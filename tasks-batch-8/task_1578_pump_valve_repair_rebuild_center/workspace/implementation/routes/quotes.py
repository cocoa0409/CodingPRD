from datetime import timedelta

from flask import Blueprint, request

from db import CLOCK, DB, _parse_iso, fmt_ts, stamp_new, touch
from errors import (
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_PART_OBSOLETE,
    ERR_POOL_UNIT_UNAVAILABLE,
    ERR_QUOTE_EXPIRED,
    ERR_STALE_VERSION,
    ERR_SUBSTITUTION_NOT_ALLOWED,
    ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE,
    ERR_WINDOW_CAPACITY_EXCEEDED,
    invalid_state,
    not_found,
    raise_err,
    validation,
)
from middleware import (
    as_array,
    as_int,
    as_number,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination
from services.core import (
    QUOTE_VALIDITY_DAYS,
    apply_lazy_expiry,
    cancel_repair_order,
    price_quote,
    recompute_window,
)

bp = Blueprint("quotes", __name__)

QUOTE_TERMINAL = {"APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED", "CANCELLED"}


def get_quote_or_404(qid: str) -> dict:
    quote = DB.quotes.get(qid)
    if quote is None:
        not_found("Quote not found")
    return quote


def validate_quote_part_lines(part_lines):
    for line in part_lines:
        if not isinstance(line, dict):
            validation("part_lines entries must be objects")
        if not isinstance(line.get("part_id"), str):
            validation("part_lines entries require part_id")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or qty <= 0:
            validation("part_lines entries require a positive quantity")
        price = line.get("unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            validation("part_lines entries require a non-negative integer unit_price_cents")
        sub = line.get("substitution_for_part_id")
        if sub is not None and not isinstance(sub, str):
            validation("substitution_for_part_id must be a string")


@bp.route("/quotes", methods=["POST"])
def create_quote():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    repair_order_id = as_string(body, "repair_order_id")
    capacity_window_id = as_string(body, "capacity_window_id")
    labor_hours = as_number(body, "labor_hours")
    labor_rate_cents = as_int(body, "labor_rate_cents")
    part_lines = as_array(body, "part_lines")
    validate_quote_part_lines(part_lines)
    if "expected_repair_order_version" not in body or body.get("expected_repair_order_version") is None:
        validation("expected_repair_order_version is required")
    expected_version = body.get("expected_repair_order_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        validation("expected_repair_order_version must be an integer")

    # Existence: repair order, then capacity window (left to right).
    ro = DB.repair_orders.get(repair_order_id)
    if ro is None:
        not_found("Repair order not found")
    window = DB.capacity_windows.get(capacity_window_id)
    if window is None:
        not_found("Capacity window not found")

    # State validity: RO must be in QUOTE_IN_PROGRESS; OCC check is 412.
    if ro["status"] != "QUOTE_IN_PROGRESS":
        invalid_state("Repair order is not in QUOTE_IN_PROGRESS")
    if expected_version != ro["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_repair_order_version does not match current repair order version",
        )

    customer = DB.customers.get(ro["customer_id"])
    if customer is None:
        not_found("Customer not found")

    # Pricing (raises ERR_WINDOW_FULL if the window posture is FULL).
    pricing = price_quote(ro, window, customer, labor_hours, labor_rate_cents, part_lines)

    # Revision numbering + supersede prior non-terminal quotes.
    prior_quotes = sorted(
        (q for q in DB.quotes.values() if q["repair_order_id"] == ro["id"]),
        key=lambda q: (q["revision"], q["created_at"], q["id"]),
    )
    revision = (prior_quotes[-1]["revision"] + 1) if prior_quotes else 1
    supersedes_quote_id = None
    for q in reversed(prior_quotes):
        if q["status"] in ("DRAFT", "ISSUED", "REVISION_REQUESTED"):
            supersedes_quote_id = q["id"]
            break
    for q in prior_quotes:
        if q["status"] in ("DRAFT", "ISSUED", "REVISION_REQUESTED"):
            q["status"] = "SUPERSEDED"
            touch(q)

    quote = stamp_new(
        {
            "repair_order_id": ro["id"],
            "capacity_window_id": capacity_window_id,
            "revision": revision,
            "status": "DRAFT",
            "labor_hours": labor_hours,
            "labor_rate_cents": labor_rate_cents,
            "part_lines": part_lines,
            "pricing_variant": pricing["pricing_variant"],
            "surge_multiplier_applied": pricing["surge_multiplier_applied"],
            "parts_subtotal_cents": pricing["parts_subtotal_cents"],
            "labor_cents": pricing["labor_cents"],
            "total_cents": pricing["total_cents"],
            "supersedes_quote_id": supersedes_quote_id,
            "issued_at": None,
            "expires_at": None,
        }
    )
    DB.quotes[quote["id"]] = quote
    # Creating a quote revision mutates the repair order.
    touch(ro)
    return success_object(quote, status=201)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    authenticate()
    limit, offset = parse_pagination()
    repair_order_id = request.args.get("repair_order_id")
    capacity_window_id = request.args.get("capacity_window_id")
    status = request.args.get("status")
    supersedes_quote_id = request.args.get("supersedes_quote_id")
    items = sorted(DB.quotes.values(), key=lambda q: (q["created_at"], q["id"]))
    if repair_order_id is not None:
        items = [q for q in items if q["repair_order_id"] == repair_order_id]
    if capacity_window_id is not None:
        items = [q for q in items if q["capacity_window_id"] == capacity_window_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    if supersedes_quote_id is not None:
        items = [q for q in items if q.get("supersedes_quote_id") == supersedes_quote_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    caller = authenticate()
    quote = get_quote_or_404(qid)
    apply_lazy_expiry(quote)
    ro = DB.repair_orders.get(quote["repair_order_id"])
    if ro is not None:
        require_customer_ownership(caller, ro["customer_id"])
    return success_object(quote)


@bp.route("/quotes/<qid>/issue", methods=["POST"])
def issue_quote(qid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["ServiceManager"])
    quote = get_quote_or_404(qid)
    if quote["status"] != "DRAFT":
        invalid_state("Quote is not in DRAFT")
    # Validate every part line against the catalog.
    for line in quote["part_lines"]:
        part = DB.parts.get(line["part_id"])
        sub_id = line.get("substitution_for_part_id")
        if sub_id is not None:
            target = DB.parts.get(sub_id)
            if target is None or target["status"] != "OBSOLETE":
                raise_err(
                    ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE,
                    "substitution_for_part_id references a part that is not OBSOLETE",
                )
            if not target.get("aftermarket_allowed"):
                raise_err(
                    ERR_SUBSTITUTION_NOT_ALLOWED,
                    "Substitution target is OBSOLETE but aftermarket_allowed is false",
                )
        else:
            if part is None:
                not_found("Part not found")
            if part["status"] == "OBSOLETE":
                raise_err(
                    ERR_PART_OBSOLETE,
                    "Part line references an OBSOLETE part without a valid substitution",
                )
    now = CLOCK.now()
    quote["issued_at"] = fmt_ts(now)
    quote["expires_at"] = fmt_ts(now + timedelta(days=QUOTE_VALIDITY_DAYS))
    quote["status"] = "ISSUED"
    touch(quote)
    return success_object(quote)


def _customer_quote_action(qid, action: str):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Customer"])
    quote = get_quote_or_404(qid)
    ro = DB.repair_orders.get(quote["repair_order_id"])
    if ro is None:
        not_found("Repair order not found")
    require_customer_ownership(caller, ro["customer_id"])
    # Lazy expiry applies to any action on an ISSUED quote.
    if quote["status"] == "ISSUED":
        if apply_lazy_expiry(quote):
            raise_err(ERR_QUOTE_EXPIRED, "Quote has expired")
    if quote["status"] != "ISSUED":
        invalid_state(f"Quote is not in ISSUED (cannot {action})")
    return quote, ro


@bp.route("/quotes/<qid>/approve", methods=["POST"])
def approve_quote(qid):
    quote, ro = _customer_quote_action(qid, "approve")

    # Capacity gate: window must absorb the order (equality permitted).
    window = DB.capacity_windows.get(quote["capacity_window_id"])
    if window is None:
        not_found("Capacity window not found")
    if window["bay_hours_reserved"] + ro["estimated_bay_hours"] > window["bay_hours_capacity"]:
        raise_err(
            ERR_WINDOW_CAPACITY_EXCEEDED,
            "Approval would push bay_hours_reserved above bay_hours_capacity",
        )

    # Pool gate: exchange-requested orders need a RESERVED unit.
    if ro["exchange_requested"]:
        has_reserved = any(
            u["pool_status"] == "RESERVED" and u.get("reserved_for_ro_id") == ro["id"]
            for u in DB.pool_units.values()
        )
        if not has_reserved:
            raise_err(
                ERR_POOL_UNIT_UNAVAILABLE,
                "No RESERVED pool unit is linked to this exchange-requested repair order",
            )

    # Fiscal gate last: total within credit limit (equality allowed).
    customer = DB.customers.get(ro["customer_id"])
    if customer is None:
        not_found("Customer not found")
    if quote["total_cents"] > customer["credit_limit_cents"]:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "Quote total exceeds the customer credit limit")

    quote["status"] = "APPROVED"
    touch(quote)

    # Cascade: RO QUOTE_IN_PROGRESS -> AUTHORIZED; copy window; reserve hours.
    if ro["status"] == "QUOTE_IN_PROGRESS":
        ro["status"] = "AUTHORIZED"
    ro["capacity_window_id"] = quote["capacity_window_id"]
    window["bay_hours_reserved"] += ro["estimated_bay_hours"]
    recompute_window(window)
    touch(ro)
    return success_object(quote)


@bp.route("/quotes/<qid>/request-revision", methods=["POST"])
def request_revision(qid):
    quote, ro = _customer_quote_action(qid, "request-revision")
    quote["status"] = "REVISION_REQUESTED"
    touch(quote)
    return success_object(quote)


@bp.route("/quotes/<qid>/decline", methods=["POST"])
def decline_quote(qid):
    quote, ro = _customer_quote_action(qid, "decline")
    quote["status"] = "DECLINED"
    touch(quote)
    # Cascade: RO QUOTE_IN_PROGRESS -> CANCELLED with cancellation side effects.
    if ro["status"] not in ("CLOSED", "CANCELLED"):
        cancel_repair_order(ro)
    return success_object(quote)
