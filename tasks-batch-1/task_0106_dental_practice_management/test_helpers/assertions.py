"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates structural shape (ids, timestamps, enum domains)
against the PRD's field definitions. Append-only ClaimAttachment is checked to
NOT carry version/updated_at (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["balance_owed_cents"], int)


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["provider_type"] in ("DENTIST", "HYGIENIST")
    assert isinstance(data["npi"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_operatory(data: dict):
    _assert_common(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_insurance_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_name"], str)
    assert data["annual_maximum_cents"] > 0
    assert data["deductible_cents"] >= 0
    for pct in ("preventive_coinsurance_pct", "basic_coinsurance_pct", "major_coinsurance_pct"):
        assert 0 <= data[pct] <= 100


def assert_patient_coverage(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["insurance_plan_id"], str)
    assert isinstance(data["annual_benefit_used_cents"], int)
    assert isinstance(data["deductible_met_cents"], int)
    assert isinstance(data["annual_max_reached"], bool)
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_tooth_chart_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["provider_id"], str)
    assert 1 <= data["tooth_number"] <= 32
    assert data["chart_type"] in ("SURFACE", "PERIO")
    assert isinstance(data["finding"], str)


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["provider_id"], str)
    assert isinstance(data["total_fee_cents"], int)
    assert isinstance(data["estimated_patient_portion_cents"], int)
    assert data["status"] in ("DRAFT", "PROPOSED", "ACCEPTED", "COMPLETED", "CANCELLED")


def assert_treatment_plan_item(data: dict):
    _assert_common(data)
    assert isinstance(data["treatment_plan_id"], str)
    assert isinstance(data["cdt_code"], str)
    assert data["category"] in ("PREVENTIVE", "BASIC", "MAJOR")
    assert data["phase_number"] >= 1
    assert data["fee_cents"] > 0
    assert isinstance(data["requires_predetermination"], bool)
    assert isinstance(data["estimated_insurance_cents"], int)
    assert isinstance(data["estimated_patient_portion_cents"], int)
    assert data["status"] in ("PLANNED", "SCHEDULED", "COMPLETED", "CANCELLED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["provider_id"], str)
    assert isinstance(data["operatory_id"], str)
    assert data["appointment_type"] in ("PREVENTIVE", "OPERATIVE")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_predetermination(data: dict):
    _assert_common(data)
    assert isinstance(data["treatment_plan_item_id"], str)
    assert isinstance(data["patient_coverage_id"], str)
    assert isinstance(data["submitted_fee_cents"], int)
    assert data["status"] in (
        "PENDING", "APPROVED", "DENIED", "EXPIRED", "REQUIRES_REVALIDATION"
    )


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["treatment_plan_item_id"], str)
    assert isinstance(data["patient_coverage_id"], str)
    assert isinstance(data["billed_fee_cents"], int)
    assert isinstance(data["carrier_paid_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert data["submission_status"] in ("DRAFT", "SUBMITTED")
    assert data["adjudication_status"] in (
        "PENDING", "PAID", "PARTIALLY_PAID", "DENIED", "VOID"
    )


def assert_claim_attachment(data: dict):
    """ClaimAttachment is immutable (PRD §2.4): id + created_at only, no
    version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["attachment_type"] in ("XRAY", "PERIO_CHART", "NARRATIVE", "PHOTO")
    assert isinstance(data["document_ref"], str)
    assert "version" not in data, "ClaimAttachment must NOT carry a version field"
    assert "updated_at" not in data, "ClaimAttachment must NOT carry an updated_at field"


def assert_recare_recall(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert data["recall_type"] in ("PROPHY", "PERIO_MAINT", "EXAM")
    assert data["interval_months"] > 0
    assert isinstance(data["last_visit_date"], str)
    assert isinstance(data["next_due_date"], str)
    assert data["status"] in ("ACTIVE", "DUE")


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["claim_id"], str)
    assert data["principal_cents"] > 0
    assert 1 <= data["installment_count"] <= 60
    assert isinstance(data["installment_amount_cents"], int)
    assert isinstance(data["final_installment_cents"], int)
    assert isinstance(data["amount_posted_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "PAID_OFF", "DEFAULTED")


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_payment_plan_schedule_invariant(data: dict):
    """PRD §3.7: base*(count-1) + final == principal exactly; remaining ==
    principal - amount_posted."""
    base = data["installment_amount_cents"]
    count = data["installment_count"]
    final = data["final_installment_cents"]
    principal = data["principal_cents"]
    assert base * (count - 1) + final == principal, (
        f"schedule must sum to principal: {base}*{count - 1}+{final} != {principal}"
    )
    assert data["remaining_balance_cents"] == principal - data["amount_posted_cents"]


def assert_claim_responsibility_invariant(data: dict):
    """PRD §3.6/§3.8: patient_responsibility == billed_fee - carrier_paid."""
    assert (
        data["patient_responsibility_cents"]
        == data["billed_fee_cents"] - data["carrier_paid_cents"]
    ), "patient_responsibility must equal billed_fee - carrier_paid"
