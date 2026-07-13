"""Optimistic-concurrency on finalize, and role/ownership/authentication access control."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NO_AUTH_HEADERS,
    factories, fixtures, make_owner_headers, make_tester_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/finalize_with_stale_connection_version_returns_stale
# --------------------------------------------------------------------------- #
def test_finalize_with_stale_connection_version_returns_stale(api):
    """PRD §2.9: "If that value does not equal the connection's current `version` at the
    moment of finalization, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    no state changes."

    Design: Corner/cross_cutting_complexity_layers/finalize_with_stale_connection_version_returns_stale
    """
    conn = fixtures.create_connection(api, ADMIN)
    survey1 = fixtures.create_survey(conn["id"], api, ADMIN, premise_use_score=10,
                                     chemical_exposure_score=10, auxiliary_supply_score=10)
    survey2 = fixtures.create_survey(conn["id"], api, ADMIN, premise_use_score=20,
                                     chemical_exposure_score=20, auxiliary_supply_score=20)
    v0 = get_success_data(api.get_connection(conn["id"], ADMIN))["version"]
    get_success_data(api.finalize_survey(survey1["id"],
                                         {"expected_service_connection_version": v0}, ADMIN))
    # v0 is now stale because finalizing survey1 advanced the connection version.
    validate_error(api.finalize_survey(survey2["id"],
                                       {"expected_service_connection_version": v0}, ADMIN),
                   ApiErrorId.ERR_STALE_VERSION)


# --------------------------------------------------------------------------- #
# Corner/rbac/premises_owner_cannot_create_device
# --------------------------------------------------------------------------- #
def test_premises_owner_cannot_create_device(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation — or an ownership check fails — the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/premises_owner_cannot_create_device
    """
    conn = fixtures.create_connection(api, ADMIN, owner_user_id="owner-1")
    payload = factories.device_payload(conn["id"], serial_number="SN-C19",
                                       install_date="2026-01-01T00:00:00Z")
    validate_error(api.create_device(payload, make_owner_headers("owner-1")),
                   ApiErrorId.ERR_UNAUTHORIZED)


# --------------------------------------------------------------------------- #
# Corner/rbac/tester_cannot_accept_test_report
# --------------------------------------------------------------------------- #
def test_tester_cannot_accept_test_report(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation — or an ownership check fails — the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/tester_cannot_accept_test_report
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    tester = fixtures.create_tester(api, ADMIN)
    report = fixtures.submit_report(dev["id"], tester["id"], api,
                                    relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    validate_error(api.accept_report(report["id"], make_tester_headers(tester["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED)


# --------------------------------------------------------------------------- #
# Corner/rbac/tester_cannot_submit_report_for_other_tester_ownership
# --------------------------------------------------------------------------- #
def test_tester_cannot_submit_report_for_other_tester(api):
    """PRD §2.1: "ownership checks on a test appointment or a test report compare the
    resource's `tester_id` field to `X-User-ID`, so a tester may only book, cancel, or
    report against work they own."

    Design: Corner/rbac/tester_cannot_submit_report_for_other_tester_ownership
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, device_type="RP", hazard_rating="HIGH",
                                 install_date="2026-01-01T00:00:00Z")
    t1 = fixtures.create_tester(api, ADMIN)
    t2 = fixtures.create_tester(api, ADMIN)
    payload = factories.report_payload(dev["id"], t1["id"],
                                       relief_valve_differential_psid=2.5, check_valve_1_psid=1.5)
    # Acting as t2 but claiming tester_id == t1 -> ownership mismatch.
    validate_error(api.create_report(payload, make_tester_headers(t2["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED)


# --------------------------------------------------------------------------- #
# Corner/rbac/get_connection_missing_auth_returns_unauthenticated
# --------------------------------------------------------------------------- #
def test_get_connection_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of these three
    recognized values, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/get_connection_missing_auth_returns_unauthenticated
    """
    conn = fixtures.create_connection(api, ADMIN)
    validate_error(api.get_connection(conn["id"], NO_AUTH_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED)
