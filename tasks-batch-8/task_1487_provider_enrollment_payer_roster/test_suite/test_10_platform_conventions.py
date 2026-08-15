"""Platform-wide conventions: resource creation and onboarding cascades,
response envelopes, list filtering, the logical clock, optimistic concurrency
on roster submission, and immediate consistency (PRD §2, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_caqh_profile,
    assert_provider,
    create_active_agreement,
    create_approved_application,
    create_claim,
    create_draft_application,
    create_payer_config,
    create_practice_group,
    create_provider,
    create_submitted_application,
    find_record,
    get_agreement,
    get_caqh_profile,
    get_roster_line,
    roster_add_line,
    set_clock,
    setup_group_provider_payer,
    submit_roster_file,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestProviderOnboarding:
    def test_provider_creation_creates_caqh_profile(self, api):
        """PRD §3.1: "A new provider starts in `ACTIVE` status with
        `termination_date` and `termination_reason` both null and a
        `recoupment_balance_cents` of zero. Creating a provider automatically
        creates exactly one CAQH profile for them, in `NEVER_ATTESTED` status
        with `last_attested_at` and `due_at` both null; reading a provider's
        CAQH profile returns an array containing that single profile."

        Design: Corner/entities/provider_creation_creates_caqh_profile
        """
        group = create_practice_group()
        provider = validate_success(
            api.create_provider(
                group["id"],
                {"npi": "NPI-P1", "full_name": "Dr One", "specialty": "IM"},
                SPECIALIST,
            ),
            201,
        )
        assert_provider(provider)
        assert provider["status"] == "ACTIVE"
        assert provider["recoupment_balance_cents"] == 0
        assert provider["termination_date"] is None
        assert provider["termination_reason"] is None
        assert provider["practice_group_id"] == group["id"]

        profiles = validate_success(
            api.get_provider_caqh_profile(provider["id"], SPECIALIST), 200
        )
        assert isinstance(profiles, list) and len(profiles) == 1
        assert_caqh_profile(profiles[0])
        assert profiles[0]["status"] == "NEVER_ATTESTED"
        assert profiles[0]["due_at"] is None
        assert profiles[0]["last_attested_at"] is None
        assert profiles[0]["provider_id"] == provider["id"]

    def test_duplicate_npi_rejected_across_the_whole_system(self, api):
        """PRD §3.1: "The `npi` must be unique across every provider in the
        system: a duplicate is rejected with `ERR_DUPLICATE_NPI`."

        Design: Corner/entities/provider_duplicate_npi_rejected
        """
        group = create_practice_group()
        create_provider(group["id"], npi="NPI-DUP", full_name="Dr One")
        res = api.create_provider(
            group["id"],
            {"npi": "NPI-DUP", "full_name": "Dr Two", "specialty": "PD"},
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_NPI)

    def test_get_provider_with_unknown_id_returns_404(self, api):
        """PRD §2.8: "3. **Existence** — path identifiers resolve to existing
        resources, validated left to right (a parent before the child beneath
        it), and body foreign keys such as `provider_id`, `payer_id`, and
        `agreement_id` resolve, else `ERR_NOT_FOUND` (404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/provider_get_not_found_returns_404
        """
        res = api.get_provider(NON_EXISTENT_UUID, OFFICER)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert error["error_id"] == "ERR_NOT_FOUND"


class TestResponseEnvelopeShape:
    def test_object_and_array_envelopes(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/endpoints/success_envelope_shape_on_object_and_array
        """
        group = create_practice_group()

        obj_res = api.get_practice_group(group["id"], SPECIALIST)
        obj_body = obj_res.json()
        assert obj_res.status_code == 200
        assert obj_body["response_type"] == "object"
        assert isinstance(obj_body["data"], dict)
        assert obj_body["data"]["id"] == group["id"]
        assert isinstance(obj_body["meta"].get("api_request_id"), str)
        assert isinstance(obj_body["meta"].get("api_request_timestamp"), str)

        list_res = api.list_group_providers(group["id"], SPECIALIST)
        list_body = list_res.json()
        assert list_res.status_code == 200
        assert list_body["response_type"] == "array"
        assert isinstance(list_body["data"], list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"meta missing {field}"


class TestListFiltering:
    def test_applications_filter_by_status_and_provider(self, api):
        """PRD §2.3: "Collections support equality filters drawn from their
        foreign keys and statuses. Enrollment applications filter by
        `provider_id`, `payer_id`, and `status`".

        Design: Corner/endpoints/applications_filter_by_status_and_provider
        """
        _, provider, _, payer_a = setup_group_provider_payer()
        payer_b = create_payer_config(payer_code="PB", name="Payer B")
        app_a = create_submitted_application(provider["id"], payer_a["id"])
        app_b = create_draft_application(provider["id"], payer_b["id"])

        data, meta = validate_paginated(
            api.list_enrollment_applications(
                SPECIALIST,
                params={"provider_id": provider["id"], "status": "DRAFT"},
            )
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == app_b["id"], "only the DRAFT application matches"


class TestOptimisticConcurrencyOnRosterSubmission:
    def test_stale_agreement_version_rejected_with_412(self, api):
        """PRD §2.9: "A submission must carry `expected_agreement_version`, the
        `version` of the delegation agreement as the client last observed it.
        If the agreement's current `version` differs, the submission is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because the
        client is acting on an agreement state it has not observed."
        PRD §2.9: "This is not a theoretical concern: every successful roster
        submission increments the agreement's `version` by one, so a second
        submission built on a stale read of the agreement fails with this error
        instead of silently superseding a roster the caller never saw."

        Design: Corner/cross_cutting_layers/occ_stale_agreement_version_rejected
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        payer = create_payer_config()
        agreement = create_active_agreement(group["id"], payer["id"])
        v1 = agreement["version"]

        roster_a = submit_roster_file(
            agreement["id"], v1,
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
        )

        # Second submission built on the stale pre-first-submission version.
        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": v1,
                "lines": [
                    roster_add_line(provider["id"], expected_effective_date="2026-09-01")
                ],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

        assert get_agreement(agreement["id"])["version"] == v1 + 1, (
            "exactly one successful submission incremented the version"
        )
        roster_a_after = validate_success(
            api.get_roster_file(roster_a["id"], SPECIALIST), 200
        )
        assert roster_a_after["status"] == "SUBMITTED", (
            "the rejected write did not supersede the incumbent roster"
        )


class TestLogicalClock:
    def test_clock_regression_rejected_but_equal_instant_allowed(self, api):
        """PRD §2.5: "The clock is monotonic non-decreasing; an attempt to set
        it to an instant earlier than its current value is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 422)."

        Design: Corner/validations/clock_regression_rejected
        """
        first = set_clock("2026-08-02T00:00:00Z")
        assert first["current_utc"][:19] == "2026-08-02T00:00:00"

        res = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, OFFICER)
        validate_error(res, ApiErrorId.ERR_CLOCK_REGRESSION)

        # Equal instants are non-decreasing and therefore allowed.
        again = validate_success(
            api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, OFFICER), 200
        )
        assert again["current_utc"][:19] == "2026-08-02T00:00:00"

    def test_single_clock_set_drives_all_three_sweep_families(self, api):
        """PRD §2.5: "Every advance of the logical clock fires a sweep that
        re-evaluates three families of time-based state: CAQH profiles move
        between their current and warning states, enrollment records enter
        their revalidation windows or deactivate past their due dates, and
        delegation agreements expire."

        Design: Corner/cross_cutting_layers/clock_sweep_advances_all_entity_families
        """
        _, provider, _, payer = setup_group_provider_payer(
            payer_overrides={"revalidation_interval_days": 60},
        )
        # CAQH: attested at the startup clock -> due_at 2026-11-29.
        # Record: approved at the startup clock, interval 60 -> due 2026-09-30.
        _, record = create_approved_application(provider["id"], payer["id"])
        assert record["revalidation_due_date"] == "2026-09-30"
        group_id = validate_success(
            api.get_provider(provider["id"], OFFICER), 200
        )["practice_group_id"]
        agreement = create_active_agreement(
            group_id, payer["id"],
            effective_date="2026-01-01", expiry_date="2026-11-30",
        )

        set_clock("2026-12-15T00:00:00Z")

        assert get_caqh_profile(provider["id"])["status"] == "LAPSED"
        record_after = validate_success(
            api.get_enrollment_record(record["id"], SPECIALIST), 200
        )
        assert record_after["status"] == "DEACTIVATED"
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"


class TestImmediateConsistency:
    def test_approve_effects_visible_on_immediately_following_reads(self, api):
        """PRD §2.11: "The system applies every such effect immediately —
        there is no background settlement, no eventual-consistency window in
        which a claim's status and a record's status could disagree about
        whether the record covered the claim."
        PRD §3.3: "Approval stamps `approved_at`, moves the application to
        `APPROVED`, and creates the enrollment record."

        Design: Corner/consistency_model/approve_effects_visible_immediately
        """
        _, provider, _, payer = setup_group_provider_payer()
        claim = create_claim(
            provider["id"], payer["id"], service_date="2026-08-01", amount_cents=1000,
        )
        assert claim["status"] == "HELD"
        app = create_submitted_application(provider["id"], payer["id"])

        approved = validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        assert approved["status"] == "APPROVED", "the mutation response itself carries it"

        record = find_record(provider_id=provider["id"], payer_id=payer["id"])
        assert record["status"] == "ACTIVE"
        claim_after = validate_success(api.get_claim(claim["id"], SPECIALIST), 200)
        assert claim_after["status"] == "RELEASED"
