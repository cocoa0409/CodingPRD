"""Seed sales and grower settlement: one-sale-per-shift, remainder cent
distribution, provisional vs final variants, patronage evaluation order,
season scoping, finalize gates, payment, and settlement OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bales_by_tag,
    class_bale,
    close_reconcile_sell,
    close_shift,
    create_grade_schedule,
    create_grower,
    create_module,
    create_seed_sale_payload,
    create_settlement_for_grower,
    create_settlement_payload,
    create_shift,
    get_grower,
    get_module,
    get_settlement,
    gin_module,
    list_grower_settlements,
    list_ledger_entries,
    list_shift_seed_sales,
    queue_module,
    reconcile_shift,
    sell_seed,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestSeedSale:
    def test_second_sale_for_shift_rejected(self, api):
        """PRD: "Selling a shift that is not yet `RECONCILED` fails with
        `ERR_SHIFT_NOT_RECONCILED` (HTTP 409), and a shift that already has a
        sale fails with `ERR_SHIFT_ALREADY_SOLD` (HTTP 409) — at most one sale
        exists per shift, so listing a shift's seed sales returns zero or one
        element."
        PRD: "The sale's `sold_lbs` is the sum of `reconciled_seed_lbs` across
        the shift's ginned modules. The `net_pool_cents` is those pounds
        multiplied by the contract price, minus a flat handling fee of 2,500
        cents."

        Design: Corner/state_machines/seed_sale_second_sale_for_shift_rejected
        """
        grower = create_grower("MB-C16", "Seed Farm")
        shift = create_shift("2026", "STAND-SS")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-SS")
        gin_module(module["id"], shift["id"], [("B-SS1", 1000)])
        close_shift(shift["id"], 1000, 8000, 1000)
        reconcile_shift(shift["id"])

        sale = sell_seed(shift["id"], buyer_name="Delta Oil Mill",
                         price_cents_per_lb=20)
        assert sale["sold_lbs"] == 8000
        assert sale["net_pool_cents"] == 157500  # 8000 * 20 - 2500

        resp = api.create_seed_sale(
            create_seed_sale_payload(shift["id"], buyer_name="Second Mill",
                                     price_cents_per_lb=22), ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_SHIFT_ALREADY_SOLD)

        # ginning -11500 (1000 lbs x 11.5c) + seed credit +157500
        assert get_grower(grower["id"])["credit_balance_cents"] == 146000
        assert len(list_shift_seed_sales(shift["id"])) == 1

    def test_remainder_cent_distribution(self, api):
        """PRD: "The pool then allocates back to modules by the same
        largest-remainder rule used at reconciliation: each module's raw share
        is the net pool multiplied by its `reconciled_seed_lbs` and divided by
        `sold_lbs`; shares floor to whole cents; the remainder distributes one
        cent at a time to the largest fractional parts, ties broken by module
        `created_at` ascending."
        PRD: "The grower credits sum to the net pool exactly."

        Design: Corner/calculations/seed_sale_remainder_cent_distribution
        """
        ga = create_grower("MB-C33A", "Rem A")
        gb = create_grower("MB-C33B", "Rem B")
        gc = create_grower("MB-C33C", "Rem C")
        shift = create_shift("2026", "STAND-RM")
        ma = create_module(ga["id"], ticket_number="T-1", module_tag="MT-RM-A",
                           gross_weight_lbs=13000)
        mb = create_module(gb["id"], ticket_number="T-1", module_tag="MT-RM-B",
                           gross_weight_lbs=21000)
        mc = create_module(gc["id"], ticket_number="T-1", module_tag="MT-RM-C",
                           gross_weight_lbs=9000)
        gin_module(ma["id"], shift["id"], [("B-RM-A1", 2500)])
        gin_module(mb["id"], shift["id"], [("B-RM-B1", 3000)])
        gin_module(mc["id"], shift["id"], [("B-RM-C1", 1500)])
        close_shift(shift["id"], 7000, 9999, 23001)
        reconcile_shift(shift["id"])

        # reconciled shares: est 6600/11000/4400 vs 9999
        assert get_module(ma["id"])["reconciled_seed_lbs"] == 3000
        assert get_module(mb["id"])["reconciled_seed_lbs"] == 4999
        assert get_module(mc["id"])["reconciled_seed_lbs"] == 2000

        sale = sell_seed(shift["id"], buyer_name="Remainder Mill",
                         price_cents_per_lb=30)
        assert sale["sold_lbs"] == 9999
        assert sale["net_pool_cents"] == 297470  # 9999 * 30 - 2500

        def seed_credit(grower_id):
            entries = [e for e in list_ledger_entries(grower_id=grower_id)
                       if e["entry_type"] == "SEED_CREDIT"]
            assert len(entries) == 1
            return entries[0]["amount_cents"]

        # raw 89249.92 / 148720.13 / 59499.95 -> 89250 / 148720 / 59500
        credits = {ga["id"]: seed_credit(ga["id"]),
                   gb["id"]: seed_credit(gb["id"]),
                   gc["id"]: seed_credit(gc["id"])}
        assert credits == {ga["id"]: 89250, gb["id"]: 148720, gc["id"]: 59500}
        assert sum(credits.values()) == 297470, "no cent lost or invented"

        # balances fold in the per-grower ginning charges
        assert get_grower(ga["id"])["credit_balance_cents"] == 89250 - 28750
        assert get_grower(gb["id"])["credit_balance_cents"] == 148720 - 34500
        assert get_grower(gc["id"])["credit_balance_cents"] == 59500 - 17250


def _provisional_vs_final_setup(api):
    """Grower G1 with one module (net 20000) ginned into bales 500 + 520 lbs;
    a PROVISIONAL settlement created while the shift is unsold."""
    create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                          loan_rate_points=5450)
    create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                          loan_rate_points=5200,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_to="2026-07-01T00:00:00Z")
    grower = create_grower("MB-200", "Delta Farms Two")
    shift = create_shift("2026", "STAND-B")
    module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-1",
                           gross_weight_lbs=22000, tare_weight_lbs=2000,
                           moisture_pct=9.0, foreign_matter_pct=3.0)
    gin_module(module["id"], shift["id"], [("B-01", 500), ("B-02", 520)])
    st1 = create_settlement_for_grower(grower["id"], "2026")
    return grower, shift, module, st1


class TestSettlementDualVariant:
    def test_provisional_seed_estimate_while_shift_unsold(self, api):
        """PRD: "under `PROVISIONAL` it is the sum of posted `SEED_CREDIT`
        entries plus an estimate for unsold shifts — the `est_seed_lbs` of the
        grower's `GINNED` season modules whose shift has no seed sale,
        multiplied by a reference price of 25 cents per pound with no handling
        fee"
        PRD: "the new settlement is created `DRAFT` with `computation_variant`
        of `PROVISIONAL`"

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final
        """
        grower, shift, module, st1 = _provisional_vs_final_setup(api)
        st1 = get_settlement(st1["id"])
        assert st1["status"] == "DRAFT"
        assert st1["computation_variant"] == "PROVISIONAL"
        seed_entries = [e for e in list_ledger_entries(grower_id=grower["id"])
                        if e["entry_type"] == "SEED_CREDIT"]
        assert seed_entries == [], "no seed credit posted yet — the estimate is algorithmic"
        # est_seed 11000 x 25c
        assert st1["seed_credit_cents"] == 275000
        # lint 1020 x 60 = 61200; quality 0 (unclassed); ginning -(1020 x 11.5)
        # = -11730; patronage 0.2 x 11730 = 2346
        assert st1["lint_value_cents"] == 61200
        assert st1["quality_adjustment_cents"] == 0
        assert st1["ginning_charge_cents"] == -11730
        assert st1["patronage_cents"] == 2346
        assert st1["net_payable_cents"] == 326816

    def test_final_variant_uses_posted_credits_through_payment(self, api):
        """PRD: "under `FINAL` it is the posted `SEED_CREDIT` entries only,
        with no estimates."
        PRD: "The two variants legitimately differ: for identical deliveries,
        provisional and final disagree whenever a sold shift's posted credit
        differs from its estimate, or a shift is not yet sold."
        PRD: "any existing `DRAFT` or `FINAL` settlement for the pair flips to
        terminal `SUPERSEDED`"
        PRD: "On success `paid_amount_cents` captures the amount (it reads null
        until paid), the settlement moves to terminal `PAID`"

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final
        """
        grower, shift, module, st1 = _provisional_vs_final_setup(api)
        close_shift(shift["id"], 1020, 18500, 480)
        reconcile_shift(shift["id"])
        sell_seed(shift["id"], buyer_name="Delta Oil Mill", price_cents_per_lb=28)
        # sold_lbs 18500 -> net pool 18500*28 - 2500 = 515500

        bales = bales_by_tag(module["id"])
        b1, b2 = bales["B-01"], bales["B-02"]
        class_bale(b1["id"], b1["version"], grade_code="31-3", micronaire=4.0,
                   strength_gpt=29.0, staple_32nds=36)
        class_bale(b2["id"], b2["version"], grade_code="41-4", micronaire=4.5,
                   strength_gpt=27.0, staple_32nds=35)
        # b1: 265 + 25 + 15 = 305 -> 500*305/100 = +1525
        # b2: -110 + 0 + 0 = -110 -> 520*-110/100 = -572

        st2 = create_settlement_for_grower(grower["id"], "2026")
        assert get_settlement(st1["id"])["status"] == "SUPERSEDED"
        assert st2["seed_credit_cents"] == 515500, (
            "the posted entry replaces the estimate once the shift is sold")
        assert st2["quality_adjustment_cents"] == 953
        assert st2["net_payable_cents"] == 568269

        finalized = validate_success(api.finalize_settlement(st2["id"], ACCOUNTANT))
        assert finalized["status"] == "FINAL"
        assert finalized["computation_variant"] == "FINAL"
        assert finalized["net_payable_cents"] == 568269

        paid = validate_success(api.pay_settlement(st2["id"],
                                                   {"amount_cents": 568269},
                                                   ACCOUNTANT))
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 568269
        # ledger: ginning -11730, seed +515500, patronage +2346, payment -568269
        assert get_grower(grower["id"])["credit_balance_cents"] == -62153


class TestPatronageEvaluationOrder:
    def _setup(self):
        grower = create_grower("MB-302", "Patronage Farm", patronage_rate=0.20)
        shift = create_shift("2026", "STAND-D")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-P",
                               gross_weight_lbs=11000, tare_weight_lbs=1000,
                               moisture_pct=8.0, foreign_matter_pct=4.0)
        gin_module(module["id"], shift["id"], [("B-P1", 301), ("B-P2", 301)])
        return grower

    def test_patronage_derives_from_ginning_charge_only(self, api):
        """PRD: "Fifth, `patronage_cents` is the grower's `patronage_rate`
        multiplied by the absolute value of `ginning_charge_cents`, rounded
        half-up to whole cents."
        PRD: "The dependency order is pinned: patronage derives from ginning
        charges, and net payable derives from patronage — net never feeds back
        into patronage."

        Design: Difficulty/combinatorial_formula/settlement_patronage_evaluation_order
        """
        grower = self._setup()
        st = create_settlement_for_grower(grower["id"], "2026")
        # 602 lbs x 11.5 = 6923 (rounded once per module)
        assert st["ginning_charge_cents"] == -6923
        # round_half_up(0.20 x 6923) = 1385; feeding net back into the base
        # would produce a different number
        assert st["patronage_cents"] == 1385

    def test_full_provisional_lines(self, api):
        """PRD: "First, `lint_value_cents` sums each season bale's
        `net_weight_lbs` multiplied by the base lint price of 60 cents per
        pound."
        PRD: "Sixth and last, `net_payable_cents` is the sum of the lint,
        quality, seed, ginning, storage, loan-net, adjustment-net, and
        patronage lines."

        Design: Difficulty/combinatorial_formula/settlement_patronage_evaluation_order
        """
        grower = self._setup()
        st = create_settlement_for_grower(grower["id"], "2026")
        assert st["lint_value_cents"] == 36120       # 602 x 60
        assert st["seed_credit_cents"] == 137500     # est 5500 x 25, shift unsold
        assert st["ginning_charge_cents"] == -6923
        assert st["patronage_cents"] == 1385
        assert st["net_payable_cents"] == 168082     # 36120 + 137500 - 6923 + 1385


class TestSettlementSeasonScope:
    def test_settlement_excludes_other_season_entries(self, api):
        """PRD: "Every money line is a pure function of the grower's
        season-scoped inputs, evaluated in a pinned order."
        PRD: "First, `lint_value_cents` sums each season bale's
        `net_weight_lbs` multiplied by the base lint price of 60 cents per
        pound."
        PRD: "A `Grower`'s `credit_balance_cents` is a read-only running
        balance that starts at 0 at registration and equals the sum of
        `amount_cents` across every `LedgerEntry` posted for that grower."

        Design: Corner/calculations/settlement_excludes_other_season_entries
        """
        grower = create_grower("MB-C36", "Season Farm")
        s25 = create_shift("2025", "STAND-S25")
        s26 = create_shift("2026", "STAND-S26")
        m25 = create_module(grower["id"], season="2025", ticket_number="T-1",
                            module_tag="MT-25")
        m26 = create_module(grower["id"], season="2026", ticket_number="T-1",
                            module_tag="MT-26")
        gin_module(m25["id"], s25["id"], [("B-25", 500)])
        gin_module(m26["id"], s26["id"], [("B-26", 500)])

        st = create_settlement_for_grower(grower["id"], "2026")
        assert st["lint_value_cents"] == 30000, "only the 2026 bale"
        assert st["ginning_charge_cents"] == -5750, "only the 2026 entry"
        assert st["seed_credit_cents"] == 137500, "2026 estimate; 2025 out of scope"
        assert st["patronage_cents"] == 1150
        assert st["net_payable_cents"] == 162900
        # the ledger spans both seasons even though the settlement does not
        assert get_grower(grower["id"])["credit_balance_cents"] == -11500


class TestFinalizeGates:
    def test_finalize_gated_by_unginned_modules(self, api):
        """PRD: "three completeness gates must all pass: every module of the
        grower-season must be `GINNED` or `REJECTED` (else
        `ERR_UNGINNED_MODULES_EXIST`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_gated_by_module_states
        """
        # Only the module-state gate may fail: the ginned module's bale is
        # classed and the shift's seed is sold, isolating the QUEUED module.
        create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                              loan_rate_points=5200)
        grower = create_grower("MB-801", "Pending Farm")
        shift = create_shift("2026", "STAND-M")
        m1 = create_module(grower["id"], ticket_number="T-1", module_tag="MT-F1")
        m2 = create_module(grower["id"], ticket_number="T-2", module_tag="MT-F2")
        gin_module(m1["id"], shift["id"], [("B-F1", 500)])
        bale = bales_by_tag(m1["id"])["B-F1"]
        class_bale(bale["id"], bale["version"], grade_code="21-2", micronaire=4.0,
                   strength_gpt=28.0, staple_32nds=35)
        queue_module(m2["id"], shift["id"])
        close_reconcile_sell(shift["id"], 500, 9000, 500)

        st = create_settlement_for_grower(grower["id"], "2026")
        resp = api.finalize_settlement(st["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_UNGINNED_MODULES_EXIST)

    def test_finalize_rejection_leaves_settlement_draft(self, api):
        """PRD: "Finalizing recomputes all money lines under
        `computation_variant` `FINAL`, moves the settlement `DRAFT → FINAL`"
        PRD: "every module of the grower-season must be `GINNED` or `REJECTED`
        (else `ERR_UNGINNED_MODULES_EXIST`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_gated_by_module_states
        """
        create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                              loan_rate_points=5200)
        grower = create_grower("MB-801", "Pending Farm")
        shift = create_shift("2026", "STAND-M")
        m1 = create_module(grower["id"], ticket_number="T-1", module_tag="MT-F1")
        m2 = create_module(grower["id"], ticket_number="T-2", module_tag="MT-F2")
        gin_module(m1["id"], shift["id"], [("B-F1", 500)])
        bale = bales_by_tag(m1["id"])["B-F1"]
        class_bale(bale["id"], bale["version"], grade_code="21-2", micronaire=4.0,
                   strength_gpt=28.0, staple_32nds=35)
        queue_module(m2["id"], shift["id"])
        close_reconcile_sell(shift["id"], 500, 9000, 500)

        st = create_settlement_for_grower(grower["id"], "2026")
        validate_error(api.finalize_settlement(st["id"], ACCOUNTANT),
                       ApiErrorId.ERR_UNGINNED_MODULES_EXIST)
        after = get_settlement(st["id"])
        assert after["status"] == "DRAFT"
        assert after["computation_variant"] == "PROVISIONAL"

    def test_finalize_with_unclassed_bale_rejected(self, api):
        """PRD: "every bale of the grower-season must be `CLASSED` (else
        `ERR_UNCLASSED_BALES_EXIST`, HTTP 409)"

        Design: Corner/validations/finalize_with_unclassed_bale_rejected
        """
        # Only the classing gate may fail: module GINNED and the shift's seed
        # is sold, isolating the UNCLASSED bale.
        create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                              loan_rate_points=5200)
        grower = create_grower("MB-C51", "Unclassed Settle Farm")
        shift = create_shift("2026", "STAND-US")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-US")
        gin_module(module["id"], shift["id"], [("B-US1", 500)])
        close_reconcile_sell(shift["id"], 500, 9000, 500)

        st = create_settlement_for_grower(grower["id"], "2026")
        resp = api.finalize_settlement(st["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_UNCLASSED_BALES_EXIST)
        assert get_settlement(st["id"])["status"] == "DRAFT"

    def test_finalize_with_unsold_seed_rejected(self, api):
        """PRD: "every shift holding a `GINNED` module of the grower-season
        must have its seed sold (else `ERR_UNSOLD_SEED_EXISTS`, HTTP 409)."

        Design: Corner/validations/finalize_with_unsold_seed_rejected
        """
        create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                              loan_rate_points=5200)
        grower = create_grower("MB-C52", "Unsold Farm")
        shift = create_shift("2026", "STAND-US2")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-US2")
        gin_module(module["id"], shift["id"], [("B-US2", 500)])
        bale = bales_by_tag(module["id"])["B-US2"]
        class_bale(bale["id"], bale["version"], grade_code="21-2", micronaire=4.0,
                   strength_gpt=28.0, staple_32nds=35)
        close_shift(shift["id"], 500, 9000, 500)
        reconcile_shift(shift["id"])
        # no seed sale

        st = create_settlement_for_grower(grower["id"], "2026")
        resp = api.finalize_settlement(st["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_UNSOLD_SEED_EXISTS)
        assert get_settlement(st["id"])["status"] == "DRAFT"


class TestSettlementPayment:
    def test_finalize_on_superseded_rejected(self, api):
        """PRD: "The settlement must be `DRAFT` (else
        `ERR_SETTLEMENT_NOT_FINALIZABLE`, HTTP 409)"
        PRD: "any existing `DRAFT` or `FINAL` settlement for the pair flips to
        terminal `SUPERSEDED`, and the new settlement is created `DRAFT` with
        `computation_variant` of `PROVISIONAL`"

        Design: Corner/state_machines/settlement_finalize_on_superseded_rejected
        """
        grower = create_grower("MB-C23", "Supersede Farm")
        st1 = create_settlement_for_grower(grower["id"], "2026")
        st2 = create_settlement_for_grower(grower["id"], "2026")

        resp = api.finalize_settlement(st1["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FINALIZABLE)
        assert get_settlement(st1["id"])["status"] == "SUPERSEDED"
        assert get_settlement(st2["id"])["status"] == "DRAFT"

    def test_pay_from_draft_rejected_state_beats_amount(self, api):
        """PRD: "The settlement must be `FINAL` (else
        `ERR_SETTLEMENT_NOT_FINAL`, HTTP 409), and the payload `amount_cents`
        must equal the settlement's `net_payable_cents` exactly — any other
        amount fails with `ERR_OVERPAYMENT` (HTTP 402)."
        PRD: "Only then do state-gate checks run (the transition gates and the
        OCC version match), then contamination and moisture safety plus
        segregation of duties, then uniqueness and quota rules, then temporal
        window rules, then cross-entity coherence, and finally money caps and
        exact-amount rules. A request failing an earlier tier never surfaces a
        later tier's error."

        Design: Corner/state_machines/settlement_pay_from_draft_rejected
        """
        grower = create_grower("MB-C22", "Draft Farm")
        st = create_settlement_for_grower(grower["id"], "2026")
        assert st["net_payable_cents"] == 0, "no season activity"

        resp = api.pay_settlement(st["id"], {"amount_cents": 5}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FINAL)
        assert get_settlement(st["id"])["status"] == "DRAFT"
        entries = list_ledger_entries(settlement_id=st["id"])
        assert entries == [], "no PATRONAGE or SETTLEMENT_PAYMENT entries posted"

    def test_pay_amount_mismatch_then_exact_then_paid_lockout(self, api):
        """PRD: "the payload `amount_cents` must equal the settlement's
        `net_payable_cents` exactly — any other amount fails with
        `ERR_OVERPAYMENT` (HTTP 402)."
        PRD: "two ledger entries post with `settlement_id` set: a `PATRONAGE`
        entry for positive `patronage_cents` and a `SETTLEMENT_PAYMENT` entry
        for the negative of `net_payable_cents`"
        PRD: "Creation is refused while a `PAID` settlement exists for that
        grower and season — `ERR_SETTLEMENT_ALREADY_PAID` (HTTP 409)."

        Design: Corner/state_machines/settlement_pay_amount_mismatch_and_paid_lockout
        """
        create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                              loan_rate_points=5200)
        grower = create_grower("MB-C24", "Pay Farm")
        shift = create_shift("2026", "STAND-PY")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-PY")
        gin_module(module["id"], shift["id"], [("B-PY1", 100)])
        bale = bales_by_tag(module["id"])["B-PY1"]
        # mic 4.0 -> +25; str 28.0 -> 0; schedule 0 -> 25 pts -> +25 cents
        class_bale(bale["id"], bale["version"], grade_code="21-2", micronaire=4.0,
                   strength_gpt=28.0, staple_32nds=35)
        close_reconcile_sell(shift["id"], 100, 9000, 900, price_cents_per_lb=20)
        # seed pool: 9000 x 20 - 2500 = 177500

        st = create_settlement_for_grower(grower["id"], "2026")
        validate_success(api.finalize_settlement(st["id"], ACCOUNTANT))
        st = get_settlement(st["id"])
        # lint 6000 + quality 25 + seed 177500 - ginning 1150 + patronage 230
        assert st["net_payable_cents"] == 182605

        e1 = api.pay_settlement(st["id"], {"amount_cents": 182604}, ACCOUNTANT)
        validate_error(e1, ApiErrorId.ERR_OVERPAYMENT)
        assert get_settlement(st["id"])["status"] == "FINAL"

        paid = validate_success(api.pay_settlement(st["id"],
                                                   {"amount_cents": 182605},
                                                   ACCOUNTANT))
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 182605

        entries = list_ledger_entries(settlement_id=st["id"])
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type["PATRONAGE"] == 230
        assert by_type["SETTLEMENT_PAYMENT"] == -182605

        e2 = api.create_settlement(
            grower["id"],
            create_settlement_payload("2026", get_grower(grower["id"])["version"]),
            ACCOUNTANT)
        validate_error(e2, ApiErrorId.ERR_SETTLEMENT_ALREADY_PAID)


class TestSettlementOcc:
    def test_stale_grower_version_rejected(self, api):
        """PRD: "Creating a settlement for a grower requires the request to
        carry `expected_grower_version` equal to the grower's current
        `version`. If the grower's version has advanced since the client last
        read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD: "creation also increments the grower's `version`."

        Design: Corner/cross_cutting_layers/occ_settlement_stale_version_rejected
        """
        grower = create_grower("MB-C81", "OCC Settle Farm")
        observed = grower["version"]
        st1 = validate_success(api.create_settlement(
            grower["id"], create_settlement_payload("2026", observed), ACCOUNTANT),
            expected_status=201)
        assert st1["status"] == "DRAFT"

        replay = api.create_settlement(
            grower["id"], create_settlement_payload("2026", observed), ACCOUNTANT)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        settlements = list_grower_settlements(grower["id"])
        assert len(settlements) == 1, (
            "the rejected stale create produced no SUPERSEDED settlement")
        assert settlements[0]["id"] == st1["id"]
        assert settlements[0]["status"] == "DRAFT"
