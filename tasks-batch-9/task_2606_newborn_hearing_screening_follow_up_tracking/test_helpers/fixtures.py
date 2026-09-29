"""Composite scenario builders.

Each builder drives the API exactly as a client would — no state is written by
any other route — so a scenario is reproducible from an empty database with the
logical clock at its starting value.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import clock, factories
from .api_client import EhdiApiClient
from .constants import CLOCK_START
from .test_users import (
    OPERATOR_ONE_ID,
    OPERATOR_TWO_ID,
    PROGRAM_ADMIN_ID,
    PROGRAM_AUDITOR_ID,
    make_audiologist_headers,
    make_ei_coordinator_headers,
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)
from .types import Headers, JsonDict

ADMIN: Headers = make_program_admin_headers(PROGRAM_ADMIN_ID)
AUDITOR: Headers = make_program_auditor_headers(PROGRAM_AUDITOR_ID)
OPERATOR_ONE_AUDITOR: Headers = make_program_auditor_headers(OPERATOR_ONE_ID)
OPERATOR_ONE_ADMIN: Headers = make_program_admin_headers(OPERATOR_ONE_ID)
OPERATOR_TWO_ADMIN: Headers = make_program_admin_headers(OPERATOR_TWO_ID)


# ---------------------------------------------------------------------------
# primitive steps
# ---------------------------------------------------------------------------


def set_clock(client: EhdiApiClient, to_iso8601: str) -> JsonDict:
    """Move the logical clock and return the reported state."""
    return validate_success(client.set_clock(to_iso8601, headers=ADMIN), 200)


def create_facility(
    client: EhdiApiClient,
    name: str,
    facility_type: str,
    region_code: str = "R1",
    navigation_budget_units_total: Optional[int] = None,
) -> JsonDict:
    payload = factories.facility_payload(
        name=name,
        facility_type=facility_type,
        region_code=region_code,
        navigation_budget_units_total=navigation_budget_units_total,
    )
    return validate_success(client.create_facility(payload, headers=ADMIN), 201)


def create_provider(
    client: EhdiApiClient,
    facility_id: str,
    provider_type: str,
    full_name: str,
    region_code: str = "R1",
    languages: Optional[List[str]] = None,
    credential_status: Optional[str] = None,
    max_open_tasks: Optional[int] = None,
) -> JsonDict:
    payload = factories.provider_payload(
        facility_id=facility_id,
        provider_type=provider_type,
        full_name=full_name,
        region_code=region_code,
        languages=languages,
        credential_status=credential_status,
        max_open_tasks=max_open_tasks,
    )
    return validate_success(client.create_provider(payload, headers=ADMIN), 201)


def create_infant(client: EhdiApiClient, birth_facility_id: str, **kwargs: Any) -> JsonDict:
    payload = factories.infant_payload(birth_facility_id=birth_facility_id, **kwargs)
    return validate_success(client.create_infant(payload, headers=ADMIN), 201)


def read_infant(client: EhdiApiClient, infant_id: str) -> JsonDict:
    return validate_success(client.get_infant(infant_id, headers=ADMIN), 200)


def read_facility(client: EhdiApiClient, facility_id: str) -> JsonDict:
    return validate_success(client.get_facility(facility_id, headers=ADMIN), 200)


def read_provider(client: EhdiApiClient, provider_id: str) -> JsonDict:
    return validate_success(client.get_provider(provider_id, headers=ADMIN), 200)


def read_slot(client: EhdiApiClient, slot_id: str) -> JsonDict:
    return validate_success(client.get_slot(slot_id, headers=ADMIN), 200)


def read_episode(client: EhdiApiClient, episode_id: str) -> JsonDict:
    return validate_success(client.get_episode(episode_id, headers=ADMIN), 200)


def read_appointment(client: EhdiApiClient, appointment_id: str) -> JsonDict:
    return validate_success(client.get_appointment(appointment_id, headers=ADMIN), 200)


def read_task(client: EhdiApiClient, task_id: str) -> JsonDict:
    return validate_success(client.get_task(task_id, headers=ADMIN), 200)


def read_evaluation(client: EhdiApiClient, evaluation_id: str) -> JsonDict:
    return validate_success(client.get_evaluation(evaluation_id, headers=ADMIN), 200)


def read_referral(client: EhdiApiClient, referral_id: str) -> JsonDict:
    return validate_success(client.get_referral(referral_id, headers=ADMIN), 200)


def read_period(client: EhdiApiClient, period_id: str) -> JsonDict:
    return validate_success(client.get_period(period_id, headers=ADMIN), 200)


def read_report(client: EhdiApiClient, report_id: str) -> JsonDict:
    return validate_success(client.get_report(report_id, headers=ADMIN), 200)


def read_timeliness(client: EhdiApiClient, infant_id: str) -> JsonDict:
    return validate_success(client.get_timeliness(infant_id, headers=ADMIN), 200)


def read_performance(client: EhdiApiClient, facility_id: str) -> JsonDict:
    return validate_success(client.get_facility_performance(facility_id, headers=ADMIN), 200)


def infant_version(client: EhdiApiClient, infant_id: str) -> int:
    return read_infant(client, infant_id)["version"]


def facility_version(client: EhdiApiClient, facility_id: str) -> int:
    return read_facility(client, facility_id)["version"]


def rows(response) -> List[JsonDict]:
    """Return the data array of a list response."""
    return get_success_data(response)


def list_rows(response) -> List[JsonDict]:
    body = response.json()
    assert response.status_code == 200, body
    return body["data"]


def episodes_of(client: EhdiApiClient, infant_id: str) -> List[JsonDict]:
    response = client.list_episodes(headers=ADMIN, limit=100, infant_id=infant_id)
    return list_rows(response)


def tasks_of(client: EhdiApiClient, infant_id: str) -> List[JsonDict]:
    response = client.list_tasks(headers=ADMIN, limit=100, infant_id=infant_id)
    return list_rows(response)


def referrals_of(client: EhdiApiClient, infant_id: str) -> List[JsonDict]:
    response = client.list_referrals(headers=ADMIN, limit=100, infant_id=infant_id)
    return list_rows(response)


def encounters_of(client: EhdiApiClient, infant_id: str) -> List[JsonDict]:
    response = client.list_encounters(headers=ADMIN, limit=100, infant_id=infant_id)
    return list_rows(response)


def risk_entries_of(client: EhdiApiClient, infant_id: str, **filters: Any) -> List[JsonDict]:
    response = client.list_risk_factor_entries(
        infant_id, headers=ADMIN, limit=100, **filters
    )
    return list_rows(response)


def active_episode(client: EhdiApiClient, infant_id: str) -> JsonDict:
    """The infant's single open episode, newest first by creation order."""
    open_states = ("PENDING_SCHEDULING", "SCHEDULED", "ESCALATED_DIAGNOSTIC")
    candidates = [e for e in episodes_of(client, infant_id) if e["status"] in open_states]
    assert candidates, "infant {0} has no open episode".format(infant_id)
    return candidates[-1]


