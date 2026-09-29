"""
Multi-hop cascades: one call whose effects travel through three or four resources.

The sweep cascade runs breach -> auto audit -> club sanction -> case freeze; the
symptom-check cascade runs recurrence -> clearance denial -> stage revocation.
Each hop is asserted, not just the final state.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_case_progress,
    assert_club_posture,
    assert_instant,
    assert_return_step,
)
from test_helpers.test_users import AUDITOR_A, AUDITOR_B


def _setup_abandoned_examination_and_probation_club(api) -> Dict[str, Any]:
    """
    The canonical case with stage one open, a second player's examination
    abandoned past its deadline, and the club already on PROBATION.
    """
    ctx = fx.setup_case_with_stage_open(api, 1)

    player2 = fx.add_second_player(api, ctx)
    game2 = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        season_year=2026,
        week_index=2,
        kickoff_at="2026-09-16T17:00:00Z",
    )
    fx.set_clock(api, "2026-09-16T17:00:00Z")
    fx.advance_game(api, game2["id"], "IN_PROGRESS")

    fx.set_clock(api, "2026-09-16T18:00:00Z")
    evaluation = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(player2["id"], game2["id"], trigger_source="VIDEO_SPOTTER"),
            ctx["doc_h_headers"],
        ),
        201,
    )
    validate_success(
        api.screen_evaluation(
            evaluation["id"],
            f.screen_payload(no_go_signs=["CONFUSION"], symptom_score=6),
            ctx["doc_h_headers"],
        )
    )
    validate_success(
        api.start_locker_room_exam(
            evaluation["id"],
            f.locker_room_exam_payload(ctx["inc_id"]),
            ctx["doc_h_headers"],
        )
    )

    # 100 - 20 - 6 = 74, which is TIER_2 and PROBATION.
    audit1 = fx.open_audit(api, ctx["club_h_id"], opener_headers=AUDITOR_A)
    fx.issue_findings(
        api,
        audit1["id"],
        ["MISSING_INC_CLEARANCE", "LATE_INJURY_REPORT"],
        0,
        issuer_headers=AUDITOR_B,
    )

    # One minute past the abandoned examination's mandatory-removal deadline.
    fx.set_clock(api, "2026-09-16T18:16:00Z")

    ctx["eval2_id"] = evaluation["id"]
    ctx["audit1_id"] = audit1["id"]
    return ctx


# ─── Sweep: breach -> auto audit -> sanction -> freeze ───────────────────────

def test_sweep_breaches_the_abandoned_examination_and_prices_its_own_audit(api):
    """
    The sweep breaches an examination left unconcluded past its deadline and
    opens the resulting audit on its own initiative, carrying both codes.

    PRD §3.11: "An evaluation caught in `LOCKER_ROOM_EXAM` moves
    `LOCKER_ROOM_EXAM → PROTOCOL_BREACH` the same way, except that its auto-opened
    audit carries **two** codes — `[EVALUATION_DEADLINE_BREACH,
    INCOMPLETE_LOCKER_ROOM_EXAM]` — because the examination was left
    unconcluded."

    Design: Difficulty/transitive_cascade/sweep_breach_cascades_to_club_sanction_and_case_freeze
    """
    ctx = _setup_abandoned_examination_and_probation_club(api)

    summary = fx.run_sweep(api)

    assert summary["breached_evaluation_ids"] == [ctx["eval2_id"]]
    assert fx.read_evaluation(api, ctx["eval2_id"])["status"] == "PROTOCOL_BREACH"

    assert len(summary["auto_opened_audit_ids"]) == 1
    audit = fx.read_audit(api, summary["auto_opened_audit_ids"][0])
    assert audit["auto_opened"] is True
    assert audit["opened_by_user_id"] is None
    assert audit["sideline_evaluation_id"] == ctx["eval2_id"]
    assert audit["case_id"] is None
    assert audit["violation_codes"] == [
        "EVALUATION_DEADLINE_BREACH",
        "INCOMPLETE_LOCKER_ROOM_EXAM",
    ]
    assert audit["status"] == "FINDINGS_ISSUED"
    # (5000000 + 7500000) at exposure factor 1 and severity 1.00, x2.00 for the
    # stamped TIER_2.
    assert audit["escalation_tier_at_issuance"] == "TIER_2"
    assert audit["assessed_fine_cents"] == 25000000


def test_sweep_sanction_freezes_a_case_the_breach_never_touched(api):
    """
    The auto-issued findings drive the club below the posture floor, and the
    sanction — not the audit — freezes an unrelated case that was climbing the
    ladder.

    PRD §3.10: "When the recomputed score falls below 70 the club becomes
    `SANCTIONED`, from either `ACTIVE` or `PROBATION`, and every case of that club
    in `RTP_IN_PROGRESS` or `PENDING_INC_CLEARANCE` is frozen: `frozen_from_status`
    records the case's status as it stood and `case_status` becomes
    `STAGE_FROZEN`, with `heightened_review_required` true."

    Design: Difficulty/transitive_cascade/sweep_breach_cascades_to_club_sanction_and_case_freeze
    """
    ctx = _setup_abandoned_examination_and_probation_club(api)
    assert fx.read_case(api, ctx["case_id"])["case_status"] == "RTP_IN_PROGRESS"

    summary = fx.run_sweep(api)

    # 100 - 20 - 6 - 15 - 12 = 47; 21500000 already outstanding plus 25000000.
    assert_club_posture(
        fx.read_club(api, ctx["club_h_id"]),
        compliance_score=47,
        escalation_tier="TIER_3",
        status="SANCTIONED",
        outstanding_fine_cents=46500000,
    )

    assert summary["frozen_case_ids"] == [ctx["case_id"]]
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "STAGE_FROZEN"
    assert case["frozen_from_status"] == "RTP_IN_PROGRESS"
    assert case["heightened_review_required"] is True

    # The freeze is on the case, not on the step it left open.
    assert_return_step(fx.read_step(api, ctx["step_ids"][1]), stage_index=1, status="IN_PROGRESS")


# ─── Symptom check: recurrence -> denial -> revocation ───────────────────────

def test_symptom_check_recurrence_denies_the_pending_clearance(api):
    """
    A symptomatic check against a case awaiting final clearance denies that
    clearance itself and revokes the top passed rung.

    PRD §3.8: "Where the case was `PENDING_INC_CLEARANCE`, the check additionally
    denies the pending clearance as `DENIED_MORE_REST` with `decided_at` stamped
    from the logical clock, revokes the case's highest passed step by the same
    selection rule as a consultant's more-rest denial, drops `rtp_stage` to the
    greater of 0 and one less than its current value, clears `earliest_return_at`
    to null, and returns the case `PENDING_INC_CLEARANCE → RTP_IN_PROGRESS`."

    Design: Difficulty/transitive_cascade/symptom_check_cascades_to_denial_and_stage_five_revocation
    """
    ctx = fx.setup_case_pending_clearance(api)

    validate_success(
        api.symptom_check(
            ctx["case_id"], f.symptom_check_payload(symptom_score=5), ctx["doc_h_headers"]
        )
    )

    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "DENIED_MORE_REST"
    assert_instant(clearance["decided_at"], "2026-09-27T12:00:00.000Z")

    assert_return_step(fx.read_step(api, ctx["step_ids"][5]), stage_index=5, status="REVOKED")
    assert fx.read_case(api, ctx["case_id"])["case_status"] == "RTP_IN_PROGRESS"


def test_symptom_check_recurrence_rescores_severity_and_withdraws_the_return_date(api):
    """
    The same check counts as a recurrence, so severity is recomputed with the
    higher recurrence term while monitoring stays on active watch at one
    recurrence.

    PRD §3.8: "It stamps `last_symptomatic_at` from the logical clock, increases
    `recurrence_count` by 1, and recomputes `severity_index`."

    Design: Difficulty/transitive_cascade/symptom_check_cascades_to_denial_and_stage_five_revocation
    """
    ctx = fx.setup_case_pending_clearance(api)
    before = fx.read_case(api, ctx["case_id"])
    assert_case_progress(before, rtp_stage=5, recurrence_count=0, severity_index=82)

    validate_success(
        api.symptom_check(
            ctx["case_id"], f.symptom_check_payload(symptom_score=5), ctx["doc_h_headers"]
        )
    )

    case = fx.read_case(api, ctx["case_id"])
    # 40 + min(30, 27) + min(24, 12) + 0 + min(15, 27) = 94.
    assert_case_progress(
        case, rtp_stage=4, recurrence_count=1, severity_index=94, earliest_return_at=None
    )
    assert case["last_symptom_check_score"] == 5
    assert_instant(case["last_symptomatic_at"], "2026-09-27T12:00:00.000Z")
    assert_case_dimensions(case, monitoring_status="ACTIVE_SYMPTOM_WATCH")
