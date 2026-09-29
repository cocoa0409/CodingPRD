"""Unit orders: configuration, submit, slots, chassis matching, release, ship, financing."""
from decimal import Decimal

import constants as C
import db
import validation as V
from db import store
from errors import ApiError
from flask import Blueprint, g
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import calc, cascade, derive

bp = Blueprint("orders", __name__)

ORDER_STATUSES = [
    "DRAFT",
    "CONFIG_VALIDATED",
    "SLOTTED",
    "IN_PRODUCTION",
    "BUILT",
    "SHIPPED",
    "CANCELLED",
]
FINANCING_STATUSES = [
    "NOT_FINANCED",
    "FUNDING_REQUESTED",
    "FLOOR_PLAN_FUNDED",
    "CURTAILED",
    "PAID_OFF",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _scope(dealer_id):
    """Validation band 6 — dealer ownership."""
    if g.get("role") == "DealerPrincipal" and g.get("user_id") != dealer_id:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "A DealerPrincipal may only act on its own dealer's records.",
        )


def _floor_plan(order):
    return store.floor_plans[order["floor_plan_id"]]


def _dealer(order):
    return store.dealers[order["dealer_id"]]


def _suspended(order):
    if _dealer(order)["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", "The dealer agreement is SUSPENDED.")


def _credit_and_curtailment(order, check_curtailment=True):
    dealer = _dealer(order)
    if derive.dealer_credit_status(dealer) == "CREDIT_HOLD":
        raise ApiError("ERR_DEALER_CREDIT_HOLD", "The dealer's credit_status is CREDIT_HOLD.")
    if check_curtailment and derive.dealer_is_delinquent(dealer["id"]):
        raise ApiError(
            "ERR_DEALER_CURTAILMENT_DELINQUENT",
            "The dealer holds a CURTAILED order with a positive curtailment obligation.",
        )


def _config_is_stale(order):
    floor_plan = _floor_plan(order)
    if order["locked_floor_plan_version"] is None:
        return True
    if int(order["locked_floor_plan_version"]) != int(floor_plan["version"]):
        return True
    for entry in order["locked_option_versions"]:
        option = store.option_items.get(entry["option_id"])
        if option is None or int(option["version"]) != int(entry["version"]):
            return True
    return False


def _require_fresh_config(order):
    if _config_is_stale(order):
        raise ApiError(
            "ERR_CONFIG_REFERENCE_STALE",
            "The pinned floor-plan or option versions have moved since submit.",
        )


def _apply_totals(order, floor_plan, options):
    totals = calc.configuration_totals(floor_plan, options)
    order.update(totals)
    return totals


def _resolve_options(option_ids):
    return [must_find("option_items", oid) for oid in option_ids]


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------
@bp.post("/unit-orders")
@authorize("DealerPrincipal")
def create_unit_order():
    body = V.body_dict()
    dealer_id = V.field_string(body, "dealer_id", required=True, min_len=1)
    floor_plan_id = V.field_string(body, "floor_plan_id", required=True, min_len=1)
    order_type = V.field_enum(body, "order_type", C.ORDER_TYPES, required=True)
    option_ids = V.field_str_array(body, "selected_option_ids", required=True)
    delivery = V.field_datetime(body, "requested_delivery_date", required=True)
    customer_reference = V.field_string(body, "customer_reference")

    must_find("dealers", dealer_id)
    floor_plan = must_find("floor_plans", floor_plan_id)
    options = _resolve_options(option_ids)
    _scope(dealer_id)

    row = db.new_row(
        {
            "dealer_id": dealer_id,
            "floor_plan_id": floor_plan_id,
            "order_type": order_type,
            "customer_reference": customer_reference,
            "selected_option_ids": list(option_ids),
            "requested_delivery_date": delivery,
            "status": "DRAFT",
            "financing_status": "NOT_FINANCED",
            "provisional_invoice_cents": 0,
            "final_invoice_cents": None,
            "locked_floor_plan_version": None,
            "locked_option_versions": [],
            "financed_principal_cents": 0,
            "curtailment_paid_cents": 0,
            "funded_at": None,
            "shipped_at": None,
            "ship_hold_reason": "NONE",
        }
    )
    _apply_totals(row, floor_plan, options)
    insert("unit_orders", row)
    return object_out("unit_orders", row, 201)


