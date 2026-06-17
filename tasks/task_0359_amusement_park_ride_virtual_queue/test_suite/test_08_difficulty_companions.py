"""Second tests for each difficulty-index instance (the queue-A >=2-per-instance
requirement). Each test exercises the complementary branch, boundary success side,
or an intermediate hop of the same rule its sibling asserts.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    create_day_ticket, admit, create_plan, book_vq, confirm,
    setup_park_ride_window, setup_booked_reservation, setup_held_reservation,
    setup_loaded_ride_for_peak_price, setup_party_with_member, setup_admitted_to_peak,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


# --- dual_variant_calc ---

def test_lightning_lane_open_branch_no_surge_on_loaded_plan(api):
    """PRD §3.6: "when the posture is `OPEN` the surged figure is simply the base
    with no multiplier ... for a `MULTI_PASS` plan the surged figure is rounded
    half-up to whole cents directly."

    The OPEN branch of the same plan/surge: unloaded ride keeps charged_cents at the
    flat base 2500 despite surge 3.0.

    Design: Difficulty/dual_variant_calc/lightning_lane_price_peak_vs_open_on_purchase
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    plan = create_plan(park["id"], tier="MULTI_PASS", price_cents=2500,
                       max_concurrent_holds=3, surge_multiplier=3.0)
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": guest["id"], "ride_id": ride["id"], "plan_id": plan["id"]},
        make_guest_headers(guest["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["charged_cents"] == 2500, f"OPEN posture must be flat 2500, got {data['charged_cents']}"


def test_posted_wait_operating_branch_positive(api):
    """PRD §3.8: "When the ride is `OPEN`, the estimate models how long it takes to
    clear the standby demand: standby demand is the ride's `booked_slot_count` plus
    a baseline of 20 notional standby guests, and the posted wait is that demand
    divided by the ride's `hourly_throughput`, multiplied by 60 to convert hours to
    minutes, then rounded up to the next whole minute."

    The OPEN (operating) half of the variant: throughput 100, one booking ->
    ceil((1+20)/100*60) = 13 (a positive wait, not the DOWN short-circuit 0).

    Design: Difficulty/dual_variant_calc/posted_wait_operating_vs_down_on_ride
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    book_vq(ride["id"], guest["id"], window["id"], window["version"])
    data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert data["operational_status"] == "OPEN"
    assert data["posted_wait_minutes"] == 13, \
        f"OPEN ride must post a positive estimate 13, got {data['posted_wait_minutes']}"


# --- combinatorial_formula ---

def test_single_pass_cap_does_not_bind_when_surged_below_cap(api):
    """PRD §3.6: "for a `SINGLE_PASS` plan the charge is the lesser of the surged
    figure and the single-pass cap of 9900 cents, after which it is rounded half-up
    to whole cents".

    The non-binding branch of the min(): SINGLE_PASS at PEAK base 3000 x surge 2.0
    = 6000 < 9900, so min picks the surged figure 6000.

    Design: Difficulty/combinatorial_formula/lightning_lane_price_nested_min_and_branches
    """
    park, ride, window, buyer, plan = setup_loaded_ride_for_peak_price(
        price_cents=3000, surge_multiplier=2.0, tier="SINGLE_PASS",
    )
    ga = create_guest(park["id"], full_name="GAbuyer", height_cm=170)
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": ga["id"], "ride_id": ride["id"], "plan_id": plan["id"]},
        make_guest_headers(ga["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["charged_cents"] == 6000, \
        f"surged 6000 < cap 9900 means min picks 6000, got {data['charged_cents']}"


def test_slot_capacity_floor_drops_fractional_product(api):
    """PRD §3.1: "take the window's length in whole minutes ... multiply the ride's
    `hourly_throughput` by that length divided by 60, multiply again by the
    virtual-queue supply fraction of 0.40 ... and floor the result to a whole number
    of slots."

    A 45-min window on throughput 100 -> floor(100 * (45/60) * 0.40) = floor(30.0) = 30.

    Design: Difficulty/combinatorial_formula/slot_capacity_minute_truncation_then_floor_order
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100, name="RT")
    resp = api.create_return_window(
        ride["id"],
        {"window_start_utc": "2026-06-15T10:00:00.000Z", "window_end_utc": "2026-06-15T10:45:00.000Z"},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["slot_capacity"] == 30, f"expected 30 slots, got {data['slot_capacity']}"


# --- non_linear_state_machine ---

def test_reservation_enters_redistributed_on_ride_down(api):
    """PRD §3.7: "Every reservation on the ride in `BOOKED` status is redistributed:
    it moves `BOOKED → REDISTRIBUTED`, its `redistributed_from_window_id` is set to
    the window it currently occupies".

    The first leg of the cycle: declaring DOWN moves a BOOKED reservation to
    REDISTRIBUTED with redistributed_from_window_id recorded.

    Design: Difficulty/non_linear_state_machine/reservation_cycle_booked_redistributed_booked
    """
    park, ride, window, guest, booked = setup_booked_reservation(hourly_throughput=100)
    validate_success(api.declare_down(ride["id"], OPERATOR))
    data = validate_success(api.get_reservation(booked["id"], ADMIN))
    assert data["reservation_status"] == "REDISTRIBUTED", \
        f"booked reservation must become REDISTRIBUTED on ride-down, got {data['reservation_status']}"
    assert data["redistributed_from_window_id"] == window["id"], \
        f"redistributed_from_window_id must record the original window, got {data['redistributed_from_window_id']}"


def test_window_enters_exhausted_when_filled(api):
    """PRD §3.4: "It tips to `EXHAUSTED` the instant a held reservation drives
    `reserved_count` to `slot_capacity` or above".

    The OPEN -> EXHAUSTED leg of the cycle: filling a capacity-2 window with two
    HELD reservations drives it to EXHAUSTED.

    Design: Difficulty/non_linear_state_machine/return_window_cycle_open_exhausted_open
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    book_vq(ride["id"], gb["id"], window["id"], res_a["version"])
    data = validate_success(api.get_return_window(window["id"], ADMIN))
    assert data["window_status"] == "EXHAUSTED", \
        f"filled window must be EXHAUSTED, got {data['window_status']}"
    assert data["reserved_count"] == 2, f"expected reserved_count 2, got {data['reserved_count']}"


# --- transitive_cascade ---

def test_advance_windows_reports_forfeited_reservation_id(api):
    """PRD §3.4: "The advance returns the count of expired windows and the list of
    forfeited reservation identifiers."

    The advance-windows response surfaces the forfeited reservation id as the
    cascade's observable output.

    Design: Difficulty/transitive_cascade/window_expiry_forfeits_reservation_then_recomputes_wait
    """
    park = create_park()
    set_clock(park["id"], "2026-06-15T10:30:00.000Z")
    ride = create_ride(park["id"], hourly_throughput=100)
    window = create_window(ride["id"], "2026-06-15T10:00:00.000Z", "2026-06-15T11:00:00.000Z")
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    confirm(res["id"], guest["id"])
    set_clock(park["id"], "2026-06-15T11:05:00.000Z")
    data = validate_success(api.advance_windows(park["id"], ADMIN))
    assert res["id"] in data["forfeited_reservation_ids"], \
        f"forfeited reservation id must be reported, got {data['forfeited_reservation_ids']}"
    assert data["expired_window_count"] == 1, \
        f"expected expired_window_count 1, got {data['expired_window_count']}"


def test_party_disband_removes_leader_membership_too(api):
    """PRD §3.5: "disbanding moves the party `FORMING → DISBANDED`, sets every
    `LINKED` membership to `REMOVED`, and clears the `party_id` of each affected
    guest back to null."
    PRD §3.5: "On creation the party is `FORMING`, its leader is auto-linked as a
    `PartyMembership` in `LINKED` status".

    "Every LINKED membership" includes the leader's auto-linked membership: after
    disband the leader's own guest party_id is cleared. (Sibling asserts the added
    member; this asserts the leader-membership leg.)

    Design: Difficulty/transitive_cascade/party_disband_removes_memberships_then_clears_guest_party_id
    """
    park, ride, window, leader, member, party = setup_party_with_member(with_window=False)
    # Confirm leader is linked while FORMING.
    before = validate_success(api.get_guest(leader["id"], ADMIN))
    assert before["party_id"] == party["id"]
    validate_success(api.disband(party["id"], make_guest_headers(leader["id"])))
    after = validate_success(api.get_guest(leader["id"], ADMIN))
    assert after["party_id"] is None, \
        f"leader's party_id must clear on disband, got {after['party_id']}"


# --- priority_pair_validation_conflict ---

def test_redeem_invalid_state_alone_fires_when_height_ok(api):
    """PRD §3.4: "an attempt against a reservation not in `BOOKED` status, or a ride
    not `OPEN`, is rejected with `ERR_INVALID_STATE`."

    Isolating the priority-5 state check (the winner of the pair): a HELD
    reservation whose guest meets the height requirement still fails redeem on state.

    Design: Difficulty/priority_pair_validation_conflict/redeem_invalid_state_beats_height_on_reservation
    """
    # Tall guest (height OK, 170 >= 120); reservation left HELD; clock inside window.
    park, ride, window, guest, res = setup_held_reservation(
        hourly_throughput=100, clock="2026-06-15T10:15:00.000Z", queue_type="SINGLE_RIDER",
        ride_overrides={"min_height_cm": 120},
    )
    resp = api.redeem_reservation(res["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_window_exhausted_alone_fires_for_tall_guest(api):
    """PRD §3.3: "for a `VIRTUAL_QUEUE` booking, the window must have room: its
    `reserved_count` must be strictly below its `slot_capacity`, or the request is
    rejected with `ERR_WINDOW_EXHAUSTED`."

    Isolating the priority-13 fiscal check (the loser of the pair): a tall guest
    (height OK) booking the same exhausted window sees the exhaustion failure alone.

    Design: Difficulty/priority_pair_validation_conflict/book_height_beats_window_exhausted_on_reservation
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5, ride_overrides={"min_height_cm": 120})
    t1 = create_guest(park["id"], full_name="T1", height_cm=170)
    t2 = create_guest(park["id"], full_name="T2", height_cm=170)
    t3 = create_guest(park["id"], full_name="T3", height_cm=170)
    res1 = book_vq(ride["id"], t1["id"], window["id"], window["version"])
    res2 = book_vq(ride["id"], t2["id"], window["id"], res1["version"])
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": t3["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res2["version"]},
        make_guest_headers(t3["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_EXHAUSTED)


# --- boundary_precision_check ---

def test_window_capacity_boundary_admits_last_slot(api):
    """PRD §3.3: "for a `VIRTUAL_QUEUE` booking, the window must have room: its
    `reserved_count` must be strictly below its `slot_capacity`, or the request is
    rejected with `ERR_WINDOW_EXHAUSTED`."

    The success side of the boundary: the slot_capacity-th booking (the 2nd, with
    reserved_count 1 < 2) succeeds, bringing reserved_count to exactly 2.

    Design: Difficulty/boundary_precision_check/window_capacity_boundary_at_slot_capacity
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    res_b = validate_success(
        api.create_reservation(
            {"ride_id": ride["id"], "guest_id": gb["id"], "return_window_id": window["id"],
             "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res_a["version"]},
            make_guest_headers(gb["id"]),
        ),
        expected_status=201,
    )
    assert res_b["reservation_status"] == "HELD"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 2, f"the capacity-th slot must fill to 2, got {win['reserved_count']}"


def test_park_admission_boundary_admits_last_guest(api):
    """PRD §3.2: "Admission may proceed only when the ticket is `ISSUED`, its
    `ticket_date` equals the park's `operating_date`, and the park is not full
    (`admitted_count` strictly less than `gate_capacity`)".
    PRD §2.8: "it is `FULL` once `admitted_count` reaches `gate_capacity` or more."

    The success side of the boundary: with gate_capacity 2 the second admission
    (admitted_count 1 < 2) succeeds, bringing the park to admitted_count 2, FULL.

    Design: Difficulty/boundary_precision_check/park_admission_boundary_at_gate_capacity
    """
    park = create_park(gate_capacity=2)
    tickets = []
    for i in range(2):
        g = create_guest(park["id"], full_name=f"G{i}")
        t = create_day_ticket(park["id"], g["id"])
        tickets.append(t["id"])
    admit(park["id"], tickets[0])
    data = validate_success(api.admit(park["id"], {"ticket_id": tickets[1]}, ADMIN), expected_status=201)
    assert data["admission_status"] == "ADMITTED"
    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["admitted_count"] == 2, f"expected admitted_count 2, got {park_data['admitted_count']}"
    assert park_data["day_phase"] == "FULL", f"expected FULL, got {park_data['day_phase']}"


# --- cross_entity_state_dependency ---

def test_confirm_succeeds_when_ride_open(api):
    """PRD §3.3: "Confirmation is allowed only when the reservation is `HELD`, the
    parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the owning
    window is `OPEN` ... A successful confirm moves the reservation `HELD → BOOKED`".

    The positive control of the cross-entity precondition: with the ride OPEN the
    confirm succeeds and the reservation becomes BOOKED.

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_when_ride_down
    """
    park, ride, window, guest, res = setup_held_reservation(hourly_throughput=100)
    data = validate_success(api.confirm_reservation(res["id"], make_guest_headers(guest["id"])))
    assert data["reservation_status"] == "BOOKED", \
        f"confirm on an OPEN ride must yield BOOKED, got {data['reservation_status']}"


def test_multi_pass_holder_can_book_at_peak(api):
    """PRD §3.3: "when the park's `day_phase` is `PEAK`, a new virtual-queue
    reservation is allowed only if the acting guest holds an `ACTIVE` Lightning Lane
    purchase of the `MULTI_PASS` tier in this park".

    The positive branch of the peak gate: a guest holding an ACTIVE MULTI_PASS hold
    books successfully at PEAK.

    Design: Difficulty/cross_entity_state_dependency/vq_booking_blocked_when_park_phase_peak
    """
    park, ride, window, extra = setup_admitted_to_peak(gate_capacity=4, peak_threshold_pct=0.5, admit_count=2)
    plan = create_plan(park["id"], tier="MULTI_PASS", price_cents=1500, max_concurrent_holds=3, surge_multiplier=1.0)
    validate_success(
        api.create_lightning_lane_purchase(
            {"park_id": park["id"], "guest_id": extra["id"], "ride_id": ride["id"], "plan_id": plan["id"]},
            make_guest_headers(extra["id"]),
        ),
        expected_status=201,
    )
    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["day_phase"] == "PEAK"
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": extra["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(extra["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["reservation_status"] == "HELD", \
        f"MULTI_PASS holder must book at PEAK, got {data['reservation_status']}"


# --- resource_temporal_overlap ---

def test_aggregate_window_admits_below_capacity_occupation(api):
    """PRD §3.3: "for a `VIRTUAL_QUEUE` booking, the window must have room: its
    `reserved_count` must be strictly below its `slot_capacity`, or the request is
    rejected with `ERR_WINDOW_EXHAUSTED`."

    The below-capacity side of the aggregate interval: the first occupation on a
    capacity-2 window (reserved_count 0 < 2) is admitted.

    Design: Difficulty/resource_temporal_overlap/window_aggregate_capacity_overlap_on_return_window
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5, clock="2026-06-15T09:30:00.000Z")
    guest = create_guest(park["id"], full_name="GA")
    res = validate_success(
        api.create_reservation(
            {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
             "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
            make_guest_headers(guest["id"]),
        ),
        expected_status=201,
    )
    assert res["reservation_status"] == "HELD"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 1, f"expected reserved_count 1, got {win['reserved_count']}"
    assert win["window_status"] == "OPEN", f"below-capacity window must stay OPEN, got {win['window_status']}"


def test_redeem_at_inclusive_start_boundary_succeeds(api):
    """PRD §3.4: "the park's `current_utc` falls within the window: at or after
    `window_start_utc` and strictly before `window_end_utc`."

    The inclusive-start side of the half-open interval: redeem at exactly
    window_start_utc (10:00:00, which is inside [10:00, 11:00)) succeeds.

    Design: Difficulty/resource_temporal_overlap/redeem_exclusive_end_boundary_on_reservation
    """
    park, ride, window, guest, booked = setup_booked_reservation(clock="2026-06-15T09:30:00.000Z")
    set_clock(park["id"], "2026-06-15T10:00:00.000Z")
    data = validate_success(api.redeem_reservation(booked["id"], OPERATOR))
    assert data["reservation_status"] == "REDEEMED", \
        f"redeem at inclusive start must succeed, got {data['reservation_status']}"


# --- compensating_invariant ---

def test_window_slot_debited_before_cancel(api):
    """PRD §3.3: "When a `VIRTUAL_QUEUE` reservation is created and passes every
    gate, the system increments the target window's `reserved_count` by one and the
    ride's `booked_slot_count` by one".

    The debit half of the conserved-quantity round-trip: after the book (before any
    cancel) reserved_count is 1 and booked_slot_count is 1.

    Design: Difficulty/compensating_invariant/window_slot_conserved_under_book_then_cancel
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    guest = create_guest(park["id"], full_name="GA")
    book_vq(ride["id"], guest["id"], window["id"], window["version"])
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 1, f"book must debit reserved_count to 1, got {win['reserved_count']}"
    ride_data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert ride_data["booked_slot_count"] == 1, \
        f"book must debit booked_slot_count to 1, got {ride_data['booked_slot_count']}"


def test_admission_count_incremented_before_exit(api):
    """PRD §3.2: "A successful admission moves the ticket from `ISSUED` to
    `ADMITTED`, increases the park's `admitted_count` by one, recomputes the park's
    `day_phase` from the new occupancy".
    PRD §2.8: "it is `FULL` once `admitted_count` reaches `gate_capacity` or more."

    The increment half of the conserved-quantity round-trip: after the admit (before
    any exit) admitted_count is 1 and day_phase is FULL (gate 1).

    Design: Difficulty/compensating_invariant/park_admission_count_conserved_under_admit_then_exit
    """
    park = create_park(gate_capacity=1)
    guest = create_guest(park["id"], full_name="GA")
    ticket = create_day_ticket(park["id"], guest["id"])
    admit(park["id"], ticket["id"])
    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["admitted_count"] == 1, \
        f"admit must increment admitted_count to 1, got {park_data['admitted_count']}"
    assert park_data["day_phase"] == "FULL", f"gate-1 park must be FULL, got {park_data['day_phase']}"
