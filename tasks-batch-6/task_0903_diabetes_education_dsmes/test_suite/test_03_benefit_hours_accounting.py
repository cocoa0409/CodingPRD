"""DSMT benefit-hour accounting: dual provisional/final totals, per-session
rounding order, the cap boundary, and hour conservation on cancel.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula,
boundary_precision_check, compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- dv_provisional_vs_final_benefit_hours ---
def test_provisional_hours_used_counts_scheduled_and_completed(api):
    """PRD §2.8: "`provisional_hours_used` is the sum of per-session provisional
    hours over every session of the enrollment whose `encounter_status` is
    `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; sessions in `NO_SHOW` or
    `CANCELLED` are excluded from this sum."

    One 60-min session completed (actual 45) plus one 90-min session still
    scheduled: provisional_hours_used = 1.0 + 1.5 = 2.5.

    Design: Difficulty/dual_variant_calc/dv_provisional_vs_final_benefit_hours
    """
    ctx = setup_active_enrollment(api)
    sa = th.schedule_individual_session_ok(api, ctx, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    th.schedule_individual_session_ok(api, ctx, "2026-05-11T09:00:00Z", "2026-05-11T10:30:00Z")
    th.complete(api, ctx, sa["id"], 45)
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["provisional_hours_used"] == 2.5, \
        f"provisional_hours_used must be 2.5, got {enr['provisional_hours_used']}"


def test_final_hours_used_counts_only_completed_actuals(api):
    """PRD §2.8: "`final_hours_used` is the sum of per-session final hours over
    only the sessions in `COMPLETED`."

    Same setup as its sibling: only the 60-min session is completed (actual 45),
    so final_hours_used = floor(45/30)*0.5 = 0.5.

    Design: Difficulty/dual_variant_calc/dv_provisional_vs_final_benefit_hours
    """
    ctx = setup_active_enrollment(api)
    sa = th.schedule_individual_session_ok(api, ctx, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    th.schedule_individual_session_ok(api, ctx, "2026-05-11T09:00:00Z", "2026-05-11T10:30:00Z")
    th.complete(api, ctx, sa["id"], 45)
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["final_hours_used"] == 0.5, \
        f"final_hours_used must be 0.5, got {enr['final_hours_used']}"


# --- cb_per_session_round_then_sum_hours ---
def test_final_hours_round_each_session_then_sum(api):
    """PRD §2.8: "each session is rounded to whole 30-minute units first, and only
    then are per-session hours summed at the enrollment level."

    Two completed sessions of actual 50 and 40 minutes: floor(50/30)+floor(40/30)
    = 1+1 = 2 units = 1.0h — NOT sum-then-round floor(90/30)=3 units=1.5h.

    Design: Difficulty/combinatorial_formula/cb_per_session_round_then_sum_hours
    """
    ctx = setup_active_enrollment(api)
    s1 = th.schedule_individual_session_ok(api, ctx, "2026-05-08T09:00:00Z", "2026-05-08T10:00:00Z")
    s2 = th.schedule_individual_session_ok(api, ctx, "2026-05-08T11:00:00Z", "2026-05-08T12:00:00Z")
    th.complete(api, ctx, s1["id"], 50)
    th.complete(api, ctx, s2["id"], 40)
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["final_hours_used"] == 1.0, \
        f"round-each-then-sum must yield 1.0, got {enr['final_hours_used']}"


def test_per_session_final_hours_floored_individually(api):
    """PRD §2.8: "A single session's forward-looking provisional hours equal the
    whole units in its planned duration times 0.5, and its realized final hours
    equal the whole units in its actual face-to-face duration times 0.5."

    Each session's own final_hours floors independently: 50 min and 40 min both
    yield floor(min/30)*0.5 = 0.5.

    Design: Difficulty/combinatorial_formula/cb_per_session_round_then_sum_hours
    """
    ctx = setup_active_enrollment(api)
    s1 = th.schedule_individual_session_ok(api, ctx, "2026-05-08T09:00:00Z", "2026-05-08T10:00:00Z")
    s2 = th.schedule_individual_session_ok(api, ctx, "2026-05-08T11:00:00Z", "2026-05-08T12:00:00Z")
    c1 = th.complete(api, ctx, s1["id"], 50)
    c2 = th.complete(api, ctx, s2["id"], 40)
    assert c1["final_hours"] == 0.5, f"50-min session final_hours must be 0.5, got {c1['final_hours']}"
    assert c2["final_hours"] == 0.5, f"40-min session final_hours must be 0.5, got {c2['final_hours']}"


# --- bp_benefit_hours_cap_exact_boundary ---
def test_session_at_exact_cap_accepted(api):
    """PRD §2.8: "For an initial benefit year (`benefit_year_index` of 0) the cap
    is 10.0 hours".
    PRD §2.8: "`hours_remaining` is `benefit_hours_cap` minus
    `provisional_hours_used`."

    A 600-min session equals exactly 10.0h == cap and is accepted, leaving
    hours_remaining 0.0.

    Design: Difficulty/boundary_precision_check/bp_benefit_hours_cap_exact_boundary
    """
    ctx = setup_active_enrollment(api)
    th.schedule_individual_session_ok(api, ctx, "2026-06-01T08:00:00Z", "2026-06-01T18:00:00Z")
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["provisional_hours_used"] == 10.0, \
        f"provisional_hours_used must be 10.0 at cap, got {enr['provisional_hours_used']}"
    assert enr["hours_remaining"] == 0.0, \
        f"hours_remaining must be 0.0 at cap, got {enr['hours_remaining']}"


def test_session_past_cap_rejected(api):
    """PRD §3.4: "if `provisional_hours_used` plus this session's
    `provisional_hours` would exceed `benefit_hours_cap`, the request is rejected
    with `ERR_BENEFIT_HOURS_EXCEEDED`."

    With provisional_hours_used already at the 10.0 cap, a further 30-min session
    (10.5h > cap) is rejected — the boundary is strict >.

    Design: Difficulty/boundary_precision_check/bp_benefit_hours_cap_exact_boundary
    """
    ctx = setup_active_enrollment(api)
    th.schedule_individual_session_ok(api, ctx, "2026-06-01T08:00:00Z", "2026-06-01T18:00:00Z")
    resp = th.schedule_individual_session(api, ctx, "2026-06-02T08:00:00Z", "2026-06-02T08:30:00Z")
    validate_error(resp, ApiErrorId.ERR_BENEFIT_HOURS_EXCEEDED.value)


# --- ci_benefit_hours_conserved_on_cancel ---
def test_cancel_restores_provisional_hours_used(api):
    """PRD §3.6: "Cancelling reverses the session's `provisional_hours` from the
    enrollment's `provisional_hours_used` (and recomputes `hours_remaining`)".

    Scheduling a 60-min session debits 1.0h; cancelling it credits exactly 1.0h
    back, restoring provisional_hours_used to 0.0.

    Design: Difficulty/compensating_invariant/ci_benefit_hours_conserved_on_cancel
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-21T09:00:00Z", "2026-05-21T10:00:00Z")
    before = th.get_enrollment(api, ctx["enrollment_id"])
    assert before["provisional_hours_used"] == 1.0, \
        f"pre-cancel provisional_hours_used must be 1.0, got {before['provisional_hours_used']}"
    th.cancel(api, ctx, sess["id"], cancel_reason="patient reschedule")
    after = th.get_enrollment(api, ctx["enrollment_id"])
    assert after["provisional_hours_used"] == 0.0, \
        f"post-cancel provisional_hours_used must be 0.0, got {after['provisional_hours_used']}"


def test_cancel_restores_hours_remaining(api):
    """PRD §3.6: "Cancelling reverses the session's `provisional_hours` from the
    enrollment's `provisional_hours_used` (and recomputes `hours_remaining`)".

    hours_remaining returns to the full 10.0 cap after the only session is
    cancelled.

    Design: Difficulty/compensating_invariant/ci_benefit_hours_conserved_on_cancel
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-21T09:00:00Z", "2026-05-21T10:00:00Z")
    th.cancel(api, ctx, sess["id"])
    after = th.get_enrollment(api, ctx["enrollment_id"])
    assert after["hours_remaining"] == 10.0, \
        f"post-cancel hours_remaining must be 10.0, got {after['hours_remaining']}"
