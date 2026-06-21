"""Premium endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response, array_response
from services import contract as contract_svc
from services import lookups
from services.money import round_half_up

bp = Blueprint("premiums", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def serialize(p):
    return {
        "id": p["id"],
        "contract_id": p["contract_id"],
        "gross_premium_cents": p["gross_premium_cents"],
        "premium_load_bps": p["premium_load_bps"],
        "net_premium_cents": p["net_premium_cents"],
        "is_initial": p["is_initial"],
        "source_exchange_id": p["source_exchange_id"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _net(gross, load_bps):
    # net = round_half_up(gross * (1 - load_bps/10000)) = round_half_up(gross*(10000-load)/10000)
    return round_half_up(gross * (10000 - load_bps), 10000)


@bp.post("/premiums")
def create_premium():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    gross = v.require_int(body, "gross_premium_cents", minimum=1)
    expected_version = v.require_int(body, "expected_contract_version")
    load_bps = v.require_int(
        body, "premium_load_bps", minimum=0, maximum=1000, required=False, default=0
    )
    source_exchange_id = v.optional_string(body, "source_exchange_id")

    contract = lookups.ref_contract(contract_id)
    if source_exchange_id is not None:
        lookups.ref_exchange(source_exchange_id)

    is_initial = not any(
        p["contract_id"] == contract_id for p in store.premiums.values()
    )

    # OCC: expected_contract_version must match the live contract version.
    if expected_version != contract["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_CONTRACT_VERSION, 412, "Stale contract version."
        )

    # Frozen contract rejects new premium creation.
    if contract_svc.is_frozen(contract):
        raise errors.ApiError(
            errors.ERR_CONTRACT_FROZEN, 409, "Contract is frozen by an open death claim."
        )

    # Business fiscal: initial premium minimum.
    if is_initial:
        product = store.products[contract["product_id"]]
        if gross < product["min_initial_premium_cents"]:
            raise errors.ApiError(
                errors.ERR_BELOW_MINIMUM_PREMIUM,
                422,
                "Initial premium is below the product minimum.",
            )

    now = store.clock.now()
    pid = store.new_id()
    premium = {
        "id": pid,
        "contract_id": contract_id,
        "gross_premium_cents": gross,
        "premium_load_bps": load_bps,
        "net_premium_cents": _net(gross, load_bps),
        "is_initial": is_initial,
        "source_exchange_id": source_exchange_id,
        "status": "SUBMITTED",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.premiums[pid] = premium

    # Submitting a premium bumps the contract version (per §1.5 side effect).
    contract_svc.bump(contract)

    return object_response(serialize(premium), 201, now)


@bp.get("/premiums")
def list_premiums():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = v.parse_pagination()
    contract_filter = request.args.get("contract_id")
    exchange_filter = request.args.get("source_exchange_id")
    status_filter = request.args.get("status")

    rows = lookups.sorted_by_creation(list(store.premiums.values()))
    if contract_filter is not None:
        rows = [p for p in rows if p["contract_id"] == contract_filter]
    if exchange_filter is not None:
        rows = [p for p in rows if p["source_exchange_id"] == exchange_filter]
    if status_filter is not None:
        rows = [p for p in rows if p["status"] == status_filter]
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [serialize(p) for p in page], total, limit, offset, store.clock.now()
    )


@bp.get("/premiums/<rid>")
def get_premium(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    premium = lookups.path_premium(rid)
    return object_response(serialize(premium), 200, store.clock.now())


@bp.post("/premiums/<rid>/clear")
def clear_premium(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    premium = lookups.path_premium(rid)
    contract = store.contracts[premium["contract_id"]]

    # State legality: premium must be SUBMITTED.
    if premium["status"] != "SUBMITTED":
        raise errors.invalid_state("Premium is not SUBMITTED.")

    # Frozen contract rejects clearing. A frozen contract is in DEATH_CLAIM
    # status, which is neither PENDING nor ACTIVE, so the freeze must be
    # reported as ERR_CONTRACT_FROZEN before the contract-state-match check
    # (PRD §3.9).
    if contract_svc.is_frozen(contract):
        raise errors.ApiError(
            errors.ERR_CONTRACT_FROZEN, 409, "Contract is frozen by an open death claim."
        )

    # Contract must be in the matching state (PENDING for initial, ACTIVE for
    # subsequent).
    if premium["is_initial"]:
        if contract["status"] != "PENDING":
            raise errors.invalid_state("Initial premium requires a PENDING contract.")
    else:
        if contract["status"] != "ACTIVE":
            raise errors.invalid_state("Subsequent premium requires an ACTIVE contract.")

    # VARIABLE allocation completeness for the initial clear.
    if premium["is_initial"]:
        product = store.products[contract["product_id"]]
        if product["contract_type"] == "VARIABLE":
            total = sum(
                a["allocation_bps"]
                for a in store.sub_account_allocations.values()
                if a["contract_id"] == contract["id"] and a["status"] == "ACTIVE"
            )
            if total != 10000:
                raise errors.ApiError(
                    errors.ERR_ALLOCATION_INCOMPLETE,
                    409,
                    "Sub-account allocations do not sum to 10000.",
                )

    now = store.clock.now()
    premium["net_premium_cents"] = _net(
        premium["gross_premium_cents"], premium["premium_load_bps"]
    )
    premium["status"] = "CLEARED"
    premium["version"] += 1
    premium["updated_at"] = iso8601(now)

    # Cascade: clearing the initial premium drives PENDING -> ACTIVE.
    if premium["is_initial"]:
        contract["status"] = "ACTIVE"
        contract["issue_date"] = iso8601(now)
        # highest_anniversary_value seeded from the new accumulation value.
        contract["highest_anniversary_value_cents"] = contract_svc.accumulation_value_cents(
            contract
        )
    contract_svc.bump(contract)

    return object_response(serialize(premium), 200, now)


@bp.post("/premiums/<rid>/reject")
def reject_premium(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    premium = lookups.path_premium(rid)
    if premium["status"] != "SUBMITTED":
        raise errors.invalid_state("Premium is not SUBMITTED.")
    now = store.clock.now()
    premium["status"] = "REJECTED"
    premium["version"] += 1
    premium["updated_at"] = iso8601(now)
    return object_response(serialize(premium), 200, now)
