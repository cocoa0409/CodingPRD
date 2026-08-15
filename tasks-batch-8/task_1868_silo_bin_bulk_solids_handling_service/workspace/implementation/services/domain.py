"""Domain services: calculations, derivation rules, and cross-entity cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, parse_iso


# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml §1.3 / PRD §3)
# ---------------------------------------------------------------------------

BASE_RATE_CENTS_PER_CREW_HOUR = {
    "DIAGNOSIS": 9500,
    "CLEANOUT": 14500,
    "INSPECTION": 11000,
    "RETROFIT_AERATION": 22000,
    "RETROFIT_VIBRATOR": 18000,
}
EMERGENCY_MULT = Decimal("1.5")
MILEAGE_RATE_CENTS_PER_MILE = Decimal("331.7")
DISPOSAL_RATE_CENTS_PER_TON = Decimal("3653.92")
TAX_RATE_PCT = Decimal("6.0")

# Atmosphere evaluation constants (PRD §3.8)
O2_MIN_PCT = Decimal("19.5")
O2_MAX_PCT = Decimal("23.5")
COMBUSTIBLE_MAX_PCT_LEL = Decimal("10.0")

VESSEL_DOWNTIME_BUFFER = timedelta(hours=2)
USAGE_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def _D(x) -> Decimal:
    """Coerce to Decimal without going through float binary representation."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(str(x))


def round_half_up(value, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)  # 10^-places
    return _D(value).quantize(q, rounding=ROUND_HALF_UP)


def to_number(d: Decimal, places: int):
    """Return an int when places == 0, else a float with the given precision."""
    if places == 0:
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Vessel / posture derivations
# ---------------------------------------------------------------------------

def _vessel_readings(vessel_id: str):
    return [r for r in store.level_readings.values() if r["vessel_id"] == vessel_id]


def _vessel_orders(vessel_id: str):
    return [o for o in store.replenishment_orders.values() if o["vessel_id"] == vessel_id]


def _vessel_reports(vessel_id: str):
    return [r for r in store.quality_reports.values() if r["vessel_id"] == vessel_id]


def _latest_anchor_reading(vessel_id: str):
    readings = _vessel_readings(vessel_id)
    if not readings:
        return None
    return max(readings, key=lambda r: (parse_iso(r["measured_at"]), parse_iso(r["created_at"])))


def compute_current_inventory_tons(vessel: dict) -> Decimal:
    """PRD §3.2 first step: anchor inventory + RECEIVED receipts strictly after anchor."""
    return compute_current_inventory_tons_excluding(vessel, exclude_order_id=None)


def compute_current_inventory_tons_excluding(vessel: dict, exclude_order_id=None) -> Decimal:
    """§3.2 recompute with one order optionally excluded from the received set
    (used by the §3.5 void pre-check: the receipt 'simply leaves the received set')."""
    capacity = _D(vessel["capacity_tons"])
    anchor = _latest_anchor_reading(vessel["id"])
    if anchor is None:
        anchor_dt = parse_iso(vessel["created_at"])
        anchor_inventory = _D(vessel.get("opening_inventory_tons", 0))
    else:
        anchor_dt = parse_iso(anchor["measured_at"])
        anchor_inventory = round_half_up(_D(anchor["level_pct"]) * capacity / Decimal(100), 1)

    receipts = Decimal(0)
    for o in _vessel_orders(vessel["id"]):
        if o["status"] != "RECEIVED":
            continue
        if exclude_order_id is not None and o["id"] == exclude_order_id:
            continue
        received_at = o.get("received_at")
        if received_at is None:
            continue
        if parse_iso(received_at) > anchor_dt:
            receipts += _D(o.get("delivered_tons", 0))

    return round_half_up(anchor_inventory + receipts, 1)


def compute_avg_daily_usage_tons(vessel: dict) -> Decimal:
    """PRD §3.2 DAYS_OF_COVER usage window (trailing 14 days from logical clock)."""
    capacity = _D(vessel["capacity_tons"])
    clock = store.logical_clock
    window_start = clock - timedelta(days=USAGE_WINDOW_DAYS)

    in_window = []
    for r in _vessel_readings(vessel["id"]):
        m = parse_iso(r["measured_at"])
        if window_start < m <= clock:
            in_window.append(r)
    in_window.sort(key=lambda r: (parse_iso(r["measured_at"]), parse_iso(r["created_at"])))

    if len(in_window) < 2:
        return _D(vessel.get("default_usage_tons", 1.0))

    earliest = in_window[0]
    latest = in_window[-1]
    earliest_dt = parse_iso(earliest["measured_at"])
    latest_dt = parse_iso(latest["measured_at"])

    inv_earliest = round_half_up(_D(earliest["level_pct"]) * capacity / Decimal(100), 1)
    inv_latest = round_half_up(_D(latest["level_pct"]) * capacity / Decimal(100), 1)

    receipts = Decimal(0)
    for o in _vessel_orders(vessel["id"]):
        if o["status"] != "RECEIVED":
            continue
        ra = o.get("received_at")
        if ra is None:
            continue
        ra_dt = parse_iso(ra)
        if earliest_dt < ra_dt <= latest_dt:
            receipts += _D(o.get("delivered_tons", 0))

    days = Decimal(str((latest_dt - earliest_dt).total_seconds())) / Decimal(86400)
    if days <= 0:
        return _D(vessel.get("default_usage_tons", 1.0))
    usage = (inv_earliest - inv_latest + receipts) / days
    if usage < 0:
        usage = Decimal(0)
    return round_half_up(usage, 2)


