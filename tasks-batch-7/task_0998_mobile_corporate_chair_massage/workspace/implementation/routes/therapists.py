"""Therapist endpoints (onboarding, lifecycle, reverse-FK lists)."""
from flask import Blueprint

import db
import errors
from auth import require_roles, require_therapist_self
from respond import success
from services.domain import get_or_404, ACTIVE_CHAIR_STATES
from validate import apply_filters, json_body, paginate, req_int, req_str

bp = Blueprint("therapists", __name__)


@bp.post("/chair-massage/therapists")
@require_roles("PlatformAdmin")
def create_therapist():
    body = json_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    home_region_id = req_str(body, "home_region_id")
    rate = req_int(body, "per_hour_rate_cents", min_v=0)
    max_minutes = req_int(body, "max_minutes_per_day", min_v=30)
    get_or_404("regions", home_region_id, "Region")
    for existing in db.stores["therapists"].values():
        if existing["email"] == email:
            raise errors.invalid_request(f"Therapist email '{email}' already exists")
    therapist = db.stamp_new({
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "home_region_id": home_region_id,
        "per_hour_rate_cents": rate,
        "status": "ACTIVE",
        "max_minutes_per_day": max_minutes,
        "rating_avg_x100": 0,
    })
    db.insert("therapists", therapist)
    return success(db.public(therapist), status=201)


@bp.get("/chair-massage/therapists")
@require_roles("PlatformAdmin", "Organizer")
def list_therapists():
    items = db.all_sorted("therapists")
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "home_region_id": (lambda e: e["home_region_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/therapists/<tid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_therapist(tid):
    therapist = get_or_404("therapists", tid, "Therapist")
    require_therapist_self(tid)
    return success(db.public(therapist))


@bp.post("/chair-massage/therapists/<tid>/suspend")
@require_roles("PlatformAdmin")
def suspend_therapist(tid):
    therapist = get_or_404("therapists", tid, "Therapist")
    if therapist["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE therapist can be suspended")
    therapist["status"] = "SUSPENDED"
    db.touch(therapist)
    return success(db.public(therapist))


@bp.post("/chair-massage/therapists/<tid>/reactivate")
@require_roles("PlatformAdmin")
def reactivate_therapist(tid):
    therapist = get_or_404("therapists", tid, "Therapist")
    if therapist["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED therapist can be reactivated")
    therapist["status"] = "ACTIVE"
    db.touch(therapist)
    return success(db.public(therapist))


@bp.post("/chair-massage/therapists/<tid>/deactivate")
@require_roles("PlatformAdmin")
def deactivate_therapist(tid):
    therapist = get_or_404("therapists", tid, "Therapist")
    if therapist["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED therapist can be deactivated")
    busy = any(
        c for c in db.stores["chair_slots"].values()
        if c["therapist_id"] == tid and c["status"] in ACTIVE_CHAIR_STATES)
    if busy:
        raise errors.invalid_state(
            "Therapist holds chair slots in ASSIGNED/EN_ROUTE/ON_SITE status")
    therapist["status"] = "DEACTIVATED"
    db.touch(therapist)
    return success(db.public(therapist))


@bp.get("/chair-massage/therapists/<tid>/licenses")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_therapist_licenses(tid):
    get_or_404("therapists", tid, "Therapist")
    require_therapist_self(tid)
    items = [l for l in db.all_sorted("therapist_licenses") if l["therapist_id"] == tid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/therapists/<tid>/chair-slots")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_therapist_chair_slots(tid):
    get_or_404("therapists", tid, "Therapist")
    require_therapist_self(tid)
    items = [c for c in db.all_sorted("chair_slots") if c["therapist_id"] == tid]
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "event_date": (lambda e: (db.get("bookings", e["booking_id"]) or {}).get("event_date"), "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/therapists/<tid>/travel-legs")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_therapist_travel_legs(tid):
    get_or_404("therapists", tid, "Therapist")
    require_therapist_self(tid)
    items = [l for l in db.all_sorted("travel_legs") if l["therapist_id"] == tid]
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "booking_id": (lambda e: e["booking_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/therapists/<tid>/payout-ledger-entries")
@require_roles("PlatformAdmin", "Therapist")
def list_therapist_payouts(tid):
    get_or_404("therapists", tid, "Therapist")
    require_therapist_self(tid)
    items = [p for p in db.all_sorted("payout_ledger_entries")
             if p["therapist_id"] == tid]
    items = apply_filters(items, {
        "entry_kind": (lambda e: e["entry_kind"], "str"),
        "booking_id": (lambda e: e["booking_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)
