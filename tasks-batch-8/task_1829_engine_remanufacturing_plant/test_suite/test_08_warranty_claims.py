"""Warranty claims: filing window, teardown, segregation of duties, and the
credit vs replacement settlement variants with their cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_claim_payload,
    adjudicate_warranty_claim,
    assert_core_deposit,
    assert_warranty_claim,
    create_active_spec,
    create_distributor,
    create_warranty_claim_payload,
    file_warranty_claim,
    find_deposit_for_engine,
    get_distributor,
    get_reman_engine,
    make_distributor_headers,
    make_warranty_adjuster_headers,
    produce_sealed_engine,
    sell_engine_to,
    set_logical_clock,
    teardown_warranty_claim,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["plant_admin_headers"]


def _setup_two_claims(api, buyer_discount=0.15, app_code="K1500-1997",
                      with_replacement_pool=False):
    """Two engines sold to the buyer at the default clock; claims filed at
    2026-11-04 (day 95 -> 3 months in service) and torn down by tech-9.

    Returns (buyer, spec, ctx1, sale1, claim1, ctx2, sale2, claim2) plus
    optionally ctx3 for a sealed replacement pool engine.
    """
    set_logical_clock()
    core_source = create_distributor(distributor_code="D-CORE",
                                     name="Core Supply Co")
    buyer = create_distributor(distributor_code="D-BUY", name="Buyer Bros",
                               credit_limit_cents=2000000,
                               volume_discount_pct=buyer_discount)
    spec = create_active_spec(application_code=app_code)
    ctx1 = produce_sealed_engine(spec, core_source, slot=0)
    ctx2 = produce_sealed_engine(spec, core_source, slot=1)
    ctx3 = (produce_sealed_engine(spec, core_source, slot=2)
            if with_replacement_pool else None)
    sale1 = sell_engine_to(buyer, spec)
    sale2 = sell_engine_to(buyer, spec)
    set_logical_clock("2026-11-04T00:00:00Z")
    claim1 = file_warranty_claim(sale1["engine"]["id"], buyer)
    claim2 = file_warranty_claim(sale2["engine"]["id"], buyer)
    claim1 = teardown_warranty_claim(claim1["id"], tech_user_id="tech-9")
    claim2 = teardown_warranty_claim(claim2["id"], tech_user_id="tech-9")
    return buyer, spec, ctx1, sale1, claim1, ctx2, sale2, claim2, ctx3


class TestWarrantySettlementVariants:
    def test_credit_settlement_prorated_minus_fee(self, api):
        """PRD §3.9: "The engine's price is computed per the sale-pricing
        rule: the spec's `list_price_cents` multiplied by one minus the
        buyer's `volume_discount_pct`, rounded half-up to whole cents, and
        written to `sale_price_cents`."
        PRD §3.11: "the system computes `months_in_service` as the number of
        whole days between `filed_at` and the engine's `sold_at`, divided by
        30 and rounded down."
        PRD §3.11: "The credit is computed with a pinned evaluation order:
        first `months_in_service` as already computed on the claim; then the
        remaining ratio — the twelve-month warranty term minus the months
        used, divided by twelve, floored at zero so a claim filed late in the
        term never goes negative; then the prorated amount, which is the
        engine's `sale_price_cents` multiplied by that remaining ratio and
        rounded half-up to whole cents; then the settlement, which is the
        prorated amount minus the `teardown_fee_cents`, floored at zero."

        Design: Difficulty/dual_variant_calc/warranty_credit_vs_replacement_settlement
        """
        buyer, spec, ctx1, sale1, claim1, ctx2, sale2, claim2, _ = \
            _setup_two_claims(api)
        assert sale1["engine"]["sale_price_cents"] == 212500, (
            "round_half_up(250000 x (1 - 0.15))")
        assert claim1["months_in_service"] == 3, "floor(95 / 30)"

        settled = adjudicate_warranty_claim(claim1["id"], "APPROVED_CREDIT",
                                            teardown_fee_cents=7500,
                                            adjuster_user_id="adj-1")
        assert_warranty_claim(settled)
        assert settled["status"] == "APPROVED_CREDIT"
        # max(0, round_half_up(212500 x 9/12) - 7500) = 159375 - 7500
        assert settled["settled_credit_cents"] == 151875

        after = get_distributor(buyer["id"])
        assert after["credit_balance_cents"] == 151875, (
            "the settlement posts to the buyer's credit balance")
        assert get_reman_engine(sale1["engine"]["id"])["status"] == "SCRAPPED"

    def test_replacement_settlement_consumes_sealed_pool(self, api):
        """PRD §3.11: "An outcome of `APPROVED_REPLACEMENT` settles in kind,
        not cash: `settled_credit_cents` is 0, and instead the same
        server-side selector as a sale allocates a replacement — a `SEALED`
        engine whose `build_spec_id` matches the failed engine's spec".
        PRD §3.11: "The selected engine moves from `SEALED` to `SOLD` with
        `distributor_id` set to the claimant, `sold_at` stamped from the
        adjudication clock, and `sale_price_cents` set to 0 — warranty
        replacements bypass the sale-pricing rule entirely."

        Design: Difficulty/dual_variant_calc/warranty_credit_vs_replacement_settlement
        """
        buyer, spec, ctx1, sale1, claim1, ctx2, sale2, claim2, ctx3 = \
            _setup_two_claims(api, with_replacement_pool=True)

        settled = adjudicate_warranty_claim(claim2["id"],
                                            "APPROVED_REPLACEMENT",
                                            teardown_fee_cents=7500,
                                            adjuster_user_id="adj-1")
        assert settled["status"] == "APPROVED_REPLACEMENT"
        assert settled["settled_credit_cents"] == 0, (
            "the replacement variant grants no cash credit")

        replacement = get_reman_engine(ctx3["engine"]["id"])
        assert replacement["status"] == "SOLD"
        assert replacement["distributor_id"] == buyer["id"]
        assert replacement["sale_price_cents"] == 0

        after = get_distributor(buyer["id"])
        # deposits on E1, E2, and the replacement E3: 3 x 200000
        assert after["deposits_held_cents"] == 600000
        assert after["credit_balance_cents"] == 0
        assert get_reman_engine(sale2["engine"]["id"])["status"] == "SCRAPPED"


class TestWarrantyProrationFloor:
    def test_proration_mid_term_pays_prorated_minus_fee(self, api):
        """PRD §3.11: "then the settlement, which is the prorated amount minus
        the `teardown_fee_cents`, floored at zero."
        PRD §3.11: "The result is written to `settled_credit_cents` and added
        to the distributor's `credit_balance_cents`."

        Design: Difficulty/combinatorial_formula/warranty_proration_multi_input_floor
        """
        buyer, spec, ctx1, sale1, claim1, ctx2, sale2, claim2, _ = \
            _setup_two_claims(api, app_code="TAHOE-1998")

        settled = adjudicate_warranty_claim(claim1["id"], "APPROVED_CREDIT",
                                            teardown_fee_cents=7500,
                                            adjuster_user_id="adj-1")
        # months 3: round_half_up(212500 x 9/12) - 7500 = 159375 - 7500
        assert settled["settled_credit_cents"] == 151875
        assert get_distributor(buyer["id"])["credit_balance_cents"] == 151875

    def test_proration_late_term_floors_at_zero(self, api):
        """PRD §3.11: "then the remaining ratio — the twelve-month warranty
        term minus the months used, divided by twelve, floored at zero so a
        claim filed late in the term never goes negative; then the prorated
        amount, which is the engine's `sale_price_cents` multiplied by that
        remaining ratio and rounded half-up to whole cents; then the
        settlement, which is the prorated amount minus the
        `teardown_fee_cents`, floored at zero."

        Design: Difficulty/combinatorial_formula/warranty_proration_multi_input_floor
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-CW",
                                         name="Core World")
        buyer = create_distributor(distributor_code="D-W",
                                   name="Warranty Buyer",
                                   credit_limit_cents=2000000,
                                   volume_discount_pct=0.15)
        spec = create_active_spec(application_code="TAHOE-1998")
        produce_sealed_engine(spec, core_source, slot=0)
        produce_sealed_engine(spec, core_source, slot=1)
        sale1 = sell_engine_to(buyer, spec)
        sale2 = sell_engine_to(buyer, spec)

        set_logical_clock("2026-11-04T00:00:00Z")  # day 95 -> months 3
        claim1 = file_warranty_claim(sale1["engine"]["id"], buyer)
        teardown_warranty_claim(claim1["id"], tech_user_id="tech-9")

        set_logical_clock("2027-07-26T00:00:00Z")  # day 359 -> months 11
        claim2 = file_warranty_claim(sale2["engine"]["id"], buyer,
                                     "excessive blow-by")
        assert claim2["months_in_service"] == 11, "floor(359 / 30)"
        teardown_warranty_claim(claim2["id"], tech_user_id="tech-9")

        adjudicate_warranty_claim(claim1["id"], "APPROVED_CREDIT",
                                  teardown_fee_cents=7500,
                                  adjuster_user_id="adj-1")
        settled2 = adjudicate_warranty_claim(claim2["id"], "APPROVED_CREDIT",
                                             teardown_fee_cents=20000,
                                             adjuster_user_id="adj-1")
        # months 11: round_half_up(212500 x 1/12) == 17708, then
        # max(0, 17708 - 20000) floors at 0
        assert settled2["settled_credit_cents"] == 0
        assert get_distributor(buyer["id"])["credit_balance_cents"] == 151875


