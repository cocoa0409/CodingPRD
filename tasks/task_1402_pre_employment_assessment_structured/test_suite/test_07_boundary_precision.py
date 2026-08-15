"""Boundary precision: four-fifths ratio exactly 0.8000, quorum exact-equality,
and the retention expiry instant (inclusive feedback vs strict purge)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    book_completed_session,
    submit_scorecard,
    create_snapshot_payload,
    create_decision_payload,
    set_clock_payload,
    feedback_payload,
    setup_quorum_ready_candidate,
    setup_decided_candidate,
    get_group_breakdown,
    plus_days,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]
DO = TEST_USERS["do_headers"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/impact_ratio_exactly_four_fifths_not_flagged
# ---------------------------------------------------------------------------

def _build_four_fifths_cycle():
    """GROUP_A: 1 COMPLETED (composite 0.7413, projected-selected) + 1 SCHEDULED ->
    2 applicants, 1 selected (rate 0.5000).
    GROUP_B: 2 COMPLETED (composite 0.7413, selected) + 3 SCHEDULED -> 5 applicants,
    2 selected (rate 0.4000)."""
    ctx = setup_active_cycle(openings_count=10)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])

    def _mk(ref, grp):
        return create_candidate(external_ref=ref, full_name=f"Cand {ref}",
                                email=f"{ref.lower()}@x.com", group_code=grp)

    ca1, ca2 = _mk("C-A1", "GROUP_A"), _mk("C-A2", "GROUP_A")
    cbs = [_mk(f"C-B{i}", "GROUP_B") for i in range(1, 6)]
    a1 = invite_and_complete_candidate(cycle["id"], ca1["id"], raw_score=72)
    a2 = invite_candidate(cycle["id"], ca2["id"]); schedule_assessment(a2["id"])
    b1 = invite_and_complete_candidate(cycle["id"], cbs[0]["id"], raw_score=72)
    b2 = invite_and_complete_candidate(cycle["id"], cbs[1]["id"], raw_score=72)
    for c in cbs[2:]:
        a = invite_candidate(cycle["id"], c["id"]); schedule_assessment(a["id"])

    s1 = book_completed_session(cycle["id"], ca1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], cbs[0]["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    s3 = book_completed_session(cycle["id"], cbs[1]["id"], interviewer["id"], guide["id"],
                                "2026-08-12T11:00:00Z", "2026-08-12T12:00:00Z")
    for s in (s1, s2, s3):
        submit_scorecard(s["id"], interviewer["id"])
    return ctx


def test_impact_ratio_exactly_four_fifths_rates(api):
    """PRD §3.7: "each included group's `selection_rate` is its `selected` divided by
    its `applicants`, rounded half-up to four decimal places first".

    GROUP_A 1/2 -> 0.5000 (highest); GROUP_B 2/5 -> 0.4000 -> ratio 0.8000.

    Design: Difficulty/boundary_precision_check/impact_ratio_exactly_four_fifths_not_flagged
    """
    ctx = _build_four_fifths_cycle()
    resp = api.create_adverse_impact_snapshot(ctx["cycle"]["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    group_a = get_group_breakdown(snap, "GROUP_A")
    group_b = get_group_breakdown(snap, "GROUP_B")
    assert group_a["selection_rate"] == pytest.approx(0.5, abs=0.0001)
    assert group_a["impact_ratio"] == pytest.approx(1.0, abs=0.0001)
    assert group_b["selection_rate"] == pytest.approx(0.4, abs=0.0001)
    assert group_b["impact_ratio"] == pytest.approx(0.8, abs=0.0001)


def test_impact_ratio_exactly_four_fifths_is_not_flagged(api):
    """PRD §3.7: "`flagged` is true exactly when some included group's `impact_ratio` is
    strictly below the four-fifths threshold of 0.8000 — an impact ratio of exactly
    0.8000 does not flag the snapshot."

    Design: Difficulty/boundary_precision_check/impact_ratio_exactly_four_fifths_not_flagged
    """
    ctx = _build_four_fifths_cycle()
    resp = api.create_adverse_impact_snapshot(ctx["cycle"]["id"], create_snapshot_payload(), CO)
    snap = validate_success(resp, expected_status=201)
    assert snap["flagged"] is False


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/quorum_exactly_required_allows_decision
# ---------------------------------------------------------------------------

def test_quorum_exact_tie_passes(api):
    """PRD §3.8: "the quorum is met exactly when the submitted count is at least the
    required count — an exact tie passes" and "the required count is fixed as the
    larger of 2 and the smaller of 3 and the number of evaluated sessions".

    Two evaluated sessions -> required max(2, min(3, 2)) = 2; two SUBMITTED scorecards
    -> 2 >= 2 passes.

    Design: Difficulty/boundary_precision_check/quorum_exactly_required_allows_decision
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    resp = api.create_decision(ctx["cycle"]["id"], create_decision_payload(ctx["candidate"]["id"]), DO)
    decision = validate_success(resp, expected_status=201)
    assert decision["quorum_required_at_decision"] == 2
    assert decision["quorum_submitted_at_decision"] == 2


