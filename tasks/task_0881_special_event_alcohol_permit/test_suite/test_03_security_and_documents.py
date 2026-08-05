"""Supporting documents: security staffing math, cert/coverage/date safety gates.

Difficulty: combinatorial_formula (guards), boundary_precision_check (occupancy).
Corner: cert/coverage/date validations, enum, reverse lookup, verify idempotency.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_server_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS

APPLICANT = TEST_USERS["applicant_headers"]
CLERK = TEST_USERS["clerk_headers"]


def _required_guard_count(api, expected_attendance, alcohol_service_hours, occupancy_limit=200):
    venue = fixtures.create_venue(api, occupancy_limit=occupancy_limit)
    app = fixtures.create_application(
        api, venue_id=venue["id"], expected_attendance=expected_attendance,
        alcohol_service_hours=alcohol_service_hours)
    plan = fixtures.add_security_plan(api, app["id"], planned_guard_count=99)
    return plan["required_guard_count"]


def test_required_guards_combines_base_duration_and_occupancy(api):
    """PRD §3.4: "Start with a base of the attendance divided by 75 attendees per guard,
    rounded up to the next whole guard. Add one guard when the event's
    `alcohol_service_hours` exceeds 5 hours. Add one more guard when the
    `expected_attendance` is at least ninety percent of the venue's `occupancy_limit`
    (the ninety-percent boundary is inclusive). Finally, take the greater of that running
    total and a floor of 2 guards; the result is the required number of guards."

    attendance 180 (>= 0.9*200), 6h (>5): base ceil(180/75)=3, +1, +1 => 5.

    Design: Difficulty/combinatorial_formula/security_guards_multifactor
    """
    assert _required_guard_count(api, 180, 6) == 5


def test_required_guards_drops_duration_bonus_at_five_hours(api):
    """PRD §3.4: "Add one guard when the event's `alcohol_service_hours` exceeds 5 hours."

    attendance 180 (>= 0.9*200), exactly 5h (not > 5): base 3, +0 duration, +1 occupancy => 4.

    Design: Difficulty/combinatorial_formula/security_guards_multifactor
    """
    assert _required_guard_count(api, 180, 5) == 4


def test_high_occupancy_bonus_fires_at_ninety_percent_boundary(api):
    """PRD §3.4: "Add one more guard when the `expected_attendance` is at least ninety
    percent of the venue's `occupancy_limit` (the ninety-percent boundary is inclusive)."

    attendance exactly 180 == 0.9*200, 4h: base 3, +0 duration, +1 occupancy => 4.

    Design: Difficulty/boundary_precision_check/high_occupancy_guard_boundary
    """
    assert _required_guard_count(api, 180, 4) == 4


def test_high_occupancy_bonus_absent_just_below_boundary(api):
    """PRD §3.4: "Add one more guard when the `expected_attendance` is at least ninety
    percent of the venue's `occupancy_limit` (the ninety-percent boundary is inclusive)."

    attendance 179 (< 0.9*200=180), 4h: base ceil(179/75)=3, +0, +0 => 3.

    Design: Difficulty/boundary_precision_check/high_occupancy_guard_boundary
    """
    assert _required_guard_count(api, 179, 4) == 3


def test_verify_server_with_expired_cert_rejected(api):
    """PRD §3.4: "its `cert_expiry_date` must be on or after the application's `event_end`;
    a certificate that expires before the event ends is rejected with `ERR_CERT_EXPIRED`."

    Design: Corner/validations/cert_expired_verify_rejected
    """
    app = fixtures.create_application(api)
    server = fixtures.add_server(api, app["id"], cert_expiry_date="2026-06-10T00:00:00Z")
    resp = api.verify_server(server["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_CERT_EXPIRED)


def test_approve_security_plan_with_too_few_guards_rejected(api):
    """PRD §3.4: "its `planned_guard_count` must meet or exceed the required guard count,
    else `ERR_INSUFFICIENT_SECURITY`."

    attendance 151 requires 3 guards; a plan committing only 2 is rejected.

    Design: Corner/validations/insufficient_security_approve_rejected
    """
    app = fixtures.create_application(api, expected_attendance=151)
    plan = fixtures.add_security_plan(api, app["id"], planned_guard_count=2)
    resp = api.approve_security_plan(plan["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SECURITY)


def test_accept_insurance_with_non_spanning_dates_rejected(api):
    """PRD §3.4: "The policy dates must span the event — its `effective_date` at or before
    `event_start` and its `expiry_date` at or after `event_end` — else
    `ERR_INSURANCE_DATES_INVALID`."

    effective_date 2026-06-20 is after event_start 2026-06-15 though coverage is sufficient.

    Design: Corner/validations/insurance_dates_invalid_accept_rejected
    """
    app = fixtures.create_application(api)
    policy = fixtures.add_insurance(api, app["id"], effective_date="2026-06-20T00:00:00Z",
                                    expiry_date="2026-07-01T00:00:00Z")
    resp = api.accept_insurance_policy(policy["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_DATES_INVALID)


def test_add_server_with_invalid_training_provider_rejected(api):
    """PRD §2.9: "an enum field whose value is outside its allowed set surfaces as
    `ERR_INVALID_ENUM`".

    Design: Corner/entities/server_invalid_enum_training_provider_rejected
    """
    app = fixtures.create_application(api)
    payload = create_server_payload(app["id"], training_provider="BOGUS")
    resp = api.create_server(payload, APPLICANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_servers_filtered_by_application_id(api):
    """PRD §3.2: "the applicant attaches the three mandatory document types, each
    referencing its owning application by `application_id`".
    PRD §3.2: "A newly added server is `PENDING`."

    Design: Corner/endpoints/servers_reverse_lookup_by_application
    """
    app = fixtures.create_application(api)
    server = fixtures.add_server(api, app["id"])
    resp = api.list_servers(CLERK, params={"application_id": app["id"]})
    data, _meta = validate_paginated(resp)
    match = [s for s in data if s["id"] == server["id"]]
    assert match, f"server {server['id']} not returned for application {app['id']}"
    assert match[0]["status"] == "PENDING"


def test_verify_already_verified_server_rejected(api):
    """PRD §3.4: "The server must currently be `PENDING` (else `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/verify_already_verified_rejected
    """
    app = fixtures.create_application(api)
    server = fixtures.add_server(api, app["id"])
    validate_success(api.verify_server(server["id"], CLERK))
    resp = api.verify_server(server["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
