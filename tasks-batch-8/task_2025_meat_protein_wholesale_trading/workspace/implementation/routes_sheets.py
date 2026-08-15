"""Price sheets, lines, publish/close lifecycle, and the allocation
waterfall (PRD sections 3.2 and 3.6)."""

from datetime import date, timedelta

from flask import Blueprint, request

from store import TABLES, clock_now, clock_iso
from helpers import (
    auth, success, err, get_body, req_str, req_num, req_positive_num,
    req_positive_int, req_date, parse_iso_date, paginate, sorted_by_created,
    stamp_new, touch, path_get, require_ref, find, num_out, dec, q2,
    recompute_customer_exposure,
)

bp = Blueprint("sheets", __name__)

ADMIN = ["DeskAdmin"]
TRADER = ["Trader"]
RISK = ["RiskOfficer"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]

TIER_RANK = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}


def sheet_public(s):
    return {
        "id": s["id"],
        "week_start_date": s["week_start_date"],
        "status": s["status"],
        "supersedes_sheet_id": s["supersedes_sheet_id"],
        "published_at": s["published_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def line_public(l):
    return {
        "id": l["id"],
        "price_sheet_id": l["price_sheet_id"],
        "product_id": l["product_id"],
        "price_per_lb_cents": l["price_per_lb_cents"],
        "weekly_supply_lbs": l["weekly_supply_lbs"],
        "allocated_lbs": num_out(l["allocated_lbs"]),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ---------------------------------------------------------------------------
# Price sheets
# ---------------------------------------------------------------------------

@bp.route("/api/price-sheets", methods=["POST"])
def create_sheet():
    auth(TRADER)
    body = get_body()
    week = req_date(body, "week_start_date")
    supersedes = req_str(body, "supersedes_sheet_id", optional=True)
    if supersedes is not None:
        require_ref("price_sheets", supersedes, "supersedes_sheet_id")
    # Temporal: week_start_date must be a Monday.
    if parse_iso_date(week, "week_start_date").weekday() != 0:
        err("ERR_INVALID_WEEK_START", 422, "week_start_date must be a Monday")
    rec = {
        "week_start_date": week,
        "status": "DRAFT",
        "supersedes_sheet_id": supersedes,
        "published_at": None,
    }
    stamp_new(rec)
    TABLES["price_sheets"][rec["id"]] = rec
    return success(sheet_public(rec), code=201)


@bp.route("/api/price-sheets", methods=["GET"])
def list_sheets():
    auth(ALL)
    items = sorted_by_created(TABLES["price_sheets"].values())
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_sheet_id")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if supersedes is not None:
        items = [s for s in items if s["supersedes_sheet_id"] == supersedes]
    page, meta = paginate(items)
    return success([sheet_public(s) for s in page], response_type="array",
                   pagination=meta)


@bp.route("/api/price-sheets/<sheetId>", methods=["GET"])
def get_sheet(sheetId):
    auth(ALL)
    s = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    return success(sheet_public(s))


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

@bp.route("/api/price-sheets/<sheetId>/lines", methods=["POST"])
def add_line(sheetId):
    auth(TRADER)
    body = get_body()
    product_id = req_str(body, "product_id")
    price = req_positive_int(body, "price_per_lb_cents")
    supply = req_positive_int(body, "weekly_supply_lbs")
    sheet = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    require_ref("products", product_id, "product_id")
    if sheet["status"] != "DRAFT":
        err("ERR_PRICE_SHEET_NOT_DRAFT", 409, "Lines may only be added to a DRAFT sheet")
    rec = {
        "price_sheet_id": sheet["id"],
        "product_id": product_id,
        "price_per_lb_cents": price,
        "weekly_supply_lbs": supply,
        "allocated_lbs": q2(dec(0)),
    }
    stamp_new(rec)
    TABLES["price_sheet_lines"][rec["id"]] = rec
    return success(line_public(rec), code=201)


@bp.route("/api/price-sheets/<sheetId>/lines", methods=["GET"])
def list_sheet_lines(sheetId):
    auth(ALL)
    sheet = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    items = [l for l in sorted_by_created(TABLES["price_sheet_lines"].values())
             if l["price_sheet_id"] == sheet["id"]]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    page, meta = paginate(items)
    return success([line_public(l) for l in page], response_type="array",
                   pagination=meta)


@bp.route("/api/price-sheet-lines", methods=["GET"])
def list_all_lines():
    auth(ALL)
    items = sorted_by_created(TABLES["price_sheet_lines"].values())
    product_id = request.args.get("product_id")
    sheet_id = request.args.get("price_sheet_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if sheet_id is not None:
        items = [l for l in items if l["price_sheet_id"] == sheet_id]
    page, meta = paginate(items)
    return success([line_public(l) for l in page], response_type="array",
                   pagination=meta)


@bp.route("/api/price-sheet-lines/<lineId>", methods=["GET"])
def get_line(lineId):
    auth(ALL)
    l = path_get("price_sheet_lines", lineId, "ERR_PRICE_SHEET_LINE_NOT_FOUND")
    return success(line_public(l))


# ---------------------------------------------------------------------------
# Cascades shared by publish / close
# ---------------------------------------------------------------------------

def allocation_has_open_shipments(alloc):
    for s in TABLES["shipments"].values():
        if s["allocation_id"] == alloc["id"] and s["status"] in ("STAGING", "IN_TRANSIT"):
            return True
    return False


def cancel_allocation(alloc, reason):
    """Cascade cancellation: REQUESTED simply closes; CONFIRMED (with no open
    shipments) releases its supply and recomputes the customer's exposure."""
    was_confirmed = alloc["status"] == "CONFIRMED"
    if was_confirmed:
        grant = dec(alloc["allocated_lbs"])
        if alloc.get("forward_contract_id"):
            contract = find("forward_contracts", alloc["forward_contract_id"])
            if contract is not None:
                contract["earmarked_lbs"] = q2(dec(contract["earmarked_lbs"]) - grant)
                touch(contract)
        else:
            line = find("price_sheet_lines", alloc["price_sheet_line_id"])
            if line is not None:
                line["allocated_lbs"] = q2(dec(line["allocated_lbs"]) - grant)
                touch(line)
    alloc["status"] = "CANCELLED"
    alloc["cancel_reason"] = reason
    touch(alloc)
    if was_confirmed:
        customer = find("customers", alloc["customer_id"])
        if customer is not None:
            recompute_customer_exposure(customer)


def cascade_cancel_sheet_allocations(sheet, reason):
    """Cancel remaining REQUESTED allocations on the sheet's lines and
    CONFIRMED allocations with no STAGING or IN_TRANSIT shipment."""
    for line in sorted_by_created(TABLES["price_sheet_lines"].values()):
        if line["price_sheet_id"] != sheet["id"]:
            continue
        for alloc in sorted_by_created(TABLES["allocations"].values()):
            if alloc["price_sheet_line_id"] != line["id"]:
                continue
            if alloc["status"] == "REQUESTED":
                cancel_allocation(alloc, reason)
            elif alloc["status"] == "CONFIRMED" and not allocation_has_open_shipments(alloc):
                cancel_allocation(alloc, reason)


# ---------------------------------------------------------------------------
# Publish / close
# ---------------------------------------------------------------------------

@bp.route("/api/price-sheets/<sheetId>/publish", methods=["POST"])
def publish_sheet(sheetId):
    auth(ADMIN)
    sheet = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    # State precondition: must be DRAFT.
    if sheet["status"] != "DRAFT":
        err("ERR_PRICE_SHEET_NOT_DRAFT", 409, "Only a DRAFT sheet may be published")
    # Must carry at least one line.
    lines = [l for l in TABLES["price_sheet_lines"].values()
             if l["price_sheet_id"] == sheet["id"]]
    if not lines:
        err("ERR_SHEET_HAS_NO_LINES", 409, "Cannot publish a sheet with no lines")
    # No other DRAFT or PUBLISHED sheet may cover the same week. The sheet
    # named by supersedes_sheet_id is being replaced by this very act, so it
    # is not a competing contender for the week.
    for other in TABLES["price_sheets"].values():
        if other["id"] == sheet["id"]:
            continue
        if sheet["supersedes_sheet_id"] and other["id"] == sheet["supersedes_sheet_id"]:
            continue
        if other["status"] in ("DRAFT", "PUBLISHED") and \
                other["week_start_date"] == sheet["week_start_date"]:
            err("ERR_PRICE_SHEET_WEEK_CONFLICT", 409,
                "Another DRAFT or PUBLISHED sheet covers the same week_start_date")
    # Supersede target must currently be PUBLISHED.
    target = None
    if sheet["supersedes_sheet_id"]:
        target = TABLES["price_sheets"].get(sheet["supersedes_sheet_id"])
        if target is None:
            err("ERR_REFERENCE_NOT_FOUND", 422, "supersedes_sheet_id does not exist")
        if target["status"] != "PUBLISHED":
            err("ERR_PRICE_SHEET_NOT_PUBLISHED", 409,
                "supersedes_sheet_id must reference a PUBLISHED sheet")
    # Publish.
    sheet["status"] = "PUBLISHED"
    sheet["published_at"] = clock_iso()
    touch(sheet)
    # Three-link supersede cascade.
    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)
        cascade_cancel_sheet_allocations(target, "SHEET_SUPERSEDED")
    return success(sheet_public(sheet))


@bp.route("/api/price-sheets/<sheetId>/close", methods=["POST"])
def close_sheet(sheetId):
    auth(ADMIN)
    sheet = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    if sheet["status"] == "DRAFT":
        # Discarding a draft has no further effect.
        sheet["status"] = "DISCARDED"
        touch(sheet)
        return success(sheet_public(sheet))
    if sheet["status"] != "PUBLISHED":
        err("ERR_PRICE_SHEET_NOT_PUBLISHED", 409,
            "Only a PUBLISHED sheet may be closed")
    sheet["status"] = "CLOSED"
    touch(sheet)
    cascade_cancel_sheet_allocations(sheet, "SHEET_CLOSED")
    return success(sheet_public(sheet))


# ---------------------------------------------------------------------------
# Allocation waterfall (PRD section 3.6)
# ---------------------------------------------------------------------------

def allocation_public(a):
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "price_sheet_line_id": a["price_sheet_line_id"],
        "forward_contract_id": a["forward_contract_id"],
        "requested_lbs": num_out(a["requested_lbs"]),
        "allocated_lbs": num_out(a["allocated_lbs"]),
        "unit_price_cents": a["unit_price_cents"],
        "status": a["status"],
        "cancel_reason": a["cancel_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/api/price-sheets/<sheetId>/run-allocation", methods=["POST"])
def run_allocation(sheetId):
    auth(RISK)
    sheet = path_get("price_sheets", sheetId, "ERR_PRICE_SHEET_NOT_FOUND")
    if sheet["status"] != "PUBLISHED":
        err("ERR_PRICE_SHEET_NOT_PUBLISHED", 409,
            "Allocation runs require a PUBLISHED sheet")
    confirmed = 0
    shortfall = 0
    processed = []
    lines = [l for l in sorted_by_created(TABLES["price_sheet_lines"].values())
             if l["price_sheet_id"] == sheet["id"]]
    for line in lines:
        remaining = dec(line["weekly_supply_lbs"]) - dec(line["allocated_lbs"])
        reqs = [a for a in TABLES["allocations"].values()
                if a["price_sheet_line_id"] == line["id"] and a["status"] == "REQUESTED"]
        reqs.sort(key=lambda a: (
            TIER_RANK.get(find("customers", a["customer_id"])["allocation_tier"]
                          if find("customers", a["customer_id"]) else "TIER_3", 3),
            a["_seq"]))
        for alloc in reqs:
            contract = None
            if alloc.get("forward_contract_id"):
                contract = find("forward_contracts", alloc["forward_contract_id"])
                if contract is not None and contract["status"] == "OPEN":
                    pool = dec(contract["committed_lbs"]) \
                        - dec(contract["delivered_lbs"]) \
                        - dec(contract["earmarked_lbs"])
                    price = contract["fixed_price_per_lb_cents"]
                else:
                    pool = dec(0)
                    price = contract["fixed_price_per_lb_cents"] if contract \
                        else line["price_per_lb_cents"]
            else:
                pool = remaining
                price = line["price_per_lb_cents"]
            grant = min(dec(alloc["requested_lbs"]), pool)
            if grant < 0:
                grant = dec(0)
            grant = q2(grant)
            if grant > 0:
                alloc["status"] = "CONFIRMED"
                alloc["allocated_lbs"] = grant
                alloc["unit_price_cents"] = price
                touch(alloc)
                if contract is not None:
                    contract["earmarked_lbs"] = q2(dec(contract["earmarked_lbs"]) + grant)
                    touch(contract)
                else:
                    line["allocated_lbs"] = q2(dec(line["allocated_lbs"]) + grant)
                    touch(line)
                    remaining -= grant
                confirmed += 1
                customer = find("customers", alloc["customer_id"])
                if customer is not None:
                    recompute_customer_exposure(customer)
            else:
                alloc["status"] = "SHORTFALL"
                touch(alloc)
                shortfall += 1
            processed.append(alloc)
    return success({
        "confirmed_count": confirmed,
        "shortfall_count": shortfall,
        "allocations": [allocation_public(a) for a in processed],
    })
