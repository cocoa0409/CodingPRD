"""Declared, computed and system fields on the response bodies of the entities."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_STARTUP_INSTANT,
    ERR_AGREEMENT_NOT_FOUND,
    IPA_ADMIN_HEADERS,
    activate_agreement,
    agreement_payload,
    assert_fields,
    assert_pagination_meta,
    assert_pmpm_components,
    assert_row_resource,
    assign_enrollee,
    create_active_agreement,
    create_active_physician,
    create_agreement,
    create_enrollee,
    create_enrollment_file,
    enrollee_payload,
    enrollment_row_payload,
    expected_pmpm_components,
    make_payer_representative_headers,
    read_agreement,
    read_enrollee,
    read_file,
    set_clock,
)


def _agreement_creation(api):
    """Submit one fully specified agreement payload and keep both sides of it."""
    set_clock(api, CLOCK_STARTUP_INSTANT)
    payload = agreement_payload(
        payer_name="Corner Creation Health",
        delegation_scope="CLAIMS_AND_UM",
        base_pmpm_cents=30000,
        quality_withhold_bps=700,
        continuity_of_care_days=90,
    )
    return payload, api.create_agreement(payload, IPA_ADMIN_HEADERS)


class TestDelegationAgreementCreationFields:
    def test_creation_starts_in_draft_with_every_ledger_counter_at_zero(self, api):
        """PRD §3.1: "A newly created agreement begins in `status` `DRAFT` with
        `capitation_posture` `CURRENT` and every derived counter at zero:
        `accrued_capitation_cents`, `withheld_balance_cents`,
        `forfeited_withhold_cents` and `total_assigned_members` all start at 0."

        Design: Corner/entities/create_delegation_agreement_returns_all_declared_fields
        """
        _payload, response = _agreement_creation(api)
        created = validate_success(response, 201)

        assert_fields(
            created,
            {
                "status": "DRAFT",
                "capitation_posture": "CURRENT",
                "accrued_capitation_cents": 0,
                "withheld_balance_cents": 0,
                "forfeited_withhold_cents": 0,
                "total_assigned_members": 0,
            },
        )

    def test_creation_echoes_every_declared_contract_parameter(self, api):
        """PRD §3.1: "The `delegation_scope` records how much the payer has handed
        over and takes one of `CLAIMS_ONLY`, `CLAIMS_AND_UM` or `FULL_RISK`."

        Design: Corner/entities/create_delegation_agreement_returns_all_declared_fields
        """
        payload, response = _agreement_creation(api)
        created = validate_success(response, 201)

        assert_fields(
            created,
            {
                "payer_name": "Corner Creation Health",
                "payer_tax_id": payload["payer_tax_id"],
                "delegation_scope": "CLAIMS_AND_UM",
                "base_pmpm_cents": 30000,
                "reconciliation_method": payload["reconciliation_method"],
                "ibnr_method": payload["ibnr_method"],
                "ibnr_completion_factor_bps": payload["ibnr_completion_factor_bps"],
                "target_claims_pmpm_cents": payload["target_claims_pmpm_cents"],
                "professional_pool_share_bps": payload["professional_pool_share_bps"],
                "institutional_pool_share_bps": payload["institutional_pool_share_bps"],
                "quality_withhold_bps": 700,
                "stop_loss_attachment_cents": payload["stop_loss_attachment_cents"],
                "reinsurance_recovery_bps": payload["reinsurance_recovery_bps"],
                "max_panel_size": payload["max_panel_size"],
                "continuity_of_care_days": 90,
            },
        )

    def test_creation_carries_the_four_audit_fields_with_version_one(self, api):
        """PRD §2.4: "Eleven of the twelve resource types — `DelegationAgreement`,
        `PhysicianMember`, `Enrollee`, `MemberAssignment`, `EnrollmentFile`,
        `CapitationRemittance`, `RiskPool`, `DownstreamClaim`, `StopLossRecovery`,
        `QualityScorecard` and `PoolDistribution` — additionally carry
        `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increases by exactly
        1 on every mutation of that resource."

        Design: Corner/entities/create_delegation_agreement_returns_all_declared_fields
        """
        _payload, response = _agreement_creation(api)
        created = validate_success(response, 201)

        assert is_valid_uuid(created["id"]), created["id"]
        assert is_iso8601_timestamp(created["created_at"]), created["created_at"]
        assert is_iso8601_timestamp(created["updated_at"]), created["updated_at"]
        assert created["version"] == 1

    def test_creation_is_wrapped_in_the_single_object_envelope(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/create_delegation_agreement_returns_all_declared_fields
        """
        _payload, response = _agreement_creation(api)
        validate_success(response, 201)
        body = response.json()

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def _activated_agreement(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_agreement(
        api,
        payer_name="Corner Retrieval Health",
        delegation_scope="FULL_RISK",
        base_pmpm_cents=20000,
        quality_withhold_bps=0,
    )
    activated = activate_agreement(api, agreement["id"])
    return agreement, activated


class TestDelegationAgreementRetrieval:
    def test_the_read_reports_the_post_activation_row(self, api):
        """PRD §3.1: "Reading an agreement returns its derived counters and its
        `capitation_posture` alongside the contract parameters, and agreements may
        be listed with an optional `status` filter."

        Design: Corner/entities/get_delegation_agreement_returns_stored_data
        """
        agreement, _activated = _activated_agreement(api)

        stored = read_agreement(
            api, agreement["id"], make_payer_representative_headers(agreement["id"])
        )
        assert_fields(
            stored,
            {
                "id": agreement["id"],
                "status": "ACTIVE",
                "capitation_posture": "CURRENT",
                "base_pmpm_cents": 20000,
                "accrued_capitation_cents": 0,
                "total_assigned_members": 0,
            },
        )

    def test_a_read_does_not_advance_the_version(self, api):
        """PRD §2.4: "Eleven of the twelve resource types — `DelegationAgreement`,
        `PhysicianMember`, `Enrollee`, `MemberAssignment`, `EnrollmentFile`,
        `CapitationRemittance`, `RiskPool`, `DownstreamClaim`, `StopLossRecovery`,
        `QualityScorecard` and `PoolDistribution` — additionally carry
        `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increases by exactly
        1 on every mutation of that resource."

        Design: Corner/entities/get_delegation_agreement_returns_stored_data
        """
        agreement, activated = _activated_agreement(api)

        first_read = read_agreement(
            api, agreement["id"], make_payer_representative_headers(agreement["id"])
        )
        second_read = read_agreement(api, agreement["id"])

        assert first_read["version"] == activated["version"]
        assert second_read["version"] == activated["version"]


def _three_members_under_one_agreement_and_one_under_another(api):
    """Three enrollees on the agreement under test, one namesake on another."""
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Listing Health", base_pmpm_cents=30000
    )
    create_enrollee(api, agreement["id"], external_member_id="E3-0001")
    set_clock(api, "2026-08-02T00:00:00Z")
    create_enrollee(
        api, agreement["id"], external_member_id="E3-0002", age_band="SENIOR"
    )
    set_clock(api, "2026-08-03T00:00:00Z")
    create_enrollee(
        api, agreement["id"], external_member_id="E3-0003", age_band="PEDIATRIC"
    )

    set_clock(api, "2026-08-04T00:00:00Z")
    other = create_active_agreement(
        api, payer_name="Corner Listing Other Health", base_pmpm_cents=30000
    )
    create_enrollee(api, other["id"], external_member_id="E3-0001")
    return agreement, other


def _enrollee_page(api, agreement_id, limit, offset):
    return validate_paginated(
        api.list_enrollees(
            IPA_ADMIN_HEADERS,
            {"agreement_id": agreement_id, "limit": limit, "offset": offset},
        )
    )


class TestEnrolleeListingWindow:
    def test_the_filter_and_the_window_are_applied_together(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` is the number of records matching the filter before
        pagination is applied and `has_more` indicates whether records remain
        beyond the current window."

        Design: Corner/entities/list_enrollees_paginates_and_filters_by_agreement
        """
        agreement, _other = _three_members_under_one_agreement_and_one_under_another(api)

        first_rows, first_meta = _enrollee_page(api, agreement["id"], 2, 0)
        assert len(first_rows) == 2
        assert_pagination_meta(first_meta, 2, 0, 3, True)

        second_rows, second_meta = _enrollee_page(api, agreement["id"], 2, 2)
        assert len(second_rows) == 1
        assert_pagination_meta(second_meta, 2, 2, 3, False)

    def test_the_window_walks_the_rows_in_created_at_order(self, api):
        """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
        ordered by the resource's `created_at` timestamp, ascending."

        Design: Corner/entities/list_enrollees_paginates_and_filters_by_agreement
        """
        agreement, _other = _three_members_under_one_agreement_and_one_under_another(api)

        first_rows, _first_meta = _enrollee_page(api, agreement["id"], 2, 0)
        second_rows, _second_meta = _enrollee_page(api, agreement["id"], 2, 2)

        assert [row["external_member_id"] for row in first_rows] == [
            "E3-0001",
            "E3-0002",
        ]
        assert [row["external_member_id"] for row in second_rows] == ["E3-0003"]

    def test_the_other_agreement_s_namesake_member_is_never_in_the_window(self, api):
        """PRD §3.3: "Enrollees may be listed with optional `agreement_id`,
        `assigned_physician_id` and `age_band` filters, and an individual read
        exposes the gross, withhold and net components together with
        `cumulative_paid_claims_cents`."

        Design: Corner/entities/list_enrollees_paginates_and_filters_by_agreement
        """
        agreement, other = _three_members_under_one_agreement_and_one_under_another(api)

        first_rows, _first_meta = _enrollee_page(api, agreement["id"], 2, 0)
        second_rows, _second_meta = _enrollee_page(api, agreement["id"], 2, 2)
        assert all(
            row["agreement_id"] == agreement["id"] for row in first_rows + second_rows
        )

        other_rows, other_meta = _enrollee_page(api, other["id"], 10, 0)
        assert other_meta["total_count"] == 1
        assert other_rows[0]["external_member_id"] == "E3-0001"


