"""Entity assertions and domain invariant checkers (WIOA PRD)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_local_area(data: dict):
    _assert_common(data)
    for f in ("ita_budget_total_cents", "ita_budget_available_cents",
              "ita_budget_obligated_cents", "ita_budget_expended_cents",
              "ita_individual_cap_cents", "supportive_annual_cap_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert_ita_pool_conserved(data)


def assert_ita_pool_conserved(data: dict):
    """PRD §2.7: available + obligated + expended == total, always."""
    total = (data["ita_budget_available_cents"] + data["ita_budget_obligated_cents"]
             + data["ita_budget_expended_cents"])
    assert total == data["ita_budget_total_cents"], (
        f"ITA pool not conserved: {total} != total {data['ita_budget_total_cents']}")
    assert data["ita_budget_available_cents"] >= 0
    assert data["ita_budget_obligated_cents"] >= 0
    assert data["ita_budget_expended_cents"] >= 0


def assert_participant(data: dict):
    _assert_common(data)
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "INELIGIBLE")
    assert data["enrollment_status"] in ("NOT_ENROLLED", "ENROLLED", "EXITED")
    assert data["priority_of_service"] in ("PRIORITY", "NON_PRIORITY")
    assert data["funding_stream"] in ("ADULT", "DISLOCATED_WORKER", "YOUTH")


def assert_supportive_pool_conserved(data: dict, annual_cap: int):
    """PRD §2.7: supportive available + obligated + expended == initialized annual cap."""
    total = (data["supportive_available_cents"] + data["supportive_obligated_cents"]
             + data["supportive_expended_cents"])
    assert total == annual_cap, (
        f"Supportive pool not conserved: {total} != cap {annual_cap}")


def assert_career_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "CLOSED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_training_provider(data: dict):
    _assert_common(data)
    assert data["etpl_status"] in ("APPLIED", "ELIGIBLE", "SUSPENDED")


def assert_training_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["credential_type"] in ("DEGREE", "CERTIFICATE", "LICENSE", "NONE")


def assert_voucher(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "OBLIGATED", "COMPLETED", "CANCELLED")
    assert isinstance(data["amount_obligated_cents"], int)
    assert isinstance(data["amount_expended_cents"], int)


def assert_disbursement(data: dict):
    """Append-only ledger record: id + created_at only (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_supportive_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "PAID", "VOIDED")
    assert data["service_type"] in ("MILEAGE", "CHILDCARE", "TOOLS", "OTHER")
    assert isinstance(data["computed_amount_cents"], int)


def assert_employer(data: dict):
    _assert_common(data)
    assert data["size"] in ("SMALL", "LARGE")


def assert_ojt_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETED", "TERMINATED")
    assert isinstance(data["amount_expended_cents"], int)


def assert_job_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "PLACED", "REJECTED")
