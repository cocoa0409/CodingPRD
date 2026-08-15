"""Authentication, role authorization, existence validation, and uniqueness
constraints (PRD §2.1, §2.8, §3.1, §3.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_crossing,
    create_crossing_payload,
    create_diagnostic_review_payload,
    create_funding_program_payload,
    create_locality,
    create_program,
    create_project,
    create_team,
    get_success_data,
    make_local_authority_headers,
    setup_locality_and_crossing,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
RAILROAD = TEST_USERS["railroad_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        the system does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)." PRD §2.9: "1. **Authentication** — missing or malformed
        `X-User-ID` / `X-User-Role` headers yield `ERR_UNAUTHENTICATED`." (auth
        outranks existence, so even a bogus locality FK does not surface first)

        Design: Corner/rbac/missing_auth_returns_unauthenticated
        """
        payload = create_crossing_payload(
            dot_crossing_number="DOT-060001",
            road_authority_locality_id="8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
        )
        resp = api.create_crossing(payload, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleExclusivity:
    def test_local_authority_cannot_create_crossings(self, api):
        """PRD §2.1: "Every endpoint admits a specific list of roles (§4); a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST /crossings is authorized
        for ProgramAdministrator only.

        Design: Corner/rbac/role_exclusive_operations_denied
        """
        locality = create_locality(locality_name="Role City")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-060011",
                road_authority_locality_id=locality["id"],
            ),
            make_local_authority_headers(locality["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_railroad_maintainer_cannot_create_funding_programs(self, api):
        """PRD §2.1: "Every endpoint admits a specific list of roles (§4); a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4: POST /funding-programs is
        authorized for ProgramAdministrator only.

        Design: Corner/rbac/role_exclusive_operations_denied
        """
        resp = api.create_funding_program(
            create_funding_program_payload(
                fiscal_year=2050,
                apportionment_cents=1_000_000,
                allocation_method="WATERFALL_BY_RANK",
            ),
            RAILROAD,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


class TestExistenceValidation:
    def test_body_foreign_keys_existence_checked(self, api, admin_headers):
        """PRD §2.8: "For any request that references resources — by path
        identifier or by a foreign key in the request body — the server validates
        existence in a fixed left-to-right order: path identifiers first, in the
        order they appear in the URL, then body foreign keys. The first reference
        that does not resolve to an existing resource produces the response, and
        each resource family has its own code: `ERR_CROSSING_NOT_FOUND`,
        `ERR_LOCALITY_NOT_FOUND` ... (all HTTP 404)."

        Design: Corner/validations/body_fk_existence_validated
        """
        team = create_team(team_name="Team Eta")
        bogus = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

        resp = api.create_diagnostic_review(
            create_diagnostic_review_payload(
                crossing_id=bogus, team_id=team["id"], scheduled_date="2026-09-10"
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CROSSING_NOT_FOUND, expected_status=404)

        resp2 = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-040141",
                road_authority_locality_id=bogus,
            ),
            admin_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_LOCALITY_NOT_FOUND, expected_status=404)


class TestNotFoundSweep:
    @pytest.mark.parametrize(
        "getter,error_id",
        [
            ("get_funding_program", ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            ("get_upgrade_project", ApiErrorId.ERR_PROJECT_NOT_FOUND),
            ("get_closure_agreement", ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            ("get_quiet_zone_application", ApiErrorId.ERR_QZ_APPLICATION_NOT_FOUND),
            ("get_quiet_zone_crossing", ApiErrorId.ERR_QZ_MEMBER_NOT_FOUND),
            ("get_maintenance_assignment", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            ("get_maintenance_work_order", ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
            (
                "get_preemption_interconnection",
                ApiErrorId.ERR_INTERCONNECTION_NOT_FOUND,
            ),
            ("get_diagnostic_review", ApiErrorId.ERR_REVIEW_NOT_FOUND),
            ("get_diagnostic_team", ApiErrorId.ERR_TEAM_NOT_FOUND),
            ("get_locality", ApiErrorId.ERR_LOCALITY_NOT_FOUND),
            ("get_incident_report", ApiErrorId.ERR_INCIDENT_NOT_FOUND),
        ],
    )
    def test_detail_get_with_absent_uuid_returns_domain_404(
        self, api, admin_headers, getter, error_id
    ):
        """PRD §2.8: "The first reference that does not resolve to an existing
        resource produces the response, and each resource family has its own code:
        `ERR_CROSSING_NOT_FOUND`, `ERR_LOCALITY_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_QZ_APPLICATION_NOT_FOUND`, `ERR_QZ_MEMBER_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and
        `ERR_INTERCONNECTION_NOT_FOUND` (all HTTP 404)."

        Design: Corner/endpoints/error_catalog_not_found_sweep
        """
        resp = getattr(api, getter)(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers
        )
        validate_error(resp, error_id, expected_status=404)


class TestUniqueness:
    def test_duplicate_dot_crossing_number_rejected(self, api, admin_headers):
        """PRD §3.1: "its federally assigned `dot_crossing_number` (unique across
        all crossings — a duplicate is rejected with `ERR_DUPLICATE_DOT_NUMBER`)".

        Design: Corner/validations/duplicate_dot_number_rejected
        """
        locality = create_locality(locality_name="Dup City")
        create_crossing(locality["id"], dot_crossing_number="DOT-040011")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-040011",
                road_authority_locality_id=locality["id"],
                aadt=4000,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DOT_NUMBER, expected_status=409)

    def test_duplicate_fiscal_year_rejected(self, api, admin_headers):
        """PRD §3.4: "A `ProgramAdministrator` creates one with its `fiscal_year`
        (unique across programs — a repeat is rejected with
        `ERR_DUPLICATE_FISCAL_YEAR`)".

        Design: Corner/validations/duplicate_fiscal_year_rejected
        """
        create_program(
            fiscal_year=2041,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        resp = api.create_funding_program(
            create_funding_program_payload(
                fiscal_year=2041,
                apportionment_cents=2_000_000,
                allocation_method="PROPORTIONAL_SHARE",
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR, expected_status=409)


class TestProjectCreationConstraints:
    def test_target_same_as_current_device_class_rejected(self, api, officer_headers):
        """PRD §3.4: "the target class must differ from the crossing's current
        `warning_device_class` (else `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/project_target_same_device_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040021", "warning_device_class": "GATES"}
        )
        prog = create_program(fiscal_year=2042, apportionment_cents=1_000_000)
        from test_helpers import create_upgrade_project_payload

        resp = api.create_upgrade_project(
            create_upgrade_project_payload(
                crossing_id=crossing["id"],
                program_id=prog["id"],
                target_device_class="GATES",
                estimated_cost_cents=300_000,
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_one_non_terminal_project_per_crossing(self, api, officer_headers):
        """PRD §3.4: "a crossing may carry at most one non-terminal project at a
        time — if one already exists in `PROPOSED`, `ELIGIBLE`, `SELECTED`,
        `AWARDED`, or `IN_PROGRESS`, the proposal is rejected with
        `ERR_ACTIVE_PROJECT_EXISTS`."

        Design: Corner/validations/active_project_exists_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040061"}
        )
        prog = create_program(fiscal_year=2045, apportionment_cents=1_000_000)
        create_project(
            crossing["id"],
            prog["id"],
            target_device_class="FOUR_QUADRANT_GATES",
            estimated_cost_cents=300_000,
        )
        from test_helpers import create_upgrade_project_payload

        resp = api.create_upgrade_project(
            create_upgrade_project_payload(
                crossing_id=crossing["id"],
                program_id=prog["id"],
                target_device_class="FLASHING_LIGHTS",
                estimated_cost_cents=100_000,
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PROJECT_EXISTS, expected_status=409)


class TestProjectTerminalLockdown:
    def test_withdrawn_project_rejects_further_transitions(
        self, api, officer_headers
    ):
        """PRD §3.4: "A project may also be withdrawn from `PROPOSED`, `ELIGIBLE`,
        or `SELECTED` by a `RailSafetyOfficer` ... `COMPLETED` and `WITHDRAWN` are
        terminal."

        Design: Corner/state_machines/project_withdrawn_terminal_lockdown
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020021"}
        )
        prog = create_program(fiscal_year=2040, apportionment_cents=1_000_000)
        pj = create_project(crossing["id"], prog["id"], estimated_cost_cents=300_000)
        withdrawn = get_success_data(
            api.transition_upgrade_project(
                pj["id"], {"to_status": "WITHDRAWN"}, officer_headers
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.transition_upgrade_project(
            pj["id"], {"to_status": "ELIGIBLE"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_upgrade_project(pj["id"], ADMIN))
        assert after["status"] == "WITHDRAWN"
