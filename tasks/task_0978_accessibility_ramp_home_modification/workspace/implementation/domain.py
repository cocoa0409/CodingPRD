"""Domain logic: calculations, ledger recomputation, state helpers, time-driven tick."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import (
    db, now, now_iso, iso, touch, new_record, next_number,
    round_half_up_cents,
)

# ----------------------------- constants --------------------------

ACTIVE_QUOTE_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED")
BILLED_INVOICE_STATUSES = ("SENT", "PARTIALLY_PAID", "PAID", "OVERDUE", "DISPUTED")
FUNDED_SOURCE_STATUSES = ("APPROVED", "EXHAUSTED")
ACTIVE_RENTAL_STATUSES = ("RESERVED", "DELIVERED", "INSTALLED", "IN_USE", "PICKUP_SCHEDULED")
NONTERMINAL_JOB_STATUSES = ("SCHEDULED", "MATERIALS_ORDERED", "IN_PROGRESS", "PUNCH_LIST")

EQUIPMENT_LINE_TYPES = ("EQUIPMENT_RENTAL", "EQUIPMENT_PURCHASE")
RENTAL_LINE_TYPES = ("EQUIPMENT_RENTAL",)
NO_RENTAL_RESTRICTIONS = ("NO_RENTAL", "PERMANENT_ONLY")

CASE_CORRIDOR = [
    "INTAKE", "ASSESSMENT_SCHEDULED", "ASSESSED", "QUOTE_DRAFTED",
    "QUOTE_SUBMITTED", "FUNDING_PENDING", "FUNDING_APPROVED",
    "INSTALLATION_SCHEDULED", "INSTALLED", "INSPECTED", "WARRANT_ACTIVE",
    "CLOSED",
]


# ----------------------------- case ledger ------------------------

def _quotes_of(case_id):
    return [q for q in db["quotes"].values() if q["case_id"] == case_id]


def _sources_of(case_id):
    return [s for s in db["funding_sources"].values() if s["case_id"] == case_id]


def _invoices_of(case_id):
    return [i for i in db["invoices"].values() if i["case_id"] == case_id]


def recompute_case_totals(case):
    cid = case["id"]
    quoted = sum(q["total_cents"] for q in _quotes_of(cid)
                 if q["status"] in ACTIVE_QUOTE_STATUSES)
    funded = sum((s.get("approved_cents") or 0) for s in _sources_of(cid)
                 if s["status"] in FUNDED_SOURCE_STATUSES)
    billed = sum(i["total_cents"] for i in _invoices_of(cid)
                 if i["status"] in BILLED_INVOICE_STATUSES)
    paid = sum(i["amount_paid_cents"] for i in _invoices_of(cid)
               if i["status"] in BILLED_INVOICE_STATUSES)
    case["total_quoted_cents"] = quoted
    case["total_funded_cents"] = funded
    case["total_billed_cents"] = billed
    case["total_paid_cents"] = paid
    case["balance_due_cents"] = max(0, billed - paid)
    if funded == 0:
        posture = "UNFUNDED"
    elif funded < quoted:
        posture = "PARTIALLY_FUNDED"
    elif funded == quoted:
        posture = "FULLY_FUNDED"
    else:
        posture = "OVERFUNDED"
    case["funding_posture"] = posture


def mutate_case(case):
    recompute_case_totals(case)
    touch(case)


def _latest_open_quote(case_id):
    """Most recent quote in SUBMITTED/UNDER_REVIEW (fallback APPROVED)."""
    qs = [q for q in _quotes_of(case_id) if q["status"] in ("SUBMITTED", "UNDER_REVIEW")]
    if not qs:
        qs = [q for q in _quotes_of(case_id) if q["status"] == "APPROVED"]
    if not qs:
        return None
    return max(qs, key=lambda q: (q["_created_dt"], q["_seq"]))


def advance_case_funding(case):
    """QUOTE_SUBMITTED -> FUNDING_PENDING -> FUNDING_APPROVED progression."""
    if case["status"] not in ("QUOTE_SUBMITTED", "FUNDING_PENDING"):
        return
    q = _latest_open_quote(case["id"])
    if q is not None and case["total_funded_cents"] >= q["total_cents"]:
        case["status"] = "FUNDING_APPROVED"
    elif case["status"] == "QUOTE_SUBMITTED" and _sources_of(case["id"]):
        case["status"] = "FUNDING_PENDING"


# ----------------------------- calculations -----------------------

def safety_risk_index(hazard_count, mobility_score):
    risk = Decimal(str(hazard_count)) * Decimal("0.5") + \
        (Decimal("100") - Decimal(str(mobility_score))) * Decimal("0.05")
    if risk < 0:
        risk = Decimal("0")
    if risk > 10:
        risk = Decimal("10")
    return float(risk.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


ADA_WEIGHTS = (
    ("entrance_access", Decimal("0.25")),
    ("interior_circulation", Decimal("0.20")),
    ("bathroom_access", Decimal("0.25")),
    ("kitchen_access", Decimal("0.15")),
    ("bedroom_access", Decimal("0.15")),
)


def ada_compliance_pct(factors, fallback_score):
    """Weighted sum of the five factor scores; missing factors fall back."""
    total = Decimal("0")
    for name, weight in ADA_WEIGHTS:
        v = factors.get(name)
        if v is None:
            v = fallback_score
        total += Decimal(str(v)) * weight
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rental_tier_multiplier(months):
    if months <= 3:
        return Decimal("1.00")
    if months <= 6:
        return Decimal("0.90")
    if months <= 12:
        return Decimal("0.80")
    return Decimal("0.70")


def rental_months(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        months += 1
    return max(1, months)


def rental_rate_and_deposit(unit, start, end):
    months = rental_months(start, end)
    base = Decimal(str(unit["monthly_rate_cents"]))
    rate = round_half_up_cents(base * rental_tier_multiplier(months))
    two_months = 2 * rate
    cap = round_half_up_cents(
        Decimal(str(unit["purchase_price_cents"])) * Decimal("20") / Decimal("100"))
    return rate, min(two_months, cap)


def compute_quote_totals(quote):
    lines = [li for li in db["quote_line_items"].values()
             if li["quote_id"] == quote["id"]]
    labor = sum(li["extended_price_cents"] for li in lines if li["line_type"] == "LABOR")
    material = sum(li["extended_price_cents"] for li in lines if li["line_type"] == "MATERIAL")
    permit = sum(li["extended_price_cents"] for li in lines if li["line_type"] == "PERMIT")
    equipment = sum(li["extended_price_cents"] for li in lines
                    if li["line_type"] in EQUIPMENT_LINE_TYPES)
    subtotal = sum(li["extended_price_cents"] for li in lines)
    contingency = round_half_up_cents(
        Decimal(subtotal) * Decimal(str(quote["contingency_pct"])) / Decimal("100"))
    quote["labor_cost_cents"] = labor
    quote["material_cost_cents"] = material
    quote["permit_fee_cents"] = permit
    quote["equipment_cost_cents"] = equipment
    quote["subtotal_cents"] = subtotal
    quote["contingency_cents"] = contingency
    quote["total_cents"] = subtotal + contingency - quote.get("discount_cents", 0)
    return quote


def compute_invoice_totals(invoice):
    lines = [li for li in db["invoice_line_items"].values()
             if li["invoice_id"] == invoice["id"]]
    subtotal = sum(li["extended_price_cents"] for li in lines)
    tax = sum(li["tax_cents"] for li in lines)
    invoice["subtotal_cents"] = subtotal
    invoice["tax_cents"] = tax
    invoice["total_cents"] = subtotal + tax
    invoice["balance_cents"] = invoice["total_cents"] - invoice["amount_paid_cents"]
    return invoice


def quote_line_amounts(quantity, unit_price_cents, is_taxable, tax_rate_pct):
    ext = round_half_up_cents(Decimal(str(quantity)) * Decimal(str(unit_price_cents)))
    if is_taxable:
        tax = round_half_up_cents(
            Decimal(ext) * Decimal(str(tax_rate_pct)) / Decimal("100"))
    else:
        tax = 0
    return ext, tax


def invoice_line_amounts(quantity, unit_price_cents, tax_rate_pct):
    ext = round_half_up_cents(Decimal(str(quantity)) * Decimal(str(unit_price_cents)))
    tax = round_half_up_cents(Decimal(ext) * Decimal(str(tax_rate_pct)) / Decimal("100"))
    return ext, tax, ext + tax


def rental_prorated_amount(monthly_rate_cents, days, ref_dt):
    days_in_month = _days_in_month(ref_dt.year, ref_dt.month)
    return round_half_up_cents(
        Decimal(str(monthly_rate_cents)) * Decimal(days) / Decimal(days_in_month))


def _days_in_month(year, month):
    if month == 12:
        nxt = (year + 1, 1)
    else:
        nxt = (year, month + 1)
    from datetime import date
    first = date(year, month, 1)
    nxt_first = date(nxt[0], nxt[1], 1)
    return (nxt_first - first).days


def add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, _days_in_month(y, m))
    return dt.replace(year=y, month=m, day=d)


# ----------------------------- funding helpers --------------------

def release_pending_allocations_for_quote(quote_id):
    for a in db["funding_allocations"].values():
        if a["quote_id"] == quote_id and a["status"] == "PENDING":
            a["status"] = "RELEASED"
            touch(a)


def release_pending_allocations_for_source(source_id):
    for a in db["funding_allocations"].values():
        if a["funding_source_id"] == source_id and a["status"] == "PENDING":
            a["status"] = "RELEASED"
            touch(a)


def _maybe_exhaust(source):
    if source["status"] == "APPROVED" and \
            (source.get("remaining_cents") or 0) == 0:
        source["status"] = "EXHAUSTED"
        touch(source)


def commit_allocation(allocation, source):
    allocation["status"] = "COMMITTED"
    allocation["committed_at"] = now_iso()
    touch(allocation)
    source["remaining_cents"] = (source.get("remaining_cents") or 0) - \
        allocation["amount_cents"]
    touch(source)
    _maybe_exhaust(source)


def source_has_rental_restriction(source):
    restrictions = source.get("restrictions") or []
    return any(r in NO_RENTAL_RESTRICTIONS for r in restrictions)


def quote_rental_exposure(quote):
    """Extended-price total of rental line items on the quote."""
    return sum(li["extended_price_cents"]
               for li in db["quote_line_items"].values()
               if li["quote_id"] == quote["id"]
               and li["line_type"] in RENTAL_LINE_TYPES)


def run_funding_waterfall(case, quote, need_cents):
    """Create COMMITTED allocations against APPROVED sources, priority order.

    Returns list of (allocation) created. Raises nothing; caller checks
    feasibility first via waterfall_capacity."""
    sources = [s for s in _sources_of(case["id"])
               if s["status"] == "APPROVED" and (s.get("remaining_cents") or 0) > 0]
    sources.sort(key=lambda s: (s.get("priority_rank") or 0, s["_created_dt"], s["_seq"]))
    rental_exposure = quote_rental_exposure(quote)
    created = []
    remaining_need = need_cents
    for s in sources:
        if remaining_need <= 0:
            break
        cap = s["remaining_cents"]
        if source_has_rental_restriction(s):
            non_rental_room = max(0, quote["total_cents"] - rental_exposure)
            already = sum(a["amount_cents"]
                          for a in db["funding_allocations"].values()
                          if a["funding_source_id"] == s["id"]
                          and a["quote_id"] == quote["id"]
                          and a["status"] in ("PENDING", "COMMITTED"))
            cap = min(cap, max(0, non_rental_room - already))
        if cap <= 0:
            continue
        amount = min(cap, remaining_need)
        alloc = new_record()
        alloc.update({
            "funding_source_id": s["id"],
            "quote_id": quote["id"],
            "quote_line_item_id": None,
            "amount_cents": amount,
            "allocation_type": "QUOTE_LEVEL",
            "status": "PENDING",
            "committed_at": None,
        })
        db["funding_allocations"][alloc["id"]] = alloc
        commit_allocation(alloc, s)
        created.append(alloc)
        remaining_need -= amount
    return created


def waterfall_capacity(case, quote, need_cents):
    """How much the waterfall could supply toward need_cents."""
    sources = [s for s in _sources_of(case["id"])
               if s["status"] == "APPROVED" and (s.get("remaining_cents") or 0) > 0]
    rental_exposure = quote_rental_exposure(quote)
    total = 0
    for s in sources:
        cap = s["remaining_cents"]
        if source_has_rental_restriction(s):
            non_rental_room = max(0, quote["total_cents"] - rental_exposure)
            already = sum(a["amount_cents"]
                          for a in db["funding_allocations"].values()
                          if a["funding_source_id"] == s["id"]
                          and a["quote_id"] == quote["id"]
                          and a["status"] in ("PENDING", "COMMITTED"))
            cap = min(cap, max(0, non_rental_room - already))
        total += max(0, cap)
    return min(total, need_cents)


# ----------------------------- human-readable numbers -------------

def make_quote_number():
    day, n = next_number("Q")
    return f"Q-{day}-{n:03d}"


def make_job_number():
    day, n = next_number("JOB")
    return f"JOB-{day}-{n:03d}"


def make_invoice_number():
    day, n = next_number("INV")
    return f"INV-{day}-{n:03d}"


def make_claim_number():
    day, n = next_number("WC")
    return f"WC-{day}-{n:03d}"


# ----------------------------- time-driven transitions ------------

def tick():
    """Apply all clock-driven transitions. Runs before every request."""
    ts = now()

    for q in db["quotes"].values():
        if q["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            vu = q.get("_valid_until_dt")
            if vu is not None and ts > vu:
                q["status"] = "EXPIRED"
                touch(q)
                release_pending_allocations_for_quote(q["id"])

    for inv in db["invoices"].values():
        if inv["status"] in ("SENT", "PARTIALLY_PAID"):
            due = inv.get("_due_date_dt")
            if due is not None and ts > due and inv["balance_cents"] > 0:
                inv["status"] = "OVERDUE"
                touch(inv)

    for c in db["ot_consultations"].values():
        if c["status"] == "SCHEDULED":
            sd = c.get("_scheduled_date_dt")
            if sd is not None and ts > sd:
                c["status"] = "NO_SHOW"
                touch(c)

    for s in db["reassessment_schedules"].values():
        if s["status"] in ("PENDING", "SCHEDULED"):
            dd = s.get("_due_date_dt")
            if dd is not None and ts > dd:
                s["status"] = "OVERDUE"
                touch(s)

    for r in db["rental_ramps"].values():
        if r["status"] == "INSTALLED":
            start = r.get("_rental_start_dt")
            end = r.get("_rental_end_dt")
            if start is not None and end is not None and start <= ts <= end:
                r["status"] = "IN_USE"
                touch(r)

    for src in db["funding_sources"].values():
        _maybe_exhaust(src)
