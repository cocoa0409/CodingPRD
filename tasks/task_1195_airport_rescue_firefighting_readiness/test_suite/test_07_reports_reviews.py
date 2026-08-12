"""Incident reports, review loop, post-incident reviews."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_accepted_report,
    create_controlled_incident,
    create_draft_report,
    create_incident_report_payload,
    create_post_incident_review_payload,
    create_submitted_report,
    get_success_data,
    make_airport_manager_headers,
    make_safety_officer_headers,
    set_clock,
    setup_compliant_index_c_airport,
    validate_error,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]
SO1 = TEST_USERS["safety_officer_headers"]
SO2 = TEST_USERS["safety_officer_2_headers"]
AM2 = TEST_USERS["airport_manager_2_headers"]

NARRATIVE = (
    "Aircraft N12345 experienced a hydraulic systems failure during landing "
    "rollout on runway 09L at 10:42Z. ARFF units RED-1 and RED-2 responded "
    "within three minutes, applied a foam blanket around the leaking left "
    "main gear, and escorted the airframe to the hardstand. No injuries."
)


class TestReportReviewRevisionLoop:
    def test_loop_returned_resets_to_draft_and_cycle_count_increments(self, api):
        """PRD §3.10: "Return moves `SUBMITTED` back to `RETURNED` and
        increments `review_cycle_count` by one." and "While a report is
        `DRAFT` or `RETURNED`, the author may edit it; editing updates
        `narrative` and/or `agent_expenditure_lines`, recomputes
        `agent_expense_total_cents` by the same rounding-pinned formula, and —
        when the previous status was `RETURNED` — resets status to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/nl_report_review_revision_loop
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_draft_report(inc["id"], narrative=NARRATIVE,
                                  author_user_id="user-so-1")
        # Submit -> Return -> PATCH (resets to DRAFT) -> Submit -> Accept
        api.submit_incident_report(rep["id"], SO1)
        api.return_incident_report(rep["id"], AM)
        # PATCH the RETURNED report
        resp = api.patch_incident_report(
            rep["id"],
            {"narrative": NARRATIVE + " Amended with timeline."},
            SO1,
        )
        patched = validate_success(resp)
        assert patched["status"] == "DRAFT"
        api.submit_incident_report(rep["id"], SO1)
        api.accept_incident_report(rep["id"], AM)
        final = get_success_data(api.get_incident_report(rep["id"], SO1))
        assert final["status"] == "ACCEPTED"
        assert final["review_cycle_count"] == 1

    def test_return_on_accepted_report_rejected(self, api):
        """PRD §3.10: "Both accept and return require the report currently be
        `SUBMITTED` (otherwise `ERR_REPORT_NOT_REVIEWABLE`)..."

        Design: Difficulty/non_linear_state_machine/nl_report_review_revision_loop
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_submitted_report(inc["id"], narrative=NARRATIVE)
        api.accept_incident_report(rep["id"], AM)
        # Return on ACCEPTED must be rejected
        resp = api.return_incident_report(rep["id"], AM)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_REVIEWABLE)


class TestAgentExpensePerLineRounding:
    def test_per_line_rounding_pinned_total(self, api):
        """PRD §3.10: "Each line's cost in cents is the line's
        `water_gal_used` multiplied by 137 plus the line's `dry_chem_lb_used`
        multiplied by 89, rounded half-up to a whole cent. The report's
        `agent_expense_total_cents` is the sum of the per-line rounded cents.
        Round per line first, then sum — never the reverse."

        Design: Difficulty/combinatorial_formula/cf_agent_expense_per_line_rounding
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_2",
                                         location="Runway 09L midfield")
        lines = [
            {"vehicle_id": ctx["veh1"]["id"], "water_gal_used": 3.5,
             "dry_chem_lb_used": 0},
            {"vehicle_id": ctx["veh2"]["id"], "water_gal_used": 3.5,
             "dry_chem_lb_used": 0},
            {"vehicle_id": ctx["veh1"]["id"], "water_gal_used": 0,
             "dry_chem_lb_used": 2.5},
        ]
        rep = create_draft_report(
            inc["id"], narrative=NARRATIVE, agent_expenditure_lines=lines,
            author_user_id="user-so-1",
        )
        # 480 + 480 + 223 = 1183; sum-then-round would give 1182
        assert rep["agent_expense_total_cents"] == 1183

    def test_per_line_rounding_not_sum_then_round(self, api):
        """PRD §2.7: "Agent-expense lines are rounded per line using
        round-half-up before summation — the rounding order is pinned and not
        negotiable: round each line to a whole cent first, then sum the
        rounded line cents to form the report total."

        Design: Difficulty/combinatorial_formula/cf_agent_expense_per_line_rounding
        """
        ctx = setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway B")
        # A single 3.5 gal line: 3.5*137 = 479.5 -> 480
        lines = [
            {"vehicle_id": ctx["veh1"]["id"], "water_gal_used": 3.5,
             "dry_chem_lb_used": 0},
        ]
        rep = create_draft_report(
            inc["id"], narrative=NARRATIVE, agent_expenditure_lines=lines,
            author_user_id="user-so-1",
        )
        assert rep["agent_expense_total_cents"] == 480


