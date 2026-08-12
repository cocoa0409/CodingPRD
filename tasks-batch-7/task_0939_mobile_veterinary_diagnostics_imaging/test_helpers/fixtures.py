"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server against an empty database
before each individual test.  Setup calls use the lenient ``get_success_data``
validator so a broken precondition surfaces as a clear setup failure rather
than as a confusing assertion deep inside a test.

Identity threading: `ClinicUser`, `FieldTech` and `Specialist` are entity-backed
roles, so every ownership-gated call here uses ``make_clinic_user_headers``,
``make_field_tech_headers`` or ``make_specialist_headers`` with the real
entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_clinic_user_headers,
    make_field_tech_headers,
    make_specialist_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str, api=api_client) -> dict:
    """Drive the server's logical clock to a supplied instant."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — reference data
# --------------------------------------------------------------------------
def new_clinic(name="Test Referring Vet", address_zone="Z0", api=api_client, **overrides) -> dict:
    payload = {"name": name, "address_zone": address_zone}
    payload.update(overrides)
    return get_success_data(api.create_clinic(payload, ADMIN))


def new_contract(clinic_id, kind="PER_STUDY_LIST", valid_from="2026-05-01T00:00:00Z",
                 valid_until="2026-08-01T00:00:00Z", api=api_client, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "kind": kind,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return get_success_data(api.create_contract(payload, BILLING))


def new_mobile_unit(name="Test Van", api=api_client, **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return get_success_data(api.create_mobile_unit(payload, ADMIN))


def new_equipment(modality="ULTRASOUND", serial_label="US-1", assigned_unit_id=None,
                  api=api_client, **overrides) -> dict:
    payload = {"modality": modality, "serial_label": serial_label}
    if assigned_unit_id is not None:
        payload["assigned_unit_id"] = assigned_unit_id
    payload.update(overrides)
    return get_success_data(api.create_equipment(payload, ADMIN))


def calibrate(equipment_id, valid_from="2026-05-01T00:00:00Z",
              valid_until="2026-05-29T00:00:00Z", api=api_client) -> dict:
    return get_success_data(
        api.calibrate_equipment(
            equipment_id,
            {"calibration_valid_from": valid_from, "calibration_valid_until": valid_until},
            ADMIN,
        )
    )


def new_calibrated_equipment(assigned_unit_id, modality="ULTRASOUND", serial_label="US-1",
                             api=api_client) -> dict:
    """Register a modality unit on a van and give it a window containing the
    2026-05-04 test day, so its computed calibration_status reads VALID."""
    equipment = new_equipment(
        modality=modality, serial_label=serial_label,
        assigned_unit_id=assigned_unit_id, api=api,
    )
    calibrate(equipment["id"], api=api)
    return get_success_data(api.get_equipment(equipment["id"], ADMIN))


def new_technician(full_name="Test Technician", certified_modalities=("ULTRASOUND",),
                   api=api_client, **overrides) -> dict:
    payload = {"full_name": full_name, "certified_modalities": list(certified_modalities)}
    payload.update(overrides)
    return get_success_data(api.create_technician(payload, ADMIN))


def new_specialist(full_name="Test Specialist", modality_privileges=("ULTRASOUND",),
                   species_privileges=("CANINE",), stat_eligible=False,
                   api=api_client, **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "modality_privileges": list(modality_privileges),
        "species_privileges": list(species_privileges),
        "stat_eligible": stat_eligible,
    }
    payload.update(overrides)
    return get_success_data(api.create_specialist(payload, ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — routes and stops
# --------------------------------------------------------------------------
def new_route(mobile_unit_id, technician_id, service_date="2026-05-04",
              shift_start_minute=480, shift_end_minute=900, api=api_client, **overrides) -> dict:
    payload = {
        "mobile_unit_id": mobile_unit_id,
        "technician_id": technician_id,
        "service_date": service_date,
        "shift_start_minute": shift_start_minute,
        "shift_end_minute": shift_end_minute,
    }
    payload.update(overrides)
    return get_success_data(api.create_route(payload, SCHED))


def route_version(route_id, api=api_client) -> int:
    """Read the route's current version, as a client must before inserting a stop."""
    return get_success_data(api.get_route(route_id, SCHED))["version"]


def add_stop(route_id, clinic_id, planned_arrival_minute=540, service_minutes=45,
             drive_minutes_from_prev=20, stop_priority="ROUTINE",
             expected_route_version=None, api=api_client) -> dict:
    if expected_route_version is None:
        expected_route_version = route_version(route_id, api=api)
    payload = {
        "clinic_id": clinic_id,
        "planned_arrival_minute": planned_arrival_minute,
        "service_minutes": service_minutes,
        "drive_minutes_from_prev": drive_minutes_from_prev,
        "stop_priority": stop_priority,
        "expected_route_version": expected_route_version,
    }
    return get_success_data(api.add_route_stop(route_id, payload, SCHED))


