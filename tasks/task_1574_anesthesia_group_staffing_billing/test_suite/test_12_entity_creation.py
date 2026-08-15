"""Entity creation claims: defaults, envelopes, required fields, type
constraints, listings, 404s (PRD §2.2, §2.3, §2.4, §2.5, §2.8, §3.1–3.5)."""
from test_helpers import (
    ADMIN,
    SCHED,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_case,
    assert_site,
    build_user_headers,
    create_case,
    create_fee_schedule,
    create_published_roster,
    create_provider,
    create_roster,
    create_site,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_site_fee_roster,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestSiteCreation:
    def test_site_creation_defaults_and_envelope(self, api):
        """PRD §3.1: "a site carries only a `name` and a system-managed
        `status` that is always `ACTIVE` in this version of the API".
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources. The `data` field contains
        the resource object".
        PRD §2.5: "Every persisted resource carries four common properties:
        `id`, a server-minted UUID with no type prefix; `created_at`, an ISO
        8601 UTC timestamp with three fractional digits recorded at creation;
        `updated_at`, the same format, refreshed on every mutation; and
        `version`".

        Design: Corner/entities/site_creation_defaults_system_fields_and_envelope
        """
        resp = api.create_site({"name": "General Hospital"}, ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        site = body["data"]
        assert_site(site)
        assert site["status"] == "ACTIVE"
        assert is_valid_uuid(site["id"])
        assert is_iso8601_timestamp(site["created_at"])
        assert is_iso8601_timestamp(site["updated_at"])
        fetched = get_success_data(api.get_site(site["id"], SCHED))
        assert fetched["name"] == "General Hospital"
        assert fetched["id"] == site["id"]


class TestCaseCreationDefaults:
    def test_new_case_field_defaults(self, api):
        """PRD §3.2: "an optional `emergency_flag` (default false)".
        PRD §3.2: "New cases begin `SCHEDULED`, with `actual_start_minute`,
        `actual_end_minute`, `cancellation_reason`,
        `cancellation_notice_minutes`, `provisional_charge_cents`, and
        `final_charge_cents` all null."

        Design: Corner/entities/case_creation_applies_field_defaults
        """
        site, fee, roster = setup_site_fee_roster()
        resp = api.create_case(
            {"roster_id": roster["id"], "procedure_code": "P100",
             "physical_status": "P2", "scheduled_start_minute": 540,
             "scheduled_end_minute": 600}, SCHED)
        case = validate_success(resp, expected_status=201)
        assert_case(case)
        assert case["emergency_flag"] is False, "default false must be applied"
        assert case["status"] == "SCHEDULED"
        for field in ("actual_start_minute", "actual_end_minute",
                      "cancellation_reason", "cancellation_notice_minutes",
                      "provisional_charge_cents", "final_charge_cents"):
            assert case[field] is None, f"{field} must be null on creation"


class TestAttestationCreationDefaults:
    def test_new_attestation_defaults(self, api):
        """PRD §3.5: "A new attestation begins `IN_PROGRESS`, with
        `submitted_count` at zero, `rejection_reason` null, and all seven step
        flags false by default."

        Design: Corner/entities/attestation_creation_step_defaults_and_zero_count
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director_resp = api.create_provider(
            {"full_name": "Dr. Direct", "provider_type": "ANESTHESIOLOGIST",
             "npi": "1000000002", "credential_expires_on": "2027-01-31",
             "dea_expires_on": "2027-01-31"}, ADMIN)
        director = get_success_data(director_resp)
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        assert att["status"] == "IN_PROGRESS"
        assert att["submitted_count"] == 0
        assert att["rejection_reason"] is None
        for step in ("step_preanesthetic_exam", "step_prescribes_plan",
                     "step_participates_key_portions",
                     "step_ensures_qualified_personnel", "step_monitors_course",
                     "step_available_for_emergencies",
                     "step_post_anesthesia_care"):
            assert att[step] is False, f"{step} must default to false"


class TestRosterCreationPosture:
    def test_new_roster_understaffed_draft(self, api):
        """PRD §3.1: "A new roster begins with `lifecycle` `DRAFT` and
        `posture` `UNDERSTAFFED`."

        Design: Corner/entities/roster_creation_initial_posture_understaffed
        """
        site = create_site()
        roster = get_success_data(api.create_roster(
            {"site_id": site["id"], "service_date": "2026-08-10",
             "required_primary_slots": 2, "scheduled_day_end_minute": 1020},
            SCHED))
        assert roster["lifecycle"] == "DRAFT"
        assert roster["posture"] == "UNDERSTAFFED"


class TestRequiredFieldsAndTypes:
    def test_case_create_missing_required_field_rejected(self, api):
        """PRD §2.8: "**Request schema** — required fields present, types
        correct, enum values valid, no unknown fields, dates well-formed;
        violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/case_create_missing_required_field_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        resp = api.create_case(
            {"roster_id": roster["id"], "procedure_code": "P100",
             "physical_status": "P1", "scheduled_start_minute": 540}, SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_provider_create_invalid_enum_rejected(self, api):
        """PRD §2.7: "a `provider_type` of `ANESTHESIOLOGIST`, `CRNA`, or
        `AA`".
        PRD §2.8: "**Request schema** — required fields present, types
        correct, enum values valid, no unknown fields, dates well-formed;
        violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/provider_create_invalid_enum_rejected
        """
        resp = api.create_provider(
            {"full_name": "Tech Tom", "provider_type": "TECHNICIAN",
             "npi": "1000000099", "credential_expires_on": "2027-01-31",
             "dea_expires_on": "2027-01-31"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_providers(ADMIN))
        assert meta["total_count"] == 0, "no provider may be persisted"

    def test_roster_day_end_out_of_range_rejected(self, api):
        """PRD §2.4: "Start-of-window fields (`scheduled_start_minute`,
        `window_start_minute`, and the roster's `scheduled_day_end_minute`)
        range from 0 through 1438 inclusive".
        PRD §2.8: "**Request schema** — required fields present, types
        correct, enum values valid, no unknown fields, dates well-formed;
        violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/roster_create_day_end_out_of_range_rejected
        """
        site = create_site()
        resp = api.create_roster(
            {"site_id": site["id"], "service_date": "2026-08-10",
             "required_primary_slots": 1, "scheduled_day_end_minute": 1439},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProviderListPagination:
    def test_pagination_envelope_and_filter(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10, with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0. ... The `meta` object of a list response
        carries `limit`, `offset`, `total_count` (the full count of matching
        records, not just the page), and `has_more` (whether further pages
        exist beyond this one)."
        PRD §4: "List providers (filterable by type and status)".

        Design: Corner/entities/list_providers_pagination_envelope
        """
        create_provider("ANESTHESIOLOGIST", "Dr. A")
        create_provider("CRNA", "Crna B")
        create_provider("AA", "Aa C")
        page1, meta1 = validate_paginated(
            api.list_providers(SCHED, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_providers(SCHED, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        filtered, meta3 = validate_paginated(
            api.list_providers(SCHED, params={"provider_type": "CRNA"}))
        assert meta3["total_count"] == 1
        assert filtered[0]["full_name"] == "Crna B"


class TestNotFound:
    def test_detail_gets_with_absent_uuid_return_404(self, api):
        """PRD §2.8: "Unknown resources surface as `ERR_SITE_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_ROSTER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CALL_ASSIGNMENT_NOT_FOUND`,
        `ERR_ATTESTATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_STIPEND_ENTRY_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, or
        `ERR_FINDING_NOT_FOUND`, each HTTP 404."

        Design: Corner/entities/resource_get_not_found_returns_404
        """
        probes = [
            (api.get_site, ApiErrorId.ERR_SITE_NOT_FOUND),
            (api.get_provider, ApiErrorId.ERR_PROVIDER_NOT_FOUND),
            (api.get_roster, ApiErrorId.ERR_ROSTER_NOT_FOUND),
            (api.get_case, ApiErrorId.ERR_CASE_NOT_FOUND),
            (api.get_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_call_assignment, ApiErrorId.ERR_CALL_ASSIGNMENT_NOT_FOUND),
            (api.get_attestation, ApiErrorId.ERR_ATTESTATION_NOT_FOUND),
            (api.get_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api.get_fee_schedule, ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND),
            (api.get_stipend_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api.get_stipend_entry, ApiErrorId.ERR_STIPEND_ENTRY_NOT_FOUND),
            (api.get_audit, ApiErrorId.ERR_AUDIT_NOT_FOUND),
            (api.get_finding, ApiErrorId.ERR_FINDING_NOT_FOUND),
        ]
        for getter, error_id in probes:
            resp = getter(NON_EXISTENT_UUID, ADMIN)
            err = validate_error(resp, error_id)
            assert err.get("message"), f"{error_id}: error envelope must carry a message"
