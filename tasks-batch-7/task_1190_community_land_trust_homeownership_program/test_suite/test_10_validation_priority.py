"""Validation priority conflicts — state before business-safety, cure-evidence before arrears."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    setup_active_lease,
    setup_defaulted_lease,
    setup_program,
    validate_error,
    validate_error_is_one_of,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _pa():
    return TEST_USERS["platform_admin_headers"]


def test_double_activate_returns_invalid_state_not_other_errors():
    """PRD §2.10 step 4: "**State** — the target resource must be in a state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."
    PRD §3.3: "Activating a draft lease is a `LeaseManager` operation guarded
    by optimistic concurrency on the unit: the request must carry
    `expected_unit_version` equal to the unit's current `version`, otherwise
    the activation is rejected with `ERR_STALE_VERSION`."

    When the lease is already ACTIVE, the state check fires regardless of
    OCC correctness on the unit side — the unit itself is OCCUPIED so the
    activation precondition `occupancy_status in (VACANT, UNDER_CONTRACT)`
    fails, returning ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_lease_activate
    """
    prog = setup_program(name="P-PR1")
    _, unit, _, lease = setup_active_lease(prog["id"])

    # Fresh read of unit version (matches).
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    resp = api_client.activate_lease(
        prog["id"],
        unit["id"],
        lease["id"],
        {"expected_unit_version": unit_now["version"]},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    # Lease state unchanged.
    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["status"] == "ACTIVE"


def test_activate_already_active_lease_with_stale_unit_version_also_returns_invalid_state():
    """PRD §2.10 step 4: "**State** — the target resource must be in a state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."
    PRD §2.10 step 8: "**Optimistic concurrency** — for the five OCC-guarded
    operations listed in §2.6, the `expected_*_version` must match the
    parent's current version; otherwise `ERR_STALE_VERSION`."

    State (step 4) fires before OCC (step 8): even with a stale
    `expected_unit_version`, an already-ACTIVE lease must yield
    ERR_INVALID_STATE, not ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_lease_activate
    """
    prog = setup_program(name="P-PR1b")
    _, unit, _, lease = setup_active_lease(prog["id"])

    # Lease is ACTIVE; unit version has been bumped by the activation.
    # Submit with a stale unit version — state check fires first.
    resp = api_client.activate_lease(
        prog["id"],
        unit["id"],
        lease["id"],
        {"expected_unit_version": 0},  # clearly stale
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cure_with_empty_evidence_and_unpaid_arrears_fires_evidence_check_first():
    """PRD §2.10 step 7 enumerates business-rule checks in order; cure
    evidence precedes arrears clearance in the §3.4 rule text.
    PRD §3.4: "For a `FEE_ARREARS` notice, the lease's `fee_arrears_cents`
    must equal 0 after any concurrent payment has been applied; if arrears
    remain, the cure is rejected with `ERR_ARREARS_NOT_CLEARED`. For a
    `MAINTENANCE` notice, a follow-up `InspectionRecord` with `result` equal
    to `PASSED` must exist whose `completed_at` is strictly after the
    notice's `issued_at`; if no such inspection exists (or `cure_evidence` is
    missing), the cure is rejected with `ERR_CURE_EVIDENCE_MISSING`."
    PRD §3.4: "Curing a notice is a `LeaseManager` operation that requires a
    non-empty `cure_evidence` string."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_default_cure
    """
    prog = setup_program(name="P-PR2")
    _, unit, _, lease, notice = setup_defaulted_lease(prog["id"])

    resp = api_client.cure_default_notice(
        prog["id"],
        unit["id"],
        lease["id"],
        notice["id"],
        {"cure_evidence": ""},
        _lm(),
    )
    # Empty cure_evidence violates the universal "non-empty cure_evidence"
    # requirement. PRD names ERR_CURE_EVIDENCE_MISSING for missing evidence
    # only inside the MAINTENANCE clause; for a FEE_ARREARS notice the
    # non-empty requirement exists but no error_id is pinned, so both
    # ERR_CURE_EVIDENCE_MISSING and generic ERR_INVALID_REQUEST are
    # PRD-faithful. What this test pins is the ORDERING: the evidence check
    # fires at the evidence step — never the arrears step.
    actual = validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_CURE_EVIDENCE_MISSING.value,
            ApiErrorId.ERR_INVALID_REQUEST.value,
        ],
    )
    assert actual != ApiErrorId.ERR_ARREARS_NOT_CLEARED.value

    # Notice remains OPEN.
    notice_after = get_success_data(
        api_client.get_default_notice(
            prog["id"], unit["id"], lease["id"], notice["id"], _lm()
        )
    )
    assert notice_after["status"] == "OPEN"


def test_cure_with_arrears_remaining_fires_arrears_check_when_evidence_present():
    """PRD §3.4: "For a `FEE_ARREARS` notice, the lease's `fee_arrears_cents`
    must equal 0 after any concurrent payment has been applied; if arrears
    remain, the cure is rejected with `ERR_ARREARS_NOT_CLEARED`."

    When `cure_evidence` is supplied (non-empty) but the arrears have not
    been cleared, the arrears-clearance check fires.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_default_cure
    """
    prog = setup_program(name="P-PR2b")
    _, unit, _, lease = setup_active_lease(prog["id"])

    # PRD §3.3: a PENDING fee goes LATE at due_date + 5 days of grace, and
    # "that transition increments the lease's `fee_arrears_cents` by the
    # fee's `amount_cents`". The activation fee covers 2026-05 with due_date
    # 2026-05-01; advancing to 2026-06-10 marks it LATE, so arrears > 0.
    get_success_data(api_client.set_clock("2026-06-10T00:00:00Z", _pa()))
    lease_late = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_late["fee_arrears_cents"] > 0

    notice = get_success_data(
        api_client.create_default_notice(
            prog["id"],
            unit["id"],
            lease["id"],
            {
                "notice_kind": "FEE_ARREARS",
                "amount_due_cents": lease_late["fee_arrears_cents"],
            },
            _lm(),
        )
    )

    # Arrears still > 0, but cure_evidence is supplied.
    resp = api_client.cure_default_notice(
        prog["id"],
        unit["id"],
        lease["id"],
        notice["id"],
        {"cure_evidence": "claimed-payment-ref"},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_ARREARS_NOT_CLEARED.value)

    notice_after = get_success_data(
        api_client.get_default_notice(
            prog["id"], unit["id"], lease["id"], notice["id"], _lm()
        )
    )
    assert notice_after["status"] == "OPEN"
