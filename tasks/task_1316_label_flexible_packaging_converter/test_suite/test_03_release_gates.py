"""Release gates: material calculation, minimum order, food-contact component
safety, credit hold, artwork freshness, optimistic concurrency, and the fixed
validation order among them."""
from test_helpers import (
    EST,
    PREPRESS,
    api_client,
    approve_job,
    create_job_for,
    current_artwork_version,
    get_job,
    job_chain,
    release_job,
    setup_plant,
    validate_error,
    validate_success,
)


class TestMaterialCalculation:

    def test_material_ft_absent_until_release(self):
        """PRD §3.4: "At creation the job is `QUOTED`; `material_ft`,
        `good_quantity_produced` and `invoiced_price_cents` remain unset,
        `die_charge_applied_cents` starts at 0, and the system computes a
        provisional `quoted_price_cents` from four components."
        PRD §3.5: "At release the system computes and freezes the job's
        `material_ft` in three steps. First, the running footage:
        `quantity_ordered` multiplied by `repeat_length_mm` and divided by
        304.8 millimetres per foot, rounded up to a whole foot. Second, setup
        waste: when the running footage is below the short-run threshold of
        5,000 feet, the press's full `setup_waste_ft` is charged; when the
        running footage is 5,000 feet or more, makeready is considered
        amortized across the run and no separate setup waste is billed. Third,
        running waste: the running footage multiplied by the press's
        `run_waste_pct_numerator` and divided by 100, rounded up to a whole
        foot. The job's `material_ft` is the sum of running footage, setup
        waste and running waste, and it does not change afterwards."

        Design: Corner/calculations/material_ft_absent_until_release
        """
        chain = job_chain(stop_at="QUOTED", account_name="Derived Co",
                          artwork_code="AW-DV", substrate_code="DV-1",
                          recipe_code="INK-DV", die_code="D-DV",
                          press_code="P-DV", quantity_ordered=6000,
                          repeat_length_mm=76, rewind_max_rolls=3)
        job_id = chain["job"]["id"]
        pre = get_job(job_id)
        assert pre["material_ft"] is None, \
            "material_ft must remain unset until release"
        assert pre["status"] == "QUOTED"

        approve_job(job_id)
        release_job(job_id, current_artwork_version(chain["plant"]))
        post = get_job(job_id)
        # running ceil(6000*76/304.8)=1497 < 5000 -> setup 300;
        # waste ceil(1497*0.05)=75 -> 1497+300+75
        assert post["material_ft"] == 1872

    def test_material_calc_short_run_bills_setup_waste(self):
        """PRD §3.5: "Second, setup waste: when the running footage is below
        the short-run threshold of 5,000 feet, the press's full
        `setup_waste_ft` is charged; when the running footage is 5,000 feet or
        more, makeready is considered amortized across the run and no separate
        setup waste is billed. Third, running waste: the running footage
        multiplied by the press's `run_waste_pct_numerator` and divided by 100,
        rounded up to a whole foot. The job's `material_ft` is the sum of
        running footage, setup waste and running waste, and it does not change
        afterwards."

        Design: Difficulty/combinatorial_formula/material_calc_short_vs_long_run_branching
        """
        chain = job_chain(stop_at="RELEASED", account_name="Combo Short",
                          artwork_code="AW-3S", substrate_code="PE-90S",
                          recipe_code="INK-3S", die_code="D-3S",
                          press_code="P-3S", station_count=6,
                          quantity_ordered=6000, repeat_length_mm=76,
                          rewind_max_rolls=3)
        job = chain["job"]
        assert job["status"] == "RELEASED"
        # running ceil(6000*76/304.8)=1497 < 5000 -> setup billed
        assert job["material_ft"] == 1872

    def test_material_calc_long_run_waives_setup_waste(self):
        """PRD §3.5: "Second, setup waste: when the running footage is below
        the short-run threshold of 5,000 feet, the press's full
        `setup_waste_ft` is charged; when the running footage is 5,000 feet or
        more, makeready is considered amortized across the run and no separate
        setup waste is billed. Third, running waste: the running footage
        multiplied by the press's `run_waste_pct_numerator` and divided by 100,
        rounded up to a whole foot. The job's `material_ft` is the sum of
        running footage, setup waste and running waste, and it does not change
        afterwards."

        Design: Difficulty/combinatorial_formula/material_calc_short_vs_long_run_branching
        """
        chain = job_chain(stop_at="RELEASED", account_name="Combo Long",
                          artwork_code="AW-3L", substrate_code="PE-90L",
                          recipe_code="INK-3L", die_code="D-3L",
                          press_code="P-3L", station_count=6,
                          quantity_ordered=60000, repeat_length_mm=76,
                          rewind_max_rolls=9)
        job = chain["job"]
        assert job["status"] == "RELEASED"
        # running ceil(60000*76/304.8)=14961 >= 5000 -> setup waived;
        # waste ceil(14961*0.05)=749 -> 14961+0+749
        assert job["material_ft"] == 15710


