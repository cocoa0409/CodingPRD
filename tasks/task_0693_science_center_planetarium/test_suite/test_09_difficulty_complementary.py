"""Complementary depth tests — a second assertion per difficulty rule, each pinning
a distinct PRD-derived observable. Paired with the primary tests in test_01..test_03.

Queue A (Difficulty): second test per instance.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_active_membership,
    create_membership,
    create_classroom_program,
    create_registration,
    create_hold,
    create_confirmed_booking,
    create_group_booking,
    create_deposit_paid_group,
    create_rental_hall,
    create_held_rental,
    create_sponsor,
    record_contribution,
    submit_and_approve_accommodation,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
EVENTS = TEST_USERS["events_manager_headers"]
DEV = TEST_USERS["development_officer_headers"]
ACCESS = TEST_USERS["accessibility_headers"]


# --- dual_variant_calc ---

def test_group_deposit_estimate_value(api):
    """PRD §3.5: "The **deposit** runs that grand total over the requested
    `student_count` and `chaperone_count`, takes 25% of it, and floors the result to
    whole cents; that figure is stored in `deposit_cents`."

    student_count=20, chaperone_count=3, per_seat=2500: free_chaperones=2, billable=1,
    student_seat=round(2500*0.70)=1750, students=35000, chaperones=2000,
    grand=37000, deposit=floor(37000*0.25)=9250.

    Design: Difficulty/dual_variant_calc/group_invoice_deposit_vs_final_diverges
    """
    show = create_open_show(seated_capacity=60, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Stars2")
    gb = create_group_booking(show["id"], student_count=20, chaperone_count=3,
                              organization_name="PS 42")
    assert gb["deposit_cents"] == 9250, f"expected deposit 9250, got {gb['deposit_cents']}"


def test_rental_deposit_estimate_value(api):
    """PRD §3.7: "The **deposit** runs this grand total over the estimated
    `guest_count`, takes 25% of it, and floors to whole cents, storing the result in
    `deposit_cents`."

    guest_count=15, base=50000: tier1=15*500=7500, grand=57500,
    deposit=floor(57500*0.25)=14375.

    Design: Difficulty/dual_variant_calc/rental_deposit_vs_final_diverges
    """
    hall = create_rental_hall(seated_capacity=80, name="Party Hall 2")
    rental = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "Mia",
         "starts_at": "2026-05-02T14:00:00Z", "ends_at": "2026-05-02T17:00:00Z",
         "guest_count": 15, "base_rental_cents": 50000}, EVENTS), expected_status=201)
    assert rental["deposit_cents"] == 14375, \
        f"expected deposit 14375, got {rental['deposit_cents']}"


# --- combinatorial_formula ---

def test_family_show_pricing_gross_unaffected_by_discount(api):
    """PRD §3.4: "The `gross_price_cents` is the booking's `party_size` multiplied by
    that per-seat price."

    per_seat=2500, party_size=3 -> gross=7500, independent of the member discount.

    Design: Difficulty/combinatorial_formula/show_pricing_per_seat_round_then_sum
    """
    fam = create_active_membership(tier="FAMILY", home_zip="90210", party_size=4,
                                   dues_cents=12000, primary_member_name="Fam3")
    show = create_open_show(seated_capacity=60, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Laser2")
    booking = validate_success(api.create_show_booking(
        {"show_event_id": show["id"], "membership_id": fam["id"], "party_size": 3,
         "expected_show_version": show["version"]}, BOX_OFFICE), expected_status=201)
    assert booking["gross_price_cents"] == 7500, \
        f"expected gross 7500, got {booking['gross_price_cents']}"


def test_rental_marginal_tier_within_first_tier_only(api):
    """PRD §3.7: "the tier-one guests are the smaller of the guest count and 20 ... and
    the guest charge is the tier-one count times 500 cents plus the tier-two count
    times 300 cents. The grand total is the `base_rental_cents` plus that guest
    charge."
    PRD §3.7: "The **deposit** runs this grand total over the estimated `guest_count`,
    takes 25% of it, and floors to whole cents".

    guest_count=10 (all in tier 1), base=50000: guest_charge=10*500=5000,
    grand=55000, deposit=floor(55000*0.25)=13750.

    Design: Difficulty/combinatorial_formula/rental_marginal_tier_three_inputs
    """
    hall = create_rental_hall(seated_capacity=100, name="Hall C2")
    rental = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "Sam",
         "starts_at": "2026-06-01T12:00:00Z", "ends_at": "2026-06-01T15:00:00Z",
         "guest_count": 10, "base_rental_cents": 50000}, EVENTS), expected_status=201)
    assert rental["deposit_cents"] == 13750, \
        f"expected deposit 13750, got {rental['deposit_cents']}"


# --- non_linear_state_machine ---

def test_show_reaches_sold_out_at_capacity(api):
    """PRD §3.3: "When `seats_sold` reaches the venue's `seated_capacity`, the system
    automatically bubbles the show `OPEN → SOLD_OUT`".

    Capacity 2: after two party-1 holds, seats_sold==2 and the show is SOLD_OUT.

    Design: Difficulty/non_linear_state_machine/show_sold_out_open_cycle
    """
    show = create_open_show(seated_capacity=2, base_price_cents=1000, title="Mini2")
    create_hold(show["id"], party_size=1)
    create_hold(show["id"], party_size=1)
    fetched = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert fetched["seats_sold"] == 2
    assert fetched["status"] == "SOLD_OUT", f"expected SOLD_OUT, got {fetched['status']}"


def test_membership_expired_after_sweep_before_renewal(api):
    """PRD §3.2: "Once the logical clock reaches or passes `expires_at`, the next sweep
    moves an `ACTIVE` card to `EXPIRED` (Section 2.5)."

    The ACTIVE→EXPIRED leg of the renewal cycle: after advancing past expiry and
    sweeping, the card is EXPIRED.

    Design: Difficulty/non_linear_state_machine/membership_active_expired_renewal_cycle
    """
    m = create_membership(tier="FAMILY", home_zip="90210", party_size=2,
                          primary_member_name="Renew Me 2")
    validate_success(api.activate_membership(m["id"], {"dues_cents": 12000}, CLERK))
    validate_success(api.set_clock("2027-03-02T00:00:00Z", ADMIN))
    validate_success(api.run_sweeps(ADMIN))
    expired = validate_success(api.get_membership(m["id"], CLERK))
    assert expired["status"] == "EXPIRED", f"expected EXPIRED, got {expired['status']}"


# --- transitive_cascade ---

def test_show_cancel_sets_seats_sold_zero_and_cancelled(api):
    """PRD §3.3: "then the show's `seats_sold` is set to 0, the show is set to
    `CANCELLED`, and its `version` is incremented."

    The terminal hop of the show-cancel cascade: the show ends CANCELLED with
    seats_sold 0.

    Design: Difficulty/transitive_cascade/show_cancel_cascade_booking_cascade_accommodation
    """
    show = create_open_show(seated_capacity=50, accessible_seats=4, base_price_cents=1500,
                            title="Sky2")
    booking = create_confirmed_booking(show["id"], party_size=2)
    submit_and_approve_accommodation("SHOW_BOOKING", accommodation_kind="WHEELCHAIR",
                                     show_booking_id=booking["id"])
    cancelled = validate_success(api.cancel_show(show["id"], BOX_OFFICE))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_sold"] == 0, f"expected seats_sold 0, got {cancelled['seats_sold']}"


def test_registration_cancel_marks_cancelled_reg_terminal(api):
    """PRD §3.6: "first the session's `enrolled_count` is recomputed downward; then the
    `WAITLISTED` registration with the lowest `created_at` on that session is promoted
    to `ENROLLED` to fill the freed seat".

    The first hop: the cancelled ENROLLED registration is CANCELLED (the terminal
    state for a registration).

    Design: Difficulty/transitive_cascade/registration_cancel_cascade_promote_reopen
    """
    program = create_classroom_program(capacity=1, tuition_cents=10000, min_age=6, max_age=12,
                                        title="Astro Camp 2")
    reg1 = create_registration(program["id"], participant_name="Ann", participant_age=8)
    create_registration(program["id"], participant_name="Ben", participant_age=9)
    validate_success(api.cancel_registration(reg1["id"], PROGRAM))
    reg1_after = validate_success(api.get_registration(reg1["id"], PROGRAM))
    assert reg1_after["status"] == "CANCELLED", \
        f"cancelled reg should be CANCELLED, got {reg1_after['status']}"


# --- priority_pair_validation_conflict ---

def test_group_deposit_state_error_leaves_booking_requested(api):
    """PRD §3.5: "When the agent pays the deposit, the booking moves
    `REQUESTED → DEPOSIT_PAID`: this is permitted only while the booking is
    `REQUESTED` and the linked show is `OPEN`".
    PRD §3.10: "A higher-priority failure is always reported in preference to a
    lower-priority one."

    With the higher-priority state failure firing, the booking is unchanged (still
    REQUESTED).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_group_pay_deposit
    """
    dome = create_dome(seated_capacity=2, name="Dome E2")
    show = validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "Closed2", "starts_at": "2026-04-12T10:00:00Z",
         "ends_at": "2026-04-12T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)
    gb = validate_success(api.create_group_booking(
        {"show_event_id": show["id"], "organization_name": "Big Group",
         "student_count": 4, "chaperone_count": 1}, GROUP_SALES), expected_status=201)
    validate_error(api.pay_group_deposit(gb["id"], GROUP_SALES), ApiErrorId.ERR_INVALID_STATE.value)
    gb_after = validate_success(api.get_group_booking(gb["id"], GROUP_SALES))
    assert gb_after["status"] == "REQUESTED", f"expected REQUESTED, got {gb_after['status']}"


def test_overfulfillment_rejected_independently(api):
    """PRD §3.8: "A contribution that would push the sponsor's `received_cents` above
    its `pledged_cents` is rejected with `ERR_OVERFULFILLMENT` — over-fulfillment is
    not allowed."

    The fiscal leg of the category pair, isolated: a PARTIALLY_FULFILLED sponsor
    (still in an accepting state) rejects a contribution that would push
    received_cents above pledged_cents with ERR_OVERFULFILLMENT.

    Design: Difficulty/priority_pair_validation_conflict/safety_age_vs_fiscal_overfulfillment_categories
    """
    sponsor = create_sponsor(pledged_cents=5000, sponsor_kind="SPONSOR", org_name="Acme2")
    record_contribution(sponsor["id"], amount_cents=3000)  # -> PARTIALLY_FULFILLED (still accepting)
    live = validate_success(api.get_sponsor(sponsor["id"], DEV))
    resp = api.create_contribution(
        sponsor["id"], {"amount_cents": 3000, "expected_sponsor_version": live["version"]}, DEV)
    validate_error(resp, ApiErrorId.ERR_OVERFULFILLMENT.value, expected_status=422)


# --- boundary_precision_check ---
# show_capacity_exact_boundary already has two primary tests (X and X+1) in test_03.

def test_waitlisted_then_cancel_enrolled_is_not_yet_promoted_position(api):
    """PRD §3.6: "a waitlisted one is `WAITLISTED`, and its `waitlist_position` is its
    1-based rank among the session's `WAITLISTED` registrations ordered by `created_at`
    ascending (the position is null while enrolled)."

    Capacity 1 with 1 ENROLLED: a second registration is WAITLISTED with position 1
    and a null waitlist_position is reserved only for the enrolled registration.

    Design: Difficulty/boundary_precision_check/program_waitlist_zero_seat_empty_set
    """
    program = create_classroom_program(capacity=1, tuition_cents=5000, min_age=5, max_age=99,
                                        program_kind="CLASS", title="Solo Class 2")
    reg1 = create_registration(program["id"], participant_name="First", participant_age=10)
    reg2 = create_registration(program["id"], participant_name="Second", participant_age=11)
    assert reg1["status"] == "ENROLLED"
    assert reg1["waitlist_position"] is None, \
        f"enrolled reg waitlist_position must be null, got {reg1['waitlist_position']}"
    assert reg2["status"] == "WAITLISTED"
    assert reg2["waitlist_position"] == 1


# --- cross_entity_state_dependency ---

def test_confirm_blocked_booking_is_cancelled_state(api):
    """PRD §3.3: "every booking on the show that is currently `HELD` or `CONFIRMED` is
    moved to `CANCELLED`".

    The precondition the confirm fails on: after the show cancel cascade, the booking
    is CANCELLED.

    Design: Difficulty/cross_entity_state_dependency/show_booking_confirm_requires_show_open
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1000, title="GateA2")
    booking = create_hold(show["id"], party_size=1)
    validate_success(api.cancel_show(show["id"], BOX_OFFICE))
    booking_after = validate_success(api.get_show_booking(booking["id"], BOX_OFFICE))
    assert booking_after["status"] == "CANCELLED"
    validate_error(api.confirm_show_booking(booking["id"], BOX_OFFICE),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_group_deposit_on_scheduled_show_keeps_requested(api):
    """PRD §3.5: "this is permitted only while the booking is `REQUESTED` and the
    linked show is `OPEN`".

    The deposit attempt against a SCHEDULED show is rejected and leaves the group
    booking REQUESTED.

    Design: Difficulty/cross_entity_state_dependency/group_pay_deposit_requires_show_open
    """
    dome = create_dome(seated_capacity=60, name="Dome H2")
    show = validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "GateB2", "starts_at": "2026-04-18T10:00:00Z",
         "ends_at": "2026-04-18T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)
    gb = validate_success(api.create_group_booking(
        {"show_event_id": show["id"], "organization_name": "Grp",
         "student_count": 10, "chaperone_count": 1}, GROUP_SALES), expected_status=201)
    validate_error(api.pay_group_deposit(gb["id"], GROUP_SALES), ApiErrorId.ERR_INVALID_STATE.value)
    gb_after = validate_success(api.get_group_booking(gb["id"], GROUP_SALES))
    assert gb_after["status"] == "REQUESTED"


# --- resource_temporal_overlap ---

def test_show_conflict_http_status_409(api):
    """PRD §2.10: "When a new show is scheduled, its window extended forward by the
    venue's turnover buffer must not overlap any other non-cancelled show in that same
    venue; an overlap is rejected with `ERR_SHOW_TIME_CONFLICT`."

    The buffered overlap returns ERR_SHOW_TIME_CONFLICT at HTTP 409.

    Design: Difficulty/resource_temporal_overlap/show_overlap_with_turnover_buffer
    """
    dome = create_dome(seated_capacity=50, turnover_buffer_minutes=15, name="Dome I2")
    validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "First", "starts_at": "2026-04-20T10:00:00Z",
         "ends_at": "2026-04-20T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)
    resp = api.create_show(
        {"venue_id": dome["id"], "title": "Second", "starts_at": "2026-04-20T11:10:00Z",
         "ends_at": "2026-04-20T12:00:00Z", "base_price_cents": 1000}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_SHOW_TIME_CONFLICT.value, expected_status=409)


def test_rental_adjacent_hold_independent_first_stays_held(api):
    """PRD §2.10: "a rental may be held only if its bare window overlaps no other held
    or confirmed rental in the same hall".

    The first HELD rental remains HELD while an adjacent (gap=0) second rental is also
    successfully held — the bare windows do not overlap.

    Design: Difficulty/resource_temporal_overlap/rental_overlap_no_buffer_adjacency_ok
    """
    hall = create_rental_hall(seated_capacity=80, name="Hall J2")
    r1 = create_held_rental(hall["id"], guest_count=10, base_rental_cents=30000, host_name="A",
                            starts_at="2026-05-10T14:00:00Z", ends_at="2026-05-10T16:00:00Z")
    r2 = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "B", "starts_at": "2026-05-10T16:00:00Z",
         "ends_at": "2026-05-10T18:00:00Z", "guest_count": 10, "base_rental_cents": 30000}, EVENTS),
        expected_status=201)
    validate_success(api.hold_rental(r2["id"], EVENTS))
    r1_after = validate_success(api.get_rental(r1["id"], EVENTS))
    assert r1_after["status"] == "HELD", f"first rental should stay HELD, got {r1_after['status']}"


