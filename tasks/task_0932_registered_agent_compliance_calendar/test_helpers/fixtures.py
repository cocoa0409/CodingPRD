"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints:
the server is restarted before each test, so nothing survives between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    capture_payload,
    create_appointment_payload,
    create_beneficial_owner_payload,
    create_boi_report_payload,
    create_certificate_payload,
    create_client_payload,
    create_legal_entity_payload,
    create_name_clearance_payload,
    create_obligation_filing_payload,
    create_obligation_payload,
    create_payment_payload,
    create_sop_payload,
    create_standalone_filing_payload,
)
from .test_users import ADMIN, AGENT, OFFICER, SOP, make_compliance_officer_headers, \
    make_filing_agent_headers

OFFICER_USER_ID = "officer-1"
AGENT_USER_ID = "agent-9"


# --- Tier 0: primitives ------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def ops_run() -> dict:
    return get_success_data(api_client.advance_calendar(ADMIN))


def publish_rule(payload: dict) -> dict:
    return get_success_data(api_client.create_state_rule(payload, ADMIN))


def new_client(**overrides) -> dict:
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), ADMIN)
    )


def new_entity(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_legal_entity(
            client_id, create_legal_entity_payload(**overrides), OFFICER
        )
    )


def read_entity(entity_id: str) -> dict:
    return get_success_data(api_client.get_legal_entity(entity_id, OFFICER))


def read_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, OFFICER))


def read_obligation(obligation_id: str) -> dict:
    return get_success_data(api_client.get_compliance_obligation(obligation_id, OFFICER))


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_filing(filing_id, OFFICER))


def read_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, ADMIN))


def read_payment(payment_id: str) -> dict:
    return get_success_data(api_client.get_payment(payment_id, ADMIN))


def read_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.get_agent_appointment(appointment_id, OFFICER))


def read_sop(sop_document_id: str) -> dict:
    return get_success_data(api_client.get_sop_document(sop_document_id, SOP))


def new_home_registration(entity_id: str) -> dict:
    return get_success_data(api_client.create_home_registration(entity_id, OFFICER))


def propose_appointment(registration: dict, **overrides) -> dict:
    """Propose an agent against a registration, carrying its current version."""
    payload = create_appointment_payload(registration["version"], **overrides)
    return get_success_data(
        api_client.create_agent_appointment(registration["id"], payload, OFFICER)
    )


def accept_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.accept_agent_appointment(appointment_id, AGENT))


def activate_registration(registration_id: str) -> dict:
    return get_success_data(api_client.activate_registration(registration_id, AGENT))


def new_obligation(registration_id: str, obligation_type: str, period_year: int) -> dict:
    return get_success_data(
        api_client.create_compliance_obligation(
            registration_id, create_obligation_payload(obligation_type, period_year),
            OFFICER,
        )
    )


def new_certificate(registration_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_good_standing_certificate(
            registration_id, create_certificate_payload(**overrides), OFFICER
        )
    )


def new_clearance(entity_id: str, result: str = "AVAILABLE", record_payload=None,
                  **overrides) -> dict:
    """Open a name-availability search and record the jurisdiction's answer."""
    clearance = get_success_data(
        api_client.create_name_clearance(
            entity_id, create_name_clearance_payload(**overrides), OFFICER
        )
    )
    payload = record_payload if record_payload is not None else {"result": result}
    return get_success_data(
        api_client.record_name_clearance_result(clearance["id"], payload, AGENT)
    )


def new_payment(client_id: str, authorized_amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_payment(
            client_id, create_payment_payload(authorized_amount_cents), ADMIN
        )
    )


def capture(payment_id: str, amount: int, target_filing_id=None) -> dict:
    return get_success_data(
        api_client.capture_payment(
            payment_id, capture_payload(amount, target_filing_id), ADMIN
        )
    )


# --- Tier 1: state progression ----------------------------------------------

def setup_pending_home_registration(rule_payload: dict, client_overrides=None,
                                    entity_overrides=None) -> dict:
    """Publish one rule, register a client, create one legal entity and its HOME
    registration. The registration is left in PENDING."""
    publish_rule(rule_payload)
    client = new_client(**(client_overrides or {}))
    entity = new_entity(client["id"], **(entity_overrides or {}))
    registration = new_home_registration(entity["id"])
    return {"client": client, "entity": entity, "registration": registration}


