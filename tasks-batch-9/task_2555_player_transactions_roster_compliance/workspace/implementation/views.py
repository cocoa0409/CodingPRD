"""Resource serialisers. created_at/updated_at carry three fractional digits."""
import domain
from store import fmt_ms, fmt_ts


def _stamps(record, out):
    out["created_at"] = fmt_ms(record["created_at"])
    out["updated_at"] = fmt_ms(record["updated_at"])
    out["version"] = record["version"]
    return out


def team(record):
    out = {
        "id": record["id"],
        "name": record["name"],
        "market_code": record["market_code"],
        "salary_cap_limit_cents": record["salary_cap_limit_cents"],
        "active_roster_limit": record["active_roster_limit"],
        "reserve_roster_limit": record["reserve_roster_limit"],
        "injured_reserve_limit": record["injured_reserve_limit"],
        "practice_squad_limit": record["practice_squad_limit"],
        "waiver_priority_rank": record["waiver_priority_rank"],
        "active_roster_count": record["active_roster_count"],
        "reserve_roster_count": record["reserve_roster_count"],
        "injured_reserve_count": record["injured_reserve_count"],
        "practice_squad_count": record["practice_squad_count"],
        "provisional_cap_committed_cents": record["provisional_cap_committed_cents"],
        "final_cap_committed_cents": record["final_cap_committed_cents"],
        "dead_money_cents": record["dead_money_cents"],
        "cap_space_cents": record["cap_space_cents"],
        "open_medical_review_count": record["open_medical_review_count"],
        "compliance_status": record["compliance_status"],
        "grace_expires_at": fmt_ts(record["grace_expires_at"]),
        "consecutive_noncompliant_checks": record["consecutive_noncompliant_checks"],
    }
    return _stamps(record, out)


def player(record):
    out = {
        "id": record["id"],
        "full_name": record["full_name"],
        "position": record["position"],
        "current_team_id": record["current_team_id"],
        "roster_designation": record["roster_designation"],
        "medical_status": record["medical_status"],
        "designation_effective_at": fmt_ts(record["designation_effective_at"]),
        "accrued_active_days": record["accrued_active_days"],
        "accrued_reserve_days": record["accrued_reserve_days"],
        "accrued_ir_days": record["accrued_ir_days"],
        "accrued_practice_days": record["accrued_practice_days"],
        "practice_squad_seasons_used": record["practice_squad_seasons_used"],
        "pension_credit_days": domain.pension_credit_days(record),
        "roster_service_days": domain.roster_service_days(record),
        "service_years": domain.service_years(record),
        "contract_rights_class": domain.contract_rights_class(record),
        "practice_squad_eligible": domain.practice_squad_eligible(record),
        "waiver_revocability_class": domain.waiver_revocability_class(),
        "last_physical_passed_at": fmt_ts(domain.last_physical_passed_at(record)),
    }
    return _stamps(record, out)


def contract(record):
    out = {
        "id": record["id"],
        "player_id": record["player_id"],
        "team_id": record["team_id"],
        "signed_via_transaction_id": record["signed_via_transaction_id"],
        "status": record["status"],
        "years": record["years"],
        "base_salary_cents": record["base_salary_cents"],
        "base_guaranteed": record["base_guaranteed"],
        "signing_bonus_cents": record["signing_bonus_cents"],
        "start_season_year": record["start_season_year"],
        "is_practice_squad_contract": record["is_practice_squad_contract"],
        "proration_years": record["proration_years"],
        "annual_proration_cents": record["annual_proration_cents"],
        "final_season_proration_cents": record["final_season_proration_cents"],
        "current_season_cap_charge_cents": record["current_season_cap_charge_cents"],
        "total_value_cents": record["total_value_cents"],
        "option_type": record["option_type"],
        "option_deadline_at": fmt_ts(record["option_deadline_at"]),
        "option_salary_cents": record["option_salary_cents"],
        "option_status": record["option_status"],
        "dead_money_current_season_cents": record["dead_money_current_season_cents"],
        "dead_money_next_season_cents": record["dead_money_next_season_cents"],
        "termination_reason": record["termination_reason"],
    }
    return _stamps(record, out)


def bonus_allocation(record):
    out = {
        "id": record["id"],
        "contract_id": record["contract_id"],
        "bonus_type": record["bonus_type"],
        "season_year": record["season_year"],
        "amount_cents": record["amount_cents"],
        "allocation_status": record["allocation_status"],
        "counts_against_provisional": record["counts_against_provisional"],
        "earned_at": fmt_ts(record["earned_at"]),
    }
    return _stamps(record, out)


def transaction(record):
    out = {
        "id": record["id"],
        "team_id": record["team_id"],
        "player_id": record["player_id"],
        "transaction_type": record["transaction_type"],
        "status": record["status"],
        "target_designation": record["target_designation"],
        "injury_designation_id": record["injury_designation_id"],
        "contract_id": record["contract_id"],
        "requires_physical": record["requires_physical"],
        "filing_deadline_at": fmt_ts(record["filing_deadline_at"]),
        "filed_at": fmt_ts(record["filed_at"]),
        "filed_by_user_id": record["filed_by_user_id"],
        "decided_at": fmt_ts(record["decided_at"]),
        "decided_by_user_id": record["decided_by_user_id"],
        "effective_at": fmt_ts(record["effective_at"]),
        "rejection_reason": record["rejection_reason"],
        "revision_count": record["revision_count"],
        "prior_designation": record["prior_designation"],
    }
    return _stamps(record, out)


