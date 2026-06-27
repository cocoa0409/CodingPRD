"""Wine & Spirits Retail API — Flask entry point.

All entities live in-memory (db.store). The store starts empty on every boot;
nothing is seeded. Tests build all state via the API surface.
"""
import os
import re
from datetime import datetime, timezone, date

from flask import Flask, request

import calculations as calc
import errors
import middleware
import response
from db import store, new_id
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

# Roles
R_CUSTOMER = "Customer"
R_ASSOCIATE = "StoreAssociate"
R_COMPLIANCE = "ComplianceOfficer"
R_ADMIN = "Admin"
R_ANON = "Anonymous"

PRODUCT_CATEGORIES = {"WINE", "SPIRITS", "BEER", "GROWLER", "KEG"}
CONTAINER_TYPES = {"BOTTLE", "CAN", "GROWLER_FILL", "KEG_HALF_BBL"}
DRAFT_CATEGORIES = {"GROWLER", "KEG"}
TAX_STATUSES = {"BONDED", "TAXED"}
CHANNELS = {"POS", "PICKUP", "DELIVERY", "SHIP"}
SHIPPING_CHANNELS = {"DELIVERY", "SHIP"}
CARRIERS = {"STORE_COURIER", "LICENSED_COMMON_CARRIER"}
REJECT_REASONS = {"EXPIRED", "DOB_MISMATCH", "UNDERAGE"}


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(err):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return response.error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)


# ===========================================================================
# Request body / field helpers
# ===========================================================================
def get_body():
    """Parse JSON body; tolerate missing/empty body as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.missing_field(f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise errors.missing_field(f"Field {name} must be a string.")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.missing_field(f"Field {name} must be an integer.")
    return v


def is_two_letter_state(code):
    return isinstance(code, str) and bool(re.fullmatch(r"[A-Z]{2}", code))


# ===========================================================================
# Timestamp / version stamping
# ===========================================================================
def stamp_create(rec, with_version=True):
    rec["id"] = new_id()
    rec["created_at"] = store.now_iso()
    rec["_seq"] = store.next_seq()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: bump version + updated_at (only for versioned entities)."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = store.now_iso()
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]


# ===========================================================================
# Clock helpers (PRD §2.8)
# ===========================================================================
def parse_iso(value):
    """Parse an ISO 8601 datetime/date string -> aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request("Timestamp must be a string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        # Maybe a bare date
        try:
            d = date.fromisoformat(value.strip())
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            raise errors.invalid_request(f"Invalid ISO 8601 value: {value}")


def whole_years_between(birth_dt, ref_dt):
    """Whole years from birth_dt to ref_dt."""
    years = ref_dt.year - birth_dt.year
    if (ref_dt.month, ref_dt.day) < (birth_dt.month, birth_dt.day):
        years -= 1
    return years


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_pagination("limit must be in [1, 100].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_pagination("offset must be >= 0.")
    return limit, offset


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


# ===========================================================================
# Lookups (404 on miss)
# ===========================================================================
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return response.object_response({"status": "ok"})


# Routes are registered below by importing route modules.
import routes  # noqa: E402  (registers all endpoints on `app`)
