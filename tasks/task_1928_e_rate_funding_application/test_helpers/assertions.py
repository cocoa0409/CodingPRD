"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AppealStatus, BidStatus, Category, ContractStatus, DocumentStatus,
    EntityType, InvoiceMethod, InvoiceStatus, LineDenialReason, LineStatus,
    PostingStatus, RequestStatus, ServiceType, SubjectType, SubstitutionStatus,
    UrbanRural, UserFunction,
)


def _assert_primary_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_funding_cycle(data: dict):
    _assert_primary_fields(data, "FundingCycle")
    assert isinstance(data["label"], str) and data["label"]
    for field in ("window_open_date", "window_close_date", "service_delivery_deadline"):
        assert isinstance(data[field], str) and len(data[field]) == 10, (
            f"FundingCycle.{field} must be a YYYY-MM-DD date"
        )


def assert_eligible_service(data: dict):
    _assert_primary_fields(data, "EligibleService")
    assert is_valid_uuid(data["funding_cycle_id"])
    assert isinstance(data["service_description"], str) and data["service_description"]
    assert data["category"] in [c.value for c in Category]
    assert data["service_type"] in [t.value for t in ServiceType]


def assert_applicant(data: dict):
    _assert_primary_fields(data, "Applicant")
    assert isinstance(data["name"], str) and data["name"]
    assert data["entity_type"] in [e.value for e in EntityType]
    assert data["urban_rural"] in [u.value for u in UrbanRural]
    if data["entity_type"] == EntityType.SCHOOL.value:
        assert isinstance(data["student_count"], int) and data["student_count"] > 0
    if data["entity_type"] == EntityType.LIBRARY.value:
        assert isinstance(data["square_feet"], int) and data["square_feet"] > 0
    assert isinstance(data["audit_hold_active"], bool)


def assert_nslp_snapshot(data: dict):
    """Append-only snapshot: only id + created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "NSLPSnapshot.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "NSLPSnapshot.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "snapshots are append-only: updated_at must be absent"
    assert "version" not in data, "snapshots are append-only: version must be absent"
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["funding_cycle_id"])
    assert isinstance(data["total_students"], int) and data["total_students"] > 0
    free = data["free_lunch_eligible_students"]
    assert isinstance(free, int) and 0 <= free <= data["total_students"]
    assert isinstance(data["cep_participating"], bool)
    assert isinstance(data["effective_share_pct"], (int, float))


def assert_applicant_user(data: dict):
    _assert_primary_fields(data, "ApplicantUser")
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["function"] in [f.value for f in UserFunction]


def assert_service_provider(data: dict):
    _assert_primary_fields(data, "ServiceProvider")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["spin"], str) and data["spin"]


def assert_procurement_posting(data: dict):
    _assert_primary_fields(data, "ProcurementPosting")
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["funding_cycle_id"])
    assert data["category"] in [c.value for c in Category]
    assert isinstance(data["price_weight_pct"], int) and 0 < data["price_weight_pct"] <= 100
    assert isinstance(data["other_factor_weights"], list)
    assert data["status"] in [s.value for s in PostingStatus]


def assert_bid(data: dict):
    _assert_primary_fields(data, "Bid")
    assert is_valid_uuid(data["posting_id"])
    assert is_valid_uuid(data["service_provider_id"])
    assert isinstance(data["eligible_price_cents"], int) and data["eligible_price_cents"] > 0
    assert isinstance(data["factor_scores"], list)
    assert data["status"] in [s.value for s in BidStatus]


def assert_contract(data: dict):
    _assert_primary_fields(data, "Contract")
    for field in ("applicant_id", "service_provider_id", "posting_id", "winning_bid_id"):
        assert is_valid_uuid(data[field]), f"Contract.{field} must be a valid UUID"
    assert data["category"] in [c.value for c in Category]
    assert isinstance(data["total_eligible_cents"], int) and data["total_eligible_cents"] > 0
    assert data["service_end_date"] >= data["service_start_date"]
    assert data["status"] in [s.value for s in ContractStatus]


def assert_funding_request(data: dict):
    _assert_primary_fields(data, "FundingRequest")
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["funding_cycle_id"])
    assert data["status"] in [s.value for s in RequestStatus]
    assert isinstance(data["services_started"], bool)
    assert isinstance(data["pia_reviewer_user_ids"], list)


def assert_funding_request_line(data: dict):
    _assert_primary_fields(data, "FundingRequestLine")
    assert is_valid_uuid(data["funding_request_id"])
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["eligible_service_id"])
    assert data["category"] in [c.value for c in Category]
    assert isinstance(data["requested_pre_discount_cents"], int)
    assert data["requested_pre_discount_cents"] > 0
    assert data["status"] in [s.value for s in LineStatus]
    if data.get("denial_reason") is not None:
        assert data["denial_reason"] in [r.value for r in LineDenialReason]


def assert_invoice_submission(data: dict):
    _assert_primary_fields(data, "InvoiceSubmission")
    assert is_valid_uuid(data["frn_line_id"])
    assert data["method"] in [m.value for m in InvoiceMethod]
    assert isinstance(data["gross_invoiced_cents"], int) and data["gross_invoiced_cents"] > 0
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_service_substitution(data: dict):
    _assert_primary_fields(data, "ServiceSubstitution")
    assert is_valid_uuid(data["frn_line_id"])
    assert is_valid_uuid(data["from_eligible_service_id"])
    assert is_valid_uuid(data["to_eligible_service_id"])
    assert data["status"] in [s.value for s in SubstitutionStatus]


def assert_appeal(data: dict):
    _assert_primary_fields(data, "Appeal")
    assert is_valid_uuid(data["funding_request_id"])
    assert isinstance(data["grounds"], str)
    assert isinstance(data["filed_date"], str) and len(data["filed_date"]) == 10
    assert data["status"] in [s.value for s in AppealStatus]


def assert_retained_document(data: dict):
    _assert_primary_fields(data, "RetainedDocument")
    assert data["subject_type"] in [t.value for t in SubjectType]
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert is_valid_uuid(data["funding_cycle_id"])
    assert isinstance(data["document_kind"], str) and data["document_kind"]
    assert isinstance(data["retained_until_date"], str) and len(data["retained_until_date"]) == 10
    assert data["status"] in [s.value for s in DocumentStatus]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_line_ledger_conserved(line: dict):
    """PRD §3.6: a line's committed share is exactly conserved between the
    paid and remaining portions of its reimbursement ledger."""
    total = line["committed_share_cents"]
    assert line["reimbursed_cents"] + line["remaining_reimbursable_cents"] == total, (
        f"line ledger drifted: reimbursed {line['reimbursed_cents']} + remaining "
        f"{line['remaining_reimbursable_cents']} != committed_share {total}"
    )


def assert_c2_budget_invariants(summary: dict):
    """PRD §3.2: the server maintains the invariant that the Category Two cap
    always equals committed plus available."""
    assert summary["c2_cap_cents"] >= 0
    assert summary["c2_committed_cents"] >= 0
    assert summary["c2_available_cents"] >= 0
    assert (
        summary["c2_cap_cents"]
        == summary["c2_committed_cents"] + summary["c2_available_cents"]
    ), (
        f"budget invariant broken: cap {summary['c2_cap_cents']} != committed "
        f"{summary['c2_committed_cents']} + available {summary['c2_available_cents']}"
    )
