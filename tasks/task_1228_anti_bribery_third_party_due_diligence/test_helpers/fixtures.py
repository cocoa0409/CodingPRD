"""Composite setup helpers.

Each helper drives one multi-step onboarding/workflow preamble through the
public API so tests can start from the exact system state their claim needs.
All setup calls use get_success_data so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion deep in a test.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STARTUP_CLOCK
from .factories import (
    audit_exercise_payload,
    certification_payload,
    contract_payload,
    country_profile_payload,
    gift_entry_payload,
    payment_request_payload,
    policy_payload,
    questionnaire_answers_payload,
    red_flag_payload,
    third_party_payload,
)
from .test_users import (
    SPONSOR_1_ID,
    admin_headers,
    analyst_headers,
    audit_headers,
    finance_headers,
    officer_headers,
    sponsor_headers,
)


def _ok(response, step: str):
    """Extract data from a setup response or fail with a clear message."""
    try:
        return get_success_data(response)
    except Exception as exc:  # pragma: no cover - setup diagnostics
        pytest.fail(f"Setup failed at step '{step}': {exc} — body: {response.text}")


# ---------------------------------------------------------------------------
# Tier 1: risk basis (clock + country profile + active policy)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = STARTUP_CLOCK) -> dict:
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, admin_headers()), "set_clock")


def create_country(country_code: str = "CH", cpi_score: int = 80, sanctioned=None) -> dict:
    payload = country_profile_payload(country_code=country_code, cpi_score=cpi_score)
    if sanctioned is not None:
        payload["sanctioned"] = sanctioned
    return _ok(api_client.create_country_profile(payload, admin_headers()), "create_country")


def create_active_policy(**overrides) -> dict:
    """Create a scoring policy and activate it (OCC on the policy version)."""
    policy = _ok(api_client.create_policy(policy_payload(**overrides), admin_headers()), "create_policy")
    activated = _ok(
        api_client.activate_policy(
            policy["id"], {"expected_policy_version": policy["version"]}, admin_headers()
        ),
        "activate_policy",
    )
    return activated


def setup_risk_basis(country_code: str = "CH", cpi_score: int = 80, sanctioned=None,
                     clock: str = STARTUP_CLOCK, **policy_overrides) -> dict:
    """Clock set + country profile + one ACTIVE policy.

    Returns {"country": <CountryRiskProfile>, "policy": <RiskScoringPolicy>}.
    """
    set_clock(clock)
    country = create_country(country_code, cpi_score, sanctioned)
    policy = create_active_policy(**policy_overrides)
    return {"country": country, "policy": policy}


# ---------------------------------------------------------------------------
# Tier 1/2: third-party lifecycle walkers
# ---------------------------------------------------------------------------

def create_draft_third_party(country_code: str = "CH", industry: str = "TECHNOLOGY",
                             touchpoint: str = "NONE", sponsor_id: str = SPONSOR_1_ID,
                             legal_name: str = None) -> dict:
    payload = third_party_payload(country_code=country_code, industry=industry,
                                  government_touchpoint=touchpoint)
    if legal_name is not None:
        payload["legal_name"] = legal_name
    return _ok(api_client.create_third_party(payload, sponsor_headers(sponsor_id)),
               "create_third_party")


def submit_third_party(tp_id: str, sponsor_id: str = SPONSOR_1_ID) -> dict:
    return _ok(api_client.submit_third_party(tp_id, sponsor_headers(sponsor_id)),
               "submit_third_party")


def get_check_ids(tp_id: str) -> list:
    """Return the party's three screening check ids in creation order (PEP, AM, SAN)."""
    data = _ok(api_client.list_screening_checks(tp_id, officer_headers()), "list_screening_checks")
    checks = data if isinstance(data, list) else data.get("data", data)
    assert isinstance(checks, list) and len(checks) == 3, (
        f"Setup failed: expected 3 screening checks, got {checks!r}"
    )
    return [c["id"] for c in checks]


def disposition_check(check_id: str, outcome: str, match_detail: str = None) -> dict:
    payload = {"outcome": outcome}
    if match_detail is not None:
        payload["match_detail"] = match_detail
    return _ok(api_client.disposition_screening_check(check_id, payload, analyst_headers()),
               f"disposition_check({outcome})")


def clear_all_checks(tp_id: str) -> list:
    """CLEAR all three screening checks. Returns the check ids in creation order."""
    ids = get_check_ids(tp_id)
    for cid in ids:
        disposition_check(cid, "CLEAR")
    return ids


def get_third_party(tp_id: str) -> dict:
    return _ok(api_client.get_third_party(tp_id, officer_headers()), "get_third_party")


def issue_questionnaire(tp_id: str) -> dict:
    """Issue a questionnaire carrying the party's current version (OCC)."""
    current = get_third_party(tp_id)
    return _ok(
        api_client.issue_questionnaire(
            tp_id, {"expected_third_party_version": current["version"]}, officer_headers()
        ),
        "issue_questionnaire",
    )


