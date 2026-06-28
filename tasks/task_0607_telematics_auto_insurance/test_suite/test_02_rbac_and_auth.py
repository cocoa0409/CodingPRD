"""Authentication, role permission, and resource-ownership tests.

Translated from SCAFFOLD_CORNER_DESIGN.yaml queue B instances under sections
`errors` and `rbac`.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    create_policy_payload,
    create_enrollment_payload,
    create_claim_payload,
    triage_claim_payload,
    TEST_USERS,
    make_driver_headers,
    set_clock,
    create_rate_plan,
    create_driver,
    setup_ready_quote,
    setup_bound_policy,
    create_manual_claim,
)

UW = TEST_USERS["underwriting_headers"]


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/errors/missing_user_context_header_rejected
    """
    res = api.list_drivers(headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=401)


def test_quote_not_expired_early_expire_rejected(api):
    """PRD §3.4: "An `UnderwritingOps` operator may expire an `OPEN` quote whose
    validity window has elapsed, moving it to the terminal `EXPIRED` state; expiry is
    permitted only when the clock is strictly past `expires_at`, and an early call is
    rejected with `ERR_QUOTE_NOT_EXPIRED`."

    Design: Corner/errors/quote_not_expired_early_expire_rejected
    """
    ctx = setup_ready_quote(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # clock still at 2026-02-01, quote validity is 14 days -> not yet expired
    res = api.expire_quote(ctx["quote"]["id"], UW)
    validate_error(res, "ERR_QUOTE_NOT_EXPIRED", expected_status=409)


def test_driver_cannot_bind_quote_forbidden(api):
    """PRD §2.1: "When a request is well-formed but the declared role is not permitted
    to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`."
    PRD §3.4: "Binding is performed by an `UnderwritingOps` operator who supplies the
    `quote_id` to create a **policy**."

    Design: Corner/rbac/driver_cannot_bind_quote_forbidden
    """
    ctx = setup_ready_quote(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    res = api.create_policy(create_policy_payload(ctx["quote"]["id"]), ctx["dheaders"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_driver_cannot_act_on_other_drivers_enrollment_forbidden(api):
    """PRD §2.1: "A `DriverUser` who acts on a driver-scoped resource that resolves to
    a different driver is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/driver_cannot_act_on_other_drivers_enrollment_forbidden
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver_a = create_driver(email="owner-a@example.com")
    driver_b = create_driver(email="owner-b@example.com")
    # acting as driver A, try to open an enrollment for driver B
    res = api.create_enrollment(
        create_enrollment_payload(driver_b["id"], rate_plan["id"], 30),
        make_driver_headers(driver_a["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_driver_cannot_triage_claim_forbidden(api):
    """PRD §2.1: "When a request is well-formed but the declared role is not permitted
    to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`."
    PRD §3.8: "A `ClaimsAdjuster` drives the claim through its lifecycle. Triage moves
    a claim from `FNOL` to `UNDER_REVIEW`".

    Design: Corner/rbac/driver_cannot_triage_claim_forbidden
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    claim = create_manual_claim(ctx, reported_severity=3)
    res = api.triage_claim(claim["id"], triage_claim_payload(), ctx["dheaders"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
