"""Lifecycle corners: entry states, guarded transitions, terminal lockdown.

Each test walks one prescription / order / hold / dispute / return through the
lifecycle rules of the PRD and pins both the transition outcome and the side
effects the PRD attaches to it.
"""

from test_helpers import (
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    CO_BRAVO,
    CO_BRAVO_HEADERS,
    DEFAULT_CLOCK_UTC,
    FO_HEADERS,
    WORKING_TUESDAY_10AM,
    ApiErrorId,
    assert_ledger_values,
    assert_order,
    assert_prescriber_dispute,
    assert_prescription,
    assert_reorder_hold,
    assert_return_request,
    cancel_order,
    count_compliance_events,
    create_order_payload,
    create_reorder_hold_payload,
    file_prescriber_dispute,
    get_ledger,
    make_customer_headers,
    new_order,
    read_order,
    read_prescription,
    resolve_prescriber_dispute,
    run_verification_sweep,
    set_clock,
    setup_approved_return,
    setup_draft_prescription,
    setup_order_on_verified_prescription,
    setup_pending_verification_prescription,
    setup_verified_prescription,
    setup_verified_prescription_with_prescriber,
    validate_error,
    validate_paginated,
    validate_success,
)

# A prescription valid until 2026-09-10 read against a clock two days earlier is
# still live; the same prescription read on 2026-09-11 has lapsed.
CLOCK_BEFORE_EXPIRY = "2026-09-08T10:00:00Z"
CLOCK_AFTER_EXPIRY = "2026-09-11T09:00:00Z"
LAPSING_EXPIRY_DATE = "2026-09-10"


def _verification_request_count(api, prescription_id: str) -> int:
    """How many verification requests exist for one prescription."""
    _, meta = validate_paginated(
        api.list_verification_requests(
            CO_ALPHA_HEADERS, params={"prescription_id": prescription_id}
        )
    )
    return meta["total_count"]


def _setup_lapsed_prescription_swept_to_expired() -> dict:
    """A prescription that a sweep run after its expiry date drove to EXPIRED.

    The prescription names a prescriber, so a verification round can then be
    attempted against the terminal row.
    """
    scenario = setup_verified_prescription_with_prescriber(
        clock=CLOCK_BEFORE_EXPIRY,
        prescription_overrides={"expiry_date": LAPSING_EXPIRY_DATE},
    )
    set_clock(CLOCK_AFTER_EXPIRY)
    scenario["sweep"] = run_verification_sweep()
    return scenario


class TestPrescriptionSubmitFork:
    """Submit routes a prescription by `capture_mode` into one of two states."""

    def test_upload_submit_lands_directly_in_verified_active(self, api):
        """PRD §3.3: "When `capture_mode` is `UPLOAD` and `document_reference` is
        present, the document itself is the evidence and the prescription goes
        straight from `DRAFT` to `VERIFIED_ACTIVE`."

        PRD §3.3: "A successful upload submit appends a compliance event of type
        `RX_SUBMITTED` with the detail `upload accepted`."

        PRD §3.2: "It also carries two derived counters: `boxes_consumed`, the
        running box ledger described in §2.7, and `verification_rounds`, the
        number of verification contacts sent on its behalf, both starting at
        zero."

        PRD §3.3: "A successful round creates a **verification request**."

        Design: Corner/state_machines/upload_submit_moves_prescription_from_draft_to_verified_active
        """
        scenario = setup_draft_prescription(clock=DEFAULT_CLOCK_UTC)
        prescription = scenario["prescription"]
        customer = scenario["customer"]

        data = validate_success(
            api.submit_prescription(
                prescription["id"], make_customer_headers(customer["id"])
            ),
            200,
        )

        assert_prescription(data)
        assert data["status"] == "VERIFIED_ACTIVE"
        assert data["verification_rounds"] == 0
        assert _verification_request_count(api, prescription["id"]) == 0

        events, meta = validate_paginated(
            api.list_compliance_events_for_prescription(
                prescription["id"], CO_ALPHA_HEADERS
            )
        )
        assert meta["total_count"] == 1
        assert events[0]["event_type"] == "RX_SUBMITTED"
        assert events[0]["detail"] == "upload accepted"

    def test_doctor_lookup_submit_lands_in_pending_verification(self, api):
        """PRD §3.3: "When `capture_mode` is `DOCTOR_LOOKUP` — which requires
        `prescriber_id` — or `SELF_REPORT` — which requires
        `self_reported_prescriber_name` — the prescription moves from `DRAFT` to
        `PENDING_VERIFICATION` and awaits the prescriber."

        PRD §3.3: "This submit appends a compliance event of type `RX_SUBMITTED`
        with the detail `awaiting prescriber verification`, and it does nothing
        else: in particular it does not invalidate the prescription named by
        `supersedes_prescription_id` and does not cancel that prescription's
        schedules."

        PRD §3.2: "It also carries two derived counters: `boxes_consumed`, the
        running box ledger described in §2.7, and `verification_rounds`, the
        number of verification contacts sent on its behalf, both starting at
        zero."

        Design: Corner/state_machines/doctor_lookup_submit_moves_prescription_from_draft_to_pending_verification
        """
        scenario = setup_pending_verification_prescription(
            clock=WORKING_TUESDAY_10AM, submit=False
        )
        prescription = scenario["prescription"]
        customer = scenario["customer"]

        data = validate_success(
            api.submit_prescription(
                prescription["id"], make_customer_headers(customer["id"])
            ),
            200,
        )

        assert_prescription(data)
        assert data["status"] == "PENDING_VERIFICATION"
        assert data["verification_rounds"] == 0

        events, meta = validate_paginated(
            api.list_compliance_events_for_prescription(
                prescription["id"], CO_ALPHA_HEADERS
            )
        )
        assert meta["total_count"] == 1
        assert events[0]["event_type"] == "RX_SUBMITTED"
        assert events[0]["detail"] == "awaiting prescriber verification"


