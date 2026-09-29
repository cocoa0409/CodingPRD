"""
Penalty pricing: where the fine lands depends on the order of the rounding steps
and on which escalation tier is read.

Both are one-cent-visible decisions, so each is asserted against the exact figure
the contract derives and against the figure the wrong reading would produce.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_club_posture
from test_helpers.test_users import AUDITOR_A, AUDITOR_B


# ─── Round each violation line, then sum ─────────────────────────────────────

def test_two_violation_lines_are_rounded_individually_before_being_summed(api):
    """
    Two lines that each round up must be rounded before summing, which lands one
    cent above the figure produced by summing first.

    PRD §2.10: "Summing unrounded line values and rounding a single time at the
    end produces a different, incorrect result; the two-stage discipline is
    normative."

    Design: Difficulty/combinatorial_formula/audit_fine_rounds_each_violation_line_before_summing
    """
    ctx = fx.setup_diagnosed_case(api)
    audit = fx.open_audit(
        api,
        ctx["club_h_id"],
        case_id=ctx["case_id"],
        sideline_evaluation_id=ctx["eval_id"],
        opener_headers=AUDITOR_A,
    )

    issued = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(
                violation_codes=["MISSING_INC_CLEARANCE", "UNAUTHORIZED_SAME_GAME_RETURN"],
                exposure_days=2,
            ),
            AUDITOR_B,
        )
    )

    # Exposure factor 9/7, severity factor 1.15 (the linked case scores 82).
    # 25000000 * 9/7 * 1.15 -> 36964286 and 20000000 * 9/7 * 1.15 -> 29571429,
    # summing to 66535715; rounding only at the end would give 66535714.
    assert issued["status"] == "FINDINGS_ISSUED"
    assert issued["escalation_tier_at_issuance"] == "TIER_0"
    assert issued["assessed_fine_cents"] == 66535715
    assert issued["assessed_fine_cents"] != 66535714


def test_the_rounded_fine_is_the_figure_carried_into_the_club_ledger(api):
    """
    The per-line rounded total is what the club's ledger and posture are rebuilt
    from, and the resulting sanction reaches the club's open case.

    PRD §2.8: "Recompute `outstanding_fine_cents` as the sum of
    `assessed_fine_cents` over the club's audits whose `status` is
    `FINDINGS_ISSUED`, `CLUB_RESPONDED` or `CLOSED_UPHELD`."

    Design: Difficulty/combinatorial_formula/audit_fine_rounds_each_violation_line_before_summing
    """
    ctx = fx.setup_diagnosed_case(api)
    audit = fx.open_audit(
        api,
        ctx["club_h_id"],
        case_id=ctx["case_id"],
        sideline_evaluation_id=ctx["eval_id"],
        opener_headers=AUDITOR_A,
    )
    fx.issue_findings(
        api,
        audit["id"],
        ["MISSING_INC_CLEARANCE", "UNAUTHORIZED_SAME_GAME_RETURN"],
        2,
        issuer_headers=AUDITOR_B,
    )

    # Weights 20 + 25 charged against the preliminary score.
    club = fx.read_club(api, ctx["club_h_id"])
    assert_club_posture(
        club,
        compliance_score=55,
        escalation_tier="TIER_3",
        status="SANCTIONED",
        outstanding_fine_cents=66535715,
    )

    # The case has not started the ladder, so the sanction cannot freeze it, but
    # heightened review still lands on it.
    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "MANDATORY_REMOVAL"
    assert case["heightened_review_required"] is True


# ─── Price with the tier stamped before the audit's own score impact ─────────

def test_findings_are_priced_with_the_tier_read_before_the_posture_routine(api):
    """
    The tier stamped on an audit excludes that audit, so a second audit prices at
    the tier the club held beforehand rather than at the tier it lands on.

    PRD §2.8: "Critically, the escalation tier used to *price* an audit is read
    before step 1 of this routine runs — see §3.9."

    Design: Difficulty/combinatorial_formula/audit_fine_uses_tier_stamped_before_its_own_score_impact
    """
    ctx = fx.setup_diagnosed_case(api)

    # A first audit takes the club to 100 - 15 = 85, TIER_1, PROBATION.
    audit1 = fx.open_audit(api, ctx["club_h_id"], opener_headers=AUDITOR_A)
    first = fx.issue_findings(
        api, audit1["id"], ["EVALUATION_DEADLINE_BREACH"], 0, issuer_headers=AUDITOR_B
    )
    assert first["assessed_fine_cents"] == 5000000

    audit2 = fx.open_audit(
        api, ctx["club_h_id"], case_id=ctx["case_id"], opener_headers=AUDITOR_A
    )
    issued = validate_success(
        api.issue_findings(
            audit2["id"],
            f.findings_payload(violation_codes=["MISSED_MANDATORY_REMOVAL"], exposure_days=2),
            AUDITOR_B,
        )
    )

    # 15000000 * 9/7 * 1.15 -> 22178571, then x1.50 for the stamped TIER_1
    # -> 33267857.  Pricing at the post-transaction TIER_2 would give 44357142.
    assert issued["escalation_tier_at_issuance"] == "TIER_1"
    assert issued["assessed_fine_cents"] == 33267857
    assert issued["assessed_fine_cents"] != 44357142


def test_the_club_lands_on_a_lower_tier_than_the_one_that_priced_the_audit(api):
    """
    After the posture routine the club's live tier is below the tier stamped on
    the audit, which is exactly why the stamped value has to be read first.

    PRD §2.8: "`escalation_tier` is `TIER_0` when `compliance_score` is at least
    90, `TIER_1` when it lies between 75 and 89 inclusive, `TIER_2` when it lies
    between 60 and 74 inclusive, and `TIER_3` when it is below 60."

    Design: Difficulty/combinatorial_formula/audit_fine_uses_tier_stamped_before_its_own_score_impact
    """
    ctx = fx.setup_diagnosed_case(api)

    audit1 = fx.open_audit(api, ctx["club_h_id"], opener_headers=AUDITOR_A)
    fx.issue_findings(api, audit1["id"], ["EVALUATION_DEADLINE_BREACH"], 0, issuer_headers=AUDITOR_B)
    audit2 = fx.open_audit(
        api, ctx["club_h_id"], case_id=ctx["case_id"], opener_headers=AUDITOR_A
    )
    fx.issue_findings(api, audit2["id"], ["MISSED_MANDATORY_REMOVAL"], 2, issuer_headers=AUDITOR_B)

    # 100 - 15 - 18 = 67, which is TIER_2 but already below the posture floor.
    club = fx.read_club(api, ctx["club_h_id"])
    assert_club_posture(
        club,
        compliance_score=67,
        escalation_tier="TIER_2",
        status="SANCTIONED",
        outstanding_fine_cents=38267857,
    )

    stamped = fx.read_audit(api, audit2["id"])
    assert stamped["escalation_tier_at_issuance"] == "TIER_1"
    assert stamped["escalation_tier_at_issuance"] != club["escalation_tier"]
