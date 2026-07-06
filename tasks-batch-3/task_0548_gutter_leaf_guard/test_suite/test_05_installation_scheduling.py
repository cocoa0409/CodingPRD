"""Job scheduling: the weather-before-overlap priority ordering, crew whole-day
overlap, the crew-day reservation invariant, deposit/install-day computation,
the weather-hold recovery loop, and the leaf-guard certification gate.
"""
from test_helpers import (
    ApiErrorId,
    create_crew,
    schedule_job,
    set_forecast,
    setup_accepted_quote,
    setup_scheduled_job,
    setup_two_jobs_same_crew,
    transition_job,
    validate_error,
    validate_success,
)


# ------------------------------------------- weather beats crew-overlap priority
def test_schedule_severe_weather_reported_before_crew_overlap(api, admin_headers):
    """PRD §2.6: "In particular, for the scheduling of a job the weather check
    precedes the certification check, which precedes the crew-overlap check."
    PRD §3.7: "First, the forecast for the requested `install_date` must not be
    `SEVERE`, else `ERR_WEATHER_UNSAFE`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_weather_beats_crew_double_booked
    """
    scenario = setup_two_jobs_same_crew(
        job1_feet=210, job2_feet=140, job1_install_date="2026-06-10"
    )
    # 2026-06-11 is inside job1's span AND set to SEVERE; the weather check wins.
    set_forecast("2026-06-11", "SEVERE")
    resp = api.schedule_job(
        scenario["job2"]["id"],
        {"crew_id": scenario["crew"]["id"], "install_date": "2026-06-11"},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WEATHER_UNSAFE)


def test_schedule_weather_conflict_leaves_job_pending(api, admin_headers):
    """PRD §3.7: "On success the crew and date are assigned and the crew's reserved
    `booked_days` grows by this job's `install_days`."
    PRD §3.7: "At birth a job carries the `quote_id` it fulfills and the `lead_id`
    homeowner, starts in `PENDING`, and has a null `crew_id` and null
    `install_date` until it is scheduled."

    Design: Difficulty/priority_pair_validation_conflict/schedule_weather_beats_crew_double_booked
    """
    scenario = setup_two_jobs_same_crew(
        job1_feet=210, job2_feet=140, job1_install_date="2026-06-10"
    )
    set_forecast("2026-06-11", "SEVERE")
    api.schedule_job(
        scenario["job2"]["id"],
        {"crew_id": scenario["crew"]["id"], "install_date": "2026-06-11"},
        admin_headers,
    )
    job2 = validate_success(api.get_job(scenario["job2"]["id"], admin_headers))
    assert job2["status"] == "PENDING"
    assert job2.get("crew_id") is None


# --------------------------------------------------- crew whole-day overlap
def test_crew_double_booked_on_overlapping_whole_day(api, admin_headers):
    """PRD §3.7: "Third, the job's whole-day span — the inclusive range of days
    from the `install_date` through the `install_date` plus `install_days` minus
    one — must not overlap the day span of any other `SCHEDULED` or `IN_PROGRESS`
    job already assigned to that same crew, else `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_install_overlap_whole_day
    """
    scenario = setup_two_jobs_same_crew(
        job1_feet=210, job2_feet=140, job1_install_date="2026-06-10"
    )
    # job1 (install_days 2) occupies 06-10..06-11; 06-11 collides.
    resp = api.schedule_job(
        scenario["job2"]["id"],
        {"crew_id": scenario["crew"]["id"], "install_date": "2026-06-11"},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)
    job2 = validate_success(api.get_job(scenario["job2"]["id"], admin_headers))
    assert job2["status"] == "PENDING"


def test_crew_schedule_succeeds_on_free_day(api):
    """PRD §3.7: "Third, the job's whole-day span — the inclusive range of days
    from the `install_date` through the `install_date` plus `install_days` minus
    one — must not overlap the day span of any other `SCHEDULED` or `IN_PROGRESS`
    job already assigned to that same crew, else `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_install_overlap_whole_day
    """
    scenario = setup_two_jobs_same_crew(
        job1_feet=210, job2_feet=140, job1_install_date="2026-06-10"
    )
    # job1 occupies 06-10..06-11; job2 (install_days 1) on 06-12 does not overlap.
    job2 = schedule_job(scenario["job2"]["id"], scenario["crew"]["id"], "2026-06-12")
    assert job2["status"] == "SCHEDULED"
    assert job2["install_date"] == "2026-06-12"


