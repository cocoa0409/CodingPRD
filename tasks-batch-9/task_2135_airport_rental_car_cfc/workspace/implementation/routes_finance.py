"""Bond debt service, shuttle cost pools, capital projects/draws and true-ups."""

from flask import Blueprint, g

import calc
import serializers as ser
from domain import (agreement_or_404, apply_funding, bump, check_owner,
                    facility_or_404, release_facility_projects,
                    release_successor_projects, rows_of)
from errors import ApiError
from store import all_rows, db, get, new_row
from validation import (ALL_ROLES, body, endpoint, opt_int, opt_str, pagination,
                        paginate, q_enum, q_str, req_date, req_enum, req_int,
                        req_str)
import response as resp

bp = Blueprint("finance", __name__)

OBLIGATION_STATUSES = ("SCHEDULED", "FUNDED", "PAID", "DEFERRED")
SHUTTLE_PERIOD_STATUSES = ("OPEN", "ALLOCATED")
ALLOCATION_BASES = ("TRANSACTION_DAYS", "GROSS_REVENUE")
PROJECT_STATUSES = ("PROPOSED", "APPROVED", "FUNDED", "CLOSED", "CANCELLED")
DISBURSEMENT_STATUSES = ("REQUESTED", "AUTHORIZED", "PAID", "REJECTED", "VOIDED")
SETTLEMENT_STATUSES = ("DRAFT", "ISSUED", "DISPUTED", "SETTLED", "SUPERSEDED")


# --------------------------------------------------------------------------
# DebtServiceObligation
# --------------------------------------------------------------------------

@bp.route("/rac/debt-service-obligations", methods=["POST"])
@endpoint(["FacilityAdmin", "FinanceOfficer"])
def create_obligation():
    data = body()
    facility_id = req_str(data, "facility_id")
    series_label = req_str(data, "series_label")
    due_date = req_date(data, "due_date")
    amount_due_cents = req_int(data, "amount_due_cents", minimum=1)
    coverage_requirement_bps = opt_int(
        data, "coverage_requirement_bps", calc.DEFAULT_COVERAGE_REQUIREMENT_BPS, minimum=0)

    facility = facility_or_404(facility_id)
    row = new_row("obligations", {
        "facility_id": facility["id"],
        "series_label": series_label,
        "due_date": due_date,
        "amount_due_cents": amount_due_cents,
        "coverage_requirement_bps": coverage_requirement_bps,
        "coverage_ratio_at_funding": None,
        "funded_from_reserve_cents": 0,
        "auto_funded": False,
        "status": "SCHEDULED",
    })
    return resp.created(ser.obligation(row))


