"""On-site day execution: depart/setup/ready/service gates, checklist cycle,
and cross-entity state gates on begin-scan and mark-ready."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_staffing,
    book_appointment,
    create_setup_checklist_payload,
    create_technologist,
    drive_day_to_ready,
    make_facility_coordinator_headers,
    make_technologist_headers,
    plan_transport_leg,
    record_checklist,
    record_checklist_item,
    setup_bookable_day,
    setup_in_service_day,
    validate_error,
    validate_success,
    get_success_data,
)

OPS = TEST_USERS["operations_director_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_depart_dispatches_planned_transport_legs(api):
    """PRD §3.4: "The day must be `SCHEDULED` (`ERR_INVALID_STATE`) and the
    unit's governing accreditation must be `ACTIVE` or `EXPIRING_SOON`
    (`ERR_ACCREDITATION_NOT_VALID`); the day then advances `SCHEDULED` →
    `EN_ROUTE`, and every `PLANNED` transport leg of the day cascades to
    `DISPATCHED`."

    Design: Corner/state_machines/depart_dispatches_planned_transport_legs
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])

    resp = api.depart_site_day(day["id"], OPS)
    data = validate_success(resp)
    assert data["status"] == "EN_ROUTE", f"Day must be EN_ROUTE, got {data['status']}"

    leg_after = validate_success(api.get_transport_leg(leg["id"], OPS))
    assert leg_after["status"] == "DISPATCHED", (
        f"Depart must cascade PLANNED legs to DISPATCHED, got {leg_after['status']}"
    )


