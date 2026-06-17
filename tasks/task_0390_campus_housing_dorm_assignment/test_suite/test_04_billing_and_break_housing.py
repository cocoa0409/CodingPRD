"""Damage-charge billing (SOLE vs SHARED split), the bill/pay ledger invariant,
and break-housing approval (night charge, overlap, capacity, date range)."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_officer_headers, make_student_headers,
    create_damage_charge, bill_charge,
    setup_active_assignment, setup_shared_room_assignments,
    setup_break_eligible_assignment, create_break_request, approve_break_request,
    setup_break_eligible_double_two_occupants,
    setup_break_eligible_two_rooms_one_occupant_each,
)

OFFICER = make_officer_headers()


# ─── Difficulty: dual-variant damage split (SOLE vs SHARED) ───────────────────

def test_damage_split_sole_bills_full_assessed(api):
    """PRD §3.6: "The split rule is: when `split_basis` is `SOLE`, the final
    `amount_cents` equals the full `assessed_cents` and the occupant count is
    ignored."

    Design: Difficulty/dual_variant_calc/damage_split_sole_vs_shared_on_damage_charge
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Sole Sam",
                                                  "lottery_number": 10},
                                  room_kwargs={"room_number": "S1"},
                                  preferred_room_type="SINGLE", term_label="FALL_SOLE")
    charge = create_damage_charge(scn["assignment"]["id"], category="REPAIR",
                                  assessed_cents=10000, split_basis="SOLE")
    billed = validate_success(api.bill_damage_charge(charge["id"], OFFICER), 200)
    assert billed["status"] == "BILLED"
    assert billed["amount_cents"] == 10000


def test_damage_split_shared_floor_divides_with_remainder_to_billed(api):
    """PRD §3.6: "When `split_basis` is `SHARED`, the server counts the
    assignments in `ACTIVE` status on the charge's room at the moment of billing;
    if that count is one or fewer, the final `amount_cents` is the full
    `assessed_cents`; otherwise the base share is `assessed_cents` divided by the
    occupant count using integer floor division, the remainder is `assessed_cents`
    minus the base times the occupant count, and the billed resident (this
    charge's assignment) is charged the base share plus that entire remainder."

    Design: Difficulty/dual_variant_calc/damage_split_sole_vs_shared_on_damage_charge
    """
    # TRIPLE room with three ACTIVE occupants; 10000 / 3 -> base 3333 + remainder 1 = 3334.
    scn = setup_shared_room_assignments(num_occupants=3, room_type="TRIPLE",
                                        term_label="FALL_SHARE3")
    billed_assignment = scn["assignments"][0]
    charge = create_damage_charge(billed_assignment["id"], category="REPAIR",
                                  assessed_cents=10000, split_basis="SHARED")
    billed = validate_success(api.bill_damage_charge(charge["id"], OFFICER), 200)
    assert billed["amount_cents"] == 3334


def test_damage_shared_floor_then_remainder_order_4501(api):
    """PRD §3.6: "the base share is `assessed_cents` divided by the occupant count
    using integer floor division, the remainder is `assessed_cents` minus the base
    times the occupant count, and the billed resident (this charge's assignment)
    is charged the base share plus that entire remainder."
    PRD §2.6: "the division is integer floor division and the leftover remainder
    is assigned deterministically as described in §3.6, never spread or rounded
    away."

    Design: Difficulty/combinatorial_formula/damage_shared_floor_then_remainder_order_mode_b
    """
    # DOUBLE room with two ACTIVE occupants; 9001 / 2 -> base 4500 + remainder 1 = 4501.
    scn = setup_shared_room_assignments(num_occupants=2, room_type="DOUBLE",
                                        term_label="FALL_2026D")
    billed_assignment = scn["assignments"][0]
    charge = create_damage_charge(billed_assignment["id"], category="REPLACEMENT",
                                  assessed_cents=9001, split_basis="SHARED")
    billed = validate_success(api.bill_damage_charge(charge["id"], OFFICER), 200)
    assert billed["amount_cents"] == 4501


def test_damage_shared_remainder_debits_billed_student_balance(api):
    """PRD §3.6: "Billing a pending charge moves it from `PENDING` to `BILLED`,
    computes its final `amount_cents`, and debits the resident: the student's
    `account_balance_cents` increases by `amount_cents`." ... "the billed resident
    (this charge's assignment) is charged the base share plus that entire
    remainder."

    Design: Difficulty/combinatorial_formula/damage_shared_floor_then_remainder_order_mode_b
    """
    # DOUBLE room, two occupants; 9001 / 2 -> base 4500 + remainder 1 = 4501 to
    # the billed resident; the billed student's balance rises by exactly 4501.
    scn = setup_shared_room_assignments(num_occupants=2, room_type="DOUBLE",
                                        term_label="FALL_SHARE_BAL")
    billed_assignment = scn["assignments"][0]
    billed_student = scn["students"][0]
    charge = create_damage_charge(billed_assignment["id"], category="REPLACEMENT",
                                  assessed_cents=9001, split_basis="SHARED")
    bill_charge(charge["id"])
    student_after = validate_success(api.get_student(billed_student["id"], OFFICER), 200)
    assert student_after["account_balance_cents"] == 4501


