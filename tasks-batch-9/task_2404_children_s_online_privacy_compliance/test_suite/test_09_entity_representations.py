"""Entity representations: declared defaults, computed fields and body references."""

from test_helpers import (
    ENGINEER_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    api_client,
    add_audience_sample,
    add_design_factor,
    assert_instant,
    child_data_record_payload,
    collect_record,
    collection_ready_service,
    create_activity,
    create_program,
    create_service,
    granted_consent,
    mixed_audience_service,
    published_notice,
    read_service,
    run_determination,
    service_version,
    validate_error,
    validate_paginated,
)
from test_helpers import ASSESSOR_HEADERS, CERTIFIER_HEADERS


class TestServiceRegistrationRepresentation:
    """What registration returns, and what it refuses to take from the client."""

    def test_01_registration_returns_every_declared_default(self):
        """A freshly registered service carries the whole initialised record.

        "Registration returns a fully initialised compliance record:
        `determination_status` is `NOT_ASSESSED`, `compliance_posture` is `OPEN`,
        `posture_override` is null, `determination_variant_applied` is null, `design_score`
        is `0.00`, `audience_child_share` is null, `determination_evaluated_at` is null,
        `safe_harbor_status` is `NOT_ENROLLED`, `safe_harbor_expires_at` is null, every
        counter ... is 0, and `version` is 1."

        Design: Corner/entities/service_creation_returns_declared_defaults_and_version_one
        """
        service = create_service(
            name="Fresh Register Kids",
            operator_organization="Fresh Register Media",
            service_category="GAME",
            subject_matter_code="FAMILY_MIXED",
        )

        assert isinstance(service["id"], str) and service["id"]
        assert service["version"] == 1
        assert_instant(service["created_at"], STARTUP_CLOCK, "created_at")
        assert service["determination_status"] == "NOT_ASSESSED"
        assert service["compliance_posture"] == "OPEN"
        assert service["posture_override"] is None
        assert service["determination_variant_applied"] is None
        assert float(service["design_score"]) == 0.00
        assert service["audience_child_share"] is None
        assert service["determination_evaluated_at"] is None
        assert service["safe_harbor_status"] == "NOT_ENROLLED"
        assert service["safe_harbor_expires_at"] is None
        for counter in (
            "active_consent_count",
            "granted_disclosure_consent_count",
            "live_child_data_element_count",
            "lifetime_collected_element_count",
            "third_party_exposure_points",
            "open_audit_count",
            "audit_decision_count",
            "evidence_sequence_counter",
            "compliance_run_sequence",
        ):
            assert service[counter] == 0, f"{counter} starts at 0, got {service[counter]}"
        assert service["name"] == "Fresh Register Kids"
        assert service["operator_organization"] == "Fresh Register Media"
        assert service["service_category"] == "GAME"
        assert service["subject_matter_code"] == "FAMILY_MIXED"

    def test_02_computed_fields_supplied_by_the_client_are_ignored(self):
        """The determination axis is written by the determination, not by the create body.

        "Registration returns a fully initialised compliance record:
        `determination_status` is `NOT_ASSESSED` ... `design_score` is `0.00`", and only
        a determination run "records which of two reasoning variants it used in
        `determination_variant_applied`, then writes `determination_status`".

        Design: Corner/entities/service_create_with_client_supplied_computed_extra_field_ignored
        """
        service = create_service(
            name="Injected Score Kids",
            design_score=0.99,
            determination_status="GENERAL_AUDIENCE",
            compliance_posture="OPEN",
            live_child_data_element_count=42,
        )

        assert float(service["design_score"]) == 0.00, (
            f"the supplied score is ignored, got {service['design_score']}"
        )
        assert service["determination_status"] == "NOT_ASSESSED", (
            f"the supplied status is ignored, got {service['determination_status']}"
        )
        assert service["live_child_data_element_count"] == 0, (
            f"the supplied counter is ignored, got {service['live_child_data_element_count']}"
        )

        add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")
        determined = run_determination(service["id"])
        assert float(determined["design_score"]) == 0.60, (
            f"only the declared calculation writes the score, got {determined['design_score']}"
        )
        assert determined["determination_status"] == "MIXED_AUDIENCE"

    def test_03_reading_a_service_returns_the_stored_row_without_recomputing(self):
        """A read is a read: the determination's own figures come back unchanged.

        A determination run "records which of two reasoning variants it used in
        `determination_variant_applied`, then writes `determination_status`, then stamps
        `determination_evaluated_at` with the current logical-clock instant", and `version`
        "increments by exactly one on each accepted mutation".

        Design: Corner/entities/service_retrieval_returns_the_stored_representation
        """
        determined = mixed_audience_service(name="Readback Kids", service_category="VIDEO_PLATFORM")
        version_after_determination = determined["version"]

        first = read_service(determined["id"], ENGINEER_HEADERS)
        second = read_service(determined["id"], CERTIFIER_HEADERS)

        assert first["id"] == determined["id"]
        assert float(first["design_score"]) == 0.60
        assert first["determination_status"] == "MIXED_AUDIENCE"
        assert first["determination_variant_applied"] == "DESIGN_FIRST", (
            "no verified panel sample exists, got "
            f"{first['determination_variant_applied']}"
        )
        assert_instant(
            first["determination_evaluated_at"], STARTUP_CLOCK, "determination_evaluated_at"
        )
        assert first["version"] == version_after_determination, (
            f"a read never advances version, got {first['version']}"
        )
        assert second["version"] == first["version"]

    def test_04_the_service_list_reports_the_whole_filtered_set(self):
        """Pagination metadata describes the set, not the page.

        "`limit` caps the number of items returned; when omitted it defaults to 10, its
        minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the
        number of items to skip; when omitted it defaults to 0". "Every list response
        includes `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta`
        object", and "list results are ordered by `created_at` ascending."

        Design: Corner/entities/service_listing_applies_limit_offset_and_reports_total_count
        """
        first = create_service(name="Page A")
        create_service(name="Page B")
        third = create_service(name="Page C")

        page_one_rows, page_one_meta = validate_paginated(
            api_client.list_online_services(OFFICER_HEADERS, {"limit": 2, "offset": 0})
        )
        assert page_one_meta["limit"] == 2
        assert page_one_meta["offset"] == 0
        assert page_one_meta["total_count"] == 3
        assert page_one_meta["has_more"] is True
        assert len(page_one_rows) == 2
        assert page_one_rows[0]["id"] == first["id"], (
            "the earliest created row comes first"
        )

        page_two_rows, page_two_meta = validate_paginated(
            api_client.list_online_services(OFFICER_HEADERS, {"limit": 2, "offset": 2})
        )
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False
        assert len(page_two_rows) == 1
        assert page_two_rows[0]["id"] == third["id"]

        _, default_meta = validate_paginated(
            api_client.list_online_services(ASSESSOR_HEADERS)
        )
        assert default_meta["limit"] == 10, (
            f"the declared default page size is 10, got {default_meta['limit']}"
        )
        assert default_meta["offset"] == 0
        assert default_meta["total_count"] == 3
        assert default_meta["has_more"] is False

        _, filtered_meta = validate_paginated(
            api_client.list_online_services(
                OFFICER_HEADERS,
                {"determination_status": "MIXED_AUDIENCE", "limit": 10, "offset": 0},
            )
        )
        assert filtered_meta["total_count"] == 0, (
            "no service has been determined, got "
            f"{filtered_meta['total_count']}"
        )
        assert filtered_meta["has_more"] is False

    def test_05_an_unknown_service_id_in_the_path_is_a_not_found(self):
        """An id that resolves to no row is reported as a missing service.

        "identifiers are resolved strictly left to right and the request fails on the
        **first** one that does not resolve, with the 404 error belonging to that identifier:
        `ERR_SERVICE_NOT_FOUND`, `ERR_AGE_SCREEN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`" and so
        on down the list.

        Design: Corner/entities/service_get_with_unknown_id_reports_missing_service
        """
        existing = create_service(name="Existing Service")

        response = api_client.get_online_service(NON_EXISTENT_UUID, OFFICER_HEADERS)
        error = validate_error(response, "ERR_SERVICE_NOT_FOUND")

        assert isinstance(error.get("message"), str) and error["message"], (
            "the error body carries a non-empty message"
        )
        assert "name" not in error, "an error body carries no entity fields"
        assert read_service(existing["id"])["id"] == existing["id"], (
            "the real id still resolves after the failed lookup"
        )


