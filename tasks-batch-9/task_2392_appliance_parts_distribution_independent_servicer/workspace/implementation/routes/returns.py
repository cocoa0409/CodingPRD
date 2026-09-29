"""Return authorizations: request, decision, receipt and credit."""

from db import db, base_row, fmt, now, parse_stored, touch, whole_days_between
from errors import ApiError
from flask import Blueprint
from middleware import (authenticate, check_account_scope, check_branch_open,
                        check_branch_scope)
from response import created, ok, ok_list
from services import calc, flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("returns", __name__)

ALL_ROLES = ("PlatformAdmin", "CreditManager", "BranchCounterRep", "WarrantyAdmin",
             "PricingAdmin", "Servicer")
RAISERS = ("Servicer", "BranchCounterRep", "PlatformAdmin")
CREDIT_WRITERS = ("CreditManager", "PlatformAdmin")
BRANCH_WRITERS = ("BranchCounterRep", "PlatformAdmin")

REASON_CODES = {"WRONG_PART", "DEFECTIVE_ON_ARRIVAL", "NO_LONGER_NEEDED",
                "CORE_RETURN"}
DECISIONS = {"APPROVE", "REJECT"}
SHIPPED_STATUSES = ("SHIPPED", "RETURNED")
RESTOCKING_REASONS = ("WRONG_PART", "NO_LONGER_NEEDED")


def _ra_or_404(ra_id):
    return flows.find(db.return_authorizations, ra_id,
                      "ERR_RETURN_AUTHORIZATION_NOT_FOUND")


def _require_ra_status(ra, allowed):
    """Rule 16."""
    if ra["ra_status"] not in allowed:
        raise ApiError("ERR_RA_STATE_INVALID",
                       "A return authorization in %s does not accept this "
                       "operation" % ra["ra_status"])


def _line_and_order(ra):
    line = db.order_lines.get(ra["order_line_id"])
    order = db.part_orders.get(line["part_order_id"]) if line else None
    return line, order


@bp.post("/return-authorizations")
def create_return():
    user_id, role = authenticate(RAISERS)
    body = parse_body([
        ("servicer_account_id", "str", True),
        ("order_line_id", "str", True),
        ("quantity", "qty", True),
        ("reason_code", "enum", True, REASON_CODES),
        ("return_branch_id", "str", True),
    ])
    # rule 5 walks the body foreign keys in the order the PRD enumerates them
    flows.branch_or_404(body["return_branch_id"])
    line = flows.line_or_404(body["order_line_id"])
    account = flows.account_or_404(body["servicer_account_id"])
    check_account_scope(user_id, role, account["id"])

    if line["line_status"] not in SHIPPED_STATUSES:
        raise ApiError("ERR_LINE_NOT_SHIPPED",
                       "A return may only be raised against a shipped line")
    part = db.parts.get(line["resolved_part_id"])
    if part is None or not calc.is_returnable(part):
        raise ApiError("ERR_PART_NON_RETURNABLE",
                       "The resolved part may not be returned")

    reason = body["reason_code"]
    is_core = reason == "CORE_RETURN"
    committed = 0
    for other in db.return_authorizations.values():
        if other["order_line_id"] != line["id"]:
            continue
        if other["ra_status"] not in flows.RA_COMMITTED:
            continue
        if (other["reason_code"] == "CORE_RETURN") != is_core:
            continue
        committed += other["quantity"]
    if committed + body["quantity"] > line["quantity"]:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED",
                       "Only %d of the line's %d units remain returnable"
                       % (max(0, line["quantity"] - committed), line["quantity"]))

    order = db.part_orders.get(line["part_order_id"])
    fulfilled_at = order.get("fulfilled_at") if order else None
    if fulfilled_at is None:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED",
                       "The order behind this line was never fulfilled")
    days = whole_days_between(parse_stored(fulfilled_at), now())
    window = calc.CORE_RETURN_WINDOW_DAYS if is_core else calc.RETURN_WINDOW_DAYS
    if days > window:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED",
                       "%d whole days have elapsed since fulfillment, beyond the "
                       "%d-day window" % (days, window))

    gross = 0 if is_core else \
        (line.get("invoiced_unit_price_cents") or 0) * body["quantity"]
    row = base_row()
    row.update({
        "servicer_account_id": account["id"],
        "order_line_id": line["id"],
        "quantity": body["quantity"],
        "reason_code": reason,
        "return_branch_id": body["return_branch_id"],
        "ra_status": "REQUESTED",
        "days_since_fulfilled_at_request": days,
        "gross_return_cents": gross,
        "restocking_fee_pct": None,
        "restocking_fee_cents": 0,
        "credit_amount_cents": 0,
        "core_deposit_refund_cents": 0,
        "fee_waived": False,
        "created_by_user_id": user_id,
        "decided_by_user_id": None,
        "received_at": None,
    })
    db.return_authorizations[row["id"]] = row
    return created(serialize.return_authorization(row))


