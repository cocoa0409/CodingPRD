"""Point-of-service meals: offer-vs-serve, a-la-carte tax, guards, and voiding."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_site, create_food_items, create_food_item, create_approved_lunch_menu,
    create_planned_production, create_prepared_production, setup_prepared_lunch_site,
    create_student, create_funded_student, record_meal,
    create_meal_transaction_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["pos_clerk_headers"]

REIMBURSABLE = ["MEAT_MEAT_ALT", "GRAINS", "FRUIT"]


# ==========================================================================
# Combinatorial formula: a-la-carte tax rounded per line, then summed
# ==========================================================================
class TestAlaCartePerLineRounding:
    def test_two_lines_tax_rounded_per_line_then_summed(self, api):
        """PRD §3.6: "For each line — carrying a `food_item_id`, a `qty`, and a `unit_price_cents` — the base is `qty` multiplied by `unit_price_cents`, the line tax is that base multiplied by the site's `sales_tax_bps` divided by 10000 and then rounded half-up to whole cents, and the line total is the base plus the rounded tax."
        PRD §3.6: "The tax must be rounded to whole cents on each line first and the rounded line totals summed afterward; summing the raw bases and rounding the aggregate once is explicitly not used and generally yields a different result."

        Two lines of base 100 at 725 bps: round(7.25)=7 per line -> 200+7+7=214
        (sum-then-round would give 200+round(14.5)=215).

        Design: Difficulty/combinatorial_formula/alacarte_per_line_round_then_sum
        """
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"sales_tax_bps": 725, "negative_balance_allowed": True})
        snack = create_food_item(api, name="Baked Chips", category="SNACK", calories=120,
                                 sat_fat_g=0.5, sodium_mg=140, total_sugar_g=1, weight_g=28)
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=REIMBURSABLE,
                         a_la_carte_lines=[{"food_item_id": snack["id"], "qty": 1, "unit_price_cents": 100},
                                           {"food_item_id": snack["id"], "qty": 1, "unit_price_cents": 100}])
        assert mt["alacarte_total_cents"] == 214, f"expected 214, got {mt['alacarte_total_cents']}"

    def test_per_line_rounding_diverges_from_aggregate_rounding(self, api):
        """PRD §3.6: "The tax must be rounded to whole cents on each line first and the rounded line totals summed afterward; summing the raw bases and rounding the aggregate once is explicitly not used and generally yields a different result."

        Two lines of base 100 at 250 bps: round(2.5)=3 per line -> 200+3+3=206
        (sum-then-round would give 200+round(5.0)=205).

        Design: Difficulty/combinatorial_formula/alacarte_per_line_round_then_sum
        """
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"sales_tax_bps": 250, "negative_balance_allowed": True})
        snack = create_food_item(api, name="Baked Chips", category="SNACK", calories=120,
                                 sat_fat_g=0.5, sodium_mg=140, total_sugar_g=1, weight_g=28)
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=REIMBURSABLE,
                         a_la_carte_lines=[{"food_item_id": snack["id"], "qty": 1, "unit_price_cents": 100},
                                           {"food_item_id": snack["id"], "qty": 1, "unit_price_cents": 100}])
        assert mt["alacarte_total_cents"] == 206, f"expected 206, got {mt['alacarte_total_cents']}"


# ==========================================================================
# Boundary precision: offer-vs-serve minimum of three components
# ==========================================================================
class TestOfferVsServeBoundary:
    def test_exactly_three_components_with_fruit_is_reimbursable(self, api):
        """PRD §3.6: "A lunch meal is `REIMBURSABLE` when the number taken is at least 3 and it has a fruit-or-vegetable; a breakfast meal is `REIMBURSABLE` when the number taken is at least 3 and it has a fruit-or-vegetable."

        Design: Difficulty/boundary_precision_check/ovs_minimum_three_components_boundary
        """
        scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=["MEAT_MEAT_ALT", "GRAINS", "FRUIT"])
        assert mt["meal_claim_status"] == "REIMBURSABLE", f"got {mt['meal_claim_status']}"

    def test_three_components_without_fruit_or_veg_is_non_reimbursable(self, api):
        """PRD §3.6: "the meal has a fruit-or-vegetable when `selected_components` includes at least one of `FRUIT` or `VEGETABLE`."
        PRD §3.6: "A meal that fails offer-vs-serve is `NON_REIMBURSABLE`."

        Design: Difficulty/boundary_precision_check/ovs_minimum_three_components_boundary
        """
        scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        # 3 distinct components but none is FRUIT/VEGETABLE -> fails the fruit-or-veg rule.
        mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                         selected_components=["MEAT_MEAT_ALT", "GRAINS", "MILK"])
        assert mt["meal_claim_status"] == "NON_REIMBURSABLE", f"got {mt['meal_claim_status']}"


# ==========================================================================
# Priority pair: production-not-ready outranks insufficient-balance
# ==========================================================================
class TestProductionReadinessBeatsBalance:
    def _meal_on_planned_prod_zero_balance_no_negative_site(self, api):
        site = create_site(api, negative_balance_allowed=False, paid_lunch_price_cents=300)
        food_ids = create_food_items(api)
        mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
        pr = create_planned_production(api, site["id"], mc_id)  # left PLANNED
        student = create_student(api, site["id"], eligibility_category="PAID")  # balance 0
        payload = create_meal_transaction_payload(site["id"], student["id"], pr["id"],
                                                  selected_components=REIMBURSABLE)
        return api.create_meal_transaction(payload, CLERK)

    def test_planned_production_zero_balance_returns_production_not_ready(self, api):
        """PRD §3.6: "The linked production record must be `PREPARED`, else `ERR_PRODUCTION_NOT_READY` (409)."
        PRD §2.5: "a point-of-service meal evaluates its guards in this order: production readiness (`ERR_PRODUCTION_NOT_READY`), then Smart-Snacks compliance (`ERR_NOT_SMART_SNACK_COMPLIANT`), then student-site match (`ERR_STUDENT_SITE_MISMATCH`), then component validity (`ERR_INVALID_COMPONENT`), then the duplicate-reimbursable-meal check (`ERR_DUPLICATE_REIMBURSABLE_MEAL`), and finally the balance check (`ERR_INSUFFICIENT_BALANCE`)."

        Design: Difficulty/priority_pair_validation_conflict/production_not_ready_beats_insufficient_balance
        """
        resp = self._meal_on_planned_prod_zero_balance_no_negative_site(api)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_READY.value)

    def test_production_readiness_precedes_balance_status_409(self, api):
        """PRD §2.5: "a point-of-service meal evaluates its guards in this order: production readiness (`ERR_PRODUCTION_NOT_READY`), then Smart-Snacks compliance (`ERR_NOT_SMART_SNACK_COMPLIANT`), then student-site match (`ERR_STUDENT_SITE_MISMATCH`), then component validity (`ERR_INVALID_COMPONENT`), then the duplicate-reimbursable-meal check (`ERR_DUPLICATE_REIMBURSABLE_MEAL`), and finally the balance check (`ERR_INSUFFICIENT_BALANCE`)."

        Design: Difficulty/priority_pair_validation_conflict/production_not_ready_beats_insufficient_balance
        """
        resp = self._meal_on_planned_prod_zero_balance_no_negative_site(api)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
        # Must be the readiness error, not the balance error.
        body = resp.json()["data"]
        assert body["error_id"] == ApiErrorId.ERR_PRODUCTION_NOT_READY.value


# ==========================================================================
# Cross-entity state dependency: meal requires a PREPARED production record
# ==========================================================================
class TestMealRequiresPreparedProduction:
    def _meal_on_planned_production_funded_student(self, api):
        site = create_site(api, negative_balance_allowed=True)
        food_ids = create_food_items(api)
        mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
        pr = create_planned_production(api, site["id"], mc_id)  # PLANNED, not prepared
        student = create_funded_student(api, site["id"], eligibility_category="PAID")
        payload = create_meal_transaction_payload(site["id"], student["id"], pr["id"],
                                                  selected_components=REIMBURSABLE)
        return api.create_meal_transaction(payload, CLERK)

    def test_meal_against_planned_production_returns_production_not_ready(self, api):
        """PRD §3.6: "The linked production record must be `PREPARED`, else `ERR_PRODUCTION_NOT_READY` (409)."

        Design: Difficulty/cross_entity_state_dependency/meal_requires_production_prepared
        """
        resp = self._meal_on_planned_production_funded_student(api)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_READY.value)

    def test_meal_against_planned_production_status_409(self, api):
        """PRD §3.6: "The linked production record must be `PREPARED`, else `ERR_PRODUCTION_NOT_READY` (409)."

        Design: Difficulty/cross_entity_state_dependency/meal_requires_production_prepared
        """
        resp = self._meal_on_planned_production_funded_student(api)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_READY.value)


# ==========================================================================
# Resource temporal overlap (point occupancy): duplicate reimbursable meal
# ==========================================================================
class TestDuplicateReimbursableMeal:
    def _record_two_reimbursable_lunches_same_student_day(self, api):
        scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                    selected_components=REIMBURSABLE)  # first reimbursable lunch
        payload = create_meal_transaction_payload(scenario["site_id"], student["id"],
                                                  scenario["pr_id"], selected_components=REIMBURSABLE)
        return api.create_meal_transaction(payload, CLERK)

    def test_second_reimbursable_meal_same_day_rejected(self, api):
        """PRD §3.6: "Additionally, at most one `REIMBURSABLE` meal is allowed per student, service date, and meal type: a second reimbursable meal for that same combination is refused with `ERR_DUPLICATE_REIMBURSABLE_MEAL` (409)."

        Design: Difficulty/resource_temporal_overlap/duplicate_reimbursable_meal_same_day_rejected
        """
        resp = self._record_two_reimbursable_lunches_same_student_day(api)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REIMBURSABLE_MEAL.value)

    def test_second_reimbursable_meal_same_day_status_409(self, api):
        """PRD §3.6: "Additionally, at most one `REIMBURSABLE` meal is allowed per student, service date, and meal type: a second reimbursable meal for that same combination is refused with `ERR_DUPLICATE_REIMBURSABLE_MEAL` (409)."

        Design: Difficulty/resource_temporal_overlap/duplicate_reimbursable_meal_same_day_rejected
        """
        resp = self._record_two_reimbursable_lunches_same_student_day(api)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REIMBURSABLE_MEAL.value)


# ==========================================================================
# Corner: POS breadth claims
# ==========================================================================
def test_alacarte_snack_failing_smart_snacks_rejected(api):
    """PRD §3.6: "Any a-la-carte line whose food item is a `SNACK` or `BEVERAGE` must pass the **Smart-Snacks** nutrient screen, else `ERR_NOT_SMART_SNACK_COMPLIANT` (422); a snack or beverage item passes only when its `calories` are at most 200, its `sodium_mg` is at most 200, its `total_fat_g` contributes at most 35% of its calories, its `sat_fat_g` contributes less than 10% of its calories, and its `total_sugar_g` is at most 35% of its `weight_g` by weight (fat grams convert to calories at nine calories per gram for the percentage-of-calories tests)."

    Design: Corner/validations/not_smart_snack_compliant_alacarte_rejected
    """
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    bad = create_food_item(api, name="Candy Bar", category="SNACK", calories=400,
                           sat_fat_g=8, sodium_mg=300, total_sugar_g=30, weight_g=50)
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    payload = create_meal_transaction_payload(
        scenario["site_id"], student["id"], scenario["pr_id"], selected_components=REIMBURSABLE,
        a_la_carte_lines=[{"food_item_id": bad["id"], "qty": 1, "unit_price_cents": 150}])
    resp = api.create_meal_transaction(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_SMART_SNACK_COMPLIANT.value)


def test_meal_student_site_mismatch_rejected(api):
    """PRD §3.6: "The `student_id` must belong to the same site as the transaction's `site_id`, else `ERR_STUDENT_SITE_MISMATCH` (409)."

    Design: Corner/validations/meal_student_site_mismatch_rejected
    """
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    other_site = create_site(api, negative_balance_allowed=True)
    student_b = create_student(api, other_site["id"], eligibility_category="FREE")
    payload = create_meal_transaction_payload(
        scenario["site_id"], student_b["id"], scenario["pr_id"], selected_components=REIMBURSABLE)
    resp = api.create_meal_transaction(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_STUDENT_SITE_MISMATCH.value)


def test_meal_selecting_unoffered_component_rejected(api):
    """PRD §3.6: "Every value in `selected_components` must be a component offered by the production record's menu cycle, else `ERR_INVALID_COMPONENT` (422)."

    Design: Corner/validations/invalid_component_not_offered_rejected
    """
    # Menu offers {MEAT_MEAT_ALT, GRAINS, FRUIT, MILK}; VEGETABLE is not offered.
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    payload = create_meal_transaction_payload(
        scenario["site_id"], student["id"], scenario["pr_id"],
        selected_components=["MEAT_MEAT_ALT", "GRAINS", "VEGETABLE"])
    resp = api.create_meal_transaction(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_COMPONENT.value)


def test_two_components_meal_is_non_reimbursable_and_recorded(api):
    """PRD §3.6: "A lunch meal is `REIMBURSABLE` when the number taken is at least 3 and it has a fruit-or-vegetable"
    PRD §3.6: "A meal that fails offer-vs-serve is `NON_REIMBURSABLE`."
    PRD §3.6: "A meal enters the `RECORDED` state on creation."

    Design: Corner/validations/ovs_two_components_non_reimbursable
    """
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                     selected_components=["MEAT_MEAT_ALT", "GRAINS"])
    assert mt["meal_claim_status"] == "NON_REIMBURSABLE", f"got {mt['meal_claim_status']}"


def test_void_already_voided_meal_rejected(api):
    """PRD §3.6: "Voiding a meal moves it from `RECORDED` to the terminal `VOIDED` state and is permitted only while the meal is `RECORDED`, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/void_already_voided_meal_rejected
    """
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    mt = record_meal(api, scenario["site_id"], student["id"], scenario["pr_id"],
                     selected_components=REIMBURSABLE)
    validate_success(api.void_meal_transaction(mt["id"], CLERK), 200)  # first void

    resp = api.void_meal_transaction(mt["id"], CLERK)  # second void
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
