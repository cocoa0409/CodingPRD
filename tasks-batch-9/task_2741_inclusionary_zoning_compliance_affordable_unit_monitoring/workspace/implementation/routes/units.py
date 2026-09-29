"""Affordable units: creation, withdraw/reinstate, deed restriction, refinance."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from services import calc, lookup, project_svc

bp = Blueprint("units", __name__)

READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
              mw.DEVELOPER, mw.RESIDENT, mw.FUND_AUDITOR)

TENURES = ("RENTAL", "OWNERSHIP")
LIVE_RESALE_STATES = ("SUBMITTED", "PRICE_APPROVED", "ROFR_WAIVED",
                      "ROFR_EXERCISED", "BUYER_CERTIFIED")

FILTER_FIELDS = ("project_id", "agreement_id", "occupant_household_id",
                 "occupancy_status", "compliance_status", "restriction_state",
                 "tenure")


def assess_substitution_fee(project):
    """Cascade L3 of a withdrawal: one whole unit equivalent priced as a
    SUBSTITUTION assessment on the project's behalf."""
    ordinance = lookup.maybe("ordinance", project.get("ordinance_id"))
    if ordinance is None:
        raise ApiError("ERR_NO_GOVERNING_ORDINANCE")
    figures = calc.in_lieu_fee_assessment(project, ordinance, "SUBSTITUTION")
    row = {
        "project_id": project["id"],
        "ordinance_id": ordinance["id"],
        "superseded_by_fee_id": None,
        "basis": "SUBSTITUTION",
        "paid_amount_cents": 0,
        "state": "ASSESSED",
        "last_payment_at": None,
    }
    row.update(figures)
    return db.insert(db.in_lieu_fees, row)


# --------------------------------------------------------------------------
@bp.route("/iz-compliance/affordable-units", methods=["POST"])
def create_unit():
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    project_id = mw.take_str(payload, "project_id")
    agreement_id = mw.take_str(payload, "agreement_id")
    unit_number = mw.take_str(payload, "unit_number", min_len=1, max_len=16)
    bedrooms = mw.take_int(payload, "bedrooms", lo=0, hi=3)
    sqft = mw.take_int(payload, "sqft", lo=200)
    tenure = mw.take_enum(payload, "tenure", TENURES)
    level_bps = mw.take_int(payload, "affordability_level_bps")
    if level_bps not in calc.AFFORDABILITY_LEVELS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'affordability_level_bps' must be 5000, 8000 or 12000.")
    market_comparable_sqft = mw.take_int(payload, "market_comparable_sqft", lo=200)

    # rung 6
    project = lookup.fetch("project", project_id)
    agreement = lookup.fetch("agreement", agreement_id)
    # rung 7
    lookup.require_project_owner(project, user_id, role)
    # rung 9
    if project.get("state") not in ("PATH_ELECTED", "AGREEMENT_RECORDED", "MONITORING"):
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Units are created only on a project that has elected a path.")
    # rung 24
    calc.check_comparability(sqft, market_comparable_sqft)
    # rung 29
    for existing in lookup.project_units(project_id):
        if existing.get("unit_number") == unit_number:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "unit_number %s already exists on this project." % unit_number)
    # rung 38
    if agreement.get("project_id") != project_id:
        raise ApiError("ERR_UNIT_PROJECT_MISMATCH")

    row = db.insert(db.units, project_svc.new_unit_row(
        project_id, agreement_id, unit_number, bedrooms, sqft, tenure,
        level_bps, market_comparable_sqft))

    project_svc.refresh(project)
    return response.created(db.public(row))


