"""Composite setup helpers for the IRF Admission & Compliance API.

Every test starts against an empty database, so all preconditions are built
here from PRD-declared endpoints only. Helpers use the lenient
`get_success_data()` validator so a broken precondition surfaces as a setup
failure rather than a confusing assertion failure.

Clinician-backed roles thread identity: whenever a helper acts as a
NurseCaseManager, RehabPhysician, TherapyLead or HimCoder it builds the headers
from the real `Clinician.id` created earlier in the same helper.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    admit_admission_payload,
    complete_assessment_payload,
    create_admission_payload,
    create_assessment_payload,
    create_clinician_payload,
    create_compliance_review_payload,
    create_facility_payload,
    create_patient_payload,
    create_plan_of_care_payload,
    create_qrp_assessment_payload,
    create_screening_payload,
    create_team_conference_payload,
    create_therapy_session_payload,
    create_therapy_week_payload,
    discharge_admission_payload,
    grant_week_exception_payload,
    review_screening_payload,
    void_session_payload,
)
from .test_users import (
    TEST_USERS,
    make_coder_headers,
    make_nurse_headers,
    make_physician_headers,
    make_therapy_lead_headers,
)

OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER_HEADERS = TEST_USERS["second_compliance_officer_headers"]

# Staff roster used by `setup_facility_with_staff`: key -> (credential, npi).
STAFF_ROSTER = {
    "nurse": ("NURSE", "1000000001"),
    "physician": ("REHAB_PHYSICIAN", "1000000002"),
    "pt": ("THERAPIST_PT", "1000000003"),
    "coder": ("CODER", "1000000004"),
    "pt2": ("THERAPIST_PT", "1000000005"),
    "coder2": ("CODER", "1000000006"),
    "ot": ("THERAPIST_OT", "1000000007"),
    "slp": ("THERAPIST_SLP", "1000000008"),
    "physician2": ("REHAB_PHYSICIAN", "1000000009"),
    "nurse2": ("NURSE", "1000000010"),
}

STAFF_FULL_NAMES = {
    "nurse": "Dana Whitfield",
    "physician": "Dr. Elena Marsh",
    "pt": "Owen Petrov",
    "coder": "Casey Delgado",
    "pt2": "Priya Raman",
    "coder2": "Marcus Cole",
    "ot": "Tessa Nolan",
    "slp": "Sam Larkin",
    "physician2": "Dr. Ravi Anand",
    "nurse2": "Ingrid Solvang",
}

DEFAULT_STAFF = ("nurse", "physician", "pt", "coder")


def headers_for_credential(credential: str, clinician_id: str) -> dict:
    """Role headers matching a clinician's credential (PRD §2.1)."""
    if credential == "NURSE":
        return make_nurse_headers(clinician_id)
    if credential == "REHAB_PHYSICIAN":
        return make_physician_headers(clinician_id)
    if credential in ("THERAPIST_PT", "THERAPIST_OT", "THERAPIST_SLP"):
        return make_therapy_lead_headers(clinician_id)
    if credential == "CODER":
        return make_coder_headers(clinician_id)
    raise ValueError(f"Unknown credential {credential!r}")


