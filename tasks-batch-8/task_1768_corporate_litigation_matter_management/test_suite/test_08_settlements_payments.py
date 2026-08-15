"""Settlement authority, negotiation cycle, execution cascade, and the payment rail."""
from test_helpers import (
    TIER2_EXPOSURE,
    TEST_USERS,
    add_hold,
    add_vendor,
    create_and_authorize_work_order,
    create_finance_approved_payment,
    create_payment_request_payload,
    create_settlement_under_review,
    create_tier2_policy,
    get_success_data,
    setup_active_matter,
    setup_resolved_judgment_matter,
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId, CustodianStatus, EngagementStatus, HoldStatus, MatterStatus,
    PaymentRail, PaymentStatus, SettlementStatus, WorkOrderStatus,
)

OPS = TEST_USERS["ops_headers"]


def _settlement_pending_with_discovery(api, amount=5_000_000):
    """ACTIVE TIER_2 matter + policy + ACKNOWLEDGED hold + AUTHORIZED work order
    (vendor committed 100 GB) + fully approved settlement + staged payment."""
    ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
    create_tier2_policy(ctx)
    hold, custodian = add_hold(ctx, acknowledge=True)
    vendor = add_vendor(ctx, capacity_gb=1000)
    wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                         estimated_gb=100)
    sr = create_settlement_under_review(ctx, proposed_amount_cents=amount)
    ctx["sr"] = validate_success(api.approve_settlement(sr["id"], ctx["gc"]))
    ctx["sr_id"] = ctx["sr"]["id"]
    create_finance_approved_payment(ctx, payment_kind="SETTLEMENT",
                                    amount_cents=amount,
                                    settlement_request_id=ctx["sr_id"])
    ctx.update(hold=hold, custodian=custodian, vendor=vendor, wo=wo)
    return ctx


class TestNegotiationCycle:
    def test_dual_approval_first_approval_self_loop(self, api):
        """PRD §3.8: "For a dual-approval amount the first approval leaves the request
        in `UNDER_REVIEW` — a self-loop at the API level — and only the second,
        higher-ranked approval completes it."
        PRD §3.8: "Approval then accumulates as described above: each successful
        approve appends the acting user's id to `approved_by_user_ids` and increments
        the request's `version`."

        Design: Difficulty/non_linear_state_machine/settlement_request_negotiation_cycle_resets_approvals
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)
        sr = create_settlement_under_review(ctx, proposed_amount_cents=12_000_000)
        after_first = validate_success(api.approve_settlement(sr["id"], ctx["gc"]))
        assert after_first["status"] == SettlementStatus.UNDER_REVIEW.value, \
            "first of two required approvals must not complete the approval"
        assert after_first["approved_by_user_ids"] == [ctx["gc_id"]]

    def test_counter_clears_approvals_and_accept_replaces_ask(self, api):
        """PRD §3.8: "A `DeputyGeneralCounsel` counters a request under review
        (`UNDER_REVIEW` → `COUNTERED`) with a `counter_amount_cents` that must be
        positive and different from the current ask, failing which the counter is
        rejected with `ERR_FIELD_CONSTRAINT`; countering sets `counter_amount_cents`
        and clears `approved_by_user_ids` back to empty — a new negotiation round
        resets prior partial approvals."
        PRD §3.8: "The requesting counsel, and only the requesting counsel, accepts
        the counter (`COUNTERED` → `UNDER_REVIEW`): the counter amount replaces
        `proposed_amount_cents` as the ask and the authority tier is re-snapshotted
        from the matter's current `exposure_tier`, re-pinning routing to the new
        amount."

        Design: Difficulty/non_linear_state_machine/settlement_request_negotiation_cycle_resets_approvals
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)
        sr = create_settlement_under_review(ctx, proposed_amount_cents=12_000_000)
        get_success_data(api.approve_settlement(sr["id"], ctx["gc"]))
        get_success_data(api.counter_settlement(sr["id"], 11_000_000, ctx["dgc"]))
        get_success_data(api.accept_counter_settlement(sr["id"], ctx["counsel"]))

        current = get_success_data(api.get_settlement_request(sr["id"], ctx["counsel"]))
        assert current["status"] == SettlementStatus.UNDER_REVIEW.value
        assert current["approved_by_user_ids"] == [], \
            "the counter must reset the recorded partial approvals"
        assert current["proposed_amount_cents"] == 11_000_000, \
            "accepting the counter replaces the ask with the counter amount"


