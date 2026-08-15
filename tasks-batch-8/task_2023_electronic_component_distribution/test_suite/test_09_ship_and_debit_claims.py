"""Ship-and-debit claims: provisional vs audited amounts, the dispute cycle,
settlement, reversal, and debit-ledger conservation (PRD §3.7)."""
from test_helpers import (
    ADMIN,
    SALES,
    SUPPLIER,
    ApiErrorId,
    advance_clock,
    get_success_data,
    list_claims_for_line,
    setup_submitted_claim,
    ship_line,
    validate_error,
    validate_success,
)


def _get_claim(api, claim_id):
    return get_success_data(api.get_claim(claim_id, ADMIN))


def _get_line_balance(api, line_id):
    return get_success_data(api.get_manufacturer_line(line_id, ADMIN))[
        "open_debit_balance_cents"]


class TestProvisionalVsAudited:
    def test_claim_provisional_amount_pinned_at_ship(self, api):
        """PRD §3.7: "A claim's provisional amount is pinned at creation:
        `amount_provisional_cents` is the claim `qty` multiplied by the gap
        between its snapshotted `standard_cost_cents` and
        `registered_cost_cents` — exact integer-cents multiplication, no
        rounding."
        PRD §3.6: "The registration's `registered_qty_remaining` falls by the
        covered amount, and a registration whose remaining quantity reaches
        zero transitions to `EXHAUSTED`."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_audited_final
        """
        sc = setup_submitted_claim(order_quantity=20, ship_qty=20,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]
        assert claim["qty"] == 20
        assert claim["standard_cost_cents"] == 1000
        assert claim["registered_cost_cents"] == 700
        assert claim["amount_provisional_cents"] == 6000, "20 * (1000 - 700)"
        assert claim["status"] == "SUBMITTED"
        assert claim["registration_id"] == sc["registration"]["id"]

        registration = get_success_data(
            api.get_design_registration(sc["registration"]["id"], ADMIN))
        assert registration["registered_qty_remaining"] == 0
        assert registration["status"] == "EXHAUSTED"

    def test_claim_final_amount_diverges_with_audited_cost(self, api):
        """PRD §3.7: "Approving accepts an optional `audited_cost_cents`; when
        omitted it defaults to the claim's `registered_cost_cents`. The claim
        moves to `SUPPLIER_APPROVED` with `amount_final_cents` computed as `qty`
        times the gap between `standard_cost_cents` and `audited_cost_cents` —
        so when the audited cost differs from the registered cost, the final
        amount diverges from the provisional."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_audited_final
        """
        sc = setup_submitted_claim(order_quantity=20, ship_qty=20,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]
        decided = validate_success(
            api.supplier_decide_claim(
                claim["id"], {"decision": "APPROVE", "audited_cost_cents": 720},
                SUPPLIER),
            200)
        assert decided["status"] == "SUPPLIER_APPROVED"
        assert decided["audited_cost_cents"] == 720
        assert decided["amount_final_cents"] == 5600, "20 * (1000 - 720)"
        assert decided["amount_provisional_cents"] == 6000
        assert decided["amount_final_cents"] != decided["amount_provisional_cents"]