@bp.route("/iz-compliance/affordable-units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("unit", unit_id)))


@bp.route("/iz-compliance/affordable-units", methods=["GET"])
def list_units():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.units, FILTER_FIELDS)
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/affordable-units/<unit_id>/withdraw", methods=["POST"])
def withdraw_unit(unit_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    reason = mw.take_str(payload, "reason", min_len=1, max_len=500)

    unit = lookup.fetch("unit", unit_id)
    lookup.require_unit_owner_developer(unit, user_id, role)
    project = lookup.maybe("project", unit.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    if project.get("state") == "CLOSED_OUT":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "A closed-out project's units cannot be withdrawn.")
    if unit.get("occupancy_status") not in ("PLANNED", "MARKETING"):
        raise ApiError("ERR_UNIT_OCCUPANCY_STATE_INVALID",
                       "Withdrawal is permitted only from PLANNED or MARKETING.")

    # L1 -- the unit itself
    unit["occupancy_status"] = "WITHDRAWN"
    unit["withdrawn_reason"] = reason
    db.touch(unit)

    # L2 -- the onsite term drops and the posture is recomputed
    project_svc.refresh(project)

    # L3/L4 -- a shortfall on an ONSITE project is covered by a substitution fee
    if (project.get("compliance_posture") == "DEFICIENT"
            and project.get("compliance_path") == "ONSITE"):
        assess_substitution_fee(project)
        project_svc.refresh(project)

    return response.ok(db.public(unit))


@bp.route("/iz-compliance/affordable-units/<unit_id>/reinstate", methods=["POST"])
def reinstate_unit(unit_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    mw.body()

    unit = lookup.fetch("unit", unit_id)
    lookup.require_unit_owner_developer(unit, user_id, role)
    project = lookup.maybe("project", unit.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    if unit.get("occupancy_status") != "WITHDRAWN":
        raise ApiError("ERR_UNIT_OCCUPANCY_STATE_INVALID",
                       "Reinstatement is permitted only from WITHDRAWN.")

    # rung 31 / rung 47 -- oldest open substitution assessment, unpaid
    candidates = [fee for fee in lookup.project_fees(project["id"])
                  if fee.get("basis") == "SUBSTITUTION"
                  and fee.get("state") in project_svc.OPEN_FEE_STATES]
    if not candidates:
        raise ApiError("ERR_NO_SUBSTITUTION_FEE")
    target = candidates[0]
    if int(target.get("paid_amount_cents") or 0) > 0:
        raise ApiError("ERR_SUBSTITUTION_FEE_PAID")

    unit["occupancy_status"] = "PLANNED"
    unit["withdrawn_reason"] = None
    db.touch(unit)

    target["state"] = "SUPERSEDED"
    target["superseded_by_fee_id"] = None
    db.touch(target)

    project_svc.refresh(project)
    return response.ok(db.public(unit))


@bp.route("/iz-compliance/affordable-units/<unit_id>/record-restriction", methods=["POST"])
def record_restriction(unit_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    original_price = mw.take_int(payload, "original_purchase_price_cents", lo=0)
    recorded_at = mw.take_date_loose(payload, "recorded_at")

    unit = lookup.fetch("unit", unit_id)
    agreement = lookup.maybe("agreement", unit.get("agreement_id"))

    # rung 10
    if agreement is None or agreement.get("state") != "RECORDED":
        raise ApiError("ERR_AGREEMENT_NOT_RECORDED")
    # rung 11
    if unit.get("restriction_state") != "NOT_RECORDED":
        raise ApiError("ERR_UNIT_NOT_RESTRICTED",
                       "The restriction has already been recorded or released.")
    # rung 12
    if unit.get("occupancy_status") == "WITHDRAWN":
        raise ApiError("ERR_UNIT_OCCUPANCY_STATE_INVALID",
                       "A withdrawn unit carries no deed restriction.")
    # rung 27
    ami = calc.select_ami_schedule()
    # rung 53
    if unit.get("tenure") != "OWNERSHIP":
        raise ApiError("ERR_RESTRICTION_TENURE_MISMATCH")

    unit["restriction_state"] = "RECORDED"
    unit["restriction_recorded_at"] = recorded_at
    unit["original_purchase_price_cents"] = original_price
    unit["ami_income_at_purchase_cents"] = calc.current_median_for_unit(unit, ami)
    db.touch(unit)

    return response.ok(db.public(unit))


@bp.route("/iz-compliance/affordable-units/<unit_id>/release-restriction", methods=["POST"])
def release_restriction(unit_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    mw.body()
    unit = lookup.fetch("unit", unit_id)

    # rung 11
    if unit.get("restriction_state") != "RECORDED":
        raise ApiError("ERR_UNIT_NOT_RESTRICTED",
                       "Only a RECORDED restriction can be released.")
    # rung 22
    if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
        raise ApiError("ERR_UNIT_OUT_OF_COMPLIANCE")
    # rung 54
    for txn in lookup.unit_resales(unit_id):
        if txn.get("state") in LIVE_RESALE_STATES:
            raise ApiError("ERR_RESALE_IN_PROGRESS")

    unit["restriction_state"] = "RELEASED"
    db.touch(unit)
    return response.ok(db.public(unit))


@bp.route("/iz-compliance/affordable-units/<unit_id>/refinance-review", methods=["POST"])
def refinance_review(unit_id):
    user_id, role = mw.auth(mw.DEVELOPER, mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    requested = mw.take_int(payload, "requested_balance_cents", lo=0)

    unit = lookup.fetch("unit", unit_id)
    # rung 7
    lookup.require_unit_owner_developer(unit, user_id, role)
    # rung 11
    if unit.get("restriction_state") != "RECORDED":
        raise ApiError("ERR_UNIT_NOT_RESTRICTED",
                       "A refinance review requires a RECORDED restriction.")
    # rung 22
    if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
        raise ApiError("ERR_UNIT_OUT_OF_COMPLIANCE")
    # rung 27
    ami = calc.select_ami_schedule()

    agreement = lookup.maybe("agreement", unit.get("agreement_id"))
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")

    cap = calc.refinance_cap(unit, agreement, ami)
    # rung 45 -- the cap itself is inclusive
    if requested > cap:
        raise ApiError("ERR_REFINANCE_EXCEEDS_CAP")

    unit["approved_refinance_cap_cents"] = cap
    unit["last_refinance_balance_cents"] = requested
    db.touch(unit)
    return response.ok(db.public(unit))
