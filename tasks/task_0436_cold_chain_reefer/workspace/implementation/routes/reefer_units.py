"""ReeferUnit endpoints (PRD §3.1).

State machine: AVAILABLE -> ASSIGNED -> IN_TRANSIT -> AVAILABLE; AVAILABLE ->
RETIRED (terminal). DELETE retires only from AVAILABLE.
"""

from flask import Blueprint, request

from constants import REEFER_STATUSES
from db import store
from errors import err
from helpers import (
    get_carrier_or_404,
    get_reefer_unit_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from validators import (
    as_enum,
    as_int,
    as_string,
    get_body,
    parse_datetime_field,
    require,
)

bp = Blueprint("reefer_units", __name__)


@bp.route("/reefer-units", methods=["POST"])
def create_reefer_unit():
    _uid, role = authenticate()
    require_role(role, {"Carrier", "PlatformAdmin"})

    body = get_body(request)
    carrier_id = as_string(require(body, "carrier_id"), "carrier_id")
    asset_tag = as_string(require(body, "asset_tag"), "asset_tag")
    compartment_count = as_int(
        require(body, "compartment_count"), "compartment_count", minimum=1, maximum=4
    )
    last_sanitation_at = None
    if body.get("last_sanitation_at") is not None:
        last_sanitation_at = parse_datetime_field(
            body["last_sanitation_at"], "last_sanitation_at"
        )

    # FK existence (priority 4)
    if carrier_id not in store.carriers:
        raise err("ERR_FK_NOT_FOUND", "carrier_id does not resolve to a carrier")

    # Duplicate asset_tag among the carrier's non-RETIRED units (priority 12)
    for u in store.reefer_units.values():
        if (
            u["carrier_id"] == carrier_id
            and u["asset_tag"] == asset_tag
            and u["status"] != "RETIRED"
        ):
            raise err(
                "ERR_DUPLICATE_ASSET_TAG",
                "asset_tag already used by a non-RETIRED unit of this carrier",
            )

    rec = {
        "carrier_id": carrier_id,
        "asset_tag": asset_tag,
        "compartment_count": compartment_count,
        "status": "AVAILABLE",
        "last_sanitation_at": last_sanitation_at,
    }
    stamp_create(rec)
    store.reefer_units[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/reefer-units/<uid>", methods=["GET"])
def get_reefer_unit(uid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_reefer_unit_or_404(uid)
    return object_response(serialize(rec), 200)


@bp.route("/reefer-units", methods=["GET"])
def list_reefer_units():
    _uid, role = authenticate()
    require_role(role, {"Carrier", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    if status is not None and status not in REEFER_STATUSES:
        raise err("ERR_INVALID_REQUEST", "Invalid status filter")

    records = list(store.reefer_units.values())
    if carrier_id is not None:
        records = [r for r in records if r["carrier_id"] == carrier_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/reefer-units/<uid>", methods=["PATCH"])
def patch_reefer_unit(uid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "PlatformAdmin"})
    rec = get_reefer_unit_or_404(uid)

    body = get_body(request)
    last_sanitation_at = parse_datetime_field(
        require(body, "last_sanitation_at"), "last_sanitation_at"
    )
    rec["last_sanitation_at"] = last_sanitation_at
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/reefer-units/<uid>", methods=["DELETE"])
def retire_reefer_unit(uid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "PlatformAdmin"})
    rec = get_reefer_unit_or_404(uid)

    # Retirement permitted only from AVAILABLE (state check, priority 5)
    if rec["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Only an AVAILABLE unit may be retired")

    rec["status"] = "RETIRED"
    touch(rec)
    return object_response(serialize(rec), 200)
