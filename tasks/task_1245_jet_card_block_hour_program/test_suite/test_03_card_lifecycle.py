"""JetCard lifecycle: suspend/resume cycle, expiration sweep, terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_card,
    create_member,
    create_program,
    expire_card_via_sweep,
    get_card,
    purchase_card,
    resume_card,
    set_clock,
    setup_active_card,
    suspend_card,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


def test_card_suspend_resume_cycle_status(api):
    """PRD §3.3: "Suspension and resume are lightweight `Ops` actions that move the card
    between `ACTIVE` and `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/jet_card_active_suspended_active_cycle
    """
    _, _, card = setup_active_card(program_overrides={"program_code": "CYC1"})
    suspend_card(card["id"])
    resume_card(card["id"])
    suspend_card(card["id"])
    final = get_card(card["id"])
    assert final["card_status"] == "SUSPENDED", (
        f"after suspend->resume->suspend the card must be SUSPENDED, got {final['card_status']}"
    )


def test_card_suspend_resume_cycle_version_increments(api):
    """PRD §3.3: "Every transition increments the card's `version`."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by 1 on
    every mutation of that resource."

    Design: Difficulty/non_linear_state_machine/jet_card_active_suspended_active_cycle
    """
    _, _, card = setup_active_card(program_overrides={"program_code": "CYC1V"})
    # create = v1, activate = v2 (per fixture: purchase then activate).
    assert card["version"] == 2, f"post-activation version must be 2, got {card['version']}"
    suspend_card(card["id"])
    resume_card(card["id"])
    final = suspend_card(card["id"])
    assert final["version"] == 5, (
        f"create(1)+activate(2)+suspend(3)+resume(4)+suspend(5) must give version 5, "
        f"got {final['version']}"
    )


def test_card_terminal_state_lockdown_expired(api):
    """PRD §3.3: "Suspension and resume are lightweight `Ops` actions that move the card
    between `ACTIVE` and `SUSPENDED`." — a card in `EXPIRED` is in neither from-state.
    PRD §2.11: "Only after all four pass do state guards run — card-active
    (`ERR_CARD_NOT_ACTIVE`), member-active (`ERR_MEMBER_NOT_ACTIVE`), and from-state
    validity (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/card_terminal_state_lockdown_expired
    """
    _, _, card = setup_active_card(
        program_overrides={"program_code": "SM2", "expiry_months": 1}
    )
    expired = expire_card_via_sweep(card["id"], "2026-08-01T00:00:00Z")
    assert expired["card_status"] == "EXPIRED"
    resp = api.suspend_card(card["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_card(card["id"])
    assert after["card_status"] == "EXPIRED", (
        f"rejected suspend must leave the card EXPIRED, got {after['card_status']}"
    )


def test_ops_run_sweeps_expired_cards(api):
    """PRD §3.9: "When the sweep finds an `ACTIVE` card whose `expires_at` is at or before
    the current logical time, the card's balance decides its fate. A card whose
    `hours_remaining` is still positive transitions to `EXPIRED`: an `EXPIRATION_DEBIT`
    ledger entry is inserted for the negative of the remaining hours, the escrow's
    `forfeited_cents` increases by the full `escrow_balance_cents` while `available_cents`
    drops to zero, and the card's `hours_expired` reflects the lapsed quantity."

    Design: Corner/endpoints/ops_run_sweeps_expired_cards
    """
    _, _, card = setup_active_card(
        program_overrides={"program_code": "EP2", "expiry_months": 1}
    )
    swept = expire_card_via_sweep(card["id"], "2026-08-01T00:00:00Z")
    assert swept["card_status"] == "EXPIRED", (
        f"card past expires_at with positive balance must be EXPIRED, got {swept['card_status']}"
    )
    assert swept["hours_expired"] == pytest.approx(25.0, abs=0.005), (
        f"all 25 unused hours must lapse, got hours_expired={swept['hours_expired']}"
    )
    assert swept["hours_remaining"] == pytest.approx(0.0, abs=0.005), (
        f"hours_remaining must be 0 after the expiration debit, got {swept['hours_remaining']}"
    )


def test_list_cards_filtered_by_status(api):
    """PRD §3.3: "Both `Ops` and the owning `Member` can read a card, list a member's
    cards (optionally filtered by `card_status`), and page through the card's ledger
    entries with an optional `entry_kind` filter."

    Design: Corner/endpoints/list_cards_filtered_by_status
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "EP1"})
    resp = api.list_member_cards(member["id"], OPS, params={"card_status": "ACTIVE"})
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "expected at least the activated card"
    first = data[0]
    assert first["id"] == card["id"], f"expected card {card['id']}, got {first['id']}"
    assert first["card_status"] == "ACTIVE"
    for item in data:
        assert item["card_status"] == "ACTIVE", (
            f"card_status=ACTIVE filter must return only ACTIVE cards, got {item['card_status']}"
        )
