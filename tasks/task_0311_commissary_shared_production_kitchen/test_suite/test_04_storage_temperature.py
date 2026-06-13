"""Storage waterfall allocation, slot conservation, temperature excursions,
quarantine cascade, and storage pricing.

Translates difficulty queue instances:
  transitive_cascade / temp_breach_quarantines_unit_then_assignment
  boundary_precision_check / temp_reading_at_max_inclusive_is_in_range
  boundary_precision_check / storage_allocation_empty_candidate_pool_rejects
  cross_entity_state_dependency / assignment_create_requires_unit_not_quarantined
  resource_temporal_overlap / storage_slot_aggregate_capacity_overlap_rejects
  compensating_invariant / storage_release_restores_slot_conservation
and corner queue instances for premium-discount fee, waterfall overflow,
unit-not-recovered, excursion recovery, and member-close obligations.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_member, register_funded_member, current_member_version,
    create_storage_unit, create_storage_assignment,
)

FM = TEST_USERS["facility_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ── Difficulty: transitive_cascade / temp_breach_quarantines_unit_then_assignment ──

def test_temp_breach_quarantines_unit_and_cascades_to_assignment(api):
    """PRD 3.11: "If, after adding that gap, excursion_minutes strictly exceeds
    120 ... the unit transitions to QUARANTINED. Quarantining a unit cascades:
    every ACTIVE storage assignment whose allocation_plan touches this unit is
    itself moved to QUARANTINED". Readings at 10:00, 11:00, 12:05 accumulate
    excursion_minutes to 125 (>120), quarantining the unit and its assignment.

    Design: Difficulty/transitive_cascade/temp_breach_quarantines_unit_then_assignment
    """
    member = register_member(business_name="M7")
    v = member["version"]
    cold = create_storage_unit(name="Cold1", temp_class="COLD", total_slots=10,
                               temp_min_c=0.0, temp_max_c=4.0)
    assignment = create_storage_assignment(member["id"], "COLD", 3, v)

    api.create_temp_log(cold["id"], {"reading_c": 8.0, "reading_utc": "2026-07-03T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 8.0, "reading_utc": "2026-07-03T11:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 8.0, "reading_utc": "2026-07-03T12:05:00.000Z"}, CO)

    unit = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert unit["excursion_minutes"] == 125, f"got {unit['excursion_minutes']}"
    assert unit["compliance_status"] == "QUARANTINED"

    mo = make_member_operator_headers(member["id"])
    asn = validate_success(api.get_member_storage_assignment(member["id"], assignment["id"], mo), 200)
    assert asn["status"] == "QUARANTINED"


def test_temp_breach_under_120_does_not_quarantine(api):
    """PRD 3.11: "120 minutes exactly is not yet a breach, only a value greater
    than 120 is". Two readings 120 minutes apart leave excursion_minutes at 120
    and the unit in EXCURSION, not QUARANTINED.

    Design: Difficulty/transitive_cascade/temp_breach_quarantines_unit_then_assignment
    """
    cold = create_storage_unit(name="Cold1b", temp_class="COLD", total_slots=10,
                               temp_min_c=0.0, temp_max_c=4.0)
    api.create_temp_log(cold["id"], {"reading_c": 8.0, "reading_utc": "2026-07-03T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 8.0, "reading_utc": "2026-07-03T12:00:00.000Z"}, CO)
    unit = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert unit["excursion_minutes"] == 120, f"got {unit['excursion_minutes']}"
    assert unit["compliance_status"] == "EXCURSION"


# ── Difficulty: boundary_precision_check / temp_reading_at_max_inclusive_is_in_range ──

def test_reading_at_temp_max_is_in_range(api):
    """PRD 3.11: "a reading exactly at temp_max_c is in range." A 4.0 reading in
    the [0.0, 4.0] band is in_range, the unit stays COMPLIANT and
    excursion_minutes is 0.

    Design: Difficulty/boundary_precision_check/temp_reading_at_max_inclusive_is_in_range
    """
    cold = create_storage_unit(name="Cold3", temp_class="COLD", total_slots=5,
                               temp_min_c=0.0, temp_max_c=4.0)
    log = validate_success(
        api.create_temp_log(cold["id"], {"reading_c": 4.0, "reading_utc": "2026-07-06T10:00:00.000Z"}, CO), 201)
    assert log["in_range"] is True
    unit = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert unit["compliance_status"] == "COMPLIANT"
    assert unit["excursion_minutes"] == 0


def test_reading_above_temp_max_is_out_of_range(api):
    """PRD 3.11: "it is true exactly when the reading sits within the unit's safe
    band, that is, when reading_c is greater than or equal to temp_min_c and less
    than or equal to temp_max_c, with both bounds inclusive". A 4.1 reading
    above the 4.0 max is out of range and moves the unit to EXCURSION.

    Design: Difficulty/boundary_precision_check/temp_reading_at_max_inclusive_is_in_range
    """
    cold = create_storage_unit(name="Cold3b", temp_class="COLD", total_slots=5,
                               temp_min_c=0.0, temp_max_c=4.0)
    log = validate_success(
        api.create_temp_log(cold["id"], {"reading_c": 4.1, "reading_utc": "2026-07-06T10:00:00.000Z"}, CO), 201)
    assert log["in_range"] is False
    unit = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert unit["compliance_status"] == "EXCURSION"


# ── Difficulty: boundary_precision_check / storage_allocation_empty_candidate_pool_rejects ──

def test_storage_request_with_no_matching_units_rejected(api):
    """PRD 3.9: "If the aggregate free capacity across all same-class
    non-quarantined units is less than requested_slots, the request cannot be
    filled and is rejected with ERR_STORAGE_CAPACITY_EXCEEDED". Requesting FROZEN
    slots when no FROZEN units exist gives zero aggregate capacity.

    Design: Difficulty/boundary_precision_check/storage_allocation_empty_candidate_pool_rejects
    """
    member = register_member(business_name="M11")
    v = member["version"]
    create_storage_unit(name="DryX", temp_class="DRY", total_slots=10,
                        temp_min_c=10.0, temp_max_c=25.0)
    mo = make_member_operator_headers(member["id"])
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "FROZEN", "requested_slots": 1, "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_STORAGE_CAPACITY_EXCEEDED")


def test_storage_request_with_matching_unit_succeeds(api):
    """PRD 3.9: "The candidates are all storage units of the matching temp_class
    whose compliance_status is not QUARANTINED". When a matching FROZEN unit does
    exist with free slots, the same 1-slot request is satisfied (confirming the
    empty candidate pool was the cause of the rejection in the companion test).

    Design: Difficulty/boundary_precision_check/storage_allocation_empty_candidate_pool_rejects
    """
    member = register_member(business_name="M11b")
    v = member["version"]
    create_storage_unit(name="FrzAvail", temp_class="FROZEN", total_slots=10,
                        temp_min_c=-22.0, temp_max_c=-16.0)
    mo = make_member_operator_headers(member["id"])
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "FROZEN", "requested_slots": 1, "expected_member_version": v,
    }, mo)
    asn = validate_success(res, 201)
    assert asn["status"] == "ACTIVE"


# ── Difficulty: resource_temporal_overlap / storage_slot_aggregate_capacity_overlap_rejects ──

def test_storage_aggregate_capacity_overflow_rejected(api):
    """PRD 2.9: "Allocations may never drive a unit's used slots above its total
    slots, and the system never performs a partial allocation: a storage request
    either secures every requested slot or is rejected outright." With 8 of 10
    COLD slots already held, a 5-slot request overflows the 2 free and is
    rejected.

    Design: Difficulty/resource_temporal_overlap/storage_slot_aggregate_capacity_overlap_rejects
    """
    member_a = register_member(business_name="M15a")
    member_b = register_member(business_name="M15b")
    cold = create_storage_unit(name="Cold5", temp_class="COLD", total_slots=10,
                               temp_min_c=0.0, temp_max_c=4.0)
    create_storage_assignment(member_a["id"], "COLD", 8, member_a["version"])
    mo_b = make_member_operator_headers(member_b["id"])
    res = api.create_storage_assignment(member_b["id"], {
        "temp_class": "COLD", "requested_slots": 5, "expected_member_version": member_b["version"],
    }, mo_b)
    validate_error(res, "ERR_STORAGE_CAPACITY_EXCEEDED")


def test_storage_request_fitting_free_slots_succeeds(api):
    """PRD 3.9: "Walking the candidates in that order, the system takes from each
    unit the smaller of its free slots ... until the request is fully satisfied."
    With 8 of 10 COLD slots held, a 2-slot request fits the remaining free
    capacity and succeeds.

    Design: Difficulty/resource_temporal_overlap/storage_slot_aggregate_capacity_overlap_rejects
    """
    member_a = register_member(business_name="M15c")
    member_b = register_member(business_name="M15d")
    create_storage_unit(name="Cold5b", temp_class="COLD", total_slots=10,
                        temp_min_c=0.0, temp_max_c=4.0)
    create_storage_assignment(member_a["id"], "COLD", 8, member_a["version"])
    asn = create_storage_assignment(member_b["id"], "COLD", 2, member_b["version"])
    assert asn["status"] == "ACTIVE"


# ── Difficulty: compensating_invariant / storage_release_restores_slot_conservation ──

def test_release_restores_unit_used_slots_to_zero(api):
    """PRD 2.9: "when an assignment is released, those same slots are returned.
    This release is a compensating action that restores the slot-conservation
    invariant exactly." A 15-slot waterfall across DryA(10) and DryB(5), once
    released, returns both units' used_slots to 0.

    Design: Difficulty/compensating_invariant/storage_release_restores_slot_conservation
    """
    member = register_member(business_name="M17")
    mo = make_member_operator_headers(member["id"])
    dry_a = create_storage_unit(name="DryA", temp_class="DRY", total_slots=10,
                                temp_min_c=10.0, temp_max_c=25.0)
    dry_b = create_storage_unit(name="DryB", temp_class="DRY", total_slots=10,
                                temp_min_c=10.0, temp_max_c=25.0)
    asn = create_storage_assignment(member["id"], "DRY", 15, member["version"])
    validate_success(api.release_storage_assignment(member["id"], asn["id"], mo), 200)

    unit_a = validate_success(api.get_storage_unit(dry_a["id"], FM), 200)
    unit_b = validate_success(api.get_storage_unit(dry_b["id"], FM), 200)
    assert unit_a["used_slots"] == 0, f"DryA got {unit_a['used_slots']}"
    assert unit_b["used_slots"] == 0, f"DryB got {unit_b['used_slots']}"


def test_active_assignment_holds_slots_before_release(api):
    """PRD 2.9: "When an assignment is created, every unit it touches has its
    used_slots increased by the slots allocated there". Before release a 15-slot
    DRY assignment shows DryA holding 10 and DryB holding 5.

    Design: Difficulty/compensating_invariant/storage_release_restores_slot_conservation
    """
    member = register_member(business_name="M17b")
    dry_a = create_storage_unit(name="DryA2", temp_class="DRY", total_slots=10,
                                temp_min_c=10.0, temp_max_c=25.0)
    dry_b = create_storage_unit(name="DryB2", temp_class="DRY", total_slots=10,
                                temp_min_c=10.0, temp_max_c=25.0)
    create_storage_assignment(member["id"], "DRY", 15, member["version"])
    unit_a = validate_success(api.get_storage_unit(dry_a["id"], FM), 200)
    unit_b = validate_success(api.get_storage_unit(dry_b["id"], FM), 200)
    assert unit_a["used_slots"] == 10
    assert unit_b["used_slots"] == 5


# ── Difficulty: cross_entity_state_dependency / assignment_create_requires_unit_not_quarantined ──

def test_assignment_against_quarantined_unit_rejected(api):
    """PRD 3.9: "if any same-class unit that the waterfall plan would touch is
    itself QUARANTINED, the create is refused with ERR_UNIT_QUARANTINED." A new
    FROZEN assignment whose only matching unit is quarantined is rejected.

    Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_unit_not_quarantined
    """
    member = register_member(business_name="M13")
    v = member["version"]
    frz = create_storage_unit(name="Frz1", temp_class="FROZEN", total_slots=10,
                              temp_min_c=-22.0, temp_max_c=-16.0)
    # Drive the unit to QUARANTINED: two out-of-range readings > 120 min apart.
    api.create_temp_log(frz["id"], {"reading_c": 0.0, "reading_utc": "2026-07-07T10:00:00.000Z"}, CO)
    api.create_temp_log(frz["id"], {"reading_c": 0.0, "reading_utc": "2026-07-07T12:01:00.000Z"}, CO)
    quarantined = validate_success(api.get_storage_unit(frz["id"], FM), 200)
    assert quarantined["compliance_status"] == "QUARANTINED"

    mo = make_member_operator_headers(member["id"])
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "FROZEN", "requested_slots": 2, "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_UNIT_QUARANTINED")


def test_assignment_against_compliant_unit_succeeds(api):
    """PRD 3.9: "The candidates are all storage units of the matching temp_class
    whose compliance_status is not QUARANTINED". Against a COMPLIANT FROZEN unit
    with free slots, the same 2-slot assignment is accepted — isolating the
    unit's compliance_status as the rejection cause in the companion test.

    Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_unit_not_quarantined
    """
    member = register_member(business_name="M13b")
    v = member["version"]
    create_storage_unit(name="Frz1b", temp_class="FROZEN", total_slots=10,
                        temp_min_c=-22.0, temp_max_c=-16.0)
    mo = make_member_operator_headers(member["id"])
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "FROZEN", "requested_slots": 2, "expected_member_version": v,
    }, mo)
    asn = validate_success(res, 201)
    assert asn["status"] == "ACTIVE"


# ── Corner: calculations / storage_fee_premium_discount_applied ──

def test_storage_fee_premium_discount(api):
    """PRD 3.10: "COLD storage is 700 cents per slot per month" and "If the
    member's plan_tier is PREMIUM, a five-percent discount applies". A PREMIUM
    member's COLD 10-slot assignment is gross 7000, discount 350, monthly_fee
    6650.

    Design: Corner/calculations/storage_fee_premium_discount_applied
    """
    member, _ = register_funded_member(amount_cents=0, plan_tier="PREMIUM", business_name="Sf")
    create_storage_unit(name="ColdSf", temp_class="COLD", total_slots=20,
                        temp_min_c=0.0, temp_max_c=4.0)
    v = current_member_version(member["id"])
    asn = create_storage_assignment(member["id"], "COLD", 10, v)
    assert asn["monthly_fee_cents"] == 6650, f"got {asn['monthly_fee_cents']}"


# ── Corner: calculations / storage_waterfall_overflow_into_second_unit ──

def test_waterfall_overflow_into_second_unit(api):
    """PRD 3.9: "The candidates are all storage units of the matching temp_class
    whose compliance_status is not QUARANTINED, considered strictly in ascending
    created_at order (the earliest-created unit fills first...)". A 15-slot DRY
    request fills DryA(10) fully then DryB(5).

    Design: Corner/calculations/storage_waterfall_overflow_into_second_unit
    """
    member = register_member(business_name="Wf")
    wfa = create_storage_unit(name="WfA", temp_class="DRY", total_slots=10,
                              temp_min_c=10.0, temp_max_c=25.0)
    wfb = create_storage_unit(name="WfB", temp_class="DRY", total_slots=10,
                              temp_min_c=10.0, temp_max_c=25.0)
    create_storage_assignment(member["id"], "DRY", 15, member["version"])
    unit_a = validate_success(api.get_storage_unit(wfa["id"], FM), 200)
    unit_b = validate_success(api.get_storage_unit(wfb["id"], FM), 200)
    assert unit_a["used_slots"] == 10
    assert unit_b["used_slots"] == 5


# ── Corner: endpoints / certify_compliant_before_recovery_rejected ──

def test_certify_compliant_before_recovery_rejected(api):
    """PRD 3.11: "A quarantined unit is cleared back to COMPLIANT only by a
    ComplianceOfficer certifying it compliant, which is permitted only when the
    unit is currently QUARANTINED (otherwise ERR_INVALID_STATE) and only when the
    latest temperature reading for the unit is in range (otherwise
    ERR_UNIT_NOT_RECOVERED)". The latest reading is still 9.0 (out of range).

    Design: Corner/endpoints/certify_compliant_before_recovery_rejected
    """
    cold = create_storage_unit(name="ColdNR", temp_class="COLD", total_slots=5,
                               temp_min_c=0.0, temp_max_c=4.0)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-17T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-17T12:01:00.000Z"}, CO)
    res = api.certify_compliant(cold["id"], CO)
    validate_error(res, "ERR_UNIT_NOT_RECOVERED")


# ── Corner: state_machines / temp_excursion_recovery_resets_minutes ──

def test_in_range_reading_recovers_excursion(api):
    """PRD 3.11: "When an in-range reading arrives, excursion_minutes is reset to
    0, and if the unit was in EXCURSION it returns to COMPLIANT." An in-range
    reading before the 120-minute limit recovers the unit.

    Design: Corner/state_machines/temp_excursion_recovery_resets_minutes
    """
    cold = create_storage_unit(name="ColdRec", temp_class="COLD", total_slots=5,
                               temp_min_c=0.0, temp_max_c=4.0)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-13T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 3.0, "reading_utc": "2026-07-13T10:30:00.000Z"}, CO)
    unit = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert unit["compliance_status"] == "COMPLIANT"
    assert unit["excursion_minutes"] == 0


# ── Corner: state_machines / member_close_with_open_obligations_rejected ──

def test_close_member_with_active_assignment_rejected(api):
    """PRD 3.1: "A close is only permitted when the member has wound down its
    obligations: it must have no ACTIVE storage assignments and no CONFIRMED
    future bookings. If either obligation is still open, the close is rejected
    with ERR_MEMBER_HAS_OPEN_OBLIGATIONS."

    Design: Corner/state_machines/member_close_with_open_obligations_rejected
    """
    member = register_member(business_name="Ob")
    create_storage_unit(name="DryOb", temp_class="DRY", total_slots=10,
                        temp_min_c=10.0, temp_max_c=25.0)
    create_storage_assignment(member["id"], "DRY", 2, member["version"])
    v2 = current_member_version(member["id"])
    res = api.close_member(member["id"], {"expected_member_version": v2}, FM)
    validate_error(res, "ERR_MEMBER_HAS_OPEN_OBLIGATIONS")
