"""Computed summaries (teacher utilization, family risk variants), optimistic
concurrency on window writes, and immediate read-after-write consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_teacher,
    assert_family,
    book_slot,
    generate_slots,
    get_success_data,
    publish_window,
    read_window,
    scenario_risk_marks,
    scenario_utilization,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)

OCC_WINDOW_QUOTE = (
    "Updating a conference window's configuration requires the request to carry "
    "`expected_window_version` equal to the window's current `version`. The "
    "window's version advances on every configuration edit, on every "
    "slot-generation run, and on every lifecycle transition, so a client that read "
    "the window before another writer acted holds a stale number. A mismatch is "
    "rejected with `ERR_STALE_VERSION` (HTTP 412)."
)

UTIL_COUNTS_QUOTE = (
    "It counts the teacher's slots in that window with status `OPEN`, `BLOCKED`, "
    "`HELD`, or `BOOKED` as `bookable_slots` — `RETIRED` slots are excluded — and "
    "reports the `BOOKED` subset as `booked_slots`, the `HELD` subset as "
    "`held_slots`, the `OPEN` subset as `open_slots`, and the teacher's `WAITING` "
    "waitlist entries in the window as `waiting_entries`, echoing the `teacher_id` "
    "and `window_id`."
)

RISK_QUOTE = (
    "The strict variant, stored as `attendance_risk_strict`, is simply the "
    "lifetime count of the family's `NO_SHOW` records across every booking in "
    "every window, weighted at 1.0 each — it ignores strike clears entirely. The "
    "weighted variant, stored as `attendance_risk_score`, counts each `NO_SHOW` at "
    "1.0, each `LATE` at 0.5, and each `EXCUSED` at 0.25 over the same lifetime "
    "record set; a family with one no-show, one late arrival, and one excused "
    "absence therefore reads 1.00 on the strict scale and 1.75 on the weighted "
    "scale. The third number, `no_show_strike_count`, is the lifetime `NO_SHOW` "
    "count minus the family's `strikes_cleared_total`, floored at zero."
)


def test_occ_stale_window_patch_rejected(api, school_admin_headers):
    """PRD 2.6: "Updating a conference window's configuration requires the
    request to carry `expected_window_version` equal to the window's current
    `version`. The window's version advances on every configuration edit, on
    every slot-generation run, and on every lifecycle transition, so a client
    that read the window before another writer acted holds a stale number. A
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_window_patch_rejected
    """
    ctx = setup_window_at_stage("PUBLISHED")
    window_id = ctx["window"]["id"]
    fresh_version = ctx["window"]["version"]       # advanced by generation
    stale_version = fresh_version - 1              # the post-publish reading

    rejected = api.patch_window(
        window_id,
        {"expected_window_version": stale_version, "teacher_daily_conf_cap": 4},
        school_admin_headers,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION, 412)

    patched = validate_success(api.patch_window(
        window_id,
        {"expected_window_version": fresh_version, "teacher_daily_conf_cap": 4},
        school_admin_headers,
    ))
    assert patched["teacher_daily_conf_cap"] == 4
    assert patched["version"] == fresh_version + 1


def test_occ_stale_regeneration_rejected(api, school_admin_headers):
    """PRD 2.6: "Running slot generation for a window likewise requires
    `expected_window_version`. Because generation destroys and recreates the
    slot grid, the caller must have observed the window's current version; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.2: "A permitted regeneration retires the entire existing grid — every
    slot moves to `RETIRED`, and `RETIRED` slots never reopen — and then builds
    a fresh grid from the current configuration."

    Design: Corner/complexity_layers/occ_stale_regeneration_rejected
    """
    ctx = setup_window_at_stage("PUBLISHED")
    window_id = ctx["window"]["id"]
    fresh_version = ctx["window"]["version"]
    stale_version = fresh_version - 1

    rejected = api.generate_slots(
        window_id, {"expected_window_version": stale_version}, school_admin_headers
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION, 412)

    regenerated = validate_success(api.generate_slots(
        window_id, {"expected_window_version": fresh_version}, school_admin_headers
    ))
    # The retired grid is not double-counted against the fresh one.
    assert regenerated["slots_total_count"] == 8
    assert regenerated["slots_open_count"] == 8
    assert regenerated["version"] == fresh_version + 1


def test_immediate_consistency_booking_visible(api):
    """PRD 2.8: "These counters are recomputed by every operation that can
    change them — slot generation, blocking and unblocking, booking creation,
    cancellation, rescheduling, waitlist promotion, claims, declines,
    withdrawals, the window lock, and the deactivation, restriction, and
    withdrawal cascades — so a read of the window always reflects the current
    state of its children."
    PRD 3.4: "A successful create moves the slot from `OPEN` to `BOOKED`,
    stores the booking in `CONFIRMED` status with `version` 1, and — when
    `interpreter_language` was supplied — automatically creates an interpreter
    request in `REQUESTED` status for the booking."

    Design: Corner/consistency_model/immediate_consistency_booking_visible
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    slot = ctx["teacher_slots"][teacher_id][0]

    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"])
    assert booking["status"] == "CONFIRMED"

    slot_after = validate_success(api.get_slot(slot["id"], party["guardian"]))
    assert slot_after["status"] == "BOOKED"

    window_after = validate_success(api.get_window(ctx["window"]["id"], party["guardian"]))
    assert window_after["slots_booked_count"] == 1
    assert window_after["bookings_confirmed_count"] == 1


