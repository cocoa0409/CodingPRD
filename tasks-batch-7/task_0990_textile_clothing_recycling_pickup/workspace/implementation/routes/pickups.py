"""PickupRequest lifecycle endpoints."""
from flask import Blueprint

from db import store, new_record, touch, now_dt, now_iso
from errors import fail
from middleware import endpoint
from response import success
from services import calc, domain
from util import check_fields, get_body, paginate, parse_dt

bp = Blueprint("pickups", __name__)


def _own_pickup_or_403(user_id, pickup):
    if pickup is not None and pickup["resident_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "Residents may only act on their own pickups")


def _new_window_checks(body, resident_id, exclude_id=None):
    """p8 temporal + p9a buffered overlap (shared by create/reschedule/rebook)."""
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    domain.check_window_shape(ws, we)
    domain.check_window_not_past(ws)
    domain.check_window_conflict(resident_id, ws, we, exclude_id=exclude_id)
    return ws, we


@bp.route("/pickup-requests", methods=["POST"])
@endpoint(["Resident"])
def create_pickup(user_id, role):
    body = get_body()
    # p2: entity-backed ownership — body resident_id must equal X-User-ID
    if "resident_id" in body and body["resident_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "resident_id must equal the acting resident")
    check_fields(body, {
        "resident_id": ("str", True),
        "window_start": ("dt", True),
        "window_end": ("dt", True),
        "bags_claimed": ("int", True),
    })
    if body["bags_claimed"] < 1:
        fail("ERR_INVALID_REQUEST", "bags_claimed must be >= 1")
    resident = store.residents.get(body["resident_id"])
    if resident is None:
        fail("ERR_NOT_FOUND", "Resident not found: %s" % body["resident_id"])
    # p5: resident must be ACTIVE
    if resident["status"] != "ACTIVE":
        fail("ERR_RESIDENT_SUSPENDED", "Resident is SUSPENDED")
    ws, we = _new_window_checks(body, resident["id"])
    rec = new_record()
    rec.update({
        "resident_id": resident["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "bags_claimed": body["bags_claimed"],
        "est_weight_kg": calc.est_weight(body["bags_claimed"]),
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "rebook_count": 0,
        "driver_id": None,
        "service_date": None,
        "_ws": ws,
        "_we": we,
    })
    store.pickups[rec["id"]] = rec
    return success(domain.pickup_view(rec), code=201)


@bp.route("/pickup-requests/<pid>", methods=["GET"])
@endpoint(["ZoneOperator", "Resident", "Driver"])
def get_pickup(user_id, role, pid):
    pickup = store.pickups.get(pid)
    if role == "Resident":
        _own_pickup_or_403(user_id, pickup)
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    return success(domain.pickup_view(pickup))


@bp.route("/pickup-requests/<pid>/reschedule", methods=["POST"])
@endpoint(["Resident"])
def reschedule_pickup(user_id, role, pid):
    pickup = store.pickups.get(pid)
    _own_pickup_or_403(user_id, pickup)
    body = get_body()
    check_fields(body, {
        "window_start": ("dt", True),
        "window_end": ("dt", True),
        "expected_pickup_version": ("int", True),
    })
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    # p5: state
    if pickup["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Pickup must be SCHEDULED to reschedule")
    # p6: OCC
    if body["expected_pickup_version"] != pickup["version"]:
        fail("ERR_STALE_VERSION", "expected_pickup_version does not match current version")
    # p8 + p9a
    ws, we = _new_window_checks(body, pickup["resident_id"], exclude_id=pickup["id"])
    # p9c: reschedule cap
    if pickup["reschedule_count"] >= calc.MAX_RESCHEDULES:
        fail("ERR_RESCHEDULE_LIMIT_REACHED", "reschedule_count cap reached")
    pickup["window_start"] = body["window_start"]
    pickup["window_end"] = body["window_end"]
    pickup["_ws"] = ws
    pickup["_we"] = we
    pickup["reschedule_count"] += 1
    touch(pickup)
    return success(domain.pickup_view(pickup))


@bp.route("/pickup-requests/<pid>/cancel", methods=["POST"])
@endpoint(["Resident"])
def cancel_pickup(user_id, role, pid):
    pickup = store.pickups.get(pid)
    _own_pickup_or_403(user_id, pickup)
    get_body()
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    if pickup["status"] not in ("SCHEDULED", "ROUTED"):
        fail("ERR_INVALID_STATE", "Pickup must be SCHEDULED or ROUTED to cancel")
    if pickup["status"] == "ROUTED":
        pickup["driver_id"] = None
        pickup["service_date"] = None
    pickup["status"] = "CANCELLED"
    touch(pickup)
    return success(domain.pickup_view(pickup))


@bp.route("/pickup-requests/<pid>/rebook", methods=["POST"])
@endpoint(["Resident"])
def rebook_pickup(user_id, role, pid):
    pickup = store.pickups.get(pid)
    _own_pickup_or_403(user_id, pickup)
    body = get_body()
    check_fields(body, {
        "window_start": ("dt", True),
        "window_end": ("dt", True),
    })
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    # p5: state, then resident must be ACTIVE
    if pickup["status"] != "NO_SHOW":
        fail("ERR_INVALID_STATE", "Pickup must be NO_SHOW to rebook")
    resident = store.residents.get(pickup["resident_id"])
    if resident is None or resident["status"] != "ACTIVE":
        fail("ERR_RESIDENT_SUSPENDED", "Resident is SUSPENDED")
    ws, we = _new_window_checks(body, pickup["resident_id"], exclude_id=pickup["id"])
    # p9d: rebook cap
    if pickup["rebook_count"] >= calc.MAX_REBOOKS:
        fail("ERR_REBOOK_LIMIT_REACHED", "rebook_count cap reached")
    pickup["window_start"] = body["window_start"]
    pickup["window_end"] = body["window_end"]
    pickup["_ws"] = ws
    pickup["_we"] = we
    pickup["status"] = "SCHEDULED"
    pickup["rebook_count"] += 1
    touch(pickup)
    return success(domain.pickup_view(pickup))


@bp.route("/pickup-requests/<pid>/route", methods=["POST"])
@endpoint(["ZoneOperator"])
def route_pickup(user_id, role, pid):
    pickup = store.pickups.get(pid)
    body = get_body()
    check_fields(body, {
        "driver_id": ("str", True),
        "service_date": ("date", True),
    })
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    if pickup["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Pickup must be SCHEDULED to route")
    # p11: route-day vehicle capacity (exactly 800.0 allowed)
    driver_id = body["driver_id"]
    service_date = body["service_date"]
    total = calc.dec("0")
    for p in store.pickups.values():
        if (p["status"] == "ROUTED" and p.get("driver_id") == driver_id
                and p.get("service_date") == service_date):
            total += calc.dec(p["est_weight_kg"])
    if total + calc.dec(pickup["est_weight_kg"]) > calc.VEHICLE_CAPACITY_KG:
        fail("ERR_ROUTE_CAPACITY_EXCEEDED", "route-day capacity would exceed 800.0 kg")
    pickup["status"] = "ROUTED"
    pickup["driver_id"] = driver_id
    pickup["service_date"] = service_date
    touch(pickup)
    return success(domain.pickup_view(pickup))


def _driver_ownership(user_id, pickup):
    """Assigned-driver binding: only when the pickup is routed (driver_id set)."""
    if pickup is not None and pickup.get("driver_id") is not None \
            and pickup["driver_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "Only the assigned driver may perform this action")


@bp.route("/pickup-requests/<pid>/mark-collected", methods=["POST"])
@endpoint(["Driver"])
def mark_collected(user_id, role, pid):
    pickup = store.pickups.get(pid)
    _driver_ownership(user_id, pickup)
    body = get_body()
    check_fields(body, {"provisional_weight_kg": ("num", True)})
    if calc.dec(body["provisional_weight_kg"]) <= 0:
        fail("ERR_INVALID_REQUEST", "provisional_weight_kg must be > 0")
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    if pickup["status"] != "ROUTED":
        fail("ERR_INVALID_STATE", "Pickup must be ROUTED to mark collected")
    # p10: resident must own at least one DELIVERED kit
    delivered = any(k["resident_id"] == pickup["resident_id"] and k["status"] == "DELIVERED"
                    for k in store.kits.values())
    if not delivered:
        fail("ERR_BAGS_NOT_DELIVERED", "Resident has no DELIVERED bag kit")
    # effects: pickup -> COLLECTED; ticket created; DELIVERED kits -> RETIRED
    pickup["status"] = "COLLECTED"
    touch(pickup)
    ticket = new_record()
    ticket.update({
        "source_type": "PICKUP_REQUEST",
        "source_id": pickup["id"],
        "provisional_weight_kg": body["provisional_weight_kg"],
        "certified_weight_kg": None,
        "grade": None,
        "status": "PROVISIONAL",
        "projected_credit_cents": calc.projected_credit_cents(body["provisional_weight_kg"]),
        "highest_upheld_severity": "NONE",
        "certified_at": None,
        "_certified_at": None,
    })
    store.tickets[ticket["id"]] = ticket
    for k in store.kits.values():
        if k["resident_id"] == pickup["resident_id"] and k["status"] == "DELIVERED":
            k["status"] = "RETIRED"
            touch(k)
    return success(domain.ticket_view(ticket), code=201)


@bp.route("/pickup-requests/<pid>/mark-no-show", methods=["POST"])
@endpoint(["Driver"])
def mark_no_show(user_id, role, pid):
    pickup = store.pickups.get(pid)
    _driver_ownership(user_id, pickup)
    get_body()
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    if pickup["status"] != "ROUTED":
        fail("ERR_INVALID_STATE", "Pickup must be ROUTED to mark no-show")
    pickup["status"] = "NO_SHOW"
    pickup["driver_id"] = None
    pickup["service_date"] = None
    touch(pickup)
    return success(domain.pickup_view(pickup))


@bp.route("/pickup-requests/<pid>/weight-tickets", methods=["GET"])
@endpoint(["ZoneOperator", "Resident", "Driver", "Inspector"])
def list_pickup_tickets(user_id, role, pid):
    pickup = store.pickups.get(pid)
    if role == "Resident":
        _own_pickup_or_403(user_id, pickup)
    if pickup is None:
        fail("ERR_NOT_FOUND", "PickupRequest not found: %s" % pid)
    items = [t for t in store.tickets.values()
             if t["source_type"] == "PICKUP_REQUEST" and t["source_id"] == pid]
    page, meta = paginate(items)
    return success([domain.ticket_view(t) for t in page], response_type="array",
                   pagination=meta)
