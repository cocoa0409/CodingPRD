"""Cross-entity state dependencies (rule 7) and temporal overlap (rule 8).

Covers: quotation accept gated on VesselCall IN_PORT; bonded delivery gated on
customs CLEARED; complaint accept gated on a creditable invoice; closed-interval
delivery window containment; half-open cold-store aggregate capacity.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    list_credit_notes,
    make_officer_headers,
    make_qa_headers,
    setup_accepted_order,
    setup_delivered_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    confirm_delivery,
    create_agent,
    create_catalog_item,
    create_scheduled_delivery,
    create_sent_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    dispatch_delivery,
    file_complaint,
    set_clock,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def _water_item(sku="WATER-17"):
    return dict(
        sku=sku, name="Water 1L", category="PROVISIONS",
        bonded_eligible=False, requires_cold_chain=False,
        base_price_cents=120, duty_rate_pct=0,
    )


# ===========================================================================
# cross_entity_state_dependency / quotation_accept_requires_vessel_in_port
# ===========================================================================

class TestQuotationAcceptRequiresVesselInPort:
    def test_accept_while_scheduled_fails_and_quotation_stays_sent(self, api):
        """PRD §3.4: "then the cross-entity gate requires the vessel call to be
        `IN_PORT` — a quotation cannot be accepted for a vessel that has not
        arrived — else `ERR_VESSEL_CALL_NOT_IN_PORT`". The quotation's own state
        is valid (SENT); only the linked VesselCall's state blocks the
        transition, and the failed accept leaves the quotation SENT.

        Design: Difficulty/cross_entity_state_dependency/quotation_accept_requires_vessel_in_port
        """
        agent = create_agent(name="Agent Rho")
        water = create_catalog_item(**_water_item("WATER-17"))
        create_stock_lot(water["id"], lot_code="DS-W17", received_qty=10000)
        call = create_vessel_call(agent["id"])  # never arrived: stays SCHEDULED
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=100)
        quo = create_sent_quotation(req["id"], water["id"], qty=100, unit_price_cents=120)
        set_clock("2026-08-10T09:00:00Z")  # within validity

        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_VESSEL_CALL_NOT_IN_PORT)
        quotation = get_success_data(api_client.get_quotation(quo["id"], SALES))
        assert quotation["status"] == "SENT", "No side effects fire on the failed accept"

    def test_accept_after_arrival_succeeds(self, api):
        """PRD §3.4: "A successful accept creates the `Order` in one atomic act".
        Same fixture but the vessel has arrived: the cross-entity gate passes and
        the accept succeeds, creating an OPEN x UNINVOICED order.

        Design: Difficulty/cross_entity_state_dependency/quotation_accept_requires_vessel_in_port
        """
        ctx = setup_accepted_order(
            qty=100, unit_price_cents=120,
            item_overrides=_water_item("WATER-17"),
            lot_overrides=dict(lot_code="DS-W17", received_qty=10000),
        )
        assert ctx["order"]["fulfillment_status"] == "OPEN"
        assert ctx["order"]["payment_status"] == "UNINVOICED"
        quotation = get_success_data(api_client.get_quotation(ctx["quotation"]["id"], SALES))
        assert quotation["status"] == "ACCEPTED"


# ===========================================================================
# cross_entity_state_dependency / bonded_delivery_requires_customs_cleared
# ===========================================================================

def _setup_bonded_order_customs_pending():
    """WHISKY order accepted while clearance stays PENDING (accept has no
    customs gate); delivery attempted while clearance still PENDING."""
    return setup_accepted_order(
        qty=10, unit_price_cents=5000, requested_qty=10,
        item_overrides=dict(
            sku="WHISKY-18", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        ),
        lot_overrides=dict(lot_code="BW-18", storage_tier="BONDED_WAREHOUSE",
                           received_qty=500, capacity_qty=0),
        call_overrides=dict(foreign_going=True),
    )


class TestBondedDeliveryRequiresCustomsCleared:
    def test_bonded_delivery_pending_clearance_rejected(self, api):
        """PRD §3.6: "And the customs gate: if any planned line's catalog item is
        `bonded_eligible`, the vessel call's `customs_clearance_status` must be
        `CLEARED` at scheduling time, else the create is refused with
        `ERR_CUSTOMS_CLEARANCE_REQUIRED`." With clearance PENDING the delivery
        create fails even though the order, stock, and window are all valid, and
        no delivery is created.

        Design: Difficulty/cross_entity_state_dependency/bonded_delivery_requires_customs_cleared
        """
        ctx = _setup_bonded_order_customs_pending()
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-10T10:00:00Z",
            "window_end": "2026-08-10T14:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 10}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_CUSTOMS_CLEARANCE_REQUIRED)
        deliveries, _meta = validate_paginated(
            api_client.list_deliveries(ctx["order"]["id"], WAREHOUSE)
        )
        assert deliveries == [], "No Delivery is created for the order"

    def test_bonded_delivery_after_clearance_succeeds(self, api):
        """PRD §3.6: "A successfully created delivery is `SCHEDULED`". Same bonded
        order but customs CLEARED before scheduling: the gate passes and the
        delivery is created SCHEDULED.

        Design: Difficulty/cross_entity_state_dependency/bonded_delivery_requires_customs_cleared
        """
        ctx = _setup_bonded_order_customs_pending()
        from test_helpers.fixtures import customs_decision
        customs_decision(ctx["call"]["id"], "CLEARED")
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-10T10:00:00Z",
            "window_end": "2026-08-10T14:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 10}],
        }, WAREHOUSE)
        delivery = validate_success(resp, expected_status=201)
        assert delivery["status"] == "SCHEDULED"


# ===========================================================================
# cross_entity_state_dependency / credit_note_requires_issued_invoice
# ===========================================================================

class TestCreditNoteRequiresIssuedInvoice:
    def test_accept_fails_without_creditable_invoice(self, api):
        """PRD §3.12: "Acceptance additionally requires a creditable invoice to
        exist: among the order's invoices in `ISSUED` or `PARTIALLY_PAID`, the
        selector picks the latest `created_at` first, breaking ties toward the
        higher `total_cents`; if the candidate set is empty, or the computed
        credit amount would be zero or negative, acceptance fails with
        `ERR_NO_CREDITABLE_INVOICE`." Order delivered but never invoiced
        (payment UNINVOICED): the accept fails and the complaint stays
        SUBMITTED.

        Design: Difficulty/cross_entity_state_dependency/credit_note_requires_issued_invoice
        """
        ctx = setup_delivered_order(
            qty=1000, unit_price_cents=120,
            item_overrides=_water_item("WATER-19"),
            lot_overrides=dict(lot_code="DS-W19", received_qty=10000),
        )
        officer = make_officer_headers(ctx["call"]["id"])
        complaint = file_complaint(ctx["delivery"]["id"], ctx["item"]["id"], 10, officer)
        resp = api_client.accept_complaint(complaint["id"], make_qa_headers("qa-lead-1"))
        validate_error(resp, ApiErrorId.ERR_NO_CREDITABLE_INVOICE)
        # No credit note was created.
        notes, _meta = list_credit_notes()
        assert notes == [], "No CreditNote created on the failed accept"

    def test_accept_succeeds_once_invoice_issued(self, api):
        """PRD §3.12: "A successful accept auto-creates exactly one `CreditNote` in
        `APPLIED` status". Same fixture but with the order invoiced first: the
        accept succeeds and the complaint lands ACCEPTED.

        Design: Difficulty/cross_entity_state_dependency/credit_note_requires_issued_invoice
        """
        ctx = setup_delivered_order(
            qty=1000, unit_price_cents=120,
            item_overrides=_water_item("WATER-19"),
            lot_overrides=dict(lot_code="DS-W19", received_qty=10000),
        )
        invoice = get_success_data(api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 1.0}, TEST_USERS["finance_headers"],
        ))
        officer = make_officer_headers(ctx["call"]["id"])
        complaint = file_complaint(ctx["delivery"]["id"], ctx["item"]["id"], 10, officer)
        accepted = get_success_data(
            api_client.accept_complaint(complaint["id"], make_qa_headers("qa-lead-1"))
        )
        assert accepted["status"] == "ACCEPTED"


# ===========================================================================
# resource_temporal_overlap / delivery_window_closed_containment
# ===========================================================================

class TestDeliveryWindowClosedContainment:
    def test_window_start_one_second_before_eta_rejected(self, api):
        """PRD §3.6: "it must fit inside the vessel's port stay: `window_start` at
        or after the call's effective arrival (`actual_eta` once set, otherwise
        `scheduled_eta`) ... Containment is a closed interval; a window whose
        start equals the arrival or whose end equals the departure is
        admissible. A window outside the stay is `ERR_WINDOW_OUTSIDE_PORT_STAY`."

        Vessel arrived at actual_eta 2026-08-10T08:00:00Z (clock pinned): a
        window starting 07:59:59 (one second before) is rejected.

        Design: Difficulty/resource_temporal_overlap/delivery_window_closed_containment
        """
        ctx = setup_accepted_order(
            qty=200, unit_price_cents=120,
            item_overrides=_water_item("WATER-20"),
            lot_overrides=dict(lot_code="DS-W20", received_qty=10000),
        )
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-10T07:59:59Z",  # one second before actual_eta
            "window_end": "2026-08-10T12:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 100}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_PORT_STAY)

    def test_window_start_equal_to_eta_accepted(self, api):
        """PRD §3.6: "Containment is a closed interval; a window whose start equals
        the arrival or whose end equals the departure is admissible."
        window_start exactly == actual_eta 2026-08-10T08:00:00Z => accepted,
        delivery SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/delivery_window_closed_containment
        """
        ctx = setup_accepted_order(
            qty=200, unit_price_cents=120,
            item_overrides=_water_item("WATER-20"),
            lot_overrides=dict(lot_code="DS-W20", received_qty=10000),
        )
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-10T08:00:00Z",  # == actual_eta (inclusive)
            "window_end": "2026-08-10T12:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 100}],
        }, WAREHOUSE)
        delivery = validate_success(resp, expected_status=201)
        assert delivery["status"] == "SCHEDULED"


# ===========================================================================
# resource_temporal_overlap / cold_store_half_open_aggregate_capacity
# ===========================================================================

def _fish_item():
    return dict(
        sku="FISH-21", name="Frozen Salmon 1kg", category="PROVISIONS",
        bonded_eligible=False, requires_cold_chain=True,
        base_price_cents=2500, duty_rate_pct=5,
    )


def _accept_cold_order(agent, lot_item_id, vessel_suffix, eta, etd, qty, accept_clock):
    """Accept a cold-chain order on a dedicated vessel call. Returns order."""
    call = create_vessel_call(
        agent["id"], vessel_name=f"MV {vessel_suffix}",
        scheduled_eta=eta, scheduled_etd=etd,
    )
    officer = make_officer_headers(call["id"])
    req = create_submitted_requisition(call["id"], lot_item_id, requested_qty=qty)
    quo = create_sent_quotation(
        req["id"], lot_item_id, qty=qty, unit_price_cents=2500,
        valid_until="2026-08-13T00:00:00Z",
    )
    set_clock(accept_clock)
    arrive_vessel_call(call["id"])
    return api_client.accept_quotation(quo["id"], officer)


class TestColdStoreHalfOpenAggregateCapacity:
    def test_touching_windows_do_not_overlap(self, api):
        """PRD §3.5: "Windows that merely touch — one order's
        `reservation_window_end` equal to another's `accepted_at` — do **not**
        overlap under half-open semantics." Vessel A accepts 60 cold units with
        window [2026-08-10T08:00:00Z, 2026-08-12T00:00:00Z); vessel B accepts 60
        at exactly 2026-08-12T00:00:00Z with window [2026-08-12T00:00:00Z,
        2026-08-16T00:00:00Z): touching, not overlapping; 60 <= 100 capacity =>
        B accepted.

        Design: Difficulty/resource_temporal_overlap/cold_store_half_open_aggregate_capacity
        """
        agent = create_agent(name="Agent Phi")
        fish = create_catalog_item(**_fish_item())
        create_stock_lot(fish["id"], lot_code="CS-21", storage_tier="COLD_STORE",
                         received_qty=1000, capacity_qty=100)
        resp_a = _accept_cold_order(agent, fish["id"], "Phoebe",
                                    "2026-08-10T08:00:00Z", "2026-08-12T00:00:00Z",
                                    60, "2026-08-10T08:00:00Z")
        order_a = validate_success(resp_a, expected_status=201)
        assert order_a["fulfillment_status"] == "OPEN"

        resp_b = _accept_cold_order(agent, fish["id"], "Pandora",
                                    "2026-08-12T00:00:00Z", "2026-08-16T00:00:00Z",
                                    60, "2026-08-12T00:00:00Z")
        order_b = validate_success(resp_b, expected_status=201)
        assert order_b["fulfillment_status"] == "OPEN", (
            "B's window merely touches A's: no overlap under half-open semantics"
        )

    def test_overlapping_windows_exceeding_capacity_rejected(self, api):
        """PRD §3.5: "each `COLD_STORE` lot enforces an aggregate capacity: the sum
        of reserved allocations whose half-open window `[accepted_at,
        reservation_window_end)` overlaps the new order's window, plus the new
        allocation, must not exceed the lot's `capacity_qty`... A violation
        rejects the accept with `ERR_COLD_CHAIN_CAPACITY_EXCEEDED`."

        Vessel A holds 60 cold units over [2026-08-10T08:00, 2026-08-12T00:00).
        Vessel C accepts at 2026-08-11T00:00 with ETD 2026-08-16T00:00 — its
        window overlaps A's, and 60 + 60 = 120 > capacity 100 =>
        ERR_COLD_CHAIN_CAPACITY_EXCEEDED (aggregate, not boolean).

        Design: Difficulty/resource_temporal_overlap/cold_store_half_open_aggregate_capacity
        """
        agent = create_agent(name="Agent Phi")
        fish = create_catalog_item(**_fish_item())
        create_stock_lot(fish["id"], lot_code="CS-21", storage_tier="COLD_STORE",
                         received_qty=1000, capacity_qty=100)
        resp_a = _accept_cold_order(agent, fish["id"], "Phoebe",
                                    "2026-08-10T08:00:00Z", "2026-08-12T00:00:00Z",
                                    60, "2026-08-10T08:00:00Z")
        validate_success(resp_a, expected_status=201)

        resp_c = _accept_cold_order(agent, fish["id"], "Persephone",
                                    "2026-08-11T00:00:00Z", "2026-08-16T00:00:00Z",
                                    60, "2026-08-11T00:00:00Z")
        validate_error(resp_c, ApiErrorId.ERR_COLD_CHAIN_CAPACITY_EXCEEDED)
