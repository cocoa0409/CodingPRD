"""Billing cycles: overlap boundary, close/export/reject-export, manual
adjustments, settlement outcomes, and the employee balance ledger."""
import pytest

from test_helpers import (
    TEST_USERS,
    close_and_export_cycle,
    close_cycle,
    create_billing_cycle_payload,
    create_charge_entry_payload,
    create_employee,
    create_program,
    cycle_event_payload,
    export_cycle,
    get_cycle,
    get_cycle_version,
    get_employee,
    open_billing_cycle,
    post_adjustment,
    set_logical_clock,
    settle_entry,
    setup_program_lot_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]


class TestBillingCycleClosedIntervalBoundary:
    """Cycles of one program use closed-interval semantics: sharing even one
    boundary day is an overlap."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-BC")
        first = open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
        return program, first

    def test_cycle_sharing_boundary_day_rejected(self, api):
        """PRD section 3.6: "Cycles of one program may never share a calendar day —
        even sharing a single boundary day counts as an overlap and is rejected
        with `ERR_BILLING_CYCLE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/billing_cycle_closed_interval_boundary
        """
        program, _first = self._setup(api)
        res = api.create_billing_cycle(
            create_billing_cycle_payload(program["id"], "2026-08-31", "2026-09-30"),
            PAYROLL,
        )
        validate_error(res, "ERR_BILLING_CYCLE_OVERLAP", expected_status=409)

    def test_cycle_starting_day_after_period_end_accepted(self, api):
        """PRD section 3.6: "Cycles of one program may never share a calendar day —
        even sharing a single boundary day counts as an overlap and is rejected
        with `ERR_BILLING_CYCLE_OVERLAP`." A cycle starting the day after the
        existing period's closed-interval end shares no day.

        Design: Difficulty/resource_temporal_overlap/billing_cycle_closed_interval_boundary
        """
        program, _first = self._setup(api)
        res = api.create_billing_cycle(
            create_billing_cycle_payload(program["id"], "2026-08-31", "2026-09-30"),
            PAYROLL,
        )
        validate_error(res, "ERR_BILLING_CYCLE_OVERLAP", expected_status=409)

        second = validate_success(
            api.create_billing_cycle(
                create_billing_cycle_payload(program["id"], "2026-09-01", "2026-09-30"),
                PAYROLL,
            ),
            201,
        )
        assert second["status"] == "OPEN"

        _data, meta = validate_paginated(
            api.list_billing_cycles(PAYROLL, params={"program_id": program["id"]})
        )
        assert meta["total_count"] == 2, (
            "the rejected create left no residue; exactly two cycles exist"
        )


def test_cycle_reject_export_compensation_and_locks(api):
    """PRD section 3.6: "If payroll rejects the file, an event of `REJECT_EXPORT`
    returns the cycle from `EXPORTED` to `CLOSED` and compensates by moving its
    `EXPORTED` entries back to `APPLIED` — but only while no entry of the cycle
    has reached `SETTLED` or `DEDUCTION_FAILED`; once any entry has, the rejection
    is refused with `ERR_INVALID_STATE`."
    PRD section 3.6: "A `PayrollAdmin` settles an `EXPORTED` entry — or retries a
    `DEDUCTION_FAILED` one — by supplying an `outcome` of `SETTLED` or
    `DEDUCTION_FAILED`."

    Design: Corner/state_machines/cycle_reject_export_compensation_and_locks
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-SM4")
    cycle = open_billing_cycle(program["id"])
    employee = create_employee(program["id"], badge_number="B001")
    entry = post_adjustment(cycle["id"], employee["id"], "ADJUSTMENT_DEBIT", 700,
                            description="fine admin")
    close_cycle(cycle["id"])
    export_cycle(cycle["id"])

    # REJECT_EXPORT compensates the export: cycle CLOSED, entry back to APPLIED.
    rejected = validate_success(
        api.billing_cycle_event(cycle["id"], cycle_event_payload("REJECT_EXPORT"),
                                PAYROLL),
        200,
    )
    assert rejected["status"] == "CLOSED"
    entry_after = validate_success(api.get_charge_entry(entry["id"], PAYROLL), 200)
    assert entry_after["status"] == "APPLIED"

    # An APPLIED entry is not settleable (settle requires EXPORTED or
    # DEDUCTION_FAILED).
    res = api.settle_charge_entry(entry["id"], {"outcome": "SETTLED"}, PAYROLL)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    # Re-export, settle for real, then REJECT_EXPORT is locked out.
    export_cycle(cycle["id"])
    settled = settle_entry(entry["id"], "SETTLED")
    assert settled["status"] == "SETTLED"

    res2 = api.billing_cycle_event(cycle["id"], cycle_event_payload("REJECT_EXPORT"),
                                   PAYROLL)
    validate_error(res2, "ERR_INVALID_STATE", expected_status=409)


def test_manual_adjustment_cycle_state_and_sign_rules(api):
    """PRD section 3.6: "Between those milestones, a `PayrollAdmin` may post
    manual adjustments into an `OPEN` cycle (`ERR_CYCLE_NOT_OPEN` otherwise)."
    PRD section 3.6: "The sign of a manual amount is enforced by its type —
    credits are negative, debits positive — and a violation is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/manual_adjustment_cycle_state_and_sign_rules
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-V13")
    employee = create_employee(program["id"], badge_number="B001")
    august = open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
    close_cycle(august["id"])
    september = open_billing_cycle(program["id"], "2026-09-01", "2026-09-30")

    closed_cycle = api.create_charge_entry(
        create_charge_entry_payload(august["id"], employee["id"],
                                    "ADJUSTMENT_DEBIT", 100),
        PAYROLL,
    )
    validate_error(closed_cycle, "ERR_CYCLE_NOT_OPEN", expected_status=409)

    bad_sign = api.create_charge_entry(
        create_charge_entry_payload(september["id"], employee["id"],
                                    "ADJUSTMENT_CREDIT", 500),
        PAYROLL,
    )
    validate_error(bad_sign, "ERR_INVALID_REQUEST", expected_status=400)

    ok = validate_success(
        api.create_charge_entry(
            create_charge_entry_payload(september["id"], employee["id"],
                                        "ADJUSTMENT_CREDIT", -500,
                                        description="goodwill"),
            PAYROLL,
        ),
        201,
    )
    assert ok["amount_cents"] == -500
    assert ok["status"] == "PENDING"
    assert ok["cycle_id"] == september["id"]


def test_employee_balance_exactly_zero_is_good_standing(api):
    """PRD section 3.1: "`balance_due_cents` is the sum of `amount_cents` over the
    employee's charge entries currently in `DEDUCTION_FAILED` status — reversed
    and settled rows are excluded — and is never negative. `standing` is
    `BILLING_HOLD` whenever that balance is strictly greater than zero and
    `GOOD_STANDING` when it is exactly zero."
    PRD section 3.6: "Marking `DEDUCTION_FAILED` raises the employee's
    `balance_due_cents` by the entry's `amount_cents` and recomputes `standing`,
    which flips to `BILLING_HOLD` once the balance exceeds zero; permits are not
    auto-suspended as a consequence. A later `SETTLED` outcome on that entry
    reduces the balance by the same amount and recomputes standing again."

    Design: Corner/calculations/employee_balance_exactly_zero_is_good_standing
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-BAL")
    cycle = open_billing_cycle(program["id"])
    employee = create_employee(program["id"], badge_number="B001")
    entry = post_adjustment(cycle["id"], employee["id"], "ADJUSTMENT_DEBIT", 5000,
                            description="badge replacement")
    close_and_export_cycle(cycle["id"])

    settle_entry(entry["id"], "DEDUCTION_FAILED")
    mid = get_employee(employee["id"])
    assert mid["balance_due_cents"] == 5000
    assert mid["standing"] == "BILLING_HOLD", "balance strictly above zero holds"

    # Retry path: DEDUCTION_FAILED -> SETTLED returns the balance to exactly 0.
    settle_entry(entry["id"], "SETTLED")
    fin = get_employee(employee["id"])
    assert fin["balance_due_cents"] == 0
    assert fin["standing"] == "GOOD_STANDING", "exactly zero is GOOD_STANDING"


def test_cycle_close_occ_stale_then_fresh_version(api):
    """PRD section 3.6: "A `PayrollAdmin` closes an `OPEN` cycle by submitting
    `expected_billing_cycle_version`; per §2.7 a mismatch with the cycle's
    current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), and
    that stale-version rejection is evaluated before the state gate. Closing a
    cycle that is not `OPEN` is rejected with `ERR_CYCLE_NOT_OPEN`."
    PRD section 2.7: "Second, billing-cycle close: a close request must carry
    `expected_billing_cycle_version` matching the cycle's current `version`."

    Design: Corner/cross_cutting_layers/occ_cycle_close_stale_version
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-CC2")
    cycle = open_billing_cycle(program["id"])

    stale = get_cycle_version(cycle["id"])
    closed = close_cycle(cycle["id"])
    assert closed["status"] == "CLOSED"

    # The close bumped the cycle's version, so the pre-close snapshot is stale —
    # and the stale-version rejection is evaluated before the state gate.
    res = api.close_billing_cycle(
        cycle["id"], {"expected_billing_cycle_version": stale}, PAYROLL
    )
    validate_error(res, "ERR_STALE_CYCLE_VERSION", expected_status=412)

    fresh = get_cycle_version(cycle["id"])
    res2 = api.close_billing_cycle(
        cycle["id"], {"expected_billing_cycle_version": fresh}, PAYROLL
    )
    validate_error(res2, "ERR_CYCLE_NOT_OPEN", expected_status=409)
