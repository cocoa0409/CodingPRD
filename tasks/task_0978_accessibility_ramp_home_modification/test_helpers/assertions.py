"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CASE_STATUSES = [
    "INTAKE", "ASSESSMENT_SCHEDULED", "ASSESSED", "QUOTE_DRAFTED",
    "QUOTE_SUBMITTED", "FUNDING_PENDING", "FUNDING_APPROVED",
    "INSTALLATION_SCHEDULED", "INSTALLED", "INSPECTED", "WARRANTY_ACTIVE",
    "CLOSED", "CANCELLED",
]
POSTURES = ["UNFUNDED", "PARTIALLY_FUNDED", "FULLY_FUNDED", "OVERFUNDED"]
ASSESSMENT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
QUOTE_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED"]
FUNDING_STATUSES = ["PENDING", "APPROVED", "DENIED", "EXHAUSTED", "WITHDRAWN"]
ALLOCATION_STATUSES = ["PENDING", "COMMITTED", "RELEASED", "REVERSED"]
JOB_STATUSES = ["SCHEDULED", "MATERIALS_ORDERED", "IN_PROGRESS", "PUNCH_LIST", "COMPLETED", "CANCELLED"]
RENTAL_STATUSES = ["RESERVED", "DELIVERED", "INSTALLED", "IN_USE", "PICKUP_SCHEDULED", "RETURNED", "CANCELLED"]
UNIT_STATUSES = ["AVAILABLE", "RESERVED", "DEPLOYED", "MAINTENANCE", "RETIRED"]
INSPECTION_OUTCOMES = ["PENDING", "PASSED", "FAILED", "CONDITIONAL_PASS"]
INVOICE_STATUSES = ["DRAFT", "SENT", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOID", "DISPUTED"]
CLAIM_STATUSES = ["OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "DENIED", "CLOSED"]
CONSULT_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]
SCHEDULE_STATUSES = ["PENDING", "SCHEDULED", "COMPLETED", "OVERDUE", "WAIVED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert isinstance(data["client_address"], str)
    assert isinstance(data["client_phone"], str)
    assert data["referral_source"] in ["PHYSICIAN", "OT", "VA", "SELF", "AGENCY"]
    assert data["status"] in CASE_STATUSES
    assert data["funding_posture"] in POSTURES
    for f in ("total_quoted_cents", "total_funded_cents", "total_billed_cents",
              "total_paid_cents", "balance_due_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert_case_ledger_invariants(data)


def assert_case_ledger_invariants(data: dict):
    """Case ledger invariants from PRD §2.8."""
    assert data["balance_due_cents"] >= 0, "balance_due_cents may never go negative (PRD §2.8)"
    for f in ("total_quoted_cents", "total_funded_cents", "total_billed_cents", "total_paid_cents"):
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ASSESSMENT_STATUSES
    assert data["assessor_role"] in ["OT", "CAPS", "BOTH"]
    assert data["assessment_type"] in ["INITIAL", "REASSESSMENT", "POST_INSTALL"]
    assert is_valid_uuid(data.get("case_id", "")), "case_id must link to the parent case"


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in QUOTE_STATUSES
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    for f in ("labor_cost_cents", "material_cost_cents", "permit_fee_cents",
              "equipment_cost_cents", "contingency_cents", "subtotal_cents", "total_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative integer cents"


def assert_quote_line_item(data: dict):
    _assert_common(data)
    assert data["line_type"] in [
        "LABOR", "MATERIAL", "PERMIT", "EQUIPMENT_RENTAL",
        "EQUIPMENT_PURCHASE", "DEMOLITION", "ELECTRICAL", "PLUMBING",
    ]
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["tax_cents"], int)


def assert_funding_source(data: dict):
    _assert_common(data)
    assert data["status"] in FUNDING_STATUSES
    assert data["source_type"] in [
        "MEDICAID_WAIVER", "VA_BENEFIT", "STATE_GRANT",
        "PRIVATE_INSURANCE", "SELF_PAY", "CHARITY",
    ]
    assert isinstance(data["requested_cents"], int)


def assert_funding_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ALLOCATION_STATUSES
    assert data["allocation_type"] in ["QUOTE_LEVEL", "LINE_LEVEL"]
    assert isinstance(data["amount_cents"], int)


def assert_installation_job(data: dict):
    _assert_common(data)
    assert data["status"] in JOB_STATUSES
    assert data["permit_status"] in ["NOT_REQUIRED", "PENDING", "ISSUED", "EXPIRED", "CLOSED"]
    assert data["inspection_status"] in ["NOT_SCHEDULED", "SCHEDULED", "PASSED", "FAILED", "WAIVED"]


def assert_rental_ramp(data: dict):
    _assert_common(data)
    assert data["status"] in RENTAL_STATUSES
    assert data["deposit_status"] in ["HELD", "REFUNDED", "FORFEITED"]
    assert isinstance(data["monthly_rate_cents"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_inventory_unit(data: dict):
    _assert_common(data)
    assert data["status"] in UNIT_STATUSES
    assert data["ramp_type"] in ["MODULAR_ALUMINUM", "PORTABLE_THRESHOLD", "SUITCASE", "CUSTOM_WOOD"]
    assert data["condition_grade"] in ["A", "B", "C", "D"]


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ["PRE_INSTALL", "ROUGH", "FINAL", "WARRANTY", "REASSESSMENT"]
    assert data["outcome"] in INSPECTION_OUTCOMES


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in INVOICE_STATUSES
    assert data["invoice_type"] in [
        "INSTALLATION", "RENTAL_MONTHLY", "RENTAL_FINAL", "SERVICE_CALL", "WARRANTY_WORK",
    ]
    for f in ("subtotal_cents", "tax_cents", "total_cents", "amount_paid_cents", "balance_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_invoice_line_item(data: dict):
    _assert_common(data)
    for f in ("extended_price_cents", "tax_cents", "line_total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in CLAIM_STATUSES
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "SAFETY_CRITICAL"]


def assert_ot_consultation(data: dict):
    _assert_common(data)
    assert data["status"] in CONSULT_STATUSES
    assert data["consultation_type"] in ["INITIAL_EVAL", "FOLLOW_UP", "DISCHARGE_PLANNING", "HOME_SAFETY"]


def assert_reassessment_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in SCHEDULE_STATUSES
    assert data["trigger_event"] in ["POST_INSTALL", "TIME_BASED", "CONDITION_CHANGE", "REQUEST"]
    assert data["priority"] in ["ROUTINE", "URGENT", "EMERGENT"]
