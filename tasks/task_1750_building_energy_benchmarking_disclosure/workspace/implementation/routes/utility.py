"""Utility account and usage record endpoints."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import parse_body, require_path_entity, parse_datetime

bp = Blueprint("utility", __name__)


def _periods_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection: each start strictly before the other's end."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Utility accounts
# ---------------------------------------------------------------------------

@bp.post("/v1/buildings/<building_id>/utility-accounts")
def create_utility_account(building_id):
    uid, role = get_context()
    require_roles(["BuildingOwner", "ComplianceOfficer"])
    building = require_path_entity(store.buildings, building_id)
    if role == "BuildingOwner" and building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    body = parse_body({
        "account_number": ("string", True, None),
        "commodity": ("string", True, core.COMMODITIES),
    }, allow_empty=False)
    for a in store.utility_accounts.values():
        if a["building_id"] == building["id"] and a["account_number"] == body["account_number"]:
            raise ApiError("ERR_DUPLICATE_ACCOUNT", 409,
                           "account_number already exists on this building")
    account = db.new_common({
        "id": db.new_id(),
        "building_id": building["id"],
        "account_number": body["account_number"],
        "commodity": body["commodity"],
    })
    store.utility_accounts[account["id"]] = account
    return created(account)


@bp.get("/v1/utility-accounts")
def list_utility_accounts():
    get_context()
    rows = list(store.utility_accounts.values())
    rows = paginate.filter(rows, "building_id")
    rows = paginate.filter(rows, "commodity")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/utility-accounts/<account_id>")
def get_utility_account(account_id):
    get_context()
    account = require_path_entity(store.utility_accounts, account_id)
    return ok(account)


# ---------------------------------------------------------------------------
# Usage records
# ---------------------------------------------------------------------------

@bp.post("/v1/utility-accounts/<account_id>/usage-records")
def create_usage_record(account_id):
    get_context()
    require_roles(["UtilityAgent"])
    account = require_path_entity(store.utility_accounts, account_id)
    body = parse_body({
        "period_start": ("datetime", True, None),
        "period_end": ("datetime", True, None),
        "consumption_value": ("number", True, None),
    }, allow_empty=False)
    period_start = parse_datetime(body["period_start"])
    period_end = parse_datetime(body["period_end"])
    if not (period_start < period_end):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "period_end must fall strictly after period_start")
    if body["consumption_value"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "consumption_value must be greater than zero")
    for r in store.usage_records.values():
        if r["utility_account_id"] != account["id"] or r["status"] != "ACTIVE":
            continue
        if _periods_overlap(period_start, period_end, r["period_start"], r["period_end"]):
            raise ApiError("ERR_USAGE_PERIOD_OVERLAP", 409,
                           "The usage period overlaps an ACTIVE record on this account")
    record = db.new_common({
        "id": db.new_id(),
        "utility_account_id": account["id"],
        "period_start": period_start,
        "period_end": period_end,
        "consumption_value": body["consumption_value"],
        "commodity": account["commodity"],
        "kbtu": core.compute_kbtu(account["commodity"], body["consumption_value"]),
        "status": "ACTIVE",
        "void_reason": None,
        "replaces_usage_record_id": None,
    })
    store.usage_records[record["id"]] = record
    core.usage_upload_cascade(account["building_id"], record)
    return created(record)


@bp.post("/v1/usage-records/<record_id>/void")
def void_usage_record(record_id):
    get_context()
    require_roles(["UtilityAgent"])
    record = require_path_entity(store.usage_records, record_id)
    body = parse_body({
        "reason": ("string", True, None),
        "replacement_period_start": ("datetime", False, None),
        "replacement_period_end": ("datetime", False, None),
        "replacement_consumption_value": ("number", False, None),
    }, allow_empty=False)
    # Input semantics (tier 6): replacement fields are all-or-nothing.
    repl_fields = [f for f in ("replacement_period_start", "replacement_period_end",
                               "replacement_consumption_value") if f in body]
    if repl_fields and len(repl_fields) != 3:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "replacement_period_start, replacement_period_end and "
                       "replacement_consumption_value are all-or-nothing")
    repl_start = repl_end = repl_value = None
    if repl_fields:
        repl_start = parse_datetime(body["replacement_period_start"])
        repl_end = parse_datetime(body["replacement_period_end"])
        repl_value = body["replacement_consumption_value"]
        if not (repl_start < repl_end):
            raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                           "replacement period_end must fall strictly after period_start")
        if repl_value <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "replacement_consumption_value must be greater than zero")
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ACTIVE usage record can be voided")
    account = store.utility_accounts.get(record["utility_account_id"])
    if repl_fields and account is not None:
        for r in store.usage_records.values():
            if (r["utility_account_id"] != account["id"] or r["status"] != "ACTIVE"
                    or r["id"] == record["id"]):
                continue
            if _periods_overlap(repl_start, repl_end, r["period_start"], r["period_end"]):
                raise ApiError("ERR_USAGE_PERIOD_OVERLAP", 409,
                               "The replacement period overlaps an ACTIVE record on this account")
    record["status"] = "VOIDED"
    record["void_reason"] = body["reason"]
    db.touch(record)
    affected_years = set()
    original_year = core.record_year(record)
    if original_year is not None:
        affected_years.add(original_year)
    if repl_fields and account is not None:
        replacement = db.new_common({
            "id": db.new_id(),
            "utility_account_id": account["id"],
            "period_start": repl_start,
            "period_end": repl_end,
            "consumption_value": repl_value,
            "commodity": account["commodity"],
            "kbtu": core.compute_kbtu(account["commodity"], repl_value),
            "status": "ACTIVE",
            "void_reason": None,
            "replaces_usage_record_id": record["id"],
        })
        store.usage_records[replacement["id"]] = replacement
        repl_year = core.record_year(replacement)
        if repl_year is not None:
            affected_years.add(repl_year)
    if account is not None:
        core.usage_void_cascade(account["building_id"], affected_years)
    return ok(record)


@bp.get("/v1/usage-records")
def list_usage_records():
    get_context()
    rows = list(store.usage_records.values())
    rows = paginate.filter(rows, "utility_account_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "replaces_usage_record_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/usage-records/<record_id>")
def get_usage_record(record_id):
    get_context()
    record = require_path_entity(store.usage_records, record_id)
    return ok(record)
