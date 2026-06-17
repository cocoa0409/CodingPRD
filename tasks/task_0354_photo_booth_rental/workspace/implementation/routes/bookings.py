"""Booking hub: create/read/list, add-on lines, payments, and the schedule &
payment lifecycle transitions (PRD §3.2-3.8)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
import helpers
from services import calculations as calc
from services import booking_logic as bl
from services import intervals
from services.serialize import (
    booking_out, addon_line_out, payment_out, plain_out,
)

bp = Blueprint("bookings", __name__)

PAYMENT_KINDS = {"DEPOSIT", "BALANCE", "REFUND"}
SCHEDULE_STATUSES = {"DRAFT", "CONFIRMED", "IN_SERVICE", "COMPLETED", "CANCELLED"}


def _get_booking_or_404(bk_id):
    rec = db.bookings.get(bk_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Booking not found.")
    return rec


def _customer_owner_guard(booking, role, user_id):
    """PRD §2.1/§2.9: a Customer acting on a booking must own it."""
    if role == "Customer" and booking["customer_id"] != user_id:
        raise err(errors.ERR_NOT_BOOKING_OWNER, "Booking is not owned by the caller.")


# ============================ CREATE ============================
@bp.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    body = helpers.get_json()
    customer_id = helpers.require_string(body, "customer_id")
    package_id = helpers.require_string(body, "package_id")
    # Existence (priority 10) before well-formedness of the window numbers.
    customer = db.customers.get(customer_id)
    if not customer:
        raise err(errors.ERR_NOT_FOUND, "Customer not found.")
    package = db.packages.get(package_id)
    if not package:
        raise err(errors.ERR_NOT_FOUND, "Package not found.")
    # Customer ownership: a Customer drafts a booking for itself.
    if role == "Customer" and customer_id != user_id:
        raise err(errors.ERR_NOT_BOOKING_OWNER, "Cannot draft a booking for another customer.")

    event_start = helpers.parse_datetime(body, "event_start")
    event_end = helpers.parse_datetime(body, "event_end")
    if not (event_end > event_start):
        raise err(errors.ERR_INVALID_REQUEST, "event_end must be strictly after event_start.")
    venue_distance = helpers.require_int(body, "venue_distance_miles", minimum=0)
    setup_lead = helpers.optional_int(body, "requested_setup_lead_min", 0, minimum=0)

    rec = db.common_create()
    rec.update({
        "customer_id": customer_id,
        "package_id": package_id,
        "booth_id": None,
        "event_start": _iso(event_start),
        "event_end": _iso(event_end),
        "_event_start_dt": event_start,
        "_event_end_dt": event_end,
        "venue_distance_miles": venue_distance,
        "requested_setup_lead_min": setup_lead,
        "schedule_status": "DRAFT",
        "payment_status": "UNPAID",
        "travel_fee": calc.travel_fee(venue_distance),
        "final_subtotal": None,
        "amount_paid": Decimal("0"),
        "amount_refunded": Decimal("0"),
        "_refundable_amount": None,
    })
    # quote + deposit (no add-ons yet)
    bl.recompute_quote(rec)
    rec["balance_due"] = rec["quote_subtotal"]  # full amount outstanding (PRD §3.2)
    db.bookings[rec["id"]] = rec
    return success(booking_out(rec), 201)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ============================ READ / LIST ============================
@bp.route("/bookings/<bk_id>", methods=["GET"])
def get_booking(bk_id):
    user_id, role = authenticate()
    require_role(role, {"Customer", "OperationsManager", "FinanceClerk", "PlatformAdmin"})
    rec = _get_booking_or_404(bk_id)
    _customer_owner_guard(rec, role, user_id)
    return success(booking_out(rec), 200)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    user_id, role = authenticate()
    require_role(role, {"OperationsManager", "FinanceClerk", "PlatformAdmin", "Customer"})
    limit, offset = helpers.pagination_params()
    recs = list(db.bookings.values())
    cust = request.args.get("customer_id")
    pkg = request.args.get("package_id")
    booth = request.args.get("booth_id")
    sched = request.args.get("schedule_status")
    if cust is not None:
        recs = [r for r in recs if r["customer_id"] == cust]
    if pkg is not None:
        recs = [r for r in recs if r["package_id"] == pkg]
    if booth is not None:
        recs = [r for r in recs if r.get("booth_id") == booth]
    if sched is not None:
        recs = [r for r in recs if r["schedule_status"] == sched]
    # A Customer only sees its own bookings.
    if role == "Customer":
        recs = [r for r in recs if r["customer_id"] == user_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([booking_out(r) for r in window], limit, offset, total)


# ============================ ADD-ON LINES ============================
@bp.route("/bookings/<bk_id>/add-ons", methods=["POST"])
def add_addon_line(bk_id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    rec = _get_booking_or_404(bk_id)
    _customer_owner_guard(rec, role, user_id)
    body = helpers.get_json()
    add_on_id = helpers.require_string(body, "add_on_id")
    add_on = db.add_ons.get(add_on_id)
    if not add_on:
        raise err(errors.ERR_NOT_FOUND, "Add-on not found.")
    # qty must be an integer first (well-formedness, priority 20), then range
    # (priority 22) -> ERR_QTY_OUT_OF_RANGE.
    qty = helpers.require_int(body, "qty")
    # PRD §2.9 ordering: quantity range (priority 22) is checked BEFORE the
    # draft-lock state guard (priority 31).
    if qty < 1 or qty > add_on["max_qty"]:
        raise err(errors.ERR_QTY_OUT_OF_RANGE, "qty must be within 1..max_qty.")
    # State: lines only on DRAFT bookings (priority 31) -> ERR_BOOKING_LOCKED.
    if rec["schedule_status"] != "DRAFT":
        raise err(errors.ERR_BOOKING_LOCKED, "Add-on lines may only be added while DRAFT.")

    line = db.common_create()
    line_total = calc.round2(Decimal(str(add_on["unit_price"])) * Decimal(qty))
    line.update({
        "booking_id": bk_id,
        "add_on_id": add_on_id,
        "qty": qty,
        "line_total": line_total,
    })
    db.booking_add_ons[line["id"]] = line

    # Refresh quote + re-derive deposit/balance; bump booking version.
    bl.recompute_quote(rec)
    rec["balance_due"] = rec["quote_subtotal"] - rec["amount_paid"]
    db.touch(rec)
    return success(addon_line_out(line), 201)


@bp.route("/bookings/<bk_id>/add-ons", methods=["GET"])
def list_booking_addons(bk_id):
    user_id, role = authenticate()
    require_role(role, {"Customer", "OperationsManager", "PlatformAdmin"})
    rec = _get_booking_or_404(bk_id)
    _customer_owner_guard(rec, role, user_id)
    limit, offset = helpers.pagination_params()
    recs = [l for l in db.booking_add_ons.values() if l["booking_id"] == bk_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([addon_line_out(r) for r in window], limit, offset, total)


# ============================ PAYMENTS ============================
@bp.route("/bookings/<bk_id>/payments", methods=["POST"])
def create_payment(bk_id):
    _, role = authenticate()
    require_role(role, {"FinanceClerk"})
    rec = _get_booking_or_404(bk_id)
    body = helpers.get_json()
    kind = helpers.require_enum(body, "kind", PAYMENT_KINDS)
    amount = helpers.require_money(body, "amount", strictly_positive=True)

    if kind == "DEPOSIT":
        _apply_deposit(rec, amount)
    elif kind == "BALANCE":
        _apply_balance(rec, amount)
    else:
        _apply_refund(rec, amount)

    pay = db.payment_create()
    pay.update({"booking_id": bk_id, "kind": kind, "amount": amount})
    db.payments[pay["id"]] = pay
    return success(payment_out(pay), 201)


def _apply_deposit(rec, amount):
    # State (priority 30): UNPAID + DRAFT.
    if rec["payment_status"] != "UNPAID" or rec["schedule_status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Deposit requires UNPAID payment and DRAFT schedule.")
    # Fiscal (priority 50): amount == deposit_due exactly.
    if amount != calc.round2(rec["deposit_due"]):
        raise err(errors.ERR_DEPOSIT_AMOUNT_MISMATCH, "Deposit amount must equal deposit_due.")
    rec["amount_paid"] = rec["amount_paid"] + amount
    rec["balance_due"] = rec["quote_subtotal"] - rec["amount_paid"]
    rec["payment_status"] = "DEPOSIT_PAID"
    db.touch(rec)


def _apply_balance(rec, amount):
    if rec["payment_status"] != "DEPOSIT_PAID":
        raise err(errors.ERR_INVALID_STATE, "Balance requires DEPOSIT_PAID payment status.")
    if rec["schedule_status"] not in ("CONFIRMED", "IN_SERVICE"):
        raise err(errors.ERR_INVALID_STATE, "Balance requires CONFIRMED or IN_SERVICE schedule.")
    # Event log must be finalized so balance_due reflects the final settlement.
    elog = _eventlog_for(rec["id"])
    if not elog or not elog.get("finalized"):
        raise err(errors.ERR_INVALID_STATE, "Balance requires a finalized event log.")
    # Fiscal (priority 51): amount == balance_due exactly.
    if amount != calc.round2(rec["balance_due"]):
        raise err(errors.ERR_BALANCE_AMOUNT_MISMATCH, "Balance amount must equal balance_due.")
    rec["amount_paid"] = rec["amount_paid"] + amount
    rec["balance_due"] = Decimal("0")
    rec["payment_status"] = "PAID_IN_FULL"
    db.touch(rec)


def _apply_refund(rec, amount):
    if rec["schedule_status"] != "CANCELLED":
        raise err(errors.ERR_INVALID_STATE, "Refund requires CANCELLED schedule.")
    if rec["payment_status"] != "DEPOSIT_PAID":
        raise err(errors.ERR_INVALID_STATE, "Refund requires DEPOSIT_PAID payment status.")
    refundable = rec.get("_refundable_amount")
    if refundable is None:
        refundable = calc.cancellation_refund(rec, db.get_clock())
    if refundable <= 0:
        raise err(errors.ERR_INVALID_STATE, "No refundable amount; deposit must be forfeited.")
    # Fiscal (priority 52): amount == refundable exactly.
    if amount != calc.round2(refundable):
        raise err(errors.ERR_REFUND_AMOUNT_MISMATCH, "Refund amount must equal refundable amount.")
    rec["amount_refunded"] = rec["amount_refunded"] + amount
    rec["payment_status"] = "REFUNDED"
    db.touch(rec)


@bp.route("/bookings/<bk_id>/payments", methods=["GET"])
def list_payments(bk_id):
    _, role = authenticate()
    require_role(role, {"FinanceClerk", "OperationsManager", "PlatformAdmin"})
    _get_booking_or_404(bk_id)
    limit, offset = helpers.pagination_params()
    recs = [p for p in db.payments.values() if p["booking_id"] == bk_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([payment_out(r) for r in window], limit, offset, total)


# ============================ CONFIRM ============================
@bp.route("/bookings/<bk_id>/confirm", methods=["POST"])
def confirm_booking(bk_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = _get_booking_or_404(bk_id)
    body = helpers.get_json()
    expected_booth_version = helpers.require_int(body, "expected_booth_version")
    package = db.packages[rec["package_id"]]

    # State (priority 30): DRAFT + DEPOSIT_PAID + active package.
    if rec["schedule_status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Confirm requires DRAFT schedule.")
    if rec["payment_status"] != "DEPOSIT_PAID":
        raise err(errors.ERR_INVALID_STATE, "Confirm requires the deposit to be paid.")
    if not package.get("active", True):
        raise err(errors.ERR_INVALID_STATE, "Package is not active.")

    # Selection: choose booth (raises interval/availability errors per priority
    # 42/43). OCC (priority 40) is checked AGAINST THE CHOSEN BOOTH before the
    # interval scan? Per PRD §2.9, OCC precedes interval/selection checks. The
    # OCC field asserts the version of the booth the client intends to claim.
    # We pick the candidate first to know which booth's version to compare, but
    # the PRD orders STALE before interval-overlap. Since the chosen booth is
    # the surviving candidate, we run the selector (which already enforces the
    # overlap filter) — to honor STALE-before-overlap ordering we compare the
    # client's expected version against the chosen booth here.
    chosen_booth = bl.select_booth(rec)
    if expected_booth_version != chosen_booth["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_booth_version does not match chosen booth.")

    # Attendant staffing if required.
    requires_attendant = bl.booking_requires_attendant(rec)
    chosen_attendant = None
    if requires_attendant:
        chosen_attendant = bl.select_attendant(rec)

    # Commit: claim booth, create assignment, advance state, refresh quote.
    rec["booth_id"] = chosen_booth["id"]
    db.touch(chosen_booth)  # interval claim bumps booth version

    if requires_attendant:
        occ_start, occ_end = intervals.attendant_interval(
            rec["_event_start_dt"], rec["_event_end_dt"])
        assign = db.common_create()
        assign.update({
            "booking_id": rec["id"],
            "attendant_id": chosen_attendant["id"],
            "occupied_start": _iso(occ_start),
            "occupied_end": _iso(occ_end),
            "_occupied_start_dt": occ_start,
            "_occupied_end_dt": occ_end,
            "status": "ACTIVE",
        })
        db.attendant_assignments[assign["id"]] = assign

    bl.recompute_quote(rec)
    rec["balance_due"] = rec["quote_subtotal"] - rec["amount_paid"]
    rec["schedule_status"] = "CONFIRMED"
    db.touch(rec)
    return success(booking_out(rec), 200)


# ============================ START SERVICE ============================
@bp.route("/bookings/<bk_id>/start-service", methods=["POST"])
def start_service(bk_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = _get_booking_or_404(bk_id)
    if rec["schedule_status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Start-service requires CONFIRMED schedule.")
    if _eventlog_for(rec["id"]) is not None:
        raise err(errors.ERR_INVALID_STATE, "An event log already exists for this booking.")

    elog = db.common_create()
    elog.update({
        "booking_id": rec["id"],
        "actual_setup_start": None,
        "actual_coverage_start": None,
        "actual_coverage_end": None,
        "actual_teardown_end": None,
        "actual_print_count": None,
        "finalized": False,
    })
    db.event_logs[elog["id"]] = elog

    rec["schedule_status"] = "IN_SERVICE"
    db.touch(rec)
    return success(booking_out(rec), 200)


# ============================ COMPLETE ============================
@bp.route("/bookings/<bk_id>/complete", methods=["POST"])
def complete_booking(bk_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = _get_booking_or_404(bk_id)
    if rec["schedule_status"] != "IN_SERVICE":
        raise err(errors.ERR_INVALID_STATE, "Complete requires IN_SERVICE schedule.")
    elog = _eventlog_for(rec["id"])
    if not elog or not elog.get("finalized"):
        raise err(errors.ERR_INVALID_STATE, "Complete requires a finalized event log.")
    if rec["payment_status"] != "PAID_IN_FULL":
        raise err(errors.ERR_INVALID_STATE, "Complete requires PAID_IN_FULL payment status.")

    # Release attendant assignment(s).
    for assign in db.attendant_assignments.values():
        if assign["booking_id"] == rec["id"] and assign["status"] == "ACTIVE":
            assign["status"] = "RELEASED"
            db.touch(assign)

    # Create the gallery if none exists.
    if _gallery_for(rec["id"]) is None:
        gal = db.common_create()
        gal.update({
            "booking_id": rec["id"],
            "photo_count": 0,
            "status": "DRAFT",
            "access_pin": None,
        })
        db.galleries[gal["id"]] = gal

    rec["schedule_status"] = "COMPLETED"
    db.touch(rec)
    return success(booking_out(rec), 200)


# ============================ CANCEL ============================
@bp.route("/bookings/<bk_id>/cancel", methods=["POST"])
def cancel_booking(bk_id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    rec = _get_booking_or_404(bk_id)
    _customer_owner_guard(rec, role, user_id)
    if rec["schedule_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Cancel requires DRAFT or CONFIRMED schedule.")

    was_confirmed = rec["schedule_status"] == "CONFIRMED"
    if was_confirmed:
        # Release the held booth interval claim and the attendant assignment.
        # booth_id is retained on the booking (the historical assignment, which
        # a later booking's booth_id assertion may compare against); the
        # interval is freed because the booking leaves the CONFIRMED/IN_SERVICE
        # states that hold it. Releasing the claim is a mutation of the booth,
        # so the booth's version is bumped.
        held_booth = db.booths.get(rec.get("booth_id")) if rec.get("booth_id") else None
        if held_booth is not None:
            db.touch(held_booth)
        for assign in db.attendant_assignments.values():
            if assign["booking_id"] == rec["id"] and assign["status"] == "ACTIVE":
                assign["status"] = "RELEASED"
                db.touch(assign)

    rec["schedule_status"] = "CANCELLED"
    refundable = calc.cancellation_refund(rec, db.get_clock())
    rec["_refundable_amount"] = refundable

    # If nothing was paid, payment_status moves to REFUNDED immediately.
    if rec["amount_paid"] == 0:
        rec["payment_status"] = "REFUNDED"
    # Otherwise the FinanceClerk must still issue a REFUND (or forfeit).
    db.touch(rec)
    return success(booking_out(rec), 200)


# ============================ FORFEIT ============================
@bp.route("/bookings/<bk_id>/forfeit", methods=["POST"])
def forfeit_booking(bk_id):
    _, role = authenticate()
    require_role(role, {"FinanceClerk"})
    rec = _get_booking_or_404(bk_id)
    if rec["schedule_status"] != "CANCELLED":
        raise err(errors.ERR_INVALID_STATE, "Forfeit requires CANCELLED schedule.")
    if rec["payment_status"] != "DEPOSIT_PAID":
        raise err(errors.ERR_INVALID_STATE, "Forfeit requires DEPOSIT_PAID payment status.")
    refundable = rec.get("_refundable_amount")
    if refundable is None:
        refundable = calc.cancellation_refund(rec, db.get_clock())
    if refundable != 0:
        raise err(errors.ERR_INVALID_STATE, "Forfeit requires a zero refundable amount.")
    rec["payment_status"] = "FORFEITED"
    db.touch(rec)
    return success(booking_out(rec), 200)


# ============================ ATTENDANT ASSIGNMENTS (booking-scoped) ====
@bp.route("/bookings/<bk_id>/attendant-assignments", methods=["GET"])
def list_booking_assignments(bk_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    _get_booking_or_404(bk_id)
    limit, offset = helpers.pagination_params()
    recs = [a for a in db.attendant_assignments.values() if a["booking_id"] == bk_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([plain_out(r) for r in window], limit, offset, total)


# ============================ EVENT LOGS (booking-scoped) ============================
@bp.route("/bookings/<bk_id>/event-logs", methods=["GET"])
def list_booking_eventlogs(bk_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "FinanceClerk", "PlatformAdmin"})
    _get_booking_or_404(bk_id)
    limit, offset = helpers.pagination_params()
    recs = [e for e in db.event_logs.values() if e["booking_id"] == bk_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([plain_out(r) for r in window], limit, offset, total)


# ============================ GALLERIES (booking-scoped) ============================
@bp.route("/bookings/<bk_id>/galleries", methods=["GET"])
def list_booking_galleries(bk_id):
    user_id, role = authenticate()
    require_role(role, {"Customer", "OperationsManager", "PlatformAdmin"})
    rec = _get_booking_or_404(bk_id)
    _customer_owner_guard(rec, role, user_id)
    limit, offset = helpers.pagination_params()
    recs = [g for g in db.galleries.values() if g["booking_id"] == bk_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([plain_out(r) for r in window], limit, offset, total)


# ---------------- helpers ----------------
def _eventlog_for(booking_id):
    for e in db.event_logs.values():
        if e["booking_id"] == booking_id:
            return e
    return None


def _gallery_for(booking_id):
    for g in db.galleries.values():
        if g["booking_id"] == booking_id:
            return g
    return None
