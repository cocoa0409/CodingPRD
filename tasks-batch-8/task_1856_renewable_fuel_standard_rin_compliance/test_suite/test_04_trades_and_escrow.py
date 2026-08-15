"""Purchase ledger, trade state-machine guards, and escrow conservation (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_delivered_trade,
    create_trade,
    create_vendor,
    get_success_data,
    make_trader_headers,
    pay_trade,
    validate_error,
    validate_success,
    api_client,
)


class TestEscrowConservation:
    def test_create_reserves_escrow_and_cancel_releases_it(self, api):
        """PRD §3.3: "the account's `escrow_reserved_cents` rises by the total while the trade sits with `payment_status` `UNPAID` and `transfer_status` `PENDING`"
        PRD §3.3: "Cancelling a still-`PENDING` transfer moves it to `CANCELLED`; when the trade was never paid, the reserved escrow is released — `escrow_reserved_cents` falls by the total — and payment stays `UNPAID`"

        Design: Difficulty/compensating_invariant/escrow_conservation_create_cancel
        """
        acct = create_account(epa_registration_id="EPA-ACME-18")
        ven = create_vendor(acct["id"])
        trd = create_trade(
            acct["id"], ven["id"], rin_qty=50, price_per_rin_cents=100,
        )
        mid = validate_success(api.get_compliance_account(acct["id"], OPS))
        assert mid["escrow_reserved_cents"] == 5000
        get_success_data(api.cancel_trade(trd["id"], make_trader_headers("tr-1")))
        final = validate_success(api.get_compliance_account(acct["id"], OPS))
        assert final["escrow_reserved_cents"] == 0
        assert final["spent_cents"] == 0

    def test_cancelled_trade_terminal_state_and_total(self, api):
        """PRD §3.3: "Cancelling a still-`PENDING` transfer moves it to `CANCELLED`"
        PRD §3.3: "The trade's `total_price_cents` is the exact integer product of quantity and unit price"

        Design: Difficulty/compensating_invariant/escrow_conservation_create_cancel
        """
        acct = create_account(epa_registration_id="EPA-ACME-18B")
        ven = create_vendor(acct["id"])
        trd = create_trade(
            acct["id"], ven["id"], rin_qty=50, price_per_rin_cents=100,
        )
        data = get_success_data(
            api.cancel_trade(trd["id"], make_trader_headers("tr-1")),
        )
        assert data["transfer_status"] == "CANCELLED"
        assert data["total_price_cents"] == 5000


class TestTradeStateGuards:
    def test_deliver_before_pay_rejected(self, api):
        """PRD §3.3: "Recording delivery requires `payment_status` `PAID` (`ERR_INVALID_STATE` otherwise) and moves the transfer `PENDING` → `DELIVERED`"

        Design: Corner/state_machines/deliver_before_pay_rejected
        """
        acct = create_account(epa_registration_id="EPA-SM-2")
        ven = create_vendor(acct["id"])
        trd = create_trade(acct["id"], ven["id"])
        resp = api.deliver_trade(trd["id"], make_trader_headers("tr-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_rin_trade(trd["id"], CM))
        assert after["transfer_status"] == "PENDING"

    def test_pay_twice_rejected_and_spend_recorded_once(self, api):
        """PRD §3.3: "the trader pays, which requires the transfer to still be `PENDING` (`ERR_INVALID_STATE` otherwise), moves payment `UNPAID` → `PAID`, and shifts the total out of `escrow_reserved_cents` and into `spent_cents`."

        Design: Corner/state_machines/pay_twice_rejected
        """
        acct = create_account(epa_registration_id="EPA-SM-3")
        ven = create_vendor(acct["id"])
        h = make_trader_headers("tr-1")
        trd = create_trade(acct["id"], ven["id"], trader_headers=h,
                           rin_qty=10, price_per_rin_cents=100)
        pay_trade(trd["id"], trader_headers=h)
        resp = api.pay_trade(trd["id"], h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        acct_after = validate_success(api.get_compliance_account(acct["id"], OPS))
        assert acct_after["spent_cents"] == 1000

    def test_cancel_after_deliver_rejected(self, api):
        """PRD §3.3: "A trade can be unwound only before delivery."

        Design: Corner/state_machines/cancel_after_deliver_rejected
        """
        acct = create_account(epa_registration_id="EPA-SM-4")
        ven = create_vendor(acct["id"])
        h = make_trader_headers("tr-1")
        trd = create_delivered_trade(acct["id"], ven["id"], trader_headers=h)
        resp = api.cancel_trade(trd["id"], h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_rin_trade(trd["id"], CM))
        assert after["transfer_status"] == "DELIVERED"
