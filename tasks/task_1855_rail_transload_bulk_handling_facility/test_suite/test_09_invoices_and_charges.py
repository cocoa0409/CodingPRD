"""Invoices and charge entries: issue sweeps, period bounds, pay/dispute
flows, manual charge voids, and terminal-state rejections."""
from test_helpers import (
    ApiErrorId,
    create_invoice_payload,
    get_success_data,
    make_customer_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    OPERATOR,
    SAFETY,
    YARD,
    arrive_car,
    create_customer,
    create_facility,
    create_invoice_for,
    create_lot,
    create_product,
    create_railcar,
    create_spot_order_for_car,
    create_track,
    list_all_charges,
    schedule_spot_order,
    set_clock,
)


def _customer_with_scheduled_order(api, *, name="FT-S14", cust_name="C1",
                                   car_number="96901",
                                   schedule_clock="2026-08-03T00:30:00Z"):
    """Facility + customer + car ARRIVED with a SCHEDULED spot order, which
    leaves exactly one ACCRUED SWITCHING charge (18500) on the customer."""
    set_clock("2026-08-03T00:00:00Z")
    create_facility(name=name)
    cust = create_customer(name=cust_name, allocated_car_spots=5)
    prod = create_product(name="Salt")
    lot = create_lot(cust["id"], prod["id"])
    trk = create_track(name="T1", spot_capacity=1)
    car = arrive_car(
        create_railcar(cust["id"], prod["id"], lot["id"], car_number=car_number)["id"]
    )
    so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                   "2026-08-03T01:00:00Z", "2026-08-03T03:00:00Z")
    set_clock(schedule_clock)
    schedule_spot_order(so["id"])
    return {"customer": cust, "spot_order": so, "car": car}


class TestInvoiceHappyPath:
    def test_invoice_issue_sweeps_accrued_charges(self, api):
        """PRD §3.8: "Issuing the invoice sweeps the eligible charges: every
        `ChargeEntry` of that customer in `ACCRUED` status whose `created_at`
        falls within the period on both inclusive bounds." and "Otherwise each
        swept charge moves from `ACCRUED` to `INVOICED` with `invoice_id` set
        to this invoice (bumping each charge's version), and the invoice's
        `charge_count` is set to the number swept while `total_cents` is the
        integer sum of the swept lines' `amount_cents`."
        PRD §3.8: "From `ISSUED`, an invoice may be paid — by the owning
        `CustomerRep` or a `BillingClerk` — moving it to `PAID`"

        Design: Corner/state_machines/invoice_happy_path
        """
        ctx = _customer_with_scheduled_order(api)
        inv = create_invoice_for(ctx["customer"]["id"])

        issued = validate_success(api.issue_invoice(inv["id"], BILLING))
        assert issued["status"] == "ISSUED"
        assert issued["charge_count"] == 1
        assert issued["total_cents"] == 18500

        swept = [c for c in list_all_charges() if c.get("invoice_id") == inv["id"]]
        assert len(swept) == 1
        assert swept[0]["status"] == "INVOICED"

        paid = validate_success(api.pay_invoice(inv["id"], BILLING))
        assert paid["status"] == "PAID"


