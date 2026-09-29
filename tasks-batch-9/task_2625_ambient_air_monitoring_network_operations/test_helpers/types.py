"""TypedDict shapes for every resource the PRD declares.

A pollutant and a quality-control event are immutable (PRD 2.4), so their
shapes carry only `id` and `created_at`; every other resource also carries
`updated_at` and `version`.
"""

from typing import List, Optional, TypedDict


class ImmutableRecord(TypedDict):
    id: str
    created_at: str


class VersionedRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Pollutant(ImmutableRecord, total=False):
    code: str
    averaging_period_hours: int
    standard_form: str
    primary_standard_value: float
    design_value_years: int
    completeness_threshold_pct: float
    rounding_decimals: int


class ReferenceMethod(VersionedRecord, total=False):
    pollutant_id: str
    method_code: str
    designation_type: str
    designation_status: str
    effective_from: str
    withdrawn_on: Optional[str]
    max_span_drift_pct: float
    zero_drift_limit: float
    required_span_check_interval_days: int
    required_calibration_interval_days: int
    designation_change_count: int


class MonitoringNetwork(VersionedRecord, total=False):
    name: str
    agency_code: str
    metropolitan_population: int
    network_status: str
    current_assessment_year: Optional[int]
    total_site_count: int
    proposed_site_count: int
    approved_site_count: int
    operating_site_count: int
    suspended_site_count: int
    shutdown_site_count: int
    relocated_site_count: int
    delinquent_monitor_count: int
    waiver_required_site_count: int


class MonitoringSite(VersionedRecord, total=False):
    network_id: str
    replaces_site_id: Optional[str]
    site_code: str
    site_type: str
    latitude: float
    longitude: float
    population_served: int
    probe_height_m: float
    distance_to_roadway_m: float
    distance_to_obstruction_m: float
    obstruction_height_m: float
    distance_to_source_m: float
    status: str
    siting_violation_codes: List[str]
    siting_waiver_required: bool
    siting_waiver_granted: bool
    operations_start_at: Optional[str]
    suspended_at: Optional[str]
    operating_monitor_count: int
    current_attainment_status: str


class Monitor(VersionedRecord, total=False):
    site_id: str
    reference_method_id: str
    poc: int
    is_primary_for_design_value: bool
    installed_at: str
    monitor_status: str
    last_calibration_at: Optional[str]
    last_span_check_at: Optional[str]
    last_zero_check_at: Optional[str]
    last_maintenance_at: Optional[str]
    consecutive_qc_failure_count: int
    out_of_service_since: Optional[str]
    out_of_service_day_count: int
    qc_posture: str
    qc_posture_in_service: str


class QcEvent(ImmutableRecord, total=False):
    monitor_id: str
    event_type: str
    performed_at: str
    span_drift_pct: Optional[float]
    zero_drift_value: Optional[float]
    declared_failure: bool
    outcome: str
    performed_by_user_id: str


class DataBatch(VersionedRecord, total=False):
    monitor_id: str
    year: int
    quarter: int
    scheduled_hour_count: int
    quarterly_mean_concentration: float
    quarterly_mean_concentration_event_adjusted: Optional[float]
    fourth_high_daily_max: Optional[float]
    excused_hour_count: int
    invalidated_hour_count: int
    event_excluded_hour_count: int
    adjusted_scheduled_hour_count: int
    valid_hour_count: int
    completeness_pct: float
    regulatory_use_eligible: bool
    validation_status: str
    submission_status: str
    validated_by_user_id: Optional[str]
    invalidation_applied_by_user_ids: List[str]
    batch_invalidation_reason: Optional[str]
    reopen_count: int


class DataInvalidation(VersionedRecord, total=False):
    data_batch_id: str
    start_hour_index: int
    end_hour_index: int
    hours_affected: int
    invalidation_code: str
    status: str
    applied_by_user_id: str
    withdrawn_reason: Optional[str]


class ExceptionalEventDemonstration(VersionedRecord, total=False):
    site_id: str
    pollutant_id: str
    event_type: str
    event_start_date: str
    event_end_date: str
    narrative: str
    clear_causal_relationship: bool
    status: str
    info_request_count: int
    determined_by_user_id: Optional[str]
    determined_at: Optional[str]
    excluded_hour_total: int


class EventExclusion(VersionedRecord, total=False):
    demonstration_id: str
    data_batch_id: str
    start_hour_index: int
    end_hour_index: int
    hours_affected: int
    status: str
    effective_at: Optional[str]


class DesignValue(VersionedRecord, total=False):
    site_id: str
    pollutant_id: str
    primary_monitor_id: str
    period_end_year: int
    variant: str
    annual_statistics: List[float]
    complete_year_count: int
    design_value: Optional[float]
    attainment_status: str
    status: str
    stale_reason: Optional[str]
    finalized_by_user_id: Optional[str]


class NetworkAssessment(VersionedRecord, total=False):
    network_id: str
    cycle_year: int
    required_population_site_count: int
    coverage_ratio: float
    adequacy_score: float
    adequacy_tier: str
    status: str
    return_count: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]


class SiteChangeRequest(VersionedRecord, total=False):
    site_id: str
    replacement_site_id: Optional[str]
    assessment_id: str
    request_type: str
    justification: str
    status: str
    revision_request_count: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    effective_at: Optional[str]


class CertificationPackage(VersionedRecord, total=False):
    network_id: str
    pollutant_id: str
    year: int
    certification_deadline: str
    included_batch_count: int
    eligible_batch_count: int
    rollup_completeness_pct: float
    certification_ready: bool
    status: str
    rejection_count: int
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
