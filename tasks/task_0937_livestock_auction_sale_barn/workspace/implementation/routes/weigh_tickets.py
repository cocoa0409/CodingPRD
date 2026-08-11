"""Weigh tickets: opening, capture and voiding (PRD 3.4)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, fields, path_row, reference
from clock import clock, render_instant
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q0
from serialize import scale_status
from services.lots import governing_ticket, lot_tickets, recompute_lot_weights
from store import db, get, insert_versioned, touch

bp = Blueprint("weigh_tickets", __name__)
ALL = config.ALL_ROLES


def _context(lot):
    consignment = get("consignments", lot["consignment_id"])
    sale_day = get("sale_days", lot["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"]) if consignment else None
    return consignment, sale_day, party


@bp.post("/sale-barn/weigh-tickets")
def create_ticket():
    actor(["YardOperator"])
    data = body()
    v = fields(data, required=[
        ("lot_id", "string"),
        ("scale_id", "string"),
        ("head_on_draft", "integer"),
        ("gross_weight_lb", "number"),
        ("tare_weight_lb", "number"),
    ])
    check_min(v["head_on_draft"], 1, "head_on_draft")
    check_min(v["gross_weight_lb"], 0, "gross_weight_lb", inclusive=False)
    check_min(v["tare_weight_lb"], 0, "tare_weight_lb")

    lot = reference("lots", v["lot_id"], "Lot")
    scale = reference("scales", v["scale_id"], "Scale")
    consignment, sale_day, party = _context(lot)
    run_gates("weigh_tickets.create", sale_day=sale_day, lot=lot, party=party)

    # Rung 18 - the scale is certified at the current clock date.
    if scale_status(scale) != "CERTIFIED":
        fail("ERR_SCALE_NOT_CERTIFIED")

    tickets = lot_tickets(lot["id"])
    # Rung 19 - no other ticket on the lot is OPEN.
    if any(t["status"] == "OPEN" for t in tickets):
        fail("ERR_WEIGH_TICKET_OPEN")
    # Rung 20 - the re-weigh count is the lot's ticket count less one.
    # Adjudication of friction 6: the denominator is ALL tickets on the lot,
    # VOIDED and SUPERSEDED included, because the PRD calls it "the lot's
    # ticket count" and because ticket_seq is handed out from the same
    # unfiltered count; counting only CAPTURED tickets would let a barn void
    # its way past the cap indefinitely.
    if len(tickets) - 1 >= config.MAX_REWEIGH_COUNT:
        fail("ERR_REWEIGH_LIMIT_EXCEEDED")

    row = insert_versioned("weigh_tickets", {
        "lot_id": lot["id"],
        "scale_id": scale["id"],
        "head_on_draft": v["head_on_draft"],
        "gross_weight_lb": D(v["gross_weight_lb"]),
        "tare_weight_lb": D(v["tare_weight_lb"]),
        "net_weight_lb": None,
        "ticket_seq": len(tickets) + 1,
        "status": "OPEN",
        "opened_at": render_instant(clock.now()),
        "captured_at": None,
        "_captured_dt": None,
    })
    return ok(serialize.weigh_ticket(row), 201)


@bp.get("/sale-barn/weigh-tickets/<ticket_id>")
def read_ticket(ticket_id):
    actor(ALL)
    return ok(serialize.weigh_ticket(
        path_row("weigh_tickets", ticket_id, "WeighTicket")))


@bp.get("/sale-barn/weigh-tickets")
def list_tickets():
    actor(ALL)
    rows = list(db["weigh_tickets"].values())
    for key in ("lot_id", "scale_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.weigh_ticket)


@bp.post("/sale-barn/weigh-tickets/<ticket_id>/capture")
def capture(ticket_id):
    actor(["YardOperator"])
    ticket = path_row("weigh_tickets", ticket_id, "WeighTicket")
    lot = get("lots", ticket["lot_id"])
    consignment, sale_day, party = _context(lot)
    run_gates("weigh_tickets.capture", sale_day=sale_day, lot=lot, party=party)

    if ticket["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    scale = get("scales", ticket["scale_id"])
    if scale is None or scale_status(scale) != "CERTIFIED":
        fail("ERR_SCALE_NOT_CERTIFIED")

    prior = governing_ticket(lot["id"])
    if consignment is not None and consignment["weigh_basis"] == "STAND_ACTUAL" \
            and ticket["ticket_seq"] > 1 and prior is not None \
            and prior.get("_captured_dt") is not None:
        elapsed = (clock.now() - prior["_captured_dt"]).total_seconds() / 60.0
        if elapsed < config.STAND_TIME_MINUTES:
            fail("ERR_STAND_TIME_NOT_MET")

    ticket["status"] = "CAPTURED"
    ticket["captured_at"] = render_instant(clock.now())
    ticket["_captured_dt"] = clock.now()
    ticket["net_weight_lb"] = q0(D(ticket["gross_weight_lb"])
                                 - D(ticket["tare_weight_lb"]))
    touch(ticket)

    for other in lot_tickets(lot["id"]):
        if other["id"] != ticket["id"] and other["status"] == "CAPTURED" \
                and other["ticket_seq"] < ticket["ticket_seq"]:
            other["status"] = "SUPERSEDED"
            touch(other)

    recompute_lot_weights(lot)
    return ok(serialize.weigh_ticket(ticket))


@bp.post("/sale-barn/weigh-tickets/<ticket_id>/void")
def void_ticket(ticket_id):
    actor(["YardOperator"])
    ticket = path_row("weigh_tickets", ticket_id, "WeighTicket")
    lot = get("lots", ticket["lot_id"])
    consignment, sale_day, party = _context(lot)
    run_gates("weigh_tickets.void", sale_day=sale_day, lot=lot, party=party)
    if ticket["status"] not in ("OPEN", "CAPTURED"):
        fail("ERR_INVALID_STATE")
    ticket["status"] = "VOIDED"
    touch(ticket)
    # A SUPERSEDED ticket is NOT resurrected by voiding its successor; only
    # tickets standing in CAPTURED ever govern.
    recompute_lot_weights(lot)
    return ok(serialize.weigh_ticket(ticket))
