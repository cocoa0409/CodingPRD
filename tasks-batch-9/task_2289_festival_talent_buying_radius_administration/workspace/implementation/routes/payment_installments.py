"""Payment installments: release, mark-paid and clawback."""

from datetime import timedelta

from flask import Blueprint

from db import db, iso_instant, public, public_list, touch
from errors import fail
from middleware import endpoint, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    load,
    pagination,
    query_enum,
    req_int,
    stored_date,
)

bp = Blueprint("payment_installments", __name__)

INSTALLMENT_STATUSES = (
    "SCHEDULED",
    "HELD",
    "RELEASED",
    "PAID",
    "VOIDED",
    "CLAWBACK_PENDING",
    "RECOVERED",
)
INSTALLMENT_TYPES = ("DEPOSIT", "BALANCE")
READ_ROLES = ["TalentBuyer", "ArtistRep", "BusinessAffairs", "FinanceController"]


def _booking_of(row):
    return db.bookings.get(row["booking_id"])


def _check_breach(booking):
    if booking is None:
        return
    if booking["settlement_status"] == "WITHHELD":
        fail("ERR_RADIUS_BREACH_ACTIVE", "the booking's money is withheld")
    if any(
        c["enforcement_status"] == "BREACHED"
        for c in calc.clauses_for_booking(booking["id"])
    ):
        fail("ERR_RADIUS_BREACH_ACTIVE", "a breached radius clause blocks payment")


@bp.get("/bookings/<booking_id>/payment-installments")
@endpoint(READ_ROLES)
def list_booking_installments(booking_id):
    status = query_enum("status", INSTALLMENT_STATUSES)
    installment_type = query_enum("installment_type", INSTALLMENT_TYPES)
    limit, offset = pagination()
    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])

    rows = calc.booking_installments(booking["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if installment_type is not None:
        rows = [r for r in rows if r["installment_type"] == installment_type]
    rows = calc.sorted_rows(rows, [("due_date", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.get("/payment-installments/<installment_id>")
@endpoint(READ_ROLES)
def get_installment(installment_id):
    row = load("payment_installments", installment_id)
    booking = _booking_of(row)
    if booking is not None:
        require_artist_scope(booking["artist_id"])
    return respond_object(public(row))


@bp.post("/payment-installments/<installment_id>/release")
@endpoint(["FinanceController"])
def release_installment(installment_id):
    row = load("payment_installments", installment_id)
    booking = _booking_of(row)

    if row["status"] != "SCHEDULED":
        fail("ERR_INVALID_INSTALLMENT_STATE", "only a scheduled installment may be released")
    if row["installment_type"] == "BALANCE":
        if booking is None or booking["contract_status"] != "COUNTERSIGNED":
            fail(
                "ERR_INVALID_BOOKING_STATE",
                "the balance may not move before countersignature",
            )
    _check_breach(booking)

    window_open = stored_date(row["due_date"]) - timedelta(days=calc.RELEASE_WINDOW_DAYS)
    if db.clock.date() < window_open:
        fail("ERR_PAYMENT_NOT_RELEASABLE", "the release window has not opened")

    row["status"] = "RELEASED"
    row["released_at"] = iso_instant(db.clock)
    touch(row)

    if (
        row["installment_type"] == "BALANCE"
        and booking is not None
        and booking["settlement_status"] == "DEPOSIT_PAID"
    ):
        booking["settlement_status"] = "BALANCE_DUE"
        derive.recompute_booking_money(booking)
        touch(booking)
    return respond_object(public(row))


@bp.post("/payment-installments/<installment_id>/mark-paid")
@endpoint(["FinanceController"])
def mark_paid(installment_id):
    payload = body()
    paid_amount_cents = req_int(payload, "paid_amount_cents", 0, None)

    row = load("payment_installments", installment_id)
    booking = _booking_of(row)

    if row["status"] != "RELEASED":
        fail("ERR_INVALID_INSTALLMENT_STATE", "only a released installment may be paid")
    _check_breach(booking)

    row["status"] = "PAID"
    row["paid_at"] = iso_instant(db.clock)
    row["paid_amount_cents"] = paid_amount_cents
    touch(row)

    if booking is not None:
        if row["installment_type"] == "DEPOSIT":
            if booking["settlement_status"] == "UNFUNDED":
                booking["settlement_status"] = "DEPOSIT_PAID"
        else:
            if booking["settlement_status"] == "BALANCE_DUE":
                booking["settlement_status"] = "SETTLED"
            if booking["contract_status"] == "COUNTERSIGNED":
                booking["contract_status"] = "CLOSED_OUT"
        derive.recompute_booking_money(booking)
        touch(booking)
    return respond_object(public(row))


@bp.post("/payment-installments/<installment_id>/clawback")
@endpoint(["FinanceController"])
def clawback(installment_id):
    payload = body()
    recovered_cents = req_int(payload, "recovered_cents", 0, None)

    row = load("payment_installments", installment_id)
    booking = _booking_of(row)

    if row["status"] != "CLAWBACK_PENDING":
        fail(
            "ERR_INVALID_INSTALLMENT_STATE",
            "only an installment pending clawback may be recovered",
        )
    if recovered_cents > row["paid_amount_cents"]:
        fail(
            "ERR_RECOVERY_EXCEEDS_CONTRACTUAL",
            "a clawback may not exceed the amount actually paid",
        )
    if booking is not None:
        if (
            booking["actual_recovered_cents"] + recovered_cents
            > booking["contractual_recovery_cents"]
        ):
            fail(
                "ERR_RECOVERY_EXCEEDS_CONTRACTUAL",
                "the clawback would exceed the contractual ceiling",
            )

    row["status"] = "RECOVERED"
    row["recovered_cents"] = recovered_cents
    touch(row)

    if booking is not None:
        remaining = any(
            r["status"] == "CLAWBACK_PENDING"
            for r in calc.booking_installments(booking["id"])
        )
        if not remaining and booking["settlement_status"] == "RECOVERY_PENDING":
            booking["settlement_status"] = "RECOVERED"
        derive.recompute_booking_money(booking)
        touch(booking)
    return respond_object(public(row))
