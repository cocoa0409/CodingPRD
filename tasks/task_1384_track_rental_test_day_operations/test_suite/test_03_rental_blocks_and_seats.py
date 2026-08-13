"""Rental-block constraints, seat accounting, and approval integrity."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_track, make_track_day, make_open_track_day, make_block,
    make_booking, approve_booking, get_block, block_version,
    assert_block_seat_invariant, setup_open_day_with_block,
    create_rental_block_payload,
    TEST_USERS, make_organizer_headers,
)

OPS = TEST_USERS["trackops_headers"]


def test_group_size_exceeds_track_cap_returns_422(api):
    """PRD §3.2: "Each block also declares `max_group_size`, the cap on
    simultaneous on-track cars for that block, which must not exceed the
    track's `run_group_capacity`; a block that oversteps the venue cap is
    rejected with `ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP` (422)."

    Design: Corner/validations/group_size_exceeds_track_cap_returns_422
    """
    track = make_track(name="V4", run_group_capacity=4)
    day = make_track_day(track["id"], "2026-09-23")
    resp = api.create_rental_block(
        track["id"], day["id"],
        create_rental_block_payload(max_group_size=10), OPS)
    validate_error(resp, ApiErrorId.ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP)


def test_invalid_driver_count_zero_rejected(api):
    """PRD §3.3: "The declared `driver_count` must be at least one and no more
    than the block's `max_group_size` — violations draw
    `ERR_INVALID_DRIVER_COUNT` (422) — and the submission itself is rejected
    with `ERR_BLOCK_FULL` (409) when the block is already `FULL`, or with
    `ERR_TRACK_DAY_NOT_LIVE` (409) when the day is cancelled or closed."

    Design: Corner/validations/invalid_driver_count_zero_rejected
    """
    env = setup_open_day_with_block("2026-09-24")
    resp = api.create_booking(
        env["track"]["id"], env["day"]["id"], env["block"]["id"],
        {"organizer_user_id": "oV5", "group_name": "G",
         "run_group_class": "ADVANCED", "driver_count": 0,
         "insurance_policy_ref": "P"},
        make_organizer_headers("oV5"))
    validate_error(resp, ApiErrorId.ERR_INVALID_DRIVER_COUNT)


def test_booking_cannot_be_approved_twice_idempotency(api):
    """PRD §2.9: "State-machine preconditions — the resource stands in a state
    that permits the requested transition, on every state-transition endpoint:
    `ERR_INVALID_STATE` (409)." PRD §3.3: "A successful approval stamps
    `approval_status` `APPROVED`, adds the booking's `driver_count` to the
    block's `seats_reserved` — flipping the block to `FULL` when the seats
    exactly fill — freezes the cancellation-policy thresholds into
    `cancel_policy_snapshot`, and advances the block's `version` by one."

    Design: Corner/state_machines/booking_cannot_be_approved_twice_idempotency
    """
    env = setup_open_day_with_block("2026-09-15")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    booking = make_booking(tid, tdid, rbid, "orgSM2")
    approve_booking(tid, tdid, rbid, booking["id"])
    assert get_block(tid, tdid, rbid)["seats_reserved"] == 1
    # Second approve carries the current block version, so only the state
    # gate (booking already APPROVED) can reject it.
    resp = api.approve_booking(
        tid, tdid, rbid, booking["id"],
        {"expected_rental_block_version": block_version(tid, tdid, rbid)}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_block(tid, tdid, rbid)["seats_reserved"] == 1, \
        "a rejected second approval must not double-count seats"


def test_seats_count_only_approved_bookings(api):
    """PRD §3.2: "Two counters are then derived continuously:
    `seats_reserved`, the sum of `driver_count` across the block's `APPROVED`
    bookings, and `seats_available`, `max_group_size` minus `seats_reserved`,
    floored at zero so it can never report negative."

    Design: Corner/calculations/rental_block_seats_input_set_filtering
    """
    env = setup_open_day_with_block("2026-09-20",
                                    block_overrides={"max_group_size": 10})
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    pending = make_booking(tid, tdid, rbid, "oP", driver_count=2)
    approved = make_booking(tid, tdid, rbid, "oA", driver_count=1)
    cancelled = make_booking(tid, tdid, rbid, "oC", driver_count=3)
    approve_booking(tid, tdid, rbid, approved["id"])
    approve_booking(tid, tdid, rbid, cancelled["id"])
    cancel_resp = api.cancel_booking(
        tid, tdid, rbid, cancelled["id"], {"reason": "CUSTOMER"},
        make_organizer_headers("oC"))
    validate_success(cancel_resp)
    block = get_block(tid, tdid, rbid)
    assert block["seats_reserved"] == 1, \
        "only APPROVED bookings count; PENDING and CANCELLED are excluded"
    assert block["seats_available"] == 9


def test_stale_block_version_on_approve_returns_412(api):
    """PRD §2.6: "Approving a booking requires
    `expected_rental_block_version`, carrying the client's last observed
    `version` of the rental block. If the block's current `version` has
    advanced past it — for example because a prior approval consumed the
    remaining seats and flipped the block to FULL — the request is rejected
    with `ERR_STALE_VERSION` (412)."

    Design: Corner/errors/err_stale_version_triggerable
    """
    env = setup_open_day_with_block("2026-10-01")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    stale_version = env["block"]["version"]
    first = make_booking(tid, tdid, rbid, "oER1a")
    second = make_booking(tid, tdid, rbid, "oER1b")
    resp = api.approve_booking(tid, tdid, rbid, first["id"],
                               {"expected_rental_block_version": stale_version},
                               OPS)
    validate_success(resp)
    # The first approval advanced the block's version; the stale value fails.
    resp = api.approve_booking(tid, tdid, rbid, second["id"],
                               {"expected_rental_block_version": stale_version},
                               OPS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_adjacent_block_interval_allowed(api):
    """PRD §3.2: "Each block carries a `block_index` sequencing it within the
    day and a half-open minute-of-day window — `start_minute` inclusive,
    `end_minute` exclusive — so two blocks may touch at a boundary without
    overlapping."

    Design: Difficulty/resource_temporal_overlap/rental_block_interval_overlap_half_open
    """
    env = setup_open_day_with_block(
        "2026-09-06",
        block_overrides={"block_index": 0, "start_minute": 480,
                         "end_minute": 540})
    resp = api.create_rental_block(
        env["track"]["id"], env["day"]["id"],
        create_rental_block_payload(block_index=1, start_minute=540,
                                    end_minute=600), OPS)
    data = validate_success(resp, 201)
    assert data["start_minute"] == 540 and data["end_minute"] == 600


def test_overlapping_block_interval_rejected(api):
    """PRD §3.2: "An interval that overlaps any other block on the same day is
    rejected with `ERR_BLOCK_OVERLAP` (409), and this temporal check is
    evaluated before the capacity check that follows."

    Design: Difficulty/resource_temporal_overlap/rental_block_interval_overlap_half_open
    """
    env = setup_open_day_with_block(
        "2026-09-06",
        block_overrides={"block_index": 0, "start_minute": 480,
                         "end_minute": 540})
    ok = api.create_rental_block(
        env["track"]["id"], env["day"]["id"],
        create_rental_block_payload(block_index=1, start_minute=540,
                                    end_minute=600), OPS)
    validate_success(ok, 201)
    resp = api.create_rental_block(
        env["track"]["id"], env["day"]["id"],
        create_rental_block_payload(block_index=2, start_minute=539,
                                    end_minute=600), OPS)
    validate_error(resp, ApiErrorId.ERR_BLOCK_OVERLAP)


def test_exact_fill_approval_flips_block_full(api):
    """PRD §3.2: "When an approval pushes `seats_reserved` to exactly
    `max_group_size`, the block flips from `OPEN` to `FULL`, and while a block
    is `FULL` new booking submissions against it are rejected with
    `ERR_BLOCK_FULL` (409)." PRD §3.3: "A successful approval stamps
    `approval_status` `APPROVED`, adds the booking's `driver_count` to the
    block's `seats_reserved` — flipping the block to `FULL` when the seats
    exactly fill — freezes the cancellation-policy thresholds into
    `cancel_policy_snapshot`, and advances the block's `version` by one."

    Design: Difficulty/boundary_precision_check/rental_block_seats_zero_boundary
    """
    env = setup_open_day_with_block("2026-09-03",
                                    block_overrides={"max_group_size": 3})
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    booking = make_booking(tid, tdid, rbid, "orgA", driver_count=3)
    approved = approve_booking(tid, tdid, rbid, booking["id"])
    assert approved["approval_status"] == "APPROVED"
    block = get_block(tid, tdid, rbid)
    assert block["seats_reserved"] == 3
    assert block["seats_available"] == 0
    assert block["status"] == "FULL", "exact fill flips the block to FULL"


def test_approve_beyond_full_block_rejected(api):
    """PRD §3.3: "Only then come the fiscal checks, in this order: seating,
    where a `driver_count` exceeding the block's current `seats_available` is
    rejected with `ERR_BLOCK_FULL` (409); and insurance, where a missing or
    empty `insurance_policy_ref` is rejected with `ERR_INSURANCE_MISSING`
    (422)."

    Design: Difficulty/boundary_precision_check/rental_block_seats_zero_boundary
    """
    env = setup_open_day_with_block("2026-09-03",
                                    block_overrides={"max_group_size": 3})
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    big = make_booking(tid, tdid, rbid, "orgA", driver_count=3)
    small = make_booking(tid, tdid, rbid, "orgB", driver_count=1)
    approve_booking(tid, tdid, rbid, big["id"])
    resp = api.approve_booking(
        tid, tdid, rbid, small["id"],
        {"expected_rental_block_version": block_version(tid, tdid, rbid)}, OPS)
    validate_error(resp, ApiErrorId.ERR_BLOCK_FULL)
    booking = validate_success(api.get_booking(tid, tdid, rbid, small["id"], OPS))
    assert booking["approval_status"] == "PENDING"


def test_seats_fill_to_full_with_invariant(api):
    """PRD §3.2: "Two counters are then derived continuously:
    `seats_reserved`, the sum of `driver_count` across the block's `APPROVED`
    bookings, and `seats_available`, `max_group_size` minus `seats_reserved`,
    floored at zero so it can never report negative. When an approval pushes
    `seats_reserved` to exactly `max_group_size`, the block flips from `OPEN`
    to `FULL`, and while a block is `FULL` new booking submissions against it
    are rejected with `ERR_BLOCK_FULL` (409)."

    Design: Difficulty/compensating_invariant/seats_conservation_across_approve_cancel
    """
    env = setup_open_day_with_block("2026-09-08",
                                    block_overrides={"max_group_size": 4})
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = make_booking(tid, tdid, rbid, "orgA17", driver_count=2)
    second = make_booking(tid, tdid, rbid, "orgB17", driver_count=2)
    approve_booking(tid, tdid, rbid, first["id"])
    mid = get_block(tid, tdid, rbid)
    assert mid["seats_reserved"] == 2 and mid["seats_available"] == 2
    assert_block_seat_invariant(mid)
    approve_booking(tid, tdid, rbid, second["id"])
    full = get_block(tid, tdid, rbid)
    assert full["seats_reserved"] == 4 and full["seats_available"] == 0
    assert full["status"] == "FULL"
    assert_block_seat_invariant(full)


def test_seats_restore_to_open_after_cancels(api):
    """PRD §3.9: "Cancellation unwinds everything the booking held:
    `approval_status` becomes `CANCELLED`; the block's `seats_reserved` drops
    by the booking's `driver_count` and the block's status is recomputed, so a
    `FULL` block with freed seats returns to `OPEN`". PRD §3.2: "When a later
    cancellation or rejection brings `seats_reserved` back below
    `max_group_size`, the block returns from `FULL` to `OPEN`."

    Design: Difficulty/compensating_invariant/seats_conservation_across_approve_cancel
    """
    env = setup_open_day_with_block("2026-09-08",
                                    block_overrides={"max_group_size": 4})
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = make_booking(tid, tdid, rbid, "orgA17", driver_count=2)
    second = make_booking(tid, tdid, rbid, "orgB17", driver_count=2)
    approve_booking(tid, tdid, rbid, first["id"])
    approve_booking(tid, tdid, rbid, second["id"])
    assert get_block(tid, tdid, rbid)["status"] == "FULL"
    validate_success(api.cancel_booking(
        tid, tdid, rbid, first["id"], {"reason": "CUSTOMER"},
        make_organizer_headers("orgA17")))
    validate_success(api.cancel_booking(
        tid, tdid, rbid, second["id"], {"reason": "CUSTOMER"},
        make_organizer_headers("orgB17")))
    block = get_block(tid, tdid, rbid)
    assert block["seats_reserved"] == 0, "two compensate cycles leave zero drift"
    assert block["seats_available"] == 4
    assert block["status"] == "OPEN"
    assert_block_seat_invariant(block)