def compute_flow_posture(vessel: dict) -> str:
    """PRD §2.4: FLOW_IMPAIRED > PENDING_REPLENISHMENT > NORMAL."""
    reports = _vessel_reports(vessel["id"])
    impaired = False
    if reports:
        latest_qr = max(reports, key=lambda r: (parse_iso(r["sampled_at"]), parse_iso(r["created_at"])))
        if (_D(latest_qr["moisture_pct"]) > _D(vessel["moisture_limit_pct"])
                or int(latest_qr["caking_index"]) >= 4):
            impaired = True
    if impaired:
        return "FLOW_IMPAIRED"
    open_order = any(o["status"] in ("TRIGGERED", "DISPATCHED") for o in _vessel_orders(vessel["id"]))
    if open_order:
        return "PENDING_REPLENISHMENT"
    return "NORMAL"


def compute_site_posture(site_id: str) -> str:
    """PRD §2.4 worst-case rollup of child vessel postures."""
    postures = [compute_flow_posture(v) for v in store.vessels.values() if v["site_id"] == site_id]
    if "FLOW_IMPAIRED" in postures:
        return "CRITICAL"
    if "PENDING_REPLENISHMENT" in postures:
        return "ATTENTION"
    return "NORMAL"


def auto_void_permits_on_impaired(vessel_id: str):
    """PRD §2.4: when a vessel becomes FLOW_IMPAIRED, DRAFT/ISSUED permits -> VOIDED."""
    for p in store.entry_permits.values():
        if p["vessel_id"] == vessel_id and p["status"] in ("DRAFT", "ISSUED"):
            p["status"] = "VOIDED"
            p["void_reason"] = "AUTO_QUALITY_HAZARD"
            p["updated_at"] = _now_iso()
            p["version"] = p.get("version", 1) + 1


def _now_iso() -> str:
    from db import now_iso
    return now_iso()


# ---------------------------------------------------------------------------
# Technician capacity
# ---------------------------------------------------------------------------

def compute_remaining_capacity_hours(technician: dict) -> Decimal:
    """PRD §3.7: weekly - sum(est_hours of SCHEDULED/IN_PROGRESS tickets)."""
    total = _D(technician["weekly_capacity_hours"])
    used = Decimal(0)
    for t in store.service_tickets.values():
        if t.get("technician_id") == technician["id"] and t["status"] in ("SCHEDULED", "IN_PROGRESS"):
            used += _D(t["est_hours"])
    return round_half_up(total - used, 2)


# ---------------------------------------------------------------------------
# Estimate & invoice
# ---------------------------------------------------------------------------

def compute_estimate_cents(ticket: dict, vessel: dict, site: dict) -> int:
    """PRD §3.6: base = rate*est_hours*crew_size; emergency mult if FLOW_IMPAIRED;
    then discount; integer cents, round half up."""
    rate = Decimal(BASE_RATE_CENTS_PER_CREW_HOUR[ticket["job_type"]])
    base = rate * _D(ticket["est_hours"]) * Decimal(int(ticket["crew_size"]))
    mult = EMERGENCY_MULT if compute_flow_posture(vessel) == "FLOW_IMPAIRED" else Decimal("1.0")
    subtotal = round_half_up(base * mult, 0)
    discount = round_half_up(subtotal * _D(site.get("contract_discount_pct", 0)) / Decimal(100), 0)
    return int(subtotal - discount)


def compute_invoice(ticket: dict, site: dict, actual_hours, mileage_miles, disposal_tons) -> dict:
    """PRD §3.9: per-line rounding, then sum, then discount, then tax."""
    rate = Decimal(BASE_RATE_CENTS_PER_CREW_HOUR[ticket["job_type"]])
    labor = round_half_up(_D(actual_hours) * rate * Decimal(int(ticket["crew_size"])), 0)
    mobilization = round_half_up(_D(mileage_miles) * MILEAGE_RATE_CENTS_PER_MILE, 0)
    disposal = round_half_up(_D(disposal_tons) * DISPOSAL_RATE_CENTS_PER_TON, 0)
    subtotal = labor + mobilization + disposal
    discount = round_half_up(subtotal * _D(site.get("contract_discount_pct", 0)) / Decimal(100), 0)
    taxable = subtotal - discount
    tax = round_half_up(taxable * TAX_RATE_PCT / Decimal(100), 0)
    total = taxable + tax
    return {
        "invoice_labor_cents": int(labor),
        "invoice_mobilization_cents": int(mobilization),
        "invoice_disposal_cents": int(disposal),
        "invoice_subtotal_cents": int(subtotal),
        "invoice_discount_cents": int(discount),
        "invoice_tax_cents": int(tax),
        "invoice_total_cents": int(total),
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def compute_calibration(vessel: dict, test_weight_tons, indicated_tons, tolerance_pct):
    """PRD §3.4: error_pct @3dp half-up; PASS when |error| <= tolerance (inclusive)."""
    basis = vessel.get("error_basis", "OF_READING")
    tw = _D(test_weight_tons)
    ind = _D(indicated_tons)
    if basis == "OF_READING":
        raw = (ind - tw) / tw * Decimal(100)
    else:  # OF_FULL_SCALE
        fs = _D(vessel.get("full_scale_tons"))
        raw = (ind - tw) / fs * Decimal(100)
    error_pct = round_half_up(raw, 3)
    result = "PASS" if abs(error_pct) <= _D(tolerance_pct) else "FAIL"
    return basis, error_pct, result


# ---------------------------------------------------------------------------
# Atmosphere
# ---------------------------------------------------------------------------

def atmosphere_passes(oxygen_pct, combustible_pct) -> bool:
    o2 = _D(oxygen_pct)
    comb = _D(combustible_pct)
    return O2_MIN_PCT <= o2 <= O2_MAX_PCT and comb <= COMBUSTIBLE_MAX_PCT_LEL
