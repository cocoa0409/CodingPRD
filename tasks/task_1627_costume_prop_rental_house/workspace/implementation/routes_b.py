"""Routes: productions, reservations, pull lists."""

from datetime import timedelta

from flask import Blueprint, request

from db import (DB, PRODUCTION_STATUSES, RESERVATION_STATUSES,
                PULL_LIST_STATUSES, HOLD_HOURS, new_record, touch, now_iso,
                now_dt, today, fmt_ts, sort_key)
from errors import fail
from middleware import (authenticate, require_roles, scope_check, BodyReader,
                        renter_id_of_production, renter_id_of_reservation,
                        renter_id_of_pull_list)
from response import respond_object, respond_list, serialize, serialize_many
from services import (compute_run_weeks, compute_return_by, compute_quote,
                      availability_for_window, windows_overlap, select_units,
                      compute_line_rental_charge, evaluate_pull_list_close)

bp = Blueprint("routes_b", __name__)

ALL_ROLES = ["HouseAdmin", "WardrobeStaff", "RenterContact", "Accountant"]


def _visible_productions(role, uid):
    recs = list(DB.productions.values())
    if role == "RenterContact":
        recs = [p for p in recs if p["renter_id"] == uid]
    return recs


# ---------------------------------------------------------------------------
# Productions
# ---------------------------------------------------------------------------

