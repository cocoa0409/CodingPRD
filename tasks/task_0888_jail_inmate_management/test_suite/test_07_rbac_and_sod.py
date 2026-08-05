"""Role-based access control, authentication, and segregation of duties."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures, build_user_headers,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]


def test_scheduler_cannot_create_inmate(api):
    """PRD §2.1: "If the headers are present but the named role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." Only an
    `IntakeOfficer` "books inmates".

    Design: Corner/rbac/scheduler_cannot_create_inmate_unauthorized
    """
    resp = api.create_inmate(f.create_inmate_payload(full_name="No Right"), SCHEDULER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller, and
    `X-User-Role`, naming the caller's role. If either header is missing or malformed, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_inmate(f.create_inmate_payload(full_name="Anon"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_uphold_own_report_segregation_of_duties(api):
    """PRD §3.8: "Upholding enforces segregation of duties: the upholder's `X-User-ID` must not
    equal the `reported_by_user_id` of the officer who reported it, and an attempt to uphold
    one's own report is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/uphold_by_reporter_segregation_of_duties
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], charge_severity="FELONY", sentence_days=100)
    # Reported by supervisor-9; uphold attempted by the same supervisor-9.
    reporter = build_user_headers("supervisor-9", "Supervisor")
    infraction = get_success_data(
        api.create_infraction(booking["id"], f.create_infraction_payload("ASSAULT", 4), reporter)
    )
    resp = api.uphold_infraction(infraction["id"], build_user_headers("supervisor-9", "Supervisor"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    infr_now = get_success_data(api.list_infractions(booking["id"], TEST_USERS["supervisor_headers"]))
    inf = next(i for i in infr_now if i["id"] == infraction["id"])
    assert inf["infraction_status"] == "REPORTED", f"infraction must stay REPORTED, got {inf['infraction_status']}"
