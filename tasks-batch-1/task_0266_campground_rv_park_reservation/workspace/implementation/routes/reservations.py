"""Reservation lifecycle, add-on, and payment endpoints."""
from flask import Blueprint, request

from db import store, new_id
import errors
from middleware import get_principal, require_role, ROLE_OPERATOR, ROLE_GUEST
from response import success, success_list
from services.common import stamp_common, touch, parse_date, clock_date
from services import validate as V
from services.listing import pagination, paginate
from services.serializers import (
    serialize_reservation,
    serialize_addon,
    serialize_payment,
    compute_amount_paid,
)
from services import reservation_ops as ops

bp = Blueprint("reservations", __name__)

ADDON_KINDS = {"FIREWOOD", "EXTRA_VEHICLE", "PET_FEE", "EARLY_CHECKIN"}
PAYMENT_TYPES = {"DEPOSIT", "BALANCE"}  # client may only record DEPOSIT or BALANCE


def _require_owns_reservation(res, user_id, role):
    """Guest acting on a reservation/add-on/payment must own it (PRD §2.1)."""
    if role == ROLE_GUEST and res["guest_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Guest does not own this reservation")


# ---------------------------------------------------------------------------
# Reservation create (lock) — Guest only
# ---------------------------------------------------------------------------
@bp.route("/sites/<sid>/reservations", methods=["POST"])
def create_reservation(sid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    body = V.get_json_body()
    V.require_fields(body, ["guest_id", "check_in_date", "check_out_date"])
    guest_id = V.require_str(body, "guest_id")

    # Authorization: the acting guest must be creating for itself (guest_id == X-User-ID).
    if guest_id != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "guest_id must equal the acting guest")

    # Existence: guest must exist.
    guest = store.guests.get(guest_id)
    if guest is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Guest not found")

    # Well-formedness: dates parse, check_out strictly after check_in.
    check_in_s = V.require_str(body, "check_in_date")
    check_out_s = V.require_str(body, "check_out_date")
    check_in = parse_date(check_in_s)
    check_out = parse_date(check_out_s)
    if check_out <= check_in:
        raise errors.err(errors.ERR_INVALID_REQUEST, "check_out_date must be after check_in_date")

    # OCC (priority 5).
    expected = body.get("expected_site_version")
    if expected is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: expected_site_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise errors.err(errors.ERR_STALE_SITE_VERSION, "Stale site version")

    # Business guards in pinned order (priorities 8 -> 11).
    nights = (check_out - check_in).days
    # (8) max stay cap: nights <= cap allowed; cap+1 rejected.
    if nights > site["max_length_of_stay_nights"]:
        raise errors.err(errors.ERR_MAX_STAY_EXCEEDED, "Reservation nights exceed the site max stay")
    # (9) site availability.
    if site["status"] in ("RETIRED", "MAINTENANCE"):
        raise errors.err(errors.ERR_SITE_UNAVAILABLE, "Site is unavailable")
    # (10) maintenance-buffer conflict.
    ops.check_maintenance_conflict(site, check_in, check_out)
    # (11) date overlap with live reservations.
    ops.check_date_overlap(sid, check_in, check_out)

    res = ops.create_reservation(site, guest, check_in_s, check_out_s)
    return success(serialize_reservation(res), 201)


@bp.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    return success(serialize_reservation(res), 200)


