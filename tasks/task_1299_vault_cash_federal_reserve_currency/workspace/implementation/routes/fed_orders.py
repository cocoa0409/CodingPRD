"""FedOrder + DenominationLine endpoints."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from db import DB, new_id, clock_dt, clock_date_str, clock_iso_ms
from errors import ApiError
from middleware import (
    auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope,
)
from response import ok, ok_list
from services import (
    stamp_new, touch, public, append_ledger, recompute_order_totals,
    effective_basis, site_mutation, DENOMINATIONS, STRAP_NOTES,
)
from util import (
    body, required, as_int, as_str, as_enum, as_ymd, parse_ymd, pagination_args,
    created_ts_key,
)

bp = Blueprint("fed_orders", __name__)

DIRECTIONS = {"ORDER", "DEPOSIT"}


def _get_order_or_404(order_id):
    order = DB["fed_orders"].get(order_id)
    if order is None:
        raise ApiError("ERR_FED_ORDER_NOT_FOUND", 404, "Fed order not found")
    return order


def _get_site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/fed-orders")
def create_order():
    principal = auth(["FedCoordinator"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    _get_site_or_404(site_id)  # body FK existence
    require_site_scope(principal, site_id)
    direction = as_enum(required(data, "direction"), "direction", DIRECTIONS)
    business_date = as_ymd(required(data, "business_date"), "business_date")

    order = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "direction": direction,
        "business_date": business_date,
        "face_total_cents": 0,
        "fee_total_cents": 0,
        "grand_total_cents": 0,
        "advice_count": 0,
        "settled_basis_cents": None,
        "status": "DRAFT",
    })
    DB["fed_orders"][order["id"]] = order
    DB["denomination_lines"][order["id"]] = []
    return ok(public(order), status=201)


@bp.get("/vault-cash/fed-orders")
def list_orders():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    direction = request.args.get("direction")
    rows = list(DB["fed_orders"].values())
    if site_id is not None:
        rows = [o for o in rows if o["site_id"] == site_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    if direction is not None:
        rows = [o for o in rows if o["direction"] == direction]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [o for o in rows if o["site_id"] == principal.home_site_id]
    rows.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(rows)
    return ok_list([public(o) for o in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/fed-orders/<orderId>")
def get_order(orderId):
    principal = auth(ALL_ROLES)
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    return ok(public(order))


@bp.post("/vault-cash/fed-orders/<orderId>/lines")
def add_line(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    data = body()
    denom = as_int(required(data, "denomination_cents"), "denomination_cents")
    strap_count = as_int(required(data, "strap_count"), "strap_count")
    expected = as_int(
        required(data, "expected_fed_order_version"), "expected_fed_order_version"
    )
    # OCC check fires before state/business checks: the write mutates the order
    # and a stale expected version reflects an order the client never observed.
    if expected != order["version"]:
        raise ApiError(
            "ERR_STALE_FED_ORDER_VERSION",
            412,
            "expected_fed_order_version does not match current order version",
        )
    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE", 409, "Lines may only be added in DRAFT"
        )
    if denom not in DENOMINATIONS:
        raise ApiError(
            "ERR_INVALID_DENOMINATION_MIX", 422, "Invalid denomination_cents"
        )
    if strap_count < 1:
        raise ApiError(
            "ERR_INVALID_DENOMINATION_MIX", 422, "strap_count must be >= 1"
        )
    if order["direction"] == "ORDER":
        if denom <= 2000 and strap_count % 10 != 0:
            raise ApiError(
                "ERR_INVALID_DENOMINATION_MIX",
                422,
                "ORDER denominations <= 2000 require strap_count multiple of 10",
            )
        if denom >= 5000 and strap_count % 5 != 0:
            raise ApiError(
                "ERR_INVALID_DENOMINATION_MIX",
                422,
                "ORDER denominations >= 5000 require strap_count multiple of 5",
            )
    line = {
        "id": new_id(),
        "fed_order_id": order["id"],
        "denomination_cents": denom,
        "strap_count": strap_count,
        "line_cents": denom * STRAP_NOTES * strap_count,
        "fee_cents": 0,
        "created_at": clock_iso_ms(),
        "_seq": created_ts_key(),
    }
    DB["denomination_lines"][order["id"]].append(line)
    recompute_order_totals(order)
    # Stamp the per-line fee produced by the pinned round-per-line-then-sum rule.
    _refresh_line_fees(order)
    touch(order)
    return ok(public(line), status=201)


def _refresh_line_fees(order):
    from decimal import Decimal
    from services import FEE_NUM, FEE_DEN
    from util import round_half_up_cents

    for line in DB["denomination_lines"].get(order["id"], []):
        line["fee_cents"] = round_half_up_cents(
            Decimal(line["line_cents"]) * FEE_NUM / FEE_DEN
        )


@bp.get("/vault-cash/fed-orders/<orderId>/lines")
def list_lines(orderId):
    principal = auth(ALL_ROLES)
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    limit, offset = pagination_args()
    rows = list(DB["denomination_lines"].get(order["id"], []))
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    total = len(rows)
    return ok_list([public(l) for l in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/vault-cash/fed-orders/<orderId>/submit")
def submit_order(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    site = _get_site_or_404(order["site_id"])

    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE", 409, "Order must be DRAFT to submit"
        )
    if not DB["denomination_lines"].get(order["id"]):
        raise ApiError(
            "ERR_ORDER_HAS_NO_LINES", 422, "Order has no denomination lines"
        )
    # Cutoff: clock must be earlier than (business_date - 1 day)T18:00:00Z.
    cutoff = datetime.combine(
        parse_ymd(order["business_date"]) - timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(hours=18)
    if not clock_dt() < cutoff:
        raise ApiError(
            "ERR_ORDER_CUTOFF_PASSED", 422, "Submission cutoff has passed"
        )

    if order["direction"] == "ORDER":
        # Insurance headroom (candidate excluded from committed exposure). This
        # guard precedes the FROZEN cross-entity guard so that a site frozen by
        # an exhausted headroom still reports the precise headroom error.
        committed = (
            site["on_hand_total_cents"]
            + site.get("in_transit_inbound_cents", 0)
            + site.get("pending_inbound_order_cents", 0)
        )
        headroom = site["insurance_coverage_cents"] - committed
        if order["face_total_cents"] > headroom:
            raise ApiError(
                "ERR_INSURANCE_HEADROOM_EXCEEDED",
                402,
                "Order face exceeds insurance headroom",
            )
    else:  # DEPOSIT draws UNFIT first, then FIT.
        available = site["on_hand_unfit_cents"] + site["on_hand_fit_cents"]
        if order["face_total_cents"] > available:
            raise ApiError(
                "ERR_INSUFFICIENT_CASH_FOR_DEPOSIT",
                422,
                "Deposit face exceeds site fit + unfit on hand",
            )
    # Cross-entity guard: a FROZEN site blocks submission (e.g. born at the vault
    # limit, or frozen by overdue SEIZED cases).
    if site["posture"] == "FROZEN":
        raise ApiError("ERR_VAULT_FROZEN", 409, "Site posture is FROZEN")
    if order["direction"] == "ORDER":
        if site["on_hand_total_cents"] + order["face_total_cents"] > site["vault_limit_cents"]:
            raise ApiError(
                "ERR_VAULT_LIMIT_EXCEEDED",
                402,
                "Order would push on-hand total over the vault limit",
            )

    order["status"] = "SUBMITTED"
    touch(order)
    if order["direction"] == "ORDER":
        site["pending_inbound_order_cents"] = (
            site.get("pending_inbound_order_cents", 0) + order["face_total_cents"]
        )
        site_mutation(site)
    return ok(public(order))


@bp.post("/vault-cash/fed-orders/<orderId>/recall")
def recall_order(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    if order["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE", 409, "Only SUBMITTED orders may be recalled"
        )
    order["status"] = "DRAFT"
    touch(order)
    if order["direction"] == "ORDER":
        site = _get_site_or_404(order["site_id"])
        site["pending_inbound_order_cents"] = (
            site.get("pending_inbound_order_cents", 0) - order["face_total_cents"]
        )
        site_mutation(site)
    return ok(public(order))


@bp.post("/vault-cash/fed-orders/<orderId>/acknowledge")
def acknowledge_order(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    if order["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE",
            409,
            "Only SUBMITTED orders may be acknowledged",
        )
    order["status"] = "ACKNOWLEDGED"
    touch(order)
    return ok(public(order))


@bp.post("/vault-cash/fed-orders/<orderId>/cancel")
def cancel_order(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE",
            409,
            "Only DRAFT or SUBMITTED orders may be cancelled",
        )
    was_submitted_order = order["status"] == "SUBMITTED" and order["direction"] == "ORDER"
    order["status"] = "CANCELLED"
    touch(order)
    if was_submitted_order:
        site = _get_site_or_404(order["site_id"])
        site["pending_inbound_order_cents"] = (
            site.get("pending_inbound_order_cents", 0) - order["face_total_cents"]
        )
        site_mutation(site)
    return ok(public(order))


@bp.post("/vault-cash/fed-orders/<orderId>/record-fed-advice")
def record_advice(orderId):
    principal = auth(["FedCoordinator"])
    order = _get_order_or_404(orderId)
    require_site_scope(principal, order["site_id"])
    data = body()
    counted = as_int(required(data, "counted_total_cents"), "counted_total_cents")
    if order["status"] not in ("RECEIVED", "DISPUTED"):
        raise ApiError(
            "ERR_FED_ORDER_INVALID_STATE",
            409,
            "Advices may only be recorded from RECEIVED or DISPUTED",
        )
    order["advice_count"] = order.get("advice_count", 0) + 1
    basis = effective_basis(order)
    delta = counted - basis
    order["settled_basis_cents"] = counted
    # RECONCILED iff the advice matches face; any mismatch keeps/puts DISPUTED.
    order["status"] = "RECONCILED" if counted == order["face_total_cents"] else "DISPUTED"
    touch(order)
    if delta != 0:
        # CASCADE: ADJUSTMENT (FIT) on clock date -> site recompute -> recon refresh.
        append_ledger(
            order["site_id"],
            clock_date_str(),
            "ADJUSTMENT",
            delta,
            "FIT",
            note=f"Fed advice variance on order {order['id']}",
        )
    return ok(public(order))
