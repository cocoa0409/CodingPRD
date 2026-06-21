"""Session scheduling guards: provider double-booking under half-open interval
semantics, the client 15-minute buffer, the authorization window, and the
credential-mismatch-vs-double-booked priority pair."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_rbt_headers,
    make_bcba_headers,
    setup_active_authorization,
    create_finalized_evaluation,
    create_approved_plan,
    create_client,
    create_rbt,
    schedule_session,
    factories,
)


# ─── Difficulty: provider double-booked, half-open intervals ─────────────────

def test_overlapping_session_same_provider_rejected(api):
    """PRD §3.6: "if the provider already has a `SCHEDULED` or `DELIVERED` session
    whose interval overlaps the new half-open `[scheduled_start, scheduled_end)`
    interval, the request is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_halfopen_adjacent_allowed
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-10-01T09:00:00Z",
                     scheduled_end="2026-10-01T11:00:00Z", scheduled_units=8)
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], sc["rbt"]["id"],
            scheduled_start="2026-10-01T10:00:00Z",
            scheduled_end="2026-10-01T11:00:00Z", scheduled_units=4,
        ),
        make_rbt_headers(sc["rbt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED.value, 409)


def test_adjacent_session_same_provider_different_client_accepted(api):
    """PRD §3.6: "the interval treated as the half-open range from start up to but
    not including end".

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_halfopen_adjacent_allowed
    """
    # First client/authorization with the 09:00-11:00 session.
    sc = setup_active_authorization(api, authorized_direct_units=100)
    rbt_id = sc["rbt"]["id"]
    schedule_session(api, sc["authorization"]["id"], rbt_id, "RBT",
                     scheduled_start="2026-10-01T09:00:00Z",
                     scheduled_end="2026-10-01T11:00:00Z", scheduled_units=8)
    # Second client + plan + authorization so the adjacent session is for a
    # DIFFERENT client (the client-buffer rule must not fire here).
    client2 = create_client(api, insurance_payer_id=sc["payer"]["id"],
                            full_name="Child O2")
    ev2 = create_finalized_evaluation(api, client2["id"], sc["bcba"]["id"], 70)
    plan2 = create_approved_plan(api, client2["id"], ev2["id"], sc["bcba"]["id"])
    auth2 = get_success_data(
        api.create_authorization(
            factories.create_authorization_payload(plan2["id"], sc["payer"]["id"]),
            TEST_USERS["billing_headers"],
        )
    )
    # Adjacent 11:00-12:00 touching at the shared boundary, same RBT.
    resp = api.create_session(
        factories.create_session_payload(
            auth2["id"], rbt_id,
            scheduled_start="2026-10-01T11:00:00Z",
            scheduled_end="2026-10-01T12:00:00Z", scheduled_units=4,
        ),
        make_rbt_headers(rbt_id),
    )
    validate_success(resp, 201)


# ─── Difficulty: client 15-minute buffer ─────────────────────────────────────

def test_client_session_within_buffer_rejected(api):
    """PRD §3.6: "if the client has any `SCHEDULED` or `DELIVERED` session within
    fifteen minutes of the new interval (a buffered overlap extending the conflict
    window by a quarter hour on each side), the request is rejected with
    `ERR_CLIENT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/client_buffer_conflict_fifteen_minute_gap_required
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    rbt1_id = sc["rbt"]["id"]
    rbt2 = create_rbt(api, supervising_bcba_id=sc["bcba"]["id"],
                      full_name="RBT Buffer B")
    schedule_session(api, sc["authorization"]["id"], rbt1_id, "RBT",
                     scheduled_start="2026-11-01T09:00:00Z",
                     scheduled_end="2026-11-01T11:00:00Z", scheduled_units=8)
    # Same client, different provider, adjacent 11:00-12:00 within 15-min buffer.
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], rbt2["id"],
            scheduled_start="2026-11-01T11:00:00Z",
            scheduled_end="2026-11-01T12:00:00Z", scheduled_units=4,
        ),
        make_rbt_headers(rbt2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_BUFFER_CONFLICT.value, 409)


def test_client_session_after_buffer_gap_accepted(api):
    """PRD §3.6: "if the client has any `SCHEDULED` or `DELIVERED` session within
    fifteen minutes of the new interval (a buffered overlap extending the conflict
    window by a quarter hour on each side), the request is rejected with
    `ERR_CLIENT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/client_buffer_conflict_fifteen_minute_gap_required
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    rbt1_id = sc["rbt"]["id"]
    rbt2 = create_rbt(api, supervising_bcba_id=sc["bcba"]["id"],
                      full_name="RBT Buffer B")
    schedule_session(api, sc["authorization"]["id"], rbt1_id, "RBT",
                     scheduled_start="2026-11-01T09:00:00Z",
                     scheduled_end="2026-11-01T11:00:00Z", scheduled_units=8)
    # Same client, starting 11:15 (>= 15-minute gap) is accepted.
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], rbt2["id"],
            scheduled_start="2026-11-01T11:15:00Z",
            scheduled_end="2026-11-01T12:15:00Z", scheduled_units=4,
        ),
        make_rbt_headers(rbt2["id"]),
    )
    validate_success(resp, 201)


# ─── Difficulty: credential mismatch beats double-booked (priority pair) ─────

def test_credential_mismatch_reported_over_double_booked(api):
    """PRD §3.6: "The provider's `credential` must match the `service_line`:
    direct therapy must be scheduled to an `RBT`, while supervision and parent
    training must be scheduled to a `BCBA`; a mismatch is rejected with
    `ERR_CREDENTIAL_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/credential_mismatch_beats_double_booked_on_session_create
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    rbt_id = sc["rbt"]["id"]
    schedule_session(api, sc["authorization"]["id"], rbt_id, "RBT",
                     scheduled_start="2026-06-01T09:00:00Z",
                     scheduled_end="2026-06-01T11:00:00Z", scheduled_units=8)
    # Same RBT, SUPERVISION line (RBT cannot do supervision) AND overlapping time.
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], rbt_id, service_line="SUPERVISION",
            scheduled_start="2026-06-01T10:00:00Z",
            scheduled_end="2026-06-01T11:00:00Z", scheduled_units=4,
        ),
        make_rbt_headers(rbt_id),
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISMATCH.value, 409)