class TestMinimumOrder:

    def test_release_at_exactly_minimum_order_succeeds(self):
        """PRD §3.5: "The `quantity_ordered` must be at least the minimum order
        quantity of 1,000 labels (`ERR_BELOW_MINIMUM_ORDER`)."

        Design: Difficulty/boundary_precision_check/minimum_order_exactly_1000_releases
        """
        chain = job_chain(stop_at="APPROVED", account_name="MinOrder OK",
                          artwork_code="AW-12A", substrate_code="BOPP-36A",
                          recipe_code="INK-12A", die_code="D-12A",
                          press_code="P-12A", quantity_ordered=1000,
                          repeat_length_mm=76)
        released = release_job(chain["job"]["id"],
                               current_artwork_version(chain["plant"]))
        assert released["status"] == "RELEASED", \
            "1000 >= 1000 must pass the minimum-order gate"

    def test_release_one_below_minimum_order_rejected(self):
        """PRD §3.5: "The `quantity_ordered` must be at least the minimum order
        quantity of 1,000 labels (`ERR_BELOW_MINIMUM_ORDER`)."

        Design: Difficulty/boundary_precision_check/minimum_order_exactly_1000_releases
        """
        chain = job_chain(stop_at="APPROVED", account_name="MinOrder Bad",
                          artwork_code="AW-12B", substrate_code="BOPP-36B",
                          recipe_code="INK-12B", die_code="D-12B",
                          press_code="P-12B", quantity_ordered=999,
                          repeat_length_mm=76)
        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version":
             current_artwork_version(chain["plant"])},
            EST)
        validate_error(resp, "ERR_BELOW_MINIMUM_ORDER", expected_status=422)
        assert get_job(chain["job"]["id"])["status"] == "APPROVED", \
            "rejected release must leave the job APPROVED"


