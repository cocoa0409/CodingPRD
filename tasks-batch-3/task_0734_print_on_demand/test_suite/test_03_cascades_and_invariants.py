"""Cascades (design-reject depth-3, refund-full depth-2) and compensating
invariants (wallet conservation across release/return; backlog conservation
across route/refund)."""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    make_creator_headers,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_fulfillment_partner_headers,
    set_clock,
    setup_basic_scenario,
    create_verified_creator,
    create_active_partner,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    create_and_capture_order,
    advance_order_to_delivered,
    create_order_and_authorize,
    create_payout_cycle,
    release_payout_cycle,
    order_payload,
    refund_payload,
)
from test_helpers.fixtures import _find_job_for_order


# =============================================================================
# Rule 4 — transitive_cascade: design reject -> listing archive -> order cancel
# =============================================================================

def test_design_reject_cascades_listing_to_archived(api):
    """PRD §3.5: "An admin may also recall an already-`APPROVED` design,
    transitioning `status` from `APPROVED` to `REJECTED`. This retroactive
    rejection cascades along a three-level chain. First, every `Listing` whose
    `design_id` equals the recalled design and whose `status` is either `DRAFT`
    or `PUBLISHED` transitions to `ARCHIVED`, with `updated_at` refreshed and
    `version` incremented."

    Rejecting an APPROVED design cascades to any PUBLISHED listing referencing it,
    moving the listing to ARCHIVED.

    Design: Difficulty/transitive_cascade/design_reject_cascades_listing_archive_then_order_cancel_depth3
    """
    scenario = setup_basic_scenario(
        creator_email="tc1@example.com", display_name="TC1", slug="tc1-sf",
        sku="T-TC1", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_tc1", clock_iso="2026-06-01T00:00:00Z",
    )
    # Authorize an order to reach AUTHORIZED payment_status + PENDING fulfillment_status
    order = create_order_and_authorize(scenario, item_count=1)
    # Now reject the (APPROVED) design
    api.reject_design(scenario["design"]["id"], make_platform_admin_headers())

    listing_after = get_success_data(
        api.get_listing(scenario["listing"]["id"], make_platform_admin_headers())
    )
    assert listing_after["status"] == "ARCHIVED", \
        f"Expected listing status=ARCHIVED after design recall, got {listing_after['status']}"


def test_design_reject_cascades_pending_authorized_order_to_cancelled_and_voided(api):
    """PRD §3.5: "Second, every `Order` whose `listing_id` sits in that
    just-archived set, whose `fulfillment_status` is still `PENDING`, and whose
    `payment_status` is either `DRAFT` or `AUTHORIZED`, has its
    `fulfillment_status` transitioned to `CANCELLED`; if that order's
    `payment_status` was `AUTHORIZED`, `payment_status` is simultaneously
    transitioned to `VOIDED`."

    An AUTHORIZED/PENDING order under a design that is subsequently recalled ends
    at payment_status=VOIDED and fulfillment_status=CANCELLED.

    Design: Difficulty/transitive_cascade/design_reject_cascades_listing_archive_then_order_cancel_depth3
    """
    scenario = setup_basic_scenario(
        creator_email="tc2@example.com", display_name="TC2", slug="tc2-sf",
        sku="T-TC2", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_tc2", clock_iso="2026-06-01T00:00:00Z",
    )
    order = create_order_and_authorize(scenario, item_count=1)
    assert order["payment_status"] == "AUTHORIZED"
    assert order["fulfillment_status"] == "PENDING"

    api.reject_design(scenario["design"]["id"], make_platform_admin_headers())

    order_after = get_success_data(
        api.get_order(order["id"], make_platform_admin_headers())
    )
    assert order_after["payment_status"] == "VOIDED", \
        f"Expected payment_status=VOIDED after cascade, got {order_after['payment_status']}"
    assert order_after["fulfillment_status"] == "CANCELLED", \
        f"Expected fulfillment_status=CANCELLED after cascade, got {order_after['fulfillment_status']}"


