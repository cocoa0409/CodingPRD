from datetime import timedelta

from flask import Blueprint, g, request

from auth import auth, check_own
from envelope import created, list_response, success
from errors import err
from services import capacity_for_date, labor_minutes, tune_quote
from store import db, iso, new_entity, now, pub, touch
from validate import SERVICES, body, get_or_404, opt_bool, opt_int, req_str

bp = Blueprint("tunes", __name__)

ALL_ROLES = ("Customer", "FrontDesk", "Technician", "Manager")


@bp.post("/shop/tune-tickets")
def create_tune_ticket():
    auth(*ALL_ROLES)
    b = body()
    cust_id = b.get("customer_id")
    if g.user_role == "Customer" and cust_id is not None and cust_id != g.user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "Customers may only create tickets for themselves")
    if cust_id is not None:
        get_or_404(db.customers, cust_id, "Customer")
    equipment_item_id = b.get("equipment_item_id")
    if equipment_item_id is not None:
        get_or_404(db.equipment_items, equipment_item_id, "Equipment item")
    # field-shape validation (priority 10) before capacity gates (16, 17)
    cust_id = req_str(b, "customer_id")
    own_gear = b.get("own_gear_description")
    if own_gear is not None and not isinstance(own_gear, str):
        raise err("ERR_INVALID_REQUEST", "own_gear_description must be a string")
    has_unit = equipment_item_id is not None
    has_own = isinstance(own_gear, str) and own_gear != ""
    if has_unit == has_own:
        raise err("ERR_INVALID_REQUEST",
                  "Exactly one of equipment_item_id / own_gear_description "
                  "is required")
    services = b.get("services")
    if (not isinstance(services, list) or len(services) == 0
            or any(s not in SERVICES for s in services)):
        raise err("ERR_INVALID_REQUEST",
                  "services must be a non-empty array of WAX | EDGE_TUNE | "
                  "BASE_GRIND | BINDING_ADJUST")
    rush = opt_bool(b, "rush", False)
    labor = labor_minutes(services)
    # capacity gates, in fixed order: row must exist, then rush pool must fit
    cap = capacity_for_date(now().date())
    if cap is None:
        raise err("ERR_CAPACITY_MISSING",
                  "No ShopDayCapacity row for the ticket's creation date")
    if rush:
        if cap["rush_booked_minutes"] + labor > cap["rush_reserved_minutes"]:
            raise err("ERR_RUSH_CAPACITY_EXCEEDED",
                      "Rush labor pool cannot fit this ticket")
        cap["rush_booked_minutes"] += labor
        touch(cap)
    promised = now() + timedelta(hours=24 if rush else 48)
    ticket = new_entity({
        "customer_id": cust_id,
        "equipment_item_id": equipment_item_id,
        "own_gear_description": own_gear if has_own else None,
        "services": services,
        "rush": rush,
        "parts_surcharge_cents": 0,
        "labor_minutes": labor,
        "status": "INTAKE",
        "promised_at": iso(promised),
        "quoted_price_cents": None,
        "final_price_cents": None,
        "rework_count": 0,
        "junior_discount_applied": False,
        "_capacity_date": now().date().isoformat(),
    })
    db.tune_tickets[ticket["id"]] = ticket
    return created(pub(ticket))


@bp.get("/shop/tune-tickets/<tid>")
def get_tune_ticket(tid):
    auth(*ALL_ROLES)
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    check_own(ticket["customer_id"])
    return success(pub(ticket))


