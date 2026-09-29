"""The two optimistic-concurrency guards, the version counter they both lean on, and
the immediacy of the fee ledger: a stale lineup snapshot, a stale rack snapshot, and
a submission whose figures are already settled in the response that made them.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_rack_units_conserved,
    assert_regatta,
    assert_regatta_entry,
    assert_trailer_load,
    validate_error,
    validate_success,
)
from test_helpers.factories import lineup_payload, seat
from test_helpers.fixtures import (
    add_single,
    declare_single_lineup,
    enrol_athlete,
    make_submitted_single_entry,
    open_away_regatta,
    open_entry,
    open_regatta,
    open_trailer_load,
    rack_entry,
    read_entry,
    read_regatta,
    read_trailer,
    seats_of_entry,
    set_clock_to,
    submit_entry,
)

SECOND_WRITE_CLOCK = "2026-08-02T00:00:00Z"
SINGLE_HOME_FEE_CENTS = 4500
DEFAULT_RACK_CAPACITY = 16


@pytest.fixture
def declared_entry_with_a_superseded_snapshot(cast):
    """A 1X entry declared once, leaving the coach's original snapshot stale."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    shell = add_single(hull_name="Kingfisher")
    first = enrol_athlete("Row One", "COMPETITIVE", 82.0)
    second = enrol_athlete("Row Two", "COMPETITIVE", 83.0)
    entry = open_entry(
        regatta["id"], shell["id"], cast["coach_headers"], seed_time_seconds=380.0
    )
    stale_version = entry["version"]
    declared = declare_single_lineup(entry, first["id"], cast["coach_headers"])
    return {
        "regatta": regatta,
        "entry": declared,
        "stale_version": stale_version,
        "first": first,
        "second": second,
    }


@pytest.fixture
def away_load_with_one_hull_racked(cast):
    """An away load carrying entry A, with entry B still waiting on the dock."""
    regatta = open_away_regatta(name="Lakeside Sprints", host_club="Lakeside RC")
    shell_a = add_single(hull_name="Kingfisher", hull_weight_kg=14.0, home_bay="BAY-1")
    shell_b = add_single(hull_name="Heron", hull_weight_kg=14.5, home_bay="BAY-2")
    rower_a = enrol_athlete("Row One", "COMPETITIVE", 82.0)
    rower_b = enrol_athlete("Row Two", "COMPETITIVE", 83.0)
    entry_a = make_submitted_single_entry(
        regatta, shell_a, rower_a["id"], cast["coach_headers"], seed_time_seconds=370.0
    )
    entry_b = make_submitted_single_entry(
        regatta, shell_b, rower_b["id"], cast["coach_headers"], seed_time_seconds=390.0
    )
    trailer = open_trailer_load(
        regatta["id"],
        cast["driver"]["id"],
        cast["boatman_headers"],
        tow_vehicle_code="TOW-1",
        depart_at="2026-08-11T12:00:00Z",
    )
    stale_version = trailer["version"]
    rack_entry(trailer, entry_a["id"], cast["boatman_headers"])
    return {
        "regatta": regatta,
        "entry_a": entry_a,
        "entry_b": entry_b,
        "trailer": read_trailer(trailer["id"]),
        "stale_version": stale_version,
    }


class TestLineupSnapshotConcurrency:
    def test_a_replayed_lineup_declaration_is_refused_and_writes_nothing(
        self, cast, declared_entry_with_a_superseded_snapshot
    ):
        """The self-loop is guarded, so a coach's pre-declaration view cannot be replayed.

        PRD: "If that value does not equal the entry's current `version`, the
        declaration is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412) and nothing
        is written."

        Design: Corner/complexity_layers/corner_stale_entry_version_on_lineup_redeclaration_returns_412
        """
        scenario = declared_entry_with_a_superseded_snapshot
        entry = scenario["entry"]
        assert entry["status"] == "LINEUP_DECLARED", (
            f"the accepted declaration moved the entry, got {entry['status']}"
        )
        assert entry["version"] == scenario["stale_version"] + 1, (
            "the accepted declaration cost exactly one version, expected "
            f"{scenario['stale_version'] + 1}, got {entry['version']}"
        )

        response = api_client.declare_lineup(
            entry["id"],
            lineup_payload(
                scenario["stale_version"],
                [seat(scenario["second"]["id"], 1, "ROWER")],
            ),
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STALE_ENTRY_VERSION.value)

        seats = seats_of_entry(entry["id"])
        assert len(seats) == 1, (
            f"the accepted declaration's single seat is all there is, got {len(seats)}"
        )
        assert seats[0]["member_id"] == scenario["first"]["id"], (
            "and it still holds the rower who was actually declared, expected "
            f"{scenario['first']['id']}, got {seats[0]['member_id']}"
        )
        stored = assert_regatta_entry(read_entry(entry["id"]))
        assert stored["version"] == entry["version"], (
            "the refused declaration consumed no version, expected "
            f"{entry['version']}, got {stored['version']}"
        )


