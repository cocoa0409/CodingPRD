"""Settlement approval gating, dispute loop, payment, and grower rating
(PRD §3.7, §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_settlement,
    get_settlement_for_flock,
    get_success_data,
    lock_group,
    preview_settlement,
    setup_harvested_flock,
    setup_locked_settlement,
    setup_paid_settlement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]

# Single-member group fixture shape: 5000 head, 10000 lbs feed, 5000 lbs live
# weight, no loans. rank_pct 0 -> base 6 c/lb * 5000 = 30000; adj_fcr 1.6 ==
# group average -> bonus 0.25 c/lb = 1250; net 31250.
EXPECTED_SINGLE_MEMBER_NET = 31250


def _setup_open_group_with_provisional(api):
    """Harvested flock with a PROVISIONAL PENDING settlement in an OPEN
    group."""
    ctx = setup_harvested_flock(grower_code="G-X1", full_name="Cross Grower 1",
                                contract_no="C-X1", group_code="WK-43",
                                week_ending_date="2026-11-28", flock_no="F-X1",
                                set_clock_to="2026-08-01T00:00:00Z",
                                crew_code="CREW-X1", weight_ticket_no="WT-X1")
    ctx["settlement"] = preview_settlement(ctx["flock"]["id"])
    return ctx


class TestSettlementApproveDependsOnGroupLocked:
    def test_approve_rejected_while_group_open(self, api, analyst_headers):
        """PRD §3.10: "Two preconditions guard it, and their violation surfaces
        as `ERR_GROUP_NOT_LOCKED` (HTTP 409): the parent group must be in
        `LOCKED` status, and the settlement's `variant` must be `FINAL`."

        Design: Difficulty/cross_entity_state_dependency/settlement_approve_depends_on_group_locked
        """
        ctx = _setup_open_group_with_provisional(api)
        settlement = ctx["settlement"]
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["status"] == "PENDING"

        resp = api.approve_settlement(settlement["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_LOCKED)

    def test_approve_succeeds_after_group_locked(self, api, analyst_headers):
        """PRD §3.10: "Approving a settlement moves it `PENDING` → `APPROVED`
        and fires the domain's largest cascade: the flock transitions
        `HARVESTED` → `SETTLED` and its `performance_score` is computed; the
        loan repayment waterfall of §3.9 runs against the grower's `ISSUED`
        loans and the grower's `loan_outstanding_cents` is recomputed; and the
        grower's `performance_rating` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/settlement_approve_depends_on_group_locked
        """
        ctx = _setup_open_group_with_provisional(api)
        settlement = ctx["settlement"]
        validate_error(api.approve_settlement(settlement["id"], analyst_headers),
                       ApiErrorId.ERR_GROUP_NOT_LOCKED)

        lock_group(ctx["group"]["id"])
        approved = validate_success(
            api.approve_settlement(settlement["id"], analyst_headers))
        assert_settlement(approved)
        assert approved["status"] == "APPROVED"
        assert approved["variant"] == "FINAL"

        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "SETTLED"


class TestSettlementDisputeRevisionLoop:
    def test_dispute_then_resolve_returns_to_pending(self, api):
        """PRD §3.10: "A `Grower` may dispute a `PENDING` settlement on their
        own flock — the acting grower's identity must match the grower who
        owns the flock's house — moving it `PENDING` → `DISPUTED`. A
        `SettlementAnalyst` resolves the dispute, returning it `DISPUTED` →
        `PENDING` and recomputing the amounts per the full settlement
        calculation; this revision loop can run as often as needed before
        approval."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_revision_loop
        """
        ctx = setup_locked_settlement(
            grower_code="G-D", full_name="Dispute Grower", contract_no="C-D",
            group_code="WK-35", week_ending_date="2026-10-03", flock_no="F-D",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-D",
            weight_ticket_no="WT-D1")
        settlement = ctx["settlement"]
        assert settlement["status"] == "PENDING"

        disputed = validate_success(
            api.dispute_settlement(settlement["id"], ctx["grower_headers"]))
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(
            api.resolve_dispute(settlement["id"], ANALYST))
        assert resolved["status"] == "PENDING", "the revision cycle completes"

    def test_resolve_dispute_recomputes_amounts(self, api):
        """PRD §3.10: "A `SettlementAnalyst` resolves the dispute, returning it
        `DISPUTED` → `PENDING` and recomputing the amounts per the full
        settlement calculation; this revision loop can run as often as needed
        before approval."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_revision_loop
        """
        ctx = setup_locked_settlement(
            grower_code="G-D", full_name="Dispute Grower", contract_no="C-D",
            group_code="WK-35", week_ending_date="2026-10-03", flock_no="F-D",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-D",
            weight_ticket_no="WT-D1")
        settlement = ctx["settlement"]
        get_success_data(api.dispute_settlement(settlement["id"],
                                                ctx["grower_headers"]))

        resolved = validate_success(api.resolve_dispute(settlement["id"],
                                                        ANALYST))
        assert_settlement(resolved)
        # Single-member group: rank_pct 0 -> base 30000; adj_fcr 1.6 == group
        # average -> bonus 0.25 c/lb = 1250; no condemnation, no loans.
        assert resolved["base_amount_cents"] == 30000
        assert resolved["fcr_bonus_cents"] == 1250
        assert resolved["condemnation_deduction_cents"] == 0
        assert resolved["loan_repayment_cents"] == 0
        assert resolved["net_amount_cents"] == EXPECTED_SINGLE_MEMBER_NET


class TestSettlementTerminalPaidLockdown:
    def _setup_paid(self, api):
        return setup_paid_settlement(
            grower_code="G-S3", full_name="State Three", contract_no="C-S3",
            group_code="WK-S3", flock_no="F-S3",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-S3",
            weight_ticket_no="WT-S3")

    def test_dispute_from_paid_rejected(self, api):
        """PRD §3.10: "Finally, an `APPROVED` settlement is paid by a
        `SettlementAnalyst`, moving it `APPROVED` → `PAID`; payment freezes
        `net_amount_cents`, and `PAID` is terminal."
        PRD §2.8: "5. Transition legality — the target entity is in a
        from-state of the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/settlement_terminal_paid_lockdown
        """
        ctx = self._setup_paid(api)
        settlement = ctx["settlement"]
        assert settlement["status"] == "PAID"
        frozen_net = settlement["net_amount_cents"]

        resp = api.dispute_settlement(settlement["id"], ctx["grower_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_settlement_for_flock(ctx["flock"]["id"])[0]
        assert after["status"] == "PAID"
        assert after["net_amount_cents"] == frozen_net

    def test_pay_and_approve_from_paid_rejected(self, api, analyst_headers):
        """PRD §3.10: "Finally, an `APPROVED` settlement is paid by a
        `SettlementAnalyst`, moving it `APPROVED` → `PAID`; payment freezes
        `net_amount_cents`, and `PAID` is terminal."
        PRD §2.8: "5. Transition legality — the target entity is in a
        from-state of the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/settlement_terminal_paid_lockdown
        """
        ctx = self._setup_paid(api)
        settlement = ctx["settlement"]

        validate_error(api.pay_settlement(settlement["id"], analyst_headers),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.approve_settlement(settlement["id"], analyst_headers),
                       ApiErrorId.ERR_INVALID_STATE)

        after = get_settlement_for_flock(ctx["flock"]["id"])[0]
        assert after["status"] == "PAID"
        assert after["net_amount_cents"] == EXPECTED_SINGLE_MEMBER_NET


class TestGrowerPerformanceRating:
    def test_rating_null_then_equals_first_settled_score(self, api,
                                                         analyst_headers):
        """PRD §3.10: "The performance rating is a rolling form guide: the
        mean of `performance_score` across the grower's flocks in `SETTLED`
        status, taking the three most recent by `placed_date` — with ties
        broken by the later settled date, then by creation order — rounded
        half-up to 4 decimal places. A grower with no settled flocks has a
        null rating."
        PRD §3.7: "The score starts from 100 and applies three adjustments".

        Design: Corner/calculations/performance_rating_rolling_window_of_three
        """
        ctx = setup_locked_settlement(
            grower_code="G-RT", full_name="Rating Grower", contract_no="C-RT",
            group_code="WK-RT", flock_no="F-RT",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-RT",
            weight_ticket_no="WT-RT")
        before = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        # The grower has settled nothing yet in this fixture; rating is null.
        assert ctx["flock"]["status"] == "HARVESTED"
        fresh = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert fresh["performance_rating"] is None

        get_success_data(api.approve_settlement(ctx["settlement"]["id"],
                                                analyst_headers))

        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "SETTLED"
        # Single-member group: every adjustment delta is zero.
        assert flock["performance_score"] == pytest.approx(100.0, abs=1e-9)

        after = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert after["performance_rating"] == pytest.approx(100.0, abs=1e-9)
        assert after["performance_rating"] == pytest.approx(
            flock["performance_score"], abs=1e-9), \
            "with exactly one settled flock the rating equals that flock's score"
        assert before["performance_rating"] is None
