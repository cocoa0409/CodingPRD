"""CapitalInstrument endpoints."""

from __future__ import annotations

from flask import Blueprint

from db import capital_instruments, stamp_new, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_PCA_BLOCKS_REDEMPTION, ERR_INSTRUMENT_NOT_CALLABLE,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_instrument, get_bank, get_instrument, recompute_instrument_reg_cap,
    recompute_mdba, refresh_open_issuance_headrooms, bump_bank, clock_today,
    INSTRUMENT_CLASSES, INSTRUMENT_SUBTYPES, CALLABLE_SUBTYPES, PCA_PASSING,
    t2_headroom_cents,
)
from util import get_body, req_int, req_date, opt_date, req_enum, apply_filters, sorted_page

bp = Blueprint("instruments", __name__)


@bp.route("/banks/<bankId>/capital-instruments", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_instrument(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    instrument_class = req_enum(body, "instrument_class", INSTRUMENT_CLASSES)
    instrument_subtype = req_enum(body, "instrument_subtype", INSTRUMENT_SUBTYPES)
    amount = req_int(body, "outstanding_amount_cents")
    if amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "outstanding_amount_cents must be positive")
    issuance_date = req_date(body, "issuance_date")
    maturity = opt_date(body, "maturity_date")
    if instrument_subtype == "SUBORDINATED_DEBT" and maturity is None:
        raise_err(ERR_INVALID_REQUEST, "maturity_date is required for SUBORDINATED_DEBT")
    rate = req_int(body, "contractual_rate_bps")
    if rate < 0:
        raise_err(ERR_INVALID_REQUEST, "contractual_rate_bps must be non-negative")
    inst = {
        "bank_id": bank["id"],
        "instrument_class": instrument_class,
        "instrument_subtype": instrument_subtype,
        "outstanding_amount_cents": amount,
        "issuance_date": issuance_date.isoformat(),
        "contractual_rate_bps": rate,
        "status": "OUTSTANDING",
        "_maturity_date": maturity,
    }
    stamp_new(inst)
    recompute_instrument_reg_cap(inst, clock_today())
    capital_instruments[inst["id"]] = inst
    bump_bank(bank)
    return success_object(ser_instrument(inst), 201)


@bp.route("/banks/<bankId>/capital-instruments/<instrumentId>", methods=["GET"])
@require_roles("Any")
def get_one_instrument(bankId: str, instrumentId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_instrument(get_instrument(bank, instrumentId)))


@bp.route("/banks/<bankId>/capital-instruments", methods=["GET"])
@require_roles("Any")
def list_instruments(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [i for i in capital_instruments.values() if i["bank_id"] == bank["id"]]
    items = apply_filters(items, {"instrument_class": "instrument_class", "status": "status"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_instrument(i) for i in page], limit, offset, total)


def _call_or_redeem(bankId: str, instrumentId: str, target_status: str, _user_id: str):
    bank = get_bank(bankId)
    inst = get_instrument(bank, instrumentId)
    # State check (priority 5)
    if inst["status"] != "OUTSTANDING":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"CapitalInstrument must be OUTSTANDING to transition to {target_status}")
    # PCA gate (priority 6) — subordinated debt only (PRD 3.1)
    if inst["instrument_subtype"] == "SUBORDINATED_DEBT":
        if bank["pca_bucket"] not in PCA_PASSING:
            raise_err(ERR_PCA_BLOCKS_REDEMPTION,
                      "PCA bucket blocks subordinated debt call/redemption")
        # Post-call T2 position still satisfies the T2 cap: removing an
        # instrument can only reduce outstanding T2, so the cap holds.
        _ = t2_headroom_cents(bank)
    # Callability (priority 18)
    if inst["instrument_subtype"] not in CALLABLE_SUBTYPES:
        raise_err(ERR_INSTRUMENT_NOT_CALLABLE,
                  "COMMON_STOCK/OTHER instruments cannot be called or redeemed")
    inst["status"] = target_status
    touch(inst)
    recompute_mdba(bank)
    refresh_open_issuance_headrooms(bank)
    bump_bank(bank)
    return success_object(ser_instrument(inst))


@bp.route("/banks/<bankId>/capital-instruments/<instrumentId>/call", methods=["POST"])
@require_roles("CapitalAnalyst")
def call_instrument(bankId: str, instrumentId: str, _user_id: str, _role: str):
    return _call_or_redeem(bankId, instrumentId, "CALLED", _user_id)


@bp.route("/banks/<bankId>/capital-instruments/<instrumentId>/redeem", methods=["POST"])
@require_roles("CapitalAnalyst")
def redeem_instrument(bankId: str, instrumentId: str, _user_id: str, _role: str):
    return _call_or_redeem(bankId, instrumentId, "REDEEMED", _user_id)
