"""Bootstrap routes: borrowers, ABS pools, rate-grid entries, and the clock.

PRD §3.1 (Bootstrapping), §2.9 (test-driving clock).
"""
from flask import Blueprint

import clock
import db
import serialize
from auth import authorize
from constants import FICO_BANDS, POOL_RATE_TYPES, TERM_MONTHS, RATE_TYPES
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate
from timeutil import parse_iso
from validate import (
    get_json_body,
    require_str,
    require_enum,
    require_nonneg_int,
    require_positive_int,
    require_int,
    parse_pagination,
)

bp = Blueprint("bootstrap", __name__)


# ---- Borrowers ----
@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    authorize(("POST", "/borrowers"))
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    annual_income_cents = require_nonneg_int(body, "annual_income_cents")
    fico_band = require_enum(body, "fico_band", FICO_BANDS)

    with db.lock():
        # email unique across borrowers (PRD §3.1) -> ERR_DUPLICATE_KEY.
        for b in db.borrowers.values():
            if b["email"] == email:
                raise err("ERR_DUPLICATE_KEY", "borrower email already exists")
        record = {
            "email": email,
            "full_name": full_name,
            "annual_income_cents": annual_income_cents,
            "fico_band": fico_band,
            "member_tier": "NONE",  # every new borrower starts at NONE (PRD §3.1)
        }
        db.stamp_create(record)
        db.borrowers[record["id"]] = record
    return object_response(serialize.borrower(record), 201)


@bp.route("/borrowers/<rid>", methods=["GET"])
def get_borrower(rid):
    authorize(("GET", "/borrowers/{id}"))
    record = get_or_404(db.borrowers, rid)
    return object_response(serialize.borrower(record), 200)


# ---- ABS Pools ----
@bp.route("/abs-pools", methods=["POST"])
def create_abs_pool():
    authorize(("POST", "/abs-pools"))
    body = get_json_body()
    pool_code = require_str(body, "pool_code")
    max_principal_cents = require_positive_int(body, "max_principal_cents")
    min_fico_band = require_enum(body, "min_fico_band", FICO_BANDS)
    allowed_rate_type = require_enum(body, "allowed_rate_type", POOL_RATE_TYPES)

    with db.lock():
        for p in db.abs_pools.values():
            if p["pool_code"] == pool_code:
                raise err("ERR_DUPLICATE_KEY", "pool_code already exists")
        record = {
            "pool_code": pool_code,
            "max_principal_cents": max_principal_cents,
            "min_fico_band": min_fico_band,
            "allowed_rate_type": allowed_rate_type,
            "committed_principal_cents": 0,  # initialized to 0 (PRD §3.1)
            "status": "OPEN",
        }
        db.stamp_create(record)
        db.abs_pools[record["id"]] = record
    return object_response(serialize.abs_pool(record), 201)


@bp.route("/abs-pools/<rid>", methods=["GET"])
def get_abs_pool(rid):
    authorize(("GET", "/abs-pools/{id}"))
    record = get_or_404(db.abs_pools, rid)
    return object_response(serialize.abs_pool(record), 200)


@bp.route("/abs-pools/<rid>/close", methods=["POST"])
def close_abs_pool(rid):
    authorize(("POST", "/abs-pools/{id}/close"))
    with db.lock():
        record = get_or_404(db.abs_pools, rid)
        record["status"] = "CLOSED"  # only OPEN pools are candidates at funding
        db.touch(record)
    return object_response(serialize.abs_pool(record), 200)


# ---- Rate-Grid Entries ----
@bp.route("/rate-grid-entries", methods=["POST"])
def create_rate_grid_entry():
    authorize(("POST", "/rate-grid-entries"))
    body = get_json_body()
    rate_type = require_enum(body, "rate_type", RATE_TYPES)
    term_months = require_int(body, "term_months")
    if term_months not in TERM_MONTHS:
        raise err("ERR_INVALID_REQUEST", "term_months must be one of %s" % sorted(TERM_MONTHS))
    min_fico_band = require_enum(body, "min_fico_band", FICO_BANDS)
    base_apr_bps = require_positive_int(body, "base_apr_bps")
    # index_apr_bps optional, defaults to 0; must be >= 0 (PRD §3.1).
    if "index_apr_bps" in body and body.get("index_apr_bps") is not None:
        index_apr_bps = require_nonneg_int(body, "index_apr_bps")
    else:
        index_apr_bps = 0

    with db.lock():
        record = {
            "rate_type": rate_type,
            "term_months": term_months,
            "min_fico_band": min_fico_band,
            "base_apr_bps": base_apr_bps,
            "index_apr_bps": index_apr_bps,
        }
        # Light entity: only id + created_at (PRD §2.4).
        db.stamp_create(record, with_version=False)
        db.rate_grid_entries[record["id"]] = record
    return object_response(serialize.rate_grid_entry(record), 201)


@bp.route("/rate-grid-entries", methods=["GET"])
def list_rate_grid_entries():
    authorize(("GET", "/rate-grid-entries"))
    limit, offset = parse_pagination()
    from flask import request
    f_rate_type = request.args.get("rate_type")
    f_term = request.args.get("term_months")
    f_band = request.args.get("min_fico_band")

    records = list(db.rate_grid_entries.values())
    if f_rate_type is not None:
        records = [r for r in records if r["rate_type"] == f_rate_type]
    if f_term is not None:
        try:
            term_val = int(f_term)
        except (ValueError, TypeError):
            term_val = None
        records = [r for r in records if r["term_months"] == term_val]
    if f_band is not None:
        records = [r for r in records if r["min_fico_band"] == f_band]

    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.rate_grid_entry(r) for r in page], limit, offset, total)


# ---- Test-driving clock ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(("POST", "/_clock/set_current_utc"))
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601:
        raise err("ERR_INVALID_REQUEST", "missing to_iso8601")
    dt = parse_iso(to_iso8601)
    clock.set_now(dt)
    # output: null (scaffold §1.5) -> data is an empty object per PRD §2.2.
    return object_response({}, 200)
