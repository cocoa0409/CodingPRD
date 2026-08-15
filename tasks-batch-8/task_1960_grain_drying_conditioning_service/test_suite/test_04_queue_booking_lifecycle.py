"""Queue-ticket booking lifecycle: creation, confirmation gates, preemption,
requeue, expiry, suspension, and credit headroom (PRD §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_queue_ticket,
    capacity_calendar,
    certify_test,
    confirm_ticket,
    create_customer,
    create_lot,
    create_moisture_test,
    create_queued_lot,
    create_tested_lot,
    create_ticket,
    get_lot,
    get_ticket,
    make_grower_headers,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
)


class TestTicketCreation:
    def test_ticket_initial_state_pending(self, api, manager_headers):
        """PRD §3.4: "A new ticket is `PENDING`; its `priority_class` is copied
        from the customer's at creation and never changes, and its
        `preemption_count` starts at zero."

        Design: Corner/state_machines/ticket_initial_state_pending
        """
        ctx = setup_base()
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        res = api.create_queue_ticket(
            {"lot_id": lot["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-12", "requested_bushels": 200},
            # booking by the owning grower
            make_grower_headers(ctx["cust"]["id"]),
        )
        ticket = validate_success(res, 201)
        assert_queue_ticket(ticket)
        assert ticket["status"] == "PENDING"
        assert ticket["priority_class"] == "STANDARD"
        assert ticket["preemption_count"] == 0
        # PENDING holds no capacity and does not move the lot.
        assert get_lot(lot["id"])["status"] == "TESTED"

    def test_ticket_window_in_past_rejected(self, api, manager_headers):
        """PRD §3.4: "The date must not be in the past and the bushel count must
        be positive; violations are rejected with `ERR_TICKET_WINDOW_INVALID`
        (HTTP 422)."

        Design: Corner/validations/ticket_window_in_past_rejected
        """
        ctx = setup_base()
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        set_clock("2026-09-10T08:00:00Z")
        res = api.create_queue_ticket(
            {"lot_id": lot["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-09", "requested_bushels": 200},
            make_grower_headers(ctx["cust"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TICKET_WINDOW_INVALID, expected_status=422)


class TestConfirmRequiresTestedLot:
    def test_confirm_rejected_while_lot_received(self, api, manager_headers):
        """PRD §3.4: "The lot must be `RECEIVED` or `TESTED` — creation does not
        require the lot to be `TESTED`; confirmation does."
        PRD §3.4: "The ticket must be `PENDING` and its lot `TESTED` — anything
        else is `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/ticket_confirm_requires_lot_tested
        """
        ctx = setup_base()
        lot = create_lot(ctx["cust"]["id"])  # stays RECEIVED
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12")
        res = api.confirm_queue_ticket(ticket["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_ticket(ticket["id"])["status"] == "PENDING"

    def test_confirm_succeeds_after_certification(self, api, manager_headers):
        """PRD §3.4: "A confirmed ticket moves `PENDING` → `CONFIRMED`, moves its
        lot `TESTED` → `QUEUED`, and adds its `requested_bushels` to the
        committed capacity of that unit on that date."

        Design: Difficulty/cross_entity_state_dependency/ticket_confirm_requires_lot_tested
        """
        ctx = setup_base()
        lot = create_lot(ctx["cust"]["id"])
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12")
        # Certification moves the lot RECEIVED -> TESTED without touching the ticket.
        test = create_moisture_test(lot["id"], 20.0, tech_id="tech-1")
        certify_test(test["id"], tech_id="tech-1")
        confirmed = validate_success(
            api.confirm_queue_ticket(ticket["id"], manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_lot(lot["id"])["status"] == "QUEUED"


class TestPreemptRequeueCycle:
    def test_preempt_releases_capacity_and_reverts_lot(self, api, manager_headers):
        """PRD §3.4: "Preemption moves the ticket `CONFIRMED` → `PREEMPTED`,
        releases its committed capacity, returns its lot `QUEUED` → `TESTED`,
        and increments the ticket's `preemption_count`."

        Design: Difficulty/non_linear_state_machine/queue_ticket_preempt_requeue_cycle
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-12",
            requested_bushels=1500, sample_moisture_pct=20.0)
        res = api.preempt_queue_ticket(ticket["id"], manager_headers)
        preempted = validate_success(res, 200)
        assert preempted["status"] == "PREEMPTED"
        assert preempted["preemption_count"] == 1
        assert get_lot(lot["id"])["status"] == "TESTED"

    def test_requeue_then_reconfirm_closes_cycle(self, api, manager_headers):
        """PRD §3.4: "A preempted ticket is not dead: while its
        `preemption_count` is below two, a `Grower` (own tickets) or
        `ElevatorManager` may requeue it, `PREEMPTED` → `PENDING`, after which it
        must be confirmed anew with every gate re-evaluated."

        Design: Difficulty/non_linear_state_machine/queue_ticket_preempt_requeue_cycle
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-12",
            requested_bushels=1500, sample_moisture_pct=20.0)
        api.preempt_queue_ticket(ticket["id"], manager_headers)
        requeued = validate_success(
            api.requeue_queue_ticket(ticket["id"], manager_headers), 200)
        assert requeued["status"] == "PENDING"
        confirmed = validate_success(
            api.confirm_queue_ticket(ticket["id"], manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["preemption_count"] == 1
        assert get_lot(lot["id"])["status"] == "QUEUED"


class TestPreemptEligibility:
    def test_preempt_priority_ticket_rejected(self, api, manager_headers):
        """PRD §3.4: "Only a `CONFIRMED` ticket of `STANDARD` class may be
        preempted; any other target is rejected with
        `ERR_PREEMPTION_NOT_ALLOWED` (HTTP 422)."

        Design: Corner/validations/preempt_priority_ticket_rejected
        """
        ctx = setup_base(customer_overrides={"priority_class": "PRIORITY_CONTRACT"})
        _lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-12",
            requested_bushels=200, sample_moisture_pct=20.0)
        assert get_ticket(ticket["id"])["priority_class"] == "PRIORITY_CONTRACT"
        res = api.preempt_queue_ticket(ticket["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_PREEMPTION_NOT_ALLOWED, expected_status=422)
        assert get_ticket(ticket["id"])["status"] == "CONFIRMED"


class TestTicketExpiry:
    def test_ticket_expiry_on_clock_advance(self, api, manager_headers):
        """PRD §2.4: "Advancing the clock past a PENDING queue ticket's
        `window_date` expires the ticket — its status becomes EXPIRED with no
        further effect."
        PRD §2.5: "Once a resource reaches a terminal state, further transition
        attempts on it are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/ticket_expiry_on_clock_advance
        """
        ctx = setup_base()
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-03")
        set_clock("2026-09-04T00:00:00Z")
        assert get_ticket(ticket["id"])["status"] == "EXPIRED"
        res = api.confirm_queue_ticket(ticket["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)


class TestFiscalGates:
    def test_suspended_customer_confirm_rejected(self, api, manager_headers):
        """PRD §3.1: "A `SUSPENDED` account cannot book new dryer time and cannot
        have pending bookings confirmed: both attempts are rejected with
        `ERR_CUSTOMER_SUSPENDED` (HTTP 422)."

        Design: Corner/validations/suspended_customer_confirm_rejected
        """
        ctx = setup_base()
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12")
        validate_success(api.update_customer(
            ctx["cust"]["id"], {"account_status": "SUSPENDED"}, manager_headers), 200)
        res = api.confirm_queue_ticket(ticket["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SUSPENDED, expected_status=422)
        assert get_ticket(ticket["id"])["status"] == "PENDING"

    def test_credit_limit_boundary_estimate_equal_allowed_less_rejected(self, api, manager_headers):
        """PRD §3.1: "Confirming a queue ticket estimates the drying charge for
        the ticket's lot and requires that this estimate plus the account's
        outstanding dues across ISSUED invoices stay within `credit_limit_cents`;
        a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/credit_limit_boundary_estimate_equal_allowed_less_rejected
        """
        ctx = setup_base(with_schedule=True)
        # 5600-lb lot @20.0 target 15.0 -> 100 bu * 5 pt * 4c = 2000c estimate.
        cust_a = create_customer(name="CA", credit_limit_cents=2000)
        cust_b = create_customer(name="CB", credit_limit_cents=1999)
        lot_a, _ = create_tested_lot(cust_a["id"], sample_moisture_pct=20.0,
                                     gross_weight_lbs=39600, tare_weight_lbs=34000,
                                     foreign_material_pct=2.0)
        lot_b, _ = create_tested_lot(cust_b["id"], sample_moisture_pct=20.0,
                                     gross_weight_lbs=39600, tare_weight_lbs=34000,
                                     foreign_material_pct=2.0)
        ticket_a = validate_success(api.create_queue_ticket(
            {"lot_id": lot_a["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-12", "requested_bushels": 100},
            make_grower_headers(cust_a["id"])), 201)
        ticket_b = validate_success(api.create_queue_ticket(
            {"lot_id": lot_b["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-12", "requested_bushels": 100},
            make_grower_headers(cust_b["id"])), 201)

        ok = api.confirm_queue_ticket(ticket_a["id"], manager_headers)
        assert validate_success(ok, 200)["status"] == "CONFIRMED"  # 2000 <= 2000
        res = api.confirm_queue_ticket(ticket_b["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=422)
        assert get_ticket(ticket_b["id"])["status"] == "PENDING"


class TestImmediateConsistency:
    def test_immediate_visibility_after_confirm(self, api, manager_headers):
        """PRD §1: "The system's consistency model is immediate: every mutation
        is visible in its own response, and all derived fields are recomputed
        synchronously as part of the operation that triggers them."
        PRD §3.4: "A confirmed ticket moves `PENDING` → `CONFIRMED`, moves its
        lot `TESTED` → `QUEUED`, and adds its `requested_bushels` to the
        committed capacity of that unit on that date."

        Design: Corner/consistency_model/immediate_visibility_after_confirm
        """
        ctx = setup_base()
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12",
                               requested_bushels=200)
        confirmed = validate_success(
            api.confirm_queue_ticket(ticket["id"], manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_lot(lot["id"])["status"] == "QUEUED"
        cal = capacity_calendar(ctx["unit"]["id"], "2026-09-12")
        assert cal["total_committed_bushels"] == 200
