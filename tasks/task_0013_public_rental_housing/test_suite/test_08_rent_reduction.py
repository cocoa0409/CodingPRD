"""Rent reduction lifecycle: provisional vs final discount, branching reject/resubmit
cycle, segregation of duties, and overlap on the half-open validity interval.

Covers PRD §3.6 (rent reductions) and supports SCAFFOLD_DIFFICULTY_DESIGN instances:
- rent_reduction_provisional_vs_final (dual_variant_calc)
- rent_reduction_branching_with_revert (non_linear_state_machine)
- rent_reduction_validity_overlap_half_open (resource_temporal_overlap)

# difficulty: dual_variant_calc/rent_reduction_provisional_vs_final
# difficulty: non_linear_state_machine/rent_reduction_branching_with_revert
# difficulty: resource_temporal_overlap/rent_reduction_validity_overlap_half_open
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_program,
    create_rent_reduction_payload,
    emit_tax_income_assets_for,
    make_applicant_headers,
    make_housing_director_headers,
    make_housing_officer_headers,
    setup_active_contract_for_rent_reduction_branch,
    setup_contract_active,
    setup_rent_reduction_in_state,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc/rent_reduction_provisional_vs_final
# ──────────────────────────────────────────────────────────


def test_provisional_vs_final_discount_diverges_when_verified_income_in_other_tier():
    """PRD §3.6: "The provisional discount is computed in two steps. The income ratio
    is declared_hardship_income_cents divided by the parent unit's monthly_base_rent_cents.
    If the ratio is strictly less than 0.30, the base discount is 5000 basis points;
    otherwise if the ratio is strictly less than 0.50, the base discount is 3000 basis
    points; otherwise if the ratio is strictly less than 0.80, the base discount is
    1500 basis points; otherwise the base discount is 0. The category boost adds 1500
    basis points for MAJOR_ILLNESS, 1000 for UNEMPLOYMENT, 1500 for DISABILITY, or
    500 for ELDER_CARE."

    PRD §3.6: "The final_discount_bps is computed by the same tiering and category-boost
    rules as provisional_discount_bps, but using the monthly_income_cents value from
    the latest TAX_INCOME_ASSETS event for the parent application as the income operand
    instead of the applicant's self-declared declared_hardship_income_cents."

    Setup:
    - monthly_base_rent_cents = 100000.
    - declared_hardship_income_cents = 25000 -> ratio 0.25 < 0.30 -> base 5000.
      With UNEMPLOYMENT (+1000), provisional = 6000.
    - verified TAX_INCOME_ASSETS monthly_income_cents = 35000 -> ratio 0.35
      strictly less than 0.50 -> base 3000. With UNEMPLOYMENT (+1000), final = 4000.

    # difficulty: dual_variant_calc/rent_reduction_provisional_vs_final
    """
    program = create_program(notice_period_length=1)
    application, contract, applicant_id = setup_active_contract_for_rent_reduction_branch(
        program["id"]
    )
    applicant_headers = make_applicant_headers(applicant_id)
    rr = validate_success(
        api.create_rent_reduction(
            program["id"],
            contract["id"],
            create_rent_reduction_payload(
                hardship_category="UNEMPLOYMENT",
                declared_hardship_income_cents=25_000,
            ),
            applicant_headers,
        ),
        expected_status=201,
    )
    assert rr["provisional_discount_bps"] == 6000, (
        f"PRD §3.6 provisional expected 6000, got {rr['provisional_discount_bps']}"
    )
    # Emit a verified-income event whose ratio falls in the 0.30..0.50 tier.
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=35_000, total_assets_cents=0
    )
    rr = validate_success(
        api.advance_rent_reduction_to_primary(program["id"], rr["id"], OFFICER_HEADERS)
    )
    primary_headers = make_housing_officer_headers("primary-1")
    rr = validate_success(
        api.advance_rent_reduction_to_secondary(program["id"], rr["id"], primary_headers)
    )
    director_headers = make_housing_director_headers("director-1")
    rr = validate_success(
        api.final_approve_rent_reduction(program["id"], rr["id"], director_headers)
    )
    assert rr["status"] == "FINAL_APPROVED"
    assert rr["final_discount_bps"] == 4000, (
        f"PRD §3.6 final expected 4000, got {rr.get('final_discount_bps')}"
    )
    assert rr["final_discount_bps"] != rr["provisional_discount_bps"]


def test_provisional_vs_final_second_instance_lower_verified_income():
    """Second instance for difficulty coverage. Verified income in the deepest tier so
    the final discount EXCEEDS the provisional.

    PRD §3.6: tier comparisons are strict less-than. With base=100000:
    - declared 60000 -> ratio 0.60 in [0.50, 0.80) -> base 1500. ELDER_CARE (+500) -> 2000.
    - verified 20000 -> ratio 0.20 < 0.30 -> base 5000. ELDER_CARE (+500) -> 5500.

    # difficulty: dual_variant_calc/rent_reduction_provisional_vs_final
    """
    program = create_program(notice_period_length=1)
    application, contract, applicant_id = setup_active_contract_for_rent_reduction_branch(
        program["id"]
    )
    applicant_headers = make_applicant_headers(applicant_id)
    rr = validate_success(
        api.create_rent_reduction(
            program["id"],
            contract["id"],
            create_rent_reduction_payload(
                hardship_category="ELDER_CARE",
                declared_hardship_income_cents=60_000,
            ),
            applicant_headers,
        ),
        expected_status=201,
    )
    assert rr["provisional_discount_bps"] == 2000
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=20_000, total_assets_cents=0
    )
    validate_success(
        api.advance_rent_reduction_to_primary(program["id"], rr["id"], OFFICER_HEADERS)
    )
    validate_success(
        api.advance_rent_reduction_to_secondary(
            program["id"], rr["id"], make_housing_officer_headers("primary-2")
        )
    )
    rr = validate_success(
        api.final_approve_rent_reduction(
            program["id"], rr["id"], make_housing_director_headers("director-2")
        )
    )
    assert rr["final_discount_bps"] == 5500


# ──────────────────────────────────────────────────────────
# Difficulty: non_linear_state_machine/rent_reduction_branching_with_revert
# ──────────────────────────────────────────────────────────


def test_reject_then_resubmit_returns_to_submitted_and_clears_reviewers():
    """PRD §3.6: "The applicant who owns the parent contract may then resubmit a
    rejected reduction, providing optionally updated hardship_category,
    declared_hardship_income_cents, and supporting_documents; this requires the
    reduction to be in REJECTED (else ERR_RENT_REDUCTION_NOT_REJECTED) and requires
    that X-User-ID equal the parent contract's owning applicant's applicant_user_id.
    On success the status returns to SUBMITTED, both reviewer slots
    (primary_review_user_id and secondary_review_user_id) are cleared, and
    provisional_discount_bps is recomputed against whichever values are now in effect."

    # difficulty: non_linear_state_machine/rent_reduction_branching_with_revert
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "REJECTED",
        primary_officer_id="primary-rev",
    )
    assert rr["status"] == "REJECTED"
    res = api.resubmit_rent_reduction(
        program["id"], rr["id"], make_applicant_headers(applicant_id),
        create_rent_reduction_payload(declared_hardship_income_cents=10_000)
    )
    rr2 = validate_success(res)
    assert rr2["status"] == "SUBMITTED"
    # Reviewer slots cleared.
    assert rr2.get("primary_review_user_id") in (None, "")
    assert rr2.get("secondary_review_user_id") in (None, "")


