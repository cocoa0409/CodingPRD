"""Orders, lines, quoting, confirmation, production and money (PRD 3.5, 3.6, 3.9)."""

from flask import Blueprint, g, request

import calc
from auth import (
    check_facility_filter,
    check_facility_scope,
    get_facility,
    get_order,
    get_order_line,
    get_revision,
    require,
)
from constants import (
    BILLING_STATUSES,
    CONFIG_STATUSES,
    FINISH_CODES,
    FULFILLMENT_STATUSES,
    LINE_STATUSES,
)
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, mutate_forced, new_entity, store
from validation import (
    field_datetime,
    field_enum_array,
    field_id,
    field_int,
    field_str,
    get_body,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("orders", __name__)


def _facility_of_order(order):
    return store.facilities[order["facility_id"]]


def _require_facility_active(facility):
    if facility["status"] != "ACTIVE":
        raise ApiError(
            "ERR_FACILITY_SUSPENDED", "The facility account is suspended."
        )


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------
@bp.post("/orders")
@require("OrderPlanner", "FacilityManager")
def create_order():
    body = get_body()

    # rung 4 — facility scope on the body-borne target
    target = body.get("facility_id")
    if isinstance(target, str):
        check_facility_scope(target)

    facility_id = field_id(body, "facility_id")
    window_start, start_dt = field_datetime(body, "requested_install_window_start")
    window_end, end_dt = field_datetime(body, "requested_install_window_end")

    # rung 8 — window sanity
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "requested_install_window_end must be strictly after the start.",
        )

    # rung 9
    facility = get_facility(facility_id)

    # rung 28
    _require_facility_active(facility)

    order = new_entity(
        {
            "facility_id": facility["id"],
            "config_status": "CONFIGURING",
            "fulfillment_status": "PENDING",
            "billing_status": "UNQUOTED",
            "requested_install_window_start": window_start,
            "requested_install_window_end": window_end,
            "line_subtotal_cents": 0,
            "install_amount_cents": 0,
            "volume_discount_cents": 0,
            "freight_cents": 0,
            "punch_list_credit_cents": 0,
            "chargeable_weight_kg": 0,
            "quoted_total_cents": 0,
            "final_total_cents": None,
            "price_variant_applied": "NONE",
            "tradein_credit_applied_cents": 0,
            "amount_due_cents": None,
            "quoted_at": None,
        }
    )
    store.orders[order["id"]] = order
    return created(order)


@bp.get("/orders")
@require("OrderPlanner", "FacilityManager", "ServiceOpsAdmin")
def list_orders():
    limit, offset = paging()
    check_facility_filter()
    facility_id = query_str("facility_id")
    config_status = query_enum("config_status", CONFIG_STATUSES)
    fulfillment_status = query_enum("fulfillment_status", FULFILLMENT_STATUSES)
    billing_status = query_enum("billing_status", BILLING_STATUSES)

    rows = list(store.orders.values())
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if config_status is not None:
        rows = [r for r in rows if r["config_status"] == config_status]
    if fulfillment_status is not None:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/orders/<order_id>")
@require("OrderPlanner", "FacilityManager", "ServiceOpsAdmin")
def read_order(order_id):
    order = get_order(order_id)
    check_facility_scope(order["facility_id"])
    return ok(order)