# ---------------------------------------------------------------------------
# the standard cast of facilities and providers
# ---------------------------------------------------------------------------


@dataclass
class Registry:
    """A birth hospital, an audiology clinic, an EI program, and their staff."""

    birth_hospital: JsonDict
    clinic: JsonDict
    ei_program: JsonDict
    screener: JsonDict
    audiologist: JsonDict
    second_audiologist: JsonDict
    navigator: JsonDict
    coordinator: JsonDict

    # --- convenient identifiers ---
    @property
    def bh_id(self) -> str:
        return self.birth_hospital["id"]

    @property
    def ac_id(self) -> str:
        return self.clinic["id"]

    @property
    def ei_id(self) -> str:
        return self.ei_program["id"]

    @property
    def s1_id(self) -> str:
        return self.screener["id"]

    @property
    def a1_id(self) -> str:
        return self.audiologist["id"]

    @property
    def a2_id(self) -> str:
        return self.second_audiologist["id"]

    @property
    def n1_id(self) -> str:
        return self.navigator["id"]

    @property
    def c1_id(self) -> str:
        return self.coordinator["id"]

    # --- identity headers ---
    @property
    def bh_admin(self) -> Headers:
        return make_facility_admin_headers(self.bh_id)

    @property
    def ac_admin(self) -> Headers:
        return make_facility_admin_headers(self.ac_id)

    @property
    def ei_admin(self) -> Headers:
        return make_facility_admin_headers(self.ei_id)

    @property
    def s1(self) -> Headers:
        return make_facility_screener_headers(self.s1_id)

    @property
    def a1(self) -> Headers:
        return make_audiologist_headers(self.a1_id)

    @property
    def a2(self) -> Headers:
        return make_audiologist_headers(self.a2_id)

    @property
    def n1(self) -> Headers:
        return make_navigator_headers(self.n1_id)

    @property
    def c1(self) -> Headers:
        return make_ei_coordinator_headers(self.c1_id)