def submit_questionnaire(q_id: str, sponsor_id: str = SPONSOR_1_ID,
                         government_ownership_pct: int = 0,
                         has_facilitation_payments: bool = False,
                         uses_sub_agents: bool = False) -> dict:
    return _ok(
        api_client.submit_questionnaire(
            q_id,
            questionnaire_answers_payload(
                government_ownership_pct=government_ownership_pct,
                has_facilitation_payments=has_facilitation_payments,
                uses_sub_agents=uses_sub_agents,
            ),
            sponsor_headers(sponsor_id),
        ),
        "submit_questionnaire",
    )


def accept_questionnaire(q_id: str) -> dict:
    return _ok(api_client.accept_questionnaire(q_id, officer_headers()), "accept_questionnaire")


def advance_to_dd_review(tp_id: str, sponsor_id: str = SPONSOR_1_ID) -> dict:
    """Submit + CLEAR all three checks so the party auto-advances to DD_REVIEW."""
    submit_third_party(tp_id, sponsor_id)
    clear_all_checks(tp_id)
    tp = get_third_party(tp_id)
    assert tp["onboarding_status"] == "DD_REVIEW", (
        f"Setup failed: expected DD_REVIEW after clearing checks, got {tp['onboarding_status']}"
    )
    return tp


def walk_to_questionnaire_accepted(tp_id: str, sponsor_id: str = SPONSOR_1_ID, **answers) -> dict:
    """From DD_REVIEW: issue + submit + accept the questionnaire. Returns it."""
    q = issue_questionnaire(tp_id)
    submit_questionnaire(q["id"], sponsor_id, **answers)
    return accept_questionnaire(q["id"])


def approve_third_party(tp_id: str) -> dict:
    return _ok(api_client.approve_third_party(tp_id, officer_headers()), "approve_third_party")


def walk_to_approved(tp_id: str, sponsor_id: str = SPONSOR_1_ID, **answers) -> dict:
    """Full onboarding: DD_REVIEW -> questionnaire ACCEPTED -> APPROVED."""
    walk_to_questionnaire_accepted(tp_id, sponsor_id, **answers)
    return approve_third_party(tp_id)


def setup_third_party_in_state(target: str, country_code: str = "CH", cpi_score: int = 80,
                               industry: str = "TECHNOLOGY", touchpoint: str = "NONE",
                               sponsor_id: str = SPONSOR_1_ID, sanctioned=None,
                               legal_name: str = None, clock: str = STARTUP_CLOCK,
                               **policy_overrides) -> dict:
    """Build the risk basis and walk a new third party to the requested state.

    target: DRAFT | SCREENING | DD_REVIEW | APPROVED
    Returns {"policy": ..., "third_party": ...} with the party in `target`.
    """
    policy = setup_risk_basis(country_code, cpi_score, sanctioned, clock,
                              **policy_overrides)["policy"]
    tp = create_draft_third_party(country_code, industry, touchpoint, sponsor_id, legal_name)
    if target == "DRAFT":
        return {"policy": policy, "third_party": tp}
    tp = submit_third_party(tp["id"], sponsor_id)
    if target == "SCREENING":
        return {"policy": policy, "third_party": tp}
    # Already submitted above; only need to clear checks to reach DD_REVIEW.
    clear_all_checks(tp["id"])
    tp = get_third_party(tp["id"])
    assert tp["onboarding_status"] == "DD_REVIEW", (
        f"Setup failed: expected DD_REVIEW after clearing checks, got {tp['onboarding_status']}"
    )
    if target == "DD_REVIEW":
        return {"policy": policy, "third_party": tp}
    tp = walk_to_approved(tp["id"], sponsor_id)
    if target == "APPROVED":
        return {"policy": policy, "third_party": tp}
    raise ValueError(f"unsupported target state: {target}")


# ---------------------------------------------------------------------------
# Tier 2/3: contract + certification + payment composite setups
# ---------------------------------------------------------------------------

def create_verified_certification(tp_id: str, sponsor_id: str = SPONSOR_1_ID,
                                  cert_type: str = "ANNUAL_ABAC") -> dict:
    cert = _ok(api_client.create_certification(tp_id, certification_payload(cert_type=cert_type),
                                               officer_headers()), "create_certification")
    _ok(api_client.submit_certification(cert["id"], {"document_ref": "s3://certs/doc.pdf"},
                                        sponsor_headers(sponsor_id)), "submit_certification")
    return _ok(api_client.verify_certification(cert["id"], officer_headers()),
               "verify_certification")


def create_draft_contract(tp_id: str, sponsor_id: str = SPONSOR_1_ID,
                          value_cents: int = 500000,
                          start_date: str = "2026-05-02", end_date: str = "2027-05-01") -> dict:
    return _ok(
        api_client.create_contract(
            tp_id,
            contract_payload(contract_value_cents=value_cents,
                             start_date=start_date, end_date=end_date),
            sponsor_headers(sponsor_id),
        ),
        "create_contract",
    )


