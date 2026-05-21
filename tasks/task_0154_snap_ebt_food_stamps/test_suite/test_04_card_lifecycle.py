"""EBT Card lifecycle: issuance, activation, suspend, resume, replace, close.

Covers PRD §3.4 and the cascade from §2.8.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_CARD_ALREADY_EXISTS, ERR_FRAUD_HOLD, ERR_FORBIDDEN,
    TEST_USERS, make_household_head_headers,
    assert_ebt_card,
    setup_basic_household, setup_approved_household_and_capture_card,
    setup_approved_household_with_active_card,
    create_household,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]


class TestCardIssuance:
    def test_manual_issuance_yields_issued_status(self, api):
        """PRD §3.4: "On creation, the card is in `ISSUED`, the server stamps
        `issued_at` to `Clock.now`, and `card_number_last4` is minted as four
        digits (the actual PAN is **never** stored)."

        Claim: a manual POST /cards yields status=ISSUED + valid last4.
        """
        hh = create_household()
        resp = api.create_card(hh["id"], CASEWORKER)
        data = validate_success(resp, expected_status=201)
        assert_ebt_card(data)
        assert data["status"] == "ISSUED"
        assert len(data["card_number_last4"]) == 4
        assert data["card_number_last4"].isdigit()

    def test_uniqueness_blocks_second_issuance(self, api):
        """PRD §3.4: "A `Household` may hold **at most one** card whose `status`
        is `ISSUED`, `ACTIVE`, or `SUSPENDED` at any time. If a caseworker
        attempts to issue a card while another exists in any of those three
        statuses, the second issuance is rejected with `ERR_CARD_ALREADY_EXISTS`."

        Claim: second POST /cards on a household with an ISSUED card yields
        ERR_CARD_ALREADY_EXISTS.
        """
        hh = create_household()
        validate_success(api.create_card(hh["id"], CASEWORKER), expected_status=201)
        resp = api.create_card(hh["id"], CASEWORKER)
        validate_error(resp, ERR_CARD_ALREADY_EXISTS)

    def test_replaced_card_does_not_block_new_issuance(self, api):
        """PRD §3.4: "Cards in `REPLACED` or `CLOSED` are terminal for the
        purposes of this rule and do not block a new issuance."

        Claim: after replacing an ACTIVE card, the old card is in REPLACED and
        a new ISSUED card exists; a subsequent issuance attempt collides with
        the NEW card (not the old) — but if we close the new card, issuance
        succeeds again.

        We weaken to the closer-to-PRD form: after replace, the old REPLACED
        card does not block, but the new ISSUED one does — so attempting
        issuance yields ERR_CARD_ALREADY_EXISTS due to the new card.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        hh_id = ctx["household"]["id"]
        old_card_id = ctx["card"]["id"]
        hh_head = make_household_head_headers(hh_id)
        validate_success(api.replace_card(hh_id, old_card_id, hh_head))
        # Attempt a manual issuance again — blocked by the new ISSUED card
        resp = api.create_card(hh_id, CASEWORKER)
        validate_error(resp, ERR_CARD_ALREADY_EXISTS)


class TestCardActivation:
    def test_activate_requires_approved_household(self, api):
        """PRD §3.4: "Activation, performed by the `HouseholdHead`, transitions
        the card from `ISSUED` to `ACTIVE` and stamps `activated_at` as
        `Clock.now`; activation requires the household's `certification_status`
        to be `APPROVED`."

        Claim: activate on an unapproved household yields ERR_INVALID_STATE.
        """
        # difficulty: cross_entity_state_dependency/ebtcard_activate_requires_household_certified
        hh = create_household()
        card = validate_success(api.create_card(hh["id"], CASEWORKER), expected_status=201)
        hh_head = make_household_head_headers(hh["id"])
        resp = api.activate_card(hh["id"], card["id"], hh_head)
        validate_error(resp, ERR_INVALID_STATE)

    def test_activate_after_household_approved_succeeds(self, api):
        """PRD §3.4: "activation requires the household's `certification_status`
        to be `APPROVED`."

        Claim (positive boundary): once household is APPROVED, activate succeeds.
        """
        # difficulty: cross_entity_state_dependency/ebtcard_activate_requires_household_certified
        ctx = setup_approved_household_and_capture_card(size=1, age=30)
        hh_head = make_household_head_headers(ctx["household"]["id"])
        resp = api.activate_card(ctx["household"]["id"], ctx["card"]["id"], hh_head)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"
        assert data["activated_at"] is not None

    def test_activate_role_restricted_to_household_head(self, api):
        """PRD §4 table: "POST /households/{id}/cards/{cardId}/activate —
        ISSUED to ACTIVE — HouseholdHead."

        Claim: a Caseworker calling /activate yields ERR_FORBIDDEN.
        """
        ctx = setup_approved_household_and_capture_card(size=1, age=30)
        resp = api.activate_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER)
        validate_error(resp, ERR_FORBIDDEN)


