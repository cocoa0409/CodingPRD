"""Work order intake, tests, diagnosis, scrap, rewind, coil-data, release, deliver, close."""
from datetime import timedelta
from flask import Blueprint, request
from middleware import require_role
from errors import (
    err_invalid_state, err_invalid_input, err_reference_not_found,
    err_stale_version, err_final_test_not_pass, err_claims_open,
    err_segregation,
)
from db import store, new_id
from response import success_object, success_list
from serializers import (
    work_order_view, test_record_view, coil_data_view,
)
from services import calc
from services.lazy import bump, recompute_standing
from routes.common import (
    get_json_body, parse_str_field, parse_int_field, parse_number_field,
    parse_enum_field, get_shop_or_404, get_work_order_or_404, get_motor_or_404,
    get_customer_or_404, get_pagination, paginate,
)

bp = Blueprint("work_orders", __name__)


@bp.route("/shops/<shopId>/work-orders", methods=["POST"])
def create_work_order(shopId):
    require_role("Technician")
    get_shop_or_404(shopId)
    body = get_json_body()
    customer_id = body.get("customer_id")
    motor_id = body.get("motor_id")
    if not isinstance(customer_id, str) or not isinstance(motor_id, str):
        raise err_invalid_input("customer_id and motor_id are required strings")
    customer = store.customers.get(customer_id)
    if customer is None or customer["shop_id"] != shopId:
        raise err_reference_not_found("customer_id does not resolve")
    motor = store.motors.get(motor_id)
    if motor is None or motor["shop_id"] != shopId:
        raise err_reference_not_found("motor_id does not resolve")
    priority = parse_enum_field(body, "priority", {"STANDARD", "RUSH", "EMERGENCY"}, default="STANDARD")

    # State precondition: motor custody must be WITH_CUSTOMER
    if motor["custody"] != "WITH_CUSTOMER":
        raise err_invalid_state("Motor custody must be WITH_CUSTOMER for intake")

    now = store.now()
    wo = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "shop_id": shopId,
        "customer_id": customer_id,
        "motor_id": motor_id,
        "priority": priority,
        "no_charge": False,
        "status": "INTAKE",
        "failure_diagnosis": None,
        "rewind_hours": None,
        "materials_cents": None,
        "replacement_cost_cents": None,
        "active_quote_id": None,
        "invoice_total_cents": 0,
        "delivered_at": None,
        "closed_at": None,
        "_reached_balancing": False,
        "_incoming_recorder": None,
        "_coil_recorder": None,
    }
    store.work_orders[wo["id"]] = wo
    motor["custody"] = "IN_SHOP"
    bump(motor)
    return success_object(work_order_view(wo), status=201)


def _list_work_orders(shop_id_filter):
    items = list(store.work_orders.values())
    if shop_id_filter is not None:
        items = [w for w in items if w["shop_id"] == shop_id_filter]
    if request.args.get("customer_id"):
        items = [w for w in items if w["customer_id"] == request.args["customer_id"]]
    if request.args.get("motor_id"):
        items = [w for w in items if w["motor_id"] == request.args["motor_id"]]
    if request.args.get("active_quote_id"):
        items = [w for w in items if w.get("active_quote_id") == request.args["active_quote_id"]]
    if request.args.get("status"):
        items = [w for w in items if w["status"] == request.args["status"]]
    if request.args.get("priority"):
        items = [w for w in items if w["priority"] == request.args["priority"]]
    items.sort(key=lambda w: w["created_at"])
    return items


