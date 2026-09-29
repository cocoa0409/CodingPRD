"""Reachability of the resource-specific 404s and of the role, ownership and duty rules."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    build_user_headers,
    validate_error,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    CLAIMS_EXAMINER_USER_ID,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DISTRIBUTION_NOT_FOUND,
    ERR_ENROLLEE_NOT_FOUND,
    ERR_ENROLLMENT_FILE_NOT_FOUND,
    ERR_PHYSICIAN_NOT_FOUND,
    ERR_RECOVERY_NOT_FOUND,
    ERR_REMITTANCE_NOT_FOUND,
    ERR_RISK_POOL_NOT_FOUND,
    ERR_SCORECARD_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PHYSICIAN_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    IPA_ADMIN_HEADERS,
    IPA_ADMIN_USER_ID,
    NETWORK_MANAGER_HEADERS,
    REINSURANCE_UNDERWRITER_HEADERS,
    assert_fields,
    assign_enrollee,
    assignment_payload,
    build_paid_claim,
    build_posted_file,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_enrollment_file,
    create_physician,
    create_pool,
    create_recovery,
    credential_physician,
    enrollee_version,
    make_physician_user_headers,
    make_reinsurance_underwriter_headers,
    physician_version,
    read_agreement,
    read_physician,
    read_pool,
    read_recovery,
    risk_pool_payload,
    scorecard_payload,
    set_clock,
    state_payload,
    submit_recovery,
    terminate_assignment,
)

_PAGE = {"limit": 10, "offset": 0}


class TestEveryPathIdentifierNotFoundIsReachable:
    @pytest.mark.parametrize(
        "getter, expected_error",
        [
            pytest.param(
                lambda api: api.get_agreement(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_AGREEMENT_NOT_FOUND,
                id="agreementId",
            ),
            pytest.param(
                lambda api: api.get_physician(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_PHYSICIAN_NOT_FOUND,
                id="physicianId",
            ),
            pytest.param(
                lambda api: api.get_enrollee(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_ENROLLEE_NOT_FOUND,
                id="enrolleeId",
            ),
            pytest.param(
                lambda api: api.get_assignment(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_ASSIGNMENT_NOT_FOUND,
                id="assignmentId",
            ),
            pytest.param(
                lambda api: api.get_enrollment_file(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS
                ),
                ERR_ENROLLMENT_FILE_NOT_FOUND,
                id="fileId",
            ),
            pytest.param(
                lambda api: api.get_remittance(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_REMITTANCE_NOT_FOUND,
                id="remittanceId",
            ),
            pytest.param(
                lambda api: api.get_risk_pool(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_RISK_POOL_NOT_FOUND,
                id="poolId",
            ),
            pytest.param(
                lambda api: api.get_claim(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_CLAIM_NOT_FOUND,
                id="claimId",
            ),
            pytest.param(
                lambda api: api.get_recovery(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_RECOVERY_NOT_FOUND,
                id="recoveryId",
            ),
            pytest.param(
                lambda api: api.get_scorecard(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_SCORECARD_NOT_FOUND,
                id="scorecardId",
            ),
            pytest.param(
                lambda api: api.get_distribution(NON_EXISTENT_UUID, IPA_ADMIN_HEADERS),
                ERR_DISTRIBUTION_NOT_FOUND,
                id="distributionId",
            ),
        ],
    )
    def test_each_resource_specific_path_not_found_is_reachable(
        self, api, getter, expected_error
    ):
        """PRD §2.7: "Each of these carries HTTP 404."

        Design: Corner/errors/every_path_id_not_found_code_is_reachable
        """
        validate_error(getter(api), expected_error, 404)

    @pytest.mark.parametrize(
        "getter, expected_error",
        [
            pytest.param(
                lambda api: api.list_agreement_physicians(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_AGREEMENT_NOT_FOUND,
                id="agreement-physicians",
            ),
            pytest.param(
                lambda api: api.list_agreement_enrollment_files(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_AGREEMENT_NOT_FOUND,
                id="agreement-enrollment-files",
            ),
            pytest.param(
                lambda api: api.list_agreement_risk_pools(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_AGREEMENT_NOT_FOUND,
                id="agreement-risk-pools",
            ),
            pytest.param(
                lambda api: api.list_enrollment_file_rows(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_ENROLLMENT_FILE_NOT_FOUND,
                id="file-rows",
            ),
            pytest.param(
                lambda api: api.list_file_remittances(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_ENROLLMENT_FILE_NOT_FOUND,
                id="file-remittances",
            ),
            pytest.param(
                lambda api: api.list_physician_scorecards(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS, dict(_PAGE)
                ),
                ERR_PHYSICIAN_NOT_FOUND,
                id="physician-scorecards",
            ),
            pytest.param(
                lambda api: api.get_settlement_preview(
                    NON_EXISTENT_UUID, IPA_ADMIN_HEADERS
                ),
                ERR_RISK_POOL_NOT_FOUND,
                id="pool-settlement-preview",
            ),
        ],
    )
    def test_a_nested_collection_reports_its_own_parent_not_found(
        self, api, getter, expected_error
    ):
        """PRD §2.10: "Every identifier in the path resolves, left to right as described in §2.7."

        Design: Corner/errors/every_path_id_not_found_code_is_reachable
        """
        validate_error(getter(api), expected_error, 404)


class TestBodyForeignKeysResolveInInputOrder:
    def test_the_first_declared_body_reference_wins_when_both_are_unresolvable(
        self, api
    ):
        """PRD §2.7: "Identifiers supplied in a request body are resolved after every path identifier has resolved, and among themselves in the order the endpoint declares its input fields; an unresolvable body identifier raises the same resource-specific 404."

        Design: Corner/errors/body_foreign_keys_are_resolved_in_input_order_not_found
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        create_active_agreement(api, max_panel_size=5)

        response = api.create_assignment(
            assignment_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, 1),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_ENROLLEE_NOT_FOUND, 404)

    def test_the_second_declared_body_reference_is_reported_once_the_first_resolves(
        self, api
    ):
        """PRD §2.10: "Every foreign reference supplied in the body resolves, in the order the endpoint declares its input fields, raising `ERR_ENROLLEE_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND` or `ERR_RISK_POOL_NOT_FOUND` (404)."

        Design: Corner/errors/body_foreign_keys_are_resolved_in_input_order_not_found
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        enrollee = create_enrollee(api, agreement["id"])

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                NON_EXISTENT_UUID,
                enrollee_version(api, enrollee["id"]),
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_PHYSICIAN_NOT_FOUND, 404)

    def test_an_unresolvable_body_reference_outranks_the_version_guard(self, api):
        """PRD §2.10: "The supplied `expected_enrollee_version` or `expected_physician_version` equals the parent's current `version`, per §2.8."

        Design: Corner/errors/body_foreign_keys_are_resolved_in_input_order_not_found
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        physician = create_active_physician(api, agreement["id"])

        stale = physician_version(api, physician["id"]) - 1
        validate_error(
            api.create_scorecard(
                scorecard_payload(physician["id"], stale), IPA_ADMIN_HEADERS
            ),
            ERR_STALE_PHYSICIAN_VERSION,
            412,
        )
        validate_error(
            api.create_scorecard(
                scorecard_payload(NON_EXISTENT_UUID, stale), IPA_ADMIN_HEADERS
            ),
            ERR_PHYSICIAN_NOT_FOUND,
            404,
        )


