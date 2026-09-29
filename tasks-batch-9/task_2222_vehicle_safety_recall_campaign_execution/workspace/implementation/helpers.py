"""Lookups, shared gates, cascades and serializers."""
from datetime import timedelta
from decimal import Decimal

import calc
from db import (base_record, clock_date, clock_now, fmt_instant, parse_date,
                parse_instant, store, touch)
from errors import ApiError

TERMINAL_CAMPAIGN_STATES = ("CLOSED", "SUPERSEDED")


# --------------------------------------------------------------------------
# path / body lookups
# --------------------------------------------------------------------------
def get_campaign(campaign_id):
    row = store.campaigns.get(campaign_id)
    if row is None:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND")
    return row


def get_vehicle(vehicle_id):
    row = store.vehicles.get(vehicle_id)
    if row is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    return row


def get_av(av_id):
    row = store.affected_vehicles.get(av_id)
    if row is None:
        raise ApiError("ERR_AFFECTED_VEHICLE_NOT_FOUND")
    return row


def get_wave(wave_id):
    row = store.waves.get(wave_id)
    if row is None:
        raise ApiError("ERR_WAVE_NOT_FOUND")
    return row


def get_dealer(dealer_id):
    row = store.dealers.get(dealer_id)
    if row is None:
        raise ApiError("ERR_DEALER_NOT_FOUND")
    return row


def get_part(part_id):
    row = store.remedy_parts.get(part_id)
    if row is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    return row


def get_allocation(allocation_id):
    row = store.allocations.get(allocation_id)
    if row is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    return row


def get_labor_op(labor_op_id):
    row = store.labor_operations.get(labor_op_id)
    if row is None:
        raise ApiError("ERR_LABOR_OP_NOT_FOUND")
    return row


def get_claim(claim_id):
    row = store.repair_claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return row


def get_reimbursement(request_id):
    row = store.reimbursements.get(request_id)
    if row is None:
        raise ApiError("ERR_REIMBURSEMENT_NOT_FOUND")
    return row


# --------------------------------------------------------------------------
# shared gates
# --------------------------------------------------------------------------
def assert_campaign_writable(campaign, allowed=None):
    if campaign["campaign_status"] in TERMINAL_CAMPAIGN_STATES:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    if allowed is not None and campaign["campaign_status"] not in allowed:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")


def recompute_effectiveness(campaign):
    """PRD 3.9 - refresh the campaign's persisted remedy_effectiveness_score."""
    campaign["remedy_effectiveness_score"] = calc.remedy_effectiveness_score(campaign)


def assert_remedy_available(campaign):
    if campaign["remedy_status"] in ("REMEDY_UNDER_DEVELOPMENT", "INTERIM_ONLY"):
        raise ApiError("ERR_REMEDY_NOT_AVAILABLE")


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------
def return_units_to_pool(allocation, reason):
    """Revoke an ALLOCATED allocation, returning its uncommitted units."""
    part = store.remedy_parts.get(allocation["remedy_part_id"])
    returned = allocation["allocated_qty"] - allocation["consumed_qty"]
    allocation["status"] = "REVOKED"
    allocation["revoked_reason"] = reason
    touch(allocation)
    if part is not None:
        part["unallocated_qty"] = part["unallocated_qty"] + returned
        touch(part)


def revoke_campaign_allocations(campaign, reason):
    for alloc in calc.campaign_allocations(campaign["id"]):
        if alloc["status"] == "ALLOCATED":
            return_units_to_pool(alloc, reason)


def cancel_open_waves(campaign, reason):
    for wave in calc.campaign_waves(campaign["id"]):
        if wave["status"] in ("PLANNED", "RELEASE_APPROVED"):
            wave["status"] = "CANCELLED"
            wave["cancel_reason"] = reason
            touch(wave)


def supersede_campaign(target):
    """PRD 3.1 - supersession cascade on the replaced campaign."""
    target["campaign_status"] = "SUPERSEDED"
    cancel_open_waves(target, "CAMPAIGN_SUPERSEDED")
    revoke_campaign_allocations(target, "CAMPAIGN_SUPERSEDED")
    touch(target)


def next_wave_sequence_number(campaign_id):
    siblings = [w for w in calc.campaign_waves(campaign_id)
                if w["status"] != "CANCELLED"]
    return 1 + len(siblings)


