"""Cycle generation windows, the cutoff lock, and the skip allowance."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cycle,
    assert_same_instant,
    assert_skip_record,
    list_skip_records,
    read_cycle,
    read_subscription,
    set_clock,
    setup_allocated_cycle,
    setup_household,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import generate_cycle

OPS = TEST_USERS["ops_admin_headers"]


def test_the_generated_window_ship_date_and_cutoff_are_all_derived(api):
    """PRD §3.5: "The cycle's coverage window is half-open: `window_start` takes the
    subscription's current `anchor_date`, `window_end` is `window_start` plus
    `cadence_interval_days` days, and the window covers every instant from the start up to
    but not including the end. The planned dispatch instant, `ship_date`, is set equal to
    `window_start`, and the cutoff instant `cutoff_at` is set to `ship_date` minus 48
    hours."
    PRD §3.5: "Immediately after the cycle is written, the subscription's `anchor_date`
    advances to the new `window_end`, so the anchor always means "where the next cycle will
    start"."

    Design: Corner/entities/corner_cycle_window_and_cutoff_are_system_computed
    """
    ctx = setup_household(api, with_sku=False, email_prefix="win")
    cycle = validate_success(api.generate_cycle(ctx["subscription"]["id"], OPS), 201)
    assert_cycle(cycle)
    assert_same_instant(cycle["window_start"], "2026-06-08T00:00:00Z", "window_start")
    assert_same_instant(cycle["window_end"], "2026-06-28T00:00:00Z", "window_end")
    assert_same_instant(cycle["ship_date"], "2026-06-08T00:00:00Z", "ship_date")
    assert_same_instant(cycle["cutoff_at"], "2026-06-06T00:00:00Z", "cutoff_at")

    after = read_subscription(api, ctx["subscription"]["id"])
    assert_same_instant(after["anchor_date"], "2026-06-28T00:00:00Z", "anchor_date")


def test_locking_strictly_before_the_cutoff_is_refused(api):
    """PRD §3.5: "Once the logical clock has reached a cycle's `cutoff_at` — the comparison
    is inclusive, so the exact cutoff instant qualifies — an operator locks the cycle,
    moving it `ALLOCATED → CUTOFF_LOCKED`. Attempting the lock strictly before the cutoff is
    refused with `ERR_CUTOFF_NOT_REACHED` (HTTP 409)."

    Design: Corner/state_machines/corner_lock_before_cutoff_rejected
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="lock")
    resp = api.lock_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CUTOFF_NOT_REACHED.value, 409)
    assert read_cycle(api, cycle["id"])["status"] == "ALLOCATED"


def test_revoking_a_skip_rewinds_the_anchor_exactly(api):
    """PRD §3.5: "Skipping *advances* the schedule rather than shortening the subscription:
    `anchor_after` is `anchor_before` plus exactly one `cadence_interval_days`, and the
    subscription's `anchor_date` moves there."
    PRD §3.5: "Withdrawal moves the cycle `SKIPPED → PLANNED`, making the fulfilment axis
    re-entrant, moves the record `APPLIED → REVOKED`, which immediately restores one unit of
    allowance inside the rolling window, and rewinds the subscription's `anchor_date` to the
    record's `anchor_before` exactly."

    Design: Corner/state_machines/corner_skip_revoke_restores_allowance_and_rewinds_anchor
    """
    ctx = setup_household(api, with_sku=False, email_prefix="unskip")
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    validate_success(api.skip_cycle(cycle["id"], ctx["headers"]))

    revoked = validate_success(api.revoke_skip(cycle["id"], ctx["headers"]))
    assert revoked["status"] == "PLANNED"

    records = list_skip_records(api, cycle_id=cycle["id"])
    assert len(records) == 1
    record = records[0]
    assert_skip_record(record)
    assert record["status"] == "REVOKED"
    assert_same_instant(record["anchor_before"], "2026-06-28T00:00:00Z", "anchor_before")
    assert_same_instant(record["anchor_after"], "2026-07-18T00:00:00Z", "anchor_after")

    after = read_subscription(api, ctx["subscription"]["id"])
    assert_same_instant(after["anchor_date"], "2026-06-28T00:00:00Z", "anchor_date")


