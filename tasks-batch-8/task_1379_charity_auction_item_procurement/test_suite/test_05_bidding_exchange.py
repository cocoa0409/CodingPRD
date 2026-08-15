"""The bidding exchange: minimum-bid acceptance boundary, tier boundary
selection, event-phase and catalog gates, bidder eligibility, and OCC on
bundle version."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_bid,
    create_bidder,
    create_bundle,
    attach_item,
    create_event,
    get_success_data,
    make_bidder_headers,
    publish_bundle,
    setup_bidding_open_scenario,
    setup_published_bundle,
    setup_valued_item,
    place_bid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMinBidAcceptanceBoundary:

    def test_bid_below_min_bid_rejected(self):
        """PRD section 3.5: "When no `ACTIVE` bid exists on the bundle,
        the minimum acceptable next bid is the bundle's `min_bid_cents`."
        PRD section 2.8: "the offered amount reaches the minimum acceptable
        next bid; otherwise `ERR_BID_BELOW_MINIMUM` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_min_bid_boundary
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Rug")
        assert ctx["bundle"]["min_bid_cents"] == 12000
        bidder = create_bidder(ctx["event"]["id"])
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 11999,
             "expected_bundle_version": ctx["bundle"]["version"]},
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM)

    def test_bid_exactly_at_min_bid_accepted(self):
        """PRD section 3.5: "Acceptance is inclusive: an `amount_cents`
        equal to the computed minimum is accepted."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_min_bid_boundary
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Rug")
        bidder = create_bidder(ctx["event"]["id"])
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": ctx["bundle"]["version"]},
            make_bidder_headers(bidder["id"]),
        )
        bid = validate_success(resp, expected_status=201)
        assert_bid(bid)
        assert bid["status"] == "ACTIVE"
        assert bid["bidder_id"] == bidder["id"]
        assert bid["placed_at"] == "2026-08-01T00:00:00Z"

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["current_high_bid_cents"] == 12000


class TestTierBoundarySelection:

    def _event_with_high_bid_at_tier_edge(self):
        """Bundle FMV 100000 (min 30000); first bid lands at exactly
        100000, the first tier's up_to_cents boundary."""
        ctx = setup_bidding_open_scenario(fmv_cents=100000, title="Guitar")
        bidder1 = create_bidder(ctx["event"]["id"], full_name="Bidder One")
        bidder2 = create_bidder(ctx["event"]["id"], full_name="Bidder Two")
        bid1 = place_bid(ctx["bundle"]["id"], 100000, bidder1["id"])
        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["current_high_bid_cents"] == 100000
        return ctx, bidder1, bidder2, bid1, bundle

    def test_tier_boundary_strict_less_than_rejects_below(self):
        """PRD section 3.5: "Tier selection is strict at the boundary: a
        current high bid exactly equal to a tier's `up_to_cents` falls
        into the following tier. Consider an event whose tiers place a
        5000-cent increment above a 100000-cent boundary — with the
        current high bid at exactly 100000 cents, the 100000-boundary tier
        does not apply, the 5000-cent increment governs, and the minimum
        acceptable bid is 105000 cents."

        Design: Difficulty/combinatorial_formula/min_next_bid_tier_boundary
        """
        ctx, _b1, bidder2, _bid1, bundle = \
            self._event_with_high_bid_at_tier_edge()
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 104999,
             "expected_bundle_version": bundle["version"]},
            make_bidder_headers(bidder2["id"]),
        )
        # min_next = 100000 + 5000 (second tier) = 105000.
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM)

    def test_tier_boundary_acceptance_inclusive(self):
        """PRD section 3.5: "Acceptance is inclusive: an `amount_cents`
        equal to the computed minimum is accepted." PRD section 3.5: "The
        bundle's previous `ACTIVE` bid, if any, transitions to `OUTBID`,
        the new bid enters `ACTIVE`, and the bundle's
        `current_high_bid_cents` is updated to the new amount, with the
        bundle's `version` incrementing."

        Design: Difficulty/combinatorial_formula/min_next_bid_tier_boundary
        """
        ctx, _b1, bidder2, bid1, bundle = \
            self._event_with_high_bid_at_tier_edge()
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 105000,
             "expected_bundle_version": bundle["version"]},
            make_bidder_headers(bidder2["id"]),
        )
        bid2 = validate_success(resp, expected_status=201)
        assert bid2["status"] == "ACTIVE"

        data, _meta = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle"]["id"], ADMIN))
        by_id = {b["id"]: b for b in data}
        assert by_id[bid1["id"]]["status"] == "OUTBID"
        assert by_id[bid2["id"]]["status"] == "ACTIVE"

        after = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert after["current_high_bid_cents"] == 105000


