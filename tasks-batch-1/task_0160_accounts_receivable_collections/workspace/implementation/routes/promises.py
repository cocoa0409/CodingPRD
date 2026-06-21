"""PromiseToPay endpoints (PRD §3.5, §2.9 OCC)."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_VALIDATION, ERR_STALE_VERSION, ERR_PROMISE_WINDOW_OVERLAP,
    ERR_PROMISE_ALREADY_RESOLVED,
)
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, touch, get_json_body, require_str, require_int,
    parse_pagination, paginate,
)
from timeutil import parse_iso_ms

bp = Blueprint("promises", __name__)


@bp.route("/ar/promises", methods=["POST"])
def create_promise():
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = lookup.get_customer(customer_id)
    promised = require_int(body, "promised_amount_cents", minimum=1)
    coverage_start = require_str(body, "coverage_start")
    coverage_end = require_str(body, "coverage_end")
    expected_version = require_int(body, "expected_customer_version")

    start_ms = parse_iso_ms(coverage_start)
    end_ms = parse_iso_ms(coverage_end)
    # field constraint: coverage_end strictly after coverage_start
    if end_ms <= start_ms:
        raise err(ERR_VALIDATION, "coverage_end must be after coverage_start")

    # OCC (priority 7) is checked before the window-overlap business rule
    # (priority 12), per §3.10 ordering.
    if expected_version != customer["version"]:
        raise err(ERR_STALE_VERSION, "expected_customer_version is stale")

    # window overlap with other ACTIVE promises for the same customer
    for p in db.promises.values():
        if p["customer_id"] != customer_id or p["status"] != "ACTIVE":
            continue
        # half-open [start,end); abutting (end==start) allowed; any true overlap collides
        if start_ms < p["coverage_end_ms"] and p["coverage_start_ms"] < end_ms:
            raise err(ERR_PROMISE_WINDOW_OVERLAP, "promise window overlaps an active promise")

    promise = {
        "customer_id": customer_id,
        "promised_amount_cents": promised,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "coverage_start_ms": start_ms,
        "coverage_end_ms": end_ms,
        "status": "ACTIVE",
        "applied_payment_cents": 0,
    }
    stamp_create(promise)
    db.promises[promise["id"]] = promise

    # successful create increments customer.version by 1 and recomputes stage
    touch(customer)
    domain.recompute_customer(customer, recompute_stage=True, already_touched=True)
    return success(domain.serialize_promise(promise), status=201)


@bp.route("/ar/promises/<pid>", methods=["GET"])
def get_promise(pid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    p = lookup.get_promise(pid)
    return success(domain.serialize_promise(p), status=200)


@bp.route("/ar/promises", methods=["GET"])
def list_promises():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.promises.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_promise(p) for p in page], limit, offset, total)


@bp.route("/ar/promises/<pid>/cancel", methods=["POST"])
def cancel(pid):
    _, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT"])
    p = lookup.get_promise(pid)
    # domain-specific state guard (priority 18) — not ERR_INVALID_STATE
    if p["status"] != "ACTIVE":
        raise err(ERR_PROMISE_ALREADY_RESOLVED, "promise is not ACTIVE")
    p["status"] = "CANCELLED"
    touch(p)
    return success(domain.serialize_promise(p), status=200)


@bp.route("/ar/promises/<pid>/evaluate", methods=["POST"])
def evaluate(pid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT"])
    p = lookup.get_promise(pid)
    # domain-specific state guard (priority 18)
    if p["status"] != "ACTIVE":
        raise err(ERR_PROMISE_ALREADY_RESOLVED, "promise is not ACTIVE")

    customer = db.customers.get(p["customer_id"])
    now = db.now_ms()
    # refresh applied_payment_cents from in-window payments before judging
    p["applied_payment_cents"] = domain.compute_promise_applied(p)
    # only acts once the clock is at/past coverage_end
    if now >= p["coverage_end_ms"]:
        if p["applied_payment_cents"] >= p["promised_amount_cents"]:
            p["status"] = "KEPT"
            touch(p)
            if customer is not None:
                # recompute stage toward CURRENT (handled by eval_collection_stage)
                domain.recompute_customer(customer, recompute_stage=True)
        else:
            p["status"] = "BROKEN"
            touch(p)
            if customer is not None:
                # Cascade (PRD §3.5): push credit_status to WATCH if it was GOOD.
                # Recorded as a sticky watch_floor so a later exposure-only
                # recompute keeps the WATCH posture; HOLD still overrides.
                if customer["credit_status"] == "GOOD":
                    customer["watch_floor"] = True
                # advance collection_stage toward COLLECTIONS (eval yields it
                # because an unredeemed BROKEN promise now exists) and refresh
                # credit_status through the unified recompute path.
                domain.recompute_customer(customer, recompute_stage=True)
    # if clock not past coverage_end, evaluate is a no-op (still ACTIVE)
    return success(domain.serialize_promise(p), status=200)
