"""Composite setup helpers.

Every helper builds its state exclusively through the PRD's declared endpoints,
starting from an empty database — the harness relaunches the API before each
individual test, so nothing is ever carried across.

Two conventions matter throughout:

* Identity threading — a `CHW` acts under the id of the worker row it owns and
  a `ResourcePartner` under the id of its organization row, so every helper
  that creates one of those rows also returns the matching headers.
* The records-hold write gate sits at rung 4 and pre-empts almost everything
  below it, so no helper here places a hold as an incidental side effect; a
  test that wants one calls `place_records_hold` deliberately, and last.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_instant
from .factories import (
    create_charge_line_payload,
    create_criterion_payload,
    create_encounter_payload,
    create_escalation_payload,
    create_goal_payload,
    create_grant_award_payload,
    create_home_visit_payload,
    create_instrument_payload,
    create_offering_payload,
    create_patient_payload,
    create_payer_claim_payload,
    create_referral_payload,
    create_resource_org_payload,
    create_screening_payload,
    create_worker_payload,
)
from .test_users import (
    BILLING_SPECIALIST,
    PROGRAM_ADMIN,
    SUPERVISOR,
    make_chw_headers,
    make_partner_headers,
)

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ─── Time helpers ──────────────────────────────────────────────────────────

def iso_utc(dt: datetime) -> str:
    """Render an aware datetime as an ISO 8601 UTC instant."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(instant: str, **delta: Any) -> str:
    """Shift an instant by any timedelta keyword (hours, days, seconds...)."""
    return iso_utc(parse_instant(instant) + timedelta(**delta))


# ─── Tier 0: single-call primitives ────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Drive the program's logical clock (ProgramAdmin only)."""
    return get_success_data(api_client.set_clock(to_iso8601, PROGRAM_ADMIN))


def register_worker(employee_code: str = "W-001", **overrides: Any) -> dict:
    payload = create_worker_payload(employee_code=employee_code, **overrides)
    return get_success_data(api_client.create_worker(payload, PROGRAM_ADMIN))


def add_patient(chw_headers: dict, **overrides: Any) -> dict:
    payload = create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(payload, chw_headers))


def patch_patient(patient_id: str, **payload: Any) -> dict:
    return get_success_data(api_client.update_patient(patient_id, payload, SUPERVISOR))


def enroll_patient(patient_id: str) -> dict:
    return patch_patient(patient_id, enrollment_action="ENROLL")


def disenroll_patient(patient_id: str) -> dict:
    return patch_patient(patient_id, enrollment_action="DISENROLL")


def reenroll_patient(patient_id: str) -> dict:
    return patch_patient(patient_id, enrollment_action="REENROLL")


def place_records_hold(patient_id: str, reason: str = "Consent withdrawn") -> dict:
    """Place the rung-4 write gate. Call this LAST — it masks nearly every
    other error a subsequent request could raise."""
    return get_success_data(
        api_client.records_hold(
            patient_id, {"action": "PLACE", "reason": reason}, SUPERVISOR
        )
    )


def release_records_hold(patient_id: str) -> dict:
    return get_success_data(
        api_client.records_hold(patient_id, {"action": "RELEASE"}, SUPERVISOR)
    )


def read_patient(patient_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_patient(patient_id, headers or PROGRAM_ADMIN)
    )


def patient_version(patient_id: str) -> int:
    return read_patient(patient_id)["version"]


def read_offering(offering_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_offering(offering_id, headers or PROGRAM_ADMIN)
    )


def offering_version(offering_id: str) -> int:
    return read_offering(offering_id)["version"]


def read_referral(referral_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_referral(referral_id, headers or PROGRAM_ADMIN)
    )


def read_home_visit(visit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_home_visit(visit_id, headers or PROGRAM_ADMIN)
    )


def read_goal(goal_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_goal(goal_id, headers or PROGRAM_ADMIN))


def read_encounter(encounter_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_encounter(encounter_id, headers or PROGRAM_ADMIN)
    )


def read_screening(screening_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_screening(screening_id, headers or PROGRAM_ADMIN)
    )


def read_claim(claim_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_payer_claim(claim_id, headers or PROGRAM_ADMIN)
    )


def read_award(award_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_grant_award(award_id, headers or PROGRAM_ADMIN)
    )


def award_version(award_id: str) -> int:
    return read_award(award_id)["version"]


def read_charge_line(line_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_charge_line(line_id, headers or PROGRAM_ADMIN)
    )


