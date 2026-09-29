"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

TERM_STATUSES = ["PLANNING", "OPEN", "PAYROLL_LOCKED", "CLOSED"]
PAY_PERIOD_STATUSES = ["OPEN", "LOCKED", "CLOSED"]
SOURCE_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
LIFECYCLE_STATUSES = [
    "DRAFT", "SUBMITTED", "RETURNED", "FUNDING_VERIFIED", "APPROVED", "ACTIVE",
    "NON_RENEWAL_PENDING", "COMPLETED", "TERMINATED", "CANCELLED",
]
PAYROLL_STATUSES = [
    "NOT_SCHEDULED", "SCHEDULED", "PARTIALLY_DISBURSED", "FULLY_DISBURSED",
    "PAY_SUSPENDED", "PAY_VOIDED",
]
ALLOCATION_STATUSES = ["PROPOSED", "COMMITTED", "RELEASED", "EXPENDED"]
DISBURSEMENT_STATUSES = ["SCHEDULED", "PAID", "VOIDED", "REVERSED"]
RENEWAL_STATUSES = ["DRAFT", "SAP_CERTIFIED", "NOTICE_ISSUED", "ACKNOWLEDGED"]
ASSESSMENT_STATUSES = ["PROVISIONAL", "FINAL", "AMENDED", "SUPERSEDED"]

# Lifecycle states that count toward a student's effort aggregates.
COUNTED_LIFECYCLE_STATUSES = [
    "SUBMITTED", "FUNDING_VERIFIED", "APPROVED", "ACTIVE", "NON_RENEWAL_PENDING",
]

# Lifecycle states whose remission confers an assessable tuition benefit.
BENEFIT_BEARING_LIFECYCLE_STATUSES = [
    "APPROVED", "ACTIVE", "NON_RENEWAL_PENDING", "COMPLETED", "TERMINATED",
]


def _assert_system_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert "_" not in data.get("id", "x_x"), f"{label}.id carries no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version is an integer starting at 1"
    )


def assert_academic_term(data: dict):
    _assert_system_fields(data, "AcademicTerm")
    assert data["status"] in TERM_STATUSES
    assert data["session_type"] in ["IN_SESSION", "BREAK"]
    assert data["proration_method"] in ["CALENDAR_DAY", "WORKDAY"]
    assert isinstance(data["pay_period_count"], int) and data["pay_period_count"] >= 0
    assert isinstance(data["tax_calendar_year"], int)
    assert data["term_end"] >= data["term_start"]
    assert data["term_start"] <= data["remission_drop_deadline"] <= data["term_end"]


def assert_department(data: dict):
    _assert_system_fields(data, "Department")
    assert 1 <= len(data["code"]) <= 16
    assert 1 <= data["non_renewal_notice_days"] <= 180


def assert_stipend_policy(data: dict):
    _assert_system_fields(data, "StipendPolicy")
    assert data["assistantship_type"] in ["TEACHING", "RESEARCH", "ADMINISTRATIVE"]
    assert data["degree_level"] in ["MASTERS", "DOCTORAL"]
    assert data["min_fte_monthly_stipend_cents"] >= 1
    assert data["per_credit_tuition_cents"] >= 1
    assert data["max_remission_cents_per_term"] >= 1
    assert data["term_insurance_premium_cents"] >= 0
    assert 1 <= data["insurance_min_effort_pct"] <= 100
    assert data["min_insurance_duration_days"] >= 1
    assert data["tuition_tax_exempt_cap_cents"] >= 0


def assert_pay_period(data: dict):
    _assert_system_fields(data, "PayPeriod")
    assert 1 <= data["sequence_no"] <= 24
    assert data["period_end_exclusive"] > data["period_start"]
    assert data["pay_date"] >= data["period_end_exclusive"]
    assert data["calendar_day_count"] >= 1
    assert 0 <= data["workday_count"] <= data["calendar_day_count"]
    assert data["status"] in PAY_PERIOD_STATUSES