class TestRoleExclusiveOperations:
    def test_the_ipa_admin_opens_the_agreement_and_its_risk_pool(self, api):
        """PRD §3.7: "An `IpaAdmin` opens one under an agreement by supplying `pool_type`, either `PROFESSIONAL` or `INSTITUTIONAL`, together with `pool_year_start` as the inclusive first instant of the incurral period and `pool_year_end` as its inclusive last instant."

        Design: Corner/rbac/ipa_admin_and_network_manager_perform_their_own_exclusive_operations
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)

        pool = validate_success(
            api.create_risk_pool(
                agreement["id"],
                risk_pool_payload(
                    pool_type="INSTITUTIONAL",
                    pool_year_start="2026-01-01T00:00:00Z",
                    pool_year_end="2026-12-31T23:59:59Z",
                ),
                IPA_ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(
            pool,
            {
                "agreement_id": agreement["id"],
                "pool_type": "INSTITUTIONAL",
                "status": "ACCUMULATING",
                "settlement_due_date": "2027-09-27T23:59:59Z",
            },
        )

    def test_the_network_manager_walks_the_credential_dimension(self, api):
        """PRD §3.2: "On the contracting dimension, a `NetworkManager` advances `APPLICANT → CREDENTIALED` — permitted when `credential_status` is `APPLICANT` and the parent agreement's `status` is `ACTIVE` — and then `CREDENTIALED → ACTIVE`, permitted when `credential_status` is `CREDENTIALED` and the agreement is again `ACTIVE`."

        Design: Corner/rbac/ipa_admin_and_network_manager_perform_their_own_exclusive_operations
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        physician = create_physician(api, agreement["id"])
        assert physician["credential_status"] == "APPLICANT"

        credentialed = credential_physician(api, physician["id"])
        assert_fields(
            credentialed,
            {"credential_status": "CREDENTIALED", "version": physician["version"] + 1},
        )

        activated = validate_success(
            api.set_physician_state(
                physician["id"], state_payload("ACTIVE"), NETWORK_MANAGER_HEADERS
            ),
            200,
        )
        assert_fields(
            activated,
            {"credential_status": "ACTIVE", "version": credentialed["version"] + 1},
        )

    def test_the_network_manager_terminates_an_assignment_it_placed(self, api):
        """PRD §3.4: "Terminating an assignment outright is a `NetworkManager` action, permitted when `status` is `ACTIVE` and either the holding physician's `continuity_of_care_until` is null or the logical clock has reached it."

        Design: Corner/rbac/ipa_admin_and_network_manager_perform_their_own_exclusive_operations
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        physician = create_active_physician(api, agreement["id"])
        enrollee = create_enrollee(api, agreement["id"])
        assignment = assign_enrollee(api, enrollee["id"], physician["id"])
        assert read_physician(api, physician["id"])["panel_size"] == 1

        terminated = terminate_assignment(api, assignment["id"])
        assert terminated["status"] == "TERMINATED"
        assert read_physician(api, physician["id"])["panel_size"] == 0
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0


class TestExclusiveOperationsRejectOtherRoles:
    def test_a_network_manager_may_not_open_a_risk_pool(self, api):
        """PRD §2.1: "If both headers are well-formed but the named role does not appear in the authorised-role list of the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operation_returns_403
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)

        validate_error(
            api.create_risk_pool(
                agreement["id"], risk_pool_payload(), NETWORK_MANAGER_HEADERS
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    def test_an_ipa_admin_may_not_credential_a_physician(self, api):
        """PRD §2.1: "`IpaAdmin` owns agreements, risk pools, IBNR reserving, settlement proposal and scorecard finalisation, but it cannot credential a physician."

        Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operation_returns_403
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        physician = create_physician(api, agreement["id"])

        validate_error(
            api.set_physician_state(
                physician["id"], state_payload("CREDENTIALED"), IPA_ADMIN_HEADERS
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        assert read_physician(api, physician["id"])["credential_status"] == "APPLICANT"

    def test_a_network_manager_may_not_drive_an_enrollment_file(self, api):
        """PRD §2.1: "`NetworkManager` credentials physicians, manages panels, assignments, transfers and physician exit, but it cannot post an enrollment file."

        Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operation_returns_403
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)
        enrollment_file = create_enrollment_file(api, agreement["id"])

        validate_error(
            api.set_enrollment_file_state(
                enrollment_file["id"], state_payload("PARSED"), NETWORK_MANAGER_HEADERS
            ),
            ERR_UNAUTHORIZED,
            403,
        )


def _raw_get_agreement(api, agreement_id, headers):
    return api._request(
        "GET", f"/ipa/delegation-agreements/{agreement_id}", headers=headers
    )


class TestAuthenticationHeaderRequirements:
    def test_a_request_with_no_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "If either header is absent or empty, or if `X-User-Role` names a string that is not one of those six, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_with_missing_x_user_role_header_returns_401_unauthenticated
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)

        response = _raw_get_agreement(
            api,
            agreement["id"],
            {"X-User-ID": IPA_ADMIN_USER_ID, "Content-Type": "application/json"},
        )
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_a_role_outside_the_six_declared_names_is_unauthenticated(self, api):
        """PRD §2.1: "Six roles are recognised, and their names are spelled exactly as follows: `IpaAdmin`, `NetworkManager`, `ClaimsExaminer`, `ReinsuranceUnderwriter`, `PhysicianUser`, and `PayerRepresentative`."

        Design: Corner/rbac/request_with_missing_x_user_role_header_returns_401_unauthenticated
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)

        response = _raw_get_agreement(
            api,
            agreement["id"],
            build_user_headers(IPA_ADMIN_USER_ID, "AuditorUser"),
        )
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_an_empty_user_identifier_is_unauthenticated(self, api):
        """PRD §2.10: "`X-User-Role` is present and names one of the six declared roles, and `X-User-ID` is present and non-empty."

        Design: Corner/rbac/request_with_missing_x_user_role_header_returns_401_unauthenticated
        """
        set_clock(api, "2026-01-01T00:00:00Z")
        agreement = create_active_agreement(api, max_panel_size=5)

        response = _raw_get_agreement(
            api, agreement["id"], build_user_headers("", "IpaAdmin")
        )
        validate_error(response, ERR_UNAUTHENTICATED, 401)


def _two_active_physicians(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    first = create_active_physician(api, agreement["id"], full_name="Ada Okafor")
    second = create_active_physician(api, agreement["id"], full_name="Bo Lindgren")
    return agreement, first, second


class TestPhysicianUserOwnsOnlyItsOwnPanel:
    def test_a_physician_user_closes_its_own_panel(self, api):
        """PRD §2.10: "For a `PhysicianUser`, `X-User-ID` equals the `PhysicianMember` id the operation acts on — its own physician record, its own assignment transfer target, its own claim appeal."

        Design: Corner/rbac/physician_user_cannot_patch_another_physicians_panel_status
        """
        _agreement, first, _second = _two_active_physicians(api)

        closed = validate_success(
            api.set_panel_status(
                first["id"],
                {"panel_status": "CLOSED_TO_NEW"},
                make_physician_user_headers(first["id"]),
            ),
            200,
        )
        assert_fields(
            closed,
            {"panel_status": "CLOSED_TO_NEW", "version": first["version"] + 1},
        )

    def test_a_physician_user_patching_another_panel_is_not_the_owner(self, api):
        """PRD §2.1: "A violation of either ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/physician_user_cannot_patch_another_physicians_panel_status
        """
        _agreement, first, second = _two_active_physicians(api)

        validate_error(
            api.set_panel_status(
                first["id"],
                {"panel_status": "CLOSED_TO_NEW"},
                make_physician_user_headers(second["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

    def test_the_refused_patch_leaves_the_other_panel_untouched(self, api):
        """PRD §2.1: "Identity semantics differ by role, and they govern every ownership check in the system."

        Design: Corner/rbac/physician_user_cannot_patch_another_physicians_panel_status
        """
        _agreement, first, second = _two_active_physicians(api)

        validate_error(
            api.set_panel_status(
                first["id"],
                {"panel_status": "CLOSED_TO_NEW"},
                make_physician_user_headers(second["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        assert_fields(
            read_physician(api, first["id"]),
            {"panel_status": "OPEN", "version": first["version"]},
        )
        assert_fields(
            read_physician(api, second["id"]),
            {"panel_status": "OPEN", "version": second["version"]},
        )


def _submitted_recovery(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        stop_loss_attachment_cents=1000,
        reinsurance_recovery_bps=9000,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
        max_panel_size=5,
    )
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], external_member_id="SD-0001")
    assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": enrollee["external_member_id"],
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": 20000,
            }
        ],
    )
    build_paid_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        6000,
        service_date="2026-07-10T00:00:00Z",
    )

    recovery = create_recovery(api, pool["id"], enrollee["id"], CLAIMS_EXAMINER_HEADERS)
    submitted = submit_recovery(api, recovery["id"], CLAIMS_EXAMINER_HEADERS)
    return pool, recovery, submitted


class TestRecoverySubmitterCannotAdjudicate:
    def test_submission_retains_the_acting_identifier(self, api):
        """PRD §3.7: "The originating `ClaimsExaminer` takes it `DRAFT → SUBMITTED`, permitted when `status` is `DRAFT` and `excess_cents` is greater than zero; the transition records the acting `X-User-ID` in `submitted_by_user_id`."

        Design: Corner/rbac/recovery_submitter_cannot_approve_the_recovery_it_submitted
        """
        _pool, recovery, submitted = _submitted_recovery(api)
        assert recovery["excess_cents"] == 5000
        assert_fields(
            submitted,
            {
                "status": "SUBMITTED",
                "submitted_by_user_id": CLAIMS_EXAMINER_USER_ID,
                "adjudicated_by_user_id": None,
            },
        )

    def test_approving_under_the_submitter_identifier_is_refused(self, api):
        """PRD §2.1: "Attempting to adjudicate a recovery one submitted oneself is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/recovery_submitter_cannot_approve_the_recovery_it_submitted
        """
        pool, recovery, _submitted = _submitted_recovery(api)

        validate_error(
            api.set_recovery_state(
                recovery["id"],
                state_payload("APPROVED"),
                make_reinsurance_underwriter_headers(CLAIMS_EXAMINER_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert_fields(
            read_recovery(api, recovery["id"]),
            {"status": "SUBMITTED", "adjudicated_by_user_id": None},
        )
        assert read_pool(api, pool["id"])["stop_loss_recovery_cents"] == 0

    def test_a_different_identifier_may_approve_and_move_the_pool_ledger(self, api):
        """PRD §3.7: "Approval records the acting identifier in `adjudicated_by_user_id` and increases the pool's `stop_loss_recovery_cents` by the recovery's `recovery_cents`, advancing both the recovery's `version` and the pool's `version` by 1."

        Design: Corner/rbac/recovery_submitter_cannot_approve_the_recovery_it_submitted
        """
        pool, recovery, submitted = _submitted_recovery(api)
        before = read_pool(api, pool["id"])

        approved = validate_success(
            api.set_recovery_state(
                recovery["id"],
                state_payload("APPROVED"),
                REINSURANCE_UNDERWRITER_HEADERS,
            ),
            200,
        )
        assert_fields(
            approved,
            {
                "status": "APPROVED",
                "submitted_by_user_id": CLAIMS_EXAMINER_USER_ID,
                "version": submitted["version"] + 1,
            },
        )
        assert approved["adjudicated_by_user_id"] != CLAIMS_EXAMINER_USER_ID

        after = read_pool(api, pool["id"])
        assert after["stop_loss_recovery_cents"] == (
            before["stop_loss_recovery_cents"] + recovery["recovery_cents"]
        )
        assert after["version"] == before["version"] + 1
