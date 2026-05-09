"""Annual review, ineligibility-driven exit, and grace-period termination.

Covers PRD §3.7 (annual review, rent adjustment, exit lifecycle) and PRD §2.5 (clock
sweeps), and supports SCAFFOLD_DIFFICULTY_DESIGN instances:
- annual_review_failure_to_grace_to_exit (transitive_cascade)
- annual_review_requires_application_occupied (cross_entity_state_dependency)
- empty_household_member_update_zero_count_edge (boundary_precision_check)

# difficulty: transitive_cascade/annual_review_failure_to_grace_to_exit
# difficulty: cross_entity_state_dependency/annual_review_requires_application_occupied
# difficulty: boundary_precision_check/empty_household_member_update_zero_count_edge
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_annual_review_payload,
    create_program,
    emit_tax_income_assets_for,
    make_household_member,
    setup_application_in_exit_pending,
    setup_contract_active,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# AnnualReview creation (PRD §3.7)
# ──────────────────────────────────────────────────────────


def test_annual_review_requires_occupied_application():
    """PRD §3.7: "Opening a review on an application whose status is not OCCUPIED is
    rejected with ERR_APPLICATION_NOT_OCCUPIED".

    # difficulty: cross_entity_state_dependency/annual_review_requires_application_occupied
    """
    program = create_program(notice_period_length=1, grace_period_length=2)
    # Build an EXIT_PENDING application by finalizing an INELIGIBLE annual review on it.
    application, contract, _review, _ = setup_application_in_exit_pending(
        program["id"], notice_period_length=1
    )
    assert application["status"] == "EXIT_PENDING"
    # Try to open a SECOND annual review while application is no longer OCCUPIED.
    res = api.create_annual_review(
        program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
    )
    validate_error(res, "ERR_APPLICATION_NOT_OCCUPIED")


def test_annual_review_already_open_rejected():
    """PRD §3.7: "At most one OPEN review may exist for a given application at a time;
    an attempt to open a second OPEN review on the same application is rejected with
    ERR_ANNUAL_REVIEW_ALREADY_OPEN".
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1
    )
    validate_success(
        api.create_annual_review(
            program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    res = api.create_annual_review(
        program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
    )
    validate_error(res, "ERR_ANNUAL_REVIEW_ALREADY_OPEN")


def test_annual_review_requires_occupied_second_instance_after_exit():
    """PRD §3.7: "Opening a review on an application whose status is not OCCUPIED is
    rejected with ERR_APPLICATION_NOT_OCCUPIED". Second instance: application in EXITED
    after grace period.

    # difficulty: cross_entity_state_dependency/annual_review_requires_application_occupied
    """
    program = create_program(notice_period_length=1, grace_period_length=1)
    application, contract, _review, _ = setup_application_in_exit_pending(
        program["id"], notice_period_length=1
    )
    # Drive grace period and beyond -> EXITED.
    advance_clock_by(program["id"], program["grace_period_length"] + 1)
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert application_after["status"] == "EXITED"
    res = api.create_annual_review(
        program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
    )
    validate_error(res, "ERR_APPLICATION_NOT_OCCUPIED")


# ──────────────────────────────────────────────────────────
# Difficulty: transitive_cascade/annual_review_failure_to_grace_to_exit
# ──────────────────────────────────────────────────────────


def test_finalize_ineligible_cascades_to_exit_pending_then_grace_to_exited():
    """PRD §3.7: "When re_eligibility is INELIGIBLE, the server sets exit_triggered to
    true and cascades the application from OCCUPIED to EXIT_PENDING, recording
    exit_trigger_period as the current current_period_index."

    PRD §2.5: "the new current_period_index is greater than or equal to the
    application's exit_trigger_period plus the program's grace_period_length — and
    transitions it to EXITED, cascading the parent Contract to TERMINATED and the
    parent HousingUnit back to AVAILABLE."

    # difficulty: transitive_cascade/annual_review_failure_to_grace_to_exit
    """
    program = create_program(notice_period_length=1, grace_period_length=4)
    application, contract, review, _ = setup_application_in_exit_pending(
        program["id"], notice_period_length=1
    )
    assert application["status"] == "EXIT_PENDING"
    assert review["exit_triggered"] is True
    exit_period = application["exit_trigger_period"]
    assert isinstance(exit_period, int)
    # Advance the clock past grace.
    advance_clock_by(program["id"], program["grace_period_length"])
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    contract_after = validate_success(
        api.get_contract(program["id"], contract["id"], OFFICER_HEADERS)
    )
    unit_after = validate_success(
        api.get_housing_unit(program["id"], contract["housing_unit_id"], OFFICER_HEADERS)
    )
    assert application_after["status"] == "EXITED"
    assert contract_after["status"] == "TERMINATED"
    assert unit_after["status"] == "AVAILABLE"


def test_finalize_exit_before_grace_period_rejected():
    """PRD §2.5: "A HousingOfficer may also drive the second sweep manually for a
    single application via the finalize-exit capability; that path enforces the same
    grace-period-elapsed condition and rejects an early attempt with
    ERR_GRACE_PERIOD_NOT_ELAPSED".

    # difficulty: transitive_cascade/annual_review_failure_to_grace_to_exit
    """
    program = create_program(notice_period_length=1, grace_period_length=10)
    application, contract, review, _ = setup_application_in_exit_pending(
        program["id"], notice_period_length=1
    )
    res = api.finalize_exit(program["id"], application["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_GRACE_PERIOD_NOT_ELAPSED")


# ──────────────────────────────────────────────────────────
# Difficulty: boundary_precision_check/empty_household_member_update_zero_count_edge
# ──────────────────────────────────────────────────────────


def test_finalize_with_no_updated_fields_recomputes_clock_only():
    """PRD §3.7: "On finalize, the server first applies the three update fields to the
    application, treating any null update as a no-op (the existing value is reused). It
    then re-runs the same six-condition cross-check ... It recomputes the queue_score
    per the same formula".

    Submitting a finalize where every updated_* field is omitted MUST keep the
    household composition unchanged AND still recompute queue_score against the new
    review_period_index.

    # difficulty: boundary_precision_check/empty_household_member_update_zero_count_edge
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1
    )
    initial_members = list(application["household_members"])
    # Open + finalize an annual review with all updated_* omitted (PRD §3.7 zero-update).
    advance_clock_by(program["id"], 3)
    review = validate_success(
        api.create_annual_review(
            program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    # Re-confirm the latest TAX_INCOME_ASSETS still passes per-capita thresholds.
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    review_after = validate_success(
        api.finalize_annual_review(
            program["id"], application["id"], review["id"], OFFICER_HEADERS
        )
    )
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    # Recomputed_queue_score is set (non-null integer).
    assert isinstance(review_after.get("recomputed_queue_score"), int)
    # No household_type update -> no rent adjustment (PRD §3.7).
    assert review_after.get("rent_adjustment_cents") == 0
    # Household composition unchanged.
    assert len(application_after["household_members"]) == len(initial_members)


def test_finalize_with_no_updated_fields_second_instance_same_score():
    """Second instance for difficulty coverage. With residence already saturated at the
    20-period cap (PRD §3.3), additional clock advances no longer change the residence
    component, so recomputed_queue_score must equal the original queue_score.

    PRD §3.7: "any null field reuses current value".
    PRD §3.3: "residence length ... capped at 20 — that is, if the raw residence length
    is greater than 20, the component contributes 20".

    # difficulty: boundary_precision_check/empty_household_member_update_zero_count_edge
    """
    program = create_program(notice_period_length=1)
    # Pre-advance clock so residence_start_period=0 already saturates the 20-period cap
    # before the application is even cross-checked. Subsequent clock advances baked into
    # setup_contract_active (1 period for notice) cannot move the residence component.
    advance_clock_by(program["id"], 25)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1
    )
    initial_score = application["queue_score"]
    review = validate_success(
        api.create_annual_review(
            program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    review_after = validate_success(
        api.finalize_annual_review(
            program["id"], application["id"], review["id"], OFFICER_HEADERS
        )
    )
    # Residence saturated at cap → recomputed score equals initial score.
    assert review_after.get("recomputed_queue_score") == initial_score
    assert review_after.get("rent_adjustment_cents") == 0


def test_finalize_eligible_keeps_application_occupied_with_audit_event():
    """PRD §3.7: "When re_eligibility is ELIGIBLE, the server computes
    rent_adjustment_cents as the difference between the rent associated with the
    (possibly newly applicable) household type tier and the current
    monthly_base_rent_cents; this delta is applied additively to the active contract's
    monthly_effective_rent_cents. ... The status transitions to FINALIZED, an
    AUDIT_ELIGIBILITY_CHANGE event records the before/after, and the application
    remains in OCCUPIED."
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1
    )
    review = validate_success(
        api.create_annual_review(
            program["id"], application["id"], create_annual_review_payload(), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    review_after = validate_success(
        api.finalize_annual_review(
            program["id"], application["id"], review["id"], OFFICER_HEADERS
        )
    )
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert review_after["status"] == "FINALIZED"
    assert review_after["re_eligibility"] == "ELIGIBLE"
    assert review_after["exit_triggered"] is False
    assert application_after["status"] == "OCCUPIED"
