"""Priority-pair validation conflicts and cross-entity state dependencies."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    get_success_data,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_creator_headers,
    set_clock,
    setup_basic_scenario,
    create_verified_creator,
    create_creator,
    create_active_partner,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    create_order_and_authorize,
    create_payout_cycle,
    order_payload,
    creator_register_payload,
    creator_verify_payload,
)


# =============================================================================
# Rule 5 — priority_pair_validation_conflict: state vs strike
# =============================================================================

def test_approve_already_approved_design_returns_invalid_state(api):
    """PRD §2.9: "Priority 5 covers state-precondition checks: the generic
    `ERR_INVALID_STATE` for any transition whose entity state does not permit
    the operation".
    PRD §3.5: "Approval transitions `status` from `MOCKUP_READY` to `APPROVED`,
    making the design eligible to appear on published listings."

    Approve fired against a design already at APPROVED fails the state
    precondition; ERR_INVALID_STATE is returned.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_design_approve
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="pv1@example.com", display_name="PV1")
    design = upload_and_approve_design(creator["id"], file_hash="hash_pv1")
    # Design is now APPROVED. Try to approve again.
    resp = api.approve_design(design["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_release_unverified_creator_payout_returns_creator_not_verified(api):
    """PRD §2.9: "Priority 7 is the creator-verification safety check on payout
    release, yielding `ERR_CREATOR_NOT_VERIFIED`."
    PRD §3.9: "Release requires the cycle to be at `DRAFT`, the owning creator
    to be `VERIFIED` (any other verification value is rejected with
    `ERR_CREATOR_NOT_VERIFIED`), and the computed `gross_earnings_cents` to be
    strictly greater than zero — a release whose gross would be zero is rejected
    with `ERR_PAYOUT_ZERO_GROSS`."
    PRD §2.9: "When multiple validations apply to the same request, the failure
    with the numerically lowest priority is the one returned to the caller."

    An UNVERIFIED creator with no delivered orders (gross would be zero) triggers
    both priority-7 and priority-17; priority 7 wins -> ERR_CREATOR_NOT_VERIFIED.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_payout_release
    """
    set_clock("2026-06-15T00:00:00Z")
    creator = create_creator(email="pv2@example.com", display_name="PV2")
    # NOT verified. Create a payout cycle covering an empty window.
    cycle = create_payout_cycle(
        creator["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    resp = api.release_payout(cycle["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CREATOR_NOT_VERIFIED)


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================

def test_payout_release_blocked_when_owner_creator_is_unverified(api):
    """PRD §3.9: "Release requires the cycle to be at `DRAFT`, the owning creator
    to be `VERIFIED` (any other verification value is rejected with
    `ERR_CREATOR_NOT_VERIFIED`), and the computed `gross_earnings_cents` to be
    strictly greater than zero — a release whose gross would be zero is rejected
    with `ERR_PAYOUT_ZERO_GROSS`."

    PayoutCycle release depends on the LINKED Creator entity — an UNVERIFIED
    creator blocks the transition.

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_creator_verified
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_creator(email="ce1@example.com", display_name="CE1")
    cycle = create_payout_cycle(
        creator["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    resp = api.release_payout(cycle["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CREATOR_NOT_VERIFIED)


def test_approve_rejected_design_returns_invalid_state(api):
    """PRD §2.9: "Priority 5 covers state-precondition checks: the generic
    `ERR_INVALID_STATE` for any transition whose entity state does not permit
    the operation".
    PRD §3.5: "Approval transitions `status` from `MOCKUP_READY` to `APPROVED`,
    making the design eligible to appear on published listings."
    PRD §3.5: "Rejection at this stage transitions `status` from `MOCKUP_READY`
    to `REJECTED`; because no listings can yet be `PUBLISHED` off a
    `MOCKUP_READY` design, this rejection has no downstream cascade beyond
    refreshing the design's `updated_at`."

    Approve fired against a design that is REJECTED (terminal, non-MOCKUP_READY)
    fails the state precondition — the priority-5 state check surfaces the error
    before any subsequent business-safety check would fire.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_design_approve
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="pv1b@example.com", display_name="PV1B")
    # Upload, mockup, reject (MOCKUP_READY -> REJECTED terminal).
    up_resp = api.upload_design(
        creator["id"], {"file_hash": "hash_pv1b"},
        make_creator_headers(creator["id"]),
    )
    design = get_success_data(up_resp)
    get_success_data(api.generate_mockup(design["id"], make_creator_headers(creator["id"])))
    api.reject_design(design["id"], make_platform_admin_headers())

    resp = api.approve_design(design["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_release_rejected_creator_payout_returns_creator_not_verified(api):
    """PRD §3.9: "Release requires the cycle to be at `DRAFT`, the owning creator
    to be `VERIFIED` (any other verification value is rejected with
    `ERR_CREATOR_NOT_VERIFIED`), and the computed `gross_earnings_cents` to be
    strictly greater than zero — a release whose gross would be zero is rejected
    with `ERR_PAYOUT_ZERO_GROSS`."
    PRD §2.9: "When multiple validations apply to the same request, the failure
    with the numerically lowest priority is the one returned to the caller."

    A REJECTED creator on an empty window (would-be zero gross) still yields
    ERR_CREATOR_NOT_VERIFIED — priority 7 wins over priority 17 regardless of
    which non-VERIFIED value the creator sits at.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_payout_release
    """
    set_clock("2026-06-15T00:00:00Z")
    creator = get_success_data(api.register_creator(
        creator_register_payload(email="pv2b@example.com", display_name="PV2B"),
        make_anonymous_headers(),
    ))
    get_success_data(api.verify_creator(
        creator["id"], creator_verify_payload(outcome="REJECTED"),
        make_platform_admin_headers(),
    ))
    cycle = create_payout_cycle(
        creator["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    resp = api.release_payout(cycle["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CREATOR_NOT_VERIFIED)


def test_order_capture_fails_when_no_partner_has_capacity(api):
    """PRD §3.7: "A partner whose `current_backlog_hours` equals its
    `max_backlog_hours` is excluded — equality means excluded."
    PRD §3.7: "If the country-matched candidate set is empty, the selector falls
    back to any `ACTIVE` partner (regardless of country) whose
    `current_backlog_hours` is strictly less than its `max_backlog_hours`; this
    is the cross-border fallback. If the fallback set is also empty, the routing
    attempt fails with `ERR_NO_ELIGIBLE_PARTNER`."
    PRD §3.7: "Capturing the payment transitions `payment_status` from
    `AUTHORIZED` to `CAPTURED` and, if `fulfillment_status` is still `PENDING`,
    immediately fires the routing selector."

    A partner with max_backlog_hours=0 is instantly ineligible (0 < 0 is false),
    so capture with no other partners triggers ERR_NO_ELIGIBLE_PARTNER.

    Design: Difficulty/cross_entity_state_dependency/order_route_depends_on_partner_status_and_backlog
    """
    set_clock("2026-06-01T00:00:00Z")
    # Only partner has capacity 0 -> ineligible
    create_active_partner(name="US Zero", country_code="US", max_backlog_hours=0)
    product, variant = create_product_and_variant(sku="T-CE2", category="APPAREL")
    creator = create_verified_creator(email="ce2@example.com", display_name="CE2")
    storefront = create_storefront(creator["id"], slug="ce2-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_ce2")
    listing = create_and_publish_listing(
        storefront["id"], design["id"], variant["id"], creator["id"], title="CE2 Tee",
    )
    ord_resp = api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=1),
        make_anonymous_headers(),
    )
    order = get_success_data(ord_resp)
    api.authorize_order(order["id"], make_platform_admin_headers())

    resp = api.capture_order(order["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PARTNER)


def test_verified_creator_can_release_payout_with_delivered_gross(api):
    """PRD §3.9: "Release requires the cycle to be at `DRAFT`, the owning creator
    to be `VERIFIED` (any other verification value is rejected with
    `ERR_CREATOR_NOT_VERIFIED`), and the computed `gross_earnings_cents` to be
    strictly greater than zero — a release whose gross would be zero is rejected
    with `ERR_PAYOUT_ZERO_GROSS`."
    PRD §3.9: "The cycle transitions to `RELEASED`, and the creator's
    `payout_wallet_cents` decreases by `net_paid_cents`."

    Positive counterpart of the cross-entity dependency: a VERIFIED creator with
    a delivered non-sample order in-window CAN release the cycle — proving the
    dependency is a gating check, not an unconditional block.

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_creator_verified
    """
    from test_helpers import setup_basic_scenario, create_and_capture_order, advance_order_to_delivered
    scenario = setup_basic_scenario(
        creator_email="ce_pos@example.com", display_name="CE-POS", slug="ce-pos-sf",
        sku="T-CE-POS", markup_bps=5000, file_hash="hash_ce_pos",
        clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    advance_order_to_delivered(scenario, order)
    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    resp = api.release_payout(cycle["id"], make_platform_admin_headers())
    from test_helpers import validate_success
    data = validate_success(resp)
    assert data["status"] == "RELEASED", \
        f"VERIFIED creator with delivered gross should release cycle, got status={data['status']}"


def test_order_capture_routes_when_eligible_partner_exists(api):
    """PRD §3.7: "Capturing the payment transitions `payment_status` from
    `AUTHORIZED` to `CAPTURED` and, if `fulfillment_status` is still `PENDING`,
    immediately fires the routing selector."
    PRD §3.7: "Routing advances `fulfillment_status` from `PENDING` to `ROUTED`."
    PRD §3.7: "The selector considers every `FulfillmentPartner` whose `status`
    is `ACTIVE`, whose `country_code` matches the order's `ship_country_code`,
    and whose `current_backlog_hours` is strictly less than its
    `max_backlog_hours`."

    Positive counterpart of the cross-entity dependency: with one ACTIVE US
    partner that has capacity, capture succeeds AND fulfillment_status moves to
    ROUTED (proving routing found an eligible partner).

    Design: Difficulty/cross_entity_state_dependency/order_route_depends_on_partner_status_and_backlog
    """
    from test_helpers import setup_basic_scenario
    scenario = setup_basic_scenario(
        creator_email="ce_pos2@example.com", display_name="CE-POS2", slug="ce-pos2-sf",
        sku="T-CE-POS2", markup_bps=5000, file_hash="hash_ce_pos2",
    )
    order = create_order_and_authorize(scenario, item_count=1)
    resp = api.capture_order(order["id"], make_platform_admin_headers())
    from test_helpers import validate_success
    data = validate_success(resp)
    assert data["payment_status"] == "CAPTURED"
    assert data["fulfillment_status"] == "ROUTED", \
        f"With eligible partner, capture should route the order; got {data['fulfillment_status']}"
    assert data.get("routed_partner_id") == scenario["partner"]["id"]
