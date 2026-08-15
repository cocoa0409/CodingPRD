"""Hour logs, fundraising credit (provisional vs settled, tiered pricing,
sponsor match) and recognition points (PRD §3.8, §3.9).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_volunteer_headers, make_group_leader_headers,
    validate_success, validate_error, validate_paginated,
    set_clock,
    setup_event_with_shift, add_group, add_shift, add_role, create_event,
    register_eligible_volunteer, enroll_and_pass,
    request_signup, approve_signup, confirm_signup, create_confirmed_signup,
    lock_and_start_race_day, check_in_signup,
    check_out_signup, check_out_and_fetch_log, fetch_hour_log_for_signup,
    verify_log, setup_race_day_with_confirmed,
    setup_debrief_open_with_captain,
    assert_credit_summary, assert_recognition_summary, assert_hour_log,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _setup_credit_run(api, credit_weight=1.0, headcount=5,
                      shift_start="2026-10-04T06:00:00Z",
                      shift_end="2026-10-04T14:00:00Z",
                      role_overrides=None, work_specs=None):
    """Published event (one role, one shift), one fundraising group, and one
    affiliated volunteer per work spec, each signed up REQUESTED -> APPROVED
    -> CONFIRMED; the event is then walked to RACE_DAY and every volunteer is
    checked in at the shift start and out at their spec's "out" instant.

    work_specs: [{"name": ..., "dob": ..., "out": ..., "break_minutes": 0?}]
    Returns (ctx, group, rows) where rows are [volunteer, signup, hour_log].
    """
    ro = {"credit_weight": credit_weight}
    if role_overrides:
        ro.update(role_overrides)
    ctx = setup_event_with_shift(
        publish=True, role_overrides=ro,
        shift_overrides={"start_at": shift_start, "end_at": shift_end,
                         "required_headcount": headcount})
    ev = ctx["event"]["id"]
    grp = add_group(ev)
    rows = []
    for spec in work_specs or []:
        vol = register_eligible_volunteer(ev, full_name=spec["name"],
                                          date_of_birth=spec["dob"],
                                          group_id=grp["id"])
        sg = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
        rows.append([vol, sg, None])
    lock_and_start_race_day(ev)
    for row in rows:
        set_clock(shift_start)
        check_in_signup(row[1]["id"])
    for row, spec in zip(rows, work_specs or []):
        row[2] = check_out_and_fetch_log(row[1]["id"], spec["out"],
                                         break_minutes=spec.get("break_minutes"))
    return ctx, grp, rows


def _credit_summary(group_id, headers=DIRECTOR):
    data = validate_success(api_client.get_credit_summary(group_id, headers))
    assert_credit_summary(data)
    return data


# ---------------------------------------------------------------------------
# Dual-variant divergence (PRD §3.8)
# ---------------------------------------------------------------------------

def _setup_provisional_vs_settled(api):
    """V1 worked 4h (log VERIFIED), V2 worked 6h (log PENDING_VERIFICATION),
    role weight 1.0. Clock ends at 2026-10-04T12:00:00Z, event RACE_DAY."""
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=1.0, headcount=5,
        shift_start="2026-10-04T06:00:00Z", shift_end="2026-10-04T14:00:00Z",
        work_specs=[{"name": "V One", "dob": "2000-01-01", "out": "2026-10-04T10:00:00Z"},
                    {"name": "V Two", "dob": "1999-05-05", "out": "2026-10-04T12:00:00Z"}])
    verify_log(rows[0][2]["id"])
    return ctx, grp, rows


def test_credit_provisional_variant_counts_unverified_claimed(api):
    """PRD §3.8: "The provisional variant pools the group's logs in
    `PENDING_VERIFICATION`, `VERIFIED`, or `DISPUTED` status:
    `provisional_effective_hours` is the sum of their effective claimed hours,
    and `provisional_credit_cents` prices that sum."
    PRD §3.8: "With identical data the provisional figure is never smaller
    than the settled one — it counts a larger pool at unrounded claimed hours."

    Design: Difficulty/dual_variant_calc/credit_provisional_vs_settled_diverge
    """
    ctx, grp, rows = _setup_provisional_vs_settled(api)
    summary = _credit_summary(grp["id"])
    assert summary["provisional_effective_hours"] == pytest.approx(10.0, abs=0.001), \
        "4.00 claimed (VERIFIED) + 6.00 claimed (PENDING)"
    assert summary["provisional_credit_cents"] == 5000
    assert summary["provisional_credit_cents"] != summary["settled_credit_cents"], \
        "identical data, two variants, different cents"


def test_credit_settled_variant_counts_verified_only(api):
    """PRD §3.8: "The settled variant admits `VERIFIED` logs only:
    `settled_effective_hours` is the sum of their effective hours, and
    `settled_credit_cents` prices it."
    PRD §3.8: "Step two selects the match percentage from the base alone:
    twenty-five percent when the base reaches 250,000 cents, fifteen percent
    when it reaches 50,000 cents, and five percent otherwise"

    Design: Difficulty/dual_variant_calc/credit_provisional_vs_settled_diverge
    """
    ctx, grp, rows = _setup_provisional_vs_settled(api)
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(4.0, abs=0.001)
    assert summary["settled_credit_cents"] == 2000
    assert summary["sponsor_match_cents"] == 100, "base 2000 < 50000 -> five percent"
    assert summary["total_settled_credit_cents"] == 2100


# ---------------------------------------------------------------------------
# Weighted tier straddle (PRD §3.8)
# ---------------------------------------------------------------------------

def _setup_tier_straddle(api):
    """Role weight 3.0; three volunteers each work 06:00-22:00 (16.00
    credited hours -> 48.00 effective each); all logs VERIFIED."""
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=3.0, headcount=3,
        shift_start="2026-10-04T06:00:00Z", shift_end="2026-10-04T22:00:00Z",
        role_overrides={"role_code": "HEAVY", "title": "Heavy Marshal"},
        work_specs=[{"name": "V One", "dob": "2000-01-01", "out": "2026-10-04T22:00:00Z"},
                    {"name": "V Two", "dob": "2000-01-02", "out": "2026-10-04T22:00:00Z"},
                    {"name": "V Three", "dob": "2000-01-03", "out": "2026-10-04T22:00:00Z"}])
    for row in rows:
        verify_log(row[2]["id"])
    return ctx, grp, rows


def test_tier_straddle_settled_hours_and_cents(api):
    """PRD §3.8: "Pricing is marginal across three slices, each slice rounded
    half up to a whole cent before the slices are summed: the first one
    hundred hours earn five hundred cents per hour; hours beyond the first
    hundred, up to a cumulative five hundred, earn eight hundred cents per
    hour; and all hours beyond five hundred earn twelve hundred cents per
    hour."
    PRD §3.8: "Per log, the system derives two weighted figures: effective
    hours, the log's `credited_hours` multiplied by the `credit_weight` of the
    role catalog entry behind the log's signup's shift and rounded half up to
    two decimal places"

    Design: Difficulty/combinatorial_formula/tiered_credit_weighted_straddle
    """
    ctx, grp, rows = _setup_tier_straddle(api)
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(144.0, abs=0.001), \
        "3 x round_half_up(16.00 x 3.0, 2)"
    assert summary["settled_credit_cents"] == 85200, "100 x 500 + 44 x 800"


def test_tier_straddle_match_and_provisional(api):
    """PRD §3.8: "Step two selects the match percentage from the base alone:
    twenty-five percent when the base reaches 250,000 cents, fifteen percent
    when it reaches 50,000 cents, and five percent otherwise; the tier is
    never re-evaluated against the final total. Step three sets
    `sponsor_match_cents` to the base multiplied by the selected percentage,
    rounded half up to a whole cent. Step four sets
    `total_settled_credit_cents` to the base plus the match."

    Design: Difficulty/combinatorial_formula/tiered_credit_weighted_straddle
    """
    ctx, grp, rows = _setup_tier_straddle(api)
    summary = _credit_summary(grp["id"])
    assert summary["sponsor_match_cents"] == 12780, "85200 >= 50000 -> fifteen percent"
    assert summary["total_settled_credit_cents"] == 97980
    assert summary["provisional_credit_cents"] == 85200, \
        "all logs VERIFIED and worked in whole hours: claimed equals credited"


# ---------------------------------------------------------------------------
# Pinned per-entry quarter rounding (PRD §2.8, §3.8)
# ---------------------------------------------------------------------------

def _setup_quarter_rounding(api):
    """One group volunteer works six minutes on each of two adjacent
    same-segment shifts (06:00-08:00 and 08:00-10:00); both logs VERIFIED."""
    ctx = setup_event_with_shift(
        publish=True,
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    s2 = add_shift(ev, ctx["role"]["id"], ctx["segment"]["id"],
                   start_at="2026-10-04T08:00:00Z", end_at="2026-10-04T10:00:00Z",
                   required_headcount=1)
    grp = add_group(ev)
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01",
                                      group_id=grp["id"])
    sg1 = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    sg2 = create_confirmed_signup(vol["id"], s2["id"])
    lock_and_start_race_day(ev)
    set_clock("2026-10-04T06:00:00Z")
    check_in_signup(sg1["id"])
    log1 = check_out_and_fetch_log(sg1["id"], "2026-10-04T06:06:00Z")
    set_clock("2026-10-04T08:00:00Z")
    check_in_signup(sg2["id"])
    log2 = check_out_and_fetch_log(sg2["id"], "2026-10-04T08:06:00Z")
    verify_log(log1["id"])
    verify_log(log2["id"])
    return ctx, grp, vol, log1, log2


def test_quarter_rounding_per_entry_values(api):
    """PRD §2.8: "Credited volunteer hours are exact quarter-hour multiples:
    the quarter-hour count is rounded half up to a whole number of quarters
    per individual hour-log entry before any summation takes place — group
    and volunteer totals are sums of per-entry rounded values, never the
    rounding of a sum."

    Design: Difficulty/combinatorial_formula/quarter_rounding_per_entry_order
    """
    ctx, grp, vol, log1, log2 = _setup_quarter_rounding(api)
    assert log1["raw_minutes"] == 6
    assert log1["credited_hours"] == pytest.approx(0.0, abs=0.001), \
        "six minutes is zero whole quarters"
    assert log1["claimed_hours"] == pytest.approx(0.1, abs=0.001)
    assert log2["credited_hours"] == pytest.approx(0.0, abs=0.001)


def test_quarter_rounding_forbids_sum_then_round(api):
    """PRD §3.8: "The rounding order is pinned: quarter-hour rounding applies
    per individual log entry before any summation, and group or volunteer
    totals are sums of per-entry `credited_hours`. The opposite order —
    summing raw minutes first and rounding the total — is forbidden: two
    separate six-minute logs credit zero quarters each and contribute zero
    point zero zero hours in total, never a quarter-hour between them."

    Design: Difficulty/combinatorial_formula/quarter_rounding_per_entry_order
    """
    ctx, grp, vol, log1, log2 = _setup_quarter_rounding(api)
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(0.0, abs=0.001)
    assert summary["settled_credit_cents"] == 0
    assert summary["sponsor_match_cents"] == 0
    assert summary["total_settled_credit_cents"] == 0
    assert summary["provisional_credit_cents"] == 100, \
        "claimed 0.10 + 0.10 = 0.20 effective hours at 500 cents"


# ---------------------------------------------------------------------------
# Sponsor match keyed on the base alone (PRD §3.8)
# ---------------------------------------------------------------------------

def _setup_match_base_keying(api):
    """Role weight 3.0; four volunteers each work 06:00-14:00 (8.00 credited
    -> 24.00 effective each); all four logs VERIFIED -> base exactly 48000."""
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=3.0, headcount=4,
        shift_start="2026-10-04T06:00:00Z", shift_end="2026-10-04T14:00:00Z",
        role_overrides={"role_code": "HEAVY", "title": "Heavy Marshal"},
        work_specs=[{"name": f"V {n}", "dob": f"2000-01-0{n}",
                     "out": "2026-10-04T14:00:00Z"} for n in range(1, 5)])
    for row in rows:
        verify_log(row[2]["id"])
    return ctx, grp, rows


def test_sponsor_match_base_amount(api):
    """PRD §3.8: "the first one hundred hours earn five hundred cents per
    hour"

    Design: Difficulty/combinatorial_formula/sponsor_match_base_keying_order
    """
    ctx, grp, rows = _setup_match_base_keying(api)
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(96.0, abs=0.001), \
        "4 x 24.00 effective hours"
    assert summary["settled_credit_cents"] == 48000, "96.00 hours all inside tier one"


def test_sponsor_match_keyed_on_base_not_total(api):
    """PRD §3.8: "Step two selects the match percentage from the base alone:
    twenty-five percent when the base reaches 250,000 cents, fifteen percent
    when it reaches 50,000 cents, and five percent otherwise; the tier is
    never re-evaluated against the final total."

    Design: Difficulty/combinatorial_formula/sponsor_match_base_keying_order
    """
    ctx, grp, rows = _setup_match_base_keying(api)
    summary = _credit_summary(grp["id"])
    assert summary["sponsor_match_cents"] == 2400, \
        "base 48000 < 50000 -> five percent, even though the total crosses 50000"
    assert summary["total_settled_credit_cents"] == 50400


# ---------------------------------------------------------------------------
# Tier boundary at exactly 100.00 effective hours (PRD §3.8)
# ---------------------------------------------------------------------------

def _setup_tier_boundary(api):
    """Roles HEAVY (weight 3.0; shift 06:00-14:00, headcount 5) and LIGHT
    (weight 2.0; same segment, adjacent 14:00-16:00, headcount 1). V1-V4 work
    the big shift; V5 works both. Logs for V1-V4 and V5's small-shift log are
    VERIFIED; V5's big-shift log is verified only on demand."""
    ctx = setup_event_with_shift(
        publish=True,
        role_overrides={"role_code": "HEAVY", "title": "Heavy Marshal",
                        "credit_weight": 3.0},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 5})
    ev = ctx["event"]["id"]
    role_light = add_role(ev, role_code="LIGHT", title="Light Marshal",
                          min_age_years=16, credit_weight=2.0)
    s_small = add_shift(ev, role_light["id"], ctx["segment"]["id"],
                        start_at="2026-10-04T14:00:00Z", end_at="2026-10-04T16:00:00Z",
                        required_headcount=1)
    grp = add_group(ev)
    vols, big_signups = [], []
    for n in range(1, 6):
        vol = register_eligible_volunteer(ev, full_name=f"V {n}",
                                          date_of_birth=f"2000-01-0{n}",
                                          group_id=grp["id"])
        vols.append(vol)
        big_signups.append(create_confirmed_signup(vol["id"], ctx["shift"]["id"]))
    sg_small = create_confirmed_signup(vols[4]["id"], s_small["id"])
    lock_and_start_race_day(ev)
    set_clock("2026-10-04T06:00:00Z")
    for sg in big_signups:
        check_in_signup(sg["id"])
    big_logs = [check_out_and_fetch_log(sg["id"], "2026-10-04T14:00:00Z")
                for sg in big_signups]
    set_clock("2026-10-04T14:00:00Z")
    check_in_signup(sg_small["id"])
    log_small = check_out_and_fetch_log(sg_small["id"], "2026-10-04T16:00:00Z")
    for log in (big_logs[0], big_logs[1], big_logs[2], big_logs[3], log_small):
        verify_log(log["id"])
    return ctx, grp, big_logs, log_small


