"""Consignments: booking, check-in and loss reporting (PRD 3.3)."""
from flask import Blueprint

import config
import serialize
from auth import actor, ownership
from bodyval import (body, check_max, check_min, enum_field, fields, path_row,
                     reference)
from clock import clock, render_instant
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D
from services.consignments import maybe_sorted
from services.pens import recompute_pens
from store import db, get, insert_versioned, touch

bp = Blueprint("consignments", __name__)
ALL = config.ALL_ROLES


@bp.post("/sale-barn/consignments")
def create_consignment():
    role, user_id = actor(["Consignor"])
    data = body()
    v = fields(data, required=[
        ("sale_day_id", "string"),
        ("consignor_party_id", "string"),
        ("species_class", "string"),
        ("head_received", "integer"),
        ("weigh_basis", "string"),
    ], optional=[
        ("pencil_shrink_pct", "number"),
        ("yardage_basis", "string"),
        ("commission_basis", "string"),
        ("ration_type", "string"),
        ("days_on_feed", "integer"),
        ("advances_amount", "number"),
        ("hold_until_funds", "boolean"),
    ])
    species_class = enum_field(data, "species_class", config.SPECIES_CLASSES)
    weigh_basis = enum_field(data, "weigh_basis", config.WEIGH_BASES)
    yardage_basis = enum_field(data, "yardage_basis", config.YARDAGE_BASES,
                               required=False, default="PER_HEAD_DAY")
    commission_basis = enum_field(data, "commission_basis", config.COMMISSION_BASES,
                                  required=False, default="TIERED_VALUE")
    ration_type = enum_field(data, "ration_type", config.RATION_TYPES,
                             required=False, default="NONE")

    check_min(v["head_received"], 1, "head_received")
    pencil_shrink_pct = v["pencil_shrink_pct"]
    if pencil_shrink_pct is None:
        pencil_shrink_pct = config.PENCIL_SHRINK_DEFAULT_PCT
    else:
        check_min(pencil_shrink_pct, 0, "pencil_shrink_pct")
        check_max(pencil_shrink_pct, config.PENCIL_SHRINK_MAX_PCT, "pencil_shrink_pct")
    days_on_feed = v["days_on_feed"] if v["days_on_feed"] is not None else 0
    check_min(days_on_feed, 0, "days_on_feed")
    advances_amount = v["advances_amount"] if v["advances_amount"] is not None else 0
    check_min(advances_amount, 0, "advances_amount")
    hold_until_funds = bool(v["hold_until_funds"]) if v["hold_until_funds"] is not None else False

    sale_day = reference("sale_days", v["sale_day_id"], "SaleDay")
    party = reference("parties", v["consignor_party_id"], "Party")

    ownership(role, user_id, party["id"])
    run_gates("consignments.create", sale_day=sale_day, party=party)
    if sale_day["status"] != "CHECK_IN_OPEN":
        fail("ERR_INVALID_STATE")

    row = insert_versioned("consignments", {
        "sale_day_id": sale_day["id"],
        "consignor_party_id": party["id"],
        "species_class": species_class,
        "head_received": v["head_received"],
        "weigh_basis": weigh_basis,
        "pencil_shrink_pct": D(pencil_shrink_pct),
        "yardage_basis": yardage_basis,
        "commission_basis": commission_basis,
        "ration_type": ration_type,
        "days_on_feed": days_on_feed,
        "advances_amount": D(advances_amount),
        "hold_until_funds": hold_until_funds,
        "status": "INTAKE",
        "checked_in_at": None,
        "_checked_in_dt": None,
        "head_unassigned": v["head_received"],
        "head_dead": 0,
        "head_condemned": 0,
        "head_withdrawn": 0,
    })
    return ok(serialize.consignment(row), 201)


@bp.get("/sale-barn/consignments/<consignment_id>")
def read_consignment(consignment_id):
    actor(ALL)
    return ok(serialize.consignment(
        path_row("consignments", consignment_id, "Consignment")))


@bp.get("/sale-barn/consignments")
def list_consignments():
    actor(ALL)
    rows = list(db["consignments"].values())
    for key in ("sale_day_id", "consignor_party_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.consignment)


@bp.post("/sale-barn/consignments/<consignment_id>/check-in")
def check_in(consignment_id):
    actor(["YardOperator"])
    consignment = path_row("consignments", consignment_id, "Consignment")
    sale_day = get("sale_days", consignment["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"])
    run_gates("consignments.check_in", sale_day=sale_day, party=party)
    if consignment["status"] != "INTAKE" or sale_day["status"] != "CHECK_IN_OPEN":
        fail("ERR_INVALID_STATE")
    consignment["status"] = "CHECKED_IN"
    consignment["checked_in_at"] = render_instant(clock.now())
    consignment["_checked_in_dt"] = clock.now()
    touch(consignment)
    maybe_sorted(consignment, touch)
    return ok(serialize.consignment(consignment))


@bp.post("/sale-barn/consignments/<consignment_id>/losses")
def report_loss(consignment_id):
    role, user_id = actor(["Consignor"])
    consignment = path_row("consignments", consignment_id, "Consignment")
    data = body()
    v = fields(data, required=[("loss_type", "string"), ("head", "integer")],
               optional=[("lot_id", "string")])
    loss_type = enum_field(data, "loss_type", config.LOSS_TYPES)
    check_min(v["head"], 1, "head")

    lot = None
    if v["lot_id"] is not None:
        lot = reference("lots", v["lot_id"], "Lot")

    sale_day = get("sale_days", consignment["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"])
    ownership(role, user_id, consignment["consignor_party_id"])
    run_gates("consignments.losses", sale_day=sale_day, lot=lot, party=party)

    if lot is not None:
        return _withdraw_lot(consignment, lot)
    return _remove_unassigned(consignment, loss_type, v["head"])


def _remove_unassigned(consignment, loss_type, head):
    """Without a lot_id the head are taken out of the unassigned pool."""
    if head > consignment["head_unassigned"]:
        fail("ERR_HEAD_COUNT_EXCEEDED")
    from services.consignments import head_in_lots
    becomes_withdrawn = (
        loss_type == "WITHDRAWN"
        and head == consignment["head_unassigned"]
        and head_in_lots(consignment["id"]) == 0
        and consignment["status"] in ("INTAKE", "CHECKED_IN")
    )
    if loss_type == "DEAD":
        consignment["head_dead"] += head
    elif loss_type == "CONDEMNED":
        consignment["head_condemned"] += head
    else:
        consignment["head_withdrawn"] += head
    consignment["head_unassigned"] -= head
    if becomes_withdrawn:
        consignment["status"] = "WITHDRAWN"
    touch(consignment)
    if not becomes_withdrawn:
        maybe_sorted(consignment, touch)
    return ok(serialize.consignment(consignment))


def _withdraw_lot(consignment, lot):
    """Naming a lot withdraws that lot; its head RETURN to head_unassigned
    because those animals are still standing on the yard, and head_withdrawn
    is deliberately not touched."""
    if lot["sale_status"] not in ("DRAFT", "PENNED", "READY", "NO_SALE"):
        fail("ERR_INVALID_STATE")
    pen_id = lot.get("pen_id")
    lot["sale_status"] = "WITHDRAWN"
    touch(lot)
    consignment["head_unassigned"] += lot["head_count"]
    touch(consignment)
    recompute_pens(pen_id)
    maybe_sorted(consignment, touch)
    return ok(serialize.consignment(consignment))
