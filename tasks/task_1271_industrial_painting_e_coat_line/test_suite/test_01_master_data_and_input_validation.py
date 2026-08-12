"""Master data creation, common system fields, and request-validation rules."""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_customer, assert_coating_spec,
    create_customer_payload, create_coating_spec_payload, create_paint_line_payload,
    create_pretreatment_stage_payload, create_titration_reading_payload,
    create_lot_payload,
    create_customer, create_spec, create_paint_line, create_stage,
    setup_line_with_stage, get_lot,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CHEM = TEST_USERS["chemist_headers"]


class TestCustomerCreation:
    def test_customer_create_mints_system_fields(self, api):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a
        UUID, with no type prefix" and "`version` (integer): a system-managed integer
        beginning at 1 on creation and incrementing by one on every mutation, including
        mutations applied by automatic cascades."

        Design: Corner/entities/customer_create_returns_system_fields
        """
        res = api.create_customer(create_customer_payload(name="Acme Housings"), ADMIN)
        data = validate_success(res, 201)
        assert_customer(data)
        assert data["version"] == 1
        assert data["created_at"]

    def test_customer_create_response_carries_name_and_is_retrievable(self, api):
        """PRD §3.1: "A **Customer** — an OEM jobber sending parts for coating — is
        created with nothing more than a `name`."

        Design: Corner/entities/customer_create_returns_system_fields
        """
        res = api.create_customer(create_customer_payload(name="Acme Housings"), ADMIN)
        data = validate_success(res, 201)
        assert data["name"] == "Acme Housings"
        fetched = validate_success(api.get_customer(data["id"], ADMIN), 200)
        assert fetched["id"] == data["id"]
        assert fetched["name"] == "Acme Housings"


class TestCoatingSpecSupersession:
    def test_new_spec_supersedes_prior_active_spec(self, api):
        """PRD §3.1: "At most one spec per (`customer_id`, `color_code`) pair may be
        `ACTIVE`: creating a new spec for a pair that already has an active one
        automatically moves the prior spec to `SUPERSEDED` and increments its `version`."

        Design: Corner/entities/coating_spec_create_supersedes_prior_active
        """
        customer = create_customer()
        spec_a = create_spec(customer["id"], color_code="RAL9005")
        spec_b = create_spec(
            customer["id"], color_code="RAL9005",
            film_build_min_um=20.0, film_build_max_um=26.0,
            cure_metal_temp_c=185.0, cure_minutes_at_temp=22,
            adhesion_class_min=3, impact_joules_min=45.0, voc_g_per_l=300.0,
        )
        assert spec_b["status"] == "ACTIVE"
        assert spec_b["version"] == 1
        spec_a_after = validate_success(api.get_coating_spec(spec_a["id"], ADMIN), 200)
        assert spec_a_after["status"] == "SUPERSEDED"
        assert spec_a_after["version"] == spec_a["version"] + 1

    def test_new_spec_for_different_color_does_not_supersede(self, api):
        """PRD §3.1: "At most one spec per (`customer_id`, `color_code`) pair may be
        `ACTIVE`: creating a new spec for a pair that already has an active one
        automatically moves the prior spec to `SUPERSEDED` and increments its `version`."

        Design: Corner/entities/coating_spec_create_supersedes_prior_active
        """
        customer = create_customer()
        spec_a = create_spec(customer["id"], color_code="RAL9005")
        spec_b = create_spec(customer["id"], color_code="RAL1018")
        assert spec_b["status"] == "ACTIVE"
        spec_a_after = validate_success(api.get_coating_spec(spec_a["id"], ADMIN), 200)
        assert spec_a_after["status"] == "ACTIVE"
        assert spec_a_after["version"] == spec_a["version"]


class TestLotCreationValidation:
    def test_lot_create_missing_part_quantity_rejected(self, api):
        """PRD §2.6: "required fields are present, enum values are valid, and numbers
        lie in their physical domain: `part_quantity` greater than zero, `end_utc` after
        `start_utc`, a window end after its start, `exited_at` after `entered_at`,
        `period_end` after `period_start`, positive `purge_solvent_liters`
        (`ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/lot_create_missing_required_field_returns_400
        """
        customer = create_customer()
        spec = create_spec(customer["id"])
        payload = {"customer_id": customer["id"], "spec_id": spec["id"]}
        res = api.create_lot(payload, SCHED)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_lot_create_zero_part_quantity_rejected(self, api):
        """PRD §3.3: "A `LineScheduler` books a **Lot** by naming the `customer_id`,
        the `spec_id` of the coating standard the parts must meet, and the
        `part_quantity` received, which must be greater than zero."

        Design: Corner/entities/lot_create_missing_required_field_returns_400
        """
        customer = create_customer()
        spec = create_spec(customer["id"])
        payload = create_lot_payload(customer["id"], spec["id"], part_quantity=0)
        res = api.create_lot(payload, SCHED)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestNotFoundAndEnumValidation:
    def test_lot_get_unknown_id_returns_404(self, api):
        """PRD §2.5: "Path identifiers are validated in strict left-to-right order, and
        the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not correspond to an existing resource, before any later
        identifier or any business rule is examined."

        Design: Corner/entities/lot_get_not_found_returns_404
        """
        res = api.get_lot(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_paint_line_invalid_allocation_policy_rejected(self, api):
        """PRD §3.1: "A **PaintLine** is created with a `name`, the `current_color_code`
        loaded in its e-coat tank, the conveyor `line_speed_fpm` in feet per minute, the
        physical rack capacity `hanger_capacity_parts`, and an `allocation_policy` of
        either `FULL_TO_NEXT_LOT` or `PRO_RATA_BY_PARTS` — the purge-cost policy, which
        is immutable once the line exists."
        PRD §2.6: "required fields are present, enum values are valid, and numbers lie
        in their physical domain: `part_quantity` greater than zero, `end_utc` after
        `start_utc`, a window end after its start, `exited_at` after `entered_at`,
        `period_end` after `period_start`, positive `purge_solvent_liters`
        (`ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/paint_line_invalid_enum_rejected
        """
        payload = create_paint_line_payload(allocation_policy="SPLIT_EVENLY")
        res = api.create_paint_line(payload, ADMIN)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestTitrationInputValidation:
    def test_titration_reading_negative_concentration_rejected(self, api):
        """PRD §3.2: "A negative concentration is physically meaningless and is
        rejected with `ERR_MEASUREMENT_INVALID`."
        PRD §2.6: "A measured value outside its physical domain — for example a negative
        titration concentration — is rejected with `ERR_MEASUREMENT_INVALID` (HTTP 422)."

        Design: Corner/entities/negative_concentration_returns_measurement_invalid
        """
        line, stage = setup_line_with_stage()
        payload = create_titration_reading_payload(stage["id"], measured_conc_gpl=-1.0)
        res = api.record_titration_reading(payload, CHEM)
        validate_error(res, "ERR_MEASUREMENT_INVALID", expected_status=422)

    def test_titration_reading_boundary_values_inclusive(self, api):
        """PRD §3.2: "computes `in_range` as true exactly when the measured
        concentration lies at or between `conc_min_gpl` and `conc_max_gpl` — both bounds
        inclusive — and never updates the row thereafter."

        Design: Corner/calculations/titration_boundary_inclusive_bounds
        """
        line, stage = setup_line_with_stage()  # 20.0 - 30.0 g/L band
        rd_min = validate_success(
            api.record_titration_reading(
                create_titration_reading_payload(stage["id"], measured_conc_gpl=20.0), CHEM
            ), 201
        )
        rd_max = validate_success(
            api.record_titration_reading(
                create_titration_reading_payload(stage["id"], measured_conc_gpl=30.0), CHEM
            ), 201
        )
        rd_low = validate_success(
            api.record_titration_reading(
                create_titration_reading_payload(stage["id"], measured_conc_gpl=19.9), CHEM
            ), 201
        )
        assert rd_min["in_range"] is True
        assert rd_max["in_range"] is True
        assert rd_low["in_range"] is False
        stage_after = validate_success(api.get_pretreatment_stage(stage["id"], CHEM), 200)
        assert stage_after["status"] == "OUT_OF_RANGE"
