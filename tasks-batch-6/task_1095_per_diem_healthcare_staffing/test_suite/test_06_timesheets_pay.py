"""Timesheets: hour normalization, differentials, weekly overtime, the
dispute/resubmit cycle, the estimated-vs-final pay divergence, the crisis /
night / weekend stacked pay formula, and the submission-window guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_verifier_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------- #
# Corner: hour normalization & submission guards
# --------------------------------------------------------------------------- #
def test_resubmit_from_submitted_returns_not_resubmittable(api):
    """PRD 3.6: "Resubmitting a timesheet that is not `DISPUTED` raises
    `ERR_TIMESHEET_NOT_RESUBMITTABLE`."

    Design: Corner/state_machines/resubmit_from_submitted_returns_timesheet_not_resubmittable
    """
    bundle = fx.setup_submitted_timesheet(facility_overrides={"name": "Glenmoor"})
    fac_id, cl_id, ts = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["timesheet"]
    resp = api.resubmit_timesheet(
        ts["id"], {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T20:00:00Z", "break_minutes": 0},
        make_clinician_headers(cl_id),
    )
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_NOT_RESUBMITTABLE.value, 409)
    got = validate_success(api.get_timesheet(ts["id"], ADMIN), 200)
    assert got["status"] == "SUBMITTED" and got["dispute_count"] == 0
    # clock_out is a client-supplied punch; PRD's 3-fractional-digit render rule (§2)
    # covers server-stamped fields only, so the impl echoes the submitted value verbatim.
    assert got["clock_out"] == "2026-06-08T19:00:00Z"
    assert got["break_minutes"] == 30 and got["worked_hours"] == 11.50


def test_unpaid_break_forced_to_thirty_on_long_shift(api):
    """PRD 3.6: "The deemed unpaid break, `unpaid_break_minutes`, is 30 minutes when
    `raw_minutes` is at least 360 and the reported `break_minutes` is under 30;
    otherwise it equals the reported `break_minutes`."

    Design: Corner/calculations/unpaid_break_forced_to_thirty_when_under_reported_on_long_shift
    """
    bundle = fx.setup_confirmed_assignment(facility_overrides={"name": "Halcyon"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T19:30:00Z")
    ts = validate_success(
        api.submit_timesheet(asg["id"],
                             {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T19:00:00Z", "break_minutes": 10},
                             make_clinician_headers(cl_id)), 201)
    assert ts["raw_minutes"] == 720
    assert ts["unpaid_break_minutes"] == 30
    assert ts["worked_hours"] == 11.50
    assert ts["break_minutes"] == 10
    assert ts["status"] == "SUBMITTED"


def test_short_shift_keeps_reported_zero_break(api):
    """PRD 3.6: "In effect, a short shift under 360 raw minutes with a reported break
    of 0 keeps a zero break, while a long shift with an under-reported break is
    force-deducted to 30 minutes."

    Design: Corner/calculations/short_shift_keeps_reported_zero_break
    """
    bundle = fx.setup_confirmed_assignment(
        facility_overrides={"name": "Ivory Coast Med"},
        shift_overrides={"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T11:00:00Z"},
    )
    fac_id, cl_id, asg, shift = (
        bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"], bundle["shift"])
    assert shift["estimated_pay_cents"] == 30000
    fx.set_clock("2026-06-08T11:30:00Z")
    ts = fx.submit_timesheet(asg["id"], cl_id,
                             clock_in="2026-06-08T07:00:00Z", clock_out="2026-06-08T11:00:00Z", break_minutes=0)
    verified = fx.verify_timesheet(ts["id"], fac_id)
    assert ts["raw_minutes"] == 240
    assert verified["unpaid_break_minutes"] == 0
    assert verified["worked_hours"] == 4.00
    assert verified["night_hours"] == 0.00 and verified["weekend_hours"] == 0.00
    assert verified["gross_pay_cents"] == 30000


def test_timesheet_before_shift_end_returns_shift_not_ended(api):
    """PRD 3.6: "Submission is also gated temporally: the current instant must be at or
    after the shift's `scheduled_end`, or it fails with `ERR_SHIFT_NOT_ENDED`".

    Design: Corner/validations/timesheet_before_shift_end_returns_shift_not_ended
    """
    bundle = fx.setup_confirmed_assignment(facility_overrides={"name": "Zinnia"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T12:00:00Z")
    resp = api.submit_timesheet(asg["id"],
                                {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T11:30:00Z", "break_minutes": 0},
                                make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_ENDED.value, 422)
    got = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert got["pay_status"] == "UNBILLED" and got["work_status"] == "CONFIRMED"
    ts, meta = validate_paginated(api.list_assignment_timesheets(asg["id"], make_scheduler_headers(fac_id)))
    assert meta["total_count"] == 0


def test_timesheet_after_submission_window_returns_window_closed(api):
    """PRD 3.6: "and it must be within 7 days after the shift's `scheduled_end`, or it
    fails with `ERR_TIMESHEET_WINDOW_CLOSED`."

    Design: Corner/validations/timesheet_after_submission_window_returns_window_closed
    """
    bundle = fx.setup_confirmed_assignment(facility_overrides={"name": "Amberly"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-16T00:00:00Z")
    resp = api.submit_timesheet(asg["id"],
                                {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T19:00:00Z", "break_minutes": 30},
                                make_clinician_headers(cl_id))
    err = validate_error(resp, ApiErrorId.ERR_TIMESHEET_WINDOW_CLOSED.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_SHIFT_NOT_ENDED.value
    ts, meta = validate_paginated(api.list_assignment_timesheets(asg["id"], make_scheduler_headers(fac_id)))
    assert meta["total_count"] == 0


def test_inverted_punch_interval_returns_invalid_punch_interval(api):
    """PRD 3.6: "The punch interval itself is validated: `clock_out` must be strictly
    after `clock_in`, and the punched interval must lie within the shift's scheduled
    interval widened by 4 hours on each side — that is, no earlier than
    `scheduled_start` minus 4 hours and no later than `scheduled_end` plus 4 hours — or
    the request fails with `ERR_INVALID_PUNCH_INTERVAL`."

    Design: Corner/validations/inverted_punch_interval_returns_invalid_punch_interval
    """
    bundle = fx.setup_confirmed_assignment(facility_overrides={"name": "Bellwether"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T19:30:00Z")
    resp = api.submit_timesheet(asg["id"],
                                {"clock_in": "2026-06-08T19:00:00Z", "clock_out": "2026-06-08T07:00:00Z", "break_minutes": 30},
                                make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_PUNCH_INTERVAL.value, 400)
    got = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert got["work_status"] == "CONFIRMED" and got["pay_status"] == "UNBILLED"


# --------------------------------------------------------------------------- #
# Difficulty: estimated vs final pay diverges on punch drift
# --------------------------------------------------------------------------- #
def _setup_punch_drift_timesheet():
    bundle = fx.setup_confirmed_assignment(
        facility_overrides={"name": "Mercy General"},
        clinician_overrides={"full_name": "Ana Reyes", "email": "ana.reyes@example.com"},
        shift_overrides={"scheduled_start": "2026-06-10T07:00:00Z", "scheduled_end": "2026-06-10T19:00:00Z"},
    )
    fac_id, cl_id, asg, shift = (
        bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"], bundle["shift"])
    fx.set_clock("2026-06-10T19:45:00Z")
    ts = fx.submit_timesheet(asg["id"], cl_id,
                             clock_in="2026-06-10T07:00:00Z", clock_out="2026-06-10T19:30:00Z", break_minutes=30)
    verified = fx.verify_timesheet(ts["id"], fac_id)
    return fac_id, asg, shift, verified


def test_estimated_vs_final_pay_diverges_amounts(api):
    """PRD 3.6: "`gross_pay_cents` is the sum of the regular, overtime, and
    differential components; the rounding is applied per component and never to the
    final sum."
    PRD 3.6: "When the scheduled and actual intervals coincide and no weekly overtime
    applies, the two variants agree; any punch drift or weekly overtime makes them
    diverge."

    Design: Difficulty/dual_variant_calc/estimated_vs_final_shift_pay_diverges_on_punch_drift
    """
    fac_id, asg, shift, verified = _setup_punch_drift_timesheet()
    assert shift["estimated_pay_cents"] == 86250
    assert asg["estimated_pay_cents"] == 86250
    assert verified["gross_pay_cents"] == 90225
    final_asg = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert final_asg["final_pay_cents"] == 90225
    assert final_asg["final_pay_cents"] - final_asg["estimated_pay_cents"] == 3975


def test_estimated_vs_final_pay_final_hour_breakdown(api):
    """PRD 3.6: "`night_hours` is the count of minutes of that interval whose UTC wall
    time falls in the night window, which runs from 19:00 up to midnight and from
    midnight up to 07:00, divided by 60 to two decimals."
    PRD 3.6: "`worked_hours` is then `raw_minutes` minus `unpaid_break_minutes`, divided
    by 60, to two decimals."

    Design: Difficulty/dual_variant_calc/estimated_vs_final_shift_pay_diverges_on_punch_drift
    """
    fac_id, asg, shift, verified = _setup_punch_drift_timesheet()
    assert verified["raw_minutes"] == 750
    assert verified["unpaid_break_minutes"] == 30
    assert verified["worked_hours"] == 12.00
    assert verified["night_hours"] == 0.50
    assert verified["weekend_hours"] == 0.00
    assert verified["overtime_hours"] == 0.00


# --------------------------------------------------------------------------- #
# Difficulty: crisis + night + weekend stacked pay
# --------------------------------------------------------------------------- #
def _setup_crisis_night_weekend_timesheet():
    bundle = fx.setup_confirmed_assignment(
        facility_overrides={"name": "Harbor Point", "unit_name": "ED"},
        clinician_overrides={"full_name": "Cira Nunez", "email": "cira.nunez@example.com"},
        order_overrides={"urgency": "CRISIS", "window_start": "2026-06-13T00:00:00Z", "window_end": "2026-06-15T00:00:00Z"},
        shift_overrides={"scheduled_start": "2026-06-13T19:00:00Z", "scheduled_end": "2026-06-14T07:00:00Z"},
    )
    fac_id, cl_id, asg, shift = (
        bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"], bundle["shift"])
    fx.set_clock("2026-06-14T08:00:00Z")
    ts = fx.submit_timesheet(asg["id"], cl_id,
                             clock_in="2026-06-13T19:00:00Z", clock_out="2026-06-14T07:00:00Z", break_minutes=30)
    verified = fx.verify_timesheet(ts["id"], fac_id)
    return fac_id, shift, verified


def test_crisis_night_weekend_pay_frozen_rate_and_total(api):
    """PRD 3.3: "when the order's urgency is `CRISIS`, the effective rate is the base
    rate multiplied by 1.25 and rounded half-up to whole cents once; otherwise the
    effective rate equals the base rate."
    PRD 3.6: "The differential component is the sum of two independently rounded
    pieces: `night_hours` times 450 cents per hour rounded half-up, plus `weekend_hours`
    times 300 cents per hour rounded half-up."

    Design: Difficulty/combinatorial_formula/crisis_night_weekend_stacked_pay_mode_a
    """
    fac_id, shift, verified = _setup_crisis_night_weekend_timesheet()
    assert shift["base_pay_rate_cents_per_hour"] == 7500
    assert shift["effective_rate_cents_per_hour"] == 9375
    assert shift["estimated_pay_cents"] == 116813
    assert verified["gross_pay_cents"] == 116813


def test_crisis_night_weekend_pay_hour_breakdown(api):
    """PRD 3.6: "The two windows can overlap: a minute at, say, 22:00 on a Saturday
    counts toward both and earns both differentials."
    PRD 3.6: "`weekend_hours` is the count of minutes of that interval whose UTC calendar
    day is Saturday or Sunday, divided by 60 to two decimals."

    Design: Difficulty/combinatorial_formula/crisis_night_weekend_stacked_pay_mode_a
    """
    fac_id, shift, verified = _setup_crisis_night_weekend_timesheet()
    assert verified["worked_hours"] == 11.50
    assert verified["night_hours"] == 12.00
    assert verified["weekend_hours"] == 12.00
    assert verified["overtime_hours"] == 0.00
    assert verified["regular_hours"] == 11.50


# --------------------------------------------------------------------------- #
# Difficulty: dispute/resubmit cycle bounded at two rounds
# --------------------------------------------------------------------------- #
def _setup_two_round_disputed_timesheet():
    bundle = fx.setup_submitted_timesheet(facility_overrides={"name": "Bay Crest", "unit_name": "OR"})
    fac_id, cl_id, ts = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["timesheet"]
    verifier = make_verifier_headers(fac_id)
    clinician = make_clinician_headers(cl_id)
    fx.api_client.dispute_timesheet(ts["id"], {"reason": "missing meal break attestation"}, verifier)
    fx.api_client.resubmit_timesheet(
        ts["id"], {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T19:00:00Z", "break_minutes": 45}, clinician)
    fx.api_client.dispute_timesheet(ts["id"], {"reason": "punch-out still disagrees with badge log"}, verifier)
    resubmitted = fx.api_client.resubmit_timesheet(
        ts["id"], {"clock_in": "2026-06-08T07:00:00Z", "clock_out": "2026-06-08T18:45:00Z", "break_minutes": 30}, clinician)
    assert resubmitted.status_code < 300, resubmitted.text
    assert resubmitted.json()["data"]["dispute_count"] == 2
    return fac_id, cl_id, ts["id"]


def test_third_dispute_refused_with_limit_reached(api):
    """PRD 3.6: "a third dispute attempt — one made when `dispute_count` has already
    reached 2 — is refused with `ERR_DISPUTE_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/timesheet_dispute_resubmit_cycle_bounded_at_two_rounds
    """
    fac_id, cl_id, ts_id = _setup_two_round_disputed_timesheet()
    resp = api.dispute_timesheet(ts_id, {"reason": "third round"}, make_verifier_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value, 409)
    got = validate_success(api.get_timesheet(ts_id, ADMIN), 200)
    assert got["status"] == "SUBMITTED"
    assert got["dispute_count"] == 2


def test_dispute_count_not_reset_on_resubmit(api):
    """PRD 3.6: "Crucially, `dispute_count` is not reset on resubmission — that is what
    bounds the dispute/resubmit loop to at most two rounds."

    Design: Difficulty/non_linear_state_machine/timesheet_dispute_resubmit_cycle_bounded_at_two_rounds
    """
    fac_id, cl_id, ts_id = _setup_two_round_disputed_timesheet()
    got = validate_success(api.get_timesheet(ts_id, ADMIN), 200)
    assert got["dispute_count"] == 2
    assert got["break_minutes"] == 30
    assert got["worked_hours"] == 11.25


# --------------------------------------------------------------------------- #
# Difficulty & Corner: weekly overtime boundary at exactly 40 hours
# --------------------------------------------------------------------------- #
def _setup_four_shift_week(facility_name="Summit Park", fourth_end="2026-06-11T10:30:00Z", fourth_break=0):
    """Same clinician, four shifts in the ISO week starting Monday 2026-06-08. The
    first three are 12.00 worked-hour shifts (cumulative_before 36.00); the fourth is
    controllable. Returns (fac_id, cl_id, [ts_a, ts_b, ts_c, ts_d ids])."""
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": facility_name}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id, headcount=4)
    specs = [
        ("2026-06-08T06:30:00Z", "2026-06-08T19:00:00Z", 30),
        ("2026-06-09T06:30:00Z", "2026-06-09T19:00:00Z", 30),
        ("2026-06-10T06:30:00Z", "2026-06-10T19:00:00Z", 30),
        ("2026-06-11T06:30:00Z", fourth_end, fourth_break),
    ]
    assignments = []
    for start, end, _brk in specs:
        sh = fx.add_shift(order["id"], fac_id, scheduled_start=start, scheduled_end=end)
        clm = fx.place_claim(sh["id"], cl_id)
        asg = fx.award(sh["id"], fac_id, claim_id=clm["id"])
        fx.confirm(asg["id"], cl_id)
        assignments.append(asg)
    fx.set_clock("2026-06-11T11:00:00Z")
    ts_ids = []
    for (start, end, brk), asg in zip(specs, assignments):
        ts = fx.submit_timesheet(asg["id"], cl_id, clock_in=start, clock_out=end, break_minutes=brk)
        ts_ids.append(ts["id"])
    return fac_id, cl_id, ts_ids


def test_overtime_just_over_forty_splits_regular_and_premium(api):
    """PRD 3.6: "This timesheet's `overtime_hours` is the portion of its
    `worked_hours` that pushes the running weekly total past 40 hours: it is the smaller
    of this timesheet's `worked_hours` and (the prior cumulative plus this timesheet's
    `worked_hours` minus 40), floored at zero, to two decimals."
    PRD 3.6: "The overtime component is `overtime_hours` times the effective rate times
    1.5, rounded half-up to whole cents."

    Design: Corner/calculations/overtime_just_over_forty_splits_regular_and_premium
    """
    fac_id, cl_id, ts_ids = _setup_four_shift_week(
        facility_name="Juniper Park", fourth_end="2026-06-11T11:00:00Z", fourth_break=0)
    for ts_id in ts_ids[:3]:
        fx.verify_timesheet(ts_id, fac_id)
    fourth = fx.verify_timesheet(ts_ids[3], fac_id)
    assert fourth["worked_hours"] == 4.50
    assert fourth["overtime_hours"] == 0.50
    assert fourth["regular_hours"] == 4.00
    assert fourth["night_hours"] == 0.50
    assert fourth["gross_pay_cents"] == 35850


def test_overtime_exactly_forty_hours_yields_zero_premium(api):
    """PRD 3.6: "The 40-hour boundary is strict: when the prior cumulative plus this
    timesheet's `worked_hours` equals exactly 40.00, `overtime_hours` is 0.00, and at
    40.01 it is 0.01."

    Design: Difficulty/boundary_precision_check/overtime_exactly_forty_hours_yields_zero_premium
    """
    fac_id, cl_id, ts_ids = _setup_four_shift_week()
    for ts_id in ts_ids[:3]:
        fx.verify_timesheet(ts_id, fac_id)
    fourth = fx.verify_timesheet(ts_ids[3], fac_id)
    assert fourth["worked_hours"] == 4.00
    assert fourth["overtime_hours"] == 0.00
    assert fourth["regular_hours"] == 4.00
    assert fourth["night_hours"] == 0.50
    assert fourth["gross_pay_cents"] == 30225


def test_overtime_boundary_siblings_and_pending_pay(api):
    """PRD 3.6: "Only already-verified siblings count toward the prior cumulative —
    `SUBMITTED` and `DISPUTED` siblings are excluded — so the accumulator advances in
    verification order, and once written, `overtime_hours` and `regular_hours` are
    frozen and not retro-adjusted when a later sibling is verified."
    PRD 2.9: "`pending_pay_cents` is the sum of `gross_pay_cents` over the facility's
    timesheets that are `VERIFIED` — billable but not yet placed on an invoice."

    Design: Difficulty/boundary_precision_check/overtime_exactly_forty_hours_yields_zero_premium
    """
    fac_id, cl_id, ts_ids = _setup_four_shift_week()
    for ts_id in ts_ids[:3]:
        v = fx.verify_timesheet(ts_id, fac_id)
        assert v["worked_hours"] == 12.00 and v["gross_pay_cents"] == 90225
    fx.verify_timesheet(ts_ids[3], fac_id)
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["pending_pay_cents"] == 300900
