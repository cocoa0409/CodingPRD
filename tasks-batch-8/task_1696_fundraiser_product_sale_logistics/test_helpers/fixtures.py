"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All four roles are opaque identities, but
segregation-of-duties rules compare acting X-User-ID against recorded operator
ids, so the helpers thread distinct user ids where the PRD demands separation
(acknowledge vs deliver, record vs refund, report vs approve).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_campaign_payload,
    create_claim_payload,
    create_distribution_event_payload,
    create_group_payload,
    create_order_payload,
    create_payment_payload,
    create_pickup_appointment_payload,
    create_prize_payload,
    create_product_payload,
    create_return_request_payload,
    create_seller_payload,
)
from .test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_supplier_rep_headers,
    make_treasurer_headers,
)

ADMIN = make_admin_headers("admin-1")
COORD = make_coordinator_headers("coord-1")
TREAS = make_treasurer_headers("treas-1")
TREAS2 = make_treasurer_headers("treas-2")
SUPP1 = make_supplier_rep_headers("supp-1")
SUPP2 = make_supplier_rep_headers("supp-2")


def reset_clock(to_iso8601=TEST_DEFAULTS["ORDER_WINDOW_START"]):
    """Drive the logical clock to a known instant (PRD §2.5)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: base hierarchy
# ---------------------------------------------------------------------------

def create_campaign(**overrides):
    """Create a campaign in DRAFT. Returns the campaign dict."""
    resp = api_client.create_campaign(create_campaign_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_group(campaign_id, **overrides):
    resp = api_client.create_group(
        create_group_payload(campaign_id=campaign_id, **overrides), COORD)
    return get_success_data(resp)


def create_product(campaign_id, **overrides):
    resp = api_client.create_product(
        create_product_payload(campaign_id=campaign_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_prize(campaign_id, **overrides):
    resp = api_client.create_prize(
        create_prize_payload(campaign_id=campaign_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_seller(group_id, **overrides):
    resp = api_client.create_seller(
        create_seller_payload(group_id=group_id, **overrides), COORD)
    return get_success_data(resp)


def setup_campaign_group_product(**campaign_overrides):
    """Campaign (DRAFT) + group + product. Returns (campaign, group, product)."""
    campaign = create_campaign(**campaign_overrides)
    group = create_group(campaign["id"])
    product = create_product(campaign["id"])
    return campaign, group, product


def setup_open_campaign_with_seller(**campaign_overrides):
    """Campaign opened with one group, one product, one seller.
    Returns (campaign, group, product, seller)."""
    campaign, group, product = setup_campaign_group_product(
        **campaign_overrides)
    seller = create_seller(group["id"])
    get_success_data(api_client.open_campaign(campaign["id"], ADMIN))
    return campaign, group, product, seller


# ---------------------------------------------------------------------------
# Tier 2: orders and payments
# ---------------------------------------------------------------------------

def create_order(seller_id, product_id, quantity=1, **overrides):
    """Create a DRAFT order with a single line. Returns the order dict."""
    lines = overrides.pop("lines", [{"product_id": product_id,
                                     "quantity": quantity}])
    resp = api_client.create_order(
        create_order_payload(seller_id=seller_id, lines=lines, **overrides),
        COORD)
    return get_success_data(resp)


def create_and_submit_order(seller_id, product_id, quantity=1, **overrides):
    """Create + submit an order. Returns the submitted order dict."""
    order = create_order(seller_id, product_id, quantity, **overrides)
    return get_success_data(api_client.submit_order(order["id"], COORD))


def record_and_clear_payment(order_id, amount_cents, method="CASH",
                             treasurer_headers=None):
    """Record + clear a payment. Returns the cleared payment dict."""
    headers = treasurer_headers or TREAS
    resp = api_client.create_payment(
        create_payment_payload(order_id=order_id, amount_cents=amount_cents,
                               method=method),
        headers)
    payment = get_success_data(resp)
    return get_success_data(api_client.clear_payment(payment["id"], headers))


def create_submitted_paid_order(seller_id, product_id, quantity=1,
                                unit_price_cents=None, method="CASH"):
    """Submitted order fully paid with one cleared payment. Returns order."""
    order = create_and_submit_order(seller_id, product_id, quantity)
    total = order["total_cents"]
    record_and_clear_payment(order["id"], total, method=method)
    return get_success_data(api_client.get_order(order["id"], TREAS))


def get_order_line_id(order_id):
    """First (and typically only) line id of an order."""
    data, _meta = validate_paginated(
        api_client.list_order_lines(order_id, COORD))
    assert len(data) >= 1, f"order {order_id} has no lines"
    return data[0]["id"]


# ---------------------------------------------------------------------------
# Tier 3: supplier pipeline
# ---------------------------------------------------------------------------

def close_ordering_at_window_end(campaign_id):
    """Advance the clock to the window end and close ordering."""
    reset_clock(TEST_DEFAULTS["ORDER_WINDOW_END"])
    return get_success_data(api_client.close_ordering(campaign_id, ADMIN))


def create_and_submit_supplier_order(campaign_id):
    """Create a DRAFT supplier order and submit it. Returns the order."""
    resp = api_client.create_supplier_order({"campaign_id": campaign_id}, ADMIN)
    supplier_order = get_success_data(resp)
    get_success_data(api_client.submit_supplier_order(supplier_order["id"],
                                                      ADMIN))
    return get_success_data(api_client.get_supplier_order(supplier_order["id"],
                                                          ADMIN))


def acknowledge_supplier_order(supplier_order_id, product_id,
                               unit_cost_actual_cents=None):
    """Acknowledge a SUBMITTED supplier order (SupplierRep supp-1)."""
    cost = (TEST_DEFAULTS["SUPPLIER_UNIT_COST_CENTS"]
            if unit_cost_actual_cents is None else unit_cost_actual_cents)
    payload = {
        "confirmed_delivery_date": TEST_DEFAULTS["CONFIRMED_DELIVERY_DATE"],
        "line_costs": [{"product_id": product_id,
                        "unit_cost_actual_cents": cost}],
    }
    return get_success_data(
        api_client.acknowledge_supplier_order(supplier_order_id, payload, SUPP1))


def deliver_supplier_order(supplier_order_id, product_id, delivered_units):
    """Deliver an ACKNOWLEDGED supplier order (SupplierRep supp-2 — never the
    acknowledger, per the deliverer/acknowledger segregation rule)."""
    payload = {
        "actual_delivery_date": TEST_DEFAULTS["ACTUAL_DELIVERY_DATE"],
        "delivered": [{"product_id": product_id,
                       "delivered_units": delivered_units}],
    }
    return get_success_data(
        api_client.deliver_supplier_order(supplier_order_id, payload, SUPP2))


def drive_campaign_to_delivered(campaign_id, product_id, delivered_units,
                                unit_cost_actual_cents=None):
    """ORDERING_CLOSED -> SUPPLIER_ORDERED -> DELIVERED via the supplier
    pipeline. Returns the delivered supplier order."""
    supplier_order = create_and_submit_supplier_order(campaign_id)
    acknowledge_supplier_order(supplier_order["id"], product_id,
                               unit_cost_actual_cents)
    deliver_supplier_order(supplier_order["id"], product_id, delivered_units)
    return get_success_data(api_client.get_supplier_order(supplier_order["id"],
                                                          ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: sort and distribution day
# ---------------------------------------------------------------------------

def generate_and_verify_tickets(campaign_id, verified_qty_by_index=None,
                                default_verified_qty=None):
    """Generate sort tickets and verify each PENDING one. Returns tickets."""
    get_success_data(api_client.generate_sort_tickets(campaign_id, COORD))
    tickets, _meta = validate_paginated(
        api_client.list_sort_tickets(COORD, params={"campaign_id": campaign_id}))
    for index, ticket in enumerate(tickets):
        if ticket["status"] != "PENDING":
            continue
        if verified_qty_by_index and index in verified_qty_by_index:
            qty = verified_qty_by_index[index]
        elif default_verified_qty is not None:
            qty = default_verified_qty
        else:
            qty = ticket["expected_qty"]
        get_success_data(api_client.verify_sort_ticket(
            ticket["id"], {"verified_qty": qty}, COORD))
    refreshed, _meta = validate_paginated(
        api_client.list_sort_tickets(COORD, params={"campaign_id": campaign_id}))
    return refreshed


def create_and_complete_event(campaign_id, **overrides):
    """Create a distribution event, advance the clock inside its window, and
    complete it. Returns the completed event."""
    event = get_success_data(api_client.create_distribution_event(
        create_distribution_event_payload(campaign_id=campaign_id, **overrides),
        COORD))
    reset_clock(TEST_DEFAULTS["DISTRIBUTION_INSTANT"])
    get_success_data(api_client.complete_distribution_event(event["id"], COORD))
    return get_success_data(api_client.get_distribution_event(event["id"],
                                                              COORD))


def drive_campaign_to_sorted(campaign_id, product_id, delivered_units=12,
                             unit_cost_actual_cents=None,
                             verified_qty_by_index=None,
                             default_verified_qty=None):
    """Full pipeline from ORDERING_CLOSED to SORTED. Returns supplier order."""
    supplier_order = drive_campaign_to_delivered(
        campaign_id, product_id, delivered_units, unit_cost_actual_cents)
    generate_and_verify_tickets(campaign_id, verified_qty_by_index,
                                default_verified_qty)
    get_success_data(api_client.mark_sorted(campaign_id, COORD))
    return supplier_order


def drive_campaign_to_distribution_complete(campaign_id, product_id,
                                            delivered_units=12,
                                            unit_cost_actual_cents=None,
                                            verified_qty_by_index=None,
                                            default_verified_qty=None):
    """Full pipeline to DISTRIBUTION_COMPLETE: supplier order delivered,
    tickets verified, sorted, one event completed, distribution completed.
    The campaign's distribution_completed_at is the distribution instant."""
    supplier_order = drive_campaign_to_sorted(
        campaign_id, product_id, delivered_units, unit_cost_actual_cents,
        verified_qty_by_index, default_verified_qty)
    create_and_complete_event(campaign_id)
    get_success_data(api_client.complete_distribution(campaign_id, COORD))
    return supplier_order


