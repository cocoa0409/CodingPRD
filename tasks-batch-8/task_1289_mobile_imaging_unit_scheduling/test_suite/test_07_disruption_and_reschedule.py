"""Day-level disruption: breakdowns, cancellation fees, interruption, and the
reschedule chain with credit/scan-count conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_day_to_bundle,
    add_site_day,
    assign_staffing,
    book_appointment,
    book_and_complete_appointment,
    complete_appointment_flow,
    complete_site_day,
    create_appointment_payload,
    create_breakdown_payload,
    create_technologist,
    create_unit,
    drive_day_to_in_service,
    get_day_statement,
    get_success_data,
    make_facility_coordinator_headers,
    make_technologist_headers,
    publish_plan,
    register_and_transmit_study,
    report_breakdown,
    reschedule_day,
    set_clock,
    setup_bookable_day,
    setup_in_service_day,
    setup_plan_context,
    setup_published_target_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

def test_breakdown_minor_severity_keeps_day_in_service(api):
    """PRD §3.6: "A `MINOR` breakdown cascades to nothing — the day continues."
    PRD §3.9: "Exactly one statement per site day is auto-created the moment
    the day completes, is cancelled, or is interrupted".

    Design: Corner/state_machines/breakdown_minor_severity_keeps_day_in_service
    """
    bundle = setup_in_service_day()
    day = bundle["site_day"]
    tech = bundle["technologist"]

    bd = report_breakdown(
        bundle["unit"]["id"], "MINOR", "intercom static",
        site_day_id=day["id"], as_technologist_id=tech["id"],
    )
    assert bd["status"] == "REPORTED"

    day_after = validate_success(api.get_site_day(day["id"], OPS))
    assert day_after["status"] == "IN_SERVICE", (
        f"MINOR breakdown must not interrupt the day, got {day_after['status']}"
    )
    unit_after = validate_success(api.get_unit(bundle["unit"]["id"], OPS))
    assert unit_after["status"] == "ACTIVE_SERVICE"

    data, meta = validate_paginated(
        api.list_billing_statements(OPS, params={"site_day_id": day["id"]})
    )
    assert data == [], "No statement may exist while the day has not closed"


def test_breakdown_major_interrupts_day_and_cascades(api):
    """PRD §3.6: "A `MAJOR` breakdown interrupts the named day exactly as the
    interruption action does."
    PRD §3.6: "The unwind then mirrors cancellation with interruption
    semantics: appointments in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or
    `SCANNING` are cancelled with `cancel_reason` `DAY_INTERRUPTED`; `ASSIGNED`
    staffing is released as `DAY_INTERRUPTED`; `DISPATCHED` legs become
    `FAILED`; and a `PROVISIONAL` billing statement is auto-created using the
    provisional pricing variant".

    Design: Difficulty/transitive_cascade/breakdown_major_cascade_day_appointments_statement
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech = bundle["technologist"]
    ap1 = book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="13:00")
    ap2 = book_appointment(day["id"], bundle["facility"]["id"], "P-002", scheduled_start="13:40")
    get_success_data(api.confirm_appointment(ap1["id"], OPS))
    get_success_data(api.confirm_appointment(ap2["id"], OPS))
    set_clock("2026-08-04T12:15:00Z")

    report_breakdown(
        bundle["unit"]["id"], "MAJOR", "Gradient coil fault",
        site_day_id=day["id"], as_technologist_id=tech["id"],
    )

    day_after = validate_success(api.get_site_day(day["id"], OPS))
    assert day_after["status"] == "INTERRUPTED", (
        f"Hop 1: day must be INTERRUPTED, got {day_after['status']}"
    )
    assert day_after["interrupt_reason"] == "BREAKDOWN"

    for ap in (ap1, ap2):
        ap_after = validate_success(api.get_appointment(ap["id"], OPS))
        assert ap_after["status"] == "CANCELLED", (
            f"Hop 2: appointment must be CANCELLED, got {ap_after['status']}"
        )
        assert ap_after["cancel_reason"] == "DAY_INTERRUPTED"

    staff_after = validate_success(api.get_staffing_assignment(bundle["staffing"]["id"], OPS))
    assert staff_after["status"] == "RELEASED"
    assert staff_after["release_reason"] == "DAY_INTERRUPTED"

    unit_after = validate_success(api.get_unit(bundle["unit"]["id"], OPS))
    assert unit_after["status"] == "ACTIVE_SERVICE", (
        "MAJOR severity must not take the unit OUT_OF_SERVICE"
    )


