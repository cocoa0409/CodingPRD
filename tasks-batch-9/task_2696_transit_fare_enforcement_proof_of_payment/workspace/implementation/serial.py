"""Entity serializers.

Computed fields are recomputed at read time from the surviving record set, so a
zone's compliance figure, an inspector's live-citation count, a rider's prior
counters, a deployment's sample counters and a citation's money identity are
always current with the records behind them.
"""

import calc
from core import dec4_num, iso3, db


def _common(record, versioned=True):
    out = {"id": record["id"], "created_at": iso3(record["created_at"])}
    if versioned:
        out["updated_at"] = iso3(record["updated_at"])
        out["version"] = record["version"]
    return out


def zone_out(zone):
    verified, pct = calc.zone_signage(zone)
    out = _common(zone)
    out.update({
        "zone_code": zone["zone_code"],
        "name": zone["name"],
        "required_sign_count": zone["required_sign_count"],
        "verified_sign_count": verified,
        "signage_compliance_pct": dec4_num(pct),
        "penalty_multiplier_bps": zone["penalty_multiplier_bps"],
        "enforcement_policy": zone["enforcement_policy"],
        "max_concurrent_deployments": zone["max_concurrent_deployments"],
        "designation_status": zone["designation_status"],
        "designated_at": iso3(zone["designated_at"]),
        "suspension_reason": zone["suspension_reason"],
    })
    return out


def line_out(line):
    out = _common(line)
    out.update({
        "line_code": line["line_code"],
        "mode": line["mode"],
        "daily_boardings": line["daily_boardings"],
        "baseline_evasion_rate_bps": line["baseline_evasion_rate_bps"],
    })
    return out


def assignment_out(row):
    out = _common(row, versioned=False)
    out.update({
        "zone_id": row["zone_id"],
        "line_id": row["line_id"],
        "platform_segment_count": row["platform_segment_count"],
        "effective_from": iso3(row["effective_from"]),
    })
    return out


def audit_out(row):
    out = _common(row, versioned=False)
    out.update({
        "zone_id": row["zone_id"],
        "audited_at": iso3(row["audited_at"]),
        "signs_verified_count": row["signs_verified_count"],
        "deficiency_note": row["deficiency_note"],
        "auditor_user_id": row["auditor_user_id"],
    })
    return out


def inspector_out(inspector):
    live = sum(1 for c in db.citations.values()
               if c["issuing_inspector_id"] == inspector["id"]
               and c["adjudication_status"] in calc.LIVE_ADJUDICATION)
    out = _common(inspector)
    out.update({
        "badge_number": inspector["badge_number"],
        "display_name": inspector["display_name"],
        "certification_expiry": iso3(inspector["certification_expiry"]),
        "status": inspector["status"],
        "citations_issued_count": live,
    })
    return out


def rider_out(rider):
    warnings = sum(1 for e in db.encounters.values()
                   if e["rider_id"] == rider["id"] and e["outcome"] == "WARNING_ISSUED")
    citations = sum(1 for c in db.citations.values()
                    if c["rider_id"] == rider["id"]
                    and c["adjudication_status"] in calc.LIVE_ADJUDICATION)
    out = _common(rider)
    out.update({
        "rider_ref": rider["rider_ref"],
        "display_name": rider["display_name"],
        "demographic_band": rider["demographic_band"],
        "residence_geo_tract": rider["residence_geo_tract"],
        "fare_assistance_enrolled": rider["fare_assistance_enrolled"],
        "prior_warning_count": warnings,
        "prior_citation_count": citations,
    })
    return out


def deployment_out(deployment):
    calc.refresh_deployment_counters(deployment)
    out = _common(deployment)
    out.update({
        "line_id": deployment["line_id"],
        "zone_id": deployment["zone_id"],
        "window_start": iso3(deployment["window_start"]),
        "window_end": iso3(deployment["window_end"]),
        "planned_inspector_count": deployment["planned_inspector_count"],
        "sampling_method": deployment["sampling_method"],
        "target_sample_size": deployment["target_sample_size"],
        "achieved_sample_count": deployment["achieved_sample_count"],
        "voided_encounter_count": deployment["voided_encounter_count"],
        "sample_adequacy_ratio": dec4_num(deployment["sample_adequacy_ratio"]),
        "measured_evasion_rate_bps": deployment["measured_evasion_rate_bps"],
        "resolved_evasion_rate_bps": deployment["resolved_evasion_rate_bps"],
        "enforcement_cost_cents": deployment["enforcement_cost_cents"],
        "status": deployment["status"],
        "void_reason": deployment["void_reason"],
    })
    return out


