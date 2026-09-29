"""Entity serializers. Every derived field is projected at read time so the
conserved-quantity invariant of PRD 2.11 can never drift."""
import ledger
import store
from util import fmt_ts, num


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_ts(row["created_at"])
    out["updated_at"] = fmt_ts(row["updated_at"])
    out["version"] = row["version"]
    return out


def _event(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_ts(row["created_at"])
    return out


def sponsor(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "legal_entity_type": row["legal_entity_type"],
        "performance_bond_cents": row["performance_bond_cents"],
        "banks_count": ledger.sponsor_banks_count(row["id"]),
        "good_standing": ledger.sponsor_good_standing(row["id"]),
    })


def permittee(row):
    rollup = ledger.permittee_rollup(row)
    return _common(row, {
        "organization_name": row["organization_name"],
        "permit_number": row["permit_number"],
        "impact_huc8_code": row["impact_huc8_code"],
        "required_credits": num(row["required_credits"]),
        "deposited_cents": rollup["deposited_cents"],
        "escrow_balance_cents": rollup["escrow_balance_cents"],
        "assigned_credits": num(rollup["assigned_credits"]),
        "unmet_requirement_credits": num(rollup["unmet_requirement_credits"]),
    })


def irt_member(row):
    return _common(row, {
        "member_name": row["member_name"],
        "agency": row["agency"],
        "veto_authority": row["agency"] == "USACE",
        "roster_status": row["roster_status"],
    })


def bank(row):
    aggregate = ledger.aggregates(row["id"])
    return _common(row, {
        "sponsor_id": row["sponsor_id"],
        "site_name": row["site_name"],
        "site_huc8_code": row["site_huc8_code"],
        "service_area_huc8_codes": list(row["service_area_huc8_codes"]),
        "hgm_class": row["hgm_class"],
        "annual_stewardship_cost_cents": row["annual_stewardship_cost_cents"],
        "status": row["status"],
        "sales_posture": ledger.sales_posture(row),
        "total_authorized_credits": num(row["total_authorized_credits"]),
        "credits_released": num(aggregate["credits_released"]),
        "credits_sold": num(aggregate["credits_sold"]),
        "credits_on_hold": num(aggregate["credits_on_hold"]),
        "credits_available": num(aggregate["credits_available"]),
        "stewardship_required_cents": row["stewardship_required_cents"],
        "stewardship_funded_cents": row["stewardship_funded_cents"],
        "easement_recorded": row["easement_recorded"],
        "easement_recorded_at": fmt_ts(row["easement_recorded_at"]),
        "easement_deed_reference": row["easement_deed_reference"],
        "deferral_count": row["deferral_count"],
        "open_quote_count": ledger.open_quote_count(row["id"]),
        "instrument_executed_at": fmt_ts(row["instrument_executed_at"]),
        "closed_at": fmt_ts(row["closed_at"]),
    })


def round_votes(prospectus_id, revision_round):
    return [v for v in store.prospectus_votes.values()
            if v["prospectus_id"] == prospectus_id
            and v["revision_round"] == revision_round]


def prospectus(row):
    votes = round_votes(row["id"], row["revision_round"])
    return _common(row, {
        "bank_id": row["bank_id"],
        "objective_summary": row["objective_summary"],
        "proposed_credits": num(row["proposed_credits"]),
        "status": row["status"],
        "revision_round": row["revision_round"],
        "submitted_at": fmt_ts(row["submitted_at"]),
        "review_opened_at": fmt_ts(row["review_opened_at"]),
        "concur_count": sum(1 for v in votes if v["position"] == "CONCUR"),
        "object_count": sum(1 for v in votes if v["position"] == "OBJECT"),
        "abstain_count": sum(1 for v in votes if v["position"] == "ABSTAIN"),
        "veto_recorded": any(v["is_veto"] for v in votes),
        "decision_recorded_by": row["decision_recorded_by"],
        "decided_at": fmt_ts(row["decided_at"]),
    })


def prospectus_vote(row):
    return _event(row, {
        "prospectus_id": row["prospectus_id"],
        "irt_member_id": row["irt_member_id"],
        "revision_round": row["revision_round"],
        "position": row["position"],
        "comment": row["comment"],
        "is_veto": row["is_veto"],
    })


