"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the common-record shape and field domains the PRD
guarantees on a response. The fee-schedule assertion deliberately omits version /
updated_at, which the PRD says must not be exposed on fee-schedule responses.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["mailing_email"], str) and data["mailing_email"]
    assert data["repeat_tier"] in ("FIRST", "REPEAT", "CHRONIC")
    assert isinstance(data["prior_violation_count"], int)
    assert data["prior_violation_count"] >= 0


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert isinstance(data["street_address"], str)
    assert data["occupancy"] in ("OCCUPIED", "VACANT")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_fee_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "fee schedule id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # PRD §2.4: fee schedules must NOT expose updated_at or version.
    assert "version" not in data, "fee schedule must not expose version"
    assert "updated_at" not in data, "fee schedule must not expose updated_at"
    assert data["violation_class"] in ("MINOR", "MAJOR", "HAZARD")
    assert isinstance(data["base_fine_cents"], int)
    assert isinstance(data["daily_accrual_cents"], int)
    assert isinstance(data["max_total_cents"], int)
    assert isinstance(data["cure_days"], int)


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert data["posture"] in ("INTAKE", "ACTIVE", "ABATEMENT", "LIENED", "CLOSED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["payments_applied_cents"], int)


def assert_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["reporter_kind"] in ("RESIDENT", "ANONYMOUS", "OFFICER_OBSERVED")
    assert data["status"] in ("RECEIVED", "TRIAGED", "DISMISSED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["kind"] in ("INITIAL", "REINSPECTION")
    assert data["outcome"] in (
        "PENDING", "VIOLATION_FOUND", "NO_VIOLATION", "COMPLIANT", "NON_COMPLIANT"
    )


def assert_notice(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["source_inspection_id"], str)
    assert data["violation_class"] in ("MINOR", "MAJOR", "HAZARD")
    assert data["status"] in (
        "DRAFT", "ISSUED", "COMPLIED", "OVERDUE", "CONTESTED", "UPHELD",
        "DISMISSED", "SETTLED",
    )
    assert isinstance(data["fine_total_cents"], int)
    assert isinstance(data["days_overdue"], int)
    assert data["days_overdue"] >= 0, "days_overdue floors at 0"


def assert_reinspection(data: dict):
    _assert_common(data)
    assert isinstance(data["notice_id"], str)
    assert data["result"] in ("SCHEDULED", "PASSED", "FAILED")


def assert_fine(data: dict):
    _assert_common(data)
    assert isinstance(data["notice_id"], str)
    assert data["source_kind"] in ("CITATION", "ABATEMENT_COST")
    assert isinstance(data["assessed_cents"], int)
    assert data["settlement_status"] in ("OPEN", "SETTLED", "WAIVED")


def assert_hearing(data: dict):
    _assert_common(data)
    assert isinstance(data["notice_id"], str)
    assert data["status"] in ("SCHEDULED", "HELD_UPHELD", "HELD_DISMISSED", "CONTINUED")
    assert isinstance(data["continuance_count"], int)


def assert_abatement_order(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["action_kind"] in ("BOARD_UP", "DEMOLITION")
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ("ORDERED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_lien(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("PENDING", "RECORDED", "RELEASED", "FORECLOSED")


def assert_lien_total_consistent(data: dict):
    """total_cents == principal_cents + admin_fee_cents (PRD §3.12)."""
    assert data["total_cents"] == data["principal_cents"] + data["admin_fee_cents"], (
        f"total {data['total_cents']} != principal {data['principal_cents']} "
        f"+ admin_fee {data['admin_fee_cents']}"
    )
