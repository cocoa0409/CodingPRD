"""Composite setup helpers for the Mobile & House-Call Veterinary Service API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server and empties the DB before each
test). Setup calls use get_success_data() so any setup failure surfaces clearly.

Identity threading: the Clinician role is entity_backed. After a Clinician is
created, every ownership-gated call (arrive / complete-visit / refer / estimate /
payment / euthanasia-log / specimen) uses make_clinician_headers(clinician_id)
with the real clinician id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_compliance_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock to a known instant (DEA-expiry / reminder math)."""
    return get_success_data(api.set_clock(to_iso8601, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 1/2: base entity builders
# ---------------------------------------------------------------------------

def create_service_area(zip_code="11201", name="BK North",
                        travel_surcharge_cents=0, euthanasia_allowed=True):
    payload = {
        "zip_code": zip_code,
        "name": name,
        "travel_surcharge_cents": travel_surcharge_cents,
        "euthanasia_allowed": euthanasia_allowed,
    }
    return get_success_data(api.create_service_area(payload, DISPATCHER))


def create_tech(full_name="Tech Default"):
    payload = {"full_name": full_name, "clinician_role": "TECH"}
    return get_success_data(api.create_clinician(payload, DISPATCHER))


def create_vet(full_name="Dr Vet", dea_number="AV1234567",
               dea_expires_on="2027-01-01T00:00:00Z"):
    payload = {
        "full_name": full_name,
        "clinician_role": "VET",
        "dea_number": dea_number,
        "dea_expires_on": dea_expires_on,
    }
    return get_success_data(api.create_clinician(payload, DISPATCHER))


def create_van(plate="VAN-1", controlled_stock_ml=50, vaccine_stock_count=10):
    payload = {
        "plate": plate,
        "controlled_stock_ml": controlled_stock_ml,
        "vaccine_stock_count": vaccine_stock_count,
    }
    return get_success_data(api.create_rolling_clinic(payload, DISPATCHER))


def create_patient(owner_name="Owner", species="DOG", weight_kg=30, home_zip="11201"):
    payload = {
        "owner_name": owner_name,
        "species": species,
        "weight_kg": weight_kg,
        "home_zip": home_zip,
    }
    return get_success_data(api.create_patient(payload, DISPATCHER))


def create_appointment(patient_id, visit_type="EXAM",
                       requested_start="2026-02-01T09:00:00Z",
                       requested_end="2026-02-01T10:00:00Z",
                       vaccine_doses=None):
    payload = {
        "patient_id": patient_id,
        "visit_type": visit_type,
        "requested_start": requested_start,
        "requested_end": requested_end,
    }
    if vaccine_doses is not None:
        payload["vaccine_doses"] = vaccine_doses
    return get_success_data(api.create_appointment(payload, DISPATCHER))


def create_route_day(clinician_id, rolling_clinic_id, service_date="2026-02-01T00:00:00Z"):
    payload = {
        "clinician_id": clinician_id,
        "rolling_clinic_id": rolling_clinic_id,
        "service_date": service_date,
    }
    return get_success_data(api.create_route_day(payload, DISPATCHER))


def book_stop(route_day_id, appointment_id, expected_version,
              window_start="2026-02-01T09:00:00Z", window_end="2026-02-01T10:00:00Z"):
    payload = {
        "appointment_id": appointment_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_route_day_version": expected_version,
    }
    return get_success_data(api.create_stop(route_day_id, payload, DISPATCHER))


def create_estimate(appointment_id, line_items, clinician_id):
    payload = {"appointment_id": appointment_id, "line_items": line_items}
    return get_success_data(
        api.create_estimate(payload, make_clinician_headers(clinician_id))
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — booked / in-visit scenarios
# ---------------------------------------------------------------------------

def setup_booked_appointment(visit_type="EXAM", travel_surcharge_cents=0,
                             euthanasia_allowed=True, vaccine_doses=None,
                             weight_kg=30, species="DOG", use_vet=False,
                             controlled_stock_ml=50, vaccine_stock_count=10,
                             service_date="2026-02-01T00:00:00Z",
                             window_start="2026-02-01T09:00:00Z",
                             window_end="2026-02-01T10:00:00Z",
                             requested_start="2026-02-01T09:00:00Z",
                             requested_end="2026-02-01T10:00:00Z"):
    """Active area + clinician + van + patient + appointment, booked to SCHEDULED.

    Returns a dict with area, clinician, van, patient, appointment, route_day,
    stop, and clinician_id. When use_vet is True the route lead is a VET (required
    for euthanasia bookings).
    """
    area = create_service_area(
        travel_surcharge_cents=travel_surcharge_cents,
        euthanasia_allowed=euthanasia_allowed,
    )
    clinician = create_vet() if use_vet else create_tech()
    van = create_van(controlled_stock_ml=controlled_stock_ml,
                     vaccine_stock_count=vaccine_stock_count)
    patient = create_patient(species=species, weight_kg=weight_kg)
    appointment = create_appointment(
        patient["id"], visit_type=visit_type,
        requested_start=requested_start, requested_end=requested_end,
        vaccine_doses=vaccine_doses,
    )
    route_day = create_route_day(clinician["id"], van["id"], service_date=service_date)
    stop = book_stop(route_day["id"], appointment["id"], route_day["version"],
                     window_start=window_start, window_end=window_end)
    return {
        "area": area,
        "clinician": clinician,
        "clinician_id": clinician["id"],
        "van": van,
        "patient": patient,
        "appointment": appointment,
        "route_day": route_day,
        "stop": stop,
    }


def setup_in_visit(visit_type="EXAM", **kwargs):
    """Booked appointment → lock route → arrive. Appointment is IN_VISIT.

    Returns the same dict as setup_booked_appointment (appointment reflects the
    pre-arrival snapshot; re-fetch via the API if a fresh status is needed).
    """
    ctx = setup_booked_appointment(visit_type=visit_type, **kwargs)
    clin_headers = make_clinician_headers(ctx["clinician_id"])
    get_success_data(api.lock_route_day(ctx["route_day"]["id"], DISPATCHER))
    get_success_data(api.arrive_appointment(ctx["appointment"]["id"], clin_headers))
    return ctx


def setup_in_visit_with_estimate(line_items, approve=True, visit_type="EXAM", **kwargs):
    """IN_VISIT appointment with an estimate (approved by default).

    Returns the setup dict plus 'estimate' key.
    """
    ctx = setup_in_visit(visit_type=visit_type, **kwargs)
    clin_headers = make_clinician_headers(ctx["clinician_id"])
    est = get_success_data(api.create_estimate(
        {"appointment_id": ctx["appointment"]["id"], "line_items": line_items},
        clin_headers,
    ))
    if approve:
        est = get_success_data(api.approve_estimate(est["id"], clin_headers))
    ctx["estimate"] = est
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: euthanasia controlled-med flow
# ---------------------------------------------------------------------------

def setup_euthanasia_in_visit(weight_kg=30, controlled_stock_ml=50,
                              clock="2026-02-01T08:00:00Z",
                              service_date="2026-02-01T00:00:00Z",
                              window_start="2026-02-01T09:00:00Z",
                              window_end="2026-02-01T10:00:00Z",
                              requested_start="2026-02-01T09:00:00Z",
                              requested_end="2026-02-01T10:00:00Z"):
    """A EUTHANASIA appointment IN_VISIT, VET-led route, plus a second witness VET.

    Sets the logical clock first so DEA expiry checks pass. Returns the setup dict
    augmented with 'witness_vet' / 'witness_vet_id'.
    """
    if clock is not None:
        set_clock(clock)
    area = create_service_area(euthanasia_allowed=True)
    vet = create_vet(full_name="Dr Vet A", dea_number="AV1234567")
    witness = create_vet(full_name="Dr Vet B", dea_number="BV7654321")
    van = create_van(controlled_stock_ml=controlled_stock_ml, vaccine_stock_count=0)
    patient = create_patient(species="DOG", weight_kg=weight_kg)
    appointment = create_appointment(
        patient["id"], visit_type="EUTHANASIA",
        requested_start=requested_start, requested_end=requested_end,
    )
    route_day = create_route_day(vet["id"], van["id"], service_date=service_date)
    stop = book_stop(route_day["id"], appointment["id"], route_day["version"],
                     window_start=window_start, window_end=window_end)
    clin_headers = make_clinician_headers(vet["id"])
    get_success_data(api.lock_route_day(route_day["id"], DISPATCHER))
    get_success_data(api.arrive_appointment(appointment["id"], clin_headers))
    return {
        "area": area,
        "vet": vet,
        "clinician_id": vet["id"],
        "witness_vet": witness,
        "witness_vet_id": witness["id"],
        "van": van,
        "patient": patient,
        "appointment": appointment,
        "route_day": route_day,
        "stop": stop,
    }


def dispense(appointment_id, van_id, vet_id, amount_ml):
    payload = {
        "rolling_clinic_id": van_id,
        "administering_vet_id": vet_id,
        "entry_type": "DISPENSE",
        "amount_ml": amount_ml,
    }
    return get_success_data(
        api.create_euthanasia_log(appointment_id, payload, make_clinician_headers(vet_id))
    )


def waste(appointment_id, van_id, vet_id, witness_id, amount_ml):
    payload = {
        "rolling_clinic_id": van_id,
        "administering_vet_id": vet_id,
        "entry_type": "WASTE",
        "amount_ml": amount_ml,
        "witness_vet_id": witness_id,
    }
    return get_success_data(
        api.create_euthanasia_log(appointment_id, payload, make_clinician_headers(vet_id))
    )


def setup_euthanasia_reconciled(dispense_ml=6.0, waste_ml=2.0, controlled_stock_ml=50,
                                clock="2026-02-01T08:00:00Z",
                                service_date="2026-02-01T00:00:00Z"):
    """Full euthanasia lifecycle through a RECONCILED route.

    Flow: euthanasia IN_VISIT → DISPENSE → WASTE → estimate(approve) →
    complete-visit → payment(invoice_total) → reconcile.
    Returns the setup dict plus 'estimate' and 'invoice_total_cents'.
    """
    ctx = setup_euthanasia_in_visit(controlled_stock_ml=controlled_stock_ml, clock=clock,
                                    service_date=service_date)
    vet_id = ctx["clinician_id"]
    clin_headers = make_clinician_headers(vet_id)
    appt_id = ctx["appointment"]["id"]
    van_id = ctx["van"]["id"]
    dispense(appt_id, van_id, vet_id, dispense_ml)
    waste(appt_id, van_id, vet_id, ctx["witness_vet_id"], waste_ml)
    est = get_success_data(api.create_estimate(
        {"appointment_id": appt_id,
         "line_items": [{"code": "EUTH_FEE", "label": "Euthanasia", "unit_cents": 30000, "qty": 1}]},
        clin_headers,
    ))
    est = get_success_data(api.approve_estimate(est["id"], clin_headers))
    get_success_data(api.complete_visit(appt_id, clin_headers))
    invoice = get_success_data(api.get_estimate(est["id"], clin_headers))
    inv_total = invoice["invoice_total_cents"]
    get_success_data(api.create_payment(
        {"estimate_id": est["id"], "amount_cents": inv_total, "method": "CARD"},
        clin_headers,
    ))
    get_success_data(api.reconcile_route_day(ctx["route_day"]["id"], COMPLIANCE))
    ctx["estimate"] = est
    ctx["invoice_total_cents"] = inv_total
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: completed / paid lifecycle
# ---------------------------------------------------------------------------

def setup_completed_exam(line_items=None, controlled_stock_ml=0, vaccine_stock_count=5,
                         service_date="2026-02-01T00:00:00Z"):
    """An EXAM appointment driven all the way to COMPLETED (paid).

    Returns the setup dict plus 'estimate' and 'invoice_total_cents'.
    """
    if line_items is None:
        line_items = [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}]
    ctx = setup_in_visit_with_estimate(
        line_items, approve=True, visit_type="EXAM",
        controlled_stock_ml=controlled_stock_ml, vaccine_stock_count=vaccine_stock_count,
        service_date=service_date,
    )
    clin_headers = make_clinician_headers(ctx["clinician_id"])
    appt_id = ctx["appointment"]["id"]
    get_success_data(api.complete_visit(appt_id, clin_headers))
    invoice = get_success_data(api.get_estimate(ctx["estimate"]["id"], clin_headers))
    inv_total = invoice["invoice_total_cents"]
    get_success_data(api.create_payment(
        {"estimate_id": ctx["estimate"]["id"], "amount_cents": inv_total, "method": "CASH"},
        clin_headers,
    ))
    ctx["invoice_total_cents"] = inv_total
    return ctx


def setup_locked_route_serviced(service_date="2026-02-06T00:00:00Z"):
    """A LOCKED route whose single EXAM stop has been SERVICED (and paid).

    Vehicle DEPLOYED, clinician ON_ROUTE, route ready to reconcile. Returns the
    completed-exam context (route_day, van, clinician, etc.).
    """
    return setup_completed_exam(service_date=service_date)