def _enrollee_creation_carrying_a_client_supplied_net_pmpm(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_active_agreement(
        api,
        payer_name="Corner Computed Health",
        base_pmpm_cents=30000,
        quality_withhold_bps=700,
    )
    response = api.create_enrollee(
        agreement["id"],
        enrollee_payload(
            external_member_id="E7-0001",
            age_band="ADULT",
            benefit_tier="HMO",
            risk_score_bps=12500,
            net_pmpm_cents=1,
        ),
        IPA_ADMIN_HEADERS,
    )
    return agreement, response


class TestEnrolleeComputedFields:
    def test_the_three_pmpm_components_are_derived_not_taken_from_the_body(self, api):
        """PRD §3.3: "An `ADULT` member on `HMO` coverage with a `risk_score_bps` of
        12500 reaches a raw amount of 37500 cents, which sits inside both bounds,
        so `gross_pmpm_cents` is 37500, `withhold_cents` is 2625, and
        `net_pmpm_cents` is 34875."

        Design: Corner/entities/enrollee_computed_pmpm_ignores_extra_field_in_payload
        """
        _agreement, response = _enrollee_creation_carrying_a_client_supplied_net_pmpm(api)
        created = validate_success(response, 201)

        gross, withhold, net = expected_pmpm_components(
            base_pmpm_cents=30000,
            age_band="ADULT",
            benefit_tier="HMO",
            risk_score_bps=12500,
            quality_withhold_bps=700,
        )
        assert (gross, withhold, net) == (37500, 2625, 34875)
        assert_pmpm_components(created, gross, withhold, net)
        assert created["net_pmpm_cents"] != 1

        stored = read_enrollee(api, created["id"])
        assert_pmpm_components(stored, 37500, 2625, 34875)

    def test_a_fresh_member_holds_no_panel_placement_and_no_paid_claims(self, api):
        """PRD §3.3: "A freshly registered enrollee has `assigned_physician_id` null
        and `cumulative_paid_claims_cents` 0."

        Design: Corner/entities/enrollee_computed_pmpm_ignores_extra_field_in_payload
        """
        _agreement, response = _enrollee_creation_carrying_a_client_supplied_net_pmpm(api)
        created = validate_success(response, 201)

        assert_fields(
            created,
            {"assigned_physician_id": None, "cumulative_paid_claims_cents": 0},
        )


_CLIENT_SUPPLIED_AGREEMENT_ID = "00000000-0000-4000-8000-0000000000e8"


def _agreement_created_from_a_body_carrying_system_fields(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    response = api.create_agreement(
        agreement_payload(
            payer_name="Corner System Health",
            quality_withhold_bps=0,
            id=_CLIENT_SUPPLIED_AGREEMENT_ID,
            created_at="1999-01-01T00:00:00Z",
            version=77,
        ),
        IPA_ADMIN_HEADERS,
    )
    return validate_success(response, 201)


class TestAgreementSystemFields:
    def test_the_identifier_is_server_minted_and_the_version_starts_at_one(self, api):
        """PRD §2.4: "Every resource in the system carries a server-minted `id`,
        formatted as a UUID with no type prefix, and a `created_at` timestamp
        rendered as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/entities/agreement_system_fields_generated_not_client_supplied_input_ignored
        """
        created = _agreement_created_from_a_body_carrying_system_fields(api)

        assert is_valid_uuid(created["id"]), created["id"]
        assert created["id"] != _CLIENT_SUPPLIED_AGREEMENT_ID
        assert created["version"] == 1

    def test_created_at_is_stamped_from_the_logical_clock_not_from_the_body(self, api):
        """PRD §2.5: "Before the clock has been set, it reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/agreement_system_fields_generated_not_client_supplied_input_ignored
        """
        created = _agreement_created_from_a_body_carrying_system_fields(api)

        assert is_iso8601_timestamp(created["created_at"]), created["created_at"]
        assert created["created_at"] != "1999-01-01T00:00:00Z"
        assert created["created_at"].startswith("2026-08-01T00:00:00")

    def test_the_client_supplied_identifier_resolves_to_nothing(self, api):
        """PRD §2.7: "The first identifier in the path that fails to resolve
        determines the response, and the error is the one specific to that resource
        type: `ERR_AGREEMENT_NOT_FOUND` for an unresolvable `agreementId`,
        `ERR_PHYSICIAN_NOT_FOUND` for `physicianId`, `ERR_ENROLLEE_NOT_FOUND` for
        `enrolleeId`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignmentId`,
        `ERR_ENROLLMENT_FILE_NOT_FOUND` for `fileId`, `ERR_REMITTANCE_NOT_FOUND`
        for `remittanceId`, `ERR_RISK_POOL_NOT_FOUND` for `poolId`,
        `ERR_CLAIM_NOT_FOUND` for `claimId`, `ERR_RECOVERY_NOT_FOUND` for
        `recoveryId`, `ERR_SCORECARD_NOT_FOUND` for `scorecardId`, and
        `ERR_DISTRIBUTION_NOT_FOUND` for `distributionId`."

        Design: Corner/entities/agreement_system_fields_generated_not_client_supplied_input_ignored
        """
        _created = _agreement_created_from_a_body_carrying_system_fields(api)

        response = api.get_agreement(_CLIENT_SUPPLIED_AGREEMENT_ID, IPA_ADMIN_HEADERS)
        validate_error(response, ERR_AGREEMENT_NOT_FOUND, 404)


def _file_with_one_appended_row(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_active_agreement(
        api, payer_name="Corner Immutable Health", quality_withhold_bps=0
    )
    physician = create_active_physician(
        api, agreement["id"], npi="3200000001", full_name="Imani Rocha"
    )
    enrollee = create_enrollee(api, agreement["id"], external_member_id="E10-0001")
    assign_enrollee(api, enrollee["id"], physician["id"])
    enrollment_file = create_enrollment_file(
        api, agreement["id"], coverage_month="2026-07"
    )

    response = api.create_enrollment_file_row(
        enrollment_file["id"],
        enrollment_row_payload(
            "E10-0001",
            "3200000001",
            row_action="ADD",
            claimed_capitation_cents=20000,
            effective_date="2026-07-01T00:00:00Z",
        ),
        IPA_ADMIN_HEADERS,
    )
    return enrollment_file, response


def _listed_rows(api, file_id):
    return validate_paginated(
        api.list_enrollment_file_rows(
            file_id, IPA_ADMIN_HEADERS, {"limit": 10, "offset": 0}
        )
    )


class TestEnrollmentFileRowFieldSet:
    def test_a_row_exposes_neither_version_nor_updated_at(self, api):
        """PRD §2.4: "A row carries only `id` and `created_at`; it has neither
        `updated_at` nor `version`, and neither field appears in its response body."

        Design: Corner/entities/enrollment_file_row_is_immutable_with_no_version_field
        """
        enrollment_file, response = _file_with_one_appended_row(api)
        created = validate_success(response, 201)
        assert_row_resource(created)

        rows, _meta = _listed_rows(api, enrollment_file["id"])
        assert len(rows) == 1
        assert_row_resource(rows[0])

    def test_a_row_is_appended_unmatched_until_the_file_is_parsed(self, api):
        """PRD §3.5: "A new row's `match_status` reads `UNMATCHED` until the file is
        parsed."

        Design: Corner/entities/enrollment_file_row_is_immutable_with_no_version_field
        """
        _enrollment_file, response = _file_with_one_appended_row(api)
        created = validate_success(response, 201)

        assert created["match_status"] == "UNMATCHED"

    def test_the_row_echoes_the_payer_asserted_values(self, api):
        """PRD §3.5: "Each row carries `external_member_id` exactly as the payer
        transmitted it, `physician_npi` as the payer-asserted assigned physician, a
        `row_action` from `ADD`, `TERM`, `CHANGE`, `RETRO_ADD` or `RETRO_TERM`, the
        `claimed_capitation_cents` the payer asserts for that row in whole cents
        which must be zero or more, and an `effective_date` giving the
        payer-asserted instant for the row action."

        Design: Corner/entities/enrollment_file_row_is_immutable_with_no_version_field
        """
        enrollment_file, response = _file_with_one_appended_row(api)
        validate_success(response, 201)

        rows, meta = _listed_rows(api, enrollment_file["id"])
        assert meta["total_count"] == 1
        assert_fields(
            rows[0],
            {
                "external_member_id": "E10-0001",
                "physician_npi": "3200000001",
                "row_action": "ADD",
                "claimed_capitation_cents": 20000,
                "effective_date": "2026-07-01T00:00:00Z",
            },
        )

    def test_the_counter_and_the_version_live_on_the_parent_file(self, api):
        """PRD §3.5: "Appending a row increments the file's `row_count` and advances
        the file's `version` by 1; the row itself, uniquely among this system's
        resources, carries only `id` and `created_at` and has no `updated_at` and
        no `version`."

        Design: Corner/entities/enrollment_file_row_is_immutable_with_no_version_field
        """
        enrollment_file, response = _file_with_one_appended_row(api)
        validate_success(response, 201)

        stored = read_file(api, enrollment_file["id"])
        assert stored["row_count"] == 1
        assert stored["version"] == enrollment_file["version"] + 1
        assert is_iso8601_timestamp(stored["updated_at"]), stored["updated_at"]
