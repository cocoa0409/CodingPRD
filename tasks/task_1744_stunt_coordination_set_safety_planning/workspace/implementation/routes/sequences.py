"""StuntSequence: create, lock-design, mark-ready, reverify, cancel."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    gate_posture_setup_or_active,
    gate_posture_active,
    latest_approved_assessment,
    board_score_of,
    screening_band,
    readiness_gates,
    has_special_equipment,
    serialize_sequence,
    stamp_new,
    stamp_mutable,
    touch,
    QUOTA_BY_CATEGORY,
    LOCK_THRESHOLD,
    default_sort_key,
)
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_CATEGORY_SCORE_MISMATCH,
    ERR_RISK_SCORE_ABOVE_THRESHOLD,
    ERR_EQUIPMENT_NOT_FOUND,
    ERR_INVALID_TIME_RANGE,
    ERR_CROSS_PRODUCTION_REFERENCE,
)
from domain import HAZARD_CLASSES, RISK_CATEGORIES
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_enum,
    v_datetime,
    v_id_list,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("sequences", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
COORD = ["StuntCoordinator"]


def _owner_check(seq, user_id):
    if user_id != seq["coordinator_user_id"]:
        raise err(
            ERR_NOT_RESOURCE_OWNER,
            "Only the coordinator who created the sequence may perform this action",
            403,
        )


@bp.post("/api/stunt-sequences")
def create_sequence():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "name": (v_string, True, None),
            "hazard_class": (v_enum(HAZARD_CLASSES), True, None),
            "risk_category": (v_enum(RISK_CATEGORIES), True, None),
            "scheduled_execution_start": (v_datetime, True, None),
            "scheduled_execution_end": (v_datetime, True, None),
            "required_equipment_ids": (v_id_list, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, COORD)

    # existence (tier 3): production first, then each equipment id left to right
    prod = get_production(data["production_id"])
    items = []
    for eid in data["required_equipment_ids"]:
        item = store.equipment.get(eid)
        if item is None:
            raise err(ERR_EQUIPMENT_NOT_FOUND, f"No EquipmentItem with id {eid}", 404)
        items.append(item)

    # posture (tier 5): design operations allowed in SETUP or ACTIVE
    gate_posture_setup_or_active(prod)

    # time range well-formed (tier 10)
    if not data["scheduled_execution_end"] > data["scheduled_execution_start"]:
        raise err(ERR_INVALID_TIME_RANGE,
                  "scheduled_execution_end must be after scheduled_execution_start", 422)

    # cross-production integrity (tier 11)
    for item in items:
        if item["production_id"] != prod["id"]:
            raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                      "required_equipment_ids must reference equipment of the same "
                      "production", 422)

    seq = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": prod["id"],
                "name": data["name"],
                "hazard_class": data["hazard_class"],
                "risk_category": data["risk_category"],
                "status": "DRAFT",
                "coordinator_user_id": user_id,
                "scheduled_execution_start": data["scheduled_execution_start"],
                "scheduled_execution_end": data["scheduled_execution_end"],
                "required_equipment_ids": data["required_equipment_ids"],
                "required_rehearsal_count": None,
                "completed_rehearsal_count": 0,
                "completed_rehearsal_minutes": 0,
                "current_assessment_id": None,
                "board_score": None,
                "design_revision": 1,
                "medic_standby_required": None,
            }
        )
    )
    store.sequences[seq["id"]] = seq
    return ok(serialize_sequence(seq), 201)


@bp.get("/api/stunt-sequences")
def list_sequences():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    hazard_class = request.args.get("hazard_class")
    equipment_membership = request.args.get("required_equipment_ids")
    items = []
    for s in store.sequences.values():
        if production_id is not None and s["production_id"] != production_id:
            continue
        if status is not None and s["status"] != status:
            continue
        if hazard_class is not None and s["hazard_class"] != hazard_class:
            continue
        if equipment_membership is not None and equipment_membership not in s["required_equipment_ids"]:
            continue
        items.append(s)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_sequence(s) for s in page], total, limit, offset)


@bp.get("/api/stunt-sequences/<sid>")
def get_one_sequence(sid):
    _, role = auth()
    require_role(role, READ_ROLES)
    seq = get_sequence(sid)
    return ok(serialize_sequence(seq), 200)


@bp.post("/api/stunt-sequences/<sid>/lock-design")
def lock_design(sid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    seq = get_sequence(sid)
    _owner_check(seq, user_id)
    prod = get_production(seq["production_id"])
    gate_posture_setup_or_active(prod)

    if seq["status"] != "DRAFT":
        raise err(ERR_SEQUENCE_INVALID_STATE, "lock-design requires status DRAFT", 409)
    pinned = latest_approved_assessment(seq["id"])
    if pinned is None:
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "lock-design requires at least one APPROVED risk assessment", 409)

    # risk gates (tier 8): board threshold first, then category-band match
    board = board_score_of(pinned, seq["hazard_class"])
    if board >= LOCK_THRESHOLD:
        raise err(ERR_RISK_SCORE_ABOVE_THRESHOLD,
                  f"Board risk score {board} reaches the lock threshold "
                  f"{LOCK_THRESHOLD}", 422)
    if screening_band(pinned["screening_score"]) != seq["risk_category"]:
        raise err(ERR_CATEGORY_SCORE_MISMATCH,
                  "Declared risk_category does not match the pinned assessment's "
                  "screening band", 422)

    seq["status"] = "DESIGN_LOCKED"
    seq["current_assessment_id"] = pinned["id"]
    seq["board_score"] = board
    quota = QUOTA_BY_CATEGORY[seq["risk_category"]]
    if has_special_equipment(seq):
        quota += 1
    seq["required_rehearsal_count"] = quota
    seq["medic_standby_required"] = (
        seq["risk_category"] in ("HIGH", "CRITICAL")
        or seq["hazard_class"] in ("FIRE", "PYRO", "VEHICLE", "WATER")
    )
    touch(seq)
    return ok(serialize_sequence(seq), 200)


@bp.post("/api/stunt-sequences/<sid>/mark-ready")
def mark_ready(sid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    seq = get_sequence(sid)
    _owner_check(seq, user_id)
    prod = get_production(seq["production_id"])
    gate_posture_active(prod)
    if seq["status"] != "DESIGN_LOCKED":
        raise err(ERR_SEQUENCE_INVALID_STATE, "mark-ready requires status DESIGN_LOCKED", 409)
    readiness_gates(seq, prod)
    seq["status"] = "READY"
    touch(seq)
    return ok(serialize_sequence(seq), 200)


@bp.post("/api/stunt-sequences/<sid>/reverify-readiness")
def reverify_readiness(sid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    seq = get_sequence(sid)
    _owner_check(seq, user_id)
    prod = get_production(seq["production_id"])
    gate_posture_active(prod)
    if seq["status"] != "SAFETY_HOLD":
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "reverify-readiness requires status SAFETY_HOLD", 409)
    readiness_gates(seq, prod)
    seq["status"] = "READY"
    touch(seq)
    return ok(serialize_sequence(seq), 200)


@bp.post("/api/stunt-sequences/<sid>/cancel")
def cancel_sequence(sid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_string, False, None)})
    user_id, role = auth()
    require_role(role, ["StuntCoordinator", "ProductionExecutive"])
    seq = get_sequence(sid)
    if role == "StuntCoordinator":
        _owner_check(seq, user_id)
    prod = get_production(seq["production_id"])
    gate_posture_setup_or_active(prod)
    if seq["status"] in ("REVIEWED", "CANCELLED"):
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "Sequence is already terminal", 409)

    # downstream compensation
    for r in store.rehearsals.values():
        if r["sequence_id"] == seq["id"] and r["status"] == "SCHEDULED":
            r["status"] = "CANCELLED"
            touch(r)
    for m in store.meetings.values():
        if m["sequence_id"] == seq["id"] and m["status"] in ("SCHEDULED", "IN_SESSION"):
            m["status"] = "ADJOURNED"
            touch(m)
    for adj in store.adjustments.values():
        if adj["sequence_id"] != seq["id"]:
            continue
        if adj["status"] in ("PROPOSED", "COUNTERED"):
            adj["status"] = "WITHDRAWN"
            touch(adj)
        elif adj["status"] == "AGREED":
            adj["status"] = "VOIDED"
            prod["committed_pay_cents"] -= adj["final_amount_cents"]
            touch(adj)
            touch(prod)
    seq["status"] = "CANCELLED"
    touch(seq)
    return ok(serialize_sequence(seq), 200)
