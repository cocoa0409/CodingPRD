"""Composite setup helpers.

Every helper here builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against a freshly started server with an
empty database. Helpers use the lenient success reader so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_nurse_headers,
    make_unit_charge_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
MATERIALS = TEST_USERS["materials_headers"]
SYSOP = TEST_USERS["system_operator_headers"]

CLOCK_ORIGIN = "2026-08-01T00:00:00Z"


# --- Logical clock -----------------------------------------------------------
def set_clock(to_iso8601: str, api=api_client) -> dict:
    """Reposition the server's logical clock and return the answer body."""
    return get_success_data(
        api.set_clock(f.set_clock_payload(to_iso8601), SYSOP)
    )


# --- Tier 1: single-resource creation ---------------------------------------
def create_unit(api=api_client, **overrides) -> dict:
    """Register one hospital unit with its rental ledger initialised."""
    return get_success_data(
        api.create_unit(f.create_unit_payload(**overrides), DIRECTOR)
    )


def create_patient(unit: dict, api=api_client, **overrides) -> dict:
    """Admit one patient onto `unit`, acting as that unit's charge nurse."""
    return get_success_data(
        api.create_patient(
            f.create_patient_payload(unit["id"], **overrides),
            make_unit_charge_headers(unit["id"]),
        )
    )


def create_trainee_nurse(unit: dict, api=api_client, **overrides) -> dict:
    """Register a nurse; registration leaves them TRAINEE with no load ceiling."""
    return get_success_data(
        api.create_woc_nurse(
            f.create_woc_nurse_payload(unit["id"], **overrides), DIRECTOR
        )
    )


def create_candidate_nurse(
    unit: dict,
    signed_off_at: str = CLOCK_ORIGIN,
    api=api_client,
    **overrides,
) -> dict:
    """Register a nurse, record one competency signoff and advance to CANDIDATE."""
    nurse = create_trainee_nurse(unit, api=api, **overrides)
    get_success_data(
        api.create_competency_signoff(
            nurse["id"], f.competency_signoff_payload(signed_off_at), DIRECTOR
        )
    )
    return get_success_data(api.advance_woc_nurse(nurse["id"], {}, DIRECTOR))


def create_certified_nurse(
    unit: dict,
    signed_off_at: str = CLOCK_ORIGIN,
    cert_expires_at: str = "2028-08-01T00:00:00Z",
    ce_credits: int = 30,
    api=api_client,
    **overrides,
) -> dict:
    """Walk a nurse the whole way to CERTIFIED.

    Register with `ce_credits`, record two competency signoffs, advance to
    candidate, then certify — which is the shortest path that satisfies all
    three certification gates at once.
    """
    overrides.setdefault("ce_credits", ce_credits)
    nurse = create_trainee_nurse(unit, api=api, **overrides)
    for _ in range(2):
        get_success_data(
            api.create_competency_signoff(
                nurse["id"], f.competency_signoff_payload(signed_off_at), DIRECTOR
            )
        )
    get_success_data(api.advance_woc_nurse(nurse["id"], {}, DIRECTOR))
    return get_success_data(
        api.certify_woc_nurse(
            nurse["id"], f.certify_payload(cert_expires_at), DIRECTOR
        )
    )


def create_surface(api=api_client, **overrides) -> dict:
    """Add one rental asset to the fleet."""
    return get_success_data(
        api.create_support_surface(
            f.create_support_surface_payload(**overrides), MATERIALS
        )
    )


def create_product(api=api_client, **overrides) -> dict:
    """Add one formulary product; it starts ACTIVE."""
    return get_success_data(
        api.create_formulary_product(
            f.create_formulary_product_payload(**overrides), DIRECTOR
        )
    )


# --- Tier 2: the clinical spine ---------------------------------------------
def create_consult(unit: dict, patient: dict, api=api_client, **overrides) -> dict:
    """Raise a consult from the bedside unit; it starts REQUESTED."""
    return get_success_data(
        api.create_consult_request(
            f.create_consult_request_payload(patient["id"], unit["id"], **overrides),
            make_unit_charge_headers(unit["id"]),
        )
    )


def triage_consult(consult: dict, nurse: dict, api=api_client) -> dict:
    """Triage a REQUESTED consult, computing the intake-provisional acuity."""
    return get_success_data(
        api.triage_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )


