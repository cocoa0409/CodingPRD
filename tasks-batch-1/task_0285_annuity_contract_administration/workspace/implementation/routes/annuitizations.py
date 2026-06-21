"""Annuitization endpoints (PRD §3.8)."""

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
from services.money import round_half_up_decimal

bp = Blueprint("annuitizations", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}
PAYOUT_OPTIONS = {"LIFE_ONLY", "PERIOD_CERTAIN", "LIFE_WITH_PERIOD_CERTAIN", "JOINT_LIFE"}
PERIOD_REQUIRED = {"PERIOD_CERTAIN", "LIFE_WITH_PERIOD_CERTAIN"}

OPTION_MULT = {
    "LIFE_ONLY": 100,
    "PERIOD_CERTAIN": 92,
    "LIFE_WITH_PERIOD_CERTAIN": 88,
    "JOINT_LIFE": 84,
}
PERIOD_CERTAIN_HAIRCUT = {10: 100, 15: 96, 20: 92}


def serialize(a):
    return {
        "id": a["id"],
        "contract_id": a["contract_id"],
        "payout_option": a["payout_option"],
        "period_certain_years": a["period_certain_years"],
        "annuitization_value_cents": a["annuitization_value_cents"],
        "monthly_benefit_cents": a["monthly_benefit_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _age_factor(age):
    if age < 60:
        return 480
    if age < 70:
        return 540
    if age < 80:
        return 640
    return 820


@bp.post("/annuitizations")
def create_annuitization():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    payout_option = v.require_enum(body, "payout_option", PAYOUT_OPTIONS)
    period_years = v.require_int(
        body, "period_certain_years", minimum=1, required=False, default=None
    )

    contract = lookups.ref_contract(contract_id)

    # Frozen contract rejects new annuitization creation. A frozen contract is
    # in DEATH_CLAIM status (not ACTIVE), so the freeze must be reported as
    # ERR_CONTRACT_FROZEN before the bare ACTIVE-state check (PRD §3.9).
    if contract_svc.is_frozen(contract):
        raise errors.ApiError(
            errors.ERR_CONTRACT_FROZEN, 409, "Contract is frozen by an open death claim."
        )

    # State: contract must be ACTIVE to elect annuitization (before the
    # payout-option arity business rule).
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")

    # Arity rule for period_certain_years (priority 14).
    if payout_option in PERIOD_REQUIRED:
        if period_years is None:
            raise errors.ApiError(
                errors.ERR_PAYOUT_OPTION_ARITY,
                422,
                "period_certain_years is required for this payout option.",
            )
    else:
        if period_years is not None:
            raise errors.ApiError(
                errors.ERR_PAYOUT_OPTION_ARITY,
                422,
                "period_certain_years must be absent for this payout option.",
            )

    now = store.clock.now()
    aid = store.new_id()
    annuitization = {
        "id": aid,
        "contract_id": contract_id,
        "payout_option": payout_option,
        "period_certain_years": period_years,
        "annuitization_value_cents": None,
        "monthly_benefit_cents": None,
        "status": "ELECTED",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.annuitizations[aid] = annuitization
    return object_response(serialize(annuitization), 201, now)


@bp.get("/annuitizations/<rid>")
def get_annuitization(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    annuitization = lookups.path_annuitization(rid)
    return object_response(serialize(annuitization), 200, store.clock.now())


@bp.post("/annuitizations/<rid>/begin-payout")
def begin_payout(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    annuitization = lookups.path_annuitization(rid)
    contract = store.contracts[annuitization["contract_id"]]

    if annuitization["status"] != "ELECTED":
        raise errors.invalid_state("Annuitization is not ELECTED.")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")

    acc = contract_svc.accumulation_value_cents(contract)
    if acc <= 0:
        raise errors.invalid_state("Contract accumulation value must be greater than 0.")

    # Monthly benefit calculation.
    age_factor = _age_factor(contract["annuitant_age"])
    option_mult = OPTION_MULT[annuitization["payout_option"]]
    base = Decimal(acc) / Decimal(100000) * Decimal(age_factor)
    monthly = base * Decimal(option_mult) / Decimal(100)
    if annuitization["payout_option"] in PERIOD_REQUIRED:
        haircut = PERIOD_CERTAIN_HAIRCUT.get(annuitization["period_certain_years"], 100)
        monthly = monthly * Decimal(haircut) / Decimal(100)
    monthly_cents = round_half_up_decimal(monthly)

    now = store.clock.now()
    annuitization["annuitization_value_cents"] = acc
    annuitization["monthly_benefit_cents"] = monthly_cents
    annuitization["status"] = "ACTIVE_PAYOUT"
    annuitization["version"] += 1
    annuitization["updated_at"] = iso8601(now)

    # Cascade ACTIVE -> ANNUITIZED.
    contract["status"] = "ANNUITIZED"
    contract_svc.liquidate_allocations(contract)
    contract_svc.bump(contract)

    return object_response(serialize(annuitization), 200, now)


@bp.post("/annuitizations/<rid>/decline")
def decline_annuitization(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    annuitization = lookups.path_annuitization(rid)
    if annuitization["status"] != "ELECTED":
        raise errors.invalid_state("Annuitization is not ELECTED.")
    now = store.clock.now()
    annuitization["status"] = "DECLINED"
    annuitization["version"] += 1
    annuitization["updated_at"] = iso8601(now)
    return object_response(serialize(annuitization), 200, now)
