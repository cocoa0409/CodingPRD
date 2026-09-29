"""Two transitions blocked by the state of a neighbouring record: a confirmation
held up by its own technical rider, and an acceptance held up by the engagement's
clearance dimension.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    clear_rider,
    confirm,
    make_artist_representative_headers,
    negotiate_and_accept_fee,
    open_negotiation_round,
    read_engagement,
    register_artist,
    register_equipment_item,
    register_hall,
    reserve_equipment_line,
    review_rider,
    submit_rider,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]


def _presented_engagement_blocked_only_by_its_rider() -> dict:
    """Every confirmation gate satisfied except the rider's: the fee is accepted,
    the clearance is CLEARED, and the rider sits at GAP_IDENTIFIED with its
    covering equipment already reserved."""
    space = register_hall()
    artist = register_artist(legal_name="Cinder Lane Big Band",
                            guarantee_floor_cents=100_000,
                            historical_sell_through_pct=0.80,
                            min_days_between_engagements=0)
    item = register_equipment_item(category="POWER_DISTRO",
                                  model_name="200A Distro Rack",
                                  on_hand_qty=3, daily_rate_cents=25_000,
                                  replacement_value_cents=1_500_000)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Cinder Lane Big Band",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    rider = submit_rider(engagement["id"],
                         make_artist_representative_headers(artist["id"]),
                         submitted_rigging_kg=3_000, requested_power_amps=500,
                         requested_dmx_universes=2)
    reviewed = review_rider(rider["id"])
    assert reviewed["review_status"] == "GAP_IDENTIFIED"
    line = reserve_equipment_line(rider["id"], item["id"],
                                  covers_gap="POWER_SHORTFALL", qty=1,
                                  rental_days=1)
    assert line["line_cost_cents"] == 25_000
    add_price_tier(engagement["id"], tier_name="ORCH", seats_allocated=100,
                   base_price_cents=8_000, price_ceiling_cents=12_000,
                   dynamic_pricing_enabled=False, subscription_eligible=False)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 200_000, 0.10)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 26
    assert assessed["financial_clearance"] == "CLEARED"
    return {"engagement": engagement, "rider": rider, "item": item}


def _prohibitive_engagement_with_a_standing_offer() -> dict:
    """A draft presented engagement whose clearance dimension has been driven to
    BLOCKED while its single negotiation round still stands at OFFERED."""
    space = register_hall(name="Studio Theatre", seat_capacity=400,
                         base_facility_fee_cents=500_000,
                         load_in_day_fee_cents=200_000,
                         changeover_buffer_minutes=60,
                         rigging_capacity_kg=2_000, house_power_amps=200,
                         dmx_universes=2)
    artist = register_artist(legal_name="Tessellate Experimental Ensemble",
                            agency_name="Fringe Agency",
                            guarantee_floor_cents=500_000,
                            historical_sell_through_pct=0.20,
                            routing_window_start_utc="2026-08-05T00:00:00Z",
                            routing_window_end_utc="2026-08-20T00:00:00Z",
                            min_days_between_engagements=0)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Tessellate: Untitled Work No. 4",
        load_in_start_utc="2026-08-10T08:00:00Z",
        performance_start_utc="2026-08-10T19:00:00Z",
        performance_end_utc="2026-08-10T22:00:00Z",
        load_out_end_utc="2026-08-11T02:00:00Z",
        performance_day_count=1, load_in_day_count=0)
    add_price_tier(engagement["id"], tier_name="GA", seats_allocated=100,
                   base_price_cents=5_000, price_ceiling_cents=6_000,
                   dynamic_pricing_enabled=False, subscription_eligible=False)
    standing = open_negotiation_round(engagement["id"], 500_000, 0.20)
    assert standing["status"] == "OFFERED"
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 88
    assert assessed["risk_tier"] == "PROHIBITIVE"
    assert assessed["financial_clearance"] == "BLOCKED"
    return {"artist": artist, "engagement": engagement, "round": standing}


class TestConfirmationGatedByTheRider:

    def test_the_parent_cannot_advance_while_its_rider_still_reads_gap_identified(self):
        """The engagement's own fields are all in order — fee accepted, clearance
        cleared, tier drafted — and the only thing standing in the way is a child
        record one call short of cleared. The refusal touches nothing: the booking
        stays a draft and the reserved inventory stays reserved.

        PRD: "Some technical rider of the engagement must read `CLEARED`, or the
        request is refused with `ERR_RIDER_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_by_tech_rider_review_state
        """
        scenario = _presented_engagement_blocked_only_by_its_rider()
        engagement_id = scenario["engagement"]["id"]

        validate_error(api_client.confirm_engagement(engagement_id, DIRECTOR),
                       "ERR_RIDER_INVALID_STATE", expected_status=409)

        after = read_engagement(engagement_id)
        assert after["lifecycle_status"] == "DRAFT"
        assert after["ticketing_status"] == "TIERS_DRAFT"
        assert after["financial_clearance"] == "CLEARED"
        assert after["negotiated_fee_cents"] == 200_000

        rider_after = validate_success(
            api_client.get_tech_rider(scenario["rider"]["id"], TECH_DIRECTOR))
        assert rider_after["review_status"] == "GAP_IDENTIFIED"
        assert rider_after["capability_gaps"] == ["POWER_SHORTFALL"]

        item_after = validate_success(
            api_client.get_equipment_item(scenario["item"]["id"], ADMIN))
        assert item_after["reserved_qty"] == 1

    def test_the_same_confirmation_succeeds_once_the_rider_alone_has_moved(self):
        """Nothing about the engagement changes; only the child does. Clearing the
        rider over its reserved coverage books the equipment cost and lets the
        identical confirmation through, which is what makes the earlier refusal a
        state guard rather than a missing prerequisite.

        PRD: "On success the rider's `additional_equipment_cost_cents` is set to
        the sum of `line_cost_cents` over its `RESERVED` lines; because that
        figure changed, the engagement's `additional_equipment_cost_cents` is
        re-derived"

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_by_tech_rider_review_state
        """
        scenario = _presented_engagement_blocked_only_by_its_rider()
        engagement_id = scenario["engagement"]["id"]
        validate_error(api_client.confirm_engagement(engagement_id, DIRECTOR),
                       "ERR_RIDER_INVALID_STATE")

        cleared = clear_rider(scenario["rider"]["id"])
        assert cleared["review_status"] == "CLEARED"
        assert cleared["additional_equipment_cost_cents"] == 25_000
        assert read_engagement(engagement_id)[
            "additional_equipment_cost_cents"] == 25_000

        confirmed = confirm(engagement_id, DIRECTOR)
        assert confirmed["lifecycle_status"] == "CONFIRMED"

        item_after = validate_success(
            api_client.get_equipment_item(scenario["item"]["id"], ADMIN))
        assert item_after["reserved_qty"] == 1


class TestAcceptanceGatedByTheClearanceDimension:

    def test_a_blocked_clearance_refuses_an_otherwise_valid_acceptance(self):
        """The round is a perfectly ordinary standing offer and the engagement is a
        perfectly ordinary draft, but the clearance dimension reads BLOCKED and
        that alone refuses the agency's acceptance. None of acceptance's side
        effects leak through.

        PRD: "In both cases the engagement's clearance dimension must not be
        `BLOCKED`, or the attempt is refused with `ERR_CLEARANCE_BLOCKED`"

        Design: Difficulty/cross_entity_state_dependency/fee_negotiation_accept_gated_by_engagement_financial_clearance
        """
        scenario = _prohibitive_engagement_with_a_standing_offer()
        engagement_id = scenario["engagement"]["id"]
        artist_id = scenario["artist"]["id"]

        validate_error(api_client.accept_fee_negotiation(
            scenario["round"]["id"],
            make_artist_representative_headers(artist_id)),
            "ERR_CLEARANCE_BLOCKED", expected_status=422)

        rounds, meta = validate_paginated(
            api_client.list_fee_negotiations(engagement_id, DIRECTOR))
        assert meta["total_count"] == 1
        assert rounds[0]["status"] == "OFFERED"
        assert rounds[0]["accepted_fee_cents"] is None
        assert rounds[0]["accepted_share_pct"] is None
        assert rounds[0]["accepted_by_user_id"] is None

        after = read_engagement(engagement_id)
        assert after["lifecycle_status"] == "DRAFT"
        assert after["financial_clearance"] == "BLOCKED"
        assert after["negotiated_fee_cents"] == 0
        assert after["artist_share_pct"] == 0
        assert after["fee_accepted_by_user_id"] is None

    def test_the_block_was_derived_from_the_very_offer_it_now_refuses(self):
        """The projection that condemned the booking read the standing offer as its
        fee basis, because no round is accepted, so the parent's blocking state
        came from the child the block protects. Re-running the assessment on the
        same terms scores the same, so the acceptance stays out of reach.

        PRD: "otherwise, if any round is still `OFFERED` or `COUNTERED`, the basis
        is the `offered_fee_cents` of the round with the highest `round_index`
        among those"

        Design: Difficulty/cross_entity_state_dependency/fee_negotiation_accept_gated_by_engagement_financial_clearance
        """
        scenario = _prohibitive_engagement_with_a_standing_offer()
        engagement_id = scenario["engagement"]["id"]

        blocked = read_engagement(engagement_id)
        assert blocked["projected_gross_cents"] == 100_000
        assert blocked["projected_margin_cents"] == -650_000

        reassessed = assess_risk(engagement_id)
        assert reassessed["risk_score"] == 88
        assert reassessed["risk_tier"] == "PROHIBITIVE"
        assert reassessed["financial_clearance"] == "BLOCKED"

        validate_error(api_client.accept_fee_negotiation(
            scenario["round"]["id"],
            make_artist_representative_headers(scenario["artist"]["id"])),
            "ERR_CLEARANCE_BLOCKED")
        assert read_engagement(engagement_id)["negotiated_fee_cents"] == 0
