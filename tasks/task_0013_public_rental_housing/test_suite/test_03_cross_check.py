"""Multi-department cross-check: the six conditions of PRD §3.2 and the resulting
SCORED / REJECTED branching, plus boundary precision on the per-capita income threshold
(SCAFFOLD_DIFFICULTY_DESIGN: per_capita_income_strict_greater_than).

# difficulty: boundary_precision_check/per_capita_income_strict_greater_than
# difficulty: priority_pair_validation_conflict/cross_check_referential_vs_safety
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_application_in_draft,
    create_program,
    create_sync_event_payload,
    emit_civil_affairs_for,
    emit_full_passing_sync_events,
    emit_public_security_for,
    emit_tax_income_assets_for,
    fresh_applicant_id,
    make_applicant_headers,
    make_household_member,
    public_security_identity_payload,
    setup_occupant_with_specific_citizen,
    submit_and_cross_check,
    INTEGRATION_HEADERS,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# The six conditions (PRD §3.2)
# ──────────────────────────────────────────────────────────


def test_cross_check_passes_with_all_six_conditions_satisfied():
    """PRD §3.2: "When all six pass, the application moves from UNDER_REVIEW to SCORED;
    the server writes verified_monthly_income_cents and verified_total_assets_cents
    from the latest TAX_INCOME_ASSETS payload, sets cross_check_status to PASSED".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(program["id"])
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    assert application["status"] == "SCORED"
    assert application["cross_check_status"] == "PASSED"
    assert isinstance(application.get("queue_score"), int)


