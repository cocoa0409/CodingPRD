"""Correspondence surveillance: provisional vs final risk score variants,
the escalation fork-join, segregation of duties, and the review-deadline
sweep (PRD §3.3, §2.5, §2.6).
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_rep,
    make_branch_with_rep,
    make_correspondence,
    make_escalated_correspondence,
    review_item,
    set_clock,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
PRINCIPAL_B = TEST_USERS["principal_b_headers"]
ANY = TEST_USERS["any_headers"]


# ─── dual-variant correspondence risk score ───────────

class TestProvisionalVsFinalCorrespondenceRisk:
    def test_provisional_score_formula_at_capture(self, api, any_headers):
        """PRD §3.3: "The provisional risk score is a weighted sum in integer
        points, capped at 100: ten points per lexicon hit, plus a channel
        weight — 5 for `EMAIL`, 10 for `PAPER_LETTER`, 20 for `SMS`, and 25
        for `SOCIAL_MEDIA` — plus 30 additional points when the authoring
        representative's current `supervision_tier` is `HEIGHTENED`, and zero
        when it is `STANDARD`." One lexicon hit on EMAIL for a STANDARD rep
        provisions at 10*1 + 5 + 0 = 15.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_correspondence_risk
        """
        _branch, rep = make_branch_with_rep(region="NE", crd_number="100001")
        item = make_correspondence(rep["id"], channel="EMAIL", lexicon_hits=1,
                                   subject="Client note")
        assert item["provisional_risk_score"] == 15
        assert item["status"] == "PENDING_REVIEW"
        assert item.get("final_risk_score") is None

    def test_flag_decision_clamps_final_score_to_floor(self, api, any_headers):
        """PRD §3.3: "A `FLAG` decision moves the item to `FLAGGED`, stamps
        `reviewed_by`, sets `final_risk_score` to the greater of the
        provisional score and 70 — so a provisional 20 flags at 70 — and
        increments the representative's `compliance_flag_count` by one."
        Identical item data yields provisional 15 but final 70: the two
        variants diverge on the same inputs.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_correspondence_risk
        """
        _branch, rep = make_branch_with_rep(region="NE", crd_number="100001")
        item = make_correspondence(rep["id"], channel="EMAIL", lexicon_hits=1,
                                   subject="Client note")
        assert item["provisional_risk_score"] == 15

        flagged = review_item(item["id"], "FLAG", PRINCIPAL_A)
        assert flagged["status"] == "FLAGGED"
        assert flagged["final_risk_score"] == 70
        assert flagged["final_risk_score"] != item["provisional_risk_score"]
        assert flagged.get("reviewed_by") == "principal-a"
        assert get_rep(rep["id"])["compliance_flag_count"] == 1


# ─── escalation fork-join ─────────────────────────────

class TestCorrespondenceEscalationBranch:
    def test_escalation_approve_clamps_final_score_down(self, api, any_headers):
        """PRD §3.3: "A resolving `APPROVE` moves the item to `APPROVED`,
        stamps `resolved_by`, and sets `final_risk_score` to the lesser of
        the provisional score and 30 — so a provisional 80 resolves down to
        30." An SMS item with 5 hits provisions at 10*5 + 20 = 70 and
        resolves down to 30.

        Design: Difficulty/non_linear_state_machine/nonlinear_correspondence_escalation_branch
        """
        _branch, rep = make_branch_with_rep(region="N", crd_number="100004")
        item = make_correspondence(rep["id"], channel="SMS", lexicon_hits=5,
                                   subject="urgent")
        assert item["provisional_risk_score"] == 70

        escalated = review_item(item["id"], "ESCALATE", PRINCIPAL_A)
        assert escalated["status"] == "ESCALATED"

        resolved = validate_success(
            api.resolve_escalation(item["id"], {"decision": "APPROVE"},
                                   PRINCIPAL_B),
            200,
        )
        assert resolved["status"] == "APPROVED"
        assert resolved["final_risk_score"] == 30

    def test_escalation_stamps_both_principals_without_flag_side_effect(
        self, api, any_headers
    ):
        """PRD §2.6: "Correspondence items carry `reviewed_by` (the first
        reviewing principal), `escalated_by` (the escalating principal, null
        unless the item was escalated), and `resolved_by` (the principal who
        resolved an escalation, null unless resolved)." Only FLAG decisions
        increment the flag counter: "A resolving `FLAG` moves the item to
        `FLAGGED`, stamps `resolved_by`, sets `final_risk_score` to the
        greater of the provisional score and 70, and increments the
        representative's `compliance_flag_count`." An escalation-resolved
        APPROVE therefore leaves it at zero.

        Design: Difficulty/non_linear_state_machine/nonlinear_correspondence_escalation_branch
        """
        _branch, rep = make_branch_with_rep(region="N", crd_number="100004")
        item = make_correspondence(rep["id"], channel="SMS", lexicon_hits=5,
                                   subject="urgent")
        escalated = review_item(item["id"], "ESCALATE", PRINCIPAL_A)
        assert escalated.get("escalated_by") == "principal-a"

        resolved = validate_success(
            api.resolve_escalation(item["id"], {"decision": "APPROVE"},
                                   PRINCIPAL_B),
            200,
        )
        assert resolved.get("escalated_by") == "principal-a"
        assert resolved.get("resolved_by") == "principal-b"
        assert get_rep(rep["id"])["compliance_flag_count"] == 0


# ─── segregation of duties on escalation ──────────────

def test_escalation_resolver_must_differ_from_escalator(api, any_headers):
    """PRD §2.6: "a correspondence escalation may only be resolved by a
    principal whose `X-User-ID` differs from the identifier recorded in the
    item's `escalated_by` field; an attempt by the same principal to resolve
    their own escalation is rejected with `ERR_SOD_ESCALATION_RESOLVER`
    (HTTP 403)."

    Design: Corner/state_machines/sod_escalation_resolver
    """
    _rep, item = make_escalated_correspondence(channel="EMAIL", lexicon_hits=0)
    assert item["status"] == "ESCALATED"

    res = api.resolve_escalation(item["id"], {"decision": "APPROVE"},
                                 PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_SOD_ESCALATION_RESOLVER)

    resolved = validate_success(
        api.resolve_escalation(item["id"], {"decision": "APPROVE"}, PRINCIPAL_B),
        200,
    )
    assert resolved["status"] == "APPROVED"
    assert resolved.get("resolved_by") == "principal-b"


# ─── terminal correspondence lockdown ─────────────────

def test_review_of_approved_item_rejected(api, any_headers):
    """PRD §3.3: "Reviewing an item in `PENDING_REVIEW` or `OVERDUE` —
    review from any other state is rejected with
    `ERR_CORRESPONDENCE_INVALID_STATE`" and "`APPROVED` and `FLAGGED` are
    terminal". The APPROVE-written final score (provisional unchanged, 5 for
    a zero-hit EMAIL) survives the rejected second review.

    Design: Corner/state_machines/review_approved_correspondence_rejected
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="910002")
    item = make_correspondence(rep["id"], channel="EMAIL", lexicon_hits=0,
                               subject="ok")
    approved = review_item(item["id"], "APPROVE", PRINCIPAL_A)
    assert approved["status"] == "APPROVED"
    assert approved["final_risk_score"] == 5

    res = api.review_correspondence_item(item["id"], {"decision": "FLAG"},
                                         PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_CORRESPONDENCE_INVALID_STATE)
    after = validate_success(api.get_correspondence_item(item["id"], ANY), 200)
    assert after["final_risk_score"] == 5
    assert after["status"] == "APPROVED"


