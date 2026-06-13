"""ServiceOrder lifecycle endpoints (PRD §3.3-§3.7)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, require_enum, as_number, as_str,
    get_account_or_404, get_location_or_404, get_order_or_404,
    active_rate_card, has_active_hold,
)
from services.calculations import (
    destruction_charge, estimated_billed_weight, net_weight,
)
from services.scheduling import (
    check_slot_conflict, check_onsite_buffer_conflict, _parse_dt,
)
from services.custody import (
    append_custody_event, serviced_containers, run_destruction_cascade,
    finalize_order_charge,
)

bp = Blueprint("service_orders", __name__)

SERVICE_MODES = {"ON_SITE", "OFF_SITE_PICKUP", "DROP_OFF"}
CADENCES = {"SCHEDULED", "ONE_TIME"}
TERMINAL_ORDER_STATES = {"ON_SITE_SHREDDED", "DESTROYED", "CANCELLED"}


def _order_has_weight_ticket(order_id):
    return any(t["order_id"] == order_id for t in db.weight_tickets.values())


def _latest_weight_ticket(order_id):
    tickets = [t for t in db.weight_tickets.values() if t["order_id"] == order_id]
    if not tickets:
        return None
    return sorted(tickets, key=lambda t: (t["created_at"], t["_seq"]))[-1]


@bp.post("/service-orders")
def create_order():
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician"})
    data = body()
    require_present(data, "account_id", "location_id", "service_mode", "cadence",
                    "scheduled_slot_start", "scheduled_slot_end")
    account_id = as_str(data["account_id"], "account_id")
    location_id = as_str(data["location_id"], "location_id")
    # Existence left-to-right: account, location, then each container.
    acct = get_account_or_404(account_id)
    get_location_or_404(location_id)

    container_ids = data.get("container_ids") or []
    if not isinstance(container_ids, list):
        raise err("ERR_INVALID_FIELD_VALUE", "container_ids must be a list")
    for cid in container_ids:
        if cid not in db.containers:
            raise err("ERR_NOT_FOUND", "Container not found: %s" % cid)

    # State precondition for create-related business constraints below the
    # existence checks. Per validation ordering: field sanity / referential /
    # account-state / rate-card come after slot checks. But the PRD §2.10 places
    # ERR_ACCOUNT_NOT_ACTIVE and ERR_NO_ACTIVE_RATE_CARD in the final group, and
    # ERR_CONTAINER_LOCATION_MISMATCH alongside. Field sanity precedes them.

    require_enum(data["service_mode"], SERVICE_MODES, "service_mode")
    require_enum(data["cadence"], CADENCES, "cadence")
    service_mode = data["service_mode"]
    cadence = data["cadence"]

    start = as_str(data["scheduled_slot_start"], "scheduled_slot_start")
    end = as_str(data["scheduled_slot_end"], "scheduled_slot_end")
    try:
        s_dt = _parse_dt(start)
        e_dt = _parse_dt(end)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_FIELD_VALUE", "Invalid datetime format")
    if not (e_dt > s_dt):
        raise err("ERR_INVALID_FIELD_VALUE", "scheduled_slot_end must be after scheduled_slot_start")

    assigned_tech_id = data.get("assigned_tech_id")

    # Slot-conflict (priority 9) then on-site buffer (priority 10).
    check_slot_conflict(None, account_id, container_ids, start, end)
    check_onsite_buffer_conflict(None, location_id, service_mode, start, end)

    # Referential: every container belongs to this account AND location.
    for cid in container_ids:
        c = db.containers[cid]
        if c["account_id"] != account_id or c["location_id"] != location_id:
            raise err("ERR_CONTAINER_LOCATION_MISMATCH",
                      "Container %s not in the order's account/location" % cid)

    # Account must be ACTIVE.
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Account is not ACTIVE")

    # Pricing requires an ACTIVE rate card.
    rate = active_rate_card(account_id)
    if rate is None:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No ACTIVE rate card on the account")

    order = {
        "account_id": account_id,
        "location_id": location_id,
        "service_mode": service_mode,
        "cadence": cadence,
        "container_ids": list(container_ids),
        "scheduled_slot_start": start,
        "scheduled_slot_end": end,
        "billed_weight_kg": 0,
        "order_charge_cents": 0,
        "assigned_tech_id": assigned_tech_id,
        "status": "SCHEDULED",
    }
    # Estimated variant: billed_weight = sum capacity_kg; provisional charge.
    order["billed_weight_kg"] = estimated_billed_weight(order)
    order["order_charge_cents"] = destruction_charge(order, rate)
    stamp_create(order)
    db.service_orders[order["id"]] = order

    # Each named container -> SCHEDULED_FOR_SERVICE.
    for c in serviced_containers(order):
        c["status"] = "SCHEDULED_FOR_SERVICE"
        touch(c)

    return object_response(serialize(order), 201)


@bp.get("/service-orders/<order_id>")
def get_order(order_id):
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician", "PlantOperator",
                        "DestructionWitness", "ComplianceOfficer"})
    o = get_order_or_404(order_id)
    return object_response(serialize(o), 200)


@bp.get("/service-orders")
def list_orders():
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician", "PlantOperator",
                        "ComplianceOfficer"})
    items = list(db.service_orders.values())
    account_id = request.args.get("account_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if location_id is not None:
        items = [o for o in items if o["location_id"] == location_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(o) for o in page], limit, offset, total, 200)


@bp.post("/service-orders/<order_id>/reschedule")
def reschedule_order(order_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    o = get_order_or_404(order_id)
    data = body()
    require_present(data, "expected_serviceorder_version",
                    "scheduled_slot_start", "scheduled_slot_end")

    # OCC stale-version check runs BEFORE slot geometry (PRD §2.8).
    expected = data["expected_serviceorder_version"]
    if expected != o["version"]:
        raise err("ERR_STALE_VERSION", "expected_serviceorder_version is stale")

    start = as_str(data["scheduled_slot_start"], "scheduled_slot_start")
    end = as_str(data["scheduled_slot_end"], "scheduled_slot_end")
    try:
        s_dt = _parse_dt(start)
        e_dt = _parse_dt(end)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_FIELD_VALUE", "Invalid datetime format")
    if not (e_dt > s_dt):
        raise err("ERR_INVALID_FIELD_VALUE", "scheduled_slot_end must be after scheduled_slot_start")

    check_slot_conflict(o["id"], o["account_id"], o.get("container_ids"), start, end)
    check_onsite_buffer_conflict(o["id"], o["location_id"], o["service_mode"], start, end)

    o["scheduled_slot_start"] = start
    o["scheduled_slot_end"] = end
    touch(o)
    return object_response(serialize(o), 200)


@bp.post("/service-orders/<order_id>/dispatch")
def dispatch_order(order_id):
    _, role = get_auth()
    require_role(role, {"FieldTechnician"})
    actor_id, _ = _auth_actor()
    o = get_order_or_404(order_id)
    if o["status"] != "SCHEDULED":
        raise err("ERR_ORDER_NOT_SCHEDULED", "Order is not in SCHEDULED")
    if o["service_mode"] not in ("ON_SITE", "OFF_SITE_PICKUP"):
        raise err("ERR_DISPATCH_NOT_APPLICABLE", "DROP_OFF orders never dispatch")
    if has_active_hold("SERVICE_ORDER", o["id"]):
        raise err("ERR_SUBJECT_ON_HOLD", "Order is under an active compliance hold")

    for c in serviced_containers(o):
        c["status"] = "IN_SERVICE"
        touch(c)
        append_custody_event(o, "CONTAINER", c["id"], "COLLECTED", actor_id)

    o["status"] = "EN_ROUTE"
    touch(o)
    return object_response(serialize(o), 200)


@bp.post("/service-orders/<order_id>/weigh-in")
def weigh_in(order_id):
    actor_id, role = _auth_actor()
    require_role(role, {"FieldTechnician", "PlantOperator"})
    o = get_order_or_404(order_id)
    data = body()
    require_present(data, "gross_weight_kg")
    gross = as_number(data["gross_weight_kg"], "gross_weight_kg")
    if gross < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "gross_weight_kg must be >= 0")

    tare_total, net = net_weight(o, gross)
    ticket = {
        "order_id": o["id"],
        "gross_weight_kg": gross,
        "tare_total_kg": tare_total,
        "net_weight_kg": net,
        "captured_by": actor_id,
    }
    stamp_create(ticket, with_version=False)  # id + created_at only
    db.weight_tickets[ticket["id"]] = ticket
    return object_response(serialize(ticket), 201)


@bp.post("/service-orders/<order_id>/shred-on-site")
def shred_on_site(order_id):
    actor_id, role = _auth_actor()
    require_role(role, {"FieldTechnician"})
    o = get_order_or_404(order_id)
    if o["status"] != "EN_ROUTE":
        raise err("ERR_ORDER_NOT_EN_ROUTE", "Order is not in EN_ROUTE")
    if o["service_mode"] != "ON_SITE":
        raise err("ERR_MODE_NOT_ON_SITE", "Order service_mode is not ON_SITE")
    if not _order_has_weight_ticket(o["id"]):
        raise err("ERR_WEIGH_IN_REQUIRED", "No weight ticket recorded for the order")

    rate = active_rate_card(o["account_id"])
    if rate is None:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No ACTIVE rate card on the account")

    ticket = _latest_weight_ticket(o["id"])
    # Hop 1: finalize charge under actual variant.
    finalize_order_charge(o, ticket["net_weight_kg"], rate)

    # CustodyEvent DESTROYED per serviced container; containers -> PLACED.
    for c in serviced_containers(o):
        append_custody_event(o, "CONTAINER", c["id"], "DESTROYED", actor_id)
        c["status"] = "PLACED"
        touch(c)

    o["status"] = "ON_SITE_SHREDDED"
    touch(o)

    # Cascade hops 2-3: certificate (witnessed_by = on-site tech) then invoice.
    run_destruction_cascade(o, witnessed_by=actor_id)

    return object_response(serialize(o), 200)


@bp.post("/service-orders/<order_id>/confirm-pickup")
def confirm_pickup(order_id):
    actor_id, role = _auth_actor()
    require_role(role, {"FieldTechnician"})
    o = get_order_or_404(order_id)

    if o["service_mode"] == "OFF_SITE_PICKUP":
        # EN_ROUTE -> PICKED_UP.
        if o["status"] != "EN_ROUTE":
            raise err("ERR_ORDER_NOT_EN_ROUTE", "Order is not in EN_ROUTE")
        for c in serviced_containers(o):
            append_custody_event(o, "CONTAINER", c["id"], "SEALED", actor_id)
            append_custody_event(o, "CONTAINER", c["id"], "IN_TRANSIT", actor_id)
        o["status"] = "PICKED_UP"
        touch(o)
        return object_response(serialize(o), 200)

    if o["service_mode"] == "DROP_OFF":
        # SCHEDULED -> PICKED_UP.
        if o["status"] != "SCHEDULED":
            raise err("ERR_ORDER_NOT_DROP_OFF_READY", "Order is not in SCHEDULED")
        if has_active_hold("SERVICE_ORDER", o["id"]):
            raise err("ERR_SUBJECT_ON_HOLD", "Order is under an active compliance hold")
        for c in serviced_containers(o):
            c["status"] = "IN_SERVICE"
            touch(c)
            append_custody_event(o, "CONTAINER", c["id"], "SEALED", actor_id)
            append_custody_event(o, "CONTAINER", c["id"], "IN_TRANSIT", actor_id)
        o["status"] = "PICKED_UP"
        touch(o)
        return object_response(serialize(o), 200)

    # service_mode == ON_SITE: confirm-pickup not applicable.
    # From EN_ROUTE the off-site branch demands OFF_SITE_PICKUP mode.
    if o["status"] == "EN_ROUTE":
        raise err("ERR_MODE_NOT_OFF_SITE", "Order service_mode is not OFF_SITE_PICKUP")
    # From SCHEDULED the drop-off branch demands DROP_OFF mode.
    if o["status"] == "SCHEDULED":
        raise err("ERR_MODE_NOT_DROP_OFF", "Order service_mode is not DROP_OFF")
    # Otherwise, not in a state from which confirm-pickup is defined.
    raise err("ERR_ORDER_NOT_EN_ROUTE", "Order is not in a confirm-pickup state")


@bp.post("/service-orders/<order_id>/receive-at-plant")
def receive_at_plant(order_id):
    actor_id, role = _auth_actor()
    require_role(role, {"PlantOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "PICKED_UP":
        raise err("ERR_ORDER_NOT_PICKED_UP", "Order is not in PICKED_UP")
    if not _order_has_weight_ticket(o["id"]):
        raise err("ERR_WEIGH_IN_REQUIRED", "No weight ticket recorded for the order")

    rate = active_rate_card(o["account_id"])
    if rate is None:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No ACTIVE rate card on the account")

    ticket = _latest_weight_ticket(o["id"])
    finalize_order_charge(o, ticket["net_weight_kg"], rate)

    for c in serviced_containers(o):
        append_custody_event(o, "CONTAINER", c["id"], "RECEIVED_AT_PLANT", actor_id)

    o["status"] = "AT_PLANT"
    touch(o)
    return object_response(serialize(o), 200)


@bp.post("/service-orders/<order_id>/destroy")
def destroy_order(order_id):
    actor_id, role = _auth_actor()
    require_role(role, {"DestructionWitness"})
    o = get_order_or_404(order_id)
    data = body()
    require_present(data, "witnessed_by")
    witnessed_by = as_str(data["witnessed_by"], "witnessed_by")

    if o["status"] != "AT_PLANT":
        raise err("ERR_ORDER_NOT_AT_PLANT", "Order is not in AT_PLANT")
    if has_active_hold("SERVICE_ORDER", o["id"]):
        raise err("ERR_SUBJECT_ON_HOLD", "Order is under an active compliance hold")
    # Segregation of duties: witness must differ from order.assigned_tech_id.
    if witnessed_by == o.get("assigned_tech_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "Witness may not be the custody-taker")

    for c in serviced_containers(o):
        append_custody_event(o, "CONTAINER", c["id"], "DESTROYED", witnessed_by)
        c["status"] = "PLACED"
        touch(c)

    o["status"] = "DESTROYED"
    touch(o)

    # billed_weight_kg / order_charge_cents already finalized at receive-at-plant.
    run_destruction_cascade(o, witnessed_by=witnessed_by)

    return object_response(serialize(o), 200)


@bp.post("/service-orders/<order_id>/cancel")
def cancel_order(order_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    o = get_order_or_404(order_id)
    if o["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not in SCHEDULED or EN_ROUTE")
    # No DestructionCertificate exists for this order.
    for cert in db.certificates.values():
        if cert["order_id"] == o["id"]:
            raise err("ERR_CERTIFICATE_ALREADY_ISSUED", "A certificate already exists for the order")

    # Compensation: every serviced container reverts to PLACED.
    for c in serviced_containers(o):
        c["status"] = "PLACED"
        touch(c)
    o["order_charge_cents"] = 0
    o["billed_weight_kg"] = 0
    o["status"] = "CANCELLED"
    touch(o)
    return object_response(serialize(o), 200)


def _auth_actor():
    """get_auth returns (user_id, role); helper to keep call sites short."""
    return get_auth()
