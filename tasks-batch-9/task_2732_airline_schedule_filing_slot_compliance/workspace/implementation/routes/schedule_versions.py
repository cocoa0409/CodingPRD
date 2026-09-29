"""Schedule versions: creation, forking, the compliance gate and withdrawal."""
from flask import Blueprint

import cascades
import derive
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import acting_user, authenticate, require_ownership
from response import ok, written
from routes.common import (
    READ_ROLES,
    list_response,
    read_one,
    require_carrier_active,
    require_season_open,
    season_of_version,
)

bp = Blueprint("schedule_versions", __name__)

PLANNER = ("NetworkPlanner",)
DEFAULT_BUDGET_CENTS = 100000
ROTATION_ERROR = {
    "INFEASIBLE_CONTINUITY": "ERR_ROTATION_CONTINUITY_BROKEN",
    "INFEASIBLE_TURN": "ERR_TURN_TIME_VIOLATION",
    "INFEASIBLE_BLOCK_CAP": "ERR_DAILY_BLOCK_CAP_EXCEEDED",
}


def _label_taken(carrier_id, season_id, label, skip_id=None):
    for row in store.values("schedule_versions"):
        if row["id"] == skip_id:
            continue
        if (
            row["carrier_id"] == carrier_id
            and row["season_id"] == season_id
            and row["version_label"] == label
        ):
            return True
    return False


def _new_version(carrier_id, season_id, label, budget, supersedes=None):
    return store.insert("schedule_versions", {
        "carrier_id": carrier_id,
        "season_id": season_id,
        "supersedes_version_id": supersedes,
        "version_label": label,
        "filing_status": "DRAFT",
        "compliance_state": "CLEAN",
        "validated_by_user_id": None,
        "filing_charge_budget_cents": budget,
        "filing_charge_accrued_cents": 0,
        "leg_count": 0,
        "unslotted_leg_count": 0,
        "curfew_violation_count": 0,
        "mct_violation_count": 0,
        "gate_overflow_count": 0,
        "at_risk_slot_count": 0,
        "schedule_compliance_score": 100.00,
    })


@bp.post("/schedule-versions")
def create_schedule_version():
    authenticate(PLANNER)
    payload = rv.body()
    carrier_id = rv.req_str(payload, "carrier_id", 1)
    season_id = rv.req_str(payload, "season_id", 1)
    label = rv.req_str(payload, "version_label", 1, 40)
    budget = rv.opt_int(payload, "filing_charge_budget_cents", 0, default=DEFAULT_BUDGET_CENTS)
    if _label_taken(carrier_id, season_id, label):
        rv.bad("That version_label is already used for this carrier and season.")
    carrier = store.require("carriers", carrier_id)
    season = store.require("seasons", season_id)
    require_ownership(carrier_id)
    require_season_open(season)
    require_carrier_active(carrier)
    row = _new_version(carrier_id, season_id, label, budget)
    return written(row, 201)


@bp.get("/schedule-versions/<schedule_version_id>")
def get_schedule_version(schedule_version_id):
    return ok(read_one("schedule_versions", schedule_version_id))


@bp.get("/schedule-versions")
def list_schedule_versions():
    authenticate(READ_ROLES)
    return list_response("schedule_versions", [
        ("carrier_id", rv.q_str("carrier_id")),
        ("season_id", rv.q_str("season_id")),
        ("supersedes_version_id", rv.q_str("supersedes_version_id")),
        ("filing_status", rv.q_enum("filing_status", "filing_status")),
        ("compliance_state", rv.q_enum("compliance_state", "compliance_state")),
    ])


@bp.post("/schedule-versions/<schedule_version_id>/supersede")
def supersede_schedule_version(schedule_version_id):
    authenticate(PLANNER)
    version = store.require("schedule_versions", schedule_version_id)
    payload = rv.body()
    label = rv.req_str(payload, "version_label", 1, 40)
    expected = rv.req_int(payload, "expected_schedule_version_version", 0)
    budget = rv.opt_int(payload, "filing_charge_budget_cents", 0, default=None)
    if _label_taken(version["carrier_id"], version["season_id"], label, version["id"]):
        rv.bad("That version_label is already used for this carrier and season.")
    require_ownership(version["carrier_id"])
    if expected != version["version"]:
        raise ApiError("ERR_STALE_SCHEDULE_VERSION")
    if version["filing_status"] not in ("DRAFT", "VALIDATED", "FILED"):
        raise ApiError("ERR_SCHEDULE_VERSION_STATE_INVALID")
    version["filing_status"] = "SUPERSEDED"
    mark(version)
    successor = _new_version(
        version["carrier_id"],
        version["season_id"],
        label,
        version["filing_charge_budget_cents"] if budget is None else budget,
        supersedes=version["id"],
    )
    return written(successor, 201)


@bp.post("/schedule-versions/<schedule_version_id>/validate")
def validate_schedule_version(schedule_version_id):
    authenticate(("ComplianceOfficer",))
    version = store.require("schedule_versions", schedule_version_id)
    rv.body()
    derive.recompute_all()

    if version["filing_status"] != "DRAFT":
        raise ApiError("ERR_SCHEDULE_VERSION_STATE_INVALID")
    legs = derive.legs_of_version(version["id"])
    live = derive.active(legs)
    if not legs:
        raise ApiError("ERR_SCHEDULE_VERSION_NOT_READY")
    for leg in live:
        if leg["assigned_aircraft_id"] is None or leg["status"] != "SLOT_BACKED":
            raise ApiError("ERR_SCHEDULE_VERSION_NOT_READY")
    if version["compliance_state"] == "BLOCKED":
        raise ApiError("ERR_SCHEDULE_BLOCKED")

    tails = []
    for leg in live:
        tail = store.get("aircraft", leg["assigned_aircraft_id"])
        if tail is not None and tail not in tails:
            tails.append(tail)
    for tail in tails:
        if tail["maintenance_check_required"] and (
            tail["maintenance_opportunity_minutes"] < tail["required_check_minutes"]
        ):
            raise ApiError("ERR_MAINTENANCE_OPPORTUNITY_INSUFFICIENT")
    for tail in tails:
        verdict = tail["rotation_feasibility_status"]
        if verdict in ROTATION_ERROR:
            raise ApiError(ROTATION_ERROR[verdict])
    for leg in live:
        if not derive.is_fully_slotted(leg):
            raise ApiError("ERR_SLOT_REQUIRED_AT_COORDINATED_STATION")

    version["filing_status"] = "VALIDATED"
    version["validated_by_user_id"] = acting_user()
    mark(version)
    return written(version)


@bp.post("/schedule-versions/<schedule_version_id>/withdraw")
def withdraw_schedule_version(schedule_version_id):
    authenticate(PLANNER)
    version = store.require("schedule_versions", schedule_version_id)
    payload = rv.body()
    rv.req_str(payload, "reason", 1, 500)
    require_ownership(version["carrier_id"])
    if version["filing_status"] not in ("DRAFT", "VALIDATED"):
        raise ApiError("ERR_SCHEDULE_VERSION_STATE_INVALID")
    for submission in derive.submissions_of_version(version["id"]):
        if submission["status"] in ("QUEUED", "TRANSMITTED"):
            raise ApiError("ERR_FILING_IN_FLIGHT")
    cascades.withdraw_version(version)
    return written(version)
