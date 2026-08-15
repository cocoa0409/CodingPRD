"""Entity-level claims (PRD §2.2, §2.4, §3.1): creation defaults, not-found,
required fields, state-gated member creation, append-only note shape,
case-number uniqueness, and conditional benchmark seeding.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    NON_EXISTENT_UUID, is_valid_uuid, create_case_payload,
    create_member_payload, make_case,
    setup_arrived_case, list_case_benchmarks,
)
from test_helpers.fixtures import CM


class TestCaseCreateDefaults:
    def test_case_created_pre_arrival_with_nulls(self, api):
        """PRD §3.1: "The new case starts in `PRE_ARRIVAL` status with
        `actual_arrival_date` null, `airport_pickup_completed` false, and
        `open_transfer_id` null."

        Design: Corner/entities/case_create_defaults
        """
        case = validate_success(api.create_case(
            create_case_payload(case_number="CASE-EN1", household_size=3,
                                scheduled_arrival_date="2026-08-10"), CM), 201)
        assert case["status"] == "PRE_ARRIVAL"
        assert case["airport_pickup_completed"] is False
        assert case["actual_arrival_date"] is None
        assert case["open_transfer_id"] is None
        assert isinstance(case["version"], int)
        assert is_valid_uuid(case["id"])

    def test_fresh_case_reads_on_track_with_no_topics(self, api):
        """PRD §3.3: "Otherwise the posture is `ON_TRACK`." PRD §3.5:
        "the case's derived `topics_completed`, the sorted unique list of
        topics with a `COMPLETED` session".

        Design: Corner/entities/case_create_defaults
        """
        case = validate_success(api.create_case(
            create_case_payload(case_number="CASE-EN1B", household_size=3,
                                scheduled_arrival_date="2026-08-10"), CM), 201)
        fetched = validate_success(api.get_case(case["id"], CM))
        assert fetched["posture"] == "ON_TRACK"
        assert fetched["topics_completed"] == []


class TestCaseGetNotFound:
    def test_get_unknown_case_returns_not_found(self, api):
        """PRD §2.5: "Third, existence: path identifiers are validated
        left-to-right, and then body foreign-key identifiers (`case_id`,
        `member_id`, `housing_unit_id`, `evidence_note_id`) must identify
        existing resources, else `ERR_NOT_FOUND`."

        Design: Corner/entities/case_get_not_found_returns_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, CM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMemberRequiredFields:
    def test_member_without_date_of_birth_rejected(self, api):
        """PRD §3.1: "Each member record carries the owning `case_id`, the
        member's `full_name`, `date_of_birth` as an ISO date, a `relationship`
        of `PRINCIPAL`, `SPOUSE`, `CHILD`, or `OTHER_RELATIVE`, and a
        `work_eligible` flag recording whether the arrival notification says
        the member may legally work." PRD §2.5: "Fourth, schema and field
        validity: required fields present, enum values valid, date ranges
        correctly ordered, `fulfilled_on` inside the allowed window, numeric
        fields non-negative, else `ERR_VALIDATION`."

        Design: Corner/entities/member_create_missing_required_returns_invalid_request
        """
        case = make_case(case_number="CASE-EN3", household_size=2)
        payload = create_member_payload(case_id=case["id"], full_name="No Dob",
                                        relationship="CHILD", work_eligible=False)
        del payload["date_of_birth"]
        resp = api.create_member(payload, CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestMemberCreateAfterArrival:
    def test_add_member_to_arrived_case_rejected(self, api):
        """PRD §3.1: "Member creation is permitted only while the case is
        `PRE_ARRIVAL`; once the family has arrived, attempting to add a member
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/entities/member_create_after_arrival_rejected
        """
        ctx = setup_arrived_case(case_number="CASE-EN4", household_size=1)
        resp = api.create_member(
            create_member_payload(case_id=ctx["case"]["id"],
                                  full_name="Late Member",
                                  date_of_birth="2000-01-01",
                                  relationship="OTHER_RELATIVE",
                                  work_eligible=True), CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCaseNoteAppendOnlyShape:
    def test_note_carries_no_updated_at_or_version(self, api):
        """PRD §2.4: "The sole exception is `CaseNote`, which is append-only
        documentation: it carries `id` and `created_at` only, and both
        `updated_at` and `version` are absent from it." PRD §3.4: "The server
        stamps `author_role` from the request's `X-User-Role` — one of
        `CASE_MANAGER`, `HOUSING_COORDINATOR`, `EMPLOYMENT_SPECIALIST`, or
        `AGENCY_DIRECTOR`."

        Design: Corner/entities/casenote_immutable_shape
        """
        case = make_case(case_number="CASE-EN5", household_size=1)
        note = validate_success(api.create_case_note(
            {"case_id": case["id"], "note_type": "GENERAL",
             "body": "Arrival notification received"}, CM), 201)
        assert is_valid_uuid(note["id"])
        assert note["case_id"] == case["id"]
        assert note["note_type"] == "GENERAL"
        assert note["body"] == "Arrival notification received"
        assert note["author_role"] == "CASE_MANAGER"
        assert note.get("created_at")
        assert "updated_at" not in note
        assert "version" not in note


class TestCaseNumberUniqueness:
    def test_duplicate_case_number_rejected(self, api):
        """PRD §3.1: "Case numbers are unique across the system: a
        registration repeating an already-registered `case_number` is rejected
        with `ERR_DUPLICATE_CASE_NUMBER` (HTTP 409)."

        Design: Corner/entities/case_create_duplicate_number_rejected
        """
        validate_success(api.create_case(
            create_case_payload(case_number="CASE-EN6"), CM), 201)
        resp = api.create_case(
            create_case_payload(case_number="CASE-EN6",
                                agency_affiliate_code="AFF-02",
                                household_size=2,
                                scheduled_arrival_date="2026-08-11"), CM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)


class TestCaseCreateSystemFieldsIgnored:
    def test_injected_status_and_version_ignored(self, api):
        """PRD §3.1: "The new case starts in `PRE_ARRIVAL` status with
        `actual_arrival_date` null, `airport_pickup_completed` false, and
        `open_transfer_id` null." PRD §2.4: "`updated_at` refreshes and
        `version` increments by 1 on every mutation of the resource."

        Design: Corner/entities/case_create_system_fields_input_ignored
        """
        payload = create_case_payload(case_number="CASE-EN7")
        payload["status"] = "ARRIVED"
        payload["version"] = 99
        case = validate_success(api.create_case(payload, CM), 201)
        assert case["status"] == "PRE_ARRIVAL"
        assert case["version"] == 1


class TestBenchmarkConditionalSeeding:
    def _benchmark_types(self, api, case_id):
        benchmarks = list_case_benchmarks(case_id, headers=CM)
        return sorted(bm["service_type"] for bm in benchmarks)

    def test_school_age_child_seeds_school_enrollment_not_employment(self, api):
        """PRD §3.3: "Two more are seeded conditionally from the freshly
        computed member attributes: a `SCHOOL_ENROLLMENT` benchmark with
        `due_rule` `DAYS_30` is seeded only when at least one member has
        `school_age_at_arrival` true, and an `EMPLOYMENT_PLAN` benchmark with
        `due_rule` `DAYS_90` is seeded only when at least one member is
        `work_eligible` and has `age_at_arrival` of at least 18."

        Design: Corner/entities/benchmark_conditional_seeding
        """
        ctx = setup_arrived_case(
            case_number="CASE-EN8A", household_size=2,
            members=[{"full_name": "Child A", "date_of_birth": "2016-05-20",
                      "relationship": "CHILD", "work_eligible": False}])
        types = self._benchmark_types(api, ctx["case"]["id"])
        assert sorted(types) == sorted([
            "HOME_VISIT", "HEALTH_SCREENING", "SSN_APPLICATION",
            "BENEFITS_ENROLLMENT", "CULTURAL_ORIENTATION", "SCHOOL_ENROLLMENT",
        ])

    def test_no_members_seeds_exactly_five_base_benchmarks(self, api):
        """PRD §3.3: "Five benchmarks are always seeded — `HOME_VISIT`,
        `HEALTH_SCREENING`, `SSN_APPLICATION`, and `BENEFITS_ENROLLMENT` each
        carrying a `due_rule` of `DAYS_30`, plus `CULTURAL_ORIENTATION`
        carrying `DAYS_90`."

        Design: Corner/entities/benchmark_conditional_seeding
        """
        ctx = setup_arrived_case(case_number="CASE-EN8B", household_size=1)
        types = self._benchmark_types(api, ctx["case"]["id"])
        assert sorted(types) == sorted([
            "HOME_VISIT", "HEALTH_SCREENING", "SSN_APPLICATION",
            "BENEFITS_ENROLLMENT", "CULTURAL_ORIENTATION",
        ])
