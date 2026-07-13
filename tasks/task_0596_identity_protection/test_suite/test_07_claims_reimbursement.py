"""Insurance claims: creation, supersession, submission, and the reimbursement calculation
(PRD §3.7, §2.6)."""

from test_helpers import (
    SIX_LINE_EXPENSES,
    ApiErrorId,
    assert_insurance_claim,
    create_claim,
    create_claim_payload,
    expense,
    get_case,
    get_claim,
    get_subscriber,
    list_claims,
    make_adjuster_headers,
    make_subscriber_headers,
    setup_approved_claim,
    setup_in_progress_case,
    setup_resolved_case,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

SSN_ALERT = {"alert_type": "SSN_TRACE", "severity": "MEDIUM",
             "source_detail": "tax return filed with subscriber SSN"}


class TestProvisionalVersusFinal:
    """The same expense array yields two different numbers under the two variants."""

    def test_submission_half_credits_an_undocumented_expense(self, api):
        """PRD §3.7: "A line item with `documented` true is credited in full, a factor of 1. A line
        item with `documented` false is credited at one half under the PROVISIONAL variant, and at
        zero — that is, it drops out entirely — under the FINAL variant. Round that per-item product
        half up to whole cents, immediately, before doing anything else with it."
        PRD §3.7: "Submission runs the reimbursement calculation in its **PROVISIONAL** variant and
        writes the result to `provisional_amount_cents`, the estimate the subscriber is shown, and
        increments the claim's `version` by one."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_diverge_on_identical_expenses
        """
        ctx = setup_submitted_claim(
            expenses=SIX_LINE_EXPENSES, alert_overrides=SSN_ALERT
        )

        claim = ctx["claim"]
        assert_insurance_claim(claim)
        assert claim["status"] == "SUBMITTED"
        # 120000 + min(266666, 250000) + 2251 + 2251 + 7500 + 2501 - 2500 == 382003
        assert claim["provisional_amount_cents"] == 382003
        assert claim["approved_cents"] is None, "approve has not run yet"

    def test_approval_drops_the_undocumented_expense_entirely(self, api):
        """PRD §3.7: "Approval carries it `SUBMITTED → APPROVED`, runs the reimbursement calculation
        in its **FINAL** variant, writes the result to `approved_cents`, and records the adjuster's
        `X-User-ID` in `approved_by_user_id`."
        PRD §3.7: "Because the FINAL variant zeroes out undocumented items while PROVISIONAL
        half-credits them, a claim containing any undocumented expense always approves for strictly
        less than its provisional estimate — that difference is the whole point of the two variants,
        and subscribers are told as much."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_diverge_on_identical_expenses
        """
        ctx = setup_submitted_claim(expenses=SIX_LINE_EXPENSES, alert_overrides=SSN_ALERT)

        approved = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adjuster-001"))
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "adjuster-001"
        # The undocumented CHILDCARE line contributes 7500 under PROVISIONAL and 0 under FINAL.
        assert approved["provisional_amount_cents"] == 382003
        assert approved["approved_cents"] == 374503
        assert approved["approved_cents"] < approved["provisional_amount_cents"], (
            "an undocumented expense always approves for strictly less"
        )


class TestPinnedRoundingOrder:
    """Round each line item first, then sum — never the other way round."""

    def test_two_travel_lines_round_individually_before_summing(self, api):
        """PRD §3.7: "Round that per-item product half up to whole cents, immediately, before doing
        anything else with it. Step two: for each category, sum the *already-rounded* eligible
        amounts of every line item in that category."
        PRD §3.7: "Rounding once at the end instead of per line item in step one produces a
        different number of cents and is incorrect."

        Design: Difficulty/combinatorial_formula/claim_rounding_pinned_round_per_expense_then_sum
        """
        ctx = setup_submitted_claim(expenses=SIX_LINE_EXPENSES, alert_overrides=SSN_ALERT)

        approved = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adjuster-002"))
        )
        # TRAVEL: round_half_up(4501 * 0.50) == 2251 twice, summing to 4502.
        # The forbidden sum-then-round order gives round_half_up(9002 * 0.50) == 4501.
        assert approved["approved_cents"] == 374503
        assert approved["approved_cents"] != 374502, (
            "374502 is the sum-then-round answer and is wrong"
        )

    def test_the_same_rounding_order_governs_the_provisional_estimate(self, api):
        """PRD §2.9: "Crucially, *where* the rounding happens is part of the specification, not an
        implementation detail: the composite credit score rounds only the final weighted quotient,
        and the reimbursement calculation rounds each expense line item individually and nowhere
        else. Summing unrounded products and rounding once at the end produces a different number of
        cents and is wrong."
        PRD §3.7: "Step four: sum the capped category totals across every category present in the
        claim to get the gross, then subtract a flat deductible of 2,500 cents, flooring the result
        at zero — a small claim can be reduced to nothing but never to a negative."

        Design: Difficulty/combinatorial_formula/claim_rounding_pinned_round_per_expense_then_sum
        """
        ctx = setup_submitted_claim(expenses=SIX_LINE_EXPENSES, alert_overrides=SSN_ALERT)

        claim = get_claim(ctx["claim"]["id"])
        assert claim["provisional_amount_cents"] == 382003
        assert claim["provisional_amount_cents"] != 382002, (
            "the sum-then-round order shifts the TRAVEL category by one cent"
        )


