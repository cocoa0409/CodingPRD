"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PAYER_NAME": "Meridian Commercial",
    "PAYER_CODE": "COM",
    "PAYER_TYPE": "COMMERCIAL",
    "MEDICARE_NAME": "Medicare Region A",
    "MEDICARE_CODE": "MCR",
    "ACCOUNT_NUMBER": "ACCT-1",
    "MRN": "MRN-1",
    "PATIENT_NAME": "Test Patient",
    "STATE_CODE": "CA",
    "FINANCIAL_CLASS": "OUTPATIENT",
    "PAYEE_ADDRESS_LINE": "1 Test Way",
    "NARRATIVE": "Remit posted twice by the lockbox feed",
    "BANK_ACCOUNT_CODE": "OPERATING",
}


def create_payer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PAYER_NAME"],
        "payer_code": DEFAULTS["PAYER_CODE"],
        "payer_type": DEFAULTS["PAYER_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_patient_account_payload(primary_payer_id: str, **overrides) -> dict:
    payload = {
        "account_number": DEFAULTS["ACCOUNT_NUMBER"],
        "mrn": DEFAULTS["MRN"],
        "patient_name": DEFAULTS["PATIENT_NAME"],
        "guarantor_state_code": DEFAULTS["STATE_CODE"],
        "primary_payer_id": primary_payer_id,
        "financial_class": DEFAULTS["FINANCIAL_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(txn_type: str, amount_cents: int, source: str,
                               **overrides) -> dict:
    payload = {
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "source": source,
    }
    payload.update(overrides)
    return payload


def create_root_cause_finding_payload(credit_balance_id: str, **overrides) -> dict:
    payload = {
        "credit_balance_id": credit_balance_id,
        "cause_code": "DUPLICATE_PAYMENT",
        "corrective_action": "REPOST_TRANSACTION",
        "narrative": DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def create_refund_request_payload(credit_balance_id: str, requested_amount_cents: int,
                                  payee_type: str, expected_credit_balance_version: int,
                                  **overrides) -> dict:
    payload = {
        "credit_balance_id": credit_balance_id,
        "requested_amount_cents": requested_amount_cents,
        "payee_type": payee_type,
        "payee_name": DEFAULTS["PATIENT_NAME"],
        "payee_address_line": DEFAULTS["PAYEE_ADDRESS_LINE"],
        "payee_state_code": DEFAULTS["STATE_CODE"],
        "expected_credit_balance_version": expected_credit_balance_version,
    }
    payload.update(overrides)
    return payload


def create_decision_payload(decision: str, approver_tier: int, **overrides) -> dict:
    payload = {"decision": decision, "approver_tier": approver_tier}
    payload.update(overrides)
    return payload


def create_refund_batch_payload(batch_number: str, cutoff_at: str,
                                scheduled_run_at: str, **overrides) -> dict:
    payload = {
        "batch_number": batch_number,
        "bank_account_code": DEFAULTS["BANK_ACCOUNT_CODE"],
        "cutoff_at": cutoff_at,
        "scheduled_run_at": scheduled_run_at,
    }
    payload.update(overrides)
    return payload


def create_take_back_notice_payload(payer_id: str, notice_number: str,
                                    total_recoup_cents: int, **overrides) -> dict:
    payload = {
        "payer_id": payer_id,
        "notice_number": notice_number,
        "total_recoup_cents": total_recoup_cents,
    }
    payload.update(overrides)
    return payload


def create_offset_application_payload(target_account_ids: list,
                                      expected_take_back_notice_version: int,
                                      **overrides) -> dict:
    payload = {
        "target_account_ids": list(target_account_ids),
        "expected_take_back_notice_version": expected_take_back_notice_version,
    }
    payload.update(overrides)
    return payload


def create_escheatment_record_payload(check_disbursement_id: str, **overrides) -> dict:
    payload = {"check_disbursement_id": check_disbursement_id}
    payload.update(overrides)
    return payload


def create_compliance_report_payload(report_type: str, scope_code: str,
                                     period_start_at: str, period_end_at: str,
                                     as_of_at: str, **overrides) -> dict:
    payload = {
        "report_type": report_type,
        "scope_code": scope_code,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "as_of_at": as_of_at,
    }
    payload.update(overrides)
    return payload
