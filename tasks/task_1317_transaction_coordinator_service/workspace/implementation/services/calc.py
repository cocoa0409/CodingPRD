"""Calculation rules (scaffold table 3): fees, invoice totals, due dates,
reminder schedules, compliance audit, subscription commitment."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, mint, touch, fmt_dt
from util import parse_date

UTC = timezone.utc

BASE_FEE_CENTS = {"PURCHASE_SALE": 39500, "LISTING_ONLY": 29500}
RUSH_THRESHOLD_DAYS = 10
RUSH_SURCHARGE_CENTS = 7500
FREE_AMENDMENTS = 1
AMENDMENT_FEE_CENTS = 5000
SUBSCRIPTION_DISCOUNT_PCT = Decimal("0.05")
BUSINESS_DAY_STATES = {"NY"}
REMINDER_OFFSETS_DAYS = [5, 2, 0]
REMINDER_HOUR_UTC = 9
MIN_CLOSING_GAP_DAYS = 2
STATE_REQUIRED_DISCLOSURES = {
    "TX": ["T47_DISCLOSURE"],
    "NY": ["NHD_REPORT"],
    "CA": ["TDS_DISCLOSURE", "NHD_REPORT"],
    "CO": [],
}


# ---- deadline_due_date ----
def day_convention(state_code):
    return "BUSINESS" if state_code in BUSINESS_DAY_STATES else "CALENDAR"


def _add_business_days(d, n):
    # day 0 = effective_date itself; count starts on the day after; Mon-Fri only.
    cur = d
    left = n
    while left > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            left -= 1
    return cur


def deadline_due_date(effective_date_str, offset_days, state_code):
    eff = parse_date(effective_date_str)
    if state_code in BUSINESS_DAY_STATES:
        return _add_business_days(eff, offset_days).isoformat()
    return (eff + timedelta(days=offset_days)).isoformat()


def milestone_due_date(effective_date_str, offset_days):
    # Milestones always use calendar days.
    return (parse_date(effective_date_str) + timedelta(days=offset_days)).isoformat()


# ---- reminder_schedule ----
def create_reminders(deadline):
    """Create future QUEUED reminders for a PENDING deadline; sequence_no 1..k
    ascending by scheduled_at. SENT reminders elsewhere are never touched here."""
    d = parse_date(deadline["due_date"])
    base = datetime(d.year, d.month, d.day, REMINDER_HOUR_UTC, 0, 0, tzinfo=UTC)
    candidates = sorted(base - timedelta(days=n) for n in REMINDER_OFFSETS_DAYS)
    seq = 0
    for sched in candidates:
        if sched > store.now:  # strictly after current clock time
            seq += 1
            rec = mint({
                "deadline_id": deadline["id"],
                "sequence_no": seq,
                "scheduled_at": fmt_dt(sched),
                "sent_at": None,
                "status": "QUEUED",
            })
            store.reminders[rec["id"]] = rec


def cancel_queued_reminders(deadline_id):
    for r in store.reminders.values():
        if r["deadline_id"] == deadline_id and r["status"] == "QUEUED":
            r["status"] = "CANCELLED"
            touch(r)


def regenerate_reminders(deadline):
    """Amendment EFFECTIVE: QUEUED -> CANCELLED, new future ones created;
    SENT preserved and not counted toward the new sequence."""
    cancel_queued_reminders(deadline["id"])
    create_reminders(deadline)


# ---- subscription_commitment ----
def commit_subscription_slot(sub, file_rec):
    """Evaluate within-quota BEFORE applying the commitment (strict <), freeze the
    verdict on the file, then increment the counter and bump subscription version."""
    file_rec["_within_quota"] = sub["included_files_used"] < sub["included_files_quota"]
    sub["included_files_used"] += 1
    touch(sub)


# ---- file_fee_estimate ----
def fee_estimate(file_rec):
    activation_date = store.now.date()
    closing = parse_date(file_rec["closing_date"])
    rush = RUSH_SURCHARGE_CENTS if (closing - activation_date).days < RUSH_THRESHOLD_DAYS else 0
    if file_rec["billing_model"] == "PER_FILE":
        base = BASE_FEE_CENTS[file_rec["contract_type"]]
        fee = base + rush
        lines = [{"label": "BASE_FEE", "amount_cents": base}]
        if rush:
            lines.append({"label": "RUSH_SURCHARGE", "amount_cents": rush})
    else:
        sub = store.subscriptions[file_rec["subscription_id"]]
        if file_rec["_within_quota"]:
            fee = 0
            lines = [{"label": "SUBSCRIPTION_INCLUDED", "amount_cents": 0}]
        else:
            fee = sub["overage_fee_cents"] + rush
            lines = [{"label": "SUBSCRIPTION_OVERAGE", "amount_cents": sub["overage_fee_cents"]}]
            if rush:
                lines.append({"label": "RUSH_SURCHARGE", "amount_cents": rush})
    return fee, lines, rush


# ---- file_fee_final ----
def fee_final(file_rec):
    effective = [a for a in store.amendments.values()
                 if a["file_id"] == file_rec["id"] and a["status"] == "EFFECTIVE"]
    amendment_fee = max(0, len(effective) - FREE_AMENDMENTS) * AMENDMENT_FEE_CENTS
    rush = file_rec.get("_rush_cents", 0)
    if file_rec["billing_model"] == "PER_FILE":
        base_component = BASE_FEE_CENTS[file_rec["contract_type"]]
        lines = [{"label": "BASE_FEE", "amount_cents": base_component}]
    else:
        if file_rec["_within_quota"]:
            base_component = 0
            lines = [{"label": "SUBSCRIPTION_INCLUDED", "amount_cents": 0}]
        else:
            base_component = store.subscriptions[file_rec["subscription_id"]]["overage_fee_cents"]
            lines = [{"label": "SUBSCRIPTION_OVERAGE", "amount_cents": base_component}]
    if rush:
        lines.append({"label": "RUSH_SURCHARGE", "amount_cents": rush})
    if amendment_fee:
        lines.append({"label": "AMENDMENT_FEE", "amount_cents": amendment_fee})
    return base_component + rush + amendment_fee, lines


# ---- invoice_total ----
def invoice_totals(billing_model, lines):
    subtotal = sum(l["amount_cents"] for l in lines)
    if billing_model == "SUBSCRIPTION":
        discount = int((Decimal(subtotal) * SUBSCRIPTION_DISCOUNT_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        discount = 0
    return subtotal, discount, subtotal - discount


def build_invoice(file_rec, lines):
    subtotal, discount, total = invoice_totals(file_rec["billing_model"], lines)
    rec = mint({
        "file_id": file_rec["id"],
        "subscription_id": file_rec.get("subscription_id"),
        "line_items": lines,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "status": "DRAFT",
        "issued_at": None,
    })
    store.invoices[rec["id"]] = rec
    return rec


def rebuild_invoice(file_rec, invoice, lines, issued_now=True):
    subtotal, discount, total = invoice_totals(file_rec["billing_model"], lines)
    invoice["line_items"] = lines
    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["total_cents"] = total
    if invoice["status"] == "DRAFT":
        invoice["status"] = "ISSUED"
        invoice["issued_at"] = fmt_dt(store.now)
    touch(invoice)


# ---- compliance_audit ----
def run_audit(file_rec):
    required = []
    tpl = store.templates.get(file_rec.get("template_id"))
    if tpl is not None:
        required.extend(tpl["required_doc_types"])
    required.extend(STATE_REQUIRED_DISCLOSURES.get(file_rec["state_code"], []))
    seen = set()
    required_set = []
    for dt in required:
        if dt not in seen:
            seen.add(dt)
            required_set.append(dt)
    accepted_types = {d["doc_type"] for d in store.documents.values()
                      if d["file_id"] == file_rec["id"] and d["status"] == "ACCEPTED"}
    missing = [dt for dt in required_set if dt not in accepted_types]
    result = "PASS" if not missing else "FAIL"
    if file_rec["last_audit_status"] != result:
        file_rec["last_audit_status"] = result
        touch(file_rec)
    return {"result": result, "missing_doc_types": missing}


def file_of_invoice(inv):
    return store.files.get(inv["file_id"])
