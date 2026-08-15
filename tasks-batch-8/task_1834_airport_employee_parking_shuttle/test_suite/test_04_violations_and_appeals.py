"""Violations: escalating fines, the suspension threshold, the parallel
payment/appeal dimensions, and the appeal window."""
import pytest

from test_helpers import (
    TEST_USERS,
    close_and_export_cycle,
    entries_for_permit,
    get_cycle,
    issue_violations,
    make_appeals_officer_headers,
    make_employee_headers,
    permit_fee_entries,
    set_logical_clock,
    settle_entry,
    setup_active_permit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]


def _setup_active_pool0(api):
    set_logical_clock("2026-08-01T00:00:00Z")
    return setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 5},
    )


class TestViolationParallelDimensions:
    """payment_status and appeal_status are two parallel state dimensions."""

    def _setup_v1_appealed(self, api):
        bundle = _setup_active_pool0(api)
        set_logical_clock("2026-08-05T10:00:00Z")
        v1 = issue_violations(bundle["permit"], "WRONG_LOT", count=1,
                              officer_id="officer-1")[0]
        set_logical_clock("2026-08-06T10:00:00Z")
        return bundle, v1

    def test_appeal_moves_appeal_axis_while_payment_stays_unpaid(self, api):
        """PRD section 3.7: "The payment dimension `payment_status` starts at
        `UNPAID` and moves to `PAID` when the linked fine entry settles to
        `SETTLED`, or to `REVERSED` through the dismissal cascade below. The
        appeal dimension `appeal_status` starts at `NONE` and moves to
        `APPEALED`, then to `UPHELD` or `DISMISSED`."
        PRD section 3.7: "A `DISMISSED` decision flips `payment_status` to
        `REVERSED` and compensates the ledger: the linked `VIOLATION_FINE` entry
        is reversed when it is still `PENDING`, while an entry that has already
        advanced to `APPLIED` or `EXPORTED` is left in place and an
        `ADJUSTMENT_CREDIT` for the fine amount is posted instead into the
        program's current `OPEN` cycle, if one exists."

        Design: Difficulty/non_linear_state_machine/violation_parallel_payment_appeal_dimensions
        """
        bundle, v1 = self._setup_v1_appealed(api)
        appealed = validate_success(
            api.violation_event(v1["id"], {"event_type": "APPEAL"},
                                make_employee_headers(bundle["employee"]["id"])),
            200,
        )
        assert appealed["appeal_status"] == "APPEALED"
        assert appealed["payment_status"] == "UNPAID", (
            "the dimensions move independently"
        )

        dismissed = validate_success(
            api.violation_event(
                v1["id"], {"event_type": "DECIDE_APPEAL", "decision": "DISMISSED"},
                make_appeals_officer_headers("officer-2"),
            ),
            200,
        )
        assert dismissed["appeal_status"] == "DISMISSED"
        assert dismissed["payment_status"] == "REVERSED", (
            "cross-dimension side effect of a dismissal"
        )

        fine_entry = validate_success(
            api.get_charge_entry(dismissed["charge_entry_id"], ADMIN), 200
        )
        assert fine_entry["status"] == "REVERSED", (
            "the still-PENDING fine entry is reversed on dismissal"
        )

    def test_second_violation_settles_to_paid_with_no_appeal(self, api):
        """PRD section 3.7: "The escalation count is the number of violations of
        the same permit still `UNPAID` and issued within the trailing 365 days —
        the boundary day 365 days back is included, while `PAID` and `REVERSED`
        violations are excluded."
        PRD section 3.6: "Settling an entry whose `charge_type` is `VIOLATION_FINE`
        to `SETTLED` — whether directly from `EXPORTED` or by retry from
        `DEDUCTION_FAILED` — flips the linked violation's `payment_status` from
        `UNPAID` to `PAID`."

        Design: Difficulty/non_linear_state_machine/violation_parallel_payment_appeal_dimensions
        """
        bundle, v1 = self._setup_v1_appealed(api)
        validate_success(
            api.violation_event(v1["id"], {"event_type": "APPEAL"},
                                make_employee_headers(bundle["employee"]["id"])),
            200,
        )
        validate_success(
            api.violation_event(
                v1["id"], {"event_type": "DECIDE_APPEAL", "decision": "DISMISSED"},
                make_appeals_officer_headers("officer-2"),
            ),
            200,
        )

        v2 = issue_violations(bundle["permit"], "NO_PERMIT_DISPLAY", count=1,
                              officer_id="officer-1")[0]
        assert v2["fine_cents"] == 2500, (
            "the REVERSED first violation is excluded from the escalation window"
        )

        close_and_export_cycle(bundle["cycle"]["id"])
        settle_entry(v2["charge_entry_id"], "SETTLED")

        settled = validate_success(api.get_violation(v2["id"], ADMIN), 200)
        assert settled["payment_status"] == "PAID"
        assert settled["appeal_status"] == "NONE"


