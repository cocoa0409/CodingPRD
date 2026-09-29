"""Catalogue and shop-floor rejections at the edges of the rule set.

Machine-model registration guards its per-product-line capacity band and its
model-code uniqueness, a station log is refused when the referenced station is
the wrong type, the wrong tooling or under maintenance, and the floor's temporal
guards refuse a reversed work interval and a double-booked technician.
"""

from prd_bench_local_runner.testing import validate_success, validate_error
from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    make_distributor_headers,
    make_technician_headers,
)

# The standard drum-fabrication visit of the default floor timeline.
DRUM_START = "2026-08-01T08:00:00Z"
DRUM_END = "2026-08-01T09:00:00Z"


def _certified_on_premises_floor(api, station_overrides, scopes):
    """A certified ON_PREMISES model, one station, one certified factory
    technician and one unit released to the floor and waiting for drum work."""
    env = fx.make_certified_model(api)
    station = fx.make_station(api, **station_overrides)
    technician = fx.make_certified_technician(
        api, scopes, employee_code="T-100", full_name="Ann Ito", employer="FACTORY"
    )
    build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
    fx.release_build(api, build["id"])
    return {
        "model": env["model"],
        "station": station,
        "technician": technician,
        "build": build,
    }


class TestMachineModelRegistrationValidations:
    """Registration-time guards on the machine-model catalogue."""

    def test_01_capacity_rating_outside_product_line_band_rejected(self, api):
        """A 90 lb vended machine is refused because the band is read against the
        declared product line, while the same rating is a legal on-premises unit.

        PRD: "A registration whose `capacity_rating_lb` falls outside the band its own `product_line` allows is rejected with `ERR_CAPACITY_RATING_OUT_OF_BAND`."
        Design: Corner/validations/capacity_rating_outside_product_line_band_rejected
        """
        rejected = api.create_machine_model(
            f.machine_model_payload(
                model_code="VND-90-C",
                product_line="VENDED",
                capacity_rating_lb=90,
                rated_water_gal_per_cwt=0.95,
                rated_kwh_per_cwt=0.38,
                drum_alloy_grade="AISI_316",
                payment_module_options=["COIN"],
                list_price_cents=900000,
            ),
            PRODUCT_ENGINEER,
        )
        validate_error(
            rejected, E.ERR_CAPACITY_RATING_OUT_OF_BAND, expected_status=422
        )

        catalogue = validate_success(
            api.list_machine_models(PRODUCT_ENGINEER), expected_status=200
        )
        assert catalogue == [], f"A rejected registration stored a row: {catalogue}"

        # The on-premises band runs from 20 to 200 pounds inclusive, and an
        # on-premises machine is metered by the facility so it offers no
        # payment modules at all.
        accepted = validate_success(
            api.create_machine_model(
                f.machine_model_payload(
                    model_code="VND-90-C",
                    product_line="ON_PREMISES",
                    capacity_rating_lb=90,
                    rated_water_gal_per_cwt=0.95,
                    rated_kwh_per_cwt=0.38,
                    drum_alloy_grade="AISI_316",
                    payment_module_options=[],
                    list_price_cents=900000,
                ),
                PRODUCT_ENGINEER,
            ),
            expected_status=201,
        )
        assert accepted["capacity_rating_lb"] == 90
        assert accepted["product_line"] == "ON_PREMISES"

    def test_02_duplicate_model_code_rejected(self, api):
        """Reusing a catalogue code for a machine on a different product line is
        still a collision, because the code is unique across the whole catalogue.

        PRD: "A duplicate `model_code` is rejected with `ERR_DUPLICATE_RESOURCE_CODE`."
        Design: Corner/validations/duplicate_model_code_rejected
        """
        first = fx.make_model(api)

        duplicate = api.create_machine_model(
            f.tunnel_model_payload(
                model_code="OPL-60-A",
                capacity_rating_lb=300,
                rated_water_gal_per_cwt=0.85,
                rated_kwh_per_cwt=0.55,
                list_price_cents=9800000,
            ),
            PRODUCT_ENGINEER,
        )
        validate_error(duplicate, E.ERR_DUPLICATE_RESOURCE_CODE, expected_status=409)

        catalogue = validate_success(
            api.list_machine_models(PRODUCT_ENGINEER), expected_status=200
        )
        assert len(catalogue) == 1, catalogue
        assert catalogue[0]["id"] == first["id"]


