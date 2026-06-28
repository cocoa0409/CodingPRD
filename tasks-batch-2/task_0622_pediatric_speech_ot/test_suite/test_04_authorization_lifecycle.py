"""Authorization lifecycle: the reauthorization cycle, closing, optimistic
concurrency control, and clock-driven expiry.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, set_clock, create_child, create_authorization,
    setup_exhausted_authorization, setup_reauth_requested,
    get_authorization, request_reauth,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_close_authorization_with_outstanding_reservation_rejected(api):
    """PRD §3.4: "A `ClinicAdmin` closes an authorization that is `EXPIRED` or
    `EXHAUSTED` (otherwise `ERR_AUTH_NOT_CLOSEABLE`), but only when
    `reserved_visits` is 0 — that is, when there are no outstanding `SCHEDULED`
    appointments holding visits against it (otherwise
    `ERR_OUTSTANDING_RESERVATIONS`)."

    Design: Corner/state_machines/close_authorization_with_outstanding_reservation_rejected
    """
    ctx, appt = setup_exhausted_authorization()
    # authorized_visits=1 fully reserved -> EXHAUSTED with reserved_visits=1.
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["status"] == "EXHAUSTED"
    assert auth["reserved_visits"] == 1
    res = api.close_authorization(ctx["auth"]["id"], ADMIN)
    validate_error(res, "ERR_OUTSTANDING_RESERVATIONS")


def test_reauth_grant_replenishes_cap_and_returns_active(api):
    """PRD §3.4: "Granting adds `additional_visits` to `authorized_visits`, sets
    `valid_until` to `new_valid_until`, and recomputes `available_visits` as the
    new `authorized_visits` minus `reserved_visits` minus `committed_visits`; if
    that recomputed balance is above 0 the authorization returns to `ACTIVE`,
    closing the cycle."

    Design: Corner/state_machines/reauth_grant_replenishes_and_returns_active
    """
    set_clock("2026-06-20T12:00:00Z")
    # Build authorized_visits=1 fully committed: book then complete one visit.
    from test_helpers import (create_therapist, create_finalized_evaluation,
                              create_active_plan, book_appointment_ok, complete_appointment)
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=1)
    ctx = {"child": child, "therapist": th, "auth": auth, "plan": plan}
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(appt["id"], th["id"]))

    auth_now = get_authorization(auth["id"])
    assert auth_now["committed_visits"] == 1
    assert auth_now["available_visits"] == 0
    requested = request_reauth(auth["id"], auth_now["version"])
    assert requested["status"] == "REAUTH_REQUESTED"

    res = api.grant_reauth(
        auth["id"],
        {"additional_visits": 4, "new_valid_until": "2026-12-01T00:00:00Z",
         "expected_authorization_version": requested["version"]},
        ADMIN)
    granted = validate_success(res, 200)
    assert granted["status"] == "ACTIVE", granted
    assert granted["authorized_visits"] == 5, granted
    assert granted["committed_visits"] == 1, granted
    assert granted["available_visits"] == 4, granted


def test_grant_reauth_with_stale_version_rejected(api):
    """PRD §2.9: "The server compares it against the authorization's current
    `version`. If another writer has advanced the authorization's `version` since
    the client last read it ... the supplied `expected_authorization_version` will
    not match, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_grant_reauth_stale_version_rejected
    """
    ctx, appt = setup_exhausted_authorization()
    auth = get_authorization(ctx["auth"]["id"])
    requested = request_reauth(auth["id"], auth["version"])
    stale = requested["version"] - 1
    res = api.grant_reauth(
        auth["id"],
        {"additional_visits": 3, "new_valid_until": "2026-12-01T00:00:00Z",
         "expected_authorization_version": stale},
        ADMIN)
    validate_error(res, "ERR_STALE_VERSION")
    assert get_authorization(auth["id"])["status"] == "REAUTH_REQUESTED"


def test_request_reauth_with_stale_version_rejected(api):
    """PRD §2.9: "A request to request reauthorization and a request to grant
    reauthorization must each carry `expected_authorization_version`". PRD §2.9:
    "the supplied `expected_authorization_version` will not match, and the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_request_reauth_stale_version_rejected
    """
    from test_helpers import (create_therapist, create_finalized_evaluation,
                              create_active_plan, book_appointment_ok)
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3)
    ctx = {"child": child, "therapist": th, "auth": auth, "plan": plan}
    # Booking bumps the authorization version; the client's pre-booking view is stale.
    book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    current = get_authorization(auth["id"])["version"]
    res = api.request_reauth(
        auth["id"], {"expected_authorization_version": current - 1}, ADMIN)
    validate_error(res, "ERR_STALE_VERSION")
    assert get_authorization(auth["id"])["status"] == "ACTIVE"


def test_grant_reauth_with_correct_version_succeeds(api):
    """PRD §2.4: "reserving, releasing, committing, requesting reauth, and granting
    reauth each increment the authorization's `version`." PRD §3.4: "Granting adds
    `additional_visits` to `authorized_visits` ... if that recomputed balance is
    above 0 the authorization returns to `ACTIVE`, closing the cycle."

    Design: Corner/cross_cutting_complexity_layers/occ_grant_reauth_correct_version_succeeds
    """
    child, requested, fresh_version = setup_reauth_requested(authorized_visits=2)
    auth_id = requested["id"]
    res = api.grant_reauth(
        auth_id,
        {"additional_visits": 3, "new_valid_until": "2026-12-01T00:00:00Z",
         "expected_authorization_version": fresh_version},
        ADMIN)
    granted = validate_success(res, 200)
    assert granted["status"] == "ACTIVE", granted
    assert granted["authorized_visits"] == 5, granted
    assert granted["available_visits"] == 5, granted


def test_clock_set_to_valid_until_expires_authorization(api):
    """PRD §3.4: "Expiry is driven by the clock: when the logical clock reaches
    `valid_until`, an `ACTIVE` authorization automatically transitions to
    `EXPIRED`, after which no new reservation may draw on it."

    Design: Corner/cross_cutting_complexity_layers/clock_expires_authorization_threshold
    """
    set_clock("2026-06-05T12:00:00Z")
    child = create_child()
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3,
                                valid_from="2026-06-01T00:00:00Z",
                                valid_until="2026-06-15T00:00:00Z")
    res = api.set_clock("2026-06-15T00:00:00Z", ADMIN)
    validate_success(res, 200)
    assert get_authorization(auth["id"])["status"] == "EXPIRED"