def test_credit_tier_boundary_exactly_100_hours(api):
    """PRD §3.8: "Pricing is marginal across three slices, each slice rounded
    half up to a whole cent before the slices are summed: the first one
    hundred hours earn five hundred cents per hour; hours beyond the first
    hundred, up to a cumulative five hundred, earn eight hundred cents per
    hour; and all hours beyond five hundred earn twelve hundred cents per
    hour."

    Design: Difficulty/boundary_precision_check/credit_tier_boundary_at_exact_100_hours
    """
    ctx, grp, big_logs, log_small = _setup_tier_boundary(api)
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(100.0, abs=0.001), \
        "4 x 24.00 + 4.00: the boundary lands exactly on one hundred"
    assert summary["settled_credit_cents"] == 50000, \
        "the entire 100th hour still bills at 500; nothing enters the 800 tier"
    assert summary["sponsor_match_cents"] == 7500, "base 50000 reaches the 15% match"
    assert summary["total_settled_credit_cents"] == 57500


def test_credit_tier_boundary_one_log_over(api):
    """PRD §3.8: "hours beyond the first hundred, up to a cumulative five
    hundred, earn eight hundred cents per hour"

    Design: Difficulty/boundary_precision_check/credit_tier_boundary_at_exact_100_hours
    """
    ctx, grp, big_logs, log_small = _setup_tier_boundary(api)
    verify_log(big_logs[4]["id"])
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(124.0, abs=0.001)
    assert summary["settled_credit_cents"] == 69200, \
        "50000 + 24 x 800: only the overflow bills at tier two"
    assert summary["sponsor_match_cents"] == 10380
    assert summary["total_settled_credit_cents"] == 79580