class TestArtworkFreshnessGate:

    def test_release_blocked_while_artwork_only_submitted(self):
        """PRD §3.5: "The referenced artwork revision must be `APPROVED`
        (`ERR_ARTWORK_NOT_APPROVED`)."

        Design: Difficulty/cross_entity_state_dependency/job_release_depends_on_artwork_approved_state
        """
        chain = job_chain(stop_at="APPROVED", account_name="CrossDep A",
                          artwork_code="AW-13", approve_artwork=False,
                          substrate_code="BOPP-37", recipe_code="INK-13",
                          die_code="D-13", press_code="P-13",
                          quantity_ordered=2000, repeat_length_mm=76)
        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version":
             current_artwork_version(chain["plant"])},
            EST)
        validate_error(resp, "ERR_ARTWORK_NOT_APPROVED", expected_status=422)

    def test_release_unblocks_once_artwork_approved(self):
        """PRD §3.5: "The referenced artwork revision must be `APPROVED`
        (`ERR_ARTWORK_NOT_APPROVED`)."
        PRD §3.5: "The job itself moves `APPROVED` → `RELEASED`, its `version`
        incrementing as on every mutation."

        Design: Difficulty/cross_entity_state_dependency/job_release_depends_on_artwork_approved_state
        """
        chain = job_chain(stop_at="APPROVED", account_name="CrossDep A2",
                          artwork_code="AW-13B", approve_artwork=False,
                          substrate_code="BOPP-37B", recipe_code="INK-13B",
                          die_code="D-13B", press_code="P-13B",
                          quantity_ordered=2000, repeat_length_mm=76)
        plant = chain["plant"]
        pre = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version": current_artwork_version(plant)}, EST)
        validate_error(pre, "ERR_ARTWORK_NOT_APPROVED", expected_status=422)

        validate_success(api_client.approve_artwork(
            plant["customer"]["id"], plant["artwork"]["id"], PREPRESS))
        released = release_job(chain["job"]["id"],
                               current_artwork_version(plant))
        assert released["status"] == "RELEASED"


class TestFoodContactComponentGate:

    def test_food_contact_release_with_unqualified_components_rejected(self):
        """PRD §3.5: "And when the job's `requires_food_contact_letter` is
        true, both the substrate's `food_contact_certified` and the ink
        recipe's `food_contact_compliant` must be true
        (`ERR_FOOD_CONTACT_COMPONENT`)."
        PRD §3.1: "These two flags resurface later as hard gates: a job
        flagged for food-contact work can be released, and its compliance
        letter issued, only when both components are qualified."

        Design: Corner/validations/food_contact_release_with_unqualified_components_rejected
        """
        chain = job_chain(stop_at="APPROVED", account_name="FoodSafe Co",
                          artwork_code="AW-FC", substrate_code="NFC-1",
                          substrate_food_certified=False,
                          recipe_code="INK-FC", ink_food_compliant=True,
                          die_code="D-FC", press_code="P-FC",
                          quantity_ordered=2000, repeat_length_mm=76,
                          requires_food_contact_letter=True)
        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version":
             current_artwork_version(chain["plant"])},
            EST)
        validate_error(resp, "ERR_FOOD_CONTACT_COMPONENT", expected_status=422)
        assert get_job(chain["job"]["id"])["status"] == "APPROVED"

    def test_credit_hold_release_rejected(self):
        """PRD §3.5: "The customer must not be on credit hold
        (`ERR_CUSTOMER_CREDIT_HOLD`)."
        PRD §3.1: "Two optional attributes complete the account: `credit_hold`
        (default false) marks accounts that must not release new work to press,
        and `preferred_currency` (default `USD`) records the billing currency
        code."

        Design: Corner/validations/credit_hold_release_rejected
        """
        chain = job_chain(stop_at="APPROVED", account_name="Hold Co",
                          artwork_code="AW-H", substrate_code="H-1",
                          recipe_code="INK-H", die_code="D-H",
                          press_code="P-H", quantity_ordered=2000,
                          repeat_length_mm=76)
        plant = chain["plant"]
        validate_success(api_client.patch_customer(
            plant["customer"]["id"], {"credit_hold": True}, EST))

        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version": current_artwork_version(plant)}, EST)
        validate_error(resp, "ERR_CUSTOMER_CREDIT_HOLD", expected_status=422)


