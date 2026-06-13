"""Occupational-health slot tests: the half-open collector interval (adjacency
allowed, overlap rejected) versus the buffer-padded closed room interval
(adjacency rejected), and the result cascade that posts an OCC_HEALTH charge
(PRD §3.8).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_provider_headers,
    TEST_USERS,
    create_clinic,
    create_exam_room,
    create_provider,
    create_walk_in,
    set_clock,
    setup_roomed_visit,
)

_ANON = TEST_USERS["anonymous_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]


# ─── boundary_precision_check / occ_slot_half_open_back_to_back_allowed ───

def test_collector_back_to_back_drug_screens_allowed():
    """PRD §3.8: "Because the interval is half-open, two back-to-back orders where
    the new order's start equals the existing order's end do not overlap and are
    allowed — a zero gap is permitted on the collector."

    Design: Difficulty/boundary_precision_check/occ_slot_half_open_back_to_back_allowed
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="OccClinic", exam_room_capacity=2)
    collector = create_provider(clinic["id"], full_name="Collector", credential="NP")
    qe1 = create_walk_in(clinic["id"], chief_complaint="occ1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="occ2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "DRUG_SCREEN", "employer_name": "Acme",
         "scheduled_start": "2026-06-08T10:00:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)

    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "DRUG_SCREEN", "employer_name": "Acme",
         "scheduled_start": "2026-06-08T10:30:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    order = validate_success(res, 201)
    assert order["status"] == "SCHEDULED", (
        f"back-to-back collector order should be SCHEDULED, got {order['status']}")


def test_collector_back_to_back_does_not_error():
    """PRD §3.8: a new collector order is rejected with ERR_SLOT_CONFLICT only when
    "the new start falls before the existing end and the existing start falls before
    the new end"; equal start/end "do not overlap and are allowed".

    Design: Difficulty/boundary_precision_check/occ_slot_half_open_back_to_back_allowed
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="OccClinic2", exam_room_capacity=2)
    collector = create_provider(clinic["id"], full_name="Collector2", credential="NP")
    qe1 = create_walk_in(clinic["id"], chief_complaint="a1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="a2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "DRUG_SCREEN", "employer_name": "Acme",
         "scheduled_start": "2026-06-08T11:00:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "DRUG_SCREEN", "employer_name": "Acme",
         "scheduled_start": "2026-06-08T11:30:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    assert res.status_code == 201, (
        f"zero-gap collector booking must be accepted, got {res.status_code}")


# ─── resource_temporal_overlap / collector_half_open_overlap_rejected ───

def test_collector_overlapping_order_rejected():
    """PRD §3.8: "A new order for a collector is rejected with ERR_SLOT_CONFLICT if
    its interval overlaps any existing SCHEDULED or IN_PROGRESS order on that same
    collector, where overlap means the new start falls before the existing end and
    the existing start falls before the new end."

    Design: Difficulty/resource_temporal_overlap/collector_half_open_overlap_rejected
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="ColOverlapClinic", exam_room_capacity=2)
    collector = create_provider(clinic["id"], full_name="Col", credential="NP")
    qe1 = create_walk_in(clinic["id"], chief_complaint="c1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="c2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "DRUG_SCREEN", "employer_name": "Globex",
         "scheduled_start": "2026-06-08T10:00:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    # 10:15-10:45 overlaps the existing 10:00-10:30 (10:15 < 10:30).
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "DRUG_SCREEN", "employer_name": "Globex",
         "scheduled_start": "2026-06-08T10:15:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    validate_error(res, "ERR_SLOT_CONFLICT")


def test_collector_overlap_with_default_duration_rejected():
    """PRD §3.8: the half-open collector interval runs "from its scheduled_start up
    to but not including scheduled_start plus duration_minutes"; an order starting
    inside an existing slot is rejected with ERR_SLOT_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/collector_half_open_overlap_rejected
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="ColOverlapClinic2", exam_room_capacity=2)
    collector = create_provider(clinic["id"], full_name="Col2", credential="NP")
    qe1 = create_walk_in(clinic["id"], chief_complaint="d1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="d2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "DRUG_SCREEN", "employer_name": "Globex",
         "scheduled_start": "2026-06-08T12:00:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    # 12:10-12:40 overlaps 12:00-12:30.
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "DRUG_SCREEN", "employer_name": "Globex",
         "scheduled_start": "2026-06-08T12:10:00Z", "collector_id": collector["id"],
         "duration_minutes": 30}, _CLERK)
    validate_error(res, "ERR_SLOT_CONFLICT")


# ─── resource_temporal_overlap / room_buffer_padded_overlap_rejected ───

def test_room_back_to_back_rejected_by_buffer():
    """PRD §3.8: "a new room-bound order is rejected with ERR_ROOM_SLOT_CONFLICT if
    the new start falls before the existing end plus fifteen minutes and the
    existing start falls before the new end plus fifteen minutes"; "back-to-back
    room bookings are rejected because the buffer is mandatory."

    Design: Difficulty/resource_temporal_overlap/room_buffer_padded_overlap_rejected
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="RoomOverlapClinic", exam_room_capacity=3)
    room = create_exam_room(clinic["id"], room_label="PROC1", room_type="PROCEDURE")
    col_a = create_provider(clinic["id"], full_name="ColA", credential="MD")
    col_b = create_provider(clinic["id"], full_name="ColB", credential="DO")
    qe1 = create_walk_in(clinic["id"], chief_complaint="r1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="r2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "PHYSICAL", "employer_name": "Initech",
         "scheduled_start": "2026-06-08T10:00:00Z", "collector_id": col_a["id"],
         "room_id": room["id"], "duration_minutes": 30}, _CLERK)
    # New 10:30-11:00 in same room: 10:30 < existing end 10:30 + 15min -> rejected.
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "PHYSICAL", "employer_name": "Initech",
         "scheduled_start": "2026-06-08T10:30:00Z", "collector_id": col_b["id"],
         "room_id": room["id"], "duration_minutes": 30}, _CLERK)
    validate_error(res, "ERR_ROOM_SLOT_CONFLICT")