@bp.route("/sites/<sid>/reservations", methods=["GET"])
def list_site_reservations(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    items = [r for r in store.reservations.values() if r["site_id"] == sid]
    status = request.args.get("reservation_status")
    if status is not None:
        items = [r for r in items if r["reservation_status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_reservation(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Confirm — Guest, owner
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm(rid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    _require_owns_reservation(res, user_id, role)

    # State legality: must be REQUESTED.
    if res["reservation_status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation is not REQUESTED")

    site = store.sites[res["site_id"]]
    # Deposit must already be collected.
    if res["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise errors.err(errors.ERR_INVALID_STATE, "Deposit has not been collected")
    # Site must be ACTIVE.
    if site["status"] in ("RETIRED", "MAINTENANCE"):
        raise errors.err(errors.ERR_SITE_UNAVAILABLE, "Site is unavailable")

    # Re-run maintenance-buffer and date-overlap checks.
    check_in = parse_date(res["check_in_date"])
    check_out = parse_date(res["check_out_date"])
    ops.check_maintenance_conflict(site, check_in, check_out)
    ops.check_date_overlap(res["site_id"], check_in, check_out, exclude_reservation_id=rid)

    ops.confirm_reservation(res)
    return success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Check-in — Operator
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/check-in", methods=["POST"])
def check_in(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")

    if res["reservation_status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation is not CONFIRMED")
    site = store.sites[res["site_id"]]
    if res["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise errors.err(errors.ERR_INVALID_STATE, "Deposit has not been collected")
    if site["status"] in ("RETIRED", "MAINTENANCE"):
        raise errors.err(errors.ERR_SITE_UNAVAILABLE, "Site is unavailable")
    # Current clock date must be at or after check_in_date.
    if clock_date() < parse_date(res["check_in_date"]):
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot check in before the check-in date")

    ops.check_in_reservation(res)
    return success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Check-out — Operator
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/check-out", methods=["POST"])
def check_out(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    if res["reservation_status"] != "CHECKED_IN":
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation is not CHECKED_IN")
    ops.check_out_reservation(res)
    return success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Cancel — Guest, owner
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel(rid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    _require_owns_reservation(res, user_id, role)
    if res["reservation_status"] not in ("REQUESTED", "CONFIRMED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation cannot be cancelled from its current state")
    ops.cancel_reservation(res)
    return success(serialize_reservation(res), 200)


# ---------------------------------------------------------------------------
# Add-ons — Guest, owner
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/add-ons", methods=["POST"])
def add_addon(rid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    _require_owns_reservation(res, user_id, role)
    body = V.get_json_body()
    V.require_fields(body, ["kind", "amount_cents"])
    kind = V.require_enum(body, "kind", ADDON_KINDS)
    amount = V.require_int(body, "amount_cents", non_negative=True)
    taxable = V.optional_bool(body, "taxable", default=True)

    # Add only while parent reservation is non-terminal.
    if res["reservation_status"] in ("CHECKED_OUT", "CANCELLED"):
        raise errors.err(errors.ERR_ADDON_LOCKED, "Reservation is terminal; add-ons are locked")

    aid = new_id()
    addon = {
        "id": aid,
        "reservation_id": rid,
        "kind": kind,
        "amount_cents": amount,
        "taxable": taxable,
        "status": "ACTIVE",
    }
    stamp_common(addon)
    store.add_ons[aid] = addon

    ops.recompute_provisional(res)
    touch(res)
    return success(serialize_addon(addon), 201)


@bp.route("/reservations/<rid>/add-ons", methods=["GET"])
def list_addons(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    items = [a for a in store.add_ons.values() if a["reservation_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_addon(a) for a in page], limit, offset, total)


@bp.route("/add-ons/<aid>/remove", methods=["POST"])
def remove_addon(aid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    addon = store.add_ons.get(aid)
    if addon is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Add-on not found")
    res = store.reservations.get(addon["reservation_id"])
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    _require_owns_reservation(res, user_id, role)

    # Locked once the parent reservation is terminal.
    if res["reservation_status"] in ("CHECKED_OUT", "CANCELLED"):
        raise errors.err(errors.ERR_ADDON_LOCKED, "Reservation is terminal; add-ons are locked")
    # Must currently be ACTIVE.
    if addon["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Add-on is not ACTIVE")

    addon["status"] = "REMOVED"
    touch(addon)
    ops.recompute_provisional(res)
    touch(res)
    return success(serialize_addon(addon), 200)


# ---------------------------------------------------------------------------
# Payments — Guest, owner
# ---------------------------------------------------------------------------
@bp.route("/reservations/<rid>/payments", methods=["POST"])
def record_payment(rid):
    user_id, role = get_principal()
    require_role(role, {ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    _require_owns_reservation(res, user_id, role)
    body = V.get_json_body()
    V.require_fields(body, ["type", "amount_cents"])
    ptype = V.require_enum(body, "type", PAYMENT_TYPES)
    amount = V.require_int(body, "amount_cents", non_negative=True)
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "reason must be a string")

    amount_paid = compute_amount_paid(rid)

    # The already-settled check (ERR_PAYMENT_ALREADY_SETTLED, 409) is a
    # state-transition legality check on the payment_status dimension; per the
    # global ordering in PRD §2.8, the state-transition legality check (409)
    # precedes the domain-specific business rules (here the fiscal amount check,
    # ERR_PAYMENT_AMOUNT_INVALID, 422). So already-settled is evaluated first.
    if res["payment_status"] in ("PAID_IN_FULL", "REFUNDED"):
        raise errors.err(errors.ERR_PAYMENT_ALREADY_SETTLED, "Reservation is already settled")

    # Fiscal amount check (ERR_PAYMENT_AMOUNT_INVALID, 422).
    if ptype == "DEPOSIT":
        # DEPOSIT amount must equal deposit_due_cents.
        if amount != res["deposit_due_cents"]:
            raise errors.err(
                errors.ERR_PAYMENT_AMOUNT_INVALID,
                "DEPOSIT amount must equal deposit_due_cents",
            )
    else:  # BALANCE
        outstanding = res["total_due_cents"] - amount_paid
        if amount > outstanding:
            raise errors.err(
                errors.ERR_PAYMENT_AMOUNT_INVALID,
                "BALANCE amount exceeds the outstanding balance",
            )

    # DEPOSIT may only be recorded while UNPAID (deposit -> DEPOSIT_PAID transition).
    if ptype == "DEPOSIT" and res["payment_status"] != "UNPAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Deposit may only be recorded while UNPAID")

    payment = ops._append_payment(rid, ptype, amount, reason=reason)

    # Advance payment_status.
    new_amount_paid = compute_amount_paid(rid)
    if ptype == "DEPOSIT":
        res["payment_status"] = "DEPOSIT_PAID"
    if new_amount_paid >= res["total_due_cents"]:
        res["payment_status"] = "PAID_IN_FULL"
    touch(res)
    return success(serialize_payment(payment), 201)


@bp.route("/reservations/<rid>/payments", methods=["GET"])
def list_payments(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    res = store.reservations.get(rid)
    if res is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Reservation not found")
    items = [p for p in store.payments.values() if p["reservation_id"] == rid]
    ptype = request.args.get("type")
    if ptype is not None:
        items = [p for p in items if p["type"] == ptype]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_payment(p) for p in page], limit, offset, total)