class TestOrderInitialLifecycleStates:
    """An order is born into two independent lifecycle dimensions."""

    def test_order_on_unverified_prescription_is_born_rx_pending_and_pending(self, api):
        """PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        PRD §3.5: "Its `fulfillment_state` begins at `PENDING`."

        PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached
        the free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        PRD §3.5: "Placing an order also moves the ledgers forward: the
        prescription's `boxes_consumed` grows by the ordered boxes, and the
        customer's `lifetime_charged_cents` and `net_cash_position_cents` are
        reconciled."

        PRD §3.5: "Order lists may be filtered by `customer_id`,
        `prescription_id`, `ordered_product_id`, `fulfilled_product_id` and,
        independently, by `verification_state` and `fulfillment_state`."

        Design: Corner/state_machines/order_against_pending_verification_prescription_starts_rx_pending_and_pending
        """
        scenario = setup_pending_verification_prescription(clock=WORKING_TUESDAY_10AM)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]

        data = validate_success(
            api.create_order(
                create_order_payload(
                    customer_id, prescription_id, scenario["product"]["id"], 1, 1
                ),
                make_customer_headers(customer_id),
            ),
            201,
        )

        assert_order(data)
        assert data["verification_state"] == "RX_PENDING"
        assert data["fulfillment_state"] == "PENDING"
        assert data["total_cents"] == 6400

        assert read_prescription(prescription_id)["boxes_consumed"] == 2

        _, meta = validate_paginated(
            api.list_orders(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "verification_state": "RX_PENDING"},
            )
        )
        assert meta["total_count"] == 1


