"""Conditional endpoints, OCC stale-version errors, RBAC, concurrency/version, and
immediate consistency.

Queue B (Corner) sections endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_program, create_active_card, setup_program_and_active_card,
    setup_approved_replacement, setup_open_replacement,
    setup_pending_refund_on_owned_card,
    draft_redemption, settle_redemption, place_hold, set_clock,
    create_replacement_payload, reload_card_payload,
    make_customer_headers,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]


# ── endpoints ──────────────────────────────────────────────────────────────

def test_open_replacement_on_already_replaced_card_rejected(api):
    """PRD §3.7: "Opening is refused if the old card already has its replaced_by_card_id set —
    meaning an approved replacement already exists — with ERR_CARD_ALREADY_REPLACED."

    Design: Corner/endpoints/open_replacement_on_already_replaced_card_rejected
    """
    program, old_card, _approved = setup_approved_replacement(settled_cents=3000, reason="FRAUD")
    # old_card is now VOIDED with replaced_by_card_id set; a new replacement is refused.
    res = api.create_replacement(
        create_replacement_payload(old_card["id"], reason="LOST"), _FRAUD)
    validate_error(res, "ERR_CARD_ALREADY_REPLACED", expected_status=409)


def test_redemption_legs_discoverable_by_card_filter(api):
    """PRD §3.5: "A redemption's legs can be listed and filtered by redemption_id, by card_id,
    or by ledger_entry_id."

    Design: Corner/endpoints/legs_discoverable_by_card_filter
    """
    program, card = setup_program_and_active_card(settled_cents=3000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    validate_success(settle_redemption(redemption["id"], redemption["version"]), 200)
    data, meta = validate_paginated(
        api.list_redemption_legs(_STORE, params={"card_id": card["id"]}))
    assert len(data) == 1
    assert data[0]["leg_amount_cents"] == 1000


# ── errors (OCC stale-version) ─────────────────────────────────────────────

def test_settle_with_stale_redemption_version_rejected(api):
    """PRD §2.12: "If an amendment has advanced the redemption's version since the client last
    read it, the client's settle request carries a stale expected_redemption_version, and the
    settle is rejected with ERR_STALE_VERSION (HTTP 412) before any debit posts."

    Design: Corner/errors/error_stale_version_on_settle_after_amend
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    stale_version = redemption["version"]
    # Amend advances the redemption's version past stale_version.
    get_success_data(api.amend_redemption(
        redemption["id"], {"requested_amount_cents": 2000}, _STORE))
    res = settle_redemption(redemption["id"], stale_version)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["settled_balance_cents"] == 5000, "no debit posted"


def test_approve_with_stale_old_card_version_rejected(api):
    """PRD §2.12: "If another writer has reloaded or partially redeemed the old card since the
    analyst last read it, the card's version has advanced, the submitted
    expected_old_card_version is stale, and the approval is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/errors/error_stale_old_card_version_on_replacement_approve
    """
    program, card, replacement = setup_open_replacement(settled_cents=3000, reason="FRAUD")
    stale_version = card["version"]
    # Reload advances the old card's version past stale_version.
    get_success_data(api.reload_card(card["id"], reload_card_payload(1000), _STORE))
    res = api.approve_replacement(
        replacement["id"], {"expected_old_card_version": stale_version}, _FRAUD)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_card(card["id"], _FRAUD), 200)
    assert after["lifecycle_status"] == "ACTIVE", "old card not voided"


# ── rbac ───────────────────────────────────────────────────────────────────

def test_store_associate_cannot_approve_replacement(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation ... the request is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/store_associate_cannot_approve_replacement
    """
    program, card, replacement = setup_open_replacement(settled_cents=3000, reason="FRAUD")
    # approve is FraudAnalyst-exclusive (PRD §4 endpoint table).
    res = api.approve_replacement(
        replacement["id"], {"expected_old_card_version": card["version"]}, _STORE)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_customer_cannot_approve_refund(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation ... the request is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/customer_cannot_approve_own_refund
    """
    program, customer, card, refund = setup_pending_refund_on_owned_card(
        settled_cents=5000, refund_cents=1000)
    # approve is ProgramAdmin-exclusive (PRD §4 endpoint table); the owning Customer cannot.
    res = api.approve_refund(refund["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ── cross_cutting_complexity_layers ────────────────────────────────────────

def test_amend_increments_redemption_version(api):
    """PRD §2.4: "a version, an integer that begins at 1 and increments by one on every
    mutation of the resource."
    PRD §2.12: "A draft redemption can be amended (its card_id_order or requested_amount_cents
    revised), and each amendment increments the redemption's version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    assert redemption["version"] == 1
    get_success_data(api.amend_redemption(
        redemption["id"], {"requested_amount_cents": 1500}, _STORE))
    after = validate_success(api.get_redemption(redemption["id"], _STORE), 200)
    assert after["version"] == 2
    assert after["requested_amount_cents"] == 1500


def test_hold_release_after_expiry_finalizes_as_expired(api):
    """PRD §3.4: "If the release is attempted at or after the hold's expires_at, the hold
    finalizes instead as EXPIRED (ACTIVE to EXPIRED), again restoring available balance by the
    held amount with no settled-balance impact."

    Design: Corner/cross_cutting_complexity_layers/hold_expiry_releases_value_after_clock_advance
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000,
                             hold_ttl_seconds=900)
    set_clock("2026-06-01T00:00:00Z")
    # Card and hold are created under the set clock so the hold's expires_at is well-defined.
    card = create_active_card(program["id"], 5000)
    hold = place_hold(card["id"], 2000)
    set_clock("2026-06-01T01:00:00Z")  # past created_at + 900s
    released = validate_success(api.release_hold(hold["id"], _STORE), 200)
    assert released["status"] == "EXPIRED"
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["pending_hold_cents"] == 0
    assert after["available_balance_cents"] == 5000


# ── consistency_model ──────────────────────────────────────────────────────

def test_settled_balance_visible_immediately_after_settle(api):
    """PRD §2.9: "the system applies changes immediately and consistently — a read taken after
    an operation reflects every cascade that operation triggered."

    Design: Corner/consistency_model/redemption_settle_balances_visible_same_response
    """
    program, card = setup_program_and_active_card(settled_cents=3000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    validate_success(settle_redemption(redemption["id"], redemption["version"]), 200)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["settled_balance_cents"] == 2000
    assert after["lifecycle_status"] == "ACTIVE"
