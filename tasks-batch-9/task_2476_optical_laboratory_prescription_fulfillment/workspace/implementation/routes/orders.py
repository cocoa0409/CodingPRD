"""Orders, frame layouts, and the billing dimension (PRD 3.3, 3.4, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import serializers as S
import services
from auth import acting_user_id, require_roles
from envelope import created, listing, ok
from errors import ApiError
from store import db, now, sorted_rows, stamp_common, touch
from validate import F, json_body, validate_body

bp = Blueprint("orders", __name__)


# --- RxOrder ---------------------------------------------------------------

@bp.post("/rx-orders")
def create_rx_order():
    body = json_body()
    data = validate_body(
        body,
        [
            F("patient_id", "string"),
            F("prescription_id", "string"),
            F("lens_design_id", "string"),
            F("frame_sku", "string", min_len=1),
            F("frame_retail_cents", "int", minimum=0),
            F("requested_coatings", "array", item_kind="string"),
            F("monocular_pd_od_mm", "number", minimum=20.0, maximum=40.0),
            F("monocular_pd_os_mm", "number", minimum=20.0, maximum=40.0),
            F("fitting_height_mm", "number", minimum=8.0, maximum=40.0),
            F("expedite_requested", "bool", required=False, default=False),
            F("prior_auth_reference", "string", required=False),
        ],
    )
    patient = services.get_or_404(db.patients, data["patient_id"], "ERR_PATIENT_NOT_FOUND")
    rx = services.get_or_404(db.prescriptions, data["prescription_id"], "ERR_PRESCRIPTION_NOT_FOUND")
    design = services.get_or_404(db.lens_designs, data["lens_design_id"], "ERR_LENS_DESIGN_NOT_FOUND")
    user_id, _role = require_roles("StoreOptician")

    if rx["patient_id"] != patient["id"]:
        raise ApiError("ERR_RX_PATIENT_MISMATCH")

    allowed = design["allowed_coatings"] or []
    for code in data["requested_coatings"]:
        if code not in allowed:
            raise ApiError("ERR_COATING_NOT_AVAILABLE_FOR_DESIGN")

    if rx["requires_multifocal"] and design["design_type"] == "SINGLE_VISION":
        raise ApiError("ERR_DESIGN_INCOMPATIBLE_WITH_RX")

    if rx["verification_status"] != "VERIFIED":
        raise ApiError("ERR_RX_NOT_VERIFIED")

    if now() >= rx["expires_at"]:
        raise ApiError("ERR_RX_EXPIRED")

    pd_gap = abs(
        calc.D(data["monocular_pd_od_mm"]) + calc.D(data["monocular_pd_os_mm"])
        - calc.D(rx["pd_distance_mm"])
    )
    if pd_gap > Decimal("1.0"):
        raise ApiError("ERR_MONOCULAR_PD_INCONSISTENT")

    plan = services.patient_plan(patient)
    if (design["design_type"] == "SPECIALTY" and plan is not None
            and plan.get("specialty_requires_prior_auth")
            and data["prior_auth_reference"] is None):
        raise ApiError("ERR_PRIOR_AUTH_REQUIRED")

    row = stamp_common(
        {
            "patient_id": data["patient_id"],
            "prescription_id": data["prescription_id"],
            "lens_design_id": data["lens_design_id"],
            "frame_sku": data["frame_sku"],
            "frame_retail_cents": data["frame_retail_cents"],
            "requested_coatings": list(data["requested_coatings"]),
            "monocular_pd_od_mm": data["monocular_pd_od_mm"],
            "monocular_pd_os_mm": data["monocular_pd_os_mm"],
            "fitting_height_mm": data["fitting_height_mm"],
            "expedite_requested": bool(data["expedite_requested"]),
            "prior_auth_reference": data["prior_auth_reference"],
            "product_tier": design["product_tier"],
            "fulfillment_status": "DRAFT",
            "billing_status": "PROVISIONAL_QUOTED",
            "quote_variant": "PROVISIONAL",
            "gross_charge_cents": 0,
            "estimated_benefit_cents": 0,
            "insurance_benefit_cents": 0,
            "patient_portion_cents": 0,
            "lab_writeoff_cents": 0,
            "patient_paid_cents": 0,
            "expedite_fee_cents": 0,
            "promised_tat_hours": 0,
            "promised_due_at": None,
            "tat_commitment_status": "ON_TRACK",
            "remake_count": 0,
            "benefit_applied_at": None,
            "created_by_optician_id": user_id,
            "_backorder_count": 0,
        }
    )
    services.apply_provisional_quote(row)
    db.rx_orders[row["id"]] = row
    return created(S.rx_order(row))


@bp.get("/rx-orders/<rid>")
def get_rx_order(rid):
    row = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles()
    return ok(S.rx_order(row))


@bp.get("/rx-orders")
def list_rx_orders():
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager",
                  "BenefitsAdministrator")
    rows = sorted_rows(db.rx_orders)
    for arg in ("patient_id", "prescription_id", "lens_design_id", "fulfillment_status",
                "billing_status", "tat_commitment_status"):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(arg) == value]
    return listing(rows, S.rx_order)


@bp.get("/rx-orders/<rid>/charge-summary")
def charge_summary(rid):
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician", "LabManager", "BenefitsAdministrator")
    balance = order["patient_portion_cents"] - order["patient_paid_cents"]
    invariant = (
        order["gross_charge_cents"]
        == order["insurance_benefit_cents"] + order["patient_portion_cents"] + order["lab_writeoff_cents"]
    )
    return ok(
        {
            "gross_charge_cents": order["gross_charge_cents"],
            "estimated_benefit_cents": order["estimated_benefit_cents"],
            "insurance_benefit_cents": order["insurance_benefit_cents"],
            "patient_portion_cents": order["patient_portion_cents"],
            "lab_writeoff_cents": order["lab_writeoff_cents"],
            "patient_paid_cents": order["patient_paid_cents"],
            "patient_balance_due_cents": balance,
            "expedite_fee_cents": order["expedite_fee_cents"],
            "quote_variant": order["quote_variant"],
            "invariant_holds": invariant,
        }
    )


@bp.post("/rx-orders/<rid>/benefit-application")
def benefit_application(rid):
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("BenefitsAdministrator")
    if order["billing_status"] not in ("PROVISIONAL_QUOTED", "BENEFIT_VOIDED"):
        raise ApiError("ERR_BILLING_STATE_INVALID")
    job = services.routed_job(order["id"])
    if job is None:
        raise ApiError("ERR_ROUTE_NOT_DETERMINED")

    patient = services.order_patient(order)
    plan = services.patient_plan(patient)
    used_elsewhere = services.benefit_used_cents(patient, exclude_order_id=order["id"])
    if plan is not None:
        cap_remaining = max(0, int(plan.get("annual_benefit_cap_cents") or 0) - used_elsewhere)
        if cap_remaining == 0:
            raise ApiError("ERR_BENEFIT_CAP_EXHAUSTED")

    design = services.order_design(order)
    q = calc.quote(order, design, job["route"], "FINAL")
    benefit = calc.benefit_waterfall(
        q["components"], design, plan, q["expedite_fee_cents"], apply_annual_cap=True,
        benefit_used_excluding_this_order=used_elsewhere,
    )
    order["gross_charge_cents"] = q["gross_charge_cents"]
    order["expedite_fee_cents"] = q["expedite_fee_cents"]
    order["insurance_benefit_cents"] = benefit
    order["patient_portion_cents"] = (
        q["gross_charge_cents"] - benefit - order["lab_writeoff_cents"]
    )
    order["quote_variant"] = "FINAL"
    order["benefit_applied_at"] = now()
    order["billing_status"] = "BENEFIT_APPLIED" if plan is not None else "SELF_PAY_FINAL"
    touch(order)

    if not services.has_entry(order["id"], "ORDER_CHARGE"):
        services.append_entry(order["id"], "ORDER_CHARGE", order["gross_charge_cents"],
                              "Final order charge")
    if benefit > 0:
        services.append_entry(order["id"], "INSURANCE_BENEFIT", -benefit, "Plan benefit applied")
    return ok(S.rx_order(order))


@bp.post("/rx-orders/<rid>/benefit-void")
def benefit_void(rid):
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("BenefitsAdministrator")
    if order["billing_status"] != "BENEFIT_APPLIED":
        raise ApiError("ERR_BILLING_STATE_INVALID")
    reversed_amount = order["insurance_benefit_cents"]
    services.append_entry(order["id"], "BENEFIT_REVERSAL", reversed_amount, "Plan benefit reversed")
    order["insurance_benefit_cents"] = 0
    order["benefit_applied_at"] = None
    order["patient_portion_cents"] = order["gross_charge_cents"] - order["lab_writeoff_cents"]
    order["billing_status"] = "BENEFIT_VOIDED"
    touch(order)
    return ok(S.rx_order(order))


@bp.post("/rx-orders/<rid>/settle-patient-portion")
def settle_patient_portion(rid):
    body = json_body()
    if "amount_cents" not in body or body["amount_cents"] is None:
        raise ApiError("ERR_VALIDATION")
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ApiError("ERR_VALIDATION")
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician")
    if order["billing_status"] not in ("BENEFIT_APPLIED", "SELF_PAY_FINAL"):
        raise ApiError("ERR_BILLING_STATE_INVALID")
    balance = order["patient_portion_cents"] - order["patient_paid_cents"]
    if amount <= 0 or amount > balance:
        raise ApiError("ERR_SETTLEMENT_AMOUNT_INVALID")
    order["patient_paid_cents"] += amount
    if order["patient_paid_cents"] == order["patient_portion_cents"]:
        order["billing_status"] = "PATIENT_SETTLED"
    touch(order)
    services.append_entry(order["id"], "PATIENT_PAYMENT", -amount, "Patient payment")
    return ok(S.rx_order(order))


@bp.post("/rx-orders/<rid>/dispense")
def dispense(rid):
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician")
    if order["fulfillment_status"] != "LAB_COMPLETE":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if order["patient_portion_cents"] - order["patient_paid_cents"] != 0:
        raise ApiError("ERR_BALANCE_OUTSTANDING")
    order["fulfillment_status"] = "DISPENSED"
    touch(order)
    return ok(S.rx_order(order))


@bp.post("/rx-orders/<rid>/cancel")
def cancel_order(rid):
    order = services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician")
    if order["fulfillment_status"] in ("DISPENSED", "CANCELLED"):
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if order["billing_status"] != "PROVISIONAL_QUOTED":
        raise ApiError("ERR_BILLING_ALREADY_FINALIZED")
    job = services.newest_job(order["id"])
    if job is not None:
        for op in services.job_operations(job["id"]):
            if op["status"] == "RUNNING":
                raise ApiError("ERR_OPERATION_IN_PROGRESS")
    services.cancel_order_effects(order)
    return ok(S.rx_order(order))


@bp.get("/rx-orders/<rid>/frame-layouts")
def list_order_frame_layouts(rid):
    services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    rows = [l for l in sorted_rows(db.frame_layouts, reverse=True) if l["rx_order_id"] == rid]
    status = request.args.get("layout_status")
    if status:
        rows = [r for r in rows if r["layout_status"] == status]
    return listing(rows, S.frame_layout)


@bp.get("/rx-orders/<rid>/settlement-entries")
def list_order_settlement_entries(rid):
    services.get_or_404(db.rx_orders, rid, "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician", "LabManager", "BenefitsAdministrator")
    rows = services.order_entries(rid)
    rows.sort(key=lambda e: (e["effective_at"], e["_seq"]))
    entry_type = request.args.get("entry_type")
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return listing(rows, S.settlement_entry)


# --- FrameLayout -----------------------------------------------------------

@bp.post("/frame-layouts")
def create_frame_layout():
    body = json_body()
    data = validate_body(
        body,
        [
            F("rx_order_id", "string"),
            F("expected_rx_order_version", "int"),
            F("trace_source", "enum", enum=("DIGITAL_TRACER", "MANUAL_CALIPER", "CATALOG")),
            F("a_mm", "number"),
            F("b_mm", "number"),
            F("ed_mm", "number"),
            F("dbl_mm", "number"),
            F("fitting_height_override_mm", "number", required=False, minimum=8.0, maximum=40.0),
        ],
    )
    order = services.get_or_404(db.rx_orders, data["rx_order_id"], "ERR_RX_ORDER_NOT_FOUND")
    require_roles("StoreOptician")

    if order["fulfillment_status"] not in ("DRAFT", "LAYOUT_READY"):
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if data["expected_rx_order_version"] != order["version"]:
        raise ApiError("ERR_STALE_RX_ORDER_VERSION")

    a = calc.D(data["a_mm"])
    b = calc.D(data["b_mm"])
    ed = calc.D(data["ed_mm"])
    dbl = calc.D(data["dbl_mm"])
    if (a < Decimal("40.0") or a > Decimal("70.0")
            or b < Decimal("15.0") or b > Decimal("60.0")
            or dbl < Decimal("10.0") or dbl > Decimal("26.0")
            or ed < Decimal("40.0") or ed > Decimal("85.0")
            or ed < a):
        raise ApiError("ERR_TRACE_DIMENSIONS_OUT_OF_RANGE")

    override = data["fitting_height_override_mm"]
    effective = override if override is not None else order["fitting_height_mm"]
    design = services.order_design(order)
    if calc.D(effective) < calc.D(design["min_fitting_height_mm"]):
        raise ApiError("ERR_FITTING_HEIGHT_BELOW_DESIGN_MINIMUM")

    geometry = calc.frame_layout_geometry(
        data["a_mm"], data["b_mm"], data["ed_mm"], data["dbl_mm"], effective,
        order["monocular_pd_od_mm"], order["monocular_pd_os_mm"], design["design_type"],
    )

    for earlier in sorted_rows(db.frame_layouts):
        if earlier["rx_order_id"] == order["id"] and earlier["layout_status"] != "SUPERSEDED":
            earlier["layout_status"] = "SUPERSEDED"
            touch(earlier)

    row = stamp_common(
        {
            "rx_order_id": order["id"],
            "trace_source": data["trace_source"],
            "a_mm": data["a_mm"],
            "b_mm": data["b_mm"],
            "ed_mm": data["ed_mm"],
            "dbl_mm": data["dbl_mm"],
            "fitting_height_override_mm": override,
            "effective_fitting_height_mm": effective,
        }
    )
    row.update(geometry)
    db.frame_layouts[row["id"]] = row

    order["fulfillment_status"] = "LAYOUT_READY"
    touch(order)
    return created(S.frame_layout(row))


@bp.get("/frame-layouts/<rid>")
def get_frame_layout(rid):
    row = services.get_or_404(db.frame_layouts, rid, "ERR_FRAME_LAYOUT_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    return ok(S.frame_layout(row))
