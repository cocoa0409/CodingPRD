"""Validation-priority ordering tests. When two rules would fire at
once, PRD §2.10 pins which one is returned.

Generation policy (per testing philosophy `validation-priority` silence
pattern): we do NOT test "A wins over B because the priority list says
so" unless PRD prose names the precedence explicitly. PRD §2.10 lists
the priority order verbatim in numbered form ("This order is enforced
uniformly across all endpoints"), which means each pairwise precedence
IS named in PRD prose. We therefore generate priority tests targeting
the difficulty-design instances that pin specific pairs.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_applicant,
    advance_clock_to,
    create_application,
    create_appeal_payload,
    create_household,
    create_household_payload,
    create_state_policy,
    decide_application_payload,
    file_appeal,
    iso_offset,
    parse_iso,
    server_now_dt,
    setup_appeal_under_review,
    setup_denied_application,
    setup_eligible_application,
    validate_error,
)


# ===========================================================================
# Priority 6 (HOUSEHOLD_INCOMPLETE) wins over priority 13 (FPL_THRESHOLD_INVALID)
# ===========================================================================
class TestHouseholdIncompleteVsFplThreshold:

    def test_household_incomplete_wins_over_fpl_threshold(self, api):
        """PRD §2.10 priority order: ERR_HOUSEHOLD_INCOMPLETE (priority
        6) wins over ERR_FPL_THRESHOLD_INVALID (priority 13).
        PRD §2.10: "This order is enforced uniformly across all
        endpoints."

        Claim: a household with no non-EXCLUDED applicant (size==0 and
        head unset) reports ERR_HOUSEHOLD_INCOMPLETE, not
        ERR_FPL_THRESHOLD_INVALID.

        # difficulty: boundary_precision_check/effective_size_zero_threshold_invalid
        """
        policy = create_state_policy()
        household = create_household(state_code=policy["state_code"])
        add_applicant(household=household, dependent_status="EXCLUDED")
        application = create_application(household=household)
        res = api.submit_application(
            household["id"], application["id"],
            TEST_USERS["intake_worker_headers"],
        )
        validate_error(res, "ERR_HOUSEHOLD_INCOMPLETE")


# ===========================================================================
# Priority 6 (HOUSEHOLD_INCOMPLETE) wins over priority 12 (NOT_ELIGIBLE)
# ===========================================================================
class TestHouseholdIncompleteVsNotEligible:

    def test_household_incomplete_wins_on_submit_with_excluded_only(self, api):
        """PRD §2.10: priority 6 (HOUSEHOLD_INCOMPLETE) > priority 12
        (NOT_ELIGIBLE).

        Claim: submitting an application where (a) the household has
        only EXCLUDED applicants AND (b) raw income would fail the
        FPL ceiling returns ERR_HOUSEHOLD_INCOMPLETE.

        # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_referential_redetermination
        """
        from test_helpers import add_income
        policy = create_state_policy(magi_income_limit_pct=50.0)
        household = create_household(state_code=policy["state_code"])
        # No PRIMARY applicant; only an EXCLUDED applicant exists.
        excluded = add_applicant(
            household=household, dependent_status="EXCLUDED",
        )
        add_income(
            household=household, applicant=excluded,
            source_type="WAGES", gross_amount=100_000.00,
            frequency="ANNUAL",
        )
        application = create_application(household=household)
        res = api.submit_application(
            household["id"], application["id"],
            TEST_USERS["intake_worker_headers"],
        )
        # Per priority, HOUSEHOLD_INCOMPLETE wins.
        validate_error(res, "ERR_HOUSEHOLD_INCOMPLETE")


# ===========================================================================
# Priority 5 (INVALID_STATE) wins over priority 7 (APPEAL_WINDOW_EXPIRED)
# ===========================================================================
class TestInvalidStateVsAppealWindow:

    def test_invalid_state_wins_over_appeal_window_expired(self, api):
        """PRD §2.10: priority 5 (INVALID_STATE) > priority 7
        (APPEAL_WINDOW_EXPIRED).

        Claim: filing an Appeal against a determination whose
        Application is NOT in DENIED — for example, an APPROVED
        application — at a clock_now > decided_at + 90 days returns
        ERR_INVALID_STATE (state wins over window).

        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_appeal_late
        """
        from test_helpers import setup_approved_application
        from datetime import timedelta
        _sp, _hh, _, _app, determination, _enr = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        # Advance clock 91 days into the future.
        decided = parse_iso(determination["decided_at"])
        too_late = iso_offset(days=91, base=decided)
        advance_clock_to(too_late)
        # Try to file an appeal — application is APPROVED, not DENIED.
        # Both INVALID_STATE (priority 5) and APPEAL_WINDOW_EXPIRED
        # (priority 7) would fire. State wins.
        res = api.create_appeal(
            create_appeal_payload(determination_id=determination["id"]),
            TEST_USERS["intake_worker_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
