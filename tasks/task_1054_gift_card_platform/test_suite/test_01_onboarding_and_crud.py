"""Merchant/program/batch creation, defaults, and basic lifecycle guards.

Covers Corner queue instances in the entities and state_machines sections that
concern resource creation, defaulting, required-field validation, and simple
invalid-transition rejections.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_merchant_payload, create_card_program_payload, create_card_batch_payload,
    assert_merchant, assert_card_program, assert_gift_card,
    TEST_USERS, make_merchant_admin_headers, NON_EXISTENT_UUID,
    create_active_merchant, create_active_program, create_draft_program,
    commit_batch, get_batch_cards,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ANY = TEST_USERS["any_headers"]


def test_create_merchant_returns_pending_with_defaults(api):
    """PRD §3.1: "A newly created merchant begins in `PENDING` status with `version` 1 and its computed aggregates (`unsettled_redemptions_cents`, `lifetime_net_payout_cents`) initialized to 0."
    PRD §3.1: "an optional `settlement_currency` (an ISO currency code that defaults to `USD` and governs where settlement payouts are denominated)."

    Design: Corner/entities/create_merchant_returns_201_defaults_and_system_fields
    """
    res = api.create_merchant(create_merchant_payload(legal_name="Acme"), PLATFORM)
    merchant = validate_success(res, 201)
    assert_merchant(merchant)
    assert merchant["status"] == "PENDING"
    assert merchant["settlement_currency"] == "USD"
    assert merchant["version"] == 1
    assert merchant["unsettled_redemptions_cents"] == 0
    assert merchant["lifetime_net_payout_cents"] == 0


def test_get_unknown_merchant_returns_not_found(api):
    """PRD §2.11: "existence of every referenced resource id, validated left-to-right so that the first path or body id that does not resolve yields `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/get_merchant_not_found_returns_404
    """
    res = api.get_merchant(NON_EXISTENT_UUID, ANY)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_program_missing_name_rejected(api):
    """PRD §2.11: "body well-formedness — required fields present, enums valid, amounts positive integers, `card_count` at least 1 — yielding `ERR_VALIDATION` (HTTP 400)"

    Design: Corner/entities/create_program_missing_name_returns_validation
    """
    merchant = create_active_merchant()
    admin = make_merchant_admin_headers(merchant["id"])
    res = api.create_card_program({"merchant_id": merchant["id"]}, admin)
    validate_error(res, "ERR_VALIDATION")


def test_program_defaults_applied_on_create(api):
    """PRD §3.2: "`breakage_method` (either `ESTIMATED` or `REMITTANCE`, defaulting to `REMITTANCE`), `expiry_months` (whole months from activation to expiry, at least 1, defaulting to 12), `max_balance_cents` (the ceiling a card's balance may reach after any load or reload, defaulting to 100000), and `min_load_cents` (the smallest permitted reload amount, defaulting to 500)."

    Design: Corner/entities/program_defaults_applied_on_create
    """
    merchant = create_active_merchant()
    admin = make_merchant_admin_headers(merchant["id"])
    res = api.create_card_program(
        create_card_program_payload(merchant["id"], name="P"), admin)
    program = validate_success(res, 201)
    assert_card_program(program)
    assert program["breakage_method"] == "REMITTANCE"
    assert program["expiry_months"] == 12
    assert program["max_balance_cents"] == 100000
    assert program["min_load_cents"] == 500


def test_create_batch_invalid_channel_rejected(api):
    """PRD §2.11: "body well-formedness — required fields present, enums valid, amounts positive integers, `card_count` at least 1 — yielding `ERR_VALIDATION` (HTTP 400)"
    PRD §3.3: "A batch declares a `channel` (`DIGITAL` or `PHYSICAL`), a `card_count` (the number of cards to mint, at least 1)"

    Design: Corner/entities/create_batch_invalid_channel_enum_returns_validation
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    admin = make_merchant_admin_headers(merchant["id"])
    res = api.create_card_batch(
        create_card_batch_payload(program["id"], 1, 5000, channel="MAGSTRIPE"), admin)
    validate_error(res, "ERR_VALIDATION")


