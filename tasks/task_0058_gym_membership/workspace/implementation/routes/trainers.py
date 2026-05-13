"""Trainer and slot endpoints."""
from flask import Blueprint, request, g
from clock import from_iso, to_iso_ms
from db import state, new_id, stamp_create, bump
from errors import raise_err
from response import success_object, success_array
from middleware import require_roles, is_role
from routes.helpers import get_json, parse_pagination, paginate, sort_by_created, check_occ
from serializers import serialize_trainer, serialize_slot, serialize_commission_record
from services import pt as pt_svc


bp = Blueprint("trainers", __name__)


@bp.route("/trainers", methods=["POST"])
def create_trainer():
    require_roles("PlatformAdmin")
    body = get_json()
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name:
        raise_err("ERR_VALIDATION", "full_name required")
    specialties = body.get("specialties")
    if not isinstance(specialties, list) or not specialties:
        raise_err("ERR_VALIDATION", "specialties must be non-empty array")
    s_bp = body.get("session_commission_pct_bp")
    p_bp = body.get("package_commission_pct_bp")
    if not isinstance(s_bp, int) or not (0 <= s_bp <= 10000):
        raise_err("ERR_VALIDATION", "session_commission_pct_bp 0..10000")
    if not isinstance(p_bp, int) or not (0 <= p_bp <= 10000):
        raise_err("ERR_VALIDATION", "package_commission_pct_bp 0..10000")
    t = {
        "id": new_id(),
        "full_name": full_name,
        "specialties": specialties,
        "session_commission_pct_bp": s_bp,
        "package_commission_pct_bp": p_bp,
        "tier": "BRONZE",
        "status": "ACTIVE",
    }
    # Optional session_price_default for SINGLE bookings
    if "session_price_default" in body and isinstance(body["session_price_default"], int):
        t["session_price_default"] = body["session_price_default"]
    stamp_create(t)
    state["trainers"][t["id"]] = t
    return success_object(serialize_trainer(t), status=201)


@bp.route("/trainers/<id_>", methods=["GET"])
def get_trainer(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member", "Trainer")
    t = state["trainers"].get(id_)
    if not t:
        raise_err("ERR_NOT_FOUND", "trainer not found")
    if is_role("Trainer") and g.user_id != id_:
        raise_err("ERR_FORBIDDEN", "trainer not self")
    return success_object(serialize_trainer(t))


@bp.route("/trainers/<id_>", methods=["PATCH"])
def patch_trainer(id_):
    require_roles("PlatformAdmin")
    t = state["trainers"].get(id_)
    if not t:
        raise_err("ERR_NOT_FOUND", "trainer not found")
    body = get_json()
    check_occ(t, body)
    if "specialties" in body and body["specialties"] is not None:
        if not isinstance(body["specialties"], list) or not body["specialties"]:
            raise_err("ERR_VALIDATION", "specialties must be non-empty array")
        t["specialties"] = body["specialties"]
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("ACTIVE", "INACTIVE"):
            raise_err("ERR_VALIDATION", "invalid status")
        t["status"] = body["status"]
    if "session_commission_pct_bp" in body and body["session_commission_pct_bp"] is not None:
        v = body["session_commission_pct_bp"]
        if not isinstance(v, int) or not (0 <= v <= 10000):
            raise_err("ERR_VALIDATION", "session_commission_pct_bp 0..10000")
        t["session_commission_pct_bp"] = v
    if "package_commission_pct_bp" in body and body["package_commission_pct_bp"] is not None:
        v = body["package_commission_pct_bp"]
        if not isinstance(v, int) or not (0 <= v <= 10000):
            raise_err("ERR_VALIDATION", "package_commission_pct_bp 0..10000")
        t["package_commission_pct_bp"] = v
    if "session_price_default" in body and body["session_price_default"] is not None:
        v = body["session_price_default"]
        if not isinstance(v, int) or v < 0:
            raise_err("ERR_VALIDATION", "session_price_default >= 0")
        t["session_price_default"] = v
    bump(t)
    return success_object(serialize_trainer(t))


@bp.route("/trainer-slots", methods=["POST"])
def create_slot():
    require_roles("PlatformAdmin", "StaffOps", "Trainer")
    body = get_json()
    trainer_id = body.get("trainer_id")
    if not trainer_id:
        raise_err("ERR_VALIDATION", "trainer_id required")
    if is_role("Trainer") and trainer_id != g.user_id:
        raise_err("ERR_FORBIDDEN", "trainer can only create own slots")
    starts_at = body.get("starts_at")
    ends_at = body.get("ends_at")
    specialty_code = body.get("specialty_code")
    if not starts_at or not ends_at or not specialty_code:
        raise_err("ERR_VALIDATION", "starts_at, ends_at, specialty_code required")
    try:
        starts_at_dt = from_iso(starts_at)
        ends_at_dt = from_iso(ends_at)
    except ValueError:
        raise_err("ERR_VALIDATION", "invalid timestamp")
    if ends_at_dt <= starts_at_dt:
        raise_err("ERR_VALIDATION", "ends_at must follow starts_at")
    slot = pt_svc.create_slot(trainer_id, starts_at_dt, ends_at_dt, specialty_code)
    return success_object(serialize_slot(slot), status=201)


@bp.route("/trainer-slots", methods=["GET"])
def list_slots():
    require_roles("PlatformAdmin", "StaffOps", "Member", "Trainer")
    limit, offset = parse_pagination()
    items = list(state["trainer_slots"].values())
    t_id = request.args.get("trainer_id")
    if t_id:
        items = [s for s in items if s["trainer_id"] == t_id]
    sp = request.args.get("specialty_code")
    if sp:
        items = [s for s in items if s["specialty_code"] == sp]
    st = request.args.get("status")
    if st:
        items = [s for s in items if s["status"] == st]
    sa = request.args.get("starts_after")
    if sa:
        try:
            dt = from_iso(sa)
            items = [s for s in items if s["starts_at"] >= dt]
        except ValueError:
            raise_err("ERR_VALIDATION", "invalid starts_after")
    sb = request.args.get("starts_before")
    if sb:
        try:
            dt = from_iso(sb)
            items = [s for s in items if s["starts_at"] < dt]
        except ValueError:
            raise_err("ERR_VALIDATION", "invalid starts_before")
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_slot(x) for x in sliced], meta)


@bp.route("/trainers/<id_>/commissions", methods=["GET"])
def trainer_commissions(id_):
    require_roles("PlatformAdmin", "Trainer")
    t = state["trainers"].get(id_)
    if not t:
        raise_err("ERR_NOT_FOUND", "trainer not found")
    if is_role("Trainer") and g.user_id != id_:
        raise_err("ERR_FORBIDDEN", "trainer can read own only")
    limit, offset = parse_pagination()
    items = [r for r in state["commission_records"].values() if r["trainer_id"] == id_]
    pc = request.args.get("payout_cycle_id")
    if pc:
        items = [r for r in items if r.get("payout_cycle_id") == pc]
    k = request.args.get("kind")
    if k:
        items = [r for r in items if r["kind"] == k]
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_commission_record(x) for x in sliced], meta)
