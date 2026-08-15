"""Dispatch, SLA clock arithmetic, escalation, vendor status gating, and
capacity/fee invariants."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_order,
    create_candidate_payload,
    create_consent_payload,
    create_order_payload,
    create_report_payload,
    get_success_data,
    get_vendor_record,
    list_orders_filtered,
    make_candidate_headers,
    make_vendor_agent_headers,
    setup_consented_order,
    setup_dispatched_order,
    setup_screening_config,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestDispatchPreconditions:
    def test_dispatch_from_draft_rejected(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "The
        order's fulfillment must be `CONSENT_CAPTURED`, else
        `ERR_ORDER_NOT_CONSENT_CAPTURED`."

        Design: Corner/state_machines/dispatch_from_draft_rejected
        """
        ctx = setup_screening_config(tag="SM2", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Sm Two", email="sm2@x.com"), HR
            )
        )
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        resp = api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONSENT_CAPTURED)

        # A rejected dispatch consumes no capacity.
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 0


class TestVendorStatusGate:
    def test_dispatch_to_suspended_vendor_rejected(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "The body
        carries a `vendor_id` that must reference an existing vendor
        (`ERR_NOT_FOUND`) whose status is `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`)" and
        PRD section "Vendor Lifecycle": "Suspension blocks new dispatches to the
        vendor but does not cancel in-flight `DISPATCHED` orders"."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_vendor_status
        """
        ctx = setup_consented_order(
            tag="CE1", with_matrix=False, dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        validate_success(api.suspend_vendor(ctx["vendor"]["id"], CO))

        resp = api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)
        order_now = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order_now["fulfillment_status"] == "CONSENT_CAPTURED"

    def test_dispatch_succeeds_after_reinstate(self, api):
        """PRD section "Vendor Lifecycle": "Reinstatement returns a `SUSPENDED`
        or `PROBATION` vendor to `ACTIVE`" and PRD section "Dispatch, the SLA
        Clock, and Vendor Capacity": "increments the vendor's
        `active_order_count` by one. Fulfillment becomes `DISPATCHED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_vendor_status
        """
        ctx = setup_consented_order(
            tag="CE1B", with_matrix=False, dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        validate_success(api.suspend_vendor(ctx["vendor"]["id"], CO))
        resp = api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

        validate_success(api.reinstate_vendor(ctx["vendor"]["id"], CO))
        order = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert_order(order)
        assert order["fulfillment_status"] == "DISPATCHED"
        assert order["vendor_id"] == ctx["vendor"]["id"]
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["status"] == "ACTIVE"
        assert vendor["active_order_count"] == 1


class TestSlaDueArithmetic:
    def test_sla_due_skips_weekend_and_off_hours(self, api):
        """PRD section "The Logical Clock and Business-Time Arithmetic":
        "Deadline-projection questions ("when is this SLA due?") are answered by
        walking forward day by day from a starting instant, consuming
        business-window hours and skipping weekends and non-window hours, until
        the contracted number of business hours has elapsed"."

        Design: Corner/calculations/sla_due_skips_weekend_and_off_hours
        """
        # Friday 2026-08-07T16:00:00Z dispatch, tat 2 business hours:
        # 1h remains Friday (16:00-17:00), the 2nd hour lands Monday 09:00+1h.
        ctx = setup_consented_order(
            tag="CC1",
            with_matrix=False,
            package_overrides={"tat_business_hours": 2},
            consent_signed_at="2026-08-06T09:00:00Z",
            dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-07T16:00:00Z"))
        order = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert_instant_equals(
            order["dispatched_at"], "2026-08-07T16:00:00Z", "dispatched_at"
        )
        assert_instant_equals(
            order["sla_due_at"], "2026-08-10T10:00:00Z", "sla_due_at"
        )

    def test_clock_default_and_saturday_dispatch_anchor(self, api):
        """PRD section "The Logical Clock and Business-Time Arithmetic": "the
        startup default, before any such call, is exactly
        `2026-08-01T00:00:00Z`" and "a dispatch on a Saturday begins counting at
        09:00:00Z the following Monday."

        Design: Corner/calculations/clock_default_and_saturday_dispatch_anchor
        """
        # No set_clock call is ever made: the logical clock stays at the
        # startup default 2026-08-01T00:00:00Z, a Saturday.
        ctx = setup_consented_order(
            tag="CC2",
            with_matrix=False,
            package_overrides={"tat_business_hours": 8},
            consent_signed_at="2026-07-31T09:00:00Z",
            dispatch_at=None,
        )
        order = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert_instant_equals(
            order["dispatched_at"], "2026-08-01T00:00:00Z", "dispatched_at"
        )
        assert_instant_equals(
            order["sla_due_at"], "2026-08-03T17:00:00Z", "sla_due_at"
        )


class TestSlaBreachBoundary:
    def test_delivery_at_exact_due_instant_is_on_time(self, api):
        """PRD section "Report Delivery": "`sla_breached` is true exactly when
        the turnaround is strictly greater than the package's
        `tat_business_hours` — delivery at exactly the due boundary is on time."

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_than_tat
        """
        # tat 8 from Wed 2026-08-05T10:00:00Z: due Thu 2026-08-06T10:00:00Z.
        # An ACTIVE matrix must exist: PRD "Configuring the Screening Catalog"
        # — deliveries "fail for lack of an active matrix".
        ctx1 = setup_dispatched_order(
            tag="BP1A",
            package_overrides={"tat_business_hours": 8},
            candidate_email="bp1a@x.com",
            dispatch_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-06T10:00:00Z"))
        report1 = validate_success(
            api.create_report(
                create_report_payload(ctx1["order"]["id"], findings=[]),
                make_vendor_agent_headers(ctx1["vendor"]["id"]),
            ),
            expected_status=201,
        )
        assert report1["sla_breached"] is False

    def test_one_business_hour_late_breaches_and_moves_counter(self, api):
        """PRD section "Report Delivery": "`sla_breached` is true exactly when
        the turnaround is strictly greater than the package's
        `tat_business_hours`" and "A breached SLA increments
        `consecutive_sla_breaches`; an on-time delivery resets the counter to
        zero"."

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_than_tat
        """
        # Same vendor, two orders dispatched together at Wed 10:00 with tat 8.
        # An ACTIVE matrix must exist: report delivery requires one (PRD
        # "Configuring the Screening Catalog").
        ctx = setup_screening_config(
            tag="BP1B",
            package_overrides={"tat_business_hours": 8},
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        cand1 = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Bp One", email="bp1c@x.com"), HR
            )
        )
        cand2 = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Bp OneB", email="bp1d@x.com"), HR
            )
        )
        order1 = get_success_data(
            api.create_order(
                create_order_payload(cand1["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order1["id"], create_consent_payload(),
                make_candidate_headers(cand1["id"]),
            )
        )
        get_success_data(api.dispatch_order(order1["id"], ctx["vendor"]["id"], HM))
        order2 = get_success_data(
            api.create_order(
                create_order_payload(cand2["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order2["id"], create_consent_payload(),
                make_candidate_headers(cand2["id"]),
            )
        )
        get_success_data(api.dispatch_order(order2["id"], ctx["vendor"]["id"], HM))

        # Order 1 delivered exactly at the due instant: on time.
        get_success_data(api.set_clock("2026-08-06T10:00:00Z"))
        report1 = validate_success(
            api.create_report(
                create_report_payload(order1["id"], findings=[]),
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            ),
            expected_status=201,
        )
        assert report1["sla_breached"] is False

        # Order 2 delivered one business hour later: breach.
        get_success_data(api.set_clock("2026-08-06T11:00:00Z"))
        report2 = validate_success(
            api.create_report(
                create_report_payload(order2["id"], findings=[]),
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            ),
            expected_status=201,
        )
        assert report2["sla_breached"] is True

        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["consecutive_sla_breaches"] == 1


class TestEscalation:
    def test_escalate_requires_sla_breach_and_increments(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity":
        "Escalation requires the current logical time to be strictly later than
        `sla_due_at`; an attempt before or exactly at the due instant is
        rejected with `ERR_SLA_NOT_BREACHED`. Each successful escalation
        increments `escalation_level` by one."

        Design: Corner/validations/escalate_requires_sla_breach_and_increments
        """
        # Dispatch Monday 2026-08-03T09:00:00Z, tat 40 = 5 business days x 8h.
        ctx = setup_consented_order(
            tag="VL8",
            with_matrix=False,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-03T09:00:00Z"))
        order = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert_instant_equals(
            order["sla_due_at"], "2026-08-07T17:00:00Z", "sla_due_at"
        )

        # Before the due instant: rejected.
        resp = api.escalate_order(order["id"], HM)
        validate_error(resp, ApiErrorId.ERR_SLA_NOT_BREACHED)

        # After the due instant: each call adds exactly one level.
        get_success_data(api.set_clock("2026-08-10T09:00:00Z"))
        escalated = validate_success(api.escalate_order(order["id"], HM))
        assert escalated["escalation_level"] == 1


class TestCapacityAndFindingShape:
    def test_vendor_capacity_and_finding_check_type(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "whose
        `active_order_count` is strictly below its `max_concurrent_orders`
        (`ERR_VENDOR_CAPACITY_EXCEEDED`)" and PRD section "Report Delivery":
        "every finding's `check_type` must be a member of the pinned package's
        `check_types`, and any out-of-package finding rejects the whole
        submission with `ERR_FINDING_CHECK_TYPE_NOT_IN_PACKAGE` (HTTP 422)."

        Design: Corner/validations/vendor_capacity_and_finding_check_type
        """
        ctx = setup_screening_config(
            tag="VL9", vendor_overrides={"max_concurrent_orders": 1}
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        cand1 = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl NineA", email="vl9a@x.com"),
                HR,
            )
        )
        cand2 = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl NineB", email="vl9b@x.com"),
                HR,
            )
        )
        order1 = get_success_data(
            api.create_order(
                create_order_payload(cand1["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order1["id"], create_consent_payload(),
                make_candidate_headers(cand1["id"]),
            )
        )
        get_success_data(api.dispatch_order(order1["id"], ctx["vendor"]["id"], HM))
        order2 = get_success_data(
            api.create_order(
                create_order_payload(cand2["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order2["id"], create_consent_payload(),
                make_candidate_headers(cand2["id"]),
            )
        )

        # The vendor is at capacity (1 of 1): the second dispatch fails.
        resp1 = api.dispatch_order(order2["id"], ctx["vendor"]["id"], HM)
        validate_error(resp1, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

        # A finding whose check_type is outside the package fails at delivery.
        resp2 = api.create_report(
            create_report_payload(
                order1["id"],
                findings=[
                    {
                        "check_type": "CREDIT_CHECK",
                        "offense_category": "EMPLOYMENT_DISCREPANCY",
                        "severity": "LOW",
                        "offense_date": "2024-01-01T00:00:00Z",
                        "disposition": "PENDING",
                    }
                ],
            ),
            make_vendor_agent_headers(ctx["vendor"]["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_FINDING_CHECK_TYPE_NOT_IN_PACKAGE)


class TestCompensatingInvariants:
    def test_vendor_capacity_conserved_under_dispatch_cancel(self, api):
        """PRD section "Parallel State Dimensions and Hierarchical Cascades":
        "guaranteeing that the vendor's `active_order_count` invariant — at all
        times equal to the count of that vendor's orders with
        `fulfillment_status` `DISPATCHED` — holds after every mutation." and PRD
        section "Cancellation, Revocation, and Withdrawal Cascades": "If the
        order was `DISPATCHED`, the vendor's `active_order_count` decrements by
        one"."

        Design: Difficulty/compensating_invariant/vendor_capacity_conserved_under_dispatch_cancel
        """
        ctx = setup_consented_order(tag="CI1", with_matrix=False, dispatch_at=None)
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 0

        get_success_data(api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM))
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 1

        validate_success(api.cancel_order(ctx["order"]["id"], HM))
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 0

    def test_cancelled_order_terminal_states_after_capacity_release(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades": "In
        all cases, a non-terminal adverse-action case cascades to `ABORTED`, a
        `DECIDED` individualized assessment cascades to `VOID`, and the order's
        adjudication becomes `VOIDED` while fulfillment becomes `CANCELLED`."

        Design: Difficulty/compensating_invariant/vendor_capacity_conserved_under_dispatch_cancel
        """
        ctx = setup_dispatched_order(
            tag="CI1B", with_matrix=False, dispatch_at="2026-08-05T10:00:00Z"
        )
        cancelled = validate_success(api.cancel_order(ctx["order"]["id"], HM))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["adjudication_status"] == "VOIDED"
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 0

    def test_vendor_receivable_conserved_under_fee_void(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "freezes
        `provisional_fee_cents` as the package's `fee_cents` plus the vendor's
        `surcharge_cents`" and PRD section "Cancellation, Revocation, and
        Withdrawal Cascades": "If the order was `DISPATCHED`, the vendor's
        `active_order_count` decrements by one and `provisional_fee_cents` is
        voided to null."

        Design: Difficulty/compensating_invariant/vendor_receivable_conserved_under_fee_void
        """
        ctx = setup_consented_order(
            tag="CI2",
            with_matrix=False,
            vendor_overrides={"surcharge_cents": 1500},
            package_overrides={"fee_cents": 25000},
            dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        dispatched = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert dispatched["provisional_fee_cents"] == 26500

        validate_success(api.cancel_order(ctx["order"]["id"], HM))
        order_now = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order_now["provisional_fee_cents"] is None
        assert order_now["final_fee_cents"] is None

    def test_fee_void_leaves_vendor_receivable_at_zero(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades":
        "Cancellation is a compensated event. If the order was `DISPATCHED`, the
        vendor's `active_order_count` decrements by one and
        `provisional_fee_cents` is voided to null."

        Design: Difficulty/compensating_invariant/vendor_receivable_conserved_under_fee_void
        """
        ctx = setup_consented_order(
            tag="CI2B",
            with_matrix=False,
            vendor_overrides={"surcharge_cents": 1500},
            package_overrides={"fee_cents": 25000},
            dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        get_success_data(api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM))
        validate_success(api.cancel_order(ctx["order"]["id"], HM))

        orders, _meta = list_orders_filtered(HR, vendor_id=ctx["vendor"]["id"])
        assert len(orders) == 1
        receivable = sum(
            (o["final_fee_cents"] if o["final_fee_cents"] is not None else 0)
            + (o["provisional_fee_cents"] if o["provisional_fee_cents"] is not None else 0)
            for o in orders
        )
        assert receivable == 0


class TestImmediateConsistency:
    def test_immediate_visibility_of_mutation_in_response(self, api):
        """PRD section "Introduction": "Every mutation is atomically visible in
        the response that performs it." and PRD section "Dispatch, the SLA
        Clock, and Vendor Capacity": "A successful dispatch stamps
        `dispatched_at` with the current logical time, computes `sla_due_at` ...
        freezes `provisional_fee_cents` as the package's `fee_cents` plus the
        vendor's `surcharge_cents`, sets the order's `vendor_id`"."

        Design: Corner/cross_cutting_layers/immediate_visibility_of_mutation_in_response
        """
        # Wed 2026-08-05T10:00:00Z dispatch, tat 40 business hours:
        # Wed 7h + Thu 8h + Fri 8h + Mon 8h + Tue 8h = 39h; the 40th hour ends
        # Wed 2026-08-12 at 10:00:00Z.
        ctx = setup_consented_order(
            tag="XC4",
            with_matrix=False,
            vendor_overrides={"surcharge_cents": 500},
            package_overrides={"fee_cents": 10000, "tat_business_hours": 40},
            dispatch_at=None,
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        dispatched = validate_success(
            api.dispatch_order(ctx["order"]["id"], ctx["vendor"]["id"], HM)
        )
        assert dispatched["fulfillment_status"] == "DISPATCHED"
        assert dispatched["provisional_fee_cents"] == 10500
        assert_instant_equals(
            dispatched["sla_due_at"], "2026-08-12T10:00:00Z", "sla_due_at"
        )

        reread = validate_success(api.get_order(ctx["order"]["id"], HR))
        assert reread["fulfillment_status"] == "DISPATCHED"
        assert reread["provisional_fee_cents"] == 10500
        assert_instant_equals(
            reread["sla_due_at"], "2026-08-12T10:00:00Z", "sla_due_at re-read"
        )
