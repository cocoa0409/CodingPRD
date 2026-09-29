"""Transitions, refusals and the cascades that hang off them.

Each test drives one edge of one status machine: an initial state, a legal move,
an illegal move, a terminal-state lockdown, or a compensation that walks a cycle
backwards.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    LOGISTICS,
    ApiErrorId,
    api_client,
    assert_instant,
    assert_refund_ledger_identity,
    confirm_assignment_intake,
    create_customer_row,
    create_model,
    disposition_return,
    file_quality_claim,
    make_finance_controller_headers,
    open_return_case,
    read_assignment,
    read_customer,
    read_order,
    read_quality_claim,
    read_refund,
    read_return_case,
    request_evidence,
    set_clock,
    setup_delivered_order,
    setup_return_lifecycle,
    trial_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_refund,
    void_refund_payload,
)

S5_CONTROLLER = make_finance_controller_headers("fin-s5-a")


class TestTrialOrderFulfillmentAxis:
    """CREATED → IN_TRANSIT → DELIVERED, and the moves that are not on the graph."""

    def _created_order(self, sku: str, email: str, name: str, household: str):
        model = create_model(sku=sku, name="Comfort Q", list_price_cents=120000)
        customer = create_customer_row(
            email=email, full_name=name, household_hash=household
        )
        order = validate_success(
            api_client.create_trial_order(
                trial_order_payload(customer["id"], model["id"]), AGENT
            ),
            201,
        )
        return customer, order

    def test_a_new_order_sits_at_created_on_one_axis_and_not_started_on_the_other(self):
        """PRD §3.3: "An order's physical journey runs along the fulfillment axis, starting at `CREATED`."

        The two axes open independently: nothing about the trial has begun, so
        the trial axis is NOT_STARTED with all three window instants null, and the
        customer's delivered-order counter has not moved either.

        Design: Corner/state_machines/new_trial_order_starts_in_created_and_not_started
        """
        customer, order = self._created_order(
            "MDL-Q-S1", "s1@example.com", "Sam One", "HH-S1"
        )

        assert order["fulfillment_status"] == "CREATED"
        assert order["trial_status"] == "NOT_STARTED"
        assert order["delivered_at"] is None
        assert order["break_in_ends_at"] is None
        assert order["trial_ends_at"] is None
        assert read_customer(customer["id"])["lifetime_trial_count"] == 0, (
            "the delivered-order counter moves on delivery, not on creation"
        )

    def test_dispatch_moves_the_fulfillment_axis_and_leaves_the_trial_axis_alone(self):
        """PRD §3.3: "A `LogisticsCoordinator` dispatching the order advances `fulfillment_status` `CREATED → IN_TRANSIT` and bumps the order's `version`; the trial axis stays at `NOT_STARTED`, because the two axes are wholly independent and no clock starts until the mattress is in the house."

        One version bump, one axis moved, and delivered_at still null.

        Design: Corner/state_machines/dispatch_advances_the_fulfillment_axis_only
        """
        _customer, order = self._created_order(
            "MDL-Q-S2", "s2@example.com", "Sue Two", "HH-S2"
        )

        dispatched = validate_success(
            api_client.dispatch_trial_order(order["id"], {}, LOGISTICS), 200
        )

        assert dispatched["fulfillment_status"] == "IN_TRANSIT"
        assert dispatched["trial_status"] == "NOT_STARTED"
        assert dispatched["delivered_at"] is None
        assert dispatched["version"] == order["version"] + 1, (
            f"one mutation is one version bump, got {dispatched['version']} from "
            f"{order['version']}"
        )

    def test_delivering_before_dispatch_is_not_a_transition_on_the_graph(self):
        """PRD §3.3: "Dispatching an order that is not `CREATED`, or delivering one that is not `IN_TRANSIT`, is refused with `ERR_INVALID_ORDER_STATE`; so is keeping an order that is already returned or filing a claim on one that was never delivered."

        The refused call must leave the order exactly as it found it: still
        CREATED, delivered_at null, version unmoved and the customer's counter at
        zero.

        Design: Corner/state_machines/deliver_before_dispatch_returns_invalid_order_state
        """
        customer, order = self._created_order(
            "MDL-Q-S3", "s3@example.com", "Sid Three", "HH-S3"
        )

        response = api_client.deliver_trial_order(order["id"], {}, LOGISTICS)
        validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE)

        unchanged = read_order(order["id"])
        assert unchanged["fulfillment_status"] == "CREATED"
        assert unchanged["delivered_at"] is None
        assert unchanged["version"] == order["version"]
        assert read_customer(customer["id"])["lifetime_trial_count"] == 0

    def test_dispatching_twice_is_refused_rather_than_treated_as_idempotent(self):
        """PRD §3.3: "Dispatching an order that is not `CREATED`, or delivering one that is not `IN_TRANSIT`, is refused with `ERR_INVALID_ORDER_STATE`; so is keeping an order that is already returned or filing a claim on one that was never delivered."

        An order already IN_TRANSIT is no longer CREATED, so the repeat dispatch
        is refused and does not bump the version a second time.

        Design: Corner/state_machines/dispatching_an_already_dispatched_order_returns_invalid_order_state
        """
        _customer, order = self._created_order(
            "MDL-Q-S4", "s4@example.com", "Sal Four", "HH-S4"
        )
        dispatched = validate_success(
            api_client.dispatch_trial_order(order["id"], {}, LOGISTICS), 200
        )

        response = api_client.dispatch_trial_order(order["id"], {}, LOGISTICS)
        validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE)

        unchanged = read_order(order["id"])
        assert unchanged["fulfillment_status"] == "IN_TRANSIT"
        assert unchanged["version"] == dispatched["version"], (
            f"a refused transition must not bump the version, got "
            f"{unchanged['version']} from {dispatched['version']}"
        )

    def test_keeping_the_mattress_closes_both_axes_and_freezes_the_nights_slept(self):
        """PRD §3.3: "Keeping freezes `nights_slept` at the whole number of complete days between `delivered_at` and the current logical clock, and bumps the order's `version`."

        Delivered 2026-08-01 and kept at 2026-09-10 is exactly 40 complete days,
        and because a keep moves no money the refundable principal stays wholly
        outstanding.

        Design: Corner/state_machines/keeping_the_mattress_freezes_nights_slept_and_closes_both_axes
        """
        scenario = setup_delivered_order(
            model_overrides={"sku": "MDL-Q-S10"},
            customer_overrides={
                "email": "s10@example.com",
                "full_name": "Sara Ten",
                "household_hash": "HH-S10",
            },
        )
        set_clock("2026-09-10T00:00:00Z")

        kept = validate_success(
            api_client.keep_trial_order(
                scenario["order"]["id"], {}, scenario["customer_headers"]
            ),
            200,
        )

        assert kept["trial_status"] == "KEPT"
        assert kept["fulfillment_status"] == "CLOSED"
        assert kept["nights_slept"] == 40, (
            f"2026-08-01 to 2026-09-10 is 40 complete days, got {kept['nights_slept']}"
        )
        assert kept["outstanding_refundable_cents"] == 120000
        assert kept["refunded_total_cents"] == 0
        assert kept["retained_amount_cents"] == 0
        assert_refund_ledger_identity(kept)

        customer = read_customer(scenario["customer"]["id"])
        assert customer["completed_return_count"] == 0
        assert customer["signal_count"] == 0, (
            "keeping a mattress is not a return and raises no abuse signal"
        )


class TestDeliveryIsACrossEntityWrite:
    """The second delivery in one household is what mints the fraud signal."""

    def test_a_second_household_delivery_appends_exactly_one_household_match_signal(self):
        """PRD §3.3: "And it runs the two delivery-time fraud detectors: when another customer sharing this customer's `household_hash` already holds a trial order whose fulfillment has reached `DELIVERED`, a `HOUSEHOLD_MATCH` signal is appended, and when the same household already holds a delivered order whose `channel` differs from this order's `channel`, a `MULTI_CHANNEL` signal is appended."

        Both orders are DTC, so only the household detector fires: one 30-point
        signal lands on the household member being delivered to, the earlier
        member's score stays at zero, and the delivery also opens the two windows
        at 2026-08-22 and 2026-11-09.

        Design: Corner/state_machines/delivering_a_second_order_in_the_same_household_appends_a_household_match_signal
        """
        model = create_model(sku="MDL-Q-S9", name="Comfort Q", list_price_cents=120000)
        first = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "s9a@example.com",
                "full_name": "Ann Nine",
                "household_hash": "HH-S9",
            },
        )
        validate_success(
            api_client.keep_trial_order(
                first["order"]["id"], {}, first["customer_headers"]
            ),
            200,
        )

        second_customer = create_customer_row(
            email="s9b@example.com", full_name="Bob Nine", household_hash="HH-S9"
        )
        second_order = validate_success(
            api_client.create_trial_order(
                trial_order_payload(second_customer["id"], model["id"]), AGENT
            ),
            201,
        )
        validate_success(
            api_client.dispatch_trial_order(second_order["id"], {}, LOGISTICS), 200
        )

        delivered = validate_success(
            api_client.deliver_trial_order(second_order["id"], {}, LOGISTICS), 200
        )

        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["trial_status"] == "BREAK_IN"
        assert_instant(
            delivered["break_in_ends_at"], "2026-08-22T00:00:00Z", "break_in_ends_at"
        )
        assert_instant(
            delivered["trial_ends_at"], "2026-11-09T00:00:00Z", "trial_ends_at"
        )

        rows, meta = validate_paginated(
            api_client.list_customer_abuse_signals(second_customer["id"], ADMIN)
        )
        assert meta["total_count"] == 1, (
            f"only the household detector fires on two DTC orders, got "
            f"{meta['total_count']} signals"
        )
        assert rows[0]["signal_type"] == "HOUSEHOLD_MATCH"
        assert rows[0]["weight"] == 30

        loaded = read_customer(second_customer["id"])
        assert loaded["signal_count"] == 1
        assert loaded["abuse_score_rolling"] == 30
        assert loaded["abuse_score_lifetime"] == 30
        assert loaded["status"] == "ACTIVE"
        assert loaded["lifetime_trial_count"] == 1

        earlier = read_customer(first["customer"]["id"])
        assert earlier["signal_count"] == 0, (
            "the signal lands on the later household member only"
        )
        assert earlier["abuse_score_rolling"] == 0


class TestQualityClaimEvidenceLoop:
    """request-evidence is only a transition out of SUBMITTED."""

    def test_requesting_evidence_twice_is_refused_on_the_second_call(self):
        """PRD §3.4: "Requesting evidence on a claim that is not `SUBMITTED`, submitting evidence when none was requested, adjudicating a claim that is already settled, or settling one that was not approved for credit are all refused with `ERR_INVALID_CLAIM_STATE`."

        The claim is already in EVIDENCE_REQUESTED, so the repeat request is
        refused; because no round has actually been submitted yet the round
        counter is still zero, and the order stays in its complaint state.

        Design: Corner/state_machines/requesting_evidence_twice_on_a_quality_claim_returns_invalid_claim_state
        """
        scenario = setup_delivered_order(
            model_overrides={"sku": "MDL-Q-S6"},
            customer_overrides={
                "email": "s6@example.com",
                "full_name": "Sol Six",
                "household_hash": "HH-S6",
            },
        )
        set_clock("2026-08-03T00:00:00Z")
        claim = file_quality_claim(
            scenario["order"]["id"],
            "SHIPPING_DAMAGE",
            2,
            headers=scenario["customer_headers"],
        )
        requested = request_evidence(claim["id"])
        assert requested["status"] == "EVIDENCE_REQUESTED"

        response = api_client.request_claim_evidence(claim["id"], {}, AGENT)
        validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE)

        unchanged = read_quality_claim(claim["id"])
        assert unchanged["status"] == "EVIDENCE_REQUESTED"
        assert unchanged["evidence_round_count"] == 0, (
            "the round counter only moves when the customer actually supplies a "
            f"fresh round, got {unchanged['evidence_round_count']}"
        )
        assert unchanged["version"] == requested["version"]
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == (
            "DAMAGED_REPORTED"
        )


class TestRefundVoidIsTerminal:
    """VOIDED is the end of the ledger row's life."""

    def test_voiding_an_already_voided_row_is_refused_and_compensates_nothing_twice(self):
        """PRD §3.9: "Releasing a voided row, releasing twice, or voiding an already-voided row are all refused with `ERR_INVALID_REFUND_STATE`."

        The first void was against an AUTHORIZED row, so no money had moved and
        the ledger was already untouched; the refused second void must leave
        voided_at and void_reason exactly as the first call wrote them.

        Design: Corner/state_machines/voiding_an_already_voided_refund_returns_invalid_refund_state
        """
        scenario = setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={"sku": "MDL-Q-S5", "donation_eligible": True},
            customer_overrides={
                "email": "s5@example.com",
                "full_name": "Sky Five",
                "household_hash": "HH-S5",
            },
            authorizer_headers=S5_CONTROLLER,
        )
        voided = void_refund(
            scenario["refund"]["id"],
            headers=S5_CONTROLLER,
            void_reason="priced against a stale inspection grade",
        )
        assert voided["status"] == "VOIDED"

        response = api_client.void_refund(
            scenario["refund"]["id"],
            void_refund_payload("second void attempt"),
            S5_CONTROLLER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REFUND_STATE)

        unchanged = read_refund(scenario["refund"]["id"])
        assert unchanged["status"] == "VOIDED"
        assert_instant(unchanged["voided_at"], "2026-09-15T00:00:00Z", "voided_at")
        assert unchanged["void_reason"] == "priced against a stale inspection grade", (
            f"the refused call must not overwrite the audit reason, got "
            f"{unchanged['void_reason']!r}"
        )
        assert read_return_case(scenario["return_case"]["id"])["financial_status"] == "VOID"

        order = read_order(scenario["order"]["id"])
        assert order["refunded_total_cents"] == 0
        assert order["outstanding_refundable_cents"] == 120000
        assert order["retained_amount_cents"] == 0
        assert_refund_ledger_identity(order)


