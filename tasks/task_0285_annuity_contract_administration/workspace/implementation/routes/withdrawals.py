"""Withdrawal endpoints (PRD §3.5).

Settle computes, in pinned order: corridor split -> surrender charge ->
market value adjustment, then debits accumulation and (if full surrender)
cascades the contract to SURRENDERED.
"""

from decimal import Decimal

from flask import Blueprint

import errors
import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import contract as contract_svc
from services import lookups
from services.money import round_half_up_decimal, floor_div

bp = Blueprint("withdrawals", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}
MARKET_REFERENCE_BPS = 500
ASSUMED_GROWTH_BPS = 400


def serialize(w):
    return {
        "id": w["id"],
        "contract_id": w["contract_id"],
        "requested_amount_cents": w["requested_amount_cents"],
        "is_full_surrender": w["is_full_surrender"],
        "free_amount_cents": w["free_amount_cents"],
        "chargeable_amount_cents": w["chargeable_amount_cents"],
        "surrender_charge_cents": w["surrender_charge_cents"],
        "mva_cents": w["mva_cents"],
        "gross_withdrawal_cents": w["gross_withdrawal_cents"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.post("/withdrawals")
def create_withdrawal():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    requested = v.require_int(body, "requested_amount_cents", minimum=1)
    expected_version = v.require_int(body, "expected_contract_version")
    is_full = v.require_bool(body, "is_full_surrender", required=False, default=False)

    contract = lookups.ref_contract(contract_id)

    # OCC against live contract version.
    if expected_version != contract["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_CONTRACT_VERSION, 412, "Stale contract version."
        )

    # Frozen contract rejects new withdrawal creation. A frozen contract is in
    # DEATH_CLAIM status (not ACTIVE), so the freeze must be reported as
    # ERR_CONTRACT_FROZEN before the bare ACTIVE-state check (PRD §3.9).
    if contract_svc.is_frozen(contract):
        raise errors.ApiError(
            errors.ERR_CONTRACT_FROZEN, 409, "Contract is frozen by an open death claim."
        )

    # State: contract must be ACTIVE to request a withdrawal.
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")

    now = store.clock.now()
    wid = store.new_id()
    withdrawal = {
        "id": wid,
        "contract_id": contract_id,
        "requested_amount_cents": requested,
        "is_full_surrender": is_full,
        "free_amount_cents": None,
        "chargeable_amount_cents": None,
        "surrender_charge_cents": None,
        "mva_cents": None,
        "gross_withdrawal_cents": None,
        "status": "REQUESTED",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.withdrawals[wid] = withdrawal

    # Requesting a withdrawal bumps the contract version (per §1.5 side effect).
    contract_svc.bump(contract)

    return object_response(serialize(withdrawal), 201, now)


@bp.get("/withdrawals/<rid>")
def get_withdrawal(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    withdrawal = lookups.path_withdrawal(rid)
    return object_response(serialize(withdrawal), 200, store.clock.now())


@bp.post("/withdrawals/<rid>/settle")
def settle_withdrawal(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    withdrawal = lookups.path_withdrawal(rid)
    contract = store.contracts[withdrawal["contract_id"]]
    product = store.products[contract["product_id"]]

    # State legality: withdrawal must be REQUESTED.
    if withdrawal["status"] != "REQUESTED":
        raise errors.invalid_state("Withdrawal is not REQUESTED.")

    # Frozen contract rejects settlement. A frozen contract is in DEATH_CLAIM
    # status (not ACTIVE), so the freeze must be reported as ERR_CONTRACT_FROZEN
    # before the bare ACTIVE-state check (PRD §3.9).
    if contract_svc.is_frozen(contract):
        raise errors.ApiError(
            errors.ERR_CONTRACT_FROZEN, 409, "Contract is frozen by an open death claim."
        )

    # Contract must be ACTIVE to settle.
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")

    requested = withdrawal["requested_amount_cents"]

    # (1) Corridor split — allowance floors, remaining never negative.
    allowance = floor_div(
        contract["highest_anniversary_value_cents"]
        * product["free_withdrawal_corridor_bps"],
        10000,
    )
    remaining_corridor = max(0, allowance - contract["free_withdrawal_used_cents"])
    free_amount = min(requested, remaining_corridor)
    chargeable = requested - free_amount

    # (2) Surrender charge on the chargeable remainder.
    charge_bps = contract_svc.surrender_charge_bps(contract)
    surrender_charge = round_half_up_decimal(
        Decimal(chargeable) * Decimal(charge_bps) / Decimal(10000)
    )

    # (3) MVA on the chargeable remainder, after the charge is fixed.
    if product["mva_enabled"]:
        schedule_len = len(product["surrender_charge_schedule"] or [])
        cy = contract_svc.contract_year(contract)
        years_remaining = max(0, schedule_len - cy)
        fixed_rate = product["fixed_annual_rate_bps"]
        ref_rate = fixed_rate if fixed_rate is not None else ASSUMED_GROWTH_BPS
        rate_diff_bps = MARKET_REFERENCE_BPS - ref_rate
        mva = round_half_up_decimal(
            Decimal(chargeable)
            * Decimal(rate_diff_bps)
            * Decimal(years_remaining)
            / Decimal(1000000)
        )
    else:
        mva = 0

    gross = requested + surrender_charge + mva

    # Sizing check: gross must not exceed current accumulation.
    acc = contract_svc.accumulation_value_cents(contract)
    if gross > acc:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_ACCUMULATION,
            409,
            "Withdrawal gross exceeds the contract accumulation value.",
        )

    now = store.clock.now()
    withdrawal["free_amount_cents"] = free_amount
    withdrawal["chargeable_amount_cents"] = chargeable
    withdrawal["surrender_charge_cents"] = surrender_charge
    withdrawal["mva_cents"] = mva
    withdrawal["gross_withdrawal_cents"] = gross
    withdrawal["status"] = "SETTLED"
    withdrawal["version"] += 1
    withdrawal["updated_at"] = iso8601(now)

    # Debit and consume corridor.
    contract["free_withdrawal_used_cents"] += free_amount

    # Full-surrender cascade ACTIVE -> SURRENDERED.
    if withdrawal["is_full_surrender"]:
        contract["status"] = "SURRENDERED"
        contract_svc.liquidate_allocations(contract)
    contract_svc.bump(contract)

    return object_response(serialize(withdrawal), 200, now)


@bp.post("/withdrawals/<rid>/reject")
def reject_withdrawal(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    withdrawal = lookups.path_withdrawal(rid)
    if withdrawal["status"] != "REQUESTED":
        raise errors.invalid_state("Withdrawal is not REQUESTED.")
    now = store.clock.now()
    withdrawal["status"] = "REJECTED"
    withdrawal["version"] += 1
    withdrawal["updated_at"] = iso8601(now)
    return object_response(serialize(withdrawal), 200, now)
