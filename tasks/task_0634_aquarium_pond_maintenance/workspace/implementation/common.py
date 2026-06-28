"""Shared helpers: record lifecycle, pagination, parsing/validation,
calculations, and derived-field recomputation.

Every calculation traces to PRD §2.8/§2.9/§2.10/§3.4/§3.5/§3.8 and
SCAFFOLD calculations.
"""

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import ApiError


# ===========================================================================
# Record lifecycle (common system fields, PRD §2.4)
# ===========================================================================
def make_record(extra):
    """Create a record carrying the standard common fields.

    id (UUID, no prefix), created_at, updated_at (ISO8601 UTC 3 frac digits),
    version (integer starting at 1).
    """
    now = store.now_iso()
    rec = {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(extra)
    return rec


def touch(rec):
    """A mutation: refresh updated_at and increment version (PRD §2.4)."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ===========================================================================
# Request body / param parsing & validation (ERR_INVALID_REQUEST, priority 16)
# ===========================================================================
def require_body(data):
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def req_str(data, key, allow_missing=False, default=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if not isinstance(val, str) or val.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be a non-empty string.")
    return val


def req_enum(data, key, domain, allow_missing=False, default=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if val not in domain:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be one of {sorted(domain)}.")
    return val


def req_int(data, key, allow_missing=False, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be <= {maximum}.")
    return val


def req_number(data, key, allow_missing=False, default=None,
               minimum=None, maximum=None, exclusive_min=None, exclusive_max=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be a number.")
    val = float(val)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be <= {maximum}.")
    if exclusive_min is not None and val <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be > {exclusive_min}.")
    if exclusive_max is not None and val >= exclusive_max:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be < {exclusive_max}.")
    return val


def req_bool(data, key, allow_missing=False, default=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be a boolean.")
    return val


def req_datetime(data, key, allow_missing=False, default=None):
    if key not in data or data[key] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}.")
    val = data[key]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be an ISO8601 string.")
    parsed = parse_iso(val)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be a valid ISO8601 datetime.")
    return val  # store the original string


def clock_iso():
    """The server logical clock (PRD §3.11) as an ISO8601 UTC string with three
    fractional digits. This is the server's notion of "now" — e.g. a visit's
    completion date — and is driven by /_clock/set_current_utc, never wall-clock.
    """
    now = store.current_utc
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def parse_pagination(args):
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD §2.3), then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ===========================================================================
# Rounding (PRD §2.8) — round-half-up
# ===========================================================================
def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half rounds up. Returns float."""
    q = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ===========================================================================
# Constants (SCAFFOLD calculations)
# ===========================================================================
TIER_BASE_CENTS = {"BASIC": 6000, "PLUS": 9000, "PREMIUM": 13000}
TIER_INCLUDED_MINUTES = {"BASIC": 30, "PLUS": 45, "PREMIUM": 60}
TIER_DISCOUNT_RATE = {"BASIC": Decimal("0.00"), "PLUS": Decimal("0.10"), "PREMIUM": Decimal("0.15")}
PER_BLOCK_CENTS = 2000
EMERGENCY_SURCHARGE_RATE = Decimal("0.25")
DEPOSIT_RATE = Decimal("0.30")

WASTE_FACTOR = {
    "COMMUNITY": Decimal("1.0"),
    "CICHLID": Decimal("1.5"),
    "GOLDFISH": Decimal("2.0"),
    "PREDATOR": Decimal("2.5"),
    "INVERT": Decimal("0.5"),
}


# ===========================================================================
# Bioload (PRD §2.9, calculations.bioload_index)
# ===========================================================================
def effective_volume(system):
    nominal = Decimal(str(system["nominal_volume_l"]))
    displ = Decimal(str(system["substrate_displacement_pct"]))
    return nominal * (Decimal("1") - displ)


def compute_bioload_index(system, livestock_list):
    """Return bioload_index (float 2dp) given ALIVE livestock on this system."""
    eff = effective_volume(system)
    raw = Decimal("0")
    for l in livestock_list:
        if l["system_id"] == system["id"] and l["status"] == "ALIVE":
            raw += Decimal(str(l["adult_length_cm"])) * WASTE_FACTOR[l["species_class"]]
    if eff == 0:
        index = Decimal("0")
    else:
        index = (raw / eff) * Decimal("100")
    index = index.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(index)


def recompute_system_bioload(system):
    """Recompute bioload_index + stocking_posture on a system; mutates it."""
    livestock_list = list(store.livestock.values())
    index = compute_bioload_index(system, livestock_list)
    posture = "OVERSTOCKED" if index > 100.0 else "NORMAL"
    changed = (system.get("bioload_index") != index
               or system.get("stocking_posture") != posture)
    system["bioload_index"] = index
    system["stocking_posture"] = posture
    if changed:
        touch(system)


def bioload_with_extra(system, extra_alive_livestock_ids=None,
                       make_alive_ids=None):
    """Compute the bioload_index a system WOULD have if the named livestock
    were ALIVE, used by the overstock gate (PRD §3.2, §3.6).

    extra_alive_livestock_ids: ids treated as ALIVE in addition to current.
    make_alive_ids: existing livestock ids forced to ALIVE for the projection.
    """
    eff = effective_volume(system)
    raw = Decimal("0")
    make_alive_ids = make_alive_ids or set()
    for l in store.livestock.values():
        if l["system_id"] != system["id"]:
            continue
        is_alive = (l["status"] == "ALIVE") or (l["id"] in make_alive_ids)
        if is_alive:
            raw += Decimal(str(l["adult_length_cm"])) * WASTE_FACTOR[l["species_class"]]
    if eff == 0:
        index = Decimal("0")
    else:
        index = (raw / eff) * Decimal("100")
    return float(index.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ===========================================================================
# alive_livestock_count + account_balance (PRD §2.10)
# ===========================================================================
def systems_of_contract(contract_id):
    return [s for s in store.systems.values() if s["contract_id"] == contract_id]


def recompute_alive_livestock_count(contract):
    sys_ids = {s["id"] for s in systems_of_contract(contract["id"])}
    count = sum(
        1 for l in store.livestock.values()
        if l["system_id"] in sys_ids and l["status"] == "ALIVE"
    )
    if contract.get("alive_livestock_count") != count:
        contract["alive_livestock_count"] = count
        touch(contract)
    else:
        contract["alive_livestock_count"] = count


def recompute_account_balance(contract):
    total = 0
    for inv in store.invoices.values():
        if inv["contract_id"] == contract["id"] and inv["status"] in ("ISSUED", "OVERDUE"):
            total += inv["total_cents"] - inv["amount_paid_cents"]
    if contract.get("account_balance_cents") != total:
        contract["account_balance_cents"] = total
        touch(contract)
    else:
        contract["account_balance_cents"] = total


def contract_of_system(system):
    return store.contracts.get(system["contract_id"])


# ===========================================================================
# media_due_on (PRD §3.2, calculations.media_due_on)
# ===========================================================================
def compute_media_due_on(equipment, system):
    """date(base) + media_interval_days, as a date string YYYY-MM-DD.

    base = last_serviced_on if set, else system created_at date component.
    """
    interval = equipment["media_interval_days"]
    if equipment.get("last_serviced_on"):
        base = parse_iso(equipment["last_serviced_on"])
    else:
        base = parse_iso(system["created_at"])
    base_date = base.date()
    due = base_date + timedelta(days=interval)
    return due.isoformat()


# ===========================================================================
# visit billing (PRD §3.4, calculations.visit_billing)
# ===========================================================================
def compute_visit_total(visit, contract, consumable_lines):
    tier = contract["service_tier"]
    base = TIER_BASE_CENTS[tier]
    included = TIER_INCLUDED_MINUTES[tier]
    labor_minutes = visit["labor_minutes"]
    overage_minutes = max(0, labor_minutes - included)
    blocks = math.ceil(overage_minutes / 15) if overage_minutes > 0 else 0
    labor_overage = blocks * PER_BLOCK_CENTS

    line_items = 0
    for line in consumable_lines:
        qty = line["qty"]
        unit = line["unit_price_cents"]
        line_items += qty * unit

    subtotal = base + labor_overage + line_items
    discount_rate = TIER_DISCOUNT_RATE[tier]
    plan_discount = round_half_up(Decimal(subtotal) * discount_rate)
    after_discount = subtotal - plan_discount

    if visit["visit_kind"] == "EMERGENCY":
        surcharge = round_half_up(Decimal(after_discount) * EMERGENCY_SURCHARGE_RATE)
    else:
        surcharge = 0
    return after_discount + surcharge


def parse_consumable_lines(data):
    """Validate optional consumable_lines list. Each line: qty, unit_price_cents."""
    raw = data.get("consumable_lines")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "consumable_lines must be a list.")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each consumable line must be an object.")
        qty = req_int(entry, "qty", minimum=0)
        unit = req_int(entry, "unit_price_cents", minimum=0)
        lines.append({"qty": qty, "unit_price_cents": unit})
    return lines


# ===========================================================================
# install billing (PRD §3.8, calculations.install_billing)
# ===========================================================================
def compute_install_provisional(install):
    quote_total = install["labor_estimate_cents"] + install["equipment_estimate_cents"]
    deposit = round_half_up(Decimal(quote_total) * DEPOSIT_RATE)
    return quote_total, deposit


def compute_install_final(install):
    actual_blocks = math.ceil(install["actual_labor_minutes"] / 15) if install["actual_labor_minutes"] > 0 else 0
    actual_labor_cents = actual_blocks * PER_BLOCK_CENTS
    final_total = actual_labor_cents + install["actual_equipment_cents"] + install["change_order_cents"]
    return final_total


# ===========================================================================
# dose volume (PRD §3.5, calculations.dose_volume_ml)
# ===========================================================================
def compute_dose_ml(system, measured_value, target_value, product_strength):
    if measured_value >= target_value:
        return 0.0
    eff = float(effective_volume(system))
    raw_ml = (target_value - measured_value) * eff / product_strength
    # round UP to nearest 0.1 mL
    dose = math.ceil(raw_ml * 10) / 10.0
    return dose


# ===========================================================================
# Invoice creation helper
# ===========================================================================
def create_invoice(contract_id, source_kind, source_id, total_cents, due_on=None):
    inv = make_record({
        "contract_id": contract_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "total_cents": total_cents,
        "amount_paid_cents": 0,
        "status": "ISSUED",
        "due_on": due_on,
    })
    store.invoices[inv["id"]] = inv
    return inv


# ===========================================================================
# Window / interval helpers
# ===========================================================================
def half_open_overlap(a_start, a_end, b_start, b_end):
    """True if [a_start,a_end) and [b_start,b_end) overlap (touching endpoints
    do NOT conflict)."""
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    """True if [a_start,a_end] and [b_start,b_end] overlap (shared endpoint IS
    a conflict)."""
    return a_start <= b_end and b_start <= a_end


# ===========================================================================
# Technician resolution (PRD §2.1) — entity_backed:Technician via tech_user_id
# ===========================================================================
def technician_for_user(user_id):
    for t in store.technicians.values():
        if t["tech_user_id"] == user_id:
            return t
    return None