def test_cross_check_household_registration_mismatch_rejected():
    """PRD §3.2: "if any member is missing from the household register, the cross-check
    fails with ERR_HOUSEHOLD_REGISTRATION_MISMATCH".
    """
    program = create_program()
    members = [
        make_household_member(citizen_id="C-A"),
        make_household_member(citizen_id="C-B"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    # Civil affairs lists only C-A — C-B missing.
    emit_civil_affairs_for(program["id"], application["id"], ["C-A"])
    emit_public_security_for(
        program["id"], application["id"], ["C-A", "C-B"], all_verified=True
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_HOUSEHOLD_REGISTRATION_MISMATCH")


def test_cross_check_identity_verification_failure_rejected():
    """PRD §3.2: "if any is not, the cross-check fails with ERR_IDENTITY_VERIFICATION_FAILED"."""
    program = create_program()
    members = [
        make_household_member(citizen_id="C-A"),
        make_household_member(citizen_id="C-B"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_civil_affairs_for(program["id"], application["id"], ["C-A", "C-B"])
    # Public security says only C-A verified.
    records = [
        {"citizen_id": "C-A", "identity_verified": True},
        {"citizen_id": "C-B", "identity_verified": False},
    ]
    api.emit_sync_event(
        program["id"],
        create_sync_event_payload(
            "PUBLIC_SECURITY_IDENTITY",
            "APPLICATION",
            application["id"],
            public_security_identity_payload(records),
        ),
        INTEGRATION_HEADERS,
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_IDENTITY_VERIFICATION_FAILED")


# ──────────────────────────────────────────────────────────
# Per-capita income threshold — boundary precision (PRD §3.2)
# # difficulty: boundary_precision_check/per_capita_income_strict_greater_than
# ──────────────────────────────────────────────────────────


class TestPerCapitaIncomeBoundary:
    """PRD §3.2: "monthly_income_cents divided by family_size must not exceed
    per_capita_income_threshold_cents; equality passes, strictly greater fails with
    ERR_INCOME_OVER_THRESHOLD".

    # difficulty: boundary_precision_check/per_capita_income_strict_greater_than
    """

    def _setup(self, program, monthly_income_cents):
        members = [
            make_household_member(citizen_id=f"CIT-A-{monthly_income_cents}"),
            make_household_member(citizen_id=f"CIT-B-{monthly_income_cents}"),
        ]
        application, applicant_id = create_application_in_draft(
            program["id"], household_members=members
        )
        citizen_ids = [m["citizen_id"] for m in members]
        emit_civil_affairs_for(program["id"], application["id"], citizen_ids)
        emit_public_security_for(
            program["id"], application["id"], citizen_ids, all_verified=True
        )
        emit_tax_income_assets_for(
            program["id"],
            application["id"],
            monthly_income_cents=monthly_income_cents,
            total_assets_cents=0,
        )
        return application, applicant_id

    def test_at_exact_threshold_passes(self):
        """PRD §3.2: "equality passes, strictly greater fails". With family_size=2 and
        per_capita_income_threshold_cents=300000, monthly_income=600000 yields per-capita
        300000 — equality, must pass.
        """
        program = create_program(per_capita_income_threshold_cents=300_000)
        application, applicant_id = self._setup(program, monthly_income_cents=600_000)
        application = submit_and_cross_check(program["id"], application["id"], applicant_id)
        assert application["status"] == "SCORED"

    def test_one_cent_above_threshold_rejected(self):
        """PRD §3.2: "strictly greater fails with ERR_INCOME_OVER_THRESHOLD". With
        family_size=2 and threshold 300000, monthly_income=600002 yields per-capita
        300001 — strictly greater, must fail.
        """
        program = create_program(per_capita_income_threshold_cents=300_000)
        application, applicant_id = self._setup(program, monthly_income_cents=600_002)
        validate_success(
            api.submit_application(
                program["id"], application["id"], make_applicant_headers(applicant_id)
            )
        )
        res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
        validate_error(res, "ERR_INCOME_OVER_THRESHOLD")


def test_cross_check_assets_over_threshold_rejected():
    """PRD §3.2: "total_assets_cents divided by family_size must not exceed
    per_capita_asset_threshold_cents; equality passes, strictly greater fails with
    ERR_ASSETS_OVER_THRESHOLD".
    """
    program = create_program(
        per_capita_income_threshold_cents=10_000_000,  # large so income passes
        per_capita_asset_threshold_cents=500_000,
    )
    members = [
        make_household_member(citizen_id="C-X"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_civil_affairs_for(program["id"], application["id"], ["C-X"])
    emit_public_security_for(program["id"], application["id"], ["C-X"], all_verified=True)
    emit_tax_income_assets_for(
        program["id"],
        application["id"],
        monthly_income_cents=100_000,
        total_assets_cents=500_001,  # strictly greater than threshold
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_ASSETS_OVER_THRESHOLD")


def test_cross_check_existing_housing_detected():
    """PRD §3.2: "No citizen_id in household_members may already appear as an occupant
    on any other Contract whose status is ACTIVE, DEPOSIT_PAID, or SIGNED within the
    same program; an existing occupancy fails with ERR_EXISTING_HOUSING_DETECTED".
    """
    program = create_program(notice_period_length=1, grace_period_length=2)
    shared_id = "CIT-DUP-1"
    # Create the first applicant who reaches OCCUPIED on this citizen_id.
    setup_occupant_with_specific_citizen(program["id"], shared_id)
    # Now a brand-new application that tries to enrol the same citizen.
    members = [
        make_household_member(citizen_id=shared_id, relation="SELF"),
        make_household_member(citizen_id="CIT-FRESH", relation="SPOUSE"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_full_passing_sync_events(program["id"], application)
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_EXISTING_HOUSING_DETECTED")


def test_cross_check_not_under_review_rejected():
    """PRD §3.2: "Cross-check requires that the application be in UNDER_REVIEW (else
    ERR_APPLICATION_NOT_UNDER_REVIEW)".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(program["id"])
    # Application is still in DRAFT.
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_APPLICATION_NOT_UNDER_REVIEW")


# ──────────────────────────────────────────────────────────
# Failure branch sets rejection_reason and transitions to REJECTED
# ──────────────────────────────────────────────────────────


def test_cross_check_failure_transitions_to_rejected_with_reason():
    """PRD §3.2: "When any one of the six fails, the application moves from UNDER_REVIEW
    to REJECTED; cross_check_status is set to FAILED, rejection_reason is set to the
    specific failing error_id from the list above".
    """
    program = create_program(per_capita_income_threshold_cents=300_000)
    members = [
        make_household_member(citizen_id="C-1"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_civil_affairs_for(program["id"], application["id"], ["C-1"])
    emit_public_security_for(program["id"], application["id"], ["C-1"], all_verified=True)
    emit_tax_income_assets_for(
        program["id"],
        application["id"],
        monthly_income_cents=300_001,  # strictly greater for family_size=1
        total_assets_cents=0,
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_INCOME_OVER_THRESHOLD")
    # Application now REJECTED with rejection_reason set.
    application = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert application["status"] == "REJECTED"
    assert application["cross_check_status"] == "FAILED"
    assert application.get("rejection_reason") == "ERR_INCOME_OVER_THRESHOLD"


# ──────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict/cross_check_referential_vs_safety
# Two-reader note: PRD §3.2 explicitly orders the checks: "the household-registration
# check fires before identity verification, identity verification before income, income
# before assets, and asset before existing-housing". So when CIVIL_AFFAIRS_HOUSEHOLD is
# missing a citizen AND that same citizen is already an occupant, the household
# registration error must win.
# ──────────────────────────────────────────────────────────


def test_referential_household_mismatch_wins_over_safety_existing_housing():
    """PRD §3.2: "ordering matters because the household-registration check fires before
    identity verification, identity verification before income, income before assets,
    and asset before existing-housing, so the rejection_reason on a borderline
    application reflects the highest-precedence failing check rather than an arbitrary
    one".

    # difficulty: priority_pair_validation_conflict/cross_check_referential_vs_safety
    """
    program = create_program(notice_period_length=1, grace_period_length=2)
    shared_id = "CIT-REF-SAFETY"
    # Plant an occupant with shared_id.
    setup_occupant_with_specific_citizen(program["id"], shared_id)
    # New application uses shared_id, but CIVIL_AFFAIRS lists only the OTHER member.
    members = [
        make_household_member(citizen_id="CIT-NEW", relation="SELF"),
        make_household_member(citizen_id=shared_id, relation="SPOUSE"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    # Civil affairs omits the shared member -> referential mismatch should fire first.
    emit_civil_affairs_for(program["id"], application["id"], ["CIT-NEW"])
    emit_public_security_for(
        program["id"], application["id"], ["CIT-NEW", shared_id], all_verified=True
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=100_000, total_assets_cents=100_000
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_HOUSEHOLD_REGISTRATION_MISMATCH")


def test_referential_household_mismatch_wins_over_safety_again():
    """Second instance for difficulty coverage: re-runs the same precedence claim with
    a different family composition to ensure the order isn't accidental.

    PRD §3.2: "ordering matters because the household-registration check fires before
    identity verification, identity verification before income, income before assets,
    and asset before existing-housing".

    # difficulty: priority_pair_validation_conflict/cross_check_referential_vs_safety
    """
    program = create_program(notice_period_length=1, grace_period_length=2)
    shared_id = "CIT-REF-SAFETY-2"
    setup_occupant_with_specific_citizen(program["id"], shared_id)
    members = [
        make_household_member(citizen_id="CIT-X1", relation="SELF"),
        make_household_member(citizen_id="CIT-X2", relation="CHILD"),
        make_household_member(citizen_id=shared_id, relation="SPOUSE"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    # Omit CIT-X2 entirely -> referential mismatch (different missing member).
    emit_civil_affairs_for(program["id"], application["id"], ["CIT-X1", shared_id])
    emit_public_security_for(
        program["id"], application["id"], ["CIT-X1", "CIT-X2", shared_id], all_verified=True
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=100_000, total_assets_cents=100_000
    )
    validate_success(
        api.submit_application(
            program["id"], application["id"], make_applicant_headers(applicant_id)
        )
    )
    res = api.cross_check_application(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_HOUSEHOLD_REGISTRATION_MISMATCH")


def test_at_exact_threshold_passes_second_instance():
    """Second instance for boundary coverage with a different family size.

    PRD §3.2: "monthly_income_cents divided by family_size must not exceed
    per_capita_income_threshold_cents; equality passes, strictly greater fails with
    ERR_INCOME_OVER_THRESHOLD".

    # difficulty: boundary_precision_check/per_capita_income_strict_greater_than
    """
    program = create_program(per_capita_income_threshold_cents=400_000)
    members = [
        make_household_member(citizen_id="CITZ-1"),
        make_household_member(citizen_id="CITZ-2"),
        make_household_member(citizen_id="CITZ-3"),
    ]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    citizen_ids = [m["citizen_id"] for m in members]
    emit_civil_affairs_for(program["id"], application["id"], citizen_ids)
    emit_public_security_for(
        program["id"], application["id"], citizen_ids, all_verified=True
    )
    emit_tax_income_assets_for(
        program["id"],
        application["id"],
        monthly_income_cents=1_200_000,  # /3 = 400000 = threshold, equality passes
        total_assets_cents=0,
    )
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    assert application["status"] == "SCORED"
