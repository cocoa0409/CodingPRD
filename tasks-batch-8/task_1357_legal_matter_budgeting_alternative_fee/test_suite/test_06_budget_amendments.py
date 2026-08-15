"""Budget amendments: revision chains, authority, OCC, closed-period guard."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_approved_entry,
    advance_periods,
    api_client,
    approve_amendment,
    assert_budget_amendment,
    close_books,
    create_amendment,
    create_budget_amendment_payload,
    create_submitted_amendment,
    decide_amendment,
    get_matter,
    make_billing_partner_headers,
    make_pricing_analyst_headers,
    setup_active_matter,
    submit_amendment,
    validate_error,
    validate_success,
)


class TestAmendmentRevisionChain:

    def test_superseded_amendment_chain_completes(self):
        """PRD section 3.7: "The target phase's `current_budget_cents`
        increases by `delta_cents`, its `version_in_force` increments by
        one, and its status becomes `AMENDED` — or stays `AMENDED` when a
        subsequent amendment lands on an already-amended phase. If the
        amendment named a `supersedes_amendment_id`, the referenced
        amendment moves to `SUPERSEDED`."
        PRD section 3.7: "Rejection moves the amendment `PENDING_REVIEW` →
        `REJECTED` with no financial effect. `APPROVED` and `REJECTED` are
        the amendment's terminal states, with `SUPERSEDED` reachable when a
        later approved amendment re-papers it."

        Design: Difficulty/non_linear_state_machine/budget_amendment_revision_loop_cycle
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]

        amd1 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], phase["id"],
                                          20000, reason="scope grow")
        rejected = decide_amendment(ctx["firm"]["id"], amd1["id"],
                                    ctx["matter"]["id"], "REJECT",
                                    ctx["partner"]["id"])
        assert rejected["status"] == "REJECTED"

        amd2 = create_submitted_amendment(
            ctx["firm"]["id"], ctx["matter"]["id"], phase["id"], 15000,
            reason="revised scope", supersedes_amendment_id=amd1["id"])
        approved = approve_amendment(ctx["firm"]["id"], amd2["id"],
                                     ctx["matter"]["id"],
                                     ctx["partner"]["id"])
        assert_budget_amendment(approved)
        assert approved["status"] == "APPROVED"

        prior = validate_success(
            api_client.get_budget_amendment(amd1["id"], ADMIN), 200)
        assert prior["status"] == "SUPERSEDED", (
            f"an approved successor must push the referenced amendment to "
            f"SUPERSEDED, got {prior['status']}")

        phase_after = validate_success(
            api_client.get_phase_budget(phase["id"], ADMIN), 200)
        assert phase_after["current_budget_cents"] == 115000, (
            f"current budget must be 100000 + 15000 = 115000, got "
            f"{phase_after['current_budget_cents']}")
        assert phase_after["version_in_force"] == 2, (
            f"version_in_force must increment to 2 on the approved "
            f"amendment, got {phase_after['version_in_force']}")


