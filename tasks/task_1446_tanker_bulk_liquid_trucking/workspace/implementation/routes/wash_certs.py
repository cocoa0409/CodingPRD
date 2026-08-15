"""Tank wash certificates: booking, certification, revocation (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from authz import ALL_ROLES, SAFETY_OFFICER, WASH_OPERATOR, require_roles
from calc import WASH_VALIDITY_HOURS
from cascades import (
    recompute_exposure, refresh_cert_lazy, release_shipment_plan,
)
from db import store
from errors import err, invalid_request
from respond import success
from serialize import ser_wash_cert
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_datetime, req_enum, req_field, sorted_by_creation, touch,
)
from routes.wash_bays import WASH_LEVELS

bp = Blueprint("wash_certs", __name__)

BOOKING_ACTIVE_STATUSES = ("SCHEDULED", "CERTIFIED")


@bp.route("/tank-wash-certificates", methods=["POST"])
def create_cert():
    require_roles([WASH_OPERATOR])
    data = json_body()
    # Priority 3: body-reference existence, left-to-right.
    trailer = bay = None
    if data.get("trailer_id") is not None:
        trailer = get_or_404(store.trailers, "trailers", data["trailer_id"])
    if data.get("wash_bay_id") is not None:
        bay = get_or_404(store.wash_bays, "wash_bays", data["wash_bay_id"])
    # Priority 4: shape.
    reject_unknown(data, {"trailer_id", "wash_bay_id", "wash_level",
                          "window_start", "window_end"})
    req_field(data, "trailer_id")
    req_field(data, "wash_bay_id")
    wash_level = req_enum(data, "wash_level", WASH_LEVELS)
    w_start = req_datetime(data, "window_start")
    w_end = req_datetime(data, "window_end")
    if w_end <= w_start:
        raise invalid_request("window_end must be strictly later than window_start")
    # Priority 8 temporal: turnaround buffer overlap on the same bay among
    # SCHEDULED/CERTIFIED bookings. Conflict iff new.start < existing.end +
    # buffer AND existing.start < new.end + buffer.
    buf = timedelta(minutes=bay["cleanup_buffer_minutes"])
    for o in store.wash_certs.values():
        if o["wash_bay_id"] != bay["id"] or o["status"] not in BOOKING_ACTIVE_STATUSES:
            continue
        if w_start < o["window_end"] + buf and o["window_start"] < w_end + buf:
            raise err("ERR_WASH_BAY_WINDOW_CONFLICT",
                      "Wash window violates the bay cleanup buffer against an existing booking")
    c = {
        "id": new_id(),
        "_seq": next(store.seq),
        "trailer_id": trailer["id"],
        "wash_bay_id": bay["id"],
        "wash_level": wash_level,
        "window_start": w_start,
        "window_end": w_end,
        "certified_at": None,
        "expires_at": None,
        "consumed_by_shipment_id": None,
        "status": "SCHEDULED",
    }
    c.update(new_common_fields())
    store.wash_certs[c["id"]] = c
    return success(ser_wash_cert(c), status=201)


@bp.route("/tank-wash-certificates", methods=["GET"])
def list_certs():
    require_roles(ALL_ROLES)
    trailer_id = request.args.get("trailer_id")
    wash_bay_id = request.args.get("wash_bay_id")
    consumed_by = request.args.get("consumed_by_shipment_id")
    status = request.args.get("status")
    items = []
    for c in store.wash_certs.values():
        refresh_cert_lazy(c)  # lazy EXPIRED surfaces on reads (PRD 2.5)
        if trailer_id is not None and c["trailer_id"] != trailer_id:
            continue
        if wash_bay_id is not None and c["wash_bay_id"] != wash_bay_id:
            continue
        if consumed_by is not None and c["consumed_by_shipment_id"] != consumed_by:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_wash_cert(c) for c in page],
                   response_type="array", pagination=pagination)


@bp.route("/tank-wash-certificates/<cid>", methods=["GET"])
def get_cert(cid):
    require_roles(ALL_ROLES)
    c = get_or_404(store.wash_certs, "wash_certs", cid)
    refresh_cert_lazy(c)
    return success(ser_wash_cert(c))


@bp.route("/tank-wash-certificates/<cid>/certify", methods=["POST"])
def certify_cert(cid):
    require_roles([WASH_OPERATOR])
    c = get_or_404(store.wash_certs, "wash_certs", cid)
    reject_unknown(json_body(), set())
    if c["status"] != "SCHEDULED":
        raise err("ERR_CERT_INVALID_STATE",
                  "Certify requires the certificate to be SCHEDULED")
    c["certified_at"] = store.clock
    c["expires_at"] = store.clock + timedelta(hours=WASH_VALIDITY_HOURS[c["wash_level"]])
    c["status"] = "CERTIFIED"
    touch(c)
    trailer = store.trailers.get(c["trailer_id"])
    if trailer is not None:
        trailer["last_wash_cert_id"] = c["id"]
        touch(trailer)
    return success(ser_wash_cert(c))


@bp.route("/tank-wash-certificates/<cid>/revoke", methods=["POST"])
def revoke_cert(cid):
    require_roles([SAFETY_OFFICER])
    c = get_or_404(store.wash_certs, "wash_certs", cid)
    reject_unknown(json_body(), set())
    if c["status"] not in ("CERTIFIED", "HELD"):
        raise err("ERR_CERT_INVALID_STATE",
                  "Revoke requires the certificate to be CERTIFIED or HELD")
    held_shipment = None
    if c["status"] == "HELD":
        for s in store.shipments.values():
            if s["wash_cert_id"] == c["id"] and s["status"] == "PLANNED":
                held_shipment = s
                break
    # Hop 1: the certificate is voided.
    c["status"] = "VOIDED"
    touch(c)
    if held_shipment is not None:
        # Hop 2: the holding shipment reverts PLANNED -> DRAFT with all
        # assignment fields cleared.
        release_shipment_plan(held_shipment)
        # Hop 3 (inside release_shipment_plan): the released trailer returns
        # ASSIGNED -> AVAILABLE.
        held_shipment["status"] = "DRAFT"
        touch(held_shipment)
        recompute_exposure(held_shipment["customer_id"])
    return success(ser_wash_cert(c))


@bp.route("/tank-wash-certificates/<cid>/cancel-booking", methods=["POST"])
def cancel_booking(cid):
    require_roles([WASH_OPERATOR])
    c = get_or_404(store.wash_certs, "wash_certs", cid)
    reject_unknown(json_body(), set())
    if c["status"] != "SCHEDULED":
        raise err("ERR_CERT_INVALID_STATE",
                  "Cancel-booking requires the certificate to be SCHEDULED")
    c["status"] = "VOIDED"
    touch(c)
    return success(ser_wash_cert(c))