# ─── escalation-resolution FLAG clamp ─────────────────

def test_escalation_flag_clamps_up_and_increments_counter(api, any_headers):
    """PRD §3.3: "A resolving `FLAG` moves the item to `FLAGGED`, stamps
    `resolved_by`, sets `final_risk_score` to the greater of the provisional
    score and 70, and increments the representative's
    `compliance_flag_count`." Provisional 25 (EMAIL, 2 hits) clamps to 70
    and the counter moves exactly once.

    Design: Corner/calculations/correspondence_final_score_clamp_on_escalate_flag
    """
    rep, item = make_escalated_correspondence(channel="EMAIL", lexicon_hits=2)
    assert item["provisional_risk_score"] == 25

    resolved = validate_success(
        api.resolve_escalation(item["id"], {"decision": "FLAG"}, PRINCIPAL_B),
        200,
    )
    assert resolved["status"] == "FLAGGED"
    assert resolved["final_risk_score"] == 70
    assert get_rep(rep["id"])["compliance_flag_count"] == 1


# ─── review deadline sweep ────────────────────────────

def test_review_deadline_sweep_and_late_review(api, any_headers):
    """PRD §3.3: "Capture stamps `captured_at` from the logical clock, sets
    the `review_deadline` to exactly 30 days after `captured_at`". PRD §2.5:
    "Any CorrespondenceItem in `PENDING_REVIEW` whose `review_deadline` is
    earlier than the new clock time transitions to `OVERDUE`." PRD §3.3: "an
    item left unreviewed past its `review_deadline` is swept to `OVERDUE` per
    §2.5 but remains reviewable", and the APPROVE variant "sets
    `final_risk_score` equal to the provisional score unchanged" (5 for a
    zero-hit EMAIL).

    Design: Corner/cross_cutting/review_deadline_sweep_and_late_review
    """
    _branch, rep = make_branch_with_rep(region="N", crd_number="960003")
    item = make_correspondence(rep["id"], channel="EMAIL", lexicon_hits=0,
                               subject="newsletter")
    deadline = datetime.fromisoformat(
        item["review_deadline"].replace("Z", "+00:00")
    )
    assert deadline == datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)

    set_clock("2026-08-31T00:00:01Z")
    swept = validate_success(api.get_correspondence_item(item["id"], ANY), 200)
    assert swept["status"] == "OVERDUE"

    reviewed = validate_success(
        api.review_correspondence_item(item["id"], {"decision": "APPROVE"},
                                       PRINCIPAL_A),
        200,
    )
    assert reviewed["status"] == "APPROVED"
    assert reviewed["final_risk_score"] == 5
