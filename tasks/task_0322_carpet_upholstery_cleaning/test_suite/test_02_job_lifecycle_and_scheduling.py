"""Lifecycle and scheduling tests: state transitions, invalid-transition gates,
booking preconditions (crew availability, service-type match, slot overlap with
turnaround buffer), the reschedule cascade, crew-version OCC, the reserved-slot
conservation invariant, plan visit-count bubble-up, and job list filters.

Covers difficulty instances non_linear_state_machine (reschedule cycle),
priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, compensating_invariant (slot count), plus corner
state_machine, endpoint, and cross-cutting (OCC crew / reschedule) instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    setup_quoted_job,
    setup_booked_job,
    setup_completed_job,
    create_customer,
    create_catalog,
    create_crew,
    create_plan,
    create_job,
    add_room,
    quote_job,
    book_job,
    start_job,
    get_crew_version,
    get_job,
    get_slot_status_via_crew,
    count_reserved_slots,
    make_customer_headers,
    TEST_USERS,
)

CUSTOMER = TEST_USERS["customer_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]


# ─── non_linear_state_machine: reschedule cycle ───────────────

def test_reschedule_releases_old_slot_and_reserves_new(api):
    """PRD §3.3: "A successful reschedule is a two-hop slot cascade: the job's
    current slot is released, transitioning that slot RESERVED → RELEASED, and a
    fresh RESERVED slot is created on the new crew, with the job's
    scheduled_slot_id repointed to the new slot and the new crew's version
    incremented."

    Design: Difficulty/non_linear_state_machine/nonlinear_scheduled_slot_reschedule_cycle
    """
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")], start_minute=600, end_minute=720)
    crew = ctx["crew"]
    job = ctx["job"]
    slot_first = job["scheduled_slot_id"]

    crew_v2 = get_crew_version(crew["id"])
    res = api.reschedule_job(
        job["id"],
        {"crew_id": crew["id"], "start_minute": 900, "end_minute": 1020,
         "expected_crew_version": crew_v2},
        DISPATCHER)
    rescheduled = validate_success(res, 200)
    slot_second = rescheduled["scheduled_slot_id"]

    assert slot_second != slot_first, "scheduled_slot_id must repoint to a new slot"
    assert get_slot_status_via_crew(crew["id"], slot_first) == "RELEASED"
    assert get_slot_status_via_crew(crew["id"], slot_second) == "RESERVED"
    assert rescheduled["lifecycle_status"] == "BOOKED"


def test_reschedule_onto_different_crew_moves_reservation(api):
    """PRD §3.3: "A Dispatcher reschedules by supplying a new crew_id, start_minute,
    end_minute, and expected_crew_version for the crew being booked onto — possibly
    a different crew."
    PRD §3.3: "the job's current slot is released, transitioning that slot
    RESERVED → RELEASED, and a fresh RESERVED slot is created on the new crew."

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_release_then_reserve_on_reschedule
    """
    customer = create_customer()
    catalog = create_catalog()
    crew_old = create_crew(crew_name="OLD")
    crew_new = create_crew(crew_name="NEW")
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew_old, start_minute=600, end_minute=720)
    job = ctx["job"]
    slot_old = job["scheduled_slot_id"]

    new_v = get_crew_version(crew_new["id"])
    res = api.reschedule_job(
        job["id"],
        {"crew_id": crew_new["id"], "start_minute": 600, "end_minute": 720,
         "expected_crew_version": new_v},
        DISPATCHER)
    rescheduled = validate_success(res, 200)
    slot_new = rescheduled["scheduled_slot_id"]

    assert get_slot_status_via_crew(crew_old["id"], slot_old) == "RELEASED"
    assert get_slot_status_via_crew(crew_new["id"], slot_new) == "RESERVED"
    assert count_reserved_slots(crew_old["id"]) == 0, "old crew ends with 0 reserved slots"
    assert count_reserved_slots(crew_new["id"]) == 1, "new crew ends with 1 reserved slot"


# ─── priority_pair_validation_conflict ────────────────────────

def test_book_draft_job_fails_state_check_not_overlap(api):
    """PRD §2.6: "the target resource's state is checked: if the requested
    transition is not defined from the resource's current state, the request is
    rejected with the corresponding state error ... Only after all of these pass
    does the system evaluate the operation-specific business rules described in
    Section 3, such as room-count, crew compatibility, slot overlap."

    A DRAFT (never quoted) job whose interval also overlaps a reserved slot fails
    the state gate with ERR_JOB_NOT_QUOTED, never reaching the overlap check.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_temporal_on_book
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-PR", turnaround_buffer_minutes=0)
    # ALPHA occupies [600,720) on the crew.
    setup_booked_job(rooms=[("A", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    # BETA stays DRAFT (room added, never quoted) and targets the overlapping window.
    beta = create_job(customer, catalog["id"])
    add_room(beta, customer["id"], area_label="B", area_sqft=100, soiling_level="LIGHT")

    crew_v = get_crew_version(crew["id"])
    res = api.book_job(beta["id"],
                       {"crew_id": crew["id"], "start_minute": 650, "end_minute": 770,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_QUOTED", expected_status=409)


def test_book_wrong_service_type_crew_fails_referential(api):
    """PRD §3.3: "The crew's supported_service_type must equal the service type
    pinned by the job's catalog; a steam crew cannot take a dry job and vice versa,
    and a mismatch is rejected with ERR_SERVICE_TYPE_MISMATCH."

    A QUOTED STEAM job booked onto a DRY crew fails the service-type check.

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_fiscal_on_book
    """
    customer = create_customer()
    catalog = create_catalog(service_type="STEAM")
    dry_crew = create_crew(crew_name="Rig-DRY", supported_service_type="DRY")
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=dry_crew)
    crew_v = get_crew_version(dry_crew["id"])
    res = api.book_job(ctx["job"]["id"],
                       {"crew_id": dry_crew["id"], "start_minute": 600, "end_minute": 720,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_SERVICE_TYPE_MISMATCH", expected_status=409)


# ─── cross_entity_state_dependency ────────────────────────────

def test_book_onto_out_of_service_crew_rejected(api):
    """PRD §3.3: "The named crew must be AVAILABLE; booking onto an out-of-service
    crew is rejected with ERR_CREW_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/cross_book_requires_crew_available
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-OOS")
    validate_success(api.crew_out_of_service(crew["id"], DISPATCHER), 200)
    crew_v = get_crew_version(crew["id"])

    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew)
    res = api.book_job(ctx["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 600, "end_minute": 720,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_CREW_UNAVAILABLE", expected_status=409)


def test_quote_suspended_customer_job_rejected(api):
    """PRD §3.2: "Quoting also requires the owning customer to be ACTIVE; a
    suspended customer's quote attempt is rejected with ERR_CUSTOMER_SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/cross_quote_requires_customer_active
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Rm", area_sqft=100, soiling_level="LIGHT")
    validate_success(api.suspend_customer(customer["id"], SERVICE_MANAGER), 200)

    # Quote via ServiceManager (superset) so we exercise the suspended-state check,
    # not the ownership check.
    res = api.quote_job(job["id"], SERVICE_MANAGER)
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


# ─── resource_temporal_overlap ────────────────────────────────

def test_book_body_overlap_rejected(api):
    """PRD §3.3: "The requested interval must not collide with any RESERVED slot
    already on that crew once each existing slot is extended at its tail by the
    crew's turnaround_buffer_minutes: a new slot whose start falls within an
    existing slot's reserved-plus-buffer span overlaps and is rejected with
    ERR_SLOT_OVERLAP."

    Crew buffer 0 holds [600,720); a [700,760) request collides with the body.

    Design: Difficulty/resource_temporal_overlap/overlap_body_collision_on_crew
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-OV", turnaround_buffer_minutes=0)
    setup_booked_job(rooms=[("Rm1", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    two = setup_quoted_job(rooms=[("Rm2", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew)
    crew_v = get_crew_version(crew["id"])
    res = api.book_job(two["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 700, "end_minute": 760,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_SLOT_OVERLAP", expected_status=409)


def test_book_within_buffer_tail_rejected(api):
    """PRD §3.3: "The requested interval must not collide with any RESERVED slot
    already on that crew once each existing slot is extended at its tail by the
    crew's turnaround_buffer_minutes: a new slot whose start falls within an
    existing slot's reserved-plus-buffer span overlaps and is rejected with
    ERR_SLOT_OVERLAP."

    Crew buffer 30 holds [600,720); a [740,800) request starts inside the tail
    (740 < 720+30 = 750).

    Design: Difficulty/resource_temporal_overlap/overlap_buffer_adjacency_on_crew
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-BUF", turnaround_buffer_minutes=30)
    setup_booked_job(rooms=[("Rm1", 100, "LIGHT")], customer=customer, catalog=catalog,
                     crew=crew, start_minute=600, end_minute=720)
    two = setup_quoted_job(rooms=[("Rm2", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew)
    crew_v = get_crew_version(crew["id"])
    res = api.book_job(two["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 740, "end_minute": 800,
                        "expected_crew_version": crew_v},
                       DISPATCHER)
    validate_error(res, "ERR_SLOT_OVERLAP", expected_status=409)


# ─── compensating_invariant: reserved-slot count ──────────────

def test_cancel_booked_job_releases_slot_conserving_count(api):
    """PRD §3.3: "When a cancelled job from QUOTED or BOOKED has a RESERVED slot
    attached, that slot is released, transitioning it RESERVED → RELEASED, and the
    job's scheduled_slot_id is cleared."

    Book adds one RESERVED slot (0->1); cancel releases it (1->0), so the crew
    returns to zero reserved slots.

    Design: Difficulty/compensating_invariant/invariant_reserved_slot_count_conserved_on_book_then_cancel
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-CN")
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, catalog=catalog,
                           crew=crew, start_minute=600, end_minute=720)
    job = ctx["job"]
    slot_id = job["scheduled_slot_id"]

    res = api.cancel_job(job["id"], make_customer_headers(customer["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["scheduled_slot_id"] is None
    assert get_slot_status_via_crew(crew["id"], slot_id) == "RELEASED"
    assert count_reserved_slots(crew["id"]) == 0, "crew returns to 0 reserved slots"


# ─── corner: invalid transitions ──────────────────────────────

def test_quote_already_quoted_job_rejected(api):
    """PRD §3.2: "Rooms may only be added while the job is in DRAFT; adding a room
    to a job in any other lifecycle state is rejected with ERR_JOB_NOT_DRAFT."

    Quoting requires DRAFT; re-quoting a QUOTED job fails the DRAFT-only state gate.

    Design: Corner/state_machines/quote_from_already_quoted_returns_invalid_state
    """
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")])
    res = api.quote_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_JOB_NOT_DRAFT", expected_status=409)


def test_add_room_to_quoted_job_rejected(api):
    """PRD §3.2: "Rooms may only be added while the job is in DRAFT; adding a room
    to a job in any other lifecycle state is rejected with ERR_JOB_NOT_DRAFT."

    Design: Corner/state_machines/add_room_to_quoted_job_rejected
    """
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")])
    res = api.add_room(ctx["job"]["id"], {"area_label": "Late", "area_sqft": 50, "soiling_level": "LIGHT"},
                       make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_JOB_NOT_DRAFT", expected_status=409)


def test_start_unbooked_quoted_job_rejected(api):
    """PRD §3.3: "A Dispatcher starts a booked job, transitioning it
    BOOKED → IN_PROGRESS."

    Starting a QUOTED (never booked) job fails the BOOKED-state gate with
    ERR_JOB_NOT_BOOKED.

    Design: Corner/state_machines/start_unbooked_quoted_job_rejected
    """
    ctx = setup_quoted_job(rooms=[("Rm", 100, "LIGHT")])
    res = api.start_job(ctx["job"]["id"], DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_BOOKED", expected_status=409)


# ─── corner: completed_visit_count bubble-up ──────────────────

def test_completion_increments_plan_visit_count(api):
    """PRD §3.3: "If the job belongs to a recurring plan and that plan is ACTIVE,
    completion also increments the plan's completed_visit_count by one, a bubble-up
    recompute on the parent plan."

    Design: Corner/calculations/completed_visit_count_increments_on_completion
    """
    customer = create_customer()
    plan = create_plan(customer["id"], cadence="MONTHLY")
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], customer=customer, plan_id=plan["id"])
    plan_after = validate_success(api.get_recurring_plan(plan["id"], make_customer_headers(customer["id"])), 200)
    assert plan_after["completed_visit_count"] == 1, \
        f"completed_visit_count should bubble to 1, got {plan_after['completed_visit_count']}"


# ─── corner: OCC on crew booking ──────────────────────────────

def test_stale_crew_version_on_second_book_rejected(api):
    """PRD §2.9: "If another write has advanced that crew's version since the
    client last read it — for example, a prior booking that legitimately reserved
    an overlapping window and bumped the crew — the booking is operating on a stale
    view of the crew's slot map and is rejected with ERR_STALE_CREW_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_crew_version_on_second_book
    """
    customer = create_customer()
    catalog = create_catalog()
    crew = create_crew(crew_name="Rig-OCC")
    stale_version = crew["version"]  # version 1, before any booking

    # First job books successfully and bumps the crew version 1 -> 2.
    one = setup_quoted_job(rooms=[("R1", 100, "LIGHT")], customer=customer, catalog=catalog, crew=crew)
    book_job(one["job"], crew["id"], 0, 120, expected_crew_version=stale_version)

    # Second job carries the stale (pre-book) version 1.
    two = setup_quoted_job(rooms=[("R2", 100, "LIGHT")], customer=customer, catalog=catalog, crew=crew)
    res = api.book_job(two["job"]["id"],
                       {"crew_id": crew["id"], "start_minute": 600, "end_minute": 720,
                        "expected_crew_version": stale_version},
                       DISPATCHER)
    validate_error(res, "ERR_STALE_CREW_VERSION", expected_status=412)


# ─── corner: endpoint filters ─────────────────────────────────

def test_list_jobs_filtered_by_customer(api):
    """PRD §3.6: "Jobs can be listed and filtered by their customer_id, their
    service_catalog_id, their recurring_plan_id, their origin_job_id, their
    scheduled_slot_id, their invoice_id, or their lifecycle_status."

    Design: Corner/endpoints/list_jobs_by_customer_filtered
    """
    cust_a = create_customer(full_name="Filter A")
    cust_b = create_customer(full_name="Filter B")
    catalog = create_catalog()
    create_job(cust_a, catalog["id"])
    create_job(cust_a, catalog["id"])
    create_job(cust_b, catalog["id"])

    data, meta = _list(api.list_cleaning_jobs(SERVICE_MANAGER, params={"customer_id": cust_a["id"]}))
    assert meta["total_count"] == 2, f"customer A should have 2 jobs, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert all(j["customer_id"] == cust_a["id"] for j in data)


def test_list_jobs_filtered_by_origin(api):
    """PRD §3.6: "Jobs can be listed and filtered by their customer_id, their
    service_catalog_id, their recurring_plan_id, their origin_job_id, their
    scheduled_slot_id, their invoice_id, or their lifecycle_status."

    A granted claim spawns exactly one re-clean job whose origin_job_id points at
    the origin; the filter returns that single re-clean.

    Design: Corner/endpoints/list_reclean_jobs_by_origin
    """
    ctx = setup_completed_job(rooms=[("Rm", 100, "LIGHT")], completed_at_minute=800)
    customer = ctx["customer"]
    job_o = ctx["job"]
    hdr = make_customer_headers(customer["id"])
    claim = validate_success(api.file_claim(
        {"cleaning_job_id": job_o["id"], "reason": "x", "filed_at_minute": 900}, hdr), 201)
    validate_success(api.grant_claim(claim["id"], SERVICE_MANAGER), 200)

    data, meta = _list(api.list_cleaning_jobs(SERVICE_MANAGER, params={"origin_job_id": job_o["id"]}))
    assert meta["total_count"] == 1, f"one re-clean job expected, got {meta['total_count']}"
    assert data[0]["origin_job_id"] == job_o["id"]


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
