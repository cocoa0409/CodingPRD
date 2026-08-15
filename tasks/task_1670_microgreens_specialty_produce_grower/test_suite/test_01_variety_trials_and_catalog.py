"""Variety catalog lifecycle: trial stage, chef-panel decisions, the RETRIAL
revision loop, adoption thresholds, and retirement with open demand."""
from test_helpers import (
    ApiErrorId,
    assert_variety,
    create_customer,
    create_listed_variety,
    create_standing_order,
    add_order_line,
    confirm_standing_order,
    create_variety,
    decide_trial,
    open_trial,
    record_panel,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import GROWER


class TestVarietyCreation:
    def test_variety_created_in_trial_stage(self, api):
        """PRD §3.1: "A new variety enters in `stage` `TRIAL`: it exists, but it
        is not yet orderable."

        Design: Corner/entities/variety_creation_initial_stage_trial
        """
        resp = api.create_variety(
            {
                "name": "Popcorn Shoots",
                "crop_category": "MICROGREEN",
                "days_to_harvest": 9,
                "expected_yield_grams_per_tray": 12000,
                "listed_price_cents_per_kg": 1500,
                "min_order_grams": 100,
            },
            GROWER,
        )
        variety = validate_success(resp, 201)
        assert_variety(variety)
        assert variety["stage"] == "TRIAL", "A new variety enters in stage TRIAL"

        fetched = validate_success(api.get_variety(variety["id"], GROWER))
        assert fetched["stage"] == "TRIAL"


class TestRetrialCycle:
    def test_retrial_decision_rejects_trial_and_returns_variety_to_trial(self, api):
        """PRD §3.1: "With `outcome` set to `RETRIAL`, the trial's `decision`
        becomes `REJECTED` and the variety falls back from `EVALUATION` to
        `TRIAL`, a revision loop in which the grower may open a fresh trial for
        the same variety."

        Design: Difficulty/non_linear_state_machine/variety_trial_evaluation_retrial_cycle
        """
        variety = create_variety(name="Shiso", crop_category="SPECIALTY_HERB",
                                 days_to_harvest=25,
                                 expected_yield_grams_per_tray=3000,
                                 listed_price_cents_per_kg=4000, min_order_grams=100)
        trial = open_trial(variety["id"], yield_score=4.0)
        record_panel(trial["id"], [5.0])
        # Panel scores in: variety is now EVALUATION, trial still PENDING.
        evaluated = validate_success(api.get_variety(variety["id"], GROWER))
        assert evaluated["stage"] == "EVALUATION"

        decided = validate_success(api.decide_trial(trial["id"], "RETRIAL", GROWER))
        assert decided["decision"] == "REJECTED", (
            "RETRIAL sets the trial's decision to REJECTED")

        after = validate_success(api.get_variety(variety["id"], GROWER))
        assert after["stage"] == "TRIAL", (
            "RETRIAL loops the variety back from EVALUATION to TRIAL")

    def test_variety_can_be_re_trialed_and_adopted_after_retrial(self, api):
        """PRD §3.1: "With `outcome` set to `RETRIAL`, the trial's `decision`
        becomes `REJECTED` and the variety falls back from `EVALUATION` to
        `TRIAL`, a revision loop in which the grower may open a fresh trial for
        the same variety."
        PRD §3.1: "A successful adoption sets the trial's `decision` to
        `ADOPTED` and moves the variety from `EVALUATION` to `LISTED`, at which
        point chefs may put it on standing orders."

        Design: Difficulty/non_linear_state_machine/variety_trial_evaluation_retrial_cycle
        """
        variety = create_variety(name="Shiso Rex", crop_category="SPECIALTY_HERB",
                                 days_to_harvest=25,
                                 expected_yield_grams_per_tray=3000,
                                 listed_price_cents_per_kg=4000, min_order_grams=100)
        trial1 = open_trial(variety["id"], yield_score=4.0)
        record_panel(trial1["id"], [5.0])
        decide_trial(trial1["id"], "RETRIAL")

        # The revision loop: a fresh trial on the same variety, then adoption.
        trial2 = open_trial(variety["id"], yield_score=8.0)
        record_panel(trial2["id"], [8.0])
        adopted = validate_success(api.decide_trial(trial2["id"], "ADOPT", GROWER))
        assert adopted["decision"] == "ADOPTED"

        listed = validate_success(api.get_variety(variety["id"], GROWER))
        assert listed["stage"] == "LISTED", (
            "A re-trialed variety can still reach LISTED via ADOPT")


class TestAdoptionCriteria:
    def test_adopt_below_flavor_threshold_rejected(self, api):
        """PRD §3.1: "With `outcome` set to `ADOPT`, the variety is promoted
        only if its `avg_flavor_score` is at least 6.0 and its `yield_score` is
        at least 5.0 — an adoption attempted against weaker numbers is rejected
        with `ERR_TRIAL_CRITERIA_NOT_MET`."

        Design: Corner/validations/trial_adopt_below_threshold_rejected
        """
        variety = create_variety(name="Lovage", crop_category="SPECIALTY_HERB",
                                 days_to_harvest=28,
                                 expected_yield_grams_per_tray=3000,
                                 listed_price_cents_per_kg=3000, min_order_grams=100)
        trial = open_trial(variety["id"], yield_score=6.0)
        record_panel(trial["id"], [5.0])  # avg_flavor_score 5.0 < 6.0

        resp = api.decide_trial(trial["id"], "ADOPT", GROWER)
        validate_error(resp, ApiErrorId.ERR_TRIAL_CRITERIA_NOT_MET)

        after = validate_success(api.get_variety(variety["id"], GROWER))
        assert after["stage"] == "EVALUATION", (
            "A rejected adoption leaves the variety in EVALUATION")
        trial_after = validate_success(api.get_variety_trial(trial["id"], GROWER))
        assert trial_after["decision"] == "PENDING"


class TestVarietyRetirement:
    def test_retire_listed_variety_with_open_demand_rejected(self, api):
        """PRD §3.1: "Retirement moves it from `LISTED` to the terminal
        `RETIRED` stage, but only while no order line whose `fulfillment` is
        `PLANNED` or `ALLOCATED` still references it; if open demand exists, the
        retire is rejected with `ERR_VARIETY_IN_USE`."

        Design: Corner/state_machines/variety_retire_blocked_when_in_use
        """
        variety = create_listed_variety(name="Chive",
                                        crop_category="SPECIALTY_HERB",
                                        days_to_harvest=20,
                                        expected_yield_grams_per_tray=4000,
                                        listed_price_cents_per_kg=2400,
                                        min_order_grams=100)
        customer = create_customer(business_name="R4")
        order = create_standing_order(customer)
        add_order_line(order["id"], customer, variety["id"], 1.0)
        confirm_standing_order(order["id"], customer)

        resp = api.retire_variety(variety["id"], GROWER)
        validate_error(resp, ApiErrorId.ERR_VARIETY_IN_USE)

        after = validate_success(api.get_variety(variety["id"], GROWER))
        assert after["stage"] == "LISTED", "A blocked retire leaves the variety LISTED"
