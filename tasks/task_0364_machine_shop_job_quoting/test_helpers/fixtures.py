"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state reached by
5-15 API calls (RFQ -> PartLine -> submit -> Quote -> RoutingOp -> price ->
approve -> MaterialLot -> WorkOrder -> allocate -> release -> MachineSlot ->
... -> Inspection -> disposition -> Shipment -> Invoice). These helpers
encapsulate those preambles so each test focuses on its single assertion.

Every helper uses get_success_data() (the lenient validator) internally, so a
setup misstep surfaces as a clear "Setup failed" rather than a confusing
assertion error. Each test starts against an empty database (the harness
restarts the server before every test), so every helper builds its preconditions
from scratch using only PRD-declared endpoints.

All five roles are opaque operators (X-User-ID is never matched against an
entity id), so the shared TEST_USERS constants are the canonical headers for
every call — no per-instance header builders are needed.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_rfq_payload, create_part_line_payload, create_quote_payload,
    create_routing_op_payload, create_work_order_payload, create_material_lot_payload,
    create_machine_slot_payload, create_inspection_station_payload,
    create_inspection_payload, disposition_payload, create_shipment_payload,
    create_invoice_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]
SCHED = TEST_USERS["scheduler_headers"]
MAT = TEST_USERS["material_controller_headers"]
INSP = TEST_USERS["inspector_headers"]


# ─── Tier 1: Intake / Estimating progression ────────────────────────────────
def create_draft_rfq(**overrides):
    """A DRAFT RFQ. Returns the RFQ dict."""
    return get_success_data(api_client.create_rfq(create_rfq_payload(**overrides), ADMIN))


def create_rfq_with_part_line(part_line_overrides=None, **rfq_overrides):
    """A DRAFT RFQ with one PartLine. Returns (rfq, part_line)."""
    rfq = create_draft_rfq(**rfq_overrides)
    pl = get_success_data(api_client.create_part_line(
        rfq["id"], create_part_line_payload(**(part_line_overrides or {})), ADMIN))
    return rfq, pl


def create_submitted_rfq_with_part_line(part_line_overrides=None, **rfq_overrides):
    """A SUBMITTED RFQ with one PartLine. Returns (rfq, part_line)."""
    rfq, pl = create_rfq_with_part_line(part_line_overrides, **rfq_overrides)
    get_success_data(api_client.submit_rfq(rfq["id"], ADMIN))
    return rfq, pl


def create_draft_quote(part_line_overrides=None, quote_overrides=None, **rfq_overrides):
    """SUBMITTED RFQ + PartLine + DRAFT Quote (no routing). Returns (rfq, pl, quote)."""
    rfq, pl = create_submitted_rfq_with_part_line(part_line_overrides, **rfq_overrides)
    quote = get_success_data(api_client.create_quote(
        create_quote_payload(rfq["id"], pl["id"], **(quote_overrides or {})), EST))
    return rfq, pl, quote


def add_routing_op(quote_id, seq, machine_class, estimated_cycle_min, **overrides):
    """Add one RoutingOp to a DRAFT quote. Returns the routing op dict."""
    return get_success_data(api_client.create_routing_op(
        quote_id,
        create_routing_op_payload(seq, machine_class, estimated_cycle_min, **overrides),
        EST))


def create_priced_quote(routing_ops, part_line_overrides=None, quote_overrides=None,
                        **rfq_overrides):
    """SUBMITTED RFQ + PartLine + DRAFT Quote + routing ops, then PRICED.

    `routing_ops` is a list of payload-kwargs dicts, each supplying at least
    seq / machine_class / estimated_cycle_min (and optionally setup_fee_cents).
    Returns (rfq, part_line, priced_quote, ops_list).
    """
    rfq, pl, quote = create_draft_quote(part_line_overrides, quote_overrides, **rfq_overrides)
    ops = []
    for spec in routing_ops:
        ops.append(add_routing_op(quote["id"], **spec))
    priced = get_success_data(api_client.price_quote(quote["id"], EST))
    return rfq, pl, priced, ops


