"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["certification_status"] == "REGISTERED"
    assert isinstance(data["master_agreement_signed"], bool)


def assert_support_structure(data: dict):
    _assert_common(data)
    assert data["structure_type"] in ("EXISTING_UTILITY", "EXISTING_MUNICIPAL", "NEW_POLE")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["in_design_district"] in ("NONE", "STANDARD", "HISTORIC")
    assert isinstance(data["max_collocations"], int) and data["max_collocations"] >= 1
    assert_structure_slots(data)


def assert_structure_slots(data: dict):
    """Physical-slot conservation invariant (PRD Section 2.7)."""
    assert data["reserved_collocations"] >= 0
    assert data["active_collocations"] >= 0
    assert (
        data["available_collocations"]
        == data["max_collocations"] - data["reserved_collocations"] - data["active_collocations"]
    ), "available_collocations must equal max - reserved - active"
    assert (
        data["reserved_collocations"] + data["active_collocations"] + data["available_collocations"]
        == data["max_collocations"]
    ), "reserved + active + available must conserve max_collocations"


def assert_row_segment(data: dict):
    _assert_common(data, versioned=False)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["corridor_code"], str) and data["corridor_code"]
    assert isinstance(data["in_historic_district"], bool)


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "INCOMPLETE", "UNDER_REVIEW", "GRANTED",
        "PARTIALLY_GRANTED", "DENIED", "DEEMED_GRANTED", "WITHDRAWN",
        "UNDER_APPEAL", "APPEAL_GRANTED", "APPEAL_DENIED",
    )
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be a UUID"


def assert_node(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PROPOSED", "IN_REVIEW", "APPROVED", "REJECTED",
        "PERMITTED", "ACTIVATED", "DENIED", "WITHDRAWN",
    )
    assert data["facility_type"] in ("COLLOCATION", "NEW_POLE")
    assert data["design_review_status"] in ("PENDING", "PASS", "FAIL")
    assert data["aesthetic_review_status"] in ("PENDING", "PASS", "FAIL", "WAIVED")


def assert_node_review(data: dict):
    _assert_common(data, versioned=False)
    assert data["review_type"] in ("DESIGN_STANDARD", "AESTHETIC_HISTORIC")
    assert data["outcome"] in ("PASS", "FAIL")


def assert_inspection(data: dict):
    _assert_common(data, versioned=False)
    assert data["outcome"] in ("PASS", "FAIL")


def assert_fee_invoice(data: dict):
    _assert_common(data)
    assert data["fee_variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("OPEN", "PAID", "REFUNDED")
    assert_invoice_ledger(data)


def assert_invoice_ledger(data: dict):
    """Money-conservation invariant (PRD Section 3.7)."""
    assert (
        data["outstanding_amount_cents"]
        == data["assessed_amount_cents"] - data["paid_amount_cents"] + data["refunded_amount_cents"]
    ), "outstanding must equal assessed - paid + refunded"


def assert_payment(data: dict):
    _assert_common(data, versioned=False)
    assert data["payment_type"] in ("PAYMENT", "REFUND")
    assert data["status"] == "CAPTURED"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_recurring_rental(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "VOID")


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "OVERTURNED", "UPHELD")