class TestStationLogReferentialGuards:
    """The three checks a station log runs against the station it names."""

    def test_01_station_type_mismatch_between_body_and_station_rejected(self, api):
        """A drum-fabrication operation claimed at a bearing-installation cell is
        refused even though the unit is waiting for exactly that operation.

        PRD: "The submitted `station_type` must equal the `station_type` recorded on the referenced station, or the log is rejected with `ERR_STATION_TYPE_MISMATCH` — a technician cannot log a bearing operation at a drum-fabrication cell."
        Design: Corner/validations/station_type_mismatch_between_body_and_station_rejected
        """
        # The technician holds both scopes, so the certification gate cannot be
        # what refuses this log.
        env = _certified_on_premises_floor(
            api,
            {
                "station_code": "BRG-01",
                "station_type": "BEARING_INSTALL",
                "parallel_capacity": 1,
                "changeover_buffer_minutes": 15,
                "supported_product_lines": ["ON_PREMISES"],
            },
            ["DRUM_FAB", "BEARING_INSTALL"],
        )

        rejected = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["station"]["id"], "DRUM_FAB", DRUM_START, DRUM_END, "PASS"
            ),
            make_technician_headers(env["technician"]["id"]),
        )
        validate_error(rejected, E.ERR_STATION_TYPE_MISMATCH, expected_status=422)

        build = validate_success(
            api.get_build_order(env["build"]["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "ON_FLOOR"
        assert build["station_pass_count"] == 0

        logs = validate_success(
            api.list_station_logs(PLANT_MANAGER, build_order_id=env["build"]["id"]),
            expected_status=200,
        )
        assert logs == [], f"A rejected log was written: {logs}"

    def test_02_station_product_line_unsupported_rejected(self, api):
        """A drum cell tooled only for vended machines refuses the on-premises
        unit under build even though the operation and the scope both line up.

        PRD: "The `product_line` of the unit's model must appear in the station's `supported_product_lines`, or the log is rejected with `ERR_STATION_LINE_UNSUPPORTED`; a station tooled only for vended machines cannot build a tunnel system."
        Design: Corner/validations/station_product_line_unsupported_rejected
        """
        env = _certified_on_premises_floor(
            api,
            {
                "station_code": "DRUM-V",
                "station_type": "DRUM_FAB",
                "parallel_capacity": 1,
                "changeover_buffer_minutes": 30,
                "supported_product_lines": ["VENDED"],
            },
            ["DRUM_FAB"],
        )

        rejected = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["station"]["id"], "DRUM_FAB", DRUM_START, DRUM_END, "PASS"
            ),
            make_technician_headers(env["technician"]["id"]),
        )
        validate_error(rejected, E.ERR_STATION_LINE_UNSUPPORTED, expected_status=422)

        build = validate_success(
            api.get_build_order(env["build"]["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "ON_FLOOR"
        assert build["labor_minutes_total"] == 0

    def test_03_station_in_maintenance_accepts_no_logs_rejected(self, api):
        """A cell standing in maintenance refuses an otherwise perfect drum log.

        PRD: "And the station's `station_state` must be `OPEN`; a station in `MAINTENANCE` rejects the log with `ERR_STATION_UNAVAILABLE`."
        Design: Corner/validations/station_in_maintenance_accepts_no_logs_rejected
        """
        env = _certified_on_premises_floor(
            api,
            {
                "station_code": "DRUM-01",
                "station_type": "DRUM_FAB",
                "parallel_capacity": 1,
                "changeover_buffer_minutes": 30,
                "supported_product_lines": ["ON_PREMISES"],
                "station_state": "MAINTENANCE",
            },
            ["DRUM_FAB"],
        )

        rejected = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["station"]["id"], "DRUM_FAB", DRUM_START, DRUM_END, "PASS"
            ),
            make_technician_headers(env["technician"]["id"]),
        )
        validate_error(rejected, E.ERR_STATION_UNAVAILABLE, expected_status=409)

        station = validate_success(
            api.get_assembly_station(env["station"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        assert station["station_state"] == "MAINTENANCE"

        build = validate_success(
            api.get_build_order(env["build"]["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "ON_FLOOR"


class TestQuoteLinePaymentModuleGuard:
    """A quote line may only order payment hardware the quoted model offers."""

    def test_01_payment_module_absent_from_model_options_rejected(self, api):
        """A coin module ordered against an on-premises model that offers no
        payment hardware is refused, while the same line with no module is taken.

        PRD: "A `payment_module` of `NONE` is always acceptable; any of the three real modules must appear in the quoted model's `payment_module_options`, or the line is rejected with `ERR_PAYMENT_MODULE_NOT_SUPPORTED`."
        Design: Corner/validations/payment_module_absent_from_model_options_rejected
        """
        model = fx.make_model(api)
        distributor = fx.make_distributor(api)
        distributor_headers = make_distributor_headers(distributor["id"])
        quote = validate_success(
            api.create_quote(
                f.quote_payload(distributor["id"], financing_program="NONE"),
                distributor_headers,
            ),
            expected_status=201,
        )
        drafted_version = quote["version"]

        rejected = api.create_quote_line(
            quote["id"],
            f.quote_line_payload(
                model["id"], drafted_version, quantity=1, payment_module="COIN"
            ),
            distributor_headers,
        )
        validate_error(
            rejected, E.ERR_PAYMENT_MODULE_NOT_SUPPORTED, expected_status=422
        )

        unchanged = validate_success(
            api.get_quote(quote["id"], distributor_headers), expected_status=200
        )
        assert unchanged["line_count"] == 0
        assert unchanged["total_cents"] == 0
        assert unchanged["version"] == drafted_version

        accepted = validate_success(
            api.create_quote_line(
                quote["id"],
                f.quote_line_payload(
                    model["id"], drafted_version, quantity=1, payment_module="NONE"
                ),
                distributor_headers,
            ),
            expected_status=201,
        )
        assert accepted["payment_module"] == "NONE"


class TestStationLogTemporalGuards:
    """Interval sanity and technician contention on a station log."""

    def test_01_station_log_with_completed_before_started_rejected(self, api):
        """A work interval that finishes before it starts is refused, and so is
        one whose two instants are equal.

        PRD: "The work interval must be non-degenerate: `started_at` strictly before `completed_at`, or the log is rejected with `ERR_INTERVAL_INVALID`."
        Design: Corner/validations/station_log_with_completed_before_started_rejected
        """
        env = _certified_on_premises_floor(
            api,
            {
                "station_code": "DRUM-01",
                "station_type": "DRUM_FAB",
                "parallel_capacity": 1,
                "changeover_buffer_minutes": 30,
                "supported_product_lines": ["ON_PREMISES"],
            },
            ["DRUM_FAB"],
        )
        technician_headers = make_technician_headers(env["technician"]["id"])

        reversed_log = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["station"]["id"], "DRUM_FAB", DRUM_END, DRUM_START, "PASS"
            ),
            technician_headers,
        )
        validate_error(reversed_log, E.ERR_INTERVAL_INVALID, expected_status=400)

        logs = validate_success(
            api.list_station_logs(PLANT_MANAGER, build_order_id=env["build"]["id"]),
            expected_status=200,
        )
        assert logs == [], f"A rejected log was written: {logs}"

        degenerate_log = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["station"]["id"], "DRUM_FAB", DRUM_END, DRUM_END, "PASS"
            ),
            technician_headers,
        )
        validate_error(degenerate_log, E.ERR_INTERVAL_INVALID, expected_status=400)

    def test_02_technician_double_booked_across_two_stations_rejected(self, api):
        """One technician cannot work two units at once even at two idle cells,
        and may legitimately start the moment the previous operation finished.

        PRD: "If any existing log of the same technician overlaps the new one under that rule, the log is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."
        Design: Corner/validations/technician_double_booked_across_two_stations_rejected
        """
        env = fx.make_certified_model(api)
        first_cell = fx.make_station(
            api,
            station_code="DRUM-01",
            station_type="DRUM_FAB",
            parallel_capacity=1,
            changeover_buffer_minutes=0,
            supported_product_lines=["ON_PREMISES"],
        )
        second_cell = fx.make_station(
            api,
            station_code="DRUM-02",
            station_type="DRUM_FAB",
            parallel_capacity=1,
            changeover_buffer_minutes=0,
            supported_product_lines=["ON_PREMISES"],
        )
        technician = fx.make_certified_technician(
            api,
            ["DRUM_FAB"],
            employee_code="T-100",
            full_name="Ann Ito",
            employer="FACTORY",
        )
        first_unit = fx.make_build_order(
            api, env["model"]["id"], serial_number="SN-0001"
        )
        fx.release_build(api, first_unit["id"])
        second_unit = fx.make_build_order(
            api, env["model"]["id"], serial_number="SN-0002"
        )
        fx.release_build(api, second_unit["id"])
        fx.log_station_pass(
            api, first_unit["id"], first_cell, technician["id"], DRUM_START, DRUM_END
        )

        # The second cell is idle, so nothing but the person can refuse this log.
        overlapping = api.create_station_log(
            second_unit["id"],
            f.station_log_payload(
                second_cell["id"],
                "DRUM_FAB",
                "2026-08-01T08:30:00Z",
                "2026-08-01T09:30:00Z",
                "PASS",
            ),
            make_technician_headers(technician["id"]),
        )
        validate_error(overlapping, E.ERR_TECHNICIAN_DOUBLE_BOOKED, expected_status=409)

        build = validate_success(
            api.get_build_order(second_unit["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "ON_FLOOR"

        # Work intervals are half-open, so the technician may begin at exactly
        # the instant the earlier operation finished.
        accepted = validate_success(
            api.create_station_log(
                second_unit["id"],
                f.station_log_payload(
                    second_cell["id"],
                    "DRUM_FAB",
                    "2026-08-01T09:00:00Z",
                    "2026-08-01T10:00:00Z",
                    "PASS",
                ),
                make_technician_headers(technician["id"]),
            ),
            expected_status=201,
        )
        assert accepted["technician_id"] == technician["id"]
