"""Certified scale tolls and conservation, plus store-sale stock and points
round-tripping."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_store_sale_payload,
    setup_shift_site,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.factories import store_sale_refund_payload
from test_helpers.fixtures import (
    CASH_1,
    GM,
    SM_2,
    create_member,
    create_scale_ticket,
    create_stock_item,
    record_weigh,
    reload_shift,
    reload_stock_item,
    settle_ticket,
)
from test_helpers.fixtures import reload_member


class TestScaleSettlePreconditions:
    def test_scale_settle_requires_gross_and_tare(self, api):
        """PRD section 3.5: "Settlement moves `OPEN → PAID` and requires at
        least one `GROSS` and at least one `TARE` event on the ticket, else
        `ERR_SCALE_NOT_CERTIFIABLE` (HTTP 422). The toll is a 1250-cent
        first-weigh fee plus a 400-cent certified fee when `certified` is
        true; reweighs are always free."

        Design: Corner/state_machines/sm_scale_settle_requires_gross_and_tare
        """
        ctx = setup_shift_site("Site S5", clock=TEST_CLOCK_ISO)
        ticket = create_scale_ticket(ctx, certified=False,
                                     vehicle_plate="TRK-7", carrier_name="Acme")
        record_weigh(ticket["id"], "GROSS", 80000)

        early = api.scale_ticket_settle(ticket["id"], {"tender_type": "CASH"},
                                        CASH_1)
        validate_error(early, ApiErrorId.ERR_SCALE_NOT_CERTIFIABLE)

        record_weigh(ticket["id"], "TARE", 28000)
        settled = settle_ticket(ticket["id"], "CASH")
        assert settled["status"] == "PAID"
        assert settled["total_paid_cents"] == 1250  # certified false adds 0


class TestScaleTollConservation:
    def _setup_weighed_ticket(self):
        ctx = setup_shift_site("Site R", clock=TEST_CLOCK_ISO)
        ticket = create_scale_ticket(ctx, certified=True)
        record_weigh(ticket["id"], "GROSS", 80000)
        record_weigh(ticket["id"], "TARE", 28000)
        record_weigh(ticket["id"], "REWEIGH", 80500)
        return ctx, ticket

    def test_settle_charges_first_weigh_plus_certified_only(self, api):
        """PRD section 3.5: "The toll is a 1250-cent first-weigh fee plus a
        400-cent certified fee when `certified` is true; reweighs are always
        free." and "A `GROSS` or `REWEIGH` event refreshes the ticket's
        `gross_lbs`, a `TARE` refreshes `tare_lbs`, `net_lbs` is `gross_lbs`
        minus `tare_lbs` once both are present, and every `REWEIGH`
        increments `reweigh_count`."
        PRD section 3.5: "a cash settlement attributes it to the ticket's
        `OPEN` shift, growing expected cash and recomputing posture".

        Design: Difficulty/compensating_invariant/scale_toll_ledger_conservation
        """
        ctx, ticket = self._setup_weighed_ticket()
        settled = settle_ticket(ticket["id"], "CASH")
        assert settled["status"] == "PAID"
        assert settled["total_paid_cents"] == 1650  # 1250 + 400; REWEIGH free
        assert settled["reweigh_count"] == 1
        assert settled["net_lbs"] == 52500  # last gross 80500 - tare 28000
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 21650

    def test_paid_cancel_refunds_full_toll_restoring_zero_net(self, api):
        """PRD section 3.5: "cancelling a `PAID` ticket — a shift-manager
        action — moves it to terminal `REFUNDED`, adds the full
        `total_paid_cents` into `refund_total_cents`, and reverses the cash
        out of the shift with posture recomputed; across the ticket's life,
        the sum of tolls minus refunds is its net revenue."

        Design: Difficulty/compensating_invariant/scale_toll_ledger_conservation
        """
        ctx, ticket = self._setup_weighed_ticket()
        settle_ticket(ticket["id"], "CASH")

        cancelled = validate_success(
            api.scale_ticket_cancel(ticket["id"], SM_2)
        )
        assert cancelled["status"] == "REFUNDED"
        assert cancelled["refund_total_cents"] == 1650

        # tolls(1650) - refunds(1650) == 0 net revenue; drawer restored
        assert cancelled["total_paid_cents"] - cancelled["refund_total_cents"] == 0
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000


class TestStoreSaleRoundTrip:
    def test_store_sale_refund_cycle(self, api):
        """PRD section 3.6: "with a member attached, the sale accrues one
        point per dollar of `total_cents`, rounded half up, granted as a
        `STORE_SALE` lot and recorded as `points_earned`" and "A
        `ShiftManager` may refund a completed sale — `COMPLETED → REFUNDED`,
        optionally noting a `reason` — which sets `payment_status` to
        `REFUNDED`, restores each line's quantity to stock with
        `is_low_stock` recomputed, claws back the earned points as a negative
        lot applied newest-first, and, for a cash sale, decrements the
        shift's expected cash by `total_cents` with posture recomputed."

        Design: Corner/endpoints/endpoint_store_sale_refund_cycle
        """
        ctx = setup_shift_site("Site E3", clock=TEST_CLOCK_ISO)
        item = create_stock_item(
            ctx.site["id"], sku="SNACK-A", name="Snack A", category="RETAIL",
            unit_price_cents=999, reorder_point=5, initial_on_hand_quantity=50,
        )
        member = create_member(points=0)

        sale = validate_success(
            api.create_store_sale(
                ctx.site["id"],
                create_store_sale_payload(
                    ctx.shift["id"],
                    [{"stock_item_id": item["id"], "quantity": 3}],
                    tender_type="CASH",
                    loyalty_member_id=member["id"],
                ),
                CASH_1,
            ),
            201,
        )
        assert sale["total_cents"] == 2997
        assert sale["points_earned"] == 30  # round_half_up(29.97)
        assert reload_stock_item(item["id"])["on_hand_quantity"] == 47

        refunded = validate_success(
            api.store_sale_refund(sale["id"],
                                  store_sale_refund_payload("wrong item"), SM_2)
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["payment_status"] == "REFUNDED"
        assert reload_stock_item(item["id"])["on_hand_quantity"] == 50
        assert reload_member(member["id"])["points_balance"] == 0
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000

    def test_store_sale_insufficient_stock(self, api):
        """PRD section 3.6: "Stock sufficiency is enforced per line — the
        quantity may not exceed what is on hand, and no line may drive
        `on_hand_quantity` negative, else `ERR_INSUFFICIENT_STOCK`
        (HTTP 422)".

        Design: Corner/errors/error_insufficient_stock_store_sale
        """
        ctx = setup_shift_site("Site R5", clock=TEST_CLOCK_ISO)
        item = create_stock_item(
            ctx.site["id"], sku="SNACK-A", name="Snack A", category="RETAIL",
            unit_price_cents=999, reorder_point=1, initial_on_hand_quantity=2,
        )

        resp = api.create_store_sale(
            ctx.site["id"],
            create_store_sale_payload(
                ctx.shift["id"],
                [{"stock_item_id": item["id"], "quantity": 3}],
                tender_type="CASH",
            ),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        assert reload_stock_item(item["id"])["on_hand_quantity"] == 2
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000
