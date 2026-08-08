"""Payload factories — one per entity, input fields only."""


def create_subject_payload(**overrides) -> dict:
    payload = {
        "name": "Test Subject",
        "ssn_last4": "1234",
        "primary_program": "SNAP",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(subject_id, **overrides) -> dict:
    payload = {
        "subject_id": subject_id,
        "program": "SNAP",
        "source": "DATA_MATCH",
        "allegation_summary": "Alleged over-issuance",
    }
    payload.update(overrides)
    return payload


def decide_referral_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_case_payload(referral_id, **overrides) -> dict:
    payload = {"referral_id": referral_id}
    payload.update(overrides)
    return payload


def assign_case_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def adjudicate_case_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_evidence_payload(**overrides) -> dict:
    payload = {
        "kind": "DOCUMENT",
        "description": "Evidence item",
    }
    payload.update(overrides)
    return payload


def create_overpayment_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "claim_type": "IHE",
    }
    payload.update(overrides)
    return payload


def create_month_payload(**overrides) -> dict:
    payload = {
        "benefit_month": "2025-01",
        "benefits_issued_cents": 50050,
        "benefits_entitled_reported_cents": 30000,
        "benefits_entitled_verified_cents": 20000,
    }
    payload.update(overrides)
    return payload


def post_adjustment_payload(adjustment_amount_cents, expected_overpayment_version, **overrides) -> dict:
    payload = {
        "adjustment_amount_cents": adjustment_amount_cents,
        "reason": "Fair hearing adjustment",
        "expected_overpayment_version": expected_overpayment_version,
    }
    payload.update(overrides)
    return payload


def write_off_payload(**overrides) -> dict:
    payload = {"reason": "Uncollectible"}
    payload.update(overrides)
    return payload


def create_disqualification_payload(case_id, **overrides) -> dict:
    payload = {"case_id": case_id}
    payload.update(overrides)
    return payload


def rescind_payload(**overrides) -> dict:
    payload = {"reason": "Overturned on appeal"}
    payload.update(overrides)
    return payload


def create_hearing_payload(disqualification_id, **overrides) -> dict:
    payload = {
        "disqualification_id": disqualification_id,
        "scheduled_date": "2026-05-15T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def decide_hearing_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_recovery_plan_payload(overpayment_id, **overrides) -> dict:
    payload = {
        "overpayment_id": overpayment_id,
        "method": "RECOUPMENT",
        "start_date": "2026-05-01",
        "end_date": "2027-05-01",
        "monthly_allotment_cents": 19400,
        "scheduled_monthly_cents": 9010,
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(recovery_plan_id, amount_cents, **overrides) -> dict:
    payload = {
        "recovery_plan_id": recovery_plan_id,
        "amount_cents": amount_cents,
        "transaction_date": "2026-05-01",
        "method": "PAYMENT",
    }
    payload.update(overrides)
    return payload


def void_transaction_payload(**overrides) -> dict:
    payload = {"reason": "Posted in error"}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


# Standard two-month claim: provisional = 35050, final (verified) = 45050.
DEFAULT_MONTHS = [
    {
        "benefit_month": "2025-01",
        "benefits_issued_cents": 50050,
        "benefits_entitled_reported_cents": 30000,
        "benefits_entitled_verified_cents": 20000,
    },
    {
        "benefit_month": "2025-02",
        "benefits_issued_cents": 40000,
        "benefits_entitled_reported_cents": 25000,
        "benefits_entitled_verified_cents": 25000,
    },
]