def work_plan(row):
    return _common(row, {
        "bank_id": row["bank_id"],
        "hydrology_restoration_acres": num(row["hydrology_restoration_acres"]),
        "planting_acres": num(row["planting_acres"]),
        "invasive_control_acres": num(row["invasive_control_acres"]),
        "invasive_control_protocol": row["invasive_control_protocol"],
        "credit_strata": [{"stratum_code": s["stratum_code"],
                           "acres": num(s["acres"]),
                           "lift_factor": num(s["lift_factor"])}
                          for s in row["credit_strata"]],
        "performance_standards": [{"standard_code": s["standard_code"],
                                   "comparator": s["comparator"],
                                   "threshold_value": num(s["threshold_value"]),
                                   "weight": num(s["weight"]),
                                   "effective_from_year": s["effective_from_year"]}
                                  for s in row["performance_standards"]],
        "total_planned_credits": num(row["total_planned_credits"]),
        "status": row["status"],
        "submitted_at": fmt_ts(row["submitted_at"]),
        "decided_at": fmt_ts(row["decided_at"]),
        "return_reason": row["return_reason"],
    })


def performance_standard(row):
    return _common(row, {
        "bank_id": row["bank_id"],
        "standard_code": row["standard_code"],
        "comparator": row["comparator"],
        "threshold_value": num(row["threshold_value"]),
        "weight": num(row["weight"]),
        "effective_from_year": row["effective_from_year"],
    })


def milestone(row):
    return _common(row, {
        "bank_id": row["bank_id"],
        "predecessor_milestone_id": row["predecessor_milestone_id"],
        "milestone_code": row["milestone_code"],
        "release_pct": num(row["release_pct"]),
        "window_start": fmt_ts(row["window_start"]),
        "window_end": fmt_ts(row["window_end"]),
        "status": row["status"],
        "provisional_release_credits": num(row["provisional_release_credits"]),
        "final_release_credits": num(row["final_release_credits"]),
        "attainment_factor_applied": num(row["attainment_factor_applied"]),
        "claimed_at": fmt_ts(row["claimed_at"]),
        "approved_at": fmt_ts(row["approved_at"]),
        "deferred_at": fmt_ts(row["deferred_at"]),
    })


def monitoring_report(row):
    return _common(row, {
        "bank_id": row["bank_id"],
        "monitoring_year": row["monitoring_year"],
        "window_start": fmt_ts(row["window_start"]),
        "window_end": fmt_ts(row["window_end"]),
        "measurements": [{"standard_code": m["standard_code"],
                          "measured_value": num(m["measured_value"])}
                         for m in row["measurements"]],
        "review_status": row["review_status"],
        "compliance_status": row["compliance_status"],
        "attainment_score": num(row["attainment_score"]),
        "failed_standard_codes": list(row["failed_standard_codes"]),
        "reviewed_by_member_id": row["reviewed_by_member_id"],
        "submitted_at": fmt_ts(row["submitted_at"]),
        "reviewed_at": fmt_ts(row["reviewed_at"]),
        "return_count": row["return_count"],
    })


def remedial_action(row):
    return _common(row, {
        "monitoring_report_id": row["monitoring_report_id"],
        "deferred_milestone_id": row["deferred_milestone_id"],
        "verified_by_member_id": row["verified_by_member_id"],
        "status": row["status"],
        "round_number": row["round_number"],
        "corrective_scope": row["corrective_scope"],
        "held_credits": num(row["held_credits"]),
        "due_at": fmt_ts(row["due_at"]),
        "opened_at": fmt_ts(row["opened_at"]),
        "work_submitted_at": fmt_ts(row["work_submitted_at"]),
        "cleared_at": fmt_ts(row["cleared_at"]),
    })


def credit_sale(row):
    return _common(row, {
        "bank_id": row["bank_id"],
        "permittee_id": row["permittee_id"],
        "credits_requested": num(row["credits_requested"]),
        "impact_huc8_code": row["impact_huc8_code"],
        "service_area_tier": row["service_area_tier"],
        "status": row["status"],
        "quoted_demand_index": num(row["quoted_demand_index"]),
        "quoted_price_cents": row["quoted_price_cents"],
        "executed_price_cents": row["executed_price_cents"],
        "hold_start_at": fmt_ts(row["hold_start_at"]),
        "hold_expires_at": fmt_ts(row["hold_expires_at"]),
        "executed_at": fmt_ts(row["executed_at"]),
        "assigned_at": fmt_ts(row["assigned_at"]),
        "assignment_reference": row["assignment_reference"],
        "cancelled_reason": row["cancelled_reason"],
        "cancelled_at": fmt_ts(row["cancelled_at"]),
    })


def ledger_entry(row):
    return _event(row, {
        "bank_id": row["bank_id"],
        "sequence_number": row["sequence_number"],
        "entry_type": row["entry_type"],
        "delta_credits": num(row["delta_credits"]),
        "balance_after": num(row["balance_after"]),
        "source_entity_type": row["source_entity_type"],
        "source_id": row["source_id"],
        "memo": row["memo"],
    })
