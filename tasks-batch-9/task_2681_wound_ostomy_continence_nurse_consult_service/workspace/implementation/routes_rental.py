"""SupportSurface and SupportSurfaceOrder (12 endpoints).

The order row carries two independent state dimensions, fulfillment_status and
billing_status.  /deliver moves only the first, /reconcile only the second;
/approve and /return are the only calls that move both.
"""

import calc
import services
from core import (
    READ_ROLES,
    ROLE_MATERIALS,
    ROLE_WOC_NURSE,
    F,
    apply_filters,
    authorize,
    bad_request,
    bump,
    check_unit_version,
    chrono,
    dt_of,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    store,
)
from flask import Blueprint

bp = Blueprint("rental", __name__)

SURFACE_CLASSES = ("FOAM_OVERLAY", "ALTERNATING_PRESSURE", "LOW_AIR_LOSS",
                   "BARIATRIC_BED")
SURFACE_STATUSES = ("AVAILABLE", "IN_USE", "CLEANING", "RETIRED")
FULFILLMENT_STATUSES = ("REQUESTED", "APPROVED", "DELIVERED", "RETURNED", "DENIED")
BILLING_STATUSES = ("UNBILLED", "ENCUMBERED", "COMMITTED", "RELEASED", "RECONCILED")
LIVE_FULFILLMENT = ("REQUESTED", "APPROVED", "DELIVERED")


# ---------------------------------------------------------------------------
# SupportSurface
# ---------------------------------------------------------------------------
@bp.post("/support-surfaces")
def create_surface():
    authorize(ROLE_MATERIALS)
    body = parse_input([
        F("asset_tag", "string", required=True, min_len=3, max_len=24),
        F("surface_class", "enum", required=True, enum=SURFACE_CLASSES),
        F("daily_rate_cents", "int", required=True, minimum=1, maximum=2000000),
        F("vendor_name", "string", required=True, min_len=1, max_len=120),
    ])
    for existing in rows_of("support_surfaces"):
        if existing.get("asset_tag") == body["asset_tag"]:
            fail("ERR_DUPLICATE_NATURAL_KEY", "asset_tag is already in use.")
    surface = new_row(
        "surface",
        asset_tag=body["asset_tag"],
        surface_class=body["surface_class"],
        daily_rate_cents=body["daily_rate_cents"],
        vendor_name=body["vendor_name"],
        status="AVAILABLE",
        occupied_until=None,
        available_from=None,
    )
    insert("support_surfaces", surface)
    return ok(public(surface), 201)


