"""Entity-shape, common-field, and response-envelope tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_patient, assert_course, assert_physics_check,
    create_patient_payload, create_course_payload,
    setup_patient, setup_machine, setup_course, setup_submitted_plan,
    PHYS_A,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestPatientEntity:
    def test_patient_creation_returns_server_fields(self):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix." and
        "`version` is an integer that increments on every mutation of the resource".
        PRD §3.1: "A `Scheduler` registers each patient with a medical record
        number `mrn`, the patient's legal `full_name`, and a `date_of_birth`".

        Design: Corner/entities/patient_creation_success_returns_server_fields
        """
        resp = api_client.create_patient(
            create_patient_payload(mrn="MRN-E1", full_name="Entity One",
                                   date_of_birth="1980-01-01"), SCHED)
        data = validate_success(resp, expected_status=201)
        assert_patient(data)
        assert is_valid_uuid(data["id"]), "server must mint the id"
        assert data["version"] == 1, f"new resource version must be 1, got {data['version']}"
        assert data["mrn"] == "MRN-E1"
        assert "status" not in data, "Patient has no status machine"

    def test_patient_creation_missing_mrn_rejected(self):
        """PRD §2.5 (priority 4): "Required fields present, types correct, enum
        values within their declared domains... — `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: registration requires "a medical record number `mrn`".

        Design: Corner/entities/patient_creation_missing_required_field_rejected
        """
        resp = api_client.create_patient(
            {"full_name": "No Mrn", "date_of_birth": "1980-01-01"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_patient_duplicate_mrn_rejected(self):
        """PRD §3.1: "The `mrn` is unique across all patients: a registration
        colliding with an existing record is rejected with `ERR_DUPLICATE_MRN`
        (HTTP 422)."

        Design: Corner/entities/patient_duplicate_mrn_rejected
        """
        get_success_data(api_client.create_patient(
            create_patient_payload(mrn="MRN-DUP", full_name="First"), SCHED))
        resp = api_client.create_patient(
            create_patient_payload(mrn="MRN-DUP", full_name="Second",
                                   date_of_birth="1990-02-02"), SCHED)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MRN, expected_status=422)

    def test_patient_system_fields_input_ignored(self):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix." and
        "`version` is an integer that increments on every mutation of the resource".
        A fresh registration therefore always starts at version 1 with a
        server-minted id regardless of client-supplied lookalike fields.

        Design: Corner/entities/patient_system_fields_input_ignored
        """
        fake_id = "00000000-0000-4000-8000-00000000beef"
        resp = api_client.create_patient(
            create_patient_payload(mrn="MRN-E6", id=fake_id, version=99), SCHED)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != fake_id, "client-supplied id must be ignored"
        assert data["version"] == 1, "client-supplied version must be ignored"


class TestCourseEntity:
    def test_course_creation_computed_defaults(self):
        """PRD §3.1: "The new course anchors itself to its patient through
        `patient_id`, starts in `CONSULT`, and immediately computes its
        `dose_per_fraction_cGy` as the prescribed total divided by the planned
        fraction count, rounded half up to a whole centigray. Its delivery
        counters `delivered_fractions`, `delivered_dose_cGy`, and
        `fractions_since_chart_review` all start at zero, as do the operational
        counters `weekend_makeup_allowance` and `open_interruption_count`."

        Design: Corner/entities/course_creation_computed_defaults
        """
        pat = setup_patient(mrn="MRN-E4", full_name="Entity Four", date_of_birth="1975-05-05")
        resp = api_client.create_course(
            pat["id"],
            create_course_payload(technique="IMRT", prescribed_total_dose_cGy=6000,
                                  planned_fractions=30),
            ONC_A)
        data = validate_success(resp, expected_status=201)
        assert_course(data)
        assert data["dose_per_fraction_cGy"] == 200, "round_half_up(6000/30) == 200"
        assert data["status"] == "CONSULT"
        assert data["delivered_fractions"] == 0
        assert data["delivered_dose_cGy"] == 0
        assert data["fractions_since_chart_review"] == 0
        assert data["weekend_makeup_allowance"] == 0
        assert data["open_interruption_count"] == 0

    def test_course_invalid_technique_enum_rejected(self):
        """PRD §3.1: "the delivery `technique` (exactly one of `THREE_DCRT`,
        `IMRT`, or `SBRT`)". PRD §2.5 (priority 4): "enum values within their
        declared domains ... — `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/course_invalid_technique_enum_rejected
        """
        pat = setup_patient(mrn="MRN-E5")
        resp = api_client.create_course(
            pat["id"],
            create_course_payload(technique="PROTON"),
            ONC_A)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestAppendOnlyRecord:
    def test_physics_check_immutable_record_no_version(self):
        """PRD §2.4: "a physics check, a chart review, and a charge line each
        carry only `id` and `created_at` — both `updated_at` and `version` are
        absent from them, because they are immutable records written once and
        never edited."
        PRD §3.5: "the checker's identity lands in `checker_id`".

        Design: Corner/entities/physics_check_immutable_record_no_version
        """
        ctx = setup_submitted_plan(mrn="MRN-E7", total_dose=4000, fractions=8)
        plan = ctx["plan"]
        resp = api_client.create_physics_check(
            plan["id"], {"check_type": "PRIMARY", "outcome": "PASS"}, PHYS_A)
        check = validate_success(resp, expected_status=201)
        assert_physics_check(check)
        assert check["checker_id"] == "phys_a", "checker recorded from X-User-ID"
        # list shows exactly one record
        lst_resp = api_client.list_physics_checks(plan["id"], ONC_A)
        lst = validate_success(lst_resp)
        assert isinstance(lst, list) and len(lst) == 1


class TestParentScoping:
    def test_fraction_sessions_list_scoped_to_owning_course(self):
        """PRD §3.6: "Each session receives a per-course `fraction_number`,
        assigned as one more than the maximum `fraction_number` over all
        existing sessions of the course and never reused, even after
        cancellation." PRD §4: GET /oncology/treatment-courses/{id}/fraction-sessions
        is described as "List a course's fraction sessions" — the per-course
        listing returns only that course's sessions, so a course with one
        booking lists 1 and an unrelated freshly created course lists 0.

        Design: Corner/entities/fraction_sessions_list_scoped_to_owning_course
        """
        from test_helpers import setup_treatment_ready_linac, book_session, setup_course
        ctx = setup_treatment_ready_linac(mrn="MRN-E8A", total_dose=2000, fractions=10)
        book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                     "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        # unrelated course B
        pat_b = setup_patient(mrn="MRN-E8B", full_name="Entity Eight B", date_of_birth="1972-02-02")
        course_b = setup_course(pat_b["id"], technique="THREE_DCRT",
                                prescribed_total_dose_cGy=3000, planned_fractions=10,
                                intent="PALLIATIVE", diagnosis_code="C18")
        list_a, meta_a = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], SCHED))
        assert len(list_a) == 1 and meta_a["total_count"] == 1
        list_b, meta_b = validate_paginated(
            api_client.list_fraction_sessions(course_b["id"], SCHED))
        assert list_b == [] and meta_b["total_count"] == 0