class TestSettlementExecutionCascade:
    def test_execute_resolves_matter_and_releases_hold_hierarchy(self, api):
        """PRD §3.8: "Execution moves the request to `EXECUTED` and drives the matter
        from `SETTLEMENT_PENDING` to `RESOLVED` with `resolution_type` `SETTLEMENT`
        and the full resolution cascade of §3.9."
        PRD §3.9: "Second, every litigation hold in `DRAFT`, `ISSUED`, or
        `ACKNOWLEDGED` moves to `RELEASED` with `release_reason` `MATTER_RESOLVED`;
        because the work orders cancelled first, the release-time pin check is vacuous
        during this system-driven flow. Third, every custodian under those holds in
        `NOTICED`, `ACKNOWLEDGED`, or `ESCALATED` moves to `RELEASED`."

        Design: Difficulty/transitive_cascade/settlement_execute_cascade_matter_hold_custodian_workorder_vendor
        """
        ctx = _settlement_pending_with_discovery(api)
        executed = validate_success(api.execute_settlement(ctx["sr_id"], ctx["gc"]))
        assert executed["status"] == SettlementStatus.EXECUTED.value

        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["status"] == MatterStatus.RESOLVED.value
        assert matter["resolution_type"] == "SETTLEMENT"
        hold = get_success_data(api.get_hold(ctx["hold"]["id"], ctx["counsel"]))
        assert hold["status"] == HoldStatus.RELEASED.value
        assert hold["release_reason"] == "MATTER_RESOLVED"
        custodian = get_success_data(
            api.get_custodian(ctx["custodian"]["id"], ctx["counsel"]))
        assert custodian["status"] == CustodianStatus.RELEASED.value

    def test_execute_cancels_work_orders_and_releases_vendor_capacity(self, api):
        """PRD §3.9: "First, every work order of the matter in `DRAFT`, `AUTHORIZED`,
        or `IN_PROGRESS` moves to `CANCELLED`, each releasing its vendor-capacity
        debit and — by cancelling the orders that pinned them — unpinning the holds."
        PRD §3.8: "When the required count is reached the request becomes `APPROVED`
        and the linked matter auto-transitions from `ACTIVE` or `REOPENED` to
        `SETTLEMENT_PENDING`, suspending every `ACTIVE` engagement of the matter to
        `SUSPENDED` (each engagement's `version` increments) and recomputing posture
        and matter `version`."

        Design: Difficulty/transitive_cascade/settlement_execute_cascade_matter_hold_custodian_workorder_vendor
        """
        ctx = _settlement_pending_with_discovery(api)
        committed_pre = get_success_data(
            api.get_vendor(ctx["vendor"]["id"], OPS))["committed_gb"]
        assert committed_pre == 100
        engagement = get_success_data(
            api.get_engagement(ctx["engagement_id"], ctx["counsel"]))
        assert engagement["status"] == EngagementStatus.SUSPENDED.value, \
            "completing the settlement approval must suspend the matter's engagements"

        get_success_data(api.execute_settlement(ctx["sr_id"], ctx["gc"]))
        wo = get_success_data(api.get_work_order(ctx["wo"]["id"], OPS))
        assert wo["status"] == WorkOrderStatus.CANCELLED.value
        committed_post = get_success_data(
            api.get_vendor(ctx["vendor"]["id"], OPS))["committed_gb"]
        assert committed_post == 0, \
            "cancelling the work order must release its vendor-capacity debit"


