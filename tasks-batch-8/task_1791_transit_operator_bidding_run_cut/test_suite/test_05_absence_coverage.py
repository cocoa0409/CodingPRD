"""Absence coverage: board-path cascade, overtime fallback, version-guarded
cover, and coverage preconditions."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_absence,
    create_operator,
    get_absence_case,
    get_assignment,
    get_operator,
    get_pay_records,
    setup_absence_case_with_board_cover,
    setup_implemented_with_award,
    setup_implemented_with_board_member,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]


class TestBoardCoverCascade:
    def test_cover_marks_case_covered_and_creates_covering_assignment(self, api):
        """PRD §3.7: "A successful cover moves the case from `REPORTED` to
        `COVERED`, creates the covering assignment — carrying the same `run_id`
        and `service_date` as the absent operator's assignment, a `source` of
        `EXTRA_BOARD_FILL` on the board path or `OVERTIME_OFFER` on the
        overtime path, and `status` `SCHEDULED` — records it as the case's
        `covering_assignment_id`, and moves the absent operator's original
        assignment from `SCHEDULED` to `NO_SHOW`."

        Design: Difficulty/transitive_cascade/absence_cover_three_hop_cascade
        """
        ctx = setup_absence_case_with_board_cover()
        ac = ctx["absence_case"]
        resp = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": False, "expected_absence_case_version": ac["version"]},
            SO,
        )
        covered = validate_success(resp)
        assert covered["status"] == "COVERED"
        assert covered["covering_assignment_id"] is not None

        # Hop 2: the absent operator's original assignment is now NO_SHOW.
        original = get_assignment(ctx["assignment"]["id"])
        assert original["status"] == "NO_SHOW"

        # Hop 1's product: covering assignment for the board operator.
        covering = get_assignment(covered["covering_assignment_id"])
        assert covering["operator_id"] == ctx["junior"]["id"]
        assert covering["source"] == "EXTRA_BOARD_FILL"
        assert covering["status"] == "SCHEDULED"
        assert covering["run_id"] == ctx["assignment"]["run_id"]
        assert covering["service_date"] == ctx["assignment"]["service_date"]

    def test_cover_selects_board_operator_by_position(self, api):
        """PRD §3.7: "The board path considers operators in `EXTRA_BOARD`
        status, choosing the lowest `board_position` and breaking ties by
        earlier `hire_date`."
        PRD §3.7: "A board operator who covers keeps their place on the board:
        their slot remains `FILLED` until implementation exhausts it, and their
        `board_position` is unchanged."

        Design: Difficulty/transitive_cascade/absence_cover_three_hop_cascade
        """
        ctx = setup_absence_case_with_board_cover()
        ac = ctx["absence_case"]
        resp = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": False, "expected_absence_case_version": ac["version"]},
            SO,
        )
        covered = validate_success(resp)
        covering = get_assignment(covered["covering_assignment_id"])
        # The only board operator is the junior, at board_position 1.
        assert covering["operator_id"] == ctx["junior"]["id"]
        # Board place is kept: slot remains FILLED and board_position unchanged.
        junior = get_operator(ctx["junior"]["id"])
        assert junior["board_position"] == 1
        assert junior["status"] == "EXTRA_BOARD"


class TestCoverPreconditions:
    def test_cover_without_scheduled_assignment_rejected(self, api):
        """PRD §3.7: "Two preconditions precede selection: the absent operator
        must hold a `SCHEDULED` assignment on the `absence_date` with a
        non-null `run_id` — otherwise `ERR_INVALID_STATE` — and at least one
        eligible covering operator must exist."

        Design: Difficulty/cross_entity_state_dependency/absence_cover_requires_scheduled_assignment
        """
        operator = create_operator()
        ac = create_absence(operator["id"], absence_date="2026-09-07")
        resp = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cover_without_scheduled_assignment_leaves_case_reported(self, api):
        """PRD §3.7: "Two preconditions precede selection: the absent operator
        must hold a `SCHEDULED` assignment on the `absence_date` with a
        non-null `run_id` — otherwise `ERR_INVALID_STATE` — and at least one
        eligible covering operator must exist."

        Design: Difficulty/cross_entity_state_dependency/absence_cover_requires_scheduled_assignment
        """
        operator = create_operator()
        ac = create_absence(operator["id"], absence_date="2026-09-07")
        resp = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_absence_case(ac["id"])
        assert after["status"] == "REPORTED"


class TestNoCoverAvailable:
    def _absence_with_no_board(self, api):
        """Implemented period with one awarded operator and no board members
        (only one operator exists; nobody is demoted to the board)."""
        # One operator wins the only run; the board is sized at 20% of 1 posted
        # run -> 1 slot, but no operator is ever demoted onto it, so the board
        # is empty of EXTRA_BOARD operators.
        from test_helpers import (
            award_run_to_operator,
            create_operator,
            create_picking_period,
            implement_period,
            lock_period,
            find_assignment,
        )
        period, runs = create_picking_period()
        operator = create_operator(employee_number="E1", full_name="Op A", hire_date="2000-01-01")
        award_run_to_operator(period["id"], operator["id"], runs[0]["id"])
        lock_period(period["id"])
        period = implement_period(period["id"])
        assignment = find_assignment(operator["id"], period["id"])
        ac = create_absence(operator["id"], absence_date=assignment["service_date"])
        return period, operator, assignment, ac

    def test_empty_board_and_no_overtime_rejected(self, api):
        """PRD §3.7: "The overtime path is available only when the board is
        empty and the request's `allow_overtime` flag is true; it considers
        operators in `ACTIVE` status only — board and suspended operators are
        excluded — choosing the lowest `weekly_ot_minutes_accum` and breaking
        ties by lower `seniority_rank`, which is the overtime-equalization
        rule: premium hours steer toward the operator who has received the
        least of them. When neither path yields a candidate, the cover attempt
        is rejected with `ERR_NO_COVER_AVAILABLE`."

        Design: Corner/errors/no_cover_available_error
        """
        _period, _operator, _asg, ac = self._absence_with_no_board(api)
        resp = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": False, "expected_absence_case_version": ac["version"]},
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_NO_COVER_AVAILABLE)


class TestCoverOcc:
    def test_stale_version_on_cover_rejected(self, api):
        """PRD §3.7: "Coverage is the dispatcher's desk, and it is one of the
        two version-guarded writes of §2.9: the request must carry
        `expected_absence_case_version` matching the case's current `version`,
        with a mismatch rejected as `ERR_STALE_VERSION`."
        PRD §2.10: "cover, declare-uncovered, and close each increment the
        absence case's `version`"

        Design: Corner/cross_cutting_layers/occ_stale_version_on_absence_cover
        """
        ctx = setup_absence_case_with_board_cover()
        ac = ctx["absence_case"]
        # First cover at the captured version succeeds and advances the version.
        resp1 = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
            SO,
        )
        validate_success(resp1)
        # Second cover reusing the now-stale version is rejected. PRD §2.6
        # places the state gate before the stale-version check, and the case is
        # no longer REPORTED after the first cover, so either ERR_INVALID_STATE
        # or ERR_STALE_VERSION is a faithful rejection of the stale replay.
        resp2 = api.cover_absence_case(
            ac["id"],
            {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
            SO,
        )
        validate_error_is_one_of(
            resp2, [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )
