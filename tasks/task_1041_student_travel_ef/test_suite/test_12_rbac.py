"""Role-based access control: exclusive operations, missing auth, and ownership (queue-B rbac)."""
from test_helpers import (
    validate_error, OPERATOR, ANON_HEADERS,
    ApiErrorId,
    make_group_leader, make_group_leader_headers, make_traveler_headers,
    setup_open_departure, enroll,
    create_tour_payload,
)


def test_group_leader_cannot_create_tour_returns_unauthorized(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, or an ownership check fails, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."
    PRD §4: "POST | /tours | Create a tour product template | Operator".

    Design: Corner/rbac/group_leader_cannot_create_tour_returns_unauthorized
    """
    gl = make_group_leader(api)
    headers = make_group_leader_headers(gl["id"])
    resp = api.create_tour(
        create_tour_payload(name="Sneaky Tour", destination="Nowhere", nights=3, base_price_cents=100000), headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of these three values, the request
    is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_tour(
        create_tour_payload(name="Anon Tour", destination="Nowhere", nights=3, base_price_cents=100000), ANON_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_traveler_cannot_cancel_other_travelers_enrollment_returns_unauthorized(api):
    """PRD §2.1: "When X-User-Role is Traveler, X-User-ID is the id of the acting Enrollment.
    Ownership checks compare the target enrollment's id to X-User-ID; for payment and
    permission-form actions the referenced plan or form must resolve back to that same
    enrollment."

    Design: Corner/rbac/traveler_cannot_cancel_other_travelers_enrollment_returns_unauthorized
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    enr_a = enroll(api, ctx["departure"]["id"], traveler_name="Owner A")
    enr_b = enroll(api, ctx["departure"]["id"], traveler_name="Owner B", traveler_dob="2010-05-02T00:00:00Z")
    # Act as Traveler identified by enr_a, but target enr_b.
    headers = make_traveler_headers(enr_a["id"])
    resp = api.cancel_enrollment(enr_b["id"], headers, {"reason": "traveler"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