class TestReimbursementBoundaries:
    def test_a_claim_below_the_deductible_floors_at_zero(self, api):
        """PRD §3.7: "Step four: sum the capped category totals across every category present in the
        claim to get the gross, then subtract a flat deductible of 2,500 cents, flooring the result
        at zero — a small claim can be reduced to nothing but never to a negative."

        Design: Corner/calculations/claim_deductible_floors_reimbursement_at_zero
        """
        ctx = setup_submitted_claim(
            expenses=[expense("POSTAGE", 1500, True)], alert_overrides=SSN_ALERT
        )

        claim = ctx["claim"]
        # POSTAGE is covered in full: gross 1500, less the 2500 deductible, floored at 0.
        assert claim["provisional_amount_cents"] == 0, "floored at zero, never negative"
        assert claim["status"] == "SUBMITTED"

    def test_the_lost_wages_category_sublimit_caps_the_payout(self, api):
        """PRD §3.7: "Step three: apply the category sublimits — `LOST_WAGES` is capped at 250,000
        cents, `TRAVEL` at 100,000 cents, and `CHILDCARE` at 100,000 cents; a category's total is
        replaced by the smaller of itself and its sublimit."
        PRD §3.7: "Step one, per line item, individually: multiply the item's `amount_cents` by its
        category's coverage percentage — `LEGAL_FEES`, `NOTARY` and `POSTAGE` are covered in full at
        100 percent, `LOST_WAGES` at 80 percent, `TRAVEL` and `CHILDCARE` at 50 percent — and then
        by a documentation factor."

        Design: Corner/calculations/claim_category_sublimit_caps_lost_wages_at_250000
        """
        ctx = setup_submitted_claim(
            expenses=[
                expense("LOST_WAGES", 200000, True),
                expense("LOST_WAGES", 200000, True),
            ],
            alert_overrides={"alert_type": "ACCOUNT_TAKEOVER", "severity": "MEDIUM",
                             "source_detail": "payroll redirected"},
        )
        assert ctx["claim"]["provisional_amount_cents"] == 247500

        approved = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adjuster-200"))
        )
        # 160000 + 160000 == 320000, capped at the 250000 sublimit, less the 2500 deductible.
        assert approved["approved_cents"] == 247500
        assert approved["status"] == "APPROVED"