def test_breakdown_major_statement_prices_zero_billable_floor(api):
    """PRD §3.9: "Under `PER_SCAN`: the charge is the billable count up to
    `included_scan_quota` times `scan_rate_cents`, plus any billable count
    beyond the quota times `overage_scan_rate_cents`, plus `no_show_count`
    times `no_show_fee_cents`; and when the day reached `READY` at least once
    yet the billable count is zero, the charge is raised to at least
    `guaranteed_minimum_cents`."

    Design: Difficulty/transitive_cascade/breakdown_major_cascade_day_appointments_statement
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech = bundle["technologist"]
    ap1 = book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="13:00")
    get_success_data(api.confirm_appointment(ap1["id"], OPS))
    set_clock("2026-08-04T12:15:00Z")

    report_breakdown(
        bundle["unit"]["id"], "MAJOR", "Gradient coil fault",
        site_day_id=day["id"], as_technologist_id=tech["id"],
    )

    stmt = get_day_statement(day["id"])
    assert stmt["status"] == "PROVISIONAL"
    # The cascade cancelled every appointment -> zero billable on a day that
    # reached READY -> the guaranteed minimum floor applies.
    assert stmt["provisional_amount_cents"] == 200000, (
        f"Zero-billable PER_SCAN day must price the 200000 floor, "
        f"got {stmt['provisional_amount_cents']}"
    )


def test_resolve_breakdown_twice_rejected(api):
    """PRD §3.6: "An `OperationsDirector` later resolves a `REPORTED` event by
    recording `downtime_hours` and `resolution_notes`; resolving anything not
    `REPORTED` is `ERR_BREAKDOWN_ALREADY_RESOLVED`."

    Design: Corner/state_machines/resolve_breakdown_twice_rejected
    """
    unit = create_unit()
    tech = create_technologist()
    bd = report_breakdown(
        unit["id"], "MINOR", "door latch", as_technologist_id=tech["id"]
    )
    get_success_data(
        api.resolve_breakdown(
            bd["id"], {"downtime_hours": 1.5, "resolution_notes": "latch replaced"}, OPS
        )
    )

    resp = api.resolve_breakdown(
        bd["id"], {"downtime_hours": 0.5, "resolution_notes": "duplicate"}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_BREAKDOWN_ALREADY_RESOLVED)


# ---------------------------------------------------------------------------
# Cancellation fees
# ---------------------------------------------------------------------------

def test_cancel_fee_late_vs_early(api):
    """PRD §3.6: "the day's billing statement is auto-created in `PROVISIONAL`
    with the cancellation fee priced per the contract — the charge is late, and
    priced as such, exactly when `notice_hours` is less than the contract's
    `cancel_notice_hours`."
    PRD §3.9: "a cancelled day bills nothing when the cancel was early or
    provider-caused (`ACCREDITATION_EXPIRED`), and otherwise bills
    `day_rate_cents` multiplied by `cancel_late_pct`, rounded half-up to whole
    cents."

    Design: Corner/calculations/cancel_fee_late_vs_early
    """
    bundle = setup_bookable_day(publish=False)  # PER_DAY, notice 48h, pct 0.5
    day1 = bundle["site_day"]
    day2 = add_day_to_bundle(bundle, "2026-08-05")
    publish_plan(bundle["plan"]["id"])

    # Late cancel: 24h < 48h -> round_half_up(500000 * 0.5) = 250000.
    get_success_data(api.cancel_site_day(day1["id"], {"notice_hours": 24}, OPS))
    # Early cancel: 72h >= 48h -> 0.
    get_success_data(
        api.cancel_site_day(
            day2["id"], {"notice_hours": 72},
            make_facility_coordinator_headers(bundle["facility"]["id"]),
        )
    )

    late = get_day_statement(day1["id"])
    early = get_day_statement(day2["id"])
    assert late["provisional_amount_cents"] == 250000, (
        f"Late cancel must bill 250000, got {late['provisional_amount_cents']}"
    )
    assert early["provisional_amount_cents"] == 0, (
        f"Early cancel must bill 0, got {early['provisional_amount_cents']}"
    )


# ---------------------------------------------------------------------------
# Reschedule preconditions and OCC
# ---------------------------------------------------------------------------

def test_reschedule_from_non_interrupted_source_rejected(api):
    """PRD §3.6: "The source day must be `INTERRUPTED`
    (`ERR_RESCHEDULE_SOURCE_INVALID`)."

    Design: Corner/validations/reschedule_from_non_interrupted_source_rejected
    """
    bundle = setup_bookable_day(service_date="2026-08-12", week_start_date="2026-08-10")
    source_day = bundle["site_day"]  # SCHEDULED, not INTERRUPTED
    plan2 = setup_published_target_plan(bundle, "2026-08-17", "2026-08-19")
    fresh = validate_success(api.get_route_plan(plan2["id"], OPS))

    payload = {
        "target_route_plan_id": plan2["id"],
        "expected_route_plan_version": fresh["version"],
        "new_service_date": "2026-08-18",
        "new_arrival_time": "07:00",
        "new_first_patient_time": "08:30",
        "new_last_patient_time": "16:00",
        "new_departure_time": "17:00",
    }
    resp = api.reschedule_site_day(source_day["id"], payload, OPS)
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_SOURCE_INVALID)


def test_occ_stale_route_plan_version_on_reschedule(api):
    """PRD §2.7: "Rescheduling an interrupted site day requires the request
    body to carry `expected_route_plan_version`, the `version` of the target
    `RoutePlan` as the client last observed it. If the target plan's `version`
    has advanced in the meantime — its day roster may have changed — the
    reschedule is rejected with `ERR_STALE_ROUTE_PLAN_VERSION` (HTTP 412)."
    PRD §2.7: "Both checks are evaluated immediately after existence checks and
    before any state or business rule, so a stale version surfaces as a version
    error rather than being masked by a later validation."

    Design: Corner/cross_cutting_layers/occ_stale_route_plan_version_on_reschedule
    """
    bundle = setup_bookable_day(service_date="2026-08-12", week_start_date="2026-08-10")
    plan = bundle["plan"]
    source_day = bundle["site_day"]
    stale = validate_success(api.get_route_plan(plan["id"], OPS))["version"]
    # Another write (a second site day) advances the plan version.
    add_site_day(
        plan["id"], bundle["facility"]["id"], bundle["contract"]["id"], "2026-08-13"
    )

    payload = {
        "target_route_plan_id": plan["id"],
        "expected_route_plan_version": stale,
        "new_service_date": "2026-08-14",
        "new_arrival_time": "07:00",
        "new_first_patient_time": "08:30",
        "new_last_patient_time": "16:00",
        "new_departure_time": "17:00",
    }
    resp = api.reschedule_site_day(source_day["id"], payload, OPS)
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_PLAN_VERSION)


# ---------------------------------------------------------------------------
# Priority pair: state (bookability) beats fiscal (scan cap)
# ---------------------------------------------------------------------------

def test_interrupted_day_state_error_masks_scan_cap(api):
    """PRD §2.8: "Every request is validated against a fixed priority ladder,
    and a failure at any rung stops evaluation so that earlier errors mask
    later ones."
    PRD §3.5: "The day must be bookable — a day that is `INTERRUPTED`,
    `CANCELLED`, `COMPLETED`, or `RESCHEDULED` accepts no appointments and
    answers `ERR_SITE_DAY_NOT_BOOKABLE`."

    Design: Difficulty/priority_pair_validation_conflict/interrupted_day_and_scan_cap_state_beats_fiscal
    """
    bundle = setup_bookable_day(
        billing_model="PER_SCAN", publish=False, contract_overrides={"monthly_scan_cap": 1}
    )
    day1 = bundle["site_day"]  # 2026-08-04
    day2 = add_day_to_bundle(bundle, "2026-08-05")
    publish_plan(bundle["plan"]["id"])
    # Consume the only monthly slot on day2.
    book_appointment(day2["id"], bundle["facility"]["id"], "P-100")
    # Drive day1 to IN_SERVICE and interrupt it.
    drive_day_to_in_service(bundle, site_day=day1)
    get_success_data(api.interrupt_site_day(day1["id"], {"reason": "OPERATOR_INTERRUPT"}, OPS))

    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    resp = api.create_appointment(
        create_appointment_payload(day1["id"], "P-101", scheduled_start="10:00"), coord
    )
    # State (rung 5) fires; the fiscal cap (rung 13) is masked even though it
    # also held.
    validate_error(resp, ApiErrorId.ERR_SITE_DAY_NOT_BOOKABLE)


def test_scan_cap_error_surfaces_when_day_bookable(api):
    """PRD §3.5: "Last of all — it is the fiscal gate on the §2.8 ladder, so
    all earlier checks fire first — the contract's `monthly_scan_cap` is
    enforced: counting every appointment on site days under the same contract
    whose `service_date` falls in the target calendar month and whose status
    is anything but `CANCELLED`, the booking is rejected with
    `ERR_SCAN_CAP_EXCEEDED` when that count has already reached the cap;
    booking the appointment that reaches the cap is allowed, and only the next
    one is refused."

    Design: Difficulty/priority_pair_validation_conflict/interrupted_day_and_scan_cap_state_beats_fiscal
    """
    bundle = setup_bookable_day(
        billing_model="PER_SCAN", contract_overrides={"monthly_scan_cap": 1}
    )
    day = bundle["site_day"]  # bookable
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    get_success_data(
        api.create_appointment(
            create_appointment_payload(day["id"], "P-100", scheduled_start="09:00"), coord
        )
    )

    resp = api.create_appointment(
        create_appointment_payload(day["id"], "P-101", scheduled_start="09:40"), coord
    )
    validate_error(resp, ApiErrorId.ERR_SCAN_CAP_EXCEEDED)


# ---------------------------------------------------------------------------
# Compensating invariant: PER_DAY money conservation across reschedule
# ---------------------------------------------------------------------------

def _interrupt_per_day_at_half_window(api):
    """PER_DAY day driven to IN_SERVICE, clock at 12:15 (225 of 450 window
    minutes delivered), then interrupted; rescheduled into a second published
    plan for 2026-08-11. Returns (bundle, source_day_id, replacement_day)."""
    bundle = setup_in_service_day(billing_model="PER_DAY")
    source = bundle["site_day"]
    set_clock("2026-08-04T12:15:00Z")
    get_success_data(api.interrupt_site_day(source["id"], {"reason": "OPERATOR_INTERRUPT"}, OPS))
    plan2 = setup_published_target_plan(bundle, "2026-08-10", "2026-08-12")
    replacement = reschedule_day(source["id"], plan2, "2026-08-11")
    return bundle, source["id"], replacement


def test_per_day_interrupt_reschedule_source_credit(api):
    """PRD §3.6: "Interruption freezes delivered service at the minutes elapsed
    from `first_patient_time` to the logical clock, clamped below at zero and
    above at the full planned window length, and stores it in
    `delivered_service_minutes`."
    PRD §3.9: "an interrupted day bills the day rate multiplied by the fraction
    of the planned window actually delivered — `delivered_service_minutes` over
    the minutes from `first_patient_time` to `last_patient_time` — rounded
    half-up to whole cents, but never less than `interruption_floor_cents`, and
    the difference between the day rate and that prorated amount is recorded as
    the statement's `credit_granted_cents`;".
    PRD §3.6: "On success a replacement day is created `SCHEDULED` in the
    target plan with the same `facility_id` and `contract_id`, its
    `rescheduled_from_id` pointing back to the source; the source day becomes
    `RESCHEDULED` with its `rescheduled_to_id` pointing at the replacement".

    Design: Difficulty/compensating_invariant/per_day_interrupt_reschedule_money_conservation
    """
    bundle, source_id, replacement = _interrupt_per_day_at_half_window(api)

    stmt_a = get_day_statement(source_id)
    # delivered 225 of 450 -> max(100000, round_half_up(500000 * 0.5)) = 250000.
    assert stmt_a["provisional_amount_cents"] == 250000, (
        f"Source provisional must be 250000, got {stmt_a['provisional_amount_cents']}"
    )
    assert stmt_a["credit_granted_cents"] == 250000, (
        f"Source credit_granted must be 500000 - 250000 = 250000, "
        f"got {stmt_a['credit_granted_cents']}"
    )

    source_after = validate_success(api.get_site_day(source_id, OPS))
    assert source_after["status"] == "RESCHEDULED"
    assert source_after["rescheduled_to_id"] == replacement["id"]
    assert replacement["rescheduled_from_id"] == source_id
    assert replacement["status"] == "SCHEDULED"


def test_per_day_interrupt_reschedule_money_conservation(api):
    """PRD §3.9: "On the interrupted source day's `PER_DAY` statement,
    `credit_granted_cents` is the day rate minus the statement's provisional
    amount; the replacement day's statement then carries `credit_applied_cents`
    equal to that granted credit. The money invariant follows: when the
    replacement day completes a full window, the two statements' `net_due_cents`
    sum to exactly the contract's `day_rate_cents`."
    PRD §3.9: "While `PROVISIONAL`, `net_due_cents` equals
    `provisional_amount_cents` minus `credit_applied_cents`; once finalized, it
    equals `final_amount_cents` minus `credit_applied_cents`."

    Design: Difficulty/compensating_invariant/per_day_interrupt_reschedule_money_conservation
    """
    bundle, source_id, replacement = _interrupt_per_day_at_half_window(api)

    # Drive the replacement day through a full window to COMPLETED.
    drive_day_to_in_service(
        bundle, site_day=replacement, technologist=bundle["technologist"]
    )
    complete_site_day(bundle, replacement["id"])

    stmt_a = get_day_statement(source_id)
    stmt_b = get_day_statement(replacement["id"])
    assert stmt_b["provisional_amount_cents"] == 500000, (
        f"Replacement full-window day bills day_rate 500000, got {stmt_b['provisional_amount_cents']}"
    )
    assert stmt_b["credit_applied_cents"] == 250000, (
        f"Replacement carries the granted credit 250000, got {stmt_b['credit_applied_cents']}"
    )
    assert stmt_a["net_due_cents"] == 250000
    assert stmt_b["net_due_cents"] == 250000, (
        f"Replacement net must be 500000 - 250000 = 250000, got {stmt_b['net_due_cents']}"
    )
    total = stmt_a["net_due_cents"] + stmt_b["net_due_cents"]
    assert total == bundle["contract"]["day_rate_cents"], (
        f"Money invariant: source net + replacement net must equal day_rate_cents "
        f"500000, got {total}"
    )


# ---------------------------------------------------------------------------
# Compensating invariant: PER_SCAN billed scan-count conservation
# ---------------------------------------------------------------------------

def _interrupt_per_scan_with_one_completed_scan(api):
    """PER_SCAN day IN_SERVICE: appointment 1 COMPLETED with its study
    DELIVERED; appointment 2 still CONFIRMED; a MAJOR breakdown interrupts the
    day; the day is rescheduled to 2026-08-11. Returns (bundle, ids...)."""
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech = bundle["technologist"]
    ap1 = book_and_complete_appointment(bundle, "P-001", scheduled_start="09:00")
    register_and_transmit_study(bundle, ap1["id"], "1.2.3.4", 500)
    ap2 = book_appointment(day["id"], bundle["facility"]["id"], "P-002", scheduled_start="09:40")
    get_success_data(api.confirm_appointment(ap2["id"], OPS))

    set_clock("2026-08-04T12:15:00Z")
    report_breakdown(
        bundle["unit"]["id"], "MAJOR", "tube arc",
        site_day_id=day["id"], as_technologist_id=tech["id"],
    )
    plan2 = setup_published_target_plan(bundle, "2026-08-10", "2026-08-12")
    replacement = reschedule_day(day["id"], plan2, "2026-08-11")
    return bundle, day["id"], ap1, ap2, replacement


def test_per_scan_reschedule_source_scan_count(api):
    """PRD §3.9: "Under `PER_SCAN` the invariant is a count: the billable scans
    across both statements equal the number of distinct `COMPLETED`
    appointments across both days, because appointments cancelled by the
    interruption (`DAY_INTERRUPTED`) are never billable, so a rebooked scan is
    billed exactly once."
    PRD §3.9: "The provisional variant, computed at day close, counts every
    `COMPLETED` appointment as billable."

    Design: Difficulty/compensating_invariant/per_scan_reschedule_scan_count_conservation
    """
    bundle, source_id, ap1, ap2, _replacement = _interrupt_per_scan_with_one_completed_scan(api)

    ap2_after = validate_success(api.get_appointment(ap2["id"], OPS))
    assert ap2_after["status"] == "CANCELLED"
    assert ap2_after["cancel_reason"] == "DAY_INTERRUPTED"

    stmt_a = get_day_statement(source_id)
    assert stmt_a["completed_scan_count"] == 1, (
        f"Only the delivered COMPLETED scan counts, got {stmt_a['completed_scan_count']}"
    )
    assert stmt_a["provisional_amount_cents"] == 40000, (
        f"1 billable scan * 40000 must price 40000, got {stmt_a['provisional_amount_cents']}"
    )


def test_per_scan_reschedule_scan_count_conservation(api):
    """PRD §3.9: "Under `PER_SCAN` the invariant is a count: the billable scans
    across both statements equal the number of distinct `COMPLETED`
    appointments across both days, because appointments cancelled by the
    interruption (`DAY_INTERRUPTED`) are never billable, so a rebooked scan is
    billed exactly once."

    Design: Difficulty/compensating_invariant/per_scan_reschedule_scan_count_conservation
    """
    bundle, source_id, ap1, ap2, replacement = (
        _interrupt_per_scan_with_one_completed_scan(api)
    )

    # Rebook the displaced patient on the replacement day and complete it.
    drive_day_to_in_service(
        bundle, site_day=replacement, technologist=bundle["technologist"]
    )
    ap3 = book_and_complete_appointment(
        bundle, "P-002", scheduled_start="09:00"
    )
    complete_site_day(bundle, replacement["id"])

    stmt_a = get_day_statement(source_id)
    stmt_b = get_day_statement(replacement["id"])
    assert stmt_a["completed_scan_count"] == 1
    assert stmt_b["completed_scan_count"] == 1, (
        f"Replacement bills the rebooked scan once, got {stmt_b['completed_scan_count']}"
    )
    assert stmt_b["provisional_amount_cents"] == 40000
    total_billable = stmt_a["completed_scan_count"] + stmt_b["completed_scan_count"]
    assert total_billable == 2, (
        f"Total billable scans across both days must be 2 (appt {ap1['id']} + "
        f"appt {ap3['id']}); the DAY_INTERRUPTED-cancelled {ap2['id']} is never "
        f"billable; got {total_billable}"
    )