class TestReplacementCascade:
    def _setup_replacement_case(self, api):
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC",
                                         name="Core Source")
        claimant = create_distributor(distributor_code="D-CL",
                                      name="Claimant Dist",
                                      credit_limit_cents=2000000)
        spec = create_active_spec(application_code="ASTRO-1996")
        ctx_failed = produce_sealed_engine(spec, core_source, slot=0)
        ctx_replacement = produce_sealed_engine(spec, core_source, slot=1)
        sale = sell_engine_to(claimant, spec)  # sells the first-sealed engine
        claim = file_warranty_claim(sale["engine"]["id"], claimant,
                                    "oil consumption")
        claim = teardown_warranty_claim(claim["id"], "valve seal failure",
                                        tech_user_id="tech-9")
        return claimant, spec, ctx_failed, sale, ctx_replacement, claim

    def test_replacement_adjudication_moves_engines(self, api):
        """PRD §3.11: "The selected engine moves from `SEALED` to `SOLD` with
        `distributor_id` set to the claimant, `sold_at` stamped from the
        adjudication clock, and `sale_price_cents` set to 0 — warranty
        replacements bypass the sale-pricing rule entirely."
        PRD §3.11: "The failed engine, already `RETURNED`, is scrapped —
        `RETURNED` to `SCRAPPED` — regardless of outcome."

        Design: Difficulty/transitive_cascade/replacement_adjudication_depth3_chain
        """
        claimant, spec, ctx_failed, sale, ctx_replacement, claim = \
            self._setup_replacement_case(api)
        assert sale["engine"]["id"] == ctx_failed["engine"]["id"], (
            "the sale selector picked the only sealed engine at sale time")

        settled = adjudicate_warranty_claim(claim["id"],
                                            "APPROVED_REPLACEMENT",
                                            teardown_fee_cents=0,
                                            adjuster_user_id="adj-1")
        assert settled["status"] == "APPROVED_REPLACEMENT"
        assert settled["settled_credit_cents"] == 0

        replacement = get_reman_engine(ctx_replacement["engine"]["id"])
        assert replacement["status"] == "SOLD"
        assert replacement["distributor_id"] == claimant["id"]
        assert replacement["sale_price_cents"] == 0

        failed = get_reman_engine(ctx_failed["engine"]["id"])
        assert failed["status"] == "SCRAPPED", (
            "the failed unit is torn down and scrapped regardless of outcome")

    def test_replacement_adjudication_creates_deposit_and_debits_ledger(self, api):
        """PRD §3.11: "The replacement chain then runs exactly as a sale chain
        would: a new core deposit is created for the claimant in `HELD` status
        with `amount_cents` copied from the spec's `core_deposit_cents`, the
        claimant's `deposits_held_cents` increases by that amount, and the
        distributor's `version` increments by 1."

        Design: Difficulty/transitive_cascade/replacement_adjudication_depth3_chain
        """
        claimant, spec, ctx_failed, sale, ctx_replacement, claim = \
            self._setup_replacement_case(api)
        assert get_distributor(claimant["id"])["deposits_held_cents"] == 200000

        adjudicate_warranty_claim(claim["id"], "APPROVED_REPLACEMENT",
                                  teardown_fee_cents=0, adjuster_user_id="adj-1")

        deposit = find_deposit_for_engine(ctx_replacement["engine"]["id"])
        assert_core_deposit(deposit)
        assert deposit["status"] == "HELD"
        assert deposit["amount_cents"] == 200000
        assert deposit["distributor_id"] == claimant["id"]

        after = get_distributor(claimant["id"])
        # original E-F deposit 200000 plus replacement deposit 200000
        assert after["deposits_held_cents"] == 400000, (
            "the replacement sale itself creates a second HELD deposit")


