"""Hazard-pay negotiation: dual payout variants, bump bounds, per-line rollup
rounding, the pinned budget-reserve evaluation order, committed-pay invariant,
negotiation caps, and ownership (PRD §2.10, §3.1, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    agree_adjustment,
    counter_adjustment,
    create_open_adjustment,
    create_pay_adjustment_payload,
    create_production,
    create_qualified_performer,
    create_sequence,
    get_adjustment,
    get_production,
    make_performer_headers,
    reshoot_and_reready,
    attempt_take,
    complete_take,
    setup_ready_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_negotiable(api, budget=10000000, risk_category="MEDIUM", union_status="NON_UNION",
                      name="Neg", day_rate=150000):
    """SETUP production + DRAFT sequence + QUALIFIED performer (negotiation is
    permitted in SETUP posture, PRD §2.7 tier 5)."""
    prod = create_production(name=f"{name} Prod", budget=budget)
    seq = create_sequence(prod["id"], name=f"{name} Seq", hazard_class="FIGHT", risk_category=risk_category)
    perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT", day_rate=day_rate,
                                         union_status=union_status)
    return prod, seq, perf


class TestProvisionalVsFinalSettlement:
    """Pay-domain dual variant: provisional estimate at creation vs settled
    amounts at agree/execution (PRD §3.7, §3.8)."""

    def _setup_agreed_adjustment(self, api):
        ctx = setup_ready_sequence(name="DV Pay", hazard_class="FIGHT", risk_category="LOW")
        adj = create_open_adjustment(
            ctx["production"]["id"], ctx["sequence"]["id"], ctx["performer"]["id"],
            base_amount_cents=200000, requested_pct=0.10, side="PERFORMER",
        )
        return ctx, adj

    def test_provisional_estimate_assumes_one_planned_take(self, api):
        """PRD §3.7: "At creation the system also stores
        `provisional_estimate_cents`: the base, plus the bump at `requested_pct`
        rounded half up to whole cents, plus a take bonus of 50,000 cents for
        exactly one planned take." and "On success, `final_amount_cents` is
        computed as the base plus the bump at `current_pct` rounded half up,
        `payable_amount_cents` is initialized equal to `final_amount_cents`
        because no takes have completed yet"

        Design: Difficulty/dual_variant_calc/dv_pay_provisional_vs_final_settlement
        """
        ctx, adj = self._setup_agreed_adjustment(api)
        assert adj["provisional_estimate_cents"] == 270000, "200000 + 20000 bump + 50000 x 1 planned take"
        agreed = agree_adjustment(adj["id"], ctx["performer"]["id"], side="COORDINATOR")
        assert agreed["status"] == "AGREED"
        assert agreed["final_amount_cents"] == 220000, "200000 + round_half_up(200000 x 0.10)"
        assert agreed["payable_amount_cents"] == 220000, "zero completed takes at agree time"

    def test_payable_uses_actual_completed_take_count(self, api):
        """PRD §3.7: "The provisional figure assumes one take and the opening
        percentage; the settled figures diverge once negotiation moves the
        percentage and more takes complete — a base of 200,000 cents at 0.40
        estimates provisionally at 330,000 cents, yet pays 380,000 after two
        completed takes."
        PRD §3.8: "And every `AGREED` pay adjustment of the sequence re-prices:
        `payable_amount_cents` becomes `final_amount_cents` plus 50,000 cents
        multiplied by the count of the sequence's `COMPLETED` executions — the
        actual completed take count, not the planned one."

        Design: Difficulty/dual_variant_calc/dv_pay_provisional_vs_final_settlement
        """
        ctx, adj = self._setup_agreed_adjustment(api)
        agree_adjustment(adj["id"], ctx["performer"]["id"], side="COORDINATOR")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        # Take 1 completes while the sequence is READY (first completion ->
        # EXECUTED); the reshoot loop then legitimately returns the sequence to
        # READY (fresh design revision, fresh meeting) so take 2 can run.
        take1 = attempt_take(prod_id, seq_id, 1)
        complete_take(take1["id"])
        reshoot_and_reready(prod_id, seq_id)
        take2 = attempt_take(prod_id, seq_id, 2)
        complete_take(take2["id"])
        settled = get_adjustment(adj["id"])
        assert settled["payable_amount_cents"] == 320000, "220000 + 50000 x 2 completed takes"
        assert settled["provisional_estimate_cents"] == 270000, (
            "identical base/pct data: the provisional variant (270000) diverges from the "
            "actual-takes settlement (320000) once more than one take completes"
        )


class TestBumpBounds:
    """SAG_AFTRA floor via max(10% of base, 15000) against the MEDIUM tiered
    cap of 35% (PRD §3.7)."""

    def _setup_sag_aftra(self, api):
        return _setup_negotiable(api, risk_category="MEDIUM", union_status="SAG_AFTRA",
                                 name="Bounds", day_rate=100000)

    def test_bump_below_union_floor_rejected(self, api):
        """PRD §3.7: "Every proposed or countered percentage is bounds-checked
        before it lands — at creation against `requested_pct` and at each
        counter against `counter_pct` — and a violation is rejected with
        `ERR_BUMP_OUT_OF_RANGE`." and "The floor is zero for a `NON_UNION`
        performer; for `SAG_AFTRA` it is the larger of ten percent of the base
        (rounded half up) and a union floor of 15,000 cents."

        Design: Difficulty/combinatorial_formula/cf_bump_bounds_tiered_floor_cap
        """
        prod, seq, perf = self._setup_sag_aftra(api)
        payload = create_pay_adjustment_payload(prod["id"], seq["id"], perf["id"],
                                                base_amount_cents=100000, requested_pct=0.10)
        resp = api.create_pay_adjustment(payload, make_performer_headers(perf["id"]))
        validate_error(resp, ApiErrorId.ERR_BUMP_OUT_OF_RANGE)
        # bump 10000 < floor max(10000, 15000) = 15000

    def test_bump_within_floor_and_cap_accepted(self, api):
        """PRD §3.7: "The cap is the base multiplied by the category cap —
        fifteen percent for `LOW`, thirty-five percent for `MEDIUM`, sixty
        percent for `HIGH`, one hundred percent for `CRITICAL` — rounded half up
        to whole cents" and "The bump is valid exactly when it falls at or
        between the floor and the cap, inclusively."

        Design: Difficulty/combinatorial_formula/cf_bump_bounds_tiered_floor_cap
        """
        prod, seq, perf = self._setup_sag_aftra(api)
        payload = create_pay_adjustment_payload(prod["id"], seq["id"], perf["id"],
                                                base_amount_cents=100000, requested_pct=0.20)
        adj = validate_success(api.create_pay_adjustment(payload, make_performer_headers(perf["id"])), 201)
        assert adj["provisional_estimate_cents"] == 170000, "100000 + 20000 bump + 50000 planned take"
        assert adj["status"] == "PROPOSED"


class TestRollupRoundingOrder:
    """Per-line round-half-up THEN sum: two lines of 133507 commit 267014
    (PRD §3.1, §3.7)."""

    def _setup_two_agreed_lines(self, api):
        prod = create_production(name="Rollup Prod", budget=10000000)
        seq = create_sequence(prod["id"], name="Rollup Seq", hazard_class="FIGHT", risk_category="MEDIUM")
        perf1, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Ann", last_name="One",
                                              day_rate=100005)
        perf2, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Bob", last_name="Two",
                                              day_rate=100005)
        adj1 = create_open_adjustment(prod["id"], seq["id"], perf1["id"],
                                      base_amount_cents=100005, requested_pct=0.335, side="PERFORMER")
        adj2 = create_open_adjustment(prod["id"], seq["id"], perf2["id"],
                                      base_amount_cents=100005, requested_pct=0.335, side="PERFORMER")
        return prod, adj1, adj2, perf1, perf2

    def test_line_rounded_half_up(self, api):
        """PRD §3.7: "On success, `final_amount_cents` is computed as the base
        plus the bump at `current_pct` rounded half up"
        PRD §2.9: "Every monetary computation rounds half up to whole cents, and
        rounding is applied per line before any summation"

        Design: Difficulty/combinatorial_formula/cf_rollup_per_line_rounding_order
        """
        _, adj1, _, perf1, _ = self._setup_two_agreed_lines(api)
        agreed = agree_adjustment(adj1["id"], perf1["id"], side="COORDINATOR")
        assert agreed["final_amount_cents"] == 133507, (
            "100005 + round_half_up(100005 x 0.335 = 33501.675) = 100005 + 33502"
        )

    def test_committed_pay_sums_rounded_lines(self, api):
        """PRD §3.1: "The rounding order is pinned — every line is rounded first
        and only then summed, never the reverse — so two lines of 133,507 cents
        each sum to 267,014 where a sum-then-round implementation would yield
        267,013."
        PRD §3.7: "the production's `committed_pay_cents` grows by
        `final_amount_cents` — invariant I1."

        Design: Difficulty/combinatorial_formula/cf_rollup_per_line_rounding_order
        """
        prod, adj1, adj2, perf1, perf2 = self._setup_two_agreed_lines(api)
        agree_adjustment(adj1["id"], perf1["id"], side="COORDINATOR")
        agree_adjustment(adj2["id"], perf2["id"], side="COORDINATOR")
        committed = get_production(prod["id"])["committed_pay_cents"]
        assert committed == 267014, "per-line rounding then sum; sum-then-round would give 267013"


class TestBudgetReserveEvaluationOrder:
    """The reserve is computed on the PRE-agreement committed snapshot
    (PRD §3.7)."""

    def _setup_budget_pair(self, api):
        prod = create_production(name="Budget Prod", budget=1000000)
        seq = create_sequence(prod["id"], name="Budget Seq", hazard_class="FIGHT", risk_category="MEDIUM")
        perf1, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Cal", last_name="Tre",
                                              day_rate=900000)
        perf2, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Dee", last_name="Qua",
                                              day_rate=90001)
        adj1 = create_open_adjustment(prod["id"], seq["id"], perf1["id"],
                                      base_amount_cents=900000, requested_pct=0.0, side="PERFORMER")
        adj2 = create_open_adjustment(prod["id"], seq["id"], perf2["id"],
                                      base_amount_cents=90001, requested_pct=0.0, side="PERFORMER")
        return prod, adj1, adj2, perf1, perf2

    def test_first_agree_at_exact_available_passes(self, api):
        """PRD §3.7: "First, the production's `committed_pay_cents` is read as
        it stands before this agreement. Second, the reserve is computed as ten
        percent of the remaining headroom — `total_budget_cents` minus that
        pre-agreement committed pay — rounded half up to whole cents. Third, the
        available amount is the budget minus the pre-agreement committed pay
        minus the reserve. Fourth, the new line is the adjustment's
        `base_amount_cents` multiplied by one plus `current_pct`, rounded half
        up to whole cents. The new line must be at most the available amount —
        exact equality passes — else the agreement is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/cf_budget_reserve_evaluation_order
        """
        prod, adj1, _, perf1, _ = self._setup_budget_pair(api)
        agreed = agree_adjustment(adj1["id"], perf1["id"], side="COORDINATOR")
        assert agreed["status"] == "AGREED", "line 900000 <= available 900000 passes at equality"
        assert get_production(prod["id"])["committed_pay_cents"] == 900000

    def test_second_agree_rejected_and_commits_nothing(self, api):
        """PRD §3.7: "The new line must be at most the available amount — exact
        equality passes — else the agreement is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 402)." — with the reserve computed on the
        pre-request committed pay of 900000, the available headroom is exactly
        90000, so a 90001 line is rejected and commits nothing.

        Design: Difficulty/combinatorial_formula/cf_budget_reserve_evaluation_order
        """
        prod, adj1, adj2, perf1, perf2 = self._setup_budget_pair(api)
        agree_adjustment(adj1["id"], perf1["id"], side="COORDINATOR")
        resp = api.agree_pay_adjustment(adj2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert get_production(prod["id"])["committed_pay_cents"] == 900000, (
            "the rejected agreement commits nothing"
        )


class TestBudgetEqualityBoundary:
    def _setup(self, api):
        prod = create_production(name="Eq Budget Prod", budget=1000000)
        seq = create_sequence(prod["id"], name="Eq Seq", hazard_class="FIGHT", risk_category="MEDIUM")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT", day_rate=900000)
        adj = create_open_adjustment(prod["id"], seq["id"], perf["id"],
                                     base_amount_cents=900000, requested_pct=0.0, side="PERFORMER")
        return prod, adj, perf

    def test_agree_at_exact_available_boundary(self, api):
        """PRD §3.7: "The new line must be at most the available amount — exact
        equality passes — else the agreement is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/bp_budget_equality_at_agree
        """
        _, adj, perf = self._setup(api)
        agreed = agree_adjustment(adj["id"], perf["id"], side="COORDINATOR")
        assert agreed["status"] == "AGREED"
        assert agreed["final_amount_cents"] == 900000

    def test_agree_at_equality_updates_committed_pay(self, api):
        """PRD §3.7: "On success, `final_amount_cents` is computed as the base
        plus the bump at `current_pct` rounded half up, `payable_amount_cents`
        is initialized equal to `final_amount_cents` because no takes have
        completed yet, and the production's `committed_pay_cents` grows by
        `final_amount_cents` — invariant I1."

        Design: Difficulty/boundary_precision_check/bp_budget_equality_at_agree
        """
        prod, adj, perf = self._setup(api)
        agree_adjustment(adj["id"], perf["id"], side="COORDINATOR")
        prod_read = get_production(prod["id"])
        assert prod_read["committed_pay_cents"] == 900000


class TestCommittedPayConservation:
    """Money invariant I1: agree commits, sequence cancellation voids and
    compensates (PRD §3.7)."""

    def _setup(self, api):
        prod = create_production(name="Money Prod", budget=10000000)
        seq = create_sequence(prod["id"], name="Money Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT", day_rate=200000)
        adj = create_open_adjustment(prod["id"], seq["id"], perf["id"],
                                     base_amount_cents=200000, requested_pct=0.10, side="PERFORMER")
        return prod, seq, perf, adj

    def test_agree_commits_final_amount(self, api):
        """PRD §3.7: "That invariant holds at all times: a production's
        `committed_pay_cents` equals the sum of `final_amount_cents` over
        exactly its `AGREED` pay adjustments."

        Design: Difficulty/compensating_invariant/ci_committed_pay_conservation
        """
        prod, _, perf, adj = self._setup(api)
        agreed = agree_adjustment(adj["id"], perf["id"], side="COORDINATOR")
        assert agreed["final_amount_cents"] == 220000
        assert get_production(prod["id"])["committed_pay_cents"] == 220000

    def test_sequence_cancel_voids_and_compensates(self, api):
        """PRD §3.7: "Sequence cancellation withdraws open adjustments
        system-side and voids agreed ones: the move `AGREED → VOIDED` subtracts
        `final_amount_cents` from the production's `committed_pay_cents`, the
        compensating action that keeps invariant I1 exact."

        Design: Difficulty/compensating_invariant/ci_committed_pay_conservation
        """
        prod, seq, perf, adj = self._setup(api)
        agree_adjustment(adj["id"], perf["id"], side="COORDINATOR")
        assert get_production(prod["id"])["committed_pay_cents"] == 220000
        validate_success(api.cancel_sequence(seq["id"], COORD, {"reason": "scene cut"}))
        adj_read = get_adjustment(adj["id"])
        assert adj_read["status"] == "VOIDED"
        assert get_production(prod["id"])["committed_pay_cents"] == 0, (
            "forward (+220000) and compensating (-220000) actions leave the total unchanged"
        )


class TestNegotiationRoundCap:
    def test_seventh_counter_exhausts_negotiation(self, api):
        """PRD §3.7: "The negotiation allows at most six rounds: a counter
        attempted while `round_count` is already 6 is rejected with
        `ERR_NEGOTIATION_EXHAUSTED`, and that failed attempt itself exhausts the
        negotiation, moving the adjustment to `EXPIRED` with no pay committed."

        Design: Corner/state_machines/sm_negotiation_round_cap_exhausted
        """
        prod, seq, perf = _setup_negotiable(api, risk_category="MEDIUM", name="Neg", day_rate=100000)
        adj = create_open_adjustment(prod["id"], seq["id"], perf["id"],
                                     base_amount_cents=100000, requested_pct=0.20, side="PERFORMER")
        sides = ["COORDINATOR", "PERFORMER"] * 3
        pcts = [0.21, 0.22, 0.23, 0.24, 0.25, 0.26]
        last = None
        for side, pct in zip(sides, pcts):
            last = counter_adjustment(adj["id"], pct, perf["id"], side=side)
        assert last["round_count"] == 6
        assert last["status"] == "COUNTERED"
        resp = api.counter_pay_adjustment(adj["id"], {"counter_pct": 0.27}, COORD)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)
        final = get_adjustment(adj["id"])
        assert final["status"] == "EXPIRED", "the failed counter attempt terminates the negotiation"
        assert final["round_count"] == 6, "the rejected attempt does not change round_count"


class TestOneOpenNegotiation:
    def test_second_open_negotiation_rejected(self, api):
        """PRD §3.7: "at most one negotiation may be open — `PROPOSED` or
        `COUNTERED` — per sequence-and-performer pair
        (`ERR_NEGOTIATION_ALREADY_OPEN`)."

        Design: Corner/errors/err_negotiation_already_open_rejected
        """
        prod, seq, perf = _setup_negotiable(api, risk_category="MEDIUM", name="Neg2", day_rate=100000)
        first = create_open_adjustment(prod["id"], seq["id"], perf["id"],
                                       base_amount_cents=100000, requested_pct=0.20, side="PERFORMER")
        assert first["status"] == "PROPOSED"
        payload = create_pay_adjustment_payload(prod["id"], seq["id"], perf["id"],
                                                adjustment_type="STUNT_DOUBLE", base_amount_cents=80000,
                                                requested_pct=0.10)
        resp = api.create_pay_adjustment(payload, make_performer_headers(perf["id"]))
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ALREADY_OPEN)


class TestImmediateConsistency:
    def test_create_response_carries_computed_fields(self, api):
        """PRD §3.7: "At creation the system also stores
        `provisional_estimate_cents`: the base, plus the bump at `requested_pct`
        rounded half up to whole cents, plus a take bonus of 50,000 cents for
        exactly one planned take." and "The new adjustment starts `PROPOSED`
        with `round_count` zero, `current_pct` equal to `requested_pct`,
        `proposer_by` and `last_offer_by` both recording which side opened
        (`PERFORMER` or `COORDINATOR`)"

        Design: Corner/consistency_model/cons_immediate_computed_on_create
        """
        prod, seq, perf = _setup_negotiable(api, risk_category="MEDIUM", name="Cons", day_rate=100000)
        payload = create_pay_adjustment_payload(prod["id"], seq["id"], perf["id"],
                                                base_amount_cents=100000, requested_pct=0.20)
        data = validate_success(api.create_pay_adjustment(payload, make_performer_headers(perf["id"])), 201)
        assert data["provisional_estimate_cents"] == 170000, "100000 + 20000 + 50000 x 1 planned take"
        assert data["status"] == "PROPOSED"
        assert data["last_offer_by"] == "PERFORMER"
        assert data["round_count"] == 0
        assert data["current_pct"] == 0.20


class TestReferentialBeatsFiscal:
    def _setup(self, api):
        p1 = create_production(name="P1", budget=10000000)
        p2 = create_production(name="P2", budget=10000000)
        seq = create_sequence(p1["id"], name="P1 Seq", hazard_class="FIGHT", risk_category="MEDIUM")
        # Performer lives in P2 (QUALIFIED there via a valid certification).
        perf, _ = create_qualified_performer(p2["id"], discipline="FIGHT", first_name="Hal", last_name="Eig",
                                             day_rate=100000)
        return p1, p2, seq, perf

    def test_cross_production_reported_for_pay_create(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." with cross-production referential
        integrity at tier 11 (`ERR_CROSS_PRODUCTION_REFERENCE`) ahead of the
        hazard-bump bounds check at tier 13 (`ERR_BUMP_OUT_OF_RANGE`).
        PRD §2.10: "every foreign key in a payload must reference an entity
        belonging to the same production as the primary reference"

        Design: Difficulty/priority_pair_validation_conflict/pp_referential_vs_fiscal_on_pay_create
        """
        p1, _, seq, perf = self._setup(api)
        # requested_pct 9.99 is also wildly outside the MEDIUM cap — the
        # referential violation must be the one reported.
        payload = create_pay_adjustment_payload(p1["id"], seq["id"], perf["id"],
                                                base_amount_cents=100000, requested_pct=9.99)
        resp = api.create_pay_adjustment(payload, make_performer_headers(perf["id"]))
        validate_error(resp, ApiErrorId.ERR_CROSS_PRODUCTION_REFERENCE)

    def test_cross_production_first_tier_creates_no_adjustment(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." — the tier-11 referential rejection
        (`ERR_CROSS_PRODUCTION_REFERENCE`) pre-empts the tier-13 bounds check,
        so no adjustment is recorded for either production.

        Design: Difficulty/priority_pair_validation_conflict/pp_referential_vs_fiscal_on_pay_create
        """
        p1, p2, seq, perf = self._setup(api)
        payload = create_pay_adjustment_payload(p1["id"], seq["id"], perf["id"],
                                                base_amount_cents=100000, requested_pct=9.99)
        validate_error(api.create_pay_adjustment(payload, make_performer_headers(perf["id"])),
                       ApiErrorId.ERR_CROSS_PRODUCTION_REFERENCE)
        _, meta1 = validate_paginated(api.list_pay_adjustments(COORD, params={"production_id": p1["id"]}))
        _, meta2 = validate_paginated(api.list_pay_adjustments(COORD, params={"production_id": p2["id"]}))
        assert meta1["total_count"] == 0 and meta2["total_count"] == 0
