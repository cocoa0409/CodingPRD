"""State machines that are not walked once in a line: the negotiation round that
returns to a state it already occupied until a ceiling stops it, and the rider
review that forks three ways with two arms rejoining on different consequences.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    book_presented_engagement,
    book_rental_engagement,
    clear_rider,
    counter_round,
    make_rental_client_contact_headers,
    open_negotiation_round,
    read_engagement,
    register_artist,
    register_equipment_item,
    register_hall,
    register_rental_client,
    reserve_equipment_line,
    review_rider,
    revise_round,
    submit_rider,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["programming_director_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
ADMIN = TEST_USERS["center_admin_headers"]


def _draft_presented_engagement_with_an_open_round() -> dict:
    """A DRAFT presented engagement and one round standing at 1,200,000 against
    a guarantee floor of 1,000,000."""
    space = register_hall()
    artist = register_artist(legal_name="Halcyon Quartet",
                            guarantee_floor_cents=1_000_000,
                            historical_sell_through_pct=0.70,
                            min_days_between_engagements=0)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Halcyon Quartet",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    opened = open_negotiation_round(engagement["id"], 1_200_000, 0.10)
    assert opened["status"] == "OFFERED"
    assert opened["round_index"] == 1
    assert opened["revision_count"] == 0
    return {"artist": artist, "engagement": engagement, "round": opened}


def _three_rental_engagements_on_the_three_review_branches() -> dict:
    """One hall, one credit-B client already in arrears, and three rental
    engagements whose riders take the capable, gap-identified and infeasible arms
    of the review fork."""
    space = register_hall()
    client = register_rental_client(org_name="Lakeside Choral Society",
                                   contact_email="ops@lakeside.example",
                                   credit_rating="B",
                                   outstanding_balance_cents=25_000)
    item = register_equipment_item(category="POWER_DISTRO",
                                   model_name="400A Company Switch Cart",
                                   on_hand_qty=5, daily_rate_cents=25_000,
                                   replacement_value_cents=4_000_000)
    contact = make_rental_client_contact_headers(client["id"])
    windows = (
        ("Lakeside Choral: Autumn Concert", "2026-10-01T08:00:00Z",
         "2026-10-02T19:00:00Z", "2026-10-02T22:00:00Z", "2026-10-03T02:00:00Z"),
        ("Lakeside Choral: Winter Concert", "2026-10-06T08:00:00Z",
         "2026-10-07T19:00:00Z", "2026-10-07T22:00:00Z", "2026-10-08T02:00:00Z"),
        ("Lakeside Choral: Spring Gala", "2026-10-12T08:00:00Z",
         "2026-10-13T19:00:00Z", "2026-10-13T22:00:00Z", "2026-10-14T02:00:00Z"),
    )
    engagements = []
    for title, load_in, start, end, load_out in windows:
        engagement = book_rental_engagement(
            space["id"], client["id"], title=title,
            load_in_start_utc=load_in, performance_start_utc=start,
            performance_end_utc=end, load_out_end_utc=load_out,
            performance_day_count=2, load_in_day_count=1)
        assert engagement["facility_fee_cents"] == 1_200_000
        assert engagement["deposit_required_cents"] == 600_000
        engagements.append(engagement)

    capable = submit_rider(engagements[0]["id"], contact,
                           submitted_rigging_kg=3_000,
                           requested_power_amps=300,
                           requested_dmx_universes=2)
    gapped = submit_rider(engagements[1]["id"], contact,
                          submitted_rigging_kg=3_000,
                          requested_power_amps=500,
                          requested_dmx_universes=2)
    infeasible = submit_rider(engagements[2]["id"], contact,
                             submitted_rigging_kg=6_000,
                             requested_power_amps=300,
                             requested_dmx_universes=2)
    capable = review_rider(capable["id"])
    gapped = review_rider(gapped["id"])
    infeasible = review_rider(infeasible["id"])
    assert capable["review_status"] == "CAPABLE"
    assert gapped["review_status"] == "GAP_IDENTIFIED"
    assert infeasible["review_status"] == "REJECTED_INFEASIBLE"

    capable = clear_rider(capable["id"])
    line = reserve_equipment_line(gapped["id"], item["id"],
                                  covers_gap="POWER_SHORTFALL", qty=2,
                                  rental_days=2)
    assert line["line_cost_cents"] == 100_000
    return {
        "engagements": engagements,
        "item": item,
        "capable_rider": capable,
        "gapped_rider": gapped,
        "infeasible_rider": infeasible,
    }


class TestNegotiationOfferCounterCycle:

    def test_each_revision_returns_the_round_to_offered_on_fresh_terms(self):
        """The round occupies OFFERED three times over on three different
        guarantees. Every revision overwrites the offered terms, wipes the
        counter the agency had filled in and advances the revision counter, so
        the return to OFFERED is a genuine repeat rather than a relabelling.

        PRD: "The director may then answer a counter by revising the offer, which
        drives the round `COUNTERED → OFFERED`, overwrites `offered_fee_cents`
        and `offered_artist_share_pct` with the new terms, increments
        `revision_count` by 1, and resets both counter fields back to null"

        Design: Difficulty/non_linear_state_machine/fee_negotiation_offer_counter_cycle_with_revision_ceiling
        """
        scenario = _draft_presented_engagement_with_an_open_round()
        artist_id = scenario["artist"]["id"]
        round_id = scenario["round"]["id"]
        assert scenario["round"]["counter_fee_cents"] is None

        countered = counter_round(round_id, artist_id, 1_800_000, 0.15)
        assert countered["status"] == "COUNTERED"
        assert countered["counter_fee_cents"] == 1_800_000

        first_revision = revise_round(round_id, 1_400_000, 0.12)
        assert first_revision["status"] == "OFFERED"
        assert first_revision["offered_fee_cents"] == 1_400_000
        assert first_revision["revision_count"] == 1
        assert first_revision["counter_fee_cents"] is None
        assert first_revision["counter_artist_share_pct"] is None

        countered_again = counter_round(round_id, artist_id, 1_750_000, 0.14)
        assert countered_again["status"] == "COUNTERED"
        assert countered_again["counter_fee_cents"] == 1_750_000

        second_revision = revise_round(round_id, 1_500_000, 0.13)
        assert second_revision["status"] == "OFFERED"
        assert second_revision["offered_fee_cents"] == 1_500_000
        assert second_revision["revision_count"] == 2
        assert second_revision["counter_fee_cents"] is None
        assert second_revision["counter_artist_share_pct"] is None
        assert second_revision["round_index"] == 1

        engagement_after = read_engagement(scenario["engagement"]["id"])
        assert engagement_after["negotiation_round_count"] == 1
        assert engagement_after["negotiated_fee_cents"] == 0
        assert engagement_after["fee_accepted_by_user_id"] is None

    def test_the_third_revision_inside_one_round_is_refused_outright(self):
        """Two revisions exhaust the round's allowance. With the round sitting at
        COUNTERED for the third time, a third revision is refused and leaves no
        partial write: the offered terms are still the second revision's and the
        agency's last counter still stands beside them.

        PRD: "a revision is permitted only while `revision_count` is strictly
        less than 2, so at most two revisions may occur within one round, and the
        third attempt is refused with `ERR_NEGOTIATION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/fee_negotiation_offer_counter_cycle_with_revision_ceiling
        """
        scenario = _draft_presented_engagement_with_an_open_round()
        artist_id = scenario["artist"]["id"]
        engagement_id = scenario["engagement"]["id"]
        round_id = scenario["round"]["id"]

        counter_round(round_id, artist_id, 1_800_000, 0.15)
        revise_round(round_id, 1_400_000, 0.12)
        counter_round(round_id, artist_id, 1_750_000, 0.14)
        revise_round(round_id, 1_500_000, 0.13)
        counter_round(round_id, artist_id, 1_700_000, 0.14)

        validate_error(api_client.revise_fee_offer(
            round_id,
            {"offered_fee_cents": 1_600_000, "offered_artist_share_pct": 0.13},
            DIRECTOR), "ERR_NEGOTIATION_ROUND_LIMIT")

        rounds, meta = validate_paginated(
            api_client.list_fee_negotiations(engagement_id, DIRECTOR))
        assert meta["total_count"] == 1
        standing = rounds[0]
        assert standing["status"] == "COUNTERED"
        assert standing["revision_count"] == 2
        assert standing["round_index"] == 1
        assert standing["offered_fee_cents"] == 1_500_000
        assert standing["offered_artist_share_pct"] == 0.13
        assert standing["counter_fee_cents"] == 1_700_000
        assert standing["counter_artist_share_pct"] == 0.14

        engagement_after = read_engagement(engagement_id)
        assert engagement_after["negotiation_round_count"] == 1
        assert engagement_after["negotiated_fee_cents"] == 0
        assert engagement_after["fee_accepted_by_user_id"] is None


class TestRiderReviewForkAndJoin:

    def test_the_two_clearable_branches_rejoin_carrying_different_consequences(self):
        """Both riders end up CLEARED, but only the gap branch propagates money:
        it keeps its diagnosis, books the equipment that covers the shortfall and
        pushes the engagement's deposit up by the whole undiscounted cost, while
        the capable branch leaves its engagement's deposit exactly where creation
        put it.

        PRD: "Clearing from `CAPABLE` moves the rider `CAPABLE → CLEARED`, sets
        the rider's `additional_equipment_cost_cents` to 0, re-derives the
        engagement's `additional_equipment_cost_cents` (which this branch leaves
        unchanged), leaves `deposit_required_cents` untouched"

        Design: Difficulty/non_linear_state_machine/tech_rider_review_three_way_fork_and_divergent_join
        """
        scenario = _three_rental_engagements_on_the_three_review_branches()
        capable_engagement, gapped_engagement, _ = scenario["engagements"]

        cleared_gap = validate_success(api_client.clear_tech_rider(
            scenario["gapped_rider"]["id"], TECH_DIRECTOR))
        assert cleared_gap["review_status"] == "CLEARED"
        assert cleared_gap["capability_gaps"] == ["POWER_SHORTFALL"]
        assert cleared_gap["additional_equipment_cost_cents"] == 100_000

        gapped_after = read_engagement(gapped_engagement["id"])
        assert gapped_after["additional_equipment_cost_cents"] == 100_000
        assert gapped_after["deposit_required_cents"] == 700_000

        capable_after_read = validate_success(api_client.get_tech_rider(
            scenario["capable_rider"]["id"], TECH_DIRECTOR))
        assert capable_after_read["review_status"] == "CLEARED"
        assert capable_after_read["capability_gaps"] == []
        assert capable_after_read["additional_equipment_cost_cents"] == 0

        capable_after = read_engagement(capable_engagement["id"])
        assert capable_after["additional_equipment_cost_cents"] == 0
        assert capable_after["deposit_required_cents"] == 600_000

    def test_the_infeasible_arm_never_reaches_the_join_and_capable_takes_no_lines(self):
        """The rigging rejection is terminal, so that arm can never be cleared;
        and because equipment lines are admitted only while a rider reads
        GAP_IDENTIFIED, the capable arm cannot acquire cost after the fact. The
        one reservation that exists belongs to the gap arm alone.

        PRD: "That state is terminal — an infeasible rider can never be cleared,
        and because confirmation requires a cleared rider, the engagement can
        never be confirmed on it."

        Design: Difficulty/non_linear_state_machine/tech_rider_review_three_way_fork_and_divergent_join
        """
        scenario = _three_rental_engagements_on_the_three_review_branches()
        infeasible = validate_success(api_client.get_tech_rider(
            scenario["infeasible_rider"]["id"], TECH_DIRECTOR))
        assert infeasible["review_status"] == "REJECTED_INFEASIBLE"
        assert infeasible["capability_gaps"] == ["RIGGING_OVER_CAPACITY"]

        validate_error(api_client.clear_tech_rider(
            scenario["infeasible_rider"]["id"], TECH_DIRECTOR),
            "ERR_RIDER_INVALID_STATE")
        validate_error(api_client.create_equipment_line(
            scenario["capable_rider"]["id"],
            {"equipment_item_id": scenario["item"]["id"],
             "covers_gap": "POWER_SHORTFALL", "qty": 1, "rental_days": 1},
            TECH_DIRECTOR), "ERR_RIDER_INVALID_STATE")

        item_after = validate_success(
            api_client.get_equipment_item(scenario["item"]["id"], ADMIN))
        assert item_after["reserved_qty"] == 2

        lines, meta = validate_paginated(
            api_client.list_equipment_item_rental_lines(scenario["item"]["id"],
                                                        ADMIN))
        assert meta["total_count"] == 1
        assert lines[0]["tech_rider_id"] == scenario["gapped_rider"]["id"]