class TestReleaseValidationOrder:

    def test_state_error_beats_business_safety_on_release(self):
        """PRD §2.5: "5. **State admissibility.** The target resource must be
        in a state that permits the operation; violations surface as the
        state-specific errors `ERR_JOB_NOT_QUOTED`, `ERR_JOB_NOT_APPROVED`,
        `ERR_JOB_NOT_RELEASED`, `ERR_JOB_NOT_ON_PRESS`, `ERR_JOB_NOT_PRINTED`,
        `ERR_JOB_NOT_REWOUND`, `ERR_JOB_NOT_CANCELLABLE`,
        `ERR_ARTWORK_NOT_DRAFT`, `ERR_ARTWORK_NOT_SUBMITTED`,
        `ERR_MEASUREMENT_ALREADY_JUDGED` or `ERR_ROLL_ALREADY_JUDGED`."
        PRD §2.5: "6. **Business rules**, evaluated in this order: food-contact
        component safety, then color approval, then press occupancy and station
        capacity, then structural limits (roll counts, splice tolerance,
        revision monotonicity), then referential freshness (approved artwork,
        active die), then the fiscal gates (minimum order, credit hold), and
        last of all optimistic concurrency — a stale expected-version value
        surfaces as `ERR_STALE_VERSION` only after every other applicable check
        has passed."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_business_safety_on_release
        """
        chain = job_chain(stop_at="QUOTED", account_name="Prio One",
                          artwork_code="AW-9", substrate_code="PLAIN-1",
                          substrate_food_certified=False,
                          recipe_code="INK-9", ink_food_compliant=False,
                          die_code="D-9", press_code="P-9",
                          quantity_ordered=2000, repeat_length_mm=76,
                          requires_food_contact_letter=True)
        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version":
             current_artwork_version(chain["plant"])},
            EST)
        validate_error(resp, "ERR_JOB_NOT_APPROVED", expected_status=409)

    def test_food_contact_error_surfaces_once_state_passes(self):
        """PRD §3.5: "Release is the commercial point of no return, and the
        `Estimator` who releases a job must clear five gates. The job must be
        `APPROVED` (`ERR_JOB_NOT_APPROVED`). The customer must not be on credit
        hold (`ERR_CUSTOMER_CREDIT_HOLD`). The `quantity_ordered` must be at
        least the minimum order quantity of 1,000 labels
        (`ERR_BELOW_MINIMUM_ORDER`). The referenced artwork revision must be
        `APPROVED` (`ERR_ARTWORK_NOT_APPROVED`). And when the job's
        `requires_food_contact_letter` is true, both the substrate's
        `food_contact_certified` and the ink recipe's `food_contact_compliant`
        must be true (`ERR_FOOD_CONTACT_COMPONENT`)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_business_safety_on_release
        """
        chain = job_chain(stop_at="APPROVED", account_name="Prio One B",
                          artwork_code="AW-9B", substrate_code="PLAIN-1B",
                          substrate_food_certified=False,
                          recipe_code="INK-9B", ink_food_compliant=False,
                          die_code="D-9B", press_code="P-9B",
                          quantity_ordered=2000, repeat_length_mm=76,
                          requires_food_contact_letter=True)
        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version":
             current_artwork_version(chain["plant"])},
            EST)
        # With the job APPROVED, the state gate passes and the food-contact
        # component gate is the surviving violation.
        validate_error(resp, "ERR_FOOD_CONTACT_COMPONENT", expected_status=422)
        assert get_job(chain["job"]["id"])["status"] == "APPROVED"

    def test_referential_artwork_error_beats_fiscal_credit_hold(self):
        """PRD §2.5: "6. **Business rules**, evaluated in this order:
        food-contact component safety, then color approval, then press
        occupancy and station capacity, then structural limits (roll counts,
        splice tolerance, revision monotonicity), then referential freshness
        (approved artwork, active die), then the fiscal gates (minimum order,
        credit hold), and last of all optimistic concurrency — a stale
        expected-version value surfaces as `ERR_STALE_VERSION` only after every
        other applicable check has passed."
        PRD §3.5: "The customer must not be on credit hold
        (`ERR_CUSTOMER_CREDIT_HOLD`). The `quantity_ordered` must be at least
        the minimum order quantity of 1,000 labels (`ERR_BELOW_MINIMUM_ORDER`).
        The referenced artwork revision must be `APPROVED`
        (`ERR_ARTWORK_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_artwork_error_beats_fiscal_credit_hold
        """
        chain = job_chain(stop_at="APPROVED", account_name="Prio Two",
                          artwork_code="AW-10", approve_artwork=False,
                          substrate_code="PLAIN-2", recipe_code="INK-10",
                          die_code="D-10", press_code="P-10",
                          quantity_ordered=2000, repeat_length_mm=76)
        plant = chain["plant"]
        validate_success(api_client.patch_customer(
            plant["customer"]["id"], {"credit_hold": True}, EST))

        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version": current_artwork_version(plant)}, EST)
        # Referential freshness (artwork not APPROVED) outranks the fiscal
        # credit-hold gate even though both are violated.
        validate_error(resp, "ERR_ARTWORK_NOT_APPROVED", expected_status=422)

    def test_fiscal_gate_fires_once_referential_violation_cleared(self):
        """PRD §2.5: "6. **Business rules**, evaluated in this order:
        food-contact component safety, then color approval, then press
        occupancy and station capacity, then structural limits (roll counts,
        splice tolerance, revision monotonicity), then referential freshness
        (approved artwork, active die), then the fiscal gates (minimum order,
        credit hold), and last of all optimistic concurrency — a stale
        expected-version value surfaces as `ERR_STALE_VERSION` only after every
        other applicable check has passed."
        PRD §3.5: "The customer must not be on credit hold
        (`ERR_CUSTOMER_CREDIT_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_artwork_error_beats_fiscal_credit_hold
        """
        chain = job_chain(stop_at="APPROVED", account_name="Prio Two B",
                          artwork_code="AW-10B", approve_artwork=False,
                          substrate_code="PLAIN-2B", recipe_code="INK-10B",
                          die_code="D-10B", press_code="P-10B",
                          quantity_ordered=2000, repeat_length_mm=76)
        plant = chain["plant"]
        validate_success(api_client.patch_customer(
            plant["customer"]["id"], {"credit_hold": True}, EST))
        validate_success(api_client.approve_artwork(
            plant["customer"]["id"], plant["artwork"]["id"], PREPRESS))

        resp = api_client.release_job(
            chain["job"]["id"],
            {"expected_artwork_version": current_artwork_version(plant)}, EST)
        # Artwork now APPROVED: the referential check passes and the fiscal
        # credit-hold gate reports its own violation.
        validate_error(resp, "ERR_CUSTOMER_CREDIT_HOLD", expected_status=422)


