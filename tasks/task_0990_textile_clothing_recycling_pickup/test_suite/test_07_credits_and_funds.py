"""Diversion credits and the sponsor-fund ledger: dual-variant valuation,
fund-capped sponsor bonus, dispute/re-finalize branch, settle side effects,
charity split rounding order, fund gates and invariants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_resident_headers, make_sponsor_manager_headers,
    make_charity_admin_headers,
    new_zone, new_resident, new_delivered_kit, new_pickup, route_pickup,
    collect_pickup, certify_ticket, new_credit, finalize_credit, settle_credit,
    void_credit, new_fund, new_charity, set_zone_splits,
    read_credit, read_fund, read_pickup, read_resident, read_charity, read_zone,
    ctx_collected, ctx_certified, ctx_credit, ctx_finalized, ctx_settled,
    assert_fund_ledger_invariant,
    create_sponsor_fund_payload, topup_payload,
)

OP = TEST_USERS["zone_operator_headers"]


class TestDualVariantCreditProjection:
    def test_provisional_projection_at_collection(self, api):
        """PRD §3.5: "The provisional variant applies the material rate for an
        assumed `RECYCLE` grade to the provisional field weight: it takes
        `provisional_weight_kg`, multiplies by the `RECYCLE` rate of 45 cents per
        kilogram, and rounds half-up to whole cents to produce the base."
        PRD §3.5: "A bulk bonus of 500 cents is added when the provisional weight
        is at least 20.0 kilograms. The sponsor bonus, uncapped at this stage, is
        ten percent of the post-contamination value rounded half-up."

        Design: Difficulty/dual_variant_calc/credit_projection_provisional_vs_final
        """
        ctx = ctx_collected(zone_name="Zone DV1", resident_name="Rita Ray",
                            resident_email="rita@x.com", provisional_weight_kg=40.0)
        # 40.0 * 45 = 1800 base + 500 bulk + 180 uncapped bonus = 2480
        assert ctx["ticket"]["projected_credit_cents"] == 2480, (
            f"provisional variant: expected 2480, got {ctx['ticket']['projected_credit_cents']}"
        )

    def test_final_variant_projection_at_credit_creation(self, api):
        """PRD §3.7: "Its `projected_cents` is computed by the final-variant
        formula below but with the sponsor bonus uncapped — that is, base plus
        contamination adjustment plus bulk bonus plus the uncapped ten-percent
        sponsor bonus."
        PRD §2.6: "The per-kilogram material rate is keyed by the certified
        `grade`: `RESALE` is valued at 120 cents per kilogram, `RECYCLE` at 45
        cents per kilogram, and `FIBER` at 20 cents per kilogram."

        Design: Difficulty/dual_variant_calc/credit_projection_provisional_vs_final
        """
        ctx = ctx_credit(zone_name="Zone DV1", resident_name="Rita Ray",
                         resident_email="rita@x.com", provisional_weight_kg=40.0,
                         certified_weight_kg=12.5, grade="RESALE")
        # ticket projection: 40.0*45 + 500 + 180 = 2480
        assert ctx["ticket"]["projected_credit_cents"] == 2480
        # credit projection: 12.5*120 = 1500 base + 0 bulk (12.5 < 20.0) + 150 bonus = 1650
        assert ctx["credit"]["projected_cents"] == 1650, (
            f"final variant: expected 1650, got {ctx['credit']['projected_cents']}"
        )
        assert ctx["ticket"]["projected_credit_cents"] != ctx["credit"]["projected_cents"], (
            "the two variants must diverge for the identical load"
        )


class TestFundCappedSponsorBonus:
    def test_projected_uncapped_bonus(self, api):
        """PRD §3.7: "Its `projected_cents` is computed by the final-variant
        formula below but with the sponsor bonus uncapped — that is, base plus
        contamination adjustment plus bulk bonus plus the uncapped ten-percent
        sponsor bonus."

        Design: Difficulty/combinatorial_formula/credit_value_fund_capped_sponsor_bonus
        """
        ctx = ctx_credit(zone_name="Zone CF1", resident_name="Amy Ada",
                         resident_email="amy@x.com", fund_cents=2400,
                         certified_weight_kg=40.0, grade="RECYCLE")
        # 40.0*45 = 1800 base + 500 bulk + 180 uncapped bonus = 2480
        assert ctx["credit"]["projected_cents"] == 2480

    def test_finalize_caps_bonus_by_fund_headroom(self, api):
        """PRD §3.7: "Fifth, the headroom available for the bonus is computed as
        the greater of zero and the fund's `available_cents` minus the
        post-contamination value minus the bulk bonus, and the final sponsor bonus
        is the smaller of the uncapped bonus and that headroom. The credit's
        `gross_cents` is the sum of the post-contamination value, the bulk bonus,
        and the capped sponsor bonus."
        PRD §2.8: "Finalizing a credit places a hold: `held_cents` increases by
        the credit's `gross_cents` and `available_cents` falls by the same amount."

        Design: Difficulty/combinatorial_formula/credit_value_fund_capped_sponsor_bonus
        """
        ctx = ctx_credit(zone_name="Zone CF1", resident_name="Amy Ada",
                         resident_email="amy@x.com", fund_cents=2400,
                         certified_weight_kg=40.0, grade="RECYCLE")
        assert ctx["credit"]["projected_cents"] == 2480

        credit = finalize_credit(ctx["credit"]["id"])
        # headroom = max(0, 2400 - 1800 - 500) = 100; bonus = min(180, 100) = 100
        # gross = 1800 + 500 + 100 = 2400
        assert credit["gross_cents"] == 2400, (
            f"capped sponsor bonus: expected gross 2400, got {credit['gross_cents']}"
        )
        assert credit["has_hold"] is True

        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 2400
        assert fund["available_cents"] == 0
        assert_fund_ledger_invariant(fund)


class TestCharitySplitRoundingOrder:
    def _setup(self):
        ctx = ctx_finalized(zone_name="Zone CF2", resident_name="Bob Bay",
                            resident_email="bob@x.com", fund_cents=100000,
                            splits=[("ClothesAid", 33), ("FiberFund", 33)],
                            bags_claimed=4, provisional_weight_kg=12.34,
                            certified_weight_kg=12.34, grade="RESALE")
        # base round_half_up(12.34*120) = 1481; bonus round_half_up(148.1) = 148; gross 1629
        assert ctx["credit"]["gross_cents"] == 1629
        return ctx

    def test_per_line_floor_then_remainder_to_resident(self, api):
        """PRD §3.7: "For each line in the zone's `charity_splits`, iterated in
        order of the charity's `created_at` ascending, the line's `amount_cents`
        is the floor of the credit's `gross_cents` multiplied by the line's `pct`
        divided by 100. The remainder is the `gross_cents` minus the sum of all
        line amounts. When the credit is pickup-sourced, that remainder is the
        `resident_share_cents` — the resident absorbs the rounding slack."

        Design: Difficulty/combinatorial_formula/charity_split_per_line_floor_remainder
        """
        ctx = self._setup()
        credit = settle_credit(ctx["credit"]["id"])
        ch1, ch2 = ctx["charities"]
        assert credit["charity_allocations"] == [
            {"charity_id": ch1["id"], "pct": 33, "amount_cents": 537},
            {"charity_id": ch2["id"], "pct": 33, "amount_cents": 537},
        ], f"per-line floor of 1629*0.33 = 537 each: {credit['charity_allocations']}"
        assert credit["resident_share_cents"] == 555, (
            f"1629 - 1074 = 555 to the resident: got {credit['resident_share_cents']}"
        )

    def test_charity_totals_match_frozen_lines(self, api):
        """PRD §3.7: "Third, each charity's `total_received_cents` increases by
        the amount of its allocation line."
        PRD §3.7: "Computing the per-line floor first and assigning the remainder
        second is load-bearing — the opposite order (rounding the total first,
        then splitting) would give different cent values and is rejected."

        Design: Difficulty/combinatorial_formula/charity_split_per_line_floor_remainder
        """
        ctx = self._setup()
        settle_credit(ctx["credit"]["id"])
        ch1, ch2 = ctx["charities"]
        assert read_charity(ch1["id"])["total_received_cents"] == 537
        assert read_charity(ch2["id"])["total_received_cents"] == 537
        # pinned order check: round-total-then-split would pay 1075 to charities
        assert read_resident(ctx["resident"]["id"])["credit_balance_cents"] == 555


class TestDisputeRefinalizeBranch:
    def _setup(self):
        return ctx_finalized(zone_name="Zone NL2", resident_name="Drew Dix",
                             resident_email="drew@x.com", fund_cents=100000,
                             certified_weight_kg=12.5, grade="RESALE")

    def test_dispute_retains_hold(self, api):
        """PRD §3.7: "A `PROVISIONAL` or `FINALIZED` credit may be disputed. The
        dispute is filed by the beneficiary `Resident` or by a `ZoneOperator`,
        carries a free-text `reason`, and transitions the credit to `DISPUTED`.
        The hold state is unchanged: if `has_hold` was true, the fund's
        `held_cents` is unchanged, and a later re-finalize from `DISPUTED` reuses
        the same hold rather than placing a new one."

        Design: Difficulty/non_linear_state_machine/credit_dispute_refinalize_branch_no_double_hold
        """
        ctx = self._setup()
        credit = ctx["credit"]
        assert credit["status"] == "FINALIZED" and credit["has_hold"] is True
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 1650 and fund["available_cents"] == 98350

        disputed = validate_success(api_client.dispute_credit(
            credit["id"], {"reason": "resident contests certified weight"},
            make_resident_headers(ctx["resident"]["id"]),
        ))
        assert disputed["status"] == "DISPUTED"
        assert disputed["has_hold"] is True, "dispute retains the hold"
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 1650 and fund["available_cents"] == 98350

    def test_refinalize_places_no_second_hold_then_settles(self, api):
        """PRD §3.7: "A finalize invoked on a `DISPUTED` credit whose `has_hold`
        was already true retains the existing hold and places no second hold."
        PRD §2.8: "Settling a credit converts the hold to a payment: `held_cents`
        decreases by `gross_cents` and `paid_cents` increases by the same amount,
        leaving `available_cents` unchanged."

        Design: Difficulty/non_linear_state_machine/credit_dispute_refinalize_branch_no_double_hold
        """
        ctx = self._setup()
        credit = ctx["credit"]
        validate_success(api_client.dispute_credit(
            credit["id"], {"reason": "resident contests certified weight"},
            make_resident_headers(ctx["resident"]["id"]),
        ))

        refinalized = finalize_credit(credit["id"])
        assert refinalized["status"] == "FINALIZED"
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 1650, (
            f"re-finalize must not place a second hold: held {fund['held_cents']} != 1650"
        )

        settled = settle_credit(credit["id"])
        assert settled["status"] == "SETTLED"
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0 and fund["paid_cents"] == 1650
        assert fund["available_cents"] == 98350
        assert_fund_ledger_invariant(fund)


class TestFinalizeVoidInvariant:
    def test_finalize_places_hold(self, api):
        """PRD §2.8: "Finalizing a credit places a hold: `held_cents` increases by
        the credit's `gross_cents` and `available_cents` falls by the same
        amount."
        PRD §2.8: "The `available_cents` is derived as `funded_total_cents` minus
        `held_cents` minus `paid_cents`, and the server maintains the invariant
        that at all times `held_cents` plus `paid_cents` plus `available_cents`
        equals `funded_total_cents` exactly."

        Design: Difficulty/compensating_invariant/fund_finalize_void_available_restored
        """
        ctx = ctx_finalized(zone_name="Zone CI1", resident_name="Nina Noll",
                            resident_email="nina@x.com", fund_cents=100000)
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 1650
        assert fund["paid_cents"] == 0
        assert fund["available_cents"] == 98350
        assert_fund_ledger_invariant(fund)

    def test_void_restores_available_exactly(self, api):
        """PRD §2.8: "Voiding or quarantining a credit releases the hold:
        `held_cents` decreases by `gross_cents` and `available_cents` rises by the
        same amount."
        PRD §2.8: "Finalize followed by void on the same credit is therefore
        net-neutral on `available_cents`."

        Design: Difficulty/compensating_invariant/fund_finalize_void_available_restored
        """
        ctx = ctx_finalized(zone_name="Zone CI1", resident_name="Nina Noll",
                            resident_email="nina@x.com", fund_cents=100000)
        credit = void_credit(ctx["credit"]["id"])
        assert credit["status"] == "VOIDED"
        assert credit["has_hold"] is False

        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0
        assert fund["paid_cents"] == 0
        assert fund["available_cents"] == 100000, "available exactly restored — zero drift"
        assert_fund_ledger_invariant(fund)


class TestFinalizeRequiresActiveFund:
    def test_finalize_without_fund_rejected(self, api):
        """PRD §3.7: "The credit's zone must have an `ACTIVE` `SponsorFund`
        (otherwise `ERR_FUND_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_active_sponsor_fund
        """
        ctx = ctx_credit(zone_name="Zone CE2", resident_name="Karl Kipp",
                         resident_email="karl@x.com")
        resp = api_client.finalize_credit(ctx["credit"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_FUND_NOT_ACTIVE)
        assert read_credit(ctx["credit"]["id"])["status"] == "PROVISIONAL"

    def test_fund_creation_unblocks_finalize(self, api):
        """PRD §3.7: "On success the credit's `status` becomes `FINALIZED`,
        `gross_cents` is fixed as above, `fund_id` is set to the zone's `ACTIVE`
        fund, and — only if `has_hold` was false — the fund's `held_cents`
        increases by `gross_cents`, `available_cents` falls by the same amount,
        and `has_hold` flips to true."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_active_sponsor_fund
        """
        ctx = ctx_credit(zone_name="Zone CE2", resident_name="Karl Kipp",
                         resident_email="karl@x.com")
        resp = api_client.finalize_credit(ctx["credit"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_FUND_NOT_ACTIVE)

        fund = new_fund(ctx["zone"]["id"], 100000)
        credit = finalize_credit(ctx["credit"]["id"])
        assert credit["status"] == "FINALIZED"
        assert credit["gross_cents"] == 1650
        assert credit["fund_id"] == fund["id"]


class TestSettleEffects:
    def test_settle_executes_all_side_effects(self, api):
        """PRD §3.7: "Settlement performs four effects. First, the fund's
        `held_cents` decreases by `gross_cents` and `paid_cents` increases by the
        same amount — the hold converts to a payment and `available_cents` is
        unchanged. Second, the credit's `charity_allocations` are computed and
        frozen per the zone's `charity_splits` at the time of settlement. Third,
        each charity's `total_received_cents` increases by the amount of its
        allocation line. Fourth, the beneficiary resident — when the credit is
        pickup-sourced — has their `credit_balance_cents` increased by
        `resident_share_cents`, and the source pickup bubbles up from `WEIGHED` to
        `SETTLED`."

        Design: Corner/state_machines/settle_bubbles_pickup_and_pays_out
        """
        ctx = ctx_settled(zone_name="Zone SM6", resident_name="Yara Y",
                          resident_email="yara@x.com", fund_cents=100000,
                          splits=[("ClothesAid", 60), ("FiberFund", 30)],
                          certified_weight_kg=12.5, grade="RESALE")
        credit = ctx["credit"]
        ch1, ch2 = ctx["charities"]
        assert credit["status"] == "SETTLED"
        assert credit["resident_share_cents"] == 165, "1650 - 990 - 495 = 165"
        assert credit["charity_allocations"] == [
            {"charity_id": ch1["id"], "pct": 60, "amount_cents": 990},
            {"charity_id": ch2["id"], "pct": 30, "amount_cents": 495},
        ]
        assert read_pickup(ctx["pickup"]["id"])["status"] == "SETTLED"
        assert read_charity(ch1["id"])["total_received_cents"] == 990
        assert read_charity(ch2["id"])["total_received_cents"] == 495
        assert read_resident(ctx["resident"]["id"])["credit_balance_cents"] == 165
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0 and fund["paid_cents"] == 1650
        assert_fund_ledger_invariant(fund)

    def test_settle_already_settled_credit_rejected(self, api):
        """PRD §3.7: "Settling requires `has_hold` to be true and the credit to be
        in `FINALIZED`; a settle attempt against a `PROVISIONAL` or `DISPUTED`
        credit is rejected with `ERR_CREDIT_NOT_FINAL`, while one against a
        `SETTLED` or `VOIDED` credit is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/settle_already_settled_credit_rejected
        """
        ctx = ctx_settled(zone_name="Zone SM14", resident_name="Dora D",
                          resident_email="dora@x.com", fund_cents=100000)
        resp = api_client.settle_credit(ctx["credit"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fund = read_fund(ctx["fund"]["id"])
        assert fund["paid_cents"] == 1650, "no double settlement"


class TestFundGates:
    def test_second_active_fund_rejected(self, api):
        """PRD §2.8: "Every `ServiceZone` may host at most one `ACTIVE`
        `SponsorFund` at a time; an attempt to create a second one is rejected
        with `ERR_FUND_ALREADY_ACTIVE`."

        Design: Corner/validations/second_active_fund_rejected
        """
        zone = new_zone("Zone V8")
        new_fund(zone["id"], 50000)
        resp = api_client.create_sponsor_fund(
            create_sponsor_fund_payload(zone["id"], sponsor_name="GreenThread",
                                        initial_cents=25000), OP
        )
        validate_error(resp, ApiErrorId.ERR_FUND_ALREADY_ACTIVE)

    def test_fund_topup_derived_available_reconciles(self, api):
        """PRD §2.8: "A top-up increases `funded_total_cents` by the top-up amount
        and therefore also increases `available_cents` by the same amount."
        PRD §2.8: "The `funded_total_cents` is the opening `initial_cents` plus
        the cumulative sum of every top-up and only ever grows."

        Design: Corner/cross_cutting_layers/fund_topup_derived_available_reconciles
        """
        zone = new_zone("Zone XL3")
        fund = new_fund(zone["id"], 100000)

        resp = api_client.topup_fund(
            fund["id"], topup_payload(5000), make_sponsor_manager_headers(fund["id"])
        )
        fund = validate_success(resp)
        assert fund["funded_total_cents"] == 105000
        assert fund["available_cents"] == 105000
        assert fund["held_cents"] == 0 and fund["paid_cents"] == 0
        assert_fund_ledger_invariant(fund)


class TestFinalizeSettledPriority:
    def _setup_settled_with_low_fund(self):
        ctx = ctx_settled(zone_name="Zone PP1", resident_name="Gus Goff",
                          resident_email="gus@x.com", fund_cents=2000,
                          certified_weight_kg=12.5, grade="RESALE")
        fund = read_fund(ctx["fund"]["id"])
        assert fund["available_cents"] == 350, (
            "fiscal precondition genuinely failing too: 350 < 1500 material cost"
        )
        return ctx

    def test_state_error_beats_fiscal_error(self, api):
        """PRD §2.11: "When multiple validation rules apply to a single request,
        the server evaluates them in a fixed priority order and surfaces only the
        first failure."
        PRD §3.7: "The credit must be in `PROVISIONAL` or `DISPUTED` (any other
        status is rejected with `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/finalize_settled_credit_state_beats_fiscal
        """
        ctx = self._setup_settled_with_low_fund()
        resp = api_client.finalize_credit(ctx["credit"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_finalize_leaves_state_untouched(self, api):
        """PRD §2.11: "When multiple validation rules apply to a single request,
        the server evaluates them in a fixed priority order and surfaces only the
        first failure."
        PRD §3.7: "The credit must be in `PROVISIONAL` or `DISPUTED` (any other
        status is rejected with `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/finalize_settled_credit_state_beats_fiscal
        """
        ctx = self._setup_settled_with_low_fund()
        resp = api_client.finalize_credit(ctx["credit"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        assert read_credit(ctx["credit"]["id"])["status"] == "SETTLED"
        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0 and fund["paid_cents"] == 1650
        assert fund["available_cents"] == 350
