"""Assessment banding and domain flags, client risk-tier variants, and the
state-before-referential precedence on assessment creation."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_assessment,
    assert_domain_flags_sorted,
    create_assessment_payload,
    set_clock,
    schedule_visit,
    complete_visit,
    setup_active_enrollment,
    setup_risk_divergence,
    setup_shared_nurse_enrollments,
    api_client,
    get_success_data,
)


# ─── Difficulty: provisional vs comprehensive risk ──────
def test_risk_provisional_basis_counts_only_intake_flags(api):
    """PRD 3.1: "The provisional count is narrower: it sums flags only from assessments
    whose instrument_type is INTAKE, and it is intended for use at intake before the
    full battery of instruments has been recorded."
    PRD 3.1: "the tier is `HIGH` when `n` is at least 3, `MODERATE` when `n` is at least 1 but below 3, and `LOW` when `n` is 0."

    Design: Difficulty/dual_variant_calc/client_risk_provisional_vs_comprehensive_diverge
    """
    ctx = setup_risk_divergence()
    risk = validate_success(
        api.get_client_risk(ctx.client_id, ctx.supervisor_headers,
                            params={"basis": "provisional"}), 200)
    assert risk["provisional_flags"] == 1
    assert risk["tier"] == "MODERATE"


def test_risk_comprehensive_basis_counts_all_flags_and_persists(api):
    """PRD 3.1: "The comprehensive count sums the flags across every assessment belonging
    to the client's enrollment regardless of instrument, and this is the value persisted
    to risk_tier."
    PRD 3.1: "the tier is `HIGH` when `n` is at least 3, `MODERATE` when `n` is at least 1 but below 3, and `LOW` when `n` is 0."

    Design: Difficulty/dual_variant_calc/client_risk_provisional_vs_comprehensive_diverge
    """
    ctx = setup_risk_divergence()
    risk = validate_success(api.get_client_risk(ctx.client_id, ctx.supervisor_headers), 200)
    assert risk["comprehensive_flags"] == 3
    assert risk["tier"] == "HIGH"
    client = validate_success(api.get_client(ctx.client_id, ctx.supervisor_headers), 200)
    assert client["risk_tier"] == "HIGH"


# ─── Difficulty: state precedence beats referential ─────
def _assessment_mismatch_on_scheduled_visit():
    """Two active enrollments on one nurse; a SCHEDULED visit on e1. Returns
    (ctx, payload) for an assessment referencing that visit but naming e2 as owner."""
    ctx = setup_shared_nurse_enrollments(count=2)
    e1, e2 = ctx.enrollment_ids
    visit = get_success_data(api_client.create_visit(
        {"enrollment_id": e1, "nurse_id": ctx.nurse_id, "phase": "PREGNANCY",
         "target_date": "2026-06-20", "scheduled_start": "2026-06-20T09:00:00Z",
         "scheduled_end": "2026-06-20T10:00:00Z"},
        ctx.nurse_headers))
    payload = create_assessment_payload(visit["id"], e2, "INTAKE", {"communication": 5})
    return ctx, payload


def test_assessment_on_uncompleted_visit_returns_not_completed(api):
    """PRD 3.7: "The referenced visit must be in COMPLETED status; recording an
    assessment against a visit that is not completed is rejected with
    ERR_VISIT_NOT_COMPLETED."
    PRD 2.8: "the guiding principle is that state legality and structural existence are
    resolved before value-level business constraints."

    Design: Difficulty/priority_pair_validation_conflict/assessment_state_beats_referential_mismatch
    """
    ctx, payload = _assessment_mismatch_on_scheduled_visit()
    res = api.create_assessment(payload, ctx.nurse_headers)
    validate_error(res, ApiErrorId.ERR_VISIT_NOT_COMPLETED.value)


def test_assessment_dual_failure_surfaces_state_error_with_409(api):
    """PRD 3.7: "The referenced visit must be in COMPLETED status; recording an
    assessment against a visit that is not completed is rejected with
    ERR_VISIT_NOT_COMPLETED."
    PRD 2.8: "the guiding principle is that state legality and structural existence are
    resolved before value-level business constraints."

    Design: Difficulty/priority_pair_validation_conflict/assessment_state_beats_referential_mismatch
    """
    ctx, payload = _assessment_mismatch_on_scheduled_visit()
    res = api.create_assessment(payload, ctx.nurse_headers)
    assert res.status_code == 409


# ─── Corner: assessment result band + domain flags ──────
def test_assessment_low_total_bands_refer_with_domain_flags(api):
    """PRD 3.7: "it is ON_TRACK when that total is at least 85, MONITOR when the total is
    at least 70 but below 85, and REFER when the total is below 70. The domain_flags
    array lists every domain whose subscore falls below the domain flag threshold of 10,
    and the flagged domains are ordered by their domain key in ascending order for
    determinism."

    Design: Corner/calculations/assessment_result_band_refer_and_flags
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    visit = schedule_visit(
        ctx, target_date="2026-05-05",
        scheduled_start="2026-05-05T09:00:00Z", scheduled_end="2026-05-05T10:00:00Z",
    )
    complete_visit(visit["id"], "2026-05-05", ctx.nurse_headers)
    res = api.create_assessment(
        create_assessment_payload(
            visit["id"], ctx.enrollment_id, "ASQ", {"communication": 5, "motor": 50}
        ),
        ctx.nurse_headers,
    )
    assessment = validate_success(res, 201)
    assert_assessment(assessment)
    assert assessment["result_band"] == "REFER"
    assert assessment["domain_flags"] == ["communication"]
    assert_domain_flags_sorted(assessment["domain_flags"])
