"""Exchange terminal-state lifecycle: completion guards, failure, and termination
preconditions.

Translates corner sections state_machines (terminal lockdown) and errors
(terminate with funded trust).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    make_qi_coordinator_headers,
    setup_closed_exchange, setup_failed_exchange,
    set_clock,
)


def test_complete_from_terminal_failed_rejected(api):
    """PRD §3.7: "a completion from any posture other than `IDENTIFIED` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_from_terminal_failed_returns_invalid_state
    """
    exchange, trust = setup_failed_exchange("coord-trm")
    headers = make_qi_coordinator_headers("coord-trm")
    assert exchange["status"] == "FAILED"
    resp = api.complete_exchange(exchange["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_exchange(exchange["id"], headers))
    assert after["status"] == "FAILED", "FAILED exchange stays FAILED"


def test_fail_after_180day_lapse_locks_trust(api):
    """PRD §3.7: "Failing recomputes the posture to `FAILED`, locks the trust (the
    cascade from exchange fail to trust lock), sets the exchange `status` to `FAILED`,
    and increments the exchange's `version`."

    Design: Corner/state_machines/complete_from_terminal_failed_returns_invalid_state
    """
    exchange, trust = setup_failed_exchange("coord-fail2")
    headers = make_qi_coordinator_headers("coord-fail2")
    assert exchange["compliance_posture"] == "FAILED"
    trust_after = validate_success(api.list_trust(exchange["id"], headers))[0]
    assert trust_after["is_locked"] is True, "failing the exchange must lock the trust"


def test_terminate_exchange_with_funded_trust_rejected(api):
    """PRD §3.7: "Termination is permitted only while the exchange is in `DRAFT` status
    and only when no qualified trust on the exchange holds a positive
    `available_balance`."

    Design: Corner/errors/terminate_exchange_with_funded_trust_invalid_state
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-tf")
    headers = make_qi_coordinator_headers("coord-tf")
    # After close the exchange is ACTIVE (not DRAFT) and the trust holds 350000.
    resp = api.terminate_exchange(closed["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_exchange(closed["id"], headers))
    assert after["status"] == "ACTIVE", "an ACTIVE exchange with funded trust cannot be terminated"
