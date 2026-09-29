"""Identifier resolution, declared defaults and junction reachability."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    CLOCK_STARTUP_INSTANT,
    ERR_ENROLLEE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    _OMIT,
    assert_fields,
    assert_panel_size,
    assign_enrollee,
    create_active_agreement,
    create_active_physician,
    create_agreement,
    create_enrollee,
    enrollee_payload,
    give_exit_notice,
    physician_payload,
    read_agreement,
    read_enrollee,
    read_physician,
    set_clock,
)


class TestUnknownEnrolleeIdentifier:
    def test_a_well_formed_absent_enrollee_id_is_the_entity_specific_404(self, api):
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

        Design: Corner/entities/get_enrollee_with_unknown_id_returns_not_found
        """
        set_clock(api, CLOCK_STARTUP_INSTANT)

        response = api.get_enrollee(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS)
        validate_error(response, ERR_ENROLLEE_NOT_FOUND, 404)

    def test_the_miss_is_reported_through_the_error_envelope(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/get_enrollee_with_unknown_id_returns_not_found
        """
        set_clock(api, CLOCK_STARTUP_INSTANT)

        response = api.get_enrollee(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS)
        error_data = validate_error(response, ERR_ENROLLEE_NOT_FOUND, 404)

        assert response.json()["response_type"] == "error"
        assert error_data["error_id"] == "ERR_ENROLLEE_NOT_FOUND"
        assert error_data["message"].strip()


def _physician_creation_without_an_npi(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_active_agreement(
        api, payer_name="Corner Required Health", quality_withhold_bps=0
    )
    response = api.create_physician(
        agreement["id"],
        physician_payload(
            npi=_OMIT, full_name="No Npi Provided", specialty="PRIMARY_CARE"
        ),
        NETWORK_MANAGER_HEADERS,
    )
    return agreement, response


class TestPhysicianRequiredFields:
    def test_omitting_the_npi_is_rejected_as_a_malformed_request(self, api):
        """PRD §2.10: "The body parses; every required input field is present; every
        field has its declared type; every enum-typed field carries a declared
        member; every numeric field satisfies its declared range; `coverage_month`
        is four digits, a hyphen, then a month from `01` through `12`;
        `measurement_period` is exactly four digits; `limit` is between 1 and 100
        inclusive and `offset` is not negative."

        Design: Corner/entities/create_physician_missing_npi_returns_invalid_request
        """
        _agreement, response = _physician_creation_without_an_npi(api)
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_the_rejected_physician_never_reaches_the_roster(self, api):
        """PRD §3.2: "A physician record read individually exposes both state
        dimensions, `panel_size`, `quality_composite_bps` and
        `continuity_of_care_until`; the agreement's physician roster may be listed
        with optional `credential_status` and `panel_status` filters."

        Design: Corner/entities/create_physician_missing_npi_returns_invalid_request
        """
        agreement, response = _physician_creation_without_an_npi(api)
        validate_error(response, ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(
            api.list_agreement_physicians(
                agreement["id"], NETWORK_MANAGER_HEADERS, {"limit": 10, "offset": 0}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


def _agreement_created_without_a_continuity_window(api):
    set_clock(api, "2026-03-01T00:00:00Z")
    # PRD §3.2 permits APPLICANT -> CREDENTIALED only while the parent
    # agreement's status is ACTIVE, so the agreement is activated here.
    return create_active_agreement(
        api,
        payer_name="Corner Default Health",
        quality_withhold_bps=0,
        continuity_of_care_days=_OMIT,
    )


class TestContinuityOfCareDefault:
    def test_omitting_the_field_persists_the_declared_default_of_ninety(self, api):
        """PRD §3.1: "Finally, `continuity_of_care_days` sets the protected window
        that follows a physician's exit notice; when the field is omitted from the
        payload it defaults to 90 days."

        Design: Corner/entities/create_agreement_omitting_continuity_days_applies_default_90
        """
        agreement = _agreement_created_without_a_continuity_window(api)

        assert agreement["continuity_of_care_days"] == 90
        assert read_agreement(api, agreement["id"])["continuity_of_care_days"] == 90

    def test_the_exit_notice_consumes_the_defaulted_window(self, api):
        """PRD §3.2: "It is permitted when `credential_status` is `ACTIVE`, and it
        does four things at once: `credential_status` becomes `NOTICE_GIVEN`;
        `exit_notice_at` is stamped with the current logical clock instant;
        `continuity_of_care_until` is derived as `exit_notice_at` advanced by the
        agreement's `continuity_of_care_days` — ninety days by default, so a notice
        given on the first of March protects that panel until the twenty-ninth of
        May; and `panel_status` is set to `CLOSED_TO_NEW` if and only if it was
        `OPEN`, leaving `TRANSFER_PENDING` and `TRANSFERRED` untouched."

        Design: Corner/entities/create_agreement_omitting_continuity_days_applies_default_90
        """
        agreement = _agreement_created_without_a_continuity_window(api)
        activated = create_active_physician(
            api, agreement["id"], full_name="Dara Okonkwo", npi="3100000001"
        )
        assert activated["panel_status"] == "OPEN"

        noticed = give_exit_notice(api, activated["id"])
        assert_fields(
            noticed,
            {
                "credential_status": "NOTICE_GIVEN",
                "exit_notice_at": "2026-03-01T00:00:00Z",
                "panel_status": "CLOSED_TO_NEW",
            },
        )
        assert noticed["continuity_of_care_until"] is not None


def _enrollee_creation_with_a_fourth_age_band(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_active_agreement(
        api, payer_name="Corner Enum Health", quality_withhold_bps=0
    )
    response = api.create_enrollee(
        agreement["id"],
        enrollee_payload(
            external_member_id="E9-0001",
            age_band="GERIATRIC",
            benefit_tier="HMO",
            risk_score_bps=10000,
        ),
        IPA_ADMIN_HEADERS,
    )
    return agreement, response


class TestEnrolleeAgeBandDomain:
    def test_an_undeclared_age_band_is_rejected_as_a_malformed_request(self, api):
        """PRD §3.3: "The payload carries `external_member_id`, the payer-side
        member identifier that later enrollment-file rows are matched against and
        which must be unique among the agreement's enrollees; `age_band`, one of
        `PEDIATRIC`, `ADULT` or `SENIOR`; `benefit_tier`, one of `HMO`, `POS` or
        `HMO_PLUS`; `risk_score_bps`, the risk-adjustment factor in basis points
        between 1 and 50000 inclusive, where 10000 means a factor of exactly 1.00;
        `coverage_start_date`, the first instant of payer coverage, before which no
        assignment may start; and optionally `coverage_end_date`, the last instant
        of coverage, which defaults to null for an open-ended member."

        Design: Corner/entities/create_enrollee_with_unknown_age_band_returns_invalid_request
        """
        _agreement, response = _enrollee_creation_with_a_fourth_age_band(api)
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_the_rejected_member_is_not_registered_under_the_agreement(self, api):
        """PRD §3.3: "Enrollees may be listed with optional `agreement_id`,
        `assigned_physician_id` and `age_band` filters, and an individual read
        exposes the gross, withhold and net components together with
        `cumulative_paid_claims_cents`."

        Design: Corner/entities/create_enrollee_with_unknown_age_band_returns_invalid_request
        """
        agreement, response = _enrollee_creation_with_a_fourth_age_band(api)
        validate_error(response, ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(
            api.list_enrollees(
                IPA_ADMIN_HEADERS,
                {"agreement_id": agreement["id"], "limit": 10, "offset": 0},
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


def _one_junction_row_between_one_member_and_one_physician(api):
    set_clock(api, CLOCK_STARTUP_INSTANT)
    agreement = create_active_agreement(
        api, payer_name="Corner Junction Health", quality_withhold_bps=0
    )
    physician = create_active_physician(
        api, agreement["id"], npi="3400000001", full_name="Junia Castellanos"
    )
    enrollee = create_enrollee(api, agreement["id"], external_member_id="E12-0001")
    assignment = assign_enrollee(api, enrollee["id"], physician["id"])
    return agreement, physician, enrollee, assignment


def _assignments_filtered_by(api, **filters):
    query = {"limit": 10, "offset": 0}
    query.update(filters)
    return validate_paginated(api.list_assignments(NETWORK_MANAGER_HEADERS, query))


class TestMemberAssignmentJunction:
    def test_the_same_row_is_reachable_from_either_parent(self, api):
        """PRD §3.4: "Assignments may be listed with optional `enrollee_id`,
        `physician_id`, `pending_to_physician_id` and `status` filters, and an
        individual read exposes the transfer target and the continuity window."

        Design: Corner/entities/member_assignment_junction_resolves_from_both_parents
        """
        _agreement, physician, enrollee, assignment = (
            _one_junction_row_between_one_member_and_one_physician(api)
        )

        by_enrollee, enrollee_meta = _assignments_filtered_by(
            api, enrollee_id=enrollee["id"]
        )
        by_physician, physician_meta = _assignments_filtered_by(
            api, physician_id=physician["id"]
        )

        assert enrollee_meta["total_count"] == 1
        assert physician_meta["total_count"] == 1
        assert by_enrollee[0]["id"] == assignment["id"]
        assert by_physician[0]["id"] == assignment["id"]

    def test_the_junction_row_records_both_parents_and_its_source(self, api):
        """PRD §3.4: "A new assignment lands in `status` `ACTIVE` with
        `pending_to_physician_id` null, `term_date` null, `continuity_of_care_until`
        null and `superseded_by_assignment_id` null."

        Design: Corner/entities/member_assignment_junction_resolves_from_both_parents
        """
        _agreement, physician, enrollee, assignment = (
            _one_junction_row_between_one_member_and_one_physician(api)
        )

        assert_fields(
            assignment,
            {
                "enrollee_id": enrollee["id"],
                "physician_id": physician["id"],
                "status": "ACTIVE",
                "assignment_source": "MANUAL",
                "pending_to_physician_id": None,
                "term_date": None,
                "superseded_by_assignment_id": None,
            },
        )

    def test_the_denormalised_back_pointer_agrees_with_the_junction_row(self, api):
        """PRD §2.9: "`Enrollee.assigned_physician_id` is the `physician_id` of that
        enrollee's single `ACTIVE` assignment, and is null when the enrollee has
        none."

        Design: Corner/entities/member_assignment_junction_resolves_from_both_parents
        """
        _agreement, physician, enrollee, _assignment = (
            _one_junction_row_between_one_member_and_one_physician(api)
        )

        assert read_enrollee(api, enrollee["id"])["assigned_physician_id"] == physician["id"]

    def test_the_physician_panel_counts_the_single_active_row(self, api):
        """PRD §2.9: "`PhysicianMember.panel_size` is the count of that physician's
        assignments whose `status` is `ACTIVE`."

        Design: Corner/entities/member_assignment_junction_resolves_from_both_parents
        """
        _agreement, physician, _enrollee, _assignment = (
            _one_junction_row_between_one_member_and_one_physician(api)
        )

        assert_panel_size(read_physician(api, physician["id"]), 1)

    def test_the_agreement_counts_the_single_active_row(self, api):
        """PRD §2.9: "`DelegationAgreement.total_assigned_members` is the count of
        `ACTIVE` assignments across every physician of the agreement."

        Design: Corner/entities/member_assignment_junction_resolves_from_both_parents
        """
        agreement, _physician, _enrollee, _assignment = (
            _one_junction_row_between_one_member_and_one_physician(api)
        )

        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1