def base_registry(
    client: EhdiApiClient,
    region_code: str = "R1",
    birth_budget: Optional[int] = None,
    navigator_languages: Optional[List[str]] = None,
    navigator_max_open_tasks: Optional[int] = None,
) -> Registry:
    """Register the facilities and providers most scenarios need."""
    birth_hospital = create_facility(
        client,
        "Riverside Birth Hospital",
        "BIRTH_HOSPITAL",
        region_code,
        navigation_budget_units_total=birth_budget,
    )
    clinic = create_facility(client, "Lakeside Audiology Clinic", "AUDIOLOGY_CLINIC", region_code)
    ei_program = create_facility(client, "EI North", "EI_PROGRAM", region_code)
    screener = create_provider(
        client, birth_hospital["id"], "SCREENER", "Sam Reyes", region_code
    )
    audiologist = create_provider(
        client, clinic["id"], "AUDIOLOGIST", "Ada Lin", region_code
    )
    second_audiologist = create_provider(
        client, clinic["id"], "AUDIOLOGIST", "Ben Marsh", region_code
    )
    navigator = create_provider(
        client,
        birth_hospital["id"],
        "NAVIGATOR",
        "Nia Ortiz",
        region_code,
        languages=navigator_languages,
        max_open_tasks=navigator_max_open_tasks,
    )
    coordinator = create_provider(
        client, ei_program["id"], "EI_COORDINATOR", "Cleo Park", region_code
    )
    return Registry(
        birth_hospital=birth_hospital,
        clinic=clinic,
        ei_program=ei_program,
        screener=screener,
        audiologist=audiologist,
        second_audiologist=second_audiologist,
        navigator=navigator,
        coordinator=coordinator,
    )


# ---------------------------------------------------------------------------
# clinical flow
# ---------------------------------------------------------------------------


def publish_slot(
    client: EhdiApiClient,
    registry: Registry,
    starts_at: str,
    ends_at: str,
    slot_type: str = "RESCREEN",
    total_capacity: Optional[int] = None,
    provider_id: Optional[str] = None,
) -> JsonDict:
    payload = factories.slot_payload(
        facility_id=registry.ac_id,
        provider_id=provider_id or registry.a1_id,
        starts_at=starts_at,
        ends_at=ends_at,
        slot_type=slot_type,
        total_capacity=total_capacity,
    )
    return validate_success(client.create_slot(payload, headers=ADMIN), 201)


def record_encounter(
    client: EhdiApiClient,
    registry: Registry,
    infant_id: str,
    performed_at: str,
    encounter_type: str = "BIRTH_ADMISSION",
    left_ear_result: str = "PASS",
    right_ear_result: str = "PASS",
    facility_id: Optional[str] = None,
    performed_by_provider_id: Optional[str] = None,
    headers: Optional[Headers] = None,
    **kwargs: Any
) -> JsonDict:
    payload = factories.encounter_payload(
        infant_id=infant_id,
        facility_id=facility_id or registry.bh_id,
        performed_by_provider_id=performed_by_provider_id or registry.s1_id,
        performed_at=performed_at,
        encounter_type=encounter_type,
        left_ear_result=left_ear_result,
        right_ear_result=right_ear_result,
        **kwargs
    )
    return validate_success(
        client.create_encounter(payload, headers=headers or registry.s1), 201
    )


def refer_at_birth(
    client: EhdiApiClient,
    registry: Registry,
    infant_id: str,
    performed_at: str = CLOCK_START,
) -> Dict[str, JsonDict]:
    """Record a referring birth-admission screen and return the resulting rows."""
    encounter = record_encounter(
        client,
        registry,
        infant_id,
        performed_at,
        encounter_type="BIRTH_ADMISSION",
        left_ear_result="REFER",
        right_ear_result="REFER",
    )
    infant = read_infant(client, infant_id)
    return {
        "encounter": encounter,
        "infant": infant,
        "episode": active_episode(client, infant_id),
    }


