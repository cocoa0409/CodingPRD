"""
Cyclic state machines: a case can travel back down the ladder it climbed, and an
audit can be re-priced after the club has answered it.

Neither loop is a no-op — each return to a previously held status carries a
distinct side effect that the tests below pin down.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_case_progress, assert_club_posture, assert_return_step
from test_helpers.test_users import AUDITOR_A, AUDITOR_B, make_compliance_officer_headers


# ─── ConcussionCase: PENDING_INC_CLEARANCE back to RTP_IN_PROGRESS ───────────

def test_more_rest_denial_revokes_the_highest_passed_step(api):
    """
    A more-rest denial sends the case back down a rung by revoking its highest
    passed step and leaving the rung below it untouched.

    PRD §3.7: "The case's highest passed return step — selected by the greatest
    `stage_index`, then the greatest `attempt_index`, then the most recent
    `created_at` — moves `PASSED → REVOKED`, meaning that stage must be repeated
    as a new step with the next `attempt_index`."

    Design: Difficulty/non_linear_state_machine/case_status_cycles_pending_clearance_back_to_rtp_on_denial
    """
    ctx = fx.setup_case_pending_clearance(api)

    decided = validate_success(
        api.decide_inc_clearance(
            ctx["clearance_id"],
            f.clearance_decision_payload(
                decision="DENIED_MORE_REST",
                decision_notes="symptom diary still abnormal, further rest required",
            ),
            ctx["inc_headers"],
        )
    )
    assert decided["status"] == "DENIED_MORE_REST"

    assert_return_step(fx.read_step(api, ctx["step_ids"][5]), stage_index=5, status="REVOKED")
    assert_return_step(fx.read_step(api, ctx["step_ids"][4]), stage_index=4, status="PASSED")


def test_more_rest_denial_returns_the_case_to_the_ladder_without_charging_a_recurrence(api):
    """
    The case cycles back to the in-progress status it already held, one rung
    lower and with the accrued return date withdrawn, but no recurrence is
    recorded.

    PRD §3.7: "The case's `rtp_stage` drops to the greater of 0 and one less than
    its current value, `earliest_return_at` is cleared to null, and the case
    returns `PENDING_INC_CLEARANCE → RTP_IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/case_status_cycles_pending_clearance_back_to_rtp_on_denial
    """
    ctx = fx.setup_case_pending_clearance(api)
    assert fx.read_case(api, ctx["case_id"])["case_status"] == "PENDING_INC_CLEARANCE"

    fx.decide_clearance(
        api,
        ctx,
        decision="DENIED_MORE_REST",
        decision_notes="symptom diary still abnormal, further rest required",
    )

    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "RTP_IN_PROGRESS"
    assert_case_progress(case, rtp_stage=4, recurrence_count=0, earliest_return_at=None)


# ─── ProtocolAudit: FINDINGS_ISSUED to CLUB_RESPONDED and back ───────────────

def test_a_club_response_moves_the_audit_without_touching_any_arithmetic(api):
    """
    Responding records the club's note and its round count while leaving the
    compliance figures exactly where the findings put them.

    PRD §3.10: "Responding changes no compliance arithmetic whatsoever: a
    `CLUB_RESPONDED` audit remains inside the preliminary score's included set,
    so `compliance_score` and `outstanding_fine_cents` are exactly what they
    were."

    Design: Difficulty/non_linear_state_machine/audit_findings_response_findings_revision_cycle
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    fx.issue_findings(api, audit["id"], ["LATE_INJURY_REPORT"], 0, issuer_headers=AUDITOR_B)

    # 100 - 6 for the late-filing weight.
    assert fx.read_club(api, club["id"])["compliance_score"] == 94

    responded = validate_success(
        api.respond_to_audit(
            audit["id"],
            f.audit_response_payload("the filing delay was caused by a league portal outage"),
            make_compliance_officer_headers(club["id"]),
        )
    )
    assert responded["status"] == "CLUB_RESPONDED"
    assert responded["response_round_count"] == 1
    assert responded["club_response_note"] == (
        "the filing delay was caused by a league portal outage"
    )

    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=94,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=1500000,
    )


def test_revised_findings_replace_the_codes_and_re_price_from_scratch(api):
    """
    Findings re-issued from CLUB_RESPONDED overwrite the codes the audit carried
    and re-stamp the tier from a score computed with this audit excluded.

    PRD §3.10: "Findings may be issued from `OPEN`, taking the audit `OPEN →
    FINDINGS_ISSUED`, or re-issued from `CLUB_RESPONDED`, taking it
    `CLUB_RESPONDED → FINDINGS_ISSUED` as a revision; from any other status the
    request is refused with `ERR_AUDIT_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/audit_findings_response_findings_revision_cycle
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    fx.issue_findings(api, audit["id"], ["LATE_INJURY_REPORT"], 0, issuer_headers=AUDITOR_B)
    fx.respond_to_audit(api, audit["id"], club["id"])

    revised = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(violation_codes=["MISSED_MANDATORY_REMOVAL"], exposure_days=0),
            AUDITOR_B,
        )
    )

    assert revised["status"] == "FINDINGS_ISSUED"
    assert revised["violation_codes"] == ["MISSED_MANDATORY_REMOVAL"]
    # Excluding this audit restores the clean score, so the tier is TIER_0 again.
    assert revised["escalation_tier_at_issuance"] == "TIER_0"
    assert revised["assessed_fine_cents"] == 15000000
    assert revised["response_round_count"] == 1, "a revision does not reset the round count"

    # The old LATE_INJURY_REPORT weight is gone; only the new one is charged.
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
    )
