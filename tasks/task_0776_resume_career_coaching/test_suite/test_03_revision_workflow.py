"""The revision loop: DRAFTED<->IN_REVISION cycling, overage billing, the credit
boundary, credit-restoring withdrawal, and the guards on withdraw/approve."""
from test_helpers import (
    validate_success,
    validate_paginated,
    validate_error,
    ApiErrorId,
    setup_confirmed_order,
    setup_drafted_deliverable,
    first_deliverable_id,
    open_revision,
    draft,
    find_addon_by_source_ref,
    find_payment,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRevisionCycle:
    PLAN = {"tier": "PRO", "base_price_cents": 30000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 2, "included_coaching_sessions": 0, "guarantee_type": "NONE"}

    def test_deliverable_loops_drafted_to_in_revision_and_back(self, api):
        """PRD §3.4: "From DRAFTED, the owning client may open a revision round, moving
        the deliverable from DRAFTED to IN_REVISION." Then re-drafting "transitions it
        back from IN_REVISION to DRAFTED" — a genuine loop.

        Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        deliv_id = ctx["deliverable_id"]
        open_revision(deliv_id, ctx["client_headers"], reason="revise")
        after_rev = validate_success(api.get_deliverable(deliv_id, ADMIN))
        assert after_rev["status"] == "IN_REVISION"
        draft(deliv_id, ctx["coach_headers"])
        after_redraft = validate_success(api.get_deliverable(deliv_id, ADMIN))
        assert after_redraft["status"] == "DRAFTED"

    def test_redraft_addresses_open_revision_and_bumps_counts(self, api):
        """PRD §3.4: "uploading a draft on an IN_REVISION deliverable transitions it back
        from IN_REVISION to DRAFTED, increments draft_count by one, and moves the open
        revision request with the highest round_no from OPEN to ADDRESSED."

        Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        deliv_id = ctx["deliverable_id"]
        rev = open_revision(deliv_id, ctx["client_headers"], reason="revise")
        draft(deliv_id, ctx["coach_headers"])
        deliverable = validate_success(api.get_deliverable(deliv_id, ADMIN))
        assert deliverable["revision_round_count"] == 1
        assert deliverable["draft_count"] == 2
        revisions, _ = validate_paginated(api.list_deliverable_revisions(deliv_id, ADMIN))
        matched = next(r for r in revisions if r["id"] == rev["id"])
        assert matched["status"] == "ADDRESSED"


class TestRevisionOverageCascade:
    PLAN = {"tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 0, "included_coaching_sessions": 0, "guarantee_type": "NONE"}

    def test_overage_revision_marks_billable_and_creates_addon(self, api):
        """PRD §3.4: "otherwise the round is an overage, `billable` is true, and the system
        auto-creates an `EXTRA_REVISION` add-on priced at 4000 cents with `auto_generated`
        true and `source_ref` set to the revision request's `id`".

        Design: Difficulty/transitive_cascade/revision_overage_cascade_depth3
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        rev = open_revision(ctx["deliverable_id"], ctx["client_headers"], reason="overage revision")
        assert rev["billable"] is True
        deliverable = validate_success(api.get_deliverable(ctx["deliverable_id"], ADMIN))
        assert deliverable["status"] == "IN_REVISION"
        addons, _ = validate_paginated(api.list_order_addons(ctx["order_id"], ADMIN))
        addon = find_addon_by_source_ref(addons, rev["id"])
        assert addon is not None, "an auto EXTRA_REVISION add-on must reference the revision"
        assert addon["type"] == "EXTRA_REVISION"
        assert addon["price_cents"] == 4000
        assert addon["auto_generated"] is True

    def test_overage_revision_posts_charge_payment(self, api):
        """PRD §3.6: auto-generated add-ons "follow the same PENDING to CHARGED charge on
        creation, but with the overage reasons REVISION_OVERAGE or SESSION_OVERAGE".
        PRD §2.6: "whenever a CHARGE entry is written, the order's amount_charged_cents
        increases by that entry's amount".

        Design: Difficulty/transitive_cascade/revision_overage_cascade_depth3
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        open_revision(ctx["deliverable_id"], ctx["client_headers"], reason="overage revision")
        order = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert order["amount_charged_cents"] == 24000, (
            f"base 20000 + overage 4000, got {order['amount_charged_cents']}"
        )
        payments, _ = validate_paginated(api.list_order_payments(ctx["order_id"], ADMIN))
        assert find_payment(payments, "CHARGE", "REVISION_OVERAGE", 4000) is not None


class TestRevisionCreditBoundary:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}

    def test_first_round_free_second_round_billable(self, api):
        """PRD §3.4: "if revision_credits_used is still below that pool the round is free
        and its billable flag is false; otherwise the round is an overage, billable is
        true". With one included round, round 1 (used 0 < 1) is free and round 2
        (used 1 >= 1) is billable.

        Design: Difficulty/boundary_precision_check/revision_overage_credit_boundary
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        deliv_id = ctx["deliverable_id"]
        rev1 = open_revision(deliv_id, ctx["client_headers"], reason="round 1 free")
        draft(deliv_id, ctx["coach_headers"])
        rev2 = open_revision(deliv_id, ctx["client_headers"], reason="round 2 overage")
        assert rev1["billable"] is False
        assert rev2["billable"] is True

    def test_second_round_consumes_credit_and_bills(self, api):
        """PRD §2.7: revision_credits_used "counts the currently active revision rounds
        and starts at zero." Opening two rounds drives revision_credits_used to 2, and the
        billable second round creates its EXTRA_REVISION add-on.

        Design: Difficulty/boundary_precision_check/revision_overage_credit_boundary
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        deliv_id = ctx["deliverable_id"]
        open_revision(deliv_id, ctx["client_headers"], reason="round 1 free")
        draft(deliv_id, ctx["coach_headers"])
        rev2 = open_revision(deliv_id, ctx["client_headers"], reason="round 2 overage")
        order = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert order["revision_credits_used"] == 2
        addons, _ = validate_paginated(api.list_order_addons(ctx["order_id"], ADMIN))
        addon = find_addon_by_source_ref(addons, rev2["id"])
        assert addon is not None and addon["type"] == "EXTRA_REVISION"


class TestWithdrawCreditConservation:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}

    def test_withdraw_restores_consumed_credit(self, api):
        """PRD §2.7: "The order's revision_credits_remaining is the larger of zero and the
        quantity revision_credits_included plus revision_credits_purchased minus
        revision_credits_used." Opening a free round spends the one credit (remaining 0),
        and withdrawing restores it (remaining 1).

        Design: Difficulty/compensating_invariant/revision_withdraw_credit_conservation
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        rev = open_revision(ctx["deliverable_id"], ctx["client_headers"], reason="free round")
        before = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert before["revision_credits_used"] == 1
        assert before["revision_credits_remaining"] == 0
        validate_success(api.withdraw_revision(rev["id"], ctx["client_headers"]))
        after = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert after["revision_credits_used"] == 0
        assert after["revision_credits_remaining"] == 1

    def test_withdraw_returns_request_and_deliverable_to_prior_state(self, api):
        """PRD §3.4: withdrawing "moves the deliverable from IN_REVISION back to DRAFTED,
        sets the revision request from OPEN to WITHDRAWN, decrements the deliverable's
        revision_round_count by one, and restores the consumed credit by decrementing the
        order's revision_credits_used by one."

        Design: Difficulty/compensating_invariant/revision_withdraw_credit_conservation
        """
        ctx = setup_drafted_deliverable(plan_overrides=self.PLAN)
        rev = open_revision(ctx["deliverable_id"], ctx["client_headers"], reason="free round")
        withdrawn = validate_success(api.withdraw_revision(rev["id"], ctx["client_headers"]))
        assert withdrawn["status"] == "WITHDRAWN"
        deliverable = validate_success(api.get_deliverable(ctx["deliverable_id"], ADMIN))
        assert deliverable["status"] == "DRAFTED"


def test_withdraw_billable_revision_rejected(api):
    """PRD §3.4: "A withdraw attempted on a revision that is not OPEN, or on one that is
    billable, is rejected with ERR_REVISION_NOT_WITHDRAWABLE (HTTP 409)."

    Design: Corner/endpoints/withdraw_billable_revision_rejected
    """
    ctx = setup_drafted_deliverable(plan_overrides={
        "tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 0, "included_coaching_sessions": 0, "guarantee_type": "NONE"})
    rev = open_revision(ctx["deliverable_id"], ctx["client_headers"], reason="billable round")
    assert rev["billable"] is True
    resp = api.withdraw_revision(rev["id"], ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_REVISION_NOT_WITHDRAWABLE.value)


def test_approve_pending_deliverable_returns_not_drafted(api):
    """PRD §3.4: "Approving a deliverable that is not `DRAFTED` is rejected with
    `ERR_DELIVERABLE_NOT_DRAFTED`."

    Design: Corner/state_machines/approve_pending_deliverable_returns_not_drafted
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"})
    deliv_id = first_deliverable_id(ctx["order_id"])
    resp = api.approve_deliverable(deliv_id, ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_DELIVERABLE_NOT_DRAFTED.value)
