"""Composite fixtures: multi-step state built exclusively through the API.

The harness restarts the server and empties the database before every test, so
every fixture here builds its world from scratch using declared endpoints only.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ANALYST_HEADERS,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    MANAGER_USER_ID_ALT,
    OPERATOR_USER_ID,
    PLATFORM_ADMIN_HEADERS,
    make_headers,
    make_royalty_owner_headers,
)
from .constants import ROLE_ACQUISITION_MANAGER, ROLE_DIVISION_ORDER_ADMIN, ROLE_OPERATOR


# ------------------------------------------------------------------- clock
def set_clock(api: ApiClient, current_utc: str) -> dict:
    """Move the logical clock as the PlatformAdmin."""
    response = api.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS)
    return validate_success(response, 200)


# ------------------------------------------------------------------ tracts
def create_tract(api: ApiClient, headers: dict = ANALYST_HEADERS, **overrides) -> dict:
    response = api.create_tract(f.tract_payload(**overrides), headers)
    return validate_success(response, 201)


def add_chain_entry(api: ApiClient, tract_id: str, payload: dict, headers: dict = ANALYST_HEADERS) -> dict:
    response = api.create_title_chain_entry(tract_id, payload, headers)
    return validate_success(response, 201)


def add_canonical_chain(api: ApiClient, tract_id: str) -> List[dict]:
    """PATENT 1.0, DEED 480.0000, PROBATE 0.5, ASSIGNMENT 0.0625 on a 640-acre
    tract: net_mineral_acres_certified 80.0000, existing_burden_fraction 0.0625."""
    return [
        add_chain_entry(api, tract_id, f.patent_entry_payload()),
        add_chain_entry(api, tract_id, f.deed_entry_payload()),
        add_chain_entry(api, tract_id, f.probate_entry_payload()),
        add_chain_entry(api, tract_id, f.assignment_entry_payload()),
    ]


def certify_tract(api: ApiClient, tract_id: str, headers: dict = ANALYST_HEADERS) -> dict:
    response = api.certify_title(tract_id, headers)
    return validate_success(response, 200)


def create_certified_tract(api: ApiClient, **overrides) -> dict:
    """A CERTIFIED tract carrying the canonical chain."""
    tract = create_tract(api, **overrides)
    add_canonical_chain(api, tract["id"])
    return certify_tract(api, tract["id"])


# ---------------------------------------------------------- royalty owners
def create_owner(api: ApiClient, **overrides) -> dict:
    response = api.create_royalty_owner(f.royalty_owner_payload(**overrides), ADMIN_HEADERS)
    return validate_success(response, 201)


def patch_owner(api: ApiClient, owner_id: str, payload: dict, user_id: str = ADMIN_USER_ID) -> dict:
    response = api.update_royalty_owner(
        owner_id, payload, make_headers(user_id, ROLE_DIVISION_ORDER_ADMIN)
    )
    return validate_success(response, 200)


# -------------------------------------------------------- mineral interests
def create_interest(api: ApiClient, tract_id: str, owner_id: str, **overrides) -> dict:
    response = api.create_mineral_interest(
        f.mineral_interest_payload(tract_id, owner_id, **overrides), MANAGER_HEADERS
    )
    return validate_success(response, 201)


def read_interest(api: ApiClient, interest_id: str) -> dict:
    return validate_success(api.get_mineral_interest(interest_id, MANAGER_HEADERS), 200)


def interest_version(api: ApiClient, interest_id: str) -> int:
    return read_interest(api, interest_id)["version"]


# ------------------------------------------------------------- valuations
def create_valuation(
    api: ApiClient, interest_id: str, user_id: str = MANAGER_USER_ID, **overrides
) -> dict:
    response = api.create_valuation(
        interest_id,
        f.valuation_payload(**overrides),
        make_headers(user_id, ROLE_ACQUISITION_MANAGER),
    )
    return validate_success(response, 201)


# ----------------------------------------------------------- offer letters
def create_offer(
    api: ApiClient, interest_id: str, user_id: str = MANAGER_USER_ID_ALT, **overrides
) -> dict:
    response = api.create_offer_letter(
        interest_id,
        f.offer_letter_payload(**overrides),
        make_headers(user_id, ROLE_ACQUISITION_MANAGER),
    )
    return validate_success(response, 201)


def accept_offer(api: ApiClient, offer_id: str, owner_id: str) -> dict:
    response = api.accept_offer_letter(offer_id, make_royalty_owner_headers(owner_id))
    return validate_success(response, 200)


def read_offer(api: ApiClient, offer_id: str) -> dict:
    return validate_success(api.get_offer_letter(offer_id, MANAGER_HEADERS), 200)


# -------------------------------------------------------------------- psas
def create_psa(
    api: ApiClient,
    interest_id: str,
    offer_id: str,
    user_id: str = MANAGER_USER_ID_ALT,
    **overrides,
) -> dict:
    version = interest_version(api, interest_id)
    response = api.create_psa(
        f.psa_payload(offer_id, version, **overrides),
        make_headers(user_id, ROLE_ACQUISITION_MANAGER),
    )
    return validate_success(response, 201)


def read_psa(api: ApiClient, psa_id: str) -> dict:
    return validate_success(api.get_psa(psa_id, MANAGER_HEADERS), 200)


def raise_defect(api: ApiClient, psa_id: str, **overrides) -> dict:
    response = api.create_title_defect(psa_id, f.title_defect_payload(**overrides), ANALYST_HEADERS)
    return validate_success(response, 201)


def close_curative(api: ApiClient, psa_id: str, user_id: str = MANAGER_USER_ID_ALT) -> dict:
    response = api.close_curative(psa_id, make_headers(user_id, ROLE_ACQUISITION_MANAGER))
    return validate_success(response, 200)


def fund_psa(api: ApiClient, psa_id: str, user_id: str = MANAGER_USER_ID_ALT, **overrides) -> dict:
    response = api.fund_psa(
        psa_id, f.fund_payload(**overrides), make_headers(user_id, ROLE_ACQUISITION_MANAGER)
    )
    return validate_success(response, 200)


def record_deed(api: ApiClient, psa_id: str, **overrides) -> dict:
    response = api.record_deed(psa_id, f.record_deed_payload(**overrides), ANALYST_HEADERS)
    return validate_success(response, 200)


def read_defect(api: ApiClient, defect_id: str) -> dict:
    return validate_success(api.get_title_defect(defect_id, ANALYST_HEADERS), 200)


# ------------------------------------------------------------------- units
def create_unit(api: ApiClient, user_id: str = OPERATOR_USER_ID, **overrides) -> dict:
    response = api.create_unit(
        f.unit_payload(**overrides), make_headers(user_id, ROLE_OPERATOR)
    )
    return validate_success(response, 201)


def read_unit(api: ApiClient, unit_id: str) -> dict:
    return validate_success(api.get_unit(unit_id, ADMIN_HEADERS), 200)


def unit_version(api: ApiClient, unit_id: str) -> int:
    return read_unit(api, unit_id)["version"]


def create_allocation(
    api: ApiClient, unit_id: str, tract_id: str, user_id: str = OPERATOR_USER_ID, **overrides
) -> dict:
    response = api.create_allocation(
        f.allocation_payload(unit_id, tract_id, **overrides),
        make_headers(user_id, ROLE_OPERATOR),
    )
    return validate_success(response, 201)


def read_allocation(api: ApiClient, allocation_id: str) -> dict:
    return validate_success(api.get_allocation(allocation_id, ADMIN_HEADERS), 200)


def pugh_release(api: ApiClient, allocation_id: str, user_id: str = OPERATOR_USER_ID) -> dict:
    response = api.pugh_release(allocation_id, make_headers(user_id, ROLE_OPERATOR))
    return validate_success(response, 200)


def terminate_allocation(
    api: ApiClient, allocation_id: str, user_id: str = OPERATOR_USER_ID, **overrides
) -> dict:
    response = api.terminate_allocation(
        allocation_id,
        f.terminate_allocation_payload(**overrides),
        make_headers(user_id, ROLE_OPERATOR),
    )
    return validate_success(response, 200)


# ---------------------------------------------------------- division orders
def create_division_order(
    api: ApiClient, interest_id: str, unit_id: str, user_id: str = ADMIN_USER_ID, **overrides
) -> dict:
    version = unit_version(api, unit_id)
    response = api.create_division_order(
        f.division_order_payload(interest_id, unit_id, version, **overrides),
        make_headers(user_id, ROLE_DIVISION_ORDER_ADMIN),
    )
    return validate_success(response, 201)


def read_division_order(api: ApiClient, order_id: str) -> dict:
    return validate_success(api.get_division_order(order_id, ADMIN_HEADERS), 200)


def send_operator_response(
    api: ApiClient, order_id: str, user_id: str = OPERATOR_USER_ID, **overrides
) -> dict:
    response = api.operator_response(
        order_id, f.operator_response_payload(**overrides), make_headers(user_id, ROLE_OPERATOR)
    )
    return validate_success(response, 200)


def report_revenue(
    api: ApiClient, order_id: str, user_id: str = OPERATOR_USER_ID, **overrides
) -> dict:
    response = api.create_revenue_check_detail(
        order_id,
        f.revenue_check_detail_payload(**overrides),
        make_headers(user_id, ROLE_OPERATOR),
    )
    return validate_success(response, 201)


def read_revenue_detail(api: ApiClient, detail_id: str) -> dict:
    return validate_success(api.get_revenue_check_detail(detail_id, ADMIN_HEADERS), 200)


# ------------------------------------------------------- suspense accounts
def list_suspense_for_order(api: ApiClient, order_id: str) -> List[dict]:
    response = api.list_suspense_accounts(ADMIN_HEADERS, {"division_order_id": order_id})
    accounts, _meta = validate_paginated(response)
    return accounts


def suspense_for_order(api: ApiClient, order_id: str) -> dict:
    accounts = list_suspense_for_order(api, order_id)
    assert len(accounts) == 1, (
        f"expected exactly one suspense account for order {order_id}, got {len(accounts)}"
    )
    return accounts[0]


def read_suspense(api: ApiClient, suspense_id: str) -> dict:
    return validate_success(api.get_suspense_account(suspense_id, ADMIN_HEADERS), 200)


# =========================================================================
# Composite scenarios. Each returns a dict of the entities it created, so a
# test can reach any hop of the chain without re-reading it.
# =========================================================================
def valuation_ready(
    api: ApiClient,
    tract_overrides: Optional[Dict[str, Any]] = None,
    interest_overrides: Optional[Dict[str, Any]] = None,
    valuation_overrides: Optional[Dict[str, Any]] = None,
    valuation_user_id: str = MANAGER_USER_ID,
) -> Dict[str, Any]:
    """CERTIFIED tract, registered owner, PROSPECT interest, CURRENT valuation.

    With the canonical literals: net_mineral_acres 40.0000, bid_floor 37115.34,
    max_bid 55340.34.
    """
    tract = create_certified_tract(api, **(tract_overrides or {}))
    owner = create_owner(api)
    interest = create_interest(api, tract["id"], owner["id"], **(interest_overrides or {}))
    valuation = create_valuation(
        api, interest["id"], user_id=valuation_user_id, **(valuation_overrides or {})
    )
    return {
        "tract": tract,
        "owner": owner,
        "interest": interest,
        "valuation": valuation,
    }


def offer_ready(
    api: ApiClient,
    offer_overrides: Optional[Dict[str, Any]] = None,
    offer_user_id: str = MANAGER_USER_ID_ALT,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """valuation_ready plus a SENT offer letter; the interest reads OFFERED."""
    world = valuation_ready(api, **scenario_kwargs)
    world["offer"] = create_offer(
        api, world["interest"]["id"], user_id=offer_user_id, **(offer_overrides or {})
    )
    return world


def accepted_offer_ready(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """offer_ready plus the owner's acceptance; the letter reads ACCEPTED."""
    world = offer_ready(api, **kwargs)
    world["offer"] = accept_offer(api, world["offer"]["id"], world["owner"]["id"])
    return world


