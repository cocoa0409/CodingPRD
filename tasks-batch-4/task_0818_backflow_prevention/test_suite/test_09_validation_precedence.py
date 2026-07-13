"""Validation-ladder precedence (state beats safety) and uniqueness constraints."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories, fixtures, make_tester_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/removed_device_expired_tester_state_beats_safety
# --------------------------------------------------------------------------- #
def test_removed_device_expired_tester_returns_not_testable(api):
    """PRD §2.10: "(4) target state permits the transition, else the endpoint-specific
    state-conflict error; (5) tester certification for test-report and test-appointment
    writes, else `ERR_TESTER_NOT_CERTIFIED`".
    PRD §2.10: "A check earlier in this ladder always masks a violation that a later check
    would also have caught."

    Design: Difficulty/priority_pair_validation_conflict/removed_device_expired_tester_state_beats_safety
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    get_success_data(api.remove_device(dev["id"], ADMIN))
    tester = fixtures.create_tester(api, ADMIN, cert_effective_date="2025-01-01T00:00:00Z",
                                    cert_expiry_date="2026-02-01T00:00:00Z")
    fixtures.set_clock("2026-06-01T00:00:00Z", api, ADMIN)  # expires the tester
    payload = factories.report_payload(dev["id"], tester["id"], test_date="2026-06-01T00:00:00Z",
                                       relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    validate_error(api.create_report(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_DEVICE_NOT_TESTABLE)


def test_testable_device_expired_tester_returns_not_certified(api):
    """PRD §2.10: "(5) tester certification for test-report and test-appointment writes,
    else `ERR_TESTER_NOT_CERTIFIED`".
    PRD §3.3: "the tester must be certified with the `test_date` falling within the
    inclusive window from `cert_effective_date` to `cert_expiry_date` and the tester in
    `ACTIVE` status (else `ERR_TESTER_NOT_CERTIFIED`)."

    Design: Difficulty/priority_pair_validation_conflict/removed_device_expired_tester_state_beats_safety
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")  # left ACTIVE (testable)
    tester = fixtures.create_tester(api, ADMIN, cert_effective_date="2025-01-01T00:00:00Z",
                                    cert_expiry_date="2026-02-01T00:00:00Z")
    fixtures.set_clock("2026-06-01T00:00:00Z", api, ADMIN)  # expires the tester
    payload = factories.report_payload(dev["id"], tester["id"], test_date="2026-06-01T00:00:00Z",
                                       relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    validate_error(api.create_report(payload, make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_TESTER_NOT_CERTIFIED)


# --------------------------------------------------------------------------- #
# Corner/validations/duplicate_serial_number_returns_conflict
# --------------------------------------------------------------------------- #
def test_duplicate_serial_number_returns_conflict(api):
    """PRD §3.1: "A duplicate `serial_number` is rejected with `ERR_DUPLICATE_VALUE`."

    Design: Corner/validations/duplicate_serial_number_returns_conflict
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, serial_number="SN-DUP",
                           install_date="2026-01-01T00:00:00Z")
    dup = factories.device_payload(conn["id"], serial_number="SN-DUP", device_type="DC",
                                   hazard_rating="LOW", install_date="2026-01-01T00:00:00Z")
    validate_error(api.create_device(dup, ADMIN), ApiErrorId.ERR_DUPLICATE_VALUE)
