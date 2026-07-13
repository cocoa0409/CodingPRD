"""Follow-up cases: priority scoring, the repeat loop, and resolution (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_case_via_presumptive,
    create_specimen,
    receive_specimen,
    open_screen,
    setup_case_with_referral,
    setup_case_with_completed_referral,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]
COORD = TEST_USERS["follow_up_coordinator_headers"]


def _make_and_test_repeat(api, facility, infant,
                          collection_dt="2026-03-02T12:00:00Z",
                          received_dt="2026-03-02T18:00:00Z"):
    """Log a REPEAT specimen, receive it SATISFACTORY, screen it, and report NORMAL so it
    reaches TESTED (which advances a REPEAT_REQUESTED case to REPEAT_RECEIVED)."""
    spec = create_specimen(facility, infant, specimen_type="REPEAT",
                           collection_datetime=collection_dt)
    receive_specimen(spec, received_datetime=received_dt, blood_spot_count=5)
    screen = open_screen(spec)
    api.report_metabolic(screen["id"], {"metabolic_result": "NORMAL"}, LAB)
    return spec


# ─── Corner: INITIAL priority exercises all three weights (85) ────────
def test_initial_priority_preterm_lowbirth_scores_85(api):
    """PRD §3.5: "50 points for each critical analyte flagged (the case's
    `critical_flag_count`), plus 20 points if the infant is preterm — meaning
    `gestational_age_weeks` is below 34 — plus 15 points if the infant is low-birth-weight,
    meaning `birth_weight_grams` is below 1500 grams."

    Design: Corner/calculations/followup_priority_initial_preterm_lowbirth_scores_85
    """
    _f, _i, _s, _screen, case = create_case_via_presumptive(
        critical_analyte_count=1, gestational_age_weeks=33, birth_weight_grams=1400
    )
    assert case["priority_score"] == 85
    assert case["priority_variant"] == "INITIAL"


# ─── Corner: duplicate pending repeat within window rejected ──────────
def test_request_repeat_duplicate_within_window_rejected(api):
    """PRD §3.5: "a case already in `REPEAT_REQUESTED` cannot receive another pending request
    and is rejected with `ERR_DUPLICATE_REPEAT_PENDING`."

    Design: Corner/state_machines/request_repeat_duplicate_within_window_second_returns_409
    """
    _f, _i, _s, _screen, case = create_case_via_presumptive()
    validate_success(api.request_repeat(case["id"], {}, COORD), 200)
    res = api.request_repeat(case["id"], {}, COORD)
    validate_error(res, "ERR_DUPLICATE_REPEAT_PENDING", expected_status=409)


# ─── Difficulty: INITIAL 50 vs REVISED-confirmed 90 on one case ───────
def test_initial_priority_base_fifty_at_open(api):
    """PRD §3.5: "The **INITIAL** variant, computed when the case opens, is exactly that
    base."

    Design: Difficulty/dual_variant_calc/followup_priority_initial_50_vs_revised_confirmed_90
    """
    _f, _i, _s, _screen, case = create_case_via_presumptive(critical_analyte_count=1)
    # gest 39 (not preterm), bw 3200 (not low-birth-weight), one critical analyte → 50
    assert case["priority_score"] == 50
    assert case["priority_variant"] == "INITIAL"


def test_revised_priority_confirmed_adds_forty(api):
    """PRD §3.5: "The **REVISED** variant, computed when the case is resolved, starts from
    the same base and then adds 40 points if the resolving outcome is a confirmation, or
    subtracts 30 points if the resolving outcome is a normal repeat result; only one of
    those adjustments applies, according to the outcome."
    PRD §3.5: "a confirmation flips `priority_variant` to `REVISED` and recomputes the score
    in its revised, confirmatory form, changes `case_type` to `LONG_TERM`, moves the case to
    `CONFIRMED_POSITIVE`, and immediately auto-transitions it to `LONG_TERM_MONITORING`"

    Design: Difficulty/dual_variant_calc/followup_priority_initial_50_vs_revised_confirmed_90
    """
    ctx = setup_case_with_completed_referral(critical_analyte_count=1)
    resolved = validate_success(
        api.resolve_case(ctx["case"]["id"], {"outcome": "CONFIRMED"}, COORD), 200
    )
    assert resolved["priority_variant"] == "REVISED"
    assert resolved["priority_score"] == 90
    assert resolved["status"] == "LONG_TERM_MONITORING"


# ─── Difficulty: repeat loop reaches repeat_count == 2 ────────────────
def test_repeat_loop_reaches_count_two(api):
    """PRD §3.5: "From `REPEAT_RECEIVED`, the coordinator may request yet another repeat —
    again subject only to the 30-day window from `opened_at_clock` — looping back to
    `REPEAT_REQUESTED` and incrementing `repeat_count`; this loop may run any number of
    times."

    Design: Difficulty/non_linear_state_machine/followup_case_repeat_loop_reaches_count_two
    """
    facility, infant, _s, _screen, case = create_case_via_presumptive()
    validate_success(api.request_repeat(case["id"], {}, COORD), 200)  # → REPEAT_REQUESTED, count 1
    _make_and_test_repeat(api, facility, infant)                      # → REPEAT_RECEIVED
    looped = validate_success(api.request_repeat(case["id"], {}, COORD), 200)
    assert looped["status"] == "REPEAT_REQUESTED"
    assert looped["repeat_count"] == 2


def test_repeat_request_then_received_transitions(api):
    """PRD §3.5: "A successful request moves the case to `REPEAT_REQUESTED` and increments
    `repeat_count` by one."
    PRD §3.5: "The case then advances to `REPEAT_RECEIVED` automatically when a repeat
    specimen for that infant reaches `TESTED` (Section 3.4)."

    Design: Difficulty/non_linear_state_machine/followup_case_repeat_loop_reaches_count_two
    """
    facility, infant, _s, _screen, case = create_case_via_presumptive()
    requested = validate_success(api.request_repeat(case["id"], {}, COORD), 200)
    assert requested["status"] == "REPEAT_REQUESTED"
    assert requested["repeat_count"] == 1
    _make_and_test_repeat(api, facility, infant)
    reloaded = get_success_data(api.get_follow_up_case(case["id"], COORD))
    assert reloaded["status"] == "REPEAT_RECEIVED"


# ─── Difficulty: CONFIRMED resolution blocked until a referral COMPLETED ──
def test_confirm_blocked_when_referral_not_completed(api):
    """PRD §3.5: "A `CONFIRMED` outcome requires that at least one referral belonging to the
    case has reached `COMPLETED`; if none has, resolution is rejected with
    `ERR_REFERRALS_UNRESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/case_confirm_blocked_until_referral_completed
    """
    ctx = setup_case_with_referral()  # referral is only REQUESTED
    res = api.resolve_case(ctx["case"]["id"], {"outcome": "CONFIRMED"}, COORD)
    validate_error(res, "ERR_REFERRALS_UNRESOLVED", expected_status=409)


def test_confirm_rejected_leaves_case_open(api):
    """PRD §3.5: "A `CONFIRMED` outcome requires that at least one referral belonging to the
    case has reached `COMPLETED`; if none has, resolution is rejected with
    `ERR_REFERRALS_UNRESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/case_confirm_blocked_until_referral_completed
    """
    ctx = setup_case_with_referral()
    api.resolve_case(ctx["case"]["id"], {"outcome": "CONFIRMED"}, COORD)
    reloaded = get_success_data(api.get_follow_up_case(ctx["case"]["id"], COORD))
    assert reloaded["status"] == "OPEN"


# ─── Difficulty: resolve NORMAL restores the open-case count ──────────
def test_case_open_raises_open_case_count(api):
    """PRD §3.4: "that open increments the infant's `open_case_count` and sets
    `followup_status` to `ACTIVE`; and the case's INITIAL priority score is computed."

    Design: Difficulty/compensating_invariant/case_resolve_normal_restores_open_case_count
    """
    _f, infant, _s, _screen, _case = create_case_via_presumptive()
    reloaded = get_success_data(api.get_infant(infant["id"], LAB))
    assert reloaded["open_case_count"] == 1
    assert reloaded["followup_status"] == "ACTIVE"


def test_resolve_normal_restores_open_case_count_and_clears_status(api):
    """PRD §3.5: "A `NORMAL` outcome moves the case to `RESOLVED_NORMAL`, flips
    `priority_variant` to `REVISED` and recomputes the score in its revised form, and — as a
    compensating adjustment — decrements the infant's `open_case_count` by one, setting
    `followup_status` back to `CLEAR` if the count reaches zero."

    Design: Difficulty/compensating_invariant/case_resolve_normal_restores_open_case_count
    """
    _f, infant, _s, _screen, case = create_case_via_presumptive()
    resolved = validate_success(
        api.resolve_case(case["id"], {"outcome": "NORMAL"}, COORD), 200
    )
    assert resolved["status"] == "RESOLVED_NORMAL"
    reloaded = get_success_data(api.get_infant(infant["id"], LAB))
    assert reloaded["open_case_count"] == 0
    assert reloaded["followup_status"] == "CLEAR"
