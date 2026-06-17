"""Square-footage accounting, space lifecycle, and the compensating kill cascade.

Covers Difficulty rule transitive_cascade (kill depth-2) and compensating_invariant
(square feet), plus Corner cross-cutting and state-machine inventory instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
    setup_accepted_deal,
    setup_one_firm, create_broker, create_property, create_published_space,
    create_space, publish_space,
)


class TestKillCompensation:
    def test_kill_from_loi_accepted_returns_space_and_restores_available_sf(self, api):
        """PRD §3.6: "Killing from `LOI_ACCEPTED` is a compensating cascade: it rejects the accepted
        proposal, clears `accepted_proposal_id`, resets `total_consideration` and
        `total_commission` to 0, returns the space from `UNDER_LOI` to `AVAILABLE`
        and recomputes the property's `available_sf`, bubbles the listing back to
        `ACTIVE` when `open_deal_count` is 0 and the requirement back to `OPEN`, and
        increments the deal's `version`."

        Design: Difficulty/transitive_cascade/kill_compensation_cascade_depth_two
        """
        ctx = setup_accepted_deal(
            co_broke=True, base_rent_psf_yr=50, term_months=60, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=50, max_rent_psf_yr=70, market="WEST-SEA")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        tb_h = make_tenant_broker_headers(ctx["tb"]["id"])
        # Space is UNDER_LOI now; available_sf temporarily 0.
        assert get_success_data(api.get_space(ctx["space"]["id"], lb_h))["status"] == "UNDER_LOI"
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        validate_success(api.kill_deal(ctx["deal"]["id"], {"expected_deal_version": deal["version"]}, lb_h))

        assert get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["stage"] == "DEAD"
        assert get_success_data(api.get_space(ctx["space"]["id"], lb_h))["status"] == "AVAILABLE"
        prop = get_success_data(api.get_property(ctx["property"]["id"], lb_h))
        assert prop["available_sf"] == 5000, (
            f"available_sf restored to 5000, got {prop['available_sf']}")

    def test_kill_from_loi_accepted_resets_consideration_to_zero(self, api):
        """PRD §3.6: "Killing from `LOI_ACCEPTED` is a compensating cascade: it rejects the accepted
        proposal, clears `accepted_proposal_id`, resets `total_consideration` and
        `total_commission` to 0".

        Design: Difficulty/transitive_cascade/kill_compensation_cascade_depth_two
        """
        ctx = setup_accepted_deal(
            co_broke=True, base_rent_psf_yr=50, term_months=60, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=50, max_rent_psf_yr=70, market="WEST-SEA")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        validate_success(api.kill_deal(ctx["deal"]["id"], {"expected_deal_version": deal["version"]}, lb_h))
        killed = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert killed["total_consideration"] == 0, (
            f"total_consideration reset to 0, got {killed['total_consideration']}")


class TestAvailableSfConservation:
    def test_accept_then_kill_conserves_available_sf(self, api):
        """PRD §2.6: "when a space moves from `AVAILABLE` to `UNDER_LOI` the property's `available_sf`
        drops by exactly that space's `rentable_sf`, and a compensating move back
        from `UNDER_LOI` to `AVAILABLE` restores it by the same amount."

        Design: Difficulty/compensating_invariant/accept_then_kill_conserves_available_sf
        """
        ctx = setup_accepted_deal(
            co_broke=True, base_rent_psf_yr=50, term_months=60, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=50, max_rent_psf_yr=70, market="WEST-SEA")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        tb_h = make_tenant_broker_headers(ctx["tb"]["id"])
        # Forward action (accept) already moved AVAILABLE->UNDER_LOI: available_sf is 0.
        prop_mid = get_success_data(api.get_property(ctx["property"]["id"], lb_h))
        assert prop_mid["available_sf"] == 0, "available_sf decremented to 0 while UNDER_LOI"
        # Compensating kill restores it.
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        validate_success(api.kill_deal(ctx["deal"]["id"], {"expected_deal_version": deal["version"]}, tb_h))
        assert get_success_data(api.get_space(ctx["space"]["id"], lb_h))["status"] == "AVAILABLE"
        prop_after = get_success_data(api.get_property(ctx["property"]["id"], lb_h))
        assert prop_after["available_sf"] == 5000, (
            f"available_sf restored to exactly 5000, got {prop_after['available_sf']}")
        assert get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["stage"] == "DEAD"

    def test_accept_decrements_available_sf_by_rentable_sf(self, api):
        """PRD §3.6: "A move into `UNDER_LOI` from `AVAILABLE` decrements the property's `available_sf` by
        that space's `rentable_sf`".

        Design: Difficulty/compensating_invariant/accept_then_kill_conserves_available_sf
        """
        ctx = setup_accepted_deal(
            co_broke=True, base_rent_psf_yr=50, term_months=60, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=50, max_rent_psf_yr=70, market="WEST-SEA",
            suite_no="2")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        space = get_success_data(api.get_space(ctx["space"]["id"], lb_h))
        assert space["status"] == "UNDER_LOI"
        prop = get_success_data(api.get_property(ctx["property"]["id"], lb_h))
        # property had a single 5000-sf space (available_sf 5000); accept drops it to 0.
        assert prop["available_sf"] == 0, (
            f"available_sf decremented by the space's 5000 rentable_sf, got {prop['available_sf']}")


class TestSpaceLifecycle:
    def test_publish_moves_space_to_available_and_increments_available_sf(self, api):
        """PRD §3.2: "The listing broker publishes it, moving it from `DRAFT` to `AVAILABLE`, which is
        allowed only when the space has a `rentable_sf` of at least 1 and an
        `asking_rent_psf_yr` greater than 0; publication recomputes the parent
        property's `available_sf` so the now-`AVAILABLE` suite counts toward it."

        Design: Corner/state_machines/publish_space_starts_available_initial_state
        """
        _, lb, _ = setup_one_firm()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space = create_space(lb["id"], prop["id"], "P1", rentable_sf=2000, asking_rent_psf_yr=45)
        assert space["status"] == "DRAFT"
        published = publish_space(lb["id"], space["id"])
        assert published["status"] == "AVAILABLE"
        assert get_success_data(api.get_property(prop["id"], lb_h))["available_sf"] == 2000

    def test_available_sf_reconciles_after_space_withdraw(self, api):
        """PRD §3.2: "Withdrawing a space moves it from `AVAILABLE` to `OFF_MARKET`; this is permitted
        only when none of the property's listings sits in `UNDER_NEGOTIATION` and no
        space is `UNDER_LOI`, and when it succeeds it cascades every child listing
        that is in `DRAFT` or `ACTIVE` to `WITHDRAWN` and recomputes `available_sf`."

        Design: Corner/cross_cutting_complexity_layers/derived_available_sf_after_withdraw
        """
        _, lb, _ = setup_one_firm()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        create_published_space(lb["id"], prop["id"], "AV1", rentable_sf=2000, asking_rent_psf_yr=45)
        space2 = create_published_space(lb["id"], prop["id"], "AV2", rentable_sf=3000, asking_rent_psf_yr=45)
        assert get_success_data(api.get_property(prop["id"], lb_h))["available_sf"] == 5000
        validate_success(api.withdraw_space(space2["id"], lb_h))
        assert get_success_data(api.get_space(space2["id"], lb_h))["status"] == "OFF_MARKET"
        assert get_success_data(api.get_property(prop["id"], lb_h))["available_sf"] == 2000
