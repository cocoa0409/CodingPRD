"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_OPERATOR = "IntakeOperator"
    DATA_STEWARD = "DataSteward"
    DISTRIBUTION_OPERATOR = "DistributionOperator"
    PROVIDER_CONTACT = "ProviderContact"


class RosterSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class RosterSourceFormat(str, Enum):
    CSV = "CSV"
    XLSX = "XLSX"
    JSON = "JSON"
    FHIR = "FHIR"
    FIXED_WIDTH = "FIXED_WIDTH"


class RosterFileStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RosterRowStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    NEW_PROVIDER = "NEW_PROVIDER"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    MALFORMED_NPI = "MALFORMED_NPI"
    MALFORMED_TIN = "MALFORMED_TIN"
    MISSING_LOCATION = "MISSING_LOCATION"
    DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"
    SOURCE_RETIRED = "SOURCE_RETIRED"


class ProviderLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MERGED = "MERGED"
    TERMINATED = "TERMINATED"


class AttributeGroup(str, Enum):
    DEMOGRAPHIC = "DEMOGRAPHIC"
    SPECIALTY = "SPECIALTY"
    PRACTICE_ADDRESS = "PRACTICE_ADDRESS"
    CONTACT = "CONTACT"
    LICENSE = "LICENSE"


class ProviderAttributeStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RETRO_PENDING = "RETRO_PENDING"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class AliasLinkKind(str, Enum):
    AUTO_EXACT = "AUTO_EXACT"
    AUTO_FUZZY = "AUTO_FUZZY"
    MANUAL = "MANUAL"


class ProviderAliasStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNLINKED = "UNLINKED"


class ConflictResolution(str, Enum):
    PENDING = "PENDING"
    KEEP_INCUMBENT = "KEEP_INCUMBENT"
    ACCEPT_CHALLENGER = "ACCEPT_CHALLENGER"
    MERGE_VALUES = "MERGE_VALUES"


class AttributeConflictStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class DistributionTargetCode(str, Enum):
    CLAIMS = "CLAIMS"
    DIRECTORY = "DIRECTORY"
    NETWORK = "NETWORK"


class DistributionTargetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class DistributionBatchStatus(str, Enum):
    BUILDING = "BUILDING"
    PUBLISHED = "PUBLISHED"
    ACKED = "ACKED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ChangeKind(str, Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    TERM = "TERM"
    QUALITY_DROP_EXCLUDED = "QUALITY_DROP_EXCLUDED"


class AttestationCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AttestationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class AttestationOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# Append-only ledger records (distribution items, quality score rows, merge
# records) carry ONLY id + created_at (PRD §2.5): no updated_at, no version.


class RosterSource(TypedDict, total=False):
    id: str
    source_code: str
    display_name: str
    format: str
    precedence_rank: int
    freshness_sla_days: int
    status: str
    default_attestation_campaign_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RosterFile(TypedDict, total=False):
    id: str
    roster_source_id: str
    external_file_ref: str
    declared_row_count: int
    received_at: str
    status: str
    parsed_row_count: int
    rejected_row_count: int
    committed_row_count: int
    checksum: str
    created_at: str
    updated_at: str
    version: int


class RosterRow(TypedDict, total=False):
    id: str
    roster_file_id: str
    row_index: int
    raw_payload: str
    normalized_payload: dict
    npi: str
    tin: str
    location_key: str
    status: str
    reject_reason: Optional[str]
    resolved_provider_id: Optional[str]
    effective_date: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    tin: str
    location_key: str
    lifecycle_status: str
    merged_into_provider_id: Optional[str]
    current_quality_score: int
    staleness_flag: bool
    last_roster_file_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProviderAttribute(TypedDict, total=False):
    id: str
    provider_id: str
    attribute_group: str
    attribute_key: str
    attribute_value: str
    effective_date: str
    term_date: Optional[str]
    roster_source_id: Optional[str]
    roster_row_id: Optional[str]
    supersedes_attribute_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderAlias(TypedDict, total=False):
    id: str
    provider_id: str
    alias_npi: str
    alias_tin: str
    alias_location_key: str
    match_confidence: int
    link_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AttributeConflict(TypedDict, total=False):
    id: str
    provider_id: str
    attribute_group: str
    attribute_key: str
    incumbent_attribute_id: str
    challenger_attribute_id: str
    incumbent_source_id: str
    challenger_source_id: str
    resolution: str
    resolution_reason: Optional[str]
    resolved_value: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionTarget(TypedDict, total=False):
    id: str
    target_code: str
    endpoint_uri: str
    required_quality_floor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionBatch(TypedDict, total=False):
    id: str
    distribution_target_id: str
    snapshot_cutoff_at: str
    provider_count: int
    status: str
    failure_reason: Optional[str]
    retry_of_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionItem(TypedDict, total=False):
    # Append-only (PRD §2.5): NO updated_at, NO version.
    id: str
    distribution_batch_id: str
    provider_id: str
    change_kind: str
    payload_hash: str
    created_at: str


class AttestationCampaign(TypedDict, total=False):
    id: str
    name: str
    window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttestationRequest(TypedDict, total=False):
    id: str
    attestation_campaign_id: str
    provider_id: str
    sent_at: Optional[str]
    due_at: Optional[str]
    responded_at: Optional[str]
    attestation_outcome: Optional[str]
    corrected_payload: Optional[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class DataQualityScore(TypedDict, total=False):
    # Append-only (PRD §2.5): NO updated_at, NO version.
    id: str
    provider_id: str
    computed_at: str
    completeness_component: int
    freshness_component: int
    conflict_component: int
    attestation_component: int
    total_score: int
    roster_file_id: Optional[str]
    created_at: str


class ProviderMergeRecord(TypedDict, total=False):
    # Append-only (PRD §2.5): NO updated_at, NO version.
    id: str
    survivor_provider_id: str
    merged_provider_id: str
    decided_by_user_id: str
    decided_at: str
    rationale: str
    created_at: str
