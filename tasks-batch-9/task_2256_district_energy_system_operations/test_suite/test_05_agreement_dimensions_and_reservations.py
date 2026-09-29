"""Contract and billing dimensions, and the loop reservation ledger they drive."""

from test_helpers import (
    BILLING_ANALYST,
    activate_agreement,
    api_client,
    assert_agreement_state,
    assert_invoice_determinants,
    assert_loop_state,
    create_invoice,
    get_success_data,
    hospital_billing_stack,
    issue_invoice,
    midtown_reservation_stack,
    pay_invoice,
    read_agreement,
    read_loop,
    set_agreement_state,
)

JUNE_START = "2026-06-01T00:00:00Z"
JUNE_END = "2026-07-01T00:00:00Z"


def _read_point(point_id):
    return get_success_data(api_client.get_metering_point(point_id, BILLING_ANALYST))


class TestIndependentStateDimensions:
    """A suspended contract can still be current, and an active one in arrears."""

    def test_suspending_the_contract_leaves_the_billing_dimension_current(self):
        """The contract dimension moves alone; billing is untouched by a suspension.

        PRD: "The two dimensions advance independently: an agreement can be
        `SUSPENDED` and `CURRENT`, or `ACTIVE` and `IN_ARREARS`."

        Design: Difficulty/non_linear_state_machine/agreement_contract_and_billing_dimensions_advance_independently
        """
        stack = hospital_billing_stack()

        suspended = set_agreement_state(
            stack["agreement"]["id"],
            "SUSPENDED",
            reason="customer requested seasonal shutdown",
        )

        assert_agreement_state(suspended, contract_state="SUSPENDED", billing_state="CURRENT")

    def test_a_suspended_customer_can_still_be_billed_into_arrears(self):
        """Issuing against a suspended contract drives only the billing dimension.

        PRD: "Creation, issuing and adjustment all additionally require the owning
        agreement's `contract_state` to be `ACTIVE` or `SUSPENDED`; billing a
        `PENDING_CAPACITY` or `TERMINATED` agreement is rejected with
        `ERR_INVOICE_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/agreement_contract_and_billing_dimensions_advance_independently
        """
        stack = hospital_billing_stack()
        suspended = set_agreement_state(
            stack["agreement"]["id"],
            "SUSPENDED",
            reason="customer requested seasonal shutdown",
        )
        invoice = create_invoice(
            stack["agreement"]["id"],
            JUNE_START,
            JUNE_END,
            "ESTIMATED",
            expected_agreement_version=suspended["version"],
        )

        issued = issue_invoice(invoice["id"])

        assert_invoice_determinants(issued, total_amount=116819.63, invoice_state="ISSUED")
        assert_agreement_state(
            read_agreement(stack["agreement"]["id"]),
            contract_state="SUSPENDED",
            billing_state="IN_ARREARS",
            balance_due=116819.63,
        )

    def test_settling_in_full_returns_the_billing_dimension_to_current(self):
        """Payment clears the balance without touching the contract dimension.

        PRD: "the billing dimension is cascaded from `IN_ARREARS` back to
        `CURRENT` when the recomputed balance is at or below the arrears
        threshold".

        Design: Difficulty/non_linear_state_machine/agreement_contract_and_billing_dimensions_advance_independently
        """
        stack = hospital_billing_stack()
        agreement_id = stack["agreement"]["id"]
        suspended = set_agreement_state(
            agreement_id, "SUSPENDED", reason="customer requested seasonal shutdown"
        )
        invoice = create_invoice(
            agreement_id,
            JUNE_START,
            JUNE_END,
            "ESTIMATED",
            expected_agreement_version=suspended["version"],
        )
        issue_invoice(invoice["id"])

        paid = pay_invoice(invoice["id"], 116819.63, agreement_id)

        assert_invoice_determinants(paid, invoice_state="PAID", paid_amount=116819.63)
        assert_agreement_state(
            read_agreement(agreement_id),
            contract_state="SUSPENDED",
            billing_state="CURRENT",
            balance_due=0.00,
        )

    def test_reinstating_the_contract_leaves_the_reservation_and_the_ledger_alone(self):
        """The contract returns to active while the balance stays settled.

        PRD: "`SUSPENDED → ACTIVE` sets `contract_state` back to `ACTIVE` and
        likewise leaves `committed_reserved_kw` unchanged, since the reservation
        was never released."

        Design: Difficulty/non_linear_state_machine/agreement_contract_and_billing_dimensions_advance_independently
        """
        stack = hospital_billing_stack()
        agreement_id = stack["agreement"]["id"]
        suspended = set_agreement_state(
            agreement_id, "SUSPENDED", reason="customer requested seasonal shutdown"
        )
        invoice = create_invoice(
            agreement_id,
            JUNE_START,
            JUNE_END,
            "ESTIMATED",
            expected_agreement_version=suspended["version"],
        )
        issue_invoice(invoice["id"])
        pay_invoice(invoice["id"], 116819.63, agreement_id)

        reinstated = set_agreement_state(agreement_id, "ACTIVE", reason="season resumed")

        assert_agreement_state(
            reinstated,
            contract_state="ACTIVE",
            billing_state="CURRENT",
            balance_due=0.00,
        )
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=4000.0)


