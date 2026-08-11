"""Resident endpoints (+ resident-scoped bag kits and pickup lists)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body, paginate

bp = Blueprint("residents", __name__)


@bp.route("/residents", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_resident(user_id, role):
    body = get_body()
    check_fields(body, {
        "zone_id": ("str", True),
        "full_name": ("str", True),
        "email": ("str", True),
        "address": ("str", True),
    })
    if body["zone_id"] not in store.zones:
        fail("ERR_NOT_FOUND", "ServiceZone not found: %s" % body["zone_id"])
    rec = new_record()
    rec.update({
        "zone_id": body["zone_id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "address": body["address"],
        "status": "ACTIVE",
        "strikes": 0,
    })
    store.residents[rec["id"]] = rec
    return success(domain.resident_view(rec), code=201)


@bp.route("/residents/<rid>", methods=["GET"])
@endpoint(["ZoneOperator", "Resident"])
def get_resident(user_id, role, rid):
    if role == "Resident" and user_id != rid:
        fail("ERR_UNAUTHORIZED", "Residents may only read their own record")
    rec = domain.get_or_404(store.residents, rid, "Resident")
    return success(domain.resident_view(rec))


@bp.route("/residents/<rid>/reactivate", methods=["POST"])
@endpoint(["ZoneOperator"])
def reactivate_resident(user_id, role, rid):
    get_body()  # no declared fields
    rec = domain.get_or_404(store.residents, rid, "Resident")
    if rec["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Resident is not SUSPENDED")
    rec["status"] = "ACTIVE"
    rec["strikes"] = 0
    touch(rec)
    return success(domain.resident_view(rec))


@bp.route("/residents/<rid>/bag-kits", methods=["GET"])
@endpoint(["ZoneOperator", "Resident"])
def list_resident_kits(user_id, role, rid):
    if role == "Resident" and user_id != rid:
        fail("ERR_UNAUTHORIZED", "Residents may only list their own kits")
    domain.get_or_404(store.residents, rid, "Resident")
    items = [k for k in store.kits.values() if k["resident_id"] == rid]
    page, meta = paginate(items)
    return success([domain.kit_view(k) for k in page], response_type="array",
                   pagination=meta)


@bp.route("/residents/<rid>/bag-kits", methods=["POST"])
@endpoint(["Resident"])
def order_kit(user_id, role, rid):
    # p2: entity-backed ownership — self only
    if user_id != rid:
        fail("ERR_UNAUTHORIZED", "Residents may only order kits for themselves")
    resident = store.residents.get(rid)
    body = get_body()
    check_fields(body, {"kit_type": (("enum", ("BAG", "BIN")), True)})
    if resident is None:
        fail("ERR_NOT_FOUND", "Resident not found: %s" % rid)
    # p5: resident must be ACTIVE
    if resident["status"] != "ACTIVE":
        fail("ERR_RESIDENT_SUSPENDED", "Resident is SUSPENDED")
    # p9b: fewer than 2 kits in flight
    active = sum(1 for k in store.kits.values()
                 if k["resident_id"] == rid and k["status"] in ("REQUESTED", "DISPATCHED", "DELIVERED"))
    if active >= 2:
        fail("ERR_KIT_LIMIT_EXCEEDED", "Resident already has 2 active kits")
    rec = new_record()
    rec.update({
        "resident_id": rid,
        "kit_type": body["kit_type"],
        "status": "REQUESTED",
    })
    store.kits[rec["id"]] = rec
    return success(domain.kit_view(rec), code=201)


@bp.route("/residents/<rid>/pickup-requests", methods=["GET"])
@endpoint(["ZoneOperator", "Resident", "Driver"])
def list_resident_pickups(user_id, role, rid):
    if role == "Resident" and user_id != rid:
        fail("ERR_UNAUTHORIZED", "Residents may only list their own pickups")
    domain.get_or_404(store.residents, rid, "Resident")
    items = [p for p in store.pickups.values() if p["resident_id"] == rid]
    page, meta = paginate(items)
    return success([domain.pickup_view(p) for p in page], response_type="array",
                   pagination=meta)