# ---------------------------------------------------------------------------
# Pool membership and weighting (PRD §3.8)
# ---------------------------------------------------------------------------

def test_credit_excludes_rejected_logs(api):
    """PRD §3.8: "Pool membership is decided by log status alone: logs of
    volunteers whose group has since been `SUSPENDED` continue to accrue,
    because suspension blocks new affiliations rather than accrual on existing
    ones, while `REJECTED` logs fall outside both pools."
    PRD §3.8: "Rejection is coordinator-only, allowed only from
    `PENDING_VERIFICATION` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), lands in
    terminal `REJECTED`, and excludes the log from both credit variants
    forever."

    Design: Corner/calculations/credit_excludes_rejected_logs
    """
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=1.0, headcount=2,
        work_specs=[{"name": "V One", "dob": "2000-01-01", "out": "2026-10-04T10:00:00Z"},
                    {"name": "V Two", "dob": "2000-01-02", "out": "2026-10-04T12:00:00Z"}])
    verify_log(rows[0][2]["id"])
    validate_success(api_client.reject_hour_log(rows[1][2]["id"], COORDINATOR))
    summary = _credit_summary(grp["id"])
    assert summary["settled_credit_cents"] == 2000, "only the VERIFIED 4-hour log"
    assert summary["provisional_credit_cents"] == 2000, \
        "the REJECTED log is excluded from the provisional pool too"