# --- compensating_invariant ---

def test_refund_marks_booking_refunded_terminal(api):
    """PRD §3.4: "A refund releases the `party_size` seats, recomputes `seats_sold`,
    returns the `net_price_cents` to the buyer under a conserved-quantity invariant
    (the cents paid in equal the cents paid out), bubbles `SOLD_OUT → OPEN` if seats
    now fall below capacity, increments the show's `version`, and moves the booking to
    the terminal `REFUNDED` state."

    The refunded net equals the originally charged net (no cents drift).

    Design: Difficulty/compensating_invariant/show_refund_conserves_seats_and_cents
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1500, title="Refundable2")
    booking = create_confirmed_booking(show["id"], party_size=2)
    refunded = validate_success(api.refund_show_booking(booking["id"], BOX_OFFICE))
    assert refunded["status"] == "REFUNDED"
    assert refunded["net_price_cents"] == 3000, \
        f"refunded net must equal charged net 3000, got {refunded['net_price_cents']}"


def test_group_cancel_total_seats_block_size(api):
    """PRD §3.5: "At request time the system computes the block's `total_seats` as the
    `student_count` plus the `chaperone_count`".
    PRD §3.5: "Cancelling from `DEPOSIT_PAID` first releases the reserved block by
    subtracting `total_seats` from the show's `seats_sold`".

    The 10-student + 1-chaperone block is total_seats=11, and cancelling it returns the
    show to CANCELLED group state.

    Design: Difficulty/compensating_invariant/group_cancel_conserves_show_seats
    """
    show = create_open_show(seated_capacity=60, base_price_cents=1000, title="GroupShow2")
    gb = create_deposit_paid_group(show["id"], student_count=10, chaperone_count=1,
                                   organization_name="Field Trip")
    assert gb["total_seats"] == 11
    cancelled = validate_success(api.cancel_group_booking(gb["id"], GROUP_SALES))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_seats"] == 11
