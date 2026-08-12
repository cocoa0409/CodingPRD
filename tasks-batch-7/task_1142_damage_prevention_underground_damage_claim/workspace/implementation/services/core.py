"""Core business logic: calculations, cascades, recomputes, sweeps."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import db

# ---- Constants from the scaffold calculations table ----

MARKUP_PCT = {
    "LABOR": Decimal("0.15"),
    "MATERIAL": Decimal("0.10"),
    "EQUIPMENT": Decimal("0.12"),
    "RESTORATION": Decimal("0.08"),
}
EMERGENCY_MULT_CRITICAL = Decimal("1.25")
LINE_CAP_CENTS = 500000

STANDARD_UNIT_RATES = {
    "LABOR": 9500,
    "MATERIAL": 4000,
    "EQUIPMENT": 15000,
    "RESTORATION": 6000,
}

POINTS = {"MINOR": 2, "MAJOR": 4, "CRITICAL": 6}
WATCH_THRESHOLD = 6
PROBATION_THRESHOLD = 12
SUSPENDED_THRESHOLD = 18
HALF_LIFE_DAYS = 365
ZERO_DAYS = 1095

INVOICE_AUTHORITY_CAP_CENTS = 5000000
WRITE_OFF_MAX_CENTS = 20000

PENALTY_BASE_CENTS = 5000
PENALTY_PER_DAY_CENTS = 500
PENALTY_CAP_CENTS = 100000
FILING_WINDOW_DAYS = 30

STALE_MARKS_DAYS = 14

DEFAULT_SHARES = {
    "NO_TICKET": [("EXCAVATOR", 10000)],
    "EXPIRED_TICKET": [("EXCAVATOR", 8000), ("FACILITY_OWNER", 2000)],
    "MISMARK": [("LOCATOR", 7000), ("EXCAVATOR", 3000)],
    "LOCATE_LATE": [("LOCATOR", 6000), ("EXCAVATOR", 4000)],
    "OWNER_ABANDONED": [("FACILITY_OWNER", 10000)],
}

EVENT_KIND_ORDER = {
    "TICKET_SUBMITTED": 0,
    "RESPONSE_SUBMITTED": 1,
    "EVIDENCE_CAPTURED": 2,
    "DAMAGE_OCCURRED": 3,
}


def round_half_up_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- Entity touch helpers ----

def touch(entity):
    """Refresh updated_at and bump version on a common-fields entity."""
    entity["updated_at"] = clock.get_current_utc()
    entity["version"] = entity.get("version", 1) + 1


# ---- Derived recomputes ----

def recompute_case_subtotal(case):
    total = 0
    for cli in db.cost_line_items.values():
        if cli["damage_case_id"] == case["id"]:
            total += cli["line_total_cents"]
    case["subtotal_cents"] = total


def recompute_case_totals(case):
    total_invoiced = 0
    total_recovered = 0
    for inv in db.claim_invoices.values():
        if inv["damage_case_id"] == case["id"]:
            total_invoiced += inv["invoiced_cents"]
            total_recovered += inv["amount_paid_cents"]
    case["total_invoiced_cents"] = total_invoiced
    case["total_recovered_cents"] = total_recovered


def recompute_invoice_amount_due(inv):
    inv["amount_due_cents"] = inv["invoiced_cents"] - inv["amount_paid_cents"]


def recompute_debtor_outstanding(debtor_type, debtor_id):
    """Excavator.total_outstanding_cents = sum amount_due over invoices in
    ISSUED/PARTIALLY_PAID/DISPUTED. Only Excavator carries that field."""
    if debtor_type != "EXCAVATOR":
        return
    exc = db.excavators.get(debtor_id)
    if exc is None:
        return
    total = 0
    for inv in db.claim_invoices.values():
        if (inv["debtor_type"] == "EXCAVATOR" and inv["debtor_id"] == debtor_id
                and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "DISPUTED")):
            total += inv["amount_due_cents"]
    exc["total_outstanding_cents"] = total


def recompute_locator_performance(locator):
    accurate = 0
    audited = 0
    for resp in db.locate_responses.values():
        if resp["locator_id"] == locator["id"] and resp["accuracy_verdict"] in ("ACCURATE", "INACCURATE"):
            audited += 1
            if resp["accuracy_verdict"] == "ACCURATE":
                accurate += 1
    if audited == 0:
        locator["performance_score_bp"] = 10000
    else:
        locator["performance_score_bp"] = (10000 * accurate) // audited


def violation_effective_points(violation, now=None):
    if now is None:
        now = clock.get_current_utc()
    base = violation["points"]
    age_seconds = (now - violation["created_at"]).total_seconds()
    age_days = int(age_seconds // 86400)
    if age_days < HALF_LIFE_DAYS:
        return base
    if age_days <= ZERO_DAYS:
        return base // 2
    return 0


def recompute_offender_points(excavator, now=None):
    total = 0
    for v in db.violation_records.values():
        if v["excavator_id"] == excavator["id"] and v["status"] == "ACTIVE":
            total += violation_effective_points(v, now)
    excavator["offender_points"] = total
    return total


def band_for_points(points):
    if points >= SUSPENDED_THRESHOLD:
        return "SUSPENDED"
    if points >= PROBATION_THRESHOLD:
        return "PROBATION"
    if points >= WATCH_THRESHOLD:
        return "WATCH"
    return "GOOD_STANDING"


BAND_RANK = {"GOOD_STANDING": 0, "WATCH": 1, "PROBATION": 2, "SUSPENDED": 3}


def run_training_selector(excavator, new_band):
    """Auto-create TrainingAssignments for courses matching the new band.
    course_code ASC order; skip candidates with an existing ASSIGNED assignment."""
    if new_band not in ("PROBATION", "SUSPENDED"):
        return
    courses = [c for c in db.training_courses.values() if c["required_for_status"] == new_band]
    courses.sort(key=lambda c: c["course_code"])
    for course in courses:
        already = any(
            a["excavator_id"] == excavator["id"] and a["course_id"] == course["id"] and a["status"] == "ASSIGNED"
            for a in db.training_assignments.values()
        )
        if already:
            continue
        create_training_assignment(excavator["id"], course["id"])


def create_training_assignment(excavator_id, course_id):
    from util import new_id
    now = clock.get_current_utc()
    aid = new_id()
    assignment = {
        "id": aid,
        "excavator_id": excavator_id,
        "course_id": course_id,
        "status": "ASSIGNED",
        "due_at": now + timedelta(days=90),
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.training_assignments[aid] = assignment
    return assignment


def evaluate_program(excavator):
    """Recompute score and apply band. Upgrades free; downgrades gated by training."""
    points = recompute_offender_points(excavator)
    new_band = band_for_points(points)
    current = excavator["program_status"]
    if BAND_RANK[new_band] > BAND_RANK[current]:
        # upgrade to worse band: free
        excavator["program_status"] = new_band
        touch(excavator)
        if new_band in ("PROBATION", "SUSPENDED"):
            run_training_selector(excavator, new_band)
    elif BAND_RANK[new_band] < BAND_RANK[current]:
        # downgrade to better band: gated when leaving PROBATION or SUSPENDED
        if current in ("PROBATION", "SUSPENDED"):
            gate_ok = True
            for a in db.training_assignments.values():
                if a["excavator_id"] != excavator["id"]:
                    continue
                course = db.training_courses.get(a["course_id"])
                if course is None:
                    continue
                if course["required_for_status"] == current and a["status"] != "COMPLETED":
                    gate_ok = False
                    break
            if gate_ok:
                excavator["program_status"] = new_band
                touch(excavator)
            # else hold silently
        else:
            excavator["program_status"] = new_band
            touch(excavator)
    return excavator


# ---- Cost lines ----

def compute_line_total(category, quantity, unit_cost_cents, severity):
    markup = MARKUP_PCT[category]
    mult = EMERGENCY_MULT_CRITICAL if severity == "CRITICAL" else Decimal("1.00")
    raw = Decimal(str(quantity)) * Decimal(unit_cost_cents) * (Decimal(1) + markup) * mult
    rounded = round_half_up_cents(raw)
    return min(LINE_CAP_CENTS, rounded)


def compute_standard_line_total(category, quantity, severity):
    return compute_line_total(category, quantity, STANDARD_UNIT_RATES[category], severity)


# ---- Allocation distribution (waterfall with remainder absorption) ----

def allocate_shares(subtotal_cents, shares):
    """shares: list of dicts with share_bp. Returns list of invoiced cents in
    the same order as shares (0 for share_bp == 0)."""
    n = len(shares)
    result = [0] * n
    nonzero = [(i, s) for i, s in enumerate(shares) if s["share_bp"] > 0]
    if not nonzero:
        return result
    # largest: max share_bp, tie -> lowest index
    largest_idx = nonzero[0][0]
    for i, s in nonzero:
        if s["share_bp"] > shares[largest_idx]["share_bp"]:
            largest_idx = i
    allocated_sum = 0
    for i, s in nonzero:
        if i == largest_idx:
            continue
        amt = round_half_up_cents(Decimal(subtotal_cents) * Decimal(s["share_bp"]) / Decimal(10000))
        result[i] = amt
        allocated_sum += amt
    result[largest_idx] = subtotal_cents - allocated_sum
    return result


# ---- Invoice status from paid ----

def invoice_status_from_paid(inv):
    paid = inv["amount_paid_cents"]
    if paid <= 0:
        return "ISSUED"
    if paid < inv["invoiced_cents"]:
        return "PARTIALLY_PAID"
    return "PAID"


def maybe_advance_case_recovery(case):
    """After an invoice status change, recompute case recovery_status."""
    invoices = [i for i in db.claim_invoices.values() if i["damage_case_id"] == case["id"]]
    if not invoices:
        return
    recompute_case_totals(case)
    if case["recovery_status"] in ("INVOICED", "COLLECTING", "RECOVERED"):
        if all(i["status"] in ("PAID", "WRITTEN_OFF") for i in invoices):
            case["recovery_status"] = "RECOVERED"
        elif any(i["amount_paid_cents"] > 0 for i in invoices):
            if case["recovery_status"] in ("INVOICED", "RECOVERED"):
                case["recovery_status"] = "COLLECTING"


# ---- Expiry sweep ----

def expiry_sweep():
    now = clock.get_current_utc()
    for t in db.locate_tickets.values():
        if t["status"] == "OPEN" and now > t["work_end_at"]:
            t["status"] = "EXPIRED"
            t["updated_at"] = now
            t["version"] += 1
    for d in db.disputes.values():
        if d["status"] == "OPEN" and now > d["response_deadline_at"]:
            d["status"] = "EXPIRED"
            d["updated_at"] = now
            d["version"] += 1
            # target ClaimInvoice leaves DISPUTED
            if d["target_type"] == "CLAIM_INVOICE":
                inv = db.claim_invoices.get(d["target_id"])
                if inv is not None and inv["status"] == "DISPUTED":
                    # only if no other open disputes remain on it
                    if not has_open_dispute(inv["id"]):
                        inv["status"] = invoice_status_from_paid(inv)
                        recompute_invoice_amount_due(inv)
                        touch(inv)
                        case = db.damage_cases.get(inv["damage_case_id"])
                        if case is not None:
                            maybe_advance_case_recovery(case)
                            recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])
    for a in db.training_assignments.values():
        if a["status"] == "ASSIGNED" and now > a["due_at"]:
            a["status"] = "EXPIRED"
            a["updated_at"] = now
            a["version"] += 1
    # repeat_offender_score decay is clock-dependent: refresh stored points
    for exc in db.excavators.values():
        recompute_offender_points(exc, now)


def has_open_dispute(invoice_id):
    for d in db.disputes.values():
        if d["target_type"] == "CLAIM_INVOICE" and d["target_id"] == invoice_id \
                and d["status"] in ("OPEN", "UNDER_REVIEW", "COUNTERED"):
            return True
    return False


def has_open_dispute_on_allocation(alloc_id):
    for d in db.disputes.values():
        if d["target_type"] == "FAULT_ALLOCATION" and d["target_id"] == alloc_id \
                and d["status"] in ("OPEN", "UNDER_REVIEW", "COUNTERED"):
            return True
    return False