def test_credential_mismatch_alone_rejected_on_supervision_to_rbt(api):
    """PRD §3.6: "The provider's `credential` must match the `service_line`:
    direct therapy must be scheduled to an `RBT`, while supervision and parent
    training must be scheduled to a `BCBA`; a mismatch is rejected with
    `ERR_CREDENTIAL_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/credential_mismatch_beats_double_booked_on_session_create
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    # SUPERVISION scheduled to an RBT, no time conflict — isolates the credential rule.
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], sc["rbt"]["id"], service_line="SUPERVISION",
            scheduled_start="2026-06-05T09:00:00Z",
            scheduled_end="2026-06-05T10:00:00Z", scheduled_units=4,
        ),
        make_rbt_headers(sc["rbt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISMATCH.value, 409)


# ─── Corner: outside authorization window ────────────────────────────────────

def test_session_outside_window_rejected(api):
    """PRD §3.6: "The session date must fall within the authorization window — the
    date of `scheduled_start` must be on or after `period_start` and on or before
    `period_end` — or the request is rejected with `ERR_OUTSIDE_AUTH_WINDOW`."

    Design: Corner/validations/session_outside_authorization_window_rejected
    """
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    period_end="2026-01-31")
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], sc["rbt"]["id"],
            scheduled_start="2026-03-01T09:00:00Z",
            scheduled_end="2026-03-01T11:00:00Z", scheduled_units=8,
        ),
        make_rbt_headers(sc["rbt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_AUTH_WINDOW.value, 409)
