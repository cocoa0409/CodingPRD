"""Environmental samples, excursions, investigations (PRD 3.3, 3.4)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ROOM_NOT_ACTIVE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_EXCURSION_NOT_OPEN,
    ERR_INVESTIGATION_ALREADY_OPEN,
    ERR_INVESTIGATION_NOT_DRAFT,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_role, body, QA, ET
from response import ok, paginate
from services.core import (
    req_int,
    req_iso,
    opt_string,
    req_string,
    req_enum,
    touch_room,
    recompute_posture,
    classify_sample,
    compute_severity_score,
    shutdown_cascade,
)

bp = Blueprint("samples", __name__)

PRODUCT_IMPACTS = {"NONE", "POTENTIAL", "CONFIRMED"}
DISPOSITIONS = {"RELEASE", "REJECT", "REWORK"}
READERS = [QA, ET]


def load_excursion(excursion_id):
    exc = store.excursions.get(excursion_id)
    if exc is None:
        raise ApiError(ERR_NOT_FOUND, 404, "excursion %s not found" % excursion_id)
    return exc


def load_investigation(inv_id):
    inv = store.investigations.get(inv_id)
    if inv is None:
        raise ApiError(ERR_NOT_FOUND, 404, "investigation %s not found" % inv_id)
    return inv


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/samples")
def create_sample():
    uid = require_role([ET])
    payload = body()

    # priority 3: body FK existence, left to right
    point_id = payload.get("sampling_point_id")
    if point_id is None or not isinstance(point_id, str):
        raise ApiError(ERR_NOT_FOUND, 404, "sampling point not found")
    point = store.sampling_points.get(point_id)
    if point is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sampling point %s not found" % point_id)
    recurrence_id = payload.get("recurrence_of_excursion_id")
    recurrence_target = None
    if recurrence_id is not None:
        recurrence_target = store.excursions.get(recurrence_id)
        if recurrence_target is None:
            raise ApiError(ERR_NOT_FOUND, 404,
                           "excursion %s not found" % recurrence_id)

    # priority 5: state gates (room operational-write gate, point ACTIVE)
    room = store.rooms.get(point["cleanroom_id"])
    if room is not None:
        touch_room(room)
        if room["status"] != "ACTIVE":
            raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    if point["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "sampling point is RETIRED")

    # priority 9: structural validity
    result_value = req_int(payload, "result_value", minimum=0)
    sampled_at = req_iso(payload, "sampled_at")
    recurrence_id = opt_string(payload, "recurrence_of_excursion_id")

    # priority 10: referential coherence of the declared recurrence link
    if recurrence_id is not None:
        if (recurrence_target["status"] != "CLOSED"
                or recurrence_target["sampling_point_id"] != point["id"]):
            raise ApiError(
                ERR_REFERENTIAL_INTEGRITY, 422,
                "recurrence_of_excursion_id must point to a CLOSED excursion "
                "at the same sampling point")

    classification = classify_sample(room, point["metric"], result_value)

    from db import iso_ms
    sample = new_record({
        "sampling_point_id": point["id"],
        "result_value": result_value,
        "sampled_at": iso_ms(sampled_at),
        "classification": classification,
        "triggered_excursion_id": None,
    })
    store.samples[sample["id"]] = sample

    if classification != "IN_CONTROL":
        severity = "ALERT" if classification == "ALERT_EXCEEDED" else "ACTION"
        excursion = new_record({
            "cleanroom_id": room["id"],
            "sampling_point_id": point["id"],
            "sample_id": sample["id"],
            "severity": severity,
            "severity_score": compute_severity_score(point, sampled_at),
            "recurrence_of_excursion_id": recurrence_id,
            "recorded_by_user_id": uid,
            "status": "OPEN",
        })
        store.excursions[excursion["id"]] = excursion
        # The forward link is part of the sample's creation, not a later
        # mutation: the sample is still born at version 1.
        sample["triggered_excursion_id"] = excursion["id"]
        if recompute_posture(room):
            mutate(room)

    return ok(pub(sample), 201)


@bp.get("/cleanroom/samples")
def list_samples():
    require_role(READERS)
    records = list(store.samples.values())
    point_id = request.args.get("sampling_point_id")
    classification = request.args.get("classification")
    if point_id is not None:
        records = [s for s in records if s["sampling_point_id"] == point_id]
    if classification is not None:
        records = [s for s in records if s["classification"] == classification]
    return paginate(records, request.args)


@bp.get("/cleanroom/samples/<sampleId>")
def get_sample(sampleId):
    require_role(READERS)
    sample = store.samples.get(sampleId)
    if sample is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sample %s not found" % sampleId)
    return ok(pub(sample))


# ---------------------------------------------------------------------------
# Excursions
# ---------------------------------------------------------------------------


@bp.get("/cleanroom/excursions")
def list_excursions():
    require_role(READERS)
    records = list(store.excursions.values())
    filters = (
        ("cleanroom_id", "cleanroom_id"),
        ("status", "status"),
        ("severity", "severity"),
        ("sampling_point_id", "sampling_point_id"),
        ("sample_id", "sample_id"),
        ("recurrence_of_excursion_id", "recurrence_of_excursion_id"),
    )
    for param, field in filters:
        value = request.args.get(param)
        if value is not None:
            records = [e for e in records if e[field] == value]
    return paginate(records, request.args)


@bp.get("/cleanroom/excursions/<excursionId>")
def get_excursion(excursionId):
    require_role(READERS)
    return ok(pub(load_excursion(excursionId)))


@bp.get("/cleanroom/excursions/<excursionId>/samples")
def list_excursion_samples(excursionId):
    require_role(READERS)
    exc = load_excursion(excursionId)
    sample = store.samples.get(exc["sample_id"])
    records = [sample] if sample is not None else []
    return paginate(records, request.args)


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/excursions/<excursionId>/investigations")
def open_investigation(excursionId):
    uid = require_role([QA])
    exc = load_excursion(excursionId)

    # priority 5: excursion must be OPEN
    if exc["status"] != "OPEN":
        raise ApiError(ERR_EXCURSION_NOT_OPEN, 409, "excursion is not OPEN")
    # priority 8: segregation of duties vs the recording technician
    if uid == exc["recorded_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "investigator must differ from the excursion recorder")
    # priority 9: structural validity
    payload = body()
    root_cause = req_string(payload, "root_cause")
    if len(root_cause) < 20:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "root_cause must be at least 20 characters")
    product_impact = req_enum(payload, "product_impact", PRODUCT_IMPACTS)
    disposition = req_enum(payload, "disposition", DISPOSITIONS)
    # priority 12: exactly one DRAFT investigation per excursion
    if any(i["excursion_id"] == exc["id"] and i["status"] == "DRAFT"
           for i in store.investigations.values()):
        raise ApiError(ERR_INVESTIGATION_ALREADY_OPEN, 409,
                       "a DRAFT investigation already exists for this excursion")

    inv = new_record({
        "excursion_id": exc["id"],
        "root_cause": root_cause,
        "product_impact": product_impact,
        "disposition": disposition,
        "investigated_by_user_id": uid,
        "status": "DRAFT",
    })
    inv["_cleanroom_id"] = exc["cleanroom_id"]
    store.investigations[inv["id"]] = inv
    exc["status"] = "UNDER_INVESTIGATION"
    mutate(exc)
    return ok(pub(inv), 201)


@bp.get("/cleanroom/excursions/<excursionId>/investigations")
def list_investigations(excursionId):
    require_role(READERS)
    exc = load_excursion(excursionId)
    records = [i for i in store.investigations.values()
               if i["excursion_id"] == exc["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/investigations/<investigationId>")
def get_investigation(investigationId):
    require_role(READERS)
    return ok(pub(load_investigation(investigationId)))


@bp.post("/cleanroom/investigations/<investigationId>/approve")
def approve_investigation(investigationId):
    uid = require_role([QA])
    inv = load_investigation(investigationId)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVESTIGATION_NOT_DRAFT, 409,
                       "investigation is not DRAFT")
    if uid == inv["investigated_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "approver must differ from the investigator")

    from db import next_seq
    inv["status"] = "APPROVED"
    inv["_approved_seq"] = next_seq()
    mutate(inv)

    exc = store.excursions[inv["excursion_id"]]
    exc["status"] = "CLOSED"
    mutate(exc)

    room = store.rooms.get(exc["cleanroom_id"])
    if room is not None:
        if inv["product_impact"] == "CONFIRMED":
            # Cascade atomically: room -> SHUTDOWN, batches held, transfers
            # rejected. The room's own version advances only when the room
            # itself observably changed (posture transition).
            changed = recompute_posture(room)
            shutdown_cascade(room)
            if changed:
                mutate(room)
        else:
            if recompute_posture(room):
                mutate(room)
    return ok(pub(inv))


@bp.post("/cleanroom/investigations/<investigationId>/reject")
def reject_investigation(investigationId):
    require_role([QA])
    inv = load_investigation(investigationId)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVESTIGATION_NOT_DRAFT, 409,
                       "investigation is not DRAFT")
    inv["status"] = "REJECTED"
    mutate(inv)

    exc = store.excursions[inv["excursion_id"]]
    exc["status"] = "OPEN"
    mutate(exc)

    room = store.rooms.get(exc["cleanroom_id"])
    if room is not None and recompute_posture(room):
        mutate(room)
    return ok(pub(inv))
