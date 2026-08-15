"""Daily capacity allocation: class caps, aggregate totals, preemption-driven
reallocation, compensating cancel, and pinned validation ordering (PRD §3.4,
§2.9)."""
from test_helpers import (
    ApiErrorId,
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
    setup_base,
    validate_error,
    validate_success,
)


class TestCapacityEqualityBoundary:
    """Standard cap 8000 with <= comparison: 8000 confirms, 8001 rejects."""

    def _setup_two_4000_tickets(self):
        ctx = setup_base()
        lot_a, _ta, ticket_a = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-12",
            requested_bushels=4000, sample_moisture_pct=20.0)
        lot_b, _tb, ticket_b = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-12",
            requested_bushels=4000, sample_moisture_pct=20.0)
        lot_c, _tc = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        ticket_c = create_ticket(lot_c, ctx["unit"]["id"], window_date="2026-09-12",
                                 requested_bushels=1)
        return ctx, ticket_a, ticket_b, ticket_c

    def test_committed_exactly_at_cap_confirms(self, api, manager_headers):
        """PRD §3.4: "A `STANDARD` ticket may confirm only if the committed
        `STANDARD` total plus its request stays at or below
        `standard_class_cap_bushels` — equality at the cap is allowed — and the
        all-class committed total plus its request stays at or below
        `daily_capacity_bushels`."
        PRD §3.4: "The per-day position is readable as a capacity calendar:
        given a `date`, it returns the `unit_id`, the `date`, the unit's
        `daily_capacity_bushels`, `standard_committed_bushels`,
        `total_committed_bushels`, and the derived `standard_remaining_bushels`
        and `total_remaining_bushels`."

        Design: Difficulty/boundary_precision_check/capacity_equality_allowed_plus_one_rejected
        """
        ctx, _ta, ticket_b, _tc = self._setup_two_4000_tickets()
        # Second ticket brings committed to exactly 4000 + 4000 == 8000 == cap.
        assert ticket_b["status"] == "CONFIRMED"
        cal = capacity_calendar(ctx["unit"]["id"], "2026-09-12")
        assert cal["standard_committed_bushels"] == 8000
        assert cal["standard_remaining_bushels"] == 0

    def test_one_bushel_over_cap_rejected(self, api, manager_headers):
        """PRD §3.4: "A breach of either ceiling is `ERR_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/capacity_equality_allowed_plus_one_rejected
        """
        ctx, _ta, _tb, ticket_c = self._setup_two_4000_tickets()
        res = api.confirm_queue_ticket(ticket_c["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=422)
        assert get_ticket(ticket_c["id"])["status"] == "PENDING"


class TestAggregateCapacityAndPreemption:
    """Class caps aggregate per (unit, date); preemption reallocates."""

    def test_priority_confirm_over_total_cap_rejected(self, api, manager_headers):
        """PRD §3.4: "`PRIORITY_CONTRACT` tickets bypass the standard cap but
        still count toward the daily total."
        PRD §3.4: "A breach of either ceiling is `ERR_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/queue_daily_capacity_aggregate_preemption
        """
        ctx = setup_base()
        cust_p = create_customer(name="CP", priority_class="PRIORITY_CONTRACT")
        _ls1, _t1, _tick_s1 = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-15",
            requested_bushels=4000, sample_moisture_pct=20.0)
        _ls2, _t2, _tick_s2 = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-15",
            requested_bushels=4000, sample_moisture_pct=20.0)
        cal = capacity_calendar(ctx["unit"]["id"], "2026-09-15")
        assert cal["standard_committed_bushels"] == 8000
        assert cal["total_committed_bushels"] == 8000

        lot_p, _tp = create_tested_lot(cust_p["id"], sample_moisture_pct=20.0)
        tick_p = validate_success(api.create_queue_ticket(
            {"lot_id": lot_p["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-15", "requested_bushels": 2500},
            make_grower_headers(cust_p["id"])), 201)
        assert tick_p["priority_class"] == "PRIORITY_CONTRACT"  # copied from customer
        # 8000 + 2500 = 10500 > 10000 daily total cap.
        res = api.confirm_queue_ticket(tick_p["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=422)

    def test_preemption_frees_capacity_for_priority_confirm(self, api, manager_headers):
        """PRD §3.4: "Preemption moves the ticket `CONFIRMED` → `PREEMPTED`,
        releases its committed capacity, returns its lot `QUEUED` → `TESTED`,
        and increments the ticket's `preemption_count`."
        PRD §3.4: "Committed bushels are the sum of `requested_bushels` over the
        unit-date's `CONFIRMED` tickets; a ticket `CONSUMED` by an executing run
        still occupies its day, while `PENDING`, `PREEMPTED`, `CANCELLED`, and
        `EXPIRED` tickets hold nothing."

        Design: Difficulty/resource_temporal_overlap/queue_daily_capacity_aggregate_preemption
        """
        ctx = setup_base()
        cust_p = create_customer(name="CP", priority_class="PRIORITY_CONTRACT")
        _ls1, _t1, _tick_s1 = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-15",
            requested_bushels=4000, sample_moisture_pct=20.0)
        _ls2, _t2, tick_s2 = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-15",
            requested_bushels=4000, sample_moisture_pct=20.0)
        lot_p, _tp = create_tested_lot(cust_p["id"], sample_moisture_pct=20.0)
        tick_p = validate_success(api.create_queue_ticket(
            {"lot_id": lot_p["id"], "unit_id": ctx["unit"]["id"],
             "window_date": "2026-09-15", "requested_bushels": 2500},
            make_grower_headers(cust_p["id"])), 201)

        preempted = validate_success(
            api.preempt_queue_ticket(tick_s2["id"], manager_headers), 200)
        assert preempted["status"] == "PREEMPTED"

        confirmed = validate_success(
            api.confirm_queue_ticket(tick_p["id"], manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        cal = capacity_calendar(ctx["unit"]["id"], "2026-09-15")
        assert cal["standard_committed_bushels"] == 4000
        assert cal["total_committed_bushels"] == 6500


class TestConfirmCancelConservation:
    def test_confirm_commits_bushels(self, api, manager_headers):
        """PRD §3.4: "A confirmed ticket moves `PENDING` → `CONFIRMED`, moves its
        lot `TESTED` → `QUEUED`, and adds its `requested_bushels` to the
        committed capacity of that unit on that date."

        Design: Difficulty/compensating_invariant/queue_confirm_cancel_capacity_conservation
        """
        ctx = setup_base()
        lot, _t = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=20.0)
        baseline = capacity_calendar(ctx["unit"]["id"], "2026-09-20")
        assert baseline["total_committed_bushels"] == 0
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-20",
                               requested_bushels=1500)
        confirm_ticket(ticket["id"])
        after = capacity_calendar(ctx["unit"]["id"], "2026-09-20")
        assert after["total_committed_bushels"] == 1500

    def test_cancel_restores_capacity_baseline(self, api, manager_headers):
        """PRD §3.4: "Cancelling a `CONFIRMED` ticket releases its committed
        capacity and returns the lot `QUEUED` → `TESTED`."
        PRD §3.4: "Committed bushels are the sum of `requested_bushels` over the
        unit-date's `CONFIRMED` tickets; a ticket `CONSUMED` by an executing run
        still occupies its day, while `PENDING`, `PREEMPTED`, `CANCELLED`, and
        `EXPIRED` tickets hold nothing."

        Design: Difficulty/compensating_invariant/queue_confirm_cancel_capacity_conservation
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-20",
            requested_bushels=1500, sample_moisture_pct=20.0)
        cancelled = validate_success(
            api.cancel_queue_ticket(ticket["id"], manager_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        after = capacity_calendar(ctx["unit"]["id"], "2026-09-20")
        assert after["total_committed_bushels"] == 0  # no capacity drift
        assert get_lot(lot["id"])["status"] == "TESTED"


class TestValidationOrderingAtConfirm:
    def test_state_beats_fiscal_on_ticket_confirm(self, api, manager_headers):
        """PRD §2.9: "Requests are validated in a fixed order, and a failure at
        an earlier gate masks every later one — a request never reports a
        business-rule violation it would also have failed on authentication."
        PRD §2.9: "6. State permission — the target resource must be in a state
        permitting the operation"
        PRD §2.9: "12. Fiscal gates — suspension (`ERR_CUSTOMER_SUSPENDED`),
        credit headroom (`ERR_CREDIT_LIMIT_EXCEEDED`), payment size
        (`ERR_PAYMENT_EXCEEDS_DUE`), and billable content
        (`ERR_NO_BILLABLE_ACTIVITY`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_ticket_confirm
        """
        ctx = setup_base()
        lot = create_lot(ctx["cust"]["id"])  # RECEIVED: state gate will fail
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12")
        validate_success(api.update_customer(
            ctx["cust"]["id"], {"account_status": "SUSPENDED"}, manager_headers), 200)
        res = api.confirm_queue_ticket(ticket["id"], manager_headers)
        # State (gate 6) masks fiscal suspension (gate 12).
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_fiscal_gate_surfaces_once_state_fixed(self, api, manager_headers):
        """PRD §2.9: "Requests are validated in a fixed order, and a failure at
        an earlier gate masks every later one — a request never reports a
        business-rule violation it would also have failed on authentication."
        PRD §3.1: "A `SUSPENDED` account cannot book new dryer time and cannot
        have pending bookings confirmed: both attempts are rejected with
        `ERR_CUSTOMER_SUSPENDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_ticket_confirm
        """
        ctx = setup_base()
        lot = create_lot(ctx["cust"]["id"])
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-12")
        validate_success(api.update_customer(
            ctx["cust"]["id"], {"account_status": "SUSPENDED"}, manager_headers), 200)
        # Remove the state failure: certify so the lot becomes TESTED.
        test = create_moisture_test(lot["id"], 20.0, tech_id="tech-1")
        certify_test(test["id"], tech_id="tech-1")
        res = api.confirm_queue_ticket(ticket["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SUSPENDED, expected_status=422)
        assert get_ticket(ticket["id"])["status"] == "PENDING"

    def test_safety_beats_capacity_on_ticket_confirm(self, api, manager_headers):
        """PRD §2.9: "Requests are validated in a fixed order, and a failure at
        an earlier gate masks every later one — a request never reports a
        business-rule violation it would also have failed on authentication."
        PRD §2.9: "9. Dryer safety — the 26.0-percent intake-moisture limit
        (`ERR_MOISTURE_EXCEEDS_DRYER_LIMIT`)."
        PRD §2.9: "11. Capacity and time-window rules — daily class and total
        capacity (`ERR_CAPACITY_EXCEEDED`), preemption eligibility
        (`ERR_PREEMPTION_NOT_ALLOWED`), and claims filed after delivery
        (`ERR_CLAIM_AFTER_DELIVERY`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_capacity_on_ticket_confirm
        """
        ctx = setup_base()
        # Fill the 2026-09-10 standard class cap exactly (8000).
        _lot_x, _tx, _tick_x = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-10",
            requested_bushels=8000, sample_moisture_pct=20.0)
        # Second lot certified at 27.0% — over the 26.0 dryer safety limit.
        lot_y, _ty = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=27.0)
        tick_y = create_ticket(lot_y, ctx["unit"]["id"], window_date="2026-09-10",
                               requested_bushels=100)
        res = api.confirm_queue_ticket(tick_y["id"], manager_headers)
        # Safety (gate 9) masks the capacity breach (gate 11).
        validate_error(res, ApiErrorId.ERR_MOISTURE_EXCEEDS_DRYER_LIMIT,
                       expected_status=422)

    def test_capacity_unchanged_after_masked_rejection(self, api, manager_headers):
        """PRD §3.4: "The lot's `intake_moisture_pct` must be at most 26.0
        percent — the dryer safety limit — or `ERR_MOISTURE_EXCEEDS_DRYER_LIMIT`
        (HTTP 422)."
        PRD §3.4: "A confirmed ticket moves `PENDING` → `CONFIRMED`, moves its
        lot `TESTED` → `QUEUED`, and adds its `requested_bushels` to the
        committed capacity of that unit on that date."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_capacity_on_ticket_confirm
        """
        ctx = setup_base()
        _lot_x, _tx, _tick_x = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-10",
            requested_bushels=8000, sample_moisture_pct=20.0)
        lot_y, _ty = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=27.0)
        tick_y = create_ticket(lot_y, ctx["unit"]["id"], window_date="2026-09-10",
                               requested_bushels=100)
        validate_error(
            api.confirm_queue_ticket(tick_y["id"], manager_headers),
            ApiErrorId.ERR_MOISTURE_EXCEEDS_DRYER_LIMIT, expected_status=422)
        # Rejected confirm commits nothing and leaves the ticket PENDING.
        assert get_ticket(tick_y["id"])["status"] == "PENDING"
        cal = capacity_calendar(ctx["unit"]["id"], "2026-09-10")
        assert cal["standard_committed_bushels"] == 8000
        assert cal["standard_remaining_bushels"] == 0