def test_a_regenerated_window_that_strictly_overlaps_an_existing_one_is_refused(api):
    """PRD §3.5: "And the generated window may not strictly overlap the window of any
    existing cycle of the same subscription whose `status` is not `SKIPPED`, `RETURNED` or
    `CANCELLED`: two windows conflict exactly when the new start is before the existing end
    *and* the existing start is before the new end, so windows that merely touch — where the
    new `window_start` equals an existing `window_end` — never conflict. An overlap is
    refused with `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Corner/calculations/corner_cycle_window_overlap_after_skip_revoke_rewinds_anchor
    """
    ctx = setup_household(api, with_sku=False, email_prefix="overlap")
    subscription_id = ctx["subscription"]["id"]

    first = generate_cycle(api, subscription_id)
    validate_success(api.skip_cycle(first["id"], ctx["headers"]))
    second = generate_cycle(api, subscription_id)
    assert_same_instant(second["window_start"], "2026-07-18T00:00:00Z", "window_start")

    validate_success(api.revoke_skip(first["id"], ctx["headers"]))
    third = generate_cycle(api, subscription_id)
    assert_same_instant(third["window_start"], "2026-06-28T00:00:00Z", "window_start")
    assert_same_instant(third["window_end"], "2026-07-18T00:00:00Z", "window_end")

    resp = api.generate_cycle(subscription_id, OPS)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP.value, 409)

    _listed, meta = validate_paginated(
        api.list_cycles(OPS, {"subscription_id": subscription_id, "limit": 100})
    )
    assert meta["total_count"] == 3


def test_a_paused_household_with_allowance_left_reports_the_pause_refusal(api):
    """PRD §3.5: "A paused subscription may not skip either, and that refusal is
    `ERR_SKIP_WHILE_PAUSED` (HTTP 409). The order of those two checks is pinned and
    observable: the allowance rung is evaluated first, so a paused subscription that still
    has allowance left reports `ERR_SKIP_WHILE_PAUSED`, while a paused subscription whose
    allowance is exhausted reports `ERR_SKIP_ALLOWANCE_EXHAUSTED`."

    Design: Corner/validations/corner_skip_while_paused_rejected_after_allowance_check_passes
    """
    ctx = setup_household(api, with_sku=False, email_prefix="skippause")
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-01", "end_date": "2026-06-20"},
            ctx["headers"],
        ),
        201,
    )

    resp = api.skip_cycle(cycle["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_SKIP_WHILE_PAUSED.value, 409)

    assert read_cycle(api, cycle["id"])["status"] == "PLANNED"
    assert read_subscription(api, ctx["subscription"]["id"])["lifecycle_state"] == "PAUSED"
    assert not list_skip_records(api, subscription_id=ctx["subscription"]["id"])


def _exhaust_the_skip_allowance(api, ctx):
    """Skip the first two generated cycles, then generate a third."""
    subscription_id = ctx["subscription"]["id"]
    first = generate_cycle(api, subscription_id)
    validate_success(api.skip_cycle(first["id"], ctx["headers"]))
    second = generate_cycle(api, subscription_id)
    validate_success(api.skip_cycle(second["id"], ctx["headers"]))
    return generate_cycle(api, subscription_id)


def test_a_third_skip_inside_the_rolling_window_is_refused_on_its_own(api):
    """PRD §3.5: "Skip allowance is rationed: a household may skip twice inside a rolling
    180-day window. The allowance remaining is two minus the number of `SkipRecord` rows on
    that subscription whose `status` is `APPLIED` and whose `created_at` is at or after the
    instant 180 days before the logical clock; a skip is admitted only while at least one
    unit of allowance remains, and otherwise refused with `ERR_SKIP_ALLOWANCE_EXHAUSTED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/past_cutoff_beats_skip_allowance_exhausted
    """
    ctx = setup_household(api, with_sku=False, email_prefix="skip")
    third = _exhaust_the_skip_allowance(api, ctx)
    assert_same_instant(third["cutoff_at"], "2026-08-25T00:00:00Z", "cutoff_at")

    resp = api.skip_cycle(third["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_SKIP_ALLOWANCE_EXHAUSTED.value, 409)
    assert read_cycle(api, third["id"])["status"] == "PLANNED"


def test_past_cutoff_outranks_an_exhausted_skip_allowance(api):
    """PRD §3.5: "A household may skip an upcoming box while it is still `PLANNED` or
    `ALLOCATED` and the logical clock is strictly before `cutoff_at`; at or after the cutoff
    the skip is refused with `ERR_PAST_CUTOFF` (HTTP 409)."
    PRD §2.6: "Every mutating request walks the same nine gates in the same fixed order, and
    the error returned is always the error of the *earliest* gate the request violates."
    PRD §2.6: "8. **Temporal** — cutoffs, windows, interval overlaps and expiries measured
    against the logical clock (rungs 35 through 44)."

    Design: Difficulty/priority_pair_validation_conflict/past_cutoff_beats_skip_allowance_exhausted
    """
    ctx = setup_household(api, with_sku=False, email_prefix="skip2")
    third = _exhaust_the_skip_allowance(api, ctx)
    set_clock(api, "2026-08-26T00:00:00Z")

    resp = api.skip_cycle(third["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_PAST_CUTOFF.value, 409)

    assert read_cycle(api, third["id"])["status"] == "PLANNED"
    assert not list_skip_records(api, cycle_id=third["id"])