def setup_active_home_registration(rule_payload: dict, client_overrides=None,
                                   entity_overrides=None,
                                   appointment_overrides=None) -> dict:
    """As above, then propose and accept an agent and activate the registration."""
    scene = setup_pending_home_registration(
        rule_payload, client_overrides, entity_overrides
    )
    appointment = propose_appointment(
        scene["registration"], **(appointment_overrides or {})
    )
    accept_appointment(appointment["id"])
    registration = activate_registration(scene["registration"]["id"])
    scene["appointment"] = appointment
    scene["registration"] = registration
    return scene


def setup_active_entity_and_registration(rule_payload: dict, client_overrides=None,
                                         entity_overrides=None) -> dict:
    """An ACTIVE registration under an entity whose lifecycle_status is ACTIVE."""
    scene = setup_active_home_registration(
        rule_payload, client_overrides, entity_overrides
    )
    scene["entity"] = get_success_data(
        api_client.activate_legal_entity(scene["entity"]["id"], OFFICER)
    )
    return scene


def qualify_foreign(entity_id: str, state_code: str, name_clearance_id: str,
                    good_standing_certificate_id: str) -> dict:
    payload = {
        "state_code": state_code,
        "name_clearance_id": name_clearance_id,
        "good_standing_certificate_id": good_standing_certificate_id,
    }
    return get_success_data(
        api_client.create_foreign_qualification(entity_id, payload, OFFICER)
    )


# --- Tier 2: filings and money ----------------------------------------------

def draft_obligation_filing(obligation: dict, filing_kind: str,
                            preparer_user_id: str = OFFICER_USER_ID, **overrides) -> dict:
    """Draft a filing against a calendar obligation, carrying the obligation's
    current version. Pass a freshly read obligation."""
    payload = create_obligation_filing_payload(
        filing_kind, obligation["version"], **overrides
    )
    return get_success_data(
        api_client.create_obligation_filing(
            obligation["id"], payload, make_compliance_officer_headers(preparer_user_id)
        )
    )


def draft_standalone_filing(registration_id: str, filing_kind: str,
                            preparer_user_id: str = OFFICER_USER_ID, **overrides) -> dict:
    payload = create_standalone_filing_payload(filing_kind, **overrides)
    return get_success_data(
        api_client.create_standalone_filing(
            registration_id, payload, make_compliance_officer_headers(preparer_user_id)
        )
    )


def submit_filing(filing_id: str, submitter_user_id: str = AGENT_USER_ID) -> dict:
    """Lodge a draft. The submitter must differ from the filing's preparer."""
    return get_success_data(
        api_client.submit_filing(filing_id, make_filing_agent_headers(submitter_user_id))
    )


def record_filing_outcome(filing_id: str, outcome: str, rejection_reason=None,
                          submitter_user_id: str = AGENT_USER_ID) -> dict:
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.record_filing_outcome(
            filing_id, payload, make_filing_agent_headers(submitter_user_id)
        )
    )


def fund_and_submit(client_id: str, filing: dict, submitter_user_id: str = AGENT_USER_ID,
                    target: bool = True) -> dict:
    """Authorize and capture exactly the filing's total_fee_cents, then submit it."""
    payment = new_payment(client_id, filing["total_fee_cents"])
    capture(
        payment["id"],
        filing["total_fee_cents"],
        filing["id"] if target else None,
    )
    submit_filing(filing["id"], submitter_user_id)
    return payment


# --- Tier 3: service of process ---------------------------------------------

def receive_sop(registration_id: str, sop_class: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sop_document(
            registration_id, create_sop_payload(sop_class, **overrides), SOP
        )
    )


def scan_sop(sop_document_id: str, not_our_entity=None) -> dict:
    payload = {} if not_our_entity is None else {"not_our_entity": not_our_entity}
    return get_success_data(api_client.scan_sop_document(sop_document_id, SOP, payload))


def forward_sop(sop_document_id: str) -> dict:
    return get_success_data(api_client.forward_sop_document(sop_document_id, SOP))


def escalate_sop(sop_document_id: str) -> dict:
    return get_success_data(api_client.escalate_sop_document(sop_document_id, SOP))


def setup_forwarded_sop(rule_payload: dict, sop_class: str = "ORDINARY",
                        received_at: str = "2026-06-05T14:00:00Z",
                        forwarded_at: str = "2026-06-08T10:00:00Z") -> dict:
    """An ACTIVE registration carrying one scanned-and-forwarded document."""
    scene = setup_active_home_registration(rule_payload)
    set_clock(received_at)
    document = receive_sop(scene["registration"]["id"], sop_class)
    scan_sop(document["id"])
    set_clock(forwarded_at)
    scene["document"] = forward_sop(document["id"])
    return scene


