"""Airline Baggage Claims API — Flask entry point.

Implements the PRD at workspace/PRD.md and the scaffold SCAFFOLD.yaml.
Single-file app for clarity; logic grouped by resource.
"""

import os
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

from db import STORE
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REPORT_NOT_TRACING,
    ERR_REPORT_NOT_AWAITING_DELIVERY,
    ERR_REPORT_NOT_ACCEPTING_EXPENSES,
    ERR_REPORT_NOT_DELIVERED,
    ERR_REPORT_NOT_DECLARED_LOST,
    ERR_REPORT_NOT_IN_DAMAGE_REVIEW,
    ERR_REPORT_NOT_IN_CLAIM_REVIEW,
    ERR_SETTLEMENT_NOT_OFFERED,
    ERR_SETTLEMENT_NOT_PAYABLE,
    ERR_DISPATCH_NOT_RESCHEDULABLE,
    ERR_CLAIM_NOT_PAYABLE,
    ERR_STALE_REPORT_VERSION,
    ERR_BAG_PASSENGER_MISMATCH,
    ERR_BAG_ALREADY_REPORTED,
    ERR_COURIER_ZONE_MISMATCH,
    ERR_REPAIR_NOT_ALLOWED_FOR_TYPE,
    ERR_UNADJUDICATED_EXPENSE_CLAIMS,
    ERR_PICKUP_IN_PAST,
    ERR_DISPATCH_WINDOW_CONFLICT,
    ERR_VENDOR_CAPACITY_EXCEEDED,
    ERR_DUPLICATE_TAG_NUMBER,
    ERR_DUPLICATE_REPORT_REFERENCE,
    ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS,
    ERR_REPAIR_WINDOW_INVALID,
    ERR_DECLARED_VALUE_EXCEEDS_MAX,
    ERR_EXPENSE_CLAIM_OVER_MAX,
)
from middleware import get_auth, require_roles
from response import success_object, success_list, error_response
from util import (
    CLOCK_START_ISO,
    iso_to_ms,
    ms_to_iso,
    current_clock_ms,
    current_clock_iso,
    new_resource_id,
    date_iso,
    parse_date,
    date_of_ms,
    round_half_up_cents,
    touch,
    init_system_fields,
)
from validators import (
    bad_request,
    get_json_body,
    ensure_no_unknown_fields,
    require_fields,
    as_str,
    as_nonempty_str,
    as_bool,
    as_int,
    as_enum,
    as_str_array,
    as_date_str,
    as_iso_datetime_str,
    as_tag_number,
)

# =============================================================================
# Constants (calculations)
# =============================================================================

MONTREAL_CAP_CENTS = 170016
DOMESTIC_PER_KG_CENTS = 2500
DECLARED_VALUE_MAX_CENTS = 500000

EXPENSE_WINDOW_DAYS = 5
POOL_CAP_CENTS = 150000
EXPENSE_CLAIM_MAX_CENTS = 300000
FX_RATE = {"USD": Decimal("1.0"), "EUR": Decimal("1.10"), "JPY": Decimal("0.0067")}
TIER_DAILY_CAP = {"STANDARD": 7500, "PREMIUM": 10000, "ELITE": 15000}

DEPRECIATION_RATE = Decimal("0.20")
DEPRECIATION_FLOOR = Decimal("0.10")
REPLACE_THRESHOLD = Decimal("0.75")

TRACING_TIMEOUT_HOURS = 504

REPORT_TYPES = {"DELAYED", "DAMAGED", "PILFERED"}
TRACING_EVENT_TYPES = {
    "FORWARDED", "LOCATED", "ON_HAND_AT_STATION",
    "IN_TRANSIT_TO", "DELIVERY_ARRANGED", "MISSCAN_CORRECTED",
}
ROOT_CAUSES = {"MISCONNECT", "BAGROOM_ERROR", "LOADING_ERROR", "TAGGING_ERROR", "SECURITY_HOLD"}
PASSENGER_TIERS = {"STANDARD", "PREMIUM", "ELITE"}
CURRENCIES = {"USD", "EUR", "JPY"}

# Report statuses
REPORT_EXPENSE_ACCEPTING = {
    "TRACING", "FOUND_PENDING_DELIVERY", "DELIVERY_IN_PROGRESS", "DELIVERED", "DECLARED_LOST",
}


# =============================================================================
# App factory + error handlers
# =============================================================================

def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Initialize the logical clock exactly once per process
    STORE.current_utc_ms = iso_to_ms(CLOCK_START_ISO)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface as a generic 400 (shape error) — safest fallback for the harness.
        import traceback
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, f"Unexpected error: {err}", 400)

    register_routes(app)
    return app


# =============================================================================
# Serialization helpers
# =============================================================================

