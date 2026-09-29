"""Per-entity JSON projections.

Common fields (PRD 2.4): every record carries id and created_at; every record but
the immutable ProjectAssetLink also carries updated_at and version.
"""

from core import as_number, clock, iso


def _common(row):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if "updated_at" in row:
        out["updated_at"] = iso(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def _stamp(row, field):
    value = row.get(field)
    return iso(value) if value is not None else None


def jurisdiction(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "jurisdiction_code": row["jurisdiction_code"],
        "population": row["population"],
        "svi_score": as_number(row["svi_score"]),
        "svi_tier": row["svi_tier"],
        "disadvantaged_flag": row["disadvantaged_flag"],
        "endorsement_weight": row["endorsement_weight"],
        "status": row["status"],
    })
    return out


def plan_cycle(row):
    out = _common(row)
    out.update({
        "cycle_label": row["cycle_label"],
        "status": row["status"],
        "round_number": row["round_number"],
        "revision_count": row["revision_count"],
        "max_revision_rounds": row["max_revision_rounds"],
        "quorum_weight_bps": row["quorum_weight_bps"],
        "required_session_count": row["required_session_count"],
        "achieved_weight_bps": row["achieved_weight_bps"],
        "endorsement_deadline": _stamp(row, "endorsement_deadline"),
        "adopted_at": _stamp(row, "adopted_at"),
    })
    return out


def hazard_profile(row):
    out = _common(row)
    out.update({
        "jurisdiction_id": row["jurisdiction_id"],
        "hazard_type": row["hazard_type"],
        "scenario": row["scenario"],
        "horizon_year": row["horizon_year"],
        "exposure_index": as_number(row["exposure_index"]),
        "annual_event_probability": as_number(row["annual_event_probability"]),
        "projected_annual_loss_cents": row["projected_annual_loss_cents"],
        "status": row["status"],
        "published_version": row["published_version"],
        "published_at": _stamp(row, "published_at"),
    })
    return out


def asset(row):
    out = _common(row)
    out.update({
        "jurisdiction_id": row["jurisdiction_id"],
        "upstream_asset_id": row["upstream_asset_id"],
        "asset_class": row["asset_class"],
        "name": row["name"],
        "replacement_value_cents": row["replacement_value_cents"],
        "service_population": row["service_population"],
        "redundancy_factor": as_number(row["redundancy_factor"]),
        "is_shared": row["is_shared"],
        "criticality_status": row["criticality_status"],
        "consequence_score": as_number(row["consequence_score"]),
        "criticality_tier": row["criticality_tier"],
        "dependency_depth": row["dependency_depth"],
    })
    return out


def assessment(row):
    out = _common(row)
    out.update({
        "hazard_profile_id": row["hazard_profile_id"],
        "asset_id": row["asset_id"],
        "subject_type": row["subject_type"],
        "sensitivity_score": as_number(row["sensitivity_score"]),
        "adaptive_capacity_score": as_number(row["adaptive_capacity_score"]),
        "method": row["method"],
        "svi_overlay_applied": row["svi_overlay_applied"],
        "vulnerability_score": as_number(row["vulnerability_score"]),
        "vulnerability_band": row["vulnerability_band"],
        "status": row["status"],
        "assessed_at": _stamp(row, "assessed_at"),
        "assessed_profile_version": row["assessed_profile_version"],
    })
    return out


