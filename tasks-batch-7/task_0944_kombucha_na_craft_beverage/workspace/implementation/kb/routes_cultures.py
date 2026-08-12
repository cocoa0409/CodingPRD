"""SCOBY cultures and fermentation vessels."""

from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import recompute_vitality, scoby_vitality_score
from .cascades import culture_failure_cascade
from .envelope import list_response, object_response
from .errors import ApiError
from .store import base_record, collection_sorted, db, touch
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
)

bp = Blueprint("cultures", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")
CULTURE_STATES = ("ACTIVE", "REVERIFICATION_PENDING", "RETIRED", "CONTAMINATED")
VESSEL_STATES = ("DIRTY", "CIP_IN_PROGRESS", "SANITIZED", "OCCUPIED")


# ------------------------------------------------------------- cultures


@bp.post("/scoby-cultures")
def create_culture():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()

    parent = None
    raw_parent = payload.get("parent_culture_id")
    if isinstance(raw_parent, str) and raw_parent.strip():
        parent = lookup.scoby_culture(raw_parent)

    data = parse_body(
        payload,
        [
            field("label", "string", required=True),
            field("parent_culture_id", "string"),
        ],
    )

    if parent is not None:
        if parent["state"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE", "The mother culture must be ACTIVE to be split."
            )
        generation = int(parent["generation_number"]) + 1
        if generation > C.SCOBY_GENERATION_CAP:
            raise ApiError(
                "ERR_SCOBY_GENERATION_CAP",
                "A daughter beyond generation %d may not be created."
                % C.SCOBY_GENERATION_CAP,
            )
    else:
        generation = 1

    record = base_record()
    record.update(
        {
            "label": data["label"],
            "parent_culture_id": parent["id"] if parent is not None else None,
            "generation_number": generation,
            "pitch_count": 0,
            "reverification_count": 0,
            "last_reverified_at": None,
            "vitality_score": scoby_vitality_score(0, generation, 0),
            "state": "ACTIVE",
            "retire_reason": None,
        }
    )
    db.scoby_cultures[record["id"]] = record
    return object_response(record, 201)


@bp.post("/scoby-cultures/<id>/reverify")
def reverify_culture(id):
    authorize("QaManager", "PlatformAdmin")
    culture = lookup.scoby_culture(id)
    body_dict()
    if culture["state"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ACTIVE culture may be sent for reverification."
        )
    culture["state"] = "REVERIFICATION_PENDING"
    touch(culture)
    return object_response(culture)


@bp.post("/scoby-cultures/<id>/reverify-result")
def reverify_result(id):
    authorize("QaManager", "PlatformAdmin")
    culture = lookup.scoby_culture(id)
    payload = body_dict()
    data = parse_body(
        payload,
        [field("outcome", "enum", required=True, members=C.REVERIFICATION_OUTCOMES)],
    )
    if culture["state"] != "REVERIFICATION_PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a REVERIFICATION_PENDING culture may record a laboratory result.",
        )

    if data["outcome"] == "PASS":
        culture["reverification_count"] = int(culture["reverification_count"]) + 1
        culture["pitch_count"] = 0
        culture["last_reverified_at"] = db.clock
        culture["state"] = "ACTIVE"
        recompute_vitality(culture)
        touch(culture)
    else:
        culture["state"] = "CONTAMINATED"
        culture["retire_reason"] = "CONTAMINATION"
        touch(culture)
        culture_failure_cascade(culture)
    return object_response(culture)


@bp.post("/scoby-cultures/<id>/retire")
def retire_culture(id):
    authorize("ProductionOperator", "PlatformAdmin")
    culture = lookup.scoby_culture(id)
    payload = body_dict()
    data = parse_body(
        payload,
        [field("retire_reason", "enum", members=C.RETIRE_REASONS, default="OPERATOR")],
    )
    if culture["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE culture may be retired.")
    in_flight = any(
        b["scoby_culture_id"] == culture["id"]
        and b["ferment_stage"] in ("F1_ACTIVE", "F2_ACTIVE")
        for b in db.batches.values()
    )
    if in_flight:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A culture with a batch still fermenting may not be retired.",
        )
    culture["state"] = "RETIRED"
    culture["retire_reason"] = data["retire_reason"] or "OPERATOR"
    touch(culture)
    return object_response(culture)


@bp.get("/scoby-cultures/<id>")
def read_culture(id):
    authorize(*READ_ROLES)
    culture = lookup.scoby_culture(id)
    recompute_vitality(culture)
    return object_response(culture)


@bp.get("/scoby-cultures/<id>/daughters")
def list_daughters(id):
    authorize(*READ_ROLES)
    culture = lookup.scoby_culture(id)
    state = query_enum("state", CULTURE_STATES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.scoby_cultures,
        lambda c: c["parent_culture_id"] == culture["id"]
        and (state is None or c["state"] == state),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# --------------------------------------------------------------- vessels


@bp.post("/vessels")
def create_vessel():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("code", "string", required=True),
            field("capacity_liters", "number", required=True, positive=True),
        ],
    )
    from .util import round2

    record = base_record()
    record.update(
        {
            "code": data["code"],
            "capacity_liters": round2(data["capacity_liters"]),
            "state": "DIRTY",
            "cip_started_at": None,
            "cip_completed_at": None,
            "current_batch_id": None,
            "occupancy_start_at": None,
            "occupancy_end_at": None,
        }
    )
    db.vessels[record["id"]] = record
    return object_response(record, 201)


@bp.post("/vessels/<id>/cip-start")
def cip_start(id):
    authorize("ProductionOperator", "PlatformAdmin")
    vessel = lookup.vessel(id)
    body_dict()
    if vessel["state"] not in ("DIRTY", "SANITIZED"):
        raise ApiError(
            "ERR_VESSEL_UNAVAILABLE",
            "A clean-in-place cycle starts from DIRTY or SANITIZED only.",
        )
    vessel["state"] = "CIP_IN_PROGRESS"
    vessel["cip_started_at"] = db.clock
    vessel["cip_completed_at"] = None
    touch(vessel)
    return object_response(vessel)


@bp.post("/vessels/<id>/cip-complete")
def cip_complete(id):
    authorize("ProductionOperator", "PlatformAdmin")
    vessel = lookup.vessel(id)
    body_dict()
    if vessel["state"] != "CIP_IN_PROGRESS":
        raise ApiError(
            "ERR_VESSEL_UNAVAILABLE",
            "Only a vessel in CIP_IN_PROGRESS may complete its cycle.",
        )
    vessel["state"] = "SANITIZED"
    vessel["cip_completed_at"] = db.clock
    touch(vessel)
    return object_response(vessel)


@bp.get("/vessels/<id>")
def read_vessel(id):
    authorize(*READ_ROLES)
    return object_response(lookup.vessel(id))
