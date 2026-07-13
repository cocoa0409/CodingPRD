"""Shutoff notices: issue/rescind/enforce, the SHUTOFF gate on removal, and state/temporal precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories, fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/device_remove_blocked_when_connection_shutoff
# --------------------------------------------------------------------------- #
def test_device_remove_blocked_when_connection_shutoff(api):
    """PRD §3.4: "no device may be removed while its connection's `compliance_posture` is
    `SHUTOFF` (`ERR_CONNECTION_SHUTOFF`)."

    Design: Difficulty/cross_entity_state_dependency/device_remove_blocked_when_connection_shutoff
    """
    conn, dev, _ = fixtures.setup_shutoff_connection(api, ADMIN)
    validate_error(api.remove_device(dev["id"], ADMIN), ApiErrorId.ERR_CONNECTION_SHUTOFF)
    after = validate_success(api.get_device(dev["id"], ADMIN))
    assert after["status"] == "ACTIVE", f"blocked transition leaves device ACTIVE, got {after['status']}"


def test_device_removable_when_connection_not_shutoff(api):
    """PRD §3.4: "Removal takes a device from `ACTIVE` or `NEEDS_REPAIR` to the terminal
    `REMOVED` state, decrements the connection's `protected_device_count`, and recomputes
    posture."

    Design: Difficulty/cross_entity_state_dependency/device_remove_blocked_when_connection_shutoff
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, install_date="2026-01-01T00:00:00Z")
    data = validate_success(api.remove_device(dev["id"], ADMIN))
    assert data["status"] == "REMOVED", \
        f"removal permitted on a non-SHUTOFF connection, got {data['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/open_notice_count_conserved_on_issue_then_rescind
# --------------------------------------------------------------------------- #
def test_open_notice_count_zero_after_issue_then_rescind(api):
    """PRD §3.6: "The notice opens in `ISSUED` status; issuing it increments the
    connection's `open_notice_count` and recomputes posture."
    PRD §3.6: "Rescinding moves the notice `ISSUED → RESCINDED`, decrements
    `open_notice_count`, and recomputes posture".

    Design: Difficulty/compensating_invariant/open_notice_count_conserved_on_issue_then_rescind
    """
    conn = fixtures.create_connection(api, ADMIN)
    notice = fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    data = validate_success(api.rescind_notice(notice["id"], ADMIN))
    assert data["status"] == "RESCINDED", f"got {data['status']}"
    after = validate_success(api.get_connection(conn["id"], ADMIN))
    assert after["open_notice_count"] == 0, \
        f"issue 0->1 then rescind 1->0 conserves the count, got {after['open_notice_count']}"


