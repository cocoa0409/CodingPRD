"""Uncollected funds: the provisional-credit branch, the hold branch and reversal."""

from test_helpers import (
    ApiErrorId,
    MANAGER_1,
    TELLER_1,
    assert_account_balance_identity,
    assert_customer_account,
    assert_deposit_ticket,
    extend_provisional_credit,
    hold_payload,
    make_manager_headers,
    make_teller_headers,
    read_account,
    read_ticket,
    reverse_provisional_credit_payload,
    setup_verified_ticket,
    validate_error,
    validate_success,
)

STANDARD_BAG = {
    "bag_type": "CURRENCY",
    "declared_amount_cents": 100_000,
    "declared_note_count": 100,
    "declared_coin_weight_grams": 0,
}


class TestProvisionalCreditExtension:
    def test_standard_tier_haircut_extends_ninety_eight_percent_of_the_declared_total(self, api):
        """PRD §3.3: "Second, select the availability haircut from the depositor's `tier`:
        a `PREMIUM` depositor takes no haircut at all, a `STANDARD` depositor takes a two
        percent haircut, and a `WATCH` depositor takes a five percent haircut."
        PRD §3.3: "Extending credit adds the ticket's `provisional_credit_cents` to the
        customer account's own `provisional_credit_cents` and then recomputes the account's
        `available_balance_cents` as `ledger_balance_cents` plus `provisional_credit_cents`."
        PRD §3.3: "The account's `ledger_balance_cents` does not move — the funds are
        uncollected, and that distinction is the whole point of the field pair."

        Design: Difficulty/compensating_invariant/provisional_credit_then_reversal_conserves_customer_available_funds
        """
        scenario = setup_verified_ticket(bag_specs=[STANDARD_BAG], tier="STANDARD")

        ticket = extend_provisional_credit(scenario["ticket"]["id"])
        assert_deposit_ticket(ticket)
        assert ticket["status"] == "PROVISIONAL_CREDITED", (
            f"Expected PROVISIONAL_CREDITED, got {ticket['status']}"
        )
        assert ticket["provisional_credit_cents"] == 98_000, (
            f"A STANDARD depositor keeps 98% of 100000, expected 98000, got "
            f"{ticket['provisional_credit_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert_customer_account(account)
        assert account["provisional_credit_cents"] == 98_000, (
            f"The account's provisional_credit_cents must rise to 98000, got "
            f"{account['provisional_credit_cents']}"
        )
        assert account["ledger_balance_cents"] == 0, (
            "Uncollected funds must not touch ledger_balance_cents"
        )
        assert account["available_balance_cents"] == 98_000, (
            f"available_balance_cents must be 0 + 98000, got {account['available_balance_cents']}"
        )
        assert_account_balance_identity(account)

    def test_reversal_returns_the_customers_available_funds_to_their_pre_credit_figure(self, api):
        """PRD §3.3: "The reversal subtracts the ticket's `provisional_credit_cents` from
        the account's `provisional_credit_cents`, then sets the ticket's own
        `provisional_credit_cents` to 0, then recomputes the account's
        `available_balance_cents` as `ledger_balance_cents` plus `provisional_credit_cents`."
        PRD §3.3: "Because the reversal removes exactly what the extension added, a
        customer's available funds after an extend-then-reverse pair are identical to what
        they were before the extension, and the ticket is once again eligible for either
        branch of the fork."

        Design: Difficulty/compensating_invariant/provisional_credit_then_reversal_conserves_customer_available_funds
        """
        scenario = setup_verified_ticket(
            bag_specs=[STANDARD_BAG], tier="STANDARD", credit_branch="provisional"
        )
        assert scenario["ticket"]["provisional_credit_cents"] == 98_000

        mid = read_account(scenario["account"]["id"])
        assert mid["available_balance_cents"] == 98_000
        assert mid["provisional_credit_cents"] == 98_000
        assert mid["ledger_balance_cents"] == 0

        response = api.reverse_provisional_credit(
            scenario["ticket"]["id"],
            reverse_provisional_credit_payload(
                "Manifest mismatch found before counting; credit withdrawn."
            ),
            make_manager_headers(MANAGER_1),
        )
        ticket = validate_success(response, 200)
        assert ticket["status"] == "VERIFIED", (
            f"Reversal moves the ticket back to the fork at VERIFIED, got {ticket['status']}"
        )
        assert ticket["provisional_credit_cents"] == 0, (
            f"The ticket's own provisional_credit_cents is reset to 0, got "
            f"{ticket['provisional_credit_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["provisional_credit_cents"] == 0, (
            f"Expected the account's provisional_credit_cents back at 0, got "
            f"{account['provisional_credit_cents']}"
        )
        assert account["ledger_balance_cents"] == 0, "ledger_balance_cents never moved"
        assert account["available_balance_cents"] == 0, (
            f"Available funds must return to the pre-credit figure 0, got "
            f"{account['available_balance_cents']}"
        )
        assert_account_balance_identity(account)

    def test_provisional_credit_is_capped_at_five_million_cents(self, api):
        """PRD §3.3: "Fourth, take the smaller of that rounded figure and the hard
        provisional cap of 5,000,000 cents, which is fifty thousand dollars; the cap wins
        whenever the rounded figure is larger."
        PRD §3.3: "Extending credit adds the ticket's `provisional_credit_cents` to the
        customer account's own `provisional_credit_cents` and then recomputes the account's
        `available_balance_cents` as `ledger_balance_cents` plus `provisional_credit_cents`."

        Design: Corner/calculations/provisional_credit_is_capped_at_five_million_cents
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 6_000_000,
                    "declared_note_count": 600,
                    "declared_coin_weight_grams": 0,
                }
            ],
            tier="STANDARD",
        )

        ticket = extend_provisional_credit(scenario["ticket"]["id"])
        assert ticket["provisional_credit_cents"] == 5_000_000, (
            "The 5880000 haircut result exceeds the cap, so the cap wins: expected 5000000, "
            f"got {ticket['provisional_credit_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["provisional_credit_cents"] == 5_000_000
        assert account["available_balance_cents"] == 5_000_000
        assert account["ledger_balance_cents"] == 0
        assert_account_balance_identity(account)

    def test_suspended_account_cannot_take_provisional_credit(self, api):
        """PRD §3.3: "Provisional credit is extended by a `VaultTeller` and takes no
        request body; everything it needs is already on the ticket and the account. The
        depositor's account `status` must be `ACTIVE` — extending credit to a `SUSPENDED`
        account is `ERR_ACCOUNT_SUSPENDED`."

        Design: Corner/validations/suspended_account_blocks_provisional_credit
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 50,
                    "declared_coin_weight_grams": 0,
                }
            ],
            account_status="SUSPENDED",
        )

        response = api.extend_provisional_credit(
            scenario["ticket"]["id"], make_teller_headers(TELLER_1)
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)
        assert response.status_code == 409

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["status"] == "VERIFIED", (
            f"The refused extension leaves the ticket VERIFIED, got {ticket['status']}"
        )
        assert ticket["provisional_credit_cents"] == 0

        account = read_account(scenario["account"]["id"])
        assert account["provisional_credit_cents"] == 0
        assert account["available_balance_cents"] == 0