@bp.get("/unit-orders/<row_id>")
@authorize(
    "PlantAdmin",
    "DealerPrincipal",
    "ProductionScheduler",
    "LineSupervisor",
    "WarrantyAdministrator",
)
def get_unit_order(row_id):
    order = must_find("unit_orders", row_id)
    _scope(order["dealer_id"])
    return object_out("unit_orders", order)


@bp.get("/unit-orders")
@authorize("PlantAdmin", "DealerPrincipal", "ProductionScheduler")
def list_unit_orders():
    dealer_id = V.query_string("dealer_id")
    floor_plan_id = V.query_string("floor_plan_id")
    status = V.query_enum("status", ORDER_STATUSES)
    financing_status = V.query_enum("financing_status", FINANCING_STATUSES)
    order_type = V.query_enum("order_type", C.ORDER_TYPES)
    rows = list(store.unit_orders.values())
    if g.get("role") == "DealerPrincipal":
        rows = [r for r in rows if r["dealer_id"] == g.get("user_id")]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if floor_plan_id is not None:
        rows = [r for r in rows if r["floor_plan_id"] == floor_plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if financing_status is not None:
        rows = [r for r in rows if r["financing_status"] == financing_status]
    if order_type is not None:
        rows = [r for r in rows if r["order_type"] == order_type]
    return list_out("unit_orders", rows)


# ---------------------------------------------------------------------------
# configuration replacement
# ---------------------------------------------------------------------------
@bp.put("/unit-orders/<row_id>/configuration")
@authorize("DealerPrincipal")
def replace_configuration(row_id):
    body = V.body_dict()
    option_ids = V.field_str_array(body, "selected_option_ids", required=True)
    delivery = V.field_datetime(body, "requested_delivery_date")
    order = must_find("unit_orders", row_id)
    options = _resolve_options(option_ids)
    _scope(order["dealer_id"])
    if order["status"] not in ("DRAFT", "CONFIG_VALIDATED"):
        raise ApiError(
            "ERR_ORDER_NOT_SUBMITTABLE",
            "Configuration may only be replaced while the order is DRAFT or CONFIG_VALIDATED.",
        )
    order["selected_option_ids"] = list(option_ids)
    if delivery is not None:
        order["requested_delivery_date"] = delivery
    _apply_totals(order, _floor_plan(order), options)
    order["status"] = "DRAFT"
    order["locked_floor_plan_version"] = None
    order["locked_option_versions"] = []
    order["provisional_invoice_cents"] = 0
    db.touch(order)
    return object_out("unit_orders", order)


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------
def _check_option_set(order, options):
    for option in options:
        if option["status"] == "DISCONTINUED":
            raise ApiError(
                "ERR_OPTION_DISCONTINUED",
                "Option '{}' has been discontinued.".format(option["option_code"]),
            )
    selected_codes = {o["option_code"] for o in options}
    by_code = {o["option_code"]: o for o in store.option_items.values()}
    frontier = []
    for option in options:
        frontier.extend(option["requires_option_codes"])
    seen = set()
    while frontier:
        code = frontier.pop()
        if code in seen:
            continue
        seen.add(code)
        if code not in selected_codes:
            raise ApiError(
                "ERR_OPTION_REQUIRES_MISSING",
                "Required companion option '{}' is not selected.".format(code),
            )
        companion = by_code.get(code)
        if companion is not None:
            frontier.extend(companion["requires_option_codes"])
    for option in options:
        for code in option["excludes_option_codes"]:
            if code in selected_codes and code != option["option_code"]:
                raise ApiError(
                    "ERR_OPTION_MUTUALLY_EXCLUSIVE",
                    "Options '{}' and '{}' may not be ordered together.".format(
                        option["option_code"], code
                    ),
                )


@bp.post("/unit-orders/<row_id>/submit")
@authorize("DealerPrincipal")
def submit_unit_order(row_id):
    V.body_dict()
    order = must_find("unit_orders", row_id)
    _scope(order["dealer_id"])
    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_ORDER_NOT_SUBMITTABLE", "Only a DRAFT order may be submitted."
        )
    floor_plan = _floor_plan(order)
    if floor_plan["status"] == "RETIRED":
        raise ApiError("ERR_FLOOR_PLAN_RETIRED", "The floor plan has been retired.")
    _suspended(order)

    options = derive.selected_options(order)
    totals = calc.configuration_totals(floor_plan, options)

    if totals["config_weight_lbs"] > int(floor_plan["gvwr_lbs"]):
        raise ApiError(
            "ERR_PAYLOAD_CAPACITY_EXCEEDED",
            "config_weight_lbs exceeds the floor plan's gvwr_lbs.",
        )
    if totals["total_amp_draw"] > int(floor_plan["electrical_service_amps"]):
        raise ApiError(
            "ERR_ELECTRICAL_SERVICE_EXCEEDED",
            "total_amp_draw exceeds the floor plan's electrical_service_amps.",
        )
    if totals["total_water_demand_gal"] > calc.water_ceiling_gal(floor_plan):
        raise ApiError(
            "ERR_WATER_SYSTEM_CAPACITY_EXCEEDED",
            "total_water_demand_gal exceeds the plumbed-demand ceiling.",
        )
    _check_option_set(order, options)
    if totals["required_station_hours"] > C.MAX_SINGLE_UNIT_HOURS:
        raise ApiError(
            "ERR_STATION_HOURS_LIMIT_EXCEEDED",
            "required_station_hours exceeds the single-unit ceiling of 96.00 hours.",
        )

    order.update(totals)
    order["provisional_invoice_cents"] = calc.invoice_cents(
        floor_plan,
        order["order_type"],
        derive.option_lines_current(order),
        _dealer(order)["region"],
    )
    order["locked_floor_plan_version"] = int(floor_plan["version"])
    order["locked_option_versions"] = [
        {
            "option_id": option["id"],
            "version": int(option["version"]),
            "price_cents": int(option["price_cents"]),
        }
        for option in options
    ]
    order["status"] = "CONFIG_VALIDATED"
    db.touch(order)
    return object_out("unit_orders", order)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/cancel")
