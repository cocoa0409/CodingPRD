"""Composite setup helpers for the APS API.

Each helper builds preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server with an empty DB before every test). Setup
calls use get_success_data() so that setup failures surface as clear errors.

All roles are opaque (PRD 2.1), so the shared TEST_USERS headers are used
throughout — there is no ownership threading.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_client_payload,
    create_report_payload,
    create_account_payload,
    create_facility_payload,
    risk_assessment_payload,
    create_placement_payload,
    create_freeze_payload,
)

INTAKE = TEST_USERS["intake_worker_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------- Primitive builders ----------------

def set_clock(iso: str):
    """Set the server logical clock to the given ISO instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def new_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), INTAKE))


def new_account(client_id: str, total_balance_cents: int = 500_000, **overrides) -> dict:
    payload = create_account_payload(client_id, total_balance_cents=total_balance_cents, **overrides)
    return get_success_data(api_client.create_account(payload, INTAKE))


def new_facility(total_beds: int = 2, name: str = "Test Facility") -> dict:
    return get_success_data(api_client.create_facility(create_facility_payload(name=name, total_beds=total_beds), ADMIN))


def new_report(client_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_report(create_report_payload(client_id, **overrides), INTAKE))


def get_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, CASEWORKER))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, SUPERVISOR))


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, CASEWORKER))


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, CASEWORKER))


def get_investigation(investigation_id: str) -> dict:
    return get_success_data(api_client.get_investigation(investigation_id, CASEWORKER))


def get_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, CASEWORKER))


def get_freeze(freeze_id: str) -> dict:
    return get_success_data(api_client.get_freeze(freeze_id, CASEWORKER))


# ---------------- Assessment helpers ----------------

def add_capacity_determination(client_id: str, determination: str) -> dict:
    return get_success_data(
        api_client.capacity_determination(client_id, {"determination": determination}, CASEWORKER)
    )


def add_comprehensive_assessment(client_id: str, isolation_level=3, cognitive_impairment_level=3,
                                 financial_vulnerability_level=2, caregiver_dependency_level=2,
                                 prior_report_count=1) -> dict:
    """Read the client's current version, then submit a COMPREHENSIVE assessment."""
    version = get_client(client_id)["version"]
    payload = risk_assessment_payload(
        "COMPREHENSIVE", version,
        isolation_level=isolation_level,
        cognitive_impairment_level=cognitive_impairment_level,
        financial_vulnerability_level=financial_vulnerability_level,
        caregiver_dependency_level=caregiver_dependency_level,
        prior_report_count=prior_report_count,
    )
    return get_success_data(api_client.create_risk_assessment(client_id, payload, CASEWORKER))


def add_preliminary_assessment(client_id: str, **levels) -> dict:
    version = get_client(client_id)["version"]
    payload = risk_assessment_payload("PRELIMINARY", version, **levels)
    return get_success_data(api_client.create_risk_assessment(client_id, payload, CASEWORKER))


# ---------------- Screening / case lifecycle ----------------

def screen_in(report_id: str) -> dict:
    """Screen a RECEIVED report IN; returns the updated Report (carrying case_id)."""
    return get_success_data(api_client.screen_report(report_id, {"decision": "SCREEN_IN"}, SUPERVISOR))


def screen_out(report_id: str, reason: str = "does not meet APS criteria") -> dict:
    return get_success_data(
        api_client.screen_report(report_id, {"decision": "SCREEN_OUT", "screen_out_reason": reason}, SUPERVISOR)
    )


def create_screened_in_case(allegation_types=None, priority="PRIORITY", client_overrides=None) -> dict:
    """Client + RECEIVED report + SCREEN_IN. Returns dict with client, report,
    case_id, and the freshly-read case (status OPEN)."""
    client = new_client(**(client_overrides or {}))
    report = new_report(
        client["id"],
        allegation_types=allegation_types or ["NEGLECT"],
        priority=priority,
    )
    screened = screen_in(report["id"])
    case_id = screened["case_id"]
    return {
        "client": client,
        "report": screened,
        "case_id": case_id,
        "case": get_case(case_id),
    }


def open_investigation(case_id: str) -> dict:
    return get_success_data(api_client.create_investigation({"case_id": case_id}, CASEWORKER))


def create_case_under_investigation(allegation_types=None, priority="PRIORITY", client_overrides=None) -> dict:
    """Screened-in case + open investigation (case now UNDER_INVESTIGATION)."""
    base = create_screened_in_case(allegation_types, priority, client_overrides)
    investigation = open_investigation(base["case_id"])
    base["investigation"] = investigation
    base["case"] = get_case(base["case_id"])
    return base


