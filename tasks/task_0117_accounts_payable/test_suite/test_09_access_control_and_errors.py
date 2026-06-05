"""Authentication, authorization, and validation-precedence (PRD §2.1, §2.4).
The existence-beats-state precedence difficulty instance gets >=2 tests.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, capture_invoice, add_line,
    setup_master_data,
    api_client,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
APPROVER = TEST_USERS["approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Corner: errors / error_unauthenticated_missing_headers
# ---------------------------------------------------------------------------
def test_unauthenticated_missing_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    resp = api.create_vendor({"legal_name": "NoAuth", "payment_method": "ACH"}, headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)


# ---------------------------------------------------------------------------
# Corner: rbac / clerk_cannot_create_vendor_unauthorized
# ---------------------------------------------------------------------------
def test_clerk_cannot_create_vendor_unauthorized(api):
    """PRD §2.1: "An `APManager` owns the master data and the money: creating vendors,
    GL accounts, purchase orders, and approval routes".
    PRD §2.1: "If the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/clerk_cannot_create_vendor_unauthorized
    """
    resp = api.create_vendor({"legal_name": "ByClerk", "payment_method": "ACH"}, CLERK)
    validate_error(resp, "ERR_UNAUTHORIZED", 403)


# ---------------------------------------------------------------------------
# Corner: rbac / approver_cannot_code_invoice_unauthorized
# ---------------------------------------------------------------------------
def test_approver_cannot_code_invoice_unauthorized(api):
    """PRD §2.1: "An `Approver` acts on individual approval steps ... An approver may not
    code invoices and may not release payments."

    Design: Corner/rbac/approver_cannot_code_invoice_unauthorized
    """
    setup_master_data()
    vendor = create_vendor(legal_name="RB", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="RB-1")
    add_line(inv["id"], 1000)
    resp = api.code_invoice(inv["id"], APPROVER)
    validate_error(resp, "ERR_UNAUTHORIZED", 403)


# ---------------------------------------------------------------------------
# Corner: rbac / auditor_read_shared_op_allowed
# ---------------------------------------------------------------------------
def test_auditor_read_shared_op_allowed(api):
    """PRD §2.1: "An `Auditor` has read-only visibility across the entire payables
    surface ... All four roles may perform GET reads across the surface."

    Design: Corner/rbac/auditor_read_shared_op_allowed
    """
    vendor = create_vendor(legal_name="Read", payment_method="ACH")
    resp = api.get_vendor(vendor["id"], AUDITOR)
    data = validate_success(resp, 200)
    assert data["legal_name"] == "Read"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / not_found_beats_invalid_state_on_code
# Coding a non-existent invoice id -> 404 ERR_NOT_FOUND (existence outranks state).
# (>=2 tests.)
# ---------------------------------------------------------------------------
def test_code_nonexistent_invoice_returns_not_found(api):
    """PRD §2.4: "then existence of every resource referenced in the path or body
    (`ERR_NOT_FOUND`) ... and then, for any endpoint that drives a state machine,
    whether the target resource is in a state from which the requested transition is
    legal (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_code
    """
    create_gl_account()
    resp = api.code_invoice(NON_EXISTENT, CLERK)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_existence_check_precedes_state_check_on_code(api):
    """PRD §2.4: "When the server validates a request, it does so in a fixed precedence
    so that the most fundamental failures surface first."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_code
    """
    # No invoice exists, so a state machine endpoint must surface ERR_NOT_FOUND, never
    # ERR_INVALID_STATE — existence (precedence 3) ranks above state (precedence 5).
    resp = api.submit_invoice_for_approval(NON_EXISTENT, CLERK)
    validate_error(resp, "ERR_NOT_FOUND", 404)
