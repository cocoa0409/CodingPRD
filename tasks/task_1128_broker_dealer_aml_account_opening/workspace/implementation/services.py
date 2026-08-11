"""Business logic: risk scoring, aggregates, posture, cascades, scans, sweep.

All money math uses Decimal with round-half-up at 2dp, pinned per-line-before-
sum ordering (PRD §2.7). Calendar arithmetic is day-granularity on the logical
clock date. Account version bumps happen exactly where the scaffold declares
them, plus one bump whenever a posture recompute changes aml_posture.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_record, bump, today


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")


def to_dec(v):
    return Decimal(str(v))


def round2(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def round0(v):
    return int(Decimal(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(d, months):
    """Calendar months, same day-of-month, clamped to month length."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def accounts_of_customer(customer_id):
    return [a for a in store.accounts.values() if a["customer_id"] == customer_id]


def txns_of_account(account_id):
    return [t for t in store.transactions.values() if t["account_id"] == account_id]


def alerts_of_account(account_id):
    return [a for a in store.alerts.values() if a["account_id"] == account_id]


def cases_of_account(account_id):
    return [c for c in store.cases.values() if c["account_id"] == account_id]


def matches_of_account(account_id):
    return [m for m in store.matches.values() if m["account_id"] == account_id]


def reviews_of_account(account_id):
    return [r for r in store.edd_reviews.values() if r["account_id"] == account_id]


def docs_of_customer(customer_id):
    return [d for d in store.documents.values() if d["customer_id"] == customer_id]


def filings_of_account(account_id):
    case_ids = {c["id"] for c in cases_of_account(account_id)}
    return [f for f in store.sar_filings.values() if f["case_id"] in case_ids]


def owners_of_certification(cert_id):
    return [o for o in store.owners.values() if o["certification_id"] == cert_id]


def current_certified_certification(customer_id):
    certs = [c for c in store.certifications.values()
             if c["customer_id"] == customer_id and c["status"] == "CERTIFIED"]
    if not certs:
        return None
    certs.sort(key=lambda c: c["_seq"])
    return certs[-1]


# ---------------------------------------------------------------------------
# Aggregates (exposure / wire velocity / tiers) — trailing 30 calendar days
# inclusive: [clock_date - 30, clock_date]
# ---------------------------------------------------------------------------

TIER_LIMITS = {"LOW": Decimal("250000"), "MEDIUM": Decimal("100000"), "HIGH": Decimal("25000")}
OPEN_CASE_STATES = {"OPEN", "INVESTIGATING", "SAR_RECOMMENDED", "REOPENED"}
OPEN_ALERT_STATES = {"NEW", "UNDER_REVIEW"}


def _txn_date(t):
    return date.fromisoformat(t["created_at"][:10])


def recompute_aggregates(account):
    lo = today() - timedelta(days=30)
    hi = today()
    exposure = Decimal("0")
    wire = Decimal("0")
    for t in txns_of_account(account["id"]):
        if t["status"] == "REVERSED":
            continue
        d = _txn_date(t)
        if lo <= d <= hi:
            exposure += t["amount"]
            if t["txn_type"] == "WIRE_OUT":
                wire += t["amount"]
    account["exposure_30d_amount"] = exposure
    account["wire_velocity_30d_amount"] = wire
    if exposure < Decimal("100000"):
        account["exposure_tier"] = "T1"
    elif exposure < Decimal("500000"):
        account["exposure_tier"] = "T2"
    else:
        account["exposure_tier"] = "T3"


def recompute_counts(account):
    account["open_alert_count"] = sum(
        1 for a in alerts_of_account(account["id"]) if a["status"] in OPEN_ALERT_STATES)
    account["open_case_count"] = sum(
        1 for c in cases_of_account(account["id"]) if c["status"] in OPEN_CASE_STATES)


# ---------------------------------------------------------------------------
# Risk scoring (calculations.account_risk_score) — INITIAL vs ONGOING variants
# ---------------------------------------------------------------------------

