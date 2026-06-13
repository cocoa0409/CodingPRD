"""Boundary-precision, resource-temporal-overlap, and compensating-invariant tests.

Queue A:
  boundary_precision_check:
    - interval_exact_56_day_boundary_checkin_inclusive
    - recall_empty_lookback_window_zero_units_recalled
  resource_temporal_overlap:
    - slot_capacity_aggregate_occupation_full
    - donor_interval_minimum_gap_between_donations
  compensating_invariant:
    - slot_booked_count_conserved_book_then_cancel
    - inventory_total_conserved_reserve_then_unreserve
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    create_recall_event_payload, create_inventory_bucket_payload,
    advance_clock_payload,
    create_center, create_donor, create_slot, book_appointment,
    setup_collected_donation, setup_available_unit,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]
INV = TEST_USERS["inventory_manager_headers"]


def _book_second_whole_appt(center, donor, win_start, win_end, advance_to):
    """Create a second WHOLE slot, book the donor, advance the clock to advance_to.
    Returns the SCHEDULED second appointment."""
    slot2 = create_slot(center["id"], donation_type="WHOLE",
                        starts_at=win_start, ends_at=win_end, capacity=5)
    appt2 = book_appointment(donor["id"], slot2)
    get_success_data(api_client.advance_clock(center["id"], advance_clock_payload(advance_to), ADMIN))
    return appt2


# ─── interval_exact_56_day_boundary_checkin_inclusive ─────────────────────────
def test_checkin_succeeds_exactly_56_days_after_whole_collection(api):
    """PRD §3.5: "The interval is satisfied when the center's current_utc is at or after
    that next eligible instant; a donation exactly the interval's number of days later is
    therefore eligible."
    PRD §3.5: "The system enforces a minimum number of days between collections, which
    varies by donation type: 56 days for WHOLE, 28 days for PLASMA, and 7 days for PLATELET."

    A WHOLE donor collected 2025-01-01 checks in for a second WHOLE collection at exactly
    2025-02-26 (collected_at + 56d) — the inclusive >= boundary passes.

    Design: Difficulty/boundary_precision_check/interval_exact_56_day_boundary_checkin_inclusive
    """
    center, donor, slot1, appt1, donation1 = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 80})
    appt2 = _book_second_whole_appt(
        center, donor, "2025-02-26T08:00:00.000Z", "2025-02-26T18:00:00.000Z", "2025-02-26T00:00:00.000Z")

    checked_in = validate_success(api.check_in_appointment(appt2["id"], NURSE), 200)
    assert checked_in["status"] == "CHECKED_IN", "current_utc == collected_at + 56d satisfies >="


def test_checkin_rejected_one_day_before_56_day_boundary(api):
    """PRD §3.5: "The interval is satisfied when the center's current_utc is at or after
    that next eligible instant ..."
    PRD §3.4: "the inter-donation interval for the slot's donation type must have elapsed,
    else ERR_INTERVAL_NOT_ELAPSED — this is the authoritative interval gate described in §3.5."

    One day short of the boundary (2025-02-25 = collected_at + 55d) check-in is rejected
    with ERR_INTERVAL_NOT_ELAPSED — the X-1 side of the >= boundary. (Also covers the
    minimum-gap semantics of resource_temporal_overlap.)

    Design: Difficulty/boundary_precision_check/interval_exact_56_day_boundary_checkin_inclusive
    """
    center, donor, slot1, appt1, donation1 = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 80})
    appt2 = _book_second_whole_appt(
        center, donor, "2025-02-25T08:00:00.000Z", "2025-02-25T18:00:00.000Z", "2025-02-25T00:00:00.000Z")

    res = api.check_in_appointment(appt2["id"], NURSE)
    validate_error(res, "ERR_INTERVAL_NOT_ELAPSED", expected_status=409)


# ─── recall_empty_lookback_window_zero_units_recalled ─────────────────────────
def test_recall_with_window_after_donation_yields_zero_scope_and_closes(api):
    """PRD §3.8: "the window start is the center's current_utc minus lookback_days days
    (converted at 86,400 seconds per day), and the donations in scope are the donor's
    donations whose collected_at is at or after that window start — a donation falling
    exactly on the window start is in scope."
    PRD §3.8: "Finally the recall event's status is set to CLOSED."

    A donation collected 2025-01-01 with a 1-day lookback at clock 2025-03-01 (window
    start 2025-02-28) is out of scope: donations_in_scope_count and units_recalled_count
    are 0, and the recall still CLOSES.

    Design: Difficulty/boundary_precision_check/recall_empty_lookback_window_zero_units_recalled
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "A_NEG", "weight_kg": 70})
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-03-01T00:00:00.000Z"), ADMIN))

    recall = validate_success(api.create_recall_event(
        create_recall_event_payload(center["id"], donor["id"], reason="OTHER", lookback_days=1), INV), 201)
    assert recall["donations_in_scope_count"] == 0
    assert recall["units_recalled_count"] == 0
    assert recall["status"] == "CLOSED"


