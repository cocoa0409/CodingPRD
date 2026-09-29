"""
Two-variant calculations that must disagree at the same observable instant.

A concussion case publishes a provisional return projection stamped at diagnosis
and an accrued return date derived from the stage-five sign-off; a club publishes
a preliminary compliance score and an adjudicated one.  In both pairs the two
figures answer the same question and are required to differ.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_case_progress,
    assert_club_posture,
    assert_instant,
)
from test_helpers.test_users import AUDITOR_A, AUDITOR_B, AUDITOR_C


# ─── ConcussionCase: provisional projection versus accrued return date ───────

def test_stage_five_pass_accrues_the_gating_return_date(api):
    """
    Passing stage five computes the case's accrued return timeline, which is the
    figure that actually gates return to contact.

    PRD §3.6: "When the stage that passes is stage 5, the server computes the
    case's `earliest_return_at` — the **final accrued** return timeline — as that
    step's `evaluated_at` plus one day, plus a further two days for each
    recurrence the case has accumulated, using `recurrence_count` as it stands at
    the moment of that pass."

    Design: Difficulty/dual_variant_calc/case_provisional_projection_diverges_from_accrued_return_date
    """
    # Stages one to four passed on the earliest legal instants, stage five open
    # since 2026-09-25T12:00:00Z.
    ctx = fx.setup_case_with_stage_open(api, 5)

    # The dwell for stage five is two days, so 2026-09-27T12:00:00Z is the
    # earliest instant the pass is legal.
    fx.set_clock(api, fx.STAGE_FIVE_SIGNOFF_AT)
    step = validate_success(
        api.evaluate_return_step(
            ctx["step_ids"][5],
            f.evaluate_step_payload(outcome="PASS", symptom_score=0),
            ctx["doc_h_headers"],
        )
    )

    assert step["status"] == "PASSED"

    case = fx.read_case(api, ctx["case_id"])
    assert_case_progress(case, rtp_stage=5, recurrence_count=0, severity_index=82)
    # Sign-off 2026-09-27T12:00:00Z + one day, with no recurrences to add.
    assert_instant(case["earliest_return_at"], "2026-09-28T12:00:00.000Z")
    assert case["case_status"] == "RTP_IN_PROGRESS", (
        "completing the ladder does not itself return the player to contact"
    )


def test_provisional_projection_survives_the_ladder_and_trails_the_accrued_date(api):
    """
    The projection stamped at diagnosis is never revised by the ladder, so once
    stage five accrues the real date the two figures disagree.

    PRD §3.5: "This figure is stamped exactly once and is never revised — not by
    recurrences, not by stage failures, not by anything."

    Design: Difficulty/dual_variant_calc/case_provisional_projection_diverges_from_accrued_return_date
    """
    ctx = fx.setup_case_with_stage_open(api, 5)

    # Diagnosis 2026-09-13T18:19:00Z + seven days + three more for severity 82.
    assert_instant(ctx["projected_return_at"], "2026-09-23T18:19:00.000Z")

    fx.set_clock(api, fx.STAGE_FIVE_SIGNOFF_AT)
    fx.sign_off_stage(api, ctx, 5, symptom_score=0)

    case = fx.read_case(api, ctx["case_id"])
    assert_instant(case["projected_return_at"], "2026-09-23T18:19:00.000Z")
    assert_instant(case["earliest_return_at"], "2026-09-28T12:00:00.000Z")
    assert case["earliest_return_at"] > case["projected_return_at"], (
        "the accrued gating date must trail the provisional publication figure"
    )


# ─── Club: preliminary compliance score versus adjudicated ──────────────────

def test_findings_move_the_preliminary_score_while_the_adjudicated_score_holds(api):
    """
    Issuing findings charges the preliminary score immediately while the
    adjudicated score still counts only closed-upheld audits.

    PRD §2.8: "`adjudicated_compliance_score` is the **adjudicated** figure,
    computed by exactly the same arithmetic but including only audits whose
    `status` is `CLOSED_UPHELD`."

    Design: Difficulty/dual_variant_calc/club_compliance_preliminary_diverges_from_adjudicated_score
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)

    issued = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(violation_codes=["MISSED_MANDATORY_REMOVAL"], exposure_days=0),
            AUDITOR_B,
        )
    )
    # Exposure factor 7/7 and no case link, so the fine is the bare base amount.
    assert issued["assessed_fine_cents"] == 15000000
    assert issued["status"] == "FINDINGS_ISSUED"

    # 100 - 18 preliminary; the adjudicated set is still empty.
    club_row = fx.read_club(api, club["id"])
    assert_club_posture(
        club_row,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        adjudicated_compliance_score=100,
    )

    summary = fx.read_compliance_summary(api, club["id"])
    assert summary["compliance_score"] == 82
    assert summary["adjudicated_compliance_score"] == 100


def test_upholding_the_audit_pulls_the_adjudicated_score_down_to_the_preliminary(api):
    """
    Closing the audit upheld leaves the preliminary score untouched and drops the
    adjudicated score onto it.

    PRD §3.10: "Because `CLOSED_UPHELD` sits inside both included sets,
    `compliance_score` and `outstanding_fine_cents` do not move; what changes is
    that `adjudicated_compliance_score` now drops to absorb the audit's weights
    and `open_violation_count` falls by 1."

    Design: Difficulty/dual_variant_calc/club_compliance_preliminary_diverges_from_adjudicated_score
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    fx.issue_findings(api, audit["id"], ["MISSED_MANDATORY_REMOVAL"], 0, issuer_headers=AUDITOR_B)

    closed = validate_success(
        api.close_audit(
            audit["id"],
            f.audit_close_payload(disposition="UPHELD", closing_note="violation upheld on review"),
            AUDITOR_C,
        )
    )
    assert closed["status"] == "CLOSED_UPHELD"
    assert closed["assessed_fine_cents"] == 15000000

    club_row = fx.read_club(api, club["id"])
    assert_club_posture(
        club_row,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=0,
        adjudicated_compliance_score=82,
    )