class TestReservationLedgerConservation:
    """Activation adds, suspension holds and termination releases the reservation."""

    def test_activating_both_customers_accumulates_the_reserved_total(self):
        """Two activations lift the loop's reserved total from nothing to 5000 kW.

        PRD: "When the sweep clears, the agreement becomes `ACTIVE`, the loop's
        `committed_reserved_kw` is increased by the agreement's
        `reserved_capacity_kw`, and both the loop's and the agreement's `version`
        are incremented by 1."

        Design: Difficulty/compensating_invariant/loop_reserved_capacity_kw_conserved_across_activate_suspend_terminate
        """
        stack = midtown_reservation_stack()
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=0.0)

        smaller = activate_agreement(stack["smaller"]["id"])
        activate_agreement(stack["larger"]["id"])

        assert smaller["reserved_capacity_kw"] == 2000.0
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=5000.0)

    def test_a_suspended_agreement_still_holds_its_reservation_on_the_loop(self):
        """Suspension is deliberately not a release of capacity.

        PRD: "`ACTIVE → SUSPENDED` sets `contract_state` to `SUSPENDED` and leaves
        `committed_reserved_kw` **unchanged**, because a suspended agreement still
        holds its reservation on the loop."

        Design: Difficulty/compensating_invariant/loop_reserved_capacity_kw_conserved_across_activate_suspend_terminate
        """
        stack = midtown_reservation_stack()
        activate_agreement(stack["smaller"]["id"])
        activate_agreement(stack["larger"]["id"])

        set_agreement_state(stack["larger"]["id"], "SUSPENDED", reason="billing hold")

        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=5000.0)

    def test_terminating_releases_exactly_what_activation_reserved(self):
        """The reserved total returns to the surviving customer's 2000 kW alone.

        PRD: "`SUSPENDED → TERMINATED` behaves identically to the previous edge:
        reservation released, loop `version` incremented, metering points removed,
        arrears written off."

        Design: Difficulty/compensating_invariant/loop_reserved_capacity_kw_conserved_across_activate_suspend_terminate
        """
        stack = midtown_reservation_stack()
        activate_agreement(stack["smaller"]["id"])
        activate_agreement(stack["larger"]["id"])
        set_agreement_state(stack["larger"]["id"], "SUSPENDED", reason="billing hold")
        peak = read_loop(stack["loop"]["id"])["committed_reserved_kw"]

        terminated = set_agreement_state(
            stack["larger"]["id"], "TERMINATED", reason="customer exit"
        )

        final = read_loop(stack["loop"]["id"])["committed_reserved_kw"]
        assert_agreement_state(terminated, contract_state="TERMINATED")
        assert final == peak - 3000.0
        assert final == 2000.0

    def test_termination_also_pulls_the_customers_meter_out_of_service(self):
        """The reservation release carries the metering point to REMOVED with it.

        PRD: "cascades every metering point of this agreement whose `meter_state`
        is `INSTALLED` or `COMMISSIONED` to `REMOVED`".

        Design: Difficulty/compensating_invariant/loop_reserved_capacity_kw_conserved_across_activate_suspend_terminate
        """
        stack = midtown_reservation_stack()
        activate_agreement(stack["smaller"]["id"])
        activate_agreement(stack["larger"]["id"])

        set_agreement_state(stack["larger"]["id"], "TERMINATED", reason="customer exit")

        assert _read_point(stack["point"]["id"])["meter_state"] == "REMOVED"
        assert read_agreement(stack["smaller"]["id"])["contract_state"] == "ACTIVE"
