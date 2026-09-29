"""Substitute-request decisioning and withdrawal."""

from db import db, touch
from errors import ApiError
from flask import Blueprint
from middleware import authenticate, check_account_scope
from response import ok, ok_list
from services import calc, flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("substitutes", __name__)

ALL_ROLES = ("PlatformAdmin", "WarrantyAdmin", "PricingAdmin", "CreditManager",
             "BranchCounterRep", "Servicer")
DECIDERS = ("WarrantyAdmin", "PlatformAdmin")
WITHDRAWERS = ("Servicer", "PlatformAdmin")
DECISIONS = {"APPROVE", "REJECT"}


def _request_or_404(request_id):
    return flows.find(db.substitute_requests, request_id,
                      "ERR_SUBSTITUTE_REQUEST_NOT_FOUND")


def _line_and_order(request):
    line = db.order_lines.get(request["order_line_id"])
    order = db.part_orders.get(line["part_order_id"]) if line else None
    return line, order


def _require_pending(request):
    """Rule 17."""
    if request["request_status"] != "PENDING":
        raise ApiError("ERR_SUBSTITUTE_ALREADY_DECIDED",
                       "This substitute request is no longer PENDING")


@bp.post("/substitute-requests/<request_id>/decision")
def decide_substitute(request_id):
    user_id, _role = authenticate(DECIDERS)
    body = parse_body([
        ("decision", "enum", True, DECISIONS),
        ("substitute_part_id", "str", False),
        ("decision_note", "str", False),
    ])
    request = _request_or_404(request_id)
    substitute = None
    if "substitute_part_id" in body:
        substitute = flows.part_or_404(body["substitute_part_id"])
    _require_pending(request)

    line, order = _line_and_order(request)
    account = db.servicer_accounts.get(order["servicer_account_id"]) if order \
        else None
    obsolete = db.parts.get(request["obsolete_part_id"])
    approving = body["decision"] == "APPROVE"

    if approving and substitute is not None and account is not None:
        # rule 24 reads the part that is about to become the line's resolved part
        flows.check_oem_authorization(account, substitute)

    if approving:
        if substitute is None \
                or obsolete is None \
                or substitute["id"] == obsolete["id"] \
                or substitute["lifecycle_status"] != "ACTIVE" \
                or substitute["oem_code"] != obsolete["oem_code"]:
            raise ApiError("ERR_SUBSTITUTE_PART_INVALID",
                           "The offered substitute is not an acceptable "
                           "replacement for the obsolete part")
        variance = calc.price_variance_pct(obsolete["list_price_cents"],
                                          substitute["list_price_cents"])
        if abs(variance) > calc.SUBSTITUTE_VARIANCE_CAP_PCT:
            raise ApiError("ERR_SUBSTITUTE_PRICE_VARIANCE",
                           "Substitute list price varies by %s, beyond the "
                           "permitted cap" % variance)
    else:
        if substitute is not None:
            raise ApiError("ERR_SUBSTITUTE_PART_INVALID",
                           "A rejecting decision must not name a substitute part")

    request["decided_by_user_id"] = user_id
    if approving:
        request["request_status"] = "APPROVED"
        request["proposed_substitute_part_id"] = substitute["id"]
        request["price_variance_pct"] = variance
        if line is not None:
            line["resolved_part_id"] = substitute["id"]
            tier = db.pricing_tiers.get(account["pricing_tier_id"]) \
                if account else None
            if tier is not None:
                unit = calc.unit_price_cents(substitute, tier, line["quantity"])
                line["unit_price_cents"] = unit
                line["extended_price_cents"] = unit * line["quantity"]
            line["line_status"] = "RESOLVED"
            touch(line)
    else:
        request["request_status"] = "REJECTED"
        if line is not None:
            line["extended_price_cents"] = 0
            line["line_status"] = "CANCELLED"
            touch(line)
    touch(request)

    if order is not None:
        flows.recompute_totals(order, reassess_freight=False)
        touch(order)
        flows.release_order_if_ready(order)
    if account is not None:
        flows.sync_account(account)
    return ok(serialize.substitute_request(request))


@bp.post("/substitute-requests/<request_id>/withdraw")
def withdraw_substitute(request_id):
    user_id, role = authenticate(WITHDRAWERS)
    parse_body([("withdrawal_reason", "str", True)])
    request = _request_or_404(request_id)
    line, order = _line_and_order(request)
    if order is not None:
        check_account_scope(user_id, role, order["servicer_account_id"])
    _require_pending(request)

    request["request_status"] = "WITHDRAWN"
    touch(request)
    if line is not None and line["line_status"] == "SUBSTITUTE_PENDING":
        line["line_status"] = "BACKORDERED"
        touch(line)
    if order is not None:
        flows.recompute_totals(order, reassess_freight=False)
        touch(order)
        flows.release_order_if_ready(order)
        account = db.servicer_accounts.get(order["servicer_account_id"])
        if account is not None:
            flows.sync_account(account)
    return ok(serialize.substitute_request(request))


@bp.get("/substitute-requests")
def list_substitutes():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.substitute_requests)
    for field in ("order_line_id", "obsolete_part_id",
                  "proposed_substitute_part_id", "created_by_price_file_id",
                  "request_status", "source"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.substitute_request(r) for r in page],
                   limit, offset, total)


@bp.get("/substitute-requests/<request_id>")
def get_substitute(request_id):
    authenticate(ALL_ROLES)
    return ok(serialize.substitute_request(_request_or_404(request_id)))
