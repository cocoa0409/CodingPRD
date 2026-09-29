"""Allowance tonnage is conserved across a settlement, a refused settlement and
a reversal: the endowment of 40.000 tons never changes hands, it only moves
between the buckets and the settled rows."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allowance_quantity_conserved,
    assert_allowance_transaction,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

CLOCK = "2026-08-01T00:00:00Z"
ENDOWMENT_TONS = 40.000
REVERSAL_REASON = "counterparty deal cancelled before the transfer cleared"


def _endowed_account():
    fx.set_clock(CLOCK)
    facility = fx.create_facility()
    account = fx.open_allowance_account(
        facility["id"],
        holdings_prior_vintage_tons=7.000,
        holdings_current_vintage_tons=18.000,
        holdings_next_vintage_tons=15.000,
    )
    return {"facility": facility, "account": account}


def _account(account_id):
    return validate_success(api_client.get_allowance_account(account_id, fx.TRADER))


def _transactions(account_id):
    rows, _ = validate_paginated(
        api_client.list_allowance_transactions(
            fx.REVIEWER, {"allowance_account_id": account_id}
        )
    )
    return rows


def _posture(facility_id):
    return validate_success(api_client.get_facility(facility_id, fx.REVIEWER))[
        "compliance_posture"
    ]


class TestSettlementConservesTheEndowment:
    """A settled surrender moves tonnage out of the buckets and into the row."""

    def test_a_surrender_drains_the_oldest_vintage_first_without_creating_tonnage(self):
        """10.000 leaves as 7.000 banked plus 3.000 current; the sum stays 40.000.

        PRD: "A `SURRENDER` or `TRANSFER_OUT` drains **oldest vintage first**:
        `debited_prior_tons` is the smaller of the quantity still to be taken and
        `holdings_prior_vintage_tons`; the remainder is then taken as
        `debited_current_tons`, the smaller of what is left and
        `holdings_current_vintage_tons`"

        Design: Difficulty/compensating_invariant/invariant_allowance_tonnage_conserved_across_settle_and_reverse
        """
        station = _endowed_account()
        account_id = station["account"]["id"]

        opening = station["account"]
        assert_allowance_quantity_conserved(opening, ENDOWMENT_TONS, [])
        assert _posture(station["facility"]["id"]) == "COMPLIANT", (
            "no report was ever submitted, so nothing is projected"
        )

        proposed = fx.propose_transaction(
            account_id,
            opening["version"],
            transaction_type="SURRENDER",
            quantity_tons=10.000,
            vintage_year=2026,
        )
        assert_allowance_transaction(proposed)
        assert proposed["status"] == "PROPOSED"
        assert proposed["origin"] == "MANUAL"
        assert proposed["debited_prior_tons"] == 0.000, (
            "proposing debits nothing"
        )

        at_proposal = _account(account_id)
        assert at_proposal["holdings_prior_vintage_tons"] == 7.000
        assert at_proposal["holdings_current_vintage_tons"] == 18.000
        assert at_proposal["holdings_next_vintage_tons"] == 15.000

        fx.transition_transaction(proposed["id"], "RECORD")
        settled = fx.transition_transaction(proposed["id"], "SETTLE")
        assert settled["status"] == "SETTLED"
        assert settled["debited_prior_tons"] == 7.000
        assert settled["debited_current_tons"] == 3.000
        assert settled["debited_next_tons"] == 0.000, (
            "a client-initiated debit never touches the next-vintage bucket"
        )

        after = _account(account_id)
        assert after["holdings_prior_vintage_tons"] == 0.000
        assert after["holdings_current_vintage_tons"] == 15.000
        assert after["holdings_next_vintage_tons"] == 15.000
        assert after["surrendered_tons"] == 10.000
        assert after["shortfall_tons"] == 0.000

        assert_allowance_quantity_conserved(
            after, ENDOWMENT_TONS, _transactions(account_id)
        )
        assert _posture(station["facility"]["id"]) == "COMPLIANT"

    def test_a_refused_settlement_moves_no_tonnage_at_all(self):
        """30.000 against 15.000 available is refused and the buckets do not move.

        PRD: "for a `SURRENDER` or `TRANSFER_OUT` the `quantity_tons` must not
        exceed `holdings_prior_vintage_tons` plus `holdings_current_vintage_tons`,
        else `ERR_INSUFFICIENT_ALLOWANCES`, with equality accepted since draining
        an account to exactly zero is legitimate."

        Design: Difficulty/compensating_invariant/invariant_allowance_tonnage_conserved_across_settle_and_reverse
        """
        station = _endowed_account()
        account_id = station["account"]["id"]

        first = fx.propose_transaction(
            account_id,
            station["account"]["version"],
            transaction_type="SURRENDER",
            quantity_tons=10.000,
            vintage_year=2026,
        )
        fx.transition_transaction(first["id"], "RECORD")
        fx.transition_transaction(first["id"], "SETTLE")

        overdraw = fx.propose_transaction(
            account_id,
            _account(account_id)["version"],
            transaction_type="SURRENDER",
            quantity_tons=30.000,
            vintage_year=2026,
        )
        fx.transition_transaction(overdraw["id"], "RECORD")

        refused = api_client.transition_allowance_transaction(
            overdraw["id"], {"action": "SETTLE"}, fx.REPRESENTATIVE
        )
        validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_ALLOWANCES.value)

        stuck = validate_success(
            api_client.get_allowance_transaction(overdraw["id"], fx.REVIEWER)
        )
        assert stuck["status"] == "RECORDED"
        assert stuck["debited_prior_tons"] == 0.000
        assert stuck["debited_current_tons"] == 0.000
        assert stuck["debited_next_tons"] == 0.000

        unchanged = _account(account_id)
        assert unchanged["holdings_prior_vintage_tons"] == 0.000
        assert unchanged["holdings_current_vintage_tons"] == 15.000
        assert unchanged["holdings_next_vintage_tons"] == 15.000
        assert unchanged["surrendered_tons"] == 10.000
        assert_allowance_quantity_conserved(
            unchanged, ENDOWMENT_TONS, _transactions(account_id)
        )
        assert _posture(station["facility"]["id"]) == "COMPLIANT"


class TestReversalRestoresRatherThanRederives:
    """The stored per-bucket amounts come back, and a purchase does not break
    the identity."""

    def test_reversing_the_settled_surrender_credits_back_the_stored_split(self):
        """7.000 and 3.000 return to the exact buckets they were taken from.

        PRD: "Exactly `debited_prior_tons`, `debited_current_tons` and
        `debited_next_tons` are credited back to their three respective buckets —
        the stored amounts, not a re-derived split."

        Design: Difficulty/compensating_invariant/invariant_allowance_tonnage_conserved_across_settle_and_reverse
        """
        station = _endowed_account()
        account_id = station["account"]["id"]

        surrender = fx.propose_transaction(
            account_id,
            station["account"]["version"],
            transaction_type="SURRENDER",
            quantity_tons=10.000,
            vintage_year=2026,
        )
        fx.transition_transaction(surrender["id"], "RECORD")
        fx.transition_transaction(surrender["id"], "SETTLE")

        reversed_row = fx.transition_transaction(
            surrender["id"], "REVERSE", reason=REVERSAL_REASON
        )
        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["reversal_reason"] == REVERSAL_REASON

        restored = _account(account_id)
        assert restored["holdings_prior_vintage_tons"] == 7.000
        assert restored["holdings_current_vintage_tons"] == 18.000
        assert restored["holdings_next_vintage_tons"] == 15.000
        assert restored["surrendered_tons"] == 0.000
        assert restored["status"] == "OPEN", (
            "the reversed row's origin was MANUAL, so no lock was ever held"
        )
        assert_allowance_quantity_conserved(
            restored, ENDOWMENT_TONS, _transactions(account_id)
        )
        assert _posture(station["facility"]["id"]) == "COMPLIANT"

    def test_a_settled_purchase_raises_holdings_without_breaking_the_identity(self):
        """The next-vintage bucket reaches 20.000 and the identity still gives 40.000.

        PRD: "A `PURCHASE` or `TRANSFER_IN` adds `quantity_tons` to that bucket
        and records all three `debited_*` amounts as 0.0."

        Design: Difficulty/compensating_invariant/invariant_allowance_tonnage_conserved_across_settle_and_reverse
        """
        station = _endowed_account()
        account_id = station["account"]["id"]

        surrender = fx.propose_transaction(
            account_id,
            station["account"]["version"],
            transaction_type="SURRENDER",
            quantity_tons=10.000,
            vintage_year=2026,
        )
        fx.transition_transaction(surrender["id"], "RECORD")
        fx.transition_transaction(surrender["id"], "SETTLE")
        fx.transition_transaction(surrender["id"], "REVERSE", reason=REVERSAL_REASON)

        purchase = fx.propose_transaction(
            account_id,
            _account(account_id)["version"],
            transaction_type="PURCHASE",
            quantity_tons=5.000,
            vintage_year=2027,
        )
        fx.transition_transaction(purchase["id"], "RECORD")
        purchased = fx.transition_transaction(purchase["id"], "SETTLE")
        assert purchased["status"] == "SETTLED"
        assert purchased["debited_prior_tons"] == 0.000
        assert purchased["debited_current_tons"] == 0.000
        assert purchased["debited_next_tons"] == 0.000

        after = _account(account_id)
        assert after["holdings_prior_vintage_tons"] == 7.000
        assert after["holdings_current_vintage_tons"] == 18.000
        assert after["holdings_next_vintage_tons"] == 20.000, (
            "a vintage later than the compliance year addresses the next bucket"
        )
        assert after["surrendered_tons"] == 0.000

        assert_allowance_quantity_conserved(
            after, ENDOWMENT_TONS, _transactions(account_id)
        )
        assert _posture(station["facility"]["id"]) == "COMPLIANT"
