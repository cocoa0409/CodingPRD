"""Two ledgers that must balance across a compensating operation.

The first is money: the protest purse and the solicitation's escrow always sum
to what was deposited. The second is strikes: a vendor's strike count always
equals the strikes attributed by its own proceedings.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.constants import (
    AD_VALOREM_RATE_TIER_1,
    GROUNDS_MULTIPLIERS,
    PROTEST_FEE_BASE_CENTS,
)
from test_helpers.test_users import DEBARMENT_AUTHORITY_HEADERS, make_vendor_headers

# --------------------------------------------------------------------------
# The money ledger of the withdrawal scenario
# --------------------------------------------------------------------------
DEPOSIT_CENTS = 100000
SOLICITATION_VALUE_CENTS = 10000000


def _half_up_cents(product: Decimal) -> int:
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Each of the three fee components is rounded to a whole cent, and only then are
# the rounded components added: 25000 + 7500 + 3138 (the surcharge product is
# 3137.5 exactly, which rounds half-up to 3138).
_AD_VALOREM_CENTS = _half_up_cents(
    Decimal(SOLICITATION_VALUE_CENTS) * Decimal(str(AD_VALOREM_RATE_TIER_1))
)
_SURCHARGE_CENTS = _half_up_cents(
    Decimal(PROTEST_FEE_BASE_CENTS)
    * Decimal(str(GROUNDS_MULTIPLIERS["SOLICITATION_IMPROPRIETY"]))
)
EXPECTED_FEE_CENTS = PROTEST_FEE_BASE_CENTS + _AD_VALOREM_CENTS + _SURCHARGE_CENTS

# --------------------------------------------------------------------------
# The strike ledger of the dismissal scenario
# --------------------------------------------------------------------------
NOTICE_INSTANT = "2026-08-01T00:00:00Z"
HEARING_INSTANT = "2026-08-16T00:00:00Z"


def _instant(value: Any) -> datetime:
    """Parse a rendered UTC instant so comparisons ignore fractional padding."""
    assert isinstance(value, str) and value, "expected an ISO-8601 instant, got {!r}".format(
        value
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_fee_literals_are_derivable() -> None:
    """The three components of the fee, each rounded before they are added."""
    assert PROTEST_FEE_BASE_CENTS == 25000
    assert _AD_VALOREM_CENTS == 7500
    assert _SURCHARGE_CENTS == 3138
    assert EXPECTED_FEE_CENTS == 35638


def _protest_filed_against_a_funded_purse() -> Dict[str, Any]:
    """A solicitation-impropriety protest whose 35,638-cent fee has moved from
    the protester's purse into the solicitation's escrow."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Oakhurst Guardrail",
        tax_id="100000022",
        contact_email="v22@example.gov",
    )
    vendor_id = vendor["id"]
    fx.fund_vendor(vendor_id, DEPOSIT_CENTS)

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-CI1",
        title="Guardrail End Terminal Upgrade",
        issuing_agency_code="DOT",
        estimated_value_cents=SOLICITATION_VALUE_CENTS,
        original_bid_due_utc="2026-08-27T00:00:00Z",
        original_question_deadline_utc="2026-08-20T00:00:00Z",
        mandatory_requirements=[
            fac.requirement_payload(
                requirement_code="REQ-MASH",
                description="MASH TL-3 tested terminal",
                materiality="MATERIAL",
                is_waivable=False,
            )
        ],
    )
    solicitation_id = solicitation["id"]
    fx.issue_solicitation(solicitation_id)
    fx.submit_question(
        solicitation_id,
        vendor_id,
        question_text="will an equivalent MASH TL-3 terminal be accepted?",
    )

    before_filing = {
        "balance_cents": fx.read_vendor(vendor_id)["protest_fee_balance_cents"],
        "escrow_cents": fx.read_solicitation(solicitation_id)["protest_escrow_cents"],
    }

    protest = fx.file_protest(
        solicitation_id,
        vendor_id,
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative="the named terminal is a single proprietary product",
    )
    return {
        "vendor_id": vendor_id,
        "solicitation_id": solicitation_id,
        "protest_id": protest["id"],
        "protest": protest,
        "before_filing": before_filing,
    }


def _ledger(state: Dict[str, Any]) -> Dict[str, int]:
    """The two halves of the money ledger and their total."""
    balance = fx.read_vendor(state["vendor_id"])["protest_fee_balance_cents"]
    escrow = fx.read_solicitation(state["solicitation_id"])["protest_escrow_cents"]
    return {
        "balance_cents": balance,
        "escrow_cents": escrow,
        "total_cents": balance + escrow,
    }


def _withdraw(state: Dict[str, Any]):
    return api_client.withdraw_protest(
        state["protest_id"],
        fac.withdraw_payload(
            withdrawal_reason="the agency issued an addendum permitting equivalents"
        ),
        make_vendor_headers(state["vendor_id"]),
    )


