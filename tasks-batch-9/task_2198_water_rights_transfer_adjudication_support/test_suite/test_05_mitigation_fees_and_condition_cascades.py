"""Mitigation-fee pricing and the condition-violation cascade.

PRD §3.8: "Pricing a mitigation payment runs in a pinned order, because the
surcharge tier depends on the fee and the surcharge is a percentage of the fee."
"""
import pytest
from test_helpers import ApiErrorId, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    ANALYST,
    add_injury_analysis,
    condition_entry,
    conditions_of,
    decide,
    deposit,
    draft_application,
    open_account,
    publish_application,
    read_account,
    read_claimant,
    read_condition,
    read_lease,
    read_right,
    reserve_lease,
    set_clock,
    setup_application_ready_for_decision,
    setup_certified_right,
    submit_application,
)


class TestMitigationFeeTierComesFromThePreSurchargeSubtotal:
    """PRD §3.8 — "the tier is selected from that pre-surcharge subtotal and
    never from the final total".

    A 50.00 AF change of use analysed under `SEASONAL_AVERAGE` grosses
    50.00 * 0.78 = 39.00 with no credits, so 39.00 AF of net injury must be
    mitigated. The decision imposes a 39.90 AF mitigation payment, which prices
    just below the first tier boundary while its total lands just above it — the
    one figure that distinguishes the two readings.
    """

    CONDITIONS = [
        condition_entry("MITIGATION_PAYMENT", 39.90, "2026-09-01T00:00:00Z")
    ]

    def _decided(self):
        bundle = setup_application_ready_for_decision(
            requested_af=50.00, deadline_reached_at="2026-03-31T00:00:00Z"
        )
        assert bundle["analysis"]["status"] == "FINALIZED"
        assert bundle["analysis"]["gross_depletion_af"] == pytest.approx(39.00, abs=0.01)
        assert bundle["analysis"]["net_injury_af"] == pytest.approx(39.00, abs=0.01)
        bundle["application"] = decide(
            bundle["application"]["id"],
            "APPROVE_WITH_CONDITIONS",
            conditions=self.CONDITIONS,
        )
        bundle["conditions"] = conditions_of(bundle["application"]["id"])
        return bundle

    def test_tier_is_read_from_the_base_fee_not_from_the_total(self):
        """PRD §3.8: "a `base_fee_usd` strictly below 5,000.00 dollars takes a
        `surcharge_pct` of 0.040, a `base_fee_usd` from 5,000.00 up to but not
        including 20,000.00 takes 0.070".

        39.90 * 125.00 is 4,987.50, which is strictly below 5,000.00 and so takes
        0.040, giving an admin surcharge of 199.50 and a total of 5,187.00. Reading
        the tier off the 5,187.00 total instead would take 0.070 and produce a
        surcharge of 349.13 and a total of 5,336.63.

        Design: Difficulty/combinatorial_formula/mitigation_fee_tier_on_presurcharge_subtotal
        """
        bundle = self._decided()

        assert len(bundle["conditions"]) == 1
        condition = read_condition(bundle["conditions"][0]["id"])
        assert condition["condition_type"] == "MITIGATION_PAYMENT"
        assert condition["required_af"] == pytest.approx(39.90, abs=0.01)
        assert condition["base_fee_usd"] == pytest.approx(4987.50, abs=0.01)
        assert condition["surcharge_pct"] == pytest.approx(0.040, abs=0.0005)
        assert condition["admin_surcharge_usd"] == pytest.approx(199.50, abs=0.01)
        assert condition["total_fee_usd"] == pytest.approx(5187.00, abs=0.01)
        assert condition["admin_surcharge_usd"] != pytest.approx(349.13, abs=0.01), (
            "349.13 is the surcharge that follows from tiering off the total"
        )
        assert condition["total_fee_usd"] != pytest.approx(5336.63, abs=0.01)

    def test_conditional_approval_bills_the_claimant_and_moves_the_volume(self):
        """PRD §3.7: "the application's `mitigation_fee_total_usd` is set to the
        sum of the priced total fees ...; the claimant's
        `outstanding_fee_balance_usd` increases by that same sum and, when the
        balance rises above 0.00 while the claimant is `IN_GOOD_STANDING`,
        `standing_status` moves to `DELINQUENT`".

        PRD §3.8: "On the fiscal axis it begins at `NOT_APPLICABLE`, and it moves
        to `OUTSTANDING` at the moment of creation only when its `condition_type`
        is `MITIGATION_PAYMENT` and its `required_af` is strictly greater than
        zero." The same disposition performs the volume move, carrying 50.00 AF out
        of escrow and into `transferred_away_af`.

        Design: Difficulty/combinatorial_formula/mitigation_fee_tier_on_presurcharge_subtotal
        """
        bundle = self._decided()

        application = bundle["application"]
        assert application["status"] == "APPROVED_WITH_CONDITIONS"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert application["mitigation_fee_total_usd"] == pytest.approx(5187.00, abs=0.01)
        condition = read_condition(bundle["conditions"][0]["id"])
        assert condition["status"] == "IMPOSED"
        assert condition["payment_status"] == "OUTSTANDING"
        assert condition["source"] == "DECISION"
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(5187.00, abs=0.01)
        assert claimant["standing_status"] == "DELINQUENT"
        right = read_right(bundle["right"]["id"])
        assert right["transferred_away_af"] == pytest.approx(50.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(145.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"


class TestConditionViolationCascade:
    """PRD §3.8 — "This is the second four-link cascade and it reaches from a
    single condition all the way to a bank account's posture."

    One bank-enrolled right carries a conditionally approved 30.00 AF transfer
    whose `MEASUREMENT_DEVICE` condition falls due on 2026-05-01, a 60.00 AF bank
    deposit, and a 40.00 AF delivery lease active at its own authorized headgate.
    The clock is then advanced to 2026-06-01, past the compliance due date.
    """

    def _armed(self):
        bundle = setup_certified_right(
            bank_enrolled=True, pod_specs=[{"max_rate_cfs": 5.000}]
        )
        right_id = bundle["right"]["id"]
        pod = bundle["pods"][0]
        application = draft_application(right_id, bundle["study"]["id"], 30.00)
        submit_application(application["id"], right_id)
        # PRD §3.5 — the return-flow credit exactly cancels the 23.40 gross
        # depletion, so no mitigation volume is required by PRD §3.7.
        add_injury_analysis(
            application["id"], "SEASONAL_AVERAGE", 0.00, return_flow_credit_af=23.40
        )
        publish_application(application["id"])
        set_clock("2026-03-31T00:00:00Z")
        get_success_data(api_client.close_protest_period(application["id"], ANALYST))
        bundle["application"] = decide(
            application["id"],
            "APPROVE_WITH_CONDITIONS",
            conditions=[
                condition_entry("MEASUREMENT_DEVICE", 5.00, "2026-05-01T00:00:00Z")
            ],
        )
        bundle["condition"] = conditions_of(application["id"])[0]
        account = open_account(bundle["claimant"]["id"])
        deposit(account["id"], right_id, 60.00)
        bundle["lease"] = get_success_data(
            reserve_lease(
                account["id"],
                right_id,
                pod["id"],
                "2026-04-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                40.00,
                diversion_rate_cfs=1.500,
            )
        )
        set_clock("2026-04-05T00:00:00Z")
        bundle["lease"] = get_success_data(
            api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        )
        set_clock("2026-06-01T00:00:00Z")
        bundle["account"] = read_account(account["id"])
        bundle["right"] = read_right(right_id)
        bundle["pod"] = pod
        return bundle

    def test_violation_suspends_the_right_and_freezes_the_funding_account(self):
        """PRD §3.8: "The condition moves `IMPOSED → VIOLATED` and its `version`
        is bumped. The water right behind the application moves to `SUSPENDED` —
        reachable from `ACTIVE`, from `ENCUMBERED` or from `PARTIALLY_TRANSFERRED`
        — its forfeiture score is recomputed with the twelve-point suspension
        penalty now applying".

        PRD §3.8: "Every lease assignment on that right currently in `ACTIVE`
        moves `ACTIVE → SUSPENDED`, its `suspension_count` is incremented, and on
        its funding account the lease's `requested_af` moves out of `leased_out_af`
        and back into `committed_credit_af`, leaving `available_credit_af`
        untouched so the credit identity is conserved."

        The score moves 60.50 -> 72.50, which crosses out of `ELEVATED` and into
        `HIGH`, and the account lands on `FROZEN` on one suspended lease alone.

        Design: Difficulty/transitive_cascade/condition_violation_suspension_cascade
        """
        bundle = self._armed()
        assert bundle["right"]["status"] == "PARTIALLY_TRANSFERRED"
        assert bundle["right"]["forfeiture_risk_score"] == pytest.approx(60.50, abs=0.01)
        assert bundle["right"]["forfeiture_risk_band"] == "ELEVATED"
        assert bundle["lease"]["status"] == "ACTIVE"
        assert bundle["account"]["leased_out_af"] == pytest.approx(40.00, abs=0.01)
        assert bundle["account"]["posture"] == "OPEN"

        condition = get_success_data(
            api_client.violate_approval_condition(
                bundle["condition"]["id"], "No device installed at the headgate.", ANALYST
            )
        )

        assert condition["status"] == "VIOLATED"
        assert condition["payment_status"] == "NOT_APPLICABLE", (
            "the fiscal axis is untouched by a compliance failure"
        )
        right = read_right(bundle["right"]["id"])
        assert right["status"] == "SUSPENDED"
        assert right["forfeiture_risk_score"] == pytest.approx(72.50, abs=0.01)
        assert right["forfeiture_risk_band"] == "HIGH"
        lease = read_lease(bundle["lease"]["id"])
        assert lease["status"] == "SUSPENDED"
        assert lease["suspension_count"] == 1
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(60.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(40.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["suspended_lease_count"] == 1
        assert account["posture"] == "FROZEN"

    def test_reinstatement_is_refused_while_the_violation_stands(self):
        """PRD §3.2: "reinstatement becomes reachable at all" only once every
        violated condition is cured — PRD §3.8: "What curing does is clear the
        reinstatement gate, and curing every violated condition on a right is the
        only way reinstatement becomes reachable at all."

        The suspended right is therefore stuck: reinstatement is refused with
        `ERR_VIOLATION_UNRESOLVED` and the right stays `SUSPENDED` with its
        non-use history unchanged.

        Design: Difficulty/transitive_cascade/condition_violation_suspension_cascade
        """
        bundle = self._armed()
        get_success_data(
            api_client.violate_approval_condition(
                bundle["condition"]["id"], "No device installed at the headgate.", ANALYST
            )
        )

        response = api_client.reinstate_water_right(
            bundle["right"]["id"], "Holder asserts the device is now in place.", ANALYST
        )

        validate_error(
            response, ApiErrorId.ERR_VIOLATION_UNRESOLVED.value, expected_status=409
        )
        right = read_right(bundle["right"]["id"])
        assert right["status"] == "SUSPENDED"
        assert right["consecutive_nonuse_years"] == 7
        assert read_condition(bundle["condition"]["id"])["status"] == "VIOLATED"