def assert_graduate_student(data: dict):
    _assert_system_fields(data, "GraduateStudent")
    assert data["degree_level"] in ["MASTERS", "DOCTORAL"]
    assert isinstance(data["is_international"], bool)
    assert 0.0 <= float(data["cumulative_gpa"]) <= 4.00
    assert data["visa_type"] in ["F1", "J1", "NONE"]
    assert 0 <= data["enrolled_credit_hours"] <= 24
    assert 0.0 <= float(data["external_weekly_hours"]) <= 40.0
    assert data["sap_status"] in ["SATISFACTORY", "PROBATION", "UNSATISFACTORY"]
    assert 1 <= data["effort_cap_pct"] <= 100
    assert data["total_effort_pct"] >= 0
    assert float(data["assigned_hours_per_week"]) >= 0.0
    assert data["tuition_benefit_ytd_cents"] >= 0
    assert data["taxable_tuition_benefit_ytd_cents"] >= 0


def assert_funding_source(data: dict):
    _assert_system_fields(data, "FundingSource")
    assert data["source_type"] in ["GRANT", "DEPARTMENTAL_BUDGET", "FELLOWSHIP"]
    assert data["status"] in SOURCE_STATUSES
    assert data["authorized_amount_cents"] >= 1
    assert data["budget_period_end"] >= data["budget_period_start"]
    assert isinstance(data["allows_tuition_remission"], bool)
    assert 1 <= data["grant_effort_cap_pct"] <= 100
    assert data["auto_reinstate_threshold_cents"] >= 0
    if data["suspension_reason"] is not None:
        assert data["suspension_reason"] in [
            "SPONSOR_HOLD", "OVERCOMMITMENT", "AUDIT",
        ]
    assert_funding_conservation(data)


def assert_funding_conservation(source: dict):
    """authorized_amount_cents equals available plus committed plus expended."""
    authorized = source["authorized_amount_cents"]
    total = (
        source["available_amount_cents"]
        + source["committed_amount_cents"]
        + source["expended_amount_cents"]
    )
    assert authorized == total, (
        "Funding conservation broken on source "
        f"{source.get('source_code')}: authorized {authorized} != available "
        f"{source['available_amount_cents']} + committed "
        f"{source['committed_amount_cents']} + expended "
        f"{source['expended_amount_cents']}"
    )


def assert_appointment(data: dict):
    _assert_system_fields(data, "Appointment")
    assert data["assistantship_type"] in ["TEACHING", "RESEARCH", "ADMINISTRATIVE"]
    assert 1 <= data["effort_pct"] <= 100
    assert data["end_date"] >= data["start_date"]
    assert data["monthly_stipend_cents"] >= 1
    assert data["lifecycle_status"] in LIFECYCLE_STATUSES
    assert data["payroll_status"] in PAYROLL_STATUSES
    assert data["tuition_remission_pct"] in [0, 50, 75, 100]
    assert isinstance(data["insurance_eligible"], bool)
    assert isinstance(data["renewal_eligible"], bool)
    assert data["duration_days"] >= 1
    assert float(data["weekly_hours"]) >= 0.0
    for money in (
        "total_stipend_cents", "tuition_remission_cents", "insurance_subsidy_cents",
        "employee_premium_cents", "net_term_stipend_cents",
    ):
        assert isinstance(data[money], int), f"{money} is an integer number of cents"


def assert_effort_profile(data: dict, weekly_hours: float, duration_days: int,
                          tuition_remission_pct: int, insurance_eligible: bool):
    """The four fields the PRD derives immediately at appointment creation."""
    assert float(data["weekly_hours"]) == weekly_hours, (
        f"Expected weekly_hours {weekly_hours}, got {data['weekly_hours']}"
    )
    assert data["duration_days"] == duration_days, (
        f"Expected duration_days {duration_days}, got {data['duration_days']}"
    )
    assert data["tuition_remission_pct"] == tuition_remission_pct, (
        f"Expected tuition_remission_pct {tuition_remission_pct}, "
        f"got {data['tuition_remission_pct']}"
    )
    assert data["insurance_eligible"] is insurance_eligible, (
        f"Expected insurance_eligible {insurance_eligible}, "
        f"got {data['insurance_eligible']}"
    )


