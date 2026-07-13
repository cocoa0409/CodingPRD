"""Composite setup helpers for multi-step test prerequisites (Newborn Screening PRD).

Each pytest test runs against a freshly restarted, empty server, so every fixture
builds its full precondition chain from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient) internally so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion failure.

Identity threading: after creating a Facility, ownership-gated BirthFacilityUser calls
use make_birth_facility_user_headers(facility["id"]); after creating a SpecialtyClinic,
the ownership-gated complete call uses make_specialty_clinician_headers(clinic["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_infant_payload,
    create_consent_payload,
    create_specimen_payload,
    create_receive_payload,
    create_screen_payload,
    report_metabolic_payload,
    point_of_care_cchd_payload,
    create_specialty_clinic_payload,
    create_referral_payload,
    create_appointment_payload,
    create_assay_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_birth_facility_user_headers,
    make_specialty_clinician_headers,
)

# Standard "satisfactory specimen" temporal profile:
#   birth 2026-02-27T06:00:00Z, collection +30h, received +18h transit, 5 spots.
BIRTH_DT = "2026-02-27T06:00:00Z"
COLLECT_DT = "2026-02-28T12:00:00Z"   # 30h after birth
RECEIVE_DT = "2026-03-01T06:00:00Z"   # 18h transit

_ADMIN = TEST_USERS["program_admin_headers"]
_LAB = TEST_USERS["lab_technician_headers"]
_COORD = TEST_USERS["follow_up_coordinator_headers"]


# ─── low-level helpers ────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, _ADMIN))


def create_facility(facility_type="HOSPITAL", state_region="CA", name="General Hospital"):
    res = api_client.create_facility(
        create_facility_payload(name=name, facility_type=facility_type,
                                state_region=state_region),
        _ADMIN,
    )
    return get_success_data(res)


def create_lab(state_region="CA", name="State Lab"):
    return create_facility(facility_type="LAB", state_region=state_region, name=name)


def infant_version(infant_id: str) -> int:
    """Re-read the infant's current version (needed before every OCC-protected write)."""
    inf = get_success_data(api_client.get_infant(infant_id, _LAB))
    return inf["version"]


def create_infant(facility, **overrides):
    """Register an infant at `facility` acting as its BirthFacilityUser owner."""
    hdr = make_birth_facility_user_headers(facility["id"])
    res = api_client.create_infant(
        create_infant_payload(facility["id"], **overrides), hdr
    )
    return get_success_data(res)


def create_hospital_and_infant(state_region="CA", **infant_overrides):
    """Facility (HOSPITAL) + one registered infant. Returns (facility, infant)."""
    facility = create_facility(state_region=state_region)
    infant = create_infant(facility, **infant_overrides)
    return facility, infant


def create_specimen(facility, infant, specimen_type="INITIAL",
                    collection_datetime=COLLECT_DT, expected_version=None):
    """Log a specimen for `infant`, threading the current infant version for OCC."""
    hdr = make_birth_facility_user_headers(facility["id"])
    version = expected_version if expected_version is not None else infant_version(infant["id"])
    res = api_client.create_specimen(
        create_specimen_payload(
            infant["id"], version,
            specimen_type=specimen_type,
            collection_datetime=collection_datetime,
        ),
        hdr,
    )
    return get_success_data(res)


def receive_specimen(specimen, received_datetime=RECEIVE_DT, blood_spot_count=5):
    res = api_client.receive_specimen(
        specimen["id"],
        create_receive_payload(received_datetime=received_datetime,
                               blood_spot_count=blood_spot_count),
        _LAB,
    )
    return get_success_data(res)


def open_screen(specimen):
    res = api_client.create_screen(create_screen_payload(specimen["id"]), _LAB)
    return get_success_data(res)


# ─── Tier 2/3: satisfactory specimen + screen ─────────────────────────
def create_satisfactory_specimen(state_region="CA", **infant_overrides):
    """Facility + infant + INITIAL specimen received SATISFACTORY (30h age, 18h transit,
    5 spots). Returns (facility, infant, specimen)."""
    facility, infant = create_hospital_and_infant(state_region=state_region, **infant_overrides)
    specimen = create_specimen(facility, infant)
    receive_specimen(specimen)
    specimen = get_success_data(api_client.get_specimen(specimen["id"], _LAB))
    return facility, infant, specimen


def create_screen_on_satisfactory(state_region="CA", **infant_overrides):
    """Satisfactory specimen with an open Screen (specimen -> IN_TESTING).
    Returns (facility, infant, specimen, screen)."""
    facility, infant, specimen = create_satisfactory_specimen(
        state_region=state_region, **infant_overrides
    )
    screen = open_screen(specimen)
    return facility, infant, specimen, screen


