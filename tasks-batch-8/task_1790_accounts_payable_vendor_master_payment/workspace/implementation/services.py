"""Business logic: name normalization, similarity, screening, cascades,
approval routing, discount math, run totals, dormancy sweep, audit trail."""
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import TIER_ROLE

# --- calculation constants (scaffold 1.3) ---
SUFFIX_TOKENS = {"INC", "LLC", "CORP", "CORPORATION", "COMPANY", "CO", "LTD", "LP", "LLP", "PLLC", "PC"}
DUP_HARD_BLOCK_THRESHOLD = Decimal("0.9000")
DUP_REVIEW_THRESHOLD = Decimal("0.7500")
SCREEN_FUZZY_THRESHOLD = Decimal("0.8000")
NEW_VENDOR_DAYS = 30
BANK_RECENT_HOURS = 72
MAX_TIER = 3
WIRE_FEE_CENTS = 2500
DORMANCY_DAYS = 180
DORMANT_DEACTIVATE_DAYS = 90
CALLBACK_MAX_ATTEMPTS = 3
CALLBACK_EXPIRY_HOURS = 48
TREASURY_DAILY_LIMIT_CENTS = 10000000

OPEN_INVOICE_STATUSES = ("RECEIVED", "PENDING_APPROVAL", "APPROVED", "IN_PAYMENT_RUN", "ON_HOLD")


# =========================================================================
# audit trail (append-only)
# =========================================================================

