"""DeathClaim endpoints (PRD §3.9).

Fork-join: verify-identity (FILED->VERIFYING) and value-benefit
(VERIFYING->VALUED) must both complete, plus ACTIVE beneficiary shares sum to
10000, before fund (VALUED->FUNDED). Filing freezes the contract; deny
un-freezes it.
"""

from decimal import Decimal

from flask import Blueprint

import errors
import validation as v
from clock import iso8601, parse_iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import contract as contract_svc
from services import lookups
from services.money import floor_div

bp = Blueprint("death_claims", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def serialize(d):
    return {
        "id": d["id"],
        "contract_id": d["contract_id"],
        "date_of_death": d["date_of_death"],
        "identity_verified": d["identity_verified"],
        "benefit_valued": d["benefit_valued"],
        "death_benefit_cents": d["death_benefit_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/death-claims")
def file_death_claim():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    dod_raw = v.require_string(body, "date_of_death")
    dod = parse_iso8601(dod_raw)
    if dod is None:
        raise errors.invalid_request("date_of_death must be an ISO 8601 timestamp.")

    contract = lookups.ref_contract(contract_id)

    # State: contract must be ACTIVE; only one open/funded claim allowed.
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")
    if contract_svc.has_open_or_funded_claim(contract):
        raise errors.invalid_state("Contract already has an open or funded death claim.")

    # Temporal: date of death must not be in the future.
    if dod > store.clock.now():
        raise errors.ApiError(
            errors.ERR_FUTURE_DATE_OF_DEATH, 422, "date_of_death is in the future."
        )

    now = store.clock.now()
    did = store.new_id()
    claim = {
        "id": did,
        "contract_id": contract_id,
        "date_of_death": dod_raw,
        "identity_verified": False,
        "benefit_valued": False,
        "death_benefit_cents": None,
        "status": "FILED",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.death_claims[did] = claim

    # Cascade ACTIVE -> DEATH_CLAIM (freeze).
    contract["status"] = "DEATH_CLAIM"
    contract_svc.bump(contract)

    return object_response(serialize(claim), 201, now)


@bp.get("/death-claims/<rid>")
def get_death_claim(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    claim = lookups.path_death_claim(rid)
    return object_response(serialize(claim), 200, store.clock.now())


@bp.post("/death-claims/<rid>/verify-identity")
def verify_identity(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    claim = lookups.path_death_claim(rid)
    if claim["status"] != "FILED":
        raise errors.invalid_state("Death claim is not FILED.")
    now = store.clock.now()
    claim["identity_verified"] = True
    claim["status"] = "VERIFYING"
    claim["version"] += 1
    claim["updated_at"] = iso8601(now)
    return object_response(serialize(claim), 200, now)


@bp.post("/death-claims/<rid>/value-benefit")
def value_benefit(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    claim = lookups.path_death_claim(rid)
    if claim["status"] != "VERIFYING":
        raise errors.invalid_state("Death claim is not VERIFYING.")

    contract = store.contracts[claim["contract_id"]]
    product = store.products[contract["product_id"]]
    acc = contract_svc.accumulation_value_cents(contract)
    cum = contract_svc.cumulative_premium_cents(contract)
    hav = contract["highest_anniversary_value_cents"]

    dbt = product["death_benefit_type"]
    if dbt == "RETURN_OF_PREMIUM":
        benefit = max(cum, acc)
    elif dbt == "ACCOUNT_VALUE":
        benefit = acc
    else:  # HIGHEST_ANNIVERSARY
        benefit = max(hav, acc)

    now = store.clock.now()
    claim["benefit_valued"] = True
    claim["death_benefit_cents"] = benefit
    claim["status"] = "VALUED"
    claim["version"] += 1
    claim["updated_at"] = iso8601(now)
    return object_response(serialize(claim), 200, now)


@bp.post("/death-claims/<rid>/fund")
def fund(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    claim = lookups.path_death_claim(rid)
    if claim["status"] != "VALUED":
        raise errors.invalid_state("Death claim is not VALUED.")
    if not (claim["identity_verified"] and claim["benefit_valued"]):
        raise errors.invalid_state("Both fork branches must be complete to fund.")

    contract = store.contracts[claim["contract_id"]]

    # ACTIVE beneficiary shares must sum to exactly 10000.
    active_benefs = [
        b
        for b in store.beneficiaries.values()
        if b["contract_id"] == contract["id"] and b["status"] == "ACTIVE"
    ]
    if sum(b["share_bps"] for b in active_benefs) != 10000:
        raise errors.ApiError(
            errors.ERR_BENEFICIARY_SHARES_INCOMPLETE,
            409,
            "ACTIVE beneficiary shares do not sum to 10000.",
        )

    now = store.clock.now()
    total = claim["death_benefit_cents"]

    # Waterfall distribution: floor each share, remainder to earliest-created.
    ordered = lookups.sorted_by_creation(active_benefs)
    assigned = 0
    for b in ordered:
        b["payout_cents"] = floor_div(total * b["share_bps"], 10000)
        assigned += b["payout_cents"]
    remainder = total - assigned
    if ordered:
        ordered[0]["payout_cents"] += remainder
    for b in ordered:
        b["version"] += 1
        b["updated_at"] = iso8601(now)

    claim["status"] = "FUNDED"
    claim["version"] += 1
    claim["updated_at"] = iso8601(now)

    # Cascade DEATH_CLAIM -> TERMINATED.
    contract["status"] = "TERMINATED"
    contract_svc.bump(contract)

    return object_response(serialize(claim), 200, now)


@bp.post("/death-claims/<rid>/deny")
def deny(rid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    claim = lookups.path_death_claim(rid)
    if claim["status"] not in ("FILED", "VERIFYING", "VALUED"):
        raise errors.invalid_state("Death claim cannot be denied from its current state.")

    contract = store.contracts[claim["contract_id"]]
    now = store.clock.now()
    claim["status"] = "DENIED"
    claim["version"] += 1
    claim["updated_at"] = iso8601(now)

    # Cascade DEATH_CLAIM -> ACTIVE (un-freeze).
    contract["status"] = "ACTIVE"
    contract_svc.bump(contract)

    return object_response(serialize(claim), 200, now)