class TestInvoiceEdges:
    def test_invoice_edges_rejected(self, api):
        """PRD §3.8: "If no such charge exists, issue is rejected with
        `ERR_INVOICE_EMPTY`."
        PRD §3.8: "From `ISSUED`, an invoice may be paid — by the owning
        `CustomerRep` or a `BillingClerk` — moving it to `PAID`, or disputed by
        the owning `CustomerRep`, moving it to `DISPUTED`. Both are terminal;
        both bump `Invoice.version`."
        PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."
        PRD §3.8: "A `BillingClerk` or `FacilityAdmin` may void an accrued
        charge — a billing correction moving it to `VOIDED`" (only `ACCRUED`
        charges void).

        Design: Corner/state_machines/invoice_edges_rejected
        """
        # C1 has no charges at all; C2 gets one issued+paid invoice
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S15")
        cust1 = create_customer(name="C1", allocated_car_spots=5)
        cust2 = create_customer(name="C2", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot2 = create_lot(cust2["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        car2 = arrive_car(
            create_railcar(cust2["id"], prod["id"], lot2["id"],
                           car_number="96902")["id"]
        )
        so2 = create_spot_order_for_car(car2["id"], trk["id"], 1,
                                        "2026-08-03T01:00:00Z",
                                        "2026-08-03T03:00:00Z")
        schedule_spot_order(so2["id"])

        inv_a = create_invoice_for(cust1["id"])
        inv_b = create_invoice_for(cust2["id"])
        get_success_data(api.issue_invoice(inv_b["id"], BILLING))
        get_success_data(api.pay_invoice(inv_b["id"], BILLING))
        charge_b = [c for c in list_all_charges()
                    if c.get("invoice_id") == inv_b["id"]][0]

        # Issue of a charge-less DRAFT
        validate_error(api.issue_invoice(inv_a["id"], BILLING),
                       ApiErrorId.ERR_INVOICE_EMPTY)
        # Pay / dispute of a DRAFT
        validate_error(api.pay_invoice(inv_a["id"], BILLING),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(
            api.dispute_invoice(
                inv_a["id"], make_customer_rep_headers(cust1["id"])
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        # Re-issue / re-pay / dispute of a PAID (terminal) invoice
        validate_error(api.issue_invoice(inv_b["id"], BILLING),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.pay_invoice(inv_b["id"], BILLING),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(
            api.dispute_invoice(
                inv_b["id"], make_customer_rep_headers(cust2["id"])
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        # Void of an INVOICED charge (only ACCRUED voids)
        validate_error(api.void_charge(charge_b["id"], BILLING),
                       ApiErrorId.ERR_INVALID_STATE)


class TestInvoiceDispute:
    def test_invoice_dispute_flow(self, api):
        """PRD §3.8: "From `ISSUED`, an invoice may be paid — by the owning
        `CustomerRep` or a `BillingClerk` — moving it to `PAID`, or disputed by
        the owning `CustomerRep`, moving it to `DISPUTED`. Both are terminal;
        both bump `Invoice.version`."

        Design: Corner/state_machines/invoice_dispute_flow
        """
        ctx = _customer_with_scheduled_order(api, name="FT-S16",
                                             car_number="96903")
        inv = create_invoice_for(ctx["customer"]["id"])
        get_success_data(api.issue_invoice(inv["id"], BILLING))

        rep = make_customer_rep_headers(ctx["customer"]["id"])
        disputed = validate_success(api.dispute_invoice(inv["id"], rep))
        assert disputed["status"] == "DISPUTED"

        # DISPUTED is terminal: a second dispute matches no from-state
        validate_error(api.dispute_invoice(inv["id"], rep),
                       ApiErrorId.ERR_INVALID_STATE)


class TestChargeVoid:
    def test_charge_void_manual_correction(self, api):
        """PRD §3.8: "A `BillingClerk` or `FacilityAdmin` may void an accrued
        charge — a billing correction moving it to `VOIDED` and bumping its
        version"
        PRD §3.8: "Issuing the invoice sweeps the eligible charges: every
        `ChargeEntry` of that customer in `ACCRUED` status whose `created_at`
        falls within the period on both inclusive bounds."
        PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."

        Design: Corner/state_machines/charge_void_manual_correction
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S17")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        t1 = create_track(name="T1", spot_capacity=1)
        t2 = create_track(name="T2", spot_capacity=1)
        car1 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96911")["id"])
        car2 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96912")["id"])
        so1 = create_spot_order_for_car(car1["id"], t1["id"], 1,
                                        "2026-08-03T01:00:00Z",
                                        "2026-08-03T03:00:00Z")
        so2 = create_spot_order_for_car(car2["id"], t2["id"], 1,
                                        "2026-08-03T01:00:00Z",
                                        "2026-08-03T03:00:00Z")
        schedule_spot_order(so1["id"])
        schedule_spot_order(so2["id"])

        charges = [c for c in list_all_charges() if c["charge_type"] == "SWITCHING"]
        assert len(charges) == 2

        voided = validate_success(api.void_charge(charges[0]["id"], BILLING))
        assert voided["status"] == "VOIDED"

        # VOIDED is terminal for the void trigger
        validate_error(api.void_charge(charges[0]["id"], BILLING),
                       ApiErrorId.ERR_INVALID_STATE)

        inv = create_invoice_for(cust["id"])
        issued = validate_success(api.issue_invoice(inv["id"], BILLING))
        assert issued["charge_count"] == 1, "the voided charge is excluded"
        assert issued["total_cents"] == 18500


class TestInvoicePeriodBounds:
    def test_invoice_period_bounds_inclusive(self, api):
        """PRD §3.8: "Issuing the invoice sweeps the eligible charges: every
        `ChargeEntry` of that customer in `ACCRUED` status whose `created_at`
        falls within the period on both inclusive bounds."
        PRD §3.8: "the invoice's `charge_count` is set to the number swept
        while `total_cents` is the integer sum of the swept lines'
        `amount_cents`."

        Design: Corner/calculations/invoice_period_bounds_inclusive
        """
        set_clock("2026-08-01T00:00:00Z")
        create_facility(name="FT-C2")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=3)
        cars = [
            arrive_car(
                create_railcar(cust["id"], prod["id"], lot["id"],
                               car_number=f"9700{i}")["id"]
            )
            for i in (1, 2, 3)
        ]
        orders = [
            create_spot_order_for_car(
                cars[i]["id"], trk["id"], i + 1,
                f"2026-08-03T0{2 * i + 1}:00:00Z", f"2026-08-03T0{2 * i + 2}:00:00Z",
            )
            for i in range(3)
        ]
        # Charges stamped exactly on period_start, exactly on period_end, and
        # one second past period_end.
        set_clock("2026-08-01T00:00:00Z")
        schedule_spot_order(orders[0]["id"])
        set_clock("2026-08-31T23:59:59Z")
        schedule_spot_order(orders[1]["id"])
        set_clock("2026-09-01T00:00:00Z")
        schedule_spot_order(orders[2]["id"])

        inv = create_invoice_for(cust["id"])
        issued = validate_success(api.issue_invoice(inv["id"], BILLING))
        assert issued["charge_count"] == 2, (
            "both inclusive bounds sweep; the charge one second past "
            "period_end stays out"
        )
        assert issued["total_cents"] == 37000, "two 18500-cent switching fees"

        remaining = [c for c in list_all_charges() if c["status"] == "ACCRUED"]
        assert len(remaining) == 1, "the September charge remains ACCRUED"
        assert remaining[0]["invoice_id"] is None
