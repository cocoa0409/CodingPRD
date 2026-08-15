"""Litigation holds and custodians: pins, self-acknowledgement, cooling periods,
and hold reference integrity."""
from test_helpers import (
    TEST_USERS,
    add_hold,
    add_vendor,
    create_active_engagement,
    create_approved_budget,
    create_and_authorize_work_order,
    create_deadline,
    create_matter,
    create_staff_user,
    create_work_order_payload,
    get_success_data,
    make_staff_headers,
    setup_active_matter,
    setup_staffing_matter,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId, CustodianStatus, HoldStatus

OPS = TEST_USERS["ops_headers"]


class TestHoldReleasePin:
    def test_hold_release_blocked_by_pinning_work_order(self, api):
        """PRD §3.5: "The pin rule guards the pin: while any work order referencing
        the hold is `AUTHORIZED` or `IN_PROGRESS`, release is rejected with
        `ERR_HOLD_COMPLIANCE_BLOCK` — active collection work pins the hold open."

        Design: Corner/state_machines/hold_release_blocked_by_pinning_work_order
        """
        ctx = setup_active_matter()
        hold, _custodian = add_hold(ctx, acknowledge=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                             estimated_gb=100)

        resp = api.release_hold(hold["id"], "SCOPE_NARROWED", ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_HOLD_COMPLIANCE_BLOCK)

        get_success_data(api.cancel_work_order(wo["id"], OPS))
        released = validate_success(
            api.release_hold(hold["id"], "SCOPE_NARROWED", ctx["counsel"]))
        assert released["status"] == HoldStatus.RELEASED.value
        assert released["release_reason"] == "SCOPE_NARROWED"


class TestCustodianSelfAcknowledgement:
    def test_custodian_acknowledge_by_non_custodian_rejected(self, api):
        """PRD §3.5: "A custodian acknowledges their own notice — acting under the
        `StaffUser` role with an `X-User-ID` equal to the custodian row's
        `staff_user_id`, failing which the call is rejected with
        `ERR_CUSTODIAN_SELF_ACK_REQUIRED` — from either `NOTICED` or `ESCALATED`,
        provided the parent hold is still in `DRAFT` or `ISSUED`."

        Design: Corner/state_machines/custodian_acknowledge_by_non_custodian_rejected
        """
        ctx = setup_staffing_matter()
        other = create_staff_user("Olivia Other", "olivia@corp.example", "LEGAL")
        hold, custodian = add_hold(ctx, issue=True)

        resp = api.acknowledge_custodian(custodian["id"],
                                         make_staff_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_CUSTODIAN_SELF_ACK_REQUIRED)
        current = get_success_data(api.get_custodian(custodian["id"], ctx["counsel"]))
        assert current["status"] == CustodianStatus.NOTICED.value


class TestCustodianEscalationCooling:
    def test_custodian_escalation_cooling_period(self, api):
        """PRD §3.5: "Escalation moves a `NOTICED` custodian to `ESCALATED` and
        increments `escalation_count`, but only while the parent hold is `ISSUED` and
        only once at least five full days have elapsed since `noticed_at` on the
        logical clock — an early escalation is rejected with `ERR_SCHEDULE_CONFLICT`."

        Design: Corner/cross_cutting_layers/custodian_escalation_cooling_period
        """
        ctx = setup_staffing_matter()
        hold, custodian = add_hold(ctx, issue=True)
        # Custodian noticed_at is the default clock instant 2026-08-01T00:00:00Z.

        early = api.escalate_custodian(custodian["id"], ctx["counsel"])
        validate_error(early, ApiErrorId.ERR_SCHEDULE_CONFLICT)

        get_success_data(api.set_clock("2026-08-07T00:00:00Z", OPS))
        escalated = validate_success(
            api.escalate_custodian(custodian["id"], ctx["counsel"]))
        assert escalated["status"] == CustodianStatus.ESCALATED.value
        assert escalated["escalation_count"] == 1


class TestCrossMatterHoldReference:
    def test_cross_matter_hold_reference_rejected(self, api):
        """PRD §2.10: "A work order's `hold_id` must name a hold belonging to the same
        matter; a payment's `settlement_request_id` must name a settlement of the same
        matter; a revised budget's `prior_version_id` must name a budget of the same
        matter; an engagement's `supersedes_engagement_id` must name an engagement of
        the same matter."
        PRD §3.6: "The referenced hold must belong to the same matter and be in
        `ISSUED` or `ACKNOWLEDGED`, enforced by `ERR_CROSS_REFERENCE_MISMATCH`."

        Design: Corner/validations/cross_matter_hold_reference_rejected
        """
        ctx = setup_active_matter()  # M1 ACTIVE with budget, engagement, firm
        hold, _custodian = add_hold(ctx, issue=True)  # ISSUED hold on M1
        vendor = add_vendor(ctx, capacity_gb=1000)

        # M2: a second fully active matter under the same staff and firm.
        m2 = create_matter(ctx["counsel_id"], title="M2")
        get_success_data(api.submit_assessment(m2["id"], ctx["counsel"]))
        create_deadline(m2["id"], ctx["counsel_id"])
        get_success_data(api.advance_to_staffing(m2["id"], ctx["counsel"]))
        create_approved_budget(m2["id"], ctx["counsel_id"], ctx["fin_id"])
        create_active_engagement(m2["id"], ctx["firm_id"],
                                 ctx["counsel_id"], ctx["dgc_id"])
        get_success_data(api.activate_matter(m2["id"], ctx["counsel"]))

        resp = api.create_work_order(
            m2["id"],
            create_work_order_payload(vendor_id=vendor["id"], hold_id=hold["id"],
                                      estimated_gb=50),
            OPS)
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)
