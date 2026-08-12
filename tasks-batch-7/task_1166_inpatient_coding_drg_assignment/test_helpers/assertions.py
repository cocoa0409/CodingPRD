"""Entity assertions and domain invariant checkers (PRD-driven)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    """System-managed fields every resource carries (PRD: common properties)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_patient_account(data: dict):
    _assert_common(data, "PatientAccount")
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert is_iso8601_timestamp(data["admit_at"])
    assert data["patient_class"] in ("INPATIENT", "OBSERVATION")
    assert data["financial_class"] in ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")
    assert isinstance(data["total_charges_cents"], int)
    assert data["total_charges_cents"] >= 0
    assert data["status"] in ("ADMITTED", "DISCHARGED")
    assert isinstance(data["dnfb_flag"], bool)
    if data["status"] == "ADMITTED":
        assert data.get("discharge_at") is None
        assert data.get("discharge_disposition") is None
    else:
        assert is_iso8601_timestamp(data["discharge_at"])
        assert data["discharge_disposition"] in ("HOME", "SNF", "REHAB", "EXPIRED", "AMA")
    if data["dnfb_flag"]:
        assert is_iso8601_timestamp(data["dnfb_flagged_at"])
    else:
        assert data.get("dnfb_flagged_at") is None


def assert_chart(data: dict):
    _assert_common(data, "Chart")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["acuity"] in ("MEDICAL_LOW", "MEDICAL_HIGH", "SURGICAL")
    assert data["status"] in (
        "OPEN",
        "READY_FOR_CODING",
        "IN_CODING",
        "SUBMITTED",
        "CODED",
    )
    assert isinstance(data["open_deficiency_count"], int)
    assert data["open_deficiency_count"] >= 0


def assert_deficiency(data: dict):
    _assert_common(data, "ChartDeficiency")
    assert is_valid_uuid(data.get("chart_id", ""))
    assert data["type"] in (
        "MISSING_H_AND_P",
        "MISSING_DISCHARGE_SUMMARY",
        "MISSING_SIGNATURE",
        "MISSING_OP_REPORT",
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("OPEN", "RESOLVED")
    if data["status"] == "RESOLVED":
        assert is_iso8601_timestamp(data["resolved_at"])
    else:
        assert data.get("resolved_at") is None


def assert_diagnosis_line(data: dict):
    _assert_common(data, "DiagnosisLine")
    assert is_valid_uuid(data.get("chart_id", ""))
    assert isinstance(data["icd_code"], str) and len(data["icd_code"]) > 0
    assert data["poa"] in ("Y", "N", "U", "W", "EXEMPT")
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["is_principal"], bool)
    assert data["cc_level"] in ("NONE", "CC", "MCC")
    assert isinstance(data["is_manifestation"], bool)
    assert data["status"] in ("ACTIVE", "VOID")


def assert_procedure_line(data: dict):
    _assert_common(data, "ProcedureLine")
    assert is_valid_uuid(data.get("chart_id", ""))
    assert isinstance(data["pcs_code"], str) and len(data["pcs_code"]) > 0
    assert isinstance(data["is_or"], bool)
    assert is_iso8601_timestamp(data["performed_at"])


def assert_coder(data: dict):
    _assert_common(data, "Coder")
    assert isinstance(data["employee_no"], str) and len(data["employee_no"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential"] in ("CCA", "CCS", "RHIT", "RHIA")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["workload_units"], int)
    assert data["workload_units"] >= 0
    assert isinstance(data["accepted_count"], int)
    assert data["accepted_count"] >= 0
    assert isinstance(data["accepted_weighted_units"], (int, float))
    assert isinstance(data["productivity_units_per_day"], (int, float))
    assert data["productivity_units_per_day"] >= 0
    if data.get("accuracy_running") is not None:
        assert isinstance(data["accuracy_running"], (int, float))
    assert isinstance(data["credential_review_required"], bool)


def assert_assignment(data: dict):
    _assert_common(data, "CodingAssignment")
    assert is_valid_uuid(data.get("chart_id", ""))
    assert data["status"] in (
        "QUEUED",
        "ASSIGNED",
        "IN_PROGRESS",
        "SUBMITTED",
        "RETURNED",
        "ACCEPTED",
    )
    assert isinstance(data["priority_score"], int)
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["returned_count"], int)
    assert data["returned_count"] >= 0
    if data["status"] in ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "RETURNED", "ACCEPTED"):
        assert is_valid_uuid(data.get("coder_id", ""))
        assert is_iso8601_timestamp(data["assigned_at"])


