"""Sales lines, royalty statements (issue/pay), and the logical clock."""
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import (resolve, get_body, require_fields, require_enum,
                     require_positive_int, paginate_list)
from store import db, base_record, touch, parse_dt
import calc
import models
import queries

bp = Blueprint("sales", __name__)

TERRITORIES = {"US", "UK", "EU", "ROW"}
LINE_TYPES = {"SALE", "RETURN"}


# ---------------- Sales lines ----------------
@bp.route("/sales-lines", methods=["POST"])
def create_sales_line():
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    format_id = body.get("format_id")
    channel_id = body.get("channel_id")
    fmt = resolve("format", format_id) if format_id is not None else None
    channel = resolve("channel", channel_id) if channel_id is not None else None
    territory = body.get("territory")
    units = body.get("units")
    line_type = body.get("line_type")
    sale_dt = parse_dt(body.get("sale_date"))

    # business_fiscal (prio8): a price must be selectable for this line
    price = None
    if fmt and channel and territory is not None and sale_dt is not None:
        price = queries.select_price_for_sale(fmt["id"], channel["id"], territory, sale_dt)
        if price is None:
            raise ApiError("ERR_NO_VALID_PRICE",
                           "No ACTIVE price covers this format/channel/territory at sale_date")

    # shape (prio10)
    require_fields(body, ["format_id", "channel_id", "territory", "units",
                          "line_type", "sale_date"])
    require_enum(territory, TERRITORIES, "territory")
    require_enum(line_type, LINE_TYPES, "line_type")
    require_positive_int(units, "units")
    if sale_dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "sale_date is invalid")

    royalty_pu = price["royalty_per_unit_cents"]
    gross, reserve = calc.sales_line_amounts(
        royalty_pu, units, line_type, channel["returns_reserve_pct"])

    rec = base_record()
    rec.update({
        "format_id": fmt["id"],
        "channel_id": channel["id"],
        "territory": territory,
        "units": units,
        "line_type": line_type,
        "sale_date": body["sale_date"],
        "royalty_per_unit_cents": royalty_pu,
        "gross_royalty_cents": gross,
        "reserve_held_cents": reserve,
        "status": "PENDING",
    })
    db.sales[rec["id"]] = rec

    # reconcile the owning publisher's running reserve balance
    pub_id = queries.publisher_id_of_format(fmt)
    queries.reconcile_publisher_reserve(pub_id)

    return success(models.ser_salesline(rec), status=201)


@bp.route("/sales-lines/<sid>", methods=["GET"])
def get_sales_line(sid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("salesline", sid)
    require_ownership(role, uid, "salesline", rec)
    return success(models.ser_salesline(rec))


@bp.route("/sales-lines", methods=["GET"])
def list_sales_lines():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.sales.values())
    if role == "Publisher":
        records = [s for s in records if queries.publisher_id_of_sales_line(s) == uid]
    fid = request.args.get("format_id")
    cid = request.args.get("channel_id")
    if fid:
        records = [s for s in records if s.get("format_id") == fid]
    if cid:
        records = [s for s in records if s.get("channel_id") == cid]
    return paginate_list(records, models.ser_salesline)


# ---------------- Statement issue / pay ----------------
@bp.route("/royalty-statements/<stid>/issue", methods=["POST"])
def issue_statement(stid):
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    st = resolve("statement", stid)
    if st["status"] != "ACCRUING":
        raise ApiError("ERR_STATEMENT_INVALID_STATE", "Statement must be ACCRUING to issue")
    period_end = parse_dt(st["period_end"])
    period_start = parse_dt(st["period_start"])
    # business_temporal (prio5): period must have ended
    if period_end is None or period_end > db.clock:
        raise ApiError("ERR_PERIOD_NOT_ENDED", "Statement period has not ended yet")
    # sweep candidates: PENDING lines of this publisher inside [period_start, period_end]
    pub_id = st["publisher_id"]
    swept = [l for l in queries.sales_lines_of_publisher(pub_id)
             if l["status"] == "PENDING" and period_start is not None
             and period_start <= parse_dt(l["sale_date"]) <= period_end]
    # business_referential (prio6): at least one sales line in the period
    if not swept:
        raise ApiError("ERR_NO_SALES_IN_PERIOD", "No PENDING sales lines fall within the period")

    gross = sum(l["gross_royalty_cents"] for l in swept)
    reserve_held = sum(l["reserve_held_cents"] for l in swept)
    prior = queries.prior_issued_statement(pub_id, period_start)
    reserve_released = prior["reserve_held_cents"] if prior else 0
    net = gross - reserve_held + reserve_released

    for l in swept:
        l["status"] = "STATEMENTED"
        touch(l)

    st["gross_royalty_cents"] = gross
    st["reserve_held_cents"] = reserve_held
    st["reserve_released_cents"] = reserve_released
    st["provisional_net_cents"] = gross - reserve_held
    st["net_payable_cents"] = net
    st["status"] = "ISSUED"
    touch(st)
    return success(models.ser_statement(st))


@bp.route("/royalty-statements/<stid>/pay", methods=["POST"])
def pay_statement(stid):
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    st = resolve("statement", stid)
    if st["status"] != "ISSUED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE", "Statement must be ISSUED to pay")
    st["status"] = "PAID"
    touch(st)
    # publisher.lifetime_paid_cents is derived live from PAID statements
    return success(models.ser_statement(st))


@bp.route("/royalty-statements/<stid>", methods=["GET"])
def get_statement(stid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("statement", stid)
    require_ownership(role, uid, "statement", rec)
    return success(models.ser_statement(rec))


@bp.route("/royalty-statements", methods=["GET"])
def list_statements():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.statements.values())
    if role == "Publisher":
        records = [s for s in records if s.get("publisher_id") == uid]
    pub = request.args.get("publisher_id")
    if pub:
        records = [s for s in records if s.get("publisher_id") == pub]
    return paginate_list(records, models.ser_statement)


# ---------------- Logical clock ----------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_dt(raw)
    if raw is None or dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required and must be ISO-8601")
    db.clock = dt
    return success({})
