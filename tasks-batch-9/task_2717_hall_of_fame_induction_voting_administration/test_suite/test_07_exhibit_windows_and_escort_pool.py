"""Temporal and capacity resources: display windows, escort intervals, occupancy."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CURATOR_HEADERS,
    approve_travel_grant,
    build_election_world,
    create_exhibit_installation_payload,
    read_case,
    read_cycle,
    read_induction,
    read_installation,
    request_travel_grant,
    setup_artifact_intake,
    setup_exhibit_case,
    validate_error,
    validate_success,
)

FILLER_ONE = {
    "full_name": "Filler One",
    "retirement_year": 2016,
    "career_seasons": 13,
    "career_metric_value": 2600,
}
FILLER_TWO = {
    "full_name": "Filler Two",
    "retirement_year": 2013,
    "career_seasons": 11,
    "career_metric_value": 2100,
}

LIVING_PAIR = [
    {
        "full_name": "Inductee Alpha",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Inductee Beta",
        "retirement_year": 2017,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
    FILLER_ONE,
    FILLER_TWO,
]

DECEASED_PAIR = [
    {
        "full_name": "Late Alpha",
        "retirement_year": 2015,
        "career_seasons": 14,
        "career_metric_value": 2800,
        "is_deceased": True,
        "death_year": 2020,
    },
    {
        "full_name": "Late Beta",
        "retirement_year": 2014,
        "career_seasons": 13,
        "career_metric_value": 2600,
        "is_deceased": True,
        "death_year": 2019,
    },
    FILLER_ONE,
    FILLER_TWO,
]

FOUR_SLOT_VOTES = [(index, [0, 1]) for index in range(4)]


def build_two_winner_world(api, *, stage, candidate_specs, nominations, rules=None, **kwargs):
    """A four-slot ballot whose first two slots are elected by all four electors."""
    return build_election_world(
        api,
        stage=stage,
        rules=rules if rules is not None else [{}],
        elector_count=4,
        candidate_specs=candidate_specs,
        nominations=nominations,
        votes=FOUR_SLOT_VOTES,
        **kwargs,
    )


LIVING_NOMINATIONS = [
    {"candidate_index": index, "pathway": "MODERN"} for index in range(4)
]

POSTHUMOUS_NOMINATIONS = [
    {"candidate_index": 0, "pathway": "POSTHUMOUS"},
    {"candidate_index": 1, "pathway": "POSTHUMOUS"},
    {"candidate_index": 2, "pathway": "MODERN"},
    {"candidate_index": 3, "pathway": "MODERN"},
]


class TestDisplayWindowConflicts:
    """Half-open windows for one inductee, buffered dark time between inductees."""

    @pytest.fixture
    def world(self, api):
        """Two inductions with artifacts received, plus a seven-day changeover case."""
        world = build_two_winner_world(
            api,
            stage="certified",
            candidate_specs=LIVING_PAIR,
            nominations=LIVING_NOMINATIONS,
        )
        world["case"] = setup_exhibit_case(
            api, case_code="CASE-A", capacity_artifacts=10, changeover_buffer_days=7
        )
        world["induction_a"] = world["inductions"][world["candidacies"][0]["id"]]
        world["induction_b"] = world["inductions"][world["candidacies"][1]["id"]]
        for key in ("induction_a", "induction_b"):
            setup_artifact_intake(api, world[key]["id"], artifact_count=2)
        return world

    def _install(self, api, world, induction_key, starts, ends, count=2):
        payload = create_exhibit_installation_payload(
            world[induction_key]["id"],
            world["case"]["id"],
            display_starts_on=starts,
            display_ends_on=ends,
            artifact_count=count,
        )
        return api.create_exhibit_installation(payload, CURATOR_HEADERS)

    def test_back_to_back_windows_for_one_inductee_are_legal(self, api, world):
        """If the other installation belongs to the **same induction**, plain half-open
        intersection applies: the conflict is real when the new start is strictly before the
        other's end and the other's start is strictly before the new end, so back-to-back
        windows for one inductee are legal.

        Design: Difficulty/resource_temporal_overlap/exhibit_case_half_open_window_and_changeover_buffer
        """
        validate_success(
            self._install(api, world, "induction_a", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            201,
        )
        second = validate_success(
            self._install(api, world, "induction_a", "2026-12-01T00:00:00Z", "2026-12-15T00:00:00Z"),
            201,
        )
        assert second["status"] == "INSTALLED"

    def test_a_second_inductee_must_wait_out_the_changeover_buffer(self, api, world):
        """If the other installation belongs to a **different induction**, the case's
        `changeover_buffer_days` of dark time is required on both sides: the conflict is real
        when the new start is strictly before the other's end extended forward by that many
        whole days, and the other's start is strictly before the new end extended forward by the
        same amount.

        Design: Difficulty/resource_temporal_overlap/exhibit_case_half_open_window_and_changeover_buffer
        """
        validate_success(
            self._install(api, world, "induction_a", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            201,
        )
        validate_success(
            self._install(api, world, "induction_a", "2026-12-01T00:00:00Z", "2026-12-15T00:00:00Z"),
            201,
        )
        validate_error(
            self._install(api, world, "induction_b", "2026-12-15T00:00:00Z", "2026-12-20T00:00:00Z"),
            "ERR_CASE_WINDOW_CONFLICT",
            409,
        )

    def test_a_window_exactly_one_buffer_later_is_accepted(self, api, world):
        """The gap comparison is inclusive, so a window starting exactly `changeover_buffer_days`
        after the previous induction's window ended is accepted.

        Design: Difficulty/resource_temporal_overlap/exhibit_case_half_open_window_and_changeover_buffer
        """
        validate_success(
            self._install(api, world, "induction_a", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            201,
        )
        validate_success(
            self._install(api, world, "induction_a", "2026-12-01T00:00:00Z", "2026-12-15T00:00:00Z"),
            201,
        )
        validate_error(
            self._install(api, world, "induction_b", "2026-12-15T00:00:00Z", "2026-12-20T00:00:00Z"),
            "ERR_CASE_WINDOW_CONFLICT",
            409,
        )
        validate_success(
            self._install(api, world, "induction_b", "2026-12-22T00:00:00Z", "2026-12-27T00:00:00Z"),
            201,
        )

    def test_occupancy_accumulates_across_every_accepted_window(self, api, world):
        """On success the installation is written with `status` `INSTALLED`, the case's
        `artifacts_installed` increases by the new `artifact_count`, and the induction's
        `exhibit_status` moves `NOT_PLANNED` → `INSTALLED` if this is the first installation for
        that induction, leaving it at `INSTALLED` for later ones — the exhibit dimension is a
        first-installation flag, not a one-shot lock, and an induction already holding an
        installed window may take further windows.

        Design: Difficulty/resource_temporal_overlap/exhibit_case_half_open_window_and_changeover_buffer
        """
        validate_success(
            self._install(api, world, "induction_a", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            201,
        )
        validate_success(
            self._install(api, world, "induction_a", "2026-12-01T00:00:00Z", "2026-12-15T00:00:00Z"),
            201,
        )
        validate_success(
            self._install(api, world, "induction_b", "2026-12-22T00:00:00Z", "2026-12-27T00:00:00Z"),
            201,
        )
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 6
        assert read_induction(api, world["induction_a"]["id"])["exhibit_status"] == "INSTALLED"
        assert read_induction(api, world["induction_b"]["id"])["exhibit_status"] == "INSTALLED"


class TestEscortPoolClosedIntervals:
    """Two posthumous delegations whose escort intervals touch at one instant."""

    ESCORT_ONE = ("2026-11-14T00:00:00Z", "2026-11-16T00:00:00Z")
    ESCORT_TWO = ("2026-11-16T00:00:00Z", "2026-11-18T00:00:00Z")

    def _world(self, api, **ceremony):
        world = build_two_winner_world(
            api,
            stage="ceremony",
            rules=[{}, {"pathway": "POSTHUMOUS"}],
            candidate_specs=DECEASED_PAIR,
            nominations=POSTHUMOUS_NOMINATIONS,
            ceremony_overrides=ceremony or None,
        )
        world["induction_a"] = world["inductions"][world["candidacies"][0]["id"]]
        world["induction_b"] = world["inductions"][world["candidacies"][1]["id"]]
        return world

    def _request(self, world, induction_key, interval):
        return request_travel_grant(
            world,
            world[induction_key]["id"],
            nights=1,
            requested_airfare_cents=0,
            escort_from=interval[0],
            escort_to=interval[1],
        )

    def test_touching_escort_intervals_overlap_at_that_instant(self, api):
        """Escort capacity is checked at approval, before any money moves, and it treats the
        escort interval as **closed at both ends** — an interval that ends at exactly the instant
        another begins counts as one instant of overlap.

        Design: Difficulty/resource_temporal_overlap/escort_pool_closed_interval_touching_endpoints
        """
        world = self._world(api)
        first = self._request(world, "induction_a", self.ESCORT_ONE)
        approve_travel_grant(world, first["id"])
        second = self._request(world, "induction_b", self.ESCORT_TWO)
        validate_error(
            api.approve_travel_grant(second["id"], ADMIN_HEADERS),
            "ERR_ESCORT_POOL_EXHAUSTED",
            409,
        )

    def test_cancelling_the_occupant_frees_the_interval_immediately(self, api):
        """Grants in `REQUESTED`, `DENIED` or `CANCELLED` status free their interval immediately
        and never obstruct anyone.

        Design: Difficulty/resource_temporal_overlap/escort_pool_closed_interval_touching_endpoints
        """
        world = self._world(api)
        first = self._request(world, "induction_a", self.ESCORT_ONE)
        approve_travel_grant(world, first["id"])
        second = self._request(world, "induction_b", self.ESCORT_TWO)
        validate_error(
            api.approve_travel_grant(second["id"], ADMIN_HEADERS),
            "ERR_ESCORT_POOL_EXHAUSTED",
            409,
        )
        validate_success(
            api.cancel_travel_grant(
                first["id"], {"cancellation_reason": "Delegation withdrew"}, ADMIN_HEADERS
            ),
            200,
        )
        approved = validate_success(api.approve_travel_grant(second["id"], ADMIN_HEADERS), 200)
        assert approved["status"] == "APPROVED"
        assert read_induction(api, world["induction_a"]["id"])["travel_status"] == "PENDING"
        assert read_induction(api, world["induction_b"]["id"])["travel_status"] == "APPROVED"
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 27500

    def test_a_larger_pool_tolerates_both_delegations_at_once(self, api):
        """Capacity is aggregate, not exclusive: overlap is an error only once the concurrent
        count would exceed the pool, so a pool of three tolerates three simultaneous
        delegations.

        Design: Difficulty/resource_temporal_overlap/escort_pool_closed_interval_touching_endpoints
        """
        world = self._world(api, escort_pool_size=2)
        first = self._request(world, "induction_a", self.ESCORT_ONE)
        approve_travel_grant(world, first["id"])
        second = self._request(world, "induction_b", self.ESCORT_TWO)
        approved = validate_success(api.approve_travel_grant(second["id"], ADMIN_HEADERS), 200)
        assert first["award_cents"] == 27500
        assert approved["award_cents"] == 27500
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 55000


class TestCaseOccupancyRestoredOnWithdrawal:
    """Withdrawing an installation gives the case back exactly what it held."""

    WINDOW = ("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")

    @pytest.fixture
    def world(self, api):
        """A four-artifact case holding one three-artifact installation."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=4,
            candidate_count=2,
            votes=[(index, [0]) for index in range(4)],
        )
        world["case"] = setup_exhibit_case(
            api, case_code="CASE-B", capacity_artifacts=4, changeover_buffer_days=7
        )
        world["induction"] = world["inductions"][world["candidacies"][0]["id"]]
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=3)
        world["installation"] = validate_success(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"],
                    world["case"]["id"],
                    display_starts_on=self.WINDOW[0],
                    display_ends_on=self.WINDOW[1],
                    artifact_count=3,
                ),
                CURATOR_HEADERS,
            ),
            201,
        )
        return world

    def test_withdrawal_restores_the_case_occupancy_exactly(self, api, world):
        """Withdrawing an installation moves it `INSTALLED` → `WITHDRAWN`, requires the owning
        induction's `status` to still be `ANNOUNCED`, and is the exhibit counterpart of grant
        cancellation: the case's `artifacts_installed` decreases by exactly that installation's
        `artifact_count`, restoring the pre-installation occupancy precisely, and both the window
        and the capacity are released so a later installation may occupy them.

        Design: Difficulty/compensating_invariant/exhibit_case_occupancy_restored_exactly_on_withdrawal
        """
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 3
        withdrawn = validate_success(
            api.withdraw_exhibit_installation(world["installation"]["id"], CURATOR_HEADERS), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["artifact_count"] == 3
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 0

    def test_withdrawal_returns_the_exhibit_dimension_to_not_planned(self, api, world):
        """If no other installation of that induction is still `INSTALLED`, the induction's
        `exhibit_status` moves `INSTALLED` → `NOT_PLANNED`, which recomputes `ceremony_ready` and
        decrements the cycle's `ceremony_ready_count` when readiness flips to false.

        Design: Difficulty/compensating_invariant/exhibit_case_occupancy_restored_exactly_on_withdrawal
        """
        assert read_induction(api, world["induction"]["id"])["exhibit_status"] == "INSTALLED"
        validate_success(
            api.withdraw_exhibit_installation(world["installation"]["id"], CURATOR_HEADERS), 200
        )
        assert read_induction(api, world["induction"]["id"])["exhibit_status"] == "NOT_PLANNED"

    def test_the_freed_capacity_absorbs_a_larger_installation(self, api, world):
        """The case's current `artifacts_installed` plus the new `artifact_count` must not exceed
        the case's `capacity_artifacts`, and an over-subscription is refused with
        `ERR_CASE_CAPACITY_EXCEEDED` (HTTP 409).

        Design: Difficulty/compensating_invariant/exhibit_case_occupancy_restored_exactly_on_withdrawal
        """
        validate_success(
            api.withdraw_exhibit_installation(world["installation"]["id"], CURATOR_HEADERS), 200
        )
        replacement = validate_success(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"],
                    world["case"]["id"],
                    display_starts_on=self.WINDOW[0],
                    display_ends_on=self.WINDOW[1],
                    artifact_count=4,
                ),
                CURATOR_HEADERS,
            ),
            201,
        )
        assert replacement["artifact_count"] == 4
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 4
        assert read_installation(api, replacement["id"])["status"] == "INSTALLED"