# --------------------------------------------------------------------------- #
# Tier 1 — primitives
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str, headers: dict = None) -> dict:
    """Move the logical clock (PRD §2.4). Returns the clock response payload."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or OFFICER_HEADERS)
    )


def register_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides),
                                   OFFICER_HEADERS)
    )


def register_clinician(facility_id: str, credential: str, npi: str,
                       full_name: str = "Test Clinician", **overrides) -> dict:
    payload = create_clinician_payload(
        facility_id, credential=credential, npi=npi, full_name=full_name,
        **overrides
    )
    return get_success_data(api_client.create_clinician(payload, OFFICER_HEADERS))


def deactivate_clinician(clinician_id: str) -> dict:
    return get_success_data(
        api_client.deactivate_clinician(clinician_id, OFFICER_HEADERS)
    )


def register_patient(env: dict, mrn: str = "MRN-A", nurse_key: str = "nurse",
                     **overrides) -> dict:
    payload = create_patient_payload(env["facility_id"], mrn=mrn, **overrides)
    return get_success_data(
        api_client.create_patient(payload, env[f"{nurse_key}_headers"])
    )


def read_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, OFFICER_HEADERS))


def read_admission(admission_id: str) -> dict:
    return get_success_data(api_client.get_admission(admission_id, OFFICER_HEADERS))


def read_screening(screening_id: str) -> dict:
    return get_success_data(api_client.get_screening(screening_id, OFFICER_HEADERS))


def read_therapy_week(week_id: str) -> dict:
    return get_success_data(api_client.get_therapy_week(week_id, OFFICER_HEADERS))


def read_therapy_session(session_id: str) -> dict:
    return get_success_data(api_client.get_therapy_session(session_id,
                                                           OFFICER_HEADERS))


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_assessment(assessment_id, OFFICER_HEADERS))


def read_compliance_review(review_id: str) -> dict:
    return get_success_data(
        api_client.get_compliance_review(review_id, OFFICER_HEADERS)
    )


def read_qrp_assessment(qrp_id: str) -> dict:
    return get_success_data(api_client.get_qrp_assessment(qrp_id, OFFICER_HEADERS))


# --------------------------------------------------------------------------- #
# Tier 2 — facility with staff
# --------------------------------------------------------------------------- #
def setup_facility_with_staff(staff=DEFAULT_STAFF,
                              clock: str = TEST_DEFAULTS["SETUP_CLOCK"],
                              **facility_overrides) -> dict:
    """Move the clock, register a facility, then register the named staff.

    Returns a dict carrying `facility`, `facility_id`, one entry per staff key
    and a matching `<key>_headers` entry built from that clinician's own `id`.
    """
    if clock is not None:
        set_clock(clock)
    facility = register_facility(**facility_overrides)
    env = {"facility": facility, "facility_id": facility["id"], "staff_keys": []}
    for key in staff:
        credential, npi = STAFF_ROSTER[key]
        clinician = register_clinician(
            facility["id"], credential, npi,
            full_name=STAFF_FULL_NAMES.get(key, f"Test {key}"),
        )
        env[key] = clinician
        env[f"{key}_headers"] = headers_for_credential(credential, clinician["id"])
        env["staff_keys"].append(key)
    return env


def add_staff(env: dict, key: str, npi: str = None, credential: str = None) -> dict:
    """Register one more clinician at the facility and thread its headers."""
    default_credential, default_npi = STAFF_ROSTER[key]
    credential = credential or default_credential
    npi = npi or default_npi
    clinician = register_clinician(
        env["facility_id"], credential, npi,
        full_name=STAFF_FULL_NAMES.get(key, f"Test {key}"),
    )
    env[key] = clinician
    env[f"{key}_headers"] = headers_for_credential(credential, clinician["id"])
    env["staff_keys"].append(key)
    return clinician


# --------------------------------------------------------------------------- #
# Tier 3 — screening / admission lifecycle
# --------------------------------------------------------------------------- #
def create_draft_screening(env: dict, patient_id: str, screener_key: str = "nurse",
                           nurse_key: str = "nurse", **overrides) -> dict:
    payload = create_screening_payload(
        patient_id, env[screener_key]["id"], **overrides
    )
    return get_success_data(
        api_client.create_screening(payload, env[f"{nurse_key}_headers"])
    )


def submit_screening(env: dict, screening_id: str, nurse_key: str = "nurse") -> dict:
    return get_success_data(
        api_client.submit_screening(screening_id, env[f"{nurse_key}_headers"])
    )


def review_screening(env: dict, screening_id: str, decision: str = "CONCUR",
                     reviewer_key: str = "physician", **overrides) -> dict:
    return get_success_data(
        api_client.review_screening(
            screening_id, review_screening_payload(decision, **overrides),
            env[f"{reviewer_key}_headers"],
        )
    )


def create_concurred_screening(env: dict, patient_id: str,
                               screener_key: str = "nurse",
                               reviewer_key: str = "physician",
                               nurse_key: str = "nurse",
                               **overrides) -> dict:
    """DRAFT -> SUBMITTED -> PHYSICIAN_CONCURRED (PRD §3.2)."""
    screening = create_draft_screening(
        env, patient_id, screener_key=screener_key, nurse_key=nurse_key, **overrides
    )
    submit_screening(env, screening["id"], nurse_key=nurse_key)
    return review_screening(env, screening["id"], "CONCUR",
                            reviewer_key=reviewer_key)


def open_admission(env: dict, patient_id: str, screening_id: str,
                   nurse_key: str = "nurse", **overrides) -> dict:
    payload = create_admission_payload(patient_id, screening_id, **overrides)
    return get_success_data(
        api_client.create_admission(payload, env[f"{nurse_key}_headers"])
    )


def admit(env: dict, admission_id: str, admitted_at: str = None,
          nurse_key: str = "nurse", advance_clock: bool = True) -> dict:
    admitted_at = admitted_at or TEST_DEFAULTS["ADMITTED_AT"]
    if advance_clock:
        set_clock(admitted_at)
    return get_success_data(
        api_client.admit_admission(admission_id,
                                   admit_admission_payload(admitted_at),
                                   env[f"{nurse_key}_headers"])
    )


def discharge(env: dict, admission_id: str, discharged_at: str,
              discharge_destination: str = "COMMUNITY",
              discharge_planned: bool = True, nurse_key: str = "nurse",
              advance_clock: bool = True) -> dict:
    if advance_clock:
        set_clock(discharged_at)
    payload = discharge_admission_payload(
        discharged_at, discharge_destination, discharge_planned
    )
    return get_success_data(
        api_client.discharge_admission(admission_id, payload,
                                       env[f"{nurse_key}_headers"])
    )


# --------------------------------------------------------------------------- #
# Tier 3 — plan of care, therapy weeks and sessions
# --------------------------------------------------------------------------- #
def sign_plan_of_care(env: dict, admission_id: str, physician_key: str = "physician",
                      expected_admission_version: int = None, **overrides) -> dict:
    """Sign a plan of care, pinning the admission's current version (PRD §2.7)."""
    if expected_admission_version is None:
        expected_admission_version = read_admission(admission_id)["version"]
    payload = create_plan_of_care_payload(
        admission_id, expected_admission_version, **overrides
    )
    return get_success_data(
        api_client.create_plan_of_care(payload, env[f"{physician_key}_headers"])
    )


