"""Reserving press minutes: interval geometry, the day cap and the minute ledger."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_job,
    create_job,
    read_job,
    read_lot,
    read_mold,
    read_press,
    schedule_job,
    setup_approved_tool,
    setup_scheduled_job,
    setup_staged_job,
    validate_error,
    validate_success,
)

PE = TEST_USERS["process_engineer_headers"]


def test_a_forty_four_minute_gap_still_collides_on_the_press(api):
    """PRD §2.9: "A candidate job collides with an existing job on the same press
    unless either the candidate starts at least 45 minutes after the existing job
    ends, or the candidate ends at least 45 minutes before the existing job starts.
    A candidate starting exactly 45 minutes after an existing job ends is accepted;
    one minute earlier collides."
    PRD §2.9: "A collision is rejected with `ERR_PRESS_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/press_half_open_window_needs_full_changeover_buffer
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T08:00:00Z",
            "scheduled_end": "2026-09-10T12:00:00Z",
        }
    )
    near_miss = add_job(shop, "2026-09-10T12:44:00Z", "2026-09-10T14:00:00Z")

    response = api.schedule_job(
        near_miss["id"],
        {"expected_press_version": read_press(shop["press"]["id"])["version"]},
        PE,
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_PRESS_WINDOW_CONFLICT.value)
    assert read_job(near_miss["id"])["run_status"] == "DRAFT"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 240


