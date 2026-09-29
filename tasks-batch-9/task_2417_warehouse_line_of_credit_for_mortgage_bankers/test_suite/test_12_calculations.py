"""Calculation corners: pinned rounding order, cap chains and constants.

Every figure here is chosen so that a plausible but wrong arithmetic order
produces a visibly different number — a cent, a flag or a whole rejection.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── The two-bucket cure waterfall ───────────────────────────────────────────

def _two_funded_advances_and_ten_days_of_fees():
    """A1 funded at midnight and A2 six hours later, then one aging run.

    The staggered `created_at` values fix which advance receives the single
    leftover cent of the principal split.
    """
    scenario = fx.setup_funded_dry_advance()

    fx.set_clock("2026-08-01T06:00:00Z")
    scenario.second_advance = fx.book_and_fund_additional_advance(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-902",
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
    )

    fx.set_clock("2026-08-11T00:00:00Z")
    scenario.aging_run = fx.run_aging(scenario.facility["id"])
    return scenario


class TestCurePaymentWaterfall:
    def test_fees_fill_first_and_the_leftover_cent_goes_to_the_older_advance(self):
        """67 and 33, never 66/34: floor per advance, then walk oldest first.

        PRD 3.6: "First, each covered advance's share is
        `applied_to_principal_cents` multiplied by that advance's
        `outstanding_balance_cents`, divided by the total
        `outstanding_balance_cents` across the covered set, floored to whole
        cents. Second, the leftover — the principal amount less the sum of those
        floored shares — is distributed one single cent at a time, walking the
        covered advances in `created_at` ascending order until the leftover is
        exhausted."

        Design: Corner/calculations/corner_calc_cure_waterfall_fees_first_then_prorata_remainder
        """
        scenario = _two_funded_advances_and_ten_days_of_fees()
        assert scenario.second_advance["advance_amount_cents"] == 980_000_000
        # 4,763,889 (A1) + 2,313,889 (A2) + 1,184,722 (unused line).
        assert scenario.aging_run["fee_accrual_cents"] == 8_262_500

        call = fx.raise_manual_margin_call(scenario.facility["id"])
        asserts.assert_margin_call(call)
        # floor(2,940,000,000 * 0.10).
        assert call["call_amount_cents"] == 294_000_000
        assert call["advance_id"] is None

        payment = fx.post_cure_payment(
            call["id"], scenario.facility["id"], 8_262_600
        )
        asserts.assert_cure_payment(payment)
        # Bucket one absorbs the whole fee balance before principal is touched.
        assert payment["applied_to_fees_cents"] == 8_262_500
        assert payment["applied_to_principal_cents"] == 100

        allocation = payment["principal_allocation"]
        assert len(allocation) == 2
        assert allocation[0]["advance_id"] == scenario.advance["id"]
        assert allocation[0]["amount_cents"] == 67
        assert allocation[1]["advance_id"] == scenario.second_advance["id"]
        assert allocation[1]["amount_cents"] == 33

        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_959_999_933
        assert fx.read_advance(scenario.second_advance["id"])[
            "outstanding_balance_cents"
        ] == 979_999_967

        cured = fx.read_margin_call(call["id"])
        assert cured["cured_amount_cents"] == 100
        assert cured["status"] == "PARTIALLY_CURED"

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["accrued_fee_balance_cents"] == 0
        assert facility["outstanding_principal_cents"] == 2_939_999_900
        # A partial cure does not lift the restriction.
        assert facility["status"] == "RESTRICTED"

        entries, meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 6
        asserts.assert_entry_types_in_order(
            entries,
            [
                ("ADVANCE_FUNDED", "DEBIT"),
                ("ADVANCE_FUNDED", "DEBIT"),
                ("FEE_ACCRUAL", "DEBIT"),
                ("FEE_PAYMENT", "CREDIT"),
                ("CURE_PRINCIPAL", "CREDIT"),
                ("CURE_PRINCIPAL", "CREDIT"),
            ],
        )
        assert entries[3]["amount_cents"] == 8_262_500
        assert entries[3]["advance_id"] is None
        assert entries[4]["amount_cents"] == 67
        assert entries[4]["advance_id"] == scenario.advance["id"]
        assert entries[5]["amount_cents"] == 33
        assert entries[5]["advance_id"] == scenario.second_advance["id"]

    def test_a_requested_advance_is_outside_the_covered_set_entirely(self):
        """A facility-level call allocates only across carrying advances.

        PRD 3.6: "When the call names an `advance_id`, the covered set is that
        single advance; when the call is facility-level, the covered set is every
        advance of the facility whose `funding_status` is `FUNDED` or `SHIPPED`,
        ordered by `created_at` ascending — advances in `REQUESTED`, `REJECTED`,
        `PURCHASED` or `REPURCHASED` never receive an allocation."

        Design: Corner/calculations/corner_calc_waterfall_covered_set_excludes_noncarrying_advances
        """
        scenario = fx.setup_funded_dry_advance()
        idle = fx.book_advance(
            scenario.facility["id"],
            scenario.custodian["id"],
            investor_commitment_id=scenario.commitment["id"],
            loan_amount_cents=300_000_000,
            note_rate=0.0700,
        )

        call = fx.raise_manual_margin_call(scenario.facility["id"])
        # The requested advance contributes nothing to outstanding principal.
        assert call["call_amount_cents"] == 196_000_000

        payment = fx.post_cure_payment(
            call["id"], scenario.facility["id"], 50_000_000
        )
        asserts.assert_cure_payment(payment)
        # No aging run has been executed, so the first bucket is empty.
        assert payment["applied_to_fees_cents"] == 0
        assert payment["applied_to_principal_cents"] == 50_000_000

        allocation = payment["principal_allocation"]
        assert len(allocation) == 1
        assert allocation[0]["advance_id"] == scenario.advance["id"]
        assert allocation[0]["amount_cents"] == 50_000_000

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(idle["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 0

        untouched = fx.read_advance(idle["id"])
        assert untouched["funding_status"] == "REQUESTED"
        assert untouched["outstanding_balance_cents"] == 0

        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_910_000_000

        cured = fx.read_margin_call(call["id"])
        assert cured["cured_amount_cents"] == 50_000_000
        assert cured["status"] == "PARTIALLY_CURED"


# ─── Constants at their exact boundaries ─────────────────────────────────────

def _two_commitments_straddling_the_minimum_advance():
    """One commitment of 999,999 cents and one of exactly 1,000,000."""
    scenario = fx.setup_facility_panel(with_commitment=False)

    scenario.investor_b = fx.register_investor(
        scenario.facility["id"],
        investor_name="Bravo Conduit",
        counterparty_rating="A",
        concentration_limit_pct=0.60,
    )
    scenario.commitment_b = fx.record_commitment(
        scenario.facility["id"],
        scenario.investor_b["id"],
        committed_amount_cents=999_999,
        price_pct=1.0100,
        effective_on="2026-08-01",
        expires_on="2026-12-31",
    )
    scenario.investor_c = fx.register_investor(
        scenario.facility["id"],
        investor_name="Charlie Securitizer",
        counterparty_rating="A",
        concentration_limit_pct=0.60,
    )
    scenario.commitment_c = fx.record_commitment(
        scenario.facility["id"],
        scenario.investor_c["id"],
        committed_amount_cents=1_000_000,
        price_pct=1.0100,
        effective_on="2026-08-01",
        expires_on="2026-12-31",
    )

    # Wet advances so that no custodian receipt is needed before funding.
    scenario.advance_b = fx.book_advance_ready_to_fund(
        scenario,
        investor_commitment_id=scenario.commitment_b["id"],
        callback_reference="CB-960",
        funding_type="WET",
        loan_amount_cents=2_000_000_000,
        note_rate=0.0650,
    )
    scenario.advance_c = fx.book_advance_ready_to_fund(
        scenario,
        investor_commitment_id=scenario.commitment_c["id"],
        callback_reference="CB-961",
        funding_type="WET",
        loan_amount_cents=2_000_000_000,
        note_rate=0.0650,
    )
    return scenario


class TestMinimumAdvanceSizeBoundary:
    def test_one_cent_under_the_floor_fails_and_the_floor_itself_funds(self):
        """The comparison is at-least, so exactly 1,000,000 is fundable.

        PRD 2.8: "The stage-four result of the sizing waterfall — the amount
        after every hard cap but before the concentration solve — is at least the
        minimum advance size, failing funding with `ERR_ADVANCE_BELOW_MINIMUM`
        (422)."

        Design: Corner/calculations/corner_calc_min_advance_cents_constant_boundary
        """
        scenario = _two_commitments_straddling_the_minimum_advance()

        # Remaining capacity is 999,999, which is positive, so the fiscal tier
        # is satisfied and the minimum-size rule is what refuses.
        validate_error(
            api_client.fund_advance(scenario.advance_b["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_ADVANCE_BELOW_MINIMUM,
        )
        refused = fx.read_advance(scenario.advance_b["id"])
        assert refused["funding_status"] == "REQUESTED"
        assert refused["advance_amount_cents"] == 0
        # A rejected funding does not release the wire.
        assert fx.wire_for_advance(scenario.advance_b["id"])["status"] == "VERIFIED"

        funded = validate_success(
            api_client.fund_advance(scenario.advance_c["id"], COLLATERAL_ANALYST)
        )
        asserts.assert_advance(funded)
        assert funded["advance_amount_cents"] == 1_000_000
        # floor(2,000,000,000 * (0.98 - 0.02)) before any cap binds.
        assert funded["provisional_advance_amount_cents"] == 1_920_000_000
        # The binding cap was commitment capacity, not the concentration solve.
        assert funded["concentration_capped"] is False

        exhausted = fx.read_commitment(scenario.commitment_c["id"])
        assert exhausted["remaining_amount_cents"] == 0
        assert exhausted["status"] == "FULLY_ALLOCATED"

        idle = fx.read_commitment(scenario.commitment_b["id"])
        assert idle["allocated_amount_cents"] == 0
        assert idle["status"] == "OPEN"

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 1_000_000
        assert facility["wet_outstanding_cents"] == 1_000_000


class TestProvisionalAgainstFinalAmount:
    def test_both_variants_persist_and_only_the_final_one_is_posted(self):
        """A stage-four cap reduces the amount without setting the flag.

        PRD 3.4: "The waterfall's output is stored as `advance_amount_cents`, and
        `concentration_capped` is set true exactly when stage five reduced the
        amount below the stage-four result and false otherwise."

        Design: Corner/calculations/corner_calc_cap_chain_reconciles_provisional_against_final
        """
        scenario = fx.setup_facility_panel(with_commitment=False)
        investor = fx.register_investor(
            scenario.facility["id"],
            investor_name="Delta Whole Loan Fund",
            counterparty_rating="A",
            concentration_limit_pct=0.60,
        )
        commitment = fx.record_commitment(
            scenario.facility["id"],
            investor["id"],
            committed_amount_cents=1_500_000_000,
            price_pct=1.0150,
            effective_on="2026-08-01",
            expires_on="2026-12-31",
        )
        advance = fx.book_advance_ready_to_fund(
            scenario,
            investor_commitment_id=commitment["id"],
            callback_reference="CB-970",
            funding_type="WET",
            loan_amount_cents=2_000_000_000,
            note_rate=0.0650,
        )

        funded = fx.fund_advance(advance["id"])
        asserts.assert_advance(funded)
        # The provisional variant ignores every cap.
        assert funded["provisional_advance_amount_cents"] == 1_920_000_000
        assert funded["advance_amount_cents"] == 1_500_000_000
        # The hypothetical outstanding is under the de-minimis floor.
        assert funded["concentration_capped"] is False
        assert funded["outstanding_balance_cents"] == 1_500_000_000

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(advance["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"
        assert entries[0]["direction"] == "DEBIT"
        # The provisional figure is never posted.
        assert entries[0]["amount_cents"] == 1_500_000_000

        settled = fx.read_commitment(commitment["id"])
        assert settled["allocated_amount_cents"] == 1_500_000_000
        assert settled["remaining_amount_cents"] == 0
        assert settled["status"] == "FULLY_ALLOCATED"

        assert fx.read_investor(investor["id"])["exposure_cents"] == 1_500_000_000
        assert fx.read_facility(scenario.facility["id"])["availability_cents"] == (
            18_500_000_000
        )


class TestOrphanRateIsACap:
    def test_withdrawal_caps_the_rate_rather_than_scaling_the_eligible_value(self):
        """0.85 replaces 0.98 only because it is the smaller of the two.

        PRD 3.6: "The fourth step is the orphan cap: when the advance names no
        commitment, or the commitment it names is `WITHDRAWN` or `EXPIRED`, the
        rate is replaced by the smaller of itself and 0.85."

        Design: Corner/calculations/corner_calc_orphan_rate_constant_applied_on_withdrawal
        """
        scenario = fx.setup_funded_dry_advance()
        assert scenario.advance["effective_advance_rate"] == pytest.approx(
            0.98, abs=1e-6
        )
        assert scenario.advance["required_paydown_cents"] == 0

        withdrawn = fx.withdraw_commitment(
            scenario.commitment["id"],
            reason="Investor exited the CONFORMING program",
        )
        assert withdrawn["status"] == "WITHDRAWN"

        orphaned = fx.read_advance(scenario.advance["id"])
        assert orphaned["effective_advance_rate"] == pytest.approx(0.85, abs=1e-6)
        # floor(min(2,000,000,000, 2,000,000,000) * 0.85).
        assert orphaned["eligible_collateral_value_cents"] == 1_700_000_000
        assert orphaned["required_paydown_cents"] == 260_000_000

        calls = fx.advance_margin_calls(scenario.advance["id"])
        assert len(calls) == 1
        asserts.assert_margin_call(calls[0])
        assert calls[0]["trigger_reason"] == "COMMITMENT_WITHDRAWN"
        assert calls[0]["status"] == "ISSUED"
        assert calls[0]["call_amount_cents"] == 260_000_000
        asserts.assert_instant(calls[0]["cure_deadline_at"], "2026-08-03T00:00:00Z")

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["status"] == "RESTRICTED"
        assert facility["open_margin_call_count"] == 1
        # A re-valuation moves no money.
        assert facility["outstanding_principal_cents"] == 1_960_000_000


class TestZeroMarginCallAmount:
    def test_both_sizing_arms_refuse_rather_than_persist_a_zero_call(self):
        """A fully collateralised advance and an undrawn facility both refuse.

        PRD 3.6: "A call whose computed amount works out to zero is never
        created: the system silently skips such a call when it would have issued
        one automatically, and a manual attempt is refused with
        `ERR_MARGIN_CALL_AMOUNT_ZERO`."

        Design: Corner/calculations/corner_calc_zero_call_amount_is_refused_not_created
        """
        scenario = fx.setup_funded_dry_advance()
        assert scenario.advance["required_paydown_cents"] == 0
        assert scenario.advance["eligible_collateral_value_cents"] == 1_960_000_000

        validate_error(
            api_client.create_margin_call(
                make.margin_call_payload(
                    scenario.facility["id"],
                    "DWELL_EXCEEDED",
                    advance_id=scenario.advance["id"],
                ),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_MARGIN_CALL_AMOUNT_ZERO,
        )

        undrawn = fx.create_active_facility(
            facility_overrides={
                "borrower_legal_name": "Keystone Home Loans Inc",
                "settlement_account_last4": "8802",
            }
        )
        # floor(0 * 0.10) is zero, so the facility-level arm refuses too.
        validate_error(
            api_client.create_margin_call(
                make.margin_call_payload(undrawn["id"], "COVENANT_BREACH"),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_MARGIN_CALL_AMOUNT_ZERO,
        )

        accepted = fx.raise_manual_margin_call(scenario.facility["id"], cure_days=5)
        assert accepted["call_amount_cents"] == 196_000_000
        # The supplied cure_days overrides the two-day default.
        asserts.assert_instant(
            accepted["cure_deadline_at"], "2026-08-06T00:00:00Z"
        )
        assert accepted["issued_by_user_id"] == "co_1"
        assert accepted["cured_amount_cents"] == 0

        # Neither refused call was persisted.
        _calls, meta = validate_paginated(
            api_client.list_facility_margin_calls(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1

        quiet = fx.read_facility(undrawn["id"])
        assert quiet["status"] == "ACTIVE"
        assert quiet["open_margin_call_count"] == 0
        assert fx.read_facility(scenario.facility["id"])["status"] == "RESTRICTED"


class TestSizingAlwaysFloors:
    def test_an_exact_half_cent_is_truncated_in_both_calculations(self):
        """980,000,024.50 becomes 980,000,024 at sizing and at valuation.

        PRD 3.4: "The rate from stage two is multiplied by `loan_amount_cents`
        and the product is floored to whole cents — truncated toward zero, never
        rounded half up, so the lender never over-advances by a rounding cent."

        Design: Corner/calculations/corner_calc_advance_sizing_floors_never_rounds_half_up
        """
        scenario = fx.setup_advance_ready_to_fund(
            advance_overrides={"loan_amount_cents": 1_000_000_025},
            callback_reference="CB-980",
        )

        funded = fx.fund_advance(scenario.advance["id"])
        asserts.assert_advance(funded)
        assert funded["advance_amount_cents"] == 980_000_024
        assert funded["eligible_collateral_value_cents"] == 980_000_024
        # An exact four-decimal rate survives the half-up rounding untouched.
        assert funded["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
        assert funded["required_paydown_cents"] == 0
        assert funded["outstanding_balance_cents"] == 980_000_024

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 980_000_024
        assert facility["availability_cents"] == 19_019_999_976
