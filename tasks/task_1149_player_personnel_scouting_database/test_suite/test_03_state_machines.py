"""State-machine cycles, invalid transitions, terminal-state lockdowns (PRD §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    GM_HEADERS,
    add_board_entry,
    advance_prospect,
    api_client,
    area_headers,
    create_and_lock_report,
    create_director,
    create_draft_board,
    create_flag,
    create_free_agent_target,
    create_prospect,
    create_report,
    create_scout,
    director_headers,
    get_success_data,
    lock_report,
    make_board_ready_prospect,
    submit_report,
    validate_error,
    validate_success,
)


class TestReportRevisionCycle:
    """Difficulty: non_linear_state_machine/report_revision_cycle."""

    def _setup_draft_report(self):
        s1 = create_scout(
            level="AREA",
            full_name="Cycle Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="Cycle Prospect", position="CB", college="State U")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        return s1, d1, p1, r1

    def test_full_revision_loop_statuses(self, api):
        """PRD §3.3: "The revision loop `SUBMITTED` → `RETURNED` → `SUBMITTED`
        may iterate as many times as needed before lock." The full path
        DRAFT -> SUBMITTED -> RETURNED -> SUBMITTED -> LOCKED exercises the
        cycle.

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        s1, d1, _, r1 = self._setup_draft_report()
        st1 = submit_report(r1["id"], s1)["status"]
        assert st1 == "SUBMITTED"
        resp = api_client.return_report(
            r1["id"], {"return_reason": "redo athleticism section"}, director_headers(d1)
        )
        st2 = validate_success(resp)["status"]
        assert st2 == "RETURNED"
        st3 = submit_report(r1["id"], s1)["status"]
        assert st3 == "SUBMITTED"
        st4 = lock_report(r1["id"], d1)["status"]
        assert st4 == "LOCKED"

    def test_lock_computes_normalized_grade_after_cycle(self, api):
        """PRD §3.3 step 1: "When the director locks a report, four cascades
        run in order: 1. The report's `normalized_grade` is computed and
        snapshotted onto the report." After the revision loop the locked
        report carries normalized_grade = 5.0 + 1.5*(7.00-6.00)/1.00 = 6.50.

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        s1, d1, _, r1 = self._setup_draft_report()
        submit_report(r1["id"], s1)
        api_client.return_report(r1["id"], {"return_reason": "redo"}, director_headers(d1))
        submit_report(r1["id"], s1)
        locked = lock_report(r1["id"], d1)
        assert locked["normalized_grade"] == pytest.approx(6.50, abs=0.005)


class TestBoardFreezeUnfreezeRevert:
    """Difficulty: non_linear_state_machine/board_freeze_unfreeze_revert."""

    def test_open_frozen_open_frozen_cycle_accepted(self, api):
        """PRD §3.5: "A board's lifecycle is `OPEN` → `FROZEN` → `FINALIZED`,
        with an `OPEN` ↔ `FROZEN` cycle: the director freezes an `OPEN` board,
        may unfreeze a `FROZEN` board back to `OPEN`, and may finalize a
        `FROZEN` board."

        Design: Difficulty/non_linear_state_machine/board_freeze_unfreeze_revert
        """
        d1 = create_director(full_name="Dir One")
        b1 = create_draft_board(d1, season_year=2026)
        assert b1["status"] == "OPEN"
        st1 = validate_success(api_client.freeze_board(b1["id"], director_headers(d1)))["status"]
        assert st1 == "FROZEN"
        st2 = validate_success(api_client.unfreeze_board(b1["id"], director_headers(d1)))["status"]
        assert st2 == "OPEN", "FROZEN -> OPEN revert must be accepted (non-linear shape)"
        st3 = validate_success(api_client.freeze_board(b1["id"], director_headers(d1)))["status"]
        assert st3 == "FROZEN"

    def test_finalize_after_refreeze_accepted(self, api):
        """PRD §3.5: "Finalization requires at least one active entry — a
        `FROZEN` board whose `active_entry_count` is zero rejects with
        `ERR_BOARD_EMPTY`. `FINALIZED` is terminal." A board that went
        OPEN -> FROZEN -> OPEN -> FROZEN with an active entry may finalize.

        Design: Difficulty/non_linear_state_machine/board_freeze_unfreeze_revert
        """
        s1 = create_scout(
            level="AREA", full_name="S", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="Dir One")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        add_board_entry(b1["id"], p1["id"], d1)
        api_client.freeze_board(b1["id"], director_headers(d1))
        api_client.unfreeze_board(b1["id"], director_headers(d1))
        api_client.freeze_board(b1["id"], director_headers(d1))
        final = validate_success(api_client.finalize_board(b1["id"], director_headers(d1)))
        assert final["status"] == "FINALIZED"


class TestInvalidTransitions:
    """Corner: lock_draft_report_rejected, submit_locked_report_rejected,
    double_submit_rejected, advance_without_locked_report_rejected,
    finalize_open_board_rejected, finalize_empty_board_rejected,
    entry_add_frozen_board_rejected, entry_add_not_board_ready_rejected,
    entry_add_excluded_prospect_rejected, pass_terminal_target_rejected."""

    def test_lock_draft_report_rejected(self, api):
        """PRD §3.3: "From `SUBMITTED` a `ScoutingDirector` has two moves:
        return the report for revision, recording a `return_reason`
        (defaulting to an empty string when omitted), which moves it to
        `RETURNED`; or lock it, which is terminal." A DRAFT report is not
        SUBMITTED, so locking it is rejected. PRD §2.9 item 5: state guards
        fire `ERR_INVALID_STATE`.

        Design: Corner/state_machines/lock_draft_report_rejected
        """
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0)
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="S", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        resp = api_client.lock_report(r1["id"], director_headers(d1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # report remains DRAFT with normalized_grade null
        current = get_success_data(api_client.get_report(r1["id"], area_headers(s1)))
        assert current["status"] == "DRAFT"
        assert current["normalized_grade"] is None

    def test_submit_locked_report_rejected(self, api):
        """PRD §3.3: "or lock it, which is terminal." Submitting a LOCKED
        report is a state-guard violation rejected with `ERR_INVALID_STATE`
        per PRD §2.9 item 5 ("State guards — the entity's current state
        permits the transition").

        Design: Corner/state_machines/submit_locked_report_rejected
        """
        s1 = create_scout(
            level="AREA", full_name="S1", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="S", college="A")
        r1 = create_and_lock_report(p1["id"], s1, d1, raw_grade=7.00, scheme_fit=1.00)
        resp = api_client.submit_report(r1["id"], area_headers(s1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_submit_rejected(self, api):
        """PRD §3.3: "The authoring scout — and only that scout, with any
        other submitter rejected as `ERR_REPORT_NOT_OWNED` — submits it,
        moving it to `SUBMITTED`." The submit transition is only valid from
        DRAFT or RETURNED; resubmitting a SUBMITTED report is a state-guard
        violation (`ERR_INVALID_STATE`).

        Design: Corner/state_machines/double_submit_rejected
        """
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0)
        p1 = create_prospect(s1, full_name="P", position="S", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        resp = api_client.submit_report(r1["id"], area_headers(s1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_advance_without_locked_report_rejected(self, api):
        """PRD §3.2: "From `SCOUTING`, a `ScoutingDirector` advances the
        prospect by supplying a `to_state` of `EVALUATED`, but only once at
        least one report on the prospect has been `LOCKED`". A merely
        SUBMITTED report does not satisfy the guard.

        Design: Corner/state_machines/advance_without_locked_report_rejected
        """
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0)
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="S", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        resp = api_client.advance_prospect(
            p1["id"], {"to_state": "EVALUATED"}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert current["evaluation_status"] == "SCOUTING"

    def test_finalize_open_board_rejected(self, api):
        """PRD §3.5: "may finalize a `FROZEN` board"; "Any state-inconsistent
        freeze, unfreeze, or finalize attempt is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/finalize_open_board_rejected
        """
        d1 = create_director(full_name="D")
        b1 = create_draft_board(d1, season_year=2026)
        resp = api_client.finalize_board(b1["id"], director_headers(d1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_finalize_empty_board_rejected(self, api):
        """PRD §3.5: "Finalization requires at least one active entry — a
        `FROZEN` board whose `active_entry_count` is zero rejects with
        `ERR_BOARD_EMPTY`."

        Design: Corner/state_machines/finalize_empty_board_rejected
        """
        d1 = create_director(full_name="D")
        b1 = create_draft_board(d1, season_year=2026)
        api_client.freeze_board(b1["id"], director_headers(d1))
        resp = api_client.finalize_board(b1["id"], director_headers(d1))
        validate_error(resp, ApiErrorId.ERR_BOARD_EMPTY)

    def test_entry_add_frozen_board_rejected(self, api):
        """PRD §3.5: "the board must be `OPEN` (a `FROZEN` or `FINALIZED`
        board rejects with `ERR_BOARD_NOT_OPEN`)".

        Design: Corner/state_machines/entry_add_frozen_board_rejected
        """
        s1 = create_scout(
            level="AREA", full_name="S", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        api_client.freeze_board(b1["id"], director_headers(d1))
        resp = api_client.add_board_entry(
            b1["id"], {"prospect_id": p1["id"]}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_BOARD_NOT_OPEN)

    def test_entry_add_not_board_ready_rejected(self, api):
        """PRD §3.5: "the prospect's `evaluation_status` must be `BOARD_READY`
        (otherwise `ERR_PROSPECT_NOT_BOARD_READY`)".

        Design: Corner/state_machines/entry_add_not_board_ready_rejected
        """
        s1 = create_scout(
            level="AREA", full_name="S", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        create_and_lock_report(p1["id"], s1, d1, raw_grade=7.00, scheme_fit=1.00)
        advance_prospect(p1["id"], "EVALUATED", d1)
        b1 = create_draft_board(d1, season_year=2026)
        resp = api_client.add_board_entry(
            b1["id"], {"prospect_id": p1["id"]}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_BOARD_READY)

    def test_entry_add_excluded_prospect_rejected(self, api):
        """PRD §3.5: "the prospect's `flag_status` must not be `EXCLUDED`
        (otherwise `ERR_PROSPECT_EXCLUDED`)".

        Design: Corner/state_machines/entry_add_excluded_prospect_rejected
        """
        from test_helpers import MED_HEADERS

        s1 = create_scout(
            level="AREA", full_name="S", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        f1 = create_flag(
            p1["id"], MED_HEADERS,
            flag_type="MEDICAL", severity="HIGH", detail="spinal fusion",
        )
        resp = api_client.escalate_flag(f1["id"], director_headers(d1))
        get_success_data(resp)
        b1 = create_draft_board(d1, season_year=2026)
        resp = api_client.add_board_entry(
            b1["id"], {"prospect_id": p1["id"]}, director_headers(d1)
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_EXCLUDED)

    def test_pass_terminal_target_rejected(self, api):
        """PRD §3.7: "with `PASSED` available as a terminal off-ramp from any
        of `IDENTIFIED`, `EVALUATING`, `APPROVED`, or `OFFERED`, and
        `RELEASED` as the terminal state reachable only from `SIGNED`."
        Passing an already-PASSED target is a state-guard violation
        (`ERR_INVALID_STATE`).

        Design: Corner/state_machines/pass_terminal_target_rejected
        """
        t1 = create_free_agent_target(
            player_name="Vet", position="WR", season_year=2026,
            base_salary_cents=1000000, signing_bonus_cents=0, contract_years=1,
        )
        api_client.pass_target(t1["id"], GM_HEADERS)
        resp = api_client.pass_target(t1["id"], GM_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFlagSideEffects:
    def test_flag_resolve_clears_prospect(self, api):
        """PRD §3.4: "On resolution the prospect's `flag_status` is
        recomputed: if no other flag of the prospect remains in `OPEN`,
        `ACKNOWLEDGED`, or `ESCALATED`, the prospect moves `UNDER_REVIEW` →
        `CLEARED`".

        Design: Corner/state_machines/flag_resolve_clears_prospect
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0)
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="S", college="A")
        f1 = create_flag(
            p1["id"], area_headers(s1),
            flag_type="CHARACTER", severity="LOW", detail="minor",
        )
        resp = api_client.resolve_flag(
            f1["id"], {"resolution_note": "cleared"}, director_headers(d1)
        )
        resolved = validate_success(resp)
        assert resolved["status"] == "RESOLVED"
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["flag_status"] == "CLEARED"

    def test_escalate_high_character_keeps_under_review(self, api):
        """PRD §3.4: "in every other case — a `LOW` medical flag, or any
        `CHARACTER` flag — the prospect simply remains (or stays)
        `UNDER_REVIEW` with no board impact."

        Design: Corner/state_machines/escalate_high_character_keeps_under_review
        """
        s1 = create_scout(
            level="AREA", full_name="S", weight=1.0,
            season_grade_mean=6.00, season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="D")
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, full_name="P", position="QB", college="A")
        b1 = create_draft_board(d1, season_year=2026)
        add_board_entry(b1["id"], p1["id"], d1)
        f1 = create_flag(
            p1["id"], area_headers(s1),
            flag_type="CHARACTER", severity="HIGH", detail="arrest report",
        )
        api_client.escalate_flag(f1["id"], director_headers(d1))
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["flag_status"] == "UNDER_REVIEW", (
            "HIGH CHARACTER escalation must not exclude the prospect"
        )
        entries = get_success_data(
            api_client.list_prospect_board_entries(p1["id"], director_headers(d1))
        )
        assert entries[0]["active"] is True
