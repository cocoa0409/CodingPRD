"""Special-diet accommodation review loop: the SUBMITTED <-> NUTRITION_REVIEW
cycle, the suitable-menu gate, and activation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_accommodation_request,
    create_accommodation,
    create_hall,
    create_recipe,
    get_accommodation,
    validate_error,
    validate_success,
)

HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]


class TestAccommodationReviewCycle:
    def _setup(self, api):
        hall = create_hall(name="Hall Ac")
        create_recipe(hall["id"], name="Vegan Chili", allergen_tags=[],
                      dietary_flags=["VEGAN"], popularity_share=0.5,
                      unit_cost_cents=500, allergen_reviewed=True)
        return hall

    def test_review_info_cycle_statuses(self, api):
        """PRD §3.6: "Starting review moves `SUBMITTED` → `NUTRITION_REVIEW`.
        When more information is needed, a request-info call cycles the request
        back from `NUTRITION_REVIEW` to `SUBMITTED`, storing the dietitian's
        note as the request's latest `review_notes`."
        PRD §3.6: "Finally, a `KitchenLead` confirms the production plan, moving
        `APPROVED` → `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/accommodation_review_info_cycle
        """
        hall = self._setup(api)
        request = create_accommodation(hall["id"], student_ref="STU-1",
                                       allergen_exclusions=["PEANUT"],
                                       dietary_requirement="VEGAN")
        statuses = [request["status"]]
        statuses.append(validate_success(
            api.start_accommodation_review(request["id"], DIETITIAN))["status"])
        statuses.append(validate_success(api.request_accommodation_info(
            request["id"], {"review_notes": "need brand list"}, DIETITIAN))["status"])
        statuses.append(validate_success(
            api.start_accommodation_review(request["id"], DIETITIAN))["status"])
        statuses.append(validate_success(
            api.approve_accommodation_request(request["id"], DIETITIAN))["status"])
        statuses.append(validate_success(
            api.activate_accommodation_request(request["id"], KITCHEN_LEAD))["status"])
        assert statuses == ["SUBMITTED", "NUTRITION_REVIEW", "SUBMITTED",
                            "NUTRITION_REVIEW", "APPROVED", "ACTIVE"], (
            "the request-info loop edge is legal, not a terminal lockdown")
        assert_accommodation_request(get_accommodation(request["id"]))

    def test_request_info_stores_latest_notes(self, api):
        """PRD §3.6: "When more information is needed, a request-info call
        cycles the request back from `NUTRITION_REVIEW` to `SUBMITTED`, storing
        the dietitian's note as the request's latest `review_notes`."

        Design: Difficulty/non_linear_state_machine/accommodation_review_info_cycle
        """
        hall = self._setup(api)
        request = create_accommodation(hall["id"], student_ref="STU-1",
                                       allergen_exclusions=["PEANUT"],
                                       dietary_requirement="VEGAN")
        validate_success(api.start_accommodation_review(request["id"], DIETITIAN))
        cycled = validate_success(api.request_accommodation_info(
            request["id"], {"review_notes": "need brand list"}, DIETITIAN))
        assert cycled["status"] == "SUBMITTED"
        assert cycled["review_notes"] == "need brand list"


class TestSuitableMenuGate:
    def test_approve_blocked_until_suitable_recipe_exists(self, api):
        """PRD §3.6: "Approving (`NUTRITION_REVIEW` → `APPROVED`) is gated on a
        suitable-menu check: at least one recipe at the request's hall must be
        `ACTIVE`, have `allergen_tags` disjoint from the request's
        `allergen_exclusions`, and satisfy the dietary requirement — where a
        requirement of `OTHER` imposes no flag constraint, and any other
        requirement must appear in the recipe's `dietary_flags`. If no such
        recipe exists, approval is refused with `ERR_NO_SUITABLE_MENU`."

        Design: Corner/errors/accommodation_approve_no_suitable_menu_then_succeeds
        """
        hall = create_hall(name="Hall E5")
        create_recipe(hall["id"], name="Peanut Satay", allergen_tags=["PEANUT"],
                      dietary_flags=["VEGAN"], popularity_share=0.4,
                      unit_cost_cents=500, allergen_reviewed=True)
        request = create_accommodation(hall["id"], student_ref="STU-2",
                                       allergen_exclusions=["PEANUT"],
                                       dietary_requirement="VEGAN")
        validate_success(api.start_accommodation_review(request["id"], DIETITIAN))

        resp = api.approve_accommodation_request(request["id"], DIETITIAN)
        validate_error(resp, ApiErrorId.ERR_NO_SUITABLE_MENU)

        create_recipe(hall["id"], name="Lentil Bowl", allergen_tags=[],
                      dietary_flags=["VEGAN"], popularity_share=0.3,
                      unit_cost_cents=450, allergen_reviewed=True)
        approved = validate_success(api.approve_accommodation_request(
            request["id"], DIETITIAN))
        assert approved["status"] == "APPROVED"