def test_credit_weight_applied_to_effective_hours(api):
    """PRD §3.8: "Per log, the system derives two weighted figures: effective
    hours, the log's `credited_hours` multiplied by the `credit_weight` of the
    role catalog entry behind the log's signup's shift and rounded half up to
    two decimal places"

    Design: Corner/calculations/credit_weight_applied_to_effective_hours
    """
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=2.0, headcount=1,
        shift_start="2026-10-04T08:00:00Z", shift_end="2026-10-04T12:00:00Z",
        role_overrides={"role_code": "LEAD", "title": "Lead Marshal"},
        work_specs=[{"name": "V One", "dob": "2000-01-01",
                     "out": "2026-10-04T09:15:00Z", "break_minutes": 1}])
    log = rows[0][2]
    assert log["raw_minutes"] == 74, "75 elapsed minutes minus 1 break minute"
    assert log["credited_hours"] == pytest.approx(1.25, abs=0.001), \
        "round_half_up(74/15) = 5 quarter-hours"
    verify_log(log["id"])
    summary = _credit_summary(grp["id"])
    assert summary["settled_effective_hours"] == pytest.approx(2.5, abs=0.001)
    assert summary["settled_credit_cents"] == 1250, "2.50 hours at 500 cents"


# ---------------------------------------------------------------------------
# Dispute / re-verify conservation (PRD §3.8)
# ---------------------------------------------------------------------------

