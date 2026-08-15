"""Program/discharge creation defaults, envelope shape, 404s, uniqueness, and
unknown-field rejection (PRD §2.2, §2.5, §2.6, §2.11, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_discharge,
    assert_program,
    create_discharge_payload,
    create_program_payload,
    create_unit_payload,
    get_program,
    get_success_data,
    make_admin_headers,
    make_program,
    make_provider,
    make_steward_headers,
    make_unit,
    validate_error,
    validate_success,
)


class TestProgramCreation:
    def test_program_creation_defaults(self, api, admin_headers):
        """PRD §3.1: "The program's `active_vendor_id` is an informational
        pointer to the currently `ACTIVE` vendor; it is null at creation and is
        not enforced as a foreign-key constraint."
        PRD §2.5: "All ten resources in the system — programs, vendors, cycles,
        care units, providers, discharges, sample cases, responses, improvement
        initiatives, and service-recovery tickets — share the same
        system-managed property set:" (including `version`, "a system-managed
        integer that increments on every mutation, including system-driven
        cascades such as counter recomputation.")
        PRD §2.4: "At startup, before any explicit set, the logical clock reads
        exactly `2026-08-01T00:00:00Z`; it must never fall back to the host wall
        clock."

        Design: Corner/entities/program_creation_defaults
        """
        res = api.create_program(
            create_program_payload(
                name="P-E1", sampling_protocol="STRATIFIED_BY_UNIT",
                admin_mode="MIXED_MODE"),
            admin_headers)
        program = validate_success(res, 201)
        assert_program(program)
        assert program["version"] == 1
        assert program["active_vendor_id"] is None
        assert program["sampling_protocol"] == "STRATIFIED_BY_UNIT"
        assert program["created_at"] == "2026-08-01T00:00:00Z"

    def test_program_created_at_matches_logical_clock_default(self, api):
        """PRD §2.4: "The server maintains a logical clock that governs every
        temporal decision in the platform. At startup, before any explicit set,
        the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never
        fall back to the host wall clock."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits, set at creation."

        Design: Corner/entities/program_creation_defaults
        """
        program = make_program(name="P-E1-clock", sampling_protocol="CENSUS",
                               admin_mode="MAIL_ONLY")
        assert program["created_at"] == "2026-08-01T00:00:00Z"
        assert program["updated_at"] == "2026-08-01T00:00:00Z"


class TestDischargeCreation:
    def test_discharge_defaults_pending(self, api):
        """PRD §3.2: "A new discharge lands in `ELIGIBILITY_PENDING` with an
        empty `exclusion_reasons` list."

        Design: Corner/entities/discharge_defaults_pending
        """
        program = make_program(name="P-E2")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        res = api.create_discharge(
            create_discharge_payload(program["id"], unit["id"], provider["id"],
                                     mrn="M-001"),
            make_steward_headers())
        discharge = validate_success(res, 201)
        assert_discharge(discharge)
        assert discharge["status"] == "ELIGIBILITY_PENDING"
        assert discharge["exclusion_reasons"] == []

    def test_discharge_evaluation_runs_only_on_evaluate(self, api):
        """PRD §3.2: "A new discharge lands in `ELIGIBILITY_PENDING` with an
        empty `exclusion_reasons` list."
        PRD §3.2: "Evaluation runs automatically per item inside the bulk import
        and on demand when a `DataSteward` evaluates a discharge"

        Design: Corner/entities/discharge_defaults_pending
        """
        program = make_program(name="P-E2B")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        # Even a plainly excludable patient (EXPIRED) stays ELIGIBILITY_PENDING
        # until evaluation runs.
        discharge = get_success_data(api.create_discharge(
            create_discharge_payload(
                program["id"], unit["id"], provider["id"], mrn="M-900",
                discharge_disposition="EXPIRED", age_years=80),
            make_steward_headers()))
        assert discharge["status"] == "ELIGIBILITY_PENDING"
        assert discharge["exclusion_reasons"] == []

        evaluated = get_success_data(api.evaluate_discharge(
            discharge["id"], {}, make_steward_headers()))
        assert evaluated["status"] == "EXCLUDED"
        assert evaluated["exclusion_reasons"] == ["EXPIRED"]


class TestNotFound:
    def test_discharge_get_not_found_returns_404(self, api, admin_headers):
        """PRD §2.11: "For any endpoint whose path contains resource
        identifiers, the identifiers are validated left to right; the request
        is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not correspond to an existing resource."

        Design: Corner/entities/discharge_get_not_found_returns_404
        """
        res = api.get_discharge(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_discharge_get_not_found_on_empty_and_populated_db(self, api):
        """PRD §2.11: "For any endpoint whose path contains resource
        identifiers, the identifiers are validated left to right; the request
        is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not correspond to an existing resource."

        Design: Corner/entities/discharge_get_not_found_returns_404
        """
        # Empty database.
        validate_error(
            api.get_discharge(NON_EXISTENT_UUID, make_admin_headers()),
            ApiErrorId.ERR_NOT_FOUND)
        # Populated database: an unrelated discharge exists, the queried id
        # still does not.
        program = make_program(name="P-NF")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        get_success_data(api.create_discharge(
            create_discharge_payload(program["id"], unit["id"], provider["id"]),
            make_steward_headers()))
        validate_error(
            api.get_discharge(NON_EXISTENT_UUID, make_admin_headers()),
            ApiErrorId.ERR_NOT_FOUND)


class TestUniquenessPerProgram:
    def test_unit_code_unique_per_program(self, api):
        """PRD §3.1: "Care units are created with `program_id`, `name`, and a
        `unit_code` that must be unique within the program — a duplicate is
        rejected with `ERR_DUPLICATE_UNIT_CODE`."

        Design: Corner/entities/unit_code_unique_per_program
        """
        p1 = make_program(name="P-E3A")
        p2 = make_program(name="P-E3B")
        make_unit(p1["id"], name="Alpha", unit_code="UU")

        dup = api.create_unit(
            create_unit_payload(p1["id"], name="Beta", unit_code="UU"),
            make_admin_headers())
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_UNIT_CODE)

        other = api.create_unit(
            create_unit_payload(p2["id"], name="Gamma", unit_code="UU"),
            make_admin_headers())
        created = validate_success(other, 201)
        assert created["unit_code"] == "UU"
        assert created["program_id"] == p2["id"]

    def test_unit_code_uniqueness_scoped_to_program(self, api):
        """PRD §3.1: "Care units are created with `program_id`, `name`, and a
        `unit_code` that must be unique within the program — a duplicate is
        rejected with `ERR_DUPLICATE_UNIT_CODE`."

        Design: Corner/entities/unit_code_unique_per_program
        """
        p1 = make_program(name="P-E3C")
        p2 = make_program(name="P-E3D")
        make_unit(p1["id"], name="Alpha", unit_code="UU")
        make_unit(p2["id"], name="Beta", unit_code="UU")
        # Each program now holds exactly one "UU" unit; a second in p2 fails.
        res = api.create_unit(
            create_unit_payload(p2["id"], name="Gamma", unit_code="UU"),
            make_admin_headers())
        validate_error(res, ApiErrorId.ERR_DUPLICATE_UNIT_CODE)
        listed = get_success_data(api.list_units(
            make_admin_headers(), params={"program_id": p2["id"], "limit": 100}))
        assert len(listed) == 1

    def test_provider_npi_unique_per_program(self, api):
        """PRD §3.1: "Providers are created with `program_id`, `full_name`,
        `npi`, and `specialty`, where `npi` must be unique within the program
        (`ERR_DUPLICATE_NPI`)."

        Design: Corner/entities/provider_npi_unique_per_program
        """
        program = make_program(name="P-E4")
        make_provider(program["id"], full_name="Dr A", npi="NPI1")
        res = api.create_provider(
            {
                "program_id": program["id"],
                "full_name": "Dr B",
                "npi": "NPI1",
                "specialty": "CARD",
            },
            make_admin_headers())
        validate_error(res, ApiErrorId.ERR_DUPLICATE_NPI)

    def test_provider_npi_duplicate_leaves_single_provider(self, api):
        """PRD §3.1: "Providers are created with `program_id`, `full_name`,
        `npi`, and `specialty`, where `npi` must be unique within the program
        (`ERR_DUPLICATE_NPI`)."

        Design: Corner/entities/provider_npi_unique_per_program
        """
        program = make_program(name="P-E4B")
        make_provider(program["id"], full_name="Dr A", npi="NPI1")
        validate_error(
            api.create_provider(
                {
                    "program_id": program["id"],
                    "full_name": "Dr B",
                    "npi": "NPI1",
                    "specialty": "CARD",
                },
                make_admin_headers()),
            ApiErrorId.ERR_DUPLICATE_NPI)
        listed = get_success_data(api.list_providers(
            make_admin_headers(),
            params={"program_id": program["id"], "limit": 100}))
        assert len(listed) == 1
        assert listed[0]["npi"] == "NPI1"


class TestUnknownFieldRejection:
    def test_discharge_rejects_extra_payload_fields(self, api):
        """PRD §2.6: "5. **Request shape.** Required fields present, unknown
        fields rejected, types correct, enum members valid, dates ISO-formatted,
        composite scores within 1 to 4 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/discharge_rejects_extra_payload_fields
        """
        program = make_program(name="P-E5")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        payload = create_discharge_payload(
            program["id"], unit["id"], provider["id"], mrn="M-001")
        payload["status"] = "ELIGIBLE"  # system-managed field smuggled in
        res = api.create_discharge(payload, make_steward_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_discharge_rejects_computed_field_in_payload(self, api):
        """PRD §2.6: "5. **Request shape.** Required fields present, unknown
        fields rejected, types correct, enum members valid, dates ISO-formatted,
        composite scores within 1 to 4 (`ERR_INVALID_REQUEST`)."
        PRD §3.2: "A new discharge lands in `ELIGIBILITY_PENDING` with an empty
        `exclusion_reasons` list." (so `exclusion_reasons` is server-computed,
        not an accepted input)

        Design: Corner/entities/discharge_rejects_extra_payload_fields
        """
        program = make_program(name="P-E5B")
        unit = make_unit(program["id"])
        provider = make_provider(program["id"])
        payload = create_discharge_payload(
            program["id"], unit["id"], provider["id"], mrn="M-002")
        payload["exclusion_reasons"] = []
        res = api.create_discharge(payload, make_steward_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
