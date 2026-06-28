"""Account creation, input validation, existence and authentication.

Covers corner queue (entities, validations, rbac/auth) instances rooted in PRD Sections 3.2,
2.9, 2.1.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_family_with_child, create_family,
)
from test_helpers.factories import create_chore_payload, create_child_payload


# ─── corner entities: child creation auto-creates jars / card / config ──────
def test_create_child_auto_creates_three_jars_and_card(api):
    """PRD 3.2: "Creating a child is a generative act: the server simultaneously creates exactly three jars, exactly one debit card, and exactly one interest-match configuration. The three jars are one each of `jar_type` `SPEND`, `SAVE`, and `GIVE`, each linked to the child through `child_account_id`."
    PRD 3.2: "The debit card created alongside the child begins `UNLOCKED` and `DRAINED`, and the interest-match configuration begins disabled until a parent configures it."

    Design: Corner/entities/create_child_account_auto_creates_jars_card_config
    """
    fam, parent_headers = create_family(deposit_cents=0)
    child = validate_success(api.create_child_account(
        fam["id"], create_child_payload(display_name="Kid", birthdate="2015-01-01"), parent_headers), 201)
    assert child["status"] == "ACTIVE"

    jars = validate_success(api.list_jars(child["id"], parent_headers), 200)
    assert len(jars) == 3
    assert {j["jar_type"] for j in jars} == {"SPEND", "SAVE", "GIVE"}

    cards = validate_success(api.list_debit_cards(child["id"], parent_headers), 200)
    assert len(cards) == 1
    assert cards[0]["lock_state"] == "UNLOCKED"
    assert cards[0]["funding_state"] == "DRAINED"


# ─── corner validations: missing required field ─────────────────────────────
def test_create_chore_missing_reward_cents_returns_invalid_request(api):
    """PRD 2.9: "Then the request body is checked for well-formedness — required fields present, enum members recognized, JSON types correct (`ERR_INVALID_REQUEST`) — before semantic field bounds are checked on an otherwise well-formed body (`ERR_VALIDATION`)"
    PRD 3.3: "A parent creates a `Chore` for a child by supplying a `title` and a `reward_cents"

    Design: Corner/entities/create_chore_missing_reward_cents_returns_invalid_request
    """
    fam, child, ph = setup_family_with_child(deposit_cents=0)
    payload = create_chore_payload(title="NoReward")
    del payload["reward_cents"]

    res = api.create_chore(child["id"], payload, ph)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── corner validations: field bound (reward_cents > 0) ─────────────────────
def test_chore_reward_cents_zero_returns_validation(api):
    """PRD 3.3: "The `reward_cents` is the amount paid on approval and must be greater than zero."
    PRD 2.9: "the bound checks require that `amount_cents`, `reward_cents`, `shares_milli`, and `price_cents_per_share` are greater than zero"

    A well-formed body with reward_cents=0 violates the >0 bound, surfacing ERR_VALIDATION (not the
    well-formedness error).

    Design: Corner/entities/chore_reward_cents_zero_returns_validation
    """
    fam, child, ph = setup_family_with_child(deposit_cents=0)

    res = api.create_chore(child["id"], create_chore_payload(title="Free", reward_cents=0), ph)
    validate_error(res, "ERR_VALIDATION")


# ─── corner existence: not found ────────────────────────────────────────────
def test_get_nonexistent_child_account_returns_not_found(api):
    """PRD 2.9: "Existence of every resource named in the path is verified next, left to right (`ERR_NOT_FOUND`)."

    Design: Corner/entities/get_child_account_nonexistent_returns_not_found
    """
    fam, parent_headers = create_family(deposit_cents=0)

    res = api.get_child_account("00000000-0000-4000-8000-000000000000", parent_headers)
    validate_error(res, "ERR_NOT_FOUND")


# ─── corner auth: missing authentication headers ────────────────────────────
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED`."
    PRD 2.9: "Authentication comes first: the presence and recognition of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`) is checked before anything else, and this applies to every endpoint except family registration."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    fam, parent_headers = create_family(deposit_cents=0)

    res = api.get_family(fam["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