@authorize("DealerPrincipal")
def cancel_unit_order(row_id):
    body = V.body_dict()
    V.field_string(body, "cancel_reason")
    order = must_find("unit_orders", row_id)
    _scope(order["dealer_id"])
    if order["status"] not in ("DRAFT", "CONFIG_VALIDATED", "SLOTTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "An order may only be cancelled from DRAFT, CONFIG_VALIDATED or SLOTTED.",
        )
    slot = derive.reserved_slot(order["id"])
    if slot is not None:
        cascade.release_slot(slot)
    cascade.unmatch_chassis(order["id"])
    order["status"] = "CANCELLED"
    db.touch(order)
    return object_out("unit_orders", order)


# ---------------------------------------------------------------------------
# production slots
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/production-slots")
@authorize("ProductionScheduler")
def reserve_production_slot(row_id):
    body = V.body_dict()
    line_id = V.field_string(body, "line_id", required=True, min_len=1)
    slot_date = V.field_datetime(body, "slot_date", required=True)
    expected = V.field_int(body, "expected_unit_order_version", required=True, minimum=0)

    order = must_find("unit_orders", row_id)
    line = must_find("production_lines", line_id)

    if order["status"] not in ("CONFIG_VALIDATED", "SLOTTED"):
        raise ApiError(
            "ERR_ORDER_NOT_SLOTTABLE",
            "A slot may only be reserved for a CONFIG_VALIDATED or SLOTTED order.",
        )
    _suspended(order)

    if int(expected) != int(order["version"]):
        raise ApiError(
            "ERR_STALE_UNIT_ORDER_VERSION",
            "expected_unit_order_version does not match the order's current version.",
        )

    floor_plan = _floor_plan(order)
    if line["chassis_class_supported"] != floor_plan["chassis_class"]:
        raise ApiError(
            "ERR_LINE_CLASS_MISMATCH",
            "The line is not tooled for the floor plan's chassis class.",
        )

    required = calc.dec(order["required_station_hours"])
    prior = derive.reserved_slot(order["id"])
    exclude_id = prior["id"] if prior is not None else None

    committed_hours, occupied_units = derive.day_occupancy(
        line["id"], slot_date, exclude_slot_id=exclude_id
    )
    if occupied_units + 1 > int(line["max_units_per_day"]):
        raise ApiError(
            "ERR_LINE_DAY_UNIT_CAP_EXCEEDED",
            "The line-day bucket already holds its maximum number of units.",
        )
    if committed_hours + required > calc.dec(line["daily_station_hour_capacity"]):
        raise ApiError(
            "ERR_LINE_DAY_HOURS_EXCEEDED",
            "The line-day bucket cannot absorb the order's required station hours.",
        )

    dealer = _dealer(order)
    _credit_and_curtailment(order)
    consumed = derive.allocation_hours_consumed(
        dealer["id"], month=derive.month_key(slot_date), exclude_slot_id=exclude_id
    )
    tolerance = calc.tolerance_hours(derive.dealer_entitlement(dealer))
    if consumed + required > tolerance:
        raise ApiError(
            "ERR_DEALER_ALLOCATION_EXCEEDED",
            "The dealer's monthly station-hour entitlement cannot absorb this order.",
        )

    if prior is not None:
        cascade.release_slot(prior)

    slot = db.new_row(
        {
            "line_id": line["id"],
            "unit_order_id": order["id"],
            "slot_date": slot_date,
            "sequence_position": occupied_units + 1,
            "station_hours_committed": calc.rhu2(required),
            "status": "RESERVED",
        }
    )
    slot["expires_at"] = db.plus_hours(slot["created_at"], C.SLOT_RESERVATION_TTL_HOURS)
    insert("production_slots", slot)

    order["status"] = "SLOTTED"
    db.touch(order)
    return object_out("production_slots", slot, 201)


