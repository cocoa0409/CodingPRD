"""Payload factories — one per creatable resource, input fields only."""
from .constants import CLOCK_DEFAULT, DEFAULT_PAYER_CONFIG


def create_payer_payload(name="P1", payer_type="RAC", **overrides):
    payload = {"name": name, "payer_type": payer_type}
    payload.update(DEFAULT_PAYER_CONFIG)
    payload.update(overrides)
    return payload


def create_issue_code_payload(code="MED_NEC", category="CLINICAL",
                              description="Medical necessity"):
    return {"code": code, "category": category, "description": description}


def create_audit_case_payload(payer_id, audit_type="RAC_COMPLEX",
                              received_at=CLOCK_DEFAULT,
                              external_audit_ref=None):
    payload = {
        "payer_id": payer_id,
        "audit_type": audit_type,
        "received_at": received_at,
    }
    if external_audit_ref is not None:
        payload["external_audit_ref"] = external_audit_ref
    return payload


def create_claim_line_payload(claim_number="L-1", patient_account_number="PA-1",
                              service_start_date="2026-01-01T00:00:00Z",
                              service_end_date="2026-01-03T00:00:00Z",
                              billed_amount_cents=100000):
    return {
        "claim_number": claim_number,
        "patient_account_number": patient_account_number,
        "service_start_date": service_start_date,
        "service_end_date": service_end_date,
        "billed_amount_cents": billed_amount_cents,
    }


def records_submission_payload(manifest_ref="M-1", expected_audit_case_version=1):
    return {
        "manifest_ref": manifest_ref,
        "expected_audit_case_version": expected_audit_case_version,
    }


def denied_outcome(claim_line_id, denied_amount_cents, issue_code_id,
                   denial_category="TECHNICAL"):
    return {
        "claim_line_id": claim_line_id,
        "outcome": "DENIED",
        "denied_amount_cents": denied_amount_cents,
        "denial_category": denial_category,
        "issue_code_id": issue_code_id,
    }


def paid_outcome(claim_line_id):
    return {"claim_line_id": claim_line_id, "outcome": "PAID_AS_BILLED"}


def partial_outcome(claim_line_id, denied_amount_cents, issue_code_id,
                    denial_category="TECHNICAL"):
    return {
        "claim_line_id": claim_line_id,
        "outcome": "PARTIALLY_DENIED",
        "denied_amount_cents": denied_amount_cents,
        "denial_category": denial_category,
        "issue_code_id": issue_code_id,
    }


def determination_payload(outcomes):
    return {"outcomes": outcomes}


def create_appeal_payload(notes=None):
    payload = {}
    if notes is not None:
        payload["notes"] = notes
    return payload


def decision_payload(outcome, upheld_cents):
    return {"outcome": outcome, "upheld_cents": upheld_cents}


def create_packet_item_payload(item_type="MEDICAL_RECORD", required=None):
    payload = {"item_type": item_type}
    if required is not None:
        payload["required"] = required
    return payload


def attach_item_payload(document_ref="doc-1"):
    return {"document_ref": document_ref}


def create_demand_payload(principal_cents, issued_at=None):
    payload = {"principal_cents": principal_cents}
    if issued_at is not None:
        payload["issued_at"] = issued_at
    return payload


def adjust_demand_payload(new_principal_cents,
                          expected_recoupment_demand_version):
    return {
        "new_principal_cents": new_principal_cents,
        "expected_recoupment_demand_version": expected_recoupment_demand_version,
    }


def create_remittance_payload(payer_id, gross_amount_cents, external_ref=None):
    payload = {"payer_id": payer_id, "gross_amount_cents": gross_amount_cents}
    if external_ref is not None:
        payload["external_ref"] = external_ref
    return payload


def manual_offset_payload(remittance_id, amount_cents):
    return {"remittance_id": remittance_id, "amount_cents": amount_cents}


def create_cap_payload(payer_id, issue_code_id, title="Fix auth capture",
                       root_cause="Auth not captured at scheduling"):
    return {
        "payer_id": payer_id,
        "issue_code_id": issue_code_id,
        "title": title,
        "root_cause": root_cause,
    }
