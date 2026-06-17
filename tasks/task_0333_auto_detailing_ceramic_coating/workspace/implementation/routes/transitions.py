"""Appointment work-status and payment-status transition endpoints
(PRD §3.4, §3.6, §3.7) plus the final-price/loyalty/refund cascades."""
from flask import Blueprint, request

import auth
import clock
import db
import domain
from domain import (
    touch, compute_final, recompute_outstanding, recompute_chronological,
    recompute_projected, deposit_amount,
)
from errors import err
from response import object_response
from serialize import serialize
from timeutil import add_minutes
from validation import get_body, require_int
from routes.appointments import _has_photo

bp = Blueprint("transitions", __name__)


def _uid():
    return request.headers.get("X-User-ID")


def _load(aid, role, allowed, own_ok=False):
    auth.require_role(role, allowed)
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    if own_ok:
        auth.require_owner(role, _uid(), appt["customer_id"])
    return appt


def _final_price_cascade(appt):
    """READY cascade: recompute final_total_cents (final variant) then outstanding."""
    appt["final_total_cents"] = compute_final(appt)
    recompute_outstanding(appt)


# =====================================================================
# Work-status transitions (Detailer-driven unless noted)
# =====================================================================
@bp.route("/detailing/appointments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer"})
    if appt["work_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "check-in requires BOOKED")
    # now >= scheduled_start - 60 minutes.
    if clock.now() < add_minutes(appt["scheduled_start_utc"], -60):
        raise err("ERR_INVALID_STATE", "too early to check in")
    # assigned resource must be AVAILABLE.
    if appt["location_mode"] == "SHOP":
        bay = db.service_bays.get(appt["service_bay_id"])
        if not bay or bay["status"] != "AVAILABLE":
            raise err("ERR_RESOURCE_UNAVAILABLE", "service bay not available")
    else:
        unit = db.mobile_units.get(appt["mobile_unit_id"])
        if not unit or unit["status"] != "AVAILABLE":
            raise err("ERR_RESOURCE_UNAVAILABLE", "mobile unit not available")
    appt["work_status"] = "CHECKED_IN"
    touch(appt)
    recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/start-prep", methods=["POST"])
def start_prep(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer"})
    if appt["work_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "start-prep requires CHECKED_IN")
    if not _has_photo(aid, "BEFORE"):
        raise err("ERR_PHOTO_REQUIRED", "BEFORE photo required")
    appt["work_status"] = "IN_PREP"
    touch(appt)
    recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/start-service", methods=["POST"])
def start_service(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer"})
    if appt["work_status"] != "IN_PREP":
        raise err("ERR_INVALID_STATE", "start-service requires IN_PREP")
    appt["work_status"] = "IN_SERVICE"
    touch(appt)
    recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/finish-service", methods=["POST"])
def finish_service(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer"})
    if appt["work_status"] != "IN_SERVICE":
        raise err("ERR_INVALID_STATE", "finish-service requires IN_SERVICE")
    if not _has_photo(aid, "AFTER"):
        raise err("ERR_PHOTO_REQUIRED", "AFTER photo required")
    if appt["tier"] == "CERAMIC":
        appt["work_status"] = "CURING"
        touch(appt)
        recompute_projected(appt["customer_id"])
    else:
        appt["work_status"] = "READY"
        _final_price_cascade(appt)
        touch(appt)
        recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/finish-cure", methods=["POST"])
def finish_cure(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer"})
    if appt["work_status"] != "CURING":
        raise err("ERR_INVALID_STATE", "finish-cure requires CURING")
    if clock.now() < appt["vehicle_release_utc"]:
        raise err("ERR_CURE_NOT_ELAPSED", "cure not elapsed")
    appt["work_status"] = "READY"
    _final_price_cascade(appt)
    touch(appt)
    recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/release", methods=["POST"])
def release(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Detailer", "ShopManager"})
    if appt["work_status"] != "READY":
        raise err("ERR_INVALID_STATE", "release requires READY")
    is_rework = appt["spawned_from_rework_claim_id"] is not None
    if not is_rework and appt["outstanding_balance_cents"] != 0:
        raise err("ERR_BALANCE_OUTSTANDING", "outstanding balance must be zero")
    appt["work_status"] = "RELEASED"
    touch(appt)
    # release cascade: realized chronological spend + loyalty tier.
    recompute_chronological(appt["customer_id"])
    # if rework-spawned, close the originating claim.
    if is_rework:
        claim = db.rework_claims.get(appt["spawned_from_rework_claim_id"])
        if claim and claim["status"] == "APPROVED":
            claim["status"] = "FULFILLED"
            touch(claim)
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Customer", "ShopManager"}, own_ok=True)
    if appt["work_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "cancel requires BOOKED")
    if appt["spawned_from_rework_claim_id"] is not None:
        # rework appointments cannot be self-cancelled.
        raise err("ERR_INVALID_STATE", "rework appointment cannot be cancelled")
    appt["work_status"] = "CANCELLED"
    if appt["payment_status"] == "DEPOSIT_HELD":
        appt["amount_refunded_cents"] += appt["amount_charged_cents"]
        appt["payment_status"] = "REFUNDED"
        recompute_outstanding(appt)
    touch(appt)
    # appointment leaves the projected set; recompute projected + loyalty.
    recompute_chronological(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Scheduler", "ShopManager"})
    if appt["work_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "mark-no-show requires BOOKED")
    if clock.now() < add_minutes(appt["scheduled_start_utc"], 30):
        raise err("ERR_INVALID_STATE", "too early to mark no-show")
    appt["work_status"] = "NO_SHOW"
    # deposit forfeited: no refund, payment_status unchanged (stays DEPOSIT_HELD).
    touch(appt)
    recompute_projected(appt["customer_id"])
    return object_response(serialize(appt))


# =====================================================================
# Payment-status transitions
# =====================================================================
@bp.route("/detailing/appointments/<aid>/capture-deposit", methods=["POST"])
def capture_deposit(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Customer", "ShopManager"}, own_ok=True)
    body = get_body()
    deposit_cents = require_int(body, "deposit_cents")
    if appt["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "capture-deposit requires UNPAID")
    if appt["work_status"] in {"CANCELLED", "NO_SHOW", "RELEASED"}:
        raise err("ERR_INVALID_STATE", "appointment is in a terminal work state")
    required = deposit_amount(appt["provisional_total_cents"])
    if deposit_cents != required:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "deposit amount mismatch")
    appt["amount_charged_cents"] += deposit_cents
    appt["payment_status"] = "DEPOSIT_HELD"
    recompute_outstanding(appt)
    touch(appt)
    # deposit transition recomputes chronological + loyalty (§3.6).
    recompute_chronological(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/pay", methods=["POST"])
def pay(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"Customer", "ShopManager"}, own_ok=True)
    body = get_body()
    amount_cents = require_int(body, "amount_cents")
    if appt["payment_status"] not in {"UNPAID", "DEPOSIT_HELD"}:
        raise err("ERR_INVALID_STATE", "pay requires UNPAID or DEPOSIT_HELD")
    if appt["work_status"] != "READY":
        raise err("ERR_INVALID_STATE", "pay requires READY")
    if amount_cents != appt["outstanding_balance_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "payment amount mismatch")
    appt["amount_charged_cents"] += amount_cents
    appt["payment_status"] = "PAID"
    recompute_outstanding(appt)
    touch(appt)
    recompute_chronological(appt["customer_id"])
    return object_response(serialize(appt))


@bp.route("/detailing/appointments/<aid>/refund", methods=["POST"])
def refund(aid):
    _, role = auth.get_identity()
    appt = _load(aid, role, {"ShopManager"})
    if appt["payment_status"] != "PAID":
        raise err("ERR_INVALID_STATE", "refund requires PAID")
    appt["amount_refunded_cents"] += appt["amount_charged_cents"]
    appt["payment_status"] = "REFUNDED"
    recompute_outstanding(appt)
    touch(appt)
    # refund cascade: recompute realized chronological spend + loyalty.
    recompute_chronological(appt["customer_id"])
    return object_response(serialize(appt))