def test_room_within_buffer_rejected():
    """PRD §3.8: "Two room orders are therefore only allowed when separated by at
    least the fifteen-minute buffer"; an order ten minutes after the existing end
    falls within the mandatory buffer and is rejected with ERR_ROOM_SLOT_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/room_buffer_padded_overlap_rejected
    """
    set_clock("2026-06-08T09:00:00Z")
    clinic = create_clinic(name="RoomOverlapClinic2", exam_room_capacity=3)
    room = create_exam_room(clinic["id"], room_label="PROC2", room_type="PROCEDURE")
    col_a = create_provider(clinic["id"], full_name="ColA2", credential="MD")
    col_b = create_provider(clinic["id"], full_name="ColB2", credential="DO")
    qe1 = create_walk_in(clinic["id"], chief_complaint="rr1")
    qe2 = create_walk_in(clinic["id"], chief_complaint="rr2")
    api_client.create_occ_health_order(
        {"queue_entry_id": qe1["id"], "order_type": "PHYSICAL", "employer_name": "Initech",
         "scheduled_start": "2026-06-08T13:00:00Z", "collector_id": col_a["id"],
         "room_id": room["id"], "duration_minutes": 30}, _CLERK)
    # Existing ends 13:30; new 13:40 is within the 15-min buffer (13:40 < 13:30+15).
    res = api_client.create_occ_health_order(
        {"queue_entry_id": qe2["id"], "order_type": "PHYSICAL", "employer_name": "Initech",
         "scheduled_start": "2026-06-08T13:40:00Z", "collector_id": col_b["id"],
         "room_id": room["id"], "duration_minutes": 30}, _CLERK)
    validate_error(res, "ERR_ROOM_SLOT_CONFLICT")


# ─── endpoints / occ_health_result_creates_occ_charge_side_effect ───

def test_occ_result_creates_occ_health_charge():
    """PRD §3.8: recording a result "sets that result and, if a visit exists for
    the same queue entry, cascades by creating an OCC_HEALTH-source charge on that
    visit (employer-billed, and thus excluded from the patient's responsibility)."

    Design: Corner/endpoints/occ_health_result_creates_occ_charge_side_effect
    """
    set_clock("2026-06-08T09:00:00Z")
    setup = setup_roomed_visit(esi_level=4, clinic_overrides={"self_pay_discount_pct": 0.30})
    clinic_id = setup["clinic"]["id"]
    qe_id = setup["queue_entry"]["id"]
    provider = setup["provider"]
    phdr = make_provider_headers(provider["id"])
    order = validate_success(api_client.create_occ_health_order(
        {"queue_entry_id": qe_id, "order_type": "DRUG_SCREEN", "employer_name": "Stark",
         "scheduled_start": "2026-06-08T09:00:00Z", "collector_id": provider["id"],
         "duration_minutes": 20}, _CLERK), 201)
    api_client.start_occ_health_order(order["id"], phdr)

    completed = validate_success(
        api_client.result_occ_health_order(order["id"], {"result": "NEGATIVE"}, phdr), 200)
    assert completed["status"] == "COMPLETED" and completed["result"] == "NEGATIVE"

    charges, _meta = validate_paginated(api_client.list_charges(setup["visit"]["id"], phdr))
    occ_charges = [c for c in charges if c["source_type"] == "OCC_HEALTH"]
    assert len(occ_charges) == 1, (
        f"result cascade should create exactly one OCC_HEALTH charge, got {len(occ_charges)}")
