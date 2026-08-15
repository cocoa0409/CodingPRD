from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, clock_now, now_iso, fmt_dt, parse_dt, next_cert_number
from errors import ApiError
from helpers import (
    add_delay_hours,
    add_trace,
    base_fields,
    ber_threshold_cents,
    create_compliance_records,
    create_invoice,
    credit_held,
    get_customer_or_404,
    get_disc_or_404,
    get_unit_or_404,
    get_wo_or_404,
    hours_between,
    ledger_fields,
    list_response,
    pub,
    q_cents,
    sort_items,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("work_orders", __name__, url_prefix="/mro")


def _new_work_order(customer_id, unit_id, work_scope, status, labor_estimate=None, labor_charge=None):
    wo = dict(base_fields())
    wo.update(
        {
            "customer_id": customer_id,
            "unit_id": unit_id,
            "work_scope": work_scope,
            "status": status,
            "received_at": now_iso(),
            "quote_submitted_at": None,
            "accumulated_delay_hours": 0,
            "promised_return_at": None,
            "released_at": None,
            "labor_estimate_cents": labor_estimate,
            "parts_estimate_cents": None,
            "ber_flag": False,
            "labor_charge_cents": labor_charge,
            "parts_charge_cents": 0,
            "test_attempt_count": 0,
            "open_discrepancy_count": 0,
            "technician_user_id": None,
            "inspector_user_id": None,
        }
    )
    store.work_orders[wo["id"]] = wo
    return wo


# ---------------------------------------------------------------------------
# Induction
# ---------------------------------------------------------------------------


@bp.route("/work-orders", methods=["POST"])
@require_roles("CustomerServiceRep")
def create_work_order():
    body = validate_body(
        get_json_body(),
        {
            "customer_id": ("str", True),
            "unit_id": ("str", True),
            "work_scope": ("enum", True, ["REPAIR", "OVERHAUL", "WARRANTY_REWORK"]),
        },
    )
    cust = get_customer_or_404(body["customer_id"])
    unit = get_unit_or_404(body["unit_id"])
    # Order pinned by PRD 2.9: custody availability, scope reservation, ownership.
    if unit["custody_status"] != "OFF_SITE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409, "Unit is not OFF_SITE")
    if body["work_scope"] == "WARRANTY_REWORK":
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "WARRANTY_REWORK scope is system-reserved"
        )
    if unit["ownership"] == "CUSTOMER" and unit["owner_customer_id"] != cust["id"]:
        raise ApiError(
            "ERR_UNIT_OWNER_MISMATCH", 422, "Unit owner does not match work-order customer"
        )
    wo = _new_work_order(cust["id"], unit["id"], body["work_scope"], "TEARDOWN_IN_PROGRESS")
    unit["custody_status"] = "IN_SHOP"
    touch(unit)
    add_trace(unit["id"], "INDUCT", work_order_id=wo["id"])
    create_compliance_records(wo["id"], unit["part_id"])
    return ok(pub(wo), 201)


