"""Booking gate tests: height, accessibility, temporal, peak gate, VQ/hold
ceilings, cross-entity state dependencies, and priority-pair resolutions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    create_day_ticket, admit, create_plan, book_vq, confirm,
    setup_park_ride_window, setup_held_reservation, setup_admitted_to_peak,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
    api_client,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


# ----------------------------------------------------------------------
# Single-violation validations
# ----------------------------------------------------------------------

def test_height_requirement_blocks_short_guest_booking(api):
    """PRD §3.3: "The guest must clear the height requirement: the guest's
    `height_cm` must be at least the ride's `min_height_cm`, or the request is
    rejected with `ERR_HEIGHT_REQUIREMENT_NOT_MET`."

    Design: Corner/validations/height_violation_on_create_reservation
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100, ride_overrides={"min_height_cm": 120})
    guest = create_guest(park["id"], full_name="GS", height_cm=110)
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HEIGHT_REQUIREMENT_NOT_MET)


def test_accessibility_blocks_wheelchair_guest_on_transfer_ride(api):
    """PRD §3.3: "it is forbidden for a guest whose `uses_wheelchair` is true to
    book a ride whose `wheelchair_transfer_required` is true — that combination, and
    only that combination, is rejected with `ERR_ACCESSIBILITY_BLOCKED`."

    Design: Corner/validations/accessibility_blocked_wheelchair_transfer_ride
    """
    park, ride, window = setup_park_ride_window(
        hourly_throughput=100, ride_overrides={"wheelchair_transfer_required": True},
    )
    guest = create_guest(park["id"], full_name="GW", uses_wheelchair=True)
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_BLOCKED)


