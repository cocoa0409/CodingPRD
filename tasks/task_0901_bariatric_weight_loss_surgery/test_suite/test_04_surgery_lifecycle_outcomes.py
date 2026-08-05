"""Surgery completion cascade, complications/readmission cycle, follow-up outcomes,
and self-pay cancellation refund.

Covers difficulty queue A (follow-up series cascade, %EWL dual variant, readmission
cascade, POST_OP<->READMITTED cycle, open-complication conservation, refund money
conservation) and corner queue B (not-found, terminal-state lockdown, ownership,
idempotency).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    setup_scheduled_case, setup_completed_case, setup_postop_with_open_complication,
    create_cleared_self_pay_program, create_surgeon, program_version, get_program,
    first_follow_up_visit_id, make_surgeon_headers,
    create_financing_plan_payload, cancel_surgery_case_payload,
    record_follow_up_visit_payload, complete_surgery_case_payload,
    assert_program_money_conserved,
    FOLLOW_UP_INTERVAL_CODES,
)

PC = TEST_USERS["program_coordinator_headers"]
DT = TEST_USERS["dietitian_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


# ---------------- Difficulty A: surgery completion cascade ----------------

def test_complete_bubbles_program_to_postop(api):
    """PRD §3.5: "The case moves to COMPLETED; the owning program bubbles from
    SURGERY_SCHEDULED to POST_OP; and entering POST_OP auto-generates the post-operative
    follow-up series and enrolls the program's outcome-registry baseline."

    Design: Difficulty/transitive_cascade/surgery_complete_generates_followup_series_cascade
    """
    ctx = setup_completed_case(api)
    assert ctx["case"]["status"] == "COMPLETED", f"expected COMPLETED, got {ctx['case']['status']}"
    assert ctx["program"]["status"] == "POST_OP", f"expected POST_OP, got {ctx['program']['status']}"


def test_complete_generates_five_followup_visits(api):
    """PRD §3.6: "the system generates a fixed five-visit follow-up series so that the
    outcome registry has a complete schedule from day one. Each visit carries an
    interval_code — WEEK_2, WEEK_6, MONTH_3, MONTH_6, and MONTH_12".

    Design: Difficulty/transitive_cascade/surgery_complete_generates_followup_series_cascade
    """
    ctx = setup_completed_case(api)
    visits = validate_success(api.list_follow_up_visits(ctx["program"]["id"], PC))
    assert len(visits) == 5, f"expected 5 follow-up visits, got {len(visits)}"
    assert {v["interval_code"] for v in visits} == set(FOLLOW_UP_INTERVAL_CODES)


# ---------------- Difficulty A: %EWL dual variant ----------------

def test_followup_record_computes_ewl_ibw(api):
    """PRD §3.6: "The ewl_pct_ibw variant divides that numerator by the gap between the
    baseline weight and the program's ideal_body_weight_kg, then multiplies by 100 ...
    storing each to one decimal place rounded half-up and independently of the other."

    Design: Difficulty/dual_variant_calc/weight_loss_outcome_ewl_ibw_vs_bmi25
    """
    ctx = setup_completed_case(api)  # FEMALE 170/120 => baseline 120, IBW 61.437
    fv_id = first_follow_up_visit_id(api, ctx["program"]["id"])
    data = validate_success(api.record_follow_up_visit(
        fv_id, record_follow_up_visit_payload(recorded_weight_kg=100), DT))
    assert data["status"] == "COMPLETED"
    assert data["ewl_pct_ibw"] == 34.2, f"expected 34.2, got {data['ewl_pct_ibw']}"


def test_followup_record_ewl_bmi25_diverges_from_ibw(api):
    """PRD §3.6: "The ewl_pct_bmi25 variant divides the same numerator by the gap between
    the baseline weight and the BMI-25 reference weight ... Because the BMI-25 reference
    weight is larger than the Devine ideal weight, its denominator gap is smaller, so the
    two percentages differ."

    Design: Difficulty/dual_variant_calc/weight_loss_outcome_ewl_ibw_vs_bmi25
    """
    ctx = setup_completed_case(api)
    fv_id = first_follow_up_visit_id(api, ctx["program"]["id"])
    data = validate_success(api.record_follow_up_visit(
        fv_id, record_follow_up_visit_payload(recorded_weight_kg=100), DT))
    assert data["ewl_pct_bmi25"] == 41.9, f"expected 41.9, got {data['ewl_pct_bmi25']}"
    assert data["ewl_pct_ibw"] != data["ewl_pct_bmi25"], "the two %EWL variants must differ"


# ---------------- Difficulty A: complication readmission cascade ----------------

def test_readmission_complication_moves_program_to_readmitted(api):
    """PRD §3.7: "When requires_readmission is true, the program's readmission_count also
    increments; and if the program is currently in POST_OP, that readmission-triggering
    complication moves it from POST_OP to READMITTED."

    Design: Difficulty/transitive_cascade/complication_readmission_cascade
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=True, complication_type="BLEEDING", severity="MODERATE")
    assert ctx["program"]["status"] == "READMITTED", f"expected READMITTED, got {ctx['program']['status']}"