class TestDisputeResubmitCycle:
    def test_claim_dispute_resubmit_cycle(self, api):
        """PRD §3.7: "Disputing moves the claim sideways to `DISPUTED` with no
        amounts changed, and a `SalesRep` may later resubmit it — optionally
        with a `note` — back to `SUBMITTED`, ready for a fresh supplier
        decision; resubmit is only lawful from `DISPUTED`."

        Design: Difficulty/non_linear_state_machine/claim_dispute_resubmit_cycle
        """
        sc = setup_submitted_claim(order_quantity=10, ship_qty=10,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]

        disputed = validate_success(
            api.supplier_decide_claim(
                claim["id"],
                {"decision": "DISPUTE", "reason": "cost backup requested"},
                SUPPLIER),
            200)
        assert disputed["status"] == "DISPUTED"

        resubmitted = validate_success(
            api.resubmit_claim(claim["id"], {"note": "cost backup attached"}, SALES),
            200)
        assert resubmitted["status"] == "SUBMITTED", "Cyclic path DISPUTED -> SUBMITTED"

    def test_claim_approve_after_resubmit_defaults_audited(self, api):
        """PRD §3.7: "Approving accepts an optional `audited_cost_cents`; when
        omitted it defaults to the claim's `registered_cost_cents`. The claim
        moves to `SUPPLIER_APPROVED` with `amount_final_cents` computed as `qty`
        times the gap between `standard_cost_cents` and `audited_cost_cents`".

        Design: Difficulty/non_linear_state_machine/claim_dispute_resubmit_cycle
        """
        sc = setup_submitted_claim(order_quantity=10, ship_qty=10,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]
        validate_success(
            api.supplier_decide_claim(claim["id"], {"decision": "DISPUTE"}, SUPPLIER))
        validate_success(api.resubmit_claim(claim["id"], {}, SALES))

        approved = validate_success(
            api.supplier_decide_claim(claim["id"], {"decision": "APPROVE"}, SUPPLIER),
            200)
        assert approved["status"] == "SUPPLIER_APPROVED"
        assert approved["amount_final_cents"] == 3000, (
            "audited defaults to registered 700: 10 * (1000 - 700)"
        )
        assert approved["amount_provisional_cents"] == 3000


class TestSettleStateGate:
    def test_claim_settle_from_submitted_rejected(self, api):
        """PRD §3.7: "A `SupplierAdmin` settles a claim from
        `SUPPLIER_APPROVED` — the only lawful source state — moving it to
        `SETTLED` and adding its `amount_final_cents` to the manufacturer
        line's `open_debit_balance_cents`."

        Design: Corner/state_machines/claim_settle_from_submitted_rejected
        """
        sc = setup_submitted_claim(order_quantity=5, ship_qty=5,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]
        assert claim["status"] == "SUBMITTED"

        resp = api.settle_claim(claim["id"], SUPPLIER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)
        assert _get_line_balance(api, sc["line"]["id"]) == 0, "No debit posted"


class TestDebitConservation:
    def _setup_two_claims(self, api):
        """Two claims of qty 20 each on one registration (max 40), created by
        two ships on the same order line. Returns (scenario, claim1, claim2)
        in creation order (PRD §2.3 ascending created_at)."""
        sc = setup_submitted_claim(order_quantity=40, ship_qty=20,
                                   registered_cost_cents=700,
                                   max_registered_qty=40)
        advance_clock("2026-08-01T01:00:00Z")
        ship_line(sc["order"]["id"], sc["order_line"]["id"], 20)
        all_claims, _meta = list_claims_for_line(sc["order_line"]["id"])
        assert len(all_claims) == 2
        return sc, all_claims[0], all_claims[1]

    def test_debit_balance_settle_accumulates(self, api):
        """PRD §3.7: "the balance at any moment equals the sum of final amounts
        over `SETTLED` claims on the line's parts minus the sum over `REVERSED`
        claims."

        Design: Difficulty/compensating_invariant/debit_dollar_conservation_settle_reverse
        """
        sc, claim1, claim2 = self._setup_two_claims(api)

        approved1 = validate_success(
            api.supplier_decide_claim(
                claim1["id"], {"decision": "APPROVE", "audited_cost_cents": 720},
                SUPPLIER), 200)
        assert approved1["amount_final_cents"] == 5600  # 20 * (1000 - 720)
        validate_success(api.settle_claim(claim1["id"], SUPPLIER))
        assert _get_line_balance(api, sc["line"]["id"]) == 5600

        approved2 = validate_success(
            api.supplier_decide_claim(claim2["id"], {"decision": "APPROVE"}, SUPPLIER),
            200)
        assert approved2["amount_final_cents"] == 6000  # 20 * (1000 - 700)
        validate_success(api.settle_claim(claim2["id"], SUPPLIER))
        assert _get_line_balance(api, sc["line"]["id"]) == 11600

    def test_debit_reverse_compensates_balance(self, api):
        """PRD §3.7: "A settle followed by its compensating reverse therefore
        leaves the line's debit balance unchanged — the ledger's net-drift is
        zero by construction, since the balance at any moment equals the sum of
        final amounts over `SETTLED` claims on the line's parts minus the sum
        over `REVERSED` claims."

        Design: Difficulty/compensating_invariant/debit_dollar_conservation_settle_reverse
        """
        sc, claim1, claim2 = self._setup_two_claims(api)
        for claim, payload in ((claim1, {"decision": "APPROVE", "audited_cost_cents": 720}),
                               (claim2, {"decision": "APPROVE"})):
            validate_success(api.supplier_decide_claim(claim["id"], payload, SUPPLIER))
            validate_success(api.settle_claim(claim["id"], SUPPLIER))
        assert _get_line_balance(api, sc["line"]["id"]) == 11600

        reversed_claim = validate_success(
            api.reverse_claim(claim1["id"], {"reason": "audit clawback"}, SUPPLIER),
            200)
        assert reversed_claim["status"] == "REVERSED"
        # Settle added claim1's 5600 and claim2's 6000; the reverse subtracts
        # claim1's same 5600, so claim2's 6000 remains: 11600 - 5600 == 6000.
        assert _get_line_balance(api, sc["line"]["id"]) == 6000, (
            "The reverse decrements the balance by claim1's amount_final_cents; "
            "the settle+reverse pair nets to zero and claim2's 6000 remains"
        )
        assert _get_claim(api, claim2["id"])["status"] == "SETTLED"


