"""Serializers — convert in-memory records to API-shaped dicts.

Field names and set of fields per entity come from SCAFFOLD §1.1 and PRD §2.5.
"""

_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def producer_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "license_number": p["license_number"],
        "full_name": p["full_name"],
        "home_state_code": p["home_state_code"],
        "status": p["status"],
        "submitted_case_count_12m": p["submitted_case_count_12m"],
        "completed_exchange_count_12m": p["completed_exchange_count_12m"],
        "rescinded_exchange_count_12m": p["rescinded_exchange_count_12m"],
        "rescission_rate_completed_bps": p["rescission_rate_completed_bps"],
        "rescission_rate_submitted_bps": p["rescission_rate_submitted_bps"],
        "last_churn_eval_at": p["last_churn_eval_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def client_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "state_code": c["state_code"],
        "age_years": c["age_years"],
        "is_senior": c["is_senior"],
        "last_rescinded_at": c["last_rescinded_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def contract_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "client_id": c["client_id"],
        "carrier_name": c["carrier_name"],
        "contract_number": c["contract_number"],
        "issue_date": c["issue_date"],
        "account_value_cents": c["account_value_cents"],
        "tax_basis_cents": c["tax_basis_cents"],
        "surrender_schedule": list(c["surrender_schedule"]),
        "living_benefit_rider": c["living_benefit_rider"],
        "rider_benefit_base_cents": c["rider_benefit_base_cents"],
        "rider_annual_fee_bps": c["rider_annual_fee_bps"],
        "last_exchange_completed_at": c["last_exchange_completed_at"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def case_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "producer_id": c["producer_id"],
        "client_id": c["client_id"],
        "existing_contract_id": c["existing_contract_id"],
        "exchange_type": c["exchange_type"],
        "exchange_amount_cents": c["exchange_amount_cents"],
        "new_product_code": c["new_product_code"],
        "new_product_surrender_years": c["new_product_surrender_years"],
        "new_product_bonus_bps": c["new_product_bonus_bps"],
        "new_product_annual_fee_bps": c["new_product_annual_fee_bps"],
        "status": c["status"],
        "submitted_at": c["submitted_at"],
        "reviewed_by_id": c["reviewed_by_id"],
        "approved_by_id": c["approved_by_id"],
        "free_look_started_at": c["free_look_started_at"],
        "free_look_deadline_date": c["free_look_deadline_date"],
        "completed_at": c["completed_at"],
        "rescinded_at": c["rescinded_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def document_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "doc_type": d["doc_type"],
        "status": d["status"],
        "revision": d["revision"],
        "rejection_reason": d["rejection_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def analysis_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "assumed_old_growth_bps": a["assumed_old_growth_bps"],
        "assumed_new_growth_bps": a["assumed_new_growth_bps"],
        "analysis_date": a["analysis_date"],
        "exchange_base_cents": a["exchange_base_cents"],
        "surrender_pct_bps_today": a["surrender_pct_bps_today"],
        "surrender_charge_today_cents": a["surrender_charge_today_cents"],
        "surrender_pct_bps_at_settlement": a["surrender_pct_bps_at_settlement"],
        "surrender_charge_at_settlement_cents": a["surrender_charge_at_settlement_cents"],
        "amount_received_cents": a["amount_received_cents"],
        "bonus_credit_cents": a["bonus_credit_cents"],
        "benefit_loss_cents": a["benefit_loss_cents"],
        "net_replacement_cost_cents": a["net_replacement_cost_cents"],
        "break_even_years": a["break_even_years"],
        "basis_transferred_cents": a["basis_transferred_cents"],
        "basis_remaining_cents": a["basis_remaining_cents"],
        "status": a["status"],
        "supersedes_analysis_id": a["supersedes_analysis_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def transfer_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "case_id": t["case_id"],
        "amount_cents": t["amount_cents"],
        "surrender_charge_cents": t["surrender_charge_cents"],
        "basis_transferred_cents": t["basis_transferred_cents"],
        "pre_exchange_value_cents": t["pre_exchange_value_cents"],
        "pre_exchange_basis_cents": t["pre_exchange_basis_cents"],
        "status": t["status"],
        "requested_at": t["requested_at"],
        "received_at": t["received_at"],
        "returned_at": t["returned_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def review_decision_view(r: dict) -> dict:
    # Audit record: only id + created_at (no updated_at, no version) per PRD §2.5
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "stage": r["stage"],
        "reviewer_id": r["reviewer_id"],
        "decision": r["decision"],
        "rationale": r["rationale"],
        "created_at": r["created_at"],
    }


def activity_event_view(e: dict) -> dict:
    # Audit record: only id + created_at (no updated_at, no version) per PRD §2.5
    return {
        "id": e["id"],
        "producer_id": e["producer_id"],
        "case_id": e["case_id"],
        "event_type": e["event_type"],
        "event_at": e["event_at"],
        "created_at": e["created_at"],
    }
