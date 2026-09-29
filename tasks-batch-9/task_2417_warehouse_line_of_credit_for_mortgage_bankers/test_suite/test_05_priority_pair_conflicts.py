"""Pairs of rules a single request violates at once.

The ladder decides which `error_id` the caller sees, so each pair is exercised
by clearing the higher rule and watching the identical request fall through to
the lower one.
"""

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


# ─── Facility posture outranks the fiscal tier ────────────────────────────────

def _exhaust_the_line_then_restrict_it():
    """Zero availability and a `RESTRICTED` posture on the same facility."""
    scenario = fx.setup_exhausted_facility()
    scenario.second_advance = fx.book_advance_ready_to_fund(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-502",
        loan_amount_cents=100_000_000,
    )
    scenario.advance = fx.mark_to_market(scenario.advance["id"], 900_000_000)
    scenario.margin_call = fx.first_open_margin_call(scenario.facility["id"])
    scenario.facility = fx.read_facility(scenario.facility["id"])
    return scenario


class TestFacilityStateOutranksAvailability:
    def test_a_restricted_line_reports_its_posture_not_its_headroom(self):
        """Priority 10 fires even though priority 38 is also violated.

        PRD 2.8: "This rule sits above every fiscal rule: a suspended facility
        whose availability is also exhausted reports `ERR_FACILITY_NOT_ACTIVE`,
        never `ERR_FACILITY_AVAILABILITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_facility_state_outranks_availability_fiscal
        """
        scenario = _exhaust_the_line_then_restrict_it()

        assert scenario.facility["status"] == "RESTRICTED"
        assert scenario.facility["availability_cents"] == 0
        assert scenario.margin_call["call_amount_cents"] == 100_000_000

        validate_error(
            api_client.fund_advance(
                scenario.second_advance["id"], COLLATERAL_ANALYST
            ),
            ApiErrorId.ERR_FACILITY_NOT_ACTIVE,
        )

    def test_waiving_the_call_restores_the_posture_but_not_the_headroom(self):
        """With the higher rule cleared the same call falls to the fiscal tier.

        PRD 2.8: "`availability_cents` is strictly greater than zero at the
        moment of funding, failing with `ERR_FACILITY_AVAILABILITY_EXCEEDED`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_facility_state_outranks_availability_fiscal
        """
        scenario = _exhaust_the_line_then_restrict_it()

        fx.waive_margin_call(
            scenario.margin_call["id"],
            reason="Third-party appraisal supports par valuation",
            officer_user_id="co_1",
        )
        facility = fx.read_facility(scenario.facility["id"])
        assert facility["status"] == "ACTIVE"
        # The waiver is audit-only, so the line is still fully drawn.
        assert facility["availability_cents"] == 0
        assert facility["outstanding_principal_cents"] == 1_000_000_000

        validate_error(
            api_client.fund_advance(
                scenario.second_advance["id"], COLLATERAL_ANALYST
            ),
            ApiErrorId.ERR_FACILITY_AVAILABILITY_EXCEEDED,
        )

        # The refused advance is untouched and nothing was written.
        unfunded = fx.read_advance(scenario.second_advance["id"])
        assert unfunded["funding_status"] == "REQUESTED"
        assert unfunded["outstanding_balance_cents"] == 0
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 1_000_000_000


# ─── Investor approval outranks the allocation match ──────────────────────────

def _offer_the_file_to_three_investors():
    """One suspended investor, one unallocated investor, one that owns the deal."""
    scenario = fx.setup_funded_dry_advance()
    scenario.suspended_investor = fx.register_investor(
        scenario.facility["id"],
        investor_name="Bravo Capital Markets",
        counterparty_rating="B",
        concentration_limit_pct=0.60,
    )
    fx.suspend_investor(
        scenario.suspended_investor["id"],
        reason="Failed to fund two prior take-outs",
    )
    scenario.unallocated_investor = fx.register_investor(
        scenario.facility["id"],
        investor_name="Charlie Loan Trust",
        counterparty_rating="A",
        concentration_limit_pct=0.60,
    )
    return scenario


class TestInvestorApprovalOutranksAllocationMatch:
    def test_a_suspended_investor_hides_the_allocation_mismatch(self):
        """Priority 25 fires before priority 27 gets a chance to.

        PRD 2.8: "Because this rule outranks every constraint rule, a suspended
        investor whose commitment also mismatches reports
        `ERR_INVESTOR_NOT_APPROVED`, never `ERR_COMMITMENT_INVESTOR_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_investor_referential_outranks_commitment_constraint
        """
        scenario = _offer_the_file_to_three_investors()

        validate_error(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.suspended_investor["id"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_INVESTOR_NOT_APPROVED,
        )

        validate_error(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.unallocated_investor["id"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_COMMITMENT_INVESTOR_MISMATCH,
        )

        # Neither refusal moved either axis of the advance.
        untouched = fx.read_advance(scenario.advance["id"])
        assert untouched["funding_status"] == "FUNDED"
        assert untouched["custody_status"] == "RECEIVED_CLEAR"

    def test_only_the_allocated_investor_receives_the_collateral_file(self):
        """The one investor behind the commitment is the only legal destination.

        PRD 2.8: "The shipment's target is the advance's own
        `investor_commitment_id`, and that commitment's `investor_id` equals the
        `investor_id` in the request, failing with
        `ERR_COMMITMENT_INVESTOR_MISMATCH` (422). Collateral cannot be
        bailee-shipped to any investor other than the one whose commitment it
        was allocated against."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_investor_referential_outranks_commitment_constraint
        """
        scenario = _offer_the_file_to_three_investors()

        for rejected in (
            scenario.suspended_investor["id"],
            scenario.unallocated_investor["id"],
        ):
            response = api_client.ship_advance(
                scenario.advance["id"], make.ship_payload(rejected), COLLATERAL_ANALYST
            )
            assert response.status_code in (422,)

        validate_success(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.investor["id"]),
                COLLATERAL_ANALYST,
            ),
            expected_status=201,
        )

        letters, meta = validate_paginated(
            api_client.list_advance_bailee_letters(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        # The two refusals issued nothing; only the accepted shipment did.
        assert meta["total_count"] == 1
        asserts.assert_bailee_letter(letters[0])
        assert letters[0]["investor_id"] == scenario.investor["id"]
        assert letters[0]["status"] == "ISSUED"

        shipped = fx.read_advance(scenario.advance["id"])
        assert shipped["funding_status"] == "SHIPPED"
        assert shipped["custody_status"] == "RELEASED_TO_INVESTOR"
