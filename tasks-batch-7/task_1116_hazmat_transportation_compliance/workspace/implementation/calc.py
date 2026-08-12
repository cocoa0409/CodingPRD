"""Calculation rules per scaffold §1.3 / PRD §3.

All money is integer cents; every component is rounded half-up to whole cents
at the step where it is produced, then integer-summed (never sum-then-round).
Weights are summed with Decimal and compared exactly at one decimal.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import add_years, months_late, store

# --- registration_fee constants ---
TIER_BASE_SMALL = 25000
TIER_BASE_MEDIUM = 100000
TIER_BASE_LARGE = 250000
LARGE_PER_UNIT_OVER_50 = 2500
SECURITY_SURCHARGE_PCT = Decimal("0.50")
LATE_PCT_PER_MONTH = Decimal("0.10")
LATE_PCT_CAP = Decimal("0.50")
DISCOUNT_PCT_HIGH = Decimal("0.05")
DISCOUNT_RATING_HIGH = 95
DISCOUNT_PCT_MID = Decimal("0.025")
DISCOUNT_RATING_MID = 90
PROCESSING_PCT = Decimal("0.03")
PROCESSING_PCT_MIN_SUBTOTAL = 100000
PROCESSING_FLAT = 2500
REINSTATEMENT_FLAT = 75000

# --- incident_penalty constants ---
SEVERITY_BASE = {"MINOR": 0, "MAJOR": 50000, "CATASTROPHIC": 150000}
LATE_PHONE_FEE = 25000
LATE_WRITTEN_DAILY = 5000
LATE_WRITTEN_CAP = 500000
PHONE_DEADLINE = timedelta(hours=12)
WRITTEN_DEADLINE = timedelta(days=30)

# --- placard_determination constants ---
TABLE2_THRESHOLD_KG = Decimal("454.0")
DANGEROUS_THRESHOLD_KG = Decimal("2270.0")

# --- load_handling_fee constants ---
HANDLING_RATE = Decimal("0.0625")
PLACARD_FEE_CENTS = 725

# --- segregation constants ---
CLASS_1_FAMILY = {"CLASS_1_1", "CLASS_1_2", "CLASS_1_3"}

# --- training ---
EARLY_RENEWAL_WINDOW = timedelta(days=90)
TRAINING_VALIDITY_YEARS = 3

# --- safety_rating_update ---
SAFETY_POINTS = {"MINOR": 2, "MAJOR": 10, "CATASTROPHIC": 25}
RATING_FLOOR = 0

# carrier early renewal window
EARLY_RENEWAL_DAYS = timedelta(days=30)

SECURITY_PLAN_CATEGORIES = {"EXPLOSIVE", "RADIOACTIVE", "INHALATION_TOXIC"}

PG_RANK = {"PG_I": 1, "PG_II": 2, "PG_III": 3}


def rhu(dec):
    """Round half-up to whole cents, returning an int."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_of(fleet):
    if fleet <= 10:
        return "SMALL"
    if fleet <= 50:
        return "MEDIUM"
    return "LARGE"


def base_of(tier, fleet):
    if tier == "SMALL":
        return TIER_BASE_SMALL
    if tier == "MEDIUM":
        return TIER_BASE_MEDIUM
    return TIER_BASE_LARGE + LARGE_PER_UNIT_OVER_50 * (fleet - 50)


def registration_fee(fleet, security_plan_required, kind, months_late_count,
                     safety_rating, variant):
    """Tiered registration fee. Returns (tier, total_cents).

    provisional variant: declared fleet, discount always 0.
    final variant: verified fleet, safety discount applied.
    """
    tier = tier_of(fleet)
    base = base_of(tier, fleet)
    surcharge = rhu(Decimal(base) * SECURITY_SURCHARGE_PCT) if security_plan_required else 0
    late_fee = 0
    if kind == "RENEWAL":
        late_pct = min(LATE_PCT_PER_MONTH * months_late_count, LATE_PCT_CAP)
        late_fee = rhu(Decimal(base + surcharge) * late_pct)
    discount = 0
    if variant == "final":
        if safety_rating >= DISCOUNT_RATING_HIGH:
            discount = rhu(Decimal(base) * DISCOUNT_PCT_HIGH)
        elif safety_rating >= DISCOUNT_RATING_MID:
            discount = rhu(Decimal(base) * DISCOUNT_PCT_MID)
    subtotal = base + surcharge + late_fee - discount
    if subtotal >= PROCESSING_PCT_MIN_SUBTOTAL:
        processing_fee = rhu(Decimal(subtotal) * PROCESSING_PCT)
    else:
        processing_fee = PROCESSING_FLAT
    return tier, subtotal + processing_fee