class TestBidEventPhaseGate:

    def _cataloging_event_with_published_bundle(self):
        """Event still CATALOGING with one PUBLISHED bundle (FMV 40000,
        min bid 12000); a registered bidder with a payment method."""
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        part = setup_valued_item(event["id"], 40000, title="Lamp")
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        bundle = setup_published_bundle(event["id"], [part["item"]["id"]],
                                        title="Lamp")
        bidder = create_bidder(event["id"])
        return event, bundle, bidder

    def test_bid_rejected_while_event_cataloging(self):
        """PRD section 3.5: "The bundle's event must be in `BIDDING_OPEN`
        (`ERR_EVENT_PHASE_FORBIDDEN` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/bid_requires_event_bidding_open
        """
        _event, bundle, bidder = \
            self._cataloging_event_with_published_bundle()
        assert bundle["status"] == "PUBLISHED", \
            "the bundle's own machine is satisfied"
        resp = api_client.place_bid(
            bundle["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": bundle["version"]},
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_PHASE_FORBIDDEN)

    def test_bid_accepted_once_bidding_opens(self):
        """PRD section 3.5: "The bundle's event must be in `BIDDING_OPEN`
        (`ERR_EVENT_PHASE_FORBIDDEN` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/bid_requires_event_bidding_open
        """
        event, bundle, bidder = \
            self._cataloging_event_with_published_bundle()
        api_client.advance_gala_event(event["id"], ADMIN)  # BIDDING_OPEN
        bid = place_bid(bundle["id"], 12000, bidder["id"])
        assert bid["status"] == "ACTIVE"


class TestStateBeatsFiscal:

    def _event_open_with_draft_and_published_bundles(self):
        """Event BIDDING_OPEN: bundle A PUBLISHED (FMV 30000, min 9000)
        enabled the open; bundle B stays DRAFT with a VALUED item (FMV
        40000) attached."""
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        part_a = setup_valued_item(event["id"], 30000, title="Chair")
        part_b = setup_valued_item(event["id"], 40000, title="Desk")
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        bundle_a = create_bundle(event["id"], title="Chair")
        attach_item(bundle_a["id"], part_a["item"]["id"])
        bundle_b = create_bundle(event["id"], title="Desk")
        bundle_b = attach_item(bundle_b["id"], part_b["item"]["id"])
        bundle_a = publish_bundle(bundle_a["id"])
        api_client.advance_gala_event(event["id"], ADMIN)  # BIDDING_OPEN
        bidder = create_bidder(event["id"])
        return event, bundle_a, bundle_b, bidder

    def test_bid_on_draft_bundle_state_error(self):
        """PRD section 2.8: "Every request is evaluated against a single
        ordered cascade of checks; a failure at any step short-circuits
        the rest, so the error a client receives identifies the earliest
        failing category." PRD section 2.8: "the target entity's state
        machine permits the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409)." (step 7, ahead of the step-19
        bid-amount check)

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_draft_bundle_bid
        """
        _event, _bundle_a, bundle_b, bidder = \
            self._event_open_with_draft_and_published_bundles()
        resp = api_client.place_bid(
            bundle_b["id"],
            {"amount_cents": 1,
             "expected_bundle_version": bundle_b["version"]},
            make_bidder_headers(bidder["id"]),
        )
        # Amount 1 violates the fiscal minimum too, but the DRAFT bundle
        # fails the earlier state check.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_bid_below_minimum_when_state_passes(self):
        """PRD section 2.8: "the offered amount reaches the minimum
        acceptable next bid; otherwise `ERR_BID_BELOW_MINIMUM`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_draft_bundle_bid
        """
        _event, bundle_a, _bundle_b, bidder = \
            self._event_open_with_draft_and_published_bundles()
        assert bundle_a["min_bid_cents"] == 9000
        resp = api_client.place_bid(
            bundle_a["id"],
            {"amount_cents": 1,
             "expected_bundle_version": bundle_a["version"]},
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM)