def open_episode(
    client: EhdiApiClient,
    infant_id: str,
    episode_type: str,
    expected_infant_version: Optional[int] = None,
    supersedes_episode_id: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    version = (
        expected_infant_version
        if expected_infant_version is not None
        else infant_version(client, infant_id)
    )
    payload = factories.episode_payload(
        infant_id=infant_id,
        episode_type=episode_type,
        expected_infant_version=version,
        supersedes_episode_id=supersedes_episode_id,
    )
    return validate_success(client.create_episode(payload, headers=headers or ADMIN), 201)


def open_diagnostic_episode(client: EhdiApiClient, infant_id: str) -> JsonDict:
    """Open a diagnostic episode superseding whichever episode is open."""
    current = active_episode(client, infant_id)
    return open_episode(
        client,
        infant_id,
        "DIAGNOSTIC",
        supersedes_episode_id=current["id"],
    )


def book(
    client: EhdiApiClient,
    episode_id: str,
    slot_id: str,
    interpreter_needed: Optional[bool] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = factories.appointment_payload(
        episode_id=episode_id, slot_id=slot_id, interpreter_needed=interpreter_needed
    )
    return validate_success(client.create_appointment(payload, headers=headers or ADMIN), 201)


def close_appointment(
    client: EhdiApiClient,
    appointment_id: str,
    disposition: str,
    reason: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload: JsonDict = {"disposition": disposition}
    if reason is not None:
        payload["reason"] = reason
    return validate_success(
        client.close_appointment(appointment_id, payload, headers=headers or ADMIN), 200
    )


def register_risk_factor(
    client: EhdiApiClient,
    infant_id: str,
    risk_factor_code: str,
    identified_at: str = CLOCK_START,
    source: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = factories.risk_factor_payload(
        infant_id=infant_id,
        risk_factor_code=risk_factor_code,
        identified_at=identified_at,
        source=source,
    )
    return validate_success(
        client.create_risk_factor_entry(payload, headers=headers or ADMIN), 201
    )


# ---------------------------------------------------------------------------
# diagnostic evaluation chain
# ---------------------------------------------------------------------------


def draft_evaluation(
    client: EhdiApiClient,
    registry: Registry,
    infant_id: str,
    episode_id: str,
    evaluation_datetime: str = CLOCK_START,
    method: str = "DIAGNOSTIC_ABR",
    performed_by_provider_id: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = factories.evaluation_payload(
        infant_id=infant_id,
        episode_id=episode_id,
        facility_id=registry.ac_id,
        performed_by_provider_id=performed_by_provider_id or registry.a1_id,
        evaluation_datetime=evaluation_datetime,
        method=method,
    )
    return validate_success(client.create_evaluation(payload, headers=headers or registry.a1), 201)


def submit_evaluation(
    client: EhdiApiClient,
    registry: Registry,
    evaluation_id: str,
    left_ear_threshold_db: int,
    right_ear_threshold_db: int,
    outcome: str,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = factories.submit_payload(
        left_ear_threshold_db, right_ear_threshold_db, outcome
    )
    return validate_success(
        client.submit_evaluation(evaluation_id, payload, headers=headers or registry.a1), 200
    )


def attest_evaluation(
    client: EhdiApiClient,
    registry: Registry,
    evaluation_id: str,
    decision: str = "ACCEPT",
    note: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload: JsonDict = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return validate_success(
        client.attest_evaluation(evaluation_id, payload, headers=headers or registry.a2), 200
    )


def finalize_evaluation(
    client: EhdiApiClient,
    registry: Registry,
    evaluation_id: str,
    headers: Optional[Headers] = None,
) -> JsonDict:
    return validate_success(
        client.finalize_evaluation(evaluation_id, {}, headers=headers or registry.a1), 200
    )


def diagnostic_track(
    client: EhdiApiClient, registry: Registry, infant_id: str, performed_at: str = CLOCK_START
) -> Dict[str, JsonDict]:
    """Refer the infant at birth, then open the diagnostic episode."""
    referred = refer_at_birth(client, registry, infant_id, performed_at)
    diagnostic = open_diagnostic_episode(client, infant_id)
    return {
        "encounter": referred["encounter"],
        "rescreen_episode": referred["episode"],
        "episode": diagnostic,
    }


def attested_evaluation(
    client: EhdiApiClient,
    registry: Registry,
    infant_id: str,
    episode_id: str,
    left_ear_threshold_db: int,
    right_ear_threshold_db: int,
    outcome: str,
    evaluation_datetime: str = CLOCK_START,
) -> JsonDict:
    """Create, submit and attest an evaluation, leaving it ready to finalize."""
    evaluation = draft_evaluation(
        client, registry, infant_id, episode_id, evaluation_datetime
    )
    submit_evaluation(
        client,
        registry,
        evaluation["id"],
        left_ear_threshold_db,
        right_ear_threshold_db,
        outcome,
    )
    return attest_evaluation(client, registry, evaluation["id"])


# ---------------------------------------------------------------------------
# navigation tasks
# ---------------------------------------------------------------------------


def create_task(
    client: EhdiApiClient,
    infant_id: str,
    task_type: str = "OUTREACH_CALL",
    headers: Optional[Headers] = None,
    **kwargs: Any
) -> JsonDict:
    payload = factories.task_payload(infant_id=infant_id, task_type=task_type, **kwargs)
    return validate_success(client.create_task(payload, headers=headers or ADMIN), 201)


def assign_task(
    client: EhdiApiClient,
    task_id: str,
    assigned_provider_id: Optional[str] = None,
    auto_assign: Optional[bool] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload: JsonDict = {}
    if assigned_provider_id is not None:
        payload["assigned_provider_id"] = assigned_provider_id
    if auto_assign is not None:
        payload["auto_assign"] = auto_assign
    return validate_success(client.assign_task(task_id, payload, headers=headers or ADMIN), 200)


def close_task(
    client: EhdiApiClient,
    task_id: str,
    disposition: str = "COMPLETED",
    outcome: Optional[str] = None,
    contacted_language: Optional[str] = None,
    reason: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload: JsonDict = {"disposition": disposition}
    if outcome is not None:
        payload["outcome"] = outcome
    if contacted_language is not None:
        payload["contacted_language"] = contacted_language
    if reason is not None:
        payload["reason"] = reason
    return validate_success(client.close_task(task_id, payload, headers=headers or ADMIN), 200)


# ---------------------------------------------------------------------------
# compliance and reporting
# ---------------------------------------------------------------------------


def adjust_penalty(
    client: EhdiApiClient,
    facility_id: str,
    points_delta: int,
    reason: str = "manual compliance adjustment",
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = {"points_delta": points_delta, "reason": reason}
    return validate_success(
        client.create_penalty_adjustment(facility_id, payload, headers=headers or ADMIN), 200
    )


def suspend_facility(client: EhdiApiClient, facility_id: str) -> JsonDict:
    """Drive a facility to the SUSPENDED posture through a manual adjustment."""
    return adjust_penalty(client, facility_id, 18, "compliance escalation")


def open_period(
    client: EhdiApiClient,
    period_start: str,
    period_end: str,
    submission_due_datetime: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = factories.period_payload(
        period_start=period_start,
        period_end=period_end,
        submission_due_datetime=submission_due_datetime or period_end,
    )
    return validate_success(client.create_period(payload, headers=headers or ADMIN), 201)


def august_period(client: EhdiApiClient) -> JsonDict:
    """The month that begins at the clock's starting instant."""
    return open_period(
        client,
        CLOCK_START,
        "2026-09-01T00:00:00Z",
        "2026-09-15T00:00:00Z",
    )


def file_report(
    client: EhdiApiClient,
    facility_id: str,
    reporting_period_id: str,
    attested_screened_count: int = 0,
    attested_refer_count: int = 0,
    expected_facility_version: Optional[int] = None,
    supersedes_report_id: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    version = (
        expected_facility_version
        if expected_facility_version is not None
        else facility_version(client, facility_id)
    )
    payload = factories.report_payload(
        facility_id=facility_id,
        reporting_period_id=reporting_period_id,
        attested_screened_count=attested_screened_count,
        attested_refer_count=attested_refer_count,
        expected_facility_version=version,
        supersedes_report_id=supersedes_report_id,
    )
    return validate_success(
        client.create_report(
            payload, headers=headers or make_facility_admin_headers(facility_id)
        ),
        201,
    )


def review_report(
    client: EhdiApiClient,
    report_id: str,
    decision: str = "ACCEPT",
    note: Optional[str] = None,
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload: JsonDict = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return validate_success(
        client.review_report(report_id, payload, headers=headers or OPERATOR_ONE_AUDITOR), 200
    )


def close_period(
    client: EhdiApiClient, period_id: str, headers: Optional[Headers] = None
) -> JsonDict:
    return validate_success(client.close_period(period_id, {}, headers=headers or ADMIN), 200)


def waive_penalty(
    client: EhdiApiClient,
    report_id: str,
    waiver_reason: str = "documented data outage",
    headers: Optional[Headers] = None,
) -> JsonDict:
    payload = {"waiver_reason": waiver_reason}
    return validate_success(
        client.waive_report_penalty(report_id, payload, headers=headers or OPERATOR_TWO_ADMIN),
        200,
    )


def reports_of(client: EhdiApiClient, **filters: Any) -> List[JsonDict]:
    response = client.list_reports(headers=ADMIN, limit=100, **filters)
    return list_rows(response)


def report_of_record(client: EhdiApiClient, facility_id: str, period_id: str) -> JsonDict:
    """The facility's non-superseded report for a period, latest one wins."""
    candidates = [
        row
        for row in reports_of(client, facility_id=facility_id, reporting_period_id=period_id)
        if row["status"] != "SUPERSEDED"
    ]
    assert candidates, "no report of record for facility {0}".format(facility_id)
    return candidates[-1]
