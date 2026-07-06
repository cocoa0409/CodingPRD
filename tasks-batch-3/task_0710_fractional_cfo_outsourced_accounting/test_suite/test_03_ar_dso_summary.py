"""AR summary: gross vs net outstanding and the two DSO variants."""
from test_helpers import (
    get_success_data,
    create_client, create_ar_invoice, dispute_ar_invoice,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]


class TestArDsoGrossVsNet:
    def test_gross_includes_disputed_net_excludes(self, api):
        """PRD §3.5: "The **gross outstanding** is the sum, over those `OPEN` and
        `DISPUTED` invoices, of `amount_cents` minus `paid_amount_cents`; the **net
        outstanding** is the same sum restricted to `OPEN` invoices only, so it
        omits disputed balances."
        PRD §3.5: "The gross DSO is the gross outstanding divided by
        `credit_sales_cents`, multiplied by a fixed 30-day window, rounded half up
        to two decimal places; the net DSO is computed the same way from the net
        outstanding."

        Design: Difficulty/dual_variant_calc/ar_dso_gross_vs_net_divergence
        """
        client = create_client(retainer_tier="ESSENTIALS", state_code="NY")
        cid = client["id"]
        create_ar_invoice(cid, amount_cents=2500000, counterparty_name="Cust1")
        create_ar_invoice(cid, amount_cents=1500000, counterparty_name="Cust2")
        ar3 = create_ar_invoice(cid, amount_cents=500000, counterparty_name="Cust3")
        dispute_ar_invoice(cid, ar3["id"])
        data = get_success_data(api.get_ar_summary(
            cid, CFO, params={"credit_sales_cents": 9000000}))
        assert data["gross_outstanding_cents"] == 4500000
        assert data["net_outstanding_cents"] == 4000000
        assert data["dso_gross"] == 15.00
        assert data["dso_net"] == 13.33

    def test_net_dso_never_exceeds_gross_dso(self, api):
        """PRD §3.5: "Because disputed balances inflate the gross numerator but not
        the net one, for identical data the net DSO never exceeds the gross DSO."

        Design: Difficulty/dual_variant_calc/ar_dso_gross_vs_net_divergence
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        create_ar_invoice(cid, amount_cents=2500000, counterparty_name="Cust1")
        create_ar_invoice(cid, amount_cents=1500000, counterparty_name="Cust2")
        ar3 = create_ar_invoice(cid, amount_cents=500000, counterparty_name="Cust3")
        dispute_ar_invoice(cid, ar3["id"])
        data = get_success_data(api.get_ar_summary(
            cid, CFO, params={"credit_sales_cents": 9000000}))
        assert data["dso_net"] <= data["dso_gross"]
        assert data["dso_gross"] == 15.00
        assert data["dso_net"] == 13.33