@bp.route("/work-orders/<workOrderId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_work_order(workOrderId):
    return ok(pub(get_wo_or_404(workOrderId)))


@bp.route("/customers/<customerId>/work-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_customer_work_orders(customerId):
    cust = get_customer_or_404(customerId)
    return list_response([w for w in store.work_orders.values() if w["customer_id"] == cust["id"]])


@bp.route("/units/<unitId>/work-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_unit_work_orders(unitId):
    unit = get_unit_or_404(unitId)
    return list_response([w for w in store.work_orders.values() if w["unit_id"] == unit["id"]])


# ---------------------------------------------------------------------------
# Teardown, discrepancy cards
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<workOrderId>/teardown-complete", methods=["POST"])
@require_roles("Technician")
def teardown_complete(workOrderId):
    wo = get_wo_or_404(workOrderId)
    if wo["status"] != "TEARDOWN_IN_PROGRESS":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in TEARDOWN_IN_PROGRESS")
    if wo["open_discrepancy_count"] > 0:
        raise ApiError("ERR_OPEN_DISCREPANCIES", 409, "OPEN discrepancy cards remain")
    wo["status"] = "AWAITING_QUOTE"
    touch(wo)
    return ok(pub(wo))


@bp.route("/work-orders/<workOrderId>/discrepancies", methods=["POST"])
@require_roles("Technician")
def file_discrepancy(workOrderId):
    wo = get_wo_or_404(workOrderId)
    body = validate_body(
        get_json_body(),
        {"finding_text": ("str", True), "severity": ("enum", True, ["MINOR", "MAJOR"])},
    )
    card = dict(base_fields())
    card.update(
        {
            "work_order_id": wo["id"],
            "finding_text": body["finding_text"],
            "severity": body["severity"],
            "disposition_text": None,
            "status": "OPEN",
        }
    )
    store.discrepancies[card["id"]] = card
    wo["open_discrepancy_count"] += 1
    touch(wo)
    return ok(pub(card), 201)


@bp.route("/work-orders/<workOrderId>/discrepancies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_discrepancies(workOrderId):
    wo = get_wo_or_404(workOrderId)
    return list_response([c for c in store.discrepancies.values() if c["work_order_id"] == wo["id"]])


@bp.route("/discrepancies/<discrepancyId>/disposition", methods=["POST"])
@require_roles("Technician")
def disposition_discrepancy(discrepancyId):
    card = get_disc_or_404(discrepancyId)
    body = validate_body(get_json_body(), {"disposition_text": ("str", True)})
    if card["status"] != "OPEN":
        raise ApiError("ERR_DISCREPANCY_INVALID_STATE", 409, "Discrepancy card is not OPEN")
    card["status"] = "DISPOSITIONED"
    card["disposition_text"] = body["disposition_text"]
    touch(card)
    wo = store.work_orders.get(card["work_order_id"])
    if wo is not None:
        wo["open_discrepancy_count"] = max(0, wo["open_discrepancy_count"] - 1)
        touch(wo)
    return ok(pub(card))


# ---------------------------------------------------------------------------
# Quoting cycle
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<workOrderId>/quote", methods=["POST"])
@require_roles("CustomerServiceRep")
def submit_quote(workOrderId):
    body = validate_body(
        get_json_body(),
        {
            "labor_estimate_cents": ("int", True),
            "parts_estimate_cents": ("int", True),
            "scrap_option_ack": ("bool", False),
        },
    )
    wo = get_wo_or_404(workOrderId)
    if wo["status"] not in ("AWAITING_QUOTE", "QUOTE_SUBMITTED"):
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not awaiting a quote"
        )
    unit = store.units[wo["unit_id"]]
    part = store.parts[unit["part_id"]]
    ber = (body["labor_estimate_cents"] + body["parts_estimate_cents"]) >= ber_threshold_cents(part)
    # Safety check before the fiscal check (pinned order).
    if ber and body["scrap_option_ack"] is not True:
        raise ApiError(
            "ERR_BER_SCRAP_ACK_REQUIRED", 403, "BER quote requires scrap_option_ack=true"
        )
    cust = store.customers[wo["customer_id"]]
    if credit_held(cust):
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", 402, "Customer is on credit hold")
    wo["labor_estimate_cents"] = body["labor_estimate_cents"]
    wo["parts_estimate_cents"] = body["parts_estimate_cents"]
    wo["ber_flag"] = ber
    wo["labor_charge_cents"] = body["labor_estimate_cents"]
    wo["quote_submitted_at"] = now_iso()
    wo["promised_return_at"] = fmt_dt(
        parse_dt(wo["received_at"]) + timedelta(hours=cust["contract_tat_hours"])
    )
    wo["status"] = "QUOTE_SUBMITTED"
    touch(wo)
    return ok(pub(wo))


@bp.route("/work-orders/<workOrderId>/quote-approval", methods=["POST"])
@require_roles("Customer")
def approve_quote(workOrderId):
    body = validate_body(
        get_json_body(), {"expected_work_order_version": ("int", True)}
    )
    wo = get_wo_or_404(workOrderId)
    # OCC fires after existence, before from-state and ownership (PRD 2.9).
    if body["expected_work_order_version"] != wo["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Work order version has advanced")
    if wo["status"] != "QUOTE_SUBMITTED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in QUOTE_SUBMITTED")
    if request.user_id != wo["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the work-order customer")
    add_delay_hours(wo, hours_between(wo["quote_submitted_at"], clock_now()))
    wo["status"] = "REPAIR_IN_PROGRESS"
    touch(wo)
    return ok(pub(wo))


@bp.route("/work-orders/<workOrderId>/quote-decline", methods=["POST"])
@require_roles("Customer")
def decline_quote(workOrderId):
    body = validate_body(
        get_json_body(),
        {"disposition": ("enum", True, ["RETURN_UNREPAIRED", "SCRAP"])},
    )
    wo = get_wo_or_404(workOrderId)
    # Order: from-state, then scrap-requires-BER, then ownership (PRD 2.9).
    if wo["status"] != "QUOTE_SUBMITTED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in QUOTE_SUBMITTED")
    if body["disposition"] == "SCRAP" and not wo["ber_flag"]:
        raise ApiError("ERR_SCRAP_REQUIRES_BER", 409, "Scrap decline requires ber_flag")
    if request.user_id != wo["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the work-order customer")
    add_delay_hours(wo, hours_between(wo["quote_submitted_at"], clock_now()))
    unit = store.units[wo["unit_id"]]
    if body["disposition"] == "RETURN_UNREPAIRED":
        wo["status"] = "CANCELLED"
        unit["custody_status"] = "AWAITING_SHIPMENT"
        touch(unit)
    else:  # SCRAP
        wo["status"] = "BER_SCRAPPED"
        unit["condition_status"] = "SCRAPPED"
        unit["custody_status"] = "AWAITING_SHIPMENT"
        touch(unit)
        add_trace(unit["id"], "SCRAP", work_order_id=wo["id"])
    touch(wo)
    return ok(pub(wo))


# ---------------------------------------------------------------------------
# Repair execution, directive compliance
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<workOrderId>/directive-compliance", methods=["POST"])
@require_roles("Technician")
def record_directive_compliance(workOrderId):
    wo = get_wo_or_404(workOrderId)
    body = validate_body(
        get_json_body(),
        {
            "directive_number": ("str", True),
            "result": ("enum", True, ["COMPLIED", "NOT_APPLICABLE"]),
            "note": ("str", False),
        },
    )
    rec = None
    for dc in store.compliances.values():
        if dc["work_order_id"] == wo["id"] and dc["directive_number"] == body["directive_number"]:
            rec = dc
            break
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "No compliance record for directive_number")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "DirectiveCompliance is not PENDING")
    rec["status"] = body["result"]
    if body["note"] is not None:
        rec["compliance_note"] = body["note"]
    touch(rec)
    return ok(pub(rec), 201)