def create_wave(campaign, wave_type, region, mail_date_str, auto_created=False):
    wave = base_record()
    wave.update({
        "campaign_id": campaign["id"],
        "wave_type": wave_type,
        "target_region_code": region,
        "scheduled_mail_date": mail_date_str,
        "sequence_number": next_wave_sequence_number(campaign["id"]),
        "status": "PLANNED",
        "eligible_vehicle_count": 0,
        "parts_capacity_qty": 0,
        "provisional_coverage_ratio": Decimal("0.0000"),
        "coverage_tier_factor": Decimal("0.00"),
        "planned_vehicle_count": 0,
        "parts_coverage_ratio": Decimal("0.0000"),
        "mailed_vehicle_count": 0,
        "actual_mail_date": None,
        "auto_created": auto_created,
        "cancel_reason": None,
    })
    store.waves[wave["id"]] = wave
    return wave


def cascade_remedy_revision(campaign, filing):
    """Cascade B (PRD 2.5 / 3.4)."""
    campaign["remedy_status"] = "REMEDY_REVISED"
    campaign["remedy_revision_count"] = campaign["remedy_revision_count"] + 1
    for av in calc.campaign_avs(campaign["id"]):
        if av["remedy_status"] == "REMEDIED":
            av["remedy_status"] = "UNREPAIRED"
            av["requires_renotification"] = True
            touch(av)
    if filing is not None:
        filing["amendment_required"] = True
    revoke_campaign_allocations(campaign, "REMEDY_REVISED")
    touch(campaign)


def followup_wave_autoschedule(campaign, av):
    """Cascade A link 3 (PRD 3.8)."""
    if campaign["campaign_status"] != "MONITORING":
        return None
    if calc.regulatory_completion_rate(campaign["id"]) >= calc.FOLLOWUP_TRIGGER_PCT:
        return None
    vehicle = store.vehicles.get(av["vehicle_id"])
    if vehicle is None:
        return None
    region = vehicle["region_code"]
    waves = calc.campaign_waves(campaign["id"])
    for wave in waves:
        if (wave["wave_type"] == "FOLLOW_UP"
                and wave["target_region_code"] == region
                and wave["status"] in ("PLANNED", "RELEASE_APPROVED")):
            return None
    candidate = clock_date() + timedelta(days=calc.FOLLOWUP_LEAD_DAYS)
    blocking = [w for w in waves
                if w["target_region_code"] == region
                and w["status"] in ("PLANNED", "RELEASE_APPROVED", "MAILED")]
    while any(abs((candidate - parse_date(w["scheduled_mail_date"])).days)
              < calc.MIN_WAVE_SEPARATION_DAYS for w in blocking):
        candidate = candidate + timedelta(days=1)
    return create_wave(campaign, "FOLLOW_UP", region, candidate.isoformat(),
                       auto_created=True)


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------
def campaign_out(campaign):
    buckets = calc.population_buckets(campaign["id"])
    return {
        "id": campaign["id"],
        "campaign_number": campaign["campaign_number"],
        "defect_type": campaign["defect_type"],
        "defect_description": campaign["defect_description"],
        "risk_severity": campaign["risk_severity"],
        "campaign_status": campaign["campaign_status"],
        "remedy_status": campaign["remedy_status"],
        "supersedes_campaign_id": campaign["supersedes_campaign_id"],
        "defect_determination_date": campaign["defect_determination_date"],
        "filing_deadline_utc": campaign["filing_deadline_utc"],
        "filed_at": campaign["filed_at"],
        "days_late": campaign["days_late"],
        "late_filing_flag": campaign["late_filing_flag"],
        "determined_by_user_id": campaign["determined_by_user_id"],
        "remedy_released_by_user_id": campaign["remedy_released_by_user_id"],
        "remedy_released_at": campaign["remedy_released_at"],
        "remedy_revision_count": campaign["remedy_revision_count"],
        "stop_sale_flag": campaign["stop_sale_flag"],
        "do_not_drive_flag": campaign["do_not_drive_flag"],
        "affected_vehicle_count": buckets["total"],
        "recall_population_count": buckets["recall_population"],
        "remedied_count": buckets["remedied"],
        "completion_rate_pct": calc.num(
            calc.regulatory_completion_rate(campaign["id"], buckets)),
        "remedy_effectiveness_score": calc.num(
            campaign["remedy_effectiveness_score"]),
        "reimbursement_obligation_cents": calc.reimbursement_obligation_cents(
            campaign["id"]),
        "quarterly_filing_count": campaign["quarterly_filing_count"],
        "open_followup_wave_count": calc.open_followup_wave_count(campaign["id"]),
        "closure_note": campaign["closure_note"],
        "created_at": campaign["created_at"],
        "updated_at": campaign["updated_at"],
        "version": campaign["version"],
    }


