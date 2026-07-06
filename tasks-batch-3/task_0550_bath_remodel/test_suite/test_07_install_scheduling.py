"""The one-day install: state gate, crew certification gate, per-date capacity,
minimum lead time, validation precedence, and the book/cancel slot invariant.

Queue A (difficulty): cross_entity_state_dependency, resource_temporal_overlap
(crew capacity), boundary_precision_check (lead time),
priority_pair_validation_conflict (state beats capacity), compensating_invariant
(crew slot conserved).
Queue B (corner): validations + state_machines + endpoints install instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_crew, set_clock, refresh_project,
    setup_accepted_quote, setup_install_ready_project,
    setup_scheduled_install, setup_design_complete_project,
)

IC = TEST_USERS["install_coordinator_headers"]
DATE = "2026-06-01T00:00:00Z"


def _book(api, project_id, crew_id, install_date=DATE):
    return api.create_install_booking(
        {"project_id": project_id, "crew_id": crew_id, "install_date": install_date}, IC)


# --- Queue A: install gated by project permit status -----------------------

def test_install_on_permit_pending_project_rejected(api):
    """PRD §3.6: "Scheduling is permitted only from INSTALL_READY; from any other
    state it is refused with ERR_PROJECT_NOT_INSTALL_READY."

    Design: Difficulty/cross_entity_state_dependency/install_gated_by_project_permit_status
    """
    ctx = setup_accepted_quote(
        api, area=100.0, wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB")
    assert ctx["project"]["status"] == "PERMIT_PENDING"
    crew = create_crew(api, accessibility_certified=True)
    resp = _book(api, ctx["project"]["id"], crew["id"])
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_INSTALL_READY.value)


def test_install_succeeds_after_permit_approved(api):
    """PRD §3.5: "An APPROVED outcome sets permit_status to APPROVED and advances
    the project PERMIT_PENDING → INSTALL_READY."
    PRD §3.6: "When all checks pass, the booking is created in BOOKED status and
    the project advances INSTALL_READY → INSTALL_SCHEDULED."

    Design: Difficulty/cross_entity_state_dependency/install_gated_by_project_permit_status
    """
    ctx = setup_accepted_quote(
        api, area=100.0, wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB")
    validate_success(api.resolve_permit(ctx["project"]["id"], {"outcome": "APPROVED"}, IC), 200)
    project = refresh_project(api, ctx["project"]["id"])
    assert project["permit_status"] == "APPROVED"
    crew = create_crew(api, accessibility_certified=True)
    booking = validate_success(_book(api, ctx["project"]["id"], crew["id"]), 201)
    assert booking["status"] == "BOOKED"
    assert refresh_project(api, ctx["project"]["id"])["status"] == "INSTALL_SCHEDULED"


# --- Queue A: install gated by crew certification --------------------------

def test_install_on_non_certified_crew_rejected(api):
    """PRD §3.6: "If the project's requires_accessible_crew flag is true, the crew
    must be accessibility_certified, or the booking is refused with
    ERR_CREW_NOT_CERTIFIED — this is how a walk-in tub or barrier-free shower is
    steered to a qualified crew (the permit requirement itself is already enforced
    by the INSTALL_READY gate)."

    Design: Difficulty/cross_entity_state_dependency/install_gated_by_crew_certification
    """
    ctx = setup_install_ready_project(
        api, area=100.0, wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB")
    non_cert = create_crew(api, accessibility_certified=False)
    resp = _book(api, ctx["project"]["id"], non_cert["id"])
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED.value)


def test_install_on_certified_crew_succeeds(api):
    """PRD §3.6: "If the project's requires_accessible_crew flag is true, the crew
    must be accessibility_certified, or the booking is refused with
    ERR_CREW_NOT_CERTIFIED — this is how a walk-in tub or barrier-free shower is
    steered to a qualified crew (the permit requirement itself is already enforced
    by the INSTALL_READY gate)."

    Design: Difficulty/cross_entity_state_dependency/install_gated_by_crew_certification
    """
    ctx = setup_install_ready_project(
        api, area=100.0, wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB")
    cert = create_crew(api, accessibility_certified=True)
    booking = validate_success(_book(api, ctx["project"]["id"], cert["id"]), 201)
    assert booking["status"] == "BOOKED"
    assert booking["crew_id"] == cert["id"]


# --- Queue A: crew per-date capacity ---------------------------------------

def test_crew_at_capacity_same_date_rejected(api):
    """PRD §3.6: "A new booking is refused with ERR_CREW_AT_CAPACITY when the count
    of BOOKED bookings for that crew and date already equals the crew's
    max_installs_per_day."

    Design: Difficulty/resource_temporal_overlap/crew_at_capacity_same_install_date
    """
    crew = create_crew(api, max_installs_per_day=1, accessibility_certified=True)
    setup_scheduled_install(api, area=100.0, crew=crew, install_date=DATE,
                            wall_system="TILE_LOOK_ACRYLIC")  # fills the single slot
    ctx2 = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    resp = _book(api, ctx2["project"]["id"], crew["id"], DATE)
    validate_error(resp, ApiErrorId.ERR_CREW_AT_CAPACITY.value)


def test_crew_capacity_is_per_date(api):
    """PRD §3.6: "For a given crew and install_date, the number of slots already
    consumed is the count of that crew's install bookings on that date that are
    currently in BOOKED status; bookings that are COMPLETED or CANCELLED do not
    consume capacity."

    Design: Difficulty/resource_temporal_overlap/crew_at_capacity_same_install_date
    """
    crew = create_crew(api, max_installs_per_day=1, accessibility_certified=True)
    setup_scheduled_install(api, area=100.0, crew=crew, install_date=DATE,
                            wall_system="TILE_LOOK_ACRYLIC")  # fills 2026-06-01 only
    ctx2 = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    booking = validate_success(_book(api, ctx2["project"]["id"], crew["id"],
                                     "2026-06-02T00:00:00Z"), 201)
    assert booking["status"] == "BOOKED", "a different date has its own independent capacity"


# --- Queue A: install lead-time boundary -----------------------------------

def test_install_date_at_exact_minimum_lead_time_accepted(api):
    """PRD §3.6: "The install_date must be at least three days after the current
    logical-clock date; a date sooner than that minimum lead time is rejected with
    ERR_INSTALL_LEAD_TIME."

    Design: Difficulty/boundary_precision_check/install_lead_time_at_exact_min_days
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    crew = create_crew(api, max_installs_per_day=2)
    booking = validate_success(_book(api, ctx["project"]["id"], crew["id"],
                                     "2026-05-04T00:00:00Z"), 201)  # clock + 3 days
    assert booking["status"] == "BOOKED"
    assert refresh_project(api, ctx["project"]["id"])["status"] == "INSTALL_SCHEDULED"


def test_install_date_one_day_short_of_lead_time_rejected(api):
    """PRD §3.6: "The install_date must be at least three days after the current
    logical-clock date; a date sooner than that minimum lead time is rejected with
    ERR_INSTALL_LEAD_TIME."

    Design: Difficulty/boundary_precision_check/install_lead_time_at_exact_min_days
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    crew = create_crew(api, max_installs_per_day=2)
    resp = _book(api, ctx["project"]["id"], crew["id"], "2026-05-03T00:00:00Z")  # clock + 2 days
    validate_error(resp, ApiErrorId.ERR_INSTALL_LEAD_TIME.value)


# --- Queue A: state precondition beats capacity (precedence) ---------------

def test_state_error_beats_capacity_error(api):
    """PRD §2.5: "When a request could fail more than one check, the checks are
    evaluated in a fixed precedence so that the reported error is deterministic."
    PRD §3.6: "Scheduling is permitted only from INSTALL_READY; from any other
    state it is refused with ERR_PROJECT_NOT_INSTALL_READY."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_crew_capacity
    """
    crew = create_crew(api, max_installs_per_day=1, accessibility_certified=True)
    setup_scheduled_install(api, area=100.0, crew=crew, install_date=DATE,
                            wall_system="TILE_LOOK_ACRYLIC")  # crew now at capacity
    # A project left at DESIGN_COMPLETE (never accepted) — both the state gate and
    # the capacity gate would fail; the state gate (prio 7) wins over capacity (prio 9).
    other = setup_design_complete_project(api, area=100.0)
    resp = _book(api, other["project"]["id"], crew["id"], DATE)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_INSTALL_READY.value)


def test_state_gate_fires_when_only_state_violated(api):
    """PRD §3.6: "Scheduling is permitted only from INSTALL_READY; from any other
    state it is refused with ERR_PROJECT_NOT_INSTALL_READY."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_crew_capacity
    """
    crew = create_crew(api, max_installs_per_day=2)  # ample capacity, only state can fail
    other = setup_design_complete_project(api, area=100.0)
    resp = _book(api, other["project"]["id"], crew["id"], DATE)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_INSTALL_READY.value)


# --- Queue A: crew slot conserved across book+cancel -----------------------

def test_crew_slot_freed_allows_rebooking(api):
    """PRD §3.6: "Because a booked slot that is later cancelled leaves capacity
    exactly as it was before the booking, the book-then-cancel pair is a no-op on
    a crew's available slots for that date."

    Design: Difficulty/compensating_invariant/crew_slot_conserved_after_book_then_cancel
    """
    crew = create_crew(api, max_installs_per_day=1, accessibility_certified=True)
    ctx1 = setup_scheduled_install(api, area=100.0, crew=crew, install_date=DATE,
                                   wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_install_booking(ctx1["booking"]["id"], IC), 200)
    ctx2 = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    booking2 = validate_success(_book(api, ctx2["project"]["id"], crew["id"], DATE), 201)
    assert booking2["status"] == "BOOKED"
    assert refresh_project(api, ctx2["project"]["id"])["status"] == "INSTALL_SCHEDULED"


def test_cancelling_booking_releases_slot_and_reverts_project(api):
    """PRD §3.6: "cancellation is allowed only from BOOKED
    (ERR_BOOKING_INVALID_STATE), moves the booking BOOKED → CANCELLED, releases
    the crew's slot for that date, and — when it is the booking that is cancelled
    directly — returns the project INSTALL_SCHEDULED → INSTALL_READY".

    Design: Difficulty/compensating_invariant/crew_slot_conserved_after_book_then_cancel
    """
    crew = create_crew(api, max_installs_per_day=1, accessibility_certified=True)
    ctx1 = setup_scheduled_install(api, area=100.0, crew=crew, install_date=DATE,
                                   wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_install_booking(ctx1["booking"]["id"], IC), 200)
    booking = validate_success(api.get_install_booking(ctx1["booking"]["id"], IC), 200)
    assert booking["status"] == "CANCELLED"
    assert refresh_project(api, ctx1["project"]["id"])["status"] == "INSTALL_READY"


# --- Queue B (corner) ------------------------------------------------------

def test_install_on_inactive_crew_rejected(api):
    """PRD §3.6: "The chosen crew must be active (ERR_CREW_INACTIVE)."

    Design: Corner/validations/book_install_inactive_crew_rejected
    """
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    crew = create_crew(api, active=False)
    resp = _book(api, ctx["project"]["id"], crew["id"])
    validate_error(resp, ApiErrorId.ERR_CREW_INACTIVE.value)


def test_install_lead_time_short_rejected(api):
    """PRD §3.6: "The install_date must be at least three days after the current
    logical-clock date; a date sooner than that minimum lead time is rejected with
    ERR_INSTALL_LEAD_TIME."

    Design: Corner/validations/install_lead_time_one_day_short_rejected
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    crew = create_crew(api, max_installs_per_day=2)
    resp = _book(api, ctx["project"]["id"], crew["id"], "2026-05-03T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_INSTALL_LEAD_TIME.value)


def test_booking_cancel_reverts_project_to_install_ready(api):
    """PRD §3.6: "cancellation is allowed only from BOOKED
    (ERR_BOOKING_INVALID_STATE), moves the booking BOOKED → CANCELLED, releases
    the crew's slot for that date, and — when it is the booking that is cancelled
    directly — returns the project INSTALL_SCHEDULED → INSTALL_READY".

    Design: Corner/state_machines/install_booking_cancel_reverts_project_to_install_ready
    """
    ctx = setup_scheduled_install(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_install_booking(ctx["booking"]["id"], IC), 200)
    booking = validate_success(api.get_install_booking(ctx["booking"]["id"], IC), 200)
    assert booking["status"] == "CANCELLED"
    assert refresh_project(api, ctx["project"]["id"])["status"] == "INSTALL_READY"


def test_complete_cancelled_booking_rejected(api):
    """PRD §3.6: "On install day, the InstallCoordinator marks the booking
    complete, which is allowed only while the booking is BOOKED
    (ERR_BOOKING_INVALID_STATE)."

    Design: Corner/state_machines/complete_cancelled_booking_returns_invalid_state
    """
    ctx = setup_scheduled_install(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.cancel_install_booking(ctx["booking"]["id"], IC), 200)
    resp = api.complete_install_booking(ctx["booking"]["id"], IC)
    validate_error(resp, ApiErrorId.ERR_BOOKING_INVALID_STATE.value)


def test_book_install_unknown_crew_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/book_install_unknown_crew_returns_not_found
    """
    ctx = setup_install_ready_project(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    resp = _book(api, ctx["project"]["id"], NON_EXISTENT_UUID)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_FOUND.value)