def assign_consult(consult: dict, nurse: dict, api=api_client) -> dict:
    """Route a triaged or escalated consult to `nurse`."""
    return get_success_data(
        api.assign_consult_request(
            consult["id"], f.assign_consult_payload(nurse["id"]), DIRECTOR
        )
    )


def read_patient_version(patient_id: str, api=api_client) -> int:
    """Re-read a patient to seed the assessment's expected_patient_version."""
    return get_success_data(api.get_patient(patient_id, DIRECTOR))["version"]


def file_assessment(
    consult: dict,
    patient: dict,
    nurse: dict,
    api=api_client,
    expected_patient_version=None,
    **overrides,
) -> dict:
    """File a bedside skin assessment, re-reading the patient version first."""
    if expected_patient_version is None:
        expected_patient_version = read_patient_version(patient["id"], api=api)
    payload = f.create_skin_assessment_payload(
        consult["id"], patient["id"], expected_patient_version, **overrides
    )
    return get_success_data(
        api.create_skin_assessment(payload, make_nurse_headers(nurse["id"]))
    )


def validate_assessment(
    assessment: dict,
    api=api_client,
    headers=None,
    confirmed_stage: str = "STAGE_2",
    present_on_admission_confirmed: bool = False,
    **overrides,
) -> dict:
    """Validate a pending assessment. Defaults to the director, who is always a
    legal validator and never trips the self-validation prohibition."""
    return get_success_data(
        api.validate_skin_assessment(
            assessment["id"],
            f.validate_assessment_payload(
                confirmed_stage, present_on_admission_confirmed, **overrides
            ),
            headers if headers is not None else DIRECTOR,
        )
    )


def setup_assigned_consult(
    api=api_client,
    unit_overrides=None,
    patient_overrides=None,
    consult_overrides=None,
    nurse_overrides=None,
) -> dict:
    """Unit + patient + certified nurse + a consult triaged and assigned.

    Returns a scenario dict keyed `unit`, `patient`, `nurse`, `consult`.
    """
    unit = create_unit(api=api, **(unit_overrides or {}))
    patient = create_patient(unit, api=api, **(patient_overrides or {}))
    nurse = create_certified_nurse(unit, api=api, **(nurse_overrides or {}))
    consult = create_consult(unit, patient, api=api, **(consult_overrides or {}))
    triage_consult(consult, nurse, api=api)
    consult = assign_consult(consult, nurse, api=api)
    return {"unit": unit, "patient": patient, "nurse": nurse, "consult": consult}


def setup_assessed_consult(
    api=api_client,
    assessment_overrides=None,
    **scenario_kwargs,
) -> dict:
    """`setup_assigned_consult` plus one filed assessment, so the consult is
    ASSESSED and a pressure injury case is open. Adds `assessment` to the
    scenario dict."""
    scenario = setup_assigned_consult(api=api, **scenario_kwargs)
    scenario["assessment"] = file_assessment(
        scenario["consult"],
        scenario["patient"],
        scenario["nurse"],
        api=api,
        **(assessment_overrides or {}),
    )
    return scenario


def setup_validated_assessment(
    api=api_client,
    confirmed_stage: str = "STAGE_2",
    present_on_admission_confirmed: bool = False,
    validate_headers=None,
    **scenario_kwargs,
) -> dict:
    """`setup_assessed_consult` plus validation of that assessment."""
    scenario = setup_assessed_consult(api=api, **scenario_kwargs)
    scenario["assessment"] = validate_assessment(
        scenario["assessment"],
        api=api,
        headers=validate_headers,
        confirmed_stage=confirmed_stage,
        present_on_admission_confirmed=present_on_admission_confirmed,
    )
    return scenario


def setup_plan_active_consult(
    api=api_client,
    product_overrides=None,
    protocol_overrides=None,
    **scenario_kwargs,
) -> dict:
    """Drive a consult all the way to PLAN_ACTIVE with a live dressing protocol.

    Adds `product` and `protocol` to the scenario dict.
    """
    scenario = setup_validated_assessment(api=api, **scenario_kwargs)
    scenario["product"] = create_product(api=api, **(product_overrides or {}))
    scenario["protocol"] = get_success_data(
        api.create_dressing_protocol(
            f.create_dressing_protocol_payload(
                scenario["consult"]["id"],
                scenario["product"]["id"],
                **(protocol_overrides or {}),
            ),
            make_nurse_headers(scenario["nurse"]["id"]),
        )
    )
    return scenario


