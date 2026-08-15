"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints, because every test runs against a freshly restarted server with an
empty database. Setup calls use the lenient `get_success_data` validator so a
setup failure surfaces as a clear "Setup step failed" error.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_hai_payload,
    adjudicate_ruled_out_payload,
    create_audit_payload,
    create_cap_payload,
    create_device_day_count_payload,
    create_device_episode_payload,
    create_employee_payload,
    create_exposure_payload,
    create_facility_payload,
    create_infection_case_payload,
    create_isolation_order_payload,
    create_monthly_summary_payload,
    create_observation_payload,
    create_outbreak_investigation_payload,
    create_patient_payload,
    create_surgical_procedure_payload,
    create_unit_payload,
    correct_device_day_count_payload,
    record_draw_payload,
    record_serologies_payload,
    reopen_payload,
    submit_for_verification_payload,
)
from .test_users import (
    TEST_USERS,
    director_headers,
    ip_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
IP = TEST_USERS["infection_preventionist_headers"]
DIRECTOR = TEST_USERS["infection_control_director_headers"]
NURSE = TEST_USERS["unit_nurse_manager_headers"]
EHN = TEST_USERS["employee_health_nurse_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (PRD §2.6). Returns the clock reading."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), ADMIN)
    )


def create_unit(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit(create_unit_payload(facility_id, **overrides), ADMIN)
    )


def setup_facility_unit(unit_type: str = "ICU", **facility_overrides) -> Tuple[dict, dict]:
    """Facility + one unit. Returns (facility, unit)."""
    facility = create_facility(**facility_overrides)
    unit = create_unit(facility["id"], unit_type=unit_type)
    return facility, unit


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, ADMIN))


def create_patient(unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(create_patient_payload(unit_id, **overrides), NURSE)
    )


def transfer_patient(patient_id: str, to_unit_id: str, transferred_at: str) -> dict:
    return get_success_data(
        api_client.transfer_patient(
            patient_id, {"to_unit_id": to_unit_id, "transferred_at": transferred_at}, NURSE
        )
    )


def discharge_patient(patient_id: str, discharged_at: str) -> dict:
    return get_success_data(
        api_client.discharge_patient(patient_id, {"discharged_at": discharged_at}, NURSE)
    )


def create_employee(home_unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(create_employee_payload(home_unit_id, **overrides), EHN)
    )


def create_device_episode(patient_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_device_episode(
            create_device_episode_payload(patient_id, **overrides), NURSE
        )
    )


def remove_device_episode(episode_id: str, removed_at: str) -> dict:
    return get_success_data(
        api_client.remove_device_episode(episode_id, {"removed_at": removed_at}, NURSE)
    )