class TestAuthorityAmountBoundary:
    def test_amount_at_single_ceiling_approves_with_one_approval(self, api):
        """PRD §3.8: "A request at or below the policy's single-approval ceiling needs
        exactly one approval, from the role the policy names; an amount exactly equal
        to the ceiling still needs only one."
        PRD §3.8: "When the required count is reached the request becomes `APPROVED`
        and the linked matter auto-transitions from `ACTIVE` or `REOPENED` to
        `SETTLEMENT_PENDING`"

        Design: Difficulty/boundary_precision_check/settlement_authority_single_vs_dual_boundary_exact_cent
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)  # ceiling 10,000,000
        sr = create_settlement_under_review(ctx, proposed_amount_cents=10_000_000)
        approved = validate_success(api.approve_settlement(sr["id"], ctx["gc"]))
        assert approved["status"] == SettlementStatus.APPROVED.value
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["status"] == MatterStatus.SETTLEMENT_PENDING.value

    def test_amount_one_cent_over_ceiling_engages_dual_path(self, api):
        """PRD §3.8: "One cent over the ceiling requires two approvals: the first from
        the policy-named role, the second from a role ranked strictly above the first
        approver's — and only when `dual_approval_required_over_cents` reaches the
        proposed amount"
        PRD §3.8: "For a dual-approval amount the first approval leaves the request in
        `UNDER_REVIEW` — a self-loop at the API level — and only the second,
        higher-ranked approval completes it."

        Design: Difficulty/boundary_precision_check/settlement_authority_single_vs_dual_boundary_exact_cent
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)  # ceiling 10,000,000; dual path up to 50,000,000
        sr = create_settlement_under_review(ctx, proposed_amount_cents=10_000_001)
        after_first = validate_success(api.approve_settlement(sr["id"], ctx["gc"]))
        assert after_first["status"] == SettlementStatus.UNDER_REVIEW.value, \
            "one cent over the ceiling must engage the dual-approval path"
        assert after_first["approved_by_user_ids"] == [ctx["gc_id"]]


