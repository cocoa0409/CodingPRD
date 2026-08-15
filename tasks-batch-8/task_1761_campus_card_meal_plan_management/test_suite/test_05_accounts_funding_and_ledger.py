"""Declining-balance accounts, funding, manual adjustments, the append-only
ledger, and idempotency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_holder,
    fund_account,
    get_success_data,
    make_bursar_headers,
    open_account,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

BURSAR = TEST_USERS["bursar_headers"]


class TestAccountCreation:
    def test_account_balance_is_computed_not_settable(self, api):
        """PRD §3.5: "New accounts start `OPEN` with `balance_cents` 0 — a derived
        value that is never settable directly, only moved through ledger entries —
        and a null `last_adjusted_by`."
        PRD §3.5: "a `CAMPUS_CASH` account is termless and must carry a null
        `term_id`"

        Design: Corner/entities/account_balance_is_computed_not_settable
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90005", full_name="Eve Comp",
                               email="eve@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        assert account["balance_cents"] == 0
        assert account["status"] == "OPEN"
        assert account["term_id"] is None

    def test_dining_account_requires_term_and_campus_cash_forbids_it(self, api):
        """PRD §3.5: "A `DINING_DOLLARS` account is bound to a term and requires a
        `term_id`; a `CAMPUS_CASH` account is termless and must carry a null
        `term_id` — violating either rule is `ERR_VALIDATION`."

        Design: Corner/entities/dining_account_requires_term_and_campus_cash_forbids_it
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90007", full_name="Gus Term",
                               email="gus2@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        no_term = api.create_account(holder["id"],
                                     {"account_type": "DINING_DOLLARS"}, BURSAR)
        validate_error(no_term, ApiErrorId.ERR_VALIDATION)
        with_term = api.create_account(
            holder["id"],
            {"account_type": "CAMPUS_CASH", "term_id": str(NON_EXISTENT_UUID)},
            BURSAR)
        validate_error(with_term, ApiErrorId.ERR_VALIDATION)

    def test_duplicate_campus_cash_account_rejected(self, api):
        """PRD §3.5: "At most one non-terminal account may exist per holder, type,
        and term combination (`ERR_ACCOUNT_UNIQUENESS`)."

        Design: Corner/validations/duplicate_campus_cash_account_rejected
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U92004", full_name="Ned Dup",
                               email="ned@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        open_account(holder["id"], "CAMPUS_CASH")
        resp = api.create_account(holder["id"], {"account_type": "CAMPUS_CASH"},
                                  BURSAR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_UNIQUENESS)


class TestLedger:
    def test_ledger_entry_immutability_and_sequence(self, api):
        """PRD §2.4: "A `LedgerEntry` and an `AccessEvent` are immutable event
        records: each carries only `id` and `created_at`, and neither `updated_at`
        nor `version` exists on them."
        PRD §2.7: "a per-account `entry_sequence` that increases monotonically
        starting at 1" and "each entry's `running_balance_cents` stores the balance
        immediately after that entry in that replay order."

        Design: Corner/entities/ledger_entry_immutability_and_sequence
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90004", full_name="Dee Ledger",
                               email="dee@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        fund_account(account["id"], 1000, key="le-1")
        fund_account(account["id"], 500, key="le-2")

        entries, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": account["id"]}))
        assert len(entries) == 2
        first, second = entries[0], entries[1]
        assert first["entry_sequence"] == 1
        assert second["entry_sequence"] == 2
        assert first["entry_type"] == "FUND" and second["entry_type"] == "FUND"
        assert first["running_balance_cents"] == 1000
        assert second["running_balance_cents"] == 1500
        for entry in entries:
            assert "updated_at" not in entry
            assert "version" not in entry

    def test_mutation_visible_in_same_request_and_immediate_read(self, api):
        """PRD §2.7: "Every declining-balance account's `balance_cents` is a
        **derived value**: it is never set directly by any client, and it is
        recomputed after every ledger posting as the signed sum of the account's
        `LedgerEntry` rows."
        PRD §2.12: "Every state-changing action on a resource — activation,
        freezing, review, lifecycle transitions, postings that touch derived
        fields — increments that resource's `version` by 1 and refreshes its
        `updated_at`."

        Design: Corner/consistency_model/mutation_visible_in_same_request_and_immediate_read
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U95006", full_name="Jet Imm",
                               email="jet@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        before_version = account["version"]

        entry = validate_success(
            api.fund_account(account["id"],
                             {"amount_cents": 1500, "idempotency_key": "jet-f"},
                             BURSAR), 201)
        assert entry["running_balance_cents"] == 1500

        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 1500
        assert after["version"] == before_version + 1