@bp.get("/support-surfaces")
def list_surfaces():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({"surface_class": SURFACE_CLASSES, "status": SURFACE_STATUSES})
    rows = chrono(apply_filters(rows_of("support_surfaces"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/support-surfaces/<surface_id>")
def get_surface(surface_id):
    authorize(*READ_ROLES)
    return ok(public(must("support_surfaces", surface_id)))


@bp.post("/support-surfaces/<surface_id>/retire")
def retire_surface(surface_id):
    authorize(ROLE_MATERIALS)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    surface = must("support_surfaces", surface_id)
    if surface.get("status") not in ("AVAILABLE", "CLEANING"):
        fail("ERR_RESOURCE_NOT_ACTIVE",
             "Only an AVAILABLE or CLEANING surface may be retired.")
    for order in rows_of("support_surface_orders"):
        if order.get("support_surface_id") != surface_id:
            continue
        if order.get("fulfillment_status") in LIVE_FULFILLMENT:
            fail("ERR_RESOURCE_NOT_ACTIVE",
                 "Surface still carries a live support surface order.")
    surface["status"] = "RETIRED"
    bump(surface)
    return ok(public(surface))


# ---------------------------------------------------------------------------
# SupportSurfaceOrder
# ---------------------------------------------------------------------------
@bp.post("/support-surface-orders")
def create_order():
    authorize(ROLE_MATERIALS, ROLE_WOC_NURSE)
    body = parse_input([
        F("patient_id", "id", required=True),
        F("unit_id", "id", required=True),
        F("support_surface_id", "id", required=True),
        F("rental_start", "datetime", required=True),
        F("rental_end", "datetime", required=True),
        F("authorized_days", "int", required=True, minimum=1, maximum=120),
        F("consult_request_id", "id", nullable=True),
    ])
    if body["rental_end"] <= body["rental_start"]:
        bad_request("rental_end must be strictly after rental_start.")
    patient = must("patients", body["patient_id"])
    unit = must("units", body["unit_id"])
    surface = must("support_surfaces", body["support_surface_id"])
    consult_request_id = body.get("consult_request_id")
    if consult_request_id is not None:
        must("consult_requests", consult_request_id)
    if unit["id"] != patient.get("unit_id"):
        fail("ERR_ENTITY_LINK_MISMATCH", "unit_id must equal the patient's unit_id.")
    if patient.get("status") != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED")
    if surface.get("status") == "RETIRED":
        fail("ERR_RESOURCE_NOT_ACTIVE", "Support surface has been retired.")
    if unit.get("survey_posture") == "FROZEN":
        fail("ERR_UNIT_POSTURE_RESTRICTED",
             "Unit survey posture is FROZEN; no new rental may be raised.")

    days, projected, fee, authorized = calc.price_rental(
        surface["daily_rate_cents"], body["rental_start"], body["rental_end"])
    order = new_row(
        "order",
        patient_id=patient["id"],
        unit_id=unit["id"],
        support_surface_id=surface["id"],
        consult_request_id=consult_request_id,
        rental_start=body["rental_start"],
        rental_end=body["rental_end"],
        authorized_days=body["authorized_days"],
        billable_days=days,
        projected_cost_cents=projected,
        vendor_service_fee_cents=fee,
        authorized_cost_cents=authorized,
        actual_return_at=None,
        actual_cost_cents=None,
        fulfillment_status="REQUESTED",
        billing_status="UNBILLED",
        # PRD §3.8: "when the posture is `RESTRICTED` at creation time the order
        # is created with `requires_director_override` already true."
        requires_director_override=(unit.get("survey_posture") == "RESTRICTED"),
        posture_hold_applied_at=None,
        delivered_at=None,
        denial_reason=None,
    )
    insert("support_surface_orders", order)
    return ok(public(order), 201)


@bp.get("/support-surface-orders")
def list_orders():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "patient_id": None,
        "unit_id": None,
        "support_surface_id": None,
        "consult_request_id": None,
        "fulfillment_status": FULFILLMENT_STATUSES,
        "billing_status": BILLING_STATUSES,
    })
    rows = chrono(apply_filters(rows_of("support_surface_orders"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/support-surface-orders/<order_id>")
def get_order(order_id):
    authorize(*READ_ROLES)
    return ok(public(must("support_surface_orders", order_id)))


@bp.post("/support-surface-orders/<order_id>/approve")
def approve_order(order_id):
    authorize(ROLE_MATERIALS)
    body = parse_input([
        F("expected_unit_version", "int", required=True, minimum=0),
        F("director_override", "bool"),
    ])
    order = must("support_surface_orders", order_id)
    # Rung 12 — fulfillment dimension.
    if order.get("fulfillment_status") != "REQUESTED":
        fail("ERR_ORDER_NOT_PENDING")
    unit = store("units").get(order.get("unit_id"))
    # Rung 20 — optimistic concurrency on the Unit rental ledger.
    check_unit_version(unit, body["expected_unit_version"])
    # Rung 46 — half-open occupation span plus the trailing reclean buffer.
    if not services.surface_interval_free(order["support_surface_id"],
                                          order["rental_start"],
                                          order["rental_end"],
                                          exclude_order_id=order["id"]):
        fail("ERR_SURFACE_UNAVAILABLE")
    # Rung 58 — posture gates.
    if unit.get("survey_posture") == "FROZEN":
        fail("ERR_UNIT_POSTURE_RESTRICTED",
             "Unit survey posture is FROZEN; approval is blocked.")
    if order.get("requires_director_override") and body.get("director_override") is not True:
        fail("ERR_UNIT_POSTURE_RESTRICTED",
             "This order carries a posture hold and needs director_override.")
    # Rung 70 — authorized day ceiling.
    if int(order.get("billable_days") or 0) > int(order.get("authorized_days") or 0):
        fail("ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION")
    # Rung 72 — budget headroom.
    authorized_cost = int(order.get("authorized_cost_cents") or 0)
    if authorized_cost > int(unit.get("rental_available_cents") or 0):
        fail("ERR_RENTAL_BUDGET_EXCEEDED")

    order["fulfillment_status"] = "APPROVED"
    order["billing_status"] = "ENCUMBERED"
    services.encumber(unit, authorized_cost)
    bump(unit)
    surface = store("support_surfaces").get(order["support_surface_id"])
    if surface is not None:
        services.occupy_surface(surface, order["rental_end"])
    bump(order)
    return ok(public(order))


@bp.post("/support-surface-orders/<order_id>/deny")
def deny_order(order_id):
    authorize(ROLE_MATERIALS)
    body = parse_input([
        F("denial_reason", "string", required=True, min_len=1, max_len=2000),
    ])
    order = must("support_surface_orders", order_id)
    if order.get("fulfillment_status") != "REQUESTED":
        fail("ERR_ORDER_NOT_PENDING")
    order["fulfillment_status"] = "DENIED"
    order["denial_reason"] = body["denial_reason"]
    # billing_status stays UNBILLED because nothing was ever encumbered.
    bump(order)
    return ok(public(order))


@bp.post("/support-surface-orders/<order_id>/deliver")
def deliver_order(order_id):
    authorize(ROLE_MATERIALS)
    body = parse_input([F("delivered_at", "datetime", required=True)])
    order = must("support_surface_orders", order_id)
    if order.get("fulfillment_status") != "APPROVED":
        fail("ERR_ORDER_NOT_PENDING")
    if body["delivered_at"] < order.get("rental_start"):
        bad_request("delivered_at must be at or after rental_start.")
    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = body["delivered_at"]
    # billing_status is deliberately untouched: it stays ENCUMBERED.
    bump(order)
    return ok(public(order))


@bp.post("/support-surface-orders/<order_id>/return")
def return_order(order_id):
    authorize(ROLE_MATERIALS)
    body = parse_input([F("actual_return_at", "datetime", required=True)])
    order = must("support_surface_orders", order_id)
    if order.get("fulfillment_status") != "DELIVERED":
        fail("ERR_ORDER_NOT_PENDING")
    if order.get("billing_status") != "ENCUMBERED":
        fail("ERR_ORDER_INVALID_BILLING_STATE")
    if body["actual_return_at"] <= order.get("rental_start"):
        bad_request("actual_return_at must be strictly after rental_start.")

    surface = store("support_surfaces").get(order["support_surface_id"])
    daily_rate = surface["daily_rate_cents"] if surface is not None else 0
    _days, projected, _fee, actual = calc.price_rental(
        daily_rate, order["rental_start"], body["actual_return_at"])
    order["fulfillment_status"] = "RETURNED"
    order["actual_return_at"] = body["actual_return_at"]
    order["actual_cost_cents"] = actual
    order["billing_status"] = "COMMITTED"

    unit = store("units").get(order.get("unit_id"))
    if unit is not None:
        services.commit(unit, int(order.get("authorized_cost_cents") or 0), actual)
        bump(unit)
    if surface is not None:
        services.clean_surface(surface, body["actual_return_at"])
    bump(order)
    return ok(public(order))


@bp.post("/support-surface-orders/<order_id>/reconcile")
def reconcile_order(order_id):
    authorize(ROLE_MATERIALS)
    parse_input([])
    order = must("support_surface_orders", order_id)
    # Rung 13 — billing dimension only.
    if order.get("billing_status") != "COMMITTED":
        fail("ERR_ORDER_INVALID_BILLING_STATE")
    order["billing_status"] = "RECONCILED"
    # No ledger amount moves; rental_committed_cents already carries actual_cost.
    surface = store("support_surfaces").get(order.get("support_surface_id"))
    if surface is not None and surface.get("status") == "CLEANING":
        available_from = surface.get("available_from")
        if available_from is not None and dt_of(now()) >= dt_of(available_from):
            surface["status"] = "AVAILABLE"
            bump(surface)
    bump(order)
    return ok(public(order))
