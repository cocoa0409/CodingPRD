"""Blackout periods: half-open overlap geometry, advisory timing, activation /
completion gates, and the election-blocking effect of an active blackout."""
from test_helpers import (
    ApiErrorId,
    activate_blackout,
    assert_instant_equal,
    complete_blackout,
    create_blackout,
    create_blackout_with_advisory,
    create_case,
    effectuate_termination,
    get_case,
    issue_noit,
    issue_notice,
    set_clock,
    setup_case_in_distribution,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]


class TestBlackoutOverlap:
    def test_blackout_adjacent_window_allowed_overlap_rejected(self, api):
        """PRD §3.5: "Blackout windows on the same case may not intersect: a
        new half-open window overlapping an existing one is rejected with
        `ERR_BLACKOUT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency — a new
        `start_at` exactly equal to an existing window's `end_at` — is allowed."

        Design: Difficulty/resource_temporal_overlap/blackout_half_open_overlap
        """
        case = create_case(plan_name="Overlap Co 401k", plan_number="090")
        create_blackout(case["id"], "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z")
        # Pure adjacency: start_at == A.end_at is allowed under half-open semantics.
        adjacent = create_blackout(
            case["id"], "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z"
        )
        assert adjacent["status"] == "SCHEDULED"
        resp = api.create_blackout_period(
            {
                "termination_case_id": case["id"],
                "start_at": "2026-09-09T00:00:00Z",
                "end_at": "2026-09-12T00:00:00Z",
                "outgoing_recordkeeper": "RKX",
                "incoming_recordkeeper": "RKY",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_WINDOW_OVERLAP)

    def test_blackout_overlap_rejection_leaves_schedule_unchanged(self, api):
        """PRD §3.5: "Blackout windows on the same case may not intersect: a
        new half-open window overlapping an existing one is rejected with
        `ERR_BLACKOUT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency — a new
        `start_at` exactly equal to an existing window's `end_at` — is allowed."

        Design: Difficulty/resource_temporal_overlap/blackout_half_open_overlap
        """
        case = create_case(plan_name="Overlap Co 401k", plan_number="090")
        create_blackout(case["id"], "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z")
        create_blackout(case["id"], "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z")
        resp = api.create_blackout_period(
            {
                "termination_case_id": case["id"],
                "start_at": "2026-09-09T00:00:00Z",
                "end_at": "2026-09-12T00:00:00Z",
                "outgoing_recordkeeper": "RKX",
                "incoming_recordkeeper": "RKY",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_WINDOW_OVERLAP)
        data, meta = validate_paginated(api.list_blackout_periods(case["id"], ADMIN))
        assert len(data) == 2, (
            "only the two non-overlapping windows persist after the rejection"
        )


class TestBlackoutActivationPriority:
    def _completed_blackout(self, api):
        """Case (DRAFT) with blackout [2026-09-01, 2026-09-05) activated at
        2026-09-03 and completed at 2026-09-06. Clock left at 2026-09-06."""
        case = create_case(plan_name="Prio One Co 401k", plan_number="060")
        blackout = create_blackout_with_advisory(
            case["id"], "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z",
            advisory_clock="2026-08-01T00:00:00Z",
        )
        activate_blackout(blackout["id"], "2026-09-03T00:00:00Z")
        complete_blackout(blackout["id"], "2026-09-06T00:00:00Z")
        return case, blackout

    def test_blackout_activate_state_beats_temporal(self, api):
        """PRD §2.9: "Every write request passes through a fixed sequence of
        rejection layers, and the layering is observable: an earlier failure
        masks later ones."
        PRD §2.9: "Sixth, from-state gates run — case status, participant flag
        and missing gates, search-case step gates, election and payout states,
        transfer and DLR states, blackout states."
        PRD §2.9: "Tenth, the statutory temporal windows."
        PRD §3.5: "Activation is the `Recordkeeper`'s act and requires the
        period to be `SCHEDULED` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`), the
        current clock to satisfy being at or after `start_at` and strictly
        before `end_at` (otherwise `ERR_BLACKOUT_NOT_IN_WINDOW`, HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/blackout_activate_state_beats_temporal
        """
        _, blackout = self._completed_blackout(api)
        # Second activation at 2026-09-06 violates both the from-state gate
        # (COMPLETED) and the window rule (now >= end_at); state wins.
        resp = api.activate_blackout(blackout["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_NOT_SCHEDULED)

    def test_completed_blackout_unchanged_after_rejected_activation(self, api):
        """PRD §3.5: "Completion, also by the `Recordkeeper`, requires the
        period to be `ACTIVE` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`) and the
        current clock to be at or after `end_at` (otherwise
        `ERR_BLACKOUT_NOT_ENDED`, HTTP 409). Completion stamps `completed_at`,
        recomputes `blackout_active` to false".

        Design: Difficulty/priority_pair_validation_conflict/blackout_activate_state_beats_temporal
        """
        case, blackout = self._completed_blackout(api)
        api.activate_blackout(blackout["id"], RECORDKEEPER)  # rejected
        data, _ = validate_paginated(api.list_blackout_periods(case["id"], ADMIN))
        current = data[0]
        assert current["status"] == "COMPLETED"
        assert_instant_equal(
            current["completed_at"], "2026-09-06T00:00:00Z", "completed_at"
        )
        assert get_case(case["id"])["blackout_active"] is False


class TestBlackoutNoticesAndGates:
    def test_blackout_advisory_window_too_close_rejected(self, api):
        """PRD §3.5: "its issuance is lawful only when a `SCHEDULED` blackout
        exists on the case whose `start_at` equals that `action_effective_date`
        and the issuance clock time falls within the window from 60 days before
        the start through 30 days before it, inclusive by whole calendar days;
        an issuance failing either half is rejected with
        `ERR_BLACKOUT_NOTICE_WINDOW` (HTTP 422)".

        Design: Corner/validations/blackout_advisory_window_too_close_returns_error
        """
        case = create_case(plan_name="Advisory Co 401k", plan_number="145")
        create_blackout(case["id"], "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z")
        set_clock("2026-09-02T00:00:00Z")  # 29 days before the start
        case = get_case(case["id"])
        resp = api.create_notice(
            {
                "termination_case_id": case["id"],
                "notice_type": "BLACKOUT_ADVISORY",
                "action_effective_date": "2026-10-01T00:00:00Z",
                "expected_termination_case_version": case["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_NOTICE_WINDOW)

    def test_blackout_activate_without_notice_and_pending_blackout(self, api):
        """PRD §3.5: "Activation is the `Recordkeeper`'s act and requires the
        period to be `SCHEDULED` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`), the
        current clock to satisfy being at or after `start_at` and strictly
        before `end_at` (otherwise `ERR_BLACKOUT_NOT_IN_WINDOW`, HTTP 409), and
        a non-superseded `BLACKOUT_ADVISORY` notice to exist on the case whose
        `action_effective_date` equals the period's `start_at` (otherwise
        `ERR_BLACKOUT_NOTICE_MISSING`, HTTP 422) — that notice's own 30-to-60-day
        window having been enforced at its issuance."
        PRD §3.2: "Beginning distributions requires the case to be
        `TERMINATION_EFFECTIVE` (otherwise `ERR_CASE_INVALID_STATE`), requires a
        non-superseded `DISTRIBUTION` notice to exist for the case (otherwise
        `ERR_DISTRIBUTION_NOTICE_REQUIRED`, HTTP 422), and requires that no
        `BlackoutPeriod` of the case is `SCHEDULED` or `ACTIVE` (otherwise
        `ERR_BLACKOUT_TRANSITION_PENDING`, HTTP 409)."

        Design: Corner/validations/blackout_activate_without_notice_returns_missing
        """
        # Arm 1: activation inside the window but without the advisory notice.
        case_a = create_case(plan_name="NoNotice Co 401k", plan_number="146")
        blackout = create_blackout(
            case_a["id"], "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
        )
        set_clock("2026-09-02T00:00:00Z")
        resp = api.activate_blackout(blackout["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_NOTICE_MISSING)

        # Arm 2: begin-distributions while a blackout is SCHEDULED.
        case_b = create_case(plan_name="Pending Co 401k", plan_number="147")
        issue_noit(case_b["id"])
        effectuate_termination(case_b["id"])
        issue_notice(case_b["id"], "DISTRIBUTION", "2026-10-20T00:00:00Z")
        create_blackout(case_b["id"], "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z")
        resp = api.begin_distributions(case_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_TRANSITION_PENDING)
        assert get_case(case_b["id"])["status"] == "TERMINATION_EFFECTIVE"

    def test_blackout_complete_early_census_frozen_and_notice_required(self, api):
        """PRD §3.5: "Completion, also by the `Recordkeeper`, requires the
        period to be `ACTIVE` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`) and the
        current clock to be at or after `end_at` (otherwise
        `ERR_BLACKOUT_NOT_ENDED`, HTTP 409)."
        PRD §3.1: "a participant may only be added while the case is `DRAFT`,
        `NOTICE_OF_INTENT_ISSUED`, or `TERMINATION_EFFECTIVE`, and a create
        attempted once the case has reached `DISTRIBUTION_IN_PROGRESS` or beyond
        is rejected with `ERR_CASE_CENSUS_FROZEN` (HTTP 409)."
        PRD §3.2: "Beginning distributions requires the case to be
        `TERMINATION_EFFECTIVE` (otherwise `ERR_CASE_INVALID_STATE`), requires a
        non-superseded `DISTRIBUTION` notice to exist for the case (otherwise
        `ERR_DISTRIBUTION_NOTICE_REQUIRED`, HTTP 422)".

        Design: Corner/consistency_model/blackout_complete_before_end_and_census_frozen
        """
        # Arm 1: completing a blackout before end_at.
        case_a = create_case(plan_name="EarlyEnd Co 401k", plan_number="202")
        blackout = create_blackout_with_advisory(
            case_a["id"], "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z",
            advisory_clock="2026-08-01T00:00:00Z",
        )
        activate_blackout(blackout["id"], "2026-09-02T00:00:00Z")
        # clock is 2026-09-02 (inside the window, before end_at 2026-09-05)
        resp = api.complete_blackout(blackout["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_NOT_ENDED)

        # Arm 2: the census freezes once distributions have begun.
        case_b, _ = setup_case_in_distribution(
            participants=[], plan_name="Census Co 401k", plan_number="203"
        )
        resp = api.create_participant(
            {
                "termination_case_id": case_b["id"],
                "full_name": "Too Late",
                "ssn": "121110099",
                "mailing_address": "9 L St",
                "account_balance_cents": 1000,
                "vested_pct": 100,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_CENSUS_FROZEN)

        # Arm 3: begin-distributions without a live DISTRIBUTION notice.
        case_c = create_case(plan_name="NoDist Co 401k", plan_number="204")
        issue_noit(case_c["id"])
        effectuate_termination(case_c["id"])
        resp = api.begin_distributions(case_c["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_NOTICE_REQUIRED)