class TestViolationThresholdCascade:
    """Depth-2 cascade: the threshold-reaching violation suspends the permit,
    and the suspension truncates the pending fee."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 100000,
                               "violation_suspension_threshold": 3},
            lot_overrides={"capacity": 5},
        )
        set_logical_clock("2026-08-16T10:00:00Z")
        fines = [
            v["fine_cents"]
            for v in issue_violations(bundle["permit"], "BLOCKED_LANE", count=3,
                                      officer_id="officer-1")
        ]
        return bundle, fines

    def test_escalating_fine_amounts(self, api):
        """PRD section 3.7: "The escalation count is the number of violations of
        the same permit still `UNPAID` and issued within the trailing 365 days —
        the boundary day 365 days back is included, while `PAID` and `REVERSED`
        violations are excluded. Each such prior unpaid violation adds 50% of the
        base fine: the fine is the base for the code multiplied by one plus
        one-half times the escalation count, rounded half-up to integer cents, and
        stored as `fine_cents`. Base fines are 5000 cents for `EXPIRED_PERMIT`,
        3500 for `WRONG_LOT`, 2500 for `NO_PERMIT_DISPLAY`, 7500 for
        `BLOCKED_LANE`, and 10000 for `PARKED_AFTER_REVOCATION`."

        Design: Difficulty/transitive_cascade/violation_threshold_two_hop_cascade
        """
        _bundle, fines = self._drive(api)
        assert fines == [7500, 11250, 15000], (
            "BLOCKED_LANE base 7500 with x1.0 / x1.5 / x2.0 escalation"
        )

    def test_threshold_suspension_truncates_fee(self, api):
        """PRD section 3.7: "When the escalation count plus the new violation
        reaches or exceeds the program's `violation_suspension_threshold` — the
        violation that reaches the threshold is the one that triggers — and the
        permit is `ACTIVE`, the permit moves to `SUSPENDED` with
        `suspension_reason` `VIOLATION_THRESHOLD`, carrying the full suspension
        bookkeeping of §3.5 including the fee truncation repost."
        PRD section 3.5: "The permit's `PENDING` `PERMIT_FEE` entry in the
        program's `OPEN` cycle whose span contains the suspension date is
        reversed, and a truncated `PENDING` repost is created covering the span
        start through the suspension date, priced per §3.4."

        Design: Difficulty/transitive_cascade/violation_threshold_two_hop_cascade
        """
        bundle, _fines = self._drive(api)

        permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "VIOLATION_THRESHOLD"

        fees = permit_fee_entries(bundle["permit"]["id"])
        by_span = {(f["span_start"], f["span_end"]): f for f in fees}
        original = by_span[("2026-08-01", "2026-08-31")]
        truncated = by_span[("2026-08-01", "2026-08-16")]
        assert original["amount_cents"] == 10800
        assert original["status"] == "REVERSED"
        # net = 12000 - 1200 = 10800 over 16 active days of 31.
        assert truncated["amount_cents"] == 5574
        assert truncated["status"] == "PENDING"

        cycle = get_cycle(bundle["cycle"]["id"])
        assert cycle["total_charges_cents"] == 39324, (
            "5574 truncated fee + 7500 + 11250 + 15000 fines"
        )


class TestViolationSuspensionAtExactThreshold:
    """Count boundary on the suspension trigger: the comparison is >=."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 0,
                               "violation_suspension_threshold": 3},
            lot_overrides={"capacity": 5},
        )
        set_logical_clock("2026-08-16T10:00:00Z")
        return bundle

    def test_two_violations_below_threshold_leave_permit_active(self, api):
        """PRD section 3.7: "When the escalation count plus the new violation
        reaches or exceeds the program's `violation_suspension_threshold` — the
        violation that reaches the threshold is the one that triggers — and the
        permit is `ACTIVE`, the permit moves to `SUSPENDED` with
        `suspension_reason` `VIOLATION_THRESHOLD`, carrying the full suspension
        bookkeeping of §3.5 including the fee truncation repost."
        PRD section 3.7: "Each such prior unpaid violation adds 50% of the base
        fine: the fine is the base for the code multiplied by one plus one-half
        times the escalation count, rounded half-up to integer cents, and stored
        as `fine_cents`."

        Design: Difficulty/boundary_precision_check/violation_suspension_at_exact_threshold
        """
        bundle = self._setup(api)
        fines = [
            v["fine_cents"]
            for v in issue_violations(bundle["permit"], "WRONG_LOT", count=2,
                                      officer_id="officer-1")
        ]
        assert fines == [3500, 5250], "WRONG_LOT base 3500, escalation x1.0 then x1.5"

        permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
        assert permit["status"] == "ACTIVE", "2 < 3 does not suspend"

    def test_third_violation_at_threshold_suspends(self, api):
        """PRD section 3.7: "When the escalation count plus the new violation
        reaches or exceeds the program's `violation_suspension_threshold` — the
        violation that reaches the threshold is the one that triggers — and the
        permit is `ACTIVE`, the permit moves to `SUSPENDED` with
        `suspension_reason` `VIOLATION_THRESHOLD`, carrying the full suspension
        bookkeeping of §3.5 including the fee truncation repost."

        Design: Difficulty/boundary_precision_check/violation_suspension_at_exact_threshold
        """
        bundle = self._setup(api)
        violations = issue_violations(bundle["permit"], "WRONG_LOT", count=3,
                                      officer_id="officer-1")
        assert [v["fine_cents"] for v in violations] == [3500, 5250, 7000]

        permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
        assert permit["status"] == "SUSPENDED", "3 >= 3 suspends — equality triggers"
        assert permit["suspension_reason"] == "VIOLATION_THRESHOLD"


