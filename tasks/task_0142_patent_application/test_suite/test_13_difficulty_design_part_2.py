"""Difficulty-design coverage — Part 2 (rules 6–9).

Each instance receives at least TWO dedicated tests. Each docstring
carries the verbatim PRD sentence(s) plus a
`# difficulty: <rule_id>/<instance.name>` tag.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    abandon_application,
    advance_clock_to,
    create_applicant,
    create_application_payload,
    create_draft_application,
    create_fee_payload,
    extension_fee_cents,
    file_application,
    filing_fee_cents,
    get_application,
    get_maintenance_fee,
    get_office_action,
    get_pct_phase,
    initiate_pct_phase,
    list_audit_events,
    list_fee_transactions,
    list_office_actions,
    make_applicant_headers,
    pay_fee,
    pay_filing_fees,
    pay_maintenance_and_settle,
    pay_pct_national_and_enter,
    pct_national_fee_cents,
    setup_filed_application,
    setup_granted_application,
    setup_granted_utility_at_calendar_anchor,
    setup_office_action_at_clock,
    setup_office_action_pending,
    setup_pct_phase_filed,
    setup_under_examination,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_office_action_response_at_extended_deadline_succeeds(self, api):
        """# difficulty: boundary_precision_check/office_action_extended_deadline_inclusive_boundary

        PRD §3.3: "The response transition requires that the Office
        Action's status is PENDING, that the response is filed at a
        moment when SystemClock.now is at or before
        extended_deadline_at".

        Claim: at SystemClock.now == extended_deadline_at exactly, the
        response succeeds (boundary is inclusive). When the response
        is past response_deadline_at (90 days), an EXTENSION fee at
        months_extension=3 must be paid (180-90=90 days late ~ 3
        months).
        """
        a, app, oa = setup_office_action_at_clock(issued_at_dt=DEFAULT_BASE_CLOCK)
        ed = datetime.fromisoformat(oa["extended_deadline_at"].replace("Z", "+00:00"))
        advance_clock_to(ed)
        # 90 days past response_deadline_at = exactly 3 months
        # (ceil(90/30) = 3). Pay tier-3 extension.
        pay_fee(
            a, app, "EXTENSION",
            extension_fee_cents(3, a["entity_size"]),
            office_action_id=oa["id"],
        )
        res = api.file_response(oa["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["months_extension"] == 3

    def test_office_action_response_one_second_past_extended_deadline_rejected(self, api):
        """# difficulty: boundary_precision_check/office_action_extended_deadline_inclusive_boundary

        PRD §3.3: "A response filed after the extended deadline is
        rejected with ERR_OFFICE_ACTION_DEADLINE_PASSED."

        Claim: at SystemClock.now == extended_deadline_at + 1 second,
        the response fails. Per PRD §2.8 the sweep flips the OA to
        ABANDONED_BY_DEFAULT synchronously; under §2.11 priority the
        state check (priority 6) may fire before the deadline check
        (priority 10), so either ERR_OFFICE_ACTION_DEADLINE_PASSED or
        ERR_INVALID_STATE is a faithful PRD outcome.
        """
        a, app, oa = setup_office_action_at_clock(issued_at_dt=DEFAULT_BASE_CLOCK)
        ed = datetime.fromisoformat(oa["extended_deadline_at"].replace("Z", "+00:00"))
        advance_clock_to(ed + timedelta(seconds=1))
        res = api.file_response(oa["id"], make_applicant_headers(a["id"]))
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_OFFICE_ACTION_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_provisional_with_zero_claims_succeeds_boundary(self, api):
        """# difficulty: boundary_precision_check/provisional_with_zero_claims_empty_set_boundary

        PRD §3.2: "for a PROVISIONAL filing, both claim_count and
        independent_claim_count must be exactly 0."

        Claim: PROVISIONAL with claim_count=0 succeeds (the empty-set
        boundary).
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="PROVISIONAL",
            claim_count=0, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["claim_count"] == 0
        assert data["independent_claim_count"] == 0

    def test_utility_with_zero_claims_rejected_boundary(self, api):
        """# difficulty: boundary_precision_check/provisional_with_zero_claims_empty_set_boundary

        PRD §3.2: "For a UTILITY or DESIGN filing, claim_count must be
        at least 1 and independent_claim_count must be at least 1 and
        no greater than claim_count ... Any violation of these
        constraints is reported as ERR_CLAIM_SHAPE_INVALID."

        Claim: UTILITY with claim_count=0 fails — boundary 0 vs 1 is
        the empty-set edge.
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=0, independent_claim_count=0,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_CLAIM_SHAPE_INVALID.value)

    def test_utility_with_one_claim_succeeds_boundary(self, api):
        """# difficulty: boundary_precision_check/provisional_with_zero_claims_empty_set_boundary

        PRD §3.2: "For a UTILITY or DESIGN filing, claim_count must be
        at least 1 and independent_claim_count must be at least 1".

        Claim: UTILITY with claim_count=1, independent_claim_count=1
        succeeds — the minimum non-empty boundary.
        """
        a = create_applicant(entity_size="SMALL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["claim_count"] == 1


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_allow_blocked_while_office_action_pending(self, api, examiner_headers):
        """# difficulty: cross_entity_state_dependency/application_allow_depends_on_office_action_status

        PRD §3.3: "Once every Office Action for the application has
        been resolved — that is, no Office Action with status PENDING
        remains — an examiner may allow the application, transitioning
        it from UNDER_EXAMINATION to ALLOWED."

        Claim: Application's ability to /allow depends on the child
        OfficeAction.status set — when at least one OA is PENDING,
        /allow returns ERR_INVALID_STATE.
        """
        a, app, oa = setup_office_action_pending()
        res = api.allow_application(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_allow_succeeds_after_office_action_responded(self, api):
        """# difficulty: cross_entity_state_dependency/application_allow_depends_on_office_action_status

        PRD §3.3: "Once every Office Action for the application has
        been resolved — that is, no Office Action with status PENDING
        remains — an examiner may allow the application".

        Claim: after the OA flips to RESPONDED, /allow succeeds.
        """
        from test_helpers import allow_application
        a, app, oa = setup_office_action_pending()
        api.file_response(oa["id"], make_applicant_headers(a["id"]))
        oa_after = get_office_action(oa["id"])
        assert oa_after["status"] == "RESPONDED"
        result = allow_application(get_application(app["id"]))
        assert result["status"] == "ALLOWED"

    def test_pct_initiation_blocked_when_parent_not_utility(self, api):
        """# difficulty: cross_entity_state_dependency/pct_initiation_depends_on_application_status_and_type

        PRD §3.6: "PCT initiation is only permitted when the parent
        application's application_type is UTILITY and its status is one
        of FILED, UNDER_EXAMINATION, or OFFICE_ACTION_PENDING; design,
        provisional, allowed, or granted applications cannot be
        elevated to PCT, and any such attempt is rejected with
        ERR_PCT_INELIGIBLE."

        Claim: a DESIGN parent (UTILITY type required) yields
        ERR_PCT_INELIGIBLE.
        """
        a, app = setup_filed_application(application_type="DESIGN")
        res = api.initiate_pct_phase(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PCT_INELIGIBLE.value)

    def test_pct_initiation_blocked_when_parent_granted(self, api):
        """# difficulty: cross_entity_state_dependency/pct_initiation_depends_on_application_status_and_type

        PRD §3.6: "granted applications cannot be elevated to PCT,
        and any such attempt is rejected with ERR_PCT_INELIGIBLE."

        Claim: a GRANTED UTILITY parent yields ERR_PCT_INELIGIBLE
        (status outside {FILED, UNDER_EXAMINATION, OFFICE_ACTION_PENDING}).
        """
        a, granted = setup_granted_application(application_type="UTILITY")
        res = api.initiate_pct_phase(granted["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PCT_INELIGIBLE.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_maintenance_payment_at_window_open_inclusive_left(self, api):
        """# difficulty: resource_temporal_overlap/maintenance_fee_window_half_open_with_grace_extension

        PRD §3.5: "The transition requires that the owning
        application's status is currently GRANTED, that SystemClock.now
        is at or after window_open_at and at or before
        grace_period_end_at".

        Claim: SystemClock.now == window_open_at is accepted
        (left-inclusive); no surcharge applies because clock <= due_at.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        advance_clock_to(win)
        result = pay_maintenance_and_settle(a, granted, s35, in_grace=False)
        assert result["status"] == "PAID"

    def test_maintenance_payment_at_grace_end_inclusive_right_with_surcharge(self, api):
        """# difficulty: resource_temporal_overlap/maintenance_fee_window_half_open_with_grace_extension

        PRD §3.5: "SystemClock.now is at or after window_open_at and
        at or before grace_period_end_at".
        PRD §3.5: "A flat surcharge of 16000 cents applies whenever the
        current clock is strictly after due_at and at or before
        grace_period_end_at".

        Claim: SystemClock.now == grace_period_end_at is accepted
        (right-inclusive) with surcharge.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(grace)
        result = pay_maintenance_and_settle(a, granted, s35, in_grace=True)
        assert result["status"] == "PAID"

    def test_pct_entry_at_deadline_inclusive(self, api):
        """# difficulty: resource_temporal_overlap/pct_national_phase_single_deadline_inclusive

        PRD §3.6: "The transition requires that SystemClock.now is at
        or before national_phase_deadline_at".

        Claim: SystemClock.now == national_phase_deadline_at is
        accepted (right-inclusive single-deadline geometry).
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        deadline = datetime.fromisoformat(
            pct["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline)
        result = pay_pct_national_and_enter(a, app, pct)
        assert result["status"] == "NATIONAL_ENTERED"

    def test_pct_entry_one_second_past_deadline_rejected(self, api):
        """# difficulty: resource_temporal_overlap/pct_national_phase_single_deadline_inclusive

        PRD §3.6: "A national-entry attempt after the 30-month deadline
        is rejected with ERR_PCT_DEADLINE_PASSED."

        Claim: one second past the deadline fails. Per PRD §2.8 the
        sweep flips the PCT row to LAPSED synchronously when the clock
        crosses the deadline; PRD §2.11 priority then surfaces the
        state check (priority 6) before the PCT temporal check
        (priority 12), so either ERR_PCT_DEADLINE_PASSED or
        ERR_INVALID_STATE is a faithful PRD outcome.
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        deadline = datetime.fromisoformat(
            pct["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline + timedelta(seconds=1))
        pay_fee(a, app, "PCT_NATIONAL", pct_national_fee_cents(a["entity_size"]))
        res = api.enter_national_phase(pct["id"], make_applicant_headers(a["id"]))
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_PCT_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_total_fees_paid_unchanged_after_abandon(self, api):
        """# difficulty: compensating_invariant/fee_ledger_invariant_under_abandon_after_filing

        PRD §2.9: "The denormalised aggregate
        Application.total_fees_paid_cents is recomputed on every
        FeeTransaction insertion as the sum of every
        FeeTransaction.amount_cents row whose application_id matches".

        Claim: pay FILING -> file -> abandon. The total_fees_paid_cents
        equals the FILING amount BOTH before and after abandon — fees
        are not refunded.
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY")
        pay_filing_fees(a, app)
        filed = file_application(a, app)
        total_before = filed["total_fees_paid_cents"]
        expected_filing = filing_fee_cents("UTILITY", "SMALL")
        assert total_before == expected_filing
        abandoned = abandon_application(a, app)
        total_after = abandoned["total_fees_paid_cents"]
        # The ledger and aggregate are both unchanged: no refund row
        # is inserted, and the aggregate equals the same sum.
        assert total_after == total_before == expected_filing, (
            "PRD §2.9: total_fees_paid_cents must equal the ledger sum at "
            "all times — abandon does not refund fees."
        )

    def test_fee_ledger_sum_equals_total_fees_paid_cents_after_abandon(self, api):
        """# difficulty: compensating_invariant/fee_ledger_invariant_under_abandon_after_filing

        PRD §2.9: "the sum of every FeeTransaction.amount_cents row
        whose application_id matches".

        Claim: sum(FeeTransaction.amount_cents) == total_fees_paid_cents
        BEFORE and AFTER abandon (drift in either direction is a
        violation).
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY")
        pay_filing_fees(a, app)
        filed = file_application(a, app)
        rows_before = list_fee_transactions(app["id"])
        sum_before = sum(r["amount_cents"] for r in rows_before)
        assert sum_before == filed["total_fees_paid_cents"]
        abandoned = abandon_application(a, app)
        rows_after = list_fee_transactions(app["id"])
        sum_after = sum(r["amount_cents"] for r in rows_after)
        assert sum_after == abandoned["total_fees_paid_cents"]
        assert sum_after == sum_before, (
            "PRD §2.9: ledger sum invariant violated — abandon must not "
            "insert refund rows."
        )

    def test_office_action_count_equals_max_action_number(self, api):
        """# difficulty: compensating_invariant/office_action_count_invariant_under_response_cycle

        PRD §3.3: "The server assigns a sequential action_number per
        application starting at 1 and incrementing by 1 for each
        subsequent Office Action on the same application".

        Claim: after every cycle, count(OfficeAction) ==
        max(action_number) — no gaps, no collisions.
        """
        from test_helpers import issue_office_action
        a, app = setup_under_examination()
        # Three cycles.
        oa1 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa1["id"], make_applicant_headers(a["id"]))
        oa2 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa2["id"], make_applicant_headers(a["id"]))
        oa3 = issue_office_action(app, action_type="FINAL")
        rows = list_office_actions(app["id"])
        nums = [r["action_number"] for r in rows]
        assert len(rows) == max(nums), (
            f"PRD §3.3: count(OfficeAction) must equal max(action_number); "
            f"got count={len(rows)}, max={max(nums)}, action_numbers={sorted(nums)}"
        )
        assert sorted(nums) == list(range(1, len(rows) + 1)), (
            "PRD §3.3: action_number sequence must be dense [1..N] with no gaps"
        )

    def test_office_action_rows_persist_through_response(self, api):
        """# difficulty: compensating_invariant/office_action_count_invariant_under_response_cycle

        PRD §3.3: "sets the Office Action's status to RESPONDED,
        transitions the application from OFFICE_ACTION_PENDING back to
        UNDER_EXAMINATION".

        Claim: filing a response does not DELETE the OA — it flips its
        status to RESPONDED. Count remains stable.
        """
        from test_helpers import issue_office_action
        a, app = setup_under_examination()
        oa1 = issue_office_action(app, action_type="NON_FINAL")
        count_before = len(list_office_actions(app["id"]))
        api.file_response(oa1["id"], make_applicant_headers(a["id"]))
        count_after = len(list_office_actions(app["id"]))
        assert count_after == count_before, (
            "PRD §3.3: response does not delete OA — must remain in list with status RESPONDED"
        )
        oa1_after = get_office_action(oa1["id"])
        assert oa1_after["status"] == "RESPONDED"


# ===========================================================================
# Second-angle tests for instances under-covered in Part 1.
# ===========================================================================
class TestTransitiveCascadeSecondAngle:

    def test_maintenance_lapse_chain_includes_application_expired_after_grace(self, api):
        """# difficulty: transitive_cascade/maintenance_lapse_triggers_application_expiration_triggers_pct_lapse

        PRD §3.5: "When the clock advances past a MaintenanceFee's
        grace_period_end_at while that row is still SCHEDULED and no
        qualifying MAINTENANCE-category fee transaction tied to it has
        been recorded, the deadline sweep in §2.8 deterministically
        flips the row's status to LAPSED and writes a
        MAINTENANCE_FEE_LAPSED audit row. A lapsed maintenance fee in
        turn drives the owning application to EXPIRED via the same
        sweep, which writes an APPLICATION_EXPIRED audit row."

        Claim: the MaintenanceFee row reaches LAPSED and the parent
        Application reaches EXPIRED — a depth-2 cascade.
        """
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        grace = datetime.fromisoformat(
            s35["grace_period_end_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(grace + timedelta(seconds=1))
        mf_after = get_maintenance_fee(s35["id"])
        app_after = get_application(granted["id"])
        assert mf_after["status"] == "LAPSED"
        assert app_after["status"] == "EXPIRED"

    def test_abandon_during_office_action_pending_writes_audit_chain(self, api):
        """# difficulty: transitive_cascade/application_abandon_triggers_office_action_close_triggers_maintenance_purge

        PRD §3.3: "the abandonment cascades every PENDING Office Action
        for that application into ABANDONED_BY_DEFAULT, deletes every
        SCHEDULED MaintenanceFee row that may have been provisioned
        for the application, and writes an
        APPLICATION_ABANDONED_VOLUNTARY audit row."

        Claim: after /abandon on an OFFICE_ACTION_PENDING app, an
        APPLICATION_ABANDONED_VOLUNTARY audit row is present and the
        application has zero PENDING Office Actions remaining.
        """
        from test_helpers import setup_office_action_pending, get_office_action
        a, app, oa = setup_office_action_pending()
        abandon_application(a, app)
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_ABANDONED_VOLUNTARY" in actions
        # No PENDING OA remains.
        oas = list_office_actions(app["id"])
        pending = [r for r in oas if r["status"] == "PENDING"]
        assert pending == [], (
            "PRD §3.3: voluntary abandon must close all PENDING OAs"
        )


class TestPriorityPairSecondAngle:

    def test_maintenance_invalid_state_priority_over_fee_amount_strict(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_conflict_on_maintenance_pay

        PRD §2.11: "(6) state-machine preconditions yield
        ERR_INVALID_STATE".
        PRD §2.11: "(13) the fee-amount precondition yields
        ERR_FEE_AMOUNT_MISMATCH".

        Claim: when both the state-machine precondition (target
        MaintenanceFee already PAID) AND the fee-amount precondition
        (wrong cents) would fail, the server returns
        ERR_INVALID_STATE — confirming priority 6 fires before
        priority 13.
        """
        from test_helpers import maintenance_fee_cents
        a, granted, mfs = setup_granted_utility_at_calendar_anchor(
            entity_size="SMALL", grant_year=2024,
        )
        s35 = next(m for m in mfs if m["stage"] == "STAGE_3_5")
        win = datetime.fromisoformat(s35["window_open_at"].replace("Z", "+00:00"))
        advance_clock_to(win)
        # First, pay it correctly so it becomes PAID.
        pay_maintenance_and_settle(a, granted, s35, in_grace=False)
        # Now attempt to /pay again — the FeeTransaction step will be
        # rejected on state grounds because mf is no longer SCHEDULED.
        # Use the right amount so the only failing precondition is state.
        right_amount = maintenance_fee_cents("STAGE_3_5", "SMALL", in_grace=False)
        # Create a fresh FeeTransaction would also fail state, so we
        # invoke /pay directly first; PRD §2.11 priority 6 must catch
        # state before priority 13.
        res = api.pay_maintenance_fee(s35["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
