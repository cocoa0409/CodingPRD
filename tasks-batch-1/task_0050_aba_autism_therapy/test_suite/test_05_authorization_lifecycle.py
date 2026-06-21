"""Authorization lifecycle: closing cascades cancellations and frees pools,
renewal makes the predecessor non-deliverable, the close pre-condition, and the
optimistic-concurrency stale-version guard on renew."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    make_rbt_headers,
    setup_active_authorization,
    schedule_session,
    get_authorization,
    factories,
)


def _set_clock(api, instant):
    get_success_data(api.set_clock(instant, TEST_USERS["billing_headers"]))


# ─── Difficulty: close cascades cancel session then frees pool (depth 3) ─────

def test_close_expires_authorization_and_cancels_scheduled_session(api):
    """PRD §3.4: "A successful close moves the authorization from `ACTIVE` to
    `EXPIRED` and cascades through its still-scheduled sessions, cancelling each
    one and freeing the reservation those sessions held."

    Design: Difficulty/transitive_cascade/close_authorization_cascades_cancel_session_then_frees_pool_depth3
    """
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    period_end="2026-01-31")
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_start="2026-01-20T09:00:00Z",
                               scheduled_end="2026-01-20T11:00:00Z",
                               scheduled_units=8)
    _set_clock(api, "2026-02-05T00:00:00Z")
    closed = get_success_data(
        api.close_authorization(sc["authorization"]["id"],
                                TEST_USERS["billing_headers"])
    )
    assert closed["status"] == "EXPIRED", closed["status"]
    sess = get_success_data(
        api.get_session(session["id"], TEST_USERS["billing_headers"])
    )
    assert sess["status"] == "CANCELLED", sess["status"]


def test_close_cascade_releases_reserved_units_back_to_pool(api):
    """PRD §3.4: "A successful close moves the authorization from `ACTIVE` to
    `EXPIRED` and cascades through its still-scheduled sessions, cancelling each
    one and freeing the reservation those sessions held."

    Design: Difficulty/transitive_cascade/close_authorization_cascades_cancel_session_then_frees_pool_depth3
    """
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    period_end="2026-01-31")
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-01-20T09:00:00Z",
                     scheduled_end="2026-01-20T11:00:00Z", scheduled_units=8)
    _set_clock(api, "2026-02-05T00:00:00Z")
    get_success_data(
        api.close_authorization(sc["authorization"]["id"],
                                TEST_USERS["billing_headers"])
    )
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 0, auth["reserved_direct_units"]
    assert auth["remaining_direct_units"] == 100, auth["remaining_direct_units"]


# ─── Difficulty: deliver requires ACTIVE/EXHAUSTED authorization ─────────────

def test_renew_leaves_predecessor_session_scheduled(api):
    """PRD §3.5: "the predecessor moves from `ACTIVE` to the terminal `RENEWED`
    state".

    Design: Difficulty/cross_entity_state_dependency/session_deliver_requires_active_authorization
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_start="2026-06-20T09:00:00Z",
                               scheduled_end="2026-06-20T11:00:00Z",
                               scheduled_units=8)
    auth = get_authorization(api, sc["authorization"]["id"])
    get_success_data(
        api.renew_authorization(
            sc["authorization"]["id"],
            factories.renew_authorization_payload(auth["version"]),
            TEST_USERS["billing_headers"],
        )
    )
    auth_after = get_authorization(api, sc["authorization"]["id"])
    assert auth_after["status"] == "RENEWED", auth_after["status"]
    sess = get_success_data(
        api.get_session(session["id"], TEST_USERS["billing_headers"])
    )
    assert sess["status"] == "SCHEDULED", (
        f"renew must not cascade-cancel sessions, got {sess['status']}"
    )


def test_deliver_against_renewed_authorization_rejected(api):
    """PRD §3.7: "Delivery is allowed only while the owning authorization is
    `ACTIVE` or `EXHAUSTED`; if the authorization has been expired or renewed,
    delivery is rejected with `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/session_deliver_requires_active_authorization
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_start="2026-06-20T09:00:00Z",
                               scheduled_end="2026-06-20T11:00:00Z",
                               scheduled_units=8)
    auth = get_authorization(api, sc["authorization"]["id"])
    get_success_data(
        api.renew_authorization(
            sc["authorization"]["id"],
            factories.renew_authorization_payload(auth["version"]),
            TEST_USERS["billing_headers"],
        )
    )
    resp = api.deliver_session(session["id"], 8, make_rbt_headers(sc["rbt"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_ACTIVE.value, 409)


# ─── Corner: close before period_end rejected ────────────────────────────────

def test_close_before_period_end_returns_not_expirable(api):
    """PRD §3.4: "The close is permitted only when the server's current clock date
    is strictly after `period_end`; if the window has not yet elapsed the close is
    rejected with `ERR_AUTHORIZATION_NOT_EXPIRABLE`."

    Design: Corner/state_machines/close_authorization_before_period_end_returns_not_expirable
    """
    _set_clock(api, "2026-01-15T00:00:00Z")
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    period_end="2026-12-31", with_rbt=False)
    resp = api.close_authorization(sc["authorization"]["id"],
                                   TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_EXPIRABLE.value, 409)


# ─── Corner: OCC stale-version on renew ──────────────────────────────────────

def test_second_renew_with_stale_version_returns_412(api):
    """PRD §2.6: "If they do not match — because some other writer has advanced
    the authorization's version since the client last read it — the renewal is
    rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/errors/renew_with_stale_authorization_version_returns_412
    """
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    with_rbt=False)
    stale_version = sc["authorization"]["version"]
    first = api.renew_authorization(
        sc["authorization"]["id"],
        factories.renew_authorization_payload(stale_version),
        TEST_USERS["billing_headers"],
    )
    validate_success(first, 201)
    resp = api.renew_authorization(
        sc["authorization"]["id"],
        factories.renew_authorization_payload(
            stale_version, authorized_direct_units=50,
            authorized_supervision_units=10, authorized_parent_training_units=4,
            period_start="2028-01-01", period_end="2028-12-31",
        ),
        TEST_USERS["billing_headers"],
    )
    # ERROR PRECEDENCE SILENCE: after the first renew the predecessor is in the
    # terminal RENEWED state (PRD §3.5: "Both EXPIRED and RENEWED are terminal
    # states from which no further transition is possible") AND its version has
    # advanced. PRD §2.6 names ERR_STALE_VERSION for "after the authorization
    # had already been renewed", but nothing in PRD states the version check
    # pre-empts the ACTIVE-precondition state-check path, so a faithful reader
    # could report ERR_INVALID_STATE here. Accept either.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