@bp.route("/rac/debt-service-obligations/<obligation_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_obligation(obligation_id):
    return resp.ok(ser.obligation(get("obligations", obligation_id,
                                      "ERR_OBLIGATION_NOT_FOUND")))


@bp.route("/rac/debt-service-obligations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_obligations():
    limit, offset = pagination()
    rows = rows_of("obligations",
                   facility_id=q_str("facility_id"),
                   status=q_enum("status", OBLIGATION_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.obligation)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/debt-service-obligations/<obligation_id>/fund", methods=["POST"])
@endpoint(["FinanceOfficer"])
def fund_obligation(obligation_id):
    row = get("obligations", obligation_id, "ERR_OBLIGATION_NOT_FOUND")
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    facility = db.facilities[row["facility_id"]]
    if not calc.coverage_passes(facility, row):
        raise ApiError("ERR_COVERAGE_BELOW_REQUIREMENT")
    apply_funding(facility, row, auto=False)
    bump(facility)
    return resp.ok(ser.obligation(row))


@bp.route("/rac/debt-service-obligations/<obligation_id>/pay", methods=["POST"])
@endpoint(["FinanceOfficer"])
def pay_obligation(obligation_id):
    row = get("obligations", obligation_id, "ERR_OBLIGATION_NOT_FOUND")
    if row["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE")
    facility = db.facilities[row["facility_id"]]
    row["status"] = "PAID"
    facility["trust_debt_service_funded_cents"] -= row["amount_due_cents"]
    facility["trust_disbursed_cents"] += row["amount_due_cents"]
    calc.recompute_bond_coverage(facility)
    bump(row)
    bump(facility)
    return resp.ok(ser.obligation(row))


# --------------------------------------------------------------------------
# ShuttleCostPeriod / ShuttleCostAllocation
# --------------------------------------------------------------------------

@bp.route("/rac/shuttle-cost-periods", methods=["POST"])
@endpoint(["FacilityAdmin", "FinanceOfficer"])
def create_shuttle_period():
    data = body()
    facility_id = req_str(data, "facility_id")
    period_year = req_int(data, "period_year", minimum=2000, maximum=2100)
    period_month = req_int(data, "period_month", minimum=1, maximum=12)
    total_cost_cents = req_int(data, "total_cost_cents", minimum=0)
    allocation_basis = req_enum(data, "allocation_basis", ALLOCATION_BASES)

    facility = facility_or_404(facility_id)
    row = new_row("shuttle_periods", {
        "facility_id": facility["id"],
        "period_year": period_year,
        "period_month": period_month,
        "total_cost_cents": total_cost_cents,
        "allocation_basis": allocation_basis,
        "total_basis_value": 0,
        "allocated_total_cents": 0,
        "line_count": 0,
        "status": "OPEN",
    })
    return resp.created(ser.shuttle_period(row))


@bp.route("/rac/shuttle-cost-periods/<shuttle_period_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_shuttle_period(shuttle_period_id):
    return resp.ok(ser.shuttle_period(
        get("shuttle_periods", shuttle_period_id, "ERR_SHUTTLE_PERIOD_NOT_FOUND")))


@bp.route("/rac/shuttle-cost-periods", methods=["GET"])
@endpoint(ALL_ROLES)
def list_shuttle_periods():
    limit, offset = pagination()
    rows = rows_of("shuttle_periods",
                   facility_id=q_str("facility_id"),
                   status=q_enum("status", SHUTTLE_PERIOD_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.shuttle_period)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/shuttle-cost-periods/<shuttle_period_id>/allocate", methods=["POST"])
@endpoint(["FinanceOfficer"])
def allocate_shuttle_period(shuttle_period_id):
    period = get("shuttle_periods", shuttle_period_id, "ERR_SHUTTLE_PERIOD_NOT_FOUND")
    if period["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    candidates = []
    for agreement in all_rows("agreements"):
        if agreement["facility_id"] != period["facility_id"]:
            continue
        if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        basis_value = 0
        for report in all_rows("reports"):
            if report["agreement_id"] != agreement["id"]:
                continue
            if report["status"] != "ACCEPTED":
                continue
            if report["period_year"] != period["period_year"]:
                continue
            if report["period_month"] != period["period_month"]:
                continue
            if period["allocation_basis"] == "TRANSACTION_DAYS":
                basis_value += report["audited_on_airport_transaction_days"] or 0
            else:
                basis_value += report["audited_gross_revenue_cents"] or 0
        if basis_value > 0:
            candidates.append({
                "agreement": agreement,
                "basis_value": basis_value,
                "_order": (agreement["created_at"], agreement["_seq"]),
            })

    total_basis_value = sum(c["basis_value"] for c in candidates)
    if not candidates or total_basis_value == 0:
        raise ApiError("ERR_NO_ALLOCATION_BASIS")

    results = calc.largest_remainder(period["total_cost_cents"], candidates,
                                     total_basis_value)

    allocated_total = 0
    for entry, (floor_cents, rank, amount_cents, share_bps) in zip(candidates, results):
        new_row("shuttle_allocations", {
            "shuttle_period_id": period["id"],
            "agreement_id": entry["agreement"]["id"],
            "basis_value": entry["basis_value"],
            "share_bps": share_bps,
            "floor_cents": floor_cents,
            "remainder_rank": rank,
            "amount_cents": amount_cents,
        }, versioned=False)
        allocated_total += amount_cents

    period["total_basis_value"] = total_basis_value
    period["allocated_total_cents"] = allocated_total
    period["line_count"] = len(candidates)
    period["status"] = "ALLOCATED"
    bump(period)
    return resp.ok(ser.shuttle_period(period))


@bp.route("/rac/shuttle-cost-allocations/<shuttle_allocation_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_shuttle_allocation(shuttle_allocation_id):
    return resp.ok(ser.shuttle_allocation(
        get("shuttle_allocations", shuttle_allocation_id,
            "ERR_SHUTTLE_ALLOCATION_NOT_FOUND")))


@bp.route("/rac/shuttle-cost-allocations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_shuttle_allocations():
    limit, offset = pagination()
    rows = rows_of("shuttle_allocations",
                   shuttle_period_id=q_str("shuttle_period_id"),
                   agreement_id=q_str("agreement_id"))
    items, limit, offset, total = paginate(rows, limit, offset, ser.shuttle_allocation)
    return resp.listing(items, limit, offset, total)


# --------------------------------------------------------------------------
# CapitalProject
# --------------------------------------------------------------------------

@bp.route("/rac/capital-projects", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_project():
    data = body()
    facility_id = req_str(data, "facility_id")
    project_name = req_str(data, "project_name")
    budget_cents = req_int(data, "budget_cents", minimum=1)
    predecessor_project_id = opt_str(data, "predecessor_project_id")

    facility = facility_or_404(facility_id)
    if predecessor_project_id is not None:
        get("projects", predecessor_project_id, "ERR_PROJECT_NOT_FOUND")

    row = new_row("projects", {
        "facility_id": facility["id"],
        "predecessor_project_id": predecessor_project_id,
        "project_name": project_name,
        "budget_cents": budget_cents,
        "disbursed_cents": 0,
        "encumbered_cents": 0,
        "draw_request_count": 0,
        "rejected_draw_count": 0,
        "funding_hold": True,
        "status": "PROPOSED",
    })
    return resp.created(ser.project(row))


@bp.route("/rac/capital-projects/<project_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_project(project_id):
    return resp.ok(ser.project(get("projects", project_id, "ERR_PROJECT_NOT_FOUND")))


@bp.route("/rac/capital-projects", methods=["GET"])
@endpoint(ALL_ROLES)
def list_projects():
    limit, offset = pagination()
    rows = rows_of("projects",
                   facility_id=q_str("facility_id"),
                   predecessor_project_id=q_str("predecessor_project_id"),
                   status=q_enum("status", PROJECT_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.project)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/capital-projects/<project_id>/approve", methods=["POST"])
@endpoint(["FacilityAdmin"])
def approve_project(project_id):
    row = get("projects", project_id, "ERR_PROJECT_NOT_FOUND")
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")
    facility = db.facilities[row["facility_id"]]
    row["status"] = "APPROVED"

    gate_clear = (facility["funded_obligation_count"] >= 1 and
                  facility["bond_coverage_status"] == "SATISFIED")
    predecessor_id = row.get("predecessor_project_id")
    if predecessor_id is not None:
        predecessor = db.projects.get(predecessor_id)
        if predecessor is None or predecessor["status"] != "CLOSED":
            gate_clear = False

    if gate_clear:
        row["funding_hold"] = False
        row["status"] = "FUNDED"
    bump(row)
    return resp.ok(ser.project(row))


@bp.route("/rac/capital-projects/<project_id>/close", methods=["POST"])
@endpoint(["FacilityAdmin"])
def close_project(project_id):
    row = get("projects", project_id, "ERR_PROJECT_NOT_FOUND")
    if row["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE")
    if row["encumbered_cents"] != 0:
        raise ApiError("ERR_PROJECT_HAS_ENCUMBRANCE")
    row["status"] = "CLOSED"
    bump(row)
    facility = db.facilities[row["facility_id"]]
    release_successor_projects(row, facility)
    return resp.ok(ser.project(row))


@bp.route("/rac/capital-projects/<project_id>/cancel", methods=["POST"])
@endpoint(["FacilityAdmin"])
def cancel_project(project_id):
    row = get("projects", project_id, "ERR_PROJECT_NOT_FOUND")
    if row["status"] not in ("PROPOSED", "APPROVED", "FUNDED"):
        raise ApiError("ERR_INVALID_STATE")
    if row["status"] in ("APPROVED", "FUNDED") and row["encumbered_cents"] != 0:
        raise ApiError("ERR_PROJECT_HAS_ENCUMBRANCE")
    row["status"] = "CANCELLED"
    bump(row)
    return resp.ok(ser.project(row))


# --------------------------------------------------------------------------
# CapitalDisbursement
# --------------------------------------------------------------------------

@bp.route("/rac/capital-disbursements", methods=["POST"])
@endpoint(["FinanceOfficer", "FacilityAdmin"])
def create_disbursement():
    data = body()
    project_id = req_str(data, "project_id")
    amount_cents = req_int(data, "amount_cents", minimum=1)
    memo = opt_str(data, "memo")
    expected_project_version = req_int(data, "expected_project_version")

    project = get("projects", project_id, "ERR_PROJECT_NOT_FOUND")

    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_VERSION")

    predecessor_id = project.get("predecessor_project_id")
    if predecessor_id is not None:
        predecessor = db.projects.get(predecessor_id)
        if predecessor is None or predecessor["status"] != "CLOSED":
            raise ApiError("ERR_PREDECESSOR_NOT_CLOSED")

    row = new_row("disbursements", {
        "project_id": project["id"],
        "amount_cents": amount_cents,
        "memo": memo,
        "requested_by_user_id": g.user_id,
        "authorized_by_user_id": None,
        "status": "REQUESTED",
    })
    project["draw_request_count"] += 1
    bump(project)
    return resp.created(ser.disbursement(row))


@bp.route("/rac/capital-disbursements/<disbursement_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_disbursement(disbursement_id):
    return resp.ok(ser.disbursement(
        get("disbursements", disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")))


@bp.route("/rac/capital-disbursements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_disbursements():
    limit, offset = pagination()
    rows = rows_of("disbursements",
                   project_id=q_str("project_id"),
                   status=q_enum("status", DISBURSEMENT_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.disbursement)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/capital-disbursements/<disbursement_id>/authorize", methods=["POST"])
@endpoint(["FinanceOfficer"])
def authorize_disbursement(disbursement_id):
    row = get("disbursements", disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id == row["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    project = db.projects[row["project_id"]]
    if project["status"] != "FUNDED":
        raise ApiError("ERR_PROJECT_NOT_FUNDED")

    facility = db.facilities[project["facility_id"]]
    if facility["bond_coverage_status"] != "SATISFIED":
        raise ApiError("ERR_BOND_COVENANT_DEFICIENT")

    if project["disbursed_cents"] + project["encumbered_cents"] + row["amount_cents"] > \
            project["budget_cents"]:
        raise ApiError("ERR_PROJECT_BUDGET_EXCEEDED")

    if facility["trust_capital_fund_cents"] < row["amount_cents"]:
        raise ApiError("ERR_CAPITAL_FUND_INSUFFICIENT")

    row["status"] = "AUTHORIZED"
    row["authorized_by_user_id"] = g.user_id
    facility["trust_capital_fund_cents"] -= row["amount_cents"]
    facility["trust_encumbered_cents"] += row["amount_cents"]
    project["encumbered_cents"] += row["amount_cents"]
    calc.recompute_bond_coverage(facility)
    bump(row)
    bump(project)
    bump(facility)
    return resp.ok(ser.disbursement(row))


@bp.route("/rac/capital-disbursements/<disbursement_id>/reject", methods=["POST"])
@endpoint(["FinanceOfficer"])
def reject_disbursement(disbursement_id):
    row = get("disbursements", disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id == row["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    project = db.projects[row["project_id"]]
    row["status"] = "REJECTED"
    project["rejected_draw_count"] += 1
    bump(row)
    bump(project)
    return resp.ok(ser.disbursement(row))


@bp.route("/rac/capital-disbursements/<disbursement_id>/pay", methods=["POST"])
@endpoint(["FinanceOfficer"])
def pay_disbursement(disbursement_id):
    row = get("disbursements", disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if row["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE")
    project = db.projects[row["project_id"]]
    facility = db.facilities[project["facility_id"]]
    row["status"] = "PAID"
    facility["trust_encumbered_cents"] -= row["amount_cents"]
    facility["trust_disbursed_cents"] += row["amount_cents"]
    project["encumbered_cents"] -= row["amount_cents"]
    project["disbursed_cents"] += row["amount_cents"]
    calc.recompute_bond_coverage(facility)
    bump(row)
    bump(project)
    bump(facility)
    return resp.ok(ser.disbursement(row))


@bp.route("/rac/capital-disbursements/<disbursement_id>/void", methods=["POST"])
@endpoint(["FinanceOfficer"])
def void_disbursement(disbursement_id):
    row = get("disbursements", disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if row["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE")
    project = db.projects[row["project_id"]]
    facility = db.facilities[project["facility_id"]]
    row["status"] = "VOIDED"
    facility["trust_encumbered_cents"] -= row["amount_cents"]
    facility["trust_capital_fund_cents"] += row["amount_cents"]
    project["encumbered_cents"] -= row["amount_cents"]
    calc.recompute_bond_coverage(facility)
    bump(row)
    bump(project)
    bump(facility)
    return resp.ok(ser.disbursement(row))


# --------------------------------------------------------------------------
# TrueUpSettlement
# --------------------------------------------------------------------------

def _accepted_reports(agreement_id):
    return [r for r in all_rows("reports")
            if r["agreement_id"] == agreement_id and r["status"] == "ACCEPTED"]


@bp.route("/rac/true-up-settlements", methods=["POST"])
@endpoint(["AuditOfficer", "FacilityAdmin"])
def create_settlement():
    data = body()
    agreement_id = req_str(data, "agreement_id")
    contract_year_index = req_int(data, "contract_year_index", minimum=1)

    agreement = agreement_or_404(agreement_id)

    for existing in all_rows("settlements"):
        if existing["agreement_id"] != agreement["id"]:
            continue
        if existing["contract_year_index"] != contract_year_index:
            continue
        if existing["status"] in ("DRAFT", "ISSUED", "DISPUTED"):
            raise ApiError("ERR_DUPLICATE_SETTLEMENT")

    if contract_year_index != agreement["contract_year_index"]:
        raise ApiError("ERR_CONTRACT_YEAR_MISMATCH")

    row = new_row("settlements", {
        "agreement_id": agreement["id"],
        "contract_year_index": contract_year_index,
        "final_percentage_rent_cents": 0,
        "mag_cents": 0,
        "rent_billed_cents": 0,
        "audit_assessment_cents": 0,
        "base_true_up_cents": 0,
        "credit_bps": 0,
        "shuttle_credit_cents": 0,
        "net_true_up_cents": 0,
        "amount_paid_cents": 0,
        "issued_by_user_id": None,
        "status": "DRAFT",
    })
    return resp.created(ser.settlement(row))


@bp.route("/rac/true-up-settlements/<settlement_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_settlement(settlement_id):
    return resp.ok(ser.settlement(
        get("settlements", settlement_id, "ERR_SETTLEMENT_NOT_FOUND")))


@bp.route("/rac/true-up-settlements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_settlements():
    limit, offset = pagination()
    rows = rows_of("settlements",
                   agreement_id=q_str("agreement_id"),
                   status=q_enum("status", SETTLEMENT_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.settlement)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/true-up-settlements/<settlement_id>/issue", methods=["POST"])
@endpoint(["AuditOfficer"])
def issue_settlement(settlement_id):
    row = get("settlements", settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    if row["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE")

    agreement = db.agreements[row["agreement_id"]]

    accepted = _accepted_reports(agreement["id"])
    for report in accepted:
        if report["audited_by_user_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for report in all_rows("reports"):
        if report["agreement_id"] != agreement["id"]:
            continue
        if report["status"] not in ("ACCEPTED", "SUPERSEDED"):
            raise ApiError("ERR_REPORTS_NOT_FINALIZED")

    final_percentage_rent_cents = calc.bps_of(agreement["gross_revenue_ytd_cents"],
                                              agreement["percentage_rent_rate_bps"])
    mag_cents = agreement["mag_annual_cents"]
    rent_billed_cents = agreement["rent_billed_to_date_cents"]
    audit_assessment_cents = sum(r["variance_assessment_cents"] for r in accepted)

    base_true_up_cents = max(mag_cents, final_percentage_rent_cents) \
        - rent_billed_cents + audit_assessment_cents
    credit_bps = calc.credit_tier_bps(base_true_up_cents)
    shuttle_credit_cents = calc.bps_of(base_true_up_cents, credit_bps)
    net_true_up_cents = base_true_up_cents - shuttle_credit_cents

    row["final_percentage_rent_cents"] = final_percentage_rent_cents
    row["mag_cents"] = mag_cents
    row["rent_billed_cents"] = rent_billed_cents
    row["audit_assessment_cents"] = audit_assessment_cents
    row["base_true_up_cents"] = base_true_up_cents
    row["credit_bps"] = credit_bps
    row["shuttle_credit_cents"] = shuttle_credit_cents
    row["net_true_up_cents"] = net_true_up_cents
    row["issued_by_user_id"] = g.user_id
    row["status"] = "ISSUED"
    bump(row)
    return resp.ok(ser.settlement(row))


@bp.route("/rac/true-up-settlements/<settlement_id>/dispute", methods=["POST"])
@endpoint(["ConcessionaireOperator"])
def dispute_settlement(settlement_id):
    row = get("settlements", settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)
    if row["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "DISPUTED"
    bump(row)
    return resp.ok(ser.settlement(row))


@bp.route("/rac/true-up-settlements/<settlement_id>/settle", methods=["POST"])
@endpoint(["FinanceOfficer"])
def settle_settlement(settlement_id):
    data = body()
    amount_paid_cents = req_int(data, "amount_paid_cents", minimum=0)

    row = get("settlements", settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    if row["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    if amount_paid_cents < row["net_true_up_cents"]:
        raise ApiError("ERR_SETTLEMENT_UNDERPAID")

    agreement = db.agreements[row["agreement_id"]]
    row["amount_paid_cents"] = amount_paid_cents
    row["status"] = "SETTLED"
    bump(row)
    if agreement["compliance_status"] == "COVENANT_BREACH":
        agreement["compliance_status"] = "COMPLIANT"
        bump(agreement)
    return resp.ok(ser.settlement(row))
