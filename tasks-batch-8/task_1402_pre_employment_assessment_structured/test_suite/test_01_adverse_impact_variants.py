"""Adverse-impact snapshot variants: PROVISIONAL vs FINAL divergence."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_interviewer_headers,
    create_candidate_payload,
    create_invitation_payload,
    create_session_payload,
    create_scorecard_payload,
    create_snapshot_payload,
    set_clock_payload,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    complete_assessment_at,
    book_completed_session,
    submit_scorecard,
    get_group_breakdown,
    assert_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


def _build_provisional_final_divergence():
    """Cycle with A=1 COMPLETED(projected-selected) + 1 SCHEDULED; B=1 COMPLETED(not selected) + 1 NO_SHOW.

    a1 raw 72 (component (72-40)/60 = 0.5333) with scorecard COMM4/ANAL5 ->
    guide component 0.88 -> composite 0.6*0.88+0.4*0.5333 = 0.7413 (>= 0.7000).
    b1 raw 45 (component (45-40)/60 = 0.0833) with scorecard COMM3/ANAL3 ->
    guide component 0.6 -> composite 0.6*0.6+0.4*0.0833 = 0.3933 (< 0.7000).
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])

    ca1 = create_candidate(external_ref="C-A1", full_name="Cand A1",
                           email="ca1@x.com", group_code="GROUP_A")
    ca2 = create_candidate(external_ref="C-A2", full_name="Cand A2",
                           email="ca2@x.com", group_code="GROUP_A")
    cb1 = create_candidate(external_ref="C-B1", full_name="Cand B1",
                           email="cb1@x.com", group_code="GROUP_B")
    cb2 = create_candidate(external_ref="C-B2", full_name="Cand B2",
                           email="cb2@x.com", group_code="GROUP_B")

    a1 = invite_candidate(cycle["id"], ca1["id"])
    a2 = invite_candidate(cycle["id"], ca2["id"])
    b1 = invite_candidate(cycle["id"], cb1["id"])
    b2 = invite_candidate(cycle["id"], cb2["id"])
    for a in (a1, a2, b1, b2):
        schedule_assessment(a["id"], "2026-08-10T09:00:00Z")

    complete_assessment_at(a1["id"], raw_score=72, work_instant="2026-08-10T09:00:00Z")
    complete_assessment_at(b1["id"], raw_score=45, work_instant="2026-08-10T09:00:00Z")
    get_success_data(api_client.set_clock(set_clock_payload("2026-08-10T10:00:00Z"), ADMIN))
    get_success_data(api_client.mark_assessment_no_show(b2["id"], HM))

    # a1's scorecard -> composite 0.7413 (projected selection in PROVISIONAL)
    s1 = book_completed_session(cycle["id"], ca1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    submit_scorecard(s1["id"], interviewer["id"],
                     ratings=[{"competency_code": "COMM", "rating": 4},
                              {"competency_code": "ANAL", "rating": 5}])
    # b1's scorecard -> composite 0.3933 (not projected)
    s2 = book_completed_session(cycle["id"], cb1["id"], interviewer["id"], guide["id"],
                                "2026-08-13T10:00:00Z", "2026-08-13T11:00:00Z")
    submit_scorecard(s2["id"], interviewer["id"],
                     ratings=[{"competency_code": "COMM", "rating": 3},
                              {"competency_code": "ANAL", "rating": 3}],
                     overall_recommendation="NO")
    return ctx


def test_provisional_snapshot_counts_presented_and_projected(api):
    """PRD §3.7: "a `PROVISIONAL` snapshot counts a cycle's candidate assessments whose
    `admin_status` is `SCHEDULED`, `ACCOMMODATION_HOLD`, `IN_PROGRESS`, `COMPLETED`, or
    `NO_SHOW` (the `INVITED`, `CANCELLED`, and `PURGED` are excluded, since those
    candidates were never presented or were removed before presentation)" and "for
    `PROVISIONAL` snapshots the selected count comprises finalized `ADVANCE` decisions
    plus — as projected selections for candidates not yet decided — completed
    assessments whose `composite_score` is at least 0.7000".

    Design: Difficulty/dual_variant_calc/adverse_impact_provisional_vs_final_divergence
    """
    ctx = _build_provisional_final_divergence()
    cycle = ctx["cycle"]
    resp = api.create_adverse_impact_snapshot(cycle["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert_snapshot(snap)
    assert snap["flagged"] is True, (
        "PROVISIONAL: applicants A=2 (COMPLETED+SCHEDULED), B=2 (COMPLETED+NO_SHOW); "
        "selected A=1 (composite 0.7413 >= 0.7000 projected), B=0 -> "
        "rates 0.5000/0.0000 -> ratio_B 0.0000 < 0.8000"
    )
    assert get_group_breakdown(snap, "GROUP_B")["impact_ratio"] == pytest.approx(0.0, abs=0.0001)


def test_final_snapshot_shrinks_groups_below_min_n(api):
    """PRD §3.7: "a `FINAL` snapshot counts only assessments whose `admin_status` is
    `COMPLETED`" and "any group with fewer than 2 applicants is excluded from comparison
    entirely: its `selection_rate` and `impact_ratio` are null and its `excluded_reason`
    is `INSUFFICIENT_N`."

    Design: Difficulty/dual_variant_calc/adverse_impact_provisional_vs_final_divergence
    """
    ctx = _build_provisional_final_divergence()
    cycle = ctx["cycle"]
    resp = api.create_adverse_impact_snapshot(
        cycle["id"], create_snapshot_payload(snapshot_type="FINAL"), CO,
    )
    snap = validate_success(resp, expected_status=201)
    assert_snapshot(snap)
    # FINAL: applicants A=1, B=1 — both below MIN_GROUP_N
    assert snap["flagged"] is False
    group_a = get_group_breakdown(snap, "GROUP_A")
    assert group_a["selection_rate"] is None
    assert group_a["excluded_reason"] == "INSUFFICIENT_N"
    assert snap["highest_rate_group_code"] is None
    # FINAL snapshot not flagged -> cycle is not frozen for adverse impact
    cycle_after = get_success_data(api.get_cycle(cycle["id"], CO))
    assert cycle_after["posture"] == "ACTIVE"