def create_approved_quote(routing_ops, part_line_overrides=None, quote_overrides=None,
                          **rfq_overrides):
    """As create_priced_quote, then APPROVED (OCC with the priced version).

    Returns (rfq, part_line, approved_quote, ops_list).
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops, part_line_overrides, quote_overrides, **rfq_overrides)
    approved = get_success_data(api_client.approve_quote(
        priced["id"], {"expected_quote_version": priced["version"]}, EST))
    return rfq, pl, approved, ops


# ─── Tier 2: Material ────────────────────────────────────────────────────────
def receive_lot(material_spec, qty_received, unit_cost_cents, received_at, **overrides):
    """Receive one MaterialLot into stock. Returns the lot dict."""
    return get_success_data(api_client.create_material_lot(
        create_material_lot_payload(material_spec, qty_received, unit_cost_cents,
                                    received_at, **overrides),
        MAT))


# ─── Tier 3: WorkOrder lifecycle shortcuts ───────────────────────────────────
def create_planned_work_order(quote_id, part_line_id, qty_ordered, qty_started):
    """A PLANNED WorkOrder from an approved quote. Returns the WO dict."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(quote_id, part_line_id, qty_ordered, qty_started), ADMIN))


def create_allocated_work_order(routing_ops, qty_ordered, qty_started, lots,
                                part_line_overrides=None, quote_overrides=None,
                                **rfq_overrides):
    """Full chain to a PLANNED WO with material allocated.

    `lots` is a list of receive_lot kwargs dicts (each material_spec/qty_received/
    unit_cost_cents/received_at). Lots are received BEFORE allocation so the FIFO
    waterfall sees them in received_at order.
    Returns (rfq, part_line, quote, ops, wo, created_lots).
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops, part_line_overrides, quote_overrides, **rfq_overrides)
    created_lots = [receive_lot(**spec) for spec in lots]
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered, qty_started)
    get_success_data(api_client.allocate_material(wo["id"], MAT))
    wo = get_success_data(api_client.get_work_order(wo["id"], ADMIN))
    return rfq, pl, quote, ops, wo, created_lots


def create_released_work_order(routing_ops, qty_ordered, qty_started, lots,
                               part_line_overrides=None, quote_overrides=None,
                               **rfq_overrides):
    """Full chain to a RELEASED WorkOrder (OCC with the post-allocation version).

    Returns (rfq, part_line, quote, ops, wo, created_lots).
    """
    rfq, pl, quote, ops, wo, created_lots = create_allocated_work_order(
        routing_ops, qty_ordered, qty_started, lots,
        part_line_overrides, quote_overrides, **rfq_overrides)
    get_success_data(api_client.release_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, ADMIN))
    wo = get_success_data(api_client.get_work_order(wo["id"], ADMIN))
    return rfq, pl, quote, ops, wo, created_lots


def book_slot(machine_class, machine_code, routing_op_id, start_min, end_min):
    """Book a CNC machine slot for a routing op. Returns the slot dict."""
    return get_success_data(api_client.create_machine_slot(
        create_machine_slot_payload(machine_class, machine_code, routing_op_id,
                                    start_min, end_min),
        SCHED))


def create_in_process_work_order(routing_ops, qty_ordered, qty_started, lots,
                                 slot_specs, part_line_overrides=None,
                                 quote_overrides=None, **rfq_overrides):
    """Full chain to an IN_PROCESS WorkOrder.

    Books a machine slot on each routing op (`slot_specs` is a list of dicts with
    machine_class/machine_code, paired positionally with `ops`); the first
    booked slot bubbles the WO RELEASED -> IN_PROCESS.
    Returns (rfq, part_line, quote, ops, wo, created_lots, slots).
    """
    rfq, pl, quote, ops, wo, created_lots = create_released_work_order(
        routing_ops, qty_ordered, qty_started, lots,
        part_line_overrides, quote_overrides, **rfq_overrides)
    slots = []
    for op, spec in zip(ops, slot_specs):
        slots.append(book_slot(
            spec["machine_class"], spec["machine_code"], op["id"],
            spec["start_min"], spec["end_min"]))
    wo = get_success_data(api_client.get_work_order(wo["id"], ADMIN))
    return rfq, pl, quote, ops, wo, created_lots, slots


# ─── Tier 4: Inspection station + inspection ─────────────────────────────────
def create_station(name="CMM-TEST", supports_mode="ALL", buffer_min=15):
    """Create one InspectionStation. Returns the station dict."""
    return get_success_data(api_client.create_inspection_station(
        create_inspection_station_payload(name=name, supports_mode=supports_mode,
                                          buffer_min=buffer_min),
        INSP))


def open_inspection(work_order_id, station_id, mode, window_start_min, window_end_min):
    """Open an inspection booking on a station. Returns the inspection dict."""
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(work_order_id, station_id, mode,
                                  window_start_min, window_end_min),
        INSP))


def create_open_inspection_on_in_process_wo(routing_ops, qty_ordered, qty_started, lots,
                                            slot_specs, station_supports_mode="ALL",
                                            station_buffer_min=15, inspection_mode="FINAL",
                                            window_start_min=200, window_end_min=260,
                                            part_line_overrides=None, quote_overrides=None,
                                            **rfq_overrides):
    """Full chain to an IN_PROCESS WO with one OPEN inspection ready to disposition.

    Returns (rfq, part_line, quote, ops, wo, lots, slots, station, inspection).
    """
    rfq, pl, quote, ops, wo, created_lots, slots = create_in_process_work_order(
        routing_ops, qty_ordered, qty_started, lots, slot_specs,
        part_line_overrides, quote_overrides, **rfq_overrides)
    station = create_station(name="CMM-FX", supports_mode=station_supports_mode,
                             buffer_min=station_buffer_min)
    insp = open_inspection(wo["id"], station["id"], inspection_mode,
                           window_start_min, window_end_min)
    return rfq, pl, quote, ops, wo, created_lots, slots, station, insp


def disposition(inspection_id, qty_inspected, qty_accepted, qty_rework, qty_scrap):
    """Disposition an OPEN inspection. Returns the dispositioned inspection dict."""
    return get_success_data(api_client.disposition_inspection(
        inspection_id,
        disposition_payload(qty_inspected, qty_accepted, qty_rework, qty_scrap),
        INSP))


# ─── Tier 5: Delivery / Billing terminal states ─────────────────────────────
def ship(work_order_id, qty_shipped, promised_date, actual_ship_date):
    """Create a shipment for a WO. Returns the shipment dict."""
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(work_order_id, qty_shipped, promised_date, actual_ship_date),
        ADMIN))


def invoice(shipment_id):
    """Create an invoice for a shipment. Returns the invoice dict."""
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(shipment_id), ADMIN))


def setup_completed_wo_ready_to_ship(qty=10, material_unit_cost_cents=1500,
                                     scrap_allowance_pct=5):
    """Full canonical chain to a COMPLETED WorkOrder with qty_accepted == qty,
    ready for a shipment. Uses the canonical quote shape (MILL_3AX 12.5/8000 +
    LATHE 6.0/4500) so quoted_unit_price_cents == 7469 at qty=10.

    Returns (rfq, part_line, quote, wo).
    """
    routing_ops = [
        {"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 12.5, "setup_fee_cents": 8000},
        {"seq": 2, "machine_class": "LATHE", "estimated_cycle_min": 6.0, "setup_fee_cents": 4500},
    ]
    slot_specs = [
        {"machine_class": "MILL_3AX", "machine_code": "VF2-FX", "start_min": 0, "end_min": 150},
        {"machine_class": "LATHE", "machine_code": "L-FX", "start_min": 0, "end_min": 80},
    ]
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        create_open_inspection_on_in_process_wo(
            routing_ops, qty_ordered=qty, qty_started=qty,
            lots=[{"material_spec": "AL_6061", "qty_received": qty,
                   "unit_cost_cents": 1500, "received_at": "2026-06-01T00:00:00Z"}],
            slot_specs=slot_specs,
            part_line_overrides={"material_spec": "AL_6061", "quantity": qty,
                                 "tolerance_class": "STANDARD"},
            quote_overrides={"material_unit_cost_cents": material_unit_cost_cents,
                             "scrap_allowance_pct": scrap_allowance_pct},
        )
    disposition(insp["id"], qty_inspected=qty, qty_accepted=qty, qty_rework=0, qty_scrap=0)
    wo = get_success_data(api_client.get_work_order(wo["id"], ADMIN))
    return rfq, pl, quote, wo
