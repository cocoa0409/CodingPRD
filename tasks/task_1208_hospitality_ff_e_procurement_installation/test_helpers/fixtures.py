"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error, not a confusing
assertion failure deep inside a test.

Tiers:
  1. State progression (project -> PROCUREMENT, spec -> BRAND_APPROVED, ...)
  2. Entity hierarchy (project + budget line + spec + bid + PO + line)
  3. Full lifecycle shortcuts (PO -> READY_TO_SHIP, shipment -> IN_TRANSIT, ...)
  4. Accumulation / threshold targeting (received pipelines with exact
     quantities, change-order scenarios with exact committed totals)
  5. Terminal / late-stage states (shipment RECEIVED, window IN_PROGRESS)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_project_payload,
    create_budget_line_payload,
    create_spec_item_payload,
    create_bid_payload,
    create_purchase_order_payload,
    create_po_line_payload,
    create_shipment_payload,
    create_receiving_event_payload,
    create_damage_claim_payload,
    create_room_payload,
    create_installation_window_payload,
    create_installation_task_payload,
    create_change_order_payload,
)
from .test_users import TEST_USERS, make_purchasing_agent_headers

PA = TEST_USERS["purchasing_agent_headers"]
BA = TEST_USERS["brand_approver_headers"]
VEN = TEST_USERS["vendor_headers"]
WR = TEST_USERS["warehouse_receiver_headers"]
IM = TEST_USERS["installation_manager_headers"]
OR = TEST_USERS["owner_rep_headers"]


# ─── Tier 1: single-call primitives ─────────────────────────────────────────

def create_project(**overrides) -> dict:
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), PA)
    )


def get_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, PA))


def add_budget_line(project_id, category="FURNITURE", budgeted_cents=8_000_000) -> dict:
    return get_success_data(
        api_client.create_budget_line(
            create_budget_line_payload(
                project_id, category=category, budgeted_cents=budgeted_cents
            ),
            PA,
        )
    )


def get_budget_line(budget_line_id) -> dict:
    return get_success_data(api_client.get_budget_line(budget_line_id, PA))


def advance_project_lifecycle(project_id, to_status) -> dict:
    return get_success_data(
        api_client.transition_project_lifecycle(
            project_id, {"to_status": to_status}, PA
        )
    )


def create_spec(project_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_spec_item(create_spec_item_payload(project_id, **overrides), PA)
    )


def get_spec(spec_item_id) -> dict:
    return get_success_data(api_client.get_spec_item(spec_item_id, PA))


def submit_spec(spec_item_id) -> dict:
    return get_success_data(api_client.submit_spec_item(spec_item_id, PA))