def test_a_gap_of_exactly_the_changeover_buffer_is_accepted_and_adds_to_the_ledger(api):
    """PRD §2.9: "A press cannot go from one tool to the next instantaneously; a
    mandatory changeover buffer of **45 minutes** must separate two occupancies of
    the same machine, and the buffer is applied to the *gap* between them."
    PRD §2.9: "Alongside the collision rules, each press carries a **minute
    ledger**, `committed_minutes_scheduled`, defined as the sum of the whole-minute
    durations of every job on that press whose `run_status` is `SCHEDULED` or
    `RUNNING`."

    Design: Difficulty/resource_temporal_overlap/press_half_open_window_needs_full_changeover_buffer
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T08:00:00Z",
            "scheduled_end": "2026-09-10T12:00:00Z",
        }
    )
    exact_gap = add_job(shop, "2026-09-10T12:45:00Z", "2026-09-10T14:00:00Z")

    data = validate_success(
        api.schedule_job(
            exact_gap["id"],
            {"expected_press_version": read_press(shop["press"]["id"])["version"]},
            PE,
        )
    )

    assert data["run_status"] == "SCHEDULED"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 315, (
        "240 minutes for the first job plus 75 for the second"
    )


def test_an_overlapping_schedule_reports_the_window_conflict_not_the_day_cap(api):
    """PRD §2.7: "Requests are screened in a fixed order, and the **first** check
    that fails determines the response. This ordering is normative: a request that
    would fail two different checks always reports the earlier one."
    PRD §2.7: "**Press window overlap.** `ERR_PRESS_WINDOW_CONFLICT` (409)."
    PRD §2.7: "**Press daily capacity.** `ERR_PRESS_DAILY_CAPACITY_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/press_window_conflict_beats_daily_capacity_on_schedule
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T00:00:00Z",
            "scheduled_end": "2026-09-10T20:00:00Z",
        }
    )
    overlapping = add_job(shop, "2026-09-10T19:00:00Z", "2026-09-10T23:00:00Z", planned_qty=5000)

    response = api.schedule_job(
        overlapping["id"],
        {"expected_press_version": read_press(shop["press"]["id"])["version"]},
        PE,
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_PRESS_WINDOW_CONFLICT.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PRESS_DAILY_CAPACITY_EXCEEDED.value


def test_the_rejected_overlap_leaves_the_job_draft_and_the_ledger_untouched(api):
    """PRD §2.9: "A collision is rejected with `ERR_PRESS_WINDOW_CONFLICT`."
    PRD §2.9: "Alongside the collision rules, each press carries a **minute
    ledger**, `committed_minutes_scheduled`, defined as the sum of the whole-minute
    durations of every job on that press whose `run_status` is `SCHEDULED` or
    `RUNNING`."
    PRD §3.6: "On success the job's whole-minute duration is added to the press's
    `committed_minutes_scheduled` and the press's `version` is incremented by 1."

    Design: Difficulty/priority_pair_validation_conflict/press_window_conflict_beats_daily_capacity_on_schedule
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T00:00:00Z",
            "scheduled_end": "2026-09-10T20:00:00Z",
        }
    )
    overlapping = add_job(shop, "2026-09-10T19:00:00Z", "2026-09-10T23:00:00Z", planned_qty=5000)

    response = api.schedule_job(
        overlapping["id"],
        {"expected_press_version": read_press(shop["press"]["id"])["version"]},
        PE,
    )
    assert response.status_code == 409

    assert read_job(overlapping["id"])["run_status"] == "DRAFT"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 1200, (
        "only the first job's 1200 minutes are booked; 1200 + 240 would have breached the day cap"
    )


def test_the_daily_cap_refuses_a_non_overlapping_but_oversized_day(api):
    """PRD §2.9: "Finally, a press may not be booked past **1,224 minutes — twenty
    hours and twenty-four minutes — of committed time on any single UTC calendar
    day**. The day is the UTC calendar date of the candidate job's
    `scheduled_start`; the running total is the summed duration of every job on that
    press whose `run_status` is `SCHEDULED` or `RUNNING` and whose own
    `scheduled_start` falls on that same UTC date; and if that total plus the
    candidate's duration exceeds 1,224 minutes, the request is rejected with
    `ERR_PRESS_DAILY_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/press_daily_capacity_gate_rejects_a_non_overlapping_but_oversized_day
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T00:00:00Z",
            "scheduled_end": "2026-09-10T10:00:00Z",
        }
    )
    oversized = add_job(shop, "2026-09-10T10:45:00Z", "2026-09-10T23:45:00Z")

    response = api.schedule_job(
        oversized["id"],
        {"expected_press_version": read_press(shop["press"]["id"])["version"]},
        PE,
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_PRESS_DAILY_CAPACITY_EXCEEDED.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PRESS_WINDOW_CONFLICT.value, (
        "the windows are separated by exactly the 45-minute changeover buffer"
    )
    assert read_job(oversized["id"])["run_status"] == "DRAFT"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 600


def test_cancelling_a_scheduled_job_returns_the_press_ledger_to_zero(api):
    """PRD §3.6: "Cancelling a `SCHEDULED` or a `RUNNING` job releases its duration
    from the press's `committed_minutes_scheduled` and increments the press's
    `version` by 1, and moves `material_status` `STAGED → UNSTAGED` with
    `staged_resin_lot_id` cleared."
    PRD §2.9: "Every forward reservation increases it and every compensating release
    decreases it, so the ledger is an exact identity at rest rather than an
    approximation."

    Design: Difficulty/compensating_invariant/job_cancellation_conserves_press_committed_minutes
    """
    shop = setup_staged_job()
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    cancelled = validate_success(
        api.cancel_job(shop["job"]["id"], {"reason": "customer pulled the release"}, PE)
    )

    assert cancelled["run_status"] == "CANCELLED"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 0


def test_cancelling_de_stages_the_job_without_touching_the_resin_ledger(api):
    """PRD §3.6: "Cancelling a `SCHEDULED` or a `RUNNING` job releases its duration
    from the press's `committed_minutes_scheduled` and increments the press's
    `version` by 1, and moves `material_status` `STAGED → UNSTAGED` with
    `staged_resin_lot_id` cleared."
    PRD §3.6: "In every cancellation path, shift reports already posted against the
    job keep their `resin_lot_id` snapshot and remain non-reversed, so the resin and
    shot ledgers are untouched by the cancellation; and `as_run_piece_price_cents`
    and `price_variance_cents` stay unset, because the as-run pricing pass runs only
    on completion."

    Design: Difficulty/compensating_invariant/job_cancellation_conserves_press_committed_minutes
    """
    shop = setup_staged_job()

    cancelled = validate_success(
        api.cancel_job(shop["job"]["id"], {"reason": "customer pulled the release"}, PE)
    )

    assert cancelled["material_status"] == "UNSTAGED"
    assert cancelled.get("staged_resin_lot_id") is None
    assert cancelled.get("as_run_piece_price_cents") is None
    assert cancelled.get("price_variance_cents") is None
    lot = read_lot(shop["lot"]["id"])
    assert lot["qty_grams_remaining"] == 500000, "cancelling consumes no material"
    assert lot["status"] == "RELEASED"
    mold = read_mold(shop["mold"]["id"])
    assert mold["total_shot_count"] == 0
    assert mold["service_state"] == "SERVICEABLE"


def test_a_scheduled_unstaged_job_refuses_unblock_start_and_complete_distinctly(api):
    """PRD §3.6: "Unblocking a job that is not `BLOCKED` is rejected with
    `ERR_JOB_NOT_BLOCKED`."
    PRD §3.6: "Starting a job carries no request body at all. It advances
    `SCHEDULED → RUNNING` and requires that the job's `material_status` is `STAGED`
    — otherwise `ERR_JOB_MATERIAL_NOT_STAGED` — that the staged lot's `status` is
    still `RELEASED`, otherwise `ERR_RESIN_LOT_NOT_RELEASED`, and that the tool is
    still `PPAP_APPROVED` or `INTERIM_APPROVED` with `service_state` `SERVICEABLE`."
    PRD §3.6: "Completing a job that is not `RUNNING` is rejected with
    `ERR_JOB_NOT_RUNNING`."

    Design: Corner/endpoints/scheduled_job_rejects_unblock_start_without_material_and_complete
    """
    shop = setup_scheduled_job()
    job_id = shop["job"]["id"]

    unblock = api.unblock_job(
        job_id,
        {"expected_press_version": read_press(shop["press"]["id"])["version"]},
        PE,
    )
    assert unblock.status_code == 409, f"Expected 409, got {unblock.status_code}"
    validate_error(unblock, ApiErrorId.ERR_JOB_NOT_BLOCKED.value)

    start = api.start_job(job_id, PE)
    assert start.status_code == 409, f"Expected 409, got {start.status_code}"
    validate_error(start, ApiErrorId.ERR_JOB_MATERIAL_NOT_STAGED.value)

    complete = api.complete_job(job_id, PE)
    assert complete.status_code == 409, f"Expected 409, got {complete.status_code}"
    validate_error(complete, ApiErrorId.ERR_JOB_NOT_RUNNING.value)

    job = read_job(job_id)
    assert job["run_status"] == "SCHEDULED"
    assert job["material_status"] == "UNSTAGED"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480


def test_the_schedule_response_body_already_carries_every_side_effect(api):
    """PRD §3.6: "Scheduling turns the plan into a booking and is where the press
    ledger first moves. The `ProcessEngineer` supplies `expected_press_version`, and
    the job advances `DRAFT → SCHEDULED`."
    PRD §2.4: "The `version` of a resource starts at 1 when the resource is created
    and is incremented by exactly 1 on every mutation of that resource, and
    `updated_at` is refreshed to the current logical time on the same mutation."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/consistency_model/schedule_response_body_already_reflects_every_side_effect
    """
    shop = setup_approved_tool(with_lot=False)
    job = create_job(shop["quote"]["id"], press_id=shop["press"]["id"])
    press_before = read_press(shop["press"]["id"])

    response = api.schedule_job(
        job["id"], {"expected_press_version": press_before["version"]}, PE
    )
    data = validate_success(response)

    assert data["run_status"] == "SCHEDULED"
    assert data["version"] == 2, "creation minted version 1; scheduling is the first mutation"
    assert response.json()["meta"]["api_request_id"].startswith("req_")

    press_response = api.get_press(shop["press"]["id"], PE)
    press_after = validate_success(press_response)
    assert press_after["committed_minutes_scheduled"] == 480
    assert press_after["version"] == press_before["version"] + 1
    assert press_response.json()["meta"]["api_request_id"].startswith("req_")


def test_scheduling_with_a_stale_press_version_is_rejected_and_retries_cleanly(api):
    """PRD §2.5: "Scheduling a production job requires `expected_press_version`
    matching the target press's current `version`. A mismatch is rejected with
    `ERR_STALE_PRESS_VERSION` (HTTP 412)."
    PRD §3.6: "On success the job's whole-minute duration is added to the press's
    `committed_minutes_scheduled` and the press's `version` is incremented by 1."

    Design: Corner/cross_cutting_layers/stale_press_version_on_schedule_returns_412
    """
    shop = setup_approved_tool(with_lot=False)
    job_a = create_job(
        shop["quote"]["id"],
        press_id=shop["press"]["id"],
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T16:00:00Z",
    )
    job_b = create_job(
        shop["quote"]["id"],
        press_id=shop["press"]["id"],
        scheduled_start="2026-09-12T08:00:00Z",
        scheduled_end="2026-09-12T16:00:00Z",
    )
    version_pre = read_press(shop["press"]["id"])["version"]
    schedule_job(job_a["id"], shop["press"]["id"])

    stale = api.schedule_job(job_b["id"], {"expected_press_version": version_pre}, PE)
    assert stale.status_code == 412, f"Expected 412, got {stale.status_code}"
    validate_error(stale, ApiErrorId.ERR_STALE_PRESS_VERSION.value)
    assert read_job(job_b["id"])["run_status"] == "DRAFT"
    version_post = read_press(shop["press"]["id"])["version"]
    assert version_post == version_pre + 1
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    retry = validate_success(
        api.schedule_job(job_b["id"], {"expected_press_version": version_post}, PE)
    )
    assert retry["run_status"] == "SCHEDULED"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 960
