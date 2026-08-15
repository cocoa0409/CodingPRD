"""Clock, parties, fairs, and venue slots."""

from flask import Blueprint, g

import db
from db import fmt_dt
from errors import fail
from middleware import ALL_ROLES, require_roles, require_scope
from response import success, success_list
from services import (
    cascade_fair_cancel,
    compute_provisional_lines,
    new_entity,
    run_preorder_allocation,
    sweep_agreement_expiry,
    touch,
    venue_conflict,
)
from util import (
    get_body,
    list_filtered,
    page,
    pagination_params,
    parse_dt,
    v_date,
    v_datetime,
    v_enum,
    v_int,
    v_str,
    validate_body,
)

bp = Blueprint("core", __name__)


def get_or_404(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        fail("ERR_NOT_FOUND", "%s not found" % label)
    return entity


# ---------------------------------------------------------------------------
# Logical clock (Organizer-only test driver)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("Organizer")
def set_clock():
    data = get_body()
    vals = validate_body(data, [("to_iso8601", True, v_datetime)])
    db.logical_clock = vals["to_iso8601"]
    expired = sweep_agreement_expiry()
    return success(
        {"current_utc": fmt_dt(db.logical_clock), "expired_agreement_ids": expired}
    )


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------

@bp.post("/parties")
@require_roles("Organizer")
def create_party():
    data = get_body()
    vals = validate_body(
        data,
        [
            ("kind", True, v_enum("SCHOOL", "PUBLISHER", "AUTHOR")),
            ("name", True, v_str),
            ("contact_email", True, v_str),
        ],
    )
    party = new_entity(
        kind=vals["kind"], name=vals["name"], contact_email=vals["contact_email"]
    )
    db.parties[party["id"]] = party
    return success(party, 201)


@bp.get("/parties/<pid>")
@require_roles(*ALL_ROLES)
def get_party(pid):
    return success(get_or_404(db.parties, pid, "Party"))


# ---------------------------------------------------------------------------
# Fairs
# ---------------------------------------------------------------------------

@bp.post("/fairs")
@require_roles("Organizer")
def create_fair():
    data = get_body()
    # Body FK existence (priority 5) precedes full shape validation (7).
    school_id = data.get("school_party_id")
    if isinstance(school_id, str) and school_id not in db.parties:
        fail("ERR_NOT_FOUND", "school_party_id references no existing Party")
    vals = validate_body(
        data,
        [
            ("school_party_id", True, v_str),
            ("title", True, v_str),
            ("venue_key", True, v_str),
            ("planned_start_date", True, v_date),
            ("planned_end_date", True, v_date),
            ("signing_floor_capacity_units", True, v_int(1)),
            ("promo_budget_cents", True, v_int(0)),
        ],
    )
    school = db.parties[vals["school_party_id"]]
    if school["kind"] != "SCHOOL":
        fail("ERR_VALIDATION", "school_party_id must reference a Party of kind SCHOOL")
    if vals["planned_end_date"] < vals["planned_start_date"]:
        fail("ERR_VALIDATION", "planned_end_date must be >= planned_start_date")
    fair = new_entity(
        school_party_id=vals["school_party_id"],
        title=vals["title"],
        venue_key=vals["venue_key"],
        planned_start_date=vals["planned_start_date"],
        planned_end_date=vals["planned_end_date"],
        signing_floor_capacity_units=vals["signing_floor_capacity_units"],
        promo_budget_cents=vals["promo_budget_cents"],
        status="DRAFT",
        gross_sales_cents=0,
        firm_purchases_cents=0,
        publisher_remittance_cents=0,
        return_credits_cents=0,
        honorarium_total_cents=0,
        preorder_allocation_run=False,
    )
    db.fairs[fair["id"]] = fair
    return success(fair, 201)


@bp.get("/fairs")
@require_roles(*ALL_ROLES)
def list_fairs():
    limit, offset = pagination_params()
    items = list_filtered(db.fairs, [("school_party_id", "school_party_id"), ("status", "status")])
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/fairs/<fid>")
@require_roles(*ALL_ROLES)
def get_fair(fid):
    return success(get_or_404(db.fairs, fid, "Fair"))


def _fair_action(fid):
    return get_or_404(db.fairs, fid, "Fair")


@bp.post("/fairs/<fid>/schedule")
@require_roles("Organizer")
def fair_schedule(fid):
    fair = _fair_action(fid)
    validate_body(get_body(), [])
    if fair["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Fair is not in DRAFT")
    confirmed = any(
        s["fair_id"] == fair["id"] and s["status"] == "CONFIRMED"
        for s in db.venue_slots.values()
    )
    if not confirmed:
        fail("ERR_INVALID_STATE", "Scheduling requires at least one CONFIRMED venue slot")
    fair["status"] = "SCHEDULED"
    touch(fair)
    return success(fair)


@bp.post("/fairs/<fid>/open-stocking")
@require_roles("Organizer")
def fair_open_stocking(fid):
    fair = _fair_action(fid)
    validate_body(get_body(), [])
    if fair["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Fair is not in SCHEDULED")
    accepted = any(
        a["fair_id"] == fair["id"] and a["status"] == "ACCEPTED" for a in db.agreements.values()
    )
    if not accepted:
        fail("ERR_INVALID_STATE", "Stocking requires at least one ACCEPTED consignment agreement")
    fair["status"] = "STOCKING"
    touch(fair)
    return success(fair)


@bp.post("/fairs/<fid>/open")
@require_roles("Organizer")
def fair_open(fid):
    fair = _fair_action(fid)
    validate_body(get_body(), [])
    if fair["status"] != "STOCKING":
        fail("ERR_INVALID_STATE", "Fair is not in STOCKING")
    committed = any(
        l["fair_id"] == fair["id"] and l["status"] == "COMMITTED"
        for l in db.stock_lines.values()
    )
    if committed:
        fail("ERR_INVALID_STATE", "Every COMMITTED stock line must be delivered before opening")
    fair["status"] = "OPEN"
    fair["preorder_allocation_run"] = True
    touch(fair)
    run_preorder_allocation(fair)
    return success(fair)


@bp.post("/fairs/<fid>/close-sales")
@require_roles("Organizer")
def fair_close_sales(fid):
    fair = _fair_action(fid)
    validate_body(get_body(), [])
    if fair["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Fair is not in OPEN")
    open_sessions = any(
        s["fair_id"] == fair["id"] and s["status"] in ("SCHEDULED", "OPEN_FOR_SIGNING")
        for s in db.sessions.values()
    )
    if open_sessions:
        fail(
            "ERR_INVALID_STATE",
            "No signing session may remain SCHEDULED or OPEN_FOR_SIGNING at close-sales",
        )
    existing = any(r["fair_id"] == fair["id"] for r in db.reconciliations.values())
    if existing:
        fail("ERR_DUPLICATE_RESOURCE", "A reconciliation already exists for this fair")
    # Sweep unfulfilled ALLOCATED preorders (holds released).
    from services import cancel_preorder

    for preorder in list(db.preorders.values()):
        if preorder["fair_id"] == fair["id"] and preorder["status"] == "ALLOCATED":
            cancel_preorder(preorder)
    recon = new_entity(
        fair_id=fair["id"],
        created_by_user_id=g.user_id,
        provisional_lines=compute_provisional_lines(fair["id"]),
        counted_lines=[],
        variance_lines=[],
        total_abs_variance=0,
        remittance_cents=None,
        dispute_reason=None,
        status="OPEN",
    )
    db.reconciliations[recon["id"]] = recon
    fair["status"] = "RECONCILING"
    touch(fair)
    return success(fair)


@bp.post("/fairs/<fid>/settle")
@require_roles("Organizer")
def fair_settle(fid):
    from services import latest_reconciliation

    fair = _fair_action(fid)
    validate_body(get_body(), [])
    if fair["status"] != "RECONCILING":
        fail("ERR_INVALID_STATE", "Fair is not in RECONCILING")
    recon = latest_reconciliation(fair["id"])
    if recon is None or recon["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The fair's latest reconciliation must be ACCEPTED")
    ra_open = any(
        r["fair_id"] == fair["id"] and r["status"] not in ("CREDITED", "REJECTED")
        for r in db.return_authorizations.values()
    )
    if ra_open:
        fail("ERR_INVALID_STATE", "Every return authorization must be CREDITED or REJECTED")
    booking_open = any(
        b["fair_id"] == fair["id"] and b["status"] not in ("SETTLED", "CANCELLED", "DECLINED")
        for b in db.bookings.values()
    )
    if booking_open:
        fail("ERR_INVALID_STATE", "Every author booking must be SETTLED, CANCELLED, or DECLINED")
    payout = next((p for p in db.payouts.values() if p["fair_id"] == fair["id"]), None)
    if payout is None or payout["status"] != "PAID":
        fail("ERR_INVALID_STATE", "The fair's profit-share payout must exist and be PAID")
    fair["status"] = "SETTLED"
    touch(fair)
    return success(fair)


@bp.post("/fairs/<fid>/cancel")
@require_roles("Organizer")
def fair_cancel(fid):
    fair = _fair_action(fid)
    data = get_body()
    validate_body(data, [("reason", False, v_str)])
    if fair["status"] not in ("DRAFT", "SCHEDULED", "STOCKING", "OPEN"):
        fail("ERR_INVALID_STATE", "Fair cannot be cancelled from its current state")
    tendered = any(
        s["fair_id"] == fair["id"] and s["status"] == "TENDERED" for s in db.sales.values()
    )
    if tendered:
        fail("ERR_INVALID_STATE", "Cannot cancel a fair with a TENDERED sale")
    cascade_fair_cancel(fair)
    fair["status"] = "CANCELLED"
    touch(fair)
    return success(fair)


# ---------------------------------------------------------------------------
# Venue slots
# ---------------------------------------------------------------------------

@bp.post("/venue-slots")
@require_roles("Organizer")
def create_venue_slot():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    vals = validate_body(
        data,
        [
            ("fair_id", True, v_str),
            ("venue_key", True, v_str),
            ("purpose", True, v_enum("SETUP", "FAIR_DAY", "AUTHOR_EVENT", "TEARDOWN")),
            ("start_at", True, v_datetime),
            ("end_at", True, v_datetime),
            ("setup_buffer_minutes", True, v_int(0)),
            ("teardown_buffer_minutes", True, v_int(0)),
        ],
    )
    fair = db.fairs[vals["fair_id"]]
    if vals["venue_key"] != fair["venue_key"]:
        fail("ERR_VALIDATION", "venue_key must equal the linked Fair's venue_key")
    if not vals["end_at"] > vals["start_at"]:
        fail("ERR_VALIDATION", "end_at must be strictly after start_at")
    if venue_conflict(
        vals["venue_key"],
        vals["start_at"],
        vals["end_at"],
        vals["setup_buffer_minutes"],
        vals["teardown_buffer_minutes"],
    ):
        fail("ERR_VENUE_CONFLICT", "Buffered interval intersects a non-RELEASED slot on this venue_key")
    slot = new_entity(
        fair_id=vals["fair_id"],
        venue_key=vals["venue_key"],
        purpose=vals["purpose"],
        start_at=fmt_dt(vals["start_at"]),
        end_at=fmt_dt(vals["end_at"]),
        setup_buffer_minutes=vals["setup_buffer_minutes"],
        teardown_buffer_minutes=vals["teardown_buffer_minutes"],
        status="HELD",
    )
    db.venue_slots[slot["id"]] = slot
    return success(slot, 201)


@bp.get("/venue-slots")
@require_roles(*ALL_ROLES)
def list_venue_slots():
    limit, offset = pagination_params()
    items = list_filtered(
        db.venue_slots,
        [("fair_id", "fair_id"), ("venue_key", "venue_key"), ("status", "status")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/venue-slots/<sid>")
@require_roles(*ALL_ROLES)
def get_venue_slot(sid):
    return success(get_or_404(db.venue_slots, sid, "VenueSlot"))


@bp.post("/venue-slots/<sid>/confirm")
@require_roles("SchoolCoordinator")
def confirm_venue_slot(sid):
    slot = get_or_404(db.venue_slots, sid, "VenueSlot")
    fair = db.fairs[slot["fair_id"]]
    require_scope(fair["school_party_id"])
    validate_body(get_body(), [])
    if slot["status"] != "HELD":
        fail("ERR_INVALID_STATE", "VenueSlot is not in HELD")
    if fair["status"] not in ("DRAFT", "SCHEDULED"):
        fail("ERR_INVALID_STATE", "Slot's fair must be in DRAFT or SCHEDULED")
    slot["status"] = "CONFIRMED"
    touch(slot)
    return success(slot)


@bp.post("/venue-slots/<sid>/release")
@require_roles("Organizer")
def release_venue_slot(sid):
    slot = get_or_404(db.venue_slots, sid, "VenueSlot")
    validate_body(get_body(), [])
    if slot["status"] not in ("HELD", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "VenueSlot cannot be released from its current state")
    slot["status"] = "RELEASED"
    touch(slot)
    return success(slot)
