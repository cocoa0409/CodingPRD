"""Violation review lifecycle and adverse-conditions claim adjudication (PRD §3.9, §3.10).

Covers difficulty non_linear_state_machine (cyclic acknowledge/reopen) and
resource_temporal_overlap (strict event ordering), plus corner state_machines instances.
"""
from test_helpers import fixtures, factories
from test_helpers.test_users import make_driver_headers, TEST_USERS
from test_helpers import validate_success, validate_error


ADMIN = TEST_USERS["carrier_admin_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]


# =====================================================================
# Difficulty / non_linear_state_machine — cyclic acknowledge -> reopen loop
# =====================================================================
def test_violation_acknowledge_then_reopen_returns_to_open(api):
    """PRD §3.10: "Acknowledging an open violation transitions it OPEN → ACKNOWLEDGED and
    bumps its version; it is permitted only from OPEN".
    PRD §3.10: "An acknowledged violation may be re-opened, transitioning ACKNOWLEDGED → OPEN
    and bumping its version, permitted only from ACKNOWLEDGED".

    Design: Difficulty/non_linear_state_machine/hosviolation_cyclic_acknowledge_reopen_loop
    """
    setup = fixtures.setup_driving_11h_violation()
    v_id = setup["violation"]["id"]

    acked = fixtures.acknowledge_violation(v_id)
    assert acked["status"] == "ACKNOWLEDGED"

    reopened = fixtures.reopen_violation(v_id)
    assert reopened["status"] == "OPEN", "cyclic: returned to a prior state"


def test_violation_reopen_after_acknowledge_increments_version(api):
    """PRD §3.10: "An acknowledged violation may be re-opened, transitioning ACKNOWLEDGED → OPEN
    and bumping its version, permitted only from ACKNOWLEDGED".

    Design: Difficulty/non_linear_state_machine/hosviolation_cyclic_acknowledge_reopen_loop
    """
    setup = fixtures.setup_driving_11h_violation()
    v_id = setup["violation"]["id"]
    acked = fixtures.acknowledge_violation(v_id)
    reopened = fixtures.reopen_violation(v_id)
    assert reopened["status"] == "OPEN"
    assert reopened["version"] == acked["version"] + 1, (
        f"reopen bumps version: {acked['version']} -> {acked['version'] + 1}, got {reopened['version']}"
    )


# =====================================================================
# Difficulty / resource_temporal_overlap — strict event ordering
# =====================================================================
def test_event_time_equal_to_latest_rejected(api):
    """PRD §3.3: "The event_time must be strictly greater than the event_time of the latest
    surviving event for this driver — events arrive in strictly increasing time order — and an
    event_time that is not strictly later is rejected with ERR_EVENT_OUT_OF_ORDER."

    Design: Difficulty/resource_temporal_overlap/duty_event_strict_ordering_rejects_non_increasing_time
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")

    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T10:00:00Z", v)
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_EVENT_OUT_OF_ORDER")


def test_event_time_before_latest_rejected(api):
    """PRD §3.3: "The event_time must be strictly greater than the event_time of the latest
    surviving event for this driver ... an event_time that is not strictly later is rejected
    with ERR_EVENT_OUT_OF_ORDER."

    Design: Difficulty/resource_temporal_overlap/duty_event_strict_ordering_rejects_non_increasing_time
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")

    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T09:00:00Z", v)
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_EVENT_OUT_OF_ORDER")


# =====================================================================
# Corner / state_machines — violation + claim transitions
# =====================================================================
def test_acknowledge_already_acknowledged_violation_invalid_state(api):
    """PRD §3.10: "Acknowledging an open violation transitions it OPEN → ACKNOWLEDGED and
    bumps its version; it is permitted only from OPEN, otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/acknowledge_violation_from_already_acknowledged_returns_invalid_state
    """
    setup = fixtures.setup_driving_11h_violation()
    v_id = setup["violation"]["id"]
    fixtures.acknowledge_violation(v_id)

    resp = api.acknowledge_violation(v_id, OFFICER)
    validate_error(resp, "ERR_INVALID_STATE")
    after = fixtures.get_violation(v_id)
    assert after["status"] == "ACKNOWLEDGED"


def test_resolve_open_violation_without_acknowledge_invalid_state(api):
    """PRD §3.10: "Resolving a violation transitions it ACKNOWLEDGED → RESOLVED, stores the
    supplied resolution_note, and bumps its version; it is permitted only from ACKNOWLEDGED
    (else ERR_INVALID_STATE)".

    Design: Corner/state_machines/resolve_open_violation_without_acknowledge_returns_invalid_state
    """
    setup = fixtures.setup_driving_11h_violation()
    v_id = setup["violation"]["id"]
    resp = api.resolve_violation(v_id, factories.resolve_violation_payload("Driver retrained."), OFFICER)
    validate_error(resp, "ERR_INVALID_STATE")
    after = fixtures.get_violation(v_id)
    assert after["status"] == "OPEN"


def test_reject_adverse_claim_then_approve_invalid_state(api):
    """PRD §3.9: "Approving a claim is the consequential branch. It requires the claim still
    be PENDING, otherwise ERR_INVALID_STATE".
    PRD §3.9: "Rejecting a claim is the inert branch: it requires the claim be PENDING (else
    ERR_INVALID_STATE), moves it PENDING → REJECTED".

    Design: Corner/state_machines/reject_adverse_claim_then_approve_returns_invalid_state
    """
    driver = fixtures.create_driver()
    claim = fixtures.file_adverse_claim(driver["id"], "2026-06-01", reason="TRAFFIC_INCIDENT",
                                        narrative="Multi-car pileup ahead.")
    rejected = fixtures.reject_adverse_claim(claim["id"])
    assert rejected["status"] == "REJECTED"

    resp = api.approve_adverse_claim(claim["id"], factories.approve_claim_payload(rejected["version"]), OFFICER)
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_adverse_claim(claim["id"], OFFICER), 200)
    assert after["status"] == "REJECTED"
