"""Output serialization.  Every `source: computed` field is recomputed here so
that each read reflects the present state of the graph (PRD sections 2.9, 3.2,
3.3, 3.4, 3.8 and 3.9).
"""
import clock
from db import store
from services import compute as K


def _num(value):
    return K.as_number(value)


def _ts(value):
    return clock.iso(value)


def _common(rec, out, revisioned=True):
    out["id"] = rec["id"]
    out["created_at"] = _ts(rec["created_at"])
    if revisioned:
        out["updated_at"] = _ts(rec["updated_at"])
        out["version"] = rec["version"]
    return out


# --------------------------------------------------------------------------
# Pollutant -- immutable, so no updated_at and no version (PRD 2.4)
# --------------------------------------------------------------------------
def pollutant(rec):
    out = {
        "code": rec["code"],
        "averaging_period_hours": rec["averaging_period_hours"],
        "standard_form": rec["standard_form"],
        "primary_standard_value": _num(rec["primary_standard_value"]),
        "design_value_years": rec["design_value_years"],
        "completeness_threshold_pct": _num(rec["completeness_threshold_pct"]),
        "rounding_decimals": rec["rounding_decimals"],
    }
    return _common(rec, out, revisioned=False)


def reference_method(rec):
    out = {
        "pollutant_id": rec["pollutant_id"],
        "method_code": rec["method_code"],
        "designation_type": rec["designation_type"],
        "designation_status": rec["designation_status"],
        "effective_from": _ts(rec["effective_from"]),
        "withdrawn_on": _ts(rec["withdrawn_on"]),
        "max_span_drift_pct": _num(rec["max_span_drift_pct"]),
        "zero_drift_limit": _num(rec["zero_drift_limit"]),
        "required_span_check_interval_days": rec["required_span_check_interval_days"],
        "required_calibration_interval_days": rec["required_calibration_interval_days"],
        "designation_change_count": rec["designation_change_count"],
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# MonitoringNetwork -- the census is a hard invariant recomputed on every read
# --------------------------------------------------------------------------
def network(rec):
    census = K.network_census(rec["id"])
    rec.update(census)
    out = {
        "name": rec["name"],
        "agency_code": rec["agency_code"],
        "metropolitan_population": rec["metropolitan_population"],
        "network_status": rec["network_status"],
        "current_assessment_year": rec["current_assessment_year"],
    }
    out.update(census)
    return _common(rec, out)


# --------------------------------------------------------------------------
# MonitoringSite -- siting evaluation, monitor count and attainment standing
# are all computed fresh on read
# --------------------------------------------------------------------------
def refresh_site_computed(rec):
    K.refresh_siting(rec)
    rec["operating_monitor_count"] = K.operating_monitor_count(rec["id"])
    rec["current_attainment_status"] = K.current_attainment_status(rec["id"])
    return rec


def site(rec):
    refresh_site_computed(rec)
    out = {
        "network_id": rec["network_id"],
        "replaces_site_id": rec["replaces_site_id"],
        "site_code": rec["site_code"],
        "site_type": rec["site_type"],
        "latitude": _num(rec["latitude"]),
        "longitude": _num(rec["longitude"]),
        "population_served": rec["population_served"],
        "probe_height_m": _num(rec["probe_height_m"]),
        "distance_to_roadway_m": _num(rec["distance_to_roadway_m"]),
        "distance_to_obstruction_m": _num(rec["distance_to_obstruction_m"]),
        "obstruction_height_m": _num(rec["obstruction_height_m"]),
        "distance_to_source_m": _num(rec["distance_to_source_m"]),
        "status": rec["status"],
        "siting_violation_codes": list(rec["siting_violation_codes"]),
        "siting_waiver_required": rec["siting_waiver_required"],
        "siting_waiver_granted": rec["siting_waiver_granted"],
        "operations_start_at": _ts(rec["operations_start_at"]),
        "suspended_at": _ts(rec["suspended_at"]),
        "operating_monitor_count": rec["operating_monitor_count"],
        "current_attainment_status": rec["current_attainment_status"],
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# Monitor -- both postures recomputed on read; a decommissioned instrument
# keeps its last computed posture (PRD 3.3)
# --------------------------------------------------------------------------
def monitor(rec):
    K.refresh_qc_posture(rec)
    out = {
        "site_id": rec["site_id"],
        "reference_method_id": rec["reference_method_id"],
        "poc": rec["poc"],
        "is_primary_for_design_value": rec["is_primary_for_design_value"],
        "installed_at": _ts(rec["installed_at"]),
        "monitor_status": rec["monitor_status"],
        "last_calibration_at": _ts(rec["last_calibration_at"]),
        "last_span_check_at": _ts(rec["last_span_check_at"]),
        "last_zero_check_at": _ts(rec["last_zero_check_at"]),
        "last_maintenance_at": _ts(rec["last_maintenance_at"]),
        "consecutive_qc_failure_count": rec["consecutive_qc_failure_count"],
        "out_of_service_since": _ts(rec["out_of_service_since"]),
        "out_of_service_day_count": rec["out_of_service_day_count"],
        "qc_posture": rec["qc_posture"],
        "qc_posture_in_service": rec["qc_posture_in_service"],
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# QcEvent -- immutable, so no updated_at and no version (PRD 2.4)
# --------------------------------------------------------------------------
def qc_event(rec):
    out = {
        "monitor_id": rec["monitor_id"],
        "event_type": rec["event_type"],
        "performed_at": _ts(rec["performed_at"]),
        "span_drift_pct": _num(rec["span_drift_pct"]),
        "zero_drift_value": _num(rec["zero_drift_value"]),
        "declared_failure": rec["declared_failure"],
        "outcome": rec["outcome"],
        "performed_by_user_id": rec["performed_by_user_id"],
    }
    return _common(rec, out, revisioned=False)


# --------------------------------------------------------------------------
# DataBatch -- hour accounting recomputed on read; the two status dimensions
# are independent (PRD 3.4)
# --------------------------------------------------------------------------
def data_batch(rec):
    K.refresh_hour_accounting(rec)
    out = {
        "monitor_id": rec["monitor_id"],
        "year": rec["year"],
        "quarter": rec["quarter"],
        "scheduled_hour_count": rec["scheduled_hour_count"],
        "quarterly_mean_concentration": _num(rec["quarterly_mean_concentration"]),
        "quarterly_mean_concentration_event_adjusted":
            _num(rec["quarterly_mean_concentration_event_adjusted"]),
        "fourth_high_daily_max": _num(rec["fourth_high_daily_max"]),
        "excused_hour_count": rec["excused_hour_count"],
        "invalidated_hour_count": rec["invalidated_hour_count"],
        "event_excluded_hour_count": rec["event_excluded_hour_count"],
        "adjusted_scheduled_hour_count": rec["adjusted_scheduled_hour_count"],
        "valid_hour_count": rec["valid_hour_count"],
        "completeness_pct": _num(rec["completeness_pct"]),
        "regulatory_use_eligible": rec["regulatory_use_eligible"],
        "validation_status": rec["validation_status"],
        "submission_status": rec["submission_status"],
        "validated_by_user_id": rec["validated_by_user_id"],
        "invalidation_applied_by_user_ids": list(rec["invalidation_applied_by_user_ids"]),
        "batch_invalidation_reason": rec["batch_invalidation_reason"],
        "reopen_count": rec["reopen_count"],
    }
    return _common(rec, out)


def invalidation(rec):
    out = {
        "data_batch_id": rec["data_batch_id"],
        "start_hour_index": rec["start_hour_index"],
        "end_hour_index": rec["end_hour_index"],
        "hours_affected": rec["hours_affected"],
        "invalidation_code": rec["invalidation_code"],
        "status": rec["status"],
        "applied_by_user_id": rec["applied_by_user_id"],
        "withdrawn_reason": rec["withdrawn_reason"],
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# ExceptionalEventDemonstration -- excluded_hour_total counts only EFFECTIVE
# exclusions (PRD 3.6)
# --------------------------------------------------------------------------
def refresh_demonstration_computed(rec):
    rec["excluded_hour_total"] = sum(
        e["hours_affected"] for e in K.exclusions_of_demonstration(rec["id"])
        if e["status"] == "EFFECTIVE"
    )
    return rec


def demonstration(rec):
    refresh_demonstration_computed(rec)
    out = {
        "site_id": rec["site_id"],
        "pollutant_id": rec["pollutant_id"],
        "event_type": rec["event_type"],
        "event_start_date": _ts(rec["event_start_date"]),
        "event_end_date": _ts(rec["event_end_date"]),
        "narrative": rec["narrative"],
        "clear_causal_relationship": rec["clear_causal_relationship"],
        "status": rec["status"],
        "info_request_count": rec["info_request_count"],
        "determined_by_user_id": rec["determined_by_user_id"],
        "determined_at": _ts(rec["determined_at"]),
        "excluded_hour_total": rec["excluded_hour_total"],
    }
    return _common(rec, out)


def exclusion(rec):
    out = {
        "demonstration_id": rec["demonstration_id"],
        "data_batch_id": rec["data_batch_id"],
        "start_hour_index": rec["start_hour_index"],
        "end_hour_index": rec["end_hour_index"],
        "hours_affected": rec["hours_affected"],
        "status": rec["status"],
        "effective_at": _ts(rec["effective_at"]),
    }
    return _common(rec, out)


def design_value(rec):
    out = {
        "site_id": rec["site_id"],
        "pollutant_id": rec["pollutant_id"],
        "primary_monitor_id": rec["primary_monitor_id"],
        "period_end_year": rec["period_end_year"],
        "variant": rec["variant"],
        "annual_statistics": [_num(v) for v in rec["annual_statistics"]],
        "complete_year_count": rec["complete_year_count"],
        "design_value": _num(rec["design_value"]),
        "attainment_status": rec["attainment_status"],
        "status": rec["status"],
        "stale_reason": rec["stale_reason"],
        "finalized_by_user_id": rec["finalized_by_user_id"],
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# NetworkAssessment -- adequacy scoring recomputed on read (PRD 3.9)
# --------------------------------------------------------------------------
def refresh_assessment_computed(rec):
    net = store.networks.get(rec["network_id"])
    if net is not None:
        rec.update(K.network_adequacy_score(net))
    return rec


def assessment(rec):
    refresh_assessment_computed(rec)
    out = {
        "network_id": rec["network_id"],
        "cycle_year": rec["cycle_year"],
        "required_population_site_count": rec["required_population_site_count"],
        "coverage_ratio": _num(rec["coverage_ratio"]),
        "adequacy_score": _num(rec["adequacy_score"]),
        "adequacy_tier": rec["adequacy_tier"],
        "status": rec["status"],
        "return_count": rec["return_count"],
        "submitted_at": _ts(rec["submitted_at"]),
        "approved_at": _ts(rec["approved_at"]),
        "approved_by_user_id": rec["approved_by_user_id"],
    }
    return _common(rec, out)


def change_request(rec):
    out = {
        "site_id": rec["site_id"],
        "replacement_site_id": rec["replacement_site_id"],
        "assessment_id": rec["assessment_id"],
        "request_type": rec["request_type"],
        "justification": rec["justification"],
        "status": rec["status"],
        "revision_request_count": rec["revision_request_count"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "decided_at": _ts(rec["decided_at"]),
        "effective_at": _ts(rec["effective_at"]),
    }
    return _common(rec, out)


# --------------------------------------------------------------------------
# CertificationPackage -- rollup recomputed on read (PRD 3.8)
# --------------------------------------------------------------------------
def refresh_package_computed(rec):
    rec.update(K.certification_package_rollup(rec))
    return rec


def package(rec):
    refresh_package_computed(rec)
    out = {
        "network_id": rec["network_id"],
        "pollutant_id": rec["pollutant_id"],
        "year": rec["year"],
        "certification_deadline": _ts(rec["certification_deadline"]),
        "included_batch_count": rec["included_batch_count"],
        "eligible_batch_count": rec["eligible_batch_count"],
        "rollup_completeness_pct": _num(rec["rollup_completeness_pct"]),
        "certification_ready": rec["certification_ready"],
        "status": rec["status"],
        "rejection_count": rec["rejection_count"],
        "certified_by_user_id": rec["certified_by_user_id"],
        "certified_at": _ts(rec["certified_at"]),
    }
    return _common(rec, out)
