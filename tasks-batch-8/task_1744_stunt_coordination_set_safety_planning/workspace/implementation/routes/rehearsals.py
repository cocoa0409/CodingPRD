"""Rehearsal scheduling and lifecycle."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_performer,
    get_rehearsal,
    gate_posture_active,
    performer_effective_status,
    cert_valid,
    rehearsal_conflict,
    serialize_rehearsal,
    stamp_new,
    stamp_mutable,
    touch,
    default_sort_key,
)
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_PERFORMER_NOT_QUALIFIED,
    ERR_CERTIFICATION_MISSING_OR_EXPIRED,
    ERR_REHEARSAL_INVALID_STATE,
    ERR_REHEARSAL_CONFLICT,
    ERR_INVALID_TIME_RANGE,
    ERR_CROSS_PRODUCTION_REFERENCE,
    ERR_REHEARSAL_IN_PAST,
    ERR_REHEARSAL_TIME_GATE,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_datetime,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("rehearsals", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
COORD = ["StuntCoordinator"]


def _owner_check(rehearsal, user_id):
    seq = get_sequence(rehearsal["sequence_id"])
    if user_id != seq["coordinator_user_id"]:
        raise err(
            ERR_NOT_RESOURCE_OWNER,
            "Only the coordinator who owns the sequence may perform this action",
            403,
        )


@bp.post("/api/rehearsals")
def create_rehearsal():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
            "performer_id": (v_string, True, None),
            "facility": (v_string, True, None),
            "scheduled_start": (v_datetime, True, None),
            "scheduled_end": (v_datetime, True, None),
        },
    )
    _, role = auth()
    require_role(role, COORD)

    # existence (tier 3), left to right
    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])
    performer = get_performer(data["performer_id"])

    # posture (tier 5): ACTIVE and not STOPPED
    prod = get_production(seq["production_id"])
    gate_posture_active(prod)

    # entity state (tier 6): sequence state, then performer qualification
    if seq["status"] not in ("DESIGN_LOCKED", "READY"):
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "Rehearsals require the sequence in DESIGN_LOCKED or READY", 409)
    if performer_effective_status(performer) != "QUALIFIED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "The performer must be QUALIFIED at scheduling", 409)

    # certification discipline/validity vs the rehearsal's start (tier 7)
    has_cert = any(
        c["performer_id"] == performer["id"]
        and c["discipline"] == seq["hazard_class"]
        and cert_valid(c, data["scheduled_start"])
        for c in store.certifications.values()
    )
    if not has_cert:
        raise err(ERR_CERTIFICATION_MISSING_OR_EXPIRED,
                  "The performer lacks a valid certification matching the sequence's "
                  "hazard class", 422)

    # time range, then overlap (tier 10)
    if not data["scheduled_end"] > data["scheduled_start"]:
        raise err(ERR_INVALID_TIME_RANGE,
                  "scheduled_end must be after scheduled_start", 422)
    if rehearsal_conflict(
        data["production_id"], performer["id"],
        data["scheduled_start"], data["scheduled_end"],
    ):
        raise err(ERR_REHEARSAL_CONFLICT,
                  "The performer already has a rehearsal overlapping this window", 409)

    # cross-production integrity (tier 11)
    if seq["production_id"] != data["production_id"] or \
            performer["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "All references must belong to the same production", 422)

    # clock-relative (tier 12): start strictly in the future
    if not data["scheduled_start"] > store.now():
        raise err(ERR_REHEARSAL_IN_PAST,
                  "scheduled_start must be strictly in the future", 422)

    duration = int((data["scheduled_end"] - data["scheduled_start"]).total_seconds()) // 60
    rehearsal = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "performer_id": performer["id"],
                "facility": data["facility"],
                "scheduled_start": data["scheduled_start"],
                "scheduled_end": data["scheduled_end"],
                "duration_minutes": duration,
                "status": "SCHEDULED",
                "void_reason": None,
            }
        )
    )
    store.rehearsals[rehearsal["id"]] = rehearsal
    return ok(serialize_rehearsal(rehearsal), 201)


@bp.get("/api/rehearsals")
def list_rehearsals():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    performer_id = request.args.get("performer_id")
    status = request.args.get("status")
    items = []
    for r in store.rehearsals.values():
        if production_id is not None and r["production_id"] != production_id:
            continue
        if sequence_id is not None and r["sequence_id"] != sequence_id:
            continue
        if performer_id is not None and r["performer_id"] != performer_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_rehearsal(r) for r in page], total, limit, offset)


@bp.get("/api/rehearsals/<rid>")
def get_one_rehearsal(rid):
    _, role = auth()
    require_role(role, READ_ROLES)
    rehearsal = get_rehearsal(rid)
    return ok(serialize_rehearsal(rehearsal), 200)


@bp.post("/api/rehearsals/<rid>/complete")
def complete_rehearsal(rid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    rehearsal = get_rehearsal(rid)
    _owner_check(rehearsal, user_id)
    prod = get_production(rehearsal["production_id"])
    gate_posture_active(prod)
    if rehearsal["status"] != "SCHEDULED":
        raise err(ERR_REHEARSAL_INVALID_STATE,
                  "complete requires status SCHEDULED", 409)
    performer = get_performer(rehearsal["performer_id"])
    if performer_effective_status(performer) != "QUALIFIED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "The performer must be QUALIFIED at completion time", 409)
    if store.now() < rehearsal["scheduled_start"]:
        raise err(ERR_REHEARSAL_TIME_GATE,
                  "A rehearsal cannot complete before its scheduled_start", 422)

    rehearsal["status"] = "COMPLETED"
    touch(rehearsal)
    seq = get_sequence(rehearsal["sequence_id"])
    seq["completed_rehearsal_count"] += 1
    seq["completed_rehearsal_minutes"] += rehearsal["duration_minutes"]
    touch(seq)
    performer["completed_rehearsal_minutes"] += rehearsal["duration_minutes"]
    touch(performer)
    return ok(serialize_rehearsal(rehearsal), 200)


@bp.post("/api/rehearsals/<rid>/mark-missed")
def mark_missed_rehearsal(rid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    rehearsal = get_rehearsal(rid)
    _owner_check(rehearsal, user_id)
    prod = get_production(rehearsal["production_id"])
    gate_posture_active(prod)
    if rehearsal["status"] != "SCHEDULED":
        raise err(ERR_REHEARSAL_INVALID_STATE,
                  "mark-missed requires status SCHEDULED", 409)
    if not store.now() > rehearsal["scheduled_end"]:
        raise err(ERR_REHEARSAL_TIME_GATE,
                  "A rehearsal can be marked missed only after its scheduled_end", 422)
    rehearsal["status"] = "MISSED"
    touch(rehearsal)
    return ok(serialize_rehearsal(rehearsal), 200)


@bp.post("/api/rehearsals/<rid>/cancel")
def cancel_rehearsal(rid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    rehearsal = get_rehearsal(rid)
    _owner_check(rehearsal, user_id)
    prod = get_production(rehearsal["production_id"])
    gate_posture_active(prod)
    if rehearsal["status"] != "SCHEDULED":
        raise err(ERR_REHEARSAL_INVALID_STATE, "cancel requires status SCHEDULED", 409)
    rehearsal["status"] = "CANCELLED"
    touch(rehearsal)
    return ok(serialize_rehearsal(rehearsal), 200)


@bp.post("/api/rehearsals/<rid>/void-completion")
def void_completion(rid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    _, role = auth()
    require_role(role, ["SafetyOfficer"])
    rehearsal = get_rehearsal(rid)
    prod = get_production(rehearsal["production_id"])
    gate_posture_active(prod)
    if rehearsal["status"] != "COMPLETED":
        raise err(ERR_REHEARSAL_INVALID_STATE,
                  "void-completion requires status COMPLETED", 409)
    rehearsal["status"] = "VOIDED"
    rehearsal["void_reason"] = data["reason"]
    touch(rehearsal)
    # compensating action for invariant I2
    seq = get_sequence(rehearsal["sequence_id"])
    seq["completed_rehearsal_count"] -= 1
    seq["completed_rehearsal_minutes"] -= rehearsal["duration_minutes"]
    touch(seq)
    performer = get_performer(rehearsal["performer_id"])
    performer["completed_rehearsal_minutes"] -= rehearsal["duration_minutes"]
    touch(performer)
    return ok(serialize_rehearsal(rehearsal), 200)
