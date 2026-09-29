"""What a create returns, what a read returns, and what the server fills in
when the client leaves an optional input out."""
from test_helpers import (
    api_client,
    assert_facility,
    assert_monitoring_system,
    assert_quarterly_report,
    assert_unit,
    is_valid_uuid,
    validate_success,
)
from test_helpers import fixtures as fx

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
CLOCK_APRIL = "2026-04-02T00:00:00Z"
TRUE_UP_DEADLINE = "2027-03-01T00:00:00Z"


def _names_instant(value, instant):
    """An ISO 8601 timestamp naming `instant`, at whatever fractional
    precision the server serialises."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert value.startswith(instant[:-1]), (
        f"expected a timestamp at {instant}, got {value!r}"
    )


class TestFacilityCreateAndUnitRead:
    """One create echoes every input; one read returns the stored row."""

    def test_registering_a_station_echoes_every_input_and_its_initial_state(self):
        """201 with the two programs, the ceiling of 2, OPERATING and version 1.

        PRD: "A `RegulatoryReviewer` brings a station into the system by
        registering a **Facility** with its plant `name`, its `orispl_code` (the
        EIA/EPA plant code, between 1 and 8 characters long and globally unique —
        a repeat is rejected with `ERR_DUPLICATE_ORISPL_CODE`), its `state_code`
        (exactly two uppercase letters), the legal operating company in
        `operator_org`, the allowance `programs` the station is subject to, and the
        `true_up_deadline_utc` before which no allowance true-up may be run."

        PRD: "A new facility begins with `status` of `OPERATING` and a
        `compliance_posture` of `COMPLIANT`."

        Design: Corner/entities/entity_facility_creation_returns_every_declared_field
        """
        fx.set_clock(CLOCK_AUGUST)

        facility = validate_success(
            api_client.create_facility(
                {
                    "name": "Kestrel Generating Station",
                    "orispl_code": "7101",
                    "state_code": "OH",
                    "operator_org": "op_alpha",
                    "programs": ["ARP_SO2", "CSAPR_SO2_G1"],
                    "true_up_deadline_utc": TRUE_UP_DEADLINE,
                    "max_concurrent_control_outages": 2,
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert_facility(facility)

        assert facility["name"] == "Kestrel Generating Station"
        assert facility["orispl_code"] == "7101"
        assert facility["state_code"] == "OH"
        assert facility["operator_org"] == "op_alpha"
        assert facility["programs"] == ["ARP_SO2", "CSAPR_SO2_G1"], (
            "the programs array is echoed verbatim, in the order supplied"
        )
        assert facility["true_up_deadline_utc"] == TRUE_UP_DEADLINE
        assert facility["max_concurrent_control_outages"] == 2

        assert facility["status"] == "OPERATING"
        assert facility["compliance_posture"] == "COMPLIANT", (
            "a brand new station holds no accounts and no reports, so it is "
            "compliant"
        )
        assert facility["version"] == 1
        assert is_valid_uuid(facility["id"])
        _names_instant(facility["created_at"], CLOCK_AUGUST)

    def test_reading_a_unit_returns_the_row_the_nested_create_wrote(self):
        """The facility_id comes from the create path, not from the body.

        PRD: "A unit is described by its boiler designation `unit_identifier`,
        unique among the units of its owning facility; its `primary_fuel`, one of
        `COAL`, `NATURAL_GAS` or `OIL`; its `nameplate_capacity_mw` and its
        `max_rated_heat_input_mmbtu_hr`, both strictly positive; and optionally its
        `control_device`, one of `SCR`, `SNCR`, `FGD` or `NONE` — a unit with no
        post-combustion control records `NONE`."

        PRD: "The unit's owning plant is recorded as `facility_id`."

        Design: Corner/entities/entity_unit_retrieval_returns_the_stored_record
        """
        fx.set_clock(CLOCK_AUGUST)
        facility = fx.create_facility()
        created = fx.create_unit(
            facility["id"],
            unit_identifier="U1",
            primary_fuel="COAL",
            nameplate_capacity_mw=600,
            max_rated_heat_input_mmbtu_hr=6000,
            control_device="FGD",
        )

        unit = validate_success(api_client.get_unit(created["id"], fx.QA))
        assert_unit(unit)

        assert unit["id"] == created["id"]
        assert unit["facility_id"] == facility["id"]
        assert unit["unit_identifier"] == "U1"
        assert unit["primary_fuel"] == "COAL"
        assert unit["nameplate_capacity_mw"] == 600
        assert unit["max_rated_heat_input_mmbtu_hr"] == 6000
        assert unit["control_device"] == "FGD"
        assert unit["version"] == 1, (
            "a read is not a mutation, so the version stays where the create "
            f"left it, got {unit['version']}"
        )


class TestDeclaredDefaultsAndServerFields:
    """Optional inputs fall back; identity fields are never client supplied."""

    def test_three_omitted_optional_inputs_each_take_their_declared_default(self):
        """Ceiling 2, control_device NONE and a 2.5 percent calibration spec.

        PRD: "An optional `max_concurrent_control_outages` caps how much control
        equipment the station may have out of service at once; it defaults to 2 and
        must be at least 1."

        PRD: "A new unit begins `OFFLINE` in `dispatch_state`, `AVAILABLE` in
        `control_status`, with `data_availability_pct` of 100.0,
        `certified_so2_lbs_ytd` of 0.0, and `dispatch_restricted` false."

        PRD: "A new system starts with `qa_status` of `RECERTIFICATION_PENDING`,
        `cal_status` of `CAL_EXPIRED`, `bias_adjustment_factor` of 1.0 and
        `consecutive_failed_calibrations` of 0."

        Design: Corner/entities/entity_omitted_optional_inputs_fall_back_to_declared_defaults
        """
        fx.set_clock(CLOCK_AUGUST)

        facility = validate_success(
            api_client.create_facility(
                {
                    "name": "Kestrel Generating Station",
                    "orispl_code": "7101",
                    "state_code": "OH",
                    "operator_org": "op_alpha",
                    "programs": ["ARP_SO2"],
                    "true_up_deadline_utc": TRUE_UP_DEADLINE,
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert facility["max_concurrent_control_outages"] == 2
        assert facility["status"] == "OPERATING"
        assert facility["compliance_posture"] == "COMPLIANT"

        unit = validate_success(
            api_client.create_unit(
                facility["id"],
                {
                    "unit_identifier": "U1",
                    "primary_fuel": "COAL",
                    "nameplate_capacity_mw": 600,
                    "max_rated_heat_input_mmbtu_hr": 6000,
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert_unit(unit)
        assert unit["control_device"] == "NONE", (
            "a unit with no post-combustion control records NONE"
        )
        assert unit["dispatch_state"] == "OFFLINE"
        assert unit["control_status"] == "AVAILABLE"
        assert unit["dispatch_restricted"] is False
        assert unit["data_availability_pct"] == 100.0
        assert unit["certified_so2_lbs_ytd"] == 0.0

        system = validate_success(
            api_client.install_monitoring_system(
                unit["id"],
                {"parameter": "SO2", "system_type": "CEM", "span_value": 400.0},
                fx.QA,
            ),
            201,
        )
        assert_monitoring_system(system)
        assert system["calibration_error_spec_pct"] == 2.5
        assert system["qa_status"] == "RECERTIFICATION_PENDING"
        assert system["cal_status"] == "CAL_EXPIRED"
        assert system["bias_adjustment_factor"] == 1.0
        assert system["consecutive_failed_calibrations"] == 0

    def test_two_sibling_creates_share_a_created_at_but_never_an_id(self):
        """The logical clock stamps both units; the report's parent is the path.

        PRD: "Every resource carries a server-minted `id`, formatted as a UUID with
        no type prefix, and a `created_at` timestamp — an ISO 8601 UTC string with
        three fractional digits, for example `2026-08-01T00:00:00.000Z`."

        PRD: "It maintains a **logical current UTC instant**, which every
        server-assigned timestamp and every temporal comparison in this
        specification reads."

        PRD: "A new report stands at `DRAFT` with `operating_hour_count`,
        `measured_hour_count`, `substituted_hour_count` and `resubmission_count`
        all 0, every total 0, `monitor_data_availability_pct` at 100.0, and
        `submission_format`, `submitted_by_user_id`, `submitted_utc` and
        `rejection_reason` all null."

        Design: Corner/entities/entity_system_fields_are_server_generated_on_every_create
        """
        fx.set_clock(CLOCK_APRIL)
        facility = fx.create_facility()
        first = fx.create_unit(
            facility["id"], unit_identifier="U1", control_device="FGD"
        )
        second = fx.create_unit(
            facility["id"], unit_identifier="U2", control_device="SCR"
        )

        assert first["id"] != second["id"], "each row gets its own minted id"
        assert is_valid_uuid(first["id"]) and is_valid_uuid(second["id"])
        _names_instant(first["created_at"], CLOCK_APRIL)
        _names_instant(second["created_at"], CLOCK_APRIL)
        assert first["created_at"] == second["created_at"], (
            "both creates read the same pinned logical instant"
        )

        report = validate_success(
            api_client.open_quarterly_report(
                first["id"], {"year": 2026, "quarter": 2}, fx.PREPARER
            ),
            201,
        )
        assert_quarterly_report(report)
        assert is_valid_uuid(report["id"])
        assert report["version"] == 1
        _names_instant(report["created_at"], CLOCK_APRIL)
        assert report["created_at"] == report["updated_at"], (
            "nothing has mutated the report yet"
        )
        assert report["unit_id"] == first["id"], (
            "the parent is taken from the path, never from the body"
        )
        assert report["status"] == "DRAFT"
        assert report["resubmission_count"] == 0
        assert report["operating_hour_count"] == 0
        assert report["measured_hour_count"] == 0
        assert report["substituted_hour_count"] == 0
        assert report["total_heat_input_mmbtu"] == 0
        assert report["total_so2_lbs"] == 0
        assert report["total_nox_lbs"] == 0
        assert report["total_co2_tons"] == 0
        assert report["total_so2_tons"] == 0
        assert report["monitor_data_availability_pct"] == 100.0
        assert report["submission_format"] is None
        assert report["submitted_by_user_id"] is None
        assert report["submitted_utc"] is None
        assert report["rejection_reason"] is None