def test_resubmit_by_non_owner_rejected_with_insufficient_permissions():
    """PRD §3.6: "this requires ... that X-User-ID equal the parent contract's owning
    applicant's applicant_user_id".
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "REJECTED",
        primary_officer_id="primary-impostor",
    )
    res = api.resubmit_rent_reduction(
        program["id"],
        rr["id"],
        make_applicant_headers("not-the-owner"),
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_segregation_of_duties_violated_on_final_approve():
    """PRD §3.6: "requires that the director's X-User-ID differs from the recorded
    primary_review_user_id (else ERR_SEGREGATION_OF_DUTIES_VIOLATION at HTTP 403 — a
    single individual may not occupy both review slots)".
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    # Use the same id for primary and director to manufacture the violation.
    rr = setup_rent_reduction_in_state(
        program["id"],
        contract,
        applicant_id,
        "SECONDARY_REVIEW",
        primary_officer_id="dual-role-1",
    )
    same_id_director = make_housing_director_headers("dual-role-1")
    res = api.final_approve_rent_reduction(program["id"], rr["id"], same_id_director)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES_VIOLATION")


def test_advance_to_primary_requires_submitted_state():
    """PRD §3.6: "rejected with ERR_RENT_REDUCTION_NOT_SUBMITTED if not in SUBMITTED"."""
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "PRIMARY_REVIEW",
    )
    res = api.advance_rent_reduction_to_primary(program["id"], rr["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_RENT_REDUCTION_NOT_SUBMITTED")


def test_advance_to_secondary_requires_primary_review_state():
    """PRD §3.6: "rejected with ERR_RENT_REDUCTION_NOT_IN_PRIMARY if not in PRIMARY_REVIEW"."""
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "SUBMITTED",
    )
    res = api.advance_rent_reduction_to_secondary(program["id"], rr["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_RENT_REDUCTION_NOT_IN_PRIMARY")


def test_final_approve_requires_secondary_review_state():
    """PRD §3.6: "this requires SECONDARY_REVIEW (else
    ERR_RENT_REDUCTION_NOT_IN_SECONDARY)".
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "PRIMARY_REVIEW",
    )
    res = api.final_approve_rent_reduction(
        program["id"], rr["id"], make_housing_director_headers("d-x")
    )
    validate_error(res, "ERR_RENT_REDUCTION_NOT_IN_SECONDARY")


def test_branching_with_revert_full_cycle_then_final_approve_succeeds():
    """PRD §3.6 branching/revert: REJECTED -> SUBMITTED via /resubmit, then advance back
    through PRIMARY_REVIEW -> SECONDARY_REVIEW -> FINAL_APPROVED with distinct primary
    and final-approver identities.

    # difficulty: non_linear_state_machine/rent_reduction_branching_with_revert
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    # Path: SUBMITTED -> PRIMARY -> SECONDARY -> REJECTED.
    rr = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "REJECTED",
        primary_officer_id="primary-cycle",
    )
    # Resubmit -> SUBMITTED.
    rr = validate_success(
        api.resubmit_rent_reduction(
            program["id"], rr["id"], make_applicant_headers(applicant_id)
        )
    )
    assert rr["status"] == "SUBMITTED"
    rr = validate_success(
        api.advance_rent_reduction_to_primary(program["id"], rr["id"], OFFICER_HEADERS)
    )
    rr = validate_success(
        api.advance_rent_reduction_to_secondary(
            program["id"], rr["id"], make_housing_officer_headers("primary-cycle-2")
        )
    )
    rr = validate_success(
        api.final_approve_rent_reduction(
            program["id"], rr["id"], make_housing_director_headers("director-cycle")
        )
    )
    assert rr["status"] == "FINAL_APPROVED"


