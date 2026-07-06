"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp) internally.
"""
import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(s):
    """Parse an ISO 8601 UTC instant ('Z' or offset, with or without fractional
    digits) into an aware UTC datetime for instant-equality comparison."""
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def assert_same_instant(actual, expected):
    """Assert two ISO 8601 timestamps denote the same UTC instant.

    PRD §2.4 fixes the three-fractional-digit representation only for `created_at`,
    `updated_at`, and `api_request_timestamp`; it does not pin a fractional-digit
    format for clock-derived timestamps such as `decision_deadline`, `delivery_date`,
    or `warranty_expiry`. This compares the instant (the PRD-determined arithmetic)
    rather than the exact string form (which the PRD leaves unspecified)."""
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: actual={actual!r} expected (same instant as) {expected!r}"
    )


PAYER_TYPES = ["MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY"]
DEVICE_CATEGORIES = ["LOWER_LIMB_PROSTHETIC", "UPPER_LIMB_PROSTHETIC",
                     "SPINAL_ORTHOSIS", "LOWER_EXTREMITY_ORTHOSIS"]
RX_STATUSES = ["DRAFT", "SIGNED", "CONSUMED", "EXPIRED", "VOIDED"]
ORDER_STATUSES = ["INTAKE", "AUTH_PENDING", "FABRICATION", "READY_FOR_FITTING",
                  "DELIVERED", "CANCELLED"]
PA_STATUSES = ["SUBMITTED", "PENDED", "APPROVED", "DENIED", "EXPIRED"]
ADJUDICATION_STATUSES = ["DRAFT", "SUBMITTED", "ADJUDICATED", "DENIED"]
APPEAL_STATUSES = ["NONE", "APPEALED", "APPEAL_UPHELD", "APPEAL_OVERTURNED"]
MODIFIERS = ["NONE", "KX", "GA", "GZ", "RT", "LT"]
MILESTONE_STEPS = ["CASTING", "MODIFICATION", "ASSEMBLY", "QUALITY_CHECK"]
REPAIR_STATUSES = ["REPORTED", "ASSESSED", "REPAIRED", "REPLACEMENT_AUTHORIZED", "CLOSED"]
ACCREDITATION_STATUSES = ["ACCREDITED", "LAPSED", "UNACCREDITED"]


def _assert_common(data: dict):
    """id (UUID, no prefix), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version int >= 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["payer_type"] in PAYER_TYPES


def assert_physician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi"], str)
    assert isinstance(data["pecos_enrolled"], bool)


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["accreditation_status"] in ACCREDITATION_STATUSES
    assert isinstance(data["surety_bond_active"], bool)


def assert_prescription(data: dict):
    _assert_common(data)
    assert data["device_category"] in DEVICE_CATEGORIES
    assert data["status"] in RX_STATUSES


def assert_device_order(data: dict):
    _assert_common(data)
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["requires_prior_auth"], bool)
    assert isinstance(data["milestone_progress_pct"], int)
    assert isinstance(data["allowed_total_cents"], int)


def assert_prior_auth(data: dict):
    _assert_common(data)
    assert data["status"] in PA_STATUSES
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1


def assert_claim_line(data: dict):
    _assert_common(data)
    assert data["modifier"] in MODIFIERS
    assert data["adjudication_status"] in ADJUDICATION_STATUSES
    assert data["appeal_status"] in APPEAL_STATUSES
    assert isinstance(data["allowed_cents"], int)


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["step"] in MILESTONE_STEPS
    assert isinstance(data["weight"], int) and data["weight"] >= 1
    assert isinstance(data["completed"], bool)


def assert_repair_request(data: dict):
    _assert_common(data)
    assert data["status"] in REPAIR_STATUSES
    assert isinstance(data["cost_cents"], int)
    assert isinstance(data["warranty_applies"], bool)


def assert_adjustment(data: dict):
    _assert_common(data)
    assert isinstance(data["within_warranty"], bool)
    assert isinstance(data["billable"], bool)


def assert_compliance_check(data: dict):
    """ComplianceCheck is append-only: carries id + created_at only, NO version field."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["passed"], bool)
    assert isinstance(data["failure_reasons"], list)


def assert_order_ledger_consistent(order: dict, claim_lines: list):
    """Invariant: allowed_total_cents == exact sum of allowed_cents over ADJUDICATED lines."""
    expected = sum(cl["allowed_cents"] for cl in claim_lines
                   if cl["adjudication_status"] == "ADJUDICATED")
    assert order["allowed_total_cents"] == expected, (
        f"ledger drift: allowed_total_cents={order['allowed_total_cents']} "
        f"but sum over ADJUDICATED lines={expected}"
    )
