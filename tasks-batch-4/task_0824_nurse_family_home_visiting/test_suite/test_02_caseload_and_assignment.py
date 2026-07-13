"""Nurse assignment, caseload weighting, the caseload-conservation invariant, the
nurse-active precondition, the state-before-fiscal precedence, graduation gating, and
optimistic concurrency on reassignment."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_assignment_payload,
    create_nurse,
    create_supervisor,
    create_client,
    record_consent,
    create_prospect_enrollment,
    activate_enrollment,
    create_assignment,
    get_nurse,
    setup_active_enrollment,
    setup_enrolled_enrollment,
    setup_caseload_three_assignments,
    make_supervisor_headers,
    get_success_data,
    TEST_USERS,
    api_client,
)


# ─── Difficulty: combinatorial caseload weight ──────────
def test_nurse_caseload_weight_is_pinned_sum_of_tiered_high_needs_weights(api):
    """PRD 3.4: "A nurse's current_caseload_weight is then the sum of the per-assignment
    caseload_weight values across all of the nurse's ACTIVE assignments, with each
    per-assignment weight rounded first and the pinned sum then rounded half-up to two
    decimal places."

    Design: Difficulty/combinatorial_formula/caseload_weight_tiered_phase_times_high_needs_multiplier
    """
    nurse_id, _ = setup_caseload_three_assignments()
    nurse = get_nurse(nurse_id)
    assert nurse["current_caseload_weight"] == pytest.approx(3.25, abs=0.001)


def test_per_assignment_caseload_weight_applies_phase_tier_and_multiplier(api):
    """PRD 3.4: "Each phase carries a base weight: PREGNANCY weighs 1.0, INFANCY weighs
    0.8, and TODDLERHOOD weighs 0.6. The base weight for the assignment's
    phase_at_assignment is multiplied by 1.25 when high_needs is true, or by 1.0 when it
    is false, and the product is rounded half-up to two decimal places to yield the
    assignment's caseload_weight."

    Design: Difficulty/combinatorial_formula/caseload_weight_tiered_phase_times_high_needs_multiplier
    """
    _, (a1, a2, a3) = setup_caseload_three_assignments()
    # a1 PREGNANCY/no-needs = 1.0; a2 INFANCY/high-needs = 0.8*1.25 = 1.0;
    # a3 PREGNANCY/high-needs = 1.0*1.25 = 1.25
    assert a1["caseload_weight"] == pytest.approx(1.0, abs=0.001)
    assert a2["caseload_weight"] == pytest.approx(1.0, abs=0.001)
    assert a3["caseload_weight"] == pytest.approx(1.25, abs=0.001)


# ─── Difficulty: caseload conserved on end ──────────────
def test_creating_pregnancy_assignment_adds_full_weight(api):
    """PRD 3.4: "The base weight for the assignment's phase_at_assignment is multiplied
    by 1.25 when high_needs is true, or by 1.0 when it is false, and the product is
    rounded half-up to two decimal places to yield the assignment's caseload_weight."
    PRD 3.4: "A nurse's current_caseload_weight is then the sum of the per-assignment
    caseload_weight values across all of the nurse's ACTIVE assignments, with each
    per-assignment weight rounded first and the pinned sum then rounded half-up to two
    decimal places."

    Design: Difficulty/compensating_invariant/caseload_weight_conserved_on_assignment_end
    """
    ctx = setup_active_enrollment()  # one PREGNANCY assignment, weight 1.0
    nurse = get_nurse(ctx.nurse_id)
    assert nurse["current_caseload_weight"] == pytest.approx(1.0, abs=0.001)


def test_ending_assignment_releases_its_weight_back_to_zero(api):
    """PRD 3.4: "Ending subtracts the assignment's `caseload_weight` from the nurse's `current_caseload_weight` (recomputed over the nurse's remaining active assignments)".

    Design: Difficulty/compensating_invariant/caseload_weight_conserved_on_assignment_end
    """
    ctx = setup_active_enrollment()
    res = api.end_assignment(ctx.assignment_id, ctx.supervisor_headers)
    ended = validate_success(res, 200)
    assert ended["status"] == "ENDED"
    nurse = get_nurse(ctx.nurse_id)
    assert nurse["current_caseload_weight"] == pytest.approx(0.0, abs=0.001)


# ─── Difficulty: assignment requires nurse ACTIVE ───────
def test_assignment_to_inactive_nurse_rejected(api):
    """PRD 3.4: "Next, the target nurse must be employable — `Nurse.status` must be `ACTIVE`, otherwise `ERR_NURSE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_nurse_active
    """
    ctx = setup_enrolled_enrollment(nurse_overrides={"status": "INACTIVE"})
    payload = create_assignment_payload(
        ctx.enrollment_id, ctx.nurse_id, ctx.enrollment_version
    )
    res = api.create_assignment(payload, ctx.supervisor_headers)
    validate_error(res, ApiErrorId.ERR_NURSE_NOT_ACTIVE.value)


def test_assignment_to_on_leave_nurse_rejected(api):
    """PRD 3.4: "Next, the target nurse must be employable — `Nurse.status` must be `ACTIVE`, otherwise `ERR_NURSE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_nurse_active
    """
    ctx = setup_enrolled_enrollment(nurse_overrides={"status": "ON_LEAVE"})
    payload = create_assignment_payload(
        ctx.enrollment_id, ctx.nurse_id, ctx.enrollment_version
    )
    res = api.create_assignment(payload, ctx.supervisor_headers)
    validate_error(res, ApiErrorId.ERR_NURSE_NOT_ACTIVE.value)


# ─── Difficulty: state precedence beats fiscal cap ──────
def _setup_exited_enrollment_and_capped_nurse():
    """Nurse at cap (max 1.0, carrying one PREGNANCY assignment) + a second enrollment
    disenrolled to EXITED. Returns (nurse_id, supervisor_id, exited_enr_id, exited_version)."""
    nurse = create_nurse(full_name="N Cap", max_caseload_weight=1.0)
    supervisor = create_supervisor(full_name="S Cap")

    c1 = create_client(full_name="C Cap1", gestational_age_weeks=20)
    record_consent(c1["id"])
    e1 = activate_enrollment(create_prospect_enrollment(c1["id"])["id"])
    create_assignment(e1["id"], nurse["id"], supervisor["id"], e1["version"])  # at cap 1.0

    c2 = create_client(full_name="C Cap2", gestational_age_weeks=21)
    record_consent(c2["id"])
    e2 = activate_enrollment(create_prospect_enrollment(c2["id"])["id"])
    e2 = get_success_data(
        api_client.disenroll(e2["id"], TEST_USERS["intake_headers"])
    )
    return nurse["id"], supervisor["id"], e2["id"], e2["version"]


def test_unassignable_enrollment_error_precedes_caseload_cap(api):
    """PRD 3.4: "First, the target enrollment must be assignable — its status must be
    ENROLLED or ACTIVE; any other status yields ERR_ENROLLMENT_NOT_ASSIGNABLE."

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_beats_fiscal_cap
    """
    nurse_id, sup_id, e2_id, e2_v = _setup_exited_enrollment_and_capped_nurse()
    payload = create_assignment_payload(e2_id, nurse_id, e2_v)
    res = api.create_assignment(payload, make_supervisor_headers(sup_id))
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ASSIGNABLE.value)


def test_dual_failure_assignment_is_rejected_without_mutating_caseload(api):
    """PRD 3.4: "First, the target enrollment must be assignable — its status must be
    ENROLLED or ACTIVE; any other status yields ERR_ENROLLMENT_NOT_ASSIGNABLE."

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_beats_fiscal_cap
    """
    nurse_id, sup_id, e2_id, e2_v = _setup_exited_enrollment_and_capped_nurse()
    payload = create_assignment_payload(e2_id, nurse_id, e2_v)
    res = api.create_assignment(payload, make_supervisor_headers(sup_id))
    assert res.status_code == 409
    # The rejected create must not have added a phantom assignment weight.
    nurse = get_nurse(nurse_id)
    assert nurse["current_caseload_weight"] == pytest.approx(1.0, abs=0.001)


# ─── Corner: graduation gating ──────────────────────────
def test_graduate_before_toddlerhood_rejected(api, intake_headers):
    """PRD 3.2: "Graduation advances an ACTIVE enrollment to GRADUATED and is permitted
    only once the family has reached the final program phase: the enrollment's
    program_phase must be TODDLERHOOD, otherwise the request is rejected with
    ERR_GRADUATION_TOO_EARLY."

    Design: Corner/state_machines/graduate_before_toddlerhood_rejected
    """
    ctx = setup_active_enrollment()  # PREGNANCY phase, ACTIVE
    res = api.graduate_enrollment(ctx.enrollment_id, intake_headers)
    validate_error(res, ApiErrorId.ERR_GRADUATION_TOO_EARLY.value)


# ─── Corner: OCC stale enrollment version ───────────────
def test_stale_enrollment_version_on_reassignment_rejected(api):
    """PRD 2.7: "If expected_enrollment_version does not match the enrollment's current
    version — because another writer has already advanced it since the caller last read
    it — the request is rejected with ERR_STALE_ENROLLMENT_VERSION (HTTP 412)".

    Design: Corner/cross_cutting/assignment_occ_stale_enrollment_version_conflict
    """
    ctx = setup_enrolled_enrollment()
    stale_version = ctx.enrollment_version
    # First assignment advances the enrollment's version.
    create_assignment(ctx.enrollment_id, ctx.nurse_id, ctx.supervisor_id, stale_version)
    second_nurse = create_nurse(full_name="N Occ2")
    payload = create_assignment_payload(
        ctx.enrollment_id, second_nurse["id"], stale_version
    )
    res = api.create_assignment(payload, ctx.supervisor_headers)
    validate_error(res, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value)