def test_readmission_complication_updates_counters(api):
    """PRD §3.7: "Every new complication starts in OPEN and increments the owning
    program's active_complication_count ... When requires_readmission is true, the
    program's readmission_count also increments".

    Design: Difficulty/transitive_cascade/complication_readmission_cascade
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=True, complication_type="BLEEDING", severity="MODERATE")
    prog = ctx["program"]
    assert prog["readmission_count"] == 1, f"expected 1, got {prog['readmission_count']}"
    assert prog["active_complication_count"] == 1, f"expected 1, got {prog['active_complication_count']}"


# ---------------- Difficulty A: POST_OP <-> READMITTED cycle ----------------

def test_resolve_last_complication_returns_program_to_postop(api):
    """PRD §3.7: "Resolution is also the compensation for a readmission: when the program
    is in READMITTED and this resolution brings the active_complication_count down to
    zero, the program transitions from READMITTED back to POST_OP."

    Design: Difficulty/non_linear_state_machine/program_postop_readmit_postop_cycle
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=True, complication_type="LEAK", severity="SEVERE")
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    validate_success(api.resolve_complication(ctx["complication"]["id"], surgeon_headers))
    prog = get_program(api, ctx["program"]["id"])
    assert prog["status"] == "POST_OP", f"expected POST_OP, got {prog['status']}"
    assert prog["active_complication_count"] == 0, f"expected 0, got {prog['active_complication_count']}"


def test_readmission_count_persists_after_resolution(api):
    """PRD §3.7: "Resolution moves the complication to RESOLVED and decrements the
    program's active_complication_count."
    PRD §2.9: "Resolving the last open complication compensates that readmission by
    returning the program to POST_OP."

    Design: Difficulty/non_linear_state_machine/program_postop_readmit_postop_cycle
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=True, complication_type="LEAK", severity="SEVERE")
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    comp = validate_success(api.resolve_complication(ctx["complication"]["id"], surgeon_headers))
    prog = get_program(api, ctx["program"]["id"])
    assert comp["status"] == "RESOLVED", f"expected RESOLVED, got {comp['status']}"
    assert prog["readmission_count"] == 1, f"readmission_count must remain 1, got {prog['readmission_count']}"


# ---------------- Difficulty A: open-complication count conservation ----------------

def test_resolve_nonreadmit_restores_open_count_zero(api):
    """PRD §3.7: "The active_complication_count is a conserved quantity: it counts exactly
    the program's complications currently in OPEN ... Resolution moves the complication to
    RESOLVED and decrements the program's active_complication_count."

    Design: Difficulty/compensating_invariant/complication_open_count_conservation
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=False, complication_type="INFECTION", severity="MINOR")
    assert ctx["program"]["active_complication_count"] == 1
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    comp = validate_success(api.resolve_complication(ctx["complication"]["id"], surgeon_headers))
    prog = get_program(api, ctx["program"]["id"])
    assert prog["active_complication_count"] == 0, f"expected 0, got {prog['active_complication_count']}"
    assert comp["status"] == "RESOLVED"