class TestReverseRestoreCascade:
    def _setup_settled_claim_on_exhausted_registration(self, api):
        """Claim qty 20 fully consuming its registration (EXHAUSTED), approved
        with audited 720 and settled: line balance 5600."""
        sc = setup_submitted_claim(order_quantity=20, ship_qty=20,
                                   registered_cost_cents=700,
                                   max_registered_qty=20)
        claim = sc["claim"]
        validate_success(
            api.supplier_decide_claim(
                claim["id"], {"decision": "APPROVE", "audited_cost_cents": 720},
                SUPPLIER))
        validate_success(api.settle_claim(claim["id"], SUPPLIER))
        return sc, claim

    def test_claim_reverse_compensates_debit_balance(self, api):
        """PRD §3.7: "A settled claim can later be reversed, optionally with a
        `reason`, moving it to the terminal `REVERSED`: the line's
        `open_debit_balance_cents` is decremented by the same
        `amount_final_cents`".

        Design: Difficulty/transitive_cascade/claim_reverse_restore_cascade_depth2
        """
        sc, claim = self._setup_settled_claim_on_exhausted_registration(api)
        assert _get_line_balance(api, sc["line"]["id"]) == 5600

        reversed_claim = validate_success(
            api.reverse_claim(claim["id"], {"reason": "supplier chargeback"}, SUPPLIER),
            200)
        assert reversed_claim["status"] == "REVERSED"
        assert _get_line_balance(api, sc["line"]["id"]) == 0, "Debit compensated"

    def test_claim_reverse_restores_registration_and_reinstates_approved(self, api):
        """PRD §3.7: "the claim's `qty` is restored to the registration's
        `registered_qty_remaining`, and an `EXHAUSTED` registration whose
        remaining quantity is thereby lifted above zero returns to `APPROVED`."

        Design: Difficulty/transitive_cascade/claim_reverse_restore_cascade_depth2
        """
        sc, claim = self._setup_settled_claim_on_exhausted_registration(api)
        registration_pre = get_success_data(
            api.get_design_registration(sc["registration"]["id"], ADMIN))
        assert registration_pre["status"] == "EXHAUSTED"
        assert registration_pre["registered_qty_remaining"] == 0

        validate_success(
            api.reverse_claim(claim["id"], {"reason": "supplier chargeback"}, SUPPLIER))

        registration_post = get_success_data(
            api.get_design_registration(sc["registration"]["id"], ADMIN))
        assert registration_post["registered_qty_remaining"] == 20, (
            "Link 1: the reverse restores the claim's qty"
        )
        assert registration_post["status"] == "APPROVED", (
            "Link 2: the restore flips EXHAUSTED back to APPROVED"
        )