class TestPaymentRailAndAccrual:
    def test_disburse_accrues_payment_to_matter(self, api):
        """PRD §3.8: "Disbursement requires the rail to still read `NOT_SENT`; it
        stamps `disbursed_at`, moves the rail to `SENT`, adds the amount to the
        matter's `accrued_to_date_cents` — payments count as accrued spend — and
        recomputes the reserve to burn it down."

        Design: Difficulty/compensating_invariant/payment_rail_disburse_return_accrual_conservation
        """
        ctx = setup_resolved_judgment_matter()
        payment = create_finance_approved_payment(ctx, amount_cents=7_000_000)
        before = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert before["accrued_to_date_cents"] == 0

        disbursed = validate_success(api.disburse_payment(payment["id"], ctx["fin"]))
        assert disbursed["status"] == PaymentStatus.DISBURSED.value
        assert disbursed["payment_status"] == PaymentRail.SENT.value
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["accrued_to_date_cents"] == 7_000_000

    def test_mark_returned_unwinds_accrued_spend(self, api):
        """PRD §3.8: "Finance then confirms receipt (`SENT` → `CONFIRMED`) or marks
        the payment returned (`SENT` → `RETURNED`), the latter subtracting the amount
        back out of the matter's accrued spend and recomputing the reserve"
        PRD §3.4: "A payment whose rail is `RETURNED` is excluded: returned money
        unwinds."

        Design: Difficulty/compensating_invariant/payment_rail_disburse_return_accrual_conservation
        """
        ctx = setup_resolved_judgment_matter()
        payment = create_finance_approved_payment(ctx, amount_cents=7_000_000)
        get_success_data(api.disburse_payment(payment["id"], ctx["fin"]))
        mid = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert mid["accrued_to_date_cents"] == 7_000_000

        returned = validate_success(api.mark_returned_payment(payment["id"], ctx["fin"]))
        assert returned["payment_status"] == PaymentRail.RETURNED.value
        after = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert after["accrued_to_date_cents"] == 0, \
            "disburse then mark-returned must conserve the ledger exactly"

    def test_payment_disburse_rail_gate_and_idempotent_terminal(self, api):
        """PRD §3.8: "The rail moves partly under system control and partly under
        Finance, and rail actions from the wrong rail state are rejected with
        `ERR_PAYMENT_RAIL_STATE`."
        PRD §2.11 lists "(5) whether the invoked transition exists from the target
        resource's current state (`ERR_INVALID_STATE`)" — a second disbursement from
        the terminal `DISBURSED` state is such an invalid-from transition.

        Design: Corner/state_machines/payment_disburse_rail_gate_and_idempotent_terminal
        """
        ctx = setup_resolved_judgment_matter()
        payment = create_finance_approved_payment(ctx, amount_cents=7_000_000)

        # Rail action (confirm-receipt) while the rail still reads NOT_SENT.
        early_confirm = api.confirm_receipt_payment(payment["id"], ctx["fin"])
        validate_error(early_confirm, ApiErrorId.ERR_PAYMENT_RAIL_STATE)

        get_success_data(api.disburse_payment(payment["id"], ctx["fin"]))
        # Second disbursement from the terminal DISBURSED approval state.
        double = api.disburse_payment(payment["id"], ctx["fin"])
        validate_error(double, ApiErrorId.ERR_INVALID_STATE)

        confirmed = validate_success(
            api.confirm_receipt_payment(payment["id"], ctx["fin"]))
        assert confirmed["payment_status"] == PaymentRail.CONFIRMED.value

    def test_settlement_payment_submit_requires_approved_settlement(self, api):
        """PRD §3.8: "Submission gates on the matter being in `SETTLEMENT_PENDING`,
        `RESOLVED`, `ACTIVE`, or `REOPENED`, and on the kind: a `SETTLEMENT` payment
        requires the linked settlement request to be `APPROVED` (else
        `ERR_REFERENCE_STATE_INVALID`) and its amount must equal the settlement's
        `proposed_amount_cents` exactly (else `ERR_FIELD_CONSTRAINT`)"

        Design: Corner/state_machines/settlement_payment_submit_requires_approved_settlement
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)
        sr = create_settlement_under_review(ctx, proposed_amount_cents=5_000_000)
        payment = validate_success(api.create_payment_request(
            ctx["matter_id"],
            create_payment_request_payload(
                payment_kind="SETTLEMENT", amount_cents=5_000_000,
                settlement_request_id=sr["id"]),
            ctx["counsel"]), 201)

        resp = api.submit_payment(payment["id"], ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_REFERENCE_STATE_INVALID)
        current = get_success_data(api.get_payment_request(payment["id"], ctx["fin"]))
        assert current["status"] == PaymentStatus.DRAFT.value

    def test_settlement_offer_expiry_sweep(self, api):
        """PRD §2.6: "Third, every SettlementRequest in `SUBMITTED`, `UNDER_REVIEW`,
        or `COUNTERED` whose `expires_at` is earlier than the new clock time
        transitions to `EXPIRED`."
        PRD §3.8: "Should the logical clock pass `expires_at` while the request sits
        in `SUBMITTED`, `UNDER_REVIEW`, or `COUNTERED`, the system sweeps it to
        `EXPIRED` and clears any recorded approvals."

        Design: Corner/cross_cutting_layers/settlement_offer_expiry_sweep
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)
        sr = create_settlement_under_review(ctx, proposed_amount_cents=5_000_000,
                                            expires_at="2026-08-10T00:00:00Z")
        get_success_data(api.set_clock("2026-08-11T00:00:00Z", OPS))
        current = get_success_data(api.get_settlement_request(sr["id"], ctx["counsel"]))
        assert current["status"] == SettlementStatus.EXPIRED.value

        resp = api.approve_settlement(sr["id"], ctx["gc"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
