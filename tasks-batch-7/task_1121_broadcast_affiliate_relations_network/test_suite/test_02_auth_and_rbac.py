"""Auth and RBAC coverage (corner index: validations + rbac sections)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_clearance_report_payload,
    create_network_payload,
    create_program_payload,
    create_station_group_payload,
    create_station_payload,
    get_success_data,
    make_auditor_headers,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_active_agreement,
    create_clearance_report,
    create_territory,
)


class TestUnauthenticated:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role not
        in the RBAC matrix, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        # Anonymous headers: empty dict, no X-User-ID / X-User-Role.
        resp = api.create_network(create_network_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestUnauthorizedRole:
    def test_station_group_owner_cannot_create_program(self, api):
        """PRD §4: POST /networks/{nid}/programs is authorized for
        NetworkAffiliateRelations only; PRD §2.1: "A request whose role is
        recognized but not authorized for the target endpoint is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/validations/unauthorized_role_cannot_create_program
        """
        setup_clock("2026-05-01T00:00:00Z")
        admin = make_platform_admin_headers()
        net = get_success_data(api.create_network(create_network_payload(), admin))
        grp = get_success_data(api.create_station_group(create_station_group_payload(), admin))
        sgo = make_station_group_owner_headers(grp["id"])
        resp = api.create_program(net["id"], create_program_payload(), sgo)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_compliance_auditor_cannot_terminate_agreement(self, api):
        """PRD §4: POST .../agreements/{aid}/terminate is NetworkAffiliateRelations
        exclusive; PRD §2.1: role recognized but not authorized for the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

        Design: Corner/rbac/compliance_auditor_cannot_terminate_agreement
        """
        scenario = setup_basic_scenario()
        auditor = make_auditor_headers()
        resp = api.terminate_agreement(
            scenario["network"]["id"],
            scenario["station"]["id"],
            scenario["agreement"]["id"],
            auditor,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_platform_admin_cannot_file_clearance(self, api):
        """PRD §4: POST .../clearance-reports/{cid}/file is StationGroupOwner
        exclusive; PRD §2.1: role recognized but not authorized is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

        Design: Corner/rbac/platform_admin_cannot_file_clearance
        """
        scenario = setup_basic_scenario()
        # Build a DRAFT clearance report as the station group owner.
        report = create_clearance_report(
            scenario["network"]["id"],
            scenario["station"]["id"],
            scenario["sgo_headers"],
        )
        admin = make_platform_admin_headers()
        resp = api.file_clearance_report(
            scenario["network"]["id"],
            scenario["station"]["id"],
            report["id"],
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