def test_recall_with_window_covering_donation_finds_it_in_scope(api):
    """PRD §3.8: "the donations in scope are the donor's donations whose collected_at is
    at or after that window start — a donation falling exactly on the window start is in
    scope. These are ordered by collected_at ascending and then created_at ascending for
    a deterministic cascade, and their count is recorded in donations_in_scope_count."

    The X+ side: a wide 90-day lookback at clock 2025-03-01 (window start ~2025-11 prior)
    covers the 2025-01-01 donation, so donations_in_scope_count is 1.

    Design: Difficulty/boundary_precision_check/recall_empty_lookback_window_zero_units_recalled
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "A_NEG", "weight_kg": 70})
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-03-01T00:00:00.000Z"), ADMIN))

    recall = validate_success(api.create_recall_event(
        create_recall_event_payload(center["id"], donor["id"], reason="OTHER", lookback_days=90), INV), 201)
    assert recall["donations_in_scope_count"] == 1, "90-day window covers the 2025-01-01 donation"


# ─── slot_capacity_aggregate_occupation_full ──────────────────────────────────
def test_second_booking_into_full_capacity_one_slot_rejected(api):
    """PRD §3.3: "it becomes FULL automatically when booked_count reaches or exceeds
    capacity ..."
    PRD §3.3: "The slot must be bookable: a slot that is CLOSED or FULL is rejected with
    ERR_SLOT_NOT_BOOKABLE."

    A capacity-1 slot with one SCHEDULED appointment is FULL; a second donor's booking is
    rejected with ERR_SLOT_NOT_BOOKABLE.

    Design: Difficulty/resource_temporal_overlap/slot_capacity_aggregate_occupation_full
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor_a = create_donor(center["id"], full_name="First Donor", date_of_birth="1990-01-01",
                          weight_kg=70, blood_type="O_POS")
    donor_b = create_donor(center["id"], full_name="Second Donor", date_of_birth="1991-01-01",
                          weight_kg=70, blood_type="O_NEG")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T09:00:00.000Z", capacity=1)
    book_appointment(donor_a["id"], slot)

    slot_after = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert slot_after["status"] == "FULL", "booked_count 1 == capacity 1 -> FULL"

    res = api.create_appointment(
        {"donor_id": donor_b["id"], "slot_id": slot["id"], "expected_slot_version": slot_after["version"]}, NURSE)
    validate_error(res, "ERR_SLOT_NOT_BOOKABLE", expected_status=409)


