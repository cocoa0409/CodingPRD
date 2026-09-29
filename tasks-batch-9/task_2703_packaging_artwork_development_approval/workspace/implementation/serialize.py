"""Response projections. The four conserved ledgers and the three computed counters of
PRD 2.9 are derived here as sums over subordinate rows, never stored as operator input."""
from calc import number, one_dp
from core import db, rows


# ---------------------------------------------------------------- ledgers
def asset_plate_orders(asset_id):
    result = []
    for order in rows("plate_orders"):
        version = db.versions.get(order["artwork_version_id"])
        if version is not None and version["artwork_asset_id"] == asset_id:
            result.append(order)
    return result


def committed_plate_cost(asset_id):
    return sum(o["cost_cents"] for o in asset_plate_orders(asset_id) if o["status"] == "ORDERED")


def scrapped_runouts(asset_id):
    return [
        r
        for r in rows("runouts")
        if r["artwork_asset_id"] == asset_id and r["state"] == "SCRAPPED"
    ]


def obsolete_units_total(asset_id):
    return sum(r["units_scrapped"] for r in scrapped_runouts(asset_id))


def changeover_cost_committed(asset_id):
    return sum(r["total_changeover_cost_cents"] for r in scrapped_runouts(asset_id))


def recovery_balance(printer_id):
    total = 0
    for escape in rows("escapes"):
        if escape["printer_id"] == printer_id and escape["state"] == "SETTLED":
            total += escape.get("final_recovery_cents") or 0
    return total


def asset_count(brief_id):
    return len([a for a in rows("assets") if a["brief_id"] == brief_id])


def claim_usage_count(claim_id):
    return len([v for v in rows("versions") if claim_id in (v.get("claim_ids") or [])])


def escape_count(printer_id):
    return len([e for e in rows("escapes") if e["printer_id"] == printer_id])


