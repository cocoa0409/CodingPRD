"""Corner tests: blood-unit lifecycle, labeling validations, inventory reconciliation,
OCC booking, scheduled expiry sweeps, RBAC, and immediate consistency.

Queue B sections: state_machines, validations, endpoints, rbac,
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    get_success_data,
    create_blood_unit_payload, create_test_result_payload, create_inventory_bucket_payload,
    create_recall_event_payload, advance_clock_payload, create_deferral_payload,
    create_center, create_donor, create_slot, book_appointment, make_donor_headers,
    setup_collected_donation, setup_labeled_unit, setup_available_unit,
    raise_deferral,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]
LAB = TEST_USERS["lab_technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ─── state_machines / reserve_terminal_issued_unit ────────────────────────────
def test_reserve_issued_terminal_unit_returns_not_available(api):
    """PRD §3.7: "The states DISCARDED, RECALLED, ISSUED, and EXPIRED are terminal."
    PRD §3.7: "Reserving a unit is an InventoryManager action requiring the unit to be
    AVAILABLE, else ERR_UNIT_NOT_AVAILABLE ..."

    An ISSUED (terminal) unit cannot be reserved -> ERR_UNIT_NOT_AVAILABLE (409).

    Design: Corner/state_machines/reserve_terminal_issued_unit_returns_not_available
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(din="DIN-ISS-001")
    get_success_data(api.reserve_blood_unit(unit["id"], INV))
    get_success_data(api.issue_blood_unit(unit["id"], INV))

    res = api.reserve_blood_unit(unit["id"], INV)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE", expected_status=409)


# ─── validations / duplicate_din_within_center ────────────────────────────────
def test_duplicate_din_within_center_returns_duplicate_din(api):
    """PRD §3.7: "The din must be unique among all blood units at the center; a duplicate
    is rejected with ERR_DUPLICATE_DIN."

    Labeling a second unit with a DIN already used at the center -> ERR_DUPLICATE_DIN (409).

    Design: Corner/validations/duplicate_din_within_center_returns_duplicate_din
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    get_success_data(api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="RBC", din="DIN-DUP-1"), LAB))
    # A second unit on the same WHOLE donation with a duplicate DIN (PLASMA is a valid
    # component for a WHOLE donation, so only the DIN constraint should fire).
    res = api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="PLASMA", din="DIN-DUP-1"), LAB)
    validate_error(res, "ERR_DUPLICATE_DIN", expected_status=409)


# ─── validations / component_type_mismatch ────────────────────────────────────
def test_component_type_mismatch_plasma_donation_rbc_unit(api):
    """PRD §3.7: "it must be compatible with the parent donation's donation_type: a WHOLE
    donation may yield RBC, PLASMA, or WHOLE_BLOOD; a PLASMA donation may yield only PLASMA;
    and a PLATELET donation may yield only PLATELET. An incompatible component is rejected
    with ERR_COMPONENT_TYPE_MISMATCH (HTTP 422)."

    Labeling an RBC unit from a PLASMA donation -> ERR_COMPONENT_TYPE_MISMATCH (422).

    Design: Corner/validations/component_type_mismatch_plasma_donation_rbc_unit
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="PLASMA", volume_ml=600,
        screening_overrides={"weight_kg": 75}, donor_overrides={"weight_kg": 75, "blood_type": "O_POS"})
    res = api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="RBC", din="DIN-MM-001"), LAB)
    validate_error(res, "ERR_COMPONENT_TYPE_MISMATCH", expected_status=422)


