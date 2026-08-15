"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All money is integer cents;
fractional intermediates use Decimal and round half-up at the pinned points."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, now_dt

# --- paint_material_estimate constants ---
COVERAGE_SQFT_PER_GAL = 350
SCUFF_MATERIAL_FACTOR = Decimal("0.85")
ACCENT_COVERAGE_SQFT_PER_GAL = 500
TIER1_MAX_GAL = 20
TIER1_RATE_CENTS = 18500
TIER2_MAX_GAL = 60
TIER2_RATE_CENTS = 17250
TIER3_RATE_CENTS = 16000

# --- weight_delta constants ---
FILM_LB_PER_SQFT_COAT_EST = Decimal("0.006")      # PROVISIONAL
FILM_LB_PER_SQFT_COAT_ACTUAL = Decimal("0.0058")  # FINAL

# --- booth_utilization_fee constants ---
OVERRUN_PREMIUM_MULT = Decimal("1.25")

# --- invoice_line_totals constants ---
DEPOSIT_PCT = Decimal("0.10")
PROGRESS_PCT = Decimal("0.40")
DISCOVERY_HANDLING_PCT = Decimal("0.10")

# --- burn_certification_derivation constants ---
MAX_RETESTS = 3

# --- major_defect_discovery_trigger constants ---
MAJOR_DEFECT_THRESHOLD = 2

EXCUSABLE_CATEGORIES = ("CUSTOMER_CAUSED", "FORCE_MAJEURE")


def round_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Decimal from a JSON number without float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Entity lookups used by calculations
# ---------------------------------------------------------------------------

def events_of(program_id):
    return [e for e in STORE.delay_events.values() if e["program_id"] == program_id]


def change_orders_of(program_id):
    return [c for c in STORE.change_orders.values() if c["program_id"] == program_id]


def discovery_items_of(program_id):
    items = [d for d in STORE.discovery_items.values() if d["program_id"] == program_id]
    return sorted(items, key=lambda d: d["_seq"])


def slots_of(program_id):
    return [s for s in STORE.hangar_slots.values() if s["program_id"] == program_id]


def bookings_of(program_id):
    return [b for b in STORE.booth_bookings.values() if b["program_id"] == program_id]


def invoices_of(program_id):
    return [i for i in STORE.invoices.values() if i["program_id"] == program_id]


def current_assessment(program_id):
    """The latest non-SUPERSEDED SurfaceAssessment of a program (or None)."""
    current = None
    for a in STORE.surface_assessments.values():
        if a["program_id"] == program_id and a["status"] != "SUPERSEDED":
            if current is None or a["_seq"] > current["_seq"]:
                current = a
    return current


def current_decision(program_id):
    """Current assessment decision; defaults to STRIP semantics (None -> factor 1)."""
    a = current_assessment(program_id)
    if a is not None and a["status"] == "DECIDED":
        return a["decision"]
    return None


# ---------------------------------------------------------------------------
# Program-level derived fields
# ---------------------------------------------------------------------------

def total_contract_value_cents(prog):
    total = prog["base_price_cents"]
    for co in change_orders_of(prog["id"]):
        if co["status"] == "APPROVED":
            total += co["delta_price_cents"]
    return total


def discovery_cost_total_cents(program_id):
    total = 0
    for d in discovery_items_of(program_id):
        if d["status"] == "APPROVED":
            total += d["est_cost_cents"] or 0
        elif d["status"] == "COMPLETED":
            total += d["actual_cost_cents"] or 0
    return total


def committed_delivery_date(prog):
    """contractual + sum(impact_days of CONFIRMED excusable events, event_seq order)."""
    shift = 0
    for e in sorted(events_of(prog["id"]), key=lambda e: e["event_seq"]):
        if e["status"] == "CONFIRMED" and e["category"] in EXCUSABLE_CATEGORIES:
            shift += e["impact_days"]
    return prog["contractual_delivery_date"] + timedelta(days=shift)


def delivery_penalty(prog, variant, reference_date=None):
    """delivery_penalty calc, pinned evaluation order (cap before min).

    variant: "projection" (CONFIRMED + REPORTED excusable; reference is the
    later of clock date and adjusted commitment) or "settlement" (CONFIRMED
    only; reference is actual delivery date, or clock date if undelivered).
    Returns integer cents.
    """
    contract_value = total_contract_value_cents(prog)
    cap = round_cents(dec(contract_value) * dec(prog["penalty_cap_pct"]))
    if variant == "settlement":
        statuses = ("CONFIRMED",)
    else:
        statuses = ("CONFIRMED", "REPORTED")
    shift = 0
    for e in sorted(events_of(prog["id"]), key=lambda e: e["event_seq"]):
        if e["status"] in statuses and e["category"] in EXCUSABLE_CATEGORIES:
            shift += e["impact_days"]
    adjusted = (prog["contractual_delivery_date"] + timedelta(days=shift)).date()
    if reference_date is None:
        if variant == "settlement":
            ref_dt = prog["actual_delivery_date"] or now_dt()
            reference_date = ref_dt.date()
        else:
            reference_date = max(now_dt().date(), adjusted)
    late_days = max(0, (reference_date - adjusted).days)
    raw = late_days * prog["daily_penalty_rate_cents"]
    return min(raw, cap)


