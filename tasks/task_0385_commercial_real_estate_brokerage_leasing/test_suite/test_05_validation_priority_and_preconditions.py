"""Validation priority ordering, cross-entity preconditions, and the match predicate
boundary.

Covers Difficulty rules priority_pair_validation_conflict (both), boundary_precision_check
(match sf), and cross_entity_state_dependency (deal->listing), plus Corner validation and
precondition-enforcement instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
    setup_two_firms, create_broker, create_property, create_published_space,
    create_active_listing, create_requirement, create_tour, confirm_tour,
    setup_prospect_deal, submit_first_proposal,
)


class TestPriorityConflicts:
    def test_stale_version_beats_wrong_side(self, api):
        """PRD §2.10: A consequence of this ordering is that a stale deal version surfaces
        as `ERR_STALE_DEAL_VERSION` before any "wrong side" or "invalid state" reasoning is
        applied.

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_wrong_side
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        deal0_version = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["version"]  # 1
        # First LISTING proposal advances version to 2; latest PENDING is from LISTING.
        validate_success(api.create_proposal(ctx["deal"]["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 50, "term_months": 60,
            "expected_deal_version": deal0_version}, lb_h), expected_status=201)
        # A second LISTING proposal at the stale pre-proposal version is BOTH stale (v1 != v2)
        # AND wrong-side (LISTING again). Stale (priority 6) must win over wrong-side (8).
        validate_error(api.create_proposal(ctx["deal"]["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 49, "term_months": 60,
            "expected_deal_version": deal0_version}, lb_h),
            ApiErrorId.ERR_STALE_DEAL_VERSION.value)

    def test_stale_version_surfaces_before_wrong_side_on_accept(self, api):
        """PRD §2.10: A consequence of this ordering is that a stale deal version surfaces
        as `ERR_STALE_DEAL_VERSION` before any "wrong side" or "invalid state" reasoning is
        applied.

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_wrong_side
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        v0 = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["version"]  # 1
        # LISTING authors the latest PENDING proposal (advances version to 2).
        submit_first_proposal(ctx, "LISTING", 50, 60)
        # LISTING accepting its own proposal is wrong-side AND the version v0 is now stale.
        # Stale (priority 6) wins over wrong-side (priority 8).
        validate_error(api.accept_deal(ctx["deal"]["id"], {
            "from_side": "LISTING", "expected_deal_version": v0}, lb_h),
            ApiErrorId.ERR_STALE_DEAL_VERSION.value)

    def test_space_not_available_beats_window_conflict(self, api):
        """PRD §2.10: "then the business preconditions specific to each workflow —
        negotiation side, listing negotiability, requirement activity, space availability,
        tour-window conflicts, tour clock gates, withdrawal and close guards, and broker
        suspension — as those workflows describe in §3."

        Design: Difficulty/priority_pair_validation_conflict/space_not_available_beats_window_conflict
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        tb_h = make_tenant_broker_headers(tb["id"])
        prop = create_property(lb["id"], "DT-LA", "OFFICE", total_sf=10000)
        space, listing = create_active_listing(
            lb["id"], prop["id"], "31", rentable_sf=5000, asking_rent_psf_yr=40,
            term_months=120, annual_escalation_pct=0)
        req_tour = create_requirement(tb["id"], "DT-LA", "OFFICE", 1000, 9000, 70, "Tour Tenant")
        # tour1 confirmed 10:00-11:00; tour2 10:30-11:30 would overlap, still REQUESTED
        t1 = create_tour(tb["id"], req_tour["id"], space["id"],
                         "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        t2 = create_tour(tb["id"], req_tour["id"], space["id"],
                         "2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z")
        # Drive a separate deal to EXECUTED so the space becomes LEASED.
        req_deal = create_requirement(tb["id"], "DT-LA", "OFFICE", 1000, 9000, 70, "Deal Tenant")
        deal = get_success_data(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req_deal["id"]}, lb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.create_proposal(deal["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 40, "term_months": 120,
            "annual_escalation_pct": 0, "expected_deal_version": d["version"]}, lb_h),
            expected_status=201)
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.accept_deal(deal["id"], {"from_side": "TENANT", "expected_deal_version": d["version"]}, tb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.lease_out_deal(deal["id"], {"expected_deal_version": d["version"]}, lb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.execute_deal(deal["id"], {"expected_deal_version": d["version"]}, lb_h))
        assert get_success_data(api.get_space(space["id"], lb_h))["status"] == "LEASED"
        # Now confirming t2: space is LEASED (not showable) AND windows overlap.
        # Space availability (earlier precondition) must surface.
        validate_error(api.confirm_tour(t2["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_SPACE_NOT_AVAILABLE.value)

    def test_space_not_available_precedence_leaves_tour_requested(self, api):
        """PRD §3.4: "Confirmation requires the space to be in `AVAILABLE` or `ON_HOLD`; a space that is
        `LEASED`, `OFF_MARKET`, or `UNDER_LOI` causes rejection with
        `ERR_SPACE_NOT_AVAILABLE`."
        PRD §2.10: "then the business preconditions specific to each workflow —
        negotiation side, listing negotiability, requirement activity, space availability,
        tour-window conflicts, tour clock gates, withdrawal and close guards, and broker
        suspension — as those workflows describe in §3."

        Design: Difficulty/priority_pair_validation_conflict/space_not_available_beats_window_conflict
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        tb_h = make_tenant_broker_headers(tb["id"])
        prop = create_property(lb["id"], "DT-LA", "OFFICE", total_sf=10000)
        space, listing = create_active_listing(
            lb["id"], prop["id"], "32", rentable_sf=5000, asking_rent_psf_yr=40,
            term_months=120, annual_escalation_pct=0)
        req_tour = create_requirement(tb["id"], "DT-LA", "OFFICE", 1000, 9000, 70, "Tour Tenant")
        t1 = create_tour(tb["id"], req_tour["id"], space["id"],
                         "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        t2 = create_tour(tb["id"], req_tour["id"], space["id"],
                         "2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z")
        req_deal = create_requirement(tb["id"], "DT-LA", "OFFICE", 1000, 9000, 70, "Deal Tenant")
        deal = get_success_data(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req_deal["id"]}, lb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.create_proposal(deal["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 40, "term_months": 120,
            "annual_escalation_pct": 0, "expected_deal_version": d["version"]}, lb_h),
            expected_status=201)
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.accept_deal(deal["id"], {"from_side": "TENANT", "expected_deal_version": d["version"]}, tb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.lease_out_deal(deal["id"], {"expected_deal_version": d["version"]}, lb_h))
        d = get_success_data(api.get_deal(deal["id"], lb_h))
        validate_success(api.execute_deal(deal["id"], {"expected_deal_version": d["version"]}, lb_h))
        validate_error(api.confirm_tour(t2["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_SPACE_NOT_AVAILABLE.value)
        assert get_success_data(api.get_tour(t2["id"], lb_h))["status"] == "REQUESTED"


class TestMatchPredicateBoundary:
    def test_match_count_inclusive_at_max_sf_boundary(self, api):
        """PRD §3.3: "the suite's `rentable_sf` is at least the requirement's `min_sf` and at most its
        `max_sf`, with both bounds inclusive".

        Design: Difficulty/boundary_precision_check/match_predicate_inclusive_max_sf_boundary
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        tb_h = make_tenant_broker_headers(tb["id"])
        prop = create_property(lb["id"], "GASLAMP-SD", "RETAIL", total_sf=30000)
        # boundary space: rentable_sf == max_sf (5000), asking 60 <= max_rent 70 -> MATCH
        create_active_listing(lb["id"], prop["id"], "BND", rentable_sf=5000,
                              asking_rent_psf_yr=60, term_months=36)
        # over space: rentable_sf 5001 > max_sf 5000 -> NO match
        create_active_listing(lb["id"], prop["id"], "OVR", rentable_sf=5001,
                              asking_rent_psf_yr=60, term_months=36)
        req = create_requirement(tb["id"], "GASLAMP-SD", "RETAIL", 1000, 5000, 70, "B1 Tenant")
        fresh = get_success_data(api.get_requirement(req["id"], tb_h))
        assert fresh["match_count"] == 1, (
            f"only the 5000-sf boundary space matches (5001 excluded), got {fresh['match_count']}")

    def test_match_list_excludes_over_boundary_space(self, api):
        """PRD §3.3: "A tenant broker can read the live matches as a list of the listings
        currently satisfying the predicate."
        PRD §3.3: "the suite's `rentable_sf` is at least the requirement's `min_sf` and at most its
        `max_sf`, with both bounds inclusive".

        Design: Difficulty/boundary_precision_check/match_predicate_inclusive_max_sf_boundary
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        tb_h = make_tenant_broker_headers(tb["id"])
        prop = create_property(lb["id"], "ARTS-LA", "RETAIL", total_sf=30000)
        _, listing_in = create_active_listing(lb["id"], prop["id"], "BND2", rentable_sf=5000,
                                              asking_rent_psf_yr=60, term_months=36)
        create_active_listing(lb["id"], prop["id"], "OVR2", rentable_sf=5001,
                              asking_rent_psf_yr=60, term_months=36)
        req = create_requirement(tb["id"], "ARTS-LA", "RETAIL", 1000, 5000, 70, "Match Tenant")
        from test_helpers import validate_paginated
        data, meta = validate_paginated(api.list_requirement_matches(req["id"], tb_h))
        match_ids = [l["id"] for l in data]
        assert listing_in["id"] in match_ids, "the 5000-sf boundary listing is in the match list"
        assert meta["total_count"] == 1, (
            f"only the inclusive-boundary listing matches, got {meta['total_count']}")


class TestCrossEntityPreconditions:
    def test_proposal_requires_listing_negotiable(self, api):
        """PRD §3.5: "This is allowed only when the authoring broker is not `SUSPENDED`
        (`ERR_BROKER_SUSPENDED`), the listing's `status` is `ACTIVE` or
        `UNDER_NEGOTIATION` (`ERR_LISTING_NOT_NEGOTIABLE`)".

        Design: Difficulty/cross_entity_state_dependency/proposal_requires_listing_negotiable
        """
        # Open a deal on a DRAFT (never-activated) listing; first proposal must reject.
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=20000)
        space = create_published_space(lb["id"], prop["id"], "51", rentable_sf=3000, asking_rent_psf_yr=50)
        from test_helpers import create_listing
        listing = create_listing(lb["id"], space["id"], term_months=60)  # left in DRAFT
        req = create_requirement(tb["id"], "SOMA-SF", "OFFICE", 1000, 6000, 70)
        deal = get_success_data(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req["id"]}, lb_h))
        validate_error(api.create_proposal(deal["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 50, "term_months": 60,
            "expected_deal_version": deal["version"]}, lb_h),
            ApiErrorId.ERR_LISTING_NOT_NEGOTIABLE.value)
        assert get_success_data(api.get_deal(deal["id"], lb_h))["stage"] == "PROSPECT"

    def test_proposal_succeeds_once_listing_is_active(self, api):
        """PRD §3.5: "This is allowed only when the authoring broker is not `SUSPENDED`
        (`ERR_BROKER_SUSPENDED`), the listing's `status` is `ACTIVE` or
        `UNDER_NEGOTIATION` (`ERR_LISTING_NOT_NEGOTIABLE`)".

        Design: Difficulty/cross_entity_state_dependency/proposal_requires_listing_negotiable
        """
        # Contrast case: with the listing ACTIVE, the same first proposal is accepted and
        # the deal advances to LOI_DRAFT — proving the listing-status gate was the cause.
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        assert get_success_data(api.get_listing(ctx["listing"]["id"], lb_h))["status"] == "ACTIVE"
        v = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["version"]
        validate_success(api.create_proposal(ctx["deal"]["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 50, "term_months": 60,
            "expected_deal_version": v}, lb_h), expected_status=201)
        assert get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["stage"] == "LOI_DRAFT"

    def test_existence_checked_before_state_on_bogus_listing(self, api):
        """PRD §2.10: "then existence of every path resource and body foreign key
        (`ERR_NOT_FOUND`) ... Only after those structural gates does the system evaluate
        state-level rules".

        Design: Corner/validations/existence_checked_before_state_returns_not_found
        """
        lb, _ = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        validate_error(api.activate_listing(NON_EXISTENT_UUID, lb_h), ApiErrorId.ERR_NOT_FOUND.value)

    def test_accept_by_proposal_author_side_rejected(self, api):
        """PRD §3.6: "The acceptor must be the side that did not author the latest `PENDING` proposal
        (`ERR_WRONG_SIDE`)".

        Design: Corner/state_machines/accept_by_proposal_author_side_rejected
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        # LISTING authors latest PENDING proposal -> LISTING cannot accept its own.
        submit_first_proposal(ctx, "LISTING", 50, 60)
        version = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["version"]
        validate_error(api.accept_deal(ctx["deal"]["id"], {
            "from_side": "LISTING", "expected_deal_version": version}, lb_h),
            ApiErrorId.ERR_WRONG_SIDE.value)
        assert get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))["stage"] == "LOI_DRAFT"

    def test_suspended_broker_open_deal_rejected(self, api):
        """PRD §3.5: "The acting broker must not be `SUSPENDED`, or the open is rejected with
        `ERR_BROKER_SUSPENDED`."

        Design: Corner/state_machines/suspended_broker_open_deal_rejected
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        admin_h = make_admin_headers()
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space, listing = create_active_listing(lb["id"], prop["id"], "SB1",
                                               rentable_sf=3000, asking_rent_psf_yr=50)
        req = create_requirement(tb["id"], "SOMA-SF", "OFFICE", 1000, 6000, 70)
        validate_success(api.suspend_broker(lb["id"], admin_h))
        validate_error(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req["id"]}, lb_h),
            ApiErrorId.ERR_BROKER_SUSPENDED.value)
