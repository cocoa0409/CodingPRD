"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server). Lenient get_success_data
is used internally so setup failures surface as clear "Setup failed" errors.

CustomerRep calls that are ownership-gated (accept / reject / payment) always
thread the acting customer's id through make_customer_rep_headers (PRD §2.1).
"""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_customer_payload,
    create_machine_payload,
    create_material_grade_payload,
    create_outside_vendor_payload,
    create_quote_payload,
    create_sheet_stock_payload,
)
from .test_users import TEST_USERS, make_customer_rep_headers, make_operator_headers

MGR = TEST_USERS["shop_manager_headers"]
EST = TEST_USERS["estimator_headers"]
PLAN = TEST_USERS["planner_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]

TEST_CREDIT_LIMIT = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"]

# Pinned pricing-fixture geometry (PRD §3.3 worked inputs):
# 300x200 mm, 5 holes d20, 2 fillets, 4 bends, tier index 0, hardness 1.0,
# base rate 2.0 -> billed 77s, cut 154c, bend_units 8 -> 1200c, material 35c,
# setup 900c -> line_base 2289c per part (STANDARD, before any discount).
PINNED_LINE = {
    "thickness_mm": 1.0,
    "bbox_width_mm": 300,
    "bbox_height_mm": 200,
    "hole_count": 5,
    "hole_diameter_mm": 20,
    "corner_fillet_count": 2,
    "bend_count": 4,
    "weld_inches": 0,
    "finish": "NONE",
}
PINNED_TIERS_2 = [
    {"max_thickness_mm": 1.0, "tier_index": 0},
    {"max_thickness_mm": 2.0, "tier_index": 1},
]
PINNED_TIERS_3 = [
    {"max_thickness_mm": 1.0, "tier_index": 0},
    {"max_thickness_mm": 2.0, "tier_index": 1},
    {"max_thickness_mm": 3.2, "tier_index": 2},
]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_grade(tiers=None, **overrides) -> dict:
    payload = create_material_grade_payload(**overrides)
    if tiers is not None:
        payload["thickness_tiers"] = tiers
    return get_success_data(api_client.create_material_grade(payload, MGR))


def create_customer(credit_limit_cents: int = TEST_CREDIT_LIMIT, **overrides) -> dict:
    payload = create_customer_payload(credit_limit_cents=credit_limit_cents, **overrides)
    return get_success_data(api_client.create_customer(payload, MGR))


def create_machine(station: str = "LASER", **overrides) -> dict:
    return get_success_data(
        api_client.create_machine(create_machine_payload(station, **overrides), MGR)
    )


def create_vendor(process: str = "PLATING", **overrides) -> dict:
    return get_success_data(
        api_client.create_outside_vendor(
            create_outside_vendor_payload(process, **overrides), MGR,
        )
    )


def create_full_sheet(grade_id: str, thickness_mm: float = 1.0, **overrides) -> dict:
    payload = create_sheet_stock_payload(grade_id, thickness_mm=thickness_mm, **overrides)
    return get_success_data(api_client.create_sheet_stock(payload, CLERK))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, MGR))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, MGR))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, PLAN))


# ---------------------------------------------------------------------------
# Quote lifecycle
# ---------------------------------------------------------------------------

def create_draft_quote(customer_id: str, grade_id: str, line_overrides=None,
                       expedite_tier: str = "STANDARD", qty: int = 1) -> dict:
    line = dict(PINNED_LINE)
    line.update(line_overrides or {})
    line["grade_id"] = grade_id
    line["qty"] = qty
    payload = create_quote_payload(
        customer_id, lines=[line], expedite_tier=expedite_tier,
    )
    return get_success_data(api_client.create_quote(payload, EST))


def price_quote(quote_id: str, expected_version: int) -> dict:
    return get_success_data(api_client.price_quote(quote_id, expected_version, EST))


def submit_quote(quote_id: str) -> dict:
    return get_success_data(api_client.submit_quote(quote_id, EST))


def create_priced_quote(customer_id: str, grade_id: str, line_overrides=None,
                        expedite_tier: str = "STANDARD", qty: int = 1) -> dict:
    """DRAFT quote -> PRICED."""
    quote = create_draft_quote(customer_id, grade_id, line_overrides,
                               expedite_tier, qty)
    return price_quote(quote["id"], quote["version"])


def create_submitted_quote(customer_id: str, grade_id: str, line_overrides=None,
                           expedite_tier: str = "STANDARD", qty: int = 1) -> dict:
    """DRAFT -> PRICED -> SUBMITTED."""
    priced = create_priced_quote(customer_id, grade_id, line_overrides,
                                 expedite_tier, qty)
    return submit_quote(priced["id"])


def rep_headers(customer: dict) -> dict:
    return make_customer_rep_headers(customer["id"])


# ---------------------------------------------------------------------------
# Accept cascade + production walking
# ---------------------------------------------------------------------------

def accept_quote(quote_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.accept_quote(quote_id, make_customer_rep_headers(customer_id))
    )


def create_accepted_order(customer: dict, grade_id: str, line_overrides=None,
                          expedite_tier: str = "STANDARD", qty: int = 1) -> dict:
    """SUBMITTED quote -> accept. Returns the FabricationOrder."""
    submitted = create_submitted_quote(customer["id"], grade_id, line_overrides,
                                       expedite_tier, qty)
    return accept_quote(submitted["id"], customer["id"])


def release_order(order_id: str) -> dict:
    return get_success_data(api_client.release_order(order_id, PLAN))


def get_order_steps(order_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_order_routing_steps(order_id, PLAN))
    return sorted(data, key=lambda s: s["seq"])


def get_order_lines(quote_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_quote_lines(quote_id, EST))
    return data


def get_step_by_station(steps: list, station: str) -> dict:
    matches = [s for s in steps if s["station"] == station]
    assert matches, f"Setup failed: no routing step with station {station}"
    return matches[0]


def complete_step(step_id: str, operator_id: str = "op-default") -> dict:
    return get_success_data(
        api_client.complete_routing_step(step_id, make_operator_headers(operator_id))
    )


def complete_inhouse_steps(order_id: str, operator_id: str = "op-default") -> list:
    """Complete every in-house IN_PROGRESS step in seq order (serial advance).

    Stops when no in-house IN_PROGRESS step remains (order may have moved to
    AWAITING_OUTSIDE or INSPECTION). Returns the final step listing.
    """
    for _ in range(16):
        steps = get_order_steps(order_id)
        current = next(
            (s for s in steps
             if s["status"] == "IN_PROGRESS" and s["station"] != "OUTSIDE_VENDOR"),
            None,
        )
        if current is None:
            return steps
        complete_step(current["id"], operator_id)
    raise AssertionError("Setup failed: routing chain did not advance")


def drive_order_to_inspection(order_id: str, operator_id: str = "op-default") -> list:
    """Complete all in-house steps of an in-house-only order until INSPECTION."""
    steps = complete_inhouse_steps(order_id, operator_id)
    order = get_order(order_id)
    assert order["status"] == "INSPECTION", (
        f"Setup failed: expected INSPECTION, got {order['status']}"
    )
    return steps


def submit_inspection(order_id: str, deviation_mm: float = 0.5,
                      diagonal_mm: int = 400, dimensional_pass: bool = True,
                      inspector_id: str = "qc-1"):
    """Raw inspection-report response (caller asserts success/failure)."""
    from .test_users import make_qc_inspector_headers
    payload = {
        "flatness_deviation_mm": deviation_mm,
        "measured_diagonal_mm": diagonal_mm,
        "dimensional_pass": dimensional_pass,
    }
    return api_client.submit_inspection_report(
        order_id, payload, make_qc_inspector_headers(inspector_id),
    )


def submit_passing_inspection(order_id: str, inspector_id: str = "qc-1",
                              deviation_mm: float = 0.5,
                              diagonal_mm: int = 400) -> dict:
    return get_success_data(
        submit_inspection(order_id, deviation_mm, diagonal_mm, True, inspector_id)
    )


def create_completed_order(customer: dict, grade_id: str, line_overrides=None,
                           expedite_tier: str = "STANDARD", qty: int = 1,
                           operator_id: str = "op-default",
                           inspector_id: str = "qc-1") -> dict:
    """Full lifecycle: accept -> release -> complete steps -> PASS inspection."""
    order = create_accepted_order(customer, grade_id, line_overrides,
                                  expedite_tier, qty)
    release_order(order["id"])
    drive_order_to_inspection(order["id"], operator_id)
    submit_passing_inspection(order["id"], inspector_id)
    return get_order(order["id"])


# ---------------------------------------------------------------------------
# Scrap credit ledger
# ---------------------------------------------------------------------------

def post_scrap_credit(customer_id: str, sheet_stock_id: str) -> dict:
    return get_success_data(
        api_client.create_scrap_credit(
            {"customer_id": customer_id, "sheet_stock_id": sheet_stock_id}, CLERK,
        )
    )


def find_remnant_for_order(order_id: str) -> Optional[dict]:
    data, _meta = validate_paginated(
        api_client.list_sheet_stock(
            CLERK, params={"source_order_id": order_id, "kind": "REMNANT"},
        )
    )
    return data[0] if data else None


def list_customer_credits(customer_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_scrap_credits(MGR, params={"customer_id": customer_id})
    )
    return data


def list_audit_events(params: dict) -> list:
    data, _meta = validate_paginated(api_client.list_audit_events(MGR, params=params))
    return data


# ---------------------------------------------------------------------------
# Composite scenario
# ---------------------------------------------------------------------------

def setup_shop(stations=("LASER",), tier_table=None, num_sheets=1,
               grade_overrides=None, vendor=None,
               credit_limit=TEST_CREDIT_LIMIT) -> dict:
    """Grade + customer + machines (+ optional vendor + full sheets)."""
    grade = create_grade(tiers=tier_table, **(grade_overrides or {}))
    customer = create_customer(credit_limit)
    machines = {st: create_machine(st) for st in stations}
    vendor_row = create_vendor(**vendor) if vendor else None
    sheets = [create_full_sheet(grade["id"]) for _ in range(num_sheets)]
    return {
        "grade": grade,
        "customer": customer,
        "machines": machines,
        "vendor": vendor_row,
        "sheets": sheets,
    }
