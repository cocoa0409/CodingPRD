"""Seasonal storage, technician scheduling, test-ride waivers, and warranty/recall
claims: bay overlap, the buffered technician interval, winterization prep orders,
storage-fee finalization, waiver gating, and warranty settlement of repair orders.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer_payload, create_unit_payload, create_repair_order_payload,
    create_storage_agreement_payload, create_test_ride_waiver_payload,
    create_warranty_claim_payload, create_service_line_payload,
    create_part_line_payload, TEST_USERS,
    create_customer, create_in_stock_unit, create_technician, create_storage_bay,
    create_part, set_clock,
    setup_reserved_storage_agreement, setup_checked_in_storage_agreement,
    setup_signed_waiver, setup_delivered_unit, setup_warranty_ro_on_delivered_unit,
)

SM = TEST_USERS["sales_manager_headers"]
FM = TEST_USERS["finance_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PC = TEST_USERS["parts_clerk_headers"]
DP = TEST_USERS["dealer_principal_headers"]


# ─── Storage bay half-open overlap (queue A) ──────────────────────────────────
def test_storage_bay_overlapping_window_rejected(api):
    """PRD 3.10: "Checking in advances RESERVED to CHECKED_IN but only if no other
    CHECKED_IN agreement occupies the same storage_bay_id over an overlapping
    window; the storage window is half-open on [period_start, period_end), so two
    agreements that merely touch at an endpoint do not overlap, while any true
    overlap is rejected with ERR_BAY_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/storage_bay_half_open_interval_overlap_rejected
    """
    bay, cust_a, unit_a, agr_a = setup_checked_in_storage_agreement(
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-03-01T00:00:00.000Z")
    _, _, _, agr_b = setup_reserved_storage_agreement(
        bay_id=bay["id"], clock=None,
        period_start="2026-02-15T00:00:00.000Z",
        period_end="2026-04-01T00:00:00.000Z")
    res = api.check_in_storage_agreement(agr_b["id"], SA)
    validate_error(res, "ERR_BAY_DOUBLE_BOOKED")
    agr_b_after = validate_success(api.get_storage_agreement(agr_b["id"], SA), 200)
    assert agr_b_after["status"] == "RESERVED"


def test_storage_bay_adjacent_window_allowed(api):
    """PRD 3.10: "the storage window is half-open on [period_start, period_end), so
    two agreements that merely touch at an endpoint do not overlap, while any true
    overlap is rejected with ERR_BAY_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/storage_bay_half_open_interval_overlap_rejected
    """
    bay, cust_a, unit_a, agr_a = setup_checked_in_storage_agreement(
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-03-01T00:00:00.000Z")
    # Agreement B starts exactly where A ends -> half-open, no overlap.
    _, _, _, agr_b = setup_reserved_storage_agreement(
        bay_id=bay["id"], clock=None,
        period_start="2026-03-01T00:00:00.000Z",
        period_end="2026-05-01T00:00:00.000Z")
    checked_in = validate_success(api.check_in_storage_agreement(agr_b["id"], SA), 200)
    assert checked_in["status"] == "CHECKED_IN"


# ─── Technician buffered interval (queue A) ───────────────────────────────────
def test_technician_buffer_gap_conflict_rejected(api):
    """PRD 3.6: "Before the order is created, the platform checks the assigned
    technician's schedule: if the requested appointment window — taken as a closed
    interval and extended by that technician's cleanup_buffer_minutes gap —
    overlaps any existing repair-order window for the same technician, the request
    is rejected with ERR_TECH_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/technician_appointment_buffer_gap_conflict_rejected
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cust = create_customer()
    unit = create_in_stock_unit(category="ATV")
    tech = create_technician(cleanup_buffer_minutes=30)
    validate_success(api.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start="2026-06-06T09:00:00.000Z",
                                    appointment_end="2026-06-06T10:00:00.000Z",
                                    authorized_amount_cents=50_000), SA), 201)
    # RO-2 starts 15 min after RO-1 end -> inside the 30-min buffer.
    res = api.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start="2026-06-06T10:15:00.000Z",
                                    appointment_end="2026-06-06T11:00:00.000Z",
                                    authorized_amount_cents=50_000), SA)
    validate_error(res, "ERR_TECH_SCHEDULE_CONFLICT")


