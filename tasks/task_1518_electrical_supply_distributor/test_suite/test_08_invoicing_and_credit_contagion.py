"""Invoicing side effects: ledger settlement, the credit-contagion cascade,
and the payment cure that reverses it."""
from test_helpers import (
    create_awarded_quote,
    create_contractor,
    create_foot_item,
    create_job_account,
    create_release,
    get_contractor,
    get_job_account,
    get_release,
    invoice_release,
    receive_stock,
    record_payment,
    setup_credit_hold_scenario,
    walk_release,
)


class TestJobCreditHoldCycle:

    def test_invoice_breach_places_job_on_credit_hold(self):
        """PRD section 3.8: "The contractor's `committed_balance_cents`
        decreases by the release's `estimated_total_cents`, and
        `invoiced_balance_cents` increases by `billed_total_cents`."
        PRD section 3.8: "Should that posting push `invoiced_balance_cents`
        above the contractor's `credit_limit_cents`, credit contagion follows:
        every `OPEN` job account of that contractor transitions to
        `CREDIT_HOLD`, blocking further credit approvals and quote activity
        until payments bring the balance back within the limit (§3.1)."

        Design: Difficulty/non_linear_state_machine/job_credit_hold_cycle
        """
        world = setup_credit_hold_scenario()
        r1 = get_release(world["r1"]["id"])
        # Index ratio 200/100 = 2.0; eff unit 90.5 c/ft; 300 x 90.5 = 27150,
        # plus the 1500 cut charge (300 < 500-ft reel).
        assert r1["billed_total_cents"] == 28_650, (
            f"escalated billing must produce 28650, got "
            f"{r1['billed_total_cents']}")
        contractor = get_contractor(world["contractor"]["id"])
        assert contractor["invoiced_balance_cents"] == 28_650
        assert get_job_account(world["j1"]["id"])["status"] == "CREDIT_HOLD", (
            "billing over the 20000 limit places the job on CREDIT_HOLD")

    def test_payment_cure_returns_job_to_open(self):
        """PRD section 3.1: "If the posting brings `invoiced_balance_cents`
        back to at or below `credit_limit_cents`, every `CREDIT_HOLD` job
        account belonging to that contractor automatically returns to `OPEN` —
        the mirror image of the credit contagion described in §3.8."

        Design: Difficulty/non_linear_state_machine/job_credit_hold_cycle
        """
        world = setup_credit_hold_scenario()
        assert get_job_account(world["j1"]["id"])["status"] == "CREDIT_HOLD"

        record_payment(world["contractor"]["id"], 10_000)
        contractor = get_contractor(world["contractor"]["id"])
        assert contractor["invoiced_balance_cents"] == 18_650, (
            f"payment subtracts from the invoiced balance: 28650 - 10000 = "
            f"18650, got {contractor['invoiced_balance_cents']}")
        assert get_job_account(world["j1"]["id"])["status"] == "OPEN", (
            "the balance is back within the 20000 limit, so the held job "
            "returns to OPEN")


class TestInvoiceBreachContagion:

    def test_invoice_posts_billed_total_to_invoiced_balance(self):
        """PRD section 3.8: "The contractor's `committed_balance_cents`
        decreases by the release's `estimated_total_cents`, and
        `invoiced_balance_cents` increases by `billed_total_cents`."

        Design: Difficulty/transitive_cascade/invoice_breach_cascades_credit_hold
        """
        world = setup_credit_hold_scenario(second_job=True)
        r1 = get_release(world["r1"]["id"])
        assert r1["billed_total_cents"] == 28_650
        contractor = get_contractor(world["contractor"]["id"])
        assert contractor["invoiced_balance_cents"] == 28_650, (
            f"the invoice posts the billed total onto the invoiced balance, "
            f"got {contractor['invoiced_balance_cents']}")
        assert contractor["committed_balance_cents"] == 0, (
            "the committed estimate is released when the invoice posts")

    def test_breach_cascades_hold_to_all_open_jobs(self):
        """PRD section 3.8: "Should that posting push `invoiced_balance_cents`
        above the contractor's `credit_limit_cents`, credit contagion follows:
        every `OPEN` job account of that contractor transitions to
        `CREDIT_HOLD`, blocking further credit approvals and quote activity
        until payments bring the balance back within the limit (§3.1)."

        Design: Difficulty/transitive_cascade/invoice_breach_cascades_credit_hold
        """
        world = setup_credit_hold_scenario(second_job=True)
        assert get_job_account(world["j1"]["id"])["status"] == "CREDIT_HOLD"
        assert get_job_account(world["j2"]["id"])["status"] == "CREDIT_HOLD", (
            "contagion reaches the sibling OPEN account that had no part in "
            "the breaching invoice")


