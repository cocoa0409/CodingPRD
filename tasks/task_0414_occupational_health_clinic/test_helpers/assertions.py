"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_audit(data: dict):
    """id (UUID, no type prefix), created_at, updated_at, integer version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at its initial value and increments"


def assert_employer(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["account_status"] in ["PROSPECT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["dot_regulated"], bool)
    assert isinstance(data["mro_user_id"], str)
    assert isinstance(data["net_terms_days"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "outstanding balance is never negative"


def assert_protocol(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["employer_id"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert isinstance(data["panels"], list)


def assert_worker(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["job_category"], str)
    assert data["hire_status"] in ["CANDIDATE", "CLEARED", "DISQUALIFIED"]


def assert_encounter(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["worker_id"], str)
    assert data["encounter_type"] in ["PHYSICAL", "DRUG_SCREEN", "INJURY", "SURVEILLANCE"]
    assert data["status"] in [
        "SCHEDULED", "IN_PROGRESS", "PENDING_RESULTS", "COMPLETED", "CANCELLED", "VOIDED",
    ]
    assert isinstance(data["billable_amount_cents"], int)
    assert data["billable_amount_cents"] >= 0
    assert isinstance(data["is_billed"], bool)


def assert_drug_screen(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["encounter_id"], str)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["is_dot"], bool)
    assert isinstance(data["specimen_seal_intact"], bool)
    assert data["status"] in [
        "AWAITING_COLLECTION", "COLLECTED", "AT_LAB", "LAB_REPORTED",
        "MRO_REVIEW", "VERIFIED", "RECOLLECT_ORDERED", "CANCELLED",
    ]
    assert isinstance(data["recollection_count"], int)
    assert 0 <= data["recollection_count"] <= 2


def assert_injury_case(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["encounter_id"], str)
    assert isinstance(data["employer_id"], str)
    assert data["treatment_level"] in [
        "FIRST_AID", "MEDICAL_TREATMENT", "LOST_TIME", "RESTRICTED_DUTY", "FATALITY",
    ]
    assert isinstance(data["days_away"], int) and data["days_away"] >= 0
    assert isinstance(data["days_restricted"], int) and data["days_restricted"] >= 0
    assert isinstance(data["is_osha_recordable"], bool)
    assert data["osha_column"] in [
        "NOT_RECORDABLE", "DEATH", "DAYS_AWAY", "RESTRICTED_TRANSFER", "OTHER_RECORDABLE",
    ]
    assert data["status"] in ["OPEN", "RTW_PENDING", "CLOSED"]


def assert_work_status(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["injury_case_id"], str)
    assert data["disposition"] in ["FULL_DUTY", "MODIFIED_DUTY", "OFF_WORK"]
    assert isinstance(data["superseded"], bool)


def assert_surveillance_exam(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["encounter_id"], str)
    assert data["exam_kind"] in ["AUDIOMETRIC", "RESPIRATOR_FIT"]
    assert data["status"] in ["SCHEDULED", "RECORDED", "FINALIZED", "CANCELLED"]


def assert_clearance(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["encounter_id"], str)
    assert data["determination"] in ["FIT", "FIT_WITH_RESTRICTIONS", "NOT_FIT"]
    assert data["status"] in ["ISSUED", "RESCINDED"]


def assert_invoice(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["line_item_encounter_ids"], list)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert data["status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOIDED",
    ]


def assert_invoice_totals(data: dict):
    """total_cents == subtotal_cents - discount_cents and is never negative."""
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], (
        f"total {data['total_cents']} must equal subtotal {data['subtotal_cents']} "
        f"minus discount {data['discount_cents']}"
    )
    assert data["total_cents"] >= 0


def assert_custody_event(data: dict):
    """Append-only record: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["drug_screen_id"], str)
    assert data["step"] in ["COLLECT", "SEAL", "SHIP", "LAB_RECEIVE", "LAB_REPORT", "MRO_RECEIVE"]
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert "updated_at" not in data, "CustodyEvent is append-only and carries no updated_at"
    assert "version" not in data, "CustodyEvent is append-only and carries no version"