# ---------------------------------------------------------------------------
# order lines
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/lines")
@require("OrderPlanner", "FacilityManager")
def create_order_line(order_id):
    order = get_order(order_id)
    check_facility_scope(order["facility_id"])

    body = get_body()
    model_revision_id = field_id(body, "model_revision_id")
    quantity = field_int(body, "quantity", minimum=1, maximum=500)
    finish_codes = field_enum_array(
        body, "finish_codes", FINISH_CODES, required=True, non_empty=False
    )
    layout_zone_label = field_str(body, "layout_zone_label", min_len=1, max_len=40)

    # rung 9
    revision = get_revision(model_revision_id)

    # rung 13
    if revision["status"] != "RELEASED":
        raise ApiError(
            "ERR_REVISION_NOT_RELEASED",
            "Only a RELEASED revision may be configured on an order line.",
        )

    # rung 21
    model = calc.model_of_revision(revision)
    for code in finish_codes:
        if code not in model["allowed_finish_codes"]:
            raise ApiError(
                "ERR_FINISH_NOT_ALLOWED",
                "Finish code %s is not available on this model." % code,
            )

    # rung 28
    _require_facility_active(_facility_of_order(order))

    line = new_entity(
        {
            "order_id": order["id"],
            "model_revision_id": revision["id"],
            "quantity": quantity,
            "finish_codes": finish_codes,
            "layout_zone_label": layout_zone_label,
            "unit_price_cents": 0,
            "extended_price_cents": 0,
            "status": "ACTIVE",
            "assets_minted_count": 0,
        }
    )
    store.order_lines[line["id"]] = line
    calc.price_line(line)
    calc.recompute_order_configuration(order)
    calc.invalidate_quote(order)
    return created(line)


@bp.get("/order-lines")
@require("OrderPlanner", "FacilityManager", "ServiceOpsAdmin")
def list_order_lines():
    limit, offset = paging()
    order_id = query_str("order_id")
    model_revision_id = query_str("model_revision_id")
    status = query_enum("status", LINE_STATUSES)

    rows = list(store.order_lines.values())
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if model_revision_id is not None:
        rows = [r for r in rows if r["model_revision_id"] == model_revision_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/order-lines/<line_id>")
@require("OrderPlanner", "FacilityManager", "ServiceOpsAdmin")
def read_order_line(line_id):
    line = get_order_line(line_id)
    order = store.orders[line["order_id"]]
    check_facility_scope(order["facility_id"])
    return ok(line)


@bp.post("/order-lines/<line_id>/void")
@require("OrderPlanner", "FacilityManager")
def void_order_line(line_id):
    line = get_order_line(line_id)
    order = store.orders[line["order_id"]]
    check_facility_scope(order["facility_id"])
    get_body()

    if line["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE line may be voided."
        )

    with mutate(line):
        line["status"] = "VOIDED"
    calc.recompute_order_configuration(order)
    calc.invalidate_quote(order)
    return ok(line)


# ---------------------------------------------------------------------------
# quoting, confirmation, production
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/quote")
@require("OrderPlanner")
def quote_order(order_id):
    order = get_order(order_id)
    body = get_body()
    expected_version = field_int(body, "expected_order_version", minimum=0)

    # rung 10
    if expected_version != order["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", "The order has been modified since it was read."
        )

    # rung 11
    if order["config_status"] != "CONFIGURING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a CONFIGURING order may be quoted.",
        )
    if order["billing_status"] not in ("UNQUOTED", "QUOTED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The order's billing status does not allow quoting.",
        )

    facility = _facility_of_order(order)
    # rung 28
    _require_facility_active(facility)
    # rung 29 — the first-quote branch requires a configuration
    if order["billing_status"] == "UNQUOTED" and not calc.has_active_line(order):
        raise ApiError(
            "ERR_ORDER_HAS_NO_LINES", "The order has no ACTIVE line to price."
        )

    with mutate_forced(order):
        calc.recompute_order_configuration(order)
        calc.apply_provisional_pricing(order)
    return ok(order)


@bp.post("/orders/<order_id>/confirm")
@require("OrderPlanner", "FacilityManager")
def confirm_order(order_id):
    order = get_order(order_id)
    check_facility_scope(order["facility_id"])
    get_body()

    # rung 11
    if order["config_status"] != "CONFIGURING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a CONFIGURING order may be confirmed.",
        )
    # rung 12
    if order["billing_status"] != "QUOTED":
        raise ApiError(
            "ERR_ORDER_NOT_QUOTED", "The order must carry a current quote."
        )

    facility = _facility_of_order(order)
    # rung 28
    _require_facility_active(facility)
    # rung 29
    if not calc.has_active_line(order):
        raise ApiError("ERR_ORDER_HAS_NO_LINES", "The order has no ACTIVE line.")
    # rung 36
    if (
        facility["open_order_exposure_cents"] + order["quoted_total_cents"]
        > facility["credit_limit_cents"]
    ):
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "The facility's credit limit does not cover this order.",
        )

    with mutate(order):
        order["config_status"] = "CONFIRMED"
        order["fulfillment_status"] = "IN_PRODUCTION"
    calc.recompute_facility(facility)
    return ok(order)


