"""PayableConfirmation upload, confirm, revoke (PRD §3.3, §2.7).

State transitions: DRAFT → PENDING_CONFIRM → CONFIRMED → REVOKED |
SETTLED. The credit-line ledger is updated on CONFIRMED and revoke.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_credit_line_invariants,
    assert_payable_confirmation,
    confirm_payable_confirmation,
    create_payable_confirmation,
    create_payable_confirmation_payload,
    get_core_enterprise,
    iso_in_days,
    make_core_enterprise_headers,
    revoke_confirmation,
    revoke_payable_confirmation_payload,
    setup_active_supplier,
    setup_approved_core_enterprise,
    setup_confirmed_payable_confirmation,
    setup_tier2_chain,
    suspend_core_enterprise,
    validate_error,
    validate_success,
)


def test_upload_payable_confirmation_starts_pending_with_tier_copied(api):
    """PRD §3.3: "The new confirmation is created in DRAFT and
    transitions immediately on upload to PENDING_CONFIRM provided three
    structural preconditions hold." PRD §3.3 also: "the platform
    copies the supplier's current tier_to_core into the confirmation's
    own tier field, pinning the tier for the lifetime of the
    confirmation."
    """
    ce = setup_approved_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=supplier["id"],
        amount_cents=1_000_000, due_date=iso_in_days(60),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    pc = validate_success(res, expected_status=201)
    assert_payable_confirmation(pc)
    assert pc["status"] == "PENDING_CONFIRM"
    assert pc["tier"] == supplier["tier_to_core"]


def test_upload_blocks_when_core_enterprise_pending(api):
    """PRD §3.3: "The referenced CoreEnterprise is in onboarding_status
    of APPROVED."

    A still-pending core enterprise cannot host a payable confirmation
    upload — PRD §5 catalogues ERR_CORE_ENTERPRISE_NOT_APPROVED (409).
    """
    from test_helpers import register_core_enterprise, TEST_USERS
    ce = register_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=supplier["id"],
        amount_cents=1_000_000, due_date=iso_in_days(60),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CORE_ENTERPRISE_NOT_APPROVED.value)


def test_upload_requires_positive_amount(api):
    """PRD §3.3: "The amount_cents must be strictly positive (else
    ERR_AMOUNT_NON_POSITIVE)."
    """
    ce = setup_approved_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=supplier["id"],
        amount_cents=0, due_date=iso_in_days(60),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    validate_error(res, ApiErrorId.ERR_AMOUNT_NON_POSITIVE.value)


def test_upload_rejects_due_date_in_the_past(api):
    """PRD §3.3: "the due_date must be strictly later than the current
    clock ... (else ERR_DUE_DATE_OUT_OF_RANGE)."
    """
    ce = setup_approved_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=supplier["id"],
        amount_cents=1_000_000, due_date=iso_in_days(-10),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUE_DATE_OUT_OF_RANGE.value)


def test_confirm_moves_pending_to_confirmed_and_reserves_credit_line(api):
    """PRD §3.3: "Electronic confirmation by the core enterprise
    advances PENDING_CONFIRM → CONFIRMED ... On success,
    credit_line_reserved_cents is increased by amount_cents,
    confirmed_at is set to the current UTC instant."
    """
    bundle = setup_confirmed_payable_confirmation(
        amount_cents=2_000_000,
        credit_line_total_cents=10_000_000_00,
    )
    ce = get_core_enterprise(bundle["ce"]["id"])
    pc = bundle["confirmation"]
    assert pc["status"] == "CONFIRMED"
    assert pc.get("confirmed_at"), (
        "confirmed_at MUST be set per PRD §3.3 on confirm."
    )
    assert ce["credit_line_reserved_cents"] == 2_000_000, (
        f"Expected credit_line_reserved_cents == 2_000_000, "
        f"got {ce['credit_line_reserved_cents']}"
    )
    assert_credit_line_invariants(ce)


def test_confirm_blocks_when_credit_line_insufficient(api):
    """PRD §3.3: "available headroom ... is at least equal to the
    confirmation's amount_cents, failing which the response is
    ERR_CREDIT_LINE_INSUFFICIENT."
    """
    ce = setup_approved_core_enterprise(credit_line_total_cents=1_000_000)
    supplier = setup_active_supplier(tier_to_core=1)
    pc = create_payable_confirmation(
        ce, supplier, amount_cents=2_000_000,
    )  # Amount exceeds the 1_000_000 line.
    res = api.confirm_payable_confirmation(
        pc["id"], make_core_enterprise_headers(ce["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_LINE_INSUFFICIENT.value)


def test_double_confirm_returns_invalid_state(api):
    """PRD §2.9: "Two concurrent attempts to confirm the same
    PayableConfirmation are first-writer-wins on its status field; the
    loser receives ERR_INVALID_STATE (HTTP 409) because the
    confirmation already left PENDING_CONFIRM."
    """
    bundle = setup_confirmed_payable_confirmation()
    res = api.confirm_payable_confirmation(
        bundle["confirmation"]["id"],
        make_core_enterprise_headers(bundle["ce"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_revoke_confirmed_releases_reservation(api):
    """PRD §3.3: "when allowed, the reserved amount is subtracted from
    credit_line_reserved_cents."
    """
    bundle = setup_confirmed_payable_confirmation(amount_cents=3_000_000)
    ce_before = get_core_enterprise(bundle["ce"]["id"])
    revoke_confirmation(bundle["ce"], bundle["confirmation"])
    ce_after = get_core_enterprise(bundle["ce"]["id"])
    assert ce_after["credit_line_reserved_cents"] == (
        ce_before["credit_line_reserved_cents"] - 3_000_000
    ), (
        "credit_line_reserved_cents must decrease by the confirmation "
        "amount_cents on revoke"
    )
    assert_credit_line_invariants(ce_after)


def test_revoke_requires_reason(api):
    """PRD §3.3: "The request body must carry a free-text
    revoke_reason."
    """
    bundle = setup_confirmed_payable_confirmation()
    payload = {}  # missing revoke_reason
    res = api.revoke_payable_confirmation(
        bundle["confirmation"]["id"], payload,
        make_core_enterprise_headers(bundle["ce"]["id"]),
    )
    assert res.status_code >= 400, (
        "Revoke without revoke_reason must be rejected per PRD §3.3."
    )


def test_tier2_upload_requires_parent_chain_confirmed(api):
    """PRD §3.3: "For tier-2 and deeper suppliers, the upload
    additionally requires that the upstream parent confirmation chain
    — resolved by following parent_supplier_id and locating the most
    recent PayableConfirmation for that parent — be in CONFIRMED or
    SETTLED; otherwise the upload is rejected with
    ERR_TIER_PARENT_NOT_CONFIRMED."

    Build a tier-2 supplier whose parent has NO confirmed confirmation.
    """
    from test_helpers import register_supplier, setup_active_supplier
    ce = setup_approved_core_enterprise()
    s_t1 = setup_active_supplier(tier_to_core=1)
    # Tier-2 supplier with parent tier-1, but no parent confirmation yet.
    s_t2_raw = register_supplier(
        tier_to_core=2, parent_supplier_id=s_t1["id"],
    )
    from test_helpers import kyc_pass_supplier
    s_t2 = kyc_pass_supplier(s_t2_raw)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=s_t2["id"],
        amount_cents=1_000_000, due_date=iso_in_days(60),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TIER_PARENT_NOT_CONFIRMED.value)


def test_tier2_upload_succeeds_when_parent_chain_confirmed(api):
    """PRD §3.3: tier-2+ upload "be in CONFIRMED or SETTLED" — when the
    parent confirmation IS confirmed, the tier-2 upload succeeds.
    """
    chain = setup_tier2_chain()
    payload = create_payable_confirmation_payload(
        core_enterprise_id=chain["ce"]["id"],
        supplier_id=chain["supplier_t2"]["id"],
        amount_cents=500_000, due_date=iso_in_days(60),
    )
    res = api.create_payable_confirmation(
        payload, make_core_enterprise_headers(chain["ce"]["id"]),
    )
    pc = validate_success(res, expected_status=201)
    assert pc["status"] == "PENDING_CONFIRM"
    assert pc["tier"] == 2