def read_escalation(escalation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_escalation(escalation_id, headers or PROGRAM_ADMIN)
    )


def run_sweep(sweep_type: str) -> dict:
    return get_success_data(api_client.run_sweep(sweep_type, PROGRAM_ADMIN))


def program_report(service_month: str, denominator_basis: str,
                   headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.program_summary(
            headers or SUPERVISOR,
            params={
                "service_month": service_month,
                "denominator_basis": denominator_basis,
            },
        )
    )


# ─── Tier 1: worker + patient scaffolding ─────────────────────────────────

def program_with_patient(
    clock: Optional[str] = DEFAULT_CLOCK,
    employee_code: str = "W-001",
    enroll: bool = True,
    **patient_overrides: Any,
) -> Tuple[dict, dict, dict]:
    """One worker and one patient, enrolled by default.

    Returns `(worker, patient, chw_headers)` where `chw_headers` already carries
    the worker's own id, which is what every ownership check compares against.
    """
    if clock is not None:
        set_clock(clock)
    worker = register_worker(employee_code=employee_code)
    chw_headers = make_chw_headers(worker["id"])
    patient = add_patient(chw_headers, **patient_overrides)
    if enroll:
        patient = enroll_patient(patient["id"])
    return worker, patient, chw_headers


def second_worker(employee_code: str = "W-002", full_name: str = "Ben Cole") -> Tuple[dict, dict]:
    worker = register_worker(employee_code=employee_code, full_name=full_name)
    return worker, make_chw_headers(worker["id"])


# ─── Tier 1: screening instruments and screenings ─────────────────────────

def published_instrument(**overrides: Any) -> dict:
    """A screening instrument revision walked from DRAFT to PUBLISHED."""
    payload = create_instrument_payload(**overrides)
    instrument = get_success_data(api_client.create_instrument(payload, PROGRAM_ADMIN))
    return get_success_data(
        api_client.publish_instrument(instrument["id"], PROGRAM_ADMIN)
    )


def draft_instrument(**overrides: Any) -> dict:
    payload = create_instrument_payload(**overrides)
    return get_success_data(api_client.create_instrument(payload, PROGRAM_ADMIN))


def administer_screening(
    chw_headers: dict,
    patient_id: str,
    instrument_id: str,
    domain_scores: Optional[dict] = None,
    expected_patient_version: Optional[int] = None,
) -> dict:
    """Administer a screening, reading the patient's live version when the
    caller does not pin one explicitly."""
    version = (
        expected_patient_version
        if expected_patient_version is not None
        else patient_version(patient_id)
    )
    payload = create_screening_payload(patient_id, instrument_id, version)
    if domain_scores is not None:
        payload["domain_scores"] = domain_scores
    return get_success_data(api_client.administer_screening(payload, chw_headers))


# ─── Tier 1: resource network ─────────────────────────────────────────────

def register_org(**overrides: Any) -> Tuple[dict, dict]:
    """Register a resource organization. Returns `(org, partner_headers)`."""
    payload = create_resource_org_payload(**overrides)
    org = get_success_data(api_client.create_resource_org(payload, PROGRAM_ADMIN))
    return org, make_partner_headers(org["id"])


def create_offering(resource_org_id: str, **overrides: Any) -> dict:
    payload = create_offering_payload(resource_org_id, **overrides)
    return get_success_data(api_client.create_offering(payload, PROGRAM_ADMIN))


def org_with_offering(
    capacity_total: int = 5,
    org_overrides: Optional[dict] = None,
    **offering_overrides: Any,
) -> Tuple[dict, dict, dict]:
    """One ACTIVE organization plus one offering. Returns
    `(org, offering, partner_headers)`."""
    org, partner_headers = register_org(**(org_overrides or {}))
    offering = create_offering(
        org["id"], capacity_total=capacity_total, **offering_overrides
    )
    return org, offering, partner_headers


def attach_criterion(offering_id: str, criterion_type: str, **fields: Any) -> dict:
    payload = create_criterion_payload(criterion_type, **fields)
    return get_success_data(
        api_client.create_criterion(offering_id, payload, PROGRAM_ADMIN)
    )


def suspend_org(org_id: str) -> dict:
    return get_success_data(
        api_client.suspend_resource_org(org_id, {"action": "SUSPEND"}, PROGRAM_ADMIN)
    )


