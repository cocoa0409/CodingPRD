"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import (
    DEFAULT_AGREEMENT_VERSION,
    PERIOD_2026_08,
    PRODUCT_SERUM,
)


def compensation_plan_payload(plan_code="PLAN-A", name="Consultant Plan A", **overrides) -> dict:
    payload = {"plan_code": plan_code, "name": name}
    payload.update(overrides)
    return payload


def tax_jurisdiction_payload(
    state_code="TX", tax_rate_bp=825, facilitator_agreement_active=True, **overrides
) -> dict:
    payload = {
        "state_code": state_code,
        "tax_rate_bp": tax_rate_bp,
        "facilitator_agreement_active": facilitator_agreement_active,
    }
    payload.update(overrides)
    return payload


def product_payload(
    sku="SERUM",
    name="Renewal Serum",
    wholesale_price_cents=PRODUCT_SERUM["wholesale_price_cents"],
    srp_cents=PRODUCT_SERUM["srp_cents"],
    **overrides,
) -> dict:
    payload = {
        "sku": sku,
        "name": name,
        "wholesale_price_cents": wholesale_price_cents,
        "srp_cents": srp_cents,
    }
    payload.update(overrides)
    return payload


def enrollment_application_payload(
    compensation_plan_id,
    starter_kit_product_id,
    applicant_email="alice@example.com",
    applicant_full_name="Alice Root",
    applicant_state_code="TX",
    sponsor_consultant_id=None,
    **overrides,
) -> dict:
    payload = {
        "applicant_email": applicant_email,
        "applicant_full_name": applicant_full_name,
        "applicant_state_code": applicant_state_code,
        "compensation_plan_id": compensation_plan_id,
        "starter_kit_product_id": starter_kit_product_id,
    }
    if sponsor_consultant_id is not None:
        payload["sponsor_consultant_id"] = sponsor_consultant_id
    payload.update(overrides)
    return payload


def accept_agreement_payload(agreement_version=DEFAULT_AGREEMENT_VERSION) -> dict:
    return {"agreement_version": agreement_version}


def identity_submission_payload(identity_document_reference="DOC-002") -> dict:
    return {"identity_document_reference": identity_document_reference}


def identity_decision_payload(decision="VERIFY", failure_reason=None) -> dict:
    payload = {"decision": decision}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return payload


def pay_starter_kit_payload(amount_cents, payment_reference="KIT-PAY-1") -> dict:
    return {"amount_cents": amount_cents, "payment_reference": payment_reference}


def withdraw_payload(reason="CHANGED_MIND") -> dict:
    return {"reason": reason}


def order_line(product_id, quantity) -> dict:
    return {"product_id": product_id, "quantity": quantity}


def product_order_payload(
    consultant_id,
    lines,
    order_type="PERSONAL_INVENTORY",
    posted_period_code=PERIOD_2026_08["period_code"],
    ship_to_state_code="TX",
    **overrides,
) -> dict:
    payload = {
        "consultant_id": consultant_id,
        "order_type": order_type,
        "posted_period_code": posted_period_code,
        "ship_to_state_code": ship_to_state_code,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def pay_order_payload(amount_cents, payment_reference="PAY-OK") -> dict:
    return {"amount_cents": amount_cents, "payment_reference": payment_reference}


def fulfillment_payload(event="SHIP") -> dict:
    return {"event": event}


def qualification_period_payload(
    compensation_plan_id,
    period_code=PERIOD_2026_08["period_code"],
    period_start=PERIOD_2026_08["period_start"],
    period_end=PERIOD_2026_08["period_end"],
    **overrides,
) -> dict:
    payload = {
        "compensation_plan_id": compensation_plan_id,
        "period_code": period_code,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def reopen_payload(reason="apply the returned volume to group totals") -> dict:
    return {"reason": reason}


def personal_use_attestation_payload(attested_personal_use_points) -> dict:
    return {"attested_personal_use_points": attested_personal_use_points}


def commission_run_payload(qualification_period_id, expected_qualification_period_version) -> dict:
    return {
        "qualification_period_id": qualification_period_id,
        "expected_qualification_period_version": expected_qualification_period_version,
    }


def approval_decision_payload(decision="APPROVE", decision_note=None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def reversal_payload(reversal_reason="duplicate volume posting discovered") -> dict:
    return {"reversal_reason": reversal_reason}


def buyback_line(product_order_id, product_id, quantity, condition="RESALABLE") -> dict:
    return {
        "product_order_id": product_order_id,
        "product_id": product_id,
        "quantity": quantity,
        "condition": condition,
    }


def buyback_request_payload(consultant_id, lines) -> dict:
    return {"consultant_id": consultant_id, "lines": lines}


def buyback_decision_payload(decision="APPROVE", decision_reason=None) -> dict:
    payload = {"decision": decision}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return payload


def compliance_case_payload(
    consultant_id, claim_type="INCOME_CLAIM", evidence_reference="EV-1"
) -> dict:
    return {
        "consultant_id": consultant_id,
        "claim_type": claim_type,
        "evidence_reference": evidence_reference,
    }


def compliance_decision_payload(
    decision="SANCTION",
    sanction_level=None,
    effective_from=None,
    effective_until=None,
    decision_reason=None,
) -> dict:
    payload = {"decision": decision}
    if sanction_level is not None:
        payload["sanction_level"] = sanction_level
    if effective_from is not None:
        payload["effective_from"] = effective_from
    if effective_until is not None:
        payload["effective_until"] = effective_until
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return payload


def appeal_payload(appeal_statement="the claim was misread") -> dict:
    return {"appeal_statement": appeal_statement}


def termination_payload(termination_reason="VOLUNTARY") -> dict:
    return {"termination_reason": termination_reason}


def reinstatement_payload(reinstatement_note="returned within the window") -> dict:
    return {"reinstatement_note": reinstatement_note}


def rank_adjustment_payload(rank_code, adjustment_reason=None) -> dict:
    payload = {"rank_code": rank_code}
    if adjustment_reason is not None:
        payload["adjustment_reason"] = adjustment_reason
    return payload


def income_disclosure_payload(
    commission_run_id, expected_commission_run_version, population_basis="ALL_ENROLLED"
) -> dict:
    return {
        "commission_run_id": commission_run_id,
        "population_basis": population_basis,
        "expected_commission_run_version": expected_commission_run_version,
    }


def legal_decision_payload(decision="PUBLISH", revision_note=None) -> dict:
    payload = {"decision": decision}
    if revision_note is not None:
        payload["revision_note"] = revision_note
    return payload


def clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
