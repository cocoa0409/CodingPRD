"""Claims, claim lines, repair authorizations."""
from flask import Blueprint, request, g

from db import db
from errors import err
from middleware import require_roles
from response import ok, created, listing
import common as c

bp = Blueprint("claims", __name__)


# ===========================================================================
# Claims
# ===========================================================================
@bp.route("/claims", methods=["POST"])
@require_roles("ClaimsAdjuster", "RepairFacility")
def create_claim():
    body = c.require_body(request.get_json(silent=True))
    contract_id = c.req_field(body, "contract_id", "str")
    facility_id = c.req_field(body, "repair_facility_id", "str")
    odo = c.req_field(body, "odometer_at_claim", "int")
    claim_date = c.req_field(body, "claim_date", "str")
    complaint = c.req_field(body, "complaint", "str")
    rental_days = c.opt_field(body, "rental_days_claimed", 0, "int")
    towing = c.opt_field(body, "towing_claimed", False, "bool")
    c.non_negative(odo, "odometer_at_claim")
    c.non_negative(rental_days, "rental_days_claimed")

    contract = c.fk_or_404(db.contracts, contract_id)
    c.fk_or_404(db.repair_facilities, facility_id)

    rec = c.make_common()
    rec.update({
        "contract_id": contract_id, "repair_facility_id": facility_id,
        "reinsurance_pool_id": contract["reinsurance_pool_id"],
        "odometer_at_claim": odo, "claim_date": claim_date, "complaint": complaint,
        "requested_amount_cents": 0, "adjudicated_amount_cents": 0,
        "rental_days_claimed": rental_days, "towing_claimed": towing, "reserve_cents": 0,
        "adjudication_status": "SUBMITTED", "payment_status": "UNPAID",
    })
    db.claims[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/claims/<id>", methods=["GET"])
@require_roles("ClaimsAdjuster", "RepairFacility", "ContractAdmin", "Auditor")
def get_claim(id):
    rec = c.get_or_404(db.claims, id)
    return ok(c.public(rec))


@bp.route("/claims/<id>/lines", methods=["POST"])
@require_roles("ClaimsAdjuster", "RepairFacility")
def add_line(id):
    claim = c.get_or_404(db.claims, id)
    body = c.require_body(request.get_json(silent=True))
    line_type = c.req_field(body, "line_type", "str")
    part_number = c.opt_field(body, "part_number", None, "str")
    requested = c.opt_field(body, "requested_amount_cents", 0, "int")
    labor_hours = c.opt_field(body, "labor_hours", 0, "number")
    covered = c.opt_field(body, "covered", True, "bool")
    c.non_negative(requested, "requested_amount_cents")
    c.non_negative(labor_hours, "labor_hours")

    if line_type == "PART":
        if part_number is None:
            raise err("ERR_INVALID_CLAIM_LINE", "PART line requires part_number")
    elif line_type == "LABOR":
        if labor_hours is None or labor_hours <= 0:
            raise err("ERR_INVALID_CLAIM_LINE", "LABOR line requires positive labor_hours")
    else:
        raise err("ERR_INVALID_CLAIM_LINE", "Unknown line_type")

    rec = c.make_common()
    rec.update({
        "claim_id": id, "line_type": line_type, "part_number": part_number,
        "requested_amount_cents": requested, "labor_hours": labor_hours,
        "covered": covered, "allowed_amount_cents": 0,
    })
    db.claim_lines[rec["id"]] = rec

    # recompute claim.requested_amount_cents
    claim["requested_amount_cents"] = sum(
        l["requested_amount_cents"] for l in db.claim_lines.values() if l["claim_id"] == id
    )
    c.touch(claim)
    return created(c.public(rec))


@bp.route("/claims/<id>/lines", methods=["GET"])
@require_roles("ClaimsAdjuster", "RepairFacility", "Auditor")
def list_lines(id):
    c.get_or_404(db.claims, id)
    items = [l for l in db.claim_lines.values() if l["claim_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


def _lines_of(claim_id):
    return c.sort_created([l for l in db.claim_lines.values() if l["claim_id"] == claim_id])


@bp.route("/claims/<id>/start-review", methods=["POST"])
@require_roles("ClaimsAdjuster")
def start_review(id):
    claim = c.get_or_404(db.claims, id)
    if claim["adjudication_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim not in SUBMITTED")
    contract = db.contracts.get(claim["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Contract is not ACTIVE")
    plan = db.coverage_plans.get(contract["coverage_plan_id"])
    if claim["odometer_at_claim"] > contract["odometer_at_sale"] + plan["term_miles"]:
        raise err("ERR_MILEAGE_EXCEEDED", "Claim odometer beyond coverage")

    # claim_adjudication: round each line, then sum
    facility = db.repair_facilities.get(claim["repair_facility_id"])
    total = 0
    for line in _lines_of(id):
        if not line["covered"]:
            allowed = 0
        elif line["line_type"] == "PART":
            allowed = line["requested_amount_cents"]
        elif line["line_type"] == "LABOR":
            eff = min(facility["posted_labor_rate_cents_per_hour"],
                      plan["labor_rate_cap_cents_per_hour"])
            allowed = c.round_half_up(line["labor_hours"] * eff)
        else:
            allowed = 0
        line["allowed_amount_cents"] = allowed
        c.touch(line)
        total += allowed

    claim["adjudicated_amount_cents"] = total
    claim["adjudication_status"] = "UNDER_REVIEW"
    claim["reserve_cents"] = total
    c.touch(claim)
    c.post_ledger(claim["reinsurance_pool_id"], "RESERVE_SET", total,
                  "Reserve set on claim review", contract_id=claim["contract_id"])
    c.audit(g.user_role, "Claim", claim["id"], "CLAIM_UNDER_REVIEW")
    return ok(c.public(claim))


@bp.route("/claims/<id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve_claim(id):
    claim = c.get_or_404(db.claims, id)
    if claim["adjudication_status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim not UNDER_REVIEW")
    if claim["adjudicated_amount_cents"] == 0:
        raise err("ERR_NOTHING_COVERED", "Nothing covered")
    claim["adjudication_status"] = "APPROVED"
    c.touch(claim)
    c.audit(g.user_role, "Claim", claim["id"], "CLAIM_APPROVED")
    return ok(c.public(claim))


@bp.route("/claims/<id>/deny", methods=["POST"])
@require_roles("ClaimsAdjuster")
def deny_claim(id):
    claim = c.get_or_404(db.claims, id)
    if claim["adjudication_status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim not UNDER_REVIEW")
    reserve = claim["reserve_cents"]
    claim["adjudication_status"] = "DENIED"
    if reserve != 0:
        c.post_ledger(claim["reinsurance_pool_id"], "RESERVE_RELEASE", -reserve,
                      "Reserve release on claim denial", contract_id=claim["contract_id"])
    claim["reserve_cents"] = 0
    c.touch(claim)
    c.audit(g.user_role, "Claim", claim["id"], "CLAIM_DENIED")
    return ok(c.public(claim))


def _compute_payout(claim, plan):
    covered_repair = claim["adjudicated_amount_cents"]
    deductible = min(covered_repair, plan["deductible_cents"])
    net_repair = covered_repair - deductible
    rental_days = min(claim["rental_days_claimed"], plan["rental_max_days"])
    rental_payout = rental_days * plan["rental_benefit_cents_per_day"]
    towing_payout = plan["towing_benefit_cents"] if claim["towing_claimed"] else 0
    total = net_repair + rental_payout + towing_payout
    return covered_repair, deductible, rental_payout, towing_payout, total


@bp.route("/claims/<id>/authorize", methods=["POST"])
@require_roles("ClaimsAdjuster")
def authorize_claim(id):
    claim = c.get_or_404(db.claims, id)
    if claim["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "Claim payment_status not UNPAID")
    contract = db.contracts.get(claim["contract_id"])
    plan = db.coverage_plans.get(contract["coverage_plan_id"])
    facility = db.repair_facilities.get(claim["repair_facility_id"])
    covered_repair, deductible, rental, towing, total = _compute_payout(claim, plan)
    pay_target = "DIRECT_PAY" if facility["direct_pay_enrolled"] else "CUSTOMER_REIMBURSE"

    rec = c.make_common()
    rec.update({
        "claim_id": id, "repair_facility_id": claim["repair_facility_id"],
        "covered_repair_cents": covered_repair, "deductible_applied_cents": deductible,
        "rental_payout_cents": rental, "towing_payout_cents": towing,
        "total_payout_cents": total, "pay_target": pay_target, "status": "PENDING",
    })
    db.repair_authorizations[rec["id"]] = rec

    claim["payment_status"] = "AUTHORIZED"
    c.touch(claim)
    c.audit(g.user_role, "Claim", claim["id"], "CLAIM_AUTHORIZED")
    return created(c.public(rec))


# ===========================================================================
# Repair Authorizations
# ===========================================================================
@bp.route("/repair-authorizations/<id>", methods=["GET"])
@require_roles("ClaimsAdjuster", "RepairFacility", "Auditor")
def get_auth(id):
    rec = c.get_or_404(db.repair_authorizations, id)
    return ok(c.public(rec))


@bp.route("/claims/<id>/repair-authorizations", methods=["GET"])
@require_roles("ClaimsAdjuster", "RepairFacility", "Auditor")
def claim_auths(id):
    c.get_or_404(db.claims, id)
    items = [a for a in db.repair_authorizations.values() if a["claim_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/repair-authorizations/<id>/disburse", methods=["POST"])
@require_roles("ClaimsAdjuster")
def disburse(id):
    auth = c.get_or_404(db.repair_authorizations, id)
    if auth["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Authorization not PENDING")
    body = c.require_body(request.get_json(silent=True))
    claim = db.claims.get(auth["claim_id"])
    contract = db.contracts.get(claim["contract_id"])

    # priority order §3.7: claim approved, claim authorized, facility direct-pay, OCC
    if claim["adjudication_status"] != "APPROVED":
        raise err("ERR_CLAIM_NOT_APPROVED", "Claim is not APPROVED")
    if claim["payment_status"] != "AUTHORIZED":
        raise err("ERR_CLAIM_NOT_AUTHORIZED", "Claim payment_status is not AUTHORIZED")
    if auth["pay_target"] == "DIRECT_PAY":
        facility = db.repair_facilities.get(auth["repair_facility_id"])
        if facility["status"] != "ACTIVE" or facility["network_status"] != "IN_NETWORK":
            raise err("ERR_FACILITY_NOT_DIRECT_PAY",
                      "Facility not eligible for direct pay")
    # OCC (required field)
    expected = c.req_field(body, "expected_contract_version", "int")
    if expected != contract["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", "Contract version mismatch")

    total = auth["total_payout_cents"]
    # cascade hop 1: claim paid + reserve release
    claim["payment_status"] = "PAID"
    reserve = claim["reserve_cents"]
    if reserve != 0:
        c.post_ledger(claim["reinsurance_pool_id"], "RESERVE_RELEASE", -reserve,
                      "Reserve release on disbursement", contract_id=contract["id"])
    claim["reserve_cents"] = 0
    c.touch(claim)
    # cascade hop 2: loss paid
    c.post_ledger(claim["reinsurance_pool_id"], "LOSS_PAID", total,
                  "Loss paid on disbursement", contract_id=contract["id"])
    # cascade hop 3: contract paid_claim_total + version bump
    contract["paid_claim_total_cents"] += total
    c.touch(contract)

    auth["status"] = "DISBURSED"
    c.touch(auth)
    c.audit(g.user_role, "RepairAuthorization", auth["id"], "AUTHORIZATION_DISBURSED")
    return ok(c.public(auth))


@bp.route("/repair-authorizations/<id>/reverse", methods=["POST"])
@require_roles("ClaimsAdjuster")
def reverse(id):
    auth = c.get_or_404(db.repair_authorizations, id)
    if auth["status"] != "DISBURSED":
        raise err("ERR_INVALID_STATE", "Authorization not DISBURSED")
    claim = db.claims.get(auth["claim_id"])
    contract = db.contracts.get(claim["contract_id"])
    total = auth["total_payout_cents"]

    claim["payment_status"] = "VOID"
    c.touch(claim)
    c.post_ledger(claim["reinsurance_pool_id"], "LOSS_REVERSED", -total,
                  "Loss reversed on reversal", contract_id=contract["id"])
    contract["paid_claim_total_cents"] -= total
    c.touch(contract)

    auth["status"] = "REVERSED"
    c.touch(auth)
    c.audit(g.user_role, "RepairAuthorization", auth["id"], "AUTHORIZATION_REVERSED")
    return ok(c.public(auth))