class TestRackSnapshotConcurrency:
    def test_a_stale_capacity_view_is_refused_even_with_fifteen_units_free(
        self, cast, away_load_with_one_hull_racked
    ):
        """The rejection is keyed on the version, not on the free-unit count.

        PRD: "A value that does not equal the load's current `version` is rejected
        with `ERR_STALE_TRAILER_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/corner_stale_trailer_version_on_second_rack_assignment_returns_412
        """
        scenario = away_load_with_one_hull_racked
        trailer = scenario["trailer"]

        response = api_client.create_rack_assignment(
            trailer["id"],
            {
                "regatta_entry_id": scenario["entry_b"]["id"],
                "expected_trailer_load_version": scenario["stale_version"],
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STALE_TRAILER_VERSION.value)

        stored = assert_rack_units_conserved(
            assert_trailer_load(read_trailer(trailer["id"]))
        )
        assert stored["version"] == trailer["version"], (
            "the refused assignment consumed no version, expected "
            f"{trailer['version']}, got {stored['version']}"
        )
        assert stored["rack_units_used"] == 1, (
            f"only the one single is aboard, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == DEFAULT_RACK_CAPACITY - 1, (
            "fifteen of the sixteen units were free the whole time, got "
            f"{stored['rack_units_free']}"
        )
        entry_b = assert_regatta_entry(read_entry(scenario["entry_b"]["id"]))
        assert entry_b["trailer_load_id"] is None, (
            f"no allocation leaked through, got {entry_b['trailer_load_id']}"
        )
        assert entry_b["rack_tier"] is None, (
            f"and the entry holds no tier, got {entry_b['rack_tier']}"
        )

    def test_the_same_assignment_lands_once_the_snapshot_is_refreshed(
        self, cast, away_load_with_one_hull_racked
    ):
        """Nothing was wrong with the allocation itself, only with the client's view.

        PRD: "The first tier-and-start pair whose whole run of positions is free
        wins: `rack_tier` records the 1-based tier index, `rack_position` records the
        1-based first occupied unit position within that tier, and `trailer_load_id`
        records the load."

        Design: Corner/complexity_layers/corner_stale_trailer_version_on_second_rack_assignment_returns_412
        """
        scenario = away_load_with_one_hull_racked
        rack_entry(scenario["trailer"], scenario["entry_b"]["id"], cast["boatman_headers"])

        entry_b = assert_regatta_entry(read_entry(scenario["entry_b"]["id"]))
        assert entry_b["rack_tier"] == 1, (
            f"the waterfall starts at tier 1, got {entry_b['rack_tier']}"
        )
        assert entry_b["rack_position"] == 2, (
            "position 1 of tier 1 is taken, so the second single starts at position 2, "
            f"got {entry_b['rack_position']}"
        )
        assert entry_b["trailer_load_id"] == scenario["trailer"]["id"], (
            f"and the entry records its load, got {entry_b['trailer_load_id']}"
        )

        stored = assert_rack_units_conserved(
            assert_trailer_load(read_trailer(scenario["trailer"]["id"]))
        )
        assert stored["rack_units_used"] == 2, (
            f"two singles occupy one unit each, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == DEFAULT_RACK_CAPACITY - 2, (
            f"leaving fourteen free, got {stored['rack_units_free']}"
        )
        assert stored["version"] == scenario["trailer"]["version"] + 1, (
            "the accepted assignment costs exactly one version, expected "
            f"{scenario['trailer']['version'] + 1}, got {stored['version']}"
        )


class TestEntryVersionCounter:
    def test_each_accepted_write_to_an_entry_costs_exactly_one_version(self, cast):
        """Create, declare, submit — one, two, three, with the stamps to match.

        PRD: "`version`, an integer that starts at 1 on creation and increments by
        one on every mutation of that resource, including mutations the server
        performs on its own initiative when a cascade reaches the resource."

        Design: Corner/complexity_layers/corner_entry_version_increments_on_every_write
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)

        created = assert_regatta_entry(
            open_entry(
                regatta["id"], shell["id"], cast["coach_headers"], seed_time_seconds=380.0
            )
        )
        assert created["version"] == 1, (
            f"a freshly opened entry sits at version 1, got {created['version']}"
        )

        set_clock_to(SECOND_WRITE_CLOCK)
        declared = assert_regatta_entry(
            declare_single_lineup(created, rower["id"], cast["coach_headers"])
        )
        assert declared["version"] == 2, (
            f"the declaration is the second write, got {declared['version']}"
        )
        assert declared["status"] == "LINEUP_DECLARED", (
            f"and it moves the entry, got {declared['status']}"
        )

        submitted = assert_regatta_entry(
            submit_entry(created["id"], cast["coach_headers"])
        )
        assert submitted["version"] == 3, (
            f"the submission is the third write, got {submitted['version']}"
        )
        assert submitted["status"] == "SUBMITTED", (
            f"and moves the entry to the host, got {submitted['status']}"
        )
        assert submitted["total_fee_cents"] == SINGLE_HOME_FEE_CENTS, (
            "an on-time single at a home regatta owes 4500 cents, got "
            f"{submitted['total_fee_cents']}"
        )

        stored = assert_regatta_entry(read_entry(created["id"]))
        assert stored["version"] == 3, (
            f"the read-back agrees at version 3, got {stored['version']}"
        )
        assert stored["created_at"] == created["created_at"], (
            "the creation stamp never moves, expected "
            f"{created['created_at']}, got {stored['created_at']}"
        )
        assert stored["updated_at"].startswith("2026-08-02T00:00:00"), (
            "while updated_at has advanced to the clock the later writes ran under, "
            f"got {stored['updated_at']}"
        )


class TestImmediateFeeLedgerVisibility:
    def test_the_submission_response_already_carries_the_settled_fee(self, cast):
        """No settling period: the figures are right in the response that assessed them.

        PRD: "Submission stamps `submitted_at` from the logical clock, assesses the
        fee, moves every `COXSWAIN` seat's `weigh_in_status` from `NOT_REQUIRED` to
        `PENDING`, recomputes the regatta's `net_fee_cents`, and moves the entry
        `LINEUP_DECLARED → SUBMITTED`."

        Design: Corner/consistency_model/corner_immediate_visibility_of_fee_ledger_after_submit
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        entry = open_entry(
            regatta["id"], shell["id"], cast["coach_headers"], seed_time_seconds=380.0
        )
        declare_single_lineup(entry, rower["id"], cast["coach_headers"])

        submitted = assert_regatta_entry(
            validate_success(
                api_client.submit_regatta_entry(entry["id"], {}, cast["coach_headers"])
            )
        )
        assert submitted["base_fee_cents"] == SINGLE_HOME_FEE_CENTS, (
            f"a 1X is assessed 4500 cents, got {submitted['base_fee_cents']}"
        )
        assert submitted["transport_levy_cents"] == 0, (
            f"a home regatta levies no transport, got {submitted['transport_levy_cents']}"
        )
        assert submitted["late_fee_cents"] == 0, (
            f"the submission beat the deadline, got {submitted['late_fee_cents']}"
        )
        assert submitted["total_fee_cents"] == SINGLE_HOME_FEE_CENTS, (
            f"so the total is the base alone, got {submitted['total_fee_cents']}"
        )
        assert submitted["refund_cents"] is None, (
            f"nothing has been scratched, so no refund is computed, got {submitted['refund_cents']}"
        )

    def test_the_regatta_ledger_reads_the_same_immediately_and_again(self, cast):
        """The aggregate is recomputed inside the submitting request, not afterwards.

        PRD: "Derived aggregates are recomputed as part of the same request, never
        lazily: a member's `dues_balance_cents`, `logged_session_count` and
        `boathouse_access_level`; a hull's `condition_index_conservative` and
        `condition_index_optimistic`; a heat's `occupied_lane_count` and
        `free_lane_count`; a trailer's `rack_units_used` and `rack_units_free`; and a
        regatta's `net_fee_cents` and `deposit_held_cents`."

        Design: Corner/consistency_model/corner_immediate_visibility_of_fee_ledger_after_submit
        """
        regatta = assert_regatta(open_regatta(name="Club Head Race", host_club="Home RC"))
        assert regatta["net_fee_cents"] == 0, (
            f"a new regatta's ledger opens empty, got {regatta['net_fee_cents']}"
        )
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        entry = open_entry(
            regatta["id"], shell["id"], cast["coach_headers"], seed_time_seconds=380.0
        )
        declare_single_lineup(entry, rower["id"], cast["coach_headers"])
        submit_entry(entry["id"], cast["coach_headers"])

        first_read = assert_regatta(read_regatta(regatta["id"]))
        assert first_read["net_fee_cents"] == SINGLE_HOME_FEE_CENTS, (
            "the one submitted entry's 4500 cents is already in the ledger, got "
            f"{first_read['net_fee_cents']}"
        )
        assert first_read["deposit_held_cents"] == 0, (
            f"no protest deposit is held, got {first_read['deposit_held_cents']}"
        )

        second_read = assert_regatta(read_regatta(regatta["id"]))
        assert second_read["net_fee_cents"] == first_read["net_fee_cents"], (
            "a second read returns the same figure, so nothing converged after the "
            f"fact: {first_read['net_fee_cents']} against {second_read['net_fee_cents']}"
        )
        assert second_read["deposit_held_cents"] == first_read["deposit_held_cents"], (
            "and the deposit figure is equally settled: "
            f"{first_read['deposit_held_cents']} against {second_read['deposit_held_cents']}"
        )
        assert second_read["version"] == first_read["version"], (
            "reading the ledger is not itself a mutation, got "
            f"{second_read['version']} against {first_read['version']}"
        )