def brand_review(spec_item_id, decision, notes=None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(
        api_client.brand_review_spec_item(spec_item_id, payload, BA)
    )


def create_bid(spec_item_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bid(create_bid_payload(spec_item_id, **overrides), VEN)
    )


def get_bid(bid_id) -> dict:
    return get_success_data(api_client.get_bid(bid_id, PA))


def sample_decide(bid_id, outcome) -> dict:
    return get_success_data(
        api_client.sample_decision_bid(bid_id, {"outcome": outcome}, PA)
    )


def award(bid_id) -> dict:
    return get_success_data(api_client.award_bid(bid_id, PA))


def create_po(project_id, vendor_name="VENDA") -> dict:
    return get_success_data(
        api_client.create_purchase_order(
            create_purchase_order_payload(project_id, vendor_name=vendor_name), PA
        )
    )


def get_po(purchase_order_id) -> dict:
    return get_success_data(api_client.get_purchase_order(purchase_order_id, PA))


def add_po_line(po_id, spec_item_id, quantity_ordered=40, declared_cube_m3=10) -> dict:
    return get_success_data(
        api_client.add_purchase_order_line(
            po_id,
            create_po_line_payload(
                spec_item_id,
                quantity_ordered=quantity_ordered,
                declared_cube_m3=declared_cube_m3,
            ),
            PA,
        )
    )


def get_po_line(po_line_id) -> dict:
    return get_success_data(api_client.get_po_line(po_line_id, PA))


def transition_po(po_id, axis, to_status, headers) -> dict:
    return get_success_data(
        api_client.transition_purchase_order(
            po_id, {"axis": axis, "to_status": to_status}, headers
        )
    )


def create_shipment(project_id, carrier_name="CARR") -> dict:
    return get_success_data(
        api_client.create_shipment(
            create_shipment_payload(project_id, carrier_name=carrier_name), PA
        )
    )


def transition_shipment(shipment_id, to_status) -> dict:
    return get_success_data(
        api_client.transition_shipment(shipment_id, {"to_status": to_status}, PA)
    )


def attach_po_to_shipment(shipment_id, po_id) -> dict:
    return get_success_data(
        api_client.attach_purchase_order(
            shipment_id, {"purchase_order_id": po_id}, PA
        )
    )


def create_and_post_receiving_event(shipment_id, entries) -> dict:
    """entries: list of {"po_line_id", "qty_received", "qty_damaged"}.
    Creates the event (DRAFT) and posts it. Returns the POSTED event."""
    event = get_success_data(
        api_client.create_receiving_event(
            create_receiving_event_payload(shipment_id, entries), WR
        )
    )
    return get_success_data(
        api_client.transition_receiving_event(event["id"], {"to_status": "POSTED"}, WR)
    )


def create_claim(po_line_id, claim_type="DAMAGE", quantity=1,
                 claimed_credit_cents=10000) -> dict:
    return get_success_data(
        api_client.create_damage_claim(
            create_damage_claim_payload(
                po_line_id,
                claim_type=claim_type,
                quantity=quantity,
                claimed_credit_cents=claimed_credit_cents,
            ),
            PA,
        )
    )


def transition_claim(claim_id, to_status, headers=None,
                     approved_credit_cents=None) -> dict:
    payload = {"to_status": to_status}
    if approved_credit_cents is not None:
        payload["approved_credit_cents"] = approved_credit_cents
    return get_success_data(
        api_client.transition_damage_claim(claim_id, payload, headers or PA)
    )


def create_room(project_id, floor_number=1, room_number="R-101",
                room_type="GUEST_KING") -> dict:
    return get_success_data(
        api_client.create_room(
            create_room_payload(
                project_id,
                floor_number=floor_number,
                room_number=room_number,
                room_type=room_type,
            ),
            IM,
        )
    )


def create_window(project_id, floor_number=1, start_date="2026-07-01",
                  end_date="2026-07-05", crew_count=1) -> dict:
    return get_success_data(
        api_client.create_installation_window(
            create_installation_window_payload(
                project_id,
                floor_number=floor_number,
                start_date=start_date,
                end_date=end_date,
                crew_count=crew_count,
            ),
            IM,
        )
    )


def transition_window(window_id, to_status) -> dict:
    return get_success_data(
        api_client.transition_installation_window(
            window_id, {"to_status": to_status}, IM
        )
    )


def create_task(window_id, room_id, po_line_id, quantity=1) -> dict:
    return get_success_data(
        api_client.create_installation_task(
            create_installation_task_payload(
                window_id, room_id, po_line_id, quantity=quantity
            ),
            IM,
        )
    )


def complete_task(task_id) -> dict:
    return get_success_data(api_client.complete_installation_task(task_id, IM))


def propose_change_order(project_id, adjustments, title="Change order",
                         proposer_headers=None) -> dict:
    """Propose a change order. proposer_headers determine the recorded
    proposer_user_id (segregation of duties)."""
    return get_success_data(
        api_client.create_change_order(
            create_change_order_payload(project_id, adjustments, title=title),
            proposer_headers or make_purchasing_agent_headers("pa-1"),
        )
    )


def current_project_version(project_id) -> int:
    return get_project(project_id)["version"]


def current_po_line_version(po_line_id) -> int:
    return get_po_line(po_line_id)["version"]


def apply_change_order_now(change_order_id, expected_project_version,
                           approver_headers) -> dict:
    return get_success_data(
        api_client.apply_change_order(
            change_order_id,
            {"expected_project_version": expected_project_version},
            approver_headers,
        )
    )


# ─── Tier 2: entity hierarchy ────────────────────────────────────────────────

def create_procurement_project(*, name="P", hotel_name="H",
                               brand_program="MARQUEE_SELECT",
                               total_budget_cents=10_000_000,
                               unallocated_contingency_cents=0,
                               default_crew_capacity_per_floor_day=None,
                               category="FURNITURE",
                               budgeted_cents=8_000_000,
                               advance=True) -> dict:
    """Project + one budget line + (optionally) lifecycle -> PROCUREMENT.
    Returns {"project": ..., "budget_line": ...}."""
    overrides = {
        "name": name,
        "hotel_name": hotel_name,
        "brand_program": brand_program,
        "total_budget_cents": total_budget_cents,
        "unallocated_contingency_cents": unallocated_contingency_cents,
    }
    if default_crew_capacity_per_floor_day is not None:
        overrides["default_crew_capacity_per_floor_day"] = (
            default_crew_capacity_per_floor_day
        )
    project = create_project(**overrides)
    budget_line = add_budget_line(project["id"], category, budgeted_cents)
    if advance:
        project = advance_project_lifecycle(project["id"], "PROCUREMENT")
    return {"project": project, "budget_line": budget_line}


def create_approved_spec(project_id, **overrides) -> dict:
    """Spec -> SUBMITTED -> BRAND_APPROVED. Returns the approved spec."""
    spec = create_spec(project_id, **overrides)
    submit_spec(spec["id"])
    return brand_review(spec["id"], "APPROVE")


def create_awarded_spec(project_id, *, vendor_name="VENDA",
                        unit_price_cents=None, freight_estimate_cents=0,
                        lead_time_days=14, **spec_overrides) -> tuple:
    """Spec approved, bid submitted and sample-approved, then awarded.
    Returns (spec, AWARDED bid)."""
    spec = create_approved_spec(project_id, **spec_overrides)
    bid = create_bid(
        spec["id"],
        vendor_name=vendor_name,
        unit_price_cents=(
            unit_price_cents
            if unit_price_cents is not None
            else spec_overrides.get("unit_budget_cents", 15000)
        ),
        freight_estimate_cents=freight_estimate_cents,
        lead_time_days=lead_time_days,
    )
    sample_decide(bid["id"], "APPROVED")
    bid = award(bid["id"])
    return spec, bid


def create_po_with_lines(project_id, line_specs, vendor_name="VENDA") -> tuple:
    """PO plus one line per (spec, quantity, cube) triple.
    line_specs: list of dicts {spec, quantity_ordered, declared_cube_m3}.
    Returns (po, [line, ...])."""
    po = create_po(project_id, vendor_name)
    lines = [
        add_po_line(
            po["id"],
            ls["spec"]["id"],
            ls.get("quantity_ordered",
                   ls["spec"]["quantity_per_room"] * ls["spec"]["room_count"]),
            ls.get("declared_cube_m3", 10),
        )
        for ls in line_specs
    ]
    return po, lines


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────

def advance_po_to_ready_to_ship(po_id) -> dict:
    """FULFILLMENT ISSUED -> ACKNOWLEDGED -> READY_TO_SHIP (both by Vendor)."""
    transition_po(po_id, "FULFILLMENT", "ACKNOWLEDGED", VEN)
    return transition_po(po_id, "FULFILLMENT", "READY_TO_SHIP", VEN)


def create_consolidating_shipment_with_po(project_id, po_id,
                                          carrier_name="CARR") -> dict:
    """Shipment PLANNED -> CONSOLIDATING with the (READY_TO_SHIP) PO attached."""
    shipment = create_shipment(project_id, carrier_name)
    transition_shipment(shipment["id"], "CONSOLIDATING")
    attach_po_to_shipment(shipment["id"], po_id)
    return shipment


# ─── Tier 4: accumulation / threshold targeting ─────────────────────────────

def run_pipeline(*, name="P", brand_program="MARQUEE_SELECT",
                 total_budget_cents=10_000_000,
                 unallocated_contingency_cents=0,
                 category="FURNITURE", budgeted_cents=8_000_000,
                 line_specs, vendor_name="VENDA", carrier_name="CARR",
                 attach=None, seal=True, depart=True, receipts=None,
                 receive_shipment=False) -> dict:
    """Full procure-to-receive pipeline on one PO and one shipment.

    line_specs: list of dicts, one per spec/line:
        description, brand_standard_ref, quantity_per_room, room_count,
        unit_budget_cents, spec_overrides (dict of extra spec fields),
        unit_price_cents, freight_estimate_cents, lead_time_days,
        quantity_ordered (default quantity_per_room * room_count),
        declared_cube_m3 (default 10).
    attach: when True, walk the PO to READY_TO_SHIP and attach it to a fresh
        CONSOLIDATING shipment; defaults to True whenever a later stage
        (seal/depart/receipts/receive_shipment) is requested.
    receipts: list of events; each event is a list of
        (line_index, qty_received, qty_damaged) triples; every event is POSTED.

    Returns {"project", "budget_line", "specs", "bids", "po", "lines",
             "shipment", "events"}.
    """
    base = create_procurement_project(
        name=name, brand_program=brand_program,
        total_budget_cents=total_budget_cents,
        unallocated_contingency_cents=unallocated_contingency_cents,
        category=category, budgeted_cents=budgeted_cents,
    )
    project, budget_line = base["project"], base["budget_line"]

    specs, bids = [], []
    for i, ls in enumerate(line_specs):
        spec_kw = {
            "category": category,
            "description": ls.get("description", f"Item {i}"),
            "brand_standard_ref": ls.get("brand_standard_ref", f"MS-{i}"),
            "quantity_per_room": ls.get("quantity_per_room", 2),
            "room_count": ls.get("room_count", 20),
            "unit_budget_cents": ls.get("unit_budget_cents", 15000),
        }
        spec_kw.update(ls.get("spec_overrides") or {})
        unit_price = ls.get("unit_price_cents")
        if unit_price is None:
            unit_price = spec_kw["unit_budget_cents"]
        spec, bid = create_awarded_spec(
            project["id"],
            vendor_name=vendor_name,
            unit_price_cents=unit_price,
            freight_estimate_cents=ls.get("freight_estimate_cents", 0),
            lead_time_days=ls.get("lead_time_days", 14),
            **spec_kw,
        )
        specs.append(spec)
        bids.append(bid)

    po_line_specs = []
    for spec, ls in zip(specs, line_specs):
        entry = {
            "spec": spec,
            "declared_cube_m3": ls.get("declared_cube_m3", 10),
        }
        if "quantity_ordered" in ls:
            entry["quantity_ordered"] = ls["quantity_ordered"]
        po_line_specs.append(entry)
    po, lines = create_po_with_lines(project["id"], po_line_specs, vendor_name)

    if attach is None:
        attach = bool(seal or depart or receipts or receive_shipment)

    shipment, events = None, []
    if attach:
        advance_po_to_ready_to_ship(po["id"])
        shipment = create_consolidating_shipment_with_po(
            project["id"], po["id"], carrier_name
        )
    if seal and shipment is not None:
        transition_shipment(shipment["id"], "SEALED")
    if depart and shipment is not None:
        transition_shipment(shipment["id"], "IN_TRANSIT")
    if receipts and shipment is not None:
        for event_entries in receipts:
            entries = [
                {
                    "po_line_id": lines[idx]["id"],
                    "qty_received": qty,
                    "qty_damaged": damaged,
                }
                for (idx, qty, damaged) in event_entries
            ]
            events.append(create_and_post_receiving_event(shipment["id"], entries))
    if receive_shipment and shipment is not None:
        transition_shipment(shipment["id"], "RECEIVED")

    return {
        "project": get_project(project["id"]),
        "budget_line": get_budget_line(budget_line["id"]),
        "specs": specs,
        "bids": bids,
        "po": get_po(po["id"]),
        "lines": [get_po_line(l["id"]) for l in lines],
        "shipment": (
            get_success_data(api_client.get_shipment(shipment["id"], PA))
            if shipment is not None
            else None
        ),
        "events": events,
    }


def setup_change_order_scenario(*, total_budget_cents=10_000_000,
                                unallocated_contingency_cents=0,
                                budgeted_cents=9_000_000,
                                category="FURNITURE",
                                committed_line=None,
                                deltas=(("CO", 500000),),
                                proposer_headers=None,
                                advance=True) -> dict:
    """Project (+ optional PROCUREMENT) with a budget line, an optional
    committed PO line ((quantity_ordered, unit_price_cents) via
    committed_line), and one PROPOSED change order per (title, delta) in
    `deltas`. Returns {"project", "budget_line", "change_orders",
    "project_version", "po", "lines"}."""
    base = create_procurement_project(
        total_budget_cents=total_budget_cents,
        unallocated_contingency_cents=unallocated_contingency_cents,
        category=category, budgeted_cents=budgeted_cents, advance=advance,
    )
    project, budget_line = base["project"], base["budget_line"]

    po, lines = None, []
    if committed_line is not None:
        qty, unit_price = committed_line
        spec, _bid = create_awarded_spec(
            project["id"],
            category=category,
            description="Committed item",
            brand_standard_ref="MS-CI",
            quantity_per_room=1,
            room_count=qty,
            unit_budget_cents=unit_price,
            unit_price_cents=unit_price,
            lead_time_days=10,
        )
        po, lines = create_po_with_lines(
            project["id"],
            [{"spec": spec, "quantity_ordered": qty, "declared_cube_m3": 10}],
        )

    change_orders = [
        propose_change_order(
            project["id"],
            [{"budget_line_id": budget_line["id"], "delta_cents": delta}],
            title=title,
            proposer_headers=proposer_headers,
        )
        for title, delta in deltas
    ]
    return {
        "project": get_project(project["id"]),
        "budget_line": get_budget_line(budget_line["id"]),
        "change_orders": change_orders,
        "project_version": current_project_version(project["id"]),
        "po": po,
        "lines": lines,
    }


def setup_window_with_tasks(project_id, *, floor_number=1, room_number="R-101",
                            room_type="GUEST_KING", start_date="2026-07-01",
                            end_date="2026-07-05", crew_count=1, tasks=(),
                            release=False, start=False) -> dict:
    """Room + window + one task per (po_line_id, quantity) in `tasks`.
    Optionally releases and/or starts the window.
    Returns {"room", "window", "tasks"}."""
    room = create_room(
        project_id, floor_number=floor_number, room_number=room_number,
        room_type=room_type,
    )
    window = create_window(
        project_id, floor_number=floor_number, start_date=start_date,
        end_date=end_date, crew_count=crew_count,
    )
    created_tasks = [
        create_task(window["id"], room["id"], po_line_id, quantity)
        for po_line_id, quantity in tasks
    ]
    if release or start:
        window = transition_window(window["id"], "RELEASED")
    if start:
        window = transition_window(window["id"], "IN_PROGRESS")
    return {"room": room, "window": window, "tasks": created_tasks}


def setup_received_pipeline_with_window(*, line_qty=10, line_unit_price=10000,
                                        cube=5, received=10, damaged=0,
                                        spec_overrides=None,
                                        floor_number=7, room_number="R-701",
                                        room_type="GUEST_DOUBLE",
                                        start_date="2026-08-01",
                                        end_date="2026-08-04", crew_count=1,
                                        task_quantities=(4,),
                                        start_window=False,
                                        complete_tasks=False,
                                        budgeted_cents=8_000_000) -> dict:
    """Received pipeline (one line) plus a room, a window, and one task per
    quantity in `task_quantities` on that line. Optionally starts the window
    and/or completes every task. Returns the pipeline dict augmented with
    "room", "window", "tasks"."""
    scenario = run_pipeline(
        budgeted_cents=budgeted_cents,
        line_specs=[{
            "description": "Lamp", "brand_standard_ref": "MS-L",
            "quantity_per_room": 1, "room_count": line_qty,
            "unit_budget_cents": line_unit_price,
            "unit_price_cents": line_unit_price,
            "lead_time_days": 7,
            "quantity_ordered": line_qty,
            "declared_cube_m3": cube,
            "spec_overrides": spec_overrides,
        }],
        receipts=[[(0, received, damaged)]],
    )
    line_id = scenario["lines"][0]["id"]
    wt = setup_window_with_tasks(
        scenario["project"]["id"],
        floor_number=floor_number, room_number=room_number,
        room_type=room_type, start_date=start_date, end_date=end_date,
        crew_count=crew_count,
        tasks=[(line_id, q) for q in task_quantities],
        release=True, start=start_window,
    )
    scenario.update(wt)
    if complete_tasks:
        for task in scenario["tasks"]:
            complete_task(task["id"])
        scenario["lines"] = [get_po_line(line_id)]
    return scenario


def setup_two_pos_consolidating(*, po_specs, total_budget_cents=20_000_000,
                                budgeted_cents=8_000_000, category="FURNITURE",
                                vendor_name="VENDA") -> dict:
    """Project in PROCUREMENT with one budget line; for each entry in
    `po_specs` (dicts with spec fields plus quantity_ordered /
    declared_cube_m3 / unit_price_cents) an awarded spec, its own PO with one
    line walked to READY_TO_SHIP, and its own shipment in CONSOLIDATING with
    the PO attached. Returns {"project", "budget_line", "specs", "pos",
    "lines", "shipments"}."""
    base = create_procurement_project(
        total_budget_cents=total_budget_cents,
        category=category, budgeted_cents=budgeted_cents,
    )
    project, budget_line = base["project"], base["budget_line"]

    specs, pos, lines, shipments = [], [], [], []
    for i, ps in enumerate(po_specs):
        spec, _bid = create_awarded_spec(
            project["id"],
            vendor_name=vendor_name,
            category=category,
            description=ps.get("description", f"Bulk item {i}"),
            brand_standard_ref=ps.get("brand_standard_ref", f"MS-B{i}"),
            quantity_per_room=ps.get("quantity_per_room", 1),
            room_count=ps.get("room_count", 1),
            unit_budget_cents=ps.get("unit_budget_cents", 1000),
            unit_price_cents=ps.get("unit_price_cents", 1000),
            freight_estimate_cents=ps.get("freight_estimate_cents", 0),
            lead_time_days=ps.get("lead_time_days", 10),
        )
        po, po_lines = create_po_with_lines(
            project["id"],
            [{"spec": spec,
              "quantity_ordered": ps["quantity_ordered"],
              "declared_cube_m3": ps["declared_cube_m3"]}],
            vendor_name,
        )
        advance_po_to_ready_to_ship(po["id"])
        shipment = create_consolidating_shipment_with_po(
            project["id"], po["id"], carrier_name=f"CARR-{i}"
        )
        specs.append(spec)
        pos.append(po)
        lines.append(po_lines[0])
        shipments.append(shipment)

    return {
        "project": get_project(project["id"]),
        "budget_line": get_budget_line(budget_line["id"]),
        "specs": specs,
        "pos": [get_po(p["id"]) for p in pos],
        "lines": [get_po_line(l["id"]) for l in lines],
        "shipments": [
            get_success_data(api_client.get_shipment(s["id"], PA))
            for s in shipments
        ],
    }
