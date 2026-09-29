"""Production lots: creation, the stage ladder, sampling plans, dispositions, holds."""
from flask import Blueprint, g

from authz import (
    DESIGN_ENGINEER,
    JOB_QUALITY,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    WARRANTY_ADMINISTRATOR,
    endpoint,
    require_job_class,
)
from errors import ApiError
from helpers import (
    apply_filters,
    assemblies_of_lot,
    lookup,
    paginated,
    runs_of_lot,
    unique_or_conflict,
)
from response import object_response
from store import db
from services.constants import (
    HOLDABLE_LOT_STATES,
    HOLD_REASON_OPERATOR,
    MAX_RETESTS,
    POSTURE_FROZEN,
    POSTURE_OPEN,
)
from services.lot_service import (
    draw_plan,
    quarantine_cascade,
    recompute_lot_yield,
    release_blocked_by,
    restore_revoked_assemblies,
    scrap_cascade,
)

bp = Blueprint("lots", __name__)

LOT_READERS = [
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    DESIGN_ENGINEER,
    WARRANTY_ADMINISTRATOR,
]

PROCESS_STATES = [
    "PLANNED",
    "PLATE_PRODUCTION",
    "FORMATION",
    "ASSEMBLY",
    "LOT_TESTING",
    "QUARANTINED",
    "RELEASED",
    "SCRAPPED",
]
LADDER = ["PLANNED", "PLATE_PRODUCTION", "FORMATION", "ASSEMBLY"]

CREATE_SPEC = {
    "plant_id": {"type": "id", "required": True},
    "cell_design_id": {"type": "id", "required": True},
    "lot_code": {"type": "string", "required": True},
    "quantity": {"type": "int", "required": True, "gte": 1, "lte": 500},
}

ADVANCE_SPEC = {"to_state": {"type": "enum", "required": True, "values": PROCESS_STATES}}

PLAN_SPEC = {
    "expected_lot_version": {"type": "int", "required": True},
    "plan_reason": {"type": "string", "allow_blank": True},
}

DISPOSITION_SPEC = {
    "action": {
        "type": "enum",
        "required": True,
        "values": ["RELEASE", "QUARANTINE", "RETEST", "SCRAP"],
    },
    "disposition_note": {"type": "string", "allow_blank": True},
}

HOLD_SPEC = {
    "action": {"type": "enum", "required": True, "values": ["HOLD", "RELEASE_HOLD"]},
    "hold_reason": {"type": "enum", "values": [HOLD_REASON_OPERATOR]},
}

LOT_FILTERS = {
    "plant_id": "plant_id",
    "cell_design_id": "cell_design_id",
    "process_state": "process_state",
    "env_hold_status": "env_hold_status",
    "last_test_recorded_by_worker_id": "last_test_recorded_by_worker_id",
}
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]


def _plant_of(lot):
    return db.plants.get(lot["plant_id"])


def _design_of(lot):
    return db.cell_designs.get(lot["cell_design_id"])


def _guard_not_frozen(plant):
    if plant is not None and plant.get("compliance_posture") == POSTURE_FROZEN:
        raise ApiError("ERR_PLANT_FROZEN", "The plant's compliance posture is FROZEN")


def _guard_not_held(lot):
    if lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")


def _guard_chemistry_licensed(plant, lot):
    if plant is not None and lot["chemistry"] not in (plant.get("licensed_chemistries") or []):
        raise ApiError(
            "ERR_CHEMISTRY_NOT_LICENSED",
            "The lot's chemistry is not licensed at this plant",
        )


@bp.post("/production-lots")
@endpoint([PRODUCTION_SUPERVISOR], body=CREATE_SPEC)
def create_lot():
    payload = g.body
    plant = lookup("plants", payload["plant_id"])
    design = lookup("cell_designs", payload["cell_design_id"])
    unique_or_conflict(
        "production_lots", "lot_code", payload["lot_code"], "plant_id", plant["id"]
    )
    _guard_not_frozen(plant)
    if design["chemistry"] not in (plant.get("licensed_chemistries") or []):
        raise ApiError(
            "ERR_CHEMISTRY_NOT_LICENSED",
            "The design's chemistry is not licensed at this plant",
        )
    if design.get("approval_state") != "APPROVED":
        raise ApiError("ERR_DESIGN_NOT_APPROVED", "The cell design is not APPROVED")
    record = {
        "plant_id": plant["id"],
        "cell_design_id": design["id"],
        "lot_code": payload["lot_code"],
        "quantity": payload["quantity"],
        "design_revision_pinned": design.get("approved_revision"),
        "chemistry": design["chemistry"],
        "process_state": "PLANNED",
        "env_hold_status": "CLEAR",
        "hold_reason": None,
        "retest_count": 0,
        "sample_size": None,
        "acceptance_number": None,
        "sampling_plan_revision": 0,
        "completed_test_count": 0,
        "failed_test_count": 0,
        "passed_cycle_life_count": 0,
        "failed_formation_count": 0,
        "lot_capacity_yield_pct": None,
        "last_test_recorded_by_worker_id": None,
        "released_at": None,
    }
    db.insert("production_lots", record)
    return object_response(record, 201)


