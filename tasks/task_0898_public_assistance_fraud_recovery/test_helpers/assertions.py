"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_subject(data: dict):
    _assert_common(data)
    assert data["primary_program"] in ("SNAP", "TANF", "MEDICAID")
    assert isinstance(data["prior_ipv_count"], int)
    assert data["disqualification_status"] in ("NONE", "DISQUALIFIED", "PERMANENTLY_DISQUALIFIED")


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "ACCEPTED", "REJECTED", "CONVERTED")
    assert isinstance(data["priority_score"], int)


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "INVESTIGATION", "PENDING_REVIEW", "SUBSTANTIATED", "UNSUBSTANTIATED",
    )


def assert_evidence(data: dict):
    _assert_append_only(data)
    assert data["kind"] in ("DOCUMENT", "INTERVIEW", "DATA_MATCH", "SURVEILLANCE")


def assert_overpayment(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ("IPV", "IHE", "AE")
    assert data["status"] in (
        "DRAFT", "CALCULATED", "ESTABLISHED", "DEMANDED",
        "IN_RECOVERY", "SATISFIED", "WRITTEN_OFF", "TERMINATED",
    )
    for field in (
        "provisional_amount_cents", "final_amount_cents", "total_adjustments_cents",
        "accrued_interest_cents", "outstanding_principal_cents", "outstanding_interest_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_overpayment_month(data: dict):
    _assert_append_only(data)
    assert isinstance(data["over_issuance_reported_cents"], int)
    assert isinstance(data["over_issuance_verified_cents"], int)


def assert_disqualification(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ADH_REFERRED", "IMPOSED", "DECLINED", "RESCINDED")


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "HELD", "DECIDED_IPV", "DECIDED_NO_IPV", "DISMISSED",
    )


def assert_recovery_plan(data: dict):
    _assert_common(data)
    assert data["method"] in ("RECOUPMENT", "OFFSET", "COLLECTION")
    assert data["status"] in ("ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED")


def assert_recovery_transaction(data: dict):
    _assert_common(data)
    assert data["method"] in ("PAYMENT", "OFFSET", "RECOUPMENT")
    assert data["status"] in ("POSTED", "VOIDED")
    assert isinstance(data["applied_to_interest_cents"], int)
    assert isinstance(data["applied_to_principal_cents"], int)
