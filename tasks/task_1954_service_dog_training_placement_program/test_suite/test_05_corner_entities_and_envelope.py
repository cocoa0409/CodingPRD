"""Corner queue: entity creation shape, immutability, lineage, listing,
pagination, and response envelope (PRD §2.2–§2.4, §3.1, §3.4)."""
from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_timestamp_instant,
    create_applicant_payload,
    create_dog_payload,
    create_dog_in_advanced_training,
    record_milestone,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestApplicantCreationInitialState:
    """Corner/entities/applicant_creation_initial_state_and_system_fields."""

    def test_new_applicant_is_submitted_with_version_one(self, api):
        """PRD §3.1: "A new applicant begins in `SUBMITTED`, with
        `verified_income_cents` null and `denial_reason` null."
        PRD §2.4: "All entities except `TrainingMilestone` additionally carry
        `updated_at` (same timestamp format, refreshed on every mutation) and
        `version` (an integer that increments by 1 on every mutation of that
        entity)."

        Design: Corner/entities/applicant_creation_initial_state_and_system_fields
        """
        applicant = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        assert applicant["application_status"] == "SUBMITTED"
        assert applicant["version"] == 1
        assert applicant["verified_income_cents"] is None
        assert applicant["denial_reason"] is None
        assert applicant["reviewed_by_user_id"] is None
        assert applicant["approved_by_user_id"] is None

    def test_created_at_uses_logical_clock_default(self, api):
        """PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to the wall clock."
        PRD §2.4: "Every persisted resource carries an `id`, which is a
        server-minted UUID with no type prefix, and a `created_at` timestamp
        in ISO 8601 UTC format."

        Design: Corner/entities/applicant_creation_initial_state_and_system_fields
        """
        applicant = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        assert_timestamp_instant(
            applicant["created_at"], CLOCK_STARTUP_DEFAULT, "Applicant.created_at"
        )


