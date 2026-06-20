"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the Assisted Living & Memory Care PRD. Every entity except the
medication administration record carries the full id/created_at/updated_at/version
set; the eMAR record is append-only and carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    NURSE = "Nurse"
    BILLING_CLERK = "BillingClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STAFF = "Staff"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class FacilityLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"
    RETIRED = "RETIRED"


class UnitWing(str, Enum):
    ASSISTED_LIVING = "ASSISTED_LIVING"
    MEMORY_CARE = "MEMORY_CARE"


class ResidentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ASSESSED = "ASSESSED"
    ADMITTED = "ADMITTED"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"


class StayType(str, Enum):
    STANDARD = "STANDARD"
    RESPITE = "RESPITE"


class CareLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    MEMORY_CARE = "MEMORY_CARE"


class DischargeDisposition(str, Enum):
    TRANSFER_TO_SNF = "TRANSFER_TO_SNF"
    OTHER = "OTHER"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class MedicationOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AdministrationOutcome(str, Enum):
    GIVEN = "GIVEN"
    REFUSED = "REFUSED"
    HELD = "HELD"
    MISSED = "MISSED"


class MoveInAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class BillingStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class IncidentType(str, Enum):
    FALL = "FALL"
    MEDICATION_ERROR = "MEDICATION_ERROR"
    ELOPEMENT = "ELOPEMENT"
    INJURY = "INJURY"
    OTHER = "OTHER"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ScopeSeverity(str, Enum):
    A_C_NO_HARM = "A_C_NO_HARM"
    D_F_NO_HARM = "D_F_NO_HARM"
    G_I_ACTUAL_HARM = "G_I_ACTUAL_HARM"
    J_L_IMMEDIATE_JEOPARDY = "J_L_IMMEDIATE_JEOPARDY"


class SurveyDeficiencyStatus(str, Enum):
    CITED = "CITED"
    POC_SUBMITTED = "POC_SUBMITTED"
    POC_ACCEPTED = "POC_ACCEPTED"
    POC_REJECTED = "POC_REJECTED"
    CORRECTED = "CORRECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    license_number: str
    care_point_rate_cents: int
    license_status: str
    bed_count: int
    occupied_bed_count: int
    occupancy_rate_bps: int
    open_deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    facility_id: str
    unit_number: str
    wing: str
    monthly_base_rent_cents: int
    current_resident_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    facility_id: str
    full_name: str
    date_of_birth: str
    stay_type: str
    respite_end_date: Optional[str]
    current_care_level: Optional[str]
    current_care_points: int
    assigned_unit_id: Optional[str]
    open_balance_cents: int
    status: str
    discharge_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    resident_id: str
    adl_bathing: int
    adl_dressing: int
    adl_toileting: int
    adl_transferring: int
    adl_eating: int
    cognition_score: int
    behavior_flags: int
    care_points_total: int
    care_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    resident_id: str
    source_assessment_id: str
    supersedes_care_plan_id: Optional[str]
    adl_support_items: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict):
    id: str
    resident_id: str
    drug_name: str
    dose: str
    schedule_times: List[str]
    is_controlled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MoveInAgreement(TypedDict):
    id: str
    resident_id: str
    unit_id: str
    move_in_date: str
    monthly_base_rent_cents: int
    community_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict):
    id: str
    resident_id: str
    period_year: int
    period_month: int
    is_first_statement: bool
    rent_charge_cents: int
    care_points_charge_cents: int
    community_fee_charge_cents: int
    total_charge_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    resident_id: str
    incident_type: str
    occurred_at: str
    severity: str
    requires_state_report: bool
    linked_deficiency_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyDeficiency(TypedDict):
    id: str
    facility_id: str
    tag_code: str
    scope_severity: str
    cited_at: str
    poc_due_date: str
    poc_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity (common_fields: false -> id + created_at ONLY)
# ---------------------------------------------------------------------------
class MedicationAdministrationRecord(TypedDict):
    id: str
    medication_order_id: str
    resident_id: str
    scheduled_time: str
    outcome: str
    witness_user_id: Optional[str]
    administered_by_user_id: str
    created_at: str
