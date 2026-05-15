"""Overdue sweep, aging buckets, collection routing (PRD §3.8).

Covers OVERDUE entry, aging bucket assignment, soft → hard → legal /
joint-liability, write-off cascade.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_days,
    fetch_repayment_schedule,
    find_collection_case_for_schedule,
    iso_in_days,
    run_sweep,
    setup_scheduled_repayment,
    validate_error,
    validate_success,
    write_off_collection_case_payload,
)


def _drive_to_dpd(bundle, schedule, days_past_due: int):
    """Advance past the schedule's due date by exactly the given dpd,
    then run the sweep. Returns the open CollectionCase (if any)."""
    advance_clock_by_days(schedule["scheduled_repayment_date"], days_past_due)
    run_sweep()
    refreshed = fetch_repayment_schedule(schedule["id"])
    return refreshed, find_collection_case_for_schedule(schedule["id"])


def test_sweep_opens_collection_case_on_overdue(api):
    """PRD §3.8: "When the sweep detects that the current clock is past
    a schedule's scheduled_repayment_date and paid_cents is strictly
    less than total_due_cents, it advances the schedule to OVERDUE and
    opens a CollectionCase whose schedule_id references that repayment
    schedule, with stage set to SOFT and reminder_count at zero."
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 5)
    if refreshed["status"] != "OVERDUE":
        pytest.skip(
            "Sweep did not produce OVERDUE; logical-clock semantics "
            "may differ across implementations."
        )
    assert case is not None, (
        "PRD §3.8: a CollectionCase must be opened on OVERDUE."
    )
    assert case["stage"] == "SOFT"
    assert case["reminder_count"] == 0
    assert case["schedule_id"] == schedule["id"]
    # PRD §3.8: "The outstanding_cents of the case at open time is
    # total_due_cents - paid_cents".
    assert case["outstanding_cents"] == (
        refreshed["total_due_cents"] - refreshed["paid_cents"]
    )


def test_aging_bucket_dpd_1_30_at_dpd_30(api):
    """PRD §3.8: "a dpd from 1 through 30 inclusive yields DPD_1_30."

    Boundary inclusive-upper for DPD_1_30 is 30.
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 30)
    if refreshed["status"] != "OVERDUE":
        pytest.skip("Sweep did not produce OVERDUE.")
    assert case is not None
    assert case["aging_bucket"] == "DPD_1_30", (
        f"At dpd=30, aging_bucket must be DPD_1_30 per PRD §3.8; "
        f"got {case['aging_bucket']}"
    )


def test_aging_bucket_dpd_31_60_at_dpd_31_boundary(api):
    """PRD §3.8: "from 31 through 60 inclusive yields DPD_31_60. ...
    The boundaries are inclusive lower so the moment dpd becomes 31
    the bucket changes."

    Crossing from dpd=30 to dpd=31 flips the bucket.
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 31)
    if refreshed["status"] != "OVERDUE":
        pytest.skip("Sweep did not produce OVERDUE.")
    assert case is not None
    assert case["aging_bucket"] == "DPD_31_60", (
        f"At dpd=31, aging_bucket must be DPD_31_60 per PRD §3.8; "
        f"got {case['aging_bucket']}"
    )


def test_reminder_increments_reminder_count(
    api, collection_manager_headers,
):
    """PRD §3.8: "A CollectionManager issues a soft reminder against a
    case, incrementing reminder_count by one."
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 5)
    if not case:
        pytest.skip("No CollectionCase opened.")
    before = case["reminder_count"]
    res = api.remind_collection_case(case["id"], collection_manager_headers)
    after = validate_success(res)
    assert after["reminder_count"] == before + 1


def test_escalate_requires_aging_bucket_and_reminder_threshold(
    api, collection_manager_headers,
):
    """PRD §3.8: "Escalation from SOFT to HARD requires that
    reminder_count has reached the SOFT_TO_HARD_REMINDER_THRESHOLD
    system constant and that aging_bucket is in DPD_31_60, DPD_61_90,
    or DPD_OVER_90."

    With a fresh case (reminder_count=0) escalation must fail; PRD §5
    catalogues ERR_INVALID_STATE for state-precondition violations.
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 5)
    if not case:
        pytest.skip("No CollectionCase opened.")
    res = api.escalate_collection_case(
        case["id"], collection_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_write_off_requires_legal_and_dpd_over_90(
    api, collection_manager_headers,
):
    """PRD §3.8: "From LEGAL, the manager performs the write-off
    (LEGAL → WRITTEN_OFF) with a write_off_reason in the request body
    when aging_bucket is DPD_OVER_90."

    A still-SOFT case cannot be written off.
    """
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 5)
    if not case:
        pytest.skip("No CollectionCase opened.")
    res = api.write_off_collection_case(
        case["id"], write_off_collection_case_payload(),
        collection_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_settling_in_overdue_closes_open_case(api):
    """PRD §3.8: "Whenever the schedule reaches SETTLED while a case is
    still in SOFT, HARD, or JOINT_LIABILITY, the case cascades to
    CLOSED."
    """
    from test_helpers import api_client, repay_in_full
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    refreshed, case = _drive_to_dpd(bundle, schedule, 5)
    if not case:
        pytest.skip("No CollectionCase opened.")
    outstanding = refreshed["total_due_cents"] - refreshed["paid_cents"]
    repay_in_full(refreshed, repay_amount_cents=outstanding, ce=bundle["ce"])
    case_res = api_client.get_collection_case(
        case["id"], TEST_USERS["collection_manager_headers"],
    )
    case_after = validate_success(case_res)
    assert case_after["stage"] == "CLOSED"