def publish_route(route_id, api=api_client) -> dict:
    return get_success_data(api.publish_route(route_id, SCHED))


def dispatch_route(route_id, technician_id, api=api_client) -> dict:
    return get_success_data(
        api.dispatch_route(route_id, make_field_tech_headers(technician_id))
    )


def arrive_stop(stop_id, technician_id, api=api_client) -> dict:
    return get_success_data(
        api.arrive_stop(stop_id, make_field_tech_headers(technician_id))
    )


def depart_stop(stop_id, technician_id, api=api_client) -> dict:
    return get_success_data(
        api.depart_stop(stop_id, make_field_tech_headers(technician_id))
    )


def complete_route(route_id, technician_id, api=api_client) -> dict:
    return get_success_data(
        api.complete_route(route_id, make_field_tech_headers(technician_id))
    )


# --------------------------------------------------------------------------
# Tier 2 — referral, appointment, study
# --------------------------------------------------------------------------
def new_referral(clinic_id, patient_name="Test Patient", species="CANINE",
                 study_kind="TELERAD", requested_modality="ULTRASOUND",
                 priority="ROUTINE", clinical_history="screening",
                 api=api_client, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "patient_name": patient_name,
        "species": species,
        "study_kind": study_kind,
        "requested_modality": requested_modality,
        "priority": priority,
    }
    if clinical_history is not None:
        payload["clinical_history"] = clinical_history
    payload.update(overrides)
    return get_success_data(
        api.create_referral(payload, make_clinic_user_headers(clinic_id))
    )


def accept_referral(referral_id, api=api_client) -> dict:
    return get_success_data(api.accept_referral(referral_id, SCHED))


def new_appointment(referral_id, route_stop_id=None, api=api_client) -> dict:
    payload = {"referral_id": referral_id}
    if route_stop_id is not None:
        payload["route_stop_id"] = route_stop_id
    return get_success_data(api.create_appointment(payload, SCHED))


def accepted_referral_with_appointment(clinic_id, route_stop_id=None, api=api_client, **referral_overrides):
    """Submit a referral, accept it, and book the appointment.  Returns
    ``(referral, appointment)``."""
    referral = new_referral(clinic_id, api=api, **referral_overrides)
    accept_referral(referral["id"], api=api)
    appointment = new_appointment(referral["id"], route_stop_id=route_stop_id, api=api)
    return referral, appointment


def new_study(appointment_id, clinic_id, modality="ULTRASOUND", body_region="ABDOMEN",
              api=api_client) -> dict:
    return get_success_data(
        api.create_study(
            {"appointment_id": appointment_id, "modality": modality, "body_region": body_region},
            make_clinic_user_headers(clinic_id),
        )
    )


def upload_study(study_id, clinic_id, image_count=5, api=api_client) -> dict:
    return get_success_data(
        api.upload_study(study_id, {"image_count": image_count}, make_clinic_user_headers(clinic_id))
    )


def acquire_study(study_id, equipment_id, technician_id, image_count=5, api=api_client) -> dict:
    return get_success_data(
        api.acquire_study(
            study_id,
            {"equipment_id": equipment_id, "technician_id": technician_id, "image_count": image_count},
            make_field_tech_headers(technician_id),
        )
    )


def qc_study(study_id, technician_id, qc_result="ACCEPTED", api=api_client) -> dict:
    """Record the image-quality verdict.  Any FieldTech may record it — this
    operation carries no ownership clause whatsoever."""
    return get_success_data(
        api.qc_study(study_id, {"qc_result": qc_result}, make_field_tech_headers(technician_id))
    )


# --------------------------------------------------------------------------
# Tier 3 — reading and reporting lifecycle shortcuts
# --------------------------------------------------------------------------
def study_version(study_id, api=api_client) -> int:
    return get_success_data(api.get_study(study_id, SCHED))["version"]


def offer_read(study_id, specialist_id, expected_study_version=None, api=api_client) -> dict:
    if expected_study_version is None:
        expected_study_version = study_version(study_id, api=api)
    return get_success_data(
        api.create_read_assignment(
            {
                "study_id": study_id,
                "specialist_id": specialist_id,
                "expected_study_version": expected_study_version,
            },
            SCHED,
        )
    )


def accept_read(assignment_id, specialist_id, api=api_client) -> dict:
    return get_success_data(
        api.accept_assignment(assignment_id, make_specialist_headers(specialist_id))
    )


def decline_read(assignment_id, specialist_id, decline_reason="no capacity", api=api_client) -> dict:
    return get_success_data(
        api.decline_assignment(
            assignment_id, {"decline_reason": decline_reason},
            make_specialist_headers(specialist_id),
        )
    )


