"""Request evaluation pipeline ordering, well-formedness checks, uniqueness,
and not-found behavior (PRD §2.7, §2.10, §3.1, §3.3, §3.6, §3.9)."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_deposit_on,
    create_deposit_payload,
    create_module,
    create_curriculum_module_payload,
    create_participant,
    create_participant_payload,
    create_registration,
    create_snapshot,
    create_funder_report_payload,
    set_clock,
    setup_active_enrollment,
    setup_workshop_scenario,
    validate_error,
    validate_success,
)


def test_not_found_beats_invalid_state(api, admin_headers):
    """PRD §2.10: "The first identifier or reference that does not resolve to
    an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404),
    before any state or business rule is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="DB-401", session_count=2,
                              completion_threshold=2),
    )
    participant = create_participant(admin_headers, full_name="P Nine",
                                     email="p9@test.org")
    reg = create_registration(ctx["workshop"]["id"], participant["id"], admin_headers)
    validate_success(api.cancel_registration(reg["id"], admin_headers))
    # A state error (CANCELLED registration) would be plausible if the id
    # resolved — but a nonexistent id must surface the 404 first.
    resp = api.cancel_registration(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_not_found_returned_even_when_other_entities_would_fail_state(
    api, admin_headers
):
    """PRD §2.7: "Every request is validated in a fixed global order, and the
    first failing check determines the error returned." PRD §2.7, tier 4:
    "Path identifiers and body foreign-key references are resolved left to
    right; the first unresolvable reference yields `ERR_NOT_FOUND` (404)."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="DB-401B", session_count=2,
                              completion_threshold=2),
    )
    participant = create_participant(admin_headers)
    reg = create_registration(ctx["workshop"]["id"], participant["id"], admin_headers)
    validate_success(api.cancel_registration(reg["id"], admin_headers))
    # Mark-attendance on a nonexistent registration id: existence beats the
    # state error a CANCELLED registration would otherwise produce.
    resp = api.mark_attendance(
        NON_EXISTENT_UUID, {"outcome": "ATTENDED"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_enrollment_state_beats_pool_fiscal(api, admin_headers):
    """PRD §2.7, tier 6: "The target entity must be in a valid state for the
    operation (`ERR_INVALID_STATE`, 409); transition-style operations
    additionally require the requested target state to be reachable from the
    current state (`ERR_INVALID_TRANSITION`, 409); deposits require an `ACTIVE`
    enrollment (`ERR_ENROLLMENT_NOT_ACTIVE`, 409)". PRD §2.7: "and finally the
    fiscal guards — pool solvency (`ERR_POOL_INSUFFICIENT`, 402) before the
    per-participant match cap (`ERR_MATCH_CAP_EXCEEDED`, 409)". PRD §2.7:
    "the first failing check determines the error returned".

    Design: Difficulty/priority_pair_validation_conflict/enrollment_state_beats_pool_fiscal
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool C", total_funded_cents=50000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=50000),
        savings_goal_cents=500000,
    )
    # One accepted deposit accrues 20000, leaving pool uncommitted at 30000.
    create_deposit_on(ctx["enrollment"]["id"], 40000, admin_headers)
    # Suspend the coach: case stalls, plan freezes, enrollment MATCH_PAUSED.
    validate_success(api.suspend_coach(ctx["coach"]["id"], admin_headers))

    # This deposit's candidate (0.5 * 80000 = 40000) would also breach pool
    # solvency (uncommitted 30000) — but the enrollment-state check fires first.
    resp = api.create_deposit(
        ctx["enrollment"]["id"], create_deposit_payload(80000), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_enrollment_state_error_returned_while_pool_also_insufficient_second_probe(
    api, admin_headers
):
    """PRD §3.7: "The enrollment must be `ACTIVE`: deposits against a
    `MATCH_PAUSED`, `GOAL_MET`, or terminal enrollment are rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_state_beats_pool_fiscal
    """
    ctx = setup_active_enrollment(
        admin_headers,
        participant_income_cents=2000000,
        pool_overrides=dict(name="Pool C2", total_funded_cents=50000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=50000),
        savings_goal_cents=500000,
    )
    create_deposit_on(ctx["enrollment"]["id"], 40000, admin_headers)
    validate_success(api.suspend_coach(ctx["coach"]["id"], admin_headers))
    enr = validate_success(api.get_match_enrollment(ctx["enrollment"]["id"], admin_headers))
    assert enr["status"] == "MATCH_PAUSED"
    # Even a small deposit (no fiscal pressure at all) is rejected while paused.
    resp = api.create_deposit(
        ctx["enrollment"]["id"], create_deposit_payload(1000), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_participant_create_missing_required_email_returns_400(api, admin_headers):
    """PRD §3.3: "A `ProgramAdmin` enrolls a new **participant** with a
    `full_name`, an `email` unique among participants (a duplicate is rejected
    with `ERR_DUPLICATE_EMAIL`), and an `annual_income_cents` of at least 0".
    PRD §2.7, tier 3: "Required fields present, types correct, enum values
    valid, `end_at` strictly after `start_at`, `amount_cents` greater than
    zero, credit scores within the 300-to-850 range, `period_end` after
    `period_start`, `completion_threshold` no greater than `session_count`,
    and `new_coach_id` present on a stall reassignment (`ERR_INVALID_REQUEST`,
    400)."

    Design: Corner/entities/participant_create_missing_required_email_returns_400
    """
    resp = api.create_participant(
        {"full_name": "No Email", "annual_income_cents": 1000000}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_snapshot_credit_score_out_of_range_returns_400(api, admin_headers):
    """PRD §3.6: "at least one of the two metrics: a `credit_score` within the
    300-to-850 range, or a `savings_balance_cents` of at least 0."

    Design: Corner/validations/snapshot_credit_score_out_of_range_returns_400
    """
    participant = create_participant(admin_headers, full_name="POR", email="por@test.org")
    resp = api.create_outcome_snapshot(
        {"participant_id": participant["id"],
         "recorded_at": "2026-08-01T00:00:00Z", "credit_score": 299},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_report_period_inverted_returns_400(api, admin_headers):
    """PRD §3.9: "The request names a `period_start` (YYYY-MM-DD, inclusive),
    a `period_end` (YYYY-MM-DD, exclusive; not after `period_start` is
    `ERR_INVALID_REQUEST`)".

    Design: Corner/validations/report_period_inverted_returns_400
    """
    resp = api.create_funder_report(
        create_funder_report_payload("2026-02-01", "2026-01-01", "COHORT"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_participant_email_rejected(api, admin_headers):
    """PRD §3.3: "an `email` unique among participants (a duplicate is rejected
    with `ERR_DUPLICATE_EMAIL`)".

    Design: Corner/entities/duplicate_participant_email_rejected
    """
    create_participant(admin_headers, full_name="First", email="dup@test.org",
                       annual_income_cents=1000000)
    resp = api.create_participant(
        create_participant_payload(full_name="Second", email="dup@test.org",
                                   annual_income_cents=2000000),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


def test_duplicate_module_code_rejected(api, admin_headers):
    """PRD §3.1: "a `module_code` (unique across all modules; a reuse is
    rejected with `ERR_MODULE_CODE_TAKEN`)".

    Design: Corner/entities/duplicate_module_code_rejected
    """
    create_module(admin_headers, module_code="BF-100", title="First",
                  session_count=1, incentive_cents_per_hour=500,
                  completion_bonus_cents=0, completion_threshold=1)
    resp = api.create_curriculum_module(
        create_curriculum_module_payload(module_code="BF-100", title="Second",
                                         session_count=2,
                                         incentive_cents_per_hour=600,
                                         completion_bonus_cents=100,
                                         completion_threshold=2),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MODULE_CODE_TAKEN)


def test_workshop_get_not_found_returns_404(api, admin_headers):
    """PRD §2.10: "Existence validation covers both path identifiers and these
    body-carried references, resolved left to right. The first identifier or
    reference that does not resolve to an existing resource aborts the request
    with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/errors/workshop_get_not_found_returns_404
    """
    resp = api.get_workshop(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_request_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_auth_headers_returns_401
    """
    resp = api.get_workshop(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
