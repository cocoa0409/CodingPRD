"""Composite setup helpers for the abrasives program test suite (PRD §3).

Every fixture builds its preconditions from scratch through PRD-declared
endpoints — the server is restarted (empty database) before each test.

All fixtures use get_success_data() so a broken setup raises a clear
"Setup failed" error rather than a confusing assertion failure.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_blanket_order_payload,
    create_contract_payload,
    create_lot_payload,
    create_machine_payload,
    create_product_payload,
    create_release_payload,
    create_standard_payload,
    create_trial_payload,
    create_usage_record_payload,
    submit_results_payload,
)
from .test_users import TEST_USERS, make_ehs_officer_headers, make_program_admin_headers

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
EHS = TEST_USERS["ehs_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------


def make_product(**overrides: Any) -> Dict[str, Any]:
    """Register a product as ProgramAdmin. Returns the Product dict."""
    resp = api_client.create_product(create_product_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_machine(**overrides: Any) -> Dict[str, Any]:
    resp = api_client.create_machine(create_machine_payload(**overrides), AM)
    return get_success_data(resp)


def make_lot(product_id: str, **overrides: Any) -> Dict[str, Any]:
    resp = api_client.create_lot(
        create_lot_payload(product_id=product_id, **overrides), AM
    )
    return get_success_data(resp)


def make_standard(
    machine_id: str, product_id: str, **overrides: Any
) -> Dict[str, Any]:
    resp = api_client.create_standard(
        create_standard_payload(
            machine_id=machine_id, product_id=product_id, **overrides
        ),
        AM,
    )
    return get_success_data(resp)


def make_usage_record(
    machine_id: str, product_id: str, lot_id: str, **overrides: Any
) -> Dict[str, Any]:
    resp = api_client.create_usage_record(
        create_usage_record_payload(
            machine_id=machine_id,
            product_id=product_id,
            lot_id=lot_id,
            **overrides,
        ),
        AM,
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock; returns {current_utc, lots_expired, contracts_expired}."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: contract hierarchy (contract -> lines -> blanket order)
# ---------------------------------------------------------------------------


def make_contract(
    product_lines: Optional[List[Dict[str, Any]]] = None,
    activate: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a contract; when activate=True (default) return the ACTIVE contract."""
    resp = api_client.create_contract(
        create_contract_payload(product_lines, **overrides), AM
    )
    contract = get_success_data(resp)
    if activate:
        resp = api_client.activate_contract(contract["id"], ADMIN)
        contract = get_success_data(resp)
    return contract


def make_blanket_order(
    contract_id: str, product_id: str, confirm: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Draft a blanket order; when confirm=True (default) return the OPEN order."""
    resp = api_client.create_blanket_order(
        create_blanket_order_payload(
            contract_id=contract_id, product_id=product_id, **overrides
        ),
        AM,
    )
    order = get_success_data(resp)
    if confirm:
        resp = api_client.confirm_blanket_order(order["id"], ADMIN)
        order = get_success_data(resp)
    return order


def get_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_blanket_order(order_id, AM))


def get_release(release_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_release(release_id, AM))


def get_lot(lot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lot(lot_id, AM))


def get_standard(standard_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_standard(standard_id, AM))


def get_machine(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_machine(machine_id, AM))


def get_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: full release lifecycles
# ---------------------------------------------------------------------------


def make_release(
    order_id: str, order_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Schedule a release with the OCC version; returns the SCHEDULED release."""
    payload = create_release_payload(
        expected_blanket_order_version=order_version, **overrides
    )
    resp = api_client.create_release(order_id, payload, AM)
    return get_success_data(resp)


def make_scheduled_release_on_fresh_order(
    order: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Schedule a release against an OPEN order, reading the live version first."""
    current = get_order(order["id"])
    return make_release(order["id"], current["version"], **overrides)


def make_picked_release(
    order: Dict[str, Any], lot_qty: int = 100, qty: int = 10, **overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a lot for the order's product, schedule a release, pick it.

    Returns (picked_release, lot).
    """
    lot = make_lot(order["product_id"], qty_received=lot_qty)
    release = make_scheduled_release_on_fresh_order(order, qty=qty, **overrides)
    resp = api_client.pick_release(release["id"], AM)
    return get_success_data(resp), lot


def make_shipped_release(
    order: Dict[str, Any], lot_qty: int = 100, qty: int = 10, **overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create lot + release, pick, ship. Returns (shipped_release, lot)."""
    picked, lot = make_picked_release(order, lot_qty=lot_qty, qty=qty, **overrides)
    resp = api_client.ship_release(picked["id"], AM)
    return get_success_data(resp), lot


# ---------------------------------------------------------------------------
# Tier 4: usage / standard / trial composite setups
# ---------------------------------------------------------------------------


def make_usage_scenario(
    standard_qty_per_part: float = 0.0250,
    lot_qty: int = 5000,
    machine_overrides: Optional[Dict[str, Any]] = None,
    product_overrides: Optional[Dict[str, Any]] = None,
    standard_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Product + machine + ACTIVE covering standard + lot, ready for usage records.

    Returns {"product", "machine", "standard", "lot"}.
    """
    product = make_product(**(product_overrides or {}))
    machine = make_machine(**(machine_overrides or {}))
    std_kwargs: Dict[str, Any] = {"standard_qty_per_part": standard_qty_per_part}
    std_kwargs.update(standard_overrides or {})
    standard = make_standard(machine["id"], product["id"], **std_kwargs)
    lot = make_lot(product["id"], qty_received=lot_qty)
    return {
        "product": product,
        "machine": machine,
        "standard": standard,
        "lot": lot,
    }


def make_trial(
    machine_id: str, product_id: str, **overrides: Any
) -> Dict[str, Any]:
    resp = api_client.create_trial(
        create_trial_payload(machine_id=machine_id, product_id=product_id, **overrides),
        AM,
    )
    return get_success_data(resp)


def make_trial_in_evaluation(
    submitter_user_id: str = "ehs-1",
    parts_per_unit_media: float = 120,
    **trial_overrides: Any,
) -> Dict[str, Any]:
    """Machine + product + trial submitted to EVALUATION by submitter_user_id.

    Returns {"product", "machine", "trial"} where trial is in EVALUATION.
    """
    product = make_product()
    machine = make_machine()
    trial = make_trial(machine["id"], product["id"], **trial_overrides)
    resp = api_client.submit_trial_results(
        trial["id"],
        submit_results_payload(parts_per_unit_media=parts_per_unit_media),
        make_ehs_officer_headers(submitter_user_id),
    )
    trial = get_success_data(resp)
    return {"product": product, "machine": machine, "trial": trial}
