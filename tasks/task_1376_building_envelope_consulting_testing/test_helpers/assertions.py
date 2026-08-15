"""Entity assertions and domain invariant checkers.

Each assert_* function validates the system-managed fields of PRD section
2.10 plus the entity's declared field surface and enum membership.
LitigationHold and Invoice carry the reduced property set (id, created_at
only) per PRD section 2.10.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    AssemblyReviewStatus,
    AssemblyType,
    BarrierLayer,
    ChamberSlotStatus,
    DesignReviewStatus,
    EngagementPosture,
    EngagementStatus,
    FieldTestDiagnosisStatus,
    FieldTestExecutionStatus,
    FieldTestResult,
    InvoiceStatus,
    LitigationHoldStatus,
    MaintenanceVisitStatus,
    MockUpStatus,
    RemediationPlanStatus,
    SurveyStatus,
    SurveyType,
    TestMethod,
    WarrantyClaimStatus,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), \
        f"{entity}.version must be an integer"


def _assert_reduced_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_engagement(data: dict):
    _assert_common_fields(data, "Engagement")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert isinstance(data["fee_cap_cents"], int) and data["fee_cap_cents"] >= 1
    assert isinstance(data["labor_rate_cents_per_hour"], int) \
        and data["labor_rate_cents_per_hour"] >= 1
    assert isinstance(data["recognized_fees_cents"], int)
    assert isinstance(data["invoiced_cents"], int)
    assert isinstance(data["fee_headroom_cents"], int)
    assert isinstance(data["risk_score"], int)
    assert data["posture"] in [p.value for p in EngagementPosture]
    assert data["status"] in [s.value for s in EngagementStatus]
    assert isinstance(data["litigation_hold_active"], bool)


def assert_assembly(data: dict):
    _assert_common_fields(data, "Assembly")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["tag"], str) and data["tag"]
    assert data["assembly_type"] in [t.value for t in AssemblyType]
    assert data["design_u_factor"] > 0
    assert data["required_airtightness_lps_m2"] > 0
    assert data["review_status"] in [s.value for s in AssemblyReviewStatus]


def assert_design_review(data: dict):
    _assert_common_fields(data, "DesignReview")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["assembly_id"], str)
    assert isinstance(data["barrier_scope"], list) and data["barrier_scope"]
    for layer in data["barrier_scope"]:
        assert layer in [b.value for b in BarrierLayer]
    assert isinstance(data["drawing_count"], int) and data["drawing_count"] >= 1
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert "reviewer_id" in data
    assert "review_fee_cents" in data
    assert data["status"] in [s.value for s in DesignReviewStatus]


def assert_chamber_slot(data: dict):
    _assert_common_fields(data, "ChamberSlot")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["daily_rate_cents"], int) \
        and data["daily_rate_cents"] >= 1
    assert data["status"] in [s.value for s in ChamberSlotStatus]


def assert_mock_up(data: dict):
    _assert_common_fields(data, "MockUp")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["assembly_id"], str)
    assert isinstance(data["chamber_slot_id"], str)
    assert isinstance(data["specimen_count"], int) and data["specimen_count"] >= 1
    assert "air_leakage_lps_m2" in data
    assert "testing_fee_cents" in data
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in [s.value for s in MockUpStatus]


def assert_field_test(data: dict):
    _assert_common_fields(data, "FieldTest")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["assembly_id"], str)
    assert data["test_method"] in [m.value for m in TestMethod]
    assert isinstance(data["test_date"], str)
    assert isinstance(data["test_pressure_pa"], int)
    assert "measured_leakage_lps_m2" in data
    assert "performed_by" in data
    assert "certified_by" in data
    assert "result" in data
    if data.get("result") is not None:
        assert data["result"] in [r.value for r in FieldTestResult]
    assert data["execution_status"] in \
        [s.value for s in FieldTestExecutionStatus]
    assert data["diagnosis_status"] in \
        [s.value for s in FieldTestDiagnosisStatus]


def assert_survey(data: dict):
    _assert_common_fields(data, "Survey")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["assembly_id"], str)
    assert data["survey_type"] in [t.value for t in SurveyType]
    assert isinstance(data["survey_date"], str)
    assert isinstance(data["ambient_delta_t_c"], (int, float))
    assert isinstance(data["anomaly_count"], int) and data["anomaly_count"] >= 0
    assert data["status"] in [s.value for s in SurveyStatus]


def assert_anomaly(data: dict):
    _assert_common_fields(data, "Anomaly")
    assert isinstance(data["engagement_id"], str)
    assert "field_test_id" in data
    assert "survey_id" in data
    parents = [data.get("field_test_id"), data.get("survey_id")]
    assert sum(1 for p in parents if p is not None) == 1, \
        "exactly one of field_test_id / survey_id must be set"
    assert data["anomaly_type"] in [t.value for t in AnomalyType]
    assert data["severity"] in [s.value for s in AnomalySeverity]
    assert isinstance(data["description"], str)
    assert data["status"] in [s.value for s in AnomalyStatus]


def assert_remediation_plan(data: dict):
    _assert_common_fields(data, "RemediationPlan")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["anomaly_ids"], list) and data["anomaly_ids"]
    assert isinstance(data["spec_sections"], list) and data["spec_sections"]
    assert "estimated_cost_cents" in data
    assert "actual_cost_cents" in data
    assert "supersedes_plan_id" in data
    assert data["plan_status"] in [s.value for s in RemediationPlanStatus]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["anomaly_id"], str)
    assert isinstance(data["manufacturer_name"], str)
    assert isinstance(data["claimed_amount_cents"], int) \
        and data["claimed_amount_cents"] >= 1
    assert isinstance(data["recovered_amount_cents"], int)
    assert isinstance(data["filed_at"], str)
    assert isinstance(data["response_due_at"], str)
    assert data["claim_status"] in [s.value for s in WarrantyClaimStatus]


def assert_litigation_hold(data: dict):
    _assert_reduced_fields(data, "LitigationHold")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["matter_reference"], str)
    assert data["hold_status"] in [s.value for s in LitigationHoldStatus]


def assert_maintenance_visit(data: dict):
    _assert_common_fields(data, "MaintenanceVisit")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["visit_label"], str) and data["visit_label"]
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["buffer_days"], int) and data["buffer_days"] >= 0
    assert data["visit_status"] in [s.value for s in MaintenanceVisitStatus]


def assert_invoice(data: dict):
    _assert_reduced_fields(data, "Invoice")
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["labor_hours"], (int, float)) \
        and data["labor_hours"] >= 0
    assert isinstance(data["expense_cents"], int) and data["expense_cents"] >= 0
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["invoice_status"] in [s.value for s in InvoiceStatus]


def assert_engagement_invariants(data: dict):
    """Domain invariants that must hold after any operation (PRD 2.6/2.7)."""
    assert 0 <= data["risk_score"] <= 100
    assert data["recognized_fees_cents"] >= 0, \
        "provisional recognized fees are floored at 0"
    assert data["fee_headroom_cents"] == \
        data["fee_cap_cents"] - data["recognized_fees_cents"]