class TestClaimCreationConcurrency:
    def test_creating_a_claim_on_a_stale_case_version_is_rejected(self, api):
        """PRD §2.6: "Opening an insurance claim requires the body to carry `expected_case_version`,
        holding the client's last observed `version` of the restoration case named by `case_id`. If
        that value does not equal the case's current `version`, the create is rejected with
        `ERR_STALE_CASE_VERSION` and HTTP 412."

        Design: Corner/cross_cutting/occ_stale_case_version_on_claim_create
        """
        ctx = setup_resolved_case(alert_overrides=SSN_ALERT)
        subscriber_id = ctx["subscriber"]["id"]
        sub_headers = make_subscriber_headers(subscriber_id)
        stale_version = get_case(ctx["case"]["id"])["version"]

        first = validate_success(
            api.create_claim(
                create_claim_payload(
                    ctx["case"]["id"],
                    stale_version,
                    [expense("LEGAL_FEES", 50000, True)],
                ),
                sub_headers,
            ),
            201,
        )

        resp = api.create_claim(
            create_claim_payload(
                ctx["case"]["id"], stale_version, [expense("NOTARY", 8000, True)]
            ),
            sub_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

        claims, meta = validate_paginated(
            api.list_claims(sub_headers, params={"case_id": ctx["case"]["id"]})
        )
        assert meta["total_count"] == 1, "the second create never landed"
        assert claims[0]["id"] == first["id"]
        assert get_claim(first["id"])["status"] == "DRAFT", "nothing superseded it"

    def test_a_fresh_case_version_supersedes_the_existing_draft(self, api):
        """PRD §3.7: "A case holds at most one non-terminal claim, and the platform enforces that by
        supersession rather than refusal: creating a new claim on a case that already carries a
        `DRAFT` claim carries the older claim `DRAFT → SUPERSEDED` (a terminal state) and increments
        its `version` by one."
        PRD §3.7: "Creating the claim also increments the case's `version` by one — which is,
        incidentally, exactly why the `expected_case_version` guard matters."

        Design: Corner/cross_cutting/claim_create_supersedes_existing_draft_when_version_is_fresh
        """
        ctx = setup_resolved_case(alert_overrides=SSN_ALERT)
        subscriber_id = ctx["subscriber"]["id"]
        sub_headers = make_subscriber_headers(subscriber_id)

        first = create_claim(
            ctx["case"]["id"], subscriber_id, [expense("LEGAL_FEES", 50000, True)]
        )
        refreshed_version = get_case(ctx["case"]["id"])["version"]

        second = validate_success(
            api.create_claim(
                create_claim_payload(
                    ctx["case"]["id"],
                    refreshed_version,
                    [expense("LEGAL_FEES", 70000, True)],
                ),
                sub_headers,
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert get_claim(first["id"])["status"] == "SUPERSEDED"

        claims, meta = validate_paginated(
            api.list_claims(sub_headers, params={"case_id": ctx["case"]["id"]})
        )
        assert meta["total_count"] == 2
        drafts = [c for c in claims if c["status"] == "DRAFT"]
        assert len(drafts) == 1, "a case holds at most one non-terminal claim"
        assert drafts[0]["id"] == second["id"]

    def test_submitting_an_unknown_claim_is_not_found(self, api, subscriber_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/errors/claim_submit_on_unknown_claim_not_found
        """
        resp = api.submit_claim("33333333-4444-4555-8666-777777777777", subscriber_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)


class TestSubmitRequiresResolvedCase:
    """A claim may only be submitted once its restoration case has reached RESOLVED."""

    def test_submitting_against_an_in_progress_case_is_rejected(self, api):
        """PRD §3.7: "Four conditions must hold, and their order determines the error the subscriber
        sees: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the referenced case must be
        `RESOLVED` (else `ERR_CASE_NOT_RESOLVED`); the subscriber's enrollment must be `ACTIVE`
        (else `ERR_ENROLLMENT_NOT_ACTIVE`); the subscriber's `insurance_status` must be `AVAILABLE`
        (else `ERR_INSURANCE_EXHAUSTED`); and the subscriber's `underwriting_risk_score` must be at
        most 75 — a score of exactly 75 passes, 76 does not (else
        `ERR_UNDERWRITING_RISK_TOO_HIGH`)."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_case_resolved
        """
        ctx = setup_in_progress_case(alert_overrides=SSN_ALERT)
        subscriber_id = ctx["subscriber"]["id"]
        assert get_case(ctx["case"]["id"])["status"] == "IN_PROGRESS"

        claim = create_claim(
            ctx["case"]["id"], subscriber_id, [expense("LEGAL_FEES", 50000, True)]
        )

        resp = api.submit_claim(claim["id"], make_subscriber_headers(subscriber_id))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_RESOLVED)

    def test_the_rejection_is_purely_about_the_case_and_leaves_the_claim_draft(self, api):
        """PRD §3.7: "Once a restoration case is `RESOLVED`, the subscriber may seek reimbursement
        for what the recovery cost them."
        PRD §2.5: "9. Cross-entity state — a claim being submitted must reference a restoration case
        that has reached `RESOLVED`, rejecting with `ERR_CASE_NOT_RESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_case_resolved
        """
        ctx = setup_in_progress_case(alert_overrides=SSN_ALERT)
        subscriber_id = ctx["subscriber"]["id"]
        claim = create_claim(
            ctx["case"]["id"], subscriber_id, [expense("LEGAL_FEES", 50000, True)]
        )

        subscriber = get_subscriber(subscriber_id)
        assert subscriber["enrollment_status"] == "ACTIVE"
        assert subscriber["insurance_status"] == "AVAILABLE", "the fiscal gate is clear"
        assert subscriber["underwriting_risk_score"] == 35, "the underwriting gate is clear"

        validate_error(
            api.submit_claim(claim["id"], make_subscriber_headers(subscriber_id)),
            ApiErrorId.ERR_CASE_NOT_RESOLVED,
        )

        after = get_claim(claim["id"])
        assert after["status"] == "DRAFT"
        assert after["provisional_amount_cents"] is None