def _suspended_respondent_awaiting_decision() -> Dict[str, Any]:
    """An interim-suspended respondent whose proceeding has reached HEARING_HELD
    on the default branch, carrying exactly one strike."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Sablewood Mechanical",
        tax_id="100000023",
        contact_email="v23@example.gov",
    )
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD"],
        mitigating_factor_codes=[],
        interim_suspension=True,
    )
    fx.set_clock(HEARING_INSTANT)
    fx.hold_debarment_hearing(
        proceeding["id"],
        hearing_summary="respondent appeared and rebutted the certification allegation",
    )
    return {"vendor_id": vendor["id"], "proceeding_id": proceeding["id"]}


def _proceedings_of(vendor_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api_client.list_debarment_proceedings(
            DEBARMENT_AUTHORITY_HEADERS, params={"vendor_id": vendor_id}
        )
    )
    return rows


def _strike_ledger_total(vendor_id: str) -> int:
    """The sum of strikes_applied over the vendor's proceedings that are
    DEBARRED or interim-suspended, which is what the count is recomputed from."""
    return sum(
        row["strikes_applied"]
        for row in _proceedings_of(vendor_id)
        if row["status"] == "DEBARRED" or row["interim_status"] == "INTERIM_SUSPENDED"
    )


def _dismiss(proceeding_id: str):
    return api_client.decide_debarment(
        proceeding_id,
        fac.debarment_decision_payload(
            outcome="DISMISSED",
            rationale=(
                "the allegation was not established by a preponderance of the record"
            ),
        ),
        DEBARMENT_AUTHORITY_HEADERS,
    )


# ==========================================================================
# The money ledger: purse plus escrow across a withdrawal
# ==========================================================================
class TestProtestFeeLedgerConservation:
    """The deposited 100,000 cents is never created or destroyed by a filing or
    by the withdrawal that compensates it."""

    def test_purse_plus_escrow_totals_the_deposit_before_and_after_the_withdrawal(self):
        """From every one of those three states the effects are identical: `status` becomes `WITHDRAWN`, `stay_status` moves to `LIFTED` from `ACTIVE` or `OVERRIDDEN`, and the filing debit is fully compensated — `fee_refunded_cents` is set to the whole `filing_fee_cents`, that amount is subtracted from the solicitation's `protest_escrow_cents` and added back to the protester's `protest_fee_balance_cents`.

        Design: Difficulty/compensating_invariant/protest_fee_ledger_is_conserved_across_a_withdrawal
        """
        _assert_fee_literals_are_derivable()
        state = _protest_filed_against_a_funded_purse()

        # Checkpoint one: the purse holds the whole deposit and nothing is escrowed.
        assert state["before_filing"]["balance_cents"] == DEPOSIT_CENTS
        assert state["before_filing"]["escrow_cents"] == 0
        assert (
            state["before_filing"]["balance_cents"]
            + state["before_filing"]["escrow_cents"]
            == DEPOSIT_CENTS
        )

        # Checkpoint two: the filing debit has moved the fee, not consumed it.
        filed = _ledger(state)
        assert filed["balance_cents"] == DEPOSIT_CENTS - EXPECTED_FEE_CENTS == 64362
        assert filed["escrow_cents"] == EXPECTED_FEE_CENTS == 35638
        assert filed["total_cents"] == DEPOSIT_CENTS

        withdrawn = validate_success(_withdraw(state), expected_status=200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["stay_status"] == "LIFTED"

        # Checkpoint three: the compensation restores the opening ledger exactly.
        after = _ledger(state)
        assert after["balance_cents"] == DEPOSIT_CENTS
        assert after["escrow_cents"] == 0
        assert after["total_cents"] == DEPOSIT_CENTS
        assert after["total_cents"] - filed["total_cents"] == 0

        # A withdrawal is not a decision on the merits.
        assert withdrawn["decision_outcome"] is None
        assert withdrawn["remedy_code"] is None
        # And it touches only the ledger, not the procurement lifecycle.
        assert fx.read_solicitation(state["solicitation_id"])["status"] == "ISSUED"

    def test_the_purse_credit_and_the_escrow_debit_net_to_zero(self):
        """On success the fee is subtracted from the protester's `protest_fee_balance_cents` and added to the solicitation's `protest_escrow_cents`, and both the vendor's `version` and the solicitation's `version` increment by 1.

        Design: Difficulty/compensating_invariant/protest_fee_ledger_is_conserved_across_a_withdrawal
        """
        _assert_fee_literals_are_derivable()
        state = _protest_filed_against_a_funded_purse()

        assert state["protest"]["filing_fee_cents"] == EXPECTED_FEE_CENTS
        assert state["protest"]["fee_refunded_cents"] == 0
        assert state["protest"]["stay_status"] == "ACTIVE"

        before = _ledger(state)
        withdrawn = validate_success(_withdraw(state), expected_status=200)
        after = _ledger(state)

        purse_movement = after["balance_cents"] - before["balance_cents"]
        escrow_movement = after["escrow_cents"] - before["escrow_cents"]

        assert purse_movement == EXPECTED_FEE_CENTS
        assert escrow_movement == -EXPECTED_FEE_CENTS
        assert purse_movement + escrow_movement == 0

        # The refunded amount is the filed amount, to the cent.
        assert withdrawn["filing_fee_cents"] == EXPECTED_FEE_CENTS
        assert withdrawn["fee_refunded_cents"] == EXPECTED_FEE_CENTS
        assert withdrawn["fee_refunded_cents"] - withdrawn["filing_fee_cents"] == 0


# ==========================================================================
# The strike ledger: the vendor's count against its proceedings' strikes
# ==========================================================================
class TestDebarmentStrikeLedgerConservation:
    """An interim suspension credits one strike and the dismissal debits exactly
    that one strike back."""

    def test_strike_count_equals_the_strikes_attributed_before_and_after_dismissal(self):
        """That vendor transition sets `suspension_reason_code` to the proceeding's `cause_code` and `active_debarment_id` to the proceeding's id, and recomputes `debarment_strike_count` as the sum of `strikes_applied` over that vendor's proceedings whose `status` is `DEBARRED` or whose `interim_status` is `INTERIM_SUSPENDED`.

        Design: Difficulty/compensating_invariant/debarment_strike_count_is_conserved_across_an_interim_suspension_dismissal
        """
        state = _suspended_respondent_awaiting_decision()
        vendor_id = state["vendor_id"]

        # The identity holds at one while the interim suspension is in force.
        before_vendor = fx.read_vendor(vendor_id)
        assert before_vendor["eligibility_status"] == "SUSPENDED"
        assert before_vendor["debarment_strike_count"] == 1
        assert _strike_ledger_total(vendor_id) == 1
        assert before_vendor["debarment_strike_count"] == _strike_ledger_total(vendor_id)

        before_proceeding = fx.read_proceeding(state["proceeding_id"])
        assert before_proceeding["status"] == "HEARING_HELD"
        assert before_proceeding["interim_status"] == "INTERIM_SUSPENDED"
        assert before_proceeding["strikes_applied"] == 1
        assert _instant(before_proceeding["notice_issued_at_utc"]) == _instant(
            NOTICE_INSTANT
        )

        dismissed = validate_success(_dismiss(state["proceeding_id"]), expected_status=200)

        # And it holds again at zero, with no residual strike anywhere.
        after_vendor = fx.read_vendor(vendor_id)
        assert after_vendor["debarment_strike_count"] == 0
        assert _strike_ledger_total(vendor_id) == 0
        assert after_vendor["debarment_strike_count"] == _strike_ledger_total(vendor_id)
        assert sum(row["strikes_applied"] for row in _proceedings_of(vendor_id)) == 0

        assert dismissed["status"] == "DISMISSED"
        assert dismissed["interim_status"] == "INTERIM_LIFTED"

    def test_the_dismissal_reverses_every_field_the_interim_suspension_set(self):
        """Where an interim suspension was in force, the dismissal compensates it: `strikes_applied` moves from 1 back to 0, `interim_status` moves `INTERIM_SUSPENDED → INTERIM_LIFTED`, the respondent moves `SUSPENDED → ELIGIBLE` with `active_debarment_id` and `suspension_reason_code` both cleared to null, and `debarment_strike_count` is recomputed and so decreases by 1.

        Design: Difficulty/compensating_invariant/debarment_strike_count_is_conserved_across_an_interim_suspension_dismissal
        """
        state = _suspended_respondent_awaiting_decision()
        vendor_id = state["vendor_id"]

        before_vendor = fx.read_vendor(vendor_id)
        before_proceeding = fx.read_proceeding(state["proceeding_id"])
        assert before_vendor["active_debarment_id"] == state["proceeding_id"]
        assert before_vendor["suspension_reason_code"] == "FRAUD"

        dismissed = validate_success(_dismiss(state["proceeding_id"]), expected_status=200)
        after_vendor = fx.read_vendor(vendor_id)

        # Each component moves by exactly one strike, in opposite directions to
        # the credit the notice made, so the pair nets to zero.
        assert (
            dismissed["strikes_applied"] - before_proceeding["strikes_applied"] == -1
        )
        assert (
            after_vendor["debarment_strike_count"]
            - before_vendor["debarment_strike_count"]
            == -1
        )
        assert dismissed["strikes_applied"] == 0
        assert after_vendor["debarment_strike_count"] == 0

        assert dismissed["interim_status"] == "INTERIM_LIFTED"
        assert dismissed["status"] == "DISMISSED"
        assert _instant(dismissed["decided_at_utc"]) == _instant(HEARING_INSTANT)
        assert dismissed["debarment_period_months"] == 0
        assert dismissed["debarment_start_utc"] is None
        assert dismissed["debarment_end_utc"] is None

        assert after_vendor["eligibility_status"] == "ELIGIBLE"
        assert after_vendor["active_debarment_id"] is None
        assert after_vendor["suspension_reason_code"] is None
        assert after_vendor["reinstatement_earliest_petition_utc"] is None

        # A vendor back in good standing is off the public list.
        listed, _meta = validate_paginated(
            api_client.list_debarred_vendors(DEBARMENT_AUTHORITY_HEADERS)
        )
        assert vendor_id not in [row["id"] for row in listed]