def compute_risk(account, variant):
    customer = store.customers.get(account["customer_id"], {})
    crt = customer.get("country_risk_tier")
    points = {"LOW": 0, "MEDIUM": 10, "HIGH": 25}.get(crt, 0)
    points += 10 if customer.get("customer_type") == "LEGAL_ENTITY" else 0
    points += 20 if customer.get("is_pep") else 0
    ps = set(account.get("product_set") or [])
    product_points = (
        (15 if "LOW_PRICED_SECURITIES" in ps else 0)
        + (5 if "MARGIN" in ps else 0)
        + (5 if "OPTIONS" in ps else 0)
        + (10 if "CORRESPONDENT" in ps else 0)
    )
    points += min(25, product_points)
    # ownership opacity
    if customer.get("customer_type") == "LEGAL_ENTITY":
        cert = current_certified_certification(customer["id"]) if customer.get("id") else None
        if cert and any(o.get("is_entity_owner") for o in owners_of_certification(cert["id"])):
            points += 10
    if variant == "ONGOING":
        active_alerts = sum(
            1 for a in alerts_of_account(account["id"])
            if a["status"] in ("UNDER_REVIEW", "ESCALATED_TO_CASE"))
        filed_sars = sum(
            1 for f in filings_of_account(account["id"]) if f["status"] == "FILED")
        recompute_aggregates(account)
        tier_before = account.get("risk_tier") or "LOW"
        limit = TIER_LIMITS.get(tier_before, TIER_LIMITS["HIGH"])
        wire = account["wire_velocity_30d_amount"]
        if limit > 0:
            ratio = wire / limit
        else:
            ratio = Decimal("999")
        if ratio < Decimal("0.5"):
            band = 0
        elif ratio < Decimal("0.8"):
            band = 5
        else:
            band = 10
        points += 5 * active_alerts + 10 * filed_sars + band
    score = max(0, min(100, points))
    if crt == "PROHIBITED":
        tier = "PROHIBITED"
    elif score >= 70:
        tier = "HIGH"
    elif score >= 40:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return score, tier


def apply_risk(account, variant):
    """Recompute risk fields and variant stamp, then recompute posture.
    Does NOT bump account version for the risk change itself — the caller's
    declared bump covers it. Posture bumps itself only on value change."""
    score, tier = compute_risk(account, variant)
    account["risk_score"] = score
    account["risk_tier"] = tier
    account["risk_variant_used"] = variant
    recompute_posture(account)


# ---------------------------------------------------------------------------
# AML posture (BrokerageAccount.aml_posture parallel dimension)
# ---------------------------------------------------------------------------

def recompute_posture(account):
    severe = (
        any(m["status"] == "CONFIRMED" for m in matches_of_account(account["id"]))
        or any(c["priority"] == "CRITICAL" and c["status"] in OPEN_CASE_STATES
               for c in cases_of_account(account["id"]))
    )
    if severe:
        new = "SEVERE"
    else:
        customer_id = account["customer_id"]
        expired_doc = any(d["status"] == "EXPIRED" for d in docs_of_customer(customer_id))
        refresh_due = any(r["status"] == "REFRESH_DUE" for r in reviews_of_account(account["id"]))
        elevated = (
            account.get("has_suspicion_flag")
            or (account.get("risk_score") or 0) >= 70
            or expired_doc
            or refresh_due
        )
        new = "ELEVATED" if elevated else "STANDARD"
    if new != account["aml_posture"]:
        account["aml_posture"] = new
        bump(account)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def create_alert(rule, account, txn, rule_code, window_start, window_end, aggregate):
    """Severity frozen at creation: 100 * min(agg/threshold, 2.0) * risk_mult,
    round_half_up to integer. Cascade alerts (no rule) use ratio 1.0."""
    if rule is not None and rule.get("threshold_amount") is not None \
            and to_dec(rule["threshold_amount"]) > 0:
        ratio = to_dec(aggregate) / to_dec(rule["threshold_amount"])
    else:
        ratio = Decimal("1")
    if ratio > Decimal("2.0"):
        ratio = Decimal("2.0")
    tier = account.get("risk_tier")
    mult = Decimal("1.0")
    if tier == "HIGH":
        mult += Decimal("0.25")
    elif tier == "MEDIUM":
        mult += Decimal("0.10")
    severity = round0(Decimal("100") * ratio * mult)
    alert = new_record()
    alert.update({
        "rule_id": rule["id"] if rule else None,
        "rule_code": rule_code,
        "account_id": account["id"],
        "transaction_id": txn["id"] if txn else None,
        "window_start": window_start.isoformat() if isinstance(window_start, date) else window_start,
        "window_end": window_end.isoformat() if isinstance(window_end, date) else window_end,
        "aggregate_amount": round2(aggregate),
        "severity": severity,
        "status": "NEW",
        "close_rationale": None,
    })
    store.alerts[alert["id"]] = alert
    return alert


def has_open_alert_for_txn(txn_id):
    return any(a["transaction_id"] == txn_id
               and a["status"] in ("NEW", "UNDER_REVIEW", "ESCALATED_TO_CASE")
               for a in store.alerts.values())


