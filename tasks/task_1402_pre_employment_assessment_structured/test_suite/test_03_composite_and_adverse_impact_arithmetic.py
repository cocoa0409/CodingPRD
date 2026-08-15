"""Composite-score renormalization/clamp and adverse-impact rounding order."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    complete_assessment_at,
    invite_and_complete_candidate,
    book_completed_session,
    submit_scorecard,
    create_snapshot_payload,
    set_clock_payload,
    create_decision_payload,
    void_scorecard_payload,
    make_interviewer_headers,
    get_group_breakdown,
    assert_assessment,
    assert_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]
DO = TEST_USERS["do_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/composite_score_renormalization_and_clamp
# ---------------------------------------------------------------------------

def _build_three_candidates():
    """Cycle ACTIVE; cA raw72 full coverage COMM4/ANAL5; cB raw72 COMM4-only;
    cC raw30 COMM5/ANAL5."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])

    cA = create_candidate(external_ref="C-A", full_name="Cand A", email="ca@x.com", group_code="GROUP_A")
    cB = create_candidate(external_ref="C-B", full_name="Cand B", email="cb@x.com", group_code="GROUP_B")
    cC = create_candidate(external_ref="C-C", full_name="Cand C", email="cc@x.com", group_code="GROUP_C")
    aA = invite_and_complete_candidate(cycle["id"], cA["id"], raw_score=72)
    aB = invite_and_complete_candidate(cycle["id"], cB["id"], raw_score=72)
    aC = invite_and_complete_candidate(cycle["id"], cC["id"], raw_score=30)

    sA = book_completed_session(cycle["id"], cA["id"], interviewer["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    sB = book_completed_session(cycle["id"], cB["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    sC = book_completed_session(cycle["id"], cC["id"], interviewer["id"], guide["id"],
                                "2026-08-12T11:00:00Z", "2026-08-12T12:00:00Z")
    scA = submit_scorecard(sA["id"], interviewer["id"],
                           ratings=[{"competency_code": "COMM", "rating": 4},
                                    {"competency_code": "ANAL", "rating": 5}])
    scB = submit_scorecard(sB["id"], interviewer["id"],
                           ratings=[{"competency_code": "COMM", "rating": 4}])
    scC = submit_scorecard(sC["id"], interviewer["id"],
                           ratings=[{"competency_code": "COMM", "rating": 5},
                                    {"competency_code": "ANAL", "rating": 5}],
                           overall_recommendation="STRONG_YES")
    return ctx, aA, aB, aC, scA, scC


def test_composite_full_coverage(api):
    """PRD §3.8: "the guide component is the sum over rated competencies of each item's
    `weight` multiplied by its rounded mean and divided by its `scale_max`, all divided
    by the coverage" and "The composite is six-tenths of the guide component plus
    four-tenths of the assessment component, rounded half-up to four decimal places".

    cA: means 4.0/5.0 -> guide 0.6*4/5 + 0.4*5/5 = 0.88 (coverage 1.0);
    assessment (72-40)/(100-40) = 0.5333 -> 0.6*0.88 + 0.4*0.5333 = 0.7413.

    Design: Difficulty/combinatorial_formula/composite_score_renormalization_and_clamp
    """
    _, aA, _, _, scA, _ = _build_three_candidates()
    comp_a = validate_success(api.get_assessment(aA["id"], HM))["composite_score"]
    assert comp_a == pytest.approx(0.7413, abs=0.0001)
    sc_a_data = validate_success(api.get_scorecard(scA["id"], ADMIN))
    assert sc_a_data["weighted_total"] == pytest.approx(0.88, abs=0.0001)


def test_composite_partial_coverage_renormalizes(api):
    """PRD §3.8: "The coverage is the sum of the rubric weights of competencies that
    received at least one rating; when coverage is zero the guide component is zero,
    and otherwise the guide component is the sum over rated competencies of each item's
    `weight` multiplied by its rounded mean and divided by its `scale_max`, all divided
    by the coverage — partial panels are thus renormalized over the covered weights
    only."

    cB (raw 72, COMM4 only): coverage 0.6; guide = (0.6*4/5)/0.6 = 0.8 ->
    0.6*0.8 + 0.4*0.5333 = 0.6933 — same raw as the full-coverage candidate,
    different composite.

    Design: Difficulty/combinatorial_formula/composite_score_renormalization_and_clamp
    """
    _, _, aB, _, _, _ = _build_three_candidates()
    comp_b = validate_success(api.get_assessment(aB["id"], HM))["composite_score"]
    assert comp_b == pytest.approx(0.6933, abs=0.0001)


def test_composite_clamps_raw_below_pass_floor(api):
    """PRD §3.8: "The assessment component clamps the raw result into the unit interval:
    the `raw_score` minus `pass_floor`, divided by `max_score` minus `pass_floor`, forced
    to zero below and to one above."

    cC: raw 30 < pass_floor 40 -> assessment component 0; guide COMM5/ANAL5 -> 1.0 ->
    composite = 0.6*1.0 + 0.4*0 = 0.6000.

    Design: Difficulty/combinatorial_formula/composite_score_renormalization_and_clamp
    """
    _, _, _, aC, _, scC = _build_three_candidates()
    comp_c = validate_success(api.get_assessment(aC["id"], HM))["composite_score"]
    assert comp_c == pytest.approx(0.6, abs=0.0001)
    sc_c_data = validate_success(api.get_scorecard(scC["id"], ADMIN))
    assert sc_c_data["weighted_total"] == pytest.approx(1.0, abs=0.0001)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/adverse_impact_round_then_divide_order
# ---------------------------------------------------------------------------

def _build_round_then_divide_cycle():
    """GROUP_A: 2 COMPLETED (composite 0.7413) + 1 SCHEDULED -> 3 applicants, 2 selected.
    GROUP_B: 1 COMPLETED (composite 0.7413) + 2 SCHEDULED -> 3 applicants, 1 selected."""
    ctx = setup_active_cycle(openings_count=10)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])

    def _mk(ref, grp):
        return create_candidate(external_ref=ref, full_name=f"Cand {ref}",
                                email=f"{ref.lower()}@x.com", group_code=grp)

    ca1, ca2, ca3 = _mk("C-A1", "GROUP_A"), _mk("C-A2", "GROUP_A"), _mk("C-A3", "GROUP_A")
    cb1, cb2, cb3 = _mk("C-B1", "GROUP_B"), _mk("C-B2", "GROUP_B"), _mk("C-B3", "GROUP_B")
    a1 = invite_and_complete_candidate(cycle["id"], ca1["id"], raw_score=72)
    a2 = invite_and_complete_candidate(cycle["id"], ca2["id"], raw_score=72)
    a3 = invite_candidate(cycle["id"], ca3["id"]); schedule_assessment(a3["id"])
    b1 = invite_and_complete_candidate(cycle["id"], cb1["id"], raw_score=72)
    b2 = invite_candidate(cycle["id"], cb2["id"]); schedule_assessment(b2["id"])
    b3 = invite_candidate(cycle["id"], cb3["id"]); schedule_assessment(b3["id"])

    # Scorecards lift the three COMPLETED assessments to composite 0.7413
    # (COMM4/ANAL5 -> guide 0.88; raw 72 -> assessment 0.5333; 0.6*0.88+0.4*0.5333).
    s1 = book_completed_session(cycle["id"], ca1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], ca2["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    s3 = book_completed_session(cycle["id"], cb1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T11:00:00Z", "2026-08-12T12:00:00Z")
    for s in (s1, s2, s3):
        submit_scorecard(s["id"], interviewer["id"])
    return ctx


