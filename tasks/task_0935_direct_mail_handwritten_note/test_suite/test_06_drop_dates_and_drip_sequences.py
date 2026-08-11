"""The drop-date derivation, the blackout walk and drip-step spacing."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    SINGLE_RECORD_ROSTER,
    add_drip_step,
    add_drip_step_ok,
    assert_drip_schedule,
    assert_drip_step,
    assert_same_instant,
    build_addressed_scenario,
    build_drip_scenario,
    create_blackout_dates,
    drip_schedule_version,
    read_drip_schedule,
    read_drip_step,
    read_mail_job,
    validate_error,
    validate_success,
)


def _proofed_job_without_an_anchor(permit_number):
    return build_addressed_scenario(
        permit_number=permit_number, roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode=None, lock=False, stage="proofed",
        target_in_home_date=None, topup_cents=None,
    )


def test_an_anchor_mail_date_schedule_carries_the_anchor_through_and_derives_in_home(api):
    """PRD §3.6: "Under `ANCHOR_IN_HOME`, the supplied date is read as the desired
    in-home date and the raw drop date is that date less the class's transit days.
    Under `ANCHOR_MAIL_DATE`, the supplied date **is** the drop date and is carried
    through unchanged."
    PRD §3.6: "Worked through: an anchor of 2026-06-15 on a `MARKETING_MAIL` job
    under `ANCHOR_IN_HOME`, with no blackouts in the way, resolves to a drop date
    of 2026-06-05; the same anchor under `ANCHOR_MAIL_DATE` resolves to a drop date
    of 2026-06-15 and an in-home date of 2026-06-25 — the identical input, ten days
    apart."

    Design: Corner/calculations/anchor_mail_date_variant_derives_in_home_forwards
    """
    world = build_drip_scenario(
        permit_number="PMT-234", job_count=1, anchor_variant="ANCHOR_MAIL_DATE",
        schedule_name="Forward Drip",
    )

    step = add_drip_step_ok(world["schedule"]["id"], world["jobs"][0]["id"], 1, "2026-06-15")
    assert_drip_step(step)

    assert step["computed_mail_date"] == "2026-06-15"
    assert step["computed_in_home_date"] == "2026-06-25"
    assert step["shifted_days"] == 0

    schedule = read_drip_schedule(world["schedule"]["id"])
    assert_drip_schedule(schedule)
    assert schedule["anchor_variant"] == "ANCHOR_MAIL_DATE"
    assert schedule["step_count"] == 1


def test_an_anchor_before_the_current_date_is_refused_before_any_transit_maths(api):
    """PRD §3.6: "If the supplied anchor date is strictly earlier than the current
    date, the request is refused with `ERR_IN_HOME_DATE_PAST` (HTTP 422) at rung
    27. The comparison is strict, so an anchor equal to today passes this step."
    PRD §3.6: "An anchor date in the past reports `ERR_IN_HOME_DATE_PAST` even when
    the drop date it would have produced is also unreachable — that is precisely
    how the two temporal errors stay distinguishable, and rung 27 sitting above
    rung 29 is what makes it happen."

    Design: Corner/calculations/in_home_date_in_the_past_rejected_before_derivation
    """
    world = _proofed_job_without_an_anchor("PMT-235")

    response = api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-04-20"}, CAMPAIGN_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_IN_HOME_DATE_PAST.value)
    assert error["error_id"] != ApiErrorId.ERR_MAIL_DATE_UNREACHABLE.value

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "PROOFED"
    assert job["mail_date"] is None


def test_a_drop_date_inside_the_production_lead_time_is_unreachable(api):
    """PRD §3.6: "Finally, if the resolved drop date is earlier than the current
    date plus 3 days of production lead time, the request is refused with
    `ERR_MAIL_DATE_UNREACHABLE` (HTTP 422) at rung 29. This comparison is also
    strict, so a drop date landing exactly on the third day from today is
    accepted."
    PRD §3.6: "Each mail class carries a fixed transit expectation in calendar
    days: 3 days for `FIRST_CLASS`, 10 days for `MARKETING_MAIL`, and 12 days for
    `EDDM`."

    Design: Corner/calculations/derived_mail_date_inside_production_lead_returns_unreachable
    """
    world = _proofed_job_without_an_anchor("PMT-236")

    # The clock reads 2026-05-01, so 2026-05-05 is in the future and clears rung
    # 27; less MARKETING_MAIL's 10 transit days it derives to 2026-04-25, which
    # is earlier than 2026-05-01 plus 3 days.
    response = api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-05-05"}, CAMPAIGN_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_MAIL_DATE_UNREACHABLE.value)
    assert error["error_id"] != ApiErrorId.ERR_IN_HOME_DATE_PAST.value

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "PROOFED"
    assert job["mail_date"] is None


def test_a_single_blackout_day_walks_the_drop_date_back_by_one(api):
    """PRD §3.6: "The raw drop date is then walked backwards over the blackout
    calendar. While a blackout entry exists for the raw drop date, the date moves
    back by one calendar day and a shift counter rises by one."
    PRD §3.6: "On success it writes `mail_date` and `blackout_shifted_days` from
    the derivation, sets `scheduled_at` to the logical clock's current instant, and
    increments the job's `version`."

    Design: Corner/calculations/single_blackout_day_shifts_mail_date_backwards_by_one
    """
    world = _proofed_job_without_an_anchor("PMT-237")
    create_blackout_dates(["2026-06-05"])

    scheduled = validate_success(
        api.schedule_mail_job(
            world["job"]["id"], {"target_in_home_date": "2026-06-15"}, CAMPAIGN_MANAGER
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    # 2026-06-15 less 10 transit days is 2026-06-05, which is blacked out, so the
    # walk steps back one day to 2026-06-04 and records a single shift.
    assert scheduled["mail_date"] == "2026-06-04"
    assert scheduled["blackout_shifted_days"] == 1
    assert_same_instant(scheduled["scheduled_at"], "2026-05-01T00:00:00Z", "scheduled_at")


def test_six_consecutive_blackout_days_exhaust_the_inclusive_shift_cap(api):
    """PRD §3.6: "If the shift counter would exceed 5, the request is refused with
    `ERR_BLACKOUT_UNRESOLVABLE` (HTTP 422) at rung 28. The cap is inclusive: a walk
    that shifts exactly 5 days is accepted; one that would need 6 is not."

    Design: Corner/calculations/blackout_walk_beyond_five_days_returns_unresolvable
    """
    world = _proofed_job_without_an_anchor("PMT-238")
    create_blackout_dates(
        ["2026-06-05", "2026-06-04", "2026-06-03", "2026-06-02", "2026-06-01", "2026-05-31"]
    )

    response = api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-06-15"}, CAMPAIGN_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_BLACKOUT_UNRESOLVABLE.value)

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "PROOFED"
    assert job["mail_date"] is None
    assert job["blackout_shifted_days"] == 0


def test_a_drip_step_one_day_from_a_sibling_breaches_the_minimum_gap(api):
    """PRD §3.6: "Next, at rung 30, the new step's resolved drop date must differ
    from the resolved drop date of **every** existing non-cancelled sibling step on
    the same schedule by at least 2 calendar days; a closer spacing is
    `ERR_DRIP_GAP_TOO_SMALL` (HTTP 422)."
    PRD §3.6: "Under `ANCHOR_IN_HOME`, the supplied date is read as the desired
    in-home date and the raw drop date is that date less the class's transit days."

    Design: Difficulty/resource_temporal_overlap/drip_step_minimum_gap_buffer_between_mail_dates
    """
    world = build_drip_scenario(permit_number="PMT-161", job_count=3)
    schedule_id = world["schedule"]["id"]

    first = add_drip_step_ok(schedule_id, world["jobs"][0]["id"], 1, "2026-06-15")
    assert first["computed_mail_date"] == "2026-06-05"

    # 2026-06-16 less 10 transit days is 2026-06-06, only one day from 2026-06-05.
    response = add_drip_step(schedule_id, world["jobs"][1]["id"], 2, "2026-06-16")
    validate_error(response, ApiErrorId.ERR_DRIP_GAP_TOO_SMALL.value)

    assert read_drip_schedule(schedule_id)["step_count"] == 1


def test_a_drip_step_exactly_two_days_from_a_sibling_is_accepted(api):
    """PRD §3.6: "Next, at rung 30, the new step's resolved drop date must differ
    from the resolved drop date of **every** existing non-cancelled sibling step on
    the same schedule by at least 2 calendar days; a closer spacing is
    `ERR_DRIP_GAP_TOO_SMALL` (HTTP 422)."
    PRD §3.6: "The schedule moves `DRAFT → ACTIVE` on the first accepted step,
    `step_count` is recomputed as the number of its non-cancelled steps, and the
    schedule's `version` increments by one."

    Design: Difficulty/resource_temporal_overlap/drip_step_minimum_gap_buffer_between_mail_dates
    """
    world = build_drip_scenario(permit_number="PMT-161", job_count=3)
    schedule_id = world["schedule"]["id"]

    first = add_drip_step_ok(schedule_id, world["jobs"][0]["id"], 1, "2026-06-15")
    assert first["computed_mail_date"] == "2026-06-05"
    assert first["computed_in_home_date"] == "2026-06-15"
    assert first["status"] == "PENDING", "its job is still DRAFT"

    add_drip_step(schedule_id, world["jobs"][1]["id"], 2, "2026-06-16")

    # 2026-06-17 less 10 transit days is 2026-06-07, exactly two days clear.
    third = add_drip_step_ok(schedule_id, world["jobs"][2]["id"], 3, "2026-06-17")
    assert third["computed_mail_date"] == "2026-06-07"

    schedule = read_drip_schedule(schedule_id)
    assert schedule["step_count"] == 2
    assert schedule["status"] == "ACTIVE"


def test_the_ninth_drip_step_breaches_the_step_limit(api):
    """PRD §3.6: "Finally, at rung 31, the schedule must be holding fewer than 8
    non-cancelled steps before this one is added; an attempt to add a ninth is
    `ERR_DRIP_STEP_LIMIT` (HTTP 409)."

    Design: Corner/validations/ninth_drip_step_returns_step_limit
    """
    world = build_drip_scenario(permit_number="PMT-244", job_count=1)
    schedule_id = world["schedule"]["id"]
    job_id = world["jobs"][0]["id"]

    anchors = ["2026-06-15", "2026-06-17", "2026-06-19", "2026-06-21",
               "2026-06-23", "2026-06-25", "2026-06-27", "2026-06-29"]
    steps = [
        add_drip_step_ok(schedule_id, job_id, index + 1, anchor)
        for index, anchor in enumerate(anchors)
    ]
    # The eighth anchor of 2026-06-29 less 10 transit days is 2026-06-19.
    assert steps[7]["computed_mail_date"] == "2026-06-19"
    assert read_drip_schedule(schedule_id)["step_count"] == 8

    # 2026-07-01 derives to 2026-06-21, two clear days from 2026-06-19, so the
    # gap rung passes and only the step limit can fire.
    response = add_drip_step(schedule_id, job_id, 9, "2026-07-01")
    error = validate_error(response, ApiErrorId.ERR_DRIP_STEP_LIMIT.value)
    assert error["error_id"] != ApiErrorId.ERR_DRIP_GAP_TOO_SMALL.value

    assert read_drip_schedule(schedule_id)["step_count"] == 8


def test_reusing_a_sequence_number_is_reported_above_the_gap_rung(api):
    """PRD §3.6: "Sequence numbers must be at least 1 and are unique within a
    schedule, so reusing one is `ERR_DUPLICATE_KEY` at rung 26 — which sits above
    every temporal rung, so a colliding sequence number is reported even when the
    supplied date is also bad."

    Design: Corner/validations/duplicate_drip_sequence_number_returns_duplicate_key
    """
    world = build_drip_scenario(permit_number="PMT-245", job_count=1)
    schedule_id = world["schedule"]["id"]
    job_id = world["jobs"][0]["id"]

    add_drip_step_ok(schedule_id, job_id, 1, "2026-06-15")

    response = add_drip_step(schedule_id, job_id, 1, "2026-06-16")
    error = validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)
    assert error["error_id"] != ApiErrorId.ERR_DRIP_GAP_TOO_SMALL.value

    assert read_drip_schedule(schedule_id)["step_count"] == 1


def test_releasing_a_pending_step_is_refused_by_the_shared_state_gate(api):
    """PRD §3.6: "Releasing a step — a `CampaignManager` act requiring an open
    write gate, a step in `SCHEDULED`, and a job in `COMMITTED` — moves it
    `SCHEDULED → RELEASED` and increments its `version`."
    PRD §2.6: "20. The remaining state gates — drip steps, drip schedules and
    reprint requests — permit the operation; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/drip_step_release_from_pending_returns_invalid_state
    """
    world = build_drip_scenario(permit_number="PMT-216", job_count=1)
    step = add_drip_step_ok(world["schedule"]["id"], world["jobs"][0]["id"], 1, "2026-06-15")
    assert step["status"] == "PENDING"

    response = api.release_drip_step(step["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_drip_step(step["id"])
    assert after["status"] == "PENDING"
    assert after["computed_mail_date"] == "2026-06-05"


def test_a_second_step_carrying_the_schedules_creation_version_is_stale(api):
    """PRD §2.7: "**Adding a drip step.** `POST
    /mail/drip-schedules/{drip_schedule_id}/steps` requires
    `expected_drip_schedule_version` matching the `DripSchedule`'s current
    `version`."
    PRD §2.7: "New steps reshape the schedule's mail-date spacing, so a client
    holding a stale view of the schedule would compute the minimum-gap check
    against the wrong neighbours. A mismatch is `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_drip_schedule_version_rejects_second_step
    """
    world = build_drip_scenario(permit_number="PMT-262", job_count=1)
    schedule_id = world["schedule"]["id"]
    creation_version = world["schedule"]["version"]

    first = add_drip_step_ok(schedule_id, world["jobs"][0]["id"], 1, "2026-06-15",
                             creation_version)
    assert first["computed_mail_date"] == "2026-06-05"
    assert drip_schedule_version(schedule_id) != creation_version

    response = add_drip_step(schedule_id, world["jobs"][0]["id"], 2, "2026-06-19",
                             creation_version)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    schedule = read_drip_schedule(schedule_id)
    assert schedule["step_count"] == 1
    assert schedule["status"] == "ACTIVE"
