"""Deviation recording: severity classification, risk scoring, supersede
invariants, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_deviation, assert_negotiation,
    setup_redlining_ctx, record_deviation, approve_deviation, begin_review,
    refresh_negotiation, get_deviation, open_round, close_round,
)

RISK_CLAUSES = [
    {"clause_key": "LOI", "category": "RISK", "standard_text": "std",
     "fallback_positions": ["fb1"], "approver_role_required": "LEGAL_COUNSEL",
     "deviation_severity_cap": "HIGH"},
    {"clause_key": "PAYMENT", "category": "RISK", "standard_text": "std",
     "fallback_positions": ["fb1"], "approver_role_required": "LEGAL_COUNSEL",
     "deviation_severity_cap": "LOW"},
]


class TestSeverityClassification:
    def test_fallback_index_zero_is_fallback_and_minus_one_non_standard(self, api):
        """fallback_index 0 yields FALLBACK; -1 declares text outside all fallbacks
        and yields NON_STANDARD.

        PRD §3.5: "A `fallback_index` of -1 yields severity `NON_STANDARD`. A valid
        index — 0 through the last configured position — yields `FALLBACK`, with
        index 0 denoting the most-preferred fallback."

        Design: Corner/calculations/deviation_severity_fallback_index_zero_is_fallback
        """
        ctx = setup_redlining_ctx(clause_specs=[
            {"clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
             "fallback_positions": ["fb0", "fb1"], "approver_role_required": "LEGAL_COUNSEL",
             "deviation_severity_cap": "MEDIUM"},
            {"clause_key": "B", "category": "OPERATIONAL", "standard_text": "b",
             "fallback_positions": ["fb0"], "approver_role_required": "LEGAL_COUNSEL",
             "deviation_severity_cap": "MEDIUM"},
        ])
        dev_fb = record_deviation(ctx, clause_index=0, proposed_text="fb0", fallback_index=0)
        dev_ns = record_deviation(ctx, clause_index=1, proposed_text="nonstd", fallback_index=-1)

        assert_deviation(dev_fb)
        assert_deviation(dev_ns)
        assert dev_fb["severity"] == "FALLBACK"
        assert dev_ns["severity"] == "NON_STANDARD"

    def test_fallback_index_beyond_configured_range_rejected(self, api):
        """fallback_index == len(fallback_positions) is out of range.

        PRD §3.5: "any non-negative index when the clause has no fallback positions
        configured, or an index greater than or equal to the number of positions, is
        rejected with `ERR_FALLBACK_INDEX_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/calculations/fallback_index_out_of_range_rejected
        """
        ctx = setup_redlining_ctx(clause_specs=[
            {"clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
             "fallback_positions": ["fb0", "fb1"], "approver_role_required": "LEGAL_COUNSEL",
             "deviation_severity_cap": "MEDIUM"},
        ])
        resp = api.create_deviation(
            ctx.negotiation["id"],
            {"clause_template_id": ctx.clauses[0]["id"], "proposed_text": "oob",
             "fallback_index": 2},
            ctx.headers[ctx.users["ca"]["id"]])
        validate_error(resp, ApiErrorId.ERR_FALLBACK_INDEX_OUT_OF_RANGE)
        assert resp.status_code == 422


class TestSupersedeInvariant:
    def test_second_deviation_on_same_clause_supersedes_prior(self, api):
        """Recording a second deviation for a clause whose prior deviation is OPEN
        supersedes the prior and conserves the counters at one.

        PRD §3.5: "if instead the prior deviation is in `OPEN` or `IN_REVIEW`, the new
        record supersedes it — the prior moves to `SUPERSEDED` with its `resolved_at`
        stamped, and the open and blocking counts decrement for the superseded record
        and increment for the new one, a net change of zero."

        Design: Difficulty/compensating_invariant/open_deviation_count_invariant_after_supersede
        """
        ctx = setup_redlining_ctx()
        dev1 = record_deviation(ctx, clause_index=0, proposed_text="v1", fallback_index=0)
        dev2 = record_deviation(ctx, clause_index=0, proposed_text="v2", fallback_index=0)

        dev1_after = get_deviation(ctx, dev1["id"])
        dev2_after = get_deviation(ctx, dev2["id"])
        assert dev1_after["status"] == "SUPERSEDED"
        assert dev2_after["status"] == "OPEN"

        negotiation = refresh_negotiation(ctx)
        assert negotiation["open_deviation_count"] == 1, (
            f"net change must be zero: 1 created + 1 superseded = 1 open, got "
            f"{negotiation['open_deviation_count']}")
        assert negotiation["blocking_deviation_count"] == 1

    def test_supersede_stamps_prior_resolution_and_keeps_approval_pending(self, api):
        """The superseded record carries a stamped resolved_at, and the approval
        dimension remains DEVIATIONS_PENDING while the replacement is OPEN.

        PRD §3.5: "the prior moves to `SUPERSEDED` with its `resolved_at` stamped, and
        the open and blocking counts decrement for the superseded record and increment
        for the new one, a net change of zero."

        Design: Difficulty/compensating_invariant/open_deviation_count_invariant_after_supersede
        """
        ctx = setup_redlining_ctx()
        dev1 = record_deviation(ctx, clause_index=0, proposed_text="v1", fallback_index=0)
        dev2 = record_deviation(ctx, clause_index=0, proposed_text="v2", fallback_index=0)

        dev1_after = get_deviation(ctx, dev1["id"])
        dev2_after = get_deviation(ctx, dev2["id"])
        assert dev1_after["resolved_at"] is not None, "superseded deviation must be stamped"
        assert dev2_after["id"] != dev1["id"]

        negotiation = refresh_negotiation(ctx)
        assert negotiation["approval_status"] == "DEVIATIONS_PENDING"


class TestImmediateConsistency:
    def test_first_deviation_flips_approval_status_immediately(self, api):
        """The very next read after the first deviation shows DEVIATIONS_PENDING
        and both counters at one — no lag.

        PRD §3.5: "The first deviation recorded on a negotiation flips the approval
        dimension from `NO_DEVIATIONS` to `DEVIATIONS_PENDING`; `open_deviation_count`
        and `blocking_deviation_count` each increment; and the negotiation's `version`
        increments."

        Design: Corner/consistency_model/approval_status_immediately_reflects_first_deviation
        """
        ctx = setup_redlining_ctx()
        assert ctx.negotiation["approval_status"] == "NO_DEVIATIONS"

        record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        negotiation = refresh_negotiation(ctx)
        assert_negotiation(negotiation)
        assert negotiation["approval_status"] == "DEVIATIONS_PENDING"
        assert negotiation["open_deviation_count"] == 1
        assert negotiation["blocking_deviation_count"] == 1


class TestDeviationTerminalLockdown:
    def test_approved_deviation_rejects_further_transitions(self, api):
        """An APPROVED deviation is terminal; begin-review on it is an invalid
        transition and the status is unchanged.

        PRD §3.6: "Review begins when an approver picks up an `OPEN` deviation." — a
        deviation in APPROVED permits no further transition, so the generic state
        guard (`ERR_INVALID_STATE_TRANSITION`) fires.

        Design: Corner/state_machines/deviation_terminal_approved_no_further_transitions
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        approve_deviation(ctx, dev)
        approved = get_deviation(ctx, dev["id"])
        assert approved["status"] == "APPROVED"

        # Call begin-review as the assigned approver so the assigned-approver
        # gate (PRD §3.6, evaluated first) passes and only the state guard can
        # fire on the terminal APPROVED deviation.
        approver = ctx.headers[approved["assigned_approver_id"]]
        resp = api.begin_review(ctx.negotiation["id"], dev["id"], approver)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert resp.status_code == 409
        assert get_deviation(ctx, dev["id"])["status"] == "APPROVED"


class TestRiskScoreCap:
    def test_risk_score_respects_per_clause_caps(self, api):
        """Identical NON_STANDARD inputs on two clauses yield different scores only
        through the cap: HIGH cap keeps the weighted sum, LOW cap clamps to 30.

        Setup arithmetic (PRD §3.5 components): NON_STANDARD=30, category RISK=20,
        tier VERY_HIGH (3,000,000 > 2,000,000 high threshold)=25, counterparty
        HIGH_RISK=15, round penalty (round 2)=2 → base 92; cap HIGH=100 keeps 92,
        cap LOW=30 clamps to 30.

        PRD §3.5: "The sum of these five components is then capped according to the
        clause's `deviation_severity_cap`: 30 when the cap is `LOW`, 60 when `MEDIUM`,
        and 100 when `HIGH`. The deviation's `risk_score` is the lesser of that cap
        and the computed sum".

        Design: Difficulty/combinatorial_formula/risk_score_weighted_sum_with_cap
        """
        ctx = setup_redlining_ctx(
            clause_specs=RISK_CLAUSES, value_cents=3_000_000,
            risk_tier="HIGH_RISK", ct_code="RESA")
        # Round 1: a FALLBACK deviation on clause A, approved so the round can close.
        dev_r1 = record_deviation(ctx, clause_index=0, proposed_text="fb1", fallback_index=0)
        approve_deviation(ctx, dev_r1)
        close_round(ctx, ctx.rounds[0]["id"])
        open_round(ctx, "Round 2")

        dev_high_cap = record_deviation(ctx, clause_index=0, proposed_text="nonstd",
                                        fallback_index=-1)
        dev_low_cap = record_deviation(ctx, clause_index=1, proposed_text="nonstd",
                                       fallback_index=-1)

        assert dev_high_cap["severity"] == "NON_STANDARD"
        assert dev_low_cap["severity"] == "NON_STANDARD"
        assert dev_high_cap["risk_score"] == 92, (
            f"HIGH cap keeps the sum: expected 92, got {dev_high_cap['risk_score']}")
        assert dev_low_cap["risk_score"] == 30, (
            f"LOW cap clamps to 30: expected 30, got {dev_low_cap['risk_score']}")

    def test_risk_score_weighted_components_for_fallback_first_round(self, api):
        """A first-round FALLBACK deviation on a RISK clause with a VERY_HIGH-value
        contract and HIGH_RISK counterparty scores 10+20+25+15+0 = 70.

        PRD §3.5: "Severity contributes 0 for `STANDARD`, 10 for `FALLBACK`, or 30 for
        `NON_STANDARD`. The clause's category contributes 0 for `OPERATIONAL`, 5 for
        `COMMERCIAL`, 15 for `REGULATORY`, or 20 for `RISK`. The contract's value tier
        contributes 0 for `LOW`, 5 for `MID`, 15 for `HIGH`, or 25 for `VERY_HIGH`. The
        counterparty's risk tier contributes 0 for `LOW`, 5 for `STANDARD`, or 15 for
        `HIGH_RISK`" and "the round penalty is the negotiation's `current_round_index`
        minus one, multiplied by 2, so a first-round deviation pays nothing".

        Design: Difficulty/combinatorial_formula/risk_score_weighted_sum_with_cap
        """
        ctx = setup_redlining_ctx(
            clause_specs=RISK_CLAUSES, value_cents=3_000_000,
            risk_tier="HIGH_RISK", ct_code="RESA")
        dev = record_deviation(ctx, clause_index=0, proposed_text="fb1", fallback_index=0)

        assert dev["severity"] == "FALLBACK"
        assert dev["risk_score"] == 70, (
            f"first-round FALLBACK on RISK clause at VERY_HIGH tier with HIGH_RISK "
            f"counterparty must score 70, got {dev['risk_score']}")
