"""Serializers: exact field sets from SCAFFOLD §1.1."""
from core import fmt_dt

_COMMON = ("created_at", "updated_at")


def _base(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def _pick(row, fields):
    out = {}
    for field in fields:
        out[field] = row.get(field)
    return out


def _dt_fields(out, row, fields):
    for field in fields:
        out[field] = fmt_dt(row.get(field))
    return out


def owner(row):
    out = _base(row)
    out.update(_pick(row, [
        "legal_name", "ownership_type", "tax_id_last4",
        "permanent_disqualification_count", "cmp_outstanding_cents",
        "sanction_flag", "status",
    ]))
    return out


def store(row):
    out = _base(row)
    out.update(_pick(row, [
        "owner_id", "predecessor_store_id", "store_name", "state_code",
        "store_type", "checkout_lane_count", "staple_shelf_linear_feet",
        "annual_gross_sales_cents", "annual_staple_sales_cents",
        "staple_sales_bps", "criterion_b_pass", "max_terminal_slots",
        "tax_rate_bps", "hardship_designated", "fns_number",
        "authorization_status", "sanction_status", "permanently_disqualified",
        "redemption_flag_level", "active_terminal_count",
    ]))
    _dt_fields(out, row, ["authorized_at", "disqualified_until"])
    return out


def application(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "application_type", "claimed_criterion",
        "reported_inventory_lines", "reported_staple_sales_pct",
        "desk_qualifying_categories", "desk_perishable_categories",
        "desk_criterion_pass", "verified_criterion_pass",
        "deficiency_cycle_count", "hold_reason_code", "decision_reason_code",
        "status",
    ]))
    _dt_fields(out, row, ["submitted_at", "decided_at"])
    return out


def inspector(row):
    out = _base(row)
    out.update(_pick(row, [
        "full_name", "state_code", "max_daily_minutes", "committed_minutes",
        "status",
    ]))
    return out


def store_visit(row):
    out = _base(row)
    out.update(_pick(row, [
        "application_id", "inspector_id", "visit_type", "window_minutes",
        "observed_inventory_lines", "observed_staple_shelf_linear_feet",
        "verified_qualifying_categories", "verified_perishable_categories",
        "verified_criterion_a_pass", "depth_of_stock_pass",
        "shelf_discrepancy_bps", "shelf_discrepancy_flag", "status",
    ]))
    _dt_fields(out, row, ["window_start", "window_end", "findings_submitted_at"])
    return out


def pos_transaction(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "terminal_deployment_id", "household_ebt_card_last4",
        "line_items", "snap_benefit_available_cents",
        "other_tender_offered_cents", "eligible_subtotal_cents",
        "ineligible_subtotal_cents", "tax_cents", "ebt_tender_cents",
        "other_tender_cents", "split_tender_applied", "flagged_line_skus",
        "decline_reason_code", "void_reason_code", "status",
    ]))
    return out


def redemption_period(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "period_index", "pos_derived_total_cents",
        "pos_derived_transaction_count", "imported_total_cents",
        "imported_transaction_count", "imported_large_transaction_cents",
        "imported_even_dollar_transaction_count", "redemption_total_cents",
        "transaction_count", "large_transaction_cents",
        "even_dollar_transaction_count", "reconciliation_variance_cents",
        "reconciliation_status", "size_expectation_cents", "anomaly_score",
        "flag_level", "status",
    ]))
    _dt_fields(out, row, ["period_start", "period_end", "closed_at"])
    return out


def _evidence_item(item):
    return {
        "evidence_type": item.get("evidence_type"),
        "observed_at": fmt_dt(item.get("observed_at")),
        "note": item.get("note"),
    }


def investigation(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "trigger_period_id", "opened_reason",
        "trafficking_confidence_score", "substantiated_violation",
        "opened_by_user_id", "concluded_by_user_id", "status",
    ]))
    items = row.get("evidence_items")
    out["evidence_items"] = ([_evidence_item(i) for i in items]
                            if items is not None else None)
    _dt_fields(out, row, ["concluded_at"])
    return out


def sanction_case(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "investigation_id", "predecessor_case_id",
        "violation_type", "charge_summary", "charge_issued_by_user_id",
        "reply_text", "prior_final_sanction_count", "sanction_type",
        "disqualification_months", "cmp_basis_variant", "cmp_basis_period_ids",
        "avg_monthly_redemption_cents", "monthly_penalty_cents",
        "cmp_amount_cents", "cmp_capped", "cmp_outstanding_cents",
        "determined_by_user_id", "grounds_text", "admin_review_outcome",
        "admin_review_decided_by_user_id", "remand_count", "reason_code",
        "status",
    ]))
    _dt_fields(out, row, [
        "charge_letter_sent_at", "reply_due_at", "cmp_election_due_at",
        "reply_received_at", "determined_at", "admin_review_due_at",
        "admin_review_requested_at", "admin_review_decided_at",
        "final_decision_at", "effective_date", "enforced_at",
    ])
    return out


def cmp_election(row):
    out = _base(row)
    out.update(_pick(row, [
        "sanction_case_id", "hardship_ownership_change_pending",
        "quoted_amount_cents", "quoted_basis_variant", "status",
    ]))
    _dt_fields(out, row, ["elected_at"])
    return out


def penalty_ledger_entry(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "sanction_case_id": row["sanction_case_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "reason_code": row["reason_code"],
        "balance_after_cents": row.get("balance_after_cents"),
    }


def equipment_depot(row):
    out = _base(row)
    out.update(_pick(row, [
        "state_code", "total_units_owned", "units_reserved", "units_deployed",
        "units_pending_return", "units_retired", "units_in_stock",
    ]))
    return out


def ebt_terminal(row):
    out = _base(row)
    out.update(_pick(row, ["depot_id", "serial_number", "model", "status"]))
    return out


def terminal_deployment(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "terminal_id", "close_reason_code", "status",
    ]))
    _dt_fields(out, row, ["deploy_start", "deploy_end", "activated_at",
                          "closed_at"])
    return out


def equipment_order(row):
    out = _base(row)
    out.update(_pick(row, [
        "store_id", "lines", "subtotal_cents", "subsidy_cents",
        "net_equipment_cents", "handling_fee_cents", "total_due_cents",
        "cancel_reason_code", "status",
    ]))
    _dt_fields(out, row, ["placed_at"])
    return out
