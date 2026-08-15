"""Shower/laundry queue: FIFO positions, no-show requeue cycle, capacity with
overstay preemption, water metering, and cash payment attribution."""
import pytest

from test_helpers import (
    ApiErrorId,
    set_clock,
    setup_shift_site,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.factories import service_pay_payload
from test_helpers.fixtures import (
    CASH_1,
    GM,
    SM_2,
    call_queue,
    create_service_ticket,
    reload_shift,
    reload_site,
    start_ticket,
)


def _setup_three_shower_tickets():
    ctx = setup_shift_site("Site G", shower_units_count=1,
                           laundry_machines_count=1, clock=TEST_CLOCK_ISO)
    tickets = [
        create_service_ticket(ctx.site["id"], "SHOWER", shift_id=ctx.shift["id"])
        for _ in range(3)
    ]
    return ctx, tickets


class TestNoShowRequeueCycle:
    def test_queue_positions_and_fifo_call_order(self, api):
        """PRD section 3.5: "`queue_position` is one plus the current maximum
        `queue_position` among all tickets ever created at this site for this
        service type" and "among `QUEUED` tickets of that type at that site,
        the lowest `queue_position` is selected and moves `QUEUED → CALLED`,
        stamping `called_at`".
        PRD section 3.5: "a `NO_SHOW` ticket may be requeued — `NO_SHOW →
        QUEUED` — which sends it to the back with a fresh `queue_position` of
        one plus the lane's current maximum".

        Design: Difficulty/non_linear_state_machine/service_ticket_no_show_requeue_cycle
        """
        ctx, (t1, t2, t3) = _setup_three_shower_tickets()
        assert (t1["queue_position"], t2["queue_position"],
                t3["queue_position"]) == (1, 2, 3)

        call1 = call_queue(ctx.site["id"], "SHOWER")
        call2 = call_queue(ctx.site["id"], "SHOWER")
        assert call1["id"] == t1["id"]
        assert call2["id"] == t2["id"]

        validate_success(api.service_ticket_no_show(t1["id"], CASH_1))
        requeued = validate_success(api.service_ticket_requeue(t1["id"], CASH_1))
        assert requeued["status"] == "QUEUED"
        assert requeued["queue_position"] == 4, "requeued to the back (max+1)"

        call3 = call_queue(ctx.site["id"], "SHOWER")
        assert call3["id"] == t3["id"], "position 3 is called before position 4"

    def test_requeued_ticket_completes_full_loop(self, api):
        """PRD section 3.5: "a `NO_SHOW` ticket may be requeued — `NO_SHOW →
        QUEUED` — which sends it to the back with a fresh `queue_position` of
        one plus the lane's current maximum" and "Completion moves `ACTIVE →
        COMPLETED` and stamps `completed_at`."
        PRD section 3.5: "a shower meters 2.5 gallons per minute under water,
        with any time beyond the 45-minute cap counted only up to the cap".

        Design: Difficulty/non_linear_state_machine/service_ticket_no_show_requeue_cycle
        """
        ctx, (t1, _, t3) = _setup_three_shower_tickets()
        call_queue(ctx.site["id"], "SHOWER")
        call_queue(ctx.site["id"], "SHOWER")
        validate_success(api.service_ticket_no_show(t1["id"], CASH_1))
        validate_success(api.service_ticket_requeue(t1["id"], CASH_1))
        call_queue(ctx.site["id"], "SHOWER")

        start_ticket(t3["id"])
        completed = validate_success(
            api.service_ticket_complete(t3["id"], {"shower_minutes": 20}, CASH_1)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["water_gallons"] == pytest.approx(50.0)  # 20 x 2.5


class TestWaterMetering:
    def test_water_usage_shower_cap_and_laundry(self, api):
        """PRD section 3.5: "a shower meters 2.5 gallons per minute under
        water, with any time beyond the 45-minute cap counted only up to the
        cap; laundry meters 2.0 gallons per pound washed" and "Water usage is
        computed at completion, recorded on the ticket as `water_gallons`,
        and folded into the site's running `water_usage_gallons` at
        two-decimal precision".

        Design: Corner/calculations/calc_water_usage_shower_cap_and_laundry
        """
        ctx = setup_shift_site("Site C1", shower_units_count=1,
                               laundry_machines_count=1, clock=TEST_CLOCK_ISO)
        t1 = create_service_ticket(ctx.site["id"], "SHOWER",
                                   shift_id=ctx.shift["id"])
        t2 = create_service_ticket(ctx.site["id"], "LAUNDRY",
                                   shift_id=ctx.shift["id"])
        call_queue(ctx.site["id"], "SHOWER")
        start_ticket(t1["id"])
        call_queue(ctx.site["id"], "LAUNDRY")
        start_ticket(t2["id"])

        shower = validate_success(
            api.service_ticket_complete(t1["id"], {"shower_minutes": 120}, CASH_1)
        )
        assert shower["water_gallons"] == pytest.approx(112.5)  # min(120,45) x 2.5

        laundry = validate_success(
            api.service_ticket_complete(t2["id"], {"laundry_lbs": 12}, CASH_1)
        )
        assert laundry["water_gallons"] == pytest.approx(24.0)  # 12 x 2.0

        site_now = reload_site(ctx.site["id"])
        assert site_now["water_usage_gallons"] == pytest.approx(136.5)


class TestQueueCapacityAndPreemption:
    def test_queue_call_empty_rejected(self, api):
        """PRD section 3.5: "among `QUEUED` tickets of that type at that
        site, the lowest `queue_position` is selected and moves `QUEUED →
        CALLED`, stamping `called_at`; an empty pool is `ERR_QUEUE_EMPTY`
        (HTTP 422)".

        Design: Corner/errors/error_queue_empty_call
        """
        ctx = setup_shift_site("Site R6", clock=TEST_CLOCK_ISO)
        resp = api.call_service_queue(ctx.site["id"], {"service_type": "SHOWER"},
                                      CASH_1)
        validate_error(resp, ApiErrorId.ERR_QUEUE_EMPTY)

    def test_queue_capacity_then_preemption_after_15_min(self, api):
        """PRD section 3.5: "it is preemptable only once it has run for at
        least 15 minutes" and "When no ticket is preemptable, the start fails
        with `ERR_QUEUE_CAPACITY` (HTTP 422)." and "a preempted ticket
        cascades `ACTIVE → NO_SHOW`, forfeiting its place".

        Design: Corner/errors/error_queue_capacity_then_preemption_after_15_min
        """
        ctx = setup_shift_site("Site R9", shower_units_count=1,
                               clock=TEST_CLOCK_ISO)
        t1 = create_service_ticket(ctx.site["id"], "SHOWER",
                                   shift_id=ctx.shift["id"])
        t2 = create_service_ticket(ctx.site["id"], "SHOWER",
                                   shift_id=ctx.shift["id"])
        call_queue(ctx.site["id"], "SHOWER")
        start_ticket(t1["id"])  # ACTIVE at 10:00
        call_queue(ctx.site["id"], "SHOWER")

        blocked = api.service_ticket_start(t2["id"], CASH_1)
        validate_error(blocked, ApiErrorId.ERR_QUEUE_CAPACITY)

        set_clock("2026-08-12T10:16:00Z")
        started = validate_success(api.service_ticket_start(t2["id"], CASH_1))
        assert started["status"] == "ACTIVE"

        t1_now = validate_success(api.get_service_ticket(t1["id"], GM))
        assert t1_now["status"] == "NO_SHOW", "overstay occupant preempted"


class TestServicePayment:
    def test_service_pay_cash_shift_attribution(self, api):
        """PRD section 3.5: "the `base_price_cents` is 1500 for a shower and
        400 for laundry; a ticket created on a Saturday or Sunday (UTC) adds
        a 300-cent `weekend_surcharge_cents`; one created with its time of
        day inside the 17:00–22:00 UTC window adds a 150-cent
        `peak_surcharge_cents`" and "a `CASH` tender is attributed to the
        effective shift — the payload's `shift_id` when supplied, otherwise
        the ticket's attribution shift — which must be `OPEN`, growing its
        expected cash by `total_price_cents` and recomputing posture".

        Design: Corner/endpoints/endpoint_service_pay_cash_shift_attribution
        """
        ctx = setup_shift_site("Site E4", clock=TEST_CLOCK_ISO)
        ticket = create_service_ticket(ctx.site["id"], "SHOWER",
                                       shift_id=ctx.shift["id"])
        call_queue(ctx.site["id"], "SHOWER")

        paid = validate_success(
            api.service_ticket_pay(
                ticket["id"],
                service_pay_payload("CASH", shift_id=ctx.shift["id"]),
                CASH_1,
            )
        )
        # Wednesday 10:00 UTC: neither weekend nor peak -> base price only
        assert paid["total_price_cents"] == 1500
        assert paid["payment_status"] == "PAID"

        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 21500
