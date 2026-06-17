"""Scheduling and booking constraints: validation-priority conflicts, the part-
ready gate, technician double-booking, calibration-bay buffer, and the family of
single-failure business-rule errors (PRD 3.4, 3.6, 3.7)."""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Difficulty rule 5 — schedule_safety_beats_referential_mobile_vs_part_not_ready
# A REPLACE+ADAS work order with NO reserved part, scheduled onto a MOBILE
# appointment, violates both ERR_MOBILE_NOT_ELIGIBLE (pri 8) and
# ERR_PART_NOT_READY (pri 14). PRD 2.8 pins safety (lower priority number) first.
# ---------------------------------------------------------------------------
def test_schedule_mobile_replace_adas_without_part_returns_mobile_not_eligible(api):
    """PRD 3.4: "A REPLACE work order whose recalibration is required — an ADAS
    vehicle — cannot be scheduled onto a MOBILE appointment because recalibration
    needs the shop; such an attempt is rejected with ERR_MOBILE_NOT_ELIGIBLE."
    PRD 2.8: "and finally the domain-specific safety, scheduling, referential, and
    fiscal rules described throughout Section 3."

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_referential_mobile_vs_part_not_ready
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=True, oem="FWPRI1")
    tech = fx.create_technician(can_mobile=True, adas_certified=True, home_state="CA")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    # No part reserved. Book a MOBILE appointment (in-state mobile tech -> booking OK).
    appt = fx.book_appointment(wo["id"], tech["id"], "MOBILE",
                               "2026-06-14T15:00:00Z", "2026-06-14T16:30:00Z")
    resp = api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_MOBILE_NOT_ELIGIBLE)


def test_schedule_mobile_replace_adas_blocks_with_mobile_not_eligible_status_422(api):
    """PRD 3.4: "cannot be scheduled onto a MOBILE appointment because recalibration
    needs the shop; such an attempt is rejected with ERR_MOBILE_NOT_ELIGIBLE."
    The work order remains ASSESSED after the rejection.

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_referential_mobile_vs_part_not_ready
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=True, oem="FWPRI2")
    tech = fx.create_technician(can_mobile=True, adas_certified=True, home_state="CA")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    appt = fx.book_appointment(wo["id"], tech["id"], "MOBILE",
                               "2026-06-14T15:00:00Z", "2026-06-14T16:30:00Z")
    resp = api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_MOBILE_NOT_ELIGIBLE, 422)
    after = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    assert after["status"] == "ASSESSED", f"work order must stay ASSESSED, got {after['status']}"


