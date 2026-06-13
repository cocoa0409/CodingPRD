"""Catalog & identity resources: Customer, MeasurementProfile, Fabric, Tailor,
FittingRoom."""
from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, stamp_create, touch
from errors import fail
from lookups import get_customer, get_fabric, get_tailor, get_room
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services import orders as osvc

bp = Blueprint("catalog", __name__)


def _filtered_sorted(values, predicate=None):
    items = [v for v in values if (predicate is None or predicate(v))]
    items.sort(key=lambda v: v["created_at"])
    return items


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate"})
    body = get_json_body()
    full_name = V.req_str(body, "full_name")
    email = V.req_str(body, "email")
    rec = stamp_create()
    rec.update({
        "full_name": full_name,
        "email": email,
        "store_credit_cents": 0,
        "remake_count": 0,
        "completed_order_count": 0,
        "remake_risk_band": "STANDARD",
    })
    db.customers[rec["id"]] = rec
    return success(S.customer(rec), status=201)


@bp.get("/customers/<cid>")
def get_customer_route(cid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    c = get_customer(cid)
    return success(S.customer(c))


@bp.get("/customers")
def list_customers():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate"})
    limit, offset = V.parse_pagination()
    email = request.args.get("email")
    items = _filtered_sorted(
        db.customers.values(),
        (lambda c: c["email"] == email) if email is not None else None,
    )
    page = V.paginate(items, limit, offset)
    return list_response([S.customer(c) for c in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# MeasurementProfile
# ---------------------------------------------------------------------------

@bp.post("/measurement-profiles")
def create_profile():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "Customer"})
    body = get_json_body()
    customer_id = V.req_str(body, "customer_id")
    chest = V.req_number(body, "chest_cm", gt=0)
    waist = V.req_number(body, "waist_cm", gt=0)
    hip = V.req_number(body, "hip_cm", gt=0)
    inseam = V.req_number(body, "inseam_cm", gt=0)
    source = V.opt_enum(body, "source", {"MANUAL", "BODY_SCAN"}, default="MANUAL")
    body_scan_ref = V.opt_str(body, "body_scan_ref", default=None)

    # FK existence (priority 4)
    get_customer(customer_id)

    # body-scan reference rule (priority 6)
    if source == "BODY_SCAN" and not body_scan_ref:
        fail(errors.ERR_SCAN_REF_REQUIRED, "body_scan_ref required when source=BODY_SCAN")
    if source == "MANUAL" and body_scan_ref is not None:
        fail(errors.ERR_SCAN_REF_REQUIRED, "body_scan_ref forbidden when source=MANUAL")

    rec = stamp_create()
    rec.update({
        "customer_id": customer_id,
        "chest_cm": chest,
        "waist_cm": waist,
        "hip_cm": hip,
        "inseam_cm": inseam,
        "source": source,
        "body_scan_ref": body_scan_ref,
        "status": "DRAFT",
    })
    db.measurement_profiles[rec["id"]] = rec
    return success(S.measurement_profile(rec), status=201)


@bp.get("/measurement-profiles/<pid>")
def get_profile_route(pid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    p = db.measurement_profiles.get(pid)
    if p is None:
        fail(errors.ERR_PROFILE_NOT_FOUND, "Measurement profile not found")
    return success(S.measurement_profile(p))


@bp.get("/measurement-profiles")
def list_profiles():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "Customer"})
    limit, offset = V.parse_pagination()
    customer_id = request.args.get("customer_id")
    items = _filtered_sorted(
        db.measurement_profiles.values(),
        (lambda p: p["customer_id"] == customer_id) if customer_id is not None else None,
    )
    page = V.paginate(items, limit, offset)
    return list_response([S.measurement_profile(p) for p in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Fabric
# ---------------------------------------------------------------------------

@bp.post("/fabrics")
def create_fabric():
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    name = V.req_str(body, "name")
    price = V.req_int(body, "price_per_meter_cents", minimum=1)
    bolt_initial = V.req_number(body, "bolt_meters_initial", gt=-0.000001)
    status = V.opt_enum(body, "status", {"AVAILABLE", "DISCONTINUED"}, default="AVAILABLE")
    rec = stamp_create()
    rec.update({
        "name": name,
        "price_per_meter_cents": price,
        "bolt_meters_remaining": bolt_initial,
        "status": status,
    })
    db.fabrics[rec["id"]] = rec
    return success(S.fabric(rec), status=201)


@bp.get("/fabrics/<fid>")
def get_fabric_route(fid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    f = get_fabric(fid)
    return success(S.fabric(f))


@bp.get("/fabrics")
def list_fabrics():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    items = _filtered_sorted(
        db.fabrics.values(),
        (lambda f: f["status"] == status) if status is not None else None,
    )
    page = V.paginate(items, limit, offset)
    return list_response([S.fabric(f) for f in page], len(items), limit, offset)


@bp.patch("/fabrics/<fid>")
def patch_fabric(fid):
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    f = get_fabric(fid)
    body = get_json_body()
    changed = False
    if "price_per_meter_cents" in body and body["price_per_meter_cents"] is not None:
        price = V.req_int(body, "price_per_meter_cents", minimum=1)
        f["price_per_meter_cents"] = price
        changed = True
    if "status" in body and body["status"] is not None:
        status = V.req_enum(body, "status", {"AVAILABLE", "DISCONTINUED"})
        f["status"] = status
        changed = True
    if changed:
        touch(f)
    return success(S.fabric(f))


@bp.get("/fabrics/<fid>/option-lines")
def list_fabric_option_lines(fid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate"})
    get_fabric(fid)
    limit, offset = V.parse_pagination()
    items = _filtered_sorted(
        db.option_lines.values(),
        lambda l: l["fabric_id"] == fid,
    )
    page = V.paginate(items, limit, offset)
    return list_response([S.option_line(l) for l in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Tailor
# ---------------------------------------------------------------------------

@bp.post("/tailors")
def create_tailor():
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    display_name = V.req_str(body, "display_name")
    skill_tier = V.opt_enum(body, "skill_tier", {"APPRENTICE", "JOURNEYMAN", "MASTER"},
                            default="JOURNEYMAN")
    status = V.opt_enum(body, "status", {"ACTIVE", "INACTIVE"}, default="ACTIVE")
    rec = stamp_create()
    rec.update({
        "display_name": display_name,
        "skill_tier": skill_tier,
        "status": status,
    })
    db.tailors[rec["id"]] = rec
    return success(S.tailor(rec), status=201)


@bp.get("/tailors/<tid>")
def get_tailor_route(tid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    t = get_tailor(tid)
    return success(S.tailor(t))


@bp.get("/tailors")
def list_tailors():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    skill_tier = request.args.get("skill_tier")

    def pred(t):
        if status is not None and t["status"] != status:
            return False
        if skill_tier is not None and t["skill_tier"] != skill_tier:
            return False
        return True

    items = _filtered_sorted(db.tailors.values(), pred)
    page = V.paginate(items, limit, offset)
    return list_response([S.tailor(t) for t in page], len(items), limit, offset)


@bp.get("/tailors/<tid>/fittings")
def list_tailor_fittings(tid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    get_tailor(tid)
    limit, offset = V.parse_pagination()
    outcome = request.args.get("outcome")

    def pred(f):
        if f["tailor_id"] != tid:
            return False
        if outcome is not None and f["outcome"] != outcome:
            return False
        return True

    items = _filtered_sorted(db.fittings.values(), pred)
    page = V.paginate(items, limit, offset)
    return list_response([S.fitting(f) for f in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# FittingRoom
# ---------------------------------------------------------------------------

@bp.post("/fitting-rooms")
def create_room():
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    room_name = V.req_str(body, "room_name")
    buffer = V.opt_int(body, "cleanup_buffer_minutes", default=15, minimum=0)
    status = V.opt_enum(body, "status", {"OPEN", "CLOSED"}, default="OPEN")
    rec = stamp_create()
    rec.update({
        "room_name": room_name,
        "cleanup_buffer_minutes": buffer,
        "status": status,
    })
    db.fitting_rooms[rec["id"]] = rec
    return success(S.fitting_room(rec), status=201)


@bp.get("/fitting-rooms/<rid>")
def get_room_route(rid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    r = get_room(rid)
    return success(S.fitting_room(r))


@bp.get("/fitting-rooms")
def list_rooms():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    items = _filtered_sorted(
        db.fitting_rooms.values(),
        (lambda r: r["status"] == status) if status is not None else None,
    )
    page = V.paginate(items, limit, offset)
    return list_response([S.fitting_room(r) for r in page], len(items), limit, offset)


@bp.get("/fitting-rooms/<rid>/fittings")
def list_room_fittings(rid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist"})
    get_room(rid)
    limit, offset = V.parse_pagination()
    outcome = request.args.get("outcome")

    def pred(f):
        if f["room_id"] != rid:
            return False
        if outcome is not None and f["outcome"] != outcome:
            return False
        return True

    items = _filtered_sorted(db.fittings.values(), pred)
    page = V.paginate(items, limit, offset)
    return list_response([S.fitting(f) for f in page], len(items), limit, offset)
