"""Per-entity serializers.  Rollup counters PRD 2.12 says must be 'correct at the
moment the response is emitted' are recomputed here from the live store."""

from store import store


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def employer(row):
    out = {
        "legal_name": row["legal_name"],
        "region_code": row["region_code"],
        "transit_group_limit_cents": row["transit_group_limit_cents"],
        "parking_group_limit_cents": row["parking_group_limit_cents"],
        "pretax_ratio_cap_pct": row["pretax_ratio_cap_pct"],
        "spill_policy": row["spill_policy"],
        "rollover_policy": row["rollover_policy"],
        "rollover_cap_cents": row["rollover_cap_cents"],
        "forfeiture_grace_days": row["forfeiture_grace_days"],
        "program_cap_cents": row["program_cap_cents"],
        "program_status": row["program_status"],
        "ordinance_mandate_status": row["ordinance_mandate_status"],
        "total_pretax_committed_cents": row["total_pretax_committed_cents"],
        "enrolled_employee_count": row["enrolled_employee_count"],
    }
    return _common(row, out)


def benefit_category(row):
    live = {"PENDING", "HELD", "FUNDED"}
    count = 0
    for election in store.elections.values():
        if election["benefit_category_id"] == row["id"] and election["funding_status"] in live:
            count += 1
    out = {
        "employer_id": row["employer_id"],
        "category_type": row["category_type"],
        "limit_group": row["limit_group"],
        "monthly_exclusion_limit_cents": row["monthly_exclusion_limit_cents"],
        "pretax_allowed": row["pretax_allowed"],
        "posttax_allowed": row["posttax_allowed"],
        "status": row["status"],
        "active_election_count": count,
    }
    return _common(row, out)


def employee(row):
    out = {
        "employer_id": row["employer_id"],
        "external_ref": row["external_ref"],
        "work_region_code": row["work_region_code"],
        "payroll_cycle": row["payroll_cycle"],
        "hire_date": row["hire_date"],
        "termination_date": row["termination_date"],
        "status": row["status"],
        "substantiation_hold": row["substantiation_hold"],
        "repayment_due_cents": row["repayment_due_cents"],
    }
    return _common(row, out)


def election_window(row):
    counted = {"PENDING", "HELD", "FUNDED", "SETTLED"}
    count = 0
    for election in store.elections.values():
        if election["election_window_id"] == row["id"] and election["funding_status"] in counted:
            count += 1
    out = {
        "employer_id": row["employer_id"],
        "benefit_month": row["benefit_month"],
        "opens_at": row["opens_at"],
        "cutoff_at": row["cutoff_at"],
        "fulfillment_lead_days": row["fulfillment_lead_days"],
        "mid_month_change_allowed": row["mid_month_change_allowed"],
        "status": row["status"],
        "election_count": count,
        "locked_at": row["locked_at"],
    }
    return _common(row, out)


def benefit_account(row):
    count = 0
    for entry in store.ledger_entries.values():
        if entry["benefit_account_id"] == row["id"]:
            count += 1
    out = {
        "employee_id": row["employee_id"],
        "benefit_category_id": row["benefit_category_id"],
        "rollover_in_cents": row["rollover_in_cents"],
        "contributed_cents": row["contributed_cents"],
        "spent_cents": row["spent_cents"],
        "forfeited_cents": row["forfeited_cents"],
        "refunded_cents": row["refunded_cents"],
        "reversed_cents": row["reversed_cents"],
        "fee_charged_cents": row["fee_charged_cents"],
        "available_balance_cents": row["available_balance_cents"],
        "ledger_entry_count": count,
    }
    return _common(row, out)


