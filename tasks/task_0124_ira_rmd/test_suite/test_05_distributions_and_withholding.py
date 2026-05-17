"""Distributions and federal withholding.

Coverage targets (PRD §3.4):
- Withholding rates by distribution_reason:
  CONVERSION=0%, RMD=10%, NORMAL=10%, EARLY (<59)=20% combined,
  DEATH=0%, EXCESS_REMOVAL=0%.
- net_amount_cents = gross - federal_withholding_cents (exact
  integer).
- Insufficient balance -> ERR_INSUFFICIENT_BALANCE.
- Distribution debits Account.balance_cents.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_distribution_event,
    assert_distribution_net_invariant,
    create_distribution_payload,
    create_participant_born,
    get_account,
    open_account,
    post_contribution,
    setup_traditional_to_roth_pair,
    validate_error,
    validate_success,
)


# ===========================================================================
# Withholding rate matrix — PRD §3.4
# ===========================================================================
class TestWithholdingRates:

    def test_normal_distribution_withholds_10_percent(
        self, api, custodian_headers,
    ):
        """PRD §3.4: "For distribution_reason equal to NORMAL, the
        mandatory normal rate of 10% applies."

        Claim: NORMAL distribution of 100_000 withholds 10_000 cents.
        """
        p = create_participant_born(1960)  # well over 59
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000,
                          contribution_type="REGULAR")
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=100_000,
                distribution_reason="NORMAL",
            ),
            custodian_headers,
        )
        d = validate_success(resp, expected_status=201)
        assert_distribution_event(d)
        assert d["federal_withholding_cents"] == 10_000
        assert d["net_amount_cents"] == 90_000

    def test_early_distribution_under_59_withholds_20_percent_combined(
        self, api, custodian_headers,
    ):
        """PRD §3.4: "For distribution_reason equal to EARLY when the
        participant is strictly younger than 59 in the clock year, the
        rate is the standard 10% mandatory rate plus an additional 10%
        early adder, for a combined rate of 20%. The 20% rate is
        applied as a single multiplication followed by a single
        half-up rounding to whole cents — not as two separate 10%
        withholdings rounded independently."

        Claim: EARLY at age < 59 withholds 20% in a single rounding
        step; 100_000 gross -> 20_000 withholding -> 80_000 net.
        """
        p = create_participant_born(1990)  # age << 59
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000,
                          contribution_type="REGULAR")
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=100_000,
                distribution_reason="EARLY",
            ),
            custodian_headers,
        )
        d = validate_success(resp, expected_status=201)
        assert d["federal_withholding_cents"] == 20_000
        assert d["net_amount_cents"] == 80_000
        assert_distribution_net_invariant(d)

    def test_death_distribution_withholds_zero(self, api,
                                               custodian_headers):
        """PRD §3.4: "For distribution_reason equal to DEATH, no
        mandatory withholding applies (0%)."

        Claim: DEATH distribution withholds 0; net == gross.
        """
        p = create_participant_born(1985)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000)
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=300_000,
                distribution_reason="DEATH",
            ),
            custodian_headers,
        )
        d = validate_success(resp, expected_status=201)
        assert d["federal_withholding_cents"] == 0
        assert d["net_amount_cents"] == 300_000


# ===========================================================================
# Net invariant — PRD §3.4
# ===========================================================================
class TestNetAmountInvariant:

    def test_net_equals_gross_minus_withholding(self, api,
                                                custodian_headers):
        """PRD §3.4: "The net_amount_cents is then the exact integer
        difference gross_amount_cents minus federal_withholding_cents
        — no further rounding occurs at the subtraction step."

        Claim: net_amount_cents == gross - withholding exactly.
        """
        p = create_participant_born(1960)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000)
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=123_457,  # odd value
                distribution_reason="NORMAL",
            ),
            custodian_headers,
        )
        d = validate_success(resp, expected_status=201)
        assert (
            d["net_amount_cents"]
            == d["gross_amount_cents"] - d["federal_withholding_cents"]
        )


# ===========================================================================
# Insufficient balance — PRD §3.4
# ===========================================================================
class TestInsufficientBalance:

    def test_distribution_exceeding_balance_rejected(
        self, api, custodian_headers,
    ):
        """PRD §3.4: "The system rejects distributions that would draw
        the balance negative with ERR_INSUFFICIENT_BALANCE (the check
        requires gross_amount_cents to be less than or equal to
        Account.balance_cents)."

        Claim: gross > balance -> ERR_INSUFFICIENT_BALANCE.
        """
        p = create_participant_born(1960)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=100_000)
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=200_000,
                distribution_reason="NORMAL",
            ),
            custodian_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)

    def test_distribution_at_exact_balance_succeeds(
        self, api, custodian_headers,
    ):
        """PRD §3.4: "The system rejects distributions that would draw
        the balance negative with ERR_INSUFFICIENT_BALANCE (the check
        requires gross_amount_cents to be less than or equal to
        Account.balance_cents)."

        Claim: gross == balance succeeds and zeros balance.
        """
        p = create_participant_born(1960)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=100_000)
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=100_000,
                distribution_reason="NORMAL",
            ),
            custodian_headers,
        )
        validate_success(resp, expected_status=201)
        a2 = get_account(p["id"], a["id"])
        assert a2["balance_cents"] == 0