def project(row):
    out = _common(row)
    out.update({
        "plan_cycle_id": row["plan_cycle_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "prerequisite_project_id": row["prerequisite_project_id"],
        "capital_program_id": row["capital_program_id"],
        "name": row["name"],
        "hazard_type": row["hazard_type"],
        "strategy_type": row["strategy_type"],
        "base_cost_cents": row["base_cost_cents"],
        "service_life_years": row["service_life_years"],
        "cobenefit_points": row["cobenefit_points"],
        "feasibility_score": as_number(row["feasibility_score"]),
        "screening_status": row["screening_status"],
        "screen_score": as_number(row["screen_score"]),
        "analysis_status": row["analysis_status"],
        "program_status": row["program_status"],
        "escalated_cost_cents": row["escalated_cost_cents"],
        "admin_rate_bps": row["admin_rate_bps"],
        "admin_fee_cents": row["admin_fee_cents"],
        "total_program_cost_cents": row["total_program_cost_cents"],
        "grant_match_share_bps": row["grant_match_share_bps"],
        "allocated_cents": row["allocated_cents"],
        "equity_benefit_share_bps": row["equity_benefit_share_bps"],
        "priority_score": as_number(row["priority_score"]),
        "equity_waiver_granted": row["equity_waiver_granted"],
        "waiver_rationale": row.get("waiver_rationale"),
        "grant_hold_flag": row["grant_hold_flag"],
        "grant_funder": row["grant_funder"],
        "grant_submitted_at": _stamp(row, "grant_submitted_at"),
        "awarded_at": _stamp(row, "awarded_at"),
        "indicator_code": row["indicator_code"],
        "indicator_target_value": as_number(row["indicator_target_value"]),
        "indicator_latest_value": as_number(row["indicator_latest_value"]),
        "indicator_attainment_pct": as_number(row["indicator_attainment_pct"]),
        "latest_period_label": row["latest_period_label"],
        "reported_period_count": row["reported_period_count"],
        "implementation_status": row["implementation_status"],
    })
    return out


def link(row):
    # immutable junction row: only id and created_at from the common set
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "project_id": row["project_id"],
        "asset_id": row["asset_id"],
        "avoided_loss_annual_cents": row["avoided_loss_annual_cents"],
        "benefit_reaches_disadvantaged": row["benefit_reaches_disadvantaged"],
        "link_sequence": row["link_sequence"],
    }


def analysis(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "method": row["method"],
        "discount_rate_bps": row["discount_rate_bps"],
        "analysis_horizon_years": row["analysis_horizon_years"],
        "benefit_measure_cents": row["benefit_measure_cents"],
        "cost_measure_cents": row["cost_measure_cents"],
        "bcr": as_number(row["bcr"]),
        "grant_eligible": row["grant_eligible"],
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_at": _stamp(row, "certified_at"),
        "stale_reason": row["stale_reason"],
    })
    return out


def capital_program(row):
    out = _common(row)
    out.update({
        "fiscal_year": row["fiscal_year"],
        "authorized_cents": row["authorized_cents"],
        "committed_cents": row["committed_cents"],
        "available_cents": row["available_cents"],
        "equity_target_bps": row["equity_target_bps"],
        "equity_committed_cents": row["equity_committed_cents"],
        "equity_achieved_bps": row["equity_achieved_bps"],
        "funding_posture": row["funding_posture"],
    })
    return out


def session(row):
    out = _common(row)
    out.update({
        "plan_cycle_id": row["plan_cycle_id"],
        "host_jurisdiction_id": row["host_jurisdiction_id"],
        "modality": row["modality"],
        "window_start": _stamp(row, "window_start"),
        "window_end": _stamp(row, "window_end"),
        "status": row["status"],
        "attendee_count": row["attendee_count"],
        "disadvantaged_attendee_count": row["disadvantaged_attendee_count"],
        "equity_reach_bps": row["equity_reach_bps"],
        "preferred_strategy_type": row["preferred_strategy_type"],
    })
    return out


def endorsement(row):
    out = _common(row)
    out.update({
        "plan_cycle_id": row["plan_cycle_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "round_number": row["round_number"],
        "decision": row["decision"],
        "condition_note": row["condition_note"],
        "weight_at_cast": row["weight_at_cast"],
        "cast_at": _stamp(row, "cast_at"),
    })
    return out


def pact_status(row):
    """Derived in this exact order: EXPIRED, then EXHAUSTED, then OPEN (PRD 3.9)."""
    if clock.now() >= row["window_end"]:
        return "EXPIRED"
    if int(row["free_units"]) == 0:
        return "EXHAUSTED"
    return "OPEN"


def pact(row):
    out = _common(row)
    out.update({
        "host_jurisdiction_id": row["host_jurisdiction_id"],
        "resource_class": row["resource_class"],
        "pledged_units": row["pledged_units"],
        "reserved_units": row["reserved_units"],
        "free_units": row["free_units"],
        "window_start": _stamp(row, "window_start"),
        "window_end": _stamp(row, "window_end"),
        "max_concurrent_commitments": row["max_concurrent_commitments"],
        "status": pact_status(row),
    })
    return out


def commitment(row):
    out = _common(row)
    out.update({
        "pact_id": row["pact_id"],
        "requesting_jurisdiction_id": row["requesting_jurisdiction_id"],
        "asset_id": row["asset_id"],
        "committed_units": row["committed_units"],
        "window_start": _stamp(row, "window_start"),
        "window_end": _stamp(row, "window_end"),
        "status": row["status"],
        "released_at": _stamp(row, "released_at"),
        "fulfilled_at": _stamp(row, "fulfilled_at"),
    })
    return out