def rule_out(rule):
    return {
        "id": rule["id"],
        "campaign_id": rule["campaign_id"],
        "inclusion_mode": rule["inclusion_mode"],
        "plant_code": rule["plant_code"],
        "model_code": rule["model_code"],
        "model_year": rule["model_year"],
        "production_start_date": rule["production_start_date"],
        "production_end_date": rule["production_end_date"],
        "part_number_low": rule["part_number_low"],
        "part_number_high": rule["part_number_high"],
        "matched_vehicle_count": calc.rule_matched_count(rule["id"]),
        "created_at": rule["created_at"],
        "updated_at": rule["updated_at"],
        "version": rule["version"],
    }


def vehicle_out(vehicle):
    return {
        "id": vehicle["id"],
        "vin": vehicle["vin"],
        "plant_code": vehicle["plant_code"],
        "model_code": vehicle["model_code"],
        "model_year": vehicle["model_year"],
        "production_date": vehicle["production_date"],
        "suspect_part_number": vehicle["suspect_part_number"],
        "in_service_date": vehicle["in_service_date"],
        "region_code": vehicle["region_code"],
        "sale_status": vehicle["sale_status"],
        "owner_name": vehicle["owner_name"],
        "owner_address_valid": vehicle["owner_address_valid"],
        "stop_sale_hold": vehicle["stop_sale_hold"],
        "created_at": vehicle["created_at"],
        "updated_at": vehicle["updated_at"],
        "version": vehicle["version"],
    }


def av_out(av):
    return {
        "id": av["id"],
        "campaign_id": av["campaign_id"],
        "vehicle_id": av["vehicle_id"],
        "matched_by_rule_id": av["matched_by_rule_id"],
        "notification_wave_id": av["notification_wave_id"],
        "dealer_id": av["dealer_id"],
        "remedy_status": av["remedy_status"],
        "notice_count": av["notice_count"],
        "last_notice_type": av["last_notice_type"],
        "last_notice_date": av["last_notice_date"],
        "scheduled_repair_date": av["scheduled_repair_date"],
        "approved_claim_count": calc.approved_claim_count(av["id"]),
        "requires_renotification": av["requires_renotification"],
        "outreach_attempt_count": len(calc.outreach_for(av["id"])),
        "created_at": av["created_at"],
        "updated_at": av["updated_at"],
        "version": av["version"],
    }


def wave_out(wave):
    return {
        "id": wave["id"],
        "campaign_id": wave["campaign_id"],
        "wave_type": wave["wave_type"],
        "target_region_code": wave["target_region_code"],
        "scheduled_mail_date": wave["scheduled_mail_date"],
        "sequence_number": wave["sequence_number"],
        "status": wave["status"],
        "eligible_vehicle_count": wave["eligible_vehicle_count"],
        "parts_capacity_qty": wave["parts_capacity_qty"],
        "provisional_coverage_ratio": calc.num(wave["provisional_coverage_ratio"]),
        "coverage_tier_factor": calc.num(wave["coverage_tier_factor"]),
        "planned_vehicle_count": wave["planned_vehicle_count"],
        "parts_coverage_ratio": calc.num(wave["parts_coverage_ratio"]),
        "mailed_vehicle_count": wave["mailed_vehicle_count"],
        "actual_mail_date": wave["actual_mail_date"],
        "auto_created": wave["auto_created"],
        "cancel_reason": wave["cancel_reason"],
        "created_at": wave["created_at"],
        "updated_at": wave["updated_at"],
        "version": wave["version"],
    }


def dealer_out(dealer):
    return {
        "id": dealer["id"],
        "dealer_code": dealer["dealer_code"],
        "name": dealer["name"],
        "region_code": dealer["region_code"],
        "labor_rate_per_hour": calc.num(dealer["labor_rate_per_hour"]),
        "monthly_repair_capacity": dealer["monthly_repair_capacity"],
        "status": dealer["status"],
        "suspension_reason": dealer["suspension_reason"],
        "created_at": dealer["created_at"],
        "updated_at": dealer["updated_at"],
        "version": dealer["version"],
    }