class TestAmendmentGuards:

    def test_amendment_submit_blocked_in_closed_period(self):
        """PRD section 3.7: "Submission by the pricing analyst moves the
        amendment `DRAFT` → `PENDING_REVIEW` and re-checks a six-part
        battery in order: the target phase budget must be `ACTIVE` or
        `AMENDED`, else `ERR_PHASE_NOT_AMENDABLE`; the matter must be
        `ACTIVE` or `REOPENED`, else `ERR_MATTER_NOT_OPEN`; a set
        `supersedes_amendment_id` must still reference a `REJECTED` or
        `SUPERSEDED` amendment, else `ERR_AMENDMENT_SUPERSEDE_INVALID`;
        `delta_cents` must not be zero, else `ERR_INVALID_REQUEST`; the
        resulting `current_budget_cents` must remain non-negative, else
        `ERR_AMENDMENT_NEGATIVE_BUDGET`; and the matter's
        `last_activity_period_index` must be strictly later than the firm's
        `closed_through_period_index`, else `ERR_PERIOD_CLOSED` — a matter
        cannot be retroactively amended into a closed period."

        Design: Difficulty/resource_temporal_overlap/amendment_period_closed_overlap_guard
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]
        # Matter activity lands in period 0 (approve stamps
        # last_activity_period_index with the firm's current period).
        add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                           ctx["partner"]["id"], 50000, ctx["partner"]["id"])
        advance_periods(ctx["firm"]["id"], 1)
        close_books(ctx["firm"]["id"])

        amd = create_amendment(ctx["firm"]["id"], ctx["matter"]["id"],
                               phase["id"], 10000)
        resp = api_client.submit_budget_amendment(
            ctx["firm"]["id"], amd["id"], make_pricing_analyst_headers(
                "pa-submit"))
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED)

    def test_negative_budget_amendment_rejected_at_creation(self):
        """PRD section 3.7: "Two guards already apply at creation: if
        `supersedes_amendment_id` is set, the referenced amendment must be
        in `REJECTED` or `SUPERSEDED`, or creation fails with
        `ERR_AMENDMENT_SUPERSEDE_INVALID`; and the proposed delta must not
        drive the target phase's `current_budget_cents` below zero, or
        creation fails with `ERR_AMENDMENT_NEGATIVE_BUDGET` (HTTP 422)."

        Design: Corner/validations/amendment_negative_budget_rejected
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]

        resp = api_client.create_budget_amendment(
            ctx["firm"]["id"], ctx["matter"]["id"],
            create_budget_amendment_payload(phase["id"], -150000,
                                            scope_change_reason="too big"),
            make_pricing_analyst_headers("pa-create"))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NEGATIVE_BUDGET)

    def test_supersede_of_pending_amendment_rejected(self):
        """PRD section 3.7: "Two guards already apply at creation: if
        `supersedes_amendment_id` is set, the referenced amendment must be
        in `REJECTED` or `SUPERSEDED`, or creation fails with
        `ERR_AMENDMENT_SUPERSEDE_INVALID`; and the proposed delta must not
        drive the target phase's `current_budget_cents` below zero, or
        creation fails with `ERR_AMENDMENT_NEGATIVE_BUDGET` (HTTP 422)."

        Design: Corner/validations/amendment_supersede_invalid_when_target_pending
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]
        amd1 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], phase["id"],
                                          5000, reason="first")

        # amd1 is PENDING_REVIEW, not REJECTED or SUPERSEDED.
        resp = api_client.create_budget_amendment(
            ctx["firm"]["id"], ctx["matter"]["id"],
            create_budget_amendment_payload(
                phase["id"], 7000, scope_change_reason="second",
                supersedes_amendment_id=amd1["id"]),
            make_pricing_analyst_headers("pa-create"))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_SUPERSEDE_INVALID)

    def test_self_decision_fires_before_authority_check(self):
        """PRD section 3.7: "Segregation of duties comes first — the
        recorded `decided_by_user_id` must differ from
        `requested_by_user_id`, else the decision fails with
        `ERR_SEGREGATION_OF_DUTIES` — so a self-approval surfaces before any
        authority question is examined."

        Design: Difficulty/priority_pair_validation_conflict/segregation_vs_fiscal_priority_on_amendment_decide
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]
        # The requesting PricingAnalyst acts under the same user id as the
        # deciding BillingPartner, so requested_by == decided_by; the large
        # delta also puts the authority question in play, and segregation
        # must surface first regardless of the authority outcome.
        amd = create_amendment(ctx["firm"]["id"], ctx["matter"]["id"],
                               phase["id"], 5000000, reason="huge growth",
                               as_headers=make_pricing_analyst_headers(
                                   ctx["partner"]["id"]))
        submit_amendment(ctx["firm"]["id"], amd["id"],
                         as_headers=make_pricing_analyst_headers(
                             ctx["partner"]["id"]))

        resp = api_client.decide_budget_amendment(
            ctx["firm"]["id"], amd["id"],
            {"decision": "APPROVE",
             "expected_matter_version": get_matter(ctx["matter"]["id"])
             ["version"]},
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestAmendmentBudgetConsistency:

    def test_amendments_conserve_budget_total(self):
        """PRD section 3.5: "Its `budget_total_cents` is the sum of
        `current_budget_cents` over its phase budgets in `ACTIVE` or
        `AMENDED` status — draft and voided phases never count."
        PRD section 3.7: "The target phase's `current_budget_cents`
        increases by `delta_cents`, its `version_in_force` increments by
        one, and its status becomes `AMENDED` — or stays `AMENDED` when a
        subsequent amendment lands on an already-amended phase."

        Design: Difficulty/compensating_invariant/budget_amendment_invariant_conserves_budget_consistency
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000},
                    {"task_code": "L210", "budget": 50000}])
        pb1 = ctx["phases"]["L110"]
        pb2 = ctx["phases"]["L210"]

        amd1 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], pb1["id"],
                                          30000, reason="grow")
        approve_amendment(ctx["firm"]["id"], amd1["id"],
                          ctx["matter"]["id"], ctx["partner"]["id"])
        amd2 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], pb2["id"],
                                          -10000, reason="reduce")
        approve_amendment(ctx["firm"]["id"], amd2["id"],
                          ctx["matter"]["id"], ctx["partner"]["id"])

        pb1_after = validate_success(
            api_client.get_phase_budget(pb1["id"], ADMIN), 200)
        pb2_after = validate_success(
            api_client.get_phase_budget(pb2["id"], ADMIN), 200)
        assert pb1_after["current_budget_cents"] == 130000
        assert pb2_after["current_budget_cents"] == 40000

        matter = get_matter(ctx["matter"]["id"])
        assert matter["budget_total_cents"] == 170000, (
            f"budget total must be 130000 + 40000 = 170000 with no drift, "
            f"got {matter['budget_total_cents']}")
        assert matter["budget_total_cents"] == (
            pb1_after["current_budget_cents"]
            + pb2_after["current_budget_cents"]), (
            "budget_total_cents must equal the sum of current budgets over "
            "non-voided phases")

    def test_stale_matter_version_blocks_amendment_decision(self):
        """PRD section 2.7: "Deciding (approving or rejecting) a budget
        amendment likewise requires `expected_matter_version`."
        PRD section 2.7: "If the supplied value does not match the matter's
        current `version` — because another writer has advanced the matter's
        version since the client last read it, for instance by activating a
        competing arrangement or by having an amendment approved — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state
        change occurs."

        Design: Corner/errors/error_stale_version_on_amendment_decide
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]
        amd1 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], phase["id"],
                                          5000, reason="one")
        stale_version = get_matter(ctx["matter"]["id"])["version"]

        # A competing amendment decision advances the matter version.
        amd2 = create_submitted_amendment(ctx["firm"]["id"],
                                          ctx["matter"]["id"], phase["id"],
                                          7000, reason="two")
        approve_amendment(ctx["firm"]["id"], amd2["id"],
                          ctx["matter"]["id"], ctx["partner"]["id"])

        resp = api_client.decide_budget_amendment(
            ctx["firm"]["id"], amd1["id"],
            {"decision": "APPROVE",
             "expected_matter_version": stale_version},
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        unchanged = validate_success(
            api_client.get_budget_amendment(amd1["id"], ADMIN), 200)
        assert unchanged["status"] == "PENDING_REVIEW", (
            "no state change may occur on a stale-version rejection")
