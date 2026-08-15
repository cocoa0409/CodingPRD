"""Corner coverage — roles (PRD §2.1, §4): each exclusive endpoint refuses
roles not listed for it with ERR_FORBIDDEN_ROLE (403)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_certified_technician,
    create_outage_window,
    create_spare_unit,
    create_technician,
    create_test_event,
    make_technician_headers,
    setup_asset,
    submit_test_event,
    validate_error,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestRoleDenials:
    def test_technician_cannot_create_substation(self):
        """PRD §2.1: "A request whose role is recognized but not listed for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST `/substations` is authorized for `OperationsManager` only.

        Design: Corner/roles/technician_cannot_create_substation_rejected
        """
        tech = create_technician()
        resp = api_client.create_substation(
            {"name": "Nope", "code": "SUB-NOPE", "region": "North"},
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_coordinator_cannot_review_test(self):
        """PRD §2.1: "A request whose role is recognized but not listed for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST `/test-events/{id}/review` is authorized for
        `ComplianceOfficer` only.

        Design: Corner/roles/coordinator_cannot_review_test_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        event = create_test_event(
            base["asset"]["id"], tech_headers, "OIL_MOISTURE",
            value_primary=10, measured_at="2026-07-28T00:00:00Z",
        )
        submit_test_event(event["id"], tech_headers)
        resp = api_client.review_test_event(event["id"], {"decision": "ACCEPT"}, COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_compliance_officer_cannot_approve_outage(self):
        """PRD §2.1: "A request whose role is recognized but not listed for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST `/outage-windows/{id}/approve` is authorized for
        `OperationsManager` only.

        Design: Corner/roles/compliance_officer_cannot_approve_outage_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-12-20T08:00:00Z", "2026-12-20T16:00:00Z", purpose="RBAC probe",
        )
        resp = api_client.approve_outage_window(window["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_supervisor_cannot_create_reservation(self):
        """PRD §2.1: "A request whose role is recognized but not listed for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST `/spare-reservations` is authorized for
        `OutageCoordinator` only.

        Design: Corner/roles/supervisor_cannot_create_reservation_rejected
        """
        unit = create_spare_unit(home_location="Yard-U")
        resp = api_client.create_spare_reservation(
            {
                "spare_unit_id": unit["id"],
                "unit_type": "SPARE_TRANSFORMER",
                "required_mva": 20,
                "required_voltage_kv": 115,
                "start_ts": "2026-12-15T08:00:00Z",
                "end_ts": "2026-12-15T16:00:00Z",
            },
            SUP1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
