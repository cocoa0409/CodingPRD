"""Composite setup helpers for the School-Based Medicaid Billing (LEA) API.

Most test claims require the system in a multi-step state — a consented student,
a credentialed provider, an active authorization, a verified log, an attached
claim, a closed RMTS quarter, and so on. These helpers encapsulate those chains
so tests focus on assertions. All setup calls use the lenient get_success_data()
so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_service_provider_headers
from .factories import (
    create_student_payload, create_provider_payload, create_credential_payload,
    create_authorization_payload, create_consent_payload, create_service_log_payload,
    create_claim_payload, create_quarter_payload, create_moment_payload,
    create_settlement_payload,
)


def _mc():
    return TEST_USERS["medicaid_coordinator_headers"]


def _bc():
    return TEST_USERS["billing_coordinator_headers"]


def _sr():
    return TEST_USERS["state_reviewer_headers"]


# --- Clock -------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server logical clock to the given ISO instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, _mc()))


# --- Single-entity builders --------------------------------------------------
def create_student(**overrides) -> dict:
    return get_success_data(api_client.create_student(create_student_payload(**overrides), _mc()))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), _mc()))


def create_credential(provider_id, activate=True, **overrides) -> dict:
    """Create a credential (PENDING) and, by default, activate it to ACTIVE."""
    cred = get_success_data(api_client.create_credential(
        create_credential_payload(provider_id=provider_id, **overrides), _mc()))
    if activate:
        cred = get_success_data(api_client.activate_credential(cred["id"], _mc()))
    return cred


def create_authorization(student_id, activate=True, **overrides) -> dict:
    """Create an authorization (DRAFT) and, by default, activate it to ACTIVE."""
    auth = get_success_data(api_client.create_authorization(
        create_authorization_payload(student_id=student_id, **overrides), _mc()))
    if activate:
        auth = get_success_data(api_client.activate_authorization(auth["id"], _mc()))
    return auth


def create_consent(student_id, grant=True, consent_type="BILLING", **overrides) -> dict:
    """Create a consent (PENDING) and, by default, grant it to GRANTED."""
    con = get_success_data(api_client.create_consent(
        create_consent_payload(student_id=student_id, consent_type=consent_type, **overrides), _mc()))
    if grant:
        con = get_success_data(api_client.grant_consent(con["id"], _mc()))
    return con


# --- Service-log builders ----------------------------------------------------
def create_logged_log(auth_id, provider_id, student_id, **overrides) -> dict:
    """Create a LOGGED service log (self-logged by the owning provider)."""
    payload = create_service_log_payload(
        iep_authorization_id=auth_id, provider_id=provider_id, student_id=student_id, **overrides)
    return get_success_data(api_client.create_service_log(payload, make_service_provider_headers(provider_id)))


def document_log(log_id, provider_id, note="SOAP note") -> dict:
    return get_success_data(api_client.document_service_log(
        log_id, {"documentation_note": note}, make_service_provider_headers(provider_id)))


def verify_log(log_id) -> dict:
    return get_success_data(api_client.verify_service_log(log_id, _bc()))


def create_documented_log(auth_id, provider_id, student_id, note="SOAP note", **overrides) -> dict:
    log = create_logged_log(auth_id, provider_id, student_id, **overrides)
    return document_log(log["id"], provider_id, note)


def create_verified_log(auth_id, provider_id, student_id, note="SOAP note", **overrides) -> dict:
    log = create_logged_log(auth_id, provider_id, student_id, **overrides)
    document_log(log["id"], provider_id, note)
    return verify_log(log["id"])


# --- Eligibility context (consented student + credentialed active provider) --
def setup_billing_context(clock="2026-03-15T00:00:00Z",
                          student_overrides=None, cred_overrides=None,
                          auth_overrides=None, grant_consent=True) -> dict:
    """Active student + provider + ACTIVE credential + ACTIVE authorization +
    (by default) a GRANTED BILLING consent. Returns a dict with each entity."""
    if clock:
        set_clock(clock)
    student = create_student(**(student_overrides or {}))
    provider = create_provider()
    credential = create_credential(provider["id"], **(cred_overrides or {}))
    authorization = create_authorization(student["id"], **(auth_overrides or {}))
    consent = create_consent(student["id"], grant=grant_consent)
    return {
        "student": student,
        "provider": provider,
        "credential": credential,
        "authorization": authorization,
        "consent": consent,
    }


# --- Claim builders ----------------------------------------------------------
def create_draft_claim(student_id, service_month="2026-03") -> dict:
    return get_success_data(api_client.create_claim(
        create_claim_payload(student_id=student_id, service_month=service_month), _bc()))


def attach_log(claim_id, log_id) -> dict:
    return get_success_data(api_client.attach_log(claim_id, {"service_log_id": log_id}, _bc()))


def setup_claim_with_verified_log(clock="2026-03-15T00:00:00Z",
                                  service_date="2026-03-01",
                                  start_time="2026-03-01T09:00:00Z",
                                  end_time="2026-03-01T09:40:00Z",
                                  delivered_minutes=40,
                                  service_month="2026-03",
                                  cred_overrides=None, auth_overrides=None) -> dict:
    """Full chain to a DRAFT claim with one attached (CLAIMED) verified log.

    Returns a dict with student/provider/credential/authorization/consent, the
    verified `log`, and the `claim` after attach.
    """
    ctx = setup_billing_context(clock=clock, cred_overrides=cred_overrides, auth_overrides=auth_overrides)
    log = create_verified_log(
        ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
        service_date=service_date, start_time=start_time, end_time=end_time,
        delivered_minutes=delivered_minutes)
    claim = create_draft_claim(ctx["student"]["id"], service_month=service_month)
    claim = attach_log(claim["id"], log["id"])
    ctx["log"] = log
    ctx["claim"] = claim
    return ctx


def submit_claim(claim_id) -> dict:
    return get_success_data(api_client.submit_claim(claim_id, _bc()))


def approve_claim(claim_id) -> dict:
    return get_success_data(api_client.adjudicate_claim(claim_id, {"outcome": "APPROVE"}, _sr()))


def deny_claim(claim_id, denial_reason="DOC_INCOMPLETE") -> dict:
    return get_success_data(api_client.adjudicate_claim(
        claim_id, {"outcome": "DENY", "denial_reason": denial_reason}, _sr()))


def void_claim(claim_id) -> dict:
    return get_success_data(api_client.void_claim(claim_id, _bc()))


# --- RMTS builders -----------------------------------------------------------
def create_quarter(fiscal_quarter="2026-Q1") -> dict:
    return get_success_data(api_client.create_quarter(create_quarter_payload(fiscal_quarter=fiscal_quarter), _mc()))


def add_coded_moment(quarter_id, provider_id, category, timestamp) -> dict:
    """Generate a moment, respond (owner), and code it into the given category."""
    moment = get_success_data(api_client.create_moment(
        create_moment_payload(rmts_quarter_id=quarter_id, provider_id=provider_id, moment_timestamp=timestamp), _mc()))
    get_success_data(api_client.respond_moment(
        moment["id"], {"activity_response": "response"}, make_service_provider_headers(provider_id)))
    return get_success_data(api_client.code_moment(
        moment["id"], {"activity_category": category}, _mc()))


def create_quarter_with_coded_moments(categories, provider_id=None, fiscal_quarter="2026-Q1") -> dict:
    """Open a quarter and add one CODED moment per category (not closed).

    Eligible categories are DIRECT_MEDICAL and MEDICAL_ADMIN. Returns a dict with
    quarter_id, provider_id, and the list of coded moments.
    """
    if provider_id is None:
        provider_id = create_provider(discipline="OT")["id"]
    quarter = create_quarter(fiscal_quarter)
    moments = []
    for i, cat in enumerate(categories):
        ts = f"2026-02-{i + 1:02d}T10:00:00Z"
        moments.append(add_coded_moment(quarter["id"], provider_id, cat, ts))
    return {"quarter_id": quarter["id"], "provider_id": provider_id, "moments": moments}


def close_quarter(quarter_id) -> dict:
    return get_success_data(api_client.close_quarter(quarter_id, _mc()))


def setup_closed_quarter_half_ratio(fiscal_quarter="2026-Q1", clock="2026-03-15T00:00:00Z",
                                    provider_id=None) -> dict:
    """A CLOSED quarter with 4 coded moments, 2 eligible => ratio 0.5.

    Returns a dict with quarter_id, provider_id, the CLOSED quarter object, and
    quarter_version (the version captured immediately after close).
    """
    if clock:
        set_clock(clock)
    info = create_quarter_with_coded_moments(
        ["DIRECT_MEDICAL", "MEDICAL_ADMIN", "NON_MEDICAL", "GENERAL_ADMIN"],
        provider_id=provider_id, fiscal_quarter=fiscal_quarter)
    closed = close_quarter(info["quarter_id"])
    info["quarter"] = closed
    info["quarter_version"] = closed["version"]
    return info


# --- Cost settlement builders ------------------------------------------------
def create_settlement(quarter_id, expected_version, certified_cost_cents=1000000,
                      iep_ratio_bps=4000, fmap_bps=5000, interim_paid_cents=0) -> dict:
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(
            rmts_quarter_id=quarter_id, certified_cost_cents=certified_cost_cents,
            iep_ratio_bps=iep_ratio_bps, fmap_bps=fmap_bps,
            interim_paid_cents=interim_paid_cents, expected_rmts_quarter_version=expected_version), _mc()))