def hand_back_read(assignment_id, specialist_id, decline_reason="conflict of interest", api=api_client) -> dict:
    return get_success_data(
        api.hand_back_assignment(
            assignment_id, {"decline_reason": decline_reason},
            make_specialist_headers(specialist_id),
        )
    )


def offer_and_accept_read(study_id, specialist_id, api=api_client) -> dict:
    assignment = offer_read(study_id, specialist_id, api=api)
    accept_read(assignment["id"], specialist_id, api=api)
    return assignment


def draft_report(study_id, specialist_id, kind="FINAL", findings="normal", api=api_client) -> dict:
    return get_success_data(
        api.create_report(
            {"study_id": study_id, "kind": kind, "findings": findings},
            make_specialist_headers(specialist_id),
        )
    )


def publish_report(report_id, specialist_id, api=api_client) -> dict:
    return get_success_data(
        api.publish_report(report_id, make_specialist_headers(specialist_id))
    )


def draft_and_publish_report(study_id, specialist_id, kind="FINAL", findings="normal", api=api_client) -> dict:
    report = draft_report(study_id, specialist_id, kind=kind, findings=findings, api=api)
    return publish_report(report["id"], specialist_id, api=api)


def read_and_finalize(study_id, specialist_id, findings="normal", api=api_client):
    """Offer, accept, draft a FINAL report and publish it.  Returns
    ``(assignment, published_report)``; the study lands in FINALIZED."""
    assignment = offer_and_accept_read(study_id, specialist_id, api=api)
    report = draft_and_publish_report(study_id, specialist_id, kind="FINAL",
                                      findings=findings, api=api)
    return assignment, report


# --------------------------------------------------------------------------
# Tier 3 — equipment QC, billing hold, service status
# --------------------------------------------------------------------------
def record_qc_check(equipment_id, technician_id, result, note=None, api=api_client) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "performed_by_technician_id": technician_id,
        "result": result,
    }
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api.create_qc_check(payload, make_field_tech_headers(technician_id))
    )


def set_billing_hold(clinic_id, billing_hold_status, api=api_client) -> dict:
    return get_success_data(
        api.set_billing_hold(clinic_id, {"billing_hold_status": billing_hold_status}, BILLING)
    )


def set_service_status(unit_id, service_status, api=api_client) -> dict:
    return get_success_data(
        api.set_service_status(unit_id, {"service_status": service_status}, ADMIN)
    )


# --------------------------------------------------------------------------
# Tier 4 — invoices, postings and the prepaid block
# --------------------------------------------------------------------------
def open_invoice(clinic_id, period_start="2026-05-01", period_end="2026-05-31", api=api_client) -> dict:
    return get_success_data(
        api.create_invoice(
            {"clinic_id": clinic_id, "period_start": period_start, "period_end": period_end},
            BILLING,
        )
    )


def invoice_version(invoice_id, api=api_client) -> int:
    return get_success_data(api.get_invoice(invoice_id, BILLING))["version"]


def post_study(invoice_id, study_id, expected_invoice_version=None, api=api_client) -> dict:
    if expected_invoice_version is None:
        expected_invoice_version = invoice_version(invoice_id, api=api)
    return get_success_data(
        api.post_study_to_invoice(
            invoice_id,
            {"study_id": study_id, "expected_invoice_version": expected_invoice_version},
            BILLING,
        )
    )


def finalize_invoice(invoice_id, api=api_client) -> dict:
    return get_success_data(api.finalize_invoice(invoice_id, BILLING))


def contract_version(contract_id, api=api_client) -> int:
    return get_success_data(api.get_contract(contract_id, BILLING))["version"]


def block_purchase(contract_id, additional_studies, expected_contract_version=None, api=api_client) -> dict:
    if expected_contract_version is None:
        expected_contract_version = contract_version(contract_id, api=api)
    return get_success_data(
        api.block_purchase(
            contract_id,
            {
                "additional_studies": additional_studies,
                "expected_contract_version": expected_contract_version,
            },
            BILLING,
        )
    )


