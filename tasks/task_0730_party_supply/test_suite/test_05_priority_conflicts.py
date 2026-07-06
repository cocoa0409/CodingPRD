"""Difficulty rule 5 — validation priority conflicts across different
error-category pairs.

Instance A: state (priority 6) vs business_safety (priority 8) — state wins.
Instance B: existence (priority 5) vs business_referential (priority 9)
            — existence wins.
"""
from test_helpers import (
    validate_error, api_client, ApiErrorId,
    make_store_clerk_headers, make_store_manager_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock,
    setup_draft_order, apply_clearance,
)


# =====================================================================
# Instance A — state_vs_business_safety_return_from_draft_clearance_line
# =====================================================================

def test_return_from_draft_with_clearance_line_returns_invalid_state():
    """PRD §3.9: "State-machine legality of the requested transition is
    sixth, raising ERR_INVALID_STATE."
    PRD §3.9: "The business-safety clearance-non-returnable check is
    eighth, raising ERR_CLEARANCE_NON_RETURNABLE."
    PRD §3.9: "When several checks would apply to the same request, the
    earliest priority is the one that determines the reported error."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_return_from_draft_clearance_line
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=4000, on_hand=10, category="COSTUME")
    # apply_clearance uses current SKU version (after restock).
    apply_clearance(sku["id"], 0.30, sku["version"])
    # DRAFT order with a clearance-line item — return would fail BOTH state
    # (DRAFT not in {PICKED_UP, DELIVERED}) AND clearance-non-returnable.
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    resp = api_client.return_order(order["id"], make_store_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_return_from_reserved_with_clearance_line_returns_invalid_state():
    """PRD §3.9: "State-machine legality of the requested transition is
    sixth, raising ERR_INVALID_STATE."
    PRD §3.9: "The business-safety clearance-non-returnable check is
    eighth, raising ERR_CLEARANCE_NON_RETURNABLE."
    PRD §3.9: "When several checks would apply to the same request, the
    earliest priority is the one that determines the reported error."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_return_from_draft_clearance_line
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=4000, on_hand=10, category="COSTUME")
    apply_clearance(sku["id"], 0.30, sku["version"])
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    # Reserve — RESERVED is also not returnable per §3.5 (must be PICKED_UP or DELIVERED).
    r_res = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    from test_helpers import validate_success
    reserved = validate_success(r_res)
    assert reserved["fulfillment_status"] == "RESERVED"
    # Return attempt → state check (priority 6) fires before clearance check (priority 8).
    resp = api_client.return_order(reserved["id"], make_store_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =====================================================================
# Instance B — existence_vs_business_referential_rental_missing_order_wins
# =====================================================================

def test_rental_create_with_missing_order_and_non_tableware_returns_fk_not_found():
    """PRD §3.9: "Body-referenced foreign key existence is fifth, raising
    ERR_FK_NOT_FOUND."
    PRD §3.9: "Then the business-referential rental category check is
    ninth, raising ERR_RENTAL_CATEGORY_INVALID."
    PRD §3.9: "When several checks would apply to the same request, the
    earliest priority is the one that determines the reported error."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_referential_rental_missing_order_wins
    """
    set_clock("2026-06-15T10:00:00Z")
    latex_sku = create_sku_with_stock(unit_price_cents=100, on_hand=0,
                                      category="BALLOON_LATEX")
    # order_id is a well-formed but non-existent UUID; sku_id is not TABLEWARE.
    payload = {
        "order_id": "00000000-0000-4000-8000-000000000000",
        "sku_id": latex_sku["id"],
        "qty": 1,
        "rental_start": "2026-06-20T00:00:00Z",
        "rental_end": "2026-06-21T00:00:00Z",
    }
    resp = api_client.create_rental_contract(payload, make_store_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


def test_rental_create_with_missing_sku_and_missing_order_returns_fk_not_found():
    """PRD §3.9: "Body-referenced foreign key existence is fifth, raising
    ERR_FK_NOT_FOUND."
    PRD §3.9: "Then the business-referential rental category check is
    ninth, raising ERR_RENTAL_CATEGORY_INVALID."
    PRD §3.9: "When several checks would apply to the same request, the
    earliest priority is the one that determines the reported error."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_referential_rental_missing_order_wins
    """
    set_clock("2026-06-15T10:00:00Z")
    # Both FKs absent → FK check must fire before any category derivation.
    payload = {
        "order_id": "00000000-0000-4000-8000-000000000000",
        "sku_id": "00000000-0000-4000-8000-000000000001",
        "qty": 1,
        "rental_start": "2026-06-20T00:00:00Z",
        "rental_end": "2026-06-21T00:00:00Z",
    }
    resp = api_client.create_rental_contract(payload, make_store_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)