def create_findings_submitted(allegation_types=None, priority="PRIORITY",
                              comp_levels=None, client_overrides=None) -> dict:
    """Case UNDER_INVESTIGATION + COMPREHENSIVE assessment + submit-findings.
    Investigation ends in FINDINGS_SUBMITTED."""
    base = create_case_under_investigation(allegation_types, priority, client_overrides)
    add_comprehensive_assessment(base["client"]["id"], **(comp_levels or {}))
    inv_id = base["investigation"]["id"]
    get_success_data(api_client.submit_findings(inv_id, {"finding_summary": "draft findings"}, CASEWORKER))
    base["investigation"] = get_investigation(inv_id)
    base["client"] = get_client(base["client"]["id"])
    return base


def create_case_ready_for_closure(allegation_types=None, priority="PRIORITY",
                                  disposition="UNSUBSTANTIATED", comp_levels=None,
                                  client_overrides=None) -> dict:
    """Full path to a DISPOSED investigation / READY_FOR_CLOSURE case /
    SERVICES_PENDING client."""
    base = create_findings_submitted(allegation_types, priority, comp_levels, client_overrides)
    inv_id = base["investigation"]["id"]
    get_success_data(api_client.dispose_investigation(inv_id, {"disposition": disposition}, SUPERVISOR))
    base["investigation"] = get_investigation(inv_id)
    base["case"] = get_case(base["case_id"])
    base["client"] = get_client(base["client"]["id"])
    return base


# ---------------- Freeze helpers ----------------

def create_active_freeze(case_id: str, account_id: str, flagged_amount_cents: int,
                         freeze_start: str, freeze_end: str, as_role=CASEWORKER) -> dict:
    payload = create_freeze_payload(case_id, account_id, flagged_amount_cents, freeze_start, freeze_end)
    return get_success_data(api_client.create_freeze(payload, as_role))


def lift_freeze(freeze_id: str) -> dict:
    return get_success_data(api_client.lift_freeze(freeze_id, SUPERVISOR))


def create_financial_case_with_account(total_balance_cents: int = 500_000, clock: str = "2026-06-01T00:00:00Z"):
    """Clock set + client + account + screened-in FINANCIAL_EXPLOITATION case
    UNDER_INVESTIGATION. Returns dict with client, account, case_id, investigation."""
    set_clock(clock)
    client = new_client()
    account = new_account(client["id"], total_balance_cents=total_balance_cents)
    report = new_report(client["id"], allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    screened = screen_in(report["id"])
    case_id = screened["case_id"]
    investigation = open_investigation(case_id)
    return {
        "client": client,
        "account": account,
        "report": screened,
        "case_id": case_id,
        "investigation": investigation,
    }


# ---------------- Placement helpers ----------------

def create_eligible_placement_case(clock: str = "2026-06-01T00:00:00Z", total_beds: int = 2,
                                   make_eligible="IMPAIRED"):
    """Clock + facility + screened-in case whose client is placement-eligible.

    make_eligible == "IMPAIRED": capacity-determine the client IMPAIRED.
    make_eligible == "HIGH": give the client a COMPREHENSIVE HIGH risk_level
    (capacity left UNKNOWN). Returns dict with client, facility, case_id,
    investigation (present only for the HIGH path, which needs a case
    UNDER_INVESTIGATION to run the assessment)."""
    set_clock(clock)
    facility = new_facility(total_beds=total_beds)
    result = {"facility": facility}
    if make_eligible == "HIGH":
        base = create_case_under_investigation(
            allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
        add_comprehensive_assessment(
            base["client"]["id"],
            isolation_level=3, cognitive_impairment_level=3,
            financial_vulnerability_level=2, caregiver_dependency_level=2,
            prior_report_count=1)
        result.update(base)
        result["client"] = get_client(base["client"]["id"])
    else:
        base = create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
        add_capacity_determination(base["client"]["id"], "IMPAIRED")
        result.update(base)
        result["client"] = get_client(base["client"]["id"])
    return result


def create_placement(case_id: str, facility_id: str, start_at: str, end_at: str,
                     court_authorized: bool = True) -> dict:
    payload = create_placement_payload(
        case_id, facility_id, start_at, end_at, court_authorized=court_authorized)
    return get_success_data(api_client.create_placement(payload, CASEWORKER))