def assert_coded_case(data: dict):
    _assert_common(data, "CodedCase")
    assert is_valid_uuid(data.get("chart_id", ""))
    assert is_valid_uuid(data.get("principal_dx_id", ""))
    assert data["grouper_variant"] in ("MS_DRG", "AP_DRG")
    assert data["base_partition"] in ("SURGICAL", "MEDICAL")
    assert isinstance(data["relative_weight"], (int, float))
    assert data["relative_weight"] > 0
    assert isinstance(data["expected_reimbursement_cents"], int)
    assert data["status"] in ("GROUPED", "LOCKED")


def assert_bill(data: dict):
    _assert_common(data, "Bill")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["status"] in (
        "DRAFT",
        "READY",
        "FINAL_BILLED",
        "PAID",
        "POST_PAYMENT_REVIEW",
        "REBILL_REQUIRED",
        "REBILLED",
    )
    assert isinstance(data["expected_reimbursement_cents"], int)


def assert_dnfb_sweep(data: dict):
    _assert_common(data, "DnfbSweep")
    assert isinstance(data["threshold_days"], int)
    assert is_iso8601_timestamp(data["as_of"])
    assert isinstance(data["flagged_count"], int)
    assert data["flagged_count"] >= 0
    assert isinstance(data["flagged_account_ids"], list)
    assert isinstance(data["total_outstanding_cents"], int)


def assert_audit(data: dict):
    _assert_common(data, "CodingAudit")
    assert is_valid_uuid(data.get("auditor_id", ""))
    assert is_valid_uuid(data.get("subject_coder_id", ""))
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    assert isinstance(data["sampled_case_ids"], list)
    assert data["status"] in ("IN_REVIEW", "COMPLETED")
    assert isinstance(data["applied_findings_count"], int)


def assert_finding(data: dict):
    _assert_common(data, "AuditFinding")
    assert is_valid_uuid(data.get("audit_id", ""))
    assert is_valid_uuid(data.get("coded_case_id", ""))
    assert data["finding_type"] in (
        "PRINCIPAL_RESEQUENCE",
        "POA_CORRECTION",
        "CC_MCC_ADDED",
        "CC_MCC_REMOVED",
        "PROCEDURE_ADDED",
    )
    assert isinstance(data["delta_reimbursement_cents"], int)
    assert data["status"] in ("OPEN", "APPLIED", "DISMISSED")


def assert_review(data: dict):
    _assert_common(data, "PostPaymentReview")
    assert is_valid_uuid(data.get("bill_id", ""))
    assert isinstance(data["payer_ref"], str) and len(data["payer_ref"]) > 0
    assert isinstance(data["claimed_delta_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED_REBILL", "CLOSED_NO_CHANGE")


def assert_rebill_request(data: dict):
    _assert_common(data, "RebillRequest")
    assert is_valid_uuid(data.get("review_id", ""))
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["requested_by"], str) and len(data["requested_by"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "CANCELLED")


def assert_coder_productivity_invariants(data: dict):
    """Coder derived-field invariants (PRD: fetching a coder reports the derived profile).

    productivity_units_per_day == round_half_up(accepted_weighted_units / 30, 2).
    """
    expected = round(data["accepted_weighted_units"] / 30 + 1e-12, 2)
    assert data["productivity_units_per_day"] == expected, (
        f"productivity_units_per_day {data['productivity_units_per_day']} != "
        f"accepted_weighted_units/30 == {expected}"
    )


def assert_bill_money_invariants(data: dict):
    """Bill money invariants once a bill is FINAL_BILLED or beyond."""
    if data["status"] in (
        "FINAL_BILLED",
        "PAID",
        "POST_PAYMENT_REVIEW",
        "REBILL_REQUIRED",
        "REBILLED",
    ):
        assert data["billed_amount_cents"] is not None
    if data["status"] in ("PAID", "POST_PAYMENT_REVIEW", "REBILL_REQUIRED", "REBILLED"):
        assert data["net_receivable_cents"] is not None
