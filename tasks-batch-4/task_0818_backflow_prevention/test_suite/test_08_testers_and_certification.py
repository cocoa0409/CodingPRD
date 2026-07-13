"""Tester certification lifecycle and its gate on test-report submission."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories, fixtures, make_tester_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/report_submit_requires_active_tester
# --------------------------------------------------------------------------- #
def test_report_submit_rejected_when_tester_suspended(api):
    """PRD §3.3: "the tester must be certified with the `test_date` falling within the
    inclusive window from `cert_effective_date` to `cert_expiry_date` and the tester in
    `ACTIVE` status (else `ERR_TESTER_NOT_CERTIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_tester
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    get_success_data(api.suspend_tester(tester["id"], ADMIN))
    payload = factories.report_payload(dev["id"], tester["id"], test_date="2026-02-20T00:00:00Z",
                                       relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    validate_error(api.create_report(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_TESTER_NOT_CERTIFIED)


def test_report_submit_accepted_when_tester_active(api):
    """PRD §3.3: "the tester must be certified with the `test_date` falling within the
    inclusive window from `cert_effective_date` to `cert_expiry_date` and the tester in
    `ACTIVE` status (else `ERR_TESTER_NOT_CERTIFIED`)."
    PRD §3.1: "reinstating a suspended tester to `ACTIVE` is permitted only while the
    certification is still within its window, that is while `current_utc` is on or before
    `cert_expiry_date`."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_tester
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    get_success_data(api.suspend_tester(tester["id"], ADMIN))
    get_success_data(api.reinstate_tester(tester["id"], ADMIN))
    payload = factories.report_payload(dev["id"], tester["id"], test_date="2026-02-20T00:00:00Z",
                                       relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    data = validate_success(api.create_report(payload, make_tester_headers(tester["id"])),
                            expected_status=201)
    assert data["status"] == "SUBMITTED", \
        f"an ACTIVE certified tester may submit, got {data['status']}"


# --------------------------------------------------------------------------- #
# Corner/endpoints/tester_suspend_then_reinstate_restores_active
# --------------------------------------------------------------------------- #
def test_tester_suspend_then_reinstate_restores_active(api):
    """PRD §3.1: "An admin may move a tester from `ACTIVE` to `SUSPENDED` and back;
    reinstating a suspended tester to `ACTIVE` is permitted only while the certification is
    still within its window, that is while `current_utc` is on or before `cert_expiry_date`."

    Design: Corner/endpoints/tester_suspend_then_reinstate_restores_active
    """
    tester = fixtures.create_tester(api, ADMIN)
    get_success_data(api.suspend_tester(tester["id"], ADMIN))
    data = validate_success(api.reinstate_tester(tester["id"], ADMIN))
    assert data["status"] == "ACTIVE", f"reinstate should restore ACTIVE, got {data['status']}"
