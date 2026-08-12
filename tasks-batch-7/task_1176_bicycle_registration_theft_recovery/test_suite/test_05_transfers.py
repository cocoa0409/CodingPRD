"""Ownership transfers: creation guards, expiry, acceptance, duplicate-hold
priority (PRD §2.6, §3.3, §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_owner,
    register_bicycle,
    owner_headers,
    file_theft_report,
    flag_report,
    set_clock,
    setup_duplicate_suspect_pair,
    create_transfer_payload,
    get_all_ledger_entries,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestTransferCreationGuards:
    def test_transfer_blocked_when_bicycle_stolen(self, api):
        """PRD §3.3: "The bicycle's `registry_status` must be `REGISTERED` — a
        `STOLEN`, `RECOVERED`, or `RETURNED` bicycle cannot be sold through the
        registry, and the attempt is rejected with `ERR_BICYCLE_NOT_TRANSFERABLE`."

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_when_bicycle_stolen
        """
        seller = register_owner("o1@x.com", "O One")
        register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(seller, serial_number="XDP100", declared_value_cents=70000)
        report = file_theft_report(seller, bicycle)
        flag_report(report["id"])
        resp = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=40000),
            owner_headers(seller),
        )
        validate_error(resp, ApiErrorId.ERR_BICYCLE_NOT_TRANSFERABLE, expected_status=409)

    def test_transfer_allowed_again_after_report_withdrawn(self, api):
        """PRD §3.3: "The bicycle's `registry_status` must be `REGISTERED` — a
        `STOLEN`, `RECOVERED`, or `RETURNED` bicycle cannot be sold through the
        registry, and the attempt is rejected with `ERR_BICYCLE_NOT_TRANSFERABLE`."
        PRD §3.4: "The bicycle's `registry_status` returns from `STOLEN` to
        `REGISTERED`" (on withdrawal of a FLAGGED report).

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_when_bicycle_stolen
        """
        seller = register_owner("o1@x.com", "O One")
        register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(seller, serial_number="XDP101", declared_value_cents=70000)
        report = file_theft_report(seller, bicycle)
        flag_report(report["id"])
        blocked = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=40000),
            owner_headers(seller),
        )
        validate_error(blocked, ApiErrorId.ERR_BICYCLE_NOT_TRANSFERABLE)
        # Withdraw the FLAGGED report: the bicycle returns to REGISTERED.
        withdrawn = validate_success(
            api.withdraw_theft_report(report["id"], owner_headers(seller))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        read_back = validate_success(api.get_bicycle(bicycle["id"], REGISTRAR))
        assert read_back["registry_status"] == "REGISTERED"
        ok = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=40000),
            owner_headers(seller),
        )
        transfer = validate_success(ok, expected_status=201)
        assert transfer["status"] == "PENDING_ACCEPTANCE"

    def test_second_pending_transfer_rejected(self, api):
        """PRD §3.3: "At most one `PENDING_ACCEPTANCE` transfer may exist per
        bicycle; a second attempt fails with `ERR_TRANSFER_ALREADY_PENDING`."

        Design: Corner/errors/second_pending_transfer_rejected
        """
        seller = register_owner("o1@x.com", "O One")
        register_owner("o2@x.com", "O Two")
        register_owner("o3@x.com", "O Three")
        bicycle = register_bicycle(seller, serial_number="TPD100")
        first = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=30000),
            owner_headers(seller),
        )
        validate_success(first, expected_status=201)
        second = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o3@x.com", sale_price_cents=31000),
            owner_headers(seller),
        )
        validate_error(second, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING, expected_status=409)

    def test_self_transfer_clean_bicycle_rejected(self, api):
        """PRD §3.3: "Seller and buyer must be different owners — a `to_owner_email`
        resolving to the seller fails with `ERR_SELF_TRANSFER` (HTTP 422)."

        Design: Corner/errors/self_transfer_clean_bicycle_rejected
        """
        seller = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(seller, serial_number="SLF100")
        resp = api.create_transfer(
            create_transfer_payload(bicycle["id"], "o1@x.com", sale_price_cents=100),
            owner_headers(seller),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_TRANSFER, expected_status=422)


class TestDuplicateHoldPriority:
    def test_duplicate_hold_beats_self_transfer(self, api):
        """PRD §2.6: "Every request passes through a fixed validation pipeline, and
        the stages are evaluated in a strict order — a failure at an earlier stage
        surfaces its error and masks every later-stage check."
        PRD §2.6: "11. **Duplicate-suspect safety hold** — operations blocked while
        a bicycle is `DUPLICATE_SUSPECT` fail with `ERR_DUPLICATE_HOLD`." precedes
        "12. **Uniqueness and graph constraints** — ... self-transfer ...;
        failures yield ... `ERR_SELF_TRANSFER` ..."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_hold_beats_self_transfer
        """
        owner, bicycle_a, _bicycle_b, _flag = setup_duplicate_suspect_pair()
        # The request violates BOTH the duplicate hold and the self-transfer rule
        # (to_owner_email resolves to the acting seller's own account).
        resp = api.create_transfer(
            create_transfer_payload(bicycle_a["id"], owner["email"], sale_price_cents=100),
            owner_headers(owner),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOLD, expected_status=409)

    def test_duplicate_hold_blocks_transfer_to_other_owner(self, api):
        """PRD §3.3: "a `DUPLICATE_SUSPECT` bicycle is under a safety hold and
        rejects with `ERR_DUPLICATE_HOLD`."
        PRD §3.8: "A `DUPLICATE_SUSPECT` bicycle is under a safety hold: creating a
        transfer for it fails with `ERR_DUPLICATE_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_hold_beats_self_transfer
        """
        owner, bicycle_a, _bicycle_b, _flag = setup_duplicate_suspect_pair()
        register_owner("o2@x.com", "O Two")
        resp = api.create_transfer(
            create_transfer_payload(bicycle_a["id"], "o2@x.com", sale_price_cents=10000),
            owner_headers(owner),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOLD, expected_status=409)


class TestTransferAcceptance:
    def test_transfer_accept_from_completed_returns_not_pending(self, api):
        """PRD §3.3: "The acting owner must be the transfer's `to_owner_id`, the
        transfer must still be `PENDING_ACCEPTANCE` (otherwise
        `ERR_TRANSFER_NOT_PENDING`)."
        PRD §3.3: "posts a transfer-fee ledger pair — a `DEBIT` of 300 cents to the
        buyer's `OWNER` account and a `CREDIT` of 300 cents to the `PROGRAM`
        account, both of type `TRANSFER_FEE` and both carrying the `bicycle_id`"

        Design: Corner/state_machines/transfer_accept_from_completed_returns_not_pending
        """
        seller = register_owner("o1@x.com", "O One")
        buyer = register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(seller, serial_number="TRM100")
        transfer = validate_success(
            api.create_transfer(
                create_transfer_payload(bicycle["id"], "o2@x.com", sale_price_cents=30000),
                owner_headers(seller),
            ),
            expected_status=201,
        )
        accepted = validate_success(
            api.accept_transfer(transfer["id"], owner_headers(buyer))
        )
        assert accepted["status"] == "COMPLETED"
        resp = api.accept_transfer(transfer["id"], owner_headers(buyer))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_PENDING, expected_status=409)
        fees = get_all_ledger_entries(
            {"bicycle_id": bicycle["id"], "entry_type": "TRANSFER_FEE"}
        )
        assert len(fees) == 2, (
            f"exactly one balanced TRANSFER_FEE pair may exist (no double-charge), "
            f"got {len(fees)}"
        )
        assert all(f["amount_cents"] == 300 for f in fees)

    def test_transfer_expired_lazy_transition(self, api):
        """PRD §3.3: "The transfer begins in `PENDING_ACCEPTANCE` status with an
        `expires_at` of exactly seven days after creation."
        PRD §3.3: "the current logical time must be no later than `expires_at`. An
        acceptance attempted past expiry does not simply fail: the transfer first
        auto-transitions to `EXPIRED` — a lazy expiry that increments its `version`
        — and the call then fails with `ERR_TRANSFER_EXPIRED`."

        Design: Corner/validations/transfer_expired_lazy_transition
        """
        set_clock("2026-05-01T00:00:00Z")
        seller = register_owner("o1@x.com", "O One")
        buyer = register_owner("o2@x.com", "O Two")
        # Serials differ in 5 of 6 positions and manufacturers differ, so the
        # duplicate-confidence auto-flag (>= 8500bp, PRD §3.2) does NOT fire.
        bicycle1 = register_bicycle(seller, serial_number="EXP001", photo_url="https://x/1.jpg")
        bicycle2 = register_bicycle(
            seller,
            serial_number="ZZQ789",
            manufacturer="Giant",
            photo_url="https://x/2.jpg",
        )
        transfer1 = validate_success(
            api.create_transfer(
                create_transfer_payload(bicycle1["id"], "o2@x.com"), owner_headers(seller)
            ),
            expected_status=201,
        )
        transfer2 = validate_success(
            api.create_transfer(
                create_transfer_payload(bicycle2["id"], "o2@x.com"), owner_headers(seller)
            ),
            expected_status=201,
        )
        assert transfer1["expires_at"].startswith("2026-05-08"), (
            f"expires_at must be exactly seven days after creation, got "
            f"{transfer1['expires_at']}"
        )
        # At exactly expires_at the acceptance is still allowed (inclusive bound).
        set_clock("2026-05-08T00:00:00Z")
        accepted = validate_success(api.accept_transfer(transfer1["id"], owner_headers(buyer)))
        assert accepted["status"] == "COMPLETED"
        # One second past expiry: lazy EXPIRED transition + ERR_TRANSFER_EXPIRED.
        set_clock("2026-05-08T00:00:01Z")
        resp = api.accept_transfer(transfer2["id"], owner_headers(buyer))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_EXPIRED, expected_status=409)
        read_back = validate_success(api.get_transfer(transfer2["id"], REGISTRAR))
        assert read_back["status"] == "EXPIRED", (
            f"expired transfer must lazily transition to EXPIRED, got {read_back['status']}"
        )
