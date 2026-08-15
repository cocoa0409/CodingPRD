"""Order capture, pricing, allocation, fulfillment, and billing."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_INVALID_LINE, ERR_MODEL_NOT_ORDERABLE, \
    ERR_COMPLIANCE_HOLD, ERR_WINDOW_EXPIRED, ERR_CREDIT_HOLD, \
    ERR_STALE_VERSION, ERR_INVALID_REQUEST, invalid_state, invalid_request
from middleware import authenticate, authorize, require_owner
from response import success
from serializers import order as ser_order, order_line as ser_line
from services import core
from utils import StructErrors, check_unknown_fields, get_int, touch, is_int
from routes.common import body, get_path, get_ref, new_common, list_response

bp = Blueprint("orders", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "WarrantyProcessor",
              "ComplianceOfficer"}


def _own_order(order, role, user_id):
    require_owner(order["contractor_id"], role, user_id)


@bp.post("/orders")
def create_order():
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"contractor_id", "prebuy_program_id"}, struct)
    contractor_id = data.get("contractor_id")
    prebuy_program_id = data.get("prebuy_program_id")
    if contractor_id is None:
        struct.add("Missing required field: contractor_id")
    elif not isinstance(contractor_id, str):
        struct.add("Field contractor_id must be a string")
        contractor_id = None
    if prebuy_program_id is not None and not isinstance(prebuy_program_id, str):
        struct.add("Field prebuy_program_id must be a string")
        prebuy_program_id = None

    # Body FK existence (priority 4).
    if isinstance(contractor_id, str):
        get_ref(db.contractors, contractor_id, "contractor_id")
    if isinstance(prebuy_program_id, str):
        get_ref(db.prebuy_programs, prebuy_program_id, "prebuy_program_id")
    # Ownership: a dealer creates orders only for itself.
    if isinstance(contractor_id, str):
        require_owner(contractor_id, role, user_id)
    struct.raise_if_bad()

    o = new_common()
    o.update({
        "contractor_id": contractor_id,
        "prebuy_program_id": prebuy_program_id,
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "deposit_due_cents": 0,
        "submitted_at": None,
        "_reservations": {},
        "_committed": [],
        "_short_pool_ids": [],
        "_delivered_at": None,
    })
    db.orders[o["id"]] = o
    return success(ser_order(o), 201)


@bp.get("/orders/<oid>")
def get_order(oid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    o = get_path(db.orders, oid)
    _own_order(o, role, user_id)
    return success(ser_order(o))


@bp.get("/orders")
def list_orders():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"contractor_id": request.args.get("contractor_id"),
               "prebuy_program_id": request.args.get("prebuy_program_id"),
               "status": request.args.get("status")}
    return list_response(db.orders.values(), ser_order, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)


@bp.patch("/orders/<oid>")
def patch_order(oid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    o = get_path(db.orders, oid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"expected_order_version", "prebuy_program_id"},
                         struct)
    # Body FK existence (priority 4).
    new_program = data.get("prebuy_program_id", "__absent__")
    if new_program != "__absent__" and new_program is not None:
        if not isinstance(new_program, str):
            struct.add("Field prebuy_program_id must be a string")
        else:
            get_ref(db.prebuy_programs, new_program, "prebuy_program_id")
    _own_order(o, role, user_id)
    # From-state legality (priority 5).
    if o["status"] != "DRAFT":
        raise invalid_state("Only DRAFT orders may be edited")
    # OCC (priority 21).
    if "expected_order_version" not in data:
        raise invalid_request("Missing required field: expected_order_version")
    if data["expected_order_version"] != o["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_order_version does not match current version")
    struct.raise_if_bad()

    if new_program != "__absent__":
        o["prebuy_program_id"] = new_program
    core.reprice_order(o)
    touch(o)
    return success(ser_order(o))


@bp.post("/orders/<oid>/lines")
def add_line(oid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    o = get_path(db.orders, oid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"ahri_rating_id", "equipment_model_id",
                                "quantity", "unit_price_cents"}, struct)
    ahri_rating_id = data.get("ahri_rating_id")
    equipment_model_id = data.get("equipment_model_id")
    quantity = data.get("quantity")

    # Body FK existence (priority 4).
    if isinstance(ahri_rating_id, str):
        get_ref(db.ahri_ratings, ahri_rating_id, "ahri_rating_id")
    if isinstance(equipment_model_id, str):
        get_ref(db.equipment_models, equipment_model_id, "equipment_model_id")

    _own_order(o, role, user_id)

    # From-state (priority 5).
    if o["status"] != "DRAFT":
        raise invalid_state("Lines may only be added while the order is DRAFT")

    # Line shape (priority 15): exactly one FK, quantity >= 1.
    has_rating = ahri_rating_id is not None
    has_model = equipment_model_id is not None
    if has_rating == has_model:
        raise ApiError(ERR_INVALID_LINE, 422,
                       "Exactly one of ahri_rating_id / equipment_model_id "
                       "must be present")
    if quantity is not None and is_int(quantity) and quantity < 1:
        raise ApiError(ERR_INVALID_LINE, 422, "quantity must be >= 1")

    # Referenced-model orderability (priority 16).
    if has_model and isinstance(equipment_model_id, str):
        model = db.equipment_models.get(equipment_model_id)
        if model is not None:
            if model["status"] == "DISCONTINUED":
                raise ApiError(ERR_MODEL_NOT_ORDERABLE, 422,
                               "Model is DISCONTINUED")
            if model["status"] == "ALLOCATED_ONLY":
                if core.select_pool(model["family_code"]) is None:
                    raise ApiError(ERR_MODEL_NOT_ORDERABLE, 422,
                                   "ALLOCATED_ONLY model has no covering "
                                   "open allocation pool")
    if has_rating and isinstance(ahri_rating_id, str):
        rating = db.ahri_ratings.get(ahri_rating_id)
        if rating is not None and rating["status"] == "WITHDRAWN":
            raise ApiError(ERR_MODEL_NOT_ORDERABLE, 422,
                           "Rating is WITHDRAWN")

    # Structural (priority 22).
    if quantity is None:
        struct.add("Missing required field: quantity")
    elif not is_int(quantity):
        struct.add("Field quantity must be an integer")
    struct.raise_if_bad()

    line = new_common()
    line.update({
        "order_id": o["id"],
        "ahri_rating_id": ahri_rating_id,
        "equipment_model_id": equipment_model_id,
        "quantity": quantity,
        "unit_price_cents": 0,
        "line_discount_cents": 0,
        "line_total_cents": 0,
    })
    core.resolve_line_pricing(o, line)
    db.order_lines[line["id"]] = line
    core.recompute_order_totals(o)
    touch(o)
    return success(ser_line(line), 201)


@bp.get("/orders/<oid>/lines")
def list_order_lines(oid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    o = get_path(db.orders, oid)
    _own_order(o, role, user_id)
    lines = [l for l in db.order_lines.values() if l["order_id"] == o["id"]]
    return list_response(lines, ser_line)


@bp.get("/order-lines/<lid>")
def get_order_line(lid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    line = get_path(db.order_lines, lid)
    o = db.orders.get(line["order_id"])
    if o is not None:
        _own_order(o, role, user_id)
    return success(ser_line(line))


@bp.get("/order-lines")
def list_order_lines_global():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"ahri_rating_id": request.args.get("ahri_rating_id"),
               "equipment_model_id": request.args.get("equipment_model_id"),
               "order_id": request.args.get("order_id")}
    items = list(db.order_lines.values())
    if role == "ContractorUser":
        items = [l for l in items
                 if db.orders.get(l["order_id"], {}).get("contractor_id") == user_id]
    return list_response(items, ser_line, filters)


@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    o = get_path(db.orders, oid)
    _own_order(o, role, user_id)

    # From-state (priority 5).
    if o["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT order may be submitted")
    lines = [l for l in db.order_lines.values() if l["order_id"] == o["id"]]
    if not lines:
        raise invalid_state("Order must have at least one line")
    contractor = db.contractors.get(o["contractor_id"])
    if contractor is None or contractor["status"] != "ACTIVE":
        raise invalid_state("Contractor is not ACTIVE")

    # Compliance gate (priority 7).
    if contractor["compliance_standing"] == "HOLD":
        raise ApiError(ERR_COMPLIANCE_HOLD, 422,
                       "Contractor compliance standing is HOLD")

    # Window validity (priority 9).
    program = None
    if o.get("prebuy_program_id"):
        program = db.prebuy_programs.get(o["prebuy_program_id"])
        now = clock.now()
        core.recompute_program_status(program)
        if program["status"] != "OPEN" or not (
                program["window_start"] <= now < program["window_end"]):
            raise ApiError(ERR_WINDOW_EXPIRED, 422,
                           "Pre-buy program window is not open")

    # Credit hold (priority 19).
    if contractor["credit_hold"]:
        raise ApiError(ERR_CREDIT_HOLD, 422, "Contractor is on credit hold")

    # Execute: stamp, reprice, totals, allocation, provisional accrual.
    o["submitted_at"] = clock.now()
    core.reprice_order(o)
    o["status"] = "SUBMITTED"
    core.attempt_allocation(o)
    touch(o)
    core.refresh_provisional(o["contractor_id"])
    return success(ser_order(o))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    o = get_path(db.orders, oid)
    _own_order(o, role, user_id)
    if o["status"] not in ("DRAFT", "SUBMITTED", "BACKORDERED"):
        raise invalid_state("Order in state %s cannot be cancelled" % o["status"])
    if o["status"] != "DRAFT" and o["billing_status"] not in (
            "UNBILLED", "DEPOSIT_INVOICED"):
        raise invalid_state("Billing state %s blocks cancellation"
                            % o["billing_status"])

    core.release_reservations(o)
    if o["billing_status"] == "DEPOSIT_INVOICED":
        o["billing_status"] = "FORFEITED"
    o["status"] = "CANCELLED"
    touch(o)
    core.refresh_provisional(o["contractor_id"])
    return success(ser_order(o))


@bp.post("/orders/<oid>/ship")
def ship_order(oid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    o = get_path(db.orders, oid)
    if o["status"] != "ALLOCATED":
        raise invalid_state("Only an ALLOCATED order may ship")
    if o.get("prebuy_program_id"):
        program = db.prebuy_programs.get(o["prebuy_program_id"])
        if program is not None and clock.now() > program["ship_by_date"]:
            raise ApiError(ERR_WINDOW_EXPIRED, 422,
                           "Pre-buy ship_by_date has passed")
    o["status"] = "SHIPPED"
    touch(o)
    return success(ser_order(o))


@bp.post("/orders/<oid>/deliver")
def deliver_order(oid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    o = get_path(db.orders, oid)
    if o["status"] != "SHIPPED":
        raise invalid_state("Only a SHIPPED order may be delivered")
    o["status"] = "DELIVERED"
    o["_delivered_at"] = clock.now()
    touch(o)
    # Delivery cascade: ytd + final accrual, tier re-evaluation, provisional.
    contractor = db.contractors.get(o["contractor_id"])
    if contractor is not None:
        core.refresh_contractor_commercials(contractor)
    return success(ser_order(o))


_BILLING_EVENTS = {
    "INVOICE_DEPOSIT": "DistributorAdmin",
    "PAY_DEPOSIT": "ContractorUser",
    "INVOICE_FINAL": "DistributorAdmin",
    "PAY_FINAL": "ContractorUser",
}


@bp.post("/orders/<oid>/billing-events")
def billing_event(oid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin", "ContractorUser"}, role)
    data = body()
    event_type = data.get("event_type")
    if not isinstance(event_type, str) or event_type not in _BILLING_EVENTS:
        raise invalid_request(
            "event_type must be one of %s" % sorted(_BILLING_EVENTS))
    # Segregation of duties: invoicing vs payment events.
    authorize({_BILLING_EVENTS[event_type]}, role)
    o = get_path(db.orders, oid)
    _own_order(o, role, user_id)

    billing = o["billing_status"]
    status = o["status"]
    if event_type == "INVOICE_DEPOSIT":
        if billing != "UNBILLED" or status not in (
                "SUBMITTED", "BACKORDERED", "ALLOCATED") \
                or not o.get("prebuy_program_id"):
            raise invalid_state("INVOICE_DEPOSIT is not legal from the "
                                "current state")
        o["billing_status"] = "DEPOSIT_INVOICED"
    elif event_type == "PAY_DEPOSIT":
        if billing != "DEPOSIT_INVOICED":
            raise invalid_state("PAY_DEPOSIT is not legal from the current state")
        o["billing_status"] = "DEPOSIT_PAID"
    elif event_type == "INVOICE_FINAL":
        if billing == "DEPOSIT_PAID" and status == "SHIPPED":
            o["billing_status"] = "FINAL_INVOICED"
        elif billing == "UNBILLED" and status == "SHIPPED" \
                and not o.get("prebuy_program_id"):
            o["billing_status"] = "FINAL_INVOICED"
        else:
            raise invalid_state("INVOICE_FINAL is not legal from the "
                                "current state")
    elif event_type == "PAY_FINAL":
        if billing != "FINAL_INVOICED":
            raise invalid_state("PAY_FINAL is not legal from the current state")
        o["billing_status"] = "PAID"
    touch(o)
    return success(ser_order(o))
