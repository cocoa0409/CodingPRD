"""Cross-field references and the instants at the edge of a window."""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as fac
from test_helpers.api_errors import (
    ERR_DESIGNATION_PLAYER_MISMATCH,
    ERR_RELEASE_FILING_MISMATCH,
    ERR_RESULT_OUTSIDE_EXAM_WINDOW,
    ERR_RETURN_WINDOW_CLOSED,
)
from test_helpers.assertions import assert_designation_counts
from test_helpers.fixtures import League

CLOCK = "2026-08-10T14:00:00Z"
EXAM_START = "2026-08-10T13:00:00Z"
EXAM_END = "2026-08-10T20:00:00Z"


def _club(league: League) -> Dict[str, Any]:
    """One club with a cap large enough that no fiscal rung can fire."""
    league.set_clock(CLOCK)
    return league.register_club(
        name="Harbor Kings", market_code="HKG",
        salary_cap_limit_cents=500_000_000, waiver_priority_rank=1,
    )


class TestAnIrFilingCitingAnotherPlayersDesignation:
    """Both records exist and both belong to the club; they disagree on the player."""

    @staticmethod
    def _two_players_and_one_designation(league: League) -> Dict[str, Any]:
        club = _club(league)
        injured = league.register_player(full_name="Ray Alder", position="QB")
        healthy = league.register_player(full_name="Milo Sarr", position="WR")
        league.sign_onto_roster(
            club["id"], injured["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            years=3, base_salary_cents=80_000_000,
            signing_bonus_cents=10_000_000, start_season_year=2026,
        )
        league.sign_onto_roster(
            club["id"], healthy["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            years=1, base_salary_cents=12_000_000,
            signing_bonus_cents=0, start_season_year=2026,
        )
        designation = league.open_injury_designation(
            club["id"], injured["id"], "INJURED_RESERVE"
        )
        league.file_paperwork(designation["id"], club["id"])
        return {
            "club": club,
            "injured": injured,
            "healthy": healthy,
            "designation_id": designation["id"],
        }

    def test_a_placement_for_the_other_player_is_refused_at_create(
        self, league: League
    ) -> None:
        """The cited designation is somebody else's, so the create never lands.

        PRD 3.3: "An `IR_PLACEMENT` or `IR_ACTIVATION` requires an
        `injury_designation_id` whose designation belongs to both the filing club and
        the subject player — a mismatch on either is
        `ERR_DESIGNATION_PLAYER_MISMATCH`, and the same check is re-applied on every
        revision."

        Design: Corner/errors/an_ir_filing_pointing_at_another_players_designation_is_refused
        """
        world = self._two_players_and_one_designation(league)
        before = league.club(world["club"]["id"])

        response = league.api.create_transaction(
            fac.ir_placement_payload(
                world["club"]["id"], world["healthy"]["id"],
                before["version"], world["designation_id"],
            ),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_DESIGNATION_PLAYER_MISMATCH, 422)

        _, meta = validate_paginated(league.api.list_transactions(league.officer))
        assert meta["total_count"] == 2, (
            "only the two signings should exist — the placement was never created, "
            f"got {meta['total_count']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["player_id"] == world["injured"]["id"], (
            "the designation still belongs to the injured player, which is exactly "
            f"why the create failed, got {designation['player_id']}"
        )
        assert designation["status"] == "PAPERWORK_FILED", (
            f"and it is untouched by the refusal, got {designation['status']}"
        )

    def test_the_refused_create_moves_neither_player_nor_headcount(
        self, league: League
    ) -> None:
        """The subject player stays active and cleared, the club stays as it was.

        PRD 3.3: "Creating any filing increments the club's `version` by 1."

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/an_ir_filing_pointing_at_another_players_designation_is_refused
        """
        world = self._two_players_and_one_designation(league)
        before = league.club(world["club"]["id"])

        league.api.create_transaction(
            fac.ir_placement_payload(
                world["club"]["id"], world["healthy"]["id"],
                before["version"], world["designation_id"],
            ),
            League.analyst(world["club"]),
        )

        healthy = league.player(world["healthy"]["id"])
        assert healthy["roster_designation"] == "ACTIVE", (
            f"the subject player is still active, got {healthy['roster_designation']}"
        )
        assert healthy["medical_status"] == "CLEARED", (
            "and medically cleared — no paperwork was ever filed on him, got "
            f"{healthy['medical_status']}"
        )

        club = league.club(world["club"]["id"])
        assert_designation_counts(club, active=2, reserve=0, injured_reserve=0,
                                 practice_squad=0)
        assert club["version"] == before["version"], (
            "a create that failed increments no version, got "
            f"{club['version']}"
        )


class TestAWaiverPlacementCitingTheSigningFiling:
    """The player is on the wire's doorstep; the citation names the wrong filing."""

    @staticmethod
    def _released_but_unplaced(league: League) -> Dict[str, Any]:
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        signing = league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            years=3, base_salary_cents=80_000_000,
            signing_bonus_cents=10_000_000, start_season_year=2026,
        )
        release = league.open_release(club["id"], player["id"])
        league.submit_filing(release["id"], club["id"])
        approved_release = league.approve_filing(release["id"])
        return {
            "club": club,
            "player": player,
            "signing_id": signing["transaction_id"],
            "release": approved_release,
        }

    def test_a_placement_citing_the_signing_rather_than_the_release_is_refused(
        self, league: League
    ) -> None:
        """The cited filing is APPROVED but it is the wrong type.

        PRD 3.6: "The acting analyst's identifier must equal `from_team_id`, the
        cited filing must be an `APPROVED` filing of type `RELEASE` for the same
        player and the same club (otherwise `ERR_RELEASE_FILING_MISMATCH`), the
        player must currently be `WAIVED_PENDING`, and no other placement for that
        player may still be `PENDING` — a second one is refused with
        `ERR_WAIVER_ALREADY_PENDING`."

        Design: Corner/errors/a_waiver_placement_pointing_at_a_signing_filing_is_refused
        """
        world = self._released_but_unplaced(league)

        assert world["release"]["status"] == "APPROVED", (
            f"the release itself went through, got {world['release']['status']}"
        )
        player_before = league.player(world["player"]["id"])
        assert player_before["roster_designation"] == "WAIVED_PENDING", (
            "the released player is waiting for the wire, got "
            f"{player_before['roster_designation']}"
        )

        response = league.api.create_waiver_request(
            fac.waiver_request_payload(
                world["player"]["id"], world["club"]["id"], world["signing_id"]
            ),
            League.analyst(world["club"]),
        )
        validate_error(response, ERR_RELEASE_FILING_MISMATCH, 422)

        _, meta = validate_paginated(
            league.api.list_waiver_requests(league.officer)
        )
        assert meta["total_count"] == 0, (
            f"no wire should have been placed, got {meta['total_count']}"
        )

        signing = league.filing(world["signing_id"])
        assert signing["transaction_type"] == "SIGNING", (
            "the cited filing is the signing, which is the whole defect, got "
            f"{signing['transaction_type']}"
        )
        assert signing["status"] == "APPROVED", (
            f"and it remains approved, got {signing['status']}"
        )

        club = league.club(world["club"]["id"])
        assert club["active_roster_count"] == 0, (
            "the release already emptied the active bucket, got "
            f"{club['active_roster_count']}"
        )


class TestAResultStampedAtTheWindowEnd:
    """The examination window excludes its own end instant."""

    def test_a_result_performed_exactly_at_window_end_is_refused(
        self, league: League
    ) -> None:
        """One second earlier would have passed; the boundary itself is outside.

        PRD 3.5: "`performed_at` must fall inside the **half-open** window — at or
        after `window_start_at` and strictly before `window_end_at` — and anything
        else is `ERR_RESULT_OUTSIDE_EXAM_WINDOW`."

        PRD 3.5: "A passed result moves the exam `SCHEDULED → PASSED` and sets
        `expires_at` to `performed_at` plus 14 days."

        Design: Corner/errors/an_exam_result_stamped_at_the_window_end_instant_is_refused
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        exam = league.schedule_exam(
            club["id"], player["id"], "ENTRY_PHYSICAL", EXAM_START, EXAM_END,
        )

        assert exam["status"] == "SCHEDULED", (
            f"a booked examination is born SCHEDULED, got {exam['status']}"
        )
        assert exam["window_end_at"] == "2026-08-10T20:00:00.000Z", (
            f"the window ends at 20:00, got {exam['window_end_at']}"
        )

        response = league.api.record_exam_result(
            exam["id"], fac.exam_result_payload("PASSED", EXAM_END),
            League.medic(club),
        )
        validate_error(response, ERR_RESULT_OUTSIDE_EXAM_WINDOW, 422)

        unchanged = league.exam(exam["id"])
        assert unchanged["status"] == "SCHEDULED", (
            f"the exam is still awaiting a result, got {unchanged['status']}"
        )
        assert unchanged["performed_at"] is None, (
            f"no performance instant was stored, got {unchanged['performed_at']}"
        )
        assert unchanged["expires_at"] is None, (
            "and no expiry was derived, since only a pass sets one, got "
            f"{unchanged['expires_at']}"
        )

    def test_the_refused_result_leaves_the_player_mid_examination(
        self, league: League
    ) -> None:
        """Booking the window already moved the player; the refusal moves nothing.

        PRD 3.5: "Scheduling an exam moves the player's `medical_status` to
        `PHYSICAL_PENDING`, from `CLEARED`, from `REHAB` when the exam is a return
        physical, or from `FAILED_PHYSICAL` when the club is re-examining a player
        who previously failed."

        PRD 3.5: "A pass also records the instant on the player as
        `last_physical_passed_at` and returns the player's `medical_status` to
        `CLEARED`, provided no other scheduled exam remains outstanding."

        Design: Corner/errors/an_exam_result_stamped_at_the_window_end_instant_is_refused
        """
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        exam = league.schedule_exam(
            club["id"], player["id"], "ENTRY_PHYSICAL", EXAM_START, EXAM_END,
        )

        league.api.record_exam_result(
            exam["id"], fac.exam_result_payload("PASSED", EXAM_END),
            League.medic(club),
        )

        subject = league.player(player["id"])
        assert subject["medical_status"] == "PHYSICAL_PENDING", (
            "the booking put him mid-examination and nothing has cleared him, got "
            f"{subject['medical_status']}"
        )
        assert subject["last_physical_passed_at"] is None, (
            f"no pass was ever recorded on him, got {subject['last_physical_passed_at']}"
        )

        accepted = league.record_exam(
            exam["id"], club["id"], "PASSED", "2026-08-10T19:59:59Z"
        )
        assert accepted["status"] == "PASSED", (
            "one second inside the window is accepted, which is what makes the end "
            f"instant a boundary refusal, got {accepted['status']}"
        )
        assert accepted["expires_at"] == "2026-08-24T19:59:59.000Z", (
            "a pass expires 14 days after it was performed, got "
            f"{accepted['expires_at']}"
        )


class TestAnActivationOneSecondPastTheReturnWindow:
    """Every medical gate is satisfied; the clock has left the inclusive span."""

    LATE = "2026-09-21T14:00:01Z"

    @staticmethod
    def _filed_activation_one_second_late(league: League) -> Dict[str, Any]:
        club = _club(league)
        player = league.register_player(full_name="Ray Alder", position="QB")
        league.sign_onto_roster(
            club["id"], player["id"],
            window_start_at=EXAM_START, window_end_at=EXAM_END, performed_at=CLOCK,
            years=3, base_salary_cents=80_000_000,
            signing_bonus_cents=10_000_000, start_season_year=2026,
        )
        placement = league.place_on_injured_reserve(club["id"], player["id"])
        activated = league.designation(placement["designation_id"])

        league.set_clock("2026-08-31T14:00:00Z")
        league.run_sweep(club["id"])
        opened = league.designation(placement["designation_id"])

        league.set_clock(TestAnActivationOneSecondPastTheReturnWindow.LATE)
        activation = league.open_ir_activation(
            club["id"], player["id"], placement["designation_id"]
        )
        exam = league.schedule_exam(
            club["id"], player["id"], "RETURN_PHYSICAL",
            "2026-09-21T13:00:00Z", "2026-09-21T20:00:00Z",
            transaction_id=activation["id"],
        )
        passed = league.record_exam(
            exam["id"], club["id"], "PASSED",
            TestAnActivationOneSecondPastTheReturnWindow.LATE,
        )
        league.submit_filing(activation["id"], club["id"])
        return {
            "club": club,
            "player": player,
            "designation_id": placement["designation_id"],
            "activated": activated,
            "opened": opened,
            "activation_id": activation["id"],
            "passed": passed,
        }

    def test_an_activation_one_second_past_the_close_is_refused(
        self, league: League
    ) -> None:
        """The designation is open and the return physical is fresh; the clock is not.

        PRD 3.5: "At that moment `activated_at` is stamped with the logical clock and
        the return window is derived: `return_window_opens_at` is `activated_at` plus
        `minimum_stay_days` days, and `return_window_closes_at` is
        `return_window_opens_at` plus a further 21 days."

        PRD 3.5: "The return window is a **closed** interval: an activation landing
        exactly on `return_window_opens_at` or exactly on `return_window_closes_at`
        is on time, and only an instant outside that inclusive span draws
        `ERR_RETURN_WINDOW_CLOSED`."

        PRD 2.8: "The logical clock lies inside the closed interval from the cited
        designation's `return_window_opens_at` through its `return_window_closes_at`
        — otherwise `ERR_RETURN_WINDOW_CLOSED` (422). Applies to `POST
        /transactions/{id}/decide` on an `IR_ACTIVATION` filing."

        Design: Corner/errors/an_ir_activation_decided_after_the_return_window_closes_is_refused
        """
        world = self._filed_activation_one_second_late(league)

        assert world["activated"]["return_window_opens_at"] == "2026-08-31T14:00:00.000Z", (
            "21 minimum-stay days after activation, got "
            f"{world['activated']['return_window_opens_at']}"
        )
        assert world["activated"]["return_window_closes_at"] == "2026-09-21T14:00:00.000Z", (
            "and a further 21 days to close, got "
            f"{world['activated']['return_window_closes_at']}"
        )
        assert world["opened"]["status"] == "RETURN_WINDOW_OPEN", (
            "the sweep opened the window, so the paperwork gate is satisfied, got "
            f"{world['opened']['status']}"
        )
        assert world["passed"]["status"] == "PASSED", (
            f"the return physical passed, got {world['passed']['status']}"
        )
        assert world["passed"]["expires_at"] == "2026-10-05T14:00:01.000Z", (
            "and it stays valid for 14 days, well past the clock, got "
            f"{world['passed']['expires_at']}"
        )

        response = league.api.decide_transaction(
            world["activation_id"], fac.approve_payload(), league.officer
        )
        validate_error(response, ERR_RETURN_WINDOW_CLOSED, 422)

    def test_the_late_activation_writes_nothing_at_all(
        self, league: League
    ) -> None:
        """The filing stays filed and the player stays on injured reserve.

        PRD 3.3: "**`IR_ACTIVATION`**: the player's designation becomes `ACTIVE` and
        their `medical_status` returns to `CLEARED`; the cited designation moves
        `RETURN_WINDOW_OPEN → CLOSED` with `closed_at` set to the logical clock and
        `ir_service_credit_days` computed as the floored whole days between
        `activated_at` and `closed_at`."

        PRD 2.9: "If any precondition fails, nothing is written at all."

        Design: Corner/errors/an_ir_activation_decided_after_the_return_window_closes_is_refused
        """
        world = self._filed_activation_one_second_late(league)

        league.api.decide_transaction(
            world["activation_id"], fac.approve_payload(), league.officer
        )

        filing = league.filing(world["activation_id"])
        assert filing["status"] == "FILED", (
            f"the activation still awaits a decision, got {filing['status']}"
        )
        assert filing["effective_at"] is None, (
            f"nothing took effect, got {filing['effective_at']}"
        )

        designation = league.designation(world["designation_id"])
        assert designation["status"] == "RETURN_WINDOW_OPEN", (
            "the designation was not closed by the refused approval, got "
            f"{designation['status']}"
        )
        assert designation["closed_at"] is None, (
            f"and carries no close instant, got {designation['closed_at']}"
        )

        player = league.player(world["player"]["id"])
        assert player["roster_designation"] == "INJURED_RESERVE", (
            f"the player stays on injured reserve, got {player['roster_designation']}"
        )

        club = league.club(world["club"]["id"])
        assert_designation_counts(club, active=0, reserve=0, injured_reserve=1,
                                 practice_squad=0)
