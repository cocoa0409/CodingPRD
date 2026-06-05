"""Corner — entities section: creation, required fields, defaults, duplicates,
NOT_FOUND, and the backup-clinician requirement.
"""
from test_helpers import (
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    bootstrap_actors,
    create_clinician_payload,
    create_lab_order_payload,
    create_patient_payload,
    make_anonymous_headers,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    register_clinician,
    register_director,
    register_lab_tech,
    register_ordering_provider,
    register_patient,
    set_clock,
    validate_error,
    validate_success,
)


class TestPatientCreation:
    def test_create_patient_returns_201_with_eager_age_band_and_zero_counters(self, api):
        """PRD §3.1: "At registration the system eagerly computes `age_band` from the supplied `date_of_birth` against the server's current clock: under twenty-eight days old yields `NEONATE`, under one year yields `INFANT`, under eighteen years yields `PEDIATRIC`, and at least eighteen years yields `ADULT`."
        PRD §2.4: "an integer `version` field that begins at 1 on creation and is incremented by exactly 1 on every successful mutation."

        Design: Corner/entities/patient_creation_with_all_required_fields_returns_201
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])

        res = api_client.create_patient(
            create_patient_payload(
                mrn="MRN-CR0001",
                full_name="Created Patient",
                date_of_birth="1980-01-01",
            ),
            make_lab_tech_headers(lt["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["mrn"] == "MRN-CR0001"
        assert data["age_band"] == "ADULT", (
            f"DOB 1980-01-01 at clock 2026-05-28 → ADULT; got {data['age_band']!r}"
        )
        assert data["version"] == 1, f"version must start at 1; got {data['version']!r}"
        assert data["results_release_count"] == 0
        assert data["critical_incidents_count"] == 0


class TestPatientCreationRequiresMrn:
    def test_missing_mrn_returns_invalid_request(self, api):
        """PRD §2.10: "structural problems with the request itself — a required input field omitted, a type mismatch, or an enum value outside the declared set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A patient is registered with a medical record number (`mrn`) following the pattern `MRN-` followed by six uppercase alphanumeric characters, a legal `full_name`, and a `date_of_birth` expressed as an ISO 8601 date."

        Design: Corner/entities/patient_creation_missing_mrn_returns_invalid_request
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])

        # Send payload without mrn.
        res = api_client.create_patient(
            {"full_name": "Missing MRN", "date_of_birth": "1980-01-01"},
            make_lab_tech_headers(lt["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestPatientNotFound:
    def test_get_patient_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "the first id that does not resolve to a live row terminates the
        request with `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/patient_get_nonexistent_returns_not_found
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])

        res = api_client.get_patient(NON_EXISTENT_UUID, make_lab_tech_headers(lt["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestPatientDuplicateMrn:
    def test_duplicate_mrn_returns_duplicate_identifier(self, api):
        """PRD §3.1: "The `mrn` is unique across the entire patient population — a
        duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`."

        Design: Corner/entities/patient_duplicate_mrn_returns_duplicate_identifier
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])

        register_patient(lt["id"], mrn="MRN-DUP010", full_name="First")
        res = api_client.create_patient(
            create_patient_payload(
                mrn="MRN-DUP010",
                full_name="Second",
                date_of_birth="1985-01-01",
            ),
            make_lab_tech_headers(lt["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_IDENTIFIER)


class TestClinicianBackupRequirement:
    def test_create_non_director_without_backup_returns_backup_required(self, api):
        """PRD §3.1: "Every clinician whose `role_type` is not `LAB_DIRECTOR` MUST also supply a `backup_clinician_id` naming another clinician; omitting it is rejected with `ERR_BACKUP_REQUIRED`."
        PRD §3.1: "Only a `LAB_DIRECTOR` may register with `backup_clinician_id` omitted."

        Design: Corner/entities/clinician_create_non_director_without_backup_returns_backup_required
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])

        # Try to register a LAB_TECH (non-director) without backup_clinician_id.
        res = api_client.create_clinician(
            create_clinician_payload(
                npi="9940000099",
                full_name="Tech No Backup",
                role_type="LAB_TECH",
                phone_e164="+12025559499",
            ),
            make_lab_director_headers(director["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BACKUP_REQUIRED)


class TestLabOrderPriorityDefault:
    def test_create_lab_order_without_priority_defaults_to_routine(self, api):
        """PRD §3.2: "when omitted, `priority` defaults to `ROUTINE`."

        Design: Corner/entities/lab_order_creation_default_priority_routine
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])
        op = register_ordering_provider(director["id"])
        patient = register_patient(lt["id"], mrn="MRN-DF0100")

        res = api_client.create_lab_order(
            patient["id"],
            create_lab_order_payload(
                ordering_clinician_id=op["id"],
                panel_code="CMP",
                priority=None,
            ),
            make_ordering_provider_headers(op["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["priority"] == "ROUTINE", (
            f"omitted priority must default to ROUTINE; got {data['priority']!r}"
        )
        assert data["status"] == "DRAFT"
