"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_CLAIM_STATUSES = [
    "INTAKE", "ASSESSING", "ESTIMATING", "NEGOTIATING", "APPROVED", "AUTHORIZED",
    "IN_PROGRESS", "ON_HOLD", "COMPLETE", "INVOICED", "CLOSED", "DENIED", "WITHDRAWN",
]
_ESTIMATE_STATUSES = [
    "DRAFT", "SUBMITTED", "COUNTERED", "REVISED", "APPROVED", "LOCKED", "DENIED",
]
_LINE_STATUSES = ["PENDING", "DISPUTED", "AGREED", "REMOVED"]
_INSPECTION_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELED"]
_SUPPLEMENT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED"]
_ROUND_STATUSES = ["OPEN", "RESOLVED", "EXPIRED"]
_DISPOSITION_STATUSES = ["PENDING", "ACCEPTED", "REJECTED"]
_CODE_UPGRADE_STATUSES = ["IDENTIFIED", "APPROVED", "DENIED", "WITHDRAWN"]
_WA_STATUSES = ["DRAFT", "SIGNED", "VOIDED"]
_INVOICE_STATUSES = ["DRAFT", "ISSUED", "SETTLED", "VOIDED"]
_PAYMENT_STATUSES = ["REQUESTED", "APPROVED", "ISSUED", "CLEARED", "RETURNED", "VOIDED"]
_PAYMENT_TYPES = ["ACV_ADVANCE", "DEPRECIATION_RECOVERY", "DEDUCTIBLE", "CUSTOMER_BALANCE"]
_PAYMENT_DIRECTIONS = ["CARRIER_TO_CONTRACTOR", "CUSTOMER_TO_CONTRACTOR"]
_POSTURES = ["UNPAID", "ADVANCE_PAID", "DEPRECIATION_PENDING", "PAID_IN_FULL"]
_PHOTO_TAGS = [
    "LOSS_OVERVIEW", "AREA", "MOISTURE_PROOF", "SUPPLEMENT_EVIDENCE", "COMPLETION",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tax_rate"], (int, float))


def assert_price_list_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert data["kind"] in ["MATERIAL", "LABOR", "EQUIPMENT"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["coverage_a_limit_cents"], int)
    assert data["deductible_type"] in ["FLAT", "PERCENT_OF_COVERAGE_A"]
    assert isinstance(data["ordinance_limit_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in _CLAIM_STATUSES
    assert data["cause_of_loss"] in ["WATER", "FIRE", "WIND", "MOLD", "HAIL"]
    assert isinstance(data["deductible_cents"], int)
    assert data["payment_posture"] in _POSTURES


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in _INSPECTION_STATUSES
    assert data["type"] in ["INITIAL", "VERIFICATION"]


def assert_moisture_reading(data: dict):
    _assert_common(data)
    assert isinstance(data["reading_value"], (int, float))
    assert isinstance(data["dry_standard"], (int, float))
    assert isinstance(data["is_wet"], bool)


def assert_photo(data: dict):
    _assert_common(data)
    assert data["tag"] in _PHOTO_TAGS
    parents = [p for p in (data.get("inspection_id"), data.get("supplement_id")) if p]
    assert len(parents) == 1, "exactly one of inspection_id / supplement_id must be set"


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["status"] in _ESTIMATE_STATUSES
    assert data["type"] in ["INITIAL", "SUPPLEMENT"]
    assert isinstance(data["rcv_total_cents"], int)
    assert isinstance(data["grand_total_cents"], int)
    assert isinstance(data["acv_total_cents"], int)


def assert_estimate_line(data: dict):
    _assert_common(data)
    assert data["negotiation_status"] in _LINE_STATUSES
    assert isinstance(data["extended_cents"], int)
    assert isinstance(data["unit_price_cents"], int)


def assert_supplement(data: dict):
    _assert_common(data)
    assert data["status"] in _SUPPLEMENT_STATUSES


def assert_negotiation_round(data: dict):
    _assert_common(data)
    assert data["status"] in _ROUND_STATUSES
    assert isinstance(data["round_number"], int)


def assert_line_disposition(data: dict):
    _assert_common(data)
    assert data["status"] in _DISPOSITION_STATUSES


def assert_code_upgrade(data: dict):
    _assert_common(data)
    assert data["status"] in _CODE_UPGRADE_STATUSES
    assert isinstance(data["estimated_cost_cents"], int)


def assert_work_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in _WA_STATUSES


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in _INVOICE_STATUSES
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["applied_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in _PAYMENT_STATUSES
    assert data["type"] in _PAYMENT_TYPES
    assert data["direction"] in _PAYMENT_DIRECTIONS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_invoice_balance_invariant(invoice: dict, cleared_applied_cents: int):
    """PRD §3.9 conserved quantity: total == outstanding + cleared payments applied."""
    assert invoice["total_cents"] == invoice["outstanding_cents"] + cleared_applied_cents, (
        f"invoice invariant violated: total {invoice['total_cents']} != "
        f"outstanding {invoice['outstanding_cents']} + applied {cleared_applied_cents}"
    )
