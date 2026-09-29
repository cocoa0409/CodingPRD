"""Two contended resources with deliberately opposite interval semantics."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_EXAM_WINDOW_OVERLAP,
    ERR_MEDICAL_REVIEW_SLOT_TAKEN,
)
from test_helpers.fixtures import League
from test_helpers.test_users import make_medical_officer_headers


class TestPlayerExamWindowsAreHalfOpen:
    """One player, one examination calendar, touching endpoints allowed."""

    OCCUPIED_START = "2026-08-10T13:00:00Z"
    OCCUPIED_END = "2026-08-10T17:00:00Z"

    @staticmethod
    def _player_with_one_occupied_window(league: League) -> Dict[str, Any]:
        league.set_clock("2026-08-10T12:00:00Z")
        club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        player = league.register_player(full_name="Ray Alder", position="QB")
        occupied = league.schedule_exam(
            club["id"], player["id"], "ENTRY_PHYSICAL",
            TestPlayerExamWindowsAreHalfOpen.OCCUPIED_START,
            TestPlayerExamWindowsAreHalfOpen.OCCUPIED_END,
        )
        return {"club": club, "player": player, "occupied": occupied}

    def test_a_window_starting_exactly_at_the_occupied_end_is_accepted(
        self, league: League
    ) -> None:
        """Touching endpoints do not collide on an examination calendar.

        PRD 3.5: "Touching endpoints therefore do *not* collide — a new window
        beginning exactly at an existing window's `window_end_at` is accepted."

        Design: Difficulty/resource_temporal_overlap/player_exam_windows_admit_abutment_but_reject_one_second_of_overlap
        """
        world = self._player_with_one_occupied_window(league)

        assert world["occupied"]["window_end_at"] == "2026-08-10T17:00:00.000Z", (
            "the occupied window ends at 17:00, got "
            f"{world['occupied']['window_end_at']}"
        )

        response = league.api.create_physical_exam(
            fac.physical_exam_payload(
                world["player"]["id"], world["club"]["id"], "ENTRY_PHYSICAL",
                "2026-08-10T17:00:00Z", "2026-08-10T20:00:00Z",
            ),
            make_medical_officer_headers(world["club"]["id"]),
        )
        abutting = validate_success(response, 201)

        assert abutting["window_start_at"] == "2026-08-10T17:00:00.000Z", (
            "the abutting window starts exactly where the other ended, got "
            f"{abutting['window_start_at']}"
        )
        assert abutting["status"] == "SCHEDULED", (
            f"a booked window is SCHEDULED, got {abutting['status']}"
        )
        assert league.exam(world["occupied"]["id"])["status"] == "SCHEDULED", (
            "the incumbent window keeps its booking"
        )

        player = league.player(world["player"]["id"])
        assert player["medical_status"] == "PHYSICAL_PENDING", (
            "scheduling an examination puts the player in PHYSICAL_PENDING, got "
            f"{player['medical_status']}"
        )

    def test_a_window_one_second_earlier_collides_and_is_refused(
        self, league: League
    ) -> None:
        """One second of genuine overlap is fatal, and writes nothing.

        PRD 3.5: "A player may hold **one** scheduled examination window at a time,
        and the collision test uses **half-open** interval semantics: the requested
        window, treated as starting at `window_start_at` and ending strictly before
        `window_end_at`, collides with an existing window of another `SCHEDULED` exam
        for the same player exactly when the requested start is strictly earlier than
        the existing end and the existing start is strictly earlier than the
        requested end."

        Design: Difficulty/resource_temporal_overlap/player_exam_windows_admit_abutment_but_reject_one_second_of_overlap
        """
        world = self._player_with_one_occupied_window(league)

        league.schedule_exam(
            world["club"]["id"], world["player"]["id"], "ENTRY_PHYSICAL",
            "2026-08-10T17:00:00Z", "2026-08-10T20:00:00Z",
        )

        response = league.api.create_physical_exam(
            fac.physical_exam_payload(
                world["player"]["id"], world["club"]["id"], "ENTRY_PHYSICAL",
                "2026-08-10T16:59:59Z", "2026-08-10T20:00:00Z",
            ),
            make_medical_officer_headers(world["club"]["id"]),
        )
        validate_error(response, ERR_EXAM_WINDOW_OVERLAP, 409)

        exams, meta = validate_paginated(
            league.api.list_physical_exams(league.officer)
        )
        assert meta["total_count"] == 2, (
            "the refused window created no row, so only the two accepted windows "
            f"exist, got {meta['total_count']}"
        )
        assert all(exam["status"] == "SCHEDULED" for exam in exams), (
            "both surviving windows are still booked, got "
            f"{[exam['status'] for exam in exams]}"
        )
        assert {exam["window_start_at"] for exam in exams} == {
            "2026-08-10T13:00:00.000Z", "2026-08-10T17:00:00.000Z"
        }, (
            "no window starting at 16:59:59 should exist, got "
            f"{[exam['window_start_at'] for exam in exams]}"
        )


class TestMedicalReviewSlotsAreClosed:
    """One club, one medical-review slot, touching endpoints forbidden."""

    @staticmethod
    def _one_review_underway_and_a_second_trade_waiting(
        league: League
    ) -> Dict[str, Any]:
        league.set_clock("2026-08-10T14:00:00Z")
        shared_club = league.register_club(
            name="Harbor Kings", market_code="HKG",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
        )
        first_counterparty = league.register_club(
            name="Basin Otters", market_code="BSN",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=2,
        )
        second_counterparty = league.register_club(
            name="Coastal Rays", market_code="CST",
            salary_cap_limit_cents=500_000_000, waiver_priority_rank=3,
        )

        first_trade = league.build_trade(
            shared_club["id"], first_counterparty["id"], "PHYSICAL_CONTINGENT"
        )
        league.offer_draft_pick(
            first_trade["id"], shared_club["id"], "TO_COUNTERPARTY",
            expected_trade_version=first_trade["version"],
            draft_pick_year=2027, draft_pick_round=3,
        )
        accepted = league.accept_trade(first_trade["id"], first_counterparty["id"])

        second_trade = league.build_trade(
            shared_club["id"], second_counterparty["id"], "PHYSICAL_CONTINGENT"
        )
        league.offer_draft_pick(
            second_trade["id"], shared_club["id"], "TO_COUNTERPARTY",
            expected_trade_version=second_trade["version"],
            draft_pick_year=2028, draft_pick_round=1,
        )
        league.set_clock("2026-08-13T14:00:00Z")
        return {
            "shared_club": shared_club,
            "first_counterparty": first_counterparty,
            "second_counterparty": second_counterparty,
            "first_trade": accepted,
            "second_trade_id": second_trade["id"],
        }

    def test_a_candidate_starting_on_the_incumbent_deadline_is_refused(
        self, league: League
    ) -> None:
        """The shared club's slot is still occupied at the touching instant.

        PRD 3.7: "Each club has capacity for exactly one concurrent medical review,
        and the occupied interval runs from a trade's `accepted_at` through its
        `medical_review_deadline_at` as a **closed** interval — touching endpoints
        *do* collide, which is deliberately the opposite of the half-open rule
        governing examination windows."

        Design: Difficulty/resource_temporal_overlap/club_medical_review_slots_collide_on_touching_deadline_endpoint
        """
        world = self._one_review_underway_and_a_second_trade_waiting(league)

        assert world["first_trade"]["medical_review_deadline_at"] == (
            "2026-08-13T14:00:00.000Z"
        ), (
            "the incumbent review runs 72 hours from acceptance, got "
            f"{world['first_trade']['medical_review_deadline_at']}"
        )
        assert world["first_trade"]["status"] == "MEDICAL_REVIEW", (
            "a contingent acceptance opens a medical review, got "
            f"{world['first_trade']['status']}"
        )

        response = league.api.accept_trade(
            world["second_trade_id"],
            League.analyst(world["second_counterparty"]),
        )
        validate_error(response, ERR_MEDICAL_REVIEW_SLOT_TAKEN, 409)

        refused = league.trade(world["second_trade_id"])
        assert refused["status"] == "PROPOSED", (
            f"the refused trade is still on the table, got {refused['status']}"
        )
        assert refused["accepted_at"] is None, (
            f"no acceptance instant is stamped, got {refused['accepted_at']}"
        )
        assert refused["medical_review_deadline_at"] is None, (
            "and no review deadline either, got "
            f"{refused['medical_review_deadline_at']}"
        )
        assert refused["version"] == 2, (
            "creation and one asset addition are the only writes, got version "
            f"{refused['version']}"
        )

        shared_club = league.club(world["shared_club"]["id"])
        assert shared_club["open_medical_review_count"] == 1, (
            "the shared club still holds exactly its one review, got "
            f"{shared_club['open_medical_review_count']}"
        )
        waiting_club = league.club(world["second_counterparty"]["id"])
        assert waiting_club["open_medical_review_count"] == 0, (
            "the refused counterparty opened nothing, got "
            f"{waiting_club['open_medical_review_count']}"
        )

    def test_one_second_past_the_deadline_the_disjoint_review_is_admitted(
        self, league: League
    ) -> None:
        """Availability counts overlapping intervals, not open reviews.

        PRD 3.7: "A club is available only when the number of its overlapping
        occupied intervals is strictly less than 1, that is, when it has none; both
        clubs must be available, and otherwise the acceptance is refused with
        `ERR_MEDICAL_REVIEW_SLOT_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/club_medical_review_slots_collide_on_touching_deadline_endpoint
        """
        world = self._one_review_underway_and_a_second_trade_waiting(league)

        league.api.accept_trade(
            world["second_trade_id"],
            League.analyst(world["second_counterparty"]),
        )
        league.set_clock("2026-08-13T14:00:01Z")
        accepted = league.accept_trade(
            world["second_trade_id"], world["second_counterparty"]["id"]
        )

        assert accepted["status"] == "MEDICAL_REVIEW", (
            f"the second review should open, got {accepted['status']}"
        )
        assert accepted["accepted_at"] == "2026-08-13T14:00:01.000Z", (
            f"acceptance is stamped on the clock, got {accepted['accepted_at']}"
        )
        assert accepted["medical_review_deadline_at"] == "2026-08-16T14:00:01.000Z", (
            "the new review also runs 72 hours, got "
            f"{accepted['medical_review_deadline_at']}"
        )
        assert accepted["version"] == 3, (
            "creation, one asset and one acceptance make three writes, got version "
            f"{accepted['version']}"
        )

        shared_club = league.club(world["shared_club"]["id"])
        assert shared_club["open_medical_review_count"] == 2, (
            "both acceptances incremented the shared club's counter because the "
            "two occupied intervals are disjoint, got "
            f"{shared_club['open_medical_review_count']}"
        )
        assert league.club(
            world["second_counterparty"]["id"]
        )["open_medical_review_count"] == 1, (
            "the new counterparty now holds one review"
        )
        assert league.club(
            world["first_counterparty"]["id"]
        )["open_medical_review_count"] == 1, (
            "the original counterparty still holds its own"
        )
        assert league.trade(world["first_trade"]["id"])["status"] == (
            "MEDICAL_REVIEW"
        ), "the incumbent trade is untouched by either attempt"