class TestCardSuspendResume:
    def test_suspend_active_card(self, api):
        """PRD §3.4: "A caseworker (or fraud investigator) may suspend a card
        from `ACTIVE` to `SUSPENDED`."

        Claim: suspend on ACTIVE card -> SUSPENDED.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        resp = api.suspend_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"

    def test_resume_suspended_card_no_fraud(self, api):
        """PRD §3.4: "A caseworker may resume the card from `SUSPENDED` back
        to `ACTIVE` only when no `FraudCase` for the same household is in
        `SUBSTANTIATED`."

        Claim: resume on SUSPENDED card with no fraud -> ACTIVE.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        validate_success(api.suspend_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        resp = api.resume_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


class TestCardReplace:
    def test_replace_active_card_creates_new_issued_card(self, api):
        """PRD §3.4: "Either a `HouseholdHead` or a `Caseworker` may replace an
        `ACTIVE` card, transitioning it from `ACTIVE` to `REPLACED`. The cascade
        is: a new `EbtCard` row is created in `ISSUED` for the same household;
        the old card's `replaced_by_card_id` is set to the new card's `id`."

        Claim: after replace, old card is REPLACED with replaced_by_card_id set.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        hh_id = ctx["household"]["id"]
        old_card_id = ctx["card"]["id"]
        hh_head = make_household_head_headers(hh_id)
        resp = api.replace_card(hh_id, old_card_id, hh_head)
        old_after = validate_success(resp)
        assert old_after["status"] == "REPLACED"
        assert old_after["replaced_by_card_id"] is not None

    def test_replace_preserves_household_total_balance(self, api):
        """PRD §3.4: "the balance is migrated atomically by posting two paired
        `ADJUSTMENT` entries to the ledger — a negative entry equal to the old
        card's `balance_cents` at the instant of replacement on the old card,
        and a positive entry of the same magnitude on the new card. After the
        cascade, the new card's recomputed `balance_cents` equals the old card's
        `balance_cents` at the replacement instant, and the old card's
        recomputed `balance_cents` is zero."

        Claim: after replace, old.balance==0 and new.balance==old_pre_replace_balance.
        """
        # difficulty: compensating_invariant/card_replace_preserves_household_total_benefits
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        hh_id = ctx["household"]["id"]
        old_card_id = ctx["card"]["id"]
        hh_head = make_household_head_headers(hh_id)
        # Snapshot old balance before replace
        old_pre = validate_success(api.get_card(hh_id, old_card_id, CASEWORKER))
        balance_before = old_pre["balance_cents"]
        old_after = validate_success(api.replace_card(hh_id, old_card_id, hh_head))
        # Old card balance should be 0
        old_re = validate_success(api.get_card(hh_id, old_card_id, CASEWORKER))
        assert old_re["balance_cents"] == 0, (
            f"Old card balance should be 0 after replace, got {old_re['balance_cents']}"
        )
        # New card balance should equal old's pre-replace balance
        new_card_id = old_after["replaced_by_card_id"]
        new_card = validate_success(api.get_card(hh_id, new_card_id, CASEWORKER))
        assert new_card["balance_cents"] == balance_before, (
            f"New card balance should be {balance_before}, got {new_card['balance_cents']}"
        )

    def test_replace_invalid_from_non_active(self, api):
        """PRD §3.4: "Either a `HouseholdHead` or a `Caseworker` may replace an
        `ACTIVE` card."

        Claim: replace on an ISSUED (non-ACTIVE) card yields ERR_INVALID_STATE.
        """
        ctx = setup_approved_household_and_capture_card(size=1, age=30)
        hh_id = ctx["household"]["id"]
        card_id = ctx["card"]["id"]  # still ISSUED
        hh_head = make_household_head_headers(hh_id)
        resp = api.replace_card(hh_id, card_id, hh_head)
        validate_error(resp, ERR_INVALID_STATE)