class TestWarrantyGatekeeping:
    def test_claim_after_warranty_window_rejected(self, api):
        """PRD §3.11: "The warranty window is twelve 30-day months: filing is
        permitted only while the whole-day age of the sale — the floor of the
        difference between the current logical clock and the engine's
        `sold_at`, in seconds, divided by 86400 — is strictly less than 360
        days."
        PRD §3.11: "Filing at or after day 360 is rejected with
        `ERR_WARRANTY_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_after_warranty_window_rejected
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRCA",
                                         name="Core Source A")
        buyer = create_distributor(distributor_code="D-WX",
                                   name="Expired Claimant",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="YUKON-1995")
        produce_sealed_engine(spec, core_source, slot=0)
        sale = sell_engine_to(buyer, spec)  # sold 2026-08-01

        set_logical_clock("2027-07-27T00:00:00Z")  # exactly day 360
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(sale["engine"]["id"], buyer["id"],
                                          "late knock"),
            make_distributor_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

        claims, meta = validate_paginated(api.list_warranty_claims(ADMIN))
        assert claims == [] and meta["total_count"] == 0, (
            "no claim is persisted for an expired filing")

    def test_adjudicate_by_teardown_technician_forbidden(self, api):
        """PRD §3.11: "Adjudication is reserved for a `WarrantyAdjuster` and
        is segregation-checked: the adjudicator's `X-User-ID` must differ from
        the claim's `teardown_by`, else `ERR_ADJUDICATOR_IS_TEARDOWN_TECH`
        (HTTP 403)."

        Design: Corner/validations/adjudicate_by_teardown_technician_forbidden
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRCB",
                                         name="Core Source B")
        buyer = create_distributor(distributor_code="D-ADJ",
                                   name="Adjunct Buyer",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="SUBURBAN-1995")
        produce_sealed_engine(spec, core_source, slot=0)
        sale = sell_engine_to(buyer, spec)
        assert sale["engine"]["sale_price_cents"] == 250000  # discount 0.0

        set_logical_clock("2026-11-04T00:00:00Z")  # day 95 -> months 3
        claim = file_warranty_claim(sale["engine"]["id"], buyer,
                                    "main bearing noise")
        claim = teardown_warranty_claim(claim["id"], "spun main bearing",
                                        tech_user_id="tech-9")
        assert claim["teardown_by"] == "tech-9"

        resp = api.adjudicate_warranty_claim(
            claim["id"], adjudicate_claim_payload("APPROVED_CREDIT", 0),
            make_warranty_adjuster_headers("tech-9"))
        validate_error(resp, ApiErrorId.ERR_ADJUDICATOR_IS_TEARDOWN_TECH)

        settled = adjudicate_warranty_claim(claim["id"], "APPROVED_CREDIT",
                                            teardown_fee_cents=0,
                                            adjuster_user_id="adj-2")
        assert settled["status"] == "APPROVED_CREDIT"
        # round_half_up(250000 x 9/12) - 0
        assert settled["settled_credit_cents"] == 187500