class TestApplicantRequiredFields:
    """Corner/entities/applicant_missing_required_field_returns_400."""

    def test_missing_email_is_validation_error(self, api):
        """PRD §2.6: "1. **Request shape** — the body is well-formed, required
        fields are present, enum members are valid, and numeric ranges are
        respected ... Violations are rejected with `ERR_VALIDATION` (HTTP
        400)."
        PRD §3.1: "An `IntakeCoordinator` or `ProgramAdmin` opens the pipeline
        by creating an applicant with `full_name`, `email`, `placement_track`,
        `household_income_cents`, and `region`."

        Design: Corner/entities/applicant_missing_required_field_returns_400
        """
        payload = create_applicant_payload()
        del payload["email"]
        resp = api.create_applicant(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestApplicantNotFound:
    """Corner/entities/applicant_get_nonexistent_returns_not_found."""

    def test_unknown_uuid_returns_not_found(self, api):
        """PRD §2.6: "5. **Path resolution** — nested paths resolve left to
        right, parent before child; an unresolvable path parameter is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/applicant_get_nonexistent_returns_not_found
        """
        resp = api.get_applicant(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMilestoneImmutableEvent:
    """Corner/entities/milestone_record_is_immutable_event."""

    def test_milestone_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "`TrainingMilestone` is the single exception: milestone
        records are append-only assessment evidence and carry only `id` and
        `created_at` — both `updated_at` and `version` are absent from
        milestone resources."

        Design: Corner/entities/milestone_record_is_immutable_event
        """
        dog, _raiser, trainer, _pl = create_dog_in_advanced_training()
        milestone = record_milestone(dog["id"], trainer["id"], "OBEDIENCE", 77)
        assert milestone["id"]
        assert milestone["created_at"]
        assert "version" not in milestone, (
            "milestone must not carry a version field"
        )
        assert "updated_at" not in milestone, (
            "milestone must not carry an updated_at field"
        )
        fetched = validate_success(api.get_milestone(milestone["id"], TD))
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestDogBredLineageValidation:
    """Corner/entities/dog_bred_lineage_validation."""

    def _parents(self, api):
        sire = validate_success(
            api.create_dog(
                create_dog_payload(sex="MALE", born_on="2022-01-01"), ADMIN
            ),
            expected_status=201,
        )
        dam = validate_success(
            api.create_dog(
                create_dog_payload(sex="FEMALE", born_on="2022-02-01"), ADMIN
            ),
            expected_status=201,
        )
        return sire, dam

    def test_bred_with_valid_sire_and_dam_accepted(self, api):
        """PRD §3.4: "a `BRED` dog requires `sire_id` referencing an existing
        `MALE` dog and `dam_id` referencing an existing `FEMALE` dog distinct
        from the sire, and forbids `donor_name`."

        Design: Corner/entities/dog_bred_lineage_validation
        """
        sire, dam = self._parents(api)
        pup = validate_success(
            api.create_dog(
                create_dog_payload(
                    origin="BRED",
                    sex="FEMALE",
                    sire_id=sire["id"],
                    dam_id=dam["id"],
                    donor_name=None,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert pup["status"] == "REGISTERED"

    def test_bred_without_dam_rejected(self, api):
        """PRD §3.4: "Lineage rules depend on origin and violations are
        rejected with `ERR_DONOR_LINEAGE_INVALID` (HTTP 422): a `BRED` dog
        requires `sire_id` referencing an existing `MALE` dog and `dam_id`
        referencing an existing `FEMALE` dog distinct from the sire, and
        forbids `donor_name`."

        Design: Corner/entities/dog_bred_lineage_validation
        """
        sire, _dam = self._parents(api)
        resp = api.create_dog(
            create_dog_payload(
                origin="BRED", sex="MALE", sire_id=sire["id"], donor_name=None
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DONOR_LINEAGE_INVALID)

    def test_donated_with_sire_rejected(self, api):
        """PRD §3.4: "a `DONATED` dog requires `donor_name` and forbids both
        `sire_id` and `dam_id`."

        Design: Corner/entities/dog_bred_lineage_validation
        """
        sire, _dam = self._parents(api)
        resp = api.create_dog(
            create_dog_payload(origin="DONATED", sire_id=sire["id"]), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DONOR_LINEAGE_INVALID)


class TestApplicantListPagination:
    """Corner/entities/applicant_list_pagination_defaults."""

    def test_default_limit_and_has_more(self, api):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and must not
        exceed 100; `offset` defaults to 0. Every list response includes the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`
        inside `meta`."

        12 applicants: page 1 has 10 items, total 12, has_more true; page 2
        (offset 10) has 2 items, has_more false.

        Design: Corner/entities/applicant_list_pagination_defaults
        """
        for i in range(12):
            validate_success(
                api.create_applicant(
                    create_applicant_payload(email=f"page{i:02d}@example.org"),
                    COORD,
                ),
                expected_status=201,
            )
        page1, meta1 = validate_paginated(api.list_applicants(COORD))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_applicants(COORD, params={"limit": 10, "offset": 10})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestApplicantListStatusFilter:
    """Corner/entities/applicant_list_status_filter."""

    def test_denied_filter_returns_only_denied(self, api):
        """PRD §4: "GET /api/applicants | List applicants with filters +
        pagination (`application_status?`, `placement_track?`)."
        PRD §3.1: "From either `IN_REVIEW` or `NEEDS_INFO`, the coordinator
        may deny the application, recording the supplied `denial_reason`; the
        applicant lands in the terminal state `DENIED`."

        Design: Corner/entities/applicant_list_status_filter
        """
        a1 = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        validate_success(api.begin_review(a1["id"], COORD))
        validate_success(
            api.deny_applicant(a1["id"], {"denial_reason": "not eligible"}, COORD)
        )
        data, meta = validate_paginated(
            api.list_applicants(COORD, params={"application_status": "DENIED"})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == a1["id"]
        assert data[0]["application_status"] == "DENIED"
        assert data[0]["denial_reason"] == "not eligible"


class TestResponseEnvelopeShapes:
    """Corner/consistency_model/response_envelope_shapes."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        `meta.api_request_id`, `response_type` "object" for a single resource,
        and `data` carrying the resource.

        Design: Corner/consistency_model/response_envelope_shapes
        """
        resp = api.create_applicant(create_applicant_payload(), COORD)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "api_request_id" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["id"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and `data`
        carrying `error_id` and `message`.

        Design: Corner/consistency_model/response_envelope_shapes
        """
        resp = api.get_applicant(NON_EXISTENT_UUID, COORD)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert body["data"]["message"]
