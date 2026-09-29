"""Composite state builders.

Each builder drives the real API through the same sequence of calls a licensee
and board staff would make, and returns the entity dictionaries it created so a
test can pin identifiers, versions, and derived values without re-deriving the
chain inline. Every builder accepts `**overrides` for the payload of the record
it is primarily creating, so a test can vary exactly one input.

The server is restarted before every test, so every builder starts from an empty
database and creates its own board, program, and nurse unless it is handed one.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_DEFAULT, TEST_DEFAULTS
from .factories import (
    board_config_payload,
    ce_record_payload,
    complaint_payload,
    disciplinary_proceeding_payload,
    education_program_payload,
    evidence_request_payload,
    license_application_payload,
    monitoring_agreement_payload,
    nurse_payload,
    practice_hour_period,
    renewal_application_payload,
)
from .test_users import (
    make_applicant_headers,
    make_board_member_headers,
    make_investigator_headers,
    make_licensure_analyst_headers,
    make_monitoring_coordinator_headers,
    make_system_admin_headers,
)

# The instant most renewal chains run at: one month before a credential issued
# at the clock default expires, so `late_days` is 0.
RENEWAL_CLOCK = "2028-07-01T00:00:00Z"

# A single accredited live-contact claim worth exactly the default 30.00 hour
# requirement (1800 minutes / 60 = 30.00).
SUFFICIENT_CE_MINUTES = 1800

ADMIN = make_system_admin_headers()
ANALYST = make_licensure_analyst_headers()
INVESTIGATOR = make_investigator_headers()
PRESIDING = make_board_member_headers("bm-presiding")
COORDINATOR = make_monitoring_coordinator_headers()


# ---------------------------------------------------------------------------
# Tier 1 — single-step state progression
# ---------------------------------------------------------------------------

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return the sweep response."""
    return get_success_data(api.set_clock({"current_utc": current_utc}, ADMIN))