def test_booking_into_capacity_two_slot_below_capacity_succeeds(api):
    """PRD §3.3: "The slot's booked_count is incremented by one, its version is incremented
    by one, and its status flips to FULL if booked_count now reaches or exceeds capacity."

    A capacity-2 slot admits a second concurrent appointment (aggregate occupancy below
    capacity) and only then becomes FULL.

    Design: Difficulty/resource_temporal_overlap/slot_capacity_aggregate_occupation_full
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor_a = create_donor(center["id"], full_name="A Donor", date_of_birth="1990-01-01",
                          weight_kg=70, blood_type="O_POS")
    donor_b = create_donor(center["id"], full_name="B Donor", date_of_birth="1991-01-01",
                          weight_kg=70, blood_type="A_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T09:00:00.000Z", capacity=2)
    book_appointment(donor_a["id"], slot)
    slot_mid = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert slot_mid["status"] == "OPEN", "1 of 2 booked -> still OPEN"

    appt2 = validate_success(api.create_appointment(
        {"donor_id": donor_b["id"], "slot_id": slot["id"], "expected_slot_version": slot_mid["version"]}, NURSE), 201)
    assert appt2["status"] == "SCHEDULED"
    slot_full = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert slot_full["status"] == "FULL", "2 of 2 booked -> FULL"


# ─── donor_interval_minimum_gap_between_donations ─────────────────────────────
def test_checkin_rejected_at_55_day_gap_minimum_spacing(api):
    """PRD §3.5: "The system enforces a minimum number of days between collections, which
    varies by donation type: 56 days for WHOLE ..."
    PRD §3.4: "the inter-donation interval for the slot's donation type must have elapsed,
    else ERR_INTERVAL_NOT_ELAPSED ..."

    A WHOLE donor collected 2025-01-01 cannot check in at 2025-02-25 (55-day gap, one day
    short of the 56-day minimum spacing); ERR_INTERVAL_NOT_ELAPSED and the appointment
    stays SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/donor_interval_minimum_gap_between_donations
    """
    center, donor, slot1, appt1, donation1 = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 80})
    appt2 = _book_second_whole_appt(
        center, donor, "2025-02-25T08:00:00.000Z", "2025-02-25T18:00:00.000Z", "2025-02-25T00:00:00.000Z")

    res = api.check_in_appointment(appt2["id"], NURSE)
    validate_error(res, "ERR_INTERVAL_NOT_ELAPSED", expected_status=409)
    appt_after = validate_success(api.get_appointment(appt2["id"], NURSE), 200)
    assert appt_after["status"] == "SCHEDULED", "check-in rejected, appointment unchanged"


def test_checkin_allowed_once_minimum_gap_met(api):
    """PRD §3.5: "a donation exactly the interval's number of days later is therefore
    eligible."

    Once the 56-day minimum spacing is met (clock at 2025-02-26), the second WHOLE check-in
    succeeds — the positive control for the minimum-gap rule.

    Design: Difficulty/resource_temporal_overlap/donor_interval_minimum_gap_between_donations
    """
    center, donor, slot1, appt1, donation1 = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 80})
    appt2 = _book_second_whole_appt(
        center, donor, "2025-02-26T08:00:00.000Z", "2025-02-26T18:00:00.000Z", "2025-02-26T00:00:00.000Z")

    checked_in = validate_success(api.check_in_appointment(appt2["id"], NURSE), 200)
    assert checked_in["status"] == "CHECKED_IN"


# ─── slot_booked_count_conserved_book_then_cancel ─────────────────────────────
def test_slot_booked_count_conserved_after_book_then_cancel(api):
    """PRD §3.3: "On cancel, the appointment moves to CANCELLED, the slot's booked_count
    is decremented by one and its status is recomputed (a slot that was FULL returns to
    OPEN once it falls below capacity) ..."

    A capacity-1 slot goes booked_count 0 -> 1 (FULL) on booking, then back to 0 (OPEN)
    on cancel — the conserved occupancy invariant.

    Design: Difficulty/compensating_invariant/slot_booked_count_conserved_book_then_cancel
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Cody Cancel", date_of_birth="1990-03-03",
                         weight_kg=70, blood_type="A_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T09:00:00.000Z", capacity=1)
    appt = book_appointment(donor["id"], slot)

    mid = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert mid["booked_count"] == 1 and mid["status"] == "FULL"

    get_success_data(api.cancel_appointment(appt["id"], NURSE))
    after = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert after["booked_count"] == 0, "booked_count conserved back to pre-booking value"
    assert after["status"] == "OPEN", "FULL returns to OPEN below capacity"


