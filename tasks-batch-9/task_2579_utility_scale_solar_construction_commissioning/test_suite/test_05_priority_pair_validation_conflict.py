"""Requests that break two rules at once, and the rung that answers first.

An under-prevailing payroll line posted into a certified week violates both the
week lock at rung 8 and the wage floor at rung 28. An earthwork window inside a
rain blackout that also collides with logged crew occupancy violates rung 12 and
rung 14. In each pair the higher rung answers, and the loser is proved reachable
by a second request that trips only it.
"""

from test_helpers import validate_error
from test_helpers.api_errors import (
    ERR_BELOW_PREVAILING_WAGE,
    ERR_EARTHWORK_WINDOW_CONFLICT,
    ERR_PAYROLL_WEEK_LOCKED,
    ERR_RAIN_EVENT_BLACKOUT,
)
from test_helpers.assertions import (
    assert_grading_area_state,
    assert_instant_equals,
    assert_ratio,
    assert_week_totals,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    certify_week,
    create_grading_area,
    create_payroll_week,
    create_project,
    post_labor_entry,
    read_grading_area,
    read_payroll_week,
    read_project,
    record_rain_event,
    set_clock,
)
from test_helpers.test_users import CIVIL_SUPERINTENDENT, LABOR_COMPLIANCE_OFFICER

# 4000 paid plus 500 fringe is 500 cents an hour short of the 5000 determination.
DEFICIENT_LINE = {
    "worker_ref": "W-302",
    "classification": "ELECTRICIAN",
    "is_apprentice": False,
    "hours": 6.00,
    "paid_rate_cents": 4000,
    "fringe_rate_cents": 500,
    "prevailing_rate_cents": 5000,
}


def _strict_project_with_locked_week(api):
    """A STRICT project whose first week is certified and whose second is open."""
    project = create_project(api, name="Basin Mesa", prevailing_wage_election="STRICT")
    locked = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    post_labor_entry(
        api,
        locked["id"],
        worker_ref="W-301",
        classification="ELECTRICIAN",
        is_apprentice=False,
        hours=8.00,
        paid_rate_cents=4500,
        fringe_rate_cents=500,
        prevailing_rate_cents=5000,
        work_date="2026-08-03",
    )
    certify_week(api, locked["id"], note="week closed")
    open_week = create_payroll_week(api, project["id"], week_start_date="2026-08-10")
    return project, locked, open_week


def _post(api, week_id, work_date):
    """Attempt the deficient line without asserting success."""
    payload = f.labor_entry_payload(work_date=work_date, **DEFICIENT_LINE)
    return api.create_labor_entry(week_id, payload, LABOR_COMPLIANCE_OFFICER)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/payroll_week_lock_outranks_below_prevailing_wage
# ---------------------------------------------------------------------------
def test_the_week_lock_answers_before_the_prevailing_wage_floor(api):
    """A deficient line into a certified week is refused for the lock, not the wage.

    PRD 2.7: "The server therefore evaluates checks in a fixed global precedence
    order and returns the **first** failure it encounters, never a later one that
    happens to be easier to detect."

    Design: Difficulty/priority_pair_validation_conflict/payroll_week_lock_outranks_below_prevailing_wage
    """
    _project, locked, _open_week = _strict_project_with_locked_week(api)

    response = _post(api, locked["id"], "2026-08-04")

    validate_error(response, ERR_PAYROLL_WEEK_LOCKED, expected_status=409)


def test_the_prevailing_wage_floor_answers_when_the_week_is_open(api):
    """The same payload into the open week reaches the lower rung and is refused there.

    PRD 3.8: "When `prevailing_wage_election` is `STRICT`, an under-prevailing
    line never enters the ledger at all: the post is refused with
    `ERR_BELOW_PREVAILING_WAGE` before persistence, on the grounds that the sum
    of `paid_rate_cents` and `fringe_rate_cents` must be at least
    `prevailing_rate_cents`."

    Design: Difficulty/priority_pair_validation_conflict/payroll_week_lock_outranks_below_prevailing_wage
    """
    _project, locked, open_week = _strict_project_with_locked_week(api)
    validate_error(_post(api, locked["id"], "2026-08-04"), ERR_PAYROLL_WEEK_LOCKED, expected_status=409)

    response = _post(api, open_week["id"], "2026-08-10")

    validate_error(response, ERR_BELOW_PREVAILING_WAGE, expected_status=422)