@bp.post("/orders/<order_id>/production/complete")
@require("OrderPlanner")
def complete_production(order_id):
    order = get_order(order_id)
    get_body()

    if order["fulfillment_status"] != "IN_PRODUCTION":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an IN_PRODUCTION order may report production complete.",
        )

    with mutate(order):
        order["fulfillment_status"] = "STAGED"

    for line in calc.order_lines(order["id"], active_only=True):
        revision = store.model_revisions[line["model_revision_id"]]
        model = calc.model_of_revision(revision)
        minted = 0
        for _ in range(line["quantity"]):
            sequence_no = calc.next_sequence_no(revision["id"])
            asset = new_entity(
                {
                    "serial_number": "%s-%05d" % (revision["revision_code"], sequence_no),
                    "sequence_no": sequence_no,
                    "model_revision_id": revision["id"],
                    "facility_id": order["facility_id"],
                    "order_line_id": line["id"],
                    "installed_firmware_release_id": None,
                    "status": "BUILT",
                    "connectivity_support_status": (
                        "SUPPORTED" if model["connected"] else "NOT_APPLICABLE"
                    ),
                    "warranty_starts_at": None,
                    "warranty_expires_at": None,
                    "firmware_support_expires_at": None,
                    "support_gap_days": 0,
                    "annual_usage_hours": 0,
                    "service_history_count": 0,
                    "accrued_service_labor_hours": 0,
                    "declared_condition_grade": None,
                    "refurb_grade": None,
                    "trade_in_valuation_cents": None,
                }
            )
            store.serialized_assets[asset["id"]] = asset
            minted += 1
        with mutate(line):
            line["assets_minted_count"] = minted

    return ok(order)


@bp.get("/orders/<order_id>/price-breakdown")
@require("OrderPlanner", "FacilityManager", "ServiceOpsAdmin")
def order_price_breakdown(order_id):
    order = get_order(order_id)
    check_facility_scope(order["facility_id"])
    return ok(calc.price_breakdown(order))


@bp.post("/orders/<order_id>/apply-tradein-credit")
@require("OrderPlanner")
def apply_tradein_credit(order_id):
    order = get_order(order_id)
    body = get_body()
    amount_cents = field_int(body, "amount_cents")
    expected_version = field_int(body, "expected_facility_version", minimum=0)

    facility = _facility_of_order(order)

    # rung 10
    if expected_version != facility["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", "The facility has been modified since it was read."
        )

    # rung 37
    if order["final_total_cents"] is not None:
        outstanding = order["final_total_cents"] - order["tradein_credit_applied_cents"]
    else:
        outstanding = order["quoted_total_cents"] - order["tradein_credit_applied_cents"]
    if (
        amount_cents < 1
        or amount_cents > facility["tradein_credit_balance_cents"]
        or amount_cents > outstanding
    ):
        raise ApiError(
            "ERR_INSUFFICIENT_TRADEIN_CREDIT",
            "The requested trade-in credit is not available on this order.",
        )

    with mutate(order):
        order["tradein_credit_applied_cents"] += amount_cents
        if order["final_total_cents"] is not None:
            order["amount_due_cents"] = (
                order["final_total_cents"] - order["tradein_credit_applied_cents"]
            )
    with mutate_forced(facility):
        calc.recompute_facility(facility)
    return ok(order)


@bp.post("/orders/<order_id>/settle")
@require("OrderPlanner")
def settle_order(order_id):
    order = get_order(order_id)
    body = get_body()
    field_str(body, "payment_reference", min_len=1)

    if order["billing_status"] != "INVOICED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an INVOICED order may be settled."
        )

    with mutate(order):
        order["billing_status"] = "SETTLED"
    calc.recompute_facility(_facility_of_order(order))
    return ok(order)