def psa_ready(
    api: ApiClient,
    psa_overrides: Optional[Dict[str, Any]] = None,
    psa_user_id: str = MANAGER_USER_ID_ALT,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """An EXECUTED / CURATIVE_OPEN / UNFUNDED agreement on an accepted offer."""
    world = accepted_offer_ready(api, **scenario_kwargs)
    world["psa"] = create_psa(
        api,
        world["interest"]["id"],
        world["offer"]["id"],
        user_id=psa_user_id,
        **(psa_overrides or {}),
    )
    return world


def psa_with_defects_ready(
    api: ApiClient, defect_specs: List[Dict[str, Any]], **scenario_kwargs
) -> Dict[str, Any]:
    """An EXECUTED agreement carrying one RAISED defect per spec, in order."""
    world = psa_ready(api, **scenario_kwargs)
    world["defects"] = [
        raise_defect(api, world["psa"]["id"], **spec) for spec in defect_specs
    ]
    return world


def unit_with_allocation_ready(
    api: ApiClient,
    tract_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    allocation_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CERTIFIED tract and a Unit holding one ACTIVE allocation of it."""
    tract = create_certified_tract(api, **(tract_overrides or {}))
    unit = create_unit(api, **(unit_overrides or {}))
    allocation = create_allocation(
        api, unit["id"], tract["id"], **(allocation_overrides or {})
    )
    return {"tract": tract, "unit": unit, "allocation": allocation}


def division_order_ready(
    api: ApiClient,
    tract_overrides: Optional[Dict[str, Any]] = None,
    interest_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    allocation_overrides: Optional[Dict[str, Any]] = None,
    owner_overrides: Optional[Dict[str, Any]] = None,
    order_user_id: str = ADMIN_USER_ID,
) -> Dict[str, Any]:
    """A SENT DivisionOrder over the canonical tract / interest / unit / allocation.

    With the canonical literals expected_decimal reads 0.00195313.
    """
    tract = create_certified_tract(api, **(tract_overrides or {}))
    owner = create_owner(api, **(owner_overrides or {}))
    interest = create_interest(api, tract["id"], owner["id"], **(interest_overrides or {}))
    unit = create_unit(api, **(unit_overrides or {}))
    allocation = create_allocation(
        api, unit["id"], tract["id"], **(allocation_overrides or {})
    )
    order = create_division_order(api, interest["id"], unit["id"], user_id=order_user_id)
    return {
        "tract": tract,
        "owner": owner,
        "interest": interest,
        "unit": unit,
        "allocation": allocation,
        "order": order,
    }


def executed_division_order_ready(
    api: ApiClient,
    response_overrides: Optional[Dict[str, Any]] = None,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """division_order_ready plus an agreeing operator response: EXECUTED with a
    pinned_decimal of 0.00195313 and effective_production_month 2026-06."""
    world = division_order_ready(api, **scenario_kwargs)
    world["order"] = send_operator_response(
        api, world["order"]["id"], **(response_overrides or {})
    )
    return world


def variance_held_ready(
    api: ApiClient,
    detail_overrides: Optional[Dict[str, Any]] = None,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """An EXECUTED order pushed to SUSPENDED by one variance-held revenue line,
    together with the ACCRUING SuspenseAccount that line opened."""
    world = executed_division_order_ready(api, **scenario_kwargs)
    world["detail"] = report_revenue(
        api, world["order"]["id"], **(detail_overrides or {})
    )
    world["suspense"] = suspense_for_order(api, world["order"]["id"])
    return world