# ---------------------------------------------------------------- projections
def brief_json(row):
    return {
        "id": row["id"],
        "sku_code": row["sku_code"],
        "product_name": row["product_name"],
        "regulatory_scheme": row["regulatory_scheme"],
        "market_codes": list(row["market_codes"]),
        "language_codes": list(row["language_codes"]),
        "required_element_codes": list(row["required_element_codes"]),
        "structural_spec": row["structural_spec"],
        "net_contents_declaration": row["net_contents_declaration"],
        "status": row["status"],
        "asset_count": asset_count(row["id"]),
        "review_note": row.get("review_note"),
        "approved_by_user_id": row.get("approved_by_user_id"),
        "approved_at": row.get("approved_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def claim_json(row):
    return {
        "id": row["id"],
        "claim_code": row["claim_code"],
        "claim_text": row["claim_text"],
        "claim_type": row["claim_type"],
        "market_code": row["market_code"],
        "substantiation_ref": row["substantiation_ref"],
        "legal_status": row["legal_status"],
        "cleared_from_utc": row.get("cleared_from_utc"),
        "cleared_until_utc": row.get("cleared_until_utc"),
        "cleared_by_user_id": row.get("cleared_by_user_id"),
        "rejection_reason": row.get("rejection_reason"),
        "usage_count": claim_usage_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def asset_json(row):
    return {
        "id": row["id"],
        "brief_id": row["brief_id"],
        "market_code": row["market_code"],
        "language_codes": list(row["language_codes"]),
        "component_type": row["component_type"],
        "substrate_class": row["substrate_class"],
        "brand_critical_color": row["brand_critical_color"],
        "plate_budget_cents": row["plate_budget_cents"],
        "standard_unit_cost_cents": row["standard_unit_cost_cents"],
        "obsolescence_state": row["obsolescence_state"],
        "version_counter": row["version_counter"],
        "current_approved_version_id": row.get("current_approved_version_id"),
        "committed_plate_cost_cents": committed_plate_cost(row["id"]),
        "obsolete_units_total": obsolete_units_total(row["id"]),
        "changeover_cost_committed_cents": changeover_cost_committed(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def version_json(row):
    score = row.get("compliance_score")
    return {
        "id": row["id"],
        "artwork_asset_id": row["artwork_asset_id"],
        "version_no": row["version_no"],
        "state": row["state"],
        "reason_for_change_code": row["reason_for_change_code"],
        "change_description": row["change_description"],
        "mandatory_elements": row["mandatory_elements"],
        "claim_ids": list(row["claim_ids"]),
        "supersedes_version_id": row.get("supersedes_version_id"),
        "author_user_id": row["author_user_id"],
        "check_run_no": row["check_run_no"],
        "revision_cycle_count": row["revision_cycle_count"],
        "route_count": row["route_count"],
        "requires_reverification": row["requires_reverification"],
        "open_condition_codes": list(row["open_condition_codes"]),
        "pinned_claim_snapshot": list(row["pinned_claim_snapshot"]),
        "compliance_score": None if score is None else one_dp(score),
        "failed_element_count": row["failed_element_count"],
        "waived_element_count": row["waived_element_count"],
        "submit_note": row.get("submit_note"),
        "revise_note": row.get("revise_note"),
        "release_note": row.get("release_note"),
        "verification_note": row.get("verification_note"),
        "approved_at": row.get("approved_at"),
        "released_at": row.get("released_at"),
        "obsoleted_at": row.get("obsoleted_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def element_check_json(row):
    return {
        "id": row["id"],
        "artwork_version_id": row["artwork_version_id"],
        "check_run_no": row["check_run_no"],
        "element_code": row["element_code"],
        "severity": row["severity"],
        "result": row["result"],
        "detail": row["detail"],
        "deduction_points": number(row["deduction_points"]),
        "waived_by_user_id": row.get("waived_by_user_id"),
        "waiver_justification": row.get("waiver_justification"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def route_json(row):
    return {
        "id": row["id"],
        "artwork_version_id": row["artwork_version_id"],
        "route_no": row["route_no"],
        "status": row["status"],
        "current_stage_no": row["current_stage_no"],
        "stage_plan": row["stage_plan"],
        "conditional_count": row["conditional_count"],
        "submit_note": row.get("submit_note"),
        "completed_at": row.get("completed_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def task_json(row):
    return {
        "id": row["id"],
        "review_route_id": row["review_route_id"],
        "artwork_version_id": row["artwork_version_id"],
        "discipline": row["discipline"],
        "mode": row["mode"],
        "stage_no": row["stage_no"],
        "is_active": row["is_active"],
        "decision": row["decision"],
        "comment": row.get("comment"),
        "condition_code": row.get("condition_code"),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "decided_at": row.get("decided_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def printer_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "color_standard": row["color_standard"],
        "certified_substrates": list(row["certified_substrates"]),
        "recovery_liability_cap_cents": row["recovery_liability_cap_cents"],
        "certification_status": row["certification_status"],
        "performance_score": one_dp(row["performance_score"]),
        "recovery_balance_cents": recovery_balance(row["id"]),
        "escape_count": escape_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def proof_json(row):
    measured = row.get("measured_delta_e_max")
    return {
        "id": row["id"],
        "artwork_version_id": row["artwork_version_id"],
        "printer_id": row["printer_id"],
        "substrate_code": row["substrate_code"],
        "proof_no": row["proof_no"],
        "proof_note": row.get("proof_note"),
        "color_status": row["color_status"],
        "substrate_status": row["substrate_status"],
        "press_check_status": row["press_check_status"],
        "press_check_required": row["press_check_required"],
        "proof_state": row["proof_state"],
        "requires_recheck": row["requires_recheck"],
        "effective_tolerance": float(row["effective_tolerance"]),
        "measured_delta_e_max": None if measured is None else float(measured),
        "press_line_code": row.get("press_line_code"),
        "press_check_start_utc": row.get("press_check_start_utc"),
        "press_check_end_utc": row.get("press_check_end_utc"),
        "attended_by_user_id": row.get("attended_by_user_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def plate_order_json(row):
    return {
        "id": row["id"],
        "artwork_version_id": row["artwork_version_id"],
        "printer_id": row["printer_id"],
        "printer_proof_id": row["printer_proof_id"],
        "plate_set_count": row["plate_set_count"],
        "expedite": row["expedite"],
        "plate_subtotal_cents": row["plate_subtotal_cents"],
        "setup_fee_cents": row["setup_fee_cents"],
        "expedite_fee_cents": row["expedite_fee_cents"],
        "cost_cents": row["cost_cents"],
        "status": row["status"],
        "auto_cancelled": row["auto_cancelled"],
        "cancel_reason": row.get("cancel_reason"),
        "cancelled_at": row.get("cancelled_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def runout_json(row):
    return {
        "id": row["id"],
        "artwork_asset_id": row["artwork_asset_id"],
        "obsolete_version_id": row["obsolete_version_id"],
        "on_hand_qty": row["on_hand_qty"],
        "weekly_usage_qty": row["weekly_usage_qty"],
        "runout_start_utc": row["runout_start_utc"],
        "state": row["state"],
        "depletion_records": list(row["depletion_records"]),
        "remaining_qty": row["remaining_qty"],
        "trailing_avg_usage_qty": row.get("trailing_avg_usage_qty"),
        "projected_runout_date": row["projected_runout_date"],
        "actual_runout_date": row.get("actual_runout_date"),
        "disposition": row.get("disposition"),
        "units_scrapped": row["units_scrapped"],
        "units_reworked": row["units_reworked"],
        "material_writeoff_cents": row["material_writeoff_cents"],
        "relabel_cost_cents": row["relabel_cost_cents"],
        "changeover_base_cents": row["changeover_base_cents"],
        "changeover_expedite_cents": row["changeover_expedite_cents"],
        "total_changeover_cost_cents": row["total_changeover_cost_cents"],
        "reversal_count": row["reversal_count"],
        "reversal_reason": row.get("reversal_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def escape_json(row):
    share = row.get("printer_share_pct")
    return {
        "id": row["id"],
        "artwork_version_id": row["artwork_version_id"],
        "printer_id": row["printer_id"],
        "defect_code": row["defect_code"],
        "discovered_stage": row["discovered_stage"],
        "units_affected": row["units_affected"],
        "discovery_note": row.get("discovery_note"),
        "state": row["state"],
        "investigation_fee_cents": row["investigation_fee_cents"],
        "root_cause_party": row.get("root_cause_party"),
        "printer_share_pct": None if share is None else float(share),
        "investigation_note": row.get("investigation_note"),
        "provisional_recovery_cents": row.get("provisional_recovery_cents"),
        "liability_cap_applied": row["liability_cap_applied"],
        "dispute_reason": row.get("dispute_reason"),
        "dispute_count": row["dispute_count"],
        "actual_reprint_cost_cents": row.get("actual_reprint_cost_cents"),
        "actual_scrap_cost_cents": row.get("actual_scrap_cost_cents"),
        "actual_expedite_freight_cents": row.get("actual_expedite_freight_cents"),
        "final_recovery_cents": row.get("final_recovery_cents"),
        "recovery_variance_cents": row.get("recovery_variance_cents"),
        "resolution": row.get("resolution"),
        "settlement_note": row.get("settlement_note"),
        "settled_at": row.get("settled_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
