"""Card loss, theft, replacement, expiry, and the fraud escalation cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_card,
    create_grant,
    create_holder,
    create_provisional_card,
    create_verified_card,
    create_zone,
    fund_account,
    get_success_data,
    issue_card,
    make_cardholder_headers,
    open_account,
    replace_card,
    report_card_lost,
    report_card_stolen,
    review_photo,
    set_clock,
    submit_photo,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["card_office_admin_headers"]
BURSAR = TEST_USERS["bursar_headers"]
SECURITY = TEST_USERS["security_officer_headers"]
POS = TEST_USERS["pos_headers"]


class TestTerminalCardLockdown:
    def test_terminal_card_rejects_all_actions(self, api):
        """PRD §2.10: "**State transition legality** — the target resource's state
        permits the requested transition, including terminal-state lockout,
        invalid-from rejection, and any state-machine precondition, else
        `ERR_INVALID_STATE_TRANSITION` (409)."
        PRD §3.2: "a `CardOfficeAdmin` or `FraudAnalyst` may permanently deactivate
        any non-terminal card (`PENDING_PHOTO`, `ACTIVE`, `LOST_FROZEN`, or
        `STOLEN_FROZEN` → `DEACTIVATED`)"

        Design: Corner/state_machines/terminal_card_rejects_all_actions
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card = create_holder_with_provisional(
            university_id="U90010", full_name="Joss Term", email="joss@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        replace_card(card, "LOST")

        err1 = api.report_card_lost(card["id"],
                                    make_cardholder_headers(holder["id"]))
        validate_error(err1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        err2 = api.deactivate_card(card["id"], ADMIN)
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestStolenCardRecovery:
    def test_stolen_card_cannot_unfreeze(self, api):
        """PRD §3.2: "Unfreezing is defined only for a lost-frozen card —
        attempting it on a `STOLEN_FROZEN` card or any terminal card is rejected
        with `ERR_CARD_NOT_RECOVERABLE`."

        Design: Corner/state_machines/stolen_card_cannot_unfreeze
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card = create_holder_with_provisional(
            university_id="U90011", full_name="Kai Stolen", email="kai@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        report_card_stolen(card["id"], holder["id"])

        resp = api.unfreeze_card(card["id"], make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_RECOVERABLE)
        still = get_success_data(api.get_card(card["id"], ADMIN))
        assert still["lifecycle_status"] == "STOLEN_FROZEN"


class TestCardExpiry:
    def test_card_expires_on_first_use_past_expiry(self, api):
        """PRD §3.2: "a card whose `expires_at` has passed expires lazily: the
        first transaction or access attempt that touches it with the clock at or
        after `expires_at` flips it `ACTIVE` → `EXPIRED`, the triggering
        transaction fails with `ERR_CARD_NOT_ACTIVE`"

        Design: Corner/state_machines/card_expires_on_first_use_past_expiry
        """
        set_clock("2026-08-25T09:00:00Z")
        h2, c2 = create_holder_with_verified(
            university_id="U90018", full_name="Sara Expire", email="sara@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS",
            expires_at="2026-08-30T00:00:00Z")
        a2 = open_account(h2["id"], "CAMPUS_CASH")
        fund_account(a2["id"], 5000)
        set_clock("2026-08-31T09:00:00Z")

        resp = api.create_transaction(
            {"card_id": c2["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 100, "idempotency_key": "sara-t"}, POS)
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE)
        after = get_success_data(api.get_card(c2["id"], ADMIN))
        assert after["lifecycle_status"] == "EXPIRED"


class TestReplacementFees:
    def test_replacement_fee_waiver_variants(self, api):
        """PRD §3.2: "(1) a `FACULTY` or `STAFF` holder's first replacement is
        free — fee 0 — though the ordinal is still consumed; (2) a `STOLEN`
        replacement with a police report — either recorded as the old card's
        `stolen_police_report_number` or supplied on the replacement payload — is
        free"
        PRD §3.4: "A grant of zero posts no entry at all — ledger entries always
        carry a strictly positive `amount_cents`."

        Design: Corner/calculations/replacement_fee_waiver_variants
        """
        set_clock("2026-08-25T09:00:00Z")
        # FACULTY first replacement: free.
        faculty, fcard = create_holder_with_provisional(
            university_id="U91009", full_name="Prof Fay", email="prof@x.edu",
            holder_type="FACULTY", housing_status="OFF_CAMPUS")
        f_new = replace_card(fcard, "LOST")
        assert f_new["replacement_fee_cents"] == 0

        # No FEE entry and no auto-created CAMPUS_CASH account for a zero fee.
        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": faculty["id"],
                                       "account_type": "CAMPUS_CASH"}))
        assert accounts == []

        # STUDENT ordinal 2, STOLEN with police report: free.
        student, scard1 = create_holder_with_provisional(
            university_id="U91010", full_name="Stu Steve", email="steve@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        scard2 = replace_card(scard1, "LOST")  # ordinal 1, fee 2500
        activate_card(scard2["id"], allow_provisional=True)
        report_card_stolen(scard2["id"], student["id"],
                           police_report_number="PR-99")
        scard3 = replace_card(scard2, "STOLEN")
        assert scard3["replacement_fee_cents"] == 0

    def test_replacement_fee_tier_surcharge_surrender_amounts(self, api):
        """PRD §3.2: "the base tier fee is 2500 cents for the first replacement,
        3500 cents for the second, and 5000 cents for the third and every
        subsequent one. The rules apply in strict order: ... (3) a `STOLEN`
        replacement without a police report costs double the tier fee (a surcharge
        multiplier of 2); (4) a `DAMAGED` replacement with `surrendered` true costs
        the tier fee less a 1500-cent surrender discount, floored at 0; (5) every
        other case — `LOST`, or `DAMAGED` without surrender — pays the tier fee."

        Design: Difficulty/combinatorial_formula/replacement_fee_tier_surcharge_surrender_interaction
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, c1 = create_holder_with_provisional(
            university_id="U3001", full_name="Cara Resident", email="cara@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        report_card_lost(c1["id"], holder["id"])
        c2 = replace_card(c1, "LOST")
        assert c2["replacement_fee_cents"] == 2500  # ordinal 1, LOST

        activate_card(c2["id"], allow_provisional=True)
        report_card_stolen(c2["id"], holder["id"])  # no police report
        c3 = replace_card(c2, "STOLEN")
        assert c3["replacement_fee_cents"] == 7000  # ordinal 2, 3500 x 2

        activate_card(c3["id"], allow_provisional=True)
        c4 = replace_card(c3, "DAMAGED", surrendered=True)
        assert c4["replacement_fee_cents"] == 3500  # ordinal 3, max(0, 5000-1500)

    def test_replacement_fees_post_to_campus_cash_and_may_go_negative(self, api):
        """PRD §3.2: "The fee posts as a `FEE` ledger entry to the holder's
        `CAMPUS_CASH` account, which is auto-created `OPEN` when none exists, and
        a `FEE` entry is one of the few entry types permitted to drive a balance
        negative."
        PRD §3.2: "First, the holder's `fraud_strike_count` increments by 1." (of
        the stolen-report cascade; lost reports and replacements add no strikes)

        Design: Difficulty/combinatorial_formula/replacement_fee_tier_surcharge_surrender_interaction
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, c1 = create_holder_with_provisional(
            university_id="U3001", full_name="Cara Resident", email="cara@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        report_card_lost(c1["id"], holder["id"])
        c2 = replace_card(c1, "LOST")                    # 2500
        activate_card(c2["id"], allow_provisional=True)
        report_card_stolen(c2["id"], holder["id"])
        c3 = replace_card(c2, "STOLEN")                  # 7000
        activate_card(c3["id"], allow_provisional=True)
        replace_card(c3, "DAMAGED", surrendered=True)    # 3500

        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": holder["id"],
                                       "account_type": "CAMPUS_CASH"}))
        assert len(accounts) == 1
        assert accounts[0]["balance_cents"] == -13000

        holder_now = get_success_data(api.get_card_holder(holder["id"], ADMIN))
        assert holder_now["fraud_strike_count"] == 1


class TestFraudEscalation:
    def test_two_strikes_do_not_suspend(self, api):
        """PRD §3.2: "Second, when the count reaches or exceeds the suspension
        threshold of **3 strikes** — the boundary is inclusive, so exactly the
        third strike suspends — the holder's `status` flips to `SUSPENDED` and
        `fraud_flag` is set true."

        Design: Corner/calculations/two_strikes_do_not_suspend
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, c1 = create_holder_with_provisional(
            university_id="U91012", full_name="Gia Strikes", email="gia@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        report_card_stolen(c1["id"], holder["id"], police_report_number="PR-A")
        c2 = replace_card(c1, "STOLEN", police_report_number="PR-A")
        activate_card(c2["id"], allow_provisional=True)
        report_card_stolen(c2["id"], holder["id"], police_report_number="PR-B")

        holder_now = get_success_data(api.get_card_holder(holder["id"], ADMIN))
        assert holder_now["fraud_strike_count"] == 2
        assert holder_now["status"] == "ACTIVE"
        assert holder_now["fraud_flag"] is False

    def test_stolen_report_third_strike_suspends_holder(self, api):
        """PRD §3.2: "Second, when the count reaches or exceeds the suspension
        threshold of **3 strikes** — the boundary is inclusive, so exactly the
        third strike suspends — the holder's `status` flips to `SUSPENDED` and
        `fraud_flag` is set true."

        Design: Difficulty/transitive_cascade/stolen_report_four_link_cascade
        """
        holder, c3, account, grant = _setup_two_strikes_then_third(api)
        holder_now = get_success_data(api.get_card_holder(holder["id"], ADMIN))
        assert holder_now["fraud_strike_count"] == 3
        assert holder_now["status"] == "SUSPENDED"
        assert holder_now["fraud_flag"] is True

    def test_stolen_report_suspension_cascades_to_cards_accounts_grants(self, api):
        """PRD §3.2: "Third, that suspension freezes every `OPEN`
        declining-balance account of the holder with `frozen_reason`
        `HOLDER_SUSPENDED` and deactivates the holder's remaining non-terminal
        cards, revoking each such card's grants."
        PRD §3.2: "Fourth, independently of the strike count, the holder's `OPEN`
        accounts are frozen with `frozen_reason` `CARD_STOLEN` (an account already
        `FROZEN` stays as it is)."

        Design: Difficulty/transitive_cascade/stolen_report_four_link_cascade
        """
        holder, c3, account, grant = _setup_two_strikes_then_third(api)
        # The reported card itself stays STOLEN_FROZEN; the suspension cascade
        # deactivates only the holder's *remaining* non-terminal cards (PRD
        # §3.2), and a holder may hold at most one non-terminal card, so c3 is
        # never deactivated here. Its grant is suspended CARD_FROZEN by the
        # stolen report, not revoked.
        card_now = get_success_data(api.get_card(c3["id"], ADMIN))
        assert card_now["lifecycle_status"] == "STOLEN_FROZEN"
        account_now = get_success_data(api.get_account(account["id"], BURSAR))
        assert account_now["status"] == "FROZEN"
        grant_now = get_success_data(api.get_access_grant(grant["id"], SECURITY))
        assert grant_now["status"] == "SUSPENDED"
        assert grant_now["suspended_reason"] == "CARD_FROZEN"


class TestReplacementOptimisticConcurrency:
    def test_occ_replacement_stale_after_photo_review(self, api):
        """PRD §2.9: "Issuing a card replacement requires `expected_card_version`
        matching the card's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412), because an intervening photo review or
        lost/stolen report may have changed the fraud-relevant state the fee
        schedule depends on."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by exactly 1 on every mutation of the resource, and that underpins
        optimistic concurrency control where declared."

        Design: Corner/complexity_layers/occ_replacement_stale_after_photo_review
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U95003", full_name="Gil Repl",
                               email="gil@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        activated = activate_card(card["id"], allow_provisional=True)
        stale_version = activated["version"]
        photo = submit_photo(card["id"], holder["id"], image_ref="img://gil")
        review_photo(photo["id"], decision="APPROVED")

        stale = api.replace_card(
            card["id"], {"reason": "LOST",
                         "expected_card_version": stale_version}, ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        still = get_success_data(api.get_card(card["id"], ADMIN))
        assert still["lifecycle_status"] == "ACTIVE"

        fresh_version = still["version"]
        assert fresh_version == stale_version + 2
        new_card = replace_card(card, "LOST")
        assert new_card["replacement_fee_cents"] == 2500


class TestSingleActiveCardInvariant:
    def test_second_direct_issuance_rejected(self, api):
        """PRD §3.1: "A holder may possess **at most one non-terminal card** at
        any time: issuing while the holder already holds a card that is not
        `REPLACED`, `EXPIRED`, or `DEACTIVATED` is rejected with
        `ERR_ACTIVE_CARD_EXISTS`."

        Design: Difficulty/compensating_invariant/replacement_single_active_card_conservation
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card = create_holder_with_verified(
            university_id="U10003", full_name="Uma Resident", email="uma@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        resp = api.issue_card(holder["id"], {"expires_at": "2027-08-24T00:00:00Z"},
                              ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CARD_EXISTS)

    def test_replacement_mints_successor_and_retires_predecessor(self, api):
        """PRD §3.2: "The old card becomes `REPLACED`, its `replaced_by_card_id`
        points at the new card, and every grant of the old card in `ACTIVE` or
        `SUSPENDED` is `REVOKED` ... if the old card's `photo_status` was
        `APPROVED`, the successor is created already `ACTIVE` with
        `is_provisional` false; otherwise it starts at `PENDING_PHOTO` with
        `photo_status` `NOT_SUBMITTED`."

        Design: Difficulty/compensating_invariant/replacement_single_active_card_conservation
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card = create_holder_with_verified(
            university_id="U10003", full_name="Uma Resident", email="uma@x.edu",
            holder_type="STUDENT_RESIDENT", housing_status="ON_CAMPUS")
        new_card = replace_card(card, "LOST")
        assert new_card["lifecycle_status"] == "ACTIVE"
        assert new_card["photo_status"] == "APPROVED"
        assert new_card["is_provisional"] is False
        assert new_card["replacement_fee_cents"] == 2500

        old = get_success_data(api.get_card(card["id"], ADMIN))
        assert old["lifecycle_status"] == "REPLACED"
        assert old["replaced_by_card_id"] == new_card["id"]

        # Count invariant: exactly one non-terminal card before and after.
        cards, _ = validate_paginated(
            api.list_cards(ADMIN, {"holder_id": holder["id"]}))
        non_terminal = [c for c in cards
                        if c["lifecycle_status"] not in
                        ("REPLACED", "EXPIRED", "DEACTIVATED")]
        assert len(non_terminal) == 1
        assert non_terminal[0]["id"] == new_card["id"]


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def create_holder_with_provisional(**holder_overrides):
    from test_helpers import create_holder, create_provisional_card
    holder = create_holder(**holder_overrides)
    card = create_provisional_card(holder["id"])
    return holder, card


def create_holder_with_verified(expires_at="2027-08-24T00:00:00Z",
                                **holder_overrides):
    holder = create_holder(**holder_overrides)
    card = create_verified_card(holder["id"], expires_at=expires_at)
    return holder, card


def _setup_two_strikes_then_third(api):
    """Holder with two prior stolen reports (each police-reported and replaced);
    third card ACTIVE (provisional) with a funded CAMPUS_CASH account and one
    ACTIVE grant; then the third card is reported stolen."""
    set_clock("2026-08-25T09:00:00Z")
    holder = create_holder(university_id="U5001", full_name="Hank Resident",
                           email="hank@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
    c1 = create_provisional_card(holder["id"])
    report_card_stolen(c1["id"], holder["id"], police_report_number="PR-1")
    c2 = replace_card(c1, "STOLEN", police_report_number="PR-1")
    activate_card(c2["id"], allow_provisional=True)
    report_card_stolen(c2["id"], holder["id"], police_report_number="PR-2")
    c3 = replace_card(c2, "STOLEN", police_report_number="PR-2")
    activate_card(c3["id"], allow_provisional=True)

    account = open_account(holder["id"], "CAMPUS_CASH")
    fund_account(account["id"], 5000)
    zone = create_zone(zone_code="LIB", building="Library")
    grant = create_grant(c3["id"], zone["id"])

    report_card_stolen(c3["id"], holder["id"])
    return holder, c3, account, grant