# ─── validations / reserve_expired_unit ───────────────────────────────────────
def test_reserve_expired_unit_is_rejected(api):
    """PRD §3.7: "Reserving a unit is an InventoryManager action requiring the unit to be
    AVAILABLE, else ERR_UNIT_NOT_AVAILABLE, and requiring the center's current_utc to be
    strictly before the unit's expires_at, else ERR_UNIT_EXPIRED."
    PRD §3.1: "The second sweep examines every AVAILABLE blood unit: any whose expires_at
    is at or before the new current_utc transitions from AVAILABLE to EXPIRED ..."

    An AVAILABLE RBC unit (expires 2025-02-12) after a clock advance to 2025-03-01 is past
    expiry: the clock sweep makes it EXPIRED, so a reserve attempt is rejected. Because the
    PRD's expiry sweep and the reserve-time expiry guard both apply, a PRD-only reader could
    reach either ERR_UNIT_NOT_AVAILABLE (already swept) or ERR_UNIT_EXPIRED — both are
    rejections, so accept either.

    Design: Corner/validations/reserve_expired_unit_returns_unit_expired
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-EXP-001", donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-03-01T00:00:00.000Z"), ADMIN))

    res = api.reserve_blood_unit(unit["id"], INV)
    validate_error_is_one_of(res, ["ERR_UNIT_EXPIRED", "ERR_UNIT_NOT_AVAILABLE"])
    unit_after = validate_success(api.get_blood_unit(unit["id"], INV), 200)
    assert unit_after["status"] == "EXPIRED", "clock sweep moves the past-expiry unit to EXPIRED"


# ─── endpoints / get_donation_returns_stored_donation ─────────────────────────
def test_get_donation_returns_stored_collected_donation(api):
    """PRD §3.6: "A Donation row is created in COLLECTED status with its appointment_id
    recorded and its donor_id, center_id, and donation_type copied from the appointment,
    and its collected_at set to the center's current_utc."

    GET returns the COLLECTED donation with donation_type WHOLE (copied from the appointment)
    and collected_at equal to current_utc at collection (2025-01-01).

    Design: Corner/endpoints/get_donation_returns_stored_donation
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    fetched = validate_success(api.get_donation(donation["id"], LAB), 200)
    assert fetched["donation_type"] == "WHOLE"
    assert fetched["status"] == "COLLECTED"
    assert fetched["collected_at"] == "2025-01-01T00:00:00.000Z"


# ─── endpoints / list_blood_units_filtered_by_status_available ────────────────
def test_list_blood_units_filtered_by_status_available(api):
    """PRD §3.6: "every QUARANTINED blood unit of that donation is released to AVAILABLE"

    A WHOLE donation labeled with an RBC and a PLASMA unit, both released by one NEGATIVE
    test, both appear under a status=AVAILABLE filter.

    Design: Corner/endpoints/list_blood_units_filtered_by_status_available
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    get_success_data(api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="RBC", din="DIN-AVL-001"), LAB))
    get_success_data(api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="PLASMA", din="DIN-QUA-001"), LAB))
    get_success_data(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB))

    data, meta = validate_paginated(
        api.list_blood_units(INV, params={"center_id": center["id"], "status": "AVAILABLE"}))
    assert all(u["status"] == "AVAILABLE" for u in data), "filter returns only AVAILABLE units"
    assert meta["total_count"] == 2, "both released units are AVAILABLE"


# ─── rbac / donor_cannot_label_blood_unit ─────────────────────────────────────
def test_donor_cannot_label_blood_unit(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    PRD §2.1: "A LabTechnician records infectious-disease test results, labels blood units,
    and logs adverse reactions."

    A Donor calling the LabTechnician-exclusive labeling endpoint -> ERR_INSUFFICIENT_PERMISSIONS.

    Design: Corner/rbac/donor_cannot_label_blood_unit
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    res = api.create_blood_unit(
        create_blood_unit_payload(donation["id"], component="RBC", din="DIN-RBAC-001"),
        make_donor_headers(donor["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ─── rbac / lab_technician_cannot_open_recall_event ───────────────────────────
def test_lab_technician_cannot_open_recall_event(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    PRD §2.1: "An InventoryManager drives the blood-unit lifecycle (reserve, unreserve,
    issue), initializes inventory buckets, and opens recall/lookback events."

    A LabTechnician calling the InventoryManager-exclusive recall endpoint
    -> ERR_INSUFFICIENT_PERMISSIONS (403).

    Design: Corner/rbac/lab_technician_cannot_open_recall_event
    """
    center = create_center(clock=None)
    donor = create_donor(center["id"], full_name="Recall Donor")
    res = api.create_recall_event(
        create_recall_event_payload(center["id"], donor["id"], reason="OTHER", lookback_days=30), LAB)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ─── cross_cutting / occ_correct_slot_version_books_successfully ──────────────
