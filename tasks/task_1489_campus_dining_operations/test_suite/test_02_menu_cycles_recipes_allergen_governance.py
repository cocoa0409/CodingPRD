"""Menu-cycle interval rules, recipe allergen governance, and the
safety-vs-structural priority pair on cycle publish."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_hall,
    create_menu_cycle,
    create_menu_cycle_payload,
    create_published_cycle,
    create_recipe,
    create_recipe_payload,
    get_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]


class TestRecipeDefaults:
    def test_recipe_created_unreviewed_and_active_by_default(self, api):
        """PRD §3.2: "The `allergen_reviewed` flag defaults to false and flips to
        true only once a dietitian-reviewed allergen label exists; it may be
        supplied at creation or changed later. New recipes start `ACTIVE`."

        Design: Corner/entities/recipe_creation_default_allergen_reviewed_false
        """
        hall = create_hall(name="Hall D")
        payload = create_recipe_payload(
            hall["id"], name="Untested Stew", allergen_tags=["SOY"],
            popularity_share=0.4, unit_cost_cents=450)
        del payload["allergen_reviewed"]
        recipe = validate_success(api.create_recipe(payload, KITCHEN_LEAD),
                                  expected_status=201)
        assert recipe["allergen_reviewed"] is False
        assert recipe["status"] == "ACTIVE"


class TestMenuCycleShapeAndTerminal:
    def test_cycle_end_before_start_rejected(self, api):
        """PRD §3.2: "A `DiningAdmin` creates a cycle for a hall
        (`dining_hall_id`) with a `name` such as "Fall-2026 Cycle A", a
        `cycle_length_weeks` between 1 and 8 inclusive, and a half-open
        `start_date`/`end_date` interval whose end must be strictly after its
        start."
        PRD §2.7: "10. **Field shape** — required fields present, enum values in
        range, date intervals with start before end, swipe amounts consistent
        with entry type, worked-minutes bounds, invoice-total bounds; failures
        yield `ERR_VALIDATION`."

        Design: Corner/validations/menu_cycle_end_before_start_rejected
        """
        hall = create_hall(name="Hall V6")
        payload = create_menu_cycle_payload(
            hall["id"], name="Bad", start_date="2026-10-01", end_date="2026-09-01")
        resp = api.create_menu_cycle(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_archive_twice_is_terminal_lockdown(self, api):
        """PRD §3.2: "A cycle in either `DRAFT` or `PUBLISHED` may be archived by
        a `DiningAdmin`, moving it to `ARCHIVED`, which is terminal."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/menu_cycle_archive_twice_terminal_lockdown
        """
        hall = create_hall(name="Hall SM6")
        cycle = create_published_cycle(hall["id"], name="C", weeks=2,
                                       start_date="2026-09-01", end_date="2026-10-01")
        archived = validate_success(api.archive_menu_cycle(cycle["id"], ADMIN))
        assert archived["status"] == "ARCHIVED"
        resp = api.archive_menu_cycle(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_cycle(cycle["id"])["status"] == "ARCHIVED"


class TestAllergenGovernance:
    def test_reinstate_requires_allergen_review(self, api):
        """PRD §3.2: "reinstatement moves it back to `ACTIVE` but only when
        `allergen_reviewed` is true at that moment, otherwise
        `ERR_ALLERGEN_UNDECLARED`."

        Design: Corner/errors/recipe_reinstate_requires_allergen_review
        """
        hall = create_hall(name="Hall E8")
        recipe = create_recipe(hall["id"], name="Mystery Soup", station="DELI",
                               allergen_tags=["SOY"], popularity_share=0.3,
                               unit_cost_cents=300, allergen_reviewed=False)
        validate_success(api.suspend_recipe(recipe["id"], ADMIN))

        resp = api.reinstate_recipe(recipe["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_UNDECLARED)

        validate_success(api.patch_recipe(recipe["id"],
                                          {"allergen_reviewed": True}, KITCHEN_LEAD))
        reinstated = validate_success(api.reinstate_recipe(recipe["id"], ADMIN))
        assert reinstated["status"] == "ACTIVE"

    def test_publish_blocked_by_single_unreviewed_recipe(self, api):
        """PRD §3.2: "every recipe at the same hall whose `status` is `ACTIVE`
        must have `allergen_reviewed` set to true, or publication is refused with
        `ERR_ALLERGEN_UNDECLARED` (the check is vacuously satisfied when the hall
        has no active recipes at all)."

        Design: Corner/errors/cycle_publish_unreviewed_recipe_single_failure
        """
        hall = create_hall(name="Hall E9")
        create_recipe(hall["id"], name="Unreviewed Pie", station="BAKERY",
                      allergen_tags=["WHEAT", "EGG"], popularity_share=0.2,
                      unit_cost_cents=250, allergen_reviewed=False)
        cycle = create_menu_cycle(hall["id"], name="C", start_date="2026-09-01",
                                  end_date="2026-10-01")
        resp = api.publish_menu_cycle(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_UNDECLARED)
        assert get_cycle(cycle["id"])["status"] == "DRAFT"


class TestCycleOverlapHalfOpen:
    def test_adjacent_cycle_publishes_cleanly(self, api):
        """PRD §3.2: "Because both intervals are half-open, adjacency is allowed:
        one cycle's `end_date` equaling another's `start_date` is not an
        overlap."

        Design: Difficulty/resource_temporal_overlap/menu_cycle_half_open_adjacency
        """
        hall = create_hall(name="Hall OV1")
        create_published_cycle(hall["id"], name="C1", start_date="2026-09-01",
                               end_date="2026-10-01")
        c2 = create_menu_cycle(hall["id"], name="C2", start_date="2026-08-01",
                               end_date="2026-09-01")
        published = validate_success(api.publish_menu_cycle(c2["id"], ADMIN))
        assert published["status"] == "PUBLISHED", (
            "[2026-08-01, 2026-09-01) merely touches [2026-09-01, 2026-10-01) — "
            "adjacency is not overlap")

    def test_straddling_cycle_rejected_with_overlap(self, api):
        """PRD §3.2: "Publication also enforces exclusivity of coverage — no
        other `PUBLISHED` cycle at the same hall may have a half-open interval
        that intersects this cycle's interval. Because both intervals are
        half-open, adjacency is allowed: one cycle's `end_date` equaling
        another's `start_date` is not an overlap. A violation is rejected with
        `ERR_CYCLE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/menu_cycle_half_open_adjacency
        """
        hall = create_hall(name="Hall OV1")
        create_published_cycle(hall["id"], name="C1", start_date="2026-09-01",
                               end_date="2026-10-01")
        c3 = create_menu_cycle(hall["id"], name="C3", start_date="2026-08-15",
                               end_date="2026-09-15")
        resp = api.publish_menu_cycle(c3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP)
        assert get_cycle(c3["id"])["status"] == "DRAFT"


class TestPublishSafetyBeatsOverlap:
    def _setup_double_failure(self, api):
        """Hall with PUBLISHED C1 [09-01,10-01), an ACTIVE unreviewed recipe,
        and DRAFT C2 [09-15,10-15) that overlaps C1."""
        hall = create_hall(name="Hall P5b")
        create_published_cycle(hall["id"], name="C1", start_date="2026-09-01",
                               end_date="2026-10-01")
        recipe = create_recipe(hall["id"], name="Mystery Loaf", station="BAKERY",
                               allergen_tags=["WHEAT"], popularity_share=0.3,
                               unit_cost_cents=200, allergen_reviewed=False)
        c2 = create_menu_cycle(hall["id"], name="C2", start_date="2026-09-15",
                               end_date="2026-10-15")
        return hall, recipe, c2

    def test_safety_error_reported_when_both_fail(self, api):
        """PRD §2.7: "When several rules fail on the same request, the server
        does not report them all: it reports the failure from the **earliest
        tier** of a fixed ten-tier validation pipeline." The food-safety gates
        sit at tier 6, structural conflicts at tier 7.

        Design: Difficulty/priority_pair_validation_conflict/publish_cycle_safety_beats_overlap
        """
        _hall, _recipe, c2 = self._setup_double_failure(api)
        resp = api.publish_menu_cycle(c2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_UNDECLARED)
        assert get_cycle(c2["id"])["status"] == "DRAFT"

    def test_overlap_surfaces_once_safety_gate_passes(self, api):
        """PRD §3.2: "Publication also enforces exclusivity of coverage — no
        other `PUBLISHED` cycle at the same hall may have a half-open interval
        that intersects this cycle's interval. Because both intervals are
        half-open, adjacency is allowed: one cycle's `end_date` equaling
        another's `start_date` is not an overlap. A violation is rejected with
        `ERR_CYCLE_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/publish_cycle_safety_beats_overlap
        """
        _hall, recipe, c2 = self._setup_double_failure(api)
        validate_success(api.patch_recipe(recipe["id"],
                                          {"allergen_reviewed": True}, KITCHEN_LEAD))
        resp = api.publish_menu_cycle(c2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP)
        assert get_cycle(c2["id"])["status"] == "DRAFT"