# ---------------------------------------------------------------------------
# Restriction cascade (manual restrict, EDD rejection, 314(a) confirm hop 1)
# hop order: flag POSTED txns -> create alerts -> ONGOING risk recalc
# ---------------------------------------------------------------------------

def restrict_cascade(account, rule_code):
    txns = sorted([t for t in txns_of_account(account["id"]) if t["status"] == "POSTED"],
                  key=lambda t: t["_seq"])
    for t in txns:
        t["status"] = "FLAGGED"
        bump(t)
        if not has_open_alert_for_txn(t["id"]):
            create_alert(None, account, t, rule_code, today(), today(), t["amount"])
    apply_risk(account, "ONGOING")
    recompute_counts(account)


def restrict_account(account, rule_code):
    """Move OPEN -> RESTRICTED (only when OPEN) and run the cascade."""
    if account["lifecycle_status"] == "OPEN":
        account["lifecycle_status"] = "RESTRICTED"
    restrict_cascade(account, rule_code)


# ---------------------------------------------------------------------------
# Monitoring scan (LPS_LIQUIDATION per-line rounding pinned; dedup on
# rule_code + account_id + window_end among NEW/UNDER_REVIEW/ESCALATED_TO_CASE)
# ---------------------------------------------------------------------------

def _rule_matching_txns(rule, account, window_start, window_end):
    code = rule["rule_code"]
    out = []
    for t in txns_of_account(account["id"]):
        d = _txn_date(t)
        if not (window_start <= d <= window_end):
            continue
        if code == "LPS_LIQUIDATION":
            if t["txn_type"] == "SELL" and t.get("is_low_priced") \
                    and t["status"] in ("POSTED", "FLAGGED", "ESCALATED"):
                out.append(t)
        elif code == "LPS_DEPOSIT_LIQUIDATE":
            if t["txn_type"] in ("DEPOSIT_CERT", "DEPOSIT_DTC", "SELL") \
                    and t.get("is_low_priced") \
                    and t["status"] in ("POSTED", "FLAGGED", "ESCALATED"):
                out.append(t)
        elif code == "WIRE_VELOCITY":
            if t["txn_type"] == "WIRE_OUT" and t["status"] != "REVERSED":
                out.append(t)
        elif code == "STRUCTURING":
            if t["status"] != "REVERSED":
                out.append(t)
    return out


def _triggering_txn(matched):
    """Greatest created_at, tie-break greatest amount, then smallest quantity."""
    def key(t):
        qty = t.get("quantity")
        qty_key = float(qty) if qty is not None else float("inf")
        return (t["created_at"], float(t["amount"]), -qty_key, -t["_seq"])
    return max(matched, key=key)


def run_scan():
    alerts_created = 0
    transactions_flagged = 0
    window_end = today()
    affected_accounts = set()
    rules = sorted([r for r in store.rules.values() if r.get("enabled")],
                   key=lambda r: r["_seq"])
    accounts = sorted(store.accounts.values(), key=lambda a: a["_seq"])
    for rule in rules:
        window_start = window_end - timedelta(days=int(rule["window_days"]))
        for account in accounts:
            matched = _rule_matching_txns(rule, account, window_start, window_end)
            if not matched:
                continue
            aggregate = Decimal("0")
            for t in matched:
                aggregate += round2(t["amount"])  # amounts already rounded per line
            if aggregate < to_dec(rule["threshold_amount"]):
                continue
            if len(matched) < int(rule.get("min_transaction_count", 1)):
                continue
            dedup = any(
                a["rule_code"] == rule["rule_code"]
                and a["account_id"] == account["id"]
                and a["window_end"] == window_end.isoformat()
                and a["status"] in ("NEW", "UNDER_REVIEW", "ESCALATED_TO_CASE")
                for a in store.alerts.values())
            if not dedup:
                create_alert(rule, account, _triggering_txn(matched),
                             rule["rule_code"], window_start, window_end, aggregate)
                alerts_created += 1
                affected_accounts.add(account["id"])
            for t in matched:
                if t["status"] == "POSTED":
                    t["status"] = "FLAGGED"
                    bump(t)
                    transactions_flagged += 1
    for aid in affected_accounts:
        recompute_counts(store.accounts[aid])
    return alerts_created, transactions_flagged


# ---------------------------------------------------------------------------
# 314(a) deterministic matching
# ---------------------------------------------------------------------------

