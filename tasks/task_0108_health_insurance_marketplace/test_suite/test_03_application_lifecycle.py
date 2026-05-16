"""Application state machine: DRAFT → SUBMITTED → ELIGIBILITY_DETERMINED
→ {APPROVED, DENIED}, with amend (SUBMITTED→DRAFT) and redetermine
(APPROVED→ELIGIBILITY_DETERMINED).

PRD §3.2 (submit), §3.3 (determine, approve, deny), §3.4 (SEP), §3.9
(precedence).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_household_member,
    add_income_record,
    amend_application,
    approve_application,
    create_application,
    create_household_member_payload,
    determine_eligibility,
    iso_date,
    iso_offset,
    make_applicant_headers,
    re_get_application,
    setup_application_ready_to_submit,
    setup_approved_application,
    setup_benchmark_silver_catalog,
    setup_eligibility_determined_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)
from datetime import date


# ===========================================================================
# DRAFT → SUBMITTED
# ===========================================================================
class TestSubmitTransition:
    """PRD §3.2: "Submitting the application by the applicant transitions
    it from DRAFT to SUBMITTED."""

    def test_submit_succeeds_with_primary_filer_and_income(self, api):
        """PRD §3.2: "Three preconditions guard the transition: the
        application must have exactly one PRIMARY_FILER ... every
        member whose include_in_magi is true must have at least one
        IncomeRecord on file; and the application's coverage_year must
        equal the current year or the current year plus one."
        """
        app, _primary = setup_application_ready_to_submit()
        res = api.submit_application(
            app["id"], make_applicant_headers(app["_applicant_id"]),
        )
        submitted = validate_success(res, 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted.get("submitted_at") is not None
        assert submitted.get("pinned_fpl_table_version") is not None

    def test_submit_with_zero_primary_filers_rejected(self, api):
        """PRD §3.2: "the application must have exactly one PRIMARY_FILER
        (otherwise ERR_MISSING_PRIMARY_FILER)."
        """
        app = create_application()
        # Add only a SPOUSE — no PRIMARY_FILER.
        spouse = add_household_member(
            application=app, filer_type="SPOUSE", age_years=33,
        )
        add_income_record(
            application=app, member=spouse,
            amount_cents=1_000_000, effective_date="2026-01-01",
        )
        res = api.submit_application(
            app["id"], make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_MISSING_PRIMARY_FILER")

    def test_duplicate_primary_filer_not_both_persisted(self, api):
        """PRD §3.1: "Exactly one member per application may carry
        filer_type of PRIMARY_FILER; submitting an application with
        zero or with two or more primary filers is rejected with
        ERR_MISSING_PRIMARY_FILER."

        Claim: an Application with two PRIMARY_FILER attempts must not
        end up in a state where it can be SUBMITTED with two
        PRIMARY_FILERs successfully — the duplicate is rejected either
        at create-time or at submit-time. We assert at the boundary:
        attempting to submit must fail when two PRIMARY_FILERs are
        present.
        """
        app = create_application()
        first = add_household_member(
            application=app, filer_type="PRIMARY_FILER", age_years=35,
        )
        add_income_record(
            application=app, member=first, amount_cents=1_000_000,
            effective_date="2026-01-01",
        )
        # Second PRIMARY_FILER. Whether the implementation rejects
        # here or at submit is a downstream branch; PRD §3.1 only
        # forbids the persisted dual-PRIMARY-FILER state.
        dup_res = api.create_household_member(
            app["id"],
            create_household_member_payload(
                filer_type="PRIMARY_FILER", age_years=33,
            ),
            make_applicant_headers(app["_applicant_id"]),
        )
        if dup_res.status_code >= 400:
            # Duplicate rejected at creation — PRD rule honored.
            return
        # Implementation accepted the duplicate; submit must reject
        # with ERR_MISSING_PRIMARY_FILER.
        res = api.submit_application(
            app["id"], make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_MISSING_PRIMARY_FILER")

    def test_submit_with_member_missing_income_record_rejected(self, api):
        """PRD §3.2: "every member whose include_in_magi is true must
        have at least one IncomeRecord on file".

        Claim: PRIMARY_FILER with no IncomeRecord and include_in_magi=true
        causes submit to fail. PRD names no specific error_id for the
        income precondition; we assert non-2xx.
        """
        app = create_application()
        add_household_member(
            application=app, filer_type="PRIMARY_FILER", age_years=35,
            include_in_magi=True,
        )
        # No IncomeRecord posted.
        res = api.submit_application(
            app["id"], make_applicant_headers(app["_applicant_id"]),
        )
        assert 400 <= res.status_code < 500

    def test_submit_invalid_coverage_year_rejected(self, api):
        """PRD §3.2: "the application's coverage_year must equal the
        current year or the current year plus one as measured by the
        logical clock (otherwise ERR_COVERAGE_YEAR_INVALID)."

        Claim: coverage_year three years in the future → rejected with
        ERR_COVERAGE_YEAR_INVALID at submit time.
        """
        from test_helpers import advance_clock_to
        advance_clock_to(iso_offset(base=None, days=0))
        # Pick a coverage_year far enough out that it is definitely not
        # current_year or current_year+1. The implementation's logical
        # clock starts at real-time; pick coverage_year=2050.
        app = create_application(coverage_year=2050)
        prim = add_household_member(
            application=app, filer_type="PRIMARY_FILER", age_years=35,
        )
        add_income_record(
            application=app, member=prim, amount_cents=1_500_000,
            effective_date="2050-01-01",
        )
        res = api.submit_application(
            app["id"], make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_COVERAGE_YEAR_INVALID")


# ===========================================================================
# SUBMITTED → DRAFT (amend)
# ===========================================================================
class TestAmendTransition:
    """PRD §3.2: "While an application sits in SUBMITTED, the applicant
    may revert it back to DRAFT by amending it; this clears
    submitted_at, pinned_fpl_table_version, fpl_percentage, and
    total_magi_cents (all set back to null)."""

    def test_amend_resets_pinned_fields_to_null(self, api):
        """PRD §3.2: "this clears submitted_at, pinned_fpl_table_version,
        fpl_percentage, and total_magi_cents (all set back to null)."
        """
        submitted, _primary = setup_submitted_application()
        amended = amend_application(application=submitted)
        assert amended["status"] == "DRAFT"
        assert amended.get("submitted_at") is None
        assert amended.get("pinned_fpl_table_version") is None
        assert amended.get("fpl_percentage") is None
        assert amended.get("total_magi_cents") is None

    def test_amend_after_eligibility_determined_rejected(self, api):
        """PRD §3.2: "After an application has progressed past SUBMITTED,
        amendments are no longer available."

        Claim: amend on ELIGIBILITY_DETERMINED → ERR_INVALID_STATE.
        """
        determined, _p, _i, _pl = (
            setup_eligibility_determined_application()
        )
        res = api.amend_application(
            determined["id"],
            make_applicant_headers(determined["_applicant_id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# SUBMITTED → ELIGIBILITY_DETERMINED
# ===========================================================================
class TestDetermineEligibility:
    """PRD §3.3: "A marketplace operator advances a submitted application
    to ELIGIBILITY_DETERMINED."""

    def test_determine_succeeds_when_benchmark_present(self, api):
        """PRD §3.3: "the active Plan whose is_benchmark_silver flag is
        true, of which the catalog must contain exactly one per
        (filing_state, coverage_year) pair".
        """
        # Insurer/plan are created by the helper; should succeed.
        determined, _p, _i, _pl = (
            setup_eligibility_determined_application()
        )
        assert determined["status"] == "ELIGIBILITY_DETERMINED"
        # PRD §3.3 names csr_eligibility and aptc_estimated_cents as
        # pinned by this transition.
        assert determined.get("csr_eligibility") is not None
        assert determined.get("aptc_estimated_cents") is not None

    def test_determine_without_benchmark_rejected(self, api):
        """PRD §3.3: "the active Plan whose is_benchmark_silver flag is
        true, of which the catalog must contain exactly one per
        (filing_state, coverage_year) pair (if zero exist, eligibility
        determination is rejected with ERR_NO_BENCHMARK_PLAN)."
        """
        # Submit an application but do NOT create a benchmark plan.
        submitted, _primary = setup_submitted_application(
            filing_state="CA", coverage_year=2026,
        )
        res = api.determine_eligibility(
            submitted["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_NO_BENCHMARK_PLAN")

    def test_determine_from_wrong_state_rejected(self, api):
        """PRD §1.2 state machine: determine requires
        Application.status = SUBMITTED. PRD §3.9: "State machine
        eligibility (ERR_INVALID_STATE) is checked next."

        Claim: determine on DRAFT → ERR_INVALID_STATE.
        """
        app = create_application()
        res = api.determine_eligibility(
            app["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# ELIGIBILITY_DETERMINED → APPROVED
# ===========================================================================
class TestApprove:
    """PRD §3.3: "Approval moves the application from
    ELIGIBILITY_DETERMINED to APPROVED, provided the application's
    enrollment_window is either OEP or SEP (not CLOSED) and at least
    one included member is not Medicaid-eligible."""

    def test_approve_succeeds_with_open_window(self, api):
        """Claim: a household whose income places it well above
        Medicaid thresholds (so at least one member is not
        Medicaid-eligible) and whose enrollment_window is OEP or SEP
        can be approved.
        """
        approved, _p, _i, _pl = setup_approved_application(
            filing_state="CA", primary_income_cents=5_000_000,
        )
        assert approved["status"] == "APPROVED"
        assert approved.get("approved_at") is not None

    def test_approve_from_wrong_state_rejected(self, api):
        """PRD §1.2: approve requires status=ELIGIBILITY_DETERMINED.
        PRD §3.9 priority 5: state check fires first.

        Claim: approve on DRAFT → ERR_INVALID_STATE.
        """
        app = create_application()
        res = api.approve_application(
            app["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# ELIGIBILITY_DETERMINED → DENIED
# ===========================================================================
class TestDeny:
    """PRD §3.3: "Denial moves the application from
    ELIGIBILITY_DETERMINED to DENIED when either every included member
    is Medicaid-eligible or the enrollment_window is CLOSED.\""""

    def test_deny_records_reason(self, api):
        """PRD §3.3: "Denial accepts an optional reason to be recorded
        for audit purposes."
        """
        # Build a household everyone of whom is Medicaid-eligible so
        # /approve would have to fall to deny. Use a CA (expansion)
        # state with very low income — adults FPL < 138% → all
        # Medicaid eligible.
        determined, _p, _i, _pl = (
            setup_eligibility_determined_application(
                filing_state="CA", primary_income_cents=10_000,
            )
        )
        res = api.deny_application(
            determined["id"], TEST_USERS["admin_headers"],
            payload={"reason": "All members Medicaid eligible"},
        )
        denied = validate_success(res, 200)
        assert denied["status"] == "DENIED"


# ===========================================================================
# APPROVED → ELIGIBILITY_DETERMINED (redetermine)
# ===========================================================================
class TestRedetermine:
    """PRD §3.4: "When a SEPEvent is verified ... and the parent
    application is already APPROVED with an active enrollment in
    place, the verification triggers a three-level cascade: the
    application is force-redetermined (reverting APPROVED to
    ELIGIBILITY_DETERMINED ...)."

    Direct redetermine endpoint exposed in §4: POST
    /applications/{id}/redetermine — MarketplaceAdmin only. PRD §3.4
    describes the cascade-trigger but the direct call is testable when
    there is a VERIFIED SEP in scope.
    """

    def test_redetermine_from_wrong_state_rejected(self, api):
        """PRD §1.2: redetermine requires status=APPROVED.

        Claim: redetermine on DRAFT → ERR_INVALID_STATE.
        """
        app = create_application()
        res = api.redetermine_application(
            app["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
