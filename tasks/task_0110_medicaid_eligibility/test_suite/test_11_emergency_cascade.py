"""Public-health emergency overlay: continuous-coverage cascade and
revert.

Exercises PRD §3.5.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    advance_to_redetermination_due,
    get_enrollment,
    get_household,
    issue_emergency_declaration,
    iso_now,
    iso_offset,
    parse_iso,
    run_redetermination_sweep,
    server_now_dt,
    setup_approved_application,
    validate_success,
)


# ===========================================================================
# Federal scope cascades to all states — PRD §3.5
# ===========================================================================
class TestFederalDeclarationCascade:

    def test_federal_declaration_flips_active_to_continuous_coverage(self, api):
        """PRD §3.5: "a FEDERAL declaration covers every enrollment
        regardless of state."
        PRD §3.5: "For each covered Enrollment whose coverage_status is
        currently ACTIVE or REDETERMINATION_DUE, the system transitions
        the coverage_status to CONTINUOUS_COVERAGE."

        Claim: issuing a FEDERAL declaration flips an existing ACTIVE
        enrollment to CONTINUOUS_COVERAGE with
        continuous_coverage_flag=true.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        refreshed = get_enrollment(enrollment["id"])
        assert refreshed["coverage_status"] == "CONTINUOUS_COVERAGE", (
            "FEDERAL declaration must flip ACTIVE → CONTINUOUS_COVERAGE "
            f"per PRD §3.5; got coverage_status="
            f"{refreshed['coverage_status']!r}"
        )
        assert refreshed["continuous_coverage_flag"] is True


# ===========================================================================
# Continuous-coverage revert on emergency expiry — PRD §3.5, §2.11
# ===========================================================================
class TestRevertOnExpiry:

    def test_advance_past_expiry_reverts_to_active(self, api):
        """PRD §3.5: "Continuous coverage persists for as long as at
        least one covering emergency declaration remains ACTIVE. When
        the logical clock advances past the expires_at of the last
        covering declaration, the affected enrollments revert:
        continuous_coverage_flag is set back to false and
        coverage_status is set back to ACTIVE."

        Claim: after the only covering declaration expires, the
        enrollment reverts to ACTIVE.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        # Issue a short-window emergency.
        expires = iso_offset(days=1)
        decl = issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=expires,
        )
        # Confirm CONTINUOUS_COVERAGE.
        mid = get_enrollment(enrollment["id"])
        assert mid["coverage_status"] == "CONTINUOUS_COVERAGE"
        # Advance clock past expiry.
        advance_clock_to(expires)
        after = get_enrollment(enrollment["id"])
        assert after["coverage_status"] == "ACTIVE", (
            "Enrollment must revert to ACTIVE when last covering "
            f"declaration expires per PRD §3.5; got coverage_status="
            f"{after['coverage_status']!r}"
        )
        assert after["continuous_coverage_flag"] is False


# ===========================================================================
# Cascade: pending redetermination withdrawn when enrollment flips
# (PRD §3.5 hop-2)
# ===========================================================================
class TestEmergencyCascadeDepth2:

    def test_pending_redetermination_withdrawn_on_flip(self, api):
        """PRD §3.5: "If the covered enrollment was in
        REDETERMINATION_DUE at the moment of the flip, the system also
        withdraws any associated PENDING Redetermination on that
        enrollment — its status is set to WITHDRAWN."

        Claim: with a PENDING redetermination in flight, issuing an
        emergency declaration flips Enrollment to CONTINUOUS_COVERAGE
        AND flips Redetermination.status from PENDING to WITHDRAWN.

        # difficulty: transitive_cascade/emergency_declaration_cascade_depth_2
        """
        from test_helpers import setup_redetermination_pending
        _sp, household, _, enrollments, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        assert redet["status"] == "PENDING"
        assert enrollment["coverage_status"] == "REDETERMINATION_DUE"
        # Issue federal emergency.
        issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        # Enrollment cascades.
        enrollment_refreshed = get_enrollment(enrollment["id"])
        assert enrollment_refreshed["coverage_status"] == "CONTINUOUS_COVERAGE"
        # Redetermination cascades to WITHDRAWN.
        from test_helpers import get_redetermination
        redet_refreshed = get_redetermination(redet["id"])
        assert redet_refreshed["status"] == "WITHDRAWN", (
            "PENDING Redetermination must cascade to WITHDRAWN when "
            f"Enrollment flips to CONTINUOUS_COVERAGE per PRD §3.5; "
            f"got status={redet_refreshed['status']!r}"
        )


# ===========================================================================
# Emergency declaration computed flag on StatePolicy — PRD §3.5
# ===========================================================================
class TestEmergencyContinuousActive:

    def test_active_federal_makes_state_flag_true(self, api):
        """PRD §3.5: "A StatePolicy's emergency_continuous_active flag
        exposes this overlay to read-side consumers: it is true
        whenever an EmergencyDeclaration with scope FEDERAL, or with
        scope STATE and matching state_code, has status ACTIVE at the
        current clock_now, and false otherwise."

        Claim: a FEDERAL active declaration makes any state policy's
        emergency_continuous_active=true.
        """
        from test_helpers import create_state_policy, random_state_code
        state_code = random_state_code()
        create_state_policy(state_code=state_code)
        issue_emergency_declaration(
            scope="FEDERAL", state_code=None,
            declared_at=iso_now(), expires_at=iso_offset(days=30),
        )
        res = api.get_state_policy(
            state_code, TEST_USERS["policy_admin_headers"],
        )
        data = validate_success(res)
        assert data["emergency_continuous_active"] is True, (
            "emergency_continuous_active must be true when a FEDERAL "
            f"emergency is ACTIVE per PRD §3.5; got "
            f"{data['emergency_continuous_active']!r}"
        )
