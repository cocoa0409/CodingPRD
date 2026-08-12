"""Payload factories — one per writable endpoint body, input fields only (PRD §3)."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "MISSION_STATEMENT": "Advance charitable testing",
    "BUDGET_ESTIMATE_CENTS": 100000,
    "CONTACT_EMAIL": "contact@example.org",
    "DONOR_NAME": "Test Donor",
    "DONOR_EMAIL": "donor@example.org",
    "PAYMENT_METHOD": "CARD",
    "PURPOSE": "charitable spend",
    "PAYEE_NAME": "Test Payee",
    "SPEND_DATE": "2026-06-01",
    "WORKER_NAME": "Test Worker",
    "WORKER_EMAIL": "worker@example.org",
    "ENGAGEMENT_TYPE": "CONTRACTOR",
    "COMPENSATION_TYPE": "HOURLY",
    "RATE_CENTS": 5000,
    "START_DATE": "2026-06-01",
    "SUCCESSOR_NAME": "Successor Org",
    "SUCCESSOR_EIN": "12-3456789",
}


def create_application_payload(**overrides) -> dict:
    defaults = {
        "project_name": DEFAULTS["PROJECT_NAME"],
        "mission_statement": DEFAULTS["MISSION_STATEMENT"],
        "budget_estimate_cents": DEFAULTS["BUDGET_ESTIMATE_CENTS"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def mission_score_payload(action="ADVANCE", purpose_pts=50, benefit_pts=50,
                          capacity_pts=100, risk_pts=0, **overrides) -> dict:
    defaults = {
        "purpose_pts": purpose_pts,
        "benefit_pts": benefit_pts,
        "capacity_pts": capacity_pts,
        "risk_pts": risk_pts,
        "action": action,
    }
    defaults.update(overrides)
    return defaults


def compliance_decision_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100000,
        "donor_name": DEFAULTS["DONOR_NAME"],
        "donor_email": DEFAULTS["DONOR_EMAIL"],
        "payment_method": DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def request_refund_payload(amount_cents=1, reason="donor request", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


def decide_refund_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 5000,
        "purpose": DEFAULTS["PURPOSE"],
        "payee_type": "VENDOR",
        "payee_name": DEFAULTS["PAYEE_NAME"],
        "spend_date": DEFAULTS["SPEND_DATE"],
    }
    defaults.update(overrides)
    return defaults


def review_decision_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_staff_engagement_payload(**overrides) -> dict:
    defaults = {
        "worker_name": DEFAULTS["WORKER_NAME"],
        "worker_email": DEFAULTS["WORKER_EMAIL"],
        "engagement_type": DEFAULTS["ENGAGEMENT_TYPE"],
        "compensation_type": DEFAULTS["COMPENSATION_TYPE"],
        "rate_cents": DEFAULTS["RATE_CENTS"],
        "start_date": DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def classification_review_payload(approved_type="CONTRACTOR", rationale="vetted", **overrides) -> dict:
    defaults = {"approved_type": approved_type, "rationale": rationale}
    defaults.update(overrides)
    return defaults


def create_compliance_review_payload(review_type="TRIGGERED", **overrides) -> dict:
    defaults = {"review_type": review_type}
    defaults.update(overrides)
    return defaults


def issue_findings_payload(findings_count=1, severity_max="MEDIUM", **overrides) -> dict:
    defaults = {"findings_count": findings_count, "severity_max": severity_max}
    defaults.update(overrides)
    return defaults


def remediate_payload(remediated_count=1, **overrides) -> dict:
    defaults = {"remediated_count": remediated_count}
    defaults.update(overrides)
    return defaults


def create_risk_incident_payload(**overrides) -> dict:
    defaults = {
        "category": "LIABILITY",
        "severity": "LOW",
        "description": "test incident",
    }
    defaults.update(overrides)
    return defaults


def incident_transition_payload(action="TRIAGE", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_exit_plan_payload(**overrides) -> dict:
    defaults = {
        "successor_entity_name": DEFAULTS["SUCCESSOR_NAME"],
        "successor_ein": DEFAULTS["SUCCESSOR_EIN"],
        "reason": "spin off",
    }
    defaults.update(overrides)
    return defaults


def signoff_payload(party="SPONSOR_BOARD", **overrides) -> dict:
    defaults = {"party": party}
    defaults.update(overrides)
    return defaults


def create_grant_tranche_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100000,
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "purpose": "restricted grant purpose",
    }
    defaults.update(overrides)
    return defaults


def close_tranche_payload(report_note="final report", **overrides) -> dict:
    defaults = {"report_note": report_note}
    defaults.update(overrides)
    return defaults


def fund_adjustment_payload(expected_fund_account_version, amount_cents, memo="adjustment", **overrides) -> dict:
    defaults = {
        "expected_fund_account_version": expected_fund_account_version,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    defaults.update(overrides)
    return defaults


def amend_agreement_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {"expected_agreement_version": expected_agreement_version}
    defaults.update(overrides)
    return defaults


def close_period_payload(period_start="2026-05-01", period_end="2026-05-31", **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