def drive_campaign_to_reconciled(campaign_id, product_id, delivered_units=12,
                                 unit_cost_actual_cents=None,
                                 verified_qty_by_index=None,
                                 default_verified_qty=None):
    """Full pipeline to RECONCILED (clock moved past the 7-day return
    window). Returns supplier order."""
    supplier_order = drive_campaign_to_distribution_complete(
        campaign_id, product_id, delivered_units, unit_cost_actual_cents,
        verified_qty_by_index, default_verified_qty)
    reset_clock(TEST_DEFAULTS["AFTER_RETURN_WINDOW"])
    get_success_data(api_client.reconcile_campaign(campaign_id, ADMIN))
    return supplier_order


def drive_campaign_to_closed(campaign_id, product_id, delivered_units=12,
                             unit_cost_actual_cents=None,
                             verified_qty_by_index=None,
                             default_verified_qty=None):
    """Full pipeline to CLOSED: reconciled, then the Treasurer closes the
    books (final settlement). Returns supplier order."""
    supplier_order = drive_campaign_to_reconciled(
        campaign_id, product_id, delivered_units, unit_cost_actual_cents,
        verified_qty_by_index, default_verified_qty)
    get_success_data(api_client.close_campaign(campaign_id, TREAS))
    return supplier_order


# ---------------------------------------------------------------------------
# Tier 5: claims and returns
# ---------------------------------------------------------------------------

