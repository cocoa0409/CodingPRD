"""TypedDict shapes for the entities described in PRD Section 3.

Most records carry the common identity block of PRD Section 2.5 — `id`,
`created_at`, `updated_at` and an integer `version`. Three record types are
append-only and are never rewritten after creation, so they carry only `id` and
`created_at`: alarms, carrier test results and capacity readings.
"""

from typing import Optional, TypedDict


class Identified(TypedDict):
    """`id` plus creation instant: the block every record carries."""

    id: str
    created_at: str


class Versioned(Identified):
    """The mutable identity block: adds the update instant and OCC version."""

    updated_at: str
    version: int


class Carrier(Versioned, total=False):
    name: str
    carrier_code: str
    escalation_tier_count: int
    sla_restore_minutes_critical: int
    sla_restore_minutes_standard: int
    credit_pct_per_breach_hour: float
    credit_pct_cap: float
    min_claim_amount_cents: int
    tier_escalation_min_minutes: int
    watchlist_exposure_threshold_cents: int
    open_credit_exposure_cents: int
    committed_upgrade_mbps: int
    watchlist_state: str
    chronic_circuit_count: int


class Circuit(Versioned, total=False):
    carrier_id: str
    carrier_circuit_identifier: str
    site_a_code: str
    site_z_code: str
    bandwidth_mbps: int
    mrc_cents: int
    monitoring_state: str
    operational_state: str
    chronic_state: str
    capacity_state: str
    consecutive_high_readings: int
    spof_flag: bool
    fault_count_period: int
    last_incident_at: Optional[str]


class Device(Versioned, total=False):
    hostname: str
    site_code: str
    device_role: str
    primary_uplink_circuit_id: Optional[str]
    monitoring_state: str
    operational_state: str


class ApplicationPath(Versioned, total=False):
    name: str
    service_tier: str
    protection_scheme: str
    min_surviving_legs: int
    posture: str
    active_leg_count: int
    healthy_leg_count: int
    monitored_segment_count: int


class PathSegment(Versioned, total=False):
    application_path_id: str
    leg_group: str
    sequence_index: int
    circuit_id: Optional[str]
    device_id: Optional[str]
    segment_state: str


class Alarm(Identified, total=False):
    """Append-only: no `updated_at` and no `version`."""

    source_circuit_id: Optional[str]
    source_device_id: Optional[str]
    alarm_type: str
    raw_severity: str
    raised_at: str
    correlation_state: str
    correlation_parent_alarm_id: Optional[str]
    incident_id: Optional[str]
    cleared_at: Optional[str]


class Incident(Versioned, total=False):
    primary_circuit_id: str
    root_alarm_id: str
    severity: str
    impact_score: int
    response_state: str
    escalation_state: str
    detected_at: str
    triaged_at: Optional[str]
    mitigated_at: Optional[str]
    resolved_at: Optional[str]
    response_due_at: str
    escalation_due_at: str
    affected_path_count: int
    alarm_count: int
    reopen_count: int


class CarrierTicket(Versioned, total=False):
    incident_id: str
    circuit_id: str
    carrier_id: str
    carrier_reference: str
    reported_circuit_identifier: str
    state: str
    tier_level: int
    tier_entered_at: str
    opened_at: str
    restored_at: Optional[str]
    confirmed_at: Optional[str]
    opened_by_user_id: str
    restoration_confirmed_by_user_id: Optional[str]
    excluded_minutes: float
    restoration_minutes_carrier_clock: Optional[float]
    restoration_minutes_noc_clock: Optional[float]
    reopen_count: int
    fail_test_count: int


class TestResult(Identified, total=False):
    """Append-only diagnostic evidence: no `updated_at` and no `version`."""

    carrier_ticket_id: str
    test_type: str
    outcome: str
    notes: Optional[str]
    performed_at: str
    recorded_by_user_id: str


class SlaCreditClaim(Versioned, total=False):
    carrier_ticket_id: str
    carrier_id: str
    basis: str
    sla_target_minutes: int
    breach_minutes: float
    breach_hours: int
    credit_amount_cents: int
    state: str
    origin: str
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    paid_amount_cents: Optional[int]
    rejection_reason: Optional[str]
    revision_count: int


class MaintenanceWindow(Versioned, total=False):
    circuit_id: str
    carrier_id: str
    origin: str
    window_start: str
    window_end: str
    state: str
    suppresses_monitoring: bool
    risk_acknowledged: bool
    approved_by_user_id: Optional[str]
    monitoring_state_before_start: Optional[str]


class FailoverTest(Versioned, total=False):
    application_path_id: str
    tested_leg_group: str
    scheduled_start: str
    scheduled_end: str
    carrier_id_set: list
    state: str
    surviving_leg_count: Optional[int]
    scheduled_by_user_id: str
    attested_by_user_id: Optional[str]


class CapacityReading(Identified, total=False):
    """Append-only utilisation sample: no `updated_at` and no `version`."""

    circuit_id: str
    sample_at: str
    utilization_pct: float
    direction: str
    threshold_state: str


class UpgradeOrder(Versioned, total=False):
    circuit_id: str
    target_bandwidth_mbps: int
    delta_mbps: int
    expedite: bool
    subtotal_cents: int
    expedite_fee_cents: int
    total_cost_cents: int
    state: str
    origin: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    cancel_reason: Optional[str]


class VendorReview(Versioned, total=False):
    carrier_id: str
    period_start: str
    period_end: str
    chronic_circuit_count: int
    credit_ratio: float
    mttr_minutes: float
    net_performance_score: float
    decision: str
    decided_by_user_id: Optional[str]
    justification: Optional[str]


class AvailabilityReport(TypedDict, total=False):
    """The computed read returned for a path over a half-open period."""

    basis: str
    period_minutes: float
    path_down_minutes: float
    availability_pct: float
    leg_down_minutes: dict