def _setup_dispute_reverify(api):
    """One group volunteer with a 4-hour VERIFIED log; settled credit 2000."""
    ctx, grp, rows = _setup_credit_run(
        api, credit_weight=1.0, headcount=1,
        shift_start="2026-10-04T06:00:00Z", shift_end="2026-10-04T10:00:00Z",
        work_specs=[{"name": "V One", "dob": "2000-01-01", "out": "2026-10-04T10:00:00Z"}])
    verify_log(rows[0][2]["id"])
    return ctx, grp, rows[0]


def test_dispute_removes_log_from_settled_pool(api):
    """PRD §3.8: "A disputed log leaves the settled credit pool until it is
    re-verified, and a dispute followed by re-verification leaves the settled
    credit exactly as it stood."

    Design: Difficulty/compensating_invariant/credit_conservation_dispute_reverify_pair
    """
    ctx, grp, row = _setup_dispute_reverify(api)
    before = _credit_summary(grp["id"])
    assert before["settled_credit_cents"] == 2000, "4.00 verified hours at 500 cents"
    validate_success(api_client.dispute_hour_log(row[2]["id"], COORDINATOR))
    during = _credit_summary(grp["id"])
    assert during["settled_credit_cents"] == 0, "DISPUTED logs leave the settled pool"
    assert during["settled_effective_hours"] == pytest.approx(0.0, abs=0.001)


