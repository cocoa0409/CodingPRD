"""Validation precedence, numeric boundaries, interval-overlap rules, OCC, and
header/pagination/fee-model validations. Difficulty rules 5, 6, 8 plus corner-design
validations, errors, OCC, and consistency instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, fixtures, TEST_USERS, ApiErrorId, build_user_headers,
    make_client_contact_headers,
)
from test_helpers.constants import MISSING_UUID

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ==========================================================================
# Difficulty Rule 5 — priority_pair_validation_conflict
# ==========================================================================
class TestValidationPrecedence:
    def test_existence_beats_owner_on_request_changes_nonexistent_proposal(self, api):
        """PRD §2.5: "Third, every resource named in the path and every foreign key
        referenced in the body is confirmed to exist, validated left to right
        (`ERR_NOT_FOUND`). Fourth, for the `ClientContact`-only review operations,
        ownership of the targeted resource's client is enforced
        (`ERR_NOT_RESOURCE_OWNER`)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_owner_on_request_changes_nonexistent_proposal
        """
        client = fixtures.create_client()
        cc = make_client_contact_headers(client["id"])
        validate_error(api.request_changes_proposal(MISSING_UUID, cc),
                       ApiErrorId.ERR_NOT_FOUND.value)

    def test_existence_beats_owner_on_approve_nonexistent_proposal(self, api):
        """PRD §2.5: "Third, every resource named in the path and every foreign key
        referenced in the body is confirmed to exist, validated left to right
        (`ERR_NOT_FOUND`). Fourth, for the `ClientContact`-only review operations,
        ownership of the targeted resource's client is enforced
        (`ERR_NOT_RESOURCE_OWNER`)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_owner_on_request_changes_nonexistent_proposal
        """
        client = fixtures.create_client()
        cc = make_client_contact_headers(client["id"])
        # A ClientContact who owns nothing approving a non-existent proposal: both the
        # existence (3) and ownership (4) checks could fire; existence wins -> 404.
        validate_error(api.approve_proposal(MISSING_UUID, cc),
                       ApiErrorId.ERR_NOT_FOUND.value)

    def test_invalid_state_beats_temporal_on_withdraw_accepted_submission(self, api):
        """PRD §2.5: "Sixth, on a state-transition endpoint, the target resource
        must currently be in a state from which the transition is allowed
        (`ERR_INVALID_STATE`). ... ninth, the submission/withdraw deadline gate
        (`ERR_OPPORTUNITY_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_temporal_on_withdraw_already_accepted_submission
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission(opp_overrides={"deadline_utc": "2026-04-01T00:00:00Z"})
        get_success_data(api.record_decision(ctx["submission"]["id"], "ACCEPTED", AM))
        # Advance the clock past the deadline so the temporal gate would also fire.
        fixtures.set_clock("2026-05-01T00:00:00Z")
        # The submission is already ACCEPTED (not FILED): the lower-numbered state
        # check wins over the temporal gate.
        validate_error(api.withdraw_submission(ctx["submission"]["id"], GW),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_invalid_state_beats_temporal_on_withdraw_rejected_submission(self, api):
        """PRD §2.5: "Sixth, on a state-transition endpoint, the target resource
        must currently be in a state from which the transition is allowed
        (`ERR_INVALID_STATE`). ... ninth, the submission/withdraw deadline gate
        (`ERR_OPPORTUNITY_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_temporal_on_withdraw_already_accepted_submission
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission(opp_overrides={"deadline_utc": "2026-04-01T00:00:00Z"})
        get_success_data(api.record_decision(ctx["submission"]["id"], "REJECTED", AM))
        fixtures.set_clock("2026-05-01T00:00:00Z")
        # Submission is REJECTED (terminal, not FILED) and the clock is past the
        # deadline; the lower-numbered state check (6) wins over the temporal gate (9).
        validate_error(api.withdraw_submission(ctx["submission"]["id"], GW),
                       ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Difficulty Rule 6 — boundary_precision_check
# ==========================================================================
class TestBoundaryPrecision:
    def test_requested_amount_equals_ceiling_is_inclusive(self, api):
        """PRD §3.7: "the proposal's `requested_amount_cents` must fall within the
        opportunity's band — at least the `floor_amount_cents` and at most the
        `ceiling_amount_cents` — otherwise the filing is rejected with
        `ERR_REQUEST_OUT_OF_RANGE`."

        Design: Difficulty/boundary_precision_check/requested_amount_equals_ceiling_is_inclusive_on_submission_create
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_approved_proposal(
            opp_overrides={"ceiling_amount_cents": 200000, "floor_amount_cents": 100000},
            requested_amount_cents=200000)
        prop_v = ctx["proposal"]["version"]
        sub = validate_success(api.create_submission(
            {"proposal_id": ctx["proposal"]["id"], "expected_proposal_version": prop_v}, GW), 201)
        assert sub["status"] == "FILED", f"expected FILED, got {sub['status']}"
        prop = fixtures.get_proposal(ctx["proposal"]["id"])
        assert prop["status"] == "SUBMITTED", f"expected SUBMITTED, got {prop['status']}"

    def test_requested_amount_above_ceiling_rejected(self, api):
        """PRD §3.7: "the proposal's `requested_amount_cents` must fall within the
        opportunity's band — at least the `floor_amount_cents` and at most the
        `ceiling_amount_cents` — otherwise the filing is rejected with
        `ERR_REQUEST_OUT_OF_RANGE`."

        Design: Difficulty/boundary_precision_check/requested_amount_equals_ceiling_is_inclusive_on_submission_create
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_approved_proposal(
            opp_overrides={"ceiling_amount_cents": 200000, "floor_amount_cents": 100000},
            requested_amount_cents=200001)
        prop_v = ctx["proposal"]["version"]
        validate_error(api.create_submission(
            {"proposal_id": ctx["proposal"]["id"], "expected_proposal_version": prop_v}, GW),
            ApiErrorId.ERR_REQUEST_OUT_OF_RANGE.value)

    def test_award_pop_below_cadence_generates_zero_reports(self, api):
        """PRD §3.9: "The number of scheduled reports is the period of performance
        in months divided by the report cadence in months, with any remainder
        discarded — so if the period of performance is shorter than a single cadence
        interval, no reports are generated at all."

        Design: Difficulty/boundary_precision_check/award_pop_below_cadence_generates_zero_reports_empty_set_boundary
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=2, report_cadence_months=3)
        award = fixtures.get_award(ctx["award"]["id"])
        assert award["status"] == "ACTIVE", f"expected ACTIVE, got {award['status']}"
        data, meta = validate_paginated(
            api.list_compliance_reports(CO, params={"award_id": ctx["award"]["id"]}))
        # floor(2/3) = 0 reports.
        assert meta["total_count"] == 0, f"expected 0, got {meta['total_count']}"

    def test_award_pop_at_cadence_generates_one_report(self, api):
        """PRD §3.9: "The number of scheduled reports is the period of performance
        in months divided by the report cadence in months, with any remainder
        discarded — so if the period of performance is shorter than a single cadence
        interval, no reports are generated at all."

        Design: Difficulty/boundary_precision_check/award_pop_below_cadence_generates_zero_reports_empty_set_boundary
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=3, report_cadence_months=3)
        data, meta = validate_paginated(
            api.list_compliance_reports(CO, params={"award_id": ctx["award"]["id"]}))
        # floor(3/3) = 1 report (boundary X where pop == cadence).
        assert meta["total_count"] == 1, f"expected 1, got {meta['total_count']}"


# ==========================================================================
# Difficulty Rule 8 — resource_temporal_overlap
# ==========================================================================
class TestIntervalOverlap:
    def test_billing_period_shared_endpoint_rejected(self, api):
        """PRD §3.8: "Under these closed-interval semantics, two intervals that
        share even a single endpoint month overlap and the new invoice is rejected
        with `ERR_BILLING_PERIOD_OVERLAP`, whereas two consecutive but non-touching
        month intervals do not overlap and are both allowed."

        Design: Difficulty/resource_temporal_overlap/invoice_billing_period_closed_interval_shared_endpoint_rejected
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=12000,
            time_entries=[{"minutes": 60, "period_yyyymm": "202601"},
                          {"minutes": 60, "period_yyyymm": "202602"},
                          {"minutes": 60, "period_yyyymm": "202603"}])
        eng_id = ctx["engagement"]["id"]
        get_success_data(api.create_invoice(
            {"engagement_id": eng_id, "period_start_yyyymm": "202601",
             "period_end_yyyymm": "202602"}, AM))
        # [202602,202603] shares 202602 with the existing [202601,202602] -> reject.
        validate_error(api.create_invoice(
            {"engagement_id": eng_id, "period_start_yyyymm": "202602",
             "period_end_yyyymm": "202603"}, AM),
            ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value)

    def test_billing_period_nontouching_consecutive_allowed(self, api):
        """PRD §3.8: "Under these closed-interval semantics, two intervals that
        share even a single endpoint month overlap and the new invoice is rejected
        with `ERR_BILLING_PERIOD_OVERLAP`, whereas two consecutive but non-touching
        month intervals do not overlap and are both allowed."

        Design: Difficulty/resource_temporal_overlap/invoice_billing_period_closed_interval_shared_endpoint_rejected
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=12000,
            time_entries=[{"minutes": 60, "period_yyyymm": "202601"},
                          {"minutes": 60, "period_yyyymm": "202602"},
                          {"minutes": 60, "period_yyyymm": "202603"},
                          {"minutes": 60, "period_yyyymm": "202604"}])
        eng_id = ctx["engagement"]["id"]
        get_success_data(api.create_invoice(
            {"engagement_id": eng_id, "period_start_yyyymm": "202601",
             "period_end_yyyymm": "202602"}, AM))
        # [202603,202604] is consecutive to but does not touch [202601,202602] -> allowed.
        inv2 = validate_success(api.create_invoice(
            {"engagement_id": eng_id, "period_start_yyyymm": "202603",
             "period_end_yyyymm": "202604"}, AM), 201)
        assert inv2["status"] == "ISSUED", f"expected ISSUED, got {inv2['status']}"

    def test_report_window_touching_endpoint_allowed(self, api):
        """PRD §3.9: "Under these half-open semantics a window that begins exactly
        where another ends merely touches and does not overlap and is allowed,
        whereas any genuine interior overlap is rejected with
        `ERR_REPORT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_window_half_open_touching_endpoint_allowed
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=6)
        # Scheduled windows: (2026-03-01,2026-09-01] and (2026-09-01,2027-03-01].
        # A SUPPLEMENTAL (2027-03-01,2027-04-01] begins exactly where the second
        # scheduled window ends -> merely touches, no interior overlap -> allowed.
        supp = validate_success(api.create_compliance_report(
            {"award_id": ctx["award"]["id"],
             "covers_window_start_utc": "2027-03-01T00:00:00Z",
             "due_utc": "2027-04-01T00:00:00Z", "sequence_index": 99}, CO), 201)
        assert supp["report_type"] == "SUPPLEMENTAL", \
            f"expected SUPPLEMENTAL, got {supp['report_type']}"
        assert supp["status"] == "PENDING", f"expected PENDING, got {supp['status']}"

    def test_report_window_interior_overlap_rejected(self, api):
        """PRD §3.9: "Under these half-open semantics a window that begins exactly
        where another ends merely touches and does not overlap and is allowed,
        whereas any genuine interior overlap is rejected with
        `ERR_REPORT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_window_half_open_touching_endpoint_allowed
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(period_of_performance_months=12, report_cadence_months=6)
        # Scheduled windows: (2026-03-01,2026-09-01] and (2026-09-01,2027-03-01].
        # A SUPPLEMENTAL (2026-06-01,2026-08-01] sits strictly inside the first
        # scheduled window -> genuine interior overlap -> reject.
        validate_error(api.create_compliance_report(
            {"award_id": ctx["award"]["id"],
             "covers_window_start_utc": "2026-06-01T00:00:00Z",
             "due_utc": "2026-08-01T00:00:00Z", "sequence_index": 98}, CO),
            ApiErrorId.ERR_REPORT_WINDOW_OVERLAP.value)


# ==========================================================================
# Corner — validations
# ==========================================================================
class TestValidations:
    def test_missing_user_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed one,
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_headers_returns_400
        """
        validate_error(api.list_clients({"Content-Type": "application/json"}),
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_proposal_create_against_non_pursuing_match_rejected(self, api):
        """PRD §3.4: "The referenced match must be in `PURSUING` status at the time
        the proposal is created; attaching to a match that is not pursuing is
        rejected with `ERR_MATCH_NOT_PURSUING`."

        Design: Corner/validations/match_create_requested_match_not_pursuing_on_proposal_create
        """
        client = fixtures.create_client()
        opp = fixtures.create_opportunity()
        match = get_success_data(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, GW))  # PROPOSED
        eng = fixtures.create_active_engagement(client["id"], fee_model="HOURLY",
                                                hourly_rate_cents=12000)
        validate_error(api.create_proposal(
            {"engagement_id": eng["id"], "match_id": match["id"],
             "requested_amount_cents": 100000}, GW),
            ApiErrorId.ERR_MATCH_NOT_PURSUING.value)

    def test_success_fee_invoice_without_award_rejected(self, api):
        """PRD §3.8: "A success-fee invoice issued without a valid won award is
        rejected with `ERR_NO_AWARD_FOR_SUCCESS_FEE`."

        Design: Corner/validations/invoice_success_fee_without_award_returns_no_award_error
        """
        client = fixtures.create_client()
        eng = fixtures.create_active_engagement(client["id"], fee_model="SUCCESS_FEE",
                                                success_fee_pct=8)
        validate_error(api.create_invoice({"engagement_id": eng["id"]}, AM),
                       ApiErrorId.ERR_NO_AWARD_FOR_SUCCESS_FEE.value)

    def test_hourly_invoice_nothing_to_bill_rejected(self, api):
        """PRD §3.8: "If no `LOGGED` time exists in the window to sweep, the issue
        is rejected with `ERR_NOTHING_TO_BILL`."

        Design: Corner/validations/invoice_hourly_nothing_to_bill_returns_error
        """
        client = fixtures.create_client()
        eng = fixtures.create_active_engagement(client["id"], fee_model="HOURLY",
                                                hourly_rate_cents=12000)
        validate_error(api.create_invoice(
            {"engagement_id": eng["id"], "period_start_yyyymm": "202603",
             "period_end_yyyymm": "202603"}, AM),
            ApiErrorId.ERR_NOTHING_TO_BILL.value)

    def test_submission_below_floor_rejected(self, api):
        """PRD §3.7: "the proposal's `requested_amount_cents` must fall within the
        opportunity's band — at least the `floor_amount_cents` and at most the
        `ceiling_amount_cents` — otherwise the filing is rejected with
        `ERR_REQUEST_OUT_OF_RANGE`."

        Design: Corner/validations/submission_request_out_of_range_below_floor
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_approved_proposal(
            opp_overrides={"floor_amount_cents": 100000, "ceiling_amount_cents": 9000000},
            requested_amount_cents=50000)
        prop_v = ctx["proposal"]["version"]
        validate_error(api.create_submission(
            {"proposal_id": ctx["proposal"]["id"], "expected_proposal_version": prop_v}, GW),
            ApiErrorId.ERR_REQUEST_OUT_OF_RANGE.value)

    def test_submission_after_deadline_returns_opportunity_closed(self, api):
        """PRD §3.7: "The opportunity behind the proposal must be `OPEN` with the
        logical clock strictly before its `deadline_utc`; a closed or past-deadline
        opportunity is rejected with `ERR_OPPORTUNITY_CLOSED`."

        Design: Corner/validations/submission_create_after_deadline_returns_opportunity_closed
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_approved_proposal(
            opp_overrides={"deadline_utc": "2026-04-01T00:00:00Z", "floor_amount_cents": 0})
        prop_v = ctx["proposal"]["version"]
        fixtures.set_clock("2026-05-01T00:00:00Z")
        validate_error(api.create_submission(
            {"proposal_id": ctx["proposal"]["id"], "expected_proposal_version": prop_v}, GW),
            ApiErrorId.ERR_OPPORTUNITY_CLOSED.value)

    def test_pagination_limit_over_max_rejected(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. ... A `limit` or
        `offset` outside these bounds is rejected with `ERR_INVALID_PAGINATION`."

        Design: Corner/validations/pagination_limit_over_max_returns_invalid_pagination
        """
        validate_error(api.list_clients(AM, params={"limit": 101}),
                       ApiErrorId.ERR_INVALID_PAGINATION.value)


# ==========================================================================
# Corner — errors
# ==========================================================================
class TestErrorCatalog:
    def test_award_create_from_non_accepted_submission_rejected(self, api):
        """PRD §3.9: "The underlying submission must be in `ACCEPTED` status, or the
        create is rejected with `ERR_SUBMISSION_NOT_ACCEPTED`."

        Design: Corner/errors/award_create_from_non_accepted_submission_rejected
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        sub_v = ctx["submission"]["version"]
        validate_error(api.create_award(
            {"submission_id": ctx["submission"]["id"], "expected_submission_version": sub_v,
             "awarded_amount_cents": 1000000, "period_of_performance_months": 6,
             "report_cadence_months": 3}, CO),
            ApiErrorId.ERR_SUBMISSION_NOT_ACCEPTED.value)


# ==========================================================================
# Corner — optimistic concurrency
# ==========================================================================
class TestOptimisticConcurrency:
    def test_stale_proposal_version_on_submission_create(self, api):
        """PRD §2.6: "If another writer has advanced the proposal's `version` since
        the filing client last read it, the filing is rejected with
        `ERR_STALE_PROPOSAL_VERSION` (HTTP 412), forcing a re-read before the
        submission may proceed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_proposal_version_on_submission_create
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_review_ready_proposal(opp_overrides={"floor_amount_cents": 0})
        prop_id = ctx["proposal"]["id"]
        cc = make_client_contact_headers(ctx["client"]["id"])
        get_success_data(api.advance_deliverable_content(ctx["deliverable"]["id"], GW))
        get_success_data(api.approve_deliverable(ctx["deliverable"]["id"], cc))
        get_success_data(api.submit_proposal_for_review(prop_id, GW))
        # Capture the IN_REVIEW version, then approve (which bumps version) -> stale.
        stale_v = fixtures.get_proposal(prop_id)["version"]
        get_success_data(api.approve_proposal(prop_id, cc))
        validate_error(api.create_submission(
            {"proposal_id": prop_id, "expected_proposal_version": stale_v}, GW),
            ApiErrorId.ERR_STALE_PROPOSAL_VERSION.value)

    def test_stale_submission_version_on_award_create(self, api):
        """PRD §2.6: "A submission's `version` advances when its decision is
        recorded, so a writer whose view predates the recorded `ACCEPTED` decision
        is working from stale state; creating the award against that outdated
        version is rejected with `ERR_STALE_SUBMISSION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_submission_version_on_award_create
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_filed_submission()
        stale_v = ctx["submission"]["version"]  # captured at FILED, before decision
        get_success_data(api.record_decision(ctx["submission"]["id"], "ACCEPTED", AM))
        validate_error(api.create_award(
            {"submission_id": ctx["submission"]["id"], "expected_submission_version": stale_v,
             "awarded_amount_cents": 1000000, "period_of_performance_months": 6,
             "report_cadence_months": 3}, CO),
            ApiErrorId.ERR_STALE_SUBMISSION_VERSION.value)

    def test_version_increments_on_proposal_mutation(self, api):
        """PRD §2.4: "The `version` begins at its initial value when the resource is
        created and increments by one on each mutation of that resource, while
        `updated_at` is refreshed to the current logical instant on each such
        mutation."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_proposal_mutation
        """
        ctx = fixtures.setup_review_ready_proposal()
        prop_id = ctx["proposal"]["id"]
        v1 = ctx["proposal"]["version"]
        out = validate_success(api.submit_proposal_for_review(prop_id, GW), 200)
        assert out["version"] > v1, f"version should increment from {v1}, got {out['version']}"
        assert out["status"] == "IN_REVIEW"


# ==========================================================================
# Corner — consistency model
# ==========================================================================
class TestConsistency:
    def test_budget_total_visible_immediately_after_line_add(self, api):
        """PRD §2.7: "The general rule is that these computed values are never
        supplied by a client and are always recomputed from their inputs whenever
        those inputs change or when the owning resource is read."

        Design: Corner/consistency_model/budget_total_visible_immediately_after_line_add
        """
        ctx = fixtures.setup_drafting_proposal(requested_amount_cents=200000)
        prop_id = ctx["proposal"]["id"]
        get_success_data(api.create_budget_line(
            {"proposal_id": prop_id, "category": "PERSONNEL", "label": "Staff",
             "amount_cents": 200000}, GW))
        prop = validate_success(api.get_proposal(prop_id, GW), 200)
        assert prop["budget_total_cents"] == 200000, \
            f"expected 200000, got {prop['budget_total_cents']}"
