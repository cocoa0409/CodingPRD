"""Composite setup builders.

Every test starts against an empty store, so all state is built from scratch
through the published endpoints.  The builders here are ordinary functions
rather than pytest fixtures so a test can call the same chain twice with
different parameters (two agencies, two contracts, two programs) inside one
test body.

Layering, from cheapest to richest:

* tier 1 -- single-resource creators (``register_agency``, ``create_program``)
* tier 2 -- one resource driven to a state (``clear_agency``, ``activate_contract``)
* tier 3 -- an agency with a live contract, rate card, territory and training
  (``build_active_partner``)
* tier 4 -- a student file taken to the point where submission is legal
  (``build_submission_ready_application``) and then submitted and admitted
  (``build_admitted_application``)
* tier 5 -- histories that pre-load a performance tier (``build_platinum_history``)

Setup calls use the lenient success reader so a broken setup step reports the
server's own error identifier instead of a bare status mismatch.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import RecruitmentApiClient
from .test_users import (
    COMPLIANCE,
    COMPLIANCE_COUNTERSIGNER,
    FINANCE_APPROVER,
    FINANCE_PAYER,
    OFFICER,
    REGISTRAR,
    make_agency_owner_headers,
    make_applicant_headers,
)

# ======================================================================
# Tier 1 -- single resources
# ======================================================================


def set_clock(
    client: RecruitmentApiClient, to_iso8601: str, headers: Dict[str, str] = OFFICER
) -> Dict[str, Any]:
    """Move the logical clock and return the sweep report."""
    return get_success_data(client.set_clock(to_iso8601, headers))


def register_agency(
    client: RecruitmentApiClient,
    legal_name: str = "Sunrise Education Consultants",
    home_country_code: str = "IN",
    complete_diligence: bool = True,
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register an agency, by default with a checklist that can be cleared."""
    builder = (
        F.complete_diligence_agency_payload
        if complete_diligence
        else F.agency_payload
    )
    payload = builder(legal_name, home_country_code, **overrides)
    return get_success_data(client.register_agency(payload, headers), 201)