@bp.get("/production-lots")
@endpoint(LOT_READERS, paginated=True)
def list_lots():
    return paginated(apply_filters(db.rows("production_lots"), LOT_FILTERS), DEFAULT_ORDER)


@bp.get("/production-lots/<lot_id>")
@endpoint(LOT_READERS)
def read_lot(lot_id):
    return object_response(lookup("production_lots", lot_id))


@bp.post("/production-lots/<lot_id>/advance")
@endpoint([PRODUCTION_SUPERVISOR], body=ADVANCE_SPEC)
def advance_lot(lot_id):
    lot = lookup("production_lots", lot_id)
    target = g.body["to_state"]
    current = lot["process_state"]
    expected = None
    if current in LADDER:
        index = LADDER.index(current)
        if index + 1 < len(LADDER):
            expected = LADDER[index + 1]
    if target != expected:
        raise ApiError(
            "ERR_LOT_STATE_INVALID",
            "to_state must name the immediate successor of %s" % current,
        )
    plant = _plant_of(lot)
    _guard_not_frozen(plant)
    if target == "FORMATION" and plant is not None:
        if plant.get("compliance_posture") != POSTURE_OPEN:
            raise ApiError(
                "ERR_PLANT_RESTRICTED",
                "Formation may only begin while the plant's posture is OPEN",
            )
    _guard_not_held(lot)
    _guard_chemistry_licensed(plant, lot)
    if target == "ASSEMBLY":
        runs = runs_of_lot(lot["id"])
        if not any(r.get("run_state") == "COMPLETED" for r in runs):
            raise ApiError(
                "ERR_LOT_STATE_INVALID", "At least one formation run must be COMPLETED"
            )
        if any(r.get("run_state") in ("SCHEDULED", "CHARGING") for r in runs):
            raise ApiError(
                "ERR_LOT_STATE_INVALID", "No formation run may still be SCHEDULED or CHARGING"
            )
        if lot.get("failed_formation_count", 0) != 0:
            raise ApiError(
                "ERR_LOT_STATE_INVALID",
                "A failed formation run blocks the lot from ASSEMBLY",
            )
    lot["process_state"] = target
    db.touch(lot)
    return object_response(lot)


@bp.post("/production-lots/<lot_id>/sampling-plans")
@endpoint([QUALITY_INSPECTOR], body=PLAN_SPEC)
def draw_sampling_plan(lot_id):
    lot = lookup("production_lots", lot_id)
    if g.body["expected_lot_version"] != lot.get("version"):
        raise ApiError(
            "ERR_STALE_LOT_VERSION",
            "expected_lot_version does not match the lot's current version",
        )
    state = lot["process_state"]
    first_draw = state == "ASSEMBLY"
    if not first_draw and state != "LOT_TESTING":
        raise ApiError(
            "ERR_LOT_STATE_INVALID",
            "A plan may only be drawn from ASSEMBLY or redrawn from LOT_TESTING",
        )
    if first_draw:
        certified = [
            a
            for a in assemblies_of_lot(lot["id"])
            if a.get("certification_status") == "CERTIFIED"
        ]
        if not certified:
            raise ApiError(
                "ERR_LOT_STATE_INVALID",
                "At least one assembly must be CERTIFIED before the first draw",
            )
    plant = _plant_of(lot)
    _guard_not_frozen(plant)
    _guard_not_held(lot)
    if first_draw:
        lot["process_state"] = "LOT_TESTING"
    draw_plan(lot, _design_of(lot))
    db.touch(lot)
    return object_response(lot, 201)