class TestReleaseOptimisticConcurrency:

    def test_release_with_stale_artwork_version_returns_412(self):
        """PRD §2.8: "**Releasing a job** requires the request body to carry
        `expected_artwork_version`, holding the `version` of the referenced
        artwork revision as the client last observed it. If the revision's
        current `version` has advanced since — for example because a newer
        revision of the same artwork code was approved in the meantime — the
        release is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/release_with_stale_artwork_version_returns_412
        """
        plant = setup_plant(account_name="OCC Rel Co", artwork_code="AW-OR",
                            approve_artwork=False, submit_artwork=False,
                            substrate_code="OR-1", recipe_code="INK-OR",
                            die_code="D-OR", press_code="P-OR")
        stale_version = plant["artwork"]["version"]  # observed at DRAFT
        validate_success(api_client.submit_artwork(
            plant["customer"]["id"], plant["artwork"]["id"], PREPRESS))
        validate_success(api_client.approve_artwork(
            plant["customer"]["id"], plant["artwork"]["id"], PREPRESS))

        job = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        approve_job(job["id"])

        resp = api_client.release_job(
            job["id"], {"expected_artwork_version": stale_version}, EST)
        validate_error(resp, "ERR_STALE_VERSION", expected_status=412)
        assert get_job(job["id"])["status"] == "APPROVED", \
            "stale-version rejection must leave the job APPROVED"
