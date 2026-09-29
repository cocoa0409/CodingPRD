"""Trailering hulls away: the seal state that gates host confirmation, and the
rack-unit conservation invariant across assignment and release cycles.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_rack_capacity_derived,
    assert_rack_units_conserved,
    assert_regatta_entry,
    assert_trailer_load,
    validate_error,
)
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    confirm_entry,
    declare_coxed_four_lineup,
    declare_single_lineup,
    enrol_athlete,
    enrol_coxswain,
    move_trailer_to,
    open_away_regatta,
    open_entry,
    open_trailer_load,
    rack_entry,
    read_entry,
    read_trailer,
    release_rack_units,
    submit_entry,
)


@pytest.fixture
def open_load_with_one_racked_single(cast):
    """An away single racked on a trailer load that has not been sealed yet."""
    regatta = open_away_regatta()
    shell = add_single(hull_name="Voyager")
    rower = enrol_athlete("Tessa Trailer", "COMPETITIVE", 78.0)
    entry = open_entry(regatta["id"], shell["id"], cast["coach_headers"])
    entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
    entry = submit_entry(entry["id"], cast["coach_headers"])
    trailer = open_trailer_load(regatta["id"], cast["driver"]["id"], cast["boatman_headers"])
    trailer = rack_entry(trailer, entry["id"], cast["boatman_headers"])
    return {"regatta": regatta, "entry": read_entry(entry["id"]), "trailer": trailer}


@pytest.fixture
def load_with_a_four_and_a_single(cast):
    """A four at tier 1 position 1 and a single at tier 1 position 3."""
    regatta = open_away_regatta()
    four_hull = add_coxed_four(hull_name="Heron")
    cox = enrol_coxswain("Cody Cox", 55.0)
    rowers = [enrol_athlete(f"Rower {index}", "COMPETITIVE", 80.0) for index in range(1, 5)]
    four = open_entry(
        regatta["id"],
        four_hull["id"],
        cast["coach_headers"],
        event_code="M4P_OPEN",
        boat_class="4+",
        seed_time_seconds=400.0,
    )
    four = declare_coxed_four_lineup(
        four, cox["id"], [rower["id"] for rower in rowers], cast["coach_headers"]
    )
    four = submit_entry(four["id"], cast["coach_headers"])

    single_hull = add_single(hull_name="Kingfisher")
    sculler = enrol_athlete("Sam Sculler", "COMPETITIVE", 79.0)
    single = open_entry(regatta["id"], single_hull["id"], cast["coach_headers"])
    single = declare_single_lineup(single, sculler["id"], cast["coach_headers"])
    single = submit_entry(single["id"], cast["coach_headers"])

    trailer = open_trailer_load(regatta["id"], cast["driver"]["id"], cast["boatman_headers"])
    trailer = rack_entry(trailer, four["id"], cast["boatman_headers"])
    trailer = rack_entry(trailer, single["id"], cast["boatman_headers"])
    return {"four": four, "single": single, "trailer": trailer}


class TestConfirmationGatedOnSealState:
    def test_confirmation_refused_while_the_load_is_still_open(
        self, cast, open_load_with_one_racked_single
    ):
        """Being racked is not enough — the load must also be shut.

        PRD: "Confirmation requires that every `COXSWAIN` seat on the entry have
        `weigh_in_status` `PASSED` (`ERR_WEIGH_IN_NOT_PASSED`), that every seat
        be `ELIGIBLE`, and — when the regatta's `venue_kind` is `AWAY` — that the
        entry's `rack_tier` be non-null and its owning trailer load be in status
        `SEALED`, `DEPARTED` or `ARRIVED` (`ERR_ENTRY_NOT_RACKED`)."

        Design: Difficulty/cross_entity_state_dependency/entry_confirmation_gated_on_trailer_load_seal_state
        """
        scenario = open_load_with_one_racked_single
        assert scenario["entry"]["rack_tier"] == 1, (
            f"the hull is racked on tier 1, got {scenario['entry']['rack_tier']}"
        )
        assert scenario["entry"]["rack_position"] == 1, (
            f"the hull takes the first free unit, got {scenario['entry']['rack_position']}"
        )

        response = api_client.confirm_regatta_entry(
            scenario["entry"]["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_ENTRY_NOT_RACKED.value)

        entry = read_entry(scenario["entry"]["id"])
        assert entry["status"] == "SUBMITTED", (
            f"the refused entry stays SUBMITTED, got {entry['status']}"
        )

    def test_sealing_the_load_admits_the_identical_confirmation(
        self, cast, open_load_with_one_racked_single
    ):
        """Once the load is sealed the very same request succeeds.

        PRD: "`OPEN → SEALED` requires the regatta to be `OPEN_FOR_ENTRY` or
        `ENTRIES_CLOSED` — a load may be built and sealed before entries close
        but never once the regatta is `RACING` — and requires `rack_units_used`
        to be greater than zero, since the club will not seal an empty trailer."

        Design: Difficulty/cross_entity_state_dependency/entry_confirmation_gated_on_trailer_load_seal_state
        """
        scenario = open_load_with_one_racked_single
        api_client.confirm_regatta_entry(scenario["entry"]["id"], {}, cast["official_headers"])

        trailer = assert_rack_units_conserved(
            assert_trailer_load(
                move_trailer_to(
                    scenario["trailer"]["id"], "SEALED", cast["boatman_headers"]
                )
            )
        )
        assert trailer["status"] == "SEALED", (
            f"the load moves OPEN -> SEALED, got {trailer['status']}"
        )
        assert trailer["rack_units_used"] == 1, (
            f"a single occupies one rack unit, got {trailer['rack_units_used']}"
        )
        assert trailer["rack_units_free"] == 15, (
            f"fifteen of the sixteen units remain free, got {trailer['rack_units_free']}"
        )

        entry = assert_regatta_entry(
            confirm_entry(scenario["entry"]["id"], cast["official_headers"])
        )
        assert entry["status"] == "CONFIRMED", (
            f"the sealed load unblocks confirmation, got {entry['status']}"
        )
        assert entry["total_fee_cents"] == 9500, (
            "an away single is 4500 to enter plus a 5000-cent levy on its one rack "
            f"unit, got {entry['total_fee_cents']}"
        )
        assert entry["trailer_load_id"] == scenario["trailer"]["id"], (
            "the entry still names its load, got "
            f"{entry['trailer_load_id']}"
        )


class TestRackUnitConservation:
    def test_releases_hand_every_unit_back_to_the_load(self, cast, load_with_a_four_and_a_single):
        """Each release recomputes both counters and clears the entry's placement.

        PRD: "Releasing an entry's units, again under
        `expected_trailer_load_version`, resets that entry's `rack_tier`,
        `rack_position` and `trailer_load_id` to null and recomputes both
        counters. Both operations increment the load's `version` by one."

        Design: Difficulty/compensating_invariant/rack_units_conserved_across_assignment_release_cycles
        """
        scenario = load_with_a_four_and_a_single
        trailer = assert_rack_capacity_derived(
            assert_rack_units_conserved(scenario["trailer"])
        )
        assert trailer["rack_unit_capacity"] == 16, (
            f"four tiers of four units is a capacity of 16, got {trailer['rack_unit_capacity']}"
        )
        assert trailer["rack_units_used"] == 3, (
            "a four takes two units and a single takes one, got "
            f"{trailer['rack_units_used']}"
        )

        trailer = assert_rack_units_conserved(
            release_rack_units(trailer, scenario["four"]["id"], cast["boatman_headers"])
        )
        assert trailer["rack_units_used"] == 1, (
            f"releasing the four hands back two units, got {trailer['rack_units_used']}"
        )
        assert trailer["rack_units_free"] == 15, (
            f"fifteen units are free again, got {trailer['rack_units_free']}"
        )
        four = read_entry(scenario["four"]["id"])
        assert four["rack_tier"] is None, f"the tier is cleared, got {four['rack_tier']}"
        assert four["rack_position"] is None, (
            f"the position is cleared, got {four['rack_position']}"
        )

        trailer = assert_rack_units_conserved(
            release_rack_units(trailer, scenario["single"]["id"], cast["boatman_headers"])
        )
        assert trailer["rack_units_used"] == 0, (
            f"the load is empty again, got {trailer['rack_units_used']}"
        )
        assert trailer["rack_units_free"] == 16, (
            f"the whole capacity is free, got {trailer['rack_units_free']}"
        )
        single = read_entry(scenario["single"]["id"])
        assert single["trailer_load_id"] is None, (
            f"the released entry no longer names a load, got {single['trailer_load_id']}"
        )

    def test_a_released_slot_is_reissued_without_drift(self, cast, load_with_a_four_and_a_single):
        """The waterfall hands back exactly the placement it gave out before.

        PRD: "The first tier-and-start pair whose whole run of positions is free
        wins: `rack_tier` records the 1-based tier index, `rack_position` records
        the 1-based first occupied unit position within that tier, and
        `trailer_load_id` records the load."

        Design: Difficulty/compensating_invariant/rack_units_conserved_across_assignment_release_cycles
        """
        scenario = load_with_a_four_and_a_single
        baseline_version = scenario["trailer"]["version"]
        trailer = release_rack_units(
            scenario["trailer"], scenario["four"]["id"], cast["boatman_headers"]
        )
        trailer = release_rack_units(trailer, scenario["single"]["id"], cast["boatman_headers"])
        trailer = assert_rack_units_conserved(
            rack_entry(trailer, scenario["four"]["id"], cast["boatman_headers"])
        )

        four = read_entry(scenario["four"]["id"])
        assert four["rack_tier"] == 1, (
            f"the four rides low, back on tier 1, got {four['rack_tier']}"
        )
        assert four["rack_position"] == 1, (
            f"the first contiguous run is again position 1, got {four['rack_position']}"
        )
        assert trailer["rack_units_used"] == 2, (
            f"the four occupies two units, got {trailer['rack_units_used']}"
        )
        assert trailer["rack_units_free"] == 14, (
            f"fourteen units are free, got {trailer['rack_units_free']}"
        )

        trailer = assert_rack_units_conserved(
            release_rack_units(trailer, scenario["four"]["id"], cast["boatman_headers"])
        )
        assert trailer["rack_units_used"] == 0, (
            f"the load closes back at empty, got {trailer['rack_units_used']}"
        )
        assert trailer["rack_units_free"] == 16, (
            f"the whole capacity is free, got {trailer['rack_units_free']}"
        )
        final = read_trailer(trailer["id"])
        assert final["version"] == baseline_version + 4, (
            "each of the two releases, the re-assignment and the final release "
            f"bumps the version once, expected {baseline_version + 4}, got "
            f"{final['version']}"
        )
