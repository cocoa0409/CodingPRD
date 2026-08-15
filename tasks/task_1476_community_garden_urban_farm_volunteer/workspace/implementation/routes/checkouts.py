"""Tool checkouts: borrow, full/partial return with condition, write-off."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_ownership, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_enum, pagination_args, req_int, req_str, require_field

bp = Blueprint("checkouts", __name__)

FOUR = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader"]
STAFF = ["GardenAdmin", "Coordinator"]
CHECKOUT_TARGETS = {"RETURNED", "CLOSED_LOSS"}


@bp.post("/api/tool-checkouts")
def create_checkout():
    ctx = require_auth()
    require_role(ctx, FOUR)
    data = body()
    # existence (tier 3): tool, volunteer, optional signup
    tool_id = require_field(data, "tool_id")
    tool = db.tools.get(tool_id)
    if tool is None:
        raise err_not_found("tool")
    volunteer_id = require_field(data, "volunteer_id")
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise err_not_found("volunteer")
    signup_id = data.get("signup_id")
    signup = None
    if signup_id is not None:
        signup = db.signups.get(signup_id)
        if signup is None:
            raise err_not_found("signup")
    # ownership (tier 4)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != volunteer_id:
        raise err_ownership()
    # shape (tier 5)
    qty = req_int(data, "qty")
    if qty <= 0:
        raise err_invalid_request("qty must be > 0")
    # participation gates (tier 8)
    if vol["orientation_status"] != "ORIENTED":
        raise err("ERR_ORIENTATION_REQUIRED", "borrower orientation_status is not ORIENTED")
    if vol["waiver_status"] != "SIGNED":
        raise err("ERR_WAIVER_REQUIRED", "borrower waiver_status is not SIGNED")
    if vol["standing"] == "SUSPENDED":
        raise err("ERR_VOLUNTEER_SUSPENDED", "borrower is SUSPENDED")
    # certification gate (tier 9): POWER tools need ACTIVE TOOL_SAFETY
    if tool["category"] == "POWER" and not services.has_active_cert(volunteer_id, "TOOL_SAFETY"):
        raise err("ERR_TOOL_CERT_REQUIRED", "POWER tools require an ACTIVE TOOL_SAFETY certification")
    # referential state (tier 12): tool IN_SERVICE; signup eligibility
    if tool["status"] != "IN_SERVICE":
        raise err_state("TOOL")
    if signup is not None and (signup["volunteer_id"] != volunteer_id
                               or signup["status"] not in {"CONFIRMED", "CHECKED_IN"}):
        raise err("ERR_SIGNUP_NOT_ELIGIBLE",
                  "signup_id must belong to the same volunteer and be CONFIRMED or CHECKED_IN")
    # capacity (tier 14): stock
    if qty > services.tool_view(tool)["available_count"]:
        raise err("ERR_TOOL_INSUFFICIENT_STOCK", "qty exceeds available_count")
    rec = services.create_record({
        "tool_id": tool_id,
        "volunteer_id": volunteer_id,
        "signup_id": signup_id,
        "qty": qty,
        "qty_returned": 0,
        "condition_on_return": None,
        "status": "OPEN",
    })
    db.checkouts[rec["id"]] = rec
    services.bump(tool)
    return ok(services.checkout_view(rec), status=201)


@bp.get("/api/tool-checkouts")
def list_checkouts():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.checkouts.values(),
        {"tool_id": "tool_id", "volunteer_id": "volunteer_id",
         "signup_id": "signup_id", "status": "status"},
        request.args, services.checkout_view,
    )
    total = len(items)
    return ok([services.checkout_view(c) for c in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_checkout(checkout_id):
    co = db.checkouts.get(checkout_id)
    if co is None:
        raise err_not_found("checkout")
    return co


@bp.get("/api/tool-checkouts/<checkoutId>")
def get_checkout(checkoutId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.checkout_view(_get_checkout(checkoutId)))


@bp.post("/api/tool-checkouts/<checkoutId>/transition")
def transition_checkout(checkoutId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    co = _get_checkout(checkoutId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in CHECKOUT_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(CHECKOUT_TARGETS)}")
    # per-transition actors: CLOSED_LOSS is staff-only
    if to_state == "CLOSED_LOSS" and ctx.role not in STAFF:
        raise err_forbidden_role()
    # ownership (tier 4) for self-service returns
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != co["volunteer_id"]:
        raise err_ownership()
    tool = db.tools.get(co["tool_id"])

    if to_state == "RETURNED":
        # shape (tier 5): condition required on every return
        qty_returned = data.get("qty_returned")
        condition = opt_enum(data, "condition_on_return", {"GOOD", "DAMAGED"}, None)
        if condition is None:
            raise err_invalid_request("condition_on_return is required on return transitions")
        # from-state (tier 6)
        if co["status"] not in {"OPEN", "PARTIAL_RETURN"}:
            raise err_state("CHECKOUT")
        remainder = co["qty"] - co["qty_returned"]
        if isinstance(qty_returned, bool) or not isinstance(qty_returned, int) \
                or qty_returned <= 0 or qty_returned > remainder:
            raise err("ERR_QUANTITY_INVALID",
                      "qty_returned must be > 0 and <= the outstanding remainder")
        co["qty_returned"] += qty_returned
        co["condition_on_return"] = condition
        co["status"] = "RETURNED" if qty_returned == remainder else "PARTIAL_RETURN"
        services.bump(co)
        if tool is not None:
            if condition == "DAMAGED":
                tool["in_maintenance_count"] += qty_returned
            services.bump(tool)

    elif to_state == "CLOSED_LOSS":
        if co["status"] not in {"OPEN", "PARTIAL_RETURN"}:
            raise err_state("CHECKOUT")
        outstanding = co["qty"] - co["qty_returned"]
        co["status"] = "CLOSED_LOSS"
        services.bump(co)
        if tool is not None:
            tool["written_off_count"] += outstanding
            services.bump(tool)
        borrower = db.volunteers.get(co["volunteer_id"])
        if borrower is not None and borrower["standing"] == "GOOD":
            borrower["standing"] = "PROBATION"
            services.bump(borrower)

    return ok(services.checkout_view(co))