@bp.post("/production-lots/<lot_id>/disposition")
@endpoint([QUALITY_INSPECTOR], body=DISPOSITION_SPEC)
def dispose_lot(lot_id):
    action = g.body["action"]
    if action == "RELEASE":
        require_job_class(JOB_QUALITY)
    lot = lookup("production_lots", lot_id)
    plant = _plant_of(lot)
    state = lot["process_state"]
    if action in ("RELEASE", "QUARANTINE") and state != "LOT_TESTING":
        raise ApiError("ERR_LOT_STATE_INVALID", "%s requires the lot to be LOT_TESTING" % action)
    if action in ("RETEST", "SCRAP") and state != "QUARANTINED":
        raise ApiError("ERR_LOT_STATE_INVALID", "%s requires the lot to be QUARANTINED" % action)
    if action == "RELEASE":
        _guard_not_frozen(plant)
    if action in ("RELEASE", "RETEST"):
        _guard_not_held(lot)
    if action == "RELEASE":
        if lot.get("last_test_recorded_by_worker_id") == g.actor["id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The inspector who recorded the last test may not release the lot",
            )
        sample_size = lot.get("sample_size")
        if sample_size is None or lot.get("completed_test_count", 0) < sample_size:
            raise ApiError("ERR_SAMPLING_INCOMPLETE", "Too few completed tests for release")
        if lot.get("passed_cycle_life_count", 0) < 1:
            raise ApiError(
                "ERR_SAMPLING_INCOMPLETE", "No passing cycle-life sample for release"
            )
        if lot.get("failed_test_count", 0) > lot.get("acceptance_number", 0):
            raise ApiError("ERR_ACCEPTANCE_EXCEEDED", "Failures exceed the acceptance number")
        lot["process_state"] = "RELEASED"
        lot["released_at"] = db.now()
        recompute_lot_yield(lot)
    elif action == "QUARANTINE":
        quarantine_cascade(lot)
    elif action == "RETEST":
        if lot.get("retest_count", 0) >= MAX_RETESTS:
            raise ApiError("ERR_RETEST_LIMIT_REACHED", "The lot has already been retested twice")
        lot["retest_count"] = lot.get("retest_count", 0) + 1
        lot["completed_test_count"] = 0
        lot["failed_test_count"] = 0
        lot["passed_cycle_life_count"] = 0
        lot["process_state"] = "LOT_TESTING"
        draw_plan(lot, _design_of(lot))
        restore_revoked_assemblies(lot)
    else:
        scrap_cascade(lot)
    db.touch(lot)
    return object_response(lot)


@bp.post("/production-lots/<lot_id>/env-hold")
@endpoint([SAFETY_OFFICER], body=HOLD_SPEC)
def env_hold(lot_id):
    lot = lookup("production_lots", lot_id)
    action = g.body["action"]
    if action == "HOLD":
        if lot.get("env_hold_status") == "HELD":
            raise ApiError("ERR_LOT_STATE_INVALID", "The lot is already HELD")
        if lot["process_state"] not in HOLDABLE_LOT_STATES:
            raise ApiError(
                "ERR_LOT_STATE_INVALID",
                "A %s lot cannot be placed on hold" % lot["process_state"],
            )
        lot["env_hold_status"] = "HELD"
        lot["hold_reason"] = g.body.get("hold_reason") or HOLD_REASON_OPERATOR
    else:
        if lot.get("env_hold_status") != "HELD":
            raise ApiError("ERR_LOT_STATE_INVALID", "The lot is not HELD")
        lot["env_hold_status"] = "CLEAR"
        lot["hold_reason"] = None
    db.touch(lot)
    return object_response(lot)


@bp.get("/production-lots/<lot_id>/quality-summary")
@endpoint([PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR])
def quality_summary(lot_id):
    lot = lookup("production_lots", lot_id)
    return object_response(
        {
            "lot_id": lot["id"],
            "sample_size": lot.get("sample_size"),
            "acceptance_number": lot.get("acceptance_number"),
            "sampling_plan_revision": lot.get("sampling_plan_revision"),
            "completed_test_count": lot.get("completed_test_count"),
            "failed_test_count": lot.get("failed_test_count"),
            "passed_cycle_life_count": lot.get("passed_cycle_life_count"),
            "lot_capacity_yield_pct": lot.get("lot_capacity_yield_pct"),
            "release_blocked_by": release_blocked_by(lot, _plant_of(lot)),
        }
    )
