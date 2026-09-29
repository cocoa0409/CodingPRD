"""Prescribing a diet: the effective envelope, the revision cycle and supersession."""
import pytest
from test_helpers import (
    ApiErrorId,
    DIETITIAN_1,
    PHYSICIAN_1,
    TEST_USERS,
    activate_procedure_hold,
    assert_diet_order,
    assert_instant_equals,
    approx1,
    create_active_diet_order,
    cosign_diet_order,
    draft_diet_order,
    diet_order_version,
    line,
    new_diet_rule,
    new_menu_item,
    new_meal_period,
    new_patient,
    new_procedure_hold,
    new_ward,
    place_tray,
    read_diet_order,
    read_meal_order,
    read_meal_period,
    read_patient,
    set_clock,
    submit_diet_order,
    validate_error,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
AIDE = TEST_USERS["tray_aide_headers"]


def _envelope_scenario():
    """Two layered rules, a raised patient floor and an active clear-liquids hold."""
    ward = new_ward()
    renal = new_diet_rule("RENAL_2G_NA")
    carb = new_diet_rule("CARB_MOD")
    patient = new_patient(
        ward["id"],
        mrn="MRN-3001",
        texture_level="MINCED_MOIST",
        liquid_level="MODERATELY_THICK",
    )
    hold = new_procedure_hold(
        patient["id"],
        procedure_code="ENDO-01",
        npo_kind="NPO_CLEAR_LIQUIDS",
        hold_start_at="2026-08-02T06:00:00Z",
        hold_end_at="2026-08-02T14:00:00Z",
    )
    activate_procedure_hold(hold["id"])
    order = draft_diet_order(
        patient["id"],
        renal["id"],
        PHYSICIAN_1,
        secondary_diet_rule_id=carb["id"],
        texture_level="REGULAR",
        liquid_level="THIN",
    )
    submit_diet_order(order["id"], PHYSICIAN_1)
    return {
        "ward": ward,
        "renal": renal,
        "carb": carb,
        "patient": patient,
        "hold": hold,
        "order": order,
    }


def _revision_cycle_scenario():
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    patient = new_patient(ward["id"], mrn="MRN-6001")
    order = draft_diet_order(patient["id"], rule["id"], PHYSICIAN_1)
    return {"ward": ward, "rule": rule, "patient": patient, "order": order}


def _supersede_scenario():
    """An ACTIVE order with one VALIDATED tray, plus a successor in PENDING_COSIGN."""
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    broth = new_menu_item("SOU-BRO")
    patient = new_patient(ward["id"], mrn="MRN-9001", texture_level="PUREED")
    order_one = create_active_diet_order(patient["id"], rule["id"])
    period = new_meal_period(ward["id"])
    set_clock("2026-08-02T09:00:00Z")
    tray = place_tray(
        patient["id"], period["id"], order_one["id"], [line(broth["id"], 1)],
        order_one["version"],
    )
    validate_tray(tray["id"])
    order_two = draft_diet_order(
        patient["id"], rule["id"], PHYSICIAN_1, texture_level="PUREED"
    )
    submit_diet_order(order_two["id"], PHYSICIAN_1)
    return {
        "ward": ward,
        "rule": rule,
        "menu_item": broth,
        "patient": patient,
        "order_one": order_one,
        "order_two": order_two,
        "period": period,
        "tray": tray,
    }


class TestEffectiveEnvelope:
    def test_layered_rules_resolve_the_smallest_nutrient_ceilings(self, api):
        """PRD §3.4: "For each nutrient in turn, gather the ceilings the
        participating rules declare, ignoring any rule whose ceiling for that
        nutrient is null."
        PRD §3.4: "`effective_sodium_cap_mg` is resolved this way from each rule's
        `max_sodium_mg_per_meal`, `effective_potassium_cap_mg` from each rule's
        `max_potassium_mg_per_meal`, and `effective_carb_cap_g` from each rule's
        `max_carb_g_per_meal`."
        PRD §3.4: "If instead the patient's `npo_status` reads `NPO_CLEAR_LIQUIDS`,
        then `effective_texture_level` is forced to `LIQUIDISED`,
        `effective_liquid_level` is **pinned down to `THIN`** even when step three had
        raised it above `THIN`, and the carbohydrate ceiling is capped at fifteen
        grams: if `effective_carb_cap_g` was null it becomes 15.0, and otherwise it
        becomes the smaller of its current value and 15.0."
        PRD §3.3: "The order moves `PENDING_COSIGN → ACTIVE`, recording
        `cosigned_by_user_id` from the acting `X-User-ID`, setting `effective_from` to
        the logical-clock instant, and recomputing the effective envelope."

        Design: Difficulty/combinatorial_formula/effective_envelope_layers_two_rules_patient_floor_and_npo_override
        """
        scenario = _envelope_scenario()

        activated = validate_success(
            api.cosign_diet_order(scenario["order"]["id"], DIETITIAN), 200
        )
        assert_diet_order(activated)

        assert activated["status"] == "ACTIVE"
        # renal 700 vs carb-modified 1200 -> the smaller wins.
        assert activated["effective_sodium_cap_mg"] == 700
        # only the renal rule declares a potassium ceiling.
        assert activated["effective_potassium_cap_mg"] == 600
        # carb-modified declares 45.0, but the clear-liquids override caps it at 15.0.
        assert activated["effective_carb_cap_g"] == approx1(15.0)

    def test_clear_liquids_override_pins_texture_up_and_thickness_down(self, api):
        """PRD §3.4: "Collect the diet order's own `texture_level`, the patient's
        `texture_level`, and each participating rule's `min_texture_level` where that
        value is not null."
        PRD §3.4: "Collect the diet order's own `liquid_level`, the patient's
        `liquid_level`, and each participating rule's `min_liquid_level` where that
        value is not null."
        PRD §3.4: "If instead the patient's `npo_status` reads `NPO_CLEAR_LIQUIDS`,
        then `effective_texture_level` is forced to `LIQUIDISED`,
        `effective_liquid_level` is **pinned down to `THIN`** even when step three had
        raised it above `THIN`, and the carbohydrate ceiling is capped at fifteen
        grams: if `effective_carb_cap_g` was null it becomes 15.0, and otherwise it
        becomes the smaller of its current value and 15.0."
        PRD §3.4: "`forbidden_tag_codes_effective` is the union of the
        `forbidden_tag_codes` lists of the participating rules with duplicates
        removed."
        PRD §3.8: "**Level one:** the patient's `npo_status` is set to the hold's
        `npo_kind` and `active_procedure_hold_id` is pointed at this hold."

        Design: Difficulty/combinatorial_formula/effective_envelope_layers_two_rules_patient_floor_and_npo_override
        """
        scenario = _envelope_scenario()

        activated = validate_success(
            api.cosign_diet_order(scenario["order"]["id"], DIETITIAN), 200
        )

        # Step two would have produced MINCED_MOIST; step four forces LIQUIDISED.
        assert activated["effective_texture_level"] == "LIQUIDISED"
        # Step three had raised thickness to MODERATELY_THICK; step four pins it down.
        assert activated["effective_liquid_level"] == "THIN"
        assert activated["forbidden_tag_codes_effective"] == ["HIGH_FAT"]

        patient = read_patient(scenario["patient"]["id"])
        assert patient["npo_status"] == "NPO_CLEAR_LIQUIDS"
        assert patient["active_procedure_hold_id"] == scenario["hold"]["id"]


class TestRevisionCycle:
    def test_revision_cycle_traversed_twice_leaves_revision_round_at_two(self, api):
        """PRD §3.3: "Requesting a revision sends it back to the prescriber, parking
        the order in `REVISION_REQUESTED` and moving it `PENDING_COSIGN →
        REVISION_REQUESTED`; the request carries a free-text `revision_note`, which is
        stored on the order, `revision_round` increments by 1, and `version`
        increments by 1."
        PRD §3.3: "A prescriber then resubmits, moving `REVISION_REQUESTED →
        PENDING_COSIGN` — again requiring the patient to be `ADMITTED` and the
        referenced rules to be `ACTIVE`, again recomputing the effective envelope, and
        again bumping `version` — which closes the cycle `PENDING_COSIGN →
        REVISION_REQUESTED → PENDING_COSIGN`."

        Design: Difficulty/non_linear_state_machine/diet_order_revision_cycle_returns_twice_to_pending_cosign
        """
        scenario = _revision_cycle_scenario()
        order_id = scenario["order"]["id"]

        submitted = validate_success(api.submit_diet_order(order_id, PHYSICIAN), 200)
        assert submitted["status"] == "PENDING_COSIGN"
        assert submitted["revision_round"] == 0

        first_revision = validate_success(
            api.request_diet_order_revision(order_id, "First pass", DIETITIAN), 200
        )
        assert first_revision["status"] == "REVISION_REQUESTED"
        assert first_revision["revision_round"] == 1
        assert first_revision["revision_note"] == "First pass"

        back_to_cosign = validate_success(api.submit_diet_order(order_id, PHYSICIAN), 200)
        assert back_to_cosign["status"] == "PENDING_COSIGN"
        assert back_to_cosign["revision_round"] == 1

        second_revision = validate_success(
            api.request_diet_order_revision(order_id, "Second pass", DIETITIAN), 200
        )
        assert second_revision["status"] == "REVISION_REQUESTED"
        assert second_revision["revision_round"] == 2

        second_return = validate_success(api.submit_diet_order(order_id, PHYSICIAN), 200)
        assert second_return["status"] == "PENDING_COSIGN", (
            "the second traversal returns the order to a state it already occupied"
        )
        assert second_return["revision_round"] == 2
        assert second_return["revision_note"] == "Second pass"

    def test_cosign_after_two_revision_rounds_activates_the_order(self, api):
        """PRD §3.3: "The order moves `PENDING_COSIGN → ACTIVE`, recording
        `cosigned_by_user_id` from the acting `X-User-ID`, setting `effective_from` to
        the logical-clock instant, and recomputing the effective envelope."
        PRD §3.3: "The patient's `active_diet_order_id` is repointed at this order."
        PRD §2.4: "Before the clock has ever been set, it reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time."

        Design: Difficulty/non_linear_state_machine/diet_order_revision_cycle_returns_twice_to_pending_cosign
        """
        scenario = _revision_cycle_scenario()
        order_id = scenario["order"]["id"]

        submit_diet_order(order_id, PHYSICIAN_1)
        validate_success(
            api.request_diet_order_revision(order_id, "First pass", DIETITIAN), 200
        )
        submit_diet_order(order_id, PHYSICIAN_1)
        validate_success(
            api.request_diet_order_revision(order_id, "Second pass", DIETITIAN), 200
        )
        submit_diet_order(order_id, PHYSICIAN_1)

        activated = validate_success(api.cosign_diet_order(order_id, DIETITIAN), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["revision_round"] == 2
        assert activated["revision_note"] == "Second pass"
        assert activated["cosigned_by_user_id"] == DIETITIAN_1
        assert_instant_equals(
            activated["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
        )

        patient = read_patient(scenario["patient"]["id"])
        assert patient["active_diet_order_id"] == order_id


class TestSupersessionCascade:
    def test_cosign_supersedes_the_predecessor_and_repins_its_tray(self, api):
        """PRD §3.3: "**Level one:** if the patient already had a diet order in
        `ACTIVE`, that predecessor moves `ACTIVE → SUPERSEDED`; the predecessor records
        `superseded_by_diet_order_id` pointing at the new order, and the new order
        records `supersedes_diet_order_id` pointing back at the predecessor, forming
        the supersede chain that the diet-order listing exposes through its
        `supersedes_diet_order_id` filter alongside `patient_id`, `status`,
        `primary_diet_rule_id` and `secondary_diet_rule_id`."
        PRD §3.3: "**Level two:** because the predecessor is no longer `ACTIVE`, every
        meal order pinned to it whose fulfillment dimension reads `PENDING_VALIDATION`
        or `VALIDATED` is re-pinned onto the new order — its `diet_order_id` and
        `pinned_diet_order_version` are updated to the new order and the new order's
        current `version` — its fulfillment dimension is forced back to
        `PENDING_VALIDATION`, and `revalidation_required` is set true."

        Design: Difficulty/transitive_cascade/diet_order_cosign_cascades_supersede_repin_and_slot_release
        """
        scenario = _supersede_scenario()

        activated = validate_success(
            api.cosign_diet_order(scenario["order_two"]["id"], DIETITIAN), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["supersedes_diet_order_id"] == scenario["order_one"]["id"]

        predecessor = read_diet_order(scenario["order_one"]["id"])
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["superseded_by_diet_order_id"] == scenario["order_two"]["id"]

        patient = read_patient(scenario["patient"]["id"])
        assert patient["active_diet_order_id"] == scenario["order_two"]["id"]

        tray = read_meal_order(scenario["tray"]["id"])
        assert tray["diet_order_id"] == scenario["order_two"]["id"]
        assert tray["fulfillment_status"] == "PENDING_VALIDATION"
        assert tray["revalidation_required"] is True
        assert tray["pinned_diet_order_version"] == diet_order_version(
            scenario["order_two"]["id"]
        ), "the re-pinned tray must carry the successor's current version"

    def test_repinned_tray_returns_its_slot_and_cents_to_the_period(self, api):
        """PRD §3.3: "**Level three:** because each re-pinned tray that had been
        `VALIDATED` left a committed state, its meal period decrements its committed
        tray count by one and subtracts that tray's `food_cost_cents` from its
        committed cents."
        PRD §3.3: "**Level four:** because the committed cents moved, that meal period
        re-runs its cost rollup across `period_overhead_cents`,
        `period_bulk_discount_cents` and `period_total_cost_cents`, and recomputes
        `forecast_variance_pct` whenever `forecast_tray_count` is neither null nor
        zero."

        Design: Difficulty/transitive_cascade/diet_order_cosign_cascades_supersede_repin_and_slot_release
        """
        scenario = _supersede_scenario()

        before = read_meal_period(scenario["period"]["id"])
        assert before["committed_tray_count"] == 1
        assert before["committed_food_cost_cents"] == 211

        cosign_diet_order(scenario["order_two"]["id"], DIETITIAN_1)

        after = read_meal_period(scenario["period"]["id"])
        assert after["committed_tray_count"] == 0
        assert after["committed_food_cost_cents"] == 0
        assert after["period_overhead_cents"] == 0
        assert after["period_bulk_discount_cents"] == 0
        assert after["period_total_cost_cents"] == 0

        tray = read_meal_order(scenario["tray"]["id"])
        assert tray["food_cost_cents"] == 211, "the tray keeps its own priced cost"


class TestDietOrderTransitions:
    def test_submit_auto_activates_when_no_rule_requires_cosign(self, api):
        """PRD §3.3: "If instead the primary rule's `requires_dietitian_cosign` is
        false **and** either no secondary rule is present or the secondary rule's
        `requires_dietitian_cosign` is also false, the very same submission moves
        `DRAFT → ACTIVE` directly: the envelope is recomputed, `effective_from` is set
        to the current logical-clock instant, `cosigned_by_user_id` is explicitly left
        null to record that nobody cosigned, the full activation cascade described
        below runs, and `version` increments by 1."
        PRD §3.4: "If at least one rule declares a ceiling, the effective ceiling is
        the **smallest** of them; if every participating rule declares null, the
        effective ceiling is null, meaning uncapped."

        Design: Corner/state_machines/diet_order_submit_auto_activates_when_no_rule_requires_cosign
        """
        ward = new_ward()
        rule = new_diet_rule("CARB_MOD")
        patient = new_patient(ward["id"], mrn="MRN-S001", full_name="Sam Vale",
                              age_years=59)
        order = draft_diet_order(patient["id"], rule["id"], PHYSICIAN_1)

        activated = validate_success(api.submit_diet_order(order["id"], PHYSICIAN), 200)

        assert activated["status"] == "ACTIVE"
        assert activated["cosigned_by_user_id"] is None
        assert_instant_equals(
            activated["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
        )
        assert activated["effective_sodium_cap_mg"] == 1200
        assert activated["effective_carb_cap_g"] == approx1(45.0)
        assert activated["effective_potassium_cap_mg"] is None

        patient_after = read_patient(patient["id"])
        assert patient_after["active_diet_order_id"] == order["id"]

    def test_fourth_request_revision_returns_revision_limit_exceeded(self, api):
        """PRD §3.3: "That cycle is not unbounded: a revision may be requested only
        while the order's `revision_round` is **strictly less than three**, so the
        third completed round is the last, and a fourth attempt is rejected with
        `ERR_REVISION_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/diet_order_fourth_request_revision_returns_revision_limit_exceeded
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-T001", full_name="Tor Nyman",
                              age_years=63)
        order = draft_diet_order(patient["id"], rule["id"], PHYSICIAN_1)
        order_id = order["id"]

        for round_number in (1, 2, 3):
            submit_diet_order(order_id, PHYSICIAN_1)
            revised = validate_success(
                api.request_diet_order_revision(
                    order_id, f"Round {round_number}", DIETITIAN
                ),
                200,
            )
            assert revised["revision_round"] == round_number
        submit_diet_order(order_id, PHYSICIAN_1)

        response = api.request_diet_order_revision(order_id, "Round 4", DIETITIAN)
        validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED, 422)

        final = read_diet_order(order_id)
        assert final["status"] == "PENDING_COSIGN"
        assert final["revision_round"] == 3
        assert final["revision_note"] == "Round 3"

    def test_cosign_from_draft_returns_invalid_state(self, api):
        """PRD §3.3: "A `Dietitian` cosigns a `PENDING_COSIGN` order whose patient is
        still `ADMITTED`, and whose `ordering_physician_user_id` differs from the
        cosigner's own `X-User-ID` — a match is `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "`SUPERSEDED` and `DISCONTINUED` are both terminal; any further
        transition attempt from either reports `ERR_INVALID_STATE`, as does any
        transition attempted from a state the transition does not declare — including
        a second attempt at a transition that already succeeded."
        PRD §3.3: "Its `cosigned_by_user_id`, `revision_note`, `effective_from`,
        `supersedes_diet_order_id` and `superseded_by_diet_order_id` are all null at
        this point, and `linked_meal_order_count` is 0."

        Design: Corner/state_machines/diet_order_cosign_from_draft_returns_invalid_state
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-U001", full_name="Uma Sen",
                              age_years=41)
        order = draft_diet_order(patient["id"], rule["id"], PHYSICIAN_1)
        assert order["status"] == "DRAFT"

        response = api.cosign_diet_order(order["id"], DIETITIAN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = read_diet_order(order["id"])
        assert after["status"] == "DRAFT"
        assert after["cosigned_by_user_id"] is None
        assert read_patient(patient["id"])["active_diet_order_id"] is None
