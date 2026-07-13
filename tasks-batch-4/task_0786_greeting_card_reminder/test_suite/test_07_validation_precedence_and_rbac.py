"""Deterministic validation precedence on submit (state over fiscal, referential
over temporal) and role-based access denials.

Each precedence pair is proven with a dual-failure scenario plus a single-failure
contrast that shows the higher-priority check truly pre-empts the lower one.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_account, new_subscription, grant_credits, new_contact, new_card, new_order,
    account_version, submit, holder, TEST_USERS, create_order_payload,
)

STUDIO = TEST_USERS["studio_operator_headers"]


# --------------------------------------------------------------------------
# State (priority 4) beats fiscal (priority 18)
# --------------------------------------------------------------------------
def test_submit_state_error_pre_empts_fiscal(api):
    """PRD §2.9: "an illegal transition yields `ERR_INVALID_STATE`, and this
    state check takes precedence over every business rule that follows it."

    Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
    """
    account = new_account()
    grant_credits(account["id"], 1)  # exactly one credit
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    ah = holder(account["id"])
    submit(account["id"], order["id"])  # order -> PENDING_PROOF, balance -> 0

    # Re-submitting fails BOTH the state check (already PENDING_PROOF) and the
    # fiscal check (balance 0); the state error must win.
    fresh_version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": fresh_version}, ah),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_submit_fiscal_surfaces_when_state_is_legal(api):
    """PRD §3.4: "the account must hold at least one credit, or it fails with
    `ERR_INSUFFICIENT_CREDITS`".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
    """
    # DRAFT order (legal state) with zero credits: with the state check passing,
    # the fiscal error is what surfaces — the check the state error pre-empts above.
    account = new_account()  # 0 credits
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    ah = holder(account["id"])
    version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, ah),
        ApiErrorId.ERR_INSUFFICIENT_CREDITS.value,
    )


# --------------------------------------------------------------------------
# Referential (priority 7) beats temporal (priority 10)
# --------------------------------------------------------------------------
def test_submit_referential_error_pre_empts_temporal(api):
    """PRD §3.4: "the recipient contact's address must be `VERIFIED`, or the
    submit fails with `ERR_ADDRESS_NOT_VERIFIED`; the requested
    `scheduled_send_at` must lie strictly in the future relative to the current
    logical clock, or it fails with `ERR_SEND_DATE_IN_PAST`".

    Design: Difficulty/priority_pair_validation_conflict/submit_referential_beats_temporal
    """
    account = new_account()
    grant_credits(account["id"], 1)
    contact = new_contact(account["id"])  # UNVERIFIED
    card = new_card()
    # Past send date (before the 2026-03-01 default clock) AND unverified contact.
    order = new_order(account["id"], contact["id"], card["id"], scheduled_send_at="2026-02-01T00:00:00Z")
    ah = holder(account["id"])
    version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, ah),
        ApiErrorId.ERR_ADDRESS_NOT_VERIFIED.value,
    )


def test_submit_temporal_surfaces_when_address_verified(api):
    """PRD §3.4: "the requested `scheduled_send_at` must lie strictly in the
    future relative to the current logical clock, or it fails with
    `ERR_SEND_DATE_IN_PAST`".

    Design: Difficulty/priority_pair_validation_conflict/submit_referential_beats_temporal
    """
    # Verified contact removes the referential failure; the temporal error — the
    # one the address error pre-empts above — is what surfaces.
    account = new_account()
    grant_credits(account["id"], 1)
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"], scheduled_send_at="2026-02-01T00:00:00Z")
    ah = holder(account["id"])
    version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, ah),
        ApiErrorId.ERR_SEND_DATE_IN_PAST.value,
    )


# --------------------------------------------------------------------------
# RBAC denials (queue B)
# --------------------------------------------------------------------------
def test_studio_operator_cannot_submit_order(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation — or an account holder attempts to act on
    a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/studio_operator_cannot_submit_order_returns_unauthorized
    """
    account = new_account()
    grant_credits(account["id"], 1)
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    version = account_version(account["id"])
    # Submit is AccountHolder-exclusive; a StudioOperator call is unauthorized.
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, STUDIO),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_account_holder_cannot_verify_address(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation — or an account holder attempts to act on
    a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/account_holder_cannot_verify_address_returns_unauthorized
    """
    account = new_account()
    contact = new_contact(account["id"])
    # Address verification is StudioOperator/PlatformAdmin only.
    validate_error(
        api.verify_address(contact["id"], {"result": "VERIFIED"}, holder(account["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