def _name_eq(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()


def run_314a_scan(request_rec):
    """One Match314A per (subject, account) with strongest applicable basis."""
    created = []
    accounts = sorted(store.accounts.values(), key=lambda a: a["_seq"])
    for subject in request_rec.get("subjects") or []:
        for account in accounts:
            customer = store.customers.get(account["customer_id"])
            if customer is None:
                continue
            basis = None
            s_tax = subject.get("tax_id")
            if s_tax and customer.get("tax_id") and s_tax == customer["tax_id"]:
                basis = "TAX_ID_EXACT"
            elif subject.get("subject_type") == "INDIVIDUAL" \
                    and _name_eq(subject.get("name"), customer.get("full_name")) \
                    and subject.get("date_of_birth") \
                    and customer.get("date_of_birth") \
                    and subject["date_of_birth"] == customer["date_of_birth"]:
                basis = "NAME_DOB"
            elif _name_eq(subject.get("name"), customer.get("full_name")):
                basis = "NAME_EXACT"
            if basis is None:
                continue
            m = new_record()
            m.update({
                "request_id": request_rec["id"],
                "account_id": account["id"],
                "matched_subject_name": subject.get("name"),
                "match_basis": basis,
                "status": "PENDING_REVIEW",
                "reviewed_by": None,
            })
            store.matches[m["id"]] = m
            created.append(m)
    request_rec["match_count"] = len([m for m in store.matches.values()
                                      if m["request_id"] == request_rec["id"]])
    return created


# ---------------------------------------------------------------------------
# Daily sweep — six time-based transition families
# ---------------------------------------------------------------------------

SEVERITY_ESCALATION = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}


def run_sweep():
    clock = today()
    counts = {
        "documents_expired": 0,
        "edd_reviews_flagged": 0,
        "sar_reviews_due": 0,
        "requests_314a_overdue": 0,
        "holds_released": 0,
        "findings_aged": 0,
    }
    posture_accounts = set()

    # 1. Document expiry: VERIFIED and expiry_date < clock date -> EXPIRED
    for doc in store.documents.values():
        if doc["status"] != "VERIFIED":
            continue
        exp = date.fromisoformat(doc["expiry_date"])
        if exp < clock:
            doc["status"] = "EXPIRED"
            bump(doc)
            counts["documents_expired"] += 1
            for acc in accounts_of_customer(doc["customer_id"]):
                posture_accounts.add(acc["id"])

    # 2. EDD refresh: APPROVED and refresh_due_date < clock date -> REFRESH_DUE
    for rev in store.edd_reviews.values():
        if rev["status"] != "APPROVED" or not rev.get("refresh_due_date"):
            continue
        if date.fromisoformat(rev["refresh_due_date"]) < clock:
            rev["status"] = "REFRESH_DUE"
            bump(rev)
            counts["edd_reviews_flagged"] += 1
            posture_accounts.add(rev["account_id"])

    # 3. SAR continuing review overdue: FILED and due date < clock date
    for f in store.sar_filings.values():
        if f["status"] == "FILED" and f.get("continuing_review_due_date") \
                and date.fromisoformat(f["continuing_review_due_date"]) < clock \
                and not f.get("review_overdue"):
            f["review_overdue"] = True
            bump(f)
            counts["sar_reviews_due"] += 1

    # 4. 314(a) overdue: RECEIVED or SCAN_COMPLETE and response_deadline < clock
    for r in store.fincen_requests.values():
        if r["status"] in ("RECEIVED", "SCAN_COMPLETE") \
                and date.fromisoformat(r["response_deadline"]) < clock:
            r["status"] = "OVERDUE"
            bump(r)
            counts["requests_314a_overdue"] += 1

    # 5. Certificate hold release: CLEARANCE_HOLD and hold_release_date <= clock
    for dep in store.deposits.values():
        if dep["status"] == "CLEARANCE_HOLD" and dep.get("hold_release_date") \
                and date.fromisoformat(dep["hold_release_date"]) <= clock:
            dep["status"] = "READY_TO_ACCEPT"
            bump(dep)
            counts["holds_released"] += 1

    # 6. Finding aging: OPEN/REMEDIATION_SUBMITTED and deadline < clock date
    for f in store.findings.values():
        if f["status"] in ("OPEN", "REMEDIATION_SUBMITTED") \
                and date.fromisoformat(f["remediation_deadline"]) < clock \
                and not f.get("is_overdue"):
            f["is_overdue"] = True
            f["severity"] = SEVERITY_ESCALATION[f["severity"]]
            bump(f)
            counts["findings_aged"] += 1

    for aid in posture_accounts:
        recompute_posture(store.accounts[aid])
    return counts