def reinstate_org(org_id: str) -> dict:
    return get_success_data(
        api_client.suspend_resource_org(org_id, {"action": "REINSTATE"}, PROGRAM_ADMIN)
    )


# ─── Tier 2: the referral loop ────────────────────────────────────────────

def send_referral(
    chw_headers: dict,
    patient_id: str,
    offering_id: str,
    worker_id: str,
    units_requested: int = 1,
    urgency: str = "ROUTINE",
    expected_offering_version: Optional[int] = None,
) -> dict:
    """Send a referral, reading the offering's live version unless pinned."""
    version = (
        expected_offering_version
        if expected_offering_version is not None
        else offering_version(offering_id)
    )
    payload = create_referral_payload(
        patient_id, offering_id, worker_id, version,
        units_requested=units_requested, urgency=urgency,
    )
    return get_success_data(api_client.create_referral(payload, chw_headers))


def respond_to_referral(
    partner_headers: dict,
    referral_id: str,
    decision: str,
    decline_reason: Optional[str] = None,
) -> dict:
    payload: Dict[str, Any] = {"decision": decision}
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        api_client.respond_referral(referral_id, payload, partner_headers)
    )


def accepted_referral(
    chw_headers: dict, partner_headers: dict, patient_id: str, offering_id: str,
    worker_id: str, units_requested: int = 1, urgency: str = "ROUTINE",
) -> dict:
    referral = send_referral(
        chw_headers, patient_id, offering_id, worker_id,
        units_requested=units_requested, urgency=urgency,
    )
    return respond_to_referral(partner_headers, referral["id"], "ACCEPTED")


def declined_referral(
    chw_headers: dict, partner_headers: dict, patient_id: str, offering_id: str,
    worker_id: str, units_requested: int = 1, urgency: str = "ROUTINE",
    decline_reason: str = "Out of stock",
) -> dict:
    referral = send_referral(
        chw_headers, patient_id, offering_id, worker_id,
        units_requested=units_requested, urgency=urgency,
    )
    return respond_to_referral(
        partner_headers, referral["id"], "DECLINED", decline_reason
    )


def delivered_referral(
    chw_headers: dict, partner_headers: dict, patient_id: str, offering_id: str,
    worker_id: str, units_requested: int = 1,
) -> dict:
    referral = accepted_referral(
        chw_headers, partner_headers, patient_id, offering_id, worker_id,
        units_requested=units_requested,
    )
    return get_success_data(
        api_client.deliver_referral(referral["id"], partner_headers)
    )


def close_referral(chw_headers: dict, referral_id: str,
                   outcome_note: str = "Loop closed") -> dict:
    return get_success_data(
        api_client.close_referral(
            referral_id, {"outcome_note": outcome_note}, chw_headers
        )
    )


def reroute_referral(
    chw_headers: dict, referral_id: str, offering_id: str,
    units_requested: int = 1, urgency: str = "ROUTINE",
    expected_offering_version: Optional[int] = None,
) -> dict:
    version = (
        expected_offering_version
        if expected_offering_version is not None
        else offering_version(offering_id)
    )
    payload = {
        "offering_id": offering_id,
        "urgency": urgency,
        "units_requested": units_requested,
        "expected_offering_version": version,
    }
    return get_success_data(
        api_client.reroute_referral(referral_id, payload, chw_headers)
    )


def referral_chain_at_limit(
    chw_headers: dict, partner_headers: dict, patient_id: str, worker_id: str,
    offerings: List[dict],
) -> List[dict]:
    """Walk a chain through two successful re-routes so `reroute_count` is 2
    chain-wide. `offerings` supplies the root offering plus two alternates.
    Returns the three referral rows in chain order."""
    root = send_referral(
        chw_headers, patient_id, offerings[0]["id"], worker_id
    )
    respond_to_referral(partner_headers, root["id"], "DECLINED", "Out of stock")
    second = reroute_referral(chw_headers, root["id"], offerings[1]["id"])
    respond_to_referral(partner_headers, second["id"], "DECLINED", "Out of stock")
    third = reroute_referral(chw_headers, second["id"], offerings[2]["id"])
    respond_to_referral(partner_headers, third["id"], "DECLINED", "Out of stock")
    return [root, second, third]


# ─── Tier 3: home visits ──────────────────────────────────────────────────