# --- Tier 4: beneficial ownership -------------------------------------------

def add_owner(entity_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_beneficial_owner(
            entity_id, create_beneficial_owner_payload(**overrides), OFFICER
        )
    )


def draft_boi_report(entity_id: str, report_kind: str, **overrides) -> dict:
    """Draft a report carrying the entity's freshly read version."""
    entity = read_entity(entity_id)
    payload = create_boi_report_payload(report_kind, entity["version"], **overrides)
    return get_success_data(api_client.create_boi_report(entity_id, payload, OFFICER))


def submit_boi_report(report_id: str) -> dict:
    return get_success_data(api_client.submit_boi_report(report_id, AGENT))


def record_boi_outcome(report_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.record_boi_outcome(report_id, {"outcome": outcome}, AGENT)
    )


def setup_filed_boi_entity(rule_payload: dict, formation_date: str = "2026-02-10") -> dict:
    """An ACTIVE entity and registration whose BOI axis has reached FILED."""
    scene = setup_active_entity_and_registration(
        rule_payload, entity_overrides={"formation_date": formation_date}
    )
    scene["owner"] = add_owner(scene["entity"]["id"], is_company_applicant=True)
    report = draft_boi_report(
        scene["entity"]["id"], "INITIAL", includes_company_applicant=True
    )
    submit_boi_report(report["id"])
    scene["report"] = record_boi_outcome(report["id"], "ACCEPTED")
    scene["entity"] = read_entity(scene["entity"]["id"])
    return scene


# --- Tier 5: delinquency, dissolution and reinstatement ----------------------

def setup_delinquent_registration(rule_payload: dict, period_year: int = 2027,
                                  delinquent_clock: str = "2027-04-15T00:00:00Z",
                                  activate_entity: bool = False) -> dict:
    """An ACTIVE registration with one ANNUAL_REPORT obligation driven to
    DELINQUENT by an ops-run, which takes the registration with it."""
    if activate_entity:
        scene = setup_active_entity_and_registration(rule_payload)
    else:
        scene = setup_active_home_registration(rule_payload)
    scene["obligation"] = new_obligation(
        scene["registration"]["id"], "ANNUAL_REPORT", period_year
    )
    set_clock(delinquent_clock)
    ops_run()
    scene["obligation"] = read_obligation(scene["obligation"]["id"])
    scene["registration"] = read_registration(scene["registration"]["id"])
    return scene


def setup_admin_dissolved_registration(rule_payload: dict,
                                       delinquent_clock: str = "2027-04-15T00:00:00Z",
                                       dissolution_clock: str = "2027-06-01T00:00:00Z") -> dict:
    """Carry a registration all the way to ADMIN_DISSOLVED through two ops-runs."""
    scene = setup_delinquent_registration(rule_payload, delinquent_clock=delinquent_clock)
    set_clock(dissolution_clock)
    ops_run()
    scene["registration"] = read_registration(scene["registration"]["id"])
    scene["obligation"] = read_obligation(scene["obligation"]["id"])
    return scene


def open_reinstatement_case(registration_id: str) -> dict:
    return get_success_data(
        api_client.create_reinstatement_case(registration_id, OFFICER)
    )


def assess_fees(case_id: str) -> dict:
    return get_success_data(api_client.assess_reinstatement_fees(case_id, OFFICER))


def read_case(case_id: str, registration_id: str) -> dict:
    """Re-read one reinstatement case through its registration's listing."""
    body, _meta = _paginate(
        api_client.list_reinstatement_cases(registration_id, OFFICER)
    )
    for row in body:
        if row["id"] == case_id:
            return row
    raise AssertionError(f"reinstatement case {case_id} not found on its registration")


def _paginate(response):
    data = get_success_data(response)
    return data, response.json()["meta"]


def setup_winding_down_entity(rule_payload: dict) -> dict:
    """An ACTIVE registration under an entity moved to WINDING_DOWN."""
    scene = setup_active_entity_and_registration(rule_payload)
    scene["entity"] = get_success_data(
        api_client.begin_wind_down(scene["entity"]["id"], OFFICER)
    )
    return scene
