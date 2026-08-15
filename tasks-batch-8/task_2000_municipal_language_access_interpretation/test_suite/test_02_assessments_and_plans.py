"""Language need assessments, threshold classification, and annual plans."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_language_access_plan,
    assert_language_assessment,
    create_assessment,
    create_assessment_payload,
    create_department,
    create_plan,
    make_liaison_headers,
    make_officer_headers,
    setup_certified_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestThresholdClassificationVariants:
    def test_safe_harbor_share_passes_on_population_share(
            self, api, coordinator_headers):
        """PRD §3.2: "Two shares are computed and stored on every new assessment,
        each rounded half up to four decimal places: `lep_share` is
        `lep_speaker_count` divided by `service_area_population`, and
        `encounter_share` is `encounter_count` divided by `total_encounters`."
        PRD §3.2: "`threshold_language_safe` is true when the language's rounded
        share of the population is at least five percent or when at least 1,000
        limited-English-proficient speakers live in the service area"

        Design: Difficulty/dual_variant_calc/threshold_language_safe_harbor_vs_encounter_priority
        """
        dept = create_department(name="Dept Housing", service_area_code="SA-2")
        assessment = create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            lep_speaker_count=600, service_area_population=10000,
            encounter_count=200, total_encounters=10000)
        assert_language_assessment(assessment)
        assert assessment["lep_share"] == pytest.approx(0.06, abs=1e-9)
        assert assessment["threshold_language_safe"] is True, (
            "rounded share 0.06 >= 0.05 satisfies the safe-harbor variant"
        )

    def test_encounter_priority_differs_from_safe_harbor(
            self, api, coordinator_headers):
        """PRD §3.2: "`priority_language` is true when the language's rounded
        share of encounters is at least five percent, and it drives
        prioritization inside the annual plan."
        PRD §3.2: "New assessments land in `DRAFT` with `created_by_user_id`
        stamped from the caller's header."

        Design: Difficulty/dual_variant_calc/threshold_language_safe_harbor_vs_encounter_priority
        """
        dept = create_department(name="Dept Housing", service_area_code="SA-2")
        assessment = create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            lep_speaker_count=600, service_area_population=10000,
            encounter_count=200, total_encounters=10000)
        assert assessment["encounter_share"] == pytest.approx(0.02, abs=1e-9)
        assert assessment["priority_language"] is False, (
            "rounded encounter share 0.02 < 0.05 fails the encounter variant "
            "even though the same record passes safe-harbor"
        )
        assert assessment["status"] == "DRAFT"
        assert assessment["created_by_user_id"] == dept["id"]


class TestSafeHarborBoundary:
    def test_exactly_five_percent_share_is_threshold_safe(
            self, api, coordinator_headers):
        """PRD §3.2: "`threshold_language_safe` is true when the language's
        rounded share of the population is at least five percent or when at
        least 1,000 limited-English-proficient speakers live in the service
        area"

        Design: Difficulty/boundary_precision_check/threshold_language_exactly_five_percent_inclusive
        """
        dept = create_department(name="Dept Elections", service_area_code="SA-10")
        assessment = create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            lep_speaker_count=500, service_area_population=10000,
            encounter_count=100, total_encounters=10000)
        assert assessment["lep_share"] == pytest.approx(0.05, abs=1e-9)
        assert assessment["threshold_language_safe"] is True, (
            "at least five percent is inclusive at exactly 0.05"
        )

    def test_just_below_five_percent_not_threshold_safe(
            self, api, coordinator_headers):
        """PRD §3.2: "`threshold_language_safe` is true when the language's
        rounded share of the population is at least five percent or when at
        least 1,000 limited-English-proficient speakers live in the service
        area"

        Design: Difficulty/boundary_precision_check/threshold_language_exactly_five_percent_inclusive
        """
        dept = create_department(name="Dept Elections", service_area_code="SA-10")
        assessment = create_assessment(
            dept["id"], language_code="fr", plan_year=2026,
            lep_speaker_count=499, service_area_population=10000,
            encounter_count=100, total_encounters=10000)
        assert assessment["lep_share"] == pytest.approx(0.0499, abs=1e-9)
        assert assessment["threshold_language_safe"] is False, (
            "0.0499 < 0.05 and 499 speakers is below the 1,000 count override"
        )


class TestAssessmentWindowOverlap:
    def test_abutting_assessment_windows_allowed(self, api, coordinator_headers):
        """PRD §3.2: "Two assessments for the same department and language may
        not have overlapping windows — abutting windows, where one ends exactly
        as the next begins, are permitted — and a violation is rejected with
        `ERR_ASSESSMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/assessment_period_half_open_adjacency
        """
        dept = create_department(name="Dept Planning", service_area_code="SA-15")
        first = create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            period_start="2026-01-01T00:00:00Z", period_end="2026-06-01T00:00:00Z",
            lep_speaker_count=100, encounter_count=50)
        second = create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            period_start="2026-06-01T00:00:00Z", period_end="2026-12-01T00:00:00Z",
            lep_speaker_count=120, encounter_count=60)
        assert second["status"] == "DRAFT", (
            "a window starting exactly at the predecessor's end must be accepted"
        )
        assert second["id"] != first["id"]

    def test_overlapping_assessment_window_rejected(self, api, coordinator_headers):
        """PRD §3.2: "Two assessments for the same department and language may
        not have overlapping windows — abutting windows, where one ends exactly
        as the next begins, are permitted — and a violation is rejected with
        `ERR_ASSESSMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/assessment_period_half_open_adjacency
        """
        dept = create_department(name="Dept Planning", service_area_code="SA-15")
        create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            period_start="2026-01-01T00:00:00Z", period_end="2026-06-01T00:00:00Z")
        create_assessment(
            dept["id"], language_code="es", plan_year=2026,
            period_start="2026-06-01T00:00:00Z", period_end="2026-12-01T00:00:00Z")
        resp = api.create_assessment(
            create_assessment_payload(
                dept["id"], language_code="es", plan_year=2026,
                period_start="2026-05-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                lep_speaker_count=110, encounter_count=55),
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_PERIOD_OVERLAP.value)
        _, meta = validate_paginated(api.list_assessments(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 2, "the rejected assessment must not persist"


class TestAssessmentInputValidation:
    def test_create_assessment_with_computed_field_rejected(
            self, api, coordinator_headers):
        """PRD §2.10: "Required fields are present, types match, enum values are
        valid, and numeric ranges hold (counts at least zero; populations,
        encounter totals, word counts, and minute declarations strictly positive;
        `period_start` earlier than `period_end`); computed or system fields
        supplied as input are refused — all as `ERR_VALIDATION`."

        Design: Corner/entities/create_assessment_with_computed_field_rejected
        """
        dept = create_department(name="Dept Comp", service_area_code="SA-C2",
                                 annual_budget_cents=100000)
        payload = create_assessment_payload(dept["id"], lep_speaker_count=100)
        payload["lep_share"] = 0.99
        resp = api.create_assessment(payload, make_liaison_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        _, meta = validate_paginated(api.list_assessments(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 0


class TestAssessmentListing:
    def test_assessment_list_filtered_by_department(self, api, coordinator_headers):
        """PRD §2.3: "List endpoints also accept optional equality filters named
        for the resource's own fields — across the API these are `department_id`,
        `plan_year`, `status`, `document_id`, `vendor_contract_id`,
        `translator_id`, `reviewer_id`, `superseded_by_job_id`, `interpreter_id`,
        `interpretation_request_id`, `language_code`, `modality`, and `tier` —
        alongside `limit` and `offset`."

        Design: Corner/entities/assessment_list_filtered_by_department
        """
        dept1 = create_department(name="Dept F1", service_area_code="SA-C5",
                                  annual_budget_cents=100000)
        dept2 = create_department(name="Dept F2", service_area_code="SA-C6",
                                  annual_budget_cents=100000)
        a1 = create_assessment(dept1["id"], lep_speaker_count=100)
        a2 = create_assessment(dept2["id"], lep_speaker_count=200)
        data, meta = validate_paginated(api.list_assessments(
            coordinator_headers, params={"department_id": dept1["id"]}))
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [a1["id"]], (
            f"filter must exclude {a2['id']} which belongs to another department"
        )


class TestAssessmentReview:
    def test_assessment_reject_requires_note(self, api, coordinator_headers):
        """PRD §3.2: "`REJECT` additionally requires a `rejection_note` in the
        payload (its absence is `ERR_VALIDATION`) and records the note on the
        assessment."

        Design: Corner/state_machines/assessment_reject_requires_note
        """
        dept = create_department(name="Dept Rej", service_area_code="SA-C13",
                                 annual_budget_cents=100000)
        assessment = create_assessment(dept["id"], lep_speaker_count=100)

        missing_note = api.review_assessment(
            assessment["id"], {"decision": "REJECT"}, make_officer_headers())
        validate_error(missing_note, ApiErrorId.ERR_VALIDATION.value)
        still_draft = validate_success(api.get_assessment(
            assessment["id"], coordinator_headers))
        assert still_draft["status"] == "DRAFT"

        rejected = validate_success(api.review_assessment(
            assessment["id"],
            {"decision": "REJECT", "rejection_note": "stale survey data"},
            make_officer_headers(),
        ))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_note"] == "stale survey data"

    def test_get_assessment_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_assessment_not_found_returns_404
        """
        resp = api.get_assessment(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)


