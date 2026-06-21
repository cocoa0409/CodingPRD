"""Device commands: the delinquency guard, closed-interval window overlap, and the
referential-beats-temporal precedence after reinstatement.

Also covers the half-open RepossessionAssignment adjacency rule (opposite endpoint
treatment from the closed-interval device rule)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
    setup_delinquent_loan,
    setup_defaulted_loan,
    install_device,
    set_clock,
    create_device_command_payload,
    create_payment_payload,
    create_assignment_payload,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]
_RECOVERY = TEST_USERS["recovery_manager_headers"]


def _cmd(command_type, start, end):
    return create_device_command_payload(command_type, start, end)


# ─────────────────────────────────────────────────────────────────────────
# Cross-entity state dependency: STARTER_DISABLE requires loan DELINQUENT/DEFAULT
# ─────────────────────────────────────────────────────────────────────────
def test_device_disable_requires_loan_delinquent_or_default(api):
    """PRD §3.6: "A STARTER_DISABLE command requires that the device's starter_state is
    ENABLED, that the vehicle's active loan — the single loan whose vehicle_id matches
    the device's vehicle_id and whose payoff_status is OUTSTANDING — has a
    delinquency_status of either DELINQUENT or DEFAULT (otherwise rejected with
    ERR_DEVICE_LOAN_NOT_DELINQUENT)".

    Design: Difficulty/cross_entity_state_dependency/device_disable_requires_loan_delinquent_or_default
    """
    ctx = setup_originated_loan()  # delinquency_status CURRENT
    device = install_device(ctx["vehicle"]["id"])
    res = api.create_device_command(
        device["id"], _cmd("STARTER_DISABLE", "2026-01-02T00:00:00.000Z", "2026-01-09T00:00:00.000Z"),
        _SERVICER)
    validate_error(res, "ERR_DEVICE_LOAN_NOT_DELINQUENT")


def test_device_disable_on_current_loan_rejected_even_with_clear_window(api):
    """PRD §3.6: "the vehicle's active loan ... has a delinquency_status of either
    DELINQUENT or DEFAULT (otherwise rejected with ERR_DEVICE_LOAN_NOT_DELINQUENT)".

    Design: Difficulty/cross_entity_state_dependency/device_disable_requires_loan_delinquent_or_default
    """
    ctx = setup_originated_loan()
    device = install_device(ctx["vehicle"]["id"])
    res = api.create_device_command(
        device["id"], _cmd("STARTER_DISABLE", "2026-02-01T00:00:00.000Z", "2026-02-02T00:00:00.000Z"),
        _SERVICER)
    validate_error(res, "ERR_DEVICE_LOAN_NOT_DELINQUENT")


# ─────────────────────────────────────────────────────────────────────────
# Closed-interval overlap: adjacency touch counts as overlap
# ─────────────────────────────────────────────────────────────────────────
def test_device_command_closed_interval_adjacency_overlaps(api):
    """PRD §3.6: "Window overlap is evaluated on closed intervals, so two windows that
    merely touch at an endpoint count as overlapping; a collision is rejected with
    ERR_COMMAND_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/device_command_closed_interval_adjacency_overlaps
    """
    # Reach DELINQUENT with a device so STARTER_DISABLE is permitted; the assessment
    # cascade issues a zero-length DISABLE at the past-due clock and DISABLES the device.
    ctx = setup_delinquent_loan(install_dev=True)
    device_id = ctx["device"]["id"]
    # Re-ENABLE (cascade left it DISABLED with count 1).
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_ENABLE", "2026-03-15T00:00:00.000Z", "2026-03-15T00:00:00.000Z"),
        _SERVICER), 201)
    # Manual STARTER_DISABLE [03-25 .. 04-01], then re-ENABLE.
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-03-25T00:00:00.000Z", "2026-04-01T00:00:00.000Z"),
        _SERVICER), 201)
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_ENABLE", "2026-03-25T00:00:00.000Z", "2026-03-25T00:00:00.000Z"),
        _SERVICER), 201)
    # New STARTER_DISABLE [04-01 .. 04-08] touches the prior window's end 04-01.
    res = api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-04-01T00:00:00.000Z", "2026-04-08T00:00:00.000Z"),
        _SERVICER)
    validate_error(res, "ERR_COMMAND_WINDOW_OVERLAP")


def test_device_command_disjoint_window_after_disable_accepted(api):
    """PRD §3.6: "that the requested closed window from `effective_start` to
    `effective_end` does not overlap any existing `ISSUED` `STARTER_DISABLE` window on
    the same device."
    PRD §3.6: "A successful public `STARTER_DISABLE` advances the device `ENABLED →
    DISABLED`, increases `active_disable_count` by 1, and increments the device's
    `version`."
    A second STARTER_DISABLE whose closed window starts strictly after the prior window's
    end (no shared endpoint) does not collide and is accepted.

    Design: Difficulty/resource_temporal_overlap/device_command_closed_interval_adjacency_overlaps
    """
    ctx = setup_delinquent_loan(install_dev=True)
    device_id = ctx["device"]["id"]
    # Re-ENABLE after the assessment cascade left the device DISABLED.
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_ENABLE", "2026-03-15T00:00:00.000Z", "2026-03-15T00:00:00.000Z"),
        _SERVICER), 201)
    # Manual STARTER_DISABLE [03-25 .. 04-01], then re-ENABLE.
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-03-25T00:00:00.000Z", "2026-04-01T00:00:00.000Z"),
        _SERVICER), 201)
    validate_success(api.create_device_command(
        device_id, _cmd("STARTER_ENABLE", "2026-03-25T00:00:00.000Z", "2026-03-25T00:00:00.000Z"),
        _SERVICER), 201)
    # A disjoint window [04-02 .. 04-08] (one day past the prior end) shares no endpoint.
    ok = validate_success(api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-04-02T00:00:00.000Z", "2026-04-08T00:00:00.000Z"),
        _SERVICER), 201)
    assert ok["command_type"] == "STARTER_DISABLE"


# ─────────────────────────────────────────────────────────────────────────
# Priority pair: REFERENTIAL (p10) beats TEMPORAL/window-overlap (p15)
# ─────────────────────────────────────────────────────────────────────────
def test_referential_beats_temporal_on_disable_after_reinstatement(api):
    """PRD §3.6: "A STARTER_DISABLE command requires that the device's starter_state is
    ENABLED, that the vehicle's active loan ... has a delinquency_status of either
    DELINQUENT or DEFAULT (otherwise rejected with ERR_DEVICE_LOAN_NOT_DELINQUENT), and
    that the requested closed window from effective_start to effective_end does not
    overlap any existing ISSUED STARTER_DISABLE window on the same device." (the
    delinquency guard is listed before the window-overlap guard)

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_disable_after_reinstatement
    """
    # DELINQUENT loan, device; reinstate so loan is CURRENT again. The prior cascade
    # STARTER_DISABLE (zero-length at 03-15) remains ISSUED.
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    device_id = ctx["device"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(434236, "REINSTATEMENT"), _SERVICER), 201)
    # A new STARTER_DISABLE that BOTH targets a now-CURRENT loan AND overlaps the
    # still-ISSUED 03-15 window must report the referential error, not the overlap error.
    res = api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-03-14T00:00:00.000Z", "2026-03-16T00:00:00.000Z"),
        _SERVICER)
    validate_error(res, "ERR_DEVICE_LOAN_NOT_DELINQUENT")


def test_referential_guard_precedes_overlap_not_reported_as_overlap(api):
    """PRD §3.6: "A STARTER_DISABLE command requires that the device's starter_state is
    ENABLED, that the vehicle's active loan ... has a delinquency_status of either
    DELINQUENT or DEFAULT (otherwise rejected with ERR_DEVICE_LOAN_NOT_DELINQUENT), and
    that the requested closed window from effective_start to effective_end does not
    overlap any existing ISSUED STARTER_DISABLE window on the same device."

    When the loan is CURRENT (reinstated) the referential guard fails first, so a
    window that also overlaps the still-ISSUED prior disable is NOT reported as the
    overlap error.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_disable_after_reinstatement
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    device_id = ctx["device"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(434236, "REINSTATEMENT"), _SERVICER), 201)
    res = api.create_device_command(
        device_id, _cmd("STARTER_DISABLE", "2026-03-14T00:00:00.000Z", "2026-03-16T00:00:00.000Z"),
        _SERVICER)
    # The referential guard precedes the window-overlap guard, so the reported error
    # is the referential one, never the overlap one.
    validate_error(res, "ERR_DEVICE_LOAN_NOT_DELINQUENT")


# ─────────────────────────────────────────────────────────────────────────
# Half-open assignment overlap: adjacency allowed, true overlap rejected
# ─────────────────────────────────────────────────────────────────────────
def test_assignment_half_open_adjacency_allowed(api):
    """PRD §3.9: "because the interval is half-open, two windows that merely touch at an
    endpoint are allowed (the adjacency does not count as overlap)".

    Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_defaulted_loan(install_dev=True)
    repo_id = ctx["repo_order"]["id"]
    validate_success(api.create_assignment(
        repo_id, create_assignment_payload("Agent D", "2026-03-16T08:00:00.000Z",
                                           "2026-03-16T12:00:00.000Z"), _RECOVERY), 201)
    # Adjacent window whose start == prior window's end is allowed.
    validate_success(api.create_assignment(
        repo_id, create_assignment_payload("Agent E", "2026-03-16T12:00:00.000Z",
                                           "2026-03-16T16:00:00.000Z"), _RECOVERY), 201)


def test_assignment_true_overlap_rejected(api):
    """PRD §3.9: "An assignment window must not overlap another assignment window on the
    same order ... but any true overlap is rejected with ERR_ASSIGNMENT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_defaulted_loan(install_dev=True)
    repo_id = ctx["repo_order"]["id"]
    validate_success(api.create_assignment(
        repo_id, create_assignment_payload("Agent D", "2026-03-16T08:00:00.000Z",
                                           "2026-03-16T12:00:00.000Z"), _RECOVERY), 201)
    res = api.create_assignment(
        repo_id, create_assignment_payload("Agent F", "2026-03-16T10:00:00.000Z",
                                           "2026-03-16T14:00:00.000Z"), _RECOVERY)
    validate_error(res, "ERR_ASSIGNMENT_WINDOW_OVERLAP")
