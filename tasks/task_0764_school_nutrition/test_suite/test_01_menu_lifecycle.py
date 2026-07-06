"""Menu-cycle authoring, compliance, review workflow, and its cross-entity gate."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_site, create_food_items, create_draft_lunch_menu, submit_menu,
    approve_menu, create_approved_lunch_menu, create_planned_production,
    make_planner_headers, make_director_headers, TEST_USERS,
)

PLANNER = TEST_USERS["menu_planner_headers"]
DIRECTOR = TEST_USERS["nutrition_director_headers"]
CAFETERIA = TEST_USERS["cafeteria_manager_headers"]


# ==========================================================================
# Non-linear state machine: the reject -> DRAFT revert cycle
# ==========================================================================
class TestMenuRejectRevertCycle:
    def test_reject_reverts_under_review_to_draft_and_records_note(self, api):
        """PRD §3.2: "Rejection reverts the cycle from `UNDER_REVIEW` back to `DRAFT` and records the reviewer's `rejection_note` from the request; this revert edge lets the planner correct and resubmit."

        Design: Difficulty/non_linear_state_machine/menu_cycle_reject_revert_cycle
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        cycle = create_draft_lunch_menu(api, site["id"], food_ids)
        submit_menu(api, cycle["id"], "planner_1")

        resp = api.reject_menu_cycle(cycle["id"], make_director_headers("dir_1"),
                                     {"rejection_note": "swap the entree"})
        data = validate_success(resp, 200)
        assert data["status"] == "DRAFT", f"reject must revert to DRAFT, got {data['status']}"
        assert data["rejection_note"] == "swap the entree"

    def test_resubmit_then_approve_after_reject_reaches_approved(self, api):
        """PRD §3.2: "Approval advances the cycle from `UNDER_REVIEW` to `APPROVED` and additionally requires that no other `APPROVED` menu cycle for the same `site_id`, `meal_type`, and `grade_group` cover an overlapping half-open date range".

        Design: Difficulty/non_linear_state_machine/menu_cycle_reject_revert_cycle
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        cycle = create_draft_lunch_menu(api, site["id"], food_ids)
        submit_menu(api, cycle["id"], "planner_1")
        api.reject_menu_cycle(cycle["id"], make_director_headers("dir_1"),
                              {"rejection_note": "swap the entree"})
        # DRAFT again -> resubmit -> approve completes the cycle.
        submit_menu(api, cycle["id"], "planner_1")
        resp = api.approve_menu_cycle(cycle["id"], make_director_headers("dir_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED", f"expected APPROVED after resubmit+approve, got {data['status']}"


# ==========================================================================
# Resource temporal overlap: half-open menu period, adjacency allowed
# ==========================================================================
class TestMenuPeriodOverlap:
    def test_overlapping_approved_cycle_rejected(self, api):
        """PRD §3.2: "Approval advances the cycle from `UNDER_REVIEW` to `APPROVED` and additionally requires that no other `APPROVED` menu cycle for the same `site_id`, `meal_type`, and `grade_group` cover an overlapping half-open date range; because ranges are half-open, exact adjacency where one period's `end_date` equals another's `effective_date` is allowed, but any true overlap is refused with `ERR_MENU_PERIOD_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/menu_period_half_open_overlap_rejected
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        create_approved_lunch_menu(api, site["id"], food_ids,
                                   effective_date="2026-04-01", end_date="2026-05-01")
        cycle2 = create_draft_lunch_menu(api, site["id"], food_ids,
                                         effective_date="2026-04-15", end_date="2026-05-15")
        submit_menu(api, cycle2["id"], "planner_1")

        resp = api.approve_menu_cycle(cycle2["id"], make_director_headers("dir_1"))
        validate_error(resp, ApiErrorId.ERR_MENU_PERIOD_OVERLAP.value)

    def test_adjacent_period_end_equals_start_is_allowed(self, api):
        """PRD §3.2: "because ranges are half-open, exact adjacency where one period's `end_date` equals another's `effective_date` is allowed, but any true overlap is refused with `ERR_MENU_PERIOD_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/menu_period_half_open_overlap_rejected
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        create_approved_lunch_menu(api, site["id"], food_ids,
                                   effective_date="2026-04-01", end_date="2026-05-01")
        cycle2 = create_draft_lunch_menu(api, site["id"], food_ids,
                                         effective_date="2026-05-01", end_date="2026-06-01")
        submit_menu(api, cycle2["id"], "planner_1")

        resp = api.approve_menu_cycle(cycle2["id"], make_director_headers("dir_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED", "adjacent (end==start) period must be approvable"


# ==========================================================================
# Priority pair: meal-pattern violation outranks past-effective-date at submit
# ==========================================================================
class TestSubmitValidationPrecedence:
    def test_noncompliant_menu_computes_noncompliant_status(self, api):
        """PRD §3.2: "For a `LUNCH` cycle, the cycle is `COMPLIANT` when the total meat/meat-alternate is at least 1.0 ounce-equivalent, the total grain is at least 1.0 ounce-equivalent, the total fruit-and-vegetable is at least 0.75 cup, milk is present, and all grains are whole-grain-rich."
        PRD §3.2: "If any applicable condition fails, `compliance_status` is `NONCOMPLIANT`."

        Design: Difficulty/priority_pair_validation_conflict/meal_pattern_violation_beats_effective_date_past
        """
        site = create_site(api)
        # Grain is NOT whole-grain-rich -> all_grains_wgr fails -> NONCOMPLIANT.
        food_ids = create_food_items(api, whole_grain_rich=False)
        cycle = create_draft_lunch_menu(api, site["id"], food_ids, effective_date="2026-01-01")
        assert cycle["compliance_status"] == "NONCOMPLIANT"

    def test_noncompliant_and_past_effective_date_returns_meal_pattern_violation(self, api):
        """PRD §3.2: "Submission requires that the cycle's `compliance_status` be `COMPLIANT`; a non-compliant cycle is refused with `ERR_MEAL_PATTERN_VIOLATION` (422)."
        PRD §2.5: "The per-endpoint precedence is spelled out in the workflow narratives of §3, but as a governing example, a point-of-service meal evaluates its guards in this order: production readiness (`ERR_PRODUCTION_NOT_READY`), then Smart-Snacks compliance (`ERR_NOT_SMART_SNACK_COMPLIANT`), then student-site match (`ERR_STUDENT_SITE_MISMATCH`), then component validity (`ERR_INVALID_COMPONENT`), then the duplicate-reimbursable-meal check (`ERR_DUPLICATE_REIMBURSABLE_MEAL`), and finally the balance check (`ERR_INSUFFICIENT_BALANCE`)."

        The §3.2 narrative states the compliance requirement before the effective-date
        requirement, and §2.5 designates §3 narrative order as the per-endpoint precedence.

        Design: Difficulty/priority_pair_validation_conflict/meal_pattern_violation_beats_effective_date_past
        """
        site = create_site(api)
        food_ids = create_food_items(api, whole_grain_rich=False)
        # effective_date 2026-01-01 is before the default clock (2026-03-01): also past.
        cycle = create_draft_lunch_menu(api, site["id"], food_ids, effective_date="2026-01-01")

        resp = api.submit_menu_cycle(cycle["id"], make_planner_headers("planner_1"))
        validate_error(resp, ApiErrorId.ERR_MEAL_PATTERN_VIOLATION.value)


# ==========================================================================
# Cross-entity state dependency: production requires an APPROVED menu cycle
# ==========================================================================
class TestProductionRequiresApprovedMenu:
    def test_production_against_draft_menu_returns_menu_not_approved(self, api):
        """PRD §3.4: "Creation requires the referenced menu cycle to be both `APPROVED` and `COMPLIANT`, else `ERR_MENU_NOT_APPROVED` (409)".

        Design: Difficulty/cross_entity_state_dependency/production_requires_menu_cycle_approved
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        cycle = create_draft_lunch_menu(api, site["id"], food_ids)  # never submitted/approved

        resp = api.create_production_record(
            {"site_id": site["id"], "menu_cycle_id": cycle["id"],
             "service_date": "2026-04-15", "meal_type": "LUNCH", "planned_qty": 100},
            CAFETERIA)
        validate_error(resp, ApiErrorId.ERR_MENU_NOT_APPROVED.value)

    def test_production_against_draft_menu_status_is_409(self, api):
        """PRD §3.4: "Creation requires the referenced menu cycle to be both `APPROVED` and `COMPLIANT`, else `ERR_MENU_NOT_APPROVED` (409)".

        Design: Difficulty/cross_entity_state_dependency/production_requires_menu_cycle_approved
        """
        site = create_site(api)
        food_ids = create_food_items(api)
        cycle = create_draft_lunch_menu(api, site["id"], food_ids)

        resp = api.create_production_record(
            {"site_id": site["id"], "menu_cycle_id": cycle["id"],
             "service_date": "2026-04-15", "meal_type": "LUNCH", "planned_qty": 100},
            CAFETERIA)
        assert resp.status_code == 409, f"expected HTTP 409, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_MENU_NOT_APPROVED.value)


