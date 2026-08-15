"""Program elections: supersede cycle, election-window temporal gate, and
OCC stale-version rejection (PRD §3.4, §2.6)."""
import pytest

from test_helpers import (
    PAST_ELECTION_WINDOW_CLOCK,
    SAFE_CLOCK,
    ApiErrorId,
    assert_program_election,
    create_active_election,
    create_farm_with_member,
    create_program_election_payload,
    get_farm_version,
    make_producer_headers,
    set_clock,
    validate_error,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestSupersedeCycle:
    def test_superseding_election_displaces_prior(self, api, specialist):
        """PRD §3.4: "When an election is created for a farm, year, and commodity
        that already has an `ACTIVE` election, the prior election moves to
        `SUPERSEDED`, the new election records `effective_from_version` equal to
        the farm's current `version`, and the farm's `version` increments by
        one." and "Elections begin in `ACTIVE` under `election_status`."

        Design: Difficulty/non_linear_state_machine/program_election_supersede_cycle
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        producer_headers = make_producer_headers(producer["id"])
        first = create_active_election(farm["id"], producer["id"], election_code="PLC")
        assert first["election_status"] == "ACTIVE"
        second = create_active_election(
            farm["id"], producer["id"], election_code="ARC_CO"
        )
        first_after = validate_success(
            api.get_program_election(first["id"], specialist), 200
        )
        second_after = validate_success(
            api.get_program_election(second["id"], specialist), 200
        )
        assert_program_election(first_after)
        assert_program_election(second_after)
        assert first_after["election_status"] == "SUPERSEDED", (
            f"prior election must be SUPERSEDED, got {first_after['election_status']}"
        )
        assert second_after["election_status"] == "ACTIVE", (
            f"new election must be ACTIVE, got {second_after['election_status']}"
        )

    def test_each_supersede_round_increments_farm_version(self, api, specialist):
        """PRD §3.4: "the new election records `effective_from_version` equal to
        the farm's current `version`, and the farm's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/program_election_supersede_cycle
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        v0 = get_farm_version(farm["id"])
        create_active_election(farm["id"], producer["id"], election_code="PLC")
        v1 = get_farm_version(farm["id"])
        assert v1 == v0 + 1, (
            f"first election must bump Farm.version by one: {v0} -> {v1}"
        )
        create_active_election(farm["id"], producer["id"], election_code="ARC_CO")
        v2 = get_farm_version(farm["id"])
        assert v2 == v1 + 1, (
            f"second election must bump Farm.version by one again: {v1} -> {v2}"
        )


class TestElectionWindowClosed:
    def test_create_election_after_deadline_rejected(self, api, specialist):
        """PRD §3.4: "The election window for the 2026 crop year closes at
        `2026-03-16T23:59:59Z`; creating, superseding, or withdrawing an election
        once the clock is past that deadline is rejected with
        `ERR_ELECTION_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/election_window_closed_boundary
        """
        set_clock(PAST_ELECTION_WINDOW_CLOCK)
        farm, producer, _ = create_farm_with_member()
        version = get_farm_version(farm["id"])
        resp = api.create_program_election(
            farm["id"],
            create_program_election_payload(
                program_year=2026,
                commodity="CORN",
                election_code="PLC",
                expected_farm_version=version,
            ),
            make_producer_headers(producer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value)

    def test_withdraw_election_after_deadline_rejected(self, api, specialist):
        """PRD §3.4: "The election window for the 2026 crop year closes at
        `2026-03-16T23:59:59Z`; creating, superseding, or withdrawing an election
        once the clock is past that deadline is rejected with
        `ERR_ELECTION_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/election_window_closed_boundary
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        election = create_active_election(farm["id"], producer["id"])
        set_clock(PAST_ELECTION_WINDOW_CLOCK)
        resp = api.withdraw_program_election(
            election["id"], make_producer_headers(producer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value)


class TestOccStaleFarmVersion:
    def test_second_election_with_stale_farm_version_rejected(self, api, specialist):
        """PRD §2.6: "Creating a program election on a farm requires
        `expected_farm_version` as a non-optional request field carrying the
        client's last observed `version` of the target `Farm`. If the farm's
        current `version` has advanced past that value, the request is rejected
        with `ERR_STALE_FARM_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_farm_version_occ
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        producer_headers = make_producer_headers(producer["id"])
        stale_version = get_farm_version(farm["id"])
        # First create succeeds and advances Farm.version.
        first = api.create_program_election(
            farm["id"],
            create_program_election_payload(
                commodity="CORN", election_code="PLC",
                expected_farm_version=stale_version,
            ),
            producer_headers,
        )
        validate_success(first, 201)
        # Second create replays the now-stale version for another commodity.
        resp = api.create_program_election(
            farm["id"],
            create_program_election_payload(
                commodity="SOYBN", election_code="ARC_CO",
                expected_farm_version=stale_version,
            ),
            producer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FARM_VERSION.value)