class TestInvoicePaymentConservation:

    def _setup_delivered_200(self):
        contractor = create_contractor("Quebec Electric", 1_000_000)
        thhn = create_foot_item()
        receive_stock(thhn["id"], 200)
        job = create_job_account(contractor["id"], "Credit Job",
                                 jobsite_address="23 Site Rd")
        quote = create_awarded_quote(job["id"], [(thhn["id"], 200, 45.25)])
        release = create_release(job["id"], quote["id"], [(thhn["id"], 200)])
        walk_release(release["id"], "DELIVERED", truck_id="T1",
                     delivery_date="2026-08-10", window=(8, 12))
        return contractor, release

    def test_invoice_settles_commitment_into_invoiced_balance(self):
        """PRD section 3.8: "The contractor's `committed_balance_cents`
        decreases by the release's `estimated_total_cents`, and
        `invoiced_balance_cents` increases by `billed_total_cents`."
        PRD section 2.6: "Balance mutations are immediate and atomic with the
        operations that cause them: credit approval commits a release's
        estimate, invoicing releases the commitment and posts the billed
        amount, cancellation releases the commitment, and a recorded payment
        reduces the invoiced balance."

        Design: Difficulty/compensating_invariant/invoice_then_payment_conserves_credit
        """
        contractor, release = self._setup_delivered_200()
        mid = get_contractor(contractor["id"])
        assert mid["committed_balance_cents"] == 10_550
        assert mid["invoiced_balance_cents"] == 0

        invoiced = invoice_release(release["id"])
        # FIRM: 200 x 45.25 = 9050 plus the 1500 cut charge (200 < 500 reel).
        assert invoiced["billed_total_cents"] == 10_550
        after = get_contractor(contractor["id"])
        assert after["committed_balance_cents"] == 0, (
            "invoicing releases the commitment")
        assert after["invoiced_balance_cents"] == 10_550, (
            f"invoiced balance posts the billed total, got "
            f"{after['invoiced_balance_cents']}")
        # Conservation: invoiced + payments == billed totals.
        assert after["invoiced_balance_cents"] + 0 == \
            invoiced["billed_total_cents"]

    def test_payment_zeroes_invoiced_balance(self):
        """PRD section 3.1: "The payment amount is subtracted from
        `invoiced_balance_cents`, and the contractor's `version` increments
        by 1."
        PRD section 2.6: "`credit_used_cents` is read-only and always equals
        the sum of the other two."

        Design: Difficulty/compensating_invariant/invoice_then_payment_conserves_credit
        """
        contractor, release = self._setup_delivered_200()
        invoice_release(release["id"])
        record_payment(contractor["id"], 10_550)

        after = get_contractor(contractor["id"])
        assert after["invoiced_balance_cents"] == 0, (
            f"paying the billed 10550 zeroes the invoiced balance, got "
            f"{after['invoiced_balance_cents']}")
        assert after["credit_used_cents"] == 0
        # Conservation across the whole cycle: invoiced + payments == billed.
        assert after["invoiced_balance_cents"] + 10_550 == 10_550
