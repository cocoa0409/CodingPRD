from services import vendor_balance, mismatch_count_3yr, backup_flag


def _common(rec):
    return {"id": rec["id"], "created_at": rec["created_at"],
            "updated_at": rec["updated_at"], "version": rec["version"]}


def tax_year(rec):
    d = {"tax_year": rec["tax_year"],
         "period_start": rec["period_start"],
         "period_end_exclusive": rec["period_end_exclusive"],
         "efiling_threshold_count": rec["efiling_threshold_count"],
         "nec_reportable_threshold_cents": rec["nec_reportable_threshold_cents"],
         "misc_reportable_threshold_cents": rec["misc_reportable_threshold_cents"],
         "recipient_copy_deadline": rec["recipient_copy_deadline"],
         "backup_withholding_rate_bps": rec["backup_withholding_rate_bps"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def vendor(rec):
    d = {"legal_name": rec["legal_name"],
         "tin": rec["tin"],
         "tin_type": rec["tin_type"],
         "entity_classification": rec["entity_classification"],
         "address_line1": rec["address_line1"],
         "address_city": rec["address_city"],
         "address_state": rec["address_state"],
         "address_postal": rec["address_postal"],
         "e_delivery_consent": rec["e_delivery_consent"],
         "tin_match_status": rec["tin_match_status"],
         "mismatch_count_3yr": mismatch_count_3yr(rec["id"]),
         "b_notice_stage": rec["b_notice_stage"],
         "backup_withholding_flag": backup_flag(rec),
         "withholding_balance_cents": vendor_balance(rec["id"]),
         "merged_into_vendor_id": rec["merged_into_vendor_id"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def w9_submission(rec):
    d = {"vendor_id": rec["vendor_id"],
         "submitted_legal_name": rec["submitted_legal_name"],
         "submitted_tin": rec["submitted_tin"],
         "submitted_tin_type": rec["submitted_tin_type"],
         "signature_name": rec["signature_name"],
         "match_result": rec["match_result"],
         "mismatch_reason_code": rec["mismatch_reason_code"]}
    d.update(_common(rec))
    return d


def payment(rec):
    d = {"vendor_id": rec["vendor_id"],
         "source_system": rec["source_system"],
         "payment_type": rec["payment_type"],
         "amount_cents": rec["amount_cents"],
         "payment_date": rec["payment_date"],
         "tax_year": rec["tax_year"],
         "is_reportable": rec["is_reportable"],
         "reportable_box": rec["reportable_box"],
         "withheld_cents": rec["withheld_cents"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def withholding_entry(rec):
    # Ledger rows carry only id + created_at (no updated_at / version).
    return {"id": rec["id"],
            "vendor_id": rec["vendor_id"],
            "payment_id": rec["payment_id"],
            "reverses_entry_id": rec["reverses_entry_id"],
            "remittance_id": rec["remittance_id"],
            "tax_year": rec["tax_year"],
            "quarter": rec["quarter"],
            "entry_type": rec["entry_type"],
            "amount_cents": rec["amount_cents"],
            "status": rec["status"],
            "created_at": rec["created_at"]}


def remittance(rec):
    d = {"tax_year": rec["tax_year"],
         "quarter": rec["quarter"],
         "amount_cents": rec["amount_cents"],
         "statutory_expected_cents": rec["statutory_expected_cents"],
         "created_by_user_id": rec["created_by_user_id"],
         "submitted_by_user_id": rec["submitted_by_user_id"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def tax_return(rec):
    d = {"vendor_id": rec["vendor_id"],
         "tax_year": rec["tax_year"],
         "form_type": rec["form_type"],
         "box_amounts": rec["box_amounts"],
         "provisional_box_amounts": rec["provisional_box_amounts"],
         "amount_basis": rec["amount_basis"],
         "is_correction": rec["is_correction"],
         "corrects_return_id": rec["corrects_return_id"],
         "transmittal_id": rec["transmittal_id"],
         "federal_status": rec["federal_status"],
         "recipient_copy_status": rec["recipient_copy_status"],
         "copy_delivered_at": rec["copy_delivered_at"]}
    d.update(_common(rec))
    return d


def transmittal(rec):
    d = {"tax_year": rec["tax_year"],
         "form_type": rec["form_type"],
         "filing_channel": rec["filing_channel"],
         "return_count": rec["return_count"],
         "sealed_by_user_id": rec["sealed_by_user_id"],
         "submitted_by_user_id": rec["submitted_by_user_id"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def state_rule(rec):
    d = {"state_code": rec["state_code"],
         "participates_in_cfsf": rec["participates_in_cfsf"],
         "direct_reporting_threshold_cents": rec["direct_reporting_threshold_cents"],
         "effective_from": rec["effective_from"],
         "effective_to": rec["effective_to"]}
    d.update(_common(rec))
    return d


def state_obligation(rec):
    d = {"vendor_id": rec["vendor_id"],
         "state_rule_id": rec["state_rule_id"],
         "tax_year": rec["tax_year"],
         "required_channel": rec["required_channel"],
         "reportable_amount_cents": rec["reportable_amount_cents"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d


def b_notice(rec):
    d = {"vendor_id": rec["vendor_id"],
         "notice_year": rec["notice_year"],
         "stage": rec["stage"],
         "status": rec["status"],
         "resolved_by_user_id": rec["resolved_by_user_id"]}
    d.update(_common(rec))
    return d


def merge_request(rec):
    d = {"source_vendor_id": rec["source_vendor_id"],
         "target_vendor_id": rec["target_vendor_id"],
         "reason": rec["reason"],
         "requested_by_user_id": rec["requested_by_user_id"],
         "reviewed_by_user_id": rec["reviewed_by_user_id"],
         "status": rec["status"]}
    d.update(_common(rec))
    return d
