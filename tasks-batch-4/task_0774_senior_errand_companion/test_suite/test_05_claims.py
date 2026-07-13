"""LTC reimbursement claims: the SUBMITTED↔NEEDS_INFO revision cycle, the
state-before-fiscal precedence on submit, the invoice-finalized precondition, the
finalize-only-from-draft rule, and the policy/invoice client-match check."""
from test_helpers import (
    setup_submitted_claim,
    setup_finalized_invoice,
    setup_completed_visit,
    create_cleared_bonded_caregiver,
    create_client,
    create_visit,
    assign_caregiver,
    clock_in_visit,
    clock_out_visit,
    get_invoice_for_visit,
    attach_ltc_policy,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestClaimRevisionCycle:
    def test_request_info_moves_submitted_to_needs_info(self, api):
        """PRD §3.7: "On a submitted claim the payer may request more information,
        supplying an optional note, which moves it SUBMITTED → NEEDS_INFO"

        Design: Difficulty/non_linear_state_machine/claim_cycle_submitted_needsinfo_submitted
        """
        ctx = setup_submitted_claim(api)
        claim = validate_success(api.request_info_claim(ctx["claim"]["id"], {"note": "need EOB"}, BILLING))
        assert claim["status"] == "NEEDS_INFO", f"expected NEEDS_INFO, got {claim['status']}"

    def test_resubmit_from_needs_info_returns_to_submitted(self, api):
        """PRD §3.7: "the clerk may then resubmit, and this SUBMITTED → NEEDS_INFO →
        SUBMITTED revision cycle may repeat any number of times."

        Design: Difficulty/non_linear_state_machine/claim_cycle_submitted_needsinfo_submitted
        """
        ctx = setup_submitted_claim(api)
        validate_success(api.request_info_claim(ctx["claim"]["id"], {"note": "need EOB"}, BILLING))
        claim = validate_success(api.submit_claim(ctx["claim"]["id"], BILLING))
        assert claim["status"] == "SUBMITTED", f"expected SUBMITTED after resubmit, got {claim['status']}"


class TestSubmitStateBeatsFiscal:
    def _ctx(self, api):
        """A REIMBURSEMENT policy exhausted by an earlier approved claim
        (lifetime_max 9000, rate 1.0), plus a second DRAFT invoice on the same
        client with a DRAFT claim on it against the exhausted policy."""
        cg1 = create_cleared_bonded_caregiver(api, name="CG-1")
        client = create_client(api)
        # First visit -> finalized invoice (total 9000).
        v1 = create_visit(api, client["id"], scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T12:00:00Z")
        assign_caregiver(api, v1["id"], cg1["id"], v1["version"])
        clock_in_visit(api, v1["id"], cg1["id"], "2026-03-05T09:00:00Z")
        clock_out_visit(api, v1["id"], cg1["id"], "2026-03-05T12:00:00Z", 0)
        inv1 = get_invoice_for_visit(api, v1["id"])
        validate_success(api.finalize_invoice(inv1["id"], BILLING))
        policy = attach_ltc_policy(
            api, client["id"], payer_name="CapCo", benefit_type="REIMBURSEMENT",
            lifetime_max_cents=9000, reimbursement_rate=1.0, daily_cap_cents=100_000,
        )
        claim1 = validate_success(api.create_claim(inv1["id"], {"ltc_policy_id": policy["id"]}, BILLING), 201)
        validate_success(api.submit_claim(claim1["id"], BILLING))
        validate_success(api.claim_decision(claim1["id"], {"outcome": "APPROVE"}, BILLING))
        # Second visit -> DRAFT invoice, never finalized (different caregiver to
        # avoid any dependence on the unspecified travel-buffer length).
        cg2 = create_cleared_bonded_caregiver(api, name="CG-2")
        v2 = create_visit(api, client["id"], scheduled_start="2026-03-05T13:00:00Z", scheduled_end="2026-03-05T16:00:00Z")
        assign_caregiver(api, v2["id"], cg2["id"], v2["version"])
        clock_in_visit(api, v2["id"], cg2["id"], "2026-03-05T13:00:00Z")
        clock_out_visit(api, v2["id"], cg2["id"], "2026-03-05T16:00:00Z", 0)
        inv2 = get_invoice_for_visit(api, v2["id"])
        claim2 = validate_success(api.create_claim(inv2["id"], {"ltc_policy_id": policy["id"]}, BILLING), 201)
        return {"client": client, "policy": policy, "claim2": claim2}

    def test_policy_is_exhausted_after_full_approval(self, api):
        """PRD §3.7: "it adds the claim's reimbursed_cents to the policy's
        reimbursed_to_date_cents — and if that running total reaches the policy's
        lifetime_max_cents, the policy transitions ACTIVE → EXHAUSTED"

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_fiscal
        """
        ctx = self._ctx(api)
        policies = get_success_data(api.list_ltc_policies(ctx["client"]["id"], COORD))
        pol = next(p for p in policies if p["id"] == ctx["policy"]["id"])
        assert pol["status"] == "EXHAUSTED", f"expected EXHAUSTED policy, got {pol['status']}"

    def test_submit_reports_state_error_over_fiscal_error(self, api):
        """PRD §2.10: "State-machine eligibility of the target resource is eighth (the
        generic ERR_INVALID_STATE, refined into the specific state errors named in §3)."
        PRD §2.10: "Fiscal eligibility of a policy on claim submission is last
        (ERR_POLICY_EXHAUSTED)."

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_fiscal
        """
        ctx = self._ctx(api)
        resp = api.submit_claim(ctx["claim2"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FINALIZED)


class TestSubmitBlockedWhenInvoiceDraft:
    def _ctx(self, api):
        ctx = setup_completed_visit(api)  # DRAFT invoice, never finalized
        policy = attach_ltc_policy(api, ctx["client"]["id"], benefit_type="INDEMNITY", daily_benefit_cents=5000)
        claim = validate_success(api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": policy["id"]}, BILLING), 201)
        ctx["claim"] = claim
        return ctx

    def test_submit_on_draft_invoice_rejected(self, api):
        """PRD §3.7: "submission requires the referenced invoice to be FINALIZED
        (else ERR_INVOICE_NOT_FINALIZED) and the referenced policy to be ACTIVE"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_when_invoice_not_finalized
        """
        ctx = self._ctx(api)
        resp = api.submit_claim(ctx["claim"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FINALIZED)

    def test_claim_remains_draft_after_rejected_submit(self, api):
        """PRD §3.7: "the claim references its invoice through invoice_id."
        PRD §3.7: "At creation the claim snapshots the policy's benefit_type and
        computes its monetary fields, then begins in DRAFT."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_when_invoice_not_finalized
        """
        ctx = self._ctx(api)
        api.submit_claim(ctx["claim"]["id"], BILLING)
        claim = validate_success(api.get_claim(ctx["claim"]["id"], BILLING))
        assert claim["status"] == "DRAFT", f"rejected submit must leave claim DRAFT, got {claim['status']}"


def test_finalize_already_finalized_invoice_rejected(api):
    """PRD §3.6: "Finalizing an invoice that is not DRAFT is rejected with
    ERR_INVOICE_NOT_DRAFT."

    Design: Corner/state_machines/error_finalize_non_draft_invoice
    """
    ctx = setup_finalized_invoice(api)
    resp = api.finalize_invoice(ctx["invoice"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DRAFT)


def test_claim_create_with_mismatched_policy_client_rejected(api):
    """PRD §3.7: "The policy must belong to the same client as the invoice, or the
    request is rejected with ERR_POLICY_CLIENT_MISMATCH."

    Design: Corner/validations/error_policy_client_mismatch_on_claim_create
    """
    ctx = setup_finalized_invoice(api)  # invoice for client-1
    other_client = create_client(api, name="Other Client", home_zip="90002")
    other_policy = attach_ltc_policy(api, other_client["id"], benefit_type="INDEMNITY", daily_benefit_cents=5000)
    resp = api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": other_policy["id"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_POLICY_CLIENT_MISMATCH)
