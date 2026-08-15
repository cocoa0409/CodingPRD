"""SubordinatedDebtIssuance endpoints (PRD 3.7)."""

from __future__ import annotations

from flask import Blueprint

from db import sub_debt_issuances, capital_instruments, stamp_new, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_PCA_BLOCKS_ISSUANCE, ERR_MATURITY_TOO_SHORT, ERR_T2_CAP_EXCEEDED,
    ERR_TEMPORAL_VIOLATION,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_issuance, get_bank, get_issuance, bump_bank, clock_today,
    PCA_PASSING, t2_headroom_cents, refresh_open_issuance_headrooms,
    recompute_instrument_reg_cap, recompute_mdba,
)
from util import (
    get_body, req_int, req_date, apply_filters, sorted_page, add_years,
    require_occ_field, check_occ_matches,
)

bp = Blueprint("subdebt", __name__)


@bp.route("/banks/<bankId>/sub-debt-issuances", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_issuance(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    amount = req_int(body, "proposed_amount_cents")
    if amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "proposed_amount_cents must be positive")
    rate = req_int(body, "proposed_rate_bps")
    if rate <= 0:
        raise_err(ERR_INVALID_REQUEST, "proposed_rate_bps must be positive")
    maturity_years = req_int(body, "maturity_years")
    target = req_date(body, "target_settlement_date")
    issuance = {
        "bank_id": bank["id"],
        "proposed_amount_cents": amount,
        "proposed_rate_bps": rate,
        "maturity_years": maturity_years,
        "t2_capacity_headroom_cents": t2_headroom_cents(bank),
        "capital_instrument_id": None,
        "status": "PROPOSED",
        "_target_settlement_date": target,
    }
    stamp_new(issuance)
    sub_debt_issuances[issuance["id"]] = issuance
    return success_object(ser_issuance(issuance), 201)


@bp.route("/banks/<bankId>/sub-debt-issuances/<issuanceId>", methods=["GET"])
@require_roles("Any")
def get_one_issuance(bankId: str, issuanceId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_issuance(get_issuance(bank, issuanceId)))


@bp.route("/banks/<bankId>/sub-debt-issuances", methods=["GET"])
@require_roles("Any")
def list_issuances(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [s for s in sub_debt_issuances.values() if s["bank_id"] == bank["id"]]
    items = apply_filters(items, {"status": "status"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_issuance(s) for s in page], limit, offset, total)


@bp.route("/banks/<bankId>/sub-debt-issuances/<issuanceId>/approve", methods=["POST"])
@require_roles("CapitalAnalyst")
def approve_issuance(bankId: str, issuanceId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    issuance = get_issuance(bank, issuanceId)
    # Envelope-level: expected_bank_version presence/type (PRD 2.8 requires it).
    body = get_body()
    expected = require_occ_field(body)
    # State (priority 5).
    if issuance["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROPOSED issuance can be approved")
    # PCA gate (priority 6).
    if bank["pca_bucket"] not in PCA_PASSING:
        raise_err(ERR_PCA_BLOCKS_ISSUANCE, "PCA bucket blocks new sub-debt issuance approval")
    # Temporal (priority 9): T2-eligible term at issuance.
    if issuance["maturity_years"] < 5:
        raise_err(ERR_MATURITY_TOO_SHORT, "maturity_years must be >= 5 for T2 eligibility")
    # Capacity (priority 10).
    headroom = t2_headroom_cents(bank)
    if issuance["proposed_amount_cents"] > headroom:
        raise_err(ERR_T2_CAP_EXCEEDED, "Proposed amount exceeds the T2 capacity headroom")
    # OCC (priority 19).
    check_occ_matches(expected, bank)

    issuance["t2_capacity_headroom_cents"] = headroom
    issuance["status"] = "APPROVED"
    touch(issuance)
    bump_bank(bank)
    return success_object(ser_issuance(issuance))


@bp.route("/banks/<bankId>/sub-debt-issuances/<issuanceId>/price", methods=["POST"])
@require_roles("CapitalAnalyst")
def price_issuance(bankId: str, issuanceId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    issuance = get_issuance(bank, issuanceId)
    if issuance["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an APPROVED issuance can be priced")
    issuance["status"] = "PRICED"
    touch(issuance)
    return success_object(ser_issuance(issuance))


@bp.route("/banks/<bankId>/sub-debt-issuances/<issuanceId>/settle", methods=["POST"])
@require_roles("CapitalAnalyst")
def settle_issuance(bankId: str, issuanceId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    issuance = get_issuance(bank, issuanceId)
    if issuance["status"] != "PRICED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PRICED issuance can be settled")
    today = clock_today()
    if today < issuance["_target_settlement_date"]:
        raise_err(ERR_TEMPORAL_VIOLATION, "Current time is before target_settlement_date")
    # Re-verify the T2 cap at settlement against fresh headroom.
    headroom = t2_headroom_cents(bank)
    if issuance["proposed_amount_cents"] > headroom:
        raise_err(ERR_T2_CAP_EXCEEDED, "Proposed amount exceeds the T2 capacity headroom at settlement")
    inst = {
        "bank_id": bank["id"],
        "instrument_class": "T2",
        "instrument_subtype": "SUBORDINATED_DEBT",
        "outstanding_amount_cents": issuance["proposed_amount_cents"],
        "issuance_date": today.isoformat(),
        "contractual_rate_bps": issuance["proposed_rate_bps"],
        "status": "OUTSTANDING",
        "_maturity_date": add_years(today, issuance["maturity_years"]),
    }
    stamp_new(inst)
    recompute_instrument_reg_cap(inst, today)
    capital_instruments[inst["id"]] = inst
    issuance["capital_instrument_id"] = inst["id"]
    issuance["status"] = "SETTLED"
    touch(issuance)
    refresh_open_issuance_headrooms(bank)
    recompute_mdba(bank)
    bump_bank(bank)
    return success_object(ser_issuance(issuance))


@bp.route("/banks/<bankId>/sub-debt-issuances/<issuanceId>/withdraw", methods=["POST"])
@require_roles("CapitalAnalyst")
def withdraw_issuance(bankId: str, issuanceId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    issuance = get_issuance(bank, issuanceId)
    if issuance["status"] not in ("PROPOSED", "APPROVED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only a PROPOSED or APPROVED issuance can be withdrawn")
    issuance["status"] = "WITHDRAWN"
    touch(issuance)
    return success_object(ser_issuance(issuance))
