"""Dispatching: the promised-ETA projection vs the stamped actual response, the
technician ETA-window overlap geometry, the bay-slot overlap geometry, and the
dispatch precondition gates (on-duty, certified, departed-before-arrive).

Difficulty queue: dual_variant_calc (time), resource_temporal_overlap (technician
buffer + bay closed interval), cross_entity_state_dependency (technician on-duty).
Corner queue: state_machines (arrive/certified), endpoints (filtered list), errors
(time window), validations (bay closed).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_technician_headers,
    create_dispatch_payload,
    create_bay_booking_payload,
    create_technician,
    create_job,
    create_job_bay,
    dispatch_job,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── dual_variant_calc / eta_promised_vs_actual_time_divergence ────────────────
def test_promised_eta_is_base_travel_with_no_live_dispatches(api):
    """PRD §3.2: "The projection is the technician's base_travel_minutes plus a queue
    penalty for each of the technician's other live dispatches: count the technician's
    dispatches that are currently in ASSIGNED or EN_ROUTE status (excluding the one
    being created), multiply that count by a ten-minute per-dispatch queue penalty,
    and add the product to the base travel time."

    Design: Difficulty/dual_variant_calc/eta_promised_vs_actual_time_divergence
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=20)
    job = create_job(customer_user_id="cust-eta1", service_type="LOCKOUT",
                     requested_at_minute=600)
    disp = validate_success(
        api.create_dispatch(job["id"],
                            create_dispatch_payload(tech["id"], 605, 650), DISPATCHER), 201
    )
    assert disp["promised_eta_minutes"] == 20, (
        f"base 20, no live dispatches -> 20, got {disp['promised_eta_minutes']}"
    )


