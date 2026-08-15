"""Private-label contracts: tiered pricing at activation, per-run
minimums at scheduling and completion, fulfillment bubble-up, and the
temporal-beats-fiscal priority pair.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    create_active_contract,
    create_active_recipe,
    create_contract,
    create_run,
    create_run_payload,
    get_contract,
    set_clock,
    setup_released_batch_with_line,
    start_run,
    validate_error,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


def test_pricing_tier_edges(api):
    """PRD §3.8: "Volume earns an average-rate discount applied to the
    whole price rather than marginally, read from `contracted_total_units`
    with inclusive tier boundaries: at least 10,000 units takes 5 percent
    off, at least 50,000 takes 10 percent, and at least 100,000 takes 15
    percent — exactly 10,000 units already earns the 5 percent tier."

    Base 200 cents, CONVENTIONAL recipe: 9999 units earns no tier (200);
    exactly 10000 earns 5 percent (round_half_up(200 * 0.95) = 190).

    Design: Corner/calculations/pricing_tier_edges
    """
    recipe = create_active_recipe(name="RT")
    below = create_contract(recipe["id"], customer_name="Edge A",
                            minimum_units_per_run=100,
                            contracted_total_units=9999,
                            base_unit_price_cents=200)
    at = create_contract(recipe["id"], customer_name="Edge B",
                         minimum_units_per_run=100,
                         contracted_total_units=10000,
                         base_unit_price_cents=200)
    priced_below = activate_contract(below["id"])
    priced_at = activate_contract(at["id"])
    assert priced_below["contract_unit_price_cents"] == 200
    assert priced_at["contract_unit_price_cents"] == 190


class TestPriceTierMultiplierFloor:
    def test_organic_top_tier_price(self, api):
        """PRD §3.8: "at least 100,000 takes 15 percent"
        PRD §3.8: "Certification multiplies the price: 1.20 for an
        `ORGANIC` recipe, 1.10 for `FAIR_TRADE`, and 1.00 otherwise."
        PRD §3.8: "The unit price is the `base_unit_price_cents`
        multiplied by the certification multiplier and by one minus the
        discount, rounded half-up to whole cents, and finally floored at
        the one-cent minimum — the greater of the rounded value and one
        cent wins."
        PRD §3.8: "Activation moves the contract from `DRAFT` to
        `ACTIVE`."

        max(1, round_half_up(250 * 1.20 * 0.85)) = 255.

        Design: Difficulty/combinatorial_formula/contract_price_tier_multiplier_floor
        """
        recipe = create_active_recipe(name="R3",
                                      certification_target="ORGANIC")
        contract = create_contract(recipe["id"], customer_name="Acme Foods",
                                   minimum_units_per_run=500,
                                   contracted_total_units=120000,
                                   base_unit_price_cents=250)
        activated = activate_contract(contract["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["contract_unit_price_cents"] == 255

    def test_fair_trade_mid_tier_price(self, api):
        """PRD §3.8: "Volume earns an average-rate discount applied to
        the whole price rather than marginally, read from
        `contracted_total_units` with inclusive tier boundaries: at least
        10,000 units takes 5 percent off, at least 50,000 takes 10
        percent, and at least 100,000 takes 15 percent"
        PRD §3.8: "Certification multiplies the price: 1.20 for an
        `ORGANIC` recipe, 1.10 for `FAIR_TRADE`, and 1.00 otherwise."

        A second input combination through the same formula:
        round_half_up(300 * 1.10 * 0.90) = 297.

        Design: Difficulty/combinatorial_formula/contract_price_tier_multiplier_floor
        """
        recipe = create_active_recipe(name="R3-FT",
                                      certification_target="FAIR_TRADE")
        contract = create_contract(recipe["id"], customer_name="Fair Mart",
                                   minimum_units_per_run=500,
                                   contracted_total_units=50000,
                                   base_unit_price_cents=300)
        activated = activate_contract(contract["id"])
        assert activated["contract_unit_price_cents"] == 297


class TestPrivateLabelMinimumBoundary:
    def _scenario(self):
        """RELEASED batch + LOOSE_PACK line + ACTIVE contract
        (min 1000, total 100000, base 200); run1 booked 08:00-09:00 with
        1000 planned units, started with the clock at 08:30."""
        ctx = setup_released_batch_with_line(line_name="LP-3")
        contract = create_active_contract(
            ctx["recipe"]["id"], customer_name="Gamma Mart",
            minimum_units_per_run=1000, contracted_total_units=100000,
            base_unit_price_cents=200)
        run1 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                          "2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z",
                          1000, contract_id=contract["id"])
        set_clock("2026-08-05T08:30:00Z")
        start_run(run1["id"])
        return ctx, contract, run1

    def test_exactly_at_minimum_completes(self, api):
        """PRD §3.7: "Completion reports the `actual_units` produced —
        at least one, and at least the contract's per-run minimum when
        the run is contracted, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET`"
        PRD §3.8: "Each completion credits the contract's
        `fulfilled_units` with the run's `actual_units`"

        actual_units exactly equal to the 1000-unit minimum completes
        and credits 1000.

        Design: Difficulty/boundary_precision_check/private_label_minimum_exact_vs_one_below
        """
        _, contract, run1 = self._scenario()
        completed = validate_success(
            api.complete_run(run1["id"], {"actual_units": 1000}, PP), 200)
        assert completed["status"] == "COMPLETED"
        assert get_contract(contract["id"])["fulfilled_units"] == 1000

    def test_one_below_minimum_rejected(self, api):
        """PRD §3.8: "Both the `planned_units` given at scheduling and
        the `actual_units` reported at completion must reach the
        contract's `minimum_units_per_run`, else
        `ERR_PRIVATE_LABEL_MINIMUM_UNMET`."

        999 is one below the 1000-unit floor: the completion fails, the
        run stays IN_PROGRESS, and the contract ledger credits nothing
        for it.

        Design: Difficulty/boundary_precision_check/private_label_minimum_exact_vs_one_below
        """
        ctx, contract, run1 = self._scenario()
        validate_success(
            api.complete_run(run1["id"], {"actual_units": 1000}, PP), 200)
        run2 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                          "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z",
                          1000, contract_id=contract["id"])
        set_clock("2026-08-05T10:30:00Z")
        start_run(run2["id"])

        res = api.complete_run(run2["id"], {"actual_units": 999}, PP)
        validate_error(res, ApiErrorId.ERR_PRIVATE_LABEL_MINIMUM_UNMET)
        run2_after = validate_success(api.get_run(run2["id"], PP), 200)
        assert run2_after["status"] == "IN_PROGRESS"
        assert get_contract(contract["id"])["fulfilled_units"] == 1000, (
            "failed completion credits nothing")


def test_contract_fulfilled_bubble_up(api):
    """PRD §3.8: "Each completion credits the contract's
    `fulfilled_units` with the run's `actual_units`, and the moment the
    accumulated total reaches or exceeds the `contracted_total_units`,
    the contract promotes itself from `ACTIVE` to `FULFILLED`."

    1000 + 500 reaches the contracted 1500 exactly (inclusive boundary).

    Design: Corner/state_machines/contract_fulfilled_bubble_up
    """
    ctx = setup_released_batch_with_line(line_name="LP-B")
    contract = create_active_contract(
        ctx["recipe"]["id"], customer_name="Delta Mart",
        minimum_units_per_run=500, contracted_total_units=1500,
        base_unit_price_cents=200)
    run1 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                      "2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z", 1000,
                      contract_id=contract["id"])
    run2 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                      "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", 500,
                      contract_id=contract["id"])
    set_clock("2026-08-05T08:30:00Z")
    start_run(run1["id"])
    validate_success(api.complete_run(run1["id"], {"actual_units": 1000}, PP),
                     200)
    set_clock("2026-08-05T09:30:00Z")
    start_run(run2["id"])
    validate_success(api.complete_run(run2["id"], {"actual_units": 500}, PP),
                     200)

    after = get_contract(contract["id"])
    assert after["fulfilled_units"] == 1500
    assert after["status"] == "FULFILLED", "1500 >= 1500 is inclusive"


class TestTemporalBeatsFiscal:
    def _scenario(self):
        """RELEASED batch + line + ACTIVE contract (min 1000, total
        50000, base 300); run1 booked 08:00-10:00 with 1500 planned
        units under the contract."""
        ctx = setup_released_batch_with_line(line_name="LP-2")
        contract = create_active_contract(
            ctx["recipe"]["id"], customer_name="Beta Retail",
            minimum_units_per_run=1000, contracted_total_units=50000,
            base_unit_price_cents=300)
        create_run(ctx["line"]["id"], ctx["batch"]["id"],
                   "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z", 1500,
                   contract_id=contract["id"])
        return ctx, contract

    def test_overlap_masks_below_minimum(self, api):
        """PRD §2.10: "Every request is checked against the following
        sequence, and the first failure encountered wins — later checks
        never mask an earlier rejection"
        PRD §2.10: "9. Temporal checks — window validity, line overlap,
        the allergen changeover buffer, and certificate overlap —
        reported as `ERR_INVALID_WINDOW`, `ERR_LINE_WINDOW_CONFLICT`,
        `ERR_ALLERGEN_CHANGEOVER_BUFFER`, or `ERR_CERT_WINDOW_CONFLICT`."
        PRD §2.10: "12. Private-label run minimums at run scheduling and
        completion, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET`."

        One request that both overlaps an existing window (09:00-11:00
        vs booked 08:00-10:00) and under-runs the contract minimum (800
        < 1000) must surface the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_run_create
        """
        ctx, contract = self._scenario()
        res = api.create_run(
            create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                               "2026-08-05T09:00:00Z",
                               "2026-08-05T11:00:00Z", 800,
                               contract_id=contract["id"]), PP)
        validate_error(res, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)

    def test_below_minimum_alone_reports_fiscal_error(self, api):
        """PRD §3.8: "Both the `planned_units` given at scheduling and
        the `actual_units` reported at completion must reach the
        contract's `minimum_units_per_run`, else
        `ERR_PRIVATE_LABEL_MINIMUM_UNMET`."

        With no temporal violation in play (10:00-11:00 touches but does
        not intersect the booked 08:00-10:00), the same 800-unit request
        surfaces the fiscal rule the overlap masked in the paired test.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_run_create
        """
        ctx, contract = self._scenario()
        res = api.create_run(
            create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                               "2026-08-05T10:00:00Z",
                               "2026-08-05T11:00:00Z", 800,
                               contract_id=contract["id"]), PP)
        validate_error(res, ApiErrorId.ERR_PRIVATE_LABEL_MINIMUM_UNMET)
