"""Marketing plans, lottery events and households."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from services import calc, lookup

bp = Blueprint("marketing", __name__)

BROAD_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
                    mw.DEVELOPER, mw.RESIDENT, mw.FUND_AUDITOR)
HOUSEHOLD_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
                        mw.RESIDENT, mw.FUND_AUDITOR)

PREFERENCE_CATEGORIES = ("LIVE_WORK", "DISPLACED", "PUBLIC_EMPLOYEE")
LIVE_PLAN_STATES = ("SUBMITTED", "APPROVED", "REVISION_REQUESTED")
REVIEW_DECISIONS = ("APPROVE", "REQUEST_REVISION")


def _check_window(project_id, open_at, close_at, exclude_plan_id=None):
    # rung 32 -- strictly ordered endpoints
    if db.parse_dt(open_at) >= db.parse_dt(close_at):
        raise ApiError("ERR_INVALID_MARKETING_WINDOW")
    # rung 33 -- half-open overlap against live plans of the same project
    for existing in lookup.project_plans(project_id):
        if exclude_plan_id is not None and existing["id"] == exclude_plan_id:
            continue
        if existing.get("state") not in LIVE_PLAN_STATES:
            continue
        if calc.windows_overlap(db.parse_dt(open_at), db.parse_dt(close_at),
                                db.parse_dt(existing.get("lottery_open_at")),
                                db.parse_dt(existing.get("lottery_close_at"))):
            raise ApiError("ERR_MARKETING_WINDOW_OVERLAP")


# --------------------------------------------------------------------------
# Marketing plans
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/marketing-plans", methods=["POST"])
def create_plan():
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    project_id = mw.take_str(payload, "project_id")
    open_at = mw.take_datetime(payload, "lottery_open_at")
    close_at = mw.take_datetime(payload, "lottery_close_at")
    categories = mw.take_str_set(payload, "preference_categories",
                                 PREFERENCE_CATEGORIES, required=False, default=[])

    project = lookup.fetch("project", project_id)
    lookup.require_project_owner(project, user_id, role)
    _check_window(project_id, open_at, close_at)

    row = db.insert(db.marketing_plans, {
        "project_id": project_id,
        "lottery_open_at": open_at,
        "lottery_close_at": close_at,
        "preference_categories": categories,
        "state": "SUBMITTED",
        "revision_round": 0,
        "reviewed_by_user_id": None,
        "review_note": None,
    })
    return response.created(db.public(row))


@bp.route("/iz-compliance/marketing-plans/<marketing_plan_id>", methods=["GET"])
def get_plan(marketing_plan_id):
    mw.auth(*BROAD_READ_ROLES)
    return response.ok(db.public(lookup.fetch("marketing_plan", marketing_plan_id)))


@bp.route("/iz-compliance/marketing-plans", methods=["GET"])
def list_plans():
    mw.auth(*BROAD_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.marketing_plans, ("project_id", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/marketing-plans/<marketing_plan_id>/review", methods=["POST"])
def review_plan(marketing_plan_id):
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    decision = mw.take_enum(payload, "decision", REVIEW_DECISIONS)
    review_note = mw.take_str(payload, "review_note", required=False, min_len=0,
                              max_len=1000, default=None)

    plan = lookup.fetch("marketing_plan", marketing_plan_id)
    project = lookup.maybe("project", plan.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")

    # rung 13
    if plan.get("state") != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "Only a SUBMITTED marketing plan can be reviewed.")

    if decision == "APPROVE":
        # rung 50
        if project.get("state") != "AGREEMENT_RECORDED":
            raise ApiError("ERR_PROJECT_NOT_READY_FOR_MARKETING")
        if project.get("compliance_posture") == "UNDER_ENFORCEMENT":
            raise ApiError("ERR_PROJECT_NOT_READY_FOR_MARKETING")

        plan["state"] = "APPROVED"
        plan["reviewed_by_user_id"] = user_id
        plan["review_note"] = review_note
        db.touch(plan)

        for unit in lookup.project_units(project["id"]):
            if unit.get("occupancy_status") == "PLANNED":
                unit["occupancy_status"] = "MARKETING"
                db.touch(unit)
    else:
        plan["state"] = "REVISION_REQUESTED"
        plan["reviewed_by_user_id"] = user_id
        plan["review_note"] = review_note
        db.touch(plan)

    return response.ok(db.public(plan))


@bp.route("/iz-compliance/marketing-plans/<marketing_plan_id>/resubmit", methods=["POST"])
def resubmit_plan(marketing_plan_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    open_at = mw.take_datetime(payload, "lottery_open_at")
    close_at = mw.take_datetime(payload, "lottery_close_at")
    categories = mw.take_str_set(payload, "preference_categories",
                                 PREFERENCE_CATEGORIES, required=False, default=[])

    plan = lookup.fetch("marketing_plan", marketing_plan_id)
    project = lookup.maybe("project", plan.get("project_id"))
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    lookup.require_project_owner(project, user_id, role)

    # rung 13
    if plan.get("state") != "REVISION_REQUESTED":
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "Only a REVISION_REQUESTED plan can be resubmitted.")

    _check_window(plan["project_id"], open_at, close_at, exclude_plan_id=plan["id"])

    plan["lottery_open_at"] = open_at
    plan["lottery_close_at"] = close_at
    plan["preference_categories"] = categories
    plan["revision_round"] = int(plan.get("revision_round") or 0) + 1
    plan["state"] = "SUBMITTED"
    db.touch(plan)

    return response.ok(db.public(plan))


# --------------------------------------------------------------------------
# Lottery events
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/lottery-events", methods=["POST"])
def create_event():
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    plan_id = mw.take_str(payload, "marketing_plan_id")
    units_offered = mw.take_int(payload, "units_offered", lo=1)
    level_bps = mw.take_int(payload, "eligibility_level_bps")
    if level_bps not in calc.AFFORDABILITY_LEVELS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'eligibility_level_bps' must be 5000, 8000 or 12000.")

    plan = lookup.fetch("marketing_plan", plan_id)
    if plan.get("state") != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "A lottery round requires an APPROVED marketing plan.")

    row = db.insert(db.lottery_events, {
        "marketing_plan_id": plan_id,
        "units_offered": units_offered,
        "eligibility_level_bps": level_bps,
        "state": "PENDING",
        "round_seq": 1,
        "drawn_at": None,
        "drawn_by_user_id": None,
        "selected_household_ids": [],
        "waitlisted_household_ids": [],
        "redraw_reason": None,
    })
    return response.created(db.public(row))


@bp.route("/iz-compliance/lottery-events/<lottery_event_id>", methods=["GET"])
def get_event(lottery_event_id):
    mw.auth(*BROAD_READ_ROLES)
    return response.ok(db.public(lookup.fetch("lottery_event", lottery_event_id)))


@bp.route("/iz-compliance/lottery-events", methods=["GET"])
def list_events():
    mw.auth(*BROAD_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.lottery_events, ("marketing_plan_id", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/lottery-events/<lottery_event_id>/draw", methods=["POST"])
def draw_event(lottery_event_id):
    user_id, _role = mw.auth(mw.PROGRAM_ADMINISTRATOR)
    mw.body()

    event = lookup.fetch("lottery_event", lottery_event_id)
    plan = lookup.maybe("marketing_plan", event.get("marketing_plan_id"))
    if plan is None:
        raise ApiError("ERR_MARKETING_PLAN_NOT_FOUND")

    # rung 13
    if plan.get("state") != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "A draw requires the plan to be APPROVED.")
    # rung 14
    if event.get("state") != "PENDING":
        raise ApiError("ERR_LOTTERY_STATE_INVALID",
                       "A draw is permitted only from PENDING.")
    # rung 27
    ami = calc.select_ami_schedule()
    # rung 30
    pool = calc.eligible_pool(event, plan, ami)
    if not pool:
        raise ApiError("ERR_EMPTY_ELIGIBLE_POOL")
    # rung 55
    now = db.logical_now()
    if now < db.parse_dt(plan.get("lottery_close_at")):
        raise ApiError("ERR_APPLICATION_WINDOW_OPEN")

    ranked = calc.rank_pool(pool, plan)
    units_offered = int(event.get("units_offered") or 0)

    selected = []
    waitlisted = []
    for index, (score, household) in enumerate(ranked):
        household["preference_score"] = score
        household["rank_position"] = index + 1
        if index < units_offered:
            household["state"] = "SELECTED"
            selected.append(household)
        else:
            household["state"] = "WAITLISTED"
            waitlisted.append(household)
        db.touch(household)

    event["selected_household_ids"] = [h["id"] for h in selected]
    event["waitlisted_household_ids"] = [h["id"] for h in waitlisted]
    event["state"] = "DRAWN"
    event["drawn_at"] = db.fmt_dt(now)
    event["drawn_by_user_id"] = user_id
    db.touch(event)

    marketing_units = [unit for unit in lookup.project_units(plan["project_id"])
                       if unit.get("occupancy_status") == "MARKETING"]
    marketing_units.sort(key=lambda u: str(u.get("unit_number") or ""))
    for unit, household in zip(marketing_units, selected):
        unit["occupancy_status"] = "RESERVED"
        unit["occupant_household_id"] = household["id"]
        db.touch(unit)

    plan["state"] = "CLOSED"
    db.touch(plan)

    return response.ok(db.public(event))


@bp.route("/iz-compliance/lottery-events/<lottery_event_id>/redraw", methods=["POST"])
def redraw_event(lottery_event_id):
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    reason = mw.take_str(payload, "reason", min_len=1, max_len=500)

    event = lookup.fetch("lottery_event", lottery_event_id)
    plan = lookup.maybe("marketing_plan", event.get("marketing_plan_id"))
    if plan is None:
        raise ApiError("ERR_MARKETING_PLAN_NOT_FOUND")

    # rung 14
    if event.get("state") != "DRAWN":
        raise ApiError("ERR_LOTTERY_STATE_INVALID",
                       "A redraw is permitted only from DRAWN.")
    # rung 30
    ami = calc.active_ami_or_none()
    if ami is None:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    if not calc.eligible_pool(event, plan, ami):
        raise ApiError("ERR_EMPTY_ELIGIBLE_POOL")
    # rung 56
    for household_id in (event.get("selected_household_ids") or []):
        household = lookup.maybe("household", household_id)
        if household is not None and household.get("state") == "CERTIFIED":
            raise ApiError("ERR_REDRAW_AFTER_CERTIFICATION")

    cleared = set(event.get("selected_household_ids") or [])

    event["round_seq"] = int(event.get("round_seq") or 0) + 1
    event["state"] = "PENDING"
    event["selected_household_ids"] = []
    event["waitlisted_household_ids"] = []
    event["redraw_reason"] = reason
    db.touch(event)

    for household in lookup.event_households(event["id"]):
        if household.get("state") in ("SELECTED", "WAITLISTED"):
            household["state"] = "APPLIED"
            household["rank_position"] = None
            db.touch(household)

    for unit in lookup.project_units(plan["project_id"]):
        if (unit.get("occupancy_status") == "RESERVED"
                and unit.get("occupant_household_id") in cleared):
            unit["occupancy_status"] = "MARKETING"
            unit["occupant_household_id"] = None
            db.touch(unit)

    return response.ok(db.public(event))


# --------------------------------------------------------------------------
# Households
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/households", methods=["POST"])
def create_household():
    mw.auth(mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    applicant_name = mw.take_str(payload, "applicant_name", min_len=1, max_len=120)
    household_size = mw.take_int(payload, "household_size", lo=1, hi=5)
    income = mw.take_int(payload, "gross_annual_income_cents", lo=0)

    row = db.insert(db.households, {
        "applicant_name": applicant_name,
        "household_size": household_size,
        "gross_annual_income_cents": income,
        "preference_claims": [],
        "lottery_event_id": None,
        "state": "REGISTERED",
        "preference_score": 0,
        "rank_position": None,
    })
    return response.created(db.public(row))


@bp.route("/iz-compliance/households/<household_id>", methods=["GET"])
def get_household(household_id):
    mw.auth(*HOUSEHOLD_READ_ROLES)
    return response.ok(db.public(lookup.fetch("household", household_id)))


@bp.route("/iz-compliance/households", methods=["GET"])
def list_households():
    mw.auth(*HOUSEHOLD_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.households, ("lottery_event_id", "state"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/households/<household_id>/apply", methods=["POST"])
def apply_household(household_id):
    user_id, role = mw.auth(mw.RESIDENT)
    payload = mw.body()
    event_id = mw.take_str(payload, "lottery_event_id")
    claims = mw.take_str_set(payload, "preference_claims", PREFERENCE_CATEGORIES,
                             required=False, default=[])

    household = lookup.fetch("household", household_id)
    event = lookup.fetch("lottery_event", event_id)
    lookup.require_household_self(household, user_id, role)

    plan = lookup.maybe("marketing_plan", event.get("marketing_plan_id"))
    if plan is None:
        raise ApiError("ERR_MARKETING_PLAN_NOT_FOUND")

    # rung 13
    if plan.get("state") != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "Applications require an APPROVED marketing plan.")
    # rung 14
    if event.get("state") != "PENDING":
        raise ApiError("ERR_LOTTERY_STATE_INVALID",
                       "Applications are accepted only while the round is PENDING.")
    # rung 15
    if household.get("state") != "REGISTERED":
        raise ApiError("ERR_HOUSEHOLD_STATE_INVALID",
                       "Only a REGISTERED household may apply.")
    # rung 34 -- half-open window
    now = db.logical_now()
    open_at = db.parse_dt(plan.get("lottery_open_at"))
    close_at = db.parse_dt(plan.get("lottery_close_at"))
    if not (open_at <= now < close_at):
        raise ApiError("ERR_APPLICATION_WINDOW_CLOSED")

    household["lottery_event_id"] = event_id
    household["preference_claims"] = claims
    household["preference_score"] = calc.preference_score(
        claims, plan.get("preference_categories"))
    household["state"] = "APPLIED"
    db.touch(household)

    return response.ok(db.public(household))