class TestBidderEligibility:

    def test_bidder_event_mismatch_rejected(self):
        """PRD section 3.5: "The bidder must be registered to the same
        event as the bundle (`ERR_BIDDER_EVENT_MISMATCH`)"

        Design: Corner/validations/bidder_event_mismatch_rejected
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        other_event = create_event()
        outsider = create_bidder(other_event["id"], full_name="Bidder X")
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": ctx["bundle"]["version"]},
            make_bidder_headers(outsider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIDDER_EVENT_MISMATCH)

    def test_suspended_bidder_cannot_bid(self):
        """PRD section 3.5: "The bidder must be registered to the same
        event as the bundle (`ERR_BIDDER_EVENT_MISMATCH`), must be
        `REGISTERED` rather than `SUSPENDED` (`ERR_BIDDER_SUSPENDED`), and
        must have `payment_method_on_file` set
        (`ERR_PAYMENT_METHOD_REQUIRED`)." PRD section 3.5: "a `GalaAdmin`
        may later suspend a bidder by setting `status` to `SUSPENDED` and
        reinstate by setting it back to `REGISTERED`."

        Design: Corner/validations/suspended_bidder_cannot_bid
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        bidder = create_bidder(ctx["event"]["id"])
        validate_success(api_client.set_bidder_status(
            bidder["id"], {"status": "SUSPENDED"}, ADMIN))

        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": ctx["bundle"]["version"]},
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIDDER_SUSPENDED)

        validate_success(api_client.set_bidder_status(
            bidder["id"], {"status": "REGISTERED"}, ADMIN))
        bundle_now = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        accepted = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": bundle_now["version"]},
            make_bidder_headers(bidder["id"]),
        )
        bid = validate_success(accepted, expected_status=201)
        assert bid["status"] == "ACTIVE", "suspend/reinstate cycle"

    def test_bid_without_payment_method_rejected(self):
        """PRD section 3.5: "The bidder must be registered to the same
        event as the bundle (`ERR_BIDDER_EVENT_MISMATCH`), must be
        `REGISTERED` rather than `SUSPENDED` (`ERR_BIDDER_SUSPENDED`), and
        must have `payment_method_on_file` set
        (`ERR_PAYMENT_METHOD_REQUIRED`)."

        Design: Corner/validations/bid_without_payment_method_rejected
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        bidder = create_bidder(ctx["event"]["id"],
                               payment_method_on_file=False)
        resp = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000,
             "expected_bundle_version": ctx["bundle"]["version"]},
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_METHOD_REQUIRED)


class TestBidOcc:

    def test_bid_with_stale_bundle_version_rejected(self):
        """PRD section 2.7: "`POST /bundles/{id}/bids` requires
        `expected_bundle_version`, matched against the bundle's current
        `version`, because the amount decision was made against the
        client's observed `current_high_bid_cents`, which a newer accepted
        bid would have advanced." PRD section 2.7: "If the supplied value
        does not match the resource's current `version`, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_bid_stale_bundle_version
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        bidder1 = create_bidder(ctx["event"]["id"], full_name="Bidder A")
        bidder2 = create_bidder(ctx["event"]["id"], full_name="Bidder B")
        stale_v = ctx["bundle"]["version"]

        first = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 12000, "expected_bundle_version": stale_v},
            make_bidder_headers(bidder1["id"]),
        )
        validate_success(first, expected_status=201)

        second = api_client.place_bid(
            ctx["bundle"]["id"],
            {"amount_cents": 13000, "expected_bundle_version": stale_v},
            make_bidder_headers(bidder2["id"]),
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["current_high_bid_cents"] == 12000, \
            "only the first bid landed"


class TestOpenBiddingGate:

    def test_open_bidding_without_published_bundle_rejected(self):
        """PRD section 3.1: "Moving from `CATALOGING` to `BIDDING_OPEN`
        requires at least one bundle of the event to be `PUBLISHED`; with
        none, the advance is rejected with `ERR_NO_PUBLISHED_BUNDLES`."

        Design: Corner/validations/open_bidding_without_published_bundle_rejected
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        resp = api_client.advance_gala_event(event["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_BUNDLES)

        after = get_success_data(api_client.get_gala_event(event["id"],
                                                           ADMIN))
        assert after["status"] == "CATALOGING"
