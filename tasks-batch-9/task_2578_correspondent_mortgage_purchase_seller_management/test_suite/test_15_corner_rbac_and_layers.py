"""Who may act, who may not, and which version token the server insists on."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ALT,
    QC,
    REVIEWER,
    REVIEWER_ALT,
    REVIEWER_THIRD,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_commitment_amounts_conserved,
    assert_escrow_transfer,
    assert_loan,
    assert_purchase_advice,
    assert_repurchase_demand,
    assert_seller,
    factories,
    fixtures,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_qc_reviewer_headers,
    make_seller_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEveryRoleActsWithinItsOwnMandate:
    """One traversal in which all six roles do their own work."""

    @staticmethod
    def _onboarding_and_two_lines_split_between_partner_roles() -> dict:
        fixtures.setup_clock()
        product = fixtures.setup_product()
        fixtures.setup_pricing_adjustment(product["id"])
        seller = fixtures.setup_seller()
        seller_headers = make_seller_user_headers(seller["id"])

        statement = validate_success(
            api_client.create_financial_statement(
                seller["id"], factories.financial_statement_payload(), seller_headers
            ),
            201,
        )
        reviewed = fixtures.review_financial_statement(statement["id"], "ACCEPT")
        qc_review = fixtures.setup_qc_review(seller["id"])
        fixtures.complete_qc_review(qc_review["id"])
        approved = fixtures.decide_approval(seller["id"])

        desk_line = fixtures.setup_commitment(seller["id"], product["id"])
        seller_line = validate_success(
            api_client.create_commitment(
                factories.commitment_payload(
                    seller["id"], product["id"], commitment_type="BEST_EFFORTS"
                ),
                seller_headers,
            ),
            201,
        )
        loan_a = fixtures.deliver_loan(
            desk_line["id"], seller["id"], seller_loan_number="HP-0001"
        )
        loan_b = fixtures.deliver_loan(
            seller_line["id"],
            seller["id"],
            actor=TRADER,
            seller_loan_number="HP-0002",
        )
        return {
            "product": product,
            "seller": seller,
            "seller_id": seller["id"],
            "seller_headers": seller_headers,
            "statement": statement,
            "reviewed": reviewed,
            "approved": approved,
            "desk_line": desk_line,
            "seller_line": seller_line,
            "loan_a": loan_a,
            "loan_b": loan_b,
        }

    def test_the_two_shared_entry_points_accept_either_of_their_partner_roles(self):
        """The seller files its own statement, and both roles lock and deliver.

        Filing a statement, locking a line and delivering a file are each shared
        between two roles, and every one of those partners is exercised here: the
        seller files for itself and the analyst adjudicates, the desk locks the
        mandatory line while the seller locks its own best-efforts one, and the two
        deliveries arrive one from each partner. Nothing in the chain is refused on
        role grounds.

        PRD: "A `SellerUser` is the correspondent seller itself, acting on its own
        file — submitting financial statements, locking and delivering loans,
        curing defects, appealing and satisfying repurchase demands."

        PRD: "A `CounterpartyAnalyst` is the counterparty risk analyst: onboards
        sellers, reviews financial statements, renders the approval decision,
        applies manual standing actions and runs the scorecard cycle."

        Design: Corner/rbac/every_role_exercises_its_own_exclusive_and_shared_operations
        """
        staged = self._onboarding_and_two_lines_split_between_partner_roles()

        assert staged["statement"]["status"] == "SUBMITTED"
        assert staged["reviewed"]["status"] == "ACCEPTED"
        assert staged["reviewed"]["reviewed_by_user_id"] == "u-ca-1"

        approved = staged["approved"]
        assert_seller(approved)
        assert approved["approval_status"] == "APPROVED"
        assert approved["approval_tier"] == "STANDARD"
        assert approved["delivery_standing"] == "GOOD_STANDING"

        assert_commitment(staged["desk_line"])
        assert staged["desk_line"]["locked_by_user_id"] == "u-ld-1"
        assert staged["desk_line"]["commitment_type"] == "MANDATORY"
        assert staged["seller_line"]["locked_by_user_id"] == staged["seller_id"]
        assert staged["seller_line"]["commitment_type"] == "BEST_EFFORTS"

        assert_loan(staged["loan_a"])
        assert staged["loan_a"]["purchase_status"] == "DELIVERED"
        assert staged["loan_b"]["purchase_status"] == "DELIVERED"
        loans, meta = validate_paginated(api_client.list_loans(REVIEWER))
        assert meta["total_count"] == 2
        assert {loan["seller_loan_number"] for loan in loans} == {"HP-0001", "HP-0002"}

    def test_the_reviewer_admin_seller_and_analyst_each_take_their_own_step(self):
        """Waiver, settlement, cure, sweep, scorecard and standing all go through.

        The reviewer opens review and records the finding, the platform operator
        waives it and later wires the money and runs the per-loan sweep and opens
        the period, the seller cures the finding on its own second file, and the
        standing dimension is moved by each of its two owners in turn — a manual
        suspension that cancels nothing, then a reinstatement.

        PRD: "A `PlatformAdmin` is the platform operator: maintains the product and
        adjustment catalogue, drives the logical clock, records borrower
        first-payment events, and stands in on operational sweeps and settlements."

        PRD: "`SUSPEND` moves either `GOOD_STANDING → SUSPENDED` or `WATCH →
        SUSPENDED` and sets `suspension_reason` to `MANUAL_COUNTERPARTY_ACTION`;
        crucially, a manual suspension **cancels nothing** — existing locks survive
        it untouched."

        Design: Corner/rbac/every_role_exercises_its_own_exclusive_and_shared_operations
        """
        staged = self._onboarding_and_two_lines_split_between_partner_roles()

        fixtures.open_loan_review(staged["loan_a"]["id"])
        defect_a = fixtures.record_defect(
            staged["loan_a"]["id"], "CRED-DTI-2305", "CREDIT", "MEDIUM"
        )
        waived = validate_success(
            api_client.waive_defect(defect_a["id"], factories.waive_payload(-20), ADMIN),
            200,
        )
        assert waived["status"] == "WAIVED"
        assert waived["price_adjustment_bps"] == -20

        fixtures.clear_loan_for_purchase(staged["loan_a"]["id"])
        advice = fixtures.issue_purchase_advice(staged["loan_a"]["id"])
        assert_purchase_advice(advice)
        assert advice["issued_by_user_id"] == "u-pr-1"
        settled = fixtures.settle_purchase_advice(
            advice["id"], "WIRE-A-0001", actor=ADMIN
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "u-adm-1"
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 40297389

        fixtures.open_loan_review(staged["loan_b"]["id"])
        defect_b = fixtures.record_defect(
            staged["loan_b"]["id"], "CRED-RESERVES-2311", "CREDIT", "MEDIUM"
        )
        cured = fixtures.cure_defect(
            defect_b["id"], staged["seller_id"], "CURE-RES-0001"
        )
        assert cured["status"] == "CURED"

        swept = fixtures.sweep_loan_conditions(staged["loan_b"]["id"], actor=ADMIN)
        assert swept["expired_condition_count"] == 0
        assert swept["expired_defect_count"] == 0

        scorecard = fixtures.open_scorecard(
            staged["seller_id"], "2026-08-01", "2026-08-31", actor=ADMIN
        )
        assert scorecard["status"] == "OPEN"

        suspended = fixtures.apply_standing_action(staged["seller_id"], "SUSPEND")
        assert suspended["delivery_standing"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL_COUNTERPARTY_ACTION"
        assert (
            fixtures.read_commitment(staged["seller_line"]["id"])["status"] == "LOCKED"
        )

        reinstated = fixtures.apply_standing_action(
            staged["seller_id"], "REINSTATE", actor=ADMIN
        )
        assert reinstated["delivery_standing"] == "GOOD_STANDING"
        assert reinstated["suspension_reason"] is None


class TestCrossingIntoAnotherRolesExclusiveOperation:
    """Six refusals, one per role, all decided before any business gate."""

    @staticmethod
    def _an_approved_seller_with_one_file_in_review() -> dict:
        staged = fixtures.setup_loan_in_review(with_adjustment=False)
        return staged

    def test_no_role_may_borrow_another_roles_exclusive_decision(self):
        """The quality reviewer cannot approve and the operator cannot clear.

        Approval belongs to the analyst and clearing to the purchase reviewer, and
        neither can be borrowed: the quality reviewer's approval attempt and the
        platform operator's clearing attempt are both refused on the role list
        alone, leaving the seller's own recorded decision and the loan's review
        state exactly as they were. The operator is not a hierarchical override.

        PRD: "If both headers are present but the declared role is not among the
        roles authorized for the addressed endpoint (see the table in §4), the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD: "A `QCReviewer` opens and completes quality-control review files, and
        is deliberately barred from approving the seller it reviewed."

        Design: Corner/rbac/each_role_is_forbidden_from_other_roles_exclusive_operations
        """
        staged = self._an_approved_seller_with_one_file_in_review()

        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"], factories.approval_decision_payload("APPROVE"), QC
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["approval_status"] == "APPROVED"
        assert seller["approval_decided_by_user_id"] == "u-ca-1"

        validate_error(
            api_client.clear_loan(staged["loan_id"], ADMIN),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "IN_REVIEW"

    def test_the_role_check_runs_ahead_of_every_business_gate(self):
        """The analyst's pair-off is a role failure, not an allocation failure.

        A pair-off on this line would fail its own business gate too, because the
        line still carries a delivered loan — but the analyst never reaches that
        gate. The same precedence keeps the reviewer out of the quality-control
        collection, the desk out of the defect log and the seller out of the
        product catalogue, and none of those refusals leaves a row behind.

        PRD: "**Role authorization.** The declared role is listed for the endpoint,
        else `ERR_FORBIDDEN_ROLE`."

        PRD: "A `LockDeskTrader` prices and locks commitments, runs the expiry
        sweep and executes pair-offs."

        Design: Corner/rbac/each_role_is_forbidden_from_other_roles_exclusive_operations
        """
        staged = self._an_approved_seller_with_one_file_in_review()

        pair_off = validate_error(
            api_client.pair_off_commitment(
                staged["commitment_id"], factories.pair_off_payload(100.500), ANALYST
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        assert pair_off["error_id"] != ApiErrorId.ERR_ALLOCATION_OUTSTANDING
        assert fixtures.read_commitment(staged["commitment_id"])["status"] == "LOCKED"

        validate_error(
            api_client.create_qc_review(
                staged["seller_id"],
                factories.qc_review_payload("ANNUAL_RECERT"),
                REVIEWER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        reviews, meta = validate_paginated(
            api_client.list_qc_reviews(staged["seller_id"], QC)
        )
        assert meta["total_count"] == 1
        assert reviews[0]["review_type"] == "PRE_APPROVAL"

        validate_error(
            api_client.create_defect(
                staged["loan_id"],
                factories.defect_payload("CRED-DTI-2305", "CREDIT", "MEDIUM"),
                TRADER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        assert fixtures.read_loan(staged["loan_id"])["open_defect_count"] == 0

        validate_error(
            api_client.create_product(
                factories.product_payload(
                    product_code="CONF15F",
                    base_price_pct=102.000,
                    allowed_commitment_types=["MANDATORY"],
                    allowed_occupancies=["PRIMARY"],
                    srp_pct=1.000,
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        assert (
            validate_success(
                api_client.get_product(staged["product_id"], ADMIN)
            )["product_code"]
            == "CONF30F"
        )


class TestIdentityHeadersDecideBeforeAnythingElse:
    """A missing header is not the same failure as an unrecognised role."""

    @staticmethod
    def _a_clock_and_one_product() -> dict:
        fixtures.setup_clock()
        return fixtures.setup_product()

    def test_absent_or_empty_identity_headers_are_all_unauthenticated(self):
        """Omitting either header, or sending an empty one, fails at 401.

        Three malformed requests are sent: one carrying a user id but no role
        header, one carrying a role but no user id header, and one whose role
        header is present but blank. All three are rejected before any routing or
        role resolution happens, and the two that tried to register a seller leave
        no seller behind — an empty header is treated as missing, not as an
        unrecognised role.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which that user
        acts."

        PRD: "If either header is absent or empty, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

        Design: Corner/rbac/missing_x_user_headers_are_unauthenticated_while_an_unknown_role_is_forbidden
        """
        product = self._a_clock_and_one_product()

        validate_error(
            api_client.get_product(product["id"], headers_without_role("u-adm-1")),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api_client.create_seller(
                factories.seller_payload(
                    legal_name="Nameless Lending LLC", tin="500000001", seller_type="BANK"
                ),
                headers_without_user_id("CounterpartyAnalyst"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api_client.create_seller(
                factories.seller_payload(
                    legal_name="Nameless Lending LLC", tin="500000001", seller_type="BANK"
                ),
                headers_with_empty_role("u-ca-1"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api_client.create_seller(
                factories.seller_payload(
                    legal_name="Nameless Lending LLC", tin="500000001", seller_type="BANK"
                ),
                headers_with_empty_user_id("CounterpartyAnalyst"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        _, meta = validate_paginated(api_client.list_sellers(ANALYST))
        assert meta["total_count"] == 0

    def test_an_unrecognised_role_string_gets_past_authentication_and_is_forbidden(self):
        """A well-formed pair naming a role nobody defined stops at 403.

        Both headers are present and non-empty, so authentication succeeds; the
        declared capacity, however, appears on no endpoint's authorized list, so
        the request is refused one step later. The distinction matters — the status
        and the identifier both differ from the malformed-header case — and the
        registration attempt still leaves no seller behind.

        PRD: "Six roles exist, spelled exactly as follows: `SellerUser`,
        `CounterpartyAnalyst`, `QCReviewer`, `LockDeskTrader`, `PurchaseReviewer`,
        and `PlatformAdmin`."

        PRD: "If both headers are present but the declared role is not among the
        roles authorized for the addressed endpoint (see the table in §4), the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/missing_x_user_headers_are_unauthenticated_while_an_unknown_role_is_forbidden
        """
        self._a_clock_and_one_product()

        validate_error(
            api_client.create_seller(
                factories.seller_payload(
                    legal_name="Nameless Lending LLC", tin="500000001", seller_type="BANK"
                ),
                make_headers("u-au-1", "Auditor"),
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        _, meta = validate_paginated(api_client.list_sellers(ANALYST))
        assert meta["total_count"] == 0


class TestOneSellerReachingIntoAnothersFile:
    """Ownership is checked on whatever the path or body reaches."""

    @staticmethod
    def _a_victim_seller_with_a_file_and_an_unapproved_outsider() -> dict:
        staged = fixtures.setup_loan_in_review()
        defect = fixtures.record_defect(
            staged["loan_id"], "INC-DOC-2201", "INCOME", "MEDIUM"
        )
        outsider = fixtures.setup_seller(
            legal_name="Outsider Mortgage Co",
            tin="600220117",
            seller_type="CREDIT_UNION",
        )
        staged["defect"] = defect
        staged["outsider"] = outsider
        staged["outsider_headers"] = make_seller_user_headers(outsider["id"])
        staged["commitment_version"] = fixtures.commitment_version(
            staged["commitment_id"]
        )
        return staged

    def test_the_outsider_is_refused_on_the_victims_row_statements_and_scorecards(self):
        """Reading, filing and listing against a stranger's seller all stop at 403.

        The scope check compares the acting identity against the owning seller of
        whatever the request reaches, so the outsider cannot read the victim's row,
        cannot file a statement into its collection and cannot list its scorecard
        history. Its own row, still sitting at the initial applied state, reads
        back perfectly well — the refusal is about ownership, not about state.

        PRD: "Concretely, a `SellerUser` may only address a `Seller` whose `id`
        equals `X-User-ID`, or a `Commitment`, `Loan`, `FinancialStatement`,
        `SellerScorecard` or `RepurchaseDemand` whose `seller_id` equals
        `X-User-ID` — whether that resource is reached through the URL path or
        named in the request body."

        PRD: "A violation is rejected with `ERR_SELLER_SCOPE_VIOLATION` (HTTP
        403)."

        Design: Corner/rbac/seller_user_reaching_another_sellers_resources_is_forbidden
        """
        staged = self._a_victim_seller_with_a_file_and_an_unapproved_outsider()
        outsider_headers = staged["outsider_headers"]

        validate_error(
            api_client.get_seller(staged["seller_id"], outsider_headers),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api_client.create_financial_statement(
                staged["seller_id"],
                factories.financial_statement_payload(
                    tangible_net_worth_cents=999_000_000,
                    liquid_assets_cents=200_000_000,
                ),
                outsider_headers,
            ),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api_client.list_scorecards(staged["seller_id"], outsider_headers),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION,
            403,
        )

        statements, meta = validate_paginated(
            api_client.list_financial_statements(staged["seller_id"], ANALYST)
        )
        assert meta["total_count"] == 1
        assert statements[0]["tangible_net_worth_cents"] == 300_000_000

        own_row = validate_success(
            api_client.get_seller(staged["outsider"]["id"], outsider_headers)
        )
        assert own_row["approval_status"] == "APPLIED"
        assert own_row["delivery_standing"] == "NOT_ELIGIBLE"

    def test_the_scope_check_beats_the_state_gate_the_outsider_also_violates(self):
        """Delivering into a stranger's line answers scope, not approval state.

        The outsider is unapproved as well as uninvolved, so its delivery breaks
        two rules at once — and the answer is the ownership refusal, decided ahead
        of the eligibility gate. The same holds two hops away on the victim's
        defect, reached only through the victim's loan. Neither refusal moves the
        commitment's allocation or version, and the defect stays open.

        PRD: "**Seller ownership scope.** On every endpoint whose authorized roles
        include `SellerUser`, a caller acting as `SellerUser` must own the addressed
        resource, else `ERR_SELLER_SCOPE_VIOLATION`."

        PRD: "**Counterparty eligibility and compliance gates**, in this relative
        order: `ERR_SELLER_NOT_APPROVED`, `ERR_SELLER_DELIVERY_SUSPENDED`,
        `ERR_NO_ACCEPTED_STATEMENT`, `ERR_FINANCIAL_STATEMENT_STALE`,
        `ERR_NET_WORTH_BELOW_MINIMUM`, `ERR_LIQUIDITY_BELOW_MINIMUM`,
        `ERR_QC_REVIEW_NOT_COMPLETED`, `ERR_QC_REVIEW_FAILED`,
        `ERR_NON_CURABLE_DEFECT_PRESENT`, `ERR_LOAN_UNDER_REPURCHASE`."

        Design: Corner/rbac/seller_user_reaching_another_sellers_resources_is_forbidden
        """
        staged = self._a_victim_seller_with_a_file_and_an_unapproved_outsider()
        outsider_headers = staged["outsider_headers"]

        delivery = validate_error(
            api_client.deliver_loan(
                staged["commitment_id"],
                factories.loan_payload(
                    staged["commitment_version"],
                    seller_loan_number="OS-0001",
                    note_amount_cents=30_000_000,
                    note_rate_pct=6.750,
                ),
                outsider_headers,
            ),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION,
            403,
        )
        assert delivery["error_id"] != ApiErrorId.ERR_SELLER_NOT_APPROVED

        validate_error(
            api_client.cure_defect(
                staged["defect"]["id"],
                factories.cure_payload("OUTSIDER-0001"),
                outsider_headers,
            ),
            ApiErrorId.ERR_SELLER_SCOPE_VIOLATION,
            403,
        )

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["allocated_amount_cents"] == 40_000_000
        assert commitment["version"] == staged["commitment_version"]
        assert fixtures.read_loan_defects(staged["loan_id"])[0]["status"] == "OPEN"


class TestNobodyMayTakeBothHalvesOfASegregatedDecision:
    """Prepare and decide must be two different identities, three times over."""

    @staticmethod
    def _a_seller_whose_qc_completer_is_also_an_analyst_identity() -> dict:
        fixtures.setup_clock()
        grid = fixtures.setup_product_with_grid()
        seller = fixtures.setup_seller()
        statement = fixtures.setup_financial_statement(seller["id"])
        fixtures.review_financial_statement(statement["id"], "ACCEPT")
        dual_hatted = make_qc_reviewer_headers("u-ca-1")
        qc_review = fixtures.setup_qc_review(
            seller["id"], "PRE_APPROVAL", actor=dual_hatted
        )
        completed = fixtures.complete_qc_review(qc_review["id"], 2, 0, actor=dual_hatted)
        return {
            "product_id": grid["product_id"],
            "seller_id": seller["id"],
            "seller_headers": make_seller_user_headers(seller["id"]),
            "completed_review": completed,
        }

    def test_the_analyst_who_completed_the_review_cannot_approve_the_seller(self):
        """The dual-hatted identity is refused, and a second analyst approves.

        The quality-control review was completed by the very user id that now asks
        to approve the seller, so the approval is refused on identity even though
        the role is right and every substantive gate would have passed. The seller
        stays where the opened review left it, and a second holder of the analyst
        role clears it immediately afterwards.

        PRD: "On the seller approval decision, `X-User-ID` must differ from the
        `completed_by_user_id` of the governing quality-control review."

        PRD: "Opening the seller's **first** review is what starts the formal
        underwriting: it automatically advances the seller `APPLIED → UNDER_REVIEW`
        on the approval dimension and increments the seller's `version` by 1."

        Design: Corner/rbac/the_same_user_cannot_perform_both_halves_of_the_three_segregated_steps
        """
        staged = self._a_seller_whose_qc_completer_is_also_an_analyst_identity()
        assert staged["completed_review"]["completed_by_user_id"] == "u-ca-1"

        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"],
                factories.approval_decision_payload("APPROVE"),
                ANALYST,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        blocked = fixtures.read_seller(staged["seller_id"])
        assert blocked["approval_status"] == "UNDER_REVIEW"
        assert blocked["approval_decided_by_user_id"] is None

        approved = fixtures.decide_approval(
            staged["seller_id"], "APPROVE", actor=ANALYST_ALT
        )
        assert approved["approval_status"] == "APPROVED"
        assert approved["approval_decided_by_user_id"] == "u-ca-2"
        assert approved["delivery_standing"] == "GOOD_STANDING"

    def test_the_reviewer_who_issued_the_wire_cannot_release_it(self):
        """Self-settlement is refused, and a second reviewer wires the money.

        The advice's issuer asks to settle its own advice: role-legal, identity-
        illegal. The advice is left untouched in its issued state and the seller
        has been funded nothing, then a different reviewer settles the same advice
        and the funding lands under that second identity.

        PRD: "On the settlement of a purchase advice, `X-User-ID` must differ from
        that advice's `issued_by_user_id`."

        PRD: "The advice moves `ISSUED → SETTLED` with `settled_by_user_id` and
        `settled_at` recorded, and the settlement fans out:"

        Design: Corner/rbac/the_same_user_cannot_perform_both_halves_of_the_three_segregated_steps
        """
        staged = self._a_seller_whose_qc_completer_is_also_an_analyst_identity()
        fixtures.decide_approval(staged["seller_id"], "APPROVE", actor=ANALYST_ALT)
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"]
        )
        loan = fixtures.deliver_loan(commitment["id"], staged["seller_id"])
        fixtures.open_loan_review(loan["id"])
        defect = fixtures.record_defect(loan["id"], "INC-DOC-2201", "INCOME", "HIGH")
        fixtures.waive_defect(defect["id"], -25)
        fixtures.clear_loan_for_purchase(loan["id"])
        advice = fixtures.issue_purchase_advice(loan["id"])
        assert advice["issued_by_user_id"] == "u-pr-1"

        validate_error(
            api_client.settle_purchase_advice(
                advice["id"], factories.settlement_payload("WIRE-0001"), REVIEWER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        blocked = fixtures.read_loan_advices(loan["id"])[0]
        assert blocked["status"] == "ISSUED"
        assert blocked["settled_by_user_id"] is None
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 0

        settled = fixtures.settle_purchase_advice(
            advice["id"], "WIRE-0001", actor=REVIEWER_ALT
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "u-pr-2"
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 40277389

    def test_the_reviewer_who_issued_the_demand_cannot_decide_it(self):
        """The demand's author cannot rule on the appeal; a third reviewer can.

        A repurchase demand backed by the waived high-severity finding is issued,
        appealed by the seller, and then its own author tries to uphold it — the
        segregation check refuses that, whichever way the decision would have gone,
        and the demand stays appealed. A third reviewer rescinds instead, which
        returns the loan to its purchased state and, because no money ever moved on
        the demand, leaves the funding figure exactly as the wire left it.

        PRD: "On the decision of a repurchase demand — whether the decision upholds
        or rescinds — `X-User-ID` must differ from that demand's
        `issued_by_user_id`."

        PRD: "Rescission moves the demand `ISSUED → RESCINDED` or `APPEALED →
        RESCINDED`, a terminal status, cascades the loan `REPURCHASE_DEMANDED →
        PURCHASED`, and removes the loan from the defective population this demand
        had contributed to the seller's scorecard."

        Design: Corner/rbac/the_same_user_cannot_perform_both_halves_of_the_three_segregated_steps
        """
        staged = self._a_seller_whose_qc_completer_is_also_an_analyst_identity()
        fixtures.decide_approval(staged["seller_id"], "APPROVE", actor=ANALYST_ALT)
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"]
        )
        loan = fixtures.deliver_loan(commitment["id"], staged["seller_id"])
        fixtures.open_loan_review(loan["id"])
        defect = fixtures.record_defect(loan["id"], "INC-DOC-2201", "INCOME", "HIGH")
        fixtures.waive_defect(defect["id"], -25)
        fixtures.clear_loan_for_purchase(loan["id"])
        advice = fixtures.issue_purchase_advice(loan["id"])
        fixtures.settle_purchase_advice(advice["id"], "WIRE-0001", actor=REVIEWER_ALT)

        demand = fixtures.issue_repurchase_demand(
            loan["id"], "DEFECT", "RD-2026-0001", source_defect_id=defect["id"]
        )
        assert_repurchase_demand(demand)
        assert demand["issued_by_user_id"] == "u-pr-1"
        fixtures.appeal_repurchase_demand(
            demand["id"], staged["seller_id"], "documentation was sufficient"
        )

        validate_error(
            api_client.decide_repurchase_demand(
                demand["id"], factories.demand_decision_payload("UPHOLD"), REVIEWER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        blocked = validate_success(
            api_client.get_repurchase_demand(demand["id"], REVIEWER)
        )
        assert blocked["status"] == "APPEALED"
        assert blocked["decided_by_user_id"] is None

        rescinded = fixtures.decide_repurchase_demand(
            demand["id"], "RESCIND", "independent reviewer disagrees",
            actor=REVIEWER_THIRD,
        )
        assert rescinded["status"] == "RESCINDED"
        assert rescinded["decided_by_user_id"] == "u-pr-3"
        assert fixtures.read_loan(loan["id"])["purchase_status"] == "PURCHASED"
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 40277389


class TestTheDeliveryVersionTokenMustBeFresh:
    """A line's version moves on every delivery, and the client must keep up."""

    @staticmethod
    def _an_approved_seller_holding_one_empty_line() -> dict:
        return fixtures.setup_locked_commitment(with_adjustment=False)

    def test_a_second_delivery_replaying_the_pre_delivery_token_is_refused(self):
        """The stale token loses even though the line has room to spare.

        The first delivery advances the line's version, so a second delivery still
        carrying the pre-delivery token is refused with a precondition failure —
        and the refusal is about the token, not about capacity: the thirty million
        being delivered fits comfortably inside the sixty million still available.
        Nothing moves on the line, and no loan is created.

        PRD: "On the commitment side, `allocated_amount_cents` rises by the
        delivered `note_amount_cents`, `available_amount_cents` falls by the same
        amount, and the commitment's `version` increments by 1 — which is precisely
        what makes a second delivery carrying the original
        `expected_commitment_version` stale."

        PRD: "**Optimistic concurrency**, else `ERR_STALE_COMMITMENT_VERSION` or
        `ERR_STALE_LOAN_VERSION` — see §2.8."

        Design: Corner/complexity_layers/stale_expected_commitment_version_on_a_second_delivery_is_rejected
        """
        staged = self._an_approved_seller_holding_one_empty_line()
        first_token = staged["commitment"]["version"]

        first = fixtures.deliver_loan(
            staged["commitment_id"],
            staged["seller_id"],
            seller_loan_number="HP-0001",
            expected_version=first_token,
        )
        assert first["note_amount_cents"] == 40_000_000
        after_first = fixtures.read_commitment(staged["commitment_id"])
        assert after_first["version"] == first_token + 1
        assert after_first["allocated_amount_cents"] == 40_000_000
        assert after_first["available_amount_cents"] == 60_000_000

        validate_error(
            api_client.deliver_loan(
                staged["commitment_id"],
                factories.loan_payload(
                    first_token,
                    seller_loan_number="HP-0002",
                    note_amount_cents=30_000_000,
                    closing_date="2026-07-29",
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_STALE_COMMITMENT_VERSION,
            412,
        )
        after_refusal = fixtures.read_commitment(staged["commitment_id"])
        assert after_refusal["version"] == first_token + 1
        assert after_refusal["allocated_amount_cents"] == 40_000_000
        _, meta = validate_paginated(
            api_client.list_loans(TRADER, {"commitment_id": staged["commitment_id"]})
        )
        assert meta["total_count"] == 1

    def test_re_reading_the_line_makes_the_very_same_delivery_succeed(self):
        """The identical payload lands once it carries the refreshed token.

        After the refusal the client re-reads the line, picks up the current token
        and replays exactly the same delivery — same loan number, same amount — and
        it is accepted. Two loans now sit on the line, the second one exactly once,
        and the conserved amounts show both allocations.

        PRD: "A `POST /correspondent/commitments/{id}/loans` request must carry
        `expected_commitment_version`, matching the addressed commitment's current
        `version`."

        PRD: "The behaviour is observable with two strictly sequential requests:
        the first delivery advances the commitment's `version`, so a second delivery
        still carrying the pre-delivery number is refused."

        Design: Corner/complexity_layers/stale_expected_commitment_version_on_a_second_delivery_is_rejected
        """
        staged = self._an_approved_seller_holding_one_empty_line()
        first_token = staged["commitment"]["version"]
        fixtures.deliver_loan(
            staged["commitment_id"],
            staged["seller_id"],
            seller_loan_number="HP-0001",
            expected_version=first_token,
        )
        validate_error(
            api_client.deliver_loan(
                staged["commitment_id"],
                factories.loan_payload(
                    first_token,
                    seller_loan_number="HP-0002",
                    note_amount_cents=30_000_000,
                    closing_date="2026-07-29",
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_STALE_COMMITMENT_VERSION,
            412,
        )

        fresh_token = fixtures.commitment_version(staged["commitment_id"])
        assert fresh_token == first_token + 1
        second = fixtures.deliver_loan(
            staged["commitment_id"],
            staged["seller_id"],
            seller_loan_number="HP-0002",
            expected_version=fresh_token,
            note_amount_cents=30_000_000,
            closing_date="2026-07-29",
        )
        assert second["purchase_status"] == "DELIVERED"

        final = fixtures.read_commitment(staged["commitment_id"])
        assert final["version"] == first_token + 2
        assert final["allocated_amount_cents"] == 70_000_000
        assert final["available_amount_cents"] == 30_000_000
        assert_commitment_amounts_conserved(final)

        loans, meta = validate_paginated(
            api_client.list_loans(TRADER, {"commitment_id": staged["commitment_id"]})
        )
        assert meta["total_count"] == 2
        numbers = [loan["seller_loan_number"] for loan in loans]
        assert sorted(numbers) == ["HP-0001", "HP-0002"]


class TestTheAdviceVersionTokenMustBeFresh:
    """Re-issuing an advice is legal, but only with the loan's current token."""

    @staticmethod
    def _a_cleared_loan_and_its_token() -> dict:
        staged = fixtures.setup_cleared_loan()
        staged["loan_token"] = staged["loan"]["version"]
        return staged

    def test_replaying_the_pre_issuance_token_on_a_second_advice_is_refused(self):
        """The second issuance is legal in itself and still fails on the token.

        Issuing an advice bumps the loan's version, so replaying the issuance with
        the pre-issuance token is refused with a precondition failure. This is not
        a state precondition in disguise — a later advice supersedes an earlier one
        and would have been perfectly legal — and the refused attempt leaves the
        advice count where it was.

        PRD: "The loan's `advice_count` rises by one and its `version` increments by
        1 — which is exactly why a re-issue must carry a fresh
        `expected_loan_version`."

        PRD: "Issuing a second advice on a loan is legitimate — re-pricing after a
        defect waiver or cure supersedes the earlier advice — so this conflict
        cannot be resolved by a state precondition; both the first and the second
        issuance are individually valid."

        Design: Corner/complexity_layers/stale_expected_loan_version_on_advice_creation_is_rejected
        """
        staged = self._a_cleared_loan_and_its_token()
        first_token = staged["loan_token"]

        first = fixtures.issue_purchase_advice(
            staged["loan_id"], expected_version=first_token
        )
        assert_purchase_advice(first)
        assert first["net_wire_cents"] == 40377389

        validate_error(
            api_client.create_purchase_advice(
                staged["loan_id"], factories.advice_payload(first_token), REVIEWER
            ),
            ApiErrorId.ERR_STALE_LOAN_VERSION,
            412,
        )
        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["version"] == first_token + 1
        assert loan["advice_count"] == 1
        assert loan["purchase_status"] == "CLEARED_FOR_PURCHASE"
        assert len(fixtures.read_loan_advices(staged["loan_id"])) == 1

    def test_the_refreshed_token_lets_the_replay_supersede_the_first_advice(self):
        """The same advice request, retried with the current token, is accepted.

        Re-reading the loan yields the token the first issuance produced, and the
        identical request then succeeds: the earlier advice is pushed aside for
        audit while the new one becomes the live one. Both carry the same money,
        which is the point — nothing but the version token decided the outcome —
        and issuing an advice never moves the loan's own purchase status.

        PRD: "Any prior advice of the same loan still in `ISSUED` status moves
        `ISSUED → SUPERSEDED`, so at most one advice is live at a time; superseded
        and voided advices are retained for audit."

        PRD: "Any defect waiver, cure, condition clearance or review-cycle
        transition in between advances the loan's `version` and invalidates a
        request still carrying the earlier number, which is rejected with
        `ERR_STALE_LOAN_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_expected_loan_version_on_advice_creation_is_rejected
        """
        staged = self._a_cleared_loan_and_its_token()
        first_token = staged["loan_token"]
        first = fixtures.issue_purchase_advice(
            staged["loan_id"], expected_version=first_token
        )
        validate_error(
            api_client.create_purchase_advice(
                staged["loan_id"], factories.advice_payload(first_token), REVIEWER
            ),
            ApiErrorId.ERR_STALE_LOAN_VERSION,
            412,
        )

        fresh_token = fixtures.loan_version(staged["loan_id"])
        assert fresh_token == first_token + 1
        second = fixtures.issue_purchase_advice(
            staged["loan_id"], expected_version=fresh_token
        )
        assert second["id"] != first["id"]
        assert second["status"] == "ISSUED"
        assert second["net_wire_cents"] == first["net_wire_cents"] == 40377389

        advices = fixtures.read_loan_advices(staged["loan_id"])
        by_id = {advice["id"]: advice["status"] for advice in advices}
        assert by_id[first["id"]] == "SUPERSEDED"
        assert by_id[second["id"]] == "ISSUED"
        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["advice_count"] == 2
        assert loan["purchase_status"] == "CLEARED_FOR_PURCHASE"


class TestOneResponseCarriesEveryConsequenceOfItsOwnMutation:
    """The settling call's own body already shows the whole fan-out."""

    @staticmethod
    def _a_released_loan_with_its_advice_issued() -> dict:
        staged = fixtures.setup_cleared_loan(
            loan_overrides={
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 250_000,
            }
        )
        staged["advice"] = fixtures.issue_purchase_advice(staged["loan_id"])
        return staged

    def test_the_settlement_response_itself_reports_the_settled_advice(self):
        """No second read is needed to see the advice's own new state.

        The settling request answers with the advice as it now stands: settled, the
        funding reference recorded, and the settlement instant stamped from the
        logical clock the call was made under. The value is final on its first
        observation.

        PRD: "The advice moves `ISSUED → SETTLED` with `settled_by_user_id` and
        `settled_at` recorded, and the settlement fans out:"

        PRD: "The propagation is immediate and synchronous: by the time the
        response to the triggering request is written, every downstream effect has
        already landed."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_caused_it
        """
        staged = self._a_released_loan_with_its_advice_issued()

        settled = fixtures.settle_purchase_advice(
            staged["advice"]["id"], "WIRE-0001", actor=REVIEWER_ALT
        )
        assert_purchase_advice(settled)
        assert settled["status"] == "SETTLED"
        assert settled["funding_reference"] == "WIRE-0001"
        assert settled["settled_at"] == "2026-08-01T00:00:00.000Z"
        assert settled["settled_by_user_id"] == "u-pr-2"
        assert settled["net_wire_cents"] == 41127389

    def test_every_cascaded_row_is_already_final_when_the_wire_returns(self):
        """Loan, line, seller and escrow child are all current immediately.

        Reading each cascaded row straight after the wire shows it already settled
        into its final shape: the loan purchased and stamped, the line partially
        filled by exactly this loan, the seller's funding figure reconciled, and
        the escrow transfer the cascade created already discoverable and due. The
        line's mandatory exposure is untouched, because a partially filled line is
        not terminal and releases nothing.

        PRD: "It rises when a mandatory commitment is locked and falls by the full
        notional the moment that commitment reaches any terminal status."

        PRD: "When the loan's `servicing_election` is `RELEASED`, an
        **EscrowTransfer** is created in `PENDING` status with
        `transfer_amount_cents` frozen at the loan's `escrow_balance_cents` and
        `transfer_due_at` set to `purchased_at` advanced by 15 days."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_caused_it
        """
        staged = self._a_released_loan_with_its_advice_issued()

        fixtures.settle_purchase_advice(
            staged["advice"]["id"], "WIRE-0001", actor=REVIEWER_ALT
        )

        loan = fixtures.read_loan(staged["loan_id"])
        assert_loan(loan)
        assert loan["purchase_status"] == "PURCHASED"
        assert loan["purchased_at"] == "2026-08-01T00:00:00.000Z"

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "PARTIALLY_FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 40_000_000
        assert commitment["allocated_amount_cents"] == 0
        assert_commitment_amounts_conserved(commitment)

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["net_funded_cents"] == 41127389
        assert seller["open_mandatory_exposure_cents"] == 100_000_000

        transfer = fixtures.read_pending_escrow_transfer(staged["loan_id"])
        assert_escrow_transfer(transfer)
        assert transfer["status"] == "PENDING"
        assert transfer["transfer_amount_cents"] == 250_000
        assert transfer["transfer_due_at"] == "2026-08-16T00:00:00.000Z"