class TestReorderHoldInitialLifecycleState:
    """A manually opened hold enters OPEN and stamps its opener."""

    def test_manual_hold_opens_as_open_and_stamps_the_acting_operator(self, api):
        """PRD §3.7: "Opening a hold manually records the acting `X-User-ID` in
        `opened_by_user_id`, increments the customer's `open_hold_count`,
        recomputes `auto_reorder_enabled`, and appends a `HOLD_OPENED`
        compliance event."

        PRD §3.7: "A hold's `status` runs from `OPEN` to one of the terminal
        values `RELEASED` or `ESCALATED`, and holds may be listed filtered by
        `customer_id`, `prescription_id`, `reason` and `status`."

        PRD §2.7: "`auto_reorder_enabled` is true exactly when
        `active_schedule_count` is greater than zero and `open_hold_count` is
        zero, and false in every other case."

        Design: Corner/state_machines/reorder_hold_starts_open_and_stamps_opened_by_user_id
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]

        data = validate_success(
            api.create_reorder_hold(
                create_reorder_hold_payload(customer_id, prescription_id),
                CO_ALPHA_HEADERS,
            ),
            201,
        )

        assert_reorder_hold(data)
        assert data["status"] == "OPEN"
        assert data["reason"] == "MANUAL"
        assert data["opened_by_user_id"] == CO_ALPHA
        assert data.get("released_by_user_id") is None

        ledger = get_ledger(customer_id)
        assert_ledger_values(ledger, open_hold_count=1)
        assert ledger["auto_reorder_enabled"] is False

        assert count_compliance_events(prescription_id, "HOLD_OPENED") == 1


class TestOrderFulfillmentTransitionGuards:
    """The fulfilment dimension refuses undeclared and repeated triggers."""

    def test_second_cancel_of_a_cancelled_order_is_refused_and_moves_no_ledger(
        self, api
    ):
        """PRD §2.10: "On any action endpoint, the requested trigger is not
        declared for the target row's current state — including any attempt from
        a terminal state and any repeat of an already-applied trigger →
        `ERR_INVALID_STATE_TRANSITION` (409)."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §3.7: "The prescription's `boxes_consumed` is reduced by that
        order's `boxes_od` plus `boxes_os`, freeing the authorisation for
        reuse."

        PRD §3.7: "An `ORDER_CANCELLED` compliance event is appended."

        Design: Corner/state_machines/second_cancel_of_a_cancelled_order_is_an_invalid_state_transition
        """
        scenario = setup_order_on_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        order_id = scenario["order"]["id"]
        cancel_order(order_id, customer_id)

        validate_error(
            api.cancel_order(
                order_id,
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                make_customer_headers(customer_id),
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_charged_cents=0,
            net_cash_position_cents=0,
        )
        assert read_prescription(prescription_id)["boxes_consumed"] == 0
        assert count_compliance_events(prescription_id, "ORDER_CANCELLED") == 1

    def test_deliver_before_ship_is_refused_and_leaves_the_claim_window_shut(self, api):
        """PRD §3.7: "Delivery then advances `SHIPPED` to the terminal
        `DELIVERED`, requires `shipped_at` to be present, and stamps
        `delivered_at` from the logical clock; `delivered_at` is what opens the
        reimbursement claim window."

        PRD §2.10: "On any action endpoint, the requested trigger is not
        declared for the target row's current state — including any attempt from
        a terminal state and any repeat of an already-applied trigger →
        `ERR_INVALID_STATE_TRANSITION` (409)."

        PRD §3.5: "An order also carries fields it does not yet use at creation:
        `substitution_type` starts at `NONE`, `parameter_deviation_index` starts
        at 0.00, `fulfilled_od_sphere` and `fulfilled_os_sphere` start null,
        `recall_flagged` starts false, and `cancellation_reason`, `shipped_at`
        and `delivered_at` start null."

        Design: Corner/state_machines/deliver_before_ship_returns_invalid_state_transition
        """
        scenario = setup_order_on_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        order_id = scenario["order"]["id"]

        validate_error(
            api.deliver_order(order_id, FO_HEADERS),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        order = read_order(order_id)
        assert order["fulfillment_state"] == "PENDING"
        assert order["shipped_at"] is None
        assert order["delivered_at"] is None

    def test_ship_of_an_rx_pending_order_is_refused_by_the_cleared_precondition(
        self, api
    ):
        """PRD §3.7: "A warehouse operator may advance an order from `PENDING`
        to `SHIPPED` only when its `verification_state` is `RX_CLEARED` — an
        order still `RX_PENDING` or already `RX_BLOCKED` cannot ship, and the
        attempt is reported as an undeclared transition — and only when the
        order's customer has no reorder hold in `OPEN` status, which is reported
        specifically as `ERR_HOLD_OPEN_BLOCKS_ACTION`."

        PRD §3.5: "An order also carries fields it does not yet use at creation:
        `substitution_type` starts at `NONE`, `parameter_deviation_index` starts
        at 0.00, `fulfilled_od_sphere` and `fulfilled_os_sphere` start null,
        `recall_flagged` starts false, and `cancellation_reason`, `shipped_at`
        and `delivered_at` start null."

        Design: Corner/state_machines/ship_of_an_rx_pending_order_is_rejected_by_the_cleared_precondition
        """
        scenario = setup_pending_verification_prescription(clock=WORKING_TUESDAY_10AM)
        order = new_order(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            1,
            1,
        )

        validate_error(
            api.ship_order(order["id"], FO_HEADERS),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        stored = read_order(order["id"])
        assert stored["fulfillment_state"] == "PENDING"
        assert stored["verification_state"] == "RX_PENDING"
        assert stored["shipped_at"] is None


class TestTerminalStateLockdown:
    """Terminal rows accept no further trigger, however it is dressed up."""

    def test_expired_prescription_refuses_a_new_verification_round(self, api):
        """PRD §3.4: "Every prescription then in `VERIFIED_ACTIVE` whose
        `expiry_date` is at or before the current logical date moves to the
        terminal `EXPIRED`."

        PRD §3.4: "A reorder hold is opened with `reason` `PRESCRIPTION_EXPIRED`
        in `OPEN` status and `opened_by_user_id` set to `system`."

        PRD §3.4: "The sweep returns a summary rather than a resource:
        `promoted_prescription_ids` lists the prescriptions promoted in step one,
        `timed_out_request_ids` the verification requests that timed out,
        `expired_prescription_ids` the prescriptions expired in step two, and
        `holds_opened_count` and `schedules_paused_count` the totals across both
        steps."

        PRD §3.3: "Once a prescription sits in `PENDING_VERIFICATION`, a
        compliance officer opens a verification round by naming the
        `prescriber_id` to contact."

        PRD §2.10: "On any action endpoint, the requested trigger is not
        declared for the target row's current state — including any attempt from
        a terminal state and any repeat of an already-applied trigger →
        `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Corner/state_machines/expired_prescription_is_terminal_and_rejects_a_new_verification_round
        """
        scenario = _setup_lapsed_prescription_swept_to_expired()
        prescription_id = scenario["prescription"]["id"]
        assert prescription_id in scenario["sweep"]["expired_prescription_ids"]
        assert scenario["sweep"]["holds_opened_count"] == 1

        validate_error(
            api.send_verification_request(
                prescription_id,
                {"prescriber_id": scenario["prescriber"]["id"]},
                CO_BRAVO_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        stored = read_prescription(prescription_id)
        assert stored["status"] == "EXPIRED"
        assert stored["verification_rounds"] == 0
        assert _verification_request_count(api, prescription_id) == 0

    def test_dismissed_dispute_cannot_be_resolved_a_second_time(self, api):
        """PRD §3.9: "Only a compliance officer or administrator resolves a
        dispute, supplying a `resolution` of `UPHELD` or `DISMISSED`."

        PRD §3.9: "Both branches set the dispute's `resolution` and
        `resolved_by_user_id` and append a `DISPUTE_RESOLVED` compliance event,
        and both are declared only from `OPEN`."

        PRD §3.9: "A dispute's `status` is `OPEN` and then one of the terminal
        values `UPHELD` or `DISMISSED`; disputes may be listed filtered by
        `prescription_id`, `prescriber_id` and `status`."

        PRD §2.10: "On any action endpoint, the requested trigger is not
        declared for the target row's current state — including any attempt from
        a terminal state and any repeat of an already-applied trigger →
        `ERR_INVALID_STATE_TRANSITION` (409)."

        PRD §3.9: "A `DISMISSED` resolution is otherwise a no-op: the
        prescription, its orders and its claims are left exactly as they were,
        no hold is opened, no ledger is touched."

        Design: Corner/state_machines/dismissed_dispute_cannot_be_resolved_a_second_time
        """
        scenario = setup_verified_prescription_with_prescriber(clock=DEFAULT_CLOCK_UTC)
        prescription_id = scenario["prescription"]["id"]
        dispute = file_prescriber_dispute(
            prescription_id,
            scenario["prescriber"]["id"],
            dispute_reason="NOT_MY_PATIENT",
        )
        resolve_prescriber_dispute(dispute["id"], "DISMISSED", actor=CO_ALPHA)

        validate_error(
            api.resolve_prescriber_dispute(
                dispute["id"], {"resolution": "UPHELD"}, CO_BRAVO_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        stored = validate_success(
            api.get_prescriber_dispute(dispute["id"], CO_ALPHA_HEADERS)
        )
        assert_prescriber_dispute(stored)
        assert stored["status"] == "DISMISSED"
        assert stored["resolution"] == "DISMISSED"
        assert stored["resolved_by_user_id"] == CO_ALPHA

        assert read_prescription(prescription_id)["status"] == "VERIFIED_ACTIVE"


class TestDismissedDisputeSideEffects:
    """Dismissal is the audit-only mirror image of the upheld cascade."""

    def test_dismissed_dispute_leaves_prescription_order_and_ledger_untouched(
        self, api
    ):
        """PRD §3.9: "Both branches set the dispute's `resolution` and
        `resolved_by_user_id` and append a `DISPUTE_RESOLVED` compliance event,
        and both are declared only from `OPEN`."

        PRD §3.9: "A `DISMISSED` resolution is otherwise a no-op: the
        prescription, its orders and its claims are left exactly as they were,
        no hold is opened, no ledger is touched."

        PRD §3.5: "An order also carries fields it does not yet use at creation:
        `substitution_type` starts at `NONE`, `parameter_deviation_index` starts
        at 0.00, `fulfilled_od_sphere` and `fulfilled_os_sphere` start null,
        `recall_flagged` starts false, and `cancellation_reason`, `shipped_at`
        and `delivered_at` start null."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        Design: Corner/state_machines/dismissed_dispute_leaves_prescription_orders_and_ledger_untouched
        """
        scenario = setup_verified_prescription_with_prescriber(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        order = new_order(
            customer_id, prescription_id, scenario["product"]["id"], 1, 1
        )
        dispute = file_prescriber_dispute(
            prescription_id,
            scenario["prescriber"]["id"],
            dispute_reason="PARAMETERS_ALTERED",
        )

        data = validate_success(
            api.resolve_prescriber_dispute(
                dispute["id"], {"resolution": "DISMISSED"}, CO_ALPHA_HEADERS
            ),
            200,
        )

        assert_prescriber_dispute(data)
        assert data["status"] == "DISMISSED"
        assert data["resolution"] == "DISMISSED"
        assert data["resolved_by_user_id"] == CO_ALPHA

        stored_prescription = read_prescription(prescription_id)
        assert stored_prescription["status"] == "VERIFIED_ACTIVE"
        assert stored_prescription["boxes_consumed"] == 2

        stored_order = read_order(order["id"])
        assert stored_order["fulfillment_state"] == "PENDING"
        assert stored_order["cancellation_reason"] is None
        assert stored_order["recall_flagged"] is False

        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_charged_cents=6400,
            net_cash_position_cents=6400,
        )

        assert count_compliance_events(prescription_id, "DISPUTE_RESOLVED") == 1
        assert count_compliance_events(prescription_id, "RX_INVALIDATED") == 0


class TestReturnSettlementSideEffects:
    """Settlement is where a return's frozen figure actually moves money."""

    def test_settle_pays_cash_refund_and_offsets_the_draft_claim(self, api):
        """PRD §3.8: "A return's `status` starts at `SUBMITTED` and ends in
        `REJECTED` or `SETTLED`."

        PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."

        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS`
        and `CASH_REFUND` for the other two reasons — a torn lens is a
        replacement matter, not a refund matter."

        PRD §3.8: "Under both prorating variants, the unopened component is
        `unopened_boxes` multiplied by the per-box value, and the opened
        component values each opened box by the lenses left unused in it, as a
        fraction of a whole box."

        PRD §3.8: "For both prorating variants, `settlement_cents` is the
        unopened component plus the opened component."

        PRD §2.8: "Settling a return request requires an `X-User-ID` different
        from the request's `approved_by_user_id`."

        PRD §3.8: "Settlement records `settled_by_user_id`, and this is where
        money actually moves: a `STORE_CREDIT` settlement credits the customer's
        `store_credit_cents`, while a `CASH_REFUND` settlement increases
        `lifetime_refunded_cents`, and either way `net_cash_position_cents` is
        then reconciled."

        PRD §3.8: "Settlement also reaches into any reimbursement paperwork
        still in progress: `refund_offset_cents` is set on every claim on that
        order whose `status` is `DRAFT`, so a claim generated afterwards cannot
        ask the plan to reimburse money the platform has already returned."

        Design: Corner/state_machines/settle_pays_cash_refund_and_stamps_refund_offset_on_the_draft_claim
        """
        scenario = setup_approved_return(
            reason="PRESCRIPTION_CHANGE",
            return_overrides={"unopened_boxes": 1},
            approver=CO_ALPHA,
            with_claim=True,
            clock=DEFAULT_CLOCK_UTC,
        )
        customer_id = scenario["customer"]["id"]

        data = validate_success(
            api.settle_return_request(
                scenario["return_request"]["id"], CO_BRAVO_HEADERS
            ),
            200,
        )

        assert_return_request(data)
        assert data["status"] == "SETTLED"
        assert data["settlement_mode"] == "PER_BOX_ROUNDED"
        assert data["settlement_cents"] == 3200
        assert data["settlement_channel"] == "CASH_REFUND"
        assert data["approved_by_user_id"] == CO_ALPHA
        assert data["settled_by_user_id"] == CO_BRAVO

        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_charged_cents=6400,
            lifetime_refunded_cents=3200,
            net_cash_position_cents=3200,
            store_credit_cents=0,
        )

        claim = validate_success(
            api.get_reimbursement_claim(scenario["claim"]["id"], CO_ALPHA_HEADERS)
        )
        assert claim["status"] == "DRAFT"
        assert claim["refund_offset_cents"] == 3200
