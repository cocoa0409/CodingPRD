"""Standpipes, cooking hoods and special hazard systems (PRD 3.5)."""
from flask import Blueprint

import calc_aux
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import fmt_dt, parse_dt

bp = Blueprint("aux_systems", __name__)

MAX_CONCURRENT_OTHER_OUTAGES = 2
COMMISSIONABLE_STATUSES = ("PROPOSED", "DECOMMISSIONED_PENDING_RETEST")
WITHDRAWABLE_STATUSES = ("PROPOSED", "DECOMMISSIONED_PENDING_RETEST")

REQUIRED_BY_TYPE = {
    "STANDPIPE_CLASS_I": ["riser_count"],
    "STANDPIPE_CLASS_II": ["riser_count"],
    "COOKING": ["appliance_count"],
    "IN_RACK": ["in_rack_head_count", "hazard_area_id"],
    "FOAM_DELUGE": ["protected_area_sqft"],
    "HAZMAT_DELUGE": ["protected_area_sqft"],
}


@bp.post("/auxiliary-systems")
def create_aux_system():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    area = guards.must_fk("hazard_area", validate.raw_fk(data, "hazard_area_id"))
    guards.require_lead_engineer(actor, project)
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "hazard_area_id": validate.opt_str(data, "hazard_area_id", default=None),
        "system_type": validate.req_str(data, "system_type", enum=calc_aux.SYSTEM_TYPES),
        "label": validate.req_str(data, "label"),
        "riser_count": validate.opt_int(data, "riser_count", ge=1, default=None),
        "appliance_count": validate.opt_int(data, "appliance_count", ge=1, default=None),
        "water_wash_enabled": validate.opt_bool(data, "water_wash_enabled", default=False),
        "in_rack_head_count": validate.opt_int(data, "in_rack_head_count", ge=1, default=None),
        "protected_area_sqft": validate.opt_num(data, "protected_area_sqft", gt=0, default=None),
        "agent_type": validate.opt_str(
            data, "agent_type", enum=calc_aux.AGENT_TYPES, default="NONE"
        ),
    }

    # step 10: the conditional fields demanded by system_type
    for field in REQUIRED_BY_TYPE[row["system_type"]]:
        if row.get(field) is None:
            raise ApiError(
                "ERR_SYSTEM_TYPE_FIELD_REQUIRED",
                "Field '%s' is required for system_type %s." % (field, row["system_type"]),
            )
    guards.require_not_frozen(project)
    # step 29: an in-rack system's area must store a qualifying commodity
    if row["system_type"] == "IN_RACK":
        if area["commodity_class"] not in calc_aux.QUALIFYING_IN_RACK_COMMODITIES:
            raise ApiError(
                "ERR_IN_RACK_HAZARD_MISMATCH",
                "An IN_RACK system requires a hazard area storing CLASS_IV or GROUP_A_PLASTIC commodity.",
            )

    row["demand_gpm"] = calc_aux.demand_gpm(row["system_type"], row, project)
    row["interlock_required"] = calc_aux.interlock_required(row["system_type"])
    row["interlock_verified"] = False
    row["outage_start_at"] = None
    row["outage_end_at"] = None
    row["status"] = "PROPOSED"
    db.stamp_create(row)
    db.aux_systems[row["id"]] = row

    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))


@bp.get("/auxiliary-systems/<system_id>")
def get_aux_system(system_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("aux", system_id)))


@bp.get("/auxiliary-systems")
def list_aux_systems():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.aux_systems.values()),
        ["project_id", "hazard_area_id", "system_type", "status"],
    )
    return helpers.list_response(rows)


def _outage_concurrency_exceeded(project_id, candidate_id, start, end):
    """Half-open overlap; at most one other outage may be in flight at any instant."""
    others = []
    for system in ledger.aux_systems_of(project_id):
        if system["id"] == candidate_id or system["status"] != "COMMISSIONED":
            continue
        other_start = parse_dt(system.get("outage_start_at"))
        other_end = parse_dt(system.get("outage_end_at"))
        if other_start is None or other_end is None:
            continue
        # half-open intervals: touching endpoints do not overlap
        if other_start < end and start < other_end:
            others.append((max(other_start, start), min(other_end, end)))
    for instant, _ in others:
        overlapping = len([1 for s, e in others if s <= instant < e])
        if overlapping >= MAX_CONCURRENT_OTHER_OUTAGES:
            return True
    return False


@bp.post("/auxiliary-systems/<system_id>/commission")
def commission(system_id):
    authenticate(["Contractor"])
    system = guards.must("aux", system_id)
    project = guards.must("project", system["project_id"])
    data = validate.body()
    start = validate.req_dt(data, "outage_start_at")
    end = validate.req_dt(data, "outage_end_at")
    verified = validate.opt_bool(data, "interlock_verified", default=False)

    guards.require_not_frozen(project)
    if system["status"] == "WITHDRAWN":
        guards.terminal("The auxiliary system is WITHDRAWN and may not be commissioned.")
    if system["status"] not in COMMISSIONABLE_STATUSES:
        guards.invalid_transition(
            "No commissioning is declared for a system in status %s." % system["status"]
        )
    # step 19: the interlock, then step 38: the window bounds
    if system["interlock_required"] and not verified:
        raise ApiError(
            "ERR_INTERLOCK_NOT_VERIFIED",
            "This system type may not be commissioned without a verified interlock.",
        )
    if not start < end:
        raise ApiError(
            "ERR_WINDOW_START_NOT_BEFORE_END",
            "outage_start_at must be strictly before outage_end_at.",
        )
    if _outage_concurrency_exceeded(project["id"], system["id"], start, end):
        raise ApiError(
            "ERR_OUTAGE_CONCURRENCY_EXCEEDED",
            "The outage window exceeds the project's concurrent-outage capacity.",
        )

    system["outage_start_at"] = fmt_dt(start)
    system["outage_end_at"] = fmt_dt(end)
    system["interlock_verified"] = verified
    system["status"] = "COMMISSIONED"
    db.touch(system)
    return response.ok(response.public(system))


@bp.post("/auxiliary-systems/<system_id>/withdraw")
def withdraw(system_id):
    actor = authenticate(["DesignEngineer"])
    system = guards.must("aux", system_id)
    project = guards.must("project", system["project_id"])
    guards.require_lead_engineer(actor, project)
    data = validate.body()
    validate.opt_str(data, "withdraw_note")

    guards.require_not_frozen(project)
    if system["status"] == "WITHDRAWN":
        guards.terminal("The auxiliary system is already WITHDRAWN.")
    if system["status"] not in WITHDRAWABLE_STATUSES:
        guards.invalid_transition(
            "No withdrawal is declared for a system in status %s." % system["status"]
        )

    system["status"] = "WITHDRAWN"
    system["outage_start_at"] = None
    system["outage_end_at"] = None
    db.touch(system)
    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    db.touch(project)
    return response.ok(response.public(system))
