"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract.
Append-only entities (Photo, ApplicationStatusEvent) must NOT expose version /
updated_at, so those assertions explicitly forbid those keys.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

APPLICATION_STATUSES = [
    "DRAFT", "SUBMITTED", "IN_VERIFICATION", "REVIEW_HOLD", "ADJUDICATING",
    "APPROVED", "ISSUED", "REJECTED", "WITHDRAWN",
]
NAME_CHANGE_STATUSES = ["NONE", "PENDING_EVIDENCE", "EVIDENCE_VERIFIED", "APPROVED", "DENIED"]
DOC_VERIFICATION_STATUSES = ["PENDING", "ACCEPTED", "REJECTED"]
PHOTO_RESULTS = ["PENDING", "PASS", "FAIL"]
FEE_STATUSES = ["UNPAID", "PAID", "REFUNDED"]
APPOINTMENT_STATUSES = ["BOOKED", "COMPLETED", "CANCELLED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not expose a version field"
    assert "updated_at" not in data, "append-only entity must not expose an updated_at field"


def assert_applicant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_legal_name"], str) and len(data["full_legal_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["total_fees_paid_cents"], int)
    assert data["total_fees_paid_cents"] >= 0
    score = data["verification_risk_score"]
    assert isinstance(score, (int, float))
    assert 0 <= score <= 100


def assert_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in APPLICATION_STATUSES, f"unexpected status {data['status']!r}"
    assert data["name_change_status"] in NAME_CHANGE_STATUSES
    assert data["application_type"] in ["NEW", "RENEWAL", "MINOR"]
    assert data["product_type"] in ["BOOK", "CARD", "BOOK_AND_CARD"]
    assert data["service_level"] in ["ROUTINE", "EXPEDITE"]
    assert isinstance(data["applicant_is_minor"], bool)
    assert isinstance(data["requires_execution"], bool)
    assert isinstance(data["urgent_travel"], bool)


def assert_supporting_document(data: dict):
    _assert_common_fields(data)
    assert data["doc_category"] in ["IDENTITY", "CITIZENSHIP", "GUARDIAN_CONSENT", "NAME_CHANGE_EVIDENCE"]
    assert data["verification_status"] in DOC_VERIFICATION_STATUSES
    assert 0 <= data["declared_quality"] <= 100


def assert_photo(data: dict):
    _assert_append_only_fields(data)
    assert data["validation_result"] in PHOTO_RESULTS
    assert isinstance(data["failure_reasons"], list)


def assert_fee_assessment(data: dict):
    _assert_common_fields(data)
    assert data["payment_status"] in FEE_STATUSES
    for k in ("base_fee_cents", "execution_fee_cents", "expedite_fee_cents",
              "urgent_surcharge_cents", "one_day_delivery_cents", "total_due_cents",
              "amount_paid_cents"):
        assert isinstance(data[k], int), f"{k} must be integer cents"
    assert_fee_total_consistent(data)


def assert_fee_total_consistent(data: dict):
    """total_due_cents is the exact integer sum of its five components (PRD 3.5)."""
    expected = (
        data["base_fee_cents"]
        + data["execution_fee_cents"]
        + data["expedite_fee_cents"]
        + data["urgent_surcharge_cents"]
        + data["one_day_delivery_cents"]
    )
    assert data["total_due_cents"] == expected, (
        f"total_due_cents {data['total_due_cents']} != sum of components {expected}"
    )


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in APPOINTMENT_STATUSES
    assert data["resource_kind"] in ["ACCEPTANCE_FACILITY", "URGENT_TRAVEL_COUNTER"]


def assert_adjudication_decision(data: dict):
    _assert_common_fields(data)
    assert data["decision"] in ["APPROVE", "REJECT", "RETURN_FOR_REVIEW"]


def assert_status_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["to_status"], str)
