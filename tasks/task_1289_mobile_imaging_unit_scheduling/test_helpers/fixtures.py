"""Composite setup helpers for the Mobile Imaging Unit Scheduling API.

Each test runs against a freshly restarted server with an empty database, so
every fixture builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls go through the lenient get_success_data validator, so a
failed precondition surfaces as a clear "Setup step failed" error rather than a
confusing assertion deep inside a test.

The dominant preamble across the test suite is: clock -> facility -> unit ->
accreditation -> contract -> route plan -> site day -> publish -> technologist
-> staffing -> transport leg -> depart -> arrive -> begin-setup -> checklist ->
mark-ready -> start-service -> complete. The helpers below layer that chain so
each test controls only the values it cares about.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,
    DEFAULT_SERVICE_DATE,
    DEFAULT_WEEK_START,
)
from .factories import (
    create_accreditation_payload,
    create_appointment_payload,
    create_breakdown_payload,
    create_contract_payload,
    create_dose_record_payload,
    create_facility_payload,
    create_image_study_payload,
    create_route_plan_payload,
    create_setup_checklist_payload,
    create_site_day_payload,
    create_staffing_assignment_payload,
    create_technologist_payload,
    create_transport_leg_payload,
    create_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_facility_coordinator_headers,
    make_technologist_headers,
)

OPS = TEST_USERS["operations_director_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
RADIOLOGIST = TEST_USERS["reading_radiologist_headers"]


# ---------------------------------------------------------------------------
# Atomic creators (single POST each)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def create_facility(**overrides) -> dict:
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), OPS))


def create_unit(**overrides) -> dict:
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), OPS))


def create_accreditation(unit_id, modality="CT", **overrides) -> dict:
    payload = create_accreditation_payload(unit_id, modality=modality, **overrides)
    return get_success_data(api_client.create_accreditation(payload, COMPLIANCE))


def create_contract(facility_id, billing_model="PER_DAY", **overrides) -> dict:
    payload = create_contract_payload(facility_id, billing_model=billing_model, **overrides)
    return get_success_data(api_client.create_contract(payload, OPS))


def create_technologist(**overrides) -> dict:
    return get_success_data(
        api_client.create_technologist(create_technologist_payload(**overrides), OPS)
    )


def get_unit_fresh(unit_id) -> dict:
    return get_success_data(api_client.get_unit(unit_id, OPS))


def create_route_plan(unit_id, week_start_date=DEFAULT_WEEK_START) -> dict:
    """Create a DRAFT plan; the OCC field expected_unit_version is re-read from a
    fresh GET so the caller never has to track unit version bumps (PRD §2.7)."""
    unit = get_unit_fresh(unit_id)
    payload = create_route_plan_payload(unit_id, week_start_date, unit["version"])
    return get_success_data(api_client.create_route_plan(payload, OPS))


def add_site_day(plan_id, facility_id, contract_id, service_date=DEFAULT_SERVICE_DATE, **overrides) -> dict:
    payload = create_site_day_payload(plan_id, facility_id, contract_id, service_date, **overrides)
    return get_success_data(api_client.create_site_day(payload, OPS))


def publish_plan(plan_id) -> dict:
    return get_success_data(api_client.publish_route_plan(plan_id, OPS))


def assign_staffing(site_day_id, technologist_id, estimated_drive_minutes=30) -> dict:
    payload = create_staffing_assignment_payload(
        site_day_id, technologist_id, estimated_drive_minutes=estimated_drive_minutes
    )
    return get_success_data(api_client.create_staffing_assignment(payload, OPS))


def plan_transport_leg(site_day_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_transport_leg(create_transport_leg_payload(site_day_id, **overrides), OPS)
    )


def record_checklist(site_day_id, technologist_id, **overrides) -> dict:
    payload = create_setup_checklist_payload(site_day_id, **overrides)
    return get_success_data(
        api_client.create_setup_checklist(payload, make_technologist_headers(technologist_id))
    )


def record_checklist_item(checklist_id, technologist_id, item_key, passed, measured_value=None) -> dict:
    payload = {"item_key": item_key, "passed": passed}
    if measured_value is not None:
        payload["measured_value"] = measured_value
    return get_success_data(
        api_client.record_checklist_item(
            checklist_id, payload, make_technologist_headers(technologist_id)
        )
    )


def book_appointment(site_day_id, facility_id, patient_ref, **overrides) -> dict:
    """Book via the facility's own coordinator (ownership-gated, PRD §3.5)."""
    payload = create_appointment_payload(site_day_id, patient_ref, **overrides)
    return get_success_data(
        api_client.create_appointment(payload, make_facility_coordinator_headers(facility_id))
    )