class TestReportWindowExpired:
    def test_report_creation_past_ten_days_rejected(self, api):
        """PRD §3.10: "The creation must occur within ten days of the
        incident's `controlled_at`, inclusive; a report attempted more than
        ten days after is rejected with `ERR_REPORT_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/pp_report_window_temporal_beats_narrative_constraint
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway B")
        # Advance clock 11 days past control
        set_clock("2026-05-12T00:00:00Z")
        resp = api.create_incident_report(
            inc["id"], {"narrative": "Too short."}, SO1,
        )
        # Temporal (priority 7) beats constraint (priority 8)
        validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_EXPIRED)

    def test_report_window_expired_masks_narrative_too_short(self, api):
        """PRD §2.10: "When multiple rules could fire on the same request,
        the system applies them in priority order so that earlier errors mask
        later ones."

        Design: Difficulty/priority_pair_validation_conflict/pp_report_window_temporal_beats_narrative_constraint
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway B")
        set_clock("2026-05-12T00:00:00Z")
        # Both failures present: window expired AND narrative too short
        resp = api.create_incident_report(
            inc["id"], {"narrative": "x"}, SO1,
        )
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_REPORT_WINDOW_EXPIRED"
        assert body["data"]["error_id"] != "ERR_NARRATIVE_TOO_SHORT"


class TestReportAuthorOnlySubmitAndPatch:
    def test_other_safety_officer_submit_rejected(self, api):
        """PRD §3.10: "The author (and only the author — `X-User-ID` must
        equal `author_user_id`, otherwise `ERR_NOT_REPORT_AUTHOR`) may submit
        a `DRAFT` report, moving it to `SUBMITTED`..."

        Design: Corner/rbac/rbac_report_author_only_submit_and_patch
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_draft_report(inc["id"], narrative=NARRATIVE,
                                  author_user_id="user-so-1")
        assert rep["author_user_id"] == "user-so-1"
        resp = api.submit_incident_report(rep["id"], SO2)
        validate_error(resp, ApiErrorId.ERR_NOT_REPORT_AUTHOR)

    def test_other_safety_officer_patch_rejected(self, api):
        """PRD §3.10: "Edits by anyone other than the author are rejected
        with `ERR_NOT_REPORT_AUTHOR`; edits on a `SUBMITTED` or `ACCEPTED`
        report are rejected with `ERR_REPORT_NOT_EDITABLE`."

        Design: Corner/rbac/rbac_report_author_only_submit_and_patch
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_draft_report(inc["id"], narrative=NARRATIVE,
                                  author_user_id="user-so-1")
        resp = api.patch_incident_report(
            rep["id"],
            {"narrative": NARRATIVE + " Edited."},
            SO2,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_REPORT_AUTHOR)


class TestSelfApprovalForbidden:
    def test_accept_by_author_rejected_even_with_manager_role(self, api):
        """PRD §3.10: "Both accept and return require the report currently be
        `SUBMITTED` (otherwise `ERR_REPORT_NOT_REVIEWABLE`), and both forbid
        the reviewer being the original author — a reviewer whose `X-User-ID`
        equals `author_user_id` is rejected with
        `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/rbac/rbac_self_approval_forbidden
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_submitted_report(inc["id"], narrative=NARRATIVE,
                                      author_user_id="user-so-1")
        # Same X-User-ID but AirportManager role — still forbidden
        mgr_as_author = make_airport_manager_headers("user-so-1")
        resp = api.accept_incident_report(rep["id"], mgr_as_author)
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_different_reviewer_succeeds(self, api):
        """PRD §3.10: "Accept moves `SUBMITTED` to `ACCEPTED` (terminal)."

        Design: Corner/rbac/rbac_self_approval_forbidden
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_submitted_report(inc["id"], narrative=NARRATIVE,
                                      author_user_id="user-so-1")
        mgr_other = make_airport_manager_headers("user-am-9")
        resp = api.accept_incident_report(rep["id"], mgr_other)
        accepted = validate_success(resp)
        assert accepted["status"] == "ACCEPTED"


