"""Orders: creation with the domain gate ladder, submit/deliver/cancel
(PRD section 3.3)."""

from datetime import timedelta

from flask import Blueprint, request

import envelope
from auth import auth_and_roles, pm_owns_or_403
from calc import (
    build_order,
    deliver_cascade,
    lazy_expire_promotion,
    practice_credit_available,
)
from db import STORES, now
from errors import ApiError
from util import (
    body,
    fk_exists,
    fmt_ts,
    get_or_404,
    paginate,
    pub,
    sorted_default,
    touch,
    v_list,
    v_str,
)

bp = Blueprint("orders", __name__)

ORDER_ROLES = ["DistributionAdmin", "SalesRep", "PracticeManager"]
ORDER_WRITE_ROLES = ["PracticeManager", "SalesRep"]
CLIENT_KINDS = {"MANUAL", "STARTUP", "BUNDLE"}
STARTUP_WINDOW_DAYS = 90


def _validate_lines_shape(data):
    lines = v_list(data, "lines")
    cleaned = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Each line must be an object")
        product_id = entry.get("product_id")
        if not isinstance(product_id, str) or product_id == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, "Each line requires a product_id")
        quantity = entry.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Line quantity must be an integer > 0"
            )
        cleaned.append({"product_id": product_id, "quantity": quantity})
    return cleaned


def _order_domain_gates(practice, kind, promo, lines):
    """Domain gates for order creation, in the fixed order of PRD section 3.3."""
    t = now()
    products = [STORES["products"][l["product_id"]] for l in lines]

    # 1. Regulated license: any REGULATED line requires a non-null license
    #    expiry not earlier than the logical now.
    if any(p["kind"] == "REGULATED" for p in products):
        license_dt = practice["_license_dt"]
        if license_dt is None or license_dt < t:
            raise ApiError(
                "ERR_REGULATED_LICENSE_MISSING",
                422,
                "Practice lacks a valid regulated-items handling license",
            )

    # 2. Sterilization certification.
    if any(p["sterilization_cycle_required"] for p in products):
        if not practice["sterilization_compliant"]:
            raise ApiError(
                "ERR_STERILIZATION_NOT_CERTIFIED",
                422,
                "Practice is not certified for sterilization-cycle products",
            )

    # 3. Regulated quantity cap.
    for line, product in zip(lines, products):
        cap = product["max_qty_per_order"]
        if product["kind"] == "REGULATED" and cap is not None and line["quantity"] > cap:
            raise ApiError(
                "ERR_REGULATED_QTY_LIMIT",
                422,
                "REGULATED line quantity exceeds the product's per-order cap",
            )

    # 4. Equipment orderability: EQUIPMENT lines only on STARTUP orders.
    if kind != "STARTUP" and any(p["kind"] == "EQUIPMENT" for p in products):
        raise ApiError(
            "ERR_EQUIPMENT_NOT_ORDERABLE",
            422,
            "EQUIPMENT lines are permitted only on STARTUP orders",
        )

    # 5. Startup window: within ninety days of practice creation.
    if kind == "STARTUP":
        if t > practice["_created_dt"] + timedelta(days=STARTUP_WINDOW_DAYS):
            raise ApiError(
                "ERR_STARTUP_WINDOW_EXPIRED",
                422,
                "STARTUP orders are accepted only within 90 days of practice creation",
            )
        # 6. Startup package limit: at most one non-CANCELLED STARTUP order.
        for other in STORES["orders"].values():
            if (
                other["practice_id"] == practice["id"]
                and other["kind"] == "STARTUP"
                and other["status"] != "CANCELLED"
            ):
                raise ApiError(
                    "ERR_STARTUP_PACKAGE_LIMIT",
                    409,
                    "Practice already has a non-CANCELLED STARTUP order",
                )

    # 7./8. Promotion activity, then applicability.
    if promo is not None:
        lazy_expire_promotion(promo)
        if promo["status"] != "ACTIVE" or not (
            promo["_start_dt"] <= t <= promo["_end_dt"]
        ):
            raise ApiError(
                "ERR_PROMOTION_INACTIVE",
                422,
                "Attached promotion is not ACTIVE within its program window",
            )
        if promo["promo_kind"] != "BUNDLE_DISCOUNT":
            raise ApiError(
                "ERR_PROMOTION_NOT_APPLICABLE",
                422,
                "Orders accept only BUNDLE_DISCOUNT promotions",
            )

    # 9. Practice standing.
    if practice["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PRACTICE_SUSPENDED", 409, "SUSPENDED practices may not open new orders"
        )


