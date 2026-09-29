"""Rule-by-rule validation: submit gates, window gates and issue gates."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    ISSUING_MANAGER,
    PRINTER,
    QUALITY,
    ApiErrorId,
    append_seal_specimens,
    build_food_recipe_draft,
    build_non_food_recipe_draft,
    create_compliance_dossier_payload,
    create_extrusion_line_payload,
    create_extrusion_run_payload,
    create_seal_test_payload,
    get_success_data,
    pcr_grade_payload,
    setup_approved_food_recipe,
    setup_bag_lot_qualified,
    setup_food_contact_catalog,
    setup_mounted_plate,
    setup_non_food_bag_lot,
    setup_non_food_catalog,
    setup_print_job_in_setup,
    validate_error,
    validate_paginated,
    validate_success,
)

# A food recipe with an unapproved post-consumer grade in layer 1.
PCR_FOOD_COMPONENTS = (
    (1, "VIRGIN", 30.0, "g_pc"),
    (2, "VIRGIN", 2.5, "g_ev"),
    (2, "VIRGIN", 7.5, "g_ti"),
    (3, "VIRGIN", 50.0, "g_ll"),
    (3, "ADDITIVE", 10.0, "g_ad"),
)

# A three-layer food recipe with no barrier resin anywhere in it.
BARRIERLESS_FOOD_COMPONENTS = (
    (1, "VIRGIN", 30.0, "g_ll"),
    (2, "VIRGIN", 20.0, "g_ll"),
    (3, "VIRGIN", 40.0, "g_ll"),
    (3, "ADDITIVE", 10.0, "g_ad"),
)

NON_FOOD_SPECIMENS = ((1, 20.0), (2, 19.0), (3, 21.0))


class TestRecipeSubmitWeightGate:
    """The weight total is checked at submit, not at component insertion."""

    def test_a_ninety_percent_total_is_refused_at_submit(self, api):
        """The single 90.000 % line was accepted; the submit is not.

        PRD: "`total_weight_pct` must be exactly 100.000 — anything else, including
        an empty component list, is refused with `ERR_BLEND_WEIGHT_NOT_100`."

        Design: Corner/validations/submitting_a_recipe_whose_weights_total_ninety_percent_is_rejected
        """
        world = setup_non_food_catalog(api)
        recipe = build_non_food_recipe_draft(
            api, world, recipe_code="R-NF-W",
            components=((1, "VIRGIN", 90.0, "g_ll"),))
        assert recipe["total_weight_pct"] == pytest.approx(90.000, abs=0.001)

        validate_error(api.submit_blend_recipe(recipe["id"], ENGINEER),
                       ApiErrorId.ERR_BLEND_WEIGHT_NOT_100, 422)

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["status"] == "DRAFT"
        assert stored["total_weight_pct"] == pytest.approx(90.000, abs=0.001)
        assert stored["submitted_by_user_id"] is None


class TestConformingRecipeSubmit:
    """With every gate satisfied the transition is simply taken."""

    def test_the_transition_is_taken_and_the_submitter_is_stamped(self, api):
        """A 100.000 % single-layer recipe clears all seven gates.

        PRD: "A `BlendEngineer` submits a `DRAFT` recipe for quality review,
        moving `status` along `DRAFT → SUBMITTED`." And: "A successful submit
        stamps `submitted_by_user_id` with the acting `X-User-ID` and clears any
        previous `rejection_reason`."

        Design: Corner/validations/submitting_a_fully_conforming_recipe_succeeds
        """
        world = setup_non_food_catalog(api)
        recipe = build_non_food_recipe_draft(api, world, recipe_code="R-NF-0")

        submitted = validate_success(
            api.submit_blend_recipe(recipe["id"], ENGINEER), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "u-be-1"
        assert submitted["rejection_reason"] is None

    def test_the_gates_that_passed_are_visible_on_the_recipe(self, api):
        """A strength of 42.00 clears the product's 25.0 floor.

        PRD: "And `strength_index` must be at least the product's
        `min_strength_index`, or `ERR_STRENGTH_INDEX_BELOW_MIN`."

        Design: Corner/validations/submitting_a_fully_conforming_recipe_succeeds
        """
        world = setup_non_food_catalog(api)
        recipe = build_non_food_recipe_draft(api, world, recipe_code="R-NF-0")
        get_success_data(api.submit_blend_recipe(recipe["id"], ENGINEER))

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["strength_index"] == pytest.approx(42.00, abs=0.01)
        assert stored["regrind_pct"] == pytest.approx(0.000, abs=0.001)
        assert stored["food_contact_eligible"] is True


class TestFoodContactResinGate:
    """An ineligible resin is a compliance failure, screened before structure."""

    def test_an_unapproved_grade_in_a_food_blend_is_refused(self, api):
        """PC-7007 is not approved for food contact, and the product demands it.

        PRD: "When the product requires food contact, every virgin and additive
        component's resin must be `food_contact_approved`, or
        `ERR_FOOD_CONTACT_RESIN_INELIGIBLE`."

        Design: Corner/validations/a_food_recipe_containing_an_unapproved_resin_is_rejected_before_the_referential_rules
        """
        world = setup_food_contact_catalog(api)
        world["g_pc"] = get_success_data(
            api.create_resin_grade(pcr_grade_payload(), ADMIN))
        recipe = build_food_recipe_draft(api, world, recipe_code="R-FD-9",
                                        components=PCR_FOOD_COMPONENTS)

        validate_error(api.submit_blend_recipe(recipe["id"], ENGINEER),
                       ApiErrorId.ERR_FOOD_CONTACT_RESIN_INELIGIBLE, 422)

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["status"] == "DRAFT"
        assert stored["total_weight_pct"] == pytest.approx(100.000, abs=0.001)
        assert stored["barrier_layer_present"] is True
        assert stored["virgin_pcr_pct"] == pytest.approx(30.000, abs=0.001)
        assert stored["food_contact_eligible"] is False
        assert stored["strength_index"] == pytest.approx(33.97, abs=0.01)
        assert stored["regrind_cap_pct"] == pytest.approx(5.000, abs=0.001)


class TestBarrierStructureGate:
    """A three-layer food product demands a barrier resin somewhere in it."""

    @staticmethod
    def _barrierless_recipe(api):
        world = setup_food_contact_catalog(api)
        return build_food_recipe_draft(api, world, recipe_code="R-FD-12",
                                       components=BARRIERLESS_FOOD_COMPONENTS)

    def test_a_barrierless_three_layer_food_recipe_is_refused(self, api):
        """Four LLDPE and additive lines carry no barrier grade at all.

        PRD: "When the product's `required_layer_count` is three or more,
        `barrier_layer_present` must be true, or
        `ERR_BARRIER_STRUCTURE_REQUIRED`."

        Design: Corner/validations/a_three_layer_food_recipe_without_a_barrier_resin_is_rejected
        """
        recipe = self._barrierless_recipe(api)

        validate_error(api.submit_blend_recipe(recipe["id"], ENGINEER),
                       ApiErrorId.ERR_BARRIER_STRUCTURE_REQUIRED, 422)

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["barrier_layer_present"] is False
        assert stored["total_weight_pct"] == pytest.approx(100.000, abs=0.001)
        assert stored["status"] == "DRAFT"

    def test_the_refused_recipe_still_carries_its_derived_figures(self, api):
        """The 940.0 additive line lifts the blended density to 920.20.

        PRD: "Each line's contribution is its `weight_pct` divided by one
        hundred, multiplied by the relevant unit value, and **rounded to two
        decimals at the line**."

        Design: Corner/validations/a_three_layer_food_recipe_without_a_barrier_resin_is_rejected
        """
        recipe = self._barrierless_recipe(api)
        validate_error(api.submit_blend_recipe(recipe["id"], ENGINEER),
                       ApiErrorId.ERR_BARRIER_STRUCTURE_REQUIRED, 422)

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["strength_index"] == pytest.approx(40.09, abs=0.01)
        assert stored["blended_density_kg_m3"] == pytest.approx(920.20, abs=0.01)


class TestFoodCertifiedLineGate:
    """The line is geometrically fine and fails only on its certification."""

    def test_scheduling_food_work_on_an_uncertified_line_is_refused(self, api):
        """L-NF can carry the geometry but is not certified for food contact.

        PRD: "a `RESTRICTED` line still accepts non-food work. Food-contact
        products additionally demand a `food_contact_certified` line, or
        `ERR_LINE_NOT_FOOD_CERTIFIED`." And: "the recipe's `layer_count` may not
        exceed the line's `max_layers`, the recipe's `process_type` must match
        the line's `process_type`".

        Design: Corner/validations/a_food_contact_run_on_an_uncertified_line_is_rejected
        """
        world = setup_approved_food_recipe(api)
        uncertified = get_success_data(
            api.create_extrusion_line(create_extrusion_line_payload(), ADMIN))
        assert uncertified["food_contact_certified"] is False

        error = validate_error(api.create_extrusion_run(
            create_extrusion_run_payload(uncertified["id"], world["recipe"]["id"],
                                         run_code="RUN-X-1",
                                         scheduled_start="2026-08-05T07:00:00Z",
                                         scheduled_end="2026-08-05T15:00:00Z"),
            EXTRUDER), ApiErrorId.ERR_LINE_NOT_FOOD_CERTIFIED, 422)
        assert error["error_id"] != ApiErrorId.ERR_LINE_CAPABILITY_MISMATCH

        _rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": uncertified["id"]}))
        assert meta["total_count"] == 0

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["pinned_run_count"] == 0


class TestPrintWindowGate:
    """A job dialled in today still cannot print inside tomorrow's window."""

    def test_starting_before_the_window_opens_is_refused(self, api):
        """Registration and colour both pass; only the clock is wrong.

        PRD: "the current logical clock at or after `window_start`, an earlier
        clock yielding `ERR_PRINT_WINDOW_NOT_OPEN`." And: "`registration_state`
        becomes `REG_PASS` when the recorded drift is no greater than the press's
        `registration_tolerance_micron`".

        Design: Corner/validations/starting_a_print_before_the_window_opens_is_rejected
        """
        world = setup_mounted_plate(api)
        world = setup_print_job_in_setup(api, world, job_code="PJ-D",
                                        roll_number=2,
                                        window_start="2026-08-06T06:00:00Z",
                                        window_end="2026-08-06T18:00:00Z")
        job_id = world["print_job"]["id"]
        get_success_data(api.registration_check(job_id, 40.0, PRINTER))
        proofed = get_success_data(api.color_proof(job_id, 1.2, PRINTER))
        assert proofed["registration_state"] == "REG_PASS"
        assert proofed["color_state"] == "COLOR_PASS"

        error = validate_error(api.start_print(job_id, PRINTER),
                               ApiErrorId.ERR_PRINT_WINDOW_NOT_OPEN, 409)
        assert error["error_id"] != ApiErrorId.ERR_PRINT_JOB_STATE_INVALID

        job = get_success_data(api.get_print_job(job_id, PRINTER))
        assert job["status"] == "SETUP"