@bp.route("/work-orders/<workOrderId>/directive-compliances", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_directive_compliances(workOrderId):
    wo = get_wo_or_404(workOrderId)
    return list_response([c for c in store.compliances.values() if c["work_order_id"] == wo["id"]])


@bp.route("/work-orders/<workOrderId>/complete-repair", methods=["POST"])
@require_roles("Technician")
def complete_repair(workOrderId):
    wo = get_wo_or_404(workOrderId)
    if wo["status"] != "REPAIR_IN_PROGRESS":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in REPAIR_IN_PROGRESS")
    # Safety: every mandatory directive complied or N/A.
    for dc in store.compliances.values():
        if (
            dc["work_order_id"] == wo["id"]
            and dc["mandatory"]
            and dc["status"] not in ("COMPLIED", "NOT_APPLICABLE")
        ):
            raise ApiError(
                "ERR_AD_COMPLIANCE_INCOMPLETE", 403, "Mandatory directive still PENDING"
            )
    if wo["open_discrepancy_count"] > 0:
        raise ApiError("ERR_OPEN_DISCREPANCIES", 409, "OPEN discrepancy cards remain")
    for card in store.discrepancies.values():
        if card["work_order_id"] == wo["id"] and card["status"] == "DISPOSITIONED":
            card["status"] = "CLOSED"
            touch(card)
    wo["technician_user_id"] = request.user_id
    wo["status"] = "READY_FOR_TEST"
    touch(wo)
    return ok(pub(wo))


# ---------------------------------------------------------------------------
# ATP results and release
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<workOrderId>/test-results", methods=["POST"])
@require_roles("Inspector")
def record_test_results(workOrderId):
    body = validate_body(
        get_json_body(),
        {"result": ("enum", True, ["PASS", "FAIL"]), "atp_reference": ("str", True)},
    )
    wo = get_wo_or_404(workOrderId)
    if wo["status"] != "READY_FOR_TEST":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in READY_FOR_TEST")
    if request.user_id == wo["technician_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Inspector must differ from the technician who performed the repair",
        )
    now = clock_now()
    covering = None
    for b in sort_items([b for b in store.bookings.values() if b["work_order_id"] == wo["id"]]):
        if (
            b["status"] == "BOOKED"
            and parse_dt(b["start_time"]) <= now < parse_dt(b["end_time"])
        ):
            covering = b
            break
    if covering is None:
        raise ApiError(
            "ERR_NO_ACTIVE_TEST_BOOKING", 409, "No BOOKED booking covers the current clock"
        )
    wo["test_attempt_count"] += 1
    covering["status"] = "COMPLETED"
    touch(covering)
    if body["result"] == "PASS":
        wo["status"] = "TEST_PASSED"
        if wo["work_scope"] in ("OVERHAUL", "WARRANTY_REWORK"):
            unit = store.units[wo["unit_id"]]
            unit["cycles_since_overhaul"] = 0
            touch(unit)
    else:
        wo["status"] = "REPAIR_IN_PROGRESS"
        card = dict(base_fields())
        card.update(
            {
                "work_order_id": wo["id"],
                "finding_text": "ATP FAILURE: %s" % body["atp_reference"],
                "severity": "MAJOR",
                "disposition_text": None,
                "status": "OPEN",
            }
        )
        store.discrepancies[card["id"]] = card
        wo["open_discrepancy_count"] += 1
    touch(wo)
    return ok(pub(wo))


@bp.route("/work-orders/<workOrderId>/release", methods=["POST"])
@require_roles("Inspector")
def release_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    # From-state check fires before the safety check (PRD 2.9).
    if wo["status"] != "TEST_PASSED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in TEST_PASSED")
    if request.user_id == wo["technician_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Inspector must differ from the technician who performed the repair",
        )
    cert = dict(ledger_fields())
    cert_number = next_cert_number()
    cert.update(
        {
            "work_order_id": wo["id"],
            "cert_number": cert_number,
            "signed_by": request.user_id,
            "issued_at": now_iso(),
            "status": "ISSUED",
        }
    )
    store.certificates[cert["id"]] = cert
    wo["released_at"] = now_iso()
    wo["inspector_user_id"] = request.user_id
    wo["status"] = "RELEASED"
    unit = store.units[wo["unit_id"]]
    unit["condition_status"] = "SERVICEABLE"
    unit["custody_status"] = "IN_POOL" if unit["ownership"] == "SHOP" else "AWAITING_SHIPMENT"
    touch(unit)
    event_type = (
        "RELEASE_OVERHAUL" if wo["work_scope"] in ("OVERHAUL", "WARRANTY_REWORK") else "RELEASE_REPAIR"
    )
    add_trace(unit["id"], event_type, work_order_id=wo["id"], notes=cert_number)
    touch(wo)
    return ok(pub(wo))