def ledger_entry(row):
    return {
        "id": row["id"],
        "benefit_account_id": row["benefit_account_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "source_entity": row["source_entity"],
        "source_id": row["source_id"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }


def election(row):
    out = {
        "employee_id": row["employee_id"],
        "election_window_id": row["election_window_id"],
        "benefit_category_id": row["benefit_category_id"],
        "benefit_account_id": row["benefit_account_id"],
        "transit_media_id": row["transit_media_id"],
        "superseded_election_id": row["superseded_election_id"],
        "pretax_amount_cents": row["pretax_amount_cents"],
        "posttax_amount_cents": row["posttax_amount_cents"],
        "total_amount_cents": row["total_amount_cents"],
        "excluded_amount_cents": row["excluded_amount_cents"],
        "posttax_spill_cents": row["posttax_spill_cents"],
        "posttax_effective_cents": row["posttax_effective_cents"],
        "exclusion_basis": row["exclusion_basis"],
        "entitled_media_units": row["entitled_media_units"],
        "change_count": row["change_count"],
        "funding_status": row["funding_status"],
        "fulfillment_status": row["fulfillment_status"],
    }
    return _common(row, out)


def transit_media(row):
    out = {
        "sku": row["sku"],
        "media_type": row["media_type"],
        "region_code": row["region_code"],
        "eligible_category_type": row["eligible_category_type"],
        "unit_price_cents": row["unit_price_cents"],
        "lead_days": row["lead_days"],
        "replacement_fee_cents": row["replacement_fee_cents"],
        "requires_physical_fulfillment": row["requires_physical_fulfillment"],
        "status": row["status"],
    }
    return _common(row, out)


def order_batch(row):
    out = {
        "election_window_id": row["election_window_id"],
        "region_code": row["region_code"],
        "status": row["status"],
        "line_count": row["line_count"],
        "subtotal_cents": row["subtotal_cents"],
        "discount_cents": row["discount_cents"],
        "total_cents": row["total_cents"],
        "sealed_by_user_id": row["sealed_by_user_id"],
        "released_by_user_id": row["released_by_user_id"],
        "sealed_at": row["sealed_at"],
    }
    return _common(row, out)


def media_order(row):
    out = {
        "election_id": row["election_id"],
        "transit_media_id": row["transit_media_id"],
        "order_batch_id": row["order_batch_id"],
        "superseded_media_order_id": row["superseded_media_order_id"],
        "quantity": row["quantity"],
        "coverage_start_at": row["coverage_start_at"],
        "coverage_end_at": row["coverage_end_at"],
        "unit_price_cents_snapshot": row["unit_price_cents_snapshot"],
        "line_gross_cents": row["line_gross_cents"],
        "line_surcharge_cents": row["line_surcharge_cents"],
        "line_total_cents": row["line_total_cents"],
        "status": row["status"],
        "tracking_ref": row["tracking_ref"],
        "undelivered_reason": row["undelivered_reason"],
        "replacement_count": row["replacement_count"],
        "replacement_fee_charged_cents": row["replacement_fee_charged_cents"],
    }
    return _common(row, out)


def card_transaction(row):
    out = {
        "election_id": row["election_id"],
        "benefit_account_id": row["benefit_account_id"],
        "amount_cents": row["amount_cents"],
        "merchant_category_code": row["merchant_category_code"],
        "merchant_name": row["merchant_name"],
        "transaction_at": row["transaction_at"],
        "substantiation_status": row["substantiation_status"],
        "posted_spend_cents": row["posted_spend_cents"],
        "reopen_count": row["reopen_count"],
        "approved_by_user_id": row["approved_by_user_id"],
        "denied_by_user_id": row["denied_by_user_id"],
    }
    return _common(row, out)


def substantiation_claim(row):
    out = {
        "card_transaction_id": row["card_transaction_id"],
        "claimed_amount_cents": row["claimed_amount_cents"],
        "doc_type": row["doc_type"],
        "status": row["status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "rejection_reason": row["rejection_reason"],
    }
    return _common(row, out)


def payroll_file(row):
    out = {
        "employer_id": row["employer_id"],
        "period_month": row["period_month"],
        "status": row["status"],
        "participant_count": row["participant_count"],
        "total_pretax_cents": row["total_pretax_cents"],
        "total_posttax_cents": row["total_posttax_cents"],
        "admin_fee_cents": row["admin_fee_cents"],
        "pre_waiver_charge_cents": row["pre_waiver_charge_cents"],
        "fee_waiver_cents": row["fee_waiver_cents"],
        "employer_charge_cents": row["employer_charge_cents"],
        "transmitted_at": row["transmitted_at"],
        "acknowledgement_code": row["acknowledgement_code"],
    }
    return _common(row, out)


def compliance_assessment(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "assessment_month": row["assessment_month"],
        "covered_employee_count": row["covered_employee_count"],
        "qualifying_transit_offering_count": row["qualifying_transit_offering_count"],
        "assessed_transit_group_limit_cents": row["assessed_transit_group_limit_cents"],
        "mandate_status": row["mandate_status"],
        "finding": row["finding"],
        "created_at": row["created_at"],
    }