def create_program(
    client: RecruitmentApiClient,
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a program; defaults describe the postgraduate autumn intake."""
    return get_success_data(
        client.create_program(F.program_payload(**overrides), headers), 201
    )


def draft_contract(
    client: RecruitmentApiClient,
    agency_id: str,
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.draft_contract(F.contract_payload(agency_id, **overrides), headers), 201
    )


def append_schedule(
    client: RecruitmentApiClient,
    contract_id: str,
    expected_contract_version: int,
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.append_commission_schedule(
            contract_id,
            F.schedule_payload(expected_contract_version, **overrides),
            headers,
        ),
        201,
    )


def assign_territory(
    client: RecruitmentApiClient,
    contract_id: str,
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.assign_territory(contract_id, F.territory_payload(**overrides), headers),
        201,
    )


def record_certification(
    client: RecruitmentApiClient,
    agency_id: str,
    module_code: str = C.MODULE_PROGRAM_ACCURACY,
    score: int = 92,
    issued_on: str = C.DEFAULT_CLOCK_DATE,
    headers: Dict[str, str] = OFFICER,
) -> Dict[str, Any]:
    return get_success_data(
        client.record_certification(
            agency_id, F.certification_payload(module_code, score, issued_on), headers
        ),
        201,
    )


def record_required_certifications(
    client: RecruitmentApiClient,
    agency_id: str,
    issued_on: str = C.DEFAULT_CLOCK_DATE,
) -> Dict[str, Dict[str, Any]]:
    """Record the two modules the submission gate reads: accuracy and claims."""
    return {
        C.MODULE_PROGRAM_ACCURACY: record_certification(
            client, agency_id, C.MODULE_PROGRAM_ACCURACY, 92, issued_on
        ),
        C.MODULE_PROHIBITED_CLAIMS: record_certification(
            client, agency_id, C.MODULE_PROHIBITED_CLAIMS, 88, issued_on
        ),
    }


def create_application(
    client: RecruitmentApiClient,
    agency_id: str,
    program_id: str,
    student_ref: str = "STU-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a student file; only the owning agency may do this."""
    return get_success_data(
        client.create_application(
            F.application_payload(agency_id, program_id, student_ref, **overrides),
            make_agency_owner_headers(agency_id),
        ),
        201,
    )


def upload_document(
    client: RecruitmentApiClient,
    agency_id: str,
    application_id: str,
    doc_type: str = C.DOC_PASSPORT,
    content_hash: str = "hash-passport-0001",
    issuer_name: Optional[str] = "MEA India",
    declared_signals: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.upload_document(
            application_id,
            F.document_payload(
                doc_type, content_hash, issuer_name, declared_signals, **overrides
            ),
            make_agency_owner_headers(agency_id),
        ),
        201,
    )


def verify_document(
    client: RecruitmentApiClient,
    document_id: str,
    outcome: str = C.VERIFICATION_VERIFIED,
    headers: Dict[str, str] = COMPLIANCE,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.document_verification(
            document_id, F.verification_payload(outcome, **overrides), headers
        )
    )


def file_incident(
    client: RecruitmentApiClient,
    agency_id: str,
    headers: Dict[str, str] = COMPLIANCE,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.file_incident(F.incident_payload(agency_id, **overrides), headers), 201
    )


def resolve_incident(
    client: RecruitmentApiClient,
    incident_id: str,
    outcome: str = C.RESOLUTION_CONFIRM,
    headers: Dict[str, str] = COMPLIANCE,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.incident_resolution(
            incident_id, F.resolution_payload(outcome, **overrides), headers
        )
    )


def run_scorecard(
    client: RecruitmentApiClient,
    agency_id: str,
    period_start_date: str,
    period_end_date: str,
    headers: Dict[str, str] = OFFICER,
) -> Dict[str, Any]:
    return get_success_data(
        client.run_scorecard(
            agency_id, F.scorecard_payload(period_start_date, period_end_date), headers
        ),
        201,
    )


# ======================================================================
# Tier 2 -- resources driven to a state
# ======================================================================


def clear_agency(
    client: RecruitmentApiClient, agency_id: str, headers: Dict[str, str] = OFFICER
) -> Dict[str, Any]:
    """Drive an agency from DRAFT through SCREENING to CLEARED."""
    get_success_data(
        client.agency_vetting_action(
            agency_id, F.vetting_action_payload(C.VETTING_SUBMIT_FOR_SCREENING), headers
        )
    )
    return get_success_data(
        client.agency_vetting_action(
            agency_id, F.vetting_action_payload(C.VETTING_CLEAR), headers
        )
    )


def screen_agency(
    client: RecruitmentApiClient, agency_id: str, headers: Dict[str, str] = OFFICER
) -> Dict[str, Any]:
    """Drive an agency from DRAFT to SCREENING and stop there."""
    return get_success_data(
        client.agency_vetting_action(
            agency_id, F.vetting_action_payload(C.VETTING_SUBMIT_FOR_SCREENING), headers
        )
    )


def send_contract_for_signature(
    client: RecruitmentApiClient, contract_id: str, headers: Dict[str, str] = OFFICER
) -> Dict[str, Any]:
    return get_success_data(
        client.contract_lifecycle_action(
            contract_id, F.lifecycle_payload(C.LIFECYCLE_SEND_FOR_SIGNATURE), headers
        )
    )


def agency_sign_contract(
    client: RecruitmentApiClient, agency_id: str, contract_id: str
) -> Dict[str, Any]:
    """The agency countersigns using its own ownership-scoped identity."""
    return get_success_data(
        client.contract_lifecycle_action(
            contract_id,
            F.lifecycle_payload(C.LIFECYCLE_AGENCY_SIGN),
            make_agency_owner_headers(agency_id),
        )
    )


def compliance_approve_contract(
    client: RecruitmentApiClient,
    contract_id: str,
    headers: Dict[str, str] = COMPLIANCE_COUNTERSIGNER,
) -> Dict[str, Any]:
    """Countersign as a compliance officer other than the drafter."""
    return get_success_data(
        client.contract_lifecycle_action(
            contract_id, F.lifecycle_payload(C.LIFECYCLE_COMPLIANCE_APPROVE), headers
        )
    )


def request_amendment(
    client: RecruitmentApiClient,
    contract_id: str,
    note: str,
    headers: Dict[str, str] = COMPLIANCE,
) -> Dict[str, Any]:
    """Revert a contract awaiting countersignature back to draft."""
    return get_success_data(
        client.contract_lifecycle_action(
            contract_id,
            F.lifecycle_payload(C.LIFECYCLE_REQUEST_AMENDMENT, note=note),
            headers,
        )
    )


def suspend_contract(
    client: RecruitmentApiClient,
    contract_id: str,
    reason: str,
    headers: Dict[str, str] = COMPLIANCE,
) -> Dict[str, Any]:
    return get_success_data(
        client.contract_lifecycle_action(
            contract_id,
            F.lifecycle_payload(C.LIFECYCLE_SUSPEND, reason=reason),
            headers,
        )
    )


def posture_action(
    client: RecruitmentApiClient,
    agency_id: str,
    action: str,
    reason: str,
    headers: Dict[str, str] = COMPLIANCE,
) -> Dict[str, Any]:
    return get_success_data(
        client.agency_posture_action(
            agency_id, F.posture_action_payload(action, reason), headers
        )
    )


def release_territory(
    client: RecruitmentApiClient,
    contract_id: str,
    assignment_id: str,
    headers: Dict[str, str] = OFFICER,
) -> Dict[str, Any]:
    return get_success_data(
        client.release_territory(contract_id, assignment_id, headers)
    )


def terminate_contract(
    client: RecruitmentApiClient,
    contract_id: str,
    reason_code: str,
    effective_date: str,
    transition_note: str,
    successor_agency_id: Optional[str] = None,
    headers: Dict[str, str] = COMPLIANCE,
) -> Dict[str, Any]:
    return get_success_data(
        client.terminate_contract(
            contract_id,
            F.termination_payload(
                reason_code, effective_date, transition_note, successor_agency_id
            ),
            headers,
        )
    )


def activate_contract(
    client: RecruitmentApiClient,
    agency_id: str,
    contract_id: str,
    drafter_headers: Dict[str, str] = OFFICER,
    approver_headers: Dict[str, str] = COMPLIANCE_COUNTERSIGNER,
) -> Dict[str, Any]:
    """Walk a drafted contract all the way to ACTIVE."""
    send_contract_for_signature(client, contract_id, drafter_headers)
    agency_sign_contract(client, agency_id, contract_id)
    return compliance_approve_contract(client, contract_id, approver_headers)


def issue_disclosure(
    client: RecruitmentApiClient,
    agency_id: str,
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue the agent-relationship disclosure and mint the acknowledgement token.

    Both the recruitment officer and the owning agency may issue; the officer is
    the default because it needs no ownership threading.
    """
    return get_success_data(
        client.application_disclosure(
            application_id,
            F.disclosure_issue_payload(),
            headers if headers is not None else OFFICER,
        )
    )


def acknowledge_disclosure(
    client: RecruitmentApiClient,
    application_id: str,
    ack_token: str,
    applicant_user_id: str = "applicant-001",
) -> Dict[str, Any]:
    """The prospective student acknowledges using the single-use token."""
    return get_success_data(
        client.application_disclosure(
            application_id,
            F.disclosure_acknowledge_payload(ack_token),
            make_applicant_headers(applicant_user_id),
        )
    )


def issue_and_acknowledge_disclosure(
    client: RecruitmentApiClient,
    agency_id: str,
    application_id: str,
    applicant_user_id: str = "applicant-001",
) -> Dict[str, Any]:
    issued = issue_disclosure(client, agency_id, application_id)
    return acknowledge_disclosure(
        client, application_id, issued["disclosure_ack_token"], applicant_user_id
    )


def submit_application(
    client: RecruitmentApiClient, agency_id: str, application_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.submit_application(application_id, make_agency_owner_headers(agency_id))
    )


def admit_application(
    client: RecruitmentApiClient,
    application_id: str,
    headers: Dict[str, str] = OFFICER,
) -> Dict[str, Any]:
    return get_success_data(
        client.application_decision(
            application_id, F.decision_payload(C.DECISION_ADMIT), headers
        )
    )


def register_milestone(
    client: RecruitmentApiClient,
    application_id: str,
    milestone: str,
    event_date: str,
    expected_application_version: int,
    headers: Dict[str, str] = REGISTRAR,
) -> Dict[str, Any]:
    return get_success_data(
        client.register_milestone(
            application_id,
            F.milestone_payload(milestone, event_date, expected_application_version),
            headers,
        )
    )


def withdraw_application(
    client: RecruitmentApiClient,
    application_id: str,
    withdrawal_date: str,
    reason: str = "Student deferred to next intake",
    headers: Dict[str, str] = REGISTRAR,
) -> Dict[str, Any]:
    return get_success_data(
        client.withdraw_application(
            application_id, F.withdrawal_payload(withdrawal_date, reason), headers
        )
    )


def approve_entry(
    client: RecruitmentApiClient,
    entry_id: str,
    headers: Dict[str, str] = FINANCE_APPROVER,
) -> Dict[str, Any]:
    return get_success_data(
        client.entry_disposition(
            entry_id, F.disposition_payload(C.DISPOSITION_APPROVE), headers
        )
    )


def pay_entry(
    client: RecruitmentApiClient,
    entry_id: str,
    headers: Dict[str, str] = FINANCE_PAYER,
) -> Dict[str, Any]:
    return get_success_data(
        client.entry_disposition(
            entry_id, F.disposition_payload(C.DISPOSITION_PAY), headers
        )
    )


def void_entry(
    client: RecruitmentApiClient,
    entry_id: str,
    note: str = "Duplicate registrar feed",
    headers: Dict[str, str] = FINANCE_APPROVER,
) -> Dict[str, Any]:
    return get_success_data(
        client.entry_disposition(
            entry_id, F.disposition_payload(C.DISPOSITION_VOID, note=note), headers
        )
    )


# ======================================================================
# Reading helpers used by the richer builders
# ======================================================================


def read_agency(client: RecruitmentApiClient, agency_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_agency(agency_id, OFFICER))


def read_contract(client: RecruitmentApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_contract(contract_id, OFFICER))


def read_application(
    client: RecruitmentApiClient, application_id: str
) -> Dict[str, Any]:
    return get_success_data(client.get_application(application_id, OFFICER))


def read_document(client: RecruitmentApiClient, document_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_document(document_id, COMPLIANCE))


def read_entries(
    client: RecruitmentApiClient, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(client.list_commission_entries(FINANCE_APPROVER, params))


def read_certifications(
    client: RecruitmentApiClient, agency_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_certifications(agency_id, OFFICER, params or None)
    )


def read_scorecards(
    client: RecruitmentApiClient, agency_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(client.list_scorecards(agency_id, OFFICER, params or None))


def read_assignments(
    client: RecruitmentApiClient, contract_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_territory_assignments(contract_id, OFFICER, params or None)
    )


def read_schedules(
    client: RecruitmentApiClient, contract_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_commission_schedules(contract_id, OFFICER, params or None)
    )


def read_documents(
    client: RecruitmentApiClient, application_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_application_documents(application_id, OFFICER, params or None)
    )


def read_incidents(
    client: RecruitmentApiClient, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(client.list_incidents(COMPLIANCE, params or None))


def read_transitions(
    client: RecruitmentApiClient, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(client.list_file_transitions(OFFICER, params or None))


def read_projection(
    client: RecruitmentApiClient, application_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.get_commission_projection(application_id, FINANCE_APPROVER)
    )


def read_risk_profile(client: RecruitmentApiClient, agency_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_risk_profile(agency_id, COMPLIANCE))


def read_occupancy(
    client: RecruitmentApiClient, country_code: str, at_date: str
) -> Dict[str, Any]:
    return get_success_data(
        client.get_territory_occupancy(country_code, at_date, OFFICER)
    )


def contract_version(client: RecruitmentApiClient, contract_id: str) -> int:
    return read_contract(client, contract_id)["version"]


def application_version(client: RecruitmentApiClient, application_id: str) -> int:
    return read_application(client, application_id)["version"]


# ======================================================================
# Tier 3 -- an agency with a live contract, rate card and territory
# ======================================================================


def build_active_partner(
    client: RecruitmentApiClient,
    legal_name: str = "Sunrise Education Consultants",
    home_country_code: str = "IN",
    contract_ref: str = "CTR-2026-001",
    exclusivity_model: str = C.EXCLUSIVITY_EXCLUSIVE_ALLOWED,
    term_start_date: str = "2026-08-01",
    term_end_date: str = "2027-07-31",
    annual_commission_cap_cents: int = 5000000,
    territory_country: str = "IN",
    territory_exclusivity: str = C.TERRITORY_EXCLUSIVE,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    with_certifications: bool = True,
    certifications_issued_on: str = C.DEFAULT_CLOCK_DATE,
    activate: bool = True,
) -> Dict[str, Any]:
    """A cleared agency with a program, contract, one rate card and a territory.

    The rate card spans the whole contract term and the territory mirrors it, so
    the referential and temporal submission gates are satisfied by default.
    Returns the created resources keyed by role.
    """
    agency = register_agency(client, legal_name, home_country_code)
    clear_agency(client, agency["id"])

    program = create_program(client, **(program_overrides or {}))

    contract = draft_contract(
        client,
        agency["id"],
        contract_ref=contract_ref,
        exclusivity_model=exclusivity_model,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        annual_commission_cap_cents=annual_commission_cap_cents,
    )

    schedule_kwargs: Dict[str, Any] = {
        "effective_from": term_start_date,
        "effective_to": term_end_date,
    }
    schedule_kwargs.update(schedule_overrides or {})
    schedule = append_schedule(
        client, contract["id"], contract["version"], **schedule_kwargs
    )

    territory = assign_territory(
        client,
        contract["id"],
        country_code=territory_country,
        exclusivity=territory_exclusivity,
        start_date=term_start_date,
        end_date=term_end_date,
    )

    certifications: Dict[str, Dict[str, Any]] = {}
    if with_certifications:
        certifications = record_required_certifications(
            client, agency["id"], certifications_issued_on
        )

    if activate:
        activate_contract(client, agency["id"], contract["id"])

    return {
        "agency": agency,
        "agency_id": agency["id"],
        "owner_headers": make_agency_owner_headers(agency["id"]),
        "program": program,
        "program_id": program["id"],
        "contract": contract,
        "contract_id": contract["id"],
        "schedule": schedule,
        "schedule_id": schedule["id"],
        "territory": territory,
        "territory_id": territory["id"],
        "certifications": certifications,
    }


# ======================================================================
# Tier 4 -- student files
# ======================================================================


def build_submission_ready_application(
    client: RecruitmentApiClient,
    partner: Dict[str, Any],
    student_ref: str = "STU-0001",
    student_residence_country: str = "IN",
    student_us_person: bool = False,
    passport_hash: str = "hash-passport-0001",
    passport_issuer: str = "MEA India",
    applicant_user_id: str = "applicant-001",
    verify_passport: bool = True,
    acknowledge: bool = True,
    program_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A DRAFT student file with a VERIFIED passport and an acknowledged disclosure."""
    application = create_application(
        client,
        partner["agency_id"],
        program_id or partner["program_id"],
        student_ref=student_ref,
        student_residence_country=student_residence_country,
        student_us_person=student_us_person,
    )
    passport = upload_document(
        client,
        partner["agency_id"],
        application["id"],
        C.DOC_PASSPORT,
        passport_hash,
        passport_issuer,
    )
    if verify_passport:
        verify_document(client, passport["id"], C.VERIFICATION_VERIFIED)

    issued: Optional[Dict[str, Any]] = None
    if acknowledge:
        issued = issue_disclosure(client, partner["agency_id"], application["id"])
        acknowledge_disclosure(
            client,
            application["id"],
            issued["disclosure_ack_token"],
            applicant_user_id,
        )

    return {
        "application": application,
        "application_id": application["id"],
        "passport": passport,
        "passport_id": passport["id"],
        "ack_token": issued["disclosure_ack_token"] if issued else None,
    }


def build_admitted_application(
    client: RecruitmentApiClient,
    partner: Dict[str, Any],
    student_ref: str = "STU-0001",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A submitted-and-admitted student file, with its post-admission version."""
    ready = build_submission_ready_application(
        client, partner, student_ref=student_ref, **kwargs
    )
    submit_application(client, partner["agency_id"], ready["application_id"])
    admitted = admit_application(client, ready["application_id"])
    ready["admitted"] = admitted
    ready["version"] = admitted["version"]
    return ready


# ======================================================================
# Tier 5 -- pre-loaded histories
# ======================================================================


def build_platinum_history(
    client: RecruitmentApiClient,
    legal_name: str = "Sunrise Education Consultants",
    home_country_code: str = "IN",
) -> Dict[str, Any]:
    """An agency whose closed scorecard window already earned the top tier.

    A first student file is taken from submission through persistence on a
    commission-ineligible foundation programme, so the cohort counts are perfect
    and no ledger rows exist to muddy later assertions.  A scorecard is then run
    over the closed window, which refreshes the agency's tier.  A second,
    commission-eligible programme is created for the tests that follow.
    """
    partner = build_active_partner(
        client,
        legal_name=legal_name,
        home_country_code=home_country_code,
        program_overrides={
            "code": "FOUND-2026",
            "name": "Foundation Year",
            "level": C.LEVEL_UNDERGRADUATE,
            "annual_tuition_cents": 1000000,
            "term_start_date": "2026-08-03",
            "census_date": "2026-08-06",
            "persistence_check_date": "2026-08-10",
            "commission_eligible": False,
            "max_commission_bps": 1000,
        },
    )
    masters = create_program(
        client,
        code="MSCS-2026",
        name="MSc Computer Science",
        level=C.LEVEL_POSTGRADUATE,
        annual_tuition_cents=2845700,
        term_start_date="2026-09-01",
        census_date="2026-09-30",
        persistence_check_date="2027-02-15",
        max_commission_bps=1000,
    )

    first = build_submission_ready_application(
        client, partner, student_ref="STU-0001", passport_hash="hash-passport-0001"
    )
    submit_application(client, partner["agency_id"], first["application_id"])
    admitted = admit_application(client, first["application_id"])
    version = admitted["version"]

    for milestone, event_date, clock in (
        (C.MILESTONE_DEPOSIT_PAID, "2026-08-03", "2026-08-03T00:00:00Z"),
        (C.MILESTONE_ENROLLED, "2026-08-04", "2026-08-04T00:00:00Z"),
        (C.MILESTONE_CENSUS_CONFIRMED, "2026-08-06", "2026-08-06T00:00:00Z"),
        (C.MILESTONE_PERSISTED, "2026-08-10", "2026-08-10T00:00:00Z"),
    ):
        set_clock(client, clock)
        updated = register_milestone(
            client, first["application_id"], milestone, event_date, version
        )
        version = updated["version"]

    set_clock(client, "2026-08-11T00:00:00Z")
    scorecard = run_scorecard(
        client, partner["agency_id"], "2026-08-01", "2026-08-11"
    )

    partner["masters_program"] = masters
    partner["masters_program_id"] = masters["id"]
    partner["first_application_id"] = first["application_id"]
    partner["platinum_scorecard"] = scorecard
    return partner
