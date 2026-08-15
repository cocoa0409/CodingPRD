"""Formula revision pipeline: the CLAIM_REVIEW -> DRAFT cycle, supersede
lockdown, claim-review adjudication, and label substantiation gates
(PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestRevisionClaimReviewCycle:
    def test_reject_back_returns_revision_to_draft(self, api):
        """PRD §3.4: "The alternative outcome, reject-back, moves the revision
        from `CLAIM_REVIEW` back to `DRAFT` for reformulation; a revision may
        loop through draft, submission, verification, and review as many times
        as needed."

        Design: Difficulty/non_linear_state_machine/formula_revision_claim_review_reject_cycle
        """
        ns = fixtures.setup_formula_with_revision(lines=None, target_protein=19)
        rid = ns.r1["id"]
        s1 = validate_success(client.submit_revision(rid, SCI), 200)
        assert s1["status"] == "SUBMITTED"
        s2 = validate_success(client.verify_nutrition(rid, QM), 200)
        assert s2["status"] == "NUTRITION_VERIFIED"
        s3 = validate_success(client.send_claim_review(rid, SCI), 200)
        assert s3["status"] == "CLAIM_REVIEW"
        s4 = validate_success(client.reject_back_revision(rid, QM), 200)
        assert s4["status"] == "DRAFT"

    def test_second_loop_reaches_approved_and_versions_increment(self, api):
        """PRD §3.4: "The alternative outcome, reject-back, moves the revision
        from `CLAIM_REVIEW` back to `DRAFT` for reformulation; a revision may
        loop through draft, submission, verification, and review as many times
        as needed."
        PRD §2.4: "As a rule, every state transition, field update, and
        system-driven reconciliation described in this document is a mutation:
        it increments the owning resource's `version` by one and refreshes its
        `updated_at`"

        Design: Difficulty/non_linear_state_machine/formula_revision_claim_review_reject_cycle
        """
        ns = fixtures.setup_formula_with_revision(lines=None, target_protein=19)
        rid = ns.r1["id"]
        v0 = ns.r1["version"]
        # First loop: DRAFT -> SUBMITTED -> NUTRITION_VERIFIED -> CLAIM_REVIEW
        # -> DRAFT (reject-back).
        validate_success(client.submit_revision(rid, SCI), 200)
        validate_success(client.verify_nutrition(rid, QM), 200)
        validate_success(client.send_claim_review(rid, SCI), 200)
        validate_success(client.reject_back_revision(rid, QM), 200)
        # Second loop, this time to approval.
        validate_success(client.submit_revision(rid, SCI), 200)
        validate_success(client.verify_nutrition(rid, QM), 200)
        validate_success(client.send_claim_review(rid, SCI), 200)
        approved = validate_success(client.approve_revision(rid, QM), 200)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == v0 + 8, (
            f"8 transitions from creation must each increment version by one: "
            f"expected {v0 + 8}, got {approved['version']}"
        )


class TestSupersededRevisionLocked:
    def test_submit_on_superseded_revision_rejected(self, api):
        """PRD §3.4: "Approval fires the two-link **CASCADE-SUPERSEDE**: the
        previously `APPROVED` revision of the same formula, if one exists,
        moves to `SUPERSEDED` (a terminal, self-referential transition within
        the formula's own revision set)"
        PRD §2.6: "8. **Terminal-state lock** — the addressed resource must not
        sit in a terminal state: a `TERMINATED` agreement, a `SUPERSEDED`
        revision, a `REJECTED` or `DEPLETED` lot, a `CANCELLED` run or
        changeover, a lot release whose decision is `RELEASED` or `SCRAPPED`,
        or a `COMPLETED`, `FAILED`, or `TERMINATED` study all reject further
        action with `ERR_TERMINAL_STATE_LOCKED` (409)."

        Design: Corner/state_machines/c_superseded_revision_locked
        """
        ns = fixtures.setup_formula_with_revision(march_to="APPROVED")
        r2 = fixtures.create_revision(
            ns.f1["id"], [fixtures.line(ns.whey["id"], 42, True)],
            target_protein=16, claim_tags=[],
        )
        fixtures.march_revision_to_approved(r2["id"])
        superseded = validate_success(client.get_revision(ns.r1["id"], QM), 200)
        assert superseded["status"] == "SUPERSEDED"
        resp = client.submit_revision(ns.r1["id"], SCI)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_STATE_LOCKED, 409)


class TestRevisionApprovalGates:
    def test_approve_without_approved_claim_review_rejected(self, api):
        """PRD §3.4: "Approval moves the revision from `CLAIM_REVIEW` to
        `APPROVED` and is permitted only when every claim tag in `claim_tags`
        has exactly one claim review in `APPROVED` status; a missing or
        unapproved review for any claimed tag rejects the approval with
        `ERR_CLAIM_REVIEW_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/c_claim_review_incomplete_blocks_approve
        """
        ns = fixtures.setup_formula_with_revision(
            claim_tags=["HIGH_PROTEIN"], march_to="CLAIM_REVIEW",
        )
        resp = client.approve_revision(ns.r1["id"], QM)
        validate_error(resp, ApiErrorId.ERR_CLAIM_REVIEW_INCOMPLETE, 422)
        stayed = validate_success(client.get_revision(ns.r1["id"], QM), 200)
        assert stayed["status"] == "CLAIM_REVIEW"

    def test_label_claim_unsubstantiated_at_verify_nutrition(self, api):
        """PRD §3.4: "Verification then gates on the revision's claims: the
        LABEL result must satisfy every `NUTRIENT_CONTENT` claim in
        `claim_tags` — at least 10.0 grams per serving for `HIGH_PROTEIN` and
        at least 5.0 grams per serving for `GOOD_SOURCE_PROTEIN` — or the
        verification is rejected with `ERR_LABEL_CLAIM_UNSUBSTANTIATED`
        (HTTP 422)."

        Design: Corner/validations/c_label_claim_unsubstantiated_at_verify
        """
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        cust = fixtures.create_customer("C1")
        fl = fixtures.create_formula(cust["id"], "FL", bar_weight_g=60)
        # 10 kg * 1000 * 0.80 = 8000 g over floor(100000/60) = 1666 bars
        # -> 4.80 g/serving < 10.0 required for HIGH_PROTEIN.
        rl = fixtures.create_revision(
            fl["id"], [fixtures.line(whey["id"], 10, True)],
            target_protein=10, claim_tags=["HIGH_PROTEIN"],
        )
        fixtures.submit_revision(rl["id"])
        resp = client.verify_nutrition(rl["id"], QM)
        validate_error(resp, ApiErrorId.ERR_LABEL_CLAIM_UNSUBSTANTIATED, 422)
        stayed = validate_success(client.get_revision(rl["id"], QM), 200)
        assert stayed["status"] == "SUBMITTED"


class TestClaimReviewAdjudication:
    def test_request_revision_and_resubmit_cycle(self, api):
        """PRD §3.5: "Requesting revision moves the review from `IN_REVIEW` to
        `REVISION_REQUESTED`, also stamping `reviewer_id`, and a subsequent
        resubmission by a `FormulationScientist` or `BrandCustomerRep` returns
        it to `SUBMITTED` with `substantiation_ok` recomputed — the review may
        cycle through submission, review, and revision-request repeatedly."
        PRD §3.5: "`LOW_SUGAR` derives a sugar load per bar — the sweetener
        lines' `qty_kg_per_batch` figures are summed, converted to grams,
        divided by the batch's bar yield as computed in §3.4, and rounded
        half-up to two decimal places — and is substantiated when that figure
        is at most 4.0 grams per bar, the boundary included."

        Design: Corner/state_machines/c_claim_review_request_revision_cycle
        """
        ns = fixtures.setup_formula_with_revision(
            claim_tags=["LOW_SUGAR"], march_to="NUTRITION_VERIFIED",
        )
        # 10 kg syrup -> 10000/1666 = 6.00 g/bar > 4.0 -> not substantiated.
        review = validate_success(
            client.create_claim_review(
                {
                    "revision_id": ns.r1["id"],
                    "claim_tag": "LOW_SUGAR",
                    "claim_type": "NUTRIENT_CONTENT",
                },
                SCI,
            ),
            201,
        )
        assert review["substantiation_ok"] is False
        validate_success(client.start_claim_review(review["id"], QM), 200)
        requested = validate_success(
            client.request_revision_claim_review(review["id"], QM), 200
        )
        assert requested["status"] == "REVISION_REQUESTED"
        resubmitted = validate_success(
            client.resubmit_claim_review(review["id"], SCI), 200
        )
        assert resubmitted["status"] == "SUBMITTED"

    def test_low_sugar_threshold_boundary(self, api):
        """PRD §3.5: "`LOW_SUGAR` derives a sugar load per bar — the sweetener
        lines' `qty_kg_per_batch` figures are summed, converted to grams,
        divided by the batch's bar yield as computed in §3.4, and rounded
        half-up to two decimal places — and is substantiated when that figure
        is at most 4.0 grams per bar, the boundary included."

        Design: Corner/calculations/c_low_sugar_substantiation_threshold
        """
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        syr = fixtures.create_ingredient(
            "SYRUP", "SWEETENER", [], nominal_sweetness_factor=1.0
        )
        cust = fixtures.create_customer("C1")
        fls = fixtures.create_formula(cust["id"], "FLS", bar_weight_g=60)
        # 10 kg syrup -> 6.00 g/bar (fails); 6 kg syrup -> 3.60 g/bar (passes).
        ra = fixtures.create_revision(
            fls["id"],
            [fixtures.line(whey["id"], 40, True), fixtures.line(syr["id"], 10, False)],
            target_protein=15, claim_tags=["LOW_SUGAR"],
        )
        fixtures.submit_revision(ra["id"])
        fixtures.verify_nutrition(ra["id"])
        rb = fixtures.create_revision(
            fls["id"],
            [fixtures.line(whey["id"], 40, True), fixtures.line(syr["id"], 6, False)],
            target_protein=15, claim_tags=["LOW_SUGAR"],
        )
        fixtures.submit_revision(rb["id"])
        fixtures.verify_nutrition(rb["id"])

        review_a = validate_success(
            client.create_claim_review(
                {"revision_id": ra["id"], "claim_tag": "LOW_SUGAR",
                 "claim_type": "NUTRIENT_CONTENT"},
                SCI,
            ),
            201,
        )
        assert review_a["substantiation_ok"] is False
        review_b = validate_success(
            client.create_claim_review(
                {"revision_id": rb["id"], "claim_tag": "LOW_SUGAR",
                 "claim_type": "NUTRIENT_CONTENT"},
                SCI,
            ),
            201,
        )
        assert review_b["substantiation_ok"] is True

    def test_structure_function_claim_requires_disclaimer(self, api):
        """PRD §3.5: "Approval from `IN_REVIEW` enforces its guards in order:
        the parent revision must currently stand in `NUTRITION_VERIFIED` or
        `CLAIM_REVIEW` so that label substantiation exists (otherwise
        `ERR_INVALID_STATE`, HTTP 409); `substantiation_ok` must be true
        (otherwise `ERR_LABEL_CLAIM_UNSUBSTANTIATED`, HTTP 422); and a
        `STRUCTURE_FUNCTION` review must carry `structure_function_disclaimer`
        true (otherwise `ERR_DISCLAIMER_REQUIRED`, HTTP 422)."

        Design: Corner/validations/c_structure_function_disclaimer_required
        """
        ns = fixtures.setup_formula_with_revision(
            claim_tags=["HIGH_PROTEIN"], march_to="NUTRITION_VERIFIED",
        )
        without = validate_success(
            client.create_claim_review(
                {
                    "revision_id": ns.r1["id"],
                    "claim_tag": "HIGH_PROTEIN",
                    "claim_type": "STRUCTURE_FUNCTION",
                    "structure_function_disclaimer": False,
                },
                SCI,
            ),
            201,
        )
        assert without["substantiation_ok"] is True
        validate_success(client.start_claim_review(without["id"], QM), 200)
        resp = client.approve_claim_review(without["id"], QM)
        validate_error(resp, ApiErrorId.ERR_DISCLAIMER_REQUIRED, 422)

        with_disclaimer = validate_success(
            client.create_claim_review(
                {
                    "revision_id": ns.r1["id"],
                    "claim_tag": "HIGH_PROTEIN",
                    "claim_type": "STRUCTURE_FUNCTION",
                    "structure_function_disclaimer": True,
                },
                SCI,
            ),
            201,
        )
        validate_success(client.start_claim_review(with_disclaimer["id"], QM), 200)
        approved = validate_success(
            client.approve_claim_review(with_disclaimer["id"], QM), 200
        )
        assert approved["status"] == "APPROVED"