# ─── Difficulty: bill-then-pay conserves the student ledger ───────────────────

def test_bill_debits_then_pay_credits_restores_balance(api):
    """PRD §3.6: "Billing a pending charge moves it from `PENDING` to `BILLED`,
    computes its final `amount_cents`, and debits the resident: the student's
    `account_balance_cents` increases by `amount_cents`." ... "A billed charge may
    be marked paid, moving it from `BILLED` to the terminal `PAID` and crediting
    the resident: the student's `account_balance_cents` decreases by
    `amount_cents`, but the balance is never allowed to fall below 0."

    Design: Difficulty/compensating_invariant/bill_then_pay_conserves_student_account_balance
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Ledger L",
                                                  "gender_identity": "MALE",
                                                  "lottery_number": 160},
                                  term_label="FALL_2026R")
    student = scn["student"]
    charge = create_damage_charge(scn["assignment"]["id"], category="REPLACEMENT",
                                  assessed_cents=10000, split_basis="SOLE")
    bill_charge(charge["id"])
    after_bill = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert after_bill["account_balance_cents"] == 10000
    paid = validate_success(api.pay_damage_charge(charge["id"], OFFICER), 200)
    assert paid["status"] == "PAID"
    after_pay = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert after_pay["account_balance_cents"] == 0


def test_bill_debits_student_balance_by_amount(api):
    """PRD §3.6: "Billing a pending charge moves it from `PENDING` to `BILLED`,
    computes its final `amount_cents`, and debits the resident: the student's
    `account_balance_cents` increases by `amount_cents`."

    Design: Difficulty/compensating_invariant/bill_then_pay_conserves_student_account_balance
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Debit D",
                                                  "gender_identity": "MALE",
                                                  "lottery_number": 161},
                                  term_label="FALL_DEBIT")
    student = scn["student"]
    before = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert before["account_balance_cents"] == 0
    charge = create_damage_charge(scn["assignment"]["id"], category="REPAIR",
                                  assessed_cents=7500, split_basis="SOLE")
    bill_charge(charge["id"])
    after = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert after["account_balance_cents"] == 7500


# ─── Break housing: date range & night-count boundary ─────────────────────────

def test_break_request_invalid_date_range_rejected(api):
    """PRD §3.8: "The `check_out_date` must be strictly after the
    `check_in_date`; a check-out that is not strictly later is rejected at
    validation with `ERR_INVALID_DATE_RANGE` (HTTP 422), and such a request can
    never be approved."

    Design: Corner/validations/break_request_invalid_date_range_rejected
    """
    scn = setup_break_eligible_assignment(break_housing_capacity=2,
                                          term_label="DATE_T", lottery_number=340)
    res = api.create_break_request(
        {"assignment_id": scn["assignment"]["id"],
         "check_in_date": "2026-12-20T00:00:00Z",
         "check_out_date": "2026-12-20T00:00:00Z"},
        make_student_headers(scn["student"]["id"]))
    validate_error(res, "ERR_INVALID_DATE_RANGE", expected_status=422)


def test_break_one_night_charge_at_minimum_boundary(api):
    """PRD §3.8: "The `night_count` is the number of whole nights in the half-open
    interval from `check_in_date` up to but not including `check_out_date`,
    computed as the floored count of whole days between the two dates." ... "On
    approval the server computes `total_charge_cents` as `night_count` multiplied
    by the room's `nightly_break_rate_cents`".

    Design: Difficulty/boundary_precision_check/break_night_count_minimum_one_night_boundary
    """
    scn = setup_break_eligible_assignment(break_housing_capacity=1,
                                          nightly_break_rate_cents=4500,
                                          term_label="FALL_2026L", lottery_number=100)
    req = create_break_request(scn["assignment"]["id"], scn["student"]["id"],
                               "2026-12-20T00:00:00Z", "2026-12-21T00:00:00Z")
    approved = validate_success(api.approve_break_request(req["id"], OFFICER), 200)
    assert approved["night_count"] == 1
    assert approved["total_charge_cents"] == 4500


