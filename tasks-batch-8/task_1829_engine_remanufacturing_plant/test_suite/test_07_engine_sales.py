"""Engine sales: allocation selector, credit/emissions/fiscal gates, OCC on
the distributor version, and the deposit ledger chain."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_core_deposit,
    assert_reman_engine,
    create_active_spec,
    create_distributor,
    create_received_return,
    get_deposit,
    get_distributor,
    get_reman_engine,
    grade_core_return,
    list_all_deposits,
    make_distributor_headers,
    patch_distributor,
    produce_sealed_engine,
    sell_engine_payload,
    sell_engine_to,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]


class TestSaleGates:
    def test_credit_hold_masks_credit_limit(self, api):
        """PRD §3.9: "The sale then passes a gauntlet of checks in a fixed
        order. After the generic tiers — authentication, role, body
        well-formedness, existence, and ownership (a distributor buys only
        against its own ledger, so a mismatch yields `ERR_FORBIDDEN_OWNERSHIP`)
        — the buyer's account must be `ACTIVE`, not on `CREDIT_HOLD`
        (`ERR_DISTRIBUTOR_CREDIT_HOLD`)."
        PRD §3.9: "The fiscal gate comes next: the buyer's current
        `deposits_held_cents` plus the spec's `core_deposit_cents` must not
        exceed the buyer's `credit_limit_cents`, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/sell_credit_hold_masks_credit_limit
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC3",
                                         name="Core Source 3")
        held = create_distributor(distributor_code="D-H", name="Held Buyer",
                                  credit_limit_cents=100000)  # < 200000 deposit
        held = patch_distributor(held["id"], status="CREDIT_HOLD")
        spec = create_active_spec(application_code="IMPALA-1996")
        produce_sealed_engine(spec, core_source, slot=0)

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], held["version"]),
            make_distributor_headers(held["id"]))
        # The state gate precedes the fiscal gate in the fixed order.
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_CREDIT_HOLD)

    def test_credit_hold_rejection_has_no_sale_side_effects(self, api):
        """PRD §3.1: "While an account sits on `CREDIT_HOLD`, any purchase
        attempt on its behalf is rejected with `ERR_DISTRIBUTOR_CREDIT_HOLD`
        (HTTP 409)."
        PRD §3.9: "The sale chain then runs: a new core deposit is created for
        the buyer in `HELD` status with `amount_cents` copied from the spec's
        `core_deposit_cents` and `sold_at` set to the sale clock".

        Design: Difficulty/priority_pair_validation_conflict/sell_credit_hold_masks_credit_limit
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC3",
                                         name="Core Source 3")
        held = create_distributor(distributor_code="D-H", name="Held Buyer",
                                  credit_limit_cents=100000)
        held = patch_distributor(held["id"], status="CREDIT_HOLD")
        spec = create_active_spec(application_code="IMPALA-1996")
        ctx = produce_sealed_engine(spec, core_source, slot=0)

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], held["version"]),
            make_distributor_headers(held["id"]))
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_CREDIT_HOLD)

        engine = get_reman_engine(ctx["engine"]["id"])
        assert engine["status"] == "SEALED", "no sale fired"
        assert engine["distributor_id"] is None
        assert list_all_deposits() == [], "no deposit may be created"
        after = get_distributor(held["id"])
        assert after["deposits_held_cents"] == 0
        assert after["credit_balance_cents"] == 0

    def test_california_buyer_federal_engine_rejected(self, api):
        """PRD §3.9: "The emissions gate follows: a buyer whose
        `emissions_requirement` is `CALIFORNIA` may only be sold an engine
        whose spec's `emissions_tier` is `CALIFORNIA`, else
        `ERR_EMISSIONS_TIER_MISMATCH` (HTTP 422); a buyer whose requirement is
        `FEDERAL` accepts either tier."

        Design: Corner/validations/california_buyer_federal_engine_rejected
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC8",
                                         name="Core Source 8")
        buyer = create_distributor(distributor_code="D-CA",
                                   name="California Parts",
                                   emissions_requirement="CALIFORNIA",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="CAMARO-1995",
                                  emissions_tier="FEDERAL")
        ctx = produce_sealed_engine(spec, core_source, slot=0)

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], buyer["version"]),
            make_distributor_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_EMISSIONS_TIER_MISMATCH)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "SEALED"

    def test_sell_over_credit_limit_rejected(self, api):
        """PRD §3.9: "The fiscal gate comes next: the buyer's current
        `deposits_held_cents` plus the spec's `core_deposit_cents` must not
        exceed the buyer's `credit_limit_cents`, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/sell_over_credit_limit_rejected
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC9",
                                         name="Core Source 9")
        buyer = create_distributor(distributor_code="D-L", name="Limited Buyer",
                                   credit_limit_cents=100000)
        spec = create_active_spec(application_code="TAHOE-1995")
        ctx = produce_sealed_engine(spec, core_source, slot=0)

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], buyer["version"]),
            make_distributor_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "SEALED"

    def test_sell_with_empty_pool_rejected(self, api):
        """PRD §3.9: "An empty pool is rejected with `ERR_NO_ELIGIBLE_ENGINE`
        (HTTP 422)."

        Design: Corner/validations/sell_with_empty_pool_rejected
        """
        buyer = create_distributor(distributor_code="D-E",
                                   name="Empty Pool Buyer",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="ASTRO-1995")

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], buyer["version"]),
            make_distributor_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ENGINE)

    def test_sell_as_plant_admin_forbidden(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not listed for the endpoint will be rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.9: "A purchase is initiated by a `Distributor`-role caller
        naming a `build_spec_id`; the server, not the buyer, selects the
        unit."

        Design: Corner/rbac/sell_as_plant_admin_forbidden
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SPC",
                                         name="Core Source P")
        buyer = create_distributor(distributor_code="D-SP", name="Sell Permit",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="BRAVADA-1995")
        ctx = produce_sealed_engine(spec, core_source, slot=0)

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], buyer["version"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "SEALED"


class TestSaleChain:
    def test_sale_creates_held_deposit_and_raises_exposure(self, api):
        """PRD §3.9: "The sale chain then runs: a new core deposit is created
        for the buyer in `HELD` status with `amount_cents` copied from the
        spec's `core_deposit_cents` and `sold_at` set to the sale clock; the
        buyer's `deposits_held_cents` increases by that `amount_cents`; and
        the distributor's `version` increments by 1".
        PRD §3.1: "`deposits_held_cents` is the sum of `amount_cents` over
        exactly that distributor's core deposits whose `status` is `HELD`".

        Design: Difficulty/compensating_invariant/deposit_held_conserved_through_sale_and_refund
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC5",
                                         name="Core Source 5")
        buyer = create_distributor(distributor_code="D-S",
                                   name="Invariant Buyer",
                                   credit_limit_cents=2000000)
        assert buyer["deposits_held_cents"] == 0, "baseline"
        spec = create_active_spec(application_code="YUKON-1998")
        produce_sealed_engine(spec, core_source, slot=0)

        sale = sell_engine_to(buyer, spec)
        engine = sale["engine"]
        assert_reman_engine(engine)
        assert engine["status"] == "SOLD"
        assert engine["distributor_id"] == buyer["id"]
        assert engine["sale_price_cents"] == 250000  # discount 0.0

        deposit = sale["deposit"]
        assert_core_deposit(deposit)
        assert deposit["status"] == "HELD"
        assert deposit["amount_cents"] == 200000
        assert deposit["reman_engine_id"] == engine["id"]
        assert deposit["distributor_id"] == buyer["id"]

        after = sale["distributor"]
        assert after["deposits_held_cents"] == 200000, (
            "forward action: the sale raises the held exposure")
        assert after["version"] == buyer["version"] + 1

    def test_linked_grading_close_restores_ledger_baseline(self, api):
        """PRD §3.4: "Every close cascades to the distributor ledger:
        `deposits_held_cents` decreases by the deposit's `amount_cents`, and —
        on the refund path only — `credit_balance_cents` increases by the
        `refunded_cents`."
        PRD §3.4: "The `refunded_cents` is the `amount_cents` multiplied by
        the bracket percentage, rounded half-up to whole cents; the
        `forfeited_cents` is the `amount_cents` minus the `refunded_cents`."

        Design: Difficulty/compensating_invariant/deposit_held_conserved_through_sale_and_refund
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC5",
                                         name="Core Source 5")
        buyer = create_distributor(distributor_code="D-S",
                                   name="Invariant Buyer",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="YUKON-1998")
        produce_sealed_engine(spec, core_source, slot=0)
        sale = sell_engine_to(buyer, spec)
        deposit = sale["deposit"]
        ret = create_received_return(buyer, spec,
                                     core_deposit_id=deposit["id"])

        set_logical_clock("2026-08-31T00:00:00Z")  # exactly 30 days -> 100%
        grade_core_return(ret["id"], "GRADE_A", [])

        closed = get_deposit(deposit["id"])
        assert closed["status"] == "CLOSED_REFUNDED"
        assert closed["refunded_cents"] == 200000
        assert closed["forfeited_cents"] == 0
        assert (closed["refunded_cents"] + closed["forfeited_cents"]
                == closed["amount_cents"]), "refund + forfeit recombines"

        after = get_distributor(buyer["id"])
        assert after["deposits_held_cents"] == 0, (
            "compensating close restores the pre-sale baseline")
        # 100000 grading credit + 200000 refund
        assert after["credit_balance_cents"] == 300000


class TestSaleOcc:
    def test_occ_sell_stale_distributor_version(self, api):
        """PRD §2.9: "A purchase request — the distributor-facing engine sale
        — must carry `expected_distributor_version`, set to the buying
        distributor's `version` as last observed by the client. If the
        distributor's current `version` differs, the sale is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "The allocation selector picks from the pool of engines in
        `SEALED` status under the requested spec, choosing the one with the
        earliest `sealed_at`, breaking ties by earliest `created_at`."

        Design: Corner/cross_cutting_layers/occ_sell_stale_distributor_version
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRCC",
                                         name="Core Source C")
        buyer = create_distributor(distributor_code="D-V", name="Version Buyer",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="CORVETTE-1995")
        ctx1 = produce_sealed_engine(spec, core_source, slot=0)
        ctx2 = produce_sealed_engine(spec, core_source, slot=1)
        observed = get_distributor(buyer["id"])["version"]

        first = validate_success(api.sell_reman_engine(
            sell_engine_payload(spec["id"], observed),
            make_distributor_headers(buyer["id"])), 200)
        assert first["id"] == ctx1["engine"]["id"], "oldest sealed sells first"
        assert first["status"] == "SOLD"

        resp = api.sell_reman_engine(
            sell_engine_payload(spec["id"], observed),
            make_distributor_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_distributor(buyer["id"])
        assert fresh["version"] == observed + 1, (
            "the first sale incremented the distributor version")

        second = validate_success(api.sell_reman_engine(
            sell_engine_payload(spec["id"], fresh["version"]),
            make_distributor_headers(buyer["id"])), 200)
        assert second["id"] == ctx2["engine"]["id"], (
            "retry with the fresh version sells the next sealed engine")
