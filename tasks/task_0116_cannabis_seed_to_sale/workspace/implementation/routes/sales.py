"""Sale + SaleLine endpoints (PRD §3.7): flower-equivalent math, daily limit,
age verification, OCC."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, is_int, round2,
                     paginate, sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import sale_view, sale_line_view

bp = Blueprint("sales", __name__)

READ_ROLES = ["Budtender", "ComplianceManager", "StateRegulator"]


def get_sale_or_404(sale_id):
    s = db.sales.get(sale_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Sale not found.")
    return s


def _parse_date_part(value):
    """Parse an ISO date/datetime, returning a date for sale_date comparisons."""
    s = value
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Invalid ISO 8601 date.")
    return dt


def recompute_sale_flower_equiv(sale):
    """Sum of already-rounded per-line flower_equiv_grams, that sum rounded to
    2dp (round-then-sum, PRD §3.7 / §2.9)."""
    lines = [l for l in db.sale_lines.values() if l["sale_id"] == sale["id"]]
    total = Decimal("0")
    for l in lines:
        total += Decimal(str(l["flower_equiv_grams"]))
    sale["flower_equiv_grams"] = round2(total)


@bp.route("/compliance/sales", methods=["POST"])
@require_auth(["Budtender"])
def create_sale():
    body = get_json_body()
    require_fields(body, ["retail_license_id", "customer_id", "sale_date"])
    retail_license_id = body["retail_license_id"]
    customer_id = body["customer_id"]
    sale_date = body["sale_date"]

    # Existence (priority 3): license + customer.
    lic = db.licenses.get(retail_license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "Retail license not found.")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")

    # License-type (priority 6): only RETAIL opens sales.
    if lic["license_type"] != "RETAIL":
        raise err("ERR_LICENSE_TYPE_MISMATCH", "Sales require a RETAIL license.")

    # Sale-window overlap (priority 13): at most one OPEN sale per customer per
    # retail license per sale_date.
    for s in db.sales.values():
        if (s["customer_id"] == customer_id
                and s["retail_license_id"] == retail_license_id
                and s["sale_date"] == sale_date
                and s["status"] == "OPEN"):
            raise err("ERR_SALE_WINDOW_OVERLAP",
                      "Customer already has an OPEN sale at this license for this date.")

    rec = {
        "id": db.new_id(),
        "retail_license_id": retail_license_id,
        "customer_id": customer_id,
        "sale_date": sale_date,
        "status": "OPEN",
        "flower_equiv_grams": 0,
    }
    stamp_create(rec)
    db.sales[rec["id"]] = rec
    return object_response(sale_view(rec), 201)


@bp.route("/compliance/sales", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_sales():
    items = list(db.sales.values())
    rl = request.args.get("retail_license_id")
    cu = request.args.get("customer_id")
    sd = request.args.get("sale_date")
    st = request.args.get("status")
    if rl is not None:
        items = [r for r in items if r["retail_license_id"] == rl]
    if cu is not None:
        items = [r for r in items if r["customer_id"] == cu]
    if sd is not None:
        items = [r for r in items if r["sale_date"] == sd]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([sale_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/sales/<sale_id>", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def get_sale(sale_id):
    return object_response(sale_view(get_sale_or_404(sale_id)))


@bp.route("/compliance/sales/<sale_id>/lines", methods=["POST"])
@require_auth(["Budtender"])
def add_sale_line(sale_id):
    sale = get_sale_or_404(sale_id)
    body = get_json_body()
    require_fields(body, ["package_id", "grams"])
    package_id = body["package_id"]
    grams = body["grams"]
    if not is_number(grams) or grams <= 0:
        raise err("ERR_INVALID_REQUEST", "grams must be > 0.")

    # Existence (priority 3): package.
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise err("ERR_NOT_FOUND", "Package not found.")

    # Parent state (priority 17): sale must be OPEN.
    if sale["status"] != "OPEN":
        raise err("ERR_INVALID_PARENT_STATE", "Sale must be OPEN to add a line.")

    # Lab hold (priority 8): package must not be on lab hold.
    if pkg.get("lab_hold"):
        raise err("ERR_LAB_HOLD_ACTIVE", "Package is on lab hold and cannot be sold.")

    # Quantity sufficiency (priority 11): grams <= package remaining.
    if Decimal(str(grams)) > Decimal(str(pkg["remaining_grams"])):
        raise err("ERR_INSUFFICIENT_QUANTITY", "grams exceed package remaining_grams.")

    # Per-line flower-equivalent: grams * factor, rounded to 2dp.
    factor = Decimal(constants.FLOWER_EQUIV_FACTOR[pkg["product_category"]])
    line_fe = round2(Decimal(str(grams)) * factor)

    rec = {
        "id": db.new_id(),
        "sale_id": sale_id,
        "package_id": package_id,
        "grams": grams,
        "flower_equiv_grams": line_fe,
    }
    stamp_create(rec, versioned=False)
    db.sale_lines[rec["id"]] = rec

    recompute_sale_flower_equiv(sale)
    touch(sale)
    return object_response(sale_line_view(rec), 201)


@bp.route("/compliance/sales/<sale_id>/lines", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_sale_lines(sale_id):
    get_sale_or_404(sale_id)
    items = [l for l in db.sale_lines.values() if l["sale_id"] == sale_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([sale_line_view(r) for r in page], limit, offset, total)


def _age_at(birthdate_str, sale_date_str):
    bd = _parse_date_part(birthdate_str)
    sd = _parse_date_part(sale_date_str)
    years = sd.year - bd.year
    # subtract one if the sale month/day precedes the birth month/day
    if (sd.month, sd.day) < (bd.month, bd.day):
        years -= 1
    return years


@bp.route("/compliance/sales/<sale_id>/finalize", methods=["POST"])
@require_auth(["Budtender"])
def finalize_sale(sale_id):
    sale = get_sale_or_404(sale_id)
    body = get_json_body()
    require_fields(body, ["expected_sale_version"])
    expected = body["expected_sale_version"]

    # State (priority 4): must be OPEN.
    if sale["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Sale must be OPEN to finalize.")

    # has >= 1 line.
    lines = sort_by_created([l for l in db.sale_lines.values() if l["sale_id"] == sale_id])
    if len(lines) < 1:
        raise err("ERR_INVALID_STATE", "Sale must have at least one line to finalize.")

    # License-active (priority 5): retail license must be ACTIVE.
    lic = db.licenses.get(sale["retail_license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Retail license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Retail license is not ACTIVE.")

    customer = db.customers.get(sale["customer_id"])
    if customer is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")

    # Age verification (priority 20, safety tier, before fiscal daily-limit).
    if _age_at(customer["birthdate"], sale["sale_date"]) < constants.LEGAL_AGE_YEARS:
        raise err("ERR_AGE_VERIFICATION_FAILED", "Customer is below the legal age at sale_date.")

    # Daily-limit (priority 14): prior FINALIZED same-day + current <= limit.
    prior = Decimal("0")
    for s in db.sales.values():
        if (s["customer_id"] == sale["customer_id"]
                and s["sale_date"] == sale["sale_date"]
                and s["status"] == "FINALIZED"):
            prior += Decimal(str(s["flower_equiv_grams"]))
    projected = round2(prior + Decimal(str(sale["flower_equiv_grams"])))
    multiplier = constants.MEDICAL_LIMIT_MULTIPLIER if customer["is_medical"] else 1
    limit = Decimal(str(lic["daily_purchase_limit_grams"])) * Decimal(str(multiplier))
    if Decimal(str(projected)) > limit:
        raise err("ERR_DAILY_LIMIT_EXCEEDED", "Projected daily total exceeds the customer limit.")

    # OCC (priority 15): expected_sale_version must match.
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_sale_version must be an integer.")
    if expected != sale["version"]:
        raise err("ERR_STALE_VERSION", "expected_sale_version does not match current version.")

    # Apply: sale -> FINALIZED; cascade decrement package remaining; DEPLETED.
    from services import maybe_auto_finish_harvest
    sale["status"] = "FINALIZED"
    touched_harvests = set()
    for l in lines:
        pkg = db.packages.get(l["package_id"])
        if pkg is None:
            continue
        new_remaining = round2(Decimal(str(pkg["remaining_grams"])) - Decimal(str(l["grams"])))
        pkg["remaining_grams"] = new_remaining
        depleted = (new_remaining == 0 or new_remaining == 0.0)
        if depleted and pkg["status"] == "ACTIVE":
            pkg["status"] = "DEPLETED"
            touched_harvests.add(pkg["harvest_id"])
        touch(pkg)
    touch(sale)
    # Bubble-up: a depleted package may close its (CURED, fully-packaged) harvest.
    for hid in touched_harvests:
        maybe_auto_finish_harvest(db.harvests.get(hid))
    return object_response(sale_view(sale))


@bp.route("/compliance/sales/<sale_id>/void", methods=["POST"])
@require_auth(["Budtender"])
def void_sale(sale_id):
    sale = get_sale_or_404(sale_id)
    if sale["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Sale must be OPEN to void.")
    sale["status"] = "VOIDED"
    touch(sale)
    return object_response(sale_view(sale))