class TestClaimOverstatementGate:
    """An all-virgin lot cannot carry a five percent recycled claim."""

    @staticmethod
    def _lot_and_an_overstated_dossier(api):
        world = setup_bag_lot_qualified(api)
        world["dossier"] = get_success_data(api.create_compliance_dossier(
            create_compliance_dossier_payload(world["bag_lot"]["id"],
                                              dossier_code="CD-5",
                                              food_contact_declared=True,
                                              recycled_content_claim_pct=5.0),
            ISSUING_MANAGER))
        return world

    def test_issuing_an_overstated_claim_is_refused(self, api):
        """A 5.0 % claim against a 0.000 as-built figure overshoots by 4.500.

        PRD: "A claim that would land `OVERSTATED` is refused outright with
        `ERR_CLAIM_OVERSTATED`; understating is permitted, since a conservative
        claim harms nobody."

        Design: Corner/validations/a_recycled_content_claim_above_the_as_built_figure_is_rejected
        """
        world = self._lot_and_an_overstated_dossier(api)
        assert world["bag_lot"]["actual_recycled_content_pct"] == pytest.approx(
            0.000, abs=0.001)

        validate_error(
            api.issue_compliance_dossier(world["dossier"]["id"], ISSUING_MANAGER),
            ApiErrorId.ERR_CLAIM_OVERSTATED, 422)

    def test_the_refused_issue_leaves_the_dossier_in_draft(self, api):
        """Nothing is frozen because the claim never passed the gate.

        PRD: "The dossier begins in `DRAFT` with `as_built_recycled_content_pct` and
        `claim_variance_pct` null and `claim_conformance` reading `PENDING`."

        Design: Corner/validations/a_recycled_content_claim_above_the_as_built_figure_is_rejected
        """
        world = self._lot_and_an_overstated_dossier(api)
        validate_error(
            api.issue_compliance_dossier(world["dossier"]["id"], ISSUING_MANAGER),
            ApiErrorId.ERR_CLAIM_OVERSTATED, 422)

        dossier = get_success_data(
            api.get_compliance_dossier(world["dossier"]["id"], QUALITY))
        assert dossier["status"] == "DRAFT"
        assert dossier["issued_at"] is None
        assert dossier["issued_by_user_id"] is None
        assert dossier["claim_conformance"] == "PENDING"
        assert dossier["recycled_content_claim_pct"] == pytest.approx(5.0, abs=0.01)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "QUALIFIED"