def test_teacher_utilization_booked_variant(api, school_admin_headers):
    """PRD 3.9: "It counts the teacher's slots in that window with status
    `OPEN`, `BLOCKED`, `HELD`, or `BOOKED` as `bookable_slots` — `RETIRED`
    slots are excluded — and reports the `BOOKED` subset as `booked_slots`, the
    `HELD` subset as `held_slots`, the `OPEN` subset as `open_slots`, and the
    teacher's `WAITING` waitlist entries in the window as `waiting_entries`,
    echoing the `teacher_id` and `window_id`."
    PRD 3.9: "The `booked_utilization_pct` is one hundred times the booked
    count divided by the bookable count, rounded half-up to two decimal places,
    and reports 0.00 when there are no bookable slots."

    Design: Difficulty/dual_variant_calc/teacher_utilization_booked_vs_projected
    """
    ctx = scenario_utilization()
    teacher_id = ctx["teachers"][0]["id"]
    summary = validate_success(api.get_teacher_summary(
        teacher_id, school_admin_headers, params={"window_id": ctx["window"]["id"]}
    ))
    assert summary["teacher_id"] == teacher_id
    assert summary["window_id"] == ctx["window"]["id"]
    assert summary["bookable_slots"] == 8
    assert summary["booked_slots"] == 4
    assert summary["held_slots"] == 0
    assert summary["waiting_entries"] == 2
    # 100 * 4 / 8 = 50.00.
    assert summary["booked_utilization_pct"] == pytest.approx(50.00, abs=0.01)


def test_teacher_utilization_projected_variant(api, school_admin_headers):
    """PRD 3.9: "The `projected_utilization_pct` is forward-looking: it adds
    the held count plus half the waiting entries rounded up to a whole number
    to the booked count before dividing by the same bookable count — one
    hundred times that quotient, rounded half-up to two decimal places — so the
    projection is strictly larger than the booked figure whenever held slots or
    expected claims exist."

    Design: Difficulty/dual_variant_calc/teacher_utilization_booked_vs_projected
    """
    ctx = scenario_utilization()
    teacher_id = ctx["teachers"][0]["id"]
    summary = validate_success(api.get_teacher_summary(
        teacher_id, school_admin_headers, params={"window_id": ctx["window"]["id"]}
    ))
    # 100 * (4 booked + 0 held + ceil(2 waiting * 0.5)) / 8 = 62.50.
    assert summary["projected_utilization_pct"] == pytest.approx(62.50, abs=0.01)
    assert summary["projected_utilization_pct"] != summary["booked_utilization_pct"]