class TestAnnualPlanPublication:
    def test_publish_requires_certified_assessments_then_succeeds(
            self, api, coordinator_headers):
        """PRD §3.2: "every department must hold at least one assessment whose
        `plan_year` matches the plan's `plan_year` by value (it is a year match,
        not a record reference) and whose status is `CERTIFIED`; otherwise
        publication fails with `ERR_MISSING_CERTIFIED_ASSESSMENTS`."

        Design: Corner/validations/publish_requires_certified_assessments_then_succeeds
        """
        dept = create_department(name="Dept Pub", service_area_code="SA-C16",
                                 annual_budget_cents=100000)
        plan = create_plan(plan_year=2026, summary="FY26 plan")

        blocked = api.publish_language_access_plan(plan["id"], coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_MISSING_CERTIFIED_ASSESSMENTS.value)
        still_draft = validate_success(api.get_language_access_plan(
            plan["id"], coordinator_headers))
        assert still_draft["status"] == "DRAFT"

        setup_certified_assessment(dept["id"], plan_year=2026)
        published = validate_success(api.publish_language_access_plan(
            plan["id"], coordinator_headers))
        assert_language_access_plan(published)
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None

    def test_publish_supersedes_previous_plan(self, api, coordinator_headers):
        """PRD §3.2: "A successful publication stamps `published_at` from the
        logical clock and moves the previously `PUBLISHED` plan, if any, to
        `SUPERSEDED`, which is terminal."

        Design: Corner/validations/publish_supersedes_previous_plan
        """
        dept = create_department(name="Dept Plan", service_area_code="SA-C17",
                                 annual_budget_cents=100000)
        setup_certified_assessment(dept["id"], plan_year=2026)
        setup_certified_assessment(
            dept["id"], plan_year=2027,
            period_start="2027-01-01T00:00:00Z", period_end="2027-07-01T00:00:00Z")
        plan26 = create_plan(plan_year=2026)
        validate_success(api.publish_language_access_plan(
            plan26["id"], coordinator_headers))
        plan27 = create_plan(plan_year=2027)

        published27 = validate_success(api.publish_language_access_plan(
            plan27["id"], coordinator_headers))
        assert published27["status"] == "PUBLISHED"
        plan26_after = validate_success(api.get_language_access_plan(
            plan26["id"], coordinator_headers))
        assert plan26_after["status"] == "SUPERSEDED"

    def test_plan_year_conflict_for_duplicate_year(self, api, coordinator_headers):
        """PRD §3.2: "at most one plan per `plan_year` may exist among the
        `DRAFT` and `PUBLISHED` states — a conflicting creation fails with
        `ERR_PLAN_YEAR_CONFLICT`."

        Design: Corner/validations/plan_year_conflict_for_duplicate_year
        """
        plan = create_plan(plan_year=2028)
        resp = api.create_language_access_plan({"plan_year": 2028}, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_YEAR_CONFLICT.value)
        after = validate_success(api.get_language_access_plan(
            plan["id"], coordinator_headers))
        assert after["status"] == "DRAFT"

    def test_get_plan_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_plan_not_found_returns_404
        """
        resp = api.get_language_access_plan(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value)