def material_estimate(prog):
    """paint_material_estimate from the pinned APPROVED scheme and the current
    assessment decision. Returns (total_gallons, cost_cents); (0, 0) until a
    scheme is APPROVED."""
    scheme_id = prog.get("approved_scheme_id")
    if not scheme_id:
        return 0, 0
    scheme = STORE.paint_schemes.get(scheme_id)
    if scheme is None:
        return 0, 0
    area = dec(scheme["painted_area_sqft"])
    coats = dec(scheme["coat_count"])
    raw_main = area * coats / dec(COVERAGE_SQFT_PER_GAL)
    if current_decision(prog["id"]) == "SCUFF":
        raw_main = raw_main * SCUFF_MATERIAL_FACTOR
    gallons_main = math.ceil(raw_main)
    stripe = dec(scheme.get("stripe_pct") or 0)
    raw_accent = area * stripe / dec(ACCENT_COVERAGE_SQFT_PER_GAL)
    gallons_accent = math.ceil(raw_accent)
    total_gal = gallons_main + gallons_accent
    if total_gal <= TIER1_MAX_GAL:
        rate = TIER1_RATE_CENTS
    elif total_gal <= TIER2_MAX_GAL:
        rate = TIER2_RATE_CENTS
    else:
        rate = TIER3_RATE_CENTS
    return total_gal, total_gal * rate


# ---------------------------------------------------------------------------
# Weight & balance (weight_delta calc)
# ---------------------------------------------------------------------------

def compute_film_lbs(scheme, variant, decision):
    factor = FILM_LB_PER_SQFT_COAT_EST if variant == "PROVISIONAL" else FILM_LB_PER_SQFT_COAT_ACTUAL
    film = (dec(scheme["painted_area_sqft"]) * dec(scheme["coat_count"]) * factor
            * (Decimal(1) + dec(scheme.get("stripe_pct") or 0)))
    if decision == "SCUFF":
        film = film * SCUFF_MATERIAL_FACTOR
    return film


def compute_delta_lbs(removal_weight_lbs, installed_weight_lbs, film_lbs):
    delta = dec(installed_weight_lbs) - dec(removal_weight_lbs) + film_lbs
    return delta.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Booth utilization fee (scheduled vs actual dual variant)
# ---------------------------------------------------------------------------

def scheduled_hours_of(booking):
    micros = int((booking["end_at"] - booking["start_at"]).total_seconds() * 1_000_000)
    return math.floor(micros / 3_600_000_000)


def scheduled_fee(booking, booth):
    return scheduled_hours_of(booking) * booth["hourly_rate_cents"]


def actual_fee(booking, booth, actual_hours):
    sched = scheduled_hours_of(booking)
    rate = booth["hourly_rate_cents"]
    if actual_hours <= sched:
        return actual_hours * rate
    overrun = actual_hours - sched
    overrun_cents = round_cents(dec(overrun) * dec(rate) * OVERRUN_PREMIUM_MULT)
    return sched * rate + overrun_cents


# ---------------------------------------------------------------------------
# Invoice line computation (invoice_line_totals + hangar_stall_fee)
# ---------------------------------------------------------------------------

def hangar_stall_fee_cents(program_id):
    """Longest-duration non-CANCELLED slot (ties: earliest created) x bay rate."""
    candidates = [s for s in slots_of(program_id) if s["status"] != "CANCELLED"]
    if not candidates:
        return 0

    def key(slot):
        micros = int((slot["end_at"] - slot["start_at"]).total_seconds() * 1_000_000)
        return (-micros, slot["_seq"])

    slot = sorted(candidates, key=key)[0]
    bay = STORE.hangar_bays.get(slot["bay_id"])
    if bay is None:
        return 0
    micros = int((slot["end_at"] - slot["start_at"]).total_seconds() * 1_000_000)
    days = -(-micros // 86_400_000_000)  # calendar-day ceiling
    return days * bay["daily_rate_cents"]


def booth_fee_line_cents(program_id):
    """Sum actual fees of COMPLETED bookings; if none completed, scheduled fees
    of BOOKED bookings."""
    bookings = bookings_of(program_id)
    completed = [b for b in bookings if b["status"] == "COMPLETED"]
    if completed:
        return sum(b["actual_fee_cents"] or 0 for b in completed)
    booked = [b for b in bookings if b["status"] == "BOOKED"]
    return sum(b["scheduled_fee_cents"] or 0 for b in booked)


def compute_invoice_lines(prog, kind):
    """Per-line half-up rounding first, then summed (pinned rounding order)."""
    base = dec(prog["base_price_cents"])
    deposit_milestone = round_cents(base * DEPOSIT_PCT)
    progress_milestone = round_cents(base * PROGRESS_PCT)

    if kind == "DEPOSIT":
        lines = [{"label": "deposit_milestone", "amount_cents": deposit_milestone}]
    elif kind == "PROGRESS":
        lines = [
            {"label": "progress_milestone", "amount_cents": progress_milestone},
            {"label": "hangar_stall_fee", "amount_cents": hangar_stall_fee_cents(prog["id"])},
        ]
    else:  # FINAL
        remainder = total_contract_value_cents(prog) - deposit_milestone - progress_milestone
        lines = [{"label": "contract_remainder", "amount_cents": remainder}]
        for item in discovery_items_of(prog["id"]):
            if item["status"] == "COMPLETED":
                amount = item["actual_cost_cents"] or 0
            elif item["status"] == "APPROVED":
                amount = item["est_cost_cents"] or 0
            else:
                continue
            lines.append({"label": f"discovery_item_{item['id']}", "amount_cents": amount})
            handling = round_cents(dec(amount) * DISCOVERY_HANDLING_PCT)
            lines.append({"label": f"discovery_handling_{item['id']}", "amount_cents": handling})
        lines.append({"label": "booth_fee", "amount_cents": booth_fee_line_cents(prog["id"])})
        lines.append({"label": "penalty_credit", "amount_cents": -(prog.get("penalty_final_cents") or 0)})
    return lines, sum(line["amount_cents"] for line in lines)
