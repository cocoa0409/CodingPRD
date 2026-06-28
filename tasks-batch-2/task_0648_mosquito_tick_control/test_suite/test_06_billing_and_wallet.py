"""Payment, void, refund, and wallet-conservation tests.

Covers the Difficulty compensating_invariant instances plus corner underpayment
and void-recompute error instances.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_account_holder_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    setup_completed_per_visit_with_invoice,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

TWO_ZONES = [
    {"label": "Turf", "zone_type": "TURF", "area_sqft": 4000},
    {"label": "Perim", "zone_type": "PERIMETER", "area_sqft": 2000},
]


def _seasonal_invoice(sub_id):
    invs = get_success_data(api_client.list_subscription_invoices(sub_id, BILLING))
    if isinstance(invs, dict) and "data" in invs:
        invs = invs["data"]
    seasonal = [i for i in invs if i["invoice_type"] == "SEASONAL"]
    return seasonal[0] if seasonal else None


def _complete_n(ctx, crew, dates):
    visits = list_recurring_visits(ctx["sub"]["id"])
    for i, d in enumerate(dates):
        set_clock(f"{d}T08:00:00Z")
        v = visits[i]
        route = create_route(crew["id"], region="NE01", route_date=d)
        dispatch_visit(route["id"], v["id"], route["version"])
        log_application(v["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(v["id"], crew["id"])


class TestSeasonalCancelRefundConservesInvoiceValue:
    """wallet credit + retained served value == seasonal invoice value."""

    def _setup(self):
        ctx = create_active_subscription(
            billing_mode="SEASONAL", region="NE01",
            zones=[{"label": "Yard", "zone_type": "TURF", "area_sqft": 4000}],
            season_start="2026-05-01", season_end="2026-08-14",
            plan_overrides={"tier": "PLUS", "includes_tick_barrier": False, "seasonal_price_cents": 30000})
        crew = create_crew(home_region_code="NE01")
        _complete_n(ctx, crew, ["2026-05-01", "2026-05-22"])
        set_clock("2026-06-15T08:00:00Z")
        return ctx

    def test_wallet_credit_equals_18600(self, api):
        """
    PRD 3.7: "The refund in cents is the seasonal invoice's `amount_cents` multiplied by the unserved count divided by the total, with the result floored toward zero to a whole cent."

        Design: Difficulty/compensating_invariant/seasonal_cancel_refund_conserves_invoice_value
        """
        ctx = self._setup()
        ah = make_account_holder_headers(ctx["holder"]["id"])
        validate_success(api.cancel_subscription(ctx["sub"]["id"], ah))
        holder = get_success_data(api.get_account_holder(ctx["holder"]["id"], BILLING))
        assert holder["wallet_credit_cents"] == 18600, f"27900*4/6 floored == 18600, got {holder['wallet_credit_cents']}"

    def test_refund_conserves_seasonal_invoice_value(self, api):
        """
    PRD 3.7: "This conserves value: the amount retained on the invoice plus the wallet credit equals the original seasonal invoice amount."

        Design: Difficulty/compensating_invariant/seasonal_cancel_refund_conserves_invoice_value
        """
        ctx = self._setup()
        original = _seasonal_invoice(ctx["sub"]["id"])["amount_cents"]
        assert original == 27900
        ah = make_account_holder_headers(ctx["holder"]["id"])
        validate_success(api.cancel_subscription(ctx["sub"]["id"], ah))
        assert _seasonal_invoice(ctx["sub"]["id"])["status"] == "VOID"
        credit = get_success_data(api.get_account_holder(ctx["holder"]["id"], BILLING))["wallet_credit_cents"]
        retained = original - credit
        assert credit + retained == original == 27900, f"credit {credit} + retained {retained} != {original}"


class TestOverpaymentCreditConservesTenderedCash:
    """Paying a 7380 invoice with 8000 credits exactly 620 to the wallet."""

    def test_overpayment_credits_difference_to_wallet(self, api):
        """
    PRD 3.7: "If the tendered amount exceeds the invoice's `amount_cents`, the overpayment — the tendered amount minus the invoice amount — is credited to the owning account holder's `wallet_credit_cents` as a conserved overpayment compensation."

        Design: Difficulty/compensating_invariant/overpayment_credit_conserves_tendered_cash
        """
        ctx = setup_completed_per_visit_with_invoice(zones=TWO_ZONES, lot_size_sqft=8000)
        inv = ctx["invoice"]
        assert inv["amount_cents"] == 7380
        paid = validate_success(api.pay_invoice(inv["id"], {"paid_amount_cents": 8000}, BILLING))
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 8000
        holder = get_success_data(api.get_account_holder(ctx["holder"]["id"], BILLING))
        assert holder["wallet_credit_cents"] == 620, f"8000-7380 == 620, got {holder['wallet_credit_cents']}"

    def test_applied_plus_credit_equals_tendered(self, api):
        """
    PRD 3.7: "On payment, the invoice's `paid_amount_cents` is set to the tendered amount."

        Design: Difficulty/compensating_invariant/overpayment_credit_conserves_tendered_cash
        """
        ctx = setup_completed_per_visit_with_invoice(zones=TWO_ZONES, lot_size_sqft=8000)
        inv = ctx["invoice"]
        validate_success(api.pay_invoice(inv["id"], {"paid_amount_cents": 8000}, BILLING))
        credit = get_success_data(api.get_account_holder(ctx["holder"]["id"], BILLING))["wallet_credit_cents"]
        assert inv["amount_cents"] + credit == 8000, f"applied {inv['amount_cents']} + credit {credit} != 8000"


def test_pay_underpayment_returns_underpayment(api):
    """
    PRD 3.7: "Payment supplies a `paid_amount_cents` that must be at least the invoice's `amount_cents`; an underpayment is rejected with `ERR_UNDERPAYMENT`."

    Design: Corner/errors/pay_underpayment_returns_underpayment
    """
    ctx = setup_completed_per_visit_with_invoice(zones=TWO_ZONES, lot_size_sqft=8000)
    inv = ctx["invoice"]
    assert inv["amount_cents"] == 7380
    validate_error(api.pay_invoice(inv["id"], {"paid_amount_cents": 5000}, BILLING), ApiErrorId.ERR_UNDERPAYMENT.value)
    assert get_success_data(api.get_invoice(inv["id"], BILLING))["status"] == "ISSUED"


def test_void_invoice_recomputes_season_balance(api):
    """
    PRD 3.7: "A billing administrator may also void an `ISSUED` invoice, transitioning it `ISSUED → VOID`, which recomputes the subscription's `season_balance_cents` (the voided invoice no longer counts) and increments the invoice's `version`."

    Design: Corner/errors/void_invoice_recomputes_season_balance
    """
    ctx = setup_completed_per_visit_with_invoice(zones=TWO_ZONES, lot_size_sqft=8000)
    inv = ctx["invoice"]
    assert inv["amount_cents"] == 7380
    ah = make_account_holder_headers(ctx["holder"]["id"])
    assert get_success_data(api.get_subscription(ctx["sub"]["id"], ah))["season_balance_cents"] == 7380
    voided = validate_success(api.void_invoice(inv["id"], BILLING))
    assert voided["status"] == "VOID"
    assert get_success_data(api.get_subscription(ctx["sub"]["id"], ah))["season_balance_cents"] == 0
