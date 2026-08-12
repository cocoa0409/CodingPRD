"""GroundLease / DefaultNotice cyclic state machine — default → cure → active."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_active_lease,
    setup_defaulted_lease,
    setup_program,
    validate_error,
    ApiErrorId,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_lease_in_default_cure_returns_to_active():
    """PRD §3.4: "On a successful cure the notice transitions `OPEN` → `CURED`
    with `cured_at` set to now; if this was the last open notice on the lease,
    the lease returns to `ACTIVE` and the unit returns to `OCCUPIED`."

    Design: Difficulty/non_linear_state_machine/ground_lease_default_cure_cycle
    """
    prog = setup_program(name="P-CYC1")
    _, unit, _, lease, notice = setup_defaulted_lease(prog["id"])
    # Lease is IN_DEFAULT; unit is IN_DEFAULT.
    assert lease["status"] == "IN_DEFAULT"
    assert unit["occupancy_status"] == "IN_DEFAULT"

    cured = get_success_data(
        api_client.cure_default_notice(
            prog["id"],
            unit["id"],
            lease["id"],
            notice["id"],
            {"cure_evidence": "paid-arrears-txn-001"},
            _lm(),
        )
    )
    assert cured["status"] == "CURED"

    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["status"] == "ACTIVE"

    unit_after = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    assert unit_after["occupancy_status"] == "OCCUPIED"


def test_lease_can_reenter_default_after_cure():
    """PRD §3.4: "Issuing a notice transitions the lease to `IN_DEFAULT` and
    the unit's `occupancy_status` to `IN_DEFAULT`."
    PRD §3.4: "On a successful cure the notice transitions `OPEN` → `CURED`
    with `cured_at` set to now; if this was the last open notice on the lease,
    the lease returns to `ACTIVE` and the unit returns to `OCCUPIED`."

    The lease cycles ACTIVE → IN_DEFAULT → ACTIVE → IN_DEFAULT (a true cycle,
    not a one-way revert).

    Design: Difficulty/non_linear_state_machine/ground_lease_default_cure_cycle
    """
    prog = setup_program(name="P-CYC2")
    _, unit, _, lease, notice1 = setup_defaulted_lease(prog["id"])

    # First cycle: cure.
    get_success_data(
        api_client.cure_default_notice(
            prog["id"],
            unit["id"],
            lease["id"],
            notice1["id"],
            {"cure_evidence": "first-cure"},
            _lm(),
        )
    )
    lease_mid = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_mid["status"] == "ACTIVE"

    # Second cycle: issue a new notice — lease returns to IN_DEFAULT.
    notice2 = get_success_data(
        api_client.create_default_notice(
            prog["id"],
            unit["id"],
            lease["id"],
            {"notice_kind": "FEE_ARREARS", "amount_due_cents": 25_000},
            _lm(),
        )
    )
    lease_after2 = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after2["status"] == "IN_DEFAULT"
    assert notice2["status"] == "OPEN"

    # Cure the second notice — lease returns to ACTIVE again.
    get_success_data(
        api_client.cure_default_notice(
            prog["id"],
            unit["id"],
            lease["id"],
            notice2["id"],
            {"cure_evidence": "second-cure"},
            _lm(),
        )
    )
    lease_final = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_final["status"] == "ACTIVE"
