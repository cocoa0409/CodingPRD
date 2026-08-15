"""Conference window lifecycle: state gates, temporal gates, grid lock,
regeneration guard, and the archive outreach guard."""
from test_helpers import (
    ApiErrorId,
    add_family,
    add_teacher,
    assert_window,
    create_outreach_task_payload,
    create_window_payload,
    generate_slots,
    get_success_data,
    publish_window,
    read_window,
    set_clock,
    setup_booked_slot,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


def test_window_initial_state_draft(api, school_admin_headers):
    """PRD 3.1: "A new window is born in `DRAFT` status with `ops_run_index` at
    0, every counter at 0, and `version` at 1."

    Design: Corner/state_machines/window_initial_state_draft
    """
    data = validate_success(api.create_window(create_window_payload(), school_admin_headers), 201)
    assert_window(data)
    assert data["status"] == "DRAFT"
    assert data["ops_run_index"] == 0


def test_republish_rejected(api, school_admin_headers):
    """PRD 2.7: "Whether the window's `status` permits the operation at all —
    booking, cancellation, rescheduling, and waitlist join need `BOOKING_OPEN`;
    publish needs `DRAFT`; opening booking needs `PUBLISHED`; locking needs
    `BOOKING_OPEN`; starting needs `LOCKED`; completing needs `IN_PROGRESS`;
    archiving needs `COMPLETED`; slot generation needs `PUBLISHED`; slot block
    and unblock need `PUBLISHED` or `BOOKING_OPEN`; attendance marking needs
    `IN_PROGRESS` or `COMPLETED`; failures yield `ERR_INVALID_WINDOW_STATE`
    (409)."
    PRD 3.1: "Publication moves the window from `DRAFT` to `PUBLISHED`."

    Design: Corner/state_machines/republish_rejected
    """
    window = get_success_data(api.create_window(create_window_payload(), school_admin_headers))
    publish_window(window["id"])
    response = api.publish_window(window["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)
    assert read_window(window["id"])["status"] == "PUBLISHED"


def test_archive_before_complete_rejected(api, school_admin_headers):
    """PRD 2.7: "Whether the window's `status` permits the operation at all —
    booking, cancellation, rescheduling, and waitlist join need `BOOKING_OPEN`;
    publish needs `DRAFT`; opening booking needs `PUBLISHED`; locking needs
    `BOOKING_OPEN`; starting needs `LOCKED`; completing needs `IN_PROGRESS`;
    archiving needs `COMPLETED`; slot generation needs `PUBLISHED`; slot block
    and unblock need `PUBLISHED` or `BOOKING_OPEN`; attendance marking needs
    `IN_PROGRESS` or `COMPLETED`; failures yield `ERR_INVALID_WINDOW_STATE`
    (409)."

    Design: Corner/state_machines/archive_before_complete_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    response = api.archive_window(ctx["window"]["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)


def test_archived_window_is_terminal(api, school_admin_headers):
    """PRD 3.9: "Archiving moves the window from `COMPLETED` to `ARCHIVED`, and
    it is refused while any outreach task of that window is still `OPEN` or
    `CONTACTED` — the attempt is rejected with `ERR_OPEN_OUTREACH_TASKS` until
    the queue is worked down. Archival increments the window's `version` and
    ends the lifecycle: `ARCHIVED` is terminal."
    PRD 2.7: "Whether the window's `status` permits the operation at all —
    booking, cancellation, rescheduling, and waitlist join need `BOOKING_OPEN`;
    publish needs `DRAFT`; opening booking needs `PUBLISHED`; locking needs
    `BOOKING_OPEN`; starting needs `LOCKED`; completing needs `IN_PROGRESS`;
    archiving needs `COMPLETED`; slot generation needs `PUBLISHED`; slot block
    and unblock need `PUBLISHED` or `BOOKING_OPEN`; attendance marking needs
    `IN_PROGRESS` or `COMPLETED`; failures yield `ERR_INVALID_WINDOW_STATE`
    (409)."

    Design: Corner/state_machines/archived_window_is_terminal
    """
    ctx = setup_window_at_stage("COMPLETED")
    archived = validate_success(api.archive_window(ctx["window"]["id"], school_admin_headers))
    assert_window(archived)
    assert archived["status"] == "ARCHIVED"
    response = api.start_window(ctx["window"]["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)


def test_open_booking_without_slots_rejected(api, school_admin_headers):
    """PRD 3.4: "Two gates guard the transition, evaluated under the ordering
    of §2.7: the window must actually have inventory — `slots_total_count`
    greater than zero, meaning generation has run, otherwise
    `ERR_INVALID_WINDOW_STATE` — and the logical clock must have reached
    `booking_open_at`, otherwise `ERR_BOOKING_WINDOW_NOT_OPEN`."

    Design: Corner/validations/open_booking_without_slots_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    window = get_success_data(api.create_window(create_window_payload(), school_admin_headers))
    publish_window(window["id"])
    response = api.open_booking(window["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)


def test_open_booking_before_open_at_rejected(api, school_admin_headers):
    """PRD 3.4: "Two gates guard the transition, evaluated under the ordering
    of §2.7: the window must actually have inventory — `slots_total_count`
    greater than zero, meaning generation has run, otherwise
    `ERR_INVALID_WINDOW_STATE` — and the logical clock must have reached
    `booking_open_at`, otherwise `ERR_BOOKING_WINDOW_NOT_OPEN`."

    Design: Corner/validations/open_booking_before_open_at_rejected
    """
    # Clock sits before the window's booking_open_at (2026-09-01).
    set_clock("2026-08-15T00:00:00Z")
    window = get_success_data(api.create_window(create_window_payload(), school_admin_headers))
    add_teacher()
    published = publish_window(window["id"])
    generate_slots(window["id"], published["version"])
    response = api.open_booking(window["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_BOOKING_WINDOW_NOT_OPEN, 422)
    assert read_window(window["id"])["status"] == "PUBLISHED"


def test_lock_before_close_rejected(api, school_admin_headers):
    """PRD 3.8: "Locking moves the window from `BOOKING_OPEN` to `LOCKED` and
    is allowed once the logical clock has reached `booking_close_at` — an
    earlier attempt is rejected with `ERR_BOOKING_WINDOW_NOT_CLOSED`."

    Design: Corner/validations/lock_before_close_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    set_clock("2026-09-15T00:00:00Z")
    response = api.lock_window(ctx["window"]["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_BOOKING_WINDOW_NOT_CLOSED, 422)
    assert read_window(ctx["window"]["id"])["status"] == "BOOKING_OPEN"


def test_publish_with_invalid_day_window_rejected(api, school_admin_headers):
    """PRD 3.1: "The administrator may publish only when `day_windows` is
    non-empty and every entry ends strictly after it starts — a day range whose
    `end_at` does not fall after its `start_at` is rejected with
    `ERR_INVALID_DAY_WINDOW` — and when the slot length is positive and the
    buffer and travel values are non-negative."

    Design: Corner/validations/publish_with_invalid_day_window_rejected
    """
    payload = create_window_payload(
        name="Bad",
        day_windows=[{
            "date": "2026-10-05",
            "start_at": "2026-10-05T19:00:00Z",
            "end_at": "2026-10-05T15:00:00Z",
        }],
    )
    window = get_success_data(api.create_window(payload, school_admin_headers))
    response = api.publish_window(window["id"], school_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_DAY_WINDOW, 422)
    assert read_window(window["id"])["status"] == "DRAFT"


def test_grid_patch_after_generation_rejected(api, school_admin_headers):
    """PRD 3.1: "Once slots exist, the grid fields — `slot_length_minutes`,
    `buffer_minutes`, and `day_windows` — are frozen, and any attempt to change
    them is rejected with `ERR_WINDOW_GRID_LOCKED`; the remaining fields,
    including `name`, `booking_open_at`, `booking_close_at`,
    `teacher_daily_conf_cap`, `family_conf_cap`, `cancel_cutoff_hours`,
    `waitlist_offer_ttl_hours`, `no_show_strike_threshold`,
    `auto_no_show_grace_hours`, and `travel_minutes`, stay editable."
    PRD 3.1: "Every edit requires `expected_window_version` per §2.6 and
    increments the window's `version`."

    Design: Corner/validations/grid_patch_after_generation_rejected
    """
    ctx = setup_window_at_stage("PUBLISHED")
    window_id = ctx["window"]["id"]
    current_version = ctx["window"]["version"]

    blocked = api.patch_window(
        window_id,
        {"expected_window_version": current_version, "slot_length_minutes": 30},
        school_admin_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_WINDOW_GRID_LOCKED, 409)

    patched = validate_success(api.patch_window(
        window_id,
        {"expected_window_version": current_version, "teacher_daily_conf_cap": 4},
        school_admin_headers,
    ))
    assert_window(patched)
    assert patched["teacher_daily_conf_cap"] == 4
    assert patched["version"] == current_version + 1


def test_regenerate_with_bookings_rejected(api, school_admin_headers):
    """PRD 3.2: "When slots already exist, a fresh generation run is allowed
    only while no booking references any slot of the window; the moment any
    booking exists, regeneration is refused with `ERR_SLOTS_ALREADY_BOOKED`."

    Design: Corner/validations/regenerate_with_bookings_rejected
    """
    ctx = setup_booked_slot()
    window_id = ctx["window"]["id"]
    current = read_window(window_id)
    response = api.generate_slots(
        window_id, {"expected_window_version": current["version"]}, school_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_SLOTS_ALREADY_BOOKED, 409)


def test_archive_with_open_outreach_rejected(api, school_admin_headers, front_office_headers):
    """PRD 3.9: "Archiving moves the window from `COMPLETED` to `ARCHIVED`, and
    it is refused while any outreach task of that window is still `OPEN` or
    `CONTACTED` — the attempt is rejected with `ERR_OPEN_OUTREACH_TASKS` until
    the queue is worked down."
    PRD 3.9: "A task is born `OPEN` with `attempts_count` at 0."

    Design: Corner/validations/archive_with_open_outreach_rejected
    """
    ctx = setup_window_at_stage("COMPLETED")
    window_id = ctx["window"]["id"]
    family = add_family()
    task = get_success_data(api.create_outreach_task(
        create_outreach_task_payload(family["id"], "NO_SHOW_FOLLOW_UP",
                                     window_id=window_id, note="call home"),
        front_office_headers,
    ))
    assert task["status"] == "OPEN"

    blocked = api.archive_window(window_id, school_admin_headers)
    validate_error(blocked, ApiErrorId.ERR_OPEN_OUTREACH_TASKS, 409)

    get_success_data(api.resolve_task(task["id"], {}, front_office_headers))
    archived = validate_success(api.archive_window(window_id, school_admin_headers))
    assert archived["status"] == "ARCHIVED"
