"""In-lieu assessments, the housing trust fund and funder reporting."""

from flask import Blueprint, request

import db
import middleware as mw
import response
from errors import ApiError, invalid
from services import calc, fund, lookup, project_svc

bp = Blueprint("fund", __name__)

FEE_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
                  mw.DEVELOPER, mw.FUND_AUDITOR)
DRAW_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.FUND_AUDITOR)

BASES = ("FULL", "FRACTIONAL", "SUBSTITUTION")
ELIGIBLE_USES = ("AFFORDABLE_HOUSING_PRODUCTION", "RENTAL_SUBSIDY",
                 "HOMEBUYER_ASSISTANCE", "ADMIN")
REPORT_BASES = ("ENTITLEMENT", "OCCUPANCY")
OPEN_REVIEW_STATES = ("FINDING_ISSUED", "CURE_SUBMITTED", "ESCALATED")


# --------------------------------------------------------------------------
# In-lieu assessments
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/in-lieu-fees", methods=["POST"])
def assess_fee():
    mw.auth(mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    project_id = mw.take_str(payload, "project_id")
    basis = mw.take_enum(payload, "basis", BASES)
    expected_project_version = mw.take_int(payload, "expected_project_version", lo=0)

    # rung 6
    project = lookup.fetch("project", project_id)
    # rung 8
    lookup.check_project_version(project, expected_project_version)
    # rung 26 -- the vintage is pinned by screening and copied onto the row
    ordinance = lookup.maybe("ordinance", project.get("ordinance_id"))
    if ordinance is None:
        raise ApiError("ERR_NO_GOVERNING_ORDINANCE")
    # rung 42 -- raised from inside the pricing pipeline
    figures = calc.in_lieu_fee_assessment(project, ordinance, basis)

    row = {
        "project_id": project_id,
        "ordinance_id": ordinance["id"],
        "superseded_by_fee_id": None,
        "basis": basis,
        "paid_amount_cents": 0,
        "state": "ASSESSED",
        "last_payment_at": None,
    }
    row.update(figures)
    fee = db.insert(db.in_lieu_fees, row)

    # A new assessment retires whatever the project had open.
    for existing in lookup.project_fees(project_id):
        if existing["id"] == fee["id"]:
            continue
        if existing.get("state") in project_svc.OPEN_FEE_STATES:
            existing["state"] = "SUPERSEDED"
            existing["superseded_by_fee_id"] = fee["id"]
            db.touch(existing)

    project_svc.refresh(project)
    return response.created(db.public(fee))


@bp.route("/iz-compliance/in-lieu-fees/<fee_id>", methods=["GET"])
def get_fee(fee_id):
    mw.auth(*FEE_READ_ROLES)
    return response.ok(db.public(lookup.fetch("fee", fee_id)))


@bp.route("/iz-compliance/in-lieu-fees", methods=["GET"])
def list_fees():
    mw.auth(*FEE_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.in_lieu_fees,
                       ("project_id", "ordinance_id", "superseded_by_fee_id",
                        "basis", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/in-lieu-fees/<fee_id>/payments", methods=["POST"])
def record_payment(fee_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    amount = mw.take_int(payload, "amount_cents", lo=1)

    fee = lookup.fetch("fee", fee_id)
    project = lookup.maybe("project", fee.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    # rung 7
    lookup.require_project_owner(project, user_id, role)
    # rung 19
    if fee.get("state") not in project_svc.OPEN_FEE_STATES:
        raise ApiError("ERR_FEE_NOT_PAYABLE")
    # rung 43
    balance = int(fee.get("assessed_amount_cents") or 0) - int(fee.get("paid_amount_cents") or 0)
    if amount > balance:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    fee["paid_amount_cents"] = int(fee.get("paid_amount_cents") or 0) + amount
    fee["last_payment_at"] = db.fmt_dt(db.logical_now())
    if amount == balance:
        fee["paid_amount_cents"] = int(fee.get("assessed_amount_cents") or 0)
        fee["state"] = "PAID"
    else:
        fee["state"] = "PARTIALLY_PAID"
    db.touch(fee)

    return response.ok(db.public(fee))


# --------------------------------------------------------------------------
# Trust-fund draws
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/trust-fund-disbursements", methods=["POST"])
def request_draw():
    user_id, _role = mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    source_fee_id = mw.take_str(payload, "source_fee_id")
    eligible_use = mw.take_enum(payload, "eligible_use", ELIGIBLE_USES)
    amount = mw.take_int(payload, "amount_cents", lo=1)

    # rung 6
    lookup.fetch("fee", source_fee_id)

    ledger = fund.ledger()
    # rung 48 -- both bounds inclusive
    if eligible_use == "ADMIN":
        if ledger["admin_committed_cents"] + amount > ledger["admin_cap_cents"]:
            raise ApiError("ERR_ADMIN_USE_CAP_EXCEEDED")
    # rung 49
    if amount > ledger["unencumbered_balance_cents"]:
        raise ApiError("ERR_INSUFFICIENT_FUND_BALANCE")

    row = db.insert(db.disbursements, {
        "source_fee_id": source_fee_id,
        "eligible_use": eligible_use,
        "amount_cents": amount,
        "state": "REQUESTED",
        "requested_by_user_id": user_id,
        "disbursed_at": None,
        "void_reason": None,
    })
    return response.created(db.public(row))


@bp.route("/iz-compliance/trust-fund-disbursements/<disbursement_id>", methods=["GET"])
def get_draw(disbursement_id):
    mw.auth(*DRAW_READ_ROLES)
    return response.ok(db.public(lookup.fetch("disbursement", disbursement_id)))


@bp.route("/iz-compliance/trust-fund-disbursements", methods=["GET"])
def list_draws():
    mw.auth(*DRAW_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.disbursements, ("source_fee_id", "eligible_use", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/trust-fund-disbursements/<disbursement_id>/disburse",
          methods=["POST"])
def disburse(disbursement_id):
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    mw.body()

    draw = lookup.fetch("disbursement", disbursement_id)
    # rung 20
    if draw.get("state") != "REQUESTED":
        raise ApiError("ERR_DISBURSEMENT_STATE_INVALID",
                       "A draw is disbursed only from REQUESTED.")
    # rung 46
    source_fee = lookup.maybe("fee", draw.get("source_fee_id"))
    if source_fee is None or source_fee.get("state") != "PAID":
        raise ApiError("ERR_SOURCE_FEE_NOT_PAID")

    draw["state"] = "DISBURSED"
    draw["disbursed_at"] = db.fmt_dt(db.logical_now())
    db.touch(draw)
    return response.ok(db.public(draw))


@bp.route("/iz-compliance/trust-fund-disbursements/<disbursement_id>/void",
          methods=["POST"])
def void_draw(disbursement_id):
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    void_reason = mw.take_str(payload, "void_reason", min_len=1, max_len=500)

    draw = lookup.fetch("disbursement", disbursement_id)
    # rung 20
    if draw.get("state") not in ("REQUESTED", "DISBURSED"):
        raise ApiError("ERR_DISBURSEMENT_STATE_INVALID",
                       "A draw is voided only from REQUESTED or DISBURSED.")

    draw["state"] = "VOIDED"
    draw["void_reason"] = void_reason
    db.touch(draw)
    return response.ok(db.public(draw))


@bp.route("/iz-compliance/trust-fund-summary", methods=["GET"])
def trust_fund_summary():
    mw.auth(*DRAW_READ_ROLES)
    return response.ok(fund.ledger())


# --------------------------------------------------------------------------
# Funder reporting
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/funder-reports", methods=["GET"])
def funder_reports():
    mw.auth(mw.FUND_AUDITOR, mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER)
    mw.pagination()

    project_id = request.args.get("project_id")
    basis = request.args.get("basis")
    if project_id is None or project_id == "":
        raise invalid("Query parameter 'project_id' is required.")
    if basis is None or basis == "":
        raise invalid("Query parameter 'basis' is required.")
    if basis not in REPORT_BASES:
        raise invalid("Query parameter 'basis' must be one of %s." % sorted(REPORT_BASES))

    project = lookup.fetch("project", project_id)

    units = [unit for unit in lookup.project_units(project_id)
             if unit.get("occupancy_status") != "WITHDRAWN"]

    total_obligation = int(project.get("total_obligation_bps") or 0)
    delivered = (int(project.get("onsite_unit_equivalents_bps") or 0)
                 + int(project.get("fee_covered_equivalents_bps") or 0))
    occupied = calc.BPS * sum(
        1 for unit in units
        if unit.get("occupancy_status") == "OCCUPIED"
        and unit.get("compliance_status") == "COMPLIANT"
    )

    numerator = delivered if basis == "ENTITLEMENT" else occupied
    if total_obligation == 0:
        compliance_ratio = calc.BPS
    else:
        compliance_ratio = calc.round_half_up(calc.BPS * numerator, total_obligation)

    open_findings = 0
    for unit in units:
        for review in lookup.unit_reviews(unit["id"]):
            if review.get("state") in OPEN_REVIEW_STATES:
                open_findings += 1

    total_assessed = 0
    total_paid = 0
    for fee_row in lookup.project_fees(project_id):
        if fee_row.get("state") != "SUPERSEDED":
            total_assessed += int(fee_row.get("assessed_amount_cents") or 0)
        total_paid += int(fee_row.get("paid_amount_cents") or 0)

    return response.ok({
        "project_id": project_id,
        "basis": basis,
        "total_obligation_bps": total_obligation,
        "delivered_equivalents_bps": delivered,
        "occupied_equivalents_bps": occupied,
        "compliance_ratio_bps": compliance_ratio,
        "open_findings_count": open_findings,
        "total_fees_assessed_cents": total_assessed,
        "total_fees_paid_cents": total_paid,
    })
