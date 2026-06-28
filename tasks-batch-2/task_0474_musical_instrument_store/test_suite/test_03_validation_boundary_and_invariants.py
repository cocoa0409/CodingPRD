"""Depth tests for layered validation precedence, numeric boundary precision,
cross-entity state dependencies, resource temporal overlap, and money-conserving
compensating invariants.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    make_customer_headers,
    create_customer,
    setup_customer_and_active_agreement, setup_rto_with_n_paid_months,
    setup_quoted_special_order, setup_submitted_financing,
    setup_enrollment_linked_to_active_agreement, setup_open_layaway,
    setup_deposited_special_order,
    create_reserved_unit, read_agreement, advance_cycles,
    ApiErrorId, NON_EXISTENT_UUID,
    reserve_unit_payload, pay_deposit_payload, advance_cycle_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Difficulty / priority_pair_validation_conflict
# ===========================================================================
class TestValidationPrecedence:
    def test_forbidden_beats_invalid_state_on_repossess(self, api):
        """PRD §2.7: "Authorization comes second: a recognized role that is not
        permitted for the operation yields ERR_FORBIDDEN."
        PRD §2.7: "Then state validity is checked: the target resource must be in a
        state from which the requested transition is legal, otherwise ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_repossess
        """
        # Customer (not StoreManager) attempts repossess on an ACTIVE (not DEFAULTED)
        # agreement: violates both authorization and state — authorization wins.
        customer, agreement, _ = setup_customer_and_active_agreement(plan="RENTAL")
        resp = api.repossess_agreement(agreement["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        after = read_agreement(agreement["id"])
        assert after["status"] == "ACTIVE"

    def test_not_found_beats_credit_too_low_on_approve(self, api):
        """PRD §2.7: "Existence comes third: every resource referenced by the request
        ... must exist, validated left-to-right in the order they appear, and the
        first missing reference yields ERR_NOT_FOUND."
        PRD §2.7: "Only after all of those do the operation-specific business rules
        run (plan eligibility, payoff exactness, credit thresholds, deposit
        sufficiency, layaway-paid checks, and so on)"

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_credit_too_low_on_approve
        """
        # Approving a non-existent application id: existence (404) is checked before
        # the credit-score business rule, so ERR_NOT_FOUND wins.
        resp = api.approve_financing(NON_EXISTENT_UUID, SM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_authorized_role_on_active_agreement_surfaces_state_error(self, api):
        """PRD §2.7: "Then state validity is checked: the target resource must be in a
        state from which the requested transition is legal, otherwise ERR_INVALID_STATE."
        PRD §3.3: "Repossession is permitted only from DEFAULTED; attempting it from
        any other state is rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_repossess
        """
        # The authorized actor (StoreManager) on the same ACTIVE agreement passes the
        # authorization gate, so the layered sequence advances to the state check —
        # demonstrating that authorization, not state, is what pre-empts in the
        # Customer case above.
        customer, agreement, _ = setup_customer_and_active_agreement(plan="RENT_TO_OWN")
        resp = api.repossess_agreement(agreement["id"], SM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = read_agreement(agreement["id"])
        assert after["status"] == "ACTIVE"

    def test_credit_business_rule_fires_once_existence_passes(self, api):
        """PRD §2.7: "Only after all of those do the operation-specific business rules
        run (plan eligibility, payoff exactness, credit thresholds, ...)"
        PRD §3.8: "if it is below 660 the approval is blocked with ERR_CREDIT_TOO_LOW."

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_credit_too_low_on_approve
        """
        # When the application DOES exist, existence passes and the operation-specific
        # credit threshold becomes the reported error — confirming ERR_NOT_FOUND only
        # pre-empts when existence actually fails.
        customer, application = setup_submitted_financing(
            credit_score=640, principal_cents=240000, term_months=12
        )
        resp = api.approve_financing(application["id"], SM)
        validate_error(resp, ApiErrorId.ERR_CREDIT_TOO_LOW.value)


# ===========================================================================
# Difficulty / boundary_precision_check
# ===========================================================================
class TestDefaultThresholdBoundary:
    def test_two_missed_advances_stay_active(self, api):
        """PRD §3.3: "The threshold is three consecutive missed cycles: if an advance
        pushes the consecutive-missed count to three or more while the agreement is
        ACTIVE, the agreement transitions `ACTIVE → DEFAULTED`"

        Design: Difficulty/boundary_precision_check/default_threshold_at_exactly_three_missed
        """
        customer, agreement, _ = setup_customer_and_active_agreement(plan="RENT_TO_OWN")
        last = advance_cycles(agreement["id"], [1, 2])
        assert last["missed_streak"] == 2
        assert last["status"] == "ACTIVE"

    def test_third_missed_advance_crosses_to_defaulted(self, api):
        """PRD §3.3: "if an advance pushes the consecutive-missed count to three or
        more while the agreement is ACTIVE, the agreement transitions
        `ACTIVE → DEFAULTED`, and the late fee for that missed cycle is posted as part
        of the same advance."
        PRD §3.3: "the system appends a late-fee payment record ... an amount_cents
        of 1,500 cents (fifteen dollars) for the missed cycle."

        Design: Difficulty/boundary_precision_check/default_threshold_at_exactly_three_missed
        """
        customer, agreement, _ = setup_customer_and_active_agreement(plan="RENT_TO_OWN")
        last = advance_cycles(agreement["id"], [1, 2, 3])
        assert last["missed_streak"] == 3
        assert last["status"] == "DEFAULTED"
        # three unpaid cycles each posted a 1500 late fee -> 4500
        assert last["late_fee_balance_cents"] == 4500


class TestDepositBoundary:
    def test_deposit_exactly_meeting_required_is_accepted(self, api):
        """PRD §3.8: "A Customer or SalesAssociate pays a deposit by supplying
        amount_cents, which must be at least the required deposit — a smaller amount
        is rejected with ERR_DEPOSIT_INSUFFICIENT. A sufficient deposit transitions
        the order `QUOTED → DEPOSITED`, sets `deposit_paid_cents` to the supplied
        amount, and increments the order's `version`."

        Design: Difficulty/boundary_precision_check/deposit_exactly_meets_required_boundary
        """
        customer, order = setup_quoted_special_order(quoted_price_cents=200000, deposit_pct=0.25)
        assert order["required_deposit_cents"] == 50000
        deposited = validate_success(
            api.pay_deposit(order["id"], pay_deposit_payload(50000),
                            make_customer_headers(customer["id"])),
            200,
        )
        assert deposited["status"] == "DEPOSITED"
        assert deposited["deposit_paid_cents"] == 50000

    def test_one_cent_below_required_is_rejected(self, api):
        """PRD §3.8: "which must be at least the required deposit — a smaller amount
        is rejected with ERR_DEPOSIT_INSUFFICIENT."

        Design: Difficulty/boundary_precision_check/deposit_exactly_meets_required_boundary
        """
        customer, order = setup_quoted_special_order(quoted_price_cents=200000, deposit_pct=0.25)
        assert order["required_deposit_cents"] == 50000
        resp = api.pay_deposit(order["id"], pay_deposit_payload(49999),
                               make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)
        after = validate_success(api.get_special_order(order["id"], SA), 200)
        assert after["status"] == "QUOTED"


# ===========================================================================
# Difficulty / cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    def test_approve_blocked_by_low_customer_credit(self, api):
        """PRD §3.8: "the applicant Customer's credit_score must be at least the
        minimum financing score of 660; if it is below 660 the approval is blocked
        with ERR_CREDIT_TOO_LOW."

        Design: Difficulty/cross_entity_state_dependency/financing_approve_depends_on_customer_credit
        """
        customer, application = setup_submitted_financing(
            credit_score=640, principal_cents=240000, term_months=12
        )
        resp = api.approve_financing(application["id"], SM)
        validate_error(resp, ApiErrorId.ERR_CREDIT_TOO_LOW.value)

    def test_low_credit_blocked_approval_leaves_application_submitted(self, api):
        """PRD §3.8: "the applicant Customer's credit_score must be at least the
        minimum financing score of 660; if it is below 660 the approval is blocked
        with ERR_CREDIT_TOO_LOW."
        PRD §3.8: "The application starts `SUBMITTED` at `version` 1"

        Design: Difficulty/cross_entity_state_dependency/financing_approve_depends_on_customer_credit
        """
        # The application's own state is valid (SUBMITTED); a different entity's field
        # (Customer.credit_score) blocks, so the application is unchanged.
        customer, application = setup_submitted_financing(
            credit_score=659, principal_cents=120000, term_months=12
        )
        resp = api.approve_financing(application["id"], SM)
        validate_error(resp, ApiErrorId.ERR_CREDIT_TOO_LOW.value)
        after = validate_success(api.get_financing(application["id"], SM), 200)
        assert after["status"] == "SUBMITTED"

    def test_bundle_discount_lapses_when_agreement_no_longer_active(self, api):
        """PRD §3.9: "Resuming recomputes monthly_tuition_cents, because the bundle
        discount may have lapsed in the meantime — if the linked agreement is no
        longer ACTIVE, the resumed tuition loses the bundle portion."

        Design: Difficulty/cross_entity_state_dependency/lesson_bundle_discount_depends_on_agreement_active
        """
        customer, agreement, enrollment = setup_enrollment_linked_to_active_agreement(
            sessions_per_month=8, base_rate_cents=5000, instrument_family="BAND",
        )
        assert enrollment["monthly_tuition_cents"] == 27200
        cust_headers = make_customer_headers(customer["id"])
        # pause enrollment, return the agreement (now no longer ACTIVE), resume
        validate_success(api.pause_enrollment(enrollment["id"], cust_headers), 200)
        validate_success(api.return_agreement(agreement["id"], cust_headers), 200)
        resumed = validate_success(api.resume_enrollment(enrollment["id"], cust_headers), 200)
        # volume only now: 40000 * 0.85 = 34000 (no bundle)
        assert resumed["monthly_tuition_cents"] == 34000
        assert resumed["status"] == "ACTIVE"

    def test_bundle_discount_granted_while_linked_agreement_active(self, api):
        """PRD §3.9: "a bundle discount of twenty percent applies only when a
        rental_agreement_id is set and the linked RentalAgreement is currently
        ACTIVE, otherwise no bundle discount applies"

        Design: Difficulty/cross_entity_state_dependency/lesson_bundle_discount_depends_on_agreement_active
        """
        # The same enrollment, while its linked agreement is still ACTIVE, carries the
        # bundle discount — the cross-entity dependency in its granting direction.
        customer, agreement, enrollment = setup_enrollment_linked_to_active_agreement(
            sessions_per_month=8, base_rate_cents=5000, instrument_family="BAND",
        )
        assert agreement["status"] == "ACTIVE"
        # 40000 * 0.85 (volume) = 34000, then * 0.80 (bundle) = 27200
        assert enrollment["monthly_tuition_cents"] == 27200


# ===========================================================================
# Difficulty / resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_second_reserve_on_reserved_unit_collides(self, api):
        """PRD §3.1: "The unit must currently be `AVAILABLE`, and the supplied version
        must match per §2.8; on success the unit moves `AVAILABLE → RESERVED`"
        PRD §3.1: "A unit not in the required state for either action is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/resource_temporal_overlap/unit_single_disposition_reserve_blocks_second_hold
        """
        customer = create_customer()
        reserved, reserved_version = create_reserved_unit(customer["id"])
        # a second reserve carrying the post-reserve (current) version: the unit is
        # no longer AVAILABLE, so the state check rejects it.
        resp = api.reserve_unit(
            reserved["id"], reserve_unit_payload(customer["id"], reserved_version), SA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_unit(reserved["id"], SA), 200)
        assert after["status"] == "RESERVED"

    def test_advancing_a_paid_cycle_does_not_bump_streak(self, api):
        """PRD §3.3: "If a posted rent record already exists for that cycle index,
        the consecutive-missed count resets to 0."

        Design: Difficulty/resource_temporal_overlap/billing_cycle_index_aggregate_occupancy_one_payment_per_cycle
        """
        customer, agreement, _ = setup_rto_with_n_paid_months(
            num_months=1, list_price_cents=55000, monthly_rent_cents=5000, equity_rate_pct=0.50,
        )
        # cycle 1 is already covered by a POSTED RENT payment
        last = advance_cycles(agreement["id"], [1])
        assert last["missed_streak"] == 0
        assert last["late_fee_balance_cents"] == 0
        assert last["status"] == "ACTIVE"

    def test_released_unit_slot_can_be_re_reserved(self, api):
        """PRD §3.1: "Releasing a reservation returns a `RESERVED` unit to `AVAILABLE`,
        clears `reserved_for_customer_id`, and increments the unit's `version` by 1."
        PRD §3.1: "on success the unit moves `AVAILABLE → RESERVED`"

        Design: Difficulty/resource_temporal_overlap/unit_single_disposition_reserve_blocks_second_hold
        """
        # The exclusive single-holder slot, once vacated by release, admits a fresh
        # reserve — the complement of the blocked-while-held case above.
        customer = create_customer()
        reserved, _ = create_reserved_unit(customer["id"])
        released = validate_success(api.release_unit(reserved["id"], SA), 200)
        assert released["status"] == "AVAILABLE"
        re_reserved = validate_success(
            api.reserve_unit(reserved["id"], reserve_unit_payload(customer["id"], released["version"]), SA),
            200,
        )
        assert re_reserved["status"] == "RESERVED"

    def test_advancing_an_unpaid_cycle_bumps_streak_and_posts_fee(self, api):
        """PRD §3.3: "If no posted rent record exists for that cycle, the
        consecutive-missed count increases by 1 and the system appends a late-fee
        payment record — a PaymentRecord with kind LATE_FEE, status POSTED, and an
        amount_cents of 1,500 cents (fifteen dollars) for the missed cycle."

        Design: Difficulty/resource_temporal_overlap/billing_cycle_index_aggregate_occupancy_one_payment_per_cycle
        """
        # An unoccupied billing window (no POSTED RENT for that cycle) is NOT "covered",
        # so advancing it bumps the streak and posts a fee — the contrast to the
        # already-occupied cycle above.
        customer, agreement, _ = setup_customer_and_active_agreement(plan="RENT_TO_OWN")
        last = advance_cycles(agreement["id"], [1])
        assert last["missed_streak"] == 1
        assert last["late_fee_balance_cents"] == 1500
        assert last["status"] == "ACTIVE"


# ===========================================================================
# Difficulty / compensating_invariant
# ===========================================================================
class TestCompensatingInvariants:
    def test_layaway_cancel_splits_paid_into_refund_and_restock(self, api):
        """PRD §3.5: "The refund is computed by first forming the restock fee as the
        total price multiplied by the restock-fee fraction — total_price_cents times
        restock_fee_pct — rounded half up to whole cents, then taking the refund as
        the greater of zero and the paid amount minus that restock fee. That refund
        amount is added to the customer's store_credit_cents"

        Design: Difficulty/compensating_invariant/layaway_cancel_conserves_money_into_store_credit
        """
        # list 60000, deposit 20000 + one 20000 installment -> paid 40000; restock 0.10
        customer, plan, unit = setup_open_layaway(
            list_price_cents=60000, deposit_cents=20000, installments=[20000], restock_fee_pct=0.10
        )
        cancelled = validate_success(api.cancel_layaway(plan["id"], SA), 200)
        assert cancelled["status"] == "CANCELLED"
        # restock = round(60000*0.10)=6000; refund = 40000-6000 = 34000
        cust = validate_success(api.get_customer(customer["id"], SA), 200)
        assert cust["store_credit_cents"] == 34000
        # conservation: refund 34000 + restock 6000 == paid 40000
        assert cust["store_credit_cents"] + 6000 == 40000
        unit_after = validate_success(api.get_unit(unit["id"], SA), 200)
        assert unit_after["status"] == "AVAILABLE"

    def test_layaway_cancel_refund_floored_when_restock_exceeds_paid(self, api):
        """PRD §3.5: "taking the refund as the greater of zero and the paid amount
        minus that restock fee."
        PRD §2.5: "Computed balances that represent money owed or held — such as ...
        a customer's store_credit_cents — are floored at zero and never go negative."

        Design: Difficulty/compensating_invariant/layaway_cancel_conserves_money_into_store_credit
        """
        # paid 5000 (deposit only), restock = round(100000*0.10)=10000 > paid:
        # refund floored at 0, so no money is created — store credit stays 0.
        customer, plan, unit = setup_open_layaway(
            list_price_cents=100000, deposit_cents=5000, restock_fee_pct=0.10
        )
        validate_success(api.cancel_layaway(plan["id"], SA), 200)
        cust = validate_success(api.get_customer(customer["id"], SA), 200)
        assert cust["store_credit_cents"] == 0

    def test_special_order_cancel_returns_full_deposit(self, api):
        """PRD §3.8: "Cancelling a special order is permitted while it is QUOTED,
        DEPOSITED, or ORDERED, moving it to CANCELLED; if any deposit had been paid
        (deposit_paid_cents greater than 0), that deposit is refunded to the
        customer's store_credit_cents as a cascade."

        Design: Difficulty/compensating_invariant/special_order_cancel_conserves_deposit_back_to_credit
        """
        customer, order = setup_deposited_special_order(
            quoted_price_cents=200000, deposit_amount=50000
        )
        assert order["deposit_paid_cents"] == 50000
        cancelled = validate_success(api.cancel_special_order(order["id"], SA), 200)
        assert cancelled["status"] == "CANCELLED"
        cust = validate_success(api.get_customer(customer["id"], SA), 200)
        # full deposit conserved back to store credit
        assert cust["store_credit_cents"] == 50000

    def test_quoted_order_cancel_with_no_deposit_credits_nothing(self, api):
        """PRD §3.8: "if any deposit had been paid (deposit_paid_cents greater than 0),
        that deposit is refunded to the customer's store_credit_cents as a cascade."
        PRD §3.8: "The order starts `QUOTED` at `version` 1 with `deposit_paid_cents`
        of 0 and a null `fulfilled_unit_id`."

        Design: Difficulty/compensating_invariant/special_order_cancel_conserves_deposit_back_to_credit
        """
        # Cancelling a QUOTED order with no deposit paid moves nothing — the conserved
        # quantity (the deposit) is zero, so store credit is unchanged at 0.
        customer, order = setup_quoted_special_order(quoted_price_cents=200000)
        assert order["deposit_paid_cents"] == 0
        cancelled = validate_success(api.cancel_special_order(order["id"], SA), 200)
        assert cancelled["status"] == "CANCELLED"
        cust = validate_success(api.get_customer(customer["id"], SA), 200)
        assert cust["store_credit_cents"] == 0
