"""Record factories and the common-field mutation helper (PRD 2.4).

System-stamped instants come from the logical clock (PRD 2.5). version starts
at 1 and increments on every modification, including cascade-originated ones.
"""

from clock import CLOCK
from util import new_id


def touch(record):
    """Stamp a modification: updated_at := logical now; version += 1."""
    record["updated_at"] = CLOCK.now()
    record["version"] += 1


def base_fields():
    now = CLOCK.now()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def immutable_fields():
    return {"id": new_id(), "created_at": CLOCK.now()}


def new_merchant(legal_name, mcc, risk_tier, reserve_mode, reserve_rate_bps):
    rec = base_fields()
    rec.update({
        "legal_name": legal_name,
        "merchant_category_code": mcc,
        "risk_tier": risk_tier,
        "reserve_mode": reserve_mode,
        "reserve_rate_bps": reserve_rate_bps,
        "status": "ACTIVE",
        "clearing_balance_cents": 0,
        "current_count_ratio_bps": None,
    })
    return rec


def new_reserve_account(merchant_id):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "held_cents": 0,
        "target_cents": 0,
        "last_recomputed_at": None,
    })
    return rec


def new_rule(network, reason_code, category, required_evidence_types,
             merchant_response_days, representment_days, chargeback_fee_cents,
             effective_from, effective_to):
    rec = immutable_fields()
    rec.update({
        "network": network,
        "reason_code": reason_code,
        "category": category,
        "required_evidence_types": list(required_evidence_types),
        "merchant_response_days": merchant_response_days,
        "representment_days": representment_days,
        "chargeback_fee_cents": chargeback_fee_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    return rec


def new_transaction(merchant_id, external_ref, network, amount_cents, occurred_at):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "external_ref": external_ref,
        "network": network,
        "amount_cents": amount_cents,
        "occurred_at": occurred_at,
        "status": "SETTLED",
    })
    return rec


def new_chargeback(merchant_id, transaction_external_ref, transaction_id, network_case_id,
                   reason_code, network, amount_cents, received_at, representment_due_at, rule_id):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "transaction_external_ref": transaction_external_ref,
        "transaction_id": transaction_id,
        "network_case_id": network_case_id,
        "reason_code": reason_code,
        "network": network,
        "amount_cents": amount_cents,
        "received_at": received_at,
        "merchant_notified_at": None,
        "merchant_response_due_at": None,
        "representment_due_at": representment_due_at,
        "case_status": "RECEIVED",
        "funds_status": "MERCHANT_DEBITED",
        "recredited_cents": 0,
        "is_ratio_counted": True,
        "_rule_id": rule_id,
    })
    return rec


def new_evidence_item(chargeback_id, evidence_type, document_uri):
    rec = base_fields()
    rec.update({
        "chargeback_id": chargeback_id,
        "evidence_type": evidence_type,
        "document_uri": document_uri,
        "status": "DRAFT",
    })
    return rec


def new_representment(chargeback_id, evidence_item_ids, cure_count):
    rec = base_fields()
    rec.update({
        "chargeback_id": chargeback_id,
        "evidence_item_ids": list(evidence_item_ids),
        "status": "ASSEMBLED",
        "cure_count": cure_count,
        "submitted_at": None,
        "won_amount_cents": None,
        "decided_at": None,
    })
    return rec


def new_fee_assessment(merchant_id, chargeback_id, enrollment_id, kind, amount_cents, assessed_by):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "chargeback_id": chargeback_id,
        "enrollment_id": enrollment_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "ASSESSED",
        "assessed_by_user_id": assessed_by,
        "waived_by_user_id": None,
        "settled_at": None,
        "waived_at": None,
    })
    return rec


def new_ledger_entry(reserve_account_id, entry_type, amount_cents, source_kind, source_id, release_eligible_at):
    rec = immutable_fields()
    rec.update({
        "reserve_account_id": reserve_account_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_kind": source_kind,
        "source_id": source_id,
        "release_eligible_at": release_eligible_at,
    })
    return rec


def new_ratio_snapshot(merchant_id, network, period_month, sales_count, sales_amount_cents,
                       chargeback_count, gross_chargeback_count, count_ratio_bps,
                       gross_count_ratio_bps, computed_at):
    rec = immutable_fields()
    rec.update({
        "merchant_id": merchant_id,
        "network": network,
        "period_month": period_month,
        "sales_count": sales_count,
        "sales_amount_cents": sales_amount_cents,
        "chargeback_count": chargeback_count,
        "gross_chargeback_count": gross_chargeback_count,
        "count_ratio_bps": count_ratio_bps,
        "gross_count_ratio_bps": gross_count_ratio_bps,
        "computed_at": computed_at,
    })
    return rec


def new_program_enrollment(merchant_id, network, program_code, enrolled_month):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "network": network,
        "program_code": program_code,
        "enrolled_month": enrolled_month,
        "exited_month": None,
        "months_over_count": 1,
        "status": "ACTIVE",
    })
    return rec


def new_remediation_plan(enrollment_id, root_cause_codes, corrective_actions):
    rec = base_fields()
    rec.update({
        "enrollment_id": enrollment_id,
        "root_cause_codes": list(root_cause_codes),
        "corrective_actions": list(corrective_actions),
        "status": "DRAFT",
        "reviewed_by_user_id": None,
        "decision_note": None,
    })
    return rec


def new_prevention_alert(transaction_id, merchant_id, alert_type, received_at, response_due_at):
    rec = base_fields()
    rec.update({
        "transaction_id": transaction_id,
        "merchant_id": merchant_id,
        "alert_type": alert_type,
        "received_at": received_at,
        "response_due_at": response_due_at,
        "status": "OPEN",
    })
    return rec


def new_education_assignment(merchant_id, enrollment_ref, module_code):
    rec = base_fields()
    rec.update({
        "merchant_id": merchant_id,
        "enrollment_ref": enrollment_ref,
        "module_code": module_code,
        "assigned_reason": "PROGRAM_ENROLLMENT",
        "status": "ASSIGNED",
        "assigned_at": CLOCK.now(),
        "completed_at": None,
    })
    return rec