def schedule_visit(
    chw_headers: dict, patient_id: str, assigned_chw_id: str,
    scheduled_start: str, scheduled_end: str, **overrides: Any,
) -> dict:
    payload = create_home_visit_payload(
        patient_id, assigned_chw_id, scheduled_start, scheduled_end, **overrides
    )
    return get_success_data(api_client.create_home_visit(payload, chw_headers))


def completed_visit(
    chw_headers: dict, patient_id: str, assigned_chw_id: str,
    scheduled_start: str = "2026-06-02T09:00:00Z",
    scheduled_end: str = "2026-06-02T10:00:00Z",
    en_route_at: str = "2026-06-02T09:00:00Z",
    completed_at: str = "2026-06-02T10:00:00Z",
    **overrides: Any,
) -> dict:
    """Schedule → en route → complete, driving the clock to each instant so
    `completed_at` lands exactly where the caller asked."""
    visit = schedule_visit(
        chw_headers, patient_id, assigned_chw_id,
        scheduled_start, scheduled_end, **overrides,
    )
    set_clock(en_route_at)
    get_success_data(api_client.en_route_home_visit(visit["id"], chw_headers))
    set_clock(completed_at)
    return get_success_data(api_client.complete_home_visit(visit["id"], chw_headers))


def attest_visit(chw_headers: dict, visit_id: str,
                 visit_note: str = "Visit documented") -> dict:
    return get_success_data(
        api_client.attest_home_visit(visit_id, {"visit_note": visit_note}, chw_headers)
    )


def attested_visit(
    chw_headers: dict, patient_id: str, assigned_chw_id: str,
    attested_at: str = "2026-06-02T11:00:00Z",
    visit_note: str = "Visit documented",
    **visit_overrides: Any,
) -> dict:
    """A visit driven all the way to scheduling COMPLETED and documentation
    ATTESTED, with `attested_at` stamped at the requested instant."""
    visit = completed_visit(
        chw_headers, patient_id, assigned_chw_id, **visit_overrides
    )
    set_clock(attested_at)
    return attest_visit(chw_headers, visit["id"], visit_note)


def revise_documentation(headers: dict, visit_id: str, action: str,
                         visit_note: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"action": action}
    if visit_note is not None:
        payload["visit_note"] = visit_note
    return get_success_data(
        api_client.revise_documentation(visit_id, payload, headers)
    )


# ─── Tier 3: care-plan goals ──────────────────────────────────────────────

def create_goal(chw_headers: dict, patient_id: str, **overrides: Any) -> dict:
    payload = create_goal_payload(patient_id, **overrides)
    return get_success_data(api_client.create_goal(payload, chw_headers))


def record_progress(chw_headers: dict, goal_id: str, current_value: Any) -> dict:
    return get_success_data(
        api_client.record_goal_progress(
            goal_id, {"current_value": current_value}, chw_headers
        )
    )


def close_goal(headers: dict, goal_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.close_goal(goal_id, {"outcome": outcome}, headers)
    )


def reopen_goal(headers: dict, goal_id: str) -> dict:
    return get_success_data(api_client.reopen_goal(goal_id, headers))


# ─── Tier 3: encounters ───────────────────────────────────────────────────

def create_encounter(chw_headers: dict, patient_id: str, chw_id: str,
                     encounter_date: str, **overrides: Any) -> dict:
    payload = create_encounter_payload(
        patient_id, chw_id, encounter_date, **overrides
    )
    return get_success_data(api_client.create_encounter(payload, chw_headers))


def submitted_encounter(chw_headers: dict, patient_id: str, chw_id: str,
                        encounter_date: str, **overrides: Any) -> dict:
    """Create an encounter and walk it DRAFT → SUBMITTED."""
    encounter = create_encounter(
        chw_headers, patient_id, chw_id, encounter_date, **overrides
    )
    return get_success_data(
        api_client.submit_encounter(encounter["id"], chw_headers)
    )


def void_encounter(encounter_id: str, reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.void_encounter(encounter_id, payload, SUPERVISOR)
    )


# ─── Tier 4: payer billing ────────────────────────────────────────────────

def create_claim(patient_id: str, service_month: str, basis: str) -> dict:
    payload = create_payer_claim_payload(patient_id, service_month, basis)
    return get_success_data(api_client.create_payer_claim(payload, BILLING_SPECIALIST))


def adjudicate_claim(claim_id: str, outcome: str,
                     denial_reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"outcome": outcome}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.adjudicate_claim(claim_id, payload, BILLING_SPECIALIST)
    )