# ----------------------------------------------- crew-day reservation invariant
def test_crew_booked_days_reserved_on_schedule(api, admin_headers):
    """PRD §3.7: "On success the crew and date are assigned and the crew's reserved
    `booked_days` grows by this job's `install_days`."

    Design: Difficulty/compensating_invariant/crew_days_conserved_on_cancel
    """
    scenario = setup_scheduled_job(measured_linear_feet=210, install_date="2026-06-10")
    crew = validate_success(api.get_crew(scenario["crew"]["id"], admin_headers))
    assert crew["booked_days"] == 2  # install_days = ceil(210 / 150)


def test_crew_booked_days_released_on_cancel(api, admin_headers):
    """PRD §3.7: "A job may be `CANCELED` from `SCHEDULED`, `WEATHER_HOLD`, or
    `IN_PROGRESS`. Cancelling from `SCHEDULED` or `IN_PROGRESS` releases the crew
    reservation; cancelling from `WEATHER_HOLD` makes no crew-day change, because
    the hold already released it."

    Design: Difficulty/compensating_invariant/crew_days_conserved_on_cancel
    """
    scenario = setup_scheduled_job(measured_linear_feet=210, install_date="2026-06-10")
    before = validate_success(api.get_crew(scenario["crew"]["id"], admin_headers))
    assert before["booked_days"] == 2
    transition_job(scenario["job"]["id"], "CANCELED")
    after = validate_success(api.get_crew(scenario["crew"]["id"], admin_headers))
    assert after["booked_days"] == 0


# ------------------------------------------------------ deposit / install days
def test_job_deposit_and_install_days_computed_on_creation(api):
    """PRD §3.7: "The `install_days` — the crew-day span the job will occupy — is
    the accepted quote's `linear_feet` divided by 150 feet per crew day, rounded
    up to the next whole day. The `deposit_cents` collected at job creation is the
    quote's `total_cents` multiplied by 10 percent, rounded half up to whole
    cents."

    Design: Corner/calculations/deposit_amount_correct_on_job_creation
    """
    scenario = setup_accepted_quote(estimated_linear_feet=200, measured_linear_feet=200)
    job = scenario["job"]
    assert job["deposit_cents"] == 57000  # round_half_up(570000 * 0.10)
    assert job["install_days"] == 2       # ceil(200 / 150)


# ------------------------------------------------- weather-hold recovery loop
def test_weather_hold_releases_and_reschedule_re_reserves(api, admin_headers):
    """PRD §3.7: "From `SCHEDULED`, the job may be placed on `WEATHER_HOLD`, which
    releases the crew reservation — the crew's `booked_days` shrinks by this job's
    `install_days`. Rescheduling a held job runs the same three scheduling checks
    and re-reserves the crew days, closing the `SCHEDULED` to `WEATHER_HOLD` to
    `SCHEDULED` recovery loop."

    Design: Corner/state_machines/weather_hold_cycle_recovers_to_scheduled
    """
    scenario = setup_scheduled_job(measured_linear_feet=210, install_date="2026-06-10")
    transition_job(scenario["job"]["id"], "WEATHER_HOLD")
    on_hold = validate_success(api.get_crew(scenario["crew"]["id"], admin_headers))
    assert on_hold["booked_days"] == 0
    resumed = schedule_job(scenario["job"]["id"], scenario["crew"]["id"], "2026-06-20")
    assert resumed["status"] == "SCHEDULED"
    after = validate_success(api.get_crew(scenario["crew"]["id"], admin_headers))
    assert after["booked_days"] == 2


# ---------------------------------------------------- certification gate
def test_leaf_guard_job_requires_certified_crew(api, admin_headers):
    """PRD §3.7: "Second, if the job's product is of category `LEAF_GUARD`, the
    assigned crew's `is_certified_leaf_guard` must be true, else
    `ERR_CREW_NOT_CERTIFIED`."

    Design: Corner/validations/crew_not_certified_returns_error
    """
    scenario = setup_accepted_quote(estimated_linear_feet=210, measured_linear_feet=210)
    uncertified = create_crew(name="Crew U", is_certified_leaf_guard=False)
    resp = api.schedule_job(
        scenario["job"]["id"],
        {"crew_id": uncertified["id"], "install_date": "2026-06-10"},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED)