def waiver_request(record):
    out = {
        "id": record["id"],
        "player_id": record["player_id"],
        "from_team_id": record["from_team_id"],
        "transaction_id": record["transaction_id"],
        "contract_id": record["contract_id"],
        "origin_designation": record["origin_designation"],
        "revocability": record["revocability"],
        "status": record["status"],
        "placed_at": fmt_ts(record["placed_at"]),
        "clearance_deadline_at": fmt_ts(record["clearance_deadline_at"]),
        "processed_at": fmt_ts(record["processed_at"]),
        "awarded_to_team_id": record["awarded_to_team_id"],
        "claim_count": record["claim_count"],
        "releasing_team_dead_money_cents": record["releasing_team_dead_money_cents"],
    }
    return _stamps(record, out)


def waiver_claim(record):
    out = {
        "id": record["id"],
        "waiver_request_id": record["waiver_request_id"],
        "claiming_team_id": record["claiming_team_id"],
        "status": record["status"],
        "priority_rank_snapshot": record["priority_rank_snapshot"],
        "cap_space_snapshot_cents": record["cap_space_snapshot_cents"],
        "required_cap_charge_cents": record["required_cap_charge_cents"],
        "submitted_at": fmt_ts(record["submitted_at"]),
    }
    return _stamps(record, out)


def trade(record):
    out = {
        "id": record["id"],
        "initiating_team_id": record["initiating_team_id"],
        "counterparty_team_id": record["counterparty_team_id"],
        "status": record["status"],
        "conditional_clause_type": record["conditional_clause_type"],
        "condition_note": record["condition_note"],
        "round_count": record["round_count"],
        "accepted_at": fmt_ts(record["accepted_at"]),
        "medical_review_deadline_at": fmt_ts(record["medical_review_deadline_at"]),
        "executed_at": fmt_ts(record["executed_at"]),
        "void_reason": record["void_reason"],
        "cap_delta_initiating_cents": record["cap_delta_initiating_cents"],
        "cap_delta_counterparty_cents": record["cap_delta_counterparty_cents"],
    }
    return _stamps(record, out)


def trade_asset(record):
    out = {
        "id": record["id"],
        "trade_id": record["trade_id"],
        "asset_kind": record["asset_kind"],
        "direction": record["direction"],
        "contract_id": record["contract_id"],
        "draft_pick_year": record["draft_pick_year"],
        "draft_pick_round": record["draft_pick_round"],
        "cash_amount_cents": record["cash_amount_cents"],
        "status": record["status"],
        "cap_charge_snapshot_cents": record["cap_charge_snapshot_cents"],
    }
    return _stamps(record, out)


def qualifying_offer(record):
    out = {
        "id": record["id"],
        "player_id": record["player_id"],
        "team_id": record["team_id"],
        "offer_type": record["offer_type"],
        "tender_level": record["tender_level"],
        "prior_base_salary_cents": record["prior_base_salary_cents"],
        "amount_cents": record["amount_cents"],
        "status": record["status"],
        "issued_at": fmt_ts(record["issued_at"]),
        "deadline_at": fmt_ts(record["deadline_at"]),
        "responded_at": fmt_ts(record["responded_at"]),
        "resulting_transaction_id": record["resulting_transaction_id"],
    }
    return _stamps(record, out)


def injury_designation(record):
    out = {
        "id": record["id"],
        "player_id": record["player_id"],
        "team_id": record["team_id"],
        "designation_type": record["designation_type"],
        "status": record["status"],
        "paperwork_reference": record["paperwork_reference"],
        "placed_at": fmt_ts(record["placed_at"]),
        "paperwork_filed_at": fmt_ts(record["paperwork_filed_at"]),
        "activated_at": fmt_ts(record["activated_at"]),
        "minimum_stay_days": record["minimum_stay_days"],
        "return_window_opens_at": fmt_ts(record["return_window_opens_at"]),
        "return_window_closes_at": fmt_ts(record["return_window_closes_at"]),
        "ir_service_credit_days": record["ir_service_credit_days"],
        "closed_at": fmt_ts(record["closed_at"]),
    }
    return _stamps(record, out)


def physical_exam(record):
    out = {
        "id": record["id"],
        "player_id": record["player_id"],
        "team_id": record["team_id"],
        "transaction_id": record["transaction_id"],
        "trade_id": record["trade_id"],
        "exam_type": record["exam_type"],
        "status": record["status"],
        "window_start_at": fmt_ts(record["window_start_at"]),
        "window_end_at": fmt_ts(record["window_end_at"]),
        "performed_at": fmt_ts(record["performed_at"]),
        "result_recorded_at": fmt_ts(record["result_recorded_at"]),
        "expires_at": fmt_ts(record["expires_at"]),
    }
    return _stamps(record, out)


def compliance_check(record):
    """PRD 2.4: this audit row carries id and created_at only - no updated_at, no version."""
    return {
        "id": record["id"],
        "team_id": record["team_id"],
        "checked_at": fmt_ts(record["checked_at"]),
        "active_roster_count": record["active_roster_count"],
        "reserve_roster_count": record["reserve_roster_count"],
        "injured_reserve_count": record["injured_reserve_count"],
        "practice_squad_count": record["practice_squad_count"],
        "final_cap_committed_cents": record["final_cap_committed_cents"],
        "cap_space_cents": record["cap_space_cents"],
        "violation_codes": list(record["violation_codes"]),
        "result": record["result"],
        "grace_expires_at": fmt_ts(record["grace_expires_at"]),
        "resulting_compliance_status": record["resulting_compliance_status"],
        "created_at": fmt_ms(record["created_at"]),
    }
