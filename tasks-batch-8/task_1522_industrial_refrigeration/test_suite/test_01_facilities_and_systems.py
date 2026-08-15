"""Facility master data, refrigeration systems, and the head-pressure calculator."""
import pytest

from test_helpers import (
    ADMIN,
    MLEAD,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_facility,
    create_equipment_payload,
    create_facility,
    create_facility_payload,
    create_system,
    get_facility,
    post_charge_adjustment,
    setup_facility_system_operator,
    setup_facility_with_operator,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFacilityMasterData:

    def test_facility_created_with_defaults(self):
        """PRD section 3.1: "A new facility begins clean: `total_charge_lbs` at
        0.0, `charge_posture` at `BELOW_THRESHOLD`, `psm_program_status` at
        `NOT_REQUIRED`, `compliance_posture` at `COMPLIANT`, `posture_score` at
        0, and all three posture counts at zero."
        PRD section 3.1: "A `FacilityAdmin` onboards a plant by creating a
        **Facility** with a `name` and, optionally, a `threshold_lbs` — the PSM
        threshold quantity in pounds, defaulting to 10000.0 when omitted."

        Design: Corner/entities/facility_created_with_defaults
        """
        created = validate_success(
            api_client.create_facility(create_facility_payload(name="ColdCo Plant"),
                                       ADMIN),
            expected_status=201,
        )
        facility = validate_success(api_client.get_facility(created["id"], ADMIN),
                                    expected_status=200)
        assert_facility(facility)
        assert facility["threshold_lbs"] == pytest.approx(10000.0, abs=0.01)
        assert facility["total_charge_lbs"] == pytest.approx(0.0, abs=0.001)
        assert facility["charge_posture"] == "BELOW_THRESHOLD"
        assert facility["psm_program_status"] == "NOT_REQUIRED"
        assert facility["compliance_posture"] == "COMPLIANT"
        assert facility["posture_score"] == 0
        assert facility["overdue_inspection_count"] == 0
        assert facility["open_incident_count"] == 0
        assert facility["expired_training_count"] == 0
        assert isinstance(facility["version"], int) and facility["version"] >= 1

    def test_facility_missing_name_rejected(self):
        """PRD section 2.9: "Requests that are structurally malformed — a missing
        required field, an unknown field, an invalid enum member, or an
        out-of-range scalar such as a `safety_score` outside 0 to 100 — are
        rejected with `ERR_VALIDATION` (400) as the payload is parsed."

        Design: Corner/entities/facility_missing_name_rejected
        """
        resp = api_client.create_facility({"threshold_lbs": 5000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_get_nonexistent_facility_not_found(self):
        """PRD section 2.9: "Existence third: the path identifier — paths in
        this API carry at most one — and every resource referenced in the body
        resolve to real records (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/get_nonexistent_facility_not_found
        """
        resp = api_client.get_facility(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestSystemListing:

    def test_system_list_pagination_envelope(self):
        """PRD section 2.3: "The `limit` parameter caps how many items a page
        carries; when omitted it defaults to 10, and it is bounded below by 1
        and above by 100. The `offset` parameter states how many items to skip
        and defaults to 0. Every list is returned sorted by `created_at` in
        ascending order. The `meta` envelope of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/system_list_pagination_envelope
        """
        facility = create_facility(name="ColdCo Plant")
        for i in range(1, 12):
            create_system(facility["id"], name=f"S{i:02d}", design_charge_lbs=100)

        resp1 = api_client.list_refrigeration_systems(
            ADMIN, params={"facility_id": facility["id"]})
        data1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(data1) == 10, f"default page must carry 10 rows, got {len(data1)}"
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True

        resp2 = api_client.list_refrigeration_systems(
            ADMIN, params={"facility_id": facility["id"], "offset": 10})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1, f"offset 10 must return the 11th row, got {len(data2)}"
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False


class TestEquipmentValidation:

    def test_equipment_invalid_enum_rejected(self):
        """PRD section 3.3: equipment carries "an `equipment_type` of `VESSEL`,
        `COMPRESSOR`, `PIPING_CIRCUIT`, or `PRV`".
        PRD section 2.9: "Requests that are structurally malformed — a missing
        required field, an unknown field, an invalid enum member, or an
        out-of-range scalar such as a `safety_score` outside 0 to 100 — are
        rejected with `ERR_VALIDATION` (400) as the payload is parsed."

        Design: Corner/entities/equipment_invalid_enum_rejected
        """
        facility = create_facility(name="ColdCo Plant")
        system = create_system(facility["id"], name="ER1", design_charge_lbs=3000)
        resp = api_client.create_equipment(
            create_equipment_payload(system["id"], tag_number="B-901",
                                     equipment_type="BOILER"),
            MLEAD,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestSystemDecommission:

    def test_system_decommission_with_charge_rejected(self):
        """PRD section 3.1: "Decommissioning carries a precondition: the net
        book charge attributed to the system, meaning the signed sum of its
        ledger lines' `rounded_lbs`, must equal exactly zero, failing which the
        request is rejected with `ERR_SYSTEM_NOT_EMPTY` (409)."

        Design: Corner/state_machines/system_decommission_with_charge_rejected
        """
        facility, employee, op_headers = setup_facility_with_operator()
        system = create_system(facility["id"], name="ER1", design_charge_lbs=3000)
        post_charge_adjustment(facility["id"], "ADD", 100.0, "charge ER1",
                               op_headers, system_id=system["id"])
        out = validate_success(
            api_client.set_system_status(system["id"],
                                         {"to_status": "OUT_OF_SERVICE"}, ADMIN),
            expected_status=200,
        )
        assert out["status"] == "OUT_OF_SERVICE"

        resp = api_client.set_system_status(system["id"],
                                            {"to_status": "DECOMMISSIONED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_EMPTY, expected_status=409)
        after = get_facility(facility["id"])  # facility read still valid
        assert after["total_charge_lbs"] == pytest.approx(100.0, abs=0.01)
        system_after = validate_success(
            api_client.get_refrigeration_system(system["id"], ADMIN),
            expected_status=200)
        assert system_after["status"] == "OUT_OF_SERVICE"


class TestHeadPressureTarget:

    def _system(self, float_head_enabled=True):
        facility, system, employee, op_headers = setup_facility_system_operator(
            condenser_approach_f=15.0, min_head_psig=150.0, max_head_psig=185.0,
            float_head_enabled=float_head_enabled)
        return system, op_headers

    def test_head_pressure_load_band_at_eighty_percent(self):
        """PRD section 3.4: "The computation first derates the approach
        temperature for high condenser load: the effective approach is the
        system's `condenser_approach_f` plus 5.0 degrees when the load is at
        least 90 percent, plus 2.5 degrees when the load is at least 75 percent
        but below 90, and unchanged below 75."
        PRD section 3.4: "The raw saturation pressure is then read from the
        ammonia saturation table — 50 degrees Fahrenheit maps to 74.5 psig, 60
        to 92.9, 70 to 114.1, 80 to 138.8, 90 to 166.4, and 100 to 196.6 —
        interpolating linearly between the bracketing table points and rounding
        the interpolated result once, to one tenth of a psig, half up."

        Design: Difficulty/combinatorial_formula/floating_head_pressure_load_band_clamp
        """
        system, op_headers = self._system()
        resp = api_client.head_pressure_target(
            system["id"], {"wet_bulb_f": 70.0, "condenser_load_pct": 80},
            op_headers)
        data = validate_success(resp, expected_status=200)
        # approach 15.0 + 2.5 = 17.5; condensing temp 70 + 17.5 = 87.5F;
        # interp(80:138.8, 90:166.4) = 138.8 + 0.75*27.6 = 159.5
        assert data["effective_approach_f"] == pytest.approx(17.5, abs=0.01)
        assert data["condensing_temp_f"] == pytest.approx(87.5, abs=0.01)
        assert data["raw_psig"] == pytest.approx(159.5, abs=0.01)
        assert data["target_psig"] == pytest.approx(159.5, abs=0.01)
        assert data["variant"] == "floating"

    def test_head_pressure_load_band_below_seventy_five(self):
        """PRD section 3.4: "The computation first derates the approach
        temperature for high condenser load: the effective approach is the
        system's `condenser_approach_f` plus 5.0 degrees when the load is at
        least 90 percent, plus 2.5 degrees when the load is at least 75 percent
        but below 90, and unchanged below 75."
        PRD section 3.4: "When floating is enabled, the target clamps the raw
        pressure into the safe band — the greater of the raw pressure and
        `min_head_psig`, then the lesser of that result and `max_head_psig` —
        and the `variant` reads `floating`."

        Design: Difficulty/combinatorial_formula/floating_head_pressure_load_band_clamp
        """
        system, op_headers = self._system()
        resp = api_client.head_pressure_target(
            system["id"], {"wet_bulb_f": 70.0, "condenser_load_pct": 50},
            op_headers)
        data = validate_success(resp, expected_status=200)
        # load 50 < 75: approach unchanged 15.0; condensing temp 85.0F;
        # interp = 138.8 + 0.5*27.6 = 152.6; inside [150.0, 185.0] clamp.
        assert data["effective_approach_f"] == pytest.approx(15.0, abs=0.01)
        assert data["condensing_temp_f"] == pytest.approx(85.0, abs=0.01)
        assert data["raw_psig"] == pytest.approx(152.6, abs=0.01)
        assert data["target_psig"] == pytest.approx(152.6, abs=0.01)
        assert data["variant"] == "floating"

    def test_head_pressure_min_clamp_applied(self):
        """PRD section 3.4: "When floating is enabled, the target clamps the
        raw pressure into the safe band — the greater of the raw pressure and
        `min_head_psig`, then the lesser of that result and `max_head_psig` —
        and the `variant` reads `floating`."

        Design: Corner/calculations/head_pressure_min_clamp_applied
        """
        system, op_headers = self._system()
        resp = api_client.head_pressure_target(
            system["id"], {"wet_bulb_f": 40.0, "condenser_load_pct": 10},
            op_headers)
        data = validate_success(resp, expected_status=200)
        # condensing temp 40 + 15 = 55F -> interp(50:74.5, 60:92.9)
        # = 74.5 + 0.5*18.4 = 83.7; clamp: max(83.7, 150.0) then min(..., 185.0)
        assert data["raw_psig"] == pytest.approx(83.7, abs=0.01)
        assert data["target_psig"] == pytest.approx(150.0, abs=0.01)
        assert data["variant"] == "floating"

    def test_head_pressure_fixed_design_variant_when_float_disabled(self):
        """PRD section 3.4: "When `float_head_enabled` is false, the
        calculation short-circuits: the target is always the system's
        `max_head_psig` regardless of weather or load, and the response's
        `variant` reads `fixed_design`."

        Design: Corner/calculations/head_pressure_fixed_design_variant_when_float_disabled
        """
        system, op_headers = self._system(float_head_enabled=False)
        resp = api_client.head_pressure_target(
            system["id"], {"wet_bulb_f": 70.0, "condenser_load_pct": 80},
            op_headers)
        data = validate_success(resp, expected_status=200)
        # floating math would give 159.5, but the fixed_design variant pins max
        assert data["target_psig"] == pytest.approx(185.0, abs=0.01)
        assert data["variant"] == "fixed_design"


class TestAuthentication:

    def test_missing_role_header_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or carrying a
        role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
        (401)."

        Design: Corner/rbac/missing_role_header_unauthenticated
        """
        headers = {"X-User-ID": "test-user-1", "Content-Type": "application/json"}
        resp = api_client.create_facility({"name": "No Auth Plant"}, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