def test_adverse_impact_per_group_rates_rounded_first(api):
    """PRD §3.7: "each included group's `selection_rate` is its `selected` divided by its
    `applicants`, rounded half-up to four decimal places first; the impact ratio then
    divides those already-rounded rates and is itself rounded half-up to four decimal
    places. Dividing unrounded values would yield different fourth-decimal results and
    is not the contract."

    Design: Difficulty/combinatorial_formula/adverse_impact_round_then_divide_order
    """
    ctx = _build_round_then_divide_cycle()
    resp = api.create_adverse_impact_snapshot(ctx["cycle"]["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert get_group_breakdown(snap, "GROUP_A")["selection_rate"] == pytest.approx(0.6667, abs=0.0001)
    assert get_group_breakdown(snap, "GROUP_B")["selection_rate"] == pytest.approx(0.3333, abs=0.0001)


def test_adverse_impact_ratio_uses_rounded_rates(api):
    """PRD §3.7: "each included group's `impact_ratio` is its rounded `selection_rate`
    divided by the rounded maximum rate, rounded half-up to four decimals".

    round(0.3333 / 0.6667, 4) = 0.4999 (divide-then-round on unrounded 1/3 and 2/3
    would give 0.5000 — the fourth decimal proves the pinned order).

    Design: Difficulty/combinatorial_formula/adverse_impact_round_then_divide_order
    """
    ctx = _build_round_then_divide_cycle()
    resp = api.create_adverse_impact_snapshot(ctx["cycle"]["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert get_group_breakdown(snap, "GROUP_B")["impact_ratio"] == pytest.approx(0.4999, abs=0.0001)
    assert snap["highest_rate_group_code"] == "GROUP_A"
    assert snap["flagged"] is True, "0.4999 is strictly below the four-fifths threshold"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/quorum_gate_evaluation_order_on_void
# ---------------------------------------------------------------------------

def _build_three_submitted_scorecards():
    """Cycle ACTIVE; c1 COMPLETED raw 72; three COMPLETED sessions each with a
    SUBMITTED scorecard (s1 iv1 COMM4/ANAL5; s2 iv2 COMM5/ANAL3; s3 iv1 COMM4/ANAL4)."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"])
    iv2, _ = create_calibrated_interviewer(guide["id"])

    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)

    s1 = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], c1["id"], iv2["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    s3 = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                "2026-08-13T09:00:00Z", "2026-08-13T10:00:00Z")
    sc1 = submit_scorecard(s1["id"], iv1["id"],
                           ratings=[{"competency_code": "COMM", "rating": 4},
                                    {"competency_code": "ANAL", "rating": 5}])
    sc2 = submit_scorecard(s2["id"], iv2["id"],
                           ratings=[{"competency_code": "COMM", "rating": 5},
                                    {"competency_code": "ANAL", "rating": 3}])
    sc3 = submit_scorecard(s3["id"], iv1["id"],
                           ratings=[{"competency_code": "COMM", "rating": 4},
                                    {"competency_code": "ANAL", "rating": 4}])
    return ctx, c1, iv1, s1, sc1


def test_quorum_void_shrinks_submitted_not_required(api):
    """PRD §3.8: "Because the session set is fixed before the submitted count is read,
    voiding a scorecard shrinks the submitted count without shrinking the requirement,
    so a decision that was about to pass can become blocked without any session
    changing state." Also: "voiding a scorecard reverts its session from `SCORED` back
    to `COMPLETED`, so the session remains in this set."

    Design: Difficulty/combinatorial_formula/quorum_gate_evaluation_order_on_void
    """
    ctx, c1, iv1, s1, sc1 = _build_three_submitted_scorecards()
    cycle = ctx["cycle"]
    resp = api.void_scorecard(sc1["id"], void_scorecard_payload(), CO)
    voided = validate_success(resp)
    assert voided["status"] == "VOIDED"
    session = validate_success(api.get_session(s1["id"], ADMIN))
    assert session["status"] == "COMPLETED", (
        "void reverts SCORED -> COMPLETED but keeps the session in sessions_evaluated"
    )
    # required = max(2, min(3, 3)) = 3; submitted = 2 -> blocked
    resp = api.create_decision(cycle["id"], create_decision_payload(c1["id"]), DO)
    from test_helpers import validate_error
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)


def test_quorum_restored_by_replacement_scorecard(api):
    """PRD §3.8: "the required count is fixed as the larger of 2 and the smaller of 3
    and the number of evaluated sessions." and "the quorum is met exactly when the
    submitted count is at least the required count — an exact tie passes."

    After voiding one of three, a replacement scorecard restores submitted 3 >=
    required 3, and the decision captures quorum_required_at_decision 3,
    quorum_submitted_at_decision 3, composite_at_decision 0.7173 (COMM mean
    (5+4+4)/3 = 4.3333; ANAL mean (3+4+5)/3 = 4.0; guide 0.6*0.8667+0.4*0.8 = 0.84;
    assessment 0.5333).

    Design: Difficulty/combinatorial_formula/quorum_gate_evaluation_order_on_void
    """
    ctx, c1, iv1, s1, sc1 = _build_three_submitted_scorecards()
    cycle = ctx["cycle"]
    validate_success(api.void_scorecard(sc1["id"], void_scorecard_payload(), CO))
    # Replacement scorecard on the reverted (COMPLETED) session s1
    submit_scorecard(s1["id"], iv1["id"],
                     ratings=[{"competency_code": "COMM", "rating": 4},
                              {"competency_code": "ANAL", "rating": 5}])
    resp = api.create_decision(cycle["id"], create_decision_payload(c1["id"]), DO)
    decision = validate_success(resp, expected_status=201)
    assert decision["quorum_required_at_decision"] == 3
    assert decision["quorum_submitted_at_decision"] == 3
    assert decision["composite_at_decision"] == pytest.approx(0.7173, abs=0.0001)