class TestAdjustmentOCC:
    def test_occ_adjustment_stale_after_funding(self, api):
        """PRD §2.9: "Posting a manual adjustment to a declining-balance account
        requires `expected_account_version` matching the account's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),
        because the adjustment decision was made against a stale `balance_cents`."
        PRD §3.5: "the posting records the acting user's `X-User-ID` as the
        account's `last_adjusted_by`"

        Design: Corner/complexity_layers/occ_adjustment_stale_after_funding
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U95002", full_name="Fay Adj",
                               email="faya@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        stale_version = account["version"]
        fund_account(account["id"], 1000, key="fay-f")

        stale = api.adjust_account(
            account["id"],
            {"amount_cents": 200, "direction": "DEBIT", "reason": "correction",
             "expected_account_version": stale_version},
            make_bursar_headers("bursar-adj"))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        entries, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": account["id"]}))
        assert len(entries) == 1  # only the FUND entry

        fresh = get_success_data(api.get_account(account["id"], BURSAR))
        ok = api.adjust_account(
            account["id"],
            {"amount_cents": 200, "direction": "DEBIT", "reason": "correction",
             "expected_account_version": fresh["version"]},
            make_bursar_headers("bursar-adj"))
        entry = validate_success(ok, 201)
        assert entry["entry_type"] == "ADJUSTMENT_DEBIT"
        assert entry["running_balance_cents"] == 800

        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 800
        assert after["last_adjusted_by"] == "bursar-adj"


class TestFundingGuards:
    def test_funding_frozen_account_rejected(self, api):
        """PRD §3.5: "Funding posts to an `OPEN` account (a `FROZEN` or otherwise
        non-`OPEN` account is rejected with `ERR_ACCOUNT_FROZEN`)"
        PRD §3.2: "the holder's `OPEN` accounts are frozen with `frozen_reason`
        `CARD_STOLEN` (an account already `FROZEN` stays as it is)."

        Design: Corner/validations/funding_frozen_account_rejected
        """
        from test_helpers import (create_verified_card, report_card_stolen)
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U92013", full_name="Wyn Froz",
                               email="wyn@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = create_verified_card(holder["id"])
        account = open_account(holder["id"], "CAMPUS_CASH")
        report_card_stolen(card["id"], holder["id"])

        resp = api.fund_account(account["id"],
                                {"amount_cents": 1000, "idempotency_key": "wyn-f2"},
                                BURSAR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN)
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["status"] == "FROZEN"
        assert after["frozen_reason"] == "CARD_STOLEN"

    def test_idempotency_replay_and_conflict(self, api):
        """PRD §2.8: "When the same key is presented again with an identical
        payload, the server replays the original 201 response without performing
        the operation a second time. When the same key is presented with a
        divergent payload, the request is rejected with
        `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

        Design: Corner/complexity_layers/idempotency_replay_and_conflict
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U95005", full_name="Ivy Idem",
                               email="ivy2@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")

        first = validate_success(
            api.fund_account(account["id"],
                             {"amount_cents": 1000, "idempotency_key": "idem-1"},
                             BURSAR), 201)
        replay = validate_success(
            api.fund_account(account["id"],
                             {"amount_cents": 1000, "idempotency_key": "idem-1"},
                             BURSAR), 201)
        assert replay["id"] == first["id"]

        conflict = api.fund_account(
            account["id"], {"amount_cents": 2000, "idempotency_key": "idem-1"},
            BURSAR)
        validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)

        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 1000
        entries, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": account["id"],
                                             "entry_type": "FUND"}))
        assert len(entries) == 1
