"""Ledger posting, receipt allocation, append-only guard, initial states,
and immediate read-after-write visibility (PRD §2.4, §2.6, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    OPS,
    add_beneficiary,
    create_active_trust,
    create_approved_document,
    create_request,
    create_trust,
    post_receipt,
)


class TestInitialStates:
    def test_trust_and_request_start_in_initial_states(self, api):
        """PRD §3.1: "The new account starts in DRAFT, reported through its
        `status` field."
        PRD §3.3: "A successful create lands in SUBMITTED, increments the
        trust's `pending_distribution_count` by one, and increments the
        trust's `version` by one."

        Design: Corner/state_machines/initial_states_on_create
        """
        created = create_trust(trust_name="Init Trust", trust_type="REVOCABLE")
        assert created["status"] == "DRAFT"

        trust2 = create_trust(trust_name="Init Trust C")
        create_approved_document(trust2["id"])
        ben2 = add_beneficiary(trust2["id"], full_name="Ivy")
        assert api.submit_for_acceptance(trust2["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust2["id"], EXEC).status_code == 200
        req = create_request(trust2["id"], ben2["id"], amount_cents=100000)
        assert req["status"] == "SUBMITTED"

    def test_fee_assessment_starts_calculated_with_tiered_amount(self, api):
        """PRD §3.6: "Creation stamps `calculated_by_user_id` from the caller's
        `X-User-ID` and lands the assessment in CALCULATED."
        PRD §3.6: "Dividing the annual fee by four and rounding half up to
        whole cents gives the quarterly amount; the `assessed_fee_cents` is
        that quarterly amount floored at a minimum quarterly fee of 125,000
        cents — twelve hundred fifty dollars."

        Design: Corner/state_machines/initial_states_on_create
        """
        trust = create_active_trust(trust_name="Init Fee")
        post_receipt(trust["id"], 200000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        resp = api.create_fee_assessment(
            {
                "trust_id": trust["id"],
                "period_start": "2026-07-01",
                "period_end": "2026-09-30",
                "variant": "FINAL",
            },
            OPS,
        )
        fee = validate_success(resp, expected_status=201)
        assert fee["status"] == "CALCULATED"
        assert fee["assessed_fee_cents"] == 437500


class TestReceiptSplitRounding:
    def test_rental_receipt_appends_two_rows_income_first(self, api):
        """PRD §3.5: "RENTAL_INCOME splits ninety percent to income — the
        income share is the receipt amount multiplied by ninety percent,
        rounded half up — and the remainder to principal." and "A
        fully-classified receipt appends one LedgerEntry; a split receipt
        appends two, the INCOME row first and the PRINCIPAL row second, and
        any rounding remainder always lands in PRINCIPAL."

        Design: Corner/calculations/receipt_split_rounding_rental
        """
        trust = create_active_trust(trust_name="Rent Trust")
        resp = api.create_ledger_entry(
            {
                "trust_id": trust["id"],
                "entry_kind": "RECEIPT",
                "receipt_type": "RENTAL_INCOME",
                "amount_cents": 100001,
                "value_date": "2026-08-10",
                "description": "rent",
            },
            OPS,
        )
        rows = validate_success(resp, expected_status=201)
        assert isinstance(rows, list) and len(rows) == 2
        assert rows[0]["bucket"] == "INCOME" and rows[0]["amount_cents"] == 90001
        assert rows[1]["bucket"] == "PRINCIPAL" and rows[1]["amount_cents"] == 10000

    def test_rental_receipt_balances_conserve_cents(self, api):
        """PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket, and
        `principal_balance_cents` is the same sum over the PRINCIPAL bucket."
        PRD §3.5: "any rounding remainder always lands in PRINCIPAL."

        Design: Corner/calculations/receipt_split_rounding_rental
        """
        trust = create_active_trust(trust_name="Rent Balance")
        post_receipt(trust["id"], 100001, receipt_type="RENTAL_INCOME",
                     value_date="2026-08-10", description="rent")
        after = validate_success(api.get_trust(trust["id"], OFFICER))
        assert after["income_balance_cents"] == 90001
        assert after["principal_balance_cents"] == 10000
        assert after["income_balance_cents"] + after["principal_balance_cents"] == 100001


class TestLedgerImmutability:
    def test_put_ledger_entry_returns_405(self, api):
        """PRD §2.6: "The ledger is append-only: an attempt to modify or
        remove an existing row is always rejected with
        `ERR_LEDGER_IMMUTABLE`."

        Design: Corner/endpoints/ledger_immutable_put_returns_405
        """
        trust = create_active_trust(trust_name="Immutable")
        rows = post_receipt(trust["id"], 100000, value_date="2026-08-06", description="income")
        entry_id = rows[0]["id"]
        resp = api.put_ledger_entry(entry_id, {"amount_cents": 1}, OPS)
        validate_error(resp, ApiErrorId.ERR_LEDGER_IMMUTABLE)

    def test_rejected_put_leaves_entry_unchanged(self, api):
        """PRD §2.6: "The ledger is append-only: an attempt to modify or
        remove an existing row is always rejected with
        `ERR_LEDGER_IMMUTABLE`."

        Design: Corner/endpoints/ledger_immutable_put_returns_405
        """
        trust = create_active_trust(trust_name="Immutable Read")
        rows = post_receipt(trust["id"], 100000, value_date="2026-08-06", description="income")
        entry_id = rows[0]["id"]
        api.put_ledger_entry(entry_id, {"amount_cents": 1}, OPS)
        current = validate_success(api.get_ledger_entry(entry_id, OPS))
        assert current["amount_cents"] == 100000


class TestCommitteeMemberDefaults:
    def test_member_status_defaults_to_active(self, api):
        """PRD §3.2: "A `TrustExecutive` creates a CommitteeMember with a
        `full_name` and a service window from `term_start` to `term_end`;
        members start ACTIVE."

        Design: Corner/entities/committee_member_status_default_active
        """
        resp = api.create_committee_member(
            {"full_name": "Default Dan", "term_start": "2026-01-01",
             "term_end": "2028-12-31"},
            EXEC,
        )
        member = validate_success(resp, expected_status=201)
        assert member["status"] == "ACTIVE"

    def test_member_create_carries_common_fields(self, api):
        """PRD §2.4: "Every primary resource carries a server-minted `id`
        formatted as a UUID with no type prefix, a `created_at` timestamp
        recording when the resource was created, an `updated_at` timestamp
        refreshed on every mutation, and a `version` integer that increments
        by one on every mutation."

        Design: Corner/entities/committee_member_status_default_active
        """
        from test_helpers import assert_committee_member
        resp = api.create_committee_member(
            {"full_name": "Default Dot", "term_start": "2026-01-01",
             "term_end": "2028-12-31"},
            EXEC,
        )
        member = validate_success(resp, expected_status=201)
        assert_committee_member(member)


class TestImmediateVisibility:
    def test_get_immediately_after_post_reflects_balance(self, api):
        """PRD §2.6: "All of these derivations are recomputed immediately and
        synchronously on every contributing mutation — a ledger append, a
        reservation or release, a purchase, a sale, or a price update."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        trust = create_active_trust(trust_name="Immediate", trust_type="REVOCABLE",
                                    distribution_standard="HEMS")
        post_receipt(trust["id"], 123456, value_date="2026-08-06", description="income")
        after = validate_success(api.get_trust(trust["id"], OFFICER))
        assert after["income_balance_cents"] == 123456