def carrier_security_plan_required(carrier):
    return bool(SECURITY_PLAN_CATEGORIES.intersection(carrier["hazmat_categories"]))


def material_requires_security_plan(material):
    return (
        material["placard_table"] == "TABLE_1"
        or material["is_inhalation_hazard"]
        or material["hazard_class"] == "CLASS_7"
    )


def outstanding_balance(carrier_id):
    total = 0
    for inv in store.invoices.values():
        if inv["carrier_id"] == carrier_id and inv["status"] == "OPEN":
            total += inv["total_due_cents"] - inv["paid_cents"]
    return total


def payment_waterfall(carrier, amount_cents):
    """Allocate amount + stored credit across OPEN invoices, oldest first."""
    pool = amount_cents + carrier["credit_balance_cents"]
    targets = [
        inv for inv in store.invoices.values()
        if inv["carrier_id"] == carrier["id"] and inv["status"] == "OPEN"
    ]
    targets.sort(key=lambda i: (i["assessment_year"], i["created_at"], i["_seq"]))
    from db import touch

    for inv in targets:
        due = inv["total_due_cents"] - inv["paid_cents"]
        alloc = min(due, pool)
        if alloc <= 0:
            continue
        inv["paid_cents"] += alloc
        pool -= alloc
        if inv["paid_cents"] == inv["total_due_cents"]:
            inv["status"] = "PAID"
        touch(inv)
    carrier["credit_balance_cents"] = pool
    touch(carrier)


def training_expiry(driver_id, completed_at, new_seq):
    """training_expiry_extension: anchor to the prior record's expiry when the
    new completion falls inside the closed 90-day early-renewal window."""
    candidates = [
        r for r in store.training_records.values()
        if r["driver_id"] == driver_id and r["completed_at"] < completed_at
    ]
    prev = None
    if candidates:
        candidates.sort(key=lambda r: (r["completed_at"], r["created_at"], r["_seq"]))
        # greatest completed_at strictly before new.completed_at; ties by
        # created_at ASC (then insertion order)
        best_completed = candidates[-1]["completed_at"]
        tied = [r for r in candidates if r["completed_at"] == best_completed]
        tied.sort(key=lambda r: (r["created_at"], r["_seq"]))
        prev = tied[0]
    if prev is not None:
        window_start = prev["expires_at"] - EARLY_RENEWAL_WINDOW
        if window_start <= completed_at <= prev["expires_at"]:
            return add_years(prev["expires_at"], TRAINING_VALIDITY_YEARS)
    return add_years(completed_at, TRAINING_VALIDITY_YEARS)


def driver_posture(driver):
    """driver_qualification_posture, evaluated against the logical clock."""
    clock = store.clock
    if driver["status"] == "SUSPENDED":
        return "SUSPENDED"
    if clock > driver["hazmat_endorsement_expires_at"]:
        return "ENDORSEMENT_EXPIRED"
    for r in store.training_records.values():
        if r["driver_id"] == driver["id"] and r["expires_at"] >= clock:
            return "QUALIFIED"
    return "TRAINING_LAPSED"


def security_plan_selector(carrier_id, transport_category):
    """Winning APPROVED in-window plan covering the category, or None."""
    clock = store.clock
    cands = [
        p for p in store.security_plans.values()
        if p["carrier_id"] == carrier_id
        and p["status"] == "APPROVED"
        and transport_category in p["coverage_categories"]
        and p["effective_from"] <= clock <= p["effective_to"]
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: (p["created_at"], p["_seq"]))
    cands.sort(key=lambda p: p["approved_at"], reverse=True)  # stable: approved_at DESC, created_at ASC
    return cands[0]


def packing_group_compatible(material_pg, spec_max_pg):
    if material_pg == "PG_NONE":
        return True
    return PG_RANK[material_pg] >= PG_RANK[spec_max_pg]


def _class_forbidden(c1, c2):
    if (c1 in CLASS_1_FAMILY and c2 == "CLASS_5_1") or (
        c2 in CLASS_1_FAMILY and c1 == "CLASS_5_1"
    ):
        return True
    if {c1, c2} == {"CLASS_5_1", "CLASS_3"}:
        return True
    if {c1, c2} == {"CLASS_2_3", "CLASS_3"}:
        return True
    return False


