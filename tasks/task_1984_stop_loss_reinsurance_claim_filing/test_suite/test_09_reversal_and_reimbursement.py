"""Claim reversal blocked by active filings, and reimbursement posting."""
from test_helpers import (
    ACCOUNTANT,
    ApiErrorId,
    create_filing,
    create_reimbursement_payload,
    get_claim,
    get_filing,
    get_member,
    get_reimbursement,
    get_specific_row,
    setup_approved_filing,
    setup_draft_filing,
    setup_paid_claim_scenario,
    submit_filing,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.fixtures import EXAMINER


class TestClaimReverseBlockedByActiveFiling:
    def test_reverse_blocked_while_filing_submitted(self, api):
        """PRD §3.4: "A claim cannot be reversed while it appears as a line
        item under any filing whose status is `SUBMITTED`, `UNDER_REVIEW`,
        `APPROVED`, or `PAID`; filings still in `DRAFT` or sitting in
        `DISPUTED` do not block the reversal."

        Design: Difficulty/cross_entity_state_dependency/claim_reverse_blocked_by_active_filing
        """
        ctx = setup_draft_filing(plan_name="Nu", claim_cents=15_000_000)
        submit_filing(ctx["filing"]["id"])
        assert get_filing(ctx["filing"]["id"])["status"] == "SUBMITTED"

        resp = _api_client.reverse_claim(ctx["claim"]["id"], EXAMINER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_claim(ctx["claim"]["id"])["status"] == "PAID", (
            "Claim pinned by a SUBMITTED filing must remain PAID")

    def test_reverse_allowed_while_filing_still_draft(self, api):
        """PRD §3.4: "A claim cannot be reversed while it appears as a line
        item under any filing whose status is `SUBMITTED`, `UNDER_REVIEW`,
        `APPROVED`, or `PAID`; filings still in `DRAFT` or sitting in
        `DISPUTED` do not block the reversal."
        PRD §3.4: "When a reversal pulls the member's accumulation back below
        the notice threshold and `notice_triggered` flips from true to false,
        a member still in `NOTICE_PENDING` is reset to `NONE` — but a member
        whose notice already reached `NOTICE_FILED` stays filed."

        Design: Difficulty/cross_entity_state_dependency/claim_reverse_blocked_by_active_filing
        """
        ctx = setup_paid_claim_scenario(plan_name="Nu", claim_cents=15_000_000,
                                        file_the_notice=False)
        assert get_member(ctx["member"]["id"])["notice_status"] == "NOTICE_PENDING"
        create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                      filing_scope="SPECIFIC", member_id=ctx["member"]["id"])

        resp = _api_client.reverse_claim(ctx["claim"]["id"], EXAMINER)
        claim = validate_success(resp, 200)
        assert claim["status"] == "REVERSED"
        row = get_specific_row(ctx["contract"]["id"], ctx["member"]["id"])
        assert row["accumulated_cents"] == 0
        assert row["notice_triggered"] is False
        assert get_member(ctx["member"]["id"])["notice_status"] == "NONE"


class TestReimbursementPosting:
    def test_posting_reimbursement_moves_filing_to_paid(self, api):
        """PRD §3.7: "Posting fires two side effects as one mutation: the
        filing transitions from `APPROVED` to `PAID`, and the plan's
        `AGGREGATE` accumulation row is recalculated to net the reimbursed
        excess out of the plan's unrecovered exposure."
        PRD §3.6: "`PAID` is never reached by a direct call: it is the system
        transition that fires when a reimbursement against the filing is
        posted, as §3.7 describes."

        Design: Difficulty/transitive_cascade/reimbursement_post_to_filing_paid_to_aggregate_recompute
        """
        ctx = setup_approved_filing(plan_name="Theta", claim_cents=15_000_000,
                                    approved_amount_cents=5_000_000)
        resp = _api_client.create_reimbursement(
            create_reimbursement_payload(ctx["filing"]["id"], 5_000_000),
            ACCOUNTANT)
        reimbursement = validate_success(resp, 201)
        assert reimbursement["status"] == "RECEIVED"

        resp = _api_client.post_reimbursement(reimbursement["id"], ACCOUNTANT)
        posted = validate_success(resp, 200)
        assert posted["status"] == "POSTED"
        assert get_filing(ctx["filing"]["id"])["status"] == "PAID", (
            "Posting the exact-match reimbursement must move the filing to PAID")

    def test_posting_against_already_paid_filing_rejected(self, api):
        """PRD §3.7: "Moving a reimbursement from `RECEIVED` to `POSTED`
        requires an exact match between `received_amount_cents` and the
        filing's `approved_amount_cents` — a short payment or an overpayment
        cannot post at all and is rejected with
        `ERR_REIMBURSEMENT_MISMATCH` — and it requires the filing to still be
        in `APPROVED`."

        Design: Difficulty/transitive_cascade/reimbursement_post_to_filing_paid_to_aggregate_recompute
        """
        ctx = setup_approved_filing(plan_name="Theta", claim_cents=15_000_000,
                                    approved_amount_cents=5_000_000)
        # Both wires are recorded while the filing sits in APPROVED.
        first = validate_success(_api_client.create_reimbursement(
            create_reimbursement_payload(ctx["filing"]["id"], 5_000_000),
            ACCOUNTANT), 201)
        second = validate_success(_api_client.create_reimbursement(
            create_reimbursement_payload(ctx["filing"]["id"], 5_000_000),
            ACCOUNTANT), 201)

        validate_success(_api_client.post_reimbursement(first["id"], ACCOUNTANT), 200)
        assert get_filing(ctx["filing"]["id"])["status"] == "PAID"

        # The second wire cannot post: the filing no longer sits in APPROVED.
        resp = _api_client.post_reimbursement(second["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_reimbursement(second["id"])["status"] == "RECEIVED"

    def test_posting_mismatched_amount_rejected(self, api):
        """PRD §3.7: "Moving a reimbursement from `RECEIVED` to `POSTED`
        requires an exact match between `received_amount_cents` and the
        filing's `approved_amount_cents` — a short payment or an overpayment
        cannot post at all and is rejected with
        `ERR_REIMBURSEMENT_MISMATCH` — and it requires the filing to still be
        in `APPROVED`."

        Design: Corner/validations/reimbursement_amount_mismatch_at_post
        """
        ctx = setup_approved_filing(plan_name="P", claim_cents=15_000_000,
                                    approved_amount_cents=5_000_000)
        # Carrier wired 49000_00 against an approval of 50000_00.
        resp = _api_client.create_reimbursement(
            create_reimbursement_payload(ctx["filing"]["id"], 4_900_000),
            ACCOUNTANT)
        reimbursement = validate_success(resp, 201)
        resp = _api_client.post_reimbursement(reimbursement["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_MISMATCH)
        assert get_reimbursement(reimbursement["id"])["status"] == "RECEIVED"
        assert get_filing(ctx["filing"]["id"])["status"] == "APPROVED"
