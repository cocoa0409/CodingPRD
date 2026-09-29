"""Round trips whose compensating leg must restore an invariant exactly.

A repurchase must offset its own funding debit to the cent, and a take-out
purchase must move commitment capacity between buckets without creating or
destroying any of it.
"""

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── Repurchase must offset the funding debit exactly ─────────────────────────

class TestLedgerNetsToZeroAfterRepurchase:
    def test_a_payment_one_cent_short_is_refused_rather_than_left_as_residue(self):
        """Exactness is what keeps the ledger identity checkable.

        PRD 2.8: "The supplied `payment_amount_cents` equals the advance's
        `outstanding_balance_cents` exactly, failing with
        `ERR_REPURCHASE_AMOUNT_MISMATCH` (422). Partial repurchases do not exist;
        this exactness is what makes the ledger conservation invariant exactly
        checkable."

        Design: Difficulty/compensating_invariant/invariant_ledger_debits_equal_credits_after_repurchase
        """
        scenario = fx.setup_funded_dry_advance()
        borrower = make_borrower_headers(scenario.facility["id"])

        validate_error(
            api_client.repurchase_advance(
                scenario.advance["id"], make.repurchase_payload(1_959_999_999), borrower
            ),
            ApiErrorId.ERR_REPURCHASE_AMOUNT_MISMATCH,
        )

        untouched = fx.read_advance(scenario.advance["id"])
        assert untouched["funding_status"] == "FUNDED"
        assert untouched["outstanding_balance_cents"] == 1_960_000_000

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1

    def test_the_exact_repurchase_credit_nets_the_principal_ledger_to_zero(self):
        """One `DEBIT` in, one equal `CREDIT` out, and both invariants hold.

        PRD 3.7: "One `REPURCHASE` entry with direction `CREDIT` is appended for
        the payment amount, the funding axis moves to the terminal `REPURCHASED`,
        and the facility's `outstanding_principal_cents`, `availability_cents`
        and every sublimit rollup are re-projected along with the commitment's
        allocation buckets and the investor's `exposure_cents`."

        Design: Difficulty/compensating_invariant/invariant_ledger_debits_equal_credits_after_repurchase
        """
        scenario = fx.setup_funded_dry_advance()
        borrower = make_borrower_headers(scenario.facility["id"])

        repurchased = validate_success(
            api_client.repurchase_advance(
                scenario.advance["id"], make.repurchase_payload(1_960_000_000), borrower
            )
        )
        asserts.assert_advance(repurchased)
        assert repurchased["funding_status"] == "REPURCHASED"
        assert repurchased["outstanding_balance_cents"] == 0

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("REPURCHASE", "CREDIT")]
        )
        for entry in entries:
            asserts.assert_ledger_entry(entry)
            assert entry["amount_cents"] == 1_960_000_000

        summary = fx.read_exposure_summary(scenario.facility["id"])
        assert summary["ledger_debit_total_cents"] == 1_960_000_000
        assert summary["ledger_credit_total_cents"] == 1_960_000_000
        assert summary["advance_outstanding_sum_cents"] == 0
        assert summary["outstanding_principal_cents"] == 0
        asserts.assert_both_conservation_invariants(summary)

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 0
        assert facility["availability_cents"] == 20_000_000_000

        # The allocation is released without ever having been settled.
        commitment = fx.read_commitment(scenario.commitment["id"])
        asserts.assert_commitment(commitment)
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["settled_amount_cents"] == 0
        assert commitment["remaining_amount_cents"] == 5_000_000_000
        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == 0


# ─── Purchase moves capacity between buckets without losing any ───────────────

class TestCommitmentCapacityConservedAcrossPurchase:
    def test_the_allocation_is_intact_and_the_exposure_live_before_settlement(self):
        """Allocated plus remaining accounts for the whole commitment.

        PRD 3.2: "`allocated_amount_cents` is the sum of `advance_amount_cents`
        over the advances pointing at the commitment whose `funding_status` is
        `FUNDED` or `SHIPPED`; `settled_amount_cents` is the same sum restricted
        to advances in `PURCHASED`; and `remaining_amount_cents` is the committed
        face amount less both of those, never below zero."

        Design: Difficulty/compensating_invariant/invariant_commitment_capacity_conserved_across_purchase
        """
        scenario = fx.setup_shipped_advance(ship_clock_utc="2026-08-05T00:00:00Z")

        commitment = fx.read_commitment(scenario.commitment["id"])
        asserts.assert_commitment(commitment)
        assert commitment["allocated_amount_cents"] == 1_960_000_000
        assert commitment["settled_amount_cents"] == 0
        assert commitment["remaining_amount_cents"] == 3_040_000_000
        assert commitment["status"] == "PARTIALLY_ALLOCATED"

        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == (
            1_960_000_000
        )

    def test_settlement_moves_capacity_from_allocated_into_settled(self):
        """The three buckets still sum to the committed face amount.

        PRD 3.7: "The facility's `outstanding_principal_cents` and
        `availability_cents` are re-projected; the commitment moves the amount
        from `allocated_amount_cents` into `settled_amount_cents`, leaving
        `remaining_amount_cents` untouched and its status at
        `PARTIALLY_ALLOCATED` when remaining capacity is still positive; and the
        investor's `exposure_cents` drops by the settled amount."

        Design: Difficulty/compensating_invariant/invariant_commitment_capacity_conserved_across_purchase
        """
        scenario = fx.setup_purchased_advance()

        advance = scenario.advance
        assert advance["funding_status"] == "PURCHASED"
        asserts.assert_instant(advance["purchased_at"], "2026-08-06T00:00:00Z")
        assert advance["outstanding_balance_cents"] == 0

        letters = fx.advance_bailee_letters(scenario.advance["id"])
        assert len(letters) == 1
        assert letters[0]["status"] == "HONORED"

        commitment = fx.read_commitment(scenario.commitment["id"])
        asserts.assert_commitment(commitment)
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["settled_amount_cents"] == 1_960_000_000
        assert commitment["remaining_amount_cents"] == 3_040_000_000
        assert commitment["committed_amount_cents"] == 5_000_000_000
        assert commitment["status"] == "PARTIALLY_ALLOCATED"

        # A purchased loan is off the line but permanently consumes capacity.
        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == 0

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], COLLATERAL_ANALYST
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("INVESTOR_PROCEEDS", "CREDIT")]
        )
        assert entries[1]["amount_cents"] == 1_960_000_000

        summary = fx.read_exposure_summary(scenario.facility["id"])
        assert summary["ledger_debit_total_cents"] == 1_960_000_000
        assert summary["ledger_credit_total_cents"] == 1_960_000_000
        assert summary["advance_outstanding_sum_cents"] == 0
        asserts.assert_both_conservation_invariants(summary)

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 0
        assert facility["availability_cents"] == 20_000_000_000