def test_break_seven_night_charge(api):
    """PRD §3.8: "On approval the server computes `total_charge_cents` as
    `night_count` multiplied by the room's `nightly_break_rate_cents` and debits
    the resident: the student's `account_balance_cents` increases by
    `total_charge_cents`."

    Design: Difficulty/boundary_precision_check/break_night_count_minimum_one_night_boundary
    """
    scn = setup_break_eligible_assignment(break_housing_capacity=2,
                                          nightly_break_rate_cents=4500,
                                          term_label="FALL_7N", lottery_number=101)
    req = create_break_request(scn["assignment"]["id"], scn["student"]["id"],
                               "2026-12-20T00:00:00Z", "2026-12-27T00:00:00Z")
    approved = validate_success(api.approve_break_request(req["id"], OFFICER), 200)
    assert approved["night_count"] == 7
    assert approved["total_charge_cents"] == 31500


# ─── Break housing: building-offers gate (difficulty) ─────────────────────────

def test_break_approve_requires_building_offers_break_housing(api):
    """PRD §3.8: "The room's building must offer break housing (its
    `offers_break_housing` must be true); a building that does not is rejected
    with `ERR_PRECONDITION_NOT_MET` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/break_approve_requires_building_offers_break_housing
    """
    # Build an ACTIVE assignment in a building that does NOT offer break housing,
    # then create a break request and attempt approval.
    scn = setup_active_assignment(
        student_kwargs={"full_name": "NoBreak N", "gender_identity": "NONBINARY",
                        "lottery_number": 120},
        building_kwargs={"name": "Closed Hall", "building_type": "TRADITIONAL",
                         "offers_break_housing": False},
        room_kwargs={"room_number": "CH1"}, term_label="FALL_2026N")
    req = create_break_request(scn["assignment"]["id"], scn["student"]["id"],
                               "2027-01-02T00:00:00Z", "2027-01-05T00:00:00Z")
    res = api.approve_break_request(req["id"], OFFICER)
    validate_error(res, "ERR_PRECONDITION_NOT_MET")
    after = validate_success(api.get_break_request(req["id"], OFFICER), 200)
    assert after["status"] == "REQUESTED"


def test_break_approve_succeeds_when_building_offers_break_housing(api):
    """PRD §3.8: "The officer approves a requested break, moving it from
    `REQUESTED` to `APPROVED`, subject to several gates. The room's building must
    offer break housing (its `offers_break_housing` must be true); a building that
    does not is rejected with `ERR_PRECONDITION_NOT_MET` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/break_approve_requires_building_offers_break_housing
    """
    # Complement of the rejection case: a break-eligible building (offers_break_housing
    # true) lets the otherwise-identical request reach APPROVED.
    scn = setup_break_eligible_assignment(break_housing_capacity=2,
                                          term_label="FALL_OK_BRK", lottery_number=121)
    req = create_break_request(scn["assignment"]["id"], scn["student"]["id"],
                               "2027-01-02T00:00:00Z", "2027-01-05T00:00:00Z")
    approved = validate_success(api.approve_break_request(req["id"], OFFICER), 200)
    assert approved["status"] == "APPROVED"


# ─── Break housing: per-room overlap (difficulty) ─────────────────────────────

def test_break_per_room_overlap_rejected(api):
    """PRD §3.8: "The requested interval must not overlap any existing `APPROVED`
    break interval on the same room: treating each interval as half-open from
    check-in up to but not including check-out, two intervals conflict when they
    share any instant, while exact adjacency (one interval's check-out equal to
    the next interval's check-in) is allowed; an overlap is rejected with
    `ERR_BREAK_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/break_per_room_exclusive_overlap_half_open
    """
    # One DOUBLE room (capacity 5 building) with two occupants; first break
    # [12-20,12-27) APPROVED, second [12-24,12-29) on the SAME room overlaps.
    scn = setup_break_eligible_double_two_occupants(break_housing_capacity=5,
                                                    term_label="FALL_2026O")
    a0, a1 = scn["assignments"][0], scn["assignments"][1]
    s0, s1 = scn["students"][0], scn["students"][1]
    req0 = create_break_request(a0["id"], s0["id"],
                                "2026-12-20T00:00:00Z", "2026-12-27T00:00:00Z")
    approve_break_request(req0["id"])
    req1 = create_break_request(a1["id"], s1["id"],
                                "2026-12-24T00:00:00Z", "2026-12-29T00:00:00Z")
    res = api.approve_break_request(req1["id"], OFFICER)
    validate_error(res, "ERR_BREAK_OVERLAP")
    after = validate_success(api.get_break_request(req1["id"], OFFICER), 200)
    assert after["status"] == "REQUESTED"