@bp.get("/production-slots/<row_id>")
@authorize("PlantAdmin", "ProductionScheduler")
def get_production_slot(row_id):
    return object_out("production_slots", must_find("production_slots", row_id))


@bp.get("/production-slots")
@authorize("PlantAdmin", "ProductionScheduler")
def list_production_slots():
    line_id = V.query_string("line_id")
    unit_order_id = V.query_string("unit_order_id")
    slot_date = V.query_datetime("slot_date")
    status = V.query_enum("status", ["RESERVED", "CONSUMED", "RELEASED"])
    rows = list(store.production_slots.values())
    if line_id is not None:
        rows = [r for r in rows if r["line_id"] == line_id]
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if slot_date is not None:
        rows = [r for r in rows if r["slot_date"] == slot_date]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_out("production_slots", rows)


# ---------------------------------------------------------------------------
# chassis matching
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/match-chassis")
@authorize("ProductionScheduler")
def match_chassis(row_id):
    V.body_dict()
    order = must_find("unit_orders", row_id)
    if order["status"] not in ("CONFIG_VALIDATED", "SLOTTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A chassis may only be matched while the order is CONFIG_VALIDATED or SLOTTED.",
        )
    if derive.matched_chassis(order["id"]) is not None:
        raise ApiError(
            "ERR_ORDER_ALREADY_MATCHED", "The order already holds a matched chassis."
        )
    _require_fresh_config(order)
    winner = derive.pick_chassis(order, _floor_plan(order))
    if winner is None:
        raise ApiError("ERR_NO_MATCHING_CHASSIS", "No eligible chassis is available.")
    winner["status"] = "MATCHED"
    winner["matched_unit_order_id"] = order["id"]
    db.touch(winner)
    return object_out("chassis_receipts", winner)