class TestConvertingFeatureVerificationGate:
    """A perforated, gusseted product must be confirmed before seal testing."""

    def test_seal_testing_an_unverified_lot_is_refused(self, api):
        """Both confirmations are false on a GUSSETED, perforated product.

        PRD: "a product whose `perforation_required` is true demands
        `perforation_verified` as true, and a product whose `bag_style` is
        `GUSSETED` demands `gusset_verified` as true; either shortfall is refused
        with `ERR_CONVERTING_FEATURE_NOT_VERIFIED`."

        Design: Corner/validations/seal_testing_a_lot_whose_converting_features_are_unverified_is_rejected
        """
        world = setup_non_food_bag_lot(api, perforation_verified=False,
                                       gusset_verified=False)

        validate_error(api.add_seal_test(world["bag_lot"]["id"],
                                        create_seal_test_payload(1, 20.0),
                                        CONVERTER),
                       ApiErrorId.ERR_CONVERTING_FEATURE_NOT_VERIFIED, 422)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["perforation_verified"] is False
        assert lot["gusset_verified"] is False
        assert lot["status"] == "CONVERTING"
        assert lot["seal_specimens"] == []

    def test_the_lots_count_block_is_unaffected_by_the_refusal(self, api):
        """A 400 mm layflat with a 60 mm gusset weighs 0.019388 kg a bag.

        PRD: "`bag_unit_weight_kg` is the product's `layflat_width_mm` divided by
        one thousand, multiplied by two, multiplied by the sum of `bag_length_mm`
        and `gusset_depth_mm` divided by one thousand".

        Design: Corner/validations/seal_testing_a_lot_whose_converting_features_are_unverified_is_rejected
        """
        world = setup_non_food_bag_lot(api, perforation_verified=False,
                                       gusset_verified=False)
        validate_error(api.add_seal_test(world["bag_lot"]["id"],
                                        create_seal_test_payload(1, 20.0),
                                        CONVERTER),
                       ApiErrorId.ERR_CONVERTING_FEATURE_NOT_VERIFIED, 422)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["bag_unit_weight_kg"] == pytest.approx(0.019388, abs=0.000001)
        assert lot["bag_count_theoretical"] == 5157


