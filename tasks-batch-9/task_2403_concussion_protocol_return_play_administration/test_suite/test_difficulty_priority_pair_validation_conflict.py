"""
Refusal precedence: one request that breaks two rules at once returns exactly one
error, and it must be the earlier rung's.

Each pair is proved twice — once that the earlier rung wins, and once that the
later rung was genuinely live rather than absent.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_STAGE_FROZEN,
    ERR_CLUB_FINE_CAP_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_club_posture, assert_page_meta
from test_helpers.test_users import ADMIN, AUDITOR_A, AUDITOR_B


# ─── Freeze guard before stage sequencing ────────────────────────────────────

def test_frozen_case_reports_the_freeze_rather_than_the_stage_skip(api):
    """
    A stage request that both skips a rung and targets a frozen case reports the
    freeze, because the freeze guard sits above the sequencing rule.

    PRD §2.5 rung 11: "**Freeze guard.** The owning case is not `STAGE_FROZEN` and
    the owning club's `status` is not `SANCTIONED`, else `ERR_CASE_STAGE_FROZEN`
    (409). Applies to exactly four operations: stage creation, stage evaluation,
    the final-clearance request and return to contact."

    Design: Difficulty/priority_pair_validation_conflict/frozen_case_state_error_precedes_stage_sequence_error
    """
    ctx = fx.setup_case_through_stage(api, 1)
    fx.sanction_club(api, ctx["club_h_id"])
    # The stage-two rest buffer has elapsed, so timing cannot be the reason.
    fx.set_clock(api, "2026-09-17T12:00:00Z")

    # stage_index 3 while rtp_stage is 1 also breaks the sequencing rule.
    response = api.create_return_step(
        ctx["case_id"], f.return_step_payload(stage_index=3), ctx["doc_h_headers"]
    )
    error = validate_error(response, ERR_CASE_STAGE_FROZEN, 409)
    assert error["error_id"] == ERR_CASE_STAGE_FROZEN


def test_the_refused_stage_request_leaves_the_frozen_case_untouched(api):
    """
    The refusal writes nothing: the case keeps the rung it had and no new step
    row appears.

    PRD §3.10: "While a case is `STAGE_FROZEN`, or while its club is `SANCTIONED`,
    the four return-to-participation writes — opening a stage, evaluating a stage,
    requesting final clearance, and returning to contact — are all refused with
    `ERR_CASE_STAGE_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_case_state_error_precedes_stage_sequence_error
    """
    ctx = fx.setup_case_through_stage(api, 1)
    fx.sanction_club(api, ctx["club_h_id"])
    fx.set_clock(api, "2026-09-17T12:00:00Z")

    api.create_return_step(
        ctx["case_id"], f.return_step_payload(stage_index=3), ctx["doc_h_headers"]
    )

    assert_club_posture(
        fx.read_club(api, ctx["club_h_id"]),
        compliance_score=55,
        escalation_tier="TIER_3",
        status="SANCTIONED",
    )
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "STAGE_FROZEN"
    assert case["rtp_stage"] == 1

    steps, meta = validate_paginated(api.list_return_steps(ADMIN, case_id=ctx["case_id"]))
    assert_page_meta(meta, total_count=1)
    assert len(steps) == 1
    assert steps[0]["stage_index"] == 1


# ─── Segregation of duties before the season fine cap ───────────────────────

def test_the_opener_issuing_findings_reports_segregation_not_the_fine_cap(api):
    """
    When the opening auditor issues findings that would also breach the season
    cap, the segregation rule answers first.

    PRD §2.5 rung 18: "`ERR_SEGREGATION_OF_DUTIES` (403) — the auditor who opened
    an audit issuing its findings, or the auditor who issued the findings closing
    the audit."

    Design: Difficulty/priority_pair_validation_conflict/findings_segregation_of_duties_error_precedes_fine_cap_error
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    audit1 = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    first = fx.issue_findings(
        api, audit1["id"], ["UNAUTHORIZED_SAME_GAME_RETURN"], 30, issuer_headers=AUDITOR_B
    )
    # 25000000 * 37/7, rounded once per line and once after the TIER_0 multiplier.
    assert first["assessed_fine_cents"] == 132142857
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=75,
        escalation_tier="TIER_1",
        status="PROBATION",
    )

    audit2 = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)

    # 30000000 more would take the outstanding total past the 150000000 cap.
    response = api.issue_findings(
        audit2["id"],
        f.findings_payload(violation_codes=["MISSING_INC_CLEARANCE"], exposure_days=0),
        AUDITOR_A,
    )
    error = validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)
    assert error["error_id"] == ERR_SEGREGATION_OF_DUTIES


def test_a_different_auditor_then_hits_the_live_fine_cap(api):
    """
    Re-issuing the identical findings as a different auditor proves the cap rule
    was live all along, and the refused audit keeps no price.

    PRD §2.8: "Because a club may not be fined without limit in one season, the
    total `outstanding_fine_cents` that would result from issuing findings must
    not exceed the season cap of 150000000 cents; findings that would breach it
    are refused with `ERR_CLUB_FINE_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/findings_segregation_of_duties_error_precedes_fine_cap_error
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    audit1 = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    fx.issue_findings(
        api, audit1["id"], ["UNAUTHORIZED_SAME_GAME_RETURN"], 30, issuer_headers=AUDITOR_B
    )
    audit2 = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)

    # The opener is refused on segregation grounds first.
    validate_error(
        api.issue_findings(
            audit2["id"],
            f.findings_payload(violation_codes=["MISSING_INC_CLEARANCE"], exposure_days=0),
            AUDITOR_A,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    response = api.issue_findings(
        audit2["id"],
        f.findings_payload(violation_codes=["MISSING_INC_CLEARANCE"], exposure_days=0),
        AUDITOR_B,
    )
    validate_error(response, ERR_CLUB_FINE_CAP_EXCEEDED, 409)

    still_open = validate_success(api.get_protocol_audit(audit2["id"], AUDITOR_B))
    assert still_open["status"] == "OPEN"
    assert still_open["assessed_fine_cents"] == 0
    assert still_open["escalation_tier_at_issuance"] is None

    assert fx.read_club(api, club["id"])["outstanding_fine_cents"] == 132142857
