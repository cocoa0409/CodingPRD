"""Reserve funds, the ledger and the adequacy disclosure."""

from flask import Blueprint

from db import db, make_record, ordered, touch
from errors import fail
from middleware import authorize, body, req_enum, req_int, req_str
from response import object_response, raw_object_response
from routes.helpers import fund_or_404, listing, transaction_or_404
from services import calc, cascade

bp = Blueprint("funds", __name__)

FUND_ROLES = ("ForecastDirector", "ReserveTreasurer", "LegislativeVoter", "RatingAnalyst")
DEPOSIT_VARIANTS = ("GROWTH_ABOVE_TREND", "VOLATILE_SOURCE_CAPTURE")
RATIONALE_MIN = 20


# ------------------------------------------------------------------ reads ----
@bp.get("/reserve-funds")
@authorize(*FUND_ROLES)
def list_funds():
    return listing(
        ordered(db.funds),
        {
            "deposit_posture": ("deposit_posture", str),
            "adequacy_band": ("adequacy_band", str),
            "deposit_rule_variant": ("deposit_rule_variant", str),
        },
    )


@bp.get("/reserve-funds/<fund_id>")
@authorize(*FUND_ROLES)
def get_fund(fund_id):
    return object_response(fund_or_404(fund_id))


@bp.get("/reserve-funds/<fund_id>/adequacy")
@authorize(*FUND_ROLES)
def fund_adequacy(fund_id):
    fund = fund_or_404(fund_id)
    figures = calc.adequacy_figures(fund)
    cap = figures["cap_cents"]
    return raw_object_response(
        {
            "fund_id": fund["id"],
            "reference_cycle_id": figures["reference_cycle_id"],
            "volatility_index_bps": figures["volatility_index_bps"],
            "target_pct_bps": figures["target_pct_bps"],
            "required_reserve_cents": figures["required_reserve_cents"],
            "coverage_ratio_bps": figures["coverage_ratio_bps"],
            "adequacy_band": figures["adequacy_band"],
            "cushion_credit_bps": figures["cushion_credit_bps"],
            "disclosed_target_pct_bps": figures["disclosed_target_pct_bps"],
            "cap_cents": cap,
            "headroom_cents": None if cap is None else max(0, cap - fund["balance_cents"]),
            "annual_withdrawal_cap_cents": calc.annual_withdrawal_cap_cents(fund),
            "cap_headroom_cents": calc.cap_headroom_cents(fund),
        }
    )


@bp.get("/reserve-transactions")
@authorize(*FUND_ROLES)
def list_transactions():
    return listing(
        ordered(db.transactions),
        {
            "fund_id": ("fund_id", str),
            "origin": ("origin", str),
            "source_cycle_id": ("source_cycle_id", str),
            "reverses_transaction_id": ("reverses_transaction_id", str),
        },
    )


@bp.get("/reserve-transactions/<transaction_id>")
@authorize(*FUND_ROLES)
def get_transaction(transaction_id):
    return object_response(transaction_or_404(transaction_id))


# ----------------------------------------------------------------- writes ----
@bp.post("/reserve-funds")
@authorize("ForecastDirector")
def create_fund():
    data = body()
    name = req_str(data, "name")
    cap_pct = req_int(data, "cap_pct_bps", minimum=1, maximum=10000)
    trend = req_int(data, "trend_growth_rate_bps", minimum=0)
    capture = req_int(data, "capture_rate_bps", minimum=1, maximum=10000)
    variant = req_enum(data, "deposit_rule_variant", DEPOSIT_VARIANTS)
    seats = req_int(data, "eligible_seats", minimum=1)
    withdrawal_cap = req_int(data, "annual_withdrawal_cap_pct_bps", minimum=1, maximum=10000)
    cooling = req_int(data, "cooling_off_days", minimum=0)
    opening = req_int(data, "opening_balance_cents", minimum=0)

    rec = make_record(
        {
            "name": name,
            "cap_pct_bps": cap_pct,
            "trend_growth_rate_bps": trend,
            "capture_rate_bps": capture,
            "deposit_rule_variant": variant,
            "eligible_seats": seats,
            "annual_withdrawal_cap_pct_bps": withdrawal_cap,
            "cooling_off_days": cooling,
            "opening_balance_cents": opening,
            "balance_cents": opening,
            "fy_opening_balance_cents": opening,
            "fy_withdrawn_cents": 0,
            "deposit_posture": "ACCEPTING",
            "cap_cents": None,
            "volatility_index_bps": 0,
            "target_pct_bps": 500,
            "required_reserve_cents": None,
            "coverage_ratio_bps": 0,
            "adequacy_band": "INSUFFICIENT",
            "cushion_credit_bps": 0,
            "disclosed_target_pct_bps": 500,
            "cooling_off_until": None,
            "last_transaction_at": None,
        }
    )
    db.funds[rec["id"]] = rec
    return object_response(rec, 201)


@bp.post("/reserve-funds/<fund_id>/deposits")
@authorize("ReserveTreasurer")
def create_deposit(fund_id):
    fund = fund_or_404(fund_id)
    data = body()
    amount = req_int(data, "amount_cents", minimum=1)
    memo = req_str(data, "memo")

    if fund["deposit_posture"] != "ACCEPTING":
        fail("ERR_FUND_AT_CAP", "the fund is at its statutory cap")
    cap = fund["cap_cents"]
    if cap is not None:
        headroom = max(0, cap - fund["balance_cents"])
        if amount > headroom:
            fail("ERR_DEPOSIT_EXCEEDS_CAP",
                 "a manual deposit of %d exceeds the remaining headroom %d" % (amount, headroom))

    row = cascade.mint_transaction(fund, "MANUAL_DEPOSIT", amount, gross=amount, overflow=0,
                                  memo=memo)
    cascade.balance_changed(fund)
    return object_response(row, 201)


@bp.post("/reserve-transactions/<transaction_id>/reverse")
@authorize("ReserveTreasurer")
def reverse_transaction(transaction_id):
    original = transaction_or_404(transaction_id)
    data = body()
    rationale = req_str(data, "rationale")

    fund = db.funds.get(original["fund_id"])
    already = any(t.get("reverses_transaction_id") == original["id"]
                  for t in calc.transactions_of(original["fund_id"]))
    if original["origin"] not in ("CERTIFICATION_DEPOSIT", "MANUAL_DEPOSIT", "WITHDRAWAL") \
            or already:
        fail("ERR_TRANSACTION_ALREADY_REVERSED",
             "this ledger row may not be reversed")
    if len(rationale) < RATIONALE_MIN:
        fail("ERR_RATIONALE_TOO_SHORT",
             "rationale must be at least %d characters" % RATIONALE_MIN)

    signed = -original["signed_amount_cents"]
    if fund["balance_cents"] + signed < 0:
        fail("ERR_REVERSAL_WOULD_OVERDRAW", "the reversal would drive the balance below zero")

    row = cascade.mint_transaction(fund, "REVERSAL", signed,
                                   reverses=original["id"], memo=rationale)
    cascade.balance_changed(fund)  # releases fy_withdrawn_cents for WITHDRAWAL rows
    return object_response(row, 201)


@bp.post("/reserve-funds/<fund_id>/recompute-adequacy")
@authorize("ForecastDirector", "ReserveTreasurer")
def recompute_adequacy(fund_id):
    fund = fund_or_404(fund_id)
    cascade.apply_adequacy(fund)
    cascade.apply_posture(fund)
    touch(fund)
    return object_response(fund)
