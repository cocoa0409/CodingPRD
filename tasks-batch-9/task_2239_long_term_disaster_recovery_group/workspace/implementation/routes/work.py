"""Construction projects, volunteer deployments and lodging (PRD 3.7, 3.8)."""

import datetime

from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    DEPLOYMENT_ACTIONS,
    DEPLOYMENT_STATUSES,
    DEPLOYMENT_TURNAROUND_DAYS,
    HOUSING_STATUSES,
    MIN_FIT_BPS,
    PROJECT_ACTIONS,
    PROJECT_STATUSES,
    ROLE_ADMIN,
    ROLE_CASE_MANAGER,
    ROLE_CONSTRUCTION,
    ROLE_OFFICER,
    ROLE_VOLUNTEER,
    SCOPE_CODES,
    SKILL_FIT_VARIANTS,
    TRADE_CODES,
    VOLUNTEER_HOURS_PER_DAY,
)
from errors import ApiError
from services import calculations as calc
from services import rollups

bp = Blueprint("work", __name__)

WOUND_DOWN_CASE_STATUSES = ("CLOSURE_PENDING", "CLOSED", "INACTIVE")
VOLUNTEER_READY_STATUSES = ("PERMITTED", "IN_PROGRESS")
LIVE_DEPLOYMENT_STATUSES = ("REQUESTED", "CONFIRMED")
OPEN_DISBURSEMENT_STATUSES = ("REQUESTED", "DOB_CLEARED", "DOB_FLAGGED", "APPROVED")
REASON_REQUIRED_ACTIONS = ("SUSPEND", "CANCEL")


# ---------------------------------------------------------------------------
# ConstructionProject
# ---------------------------------------------------------------------------
@bp.post("/construction-projects")
def create_project():
    mw.authorize((ROLE_CONSTRUCTION, ROLE_ADMIN))
    body = mw.get_body()
    case_id = mw.req_id(body, "case_id")
    scope_code = mw.req_enum(body, "scope_code", SCOPE_CODES)
    required_hours = mw.req_int_map(
        body, "required_trade_hours", TRADE_CODES, allow_empty=True
    )
    material_cents = mw.req_int(body, "estimated_material_cents", minimum=0)
    critical_trades = mw.opt_enum_list(body, "critical_trades", TRADE_CODES)
    predecessor_id = mw.opt_id(body, "predecessor_project_id")

    case = lookups.case(case_id)
    predecessor = None
    if predecessor_id is not None:
        predecessor = lookups.project(predecessor_id)
        if predecessor["case_id"] != case["id"]:
            raise ApiError("ERR_PREDECESSOR_CASE_MISMATCH")

    record = db.base_record()
    record.update(
        {
            "case_id": case["id"],
            "predecessor_project_id": predecessor_id,
            "scope_code": scope_code,
            "required_trade_hours": required_hours,
            "critical_trades": list(critical_trades),
            "estimated_material_cents": material_cents,
            "permit_number": None,
            "status": "SCOPED",
            "suspension_reason": None,
            "volunteer_hours_logged": 0,
            "confirmed_deployment_count": 0,
        }
    )
    db.projects[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/construction-projects/<pid>")
def get_project(pid):
    mw.authorize(
        (
            ROLE_CONSTRUCTION,
            ROLE_VOLUNTEER,
            ROLE_CASE_MANAGER,
            ROLE_OFFICER,
            ROLE_ADMIN,
        )
    )
    return response.object_response(lookups.project(pid))


@bp.get("/construction-projects")
def list_projects():
    mw.authorize(
        (
            ROLE_CONSTRUCTION,
            ROLE_VOLUNTEER,
            ROLE_CASE_MANAGER,
            ROLE_OFFICER,
            ROLE_ADMIN,
        )
    )
    limit, offset = mw.pagination()
    case_id = mw.query_str("case_id")
    predecessor_id = mw.query_str("predecessor_project_id")
    status = mw.query_enum("status", PROJECT_STATUSES)
    scope_code = mw.query_enum("scope_code", SCOPE_CODES)

    rows = db.sorted_records(list(db.projects.values()))
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if predecessor_id is not None:
        rows = [r for r in rows if r["predecessor_project_id"] == predecessor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if scope_code is not None:
        rows = [r for r in rows if r["scope_code"] == scope_code]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


def _live_project_deployments(project_id):
    return [
        d
        for d in rollups.project_deployments(project_id)
        if d["status"] in LIVE_DEPLOYMENT_STATUSES
    ]


@bp.post("/construction-projects/<pid>/transition")
def transition_project(pid):
    mw.authorize((ROLE_CONSTRUCTION, ROLE_ADMIN))
    body = mw.get_body()
    action = mw.req_enum(body, "action", PROJECT_ACTIONS)
    if action in REASON_REQUIRED_ACTIONS:
        reason = mw.req_str(body, "reason")
    else:
        reason = mw.opt_str(body, "reason")
    permit_number = mw.opt_str(body, "permit_number")

    project = lookups.project(pid)
    status = project["status"]

    if action == "PERMIT":
        if status != "SCOPED":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        if project["predecessor_project_id"] is not None:
            predecessor = db.projects.get(project["predecessor_project_id"])
            if predecessor is None or predecessor["status"] != "CLOSED_OUT":
                raise ApiError("ERR_PREDECESSOR_NOT_COMPLETE")
        case = db.recovery_cases.get(project["case_id"])
        if case is not None and case["case_status"] in WOUND_DOWN_CASE_STATUSES:
            raise ApiError("ERR_CASE_INVALID_STATE")
        db.set_field(project, "status", "PERMITTED")
        if permit_number is not None:
            db.set_field(project, "permit_number", permit_number)

    elif action == "START":
        if status != "PERMITTED":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "IN_PROGRESS")

    elif action == "SUSPEND":
        if status != "IN_PROGRESS":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "SUSPENDED")
        db.set_field(project, "suspension_reason", reason)
        rollups.cancel_live_deployments(project, "PROJECT_SUSPENDED")

    elif action == "RESUME":
        if status != "SUSPENDED":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "IN_PROGRESS")
        db.set_field(project, "suspension_reason", None)

    elif action == "PUNCHLIST":
        if status != "IN_PROGRESS":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        if _live_project_deployments(project["id"]):
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "PUNCHLIST")

    elif action == "CLOSE_OUT":
        if status != "PUNCHLIST":
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        open_payments = [
            d
            for d in db.disbursements.values()
            if d["project_id"] == project["id"]
            and d["status"] in OPEN_DISBURSEMENT_STATUSES
        ]
        if open_payments:
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "CLOSED_OUT")

    else:  # CANCEL
        if status not in ("SCOPED", "PERMITTED", "SUSPENDED"):
            raise ApiError("ERR_PROJECT_INVALID_TRANSITION")
        db.set_field(project, "status", "CANCELLED")
        rollups.cancel_live_deployments(project, "PROJECT_CANCELLED")

    rollups.recompute_project_counts(project)
    db.mark(project)
    return response.object_response(project)


