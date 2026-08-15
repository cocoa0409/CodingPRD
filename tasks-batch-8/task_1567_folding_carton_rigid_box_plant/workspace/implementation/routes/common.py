"""Shared route helpers: body parsing, shape validation, FK existence, lists."""

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import ok_list


def get_body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def not_found(message="Resource not found"):
    raise ApiError(ERR_NOT_FOUND, 404, message)


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        not_found("Resource %s not found" % rid)
    return rec


def req_field(data, field):
    if field not in data or data[field] is None:
        invalid("Missing required field: %s" % field)
    return data[field]


def req_str(data, field):
    value = req_field(data, field)
    if not isinstance(value, str) or value == "":
        invalid("Field %s must be a non-empty string" % field)
    return value


def req_int(data, field, min_v=None):
    value = req_field(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field %s must be an integer" % field)
    if min_v is not None and value < min_v:
        invalid("Field %s must be at least %d" % (field, min_v))
    return value


def req_bool(data, field):
    value = req_field(data, field)
    if not isinstance(value, bool):
        invalid("Field %s must be a boolean" % field)
    return value


def req_enum(data, field, members):
    value = req_field(data, field)
    if not isinstance(value, str) or value not in members:
        invalid("Field %s must be one of %s" % (field, sorted(members)))
    return value


def req_list(data, field):
    value = req_field(data, field)
    if not isinstance(value, list):
        invalid("Field %s must be an array" % field)
    return value


def fk_exists(table, data, field):
    """Priority-4 existence pre-check for a body FK: if present and a string, must resolve."""
    value = data.get(field)
    if isinstance(value, str) and value not in table:
        not_found("Referenced %s does not exist" % field)


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer, filters):
    """filters: list of (query_param, record_field, kind); kind in ("str", "int")."""
    items = []
    for rec in records:
        matched = True
        for param, field, kind in filters:
            raw = request.args.get(param)
            if raw is None:
                continue
            if kind == "int":
                try:
                    wanted = int(raw)
                except ValueError:
                    matched = False
                    break
                if rec.get(field) != wanted:
                    matched = False
                    break
            else:
                if rec.get(field) != raw:
                    matched = False
                    break
        if matched:
            items.append(rec)
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def strip_private(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --- Serializers -----------------------------------------------------------

def ser_plain(rec):
    return strip_private(rec)


def ser_job(job):
    out = strip_private(job)
    good_cartons = job["good_sheets_actual"] * (job["locked_ups"] or 0)
    out["good_cartons_actual"] = good_cartons
    out["available_cartons"] = good_cartons - job["allocated_cartons"]
    return out


def ser_board_stock(stock):
    out = strip_private(stock)
    out["available_sheets"] = (stock["received_sheets"]
                               - stock["reserved_sheets"]
                               - stock["consumed_sheets"])
    return out


def locked_plan_for(job_id):
    plans = [p for p in db.imposition_plans.values()
             if p["job_id"] == job_id and p["status"] == "LOCKED"]
    if not plans:
        return None
    plans.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return plans[-1]


def available_sheets(stock):
    return stock["received_sheets"] - stock["reserved_sheets"] - stock["consumed_sheets"]


def release_job_reservation(job, clear_stock_ref):
    """Release the job's full board reservation back to its BoardStock."""
    stock = db.board_stocks.get(job["board_stock_id"]) if job["board_stock_id"] else None
    if stock is not None and job["reserved_sheets"] > 0:
        stock["reserved_sheets"] -= job["reserved_sheets"]
        from util import touch
        touch(stock)
    job["reserved_sheets"] = 0
    if clear_stock_ref:
        job["board_stock_id"] = None