def setup_active_contract(tp_id: str, sponsor_id: str = SPONSOR_1_ID, value_cents: int = 500000,
                          clauses=("ABAC",), start_date: str = "2026-05-02",
                          end_date: str = "2027-05-01") -> dict:
    """Draft contract -> attach clauses -> VERIFIED certification -> ACTIVE."""
    contract = create_draft_contract(tp_id, sponsor_id, value_cents, start_date, end_date)
    _ok(api_client.attach_clauses(contract["id"], {"clause_codes": list(clauses)},
                                  sponsor_headers(sponsor_id)), "attach_clauses")
    create_verified_certification(tp_id, sponsor_id)
    return _ok(api_client.activate_contract(contract["id"], officer_headers()),
               "activate_contract")


def create_payment(contract_id: str, sponsor_id: str = SPONSOR_1_ID,
                   payment_type: str = "COMMISSION", amount_cents: int = 50000,
                   enhanced_review_evidence=None) -> dict:
    payload = payment_request_payload(payment_type=payment_type, amount_cents=amount_cents)
    if enhanced_review_evidence is not None:
        payload["enhanced_review_evidence"] = enhanced_review_evidence
    return _ok(api_client.create_payment_request(contract_id, payload,
                                                 sponsor_headers(sponsor_id)),
               "create_payment_request")


def approve_payment(pay_id: str, finance_user: str) -> dict:
    return _ok(api_client.approve_payment(pay_id, finance_headers(finance_user)),
               "approve_payment")


def setup_approved_with_active_contract(country_code: str = "CH", cpi_score: int = 80,
                                        industry: str = "TECHNOLOGY", touchpoint: str = "NONE",
                                        sponsor_id: str = SPONSOR_1_ID,
                                        value_cents: int = 500000, clauses=("ABAC",),
                                        start_date: str = "2026-05-02",
                                        end_date: str = "2027-05-01") -> dict:
    """APPROVED third party + ACTIVE contract with a VERIFIED certification."""
    ctx = setup_third_party_in_state("APPROVED", country_code, cpi_score, industry,
                                     touchpoint, sponsor_id)
    contract = setup_active_contract(ctx["third_party"]["id"], sponsor_id, value_cents,
                                     clauses, start_date, end_date)
    ctx["contract"] = contract
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: red flags and escalation
# ---------------------------------------------------------------------------

def create_red_flag(tp_id: str, officer_id: str, severity: str = "MEDIUM",
                    description: str = "manual review finding") -> dict:
    return _ok(
        api_client.create_red_flag(
            tp_id, red_flag_payload(severity=severity, description=description),
            officer_headers(officer_id),
        ),
        "create_red_flag",
    )


def escalate_flag(flag_id: str, officer_id: str) -> dict:
    return _ok(
        api_client.disposition_red_flag(flag_id, {"disposition": "ESCALATE"},
                                        officer_headers(officer_id)),
        "escalate_flag",
    )


def get_open_case_id(tp_id: str) -> str:
    data = _ok(api_client.list_escalation_cases(tp_id, officer_headers()),
               "list_escalation_cases")
    cases = data if isinstance(data, list) else data.get("data", data)
    assert isinstance(cases, list) and cases, f"Setup failed: no escalation case on {tp_id}"
    return cases[0]["id"]


def setup_escalated_case(tp_id: str, officer_id: str, severity: str = "MEDIUM") -> dict:
    """Raise + escalate a flag; returns {"flag":..., "case_id":...}."""
    flag = create_red_flag(tp_id, officer_id, severity)
    escalate_flag(flag["id"], officer_id)
    return {"flag": flag, "case_id": get_open_case_id(tp_id)}


# ---------------------------------------------------------------------------
# Tier 2: gift registry
# ---------------------------------------------------------------------------

def create_gift(tp_id: str, sponsor_id: str = SPONSOR_1_ID, **overrides) -> dict:
    return _ok(api_client.create_gift_entry(tp_id, gift_entry_payload(**overrides),
                                            sponsor_headers(sponsor_id)),
               "create_gift_entry")


def approve_gift(entry_id: str, evidence: bool = False) -> dict:
    payload = {"enhanced_review_evidence": True} if evidence else {}
    return _ok(api_client.approve_gift_entry(entry_id, payload, officer_headers()),
               "approve_gift_entry")


def create_approved_gift(tp_id: str, sponsor_id: str = SPONSOR_1_ID, evidence: bool = False,
                         **overrides) -> dict:
    entry = create_gift(tp_id, sponsor_id, **overrides)
    return approve_gift(entry["id"], evidence=evidence)


# ---------------------------------------------------------------------------
# Tier 5: audit exercises
# ---------------------------------------------------------------------------

def create_audit(tp_id: str, start: str = "2026-05-15", end: str = "2026-05-30") -> dict:
    return _ok(api_client.create_audit_exercise(tp_id, audit_exercise_payload(
        fieldwork_start_date=start, fieldwork_end_date=end), audit_headers()),
        "create_audit_exercise")


def setup_audit_in_fieldwork(tp_id: str, start: str = "2026-05-15",
                             end: str = "2026-05-30", fieldwork_day: str = "2026-05-15") -> dict:
    """Notice an audit, move the clock into the notice window, begin fieldwork."""
    audit = create_audit(tp_id, start, end)
    set_clock(f"{fieldwork_day}T00:00:00Z")
    return _ok(api_client.begin_fieldwork(audit["id"], audit_headers()), "begin_fieldwork")