@bp.get("/construction-projects/<pid>/skill-fit")
def project_skill_fit(pid):
    mw.authorize((ROLE_VOLUNTEER, ROLE_CONSTRUCTION, ROLE_ADMIN))
    group_id = mw.query_req_str("group_id")
    variant = mw.query_req_enum("variant", SKILL_FIT_VARIANTS)
    arrival = mw.query_req_date("arrival_date")
    departure = mw.query_req_date("departure_date")

    project = lookups.project(pid)
    group = lookups.volunteer_group(group_id)
    if departure < arrival:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    figures = calc.volunteer_skill_fit_score(project, group, arrival, departure, variant)
    payload = {
        "project_id": project["id"],
        "group_id": group["id"],
        "variant": variant,
        "day_count": figures["day_count"],
        "weighted_covered": figures["numerator"],
        "weighted_required": figures["denominator"],
        "score_bps": figures["score_bps"],
        "meets_minimum": figures["score_bps"] >= MIN_FIT_BPS,
    }
    return response.object_response(payload)


# ---------------------------------------------------------------------------
# VolunteerGroup
# ---------------------------------------------------------------------------
@bp.post("/volunteer-groups")
def create_group():
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    record = db.base_record()
    record.update(
        {
            "group_name": mw.req_str(body, "group_name"),
            "home_organization": mw.req_str(body, "home_organization"),
            "member_count": mw.req_int(body, "member_count", minimum=1),
            "skill_profile": mw.req_int_map(
                body, "skill_profile", TRADE_CODES, allow_empty=True
            ),
            "requires_housing": mw.opt_bool(body, "requires_housing", True),
            "brings_own_tools": mw.opt_bool(body, "brings_own_tools", False),
            "active_deployment_count": 0,
        }
    )
    db.volunteer_groups[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/volunteer-groups/<gid>")
def get_group(gid):
    mw.authorize((ROLE_VOLUNTEER, ROLE_CONSTRUCTION, ROLE_ADMIN))
    return response.object_response(lookups.volunteer_group(gid))


# ---------------------------------------------------------------------------
# VolunteerDeployment
# ---------------------------------------------------------------------------
@bp.post("/volunteer-deployments")
def create_deployment():
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    group_id = mw.req_id(body, "group_id")
    project_id = mw.req_id(body, "project_id")
    arrival_raw = mw.req_date(body, "arrival_date")
    departure_raw = mw.req_date(body, "departure_date")

    group = lookups.volunteer_group(group_id)
    project = lookups.project(project_id)

    if project["status"] not in VOLUNTEER_READY_STATUSES:
        raise ApiError("ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS")

    arrival = mw.as_date("arrival_date", arrival_raw)
    departure = mw.as_date("departure_date", departure_raw)
    if departure < arrival or arrival < db.clock_date():
        raise ApiError("ERR_INVALID_DATE_RANGE")

    buffer_days = datetime.timedelta(days=DEPLOYMENT_TURNAROUND_DAYS)
    for existing in db.deployments.values():
        if existing["group_id"] != group["id"]:
            continue
        if existing["status"] not in ("REQUESTED", "CONFIRMED", "COMPLETED"):
            continue
        other_arrival = calc.to_date(existing["arrival_date"])
        other_departure = calc.to_date(existing["departure_date"])
        if arrival <= other_departure + buffer_days and (
            departure + buffer_days >= other_arrival
        ):
            raise ApiError("ERR_DEPLOYMENT_WINDOW_CONFLICT")

    figures = calc.volunteer_skill_fit_score(
        project, group, arrival, departure, "COVERAGE_WEIGHTED"
    )
    if figures["score_bps"] < MIN_FIT_BPS:
        raise ApiError("ERR_SKILL_FIT_BELOW_MINIMUM")

    record = db.base_record()
    record.update(
        {
            "group_id": group["id"],
            "project_id": project["id"],
            "arrival_date": arrival_raw,
            "departure_date": departure_raw,
            "day_count": figures["day_count"],
            "crew_hours_committed": group["member_count"]
            * VOLUNTEER_HOURS_PER_DAY
            * figures["day_count"],
            "skill_fit_score_bps": figures["score_bps"],
            "status": "REQUESTED",
            "hours_logged": 0,
            "cancellation_reason": None,
        }
    )
    db.deployments[record["id"]] = record

    rollups.recompute_project_counts(project)
    rollups.recompute_group_counts(group)
    db.mark(project)
    db.mark(group)
    return response.object_response(record, 201)


@bp.get("/volunteer-deployments/<did>")
def get_deployment(did):
    mw.authorize((ROLE_VOLUNTEER, ROLE_CONSTRUCTION, ROLE_ADMIN))
    return response.object_response(lookups.deployment(did))


@bp.get("/volunteer-deployments")
def list_deployments():
    mw.authorize((ROLE_VOLUNTEER, ROLE_CONSTRUCTION, ROLE_ADMIN))
    limit, offset = mw.pagination()
    group_id = mw.query_str("group_id")
    project_id = mw.query_str("project_id")
    status = mw.query_enum("status", DEPLOYMENT_STATUSES)

    rows = db.sorted_records(list(db.deployments.values()))
    if group_id is not None:
        rows = [r for r in rows if r["group_id"] == group_id]
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


def _housing_covers(group_id, arrival, departure):
    for assignment in rollups.group_active_assignments(group_id):
        check_in = calc.to_date(assignment["check_in_date"])
        check_out = calc.to_date(assignment["check_out_date"])
        if check_in <= arrival and check_out >= departure:
            return True
    return False


@bp.post("/volunteer-deployments/<did>/transition")
def transition_deployment(did):
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    action = mw.req_enum(body, "action", DEPLOYMENT_ACTIONS)
    hours_logged = (
        mw.req_int(body, "hours_logged", minimum=0)
        if action == "COMPLETE"
        else mw.opt_int(body, "hours_logged", minimum=0)
    )
    cancellation_reason = mw.opt_str(body, "cancellation_reason")

    deployment = lookups.deployment(did)
    project = db.projects.get(deployment["project_id"])
    group = db.volunteer_groups.get(deployment["group_id"])

    if action == "CONFIRM":
        if deployment["status"] != "REQUESTED":
            raise ApiError("ERR_DEPLOYMENT_INVALID_TRANSITION")
        if project is None or project["status"] not in VOLUNTEER_READY_STATUSES:
            raise ApiError("ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS")
        if group is not None and group["requires_housing"]:
            arrival = calc.to_date(deployment["arrival_date"])
            departure = calc.to_date(deployment["departure_date"])
            if not _housing_covers(group["id"], arrival, departure):
                raise ApiError("ERR_DEPLOYMENT_INVALID_TRANSITION")
        db.set_field(deployment, "status", "CONFIRMED")

    elif action == "COMPLETE":
        if deployment["status"] != "CONFIRMED":
            raise ApiError("ERR_DEPLOYMENT_INVALID_TRANSITION")
        db.set_field(deployment, "status", "COMPLETED")
        db.set_field(deployment, "hours_logged", hours_logged)
        if project is not None:
            db.set_field(
                project,
                "volunteer_hours_logged",
                project["volunteer_hours_logged"] + hours_logged,
            )

    else:  # CANCEL
        if deployment["status"] not in LIVE_DEPLOYMENT_STATUSES:
            raise ApiError("ERR_DEPLOYMENT_INVALID_TRANSITION")
        rollups.cancel_deployment(deployment, cancellation_reason)

    rollups.recompute_project_counts(project)
    rollups.recompute_group_counts(group)
    db.mark(deployment)
    return response.object_response(deployment)


# ---------------------------------------------------------------------------
# LodgingSite
# ---------------------------------------------------------------------------
@bp.post("/lodging-sites")
def create_lodging_site():
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    capacity = mw.req_int(body, "bed_capacity", minimum=1)
    record = db.base_record()
    record.update(
        {
            "site_name": mw.req_str(body, "site_name"),
            "bed_capacity": capacity,
            "has_showers": mw.opt_bool(body, "has_showers", False),
            "nightly_cost_cents": mw.opt_int(body, "nightly_cost_cents", 0, minimum=0),
            "peak_committed_beds": 0,
            "available_beds": capacity,
            "status": "OPEN",
        }
    )
    db.lodging_sites[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/lodging-sites/<lid>")
def get_lodging_site(lid):
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    return response.object_response(lookups.lodging_site(lid))


# ---------------------------------------------------------------------------
# HousingAssignment
# ---------------------------------------------------------------------------
def _site_active_assignments(site_id):
    return [
        a
        for a in db.housing_assignments.values()
        if a["lodging_site_id"] == site_id and a["status"] == "ACTIVE"
    ]


def _capacity_conflict(site, check_in, check_out, beds):
    """Half-open per-night aggregate capacity check (PRD 3.8)."""
    existing = []
    for assignment in _site_active_assignments(site["id"]):
        other_in = calc.to_date(assignment["check_in_date"])
        other_out = calc.to_date(assignment["check_out_date"])
        if other_in < check_out and check_in < other_out:
            existing.append((other_in, other_out, assignment["beds_requested"]))

    candidate_nights = {check_in}
    for other_in, _other_out, _beds in existing:
        if check_in <= other_in < check_out:
            candidate_nights.add(other_in)

    for night in candidate_nights:
        occupied = sum(
            beds_requested
            for other_in, other_out, beds_requested in existing
            if other_in <= night < other_out
        )
        if occupied + beds > site["bed_capacity"]:
            return True
    return False


@bp.post("/housing-assignments")
def create_housing_assignment():
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    group_id = mw.req_id(body, "group_id")
    site_id = mw.req_id(body, "lodging_site_id")
    check_in_raw = mw.req_date(body, "check_in_date")
    check_out_raw = mw.req_date(body, "check_out_date")

    group = lookups.volunteer_group(group_id)
    site = lookups.lodging_site(site_id)

    check_in = mw.as_date("check_in_date", check_in_raw)
    check_out = mw.as_date("check_out_date", check_out_raw)
    if check_out <= check_in or check_in < db.clock_date():
        raise ApiError("ERR_INVALID_DATE_RANGE")

    beds = group["member_count"]
    if _capacity_conflict(site, check_in, check_out, beds):
        raise ApiError("ERR_LODGING_CAPACITY_EXCEEDED")

    record = db.base_record()
    record.update(
        {
            "group_id": group["id"],
            "lodging_site_id": site["id"],
            "check_in_date": check_in_raw,
            "check_out_date": check_out_raw,
            "beds_requested": beds,
            "night_count": (check_out - check_in).days,
            "status": "ACTIVE",
            "released_at": None,
            "release_reason": None,
        }
    )
    db.housing_assignments[record["id"]] = record

    rollups.recompute_lodging_site(site)
    db.mark(site)
    return response.object_response(record, 201)


@bp.get("/housing-assignments/<hid>")
def get_housing_assignment(hid):
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    return response.object_response(lookups.housing_assignment(hid))


@bp.get("/housing-assignments")
def list_housing_assignments():
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    limit, offset = mw.pagination()
    group_id = mw.query_str("group_id")
    site_id = mw.query_str("lodging_site_id")
    status = mw.query_enum("status", HOUSING_STATUSES)

    rows = db.sorted_records(list(db.housing_assignments.values()))
    if group_id is not None:
        rows = [r for r in rows if r["group_id"] == group_id]
    if site_id is not None:
        rows = [r for r in rows if r["lodging_site_id"] == site_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/housing-assignments/<hid>/release")
def release_housing_assignment(hid):
    mw.authorize((ROLE_VOLUNTEER, ROLE_ADMIN))
    body = mw.get_body()
    reason = mw.req_str(body, "release_reason")

    assignment = lookups.housing_assignment(hid)
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_HOUSING_ALREADY_RELEASED")

    rollups.release_housing_assignment(assignment, reason)
    db.mark(assignment)
    return response.object_response(assignment)
