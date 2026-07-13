"""Role-based access control and ownership enforcement (PRD §2.1)."""
from test_helpers import (
    validate_error, TEST_USERS, make_customer_headers,
    create_participant, create_course_payload, create_waiver_payload,
)

OP = TEST_USERS["operator_headers"]


def test_customer_cannot_create_course(api):
    """PRD §2.1: "a small set of configuration and staffing operations (creating courses,
    time slots, guides, guide assignments, gear items, season passes, and
    opening/closing/completing slots) are exclusive to `Operator`."
    PRD §2.1: "When the headers are present but the acting role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_course_returns_unauthorized
    """
    customer = create_participant(api, full_name="Cust")
    res = api.create_course(create_course_payload(), make_customer_headers(customer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_customer_cannot_sign_other_participants_waiver(api):
    """PRD §2.1: "a `Customer` may only sign the waiver of, redeem a rain-checked booking
    of, or cancel a booking of the `Participant` whose `id` equals `X-User-ID`. A
    `Customer` attempting any of these against a participant or booking they do not own is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_sign_other_participants_waiver
    """
    p_a = create_participant(api, full_name="A")
    p_b = create_participant(api, full_name="B")
    res = api.sign_waiver(p_b["id"], create_waiver_payload(signature_name="A"),
                          make_customer_headers(p_a["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_course(create_course_payload(), {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
