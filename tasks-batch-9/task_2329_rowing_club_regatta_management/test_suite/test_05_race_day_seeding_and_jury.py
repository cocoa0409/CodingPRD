"""Race day: seeding a heat from the confirmed pool, and the jury's remand cycle
bounded at two review rounds.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_heat,
    assert_heat_lane_counts_conserved,
    assert_protest,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_single,
    build_filed_protest,
    drive_regatta_to_racing,
    enrol_athlete,
    make_submitted_single_entry,
    open_regatta,
    open_review,
    read_entry,
    read_heat,
    read_protest,
    read_regatta,
    rule_on_protest,
    schedule_heat,
)

RACING_CLOCK = "2026-08-12T09:00:00Z"


@pytest.fixture
def heat_with_no_confirmed_crews(cast):
    """A racing regatta whose only entry stopped at SUBMITTED."""
    regatta = open_regatta()
    shell = add_single(hull_name="Kingfisher")
    rower = enrol_athlete("Rower 1", "COMPETITIVE", 80.0)
    heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=4)
    entry = make_submitted_single_entry(regatta, shell, rower["id"], cast["coach_headers"])
    drive_regatta_to_racing(regatta, racing_clock=RACING_CLOCK)
    return {"regatta": regatta, "heat": heat, "entry": entry}


@pytest.fixture
def twice_remanded_protest(cast):
    """A protest carried through two full review rounds and remanded again."""
    scenario = build_filed_protest(cast)
    protest_id = scenario["protest"]["id"]
    open_review(protest_id, cast["chair_headers"])
    rule_on_protest(protest_id, "REMAND", cast["chair_headers"])
    scenario["protest"] = open_review(protest_id, cast["chair_headers"])
    return scenario


class TestSeedingWithAnEmptyCandidatePool:
    def test_seeding_refuses_a_pool_of_zero_confirmed_entries(
        self, cast, heat_with_no_confirmed_crews
    ):
        """Only entries sitting at exactly CONFIRMED are candidates.

        PRD: "The candidate pool is every entry whose `regatta_id` matches the
        heat's regatta, whose `event_code` matches the heat's event code, and
        whose status is exactly `CONFIRMED`; entries in any other status are
        excluded. An empty pool is rejected with `ERR_NO_ELIGIBLE_ENTRIES`."

        Design: Difficulty/boundary_precision_check/assign_lanes_with_zero_confirmed_candidates_returns_409
        """
        response = api_client.assign_lanes(
            heat_with_no_confirmed_crews["heat"]["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES.value)

        entry = read_entry(heat_with_no_confirmed_crews["entry"]["id"])
        assert entry["status"] == "SUBMITTED", (
            "the unconfirmed entry is left exactly where it was, got "
            f"{entry['status']}"
        )

    def test_refused_seeding_writes_no_lanes(self, cast, heat_with_no_confirmed_crews):
        """A rejected draw leaves every lane on the heat free.

        PRD: "A new heat is `SCHEDULED` with `occupied_lane_count` 0,
        `free_lane_count` equal to `lane_count`, and `protest_window_closes_at`
        null."

        Design: Difficulty/boundary_precision_check/assign_lanes_with_zero_confirmed_candidates_returns_409
        """
        heat_id = heat_with_no_confirmed_crews["heat"]["id"]
        api_client.assign_lanes(heat_id, {}, cast["official_headers"])

        heat = assert_heat_lane_counts_conserved(assert_heat(read_heat(heat_id)))
        assert heat["status"] == "SCHEDULED", (
            f"the heat stays SCHEDULED after a refused draw, got {heat['status']}"
        )
        assert heat["occupied_lane_count"] == 0, (
            f"no lane is occupied, got {heat['occupied_lane_count']}"
        )
        assert heat["free_lane_count"] == 4, (
            f"all four buoyed lanes remain free, got {heat['free_lane_count']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_race_lanes(cast["official_headers"], {"heat_id": heat_id})
        )
        assert meta["total_count"] == 0, (
            f"the refused draw created no lane rows, got {meta['total_count']}"
        )


class TestJuryRemandCycle:
    def test_remanded_protest_reopens_for_a_second_review_round(
        self, cast, twice_remanded_protest
    ):
        """Reopening a remanded protest counts as a further round.

        PRD: "Opening increments `review_round` by one, stamps `jury_user_id`
        with the acting chair, and moves the protest to `UNDER_JURY_REVIEW` —
        `FILED → UNDER_JURY_REVIEW` or `REMANDED → UNDER_JURY_REVIEW`."

        Design: Difficulty/non_linear_state_machine/protest_remand_reopen_cycle_capped_at_two_rounds
        """
        protest = assert_protest(twice_remanded_protest["protest"])
        assert protest["status"] == "UNDER_JURY_REVIEW", (
            f"the reopened protest is UNDER_JURY_REVIEW, got {protest['status']}"
        )
        assert protest["review_round"] == 2, (
            "two openings have happened, so review_round reads 2, got "
            f"{protest['review_round']}"
        )
        assert protest["jury_user_id"] == cast["chair"]["id"], (
            "the acting chair is stamped on the protest, expected "
            f"{cast['chair']['id']}, got {protest['jury_user_id']}"
        )

    def test_a_third_remand_is_capped_at_two_review_rounds(self, cast, twice_remanded_protest):
        """The negotiation cycle is bounded at two rounds in total.

        PRD: "A `decision` of `REMAND` sends the matter back for a further
        round, permitted only while `review_round` is strictly below two
        (`ERR_MAX_JURY_ROUNDS_EXCEEDED`)."

        Design: Difficulty/non_linear_state_machine/protest_remand_reopen_cycle_capped_at_two_rounds
        """
        protest_id = twice_remanded_protest["protest"]["id"]
        response = api_client.rule_on_protest(
            protest_id,
            {"decision": "REMAND", "rationale": "the jury wants a third look"},
            cast["chair_headers"],
        )
        validate_error(response, ApiErrorId.ERR_MAX_JURY_ROUNDS_EXCEEDED.value)

        protest = assert_protest(read_protest(protest_id))
        assert protest["status"] == "UNDER_JURY_REVIEW", (
            f"the rejected ruling leaves the protest under review, got {protest['status']}"
        )
        assert protest["review_round"] == 2, (
            f"the rejected ruling does not move the round counter, got {protest['review_round']}"
        )
        assert protest["deposit_cents"] == 5000, (
            f"the 5000-cent deposit is still held, got {protest['deposit_cents']}"
        )
        assert protest["deposit_refunded"] is False, (
            f"a remand leaves the deposit held, got {protest['deposit_refunded']}"
        )
        regatta = read_regatta(twice_remanded_protest["regatta"]["id"])
        assert regatta["deposit_held_cents"] == 5000, (
            "the regatta still holds the single live deposit, got "
            f"{regatta['deposit_held_cents']}"
        )
        heat = read_heat(twice_remanded_protest["heat"]["id"])
        assert heat["status"] == "RESULTS_PROVISIONAL", (
            f"the results stay provisional throughout the jury cycle, got {heat['status']}"
        )
