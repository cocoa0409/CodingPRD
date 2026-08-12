"""Shared domain helpers: serialization, pagination, aggregate recomputation,
and the calculations from scaffold §1.3.

Money is always integer cents; intermediate dollar->cent multiplications use
Decimal with ROUND_HALF_UP. Unit prices in the defect formula round half-up
to four decimal places.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, now_iso, clock_now
from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND

# ---------------------------------------------------------------------------
# Calculation constants (scaffold §1.3)
# ---------------------------------------------------------------------------
DEFECT_TOLERANCE_PCT = Decimal("5")
OT_THRESHOLD_HOURS = Decimal("8")
OT_MULTIPLIER = Decimal("1.5")
MIN_WAGE_DOLLARS = Decimal("15.00")
PALLET_DEPOSIT_CENTS = 2500
EARLY_PAY_DISCOUNT_PCT = Decimal("0.02")
DISCOUNT_DAYS = 5
TRUST_CLAIM_GRACE_DAYS = 30

CENT = Decimal("1")
PRICE4 = Decimal("0.0001")


def round_half_up_cents(value):
    """Decimal dollar amount -> integer cents, half-up."""
    return int((value * 100).quantize(CENT, rounding=ROUND_HALF_UP))


def round_half_up(value, quantum=CENT):
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Bump updated_at + version on a common-fields entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity, common=True):
    """Initialize id / created_at / updated_at / version on a fresh entity."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    if common:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# Aggregate recomputation (scaffold §1.3: credit_exposure,
# lot_payable_reconciliation, shipper_trust_exposure)
# ---------------------------------------------------------------------------

TRUST_EXPOSURE_LOT_STATUSES = {"ORDERED", "RECEIVED", "INSPECTED", "DISPUTED", "ACCEPTED"}
CREDIT_EXPOSURE_INVOICE_STATUSES = {"OPEN", "PAST_DUE", "TRUST_CLAIMED"}
CREDIT_EXPOSURE_ORDER_STATUSES = {"CONFIRMED", "ON_HOLD", "PICKED", "DELIVERED"}


def recompute_shipper_trust_exposure(shipper_id):
    shipper = store.shippers.get(shipper_id)
    if shipper is None:
        return
    total = 0
    for lot in store.purchase_lots.values():
        if lot["shipper_id"] == shipper_id and lot["status"] in TRUST_EXPOSURE_LOT_STATUSES:
            total += lot["payable_cents"]
    shipper["trust_exposure_cents"] = total


def recompute_customer_credit_exposure(customer_id):
    customer = store.customers.get(customer_id)
    if customer is None:
        return
    total = 0
    for inv in store.invoices.values():
        if inv["customer_id"] == customer_id and inv["status"] in CREDIT_EXPOSURE_INVOICE_STATUSES:
            total += inv["balance_cents"]
    for order in store.sales_orders.values():
        if order["customer_id"] == customer_id and order["status"] in CREDIT_EXPOSURE_ORDER_STATUSES:
            total += order["subtotal_cents"]
    customer["credit_exposure_cents"] = total


def recompute_lot_payable(lot):
    """payable = adjusted - sum(ISSUED memos); REJECTED pins payable to 0."""
    if lot["status"] == "REJECTED":
        lot["payable_cents"] = 0
        return
    memo_sum = 0
    for memo in store.credit_memos.values():
        if memo["purchase_lot_id"] == lot["id"] and memo["status"] == "ISSUED":
            memo_sum += memo["amount_cents"]
    lot["payable_cents"] = lot["adjusted_cost_cents"] - memo_sum


