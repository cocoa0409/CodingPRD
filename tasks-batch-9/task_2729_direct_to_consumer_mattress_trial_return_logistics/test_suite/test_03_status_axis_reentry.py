"""Re-entry into an already-visited status on two different entities.

Both rules walk a status dimension back into a state it has already occupied,
which a one-way state machine cannot express.
"""

from test_helpers import (
    adjudicate_claim,
    api_client,
    assert_instant,
    assert_refund_ledger_identity,
    authorize_refund,
    file_quality_claim,
    get_success_data,
    read_order,
    read_refund,
    read_return_case,
    request_evidence,
    set_clock,
    setup_delivered_order,
    setup_return_lifecycle,
    submit_evidence_payload,
    void_refund,
)


class TestFulfillmentAxisCyclesBackToDeliveredWhileTheTrialAxisHolds:
    """A compression complaint filed on night four and settled inside the break-in window."""

    def _adjudicated_compression_claim(self):
        scenario = setup_delivered_order(
            model_overrides={"sku": "MDL-Q-MED-C", "name": "Comfort Q Medium"},
            customer_overrides={"email": "sm1@example.com", "household_hash": "HH-SM1"},
        )
        set_clock("2026-08-05T00:00:00Z")
        claim = file_quality_claim(
            scenario["order"]["id"],
            "COMPRESSION_RECOVERY",
            2,
            headers=scenario["customer_headers"],
        )
        scenario["order_after_filing"] = read_order(scenario["order"]["id"])
        request_evidence(claim["id"])
        get_success_data(
            api_client.submit_claim_evidence(
                claim["id"], submit_evidence_payload(2), scenario["customer_headers"]
            )
        )
        scenario["claim"] = adjudicate_claim(claim["id"], "CREDIT")
        return scenario

    def test_a_credit_adjudication_walks_the_fulfillment_axis_back_to_delivered(self):
        """PRD §3.4: "A `CREDIT` resolution prices `credit_cents` and then reverts the fulfillment axis `DAMAGED_REPORTED → DELIVERED`, releasing the order from its complaint state; when the order has meanwhile reached `CLOSED` or `REPLACED`, the fulfillment axis is left exactly as it is."

        Filing the complaint pushed the order to DAMAGED_REPORTED; one evidence
        round later a CREDIT adjudication pays the flat 7500-cent
        compression-recovery credit and puts the order back to DELIVERED, so the
        axis has visited DELIVERED twice.

        Design: Difficulty/non_linear_state_machine/fulfillment_axis_cycles_damaged_reported_back_to_delivered_while_trial_axis_holds_break_in
        """
        scenario = self._adjudicated_compression_claim()

        assert scenario["order_after_filing"]["fulfillment_status"] == "DAMAGED_REPORTED", (
            "filing a compression complaint moves the fulfillment axis to "
            "DAMAGED_REPORTED"
        )
        claim = scenario["claim"]
        assert claim["evidence_round_count"] == 1
        assert claim["status"] == "APPROVED"
        assert claim["resolution"] == "CREDIT"
        assert claim["credit_cents"] == 7500, (
            f"a compression-recovery credit is a flat 7500 cents, got "
            f"{claim['credit_cents']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "DELIVERED"

    def test_the_trial_axis_never_moves_while_the_fulfillment_axis_cycles(self):
        """PRD §2.12: "A trial order carries `fulfillment_status`, the physical-logistics axis, and `trial_status`, the trial-clock axis."

        The whole complaint loop happens on nights four through five of a
        21-night break-in window, so the trial axis is still BREAK_IN with its
        original 2026-08-22 boundary, and no money has been settled yet.

        Design: Difficulty/non_linear_state_machine/fulfillment_axis_cycles_damaged_reported_back_to_delivered_while_trial_axis_holds_break_in
        """
        scenario = self._adjudicated_compression_claim()
        order = read_order(scenario["order"]["id"])

        assert order["trial_status"] == "BREAK_IN", (
            f"the trial axis is untouched by the complaint loop, got "
            f"{order['trial_status']}"
        )
        assert_instant(order["break_in_ends_at"], "2026-08-22T00:00:00Z", "break_in_ends_at")
        assert order["goodwill_credit_cents"] == 0, (
            "goodwill only moves when finance settles the approved credit, got "
            f"{order['goodwill_credit_cents']}"
        )


class TestReturnCaseFinancialAxisReturnsToAuthorizedAfterVoid:
    """A voided authorization superseded by a fresh one on the same case."""

    def _superseded_authorization(self):
        scenario = setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={"sku": "MDL-Q-MED-S"},
            customer_overrides={"email": "sm2@example.com", "household_hash": "HH-SM2"},
        )
        first = scenario["refund"]
        void_refund(first["id"], void_reason="grade disputed by the warehouse")
        second = authorize_refund(
            scenario["return_case"]["id"], supersedes_refund_id=first["id"]
        )
        scenario["first_refund"] = read_refund(first["id"])
        scenario["second_refund"] = second
        return scenario

    def test_a_supersede_reference_walks_the_money_axis_void_back_to_authorized(self):
        """PRD §3.9: "A voided settlement can be re-authorized with a fresh row that points at the voided one, recomputed against whatever the current state now says — perhaps the unit was re-graded, perhaps a different partner accepted it — carrying the case's money axis `VOID → AUTHORIZED` and completing the cycle `PENDING → AUTHORIZED → VOID → AUTHORIZED`."

        The recomputation reads the same inspection findings, so the second row
        prices the same 114000-cent net refund, and the logistics axis is
        undisturbed at DISPOSITIONED throughout.

        Design: Difficulty/non_linear_state_machine/return_case_financial_axis_returns_to_authorized_after_void_via_supersede
        """
        scenario = self._superseded_authorization()

        assert scenario["first_refund"]["status"] == "VOIDED"
        assert scenario["second_refund"]["status"] == "AUTHORIZED"
        assert (
            scenario["second_refund"]["supersedes_refund_id"]
            == scenario["first_refund"]["id"]
        )
        assert scenario["second_refund"]["net_refund_cents"] == 114000

        case = read_return_case(scenario["return_case"]["id"])
        assert case["financial_status"] == "AUTHORIZED", (
            f"the money axis re-enters AUTHORIZED, got {case['financial_status']}"
        )
        assert case["logistics_status"] == "DISPOSITIONED"

    def test_authorizing_twice_without_a_release_never_moves_the_order_ledger(self):
        """PRD §3.9: "Voiding an `AUTHORIZED` row stamps `voided_at`, moves the case's money axis to `VOID`, and touches no ledger field at all, because no money ever moved."

        No release ever happened on either row, so the 120000-cent principal is
        still wholly outstanding after the void and the re-authorization.

        Design: Difficulty/non_linear_state_machine/return_case_financial_axis_returns_to_authorized_after_void_via_supersede
        """
        scenario = self._superseded_authorization()
        order = read_order(scenario["order"]["id"])

        assert order["refunded_total_cents"] == 0
        assert order["outstanding_refundable_cents"] == 120000
        assert order["retained_amount_cents"] == 0
        assert_refund_ledger_identity(order)
