"""Transitions whose precondition lives on a different aggregate.

Shipping reads the customer's holds, claim generation re-reads the vision plan,
and hold release re-reads the prescription — none of these decisions can be made
from the addressed row alone.
"""

from test_helpers import (
    ApiErrorId,
    CO_BRAVO,
    WORKING_TUESDAY_10AM,
    assert_ledger_values,
    assert_timestamp_equals,
    setup_expired_prescription_via_sweep,
    setup_order_blocked_by_open_hold,
    setup_retired_plan_claim,
    validate_error,
    validate_success,
)


class TestShippingReadsTheCustomersHolds:
    """A cleared, pending order still may not ship while a hold on the same
    patient — a different aggregate entirely — sits in OPEN."""

    def test_cleared_order_cannot_ship_while_a_hold_is_open(
        self, api, fulfillment_headers, admin_headers
    ):
        """PRD §3.7: "A warehouse operator may advance an order from `PENDING` to
        `SHIPPED` only when its `verification_state` is `RX_CLEARED` — an order
        still `RX_PENDING` or already `RX_BLOCKED` cannot ship, and the attempt
        is reported as an undeclared transition — and only when the order's
        customer has no reorder hold in `OPEN` status, which is reported
        specifically as `ERR_HOLD_OPEN_BLOCKS_ACTION`."

        Design: Difficulty/cross_entity_state_dependency/shipping_depends_on_absence_of_open_reorder_hold
        """
        scenario = setup_order_blocked_by_open_hold(clock=WORKING_TUESDAY_10AM)
        order_id = scenario["order"]["id"]

        response = api.ship_order(order_id, fulfillment_headers)

        validate_error(response, ApiErrorId.ERR_HOLD_OPEN_BLOCKS_ACTION.value, 409)

        order = validate_success(api.get_order(order_id, admin_headers))
        assert order["verification_state"] == "RX_CLEARED", (
            "the blocked ship attempt must leave the verification dimension alone"
        )
        assert order["fulfillment_state"] == "PENDING", (
            "the blocked ship attempt must leave the fulfilment dimension alone"
        )

    def test_release_by_a_second_officer_lets_the_same_order_ship(
        self, api, fulfillment_headers, compliance_second_headers, admin_headers
    ):
        """PRD §3.7: "A release records `released_by_user_id`, appends a
        `HOLD_RELEASED` compliance event, and recomputes the customer's
        `open_hold_count` and `auto_reorder_enabled`."
        PRD §2.7: "`open_hold_count` is the number of that customer's reorder
        holds whose `status` is `OPEN`."
        PRD §3.7: "A warehouse operator may advance an order from `PENDING` to
        `SHIPPED` only when its `verification_state` is `RX_CLEARED` — an order
        still `RX_PENDING` or already `RX_BLOCKED` cannot ship, and the attempt
        is reported as an undeclared transition — and only when the order's
        customer has no reorder hold in `OPEN` status, which is reported
        specifically as `ERR_HOLD_OPEN_BLOCKS_ACTION`."
        PRD §3.7: "Shipping stamps `shipped_at` from the logical clock and leaves
        `verification_state` untouched."

        Design: Difficulty/cross_entity_state_dependency/shipping_depends_on_absence_of_open_reorder_hold
        """
        scenario = setup_order_blocked_by_open_hold(clock=WORKING_TUESDAY_10AM)
        order_id = scenario["order"]["id"]
        hold_id = scenario["hold"]["id"]
        customer_id = scenario["customer"]["id"]

        released = validate_success(
            api.release_reorder_hold(hold_id, {}, compliance_second_headers)
        )
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == CO_BRAVO

        ledger = validate_success(api.get_customer_ledger(customer_id, admin_headers))
        assert_ledger_values(ledger, open_hold_count=0)

        shipped = validate_success(api.ship_order(order_id, fulfillment_headers))
        assert shipped["fulfillment_state"] == "SHIPPED"
        assert_timestamp_equals(shipped["shipped_at"], "2026-09-08T10:00:00.000Z")


