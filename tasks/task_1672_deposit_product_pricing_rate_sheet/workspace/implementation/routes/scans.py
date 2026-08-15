"""CompetitorRateScan endpoints."""

from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_SCAN_INVALID_STATE, bad_request, not_found
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from utils import bump, req_date, req_list, req_str, round_half_up_int, stamp_new

bp = Blueprint("scans", __name__)

SCAN_STATUSES = ("SUBMITTED", "ANALYZED", "ACTIONED")
PRODUCT_CLASSES = ("SAVINGS", "MONEY_MARKET", "CD", "INTEREST_CHECKING")
# Deterministic tie-break order for the dominant product class.
CLASS_TIE_ORDER = ("CD", "INTEREST_CHECKING", "MONEY_MARKET", "SAVINGS")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@bp.post("/competitor-rate-scans")
@require_roles("PricingAnalyst")
def create_scan():
    data = get_body()
    market_code = req_str(data, "market_code")
    scan_date = req_date(data, "scan_date")
    source_name = req_str(data, "source_name")
    entries = req_list(data, "entries")
    for e in entries:
        if not isinstance(e, dict):
            raise bad_request("each entry must be an object")
        for f in ("competitor_name", "product_class", "rate_bp", "tier_balance_cents"):
            if f not in e:
                raise bad_request(f"entry missing field: {f}")
        if not isinstance(e["competitor_name"], str):
            raise bad_request("entry competitor_name must be a string")
        if e["product_class"] not in PRODUCT_CLASSES:
            raise bad_request("entry product_class is invalid")
        if not _is_int(e["rate_bp"]) or not _is_int(e["tier_balance_cents"]):
            raise bad_request("entry rate_bp and tier_balance_cents must be integers")
    row = {
        "market_code": market_code,
        "scan_date": scan_date,
        "source_name": source_name,
        "entries": entries,
        "benchmark_weighted_bp": None,
        "benchmark_simple_bp": None,
        "status": "SUBMITTED",
    }
    stamp_new(row)
    STORE["scans"][row["id"]] = row
    return ok_object(serialize("scans", row), 201)


@bp.get("/competitor-rate-scans")
@require_roles("PricingAnalyst", "PricingCommittee")
def list_scans():
    from flask import request
    market_code = request.args.get("market_code")
    status = query_enum("status", SCAN_STATUSES)
    rows = list(STORE["scans"].values())
    if market_code is not None:
        rows = [r for r in rows if r["market_code"] == market_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("scans", rows))


@bp.get("/competitor-rate-scans/<scan_id>")
@require_roles("PricingAnalyst", "PricingCommittee")
def get_scan(scan_id):
    row = STORE["scans"].get(scan_id)
    if row is None:
        raise not_found("Scan not found")
    return ok_object(serialize("scans", row))


@bp.post("/competitor-rate-scans/<scan_id>/analyze")
@require_roles("PricingAnalyst")
def analyze_scan(scan_id):
    get_body()
    row = STORE["scans"].get(scan_id)
    if row is None:
        raise not_found("Scan not found")
    if row["status"] != "SUBMITTED":
        raise ApiError(ERR_SCAN_INVALID_STATE, 409,
                       f"Cannot analyze a scan in {row['status']}")
    by_class = {}
    for e in row["entries"]:
        by_class.setdefault(e["product_class"], []).append(e)
    if not by_class:
        row["benchmark_weighted_bp"] = None
        row["benchmark_simple_bp"] = None
    else:
        totals = {pc: sum(e["tier_balance_cents"] for e in rows)
                  for pc, rows in by_class.items()}
        max_total = max(totals.values())
        dominant = next(pc for pc in CLASS_TIE_ORDER
                        if pc in totals and totals[pc] == max_total)
        rows = by_class[dominant]
        denom = sum(e["tier_balance_cents"] for e in rows)
        if denom > 0:
            numer = sum(e["rate_bp"] * e["tier_balance_cents"] for e in rows)
            row["benchmark_weighted_bp"] = round_half_up_int(numer, denom)
        else:
            row["benchmark_weighted_bp"] = None
        row["benchmark_simple_bp"] = round_half_up_int(
            sum(e["rate_bp"] for e in rows), len(rows)
        )
    row["status"] = "ANALYZED"
    bump(row)
    return ok_object(serialize("scans", row))