def open_therapy_week(env: dict, admission_id: str, week_index: int = 1,
                      week_start_date: str = None, lead_key: str = "pt",
                      **overrides) -> dict:
    payload = create_therapy_week_payload(
        admission_id, week_index, week_start_date, **overrides
    )
    return get_success_data(
        api_client.create_therapy_week(payload, env[f"{lead_key}_headers"])
    )


def evaluate_week(env: dict, week_id: str, lead_key: str = "pt") -> dict:
    return get_success_data(
        api_client.evaluate_therapy_week(week_id, env[f"{lead_key}_headers"])
    )


def grant_week_exception(env: dict, week_id: str, physician_key: str = "physician",
                         **overrides) -> dict:
    return get_success_data(
        api_client.grant_therapy_week_exception(
            week_id, grant_week_exception_payload(**overrides),
            env[f"{physician_key}_headers"],
        )
    )


def schedule_session(env: dict, admission_id: str, start_at: str, end_at: str,
                     clinician_key: str = "pt", lead_key: str = None,
                     **overrides) -> dict:
    """Schedule a therapy session treated by `clinician_key`."""
    lead_key = lead_key or clinician_key
    payload = create_therapy_session_payload(
        admission_id, env[clinician_key]["id"], start_at, end_at, **overrides
    )
    return get_success_data(
        api_client.create_therapy_session(payload, env[f"{lead_key}_headers"])
    )


def deliver_session(env: dict, session_id: str, lead_key: str = "pt") -> dict:
    return get_success_data(
        api_client.deliver_therapy_session(session_id, env[f"{lead_key}_headers"])
    )