# ---------------------------------------------------------------------------
# release to line
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/release-to-line")
@authorize("ProductionScheduler")
def release_to_line(row_id):
    V.body_dict()
    order = must_find("unit_orders", row_id)
    if order["status"] != "SLOTTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SLOTTED order may be released to the line.")
    chassis = None
    for candidate in store.chassis_receipts.values():
        if candidate.get("matched_unit_order_id") == order["id"] and candidate["status"] == "MATCHED":
            chassis = candidate
            break
    if chassis is None:
        raise ApiError("ERR_CHASSIS_NOT_MATCHED", "No MATCHED chassis is assigned to this order.")
    slot = derive.reserved_slot(order["id"])
    if slot is None:
        raise ApiError("ERR_INVALID_STATE", "The order holds no RESERVED production slot.")
    _suspended(order)
    _require_fresh_config(order)
    _credit_and_curtailment(order)

    floor_plan = _floor_plan(order)
    store.build_counter += 1
    sequence = store.build_counter
    build = db.new_row(
        {
            "unit_order_id": order["id"],
            "chassis_receipt_id": chassis["id"],
            "vin": "{}-{:06d}".format(floor_plan["model_code"], sequence),
            "build_sequence": sequence,
            "current_station": "CHASSIS_PREP",
            "actual_station_hours": Decimal("0.00"),
            "rework_count": 0,
            "defect_points_total": 0,
            "water_test_passed": False,
            "pdi_passed": False,
            "recall_hold": False,
        }
    )
    insert("unit_builds", build)

    chassis["status"] = "INSTALLED"
    db.touch(chassis)
    slot["status"] = "CONSUMED"
    db.touch(slot)
    order["status"] = "IN_PRODUCTION"
    db.touch(order)
    return object_out("unit_builds", build, 201)


# ---------------------------------------------------------------------------
# shipment
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/ship")
@authorize("ProductionScheduler")
def ship_unit_order(row_id):
    V.body_dict()
    order = must_find("unit_orders", row_id)
    if order["ship_hold_reason"] == "QUALITY_HOLD":
        raise ApiError("ERR_QUALITY_HOLD", "The order is held for quality reasons.")
    if order["status"] != "BUILT":
        raise ApiError("ERR_INVALID_STATE", "Only a BUILT order may ship.")
    if order["ship_hold_reason"] == "RECALL_HOLD":
        raise ApiError("ERR_RECALL_SHIP_STOP", "The order is under a recall ship stop.")
    _suspended(order)
    build = derive.build_for_order(order["id"])
    if build is None:
        raise ApiError("ERR_INVALID_STATE", "The order has no unit build.")
    if build["recall_hold"]:
        raise ApiError("ERR_RECALL_SHIP_STOP", "The build is under a recall hold.")
    if not build["water_test_passed"]:
        raise ApiError("ERR_WATER_TEST_NOT_PASSED", "The build has not passed its water test.")
    if not build["pdi_passed"]:
        raise ApiError("ERR_PDI_NOT_PASSED", "The build has not passed its PDI.")
    dealer = _dealer(order)
    if derive.dealer_credit_status(dealer) == "CREDIT_HOLD":
        raise ApiError("ERR_DEALER_CREDIT_HOLD", "The dealer's credit_status is CREDIT_HOLD.")
    if order["order_type"] == "STOCK" and order["financing_status"] != "FLOOR_PLAN_FUNDED":
        raise ApiError(
            "ERR_FLOOR_PLAN_FUNDING_REQUIRED",
            "A STOCK order may only ship once it is FLOOR_PLAN_FUNDED.",
        )

    order["shipped_at"] = db.now()
    order["final_invoice_cents"] = calc.invoice_cents(
        _floor_plan(order),
        order["order_type"],
        derive.option_lines_pinned(order),
        dealer["region"],
        build=build,
        required_hours=order["required_station_hours"],
    )
    order["status"] = "SHIPPED"
    db.touch(order)
    build["current_station"] = "SHIPPED"
    db.touch(build)
    return object_out("unit_orders", order)