# ---------------------------------------------------------------------------
# Difficulty rule 5 — complete_safety_beats_fiscal_cure_vs_unpaid
# A CURING REPLACE work order completed before safe_drive_away_at AND unpaid
# violates ERR_CURE_NOT_ELAPSED (pri 10) and ERR_BALANCE_UNPAID (pri 16);
# safety wins.
# ---------------------------------------------------------------------------
def test_complete_curing_before_cure_and_unpaid_returns_cure_not_elapsed(api):
    """PRD 3.7: "For a curing work order, an attempt to complete before
    safe_drive_away_at has elapsed is rejected with ERR_CURE_NOT_ELAPSED."

    Design: Difficulty/priority_pair_validation_conflict/complete_safety_beats_fiscal_cure_vs_unpaid
    """
    # Non-ADAS REPLACE; install at 09:00, temp_c=4 (MILD 120 min, no dry penalty) -> SDAT 11:00.
    ctx = fx.setup_after_finish_install(adas_equipped=False, temp_c=4, humidity_pct=50,
                                        clock="2026-06-13T09:00:00Z")
    wo = ctx["work_order"]
    assert wo["status"] == "CURING"
    # Advance clock to before SDAT and leave the order unpaid.
    fx.set_clock("2026-06-13T10:30:00Z")
    resp = api.complete_work_order(wo["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_CURE_NOT_ELAPSED)


def test_complete_curing_before_cure_keeps_curing_state(api):
    """PRD 3.7: "an attempt to complete before safe_drive_away_at has elapsed is
    rejected with ERR_CURE_NOT_ELAPSED." The work order stays CURING.

    Design: Difficulty/priority_pair_validation_conflict/complete_safety_beats_fiscal_cure_vs_unpaid
    """
    ctx = fx.setup_after_finish_install(adas_equipped=False, temp_c=4, humidity_pct=50,
                                        clock="2026-06-13T09:00:00Z")
    wo = ctx["work_order"]
    fx.set_clock("2026-06-13T10:30:00Z")
    resp = api.complete_work_order(wo["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_CURE_NOT_ELAPSED, 422)
    after = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    assert after["status"] == "CURING", f"work order must stay CURING, got {after['status']}"


# ---------------------------------------------------------------------------
# Difficulty rule 6 — technician_back_to_back_adjacency_boundary
# ---------------------------------------------------------------------------
def test_back_to_back_appointment_same_instant_allowed(api):
    """PRD 3.4: "back-to-back appointments that share an instant (one ending exactly
    when the next begins) are allowed and only a true point of overlap collides".

    Design: Difficulty/boundary_precision_check/technician_back_to_back_adjacency_boundary
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Adj Bay", bay_type="INSTALL")
    # First booked appointment 09:00-10:00.
    wo_a = fx.create_work_order(cust["id"], veh["id"])
    asmt_a = fx.create_assessment(wo_a["id"])
    validate_success(api.accept_assessment(wo_a["id"], {"assessment_id": asmt_a["id"]}, ADVISOR), 200)
    fx.book_appointment(wo_a["id"], tech["id"], "IN_SHOP",
                        "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z", service_bay_id=bay["id"])
    # Second appointment starting exactly at 10:00 must be allowed.
    wo_b = fx.create_work_order(cust["id"], veh["id"])
    asmt_b = fx.create_assessment(wo_b["id"])
    validate_success(api.accept_assessment(wo_b["id"], {"assessment_id": asmt_b["id"]}, ADVISOR), 200)
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo_b["id"], tech["id"], "IN_SHOP",
            "2026-06-13T10:00:00Z", "2026-06-13T11:00:00Z", service_bay_id=bay["id"]),
        ADVISOR)
    validate_success(resp, 201)


def test_one_minute_overlap_appointment_rejected(api):
    """PRD 3.4: "an appointment's half-open window from start_at up to end_at may not
    overlap any other non-cancelled appointment for the same technician ... a
    violation is rejected with ERR_TECHNICIAN_DOUBLE_BOOKED."

    Design: Difficulty/boundary_precision_check/technician_back_to_back_adjacency_boundary
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Adj Bay 2", bay_type="INSTALL")
    wo_a = fx.create_work_order(cust["id"], veh["id"])
    asmt_a = fx.create_assessment(wo_a["id"])
    validate_success(api.accept_assessment(wo_a["id"], {"assessment_id": asmt_a["id"]}, ADVISOR), 200)
    fx.book_appointment(wo_a["id"], tech["id"], "IN_SHOP",
                        "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z", service_bay_id=bay["id"])
    wo_c = fx.create_work_order(cust["id"], veh["id"])
    asmt_c = fx.create_assessment(wo_c["id"])
    validate_success(api.accept_assessment(wo_c["id"], {"assessment_id": asmt_c["id"]}, ADVISOR), 200)
    # Starts at 09:59 -> one minute of overlap with the 09:00-10:00 job.
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo_c["id"], tech["id"], "IN_SHOP",
            "2026-06-13T09:59:00Z", "2026-06-13T10:30:00Z", service_bay_id=bay["id"]),
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


# ---------------------------------------------------------------------------
# Difficulty rule 7 — schedule_blocked_until_part_order_reserved_workorder_to_partorder
# ---------------------------------------------------------------------------
def test_schedule_blocked_until_part_reserved_then_succeeds(api):
    """PRD 3.4: "If the service_decision is REPLACE, a part order for this work order
    must already be in RESERVED; scheduling a replacement whose part is not yet
    reserved is rejected with ERR_PART_NOT_READY."
    PRD 3.4: "A backordered order is later moved to RESERVED by the ShopManager when
    the stock arrives".

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_until_part_order_reserved_workorder_to_partorder
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWGATE1")
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Gate Bay", bay_type="INSTALL")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWGATE1", adas_compatible=False, on_hand_qty=0)
    po = fx.get_success_data(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    assert po["status"] == "BACKORDERED", f"zero-stock order must be BACKORDERED, got {po['status']}"
    appt = fx.book_appointment(wo["id"], tech["id"], "IN_SHOP",
                               "2026-06-15T08:00:00Z", "2026-06-15T09:00:00Z", service_bay_id=bay["id"])
    # First schedule fails: part still BACKORDERED.
    resp_before = api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR)
    validate_error(resp_before, ApiErrorId.ERR_PART_NOT_READY)
    # Receive the part -> RESERVED.
    po_recv = validate_success(api.receive_part_order(po["id"], MANAGER), 200)
    assert po_recv["status"] == "RESERVED", f"receive must yield RESERVED, got {po_recv['status']}"
    # Second schedule succeeds.
    wo_sched = validate_success(api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR), 200)
    assert wo_sched["status"] == "SCHEDULED", f"work order must reach SCHEDULED, got {wo_sched['status']}"


def test_schedule_replace_with_backordered_part_rejected(api):
    """PRD 3.4: "scheduling a replacement whose part is not yet reserved is rejected
    with ERR_PART_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_until_part_order_reserved_workorder_to_partorder
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWGATE2")
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Gate Bay 2", bay_type="INSTALL")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWGATE2", adas_compatible=False, on_hand_qty=0)
    fx.get_success_data(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    appt = fx.book_appointment(wo["id"], tech["id"], "IN_SHOP",
                               "2026-06-15T08:00:00Z", "2026-06-15T09:00:00Z", service_bay_id=bay["id"])
    resp = api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_PART_NOT_READY)


# ---------------------------------------------------------------------------
# Difficulty rule 8 — technician_overlap_no_buffer_half_open
# ---------------------------------------------------------------------------
def test_technician_positive_overlap_rejected(api):
    """PRD 3.4: "an appointment's half-open window from start_at up to end_at may not
    overlap any other non-cancelled appointment for the same technician ... a
    violation is rejected with ERR_TECHNICIAN_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/technician_overlap_no_buffer_half_open
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Ovl Bay", bay_type="INSTALL")
    wo_a = fx.create_work_order(cust["id"], veh["id"])
    asmt_a = fx.create_assessment(wo_a["id"])
    validate_success(api.accept_assessment(wo_a["id"], {"assessment_id": asmt_a["id"]}, ADVISOR), 200)
    fx.book_appointment(wo_a["id"], tech["id"], "IN_SHOP",
                        "2026-06-13T13:00:00Z", "2026-06-13T14:00:00Z", service_bay_id=bay["id"])
    wo_b = fx.create_work_order(cust["id"], veh["id"])
    asmt_b = fx.create_assessment(wo_b["id"])
    validate_success(api.accept_assessment(wo_b["id"], {"assessment_id": asmt_b["id"]}, ADVISOR), 200)
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo_b["id"], tech["id"], "IN_SHOP",
            "2026-06-13T13:30:00Z", "2026-06-13T14:30:00Z", service_bay_id=bay["id"]),
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


def test_technician_non_overlapping_appointment_allowed(api):
    """PRD 3.4: "only a true point of overlap collides" — a fully disjoint window for
    the same technician is accepted.

    Design: Difficulty/resource_temporal_overlap/technician_overlap_no_buffer_half_open
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Ovl Bay 2", bay_type="INSTALL")
    wo_a = fx.create_work_order(cust["id"], veh["id"])
    asmt_a = fx.create_assessment(wo_a["id"])
    validate_success(api.accept_assessment(wo_a["id"], {"assessment_id": asmt_a["id"]}, ADVISOR), 200)
    fx.book_appointment(wo_a["id"], tech["id"], "IN_SHOP",
                        "2026-06-13T13:00:00Z", "2026-06-13T14:00:00Z", service_bay_id=bay["id"])
    wo_b = fx.create_work_order(cust["id"], veh["id"])
    asmt_b = fx.create_assessment(wo_b["id"])
    validate_success(api.accept_assessment(wo_b["id"], {"assessment_id": asmt_b["id"]}, ADVISOR), 200)
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo_b["id"], tech["id"], "IN_SHOP",
            "2026-06-13T15:00:00Z", "2026-06-13T16:00:00Z", service_bay_id=bay["id"]),
        ADVISOR)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Difficulty rule 8 — calibration_bay_overlap_with_15min_buffer