def test_utilization_zero_bookable_returns_zero(api, school_admin_headers):
    """PRD 3.9: "The `booked_utilization_pct` is one hundred times the booked
    count divided by the bookable count, rounded half-up to two decimal places,
    and reports 0.00 when there are no bookable slots."
    PRD 3.9: "It counts the teacher's slots in that window with status `OPEN`,
    `BLOCKED`, `HELD`, or `BOOKED` as `bookable_slots` — `RETIRED` slots are
    excluded — and reports the `BOOKED` subset as `booked_slots`, the `HELD`
    subset as `held_slots`, the `OPEN` subset as `open_slots`, and the
    teacher's `WAITING` waitlist entries in the window as `waiting_entries`,
    echoing the `teacher_id` and `window_id`."

    Design: Corner/calculations/utilization_zero_bookable_returns_zero
    """
    ctx = setup_window_at_stage("PUBLISHED")
    teacher = ctx["teachers"][0]
    # Deactivation in a PUBLISHED window retires every slot of the teacher.
    get_success_data(api.patch_teacher(teacher["id"], {"status": "INACTIVE"},
                                       school_admin_headers))

    summary = validate_success(api.get_teacher_summary(
        teacher["id"], school_admin_headers, params={"window_id": ctx["window"]["id"]}
    ))
    assert summary["bookable_slots"] == 0
    assert summary["booked_utilization_pct"] == pytest.approx(0.00, abs=0.01)
    assert summary["projected_utilization_pct"] == pytest.approx(0.00, abs=0.01)


def test_family_risk_strict_variant(api, front_office_headers):
    """PRD 3.8: "The strict variant, stored as `attendance_risk_strict`, is
    simply the lifetime count of the family's `NO_SHOW` records across every
    booking in every window, weighted at 1.0 each — it ignores strike clears
    entirely. The weighted variant, stored as `attendance_risk_score`, counts
    each `NO_SHOW` at 1.0, each `LATE` at 0.5, and each `EXCUSED` at 0.25 over
    the same lifetime record set; a family with one no-show, one late arrival,
    and one excused absence therefore reads 1.00 on the strict scale and 1.75
    on the weighted scale. The third number, `no_show_strike_count`, is the
    lifetime `NO_SHOW` count minus the family's `strikes_cleared_total`,
    floored at zero."

    Design: Difficulty/dual_variant_calc/family_risk_strict_vs_weighted
    """
    ctx = scenario_risk_marks()
    family = validate_success(
        api.get_family(ctx["party"]["family"]["id"], front_office_headers))
    assert_family(family)
    # One NO_SHOW, one LATE, one EXCUSED: strict counts NO_SHOW only.
    assert family["attendance_risk_strict"] == pytest.approx(1.00, abs=0.01)
    assert family["no_show_strike_count"] == 1


def test_family_risk_weighted_variant(api, front_office_headers):
    """PRD 3.8: "The weighted variant, stored as `attendance_risk_score`,
    counts each `NO_SHOW` at 1.0, each `LATE` at 0.5, and each `EXCUSED` at
    0.25 over the same lifetime record set; a family with one no-show, one late
    arrival, and one excused absence therefore reads 1.00 on the strict scale
    and 1.75 on the weighted scale."

    Design: Difficulty/dual_variant_calc/family_risk_strict_vs_weighted
    """
    ctx = scenario_risk_marks()
    family = validate_success(
        api.get_family(ctx["party"]["family"]["id"], front_office_headers))
    # 1.0 * 1 NO_SHOW + 0.5 * 1 LATE + 0.25 * 1 EXCUSED = 1.75.
    assert family["attendance_risk_score"] == pytest.approx(1.75, abs=0.01)
    assert family["attendance_risk_score"] != family["attendance_risk_strict"]