# ---------------------------------------------------------------------------
# floor-plan financing
# ---------------------------------------------------------------------------
@bp.post("/unit-orders/<row_id>/request-funding")
@authorize("DealerPrincipal")
def request_funding(row_id):
    V.body_dict()
    order = must_find("unit_orders", row_id)
    _scope(order["dealer_id"])
    if order["financing_status"] != "NOT_FINANCED":
        raise ApiError(
            "ERR_INVALID_STATE", "Funding may only be requested from NOT_FINANCED."
        )
    if order["status"] not in ("CONFIG_VALIDATED", "SLOTTED", "IN_PRODUCTION", "BUILT"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Funding may only be requested while the order is CONFIG_VALIDATED, SLOTTED, IN_PRODUCTION or BUILT.",
        )
    _suspended(order)
    order["financing_status"] = "FUNDING_REQUESTED"
    db.touch(order)
    return object_out("unit_orders", order)


@bp.post("/unit-orders/<row_id>/funding-decision")
@authorize("PlantAdmin")
def funding_decision(row_id):
    body = V.body_dict()
    decision = V.field_enum(body, "decision", ["APPROVED", "DECLINED"], required=True)
    V.field_string(body, "decline_reason")
    order = must_find("unit_orders", row_id)
    if order["financing_status"] != "FUNDING_REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a FUNDING_REQUESTED order may be decided."
        )
    if decision == "APPROVED":
        if int(order["provisional_invoice_cents"]) <= 0:
            raise ApiError(
                "ERR_INVALID_STATE",
                "An approval requires a positive provisional_invoice_cents.",
            )
        order["financed_principal_cents"] = calc.rhu_cents(
            calc.dec(order["provisional_invoice_cents"])
            * Decimal(C.FLOOR_PLAN_ADVANCE_BP)
            / Decimal(10000)
        )
        order["funded_at"] = db.now()
        order["financing_status"] = "FLOOR_PLAN_FUNDED"
    else:
        order["financing_status"] = "NOT_FINANCED"
    db.touch(order)
    return object_out("unit_orders", order)


@bp.post("/unit-orders/<row_id>/floor-plan-payment")
@authorize("DealerPrincipal")
def floor_plan_payment(row_id):
    body = V.body_dict()
    amount = V.field_int(body, "amount_cents", required=True, minimum=1)
    order = must_find("unit_orders", row_id)
    _scope(order["dealer_id"])
    if order["financing_status"] not in ("FLOOR_PLAN_FUNDED", "CURTAILED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Payment is accepted only while the order is FLOOR_PLAN_FUNDED or CURTAILED.",
        )
    principal = int(order["financed_principal_cents"])
    paid = int(order["curtailment_paid_cents"])
    if amount > principal - paid:
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_PRINCIPAL",
            "amount_cents exceeds the remaining floor-plan principal.",
        )
    order["curtailment_paid_cents"] = paid + amount
    if order["curtailment_paid_cents"] == principal:
        order["financing_status"] = "PAID_OFF"
    elif order["financing_status"] == "CURTAILED" and derive.order_curtailment_due(order) == 0:
        order["financing_status"] = "FLOOR_PLAN_FUNDED"
    db.touch(order)
    return object_out("unit_orders", order)