def station_view(s):
    return {
        "id": s["id"],
        "station_code": s["station_code"],
        "name": s["name"],
        "bags_handled_total": s["bags_handled_total"],
        "open_report_count": s["open_report_count"],
        "recovered_bag_count": s["recovered_bag_count"],
        "mishandled_report_count": s["mishandled_report_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def carrier_view(c):
    return {
        "id": c["id"],
        "carrier_code": c["carrier_code"],
        "name": c["name"],
        "is_interline_partner": c["is_interline_partner"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def courier_view(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "serves_station_ids": list(c["serves_station_ids"]),
        "turnaround_buffer_minutes": c["turnaround_buffer_minutes"],
        "active_dispatch_count": c["active_dispatch_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def vendor_view(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "bench_capacity": v["bench_capacity"],
        "occupied_bench_slots": v["occupied_bench_slots"],
        "available_bench_slots": v["bench_capacity"] - v["occupied_bench_slots"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def passenger_view(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "tier": p["tier"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def bag_tag_view(b):
    return {
        "id": b["id"],
        "tag_number": b["tag_number"],
        "passenger_id": b["passenger_id"],
        "routing_carrier_ids": list(b["routing_carrier_ids"]),
        "is_international": b["is_international"],
        "weight_kg": b["weight_kg"],
        "declared_value_cents": b["declared_value_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "report_reference": r["report_reference"],
        "passenger_id": r["passenger_id"],
        "bag_tag_id": r["bag_tag_id"],
        "station_id": r["station_id"],
        "type": r["type"],
        "status": r["status"],
        "opened_on": r["opened_on"],
        "delivered_on": r["delivered_on"],
        "liability_regime": r["liability_regime"],
        "liable_carrier_id": r["liable_carrier_id"],
        "effective_cap_cents": r["effective_cap_cents"],
        "contents_loss_cents": r["contents_loss_cents"],
        "damage_repairable": r["damage_repairable"],
        "contents_damage_cents": r["contents_damage_cents"],
        "repair_payout_cents": r["repair_payout_cents"],
        "root_cause": r["root_cause"],
        "root_cause_station_id": r["root_cause_station_id"],
        "settlement_offer_cents": r["settlement_offer_cents"],
        "amount_payable_cents": r["amount_payable_cents"],
        "expenses_approved_unpaid_cents": r["expenses_approved_unpaid_cents"],
        "expenses_paid_cents": r["expenses_paid_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def tracing_event_view(t):
    return {
        "id": t["id"],
        "report_id": t["report_id"],
        "carrier_id": t["carrier_id"],
        "station_id": t["station_id"],
        "event_type": t["event_type"],
        "occurred_at": t["occurred_at"],
        "notes": t["notes"],
        "created_at": t["created_at"],
    }


def dispatch_view(d):
    return {
        "id": d["id"],
        "report_id": d["report_id"],
        "courier_service_id": d["courier_service_id"],
        "pickup_at": d["pickup_at"],
        "travel_minutes": d["travel_minutes"],
        "delivery_address": d["delivery_address"],
        "attempt_count": d["attempt_count"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def repair_order_view(o):
    return {
        "id": o["id"],
        "report_id": o["report_id"],
        "vendor_id": o["vendor_id"],
        "intake_date": o["intake_date"],
        "promised_date": o["promised_date"],
        "purchase_price_cents": o["purchase_price_cents"],
        "purchase_date": o["purchase_date"],
        "repair_estimate_cents": o["repair_estimate_cents"],
        "depreciated_value_cents": o["depreciated_value_cents"],
        "decision": o["decision"],
        "payout_cents": o["payout_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def expense_claim_view(c):
    return {
        "id": c["id"],
        "report_id": c["report_id"],
        "receipts": c["receipts"],
        "claimed_total_cents": c["claimed_total_cents"],
        "eligible_receipt_count": c["eligible_receipt_count"],
        "reimbursable_total_cents": c["reimbursable_total_cents"],
        "decision_reason": c["decision_reason"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def settlement_payment_view(p):
    return {
        "id": p["id"],
        "report_id": p["report_id"],
        "settlement_component_cents": p["settlement_component_cents"],
        "expense_component_cents": p["expense_component_cents"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# =============================================================================
# Pagination helper
# =============================================================================

def parse_pagination():
    """Parse limit/offset per PRD §2.3. Defaults: limit=10, offset=0; 1<=limit<=100."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc, apply offset/limit, return (page, total_count).

    `sorted` is stable and the store dicts preserve insertion order, so records
    sharing a created_at (common under the fixed logical clock) keep creation
    order deterministically instead of depending on random UUIDs.
    """
    items_sorted = sorted(items, key=lambda r: r["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total


# =============================================================================
# Existence helpers
# =============================================================================

def get_or_404(table: dict, rid: str, name: str):
    if not isinstance(rid, str):
        raise ApiError(ERR_NOT_FOUND, 404, f"{name} not found")
    obj = table.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{name} not found")
    return obj


# =============================================================================
# Business logic helpers
# =============================================================================

def convert_receipt_to_cents(amount_minor: int, currency_code: str) -> int:
    rate = FX_RATE[currency_code]
    val = Decimal(amount_minor) * rate
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_eligible_receipts(report: dict, receipts: list):
    """Return list of receipts inside the eligibility window.

    Window: opened_on <= incurred_on <= min(delivered_on, opened_on + 5 days),
    with delivered_on treated as +infinity when null. Bounds inclusive.
    """
    opened = parse_date(report["opened_on"])
    window_end = opened + timedelta(days=EXPENSE_WINDOW_DAYS)
    if report["delivered_on"] is not None:
        delivered = parse_date(report["delivered_on"])
        if delivered < window_end:
            window_end = delivered
    eligible = []
    for r in receipts:
        try:
            d = parse_date(r["incurred_on"])
        except Exception:
            continue
        if opened <= d <= window_end:
            eligible.append(r)
    return eligible


def compute_reimbursable_total(report: dict, passenger: dict, claim: dict) -> int:
    eligible = compute_eligible_receipts(report, claim["receipts"])
    if report["liability_regime"] == "DOMESTIC":
        daily = {}
        for r in eligible:
            d = r["incurred_on"]
            daily.setdefault(d, 0)
            daily[d] += convert_receipt_to_cents(r["amount_minor"], r["currency_code"])
        cap = TIER_DAILY_CAP[passenger["tier"]]
        total = 0
        for d, amt in daily.items():
            total += min(amt, cap)
        return total
    else:  # MONTREAL
        pooled = 0
        for r in eligible:
            pooled += convert_receipt_to_cents(r["amount_minor"], r["currency_code"])
        return min(pooled, POOL_CAP_CENTS)


def full_years_between(d1: date, d2: date) -> int:
    """Number of full 365-day periods between d1 and d2 (floor(day_diff / 365))."""
    if d2 < d1:
        return 0
    return (d2 - d1).days // 365


def compute_depreciation(purchase_price_cents: int, purchase_date: date, intake_date: date) -> int:
    years = full_years_between(purchase_date, intake_date)
    raw = Decimal(purchase_price_cents) * ((Decimal(1) - DEPRECIATION_RATE) ** years)
    raw_rounded = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    floor = (Decimal(purchase_price_cents) * DEPRECIATION_FLOOR).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(max(raw_rounded, floor))


def dispatch_window(d):
    """Return (start_ms, end_ms) for a dispatch."""
    start = iso_to_ms(d["pickup_at"])
    end = start + d["travel_minutes"] * 60 * 1000
    return start, end


def dispatch_window_conflict(courier: dict, new_start_ms: int, new_end_ms: int, exclude_id=None) -> bool:
    """Buffer-expanded closed-interval conflict check.

    Conflict iff (new_start - buffer) < existing_end AND existing_start < (new_end + buffer).
    """
    buf_ms = courier["turnaround_buffer_minutes"] * 60 * 1000
    for other in STORE.dispatches.values():
        if other["courier_service_id"] != courier["id"]:
            continue
        if other["status"] not in ("DISPATCHED", "FAILED_ATTEMPT"):
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        o_start, o_end = dispatch_window(other)
        if (new_start_ms - buf_ms) < o_end and o_start < (new_end_ms + buf_ms):
            return True
    return False


def vendor_capacity_exceeded(vendor: dict, intake: date, promised: date) -> bool:
    """Check whether adding a new order covering [intake, promised) would push
    occupancy on any day to >= bench_capacity.

    Counts existing orders in INTAKE / REPAIR_IN_PROGRESS / REPLACEMENT_PENDING.
    """
    # Collect existing open orders for this vendor
    intervals = []
    for o in STORE.repair_orders.values():
        if o["vendor_id"] != vendor["id"]:
            continue
        if o["status"] not in ("INTAKE", "REPAIR_IN_PROGRESS", "REPLACEMENT_PENDING"):
            continue
        intervals.append((parse_date(o["intake_date"]), parse_date(o["promised_date"])))

    # Walk days in [intake, promised)
    day = intake
    while day < promised:
        count = 0
        for (s, e) in intervals:
            if s <= day < e:
                count += 1
        # Adding this new order would push the count to count+1
        if count + 1 > vendor["bench_capacity"]:
            return True
        day = day + timedelta(days=1)
    return False


def set_bag_status(bag: dict, new_status: str):
    if bag["status"] != new_status:
        bag["status"] = new_status
        touch(bag)


def set_report_status(report: dict, new_status: str):
    if report["status"] != new_status:
        report["status"] = new_status
        touch(report)


def bump(obj: dict):
    touch(obj)


# =============================================================================
# Route registration
# =============================================================================

def _empty_action_body():
    """For POST action endpoints that take no input. Accepts empty body or empty JSON object."""
    if not request.data:
        return
    # If a body was sent, it must be a JSON object with no fields.
    body = get_json_body()
    ensure_no_unknown_fields(body, set())


def register_routes(app: Flask):

    # =========================================================================
    # Logical clock
    # =========================================================================

    @app.route("/_clock/set_current_utc", methods=["POST"])
    @require_roles("SystemAdmin")
    def set_clock():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"to_iso8601"})
        require_fields(body, ["to_iso8601"])
        as_iso_datetime_str(body["to_iso8601"], "to_iso8601")
        new_ms = iso_to_ms(body["to_iso8601"])
        STORE.current_utc_ms = new_ms

        # Tracing-timeout sweep
        swept = []
        for report in STORE.reports.values():
            if report["status"] != "TRACING":
                continue
            created_ms = iso_to_ms(report["created_at"])
            elapsed_hours = (new_ms - created_ms) / (1000.0 * 3600.0)
            if elapsed_hours < TRACING_TIMEOUT_HOURS:
                continue
            # check LOCATED event
            has_located = any(
                t["report_id"] == report["id"] and t["event_type"] == "LOCATED"
                for t in STORE.tracing_events.values()
            )
            if has_located:
                continue
            # sweep
            set_report_status(report, "DECLARED_LOST")
            bag = STORE.bag_tags.get(report["bag_tag_id"])
            if bag is not None:
                set_bag_status(bag, "CLAIMED_LOST")
            swept.append(report["id"])

        return success_object({
            "current_utc": ms_to_iso(new_ms),
            "swept_report_ids": swept,
        }, 200)

    # =========================================================================
    # Stations
    # =========================================================================

    @app.route("/baggage/stations", methods=["POST"])
    @require_roles("SystemAdmin")
    def create_station():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"station_code", "name", "bags_handled_total"})
        require_fields(body, ["station_code", "name", "bags_handled_total"])
        station_code = as_nonempty_str(body["station_code"], "station_code")
        name = as_nonempty_str(body["name"], "name")
        bags_handled_total = as_int(body["bags_handled_total"], "bags_handled_total", min_value=0)

        if station_code in STORE.station_code_index:
            raise ApiError(ERR_INVALID_REQUEST, 400, "station_code already exists")

        s = {
            "station_code": station_code,
            "name": name,
            "bags_handled_total": bags_handled_total,
            "open_report_count": 0,
            "recovered_bag_count": 0,
            "mishandled_report_count": 0,
        }
        init_system_fields(s)
        STORE.stations[s["id"]] = s
        STORE.station_code_index[station_code] = s["id"]
        return success_object(station_view(s), 201)

    @app.route("/baggage/stations/<sid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_station(sid):
        s = get_or_404(STORE.stations, sid, "Station")
        return success_object(station_view(s), 200)

    @app.route("/baggage/stations", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_stations():
        limit, offset = parse_pagination()
        page, total = paginate(list(STORE.stations.values()), limit, offset)
        return success_list([station_view(s) for s in page], limit, offset, total, 200)

    @app.route("/baggage/stations/<sid>/irregularity-summary", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def station_summary(sid):
        s = get_or_404(STORE.stations, sid, "Station")
        open_count = sum(
            1 for r in STORE.reports.values()
            if r["station_id"] == sid and r["status"] != "CLOSED"
        )
        closed_attr = [
            r for r in STORE.reports.values()
            if r.get("root_cause_station_id") == sid and r["status"] == "CLOSED"
        ]
        mishandled_count = len(closed_attr)
        recovered = sum(
            1 for t in STORE.tracing_events.values()
            if t["station_id"] == sid and t["event_type"] == "LOCATED"
        )
        by_root = {}
        for r in closed_attr:
            rc = r.get("root_cause")
            if rc:
                by_root[rc] = by_root.get(rc, 0) + 1
        if s["bags_handled_total"] == 0:
            rate = 0.0
        else:
            val = Decimal(1000) * Decimal(mishandled_count) / Decimal(s["bags_handled_total"])
            rate = float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return success_object({
            "station_id": sid,
            "open_report_count": open_count,
            "mishandled_report_count": mishandled_count,
            "recovered_bag_count": recovered,
            "by_root_cause": by_root,
            "mishandled_rate_per_1000": rate,
        }, 200)

    # =========================================================================
    # Carriers
    # =========================================================================

    @app.route("/baggage/carriers", methods=["POST"])
    @require_roles("SystemAdmin")
    def create_carrier():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"carrier_code", "name", "is_interline_partner"})
        require_fields(body, ["carrier_code", "name", "is_interline_partner"])
        carrier_code = as_nonempty_str(body["carrier_code"], "carrier_code")
        name = as_nonempty_str(body["name"], "name")
        is_interline_partner = as_bool(body["is_interline_partner"], "is_interline_partner")

        if carrier_code in STORE.carrier_code_index:
            raise ApiError(ERR_INVALID_REQUEST, 400, "carrier_code already exists")

        c = {
            "carrier_code": carrier_code,
            "name": name,
            "is_interline_partner": is_interline_partner,
        }
        init_system_fields(c)
        STORE.carriers[c["id"]] = c
        STORE.carrier_code_index[carrier_code] = c["id"]
        return success_object(carrier_view(c), 201)

    @app.route("/baggage/carriers/<cid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_carrier(cid):
        c = get_or_404(STORE.carriers, cid, "Carrier")
        return success_object(carrier_view(c), 200)

    # =========================================================================
    # Courier Services
    # =========================================================================

    @app.route("/baggage/courier-services", methods=["POST"])
    @require_roles("SystemAdmin")
    def create_courier():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"name", "serves_station_ids", "turnaround_buffer_minutes"})
        require_fields(body, ["name", "serves_station_ids", "turnaround_buffer_minutes"])
        name = as_nonempty_str(body["name"], "name")
        serves = as_str_array(body["serves_station_ids"], "serves_station_ids", allow_empty=True)
        buf = as_int(body["turnaround_buffer_minutes"], "turnaround_buffer_minutes", min_value=0)
        # FK existence
        for sid in serves:
            get_or_404(STORE.stations, sid, "Station")

        c = {
            "name": name,
            "serves_station_ids": list(serves),
            "turnaround_buffer_minutes": buf,
            "active_dispatch_count": 0,
        }
        init_system_fields(c)
        STORE.courier_services[c["id"]] = c
        return success_object(courier_view(c), 201)

    @app.route("/baggage/courier-services/<cid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_courier(cid):
        c = get_or_404(STORE.courier_services, cid, "CourierService")
        return success_object(courier_view(c), 200)

    @app.route("/baggage/courier-services", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_couriers():
        limit, offset = parse_pagination()
        items = list(STORE.courier_services.values())
        station_filter = request.args.get("serves_station_ids")
        if station_filter:
            items = [c for c in items if station_filter in c["serves_station_ids"]]
        page, total = paginate(items, limit, offset)
        return success_list([courier_view(c) for c in page], limit, offset, total, 200)

    # =========================================================================
    # Repair Vendors
    # =========================================================================

    @app.route("/baggage/repair-vendors", methods=["POST"])
    @require_roles("SystemAdmin")
    def create_vendor():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"name", "bench_capacity"})
        require_fields(body, ["name", "bench_capacity"])
        name = as_nonempty_str(body["name"], "name")
        cap = as_int(body["bench_capacity"], "bench_capacity", min_value=1)
        v = {
            "name": name,
            "bench_capacity": cap,
            "occupied_bench_slots": 0,
        }
        init_system_fields(v)
        STORE.repair_vendors[v["id"]] = v
        return success_object(vendor_view(v), 201)

    @app.route("/baggage/repair-vendors/<vid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_vendor(vid):
        v = get_or_404(STORE.repair_vendors, vid, "RepairVendor")
        return success_object(vendor_view(v), 200)

    # =========================================================================
    # Passengers
    # =========================================================================

    @app.route("/baggage/passengers", methods=["POST"])
    @require_roles("BaggageServiceAgent", "SystemAdmin")
    def create_passenger():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"full_name", "email", "tier"})
        require_fields(body, ["full_name", "email"])
        full_name = as_nonempty_str(body["full_name"], "full_name")
        email = as_nonempty_str(body["email"], "email")
        tier = body.get("tier", "STANDARD")
        tier = as_enum(tier, "tier", PASSENGER_TIERS)
        if email in STORE.passenger_email_index:
            raise ApiError(ERR_INVALID_REQUEST, 400, "email already exists")
        p = {
            "full_name": full_name,
            "email": email,
            "tier": tier,
        }
        init_system_fields(p)
        STORE.passengers[p["id"]] = p
        STORE.passenger_email_index[email] = p["id"]
        return success_object(passenger_view(p), 201)

    @app.route("/baggage/passengers/<pid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_passenger(pid):
        p = get_or_404(STORE.passengers, pid, "Passenger")
        return success_object(passenger_view(p), 200)

    # =========================================================================
    # Bag Tags
    # =========================================================================

    @app.route("/baggage/bag-tags", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def create_bag_tag():
        body = get_json_body()
        ensure_no_unknown_fields(body, {
            "tag_number", "passenger_id", "routing_carrier_ids",
            "is_international", "weight_kg", "declared_value_cents",
        })
        require_fields(body, ["tag_number", "passenger_id", "routing_carrier_ids",
                              "is_international", "weight_kg"])
        tag_number = as_tag_number(body["tag_number"])
        passenger_id = as_str(body["passenger_id"], "passenger_id")
        routing = as_str_array(body["routing_carrier_ids"], "routing_carrier_ids", allow_empty=False)
        is_international = as_bool(body["is_international"], "is_international")
        weight_kg = as_int(body["weight_kg"], "weight_kg", min_value=1)
        declared = body.get("declared_value_cents", 0)
        declared = as_int(declared, "declared_value_cents", min_value=0)

        # FK existence (priority 5)
        get_or_404(STORE.passengers, passenger_id, "Passenger")
        for cid in routing:
            get_or_404(STORE.carriers, cid, "Carrier")

        # Uniqueness (priority 9)
        if tag_number in STORE.tag_number_index:
            raise ApiError(ERR_DUPLICATE_TAG_NUMBER, 409, "tag_number already exists")

        # Fiscal cap (priority 10)
        if declared > DECLARED_VALUE_MAX_CENTS:
            raise ApiError(ERR_DECLARED_VALUE_EXCEEDS_MAX, 422,
                           "declared_value_cents exceeds 500000")

        b = {
            "tag_number": tag_number,
            "passenger_id": passenger_id,
            "routing_carrier_ids": list(routing),
            "is_international": is_international,
            "weight_kg": weight_kg,
            "declared_value_cents": declared,
            "status": "CHECKED",
        }
        init_system_fields(b)
        STORE.bag_tags[b["id"]] = b
        STORE.tag_number_index[tag_number] = b["id"]
        return success_object(bag_tag_view(b), 201)

    @app.route("/baggage/bag-tags/<bid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_bag_tag(bid):
        b = get_or_404(STORE.bag_tags, bid, "BagTag")
        return success_object(bag_tag_view(b), 200)

    @app.route("/baggage/bag-tags", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_bag_tags():
        limit, offset = parse_pagination()
        items = list(STORE.bag_tags.values())
        pid = request.args.get("passenger_id")
        if pid:
            items = [b for b in items if b["passenger_id"] == pid]
        cid = request.args.get("routing_carrier_ids")
        if cid:
            items = [b for b in items if cid in b["routing_carrier_ids"]]
        page, total = paginate(items, limit, offset)
        return success_list([bag_tag_view(b) for b in page], limit, offset, total, 200)

    # =========================================================================
    # Irregularity Reports
    # =========================================================================

    @app.route("/baggage/reports", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def create_report():
        body = get_json_body()
        ensure_no_unknown_fields(body, {
            "report_reference", "passenger_id", "bag_tag_id", "station_id", "type",
        })
        require_fields(body, ["report_reference", "passenger_id", "bag_tag_id",
                              "station_id", "type"])
        report_reference = as_nonempty_str(body["report_reference"], "report_reference")
        passenger_id = as_str(body["passenger_id"], "passenger_id")
        bag_tag_id = as_str(body["bag_tag_id"], "bag_tag_id")
        station_id = as_str(body["station_id"], "station_id")
        rtype = as_enum(body["type"], "type", REPORT_TYPES)

        # Existence (priority 5)
        get_or_404(STORE.passengers, passenger_id, "Passenger")
        bag = get_or_404(STORE.bag_tags, bag_tag_id, "BagTag")
        station = get_or_404(STORE.stations, station_id, "Station")

        # Cross-entity referential (priority 7)
        if bag["passenger_id"] != passenger_id:
            raise ApiError(ERR_BAG_PASSENGER_MISMATCH, 409,
                           "passenger_id does not match bag tag's passenger_id")
        for existing in STORE.reports.values():
            if existing["bag_tag_id"] == bag_tag_id and existing["status"] != "CLOSED":
                raise ApiError(ERR_BAG_ALREADY_REPORTED, 409,
                               "Bag tag already has a non-CLOSED report")

        # Uniqueness (priority 9)
        if report_reference in STORE.report_reference_index:
            raise ApiError(ERR_DUPLICATE_REPORT_REFERENCE, 409,
                           "report_reference already exists")

        # Compute liability
        if bag["is_international"]:
            base_cap = MONTREAL_CAP_CENTS
            regime = "MONTREAL"
        else:
            base_cap = bag["weight_kg"] * DOMESTIC_PER_KG_CENTS
            regime = "DOMESTIC"
        effective_cap = max(base_cap, bag["declared_value_cents"])
        liable_carrier_id = bag["routing_carrier_ids"][-1]

        r = {
            "report_reference": report_reference,
            "passenger_id": passenger_id,
            "bag_tag_id": bag_tag_id,
            "station_id": station_id,
            "type": rtype,
            "status": "OPEN",
            "opened_on": None,  # set after created_at
            "delivered_on": None,
            "liability_regime": regime,
            "liable_carrier_id": liable_carrier_id,
            "effective_cap_cents": effective_cap,
            "contents_loss_cents": None,
            "damage_repairable": None,
            "contents_damage_cents": None,
            "repair_payout_cents": 0,
            "root_cause": None,
            "root_cause_station_id": None,
            "settlement_offer_cents": None,
            "amount_payable_cents": 0,
            "expenses_approved_unpaid_cents": 0,
            "expenses_paid_cents": 0,
            "claim_path": None,
        }
        init_system_fields(r)
        # opened_on = date portion of created_at
        r["opened_on"] = date_iso(date_of_ms(iso_to_ms(r["created_at"])))

        # auto-transition
        if rtype == "DELAYED":
            r["status"] = "TRACING"
            r["claim_path"] = "DELAYED"
            set_bag_status(bag, "MISHANDLED")
        else:  # DAMAGED / PILFERED
            r["status"] = "DAMAGE_REVIEW"
            r["claim_path"] = rtype
            set_bag_status(bag, "DELIVERED_DAMAGED")

        # Station counter
        station["open_report_count"] += 1
        touch(station)

        STORE.reports[r["id"]] = r
        STORE.report_reference_index[report_reference] = r["id"]
        return success_object(report_view(r), 201)

    @app.route("/baggage/reports/<rid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_report(rid):
        r = get_or_404(STORE.reports, rid, "IrregularityReport")
        return success_object(report_view(r), 200)

    @app.route("/baggage/reports", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_reports():
        limit, offset = parse_pagination()
        items = list(STORE.reports.values())
        for param in ("station_id", "passenger_id", "bag_tag_id",
                      "liable_carrier_id", "root_cause_station_id", "status"):
            val = request.args.get(param)
            if val is not None:
                items = [r for r in items if r.get(param) == val]
        page, total = paginate(items, limit, offset)
        return success_list([report_view(r) for r in page], limit, offset, total, 200)

    # =========================================================================
    # Tracing Events
    # =========================================================================

    @app.route("/baggage/reports/<rid>/tracing-events", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def create_tracing_event(rid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {
            "carrier_id", "station_id", "event_type", "occurred_at", "notes",
        })
        require_fields(body, ["carrier_id", "station_id", "event_type"])
        carrier_id = as_str(body["carrier_id"], "carrier_id")
        station_id = as_str(body["station_id"], "station_id")
        event_type = as_enum(body["event_type"], "event_type", TRACING_EVENT_TYPES)
        notes = body.get("notes", "")
        if not isinstance(notes, str):
            bad_request("notes must be a string")
        occurred_at_raw = body.get("occurred_at")
        if occurred_at_raw is not None:
            as_iso_datetime_str(occurred_at_raw, "occurred_at")

        # Existence
        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        get_or_404(STORE.carriers, carrier_id, "Carrier")
        station = get_or_404(STORE.stations, station_id, "Station")

        # State (priority 6): report must be TRACING
        if report["status"] != "TRACING":
            raise ApiError(ERR_REPORT_NOT_TRACING, 409,
                           "Report is not in TRACING status")

        occurred_ms = iso_to_ms(occurred_at_raw) if occurred_at_raw else current_clock_ms()
        occurred_iso = ms_to_iso(occurred_ms)

        t = {
            "id": new_resource_id(),
            "report_id": rid,
            "carrier_id": carrier_id,
            "station_id": station_id,
            "event_type": event_type,
            "occurred_at": occurred_iso,
            "notes": notes,
            "created_at": occurred_iso,
        }
        STORE.tracing_events[t["id"]] = t

        # LOCATED cascade
        if event_type == "LOCATED":
            set_report_status(report, "FOUND_PENDING_DELIVERY")
            bag = STORE.bag_tags.get(report["bag_tag_id"])
            if bag is not None:
                set_bag_status(bag, "IN_RECOVERY")
            station["recovered_bag_count"] += 1
            touch(station)

        return success_object(tracing_event_view(t), 201)

    @app.route("/baggage/tracing-events/<tid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_tracing_event(tid):
        t = get_or_404(STORE.tracing_events, tid, "TracingEvent")
        return success_object(tracing_event_view(t), 200)

    @app.route("/baggage/tracing-events", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_tracing_events():
        limit, offset = parse_pagination()
        items = list(STORE.tracing_events.values())
        for param in ("report_id", "carrier_id", "station_id", "event_type"):
            val = request.args.get(param)
            if val is not None:
                items = [t for t in items if t.get(param) == val]
        page, total = paginate(items, limit, offset)
        return success_list([tracing_event_view(t) for t in page], limit, offset, total, 200)

    # =========================================================================
    # Damage / loss assessment + claim review entry
    # =========================================================================

    @app.route("/baggage/reports/<rid>/assess-loss", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def assess_loss(rid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"contents_loss_cents"})
        require_fields(body, ["contents_loss_cents"])
        contents_loss = as_int(body["contents_loss_cents"], "contents_loss_cents", min_value=0)
        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        if report["status"] != "DECLARED_LOST":
            raise ApiError(ERR_REPORT_NOT_DECLARED_LOST, 409,
                           "Report is not in DECLARED_LOST")
        report["contents_loss_cents"] = contents_loss
        report["claim_path"] = "DECLARED_LOST"
        set_report_status(report, "CLAIM_REVIEW")
        return success_object(report_view(report), 200)

    @app.route("/baggage/reports/<rid>/assess-damage", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def assess_damage(rid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"repairable", "contents_damage_cents"})
        require_fields(body, ["repairable"])
        repairable = as_bool(body["repairable"], "repairable")
        contents_damage = body.get("contents_damage_cents", 0)
        contents_damage = as_int(contents_damage, "contents_damage_cents", min_value=0)

        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        if report["status"] != "DAMAGE_REVIEW":
            raise ApiError(ERR_REPORT_NOT_IN_DAMAGE_REVIEW, 409,
                           "Report is not in DAMAGE_REVIEW")
        report["damage_repairable"] = repairable
        report["contents_damage_cents"] = contents_damage
        if not repairable:
            # claim_path already set at creation (DAMAGED or PILFERED)
            set_report_status(report, "CLAIM_REVIEW")
        else:
            touch(report)
        return success_object(report_view(report), 200)

    @app.route("/baggage/reports/<rid>/open-claim-review", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def open_claim_review(rid):
        _empty_action_body()
        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        if report["status"] != "DELIVERED":
            raise ApiError(ERR_REPORT_NOT_DELIVERED, 409,
                           "Report is not in DELIVERED")
        # claim_path already "DELAYED" from creation
        set_report_status(report, "CLAIM_REVIEW")
        return success_object(report_view(report), 200)

    @app.route("/baggage/reports/<rid>/offer-settlement", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def offer_settlement(rid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"root_cause", "root_cause_station_id"})
        require_fields(body, ["root_cause", "root_cause_station_id"])
        root_cause = as_enum(body["root_cause"], "root_cause", ROOT_CAUSES)
        rcs_id = as_str(body["root_cause_station_id"], "root_cause_station_id")

        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        get_or_404(STORE.stations, rcs_id, "Station")

        if report["status"] != "CLAIM_REVIEW":
            raise ApiError(ERR_REPORT_NOT_IN_CLAIM_REVIEW, 409,
                           "Report is not in CLAIM_REVIEW")

        # Compute settlement_offer per pinned evaluation order
        if report["claim_path"] == "DECLARED_LOST":
            loss_basis = report["contents_loss_cents"] or 0
        elif report["type"] == "DAMAGED":
            loss_basis = (report["repair_payout_cents"] or 0) + (report["contents_damage_cents"] or 0)
        elif report["type"] == "PILFERED":
            loss_basis = report["contents_damage_cents"] or 0
        else:  # DELAYED delivered
            loss_basis = 0
        offer = min(report["effective_cap_cents"], loss_basis)

        report["settlement_offer_cents"] = offer
        report["root_cause"] = root_cause
        report["root_cause_station_id"] = rcs_id
        report["amount_payable_cents"] = offer
        set_report_status(report, "SETTLEMENT_OFFERED")
        return success_object(report_view(report), 200)

    @app.route("/baggage/reports/<rid>/accept-settlement", methods=["POST"])
    @require_roles("Passenger")
    def accept_settlement(rid):
        _empty_action_body()
        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        # Ownership check (priority 3, but PRD orders ownership before existence)
        # Per PRD §2.10 the ownership check is priority 3, applied before existence.
        # However we need the report to exist to evaluate ownership. We accept the
        # standard interpretation: check existence first (path id must resolve) then
        # ownership. PRD's "first failing check" means if both fail we return
        # the higher-priority one; here, if the report doesn't exist we 404.
        if request.auth_user_id != report["passenger_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                           "X-User-ID does not match report passenger_id")
        if report["status"] != "SETTLEMENT_OFFERED":
            raise ApiError(ERR_SETTLEMENT_NOT_OFFERED, 409,
                           "Report is not in SETTLEMENT_OFFERED")
        set_report_status(report, "SETTLEMENT_ACCEPTED")
        return success_object(report_view(report), 200)

    @app.route("/baggage/reports/<rid>/reject-settlement", methods=["POST"])
    @require_roles("Passenger")
    def reject_settlement(rid):
        _empty_action_body()
        report = get_or_404(STORE.reports, rid, "IrregularityReport")
        if request.auth_user_id != report["passenger_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                           "X-User-ID does not match report passenger_id")
        if report["status"] != "SETTLEMENT_OFFERED":
            raise ApiError(ERR_SETTLEMENT_NOT_OFFERED, 409,
                           "Report is not in SETTLEMENT_OFFERED")
        report["settlement_offer_cents"] = None
        report["root_cause"] = None
        report["root_cause_station_id"] = None
        report["amount_payable_cents"] = 0
        set_report_status(report, "CLAIM_REVIEW")
        return success_object(report_view(report), 200)

    # =========================================================================
    # Settlement Payments
    # =========================================================================

    @app.route("/baggage/reports/<rid>/settlement-payments", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def create_settlement_payment(rid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"expected_report_version"})
        require_fields(body, ["expected_report_version"])
        expected = as_int(body["expected_report_version"], "expected_report_version", min_value=0)

        report = get_or_404(STORE.reports, rid, "IrregularityReport")

        # State check first (priority 6, machine-state first then OCC)
        if report["status"] != "SETTLEMENT_ACCEPTED":
            raise ApiError(ERR_SETTLEMENT_NOT_PAYABLE, 409,
                           "Report is not in SETTLEMENT_ACCEPTED")
        if report["version"] != expected:
            raise ApiError(ERR_STALE_REPORT_VERSION, 412,
                           "expected_report_version does not match current report version")

        # Cross-entity referential (priority 7): no SUBMITTED claims
        has_submitted = any(
            c["report_id"] == rid and c["status"] == "SUBMITTED"
            for c in STORE.expense_claims.values()
        )
        if has_submitted:
            raise ApiError(ERR_UNADJUDICATED_EXPENSE_CLAIMS, 409,
                           "Report has SUBMITTED expense claims")

        # Uniqueness (priority 9): at most one ISSUED payment
        for p in STORE.settlement_payments.values():
            if p["report_id"] == rid and p["status"] == "ISSUED":
                raise ApiError(ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS, 409,
                               "Report already has an ISSUED settlement payment")

        # Compute components
        settlement_component = report["amount_payable_cents"]
        earmarked = [
            c for c in STORE.expense_claims.values()
            if c["report_id"] == rid and c["status"] == "APPROVED"
        ]
        expense_component = sum(c["reimbursable_total_cents"] or 0 for c in earmarked)
        amount = settlement_component + expense_component

        p = {
            "report_id": rid,
            "settlement_component_cents": settlement_component,
            "expense_component_cents": expense_component,
            "amount_cents": amount,
            "status": "ISSUED",
        }
        init_system_fields(p)
        STORE.settlement_payments[p["id"]] = p

        # Mutate claims -> SETTLEMENT_EARMARKED
        for c in earmarked:
            c["status"] = "SETTLEMENT_EARMARKED"
            touch(c)

        # Mutate report: reduce payable, bump version
        report["amount_payable_cents"] -= settlement_component
        touch(report)

        return success_object(settlement_payment_view(p), 201)

    @app.route("/baggage/settlement-payments/<pid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_settlement_payment(pid):
        p = get_or_404(STORE.settlement_payments, pid, "SettlementPayment")
        return success_object(settlement_payment_view(p), 200)

    @app.route("/baggage/settlement-payments", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_settlement_payments():
        limit, offset = parse_pagination()
        items = list(STORE.settlement_payments.values())
        rid = request.args.get("report_id")
        if rid:
            items = [p for p in items if p["report_id"] == rid]
        st = request.args.get("status")
        if st:
            items = [p for p in items if p["status"] == st]
        page, total = paginate(items, limit, offset)
        return success_list([settlement_payment_view(p) for p in page], limit, offset, total, 200)

    @app.route("/baggage/settlement-payments/<pid>/mark-paid", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def mark_payment_paid(pid):
        _empty_action_body()
        p = get_or_404(STORE.settlement_payments, pid, "SettlementPayment")
        if p["status"] != "ISSUED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Payment is not in ISSUED status")
        p["status"] = "PAID"
        touch(p)

        report = STORE.reports.get(p["report_id"])
        if report is not None:
            # Move earmarked claims to PAID
            for c in STORE.expense_claims.values():
                if c["report_id"] == report["id"] and c["status"] == "SETTLEMENT_EARMARKED":
                    c["status"] = "PAID"
                    touch(c)
            report["expenses_paid_cents"] += p["expense_component_cents"]
            report["expenses_approved_unpaid_cents"] -= p["expense_component_cents"]
            set_report_status(report, "CLOSED")

            # Station counters
            rcs_id = report.get("root_cause_station_id")
            if rcs_id:
                rs = STORE.stations.get(rcs_id)
                if rs is not None:
                    rs["mishandled_report_count"] += 1
                    touch(rs)
            fs = STORE.stations.get(report["station_id"])
            if fs is not None:
                fs["open_report_count"] -= 1
                touch(fs)

        return success_object(settlement_payment_view(p), 200)

    @app.route("/baggage/settlement-payments/<pid>/void", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def void_payment(pid):
        _empty_action_body()
        p = get_or_404(STORE.settlement_payments, pid, "SettlementPayment")
        if p["status"] != "ISSUED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Payment is not in ISSUED status")
        p["status"] = "VOIDED"
        touch(p)

        report = STORE.reports.get(p["report_id"])
        if report is not None:
            report["amount_payable_cents"] += p["settlement_component_cents"]
            for c in STORE.expense_claims.values():
                if c["report_id"] == report["id"] and c["status"] == "SETTLEMENT_EARMARKED":
                    c["status"] = "APPROVED"
                    touch(c)
            touch(report)

        return success_object(settlement_payment_view(p), 200)

    # =========================================================================
    # Delivery Dispatches
    # =========================================================================

    @app.route("/baggage/dispatches", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def create_dispatch():
        body = get_json_body()
        ensure_no_unknown_fields(body, {
            "report_id", "courier_service_id", "pickup_at", "travel_minutes", "delivery_address",
        })
        require_fields(body, ["report_id", "courier_service_id", "pickup_at",
                              "travel_minutes", "delivery_address"])
        report_id = as_str(body["report_id"], "report_id")
        courier_id = as_str(body["courier_service_id"], "courier_service_id")
        pickup_at = as_iso_datetime_str(body["pickup_at"], "pickup_at")
        travel_minutes = as_int(body["travel_minutes"], "travel_minutes", min_value=1)
        delivery_address = as_nonempty_str(body["delivery_address"], "delivery_address")

        # Existence
        report = get_or_404(STORE.reports, report_id, "IrregularityReport")
        courier = get_or_404(STORE.courier_services, courier_id, "CourierService")

        # State
        if report["status"] != "FOUND_PENDING_DELIVERY":
            raise ApiError(ERR_REPORT_NOT_AWAITING_DELIVERY, 409,
                           "Report is not in FOUND_PENDING_DELIVERY")

        # Cross-entity referential: courier serves filing station
        if report["station_id"] not in courier["serves_station_ids"]:
            raise ApiError(ERR_COURIER_ZONE_MISMATCH, 409,
                           "Courier does not serve the report's filing station")

        # Temporal: pickup_at >= now
        pickup_ms = iso_to_ms(pickup_at)
        if pickup_ms < current_clock_ms():
            raise ApiError(ERR_PICKUP_IN_PAST, 409,
                           "pickup_at is before the current logical clock")

        # Temporal: window conflict
        end_ms = pickup_ms + travel_minutes * 60 * 1000
        if dispatch_window_conflict(courier, pickup_ms, end_ms):
            raise ApiError(ERR_DISPATCH_WINDOW_CONFLICT, 409,
                           "Dispatch window conflicts with an existing dispatch")

        d = {
            "report_id": report_id,
            "courier_service_id": courier_id,
            "pickup_at": ms_to_iso(pickup_ms),
            "travel_minutes": travel_minutes,
            "delivery_address": delivery_address,
            "attempt_count": 1,
            "status": "DISPATCHED",
        }
        init_system_fields(d)
        STORE.dispatches[d["id"]] = d

        courier["active_dispatch_count"] += 1
        touch(courier)
        set_report_status(report, "DELIVERY_IN_PROGRESS")

        return success_object(dispatch_view(d), 201)

    @app.route("/baggage/dispatches/<did>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_dispatch(did):
        d = get_or_404(STORE.dispatches, did, "DeliveryDispatch")
        return success_object(dispatch_view(d), 200)

    @app.route("/baggage/dispatches", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_dispatches():
        limit, offset = parse_pagination()
        items = list(STORE.dispatches.values())
        rid = request.args.get("report_id")
        if rid:
            items = [d for d in items if d["report_id"] == rid]
        cid = request.args.get("courier_service_id")
        if cid:
            items = [d for d in items if d["courier_service_id"] == cid]
        st = request.args.get("status")
        if st:
            items = [d for d in items if d["status"] == st]
        page, total = paginate(items, limit, offset)
        return success_list([dispatch_view(d) for d in page], limit, offset, total, 200)

    @app.route("/baggage/dispatches/<did>/mark-delivered", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def mark_delivered(did):
        _empty_action_body()
        d = get_or_404(STORE.dispatches, did, "DeliveryDispatch")
        if d["status"] != "DISPATCHED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Dispatch is not in DISPATCHED status")
        d["status"] = "DELIVERED"
        touch(d)

        courier = STORE.courier_services.get(d["courier_service_id"])
        if courier is not None:
            courier["active_dispatch_count"] -= 1
            touch(courier)

        report = STORE.reports.get(d["report_id"])
        if report is not None:
            report["delivered_on"] = date_iso(date_of_ms(current_clock_ms()))
            set_report_status(report, "DELIVERED")
            bag = STORE.bag_tags.get(report["bag_tag_id"])
            if bag is not None:
                set_bag_status(bag, "DELIVERED")

        return success_object(dispatch_view(d), 200)

    @app.route("/baggage/dispatches/<did>/mark-failed", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def mark_failed(did):
        _empty_action_body()
        d = get_or_404(STORE.dispatches, did, "DeliveryDispatch")
        if d["status"] != "DISPATCHED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Dispatch is not in DISPATCHED status")

        if d["attempt_count"] >= 3:
            # permanent
            d["status"] = "FAILED_PERMANENT"
            touch(d)
            courier = STORE.courier_services.get(d["courier_service_id"])
            if courier is not None:
                courier["active_dispatch_count"] -= 1
                touch(courier)
            report = STORE.reports.get(d["report_id"])
            if report is not None:
                set_report_status(report, "FOUND_PENDING_DELIVERY")
        else:
            d["status"] = "FAILED_ATTEMPT"
            touch(d)

        return success_object(dispatch_view(d), 200)

    @app.route("/baggage/dispatches/<did>/reschedule", methods=["POST"])
    @require_roles("BaggageServiceAgent")
    def reschedule_dispatch(did):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"new_pickup_at"})
        require_fields(body, ["new_pickup_at"])
        new_pickup_at = as_iso_datetime_str(body["new_pickup_at"], "new_pickup_at")

        d = get_or_404(STORE.dispatches, did, "DeliveryDispatch")
        if d["status"] != "FAILED_ATTEMPT":
            raise ApiError(ERR_DISPATCH_NOT_RESCHEDULABLE, 409,
                           "Dispatch is not in FAILED_ATTEMPT")
        new_ms = iso_to_ms(new_pickup_at)
        if new_ms < current_clock_ms():
            raise ApiError(ERR_PICKUP_IN_PAST, 409,
                           "new_pickup_at is before the current logical clock")
        courier = STORE.courier_services.get(d["courier_service_id"])
        if courier is not None:
            end_ms = new_ms + d["travel_minutes"] * 60 * 1000
            if dispatch_window_conflict(courier, new_ms, end_ms, exclude_id=d["id"]):
                raise ApiError(ERR_DISPATCH_WINDOW_CONFLICT, 409,
                               "Dispatch window conflicts with an existing dispatch")
        d["pickup_at"] = ms_to_iso(new_ms)
        d["attempt_count"] += 1
        d["status"] = "DISPATCHED"
        touch(d)
        return success_object(dispatch_view(d), 200)

    # =========================================================================
    # Repair Orders
    # =========================================================================

    @app.route("/baggage/repair-orders", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def create_repair_order():
        body = get_json_body()
        ensure_no_unknown_fields(body, {
            "report_id", "vendor_id", "intake_date", "promised_date",
            "purchase_price_cents", "purchase_date", "repair_estimate_cents",
        })
        require_fields(body, ["report_id", "vendor_id", "intake_date", "promised_date",
                              "purchase_price_cents", "purchase_date", "repair_estimate_cents"])
        report_id = as_str(body["report_id"], "report_id")
        vendor_id = as_str(body["vendor_id"], "vendor_id")
        intake_date_s = as_date_str(body["intake_date"], "intake_date")
        promised_date_s = as_date_str(body["promised_date"], "promised_date")
        purchase_price = as_int(body["purchase_price_cents"], "purchase_price_cents", min_value=0)
        purchase_date_s = as_date_str(body["purchase_date"], "purchase_date")
        repair_estimate = as_int(body["repair_estimate_cents"], "repair_estimate_cents", min_value=0)

        # Existence
        report = get_or_404(STORE.reports, report_id, "IrregularityReport")
        vendor = get_or_404(STORE.repair_vendors, vendor_id, "RepairVendor")

        # State check (priority 6): report must be in DAMAGE_REVIEW
        if report["status"] != "DAMAGE_REVIEW":
            raise ApiError(ERR_REPORT_NOT_IN_DAMAGE_REVIEW, 409,
                           "Report is not in DAMAGE_REVIEW")

        # Cross-entity (priority 7): DAMAGED + damage_repairable == True
        if report["type"] != "DAMAGED" or report["damage_repairable"] is not True:
            raise ApiError(ERR_REPAIR_NOT_ALLOWED_FOR_TYPE, 409,
                           "Repair orders allowed only for DAMAGED reports with damage_repairable=true")

        # Temporal (priority 8): vendor capacity
        intake_d = parse_date(intake_date_s)
        promised_d = parse_date(promised_date_s)
        purchase_d = parse_date(purchase_date_s)
        if vendor_capacity_exceeded(vendor, intake_d, promised_d):
            raise ApiError(ERR_VENDOR_CAPACITY_EXCEEDED, 409,
                           "Vendor bench capacity would be exceeded")

        # Structural (priority 9): window validity
        if promised_d <= intake_d or purchase_d > intake_d:
            raise ApiError(ERR_REPAIR_WINDOW_INVALID, 422,
                           "Invalid repair window dates")

        o = {
            "report_id": report_id,
            "vendor_id": vendor_id,
            "intake_date": intake_date_s,
            "promised_date": promised_date_s,
            "purchase_price_cents": purchase_price,
            "purchase_date": purchase_date_s,
            "repair_estimate_cents": repair_estimate,
            "depreciated_value_cents": None,
            "decision": None,
            "payout_cents": None,
            "status": "INTAKE",
        }
        init_system_fields(o)
        STORE.repair_orders[o["id"]] = o

        vendor["occupied_bench_slots"] += 1
        touch(vendor)

        return success_object(repair_order_view(o), 201)

    @app.route("/baggage/repair-orders/<oid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_repair_order(oid):
        o = get_or_404(STORE.repair_orders, oid, "RepairOrder")
        return success_object(repair_order_view(o), 200)

    @app.route("/baggage/repair-orders", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_repair_orders():
        limit, offset = parse_pagination()
        items = list(STORE.repair_orders.values())
        rid = request.args.get("report_id")
        if rid:
            items = [o for o in items if o["report_id"] == rid]
        vid = request.args.get("vendor_id")
        if vid:
            items = [o for o in items if o["vendor_id"] == vid]
        st = request.args.get("status")
        if st:
            items = [o for o in items if o["status"] == st]
        page, total = paginate(items, limit, offset)
        return success_list([repair_order_view(o) for o in page], limit, offset, total, 200)

    @app.route("/baggage/repair-orders/<oid>/decide", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def decide_repair_order(oid):
        _empty_action_body()
        o = get_or_404(STORE.repair_orders, oid, "RepairOrder")
        if o["status"] != "INTAKE":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Repair order is not in INTAKE")

        purchase_d = parse_date(o["purchase_date"])
        intake_d = parse_date(o["intake_date"])
        dep = compute_depreciation(o["purchase_price_cents"], purchase_d, intake_d)
        o["depreciated_value_cents"] = dep

        threshold = (Decimal(dep) * REPLACE_THRESHOLD)
        if Decimal(o["repair_estimate_cents"]) < threshold:
            o["decision"] = "REPAIR"
            o["status"] = "REPAIR_IN_PROGRESS"
        else:
            o["decision"] = "REPLACE"
            o["status"] = "REPLACEMENT_PENDING"
        touch(o)
        return success_object(repair_order_view(o), 200)

    @app.route("/baggage/repair-orders/<oid>/complete", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def complete_repair_order(oid):
        _empty_action_body()
        o = get_or_404(STORE.repair_orders, oid, "RepairOrder")
        if o["status"] not in ("REPAIR_IN_PROGRESS", "REPLACEMENT_PENDING"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Repair order is not in a completable state")

        if o["status"] == "REPAIR_IN_PROGRESS":
            o["payout_cents"] = min(o["repair_estimate_cents"], o["depreciated_value_cents"])
            o["status"] = "REPAIR_SETTLED"
        else:
            o["payout_cents"] = o["depreciated_value_cents"]
            o["status"] = "REPLACE_SETTLED"
        touch(o)

        # Release vendor slot
        vendor = STORE.repair_vendors.get(o["vendor_id"])
        if vendor is not None:
            vendor["occupied_bench_slots"] -= 1
            touch(vendor)

        # Cascade to report
        report = STORE.reports.get(o["report_id"])
        if report is not None and report["status"] == "DAMAGE_REVIEW":
            report["repair_payout_cents"] = o["payout_cents"]
            set_report_status(report, "CLAIM_REVIEW")
            # Cancel other open repair orders for this report
            for other in STORE.repair_orders.values():
                if other["id"] == o["id"]:
                    continue
                if other["report_id"] != report["id"]:
                    continue
                if other["status"] in ("INTAKE", "REPAIR_IN_PROGRESS", "REPLACEMENT_PENDING"):
                    other["status"] = "CANCELLED"
                    touch(other)
                    ov = STORE.repair_vendors.get(other["vendor_id"])
                    if ov is not None:
                        ov["occupied_bench_slots"] -= 1
                        touch(ov)

        return success_object(repair_order_view(o), 200)

    # =========================================================================
    # Expense Claims
    # =========================================================================

    @app.route("/baggage/expense-claims", methods=["POST"])
    @require_roles("Passenger")
    def create_expense_claim():
        body = get_json_body()
        ensure_no_unknown_fields(body, {"report_id", "receipts"})
        require_fields(body, ["report_id", "receipts"])
        report_id = as_str(body["report_id"], "report_id")
        receipts = body["receipts"]
        if not isinstance(receipts, list) or len(receipts) == 0:
            bad_request("receipts must be a non-empty array")
        cleaned = []
        for i, r in enumerate(receipts):
            if not isinstance(r, dict):
                bad_request(f"receipts[{i}] must be an object")
            extra = set(r.keys()) - {"incurred_on", "description", "amount_minor", "currency_code"}
            if extra:
                bad_request(f"receipts[{i}] has unknown fields: {sorted(extra)}")
            for k in ("incurred_on", "description", "amount_minor", "currency_code"):
                if k not in r:
                    bad_request(f"receipts[{i}] missing field {k}")
            incurred = as_date_str(r["incurred_on"], f"receipts[{i}].incurred_on")
            desc = r["description"]
            if not isinstance(desc, str):
                bad_request(f"receipts[{i}].description must be a string")
            amt = as_int(r["amount_minor"], f"receipts[{i}].amount_minor", min_value=1)
            cur = as_enum(r["currency_code"], f"receipts[{i}].currency_code", CURRENCIES)
            cleaned.append({
                "incurred_on": incurred,
                "description": desc,
                "amount_minor": amt,
                "currency_code": cur,
            })

        # Existence
        report = get_or_404(STORE.reports, report_id, "IrregularityReport")

        # Ownership (Passenger-scoped) — must match report.passenger_id
        if request.auth_user_id != report["passenger_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                           "X-User-ID does not match report passenger_id")

        # State: DELAYED + expense-accepting status
        if report["type"] != "DELAYED" or report["status"] not in REPORT_EXPENSE_ACCEPTING:
            raise ApiError(ERR_REPORT_NOT_ACCEPTING_EXPENSES, 409,
                           "Report is not accepting expense claims")

        # Compute claimed_total_cents
        claimed_total = 0
        for r in cleaned:
            claimed_total += convert_receipt_to_cents(r["amount_minor"], r["currency_code"])

        # Eligible count
        eligible = compute_eligible_receipts(report, cleaned)
        eligible_count = len(eligible)

        # Fiscal cap (priority 10)
        if claimed_total > EXPENSE_CLAIM_MAX_CENTS:
            raise ApiError(ERR_EXPENSE_CLAIM_OVER_MAX, 422,
                           "claimed_total_cents exceeds 300000")

        c = {
            "report_id": report_id,
            "receipts": cleaned,
            "claimed_total_cents": claimed_total,
            "eligible_receipt_count": eligible_count,
            "reimbursable_total_cents": None,
            "decision_reason": None,
            "status": "SUBMITTED",
        }
        init_system_fields(c)
        STORE.expense_claims[c["id"]] = c
        return success_object(expense_claim_view(c), 201)

    @app.route("/baggage/expense-claims/<cid>", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def get_expense_claim(cid):
        c = get_or_404(STORE.expense_claims, cid, "ExpenseClaim")
        return success_object(expense_claim_view(c), 200)

    @app.route("/baggage/expense-claims", methods=["GET"])
    @require_roles("SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger")
    def list_expense_claims():
        limit, offset = parse_pagination()
        items = list(STORE.expense_claims.values())
        rid = request.args.get("report_id")
        if rid:
            items = [c for c in items if c["report_id"] == rid]
        st = request.args.get("status")
        if st:
            items = [c for c in items if c["status"] == st]
        page, total = paginate(items, limit, offset)
        return success_list([expense_claim_view(c) for c in page], limit, offset, total, 200)

    @app.route("/baggage/expense-claims/<cid>/adjudicate", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def adjudicate_claim(cid):
        body = get_json_body()
        ensure_no_unknown_fields(body, {"decision", "reject_reason"})
        require_fields(body, ["decision"])
        decision = as_enum(body["decision"], "decision", {"APPROVE", "REJECT"})
        reject_reason = body.get("reject_reason")
        if reject_reason is not None and not isinstance(reject_reason, str):
            bad_request("reject_reason must be a string")

        c = get_or_404(STORE.expense_claims, cid, "ExpenseClaim")
        if c["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Claim is not in SUBMITTED status")

        if decision == "REJECT":
            c["decision_reason"] = reject_reason
            c["status"] = "REJECTED"
            touch(c)
        else:
            report = STORE.reports.get(c["report_id"])
            passenger = STORE.passengers.get(report["passenger_id"]) if report else None
            reimb = compute_reimbursable_total(report, passenger, c) if report and passenger else 0
            c["reimbursable_total_cents"] = reimb
            c["status"] = "APPROVED"
            touch(c)
            if report is not None:
                report["expenses_approved_unpaid_cents"] += reimb
                touch(report)

        return success_object(expense_claim_view(c), 200)

    @app.route("/baggage/expense-claims/<cid>/pay", methods=["POST"])
    @require_roles("ClaimsAdjuster")
    def pay_claim(cid):
        _empty_action_body()
        c = get_or_404(STORE.expense_claims, cid, "ExpenseClaim")
        if c["status"] != "APPROVED":
            raise ApiError(ERR_CLAIM_NOT_PAYABLE, 409,
                           "Claim is not in APPROVED status")
        report = STORE.reports.get(c["report_id"])
        if report is not None and report["status"] == "CLOSED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           "Report is CLOSED")
        c["status"] = "PAID"
        touch(c)
        if report is not None:
            amt = c["reimbursable_total_cents"] or 0
            report["expenses_approved_unpaid_cents"] -= amt
            report["expenses_paid_cents"] += amt
            touch(report)
        return success_object(expense_claim_view(c), 200)


# =============================================================================
# Main
# =============================================================================

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
