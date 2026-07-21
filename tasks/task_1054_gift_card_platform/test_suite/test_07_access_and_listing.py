"""Access control (missing context, role denial, ownership) and list-endpoint
pagination / reverse reachability.

Covers Corner rbac and endpoints (listing) instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_merchant_payload, create_card_program_payload,
    TEST_USERS, make_merchant_admin_headers,
    create_active_merchant, create_active_program, commit_batch, redeem,
    setup_single_active_card, api_client,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
POS = TEST_USERS["pos_terminal_headers"]
ANY = TEST_USERS["any_headers"]


# ─────────── Corner: RBAC ───────────

def test_missing_user_context_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational role under which the request is made. If either header is absent, or if `X-User-Role` is not one of the roles defined below, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/rbac/get_merchant_missing_user_context_returns_400
    """
    merchant = create_active_merchant()
    res = api.get_merchant(merchant["id"], {})  # no X-User-ID / X-User-Role
    validate_error(res, "ERR_MISSING_USER_CONTEXT")


def test_posterminal_create_merchant_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/posterminal_create_merchant_forbidden
    """
    res = api.create_merchant(create_merchant_payload(legal_name="Rogue"), POS)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_merchant_admin_wrong_owner_create_program_forbidden(api):
    """PRD §2.1: "Ownership checks on any merchant-scoped resource compare the resource's owning merchant to `X-User-ID`: directly against `merchant_id` for a `CardProgram`"

    Design: Corner/rbac/merchantadmin_wrong_owner_create_program_forbidden
    """
    merchant = create_active_merchant()
    wrong_owner = make_merchant_admin_headers("11111111-1111-1111-1111-111111111111")
    res = api.create_card_program(
        create_card_program_payload(merchant["id"], name="P"), wrong_owner)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─────────── Corner: list endpoints ───────────

def test_list_gift_cards_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_gift_cards_pagination_envelope
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    commit_batch(merchant["id"], program["id"], 3, 5000)
    data, meta = validate_paginated(
        api.list_gift_cards(ANY, params={"card_program_id": program["id"], "limit": 2, "offset": 0}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_list_ledger_entries_by_card(api):
    """PRD §3.4: "On activation the system posts an `ACTIVATION_LOAD` ledger entry whose `amount_cents` equals the positive `initial_load_cents`, sets `activated_at` to the current clock, sets `expires_at` to the activation instant plus the program's `expiry_months`, sets `last_activity_at` to the same instant, and moves the card to `ACTIVE`."
    PRD §3.4: "When all guards pass, a `REDEMPTION` entry is posted with a negative `amount_cents` equal to the redeemed amount, `last_activity_at` is set to the current clock, and if the redemption brings the card's `balance_cents` to exactly 0 the card auto-closes from `ACTIVE` to the terminal `CLOSED` state."

    Design: Corner/endpoints/list_ledger_entries_by_card_reverse_reachability
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    redeem(card["id"], 1000)
    data, meta = validate_paginated(
        api.list_ledger_entries(ANY, params={"gift_card_id": card["id"]}))
    assert meta["total_count"] == 2  # ACTIVATION_LOAD + REDEMPTION
