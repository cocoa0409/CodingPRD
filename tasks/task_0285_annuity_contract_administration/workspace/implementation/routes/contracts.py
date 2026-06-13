"""Contract endpoints: create, list, retrieve, projection, and nested child
lists (PRD §3.2, §3.6, §2.8)."""

from flask import Blueprint, request

import errors
import validation as v
from db import store
from middleware import authenticate, authorize
from response import object_response, array_response
from services import contract as contract_svc
from services import lookups
from services.money import round_half_up_decimal
from decimal import Decimal

bp = Blueprint("contracts", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}
ASSUMED_GROWTH_BPS = 400


@bp.post("/contracts")
def create_contract():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    product_id = v.require_string(body, "product_id")
    owner_name = v.require_string(body, "owner_name")
    annuitant_age = v.require_int(body, "annuitant_age", minimum=0, maximum=85)

    product = lookups.ref_product(product_id)
    if product["status"] != "ACTIVE":
        raise errors.invalid_state("Cannot open a contract against a RETIRED product.")

    contract = contract_svc.create_contract(product_id, owner_name, annuitant_age)
    return object_response(contract_svc.serialize(contract), 201, store.clock.now())


@bp.get("/contracts")
def list_contracts():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = v.parse_pagination()
    status_filter = request.args.get("status")
    product_filter = request.args.get("product_id")

    rows = lookups.sorted_by_creation(list(store.contracts.values()))
    if status_filter is not None:
        rows = [c for c in rows if c["status"] == status_filter]
    if product_filter is not None:
        rows = [c for c in rows if c["product_id"] == product_filter]
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [contract_svc.serialize(c) for c in page], total, limit, offset, store.clock.now()
    )


@bp.get("/contracts/<rid>")
def get_contract(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    return object_response(contract_svc.serialize(contract), 200, store.clock.now())


@bp.get("/contracts/<rid>/projection")
def projection(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    include_pending = v.parse_query_bool("include_pending", default=True)

    base = contract_svc.accumulation_value_cents(contract)
    pending = 0
    if include_pending:
        pending = sum(
            p["net_premium_cents"]
            for p in store.premiums.values()
            if p["contract_id"] == contract["id"] and p["status"] == "SUBMITTED"
        )

    product = store.products[contract["product_id"]]
    schedule_len = len(product["surrender_charge_schedule"] or [])
    cy = contract_svc.contract_year(contract)
    years_remaining = max(0, schedule_len - cy)

    if product["contract_type"] == "FIXED":
        rate_bps = product["fixed_annual_rate_bps"] or 0
    else:
        rate_bps = ASSUMED_GROWTH_BPS

    projected = base + pending
    for _ in range(years_remaining):
        projected = round_half_up_decimal(
            Decimal(projected) * (Decimal(10000 + rate_bps) / Decimal(10000))
        )

    data = {
        "projected_maturity_value_cents": projected,
        "settled_base_cents": base,
        "years_projected": years_remaining,
    }
    return object_response(data, 200, store.clock.now())


# --- nested child list endpoints -------------------------------------------
def _child_list(contract, collection, serialize_fn, fk="contract_id"):
    limit, offset = v.parse_pagination()
    rows = [o for o in collection.values() if o.get(fk) == contract["id"]]
    rows = lookups.sorted_by_creation(rows)
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [serialize_fn(o) for o in page], total, limit, offset, store.clock.now()
    )


@bp.get("/contracts/<rid>/premiums")
def list_contract_premiums(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.premiums import serialize

    return _child_list(contract, store.premiums, serialize)


@bp.get("/contracts/<rid>/withdrawals")
def list_contract_withdrawals(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.withdrawals import serialize

    return _child_list(contract, store.withdrawals, serialize)


@bp.get("/contracts/<rid>/crediting-events")
def list_contract_crediting(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.crediting_events import serialize

    return _child_list(contract, store.crediting_events, serialize)


@bp.get("/contracts/<rid>/beneficiaries")
def list_contract_beneficiaries(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.beneficiaries import serialize

    return _child_list(contract, store.beneficiaries, serialize)


@bp.get("/contracts/<rid>/sub-account-allocations")
def list_contract_allocations(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.allocations import serialize

    return _child_list(contract, store.sub_account_allocations, serialize)


@bp.get("/contracts/<rid>/index-segments")
def list_contract_segments(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.index_segments import serialize

    return _child_list(contract, store.index_segments, serialize)


@bp.get("/contracts/<rid>/annuitizations")
def list_contract_annuitizations(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.annuitizations import serialize

    return _child_list(contract, store.annuitizations, serialize)


@bp.get("/contracts/<rid>/death-claims")
def list_contract_death_claims(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    contract = lookups.path_contract(rid)
    from routes.death_claims import serialize

    return _child_list(contract, store.death_claims, serialize)