def appeal_claim(claim_id: str) -> dict:
    return get_success_data(api_client.appeal_claim(claim_id, BILLING_SPECIALIST))


def decide_appeal(claim_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_appeal(claim_id, {"decision": decision}, BILLING_SPECIALIST)
    )


def denied_claim(patient_id: str, service_month: str,
                 denial_reason: str = "Documentation insufficient") -> dict:
    """A FINAL claim carried through to DENIED, which anchors the appeal window
    at the current logical clock."""
    claim = create_claim(patient_id, service_month, "FINAL")
    return adjudicate_claim(claim["id"], "DENIED", denial_reason)


# ─── Tier 4: grant funding ────────────────────────────────────────────────

def open_award(**overrides: Any) -> dict:
    payload = create_grant_award_payload(**overrides)
    return get_success_data(api_client.create_grant_award(payload, PROGRAM_ADMIN))


def close_award(award_id: str) -> dict:
    return get_success_data(api_client.close_grant_award(award_id, PROGRAM_ADMIN))


def post_charge_line(award_id: str, encounter_id: str,
                     expected_grant_award_version: Optional[int] = None) -> dict:
    """Charge one encounter to one award, reading the award's live version
    unless the caller pins a specific one."""
    version = (
        expected_grant_award_version
        if expected_grant_award_version is not None
        else award_version(award_id)
    )
    payload = create_charge_line_payload(award_id, encounter_id, version)
    return get_success_data(api_client.create_charge_line(payload, BILLING_SPECIALIST))


def reverse_charge_line(line_id: str,
                        reversal_reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {}
    if reversal_reason is not None:
        payload["reversal_reason"] = reversal_reason
    return get_success_data(
        api_client.reverse_charge_line(line_id, payload, BILLING_SPECIALIST)
    )


def grant_funded_encounter(
    chw_headers: dict, patient_id: str, chw_id: str, encounter_date: str,
    award: Optional[dict] = None, **encounter_overrides: Any,
) -> Tuple[dict, dict, dict]:
    """A SUBMITTED encounter carved to a grant award. Returns
    `(award, encounter, charge_line)` with the encounter left LOCKED."""
    award = award or open_award()
    encounter = submitted_encounter(
        chw_headers, patient_id, chw_id, encounter_date, **encounter_overrides
    )
    line = post_charge_line(award["id"], encounter["id"])
    return award, encounter, line


# ─── Tier 5: escalations ──────────────────────────────────────────────────

def open_manual_escalation(headers: dict, patient_id: str,
                           note: Optional[str] = None) -> dict:
    payload = create_escalation_payload(patient_id)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_escalation(payload, headers))


def acknowledge_escalation(headers: dict, escalation_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_escalation(escalation_id, headers)
    )


def resolve_escalation(headers: dict, escalation_id: str) -> dict:
    return get_success_data(api_client.resolve_escalation(escalation_id, headers))


def escalations_for_offering(offering_id: str) -> List[dict]:
    response = api_client.list_escalations(
        PROGRAM_ADMIN, params={"blocking_offering_id": offering_id}
    )
    return get_success_data(response)


def escalations_for_patient(patient_id: str) -> List[dict]:
    response = api_client.list_escalations(
        PROGRAM_ADMIN, params={"patient_id": patient_id}
    )
    return get_success_data(response)


# ─── Tier 5: exhaustion scenario ──────────────────────────────────────────

def exhausted_offering_with_escalation(
    clock: str = DEFAULT_CLOCK, employee_code: str = "W-001",
) -> Dict[str, Any]:
    """Drive a single-unit offering to EXHAUSTED through one SENT referral, so
    the RESOURCE_EXHAUSTED escalation the exhaustion opens is readable.

    Returns a dict of worker / patient / chw_headers / org / offering /
    partner_headers / referral / escalation. The patient is ENROLLED and its
    gate is deliberately left OPEN.
    """
    worker, patient, chw_headers = program_with_patient(
        clock=clock, employee_code=employee_code
    )
    org, offering, partner_headers = org_with_offering(capacity_total=1)
    referral = send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"], units_requested=1
    )
    escalations = escalations_for_offering(offering["id"])
    return {
        "worker": worker,
        "patient": patient,
        "chw_headers": chw_headers,
        "org": org,
        "offering": offering,
        "partner_headers": partner_headers,
        "referral": referral,
        "escalations": escalations,
        "escalation": escalations[0] if escalations else None,
    }
