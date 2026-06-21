"""Entity CRUD, defaults, computed fields, immutability, and listing.

Queue B (Corner) section entities.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_program, issue_card,
    create_program_payload, create_card_payload, create_state_rule_payload,
    assert_program, assert_gift_card, assert_ledger_entry,
    TEST_USERS, NON_EXISTENT_UUID,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]


def test_create_program_applies_defaults(api):
    """PRD §3.1: "the reload_min_cents floor that every load and reload must meet (default
    500 cents, i.e. five dollars); the reload_max_balance_cents ceiling that a card's settled
    balance may never exceed after any credit (default 100000 cents, i.e. one thousand
    dollars)."
    PRD §3.1: "the default_currency (an ISO currency code, defaulting to USD ...)."

    Design: Corner/entities/create_program_returns_201_with_defaults
    """
    res = api.create_program(create_program_payload(name="Acme"), _ADMIN)
    prog = validate_success(res, 201)
    assert_program(prog)
    assert prog["reload_min_cents"] == 500
    assert prog["reload_max_balance_cents"] == 100000
    assert prog["default_currency"] == "USD"
    assert prog["version"] == 1


def test_get_card_not_found(api):
    """PRD §2.10: "any id named in the path that does not resolve to an existing resource
    yields ERR_NOT_FOUND before the body is examined."

    Design: Corner/entities/get_card_not_found_returns_404
    """
    res = api.get_card(NON_EXISTENT_UUID, _STORE)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_state_rule_missing_breakage_policy_rejected(api):
    """PRD §2.11: "the body is checked for well-formedness — required fields present, correct
    types, and valid enum members — yielding ERR_VALIDATION."
    PRD §3.1: "Each rule sets expiration_allowed ..., dormancy_fee_allowed ..., and a
    breakage_policy of either RECOGNIZE or ESCHEAT."

    Design: Corner/entities/create_state_rule_missing_breakage_policy_returns_validation
    """
    program = create_program()
    # Omit breakage_policy entirely.
    payload = {"program_id": program["id"], "state_code": "FL",
               "expiration_allowed": True, "dormancy_fee_allowed": False}
    res = api.create_state_rule(payload, _ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_freshly_issued_card_has_zero_balance_and_initial_states(api):
    """PRD §3.2: "A freshly issued card has lifecycle_status of INACTIVE and risk_status of
    CLEAR, with no value on it yet."
    PRD §2.5: "A card's money position is never stored directly; it is recomputed from the
    ledger on every read of the GiftCard."

    Design: Corner/entities/card_computed_balance_ignores_input_value
    """
    program = create_program()
    card = validate_success(
        api.create_card(create_card_payload(program["id"]), _STORE), 201)
    assert_gift_card(card)
    assert card["lifecycle_status"] == "INACTIVE"
    assert card["risk_status"] == "CLEAR"
    assert card["settled_balance_cents"] == 0
    assert card["available_balance_cents"] == 0


def test_create_card_invalid_form_factor_rejected(api):
    """PRD §2.11: "the body is checked for well-formedness — required fields present, correct
    types, and valid enum members — yielding ERR_VALIDATION."
    PRD §3.2: "Issuance records the program_id, the form_factor (either DIGITAL or
    PHYSICAL) ..."

    Design: Corner/entities/create_card_invalid_form_factor_enum_rejected
    """
    program = create_program()
    payload = create_card_payload(program["id"], form_factor="PLASTIC")
    res = api.create_card(payload, _STORE)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_load_ledger_entry_is_immutable_audit_record(api):
    """PRD §2.4: "a LedgerEntry and a RedemptionLeg are immutable audit records, so each
    carries only an id and a created_at — neither has an updated_at and neither has a
    version."
    PRD §3.3: "the system appends a LOAD credit whose amount equals the initial load."

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    program = create_program()
    card = issue_card(program["id"])
    get_success_data(api.activate_card(card["id"], {"initial_load_cents": 4000}, _STORE))
    data, meta = validate_paginated(
        api.list_ledger_entries(_STORE, params={"card_id": card["id"], "entry_type": "LOAD"}))
    assert len(data) == 1, "exactly one LOAD entry"
    entry = data[0]
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "LOAD"
    assert entry["amount_cents"] == 4000


def test_list_cards_paginated_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and has_more in the
    meta object of the envelope."

    Design: Corner/entities/list_cards_paginated_envelope
    """
    program = create_program()
    issue_card(program["id"], form_factor="DIGITAL")
    issue_card(program["id"], form_factor="PHYSICAL")
    data, meta = validate_paginated(
        api.list_cards(_ADMIN, params={"program_id": program["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
