"""Formulation master data: creation, retrieval, listing, validation, and the
withdraw in-flight guard."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_formulation,
    create_batch,
    create_formulation,
    create_formulation_payload,
    create_vessel,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM_CODE = "EPX-CR"


class TestFormulationCreation:
    def test_formulation_created_with_initial_state_and_system_fields(self, api, plant_manager_headers):
        """PRD §3.1: "A new formulation begins life in `DRAFT` status."
        PRD §2.4: "**`version`** (integer): a system-managed integer that starts at 1 and increments by exactly 1 on every mutation, including state transitions and any cascade-driven update to a derived counter."

        Design: Corner/entities/formulation_created_with_initial_state_and_system_fields
        """
        set_clock()
        resp = api.create_formulation(create_formulation_payload(code="EPX-CR-1"), plant_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_formulation(data)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["created_at"] and data["updated_at"]

    def test_formulation_retrieval_by_id(self, api, plant_manager_headers):
        """PRD §3.1: "A `PlantManager` creates a formulation by supplying a unique `code` (unique across all formulations), a display `name`, and the chemistry profile: `chemistry_family` (one of `EPOXY`, `POLYURETHANE`, `SILICONE`, or `ACRYLIC`), a `moisture_sensitive` boolean that will later force dry-room packaging, `solvent_content_pct` between 0 and 100, the `flash_point_c` in Celsius, the working window `pot_life_minutes` (how long after mix completion the batch remains usable before it gels), the `shelf_life_months` used for expiry dating, the release specification `spec_min_bond_strength_mpa`, and the default `min_remaining_shelf_life_days` that shipments must respect at ship date."

        Design: Corner/entities/formulation_retrieval_by_id
        """
        set_clock()
        created = create_formulation(
            "EPX-CR-2", activate=False, chemistry_family="ACRYLIC", moisture_sensitive=True,
            solvent_content_pct=12.5, flash_point_c=45.0, pot_life_minutes=90,
            shelf_life_months=12, spec_min_bond_strength_mpa=10.0,
            min_remaining_shelf_life_days=60,
        )
        resp = api.get_formulation(created["id"], plant_manager_headers)
        data = validate_success(resp)
        assert data["code"] == "EPX-CR-2"
        assert data["chemistry_family"] == "ACRYLIC"
        assert data["moisture_sensitive"] is True
        assert data["solvent_content_pct"] == pytest.approx(12.5)
        assert data["pot_life_minutes"] == 90


class TestFormulationListing:
    def test_formulation_list_pagination_envelope(self, api, plant_manager_headers):
        """PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/formulation_list_pagination_envelope
        """
        set_clock()
        create_formulation("PG-1", activate=False, name="Pg One")
        create_formulation("PG-2", activate=False, name="Pg Two", chemistry_family="SILICONE")

        data1, meta1 = validate_paginated(api.list_formulations(plant_manager_headers, params={"limit": 1, "offset": 0}))
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(api.list_formulations(plant_manager_headers, params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False


class TestFormulationErrors:
    def test_get_formulation_returns_404(self, api, plant_manager_headers):
        """PRD §2.5: "Path identifiers are validated left to right, then foreign-key identifiers in the request body; any miss returns `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_formulation_returns_404
        """
        set_clock()
        resp = api.get_formulation(NON_EXISTENT_UUID, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_formulation_missing_required_code_returns_400(self, api, plant_manager_headers):
        """PRD §2.5: "Required fields must be present, types and enum members must be valid, `mix_end_at` must be strictly after `mix_start_at`, `planned_end_at` must be at or after `planned_start_at`, integers flagged as positive must be positive, a `QUICK` cure test must carry exactly 1 specimen and a `FULL` cure test exactly 5, and `agreement_id` must be present on a shipment exactly when `shipment_kind` is `CONSIGNMENT` or `CONSIGNMENT_REPLENISHMENT` and must be absent for `SALE`. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/formulation_missing_required_code_returns_400
        """
        set_clock()
        payload = create_formulation_payload(code="X")
        del payload["code"]
        payload["name"] = "No Code"
        resp = api.create_formulation(payload, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_formulation_invalid_enum_returns_400(self, api, plant_manager_headers):
        """PRD §2.5: "Required fields must be present, types and enum members must be valid, `mix_end_at` must be strictly after `mix_start_at`, `planned_end_at` must be at or after `planned_start_at`, integers flagged as positive must be positive, a `QUICK` cure test must carry exactly 1 specimen and a `FULL` cure test exactly 5, and `agreement_id` must be present on a shipment exactly when `shipment_kind` is `CONSIGNMENT` or `CONSIGNMENT_REPLENISHMENT` and must be absent for `SALE`. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/formulation_invalid_enum_returns_400
        """
        set_clock()
        payload = create_formulation_payload(code="BAD-ENUM", name="Bad Enum", chemistry_family="GLUE")
        resp = api.create_formulation(payload, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_activate_twice_returns_409(self, api, plant_manager_headers):
        """PRD §3.1: "While in `DRAFT`, a formulation can be advanced to `EFFECTIVE` by a `PlantManager` calling activation; if the formulation is not in `DRAFT` the call fails with `ERR_FORMULATION_INVALID_STATE`."

        Design: Corner/errors/activate_twice_returns_409
        """
        formulation = create_formulation("EPX-2ACT", activate=True)
        resp = api.activate_formulation(formulation["id"], plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORMULATION_INVALID_STATE)

    def test_withdraw_blocked_by_inflight_batch(self, api, plant_manager_headers):
        """PRD §3.1: "Withdrawal is refused with `ERR_FORMULATION_INVALID_STATE` when the formulation is not currently `EFFECTIVE`, and refused with `ERR_FORMULATION_HAS_INFLIGHT_BATCHES` when any batch referencing it is still in `MIXING`, `MIXED`, or `PACKING`."

        Design: Corner/state_machines/withdraw_blocked_by_inflight_batch
        """
        set_clock()
        formulation = create_formulation("EPX-WD", activate=True, pot_life_minutes=120)
        vessel = create_vessel("V-WD", capacity_liters=100)
        create_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)

        resp = api.withdraw_formulation(formulation["id"], plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORMULATION_HAS_INFLIGHT_BATCHES)

        after = validate_success(api.get_formulation(formulation["id"], plant_manager_headers))
        assert after["status"] == "EFFECTIVE"