# =============================================================================
# Rule 4 — transitive_cascade: full refund releases backlog (depth-2)
# =============================================================================

def test_full_refund_of_routed_order_transitions_fulfillment_to_cancelled(api):
    """PRD §3.7: "A refund whose amount equals `gross_amount_cents` exactly
    transitions `payment_status` from `CAPTURED` to `REFUND_FULL`, zeros out that
    order's contribution to `payout_wallet_cents`, and — if `fulfillment_status`
    is `PENDING` or `ROUTED` at the moment of the full refund — transitions
    `fulfillment_status` to `CANCELLED`."

    Design: Difficulty/transitive_cascade/refund_full_cascades_order_cancel_then_backlog_release_depth2
    """
    scenario = setup_basic_scenario(
        creator_email="tc3@example.com", display_name="TC3", slug="tc3-sf",
        sku="T-TC3", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_tc3", clock_iso="2026-06-01T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=2)
    gross = order["gross_amount_cents"]
    api.refund_order(order["id"], refund_payload(gross), make_platform_admin_headers())

    order_after = get_success_data(
        api.get_order(order["id"], make_platform_admin_headers())
    )
    assert order_after["payment_status"] == "REFUND_FULL", \
        f"Expected REFUND_FULL, got {order_after['payment_status']}"
    assert order_after["fulfillment_status"] == "CANCELLED", \
        f"Expected fulfillment_status=CANCELLED, got {order_after['fulfillment_status']}"


def test_full_refund_of_routed_order_releases_partner_backlog(api):
    """PRD §3.7: "When the fulfillment status was `ROUTED` at refund time, the
    routed partner's `current_backlog_hours` is decremented by the ceiling of
    `item_count` multiplied by 0.5, with the result bounded below at zero — this
    releases the routed capacity as a compensating action so that the partner's
    backlog invariant remains conserved."

    Design: Difficulty/transitive_cascade/refund_full_cascades_order_cancel_then_backlog_release_depth2
    """
    scenario = setup_basic_scenario(
        creator_email="tc4@example.com", display_name="TC4", slug="tc4-sf",
        sku="T-TC4", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_tc4", clock_iso="2026-06-01T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=2)

    partner_after_route = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    assert partner_after_route["current_backlog_hours"] == 1, \
        f"Expected backlog=1 after route (ceil(2*0.5)=1), got {partner_after_route['current_backlog_hours']}"

    api.refund_order(order["id"], refund_payload(order["gross_amount_cents"]),
                     make_platform_admin_headers())

    partner_after_refund = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    assert partner_after_refund["current_backlog_hours"] == 0, \
        f"Expected backlog=0 after refund (compensating), got {partner_after_refund['current_backlog_hours']}"


# =============================================================================
# Rule 9 — compensating_invariant: wallet conserved across release/return
# =============================================================================

