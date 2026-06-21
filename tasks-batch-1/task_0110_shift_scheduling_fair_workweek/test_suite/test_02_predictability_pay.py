"""Predictability pay: clopening rest-gap, short-notice post/cancel accrual.

Covers Difficulty: boundary_precision_check (clopening), transitive_cascade
(short-notice-cancel depth-3 chain). Covers Corner: computed clopening accrual,
short-notice-post accrual, derived projected-cost reconciliation.
"""
from test_helpers import (
    validate_success, get_success_data, make_manager_headers,
    set_clock, setup_location, setup_worker, setup_pay_period,
    create_posted_shift, assign_worker, ledger_entries_for_shift,
)


M = make_manager_headers()


def test_clopening_gap_exactly_threshold_is_not_flagged(api):
    """PRD §3.7: "sets clopening_flag to true exactly when that gap is strictly less
    than the location's minimum rest hours; a gap equal to the threshold is not a
    clopening."

    Prior shift ends 2026-06-02T22:00; new shift starts EXACTLY 10h later at
    2026-06-03T08:00, equal to the 10h rest threshold -> not a clopening.

    Design: Difficulty/boundary_precision_check/clopening_gap_exactly_threshold_not_flagged
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=1,
                         min_rest_hours_between_shifts=10)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sprior = create_posted_shift(api, loc["id"], start_utc="2026-06-02T18:00:00Z",
                                 end_utc="2026-06-02T22:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sprior["id"], worker["id"])
    snew = create_posted_shift(api, loc["id"], start_utc="2026-06-03T08:00:00Z",
                               end_utc="2026-06-03T12:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], snew["id"], worker["id"])
    assert asg["clopening_flag"] is False, "gap == threshold must not flag clopening"
    entries = ledger_entries_for_shift(api, snew["id"], M, reason="CLOPENING")
    assert len(entries) == 0, "no CLOPENING entry when gap equals the threshold"


def test_clopening_gap_below_threshold_flags_and_accrues(api):
    """PRD §3.7: "sets clopening_flag to true exactly when that gap is strictly less
    than the location's minimum rest hours; a gap equal to the threshold is not a
    clopening. When the flag is true and predictability pay is enabled, the system
    appends a clopening ledger entry whose amount is the fixed clopening penalty of
    five thousand cents."

    Prior shift ends 2026-06-02T22:00; new shift starts 8h later (< 10h) ->
    clopening_flag true, one CLOPENING ledger entry of 5000 cents.

    Design: Difficulty/boundary_precision_check/clopening_gap_exactly_threshold_not_flagged
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=1,
                         min_rest_hours_between_shifts=10)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sprior = create_posted_shift(api, loc["id"], start_utc="2026-06-02T18:00:00Z",
                                 end_utc="2026-06-02T22:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sprior["id"], worker["id"])
    snew = create_posted_shift(api, loc["id"], start_utc="2026-06-03T06:00:00Z",
                               end_utc="2026-06-03T10:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], snew["id"], worker["id"])
    assert asg["clopening_flag"] is True, "gap < threshold must flag clopening"
    entries = ledger_entries_for_shift(api, snew["id"], M, reason="CLOPENING")
    assert len(entries) == 1, "exactly one CLOPENING ledger entry"
    assert entries[0]["amount_cents"] == 5000, "clopening penalty is the flat 5000 cents"


def test_clopening_accrual_on_short_rest_computed_field(api):
    """PRD §3.7: "Otherwise the system computes the rest gap in hours between that
    prior shift's end and the new shift's start, and sets clopening_flag to true
    exactly when that gap is strictly less than the location's minimum rest hours."
    PRD §3.7: "When the flag is true and predictability pay is enabled, the system
    appends a clopening ledger entry whose amount is the fixed clopening penalty of
    five thousand cents."

    A new assignment whose worker's prior shift ends 8h before start (< 10h rest)
    sets clopening_flag=true and appends a CLOPENING entry of 5000 cents.

    Design: Corner/entities/computed_clopening_pay_accrual_on_short_rest
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=1,
                         min_rest_hours_between_shifts=10)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sprior = create_posted_shift(api, loc["id"], start_utc="2026-06-02T18:00:00Z",
                                 end_utc="2026-06-02T22:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sprior["id"], worker["id"])
    snew = create_posted_shift(api, loc["id"], start_utc="2026-06-03T06:00:00Z",
                               end_utc="2026-06-03T10:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], snew["id"], worker["id"])
    assert asg["clopening_flag"] is True
    entries = ledger_entries_for_shift(api, snew["id"], M, reason="CLOPENING")
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 5000


def test_short_notice_post_accrues_on_staffing(api):
    """PRD §3.7: "When a worker is then scheduled onto such a shift, a
    SHORT_NOTICE_POST entry accrues whose amount is the shift's duration in hours
    multiplied by the worker's base hourly rate, then multiplied by the
    short-notice-post rate of one quarter, with the result rounded half-up to whole
    cents."

    8h shift posted 1 day before start (inside the 14-day window) then staffed
    accrues SHORT_NOTICE_POST of 8 * 2000 * 0.25 = 4000 cents.

    Design: Corner/cross_cutting_complexity_layers/short_notice_post_pay_accrues_on_staffing
    """
    set_clock(api, "2026-06-04T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=14)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T17:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    entries = ledger_entries_for_shift(api, s["id"], M, reason="SHORT_NOTICE_POST")
    assert len(entries) == 1, "exactly one SHORT_NOTICE_POST entry"
    assert entries[0]["amount_cents"] == 4000, "8h * 2000 * 0.25 = 4000"


def test_shift_cancel_cascades_short_notice_cancel_into_projected_cost(api):
    """PRD §3.4: "if predictability pay is enabled and the gap between the shift's
    start_utc and the current clock is less than the advance-notice window, then for
    each worker who held a now-cancelled assignment the system appends a short-notice
    cancellation entry to the predictability ledger and reconciles the pay-period."
    PRD §3.7: "the SHORT_NOTICE_CANCEL entry's amount is the shift's duration in
    hours multiplied by the worker's base hourly rate, then multiplied by the
    short-notice-cancel rate of one half, rounded half-up to whole cents."

    Depth-3 chain: shift cancel -> assignment CANCELLED -> SHORT_NOTICE_CANCEL entry
    of 6h*2000*0.5 = 6000. After cancel the assignment's provisional cost is removed
    from projected, so projected = the sum of the remaining ledger entries. Because
    the shift was posted on 06-01 with start 06-05 inside the 14-day advance-notice
    window, staffing it earlier already accrued a SHORT_NOTICE_POST entry of
    6h*2000*0.25 = 3000 (§3.7). Both ledger entries survive the cancel, so projected
    reconciles to 3000 + 6000 = 9000.

    Design: Difficulty/transitive_cascade/shift_cancel_cascade_depth3_predictability
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=14)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T15:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    set_clock(api, "2026-06-04T09:00:00Z")
    get_success_data(api.cancel_shift(loc["id"], s["id"], M))
    asg = get_success_data(api.get_assignment(asg["id"], M))
    assert asg["status"] == "CANCELLED"
    shift = get_success_data(api.get_shift(s["id"], M))
    assert shift["status"] == "CANCELLED"
    entries = ledger_entries_for_shift(api, s["id"], M, reason="SHORT_NOTICE_CANCEL")
    assert len(entries) == 1, "exactly one SHORT_NOTICE_CANCEL entry"
    assert entries[0]["amount_cents"] == 6000, "6h * 2000 * 0.5 = 6000"
    post_entries = ledger_entries_for_shift(api, s["id"], M, reason="SHORT_NOTICE_POST")
    assert len(post_entries) == 1, "the in-window post accrued one SHORT_NOTICE_POST entry"
    assert post_entries[0]["amount_cents"] == 3000, "6h * 2000 * 0.25 = 3000"
    pp_data = get_success_data(api.get_pay_period(pp["id"], M))
    assert pp_data["projected_labor_cost_cents"] == 9000, (
        f"projected = SHORT_NOTICE_POST 3000 + SHORT_NOTICE_CANCEL 6000 = 9000, got "
        f"{pp_data['projected_labor_cost_cents']}")


def test_shift_cancel_outside_window_accrues_no_short_notice_cancel(api):
    """PRD §3.4: "if predictability pay is enabled and the gap between the shift's
    start_utc and the current clock is less than the advance-notice window, then for
    each worker who held a now-cancelled assignment the system appends a short-notice
    cancellation entry to the predictability ledger and reconciles the pay-period."

    Boundary partner: with a 1-day advance-notice window and the cancel happening
    well before the shift (gap far larger than the window), no SHORT_NOTICE_CANCEL
    entry accrues and projected cost returns to 0.

    Design: Difficulty/transitive_cascade/shift_cancel_cascade_depth3_predictability
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=True, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T15:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    # Cancel ~4 days before the shift; gap (96h) >> 24h window -> not short notice.
    get_success_data(api.cancel_shift(loc["id"], s["id"], M))
    asg = get_success_data(api.get_assignment(asg["id"], M))
    assert asg["status"] == "CANCELLED"
    entries = ledger_entries_for_shift(api, s["id"], M, reason="SHORT_NOTICE_CANCEL")
    assert len(entries) == 0, "no SHORT_NOTICE_CANCEL when cancel is outside the window"
    pp_data = get_success_data(api.get_pay_period(pp["id"], M))
    assert pp_data["projected_labor_cost_cents"] == 0


def test_projected_cost_reconciled_after_assignment(api):
    """PRD §3.10: "A pay-period exposes its projected_labor_cost_cents as a read-only
    field reconciled on every assignment or ledger change."
    PRD §3.8: "the regular hours are the overtime threshold minus the prior-week
    hours, clamped to lie between zero and the shift's hours, and the overtime hours
    are whatever of the shift's hours remain above that."

    After one 8h assignment (base 2000, all regular) the pay-period's
    projected_labor_cost_cents reconciles to 16000.

    Design: Corner/cross_cutting_complexity_layers/derived_projected_cost_reconciled_after_assign
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    pp_data = get_success_data(api.get_pay_period(pp["id"], M))
    assert pp_data["projected_labor_cost_cents"] == 16000