class TestHoldBranch:
    def test_hold_records_the_reason_and_moves_no_balance_field(self, api):
        """PRD §3.3: "Placing a hold is a `VaultManager` decision and requires a free-text
        `hold_reason`, which is recorded on the ticket; the field is null until a hold is
        placed. A hold also increments the account's `hold_count` by 1. Nothing else moves:
        no credit is extended, and no balance field on the customer account changes on this
        branch."
        PRD §3.3: "Branch B places a **hold** instead, moving the ticket `VERIFIED → HELD`,
        extends nothing, and moves no balance field on the customer account at all."

        Design: Corner/state_machines/hold_branch_extends_no_credit_and_increments_hold_count
        """
        scenario = setup_verified_ticket(bag_specs=[STANDARD_BAG])
        reason = "Manifest and seal log disagree; awaiting carrier statement."

        response = api.hold_deposit_ticket(
            scenario["ticket"]["id"], hold_payload(reason), make_manager_headers(MANAGER_1)
        )
        ticket = validate_success(response, 200)
        assert ticket["status"] == "HELD", f"Expected HELD, got {ticket['status']}"
        assert ticket["hold_reason"] == reason, (
            f"hold_reason must be recorded verbatim, got {ticket['hold_reason']!r}"
        )
        assert ticket["provisional_credit_cents"] == 0, "The hold branch extends nothing"

        account = read_account(scenario["account"]["id"])
        assert account["hold_count"] == 1, (
            f"A hold increments hold_count by 1, got {account['hold_count']}"
        )
        assert account["provisional_credit_cents"] == 0
        assert account["available_balance_cents"] == 0
        assert account["ledger_balance_cents"] == 0
        assert_account_balance_identity(account)
