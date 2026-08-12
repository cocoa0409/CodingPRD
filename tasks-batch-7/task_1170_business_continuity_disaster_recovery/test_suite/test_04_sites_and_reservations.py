"""Site capacity, half-open reservation windows, and the reserve/release ledger (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_contact,
    create_process,
    create_site,
    make_site_coordinator_headers,
    reserve_seats,
    set_clock,
    validate_error,
    validate_success,
)


class TestUtilizationRoundingOrder:
    def _setup_three_single_seat_reservations(self):
        set_clock()
        coordinator = create_contact("Sam Site", "Site Coordinator")
        processes = [create_process(coordinator["id"], name=f"P{i}")
                     for i in (1, 2, 3)]
        site = create_site(coordinator["id"], name="SiteAlpha", region="us-east",
                           capacity_seats=6, monthly_cost=9000)
        for process in processes:
            reserve_seats(site["id"], process["id"], coordinator["id"], 1,
                          "2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z")
        return coordinator, site

    def test_utilization_rounds_each_reservation_before_summing(self, api):
        """PRD §3.5: "The arithmetic order is pinned: each occupying reservation's percentage is computed first as its `seats_reserved` divided by the site's `capacity_seats`, times one hundred, rounded half-up to one decimal place, and only then are the per-reservation percentages summed and the total rounded half-up to one decimal place as `utilization_pct`. Summing seats first and rounding once is a different computation and is not this one."

        Three 1-seat reservations on capacity 6 yield 3 x 16.7 = 50.1 — the
        sum-then-round order would wrongly yield 50.0.

        Design: Difficulty/combinatorial_formula/site_utilization_per_reservation_rounding
        """
        coordinator, site = self._setup_three_single_seat_reservations()
        data = validate_success(
            api_client.get_site_utilization(
                site["id"], make_site_coordinator_headers(coordinator["id"]),
                params={"probe_at": "2026-06-10T10:00:00Z"}))
        assert data["utilization_pct"] == pytest.approx(50.1, abs=0.001), (
            f"per-reservation rounding must yield 50.1, got {data['utilization_pct']}"
        )

    def test_utilization_reports_seat_totals(self, api):
        """PRD §3.5: "The response reports `capacity_seats`, the summed `reserved_seats`, `utilization_pct`, and the effective `probe_at`."
        PRD §3.5: "Occupants are the site's `CONFIRMED` reservations whose half-open window contains the probe instant — start inclusive, end exclusive; `RELEASED` reservations never count."

        The utilization read reports the raw seat totals alongside the percentage.

        Design: Difficulty/combinatorial_formula/site_utilization_per_reservation_rounding
        """
        coordinator, site = self._setup_three_single_seat_reservations()
        data = validate_success(
            api_client.get_site_utilization(
                site["id"], make_site_coordinator_headers(coordinator["id"]),
                params={"probe_at": "2026-06-10T10:00:00Z"}))
        assert data["capacity_seats"] == 6
        assert data["reserved_seats"] == 3
        assert data["utilization_pct"] == pytest.approx(50.1, abs=0.001)


class TestHalfOpenAdjacencyAndCapacity:
    def _setup(self):
        set_clock()
        coordinator = create_contact("Sam Site", "Site Coordinator")
        p1 = create_process(coordinator["id"], name="P1")
        p2 = create_process(coordinator["id"], name="P2")
        site = create_site(coordinator["id"], name="SiteGamma", region="eu-west",
                           capacity_seats=10, monthly_cost=5000)
        r1 = reserve_seats(site["id"], p1["id"], coordinator["id"], 6,
                           "2026-07-10T09:00:00Z", "2026-07-10T12:00:00Z")
        return coordinator, p1, p2, site, r1

    def test_adjacent_reservation_allowed_under_half_open_windows(self, api):
        """PRD §3.5: "And a single process may not double-book: a `CONFIRMED` reservation may not overlap — under the same half-open window semantics — another `CONFIRMED` reservation of the same process on the same site, else `ERR_SITE_WINDOW_OVERLAP`."
        PRD §3.5: "the occupation window `starts_at` (inclusive) and `ends_at` (exclusive, and strictly after the start)"

        [12:00,15:00) does not overlap [09:00,12:00): the end is exclusive.

        Design: Difficulty/resource_temporal_overlap/site_reservation_half_open_adjacency_and_capacity
        """
        coordinator, p1, _, site, _ = self._setup()
        r2 = reserve_seats(site["id"], p1["id"], coordinator["id"], 2,
                           "2026-07-10T12:00:00Z", "2026-07-10T15:00:00Z")
        assert r2["status"] == "CONFIRMED", (
            "adjacent same-process windows must be allowed under half-open semantics"
        )

    def test_same_process_overlap_and_capacity_rejections(self, api):
        """PRD §3.5: "And a single process may not double-book: a `CONFIRMED` reservation may not overlap — under the same half-open window semantics — another `CONFIRMED` reservation of the same process on the same site, else `ERR_SITE_WINDOW_OVERLAP`."
        PRD §3.5: "Aggregate capacity must hold: the seats of all `CONFIRMED` reservations of the site whose half-open windows overlap the new window, plus the new reservation's `seats_reserved`, must not exceed the site's `capacity_seats`, else `ERR_SITE_CAPACITY_EXCEEDED`."

        11:59 start collides for the same process; a different process's 5-seat
        request breaches the aggregate (6 + 5 = 11 > 10) without any same-process
        overlap.

        Design: Difficulty/resource_temporal_overlap/site_reservation_half_open_adjacency_and_capacity
        """
        coordinator, p1, p2, site, _ = self._setup()
        coordinator_headers = make_site_coordinator_headers(coordinator["id"])
        overlap = api_client.create_site_reservation(
            {"site_id": site["id"], "process_id": p1["id"], "purpose": "EXERCISE",
             "seats_reserved": 1, "starts_at": "2026-07-10T11:59:00Z",
             "ends_at": "2026-07-10T13:00:00Z",
             "created_by_contact_id": coordinator["id"]},
            coordinator_headers)
        validate_error(overlap, ApiErrorId.ERR_SITE_WINDOW_OVERLAP)

        over_capacity = api_client.create_site_reservation(
            {"site_id": site["id"], "process_id": p2["id"], "purpose": "INCIDENT",
             "seats_reserved": 5, "starts_at": "2026-07-10T10:00:00Z",
             "ends_at": "2026-07-10T11:00:00Z",
             "created_by_contact_id": coordinator["id"]},
            coordinator_headers)
        validate_error(over_capacity, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)


class TestReserveReleaseInvariant:
    def _setup(self):
        set_clock()
        creator = create_contact("Sam Site", "Site Coordinator")
        releaser = create_contact("Sue Site", "Site Coordinator")
        p1 = create_process(creator["id"], name="P1")
        p2 = create_process(creator["id"], name="P2")
        p3 = create_process(creator["id"], name="P3")
        site = create_site(creator["id"], name="SiteDelta", region="us-east",
                           capacity_seats=8, monthly_cost=8000)
        reserve_seats(site["id"], p1["id"], creator["id"], 3,
                      "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z")
        return creator, releaser, p1, p2, p3, site

    def _probe(self, site_id, headers):
        return validate_success(
            api_client.get_site_utilization(
                site_id, headers, params={"probe_at": "2026-08-10T10:00:00Z"}))

    def test_over_capacity_attempt_leaves_ledger_untouched(self, api):
        """PRD §3.5: "Aggregate capacity must hold: the seats of all `CONFIRMED` reservations of the site whose half-open windows overlap the new window, plus the new reservation's `seats_reserved`, must not exceed the site's `capacity_seats`, else `ERR_SITE_CAPACITY_EXCEEDED`."

        Baseline 3 seats at 37.5%; a forward 4-seat reservation succeeds; the
        over-capacity attempt (3 + 4 + 2 = 9 > 8, third process so only the
        capacity rule can fire) is rejected and creates nothing.

        Design: Difficulty/compensating_invariant/site_seats_reserve_release_capacity_invariant
        """
        creator, _, _, p2, p3, site = self._setup()
        creator_headers = make_site_coordinator_headers(creator["id"])
        before = self._probe(site["id"], creator_headers)
        assert before["reserved_seats"] == 3
        assert before["utilization_pct"] == pytest.approx(37.5, abs=0.001)

        reserve_seats(site["id"], p2["id"], creator["id"], 4,
                      "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                      purpose="INCIDENT")
        rejected = api_client.create_site_reservation(
            {"site_id": site["id"], "process_id": p3["id"], "purpose": "INCIDENT",
             "seats_reserved": 2, "starts_at": "2026-08-10T10:00:00Z",
             "ends_at": "2026-08-10T11:00:00Z",
             "created_by_contact_id": creator["id"]},
            creator_headers)
        validate_error(rejected, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)
        after = self._probe(site["id"], creator_headers)
        assert after["reserved_seats"] == 7, (
            "the rejected attempt must leave the seat ledger untouched (3 + 4)"
        )

    def test_release_restores_capacity_baseline(self, api):
        """PRD §3.5: "Release ends a booking: a `SiteCoordinator` moves `CONFIRMED` → `RELEASED`, the reserved seats free against the site's capacity effective immediately, and the reservation's `version` increments."
        PRD §3.5: "Occupants are the site's `CONFIRMED` reservations whose half-open window contains the probe instant — start inclusive, end exclusive; `RELEASED` reservations never count."

        The reserve/release pair conserves the seat ledger: after release the
        probe reads exactly the pre-reserve baseline.

        Design: Difficulty/compensating_invariant/site_seats_reserve_release_capacity_invariant
        """
        creator, releaser, _, p2, _, site = self._setup()
        creator_headers = make_site_coordinator_headers(creator["id"])
        before = self._probe(site["id"], creator_headers)
        forward = reserve_seats(site["id"], p2["id"], creator["id"], 4,
                                "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                                purpose="INCIDENT")
        released = validate_success(
            api_client.release_site_reservation(
                forward["id"], make_site_coordinator_headers(releaser["id"])))
        assert released["status"] == "RELEASED"
        after = self._probe(site["id"], creator_headers)
        assert after["reserved_seats"] == before["reserved_seats"] == 3
        assert after["utilization_pct"] == pytest.approx(before["utilization_pct"], abs=0.001)
        assert after["utilization_pct"] == pytest.approx(37.5, abs=0.001)