def audit(entity_type, entity_id, event_type, ctx, field_name=None, old_value=None, new_value=None):
    ev = {
        "id": db.new_id(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "field_name": field_name,
        "old_value": None if old_value is None else str(old_value),
        "new_value": None if new_value is None else str(new_value),
        "actor_user_id": ctx.user_id,
        "actor_role": ctx.role,
        "created_at": db.fmt_ts(db.now()),
    }
    db.audit_events[ev["id"]] = ev
    return ev


def audit_status_change(entity_type, entity_id, old_status, new_status, ctx):
    return audit(entity_type, entity_id, "STATUS_CHANGE", ctx,
                 field_name="status", old_value=old_status, new_value=new_status)


# =========================================================================
# name normalization + similarity (PRD 2.10)
# =========================================================================

def normalize_name(raw):
    up = raw.upper()
    cleaned = re.sub(r"[^A-Z0-9]", " ", up)
    tokens = [t for t in cleaned.split() if t not in SUFFIX_TOKENS]
    return "".join(tokens)


def _trigrams(s):
    if len(s) < 3:
        return {s}
    return {s[i:i + 3] for i in range(len(s) - 2)}


def name_similarity(name_a, name_b):
    """Dice coefficient over character trigram sets, 4dp round-half-up."""
    a = normalize_name(name_a)
    b = normalize_name(name_b)
    if a == b:
        return Decimal("1.0000")
    ta = _trigrams(a)
    tb = _trigrams(b)
    denom = len(ta) + len(tb)
    if denom == 0:
        return Decimal("0.0000")
    score = Decimal(2 * len(ta & tb)) / Decimal(denom)
    return score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# =========================================================================
# duplicate vendor detection (create time only)
# =========================================================================

def duplicate_candidates():
    return [v for v in db.vendors.values() if v["status"] not in ("MERGED", "REJECTED", "DEACTIVATED")]


def tax_id_collision(tax_id):
    for v in duplicate_candidates():
        if v["tax_id"] == tax_id:
            return True
    return False


def duplicate_score(legal_name):
    best = Decimal("0.0000")
    for cand in duplicate_candidates():
        s = name_similarity(legal_name, cand["legal_name"])
        if s > best:
            best = s
        dba = cand.get("dba_name")
        if dba:
            s2 = name_similarity(legal_name, dba)
            if s2 > best:
                best = s2
    return best


# =========================================================================
# sanctions screening (setup + payment variants share the scoring rule)
# =========================================================================

def screen_vendor(vendor, subject_type, payment_id=None):
    """Screen vendor legal_name against ACTIVE watchlist entries; persist a
    ScreeningCheck row regardless of outcome. Returns the ScreeningCheck."""
    best_entry = None
    best_score = None
    for entry in db.watchlist_entries.values():
        if entry["status"] != "ACTIVE":
            continue
        s = name_similarity(vendor["legal_name"], entry["name_pattern"])
        # max score; ties break toward the earliest-created entry
        if best_score is None or s > best_score:
            best_score = s
            best_entry = entry
    if best_entry is None:
        result = "CLEAR"
        score = Decimal("0.0000")
        matched_id = None
    else:
        score = best_score
        if best_score == Decimal("1.0000") and best_entry["severity"] == "BLOCK":
            result = "HIT"
        elif best_score == Decimal("1.0000"):
            result = "REVIEW"
        elif best_score >= SCREEN_FUZZY_THRESHOLD:
            result = "REVIEW"
        else:
            result = "CLEAR"
        matched_id = best_entry["id"] if result != "CLEAR" else None
    ts = db.fmt_ts(db.now())
    check = {
        "id": db.new_id(),
        "subject_type": subject_type,
        "vendor_id": vendor["id"],
        "payment_id": payment_id,
        "matched_watchlist_entry_id": matched_id,
        "match_score": float(score),
        "result": result,
        "screened_at": ts,
        "created_at": ts,
    }
    db.screening_checks[check["id"]] = check
    return check


# =========================================================================
# sanctions review cases
# =========================================================================

def open_case_for_vendor(vendor_id):
    for c in db.sanctions_cases.values():
        if c["vendor_id"] == vendor_id and c["status"] == "OPEN":
            return c
    return None


def open_case_unless_exists(vendor, check, opened_reason, payment_id=None):
    existing = open_case_for_vendor(vendor["id"])
    if existing is not None:
        return existing
    case = db.stamp_new({
        "id": db.new_id(),
        "vendor_id": vendor["id"],
        "payment_id": payment_id,
        "screening_check_id": check["id"],
        "opened_reason": opened_reason,
        "status": "OPEN",
        "dispositioned_by_user_id": None,
        "disposition_note": None,
    })
    db.sanctions_cases[case["id"]] = case
    return case


# =========================================================================
# documents: live validity (both bounds inclusive)
# =========================================================================

def document_live_valid(doc, on_date):
    return (
        doc["status"] == "VALID"
        and doc["valid_from"] <= on_date.isoformat()
        and on_date.isoformat() <= doc["valid_until"]
    )


def vendor_has_live_w9(vendor_id):
    today_s = db.today().isoformat()
    for doc in db.documents.values():
        if doc["vendor_id"] != vendor_id or doc["doc_type"] != "W9":
            continue
        if doc["status"] == "VALID" and doc["valid_from"] <= today_s <= doc["valid_until"]:
            return True
    return False


def vendor_has_any_w9(vendor_id):
    for doc in db.documents.values():
        if doc["vendor_id"] == vendor_id and doc["doc_type"] == "W9":
            return True
    return False


def vendor_has_open_invoices(vendor_id):
    for inv in db.invoices.values():
        if inv["vendor_id"] == vendor_id and inv["status"] in OPEN_INVOICE_STATUSES:
            return True
    return False


def vendor_has_inflight_payments(vendor_id):
    for p in db.payments.values():
        if p["vendor_id"] == vendor_id and p["status"] in ("PENDING", "RELEASED"):
            return True
    return False


# =========================================================================
# invoice hold / resume cascades
# =========================================================================

def hold_cascade(vendor_id):
    """Suspend leg: invoices in PENDING_APPROVAL / APPROVED -> ON_HOLD.
    An invoice already ON_HOLD keeps its original pre_hold_status."""
    for inv in db.invoices.values():
        if inv["vendor_id"] != vendor_id:
            continue
        if inv["status"] in ("PENDING_APPROVAL", "APPROVED"):
            inv["pre_hold_status"] = inv["status"]
            inv["status"] = "ON_HOLD"
            db.touch(inv)


def resume_cascade(vendor_id):
    for inv in db.invoices.values():
        if inv["vendor_id"] == vendor_id and inv["status"] == "ON_HOLD":
            inv["status"] = inv["pre_hold_status"]
            inv["pre_hold_status"] = None
            db.touch(inv)


def suspend_vendor(vendor, ctx, fraud_reason=None, screening_check=None,
                   opened_reason=None, payment_id=None):
    """ACTIVE -> SUSPENDED with hold cascade; optional case open on screening triggers."""
    old = vendor["status"]
    if old == "ACTIVE":
        vendor["status"] = "SUSPENDED"
    if fraud_reason is not None:
        vendor["fraud_hold_reason"] = fraud_reason
    hold_cascade(vendor["id"])
    db.touch(vendor)
    if screening_check is not None:
        open_case_unless_exists(vendor, screening_check, opened_reason, payment_id=payment_id)
    audit_status_change("Vendor", vendor["id"], old, vendor["status"], ctx)


def live_payment_for_invoice(invoice_id):
    for p in db.payments.values():
        if p["invoice_id"] == invoice_id and p["status"] in ("PENDING", "RELEASED"):
            return p
    return None


def recompute_run_totals(run):
    total = 0
    count = 0
    for p in db.payments.values():
        if p["payment_run_id"] == run["id"] and p["status"] != "VOIDED":
            total += p["net_amount_cents"]
            count += 1
    run["total_amount_cents"] = total
    run["item_count"] = count


def block_cascade(vendor, ctx):
    """Ordered block cascade: hold invoices (incl. IN_PAYMENT_RUN with PENDING
    payment), void those payments VENDOR_BLOCKED, recompute runs, demote APPROVED runs."""
    old = vendor["status"]
    payments_to_void = []
    for inv in db.invoices.values():
        if inv["vendor_id"] != vendor["id"]:
            continue
        if inv["status"] in ("PENDING_APPROVAL", "APPROVED"):
            inv["pre_hold_status"] = inv["status"]
            inv["status"] = "ON_HOLD"
            db.touch(inv)
        elif inv["status"] == "IN_PAYMENT_RUN":
            pay = live_payment_for_invoice(inv["id"])
            if pay is not None and pay["status"] == "PENDING":
                inv["pre_hold_status"] = "IN_PAYMENT_RUN"
                inv["status"] = "ON_HOLD"
                db.touch(inv)
                payments_to_void.append(pay)
    affected_run_ids = set()
    for pay in payments_to_void:
        pay["status"] = "VOIDED"
        pay["void_reason"] = "VENDOR_BLOCKED"
        db.touch(pay)
        affected_run_ids.add(pay["payment_run_id"])
    for run_id in affected_run_ids:
        run = db.payment_runs.get(run_id)
        if run is None:
            continue
        recompute_run_totals(run)
        if run["status"] == "APPROVED":
            run["status"] = "COMPILED"
            run["approved_by_user_id"] = None
        db.touch(run)
    vendor["status"] = "BLOCKED"
    db.touch(vendor)
    audit_status_change("Vendor", vendor["id"], old, "BLOCKED", ctx)


# =========================================================================
# invoice approval routing (submit / resubmit snapshot)
# =========================================================================

def route_invoice_tier(vendor, invoice):
    """Return required_tier, or None when no ACTIVE rule covers the amount."""
    rules = [r for r in db.approval_matrix_rules.values() if r["status"] == "ACTIVE"]
    scope = [r for r in rules if r["cost_center"] == invoice["cost_center"]]
    if not scope:
        scope = [r for r in rules if r["cost_center"] == "GLOBAL"]
    covering = None
    for r in scope:
        if r["min_amount_cents"] <= invoice["amount_cents"] and (
            r["max_amount_cents"] is None or invoice["amount_cents"] < r["max_amount_cents"]
        ):
            covering = r
            break
    if covering is None:
        return None
    base = covering["tier"]
    submit_time = db.now()
    bump_new = 0
    if vendor.get("first_activated_at"):
        first = _parse_ts(vendor["first_activated_at"])
        if submit_time < first + timedelta(days=NEW_VENDOR_DAYS):
            bump_new = 1
    bump_bank = 0
    primary_id = vendor.get("primary_bank_account_id")
    if primary_id:
        acct = db.bank_accounts.get(primary_id)
        if acct is not None and acct["status"] == "VERIFIED" and acct.get("verified_at"):
            verified_at = _parse_ts(acct["verified_at"])
            if submit_time < verified_at + timedelta(hours=BANK_RECENT_HOURS):
                bump_bank = 1
    return min(base + bump_new + bump_bank, MAX_TIER)


def _parse_ts(s):
    return datetime_from_iso(s)


def datetime_from_iso(s):
    from datetime import datetime, timezone
    text = s[:-1] + "+00:00" if s.endswith("Z") else s
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# =========================================================================
# early-pay discount (per single invoice, whole cents, round half up)
# =========================================================================

def discount_window_end(invoice, vendor):
    from datetime import date
    y, m, d = (int(x) for x in invoice["received_date"].split("-"))
    received = date(y, m, d)
    return received + timedelta(days=vendor["discount_window_days"])


def compute_discount_cents(invoice, vendor, reference_date):
    """reference_date is a datetime.date; discount applies iff reference <= window end."""
    pct = vendor.get("early_pay_discount_pct") or 0
    if not pct:
        return 0
    if reference_date > discount_window_end(invoice, vendor):
        return 0
    raw = Decimal(invoice["amount_cents"]) * Decimal(str(pct))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