def test_technician_appointment_outside_buffer_allowed(api):
    """PRD 3.6: "if the requested appointment window — taken as a closed interval
    and extended by that technician's cleanup_buffer_minutes gap — overlaps any
    existing repair-order window for the same technician, the request is rejected
    with ERR_TECH_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/technician_appointment_buffer_gap_conflict_rejected
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cust = create_customer()
    unit = create_in_stock_unit(category="ATV")
    tech = create_technician(cleanup_buffer_minutes=30)
    validate_success(api.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start="2026-06-06T09:00:00.000Z",
                                    appointment_end="2026-06-06T10:00:00.000Z",
                                    authorized_amount_cents=50_000), SA), 201)
    # RO-2 starts 31 min after RO-1 end -> beyond the 30-min buffer.
    ro2 = validate_success(api.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start="2026-06-06T10:31:00.000Z",
                                    appointment_end="2026-06-06T11:00:00.000Z",
                                    authorized_amount_cents=50_000), SA), 201)
    assert ro2["work_status"] == "OPEN"


# ─── Winterization & storage fee (queue B) ────────────────────────────────────
def test_checkin_with_winterization_mints_prep_ro(api):
    """PRD 3.10: "If the agreement includes_winterization, checking in also mints a
    preparation repair order for the stored unit (a non-warranty order in
    work_status OPEN) and records its id on prep_repair_order_id."

    Design: Corner/state_machines/storage_checkin_with_winterization_mints_prep_ro
    """
    bay, cust, unit, agr = setup_checked_in_storage_agreement(includes_winterization=True)
    assert agr["status"] == "CHECKED_IN"
    assert agr["prep_repair_order_id"] is not None
    prep = validate_success(api.get_repair_order(agr["prep_repair_order_id"], SA), 200)
    assert prep["work_status"] == "OPEN"


def test_checkout_blocked_when_prep_ro_open(api):
    """PRD 3.10: "If the agreement has a prep_repair_order_id, that preparation
    order's work_status must be WORK_COMPLETE or CANCELLED before check-out is
    allowed; otherwise check-out is rejected with ERR_PREP_RO_OPEN."

    Design: Corner/state_machines/storage_checkout_blocked_when_prep_ro_open
    """
    bay, cust, unit, agr = setup_checked_in_storage_agreement(includes_winterization=True)
    res = api.check_out_storage_agreement(agr["id"], SA)
    validate_error(res, "ERR_PREP_RO_OPEN")
    agr_after = validate_success(api.get_storage_agreement(agr["id"], SA), 200)
    assert agr_after["status"] == "CHECKED_IN"


def test_storage_fee_computed_on_checkout_with_winterization(api):
    """PRD 3.10: "take the ceiling of the seconds between period_start and
    period_end divided by 86400 to get the span in whole days, then take the
    ceiling of that span divided by 30 to get the number of months ... and multiply
    the months by monthly_rate_cents to get the base. When includes_winterization
    is true, a winterization fee of 14900 cents ($149.00) is added to that base."

    Design: Corner/calculations/storage_fee_computed_on_checkout_with_winterization
    """
    bay, cust, unit, agr = setup_checked_in_storage_agreement(
        includes_winterization=True,
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-04-15T00:00:00.000Z",
        monthly_rate_cents=12000)
    # Cancel the prep RO so check-out is allowed.
    validate_success(api.cancel_repair_order(agr["prep_repair_order_id"], SA), 200)
    set_clock("2026-04-15T00:00:00.000Z")
    checked_out = validate_success(api.check_out_storage_agreement(agr["id"], SA), 200)
    # 104 days -> ceil(104/30)=4 months * 12000 = 48000 + 14900 = 62900
    assert checked_out["storage_fee_cents"] == 62900
    assert checked_out["status"] == "CHECKED_OUT"


# ─── Test-ride waivers (queue A priority pair + queue B) ───────────────────────
def test_log_ride_on_delivered_unit_rejected_not_rideable(api):
    """PRD 3.11: "If the waiver is still within its validity window, the referenced
    unit must be in IN_STOCK or ON_HOLD status to be ridden, otherwise the ride is
    rejected with ERR_UNIT_NOT_RIDEABLE."

    Design: Difficulty/priority_pair_validation_conflict/log_ride_safety_beats_referential_unit_not_rideable
    """
    # The waiver is SIGNED and within its validity window, so the PRD's unit-status
    # safety check runs; the unit is DELIVERED (not IN_STOCK/ON_HOLD) -> ERR_UNIT_NOT_RIDEABLE.
    set_clock("2026-06-01T00:00:00.000Z")
    cust, unit, deal = setup_delivered_unit(clock="2026-06-01T00:00:00.000Z")
    waiver = validate_success(api.create_test_ride_waiver(
        create_test_ride_waiver_payload(cust["id"], unit["id"],
                                        valid_until="2026-06-30T00:00:00.000Z"), SM), 201)
    res = api.log_ride(waiver["id"], SM)
    validate_error(res, "ERR_UNIT_NOT_RIDEABLE")


def test_log_ride_not_rideable_leaves_waiver_signed(api):
    """PRD 3.11: "If the waiver is still within its validity window, the referenced
    unit must be in IN_STOCK or ON_HOLD status to be ridden, otherwise the ride is
    rejected with ERR_UNIT_NOT_RIDEABLE."

    Design: Difficulty/priority_pair_validation_conflict/log_ride_safety_beats_referential_unit_not_rideable
    """
    set_clock("2026-06-01T00:00:00.000Z")
    cust, unit, deal = setup_delivered_unit(clock="2026-06-01T00:00:00.000Z")
    waiver = validate_success(api.create_test_ride_waiver(
        create_test_ride_waiver_payload(cust["id"], unit["id"],
                                        valid_until="2026-06-30T00:00:00.000Z"), SM), 201)
    res = api.log_ride(waiver["id"], SM)
    # The unit-status safety check fires on the SIGNED, unexpired waiver.
    validate_error(res, "ERR_UNIT_NOT_RIDEABLE")
    waiver_after = validate_success(api.get_test_ride_waiver(waiver["id"], SM), 200)
    # The rejection does not move the waiver out of SIGNED (only expiry does).
    assert waiver_after["status"] == "SIGNED"


def test_log_ride_after_valid_until_marks_expired(api):
    """PRD 3.11: "If the current clock is at or after the waiver's valid_until, the
    waiver is moved to EXPIRED and the ride is rejected with ERR_WAIVER_EXPIRED;
    reaching the expiry instant exactly is treated as expired."

    Design: Corner/state_machines/log_ride_after_valid_until_marks_expired
    """
    cust, unit, waiver = setup_signed_waiver(valid_until="2026-06-10T00:00:00.000Z",
                                             clock="2026-06-01T00:00:00.000Z")
    set_clock("2026-06-11T00:00:00.000Z")
    res = api.log_ride(waiver["id"], SM)
    validate_error(res, "ERR_WAIVER_EXPIRED")
    waiver_after = validate_success(api.get_test_ride_waiver(waiver["id"], SM), 200)
    assert waiver_after["status"] == "EXPIRED"


def test_log_ride_happy_path_with_signed_waiver(api):
    """PRD 3.11: "If the waiver is still within its validity window, the referenced
    unit must be in IN_STOCK or ON_HOLD status to be ridden, otherwise the ride is
    rejected with ERR_UNIT_NOT_RIDEABLE. When both conditions are satisfied, the
    waiver advances from SIGNED to RIDE_LOGGED."

    Design: Corner/state_machines/log_ride_happy_path_with_signed_waiver
    """
    cust, unit, waiver = setup_signed_waiver(valid_until="2026-06-30T00:00:00.000Z",
                                             clock="2026-06-01T00:00:00.000Z")
    set_clock("2026-06-05T00:00:00.000Z")
    logged = validate_success(api.log_ride(waiver["id"], SM), 200)
    assert logged["status"] == "RIDE_LOGGED"


# ─── Warranty / recall claims (queue A cross-entity + queue B) ─────────────────
def test_warranty_approve_requires_unit_delivered(api):
    """PRD 3.12: "Approving a SUBMITTED claim requires that the referenced unit be
    in DELIVERED status, otherwise it is rejected with ERR_UNIT_NOT_DELIVERED."

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_unit_delivered
    """
    unit = create_in_stock_unit(category="SNOWMOBILE")
    claim = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(unit["id"], "WARRANTY"), SA), 201)
    res = api.approve_warranty_claim(claim["id"], DP)
    validate_error(res, "ERR_UNIT_NOT_DELIVERED")
    claim_after = validate_success(api.get_warranty_claim(claim["id"], DP), 200)
    assert claim_after["status"] == "SUBMITTED"


def test_warranty_approve_on_in_stock_leaves_submitted(api):
    """PRD 3.12: "Approving a SUBMITTED claim requires that the referenced unit be
    in DELIVERED status, otherwise it is rejected with ERR_UNIT_NOT_DELIVERED."

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_unit_delivered
    """
    unit = create_in_stock_unit(category="SNOWMOBILE")
    claim = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(unit["id"], "WARRANTY"), SA), 201)
    api.approve_warranty_claim(claim["id"], DP)
    claim_after = validate_success(api.get_warranty_claim(claim["id"], DP), 200)
    assert claim_after["status"] == "SUBMITTED"


def test_recall_claim_amount_is_labor_only(api):
    """PRD 3.12: "For a RECALL, the manufacturer pays labor only, so the claimed
    amount is the referenced order's labor_total_cents."

    Design: Corner/calculations/warranty_recall_claim_amount_labor_only
    """
    cust, unit, tech, ro, part = setup_warranty_ro_on_delivered_unit(
        flat_rate_hours=2.0, reserve_part_qty=2, clock="2026-06-01T00:00:00.000Z")
    # warranty rate 9000/hr * 2.0h = 18000 labor; RECALL excludes parts.
    claim = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(unit["id"], "RECALL",
                                      repair_order_id=ro["id"]), SA), 201)
    assert claim["claim_amount_cents"] == 18000


def test_warranty_pay_settles_linked_ro_billing(api):
    """PRD 3.12: "Paying an APPROVED claim moves it to the terminal PAID; and if the
    claim names a repair order whose billing_status is UNBILLED and whose
    work_status is WORK_COMPLETE, paying the claim settles that order by moving its
    billing_status directly to PAID — the warranty payment pays the repair order."

    Design: Corner/state_machines/warranty_pay_settles_linked_ro_billing
    """
    cust, unit, tech, ro, part = setup_warranty_ro_on_delivered_unit(
        flat_rate_hours=2.0, reserve_part_qty=0, clock="2026-06-01T00:00:00.000Z")
    claim = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(unit["id"], "WARRANTY",
                                      repair_order_id=ro["id"]), SA), 201)
    validate_success(api.approve_warranty_claim(claim["id"], DP), 200)
    paid = validate_success(api.pay_warranty_claim(claim["id"], DP), 200)
    assert paid["status"] == "PAID"
    ro_after = validate_success(api.get_repair_order(ro["id"], SA), 200)
    assert ro_after["billing_status"] == "PAID"