def test_book_elapsed_window_rejected(api):
    """PRD §3.3: "The chosen window must not already have elapsed: its
    `window_end_utc` must be strictly after the park's `current_utc`, or the booking
    is rejected with `ERR_WINDOW_NOT_REDEEMABLE`."

    Window 10:00-11:00, clock advanced to 11:30 (elapsed, not yet swept).

    Design: Corner/validations/book_elapsed_window_returns_window_not_redeemable
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    window = create_window(ride["id"], "2026-06-15T10:00:00.000Z", "2026-06-15T11:00:00.000Z")
    guest = create_guest(park["id"], full_name="G1")
    set_clock(park["id"], "2026-06-15T11:30:00.000Z")
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_REDEEMABLE)


def test_vq_ceiling_blocks_third_reservation(api):
    """PRD §3.3: "counting that guest's `VIRTUAL_QUEUE` reservations in `HELD` or
    `BOOKED` status, the count must be strictly below the park-wide limit of 2
    active virtual-queue reservations per guest before another is added; at or above
    the limit the request is rejected with `ERR_VQ_LIMIT_REACHED`."

    Design: Corner/calculations/vq_per_guest_limit_blocks_third_reservation
    """
    park = create_park()
    set_clock(park["id"], "2026-06-15T09:00:00.000Z")
    guest = create_guest(park["id"], full_name="G1")
    windows = []
    for name in ("RA", "RB", "RC"):
        ride = create_ride(park["id"], hourly_throughput=100, name=name)
        win = create_window(ride["id"])
        windows.append((ride, win))
    (ride_a, wa), (ride_b, wb), (ride_c, wc) = windows
    book_vq(ride_a["id"], guest["id"], wa["id"], wa["version"])
    book_vq(ride_b["id"], guest["id"], wb["id"], wb["version"])
    resp = api.create_reservation(
        {"ride_id": ride_c["id"], "guest_id": guest["id"], "return_window_id": wc["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": wc["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VQ_LIMIT_REACHED)


def test_hold_ceiling_blocks_second_single_pass_hold(api):
    """PRD §3.6: "The guest must also be under the plan's hold ceiling: counting
    that guest's `ACTIVE` Lightning Lane purchases, the count must be strictly below
    the plan's `max_concurrent_holds` before another is bought; at or above the
    ceiling the purchase is rejected with `ERR_HOLD_LIMIT_REACHED`."

    SINGLE_PASS plan max_concurrent_holds 1; second purchase blocked.

    Design: Corner/validations/ll_hold_limit_blocks_second_single_pass_hold
    """
    park = create_park()
    ride_a = create_ride(park["id"], hourly_throughput=100, name="RA")
    ride_b = create_ride(park["id"], hourly_throughput=100, name="RB")
    guest = create_guest(park["id"], full_name="G1")
    plan = create_plan(park["id"], tier="SINGLE_PASS", price_cents=5000,
                       max_concurrent_holds=1, surge_multiplier=1.0)
    validate_success(
        api.create_lightning_lane_purchase(
            {"park_id": park["id"], "guest_id": guest["id"], "ride_id": ride_a["id"], "plan_id": plan["id"]},
            make_guest_headers(guest["id"]),
        ),
        expected_status=201,
    )
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": guest["id"], "ride_id": ride_b["id"], "plan_id": plan["id"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOLD_LIMIT_REACHED)


# ----------------------------------------------------------------------
# Cross-entity state dependency
# ----------------------------------------------------------------------

def test_confirm_blocked_when_ride_down(api):
    """PRD §3.3: "Confirmation is allowed only when the reservation is `HELD`, the
    parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the owning
    window is `OPEN`; otherwise it is rejected with `ERR_INVALID_STATE`."

    A HELD reservation cannot confirm while the parent ride is DOWN.

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_when_ride_down
    """
    park, ride, window, guest, res = setup_held_reservation(hourly_throughput=100)
    validate_success(api.declare_down(ride["id"], OPERATOR))
    resp = api.confirm_reservation(res["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    reservation = validate_success(api.get_reservation(res["id"], ADMIN))
    assert reservation["reservation_status"] == "HELD", \
        f"blocked confirm must leave reservation HELD, got {reservation['reservation_status']}"


def test_vq_booking_blocked_when_park_peak(api):
    """PRD §3.3: "The peak gate must pass: when the park's `day_phase` is `PEAK`, a
    new virtual-queue reservation is allowed only if the acting guest holds an
    `ACTIVE` Lightning Lane purchase of the `MULTI_PASS` tier in this park; absent
    that, the booking is rejected with `ERR_PEAK_GATE_BLOCKED`."

    gate_capacity 4, peak_threshold_pct 0.5; admit 2 -> 2/4 = 0.5 >= 0.5 -> PEAK.

    Design: Difficulty/cross_entity_state_dependency/vq_booking_blocked_when_park_phase_peak
    """
    park, ride, window, extra = setup_admitted_to_peak(gate_capacity=4, peak_threshold_pct=0.5, admit_count=2)
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": extra["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(extra["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PEAK_GATE_BLOCKED)
    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["day_phase"] == "PEAK", f"park must be PEAK, got {park_data['day_phase']}"


def test_open_below_threshold_allows_non_premium_booking(api):
    """PRD §2.8: "The phase is `OPEN` while occupancy — `admitted_count` divided by
    `gate_capacity` — is strictly below `peak_threshold_pct`".
    PRD §3.3: "The peak gate must pass: when the park's `day_phase` is `PEAK`, a new
    virtual-queue reservation is allowed only if the acting guest holds an `ACTIVE`
    Lightning Lane purchase of the `MULTI_PASS` tier in this park".

    gate_capacity 4, peak_threshold_pct 0.85; admit 1 -> 1/4 = 0.25 < 0.85 -> OPEN,
    so a non-premium guest books successfully.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_peak_phase_boundary_allows_open_below_threshold
    """
    park, ride, window, extra = setup_admitted_to_peak(gate_capacity=4, peak_threshold_pct=0.85, admit_count=1)
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": extra["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(extra["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["reservation_status"] == "HELD"
    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["day_phase"] == "OPEN", f"park must be OPEN, got {park_data['day_phase']}"


# ----------------------------------------------------------------------
# Priority-pair resolutions
# ----------------------------------------------------------------------

def test_book_height_beats_window_exhausted(api):
    """PRD §2.11: "A request must clear an earlier check before a later one is even
    evaluated, so a guest who is both too short and trying to book an exhausted
    window sees the height failure, not the exhaustion failure."

    Ride min_height 120, capacity-2 window filled to EXHAUSTED by two tall guests;
    a short guest's booking fails height (priority 7), not exhaustion (priority 13).

    Design: Difficulty/priority_pair_validation_conflict/book_height_beats_window_exhausted_on_reservation
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5, ride_overrides={"min_height_cm": 120})
    t1 = create_guest(park["id"], full_name="T1", height_cm=170)
    t2 = create_guest(park["id"], full_name="T2", height_cm=170)
    short = create_guest(park["id"], full_name="GS", height_cm=110)
    res1 = book_vq(ride["id"], t1["id"], window["id"], window["version"])
    res2 = book_vq(ride["id"], t2["id"], window["id"], res1["version"])
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": short["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res2["version"]},
        make_guest_headers(short["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HEIGHT_REQUIREMENT_NOT_MET)


def test_existence_beats_state_on_missing_reservation(api):
    """PRD §2.11: "third, existence of all referenced resources, left to right
    (`ERR_NOT_FOUND`) ... fifth, that the target resource is in a valid state for
    the requested transition (`ERR_INVALID_STATE`)".
    PRD §2.10: "the first missing identifier short-circuits the request with
    `ERR_NOT_FOUND`."

    Confirming a non-existent reservation id -> ERR_NOT_FOUND before any state check.

    Design: Corner/validations/priority_existence_beats_state_on_missing_ride
    """
    park = create_park()
    guest = create_guest(park["id"], full_name="G1")
    resp = api.confirm_reservation(
        "00000000-0000-4000-8000-000000000999", make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
