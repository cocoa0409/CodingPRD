"""
Writability that lives on another row: whether a case may take its next rung is a
function of the club's posture, and whether a consultant may decide is a function
of that clinician's standing.

Each pair is proved by holding the request identical and moving only the other
entity's state.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CASE_STAGE_FROZEN, ERR_CLEARANCE_STATE_INVALID, ERR_CLINICIAN_SUSPENDED
from test_helpers.assertions import assert_case_progress, assert_club_posture, assert_instant, assert_return_step
from test_helpers.test_users import AUDITOR_A, AUDITOR_B


# ─── ConcussionCase x Club: the club's posture decides the stage write ────────

def test_the_club_sanction_refuses_a_stage_the_case_is_otherwise_ready_for(api):
    """
    Stage two is legal on the case's own terms — the rung below is passed and the
    rest buffer has elapsed — yet the club's sanction refuses it.

    PRD §3.10: "While a case is `STAGE_FROZEN`, or while its club is `SANCTIONED`,
    the four return-to-participation writes — opening a stage, evaluating a stage,
    requesting final clearance, and returning to contact — are all refused with
    `ERR_CASE_STAGE_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/case_stage_write_depends_on_club_sanction_posture
    """
    ctx = fx.setup_case_through_stage(api, 1)
    audit = fx.open_audit(api, ctx["club_h_id"], opener_headers=AUDITOR_A)
    fx.issue_findings(
        api,
        audit["id"],
        ["UNAUTHORIZED_SAME_GAME_RETURN", "MISSING_INC_CLEARANCE"],
        0,
        issuer_headers=AUDITOR_B,
    )

    assert_club_posture(
        fx.read_club(api, ctx["club_h_id"]),
        compliance_score=55,
        escalation_tier="TIER_3",
        status="SANCTIONED",
    )
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "STAGE_FROZEN"
    assert case["frozen_from_status"] == "RTP_IN_PROGRESS"

    # Exactly stage two's min_start_at, so no time gate is in play.
    fx.set_clock(api, "2026-09-17T12:00:00Z")

    validate_error(
        api.create_return_step(
            ctx["case_id"], f.return_step_payload(stage_index=2), ctx["doc_h_headers"]
        ),
        ERR_CASE_STAGE_FROZEN,
        409,
    )


def test_dismissing_the_audit_restores_the_club_and_admits_the_same_stage(api):
    """
    A dismissal returns the club's figures to what they were, restores the case to
    the status it was frozen from, and the byte-identical stage request then
    succeeds.

    PRD §3.10: "When the score returns to 90 or above the club moves `SANCTIONED →
    ACTIVE` or `PROBATION → ACTIVE`, frozen cases are restored the same way, and
    `heightened_review_required` becomes false across the club's cases."

    Design: Difficulty/cross_entity_state_dependency/case_stage_write_depends_on_club_sanction_posture
    """
    ctx = fx.setup_case_through_stage(api, 1)
    audit = fx.open_audit(api, ctx["club_h_id"], opener_headers=AUDITOR_A)
    fx.issue_findings(
        api,
        audit["id"],
        ["UNAUTHORIZED_SAME_GAME_RETURN", "MISSING_INC_CLEARANCE"],
        0,
        issuer_headers=AUDITOR_B,
    )
    fx.set_clock(api, "2026-09-17T12:00:00Z")

    closed = fx.close_audit(
        api,
        audit["id"],
        disposition="DISMISSED",
        closing_note="video review shows the removal was timely",
    )
    assert closed["status"] == "CLOSED_DISMISSED"
    assert closed["assessed_fine_cents"] == 0

    assert_club_posture(
        fx.read_club(api, ctx["club_h_id"]),
        compliance_score=100,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=0,
    )
    restored = fx.read_case(api, ctx["case_id"])
    assert restored["case_status"] == "RTP_IN_PROGRESS"
    assert restored["frozen_from_status"] is None
    assert restored["heightened_review_required"] is False

    step = validate_success(
        api.create_return_step(
            ctx["case_id"], f.return_step_payload(stage_index=2), ctx["doc_h_headers"]
        ),
        201,
    )
    assert_return_step(step, stage_index=2, status="IN_PROGRESS")
    assert_instant(step["started_at"], "2026-09-17T12:00:00.000Z")
    assert_instant(step["dwell_complete_at"], "2026-09-18T12:00:00.000Z")


# ─── IncClearance x Clinician: the consultant's standing decides the ruling ───

def test_suspending_the_consultant_supersedes_the_clearance_without_unwinding_the_ladder(api):
    """
    The suspension reaches the pending clearance and pushes the case back to the
    ladder, but leaves stage five passed and the accrued return date standing.

    PRD §3.1: "The cascade then reaches every consultant clearance still `PENDING`
    whose `inc_clinician_id` is the suspended clinician: each such clearance becomes
    `SUPERSEDED`, and each such clearance's case returns from `PENDING_INC_CLEARANCE`
    to `RTP_IN_PROGRESS` **without any return step being revoked and without
    `rtp_stage` moving**."

    Design: Difficulty/cross_entity_state_dependency/inc_decision_depends_on_consultant_suspension_state
    """
    ctx = fx.setup_case_pending_clearance(api)

    fx.suspend_clinician(api, ctx["inc_id"], "license board inquiry opened")

    assert fx.read_clinician(api, ctx["inc_id"])["status"] == "SUSPENDED"

    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "SUPERSEDED"
    assert clearance["decided_at"] is None

    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "RTP_IN_PROGRESS"
    assert_case_progress(
        case, rtp_stage=5, earliest_return_at=fx.CANONICAL_EARLIEST_RETURN_AT
    )
    assert_return_step(fx.read_step(api, ctx["step_ids"][5]), stage_index=5, status="PASSED")


def test_a_suspended_consultant_is_refused_on_standing_not_on_clearance_state(api):
    """
    The suspended consultant's approval is refused for his own standing, which is
    checked ahead of the clearance's superseded state.

    PRD §2.5 rung 9: "**Credential standing.** The acting clinician's `status` is
    `ACTIVE`, else `ERR_CLINICIAN_SUSPENDED` (409)."

    Design: Difficulty/cross_entity_state_dependency/inc_decision_depends_on_consultant_suspension_state
    """
    ctx = fx.setup_case_pending_clearance(api)
    fx.suspend_clinician(api, ctx["inc_id"], "license board inquiry opened")

    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(
            decision="APPROVED", decision_notes="attempting to clear after suspension"
        ),
        ctx["inc_headers"],
    )
    error = validate_error(response, ERR_CLINICIAN_SUSPENDED, 409)
    assert error["error_id"] != ERR_CLEARANCE_STATE_INVALID

    assert fx.read_clearance(api, ctx["clearance_id"])["status"] == "SUPERSEDED"