# ==========================================================================
# Corner: menu-cycle breadth claims
# ==========================================================================
def test_compliant_lunch_menu_computes_compliant_at_creation(api):
    """PRD §3.2: "For a `LUNCH` cycle, the cycle is `COMPLIANT` when the total meat/meat-alternate is at least 1.0 ounce-equivalent, the total grain is at least 1.0 ounce-equivalent, the total fruit-and-vegetable is at least 0.75 cup, milk is present, and all grains are whole-grain-rich."
    PRD §3.2: "A newly created cycle starts in `DRAFT` status, and its `compliance_status` is computed immediately."

    Design: Corner/calculations/menu_compliant_positive_computes_compliant
    """
    site = create_site(api)
    food_ids = create_food_items(api)  # meat 2.0, grain 1.0 WGR, fruit 0.75, milk present
    cycle = create_draft_lunch_menu(api, site["id"], food_ids)
    assert cycle["compliance_status"] == "COMPLIANT"


def test_approve_draft_menu_returns_invalid_state(api):
    """PRD §3.2: "An attempt to submit, approve, or reject a cycle that is not in the required starting state is refused with the generic `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/approve_menu_from_draft_returns_invalid_state
    """
    site = create_site(api)
    food_ids = create_food_items(api)
    cycle = create_draft_lunch_menu(api, site["id"], food_ids)  # still DRAFT

    resp = api.approve_menu_cycle(cycle["id"], make_director_headers("dir_9"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_menu_approver_equal_to_submitter_rejected(api):
    """PRD §2.7: "When a menu cycle is approved or rejected, the acting `X-User-ID` must differ from the `submitted_by_user_id` recorded when the cycle was submitted; if they are equal, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/segregation_menu_approver_equals_submitter_rejected
    """
    site = create_site(api)
    food_ids = create_food_items(api)
    cycle = create_draft_lunch_menu(api, site["id"], food_ids)
    submit_menu(api, cycle["id"], "same_person")

    resp = api.approve_menu_cycle(cycle["id"], make_director_headers("same_person"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