@bp.post("/return-authorizations/<ra_id>/decision")
def decide_return(ra_id):
    user_id, _role = authenticate(CREDIT_WRITERS)
    body = parse_body([
        ("decision", "enum", True, DECISIONS),
        ("decision_note", "str", False),
        ("waive_restocking_fee", "bool", False),
    ])
    ra = _ra_or_404(ra_id)
    _require_ra_status(ra, ("REQUESTED",))
    waive = bool(body.get("waive_restocking_fee", False))
    line, order = _line_and_order(ra)
    if waive and order is not None \
            and order.get("credit_decided_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who approved the order's credit may not "
                       "waive its restocking fee")

    ra["decided_by_user_id"] = user_id
    if body["decision"] == "REJECT":
        ra["ra_status"] = "REJECTED"
        ra["restocking_fee_pct"] = None
        ra["restocking_fee_cents"] = 0
        ra["credit_amount_cents"] = 0
        ra["core_deposit_refund_cents"] = 0
        touch(ra)
        return ok(serialize.return_authorization(ra))

    ra["ra_status"] = "APPROVED"
    ra["fee_waived"] = waive
    pct, fee, credit = calc.restocking_figures(
        ra["reason_code"], ra["days_since_fulfilled_at_request"],
        ra["gross_return_cents"], waive)
    ra["restocking_fee_pct"] = pct
    ra["restocking_fee_cents"] = fee
    ra["credit_amount_cents"] = credit
    if ra["reason_code"] == "CORE_RETURN" and line is not None:
        ra["core_deposit_refund_cents"] = (line.get("core_deposit_cents") or 0) \
            * ra["quantity"]
    else:
        ra["core_deposit_refund_cents"] = 0
    touch(ra)
    return ok(serialize.return_authorization(ra))


@bp.post("/return-authorizations/<ra_id>/receive")
def receive_return(ra_id):
    user_id, role = authenticate(BRANCH_WRITERS)
    parse_body([])
    ra = _ra_or_404(ra_id)
    check_branch_scope(user_id, role, ra["return_branch_id"])
    branch = db.branches.get(ra["return_branch_id"])
    check_branch_open(branch)
    _require_ra_status(ra, ("APPROVED",))

    line, order = _line_and_order(ra)
    ra["ra_status"] = "RECEIVED"
    ra["received_at"] = fmt(now())

    # conditional restock at the receiving branch
    if ra["reason_code"] in RESTOCKING_REASONS and line is not None:
        record = flows.inventory_for(ra["return_branch_id"],
                                    line["resolved_part_id"])
        if record is None:
            record = base_row()
            record.update({
                "branch_id": ra["return_branch_id"],
                "part_id": line["resolved_part_id"],
                "on_hand_units": ra["quantity"],
                "reserved_units": 0,
                "reorder_point": 0,
                "last_counted_at": None,
            })
            db.inventory_records[record["id"]] = record
        else:
            record["on_hand_units"] = record["on_hand_units"] + ra["quantity"]
            touch(record)

    # crediting happens in the same request
    ra["ra_status"] = "CREDITED"
    touch(ra)

    # hop 1: the line's returned units, for goods returns only
    if ra["reason_code"] != "CORE_RETURN" and line is not None:
        line["returned_units"] = (line["returned_units"] or 0) + ra["quantity"]
        if line["returned_units"] >= line["quantity"] \
                and line["line_status"] == "SHIPPED":
            line["line_status"] = "RETURNED"
        touch(line)

    # hops 2 to 5: exposure, core liability, then the conditional hold release
    account = db.servicer_accounts.get(ra["servicer_account_id"])
    if account is not None:
        flows.sync_account(account)
        flows.maybe_release_credit_hold(account)
    return ok(serialize.return_authorization(ra))


@bp.get("/return-authorizations")
def list_returns():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.return_authorizations)
    for field in ("servicer_account_id", "order_line_id", "return_branch_id",
                  "ra_status", "reason_code"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.return_authorization(r) for r in page],
                   limit, offset, total)


@bp.get("/return-authorizations/<ra_id>")
def get_return(ra_id):
    authenticate(ALL_ROLES)
    return ok(serialize.return_authorization(_ra_or_404(ra_id)))