def recompute_lot_available(lot):
    lot["available_units"] = (
        lot["quantity_units"]
        - lot["dumped_units"]
        - lot["reserved_units"]
        - lot["sold_units"]
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize(entity):
    return dict(entity)


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------

def get_json_body():
    body = None
    try:
        from flask import request

        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION, f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def req_string(body, field):
    v = body.get(field)
    if not is_str(v) or v == "":
        raise_error(ERR_VALIDATION, f"Field {field} must be a non-empty string")
    return v


def req_int(body, field, min_value=None):
    v = body.get(field)
    if not is_int(v):
        raise_error(ERR_VALIDATION, f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_VALIDATION, f"Field {field} must be >= {min_value}")
    return v


def req_positive_int(body, field):
    v = req_int(body, field)
    if v <= 0:
        raise_error(ERR_VALIDATION, f"Field {field} must be > 0")
    return v


def req_number(body, field):
    v = body.get(field)
    if not is_number(v):
        raise_error(ERR_VALIDATION, f"Field {field} must be a number")
    return Decimal(str(v))


def req_positive_number(body, field):
    v = req_number(body, field)
    if v <= 0:
        raise_error(ERR_VALIDATION, f"Field {field} must be > 0")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not is_bool(v):
        raise_error(ERR_VALIDATION, f"Field {field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not is_str(v) or v not in allowed:
        raise_error(
            ERR_VALIDATION, f"Field {field} must be one of {sorted(allowed)}"
        )
    return v


DATE_FMT = "%Y-%m-%d"


def req_date(body, field):
    v = body.get(field)
    if not is_str(v):
        raise_error(ERR_VALIDATION, f"Field {field} must be a YYYY-MM-DD string")
    try:
        return datetime.strptime(v, DATE_FMT).date()
    except ValueError:
        raise_error(ERR_VALIDATION, f"Field {field} must be a YYYY-MM-DD string")


def req_time_hhmm(body, field):
    v = body.get(field)
    if not is_str(v):
        raise_error(ERR_VALIDATION, f"Field {field} must be an HH:MM string")
    try:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h * 60 + m
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, f"Field {field} must be an HH:MM string")


def parse_datetime(value, field):
    """Parse an ISO-8601 datetime into an aware UTC datetime."""
    if not is_str(value):
        raise_error(ERR_VALIDATION, f"Field {field} must be an ISO-8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except ValueError:
        raise_error(ERR_VALIDATION, f"Field {field} must be an ISO-8601 string")
    return dt


def req_datetime(body, field):
    return parse_datetime(body.get(field), field)


# ---------------------------------------------------------------------------
# Lookup helpers (existence, priority 4)
# ---------------------------------------------------------------------------

def lookup(table, entity_id, label):
    entity = table.get(entity_id)
    if entity is None:
        raise_error(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return entity


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    from flask import request

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sorted_by_created(items):
    """Default sort: created_at ascending; id tiebreak keeps it stable."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))


# ---------------------------------------------------------------------------
# Calculations (scaffold §1.3)
# ---------------------------------------------------------------------------

def lot_provisional_cost_cents(quantity_units, shipper_unit_price):
    """lot_landed_cost PROVISIONAL: qty * price * 100, half-up."""
    return round_half_up_cents(Decimal(quantity_units) * shipper_unit_price)


def lot_final_cost_from_defect_cents(quantity_units, shipper_unit_price, defect_pct):
    """lot_landed_cost FINAL (certify PASS defect formula)."""
    if defect_pct <= DEFECT_TOLERANCE_PCT:
        return None  # adjusted stays at provisional
    factor = Decimal("1") - (defect_pct - DEFECT_TOLERANCE_PCT) / Decimal("100")
    final_unit_price = round_half_up(shipper_unit_price * factor, PRICE4)
    return round_half_up_cents(Decimal(quantity_units) * final_unit_price)


def lot_final_cost_from_agreed_cents(quantity_units, agreed_unit_price):
    """lot_landed_cost FINAL (resolve-dispute PRICE_ADJUST)."""
    return round_half_up_cents(Decimal(quantity_units) * agreed_unit_price)


def labor_charge_cents(ticket_type, hours, pieces, hourly_rate, piece_rate):
    """labor_charge HOURLY / PIECE variants."""
    if ticket_type == "HOURLY":
        regular = min(hours, OT_THRESHOLD_HOURS) * hourly_rate
        overtime = max(Decimal("0"), hours - OT_THRESHOLD_HOURS) * hourly_rate * OT_MULTIPLIER
        return round_half_up_cents(regular + overtime)
    # PIECE
    piece_pay = Decimal(pieces) * piece_rate
    guaranteed = hours * MIN_WAGE_DOLLARS
    return round_half_up_cents(max(piece_pay, guaranteed))


def order_line_extended_cents(unit_price, quantity):
    """order_subtotal: per-line round half-up to cents, then sum (pinned)."""
    return round_half_up_cents(unit_price * Decimal(quantity))


def credit_memo_amount_cents(adjusted_cost_cents, shrink_quantity, lot_quantity_units):
    """round_half_up(adjusted_cost_cents * shrink.qty / lot.quantity_units)."""
    value = (
        Decimal(adjusted_cost_cents) * Decimal(shrink_quantity)
        / Decimal(lot_quantity_units)
    )
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def early_pay_discount_cents(total_cents):
    return int(
        (Decimal(total_cents) * EARLY_PAY_DISCOUNT_PCT).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


def mid_price(low_price, high_price):
    """round_half_up((low + high) / 2, 2). Returns a float for JSON output."""
    val = ((low_price + high_price) / Decimal("2")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(val)


def to_float(dec):
    return float(dec)


# ---------------------------------------------------------------------------
# Date helpers for invoices
# ---------------------------------------------------------------------------

def add_days_str(date_obj, days):
    return (date_obj + timedelta(days=days)).strftime(DATE_FMT)
