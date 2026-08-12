"""Allocation, compliance screening, shipment tender/deliver, and cascades."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_customer, create_part, create_unit, create_aog_request,
    create_quote, make_quote_line, issue_quote,
    setup_issued_quote, accept_quote_and_get_order, allocate_all_lines,
    clear_order_compliance, get_core_return_for_line,
    create_shipment_payload, create_charter_slot_payload,
    credit_adjustment_payload, make_customer_headers, TEST_USERS,
    setup_delivered_order,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def _allocated_order_with_shipment(api, part_overrides=None, quote_overrides=None,
                                   line_overrides=None, shipment_overrides=None):
    """Accepted order, allocated line, compliance CLEARED, shipment DRAFT."""
    ctx = setup_issued_quote(
        part_overrides=part_overrides,
        quote_overrides=quote_overrides,
        line_overrides=line_overrides,
        with_unit=True, source_search=True,
    )
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]] * len(ctx["lines"]))
    clear_order_compliance(ctx)
    ctx["shipment"] = validate_success(api.create_shipment(
        create_shipment_payload(ctx["order"]["id"], **(shipment_overrides or {})),
        WAREHOUSE,
    ), 201)
    return ctx


class TestSalesOrderParallelDimensions:
    """Order row carrying three independent state dimensions (PRD §3.5)."""

    def _setup_accepted(self, api):
        return setup_issued_quote(
            customer_name="ParAir",
            part_overrides={"part_number": "PN-D", "list_price_cents": 100_000},
            unit_overrides={"condition": "NEW", "trace_doc_level": "FAA_8130"},
            aog_overrides={"aircraft_tail": "N600PA", "airport_code": "ORD"},
            line_overrides={"unit_price_cents": 100_000},
            with_unit=True, source_search=True,
        )

    def test_compliance_moves_while_others_stay(self, api):
        """PRD §3.5: "A SalesOrder tracks three independent dimensions in
        parallel: fulfillment (`PENDING_ALLOCATION`, `ALLOCATED`, `SHIPPED`,
        `DELIVERED`, `CLOSED`), compliance (`PENDING_SCREENING`, `CLEARED`,
        `EXPORT_HELD`, `BLOCKED`), and payment (`UNBILLED`, `INVOICED`,
        `PAID`)."

        Design: Difficulty/non_linear_state_machine/sales_order_parallel_dimensions_evolve_independently
        """
        ctx = self._setup_accepted(api)
        accept_quote_and_get_order(ctx)
        order = ctx["order"]
        assert order["fulfillment_status"] == "PENDING_ALLOCATION"
        assert order["compliance_status"] == "PENDING_SCREENING"
        assert order["payment_status"] == "UNBILLED"

        decided = validate_success(api.post_compliance_decision(
            order["id"], {"decision": "CLEARED"}, COMPLIANCE,
        ))
        assert decided["compliance_status"] == "CLEARED"
        assert decided["fulfillment_status"] == "PENDING_ALLOCATION"
        assert decided["payment_status"] == "UNBILLED"

    def test_delivery_advances_fulfillment_and_payment(self, api):
        """PRD §3.5: "The order's fulfillment reaches `DELIVERED`, its payment
        flips `UNBILLED` → `INVOICED` with `invoiced_cents` set to the quote's
        `total_cents` (goods and fees only — freight and core deposits are
        excluded)".

        Quote total here is 100000 + 4500 + 6270 = 110770.

        Design: Difficulty/non_linear_state_machine/sales_order_parallel_dimensions_evolve_independently
        """
        ctx = _allocated_order_with_shipment(
            api,
            part_overrides={"part_number": "PN-D", "list_price_cents": 100_000},
            line_overrides={"unit_price_cents": 100_000},
        )
        order = ctx["order"]
        validate_success(api.tender_shipment(ctx["shipment"]["id"], {}, WAREHOUSE))
        validate_success(api.deliver_shipment(ctx["shipment"]["id"], WAREHOUSE))

        after = validate_success(api.get_order(order["id"], AGENT))
        # PRD §3.5 says fulfillment "reaches DELIVERED" at delivery and later
        # "moves DELIVERED → CLOSED ... once every core return and loan born
        # of the order has settled". This order is OUTRIGHT-only — it bears no
        # core returns and no loans — so PRD does not pin whether the
        # vacuously-satisfied closure fires within the delivery request; both
        # DELIVERED and CLOSED are PRD-faithful outcomes here.
        assert after["fulfillment_status"] in ("DELIVERED", "CLOSED")
        assert after["payment_status"] == "INVOICED"
        assert after["invoiced_cents"] == 110_770
        # compliance was CLEARED before tender and is untouched by delivery
        assert after["compliance_status"] == "CLEARED"

    def test_payment_credit_moves_payment_alone(self, api):
        """PRD §3.1: "When cumulative `PAYMENT_CREDIT` entries referencing an
        invoiced order reach or exceed that order's `invoiced_cents`, the
        order's payment dimension flips from `INVOICED` to `PAID`
        automatically."

        Design: Difficulty/non_linear_state_machine/sales_order_parallel_dimensions_evolve_independently
        """
        ctx = setup_issued_quote(
            customer_name="ParAir",
            part_overrides={"part_number": "PN-D", "list_price_cents": 100_000},
            unit_overrides={"condition": "NEW", "trace_doc_level": "FAA_8130"},
            aog_overrides={"aircraft_tail": "N600PA", "airport_code": "ORD"},
            line_overrides={"unit_price_cents": 100_000},
            with_unit=True, source_search=True,
        )
        accept_quote_and_get_order(ctx)
        allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]])
        clear_order_compliance(ctx)
        shipment = validate_success(api.create_shipment(
            create_shipment_payload(ctx["order"]["id"]), WAREHOUSE,
        ), 201)
        validate_success(api.tender_shipment(shipment["id"], {}, WAREHOUSE))
        validate_success(api.deliver_shipment(shipment["id"], WAREHOUSE))

        cust = validate_success(api.get_customer(ctx["customer"]["id"], FINANCE))
        validate_success(api.post_credit_adjustment(
            cust["id"],
            credit_adjustment_payload(
                "PAYMENT_CREDIT", 110_770, cust["version"],
                order_id=ctx["order"]["id"],
            ),
            FINANCE,
        ), 201)

        after = validate_success(api.get_order(ctx["order"]["id"], AGENT))
        assert after["payment_status"] == "PAID"
        # See above: for an OUTRIGHT-only order PRD does not uniquely pin
        # DELIVERED vs immediate CLOSED (vacuous "every core return and loan
        # ... has settled" reading); the payment dimension is the asserted
        # mover here, and fulfillment must be a post-delivery state.
        assert after["fulfillment_status"] in ("DELIVERED", "CLOSED")


class TestDeliveryCascadeInvoiceToBalance:
    """EXCHANGE order: 250000 line -> subtotal 250000, handling 4500, tier fee
    15270, total 269770; STANDARD freight 800 km / 4 kg -> 1200*4*1.0 = 4800;
    core deposit 500000."""

    def test_delivery_cascade_order_side(self, api):
        """PRD §3.5: "The order's fulfillment reaches `DELIVERED`, its payment
        flips `UNBILLED` → `INVOICED` with `invoiced_cents` set to the quote's
        `total_cents`", "Every unit on an `OUTRIGHT` or `EXCHANGE` line becomes
        `SOLD`", "One CoreReturn springs up per `EXCHANGE` line with its due
        instant exactly 21 days after delivery", and "Finally the request
        advances `FULFILLING` → `FULFILLED`".

        Design: Difficulty/transitive_cascade/delivery_cascade_invoice_to_balance
        """
        ctx = self._delivered_exchange(api)

        assert ctx["shipment"]["status"] == "DELIVERED"
        order = validate_success(api.get_order(ctx["order"]["id"], AGENT))
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["payment_status"] == "INVOICED"
        assert order["invoiced_cents"] == 269_770

        core = ctx["core_return"]
        assert core["core_value_cents"] == 500_000
        assert core["due_at"].startswith("2026-05-22T00:00:00")

        unit = validate_success(api.get_inventory_unit(ctx["unit"]["id"], AGENT))
        assert unit["status"] == "SOLD"
        aog = validate_success(api.get_aog_request(ctx["aog"]["id"], AGENT))
        assert aog["status"] == "FULFILLED"

    def test_delivery_cascade_balance_side(self, api):
        """PRD §2.5: "A customer's `outstanding_balance_cents` is a read-only
        computed field: it always equals the sum of `amount_cents` over the
        debit entry types ... minus the sum over the credit entry types" and
        "The balance is recomputed synchronously within the same request that
        posts any entry". PRD §3.5: "an `INVOICE_DEBIT` for that amount posts
        against the customer, a `CORE_DEPOSIT_DEBIT` posts for each `EXCHANGE`
        line at the part's core value times the line quantity"; §3.5 shipment
        creation posts "a `FREIGHT_DEBIT` for that amount".

        Debits: 269770 (invoice) + 4800 (freight) + 500000 (deposit) = 774570.

        Design: Difficulty/transitive_cascade/delivery_cascade_invoice_to_balance
        """
        ctx = self._delivered_exchange(api)
        cust = validate_success(api.get_customer(ctx["customer"]["id"], FINANCE))
        assert cust["outstanding_balance_cents"] == 774_570

        ledger, meta = validate_paginated(
            api.list_ledger_entries(ctx["customer"]["id"], FINANCE)
        )
        seen = {(e["entry_type"], e["amount_cents"]) for e in ledger}
        assert ("INVOICE_DEBIT", 269_770) in seen
        assert ("FREIGHT_DEBIT", 4_800) in seen
        assert ("CORE_DEPOSIT_DEBIT", 500_000) in seen

    def _delivered_exchange(self, api):
        return setup_delivered_order(
            sale_type="EXCHANGE", customer_name="CascadeAir",
            part_overrides={"part_number": "PN-CAS", "list_price_cents": 250_000},
            aog_overrides={"aircraft_tail": "N700CA", "airport_code": "DFW"},
            line_overrides={"unit_price_cents": 250_000},
        )


class TestTenderBlockedUntilComplianceCleared:
    def _setup(self, api):
        ctx = setup_issued_quote(
            customer_name="GateAir",
            part_overrides={"part_number": "PN-GT", "list_price_cents": 60_000,
                            "export_control_code": "EAR9X610"},
            aog_overrides={"aircraft_tail": "N333GT", "airport_code": "BOS"},
            line_overrides={"unit_price_cents": 60_000},
            quote_overrides={"destination_country": "GB"},
            with_unit=True, source_search=True,
        )
        accept_quote_and_get_order(ctx)
        allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]])
        ctx["shipment"] = validate_success(api.create_shipment(
            create_shipment_payload(ctx["order"]["id"],
                                    export_license_ref="EXP-GB-001"),
            WAREHOUSE,
        ), 201)
        return ctx

    def test_tender_rejected_while_pending_screening(self, api):
        """PRD §3.5: "the order's compliance must be `CLEARED`
        (`ERR_COMPLIANCE_NOT_CLEARED`) and fulfillment must be `ALLOCATED`
        (`ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/tender_blocked_until_compliance_cleared
        """
        ctx = self._setup(api)
        res = api.tender_shipment(ctx["shipment"]["id"], {}, WAREHOUSE)
        validate_error(res, "ERR_COMPLIANCE_NOT_CLEARED", expected_status=409)

    def test_tender_rejected_while_export_held_then_succeeds_when_cleared(self, api):
        """PRD §3.5: "From `PENDING_SCREENING` an order may clear or be
        export-held; from `EXPORT_HELD` it may clear or be blocked." and
        "the order's compliance must be `CLEARED`
        (`ERR_COMPLIANCE_NOT_CLEARED`)".

        Design: Difficulty/cross_entity_state_dependency/tender_blocked_until_compliance_cleared
        """
        ctx = self._setup(api)
        validate_success(api.post_compliance_decision(
            ctx["order"]["id"],
            {"decision": "EXPORT_HELD", "decision_memo": "license review"},
            COMPLIANCE,
        ))
        held = api.tender_shipment(ctx["shipment"]["id"], {}, WAREHOUSE)
        validate_error(held, "ERR_COMPLIANCE_NOT_CLEARED", expected_status=409)

        validate_success(api.post_compliance_decision(
            ctx["order"]["id"],
            {"decision": "CLEARED", "decision_memo": "license verified"},
            COMPLIANCE,
        ))
        cleared = validate_success(
            api.tender_shipment(ctx["shipment"]["id"], {}, WAREHOUSE)
        )
        assert cleared["status"] in ("TENDERED", "IN_TRANSIT"), (
            "tender falls through to IN_TRANSIT automatically (PRD §3.5)"
        )


class TestAllocateRequiresUnitTraceAndCondition:
    def _setup(self, api):
        customer = create_customer(name="TraceAir")
        part = create_part(part_number="PN-TR", rotable=True,
                           list_price_cents=800_000, core_value_cents=300_000,
                           warranty_months=24)
        u1 = create_unit(part["id"], serial_number="SN-T1",
                         condition="SERVICEABLE", trace_doc_level="DUAL_RELEASE")
        u2 = create_unit(part["id"], serial_number="SN-T2",
                         condition="OVERHAULED", trace_doc_level="FAA_8130")
        aog = create_aog_request(
            customer["id"], part["id"], aircraft_tail="N444TR",
            airport_code="MIA", condition_acceptable=["OVERHAULED"],
            min_trace_doc="DUAL_RELEASE",
        )
        quote = create_quote(
            aog["id"], customer["id"],
            [make_quote_line(part["id"], sale_type="EXCHANGE",
                             unit_price_cents=800_000,
                             condition_required="OVERHAULED")],
        )
        issued = issue_quote(quote["id"])
        ctx = {"customer": customer, "part": part, "aog": aog, "quote": issued}
        accept_quote_and_get_order(ctx)
        ctx["u1"], ctx["u2"] = u1, u2
        return ctx

    def test_wrong_condition_rejected(self, api):
        """PRD §3.5: "the unit's `condition` must equal the line's
        `condition_required` (`ERR_CONDITION_NOT_ACCEPTABLE`)".

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_unit_trace_and_condition
        """
        ctx = self._setup(api)
        res = api.allocate_order_line(
            ctx["lines"][0]["id"], {"unit_id": ctx["u1"]["id"]}, WAREHOUSE,
        )
        validate_error(res, "ERR_CONDITION_NOT_ACCEPTABLE", expected_status=422)
        u1 = validate_success(api.get_inventory_unit(ctx["u1"]["id"], AGENT))
        assert u1["status"] == "AVAILABLE"

    def test_low_trace_rejected_then_certify_unblocks(self, api):
        """PRD §3.5: "its trace rank must meet the originating request's
        `min_trace_doc` rank (`ERR_TRACE_DOC_INSUFFICIENT`)" and PRD §3.2: "A
        `ComplianceOfficer` certifying a unit supplies a new `trace_doc_level`".

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_unit_trace_and_condition
        """
        ctx = self._setup(api)
        low = api.allocate_order_line(
            ctx["lines"][0]["id"], {"unit_id": ctx["u2"]["id"]}, WAREHOUSE,
        )
        validate_error(low, "ERR_TRACE_DOC_INSUFFICIENT", expected_status=422)

        validate_success(api.certify_trace(
            ctx["u2"]["id"], {"trace_doc_level": "DUAL_RELEASE"}, COMPLIANCE,
        ))
        allocated = validate_success(api.allocate_order_line(
            ctx["lines"][0]["id"], {"unit_id": ctx["u2"]["id"]}, WAREHOUSE,
        ))
        assert allocated["allocation_status"] == "ALLOCATED"
        u2 = validate_success(api.get_inventory_unit(ctx["u2"]["id"], AGENT))
        assert u2["status"] == "ALLOCATED"


class TestAllocateReleaseUnitCountInvariant:
    def _setup(self, api):
        ctx = setup_issued_quote(
            customer_name="InvAir",
            part_overrides={"part_number": "PN-INV", "list_price_cents": 70_000},
            aog_overrides={"aircraft_tail": "N771IV", "airport_code": "DEN"},
            line_overrides={"unit_price_cents": 70_000},
            with_unit=True, source_search=False,
        )
        accept_quote_and_get_order(ctx)
        return ctx

    def test_allocate_shifts_counters_and_flips_order(self, api):
        """PRD §3.5: "A successful allocation moves the unit to `ALLOCATED`
        (from `RESERVED` or directly from `AVAILABLE`, adjusting the part's
        counters accordingly), sets the line's `allocated_unit_id` and flips
        `allocation_status` to `ALLOCATED`, and increments the line's
        `version`; when every line of the order is allocated, fulfillment
        flips `PENDING_ALLOCATION` → `ALLOCATED` and the order's `version`
        increments."

        Design: Difficulty/compensating_invariant/allocate_release_unit_count_invariant
        """
        ctx = self._setup(api)
        part = validate_success(api.get_part(ctx["part"]["id"], WAREHOUSE))
        assert (part["available_count"], part["reserved_count"]) == (1, 0)

        allocated = validate_success(api.allocate_order_line(
            ctx["lines"][0]["id"], {"unit_id": ctx["unit"]["id"]}, WAREHOUSE,
        ))
        assert allocated["allocation_status"] == "ALLOCATED"
        assert allocated["allocated_unit_id"] == ctx["unit"]["id"]

        part_mid = validate_success(api.get_part(ctx["part"]["id"], WAREHOUSE))
        assert (part_mid["available_count"], part_mid["reserved_count"]) == (0, 0)
        unit_mid = validate_success(
            api.get_inventory_unit(ctx["unit"]["id"], WAREHOUSE)
        )
        assert unit_mid["status"] == "ALLOCATED"
        order_mid = validate_success(api.get_order(ctx["order"]["id"], AGENT))
        assert order_mid["fulfillment_status"] == "ALLOCATED"

    def test_release_restores_counters_and_reverts_order(self, api):
        """PRD §3.5: "Release is the compensating act: it returns the unit
        `ALLOCATED` → `AVAILABLE`, resets the line to `PENDING` with
        `allocated_unit_id` nulled, reverts an order that had flipped back to
        `PENDING_ALLOCATION`, and increments the line's `version`."

        Design: Difficulty/compensating_invariant/allocate_release_unit_count_invariant
        """
        ctx = self._setup(api)
        validate_success(api.allocate_order_line(
            ctx["lines"][0]["id"], {"unit_id": ctx["unit"]["id"]}, WAREHOUSE,
        ))
        released = validate_success(
            api.release_order_line(ctx["lines"][0]["id"], WAREHOUSE)
        )
        assert released["allocation_status"] == "PENDING"
        assert released["allocated_unit_id"] is None

        part_end = validate_success(api.get_part(ctx["part"]["id"], WAREHOUSE))
        assert (part_end["available_count"], part_end["reserved_count"]) == (1, 0), (
            "allocate+release must leave the part counters exactly as before"
        )
        unit_end = validate_success(
            api.get_inventory_unit(ctx["unit"]["id"], WAREHOUSE)
        )
        assert unit_end["status"] == "AVAILABLE"
        order_end = validate_success(api.get_order(ctx["order"]["id"], AGENT))
        assert order_end["fulfillment_status"] == "PENDING_ALLOCATION"


def test_release_after_ship_rejected(api):
    """PRD §3.5: "Release is refused with `ERR_INVALID_STATE` once fulfillment
    has reached `SHIPPED`, `DELIVERED`, or `CLOSED`".

    Design: Corner/endpoints/release_after_ship_rejected
    """
    ctx = _allocated_order_with_shipment(
        api,
        part_overrides={"part_number": "PN-LR", "list_price_cents": 20_000},
        line_overrides={"unit_price_cents": 20_000},
    )
    validate_success(api.tender_shipment(ctx["shipment"]["id"], {}, WAREHOUSE))

    res = api.release_order_line(ctx["lines"][0]["id"], WAREHOUSE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    unit = validate_success(api.get_inventory_unit(ctx["unit"]["id"], AGENT))
    assert unit["status"] == "SHIPPED"
    line = validate_success(api.get_order_line(ctx["lines"][0]["id"], AGENT))
    assert line["allocation_status"] == "ALLOCATED"


def test_hazmat_declaration_and_export_license_gates(api):
    """PRD §3.5: "then, when any line's part is hazmat-classed, a
    `hazmat_declaration_ref` must be present (`ERR_HAZMAT_DECLARATION_MISSING`);
    when any line's part is export-controlled, an `export_license_ref` must be
    present (`ERR_EXPORT_LICENSE_REQUIRED`)". Also: "Declaration references may
    be supplied at creation or at tender; the effective reference at tender is
    the tender payload's value when present, otherwise the creation-time
    value."

    Design: Corner/validations/hazmat_declaration_and_export_license_gates
    """
    ctx = setup_issued_quote(
        customer_name="HazAir",
        part_overrides={"part_number": "PN-HZ", "list_price_cents": 50_000,
                        "hazmat_class": "CLASS_3",
                        "export_control_code": "EAR9X610"},
        aog_overrides={"aircraft_tail": "N9HZ"},
        line_overrides={"unit_price_cents": 50_000},
        quote_overrides={"destination_country": "GB"},
        with_unit=True, source_search=True,
    )
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]])
    clear_order_compliance(ctx)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(ctx["order"]["id"]), WAREHOUSE,
    ), 201)

    no_refs = api.tender_shipment(shipment["id"], {}, WAREHOUSE)
    validate_error(no_refs, "ERR_HAZMAT_DECLARATION_MISSING", expected_status=422)

    hazmat_only = api.tender_shipment(
        shipment["id"], {"hazmat_declaration_ref": "DG-2026-001"}, WAREHOUSE,
    )
    validate_error(hazmat_only, "ERR_EXPORT_LICENSE_REQUIRED", expected_status=422)

    both = validate_success(api.tender_shipment(
        shipment["id"],
        {"hazmat_declaration_ref": "DG-2026-001",
         "export_license_ref": "EXP-GB-777"},
        WAREHOUSE,
    ))
    assert both["status"] in ("TENDERED", "IN_TRANSIT")


def test_export_denied_destination(api):
    """PRD §3.5: "a `destination_country` of `KP`, `CU`, `IR`, or `SY` is
    always refused with `ERR_EXPORT_DESTINATION_DENIED`"; PRD §2.8: "Shipments
    whose destination country is one of `KP`, `CU`, `IR`, or `SY` are always
    refused at tender."

    Design: Corner/errors/export_denied_destination
    """
    ctx = setup_issued_quote(
        customer_name="DeniedAir",
        part_overrides={"part_number": "PN-DN", "list_price_cents": 20_000},
        aog_overrides={"aircraft_tail": "N9DN", "airport_code": "FNJ"},
        line_overrides={"unit_price_cents": 20_000},
        quote_overrides={"destination_country": "KP", "distance_km": 9_000},
        with_unit=True, source_search=True,
    )
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]])
    clear_order_compliance(ctx)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(ctx["order"]["id"]), WAREHOUSE,
    ), 201)

    res = api.tender_shipment(shipment["id"], {}, WAREHOUSE)
    validate_error(res, "ERR_EXPORT_DESTINATION_DENIED", expected_status=422)
    after = validate_success(api.get_shipment(shipment["id"], AGENT))
    assert after["status"] == "DRAFT"


class TestCharterBookingsTurnaroundBuffer:
    def _setup_two_charter_orders(self, api):
        customer = create_customer(name="CharterCo")
        part = create_part(part_number="PN-CH", list_price_cents=500_000)
        create_unit(part["id"], serial_number="SN-CH1")
        create_unit(part["id"], serial_number="SN-CH2")
        slot = validate_success(api.create_charter_slot(
            create_charter_slot_payload(tail_number="N900CX", home_base="CLT"),
            AGENT,
        ), 201)
        orders = []
        for tail in ("N551CH", "N552CH"):
            aog = create_aog_request(customer["id"], part["id"],
                                     aircraft_tail=tail, airport_code="CLT")
            quote = create_quote(
                aog["id"], customer["id"],
                [make_quote_line(part["id"], unit_price_cents=500_000)],
                freight_mode="CHARTER", distance_km=2_500,
                chargeable_weight_kg=40,
            )
            issued = issue_quote(quote["id"])
            ctx = {"customer": customer, "quote": issued}
            accept_quote_and_get_order(ctx)
            orders.append(ctx["order"]["id"])
        return slot, orders

    def test_gap_below_120_minutes_rejected(self, api):
        """PRD §3.5: "A charter booking also checks the slot's diary: a new
        booking whose window comes within 120 minutes of another booking on
        the same slot is refused with `ERR_CHARTER_WINDOW_OVERLAP`, while a
        gap of at least 120 minutes is allowed."

        Booking A [08:00, 14:00]; booking B at 15:00 leaves a 60-minute gap.

        Design: Difficulty/resource_temporal_overlap/charter_bookings_turnaround_buffer
        """
        slot, orders = self._setup_two_charter_orders(api)
        first = validate_success(api.create_shipment(
            create_shipment_payload(
                orders[0], depart_at="2026-05-10T08:00:00Z",
                arrive_at="2026-05-10T14:00:00Z", charter_slot_id=slot["id"],
            ),
            WAREHOUSE,
        ), 201)
        # CHARTER base: max(750000, 2900 * 2500) = 7250000; no surcharges
        assert first["freight_cost_cents"] == 7_250_000

        res = api.create_shipment(
            create_shipment_payload(
                orders[1], depart_at="2026-05-10T15:00:00Z",
                arrive_at="2026-05-10T20:00:00Z", charter_slot_id=slot["id"],
            ),
            WAREHOUSE,
        )
        validate_error(res, "ERR_CHARTER_WINDOW_OVERLAP", expected_status=409)

    def test_gap_of_exactly_120_minutes_allowed(self, api):
        """PRD §3.5: "a gap of at least 120 minutes is allowed" — the buffer
        check rejects gaps strictly below 120 minutes, so a 16:00 departure
        after a 14:00 arrival succeeds.

        Design: Difficulty/resource_temporal_overlap/charter_bookings_turnaround_buffer
        """
        slot, orders = self._setup_two_charter_orders(api)
        validate_success(api.create_shipment(
            create_shipment_payload(
                orders[0], depart_at="2026-05-10T08:00:00Z",
                arrive_at="2026-05-10T14:00:00Z", charter_slot_id=slot["id"],
            ),
            WAREHOUSE,
        ), 201)
        second = validate_success(api.create_shipment(
            create_shipment_payload(
                orders[1], depart_at="2026-05-10T16:00:00Z",
                arrive_at="2026-05-10T22:00:00Z", charter_slot_id=slot["id"],
            ),
            WAREHOUSE,
        ), 201)
        assert second["order_id"] == orders[1]

        data, meta = validate_paginated(
            api.list_shipments(AGENT, params={"charter_slot_id": slot["id"]})
        )
        assert meta["total_count"] == 2