@bp.post("/orders")
def create_order():
    uid, role = auth_and_roles(ORDER_WRITE_ROLES)
    data = body()

    # Ownership (rung 2) before existence (rung 3).
    if role == "PracticeManager":
        pid = data.get("practice_id")
        if pid is not None:
            pm_owns_or_403(role, uid, pid)

    # Existence (rung 3): practice, promotion, and every line's product.
    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "promotion_id", "promotions")
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for entry in raw_lines:
            if isinstance(entry, dict):
                pid = entry.get("product_id")
                if isinstance(pid, str) and pid != "" and pid not in STORES["products"]:
                    raise ApiError(
                        "ERR_RESOURCE_NOT_FOUND",
                        404,
                        "line product_id does not reference an existing product",
                    )

    # Request shape (rung 4): a client-supplied kind of AUTO is rejected here.
    practice_id = v_str(data, "practice_id")
    kind = data.get("kind")
    if kind not in ("MANUAL", "STARTUP", "BUNDLE"):
        if kind == "AUTO":
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Order kind AUTO is system-created only"
            )
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "kind must be one of MANUAL, STARTUP, BUNDLE"
        )
    lines = _validate_lines_shape(data)

    practice = STORES["practices"][practice_id]
    promo = None
    promotion_id = data.get("promotion_id")
    if promotion_id is not None:
        if not isinstance(promotion_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "promotion_id must be a string")
        promo = STORES["promotions"][promotion_id]

    _order_domain_gates(practice, kind, promo, lines)

    order = build_order(practice, kind, promo, lines)
    return envelope.success(pub(order), "object", 201)


@bp.get("/orders/<rid>")
def get_order(rid):
    uid, role = auth_and_roles(ORDER_ROLES)
    order = get_or_404("orders", rid)
    pm_owns_or_403(role, uid, order["practice_id"])
    return envelope.success(pub(order))


@bp.get("/orders")
def list_orders():
    uid, role = auth_and_roles(ORDER_ROLES)
    records = list(STORES["orders"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    practice_id = request.args.get("practice_id")
    promotion_id = request.args.get("promotion_id")
    kind = request.args.get("kind")
    if practice_id is not None:
        records = [r for r in records if r["practice_id"] == practice_id]
    if promotion_id is not None:
        records = [r for r in records if r["promotion_id"] == promotion_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


@bp.post("/orders/<rid>/submit")
def submit_order(rid):
    uid, role = auth_and_roles(ORDER_WRITE_ROLES)
    order = get_or_404("orders", rid)
    pm_owns_or_403(role, uid, order["practice_id"])

    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT order can be submitted")
    if not order["lines"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Order has no lines")

    # Domain checks in the fixed order of PRD section 3.3.
    if order["kind"] == "BUNDLE" and order["promotion_id"] is not None:
        promo = STORES["promotions"][order["promotion_id"]]
        required = promo.get("required_product_ids") or []
        line_products = {l["product_id"] for l in order["lines"]}
        if not all(r in line_products for r in required):
            raise ApiError(
                "ERR_BUNDLE_INCOMPLETE",
                422,
                "BUNDLE order lacks one or more required bundle products",
            )

    practice = STORES["practices"][order["practice_id"]]
    if practice["status"] != "ACTIVE":
        raise ApiError("ERR_PRACTICE_SUSPENDED", 409, "Practice is SUSPENDED")

    if order["total_cents"] > practice_credit_available(practice):
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            422,
            "Order total exceeds the practice's available credit",
        )

    t = now()
    order["status"] = "SUBMITTED"
    order["submitted_at"] = fmt_ts(t)
    order["_submitted_dt"] = t
    touch(order)
    # Credit reservation: debit the practice's available credit and advance its
    # version.
    practice["credit_available_cents"] -= order["total_cents"]
    touch(practice)
    return envelope.success(pub(order))


@bp.post("/orders/<rid>/deliver")
def deliver_order(rid):
    auth_and_roles(["DistributionAdmin"])
    order = get_or_404("orders", rid)
    if order["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED order can be delivered")
    deliver_cascade(order)
    return envelope.success(pub(order))


@bp.post("/orders/<rid>/cancel")
def cancel_order(rid):
    uid, role = auth_and_roles(ORDER_WRITE_ROLES)
    order = get_or_404("orders", rid)
    pm_owns_or_403(role, uid, order["practice_id"])
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DRAFT or SUBMITTED order can be cancelled"
        )
    was_submitted = order["status"] == "SUBMITTED"
    order["status"] = "CANCELLED"
    touch(order)
    if was_submitted:
        # Compensation: the reservation is restored and the practice version
        # advances.
        practice = STORES["practices"][order["practice_id"]]
        practice["credit_available_cents"] += order["total_cents"]
        touch(practice)
    return envelope.success(pub(order))
