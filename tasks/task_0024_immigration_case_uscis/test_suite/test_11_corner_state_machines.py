"""Corner (state_machines) — initial state, invalid transitions, terminal
lockdown, side-effect cascades, and precondition enforcement."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
    setup_under_review_i130,
    setup_biometrics_scheduled_i485,
    setup_rfe_pending_i130,
    make_applicant_headers,
    make_officer_headers,
    decide_case_payload,
    rfe_respond_payload,
    issue_rfe_payload,
)


class TestInitialCaseState:

    def test_new_case_is_draft_with_initial_counters(self, api):
        """PRD §3.1: "A `Case` is created in `DRAFT` status by an applicant or attorney."
        PRD §3.1: "The case's `rfe_round_count` is initialised to 0."
        PRD §2.4: "`version` (integer): a monotonically increasing counter that starts at 1
        on creation"

        Design: Corner/state_machines/initial_case_state_is_draft
        """
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        assert case["status"] == "DRAFT"
        assert case["rfe_round_count"] == 0
        assert case["version"] == 1


class TestRefileDraftReturnsInvalidState:

    def test_refile_after_file_returns_invalid_state(self, api):
        """PRD §3.2: "The preconditions are that the case is in `DRAFT`, that `case_type`
        is set, that the referenced applicant exists"
        PRD §2.11: "source-state correctness for the requested transition (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/file_a_draft_then_re_file_returns_invalid_state
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        # First file: should succeed.
        filed = file_case(case, applicant)
        assert filed["status"] == "FILED"
        # Second file: case is now in FILED, not DRAFT → ERR_INVALID_STATE.
        headers = make_applicant_headers(applicant["id"])
        res = api.file_case(case["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestApprovedCaseAlreadyTerminal:

    def test_decide_on_approved_case_returns_terminal_or_invalid_state(self, api):
        """PRD §2.11: "source-state correctness for the requested transition (`ERR_INVALID_STATE`),
        terminal-state preclusion (`ERR_ALREADY_TERMINAL`)"
        PRD §5: "`ERR_ALREADY_TERMINAL` | 409 Conflict"

        Note: §2.11's priority order places ERR_INVALID_STATE strictly above
        ERR_ALREADY_TERMINAL, so a PRD-only implementer could ship either as
        the response here (APPROVED is both a terminal state and an invalid
        source state for the requested transition). We accept either.

        Design: Corner/state_machines/approved_case_decide_again_returns_already_terminal
        """
        # Walk to APPROVED on an I-130 (no interview, no visa gate).
        applicant, case_ur, officer = setup_under_review_i130()
        res_decide = api.decide_case(
            case_ur["id"],
            decide_case_payload("APPROVE", case_ur["version"]),
            officer,
        )
        approved = validate_success(res_decide, 200)
        assert approved["status"] == "APPROVED"

        # Try /decide again — terminal.
        res = api.decide_case(
            case_ur["id"],
            decide_case_payload("APPROVE", approved["version"]),
            officer,
        )
        validate_error_is_one_of(res, ["ERR_ALREADY_TERMINAL", "ERR_INVALID_STATE"])


class TestBiometricsNoShowCascadesCaseToAbandoned:

    def test_mark_no_show_after_grace_window_abandons_case(self, api):
        """PRD §3.3: "The officer may issue the mark-no-show capability only when the
        appointment is in `SCHEDULED` and `ClockState.current_utc` is at or after
        the appointment's `scheduled_at` plus 24 hours (the grace window).
        The appointment's `status` is set to `NO_SHOW` (a terminal state for
        the appointment), the parent case cascades to the terminal `ABANDONED` status"

        Design: Corner/state_machines/biometrics_noshow_cascades_case_to_abandoned
        """
        applicant, case, biom, officer = setup_biometrics_scheduled_i485(
            file_date_iso="2026-06-15T00:00:00Z",
            biom_at="2026-06-25T15:00:00Z",
            asc_location_code="ASC-SF-20",
        )
        # Advance past biom + 24h.
        set_clock("2026-06-27T00:00:00Z")
        res = api.mark_biometrics_no_show(biom["id"], officer)
        body = validate_success(res, 200)
        assert body["status"] == "NO_SHOW"

        case_after = get_success_data(api.get_case(case["id"], officer))
        assert case_after["status"] == "ABANDONED"


class TestRfeCapExceeded:

    def test_third_rfe_after_two_rounds_rejected_with_cap_exceeded(self, api):
        """PRD §3.5: "its `rfe_round_count` must be strictly less than 2 — the system caps
        the number of RFE rounds per case at exactly 2, and a third attempt is
        rejected with `ERR_RFE_CAP_EXCEEDED`."

        Design: Corner/state_machines/rfe_cap_exceeded_third_rfe_rejected
        """
        applicant, case_rfe, rfe1, officer = setup_rfe_pending_i130(
            evidence_items=["doc_1"]
        )
        # Respond to first RFE → back to UNDER_REVIEW.
        applicant_headers = make_applicant_headers(applicant["id"])
        api.respond_to_rfe(
            rfe1["id"],
            rfe_respond_payload(case_rfe["version"], "doc_1 sent"),
            applicant_headers,
        )
        case_v1 = get_success_data(api.get_case(case_rfe["id"], officer))
        # Issue second RFE.
        api.issue_rfe(case_rfe["id"], issue_rfe_payload(["doc_2"]), officer)
        case_v2 = get_success_data(api.get_case(case_rfe["id"], officer))
        rfe2 = get_success_data(
            api.list_rfes_for_case(case_rfe["id"], officer)
        )
        # rfe2 list — the most recent in ISSUED status.
        rfe2_id = next(r["id"] for r in rfe2 if r["status"] == "ISSUED")
        api.respond_to_rfe(
            rfe2_id,
            rfe_respond_payload(case_v2["version"], "doc_2 sent"),
            applicant_headers,
        )
        case_after = get_success_data(api.get_case(case_rfe["id"], officer))
        assert case_after["rfe_round_count"] == 2
        assert case_after["status"] == "UNDER_REVIEW"
        # Third issuance must be blocked.
        res = api.issue_rfe(case_after["id"], issue_rfe_payload(["doc_3"]), officer)
        validate_error(res, "ERR_RFE_CAP_EXCEEDED")