def test_actual_response_is_arrived_minus_requested(api):
    """PRD §3.4: "It is the arrived_at_minute minus the parent job's
    requested_at_minute; if that difference is negative (a next-day arrival, where
    the clock has wrapped past midnight), the actual response time is floored at 0
    rather than going negative."

    Design: Difficulty/dual_variant_calc/eta_promised_vs_actual_time_divergence
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=20)
    tech_h = make_technician_headers(tech["id"])
    job = create_job(customer_user_id="cust-eta2", service_type="LOCKOUT",
                     requested_at_minute=600)
    disp = dispatch_job(job["id"], tech["id"], 605, 650)
    assert disp["promised_eta_minutes"] == 20
    get_success_data(api.depart_dispatch(disp["id"], tech_h))
    arrived = validate_success(
        api.arrive_dispatch(disp["id"], {"arrived_at_minute": 645}, tech_h), 200
    )
    # 645 - 600 = 45, distinct from the promised 20
    assert arrived["actual_response_minutes"] == 45, (
        f"645-600=45 expected, got {arrived['actual_response_minutes']}"
    )
    assert arrived["promised_eta_minutes"] != arrived["actual_response_minutes"]


# ─── resource_temporal_overlap / technician_eta_window_overlap_with_buffer ─────
def test_technician_eta_window_overlap_within_buffer_rejected(api):
    """PRD §3.3: "The window being created, running from its start up to its end,
    collides with an existing live window of the same technician when the new window's
    start falls before the existing window's end plus the fifteen-minute buffer, and
    at the same time the existing window's start falls before the new window's end
    plus the same fifteen-minute buffer."

    Design: Difficulty/resource_temporal_overlap/technician_eta_window_overlap_with_buffer
    """
    tech = create_technician(certified_for=["LOCKOUT", "REKEY"], base_travel_minutes=10)
    job_a = create_job(customer_user_id="cust-ov-a", service_type="LOCKOUT",
                       requested_at_minute=600)
    dispatch_job(job_a["id"], tech["id"], 600, 640)
    job_b = create_job(customer_user_id="cust-ov-b", service_type="REKEY",
                       requested_at_minute=650)
    # window [650,700): 650 < 640+15=655 and 600 < 700+15 -> collides
    res = api.create_dispatch(
        job_b["id"], create_dispatch_payload(tech["id"], 650, 700), DISPATCHER
    )
    validate_error(res, "ERR_ETA_WINDOW_OVERLAP", expected_status=409)


def test_technician_window_at_buffer_boundary_does_not_collide(api):
    """PRD §3.3: "Because the intervals are half-open, a new window that begins exactly
    at an existing window's end plus the buffer does not collide — adjacency at that
    boundary is allowed."

    Design: Difficulty/resource_temporal_overlap/technician_eta_window_overlap_with_buffer
    """
    tech = create_technician(certified_for=["LOCKOUT", "REKEY"], base_travel_minutes=10)
    job_a = create_job(customer_user_id="cust-adj-a", service_type="LOCKOUT",
                       requested_at_minute=600)
    dispatch_job(job_a["id"], tech["id"], 600, 640)
    job_b = create_job(customer_user_id="cust-adj-b", service_type="REKEY",
                       requested_at_minute=655)
    # window starts exactly at 640+15=655 -> adjacency allowed, no collision
    disp = validate_success(
        api.create_dispatch(job_b["id"],
                            create_dispatch_payload(tech["id"], 655, 700), DISPATCHER), 201
    )
    assert disp["status"] == "ASSIGNED"


# ─── resource_temporal_overlap / bay_slot_overlap_closed_interval ──────────────
def test_bay_slot_shared_endpoint_collides(api):
    """PRD §3.11: "the new slot, running from its slot_start_minute to its
    slot_end_minute, collides with an existing booked slot of the same bay when the
    new slot's start is less than or equal to the existing slot's end and the existing
    slot's start is less than or equal to the new slot's end. Because the endpoints are
    inclusive, two slots that merely touch at a single shared endpoint minute do collide."

    Design: Difficulty/resource_temporal_overlap/bay_slot_overlap_closed_interval
    """
    bay = create_job_bay(bay_name="Bench-Ovl")
    job_a = create_job(customer_user_id="cust-bay-a", service_type="REKEY",
                       requested_at_minute=600)
    job_b = create_job(customer_user_id="cust-bay-b", service_type="REKEY",
                       requested_at_minute=640)
    validate_success(
        api.create_bay_booking(
            create_bay_booking_payload(job_a["id"], bay["id"], 600, 640), DISPATCHER), 201
    )
    # [640,700] shares endpoint minute 640 with [600,640] -> collide
    res = api.create_bay_booking(
        create_bay_booking_payload(job_b["id"], bay["id"], 640, 700), DISPATCHER
    )
    validate_error(res, "ERR_BAY_SLOT_OVERLAP", expected_status=409)


def test_bay_slot_no_buffer_unlike_technician(api):
    """PRD §3.11: "Unlike the technician timeline, bay slots are treated as closed
    intervals with inclusive endpoints and no travel buffer: the new slot, running
    from its slot_start_minute to its slot_end_minute, collides with an existing
    booked slot of the same bay when the new slot's start is less than or equal to
    the existing slot's end and the existing slot's start is less than or equal to
    the new slot's end."

    Design: Difficulty/resource_temporal_overlap/bay_slot_overlap_closed_interval
    """
    bay = create_job_bay(bay_name="Bench-NoBuf")
    job_a = create_job(customer_user_id="cust-buf-a", service_type="REKEY",
                       requested_at_minute=600)
    job_b = create_job(customer_user_id="cust-buf-b", service_type="REKEY",
                       requested_at_minute=641)
    validate_success(
        api.create_bay_booking(
            create_bay_booking_payload(job_a["id"], bay["id"], 600, 640), DISPATCHER), 201
    )
    # [641,700] does not touch [600,640]; no buffer means it succeeds
    booking = validate_success(
        api.create_bay_booking(
            create_bay_booking_payload(job_b["id"], bay["id"], 641, 700), DISPATCHER), 201
    )
    assert booking["status"] == "BOOKED"


# ─── cross_entity_state_dependency / dispatch_requires_technician_on_duty ──────
def test_dispatch_off_duty_technician_rejected(api):
    """PRD §3.2: "The named technician must be ON_DUTY — an OFF_DUTY technician yields
    ERR_TECHNICIAN_UNAVAILABLE — and the job's service_type must appear in that
    technician's certified_for list, failing which the dispatch is rejected with
    ERR_TECHNICIAN_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_technician_on_duty
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=20)
    get_success_data(api.set_technician_off_duty(tech["id"], DISPATCHER))
    job = create_job(customer_user_id="cust-od", service_type="LOCKOUT",
                     requested_at_minute=700)
    res = api.create_dispatch(
        job["id"], create_dispatch_payload(tech["id"], 705, 750), DISPATCHER
    )
    validate_error(res, "ERR_TECHNICIAN_UNAVAILABLE", expected_status=409)


