"""Composite setup helpers.

These encapsulate the multi-step API call chains required to drive the system into
the states individual tests assert against. Every helper builds its preconditions from
scratch (each test starts against an empty database) using only PRD-declared endpoints,
and uses the lenient get_success_data() validator so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_physician_headers,
    make_embryologist_headers,
    make_patient_headers,
)
from . import factories as f
from .constants import CLOCK_DEFAULT_UTC

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

# Standard three well-separated appointment windows on 2026-05-02 (30-min gaps,
# clear of the 15-minute provider buffer).
DEFAULT_APPT_WINDOWS = [
    ("2026-05-02T09:00:00Z", "2026-05-02T09:30:00Z"),
    ("2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"),
    ("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
]


# --------------------------------------------------------------------------- primitives
def create_physician(name="Dr A") -> str:
    resp = api_client.create_provider(
        f.create_provider_payload(full_name=name, provider_role="PHYSICIAN"), PLATFORM)
    return get_success_data(resp)["id"]


def create_embryologist(name="Emb A") -> str:
    resp = api_client.create_provider(
        f.create_provider_payload(full_name=name, provider_role="EMBRYOLOGIST"), PLATFORM)
    return get_success_data(resp)["id"]


def create_room(name="OR1") -> str:
    resp = api_client.create_procedure_room(
        f.create_procedure_room_payload(name=name, room_kind="RETRIEVAL_OR"), PLATFORM)
    return get_success_data(resp)["id"]


def create_tank(capacity_slots=10, name="Tank1") -> str:
    resp = api_client.create_storage_tank(
        f.create_storage_tank_payload(name=name, capacity_slots=capacity_slots), PLATFORM)
    return get_success_data(resp)["id"]


def create_patient(**overrides) -> dict:
    resp = api_client.create_patient(f.create_patient_payload(**overrides), COORD)
    return get_success_data(resp)


def get_patient_version(patient_id) -> int:
    resp = api_client.get_patient(patient_id, COORD)
    return get_success_data(resp)["version"]


def complete_eligible_consultation(patient_id, phys_id, amh_level=4.0,
                                   antral_follicle_count=20, patient_age_years=30) -> dict:
    """Create + complete a consultation so it is COMPLETED and (for amh>=0.5) ELIGIBLE."""
    resp = api_client.create_consultation(
        f.create_consultation_payload(
            patient_id, patient_age_years=patient_age_years, amh_level=amh_level,
            antral_follicle_count=antral_follicle_count),
        COORD)
    c_id = get_success_data(resp)["id"]
    phys_headers = make_physician_headers(phys_id)
    resp = api_client.complete_consultation(c_id, phys_headers)
    return get_success_data(resp)


def add_monitoring_appointments(cycle_id, phys_id, windows) -> list:
    """Create one MonitoringAppointment per (start, end) window. Returns appointment dicts."""
    appts = []
    for start, end in windows:
        resp = api_client.create_monitoring_appointment(
            f.create_monitoring_appointment_payload(cycle_id, phys_id, start, end), COORD)
        appts.append(get_success_data(resp))
    return appts


def list_patient_specimens(patient_id) -> list:
    resp = api_client.list_cryo_specimens(TEST_USERS["embryologist_headers"],
                                          params={"patient_id": patient_id})
    data = get_success_data(resp)
    return data


# --------------------------------------------------------------------------- cycle tiers
def setup_scheduled_cycle(amh_level=4.0, antral_follicle_count=20, patient_age_years=30) -> dict:
    """Patient + eligible consult + DRAFT cycle scheduled to SCHEDULED. Returns id bundle."""
    phys_id = create_physician("Dr Sched")
    patient = create_patient()
    consult = complete_eligible_consultation(
        patient["id"], phys_id, amh_level, antral_follicle_count, patient_age_years)
    resp = api_client.create_stimulation_cycle(
        f.create_cycle_payload(patient["id"], consult["id"]), COORD)
    cyc_id = get_success_data(resp)["id"]
    sched = get_success_data(api_client.schedule_cycle(cyc_id, COORD))
    return {
        "patient_id": patient["id"],
        "phys_id": phys_id,
        "consultation_id": consult["id"],
        "cycle_id": cyc_id,
        "scheduled_cycle": sched,
    }


def setup_monitoring_cycle(**kwargs) -> dict:
    """Scheduled cycle advanced to MONITORING via its first appointment."""
    b = setup_scheduled_cycle(**kwargs)
    appts = add_monitoring_appointments(b["cycle_id"], b["phys_id"], DEFAULT_APPT_WINDOWS[:1])
    b["appointments"] = appts
    return b


def setup_triggered_cycle(num_visits=3, **kwargs) -> dict:
    """Scheduled cycle with `num_visits` appointments, triggered to TRIGGERED."""
    b = setup_scheduled_cycle(**kwargs)
    appts = add_monitoring_appointments(
        b["cycle_id"], b["phys_id"], DEFAULT_APPT_WINDOWS[:num_visits])
    b["appointments"] = appts
    phys_headers = make_physician_headers(b["phys_id"])
    b["triggered_cycle"] = get_success_data(api_client.trigger_cycle(b["cycle_id"], phys_headers))
    return b


def setup_retrieved_cycle(mature_oocyte_count=2, tank_capacity=10, with_subscription=False,
                          oocytes_retrieved=12, retrieval_start="2026-05-10T08:00:00Z",
                          retrieval_end="2026-05-10T09:00:00Z", **consult_kwargs) -> dict:
    """Full clinical lifecycle to COMPLETED with `mature_oocyte_count` specimens stored.

    Returns id bundle including tank_id, cycle_id, specimen_ids, and (optionally)
    subscription_id when with_subscription=True.
    """
    phys_id = create_physician("Dr Retr")
    room_id = create_room("OR-Retr")
    tank_id = create_tank(tank_capacity, "Tank-Retr")
    patient = create_patient()
    sub_id = None
    if with_subscription:
        sub_id = get_success_data(
            api_client.create_storage_subscription(
                f.create_subscription_payload(patient["id"]), BILLING))["id"]
        api_client.record_subscription_payment(sub_id, BILLING)
    consult = complete_eligible_consultation(patient["id"], phys_id, **consult_kwargs)
    cyc_id = get_success_data(
        api_client.create_stimulation_cycle(
            f.create_cycle_payload(patient["id"], consult["id"]), COORD))["id"]
    api_client.schedule_cycle(cyc_id, COORD)
    add_monitoring_appointments(cyc_id, phys_id, DEFAULT_APPT_WINDOWS)
    phys_headers = make_physician_headers(phys_id)
    api_client.trigger_cycle(cyc_id, phys_headers)
    retrieved = get_success_data(api_client.retrieve_cycle(
        cyc_id,
        f.retrieve_payload(room_id, tank_id, mature_oocyte_count=mature_oocyte_count,
                           oocytes_retrieved=oocytes_retrieved,
                           retrieval_start=retrieval_start, retrieval_end=retrieval_end),
        phys_headers))
    specimen_ids = [s["id"] for s in list_patient_specimens(patient["id"])]
    return {
        "patient_id": patient["id"],
        "phys_id": phys_id,
        "room_id": room_id,
        "tank_id": tank_id,
        "consultation_id": consult["id"],
        "cycle_id": cyc_id,
        "subscription_id": sub_id,
        "specimen_ids": specimen_ids,
        "retrieved_cycle": retrieved,
    }


# --------------------------------------------------------------------------- subscriptions
def setup_active_subscription(patient_id=None) -> dict:
    """Patient + subscription activated (PENDING_ACTIVATION -> ACTIVE)."""
    if patient_id is None:
        patient_id = create_patient()["id"]
    sub_id = get_success_data(
        api_client.create_storage_subscription(
            f.create_subscription_payload(patient_id), BILLING))["id"]
    sub = get_success_data(api_client.record_subscription_payment(sub_id, BILLING))
    return {"patient_id": patient_id, "subscription_id": sub_id, "subscription": sub}


def set_clock(iso):
    return get_success_data(api_client.set_clock(iso, PLATFORM))


# --------------------------------------------------------------------------- directives
def create_directives(patient_id) -> dict:
    """Create an ACTIVE CONSENT and an ACTIVE DISPOSITION directive for a patient.

    Reads the patient's current version before each create so the OCC check passes.
    Returns {consent_id, disposition_id}.
    """
    p_headers = make_patient_headers(patient_id)
    v1 = get_patient_version(patient_id)
    consent = get_success_data(api_client.create_directive(
        f.create_directive_payload(patient_id, v1, directive_type="CONSENT"), p_headers))
    v2 = get_patient_version(patient_id)
    disp = get_success_data(api_client.create_directive(
        f.create_directive_payload(patient_id, v2, directive_type="DISPOSITION",
                                   disposition_action="THAW_TO_SELF"), p_headers))
    return {"consent_id": consent["id"], "disposition_id": disp["id"]}


def create_consent_only(patient_id) -> str:
    p_headers = make_patient_headers(patient_id)
    v1 = get_patient_version(patient_id)
    consent = get_success_data(api_client.create_directive(
        f.create_directive_payload(patient_id, v1, directive_type="CONSENT"), p_headers))
    return consent["id"]


# --------------------------------------------------------------------------- thaw workflow
def setup_thaw_ready(mature_oocyte_count=2, tank_capacity=10, with_subscription=True) -> dict:
    """Retrieved patient with stored specimens + ACTIVE consent/disposition + two physicians
    + an embryologist. Ready to request/authorize/execute a thaw.
    """
    bundle = setup_retrieved_cycle(
        mature_oocyte_count=mature_oocyte_count, tank_capacity=tank_capacity,
        with_subscription=with_subscription)
    phys2_id = create_physician("Dr Auth")
    emb_id = create_embryologist("Emb Exec")
    directives = create_directives(bundle["patient_id"])
    bundle["phys2_id"] = phys2_id
    bundle["emb_id"] = emb_id
    bundle.update(directives)
    return bundle


def request_thaw(patient_id, specimen_ids, requester_phys_id,
                 transfer_type="THAW_TO_TRANSFER") -> str:
    headers = make_physician_headers(requester_phys_id)
    resp = api_client.create_thaw_authorization(
        f.create_thaw_authorization_payload(patient_id, specimen_ids, transfer_type), headers)
    return get_success_data(resp)["id"]


def authorize_thaw(auth_id, authorizer_phys_id) -> dict:
    headers = make_physician_headers(authorizer_phys_id)
    return get_success_data(api_client.authorize_thaw(auth_id, headers))


# --------------------------------------------------------------------------- benefits/invoices
def setup_benefit_coverage(patient_id=None, annual_cap_cents=40000, covered_pct=0.5,
                           covered_service_types=None, employer_name="Acme") -> dict:
    if patient_id is None:
        patient_id = create_patient(employer_name=employer_name)["id"]
    resp = api_client.create_benefit_coverage(
        f.create_benefit_coverage_payload(
            patient_id, annual_cap_cents=annual_cap_cents, covered_pct=covered_pct,
            covered_service_types=covered_service_types or ["CYCLE"],
            employer_name=employer_name),
        BILLING)
    ben = get_success_data(resp)
    return {"patient_id": patient_id, "benefit_id": ben["id"], "benefit": ben}


def create_invoice(patient_id, service_type="CYCLE", line_items=None) -> dict:
    resp = api_client.create_invoice(
        f.create_invoice_payload(patient_id, service_type=service_type, line_items=line_items),
        BILLING)
    return get_success_data(resp)


def finalize_invoice(invoice_id) -> dict:
    return get_success_data(api_client.finalize_invoice(invoice_id, BILLING))


# Second-day appointment windows (used for a second cycle on the same provider so the
# 15-minute provider buffer does not falsely reject).
DAY2_APPT_WINDOWS = [
    ("2026-05-03T09:00:00Z", "2026-05-03T09:30:00Z"),
    ("2026-05-03T10:00:00Z", "2026-05-03T10:30:00Z"),
    ("2026-05-03T11:00:00Z", "2026-05-03T11:30:00Z"),
]


def setup_two_retrieval_cycles(first_start="2026-05-10T08:00:00Z",
                               first_end="2026-05-10T09:00:00Z", tank_capacity=10) -> dict:
    """One patient, one shared room, one shared tank, two cycles.

    Cycle 1 is fully retrieved into the room at [first_start, first_end); cycle 2 is
    driven to TRIGGERED and left ready for the caller to retrieve into the same room at
    whichever window the test needs (adjacent vs overlapping). Returns an id bundle.
    """
    phys_id = create_physician("Dr Room")
    room_id = create_room("OR-Shared")
    tank_id = create_tank(tank_capacity, "Tank-Shared")
    patient = create_patient()
    phys_headers = make_physician_headers(phys_id)

    consult1 = complete_eligible_consultation(patient["id"], phys_id)
    cyc1 = get_success_data(api_client.create_stimulation_cycle(
        f.create_cycle_payload(patient["id"], consult1["id"]), COORD))["id"]
    api_client.schedule_cycle(cyc1, COORD)
    add_monitoring_appointments(cyc1, phys_id, DEFAULT_APPT_WINDOWS)
    api_client.trigger_cycle(cyc1, phys_headers)
    api_client.retrieve_cycle(
        cyc1, f.retrieve_payload(room_id, tank_id, mature_oocyte_count=2,
                                 retrieval_start=first_start, retrieval_end=first_end),
        phys_headers)

    consult2 = complete_eligible_consultation(patient["id"], phys_id)
    cyc2 = get_success_data(api_client.create_stimulation_cycle(
        f.create_cycle_payload(patient["id"], consult2["id"]), COORD))["id"]
    api_client.schedule_cycle(cyc2, COORD)
    add_monitoring_appointments(cyc2, phys_id, DAY2_APPT_WINDOWS)
    api_client.trigger_cycle(cyc2, phys_headers)

    return {
        "patient_id": patient["id"],
        "phys_id": phys_id,
        "room_id": room_id,
        "tank_id": tank_id,
        "cycle1_id": cyc1,
        "cycle2_id": cyc2,
    }
