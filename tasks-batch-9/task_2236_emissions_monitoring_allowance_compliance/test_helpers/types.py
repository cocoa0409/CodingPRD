"""Domain types for the Emissions Monitoring & Allowance Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    FACILITY_OPERATOR = "FacilityOperator"
    QA_ANALYST = "QAAnalyst"
    EMISSIONS_REPORT_PREPARER = "EmissionsReportPreparer"
    DESIGNATED_REPRESENTATIVE = "DesignatedRepresentative"
    ALLOWANCE_TRADER = "AllowanceTrader"


ALL_ROLE_NAMES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class AllowanceProgram(str, Enum):
    ARP_SO2 = "ARP_SO2"
    CSAPR_NOX_ANNUAL = "CSAPR_NOX_ANNUAL"
    CSAPR_NOX_OZONE = "CSAPR_NOX_OZONE"
    CSAPR_SO2_G1 = "CSAPR_SO2_G1"


class FacilityStatus(str, Enum):
    OPERATING = "OPERATING"
    RETIRED = "RETIRED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    DEFICIT = "DEFICIT"


class PrimaryFuel(str, Enum):
    COAL = "COAL"
    NATURAL_GAS = "NATURAL_GAS"
    OIL = "OIL"


class ControlDevice(str, Enum):
    SCR = "SCR"
    SNCR = "SNCR"
    FGD = "FGD"
    NONE = "NONE"


class ControlStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DispatchState(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RESERVE_SHUTDOWN = "RESERVE_SHUTDOWN"


class MonitoredParameter(str, Enum):
    SO2 = "SO2"
    NOX_RATE = "NOX_RATE"
    CO2 = "CO2"
    FLOW = "FLOW"


class SystemType(str, Enum):
    CEM = "CEM"
    FLOW_MONITOR = "FLOW_MONITOR"
    EXCEPTED_APPENDIX_D = "EXCEPTED_APPENDIX_D"


class QaStatus(str, Enum):
    RECERTIFICATION_PENDING = "RECERTIFICATION_PENDING"
    CERTIFIED = "CERTIFIED"
    CONDITIONALLY_VALID = "CONDITIONALLY_VALID"
    OUT_OF_CONTROL = "OUT_OF_CONTROL"
    RETIRED = "RETIRED"


class CalStatus(str, Enum):
    CAL_CURRENT = "CAL_CURRENT"
    CAL_EXPIRED = "CAL_EXPIRED"
    CAL_FAILED = "CAL_FAILED"


class QaAction(str, Enum):
    CERTIFY = "CERTIFY"
    CONDITIONALLY_VALIDATE = "CONDITIONALLY_VALIDATE"
    DECLARE_OUT_OF_CONTROL = "DECLARE_OUT_OF_CONTROL"
    RETIRE = "RETIRE"


class CalibrationResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    OUT_OF_CONTROL_TRIGGERED = "OUT_OF_CONTROL_TRIGGERED"


class RataTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNS_RECORDED = "RUNS_RECORDED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class RaBasis(str, Enum):
    REFERENCE_MEAN = "REFERENCE_MEAN"
    APPLICABLE_STANDARD = "APPLICABLE_STANDARD"


class FuelSampleStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZED = "ANALYZED"
    INVALIDATED = "INVALIDATED"


class AnalysisMethod(str, Enum):
    ASTM_D5865 = "ASTM_D5865"
    ASTM_D4239 = "ASTM_D4239"
    GC_D1945 = "GC_D1945"


class FuelAnalysisOutcome(str, Enum):
    ANALYZED = "ANALYZED"
    INVALIDATE = "INVALIDATE"


class HeatInputMethod(str, Enum):
    CEMS_FLOW_CO2 = "CEMS_FLOW_CO2"
    APPENDIX_D_FUEL = "APPENDIX_D_FUEL"


class DataQuality(str, Enum):
    MEASURED = "MEASURED"
    SUBSTITUTED = "SUBSTITUTED"
    UNAVAILABLE = "UNAVAILABLE"


class SubstitutionMethod(str, Enum):
    NONE = "NONE"
    T1_90TH_PERCENTILE = "T1_90TH_PERCENTILE"
    T2_95TH_PERCENTILE = "T2_95TH_PERCENTILE"
    T3_LOOKBACK_MAXIMUM = "T3_LOOKBACK_MAXIMUM"
    T4_MAX_POTENTIAL_CONCENTRATION = "T4_MAX_POTENTIAL_CONCENTRATION"


class QuarterlyReportStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SubmissionFormat(str, Enum):
    XML_ECMPS = "XML_ECMPS"
    JSON_ECMPS = "JSON_ECMPS"


class CertificationStatus(str, Enum):
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class Pollutant(str, Enum):
    SO2 = "SO2"
    NOX_RATE = "NOX_RATE"
    CO2 = "CO2"


class LimitUnits(str, Enum):
    LB_PER_MMBTU = "LB_PER_MMBTU"
    LB_PER_HR = "LB_PER_HR"
    TONS_PER_YEAR = "TONS_PER_YEAR"


class AveragingBasis(str, Enum):
    ROLLING_3_HOUR = "ROLLING_3_HOUR"
    ROLLING_30_DAY = "ROLLING_30_DAY"
    ANNUAL = "ANNUAL"


class EvaluationStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    IN_COMPLIANCE = "IN_COMPLIANCE"
    EXCEEDED = "EXCEEDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ExcessEventStatus(str, Enum):
    DETECTED = "DETECTED"
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EXCUSED = "EXCUSED"
    ENFORCEABLE = "ENFORCEABLE"
    WITHDRAWN = "WITHDRAWN"


class AllowanceAccountStatus(str, Enum):
    OPEN = "OPEN"
    TRUE_UP_LOCKED = "TRUE_UP_LOCKED"
    CLOSED = "CLOSED"


class TransactionType(str, Enum):
    PURCHASE = "PURCHASE"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    SURRENDER = "SURRENDER"
    PENALTY_DEDUCTION = "PENALTY_DEDUCTION"


class TransactionOrigin(str, Enum):
    MANUAL = "MANUAL"
    TRUE_UP_SURRENDER = "TRUE_UP_SURRENDER"
    TRUE_UP_PENALTY = "TRUE_UP_PENALTY"


class TransactionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RECORDED = "RECORDED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class TransactionAction(str, Enum):
    RECORD = "RECORD"
    SETTLE = "SETTLE"
    REVERSE = "REVERSE"


class OutageType(str, Enum):
    PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"
    FORCED = "FORCED"
    RATA_TEST_BYPASS = "RATA_TEST_BYPASS"


class ControlOutageStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ControlOutageAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    CLOSE = "CLOSE"
    CANCEL = "CANCEL"


class ReportDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class EventDecision(str, Enum):
    RETURN = "RETURN"
    EXCUSE = "EXCUSE"
    ENFORCE = "ENFORCE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Facility(TypedDict):
    id: str
    name: str
    orispl_code: str
    state_code: str
    operator_org: str
    programs: List[str]
    true_up_deadline_utc: str
    max_concurrent_control_outages: int
    status: str
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    facility_id: str
    unit_identifier: str
    primary_fuel: str
    nameplate_capacity_mw: float
    max_rated_heat_input_mmbtu_hr: float
    control_device: Optional[str]
    control_status: str
    dispatch_state: str
    dispatch_restricted: bool
    data_availability_pct: float
    certified_so2_lbs_ytd: float
    created_at: str
    updated_at: str
    version: int


class MonitoringSystem(TypedDict):
    id: str
    unit_id: str
    parameter: str
    system_type: str
    span_value: float
    calibration_error_spec_pct: float
    qa_status: str
    cal_status: str
    consecutive_failed_calibrations: int
    out_of_control_since_utc: Optional[str]
    last_calibration_utc: Optional[str]
    bias_adjustment_factor: float
    created_at: str
    updated_at: str
    version: int


class DailyCalibration(TypedDict):
    """Append-only ledger entry: carries only id and created_at (PRD §2.5)."""
    id: str
    monitoring_system_id: str
    calibration_utc: str
    zero_reference_value: float
    zero_measured_value: float
    span_reference_value: float
    span_measured_value: float
    zero_error_pct_of_span: float
    span_error_pct_of_span: float
    result: str
    monitoring_system_version_after: int
    created_at: str


class RataTest(TypedDict):
    id: str
    monitoring_system_id: str
    retest_of_rata_test_id: Optional[str]
    window_start_utc: str
    window_end_utc: str
    applicable_standard_value: Optional[float]
    status: str
    run_count: int
    reference_mean: Optional[float]
    cems_mean: Optional[float]
    mean_difference: Optional[float]
    confidence_coefficient: Optional[float]
    ra_basis: str
    relative_accuracy_pct: Optional[float]
    bias_test_failed: bool
    bias_adjustment_factor: float
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class OperatingHour(TypedDict):
    """Append-only ledger entry: carries only id and created_at (PRD §2.5)."""
    id: str
    unit_id: str
    quarterly_report_id: str
    fuel_sample_id: Optional[str]
    hour_begin_utc: str
    op_time_fraction: float
    gross_load_mw: Optional[float]
    heat_input_method: str
    flow_scfh: Optional[float]
    co2_conc_pct: Optional[float]
    so2_conc_ppm: Optional[float]
    nox_rate_lb_mmbtu: Optional[float]
    fuel_flow_lbs: Optional[float]
    heat_input_mmbtu: Optional[float]
    so2_mass_lbs: Optional[float]
    nox_mass_lbs: Optional[float]
    co2_mass_tons: Optional[float]
    data_quality: str
    substitution_method: str
    substituted_so2_conc_ppm: Optional[float]
    monitor_data_availability_pct_at_substitution: Optional[float]
    quarterly_report_version_after: int
    created_at: str


class FuelSample(TypedDict):
    id: str
    unit_id: str
    sample_utc: str
    fuel_type: str
    lot_identifier: str
    status: str
    gcv_btu_per_lb: Optional[float]
    sulfur_content_pct: Optional[float]
    analysis_method: Optional[str]
    analyzed_utc: Optional[str]
    invalidation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarterlyReport(TypedDict):
    id: str
    unit_id: str
    year: int
    quarter: int
    status: str
    submission_format: Optional[str]
    submitted_by_user_id: Optional[str]
    submitted_utc: Optional[str]
    operating_hour_count: int
    measured_hour_count: int
    substituted_hour_count: int
    monitor_data_availability_pct: float
    total_heat_input_mmbtu: float
    total_so2_lbs: float
    total_so2_tons: float
    total_nox_lbs: float
    total_co2_tons: float
    resubmission_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceCertification(TypedDict):
    id: str
    quarterly_report_id: str
    certifier_user_id: str
    statement_text: str
    status: str
    signed_utc: str
    revoked_utc: Optional[str]
    revocation_reason: Optional[str]
    certified_so2_lbs_snapshot: float
    created_at: str
    updated_at: str
    version: int


class PermitLimit(TypedDict):
    id: str
    unit_id: str
    pollutant: str
    limit_value: float
    limit_units: str
    averaging_basis: str
    effective_from_utc: str
    current_rolling_value: Optional[float]
    window_sample_count: int
    window_evaluated_utc: Optional[str]
    evaluation_status: str
    created_at: str
    updated_at: str
    version: int


class ExcessEmissionEvent(TypedDict):
    id: str
    permit_limit_id: str
    unit_id: str
    detected_utc: str
    observed_value: float
    limit_value_snapshot: float
    exceedance_magnitude: float
    penalty_allowance_debit_tons: int
    status: str
    narrative: Optional[str]
    corrective_action: Optional[str]
    disposition_reason: Optional[str]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class AllowanceAccount(TypedDict):
    id: str
    facility_id: str
    program: str
    compliance_year: int
    holdings_current_vintage_tons: float
    holdings_prior_vintage_tons: float
    holdings_next_vintage_tons: float
    obligation_tons: int
    surrendered_tons: float
    penalty_deducted_tons: float
    shortfall_tons: float
    status: str
    true_up_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllowanceTransaction(TypedDict):
    id: str
    allowance_account_id: str
    counterparty_account_id: Optional[str]
    transaction_type: str
    quantity_tons: float
    vintage_year: int
    status: str
    origin: str
    debited_current_tons: float
    debited_prior_tons: float
    debited_next_tons: float
    allowance_account_version_after: int
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ControlOutageWindow(TypedDict):
    id: str
    unit_id: str
    start_utc: str
    end_utc: str
    outage_type: str
    control_device: str
    status: str
    activated_utc: Optional[str]
    closed_utc: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