@bp.route("/work-orders/<workOrderId>/certificate", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_certificate(workOrderId):
    wo = get_wo_or_404(workOrderId)
    certs = sort_items([c for c in store.certificates.values() if c["work_order_id"] == wo["id"]])
    from middleware import pagination_params

    limit, offset = pagination_params()
    page = certs[offset : offset + limit]
    from response import ok_list

    return ok_list([pub(c) for c in page], limit, offset, len(certs))


@bp.route("/work-orders/<workOrderId>/close", methods=["POST"])
@require_roles("CustomerServiceRep")
def close_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    if wo["status"] != "RELEASED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in RELEASED")
    has_invoice = any(
        i["source_type"] == "WORK_ORDER" and i["work_order_id"] == wo["id"]
        for i in store.invoices.values()
    )
    if not has_invoice:
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE", 409, "Work-order invoice not yet generated"
        )
    unit = store.units[wo["unit_id"]]
    if unit["ownership"] == "CUSTOMER":
        unit["custody_status"] = "SHIPPED"
        touch(unit)
    wo["status"] = "CLOSED"
    touch(wo)
    if wo["work_scope"] == "WARRANTY_REWORK":
        for claim in store.claims.values():
            if claim["rework_work_order_id"] == wo["id"] and claim["status"] == "ACCEPTED":
                claim["status"] = "SETTLED"
                touch(claim)
    return ok(pub(wo))


