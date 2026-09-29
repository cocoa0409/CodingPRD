"""Read and write shapes of the catalogue, the build order and the station log.

Covers what a machine-model registration returns and seeds, what a model read
echoes, how the model collection filters and paginates, what an incomplete build
order is answered with, and how a station operation's billable labour and
occupation window are derived.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import PRODUCT_ENGINEER, CHANNEL_MANAGER, PLANT_MANAGER, make_technician_headers


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so one instant compares equal to itself."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestMachineModelCreationShape:
    def test_01_registration_seeds_every_derived_counter(self, api):
        """A freshly registered machine model comes back with its lifecycle, yield and rebate fields at their opening values.

        PRD: "Its production counters — `accepted_unit_count`, `scrapped_unit_count` and `quality_hold_unit_count` — all begin at 0, its `first_pass_yield_pct` begins at `0.00`, and its rebate snapshot begins empty, with `rebate_program_codes` an empty array and `rebate_amount_cents` at 0."
        Design: Corner/entities/machine_model_creation_returns_declared_field_set
        """
        payload = f.machine_model_payload(
            model_code="OPL-60-A",
            product_line="ON_PREMISES",
            capacity_rating_lb=60,
            rated_water_gal_per_cwt=1.10,
            rated_kwh_per_cwt=0.42,
            drum_alloy_grade="AISI_304",
            payment_module_options=[],
            list_price_cents=1250000,
            max_rework_cycles=2,
            min_first_pass_yield_pct=80.00,
        )
        data = validate_success(api.create_machine_model(payload, PRODUCT_ENGINEER), 201)

        a.assert_common_fields(data)
        assert data["accepted_unit_count"] == 0
        assert data["scrapped_unit_count"] == 0
        assert data["quality_hold_unit_count"] == 0
        a.assert_pct(data["first_pass_yield_pct"], 0.00)
        assert data["rebate_program_codes"] == []
        a.assert_cents(data["rebate_amount_cents"], 0)
        assert data["certification_state"] == "DRAFT"
        assert data["suspended_reason"] == "NONE"
        assert data["version"] == 1


class TestMachineModelRetrievalShape:
    def test_01_read_echoes_the_nameplate_and_leaves_version_alone(self, api):
        """Reading one vended model returns the catalogue code, payment hardware and book price as registered, with the record still at its first version.

        PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."
        Design: Corner/entities/machine_model_retrieval_returns_stored_row
        """
        model = fx.make_vended_model(api)

        data = validate_success(api.get_machine_model(model["id"], CHANNEL_MANAGER), 200)

        assert data["id"] == model["id"]
        assert data["model_code"] == "VND-40-C"
        assert data["payment_module_options"] == ["COIN", "CARD", "MOBILE"]
        a.assert_cents(data["list_price_cents"], 780000)
        assert data["version"] == 1


class TestMachineModelListing:
    def test_01_product_line_filter_narrows_the_catalogue(self, api):
        """Narrowing the catalogue to on-premises machines returns only those two models and counts only those two.

        PRD: "The catalogue may be browsed newest-first and narrowed by the `product_line` and `certification_state` filters."
        Design: Corner/entities/machine_model_listing_paginates_and_filters
        """
        fx.make_model(api, model_code="OPL-60-A")
        fx.make_model(
            api,
            model_code="OPL-80-A",
            capacity_rating_lb=80,
            rated_water_gal_per_cwt=1.15,
            rated_kwh_per_cwt=0.44,
            list_price_cents=1450000,
        )
        fx.make_vended_model(api, payment_module_options=["COIN"])

        rows, meta = validate_paginated(
            api.list_machine_models(PRODUCT_ENGINEER, product_line="ON_PREMISES")
        )

        assert meta["total_count"] == 2
        assert len(rows) == 2
        a.assert_values_in_order(rows, "product_line", ["ON_PREMISES", "ON_PREMISES"])
        assert sorted(row["model_code"] for row in rows) == ["OPL-60-A", "OPL-80-A"]
        assert meta["has_more"] is False

    def test_02_truncated_page_reports_the_filtered_total(self, api):
        """A one-row page over the two on-premises models still reports two matching rows and flags that more remain.

        PRD: "`total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."
        Design: Corner/entities/machine_model_listing_paginates_and_filters
        """
        fx.make_model(api, model_code="OPL-60-A")
        fx.make_model(
            api,
            model_code="OPL-80-A",
            capacity_rating_lb=80,
            rated_water_gal_per_cwt=1.15,
            rated_kwh_per_cwt=0.44,
            list_price_cents=1450000,
        )
        fx.make_vended_model(api, payment_module_options=["COIN"])

        rows, meta = validate_paginated(
            api.list_machine_models(
                PRODUCT_ENGINEER, product_line="ON_PREMISES", limit=1, offset=0
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert rows[0]["product_line"] == "ON_PREMISES"


class TestMachineModelNotFound:
    def test_01_unknown_model_id_is_a_not_found(self, api):
        """Reading a machine model that was never registered is refused as an unknown model rather than answered with an empty row.

        PRD: "A machine-model identifier in the path resolves to a stored model — otherwise `ERR_MODEL_NOT_FOUND`, HTTP 404."
        Design: Corner/entities/machine_model_get_with_unknown_id_not_found
        """
        validate_error(
            api.get_machine_model(NON_EXISTENT_UUID, PRODUCT_ENGINEER),
            E.ERR_MODEL_NOT_FOUND,
            404,
        )


class TestBuildOrderRequiredFields:
    def test_01_build_order_without_a_serial_number_is_rejected(self, api):
        """Opening a serialized unit without its serial number is refused and no unit is written for the model.

        PRD: "The request body parses, every required input field is present, every enum-typed value is a declared member of its enumeration, every integer sits inside its declared range, and every decimal carries no more than its declared scale."
        Design: Corner/entities/build_order_create_missing_serial_number_rejected
        """
        model = fx.make_model(api, model_code="OPL-60-A")
        payload = f.build_order_payload(
            model["id"],
            planned_start_at="2026-08-01T07:00:00Z",
        )
        del payload["serial_number"]

        validate_error(
            api.create_build_order(payload, PLANT_MANAGER), E.ERR_INVALID_REQUEST, 400
        )

        rows, meta = validate_paginated(
            api.list_build_orders(PLANT_MANAGER, model_id=model["id"])
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestMachineModelDefaults:
    def test_01_omitted_quality_governors_take_their_declared_defaults(self, api):
        """A tunnel model registered without either quality governor tolerates two rework rounds and expects a four-in-five first-pass record.

        PRD: "A model registered without either field therefore tolerates two rework rounds per unit and expects four finished units in five to clear inspection on the first attempt."
        Design: Corner/entities/machine_model_defaults_applied_when_optionals_omitted
        """
        payload = f.tunnel_model_payload(
            model_code="TUN-300-I",
            capacity_rating_lb=300,
            rated_water_gal_per_cwt=0.85,
            rated_kwh_per_cwt=0.55,
            list_price_cents=9800000,
        )

        data = validate_success(api.create_machine_model(payload, PRODUCT_ENGINEER), 201)

        assert data["max_rework_cycles"] == 2
        a.assert_pct(data["min_first_pass_yield_pct"], 80.00)
        assert data["certification_state"] == "DRAFT"


class TestStationLogLabourDerivation:
    def test_01_partial_minute_is_truncated_and_the_buffer_extends_occupation(
        self, api, floor_environment
    ):
        """A drum operation of forty-five and a half minutes bills forty-five whole minutes while the cell stays occupied through its changeover.

        PRD: "And `labor_minutes` is the elapsed time from `started_at` to `completed_at` expressed in whole minutes with any partial minute truncated downward — the changeover buffer is **not** billable labour and never appears in `labor_minutes`."
        Design: Corner/entities/station_log_labor_minutes_floors_partial_minute
        """
        env = floor_environment
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, build["id"])
        payload = f.station_log_payload(
            env["stations"]["drum"]["id"],
            "DRUM_FAB",
            "2026-08-01T08:00:00Z",
            "2026-08-01T08:45:30Z",
            "PASS",
        )

        log = validate_success(
            api.create_station_log(
                build["id"],
                payload,
                make_technician_headers(env["technician"]["id"]),
            ),
            201,
        )

        assert log["labor_minutes"] == 45
        assert _instant(log["occupation_from"]) == _instant("2026-08-01T08:00:00Z")
        assert _instant(log["occupation_to"]) == _instant("2026-08-01T09:15:30Z")
        assert log["technician_id"] == env["technician"]["id"]

    def test_02_the_unit_totals_the_billable_minutes_of_its_logs(
        self, api, floor_environment
    ):
        """The unit's running labour total picks up the forty-five billable minutes of its single drum log and the unit advances past drum fabrication.

        PRD: "The unit's `labor_minutes_total` is the sum of `labor_minutes` across every station log belonging to that unit, including logs written in earlier rework rounds."
        Design: Corner/entities/station_log_labor_minutes_floors_partial_minute
        """
        env = floor_environment
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, build["id"])
        payload = f.station_log_payload(
            env["stations"]["drum"]["id"],
            "DRUM_FAB",
            "2026-08-01T08:00:00Z",
            "2026-08-01T08:45:30Z",
            "PASS",
        )
        validate_success(
            api.create_station_log(
                build["id"],
                payload,
                make_technician_headers(env["technician"]["id"]),
            ),
            201,
        )

        data = validate_success(api.get_build_order(build["id"], PLANT_MANAGER), 200)

        assert data["labor_minutes_total"] == 45
        a.assert_build_state(data, "DRUM_DONE")