# --- Tier 3: the pressure injury case and its investigation ------------------
# A hospital-acquired determination needs the earliest documentation of the body
# site to fall strictly later than admitted_at plus 24 hours. Admitting on
# 2026-07-30 and observing on the clock origin 2026-08-01 satisfies that while
# leaving the clock untouched.
HAPI_ADMITTED_AT = "2026-07-30T00:00:00Z"


def setup_hapi_case(
    api=api_client,
    confirmed_stage: str = "STAGE_3",
    patient_overrides=None,
    **scenario_kwargs,
) -> dict:
    """Drive one consult to a validated hospital-acquired staging.

    The case lands in RCA_REQUIRED, the unit's open_hapi_rca_count rises by 1
    and its survey_posture is re-derived. Adds `case` to the scenario dict.
    """
    patient_overrides = dict(patient_overrides or {})
    patient_overrides.setdefault("admitted_at", HAPI_ADMITTED_AT)
    scenario = setup_validated_assessment(
        api=api,
        confirmed_stage=confirmed_stage,
        present_on_admission_confirmed=False,
        patient_overrides=patient_overrides,
        **scenario_kwargs,
    )
    cases, _ = _list_cases(api, {"skin_assessment_id": scenario["assessment"]["id"]})
    scenario["case"] = cases[0]
    return scenario


def _list_cases(api, params):
    body = api.list_pressure_injury_cases(DIRECTOR, params=params).json()
    return body["data"], body["meta"]


def find_case_for_assessment(assessment_id: str, api=api_client) -> dict:
    """Read back the pressure injury case opened by one assessment's filing."""
    cases, _ = _list_cases(api, {"skin_assessment_id": assessment_id})
    assert cases, f"no pressure injury case found for assessment {assessment_id}"
    return cases[0]


def raise_open_hapi_count(
    unit: dict,
    target_count: int,
    api=api_client,
    start_index: int = 0,
) -> list:
    """Open `target_count` hospital-acquired cases on one unit.

    Each iteration admits a fresh patient, certifies nothing new (the same nurse
    is reused via a certified nurse created on the unit), raises a consult,
    triages, assigns, files an assessment and validates it as hospital-acquired.
    Returns the list of case rows in creation order.
    """
    nurse = create_certified_nurse(unit, api=api)
    cases = []
    for index in range(start_index, start_index + target_count):
        patient = create_patient(unit, api=api, admitted_at=HAPI_ADMITTED_AT)
        consult = create_consult(unit, patient, api=api)
        triage_consult(consult, nurse, api=api)
        assign_consult(consult, nurse, api=api)
        assessment = file_assessment(
            consult, patient, nurse, api=api, anatomic_location="SACRUM"
        )
        validate_assessment(
            assessment,
            api=api,
            confirmed_stage="STAGE_3",
            present_on_admission_confirmed=False,
        )
        cases.append(find_case_for_assessment(assessment["id"], api=api))
    return cases


def start_rca(case: dict, lead_nurse: dict, api=api_client) -> dict:
    """Open the root cause analysis, nominating a certified lead."""
    return get_success_data(
        api.rca_start(case["id"], f.rca_start_payload(lead_nurse["id"]), DIRECTOR)
    )


def complete_rca(case: dict, lead_nurse: dict, api=api_client, **overrides) -> dict:
    """Record the finding. Only the nominated lead may complete the analysis."""
    return get_success_data(
        api.rca_complete(
            case["id"],
            f.rca_complete_payload(**overrides),
            make_nurse_headers(lead_nurse["id"]),
        )
    )


def close_case(case: dict, api=api_client) -> dict:
    """Close an adjudicated case, reversing any posture hold it caused."""
    return get_success_data(
        api.close_pressure_injury_case(case["id"], f.close_case_payload(), DIRECTOR)
    )


