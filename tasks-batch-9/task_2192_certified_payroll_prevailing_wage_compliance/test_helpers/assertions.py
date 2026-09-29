"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_identity(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_versioned(data: dict, entity: str):
    _assert_identity(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_lightweight(data: dict, entity: str):
    """Portals, wage rates, staff rows and payroll lines carry only id and created_at."""
    _assert_identity(data, entity)
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_reporting_portal(data: dict):
    _assert_lightweight(data, "ReportingPortal")
    assert isinstance(data["portal_code"], str) and data["portal_code"]
    assert data["submission_format"] in ("WH347_PDF", "XML_LCP", "CSV_FLAT")
    assert isinstance(data["cutoff_offset_days"], int)
    assert isinstance(data["grace_hours"], int)
    assert isinstance(data["requires_notarized_statement"], bool)


def assert_wage_determination(data: dict):
    _assert_versioned(data, "WageDetermination")
    assert isinstance(data["decision_number"], str) and data["decision_number"]
    assert isinstance(data["modification_number"], int) and data["modification_number"] >= 0
    assert isinstance(data["locality_code"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["rate_count"], int) and data["rate_count"] >= 0


def assert_wage_rate(data: dict):
    _assert_lightweight(data, "WageRate")
    assert isinstance(data["classification_code"], str)
    assert isinstance(data["trade_code"], str)
    assert data["zone_code"] in ("BASE", "ZONE1", "ZONE2")
    assert isinstance(data["base_hourly_rate_cents"], int) and data["base_hourly_rate_cents"] >= 1
    assert isinstance(data["fringe_hourly_rate_cents"], int) and data["fringe_hourly_rate_cents"] >= 0
    assert isinstance(data["zone_adjustment_cents"], int) and data["zone_adjustment_cents"] >= 0
    scale = data["apprentice_scale_pct"]
    assert isinstance(scale, list) and 1 <= len(scale) <= 8
    assert all(isinstance(p, int) and 30 <= p <= 100 for p in scale)
    assert all(scale[i] <= scale[i + 1] for i in range(len(scale) - 1)), (
        f"apprentice_scale_pct must be non-decreasing, got {scale}"
    )


def assert_contractor(data: dict):
    _assert_versioned(data, "Contractor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["dir_registration_number"], str)
    assert data["registration_status"] in ("REGISTERED", "LAPSED")
    assert data["debarment_status"] in ("CLEAR", "PROPOSED", "DEBARRED")
    assert isinstance(data["debarment_risk_score"], int)
    assert 0 <= data["debarment_risk_score"] <= 100, (
        f"debarment_risk_score must be clamped to 0..100, got {data['debarment_risk_score']}"
    )
    assert isinstance(data["open_critical_finding_count"], int)
    assert isinstance(data["outstanding_restitution_cents"], int)


def assert_contractor_staff(data: dict):
    _assert_lightweight(data, "ContractorStaff")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["capability"] in ("PREPARER", "CERTIFIER", "BOTH")


def assert_apprentice_program(data: dict):
    _assert_versioned(data, "ApprenticeProgram")
    assert isinstance(data["registration_number"], str)
    assert isinstance(data["sponsor_name"], str)
    assert isinstance(data["trade_code"], str)
    assert data["registration_status"] in ("REGISTERED", "PROVISIONAL", "LAPSED")
    assert 1 <= data["allowed_apprentice_hours_per_100_journey"] <= 100
    assert 1 <= data["period_count"] <= 8


def assert_fringe_plan(data: dict):
    _assert_versioned(data, "FringeBenefitPlan")
    assert isinstance(data["plan_name"], str)
    assert data["plan_type"] in ("BONA_FIDE_TRUST", "UNFUNDED", "CASH_IN_LIEU")
    assert isinstance(data["annual_contribution_cents"], int)
    assert data["approval_status"] in ("PENDING_APPROVAL", "APPROVED", "REJECTED")
    assert isinstance(data["annualized_credit_cents"], int)
    assert isinstance(data["claimed_credit_cents"], int)
    assert data["claimed_credit_cents"] >= data["annualized_credit_cents"], (
        "the covered-hours-only figure is always greater than or equal to the annualized figure"
    )


def assert_project(data: dict):
    _assert_versioned(data, "Project")
    assert isinstance(data["project_name"], str)
    assert isinstance(data["awarding_agency"], str)
    assert data["zone_code"] in ("BASE", "ZONE1", "ZONE2")
    assert data["funding_source"] in ("FEDERAL_DAVIS_BACON", "STATE_ONLY", "DUAL")
    assert data["status"] in ("AWARDED", "ACTIVE", "SUBSTANTIALLY_COMPLETE", "CLOSED")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    for field in (
        "open_finding_count", "open_critical_finding_count",
        "outstanding_restitution_cents", "suspended_assignment_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"Project.{field} must be a non-negative integer"
    assert data["open_critical_finding_count"] <= data["open_finding_count"], (
        "open_critical_finding_count is a subset of open_finding_count"
    )


def assert_contract_assignment(data: dict):
    _assert_versioned(data, "ContractAssignment")
    assert data["status"] in ("INVITED", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["tier"], int) and 0 <= data["tier"] <= 4
    assert isinstance(data["subcontract_amount_cents"], int) and data["subcontract_amount_cents"] >= 1
    assert float(data["cumulative_certified_hours"]) >= 0
    assert isinstance(data["cumulative_restitution_cents"], int)
    assert isinstance(data["open_finding_count"], int)


def assert_worker(data: dict):
    _assert_versioned(data, "Worker")
    assert isinstance(data["worker_number"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["default_classification_code"], str)
    assert isinstance(data["interview_count"], int) and data["interview_count"] >= 0
    if data.get("apprentice_period") is not None:
        assert 1 <= data["apprentice_period"] <= 8


def assert_payroll_submission(data: dict):
    _assert_versioned(data, "PayrollSubmission")
    assert data["workflow_status"] in (
        "DRAFT", "PENDING_CERTIFICATION", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "RETURNED",
    )
    assert data["compliance_status"] in (
        "UNVERIFIED", "COMPLIANT", "DEFICIENT", "RESTITUTION_PENDING", "REMEDIED",
    )
    assert isinstance(data["no_work_performed"], bool)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["straight_time_underpayment_cents"], int)
    assert isinstance(data["make_whole_underpayment_cents"], int)
    assert float(data["total_hours_reported"]) >= 0
    assert float(data["excess_apprentice_hours"]) >= 0
    assert data["straight_time_underpayment_cents"] <= data["make_whole_underpayment_cents"], (
        "the straight-time total omits every overtime deficiency and can never exceed the make-whole total"
    )


def assert_payroll_line(data: dict):
    _assert_lightweight(data, "PayrollLine")
    assert isinstance(data["classification_code"], str)
    assert 0 <= float(data["straight_hours"]) <= 40
    assert float(data["overtime_hours"]) >= 0
    for field in (
        "base_rate_paid_cents", "overtime_rate_paid_cents", "fringe_cash_paid_cents",
        "required_base_cents", "required_fringe_cents", "creditable_fringe_cents",
        "line_underpayment_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"PayrollLine.{field} must be a non-negative whole-cent integer"
        )
    assert isinstance(data["reported_as_apprentice"], bool)
    assert float(data["reclassified_journey_hours"]) >= 0
    assert data["creditable_fringe_cents"] <= data["required_fringe_cents"] or (
        data["required_fringe_cents"] == 0 and data["creditable_fringe_cents"] == 0
    ), "creditable_fringe_cents is capped at required_fringe_cents"


def assert_interview(data: dict):
    _assert_versioned(data, "OnSiteInterview")
    assert data["status"] in (
        "SCHEDULED", "CONDUCTED_MATCHED", "CONDUCTED_DISCREPANT", "CANCELLED",
    )
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_finding(data: dict):
    _assert_versioned(data, "Finding")
    assert data["finding_type"] in (
        "UNDERPAYMENT", "MISCLASSIFICATION", "APPRENTICE_RATIO", "FRINGE_CREDIT", "MISSING_PAYROLL",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in (
        "OPEN", "RESPONSE_SUBMITTED", "RESPONSE_REJECTED", "RESPONSE_ACCEPTED", "WITHDRAWN",
    )
    assert isinstance(data["restitution_required_cents"], int) and data["restitution_required_cents"] >= 0
    assert isinstance(data["restitution_outstanding_cents"], int) and data["restitution_outstanding_cents"] >= 0
    assert isinstance(data["response_round"], int) and data["response_round"] >= 0


def assert_restitution_payment(data: dict):
    _assert_versioned(data, "RestitutionPayment")
    assert data["status"] in ("PENDING", "DISBURSED", "REVERSED", "VOIDED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_restitution_identity(finding: dict, disbursed_payments_total: int):
    """restitution_required_cents == restitution_outstanding_cents + sum of DISBURSED amounts."""
    assert finding["restitution_required_cents"] == (
        finding["restitution_outstanding_cents"] + disbursed_payments_total
    ), (
        f"conserved restitution ledger broken: required={finding['restitution_required_cents']}, "
        f"outstanding={finding['restitution_outstanding_cents']}, disbursed={disbursed_payments_total}"
    )