# ---------------------------------------------------------------------------
def test_calibration_bay_buffer_overlap_rejected(api):
    """PRD 3.6: "its window plus a fifteen-minute clearance buffer on each side must
    not overlap any other non-cancelled recalibration in that bay, so two
    recalibrations collide when the gap between them is strictly less than fifteen
    minutes; a violation is rejected with ERR_BAY_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/calibration_bay_overlap_with_15min_buffer
    """
    fx.set_clock("2026-06-13T09:00:00Z")
    cust = fx.create_customer(service_address_state="CA")
    tech = fx.create_technician(can_mobile=False, adas_certified=True, home_state="CA")
    install_bay = fx.create_service_bay(name="Shared Install", bay_type="INSTALL")
    cbay = fx.create_service_bay(name="Shared Calib", bay_type="CALIBRATION")
    th = fx.make_technician_headers(tech["id"])
    veh_p = fx.create_vehicle(cust["id"], adas_equipped=True, glass_part_number="FWBAYP")
    veh_q = fx.create_vehicle(cust["id"], adas_equipped=True, glass_part_number="FWBAYQ")
    wo_p = fx.drive_adas_vehicle_to_awaiting_recalibration(
        cust["id"], veh_p["id"], tech["id"], install_bay["id"], th, "FWBAYP",
        "2026-06-13T07:00:00Z", "2026-06-13T07:30:00Z")
    # First STATIC recalibration in the shared CALIBRATION bay 09:10-09:40.
    rc_p = validate_success(api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo_p["id"], tech["id"], "STATIC",
            "2026-06-13T09:10:00Z", "2026-06-13T09:40:00Z", wo_p["version"],
            service_bay_id=cbay["id"]),
        th), 201)
    assert rc_p["status"] == "SCHEDULED"
    wo_q = fx.drive_adas_vehicle_to_awaiting_recalibration(
        cust["id"], veh_q["id"], tech["id"], install_bay["id"], th, "FWBAYQ",
        "2026-06-13T07:40:00Z", "2026-06-13T08:10:00Z")
    # Second STATIC recalibration 09:50-10:20: gap to first is 10 min (< 15 buffer).
    resp = api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo_q["id"], tech["id"], "STATIC",
            "2026-06-13T09:50:00Z", "2026-06-13T10:20:00Z", wo_q["version"],
            service_bay_id=cbay["id"]),
        th)
    validate_error(resp, ApiErrorId.ERR_BAY_DOUBLE_BOOKED)


def test_calibration_bay_sufficient_gap_allowed(api):
    """PRD 3.6: "two recalibrations collide when the gap between them is strictly less
    than fifteen minutes" — a gap of exactly fifteen minutes does not collide.

    Design: Difficulty/resource_temporal_overlap/calibration_bay_overlap_with_15min_buffer
    """
    fx.set_clock("2026-06-13T09:00:00Z")
    cust = fx.create_customer(service_address_state="CA")
    tech = fx.create_technician(can_mobile=False, adas_certified=True, home_state="CA")
    install_bay = fx.create_service_bay(name="Shared Install 2", bay_type="INSTALL")
    cbay = fx.create_service_bay(name="Shared Calib 2", bay_type="CALIBRATION")
    th = fx.make_technician_headers(tech["id"])
    veh_p = fx.create_vehicle(cust["id"], adas_equipped=True, glass_part_number="FWBAYP2")
    veh_q = fx.create_vehicle(cust["id"], adas_equipped=True, glass_part_number="FWBAYQ2")
    wo_p = fx.drive_adas_vehicle_to_awaiting_recalibration(
        cust["id"], veh_p["id"], tech["id"], install_bay["id"], th, "FWBAYP2",
        "2026-06-13T07:00:00Z", "2026-06-13T07:30:00Z")
    validate_success(api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo_p["id"], tech["id"], "STATIC",
            "2026-06-13T09:10:00Z", "2026-06-13T09:40:00Z", wo_p["version"],
            service_bay_id=cbay["id"]),
        th), 201)
    wo_q = fx.drive_adas_vehicle_to_awaiting_recalibration(
        cust["id"], veh_q["id"], tech["id"], install_bay["id"], th, "FWBAYQ2",
        "2026-06-13T07:40:00Z", "2026-06-13T08:10:00Z")
    # Second recalibration 09:55-10:25: gap to first end (09:40) is exactly 15 min.
    resp = api.create_recalibration_job(
        f.create_recalibration_job_payload(
            wo_q["id"], tech["id"], "STATIC",
            "2026-06-13T09:55:00Z", "2026-06-13T10:25:00Z", wo_q["version"],
            service_bay_id=cbay["id"]),
        th)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Corner validations — adas_vehicle_non_compatible_part_rejected
# ---------------------------------------------------------------------------
def test_adas_vehicle_non_compatible_part_rejected(api):
    """PRD 3.4: "If the target vehicle is ADAS-equipped, the chosen GlassPart must be
    adas_compatible; ordering a non-compatible part for an ADAS vehicle is rejected
    with ERR_ADAS_PART_INCOMPATIBLE."

    Design: Corner/validations/adas_vehicle_non_compatible_part_rejected
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=True, oem="FWADASINC")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWADASINC", adas_compatible=False, on_hand_qty=5)
    resp = api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_ADAS_PART_INCOMPATIBLE)


# ---------------------------------------------------------------------------
# Corner validations — mobile_tech_out_of_state_rejected
# ---------------------------------------------------------------------------
def test_mobile_technician_out_of_state_rejected(api):
    """PRD 3.4: "For a MOBILE appointment, the assigned technician must have
    can_mobile true and a home_state matching the customer's service_address_state;
    otherwise the booking is rejected with ERR_MOBILE_TECH_UNAVAILABLE."

    Design: Corner/validations/mobile_tech_out_of_state_rejected
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWMOB")
    tech = fx.create_technician(can_mobile=True, adas_certified=False, home_state="NV")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo["id"], tech["id"], "MOBILE",
            "2026-06-14T15:00:00Z", "2026-06-14T16:00:00Z"),
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_MOBILE_TECH_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Corner validations — overpayment_rejected
# ---------------------------------------------------------------------------
def test_overpayment_rejected(api):
    """PRD 3.7: "A payment whose amount_cents would push amount_paid_cents above
    total_charge_cents is an overpayment and is rejected with ERR_OVERPAYMENT."

    Design: Corner/validations/overpayment_rejected
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR")  # total 9657
    resp = api.create_payment(f.create_payment_payload(wo["id"], 10000, "CARD"), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


# ---------------------------------------------------------------------------
# Corner validations — complete_unpaid_balance_rejected
# ---------------------------------------------------------------------------
def test_complete_unpaid_repair_rejected(api):
    """PRD 3.7: "an attempt to complete with an unpaid balance is rejected with
    ERR_BALANCE_UNPAID (HTTP 402)."
    PRD 3.7: "it requires the work order to be IN_SERVICE, the service_decision to
    be REPAIR, and the work order to be fully paid."

    Design: Corner/validations/complete_unpaid_balance_rejected
    """
    ctx = fx.setup_in_service(decision="REPAIR", adas_equipped=False)
    wo = ctx["work_order"]
    resp = api.complete_work_order(wo["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_BALANCE_UNPAID, 402)


# ---------------------------------------------------------------------------
# Corner errors — end_before_start_invalid_request
# ---------------------------------------------------------------------------
def test_appointment_end_before_start_rejected(api):
    """PRD 2.8: "the presence and well-typedness of required input fields, including
    that enum fields carry a declared member and that any end_at is strictly after
    its start_at (ERR_INVALID_REQUEST)."

    Design: Corner/errors/end_before_start_invalid_request
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Time Bay", bay_type="INSTALL")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    resp = api.create_service_appointment(
        f.create_service_appointment_payload(
            wo["id"], tech["id"], "IN_SHOP",
            "2026-06-13T10:00:00Z", "2026-06-13T09:00:00Z", service_bay_id=bay["id"]),
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