def test_quorum_decision_captures_composite_and_fills_requisition(api):
    """PRD §3.8: "The record captures the officer's `X-User-ID` as `decided_by_user_id`,
    a four-decimal snapshot of the assessment's `composite_score` as
    `composite_at_decision`, the required and submitted quorum counts as
    `quorum_required_at_decision` and `quorum_submitted_at_decision`, and the logical
    creation time as `finalized_at`." and "an `ADVANCE` decision increments the
    requisition's `filled_count` and, at the moment that count reaches `openings_count`,
    flips the requisition to `FILLED`".

    Scorecards COMM4/ANAL5 + COMM5/ANAL3 -> means COMM 4.5, ANAL 4.0 -> guide
    0.6*0.9 + 0.4*0.8 = 0.86; assessment (72-40)/60 = 0.5333; composite
    0.6*0.86 + 0.4*0.5333 = 0.7293.

    Design: Difficulty/boundary_precision_check/quorum_exactly_required_allows_decision
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    resp = api.create_decision(ctx["cycle"]["id"], create_decision_payload(ctx["candidate"]["id"]), DO)
    decision = validate_success(resp, expected_status=201)
    assert decision["composite_at_decision"] == pytest.approx(0.7293, abs=0.0001)
    req = validate_success(api.get_requisition(ctx["requisition"]["id"], HM))
    assert req["filled_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/retention_expiry_exact_instant
# ---------------------------------------------------------------------------

def test_feedback_allowed_exactly_at_retention_expiry(api):
    """PRD §3.9: "the feedback gate is inclusive, permitting feedback at the exact
    expiry instant".

    Decision anchored 2026-08-15T12:00:00Z + 730 days -> expiry 2028-08-14T12:00:00Z;
    feedback at exactly that instant succeeds.

    Design: Difficulty/boundary_precision_check/retention_expiry_exact_instant
    """
    ctx = setup_decided_candidate(retention_days=730)
    expiry = plus_days("2026-08-15T12:00:00Z", 730)
    api.set_clock(set_clock_payload(expiry), ADMIN)
    resp = api.send_feedback(ctx["assessment"]["id"], feedback_payload(), HM)
    sent = validate_success(resp)
    assert sent["feedback_status"] == "SENT"


def test_purge_strict_gate_spans_the_exact_expiry_second(api):
    """PRD §3.9: "the purge gate is strict, purging only when the logical now is
    strictly later than `retention_expires_at` — at exact expiry the record is still
    retained."

    Sweep at exactly expiry purges nothing; sweep at expiry + 1s purges it.

    Design: Difficulty/boundary_precision_check/retention_expiry_exact_instant
    """
    ctx = setup_decided_candidate(retention_days=730)
    expiry = plus_days("2026-08-15T12:00:00Z", 730)
    api.set_clock(set_clock_payload(expiry), ADMIN)
    sweep_at = validate_success(api.run_retention_sweep(CO))
    assert sweep_at["purged_count"] == 0
    from test_helpers.fixtures import _plus_one_second
    api.set_clock(set_clock_payload(_plus_one_second(expiry)), ADMIN)
    sweep_after = validate_success(api.run_retention_sweep(CO))
    assert sweep_after["purged_count"] == 1
    assert ctx["assessment"]["id"] in sweep_after["purged_assessment_ids"]
    after = validate_success(api.get_assessment(ctx["assessment"]["id"], HM))
    assert after["admin_status"] == "PURGED"
