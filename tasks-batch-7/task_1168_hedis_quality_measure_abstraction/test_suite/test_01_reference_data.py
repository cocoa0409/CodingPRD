"""Reference data: seasons, specification loads, members, enrollment, providers.

Covers creation defaults, request-shape validation, existence checks, uniqueness
constraints, closed-interval enrollment overlap, and immediate consistency.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_member,
    assert_season,
    create_member_payload,
    create_provider_payload,
    create_season_payload,
    create_spec_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    load_spec,
    register_member,
    register_provider,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["quality_admin_headers"]


class TestSeasonCreation:
    def test_season_creation_defaults_and_system_fields(self, api):
        """A freshly created season is DRAFT with a zero certified-run counter and
        server-minted identity fields.

        PRD §3.1: "A new season starts in `DRAFT` status with `certified_run_count`
        at zero."
        PRD §2.4: "Most resources additionally carry `created_at` and `updated_at` —
        ISO 8601 UTC timestamps with three fractional digits — and a `version` field,
        an integer that increments by exactly 1 on every mutation of that resource"

        Design: Corner/entities/season_creation_defaults_and_system_fields
        """
        resp = api.create_season(create_season_payload(), ADMIN)
        data = validate_success(resp, 201)
        assert_season(data)
        assert data["status"] == "DRAFT", f"new season must be DRAFT, got {data['status']}"
        assert data["certified_run_count"] == 0
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int)

    def test_season_create_missing_required_field_returns_400(self, api):
        """Omitting the required measurement_year is a body-shape violation.

        PRD §2.9: "Required fields must be present, enum values must lie within their
        declared sets, and on enrollment segments `span_start` must be on or before
        `span_end`; violations return `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A reporting cycle begins when a `QualityAdmin` creates a measurement
        season with its `measurement_year` (the HEDIS year, such as 2025, against which
        service dates and enrollment windows are evaluated)"

        Design: Corner/entities/season_create_missing_required_field_returns_400
        """
        payload = {
            "submission_deadline": "2026-06-15T00:00:00Z",
            "admin_data_cutoff": "2026-03-31T00:00:00Z",
            "approved_supplemental_sources": [],
        }
        resp = api.create_season(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_season_create_with_status_input_ignored(self, api):
        """A smuggled status field cannot change the birth state of a season: no
        validation band rejects extra fields, and every new season is DRAFT.

        PRD §3.1: "A new season starts in `DRAFT` status with `certified_run_count`
        at zero."
        PRD §2.9: "Every request is validated against the following checks in a fixed
        priority order; when several checks would fail, the earliest one determines the
        response and masks the rest."

        Design: Corner/entities/season_create_with_status_input_ignored
        """
        payload = create_season_payload(approved_supplemental_sources=[], status="OPEN")
        resp = api.create_season(payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", (
            f"client-supplied status must not take effect; season is {data['status']}"
        )


class TestSpecLoad:
    def test_spec_optional_field_defaults(self, api):
        """All six optional specification fields default when omitted.

        PRD §3.1: "Optional fields carry defaults: `hybrid_policy` defaults to
        `SAMPLE_ONLY` (the alternative, `ADMIN_SUPPLEMENTED`, selects a different rate
        variant and is meaningful only for `HYBRID` measures), `matching_policy`
        defaults to `EXACT` (the alternative being `TOLERANT`), `sample_size_floor`
        defaults to 411 (the NCQA-style minimum hybrid sample), `gender_requirement`
        defaults to `ANY` (with `F` and `M` as the restrictive alternatives),
        `allowable_gap_days` defaults to 45, and `reporting_weight` defaults to 1.0."

        Design: Corner/entities/spec_optional_field_defaults
        """
        season = validate_success(
            api.create_season(create_season_payload(approved_supplemental_sources=[]), ADMIN),
            201,
        )
        payload = {
            "season_id": season["id"],
            "hedis_measure_code": "BCS",
            "version_label": "2025.1",
            "collection_method": "HYBRID",
            "age_min": 50,
            "age_max": 74,
            "continuous_enrollment_months": 12,
            "anchor_date": "2025-12-31T00:00:00Z",
            "expected_season_version": season["version"],
        }
        resp = api.create_spec(payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["hybrid_policy"] == "SAMPLE_ONLY"
        assert data["matching_policy"] == "EXACT"
        assert data["sample_size_floor"] == 411
        assert data["gender_requirement"] == "ANY"
        assert data["allowable_gap_days"] == 45
        assert data["reporting_weight"] == 1.0

    def test_duplicate_measure_code_returns_409(self, api):
        """The same measure code may be loaded only once per season, even when the
        optimistic-concurrency precondition is satisfied by a fresh season version.

        PRD §3.1: "A measure code may be loaded only once per season: a duplicate
        pairing of `season_id` and `hedis_measure_code` is rejected with
        `ERR_DUPLICATE_MEASURE_CODE`."

        Design: Corner/validations/duplicate_measure_code_returns_409
        """
        season = validate_success(
            api.create_season(create_season_payload(approved_supplemental_sources=[]), ADMIN),
            201,
        )
        first = load_spec(api, season["id"], hedis_measure_code="BCS")
        assert first["status"] == "LOADED"
        season_now = validate_success(api.get_season(season["id"], ADMIN))
        payload = create_spec_payload(
            season["id"],
            season_now["version"],
            hedis_measure_code="BCS",
            version_label="2025.2",
        )
        resp = api.create_spec(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEASURE_CODE)


class TestExistenceAndFkResolution:
    def test_get_run_not_found_returns_404(self, api, analyst_headers):
        """Reading a random run id returns the error envelope with ERR_NOT_FOUND and
        a human-readable message.

        PRD §2.10: "Where a URL contains path parameters, each identifier is resolved
        in left-to-right order, and the first identifier that fails to resolve yields
        `ERR_NOT_FOUND` without evaluating the remainder of the request."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/get_run_not_found_returns_404
        """
        resp = api.get_run(NON_EXISTENT_UUID, analyst_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()

    def test_segment_create_unknown_member_returns_not_found(self, api):
        """The member_id foreign key in an enrollment-segment payload must resolve.

        PRD §2.9: "Path-template identifiers and body-supplied foreign keys —
        `season_id`, `spec_id`, `run_id`, `member_id`, `sample_id`, `chase_id`,
        `abstraction_id`, `batch_id`, `engagement_id` — must resolve, validated
        left-to-right along the path and payload, else `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/segment_create_unknown_member_returns_not_found
        """
        payload = {
            "member_id": NON_EXISTENT_UUID,
            "span_start": "2025-01-01T00:00:00Z",
            "span_end": "2025-12-31T00:00:00Z",
        }
        resp = api.create_enrollment_segment(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_member_create_unknown_provider_ref_returns_not_found(self, api):
        """A provided attributed_provider_ref must resolve to an existing provider.

        PRD §2.9: "Immediately after, on member registration only, a provided
        `attributed_provider_ref` must resolve to an existing provider's
        `provider_ref`, else `ERR_PROVIDER_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/member_create_unknown_provider_ref_returns_not_found
        """
        payload = create_member_payload("M1", attributed_provider_ref="NOPE")
        resp = api.create_member(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)


class TestRequestShapeValidation:
    def test_create_member_missing_auth_headers_returns_400(self, api):
        """A request without the identity headers fails authentication first.

        PRD §2.1: "A request missing either header, or carrying an empty value for
        either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/create_member_missing_auth_headers_returns_400
        """
        resp = api.create_member(create_member_payload("M1"), headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_member_create_invalid_enum_returns_400(self, api):
        """gender outside the declared set {F, M} is a request-shape error.

        PRD §2.9: "Required fields must be present, enum values must lie within their
        declared sets, and on enrollment segments `span_start` must be on or before
        `span_end`; violations return `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "A `QualityAdmin` registers each plan member with a business
        identifier `member_ref`, a `birth_date`, and a `gender` of `F` or `M`"

        Design: Corner/validations/member_create_invalid_enum_returns_400
        """
        payload = create_member_payload("M1", gender="X")
        resp = api.create_member(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_segment_inverted_span_invalid_request(self, api):
        """An enrollment segment with span_start after span_end violates the
        closed-interval shape rule.

        PRD §2.9: "Required fields must be present, enum values must lie within their
        declared sets, and on enrollment segments `span_start` must be on or before
        `span_end`; violations return `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/segment_inverted_span_invalid_request
        """
        member = register_member(api, "M1")
        payload = {
            "member_id": member["id"],
            "span_start": "2025-12-31T00:00:00Z",
            "span_end": "2025-01-01T00:00:00Z",
        }
        resp = api.create_enrollment_segment(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUniquenessConstraints:
    def test_duplicate_member_ref_returns_409(self, api):
        """member_ref is unique across members.

        PRD §3.2: "`member_ref` is unique across members, and a duplicate registration
        is rejected with `ERR_DUPLICATE_MEMBER_REF`."

        Design: Corner/validations/duplicate_member_ref_returns_409
        """
        register_member(api, "M1")
        resp = api.create_member(
            create_member_payload("M1", birth_date="1985-05-05T00:00:00Z", gender="M"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBER_REF)

    def test_duplicate_provider_ref_returns_409(self, api):
        """provider_ref is unique across providers.

        PRD §3.2: "Providers are registered with a unique `provider_ref` (duplicates
        rejected with `ERR_DUPLICATE_PROVIDER_REF`), a display `name`, and an optional
        `specialty`."

        Design: Corner/validations/duplicate_provider_ref_returns_409
        """
        register_provider(api, "P1")
        resp = api.create_provider(create_provider_payload("P1", name="Provider Uno"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROVIDER_REF)


class TestEnrollmentClosedIntervalOverlap:
    def test_non_touching_segments_accepted(self, api):
        """Two closed segments sharing no day coexist: [01-01,06-30] and
        [07-01,12-31] do not overlap because neither endpoint day is shared.

        PRD §3.2: "Two segments of the same member may not overlap: because the
        intervals are closed, a new segment whose `span_start` falls on or before an
        existing segment's `span_end` while its `span_end` falls on or after that
        segment's `span_start` is rejected with `ERR_ENROLLMENT_OVERLAP` — and
        touching endpoints do count as overlap, so a segment starting exactly on the
        day another ends collides."

        Design: Difficulty/resource_temporal_overlap/enrollment_segment_closed_touch_overlap
        """
        member = register_member(api, "M1")
        first = api.create_enrollment_segment(
            {
                "member_id": member["id"],
                "span_start": "2025-01-01T00:00:00Z",
                "span_end": "2025-06-30T00:00:00Z",
            },
            ADMIN,
        )
        validate_success(first, 201)
        second = api.create_enrollment_segment(
            {
                "member_id": member["id"],
                "span_start": "2025-07-01T00:00:00Z",
                "span_end": "2025-12-31T00:00:00Z",
            },
            ADMIN,
        )
        validate_success(second, 201)

    def test_touching_endpoint_segments_rejected(self, api):
        """A new segment whose span_start equals an existing segment's inclusive
        span_end shares that day and is rejected.

        PRD §3.2: "Two segments of the same member may not overlap: because the
        intervals are closed, a new segment whose `span_start` falls on or before an
        existing segment's `span_end` while its `span_end` falls on or after that
        segment's `span_start` is rejected with `ERR_ENROLLMENT_OVERLAP` — and
        touching endpoints do count as overlap, so a segment starting exactly on the
        day another ends collides."

        Design: Difficulty/resource_temporal_overlap/enrollment_segment_closed_touch_overlap
        """
        member = register_member(api, "M1")
        first = api.create_enrollment_segment(
            {
                "member_id": member["id"],
                "span_start": "2025-01-01T00:00:00Z",
                "span_end": "2025-06-30T00:00:00Z",
            },
            ADMIN,
        )
        validate_success(first, 201)
        touching = api.create_enrollment_segment(
            {
                "member_id": member["id"],
                "span_start": "2025-06-30T00:00:00Z",
                "span_end": "2025-08-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(touching, ApiErrorId.ERR_ENROLLMENT_OVERLAP)


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api, analyst_headers):
        """A member created by POST is fully visible to the very next GET.

        PRD §2.4: "Consistency is immediate: when a single request mutates several
        resources (a primary mutation plus its cascades), every one of those mutations
        is visible in the same request's response and in any subsequent read."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        register_provider(api, "P1")
        created = validate_success(
            api.create_member(
                create_member_payload("M1", attributed_provider_ref="P1"), ADMIN
            ),
            201,
        )
        fetched = validate_success(api.get_member(created["id"], analyst_headers))
        assert_member(fetched)
        assert fetched["member_ref"] == "M1"
        assert fetched["gender"] == "F"
        assert fetched["attributed_provider_ref"] == "P1"
