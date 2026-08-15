"""Expenditure charging, allowable-cost review, ledger aggregation, and SNS
documentation (PRD §3.5, §3.7)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    allow_expenditure,
    api_client,
    build_user_headers,
    charge_expenditure,
    create_expenditure_payload,
    create_sns,
    create_sns_payload,
    disallow_expenditure,
    get_grant,
    reclassify_expenditure,
    review_sns,
    setup_allocated,
    setup_certified_allocation,
    submit_sns,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")


class TestChargeTargeting:

    def test_existence_beats_state_and_fiscal_priority(self):
        """PRD §2.8: "Third, existence: every resource id appearing in the
        path and every foreign-key id in the body must resolve, validated left
        to right — path parameters first, then body fields in their declared
        order — with the first miss rejected as `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.8: "Because the tiers run in this sequence, a request that
        fails several of them surfaces the earliest failure — a malformed body
        reports `ERR_INVALID_REQUEST`, never a masked state-machine error from
        a later tier."

        Design: Corner/validations/existence_beats_state_and_fiscal_priority
        """
        ctx = setup_allocated(2062, [(100, 100)])
        grant = ctx["grant"]
        # The body's allocation id does not exist; the same request would
        # also fail the supplant gate (supplant_screen true, no SNS document)
        # and the balance check (99,000,000 exceeds every balance) — the
        # existence tier surfaces first.
        resp = api_client.create_expenditure(
            create_expenditure_payload(
                grant["id"], 99_000_000,
                incurred_date="2061-09-01",
                school_allocation_id=NON_EXISTENT_UUID,
                supplant_screen=True,
                description="charge against a nonexistent allocation"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_charge_target_ambiguous_rejected(self):
        """PRD §3.7: "The charge target is exactly one of
        `school_allocation_id` or `set_aside_id`: naming both or neither is
        rejected with `ERR_CHARGE_TARGET_AMBIGUOUS`, and the named target must
        belong to the same grant as `grant_id` — a target foreign to the grant
        is treated as unresolvable within the request and rejected with
        `ERR_NOT_FOUND`."

        Design: Corner/validations/charge_target_ambiguous_rejected
        """
        ctx = setup_certified_allocation(2063, [(100, 100)])
        grant = ctx["grant"]
        allocation = ctx["allocation"]
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        both = api_client.create_expenditure(
            create_expenditure_payload(
                grant["id"], 1000, incurred_date="2062-09-01",
                school_allocation_id=allocation["id"],
                set_aside_id=pd["id"], description="both targets named"),
            ANALYST,
        )
        validate_error(both, ApiErrorId.ERR_CHARGE_TARGET_AMBIGUOUS)
        neither = api_client.create_expenditure(
            create_expenditure_payload(
                grant["id"], 1000, incurred_date="2062-09-01",
                description="no target named"),
            ANALYST,
        )
        validate_error(neither, ApiErrorId.ERR_CHARGE_TARGET_AMBIGUOUS)

    def test_function_target_mismatch_rejected(self):
        """PRD §3.7: "The function code must agree with the target: a charge
        against a school allocation must use `INSTRUCTION`, and a charge
        against a set-aside must use the code matching its category — `PD` for
        `PROFESSIONAL_DEVELOPMENT`, `PARENT_ENGAGEMENT` for
        `PARENT_ENGAGEMENT`, `HOMELESS_SUPPORT` for `HOMELESS_SERVICES`, and
        `EQUITABLE_SERVICES` for `EQUITABLE_SERVICES` — with any mismatch
        rejected as `ERR_FUNCTION_TARGET_MISMATCH`."

        Design: Corner/validations/function_target_mismatch_rejected
        """
        ctx = setup_certified_allocation(2064, [(100, 100)])
        grant = ctx["grant"]
        allocation = ctx["allocation"]
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        wrong_for_school = api_client.create_expenditure(
            create_expenditure_payload(
                grant["id"], 1000, incurred_date="2063-09-01",
                function_code="PD", school_allocation_id=allocation["id"],
                description="wrong function for school target"),
            ANALYST,
        )
        validate_error(wrong_for_school, ApiErrorId.ERR_FUNCTION_TARGET_MISMATCH)
        wrong_for_set_aside = api_client.create_expenditure(
            create_expenditure_payload(
                grant["id"], 1000, incurred_date="2063-09-01",
                function_code="INSTRUCTION", set_aside_id=pd["id"],
                description="wrong function for set-aside target"),
            ANALYST,
        )
        validate_error(wrong_for_set_aside,
                       ApiErrorId.ERR_FUNCTION_TARGET_MISMATCH)

    def test_cost_outside_fiscal_period_rejected(self):
        """PRD §3.7: "An `incurred_date` outside the grant's funds period
        (§3.1) is rejected with `ERR_COST_OUTSIDE_FISCAL_PERIOD`."
        PRD §3.1: "The grant's funds period — the window in which costs may be
        incurred — runs from July 1 of the calendar year preceding
        `fiscal_year` through June 30 of `fiscal_year`."

        Design: Corner/errors/cost_outside_fiscal_period_rejected
        """
        # FY2087 funds period runs 2086-07-01 through 2087-06-30.
        ctx = setup_certified_allocation(2087, [(100, 100)])
        resp = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 1000, incurred_date="2087-08-01",
                school_allocation_id=ctx["allocation"]["id"],
                description="late cost"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_COST_OUTSIDE_FISCAL_PERIOD)

    def test_insufficient_balance_pure_rejected(self):
        """PRD §3.7: "First, the amount must fit the target's remaining
        balance — for an allocation, its `allocation_amount_cents` minus its
        `liquidated_cents` minus its `pending_cents`; for a set-aside, its
        `reserved_cents` minus its `liquidated_cents` minus its own pending
        charges — or the charge is rejected with
        `ERR_INSUFFICIENT_ALLOCATION_BALANCE` (HTTP 402)."

        Design: Corner/errors/insufficient_balance_pure_rejected
        """
        # One school at 100/100 on a 10,000,000 grant: the waterfall fills
        # the allocation to exactly the 9,000,000 school pool.
        ctx = setup_certified_allocation(2084, [(100, 100)])
        allocation = ctx["allocation"]
        assert allocation["allocation_amount_cents"] == 9_000_000
        over = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 9_000_001, incurred_date="2083-09-01",
                school_allocation_id=allocation["id"],
                description="one cent over"),
            ANALYST,
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION_BALANCE)
        exact = validate_success(api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 9_000_000, incurred_date="2083-09-01",
                school_allocation_id=allocation["id"],
                description="exact balance"),
            ANALYST), expected_status=201)
        assert exact["status"] == "PENDING_REVIEW", \
            "the boundary is inclusive: the exact remaining balance fits"


class TestExpenditureReview:

    def test_expenditure_review_twice_returns_not_reviewable(self):
        """PRD §3.7: "A review requires the expenditure to be in
        `PENDING_REVIEW` (else `ERR_EXPENDITURE_NOT_REVIEWABLE`) and the grant
        to be `ALLOCATED` (else `ERR_GRANT_INVALID_STATE`)."
        PRD §3.7: "The grant's ledger is always a live aggregation —
        `liquidated_cents` is the sum of `amount_cents` over the grant's
        expenditures in `ALLOWED`, `pending_cents` the same sum over
        `PENDING_REVIEW`, and each allocation and set-aside carries the same
        two sums restricted to its own charges — recomputed eagerly inside
        every triggering request, never deferred to a batch."

        Design: Corner/state_machines/expenditure_review_twice_returns_not_reviewable
        """
        ctx = setup_certified_allocation(2055, [(100, 100)])
        exp = charge_expenditure(ctx["grant"], 1000,
                                 school_allocation_id=ctx["allocation"]["id"],
                                 description="supplies")
        allow_expenditure(exp["id"])
        resp = api_client.review_expenditure(
            exp["id"],
            {"decision": "DISALLOW", "disallow_reason": "UNALLOWABLE_COST",
             "review_note": "second review attempt"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_EXPENDITURE_NOT_REVIEWABLE)
        grant = get_grant(ctx["grant"]["id"])
        assert grant["liquidated_cents"] == 1000, \
            "no double count and no reversal from the rejected second review"
        assert grant["pending_cents"] == 0

    def test_reclassify_allowed_expenditure_rejected(self):
        """PRD §3.7: "The analyst may reclassify a `DISALLOWED` expenditure —
        the only state from which reclassification is permitted, else
        `ERR_EXPENDITURE_NOT_RECLASSIFIABLE` — by naming a
        `reclassified_to_fund_source` of `NON_TITLE_I_STATE` or
        `NON_TITLE_I_LOCAL`."

        Design: Corner/errors/reclassify_allowed_expenditure_rejected
        """
        ctx = setup_certified_allocation(2077, [(100, 100)])
        exp = charge_expenditure(ctx["grant"], 1000,
                                 school_allocation_id=ctx["allocation"]["id"],
                                 description="supplies")
        allow_expenditure(exp["id"])
        resp = api_client.reclassify_expenditure(
            exp["id"], {"reclassified_to_fund_source": "NON_TITLE_I_LOCAL"},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_EXPENDITURE_NOT_RECLASSIFIABLE)
        grant = get_grant(ctx["grant"]["id"])
        assert grant["liquidated_cents"] == 1000, "ledger untouched"

    def test_ledger_aggregation_excludes_reclassified(self):
        """PRD §3.7: "The grant's ledger is always a live aggregation —
        `liquidated_cents` is the sum of `amount_cents` over the grant's
        expenditures in `ALLOWED`, `pending_cents` the same sum over
        `PENDING_REVIEW`, and each allocation and set-aside carries the same
        two sums restricted to its own charges — recomputed eagerly inside
        every triggering request, never deferred to a batch."
        PRD §3.7: "The charge moves to the terminal `RECLASSIFIED` status as
        compensating bookkeeping; the grant's `liquidated_cents` is unchanged,
        because the charge was already excluded from the allowed totals at
        disallow time."

        Design: Corner/calculations/ledger_aggregation_excludes_reclassified
        """
        ctx = setup_certified_allocation(2060, [(100, 100)])
        allocation_id = ctx["allocation"]["id"]
        e1 = charge_expenditure(ctx["grant"], 2_000_000,
                                school_allocation_id=allocation_id,
                                description="teacher stipends")
        allow_expenditure(e1["id"])
        e2 = charge_expenditure(ctx["grant"], 1_000_000,
                                school_allocation_id=allocation_id,
                                description="questionable equipment")
        disallow_expenditure(e2["id"],
                             disallow_reason="INSUFFICIENT_DOCUMENTATION",
                             review_note="missing invoices")
        moved = reclassify_expenditure(e2["id"], "NON_TITLE_I_STATE")
        assert moved["status"] == "RECLASSIFIED"
        assert moved["reclassified_to_fund_source"] == "NON_TITLE_I_STATE"
        grant = get_grant(ctx["grant"]["id"])
        assert grant["liquidated_cents"] == 2_000_000, \
            "only ALLOWED expenditures feed liquidated_cents"
        assert grant["pending_cents"] == 0
        allocation = validate_success(
            api_client.get_allocation(allocation_id, DIRECTOR))
        assert allocation["liquidated_cents"] == 2_000_000, \
            "the reclassified charge is excluded from every Title I ledger"


class TestSupplementNotSupplantGate:

    def test_safety_vs_fiscal_on_expenditure_create(self):
        """PRD §2.8: "Seventh come the segregation-of-duties rules of §2.9,
        and eighth the supplement-not-supplant gate and the open-findings
        close-out block." and "Eleventh and last, the fiscal rules: set-aside
        floors, amendment net-zero and post-amendment floors, charge amounts
        against remaining balances, and the carryover and waiver conditions.
        Because the tiers run in this sequence, a request that fails several
        of them surfaces the earliest failure — a malformed body reports
        `ERR_INVALID_REQUEST`, never a masked state-machine error from a later
        tier."
        PRD §3.7: "Second, when the filer sets `supplant_screen` to true
        (default false), flagging that the cost could supplant state or local
        funds, the charged school allocation must have an `ACCEPTED` SNS
        document (§3.5); without one the charge is rejected with
        `ERR_SUPPLANT_RISK_UNRESOLVED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_expenditure_create
        """
        # Certified allocation with a 9,000,000 balance and no SNS document:
        # the charge violates the safety gate (tier 8) AND the balance rule
        # (tier 11) — the safety error must surface.
        ctx = setup_certified_allocation(2044, [(100, 100)])
        resp = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 99_000_000, incurred_date="2043-09-01",
                school_allocation_id=ctx["allocation"]["id"],
                supplant_screen=True,
                description="oversized supplanting charge"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLANT_RISK_UNRESOLVED)

    def test_supplant_gate_fires_without_balance_violation(self):
        """PRD §3.7: "Second, when the filer sets `supplant_screen` to true
        (default false), flagging that the cost could supplant state or local
        funds, the charged school allocation must have an `ACCEPTED` SNS
        document (§3.5); without one the charge is rejected with
        `ERR_SUPPLANT_RISK_UNRESOLVED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_expenditure_create
        """
        ctx = setup_certified_allocation(2042, [(100, 100)])
        resp = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 1000, incurred_date="2042-10-01",
                school_allocation_id=ctx["allocation"]["id"],
                supplant_screen=True, description="small supplanting charge"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLANT_RISK_UNRESOLVED)
        rows, meta = validate_paginated(api_client.list_expenditures(
            DIRECTOR, params={"grant_id": ctx["grant"]["id"]}))
        assert meta["total_count"] == 0, "no expenditure row may be created"

    def test_expenditure_gated_by_sns_acceptance(self):
        """PRD §3.7: "Second, when the filer sets `supplant_screen` to true
        (default false), flagging that the cost could supplant state or local
        funds, the charged school allocation must have an `ACCEPTED` SNS
        document (§3.5); without one the charge is rejected with
        `ERR_SUPPLANT_RISK_UNRESOLVED` (HTTP 403)."
        PRD §3.5: "A `decision` of `ACCEPT` moves the document to `ACCEPTED`,
        records `reviewed_by_user_id`, and recomputes the allocation's
        `supplement_ok` to true; a `decision` of `RETURN` moves it to
        `RETURNED` and requires a `review_note` explaining the rework
        (missing, the review is rejected with `ERR_INVALID_REQUEST`)."

        Design: Difficulty/cross_entity_state_dependency/expenditure_gated_by_sns_acceptance
        """
        ctx = setup_certified_allocation(2047, [(100, 100)])
        allocation_id = ctx["allocation"]["id"]
        doc = create_sns(allocation_id, methodology="GRADE_SPAN_GROUPING")
        submit_sns(doc["id"])  # SUBMITTED, not yet ACCEPTED
        before = validate_success(api_client.get_allocation(allocation_id,
                                                            DIRECTOR))
        assert before["supplement_ok"] is False
        blocked = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 1_000_000, incurred_date="2046-09-01",
                school_allocation_id=allocation_id, supplant_screen=True,
                description="reading specialist contract"),
            ANALYST,
        )
        validate_error(blocked, ApiErrorId.ERR_SUPPLANT_RISK_UNRESOLVED)
        review_sns(doc["id"], "ACCEPT")
        after = validate_success(api_client.get_allocation(allocation_id,
                                                           DIRECTOR))
        assert after["supplement_ok"] is True, \
            "supplement_ok flips false -> true across the ACCEPT"
        ok = validate_success(api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 1_000_000, incurred_date="2046-09-01",
                school_allocation_id=allocation_id, supplant_screen=True,
                description="reading specialist contract"),
            ANALYST), expected_status=201)
        assert ok["status"] == "PENDING_REVIEW"

    def test_returned_sns_does_not_satisfy_the_gate(self):
        """PRD §3.7: "Second, when the filer sets `supplant_screen` to true
        (default false), flagging that the cost could supplant state or local
        funds, the charged school allocation must have an `ACCEPTED` SNS
        document (§3.5); without one the charge is rejected with
        `ERR_SUPPLANT_RISK_UNRESOLVED` (HTTP 403)."
        PRD §3.5: "a `decision` of `RETURN` moves it to `RETURNED` and
        requires a `review_note` explaining the rework (missing, the review is
        rejected with `ERR_INVALID_REQUEST`)."

        Design: Difficulty/cross_entity_state_dependency/expenditure_gated_by_sns_acceptance
        """
        ctx = setup_certified_allocation(2041, [(100, 100)])
        allocation_id = ctx["allocation"]["id"]
        doc = create_sns(allocation_id)
        submit_sns(doc["id"])
        returned = review_sns(doc["id"], "RETURN",
                              review_note="methodology narrative incomplete")
        assert returned["status"] == "RETURNED"
        blocked = api_client.create_expenditure(
            create_expenditure_payload(
                ctx["grant"]["id"], 1_000_000, incurred_date="2040-10-01",
                school_allocation_id=allocation_id, supplant_screen=True,
                description="charge behind a RETURNED document"),
            ANALYST,
        )
        # RETURNED is not ACCEPTED, so the gate still blocks the charge.
        validate_error(blocked, ApiErrorId.ERR_SUPPLANT_RISK_UNRESOLVED)


class TestSnsDocumentation:

    def test_sns_window_half_open_overlap(self):
        """PRD §3.5: "Coverage windows on the same allocation must not overlap
        as half-open intervals: two windows that merely touch at an endpoint
        do not conflict, but any true intersection is rejected with
        `ERR_SNS_WINDOW_OVERLAP`. A new document starts in `DRAFT` with
        `attempt_count` at zero."

        Design: Difficulty/resource_temporal_overlap/sns_window_half_open_overlap
        """
        ctx = setup_certified_allocation(2049, [(100, 100)])
        allocation_id = ctx["allocation"]["id"]
        w1 = create_sns(allocation_id, methodology="PER_SCHOOL_DISTRIBUTION",
                        coverage_start_date="2026-07-01",
                        coverage_end_date="2027-01-01")
        assert w1["status"] == "DRAFT", "creation does not auto-submit"
        # Touching W1's exclusive end: half-open adjacency is not an overlap.
        w2 = validate_success(api_client.create_sns_document(
            create_sns_payload(allocation_id,
                               methodology="PER_SCHOOL_DISTRIBUTION",
                               coverage_start_date="2027-01-01",
                               coverage_end_date="2027-07-01"),
            ANALYST), expected_status=201)
        assert w2["status"] == "DRAFT"
        # A window sharing W1's interior is a true intersection.
        resp = api_client.create_sns_document(
            create_sns_payload(allocation_id,
                               coverage_start_date="2026-12-01",
                               coverage_end_date="2027-03-01"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SNS_WINDOW_OVERLAP)
        w1_after = validate_success(
            api_client.get_sns_document(w1["id"], DIRECTOR))
        assert w1_after["status"] == "DRAFT"

    def test_sns_window_adjacency_and_allocation_scoping(self):
        """PRD §3.5: "Coverage windows on the same allocation must not overlap
        as half-open intervals: two windows that merely touch at an endpoint
        do not conflict, but any true intersection is rejected with
        `ERR_SNS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/sns_window_half_open_overlap
        """
        ctx = setup_certified_allocation(2039, [(100, 100), (50, 100)])
        s1, s2 = ctx["schools"]
        a1 = ctx["allocations"][s1["id"]]
        a2 = ctx["allocations"][s2["id"]]
        w1 = create_sns(a1["id"], coverage_start_date="2026-07-01",
                        coverage_end_date="2027-01-01")
        # Touching W1's inclusive start from the left: also adjacency.
        w0 = validate_success(api_client.create_sns_document(
            create_sns_payload(a1["id"],
                               coverage_start_date="2026-01-01",
                               coverage_end_date="2026-07-01"),
            ANALYST), expected_status=201)
        assert w0["status"] == "DRAFT"
        # The rule scopes to "the same allocation": W1's exact window on a
        # different allocation does not intersect anything there.
        other = validate_success(api_client.create_sns_document(
            create_sns_payload(a2["id"],
                               coverage_start_date="2026-07-01",
                               coverage_end_date="2027-01-01"),
            ANALYST), expected_status=201)
        assert other["school_allocation_id"] == a2["id"]
        assert w1["id"] != other["id"]

    def test_sns_double_submit_rejected(self):
        """PRD §3.5: "Submission moves the document to `SUBMITTED` and is open
        to the analyst or the director. It is permitted from `DRAFT`, from
        `RETURNED` (the revision loop), and from `STALE` (the re-baseline loop
        after a recertification cascade); from any other state it is rejected
        with `ERR_SNS_NOT_SUBMITTABLE`."

        Design: Corner/errors/sns_double_submit_rejected
        """
        ctx = setup_certified_allocation(2094, [(100, 100)])
        doc = create_sns(ctx["allocation"]["id"])
        submit_sns(doc["id"])
        resp = api_client.submit_sns_document(doc["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_SNS_NOT_SUBMITTABLE)
        after = validate_success(api_client.get_sns_document(doc["id"],
                                                             DIRECTOR))
        assert after["attempt_count"] == 1, \
            "the rejected resubmission must not increment attempt_count"

    def test_sns_review_draft_rejected(self):
        """PRD §3.5: "Review belongs to the director alone, acting on a
        document in `SUBMITTED` (otherwise `ERR_SNS_NOT_REVIEWABLE`) and never
        on their own submission (§2.9)."

        Design: Corner/errors/sns_review_draft_rejected
        """
        ctx = setup_certified_allocation(2095, [(100, 100)])
        doc = create_sns(ctx["allocation"]["id"],
                         methodology="PER_SCHOOL_DISTRIBUTION")
        assert doc["status"] == "DRAFT"
        resp = api_client.review_sns_document(doc["id"],
                                              {"decision": "ACCEPT"},
                                              DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SNS_NOT_REVIEWABLE)