class TestProgramAndNoticeInputContracts:
    """Optional inputs take their declared defaults; required ones must be supplied."""

    def test_06_omitting_the_optional_program_fields_applies_the_declared_defaults(self):
        """True, 365 and 30, and explicit values win over them.

        "`annual_assessment_required` defaults to true and states whether members owe a
        yearly assessment; `assessment_validity_days` defaults to 365 — a full year — and
        sets how long a certification remains valid; and `assessment_grace_days` defaults to
        30 and sets how long after expiry a member is still treated as merely due rather
        than lapsed."

        Design: Corner/entities/program_create_omitting_optional_fields_applies_declared_defaults
        """
        defaulted = create_program(
            program_name="Default Seal Program", regulator_approved=True
        )

        assert defaulted["annual_assessment_required"] is True
        assert defaulted["assessment_validity_days"] == 365
        assert defaulted["assessment_grace_days"] == 30
        assert defaulted["regulator_approved"] is True
        assert defaulted["version"] == 1

        explicit = create_program(
            program_name="Explicit Seal Program",
            regulator_approved=True,
            annual_assessment_required=False,
            assessment_validity_days=180,
            assessment_grace_days=0,
        )

        assert explicit["annual_assessment_required"] is False, (
            "an explicit false is not overwritten by the default true"
        )
        assert explicit["assessment_validity_days"] == 180
        assert explicit["assessment_grace_days"] == 0, (
            f"an explicit zero survives, got {explicit['assessment_grace_days']}"
        )
        assert explicit["id"] != defaulted["id"]

    def test_07_a_notice_draft_without_content_keys_is_an_invalid_request(self):
        """`content_keys` is an input of the draft, not something the server invents.

        A `ComplianceOfficer` drafts a notice revision "listing in `content_keys` the
        required content sections the notice body actually contains", while only the sibling
        input `disclosed_integration_vendors` "defaults to an empty list". Body shape is
        checked for "Required fields present, correctly typed, and within their declared
        enumerations, else `ERR_INVALID_REQUEST` (422)".

        Design: Corner/entities/notice_create_missing_content_keys_returns_invalid_request
        """
        service = create_service(name="Required Field Kids")
        version_before = service_version(service["id"])

        validate_error(
            api_client.create_parental_notice(
                {
                    "service_id": service["id"],
                    "notice_label": "Notice with no content keys",
                    "delivery_channel": "EMAIL",
                    "expected_service_version": version_before,
                },
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
        )

        assert service_version(service["id"]) == version_before, (
            "a rejected create does not advance the service version"
        )
        _, meta = validate_paginated(
            api_client.list_service_parental_notices(service["id"], OFFICER_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"no notice row was created, got {meta['total_count']}"
        )


class TestDeterminationEvidenceRows:
    """The evidence stamp, its two field groups, and its append-only shape."""

    def test_08_the_evidence_sequence_is_stamped_per_service_from_one(self):
        """Each service runs its own counter.

        "Every accepted row advances the service's `evidence_sequence_counter` by one and is
        stamped with that new value as its `evidence_sequence`, starting at 1 for the first
        row."

        Design: Corner/entities/evidence_create_stamps_system_sequence_and_timestamps
        """
        first_service = create_service(name="Sequence One")
        second_service = create_service(name="Sequence Two")

        row_one = add_design_factor(first_service["id"], "SUBJECT_MATTER", "MODERATE")
        row_two = add_design_factor(first_service["id"], "VISUAL_CONTENT", "INCIDENTAL")
        row_three = add_design_factor(second_service["id"], "SUBJECT_MATTER", "STRONG")

        assert row_one["evidence_sequence"] == 1
        assert row_two["evidence_sequence"] == 2, (
            f"the stamp is monotonic within the service, got {row_two['evidence_sequence']}"
        )
        assert_instant(row_one["created_at"], STARTUP_CLOCK, "created_at")
        assert row_three["evidence_sequence"] == 1, (
            "the second service starts its own sequence at 1, got "
            f"{row_three['evidence_sequence']}"
        )
        assert read_service(first_service["id"])["evidence_sequence_counter"] == 2
        assert read_service(second_service["id"])["evidence_sequence_counter"] == 1

    def test_09_the_two_evidence_field_groups_are_mutually_exclusive(self):
        """Wrong-group fields are a mismatch; an out-of-enum rating is not.

        "An `AUDIENCE_SAMPLE` row **requires** `measurement_method` ... together with
        `period_start`, `period_end`, `total_users` and `users_under_13`, and **must not**
        carry `factor_code` or `rating`. A `DESIGN_FACTOR` row **requires** `factor_code` and
        `rating`, and **must not** carry any of the five sample fields. Either violation is
        rejected with `ERR_EVIDENCE_FIELDS_MISMATCH`", while `rating` "is one of `ABSENT`,
        `INCIDENTAL`, `MODERATE` or `STRONG`".

        Design: Corner/entities/design_factor_evidence_carrying_sample_fields_reports_field_group_mismatch
        """
        service = create_service(name="Field Group Kids")

        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "DESIGN_FACTOR",
                    "factor_code": "SUBJECT_MATTER",
                    "rating": "MODERATE",
                    "total_users": 1000,
                    "users_under_13": 400,
                    "period_start": "2026-06-01T00:00:00Z",
                    "period_end": "2026-07-01T00:00:00Z",
                    "measurement_method": "PANEL",
                },
                OFFICER_HEADERS,
            ),
            "ERR_EVIDENCE_FIELDS_MISMATCH",
        )

        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "AUDIENCE_SAMPLE",
                    "measurement_method": "PANEL",
                    "period_start": "2026-06-01T00:00:00Z",
                    "period_end": "2026-07-01T00:00:00Z",
                    "total_users": 1000,
                    "sample_verified": True,
                },
                OFFICER_HEADERS,
            ),
            "ERR_EVIDENCE_FIELDS_MISMATCH",
        )

        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "DESIGN_FACTOR",
                    "factor_code": "SUBJECT_MATTER",
                    "rating": "OVERWHELMING",
                },
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
        )

        accepted = add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")
        assert accepted["evidence_sequence"] == 1, (
            "none of the refused calls consumed a sequence number, got "
            f"{accepted['evidence_sequence']}"
        )
        assert read_service(service["id"])["evidence_sequence_counter"] == 1

    def test_10_evidence_rows_are_append_only_and_carry_no_version(self):
        """A correction is a new row, and the original stays readable.

        "Determination evidence is the sole exception, and deliberately so: evidence is
        append-only and is never updated after it is written. An evidence row carries only
        `id` and `created_at`. It has **no** `updated_at` field and **no** `version` field,
        and neither field appears in its response payload."

        Design: Corner/entities/determination_evidence_row_exposes_no_version_and_no_write_back
        """
        service = create_service(name="Append Only Kids", service_category="VIDEO_PLATFORM")
        original = add_audience_sample(
            service["id"],
            total_users=1000,
            users_under_13=100,
            measurement_method="PANEL",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=False,
        )
        correction = add_audience_sample(
            service["id"],
            total_users=1000,
            users_under_13=100,
            measurement_method="PANEL",
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            sample_verified=True,
        )

        assert original["sample_verified"] is False
        assert correction["sample_verified"] is True
        assert original["id"] != correction["id"]
        for row in (original, correction):
            assert "version" not in row, "an evidence row carries no version field"
            assert "updated_at" not in row, "an evidence row carries no updated_at field"

        rows, _ = validate_paginated(
            api_client.list_service_determination_evidence(
                service["id"], ENGINEER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert [row["evidence_sequence"] for row in rows] == [1, 2], (
            "evidence is listed by evidence_sequence ascending"
        )
        assert rows[0]["sample_verified"] is False, (
            "the original row was never rewritten"
        )


class TestBodyReferenceResolutionAndCoherence:
    """A body reference must resolve, and then must belong to the named service."""

    def test_11_a_consent_from_another_service_is_a_scope_mismatch(self):
        """Resolution is not coherence.

        "A referenced consent request and a referenced activity definition must both belong
        to the `service_id` given in the body; otherwise the request is rejected with
        `ERR_SERVICE_SCOPE_MISMATCH` (HTTP 422)." A record's `child_pseudonym` "is copied
        from the referenced consent rather than supplied by the caller".

        Design: Corner/entities/record_create_with_consent_from_another_service_reports_scope_mismatch
        """
        bundle = collection_ready_service(child_pseudonym="child-500")
        other_service = create_service(name="Scope Service Y")
        other_notice = published_notice(other_service["id"])
        other_consent = granted_consent(
            other_service["id"],
            other_notice["id"],
            parent_email="guardian.y@x.test",
            child_pseudonym="child-501",
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    bundle["service_id"], other_consent["id"], bundle["activity_id"]
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_SERVICE_SCOPE_MISMATCH",
        )

        record = collect_record(
            bundle["service_id"], bundle["consent_id"], bundle["activity_id"]
        )
        assert record["status"] == "COLLECTED", (
            "only the cross-parent coherence differed between the two calls"
        )
        assert record["child_pseudonym"] == "child-500", (
            f"the pseudonym comes from the consent, got {record['child_pseudonym']}"
        )
        assert read_service(bundle["service_id"])["live_child_data_element_count"] == 1
        assert read_service(other_service["id"])["live_child_data_element_count"] == 0, (
            "the refused call leaked nothing into the other service"
        )

    def test_12_an_unknown_service_id_in_the_body_is_a_not_found(self):
        """A body foreign key is resolved just as a path identifier is.

        "Body foreign keys are resolved in a fixed declaration order — `service_id` first,
        then `notice_id`, then `consent_request_id`, then `activity_id`, then `program_id` —
        and the first unresolvable one determines the error: `ERR_SERVICE_NOT_FOUND` ..."

        Design: Corner/entities/activity_create_with_unknown_service_id_reports_missing_service
        """
        service = create_service(name="Body FK Kids")

        validate_error(
            api_client.create_activity(
                {
                    "service_id": NON_EXISTENT_UUID,
                    "activity_code": "QUIZ",
                    "participation_required_elements": ["SCREEN_NAME"],
                },
                OFFICER_HEADERS,
            ),
            "ERR_SERVICE_NOT_FOUND",
        )

        activity = create_activity(
            service["id"], "QUIZ", ["SCREEN_NAME"]
        )
        assert activity["service_id"] == service["id"], (
            "the stored parent is the one supplied, never inferred"
        )

        rows, meta = validate_paginated(
            api_client.list_service_activities(
                service["id"], ENGINEER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused create left no orphan row, got {meta['total_count']}"
        )
        assert rows[0]["activity_code"] == "QUIZ"
