"""Upgrade project endpoints (PRD §3.4)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_ACTIVE_PROJECT_EXISTS,
    ERR_AWARD_AMOUNT_INVALID,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INSUFFICIENT_FUNDS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_NOT_SELECTED,
    ERR_STALE_VERSION,
)
from helpers import (
    body_or_empty,
    get_or_404,
    paginate,
    query_filter,
    reject_unknown,
    req_enum,
    req_int,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs, domain

bp = Blueprint("upgrade_projects", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

DEVICE_CLASSES = ("PASSIVE_CROSSBUCK", "FLASHING_LIGHTS", "GATES", "FOUR_QUADRANT_GATES")
PROJECT_STATUSES = (
    "PROPOSED",
    "ELIGIBLE",
    "SELECTED",
    "AWARDED",
    "IN_PROGRESS",
    "COMPLETED",
    "WITHDRAWN",
)
NON_TERMINAL = ("PROPOSED", "ELIGIBLE", "SELECTED", "AWARDED", "IN_PROGRESS")

# Per-target role discipline (state machine actor column / PRD §3.4):
TRANSITION_ROLES = {
    "ELIGIBLE": ("RailSafetyOfficer",),
    "IN_PROGRESS": ("ProgramAdministrator",),
    "COMPLETED": ("ProgramAdministrator",),
    "WITHDRAWN": ("RailSafetyOfficer",),
}


def serialize_project(p):
    score_stale = False
    if p["priority_score"] is not None:
        crossing = store.crossings.get(p["crossing_id"])
        if crossing is not None and crossing["hazard_score"] != p["priority_score"]:
            score_stale = True
    return {
        "id": p["id"],
        "crossing_id": p["crossing_id"],
        "program_id": p["program_id"],
        "target_device_class": p["target_device_class"],
        "estimated_cost_cents": p["estimated_cost_cents"],
        "priority_score": float(p["priority_score"]) if p["priority_score"] is not None else None,
        "score_stale": score_stale,
        "tentative_award_cents": p["tentative_award_cents"],
        "awarded_cents": p["awarded_cents"],
        "federal_share_cents": p["federal_share_cents"],
        "state_share_cents": p["state_share_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/upgrade-projects")
def create_project():
    auth(["ProgramAdministrator", "RailSafetyOfficer"])
    body = body_or_empty()

    # Priority 3: body FKs left-to-right (crossing_id, then program_id).
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    program_id = body.get("program_id")
    if isinstance(program_id, str) and program_id and program_id not in store.programs:
        raise ApiError(ERR_PROGRAM_NOT_FOUND, 404, f"Funding program {program_id} does not exist")

    # Priority 4: the crossing must be ACTIVE.
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")

    # Priority 7: request shape and business constraints.
    reject_unknown(body, ("crossing_id", "program_id", "target_device_class", "estimated_cost_cents"))
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    program_id = req_str(body, "program_id")
    if program_id not in store.programs:
        raise ApiError(ERR_PROGRAM_NOT_FOUND, 404, f"Funding program {program_id} does not exist")
    crossing = store.crossings[crossing_id]
    target_device_class = req_enum(body, "target_device_class", DEVICE_CLASSES)
    estimated_cost_cents = req_int(body, "estimated_cost_cents")
    if estimated_cost_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'estimated_cost_cents' must be greater than zero")
    if target_device_class == crossing["warning_device_class"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "target_device_class must differ from the crossing's current warning_device_class")
    if any(
        p["crossing_id"] == crossing_id and p["status"] in NON_TERMINAL
        for p in store.projects.values()
    ):
        raise ApiError(ERR_ACTIVE_PROJECT_EXISTS, 409,
                       "The crossing already has a non-terminal upgrade project")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "program_id": program_id,
        "target_device_class": target_device_class,
        "estimated_cost_cents": estimated_cost_cents,
        "priority_score": None,
        "score_stale": False,
        "tentative_award_cents": None,
        "awarded_cents": None,
        "federal_share_cents": None,
        "state_share_cents": None,
        "status": "PROPOSED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.projects[rec["id"]] = rec
    return ok(serialize_project(rec), 201)


@bp.get("/upgrade-projects")
def list_projects():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    program_f = query_filter("program_id")
    status_f = query_filter("status")
    items = []
    for p in store.projects.values():
        if crossing_f is not None and p["crossing_id"] != crossing_f:
            continue
        if program_f is not None and p["program_id"] != program_f:
            continue
        if status_f is not None and p["status"] != status_f:
            continue
        items.append(p)
    items = sorted(items, key=lambda p: p["created_at"])
    page, meta = paginate([serialize_project(p) for p in items])
    return ok_list(page, meta)


@bp.get("/upgrade-projects/<project_id>")
def get_project(project_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.projects, project_id, ERR_PROJECT_NOT_FOUND,
                     f"Upgrade project {project_id} does not exist")
    return ok(serialize_project(rec))


@bp.post("/upgrade-projects/<project_id>/transition")
def transition_project(project_id):
    user_id, role = auth(["ProgramAdministrator", "RailSafetyOfficer"])
    body = body_or_empty()
    to_status = body.get("to_status")

    # Per-target role admission (priority 2) where the mapping is fixed.
    if isinstance(to_status, str) and to_status in TRANSITION_ROLES:
        if role not in TRANSITION_ROLES[to_status]:
            raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                           f"Role {role} may not drive a project to {to_status}")

    rec = get_or_404(store.projects, project_id, ERR_PROJECT_NOT_FOUND,
                     f"Upgrade project {project_id} does not exist")
    reject_unknown(body, ("to_status",))
    if not isinstance(to_status, str) or to_status not in PROJECT_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(PROJECT_STATUSES)}")

    if to_status == "ELIGIBLE":
        if rec["status"] != "PROPOSED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot nominate from {rec['status']}")
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is None or crossing["status"] != "ACTIVE":
            raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                           "The crossing is not ACTIVE")
        program = store.programs.get(rec["program_id"])
        if program is None or program["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "The funding program is not OPEN")
        # Version-pinning moment: priority_score pins the live hazard score.
        rec["priority_score"] = crossing["hazard_score"]
        rec["score_stale"] = False
        rec["status"] = "ELIGIBLE"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
        domain.recompute_eligible_demand(program)
    elif to_status == "IN_PROGRESS":
        if rec["status"] != "AWARDED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to IN_PROGRESS from {rec['status']}")
        rec["status"] = "IN_PROGRESS"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
    elif to_status == "COMPLETED":
        if rec["status"] != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to COMPLETED from {rec['status']}")
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is None or crossing["status"] != "ACTIVE":
            raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                           "The crossing is not ACTIVE")
        rec["status"] = "COMPLETED"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
        # The upgrade installs the target device class on the crossing, which
        # forces a hazard recompute and the staleness cascade.
        crossing["warning_device_class"] = rec["target_device_class"]
        old_hazard = crossing["hazard_score"]
        crossing["hazard_score"] = calcs.hazard_score(
            crossing["exposure_index"],
            domain.live_incident_count_5yr(crossing["id"]),
            crossing["school_bus_count"],
            crossing["sight_distance_rating"],
            crossing["warning_device_class"],
        )
        crossing["updated_at"] = now_iso()
        domain.run_hazard_staleness_cascade(crossing, old_hazard)
    elif to_status == "WITHDRAWN":
        if rec["status"] not in ("PROPOSED", "ELIGIBLE", "SELECTED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot withdraw from {rec['status']}")
        was_eligible = rec["status"] == "ELIGIBLE"
        if rec["status"] == "SELECTED":
            rec["tentative_award_cents"] = None
        rec["status"] = "WITHDRAWN"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
        if was_eligible:
            program = store.programs.get(rec["program_id"])
            if program is not None:
                domain.recompute_eligible_demand(program)
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    return ok(serialize_project(rec))


@bp.post("/upgrade-projects/<project_id>/award")
def award_project(project_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.projects, project_id, ERR_PROJECT_NOT_FOUND,
                     f"Upgrade project {project_id} does not exist")
    body = body_or_empty()
    program = store.programs.get(rec["program_id"])

    # Priority 4: state gates.
    if rec["status"] not in ("ELIGIBLE", "SELECTED"):
        raise ApiError(ERR_PROJECT_NOT_SELECTED, 409,
                       f"Project must be ELIGIBLE or SELECTED to award (current: {rec['status']})")
    if program is None or program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "The funding program is not OPEN or ALLOCATION_LOCKED")

    # Priority 5: OCC on the funding program version.
    expected = body.get("expected_funding_program_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != program["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           f"expected_funding_program_version {expected} does not match "
                           f"current version {program['version']}")

    # Priority 7: request shape and award bounds.
    reject_unknown(body, ("expected_funding_program_version", "award_cents"))
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'expected_funding_program_version' is required and must be an integer")
    award_cents = body.get("award_cents")
    if award_cents is not None and (not isinstance(award_cents, int) or isinstance(award_cents, bool)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'award_cents' must be an integer")
    if award_cents is None:
        effective = rec["tentative_award_cents"] if rec["status"] == "SELECTED" else rec["estimated_cost_cents"]
    else:
        effective = award_cents
    if effective < 1 or effective > rec["estimated_cost_cents"]:
        raise ApiError(ERR_AWARD_AMOUNT_INVALID, 422,
                       f"award_cents must be within [1, {rec['estimated_cost_cents']}]")

    # Priority 10: fiscal sufficiency.
    if effective > program["available_cents"]:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, 402,
                       "Effective award exceeds the program's available_cents")

    federal, state_share = calcs.match_split(effective)
    was_eligible = rec["status"] == "ELIGIBLE"
    rec["awarded_cents"] = effective
    rec["federal_share_cents"] = federal
    rec["state_share_cents"] = state_share
    rec["status"] = "AWARDED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    program["encumbered_cents"] += effective
    program["available_cents"] -= effective
    program["version"] += 1
    program["updated_at"] = now_iso()
    if was_eligible:
        domain.recompute_eligible_demand(program)
    return ok(serialize_project(rec))


@bp.post("/upgrade-projects/<project_id>/rescind-award")
def rescind_award(project_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.projects, project_id, ERR_PROJECT_NOT_FOUND,
                     f"Upgrade project {project_id} does not exist")
    body_or_empty()
    if rec["status"] != "AWARDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot rescind an award from {rec['status']}")
    program = store.programs.get(rec["program_id"])
    if program is None or program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "The funding program is not OPEN or ALLOCATION_LOCKED")

    # Compensating action: the pool is restored exactly.
    program["available_cents"] += rec["awarded_cents"]
    program["encumbered_cents"] -= rec["awarded_cents"]
    program["version"] += 1
    program["updated_at"] = now_iso()
    rec["awarded_cents"] = None
    rec["federal_share_cents"] = None
    rec["state_share_cents"] = None
    rec["status"] = "ELIGIBLE"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    domain.recompute_eligible_demand(program)
    return ok(serialize_project(rec))
