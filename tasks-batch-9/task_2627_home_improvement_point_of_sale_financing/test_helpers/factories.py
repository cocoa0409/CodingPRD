"""Request-payload builders.

Each builder returns a complete, valid payload for one endpoint from the
canonical literals in :mod:`constants`, and accepts keyword overrides so a test
can perturb exactly one field.  Passing ``None`` for an optional field removes
it from the payload entirely, which is how tests exercise omission.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Program reference data ───────────────────────────

def trade_rule_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(C.ROOFING_TRADE_RULE, overrides)


def promotion_plan_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(C.DEFERRED_INTEREST_PLAN, overrides)


# ─── Merchant onboarding ──────────────────────────────

def merchant_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(C.CANONICAL_MERCHANT, overrides)


def license_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(C.CANONICAL_LICENSE, overrides)


def license_verification_payload(outcome: str = "VERIFIED",
                                **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


def enrollment_submission_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"attestation_ref": C.ATTESTATION_REF}, overrides)


def enrollment_decision_payload(decision: str = "APPROVE",
                                **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def program_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── Promotion enrollment ─────────────────────────────

def promotion_enrollment_payload(promotion_plan_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "promotion_plan_id": promotion_plan_id,
            "window_start_date": C.ENROLLMENT_WINDOW_START,
            "window_end_date": C.ENROLLMENT_WINDOW_END,
            "negotiated_discount_bps": C.NEGOTIATED_DISCOUNT_BPS,
        },
        overrides,
    )


# ─── Reserve and fraud ────────────────────────────────

def holdback_adjustment_payload(adjustment_type: str, amount_cents: int,
                                expected_merchant_version: int,
                                **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "adjustment_type": adjustment_type,
            "amount_cents": amount_cents,
            "expected_merchant_version": expected_merchant_version,
        },
        overrides,
    )


def fraud_alert_payload(alert_type: str = "PHANTOM_PROJECT", severity_weight: int = 35,
                        **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"alert_type": alert_type, "severity_weight": severity_weight}, overrides
    )


def investigation_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


# ─── Point of sale ────────────────────────────────────

def consumer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(C.CANONICAL_CONSUMER, overrides)


def credit_application_payload(merchant_id: str, consumer_id: str,
                              promotion_plan_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "merchant_id": merchant_id,
            "consumer_id": consumer_id,
            "promotion_plan_id": promotion_plan_id,
            "project_amount_cents": C.CANONICAL_TICKET_CENTS,
        },
        overrides,
    )


def disclosure_delivery_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"disclosure_template_version": C.DISCLOSURE_TEMPLATE_VERSION}, overrides
    )


def disclosure_acknowledgement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"consumer_signature_ref": C.SIGNATURE_REF}, overrides)


def acceptance_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# ─── Project and milestones ───────────────────────────

def project_payload(application_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {"application_id": application_id}
    base.update(C.CANONICAL_PROJECT)
    return _merge(base, overrides)


def milestone_payload(sequence_no: int = 1, name: str = "Tear-off and deck inspection",
                      release_pct_bps: int = 3000, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sequence_no": sequence_no,
            "name": name,
            "release_pct_bps": release_pct_bps,
        },
        overrides,
    )


def claim_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"evidence_ref": C.EVIDENCE_REF}, overrides)


def milestone_verification_payload(outcome: str = "VERIFY",
                                   **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


def completion_certification_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"completion_certificate_ref": C.COMPLETION_CERTIFICATE_REF}, overrides
    )


# ─── Funding draws ────────────────────────────────────

def funding_draw_payload(loan_account_id: str, project_milestone_id: str,
                         requested_amount_cents: int, expected_loan_account_version: int,
                         settlement_speed: str = "STANDARD_3DAY",
                         **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_account_id": loan_account_id,
            "project_milestone_id": project_milestone_id,
            "requested_amount_cents": requested_amount_cents,
            "settlement_speed": settlement_speed,
            "expected_loan_account_version": expected_loan_account_version,
        },
        overrides,
    )


def settlement_payload(decision: str = "SETTLE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def reversal_payload(reversal_reason_code: str = "OPERATOR_CORRECTION",
                     **overrides: Any) -> Dict[str, Any]:
    return _merge({"reversal_reason_code": reversal_reason_code}, overrides)


# ─── Disputes ─────────────────────────────────────────

def dispute_case_payload(loan_account_id: str, project_id: str,
                         claimed_incomplete_amount_cents: int,
                         **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "loan_account_id": loan_account_id,
            "project_id": project_id,
            "claimed_incomplete_amount_cents": claimed_incomplete_amount_cents,
            "description": "Tear-off finished but shingles never installed.",
        },
        overrides,
    )


def merchant_response_payload(response_type: str = "WORK_COMPLETE_EVIDENCE",
                              **overrides: Any) -> Dict[str, Any]:
    return _merge({"response_type": response_type}, overrides)


def resolution_payload(outcome: str, expected_merchant_version: int,
                       **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"outcome": outcome, "expected_merchant_version": expected_merchant_version},
        overrides,
    )


# ─── Payments and clock ───────────────────────────────

def payment_payload(loan_account_id: str, amount_cents: int,
                    **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"loan_account_id": loan_account_id, "amount_cents": amount_cents}, overrides
    )


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ─── Milestone layouts ────────────────────────────────

def milestone_layout(*release_pct_bps: int) -> List[Dict[str, Any]]:
    """A sequence of milestone payloads carrying the given release shares in order."""
    return [
        milestone_payload(
            sequence_no=index + 1,
            name=f"Stage {index + 1}",
            release_pct_bps=share,
        )
        for index, share in enumerate(release_pct_bps)
    ]