def test_break_per_room_adjacency_allowed(api):
    """PRD §3.8: "while exact adjacency (one interval's check-out equal to the next
    interval's check-in) is allowed".

    Design: Difficulty/resource_temporal_overlap/break_per_room_exclusive_overlap_half_open
    """
    scn = setup_break_eligible_double_two_occupants(break_housing_capacity=5,
                                                    term_label="FALL_ADJ")
    a0, a1 = scn["assignments"][0], scn["assignments"][1]
    s0, s1 = scn["students"][0], scn["students"][1]
    req0 = create_break_request(a0["id"], s0["id"],
                                "2026-12-20T00:00:00Z", "2026-12-27T00:00:00Z")
    approve_break_request(req0["id"])
    # Adjacent: starts exactly where the first ends.
    req1 = create_break_request(a1["id"], s1["id"],
                                "2026-12-27T00:00:00Z", "2026-12-30T00:00:00Z")
    approved = validate_success(api.approve_break_request(req1["id"], OFFICER), 200)
    assert approved["status"] == "APPROVED"


def test_break_per_building_capacity_exceeded_rejected(api):
    """PRD §3.8: "The building's aggregate capacity must also hold: at every
    instant within the requested interval, the count of `APPROVED` break requests
    across all rooms of the same building that overlap that instant, plus this
    one, must not exceed the building's `break_housing_capacity`; exceeding it is
    rejected with `ERR_BREAK_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/break_per_building_aggregate_capacity_overlap
    """
    # capacity 1; room A approved [01-02,01-10); room B overlapping [01-05,01-08)
    # exceeds the building ceiling even though no single room is double-booked.
    scn = setup_break_eligible_two_rooms_one_occupant_each(break_housing_capacity=1,
                                                           term_label="FALL_2026P")
    a0, a1 = scn["assignments"][0], scn["assignments"][1]
    s0, s1 = scn["students"][0], scn["students"][1]
    req0 = create_break_request(a0["id"], s0["id"],
                                "2027-01-02T00:00:00Z", "2027-01-10T00:00:00Z")
    approve_break_request(req0["id"])
    req1 = create_break_request(a1["id"], s1["id"],
                                "2027-01-05T00:00:00Z", "2027-01-08T00:00:00Z")
    res = api.approve_break_request(req1["id"], OFFICER)
    validate_error(res, "ERR_BREAK_CAPACITY_EXCEEDED")
    after = validate_success(api.get_break_request(req1["id"], OFFICER), 200)
    assert after["status"] == "REQUESTED"


def test_break_per_building_capacity_allows_non_overlapping_second(api):
    """PRD §3.8: "The building's aggregate capacity must also hold: at every
    instant within the requested interval, the count of `APPROVED` break requests
    across all rooms of the same building that overlap that instant, plus this
    one, must not exceed the building's `break_housing_capacity`".

    Design: Difficulty/resource_temporal_overlap/break_per_building_aggregate_capacity_overlap
    """
    # capacity 1; room A approved [01-02,01-10); room B request [01-12,01-15)
    # shares no instant with A, so the aggregate-capacity ceiling is not exceeded
    # and the second approval succeeds.
    scn = setup_break_eligible_two_rooms_one_occupant_each(break_housing_capacity=1,
                                                           term_label="FALL_CAP_OK")
    a0, a1 = scn["assignments"][0], scn["assignments"][1]
    s0, s1 = scn["students"][0], scn["students"][1]
    req0 = create_break_request(a0["id"], s0["id"],
                                "2027-01-02T00:00:00Z", "2027-01-10T00:00:00Z")
    approve_break_request(req0["id"])
    req1 = create_break_request(a1["id"], s1["id"],
                                "2027-01-12T00:00:00Z", "2027-01-15T00:00:00Z")
    approved = validate_success(api.approve_break_request(req1["id"], OFFICER), 200)
    assert approved["status"] == "APPROVED"


def test_break_cancel_refunds_balance(api):
    """PRD §3.8: "The requesting resident may cancel their break from either
    `REQUESTED` or `APPROVED`, moving it to the terminal `CANCELLED`; if the break
    was `APPROVED`, the charge is refunded, decreasing the student's
    `account_balance_cents` by `total_charge_cents` but never below 0."

    Design: Corner/state_machines/break_cancel_refunds_balance
    """
    scn = setup_break_eligible_assignment(break_housing_capacity=2,
                                          nightly_break_rate_cents=4500,
                                          term_label="RF_T", lottery_number=280)
    student = scn["student"]
    req = create_break_request(scn["assignment"]["id"], student["id"],
                               "2026-12-20T00:00:00Z", "2026-12-27T00:00:00Z")
    approve_break_request(req["id"])
    after_approve = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert after_approve["account_balance_cents"] == 31500
    cancelled = validate_success(
        api.cancel_break_request(req["id"], make_student_headers(student["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    after_cancel = validate_success(api.get_student(student["id"], OFFICER), 200)
    assert after_cancel["account_balance_cents"] == 0
