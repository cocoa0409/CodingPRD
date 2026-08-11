"""SOW milestones: engagement-type gate, delivery state gate, the parallel
acceptance/payment dimensions, and the budget-audit cascade on acceptance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_engagement_in_open,
    create_milestone_payload,
    find_open_invoice_id,
    get_engagement,
    get_milestone,
    get_success_data,
    get_supplier,
    make_finance_analyst_headers,
    make_supplier_coordinator_headers,
    setup_sow_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_analyst_headers"]
FIN_1 = make_finance_analyst_headers("fin-1")
FIN_2 = make_finance_analyst_headers("fin-2")


def test_milestone_create_on_requisition_rejected(api):
    """PRD: "Milestones exist only under `SOW` engagements and are created by
    a `HiringManager` while the engagement is `OPEN`, `FILLING` or `ACTIVE`;
    attempting to create one under a `REQUISITION` engagement is rejected
    with `ERR_ENGAGEMENT_TYPE_MISMATCH`."

    Design: Corner/state_machines/milestone_create_on_requisition_rejected
    """
    engagement = create_engagement_in_open(title="Req")
    resp = api.create_milestone(
        engagement["id"],
        create_milestone_payload(name="Bad", amount_cents=100_000,
                                 due_date="2026-06-30"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_TYPE_MISMATCH)
    _, meta = validate_paginated(api.list_milestones(engagement["id"], ADMIN))
    assert meta["total_count"] == 0, "no milestone persisted"


class TestMilestoneDeliverRequiresEngagementActive:
    def _setup_closed_sow_with_pending_milestone(self, api):
        sow = setup_sow_engagement(
            supplier_name="Lambda Works", supplier_code="SUP-L1",
            budget_cents=5_000_000,
        )
        milestone = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M", amount_cents=1_000_000,
                                         due_date="2026-06-30"),
                HM,
            )
        )
        get_success_data(api.close_engagement(sow["engagement"]["id"], HM))
        return sow, milestone

    def test_deliver_into_closed_engagement_rejected(self, api):
        """PRD: "Delivery belongs to the awarded supplier: the caller's
        `X-User-ID` must equal the engagement's `awarded_supplier_id`, the
        engagement must be `ACTIVE` — delivery against a non-active
        engagement fails with `ERR_ENGAGEMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/milestone_deliver_requires_engagement_active
        """
        sow, milestone = self._setup_closed_sow_with_pending_milestone(api)
        assert get_engagement(sow["engagement"]["id"])["status"] == "CLOSED"
        resp = api.deliver_milestone(
            milestone["id"], {},
            make_supplier_coordinator_headers(sow["supplier"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE)
        # the caller IS the awarded supplier — only the engagement state gate fails

    def test_failed_deliver_leaves_milestone_pending(self, api):
        """PRD: "the engagement must be `ACTIVE` — delivery against a
        non-active engagement fails with `ERR_ENGAGEMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/milestone_deliver_requires_engagement_active
        """
        sow, milestone = self._setup_closed_sow_with_pending_milestone(api)
        validate_error(
            api.deliver_milestone(
                milestone["id"], {},
                make_supplier_coordinator_headers(sow["supplier"]["id"]),
            ),
            ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE,
        )
        after = get_milestone(milestone["id"])
        assert after["acceptance_status"] == "PENDING", "no partial mutation"
        assert after["delivered_by_supplier_id"] is None


class TestMilestoneParallelDimensions:
    def _setup_sow_with_milestone(self, api):
        sow = setup_sow_engagement(
            supplier_name="Delta Delivery", supplier_code="SUP-D1",
            budget_cents=10_000_000,
        )
        milestone = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M", amount_cents=1_000_000,
                                         due_date="2026-06-30"),
                HM,
            )
        )
        coordinator = make_supplier_coordinator_headers(sow["supplier"]["id"])
        return sow, milestone, coordinator

    def test_acceptance_does_not_advance_payment_dimension(self, api):
        """PRD: "The milestone's `payment_status` stays `UNINVOICED` through
        all of this — acceptance is not invoicing."
        PRD: "Delivery works from both `PENDING` and `REJECTED`; the
        redelivery loop stays open after rejection."

        Design: Difficulty/non_linear_state_machine/milestone_parallel_acceptance_payment_dimensions
        """
        sow, milestone, coordinator = self._setup_sow_with_milestone(api)
        delivered = get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
        assert delivered["acceptance_status"] == "DELIVERED"
        assert delivered["delivered_by_supplier_id"] == sow["supplier"]["id"]

        rejected = get_success_data(
            api.reject_milestone(milestone["id"], {"reason": "incomplete docs"}, HM)
        )
        assert rejected["acceptance_status"] == "REJECTED"
        assert rejected["rejection_reason"] == "incomplete docs"

        redelivered = get_success_data(
            api.deliver_milestone(milestone["id"], {"delivery_note": "v2 redelivery"},
                                  coordinator)
        )
        assert redelivered["acceptance_status"] == "DELIVERED", (
            "PENDING -> DELIVERED -> REJECTED -> DELIVERED redelivery loop"
        )
        assert redelivered["rejection_reason"] is None, (
            "redelivery clears the prior rejection_reason"
        )

        accepted = validate_success(api.accept_milestone(milestone["id"], HM))
        assert accepted["acceptance_status"] == "ACCEPTED"
        assert accepted["payment_status"] == "UNINVOICED", (
            "acceptance does not advance payment"
        )
        assert accepted["accepted_by_user_id"] == HM["X-User-ID"]

    def test_invoice_events_drive_payment_dimension_independently(self, api):
        """PRD: "the payment dimension, `payment_status`, runs `UNINVOICED` →
        `INVOICED` → `PAID` and is driven purely by invoice events (§3.8) —
        nothing in the acceptance flow touches it."
        PRD: "Finalization stamps `finalized_by_user_id` with the caller's
        `X-User-ID` and moves every milestone whose line is attached from
        `UNINVOICED` to `INVOICED` on the payment dimension."
        PRD: "A successful payment stamps `paid_by_user_id` and moves every
        attached milestone `INVOICED` → `PAID`."

        Design: Difficulty/non_linear_state_machine/milestone_parallel_acceptance_payment_dimensions
        """
        sow, milestone, coordinator = self._setup_sow_with_milestone(api)
        get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
        get_success_data(
            api.reject_milestone(milestone["id"], {"reason": "incomplete docs"}, HM)
        )
        get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
        accepted = get_success_data(api.accept_milestone(milestone["id"], HM))
        assert accepted["acceptance_status"] == "ACCEPTED"
        assert accepted["payment_status"] == "UNINVOICED"

        invoice_id = find_open_invoice_id(sow["supplier"]["id"])
        get_success_data(api.finalize_invoice(invoice_id, FIN_1))
        mid = get_milestone(milestone["id"])
        assert mid["payment_status"] == "INVOICED", "invoice event advanced payment"
        assert mid["acceptance_status"] == "ACCEPTED", (
            "invoice events do not touch acceptance"
        )

        get_success_data(api.mark_invoice_paid(invoice_id, FIN_2))
        end = get_milestone(milestone["id"])
        assert end["payment_status"] == "PAID"
        assert end["acceptance_status"] == "ACCEPTED"


class TestMilestoneAcceptBudgetAuditCascade:
    def _setup_delivered_95pct_milestone(self, api):
        sow = setup_sow_engagement(
            supplier_name="Epsilon Works", supplier_code="SUP-E1",
            budget_cents=10_000_000,
        )
        milestone = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M95", amount_cents=9_500_000,
                                         due_date="2026-06-30"),
                HM,
            )
        )
        coordinator = make_supplier_coordinator_headers(sow["supplier"]["id"])
        get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
        return sow, milestone

    def test_accept_crossing_95pct_raises_budget_audit(self, api):
        """PRD: "when the recomputed committed spend crosses the 95%
        budget-utilization threshold — from below 95% of `budget_cents` to at
        or above it — and `budget_audit_raised` is still false, a
        `BUDGET_UTILIZATION` compliance audit of severity `HIGH` is
        auto-created against the engagement and the flag is set true, so the
        audit is raised at most once per engagement."
        PRD: "Link 2: the engagement's `committed_spend_cents` is recomputed."

        Design: Difficulty/transitive_cascade/milestone_accept_budget_audit_supplier_counter
        """
        sow, milestone = self._setup_delivered_95pct_milestone(api)
        accepted = validate_success(api.accept_milestone(milestone["id"], HM))
        assert accepted["acceptance_status"] == "ACCEPTED"

        engagement = get_engagement(sow["engagement"]["id"])
        assert engagement["committed_spend_cents"] == 9_500_000, (
            "link 1: accept mutated the engagement aggregate"
        )
        assert engagement["budget_audit_raised"] is True
        audits, meta = validate_paginated(
            api.list_compliance_audits(
                ADMIN, params={"engagement_id": sow["engagement"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        audit = audits[0]
        assert audit["finding"] == "BUDGET_UTILIZATION"
        assert audit["severity"] == "HIGH"
        assert audit["status"] == "OPEN", (
            "the crossing to exactly 95.0% is at-or-above — the >= boundary fires"
        )

    def test_budget_audit_increments_supplier_violation_counter(self, api):
        """PRD: "Link 4: creating that audit increments the supplier's
        `open_violation_count` by one."
        PRD: "Engagement-level `BUDGET_UTILIZATION` findings raised by the
        approval cascades instead set the audit's `engagement_id`."

        Design: Difficulty/transitive_cascade/milestone_accept_budget_audit_supplier_counter
        """
        sow, milestone = self._setup_delivered_95pct_milestone(api)
        validate_success(api.accept_milestone(milestone["id"], HM))
        supplier = get_supplier(sow["supplier"]["id"])
        assert supplier["open_violation_count"] == 1, (
            "link 3: the audit's creation incremented the supplier counter"
        )
        audits, meta = validate_paginated(
            api.list_compliance_audits(
                ADMIN, params={"engagement_id": sow["engagement"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert audits[0]["supplier_id"] == sow["supplier"]["id"], (
            "derived via engagement.awarded_supplier_id"
        )
        assert audits[0]["engagement_id"] == sow["engagement"]["id"]