class TestReturnCaseCyclesBackwards:
    """Two compensations that walk a logistics or trial axis in reverse."""

    def test_cancelling_a_return_hands_the_order_back_to_its_trial(self):
        """PRD §3.6: "Cancellation sets `logistics_status` to `CANCELLED` and `financial_status` to `VOID`, discards the refund pricing, and hands the order back to its trial: the trial axis reverts `RETURN_REQUESTED → TRIAL_ACTIVE` when the logical clock is still before `trial_ends_at`, and lands in `TRIAL_EXPIRED` instead when the clock has already passed it."

        At 2026-09-10 the trial still runs to 2026-11-09, so the order returns to
        TRIAL_ACTIVE; because a cancelled case does not count as live, a second
        return can then be opened on the same order.

        Design: Corner/state_machines/cancelling_a_return_case_cycles_the_order_back_to_trial_active
        """
        scenario = setup_delivered_order(
            model_overrides={"sku": "MDL-Q-S8"},
            customer_overrides={
                "email": "s8@example.com",
                "full_name": "Sean Eight",
                "household_hash": "HH-S8",
            },
        )
        first = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-09-10T00:00:00Z",
        )

        cancelled = validate_success(
            api_client.cancel_return_case(
                first["id"], {}, scenario["customer_headers"]
            ),
            200,
        )
        assert cancelled["logistics_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOID"
        assert cancelled["nights_used"] is None
        assert cancelled["picked_up_at"] is None

        released = read_order(scenario["order"]["id"])
        assert released["trial_status"] == "TRIAL_ACTIVE"
        assert released["fulfillment_status"] == "DELIVERED"

        second = validate_success(
            api_client.create_return_case(
                {"order_id": scenario["order"]["id"], "reason_code": "OTHER"},
                scenario["customer_headers"],
            ),
            201,
        )
        assert second["logistics_status"] == "REQUESTED"
        assert_instant(second["requested_at"], "2026-09-10T00:00:00Z", "requested_at")
        assert read_order(scenario["order"]["id"])["trial_status"] == "RETURN_REQUESTED"

    def test_a_rejected_intake_frees_the_day_bucket_and_reopens_the_case(self):
        """PRD §3.8: "An `outcome` of `REJECTED` advances the assignment `ASSIGNED → REJECTED`, frees its units from the partner's `intake_date` bucket as a conserving compensation, and reopens the return case — `logistics_status` reverts `DISPOSITIONED → INSPECTED` and `disposition` reverts to `PENDING` so a different partner can be selected — incrementing the case's `version` by one."

        The only recycler in the region takes two units a day and the queen unit
        is exactly two units, so a re-disposition onto the same intake date can
        only succeed if the rejected assignment genuinely gave its units back; the
        rejected row is retained rather than deleted.

        Design: Corner/state_machines/rejecting_intake_frees_the_partner_day_bucket_and_reverts_the_return_to_inspected
        """
        scenario = setup_return_lifecycle(
            stage="DISPOSITIONED",
            model_overrides={"sku": "MDL-Q-S7", "donation_eligible": False},
            customer_overrides={
                "email": "s7@example.com",
                "full_name": "Sky Seven",
                "household_hash": "HH-S7",
            },
            partner_specs=[
                {
                    "name": "Recycler S7",
                    "partner_type": "RECYCLER",
                    "region_code": "CA",
                    "daily_intake_capacity_units": 2,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "ACCEPT_SOILED",
                    "priority_rank": 1,
                    "recycle_fee_cents_per_unit": 5000,
                }
            ],
            disposition="RECYCLE",
            intake_date="2026-09-16",
        )
        recycler = scenario["partners"][0]
        first_assignment = scenario["assignment"]
        assert first_assignment["units"] == 2

        rejected = confirm_assignment_intake(first_assignment["id"], "REJECTED")
        assert rejected["status"] == "REJECTED"
        assert rejected["units"] == 2

        reopened = read_return_case(scenario["return_case"]["id"])
        assert reopened["logistics_status"] == "INSPECTED"
        assert reopened["disposition"] == "PENDING"

        second_assignment = disposition_return(
            scenario["return_case"]["id"], "RECYCLE", "2026-09-16"
        )
        assert second_assignment["partner_id"] == recycler["id"], (
            "the freed units must let the same two-unit-a-day recycler take the "
            "unit again on the same intake date"
        )
        assert second_assignment["intake_date"] == "2026-09-16"
        assert second_assignment["status"] == "ASSIGNED"

        _rows, meta = validate_paginated(
            api_client.list_disposition_assignments(
                LOGISTICS, params={"return_case_id": scenario["return_case"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the rejected row is retained for audit, not deleted, got "
            f"{meta['total_count']} rows"
        )

        settled = read_return_case(scenario["return_case"]["id"])
        assert settled["logistics_status"] == "DISPOSITIONED"
        assert settled["disposition"] == "RECYCLE"
        assert read_assignment(first_assignment["id"])["status"] == "REJECTED"