def _group_forbidden(g1, g2):
    return {g1, g2} in ({"SG_ACID", "SG_ALKALI"}, {"SG_OXIDIZER", "SG_FLAMMABLE"})


def items_conflict(item_a, item_b):
    """item_x are (shipment, material) tuples."""
    sa, ma = item_a
    sb, mb = item_b
    if _class_forbidden(ma["hazard_class"], mb["hazard_class"]):
        return True
    if _group_forbidden(ma["segregation_group"], mb["segregation_group"]):
        return True
    return False


def load_items_of(load_id):
    items = [i for i in store.load_items.values() if i["load_id"] == load_id]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return items


def item_pairs(load_id, candidate=None):
    """(shipment, material) tuples for current items, optionally plus one
    candidate shipment not yet on the load."""
    pairs = []
    for item in load_items_of(load_id):
        shipment = store.shipments.get(item["shipment_id"])
        if shipment is None:
            continue
        material = store.materials.get(shipment["material_id"])
        pairs.append((shipment, material))
    if candidate is not None:
        pairs.append(candidate)
    return pairs


def segregation_violation(pairs):
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            if items_conflict(pairs[i], pairs[j]):
                return True
    return False


def candidate_violation(existing_pairs, candidate):
    for p in existing_pairs:
        if items_conflict(p, candidate):
            return True
    return False


def total_table2_weight(load_id):
    """Live sum of quantity_kg over items whose material is TABLE_2."""
    total = Decimal("0")
    for item in load_items_of(load_id):
        shipment = store.shipments.get(item["shipment_id"])
        if shipment is None:
            continue
        material = store.materials[shipment["material_id"]]
        if material["placard_table"] == "TABLE_2":
            total += Decimal(str(shipment["quantity_kg"]))
    return total


def placard_determination(load_id, carrier):
    pairs = item_pairs(load_id)
    p1 = {m["hazard_class"] for (_s, m) in pairs if m["placard_table"] == "TABLE_1"}
    w2 = total_table2_weight(load_id)
    table2_classes = {m["hazard_class"] for (_s, m) in pairs if m["placard_table"] == "TABLE_2"}
    p2 = set(table2_classes) if w2 >= TABLE2_THRESHOLD_KG else set()
    required = p1 | p2
    if (
        carrier["accepts_dangerous_placard_substitution"]
        and len(p2) >= 2
        and w2 >= DANGEROUS_THRESHOLD_KG
    ):
        required = p1 | {"DANGEROUS"}
    return sorted(required), w2


def load_handling_fee(load_id, required_placards):
    fee = 0
    for item in load_items_of(load_id):
        shipment = store.shipments.get(item["shipment_id"])
        if shipment is None:
            continue
        fee += rhu(Decimal(shipment["declared_value_cents"]) * HANDLING_RATE)
    fee += PLACARD_FEE_CENTS * len(required_placards)
    return fee


def incident_penalty_reported(incident):
    base = SEVERITY_BASE[incident["severity"]]
    phone_component = LATE_PHONE_FEE if is_phone_late(incident) else 0
    written_component = _written_component(incident)
    return base + phone_component + written_component


def incident_penalty_confirmed(incident, confirmed_severity, adjustment_percent):
    base = SEVERITY_BASE[confirmed_severity]
    phone_component = LATE_PHONE_FEE if is_phone_late(incident) else 0
    written_component = _written_component(incident)
    multiplier = Decimal("1") + Decimal(str(adjustment_percent)) / Decimal("100")
    return rhu(Decimal(base + phone_component + written_component) * multiplier)


def _written_component(incident):
    filed = incident["written_filed_at"]
    if filed is None:
        return 0
    days_late = max(
        0, int((filed - incident["written_report_deadline"]).total_seconds()) // 86400
    )
    return min(LATE_WRITTEN_DAILY * days_late, LATE_WRITTEN_CAP)


def is_phone_late(incident):
    if not incident["phone_report_required"]:
        return False
    reported = incident["phone_reported_at"]
    return reported is None or reported > incident["phone_deadline"]


def is_written_late(incident):
    filed = incident["written_filed_at"]
    if filed is None:
        return False
    return filed > incident["written_report_deadline"]