def void_session(env: dict, session_id: str, lead_key: str = "pt",
                 **overrides) -> dict:
    return get_success_data(
        api_client.void_therapy_session(
            session_id, void_session_payload(**overrides),
            env[f"{lead_key}_headers"],
        )
    )


def deliver_therapy(env: dict, admission_id: str, start_at: str, end_at: str,
                    clinician_key: str = "pt", clock: str = None,
                    **overrides) -> dict:
    """Schedule a session and immediately document it as delivered."""
    session = schedule_session(env, admission_id, start_at, end_at,
                               clinician_key=clinician_key, **overrides)
    if clock is not None:
        set_clock(clock)
    return deliver_session(env, session["id"], lead_key=clinician_key)


def record_conference(env: dict, admission_id: str, therapy_week_id: str,
                      held_at: str, lead_key: str = "physician",
                      participant_keys=("nurse", "pt"), nurse_key: str = "nurse",
                      **overrides) -> dict:
    participants = [env[key]["id"] for key in participant_keys]
    payload = create_team_conference_payload(
        admission_id, therapy_week_id, env[lead_key]["id"], participants, held_at,
        **overrides
    )
    return get_success_data(
        api_client.create_team_conference(payload, env[f"{nurse_key}_headers"])
    )


# --------------------------------------------------------------------------- #
# Tier 3 — assessments, reviews and quality reporting
# --------------------------------------------------------------------------- #
def open_assessment(env: dict, admission_id: str,
                    assessment_type: str = "ADMISSION",
                    coder_key: str = "coder", acting_coder_key: str = None,
                    **overrides) -> dict:
    acting_coder_key = acting_coder_key or coder_key
    payload = create_assessment_payload(
        admission_id, env[coder_key]["id"], assessment_type, **overrides
    )
    return get_success_data(
        api_client.create_assessment(payload, env[f"{acting_coder_key}_headers"])
    )


def complete_assessment(env: dict, assessment_id: str, coder_key: str = "coder",
                        item_set_complete: bool = True) -> dict:
    return get_success_data(
        api_client.complete_assessment(
            assessment_id, complete_assessment_payload(item_set_complete),
            env[f"{coder_key}_headers"],
        )
    )


def transmit_assessment(env: dict, assessment_id: str,
                        coder_key: str = "coder2") -> dict:
    return get_success_data(
        api_client.transmit_assessment(assessment_id, env[f"{coder_key}_headers"])
    )


def open_compliance_review(env: dict, method: str = "MEDICAL_REVIEW",
                           officer_headers: dict = None,
                           expected_facility_version: int = None,
                           **overrides) -> dict:
    """Open a review, pinning the facility's current version (PRD §2.7)."""
    if expected_facility_version is None:
        expected_facility_version = read_facility(env["facility_id"])["version"]
    payload = create_compliance_review_payload(
        env["facility_id"], expected_facility_version, method, **overrides
    )
    return get_success_data(
        api_client.create_compliance_review(
            payload, officer_headers or OFFICER_HEADERS
        )
    )


def compute_review(review_id: str, officer_headers: dict = None) -> dict:
    return get_success_data(
        api_client.compute_compliance_review(
            review_id, officer_headers or OFFICER_HEADERS
        )
    )


def certify_review(review_id: str, officer_headers: dict = None) -> dict:
    return get_success_data(
        api_client.certify_compliance_review(
            review_id, officer_headers or SECOND_OFFICER_HEADERS
        )
    )


def open_and_compute_review(env: dict, method: str = "MEDICAL_REVIEW",
                            officer_headers: dict = None, **overrides) -> dict:
    review = open_compliance_review(env, method,
                                    officer_headers=officer_headers, **overrides)
    return compute_review(review["id"], officer_headers=officer_headers)


def open_qrp_assessment(env: dict, officer_headers: dict = None, **overrides) -> dict:
    payload = create_qrp_assessment_payload(env["facility_id"], **overrides)
    return get_success_data(
        api_client.create_qrp_assessment(payload, officer_headers or OFFICER_HEADERS)
    )


