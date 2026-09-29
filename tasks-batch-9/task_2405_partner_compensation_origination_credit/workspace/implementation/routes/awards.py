"""Compensation award endpoints and the immutable draw-payment ledger."""
from flask import Blueprint

from db import new_entity, store, touch
from errors import ApiError
from middleware import authorize
from response import listing, ok
from routes.common import by_created, filtered, find_award, find_payment
from services import calculations as calc
from services.engine import award_payments, commit
from validation import (field_int, get_body, pagination, query_bool, query_enum, query_str)

bp = Blueprint("awards", __name__)

READ_ROLES = ["CycleAdmin", "CommitteeMember", "Partner", "AuditObserver"]
LEDGER_ROLES = ["CycleAdmin", "Partner", "AuditObserver"]


@bp.get("/comp/awards/<award_id>")
def read_award(award_id):
    authorize(READ_ROLES)
    return ok(find_award(award_id))


@bp.get("/comp/awards")
def list_awards():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "cycle_id": query_str("cycle_id"),
        "partner_id": query_str("partner_id"),
        "award_state": query_enum("award_state", calc.AWARD_STATES),
        "payment_state": query_enum("payment_state", calc.PAYMENT_STATES),
    }
    rows = by_created(filtered(store.awards.values(), filters))
    return listing(rows, limit, offset)


def _append_payment(award, kind, amount, memo, period_year=0, period_month=0):
    payment = new_entity({
        "award_id": award["id"],
        "kind": kind,
        "period_year": period_year,
        "period_month": period_month,
        "amount_cents": amount,
        "reversed": False,
        "memo": memo,
    }, common=False)
    store.payments[payment["id"]] = payment
    return payment


@bp.post("/comp/awards/<award_id>/draw-run")
def draw_run(award_id):
    authorize(["CycleAdmin"])
    body = get_body()
    period_year = field_int(body, "period_year", low=2000, high=2100)
    period_month = field_int(body, "period_month", low=1, high=12)
    award = find_award(award_id)

    if award["payment_state"] not in ("PENDING", "DRAWING"):
        raise ApiError("ERR_AWARD_NOT_DRAWABLE")
    if award["award_state"] != "PUBLISHED":
        raise ApiError("ERR_AWARD_NOT_DRAWABLE")
    cycle = store.cycles[award["cycle_id"]]
    if cycle["state"] not in ("AWARDS_PUBLISHED", "TRUE_UP_OPEN"):
        raise ApiError("ERR_AWARD_NOT_DRAWABLE")

    for payment in award_payments(award["id"]):
        if (payment["kind"] == "SCHEDULED_DRAW" and not payment["reversed"]
                and payment["period_year"] == period_year
                and payment["period_month"] == period_month):
            raise ApiError("ERR_DRAW_PERIOD_ALREADY_PAID")

    _append_payment(award, "SCHEDULED_DRAW", award["draw_schedule_monthly_cents"],
                    "Scheduled monthly draw for %04d-%02d." % (period_year, period_month),
                    period_year, period_month)
    award["payment_state"] = "DRAWING"
    touch(award)
    return ok(commit(award))


@bp.post("/comp/awards/<award_id>/true-up")
def true_up(award_id):
    authorize(["CycleAdmin"])
    award = find_award(award_id)
    if award["payment_state"] != "DRAWING":
        raise ApiError("ERR_AWARD_NOT_TRUE_UP_READY")
    cycle = store.cycles[award["cycle_id"]]
    if cycle["state"] != "TRUE_UP_OPEN":
        raise ApiError("ERR_AWARD_NOT_TRUE_UP_READY")

    partner = store.partners[award["partner_id"]]
    final_award = calc.award_amount(award, "FINAL_TRUE_UP")
    delta = final_award - award["draw_paid_cents"]
    capital_call = max(0, partner["target_capital_cents"]
                       - partner["capital_account_balance_cents"])
    withheld = min(capital_call, max(0, delta))

    if withheld > 0:
        _append_payment(award, "CAPITAL_WITHHOLDING", withheld,
                        "Capital withheld from the true-up distribution.")
    if delta - withheld > 0:
        _append_payment(award, "TRUE_UP", delta - withheld,
                        "True-up distribution net of capital withholding.")
    elif delta < 0:
        _append_payment(award, "CLAWBACK", delta,
                        "Clawback of draws in excess of the final award.")

    shortfall = max(0, partner["target_capital_cents"]
                    - (partner["capital_account_balance_cents"] + withheld))
    award["final_award_cents"] = final_award
    award["true_up_delta_cents"] = delta
    award["capital_call_cents"] = capital_call
    award["capital_shortfall_cents"] = shortfall
    award["payment_state"] = "SETTLED" if shortfall == 0 else "TRUED_UP"
    touch(award)
    return ok(commit(award))


@bp.get("/comp/awards/<award_id>/draw-payments")
def list_award_payments(award_id):
    authorize(LEDGER_ROLES)
    limit, offset = pagination()
    filters = {
        "kind": query_enum("kind", calc.PAYMENT_KINDS),
        "reversed": query_bool("reversed"),
    }
    find_award(award_id)
    rows = by_created(filtered(award_payments(award_id), filters))
    return listing(rows, limit, offset)


@bp.get("/comp/draw-payments/<payment_id>")
def read_payment(payment_id):
    authorize(LEDGER_ROLES)
    return ok(find_payment(payment_id))
