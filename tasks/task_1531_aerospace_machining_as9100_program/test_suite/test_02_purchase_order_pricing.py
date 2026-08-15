"""Purchase-order pricing: tier selection, surcharge, escalation, pinning (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_purchase_order,
    create_active_lta,
    create_purchase_order,
    get_lta,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = TEST_USERS["contracts_manager"]

PRICING_TIERS = [
    {"min_qty": 1, "unit_price_cents": 5000},
    {"min_qty": 100, "unit_price_cents": 4500},
    {"min_qty": 500, "unit_price_cents": 4000},
]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / po_price_tier_surcharge_escalation
# ---------------------------------------------------------------------------

def test_po_price_tier_and_special_process_surcharge(api):
    """PRD §3.2: "The applicable tier is the pricing-table element with the
    largest `min_qty` that the ordered `quantity` meets or exceeds — a quantity
    exactly equal to a tier's `min_qty` selects that tier. The unit price
    starts at that tier's `unit_price_cents`. When `requires_special_process`
    is true, the unit price is increased by a ten-percent surcharge."
    PRD §3.2: "The order's `total_cents` is then its `quantity` multiplied by
    `unit_price_cents`."

    Design: Difficulty/combinatorial_formula/po_price_tier_surcharge_escalation
    """
    lta = create_active_lta(
        pricing_tiers=PRICING_TIERS, escalation_pct_per_year=0.05, award_year=2026
    )
    # Tier-1 quantity, no surcharge, delivery in the award year (no escalation).
    po_plain = create_purchase_order(
        lta["id"], quantity=10, requires_special_process=False, delivery_year=2026
    )
    assert_purchase_order(po_plain)
    assert po_plain["unit_price_cents"] == 5000, (
        f"qty 10 selects tier min_qty 1 at 5000, got {po_plain['unit_price_cents']}"
    )
    assert po_plain["total_cents"] == 10 * 5000

    # Same quantity with the special-process surcharge: 5000 x 1.10 = 5500.
    po_surcharged = create_purchase_order(
        lta["id"], quantity=10, requires_special_process=True, delivery_year=2026
    )
    assert po_surcharged["unit_price_cents"] == 5500, (
        f"10% surcharge on 5000 must yield 5500, got "
        f"{po_surcharged['unit_price_cents']}"
    )
    assert po_surcharged["total_cents"] == 10 * 5500


def test_po_price_surcharge_with_annual_escalation(api):
    """PRD §3.2: "The result is then escalated by annual compounding: it is
    multiplied by one plus `escalation_pct_per_year`, raised to the power of
    `delivery_year` minus `award_year`. This final figure is rounded half up
    exactly once to integer cents and stored as `unit_price_cents`;
    intermediate values are never rounded."

    Design: Difficulty/combinatorial_formula/po_price_tier_surcharge_escalation
    """
    lta = create_active_lta(
        pricing_tiers=PRICING_TIERS, escalation_pct_per_year=0.05, award_year=2026
    )
    # 5000 x 1.10 (surcharge) x 1.05^1 (one year of escalation) = 5775.0
    po = create_purchase_order(
        lta["id"], quantity=10, requires_special_process=True, delivery_year=2027
    )
    assert po["unit_price_cents"] == 5775, (
        f"5000 x 1.10 x 1.05 must round half up once to 5775, got "
        f"{po['unit_price_cents']}"
    )
    assert po["total_cents"] == 10 * 5775


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / po_tier_boundary_qty_equals_min
# ---------------------------------------------------------------------------

def test_po_tier_boundary_below_breakpoint(api):
    """PRD §3.2: "The applicable tier is the pricing-table element with the
    largest `min_qty` that the ordered `quantity` meets or exceeds — a quantity
    exactly equal to a tier's `min_qty` selects that tier."

    Design: Difficulty/boundary_precision_check/po_tier_boundary_qty_equals_min
    """
    lta = create_active_lta(
        pricing_tiers=PRICING_TIERS, escalation_pct_per_year=0.0, award_year=2026
    )
    po = create_purchase_order(lta["id"], quantity=99, delivery_year=2026)
    assert po["unit_price_cents"] == 5000, (
        f"qty 99 is below the min_qty 100 breakpoint and stays at 5000, got "
        f"{po['unit_price_cents']}"
    )
    assert po["total_cents"] == 99 * 5000


def test_po_tier_boundary_qty_equals_min_selects_tier(api):
    """PRD §3.2: "The applicable tier is the pricing-table element with the
    largest `min_qty` that the ordered `quantity` meets or exceeds — a quantity
    exactly equal to a tier's `min_qty` selects that tier."

    Design: Difficulty/boundary_precision_check/po_tier_boundary_qty_equals_min
    """
    lta = create_active_lta(
        pricing_tiers=PRICING_TIERS, escalation_pct_per_year=0.0, award_year=2026
    )
    po = create_purchase_order(lta["id"], quantity=100, delivery_year=2026)
    assert po["unit_price_cents"] == 4500, (
        f"qty 100 == min_qty 100 selects the 4500 tier, got "
        f"{po['unit_price_cents']}"
    )
    assert po["total_cents"] == 100 * 4500


# ---------------------------------------------------------------------------
# Corner: entities / po_creation_computed_and_pinned_fields
# ---------------------------------------------------------------------------

def test_po_creation_computed_and_pinned_fields(api):
    """PRD §3.2: "A new order starts in `RECEIVED` with `unreleased_quantity`
    equal to `quantity` and `delivered_quantity` at zero."
    PRD §3.2: "The agreement version observed at creation is recorded as
    `lta_version_pinned`, and later amendments never reprice the order — two
    orders for identical quantities placed before and after an amendment can
    legitimately carry different unit prices."

    Design: Corner/entities/po_creation_computed_and_pinned_fields
    """
    lta = create_active_lta(
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.05,
        award_year=2026,
    )
    po = create_purchase_order(lta["id"], quantity=10, delivery_year=2026)
    assert_purchase_order(po)
    assert po["unit_price_cents"] == 5000
    assert po["total_cents"] == 50000
    assert po["unreleased_quantity"] == 10
    assert po["delivered_quantity"] == 0
    assert po["status"] == "RECEIVED"
    assert po["lta_version_pinned"] == lta["version"], (
        f"lta_version_pinned {po['lta_version_pinned']} must record the "
        f"agreement version {lta['version']} observed at creation"
    )


# ---------------------------------------------------------------------------
# Corner: entities / po_get_not_found_returns_404
# ---------------------------------------------------------------------------

def test_po_get_not_found_returns_404(api):
    """PRD §2.6: "Each resource family has its own 404 error:
    `ERR_LTA_NOT_FOUND` for agreements, `ERR_PO_NOT_FOUND` for purchase orders"

    Design: Corner/entities/po_get_not_found_returns_404
    """
    resp = api_client.get_purchase_order(NON_EXISTENT_UUID, CM)
    validate_error(resp, ApiErrorId.ERR_PO_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: validations / po_number_uniqueness_rejected
# ---------------------------------------------------------------------------

def test_po_number_uniqueness_rejected(api):
    """PRD §3.2: "Per the priority order of §2.11, the stale-version check
    (`ERR_STALE_LTA_VERSION`, 412) runs before the active-agreement check —
    creating an order against an agreement that is not `ACTIVE` fails with
    `ERR_LTA_NOT_ACTIVE` — which in turn precedes the uniqueness check,
    `po_number` being unique per agreement (`ERR_PO_NUMBER_EXISTS`, 409); the
    ceiling check runs last."

    Design: Corner/validations/po_number_uniqueness_rejected
    """
    lta = create_active_lta(escalation_pct_per_year=0.0)
    create_purchase_order(lta["id"], po_number="PO-DUP", quantity=1)
    resp = api_client.create_purchase_order(
        {
            "lta_id": lta["id"],
            "po_number": "PO-DUP",
            "part_number": "P-DUP-2",
            "part_revision": "A",
            "quantity": 1,
            "flowdown_clauses": ["AS9100D_QMS"],
            "requires_special_process": False,
            "delivery_year": 2026,
            "expected_lta_version": get_lta(lta["id"])["version"],
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_PO_NUMBER_EXISTS.value)


# ---------------------------------------------------------------------------
# Corner: entities / list_pagination_envelope
# ---------------------------------------------------------------------------

def test_list_pagination_envelope(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips
    that many items from the front of the result set and defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_pagination_envelope
    """
    lta = create_active_lta(escalation_pct_per_year=0.0)
    create_purchase_order(lta["id"], quantity=1)
    create_purchase_order(lta["id"], quantity=1)
    resp = api_client.list_purchase_orders(
        CM, params={"lta_id": lta["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one PO, got {len(data)}"
    assert meta["total_count"] == 2, f"two POs exist, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / lta_ceiling_exceeded_402
# ---------------------------------------------------------------------------

def test_lta_ceiling_exceeded_402(api):
    """PRD §3.2: "Every purchase order debits the agreement's funds:
    `remaining_ceiling_cents` is reduced by the order's `total_cents`, and an
    order whose total would drive the remainder negative is rejected with
    `ERR_LTA_CEILING_EXCEEDED` (402)."

    Design: Corner/validations/lta_ceiling_exceeded_402
    """
    lta = create_active_lta(
        ceiling_cents=1000000,
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.0,
    )
    create_purchase_order(lta["id"], quantity=100)  # 450000
    create_purchase_order(lta["id"], quantity=100)  # 450000
    lta_now = get_lta(lta["id"])
    assert lta_now["remaining_ceiling_cents"] == 100000, (
        f"1000000 - 2 x 450000 must leave 100000, got "
        f"{lta_now['remaining_ceiling_cents']}"
    )
    resp = api_client.create_purchase_order(
        {
            "lta_id": lta["id"],
            "po_number": "PO-OVER-CEILING",
            "part_number": "P-CEIL",
            "part_revision": "A",
            "quantity": 100,
            "flowdown_clauses": ["AS9100D_QMS"],
            "requires_special_process": False,
            "delivery_year": 2026,
            "expected_lta_version": lta_now["version"],
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_LTA_CEILING_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner: consistency_model / po_create_response_immediately_consistent
# ---------------------------------------------------------------------------

def test_po_create_response_immediately_consistent(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "Every purchase order debits the agreement's funds:
    `remaining_ceiling_cents` is reduced by the order's `total_cents`, and an
    order whose total would drive the remainder negative is rejected with
    `ERR_LTA_CEILING_EXCEEDED` (402)."

    Design: Corner/consistency_model/po_create_response_immediately_consistent
    """
    lta = create_active_lta(
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.0,
    )
    resp = api_client.create_purchase_order(
        {
            "lta_id": lta["id"],
            "po_number": "PO-IC",
            "part_number": "P-IC",
            "part_revision": "A",
            "quantity": 100,
            "flowdown_clauses": ["AS9100D_QMS"],
            "requires_special_process": False,
            "delivery_year": 2026,
            "expected_lta_version": lta["version"],
        },
        CM,
    )
    po = validate_success(resp, expected_status=201)
    assert_purchase_order(po)
    # The create response itself already carries the computed pricing.
    assert po["unit_price_cents"] == 4500
    assert po["total_cents"] == 450000
    # A read immediately afterwards shows the ceiling debit, no reconciliation lag.
    lta_after = get_lta(lta["id"])
    assert lta_after["remaining_ceiling_cents"] == 100000000 - 450000


# ---------------------------------------------------------------------------
# Corner: state_machines / po_double_cancel_terminal_lockdown
# ---------------------------------------------------------------------------

def test_po_double_cancel_terminal_lockdown(api):
    """PRD §3.2: "Cancellation moves an order from `RECEIVED`, `ACCEPTED`, or
    `RELEASED` to the terminal `CANCELLED` state; an order in any other state
    is not cancellable, and the attempt fails with `ERR_PO_NOT_CANCELLABLE`."

    Design: Corner/state_machines/po_double_cancel_terminal_lockdown
    """
    lta = create_active_lta(escalation_pct_per_year=0.0)
    po = create_purchase_order(lta["id"], quantity=1)
    cancelled = validate_success(
        api_client.cancel_purchase_order(po["id"], CM), expected_status=200
    )
    assert cancelled["status"] == "CANCELLED"
    resp = api_client.cancel_purchase_order(po["id"], CM)
    validate_error(resp, ApiErrorId.ERR_PO_NOT_CANCELLABLE.value)