# --- Tier 4: the rental fleet and the unit ledger ----------------------------
def setup_rental_scenario(
    api=api_client,
    unit_overrides=None,
    patient_overrides=None,
    surface_overrides=None,
) -> dict:
    """Unit + admitted patient + one AVAILABLE fleet asset.

    Returns a scenario dict keyed `unit`, `patient`, `surface`.
    """
    unit = create_unit(api=api, **(unit_overrides or {}))
    patient = create_patient(unit, api=api, **(patient_overrides or {}))
    surface = create_surface(api=api, **(surface_overrides or {}))
    return {"unit": unit, "patient": patient, "surface": surface}


def create_order(
    unit: dict,
    patient: dict,
    surface: dict,
    api=api_client,
    headers=None,
    **overrides,
) -> dict:
    """Request a rental and let the server compute its three cost figures."""
    return get_success_data(
        api.create_support_surface_order(
            f.create_support_surface_order_payload(
                patient["id"], unit["id"], surface["id"], **overrides
            ),
            headers if headers is not None else MATERIALS,
        )
    )


def read_unit_version(unit_id: str, api=api_client) -> int:
    """Re-read a unit to seed an approval's expected_unit_version."""
    return get_success_data(api.get_unit(unit_id, DIRECTOR))["version"]


def approve_order(
    order: dict,
    unit: dict,
    api=api_client,
    expected_unit_version=None,
    **overrides,
) -> dict:
    """Approve a requested rental, re-reading the unit version first."""
    if expected_unit_version is None:
        expected_unit_version = read_unit_version(unit["id"], api=api)
    return get_success_data(
        api.approve_support_surface_order(
            order["id"],
            f.approve_order_payload(expected_unit_version, **overrides),
            MATERIALS,
        )
    )


def deliver_order(order: dict, delivered_at: str, api=api_client) -> dict:
    """Mark an approved rental delivered; the billing dimension does not move."""
    return get_success_data(
        api.deliver_support_surface_order(
            order["id"], f.deliver_order_payload(delivered_at), MATERIALS
        )
    )


def return_order(order: dict, actual_return_at: str, api=api_client) -> dict:
    """Return a delivered rental; commits the realised cost and settles the ledger."""
    return get_success_data(
        api.return_support_surface_order(
            order["id"], f.return_order_payload(actual_return_at), MATERIALS
        )
    )


def reconcile_order(order: dict, api=api_client) -> dict:
    """Reconcile a committed rental against the vendor invoice."""
    return get_success_data(
        api.reconcile_support_surface_order(order["id"], {}, MATERIALS)
    )


def setup_approved_order(
    api=api_client,
    order_overrides=None,
    **scenario_kwargs,
) -> dict:
    """`setup_rental_scenario` plus one order taken to APPROVED / ENCUMBERED.

    Adds `order` to the scenario dict.
    """
    scenario = setup_rental_scenario(api=api, **scenario_kwargs)
    order = create_order(
        scenario["unit"],
        scenario["patient"],
        scenario["surface"],
        api=api,
        **(order_overrides or {}),
    )
    scenario["order"] = approve_order(order, scenario["unit"], api=api)
    return scenario


def setup_committed_order(
    api=api_client,
    delivered_at: str = "2026-08-01T00:00:00Z",
    actual_return_at: str = "2026-08-04T00:00:00Z",
    **kwargs,
) -> dict:
    """Take one order all the way to RETURNED / COMMITTED so the billing
    dimension is reconcilable."""
    scenario = setup_approved_order(api=api, **kwargs)
    deliver_order(scenario["order"], delivered_at, api=api)
    scenario["order"] = return_order(scenario["order"], actual_return_at, api=api)
    return scenario


def setup_unit_with_restricted_posture(api=api_client, unit_overrides=None) -> dict:
    """Raise a unit's open_hapi_rca_count to 2 so its survey_posture reads
    RESTRICTED. Returns a scenario dict keyed `unit`, `cases`."""
    unit = create_unit(api=api, **(unit_overrides or {}))
    cases = raise_open_hapi_count(unit, 2, api=api)
    return {"unit": unit, "cases": cases}


def setup_unit_with_frozen_posture(api=api_client, unit_overrides=None) -> dict:
    """Raise a unit's open_hapi_rca_count to 4 so its survey_posture reads
    FROZEN. Returns a scenario dict keyed `unit`, `cases`."""
    unit = create_unit(api=api, **(unit_overrides or {}))
    cases = raise_open_hapi_count(unit, 4, api=api)
    return {"unit": unit, "cases": cases}


