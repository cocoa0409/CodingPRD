"""Explicit per-entity JSON projections.  Internal bookkeeping keys (prefixed
with an underscore) never leave the process."""
import calc
from util import num_out


def _common(rec):
    return {
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def project_out(project):
    out = {
        "id": project["id"],
        "name": project["name"],
        "route_designation": project["route_designation"],
        "letting_date": project["letting_date"],
        "construction_start_date": project["construction_start_date"],
        "construction_end_date": project["construction_end_date"],
        "row_acquisition_year": project["row_acquisition_year"],
        "reimbursement_authority_cents": project["reimbursement_authority_cents"],
        "contract_daily_overhead_cents": project["contract_daily_overhead_cents"],
        "status": project["status"],
        "clearance_posture": calc.clearance_posture(project),
        "open_conflict_count": calc.project_open_conflict_count(project),
        "estimated_state_liability_cents": calc.project_state_liability(project),
        "total_committed_reimbursement_cents": calc.project_committed_ledger(project),
        "aggregate_compensable_delay_days": calc.project_aggregate_compensable_delay_days(project),
    }
    out.update(_common(project))
    return out


def owner_out(owner):
    out = {
        "id": owner["id"],
        "legal_name": owner["legal_name"],
        "utility_type": owner["utility_type"],
        "is_public_agency": owner["is_public_agency"],
        "indirect_cost_rate_pct": num_out(owner["indirect_cost_rate_pct"]),
        "delinquency_strikes": owner["delinquency_strikes"],
        "reimbursement_hold": owner["reimbursement_hold"],
        "open_commitment_days": calc.owner_open_commitment_days(owner),
        "assessed_delay_liability_cents": calc.owner_assessed_delay_liability(owner),
    }
    out.update(_common(owner))
    return out


def facility_out(facility):
    out = {
        "id": facility["id"],
        "owner_id": facility["owner_id"],
        "facility_type": facility["facility_type"],
        "station_begin": facility["station_begin"],
        "station_end": facility["station_end"],
        "offset_ft": facility["offset_ft"],
        "depth_in": facility["depth_in"],
        "material": facility["material"],
        "installed_year": facility["installed_year"],
        "occupancy_basis": facility["occupancy_basis"],
        "record_source": facility["record_source"],
    }
    out.update(_common(facility))
    return out


def investigation_out(investigation):
    # Immutable: no updated_at and no version.
    return {
        "id": investigation["id"],
        "project_id": investigation["project_id"],
        "facility_id": investigation["facility_id"],
        "quality_level": investigation["quality_level"],
        "method": investigation["method"],
        "measured_depth_in": investigation["measured_depth_in"],
        "station_at_investigation": investigation["station_at_investigation"],
        "performed_at": investigation["performed_at"],
        "contradicts_record": investigation["contradicts_record"],
        "created_at": investigation["created_at"],
    }


def conflict_out(conflict):
    out = {
        "id": conflict["id"],
        "project_id": conflict["project_id"],
        "facility_id": conflict["facility_id"],
        "depends_on_conflict_id": conflict["depends_on_conflict_id"],
        "conflict_station": conflict["conflict_station"],
        "clearance_deficiency_in": conflict["clearance_deficiency_in"],
        "resolution_type": conflict["resolution_type"],
        "state_share_pct": conflict["state_share_pct"],
        "status": conflict["status"],
    }
    out.update(_common(conflict))
    return out


def determination_out(determination):
    out = {
        "id": determination["id"],
        "conflict_id": determination["conflict_id"],
        "claimed_basis": determination["claimed_basis"],
        "narrative": determination["narrative"],
        "evidence_variant": determination["evidence_variant"],
        "provisional_state_share_pct": determination["provisional_state_share_pct"],
        "final_state_share_pct": determination["final_state_share_pct"],
        "appeal_round": determination["appeal_round"],
        "first_issued_by_user_id": determination["first_issued_by_user_id"],
        "status": determination["status"],
    }
    out.update(_common(determination))
    return out


def plan_out(plan):
    out = {
        "id": plan["id"],
        "conflict_id": plan["conflict_id"],
        "revision_round": plan["revision_round"],
        "estimated_cost_cents": plan["estimated_cost_cents"],
        "replacement_in_kind_cost_cents": plan["replacement_in_kind_cost_cents"],
        "proposed_capacity_ratio": plan["proposed_capacity_ratio"],
        "work_days": plan["work_days"],
        "joint_trench_requested": plan["joint_trench_requested"],
        "betterment_ratio": num_out(plan["betterment_ratio"]),
        "betterment_amount_cents": plan["betterment_amount_cents"],
        "status": plan["status"],
    }
    out.update(_common(plan))
    return out


def permit_out(permit):
    out = {
        "id": permit["id"],
        "conflict_id": permit["conflict_id"],
        "permit_type": permit["permit_type"],
        "applied_on": permit["applied_on"],
        "granted_on": permit["granted_on"],
        "expires_on": permit["expires_on"],
        "decision_note": permit["decision_note"],
        "status": permit["status"],
    }
    out.update(_common(permit))
    return out


def slot_out(slot):
    out = {
        "id": slot["id"],
        "project_id": slot["project_id"],
        "segment_code": slot["segment_code"],
        "trench_open_start": slot["trench_open_start"],
        "trench_open_end": slot["trench_open_end"],
        "max_occupants": slot["max_occupants"],
        "occupant_count": calc.slot_occupant_count(slot),
        "status": calc.slot_status(slot),
    }
    out.update(_common(slot))
    return out


def commitment_out(commitment):
    out = {
        "id": commitment["id"],
        "plan_id": commitment["plan_id"],
        "project_id": commitment["project_id"],
        "facility_id": commitment["facility_id"],
        "owner_id": commitment["owner_id"],
        "joint_trench_slot_id": commitment["joint_trench_slot_id"],
        "window_start": commitment["window_start"],
        "window_end": commitment["window_end"],
        "committed_work_days": commitment["committed_work_days"],
        "phase_dependency": commitment["phase_dependency"],
        "actual_complete_at": commitment["actual_complete_at"],
        "late_days": commitment["late_days"],
        "status": commitment["status"],
    }
    out.update(_common(commitment))
    return out


def agreement_out(agreement):
    out = {
        "id": agreement["id"],
        "plan_id": agreement["plan_id"],
        "project_id": agreement["project_id"],
        "owner_id": agreement["owner_id"],
        "not_to_exceed_cents": agreement["not_to_exceed_cents"],
        "cost_basis": agreement["cost_basis"],
        "eligible_cost_cents": agreement["eligible_cost_cents"],
        "indirect_cost_cents": agreement["indirect_cost_cents"],
        "betterment_credit_cents": agreement["betterment_credit_cents"],
        "net_allowable_cents": agreement["net_allowable_cents"],
        "participation_tier_pct": agreement["participation_tier_pct"],
        "state_share_cents": agreement["state_share_cents"],
        "owner_share_cents": agreement["owner_share_cents"],
        "as_built_reference": agreement["as_built_reference"],
        "executed_by_user_id": agreement["executed_by_user_id"],
        "execution_status": agreement["execution_status"],
        "settlement_status": agreement["settlement_status"],
    }
    out.update(_common(agreement))
    return out


def document_out(document):
    out = {
        "id": document["id"],
        "agreement_id": document["agreement_id"],
        "doc_type": document["doc_type"],
        "amount_cents": document["amount_cents"],
        "incurred_on": document["incurred_on"],
        "support_reference": document["support_reference"],
        "disallowed_amount_cents": document["disallowed_amount_cents"],
        "exclusion_reason": document["exclusion_reason"],
        "review_status": document["review_status"],
    }
    out.update(_common(document))
    return out


def finding_out(finding):
    out = {
        "id": finding["id"],
        "agreement_id": finding["agreement_id"],
        "finding_type": finding["finding_type"],
        "questioned_cost_cents": finding["questioned_cost_cents"],
        "auditor_user_id": finding["auditor_user_id"],
        "disposition": finding["disposition"],
        "status": finding["status"],
    }
    out.update(_common(finding))
    return out


def claim_out(claim):
    out = {
        "id": claim["id"],
        "project_id": claim["project_id"],
        "commitment_id": claim["commitment_id"],
        "contractor_name": claim["contractor_name"],
        "claimed_days": claim["claimed_days"],
        "claimed_amount_cents": claim["claimed_amount_cents"],
        "delay_cause": claim["delay_cause"],
        "compensable_days": claim["compensable_days"],
        "daily_rate_cents": claim["daily_rate_cents"],
        "allocated_to_owner_cents": claim["allocated_to_owner_cents"],
        "allocated_to_state_cents": claim["allocated_to_state_cents"],
        "status": claim["status"],
    }
    out.update(_common(claim))
    return out