def assert_funding_allocation(data: dict):
    _assert_system_fields(data, "FundingAllocation")
    assert data["status"] in ALLOCATION_STATUSES
    assert 0.01 <= float(data["share_pct"]) <= 100.00
    assert data["plan_sequence"] >= 1
    assert isinstance(data["is_cost_share"], bool)
    assert data["allocated_stipend_cents"] >= 0
    assert data["allocated_remission_cents"] >= 0
    assert data["disbursed_amount_cents"] >= 0


def assert_released_allocation(data: dict, release_reason: str):
    """A released allocation is terminal with both allocated amounts zeroed."""
    assert data["status"] == "RELEASED", (
        f"Expected RELEASED allocation, got {data['status']}"
    )
    assert data["release_reason"] == release_reason, (
        f"Expected release_reason {release_reason}, got {data['release_reason']}"
    )
    assert data["allocated_stipend_cents"] == 0, "release zeroes allocated_stipend_cents"
    assert data["allocated_remission_cents"] == 0, (
        "release zeroes allocated_remission_cents"
    )


def assert_stipend_disbursement(data: dict):
    _assert_system_fields(data, "StipendDisbursement")
    assert data["status"] in DISBURSEMENT_STATUSES
    assert data["proration_method_applied"] in ["CALENDAR_DAY", "WORKDAY"]
    assert data["covered_units"] >= 1
    assert data["period_units"] >= data["covered_units"]
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["allocation_split"], list) and data["allocation_split"]
    for element in data["allocation_split"]:
        assert is_valid_uuid(element["funding_allocation_id"])
        assert element["plan_sequence"] >= 1
        assert isinstance(element["amount_cents"], int)


def assert_allocation_split_sums_to_gross(data: dict):
    """Each disbursement's per-source split adds back to its own gross exactly."""
    total = sum(e["amount_cents"] for e in data["allocation_split"])
    assert total == data["gross_amount_cents"], (
        f"allocation_split sums to {total}, expected gross "
        f"{data['gross_amount_cents']}"
    )


def assert_renewal_decision(data: dict):
    _assert_system_fields(data, "RenewalDecision")
    assert data["status"] in RENEWAL_STATUSES
    assert data["decision"] in ["PENDING", "RENEW", "NON_RENEW"]
    assert isinstance(data["sap_certified"], bool)
    assert data["revision_count"] >= 0


def assert_tax_assessment(data: dict):
    _assert_system_fields(data, "TaxAssessment")
    assert data["status"] in ASSESSMENT_STATUSES
    assert data["variant_applied"] in ["TERM_PROVISIONAL", "CALENDAR_YEAR_FINAL"]
    for money in ("benefit_cents", "exempt_cents", "taxable_cents",
                  "imputed_withholding_cents"):
        assert isinstance(data[money], int), f"{money} is an integer number of cents"
    assert_assessment_identity(data)


def assert_assessment_identity(data: dict):
    """benefit_cents always equals exempt_cents plus taxable_cents."""
    assert data["benefit_cents"] == data["exempt_cents"] + data["taxable_cents"], (
        f"benefit {data['benefit_cents']} != exempt {data['exempt_cents']} + "
        f"taxable {data['taxable_cents']}"
    )
    assert data["taxable_cents"] >= 0, "taxable_cents is never negative"


def assert_envelope_meta(meta: dict):
    """Every response carries a request id starting ``req_`` and a timestamp."""
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        f"api_request_id must start with req_, got {meta.get('api_request_id')}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp"
    )


def assert_page_meta(meta: dict, limit: int, offset: int, total_count: int,
                     has_more: bool):
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )
