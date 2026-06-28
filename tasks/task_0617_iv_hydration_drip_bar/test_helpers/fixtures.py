"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing downstream assertion failures.

The harness restarts the server before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. The logical clock
starts at 2026-01-01T00:00:00Z on each fresh server (PRD §2.4); helpers that need
a later clock set it explicitly.

Identity threading: the dispatched Nurse is entity_backed, so ownership-gated
start/complete calls use make_nurse_headers(nurse["id"]). MedicalDirector,
IntakeNurse and ClinicAdmin are opaque, so their identifiers are passed as
literal opaque strings via make_*_headers(...).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_menu_item_payload, create_add_on_payload, create_patient_payload,
    create_membership_payload, create_standing_order_payload, create_nurse_payload,
    create_lounge_payload, create_supply_lot_payload, create_dispatch_route_payload,
    create_appointment_payload, create_intake_payload, create_consent_payload,
)
from .test_users import (
    TEST_USERS, make_clinic_admin_headers, make_intake_nurse_headers,
    make_medical_director_headers, make_nurse_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_nurse_headers"]

DEFAULT_CLOCK = "2026-06-22T00:00:00Z"
DEFAULT_START = "2026-06-23T09:00:00Z"
FAR_EXPIRY = "2026-12-31T00:00:00Z"


# ─── Tier 0: Clock control ────────────────────────────────────────────────
def set_clock(iso8601):
    """Advance the server logical clock (ClinicAdmin-only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: Single-entity creators ───────────────────────────────────────
def create_menu_item(**overrides):
    return get_success_data(api_client.create_menu_item(
        create_menu_item_payload(**overrides), ADMIN))


def create_add_on(**overrides):
    return get_success_data(api_client.create_add_on(
        create_add_on_payload(**overrides), ADMIN))


def create_patient(**overrides):
    return get_success_data(api_client.create_patient(
        create_patient_payload(**overrides), ADMIN))


def create_lounge(**overrides):
    return get_success_data(api_client.create_lounge(
        create_lounge_payload(**overrides), ADMIN))


def create_membership(**overrides):
    return get_success_data(api_client.create_membership(
        create_membership_payload(**overrides), ADMIN))


def create_nurse(**overrides):
    return get_success_data(api_client.create_nurse(
        create_nurse_payload(**overrides), ADMIN))


def create_supply_lot(**overrides):
    return get_success_data(api_client.create_supply_lot(
        create_supply_lot_payload(**overrides), ADMIN))


def create_dispatch_route(nurse_id, **overrides):
    return get_success_data(api_client.create_dispatch_route(
        create_dispatch_route_payload(nurse_id, **overrides), ADMIN))


def create_active_standing_order(covered_tier="NAD", md_user_id="md-1",
                                 effective_from="2026-06-01T00:00:00Z",
                                 expires_at=FAR_EXPIRY):
    """Create a DRAFT standing order signed by md_user_id and activate it (PRD §3.3).
    The MedicalDirector is opaque: the caller's X-User-ID equals
    medical_director_user_id."""
    md_headers = make_medical_director_headers(md_user_id)
    order = get_success_data(api_client.create_standing_order(
        create_standing_order_payload(
            medical_director_user_id=md_user_id, covered_tier=covered_tier,
            effective_from=effective_from, expires_at=expires_at),
        md_headers))
    return get_success_data(api_client.activate_standing_order(order["id"], md_headers))


def create_draft_standing_order(covered_tier="NAD", md_user_id="md-1",
                                effective_from="2026-06-01T00:00:00Z",
                                expires_at=FAR_EXPIRY):
    """Create a standing order and LEAVE it in DRAFT (PRD §3.3)."""
    md_headers = make_medical_director_headers(md_user_id)
    return get_success_data(api_client.create_standing_order(
        create_standing_order_payload(
            medical_director_user_id=md_user_id, covered_tier=covered_tier,
            effective_from=effective_from, expires_at=expires_at),
        md_headers))


# ─── Tier 2: Appointment to a given lifecycle stage ───────────────────────
def create_requested_appointment(patient_id, menu_item_id, **overrides):
    """POST /appointments -> REQUESTED (PRD §3.4)."""
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(patient_id, menu_item_id, **overrides), ADMIN))


def submit_intake(appointment_id, author_user_id="intake-1", **flags):
    """POST /appointments/{id}/intake; authors + submits a screening, recomputes
    score + outcome, moves appointment to SCREEN_PENDING (PRD §3.5)."""
    headers = make_intake_nurse_headers(author_user_id)
    return get_success_data(api_client.intake_appointment(
        appointment_id, create_intake_payload(author_user_id=author_user_id, **flags),
        headers))


def sign_consent(appointment_id, witness_user_id="wit-1"):
    """POST /consents with signed_by_patient=true (PRD §3.6). witness_user_id must
    differ from the screening author."""
    return get_success_data(api_client.create_consent(
        create_consent_payload(appointment_id, witness_user_id=witness_user_id), ADMIN))


def current_version(appointment_id):
    """Read the appointment's live version for the schedule/approve OCC field."""
    return get_success_data(api_client.get_appointment(appointment_id, ADMIN))["version"]


def setup_screen_pending_appointment(menu_overrides=None, lounge_overrides=None,
                                     patient_overrides=None, appointment_overrides=None,
                                     intake_flags=None, with_consent=True,
                                     witness_user_id="wit-1",
                                     author_user_id="intake-1", clock=DEFAULT_CLOCK,
                                     with_lounge=True):
    """Clock + menu item + (lounge) + patient + appointment + intake (+ consent).

    Returns a dict with keys: menu_item, lounge (or None), patient, appointment.
    Leaves the appointment in SCREEN_PENDING with the computed screening. Supply
    is NOT created here (callers that test the scheduling path add lots
    themselves) — keeping this fixture minimal so consent/screening/state tests
    can use it directly.
    """
    if clock is not None:
        set_clock(clock)
    menu_item = create_menu_item(**(menu_overrides or {}))
    lounge = create_lounge(**(lounge_overrides or {})) if with_lounge else None
    patient = create_patient(**(patient_overrides or {}))
    ap_over = dict(appointment_overrides or {})
    if lounge is not None and "lounge_id" not in ap_over and ap_over.get("location_type", "LOUNGE") == "LOUNGE":
        ap_over["lounge_id"] = lounge["id"]
    appointment = create_requested_appointment(patient["id"], menu_item["id"], **ap_over)
    screening = submit_intake(appointment["id"], author_user_id=author_user_id,
                              **(intake_flags or {}))
    consent = None
    if with_consent:
        consent = sign_consent(appointment["id"], witness_user_id=witness_user_id)
    return {
        "menu_item": menu_item, "lounge": lounge, "patient": patient,
        "appointment": appointment, "screening": screening, "consent": consent,
    }


def setup_cleared_lounge_ready_to_schedule(menu_overrides=None, lounge_overrides=None,
                                           patient_overrides=None,
                                           appointment_overrides=None,
                                           supply_overrides=None,
                                           addon_supply=None,
                                           membership_overrides=None,
                                           clock=DEFAULT_CLOCK,
                                           with_consent=True,
                                           witness_user_id="wit-1"):
    """A LOUNGE appointment CLEARED (no contraindication flags) + consented, with a
    DRIP_BASE supply lot reserved-ready, sitting in SCREEN_PENDING, immediately
    before POST /schedule.

    membership_overrides: when given, a membership is created and linked to the
    patient and appointment.
    addon_supply: optional list of dicts -> creates ADDON supply lots.

    Returns a dict: menu_item, lounge, patient, appointment, membership (or None),
    drip_lot, addon_lots(list), version (current appointment version).
    """
    if clock is not None:
        set_clock(clock)
    # This fixture drives the appointment to SCHEDULED; unless the caller opts in
    # to the standing-order path, the booked drip must not require one (PRD §3.7),
    # otherwise scheduling would correctly fail ERR_NO_STANDING_ORDER. Default the
    # menu to requires_standing_order=False to match the documented cash visit.
    menu_over = dict(menu_overrides or {})
    menu_over.setdefault("requires_standing_order", False)
    menu_item = create_menu_item(**menu_over)
    lounge = create_lounge(**(lounge_overrides or {}))

    membership = None
    p_over = dict(patient_overrides or {})
    if membership_overrides is not None:
        membership = create_membership(**membership_overrides)
        p_over["membership_id"] = membership["id"]
    patient = create_patient(**p_over)

    # Drip supply lot (matches menu tier).
    drip_tier = menu_item["tier"]
    drip_lot = create_supply_lot(
        **{"item_kind": "DRIP_BASE", "tier_or_code": drip_tier,
           "lot_number": f"{drip_tier}-DRIP", "units_total": 5,
           "expires_at": FAR_EXPIRY, **(supply_overrides or {})})

    addon_lots = []
    for spec in (addon_supply or []):
        addon_lots.append(create_supply_lot(**spec))

    ap_over = dict(appointment_overrides or {})
    ap_over.setdefault("location_type", "LOUNGE")
    ap_over.setdefault("lounge_id", lounge["id"])
    if membership is not None:
        ap_over.setdefault("membership_id", membership["id"])
    appointment = create_requested_appointment(patient["id"], menu_item["id"], **ap_over)
    submit_intake(appointment["id"], author_user_id="intake-1")
    if with_consent:
        sign_consent(appointment["id"], witness_user_id=witness_user_id)

    return {
        "menu_item": menu_item, "lounge": lounge, "patient": patient,
        "appointment": appointment, "membership": membership,
        "drip_lot": drip_lot, "addon_lots": addon_lots,
        "version": current_version(appointment["id"]),
    }


def schedule_appointment(appointment_id, expected_version=None):
    """POST /appointments/{id}/schedule with the live (or supplied) version."""
    if expected_version is None:
        expected_version = current_version(appointment_id)
    return get_success_data(api_client.schedule_appointment(
        appointment_id, {"expected_appointment_version": expected_version}, ADMIN))


# ─── Tier 3: Full mobile / completion lifecycle ───────────────────────────
def setup_scheduled_lounge_appointment(menu_overrides=None, supply_units=5,
                                       clock=DEFAULT_CLOCK):
    """Lounge appointment driven all the way to SCHEDULED (cash MYERS by default).
    Returns dict: menu_item, lounge, patient, appointment, drip_lot, nurse(None)."""
    ctx = setup_cleared_lounge_ready_to_schedule(
        menu_overrides=menu_overrides,
        supply_overrides={"units_total": supply_units},
        clock=clock)
    ctx["appointment"] = schedule_appointment(ctx["appointment"]["id"], ctx["version"])
    return ctx


def setup_dispatched_lounge_appointment(menu_overrides=None, supply_units=5,
                                        nurse_user_id=None, clock=DEFAULT_CLOCK):
    """Lounge appointment SCHEDULED then DISPATCHED to a freshly created nurse.
    Returns dict adding 'nurse'. The dispatched nurse is entity_backed."""
    ctx = setup_scheduled_lounge_appointment(menu_overrides=menu_overrides,
                                             supply_units=supply_units, clock=clock)
    nurse = create_nurse()
    ctx["nurse"] = nurse
    api_client.dispatch_appointment(ctx["appointment"]["id"],
                                    {"nurse_id": nurse["id"]}, ADMIN)
    ctx["appointment"] = get_success_data(
        api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    return ctx


def setup_in_progress_lounge_appointment(menu_overrides=None, supply_units=5,
                                         start_clock="2026-06-23T09:05:00Z"):
    """Lounge appointment driven to IN_PROGRESS by the dispatched nurse.
    Advances the clock past start_at, then the nurse starts the infusion.
    Returns dict including 'nurse'."""
    ctx = setup_dispatched_lounge_appointment(menu_overrides=menu_overrides,
                                              supply_units=supply_units)
    set_clock(start_clock)
    nurse_headers = make_nurse_headers(ctx["nurse"]["id"])
    api_client.start_appointment(ctx["appointment"]["id"], nurse_headers)
    ctx["appointment"] = get_success_data(
        api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    return ctx


def setup_completed_lounge_appointment(menu_overrides=None, supply_units=5,
                                       start_clock="2026-06-23T09:05:00Z"):
    """Lounge appointment driven to COMPLETED by the dispatched nurse.
    Returns dict including 'nurse' and 'drip_lot'."""
    ctx = setup_in_progress_lounge_appointment(menu_overrides=menu_overrides,
                                               supply_units=supply_units,
                                               start_clock=start_clock)
    nurse_headers = make_nurse_headers(ctx["nurse"]["id"])
    api_client.complete_appointment(ctx["appointment"]["id"], nurse_headers)
    ctx["appointment"] = get_success_data(
        api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    ctx["drip_lot"] = get_success_data(
        api_client.get_supply_lot(ctx["drip_lot"]["id"], ADMIN))
    return ctx


# ─── Tier 4: Mobile route lifecycle ───────────────────────────────────────
def setup_mobile_route_with_dispatched_stop(turnaround_minutes=30,
                                            first_start="2026-06-23T09:00:00Z",
                                            duration_minutes=60,
                                            service_date="2026-06-23T00:00:00Z",
                                            clock=DEFAULT_CLOCK):
    """MYERS MOBILE route for a fresh nurse with one DISPATCHED stop.
    Returns dict: menu_item, nurse, route, patient, appointment(DISPATCHED)."""
    if clock is not None:
        set_clock(clock)
    menu_item = create_menu_item(requires_standing_order=False)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS",
                      lot_number="MY-MOBILE", units_total=5, expires_at=FAR_EXPIRY)
    nurse = create_nurse()
    route = create_dispatch_route(nurse["id"], service_date=service_date,
                                  turnaround_minutes=turnaround_minutes)
    patient = create_patient()
    appointment = create_requested_appointment(
        patient["id"], menu_item["id"], location_type="MOBILE",
        start_at=first_start, duration_minutes=duration_minutes)
    submit_intake(appointment["id"])
    sign_consent(appointment["id"])
    schedule_appointment(appointment["id"])
    api_client.dispatch_appointment(appointment["id"],
                                    {"nurse_id": nurse["id"], "route_id": route["id"]}, ADMIN)
    appointment = get_success_data(api_client.get_appointment(appointment["id"], ADMIN))
    route = get_success_data(api_client.get_dispatch_route(route["id"], ADMIN))
    return {"menu_item": menu_item, "nurse": nurse, "route": route,
            "patient": patient, "appointment": appointment}


def add_scheduled_mobile_stop(menu_item_id, nurse_id, start_at,
                              duration_minutes=60):
    """Create + schedule (no dispatch) a second MOBILE appointment for the same
    nurse, ready to attempt dispatch onto an existing route. Returns the
    SCHEDULED appointment."""
    patient = create_patient()
    appointment = create_requested_appointment(
        patient["id"], menu_item_id, location_type="MOBILE",
        start_at=start_at, duration_minutes=duration_minutes)
    submit_intake(appointment["id"])
    sign_consent(appointment["id"])
    schedule_appointment(appointment["id"])
    return get_success_data(api_client.get_appointment(appointment["id"], ADMIN))


# ─── Tier 5: Adverse-event lifecycle ──────────────────────────────────────
def setup_reported_adverse_event(severity="MODERATE", description="flushing"):
    """Drive a lounge appointment to IN_PROGRESS, then report an adverse event by
    the dispatched nurse. Returns dict: appointment, nurse, patient, adverse_event."""
    ctx = setup_in_progress_lounge_appointment()
    nurse = ctx["nurse"]
    nurse_headers = make_nurse_headers(nurse["id"])
    ae = get_success_data(api_client.create_adverse_event(
        {"appointment_id": ctx["appointment"]["id"], "reported_by_user_id": nurse["id"],
         "severity": severity, "description": description}, nurse_headers))
    return {"appointment": ctx["appointment"], "nurse": nurse,
            "patient": ctx["patient"], "adverse_event": ae}
