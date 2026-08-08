"""The follow-up contact deadline, the bounded outreach ladder and its cooldown."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_contact_attempt,
    assert_same_instant,
    create_payer,
    declare_holidays,
    disposition_attempt,
    log_attempt,
    read_episode,
    set_clock,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_business_days_contact_deadline_skips_the_weekend(api):
    """PRD §3.3: "A patient discharged on Friday 2026-05-01 with N of 2, and no
    holidays declared, has a deadline of `2026-05-05T23:59:59.999Z`: Saturday
    and Sunday are skipped, Monday 2026-05-04 is the first business day and
    Tuesday 2026-05-05 the second."
    PRD §3.3: "`CONNECTED` moves the attempt `LOGGED → CONNECTED`, sets the
    episode's `contact_status` to `SUCCESSFUL` and its `successful_contact_at`
    to the current instant, and recomputes `contact_timely` as true when
    `successful_contact_at` is on or before `contact_deadline_at` — the
    comparison is inclusive at the deadline instant."

    Design: Difficulty/dual_variant_calc/contact_deadline_business_days_vs_calendar_hours
    """
    ctx = setup_program(payer_overrides={"name": "BD Plan", "contact_deadline_basis": "BUSINESS_DAYS"})
    ep = setup_episode(ctx)
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_sla_business_days"] == 2
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )

    set_clock("2026-05-04T10:00:00Z")
    attempt = log_attempt(ctx, ep, "PHONE")
    disposition_attempt(ctx, ep, attempt["id"], "CONNECTED")

    after = read_episode(ctx, ep["episode_id"])
    assert after["contact_status"] == "SUCCESSFUL"
    assert_same_instant(
        after["successful_contact_at"], "2026-05-04T10:00:00.000Z", "successful_contact_at"
    )
    assert after["contact_timely"] is True


def test_calendar_hours_contact_deadline_lands_two_days_earlier(api):
    """PRD §3.3: "The same Friday discharge at `2026-05-01T14:00:00Z` with N of
    2 yields a deadline of `2026-05-03T14:00:00.000Z`, two full days earlier
    than the business-days variant produced from identical facts."
    PRD §3.3: "When the episode's payer measures the deadline in **calendar
    hours**, no weekend or holiday is skipped at all. The SLA is read as N
    multiplied by 24 wall-clock hours, measured from the exact
    `discharge_datetime` instant, and the deadline lands wherever that
    arithmetic puts it — typically mid-day."

    Design: Difficulty/dual_variant_calc/contact_deadline_business_days_vs_calendar_hours
    """
    ctx = setup_program()
    calendar_payer = create_payer(
        name="CH Plan", tcm_covered=True, contact_deadline_basis="CALENDAR_HOURS"
    )
    ep = setup_episode(ctx, payer_id=calendar_payer["id"])
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_sla_business_days"] == 2
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-03T14:00:00.000Z", "contact_deadline_at"
    )

    set_clock("2026-05-04T10:00:00Z")
    attempt = log_attempt(ctx, ep, "PHONE")
    disposition_attempt(ctx, ep, attempt["id"], "CONNECTED")

    after = read_episode(ctx, ep["episode_id"])
    assert after["contact_status"] == "SUCCESSFUL"
    assert_same_instant(
        after["successful_contact_at"], "2026-05-04T10:00:00.000Z", "successful_contact_at"
    )
    assert after["contact_timely"] is False


def test_second_attempt_at_two_hundred_thirty_nine_minutes_is_rejected(api):
    """PRD §3.3: "Attempts also observe a cooldown: at least 240 minutes — four
    hours — must have elapsed between the previous attempt's `attempted_at` and
    the current instant. The boundary is inclusive, so an attempt logged exactly
    240 minutes later is allowed while one logged at 239 minutes is rejected
    with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/contact_attempt_240_minute_cooldown_boundary
    """
    ctx, ep = setup_program_with_episode()
    first = log_attempt(ctx, ep, "PHONE")
    disposition_attempt(ctx, ep, first["id"], "NO_ANSWER")

    set_clock("2026-05-01T19:59:00Z")
    validate_error(
        api.log_contact_attempt(ep["episode_id"], {"modality": "PHONE"}, ep["nav_headers"]),
        ApiErrorId.ERR_SCHEDULE_CONFLICT.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_attempt_count"] == 1
    disposed = validate_success(api.get_contact_attempt(first["id"], ADMIN))
    assert disposed["attempt_status"] == "NO_ANSWER"
    assert_same_instant(
        disposed["disposition_at"], "2026-05-01T16:00:00.000Z", "disposition_at"
    )


def test_second_attempt_at_exactly_two_hundred_forty_minutes_is_accepted(api):
    """PRD §3.3: "The boundary is inclusive, so an attempt logged exactly 240
    minutes later is allowed while one logged at 239 minutes is rejected with
    `ERR_SCHEDULE_CONFLICT`."
    PRD §3.3: "Each attempt's `attempt_number` is assigned by the server as the
    episode's current `contact_attempt_count` plus 1, and
    `contact_attempt_count` counts every attempt row ever created for the
    episode regardless of how it turned out."

    Design: Difficulty/resource_temporal_overlap/contact_attempt_240_minute_cooldown_boundary
    """
    ctx, ep = setup_program_with_episode()
    first = log_attempt(ctx, ep, "PHONE")
    disposition_attempt(ctx, ep, first["id"], "NO_ANSWER")

    set_clock("2026-05-01T20:00:00Z")
    second = validate_success(
        api.log_contact_attempt(
            ep["episode_id"], {"modality": "PHONE"}, ep["nav_headers"]
        ),
        201,
    )
    assert_contact_attempt(second)
    assert second["attempt_number"] == 2
    assert second["modality"] == "PHONE"
    assert second["attempt_status"] == "LOGGED"
    assert_same_instant(second["attempted_at"], "2026-05-01T20:00:00.000Z", "attempted_at")

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_attempt_count"] == 2
    assert episode["contact_status"] == "IN_PROGRESS"


def test_fifth_contact_attempt_hits_the_four_attempt_cap(api):
    """PRD §3.3: "At most **four** attempts may ever be logged against an
    episode; a fifth is rejected with `ERR_CONTACT_ATTEMPT_LIMIT`."
    PRD §3.3: "When the checks are ordered, the four-attempt cap is tested
    first, the cooldown second and the modality ladder third."

    Design: Corner/validations/fifth_contact_attempt_hits_attempt_limit
    """
    ctx, ep = setup_program_with_episode()
    ladder = [
        ("2026-05-01T16:00:00Z", "PHONE"),
        ("2026-05-01T20:00:00Z", "PHONE"),
        ("2026-05-02T00:00:00Z", "SECURE_MESSAGE"),
        ("2026-05-02T04:00:00Z", "HOME_VISIT"),
    ]
    logged = []
    for at, modality in ladder:
        set_clock(at)
        attempt = log_attempt(ctx, ep, modality)
        disposition_attempt(ctx, ep, attempt["id"], "NO_ANSWER")
        logged.append(attempt)

    set_clock("2026-05-02T08:00:00Z")
    validate_error(
        api.log_contact_attempt(
            ep["episode_id"], {"modality": "HOME_VISIT"}, ep["nav_headers"]
        ),
        ApiErrorId.ERR_CONTACT_ATTEMPT_LIMIT.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_attempt_count"] == 4
    assert episode["contact_status"] == "IN_PROGRESS"
    assert validate_success(api.get_contact_attempt(logged[2]["id"], ADMIN))["modality"] == "SECURE_MESSAGE"
    assert validate_success(api.get_contact_attempt(logged[3]["id"], ADMIN))["modality"] == "HOME_VISIT"


def test_third_attempt_with_phone_modality_is_out_of_sequence(api):
    """PRD §3.3: "The modality is prescribed by position, not chosen freely: the
    first attempt must be `PHONE`, the second must be `PHONE` again, the third
    must be `SECURE_MESSAGE` and the fourth must be `HOME_VISIT`. A `modality`
    that does not match the position is rejected with
    `ERR_MODALITY_OUT_OF_SEQUENCE`."

    Design: Corner/validations/third_attempt_with_phone_modality_out_of_sequence
    """
    ctx, ep = setup_program_with_episode()
    for at in ("2026-05-01T16:00:00Z", "2026-05-01T20:00:00Z"):
        set_clock(at)
        attempt = log_attempt(ctx, ep, "PHONE")
        disposition_attempt(ctx, ep, attempt["id"], "NO_ANSWER")

    set_clock("2026-05-02T00:00:00Z")
    validate_error(
        api.log_contact_attempt(
            ep["episode_id"], {"modality": "PHONE"}, ep["nav_headers"]
        ),
        ApiErrorId.ERR_MODALITY_OUT_OF_SEQUENCE.value,
    )
    assert read_episode(ctx, ep["episode_id"])["contact_attempt_count"] == 2
    _, meta = validate_paginated(
        api.list_contact_attempts(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 2


def test_refusal_locks_the_contact_axis_and_raises_a_system_red_flag(api):
    """PRD §3.3: "`REFUSED` is the sharp one: it moves the attempt `LOGGED →
    REFUSED`, sets the episode's `contact_status` to `REFUSED` so that no
    further attempt may ever be created for that episode, and raises a system
    red flag with `category` `CONTACT_REFUSED` at `TIER_3` in `RAISED` status,
    whose `raised_by_user_id` is recorded as the literal string `SYSTEM` and
    whose acknowledgement deadline is 480 minutes after the current instant."
    PRD §3.3: "A new attempt may not be logged while an earlier attempt on the
    same episode is still sitting in `LOGGED` without a disposition, nor once
    `contact_status` has reached `SUCCESSFUL` or `REFUSED`; all three
    situations are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/contact_refused_spawns_tier3_red_flag_and_locks_contact_axis
    """
    ctx, ep = setup_program_with_episode()
    attempt = log_attempt(ctx, ep, "PHONE")
    refused = disposition_attempt(ctx, ep, attempt["id"], "REFUSED")
    assert refused["attempt_status"] == "REFUSED"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["contact_status"] == "REFUSED"
    assert episode["successful_contact_at"] is None
    assert episode["contact_timely"] is False
    assert episode["open_red_flag_count"] == 1
    assert episode["escalation_state"] == "ACTIVE"

    flags, meta = validate_paginated(
        api.list_red_flags(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 1
    flag = flags[0]
    assert flag["category"] == "CONTACT_REFUSED"
    assert flag["initial_tier"] == "TIER_3"
    assert flag["tier"] == "TIER_3"
    assert flag["status"] == "RAISED"
    assert flag["raised_by_user_id"] == "SYSTEM"
    assert_same_instant(flag["ack_due_at"], "2026-05-02T00:00:00.000Z", "ack_due_at")

    set_clock("2026-05-01T21:00:00Z")
    validate_error(
        api.log_contact_attempt(
            ep["episode_id"], {"modality": "PHONE"}, ep["nav_headers"]
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_episode(ctx, ep["episode_id"])["contact_attempt_count"] == 1


def test_declared_holiday_pushes_the_business_day_contact_deadline(api):
    """PRD §2.4: "Replacing the holiday set is not inert: it immediately
    recomputes `contact_deadline_at` for every care episode whose payer measures
    the contact deadline in business days and whose record posture is still
    open, and then recomputes those episodes' `contact_timely` flag against the
    new deadline."
    PRD §3.3: "A day counts toward N only when its weekday is Monday through
    Friday **and** its date is not in the programme's holiday set."

    Design: Corner/calculations/declared_holiday_pushes_business_day_contact_deadline
    """
    ctx, ep = setup_program_with_episode()
    before = read_episode(ctx, ep["episode_id"])
    assert_same_instant(
        before["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )

    echoed = declare_holidays(["2026-05-04"])
    assert echoed["holiday_dates"] == ["2026-05-04"]

    after = read_episode(ctx, ep["episode_id"])
    assert_same_instant(
        after["contact_deadline_at"], "2026-05-06T23:59:59.999Z", "contact_deadline_at"
    )
    assert after["contact_sla_business_days"] == 2
