"""Lateness decided afresh on each submission, and the exact reversal on withdrawal."""

from test_helpers import (
    assert_price_schedule,
    assert_wholesaler,
    read_exposure,
    read_item,
    read_schedule,
    read_wholesaler,
    return_schedule_for_correction,
    set_clock,
    setup_draft_schedule,
    setup_licensee_base,
    submit_schedule,
    withdraw_schedule,
)


def _september_schedule_submitted_on_time():
    """A 2026-09 schedule filed at 2026-08-01, well inside its deadline."""
    scene = setup_licensee_base()
    setup_draft_schedule(scene, posting_month="2026-09")
    scene["schedule"] = submit_schedule(scene["schedule"]["id"], scene["agent_headers"])
    return scene


def _july_schedule_submitted_late():
    """A 2026-07 schedule filed at 2026-08-01, three weeks past its deadline."""
    scene = setup_licensee_base()
    setup_draft_schedule(scene, posting_month="2026-07")
    scene["schedule"] = submit_schedule(scene["schedule"]["id"], scene["agent_headers"])
    return scene


def test_first_submission_before_the_deadline_leaves_the_wholesaler_untouched():
    """An on-time filing moves no counter and does not disturb the wholesaler record.

    PRD §3.3: "When `is_late` comes out `false`, none of this happens: no counter moves,
    no penalty accrues, and the wholesaler's `version` and `updated_at` are left exactly
    as they were."

    Design: Difficulty/non_linear_state_machine/price_schedule_returns_to_draft_and_resubmission_after_deadline_turns_late
    """
    scene = _september_schedule_submitted_on_time()
    schedule = scene["schedule"]

    assert_price_schedule(schedule)
    assert schedule["status"] == "SUBMITTED"
    assert schedule["is_late"] is False
    assert schedule["filed_at"] == "2026-08-01T00:00:00.000Z"
    assert schedule["effective_date"] == "2026-10-01T00:00:00.000Z"
    assert schedule["return_count"] == 0

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert_wholesaler(wholesaler)
    assert wholesaler["late_filing_count"] == 0
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0
    assert wholesaler["version"] == 1


def test_resubmission_after_the_deadline_turns_the_same_schedule_late():
    """Returned to draft and filed again past the deadline, the second filing accrues.

    PRD §3.3: "The consequence is deliberate and cumulative: a schedule that is returned
    and then filed late again accrues the late filing penalty a second time and increments
    `late_filing_count` a second time, because each submission is evaluated afresh against
    the deadline instant."

    Design: Difficulty/non_linear_state_machine/price_schedule_returns_to_draft_and_resubmission_after_deadline_turns_late
    """
    scene = _september_schedule_submitted_on_time()
    schedule_id = scene["schedule"]["id"]

    returned = return_schedule_for_correction(schedule_id)
    assert returned["status"] == "DRAFT"
    assert returned["return_count"] == 1

    set_clock("2026-09-15T00:00:00Z")
    resubmitted = submit_schedule(schedule_id, scene["agent_headers"])

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["is_late"] is True
    assert resubmitted["return_count"] == 1
    assert resubmitted["filed_at"] == "2026-09-15T00:00:00.000Z"

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["late_filing_count"] == 1
    assert wholesaler["late_filing_penalty_accrued_cents"] == 250_000
    assert wholesaler["penalty_exposure_cents"] == 250_000

    item = read_item(scene["items"][0]["id"])
    assert item["status"] == "DRAFT"


def test_late_submission_accrues_the_penalty_into_the_bucket_identity():
    """The late filing bucket, the counter and the exposure sum all move in one request.

    PRD §3.3: "When `is_late` comes out `true`, the wholesaler's `late_filing_count` is
    incremented by 1, the program's `late_filing_penalty_cents` is added to the
    wholesaler's `late_filing_penalty_accrued_cents`, `penalty_exposure_cents` is
    recomputed as the sum of the four buckets, and the wholesaler's `version` is advanced
    by 1."

    Design: Difficulty/compensating_invariant/withdraw_conserves_the_wholesaler_late_filing_penalty_ledger_to_the_cent
    """
    scene = _july_schedule_submitted_late()

    assert scene["schedule"]["is_late"] is True
    assert scene["schedule"]["effective_date"] == "2026-08-01T00:00:00.000Z"

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert_wholesaler(wholesaler)
    assert wholesaler["late_filing_count"] == 1
    assert wholesaler["late_filing_penalty_accrued_cents"] == 250_000
    assert wholesaler["correction_penalty_accrued_cents"] == 0
    assert wholesaler["amendment_penalty_accrued_cents"] == 0
    assert wholesaler["assessed_penalty_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 250_000
    assert wholesaler["version"] == 2


def test_withdrawal_reverses_the_accrual_to_the_cent():
    """Withdrawal subtracts the very amount submission added and clears the counter.

    PRD §3.3: "If `is_late` is `true`, withdrawal reverses the accrual exactly: the
    wholesaler's `late_filing_count` is decremented by 1, the program's
    `late_filing_penalty_cents` is subtracted from `late_filing_penalty_accrued_cents`,
    `penalty_exposure_cents` is recomputed, and the wholesaler's `version` is advanced by
    1."

    Design: Difficulty/compensating_invariant/withdraw_conserves_the_wholesaler_late_filing_penalty_ledger_to_the_cent
    """
    scene = _july_schedule_submitted_late()

    withdrawn = withdraw_schedule(scene["schedule"]["id"], scene["agent_headers"])
    assert withdrawn["status"] == "WITHDRAWN"

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert_wholesaler(wholesaler)
    assert wholesaler["late_filing_count"] == 0
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0
    assert wholesaler["correction_penalty_accrued_cents"] == 0
    assert wholesaler["amendment_penalty_accrued_cents"] == 0
    assert wholesaler["assessed_penalty_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0
    assert wholesaler["version"] == 3

    assessed = read_exposure(scene["wholesaler"]["id"], variant="assessed_exposure")
    assert assessed["accrued_cents"] == 0
    assert assessed["provisional_cents"] == 0
    assert assessed["exposure_cents"] == 0

    provisional = read_exposure(
        scene["wholesaler"]["id"], variant="provisional_exposure"
    )
    assert provisional["exposure_cents"] == 0


def test_withdrawal_preserves_the_historical_filing_facts_it_reversed():
    """The money is undone; the record that the filing was late is not rewritten.

    PRD §3.3: "Withdrawal moves every one of the schedule's items to `WITHDRAWN`
    regardless of the status each item was in, and advances the schedule's `version` by
    1."

    Design: Difficulty/compensating_invariant/withdraw_conserves_the_wholesaler_late_filing_penalty_ledger_to_the_cent
    """
    scene = _july_schedule_submitted_late()

    withdraw_schedule(scene["schedule"]["id"], scene["agent_headers"])

    schedule = read_schedule(scene["schedule"]["id"])
    assert schedule["status"] == "WITHDRAWN"
    assert schedule["is_late"] is True
    assert schedule["filed_at"] == "2026-08-01T00:00:00.000Z"

    item = read_item(scene["items"][0]["id"])
    assert item["status"] == "WITHDRAWN"
