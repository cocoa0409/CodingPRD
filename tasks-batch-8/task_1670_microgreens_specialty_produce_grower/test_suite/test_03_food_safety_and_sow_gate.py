"""The food-safety hard gate on sowing, and the fixed validation order between
the safety gate (fifth) and the seed-lot business constraints (sixth)."""
from test_helpers import (
    ApiErrorId,
    assert_crop_plan,
    assert_tray_batch,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_food_safety_plan,
    create_listed_variety,
    create_released_seed_lot,
    create_seed_lot,
    get_plan_batch,
    get_seed_lot,
    sow_crop_plan,
    suspend_food_safety_plan,
    validate_error,
)
from test_helpers.fixtures import GROWER


class TestSowRequiresApprovedPlan:
    def test_sow_blocked_while_food_safety_plan_draft(self, api):
        """PRD §2.6: "First, no crop plan may be sown while the operation's
        food-safety plan is in any state other than `APPROVED` — the check
        applies whether the plan was never approved or has been `SUSPENDED`."
        PRD §3.3: "the operation-wide food-safety plan must be `APPROVED` or the
        sow is rejected with `ERR_FOOD_SAFETY_NOT_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/sow_requires_food_safety_plan_approved
        """
        create_food_safety_plan()  # DRAFT — never approved
        variety = create_listed_variety(name="Mizuna")
        lot = create_released_seed_lot(variety["id"])
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_FOOD_SAFETY_NOT_APPROVED)

    def test_sow_allowed_once_food_safety_plan_approved(self, api):
        """PRD §3.3: "A successful sow creates a `TrayBatch` under the plan,
        recording the `crop_plan_id`, the `seed_lot_id` it draws from, and a
        `tray_count` equal to the plan's `planned_tray_count`; the batch starts
        `SOWN`. The lot's `seeds_on_hand_grams` is decremented by the plan's
        `seed_grams_required` (which may, as noted in §3.2, tip the lot into
        `DEPLETED`). The plan's `sown_tray_count` is set to its
        `planned_tray_count`, the plan moves from `PLANNED` to `SOWING`, and the
        plan's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/sow_requires_food_safety_plan_approved
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Mizuna")
        lot = create_released_seed_lot(variety["id"], seeds_on_hand_grams=500)
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        sown = sow_crop_plan(plan["id"], plan["version"], lot["id"])
        assert_crop_plan(sown)
        assert sown["status"] == "SOWING", "The plan moves from PLANNED to SOWING"
        assert sown["sown_tray_count"] == 2
        assert sown["version"] > plan["version"], "The plan's version increments"

        batch = get_plan_batch(plan["id"])
        assert_tray_batch(batch)
        assert batch["status"] == "SOWN"
        assert batch["tray_count"] == 2
        assert batch["crop_plan_id"] == plan["id"]
        assert batch["seed_lot_id"] == lot["id"]

        lot_after = get_seed_lot(lot["id"])
        assert lot_after["seeds_on_hand_grams"] == 490


class TestSowValidationOrder:
    def test_sow_reports_food_safety_before_seed_lot_check(self, api):
        """PRD §2.9: "Every request is validated in a fixed priority order, and
        a failure at any step masks all later checks."
        PRD §2.9: "Fifth, the food-safety gate runs for the operations it
        protects. Sixth, business constraints on seed lots (released status,
        sufficient seed on hand) are enforced."

        Design: Difficulty/priority_pair_validation_conflict/sow_blocked_by_food_safety_before_seed_check
        """
        create_food_safety_plan()  # DRAFT — safety gate fails
        variety = create_listed_variety(name="Mustard")
        lot = create_seed_lot(variety["id"])  # QUARANTINE — seed check would also fail
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_FOOD_SAFETY_NOT_APPROVED)

    def test_sow_reports_food_safety_before_seed_check_when_suspended(self, api):
        """PRD §2.6: "First, no crop plan may be sown while the operation's
        food-safety plan is in any state other than `APPROVED` — the check
        applies whether the plan was never approved or has been `SUSPENDED`."
        PRD §2.9: "Fifth, the food-safety gate runs for the operations it
        protects. Sixth, business constraints on seed lots (released status,
        sufficient seed on hand) are enforced."

        Design: Difficulty/priority_pair_validation_conflict/sow_blocked_by_food_safety_before_seed_check
        """
        plan_fs = create_approved_food_safety_plan()
        suspend_food_safety_plan(plan_fs["id"])  # SUSPENDED — safety gate fails
        variety = create_listed_variety(name="Mustard")
        lot = create_seed_lot(variety["id"])  # QUARANTINE — seed check would also fail
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_FOOD_SAFETY_NOT_APPROVED)