def test_create_batch_zero_card_count_rejected(api):
    """PRD §2.11: "body well-formedness — required fields present, enums valid, amounts positive integers, `card_count` at least 1 — yielding `ERR_VALIDATION` (HTTP 400)"

    Design: Corner/entities/create_batch_zero_card_count_returns_validation
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    admin = make_merchant_admin_headers(merchant["id"])
    res = api.create_card_batch(
        create_card_batch_payload(program["id"], 0, 5000), admin)
    validate_error(res, "ERR_VALIDATION")


def test_minted_card_starts_inactive_zero_balance(api):
    """PRD §3.3: "on commit the system mints `card_count` `GiftCard` rows, each in `INACTIVE` status, each with `initial_load_cents` set to the batch's `unit_load_cents` and `channel` inherited from the batch"
    PRD §3.3: "a system-minted `card_number` that is unique across all cards"
    PRD §2.7: "A card's `balance_cents` is defined as the sum of `amount_cents` over that card's ledger entries whose `status` is `POSTED`"

    Design: Corner/entities/minted_card_starts_inactive_zero_balance
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    batch = commit_batch(merchant["id"], program["id"], 1, 5000, channel="PHYSICAL")
    cards = get_batch_cards(batch["id"])
    assert len(cards) == 1
    card = cards[0]
    assert_gift_card(card)
    assert card["status"] == "INACTIVE"
    assert card["balance_cents"] == 0
    assert isinstance(card["card_number"], str) and card["card_number"]


def test_reactivate_pending_merchant_rejected(api):
    """PRD §3.1: "reactivation returns a `SUSPENDED` merchant to `ACTIVE` (only from `SUSPENDED`, else `ERR_INVALID_STATE`) — this suspend/reactivate pair is the merchant's revert cycle."

    Design: Corner/state_machines/reactivate_pending_merchant_returns_invalid_state
    """
    merchant = validate_success(
        api.create_merchant(create_merchant_payload(), PLATFORM), 201)
    res = api.reactivate_merchant(merchant["id"], PLATFORM)
    validate_error(res, "ERR_INVALID_STATE")


def test_activate_retired_program_rejected(api):
    """PRD §3.2: "Activation moves it from `DRAFT` to `ACTIVE`, permitted only while `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning merchant is `ACTIVE`"
    PRD §3.2: "Retirement moves a program from `ACTIVE` or `PAUSED` to the terminal `RETIRED` state (permitted only from `ACTIVE` or `PAUSED`, else `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/activate_retired_program_returns_invalid_state
    """
    merchant = create_active_merchant()
    admin = make_merchant_admin_headers(merchant["id"])
    program = create_active_program(merchant["id"])
    validate_success(api.retire_card_program(program["id"], admin), 200)
    res = api.activate_card_program(program["id"], admin)
    validate_error(res, "ERR_INVALID_STATE")


def test_commit_already_committed_batch_rejected(api):
    """PRD §3.3: "The commit is permitted only while the batch is `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`)"

    Design: Corner/state_machines/commit_already_committed_batch_returns_invalid_state
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    admin = make_merchant_admin_headers(merchant["id"])
    batch = commit_batch(merchant["id"], program["id"], 1, 5000)
    res = api.commit_card_batch(batch["id"], admin)
    validate_error(res, "ERR_INVALID_STATE")


def test_commit_batch_on_draft_program_rejected(api):
    """PRD §3.3: "The commit is permitted only while the batch is `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`)"

    Design: Corner/state_machines/commit_batch_program_not_active_returns_program_not_active
    """
    merchant = create_active_merchant()
    program = create_draft_program(merchant["id"])  # never activated
    admin = make_merchant_admin_headers(merchant["id"])
    batch = validate_success(
        api.create_card_batch(create_card_batch_payload(program["id"], 1, 5000), admin), 201)
    res = api.commit_card_batch(batch["id"], admin)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")


def test_redeem_inactive_card_rejected(api):
    """PRD §3.4: "The redemption path evaluates its guards in this order: first the card must itself be `ACTIVE` — an `INACTIVE`, `SUSPENDED`, `EXPIRED`, `ESCHEATED`, or `CLOSED` card is rejected with `ERR_CARD_NOT_ACTIVE`"

    Design: Corner/state_machines/redeem_inactive_card_returns_card_not_active
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    batch = commit_batch(merchant["id"], program["id"], 1, 5000)
    card = get_batch_cards(batch["id"])[0]
    assert card["status"] == "INACTIVE"
    res = api.redeem_gift_card(card["id"], {"amount_cents": 1000}, TEST_USERS["pos_terminal_headers"])
    validate_error(res, "ERR_CARD_NOT_ACTIVE")
