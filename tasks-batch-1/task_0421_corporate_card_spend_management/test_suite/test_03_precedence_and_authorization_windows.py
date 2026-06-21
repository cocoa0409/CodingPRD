"""Validation precedence under competing failures, and spend-authorization
interval semantics (half-open overlap vs buffered adjacency).

Difficulty queue: priority_pair_validation_conflict, resource_temporal_overlap.

SKIPPED instance (PRD-first Core rule): difficulty
priority_pair_validation_conflict / ppvc_gl_required_beats_receipt_required asserts
ERR_GL_CODE_REQUIRED wins over ERR_RECEIPT_REQUIRED on approve-review. PRD §3.6/§3.5
prose enumerates the approve-review checks as "First, the review must currently be
MATCHED; if it is still NEEDS_RECEIPT or UNREVIEWED, approval is blocked with
ERR_RECEIPT_REQUIRED. Second, the transaction's gl_account_id must be set ... else
ERR_GL_CODE_REQUIRED." The prose orders the receipt check FIRST, so a faithful
PRD-only reader would return ERR_RECEIPT_REQUIRED in the both-fail scenario — the
opposite of the asserted outcome. The instance is not uniquely derivable from PRD
prose, so per the Core rule it is skipped (no weakened/xfail test emitted).
"""
from test_helpers import (
    validate_error, get_success_data, ApiClient, ApiErrorId,
    setup_active_employee_authorization, setup_active_card_authorization,
    create_company, create_employee, create_spend_policy, create_card,
)
from test_helpers import factories as F
from test_helpers.test_users import make_finance_admin_headers

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / ppvc_mcc_blocked_beats_card_not_active
# ===========================================================================
def test_mcc_blocked_wins_over_card_not_active(api: ApiClient):
    """PRD §2.9: "the capture pipeline evaluates, in this order: first, the
    merchant-category control — if the transaction's mcc_code is among the card's
    spend policy's blocked_mcc_codes, the capture is rejected with ERR_MCC_BLOCKED;
    second, card state — the card must be ACTIVE, so a REQUESTED physical card, a
    FROZEN card, or a TERMINATED card is rejected with ERR_CARD_NOT_ACTIVE"
    PRD §2.9: "This ordering means, for example, that a blocked merchant category is
    reported even when the card is also frozen, and a frozen card is reported before
    any limit arithmetic is attempted."

    A blocked-MCC capture on a FROZEN card returns ERR_MCC_BLOCKED, not ERR_CARD_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_mcc_blocked_beats_card_not_active
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    emp = create_employee(company["id"], "pp1@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"], name="Blk", blocked_mcc_codes=["7995"])
    card = create_card(company["id"], emp["id"], pol["id"])
    get_success_data(api.freeze_card(card["id"], ADMIN))
    resp = api.capture_transaction(
        card["id"], F.capture_transaction_payload(merchant_name="Casino", mcc_code="7995",
                                                  amount_cents=5000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MCC_BLOCKED.value)


def test_frozen_card_reported_when_mcc_not_blocked(api: ApiClient):
    """PRD §2.9: "second, card state — the card must be ACTIVE, so a REQUESTED physical
    card, a FROZEN card, or a TERMINATED card is rejected with ERR_CARD_NOT_ACTIVE"
    PRD §2.9: "and a frozen card is reported before any limit arithmetic is attempted."

    With no MCC block, a capture on a FROZEN card surfaces the next-priority gate,
    ERR_CARD_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_mcc_blocked_beats_card_not_active
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    emp = create_employee(company["id"], "pp1b@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"], name="Std")  # no blocked MCCs
    card = create_card(company["id"], emp["id"], pol["id"])
    get_success_data(api.freeze_card(card["id"], ADMIN))
    resp = api.capture_transaction(
        card["id"], F.capture_transaction_payload(merchant_name="Shop", mcc_code="5999",
                                                  amount_cents=5000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap / rto_employee_scope_half_open_overlap
# ===========================================================================
def test_employee_scope_overlapping_window_rejected(api: ApiClient):
    """PRD §3.9: "For an EMPLOYEE-scope authorization, the new window must not overlap
    any ACTIVE EMPLOYEE-scope authorization for the same employee_id. Overlap is the
    half-open test in which the new window's start is earlier than an existing window's
    end and that existing window's start is earlier than the new window's end ... A true
    overlap is rejected with ERR_AUTH_WINDOW_OVERLAP."

    [2026-06-05, 2026-06-15) overlaps the existing [2026-06-01, 2026-06-10): rejected.

    Design: Difficulty/resource_temporal_overlap/rto_employee_scope_half_open_overlap
    """
    s = setup_active_employee_authorization("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_spend_authorization(
        F.create_spend_authorization_payload(
            s["company"]["id"], s["employee"]["id"],
            "2026-06-05T00:00:00Z", "2026-06-15T00:00:00Z",
            scope="EMPLOYEE", budget_cents=30000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP.value)


def test_employee_scope_touching_window_allowed(api: ApiClient):
    """PRD §3.9: "windows that merely touch at an endpoint do not overlap and are
    allowed."
    PRD §3.9: "The authorization is created ACTIVE."

    A touching [2026-06-10, 2026-06-20) after [2026-06-01, 2026-06-10) is accepted
    (created ACTIVE) — the half-open test treats touching as non-overlapping.

    Design: Difficulty/resource_temporal_overlap/rto_employee_scope_half_open_overlap
    """
    s = setup_active_employee_authorization("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_spend_authorization(
        F.create_spend_authorization_payload(
            s["company"]["id"], s["employee"]["id"],
            "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z",
            scope="EMPLOYEE", budget_cents=30000), ADMIN)
    from test_helpers import validate_success
    created = validate_success(resp, expected_status=201)
    assert created["status"] == "ACTIVE", (
        f"touching EMPLOYEE-scope window accepted as ACTIVE, got {created['status']}")


# ===========================================================================
# Difficulty: resource_temporal_overlap / rto_card_scope_buffered_adjacency
# ===========================================================================
def test_card_scope_touching_window_rejected_by_buffer(api: ApiClient):
    """PRD §3.9: "For a CARD-scope authorization, the new window must keep a buffer gap
    of two days from any ACTIVE CARD-scope authorization for the same card_id ... Any
    window that fails to keep that two-day buffer — including windows that merely touch,
    which the employee scope would have allowed — is rejected with
    ERR_AUTH_WINDOW_TOO_CLOSE."

    A touching CARD-scope [2026-06-10, 2026-06-20) after [2026-06-01, 2026-06-10) has a
    0-day gap (< 2) and is rejected with ERR_AUTH_WINDOW_TOO_CLOSE.

    Design: Difficulty/resource_temporal_overlap/rto_card_scope_buffered_adjacency
    """
    s = setup_active_card_authorization("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_spend_authorization(
        F.create_spend_authorization_payload(
            s["company"]["id"], s["employee"]["id"],
            "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z",
            scope="CARD", card_id=s["card"]["id"], budget_cents=30000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_TOO_CLOSE.value)


def test_card_scope_window_beyond_buffer_allowed(api: ApiClient):
    """PRD §3.9: "the new window is acceptable only if its start is at least two days
    after the existing window's end, or its end plus two days is at or before the
    existing window's start."
    PRD §3.9: "The authorization is created ACTIVE."

    A CARD-scope window starting 2026-06-12 (>= existing end 2026-06-10 + 2 days) is
    accepted as ACTIVE.

    Design: Difficulty/resource_temporal_overlap/rto_card_scope_buffered_adjacency
    """
    s = setup_active_card_authorization("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_spend_authorization(
        F.create_spend_authorization_payload(
            s["company"]["id"], s["employee"]["id"],
            "2026-06-12T00:00:00Z", "2026-06-20T00:00:00Z",
            scope="CARD", card_id=s["card"]["id"], budget_cents=30000), ADMIN)
    from test_helpers import validate_success
    created = validate_success(resp, expected_status=201)
    assert created["status"] == "ACTIVE", (
        f"CARD-scope window beyond the 2-day buffer accepted, got {created['status']}")
