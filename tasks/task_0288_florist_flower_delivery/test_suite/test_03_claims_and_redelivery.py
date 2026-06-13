"""Quality claims: branching+cyclic resolution, refund cascade, claim gating, OCC.

Translates queue-A Difficulty non_linear_state_machine (claim branch/redelivery),
transitive_cascade (refund->wallet), cross_entity_state_dependency (claim gating),
and queue-B Corner errors (stale order version on resolve).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers,
    setup_delivered_order, setup_approved_claim,
    file_claim, approve_claim, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_redelivery_resolve_spawns_new_draft_order(api):
    """PRD §3.7: "When the remedy is `REDELIVERY`, resolution creates a brand-new
    redelivery order: its `source_order_id` is set to the original order's `id`, it
    copies the original's arrangement, zone, delivery window, `card_message`, and
    `occasion`, its `delivery_date` is set to the clock date plus one day, and it
    begins fresh at `DRAFT` fulfillment and `UNPAID` payment".

    Design: Difficulty/non_linear_state_machine/claim_branch_then_redelivery_cycles_new_order
    """
    ctx, order, claim = setup_approved_claim(
        "2026-05-10T08:00:00Z", "WILTED", "REDELIVERY",
        zone_overrides={"zone_code": "Z6", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A6", "display_name": "Bouquet6", "base_price_cents": 5000},
        order_overrides={"card_message": "Get well", "delivery_date": "2026-05-15",
                         "window_start_minute": 540, "window_end_minute": 720})
    current = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    resolved = validate_success(api.resolve_claim(
        claim["id"], {"expected_order_version": current["version"]}, DISPATCHER), 200)
    assert resolved["status"] == "RESOLVED"
    assert resolved["redelivery_order_id"] is not None
    redel = validate_success(api.get_order(resolved["redelivery_order_id"], DISPATCHER), 200)
    assert redel["source_order_id"] == order["id"]
    assert redel["fulfillment_status"] == "DRAFT"


def test_refund_resolve_cascades_payment_then_wallet(api):
    """PRD §3.7: "When the remedy is `REFUND`, resolution drives the linked order's
    `payment_status` from `CAPTURED` to the terminal `REFUNDED` state and credits
    the customer's `wallet_credit_cents` by the claim's `refund_cents`."

    Design: Difficulty/transitive_cascade/claim_refund_resolve_cascades_payment_then_wallet
    """
    ctx, order, claim = setup_approved_claim(
        "2026-06-10T08:00:00Z", "WILTED", "REFUND",
        zone_overrides={"zone_code": "Z8", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A8", "display_name": "Bouquet8", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-06-15", "window_start_minute": 540,
                         "window_end_minute": 720})
    # final_total 5800; WILTED 0.50 -> 2900 (floor 500, cap 5800).
    assert claim["refund_cents"] == 2900, claim["refund_cents"]
    current = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    resolved = validate_success(api.resolve_claim(
        claim["id"], {"expected_order_version": current["version"]}, DISPATCHER), 200)
    assert resolved["status"] == "RESOLVED"
    order_after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert order_after["payment_status"] == "REFUNDED"
    cust = validate_success(api.get_customer(ctx["customer"]["id"], DISPATCHER), 200)
    assert cust["wallet_credit_cents"] == 2900, cust["wallet_credit_cents"]


def test_claim_on_undelivered_order_returns_window_invalid(api):
    """PRD §3.7: "A claim may only be filed against an order whose
    `fulfillment_status` is `DELIVERED`; a claim against an order in any other state
    is rejected with `ERR_CLAIM_WINDOW_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_order_delivered
    """
    from test_helpers import setup_in_transit_order
    ctx, order, _wf = setup_in_transit_order(
        "2026-08-10T08:00:00Z",
        zone_overrides={"zone_code": "Z13", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A13", "display_name": "Bouquet13", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-08-15", "window_start_minute": 540,
                         "window_end_minute": 720})
    res = api.create_claim(
        {"order_id": order["id"], "customer_id": ctx["customer"]["id"],
         "reason": "WILTED", "requested_remedy": "REFUND"},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_CLAIM_WINDOW_INVALID", expected_status=409)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "IN_TRANSIT"


def test_stale_order_version_on_resolve_returns_412(api):
    """PRD §3.7: "it carries the optimistic-concurrency requirement of §2.7: the
    request must include `expected_order_version` equal to the linked order's
    current `version`, or it is rejected with `ERR_STALE_ORDER_VERSION`."

    Design: Corner/errors/stale_order_version_on_resolve_returns_412
    """
    # Capture a pre-claim Order version (stale): the claim approval does not
    # mutate the Order, but the order has advanced through its lifecycle since the
    # snapshot, so any earlier version is stale at resolve time.
    ctx, order, _wf = setup_delivered_order(
        "2027-06-15T08:00:00Z",
        zone_overrides={"zone_code": "ZR2", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CR2", "display_name": "CR2", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2027-06-20", "window_start_minute": 540,
                         "window_end_minute": 720})
    stale_version = order["version"] - 1  # one behind the delivered order's version
    claim = file_claim(order, ctx["customer"], "WILTED", "REFUND")
    claim = approve_claim(claim)
    res = api.resolve_claim(claim["id"], {"expected_order_version": stale_version}, DISPATCHER)
    validate_error(res, "ERR_STALE_ORDER_VERSION", expected_status=412)
    after = validate_success(api.get_claim(claim["id"], DISPATCHER), 200)
    assert after["status"] == "APPROVED"