def test_begin_setup_before_leg_arrival_rejected(api):
    """PRD §3.4: "Advancing `EN_ROUTE` → `SETTING_UP` requires every transport
    leg of the day to be `ARRIVED` — a straggler leg surfaces as
    `ERR_TRANSPORT_NOT_ARRIVED` — with the usual `ERR_INVALID_STATE` guarding
    the from-state."

    Design: Corner/state_machines/begin_setup_before_leg_arrival_rejected
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api.depart_site_day(day["id"], OPS))  # leg now DISPATCHED

    resp = api.begin_setup_site_day(day["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_TRANSPORT_NOT_ARRIVED)


def test_checklist_failure_cycle_recovers_via_record_item(api):
    """PRD §3.4: "Its `status` is computed, never set: `IN_PROGRESS` before any
    record exists, `ALL_PASSED` when all five booleans are true, and
    `HAS_FAILURES` as soon as any one is false."
    PRD §3.4: "Failed items are not fatal — a `Technologist` re-records a
    single item by naming its `item_key`, the new `passed` value, and, where
    applicable, a `measured_value` that overwrites `measured_amps` for the
    `POWER_VERIFY` item or `measured_uplink_mbps` for the `NETWORK_LINK` item;
    the checklist status is then recomputed, so the `HAS_FAILURES` →
    `ALL_PASSED` cycle repeats until everything passes."

    Design: Corner/state_machines/checklist_failure_cycle_recovers_via_record_item
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    tech = create_technologist()
    tech_headers = make_technologist_headers(tech["id"])
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api.depart_site_day(day["id"], OPS))
    get_success_data(api.arrive_transport_leg(leg["id"], tech_headers))
    get_success_data(api.begin_setup_site_day(day["id"], OPS))

    checklist = record_checklist(day["id"], tech["id"], chiller_passed=False)
    assert checklist["status"] == "HAS_FAILURES", (
        f"Any false boolean must compute HAS_FAILURES, got {checklist['status']}"
    )

    resp = api.mark_ready_site_day(day["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)

    fixed = record_checklist_item(checklist["id"], tech["id"], "CHILLER", True)
    assert fixed["status"] == "ALL_PASSED", (
        f"Re-recorded checklist must compute ALL_PASSED, got {fixed['status']}"
    )

    ready = validate_success(api.mark_ready_site_day(day["id"], OPS))
    assert ready["status"] == "READY"


def test_second_checklist_for_same_day_rejected(api):
    """PRD §3.4: "During `SETTING_UP` a `Technologist` records the day's
    `SetupChecklist`, one per site day: a second checklist for the same day is
    rejected with `ERR_CHECKLIST_EXISTS`, and recording against a day that is
    not in `SETTING_UP` is an `ERR_INVALID_STATE`."

    Design: Corner/validations/second_checklist_for_same_day_rejected
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    tech = create_technologist()
    tech_headers = make_technologist_headers(tech["id"])
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api.depart_site_day(day["id"], OPS))
    get_success_data(api.arrive_transport_leg(leg["id"], tech_headers))
    get_success_data(api.begin_setup_site_day(day["id"], OPS))
    record_checklist(day["id"], tech["id"])

    resp = api.create_setup_checklist(
        create_setup_checklist_payload(day["id"]), tech_headers
    )
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_EXISTS)


def test_start_service_without_staffing_rejected(api):
    """PRD §3.4: "Starting service — `READY` → `IN_SERVICE` — additionally
    requires at least one `ASSIGNED` staffing assignment on the day, failing
    which the call is rejected with `ERR_NO_STAFF_ASSIGNED`."

    Design: Corner/state_machines/start_service_without_staffing_rejected
    """
    bundle = setup_bookable_day()
    # Drive to READY without ever staffing the day.
    drive_day_to_ready(bundle)
    resp = api.start_service_site_day(bundle["site_day"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_NO_STAFF_ASSIGNED)


def test_complete_with_open_appointment_rejected(api):
    """PRD §3.4: "Completing the day — `IN_SERVICE` → `COMPLETED` — requires
    every appointment of the day to be terminal: `COMPLETED`, `CANCELLED`, or
    `NO_SHOW`; any open appointment blocks the close with
    `ERR_OPEN_APPOINTMENTS`."

    Design: Corner/state_machines/complete_with_open_appointment_rejected
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    appt = book_appointment(
        bundle["site_day"]["id"], bundle["facility"]["id"], "P-001"
    )
    get_success_data(api.confirm_appointment(appt["id"], OPS))  # CONFIRMED, not terminal

    resp = api.complete_site_day(bundle["site_day"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_OPEN_APPOINTMENTS)


def test_cancel_completed_day_returns_invalid_state(api):
    """PRD §3.6: "While a day is `SCHEDULED` or `EN_ROUTE`, an
    `OperationsDirector` or a `FacilityCoordinator` may cancel it, supplying
    `notice_hours` — how many hours before service the cancellation arrives.
    From any other state the cancel is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_day_returns_invalid_state
    """
    bundle = setup_in_service_day()
    get_success_data(api.complete_site_day(bundle["site_day"]["id"], OPS))

    resp = api.cancel_site_day(bundle["site_day"]["id"], {"notice_hours": 72}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    day = validate_success(api.get_site_day(bundle["site_day"]["id"], OPS))
    assert day["status"] == "COMPLETED", f"Day must remain COMPLETED, got {day['status']}"


def test_mark_ready_blocked_while_accreditation_suspended(api):
    """PRD §3.7: "Site-day creation, departure, and mark-ready each require the
    governing record to be `ACTIVE` or `EXPIRING_SOON` — a governing record
    that is `EXPIRED` or `SUSPENDED`, or a unit with no governing record at
    all, fails the gate with `ERR_ACCREDITATION_NOT_VALID`."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_gated_by_accreditation_state
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    tech = create_technologist()
    tech_headers = make_technologist_headers(tech["id"])
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api.depart_site_day(day["id"], OPS))
    get_success_data(api.arrive_transport_leg(leg["id"], tech_headers))
    get_success_data(api.begin_setup_site_day(day["id"], OPS))
    record_checklist(day["id"], tech["id"])  # ALL_PASSED, measured_amps 140 >= 100

    get_success_data(
        api.suspend_accreditation(
            bundle["accreditation"]["id"], {"reason": "audit finding"}, COMPLIANCE
        )
    )
    resp = api.mark_ready_site_day(day["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ACCREDITATION_NOT_VALID)


def test_mark_ready_allowed_after_accreditation_reinstated(api):
    """PRD §3.7: "Site-day creation, departure, and mark-ready each require the
    governing record to be `ACTIVE` or `EXPIRING_SOON` — a governing record
    that is `EXPIRED` or `SUSPENDED`, or a unit with no governing record at
    all, fails the gate with `ERR_ACCREDITATION_NOT_VALID`."
    PRD §3.7: "A record may also be manually suspended — an audit finding —
    moving `ACTIVE` or `EXPIRING_SOON` to `SUSPENDED` with the supplied
    `reason` stored as `suspend_reason` (`ERR_INVALID_STATE` from any other
    state), and later reinstated, at which point the landing state is
    re-derived from the clock".

    Design: Difficulty/cross_entity_state_dependency/mark_ready_gated_by_accreditation_state
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]
    tech = create_technologist()
    tech_headers = make_technologist_headers(tech["id"])
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api.depart_site_day(day["id"], OPS))
    get_success_data(api.arrive_transport_leg(leg["id"], tech_headers))
    get_success_data(api.begin_setup_site_day(day["id"], OPS))
    record_checklist(day["id"], tech["id"])

    acc_id = bundle["accreditation"]["id"]
    get_success_data(api.suspend_accreditation(acc_id, {"reason": "audit finding"}, COMPLIANCE))
    blocked = api.mark_ready_site_day(day["id"], OPS)
    validate_error(blocked, ApiErrorId.ERR_ACCREDITATION_NOT_VALID)

    get_success_data(api.reinstate_accreditation(acc_id, COMPLIANCE))
    ready = validate_success(api.mark_ready_site_day(day["id"], OPS))
    assert ready["status"] == "READY", f"After reinstate mark-ready must succeed, got {ready['status']}"


def test_begin_scan_blocked_until_day_in_service(api):
    """PRD §3.5: "An `OperationsDirector` confirms a `REQUESTED` appointment
    (`CONFIRMED`); a `FacilityCoordinator` checks the patient in once the day
    is `READY` or `IN_SERVICE` (`CHECKED_IN`, with `ERR_SITE_DAY_NOT_IN_SERVICE`
    if the day has not reached at least `READY`); a `Technologist` begins the
    scan from `CHECKED_IN` (`SCANNING`) but only while the day is `IN_SERVICE`
    (`ERR_SITE_DAY_NOT_IN_SERVICE`) and only when the acting technologist — the
    caller's `X-User-ID` — holds an `ASSIGNED` staffing assignment on that site
    day (`ERR_TECHNOLOGIST_NOT_STAFFED`)."

    Design: Difficulty/cross_entity_state_dependency/begin_scan_gated_by_site_day_in_service
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech = create_technologist()
    assign_staffing(day["id"], tech["id"])
    drive_day_to_ready(bundle, technologist=tech)  # stops at READY

    appt = book_appointment(day["id"], bundle["facility"]["id"], "P-001")
    get_success_data(api.confirm_appointment(appt["id"], OPS))
    get_success_data(
        api.check_in_appointment(
            appt["id"], make_facility_coordinator_headers(bundle["facility"]["id"])
        )
    )

    resp = api.begin_scan_appointment(appt["id"], make_technologist_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_SITE_DAY_NOT_IN_SERVICE)


def test_begin_scan_succeeds_after_start_service(api):
    """PRD §3.5: "An `OperationsDirector` confirms a `REQUESTED` appointment
    (`CONFIRMED`); a `FacilityCoordinator` checks the patient in once the day
    is `READY` or `IN_SERVICE` (`CHECKED_IN`, with `ERR_SITE_DAY_NOT_IN_SERVICE`
    if the day has not reached at least `READY`); a `Technologist` begins the
    scan from `CHECKED_IN` (`SCANNING`) but only while the day is `IN_SERVICE`
    (`ERR_SITE_DAY_NOT_IN_SERVICE`) and only when the acting technologist — the
    caller's `X-User-ID` — holds an `ASSIGNED` staffing assignment on that site
    day (`ERR_TECHNOLOGIST_NOT_STAFFED`)."

    Design: Difficulty/cross_entity_state_dependency/begin_scan_gated_by_site_day_in_service
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech = create_technologist()
    assign_staffing(day["id"], tech["id"])
    drive_day_to_ready(bundle, technologist=tech)

    appt = book_appointment(day["id"], bundle["facility"]["id"], "P-001")
    get_success_data(api.confirm_appointment(appt["id"], OPS))
    get_success_data(
        api.check_in_appointment(
            appt["id"], make_facility_coordinator_headers(bundle["facility"]["id"])
        )
    )
    blocked = api.begin_scan_appointment(appt["id"], make_technologist_headers(tech["id"]))
    validate_error(blocked, ApiErrorId.ERR_SITE_DAY_NOT_IN_SERVICE)

    get_success_data(api.start_service_site_day(day["id"], OPS))
    scanning = validate_success(
        api.begin_scan_appointment(appt["id"], make_technologist_headers(tech["id"]))
    )
    assert scanning["status"] == "SCANNING", (
        f"After start-service begin-scan must succeed, got {scanning['status']}"
    )