@bp.get("/shop/tune-tickets")
def list_tune_tickets():
    auth(*ALL_ROLES)
    items = list(db.tune_tickets.values())
    if g.user_role == "Customer":
        items = [t for t in items if t["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    equipment_item_id = request.args.get("equipment_item_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [t for t in items if t["customer_id"] == customer_id]
    if equipment_item_id is not None:
        items = [t for t in items if t["equipment_item_id"] == equipment_item_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items)


@bp.post("/shop/tune-tickets/<tid>/quote")
def quote_tune_ticket(tid):
    auth("Technician", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    if ticket["status"] not in ("INTAKE", "QUOTED"):
        raise err("ERR_INVALID_STATE",
                  "Only an INTAKE or QUOTED ticket can be quoted")
    b = body()
    if b.get("parts_surcharge_cents") is not None:
        ticket["parts_surcharge_cents"] = opt_int(b, "parts_surcharge_cents",
                                                  minimum=0)
    price, junior = tune_quote(ticket)
    ticket["quoted_price_cents"] = price
    ticket["junior_discount_applied"] = junior
    ticket["status"] = "QUOTED"
    touch(ticket)  # re-quote bumps version, invalidating outstanding approvals
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/approve")
def approve_tune_ticket(tid):
    auth("Customer", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    check_own(ticket["customer_id"])
    expected = body().get("expected_tune_ticket_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "expected_tune_ticket_version is required")
    if expected != ticket["version"]:
        raise err("ERR_STALE_VERSION",
                  "The ticket version has advanced since the observed quote")
    if ticket["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Only a QUOTED ticket can be approved")
    ticket["status"] = "APPROVED"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/start")
def start_tune_ticket(tid):
    auth("Technician", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    if ticket["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED ticket can be started")
    cap = capacity_for_date(ticket["_capacity_date"])
    if (cap is None
            or cap["booked_minutes"] + ticket["labor_minutes"]
            > cap["base_labor_minutes"]):
        raise err("ERR_CAPACITY_FULL",
                  "Standard labor pool cannot fit this ticket")
    cap["booked_minutes"] += ticket["labor_minutes"]
    touch(cap)
    ticket["status"] = "IN_PROGRESS"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/complete")
def complete_tune_ticket(tid):
    auth("Technician", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    if ticket["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE",
                  "Only an IN_PROGRESS ticket can be completed")
    ticket["status"] = "QUALITY_CHECK"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/qc-pass")
def qc_pass_tune_ticket(tid):
    auth("Technician", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    if ticket["status"] != "QUALITY_CHECK":
        raise err("ERR_INVALID_STATE",
                  "Only a QUALITY_CHECK ticket can pass QC")
    ticket["status"] = "READY"
    ticket["final_price_cents"] = ticket["quoted_price_cents"]  # rework is free
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/qc-fail")
def qc_fail_tune_ticket(tid):
    auth("Technician", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    if ticket["status"] != "QUALITY_CHECK":
        raise err("ERR_INVALID_STATE",
                  "Only a QUALITY_CHECK ticket can fail QC")
    # guards in PRD order: capacity re-verified first, then the rework counter
    cap = capacity_for_date(ticket["_capacity_date"])
    if (cap is None
            or cap["booked_minutes"] + ticket["labor_minutes"]
            > cap["base_labor_minutes"]):
        raise err("ERR_CAPACITY_FULL",
                  "Standard labor pool cannot fit the rework")
    if ticket["rework_count"] >= 2:
        raise err("ERR_REWORK_LIMIT_EXCEEDED",
                  "rework_count has reached the hard limit of 2")
    cap["booked_minutes"] += ticket["labor_minutes"]
    touch(cap)
    ticket["rework_count"] += 1
    ticket["status"] = "IN_PROGRESS"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/pickup")
def pickup_tune_ticket(tid):
    auth("Customer", "FrontDesk", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    check_own(ticket["customer_id"])
    if ticket["status"] != "READY":
        raise err("ERR_INVALID_STATE", "Only a READY ticket can be picked up")
    ticket["status"] = "PICKED_UP"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/shop/tune-tickets/<tid>/cancel")
def cancel_tune_ticket(tid):
    auth("Customer", "FrontDesk", "Manager")
    ticket = get_or_404(db.tune_tickets, tid, "Tune ticket")
    check_own(ticket["customer_id"])
    if ticket["status"] not in ("INTAKE", "QUOTED"):
        raise err("ERR_INVALID_STATE",
                  "Only an INTAKE or QUOTED ticket can be cancelled")
    if ticket["rush"]:
        cap = capacity_for_date(ticket["_capacity_date"])
        if cap is not None:
            cap["rush_booked_minutes"] -= ticket["labor_minutes"]
            touch(cap)
    ticket["status"] = "CANCELLED"
    touch(ticket)
    return success(pub(ticket))