def finalize_qrp_assessment(qrp_id: str, officer_headers: dict = None) -> dict:
    return get_success_data(
        api_client.finalize_qrp_assessment(qrp_id, officer_headers or OFFICER_HEADERS)
    )


# --------------------------------------------------------------------------- #
# Tier 4 — whole-stay composites
# --------------------------------------------------------------------------- #
def setup_stay(env: dict, mrn: str = "MRN-A",
               patient_overrides: dict = None,
               screening_overrides: dict = None,
               screener_key: str = "nurse", reviewer_key: str = "physician",
               nurse_key: str = "nurse",
               admitted_at: str = None,
               advance_clock: bool = True,
               predecessor_admission_id: str = None,
               with_plan: bool = True, plan_overrides: dict = None,
               physician_key: str = "physician") -> dict:
    """Patient -> concurred screening -> admission -> admit (-> plan of care).

    Returns `{"patient", "screening", "admission", "plan"}` where `admission`
    is the admit response and `plan` is None when `with_plan` is False.
    """
    patient = register_patient(env, mrn=mrn, nurse_key=nurse_key,
                              **(patient_overrides or {}))
    screening = create_concurred_screening(
        env, patient["id"], screener_key=screener_key, reviewer_key=reviewer_key,
        nurse_key=nurse_key, **(screening_overrides or {})
    )
    admission_overrides = {}
    if predecessor_admission_id is not None:
        admission_overrides["predecessor_admission_id"] = predecessor_admission_id
    admission = open_admission(env, patient["id"], screening["id"],
                               nurse_key=nurse_key, **admission_overrides)
    admitted = admit(env, admission["id"],
                     admitted_at or TEST_DEFAULTS["ADMITTED_AT"],
                     nurse_key=nurse_key, advance_clock=advance_clock)
    plan = None
    if with_plan:
        plan = sign_plan_of_care(env, admission["id"], physician_key=physician_key,
                                 **(plan_overrides or {}))
    return {
        "patient": patient,
        "screening": screening,
        "admission": admitted,
        "plan": plan,
    }


def setup_stay_with_week(env: dict, week_index: int = 1,
                         week_start_date: str = None, lead_key: str = "pt",
                         week_overrides: dict = None, **stay_kwargs) -> dict:
    """`setup_stay` plus one open therapy week. Adds `week` to the result."""
    stay = setup_stay(env, **stay_kwargs)
    stay["week"] = open_therapy_week(
        env, stay["admission"]["id"], week_index,
        week_start_date or TEST_DEFAULTS["WEEK_START_DATE"], lead_key=lead_key,
        **(week_overrides or {})
    )
    return stay


def setup_discharged_stay(env: dict, discharged_at: str,
                          discharge_destination: str = "COMMUNITY",
                          discharge_planned: bool = True,
                          nurse_key: str = "nurse", **stay_kwargs) -> dict:
    """`setup_stay` carried through to DISCHARGED. Adds `discharge` result."""
    stay = setup_stay(env, nurse_key=nurse_key, **stay_kwargs)
    stay["discharge"] = discharge(
        env, stay["admission"]["id"], discharged_at,
        discharge_destination=discharge_destination,
        discharge_planned=discharge_planned, nurse_key=nurse_key,
    )
    return stay


def setup_admitted_cohort(env: dict, specs, admitted_at: str = None,
                          nurse_key: str = "nurse", screener_key: str = "nurse",
                          reviewer_key: str = "physician") -> list:
    """Open several stays at the current clock, then admit them all together.

    `specs` is a sequence of dicts, each accepting `mrn`, `patient_overrides`
    and `screening_overrides`. Every screening is conducted before any patient
    is admitted, so a single clock movement admits the whole group and no
    screening is ever conducted after the instant it is admitted for.
    Returns a list of `{"patient", "screening", "admission"}` dicts.
    """
    admitted_at = admitted_at or TEST_DEFAULTS["ADMITTED_AT"]
    stays = []
    for spec in specs:
        patient = register_patient(
            env, mrn=spec.get("mrn", "MRN-A"), nurse_key=nurse_key,
            **(spec.get("patient_overrides") or {})
        )
        screening_overrides = dict(spec.get("screening_overrides") or {})
        screening_overrides.setdefault("expected_admission_at", admitted_at)
        screening = create_concurred_screening(
            env, patient["id"], screener_key=screener_key,
            reviewer_key=reviewer_key, nurse_key=nurse_key, **screening_overrides
        )
        stays.append({
            "patient": patient,
            "screening": screening,
            "admission": open_admission(env, patient["id"], screening["id"],
                                        nurse_key=nurse_key),
        })
    set_clock(admitted_at)
    for stay in stays:
        stay["admission"] = admit(env, stay["admission"]["id"], admitted_at,
                                  nurse_key=nurse_key, advance_clock=False)
    return stays


