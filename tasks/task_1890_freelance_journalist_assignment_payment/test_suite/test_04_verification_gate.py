"""Verification reports: threshold boundaries, the flag/adjudication cycle,
the confirmed-violation cascade, and recorder/adjudicator segregation."""
from test_helpers import (
    ApiErrorId,
    adjudicate_report,
    assert_verification_report,
    create_assignment,
    create_expense_claim,
    decide_expense,
    get_assignment,
    get_contributor,
    get_expense_claim,
    get_rights_purchase_for_assignment,
    get_success_data,
    list_reports,
    make_verification_editor_headers,
    record_result,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    setup_under_verification_cleared,
    validate_error,
    validate_success,
    walk_assignment,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


class TestPlagiarismThresholdBoundary:

    def test_score_exactly_at_threshold_flags(self, api):
        """PRD section 3.5: "For a `PLAGIARISM` report, a
        `similarity_score_bps` strictly below the desk's `flag_threshold_bps`
        (default 2000, i.e. 20%) clears the report; a score at or above the
        threshold flags it."
        PRD section 3.5: "The boundary is inclusive on the flag side —
        exactly at threshold means `FLAGGED`."

        Design: Difficulty/boundary_precision_check/plagiarism_threshold_exact_boundary
        """
        _contributor, _agr, assignment = setup_assignment_in_state(
            "UNDER_VERIFICATION", legal_name="Boundary Bea",
            email="bea@x.com")
        plag = list_reports(assignment["id"])[0]

        result = record_result(plag["id"], 2000, 0, user_id="ve-1")
        assert result["status"] == "FLAGGED", ">= 2000 bps flags (inclusive)"
        assert_verification_report(result)

    def test_score_one_bps_below_threshold_clears(self, api):
        """PRD section 3.5: "For a `PLAGIARISM` report, a
        `similarity_score_bps` strictly below the desk's `flag_threshold_bps`
        (default 2000, i.e. 20%) clears the report; a score at or above the
        threshold flags it."
        PRD section 3.5: "Clearing recomputes the assignment's
        `verification_cleared` (true exactly when every report of the
        assignment is `CLEARED` or `DISMISSED`); flagging closes the payment
        gate, blocking invoice submission while any report is `PENDING` or
        `FLAGGED` with `ERR_VERIFICATION_NOT_CLEARED`."

        Design: Difficulty/boundary_precision_check/plagiarism_threshold_exact_boundary
        """
        _contributor, _agr, assignment = setup_assignment_in_state(
            "UNDER_VERIFICATION", legal_name="Boundary Bea",
            email="bea@x.com")
        plag = list_reports(assignment["id"])[0]

        result = record_result(plag["id"], 1999, 0, user_id="ve-1")
        assert result["status"] == "CLEARED", "1999 < 2000 clears"
        assignment_after = get_assignment(assignment["id"])
        assert assignment_after["verification_cleared"] is False, (
            "the AI_CONTENT report is still PENDING, so the gate stays shut")


class TestFlagAdjudicationCycle:

    def test_dismissed_flag_reopens_payment_gate(self, api):
        """PRD section 3.5: "An outcome of `DISMISSED` returns the report to
        a clean state and recomputes `verification_cleared`."
        PRD section 3.5: "Clearing recomputes the assignment's
        `verification_cleared` (true exactly when every report of the
        assignment is `CLEARED` or `DISMISSED`); flagging closes the payment
        gate, blocking invoice submission while any report is `PENDING` or
        `FLAGGED` with `ERR_VERIFICATION_NOT_CLEARED`."

        Design: Difficulty/non_linear_state_machine/verification_flag_adjudication_cycle
        """
        _contributor, _agr, assignment = setup_assignment_in_state(
            "UNDER_VERIFICATION", legal_name="Cyclical Cy", email="cy@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000)
        plag, ai = list_reports(assignment["id"])
        record_result(plag["id"], 2500, 0, user_id="ve-recorder")
        record_result(ai["id"], 0, 500, user_id="ve-recorder")
        assert (get_success_data(
            _api.get_verification_report(plag["id"],
                                         make_verification_editor_headers(
                                             "ve-reader")))["status"]
            == "FLAGGED")

        adjudicated = adjudicate_report(
            plag["id"], "DISMISSED",
            note="false positive on quoted wire copy",
            user_id="ve-adjudicator")
        assert adjudicated["status"] == "DISMISSED"

        assignment_after = get_assignment(assignment["id"])
        assert assignment_after["editorial_status"] == "UNDER_VERIFICATION"
        assert assignment_after["verification_cleared"] is True, (
            "plagiarism DISMISSED + AI CLEARED means every report is clean")

    def test_confirmed_violation_rejects_assignment_and_voids_payment(
            self, api):
        """PRD section 3.5: "An outcome of `CONFIRMED_VIOLATION` fires a
        depth-three cascade: the assignment auto-transitions from
        `UNDER_VERIFICATION` to `REJECTED_AFTER_FLAG`; its `final_fee_cents`
        is set to 0 (no fee and no kill fee on a confirmed violation); its
        `payment_status` cascades to `VOID`; every expense claim for the
        assignment in `PRE_APPROVAL_REQUESTED`, `APPROVED`, or `SUBMITTED`
        flips to `DENIED`; the rights purchase flips to `REVERTED`; and the
        contributor themselves flips to `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/verification_flag_adjudication_cycle
        """
        contributor, _agr, assignment = setup_assignment_in_state(
            "UNDER_VERIFICATION", legal_name="Cyclical Cy", email="cy@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000)
        plag, ai = list_reports(assignment["id"])
        record_result(plag["id"], 100, 0, user_id="ve-recorder")
        record_result(ai["id"], 0, 8000, user_id="ve-recorder")

        adjudicated = adjudicate_report(
            ai["id"], "CONFIRMED_VIOLATION", note="undisclosed LLM draft",
            user_id="ve-adjudicator")
        assert adjudicated["status"] == "CONFIRMED_VIOLATION"

        assignment_after = get_assignment(assignment["id"])
        assert assignment_after["editorial_status"] == "REJECTED_AFTER_FLAG"
        assert assignment_after["payment_status"] == "VOID"
        assert assignment_after["final_fee_cents"] == 0
        assert (get_contributor(contributor["id"])["status"] == "SUSPENDED")


class TestConfirmedViolationDepth3Cascade:

    def _setup_flagged(self, api):
        contributor, _agr = setup_contributor_with_agreement(
            legal_name="Violator Vic", email="vic@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000,
            rights_default="ONE_TIME")
        assignment = create_assignment(contributor["id"], title="VS")
        walk_assignment(assignment["id"], contributor["id"], "ACCEPTED")
        claim = create_expense_claim(assignment["id"], contributor["id"],
                                     category="TRAVEL", requested_cents=4000)
        decide_expense(claim["id"], "APPROVE")
        walk_assignment(assignment["id"], contributor["id"],
                        "UNDER_VERIFICATION")
        plag = list_reports(assignment["id"])[0]
        record_result(plag["id"], 3000, 0, user_id="ve-recorder")
        return contributor, assignment, claim, plag

    def test_cascade_rejects_assignment_voids_payment_suspends_contributor(
            self, api):
        """PRD section 3.5: "An outcome of `CONFIRMED_VIOLATION` fires a
        depth-three cascade: the assignment auto-transitions from
        `UNDER_VERIFICATION` to `REJECTED_AFTER_FLAG`; its `final_fee_cents`
        is set to 0 (no fee and no kill fee on a confirmed violation); its
        `payment_status` cascades to `VOID`; every expense claim for the
        assignment in `PRE_APPROVAL_REQUESTED`, `APPROVED`, or `SUBMITTED`
        flips to `DENIED`; the rights purchase flips to `REVERTED`; and the
        contributor themselves flips to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/confirmed_violation_depth3_cascade
        """
        contributor, assignment, _claim, plag = self._setup_flagged(api)
        adjudicated = adjudicate_report(
            plag["id"], "CONFIRMED_VIOLATION",
            note="passages lifted verbatim", user_id="ve-adjudicator")
        assert adjudicated["status"] == "CONFIRMED_VIOLATION"

        assignment_after = get_assignment(assignment["id"])
        assert assignment_after["editorial_status"] == "REJECTED_AFTER_FLAG"
        assert assignment_after["payment_status"] == "VOID"
        assert assignment_after["final_fee_cents"] == 0
        assert (get_contributor(contributor["id"])["status"]
                == "SUSPENDED"), "link 3: contributor cascade"

    def test_cascade_denies_open_expenses_and_reverts_rights(self, api):
        """PRD section 3.5: "An outcome of `CONFIRMED_VIOLATION` fires a
        depth-three cascade: the assignment auto-transitions from
        `UNDER_VERIFICATION` to `REJECTED_AFTER_FLAG`; its `final_fee_cents`
        is set to 0 (no fee and no kill fee on a confirmed violation); its
        `payment_status` cascades to `VOID`; every expense claim for the
        assignment in `PRE_APPROVAL_REQUESTED`, `APPROVED`, or `SUBMITTED`
        flips to `DENIED`; the rights purchase flips to `REVERTED`; and the
        contributor themselves flips to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/confirmed_violation_depth3_cascade
        """
        _contributor, assignment, claim, plag = self._setup_flagged(api)
        assert get_expense_claim(claim["id"])["status"] == "APPROVED"

        adjudicate_report(plag["id"], "CONFIRMED_VIOLATION",
                          note="passages lifted verbatim",
                          user_id="ve-adjudicator")

        assert get_expense_claim(claim["id"])["status"] == "DENIED"
        rights = get_rights_purchase_for_assignment(assignment["id"])
        assert rights["status"] == "REVERTED"
        assert rights["rights_kind"] == "ONE_TIME"


def test_adjudicator_must_differ_from_recorder(api):
    """PRD section 2.8: "The `VerificationEditor` who recorded a flag on a
    verification report may not adjudicate that same report."
    PRD section 3.5: "Segregation of duties applies: the adjudicator's
    `X-User-ID` must differ from the recorder's, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_adjudication_same_recorder
    """
    _contributor, _agr, assignment = setup_assignment_in_state(
        "UNDER_VERIFICATION", legal_name="Adj Amy", email="amy@x.com")
    plag = list_reports(assignment["id"])[0]
    record_result(plag["id"], 5000, 0, user_id="ve-rec")

    resp = _api.adjudicate_verification_report(
        plag["id"],
        {"outcome": "DISMISSED",
         "adjudication_note": "self-adjudication attempt"},
        make_verification_editor_headers("ve-rec"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    report_after = get_success_data(
        _api.get_verification_report(
            plag["id"], make_verification_editor_headers("ve-reader")))
    assert report_after["status"] == "FLAGGED", "rejected adjudication leaves the flag open"
