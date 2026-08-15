"""Plan routes: CRUD, publish, revise, archive, effectiveness."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_PLAN_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CURVE_TIERS_INVALID,
    ERR_PLAN_WINDOW_OVERLAP,
    ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS,
)
from middleware import authorized
from response import success_object, success_list
from util import new_entity, touch, serialize
from validate import (
    get_body, req_str, opt_str, req_int, opt_int, opt_nullable_int,
    req_enum, opt_enum, req_date, parse_pagination, require_path_resource,
)
from services.calculations import plan_effectiveness

bp = Blueprint("plans", __name__)

ADMIN_ONLY = ["CompAdmin"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]
ATTAINMENT_MODES = {"DIRECT_ONLY", "INCLUDE_ROLLUP"}


def _parse_curve_tiers(body, required=True):
    """Parse and validate curve_tiers from request body."""
    tiers_raw = body.get("curve_tiers")
    if tiers_raw is None:
        if required:
            raise_error(ERR_INVALID_REQUEST, "missing required field: curve_tiers")
        return None
    if not isinstance(tiers_raw, list):
        raise_error(ERR_INVALID_REQUEST, "curve_tiers must be an array")
    parsed = []
    for t in tiers_raw:
        if not isinstance(t, dict):
            raise_error(ERR_INVALID_REQUEST, "each tier must be an object")
        floor = t.get("attainment_floor_bps")
        rate = t.get("rate_bps")
        if floor is None or isinstance(floor, bool) or not isinstance(floor, int):
            raise_error(ERR_INVALID_REQUEST, "tier attainment_floor_bps must be an integer")
        if rate is None or isinstance(rate, bool) or not isinstance(rate, int):
            raise_error(ERR_INVALID_REQUEST, "tier rate_bps must be an integer")
        parsed.append({"attainment_floor_bps": floor, "rate_bps": rate})
    _validate_curve_tiers(parsed)
    return parsed


def _validate_curve_tiers(tiers):
    """Validate curve tier business rules (ERR_CURVE_TIERS_INVALID)."""
    if len(tiers) == 0:
        raise_error(ERR_CURVE_TIERS_INVALID, "curve_tiers must be non-empty")
    if tiers[0]["attainment_floor_bps"] != 0:
        raise_error(ERR_CURVE_TIERS_INVALID, "first attainment_floor_bps must be 0")
    for i in range(1, len(tiers)):
        if tiers[i]["attainment_floor_bps"] <= tiers[i - 1]["attainment_floor_bps"]:
            raise_error(ERR_CURVE_TIERS_INVALID, "attainment_floor_bps must be strictly ascending")
    for t in tiers:
        if t["rate_bps"] < 0:
            raise_error(ERR_CURVE_TIERS_INVALID, "rate_bps must be >= 0")


def _check_plan_window_overlap(program_id, start_date, end_date, exclude_plan_id=None):
    """Closed-interval overlap: shared boundary counts as collision."""
    for p in db["plans"].values():
        if p["program_id"] != program_id:
            continue
        if p["status"] == "ARCHIVED":
            continue
        if exclude_plan_id and p["id"] == exclude_plan_id:
            continue
        # Closed interval [start, end] overlap: NOT (new_end < existing_start OR new_start > existing_end)
        if not (end_date < p["effective_start_date"] or start_date > p["effective_end_date"]):
            raise_error(ERR_PLAN_WINDOW_OVERLAP,
                        f"plan window [{start_date}, {end_date}] overlaps with existing plan {p['id']}")


@bp.route("/plans", methods=["POST"])
def create_plan():
    caller = authorized(ADMIN_ONLY)
    body = get_body()

    # Basic field validation
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    start_date = req_date(body, "effective_start_date")
    end_date = req_date(body, "effective_end_date")
    curve_tiers = _parse_curve_tiers(body, required=True)
    attainment_mode = opt_enum(body, "attainment_mode", ATTAINMENT_MODES, "DIRECT_ONLY")
    rollup_rate_bps = opt_int(body, "rollup_rate_bps", 0)
    payout_cap_cents = opt_nullable_int(body, "payout_cap_cents", None)

    if rollup_rate_bps < 0:
        raise_error(ERR_INVALID_REQUEST, "rollup_rate_bps must be >= 0")
    if payout_cap_cents is not None and payout_cap_cents <= 0:
        raise_error(ERR_INVALID_REQUEST, "payout_cap_cents must be > 0 or null")

    # Priority 3: existence
    program = db["programs"].get(program_id)
    if program is None:
        raise_error(ERR_NOT_FOUND, f"program not found: {program_id}")

    # Priority 6: temporal — end >= start (closed interval)
    if end_date < start_date:
        raise_error(ERR_INVALID_REQUEST, "effective_end_date must be >= effective_start_date")

    # Priority 7: structural — window overlap
    _check_plan_window_overlap(program_id, start_date, end_date)

    plan = new_entity({
        "program_id": program_id,
        "name": name,
        "effective_start_date": start_date,
        "effective_end_date": end_date,
        "curve_tiers": curve_tiers,
        "attainment_mode": attainment_mode,
        "rollup_rate_bps": rollup_rate_bps,
        "payout_cap_cents": payout_cap_cents,
        "document_version": 1,
        "created_by_user_id": caller.user_id,
        "status": "DRAFT",
    })
    db["plans"][plan["id"]] = plan
    return success_object(serialize(plan), 201)


@bp.route("/plans/<planId>", methods=["GET"])
def get_plan(planId):
    caller = authorized(ALL_ROLES)
    plan = require_path_resource("plans", planId)
    return success_object(serialize(plan))


@bp.route("/plans", methods=["GET"])
def list_plans():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["plans"].values())
    # Filters
    program_id = None
    status_filter = None
    from flask import request
    program_id = request.args.get("program_id")
    status_filter = request.args.get("status")

    if program_id:
        items = [p for p in items if p["program_id"] == program_id]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]

    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.route("/plans/<planId>/publish", methods=["POST"])
def publish_plan(planId):
    caller = authorized(ADMIN_ONLY)
    plan = require_path_resource("plans", planId)

    # Priority 4: state precondition
    if plan["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"plan is {plan['status']}, must be DRAFT to publish")

    # Priority 5: segregation of duties
    if caller.user_id == plan["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "publisher must differ from plan creator")

    # Re-validate curve tiers at publish
    _validate_curve_tiers(plan["curve_tiers"])

    plan["status"] = "PUBLISHED"
    touch(plan)
    return success_object(serialize(plan))


@bp.route("/plans/<planId>/revise", methods=["POST"])
def revise_plan(planId):
    caller = authorized(ADMIN_ONLY)
    body = get_body()
    plan = require_path_resource("plans", planId)

    # Priority 4: state precondition (before OCC per concurrency_rules)
    if plan["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"plan is {plan['status']}, must be PUBLISHED to revise")

    # OCC check (after state precondition)
    expected_plan_version = req_int(body, "expected_plan_version")
    if expected_plan_version != plan["version"]:
        raise_error(ERR_STALE_PLAN_VERSION,
                    f"expected_plan_version {expected_plan_version} != current {plan['version']}")

    # Priority 5: segregation of duties
    if caller.user_id == plan["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "reviser must differ from plan creator")

    # Optional field updates
    new_curve_tiers = _parse_curve_tiers(body, required=False)
    if new_curve_tiers is not None:
        plan["curve_tiers"] = new_curve_tiers

    new_cap = opt_nullable_int(body, "payout_cap_cents")
    if "payout_cap_cents" in body:
        if new_cap is not None and new_cap <= 0:
            raise_error(ERR_INVALID_REQUEST, "payout_cap_cents must be > 0 or null")
        plan["payout_cap_cents"] = new_cap

    new_rollup = opt_int(body, "rollup_rate_bps")
    if new_rollup is not None:
        if new_rollup < 0:
            raise_error(ERR_INVALID_REQUEST, "rollup_rate_bps must be >= 0")
        plan["rollup_rate_bps"] = new_rollup

    new_mode = opt_enum(body, "attainment_mode", ATTAINMENT_MODES)
    if new_mode is not None:
        plan["attainment_mode"] = new_mode

    # Increment document_version and plan version
    plan["document_version"] += 1
    touch(plan)

    # Cascade: ACTIVE assignments revert to OFFERED
    for a in db["assignments"].values():
        if a["plan_id"] == planId and a["status"] == "ACTIVE":
            if a["acceptance_status"] in ("ACCEPTED", "DECLINED"):
                a["acceptance_status"] = "OFFERED"
                touch(a)

    return success_object(serialize(plan))


@bp.route("/plans/<planId>/archive", methods=["POST"])
def archive_plan(planId):
    caller = authorized(ADMIN_ONLY)
    plan = require_path_resource("plans", planId)

    # Priority 4: state — must be DRAFT or PUBLISHED
    if plan["status"] == "ARCHIVED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "plan is already ARCHIVED")

    # Priority 7: no ACTIVE assignments
    active = [
        a for a in db["assignments"].values()
        if a["plan_id"] == planId and a["status"] == "ACTIVE"
    ]
    if active:
        raise_error(ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS,
                    "plan has ACTIVE assignments")

    plan["status"] = "ARCHIVED"
    touch(plan)
    return success_object(serialize(plan))


@bp.route("/plans/<planId>/effectiveness", methods=["GET"])
def get_plan_effectiveness(planId):
    caller = authorized(ALL_ROLES)
    plan = require_path_resource("plans", planId)
    result = plan_effectiveness(planId)
    return success_object(result)
