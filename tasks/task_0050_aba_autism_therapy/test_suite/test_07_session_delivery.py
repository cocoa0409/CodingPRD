"""Session delivery validity: delivered-units range and the already-delivered
terminal-state guard."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    make_rbt_headers,
    setup_active_authorization,
    setup_delivered_direct_session,
    schedule_session,
)


def test_deliver_zero_units_rejected(api):
    """PRD §3.7: "The deliver request supplies `delivered_units`, the actual units
    rendered, which must be greater than zero and no greater than the session's
    `scheduled_units`; a value outside that range is rejected with
    `ERR_DELIVERED_UNITS_INVALID`."

    Design: Corner/validations/delivered_units_zero_rejected
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_units=8)
    resp = api.deliver_session(session["id"], 0, make_rbt_headers(sc["rbt"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DELIVERED_UNITS_INVALID.value, 422)


def test_deliver_already_delivered_session_rejected(api):
    """PRD §3.10: "a request to drive a transition that the resource's current
    state does not permit is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deliver_already_delivered_session_returns_invalid_state
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=8,
                                        authorized_direct_units=100)
    resp = api.deliver_session(sc["session"]["id"], 8,
                               make_rbt_headers(sc["rbt"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