@bp.route("/shops/<shopId>/work-orders", methods=["GET"])
def list_work_orders(shopId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    get_shop_or_404(shopId)
    limit, offset = get_pagination()
    items = _list_work_orders(shopId)
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/shops/<shopId>/work-orders/<woId>", methods=["GET"])
def get_work_order(shopId, woId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    return success_object(work_order_view(wo))


@bp.route("/shops/work-orders", methods=["GET"])
def list_work_orders_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    shop_id = request.args.get("shop_id")
    items = _list_work_orders(shop_id)
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/shops/work-orders/<woId>", methods=["GET"])
def get_work_order_flat(woId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    wo = get_work_order_or_404(woId)
    return success_object(work_order_view(wo))


# ---------- Test records ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/tests", methods=["POST"])
def create_test_record(shopId, woId):
    user_id, _role = require_role("Technician")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    kind = parse_enum_field(body, "kind", {"INCOMING", "CORE_LOSS", "FINAL"}, required=True)

    measured_watts = None
    vibration_mm_s = None
    insulation_megohms = None

    if kind == "CORE_LOSS":
        measured_watts = parse_int_field(body, "measured_watts", required=True, min_value=0)
    if kind == "FINAL":
        vibration_mm_s = parse_number_field(body, "vibration_mm_s", required=True, min_value=0, allow_zero=True)
    if kind in ("INCOMING", "FINAL"):
        insulation_megohms = parse_int_field(body, "insulation_megohms", required=True, min_value=0)

    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise err_invalid_input("notes must be a string")

    motor = store.motors[wo["motor_id"]]

    # State checks per kind
    if kind == "INCOMING":
        # must be in INTAKE to advance; also can be recorded in other states? PRD: INTAKE -> INCOMING_TEST
        # Only allow when status == INTAKE (the transition defined); otherwise invalid state
        if wo["status"] != "INTAKE":
            raise err_invalid_state("INCOMING test requires WorkOrder status INTAKE")
        if motor["custody"] != "IN_SHOP":
            raise err_invalid_state("Motor custody must be IN_SHOP")
        verdict = "PASS"  # INCOMING verdict: computed per kind against nameplate; PRD doesn't define FAIL condition -> PASS
    elif kind == "CORE_LOSS":
        # Never changes work order status; can be recorded anytime? We'll allow in any non-terminal state
        # but typically before release. No state gate per PRD.
        verdict = calc.core_loss_verdict(measured_watts, motor["rated_kw"])
    elif kind == "FINAL":
        if wo["status"] != "BALANCING":
            raise err_invalid_state("FINAL test requires WorkOrder status BALANCING")
        # segregation: final recorder != coil data recorder
        coil_recorder = wo.get("_coil_recorder")
        if coil_recorder is not None and coil_recorder == user_id:
            raise err_segregation("Final-test recorder may not equal coil-data recorder")
        verdict = calc.vibration_verdict(vibration_mm_s, motor["frame_mm"])

    now = store.now()
    tr = {
        "id": new_id(),
        "created_at": now,
        "work_order_id": woId,
        "kind": kind,
        "measured_watts": measured_watts,
        "vibration_mm_s": vibration_mm_s,
        "insulation_megohms": insulation_megohms,
        "verdict": verdict,
        "recorded_by": user_id,
        "notes": notes,
    }
    store.test_records[tr["id"]] = tr

    # State transitions
    if kind == "INCOMING":
        wo["status"] = "INCOMING_TEST"
        wo["_incoming_recorder"] = user_id
        bump(wo)
    elif kind == "FINAL":
        wo["status"] = "FINAL_TEST"
        if verdict == "FAIL":
            # automatic rework loop
            wo["status"] = "IN_REWIND"
        bump(wo)

    return success_object(test_record_view(tr), status=201)


@bp.route("/shops/<shopId>/work-orders/<woId>/tests", methods=["GET"])
def list_test_records(shopId, woId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    limit, offset = get_pagination()
    items = [t for t in store.test_records.values() if t["work_order_id"] == woId]
    if request.args.get("kind"):
        items = [t for t in items if t["kind"] == request.args["kind"]]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([test_record_view(t) for t in page], limit, offset, total)


@bp.route("/shops/test-records", methods=["GET"])
def list_test_records_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    items = list(store.test_records.values())
    if request.args.get("work_order_id"):
        items = [t for t in items if t["work_order_id"] == request.args["work_order_id"]]
    if request.args.get("kind"):
        items = [t for t in items if t["kind"] == request.args["kind"]]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([test_record_view(t) for t in page], limit, offset, total)


@bp.route("/shops/test-records/<testRecordId>", methods=["GET"])
def get_test_record_flat(testRecordId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    from routes.common import get_test_record_or_404
    tr = get_test_record_or_404(testRecordId)
    return success_object(test_record_view(tr))


# ---------- Diagnose ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/diagnose", methods=["POST"])
def diagnose(shopId, woId):
    require_role("Technician")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    failure_diagnosis = parse_str_field(body, "failure_diagnosis", required=True)
    rewind_hours = parse_int_field(body, "rewind_hours", required=True, min_value=0)
    materials_cents = parse_int_field(body, "materials_cents", required=True, min_value=0, allow_zero=True)
    replacement_cost_cents = parse_int_field(body, "replacement_cost_cents", required=True, min_value=0)

    # State check
    if wo["status"] != "INCOMING_TEST":
        raise err_invalid_state("WorkOrder must be in INCOMING_TEST for diagnose")

    # Precondition: at least one INCOMING test exists
    has_incoming = any(
        t for t in store.test_records.values()
        if t["work_order_id"] == woId and t["kind"] == "INCOMING"
    )
    if not has_incoming:
        raise err_invalid_state("At least one INCOMING TestRecord required")

    wo["failure_diagnosis"] = failure_diagnosis
    wo["rewind_hours"] = rewind_hours
    wo["materials_cents"] = materials_cents
    wo["replacement_cost_cents"] = replacement_cost_cents
    wo["status"] = "DIAGNOSED"
    bump(wo)
    return success_object(work_order_view(wo))


# ---------- Scrap ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/scrap", methods=["POST"])
def scrap(shopId, woId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    if wo["status"] not in ("INTAKE", "INCOMING_TEST", "DIAGNOSED", "QUOTED", "AWAITING_APPROVAL"):
        raise err_invalid_state("WorkOrder cannot be scrapped from this state")
    # any ISSUED quote -> SUPERSEDED
    for q in store.quotes.values():
        if q["work_order_id"] == woId and q["status"] == "ISSUED":
            q["status"] = "SUPERSEDED"
            bump(q)
    wo["active_quote_id"] = None
    wo["status"] = "SCRAPPED"
    motor = store.motors[wo["motor_id"]]
    motor["custody"] = "WITH_CUSTOMER"
    bump(motor)
    bump(wo)
    return success_object(work_order_view(wo))


# ---------- Rewind process ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/start-rewind", methods=["POST"])
def start_rewind(shopId, woId):
    require_role("WindingTechnician")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    if wo["status"] != "APPROVED":
        raise err_invalid_state("WorkOrder must be APPROVED to start rewind")
    # sanity precondition: no PoolLoan against this WO in status OUT with spare still IN_POOL
    for loan in store.pool_loans.values():
        if loan["work_order_id"] == woId and loan["status"] == "OUT":
            spare = store.motors.get(loan["spare_motor_id"])
            if spare is not None and spare["custody"] == "IN_POOL":
                raise err_invalid_state("PoolLoan OUT with spare still IN_POOL")
    wo["status"] = "IN_REWIND"
    bump(wo)
    return success_object(work_order_view(wo))


@bp.route("/shops/<shopId>/work-orders/<woId>/coil-data", methods=["POST"])
def record_coil_data(shopId, woId):
    user_id, _role = require_role("WindingTechnician")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    wire_gauge_awg = parse_str_field(body, "wire_gauge_awg", required=True)
    turns_per_coil = parse_int_field(body, "turns_per_coil", required=True, min_value=0)
    coils_per_phase = parse_int_field(body, "coils_per_phase", required=True, min_value=0)
    connection = parse_enum_field(body, "connection", {"WYE", "DELTA"}, required=True)
    winding_resistance_ohms = parse_number_field(body, "winding_resistance_ohms", required=True)

    if wo["status"] != "IN_REWIND":
        raise err_invalid_state("WorkOrder must be IN_REWIND to record coil data")

    # segregation: recorded_by != incoming-test recorder
    incoming_recorder = wo.get("_incoming_recorder")
    if incoming_recorder is not None and incoming_recorder == user_id:
        raise err_segregation("Coil-data recorder may not equal incoming-test recorder")

    now = store.now()
    c = {
        "id": new_id(),
        "created_at": now,
        "work_order_id": woId,
        "wire_gauge_awg": wire_gauge_awg,
        "turns_per_coil": turns_per_coil,
        "coils_per_phase": coils_per_phase,
        "connection": connection,
        "winding_resistance_ohms": winding_resistance_ohms,
        "easa_form_version": calc.EASA_FORM_VERSION,
        "recorded_by": user_id,
    }
    store.coil_data_records[c["id"]] = c
    wo["_coil_recorder"] = user_id
    wo["_reached_balancing"] = True
    wo["status"] = "BALANCING"
    bump(wo)
    return success_object(coil_data_view(c), status=201)


@bp.route("/shops/<shopId>/work-orders/<woId>/coil-data", methods=["GET"])
def list_coil_data(shopId, woId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    limit, offset = get_pagination()
    items = [c for c in store.coil_data_records.values() if c["work_order_id"] == woId]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([coil_data_view(c) for c in page], limit, offset, total)


@bp.route("/shops/coil-data-records", methods=["GET"])
def list_coil_data_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    items = list(store.coil_data_records.values())
    if request.args.get("work_order_id"):
        items = [c for c in items if c["work_order_id"] == request.args["work_order_id"]]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([coil_data_view(c) for c in page], limit, offset, total)


@bp.route("/shops/coil-data-records/<coilDataRecordId>", methods=["GET"])
def get_coil_data_flat(coilDataRecordId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    from routes.common import get_coil_record_or_404
    c = get_coil_record_or_404(coilDataRecordId)
    return success_object(coil_data_view(c))


# ---------- Release ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/release", methods=["POST"])
def release(shopId, woId):
    require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    if wo["status"] != "FINAL_TEST":
        raise err_invalid_state("WorkOrder must be FINAL_TEST to release")

    # Latest FINAL verdict must be PASS
    final_tests = [
        t for t in store.test_records.values()
        if t["work_order_id"] == woId and t["kind"] == "FINAL"
    ]
    if not final_tests:
        raise err_final_test_not_pass("No FINAL test record")
    final_tests.sort(key=lambda t: t["created_at"])
    latest_final = final_tests[-1]
    if latest_final["verdict"] != "PASS":
        raise err_final_test_not_pass("Latest FINAL test verdict is not PASS")

    # Any CORE_LOSS record must be PASS
    for t in store.test_records.values():
        if t["work_order_id"] == woId and t["kind"] == "CORE_LOSS" and t["verdict"] != "PASS":
            raise err_final_test_not_pass("A CORE_LOSS record has verdict FAIL")

    # Find accepted quote
    accepted_quote = None
    for q in store.quotes.values():
        if q["work_order_id"] == woId and q["status"] == "ACCEPTED":
            accepted_quote = q
            break

    test_records = [t for t in store.test_records.values() if t["work_order_id"] == woId]
    total = calc.compute_invoice_total(
        shop, wo, accepted_quote, test_records, wo["_reached_balancing"]
    )
    wo["invoice_total_cents"] = total
    wo["status"] = "READY_FOR_PICKUP"

    now = store.now()
    inv = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "work_order_id": woId,
        "customer_id": wo["customer_id"],
        "total_cents": total,
        "amount_paid_cents": 0,
        "balance_due_cents": total,
        "issued_at": now,
        "due_at": now + timedelta(days=30),
        "status": "OPEN",
    }
    store.invoices[inv["id"]] = inv
    bump(wo)
    return success_object(work_order_view(wo))


# ---------- Deliver ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/deliver", methods=["POST"])
def deliver(shopId, woId):
    require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    expected = body.get("expected_work_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_input("expected_work_order_version is required and must be an integer")

    if wo["status"] != "READY_FOR_PICKUP":
        raise err_invalid_state("WorkOrder must be READY_FOR_PICKUP to deliver")

    # OCC check
    if expected != wo["version"]:
        raise err_stale_version()

    # Invoice must be OPEN or PAID
    invoices = [i for i in store.invoices.values() if i["work_order_id"] == woId]
    # Find the active invoice (non-VOID)
    active_inv = None
    for i in invoices:
        if i["status"] in ("OPEN", "PAID", "OVERDUE"):
            active_inv = i
            break
    if active_inv is not None and active_inv["status"] not in ("OPEN", "PAID", "OVERDUE"):
        raise err_invalid_state("Invoice must be OPEN or PAID for delivery")

    now = store.now()
    wo["delivered_at"] = now
    wo["status"] = "DELIVERED"
    motor = store.motors[wo["motor_id"]]
    motor["custody"] = "WITH_CUSTOMER"
    bump(motor)

    # PoolLoans OUT: recompute due_at; flip OVERDUE if past
    for loan in store.pool_loans.values():
        if loan["work_order_id"] == woId and loan["status"] == "OUT":
            loan["due_at"] = now + timedelta(days=shop["pool_loan_grace_days"])
            if now > loan["due_at"]:
                loan["status"] = "OVERDUE"
                od, oc = calc.compute_overdue(loan["due_at"], loan.get("returned_at"), now, shop["pool_loan_daily_cents"])
                loan["overdue_days"] = od
                loan["overdue_charge_cents"] = oc
            bump(loan)
            contract = store.pool_contracts.get(loan["contract_id"])
            if contract:
                recompute_standing(contract["customer_id"])

    # Resolve any FREE_REWIND warranty claim waiting on this resolution work order
    for claim in store.warranty_claims.values():
        if claim.get("resolution_work_order_id") == woId and claim["status"] == "APPROVED":
            claim["status"] = "RESOLVED"
            bump(claim)

    bump(wo)
    return success_object(work_order_view(wo))


# ---------- Close ----------

@bp.route("/shops/<shopId>/work-orders/<woId>/close", methods=["POST"])
def close(shopId, woId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    if wo["status"] != "DELIVERED":
        raise err_invalid_state("WorkOrder must be DELIVERED to close")
    # No warranty claim in FILED/UNDER_REVIEW/APPROVED
    for claim in store.warranty_claims.values():
        if claim["work_order_id"] == woId and claim["status"] in ("FILED", "UNDER_REVIEW", "APPROVED"):
            raise err_claims_open("Open warranty claim blocks close")
    # All pool loans RETURNED
    for loan in store.pool_loans.values():
        if loan["work_order_id"] == woId and loan["status"] != "RETURNED":
            raise err_claims_open("Unreturned pool loan blocks close")
    now = store.now()
    wo["closed_at"] = now
    wo["status"] = "CLOSED"
    bump(wo)
    return success_object(work_order_view(wo))
