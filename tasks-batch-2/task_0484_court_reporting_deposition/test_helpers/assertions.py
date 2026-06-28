"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["caption"], str) and len(data["caption"]) > 0
    assert isinstance(data["docket_number"], str) and len(data["docket_number"]) > 0
    assert data["jurisdiction"] in ["FEDERAL", "STATE_CA", "STATE_NY", "STATE_TX"]
    assert is_valid_uuid(data.get("noticing_attorney_id", ""))


def assert_attorney(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["firm_name"], str) and len(data["firm_name"]) > 0
    assert data["bar_state"] in ["CA", "NY", "TX", "FED"]
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_resource(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["kind"] in ["REPORTER", "VIDEOGRAPHER", "INTERPRETER"]
    assert isinstance(data["hourly_appearance_cents"], int)
    assert data["hourly_appearance_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["deponent_name"], str) and len(data["deponent_name"]) > 0
    assert data["status"] in ["NOTICED", "CONFIRMED", "IN_SESSION", "ADJOURNED", "CANCELLED"]
    assert data["staffing_posture"] in ["UNSTAFFED", "PARTIAL", "READY"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("resource_id", ""))
    assert data["role"] in ["REPORTER", "VIDEOGRAPHER", "INTERPRETER"]
    assert data["status"] in ["ACTIVE", "RELEASED", "COMPLETED"]
    assert isinstance(data["appearance_fee_cents"], int)
    assert data["appearance_fee_cents"] >= 0


def assert_realtime_stream(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["status"] in ["STARTING", "LIVE", "STOPPED"]


def assert_transcript_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("ordering_attorney_id", ""))
    assert data["turnaround_tier"] in [
        "STANDARD", "EXPEDITE_14", "EXPEDITE_7", "EXPEDITE_3", "DAILY",
    ]
    assert data["status"] in [
        "ORDERED", "ROUGH_DELIVERED", "CERTIFIED", "READ_SIGN_OPEN",
        "ERRATA_FILED", "SIGNED", "DELIVERED", "CANCELLED",
    ]
    assert isinstance(data["errata_round"], int)


def assert_exhibit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("transcript_order_id", ""))
    assert isinstance(data["marked_label"], str) and len(data["marked_label"]) > 0
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["confidential"], bool)


def assert_errata(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("transcript_order_id", ""))
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert isinstance(data["corrections"], list) and len(data["corrections"]) >= 1
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("transcript_order_id", ""))
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    for f in (
        "appearance_subtotal_cents", "page_subtotal_cents",
        "exhibit_subtotal_cents", "total_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer cent value"


def assert_invoice_reconciles(data: dict):
    """Invoice total reconciles to the plain sum of its three subtotals (PRD §3.14)."""
    expected = (
        data["appearance_subtotal_cents"]
        + data["page_subtotal_cents"]
        + data["exhibit_subtotal_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} must equal the sum of subtotals {expected}"
    )
