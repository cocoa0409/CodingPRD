"""Validation gates: which rule wins inside one category, how the first rungs of
the ladder order themselves, which rules are conditional on a configuration, how
one gate's outcome feeds the next, and the scope of a uniqueness key.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_certification_family,
    build_engine_platform,
    build_product_model,
    build_safety_certification,
    build_supplier,
    close_machining_run,
    close_machining_run_payload,
    complete_durability_run,
    create_component_lot_payload,
    create_durability_test_payload,
    create_product_model_payload,
    create_safety_certification_payload,
    open_machining_run,
    read_family,
    read_lot,
    read_machining_run,
    read_platform,
    receive_component_lot,
    release_product_model,
    schedule_durability_run,
    stage_engine_unit,
    submit_family,
    validate_error,
    validate_paginated,
    validate_success,
)

MACHINING_HOLD_LSL_MM = 64.98020
MACHINING_HOLD_USL_MM = 65.01980
_HOLD_MEASUREMENTS = [65.00500, 64.99500, 65.00500, 64.99500, 65.00000]


class TestSameCategoryPriorityConflict:
    """Two safety-and-compliance rules can both be violated by one certify call."""

    def test_certified_emission_over_the_limit_outranks_the_margin_floor(
        self, api, compliance_officer_headers, canonical_clock
    ):
        """PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §2.8: "**Safety and compliance**, in this order: supplier suspension (`ERR_SUPPLIER_SUSPENDED`), safety standard mismatch (`ERR_SAFETY_STANDARD_MISMATCH`), control configuration (`ERR_SAFETY_CONTROL_REQUIRED`), missing safety certification (`ERR_SAFETY_CERTIFICATION_MISSING`), expired safety certification (`ERR_SAFETY_CERTIFICATION_EXPIRED`), certified emission above the family limit (`ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT`), compliance margin too low (`ERR_COMPLIANCE_MARGIN_TOO_LOW`), insufficient capability sample (`ERR_CAPABILITY_SAMPLE_INSUFFICIENT`), machining run not closed (`ERR_MACHINING_RUN_NOT_CLOSED`), lot not releasable (`ERR_COMPONENT_LOT_NOT_RELEASABLE`), unit conformance (`ERR_UNIT_NONCONFORMING`), line down (`ERR_ASSEMBLY_LINE_DOWN`)."
        PRD §3.2: "Four conditions must hold, and they are checked in the ladder order of §2.8: the family must be in `SUBMITTED`; the certifying operator must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the family's `certified_emission_g_per_kwh` must be at most its `family_emission_limit_g_per_kwh`, else `ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT`; and the family's `compliance_margin_pct` must be at least 5.00 percent, else `ERR_COMPLIANCE_MARGIN_TOO_LOW`."
        PRD §3.2: "The three results are written to the family as `deterioration_factor`, `certified_emission_g_per_kwh` and `compliance_margin_pct`, and the family advances to `DURABILITY_COMPLETE`."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."
        PRD §2.7: "a family in `DURABILITY_TESTING`, `DURABILITY_COMPLETE`, `SUBMITTED` or `AUDIT_HOLD` projects posture `RESTRICTED`"

        Design: Corner/validations/emission_limit_outranks_compliance_margin_in_the_same_category
        """
        family = build_certification_family(family_code="2027-EPA-OVER")
        platform = build_engine_platform(family["id"], platform_code="208OVER")
        run = schedule_durability_run(family["id"], platform["id"])
        complete_durability_run(run["id"], final_emission_g_per_kwh=11.00)
        submit_family(family["id"])

        # 8.80 certified against an 8.00 limit breaks the ceiling, and the
        # resulting margin of -10.00 breaks the 5.00 floor at the same time.
        staged = read_family(family["id"])
        assert staged["deterioration_factor"] == pytest.approx(2.2000, abs=0.0001)
        assert staged["certified_emission_g_per_kwh"] == pytest.approx(8.80, abs=0.01)
        assert staged["compliance_margin_pct"] == pytest.approx(-10.00, abs=0.01)

        validate_error(
            api.certify_certification_family(family["id"], compliance_officer_headers),
            ApiErrorId.ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT,
        )

        refused = read_family(family["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused.get("certified_at") is None
        assert read_platform(platform["id"])["certification_posture"] == "RESTRICTED"


class TestLadderFirstRungs:
    """Authentication, role, request shape and existence, in that order."""

    def test_missing_headers_outrank_a_malformed_body(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role that operator is acting under."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "**Header authentication.** Both headers present and `X-User-Role` recognised, else `ERR_UNAUTHENTICATED`."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."

        Design: Corner/validations/auth_role_shape_and_existence_run_in_that_order_missing_auth
        """
        # The body is missing every required field, but shape is rung 3.
        validate_error(
            api.raw_post("/certification-families", {"model_year": 9999}, None),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

    def test_forbidden_role_outranks_a_malformed_body(
        self, api, channel_partner_headers
    ):
        """PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.8: "**Role authorization.** The acting role is permitted on this operation, else `ERR_FORBIDDEN_ROLE`."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."

        Design: Corner/validations/auth_role_shape_and_existence_run_in_that_order_missing_auth
        """
        validate_error(
            api.create_certification_family(
                {"model_year": 9999}, channel_partner_headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )

    def test_request_shape_outranks_existence_and_the_version_guard(
        self, api, certification_engineer_headers, canonical_clock
    ):
        """PRD §2.8: "**Request shape.** Required body and query fields present, types correct, enum members recognised, numbers inside their declared ranges, dates in ISO form."
        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."
        PRD §2.8: "**Existence**, in this order of entity: certification family (`ERR_CERTIFICATION_FAMILY_NOT_FOUND`), engine platform (`ERR_ENGINE_PLATFORM_NOT_FOUND`), durability test run (`ERR_DURABILITY_TEST_NOT_FOUND`), product model (`ERR_PRODUCT_MODEL_NOT_FOUND`), supplier (`ERR_SUPPLIER_NOT_FOUND`), component lot (`ERR_COMPONENT_LOT_NOT_FOUND`), machining run (`ERR_MACHINING_RUN_NOT_FOUND`), assembly line (`ERR_ASSEMBLY_LINE_NOT_FOUND`), build order (`ERR_BUILD_ORDER_NOT_FOUND`), engine unit (`ERR_ENGINE_UNIT_NOT_FOUND`), production line audit (`ERR_LINE_AUDIT_NOT_FOUND`), service part (`ERR_SERVICE_PART_NOT_FOUND`)."
        PRD §2.8: "**Record-version checks** on the two guarded writes, answering `ERR_STALE_FAMILY_VERSION` or `ERR_STALE_BUILD_ORDER_VERSION` (§2.9)."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §3.2: "A newly declared family opens in `status` `DRAFT` with `cumulative_audit_failures` at 0, and with `deterioration_factor`, `certified_emission_g_per_kwh`, `compliance_margin_pct`, `submitted_by_user_id`, `certified_by_user_id`, `certified_at` and `audit_hold_at` all empty."
        PRD §3.2: "so a platform created under a `DRAFT` family opens at `PENDING`"

        Design: Corner/validations/auth_role_shape_and_existence_run_in_that_order_missing_auth
        """
        family = build_certification_family(family_code="2027-EPA-LADR")
        platform = build_engine_platform(family["id"], platform_code="208LADR")

        # Unresolvable identifiers AND a stale version guard AND a missing
        # required field: only the shape complaint is reported.
        shapeless = create_durability_test_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, 999
        )
        shapeless.pop("target_hours")
        validate_error(
            api.create_durability_test(shapeless, certification_engineer_headers),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        # Repair only the shape: existence now decides, still ahead of the
        # version guard, and the family is named before the platform.
        well_formed = create_durability_test_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, 999
        )
        validate_error(
            api.create_durability_test(well_formed, certification_engineer_headers),
            ApiErrorId.ERR_CERTIFICATION_FAMILY_NOT_FOUND,
            expected_status=404,
        )

        # Nothing was scheduled against the real family.
        assert read_family(family["id"])["status"] == "DRAFT"
        assert read_platform(platform["id"])["certification_posture"] == "PENDING"

    def test_existence_of_the_platform_is_reported_after_the_family(
        self, api, certification_engineer_headers, canonical_clock
    ):
        """PRD §2.8: "**Existence**, in this order of entity: certification family (`ERR_CERTIFICATION_FAMILY_NOT_FOUND`), engine platform (`ERR_ENGINE_PLATFORM_NOT_FOUND`), durability test run (`ERR_DURABILITY_TEST_NOT_FOUND`), product model (`ERR_PRODUCT_MODEL_NOT_FOUND`), supplier (`ERR_SUPPLIER_NOT_FOUND`), component lot (`ERR_COMPONENT_LOT_NOT_FOUND`), machining run (`ERR_MACHINING_RUN_NOT_FOUND`), assembly line (`ERR_ASSEMBLY_LINE_NOT_FOUND`), build order (`ERR_BUILD_ORDER_NOT_FOUND`), engine unit (`ERR_ENGINE_UNIT_NOT_FOUND`), production line audit (`ERR_LINE_AUDIT_NOT_FOUND`), service part (`ERR_SERVICE_PART_NOT_FOUND`)."
        PRD §2.8: "Each covers both the path identifier and the corresponding body reference where one exists."
        PRD §2.8: "**Record-version checks** on the two guarded writes, answering `ERR_STALE_FAMILY_VERSION` or `ERR_STALE_BUILD_ORDER_VERSION` (§2.9)."
        PRD §3.2: "so a platform created under a `DRAFT` family opens at `PENDING`"

        Design: Corner/validations/auth_role_shape_and_existence_run_in_that_order_missing_auth
        """
        family = build_certification_family(family_code="2027-EPA-EXST")
        build_engine_platform(family["id"], platform_code="208EXST")

        # The family resolves, so the next unresolved entity answers — and the
        # deliberately stale version guard still does not get a turn.
        validate_error(
            api.create_durability_test(
                create_durability_test_payload(family["id"], NON_EXISTENT_UUID, 999),
                certification_engineer_headers,
            ),
            ApiErrorId.ERR_ENGINE_PLATFORM_NOT_FOUND,
            expected_status=404,
        )

        assert read_family(family["id"])["status"] == "DRAFT"


class TestConditionalSafetyAndChannelRules:
    """Each control, warranty and share rule keys off one configuration field."""

    def test_generator_rules_apply_only_to_generator_configurations(
        self, api, compliance_officer_headers, plant_admin_headers, family_with_platform
    ):
        """PRD §3.3: "Control configuration coherence is enforced at creation time and rejected with `ERR_SAFETY_CONTROL_REQUIRED`."
        PRD §3.3: "The `operator_presence_type` must be `BAIL` for a `WALK_MOWER`, `SEAT_SWITCH` for a `RIDING_MOWER`, `TWO_HAND` for a `SNOW_THROWER`, and `CO_SHUTOFF` for a `GENERATOR`."
        PRD §3.3: "The `blade_brake_type` must be `NONE` for a `GENERATOR` — a generator has no blade — and must be either `BLADE_BRAKE_CLUTCH` or `ENGINE_KILL` for every other product line."
        PRD §3.3: "The `standard_code` must match the model's product line — `ANSI_B71_1` for a `WALK_MOWER` or a `RIDING_MOWER`, `ANSI_B71_3` for a `SNOW_THROWER`, and `UL_2201` for a `GENERATOR` — and a mismatch is refused with `ERR_SAFETY_STANDARD_MISMATCH`."
        PRD §3.3: "Blade nullability is likewise dictated by the product line and enforced by the control-coherence rule: `blade_stop_time_ms` must be absent or null for a `GENERATOR` model and must be present and non-null for every other product line."
        PRD §2.8: "**Safety and compliance**, in this order: supplier suspension (`ERR_SUPPLIER_SUSPENDED`), safety standard mismatch (`ERR_SAFETY_STANDARD_MISMATCH`), control configuration (`ERR_SAFETY_CONTROL_REQUIRED`), missing safety certification (`ERR_SAFETY_CERTIFICATION_MISSING`), expired safety certification (`ERR_SAFETY_CERTIFICATION_EXPIRED`), certified emission above the family limit (`ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT`), compliance margin too low (`ERR_COMPLIANCE_MARGIN_TOO_LOW`), insufficient capability sample (`ERR_CAPABILITY_SAMPLE_INSUFFICIENT`), machining run not closed (`ERR_MACHINING_RUN_NOT_CLOSED`), lot not releasable (`ERR_COMPONENT_LOT_NOT_RELEASABLE`), unit conformance (`ERR_UNIT_NONCONFORMING`), line down (`ERR_ASSEMBLY_LINE_DOWN`)."
        PRD §3.3: "If no passing certification exists at all, the release is refused with `ERR_SAFETY_CERTIFICATION_MISSING`."
        PRD §3.3: "The `result` is `PASSED` when both checks pass and `FAILED` otherwise."
        PRD §3.3: "On success the model moves to `RELEASED` and `released_at` is stamped from the clock."

        Design: Corner/validations/safety_and_channel_rules_apply_only_to_matching_configurations
        """
        scenario = family_with_platform

        # A generator asked to carry the walk-behind mower's bail control.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="GN-BAIL",
                    product_line="GENERATOR",
                    blade_brake_type="NONE",
                    operator_presence_type="BAIL",
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SAFETY_CONTROL_REQUIRED,
        )

        # A generator asked to carry a blade brake it has no blade for.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="GN-BBC",
                    product_line="GENERATOR",
                    blade_brake_type="BLADE_BRAKE_CLUTCH",
                    operator_presence_type="CO_SHUTOFF",
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SAFETY_CONTROL_REQUIRED,
        )

        generator = build_product_model(
            scenario.platform_id,
            model_code="GN-5000",
            product_line="GENERATOR",
            blade_brake_type="NONE",
            operator_presence_type="CO_SHUTOFF",
        )

        # A mower standard on a generator, carrying a blade stop time the
        # generator may not have: the standard mismatch is reported first.
        validate_error(
            api.create_safety_certification(
                create_safety_certification_payload(
                    generator["id"],
                    standard_code="ANSI_B71_1",
                    blade_stop_time_ms=2600,
                ),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_SAFETY_STANDARD_MISMATCH,
        )

        # That certification never landed, so the release has nothing to lean on.
        validate_error(
            api.release_product_model(generator["id"], plant_admin_headers),
            ApiErrorId.ERR_SAFETY_CERTIFICATION_MISSING,
        )

        # The generator's own standard, with no blade figure at all, passes.
        generator_payload = create_safety_certification_payload(
            generator["id"], standard_code="UL_2201"
        )
        generator_payload.pop("blade_stop_time_ms")
        certification = validate_success(
            api.create_safety_certification(
                generator_payload, compliance_officer_headers
            ),
            201,
        )
        assert certification["result"] == "PASSED"

        released = release_product_model(generator["id"])
        assert released["status"] == "RELEASED"
        assert released["released_at"].startswith("2026-08-03T08:00:00")

    def test_mower_control_warranty_and_channel_share_rules(
        self, api, compliance_officer_headers, plant_admin_headers, family_with_platform
    ):
        """PRD §3.3: "The `operator_presence_type` must be `BAIL` for a `WALK_MOWER`, `SEAT_SWITCH` for a `RIDING_MOWER`, `TWO_HAND` for a `SNOW_THROWER`, and `CO_SHUTOFF` for a `GENERATOR`."
        PRD §3.3: "`warranty_months` runs between 12 and 120, but a model sold through the dealer network carries longer coverage: at least 36 months when the `channel` is `DEALER` or `DUAL`, and at least 24 months when it is `MASS_RETAIL`."
        PRD §3.3: "The warranty floors above are enforced by the same rule."
        PRD §3.3: "`dealer_share_pct` is the fraction of a build nominally destined for the dealer channel, given between 0.00 and 1.00 at 2 decimal places, and it must agree with the channel: exactly 1.00 for a `DEALER` model, exactly 0.00 for a `MASS_RETAIL` model, and strictly between 0.00 and 1.00 — neither endpoint — for a `DUAL` model."
        PRD §3.3: "A share that contradicts the channel is refused with `ERR_CHANNEL_SHARE_MISMATCH`."
        PRD §3.3: "The `standard_code` must match the model's product line — `ANSI_B71_1` for a `WALK_MOWER` or a `RIDING_MOWER`, `ANSI_B71_3` for a `SNOW_THROWER`, and `UL_2201` for a `GENERATOR` — and a mismatch is refused with `ERR_SAFETY_STANDARD_MISMATCH`."
        PRD §3.3: "Control configuration coherence is enforced at creation time and rejected with `ERR_SAFETY_CONTROL_REQUIRED`."
        PRD §2.8: "**Referential coherence**, in this order: platform posture (`ERR_FAMILY_NOT_CERTIFIED`), platform coherence (`ERR_PLATFORM_MISMATCH`), component category (`ERR_COMPONENT_CATEGORY_MISMATCH`), displacement inside the family band (`ERR_DISPLACEMENT_OUT_OF_FAMILY`), channel share coherence (`ERR_CHANNEL_SHARE_MISMATCH`), supersession chain (`ERR_SUPERSESSION_CYCLE`), line product-line support (`ERR_LINE_PRODUCT_LINE_UNSUPPORTED`)."

        Design: Corner/validations/safety_and_channel_rules_apply_only_to_matching_configurations
        """
        scenario = family_with_platform

        # The riding mower's seat switch is not the walk-behind mower's control.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="WM-SEAT",
                    operator_presence_type="SEAT_SWITCH",
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SAFETY_CONTROL_REQUIRED,
        )

        # 24 months clears the mass-retail floor but not the dual-channel one.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="WM-DUAL24",
                    channel="DUAL",
                    dealer_share_pct=0.55,
                    warranty_months=24,
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SAFETY_CONTROL_REQUIRED,
        )
        mass_retail = build_product_model(
            scenario.platform_id,
            model_code="WM-MASS24",
            channel="MASS_RETAIL",
            dealer_share_pct=0.00,
            warranty_months=24,
        )
        assert mass_retail["warranty_months"] == 24

        # A dealer model may not be split, and a dual model may not sit on an
        # endpoint — the control rules above are all satisfied here.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="WM-DLR55",
                    channel="DEALER",
                    dealer_share_pct=0.55,
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_CHANNEL_SHARE_MISMATCH,
        )
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="WM-DUAL00",
                    channel="DUAL",
                    dealer_share_pct=0.00,
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_CHANNEL_SHARE_MISMATCH,
        )

        # The snow thrower's standard is not the mower's standard.
        validate_error(
            api.create_safety_certification(
                create_safety_certification_payload(
                    mass_retail["id"], standard_code="ANSI_B71_3"
                ),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_SAFETY_STANDARD_MISMATCH,
        )
        build_safety_certification(mass_retail["id"], standard_code="ANSI_B71_1")
        assert release_product_model(mass_retail["id"])["status"] == "RELEASED"

        # The two-hand control belongs to snow equipment alone.
        validate_error(
            api.create_product_model(
                create_product_model_payload(
                    scenario.platform_id,
                    model_code="ST-BAIL",
                    product_line="SNOW_THROWER",
                    blade_brake_type="ENGINE_KILL",
                    operator_presence_type="BAIL",
                ),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SAFETY_CONTROL_REQUIRED,
        )
        snow = build_product_model(
            scenario.platform_id,
            model_code="ST-24",
            product_line="SNOW_THROWER",
            blade_brake_type="ENGINE_KILL",
            operator_presence_type="TWO_HAND",
        )
        assert snow["operator_presence_type"] == "TWO_HAND"


class TestCapabilityGateCascade:
    """The sample-size refusal and the capability hold both leave staging shut."""

    def test_capability_gate_outcome_gates_the_downstream_staging_check(
        self, api, quality_engineer_headers, released_order_plant
    ):
        """PRD §3.5: "The `component_type` is one of `CRANKSHAFT`, `CYLINDER_BORE` or `CAMSHAFT`, and it fixes the run's `criticality`, which is never supplied: a `CRANKSHAFT` or a `CYLINDER_BORE` run is `CRITICAL`, and a `CAMSHAFT` run is `MAJOR`."
        PRD §3.5: "A new run opens in `status` `OPEN` with `measurements` empty, `sample_count` 0, and `mean_mm`, `sigma_mm`, `cpk` and `closed_at` all empty."
        PRD §3.5: "The sample must contain at least 5 readings, else `ERR_CAPABILITY_SAMPLE_INSUFFICIENT`."
        PRD §3.5: "`mean_mm` is their arithmetic mean, rounded half up to 5 decimal places."
        PRD §3.5: "The run then forks on the **rounded** `cpk` against the gate its criticality demands: 1.33 for a `CRITICAL` run and 1.00 for a `MAJOR` run."
        PRD §3.5: "Missing the gate moves the run to `CAPABILITY_HOLD`; the capability figures are written either way, and `closed_at` is stamped from the clock on either outcome."
        PRD §3.5: "Staging an engine unit against a run whose status is `OPEN` or `CAPABILITY_HOLD` is refused with `ERR_MACHINING_RUN_NOT_CLOSED`."
        PRD §3.7: "The order's `staged_quantity` rises by 1, and the very first unit staged against a `RELEASED` order advances that order `RELEASED → IN_PRODUCTION`."
        PRD §3.7: "Each of the two consumed lots has 1 added to `consumed_qty` and 1 subtracted from `remaining_qty`, per §2.11 — note that the bound machining run and its casting lot are not charged in this way; only the carburetor and ignition lots are consumed piecewise."

        Design: Corner/validations/capability_gate_outcome_gates_the_downstream_staging_check
        """
        scenario = released_order_plant

        # A crankshaft run, so the criticality the server fixes is CRITICAL and
        # the gate is 1.33.
        thin_run = open_machining_run(
            scenario.platform_id,
            scenario.casting_lot_id,
            component_type="CRANKSHAFT",
            lsl_mm=MACHINING_HOLD_LSL_MM,
            usl_mm=MACHINING_HOLD_USL_MM,
        )
        assert thin_run["criticality"] == "CRITICAL"
        assert thin_run["status"] == "OPEN"
        assert thin_run["sample_count"] == 0

        validate_error(
            api.close_machining_run(
                thin_run["id"],
                close_machining_run_payload(measurements=_HOLD_MEASUREMENTS[:4]),
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_CAPABILITY_SAMPLE_INSUFFICIENT,
        )

        still_open = read_machining_run(thin_run["id"])
        assert still_open["status"] == "OPEN"
        assert still_open.get("cpk") is None

        validate_error(
            api.create_engine_unit(
                {
                    "build_order_id": scenario.build_order_id,
                    "machining_run_id": thin_run["id"],
                    "carburetor_lot_id": scenario.carburetor_lot_id,
                    "ignition_lot_id": scenario.ignition_lot_id,
                    "serial_number": "SN-9001",
                },
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_MACHINING_RUN_NOT_CLOSED,
        )

        held_run = open_machining_run(
            scenario.platform_id,
            scenario.casting_lot_id,
            component_type="CRANKSHAFT",
            lsl_mm=MACHINING_HOLD_LSL_MM,
            usl_mm=MACHINING_HOLD_USL_MM,
        )
        # Mean 65.00000 with sigma 0.005000 over the n-1 divisor puts cpk at
        # 1.3200, just under the CRITICAL gate.
        held_run = close_machining_run(held_run["id"], measurements=_HOLD_MEASUREMENTS)
        assert held_run["sample_count"] == 5
        assert held_run["mean_mm"] == pytest.approx(65.00000, abs=0.00001)
        assert held_run["sigma_mm"] == pytest.approx(0.005000, abs=0.000001)
        assert held_run["cpk"] == pytest.approx(1.3200, abs=0.0001)
        assert held_run["status"] == "CAPABILITY_HOLD"
        assert held_run["closed_at"].startswith("2026-08-03T08:00:00")

        validate_error(
            api.create_engine_unit(
                {
                    "build_order_id": scenario.build_order_id,
                    "machining_run_id": held_run["id"],
                    "carburetor_lot_id": scenario.carburetor_lot_id,
                    "ignition_lot_id": scenario.ignition_lot_id,
                    "serial_number": "SN-9002",
                },
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_MACHINING_RUN_NOT_CLOSED,
        )

        # Neither refusal advanced the order or charged a component piece.
        order = scenario.refresh_build_order()
        assert order["staged_quantity"] == 0
        assert order["status"] == "RELEASED"
        assert read_lot(scenario.carburetor_lot_id)["consumed_qty"] == 0

    def test_a_capable_run_closes_and_feeds_assembly(self, released_order_plant):
        """PRD §3.5: "Clearing the gate moves the run to `CLOSED`, and only a `CLOSED` run may supply the critical component of an engine unit."
        PRD §3.5: "`sample_count` is the number of readings."
        PRD §3.7: "The machining run must be `CLOSED`, per §3.5."
        PRD §3.7: "A successful staging creates the unit with `build_state` `STAGED` and `conformance_state` `PENDING`, `rework_count` at 0, and `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh`, `hot_test_emission_threshold` and `released_at` all empty."
        PRD §3.7: "The order's `staged_quantity` rises by 1, and the very first unit staged against a `RELEASED` order advances that order `RELEASED → IN_PRODUCTION`."

        Design: Corner/validations/capability_gate_outcome_gates_the_downstream_staging_check
        """
        scenario = released_order_plant

        capable = read_machining_run(scenario.machining_run_id)
        assert capable["status"] == "CLOSED"
        assert capable["sample_count"] == 5
        assert capable["mean_mm"] == pytest.approx(65.00000, abs=0.00001)
        assert capable["sigma_mm"] == pytest.approx(0.003162, abs=0.000001)

        unit = stage_engine_unit(scenario, "SN-0001")
        assert unit["build_state"] == "STAGED"
        assert unit["conformance_state"] == "PENDING"
        assert unit["rework_count"] == 0
        assert unit.get("hot_test_emission_threshold") is None

        order = scenario.refresh_build_order()
        assert order["staged_quantity"] == 1
        assert order["status"] == "IN_PRODUCTION"


class TestSeasonWindow:
    """The production week must sit on the side of the season it is labelled for."""

    def test_season_window_is_violated_from_both_sides(
        self, api, production_planner_headers, production_ready_plant
    ):
        """PRD §3.6: "The season declaration must agree with the calendar: a `PRE_SEASON` order requires its `production_week` to fall strictly before its product line's season start, and an `IN_SEASON` order requires its `production_week` to fall on or after that season start, with a contradiction refused as `ERR_SEASON_WINDOW_MISMATCH`."
        PRD §3.6: "The four season starts are fixed dates: walk-behind mowers open on 2027-03-01, riding mowers on 2027-03-15, snow equipment much earlier on 2026-11-02, and generators on 2027-05-03."
        PRD §2.8: "This step also catches `production_week` and `audit_week` that do not fall on a Monday, a `scheduled_end_at` that is not strictly after `scheduled_start_at`, an `expires_on` that is not strictly after `tested_on`, a `usl_mm` that is not strictly greater than `lsl_mm`, a `hot_test_max_rpm` that is not strictly greater than `hot_test_min_rpm`, a `displacement_max_cc` below `displacement_min_cc`, an `msrp_cents` below `standard_cost_cents`, a `defects_found` greater than the lot's `sample_size`, a `units_failed` greater than `units_tested`, and out-of-range pagination."
        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."
        PRD §3.6: "A successful plan opens the order in `status` `PLANNED` with `allocation_status` `UNALLOCATED`, all of `staged_quantity`, `built_quantity`, `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units` at 0, and `allocation_run_at`, `held_reason`, `status_before_hold` and `released_at` empty."
        PRD §3.6: "Build orders are readable individually and as a list, filterable by `product_model_id`, `assembly_line_id`, `status` and `season`."

        Design: Corner/validations/season_window_is_violated_from_both_sides
        """
        scenario = production_ready_plant

        def plan(season, production_week):
            return api.create_build_order(
                {
                    "product_model_id": scenario.model_id,
                    "assembly_line_id": scenario.line_id,
                    "season": season,
                    "production_week": production_week,
                    "week_span": 1,
                    "planned_quantity": 1,
                },
                production_planner_headers,
            )

        # Pre-season labelled on the walk-behind mower's opening Monday itself:
        # the boundary is strict from this side.
        validate_error(
            plan("PRE_SEASON", "2027-03-01"), ApiErrorId.ERR_SEASON_WINDOW_MISMATCH
        )
        # In-season labelled on the Monday before the opening.
        validate_error(
            plan("IN_SEASON", "2027-02-22"), ApiErrorId.ERR_SEASON_WINDOW_MISMATCH
        )
        # A Sunday is refused on the calendar axis, well above the season axis.
        validate_error(
            plan("PRE_SEASON", "2027-02-21"),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        _, meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0

        # Both sides of the same boundary are admissible when labelled the way
        # the calendar demands.
        pre_season = validate_success(plan("PRE_SEASON", "2027-02-22"), 201)
        assert pre_season["season"] == "PRE_SEASON"
        assert pre_season["status"] == "PLANNED"
        assert pre_season["allocation_status"] == "UNALLOCATED"

        in_season = validate_success(plan("IN_SEASON", "2027-03-01"), 201)
        assert in_season["season"] == "IN_SEASON"
        assert in_season["status"] == "PLANNED"

        rows, meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers,
                {"season": "PRE_SEASON", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [pre_season["id"]]


class TestCodeUniquenessScope:
    """A lot code is unique per supplier, not across the plant."""

    def test_lot_code_uniqueness_is_scoped_per_supplier(
        self, api, quality_engineer_headers, canonical_clock
    ):
        """PRD §3.4: "Receiving a lot is a `QualityEngineer` action naming the `supplier_id`, a `lot_code` of 1 to 30 characters that must be unique within that supplier (the same lot code under two different suppliers is fine), and a `lot_quantity` of pieces between 1 and 100000."
        PRD §2.8: "**Code uniqueness**, answering `ERR_DUPLICATE_CODE`."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §3.4: "On receipt the lot opens in `status` `RECEIVED` with `component_category` copied from the supplier, `accepted_qty`, `consumed_qty` and `remaining_qty` at 0, `defects_found` and `defect_ppm` empty and `deviation_flag` false."
        PRD §3.4: "A new supplier opens with `approval_status` `APPROVED`, `incoming_inspection_level` `NORMAL`, `rolling_defect_ppm` 0, `inspected_lot_count` 0 and `consecutive_accepted_lots` 0."

        Design: Corner/validations/lot_code_uniqueness_is_scoped_per_supplier
        """
        first_supplier = build_supplier(supplier_code="SUP-A", name="Alpha Components")
        second_supplier = build_supplier(supplier_code="SUP-B", name="Beta Components")

        original = receive_component_lot(
            first_supplier["id"], lot_code="LOT-777", lot_quantity=800
        )
        assert original["status"] == "RECEIVED"
        assert original["deviation_flag"] is False

        # The same code twice under one supplier collides.
        validate_error(
            api.create_component_lot(
                create_component_lot_payload(
                    first_supplier["id"], lot_code="LOT-777", lot_quantity=800
                ),
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
        )

        # The very same code under a different supplier is a different lot.
        twin = receive_component_lot(
            second_supplier["id"], lot_code="LOT-777", lot_quantity=800
        )
        assert twin["id"] != original["id"]
        assert twin["lot_code"] == original["lot_code"] == "LOT-777"
        assert twin["status"] == "RECEIVED"

        # Each lot keeps its own frozen plan and its own piece counters.
        for lot_id in (original["id"], twin["id"]):
            lot = read_lot(lot_id)
            assert lot["inspection_level_at_receipt"] == "NORMAL"
            assert lot["consumed_qty"] == 0
            assert lot["remaining_qty"] == 0
