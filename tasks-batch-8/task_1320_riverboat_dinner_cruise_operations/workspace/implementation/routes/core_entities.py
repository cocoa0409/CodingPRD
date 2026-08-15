"""Clock, vessels, docks, menu tiers, staff members, customers."""
from flask import Blueprint

import clock
import db
from errors import ApiError, err_invalid_request
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import (require_auth, get_json, paginate, get_or_404, touch,
                  check_enum, check_int, check_number, check_str, check_datetime)

bp = Blueprint("core_entities", __name__)

ALL_ROLES = ["OperationsManager", "Captain", "CharterSalesAgent", "Customer", "GalleyManager", "DockAttendant"]
OM = ["OperationsManager"]


def _system_fields():
    now_z = clock.to_z(clock.now())
    return {"id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(OM)
    body = get_json(required_fields=["to_iso8601"])
    dt = clock.parse_dt(body["to_iso8601"])
    if dt is None:
        raise err_invalid_request("to_iso8601 must be an ISO-8601 datetime")
    clock.set_current(dt)
    svc.process_auto_transitions()
    return ok({"current_utc": clock.to_z(clock.now())}, status=200)


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------

@bp.post("/vessels")
def create_vessel():
    require_auth(OM)
    body = get_json(required_fields=["name", "coast_guard_capacity", "home_dock_id"])
    name = check_str(body, "name")
    capacity = check_int(body, "coast_guard_capacity", minimum=0)
    dock = get_or_404(db.docks, body["home_dock_id"], "dock", "Dock not found")
    vessel = dict(_system_fields(), name=name, coast_guard_capacity=capacity,
                  home_dock_id=dock["id"], status="ACTIVE")
    db.insert(db.vessels, vessel)
    return ok(_sz("vessel", vessel), status=201)


@bp.post("/vessels/<vid>/set-out-of-service")
def vessel_out_of_service(vid):
    require_auth(OM)
    vessel = get_or_404(db.vessels, vid, "vessel", "Vessel not found")
    if vessel["status"] != "ACTIVE":
        from errors import err_invalid_state
        raise err_invalid_state("Vessel is not ACTIVE")
    vessel["status"] = "OUT_OF_SERVICE"
    touch(vessel)
    return ok(_sz("vessel", vessel))


@bp.get("/vessels")
def list_vessels():
    require_auth(ALL_ROLES)
    items = sorted(db.vessels.values(), key=lambda v: v["created_at"])
    page, meta = paginate(items)
    return ok(_szl("vessel", page), pagination=meta)


@bp.get("/vessels/<vid>")
def get_vessel(vid):
    require_auth(ALL_ROLES)
    vessel = get_or_404(db.vessels, vid, "vessel", "Vessel not found")
    return ok(_sz("vessel", vessel))


# ---------------------------------------------------------------------------
# Docks
# ---------------------------------------------------------------------------

@bp.post("/docks")
def create_dock():
    require_auth(OM)
    body = get_json(required_fields=["name", "parking_capacity"])
    dock = dict(_system_fields(), name=check_str(body, "name"),
                parking_capacity=check_int(body, "parking_capacity", minimum=0),
                parking_in_use=0)
    db.insert(db.docks, dock)
    return ok(_sz("dock", dock), status=201)


@bp.get("/docks")
def list_docks():
    require_auth(ALL_ROLES)
    items = sorted(db.docks.values(), key=lambda d: d["created_at"])
    page, meta = paginate(items)
    return ok(_szl("dock", page), pagination=meta)


@bp.get("/docks/<did>")
def get_dock(did):
    require_auth(ALL_ROLES)
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    return ok(_sz("dock", dock))


@bp.get("/docks/<did>/vessels")
def dock_vessels(did):
    require_auth(ALL_ROLES)
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    items = sorted((v for v in db.vessels.values() if v["home_dock_id"] == dock["id"]),
                   key=lambda v: v["created_at"])
    page, meta = paginate(items)
    return ok(_szl("vessel", page), pagination=meta)


@bp.get("/docks/<did>/dock-slots")
def dock_slots_list(did):
    require_auth(["OperationsManager", "Captain", "DockAttendant"])
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    items = sorted((s for s in db.dock_slots.values() if s["dock_id"] == dock["id"]),
                   key=lambda s: s["created_at"])
    page, meta = paginate(items)
    return ok(_szl("dock_slot", page), pagination=meta)


@bp.get("/docks/<did>/parking-passes")
def dock_passes_list(did):
    require_auth(["OperationsManager", "Captain", "DockAttendant"])
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    items = sorted((p for p in db.parking_passes.values() if p["dock_id"] == dock["id"]),
                   key=lambda p: p["created_at"])
    page, meta = paginate(items)
    return ok(_szl("parking_pass", page), pagination=meta)


# ---------------------------------------------------------------------------
# Menu tiers
# ---------------------------------------------------------------------------

@bp.post("/menu-tiers")
def create_menu_tier():
    require_auth(OM)
    body = get_json(required_fields=["code", "base_price_cents", "galley_load_per_cover", "bar_package_price_cents"])
    code = check_enum(body, "code", ["STANDARD", "PREMIUM", "LUXE"])
    tier = dict(_system_fields(), code=code,
                base_price_cents=check_int(body, "base_price_cents", minimum=0),
                galley_load_per_cover=check_number(body, "galley_load_per_cover"),
                bar_package_price_cents=check_int(body, "bar_package_price_cents", minimum=0))
    db.insert(db.menu_tiers, tier)
    return ok(_sz("menu_tier", tier), status=201)


@bp.get("/menu-tiers")
def list_menu_tiers():
    require_auth(ALL_ROLES)
    items = sorted(db.menu_tiers.values(), key=lambda t: t["created_at"])
    page, meta = paginate(items)
    return ok(_szl("menu_tier", page), pagination=meta)


@bp.get("/menu-tiers/<tid>")
def get_menu_tier(tid):
    require_auth(ALL_ROLES)
    tier = get_or_404(db.menu_tiers, tid, "menu_tier", "Menu tier not found")
    return ok(_sz("menu_tier", tier))


@bp.get("/menu-tiers/<tid>/cruises")
def menu_tier_cruises(tid):
    require_auth(ALL_ROLES)
    tier = get_or_404(db.menu_tiers, tid, "menu_tier", "Menu tier not found")
    items = sorted((c for c in db.cruises.values() if c["menu_tier_id"] == tier["id"]),
                   key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("cruise", page), pagination=meta)


# ---------------------------------------------------------------------------
# Staff members
# ---------------------------------------------------------------------------

STAFF_GET = ["OperationsManager", "Captain", "GalleyManager"]
ROLE_CODES = ["SERVER", "BARTENDER", "GALLEY", "ENTERTAINER", "DECKHAND"]


@bp.post("/staff-members")
def create_staff_member():
    require_auth(OM)
    body = get_json(required_fields=["full_name", "role_code"], optional_fields=["alcohol_cert_expires_at"])
    full_name = check_str(body, "full_name")
    role_code = check_enum(body, "role_code", ROLE_CODES)
    cert = body.get("alcohol_cert_expires_at")
    if cert is not None and clock.parse_dt(cert) is None:
        raise err_invalid_request("alcohol_cert_expires_at must be an ISO-8601 datetime")
    member = dict(_system_fields(), full_name=full_name, role_code=role_code,
                  alcohol_cert_expires_at=cert)
    db.insert(db.staff_members, member)
    return ok(_sz("staff_member", member), status=201)


@bp.get("/staff-members")
def list_staff_members():
    require_auth(STAFF_GET)
    items = sorted(db.staff_members.values(), key=lambda s: s["created_at"])
    page, meta = paginate(items)
    return ok(_szl("staff_member", page), pagination=meta)


@bp.get("/staff-members/<sid>")
def get_staff_member(sid):
    require_auth(STAFF_GET)
    member = get_or_404(db.staff_members, sid, "staff_member", "Staff member not found")
    return ok(_sz("staff_member", member))


@bp.get("/staff-members/<sid>/assignments")
def staff_member_assignments(sid):
    require_auth(STAFF_GET)
    member = get_or_404(db.staff_members, sid, "staff_member", "Staff member not found")
    items = sorted((a for a in db.assignments.values() if a["staff_member_id"] == member["id"]),
                   key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return ok(_szl("assignment", page), pagination=meta)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

CUSTOMER_GET = ["OperationsManager", "CharterSalesAgent", "Customer"]


@bp.post("/customers")
def create_customer():
    require_auth(OM)
    body = get_json(required_fields=["email", "full_name"])
    email = check_str(body, "email")
    full_name = check_str(body, "full_name")
    for c in db.customers.values():
        if c["email"] == email:
            raise err_invalid_request("email already registered")
    customer = dict(_system_fields(), email=email, full_name=full_name, credit_balance_cents=0)
    db.insert(db.customers, customer)
    return ok(_sz("customer", customer), status=201)


@bp.get("/customers")
def list_customers():
    require_auth(["OperationsManager", "CharterSalesAgent"])
    items = sorted(db.customers.values(), key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("customer", page), pagination=meta)


@bp.get("/customers/<cid>")
def get_customer(cid):
    require_auth(CUSTOMER_GET)
    customer = get_or_404(db.customers, cid, "customer", "Customer not found")
    return ok(_sz("customer", customer))


@bp.get("/customers/<cid>/bookings")
def customer_bookings(cid):
    require_auth(CUSTOMER_GET)
    customer = get_or_404(db.customers, cid, "customer", "Customer not found")
    items = sorted((b for b in db.bookings.values() if b["customer_id"] == customer["id"]),
                   key=lambda b: b["created_at"])
    page, meta = paginate(items)
    return ok(_szl("booking", page), pagination=meta)


@bp.get("/customers/<cid>/credits")
def customer_credits(cid):
    require_auth(CUSTOMER_GET)
    customer = get_or_404(db.customers, cid, "customer", "Customer not found")
    status_filter = _status_filter("credit_status", ["ISSUED", "SETTLED", "REDEEMED", "EXPIRED"])
    items = [c for c in db.credits.values() if c["customer_id"] == customer["id"]]
    if status_filter is not None:
        items = [c for c in items if c["credit_status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("credit", page), pagination=meta)


def _status_filter(param, allowed):
    from flask import request
    value = request.args.get(param)
    if value is None:
        return None
    if value not in allowed:
        raise err_invalid_request(f"Invalid value for {param}")
    return value