# ---------------------------------------------------------------------------
# Work-order invoice generation
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<workOrderId>/invoice", methods=["POST"])
@require_roles("CustomerServiceRep")
def generate_invoice(workOrderId):
    wo = get_wo_or_404(workOrderId)
    if wo["status"] != "RELEASED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in RELEASED")
    if any(
        i["source_type"] == "WORK_ORDER" and i["work_order_id"] == wo["id"]
        for i in store.invoices.values()
    ):
        raise ApiError("ERR_INVOICE_ALREADY_EXISTS", 409, "Work-order invoice already exists")
    labor = wo["labor_charge_cents"] or 0
    parts = sum(
        r["extended_price_cents"] or 0
        for r in store.requisitions.values()
        if r["work_order_id"] == wo["id"] and r["status"] == "ISSUED"
    )
    test_fee = sum(
        b["fee_cents"] or 0
        for b in store.bookings.values()
        if b["work_order_id"] == wo["id"] and b["status"] == "COMPLETED"
    )
    subtotal = labor + parts + test_fee
    cust = store.customers[wo["customer_id"]]
    if wo["work_scope"] == "WARRANTY_REWORK":
        penalty = 0
        penalty_variant = "NONE"
        warranty_credit = 0
        for claim in store.claims.values():
            if claim["rework_work_order_id"] == wo["id"]:
                warranty_credit = claim["credit_cents"] or 0
                break
        total = max(0, subtotal - warranty_credit)
    else:
        warranty_credit = 0
        elapsed = hours_between(wo["received_at"], parse_dt(wo["released_at"]))
        if cust["penalty_delay_rule"] == "ADJUSTED":
            basis = elapsed - Decimal(str(wo["accumulated_delay_hours"]))
        else:
            basis = elapsed
        excess = max(Decimal("0"), basis - Decimal(cust["contract_tat_hours"]))
        raw = q_cents(excess * Decimal(cust["tat_penalty_rate_cents_per_hour"]))
        cap = q_cents(
            Decimal(cust["tat_penalty_cap_pct"]) / Decimal(100) * Decimal(subtotal)
        )
        # Cap applies last, after the raw penalty.
        penalty = min(raw, cap)
        penalty_variant = cust["penalty_delay_rule"]
        total = max(0, subtotal - penalty)
    inv = create_invoice(
        "WORK_ORDER",
        wo["customer_id"],
        work_order_id=wo["id"],
        labor_cents=labor,
        parts_cents=parts,
        test_fee_cents=test_fee,
        penalty_credit_cents=penalty,
        total_cents=total,
        warranty_credit_applied_cents=warranty_credit,
        penalty_variant=penalty_variant,
    )
    return ok(pub(inv), 201)