def test_reverify_restores_settled_credit_exactly(api):
    """PRD §3.8: "A disputed log leaves the settled credit pool until it is
    re-verified, and a dispute followed by re-verification leaves the settled
    credit exactly as it stood."
    PRD §3.8: "Verification is allowed from `PENDING_VERIFICATION` or
    `DISPUTED` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), moves the log to
    `VERIFIED`, and records who acted in `verified_by_role` as `CAPTAIN` or
    `COORDINATOR`."

    Design: Difficulty/compensating_invariant/credit_conservation_dispute_reverify_pair
    """
    ctx, grp, row = _setup_dispute_reverify(api)
    before = _credit_summary(grp["id"])
    validate_success(api_client.dispute_hour_log(row[2]["id"], COORDINATOR))
    reverified = validate_success(api_client.verify_hour_log(row[2]["id"], COORDINATOR))
    assert reverified["status"] == "VERIFIED"
    assert reverified["verified_by_role"] == "COORDINATOR"
    after = _credit_summary(grp["id"])
    assert after["settled_credit_cents"] == before["settled_credit_cents"] == 2000
    assert after["total_settled_credit_cents"] == 2100


# ---------------------------------------------------------------------------
# Credit summary ownership (PRD §3.8)
# ---------------------------------------------------------------------------