def test_dispatch_on_duty_technician_succeeds(api):
    """PRD §3.2: "Dispatching is the act that advances a job from INTAKE to DISPATCHED."
    PRD §3.2: "A technician's status begins ON_DUTY and may be toggled by the dispatcher
    to OFF_DUTY (no longer dispatchable) and back to ON_DUTY through the duty-toggle
    actions"

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_technician_on_duty
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=20)
    job = create_job(customer_user_id="cust-od2", service_type="LOCKOUT",
                     requested_at_minute=700)
    disp = validate_success(
        api.create_dispatch(job["id"],
                            create_dispatch_payload(tech["id"], 705, 750), DISPATCHER), 201
    )
    assert disp["status"] == "ASSIGNED"
    job_after = validate_success(api.get_service_job(job["id"], DISPATCHER), 200)
    assert job_after["job_status"] == "DISPATCHED"


# ─── Corner: state_machines / dispatch_uncertified_technician ──────────────────
def test_dispatch_uncertified_technician_rejected(api):
    """PRD §3.2: "the job's service_type must appear in that technician's certified_for
    list, failing which the dispatch is rejected with ERR_TECHNICIAN_NOT_CERTIFIED."

    Design: Corner/state_machines/dispatch_uncertified_technician
    """
    tech = create_technician(certified_for=["REKEY"], base_travel_minutes=10)
    job = create_job(customer_user_id="cust-cert", service_type="SAFE",
                     requested_at_minute=600)
    res = api.create_dispatch(
        job["id"], create_dispatch_payload(tech["id"], 605, 650), DISPATCHER
    )
    validate_error(res, "ERR_TECHNICIAN_NOT_CERTIFIED", expected_status=409)


# ─── Corner: state_machines / arrive_dispatch_not_en_route ─────────────────────
def test_arrive_on_assigned_dispatch_rejected(api):
    """PRD §3.4: "Arriving moves the dispatch from EN_ROUTE to ARRIVED and requires the
    dispatch to be in EN_ROUTE — an arrive on a dispatch not yet en route is rejected
    with ERR_DISPATCH_NOT_EN_ROUTE."

    Design: Corner/state_machines/arrive_dispatch_not_en_route
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=10)
    tech_h = make_technician_headers(tech["id"])
    job = create_job(customer_user_id="cust-arr", service_type="LOCKOUT",
                     requested_at_minute=600)
    disp = dispatch_job(job["id"], tech["id"], 605, 650)
    # not departed -> still ASSIGNED
    res = api.arrive_dispatch(disp["id"], {"arrived_at_minute": 640}, tech_h)
    validate_error(res, "ERR_DISPATCH_NOT_EN_ROUTE", expected_status=409)


# ─── Corner: errors / invalid_time_window_eta_end_le_start ─────────────────────
def test_dispatch_eta_end_not_after_start_rejected(api):
    """PRD §2.7: "an ETA window or bench slot whose endpoints are out of order, is
    rejected with ERR_INVALID_TIME_WINDOW."
    PRD §3.2: "a promised arrival window: eta_start_minute and eta_end_minute, both
    minutes from local midnight, with the end strictly greater than the start."

    Design: Corner/entities/invalid_time_window_eta_end_le_start
    """
    tech = create_technician(certified_for=["LOCKOUT"], base_travel_minutes=10)
    job = create_job(customer_user_id="cust-tw", service_type="LOCKOUT",
                     requested_at_minute=600)
    res = api.create_dispatch(
        job["id"], create_dispatch_payload(tech["id"], 650, 650), DISPATCHER
    )
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


# ─── Corner: errors / bay_closed_for_maint_booking_rejected ────────────────────
def test_booking_closed_for_maint_bay_rejected(api):
    """PRD §3.11: "A booking is refused if the target bay is not OPEN — a
    CLOSED_FOR_MAINT bay yields ERR_BAY_NOT_OPEN."

    Design: Corner/errors/bay_closed_for_maint_booking_rejected
    """
    bay = create_job_bay(bay_name="Bench-Maint")
    get_success_data(api.close_bay_for_maint(bay["id"], DISPATCHER))
    job = create_job(customer_user_id="cust-cm", service_type="REKEY",
                     requested_at_minute=600)
    res = api.create_bay_booking(
        create_bay_booking_payload(job["id"], bay["id"], 600, 640), DISPATCHER
    )
    validate_error(res, "ERR_BAY_NOT_OPEN", expected_status=409)


# ─── Corner: endpoints / bay_booking_disjoint_slot_succeeds ────────────────────
def test_bay_booking_disjoint_slot_succeeds(api):
    """PRD §3.11: "the new slot, running from its slot_start_minute to its
    slot_end_minute, collides with an existing booked slot of the same bay when the
    new slot's start is less than or equal to the existing slot's end and the existing
    slot's start is less than or equal to the new slot's end."

    Design: Corner/endpoints/bay_booking_disjoint_slot_succeeds
    """
    bay = create_job_bay(bay_name="Bench-Disjoint")
    job_a = create_job(customer_user_id="cust-dj-a", service_type="REKEY",
                       requested_at_minute=600)
    job_b = create_job(customer_user_id="cust-dj-b", service_type="REKEY",
                       requested_at_minute=700)
    validate_success(
        api.create_bay_booking(
            create_bay_booking_payload(job_a["id"], bay["id"], 600, 640), DISPATCHER), 201
    )
    # [700,740] shares no minute with [600,640] -> succeeds
    booking = validate_success(
        api.create_bay_booking(
            create_bay_booking_payload(job_b["id"], bay["id"], 700, 740), DISPATCHER), 201
    )
    assert booking["status"] == "BOOKED"