def setup_discharged_cohort(env: dict, specs, admitted_at: str = None,
                            discharged_at: str = None,
                            discharge_destination: str = "COMMUNITY",
                            discharge_planned: bool = True,
                            nurse_key: str = "nurse", **cohort_kwargs) -> list:
    """`setup_admitted_cohort` carried through to DISCHARGED in one clock step.

    Adds `discharge` to each returned stay.
    """
    stays = setup_admitted_cohort(env, specs, admitted_at, nurse_key=nurse_key,
                                  **cohort_kwargs)
    set_clock(discharged_at)
    for stay in stays:
        stay["discharge"] = discharge(
            env, stay["admission"]["id"], discharged_at,
            discharge_destination=discharge_destination,
            discharge_planned=discharge_planned, nurse_key=nurse_key,
            advance_clock=False,
        )
    return stays


def setup_frozen_facility(env: dict,
                          admitted_at: str = "2026-08-04T12:00:00Z",
                          discharged_at: str = "2026-08-04T18:00:00Z") -> dict:
    """Discharge two non-qualifying stays so the posture reaches ADMISSION_FREEZE.

    Two discharged cohort members at 0.00 percent provisional compliance sit
    strictly below the threshold reduced by the freeze margin (PRD §2.8).
    Returns `{"stay_a", "stay_b"}`.
    """
    stays = setup_discharged_cohort(
        env, [{"mrn": "MRN-A"}, {"mrn": "MRN-B"}],
        admitted_at=admitted_at, discharged_at=discharged_at,
    )
    return {"stay_a": stays[0], "stay_b": stays[1]}


def setup_interruption_chain(env: dict,
                             head_admitted_at: str = "2026-08-04T12:00:00Z",
                             head_discharged_at: str = "2026-08-10T12:00:00Z",
                             head_destination: str = "ACUTE_CARE",
                             continuation_screened_at: str = "2026-08-11T09:00:00Z",
                             continuation_admitted_at: str = "2026-08-12T12:00:00Z",
                             mrn: str = "MRN-A",
                             patient_overrides: dict = None,
                             attach: bool = True) -> dict:
    """One patient, a priced head stay, and a continuation that reconsolidates it.

    Returns `{"patient", "head_screening", "head", "continuation_screening",
    "continuation", "continuation_admission"}`. When `attach` is False the
    continuation is opened but not admitted, so a test can trigger the attach.
    """
    patient = register_patient(env, mrn=mrn, **(patient_overrides or {}))
    head_screening = create_concurred_screening(env, patient["id"])
    head = open_admission(env, patient["id"], head_screening["id"])
    admit(env, head["id"], head_admitted_at)
    discharge(env, head["id"], head_discharged_at,
              discharge_destination=head_destination)

    set_clock(continuation_screened_at)
    continuation_screening = create_concurred_screening(
        env, patient["id"],
        expected_admission_at=continuation_admitted_at,
    )
    continuation = open_admission(
        env, patient["id"], continuation_screening["id"],
        predecessor_admission_id=head["id"],
    )
    result = {
        "patient": patient,
        "head_screening": head_screening,
        "head": head,
        "continuation_screening": continuation_screening,
        "continuation": continuation,
        "continuation_admission": None,
        "continuation_admitted_at": continuation_admitted_at,
    }
    if attach:
        result["continuation_admission"] = admit(
            env, continuation["id"], continuation_admitted_at
        )
    return result