def create_claim(order_id, order_line_id, quantity=1, claim_type="MISSING",
                 reporter_headers=None, **overrides):
    headers = reporter_headers or COORD
    resp = api_client.create_claim(
        create_claim_payload(order_id=order_id, order_line_id=order_line_id,
                             quantity=quantity, claim_type=claim_type,
                             **overrides),
        headers)
    return get_success_data(resp)


def create_approved_claim(order_id, order_line_id, quantity=1,
                          claim_type="MISSING", reporter_headers=None,
                          approver_headers=None):
    claim = create_claim(order_id, order_line_id, quantity, claim_type,
                         reporter_headers=reporter_headers)
    approver = approver_headers or ADMIN
    return get_success_data(api_client.approve_claim(claim["id"], approver))


def create_return_request(seller_id, order_id, order_line_id, quantity=1,
                          reason="UNSOLD", requester_headers=None, **overrides):
    headers = requester_headers or COORD
    resp = api_client.create_return_request(
        create_return_request_payload(
            seller_id=seller_id, order_id=order_id, order_line_id=order_line_id,
            quantity=quantity, reason=reason, **overrides),
        headers)
    return get_success_data(resp)


def create_received_return(seller_id, order_id, order_line_id, quantity=1,
                           reason="UNSOLD", disposition="RESTOCKABLE",
                           requester_headers=None, approver_headers=None):
    """Create a return, approve it (Treasurer != requester), receive it.
    Returns the received return."""
    return_request = create_return_request(
        seller_id, order_id, order_line_id, quantity, reason,
        requester_headers=requester_headers)
    approver = approver_headers or TREAS2
    get_success_data(api_client.approve_return_request(return_request["id"],
                                                       approver))
    return get_success_data(api_client.receive_return_request(
        return_request["id"], {"disposition": disposition}, approver))


# ---------------------------------------------------------------------------
# Convenience readers
# ---------------------------------------------------------------------------

def get_group_ledger(group_id):
    """All ledger entries of a group, in replay order."""
    data, _meta = validate_paginated(
        api_client.list_group_ledger(group_id, TREAS, params={"limit": 100}))
    return data


def get_group(group_id):
    return get_success_data(api_client.get_group(group_id, TREAS))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_campaign(campaign_id):
    return get_success_data(api_client.get_campaign(campaign_id, ADMIN))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, TREAS))


def get_seller(seller_id):
    return get_success_data(api_client.get_seller(seller_id, COORD))


def get_prize(prize_id):
    return get_success_data(api_client.get_prize(prize_id, ADMIN))


def list_seller_awards(seller_id):
    data, _meta = validate_paginated(
        api_client.list_prize_awards(ADMIN, params={"seller_id": seller_id}))
    return data