class TestClaimGenerationRereadsThePlan:
    """Plan eligibility is read at generation time, not snapshotted when the
    DRAFT claim row was opened."""

    def test_generation_refused_after_the_plan_is_retired(
        self, api, compliance_headers
    ):
        """PRD §3.1: "A plan's `status` is `ACTIVE` or `RETIRED` and defaults to
        `ACTIVE`; retiring a plan flips it to `RETIRED`, after which claim
        creation and claim generation against it are both refused with
        `ERR_PLAN_RETIRED`."
        PRD §3.9: "The claim is created in `DRAFT` with every money field null
        except `refund_offset_cents`, which is seeded from the settled returns
        already recorded against the order."
        PRD §3.9: "Generation also mints a `packet_reference`, the paperwork
        identifier, and increases the customer's `allowance_used_cents` by
        `applied_allowance_cents` — reconciled, as §2.7 requires, from the live
        claim rows rather than incremented blindly."

        Design: Difficulty/cross_entity_state_dependency/claim_generation_depends_on_plan_status_of_another_aggregate
        """
        scenario = setup_retired_plan_claim(clock=WORKING_TUESDAY_10AM)
        claim_id = scenario["claim"]["id"]

        response = api.generate_reimbursement_claim(claim_id, compliance_headers)

        validate_error(response, ApiErrorId.ERR_PLAN_RETIRED.value, 409)

        claim = validate_success(api.get_reimbursement_claim(claim_id, compliance_headers))
        assert claim["status"] == "DRAFT", "a refused generation leaves the claim in DRAFT"
        assert claim["packet_reference"] is None, (
            "packet_reference is minted by generation, so it stays null here"
        )
        assert claim["reimbursable_cents"] is None, (
            "a DRAFT claim's money fields are null"
        )

    def test_refused_generation_consumes_no_plan_year_allowance(
        self, api, compliance_headers
    ):
        """PRD §2.7: "`allowance_used_cents` is then the sum of
        `applied_allowance_cents` over that customer's reimbursement claims whose
        `created_at` falls inside the window and whose `status` is `GENERATED` or
        `SUBMITTED`."
        PRD §2.7: "Claims in `DRAFT` and claims in `VOIDED` contribute nothing."
        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero; for
        a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/cross_entity_state_dependency/claim_generation_depends_on_plan_status_of_another_aggregate
        """
        scenario = setup_retired_plan_claim(clock=WORKING_TUESDAY_10AM)
        claim_id = scenario["claim"]["id"]
        customer_id = scenario["customer"]["id"]

        validate_error(
            api.generate_reimbursement_claim(claim_id, compliance_headers),
            ApiErrorId.ERR_PLAN_RETIRED.value,
            409,
        )

        ledger = validate_success(
            api.get_customer_ledger(customer_id, compliance_headers)
        )
        assert_ledger_values(
            ledger, allowance_used_cents=0, allowance_remaining_cents=15000
        )


class TestHoldReleaseRereadsThePrescription:
    """The system-opened expiry hold is not self-contained: releasing it reads the
    prescription it names, and refuses while that prescription is EXPIRED."""

    def test_release_refused_while_the_prescription_is_expired(
        self, api, compliance_second_headers
    ):
        """PRD §3.7: "Releasing a hold has three gates, evaluated in the §2.10
        order: the releasing `X-User-ID` must differ from `opened_by_user_id`, or
        the release is refused with `ERR_SEGREGATION_OF_DUTIES`; the
        prescription's `status` must be `VERIFIED_ACTIVE`, or the release is
        refused with `ERR_PRESCRIPTION_NOT_VERIFIED`; and no prescriber dispute on
        the same prescription may be in `OPEN` status, or the release is refused
        with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."
        PRD §2.8: "Holds opened by a cascade rather than by a human record the
        literal string `"system"` in `opened_by_user_id`, which means any human
        operator may release them."
        PRD §3.4: "A reorder hold is opened with `reason` `PRESCRIPTION_EXPIRED`
        in `OPEN` status and `opened_by_user_id` set to `system`."

        Design: Difficulty/cross_entity_state_dependency/hold_release_depends_on_prescription_state
        """
        scenario = setup_expired_prescription_via_sweep()
        assert scenario["hold"] is not None, "the sweep must have opened an expiry hold"
        hold_id = scenario["hold"]["id"]

        response = api.release_reorder_hold(
            hold_id, {"note": "patient asked"}, compliance_second_headers
        )

        validate_error(response, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED.value, 409)

        hold = validate_success(api.get_reorder_hold(hold_id, compliance_second_headers))
        assert hold["status"] == "OPEN", "the refused release leaves the hold OPEN"
        assert hold["opened_by_user_id"] == "system", (
            "a cascade-opened hold records the literal string system, so segregation "
            "of duties was not what blocked co-bravo"
        )

    def test_escalation_clears_the_expiry_hold_the_release_could_not(
        self, api, compliance_second_headers
    ):
        """PRD §3.7: "Alternatively a compliance officer may escalate the hold
        instead of releasing it, supplying an `escalated_reason` that is recorded
        on the row; escalation moves the hold to `ESCALATED`, appends a
        `HOLD_ESCALATED` compliance event, and — because `ESCALATED` is no longer
        `OPEN` — also decrements `open_hold_count` and recomputes
        `auto_reorder_enabled`, so escalation clears the fulfilment block just as
        release does."
        PRD §2.7: "`open_hold_count` is the number of that customer's reorder
        holds whose `status` is `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/hold_release_depends_on_prescription_state
        """
        scenario = setup_expired_prescription_via_sweep()
        assert scenario["hold"] is not None, "the sweep must have opened an expiry hold"
        hold_id = scenario["hold"]["id"]
        customer_id = scenario["customer"]["id"]

        escalated = validate_success(
            api.escalate_reorder_hold(
                hold_id,
                {"escalated_reason": "expired rx, needs new capture"},
                compliance_second_headers,
            )
        )

        assert escalated["status"] == "ESCALATED"

        ledger = validate_success(
            api.get_customer_ledger(customer_id, compliance_second_headers)
        )
        assert_ledger_values(ledger, open_hold_count=0)