# --- Tier 4: the survey programme -------------------------------------------
def create_round(
    unit_ids,
    api=api_client,
    round_type: str = "PREVALENCE",
    **overrides,
) -> dict:
    """Plan a survey round over `unit_ids`; it starts PLANNED."""
    return get_success_data(
        api.create_survey_round(
            f.create_survey_round_payload(unit_ids, round_type, **overrides),
            DIRECTOR,
        )
    )


def open_round(survey_round: dict, api=api_client) -> dict:
    """Open a planned round, which is where window contention is checked."""
    return get_success_data(api.open_survey_round(survey_round["id"], {}, DIRECTOR))


def file_observation(
    survey_round: dict,
    unit: dict,
    patient: dict,
    observer: dict,
    api=api_client,
    **overrides,
) -> dict:
    """Record one immutable observation inside an open round."""
    return get_success_data(
        api.create_survey_observation(
            f.create_survey_observation_payload(
                survey_round["id"],
                unit["id"],
                patient["id"],
                observer["id"],
                **overrides,
            ),
            make_nurse_headers(observer["id"]),
        )
    )


def lock_round(survey_round: dict, api=api_client) -> dict:
    """Lock an open round once every participating unit has been walked."""
    return get_success_data(api.lock_survey_round(survey_round["id"], {}, DIRECTOR))


def publish_round(survey_round: dict, api=api_client) -> dict:
    """Publish a locked round, writing the per-unit metric."""
    return get_success_data(api.publish_survey_round(survey_round["id"], {}, DIRECTOR))


def setup_open_round(
    api=api_client,
    round_type: str = "PREVALENCE",
    unit_count: int = 1,
    patients_per_unit: int = 0,
    round_overrides=None,
) -> dict:
    """One certified observer, `unit_count` units and an OPEN round over them.

    Returns a scenario dict keyed `units`, `observer`, `round`, `patients`
    (a list per unit, empty unless `patients_per_unit` is positive).
    """
    units = [create_unit(api=api) for _ in range(unit_count)]
    observer = create_certified_nurse(units[0], api=api)
    patients = []
    for unit in units:
        patients.append(
            [create_patient(unit, api=api) for _ in range(patients_per_unit)]
        )
    survey_round = create_round(
        [unit["id"] for unit in units],
        api=api,
        round_type=round_type,
        **(round_overrides or {}),
    )
    survey_round = open_round(survey_round, api=api)
    return {
        "units": units,
        "observer": observer,
        "round": survey_round,
        "patients": patients,
    }


# --- Tier 5: ostomy education -----------------------------------------------
def setup_ostomy_plan(api=api_client, **scenario_kwargs) -> dict:
    """Drive an OSTOMY consult to ASSESSED with a validated staging and open the
    education plan. Adds `plan` to the scenario dict."""
    consult_overrides = dict(scenario_kwargs.pop("consult_overrides", None) or {})
    consult_overrides.setdefault("consult_type", "OSTOMY")
    patient_overrides = dict(scenario_kwargs.pop("patient_overrides", None) or {})
    patient_overrides.setdefault("ostomy_present", True)
    scenario = setup_validated_assessment(
        api=api,
        consult_overrides=consult_overrides,
        patient_overrides=patient_overrides,
        **scenario_kwargs,
    )
    scenario["plan"] = get_success_data(
        api.create_ostomy_education_plan(
            f.create_ostomy_education_plan_payload(
                scenario["consult"]["id"], scenario["patient"]["id"]
            ),
            make_nurse_headers(scenario["nurse"]["id"]),
        )
    )
    return scenario


def record_session(plan: dict, nurse: dict, teach_back_score: int, api=api_client) -> dict:
    """Record one education session and its teach-back score."""
    return get_success_data(
        api.create_education_session(
            plan["id"],
            f.education_session_payload(teach_back_score),
            make_nurse_headers(nurse["id"]),
        )
    )


def transition_supplies(
    plan: dict, nurse: dict, followup_appointment_at: str, api=api_client
) -> dict:
    """Transition the patient to outpatient supplies and book the follow-up."""
    return get_success_data(
        api.transition_supplies(
            plan["id"],
            f.transition_supplies_payload(followup_appointment_at),
            make_nurse_headers(nurse["id"]),
        )
    )
