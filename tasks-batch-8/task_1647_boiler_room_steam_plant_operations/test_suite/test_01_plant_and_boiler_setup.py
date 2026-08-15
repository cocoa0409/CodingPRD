"""Plant registration, boiler registration, and boiler listing/pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_boiler,
    assert_plant,
    create_boiler_payload,
    create_plant_payload,
    create_plant,
    create_boiler,
    validate_error,
    validate_paginated,
    validate_success,
)

class TestPlantRegistration:
    def test_create_plant_with_all_required_fields_returns_201(
        self, api, plant_manager_headers
    ):
        """PRD §3.1: "A new plant starts clean: `posture` is `NORMAL`,
        `fuel_inventory_gal`, `total_fuel_received_gal`, and
        `total_fuel_consumed_gal` are all 0, `ops_run_index` is 0, and
        `lead_boiler_id` is null."

        Design: Corner/entities/create_plant_with_all_required_fields_returns_201
        """
        resp = api.create_plant(
            create_plant_payload(
                name="Corner Plant", state_code="CA", header_pressure_psi=120
            ),
            plant_manager_headers,
        )
        plant = validate_success(resp, expected_status=201)
        assert_plant(plant)
        assert plant["posture"] == "NORMAL"
        assert plant["fuel_inventory_gal"] == 0
        assert plant["total_fuel_received_gal"] == 0
        assert plant["total_fuel_consumed_gal"] == 0
        assert plant["ops_run_index"] == 0
        assert plant["lead_boiler_id"] is None

    def test_create_plant_missing_required_field_returns_400(
        self, api, plant_manager_headers
    ):
        """PRD §3.1: "Everything begins when a `PlantManager` registers the
        plant itself, supplying a display `name`, the governing `state_code` —
        one of `MA`, `NY`, `CA`, or `TX`, a choice that later selects
        calculation variants and licensing jurisdiction — and the steam
        header's operating setpoint `header_pressure_psi`."
        PRD §5: `ERR_INVALID_REQUEST` is HTTP 400.

        Design: Corner/entities/create_plant_missing_required_field_returns_400
        """
        resp = api.create_plant(
            {"name": "Bad Plant", "header_pressure_psi": 120},
            plant_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_create_plant_invalid_state_code_returns_400(
        self, api, plant_manager_headers
    ):
        """PRD §3.1: "the governing `state_code` — one of `MA`, `NY`, `CA`, or
        `TX`, a choice that later selects calculation variants and licensing
        jurisdiction". A value outside the declared set is a schema violation,
        rejected with `ERR_INVALID_REQUEST` (PRD §5: HTTP 400).

        Design: Corner/entities/plant_state_code_invalid_enum_returns_400
        """
        resp = api.create_plant(
            create_plant_payload(name="Bad State", state_code="ZZ"),
            plant_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_get_nonexistent_plant_returns_404(self, api, plant_manager_headers):
        """PRD §2.7: "Existence — every identifier in the path template
        (`plantId`, `boilerId`, `entryId`, and so on) resolves to an existing
        entity within the correct scope; otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_nonexistent_plant_returns_404
        """
        resp = api.get_plant(NON_EXISTENT_UUID, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestBoilerRegistration:
    def test_boiler_initial_state_dimensions(self, api, plant_manager_headers):
        """PRD §3.1: "A boiler is born with three independent status dimensions
        — `ops_status` beginning at `STANDBY`, `cert_status` beginning at
        `VALID`, and `water_status` beginning at `IN_SPEC` — plus
        `cycles_of_concentration` initialized to 1.0 and cumulative totals
        (`total_steam_lb`, `total_fuel_burned_gal`, `total_blowdown_gal`,
        `total_feedwater_gal`) at 0; `efficiency_pct` remains unset until the
        first efficiency calculation runs."

        Design: Corner/entities/boiler_system_fields_input_ignored
        """
        plant = create_plant(name="SysFld Plant")
        resp = api.create_boiler(
            plant["id"],
            create_boiler_payload(tag="B-SF", rated_capacity_lb_hr=30000),
            plant_manager_headers,
        )
        boiler = validate_success(resp, expected_status=201)
        assert_boiler(boiler)
        assert boiler["plant_id"] == plant["id"]
        assert boiler["ops_status"] == "STANDBY"
        assert boiler["cert_status"] == "VALID"
        assert boiler["water_status"] == "IN_SPEC"
        assert boiler["cycles_of_concentration"] == pytest.approx(1.0)
        for field in (
            "total_steam_lb",
            "total_fuel_burned_gal",
            "total_blowdown_gal",
            "total_feedwater_gal",
        ):
            assert boiler[field] == 0, f"{field} must start at 0"
        assert boiler["efficiency_pct"] is None

    def test_boiler_duplicate_tag_within_plant_returns_409(
        self, api, plant_manager_headers
    ):
        """PRD §3.1: "Each boiler carries a `tag` (a human label such as B-101,
        unique within the plant — a duplicate is refused with
        `ERR_DUPLICATE_TAG`)".

        Design: Corner/entities/boiler_duplicate_tag_within_plant_returns_409
        """
        plant = create_plant(name="Dup Plant")
        first = api.create_boiler(
            plant["id"],
            create_boiler_payload(tag="B-DUP", rated_capacity_lb_hr=30000),
            plant_manager_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_boiler(
            plant["id"],
            create_boiler_payload(tag="B-DUP", rated_capacity_lb_hr=40000),
            plant_manager_headers,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_TAG, expected_status=409)


class TestBoilerListing:
    def _plant_with_boilers(self, api, plant_manager_headers, count=3):
        plant = create_plant(name="Pag Plant")
        created = []
        for i in range(count):
            resp = api.create_boiler(
                plant["id"],
                create_boiler_payload(
                    tag=f"B-{i + 1}", rated_capacity_lb_hr=30000
                ),
                plant_manager_headers,
            )
            created.append(validate_success(resp, expected_status=201))
        return plant, created

    def test_list_boilers_pagination_defaults(self, api, plant_manager_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum accepted value of 1 and
        a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0." And "every list response carries `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/entities/list_boilers_pagination_defaults
        """
        plant, created = self._plant_with_boilers(api, plant_manager_headers)
        resp = api.list_boilers(plant["id"], plant_manager_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert {b["id"] for b in data} == {b["id"] for b in created}

    def test_pagination_limit_offset_interaction(self, api, plant_manager_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum accepted value of 1 and
        a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_interaction
        """
        plant, created = self._plant_with_boilers(api, plant_manager_headers)
        first, meta1 = validate_paginated(
            api.list_boilers(
                plant["id"], plant_manager_headers, params={"limit": 2, "offset": 0}
            )
        )
        assert len(first) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        second, meta2 = validate_paginated(
            api.list_boilers(
                plant["id"], plant_manager_headers, params={"limit": 2, "offset": 2}
            )
        )
        assert len(second) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        paged_ids = {b["id"] for b in first + second}
        assert paged_ids == {b["id"] for b in created}