def create_surgical_procedure(patient_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_surgical_procedure(
            create_surgical_procedure_payload(patient_id, **overrides), NURSE
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: infection case lifecycle
# ---------------------------------------------------------------------------

def create_infection_case(patient_id: str, **overrides) -> dict:
    """Open a SUSPECTED case. CLABSI payloads must pass linked_device_episode_id."""
    return get_success_data(
        api_client.create_infection_case(
            create_infection_case_payload(patient_id, **overrides), IP
        )
    )


def begin_review(case_id: str) -> dict:
    return get_success_data(api_client.begin_review(case_id, IP))


def adjudicate_hai(case_id: str, date_of_event: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_case(case_id, adjudicate_hai_payload(date_of_event, **overrides), IP)
    )


def adjudicate_ruled_out(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_case(case_id, adjudicate_ruled_out_payload(**overrides), IP)
    )


def reopen_case(case_id: str, **overrides) -> dict:
    return get_success_data(api_client.reopen_case(case_id, reopen_payload(**overrides), IP))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_infection_case(case_id, IP))


def create_case_under_review(
    patient_id: str,
    linked_device_episode_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Create a case and move it SUSPECTED -> UNDER_REVIEW."""
    if linked_device_episode_id is not None:
        overrides.setdefault("linked_device_episode_id", linked_device_episode_id)
    case = create_infection_case(patient_id, **overrides)
    return begin_review(case["id"])


def create_adjudicated_clabsi(
    patient_id: str,
    episode_id: str,
    organism: str,
    specimen_at: str,
    date_of_event: str,
) -> dict:
    """Full walk: create CLABSI -> begin-review -> adjudicate ADJUDICATED_HAI."""
    case = create_infection_case(
        patient_id,
        case_type="CLABSI",
        suspected_organism=organism,
        first_positive_specimen_at=specimen_at,
        linked_device_episode_id=episode_id,
    )
    begin_review(case["id"])
    return adjudicate_hai(case["id"], date_of_event)


# ---------------------------------------------------------------------------
# Tier 1: denominators and summaries
# ---------------------------------------------------------------------------

def create_device_day_count(unit_id: str, count_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_device_day_count(
            create_device_day_count_payload(unit_id, count_date, **overrides), NURSE
        )
    )


def create_device_day_rows(unit_id: str, rows: List[dict]) -> List[dict]:
    """Create several denominator rows. Each row: {count_date, central_line_days, ...}."""
    return [create_device_day_count(unit_id, **row) for row in rows]


def get_device_day_count(count_id: str) -> dict:
    return get_success_data(api_client.get_device_day_count(count_id, NURSE))


def correct_device_day_count(count_id: str, expected_version: int, **counts) -> dict:
    return get_success_data(
        api_client.update_device_day_count(
            count_id,
            correct_device_day_count_payload(expected_version, **counts),
            NURSE,
        )
    )


def create_monthly_summary(unit_id: str, month: str = "2026-08") -> dict:
    return get_success_data(
        api_client.create_monthly_summary(
            create_monthly_summary_payload(unit_id, month), IP
        )
    )


def get_summary(summary_id: str) -> dict:
    return get_success_data(api_client.get_monthly_summary(summary_id, IP))


def submit_summary(summary_id: str, user_id: str = "test-ip-1") -> dict:
    return get_success_data(api_client.submit_summary(summary_id, ip_headers(user_id)))


def accept_summary(summary_id: str, user_id: str = "test-director-1") -> dict:
    return get_success_data(api_client.accept_summary(summary_id, director_headers(user_id)))


def reject_summary(summary_id: str, reason: str = "denominator audit finding",
                   user_id: str = "test-director-1") -> dict:
    return get_success_data(
        api_client.reject_summary(summary_id, {"reason": reason}, director_headers(user_id))
    )


def amend_summary(summary_id: str, reason: str = "amendment requested by NHSN",
                  user_id: str = "test-ip-1") -> dict:
    return get_success_data(
        api_client.amend_summary(summary_id, {"reason": reason}, ip_headers(user_id))
    )


# ---------------------------------------------------------------------------
# Tier 1: outbreak investigations
# ---------------------------------------------------------------------------

def create_manual_investigation(unit_id: str, organism: str) -> dict:
    return get_success_data(
        api_client.create_outbreak_investigation(
            create_outbreak_investigation_payload(unit_id, organism), IP
        )
    )


def confirm_investigation(investigation_id: str, user_id: str = "test-director-1") -> dict:
    return get_success_data(
        api_client.confirm_investigation(investigation_id, director_headers(user_id))
    )


def rule_out_investigation(investigation_id: str, reason: str = "pseudo-cluster, lab error",
                           user_id: str = "test-director-1") -> dict:
    return get_success_data(
        api_client.rule_out_investigation(
            investigation_id, {"reason": reason}, director_headers(user_id)
        )
    )


def close_investigation(investigation_id: str, user_id: str = "test-director-1") -> dict:
    return get_success_data(
        api_client.close_investigation(investigation_id, director_headers(user_id))
    )


def list_investigations(params: dict) -> Tuple[list, dict]:
    body = api_client.list_outbreak_investigations(DIRECTOR, params=params)
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(body)


# ---------------------------------------------------------------------------
# Tier 1: isolation orders and audits
# ---------------------------------------------------------------------------

def create_isolation_order(patient_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_isolation_order(
            create_isolation_order_payload(patient_id, **overrides), IP
        )
    )


def start_isolation_order(order_id: str) -> dict:
    return get_success_data(api_client.start_isolation_order(order_id, NURSE))


def discontinue_isolation_order(order_id: str) -> dict:
    return get_success_data(api_client.discontinue_isolation_order(order_id, NURSE))


def get_isolation_order(order_id: str) -> dict:
    return get_success_data(api_client.get_isolation_order(order_id, NURSE))


def create_active_isolation_order(patient_id: str, **overrides) -> dict:
    order = create_isolation_order(patient_id, **overrides)
    return start_isolation_order(order["id"])


def create_audit(isolation_order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_isolation_audit(
            create_audit_payload(isolation_order_id, **overrides), NURSE
        )
    )


def list_caps(params: dict) -> Tuple[list, dict]:
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_corrective_action_plans(DIRECTOR, params=params))


# ---------------------------------------------------------------------------
# Tier 1: hand hygiene
# ---------------------------------------------------------------------------

def record_observation(unit_id: str, observed_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_hand_hygiene_observation(
            create_observation_payload(unit_id, observed_at, **overrides), NURSE
        )
    )


def record_observation_batch(
    unit_id: str,
    date: str,
    start_hhmm: str,
    count: int,
    opportunity_type: str,
    action: str,
    step_minutes: int = 5,
) -> List[dict]:
    """Record `count` observations on `date` (YYYY-MM-DD) starting at start_hhmm
    (HH:MM), spaced step_minutes apart."""
    hour, minute = (int(part) for part in start_hhmm.split(":"))
    out = []
    for i in range(count):
        total = hour * 60 + minute + i * step_minutes
        ts = f"{date}T{total // 60:02d}:{total % 60:02d}:00Z"
        out.append(
            record_observation(unit_id, ts, opportunity_type=opportunity_type, action=action)
        )
    return out


def get_hh_rate(unit_id: str, month: str = "2026-08", headers=None) -> dict:
    return get_success_data(
        api_client.get_hand_hygiene_rate(unit_id, month, headers or NURSE)
    )


# ---------------------------------------------------------------------------
# Tier 1: employees and exposures
# ---------------------------------------------------------------------------

def create_exposure(employee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee_exposure(
            create_exposure_payload(employee_id, **overrides), EHN
        )
    )


def record_source_serologies(exposure_id: str, hbv: str = "NEGATIVE",
                             hcv: str = "NEGATIVE", hiv: str = "NEGATIVE") -> dict:
    return get_success_data(
        api_client.record_source_serologies(
            exposure_id, record_serologies_payload(hbv, hcv, hiv), EHN
        )
    )


def record_draw(exposure_id: str, stage: str, drawn_at: str, result: str = "NEGATIVE") -> dict:
    return get_success_data(
        api_client.record_draw(exposure_id, record_draw_payload(stage, drawn_at, result), EHN)
    )


def get_exposure(exposure_id: str) -> dict:
    return get_success_data(api_client.get_employee_exposure(exposure_id, EHN))


def setup_exposure_through_baseline(
    occurred_at: str = "2026-08-01T10:00:00Z",
    baseline_drawn_at: str = "2026-08-03T10:00:00Z",
) -> dict:
    """Facility + unit + employee + exposure walked to FOLLOWUP_IN_PROGRESS
    (serologies recorded, BASELINE draw accepted). Returns a context dict."""
    facility, unit = setup_facility_unit(unit_type="WARD")
    employee = create_employee(unit["id"])
    exposure = create_exposure(employee["id"], occurred_at=occurred_at,
                               source_hbv_status="NEGATIVE", source_hcv_status="NEGATIVE",
                               source_hiv_status="NEGATIVE")
    record_source_serologies(exposure["id"])
    exposure = record_draw(exposure["id"], "BASELINE", baseline_drawn_at)
    return {
        "facility": facility,
        "unit": unit,
        "employee": employee,
        "exposure": exposure,
    }


# ---------------------------------------------------------------------------
# Tier 1: corrective action plans
# ---------------------------------------------------------------------------

def create_cap(unit_id: str, source_type: str, source_ref_id: str,
               user_id: str = "test-ip-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_corrective_action_plan(
            create_cap_payload(unit_id, source_type, source_ref_id, **overrides),
            ip_headers(user_id),
        )
    )


def activate_cap(cap_id: str, user_id: str = "test-ip-1") -> dict:
    return get_success_data(api_client.activate_cap(cap_id, ip_headers(user_id)))


def submit_cap_for_verification(cap_id: str, user_id: str = "test-ip-1", **overrides) -> dict:
    return get_success_data(
        api_client.submit_cap_for_verification(
            cap_id, submit_for_verification_payload(**overrides), ip_headers(user_id)
        )
    )


def verify_cap(cap_id: str, user_id: str = "test-director-1") -> dict:
    return get_success_data(api_client.verify_cap(cap_id, director_headers(user_id)))


def fail_cap_verification(cap_id: str, reason: str = "evidence insufficient",
                          user_id: str = "test-director-1") -> dict:
    return get_success_data(
        api_client.fail_cap_verification(cap_id, {"reason": reason}, director_headers(user_id))
    )


def get_cap(cap_id: str) -> dict:
    return get_success_data(api_client.get_corrective_action_plan(cap_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2-3: composite scenarios shared by several tests
# ---------------------------------------------------------------------------

def setup_unit_with_patient(unit_type: str = "ICU", **facility_overrides) -> dict:
    """Facility + unit + one admitted patient. Returns context dict."""
    facility, unit = setup_facility_unit(unit_type=unit_type, **facility_overrides)
    patient = create_patient(unit["id"])
    return {"facility": facility, "unit": unit, "patient": patient}


def setup_unit_with_patient_and_episode(unit_type: str = "ICU",
                                        placed_at: str = "2026-08-01T10:00:00Z",
                                        **facility_overrides) -> dict:
    """Adds one ACTIVE CENTRAL_LINE episode."""
    ctx = setup_unit_with_patient(unit_type=unit_type, **facility_overrides)
    ctx["episode"] = create_device_episode(ctx["patient"]["id"], placed_at=placed_at)
    return ctx


def setup_open_summary_with_day_row(central_line_days: int = 20,
                                    patient_days: int = 40) -> dict:
    """Facility + unit + one DeviceDayCount (2026-08-01) + OPEN MonthlySummary.
    Returns ctx with facility, unit, day_row, summary."""
    facility, unit = setup_facility_unit()
    day_row = create_device_day_count(
        unit["id"],
        "2026-08-01T00:00:00Z",
        central_line_days=central_line_days,
        urinary_catheter_days=10,
        ventilator_days=5,
        patient_days=patient_days,
    )
    summary = create_monthly_summary(unit["id"], "2026-08")
    return {
        "facility": facility,
        "unit": unit,
        "day_row": day_row,
        "summary": summary,
    }


def setup_submitted_summary_with_day_row(central_line_days: int = 20,
                                         patient_days: int = 40) -> dict:
    """As setup_open_summary_with_day_row, then SUBMITTED (row cascades LOCKED)."""
    ctx = setup_open_summary_with_day_row(central_line_days, patient_days)
    ctx["summary"] = submit_summary(ctx["summary"]["id"])
    ctx["day_row"] = get_device_day_count(ctx["day_row"]["id"])
    return ctx


def setup_unit_with_adjudicated_case(
    organism: str = "Acinetobacter baumannii",
    specimen_at: str = "2026-08-03T09:00:00Z",
    date_of_event: str = "2026-08-03T00:00:00Z",
    clock: Optional[str] = "2026-08-04T00:00:00Z",
    unit_type: str = "WARD",
) -> dict:
    """Facility + unit (+ optional clock pin) + patient + CENTRAL_LINE episode
    + one CLABSI case adjudicated ADJUDICATED_HAI. Returns context dict."""
    facility, unit = setup_facility_unit(unit_type=unit_type)
    if clock is not None:
        set_clock(clock)
    patient = create_patient(unit["id"])
    episode = create_device_episode(patient["id"])
    case = create_adjudicated_clabsi(
        patient["id"], episode["id"], organism, specimen_at, date_of_event
    )
    return {
        "facility": facility,
        "unit": unit,
        "patient": patient,
        "episode": episode,
        "case": case,
    }


def setup_confirmed_investigation(organism: str = "Acinetobacter baumannii") -> dict:
    """Adjudicated case + manual investigation + CONFIRMED (unit in OUTBREAK)."""
    ctx = setup_unit_with_adjudicated_case(organism=organism)
    investigation = create_manual_investigation(ctx["unit"]["id"], organism)
    investigation = confirm_investigation(investigation["id"])
    ctx["investigation"] = investigation
    return ctx


def create_verified_outbreak_cap(unit_id: str, investigation_id: str,
                                 creator_id: str = "ip-user-1",
                                 verifier_id: str = "dir-user-1",
                                 **cap_overrides) -> dict:
    """Create (DRAFT) -> activate -> submit-for-verification -> verify. The
    creator and verifier differ, satisfying segregation of duties."""
    cap = create_cap(unit_id, "OUTBREAK", investigation_id, user_id=creator_id, **cap_overrides)
    activate_cap(cap["id"], user_id=creator_id)
    submit_cap_for_verification(cap["id"], user_id=creator_id)
    return verify_cap(cap["id"], user_id=verifier_id)


# ---------------------------------------------------------------------------
# Tier 4: calculation-targeting composites
# ---------------------------------------------------------------------------

def setup_summary_with_final_and_provisional_case() -> dict:
    """Unit with 500 central-line days in 2026-08, one ADJUDICATED_HAI CLABSI
    (DOE 2026-08-04) and one UNDER_REVIEW CLABSI (specimen 2026-08-06), then the
    2026-08 summary. Drives the final-vs-provisional variant comparison."""
    facility, unit = setup_facility_unit()
    create_device_day_rows(
        unit["id"],
        [
            {
                "count_date": f"2026-08-0{day}T00:00:00Z",
                "central_line_days": 100,
                "urinary_catheter_days": 0,
                "ventilator_days": 0,
                "patient_days": 120,
            }
            for day in range(1, 6)
        ],
    )
    patient_a = create_patient(unit["id"])
    patient_b = create_patient(unit["id"])
    episode_a = create_device_episode(patient_a["id"])
    episode_b = create_device_episode(patient_b["id"])
    case_a = create_adjudicated_clabsi(
        patient_a["id"], episode_a["id"], "Escherichia coli",
        "2026-08-04T10:00:00Z", "2026-08-04T00:00:00Z",
    )
    case_b = create_case_under_review(
        patient_b["id"],
        linked_device_episode_id=episode_b["id"],
        suspected_organism="Staphylococcus aureus",
        first_positive_specimen_at="2026-08-06T09:00:00Z",
    )
    summary = create_monthly_summary(unit["id"], "2026-08")
    return {
        "facility": facility,
        "unit": unit,
        "case_a": case_a,
        "case_b": case_b,
        "summary": summary,
    }


def setup_or_unit_with_tiered_procedures_and_ssi() -> dict:
    """OR unit with LOW (ASA 2, CLEAN), MEDIUM (ASA 3, CLEAN) and HIGH
    (ASA 4, CONTAMINATED) procedures in 2026-08 plus one SSI case on the LOW
    procedure adjudicated ADJUDICATED_HAI (DOE 2026-08-10), then the summary."""
    facility, unit = setup_facility_unit(unit_type="OR")
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    patient_3 = create_patient(unit["id"])
    proc_low = create_surgical_procedure(
        patient_1["id"], procedure_code="COLO", performed_at="2026-08-03T09:00:00Z",
        duration_minutes=60, asa_score=2, wound_class="CLEAN",
    )
    create_surgical_procedure(
        patient_2["id"], procedure_code="HYST", performed_at="2026-08-04T09:00:00Z",
        duration_minutes=90, asa_score=3, wound_class="CLEAN",
    )
    create_surgical_procedure(
        patient_3["id"], procedure_code="CRAN", performed_at="2026-08-05T09:00:00Z",
        duration_minutes=120, asa_score=4, wound_class="CONTAMINATED",
    )
    case = create_infection_case(
        patient_1["id"],
        case_type="SSI",
        suspected_organism="Staphylococcus aureus",
        first_positive_specimen_at="2026-08-10T09:00:00Z",
        surgical_procedure_id=proc_low["id"],
    )
    begin_review(case["id"])
    case = adjudicate_hai(case["id"], "2026-08-10T00:00:00Z",
                          rationale="deep incisional SSI within 30d", ssi_depth="DEEP")
    summary = create_monthly_summary(unit["id"], "2026-08")
    return {"facility": facility, "unit": unit, "case": case, "summary": summary}


def setup_unit_with_weighted_observations() -> dict:
    """40 observations in 2026-08: 20 BEFORE_PATIENT_CONTACT (15 COMPLIANT),
    10 ASEPTIC_TASK (8 COMPLIANT), 10 BODY_FLUID_RISK (7 COMPLIANT)."""
    facility, unit = setup_facility_unit(unit_type="WARD")
    record_observation_batch(unit["id"], "2026-08-03", "08:00", 15,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT")
    record_observation_batch(unit["id"], "2026-08-03", "09:15", 5,
                             "BEFORE_PATIENT_CONTACT", "MISSED")
    record_observation_batch(unit["id"], "2026-08-04", "08:00", 8,
                             "ASEPTIC_TASK", "COMPLIANT")
    record_observation_batch(unit["id"], "2026-08-04", "08:40", 2,
                             "ASEPTIC_TASK", "MISSED")
    record_observation_batch(unit["id"], "2026-08-05", "08:00", 7,
                             "BODY_FLUID_RISK", "COMPLIANT")
    record_observation_batch(unit["id"], "2026-08-05", "08:35", 3,
                             "BODY_FLUID_RISK", "MISSED")
    return {"facility": facility, "unit": unit}


def setup_unit_with_skewed_observation_weeks() -> dict:
    """36 BEFORE_PATIENT_CONTACT observations in 2026-08: ISO week 1 has 12
    (8 COMPLIANT), ISO week 2 has 24 (4 COMPLIANT). All weight 1.0."""
    facility, unit = setup_facility_unit(unit_type="WARD")
    # Week 1 (2026-08-03..09): 8 compliant, 4 missed.
    record_observation_batch(unit["id"], "2026-08-03", "08:00", 4,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT", step_minutes=10)
    record_observation_batch(unit["id"], "2026-08-04", "08:00", 4,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT", step_minutes=10)
    record_observation_batch(unit["id"], "2026-08-05", "08:00", 4,
                             "BEFORE_PATIENT_CONTACT", "MISSED", step_minutes=10)
    # Week 2 (2026-08-10..16): 4 compliant, 20 missed.
    record_observation_batch(unit["id"], "2026-08-10", "08:00", 4,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT", step_minutes=10)
    record_observation_batch(unit["id"], "2026-08-11", "08:00", 10,
                             "BEFORE_PATIENT_CONTACT", "MISSED", step_minutes=5)
    record_observation_batch(unit["id"], "2026-08-12", "08:00", 10,
                             "BEFORE_PATIENT_CONTACT", "MISSED", step_minutes=5)
    return {"facility": facility, "unit": unit}


def setup_two_units_straddling_sir_floor() -> dict:
    """Unit A with 500 central-line days (predicted exactly 1.0) and unit B
    with 499 (predicted 0.998), both with 2026-08 summaries and no cases."""
    facility = create_facility()
    unit_a = create_unit(facility["id"], name="ICU-A")
    unit_b = create_unit(facility["id"], name="ICU-B")
    create_device_day_rows(
        unit_a["id"],
        [
            {
                "count_date": f"2026-08-0{day}T00:00:00Z",
                "central_line_days": 100,
                "urinary_catheter_days": 0,
                "ventilator_days": 0,
                "patient_days": 120,
            }
            for day in range(1, 6)
        ],
    )
    rows_b = [
        {
            "count_date": f"2026-08-0{day}T00:00:00Z",
            "central_line_days": 100,
            "urinary_catheter_days": 0,
            "ventilator_days": 0,
            "patient_days": 120,
        }
        for day in range(1, 5)
    ]
    rows_b.append(
        {
            "count_date": "2026-08-05T00:00:00Z",
            "central_line_days": 99,
            "urinary_catheter_days": 0,
            "ventilator_days": 0,
            "patient_days": 120,
        }
    )
    create_device_day_rows(unit_b["id"], rows_b)
    summary_a = create_monthly_summary(unit_a["id"], "2026-08")
    summary_b = create_monthly_summary(unit_b["id"], "2026-08")
    return {
        "facility": facility,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "summary_a": summary_a,
        "summary_b": summary_b,
    }


def setup_two_active_contact_orders() -> dict:
    """Two patients, each with an ACTIVE CONTACT isolation order on one unit."""
    facility, unit = setup_facility_unit(unit_type="WARD")
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    order_1 = create_active_isolation_order(patient_1["id"], precaution_type="CONTACT")
    order_2 = create_active_isolation_order(patient_2["id"], precaution_type="CONTACT")
    return {
        "facility": facility,
        "unit": unit,
        "patient_1": patient_1,
        "patient_2": patient_2,
        "order_1": order_1,
        "order_2": order_2,
    }


def setup_case_under_review_with_open_summary() -> dict:
    """CLABSI case UNDER_REVIEW (specimen 2026-08-04) with an OPEN 2026-08
    summary already existing (baseline count 0)."""
    ctx = setup_unit_with_patient_and_episode()
    case = create_case_under_review(
        ctx["patient"]["id"],
        linked_device_episode_id=ctx["episode"]["id"],
        suspected_organism="Candida albicans",
        first_positive_specimen_at="2026-08-04T10:00:00Z",
    )
    summary = create_monthly_summary(ctx["unit"]["id"], "2026-08")
    ctx.update({"case": case, "summary": summary})
    return ctx


def setup_outbreak_posture_with_open_summary() -> dict:
    """Unit in OUTBREAK posture (adjudicated case + manual investigation
    CONFIRMED) with the 2026-08 summary sitting OPEN."""
    ctx = setup_unit_with_adjudicated_case()
    summary = create_monthly_summary(ctx["unit"]["id"], "2026-08")
    investigation = create_manual_investigation(
        ctx["unit"]["id"], "Acinetobacter baumannii"
    )
    investigation = confirm_investigation(investigation["id"])
    ctx.update({"summary": summary, "investigation": investigation})
    return ctx


def setup_cluster_scenario(organism: str = "Klebsiella pneumoniae") -> dict:
    """Facility + ICU unit + three patients each with a CENTRAL_LINE episode
    placed 2026-08-01. Two same-organism CLABSI cases are adjudicated
    ADJUDICATED_HAI (DOEs 2026-08-03 and 2026-08-06, logical clock moved between
    them); the third patient/episode/case is left ready for the caller to drive
    the threshold-crossing third adjudication. Returns a context dict."""
    facility, unit = setup_facility_unit()
    set_clock("2026-08-01T00:00:00Z")
    patients = [create_patient(unit["id"]) for _ in range(3)]
    episodes = [create_device_episode(p["id"]) for p in patients]
    case_1 = create_adjudicated_clabsi(
        patients[0]["id"], episodes[0]["id"], organism,
        "2026-08-03T09:00:00Z", "2026-08-03T00:00:00Z",
    )
    set_clock("2026-08-06T00:00:00Z")
    case_2 = create_adjudicated_clabsi(
        patients[1]["id"], episodes[1]["id"], organism,
        "2026-08-06T09:00:00Z", "2026-08-06T00:00:00Z",
    )
    case_3 = create_case_under_review(
        patients[2]["id"],
        linked_device_episode_id=episodes[2]["id"],
        suspected_organism=organism,
        first_positive_specimen_at="2026-08-09T09:00:00Z",
    )
    return {
        "facility": facility,
        "unit": unit,
        "patients": patients,
        "episodes": episodes,
        "case_1": case_1,
        "case_2": case_2,
        "case_3": case_3,
        "organism": organism,
    }