def test_neither_rejected_post_leaves_a_trace_in_either_ledger(api):
    """A certified week is terminal, and a STRICT project accrues no restitution.

    PRD 3.8: "A certified week is terminal and admits no further posts and no
    further voids."

    Design: Difficulty/priority_pair_validation_conflict/payroll_week_lock_outranks_below_prevailing_wage
    """
    project, locked, open_week = _strict_project_with_locked_week(api)
    _post(api, locked["id"], "2026-08-04")
    _post(api, open_week["id"], "2026-08-10")

    closed = read_payroll_week(api, locked["id"])
    assert closed["entry_count"] == 1
    assert_week_totals(closed, total_hours=8.00, journeyworker_hours=8.00, apprentice_hours=0.00)

    fresh = read_payroll_week(api, open_week["id"])
    assert fresh["entry_count"] == 0
    assert_week_totals(fresh, total_hours=0.00, journeyworker_hours=0.00, apprentice_hours=0.00)

    assert read_project(api, project["id"])["wage_restitution_owed_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/rain_blackout_outranks_earthwork_window_conflict
# ---------------------------------------------------------------------------
LOGGED_WINDOWS = (
    ("CLEARING", "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"),
    ("GRADING", "2026-08-06T08:00:00Z", "2026-08-06T16:00:00Z"),
    ("DRAINAGE", "2026-08-08T08:00:00Z", "2026-08-08T16:00:00Z"),
)


def _rained_out_area(api):
    """Three logged windows and a half-inch storm that blacks out two days."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Pinto Flat")
    area = create_grading_area(
        api,
        project["id"],
        area_code="A1",
        permit_number="CGP-2026-118",
        disturbed_acreage_limit=40.00,
        bmp_inspection_interval_days=14,
    )
    for activity, start_at, end_at in LOGGED_WINDOWS:
        _log(api, area["id"], activity, start_at, end_at, 5.00)
    record_rain_event(api, area["id"], "2026-08-05T18:00:00Z", 0.50)
    return project, area


def _log(api, area_id, activity, start_at, end_at, acreage):
    """Attempt an earthwork log without asserting the outcome."""
    return api.create_earthwork_log(
        area_id,
        f.earthwork_log_payload(activity, start_at, end_at, acreage),
        CIVIL_SUPERINTENDENT,
    )


def test_the_rain_blackout_answers_before_the_window_collision(api):
    """A window inside the blackout is refused for the rain, though it also collides.

    PRD 3.2: "Next comes the post-rain blackout: when `rain_blackout_until` is
    set and the proposed `work_start_at` falls strictly before it, work is
    refused with `ERR_RAIN_EVENT_BLACKOUT`; a null `rain_blackout_until` imposes
    no restriction, and a `work_start_at` exactly at the blackout boundary is
    permitted."

    Design: Difficulty/priority_pair_validation_conflict/rain_blackout_outranks_earthwork_window_conflict
    """
    _project, area = _rained_out_area(api)

    # 2026-08-06T12:00 is inside the blackout and also overlaps that day's log.
    response = _log(api, area["id"], "GRADING", "2026-08-06T12:00:00Z", "2026-08-06T20:00:00Z", 3.00)

    validate_error(response, ERR_RAIN_EVENT_BLACKOUT, expected_status=422)


def test_the_window_collision_answers_once_the_blackout_has_expired(api):
    """A window starting after the dry-out still collides with logged occupancy.

    PRD 3.2: "if the candidate's `work_start_at` is at or before the
    `work_end_at` of any record already in `earthwork_windows`, and the
    candidate's `work_end_at` is at or after that record's `work_start_at`, the
    log is refused with `ERR_EARTHWORK_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/rain_blackout_outranks_earthwork_window_conflict
    """
    _project, area = _rained_out_area(api)

    # The blackout ends 2026-08-07T18:00, so this window clears rung 12 and
    # falls to rung 14 against the 08:00-16:00 log of the same day.
    response = _log(api, area["id"], "DRAINAGE", "2026-08-08T12:00:00Z", "2026-08-08T20:00:00Z", 3.00)

    validate_error(response, ERR_EARTHWORK_WINDOW_CONFLICT, expected_status=409)


def test_a_quarter_inch_storm_sets_a_forty_eight_hour_blackout(api):
    """Half an inch of rain at 18:00 on the fifth blacks work out until the seventh.

    PRD 3.2: "A `RAIN_EVENT` additionally carries `rainfall_inches`; if that
    figure is at least a quarter of an inch — 0.25 inches — the area's
    `rain_blackout_until` is set to `occurred_at` advanced by 48 hours, which is
    to say two full days of enforced dry-out."

    Design: Difficulty/priority_pair_validation_conflict/rain_blackout_outranks_earthwork_window_conflict
    """
    _project, area = _rained_out_area(api)

    stored = read_grading_area(api, area["id"])

    assert_instant_equals(
        stored["rain_blackout_until"], "2026-08-07T18:00:00Z", "rain_blackout_until"
    )


def test_neither_rejected_log_appends_to_the_append_only_window_list(api):
    """The ledger still shows three windows and 15.00 acres, and the status stands.

    PRD 3.2: "Every record ever appended participates in this check; the list is
    append-only and is never pruned, so accepted history keeps constraining new
    work indefinitely."

    Design: Difficulty/priority_pair_validation_conflict/rain_blackout_outranks_earthwork_window_conflict
    """
    _project, area = _rained_out_area(api)
    _log(api, area["id"], "GRADING", "2026-08-06T12:00:00Z", "2026-08-06T20:00:00Z", 3.00)
    _log(api, area["id"], "DRAINAGE", "2026-08-08T12:00:00Z", "2026-08-08T20:00:00Z", 3.00)

    stored = read_grading_area(api, area["id"])

    assert len(stored["earthwork_windows"]) == 3
    assert_ratio(stored["disturbed_acreage_current"], 15.00, "disturbed_acreage_current")
    assert_grading_area_state(stored, status="GRADED", permit_status="ACTIVE")