def seed_board(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one state board of nursing."""
    return get_success_data(
        api.create_board_config(board_config_payload(**overrides), ADMIN), 201
    )


def seed_compact_board(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a board that participates in the multistate compact."""
    overrides.setdefault("compact_member", True)
    return seed_board(api, **overrides)


def seed_second_board(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a second, distinctly coded board."""
    overrides.setdefault("state_code", TEST_DEFAULTS["SECOND_STATE_CODE"])
    overrides.setdefault("board_name", TEST_DEFAULTS["SECOND_BOARD_NAME"])
    return seed_board(api, **overrides)


def seed_program(api: ApiClient, board_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register one approved nursing education program under a board."""
    return get_success_data(
        api.create_education_program(education_program_payload(board_id, **overrides), ADMIN),
        201,
    )


def seed_nurse(api: ApiClient, board_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create one nurse identity record homed at a board."""
    return get_success_data(
        api.create_nurse(nurse_payload(board_id, **overrides), ANALYST), 201
    )


def seed_application(api: ApiClient, nurse_id: str, board_id: str,
                     program_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """Create a licence application, left at DRAFT."""
    payload = license_application_payload(nurse_id, board_id, program_id, **overrides)
    return get_success_data(api.create_license_application(payload, ANALYST), 201)


def submit_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    """Advance a DRAFT application to SUBMITTED."""
    return get_success_data(api.submit_license_application(application_id, ANALYST))


def verify_application_qualification(api: ApiClient, application_id: str) -> Dict[str, Any]:
    """Run the qualification gate, which orders criminal-history screening."""
    return get_success_data(
        api.verify_license_application_qualification(application_id, ANALYST)
    )


def record_clean_screening(api: ApiClient, application_id: str) -> Dict[str, Any]:
    """Return an empty criminal-history answer for an application."""
    return get_success_data(
        api.record_screening_result(application_id, {"screening_offense_records": []}, ANALYST)
    )


def mint_license(api: ApiClient, application_id: str, **overrides: Any) -> Dict[str, Any]:
    """Mint the credential an approved application entitles the nurse to."""
    payload: Dict[str, Any] = {"source_application_id": application_id}
    payload.update(overrides)
    return get_success_data(api.create_license(payload, ANALYST), 201)


def license_version(api: ApiClient, license_id: str) -> int:
    """Read a credential's current `version` for the renewal guard."""
    return get_success_data(api.get_license(license_id, ANALYST))["version"]


def complaint_version(api: ApiClient, complaint_id: str) -> int:
    """Read a complaint's current `version` for the proceeding guard."""
    return get_success_data(api.get_complaint(complaint_id, INVESTIGATOR))["version"]


def reread_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    """Re-read a credential after a side effect."""
    return get_success_data(api.get_license(license_id, ANALYST))


def reread_nurse(api: ApiClient, nurse_id: str) -> Dict[str, Any]:
    """Re-read a nurse after a side effect."""
    return get_success_data(api.get_nurse(nurse_id, ANALYST))


def reread_complaint(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    """Re-read a complaint after a side effect."""
    return get_success_data(api.get_complaint(complaint_id, INVESTIGATOR))


def reread_renewal(api: ApiClient, renewal_id: str) -> Dict[str, Any]:
    """Re-read a renewal filing after a side effect."""
    return get_success_data(api.get_renewal_application(renewal_id, ANALYST))


def reread_proceeding(api: ApiClient, proceeding_id: str) -> Dict[str, Any]:
    """Re-read a proceeding after a side effect."""
    return get_success_data(api.get_disciplinary_proceeding(proceeding_id, PRESIDING))


def reread_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    """Re-read a monitoring agreement after a side effect."""
    return get_success_data(api.get_monitoring_agreement(agreement_id, COORDINATOR))


def all_reports(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    """List every notification report, optionally narrowed."""
    query: Dict[str, Any] = {"limit": 100}
    query.update(params)
    body = api.list_notification_reports(ANALYST, params=query).json()
    return body["data"]


def reports_for_source(api: ApiClient, source_entity_id: str) -> List[Dict[str, Any]]:
    """Every report whose `source_entity_id` is the given record."""
    return [
        report for report in all_reports(api)
        if report["source_entity_id"] == source_entity_id
    ]


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def seed_board_program_nurse(api: ApiClient,
                             board_overrides: Optional[Dict[str, Any]] = None,
                             program_overrides: Optional[Dict[str, Any]] = None,
                             nurse_overrides: Optional[Dict[str, Any]] = None,
                             compact: bool = True) -> Dict[str, Any]:
    """Board, one approved program, and one nurse — the base of every chain."""
    board_kwargs = dict(board_overrides or {})
    if compact:
        board_kwargs.setdefault("compact_member", True)
    board = seed_board(api, **board_kwargs)
    program = seed_program(api, board["id"], **(program_overrides or {}))
    nurse = seed_nurse(api, board["id"], **(nurse_overrides or {}))
    return {
        "board": board,
        "board_id": board["id"],
        "program": program,
        "program_id": program["id"],
        "nurse": nurse,
        "nurse_id": nurse["id"],
        "applicant_headers": make_applicant_headers(nurse["id"]),
    }


def seed_screened_application(api: ApiClient,
                              board_overrides: Optional[Dict[str, Any]] = None,
                              program_overrides: Optional[Dict[str, Any]] = None,
                              nurse_overrides: Optional[Dict[str, Any]] = None,
                              compact: bool = True,
                              **application_overrides: Any) -> Dict[str, Any]:
    """An application carried to the point where a credential may be minted."""
    ctx = seed_board_program_nurse(api, board_overrides, program_overrides,
                                   nurse_overrides, compact)
    application = seed_application(api, ctx["nurse_id"], ctx["board_id"],
                                   ctx["program_id"], **application_overrides)
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    application = record_clean_screening(api, application["id"])
    ctx["application"] = application
    ctx["application_id"] = application["id"]
    return ctx


def seed_active_license(api: ApiClient,
                        board_overrides: Optional[Dict[str, Any]] = None,
                        program_overrides: Optional[Dict[str, Any]] = None,
                        nurse_overrides: Optional[Dict[str, Any]] = None,
                        compact: bool = True,
                        **application_overrides: Any) -> Dict[str, Any]:
    """Board, program, nurse, approved application, and a minted credential.

    Returns the full context: every entity dictionary plus `license_id` and the
    Applicant headers bound to the nurse's own identifier.
    """
    ctx = seed_screened_application(api, board_overrides, program_overrides,
                                    nurse_overrides, compact, **application_overrides)
    credential = mint_license(api, ctx["application_id"])
    ctx["license"] = credential
    ctx["license_id"] = credential["id"]
    return ctx


def seed_aprn_license(api: ApiClient, ctx: Dict[str, Any],
                      program_overrides: Optional[Dict[str, Any]] = None,
                      aprn_role: str = "NP") -> Dict[str, Any]:
    """A dependent APRN credential built on the registered nurse credential."""
    program_kwargs = {
        "program_code": "OH-MSN-41",
        "program_name": "Erie MSN",
        "degree_level": "MSN",
        "nclex_first_time_pass_rate_bp": 9400,
    }
    program_kwargs.update(program_overrides or {})
    aprn_program = seed_program(api, ctx["board_id"], **program_kwargs)
    application = seed_application(
        api, ctx["nurse_id"], ctx["board_id"], aprn_program["id"],
        credential_type="APRN", aprn_role=aprn_role,
        base_license_id=ctx["license_id"],
    )
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    record_clean_screening(api, application["id"])
    aprn = mint_license(api, application["id"])
    ctx["aprn_program"] = aprn_program
    ctx["aprn_application_id"] = application["id"]
    ctx["aprn_license"] = aprn
    ctx["aprn_license_id"] = aprn["id"]
    return ctx


def seed_sibling_license(api: ApiClient, ctx: Dict[str, Any],
                         **nurse_overrides: Any) -> Dict[str, Any]:
    """A second nurse at the same board, holding her own registered-nurse credential.

    One live credential of each type per nurse per board is the rule, so a second
    credential in the same board must belong to a different nurse.
    """
    kwargs = {"full_name": "Sam Ortiz", "birth_year": 1991, "ssn_last4": "8320"}
    kwargs.update(nurse_overrides)
    nurse = seed_nurse(api, ctx["board_id"], **kwargs)
    application = seed_application(api, nurse["id"], ctx["board_id"], ctx["program_id"])
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    record_clean_screening(api, application["id"])
    credential = mint_license(api, application["id"])
    return {
        "nurse": nurse,
        "nurse_id": nurse["id"],
        "application_id": application["id"],
        "license": credential,
        "license_id": credential["id"],
        "applicant_headers": make_applicant_headers(nurse["id"]),
    }


def change_status(api: ApiClient, license_id: str, to_status: str) -> Dict[str, Any]:
    """Drive the credential's own status dimension."""
    return get_success_data(
        api.change_license_status(license_id, {"to_status": to_status}, ANALYST)
    )


def determine_privilege(api: ApiClient, license_id: str,
                       variant: str = "RESIDENCY_DECLARED") -> Dict[str, Any]:
    """Run the compact privilege determination under one variant."""
    return get_success_data(
        api.run_privilege_determination(license_id, {"variant": variant}, ANALYST)
    )


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts: complaints
# ---------------------------------------------------------------------------

def seed_complaint(api: ApiClient, license_id: str, **overrides: Any) -> Dict[str, Any]:
    """File one complaint against a credential, left at RECEIVED."""
    return get_success_data(
        api.create_complaint(complaint_payload(license_id, **overrides), INVESTIGATOR), 201
    )


def triage_complaint(api: ApiClient, complaint_id: str,
                     jurisdiction_finding: str = "JURISDICTION_CONFIRMED",
                     **overrides: Any) -> Dict[str, Any]:
    """Triage a RECEIVED complaint."""
    payload: Dict[str, Any] = {"jurisdiction_finding": jurisdiction_finding}
    payload.update(overrides)
    return get_success_data(api.triage_complaint(complaint_id, payload, INVESTIGATOR))


def open_investigation(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    """Open the investigation on a triaged complaint."""
    return get_success_data(api.open_investigation(complaint_id, INVESTIGATOR))


def seed_investigated_complaint(api: ApiClient, license_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    """A complaint carried to INVESTIGATION_OPEN."""
    complaint = seed_complaint(api, license_id, **overrides)
    triage_complaint(api, complaint["id"])
    return open_investigation(api, complaint["id"])


def seed_evidence_request(api: ApiClient, complaint_id: str, **overrides: Any) -> Dict[str, Any]:
    """Issue one records demand against an open investigation."""
    return get_success_data(
        api.create_evidence_request(complaint_id, evidence_request_payload(**overrides),
                                    INVESTIGATOR),
        201,
    )


def record_production(api: ApiClient, evidence_request_id: str,
                      page_count: int = 42) -> Dict[str, Any]:
    """Record a custodian's production against a demand."""
    return get_success_data(
        api.record_evidence_production(evidence_request_id, {"page_count": page_count},
                                       INVESTIGATOR)
    )


def seed_produced_evidence_request(api: ApiClient, complaint_id: str,
                                   page_count: int = 42, **overrides: Any) -> Dict[str, Any]:
    """A records demand that has already been satisfied."""
    demand = seed_evidence_request(api, complaint_id, **overrides)
    return record_production(api, demand["id"], page_count)


def complete_evidence(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    """Close the evidence phase of an investigation."""
    return get_success_data(api.complete_complaint_evidence(complaint_id, INVESTIGATOR))


def seed_evidence_complete_complaint(api: ApiClient, license_id: str,
                                     page_count: int = 42,
                                     evidence_overrides: Optional[Dict[str, Any]] = None,
                                     **overrides: Any) -> Dict[str, Any]:
    """A complaint carried to EVIDENCE_COMPLETE with one satisfied demand."""
    complaint = seed_investigated_complaint(api, license_id, **overrides)
    seed_produced_evidence_request(api, complaint["id"], page_count,
                                   **(evidence_overrides or {}))
    return complete_evidence(api, complaint["id"])


def dispose_complaint(api: ApiClient, complaint_id: str, disposition: str,
                      **overrides: Any) -> Dict[str, Any]:
    """Dispose of a complaint whose evidence phase is closed."""
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return get_success_data(api.dispose_complaint(complaint_id, payload, INVESTIGATOR))


def seed_referred_complaint(api: ApiClient, license_id: str,
                            page_count: int = 42,
                            evidence_overrides: Optional[Dict[str, Any]] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """A complaint carried to REFERRED_FOR_HEARING."""
    complaint = seed_evidence_complete_complaint(api, license_id, page_count,
                                                 evidence_overrides, **overrides)
    return dispose_complaint(api, complaint["id"], "REFER_TO_PROCEEDING")


def seed_atd_offered_complaint(api: ApiClient, license_id: str,
                               page_count: int = 24,
                               evidence_overrides: Optional[Dict[str, Any]] = None,
                               **overrides: Any) -> Dict[str, Any]:
    """A substance-use complaint carried to ATD_OFFERED."""
    overrides.setdefault("violation_category", "SUBSTANCE_USE")
    overrides.setdefault("complainant_type", "SELF_REPORT")
    complaint = seed_evidence_complete_complaint(api, license_id, page_count,
                                                 evidence_overrides, **overrides)
    return dispose_complaint(api, complaint["id"], "OFFER_ATD")


def seed_dismissed_complaint(api: ApiClient, license_id: str,
                             page_count: int = 12,
                             evidence_overrides: Optional[Dict[str, Any]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """A complaint carried to the terminal DISMISSED state."""
    complaint = seed_evidence_complete_complaint(api, license_id, page_count,
                                                 evidence_overrides, **overrides)
    return dispose_complaint(api, complaint["id"], "DISMISS")


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts: renewals
# ---------------------------------------------------------------------------

def seed_renewal(api: ApiClient, license_id: str,
                 clock: Optional[str] = RENEWAL_CLOCK,
                 attested_practice_hours: int = 1800,
                 **overrides: Any) -> Dict[str, Any]:
    """Open a DRAFT renewal filing, moving the clock into the window first."""
    if clock is not None:
        set_clock(api, clock)
    version = license_version(api, license_id)
    payload = renewal_application_payload(
        license_id, version, attested_practice_hours=attested_practice_hours, **overrides
    )
    return get_success_data(api.create_renewal_application(payload, ANALYST), 201)


def seed_ce_record(api: ApiClient, renewal_id: str, verified: bool = True,
                   **overrides: Any) -> Dict[str, Any]:
    """Attach one continuing-education claim, verified by default."""
    record = get_success_data(
        api.create_ce_record(renewal_id, ce_record_payload(**overrides), ANALYST), 201
    )
    if verified:
        record = verify_ce_record(api, record["id"], "VERIFIED")
    return record


def verify_ce_record(api: ApiClient, ce_record_id: str,
                     verification_status: str = "VERIFIED") -> Dict[str, Any]:
    """Set an analyst's verification outcome on one claim."""
    return get_success_data(
        api.verify_ce_record(ce_record_id, {"verification_status": verification_status},
                             ANALYST)
    )


def pay_renewal(api: ApiClient, renewal_id: str) -> Dict[str, Any]:
    """Assess and receive the renewal fee in one act."""
    return get_success_data(api.pay_renewal_application(renewal_id, ANALYST))


def submit_renewal(api: ApiClient, renewal_id: str) -> Dict[str, Any]:
    """Advance a renewal filing to SUBMITTED."""
    return get_success_data(api.submit_renewal_application(renewal_id, ANALYST))


def verify_renewal_ce(api: ApiClient, renewal_id: str) -> Dict[str, Any]:
    """Run the audited continuing-education variant over a filing."""
    return get_success_data(api.verify_renewal_ce(renewal_id, ANALYST))


def finalize_renewal(api: ApiClient, renewal_id: str, outcome: str) -> Dict[str, Any]:
    """Grant or deny a renewal filing."""
    return get_success_data(
        api.finalize_renewal_application(renewal_id, {"outcome": outcome}, ANALYST)
    )


def seed_submitted_renewal(api: ApiClient, license_id: str,
                           clock: Optional[str] = RENEWAL_CLOCK,
                           attested_practice_hours: int = 1800,
                           ce_minutes: int = SUFFICIENT_CE_MINUTES,
                           ce_completion_date: str = "2027-06-01T00:00:00Z",
                           **overrides: Any) -> Dict[str, Any]:
    """A paid, SUBMITTED renewal filing carrying enough verified credit."""
    renewal = seed_renewal(api, license_id, clock, attested_practice_hours, **overrides)
    seed_ce_record(api, renewal["id"], minutes=ce_minutes,
                   completion_date=ce_completion_date)
    pay_renewal(api, renewal["id"])
    return submit_renewal(api, renewal["id"])


def seed_ce_verified_renewal(api: ApiClient, license_id: str,
                             clock: Optional[str] = RENEWAL_CLOCK,
                             attested_practice_hours: int = 1800,
                             ce_minutes: int = SUFFICIENT_CE_MINUTES,
                             ce_completion_date: str = "2027-06-01T00:00:00Z",
                             **overrides: Any) -> Dict[str, Any]:
    """A renewal filing whose audited credit total has cleared the requirement."""
    renewal = seed_submitted_renewal(api, license_id, clock, attested_practice_hours,
                                     ce_minutes, ce_completion_date, **overrides)
    return verify_renewal_ce(api, renewal["id"])


def seed_licensed_renewal_context(api: ApiClient, stage: str = "CE_VERIFIED",
                                 attested_practice_hours: int = 1800,
                                 board_overrides: Optional[Dict[str, Any]] = None,
                                 program_overrides: Optional[Dict[str, Any]] = None,
                                 nurse_overrides: Optional[Dict[str, Any]] = None,
                                 **renewal_overrides: Any) -> Dict[str, Any]:
    """A credential plus a renewal filing carried to the named stage.

    `stage` is one of DRAFT, SUBMITTED, or CE_VERIFIED.
    """
    ctx = seed_active_license(api, board_overrides, program_overrides, nurse_overrides)
    if stage == "DRAFT":
        renewal = seed_renewal(api, ctx["license_id"],
                               attested_practice_hours=attested_practice_hours,
                               **renewal_overrides)
    elif stage == "SUBMITTED":
        renewal = seed_submitted_renewal(api, ctx["license_id"],
                                         attested_practice_hours=attested_practice_hours,
                                         **renewal_overrides)
    elif stage == "CE_VERIFIED":
        renewal = seed_ce_verified_renewal(api, ctx["license_id"],
                                           attested_practice_hours=attested_practice_hours,
                                           **renewal_overrides)
    else:
        raise ValueError(f"Unsupported renewal stage: {stage}")
    ctx["renewal"] = renewal
    ctx["renewal_id"] = renewal["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting: audits
# ---------------------------------------------------------------------------

def run_sampling(api: ApiClient, board_id: str) -> Dict[str, Any]:
    """Run the board-wide practice-hour audit sampling pass."""
    return get_success_data(api.run_audit_sampling({"board_config_id": board_id}, ADMIN))


def request_audit_docs(api: ApiClient, renewal_id: str,
                       note: Optional[str] = None) -> Dict[str, Any]:
    """Demand practice-hour documentation on a sampled filing."""
    payload = {"note": note} if note is not None else None
    return get_success_data(api.request_audit_documentation(renewal_id, ANALYST, payload))


def submit_audit_docs(api: ApiClient, renewal_id: str,
                      periods: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Submit employment periods against an open documentation demand."""
    return get_success_data(
        api.submit_audit_documentation(renewal_id, {"practice_hour_periods": periods},
                                       ANALYST)
    )


def decide_audit(api: ApiClient, renewal_id: str) -> Dict[str, Any]:
    """Prorate the submitted periods and settle the audit dimension."""
    return get_success_data(api.decide_audit(renewal_id, ANALYST))


def seed_selected_renewal(api: ApiClient, attested_practice_hours: int = 1800,
                          board_overrides: Optional[Dict[str, Any]] = None,
                          **renewal_overrides: Any) -> Dict[str, Any]:
    """A CE_VERIFIED filing drawn into the audit sample.

    A single eligible filing under any non-zero basis-point rate yields a quota
    of one, so the lone filing is always drawn.
    """
    ctx = seed_licensed_renewal_context(api, "CE_VERIFIED", attested_practice_hours,
                                        board_overrides, **renewal_overrides)
    ctx["sampling"] = run_sampling(api, ctx["board_id"])
    ctx["renewal"] = reread_renewal(api, ctx["renewal_id"])
    return ctx


def seed_docs_requested_renewal(api: ApiClient, attested_practice_hours: int = 1800,
                                board_overrides: Optional[Dict[str, Any]] = None,
                                **renewal_overrides: Any) -> Dict[str, Any]:
    """A sampled filing whose documentation has been demanded once."""
    ctx = seed_selected_renewal(api, attested_practice_hours, board_overrides,
                                **renewal_overrides)
    ctx["renewal"] = request_audit_docs(api, ctx["renewal_id"])
    return ctx


def seed_docs_submitted_renewal(api: ApiClient,
                                periods: Optional[List[Dict[str, Any]]] = None,
                                attested_practice_hours: int = 1800,
                                board_overrides: Optional[Dict[str, Any]] = None,
                                **renewal_overrides: Any) -> Dict[str, Any]:
    """A sampled filing whose employment periods are on file."""
    ctx = seed_docs_requested_renewal(api, attested_practice_hours, board_overrides,
                                      **renewal_overrides)
    if periods is None:
        periods = [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 1000)]
    ctx["renewal"] = submit_audit_docs(api, ctx["renewal_id"], periods)
    ctx["submitted_periods"] = periods
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting: monitoring
# ---------------------------------------------------------------------------

def seed_monitoring_agreement(api: ApiClient, nurse_id: str, complaint_id: str,
                              **overrides: Any) -> Dict[str, Any]:
    """Offer an alternative-to-discipline agreement, left at OFFERED."""
    payload = monitoring_agreement_payload(nurse_id, complaint_id, **overrides)
    return get_success_data(api.create_monitoring_agreement(payload, PRESIDING), 201)


def execute_agreement(api: ApiClient, agreement_id: str, nurse_id: str) -> Dict[str, Any]:
    """The nurse signs their own agreement, so the Applicant identity is the nurse."""
    return get_success_data(
        api.execute_monitoring_agreement(agreement_id, make_applicant_headers(nurse_id))
    )


def record_monitoring_event(api: ApiClient, agreement_id: str, event_type: str,
                            coordinator_user_id: str = "mc-1",
                            **overrides: Any) -> Dict[str, Any]:
    """Log one monitoring event against an agreement."""
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(overrides)
    return get_success_data(
        api.record_monitoring_event(agreement_id, payload,
                                    make_monitoring_coordinator_headers(coordinator_user_id))
    )


def seed_executed_agreement(api: ApiClient,
                            board_overrides: Optional[Dict[str, Any]] = None,
                            nurse_overrides: Optional[Dict[str, Any]] = None,
                            program_overrides: Optional[Dict[str, Any]] = None,
                            complaint_overrides: Optional[Dict[str, Any]] = None,
                            **agreement_overrides: Any) -> Dict[str, Any]:
    """Credential, substance-use complaint at ATD_OFFERED, and a signed agreement."""
    ctx = seed_active_license(api, board_overrides, program_overrides, nurse_overrides)
    complaint = seed_atd_offered_complaint(api, ctx["license_id"],
                                           **(complaint_overrides or {}))
    agreement = seed_monitoring_agreement(api, ctx["nurse_id"], complaint["id"],
                                          **agreement_overrides)
    agreement = execute_agreement(api, agreement["id"], ctx["nurse_id"])
    ctx["complaint"] = complaint
    ctx["complaint_id"] = complaint["id"]
    ctx["agreement"] = agreement
    ctx["agreement_id"] = agreement["id"]
    return ctx


def seed_active_agreement(api: ApiClient,
                          activation_clock: str = "2026-09-01T00:00:00Z",
                          **kwargs: Any) -> Dict[str, Any]:
    """A signed agreement whose start date the clock has reached."""
    ctx = seed_executed_agreement(api, **kwargs)
    ctx["sweep"] = set_clock(api, activation_clock)
    ctx["agreement"] = reread_agreement(api, ctx["agreement_id"])
    return ctx


def seed_breached_agreement(api: ApiClient,
                            coordinator_user_id: str = "mc-1",
                            **kwargs: Any) -> Dict[str, Any]:
    """An active agreement the licensee has broken."""
    ctx = seed_active_agreement(api, **kwargs)
    ctx["agreement"] = record_monitoring_event(api, ctx["agreement_id"], "BREACH",
                                                coordinator_user_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting: proceedings
# ---------------------------------------------------------------------------

FIVE_MEMBER_PANEL = ["bm-1", "bm-2", "bm-3", "bm-4", "bm-5"]
THREE_MEMBER_PANEL = ["bm-1", "bm-2", "bm-3"]


def seed_proceeding(api: ApiClient, complaint_id: str,
                    seated_member_user_ids: Optional[List[str]] = None,
                    presiding_user_id: str = "bm-presiding",
                    **overrides: Any) -> Dict[str, Any]:
    """Open a proceeding on a referred complaint, leaving it NOTICED."""
    version = complaint_version(api, complaint_id)
    payload = disciplinary_proceeding_payload(
        complaint_id, version,
        seated_member_user_ids=seated_member_user_ids or THREE_MEMBER_PANEL,
        **overrides
    )
    return get_success_data(
        api.create_disciplinary_proceeding(payload,
                                           make_board_member_headers(presiding_user_id)),
        201,
    )


def record_hearing_event(api: ApiClient, proceeding_id: str, event_type: str,
                         presiding_user_id: str = "bm-presiding",
                         **overrides: Any) -> Dict[str, Any]:
    """Log one hearing event under the presiding member's identity."""
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(overrides)
    return get_success_data(
        api.record_hearing_event(proceeding_id, payload,
                                 make_board_member_headers(presiding_user_id))
    )


def cast_vote(api: ApiClient, proceeding_id: str, member_user_id: str,
              proposed_sanction_tier: str, **overrides: Any) -> Dict[str, Any]:
    """One seated member's vote for a sanction tier."""
    payload: Dict[str, Any] = {"proposed_sanction_tier": proposed_sanction_tier}
    payload.update(overrides)
    return get_success_data(
        api.cast_vote(proceeding_id, payload, make_board_member_headers(member_user_id))
    )


def cast_votes(api: ApiClient, proceeding_id: str,
               ballots: List[Any]) -> Dict[str, Any]:
    """Cast a list of `(member_user_id, tier)` ballots in order."""
    result: Dict[str, Any] = {}
    for member_user_id, tier in ballots:
        result = cast_vote(api, proceeding_id, member_user_id, tier)
    return result


def issue_order(api: ApiClient, proceeding_id: str,
                ordered_restriction_codes: Optional[List[str]] = None,
                presiding_user_id: str = "bm-presiding") -> Dict[str, Any]:
    """Issue the final order of a deliberating proceeding."""
    payload = {"ordered_restriction_codes": ordered_restriction_codes or []}
    return get_success_data(
        api.issue_order(proceeding_id, make_board_member_headers(presiding_user_id),
                        payload)
    )


def seed_referred_context(api: ApiClient,
                          board_overrides: Optional[Dict[str, Any]] = None,
                          program_overrides: Optional[Dict[str, Any]] = None,
                          nurse_overrides: Optional[Dict[str, Any]] = None,
                          page_count: int = 42,
                          evidence_overrides: Optional[Dict[str, Any]] = None,
                          **complaint_overrides: Any) -> Dict[str, Any]:
    """Credential plus a complaint standing at REFERRED_FOR_HEARING."""
    ctx = seed_active_license(api, board_overrides, program_overrides, nurse_overrides)
    complaint = seed_referred_complaint(api, ctx["license_id"], page_count,
                                        evidence_overrides, **complaint_overrides)
    ctx["complaint"] = complaint
    ctx["complaint_id"] = complaint["id"]
    return ctx


def seed_noticed_proceeding(api: ApiClient,
                            seated_member_user_ids: Optional[List[str]] = None,
                            proceeding_overrides: Optional[Dict[str, Any]] = None,
                            **context_kwargs: Any) -> Dict[str, Any]:
    """A proceeding opened on a referred complaint, awaiting its hearing."""
    ctx = seed_referred_context(api, **context_kwargs)
    proceeding = seed_proceeding(api, ctx["complaint_id"], seated_member_user_ids,
                                 **(proceeding_overrides or {}))
    ctx["proceeding"] = proceeding
    ctx["proceeding_id"] = proceeding["id"]
    return ctx


def seed_convened_proceeding(api: ApiClient,
                             seated_member_user_ids: Optional[List[str]] = None,
                             proceeding_overrides: Optional[Dict[str, Any]] = None,
                             **context_kwargs: Any) -> Dict[str, Any]:
    """A proceeding whose hearing has been convened and whose floor is fixed."""
    ctx = seed_noticed_proceeding(api, seated_member_user_ids, proceeding_overrides,
                                  **context_kwargs)
    ctx["proceeding"] = record_hearing_event(api, ctx["proceeding_id"], "CONVENE")
    return ctx


def seed_deliberating_proceeding(api: ApiClient, ballots: List[Any],
                                 seated_member_user_ids: Optional[List[str]] = None,
                                 proceeding_overrides: Optional[Dict[str, Any]] = None,
                                 **context_kwargs: Any) -> Dict[str, Any]:
    """A proceeding that has voted and closed its hearing, so a tier is adopted."""
    ctx = seed_convened_proceeding(api, seated_member_user_ids, proceeding_overrides,
                                   **context_kwargs)
    cast_votes(api, ctx["proceeding_id"], ballots)
    ctx["proceeding"] = record_hearing_event(api, ctx["proceeding_id"], "CLOSE_HEARING")
    return ctx


def seed_revocation_order(api: ApiClient,
                          seated_member_user_ids: Optional[List[str]] = None,
                          **context_kwargs: Any) -> Dict[str, Any]:
    """A criminal-conduct proceeding carried through a unanimous revocation order."""
    panel = seated_member_user_ids or FIVE_MEMBER_PANEL
    context_kwargs.setdefault("violation_category", "CRIMINAL_CONDUCT")
    context_kwargs.setdefault("complainant_type", "OTHER_STATE_BOARD")
    ctx = seed_deliberating_proceeding(
        api, [(member, "REVOCATION") for member in panel], panel, **context_kwargs
    )
    ctx["proceeding"] = issue_order(api, ctx["proceeding_id"])
    return ctx


def seed_custodian_holds(api: ApiClient, complaint_id: str,
                         windows: List[Any],
                         record_class: str = "EMPLOYER_PERSONNEL",
                         custodian_code: str = TEST_DEFAULTS["CUSTODIAN_PRIMARY"]
                         ) -> List[Dict[str, Any]]:
    """Issue several concurrent holds on one custodian from `(start, end)` pairs."""
    created = []
    for hold_start_at, hold_end_at in windows:
        created.append(seed_evidence_request(
            api, complaint_id,
            record_class=record_class,
            custodian_code=custodian_code,
            hold_start_at=hold_start_at,
            hold_end_at=hold_end_at,
        ))
    return created


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal states
# ---------------------------------------------------------------------------

def seed_expired_license(api: ApiClient,
                         expiry_clock: str = "2028-08-02T00:00:00Z",
                         **context_kwargs: Any) -> Dict[str, Any]:
    """A credential the clock has carried past its expiry date."""
    ctx = seed_active_license(api, **context_kwargs)
    ctx["sweep"] = set_clock(api, expiry_clock)
    ctx["license"] = reread_license(api, ctx["license_id"])
    return ctx


def seed_lapsed_license(api: ApiClient,
                        lapse_clock: str = "2029-01-01T00:00:00Z",
                        **context_kwargs: Any) -> Dict[str, Any]:
    """A credential left unrenewed past expiry, grace, and the lapse window."""
    ctx = seed_active_license(api, **context_kwargs)
    set_clock(api, "2028-08-02T00:00:00Z")
    ctx["sweep"] = set_clock(api, lapse_clock)
    ctx["license"] = reread_license(api, ctx["license_id"])
    return ctx


def seed_renewed_license(api: ApiClient, **context_kwargs: Any) -> Dict[str, Any]:
    """A credential whose renewal filing has been granted."""
    ctx = seed_licensed_renewal_context(api, "CE_VERIFIED", **context_kwargs)
    ctx["renewal"] = finalize_renewal(api, ctx["renewal_id"], "RENEWED")
    ctx["license"] = reread_license(api, ctx["license_id"])
    return ctx


def seed_denied_renewal(api: ApiClient, **context_kwargs: Any) -> Dict[str, Any]:
    """A credential whose renewal filing has been denied."""
    ctx = seed_licensed_renewal_context(api, "CE_VERIFIED", **context_kwargs)
    ctx["renewal"] = finalize_renewal(api, ctx["renewal_id"], "DENIED")
    ctx["license"] = reread_license(api, ctx["license_id"])
    ctx["nurse"] = reread_nurse(api, ctx["nurse_id"])
    return ctx


def seed_failed_audit_renewal(api: ApiClient,
                              periods: Optional[List[Dict[str, Any]]] = None,
                              **context_kwargs: Any) -> Dict[str, Any]:
    """A filing whose prorated practice hours fall short of the requirement."""
    if periods is None:
        periods = [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 500)]
    ctx = seed_docs_submitted_renewal(api, periods, **context_kwargs)
    ctx["renewal"] = decide_audit(api, ctx["renewal_id"])
    return ctx


def seed_passed_audit_renewal(api: ApiClient,
                              periods: Optional[List[Dict[str, Any]]] = None,
                              **context_kwargs: Any) -> Dict[str, Any]:
    """A filing whose prorated practice hours meet the requirement."""
    if periods is None:
        periods = [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 1000)]
    ctx = seed_docs_submitted_renewal(api, periods, **context_kwargs)
    ctx["renewal"] = decide_audit(api, ctx["renewal_id"])
    return ctx


def seed_report(api: ApiClient, **context_kwargs: Any) -> Dict[str, Any]:
    """A queued notification report, produced by a revocation order."""
    ctx = seed_revocation_order(api, **context_kwargs)
    reports = reports_for_source(api, ctx["proceeding_id"])
    ctx["reports"] = reports
    ctx["report"] = reports[0] if reports else None
    ctx["report_id"] = reports[0]["id"] if reports else None
    return ctx


def change_report_status(api: ApiClient, report_id: str, to_status: str,
                         **overrides: Any) -> Dict[str, Any]:
    """Drive a report along QUEUED to TRANSMITTED to ACKNOWLEDGED, or to VOID."""
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return get_success_data(
        api.change_notification_report_status(report_id, payload, ADMIN)
    )


__all__ = [
    "RENEWAL_CLOCK",
    "SUFFICIENT_CE_MINUTES",
    "CLOCK_DEFAULT",
    "ADMIN",
    "ANALYST",
    "INVESTIGATOR",
    "PRESIDING",
    "COORDINATOR",
    "FIVE_MEMBER_PANEL",
    "THREE_MEMBER_PANEL",
    "set_clock",
    "seed_board",
    "seed_compact_board",
    "seed_second_board",
    "seed_program",
    "seed_nurse",
    "seed_application",
    "submit_application",
    "verify_application_qualification",
    "record_clean_screening",
    "mint_license",
    "license_version",
    "complaint_version",
    "reread_license",
    "reread_nurse",
    "reread_complaint",
    "reread_renewal",
    "reread_proceeding",
    "reread_agreement",
    "all_reports",
    "reports_for_source",
    "seed_board_program_nurse",
    "seed_screened_application",
    "seed_active_license",
    "seed_aprn_license",
    "seed_sibling_license",
    "change_status",
    "determine_privilege",
    "seed_complaint",
    "triage_complaint",
    "open_investigation",
    "seed_investigated_complaint",
    "seed_evidence_request",
    "record_production",
    "seed_produced_evidence_request",
    "complete_evidence",
    "seed_evidence_complete_complaint",
    "dispose_complaint",
    "seed_referred_complaint",
    "seed_atd_offered_complaint",
    "seed_dismissed_complaint",
    "seed_renewal",
    "seed_ce_record",
    "verify_ce_record",
    "pay_renewal",
    "submit_renewal",
    "verify_renewal_ce",
    "finalize_renewal",
    "seed_submitted_renewal",
    "seed_ce_verified_renewal",
    "seed_licensed_renewal_context",
    "run_sampling",
    "request_audit_docs",
    "submit_audit_docs",
    "decide_audit",
    "seed_selected_renewal",
    "seed_docs_requested_renewal",
    "seed_docs_submitted_renewal",
    "seed_monitoring_agreement",
    "execute_agreement",
    "record_monitoring_event",
    "seed_executed_agreement",
    "seed_active_agreement",
    "seed_breached_agreement",
    "seed_proceeding",
    "record_hearing_event",
    "cast_vote",
    "cast_votes",
    "issue_order",
    "seed_referred_context",
    "seed_noticed_proceeding",
    "seed_convened_proceeding",
    "seed_deliberating_proceeding",
    "seed_revocation_order",
    "seed_custodian_holds",
    "seed_expired_license",
    "seed_lapsed_license",
    "seed_renewed_license",
    "seed_denied_renewal",
    "seed_failed_audit_renewal",
    "seed_passed_audit_renewal",
    "seed_report",
    "change_report_status",
]
