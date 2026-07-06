"""Returns and restocking, direct-buy purchases and their compensating restock, and
the referential-before-fiscal validation ordering on direct buy.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_client_headers,
    create_active_client, create_product,
    setup_checked_out_fix_with_returns, setup_placed_purchase,
    get_fix, get_product,
)

OPS = TEST_USERS["ops_headers"]


# ------------------- Difficulty: referential status beats stock on direct buy
def test_direct_buy_discontinued_reports_unavailable_over_out_of_stock(api):
    """PRD §3.10: "A direct buy requires the client not to be CANCELLED, the product to
    be ACTIVE (otherwise ERR_PRODUCT_UNAVAILABLE), and available_count to be at least
    the requested quantity (otherwise ERR_OUT_OF_STOCK)"
    PRD §2.10: "Sibling referential status — a referenced sibling entity is in an
    acceptable status (a referenced product is ACTIVE, a referenced stylist is ACTIVE);
    otherwise ERR_PRODUCT_UNAVAILABLE or ERR_STYLIST_INACTIVE (409)"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_direct_buy
    """
    prod = create_product(total_stock=1)
    validate_success(api.discontinue_product(prod["id"], headers=OPS), 200)
    client = create_active_client(region_code="CA")
    resp = api.create_purchase(
        client["id"], {"product_id": prod["id"], "quantity": 5},
        headers=make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_UNAVAILABLE.value)


def test_direct_buy_referential_rejection_leaves_stock_untouched(api):
    """PRD §3.10: "A direct buy requires the client not to be CANCELLED, the product to
    be ACTIVE (otherwise ERR_PRODUCT_UNAVAILABLE), and available_count to be at least
    the requested quantity (otherwise ERR_OUT_OF_STOCK)"
    PRD §3.3: "a discontinued product can no longer be selected into fixes or purchased,
    and referencing one where an ACTIVE product is required yields ERR_PRODUCT_UNAVAILABLE"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_direct_buy
    """
    prod = create_product(total_stock=1)
    validate_success(api.discontinue_product(prod["id"], headers=OPS), 200)
    client = create_active_client(region_code="CA")
    api.create_purchase(client["id"], {"product_id": prod["id"], "quantity": 5},
                        headers=make_client_headers(client["id"]))
    after = get_product(prod["id"])
    assert after["available_count"] == 1 and after["sold_count"] == 0, \
        "a rejected direct buy must not sell any units"


# ------------------------------------------------- Corner: return receive & close
def test_receive_return_restocks_items_and_closes_fix(api):
    """PRD §3.7: "Operational staff receive the return, transitioning the shipment to
    RECEIVED from either LABEL_ISSUED or IN_TRANSIT, setting its received_at to the
    current clock, restocking every RETURNED item of the fix (each owning product's
    reserved_count down one and available_count up one), and bubbling the parent fix
    up to CLOSED."

    Design: Corner/state_machines/return_receive_restocks_and_closes_fix
    """
    ctx = setup_checked_out_fix_with_returns(prices=[3000, 3000, 3000])
    resp = api.receive_return(ctx["fix_id"], ctx["return_id"], headers=OPS)
    data = validate_success(resp, 200)
    assert data["status"] == "RECEIVED"
    assert get_fix(ctx["fix_id"])["status"] == "CLOSED"
    for pid in (ctx["product_ids"][1], ctx["product_ids"][2]):  # the two returned items
        prod = get_product(pid)
        assert prod["available_count"] == 5 and prod["reserved_count"] == 0


def test_receive_already_received_return_rejected(api):
    """PRD §3.7: "Receiving a shipment that is already RECEIVED is rejected with
    ERR_RETURN_NOT_RECEIVABLE."

    Design: Corner/errors/return_receive_twice_not_receivable
    """
    ctx = setup_checked_out_fix_with_returns(prices=[3000, 3000, 3000])
    validate_success(api.receive_return(ctx["fix_id"], ctx["return_id"], headers=OPS), 200)
    resp = api.receive_return(ctx["fix_id"], ctx["return_id"], headers=OPS)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_RECEIVABLE.value)


# ------------------------------------------------------- Corner: direct-buy sell
def test_direct_buy_places_purchase_and_sells_units(api):
    """PRD §3.10: "creating a Purchase in PLACED status linked by client_id,
    snapshotting the product's price into unit_price_cents, and computing total_cents
    as unit_price_cents multiplied by quantity"
    PRD §3.10: "it sells the units immediately (available_count down by quantity,
    sold_count up by quantity)"

    Design: Corner/endpoints/direct_buy_sells_inventory
    """
    prod = create_product(price_cents=3000, total_stock=5)
    client = create_active_client(region_code="CA")
    resp = api.create_purchase(
        client["id"], {"product_id": prod["id"], "quantity": 2},
        headers=make_client_headers(client["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED"
    assert data["total_cents"] == 6000
    after = get_product(prod["id"])
    assert after["available_count"] == 3 and after["sold_count"] == 2


def test_cancel_purchase_restocks_units(api):
    """PRD §3.10: "The subscriber may cancel a placed purchase they own, transitioning
    it from PLACED to CANCELLED and compensating the inventory (sold_count down by
    quantity, available_count up by quantity)."

    Design: Corner/endpoints/purchase_cancel_restocks_inventory
    """
    ctx = setup_placed_purchase(price_cents=3000, total_stock=5, quantity=2)
    resp = api.cancel_purchase(ctx["purchase_id"], headers=make_client_headers(ctx["client_id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"
    after = get_product(ctx["product_id"])
    assert after["available_count"] == 5 and after["sold_count"] == 0