def test_appeal_window_exactly_fourteen_days(api):
    """PRD section 3.7: "The owning employee — and only the `Employee` role — may
    file an appeal event while `payment_status` is still `UNPAID`
    (`ERR_INVALID_STATE` otherwise) and no later than 14 days after `issued_at`,
    with the boundary day itself still acceptable (`ERR_APPEAL_WINDOW_CLOSED`)."

    Design: Corner/validations/appeal_window_exactly_fourteen_days
    """
    bundle = _setup_active_pool0(api)
    set_logical_clock("2026-08-05T10:00:00Z")
    v1, v2 = issue_violations(bundle["permit"], "WRONG_LOT", count=1,
                              officer_id="officer-1") + issue_violations(
        bundle["permit"], "NO_PERMIT_DISPLAY", count=1, officer_id="officer-1")

    # Appeal at exactly issued_at + 14 days: inside the inclusive window.
    set_logical_clock("2026-08-19T10:00:00Z")
    ok = validate_success(
        api.violation_event(v1["id"], {"event_type": "APPEAL"},
                            make_employee_headers(bundle["employee"]["id"])),
        200,
    )
    assert ok["appeal_status"] == "APPEALED"

    # One second past the window: closed.
    set_logical_clock("2026-08-19T10:00:01Z")
    res = api.violation_event(
        v2["id"], {"event_type": "APPEAL"},
        make_employee_headers(bundle["employee"]["id"]),
    )
    validate_error(res, "ERR_APPEAL_WINDOW_CLOSED", expected_status=409)

    after = validate_success(api.get_violation(v2["id"], ADMIN), 200)
    assert after["appeal_status"] == "NONE"
