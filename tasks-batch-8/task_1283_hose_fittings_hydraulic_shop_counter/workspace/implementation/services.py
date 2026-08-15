"""Business logic: pricing (PRD §2.6/§3.3), cut-waste (§2.7), due dates and
compliance scoring (§3.7), derived counters (§3.2), and shared cascades."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, touch

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations.constants)
# ---------------------------------------------------------------------------
LABOR_RATE_STD_CPM = 150
LABOR_RATE_MID_CPM = 200
LABOR_RATE_HIGH_CPM = 260
DIA_STD_MAX_IN = 0.5
DIA_MID_MAX_IN = 1.0
EMERGENCY_LABOR_MULT = Decimal("1.5")

MIN_REMNANT_MM = 1000
LOW_THRESHOLD_MM = 20000

TEST_PRESSURE_MULTIPLIER = 2.0

PROBATION_THRESHOLD = 70
DUE_SOON_DAYS = 30

RESERVED_ORDER_STATES = ("CONFIRMED", "BUILT", "TEST_PASSED", "TEST_FAILED",
                         "REWORK", "TAGGED")


def round_half_up(value):
    """Round a Decimal to whole cents, half up (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Reels (PRD §2.7)
# ---------------------------------------------------------------------------
def reel_status_for(remaining_mm):
    if remaining_mm < MIN_REMNANT_MM:
        return "DEPLETED"
    if remaining_mm < LOW_THRESHOLD_MM:
        return "LOW"
    return "AVAILABLE"


def refresh_reel_status(reel):
    """Status ladder moves are automatic in both directions; RETIRED is
    terminal and never recomputed."""
    if reel["status"] != "RETIRED":
        reel["status"] = reel_status_for(reel["remaining_length_mm"])


# ---------------------------------------------------------------------------
# Couplings (PRD §3.2): derived reservation counters
# ---------------------------------------------------------------------------
def coupling_reserved_qty(coupling_id):
    total = 0
    for line in store.lines.values():
        if line["coupling_id"] != coupling_id:
            continue
        order = store.orders.get(line["assembly_order_id"])
        if order is not None and order["status"] in RESERVED_ORDER_STATES:
            total += line["quantity"]
    return total


def serialize_coupling(c):
    from db import pub
    out = pub(c)
    out["reserved_qty"] = coupling_reserved_qty(c["id"])
    out["available_qty"] = c["on_hand_qty"] - out["reserved_qty"]
    return out


# ---------------------------------------------------------------------------
# Assets: due dates and posture (PRD §3.7)
# ---------------------------------------------------------------------------
def next_due_date(asset):
    """base = last_passed_inspection_at if set else installed_at; + interval
    days; null when neither base exists."""
    customer = store.customers.get(asset["customer_id"])
    base = asset["last_passed_inspection_at"] or asset["installed_at"]
    if base is None or customer is None:
        return None
    return base + timedelta(days=customer["inspection_interval_days"])


def latest_completed_failed(asset_id):
    """True when the latest completed inspection is FAILED with no later
    PASSED. Later-created inspection wins ties on performed_at."""
    latest = None
    for insp in store.inspections.values():
        if insp["equipment_asset_id"] != asset_id:
            continue
        if insp["status"] not in ("PASSED", "FAILED"):
            continue
        if latest is None or insp["performed_at"] >= latest["performed_at"]:
            latest = insp
    return latest is not None and latest["result"] == "FAILED"


def compliance_posture(asset):
    """Posture chain (PRD §3.7). DECOMMISSIONED assets keep their last
    computed posture."""
    if asset["status"] == "DECOMMISSIONED":
        return asset["frozen_posture"]
    if latest_completed_failed(asset["id"]):
        return "NON_COMPLIANT"
    nd = next_due_date(asset)
    if nd is None:
        return "COMPLIANT"
    clock = now()
    if clock > nd:
        return "OVERDUE"
    if (nd - clock) <= timedelta(days=DUE_SOON_DAYS):
        return "DUE_SOON"
    return "COMPLIANT"


def serialize_asset(a):
    from db import pub
    out = pub(a)
    out["next_due_date"] = next_due_date(a)
    out["compliance_posture"] = compliance_posture(a)
    nd = out["next_due_date"]
    if nd is not None:
        from db import fmt_dt
        out["next_due_date"] = fmt_dt(nd)
    return out


# ---------------------------------------------------------------------------
# Customers: compliance scoring and program status (PRD §3.7)
# ---------------------------------------------------------------------------
def _round_score(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_scores(customer):
    """(strict, projected, program_status). Only ACTIVE assets count; 100.00
    when the customer has no ACTIVE assets."""
    cid = customer["id"]
    eligible = [a for a in store.assets.values()
                if a["customer_id"] == cid and a["status"] == "ACTIVE"]
    if not eligible:
        strict = projected = 100.00
    else:
        clock = now()
        strict_ok = 0
        projected_ok = 0
        for a in eligible:
            posture = compliance_posture(a)
            if posture in ("COMPLIANT", "DUE_SOON"):
                strict_ok += 1
                projected_ok += 1
            else:
                # Lenient variant: OVERDUE / NON_COMPLIANT assets with a
                # SCHEDULED inspection whose window_end >= clock count too.
                for insp in store.inspections.values():
                    if (insp["equipment_asset_id"] == a["id"]
                            and insp["status"] == "SCHEDULED"
                            and insp["scheduled_window_end"] >= clock):
                        projected_ok += 1
                        break
        strict = _round_score(Decimal(100 * strict_ok) / Decimal(len(eligible)))
        projected = _round_score(Decimal(100 * projected_ok) / Decimal(len(eligible)))
    if not customer["program_enrolled"]:
        program_status = "NONE"
    elif strict >= PROBATION_THRESHOLD:
        program_status = "ACTIVE"
    else:
        program_status = "PROBATION"
    return strict, projected, program_status


def serialize_customer(c):
    from db import pub
    out = pub(c)
    strict, projected, program_status = compute_scores(c)
    out["compliance_score_strict"] = strict
    out["compliance_score_projected"] = projected
    out["program_status"] = program_status
    return out


def touch_customer(customer_id):
    """A side-effect cascade that recomputes a customer's scores counts as a
    modification of the customer (PRD §2.4)."""
    customer = store.customers.get(customer_id)
    if customer is not None:
        touch(customer)


# ---------------------------------------------------------------------------
# Assembly pricing (PRD §2.6, §3.3) — pinned per-component rounding order
# ---------------------------------------------------------------------------
def material_hose_cents(cut_length_mm, reel):
    return round_half_up(Decimal(cut_length_mm) / Decimal(1000)
                         * Decimal(reel["price_per_meter_cents"]))


def labor_rate_cpm(reel):
    dia = reel["hose_diameter_in"]
    if dia <= DIA_STD_MAX_IN:
        return LABOR_RATE_STD_CPM
    if dia <= DIA_MID_MAX_IN:
        return LABOR_RATE_MID_CPM
    return LABOR_RATE_HIGH_CPM


def labor_cents(minutes, reel, is_emergency):
    mult = EMERGENCY_LABOR_MULT if is_emergency else Decimal("1")
    return round_half_up(Decimal(minutes) * Decimal(labor_rate_cpm(reel)) * mult)


def waste_surcharge_cents(scrap_charged_mm, reel):
    return round_half_up(Decimal(scrap_charged_mm) / Decimal(1000)
                         * Decimal(reel["price_per_meter_cents"]))


def assembly_total(order, minutes):
    """Pinned rounding order (SCAFFOLD assembly_invoice_total): round hose,
    labor, and waste per component; line totals exact; discount last."""
    reel = store.reels[order["reel_id"]]
    customer = store.customers[order["customer_id"]]
    hose = material_hose_cents(order["cut_length_mm"], reel)
    couplings = sum(l["line_total_cents"] for l in order_lines(order["id"]))
    labor = labor_cents(minutes, reel, order["is_emergency"])
    waste = waste_surcharge_cents(order["scrap_charged_mm"], reel)
    subtotal = hose + couplings + labor + waste
    _, _, program_status = compute_scores(customer)
    if program_status == "ACTIVE":
        discount = round_half_up(Decimal(subtotal)
                                 * Decimal(str(customer["program_discount_pct"])))
    else:
        discount = 0
    return subtotal - discount


def order_lines(order_id):
    return [l for l in store.lines.values() if l["assembly_order_id"] == order_id]


def serialize_order(o):
    from db import pub
    out = pub(o)
    out["material_couplings_cents"] = sum(
        l["line_total_cents"] for l in order_lines(o["id"]))
    return out


# ---------------------------------------------------------------------------
# Order completion cascade (PRD §3.5) — shared by the counter complete and by
# dispatch completion (§3.6).
# ---------------------------------------------------------------------------
def complete_order(order):
    """TAGGED -> COMPLETED with the full settlement cascade. Caller has
    already validated the order's state."""
    from errors import ApiError, ERR_ASSET_NOT_ACTIVE
    if order["equipment_asset_id"] is not None:
        asset = store.assets[order["equipment_asset_id"]]
        if asset["status"] != "ACTIVE":
            raise ApiError(ERR_ASSET_NOT_ACTIVE, 422,
                           "Equipment asset is DECOMMISSIONED")
    # final pricing from actual labor
    order["final_total_cents"] = assembly_total(order, order["actual_labor_minutes"])
    # coupling stock decremented per line; reservations released by the status
    # change (reserved_qty derives from non-terminal build states)
    for line in order_lines(order["id"]):
        coupling = store.couplings[line["coupling_id"]]
        coupling["on_hand_qty"] -= line["quantity"]
        touch(coupling)
    order["status"] = "COMPLETED"
    touch(order)
    # asset installation cascade
    if order["equipment_asset_id"] is not None:
        asset = store.assets[order["equipment_asset_id"]]
        asset["installed_assembly_order_id"] = order["id"]
        asset["installed_at"] = now()
        touch(asset)
        touch_customer(order["customer_id"])