def get_day_statement(site_day_id) -> dict:
    """Exactly one billing statement exists per closed day (PRD §3.9)."""
    data, _meta = _list(api_client.list_billing_statements(OPS, params={"site_day_id": site_day_id}))
    assert len(data) == 1, f"Expected exactly one statement for day {site_day_id}, got {len(data)}"
    return data[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Composite bundles
# ---------------------------------------------------------------------------

def setup_plan_context(
    billing_model="PER_DAY",
    modality="CT",
    week_start_date=DEFAULT_WEEK_START,
    facility_overrides=None,
    unit_overrides=None,
    contract_overrides=None,
    accreditation_overrides=None,
) -> dict:
    """Facility + unit + valid accreditation + contract + DRAFT plan (no site
    day yet). Used by placement-validation tests that need the failing create
    to be the first site-day call."""
    set_clock()
    # The facility must host the unit's modality (PRD §3.1); align the default
    # unless the caller explicitly overrides supported_modalities (e.g. the
    # modality-mismatch rejection test).
    merged_facility_overrides = {"supported_modalities": [modality]}
    merged_facility_overrides.update(facility_overrides or {})
    facility = create_facility(**merged_facility_overrides)
    unit = create_unit(modality=modality, **(unit_overrides or {}))
    accreditation = create_accreditation(unit["id"], modality=modality, **(accreditation_overrides or {}))
    contract = create_contract(facility["id"], billing_model=billing_model, **(contract_overrides or {}))
    plan = create_route_plan(unit["id"], week_start_date=week_start_date)
    return {
        "facility": facility,
        "unit": unit,
        "accreditation": accreditation,
        "contract": contract,
        "plan": plan,
    }


def setup_bookable_day(
    billing_model="PER_DAY",
    modality="CT",
    service_date=DEFAULT_SERVICE_DATE,
    week_start_date=DEFAULT_WEEK_START,
    publish=True,
    facility_overrides=None,
    unit_overrides=None,
    contract_overrides=None,
    day_overrides=None,
    accreditation_overrides=None,
) -> dict:
    """Facility + unit + valid accreditation + contract + plan + one SCHEDULED
    site day (plan optionally PUBLISHED). Returns a bundle dict."""
    bundle = setup_plan_context(
        billing_model=billing_model,
        modality=modality,
        week_start_date=week_start_date,
        facility_overrides=facility_overrides,
        unit_overrides=unit_overrides,
        contract_overrides=contract_overrides,
        accreditation_overrides=accreditation_overrides,
    )
    site_day = add_site_day(
        bundle["plan"]["id"],
        bundle["facility"]["id"],
        bundle["contract"]["id"],
        service_date,
        **(day_overrides or {}),
    )
    bundle["site_day"] = site_day
    if publish:
        bundle["plan"] = publish_plan(bundle["plan"]["id"])
    return bundle


def add_day_to_bundle(bundle, service_date, **overrides) -> dict:
    """Attach an additional site day (same plan/facility/contract) to a bundle."""
    day = add_site_day(
        bundle["plan"]["id"],
        bundle["facility"]["id"],
        bundle["contract"]["id"],
        service_date,
        **overrides,
    )
    return day


def drive_day_to_ready(bundle, site_day=None, technologist=None, staffing=None,
                       uplink_mbps=100, measured_amps=140, checklist_overrides=None) -> dict:
    """Walk a SCHEDULED day to READY: leg -> depart -> arrive -> begin-setup ->
    checklist (ALL_PASSED by default) -> mark-ready. Pass an existing `staffing`
    when the assignment was created earlier (e.g. after pre-booking
    appointments); pass `with_staffing=False` for the no-staff gate tests."""
    day = site_day or bundle["site_day"]
    if technologist is None:
        modality = bundle["unit"]["modality"]
        technologist = create_technologist(modality_certs=[modality])
    tech_headers = make_technologist_headers(technologist["id"])
    leg = plan_transport_leg(day["id"], destination_name=bundle["facility"]["name"])
    get_success_data(api_client.depart_site_day(day["id"], OPS))
    get_success_data(api_client.arrive_transport_leg(leg["id"], tech_headers))
    get_success_data(api_client.begin_setup_site_day(day["id"], OPS))
    checklist = record_checklist(
        day["id"],
        technologist["id"],
        measured_uplink_mbps=uplink_mbps,
        measured_amps=measured_amps,
        **(checklist_overrides or {}),
    )
    day = get_success_data(api_client.mark_ready_site_day(day["id"], OPS))
    bundle.update(
        {
            "site_day": day,
            "technologist": technologist,
            "leg": leg,
            "checklist": checklist,
        }
    )
    if staffing is not None:
        bundle["staffing"] = staffing
    return bundle


def drive_day_to_in_service(bundle, site_day=None, technologist=None, staffing=None,
                            uplink_mbps=100, measured_amps=140, checklist_overrides=None) -> dict:
    """Walk a SCHEDULED day to IN_SERVICE: staffing -> (READY path) -> start-service.
    Mutates and returns the bundle with technologist/staffing/leg/checklist."""
    day = site_day or bundle["site_day"]
    if technologist is None:
        modality = bundle["unit"]["modality"]
        technologist = create_technologist(modality_certs=[modality])
    if staffing is None:
        staffing = assign_staffing(day["id"], technologist["id"])
    bundle["staffing"] = staffing
    drive_day_to_ready(
        bundle,
        site_day=day,
        technologist=technologist,
        staffing=staffing,
        uplink_mbps=uplink_mbps,
        measured_amps=measured_amps,
        checklist_overrides=checklist_overrides,
    )
    day = get_success_data(api_client.start_service_site_day(day["id"], OPS))
    bundle["site_day"] = day
    return bundle


def complete_site_day(bundle, site_day_id=None) -> dict:
    day_id = site_day_id or bundle["site_day"]["id"]
    day = get_success_data(api_client.complete_site_day(day_id, OPS))
    bundle["site_day"] = day
    return day


def setup_in_service_day(billing_model="PER_DAY", modality="CT",
                         service_date=DEFAULT_SERVICE_DATE, uplink_mbps=100, **kwargs) -> dict:
    """Full preamble through IN_SERVICE."""
    bundle = setup_bookable_day(
        billing_model=billing_model, modality=modality, service_date=service_date, **kwargs
    )
    return drive_day_to_in_service(bundle, uplink_mbps=uplink_mbps)


def setup_completed_day(billing_model="PER_DAY", modality="CT",
                        service_date=DEFAULT_SERVICE_DATE, **kwargs) -> dict:
    """Full preamble through COMPLETED (zero appointments)."""
    bundle = setup_in_service_day(
        billing_model=billing_model, modality=modality, service_date=service_date, **kwargs
    )
    complete_site_day(bundle)
    return bundle


def complete_appointment_flow(bundle, appointment) -> dict:
    """REQUESTED -> CONFIRMED -> CHECKED_IN -> SCANNING -> COMPLETED."""
    appt_id = appointment["id"]
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    coord_headers = make_facility_coordinator_headers(bundle["facility"]["id"])
    get_success_data(api_client.confirm_appointment(appt_id, OPS))
    get_success_data(api_client.check_in_appointment(appt_id, coord_headers))
    get_success_data(api_client.begin_scan_appointment(appt_id, tech_headers))
    return get_success_data(api_client.complete_scan_appointment(appt_id, tech_headers))


def book_and_complete_appointment(bundle, patient_ref, scheduled_start="09:00", **overrides) -> dict:
    appt = book_appointment(
        bundle["site_day"]["id"], bundle["facility"]["id"], patient_ref,
        scheduled_start=scheduled_start, **overrides,
    )
    return complete_appointment_flow(bundle, appt)


def post_dose_record(appointment_id, technologist_id, dose_msv) -> dict:
    payload = create_dose_record_payload(appointment_id, technologist_id, dose_msv)
    return get_success_data(
        api_client.create_dose_record(payload, make_technologist_headers(technologist_id))
    )


def register_and_transmit_study(bundle, appointment_id, study_uid, size_mb) -> dict:
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    study = get_success_data(
        api_client.create_image_study(
            create_image_study_payload(appointment_id, study_uid, size_mb), tech_headers
        )
    )
    return get_success_data(api_client.transmit_image_study(study["id"], tech_headers))


def finalize_day_statement(site_day_id) -> dict:
    stmt = get_day_statement(site_day_id)
    return get_success_data(api_client.finalize_billing_statement(stmt["id"], OPS))


def setup_published_target_plan(bundle, week_start_date, placeholder_date) -> dict:
    """Second PUBLISHED plan for the same unit with a placeholder day, so a
    reschedule has a valid target (PRD §3.6)."""
    plan2 = create_route_plan(bundle["unit"]["id"], week_start_date=week_start_date)
    add_site_day(
        plan2["id"], bundle["facility"]["id"], bundle["contract"]["id"], placeholder_date
    )
    plan2 = publish_plan(plan2["id"])
    return plan2


def reschedule_day(source_day_id, target_plan, new_service_date, **time_overrides) -> dict:
    """Reschedule an INTERRUPTED day into a PUBLISHED target plan; the OCC field
    expected_route_plan_version is re-read fresh (PRD §2.7)."""
    fresh = get_success_data(api_client.get_route_plan(target_plan["id"], OPS))
    payload = {
        "target_route_plan_id": target_plan["id"],
        "expected_route_plan_version": fresh["version"],
        "new_service_date": new_service_date,
        "new_arrival_time": time_overrides.get("new_arrival_time", "07:00"),
        "new_first_patient_time": time_overrides.get("new_first_patient_time", "08:30"),
        "new_last_patient_time": time_overrides.get("new_last_patient_time", "16:00"),
        "new_departure_time": time_overrides.get("new_departure_time", "17:00"),
    }
    return get_success_data(api_client.reschedule_site_day(source_day_id, payload, OPS))


def report_breakdown(unit_id, severity, description, site_day_id=None, as_technologist_id=None) -> dict:
    payload = create_breakdown_payload(unit_id, severity, description)
    if site_day_id is not None:
        payload["site_day_id"] = site_day_id
    headers = (
        make_technologist_headers(as_technologist_id) if as_technologist_id else OPS
    )
    return get_success_data(api_client.create_breakdown(payload, headers))