@bp.post("/rental-house/productions")
def create_production():
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    br = BodyReader()
    renter_id = br.get_str("renter_id")
    title = br.get_str("title")
    rehearsal = br.get_date("rehearsal_start_date")
    performance = br.get_date("performance_start_date")
    closing = br.get_date("closing_date")
    # Priority 3: RenterContact may only create for own renter_id
    if renter_id is not None:
        scope_check(uid, role, renter_id)
    # Priority 4: existence
    renter = DB.renters.get(renter_id) if renter_id else None
    if renter_id is not None and renter is None:
        fail("ERR_NOT_FOUND", "Renter not found")
    # Priority 9: date order
    if rehearsal is not None and performance is not None and closing is not None:
        if not (rehearsal <= performance <= closing):
            fail("ERR_DATE_ORDER",
                 "rehearsal_start_date <= performance_start_date <= closing_date required")
    br.raise_if_errors()

    rec = new_record()
    rec.update({
        "renter_id": renter_id,
        "title": title,
        "rehearsal_start_date": rehearsal.isoformat(),
        "performance_start_date": performance.isoformat(),
        "closing_date": closing.isoformat(),
        "return_by_date": compute_return_by(closing).isoformat(),
        "run_weeks": compute_run_weeks(performance, closing),
        "long_run": False,
        "rate_card_id": None,
        "rate_card_version": None,
        "status": "DRAFT",
        "_rehearsal_start_date": rehearsal,
        "_performance_start_date": performance,
        "_closing_date": closing,
    })
    DB.productions[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/productions")
def list_productions():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = _visible_productions(role, uid)
    for field in ("renter_id", "status", "rate_card_id"):
        v = request.args.get(field)
        if v is not None:
            recs = [p for p in recs if p[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/productions/<pid>")
def get_production(pid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.productions.get(pid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Production not found")
    scope_check(uid, role, rec["renter_id"])
    return respond_object(serialize(rec))


@bp.post("/rental-house/productions/<pid>/confirm")
def confirm_production(pid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.productions.get(pid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Production not found")
    scope_check(uid, role, rec["renter_id"])
    # Priority 5: state + renter standing
    if rec["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Production is not DRAFT")
    renter = DB.renters.get(rec["renter_id"])
    if renter is None or renter["status"] != "ACTIVE":
        fail("ERR_RENTER_SUSPENDED", "Renter is not ACTIVE")
    # Priority 7: insurance covering return_by_date
    return_by = compute_return_by(rec["_closing_date"])
    if not any(c["renter_id"] == renter["id"] and c["status"] == "VERIFIED"
               and c["_expiry_date"] >= return_by
               for c in DB.certificates.values()):
        fail("ERR_INSURANCE_NOT_VERIFIED",
             "No VERIFIED certificate covers return_by_date")
    # Priority 8: a PUBLISHED rate card exists
    card = next((c for c in DB.rate_cards.values() if c["status"] == "PUBLISHED"), None)
    if card is None:
        fail("ERR_RATE_CARD_REQUIRED", "No PUBLISHED rate card exists")
    # Priority 9: date order
    if not (rec["_rehearsal_start_date"] <= rec["_performance_start_date"]
            <= rec["_closing_date"]):
        fail("ERR_DATE_ORDER", "Production dates out of order")

    run_weeks = compute_run_weeks(rec["_performance_start_date"], rec["_closing_date"])
    rec["run_weeks"] = run_weeks
    rec["return_by_date"] = return_by.isoformat()
    rec["long_run"] = run_weeks >= card["long_run_threshold_weeks"]
    rec["rate_card_id"] = card["id"]
    rec["rate_card_version"] = card["version"]
    rec["status"] = "CONFIRMED"
    touch(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/productions/<pid>/cancel")
def cancel_production(pid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.productions.get(pid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Production not found")
    scope_check(uid, role, rec["renter_id"])
    if rec["status"] not in ("DRAFT", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "Production cannot be cancelled from %s" % rec["status"])
    if rec["status"] == "CONFIRMED":
        for pl in DB.pull_lists.values():
            if pl["production_id"] == pid and pl["status"] in ("PICKING", "DISPATCHED"):
                fail("ERR_PRODUCTION_HAS_ACTIVE_PULLS",
                     "Production has PICKING or DISPATCHED pull lists")
    rec["status"] = "CANCELLED"
    touch(rec)
    for r in DB.reservations.values():
        if r["production_id"] == pid and r["status"] in ("HELD", "CONFIRMED"):
            r["status"] = "RELEASED"
            touch(r)
    for pl in DB.pull_lists.values():
        if pl["production_id"] == pid and pl["status"] == "DRAFT":
            pl["status"] = "CANCELLED"
            touch(pl)
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def _window_bounds_check(production, start, end):
    """Priority 9: end >= start and window inside [rehearsal_start, return_by_date]."""
    if start is None or end is None:
        return
    if end < start:
        fail("ERR_WINDOW_OUT_OF_BOUNDS", "window_end_date is before window_start_date")
    if start < production["_rehearsal_start_date"] or \
            end > compute_return_by(production["_closing_date"]):
        fail("ERR_WINDOW_OUT_OF_BOUNDS",
             "Window outside [rehearsal_start_date, return_by_date]")


def _renter_of_production(production):
    return DB.renters.get(production["renter_id"])


@bp.post("/rental-house/reservations")
def create_reservation():
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    br = BodyReader()
    production_id = br.get_str("production_id")
    item_id = br.get_str("item_id")
    quantity = br.get_int("quantity")
    w_start = br.get_date("window_start_date")
    w_end = br.get_date("window_end_date")
    expected_version = br.get_int("expected_production_version")

    # Priority 3/4: scope then existence (production, then item)
    production = DB.productions.get(production_id) if production_id else None
    if production is not None:
        scope_check(uid, role, production["renter_id"])
    if production_id is not None and production is None:
        fail("ERR_NOT_FOUND", "Production not found")
    item = DB.items.get(item_id) if item_id else None
    if item_id is not None and item is None:
        fail("ERR_NOT_FOUND", "Item not found")

    if production is not None:
        # Priority 5: renter ACTIVE; production DRAFT or CONFIRMED
        renter = _renter_of_production(production)
        if renter is None or renter["status"] != "ACTIVE":
            fail("ERR_RENTER_SUSPENDED", "Renter is not ACTIVE")
        if production["status"] not in ("DRAFT", "CONFIRMED"):
            fail("ERR_INVALID_STATE",
                 "Production must be DRAFT or CONFIRMED to hold reservations")
        # Priority 6: OCC
        if expected_version is not None and expected_version != production["version"]:
            fail("ERR_STALE_VERSION",
                 "expected_production_version does not match Production.version")
    # Priority 8: item rentable
    if item is not None and item["status"] != "ACTIVE":
        fail("ERR_ITEM_NOT_RENTABLE", "Item is not ACTIVE")
    # Priority 9: window bounds
    if production is not None:
        _window_bounds_check(production, w_start, w_end)
    # Priority 10: capacity, then quantity >= 1
    if item is not None and w_start is not None and w_end is not None \
            and quantity is not None and quantity >= 1:
        available = availability_for_window(item["id"], w_start, w_end)
        if quantity > available:
            fail("ERR_CAPACITY_EXCEEDED",
                 "Insufficient serviceable capacity for the window")
    if quantity is not None and quantity < 1:
        fail("ERR_QUANTITY_INVALID", "quantity must be at least 1")
    br.raise_if_errors()

    variant, quote = compute_quote(production, item, quantity, w_start, w_end)
    hold_expires = now_dt() + timedelta(hours=HOLD_HOURS)
    rec = new_record()
    rec.update({
        "production_id": production_id,
        "item_id": item_id,
        "quantity": quantity,
        "window_start_date": w_start.isoformat(),
        "window_end_date": w_end.isoformat(),
        "rate_variant": variant,
        "quoted_charge_cents": quote,
        "hold_expires_at": fmt_ts(hold_expires),
        "status": "HELD",
        "_window_start": w_start,
        "_window_end": w_end,
        "_hold_expires_dt": hold_expires,
    })
    DB.reservations[rec["id"]] = rec
    touch(production)  # reservation creation mutates the production aggregate
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/reservations")
def list_reservations():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.reservations.values())
    if role == "RenterContact":
        recs = [r for r in recs
                if renter_id_of_production(r["production_id"]) == uid]
    for field in ("production_id", "item_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/reservations/<rid>")
def get_reservation(rid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.reservations.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Reservation not found")
    scope_check(uid, role, renter_id_of_production(rec["production_id"]))
    return respond_object(serialize(rec))


@bp.post("/rental-house/reservations/<rid>/confirm")
def confirm_reservation(rid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.reservations.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Reservation not found")
    production = DB.productions.get(rec["production_id"])
    scope_check(uid, role, production["renter_id"])
    # Priority 5: state, hold expiry
    if rec["status"] != "HELD":
        fail("ERR_INVALID_STATE", "Reservation is not HELD")
    if production["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Production is not CONFIRMED")
    if now_dt() > rec["_hold_expires_dt"]:
        fail("ERR_HOLD_EXPIRED", "The hold has expired")
    # Priority 10: capacity re-check (excluding self)
    available = availability_for_window(rec["item_id"], rec["_window_start"],
                                        rec["_window_end"], exclude_reservation_id=rec["id"])
    if rec["quantity"] > available:
        fail("ERR_CAPACITY_EXCEEDED", "Capacity no longer available")
    # Priority 11: credit hold
    renter = _renter_of_production(production)
    if renter is not None and renter["credit_hold"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "Renter is on credit hold")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/reservations/<rid>/release")
def release_reservation(rid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.reservations.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Reservation not found")
    production = DB.productions.get(rec["production_id"])
    scope_check(uid, role, production["renter_id"])
    if rec["status"] not in ("HELD", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "Reservation cannot be released from %s" % rec["status"])
    if rec["status"] == "CONFIRMED":
        for ln in DB.lines.values():
            if ln["reservation_id"] == rid and ln["status"] in ("PENDING", "PICKED", "OUT"):
                fail("ERR_RESERVATION_IN_USE",
                     "Active pull-list lines reference this reservation")
    rec["status"] = "RELEASED"
    touch(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/reservations/<rid>/amend")
def amend_reservation(rid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.reservations.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Reservation not found")
    production = DB.productions.get(rec["production_id"])
    scope_check(uid, role, production["renter_id"])
    if rec["status"] not in ("HELD", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "Reservation cannot be amended from %s" % rec["status"])
    br = BodyReader()
    new_qty = br.get_int("quantity", required=False)
    new_start = br.get_date("window_start_date", required=False)
    new_end = br.get_date("window_end_date", required=False)
    qty = new_qty if new_qty is not None else rec["quantity"]
    start = new_start if new_start is not None else rec["_window_start"]
    end = new_end if new_end is not None else rec["_window_end"]
    # Priority 9: window bounds
    if "window_start_date" not in br.bad and "window_end_date" not in br.bad:
        _window_bounds_check(production, start, end)
    # Priority 10: capacity (excluding self), then quantity
    if quantity_ok(qty) and "quantity" not in br.bad and \
            "window_start_date" not in br.bad and "window_end_date" not in br.bad:
        available = availability_for_window(rec["item_id"], start, end,
                                            exclude_reservation_id=rec["id"])
        if qty > available:
            fail("ERR_CAPACITY_EXCEEDED", "Insufficient capacity for amended window")
    if qty is not None and qty < 1:
        fail("ERR_QUANTITY_INVALID", "quantity must be at least 1")
    br.raise_if_errors()

    item = DB.items.get(rec["item_id"])
    variant, quote = compute_quote(production, item, qty, start, end)
    rec["quantity"] = qty
    rec["window_start_date"] = start.isoformat()
    rec["window_end_date"] = end.isoformat()
    rec["_window_start"] = start
    rec["_window_end"] = end
    rec["rate_variant"] = variant
    rec["quoted_charge_cents"] = quote
    hold_expires = now_dt() + timedelta(hours=HOLD_HOURS)
    rec["hold_expires_at"] = fmt_ts(hold_expires)
    rec["_hold_expires_dt"] = hold_expires
    rec["status"] = "HELD"
    touch(rec)
    return respond_object(serialize(rec))


def quantity_ok(q):
    return isinstance(q, int) and not isinstance(q, bool) and q >= 1


# ---------------------------------------------------------------------------
# Pull lists
# ---------------------------------------------------------------------------

@bp.post("/rental-house/pull-lists")
def create_pull_list():
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    br = BodyReader()
    production_id = br.get_str("production_id")
    expected_version = br.get_int("expected_production_version")
    production = DB.productions.get(production_id) if production_id else None
    if production is not None:
        scope_check(uid, role, production["renter_id"])
    if production_id is not None and production is None:
        fail("ERR_NOT_FOUND", "Production not found")
    if production is not None:
        if production["status"] != "CONFIRMED":
            fail("ERR_INVALID_STATE", "Production is not CONFIRMED")
        if expected_version is not None and expected_version != production["version"]:
            fail("ERR_STALE_VERSION",
                 "expected_production_version does not match Production.version")
    br.raise_if_errors()
    rec = new_record()
    rec.update({
        "production_id": production_id,
        "status": "DRAFT",
        "submitted_at": None,
        "dispatched_at": None,
    })
    DB.pull_lists[rec["id"]] = rec
    touch(production)  # pull-list creation mutates the production aggregate
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/pull-lists")
def list_pull_lists():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.pull_lists.values())
    if role == "RenterContact":
        recs = [p for p in recs
                if renter_id_of_production(p["production_id"]) == uid]
    for field in ("production_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [p for p in recs if p[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/pull-lists/<pid>")
def get_pull_list(pid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.pull_lists.get(pid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Pull list not found")
    scope_check(uid, role, renter_id_of_production(rec["production_id"]))
    return respond_object(serialize(rec))


def _reservation_covered(reservation_id):
    """Covered when a line on a PICKING/DISPATCHED/CLOSED pull list references it."""
    for ln in DB.lines.values():
        if ln["reservation_id"] != reservation_id:
            continue
        pl = DB.pull_lists.get(ln["pull_list_id"])
        if pl is not None and pl["status"] in ("PICKING", "DISPATCHED", "CLOSED"):
            return True
    return False


@bp.post("/rental-house/pull-lists/<pid>/submit")
def submit_pull_list(pid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    pl = DB.pull_lists.get(pid)
    if pl is None:
        fail("ERR_NOT_FOUND", "Pull list not found")
    if pl["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Pull list is not DRAFT")
    production = DB.productions.get(pl["production_id"])
    if production is None or production["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Production is not CONFIRMED")
    uncovered = [r for r in DB.reservations.values()
                 if r["production_id"] == production["id"]
                 and r["status"] == "CONFIRMED"
                 and not _reservation_covered(r["id"])]
    if not uncovered:
        fail("ERR_NOTHING_TO_PULL", "No uncovered CONFIRMED reservations")
    uncovered.sort(key=lambda r: (r["_window_start"], r["created_at"], r["_seq"]))

    # Atomic unit selection: stage everything, fail before creating anything.
    staged = []  # (reservation, unit)
    staged_lines = []
    for r in uncovered:
        units = select_units(r, r["quantity"], staged_lines)
        if units is None:
            fail("ERR_NO_UNITS_AVAILABLE",
                 "Not enough eligible units for reservation %s" % r["id"])
        for u in units:
            staged.append((r, u))
            staged_lines.append({"item_unit_id": u["id"],
                                 "reservation_id": r["id"],
                                 "_reservation_ref": r})

    for r, u in staged:
        line = new_record()
        line.update({
            "pull_list_id": pl["id"],
            "reservation_id": r["id"],
            "item_unit_id": u["id"],
            "status": "PENDING",
            "due_back_date": None,
            "returned_at": None,
            "rental_charge_cents": compute_line_rental_charge(r, u),
            "late_fee_cents": 0,
            "rental_invoiced": False,
            "late_fee_invoiced": False,
            "_due_back_date": None,
        })
        DB.lines[line["id"]] = line
    pl["status"] = "PICKING"
    pl["submitted_at"] = now_iso()
    touch(pl)
    return respond_object(serialize(pl))


@bp.post("/rental-house/pull-lists/<pid>/dispatch")
def dispatch_pull_list(pid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    pl = DB.pull_lists.get(pid)
    if pl is None:
        fail("ERR_NOT_FOUND", "Pull list not found")
    if pl["status"] != "PICKING":
        fail("ERR_INVALID_STATE", "Pull list is not PICKING")
    lines = [ln for ln in DB.lines.values() if ln["pull_list_id"] == pid]
    for ln in lines:
        if ln["status"] != "PICKED":
            fail("ERR_LINES_NOT_PICKED", "Every line must be PICKED before dispatch")
    production = DB.productions.get(pl["production_id"])
    renter = _renter_of_production(production)
    if renter is None or renter["status"] != "ACTIVE":
        fail("ERR_RENTER_SUSPENDED", "Renter is not ACTIVE")
    if not any(c["renter_id"] == renter["id"] and c["status"] == "VERIFIED"
               and c["_expiry_date"] >= today() for c in DB.certificates.values()):
        fail("ERR_INSURANCE_NOT_VERIFIED",
             "No VERIFIED, unexpired certificate for the renter")
    if renter["credit_hold"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "Renter is on credit hold")

    for ln in lines:
        reservation = DB.reservations.get(ln["reservation_id"])
        ln["status"] = "OUT"
        ln["due_back_date"] = reservation["window_end_date"]
        ln["_due_back_date"] = reservation["_window_end"]
        touch(ln)
        unit = DB.units.get(ln["item_unit_id"])
        if unit is not None and unit["status"] == "AVAILABLE":
            unit["status"] = "OUT"
            touch(unit)
    covered = {ln["reservation_id"] for ln in lines}
    for rid in covered:
        r = DB.reservations.get(rid)
        if r is not None and r["status"] == "CONFIRMED":
            r["status"] = "FULFILLED"
            touch(r)
    pl["status"] = "DISPATCHED"
    pl["dispatched_at"] = now_iso()
    touch(pl)
    return respond_object(serialize(pl))


@bp.post("/rental-house/pull-lists/<pid>/cancel")
def cancel_pull_list(pid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact", "WardrobeStaff"])
    pl = DB.pull_lists.get(pid)
    if pl is None:
        fail("ERR_NOT_FOUND", "Pull list not found")
    if role == "RenterContact":
        scope_check(uid, role, renter_id_of_production(pl["production_id"]))
    if role == "RenterContact":
        if pl["status"] != "DRAFT":
            fail("ERR_INVALID_STATE",
                 "RenterContact may cancel only DRAFT pull lists")
    else:  # WardrobeStaff
        if pl["status"] != "PICKING":
            fail("ERR_INVALID_STATE",
                 "WardrobeStaff may cancel only PICKING pull lists")
    if pl["status"] == "PICKING":
        doomed = [ln for ln in DB.lines.values() if ln["pull_list_id"] == pid
                  and ln["status"] in ("PENDING", "PICKED")]
        for ln in doomed:
            del DB.lines[ln["id"]]
    pl["status"] = "CANCELLED"
    touch(pl)
    return respond_object(serialize(pl))