def test_booking_with_correct_slot_version_succeeds_and_bumps_version(api):
    """PRD §3.3: "When booking succeeds, the appointment's center_id and donation_type are
    copied from the slot, its status is set to SCHEDULED, and its booked_at is set to the
    center's current_utc. The slot's booked_count is incremented by one, its version is
    incremented by one ..."

    Booking with expected_slot_version equal to the slot's current version succeeds (201)
    and bumps the slot's version from 1 to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_slot_version_books_successfully
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="OCC OK")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T18:00:00.000Z", capacity=5)
    assert slot["version"] == 1

    appt = validate_success(api.create_appointment(
        {"donor_id": donor["id"], "slot_id": slot["id"], "expected_slot_version": slot["version"]}, NURSE), 201)
    assert appt["status"] == "SCHEDULED"
    slot_after = validate_success(api.get_slot(slot["id"], NURSE), 200)
    assert slot_after["version"] == 2 and slot_after["booked_count"] == 1


# ─── cross_cutting / occ_stale_slot_version_rejected_412 ─────────────────────
def test_booking_with_stale_slot_version_rejected_412(api):
    """PRD §2.7: "If a writer has already booked the slot since the client last read it —
    legitimately bumping the slot's booked_count and advancing its version — then the
    client's view of remaining capacity is stale, and the expected_slot_version will no
    longer match the slot's current version. In that case the booking is rejected with
    ERR_STALE_SLOT_VERSION at HTTP 412, before any capacity or slot-state check runs ..."

    Donor A books (slot version 1 -> 2); Donor B then books still passing version 1 (stale)
    -> ERR_STALE_SLOT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_slot_version_rejected_412
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor_a = create_donor(center["id"], full_name="Donor A", blood_type="O_POS")
    donor_b = create_donor(center["id"], full_name="Donor B", blood_type="A_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T18:00:00.000Z", capacity=5)
    stale_version = slot["version"]
    get_success_data(api.create_appointment(
        {"donor_id": donor_a["id"], "slot_id": slot["id"], "expected_slot_version": stale_version}, NURSE))

    res = api.create_appointment(
        {"donor_id": donor_b["id"], "slot_id": slot["id"], "expected_slot_version": stale_version}, NURSE)
    validate_error(res, "ERR_STALE_SLOT_VERSION", expected_status=412)


# ─── cross_cutting / inventory_derived_count_reconciles_after_release ─────────
def test_inventory_count_reconciles_to_one_after_release(api):
    """PRD §2.8: "These counts are maintained incrementally by the unit state-machine side
    effects, but they are an invariant: at every moment the stored counts must equal a fresh
    recount over the underlying unit rows."
    PRD §2.8: "available_count equals the number of that center's blood units in AVAILABLE
    status with that blood type and component ..."

    After a NEGATIVE test releases one O_POS/RBC unit, the matching bucket's available_count
    reconciles to exactly 1.

    Design: Corner/cross_cutting_complexity_layers/inventory_derived_count_reconciles_after_release
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-REC-9", donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    bucket = get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    fetched = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert fetched["available_count"] == 1, "live recount over BloodUnit rows == 1"


# ─── cross_cutting / available_unit_auto_expires_on_clock_sweep ──────────────
def test_available_unit_auto_expires_on_clock_sweep(api):
    """PRD §3.1: "The second sweep examines every AVAILABLE blood unit: any whose expires_at
    is at or before the new current_utc transitions from AVAILABLE to EXPIRED, and the
    matching inventory bucket's available_count is decremented by one for each such unit."
    PRD §3.7: "For RBC, PLASMA, and WHOLE_BLOOD the expiry is collection-anchored and fixed
    at labeling: expires_at is the collected_at plus the component's shelf life — 42 days
    for RBC, 365 days for PLASMA, and 35 days for WHOLE_BLOOD ..."

    A released WHOLE_BLOOD unit collected 2025-01-01 (expires 2025-02-05) is swept to
    EXPIRED when the clock advances to 2025-02-05 (>=).

    Design: Corner/cross_cutting_complexity_layers/available_unit_auto_expires_on_clock_sweep
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        component="WHOLE_BLOOD", din="DIN-WB-001", donor_overrides={"blood_type": "O_POS", "weight_kg": 75})
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-02-05T00:00:00.000Z"), ADMIN))

    unit_after = validate_success(api.get_blood_unit(unit["id"], INV), 200)
    assert unit_after["status"] == "EXPIRED", "current_utc 2025-02-05 >= expires_at 2025-02-05"


# ─── consistency_model / immediate_visibility_of_eligibility_after_deferral ───
def test_eligibility_flips_immediately_after_deferral(api):
    """PRD §2.8: "A donor's eligibility_status is recomputed from their active deferrals and
    their age relative to current_utc whenever a deferral is created, expires, or is lifted,
    and on every clock advance."
    PRD §3.2: "Raising a deferral recomputes the donor's eligibility_status to TEMP_DEFERRED
    or PERM_DEFERRED as appropriate."

    Raising a TEMPORARY deferral immediately makes the donor TEMP_DEFERRED on the next read.

    Design: Corner/consistency_model/immediate_visibility_of_eligibility_after_deferral
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Imm Donor")
    assert donor["eligibility_status"] == "ELIGIBLE"
    raise_deferral(donor["id"], category="HEMOGLOBIN", kind="TEMPORARY",
                   reason="low iron", duration_days=90)

    after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert after["eligibility_status"] == "TEMP_DEFERRED", "deferral flips eligibility immediately"
