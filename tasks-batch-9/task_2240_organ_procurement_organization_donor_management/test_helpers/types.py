"""TypedDict shapes for every resource the API exposes.

Three resources are append-only records and carry **only** ``id`` and
``created_at``: a serology result, a next-of-kin contact and a physiologic
observation.  Their TypedDicts therefore deliberately omit ``updated_at`` and
``version``, because for these three both fields are absent from the response
body entirely -- not null, absent.  The remaining eleven resource kinds carry
the full quartet and inherit from ``ManagedResource``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AppendOnlyRecord(TypedDict):
    """Only ``id`` and ``created_at`` -- no ``updated_at``, no ``version``."""

    id: str
    created_at: str


class ManagedResource(TypedDict):
    """The full identity quartet carried by the eleven managed aggregates."""

    id: str
    created_at: str
    updated_at: str
    version: int


class HospitalPartner(ManagedResource, total=False):
    name: str
    hospital_code: str
    referral_trigger_policy: str
    timely_referral_window_minutes: int
    referral_count: int
    timely_referral_count: int
    untimely_referral_count: int
    converted_donor_count: int
    timely_referral_rate: Optional[float]
    partner_posture: str


class DeathReferral(ManagedResource, total=False):
    hospital_partner_id: str
    patient_mrn: str
    age_years: int
    ventilated: bool
    gcs_score: int
    cause_of_death_category: str
    trigger_event_at: str
    death_pronounced_at: Optional[str]
    referred_at: str
    referral_lag_minutes: int
    audit_lag_minutes: Optional[int]
    timeliness_flag: str
    status: str


class EligibilityScreening(ManagedResource, total=False):
    referral_id: str
    status: str
    info_request_count: int
    info_request_note: Optional[str]
    risk_factors: List[str]
    unresolved_factors: List[str]
    informant_reliability: Optional[str]
    risk_score: Optional[float]
    risk_tier: Optional[str]
    risk_variant_applied: Optional[str]
    risk_assessed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    absolute_contraindication: bool
    ruled_out_reason: Optional[str]


class SerologyResult(AppendOnlyRecord, total=False):
    screening_id: str
    marker: str
    result: str
    resulted_at: str
    nat_confirmed: bool
    absolute_contraindication_marker: bool


class Authorization(ManagedResource, total=False):
    referral_id: str
    status: str
    registry_hit: bool
    registry_document_ref: Optional[str]
    authorization_basis: Optional[str]
    required_document_types: List[str]
    document_types_present: List[str]
    witness_name: Optional[str]
    documentation_complete: bool
    highest_rank_attempted: Optional[int]
    consenting_rank: Optional[int]
    consent_recorded_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    rescinded_reason: Optional[str]


class NextOfKinContact(AppendOnlyRecord, total=False):
    authorization_id: str
    relationship: str
    rank: int
    response: str
    contact_note: Optional[str]
    contacted_at: str
    recorded_by_user_id: str


class DonorCase(ManagedResource, total=False):
    referral_id: str
    authorization_id: str
    donor_code: str
    physiologic_status: str
    allocation_status: str
    case_posture: str
    closed_reason: Optional[str]
    risk_tier_snapshot: str
    viability_index: int
    dmg_bundle_met_count: int
    observation_count: int
    organ_count: int
    organs_accepted_count: int
    organs_recovered_count: int
    organs_nontransplantable_count: int


class PhysiologicObservation(AppendOnlyRecord, total=False):
    donor_case_id: str
    recorded_at: str
    map_mmhg: int
    pao2_fio2_ratio: int
    sodium: int
    urine_output_ml_per_kg_hr: float
    pressor_count: int
    cardiac_arrest: bool
    viability_index_snapshot: int
    dmg_bundle_met: bool
    recorded_by_user_id: str


class Organ(ManagedResource, total=False):
    donor_case_id: str
    organ_type: str
    status: str
    cit_limit_minutes: int
    viability_hold: bool
    accepted_offer_id: Optional[str]
    cross_clamp_at: Optional[str]
    transport_asset_id: Optional[str]
    transport_mode: Optional[str]
    transport_depart_at: Optional[str]
    transport_arrive_at: Optional[str]
    transit_minutes: Optional[int]
    implant_prep_minutes: Optional[int]
    projected_cold_ischemic_minutes: Optional[int]
    projected_cit_margin_minutes: Optional[int]
    nontransplantable_reason: Optional[str]
    research_protocol_code: Optional[str]
    tissue_processor_code: Optional[str]


class MatchRun(ManagedResource, total=False):
    organ_id: str
    run_number: int
    status: str
    closed_reason: Optional[str]
    generated_at: str
    primary_offer_slots: int
    candidate_count: int
    pending_offer_count: int
    slots_free: int
    promoted_count: int


class OrganOffer(ManagedResource, total=False):
    match_run_id: str
    sequence_position: int
    center_code: str
    candidate_code: str
    acceptance_clock_minutes: int
    status: str
    offered_at: Optional[str]
    expires_at: Optional[str]
    responded_at: Optional[str]
    responded_by_user_id: Optional[str]
    decline_reason: Optional[str]
    bypass_reason: Optional[str]
    increased_risk_ack: bool


class RecoveryTeam(ManagedResource, total=False):
    team_code: str
    specialty: str
    turnaround_buffer_minutes: int
    booked_or_minutes: int
    scheduled_operation_count: int


class RecoveryOperation(ManagedResource, total=False):
    donor_case_id: str
    recovery_team_id: str
    or_start_at: str
    or_end_at: str
    or_minutes: int
    status: str
    cross_clamp_at: Optional[str]
    cancelled_reason: Optional[str]
    organ_types_covered: List[str]


class TransportAsset(ManagedResource, total=False):
    asset_code: str
    mode: str
    concurrent_leg_capacity: int
    active_leg_count: int


class PerformanceReport(TypedDict, total=False):
    """The recertification report is a computed read and persists nothing."""

    hospital_partner_id: str
    window_days: int
    basis: str
    window_start: str
    window_end: str
    eligible_referral_count: int
    timely_referral_count: int
    timely_referral_rate: Optional[float]
    cleared_referral_count: int
    converted_referral_count: int
    conversion_rate: Optional[float]
    transplanted_organ_count: int
    organs_per_donor: Optional[float]
    recertification_tier: str


Candidate = Dict[str, Any]
Payload = Dict[str, Any]
Headers = Dict[str, str]