class TestFoodDeclarationGate:
    """The declaration is checked five hops back, at the producing line."""

    def test_declaring_food_contact_on_a_non_certified_chain_is_refused(self, api):
        """The lot's roll came off the uncertified line L-NF.

        PRD: "when `food_contact_declared` is true, the lot's blend recipe must
        carry `food_contact_eligible` as true and the producing line must be
        `food_contact_certified`, or `ERR_FOOD_CONTACT_DECLARATION_INVALID`."

        Design: Corner/validations/a_food_contact_declaration_on_a_lot_from_an_uncertified_line_is_rejected
        """
        world = setup_non_food_bag_lot(api)
        append_seal_specimens(api, world["bag_lot"]["id"], NON_FOOD_SPECIMENS,
                              CONVERTER)
        lot = get_success_data(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER))
        assert lot["status"] == "QUALIFIED"
        assert lot["seal_final_min_n"] == pytest.approx(19.00, abs=0.01)
        assert lot["seal_final_verdict"] == "PASS"

        dossier = get_success_data(api.create_compliance_dossier(
            create_compliance_dossier_payload(world["bag_lot"]["id"],
                                              dossier_code="CD-NF",
                                              food_contact_declared=True,
                                              recycled_content_claim_pct=0.0),
            ISSUING_MANAGER))

        error = validate_error(
            api.issue_compliance_dossier(dossier["id"], ISSUING_MANAGER),
            ApiErrorId.ERR_FOOD_CONTACT_DECLARATION_INVALID, 422)
        assert error["error_id"] != ApiErrorId.ERR_CLAIM_OVERSTATED

        stored = get_success_data(
            api.get_compliance_dossier(dossier["id"], QUALITY))
        assert stored["status"] == "DRAFT"
        assert stored["issued_at"] is None
