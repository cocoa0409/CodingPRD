"""Cross-entity cascades, compensating invariants, cross-entity state gates, and
post-award compliance scheduling. Difficulty rules 4, 7, 9 plus corner-design
side-effect / scheduled-action instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, fixtures, TEST_USERS, ApiErrorId, make_client_contact_headers,
)

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["ops_headers"]


# ==========================================================================
# Difficulty Rule 4 — transitive_cascade
# ==========================================================================
class TestTransitiveCascades:
    def test_submission_withdraw_cascades_proposal_and_client_counter(self, api):
        """PRD §3.7: "Withdrawing a submission cascades: the owning proposal is also
        moved to `WITHDRAWN`, and the client's `proposals_submitted_count` is
        recomputed because this proposal no longer counts as submitted."

        Design: Difficulty/transitive_cascade/submission_withdraw_cascades_proposal_then_client_counter_depth3
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        get_success_data(api.withdraw_submission(ctx["submission"]["id"], GW))
        sub = fixtures.get_submission(ctx["submission"]["id"])
        assert sub["status"] == "WITHDRAWN", f"expected WITHDRAWN, got {sub['status']}"
        prop = fixtures.get_proposal(ctx["proposal"]["id"])
        assert prop["status"] == "WITHDRAWN", f"expected WITHDRAWN, got {prop['status']}"
        client = fixtures.get_client(ctx["client"]["id"])
        assert client["proposals_submitted_count"] == 0, \
            f"expected 0, got {client['proposals_submitted_count']}"

    def test_submission_accept_cascades_won_counter_and_win_rate(self, api):
        """PRD §3.7: "Recording `ACCEPTED` moves the submission from `FILED` to
        `ACCEPTED`, requires that the funding opportunity behind the proposal still
        exists (a missing one surfaces as `ERR_NOT_FOUND`), increments the
        submission's `version` by one, recomputes the client's `proposals_won_count`
        upward, recomputes the client's `win_rate_pct`, and makes an award creatable
        from this submission."

        Design: Difficulty/transitive_cascade/submission_accept_cascades_won_counter_then_win_rate_depth2
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        get_success_data(api.record_decision(ctx["submission"]["id"], "ACCEPTED", AM))
        sub = fixtures.get_submission(ctx["submission"]["id"])
        assert sub["status"] == "ACCEPTED", f"expected ACCEPTED, got {sub['status']}"
        client = fixtures.get_client(ctx["client"]["id"])
        assert client["proposals_won_count"] == 1, f"expected 1, got {client['proposals_won_count']}"
        assert client["win_rate_pct"] == 100.0, f"expected 100.0, got {client['win_rate_pct']}"

    def test_submission_withdraw_cascades_owning_proposal_to_withdrawn(self, api):
        """PRD §3.7: "Withdrawing a submission cascades: the owning proposal is also
        moved to `WITHDRAWN`, and the client's `proposals_submitted_count` is
        recomputed because this proposal no longer counts as submitted."

        Design: Difficulty/transitive_cascade/submission_withdraw_cascades_proposal_then_client_counter_depth3
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        # Before withdraw, filing raised the submitted count.
        before = fixtures.get_client(ctx["client"]["id"])["proposals_submitted_count"]
        assert before == 1, f"filing should set submitted_count to 1, got {before}"
        get_success_data(api.withdraw_submission(ctx["submission"]["id"], GW))
        prop = fixtures.get_proposal(ctx["proposal"]["id"])
        assert prop["status"] == "WITHDRAWN", f"owning proposal must cascade, got {prop['status']}"

    def test_submission_accept_recomputes_win_rate_to_full(self, api):
        """PRD §3.7: "the numerator is the count in `ACCEPTED`. When the client has
        no decided submissions the `win_rate_pct` is exactly `0.0` rather than null;
        otherwise it is one hundred times the won count divided by the decided
        count, rounded half up to one decimal place."

        Design: Difficulty/transitive_cascade/submission_accept_cascades_won_counter_then_win_rate_depth2
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        before = fixtures.get_client(ctx["client"]["id"])["win_rate_pct"]
        assert before == 0.0, f"no decided submissions yet -> 0.0, got {before}"
        get_success_data(api.record_decision(ctx["submission"]["id"], "ACCEPTED", AM))
        client = fixtures.get_client(ctx["client"]["id"])
        # 1 won / 1 decided -> 100.0.
        assert client["win_rate_pct"] == 100.0, f"expected 100.0, got {client['win_rate_pct']}"


# ==========================================================================
# Difficulty Rule 9 — compensating_invariant
# ==========================================================================
class TestCompensatingInvariants:
    def test_invoice_void_restores_logged_time_and_zeros_ytd(self, api):
        """PRD §3.8: "An `AccountManager` may void an invoice, moving it from
        `ISSUED` to `VOID`. Voiding restores every time entry the invoice had swept
        back to `LOGGED` and recomputes the engagement's `ytd_billed_cents`."

        Design: Difficulty/compensating_invariant/invoice_void_restores_logged_time_minutes_conserved
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=15000,
            time_entries=[{"minutes": 90, "period_yyyymm": "202603"},
                          {"minutes": 30, "period_yyyymm": "202603"}])
        te1, te2 = ctx["time_entries"]
        inv = get_success_data(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM))
        out = validate_success(api.void_invoice(inv["id"], AM), 200)
        assert out["status"] == "VOID", f"expected VOID, got {out['status']}"
        assert fixtures.get_time_entry(te1["id"])["status"] == "LOGGED"
        assert fixtures.get_time_entry(te2["id"])["status"] == "LOGGED"
        eng = fixtures.get_engagement(ctx["engagement"]["id"])
        assert eng["ytd_billed_cents"] == 0, f"expected 0, got {eng['ytd_billed_cents']}"

    def test_invoice_void_sets_status_void_and_restores_each_entry(self, api):
        """PRD §3.8: "Voiding restores every time entry the invoice had swept back
        to `LOGGED` and recomputes the engagement's `ytd_billed_cents`."

        Design: Difficulty/compensating_invariant/invoice_void_restores_logged_time_minutes_conserved
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=15000,
            time_entries=[{"minutes": 120, "period_yyyymm": "202603"}])
        te = ctx["time_entries"][0]
        inv = get_success_data(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM))
        # The single entry was swept to BILLED at issue time.
        assert fixtures.get_time_entry(te["id"])["status"] == "BILLED"
        get_success_data(api.void_invoice(inv["id"], AM))
        # Voiding restores it to LOGGED (the conserved quantity returns).
        assert fixtures.get_time_entry(te["id"])["status"] == "LOGGED", \
            "void must restore swept time entry to LOGGED"

    def test_submission_withdraw_conserves_submitted_count(self, api):
        """PRD §3.7: "Withdrawing a submission cascades: the owning proposal is also
        moved to `WITHDRAWN`, and the client's `proposals_submitted_count` is
        recomputed because this proposal no longer counts as submitted."

        Design: Difficulty/compensating_invariant/submission_withdraw_after_file_conserves_submitted_count_invariant
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        # After filing, the count is raised; withdrawing must drop it back to 0.
        get_success_data(api.withdraw_submission(ctx["submission"]["id"], GW))
        sub = fixtures.get_submission(ctx["submission"]["id"])
        assert sub["status"] == "WITHDRAWN"
        client = fixtures.get_client(ctx["client"]["id"])
        assert client["proposals_submitted_count"] == 0, \
            f"expected 0, got {client['proposals_submitted_count']}"
        prop = fixtures.get_proposal(ctx["proposal"]["id"])
        assert prop["status"] == "WITHDRAWN"

    def test_submitted_count_returns_to_pre_file_value_after_withdraw(self, api):
        """PRD §3.7: "A successful filing creates the submission in `FILED`, stamps
        it with the opportunity's `portal_name` copied at submission time and a
        `submitted_at_utc` set to the current logical clock, advances the proposal's
        `version` by one, and recomputes the client's `proposals_submitted_count`,
        which counts the client's proposals that ever reached `SUBMITTED` through a
        submission."

        Design: Difficulty/compensating_invariant/submission_withdraw_after_file_conserves_submitted_count_invariant
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        # Filing raised the conserved counter to 1.
        assert fixtures.get_client(ctx["client"]["id"])["proposals_submitted_count"] == 1
        get_success_data(api.withdraw_submission(ctx["submission"]["id"], GW))
        # Withdraw (the compensating action) returns the counter to its pre-file value.
        assert fixtures.get_client(ctx["client"]["id"])["proposals_submitted_count"] == 0


# ==========================================================================
# Difficulty Rule 7 — cross_entity_state_dependency
# ==========================================================================
class TestCrossEntityStateGates:
    def test_proposal_submit_for_review_requires_engagement_active(self, api):
        """PRD §3.6: "The owning engagement must currently be `ACTIVE`, or the
        request is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_for_review_requires_engagement_active
        """
        ctx = fixtures.setup_review_ready_proposal()
        get_success_data(api.pause_engagement(ctx["engagement"]["id"], AM))
        validate_error(api.submit_proposal_for_review(ctx["proposal"]["id"], GW),
                       ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)
        prop = fixtures.get_proposal(ctx["proposal"]["id"])
        assert prop["status"] == "DRAFTING", f"expected DRAFTING, got {prop['status']}"

    def test_proposal_submit_for_review_succeeds_when_engagement_active(self, api):
        """PRD §3.6: "Three conditions guard this transition. The owning engagement
        must currently be `ACTIVE`, or the request is rejected with
        `ERR_ENGAGEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_for_review_requires_engagement_active
        """
        ctx = fixtures.setup_review_ready_proposal()
        # Engagement is ACTIVE (the success direction of the cross-entity gate).
        out = validate_success(api.submit_proposal_for_review(ctx["proposal"]["id"], GW), 200)
        assert out["status"] == "IN_REVIEW", f"expected IN_REVIEW, got {out['status']}"

    def test_compliance_report_file_succeeds_while_award_active(self, api):
        """PRD §3.9: "A `ComplianceOfficer` files a report, moving it from `PENDING`
        to `FILED`, or from `LATE` to `FILED`; either filing requires the owning
        award to still be `ACTIVE` (a closed-out award is rejected with
        `ERR_AWARD_CLOSED`), stamps `submitted_at_utc` to the current logical clock,
        and recomputes the award's `compliance_status`."

        Design: Difficulty/cross_entity_state_dependency/compliance_report_file_requires_award_active
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=3)
        data, meta = validate_paginated(
            api.list_compliance_reports(CO, params={"award_id": ctx["award"]["id"]}))
        report1 = data[0]
        out = validate_success(api.file_compliance_report(report1["id"], CO), 200)
        assert out["status"] == "FILED", f"expected FILED, got {out['status']}"
        award = fixtures.get_award(ctx["award"]["id"])
        assert award["compliance_status"] == "GREEN", \
            f"expected GREEN (no late reports), got {award['compliance_status']}"

    def test_compliance_report_file_stamps_submitted_at_while_award_active(self, api):
        """PRD §3.9: "either filing requires the owning award to still be `ACTIVE`
        (a closed-out award is rejected with `ERR_AWARD_CLOSED`), stamps
        `submitted_at_utc` to the current logical clock, and recomputes the award's
        `compliance_status`."

        Design: Difficulty/cross_entity_state_dependency/compliance_report_file_requires_award_active
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=3)
        data, meta = validate_paginated(
            api.list_compliance_reports(CO, params={"award_id": ctx["award"]["id"]}))
        report1 = data[0]
        out = validate_success(api.file_compliance_report(report1["id"], CO), 200)
        # Award ACTIVE -> filing succeeds (PENDING -> FILED) and stamps submitted_at_utc.
        assert out["status"] == "FILED"
        assert out["submitted_at_utc"] is not None, "submitted_at_utc must be stamped on file"


# ==========================================================================
# Corner — side effects & scheduled actions
# ==========================================================================
class TestComplianceSideEffects:
    def test_clock_advance_flips_pending_report_to_late_and_recomputes_posture(self, api):
        """PRD §2.9: "any compliance report still awaiting filing whose due instant
        is at or before the new clock transitions to `LATE`, after which each
        affected award's compliance posture is recomputed."

        Design: Corner/state_machines/clock_advance_flips_pending_report_to_late_and_recomputes_posture
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=3)
        # First report due 2026-06-01; advance past it (and before the second due 2026-09-01).
        fixtures.set_clock("2026-07-01T00:00:00Z")
        award = fixtures.get_award(ctx["award"]["id"])
        # Exactly one late report -> AT_RISK.
        assert award["compliance_status"] == "AT_RISK", \
            f"expected AT_RISK, got {award['compliance_status']}"

    def test_report_schedule_generates_expected_count(self, api):
        """PRD §3.9: "The number of scheduled reports is the period of performance
        in months divided by the report cadence in months, with any remainder
        discarded — so if the period of performance is shorter than a single
        cadence interval, no reports are generated at all."

        Design: Corner/cross_cutting_complexity_layers/report_schedule_generates_expected_count
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=3)
        data, meta = validate_paginated(
            api.list_compliance_reports(CO, params={"award_id": ctx["award"]["id"]}))
        # floor(12/3) = 4 scheduled reports.
        assert meta["total_count"] == 4, f"expected 4, got {meta['total_count']}"

    def test_ytd_billed_cents_reconciled_after_issue(self, api):
        """PRD §3.8: "Issuing any invoice recomputes the engagement's
        `ytd_billed_cents`."

        Design: Corner/cross_cutting_complexity_layers/ytd_billed_cents_reconciled_after_issue
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=15000,
            time_entries=[{"minutes": 120, "period_yyyymm": "202603"}])
        inv = validate_success(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM), 201)
        assert inv["total_cents"] == 30000
        eng = fixtures.get_engagement(ctx["engagement"]["id"])
        assert eng["ytd_billed_cents"] == 30000, f"expected 30000, got {eng['ytd_billed_cents']}"

    def test_submission_rejected_recomputes_win_rate_denominator(self, api):
        """PRD §3.7: "Recording `REJECTED` moves the submission from `FILED` to
        `REJECTED`, has no precondition, increments the submission's `version` by
        one, and recomputes the client's `win_rate_pct` — here the denominator of
        decided submissions grows while the won numerator is unchanged."

        Design: Corner/state_machines/submission_record_decision_rejected_grows_winrate_denominator
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        get_success_data(api.record_decision(ctx["submission"]["id"], "REJECTED", AM))
        sub = fixtures.get_submission(ctx["submission"]["id"])
        assert sub["status"] == "REJECTED", f"expected REJECTED, got {sub['status']}"
        client = fixtures.get_client(ctx["client"]["id"])
        # 0 won / 1 decided -> 0.0.
        assert client["win_rate_pct"] == 0.0, f"expected 0.0, got {client['win_rate_pct']}"
        assert client["proposals_won_count"] == 0

    def test_deliverable_import_snippet_seeds_body_and_bumps_usage(self, api):
        """PRD §3.4: "doing so seeds the new deliverable's `body` from that snippet
        and recomputes the snippet's `usage_count`, which counts the deliverables
        that imported it."

        Design: Corner/endpoints/deliverable_import_snippet_seeds_body_and_bumps_usage
        """
        ctx = fixtures.setup_drafting_proposal()
        snip = get_success_data(api.create_boilerplate(
            {"client_id": ctx["client"]["id"], "section_key": "ORG_HISTORY",
             "body": "Our org was founded in 1990."}, GW))
        deliv = validate_success(api.create_deliverable(
            {"proposal_id": ctx["proposal"]["id"], "kind": "NARRATIVE",
             "title": "From Snippet", "import_snippet_id": snip["id"]}, GW), 201)
        assert deliv["body"] == "Our org was founded in 1990.", \
            f"body not seeded: {deliv['body']!r}"
        snip_after = fixtures.get_boilerplate(snip["id"])
        assert snip_after["usage_count"] == 1, f"expected 1, got {snip_after['usage_count']}"