def encounter_out(encounter):
    out = _common(encounter)
    out.update({
        "deployment_id": encounter["deployment_id"],
        "inspector_id": encounter["inspector_id"],
        "rider_id": encounter["rider_id"],
        "occurred_at": iso3(encounter["occurred_at"]),
        "fare_media_type": encounter["fare_media_type"],
        "media_reference": encounter["media_reference"],
        "media_validated_at": iso3(encounter["media_validated_at"]),
        "media_expires_at": iso3(encounter["media_expires_at"]),
        "media_zone_code": encounter["media_zone_code"],
        "identity_capture_method": encounter["identity_capture_method"],
        "validation_result": encounter["validation_result"],
        "outcome": encounter["outcome"],
    })
    return out


def citation_out(citation):
    calc.refresh_citation_money(citation)
    out = _common(citation)
    out.update({
        "encounter_id": citation["encounter_id"],
        "rider_id": citation["rider_id"],
        "zone_id": citation["zone_id"],
        "issuing_inspector_id": citation["issuing_inspector_id"],
        "reissued_from_citation_id": citation["reissued_from_citation_id"],
        "issued_at": iso3(citation["issued_at"]),
        "offense_sequence": citation["offense_sequence"],
        "citation_only_sequence": citation["citation_only_sequence"],
        "assessed_penalty_cents": citation["assessed_penalty_cents"],
        "reduction_floor_cents": citation["reduction_floor_cents"],
        "admin_fee_cents": citation["admin_fee_cents"],
        "total_due_cents": citation["total_due_cents"],
        "amount_paid_cents": citation["amount_paid_cents"],
        "service_credit_cents": citation["service_credit_cents"],
        "outstanding_balance_cents": citation["outstanding_balance_cents"],
        "contest_deadline_at": iso3(citation["contest_deadline_at"]),
        "adjudication_status": citation["adjudication_status"],
        "settlement_status": citation["settlement_status"],
        "dismissal_reason_code": citation["dismissal_reason_code"],
        "dismissed_at": iso3(citation["dismissed_at"]),
    })
    return out


def hearing_out(hearing):
    out = _common(hearing)
    out.update({
        "citation_id": hearing["citation_id"],
        "requested_by_rider_id": hearing["requested_by_rider_id"],
        "scheduled_for": iso3(hearing["scheduled_for"]),
        "hearing_officer_user_id": hearing["hearing_officer_user_id"],
        "decision": hearing["decision"],
        "dismissal_reason_code": hearing["dismissal_reason_code"],
        "reduced_penalty_cents": hearing["reduced_penalty_cents"],
        "decided_at": iso3(hearing["decided_at"]),
        "status": hearing["status"],
    })
    return out


def appeal_out(appeal):
    out = _common(appeal)
    out.update({
        "citation_id": appeal["citation_id"],
        "hearing_id": appeal["hearing_id"],
        "appellant_rider_id": appeal["appellant_rider_id"],
        "grounds_code": appeal["grounds_code"],
        "statement": appeal["statement"],
        "round_index": appeal["round_index"],
        "submitted_at": iso3(appeal["submitted_at"]),
        "supplement_deadline_at": iso3(appeal["supplement_deadline_at"]),
        "decided_by_user_id": appeal["decided_by_user_id"],
        "decided_at": iso3(appeal["decided_at"]),
        "dismissal_reason_code": appeal["dismissal_reason_code"],
        "status": appeal["status"],
    })
    return out


def plan_out(plan):
    calc.refresh_plan_counters(plan)
    out = _common(plan)
    out.update({
        "citation_id": plan["citation_id"],
        "installment_count": plan["installment_count"],
        "down_payment_cents": plan["down_payment_cents"],
        "financed_cents": plan["financed_cents"],
        "base_installment_cents": plan["base_installment_cents"],
        "final_installment_cents": plan["final_installment_cents"],
        "first_due_at": iso3(plan["first_due_at"]),
        "installments_paid_count": plan["installments_paid_count"],
        "missed_installment_count": plan["missed_installment_count"],
        "remaining_balance_cents": plan["remaining_balance_cents"],
        "status": plan["status"],
    })
    return out


def service_out(assignment):
    credited = calc.service_credit_cents_for_citation(assignment["citation_id"])
    assignment["credited_cents"] = credited
    out = _common(assignment)
    out.update({
        "citation_id": assignment["citation_id"],
        "partner_org_name": assignment["partner_org_name"],
        "required_hours": assignment["required_hours"],
        "hours_completed": assignment["hours_completed"],
        "credited_cents": credited,
        "status": assignment["status"],
    })
    return out


def payment_out(payment):
    out = _common(payment, versioned=False)
    out.update({
        "citation_id": payment["citation_id"],
        "plan_id": payment["plan_id"],
        "amount_cents": payment["amount_cents"],
        "source": payment["source"],
        "hours_credited": payment["hours_credited"],
        "applied_at": iso3(payment["applied_at"]),
    })
    return out