# --------------------------------------------------------------------------
# Tier 5 — whole-pipeline scenes
# --------------------------------------------------------------------------
def setup_mobile_scene(
    clinic_name="Mobile Vet",
    address_zone="Z0",
    contract_kind=None,
    block_purchased_studies=None,
    unit_name="Test Van",
    unit_overrides=None,
    equipment_modality="ULTRASOUND",
    equipment_serial="US-1",
    technician_name="Test Technician",
    technician_modalities=("ULTRASOUND",),
    service_date="2026-05-04",
    shift_start_minute=480,
    shift_end_minute=900,
    planned_arrival_minute=540,
    service_minutes=45,
    drive_minutes_from_prev=20,
    species="CANINE",
    referral_priority="ROUTINE",
    requested_modality="ULTRASOUND",
    study_modality="ULTRASOUND",
    body_regions=("ABDOMEN",),
    publish=True,
    dispatch=True,
    arrive=True,
    acquire=False,
    qc_result=None,
    image_count=5,
    study_clock_instants=None,
    api=api_client,
) -> dict:
    """Build a whole mobile-pipeline day: clinic (optionally with a contract),
    van, calibrated modality unit, technician, route, one stop, one accepted
    referral, one appointment and one study per body region.

    ``publish`` / ``dispatch`` / ``arrive`` walk the route forward;
    ``acquire`` acquires every study on the calibrated unit; ``qc_result``
    records the image-quality verdict on every acquired study.
    """
    clinic = new_clinic(clinic_name, address_zone, api=api)
    contract = None
    if contract_kind is not None:
        extra = {}
        if block_purchased_studies is not None:
            extra["block_purchased_studies"] = block_purchased_studies
        contract = new_contract(clinic["id"], kind=contract_kind, api=api, **extra)
    unit = new_mobile_unit(unit_name, api=api, **(unit_overrides or {}))
    equipment = new_calibrated_equipment(
        unit["id"], modality=equipment_modality, serial_label=equipment_serial, api=api
    )
    technician = new_technician(technician_name, technician_modalities, api=api)
    route = new_route(
        unit["id"], technician["id"], service_date=service_date,
        shift_start_minute=shift_start_minute, shift_end_minute=shift_end_minute, api=api,
    )
    stop = add_stop(
        route["id"], clinic["id"], planned_arrival_minute=planned_arrival_minute,
        service_minutes=service_minutes, drive_minutes_from_prev=drive_minutes_from_prev,
        api=api,
    )
    referral, appointment = accepted_referral_with_appointment(
        clinic["id"], route_stop_id=stop["id"], api=api,
        species=species, study_kind="MOBILE",
        requested_modality=requested_modality, priority=referral_priority,
    )
    studies = []
    for position, region in enumerate(body_regions):
        if study_clock_instants:
            set_clock(study_clock_instants[position], api=api)
        studies.append(
            new_study(appointment["id"], clinic["id"], modality=study_modality,
                      body_region=region, api=api)
        )
    if publish:
        publish_route(route["id"], api=api)
    if dispatch:
        dispatch_route(route["id"], technician["id"], api=api)
    if arrive:
        arrive_stop(stop["id"], technician["id"], api=api)
    if acquire:
        for study in studies:
            acquire_study(study["id"], equipment["id"], technician["id"],
                          image_count=image_count, api=api)
    if qc_result is not None:
        for study in studies:
            qc_study(study["id"], technician["id"], qc_result=qc_result, api=api)
    return {
        "clinic": clinic,
        "contract": contract,
        "unit": unit,
        "equipment": equipment,
        "technician": technician,
        "route": route,
        "stop": stop,
        "referral": referral,
        "appointment": appointment,
        "studies": studies,
    }


def setup_telerad_scene(
    clinic_name="Telerad Vet",
    address_zone="Z0",
    contract_kind=None,
    block_purchased_studies=None,
    technician_name="Hub QC Technician",
    technician_modalities=("ULTRASOUND",),
    species="CANINE",
    referral_priority="ROUTINE",
    requested_modality="ULTRASOUND",
    study_modality="ULTRASOUND",
    body_regions=("ABDOMEN",),
    upload=True,
    qc_result="ACCEPTED",
    image_count=5,
    api=api_client,
) -> dict:
    """Build a whole telerad pipeline: clinic (optionally with a contract), a
    QC technician, one accepted referral, one appointment with no route stop,
    and one study per body region — optionally uploaded and image-QC'd."""
    clinic = new_clinic(clinic_name, address_zone, api=api)
    contract = None
    if contract_kind is not None:
        extra = {}
        if block_purchased_studies is not None:
            extra["block_purchased_studies"] = block_purchased_studies
        contract = new_contract(clinic["id"], kind=contract_kind, api=api, **extra)
    technician = new_technician(technician_name, technician_modalities, api=api)
    referral, appointment = accepted_referral_with_appointment(
        clinic["id"], api=api, species=species, study_kind="TELERAD",
        requested_modality=requested_modality, priority=referral_priority,
    )
    studies = [
        new_study(appointment["id"], clinic["id"], modality=study_modality,
                  body_region=region, api=api)
        for region in body_regions
    ]
    if upload:
        for study in studies:
            upload_study(study["id"], clinic["id"], image_count=image_count, api=api)
        if qc_result is not None:
            for study in studies:
                qc_study(study["id"], technician["id"], qc_result=qc_result, api=api)
    return {
        "clinic": clinic,
        "contract": contract,
        "technician": technician,
        "referral": referral,
        "appointment": appointment,
        "studies": studies,
    }