class TestReportReviewErrorBattery:
    def test_review_on_non_accepted_report_rejected(self, api):
        """PRD §3.11: "The parent report must currently be `ACCEPTED`;
        opening a review on a non-`ACCEPTED` report is rejected with
        `ERR_REPORT_NOT_ACCEPTED`."

        Design: Corner/errors/err_report_review_flow_error_battery
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_draft_report(inc["id"], narrative=NARRATIVE,
                                  author_user_id="user-so-1")
        resp = api.create_post_incident_review(
            rep["id"],
            create_post_incident_review_payload(
                findings="Early", corrective_actions_open=0,
            ),
            SO1,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_ACCEPTED)

    def test_patch_and_submit_on_submitted_report_rejected(self, api):
        """PRD §3.10: "Edits by anyone other than the author are rejected
        with `ERR_NOT_REPORT_AUTHOR`; edits on a `SUBMITTED` or `ACCEPTED`
        report are rejected with `ERR_REPORT_NOT_EDITABLE`." and "submitting
        a non-`DRAFT` report is rejected with `ERR_REPORT_NOT_SUBMITTABLE`."

        Design: Corner/errors/err_report_review_flow_error_battery
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_submitted_report(inc["id"], narrative=NARRATIVE,
                                      author_user_id="user-so-1")
        r1 = api.patch_incident_report(rep["id"], {"narrative": "x"}, SO1)
        validate_error(r1, ApiErrorId.ERR_REPORT_NOT_EDITABLE)
        r2 = api.submit_incident_report(rep["id"], SO1)
        validate_error(r2, ApiErrorId.ERR_REPORT_NOT_SUBMITTABLE)

    def test_duplicate_open_review_and_close_with_open_actions(self, api):
        """PRD §3.11: "At most one `OPEN` review may exist per report; a
        second open attempt is rejected with `ERR_REVIEW_ALREADY_OPEN`." and
        "Closure moves `OPEN` to `CLOSED` and requires the review currently
        be `OPEN` (otherwise `ERR_REVIEW_NOT_CLOSABLE`) and
        `corrective_actions_open` to equal zero — a close attempt with any
        actions outstanding is rejected with `ERR_ACTIONS_STILL_OPEN`."

        Design: Corner/errors/err_report_review_flow_error_battery
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_accepted_report(inc["id"], narrative=NARRATIVE,
                                     author_user_id="user-so-1")
        rev1 = validate_success(
            api.create_post_incident_review(
                rep["id"],
                create_post_incident_review_payload(
                    findings="Foam usage high", corrective_actions_open=2,
                ),
                SO1,
            ),
            expected_status=201,
        )
        # Second open review rejected
        resp = api.create_post_incident_review(
            rep["id"],
            create_post_incident_review_payload(
                findings="Second", corrective_actions_open=0,
            ),
            SO1,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_OPEN)
        # Close with actions open rejected
        resp = api.close_post_incident_review(rev1["id"], SO1)
        validate_error(resp, ApiErrorId.ERR_ACTIONS_STILL_OPEN)

    def test_patch_and_close_on_closed_review_rejected(self, api):
        """PRD §3.11: "While `OPEN`, the `SafetyOfficer` may patch `findings`
        or `corrective_actions_open` to track progress; a patch on a `CLOSED`
        review is rejected with `ERR_REVIEW_NOT_EDITABLE`." and "Closure
        moves `OPEN` to `CLOSED` and requires the review currently be `OPEN`
        (otherwise `ERR_REVIEW_NOT_CLOSABLE`)..."

        Design: Corner/errors/err_report_review_flow_error_battery
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_accepted_report(inc["id"], narrative=NARRATIVE,
                                     author_user_id="user-so-1")
        rev = validate_success(
            api.create_post_incident_review(
                rep["id"],
                create_post_incident_review_payload(
                    findings="Findings", corrective_actions_open=0,
                ),
                SO1,
            ),
            expected_status=201,
        )
        api.close_post_incident_review(rev["id"], SO1)
        r1 = api.patch_post_incident_review(
            rev["id"], {"findings": "late edit"}, SO1,
        )
        validate_error(r1, ApiErrorId.ERR_REVIEW_NOT_EDITABLE)
        r2 = api.close_post_incident_review(rev["id"], SO1)
        validate_error(r2, ApiErrorId.ERR_REVIEW_NOT_CLOSABLE)


class TestArffChiefCannotAcceptReport:
    def test_accept_by_arff_chief_rejected_unauthorized(self, api):
        """PRD §2.1: "After the headers validate, the role is checked against
        the endpoint's authorization list; a role not permitted for the
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_arff_chief_cannot_accept_report_unauthorized
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        rep = create_submitted_report(inc["id"], narrative=NARRATIVE,
                                      author_user_id="user-so-1")
        resp = api.accept_incident_report(rep["id"], AC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
