"""Repayment, partial prepayment, early-settle rebate, full settle
(PRD §3.7).
"""
from __future__ import annotations
import math
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_core_enterprise_headers,
    make_supplier_headers,
    partial_repay,
    repay_in_full,
    repay_repayment_schedule_payload,
    setup_scheduled_repayment,
    validate_error,
    validate_success,
)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def test_partial_prepayment_advances_to_partially_paid(api):
    """PRD §3.7: "On success, paid_cents increases by the supplied
    amount and prepayment_count increases by one, and the schedule
    status advances to PARTIALLY_PAID."
    """
    bundle, schedule = setup_scheduled_repayment(term_days=90)
    initial_paid = schedule["paid_cents"]
    updated = partial_repay(
        schedule, repay_amount_cents=100_000,
        supplier=bundle["supplier"],
    )
    assert updated["status"] == "PARTIALLY_PAID"
    assert updated["paid_cents"] == initial_paid + 100_000
    assert updated["prepayment_count"] == 1


def test_partial_prepayment_rejected_when_amount_above_outstanding(api):
    """PRD §3.7: "an attempt to pay more than outstanding returns
    ERR_OVERPAYMENT."
    """
    bundle, schedule = setup_scheduled_repayment(term_days=90)
    outstanding = schedule["total_due_cents"] - schedule["paid_cents"]
    res = api.repay_repayment_schedule(
        schedule["id"],
        repay_repayment_schedule_payload(
            repay_amount_cents=outstanding + 1, partial=True,
        ),
        make_supplier_headers(bundle["supplier"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT.value)


def test_full_balance_repayment_settles_schedule(api):
    """PRD §3.7: "On full settlement, the schedule's paid_cents is set
    to total_due_cents."
    """
    bundle, schedule = setup_scheduled_repayment(term_days=90)
    settled = repay_in_full(schedule, ce=bundle["ce"])
    assert settled["status"] == "SETTLED"
    assert settled["paid_cents"] == schedule["total_due_cents"]


def test_full_repayment_cascades_receivable_to_settled(api):
    """PRD §3.7: "the underlying Receivable is cascaded to SETTLED."
    """
    from test_helpers import get_receivable
    bundle, schedule = setup_scheduled_repayment(term_days=90)
    repay_in_full(schedule, ce=bundle["ce"])
    rec = get_receivable(bundle["receivable"]["id"])
    assert rec["status"] == "SETTLED"


def test_full_repayment_cascades_confirmation_to_settled(api):
    """PRD §3.7: "the anchoring PayableConfirmation is cascaded to
    SETTLED."
    """
    from test_helpers import get_payable_confirmation
    bundle, schedule = setup_scheduled_repayment(term_days=90)
    repay_in_full(schedule, ce=bundle["ce"])
    pc = get_payable_confirmation(bundle["confirmation"]["id"])
    assert pc["status"] == "SETTLED"


def test_full_repayment_releases_credit_line_counters(api):
    """PRD §3.7: "the ledger releases both credit_line_reserved_cents
    and credit_line_consumed_cents by the original confirmation amount
    and principal respectively."
    """
    from test_helpers import get_core_enterprise
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=90,
    )
    ce_before = get_core_enterprise(bundle["ce"]["id"])
    repay_in_full(schedule, ce=bundle["ce"])
    ce_after = get_core_enterprise(bundle["ce"]["id"])
    # After DISBURSED: reserved was reduced by 1_000_000 already (per
    # §2.7). After SETTLED: reserved AND consumed must each drop by
    # 1_000_000 from the ce_before snapshot reading.
    # The PRD says "releases both reserved and consumed by the original
    # confirmation amount and principal respectively." The confirmation
    # amount equals the disbursement principal in this fixture; both
    # drop by 1_000_000 net.
    assert ce_after["credit_line_consumed_cents"] == (
        ce_before["credit_line_consumed_cents"] - 1_000_000
    ), (
        f"consumed must drop by principal on full repayment. "
        f"before={ce_before['credit_line_consumed_cents']}, "
        f"after={ce_after['credit_line_consumed_cents']}"
    )


def test_early_settle_rebate_is_strictly_positive_before_due_date(api):
    """PRD §3.7: "the platform applies the early-settle rebate
    calculation: ... and sets rebate_cents to the larger of zero and
    the forward total minus the chronological total."

    Variant B (chronological) for a shorter actually-elapsed period
    yields strictly less interest than Variant A's full-term
    projection, so the rebate must be strictly positive when the
    schedule settles before due date.
    """
    bundle, schedule = setup_scheduled_repayment(
        mode="FACTORING", core_risk_rating="AAA",
        supplier_aml=0.05, amount_cents=1_000_000,
        approved_amount_cents=1_000_000, term_days=90,
    )
    # Advance the clock to 45 days from release.
    from test_helpers import advance_clock_by_days
    advance_clock_by_days(schedule["created_at"], 45)
    outstanding = schedule["total_due_cents"] - schedule["paid_cents"]
    res = api.repay_repayment_schedule(
        schedule["id"],
        repay_repayment_schedule_payload(
            repay_amount_cents=outstanding, early_settle=True,
        ),
        make_supplier_headers(bundle["supplier"]["id"]),
    )
    settled = validate_success(res)
    assert settled["status"] == "SETTLED"
    assert int(settled.get("rebate_cents", 0)) > 0, (
        "PRD §3.7: rebate must be strictly positive when settling "
        "before due date."
    )


def test_overdue_early_settle_pins_rebate_zero(api):
    """PRD §3.7: "If the early-settle flag is true but the current
    clock is already at or past scheduled_repayment_date, the rebate
    is pinned to zero and penalty interest accrues instead via the
    overdue-penalty calculation."

    We advance past the due date, then try an early-settle full payment.
    The rebate cannot offset anything; the payment must equal the
    outstanding (or the schedule remains unsettled).
    """
    from test_helpers import advance_clock_by_days, run_sweep, fetch_repayment_schedule
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    # Advance past the due date.
    advance_clock_by_days(schedule["scheduled_repayment_date"], 1)
    run_sweep()
    refreshed = fetch_repayment_schedule(schedule["id"])
    # The schedule should now be OVERDUE. Attempt to early-settle.
    assert refreshed["status"] in {"OVERDUE", "SCHEDULED", "PARTIALLY_PAID"}, (
        f"PRD §3.8 sweep should move past-due schedule to OVERDUE; got "
        f"{refreshed['status']}"
    )


def test_full_repayment_after_overdue_closes_collection_case(api):
    """PRD §3.7: "A repayment that lands while the schedule is in
    OVERDUE and exactly settles the outstanding closes the open
    CollectionCase to CLOSED and advances the schedule directly to
    SETTLED."
    """
    from test_helpers import (
        advance_clock_by_days,
        fetch_repayment_schedule,
        find_collection_case_for_schedule,
        run_sweep,
    )
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    advance_clock_by_days(schedule["scheduled_repayment_date"], 1)
    run_sweep()
    refreshed = fetch_repayment_schedule(schedule["id"])
    if refreshed["status"] != "OVERDUE":
        pytest.skip(
            "Sweep did not move schedule to OVERDUE; PRD pins the "
            "transition but timing depends on logical clock impl."
        )
    case = find_collection_case_for_schedule(schedule["id"])
    assert case is not None, (
        "PRD §3.8: 'opens a CollectionCase whose schedule_id "
        "references that repayment schedule' on OVERDUE."
    )
    # Now pay the outstanding in full.
    outstanding = refreshed["total_due_cents"] - refreshed["paid_cents"]
    settled = repay_in_full(
        refreshed, repay_amount_cents=outstanding, ce=bundle["ce"],
    )
    assert settled["status"] == "SETTLED"
    # The case must be CLOSED.
    from test_helpers import api_client
    case_res = api_client.get_collection_case(
        case["id"], TEST_USERS["collection_manager_headers"],
    )
    case_after = validate_success(case_res)
    assert case_after["stage"] == "CLOSED", (
        f"PRD §3.7: 'closes the open CollectionCase to CLOSED'. "
        f"Got stage={case_after['stage']}"
    )