def part_out(part):
    return {
        "id": part["id"],
        "campaign_id": part["campaign_id"],
        "part_number": part["part_number"],
        "unit_cost": calc.num(part["unit_cost"]),
        "total_procured_qty": part["total_procured_qty"],
        "unallocated_qty": part["unallocated_qty"],
        "consumed_qty": part["consumed_qty"],
        "lead_time_days": part["lead_time_days"],
        "created_at": part["created_at"],
        "updated_at": part["updated_at"],
        "version": part["version"],
    }


def allocation_out(alloc):
    return {
        "id": alloc["id"],
        "remedy_part_id": alloc["remedy_part_id"],
        "dealer_id": alloc["dealer_id"],
        "campaign_id": alloc["campaign_id"],
        "requested_qty": alloc["requested_qty"],
        "allocated_qty": alloc["allocated_qty"],
        "consumed_qty": alloc["consumed_qty"],
        "status": alloc["status"],
        "partially_granted": alloc["partially_granted"],
        "revoked_reason": alloc["revoked_reason"],
        "created_at": alloc["created_at"],
        "updated_at": alloc["updated_at"],
        "version": alloc["version"],
    }


def labor_op_out(labor_op):
    return {
        "id": labor_op["id"],
        "campaign_id": labor_op["campaign_id"],
        "labor_op_code": labor_op["labor_op_code"],
        "description": labor_op["description"],
        "flat_hours": calc.num(labor_op["flat_hours"]),
        "rate_type": labor_op["rate_type"],
        "effective_from": labor_op["effective_from"],
        "effective_to": labor_op["effective_to"],
        "claim_count": calc.labor_op_claim_count(labor_op["id"]),
        "created_at": labor_op["created_at"],
        "updated_at": labor_op["updated_at"],
        "version": labor_op["version"],
    }


def claim_out(claim):
    return {
        "id": claim["id"],
        "campaign_id": claim["campaign_id"],
        "affected_vehicle_id": claim["affected_vehicle_id"],
        "dealer_id": claim["dealer_id"],
        "labor_operation_id": claim["labor_operation_id"],
        "parts_allocation_id": claim["parts_allocation_id"],
        "repair_date": claim["repair_date"],
        "claimed_labor_hours": calc.num(claim["claimed_labor_hours"]),
        "parts_used_qty": claim["parts_used_qty"],
        "provisional_amount_cents": claim["provisional_amount_cents"],
        "final_amount_cents": claim["final_amount_cents"],
        "is_repeat_repair": claim["is_repeat_repair"],
        "status": claim["status"],
        "audit_note": claim["audit_note"],
        "reversal_reason": claim["reversal_reason"],
        "created_at": claim["created_at"],
        "updated_at": claim["updated_at"],
        "version": claim["version"],
    }


def reimbursement_out(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "vehicle_id": row["vehicle_id"],
        "labor_operation_id": row["labor_operation_id"],
        "invoice_date": row["invoice_date"],
        "invoice_amount": calc.num(row["invoice_amount"]),
        "parts_amount": calc.num(row["parts_amount"]),
        "labor_hours_claimed": calc.num(row["labor_hours_claimed"]),
        "towing_amount": calc.num(row["towing_amount"]),
        "documentation_complete": row["documentation_complete"],
        "document_round": row["document_round"],
        "approved_amount_cents": row["approved_amount_cents"],
        "status": row["status"],
        "requested_items": row["requested_items"],
        "denial_reason": row["denial_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def outreach_out(row):
    return {
        "id": row["id"],
        "affected_vehicle_id": row["affected_vehicle_id"],
        "channel": row["channel"],
        "outcome": row["outcome"],
        "attempt_number": row["attempt_number"],
        "attempted_at": row["attempted_at"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def filing_out(filing):
    return {
        "id": filing["id"],
        "campaign_id": filing["campaign_id"],
        "filing_type": filing["filing_type"],
        "report_period": filing["report_period"],
        "narrative": filing["narrative"],
        "filed_at": filing["filed_at"],
        "filed_by_user_id": filing["filed_by_user_id"],
        "days_late": filing["days_late"],
        "completion_rate_snapshot_pct": calc.num(filing["completion_rate_snapshot_pct"]),
        "remedied_count_snapshot": filing["remedied_count_snapshot"],
        "recall_population_snapshot": filing["recall_population_snapshot"],
        "effectiveness_score_snapshot": calc.num(filing["effectiveness_score_snapshot"]),
        "amendment_required": filing["amendment_required"],
        "status": filing["status"],
        "created_at": filing["created_at"],
        "updated_at": filing["updated_at"],
        "version": filing["version"],
    }