def test_donor_pending_type_cleared_after_cancel(api):
    """PRD §3.3: "and the donor's pending_donation_type is recomputed back to NONE if this
    was their open appointment."

    Cancelling the donor's only open appointment recomputes pending_donation_type to NONE
    — the donor-side leg of the book-then-cancel conservation.

    Design: Difficulty/compensating_invariant/slot_booked_count_conserved_book_then_cancel
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Cara Cancel", date_of_birth="1990-03-03",
                         weight_kg=70, blood_type="A_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T09:00:00.000Z", capacity=1)
    appt = book_appointment(donor["id"], slot)
    mid = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert mid["pending_donation_type"] == "WHOLE"

    get_success_data(api.cancel_appointment(appt["id"], NURSE))
    after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert after["pending_donation_type"] == "NONE", "pending type cleared after cancel"


# ─── inventory_total_conserved_reserve_then_unreserve ─────────────────────────
def test_inventory_total_conserved_reserve_then_unreserve(api):
    """PRD §3.7: "A successful reservation moves the unit from AVAILABLE to RESERVED,
    decrements the bucket's available_count by one, and increments its reserved_count by
    one."
    PRD §3.7: "it returns the unit to AVAILABLE, decrements reserved_count by one, and
    increments available_count by one."

    available_count + reserved_count is conserved across reserve then unreserve, and each
    counter is restored to its pre-reserve value.

    Design: Difficulty/compensating_invariant/inventory_total_conserved_reserve_then_unreserve
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-INV-001", donor_overrides={"blood_type": "O_POS", "weight_kg": 76})
    bucket = get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    assert bucket["available_count"] == 1 and bucket["reserved_count"] == 0

    api.reserve_blood_unit(unit["id"], INV)
    mid = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert mid["available_count"] == 0 and mid["reserved_count"] == 1
    assert mid["available_count"] + mid["reserved_count"] == 1, "total managed units conserved"

    api.unreserve_blood_unit(unit["id"], INV)
    after = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert after["available_count"] == 1 and after["reserved_count"] == 0, (
        "each counter restored; sum still 1")


def test_bucket_recount_reconciles_to_zero_managed_when_issued_after_cycle(api):
    """PRD §2.8: "available_count equals the number of that center's blood units in
    AVAILABLE status with that blood type and component, and reserved_count equals the
    number in RESERVED status. These counts are maintained incrementally by the unit
    state-machine side effects, but they are an invariant: at every moment the stored
    counts must equal a fresh recount over the underlying unit rows."
    PRD §3.7: "Issuing a unit to a hospital order also requires the unit to be RESERVED,
    else ERR_UNIT_NOT_RESERVED; it moves the unit to ISSUED and decrements reserved_count
    by one."

    The conserved (available + reserved) total tracks the unit out of the managed set: after
    reserve (available 0, reserved 1) and then issue (reserved 0), both counters are 0 — the
    one ISSUED (terminal) unit is no longer in either bucket count.

    Design: Difficulty/compensating_invariant/inventory_total_conserved_reserve_then_unreserve
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-INV-002", donor_overrides={"blood_type": "O_POS", "weight_kg": 76})
    bucket = get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    assert bucket["available_count"] == 1 and bucket["reserved_count"] == 0

    api.reserve_blood_unit(unit["id"], INV)
    mid = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert mid["available_count"] == 0 and mid["reserved_count"] == 1
    assert mid["available_count"] + mid["reserved_count"] == 1

    api.issue_blood_unit(unit["id"], INV)
    after = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert after["available_count"] == 0 and after["reserved_count"] == 0, (
        "the ISSUED unit leaves the managed set; both counts reconcile to 0")