# ──────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap/rent_reduction_validity_overlap_half_open
# ──────────────────────────────────────────────────────────


def test_overlapping_validity_interval_blocked_then_adjacency_permitted():
    """PRD §3.6: "requires that no existing FINAL_APPROVED reduction on the same
    contract has a half-open validity interval [validity_start_period,
    validity_end_period) that intersects the new validity window (else
    ERR_OVERLAPPING_RENT_REDUCTION). On success ... validity_start_period is set to the
    current current_period_index, validity_end_period is set to that period plus 12 (so
    the default validity is twelve periods, half-open)".

    Approve R1 at period 5 (window [5, 17)).
    Then attempt to approve R2 at period 16 -> would be window [16, 28). 16 ∈ [5, 17),
    so overlap -> ERR_OVERLAPPING_RENT_REDUCTION.
    Advance the clock to period 17 and approve again -> window [17, 29). 17 ∉ [5, 17)
    under half-open semantics, so the adjacency case must succeed.

    # difficulty: resource_temporal_overlap/rent_reduction_validity_overlap_half_open
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    # Note: setup_contract_active leaves current_period_index >= 5 typically (it had to
    # advance to satisfy notice). We'll align periods relative to "now".
    # Step 1: approve R1 -> creates window [now, now+12).
    program_now = validate_success(api.get_program(program["id"], OFFICER_HEADERS))
    period_at_r1 = program_now["current_period_index"]
    rr1 = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "FINAL_APPROVED",
        primary_officer_id="prim-overlap-1", director_id="dir-overlap-1",
    )
    assert rr1["validity_start_period"] == period_at_r1
    assert rr1["validity_end_period"] == period_at_r1 + 12

    # Step 2: create R2 and walk to SECONDARY_REVIEW.
    rr2 = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "SECONDARY_REVIEW",
        primary_officer_id="prim-overlap-2",
    )
    # Advance to period_at_r1 + 11 so the new window would be [period+11, period+23) —
    # overlaps the half-open [period_at_r1, period_at_r1+12) at periods period+11..period+11.
    advance_clock_by(program["id"], 11)
    res = api.final_approve_rent_reduction(
        program["id"], rr2["id"], make_housing_director_headers("dir-overlap-2")
    )
    validate_error(res, "ERR_OVERLAPPING_RENT_REDUCTION")
    # Step 3: advance to period_at_r1 + 12. New window [period+12, period+24) — adjacency
    # at the half-open boundary. PRD §3.6 half-open semantics permit it.
    advance_clock_by(program["id"], 1)  # now at period_at_r1 + 12
    res = api.final_approve_rent_reduction(
        program["id"], rr2["id"], make_housing_director_headers("dir-overlap-2-b")
    )
    rr2_final = validate_success(res)
    assert rr2_final["status"] == "FINAL_APPROVED"
    assert rr2_final["validity_start_period"] == period_at_r1 + 12


def test_overlapping_validity_interval_blocked_second_instance():
    """Second instance for difficulty coverage with a different overlap geometry.

    PRD §3.6: "no existing FINAL_APPROVED reduction on the same contract has a half-open
    validity interval [validity_start_period, validity_end_period) that intersects the
    new validity window (else ERR_OVERLAPPING_RENT_REDUCTION)".

    Two reductions submitted on the same contract; R2 attempts approval one period after
    R1 starts -> window [period+1, period+13) overlaps [period, period+12).

    # difficulty: resource_temporal_overlap/rent_reduction_validity_overlap_half_open
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_active(
        program["id"], notice_period_length=1
    )
    setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "FINAL_APPROVED",
        primary_officer_id="po-1", director_id="do-1",
    )
    # New R2 at period+1 — strictly inside [period, period+12).
    rr2 = setup_rent_reduction_in_state(
        program["id"], contract, applicant_id, "SECONDARY_REVIEW",
        primary_officer_id="po-2",
    )
    advance_clock_by(program["id"], 1)
    res = api.final_approve_rent_reduction(
        program["id"], rr2["id"], make_housing_director_headers("do-2")
    )
    validate_error(res, "ERR_OVERLAPPING_RENT_REDUCTION")
