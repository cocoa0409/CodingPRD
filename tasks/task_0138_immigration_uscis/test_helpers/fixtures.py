"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., an I-485 in
RFE_RESPONDED, an I-130 APPROVED with dependent I-485 in
INTERVIEW_SCHEDULED). Each fixture composes the lower-level steps so
the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

- Officer / Supervisor are OPAQUE; shared constants
  (officer_headers, supervisor_headers) are canonical.

- Petitioner is ENTITY-BACKED. PRD §2.1: "Petitioners may read and act
  only on cases whose petitioner_id matches their own X-User-ID."
  Every Petitioner-driven call (POST /cases, POST /cases/{id}/file,
  POST /cases/{id}/withdraw, POST /rfes/{id}/respond) MUST use
  make_petitioner_headers(petitioner["id"]) where petitioner is the
  actual Petitioner row.

- Beneficiary is ENTITY-BACKED. Use
  make_beneficiary_headers(beneficiary["id"]) for any
  Beneficiary-acting ownership-gated call (e.g., GET
  /beneficiaries/{id} reading self).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BIOMETRICS_LEAD_DAYS,
    DEFAULT_RFE_WINDOW_DAYS,
    INTERVIEW_LEAD_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    bulletin_month_of,
    case_type_config_payload,
    chart_in_effect_payload,
    clock_advance_payload,
    complete_interview_payload,
    create_beneficiary_payload,
    create_case_payload,
    create_petitioner_payload,
    decide_case_payload,
    iso_instant_utc,
    iso_offset,
    iso_utc,
    issue_rfe_payload,
    parse_iso,
    reschedule_biometrics_payload,
    schedule_biometrics_payload,
    schedule_interview_payload,
    utcnow,
    visa_bulletin_payload,
)
from .test_users import (
    TEST_USERS,
    make_petitioner_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.10 (Supervisor)
# ===========================================================================
def advance_clock_to(
    to_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §3.10: Supervisor-only."""
    headers = headers or TEST_USERS["supervisor_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to=to_iso), headers,
    )
    return get_success_data(resp)


def get_clock_now(
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """GET /_clock. Returns the now field as ISO 8601 string."""
    headers = headers or TEST_USERS["supervisor_headers"]
    resp = api_client.get_clock(headers)
    data = get_success_data(resp)
    return data["now"]


def server_now_dt() -> datetime:
    """Return the server's current clock as a UTC datetime."""
    return parse_iso(get_clock_now())


def server_offset_iso(*, days: int = 0, hours: int = 0,
                     minutes: int = 0, seconds: int = 0,
                     millis: int = 0) -> str:
    """Return an ISO 8601 UTC timestamp offset from the server's
    current clock. Use this for any scheduled_at / new_scheduled_at
    payload so the offset is anchored to the SERVER's wall clock
    (which the test may have advanced via /_clock/advance), not the
    test runner's local wall clock.
    """
    base = server_now_dt()
    return iso_utc(
        base + timedelta(days=days, hours=hours, minutes=minutes,
                         seconds=seconds, milliseconds=millis),
    )


# ===========================================================================
# CaseTypeConfig — PRD §3.3 (Supervisor)
# ===========================================================================
def upsert_case_type_config(
    *,
    case_type: str,
    requires_biometrics: bool,
    requires_interview: bool,
    rfe_response_window_days: int = DEFAULT_RFE_WINDOW_DAYS,
    requires_priority_date_current: bool = False,
    receipt_prefix: str = "MSC",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /admin/case-type-config — PRD §3.3 (Supervisor)."""
    headers = headers or TEST_USERS["supervisor_headers"]
    payload = case_type_config_payload(
        case_type=case_type,
        requires_biometrics=requires_biometrics,
        requires_interview=requires_interview,
        rfe_response_window_days=rfe_response_window_days,
        requires_priority_date_current=requires_priority_date_current,
        receipt_prefix=receipt_prefix,
    )
    resp = api_client.upsert_case_type_config(payload, headers)
    return get_success_data(resp)


def seed_all_case_type_configs(
    *,
    receipt_prefix: str = "MSC",
    rfe_window: int = DEFAULT_RFE_WINDOW_DAYS,
) -> Dict[str, Dict[str, Any]]:
    """Seed CaseTypeConfig rows for all four case types matching the
    PRD-pinned defaults.

    PRD §3.3: "requires_biometrics ... requires_interview ... — true
    for I-485 outside the IR category".
    PRD §3.6: "The Adjustment of Status interview is only valid for
    I-485 cases".
    """
    out: Dict[str, Dict[str, Any]] = {}
    out["I-130"] = upsert_case_type_config(
        case_type="I-130",
        requires_biometrics=False,
        requires_interview=False,
        rfe_response_window_days=rfe_window,
        requires_priority_date_current=False,
        receipt_prefix=receipt_prefix,
    )
    out["I-485"] = upsert_case_type_config(
        case_type="I-485",
        requires_biometrics=True,
        requires_interview=True,
        rfe_response_window_days=rfe_window,
        requires_priority_date_current=True,
        receipt_prefix=receipt_prefix,
    )
    out["I-765"] = upsert_case_type_config(
        case_type="I-765",
        requires_biometrics=False,
        requires_interview=False,
        rfe_response_window_days=rfe_window,
        requires_priority_date_current=False,
        receipt_prefix=receipt_prefix,
    )
    out["I-131"] = upsert_case_type_config(
        case_type="I-131",
        requires_biometrics=False,
        requires_interview=False,
        rfe_response_window_days=rfe_window,
        requires_priority_date_current=False,
        receipt_prefix=receipt_prefix,
    )
    return out


# ===========================================================================
# Petitioner / Beneficiary — PRD §3.1
# ===========================================================================
def create_petitioner(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    country_of_citizenship: Optional[str] = None,
    email: Optional[str] = None,
    a_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /petitioners — PRD §3.1.

    Default actor is Officer (opaque) — PRD §3.1: "A Petitioner may
    create only their own petitioner record (their X-User-ID becomes
    its id)". Officer/Supervisor creation does not exercise ownership,
    so the Officer header is safe for setup.
    """
    headers = headers or TEST_USERS["officer_headers"]
    payload = create_petitioner_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        country_of_citizenship=country_of_citizenship,
        email=email,
        a_number=a_number,
        **overrides,
    )
    resp = api_client.create_petitioner(payload, headers)
    return get_success_data(resp)


def create_beneficiary(
    petitioner: Dict[str, Any],
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    country_of_chargeability: Optional[str] = None,
    preference_category: Optional[str] = None,
    relationship_to_petitioner: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /petitioners/{id}/beneficiaries — PRD §3.1.

    PRD §3.1: "A Petitioner may create only ... beneficiaries under
    that own petitioner". Default actor is Officer (opaque) so setup
    does not exercise petitioner-ownership. To exercise ownership,
    pass headers=make_petitioner_headers(petitioner["id"]).
    """
    headers = headers or TEST_USERS["officer_headers"]
    payload = create_beneficiary_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        country_of_chargeability=country_of_chargeability,
        preference_category=preference_category,
        relationship_to_petitioner=relationship_to_petitioner,
        **overrides,
    )
    resp = api_client.create_beneficiary(
        petitioner["id"], payload, headers,
    )
    return get_success_data(resp)


def setup_petitioner_and_beneficiary(
    *,
    preference_category: str = "F2A",
    country_of_chargeability: str = "MEX",
    relationship_to_petitioner: str = "SPOUSE",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create Petitioner + Beneficiary in one step. Returns
    (petitioner, beneficiary).
    """
    petitioner = create_petitioner()
    beneficiary = create_beneficiary(
        petitioner,
        preference_category=preference_category,
        country_of_chargeability=country_of_chargeability,
        relationship_to_petitioner=relationship_to_petitioner,
    )
    return petitioner, beneficiary


# ===========================================================================
# Case CRUD — PRD §3.2
# ===========================================================================
def create_case(
    petitioner: Dict[str, Any],
    beneficiary: Dict[str, Any],
    *,
    case_type: str,
    linked_i130_case_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases — PRD §3.2.

    PRD §3.1 / §2.1: "A Petitioner may create ... only cases
    referencing that own petitioner". To exercise petitioner-ownership
    creation, pass headers=make_petitioner_headers(petitioner["id"]).
    Default uses Officer (opaque) so creation is unrestricted in
    setup.
    """
    headers = headers or TEST_USERS["officer_headers"]
    payload = create_case_payload(
        petitioner_id=petitioner["id"],
        beneficiary_id=beneficiary["id"],
        case_type=case_type,
        linked_i130_case_id=linked_i130_case_id,
    )
    resp = api_client.create_case(payload, headers)
    return get_success_data(resp)


def file_case(
    case: Dict[str, Any],
    petitioner: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{id}/file — PRD §4: Petitioner role exclusive.

    PRD §2.1: "Petitioners may read and act only on cases whose
    petitioner_id matches their own X-User-ID." Petitioner-acting
    ownership-gated. Mint headers from the petitioner's id unless the
    caller passed an override (e.g., to test a different actor).
    """
    headers = headers or make_petitioner_headers(petitioner["id"])
    resp = api_client.file_case(case["id"], headers)
    return get_success_data(resp)


def withdraw_case(
    case: Dict[str, Any],
    petitioner: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{id}/withdraw — PRD §4: Petitioner role exclusive.

    Petitioner-acting ownership-gated; mint headers from the
    petitioner's id.
    """
    headers = headers or make_petitioner_headers(petitioner["id"])
    resp = api_client.withdraw_case(case["id"], headers)
    return get_success_data(resp)


def re_get_case(case_id: str,
                headers: Optional[Dict[str, str]] = None,
                ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.get_case(case_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Biometrics — PRD §3.4 (Officer)
# ===========================================================================
def schedule_biometrics(
    case: Dict[str, Any],
    *,
    days_ahead: int = BIOMETRICS_LEAD_DAYS + 1,
    location_code: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{id}/biometrics — PRD §3.4 (Officer)."""
    headers = headers or TEST_USERS["officer_headers"]
    if scheduled_at is None:
        scheduled_at = server_offset_iso(days=days_ahead)
    payload = schedule_biometrics_payload(
        scheduled_at=scheduled_at, location_code=location_code,
    )
    resp = api_client.schedule_biometrics(case["id"], payload, headers)
    return get_success_data(resp)


def complete_biometrics(
    biometrics: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /biometrics/{id}/complete — PRD §3.4 (Officer).

    PRD §3.4: "Marking the appointment completed requires that ... the
    current time be at or after the recorded scheduled_at." Caller
    must advance the clock first.
    """
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.complete_biometrics(biometrics["id"], headers)
    return get_success_data(resp)


def reschedule_biometrics(
    biometrics: Dict[str, Any],
    *,
    new_scheduled_at: Optional[str] = None,
    days_ahead: int = BIOMETRICS_LEAD_DAYS + 1,
    location_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    if new_scheduled_at is None:
        new_scheduled_at = server_offset_iso(days=days_ahead)
    payload = reschedule_biometrics_payload(
        new_scheduled_at=new_scheduled_at, location_code=location_code,
    )
    resp = api_client.reschedule_biometrics(
        biometrics["id"], payload, headers,
    )
    return get_success_data(resp)


def no_show_biometrics(biometrics: Dict[str, Any],
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.no_show_biometrics(biometrics["id"], headers)
    return get_success_data(resp)


# ===========================================================================
# RFE — PRD §3.5
# ===========================================================================
def issue_rfe(
    case: Dict[str, Any],
    *,
    reason_code: str = "MISSING_DOC",
    officer_notes: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /cases/{id}/rfe — PRD §3.5 (Officer)."""
    headers = headers or TEST_USERS["officer_headers"]
    payload = issue_rfe_payload(
        reason_code=reason_code, officer_notes=officer_notes,
    )
    resp = api_client.issue_rfe(case["id"], payload, headers)
    return get_success_data(resp)


def respond_rfe(
    rfe: Dict[str, Any],
    petitioner: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /rfes/{id}/respond — PRD §4: Beneficiary, Petitioner.

    PRD §3.5: "The beneficiary (or the petitioner acting for the
    beneficiary) responds to an RFE." Ownership-gated; default routes
    through make_petitioner_headers(petitioner["id"]).
    """
    headers = headers or make_petitioner_headers(petitioner["id"])
    resp = api_client.respond_rfe(rfe["id"], headers)
    return get_success_data(resp)


# ===========================================================================
# Interview — PRD §3.6 (Officer)
# ===========================================================================
def schedule_interview(
    case: Dict[str, Any],
    *,
    days_ahead: int = INTERVIEW_LEAD_DAYS + 1,
    field_office_code: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    if scheduled_at is None:
        scheduled_at = server_offset_iso(days=days_ahead)
    payload = schedule_interview_payload(
        scheduled_at=scheduled_at, field_office_code=field_office_code,
    )
    resp = api_client.schedule_interview(case["id"], payload, headers)
    return get_success_data(resp)


def complete_interview(
    interview: Dict[str, Any],
    *,
    outcome: str = "RECOMMEND_APPROVAL",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    payload = complete_interview_payload(outcome=outcome)
    resp = api_client.complete_interview(
        interview["id"], payload, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Decide / ready-for-decision — PRD §3.7
# ===========================================================================
def decide_case(
    case: Dict[str, Any],
    *,
    decision: str,
    denial_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    payload = decide_case_payload(
        decision=decision, denial_reason=denial_reason,
    )
    resp = api_client.decide_case(case["id"], payload, headers)
    return get_success_data(resp)


def ready_for_decision(case: Dict[str, Any],
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.ready_for_decision(case["id"], headers)
    return get_success_data(resp)


def refresh_priority_date(case: Dict[str, Any],
                          headers: Optional[Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["officer_headers"]
    resp = api_client.refresh_priority_date(case["id"], headers)
    return get_success_data(resp)


# ===========================================================================
# Visa Bulletin — PRD §3.9 (Supervisor)
# ===========================================================================
def publish_bulletin(
    *,
    bulletin_month: str,
    chart_type: str = "FINAL_ACTION",
    preference_category: str = "F2A",
    country: str = "MEX",
    cutoff_date: str = "CURRENT",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["supervisor_headers"]
    payload = visa_bulletin_payload(
        bulletin_month=bulletin_month,
        chart_type=chart_type,
        preference_category=preference_category,
        country=country,
        cutoff_date=cutoff_date,
    )
    resp = api_client.publish_visa_bulletin(payload, headers)
    return get_success_data(resp)


def set_chart_in_effect(chart_type: str,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["supervisor_headers"]
    payload = chart_in_effect_payload(chart_type=chart_type)
    resp = api_client.set_chart_in_effect(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Composite fixtures — drive cases to specific states.
# ===========================================================================

def seed_world(
    *,
    receipt_prefix: str = "MSC",
    pin_clock_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Bootstrap a fresh world: all CaseTypeConfigs seeded and the
    server clock (optionally) pinned to a deterministic instant.

    Returns {"configs": {...}, "clock_iso": str|None}.
    """
    configs = seed_all_case_type_configs(receipt_prefix=receipt_prefix)
    clock_iso: Optional[str] = None
    if pin_clock_to is not None:
        advance_clock_to(pin_clock_to)
        clock_iso = pin_clock_to
    return {"configs": configs, "clock_iso": clock_iso}


def setup_filed_case(
    *,
    case_type: str = "I-130",
    preference_category: str = "F2A",
    country_of_chargeability: str = "MEX",
    receipt_prefix: str = "MSC",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive a case from creation to FILED.

    For I-485 with a non-IR beneficiary, also creates and approves an
    I-130 first to satisfy ERR_I485_MISSING_APPROVED_I130.

    Returns a dict with keys: petitioner, beneficiary, case, and
    (for I-485 with linked I-130) i130.
    """
    if seed_configs:
        seed_all_case_type_configs(receipt_prefix=receipt_prefix)
    petitioner, beneficiary = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
        country_of_chargeability=country_of_chargeability,
    )

    if case_type == "I-485" and preference_category != "IR":
        # Need a linked APPROVED I-130 first.
        i130_case = create_case(
            petitioner, beneficiary, case_type="I-130",
        )
        i130_case = file_case(i130_case, petitioner)
        i130_case = ready_for_decision(i130_case)
        i130_case = decide_case(i130_case, decision="APPROVE")
        case = create_case(
            petitioner, beneficiary,
            case_type="I-485",
            linked_i130_case_id=i130_case["id"],
        )
        case = file_case(case, petitioner)
        return {
            "petitioner": petitioner,
            "beneficiary": beneficiary,
            "case": case,
            "i130": i130_case,
        }

    case = create_case(petitioner, beneficiary, case_type=case_type)
    case = file_case(case, petitioner)
    return {
        "petitioner": petitioner,
        "beneficiary": beneficiary,
        "case": case,
    }


def setup_biometrics_completed(
    *,
    case_type: str = "I-485",
    preference_category: str = "F2A",
    country_of_chargeability: str = "MEX",
    receipt_prefix: str = "MSC",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive a case (requires_biometrics=true case type) through
    FILED -> BIOMETRICS_SCHEDULED -> BIOMETRICS_COMPLETED.
    """
    bundle = setup_filed_case(
        case_type=case_type,
        preference_category=preference_category,
        country_of_chargeability=country_of_chargeability,
        receipt_prefix=receipt_prefix,
        seed_configs=seed_configs,
    )
    case = bundle["case"]
    bio = schedule_biometrics(case, days_ahead=8)
    # PRD §3.4: completion requires now() >= scheduled_at — advance
    # clock past the appointment.
    advance_clock_to(server_offset_iso(days=9))
    bio = complete_biometrics(bio)
    bundle["biometrics"] = bio
    bundle["case"] = re_get_case(case["id"])
    return bundle


def setup_rfe_responded(
    *,
    case_type: str = "I-485",
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive an I-485 case to RFE_RESPONDED state."""
    bundle = setup_biometrics_completed(
        case_type=case_type,
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    case = bundle["case"]
    rfe = issue_rfe(case)
    bundle["rfe"] = rfe
    # Beneficiary responds in-window (default RFE window is 87 days).
    rfe = respond_rfe(rfe, bundle["petitioner"])
    bundle["rfe"] = rfe
    bundle["case"] = re_get_case(case["id"])
    return bundle


def setup_interview_scheduled(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive an I-485 case to INTERVIEW_SCHEDULED state via
    BIOMETRICS_COMPLETED -> RFE_ISSUED -> RFE_RESPONDED -> interview
    scheduling.
    """
    bundle = setup_rfe_responded(
        case_type="I-485",
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    interview = schedule_interview(bundle["case"], days_ahead=15)
    bundle["interview"] = interview
    bundle["case"] = re_get_case(bundle["case"]["id"])
    return bundle


def setup_ready_for_decision_i485(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive an I-485 case to READY_FOR_DECISION via the full
    interview path.
    """
    bundle = setup_interview_scheduled(
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    interview = bundle["interview"]
    advance_clock_to(server_offset_iso(days=16))
    interview = complete_interview(interview, outcome="RECOMMEND_APPROVAL")
    bundle["interview"] = interview
    bundle["case"] = re_get_case(bundle["case"]["id"])
    return bundle


def setup_ready_for_decision_i130(
    *,
    preference_category: str = "F2A",
    receipt_prefix: str = "MSC",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive an I-130 case to READY_FOR_DECISION via FILED ->
    ready-for-decision (I-130 has requires_biometrics=false and
    requires_interview=false).
    """
    bundle = setup_filed_case(
        case_type="I-130",
        preference_category=preference_category,
        receipt_prefix=receipt_prefix,
        seed_configs=seed_configs,
    )
    case = ready_for_decision(bundle["case"])
    bundle["case"] = case
    return bundle


def setup_approved_i130_with_dependent_i485(
    *,
    preference_category: str = "F2A",
    country_of_chargeability: str = "MEX",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """I-130 driven to APPROVED, then an I-485 dependent created in
    DRAFT with linked_i130_case_id set. Returns
    {petitioner, beneficiary, i130, i485}.
    """
    if seed_configs:
        seed_all_case_type_configs()
    petitioner, beneficiary = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
        country_of_chargeability=country_of_chargeability,
    )
    i130 = create_case(petitioner, beneficiary, case_type="I-130")
    i130 = file_case(i130, petitioner)
    i130 = ready_for_decision(i130)
    i130 = decide_case(i130, decision="APPROVE")
    i485 = create_case(
        petitioner, beneficiary,
        case_type="I-485",
        linked_i130_case_id=i130["id"],
    )
    return {
        "petitioner": petitioner,
        "beneficiary": beneficiary,
        "i130": i130,
        "i485": i485,
    }


def setup_i130_in_rfe_issued(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Drive an I-130 from FILED -> RFE_ISSUED (I-130 has
    requires_biometrics=false so RFE can issue directly from FILED).
    """
    bundle = setup_filed_case(
        case_type="I-130",
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    case = bundle["case"]
    rfe = issue_rfe(case)
    bundle["rfe"] = rfe
    bundle["case"] = re_get_case(case["id"])
    return bundle


def setup_i130_in_rfe_issued_with_dependent_i485_filed(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """I-130 driven to RFE_ISSUED; dependent I-485 created in DRAFT
    with linked_i130_case_id pointing to the I-130. Returns
    {petitioner, beneficiary, i130, i485, rfe}.

    NOTE: PRD §3.2 / §3.7 / §1.4 priority 7 — an I-485 can only enter
    FILED when its linked I-130 is APPROVED. The dependent I-485 in
    this fixture stays in DRAFT until the I-130 cascade either
    approves or denies it; the cascade only affects I-485s with
    non-terminal status, and a dependent I-485 in DRAFT is
    non-terminal (DRAFT is not in {APPROVED, DENIED, WITHDRAWN}).
    """
    if seed_configs:
        seed_all_case_type_configs()
    petitioner, beneficiary = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
    )
    i130 = create_case(petitioner, beneficiary, case_type="I-130")
    i130 = file_case(i130, petitioner)
    rfe = issue_rfe(i130)
    i130 = re_get_case(i130["id"])
    # Dependent I-485 in DRAFT (cannot file yet — I-130 not approved).
    i485 = create_case(
        petitioner, beneficiary,
        case_type="I-485",
        linked_i130_case_id=i130["id"],
    )
    return {
        "petitioner": petitioner,
        "beneficiary": beneficiary,
        "i130": i130,
        "i485": i485,
        "rfe": rfe,
    }


def setup_dependent_i485_in_interview_scheduled(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """
    I-130 APPROVED, dependent I-485 driven all the way to
    INTERVIEW_SCHEDULED with a SCHEDULED Biometrics and SCHEDULED
    Interview.

    Then transition the I-130 BACK into a posture where it can be
    DENIED via decide-action (this is NOT possible — once APPROVED is
    terminal). Instead this fixture is the building block for the
    rfe_timeout_chain_depth3 difficulty instance: an I-130 in
    RFE_ISSUED + dependent I-485 in INTERVIEW_SCHEDULED. To keep that
    state, we DO NOT approve the I-130. We file a new fresh I-130
    instead and drive only the dependent independently? — that breaks
    the FK constraint.

    Used by: i130_deny_chain_depth3 — which requires the I-130 to
    still be in READY_FOR_DECISION, NOT yet APPROVED. We expose a
    different fixture below for that case
    (setup_i130_ready_with_dependent_i485_interview_scheduled).

    Returns {petitioner, beneficiary, i130, i485, biometrics,
    interview}.
    """
    bundle = setup_approved_i130_with_dependent_i485(
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    petitioner = bundle["petitioner"]
    i485 = file_case(bundle["i485"], petitioner)
    # I-485 needs biometrics before interview.
    bio = schedule_biometrics(i485, days_ahead=8)
    advance_clock_to(server_offset_iso(days=9))
    bio = complete_biometrics(bio)
    i485 = re_get_case(i485["id"])
    interview = schedule_interview(i485, days_ahead=15)
    i485 = re_get_case(i485["id"])
    bundle["i485"] = i485
    bundle["biometrics"] = bio
    bundle["interview"] = interview
    return bundle


def setup_i130_ready_with_dependent_i485_interview_scheduled(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Build the precondition for the i130_deny_chain_depth3
    difficulty instance:

      - I-130 in READY_FOR_DECISION (not yet decided)
      - dependent I-485 in INTERVIEW_SCHEDULED with one SCHEDULED
        Biometrics chain alive (its latest row is the SCHEDULED one
        used for interview prep) and one SCHEDULED Interview

    Implementation note: an I-485 cannot file until the I-130 is
    APPROVED, so to land both cases in their target states
    simultaneously we file and decide the I-130 to APPROVED first,
    then drive the I-485 forward, then we file a SECOND fresh I-130
    purely so something is "in READY_FOR_DECISION" — but THAT second
    I-130 has no dependent.

    Therefore this fixture instead uses two beneficiaries: one
    APPROVED I-130 (for the I-485 to reference) and one separate
    Petitioner+Beneficiary+I-130 in READY_FOR_DECISION whose denial
    we test (no cascade, no dependent). The TEST FILE for the
    difficulty instance must accept this representation — see the
    fixture variant below for the cascade-correct path that uses the
    RFE-timeout chain (which CAN reach a dependent I-485 via the
    cascade).

    Returns {primary_petitioner, primary_beneficiary, i130_ready,
    i130_approved, dependent_i485, dep_biometrics, dep_interview}.
    """
    # Build the cascading dependent first.
    cascade = setup_dependent_i485_in_interview_scheduled(
        preference_category=preference_category,
        seed_configs=seed_configs,
    )
    # Build a separate ready-for-decision I-130 for denial test.
    petitioner2, beneficiary2 = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
    )
    i130_ready = create_case(
        petitioner2, beneficiary2, case_type="I-130",
    )
    i130_ready = file_case(i130_ready, petitioner2)
    i130_ready = ready_for_decision(i130_ready)
    return {
        "primary_petitioner": cascade["petitioner"],
        "primary_beneficiary": cascade["beneficiary"],
        "i130_approved": cascade["i130"],
        "dependent_i485": cascade["i485"],
        "dep_biometrics": cascade["biometrics"],
        "dep_interview": cascade["interview"],
        "petitioner_ready": petitioner2,
        "beneficiary_ready": beneficiary2,
        "i130_ready": i130_ready,
    }


def setup_i130_ready_with_real_dependent_i485(
    *,
    preference_category: str = "F2A",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """Build the I-130 deny-cascade fixture using the only PRD-
    supported path: the dependent I-485 must already be FILED (which
    requires its linked I-130 to be APPROVED), so we cannot have
    BOTH (I-130 in READY_FOR_DECISION) AND (dependent I-485 past
    DRAFT).

    Strategy used here: we file a FIRST I-130 (proxy) and APPROVE it
    so the I-485 can be filed and driven to INTERVIEW_SCHEDULED. The
    cascade target is then this proxy I-130's denial — but that I-130
    is already APPROVED (terminal), so it cannot be DENIED.

    Conclusion: the only way to test the i130_deny_chain_depth3
    cascade observably is to construct the case before the proxy
    decision. Use a fresh I-130 (RIGHT after RFE_RESPONDED -> ready)
    that has a NON-FILED dependent in DRAFT — and observe the cascade
    on the DRAFT dependent. This downgrades the assertion fidelity:
    PRD §3.7 says "every dependent I-485 whose linked_i130_case_id
    references this case and whose own status is not already one of
    APPROVED/DENIED/WITHDRAWN" — DRAFT qualifies as non-terminal, so
    the cascade still fires.

    Returns {petitioner, beneficiary, i130, dependent_i485_draft}.
    """
    if seed_configs:
        seed_all_case_type_configs()
    petitioner, beneficiary = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
    )
    # Build an I-130 in READY_FOR_DECISION (not yet decided).
    i130 = create_case(petitioner, beneficiary, case_type="I-130")
    i130 = file_case(i130, petitioner)
    i130 = ready_for_decision(i130)
    # Dependent I-485 in DRAFT (cannot file yet).
    dep_i485 = create_case(
        petitioner, beneficiary, case_type="I-485",
        linked_i130_case_id=i130["id"],
    )
    return {
        "petitioner": petitioner,
        "beneficiary": beneficiary,
        "i130": i130,
        "dependent_i485_draft": dep_i485,
    }


def setup_priority_date_inheritance_world(
    *,
    pin_clock_iso: str = "2026-05-18T00:00:00.000Z",
    bulletin_month: str = "2026-06",
    final_action_cutoff: str = "2026-04-01",
    dates_for_filing_cutoff: str = "2026-09-01",
    preference_category: str = "F2A",
    country: str = "MEX",
    seed_configs: bool = True,
) -> Dict[str, Any]:
    """World for the priority_date_currency dual-chart difficulty
    instance.

    Bootstraps:
      - All CaseTypeConfigs.
      - Clock pinned to `pin_clock_iso`.
      - I-130 created, filed, APPROVED (priority_date = pin date).
      - Two bulletin rows for the given bulletin_month
        (FINAL_ACTION, DATES_FOR_FILING) at the cutoffs supplied.
      - Dependent I-485 created (linked_i130_case_id) and filed
        (priority_date inherits from I-130).

    Returns {petitioner, beneficiary, i130, i485, bulletins,
    pin_clock_iso}.
    """
    if seed_configs:
        seed_all_case_type_configs()
    advance_clock_to(pin_clock_iso)
    petitioner, beneficiary = setup_petitioner_and_beneficiary(
        preference_category=preference_category,
        country_of_chargeability=country,
    )
    # Publish bulletin rows BEFORE filing the I-485 so the recompute
    # on FILED has data.
    fa = publish_bulletin(
        bulletin_month=bulletin_month,
        chart_type="FINAL_ACTION",
        preference_category=preference_category,
        country=country,
        cutoff_date=final_action_cutoff,
    )
    dff = publish_bulletin(
        bulletin_month=bulletin_month,
        chart_type="DATES_FOR_FILING",
        preference_category=preference_category,
        country=country,
        cutoff_date=dates_for_filing_cutoff,
    )
    i130 = create_case(petitioner, beneficiary, case_type="I-130")
    i130 = file_case(i130, petitioner)
    i130 = ready_for_decision(i130)
    i130 = decide_case(i130, decision="APPROVE")
    i485 = create_case(
        petitioner, beneficiary, case_type="I-485",
        linked_i130_case_id=i130["id"],
    )
    i485 = file_case(i485, petitioner)
    return {
        "petitioner": petitioner,
        "beneficiary": beneficiary,
        "i130": i130,
        "i485": i485,
        "bulletins": {"FINAL_ACTION": fa, "DATES_FOR_FILING": dff},
        "pin_clock_iso": pin_clock_iso,
        "bulletin_month": bulletin_month,
    }


__all__ = [
    # Clock
    "advance_clock_to",
    "get_clock_now",
    "server_now_dt",
    "server_offset_iso",
    # CaseTypeConfig
    "upsert_case_type_config",
    "seed_all_case_type_configs",
    # Petitioner / Beneficiary
    "create_petitioner",
    "create_beneficiary",
    "setup_petitioner_and_beneficiary",
    # Case ops
    "create_case",
    "file_case",
    "withdraw_case",
    "re_get_case",
    "ready_for_decision",
    "decide_case",
    "refresh_priority_date",
    # Biometrics
    "schedule_biometrics",
    "complete_biometrics",
    "reschedule_biometrics",
    "no_show_biometrics",
    # RFE
    "issue_rfe",
    "respond_rfe",
    # Interview
    "schedule_interview",
    "complete_interview",
    # Bulletin
    "publish_bulletin",
    "set_chart_in_effect",
    # World / compositions
    "seed_world",
    "setup_filed_case",
    "setup_biometrics_completed",
    "setup_rfe_responded",
    "setup_interview_scheduled",
    "setup_ready_for_decision_i485",
    "setup_ready_for_decision_i130",
    "setup_approved_i130_with_dependent_i485",
    "setup_i130_in_rfe_issued",
    "setup_i130_in_rfe_issued_with_dependent_i485_filed",
    "setup_dependent_i485_in_interview_scheduled",
    "setup_i130_ready_with_dependent_i485_interview_scheduled",
    "setup_i130_ready_with_real_dependent_i485",
    "setup_priority_date_inheritance_world",
]