def test_open_notice_count_one_after_issue(api):
    """PRD §3.6: "The notice opens in `ISSUED` status; issuing it increments the
    connection's `open_notice_count` and recomputes posture."

    Design: Difficulty/compensating_invariant/open_notice_count_conserved_on_issue_then_rescind
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    after = validate_success(api.get_connection(conn["id"], ADMIN))
    assert after["open_notice_count"] == 1, \
        f"issuing raises open_notice_count 0->1, got {after['open_notice_count']}"


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/enforce_rescinded_notice_before_due_state_beats_temporal
# --------------------------------------------------------------------------- #
def test_enforce_rescinded_notice_before_due_returns_not_issued(api):
    """PRD §3.6: "Enforcing a notice is a temporal action: it is permitted only once the
    logical clock has reached the deadline, that is when `current_utc` is on or after the
    notice's `enforcement_due_date` (else `ERR_ENFORCEMENT_NOT_DUE`), and only on a notice
    still in `ISSUED` status (else `ERR_NOTICE_NOT_ISSUED`)."
    PRD §2.10: "A check earlier in this ladder always masks a violation that a later check
    would also have caught."

    Design: Difficulty/priority_pair_validation_conflict/enforce_rescinded_notice_before_due_state_beats_temporal
    """
    conn = fixtures.create_connection(api, ADMIN)
    notice = fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    get_success_data(api.rescind_notice(notice["id"], ADMIN))
    # Clock stays at the 2026-03-01 default, before the 2026-03-31 enforcement_due_date.
    validate_error(api.enforce_notice(notice["id"], ADMIN), ApiErrorId.ERR_NOTICE_NOT_ISSUED)


def test_enforce_issued_notice_before_due_returns_not_due_control(api):
    """PRD §3.6: "Enforcing a notice is a temporal action: it is permitted only once the
    logical clock has reached the deadline, that is when `current_utc` is on or after the
    notice's `enforcement_due_date` (else `ERR_ENFORCEMENT_NOT_DUE`)".

    Design: Difficulty/priority_pair_validation_conflict/enforce_rescinded_notice_before_due_state_beats_temporal
    """
    conn = fixtures.create_connection(api, ADMIN)
    notice = fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    # State precondition satisfied (still ISSUED); only the temporal gate remains -> ENFORCEMENT_NOT_DUE.
    validate_error(api.enforce_notice(notice["id"], ADMIN), ApiErrorId.ERR_ENFORCEMENT_NOT_DUE)


# --------------------------------------------------------------------------- #
# Corner/validations/enforce_issued_notice_before_due_returns_not_due
# --------------------------------------------------------------------------- #
def test_enforce_issued_notice_before_due_returns_not_due(api):
    """PRD §3.6: "Enforcing a notice is a temporal action: it is permitted only once the
    logical clock has reached the deadline, that is when `current_utc` is on or after the
    notice's `enforcement_due_date` (else `ERR_ENFORCEMENT_NOT_DUE`)".

    Design: Corner/validations/enforce_issued_notice_before_due_returns_not_due
    """
    conn = fixtures.create_connection(api, ADMIN)
    notice = fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    validate_error(api.enforce_notice(notice["id"], ADMIN), ApiErrorId.ERR_ENFORCEMENT_NOT_DUE)


# --------------------------------------------------------------------------- #
# Corner/state_machines/rescind_already_rescinded_notice_returns_not_issued
# --------------------------------------------------------------------------- #
def test_rescind_already_rescinded_notice_returns_not_issued(api):
    """PRD §3.6: "rescinding a notice not in `ISSUED` status returns `ERR_NOTICE_NOT_ISSUED`."

    Design: Corner/state_machines/rescind_already_rescinded_notice_returns_not_issued
    """
    conn = fixtures.create_connection(api, ADMIN)
    notice = fixtures.issue_notice(conn["id"], "OVERDUE_TEST", api, ADMIN)
    get_success_data(api.rescind_notice(notice["id"], ADMIN))
    validate_error(api.rescind_notice(notice["id"], ADMIN), ApiErrorId.ERR_NOTICE_NOT_ISSUED)


# --------------------------------------------------------------------------- #
# Corner/validations/remove_already_removed_device_returns_not_removable
# --------------------------------------------------------------------------- #
def test_remove_already_removed_device_returns_not_removable(api):
    """PRD §3.4: "a device whose status is neither `ACTIVE` nor `NEEDS_REPAIR` cannot be
    removed (`ERR_DEVICE_NOT_REMOVABLE`)".

    Design: Corner/validations/remove_already_removed_device_returns_not_removable
    """
    conn = fixtures.create_connection(api, ADMIN)
    dev = fixtures.create_device(conn["id"], api, ADMIN, install_date="2026-01-01T00:00:00Z")
    get_success_data(api.remove_device(dev["id"], ADMIN))
    validate_error(api.remove_device(dev["id"], ADMIN), ApiErrorId.ERR_DEVICE_NOT_REMOVABLE)


# --------------------------------------------------------------------------- #
# Corner/validations/restore_non_shutoff_connection_returns_not_shutoff
# --------------------------------------------------------------------------- #
def test_restore_non_shutoff_connection_returns_not_shutoff(api):
    """PRD §3.6: "the connection can be brought back by a `UtilityAdmin` restore, which is
    allowed only when the connection is currently in `SHUTOFF` posture (else
    `ERR_NOT_SHUTOFF`)".

    Design: Corner/validations/restore_non_shutoff_connection_returns_not_shutoff
    """
    conn = fixtures.create_connection(api, ADMIN)
    validate_error(api.restore_connection(conn["id"], ADMIN), ApiErrorId.ERR_NOT_SHUTOFF)