def test_groupleader_foreign_credit_summary_forbidden(api):
    """PRD §3.8: "The fundraising credit summary of a group is a computed
    read, open to the `EventDirector` and to the `GroupLeader` of that group —
    whose `X-User-ID` must equal the group's `id`, otherwise
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/groupleader_foreign_credit_summary_forbidden
    """
    event = create_event(clock=None)
    g_a = add_group(event["id"], name="Club A", charity_code="CHARITY-A")
    g_b = add_group(event["id"], name="Club B", charity_code="CHARITY-B")
    foreign = api_client.get_credit_summary(g_b["id"], make_group_leader_headers(g_a["id"]))
    validate_error(foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    own = _credit_summary(g_a["id"], headers=make_group_leader_headers(g_a["id"]))
    assert own["settled_credit_cents"] == 0


# ---------------------------------------------------------------------------
# Recognition points (PRD §3.9)
# ---------------------------------------------------------------------------

def _setup_recognition_divergence(api):
    """Returning captain of the 06:00-14:00 shift with one 4-hour log left
    PENDING_VERIFICATION. Returns (ctx, hour_log)."""
    ctx = setup_debrief_open_with_captain(
        volunteer_overrides={"full_name": "V One", "date_of_birth": "2000-01-01",
                             "is_returning": True},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z"},
        checkout_at="2026-10-04T10:00:00Z")
    return ctx, ctx["hour_log"]


def _recognition(volunteer_id):
    data = validate_success(api_client.get_recognition_summary(volunteer_id, COORDINATOR))
    assert_recognition_summary(data)
    return data


def test_recognition_projected_counts_unverified_claimed(api):
    """PRD §3.9: "The projected total, `projected_points`, sums hour points
    (claimed hours for unverified logs), bonuses, and penalties across all
    non-cancelled signups, plus the returning bonus; the official total,
    `official_points`, counts `VERIFIED` credited hours only under the same
    bonuses and penalties."
    PRD §3.9: "A captain signup — `is_captain` true on a signup that is not
    `CANCELLED` — adds twenty-five points; a `NO_SHOW` signup subtracts
    fifteen; and a returning volunteer with `is_returning` true adds fifty
    points once per event."

    Design: Difficulty/dual_variant_calc/recognition_projected_vs_official_diverge
    """
    ctx, log = _setup_recognition_divergence(api)
    summary = _recognition(ctx["captain"]["id"])
    assert summary["projected_points"] == 115, "4.00 claimed h x 10 + captain 25 + returning 50"
    assert summary["official_points"] == 75, "0 verified hours + 25 + 50"
    assert summary["recognition_tier"] == "BRONZE", "75 is fifty or more but below 150"
    assert summary["captain_shift_count"] == 1
    assert summary["no_show_count"] == 0


def test_recognition_official_reconciles_on_verify(api):
    """PRD §3.9: "the official total, `official_points`, counts `VERIFIED`
    credited hours only under the same bonuses and penalties."
    PRD §3.9: "The `recognition_tier` keys on the official total: `PLATINUM`
    at six hundred points or more, `GOLD` at three hundred or more, `SILVER`
    at one hundred fifty or more, `BRONZE` at fifty or more, and `NONE` below
    that."

    Design: Difficulty/dual_variant_calc/recognition_projected_vs_official_diverge
    """
    ctx, log = _setup_recognition_divergence(api)
    before = _recognition(ctx["captain"]["id"])
    verify_log(log["id"])
    after = _recognition(ctx["captain"]["id"])
    assert after["official_points"] == 115, "verification reconciles the official variant up"
    assert after["projected_points"] == before["projected_points"] == 115, \
        "the projected variant never moves on verification"


def test_recognition_tier_gte_boundaries(api):
    """PRD §3.9: "The `recognition_tier` keys on the official total:
    `PLATINUM` at six hundred points or more, `GOLD` at three hundred or more,
    `SILVER` at one hundred fifty or more, `BRONZE` at fifty or more, and
    `NONE` below that."

    Design: Corner/calculations/recognition_tier_gte_boundaries
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01", "is_returning": True}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T16:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    vol = ctx["volunteers"][0]
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])
    log = check_out_and_fetch_log(sg["id"], "2026-10-04T16:00:00Z")
    assert log["credited_hours"] == pytest.approx(10.0, abs=0.001)
    pre = _recognition(vol["id"])
    assert pre["official_points"] == 50, "returning bonus alone"
    assert pre["recognition_tier"] == "BRONZE", "fifty or more is BRONZE (inclusive)"
    verify_log(log["id"])
    post = _recognition(vol["id"])
    assert post["official_points"] == 150, "10.00 verified hours x 10 + 50"
    assert post["recognition_tier"] == "SILVER", "one hundred fifty or more is SILVER (inclusive)"


def test_recognition_no_show_penalty_goes_negative(api):
    """PRD §3.9: "a `NO_SHOW` signup subtracts fifteen"
    PRD §3.9: "Points may go negative — there is no floor."

    Design: Corner/calculations/recognition_no_show_penalty_goes_negative
    """
    ctx = setup_event_with_shift(
        publish=True,
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 2})
    ev = ctx["event"]["id"]
    s2 = add_shift(ev, ctx["role"]["id"], ctx["segment"]["id"],
                   start_at="2026-10-04T08:00:00Z", end_at="2026-10-04T09:00:00Z",
                   required_headcount=2)
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    sg2 = create_confirmed_signup(vol["id"], s2["id"])
    lock_and_start_race_day(ev)
    set_clock("2026-10-04T06:31:00Z")
    validate_success(api_client.mark_no_show(sg1["id"], COORDINATOR))
    set_clock("2026-10-04T08:00:00Z")
    check_in_signup(sg2["id"])
    log2 = check_out_and_fetch_log(sg2["id"], "2026-10-04T09:00:00Z")
    verify_log(log2["id"])
    summary = _recognition(vol["id"])
    assert summary["official_points"] == -5, "+10 for the verified hour, -15 for the no-show"
    assert summary["recognition_tier"] == "NONE"
    assert summary["no_show_count"] == 1


# ---------------------------------------------------------------------------
# Hour log terminal lockdown (PRD §3.8)
# ---------------------------------------------------------------------------

def test_hourlog_terminal_reject_then_verify_rejected(api):
    """PRD §3.8: "Rejection is coordinator-only, allowed only from
    `PENDING_VERIFICATION` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), lands in
    terminal `REJECTED`, and excludes the log from both credit variants
    forever."
    PRD §3.8: "Verification is allowed from `PENDING_VERIFICATION` or
    `DISPUTED` (otherwise `ERR_HOUR_LOG_INVALID_STATE`)"

    Design: Corner/errors/hourlog_terminal_reject_then_verify_rejected
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T10:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])
    log = check_out_and_fetch_log(sg["id"], "2026-10-04T10:00:00Z")
    rejected = validate_success(api_client.reject_hour_log(log["id"], COORDINATOR))
    assert rejected["status"] == "REJECTED"
    verify_resp = api_client.verify_hour_log(log["id"], COORDINATOR)
    validate_error(verify_resp, ApiErrorId.ERR_HOUR_LOG_INVALID_STATE)