def test_payout_release_debits_wallet_by_net_paid(api):
    """PRD §3.9: "The cycle transitions to `RELEASED`, and the creator's
    `payout_wallet_cents` decreases by `net_paid_cents`."
    PRD §3.9: "Step three computes `net_paid_cents` as `gross_earnings_cents`
    minus `fee_cents` exactly."

    Design: Difficulty/compensating_invariant/payout_release_return_conserves_creator_wallet
    """
    scenario = setup_basic_scenario(
        creator_email="ci1@example.com", display_name="CI1", slug="ci1-sf",
        sku="T-CI1", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_ci1", clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    advance_order_to_delivered(scenario, order)

    creator_before = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    wallet_pre = creator_before["payout_wallet_cents"]
    assert wallet_pre == 1000, f"Setup: wallet pre-release should be 1000, got {wallet_pre}"

    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    released = release_payout_cycle(cycle["id"])
    net_paid = released["net_paid_cents"]

    creator_after = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_after["payout_wallet_cents"] == wallet_pre - net_paid, \
        f"Expected wallet={wallet_pre - net_paid}, got {creator_after['payout_wallet_cents']}"


def test_payout_return_restores_wallet_to_pre_release_amount(api):
    """PRD §3.9: "On successful return, the creator's `payout_wallet_cents` is
    credited back by `gross_earnings_cents` minus `fee_cents` — the fee is
    included in the restoration so the wallet-plus-external invariant holds."

    Design: Difficulty/compensating_invariant/payout_release_return_conserves_creator_wallet
    """
    scenario = setup_basic_scenario(
        creator_email="ci2@example.com", display_name="CI2", slug="ci2-sf",
        sku="T-CI2", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_ci2", clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    advance_order_to_delivered(scenario, order)

    creator_pre = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    wallet_pre = creator_pre["payout_wallet_cents"]
    assert wallet_pre == 1000, f"Setup: wallet should be 1000 pre-release, got {wallet_pre}"

    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    release_payout_cycle(cycle["id"])

    creator_after_release = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_after_release["payout_wallet_cents"] == 25, \
        f"Sanity: wallet after release should be 25, got {creator_after_release['payout_wallet_cents']}"

    api.return_payout(cycle["id"], make_platform_admin_headers())
    creator_after_return = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_after_return["payout_wallet_cents"] == wallet_pre, \
        f"Expected wallet restored to {wallet_pre}, got {creator_after_return['payout_wallet_cents']}"


# =============================================================================
# Rule 9 — compensating_invariant: backlog conserved across route/refund
# =============================================================================

def test_route_increases_backlog_and_refund_full_restores_it(api):
    """PRD §3.7: "the selected partner's `current_backlog_hours` is increased by
    the ceiling of `item_count` multiplied by 0.5."
    PRD §3.7: "When the fulfillment status was `ROUTED` at refund time, the
    routed partner's `current_backlog_hours` is decremented by the ceiling of
    `item_count` multiplied by 0.5, with the result bounded below at zero — this
    releases the routed capacity as a compensating action so that the partner's
    backlog invariant remains conserved."

    For item_count=2: backlog is incremented by ceil(2*0.5)=1 on route, and
    decremented by the same amount on full refund. backlog_pre == backlog_post.

    Design: Difficulty/compensating_invariant/route_refund_conserves_partner_backlog_hours
    """
    scenario = setup_basic_scenario(
        creator_email="ci3@example.com", display_name="CI3", slug="ci3-sf",
        sku="T-CI3", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_ci3", clock_iso="2026-06-01T00:00:00Z",
    )
    partner_pre = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    backlog_pre_route = partner_pre["current_backlog_hours"]
    assert backlog_pre_route == 0, f"Setup: partner backlog should start at 0, got {backlog_pre_route}"

    order, _ = create_and_capture_order(scenario, item_count=2)
    partner_after_route = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    backlog_post_route = partner_after_route["current_backlog_hours"]
    assert backlog_post_route == 1, f"Expected backlog=1 post-route, got {backlog_post_route}"

    api.refund_order(order["id"], refund_payload(order["gross_amount_cents"]),
                     make_platform_admin_headers())
    partner_after_refund = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    assert partner_after_refund["current_backlog_hours"] == backlog_pre_route, \
        f"Expected backlog restored to {backlog_pre_route}, got {partner_after_refund['current_backlog_hours']}"


def test_backlog_delta_matches_ceil_of_item_count_half_on_route(api):
    """PRD §3.7: "the selected partner's `current_backlog_hours` is increased by
    the ceiling of `item_count` multiplied by 0.5."

    For item_count=2, ceil(2*0.5)=1 — a strictly-positive delta that verifies the
    conserved quantity is not just always zero.

    Design: Difficulty/compensating_invariant/route_refund_conserves_partner_backlog_hours
    """
    scenario = setup_basic_scenario(
        creator_email="ci4@example.com", display_name="CI4", slug="ci4-sf",
        sku="T-CI4", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_ci4", clock_iso="2026-06-01T00:00:00Z",
    )
    partner_pre = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    _order, _ = create_and_capture_order(scenario, item_count=2)
    partner_post = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    delta = partner_post["current_backlog_hours"] - partner_pre["current_backlog_hours"]
    assert delta == 1, f"Expected backlog delta=1 for item_count=2, got {delta}"