def test_resolve_nonreadmit_keeps_program_postop(api):
    """PRD §3.7: "if the program is currently in POST_OP, that readmission-triggering
    complication moves it from POST_OP to READMITTED." (A non-readmission complication
    does not, so the program remains POST_OP with readmission_count unchanged.)

    Design: Difficulty/compensating_invariant/complication_open_count_conservation
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=False, complication_type="INFECTION", severity="MINOR")
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    validate_success(api.resolve_complication(ctx["complication"]["id"], surgeon_headers))
    prog = get_program(api, ctx["program"]["id"])
    assert prog["status"] == "POST_OP", f"expected POST_OP, got {prog['status']}"
    assert prog["readmission_count"] == 0, f"expected 0, got {prog['readmission_count']}"


# ---------------- Difficulty A: cancellation refund money conservation ----------------

def _setup_self_pay_scheduled_with_deposit(api, down_payment_cents=400000):
    prog = create_cleared_self_pay_program(api)
    v0 = program_version(api, prog["id"])
    validate_success(api.create_financing_plan(
        prog["id"], create_financing_plan_payload(v0, down_payment_cents=down_payment_cents), BILL),
        expected_status=201)
    ctx = setup_scheduled_case(api, program=prog)
    return ctx


def test_cancel_self_pay_refunds_and_forfeits(api):
    """PRD §3.5: "the clinic retains a fixed cancellation fee of 100,000 cents,
    forfeiting the smaller of that fee and the amount collected, and refunds the
    remainder. The forfeited amount is added to amount_forfeited_cents and the refunded
    amount to amount_refunded_cents".

    Design: Difficulty/compensating_invariant/cancellation_refund_money_conservation
    """
    ctx = _setup_self_pay_scheduled_with_deposit(api, down_payment_cents=400000)
    validate_success(api.cancel_surgery_case(
        ctx["case"]["id"], cancel_surgery_case_payload(cancellation_reason="patient deferred"), PC))
    prog = get_program(api, ctx["program"]["id"])
    assert prog["amount_forfeited_cents"] == 100000, f"expected 100000, got {prog['amount_forfeited_cents']}"
    assert prog["amount_refunded_cents"] == 300000, f"expected 300000, got {prog['amount_refunded_cents']}"


def test_cancel_self_pay_money_conservation_invariant(api):
    """PRD §3.5: "together they always sum back to the amount that had been collected."

    Design: Difficulty/compensating_invariant/cancellation_refund_money_conservation
    """
    ctx = _setup_self_pay_scheduled_with_deposit(api, down_payment_cents=400000)
    validate_success(api.cancel_surgery_case(
        ctx["case"]["id"], cancel_surgery_case_payload(cancellation_reason="patient deferred"), PC))
    prog = get_program(api, ctx["program"]["id"])
    assert prog["amount_collected_cents"] == 400000, f"expected 400000, got {prog['amount_collected_cents']}"
    assert_program_money_conserved(prog)


# ---------------- Corner B: not-found ----------------

def test_surgery_case_not_found_on_get(api):
    """PRD §2.8: "a surgery case ERR_SURGERY_CASE_NOT_FOUND ... each with HTTP status 404."

    Design: Corner/entities/surgery_case_not_found_on_get_returns_404
    """
    validate_error(api.get_surgery_case(NON_EXISTENT_UUID, PC),
                   ApiErrorId.ERR_SURGERY_CASE_NOT_FOUND.value)


def test_complication_not_found_on_resolve(api):
    """PRD §2.8: "a complication ERR_COMPLICATION_NOT_FOUND ... each with HTTP status 404."

    Design: Corner/state_machines/complication_not_found_on_resolve_returns_404
    """
    validate_error(api.resolve_complication(NON_EXISTENT_UUID, TEST_USERS["surgeon_headers"]),
                   ApiErrorId.ERR_COMPLICATION_NOT_FOUND.value)


def test_follow_up_visit_not_found_on_record(api):
    """PRD §2.8: "a follow-up visit ERR_FOLLOW_UP_VISIT_NOT_FOUND — each with HTTP
    status 404."

    Design: Corner/state_machines/follow_up_visit_not_found_on_record_returns_404
    """
    validate_error(
        api.record_follow_up_visit(NON_EXISTENT_UUID, record_follow_up_visit_payload(recorded_weight_kg=100), DT),
        ApiErrorId.ERR_FOLLOW_UP_VISIT_NOT_FOUND.value)


# ---------------- Corner B: terminal-state / idempotency ----------------

def test_cancel_already_cancelled_case_returns_invalid_state(api):
    """PRD §3.5: "Cancellation is valid only while the case is in SCHEDULED; cancelling a
    case in any other state is rejected with ERR_INVALID_SURGERY_STATE (HTTP 409)."

    Design: Corner/endpoints/cancel_already_cancelled_case_returns_invalid_surgery_state
    """
    ctx = setup_scheduled_case(api)
    validate_success(api.cancel_surgery_case(
        ctx["case"]["id"], cancel_surgery_case_payload(cancellation_reason="first cancel"), PC))
    validate_error(api.cancel_surgery_case(
        ctx["case"]["id"], cancel_surgery_case_payload(cancellation_reason="second cancel"), PC),
        ApiErrorId.ERR_INVALID_SURGERY_STATE.value)


def test_complete_by_non_owner_surgeon_returns_unauthorized(api):
    """PRD §3.5: "Completion is restricted to the surgeon whose id matches the case's
    surgeon_id; another surgeon attempting it is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/endpoints/complete_by_non_owner_surgeon_returns_unauthorized
    """
    ctx = setup_scheduled_case(api)
    other_surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    validate_error(
        api.complete_surgery_case(ctx["case"]["id"], complete_surgery_case_payload(actual_or_minutes=95),
                                  make_surgeon_headers(other_surgeon["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value)


def test_resolve_already_resolved_complication_returns_invalid_state(api):
    """PRD §3.7: "The assigned surgeon resolves an open complication, which is valid only
    while the complication is in OPEN; resolving one in any other state is rejected with
    ERR_INVALID_COMPLICATION_STATE (HTTP 409)."

    Design: Corner/endpoints/resolve_already_resolved_complication_returns_invalid_state
    """
    ctx = setup_postop_with_open_complication(
        api, requires_readmission=False, complication_type="INFECTION", severity="MINOR")
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    validate_success(api.resolve_complication(ctx["complication"]["id"], surgeon_headers))
    validate_error(api.resolve_complication(ctx["complication"]["id"], surgeon_headers),
                   ApiErrorId.ERR_INVALID_COMPLICATION_STATE.value)


def test_record_already_completed_followup_returns_invalid_state(api):
    """PRD §3.6: "Recording is valid only while the visit is in SCHEDULED; recording
    against a visit in any other state is rejected with ERR_INVALID_FOLLOWUP_STATE
    (HTTP 409)."

    Design: Corner/endpoints/record_already_completed_followup_returns_invalid_state
    """
    ctx = setup_completed_case(api)
    fv_id = first_follow_up_visit_id(api, ctx["program"]["id"])
    validate_success(api.record_follow_up_visit(fv_id, record_follow_up_visit_payload(recorded_weight_kg=110), DT))
    validate_error(
        api.record_follow_up_visit(fv_id, record_follow_up_visit_payload(recorded_weight_kg=108), DT),
        ApiErrorId.ERR_INVALID_FOLLOWUP_STATE.value)
