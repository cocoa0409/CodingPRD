"""Rejection rules on master data, hydraulic sizing and the foundry floor.

Everything here is a refusal, and every refusal is checked twice over: the
contract's own error identifier comes back, and the world the caller tried to
change is still exactly as it was - no row created, no ledger moved, no parent
version advanced.  The gates covered are code uniqueness, the four fluid
ceilings of a material and seal configuration, the flow and geometry envelope of
a hydraulic model, the referential and state preconditions of sizing, and the
alloy, scope, window, suspension, tooling-state, quantity, defect-ledger and
acceptance rules that guard a pour.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def _selection_count(api, headers) -> int:
    """How many selections exist right now."""
    _, meta = validate_paginated(api.list_selections(headers))
    return meta["total_count"]


def _casting_lot_count(api, headers) -> int:
    """How many casting lots exist right now."""
    _, meta = validate_paginated(api.list_casting_lots(headers))
    return meta["total_count"]


# ─────────────────────────────────────────────────────────────────────────────
# Unique codes
# ─────────────────────────────────────────────────────────────────────────────
class TestFoundryUniqueness:
    """A foundry code is an external reference and may be claimed only once."""

    def test_second_foundry_reusing_an_existing_code_is_rejected(
        self, api, admin_headers
    ):
        """The duplicate loses even though every other field differs.

        PRD 3.1: "Any of the seven unique codes in the system — `foundry_code`,
        `model_code`, `pattern_code`, `config_code`, `application_code`,
        `serial_number` and `kit_code` — repeating an existing value is rejected
        with `ERR_DUPLICATE_CODE`."

        Design: Corner/validations/duplicate_foundry_code_returns_duplicate_code
        """
        first = X.create_foundry(api, foundry_code="FDY-NORTH")

        response = api.create_foundry(
            F.foundry_payload(
                foundry_code="FDY-NORTH",
                name="Rival Iron Works",
                approved_alloys=["CN7M"],
                concurrent_pour_capacity=9,
            ),
            admin_headers,
        )
        validate_error(response, ApiErrorId.DUPLICATE_CODE)

        _, meta = validate_paginated(api.list_foundries(admin_headers))
        assert meta["total_count"] == 1, "the rejected registration must not persist"

        kept = get_success_data(api.get_foundry(first["id"], admin_headers))
        assert kept["name"] == "North Iron Works"
        assert kept["concurrent_pour_capacity"] == 2
        assert kept["approved_alloys"] == ["CI_GG25", "DUPLEX_S31803"]
        assert kept["version"] == 1, "a refused duplicate must not mutate the winner"


# ─────────────────────────────────────────────────────────────────────────────
# The four fluid ceilings and the service class of a configuration
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionProcessLimits:
    """The configuration's fluid ceilings gate sizing before the curve is sold."""

    @staticmethod
    def _size(api, world, duty, headers):
        return api.create_selection(
            F.selection_payload(
                duty["id"], world["model"]["id"], world["config"]["id"], duty["version"]
            ),
            headers,
        )

    def test_duty_above_the_configuration_temperature_ceiling_is_refused(
        self, api, engineer_headers
    ):
        """A 130.0 C duty cannot be served by a 120.0 C configuration.

        PRD 3.2: "In ladder order: `process_temp_c` must not exceed
        `max_temp_c`, else `ERR_TEMPERATURE_LIMIT_EXCEEDED`; `chloride_ppm` must
        not exceed `max_chloride_ppm`, else `ERR_CHLORIDE_LIMIT_EXCEEDED`;
        `solids_pct` must not exceed `max_solids_pct`, else
        `ERR_SOLIDS_LIMIT_EXCEEDED`; `viscosity_cst` must not exceed
        `max_viscosity_cst`, else `ERR_VISCOSITY_LIMIT_EXCEEDED`; the
        configuration's `service_class` must equal the enquiry's
        `service_class_required`, else `ERR_SERVICE_CLASS_MISMATCH`;
        `duty_flow_m3h` must not exceed the model's `max_flow_m3h`, else
        `ERR_DUTY_FLOW_ABOVE_MAX`; the rounded `trimmed_impeller_diameter_mm`
        must be at least `min_impeller_diameter_mm`, else
        `ERR_TRIM_BELOW_MINIMUM`; the same rounded diameter must not exceed
        `max_impeller_diameter_mm`, else `ERR_DUTY_POINT_ABOVE_ENVELOPE`; and
        finally `predicted_efficiency_pct` must be at least the enquiry's
        `min_efficiency_pct`, compared inclusively, else
        `ERR_EFFICIENCY_TARGET_NOT_MET`."

        Design: Corner/validations/selection_above_config_temperature_limit_returns_temperature_limit_exceeded
        """
        world = X.setup_master_data(api)
        assert world["config"]["max_temp_c"] == pytest.approx(120.0, abs=0.01)
        duty = X.create_duty_application(api, process_temp_c=130.0)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.TEMPERATURE_LIMIT_EXCEEDED)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1, "a refused sizing must not touch the enquiry"

    def test_duty_above_the_configuration_chloride_ceiling_is_refused(
        self, api, engineer_headers
    ):
        """250.0 ppm of chloride against cast-iron wetted parts rated to 200.0.

        PRD 3.2: "`chloride_ppm` must not exceed `max_chloride_ppm`, else
        `ERR_CHLORIDE_LIMIT_EXCEEDED`". The duty runs at 60.0 C, inside the
        configuration's temperature ceiling, so the chloride gate is the only one
        that can fire.

        Design: Corner/validations/selection_above_config_chloride_limit_returns_chloride_limit_exceeded
        """
        world = X.setup_master_data(api)
        assert world["config"]["max_chloride_ppm"] == pytest.approx(200.0, abs=0.01)
        duty = X.create_duty_application(api, chloride_ppm=250.0, process_temp_c=60.0)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.CHLORIDE_LIMIT_EXCEEDED)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_duty_above_the_configuration_viscosity_ceiling_is_refused(
        self, api, engineer_headers
    ):
        """60.0 centistokes is refused outright, not merely de-rated.

        PRD 3.2: "`viscosity_cst` must not exceed `max_viscosity_cst`, else
        `ERR_VISCOSITY_LIMIT_EXCEEDED`". The viscosity factor that would apply to
        a 60.0 centistoke fluid never gets to act, because the configuration gate
        runs before the efficiency prediction is sold.

        Design: Corner/validations/selection_above_config_viscosity_limit_returns_viscosity_limit_exceeded
        """
        world = X.setup_master_data(api)
        assert world["config"]["max_viscosity_cst"] == pytest.approx(50.0, abs=0.01)
        duty = X.create_duty_application(api, viscosity_cst=60.0)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.VISCOSITY_LIMIT_EXCEEDED)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_corrosive_duty_against_a_clean_rated_configuration_is_refused(
        self, api, engineer_headers
    ):
        """Every numeric ceiling is satisfied and the duty is still refused.

        PRD 3.2: "the configuration's `service_class` must equal the enquiry's
        `service_class_required`, else `ERR_SERVICE_CLASS_MISMATCH`". A
        cast-iron, single-cartridge configuration is released as `CLEAN`, so a
        `CORROSIVE` requirement cannot be served by it.

        Design: Corner/validations/selection_with_corrosive_duty_against_clean_config_returns_service_class_mismatch
        """
        world = X.setup_master_data(api)
        assert world["config"]["service_class"] == "CLEAN"
        duty = X.create_duty_application(api, service_class_required="CORROSIVE")

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.SERVICE_CLASS_MISMATCH)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The flow envelope, the trim geometry and the efficiency guarantee
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionHydraulicEnvelope:
    """Flow envelope, trimmed geometry and the inclusive efficiency target."""

    @staticmethod
    def _size(api, world, duty, headers):
        return api.create_selection(
            F.selection_payload(
                duty["id"], world["model"]["id"], world["config"]["id"], duty["version"]
            ),
            headers,
        )

    def test_duty_flow_above_the_envelope_is_reported_before_the_geometry_it_breaks(
        self, api, engineer_headers
    ):
        """One request breaks both flow and geometry; the flow gate is reported.

        PRD 2.6: "When a request violates more than one rule, exactly one error
        is returned, and which one is fully determined: checks are evaluated in
        the fixed global order below, and the first violated check ends the
        request."
        PRD 3.2: "`duty_flow_m3h` must not exceed the model's `max_flow_m3h`,
        else `ERR_DUTY_FLOW_ABOVE_MAX`; the rounded
        `trimmed_impeller_diameter_mm` must be at least
        `min_impeller_diameter_mm`, else `ERR_TRIM_BELOW_MINIMUM`; the same
        rounded diameter must not exceed `max_impeller_diameter_mm`, else
        `ERR_DUTY_POINT_ABOVE_ENVELOPE`".

        A 400.0 cubic metre per hour duty on a model whose envelope ends at
        380.0 also trims to 387.4 mm against a 355.0 mm full diameter, so both
        gates are live and the earlier rung must win.

        Design: Corner/validations/duty_flow_above_max_outranks_the_envelope_error_it_also_causes
        """
        world = X.setup_master_data(api)
        assert world["model"]["max_flow_m3h"] == pytest.approx(380.0, abs=0.01)
        assert world["model"]["max_impeller_diameter_mm"] == pytest.approx(
            355.0, abs=0.01
        )
        duty = X.create_duty_application(api, duty_flow_m3h=400.0, duty_head_m=74.0)

        response = self._size(api, world, duty, engineer_headers)
        error = validate_error(response, ApiErrorId.DUTY_FLOW_ABOVE_MAX)
        assert error["error_id"] != "ERR_DUTY_POINT_ABOVE_ENVELOPE"

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_low_head_duty_trimming_below_the_casing_minimum_is_refused(
        self, api, engineer_headers
    ):
        """A 100.0 by 30.0 duty solves to 210.1 mm against a 300.0 mm minimum.

        PRD 3.2: "the rounded `trimmed_impeller_diameter_mm` must be at least
        `min_impeller_diameter_mm`, else `ERR_TRIM_BELOW_MINIMUM`". The flow sits
        far inside the model's envelope, so the low-side geometry gate is the
        only one that can fire.

        Design: Corner/validations/low_head_duty_trimming_below_the_minimum_returns_trim_below_minimum
        """
        world = X.setup_master_data(api)
        assert world["model"]["min_impeller_diameter_mm"] == pytest.approx(
            300.0, abs=0.01
        )
        duty = X.create_duty_application(api, duty_flow_m3h=100.0, duty_head_m=30.0)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.TRIM_BELOW_MINIMUM)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_high_head_duty_four_tenths_above_the_full_diameter_is_refused(
        self, api, engineer_headers
    ):
        """355.4 mm of impeller against a 355.0 mm pattern is still too much.

        PRD 3.2: "the same rounded diameter must not exceed
        `max_impeller_diameter_mm`, else `ERR_DUTY_POINT_ABOVE_ENVELOPE`"
        PRD 3.2: "Note which value the two envelope gates read: the rounded
        diameter, not the exact trim ratio."

        A 100.0 by 90.0 duty needs four tenths of a millimetre more impeller
        than the tooling can produce, so the duty point sits above the
        full-diameter curve and may not be quietly clamped to it.

        Design: Corner/validations/high_head_duty_above_the_full_diameter_curve_returns_duty_point_above_envelope
        """
        world = X.setup_master_data(api)
        assert world["model"]["shutoff_head_m"] == pytest.approx(92.0, abs=0.01)
        duty = X.create_duty_application(api, duty_flow_m3h=100.0, duty_head_m=90.0)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.DUTY_POINT_ABOVE_ENVELOPE)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_efficiency_target_set_exactly_at_the_predicted_value_is_accepted(
        self, api, engineer_headers
    ):
        """A target of 80.96 against a predicted 80.96 is contractually met.

        PRD 3.2: "and finally `predicted_efficiency_pct` must be at least the
        enquiry's `min_efficiency_pct`, compared inclusively, else
        `ERR_EFFICIENCY_TARGET_NOT_MET`."

        Design: Corner/validations/efficiency_target_met_exactly_at_the_predicted_value_and_failed_one_hundredth_above
        """
        world = X.setup_master_data(api)
        duty = X.create_duty_application(api, min_efficiency_pct=80.96)

        response = self._size(api, world, duty, engineer_headers)
        selection = validate_success(response, 201)

        assert selection["predicted_efficiency_pct"] == pytest.approx(
            K.SEL_1001_PREDICTED_EFFICIENCY_PCT, abs=0.01
        )
        assert selection["status"] == "DRAFT"
        assert _selection_count(api, engineer_headers) == 1

    def test_efficiency_target_one_hundredth_above_the_predicted_value_is_refused(
        self, api, engineer_headers
    ):
        """A target of 80.97 against the same predicted 80.96 fails.

        PRD 3.2: "and finally `predicted_efficiency_pct` must be at least the
        enquiry's `min_efficiency_pct`, compared inclusively, else
        `ERR_EFFICIENCY_TARGET_NOT_MET`."

        One hundredth of a point above the achievable efficiency is the whole
        difference between an acceptable guarantee and an impossible one.

        Design: Corner/validations/efficiency_target_met_exactly_at_the_predicted_value_and_failed_one_hundredth_above
        """
        world = X.setup_master_data(api)
        duty = X.create_duty_application(api, min_efficiency_pct=80.97)

        response = self._size(api, world, duty, engineer_headers)
        validate_error(response, ApiErrorId.EFFICIENCY_TARGET_NOT_MET)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Referential and state preconditions of sizing
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionReferentialRules:
    """Sizing binds one enquiry, one orderable model and that model's own configuration."""

    def test_configuration_belonging_to_another_model_is_refused(
        self, api, engineer_headers
    ):
        """A configuration released for one model cannot size another.

        PRD 3.2: "the named configuration's `pump_model_id` must equal the
        `pump_model_id` on the request, or `ERR_CONFIG_MODEL_MISMATCH`."

        The foreign configuration is `CLEAN` and rated well beyond the duty, so
        no numeric ceiling of its own could have refused the request.

        Design: Corner/validations/selection_naming_another_models_config_returns_config_model_mismatch
        """
        world = X.setup_master_data(api)
        other_model = X.create_pump_model(api, **K.MODEL_VTP_08)
        foreign_config = X.create_material_seal_config(api, other_model["id"])
        duty = X.create_duty_application(api)

        response = api.create_selection(
            F.selection_payload(
                duty["id"],
                world["model"]["id"],
                foreign_config["id"],
                duty["version"],
            ),
            engineer_headers,
        )
        validate_error(response, ApiErrorId.CONFIG_MODEL_MISMATCH)

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_sizing_against_a_superseded_model_is_refused(
        self, api, admin_headers, engineer_headers
    ):
        """A superseded model is out of the catalogue but still readable.

        PRD 3.2: "the model must be `ORDERABLE`, or `ERR_MODEL_NOT_ORDERABLE`".
        PRD 3.1: "Superseding a model records the successor's identifier in
        `superseded_by_model_id` and moves the model to `SUPERSEDED`."

        Design: Corner/validations/selection_on_superseded_model_returns_model_not_orderable
        """
        world = X.setup_master_data(api)
        successor = X.create_pump_model(api, **K.MODEL_VTP_08)
        get_success_data(
            api.supersede_pump_model(
                world["model"]["id"],
                F.supersede_model_payload(successor["id"]),
                admin_headers,
            )
        )
        duty = X.create_duty_application(api)

        response = api.create_selection(
            F.selection_payload(
                duty["id"], world["model"]["id"], world["config"]["id"], duty["version"]
            ),
            engineer_headers,
        )
        validate_error(response, ApiErrorId.MODEL_NOT_ORDERABLE)

        model = X.reread_pump_model(api, world["model"]["id"])
        assert model["status"] == "SUPERSEDED"
        assert model["superseded_by_model_id"] == successor["id"]

        assert _selection_count(api, engineer_headers) == 0
        after = X.reread_duty_application(api, duty["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == 1

    def test_model_named_as_its_own_successor_is_refused(self, api, admin_headers):
        """A model may not close the interchange chain onto itself.

        PRD 3.1: "The successor must exist and must not be the model itself;
        naming the model's own identifier is rejected with
        `ERR_SUCCESSOR_MODEL_INVALID`."

        Design: Corner/validations/supersede_a_model_by_itself_returns_successor_model_invalid
        """
        model = X.create_pump_model(api)
        assert model["status"] == "ORDERABLE"
        assert model["superseded_by_model_id"] is None

        response = api.supersede_pump_model(
            model["id"], F.supersede_model_payload(model["id"]), admin_headers
        )
        validate_error(response, ApiErrorId.SUCCESSOR_MODEL_INVALID)

        after = X.reread_pump_model(api, model["id"])
        assert after["status"] == "ORDERABLE"
        assert after["superseded_by_model_id"] is None
        assert after["version"] == 1, "a refused supersession must not mutate the model"

    def test_second_selection_on_a_locked_enquiry_is_refused_on_state_not_version(
        self, api, engineer_headers
    ):
        """A freshly read token reaches the openness gate rather than the token gate.

        PRD 3.2: "The enquiry must be `OPEN`, or the request is rejected with
        `ERR_DUTY_APPLICATION_NOT_OPEN`".
        PRD 3.3: "On success the approver's `X-User-ID` is written to
        `approved_by_user_id` and the parent enquiry is driven `OPEN →
        SELECTION_LOCKED`, its `version` incremented."

        The first selection and the approval both moved the enquiry's `version`,
        so the retry re-reads it; with the token current, the only rule left to
        break is the openness of the enquiry itself.

        Design: Corner/validations/second_selection_on_a_locked_duty_application_returns_duty_application_not_open
        """
        ctx = X.setup_approved_selection(api)
        locked = X.reread_duty_application(api, ctx["duty"]["id"])
        assert locked["status"] == "SELECTION_LOCKED"

        response = api.create_selection(
            F.selection_payload(
                locked["id"],
                ctx["model"]["id"],
                ctx["config"]["id"],
                locked["version"],
            ),
            engineer_headers,
        )
        error = validate_error(response, ApiErrorId.DUTY_APPLICATION_NOT_OPEN)
        assert error["error_id"] != "ERR_STALE_DUTY_APPLICATION_VERSION"

        after = X.reread_duty_application(api, locked["id"])
        assert after["status"] == "SELECTION_LOCKED"
        assert after["version"] == locked["version"]
        assert _selection_count(api, engineer_headers) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Recording a pour
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingLotRules:
    """Alloy, scope, window, suspension and tooling state each block a pour on their own."""

    def test_pour_in_an_alloy_the_foundry_is_not_approved_for_is_refused(self, api):
        """An unapproved pour never happened, so the tooling never moved.

        PRD 3.4: "The `alloy_code` must be a member of that foundry's
        `approved_alloys`, else `ERR_ALLOY_NOT_APPROVED`."
        PRD 3.4: "Recording the pour also advances the tooling:
        `pours_since_refurb` on the pattern is incremented by 1 and the
        pattern's `version` is bumped."

        Design: Corner/validations/casting_lot_in_an_alloy_the_foundry_is_not_approved_for_returns_alloy_not_approved
        """
        world = X.setup_master_data(api)
        assert world["foundry"]["approved_alloys"] == ["CI_GG25", "DUPLEX_S31803"]

        response = api.create_casting_lot(
            F.casting_lot_payload(
                world["pattern"]["id"], world["foundry"]["id"], alloy_code="CN7M"
            ),
            world["foundry_headers"],
        )
        validate_error(response, ApiErrorId.ALLOY_NOT_APPROVED)

        assert _casting_lot_count(api, world["foundry_headers"]) == 0
        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["status"] == "QUALIFIED"
        assert pattern["pours_since_refurb"] == 0
        assert pattern["wear_index"] == 0
        assert pattern["version"] == 1

    def test_pour_booked_by_a_different_foundry_is_refused(
        self, api, foundry_partner_headers_factory
    ):
        """One foundry partner may not book a heat against another's pattern.

        PRD 2.1: "Concretely, when a foundry partner records a pour, the
        `foundry_id` supplied in the request body must equal the caller's
        `X-User-ID`, and a mismatch is rejected with
        `ERR_FOUNDRY_SCOPE_VIOLATION` and HTTP 403."

        Design: Corner/validations/casting_lot_posted_by_a_different_foundry_returns_foundry_scope_violation
        """
        world = X.setup_master_data(api)
        southern = X.create_foundry(
            api,
            foundry_code="FDY-SOUTH",
            name="Southern Castings",
            approved_alloys=["CI_GG25"],
            concurrent_pour_capacity=1,
        )
        southern_headers = foundry_partner_headers_factory(southern["id"])

        response = api.create_casting_lot(
            F.casting_lot_payload(world["pattern"]["id"], world["foundry"]["id"]),
            southern_headers,
        )
        validate_error(response, ApiErrorId.FOUNDRY_SCOPE_VIOLATION)

        assert _casting_lot_count(api, southern_headers) == 0
        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 0
        assert pattern["version"] == 1

    @pytest.mark.parametrize(
        ("pour_window_start", "pour_window_end"),
        [
            ("2026-08-10T00:00:00Z", "2026-08-05T00:00:00Z"),
            ("2026-08-05T00:00:00Z", "2026-08-05T00:00:00Z"),
        ],
        ids=["reversed", "zero_length"],
    )
    def test_pour_window_that_does_not_run_forwards_is_refused(
        self, api, pour_window_start, pour_window_end
    ):
        """A reversed window and a zero-length window are both invalid.

        PRD 3.4: "Finally, `pour_window_start` must be strictly before
        `pour_window_end`, else `ERR_INVALID_WINDOW`."

        Design: Corner/validations/casting_lot_with_a_reversed_pour_window_returns_invalid_window
        """
        world = X.setup_master_data(api)

        response = api.create_casting_lot(
            F.casting_lot_payload(
                world["pattern"]["id"],
                world["foundry"]["id"],
                pour_window_start=pour_window_start,
                pour_window_end=pour_window_end,
            ),
            world["foundry_headers"],
        )
        validate_error(response, ApiErrorId.INVALID_WINDOW)

        assert _casting_lot_count(api, world["foundry_headers"]) == 0
        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 0
        assert pattern["version"] == 1

    def test_pour_at_a_suspended_foundry_is_refused(self, api, admin_headers):
        """Suspension bites immediately on the very next heat.

        PRD 3.4: "The foundry must be `ACTIVE`, else `ERR_FOUNDRY_SUSPENDED`."
        PRD 3.1: "Suspension is forward-looking only: existing lots are
        untouched, but a suspended foundry may pour no new ones."

        Design: Corner/validations/casting_lot_at_a_suspended_foundry_returns_foundry_suspended
        """
        world = X.setup_master_data(api)
        get_success_data(
            api.suspend_foundry(
                world["foundry"]["id"],
                F.suspend_foundry_payload(
                    suspension_reason="failed annual alloy audit"
                ),
                admin_headers,
            )
        )

        response = api.create_casting_lot(
            F.casting_lot_payload(world["pattern"]["id"], world["foundry"]["id"]),
            world["foundry_headers"],
        )
        validate_error(response, ApiErrorId.FOUNDRY_SUSPENDED)

        assert _casting_lot_count(api, world["foundry_headers"]) == 0
        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["status"] == "QUALIFIED"
        assert pattern["pours_since_refurb"] == 0
        assert pattern["version"] == 1

    def test_pour_from_a_pattern_withdrawn_for_refurbishment_is_refused(
        self, api, admin_headers, inspector_headers
    ):
        """Tooling in refurbishment takes no further heats.

        PRD 3.4: "The pattern must be `QUALIFIED`; pouring from tooling that is
        `WORN`, `IN_REFURB` or `RETIRED` is rejected with
        `ERR_PATTERN_INVALID_STATE`."
        PRD 3.4: "If that leaves the pattern's model with no `QUALIFIED` pattern
        at all, the model is driven `ORDERABLE → PATTERN_CONSTRAINED` in the same
        request, after which new selections against it are refused."

        The pattern carries a withdrawal threshold of 1, so its very first pour
        wore it out and the model it produces is already constrained by the time
        the second heat is offered.

        Design: Corner/validations/casting_lot_from_a_pattern_in_refurbishment_returns_pattern_invalid_state
        """
        world = X.setup_master_data(api, pattern={"wear_threshold": 1})
        first_lot = X.pour_casting_lot(api, world)
        get_success_data(api.inspect_casting_lot(first_lot["id"], inspector_headers))
        get_success_data(api.accept_casting_lot(first_lot["id"], inspector_headers))
        get_success_data(
            api.start_pattern_refurbishment(world["pattern"]["id"], admin_headers)
        )
        withdrawn = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert withdrawn["status"] == "IN_REFURB"

        response = api.create_casting_lot(
            F.casting_lot_payload(
                world["pattern"]["id"],
                world["foundry"]["id"],
                pour_window_start="2026-08-12T00:00:00Z",
                pour_window_end="2026-08-17T00:00:00Z",
            ),
            world["foundry_headers"],
        )
        validate_error(response, ApiErrorId.PATTERN_INVALID_STATE)

        after = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert after["status"] == "IN_REFURB"
        assert after["wear_index"] == 1
        assert after["version"] == withdrawn["version"]
        assert (
            X.reread_pump_model(api, world["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )
        assert _casting_lot_count(api, world["foundry_headers"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# The strictly-positive quantity lower bounds
# ─────────────────────────────────────────────────────────────────────────────
class TestZeroQuantityLowerBounds:
    """A meaningless quantity is told apart from a malformed request."""

    def test_zero_piece_pour_is_refused_as_a_zero_quantity(self, api):
        """A heat of no pieces is meaningless rather than malformed.

        PRD 2.6: "One deliberate exception: the strictly-positive lower bounds of
        `requested_qty`, `qty_poured`, `affected_qty` and `qty` are *not*
        enforced here but at rungs 12 and 13, so that a zero quantity surfaces as
        `ERR_ZERO_QUANTITY` rather than being masked as a malformed request."

        Design: Corner/validations/zero_quantity_pour_and_zero_quantity_receipt_return_zero_quantity
        """
        world = X.setup_master_data(api)

        response = api.create_casting_lot(
            F.casting_lot_payload(
                world["pattern"]["id"], world["foundry"]["id"], qty_poured=0
            ),
            world["foundry_headers"],
        )
        error = validate_error(response, ApiErrorId.ZERO_QUANTITY)
        assert error["error_id"] != "ERR_INVALID_REQUEST"

        assert _casting_lot_count(api, world["foundry_headers"]) == 0
        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 0
        assert pattern["version"] == 1

    def test_zero_unit_kit_receipt_is_refused_as_a_zero_quantity(
        self, api, planner_headers
    ):
        """Receiving no units leaves every stock counter and the version alone.

        PRD 2.6: "One deliberate exception: the strictly-positive lower bounds of
        `requested_qty`, `qty_poured`, `affected_qty` and `qty` are *not*
        enforced here but at rungs 12 and 13, so that a zero quantity surfaces as
        `ERR_ZERO_QUANTITY` rather than being masked as a malformed request."
        PRD 3.8: "A `ProductionPlanner` receives units into stock by supplying a
        `qty` of at least 1, which is added to both `qty_on_hand` and
        `qty_received_total` and bumps the kit's `version`."

        Design: Corner/validations/zero_quantity_pour_and_zero_quantity_receipt_return_zero_quantity
        """
        model = X.create_pump_model(api)
        kit = X.create_repair_kit(api, model["id"])
        assert kit["status"] == "ACTIVE"

        response = api.receive_repair_kit_stock(
            kit["id"], F.kit_receipt_payload(0), planner_headers
        )
        error = validate_error(response, ApiErrorId.ZERO_QUANTITY)
        assert error["error_id"] != "ERR_INVALID_REQUEST"

        after = X.reread_repair_kit(api, kit["id"])
        assert after["qty_received_total"] == 0
        assert after["qty_on_hand"] == 0
        assert after["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Reporting a defect against the piece ledger
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingDefectRules:
    """A defect is bounded by what the lot can still call good, not by what it poured."""

    def test_defect_affecting_more_pieces_than_remain_acceptable_is_refused(
        self, api, inspector_headers
    ):
        """After one piece is scrapped the bound is 3, not the 4 poured.

        PRD 3.4: "Either a `FoundryPartner` or a `QualityInspector` may report a
        defect against a lot, supplying a `defect_code`, a `defect_type` from
        `POROSITY`, `SHRINKAGE`, `INCLUSION`, `COLD_SHUT`, `MISRUN` and
        `CORE_SHIFT`, a `severity` of `MINOR`, `MAJOR` or `CRITICAL`, and an
        `affected_qty` of at least 1 that must not exceed the lot's
        `qty_accepted` at report time, else
        `ERR_AFFECTED_QTY_EXCEEDS_LEDGER`."
        PRD 3.4: "`qty_accepted` is `qty_poured` minus `qty_scrapped` minus
        `qty_rework_pending`."

        Design: Corner/validations/defect_affecting_more_pieces_than_the_lot_holds_returns_affected_qty_exceeds_ledger
        """
        world = X.setup_master_data(api)
        lot = X.pour_casting_lot(api, world)
        scrapped_defect = X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_code="DEF-S1",
            defect_type="POROSITY",
            severity="MINOR",
            affected_qty=1,
        )
        get_success_data(
            api.disposition_casting_defect(
                scrapped_defect["id"], F.disposition_payload("SCRAP"), inspector_headers
            )
        )
        before = X.reread_casting_lot(api, lot["id"])
        assert before["qty_accepted"] == 3

        response = api.report_casting_defect(
            lot["id"],
            F.casting_defect_payload(
                defect_code="DEF-S2",
                defect_type="SHRINKAGE",
                severity="MAJOR",
                affected_qty=4,
            ),
            world["foundry_headers"],
        )
        validate_error(response, ApiErrorId.AFFECTED_QTY_EXCEEDS_LEDGER)

        _, meta = validate_paginated(
            api.list_casting_defects(inspector_headers, casting_lot_id=lot["id"])
        )
        assert meta["total_count"] == 1, "the refused report must not persist"
        unchanged = X.reread_casting_lot(api, lot["id"])
        assert unchanged["version"] == before["version"]

        accepted = validate_success(
            api.report_casting_defect(
                lot["id"],
                F.casting_defect_payload(
                    defect_code="DEF-S3",
                    defect_type="SHRINKAGE",
                    severity="MAJOR",
                    affected_qty=3,
                ),
                world["foundry_headers"],
            ),
            201,
        )
        assert accepted["status"] == "REPORTED"

        ledger = X.reread_casting_lot(api, lot["id"])
        assert ledger["qty_scrapped"] == 1
        assert ledger["qty_accepted"] == 3
        assert ledger["qty_rework_pending"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Accepting a lot
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingLotAcceptance:
    """Acceptance needs a settled defect list and at least one good casting."""

    def test_acceptance_is_blocked_until_the_reported_defect_is_dispositioned(
        self, api, inspector_headers
    ):
        """The lot stays inspected until the inspector has ruled on the defect.

        PRD 3.4: "Acceptance drives `INSPECTED → ACCEPTED` and requires two
        things: no defect on the lot may still be in `REPORTED`, else
        `ERR_OPEN_DEFECTS_PRESENT`, and `qty_accepted` must be at least 1, else
        `ERR_NO_ACCEPTABLE_CASTINGS`."
        PRD 3.4: "`USE_AS_IS` moves the defect `REPORTED →
        DISPOSITIONED_USE_AS_IS`, sets `disposition` to `USE_AS_IS`, records
        `dispositioned_by_user_id`, and leaves the lot's piece ledger entirely
        unchanged".

        Design: Corner/validations/accept_with_an_undispositioned_defect_returns_open_defects_present
        """
        world = X.setup_master_data(api)
        lot = X.setup_inspected_lot(api, world)
        defect = X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_code="DEF-O1",
            defect_type="POROSITY",
            severity="MINOR",
            affected_qty=1,
        )
        assert defect["status"] == "REPORTED"
        before = X.reread_casting_lot(api, lot["id"])

        validate_error(
            api.accept_casting_lot(lot["id"], inspector_headers),
            ApiErrorId.OPEN_DEFECTS_PRESENT,
        )
        blocked = X.reread_casting_lot(api, lot["id"])
        assert blocked["status"] == "INSPECTED"
        assert blocked["version"] == before["version"]

        dispositioned = validate_success(
            api.disposition_casting_defect(
                defect["id"], F.disposition_payload("USE_AS_IS"), inspector_headers
            ),
            200,
        )
        assert dispositioned["status"] == "DISPOSITIONED_USE_AS_IS"

        accepted = validate_success(
            api.accept_casting_lot(lot["id"], inspector_headers), 200
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["qty_accepted"] == 4

    def test_acceptance_of_a_fully_scrapped_lot_is_refused(self, api, inspector_headers):
        """A lot with nothing good left in it must never reach acceptance.

        PRD 3.4: "Acceptance drives `INSPECTED → ACCEPTED` and requires two
        things: no defect on the lot may still be in `REPORTED`, else
        `ERR_OPEN_DEFECTS_PRESENT`, and `qty_accepted` must be at least 1, else
        `ERR_NO_ACCEPTABLE_CASTINGS`."
        PRD 3.4: "`wear_index` is `pours_since_refurb` plus twice
        `defect_pours_since_refurb` — a lot that produced a critical defect
        counts three times as heavily against the tooling as a clean lot, because
        the pattern is implicated in the defect."

        All four pieces are written off while the lot is still poured, so no
        quarantine intervenes and the lot can be inspected in the normal way.

        Design: Corner/validations/accept_a_fully_scrapped_lot_returns_no_acceptable_castings
        """
        world = X.setup_master_data(api)
        lot = X.pour_casting_lot(api, world)
        defect = X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_code="DEF-T1",
            defect_type="CORE_SHIFT",
            severity="CRITICAL",
            affected_qty=4,
        )
        get_success_data(
            api.disposition_casting_defect(
                defect["id"], F.disposition_payload("SCRAP"), inspector_headers
            )
        )
        get_success_data(api.inspect_casting_lot(lot["id"], inspector_headers))
        before = X.reread_casting_lot(api, lot["id"])
        assert before["status"] == "INSPECTED"

        validate_error(
            api.accept_casting_lot(lot["id"], inspector_headers),
            ApiErrorId.NO_ACCEPTABLE_CASTINGS,
        )

        after = X.reread_casting_lot(api, lot["id"])
        assert after["status"] == "INSPECTED"
        assert after["qty_scrapped"] == 4
        assert after["qty_accepted"] == 0
        assert after["version"] == before["version"]

        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["defect_pours_since_refurb"] == 1
        assert pattern["wear_index"] == 3