# ─── Tier 3/4: follow-up case scenarios ───────────────────────────────
def create_case_via_presumptive(critical_analyte_count=1, **infant_overrides):
    """Open a SHORT_TERM follow-up case by reporting metabolic PRESUMPTIVE_POSITIVE.
    Returns (facility, infant, specimen, screen, case)."""
    facility, infant, specimen, screen = create_screen_on_satisfactory(**infant_overrides)
    api_client.report_metabolic(
        screen["id"],
        report_metabolic_payload("PRESUMPTIVE_POSITIVE",
                                 critical_analyte_count=critical_analyte_count),
        _LAB,
    )
    cases, _meta = _list_cases_for_screen(screen["id"])
    case = cases[0]
    return facility, infant, specimen, screen, case


def create_case_via_cchd_fail(**infant_overrides):
    """Open a SHORT_TERM case via a CCHD FAIL (SpO2 85/88), leaving the specimen
    IN_TESTING and metabolic PENDING. Returns (facility, infant, specimen, screen, case)."""
    facility, infant, specimen, screen = create_screen_on_satisfactory(**infant_overrides)
    hdr = make_birth_facility_user_headers(facility["id"])
    api_client.report_point_of_care(
        screen["id"], point_of_care_cchd_payload(85, 88), hdr
    )
    cases, _meta = _list_cases_for_screen(screen["id"])
    case = cases[0]
    return facility, infant, specimen, screen, case


def _list_cases_for_screen(screen_id):
    res = api_client.list_follow_up_cases(_COORD, params={"screen_id": screen_id})
    body = res.json()
    return body["data"], body["meta"]


# ─── Tier 3: referral / appointment scenarios ─────────────────────────
def create_clinic(specialty="METABOLIC_GENETICS", concurrent_capacity=2,
                  name="Metabolic Genetics Clinic"):
    res = api_client.create_specialty_clinic(
        create_specialty_clinic_payload(name=name, specialty=specialty,
                                        concurrent_capacity=concurrent_capacity),
        _ADMIN,
    )
    return get_success_data(res)


def create_referral(case, clinic, referral_reason=None):
    reason = referral_reason if referral_reason is not None else clinic["specialty"]
    res = api_client.create_referral(
        create_referral_payload(case["id"], clinic["id"], reason), _COORD
    )
    return get_success_data(res)


def book_appointment(referral, start_datetime="2026-03-05T09:00:00Z",
                     end_datetime="2026-03-05T10:00:00Z"):
    res = api_client.create_confirmatory_appointment(
        create_appointment_payload(referral["id"], start_datetime, end_datetime), _COORD
    )
    return get_success_data(res)


def setup_case_with_referral(specialty="METABOLIC_GENETICS", concurrent_capacity=2,
                             referral_reason=None, critical_analyte_count=1,
                             clinic_name="Metabolic Genetics Clinic", **infant_overrides):
    """Case opened via PRESUMPTIVE_POSITIVE + a clinic + one REQUESTED referral.
    Returns dict(facility, infant, specimen, screen, case, clinic, referral)."""
    facility, infant, specimen, screen, case = create_case_via_presumptive(
        critical_analyte_count=critical_analyte_count, **infant_overrides
    )
    clinic = create_clinic(specialty=specialty, concurrent_capacity=concurrent_capacity,
                           name=clinic_name)
    referral = create_referral(case, clinic, referral_reason=referral_reason)
    return {
        "facility": facility, "infant": infant, "specimen": specimen,
        "screen": screen, "case": case, "clinic": clinic, "referral": referral,
    }


def setup_case_with_completed_referral(**infant_overrides):
    """Case + clinic + referral booked, appointment completed, referral resolved COMPLETED.
    Returns dict(facility, infant, specimen, screen, case, clinic, referral, appointment)."""
    ctx = setup_case_with_referral(**infant_overrides)
    appointment = book_appointment(ctx["referral"])
    # Complete the appointment as the owning clinic.
    clinic_hdr = make_specialty_clinician_headers(ctx["clinic"]["id"])
    api_client.complete_appointment(appointment["id"], {"attended": True}, clinic_hdr)
    # Resolve the referral COMPLETED.
    api_client.resolve_referral(ctx["referral"]["id"], {"outcome": "COMPLETED"}, _COORD)
    ctx["referral"] = get_success_data(
        api_client.get_referral(ctx["referral"]["id"], _COORD)
    )
    ctx["appointment"] = appointment
    return ctx


# ─── Tier 3: assay-run scenarios ──────────────────────────────────────
def create_lab_with_run(instrument_code="MSMS-1",
                        start_datetime="2026-03-02T09:00:00Z",
                        end_datetime="2026-03-02T10:00:00Z"):
    """LAB facility + one SCHEDULED assay run. Returns (lab, run)."""
    lab = create_lab()
    res = api_client.create_assay_run(
        create_assay_run_payload(lab["id"], instrument_code, start_datetime, end_datetime),
        _LAB,
    )
    run = get_success_data(res)
    return lab, run
