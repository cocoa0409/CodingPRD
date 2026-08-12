"""Weekly menu cycle compliance: nutrition gates, allergen safety, meal-count
cap, and the freeze/unfreeze revision loop (PRD §3.4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_menu_item_payload,
    create_active_member, create_accepted_referral, create_draft_prescription,
    activate_prescription, create_menu_item, create_planned_cycle,
    transition_member,
)


def _setup_potassium_violating_cycle():
    """RENAL prescription (potassium ceiling 2000/day, protein floor 60/day)
    with Lentil Stew x5 + Banana x1: weekly potassium 14500 > 14000 and weekly
    protein 105 < 420; sodium and phosphorus pass."""
    from test_helpers import setup_member_with_active_prescription
    ctx = setup_member_with_active_prescription(
        member_overrides={"full_name": "M Four", "payer_member_id": "W-400"},
        prescription_overrides={"daily_protein_g_min": 60})
    stew = create_menu_item("lentil_stew")
    banana = create_menu_item("banana")
    planned = create_planned_cycle(ctx["member"]["id"], ctx["prescription"]["id"],
                                   "2026-05-04",
                                   [(stew["id"], 5), (banana["id"], 1)])
    ctx.update({"cycle": planned["cycle"]})
    return ctx


class TestNutritionMultiNutrientGating:
    def test_compliance_read_reports_weekly_totals_and_verdict(
            self, api, dietitian_headers):
        """PRD §3.4: "each weekly limit is seven times the prescription's
        corresponding daily limit, since a cycle spans a seven-day week."
        PRD §3.4: "a `RENAL` prescription enforces the sodium, potassium, and
        phosphorus ceilings plus the protein floor"
        PRD §3.4: "the protein gate passes when the weekly protein total is at
        least seven times `daily_protein_g_min`."

        Design: Difficulty/combinatorial_formula/nutrition_multi_nutrient_gating
        """
        ctx = _setup_potassium_violating_cycle()
        comp = validate_success(
            api.get_cycle_compliance(ctx["cycle"]["id"], dietitian_headers))
        assert comp["sodium_mg_total"] == 7600
        assert comp["potassium_mg_total"] == 14500, \
            "14500 exceeds the 14000 weekly potassium limit (7 x 2000)"
        assert comp["phosphorus_mg_total"] == 3550
        assert comp["protein_g_total"] == 105, \
            "105 is below the 420 weekly protein floor (7 x 60)"
        assert comp["nutrition_compliant"] is False
        assert comp["allergen_ok"] is True
        assert comp["allergen_violations"] == []
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["meals_count"] == 6

    def test_freeze_rejected_by_failed_nutrition_gates(
            self, api, dietitian_headers):
        """PRD §3.4: "Any failed gate rejects the freeze with
        `ERR_NUTRITION_NON_COMPLIANT`."

        Design: Difficulty/combinatorial_formula/nutrition_multi_nutrient_gating
        """
        ctx = _setup_potassium_violating_cycle()
        resp = api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_NUTRITION_NON_COMPLIANT)
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "PLANNED"


class TestFreezeUnfreezeRevisionCycle:
    def _setup_compliant_cycle(self):
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "M Five",
                              "payer_type": "MEDICARE_ADVANTAGE",
                              "payer_member_id": "MA-500",
                              "income_fpl_percent": 200, "household_size": 1})
        item = create_menu_item("rice_bowl")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(item["id"], 5)])
        ctx.update({"cycle": planned["cycle"]})
        return ctx

    def test_unfreeze_returns_cycle_to_planned_and_resets_compliance(
            self, api, dietitian_headers):
        """PRD §3.4: "A successful freeze moves the cycle to `FROZEN`, sets
        `compliance_status` to `PASSED`, and locks the `prescription_id` pin for
        the life of the cycle."
        PRD §3.4: "Unfreezing returns a `FROZEN` cycle to `PLANNED` and resets
        `compliance_status` to `UNCHECKED`"

        Design: Difficulty/non_linear_state_machine/menu_cycle_freeze_unfreeze_revision_cycle
        """
        ctx = self._setup_compliant_cycle()
        frozen = validate_success(api.freeze_cycle(ctx["cycle"]["id"],
                                                   dietitian_headers))
        assert frozen["status"] == "FROZEN"
        assert frozen["compliance_status"] == "PASSED"
        unfrozen = validate_success(api.unfreeze_cycle(ctx["cycle"]["id"],
                                                       dietitian_headers))
        assert unfrozen["status"] == "PLANNED"
        assert unfrozen["compliance_status"] == "UNCHECKED"

    def test_revision_loop_is_reentrant(self, api, dietitian_headers):
        """PRD §3.4: "This planned-frozen-planned loop may repeat."

        Design: Difficulty/non_linear_state_machine/menu_cycle_freeze_unfreeze_revision_cycle
        """
        ctx = self._setup_compliant_cycle()
        validate_success(api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers))
        validate_success(api.unfreeze_cycle(ctx["cycle"]["id"], dietitian_headers))
        refrozen = validate_success(api.freeze_cycle(ctx["cycle"]["id"],
                                                     dietitian_headers))
        assert refrozen["status"] == "FROZEN"
        assert refrozen["compliance_status"] == "PASSED"


class TestFreezeSafetyBeatsConstraint:
    def _setup_allergen_and_count_violating_cycle(self):
        """Member allergic to PEANUT; cycle holds Peanut Chicken x11 — both an
        allergen intersection and 11 > 10 meals_per_week."""
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "M Ten", "payer_member_id": "W-110",
                              "allergies": ["PEANUT"]},
            prescription_overrides={"daily_protein_g_min": 10})
        peanut = create_menu_item("peanut_chicken")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(peanut["id"], 11)])
        ctx.update({"cycle": planned["cycle"]})
        return ctx

    def test_allergen_error_wins_over_meal_count(self, api, dietitian_headers):
        """PRD §3.4: "The safety checks then run in a fixed order. First,
        allergen exposure: the blocked set is the union of the member's
        `allergies` and the pinned prescription's `excluded_allergens`, and if
        any item line's `allergen_codes` intersect that set the freeze is
        rejected with `ERR_ALLERGEN_VIOLATION`."
        PRD §3.4: "Third, the meal-count cap: if `meals_count` exceeds the
        prescription's `meals_per_week`, the freeze is rejected with
        `ERR_MEAL_COUNT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/freeze_safety_beats_constraint
        """
        ctx = self._setup_allergen_and_count_violating_cycle()
        resp = api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_VIOLATION)

    def test_rejected_freeze_leaves_cycle_untouched(self, api, dietitian_headers):
        """PRD §3.4: "The safety checks then run in a fixed order. First,
        allergen exposure: the blocked set is the union of the member's
        `allergies` and the pinned prescription's `excluded_allergens`, and if
        any item line's `allergen_codes` intersect that set the freeze is
        rejected with `ERR_ALLERGEN_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/freeze_safety_beats_constraint
        """
        ctx = self._setup_allergen_and_count_violating_cycle()
        validate_error(api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers),
                       ApiErrorId.ERR_ALLERGEN_VIOLATION)
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "PLANNED"
        assert cycle["compliance_status"] == "UNCHECKED"
        assert cycle["meals_count"] == 11


class TestFreezeRequiresMemberActive:
    def _setup_suspended_member_cycle(self):
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "M Thirteen",
                              "payer_member_id": "W-310"})
        item = create_menu_item("rice_bowl")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(item["id"], 5)])
        ctx.update({"cycle": planned["cycle"]})
        transition_member(ctx["member"]["id"], "SUSPENDED")
        return ctx

    def test_freeze_rejected_while_member_suspended(self, api,
                                                    dietitian_headers):
        """PRD §3.4: "A `Dietitian` freezes a `PLANNED` cycle; the request is
        rejected with `ERR_MENU_CYCLE_NOT_PLANNED` if the cycle is in any other
        state, with `ERR_MEMBER_NOT_ACTIVE` if the member is not `ACTIVE`, and
        with `ERR_PRESCRIPTION_NOT_ACTIVE` if the pinned prescription is no
        longer `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/freeze_requires_member_active
        """
        ctx = self._setup_suspended_member_cycle()
        resp = api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "PLANNED"

    def test_freeze_succeeds_after_reactivation(self, api, dietitian_headers):
        """PRD §3.1: "reactivation moves `SUSPENDED` back to `ACTIVE`, and this
        active-suspended loop may cycle indefinitely."
        PRD §3.4: "A successful freeze moves the cycle to `FROZEN`, sets
        `compliance_status` to `PASSED`, and locks the `prescription_id` pin for
        the life of the cycle."

        Design: Difficulty/cross_entity_state_dependency/freeze_requires_member_active
        """
        ctx = self._setup_suspended_member_cycle()
        validate_error(api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers),
                       ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        transition_member(ctx["member"]["id"], "ACTIVE")
        frozen = validate_success(api.freeze_cycle(ctx["cycle"]["id"],
                                                   dietitian_headers))
        assert frozen["status"] == "FROZEN"
        assert frozen["compliance_status"] == "PASSED"


class TestFreezeErrorIsolation:
    def test_nutrition_non_compliant_on_freeze(self, api, dietitian_headers):
        """PRD §3.4: "Second, nutrition gates: weekly totals are computed by
        summing, across all item lines, each meal's nutrient value multiplied by
        its line `quantity`; each weekly limit is seven times the prescription's
        corresponding daily limit, since a cycle spans a seven-day week."
        PRD §3.4: "Any failed gate rejects the freeze with
        `ERR_NUTRITION_NON_COMPLIANT`."

        Design: Corner/errors/error_nutrition_non_compliant_on_freeze
        """
        ctx = _setup_potassium_violating_cycle()
        resp = api.freeze_cycle(ctx["cycle"]["id"], dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_NUTRITION_NON_COMPLIANT)
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "PLANNED"
        assert cycle["compliance_status"] == "UNCHECKED"

    def test_meal_count_exceeded_alone(self, api, dietitian_headers):
        """PRD §3.4: "Third, the meal-count cap: if `meals_count` exceeds the
        prescription's `meals_per_week`, the freeze is rejected with
        `ERR_MEAL_COUNT_EXCEEDED`."

        Design: Corner/errors/error_meal_count_exceeded_alone
        """
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "N Two", "payer_member_id": "W-N2"},
            prescription_overrides={"daily_protein_g_min": 10})
        snack = create_menu_item("light_snack")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(snack["id"], 11)])
        resp = api.freeze_cycle(planned["cycle"]["id"], dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_MEAL_COUNT_EXCEEDED)
        cycle = validate_success(api.get_menu_cycle(planned["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "PLANNED"

    def test_menu_item_retired_on_add(self, api, dietitian_headers,
                                      program_admin_headers):
        """PRD §3.4: "adding a `RETIRED` item is rejected with
        `ERR_MENU_ITEM_RETIRED`."
        PRD §3.4: "Every add or remove recomputes `meals_count` as the sum of
        `quantity` across the cycle's lines."

        Design: Corner/errors/error_menu_item_retired_on_add
        """
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "N Seven", "payer_member_id": "W-N7"})
        item = create_menu_item("rice_bowl", name="Old Stew")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"], "2026-05-04")
        validate_success(api.retire_menu_item(item["id"], program_admin_headers))
        resp = api.add_cycle_item(planned["cycle"]["id"],
                                  {"menu_item_id": item["id"], "quantity": 3},
                                  dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_MENU_ITEM_RETIRED)
        cycle = validate_success(api.get_menu_cycle(planned["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["meals_count"] == 0


class TestMenuItemCatalog:
    def test_menu_item_create_missing_required_field(
            self, api, program_admin_headers):
        """PRD §2.8: "A malformed body, a missing required field, a type
        mismatch, or an invalid enum or date value is a request-format failure
        reported as `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/menu_item_create_missing_required_field
        """
        payload = create_menu_item_payload("rice_bowl")
        del payload["name"]
        resp = api.create_menu_item(payload, program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestImmediateConsistency:
    def test_immediate_consistency_on_freeze_response(
            self, api, dietitian_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "A successful freeze moves the cycle to `FROZEN`, sets
        `compliance_status` to `PASSED`, and locks the `prescription_id` pin for
        the life of the cycle."

        Design: Corner/consistency_model/immediate_consistency_on_freeze_response
        """
        from test_helpers import setup_member_with_active_prescription
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "K Three", "payer_member_id": "W-K3"})
        item = create_menu_item("rice_bowl")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(item["id"], 5)])
        frozen = validate_success(api.freeze_cycle(planned["cycle"]["id"],
                                                   dietitian_headers))
        assert frozen["status"] == "FROZEN"
        assert frozen["compliance_status"] == "PASSED"
        assert frozen["meals_count"] == 5
        fetched = validate_success(api.get_menu_cycle(planned["cycle"]["id"],
                                                      dietitian_headers))
        assert fetched["status"] == frozen["status"]
        assert fetched["compliance_status"] == frozen["compliance_status"]
