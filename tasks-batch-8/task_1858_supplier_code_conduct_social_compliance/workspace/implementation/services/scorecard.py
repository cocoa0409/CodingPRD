"""Scorecard and consequence-tier logic for suppliers."""
import db
from services.utils import parse_iso, to_iso_ms

# Constants
COUNTRY_RISK = {"BD": 60, "IN": 55, "VN": 50, "CN": 40, "TR": 35, "US": 10}
SECTOR_MULT = {"APPAREL": 1.2, "ELECTRONICS": 1.1, "FOOD": 1.0, "HARDLINES": 0.9}

TIER_PREFERRED_MIN = 80
TIER_QUALIFIED_MIN = 60
TIER_PROBATION_WATCH_MIN = 40

TIER_BASE_MONTHS = {"HIGH": 6, "MEDIUM": 12, "LOW": 24}
FAILED_ZT_CAP_MONTHS = 3
PROGRAM_VALIDITY_MONTHS = {"BSCI": 24, "SMETA": 12, "RBA": 24, "WRAP": 12}
PROGRAM_MIN_SCORE = {"BSCI": 85, "SMETA": 75, "RBA": 80, "WRAP": 80}
MIN_INTERVAL_MONTHS = 3
MAX_INTERVAL_MONTHS = 36

FX_USD_CENTS_PER_MINOR = {"USD": 1.0, "EUR": 1.08, "INR": 0.012, "BDT": 0.0115}

DUE_DAYS = {"ZERO_TOLERANCE": 30, "MAJOR": 90, "MINOR": 180}

TERMINAL_AUDIT_STATUSES = {"COMPLETED", "FAILED_ZT", "CANCELLED"}
OPEN_AUDIT_STATUSES = {"SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED"}


def _worker_factor(worker_count):
    if worker_count >= 1000:
        return 15
    if worker_count >= 300:
        return 8
    return 3


def _round_half_up_1dp(x):
    """Round a numeric value to 1 decimal place using round-half-up."""
    from decimal import Decimal, ROUND_HALF_UP
    d = Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def compute_baseline_risk(supplier, facility):
    country = COUNTRY_RISK.get(facility["country_code"], 0)
    mult = SECTOR_MULT.get(supplier["sector"], 1.0)
    wf = _worker_factor(facility["worker_count"])
    return _round_half_up_1dp(country * mult + wf)


def _terminal_audits_of_facility(facility_id):
    """Audits of this facility in COMPLETED or FAILED_ZT (not CANCELLED), per the
    'terminal audit' definition used by the risk/interval calculations."""
    out = []
    for a in db.audits.values():
        if a["facility_id"] == facility_id and a["status"] in ("COMPLETED", "FAILED_ZT"):
            out.append(a)
    return out


def _latest_terminal_audit(facility_id):
    """The audit of this facility with status in {COMPLETED, FAILED_ZT}
    having max scheduled_end; tie-break max created_at."""
    terminal = _terminal_audits_of_facility(facility_id)
    if not terminal:
        return None
    def key(a):
        se = parse_iso(a["scheduled_end"]) or parse_iso(a["created_at"])
        ca = parse_iso(a["created_at"])
        return (se, ca)
    return max(terminal, key=key)


def _facility_findings_on_terminal_audits(facility_id):
    """Findings with status != VOIDED on this facility's terminal (COMPLETED/FAILED_ZT) audits."""
    terminal = _terminal_audits_of_facility(facility_id)
    terminal_ids = {a["id"] for a in terminal}
    out = []
    for f in db.findings.values():
        if f["audit_id"] in terminal_ids and f["status"] != "VOIDED":
            out.append(f)
    return out


def compute_history_risk(supplier, facility):
    """Compute risk_score_history, or None if no terminal audit exists."""
    terminal = _terminal_audits_of_facility(facility["id"])
    if not terminal:
        return None
    findings = _facility_findings_on_terminal_audits(facility["id"])
    zt = sum(1 for f in findings if f["classification"] == "ZERO_TOLERANCE")
    major = sum(1 for f in findings if f["classification"] == "MAJOR")
    minor = sum(1 for f in findings if f["classification"] == "MINOR")
    history_component = min(100, 10 * zt + 4 * major + 1 * minor)
    baseline = facility["risk_score_baseline"]
    blended = 0.5 * baseline + 0.5 * history_component
    return _round_half_up_1dp(blended)


def derive_risk_tier(facility):
    score = facility["risk_score_history"] if facility["risk_score_history"] is not None else facility["risk_score_baseline"]
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def _valid_accepted_claim_for_facility(facility_id):
    """The valid ACCEPTED claim covering this facility, if any. A claim is valid
    when external_audit_date lies within PROGRAM_VALIDITY_MONTHS of the current clock.
    If several valid, choose max external_audit_date, tie-break max created_at."""
    now = parse_iso(db.get_clock())
    valid = []
    for c in db.mutual_recognition_claims.values():
        if c["facility_id"] != facility_id or c["status"] != "ACCEPTED":
            continue
        validity = PROGRAM_VALIDITY_MONTHS.get(c["program_name"], 0)
        ext_dt = parse_iso(c["external_audit_date"])
        if ext_dt is None:
            continue
        # Valid while external_audit_date >= current_clock - validity months
        cutoff = _subtract_months(now, validity)
        if ext_dt >= cutoff:
            valid.append(c)
    if not valid:
        return None
    def key(c):
        return (parse_iso(c["external_audit_date"]), parse_iso(c["created_at"]))
    return max(valid, key=key)


def _subtract_months(dt, months):
    # subtract months (calendar-aware)
    month_index = dt.year * 12 + (dt.month - 1) - months
    year = month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def compute_next_audit_interval_and_due(facility):
    """Returns (interval_months, due_date_iso_or_None)."""
    from services.utils import add_months
    tier = facility["risk_tier"]
    interval = TIER_BASE_MONTHS[tier]
    latest_terminal = _latest_terminal_audit(facility["id"])
    if latest_terminal is not None and latest_terminal["status"] == "FAILED_ZT":
        interval = min(interval, FAILED_ZT_CAP_MONTHS)
    claim = _valid_accepted_claim_for_facility(facility["id"])
    if claim is not None:
        interval = interval + PROGRAM_VALIDITY_MONTHS[claim["program_name"]]
    if interval < MIN_INTERVAL_MONTHS:
        interval = MIN_INTERVAL_MONTHS
    if interval > MAX_INTERVAL_MONTHS:
        interval = MAX_INTERVAL_MONTHS
    due = None
    if latest_terminal is not None:
        se = parse_iso(latest_terminal["scheduled_end"])
        if se is not None:
            due = to_iso_ms(add_months(se, interval))
    return interval, due


def recompute_facility_risk(facility):
    """Recompute risk_score_history, risk_tier, interval and due date; bump version/updated_at."""
    supplier = db.suppliers.get(facility["supplier_id"])
    if supplier is None:
        return
    facility["risk_score_history"] = compute_history_risk(supplier, facility)
    facility["risk_tier"] = derive_risk_tier(facility)
    interval, due = compute_next_audit_interval_and_due(facility)
    facility["next_audit_interval_months"] = interval
    facility["next_audit_due_date"] = due
    facility["version"] += 1
    facility["updated_at"] = db.get_clock()


def _supplier_facility_ids(supplier_id):
    return {f["id"] for f in db.facilities.values() if f["supplier_id"] == supplier_id}


def _supplier_findings(supplier_id):
    """All findings on audits of this supplier's facilities (any audit status)."""
    fac_ids = _supplier_facility_ids(supplier_id)
    audit_ids = {a["id"] for a in db.audits.values() if a["facility_id"] in fac_ids}
    return [f for f in db.findings.values() if f["audit_id"] in audit_ids]


def _supplier_unresolved_critical_grievances(supplier_id):
    fac_ids = _supplier_facility_ids(supplier_id)
    return [
        g for g in db.grievances.values()
        if g["facility_id"] in fac_ids
        and g["severity"] == "CRITICAL"
        and g["status"] in ("SUBMITTED", "UNDER_REVIEW", "ESCALATED")
    ]


def recompute_supplier_scorecard(supplier):
    """Recompute provisional_score, verified_score, consequence_tier and update
    status per gating rules. Bumps supplier version/updated_at.

    No-op if supplier is TERMINATED (frozen scorecard).
    """
    if supplier["status"] == "TERMINATED":
        return
    findings = _supplier_findings(supplier["id"])
    grievances = _supplier_unresolved_critical_grievances(supplier["id"])
    open_crit = len(grievances)

    open_zt = sum(1 for f in findings if f["classification"] == "ZERO_TOLERANCE" and f["status"] == "OPEN")
    open_major = sum(1 for f in findings if f["classification"] == "MAJOR" and f["status"] == "OPEN")
    open_minor = sum(1 for f in findings if f["classification"] == "MINOR" and f["status"] == "OPEN")
    live_zt = sum(1 for f in findings if f["classification"] == "ZERO_TOLERANCE" and f["status"] != "VOIDED")
    live_major = sum(1 for f in findings if f["classification"] == "MAJOR" and f["status"] != "VOIDED")
    live_minor = sum(1 for f in findings if f["classification"] == "MINOR" and f["status"] != "VOIDED")

    pen = supplier["escalation_penalty_points"]

    prov = 100 - 40 * live_zt - 10 * live_major - 3 * live_minor - 5 * open_crit - pen
    if prov < 0:
        prov = 0
    ver = 100 - 40 * open_zt - 10 * open_major - 3 * open_minor - 5 * open_crit - pen
    if ver < 0:
        ver = 0

    supplier["provisional_score"] = prov
    supplier["verified_score"] = ver

    if ver >= TIER_PREFERRED_MIN:
        supplier["consequence_tier"] = "PREFERRED"
    elif ver >= TIER_QUALIFIED_MIN:
        supplier["consequence_tier"] = "QUALIFIED"
    elif ver >= TIER_PROBATION_WATCH_MIN:
        supplier["consequence_tier"] = "PROBATION_WATCH"
    else:
        supplier["consequence_tier"] = "SOURCING_EXIT"

    # Status gating
    has_open_zt = open_zt > 0
    if supplier["status"] == "ACTIVE" and (ver < 60 or has_open_zt):
        supplier["status"] = "PROBATION"
    elif supplier["status"] == "PROBATION" and ver >= 60 and not has_open_zt:
        supplier["status"] = "ACTIVE"

    supplier["version"] += 1
    supplier["updated_at"] = db.get_clock()


def recompute_audit_tallies(audit):
    """Recompute zt/major/minor tallies on the audit; bump version/updated_at."""
    zt = major = minor = 0
    for f in db.findings.values():
        if f["audit_id"] == audit["id"] and f["status"] != "VOIDED":
            if f["classification"] == "ZERO_TOLERANCE":
                zt += 1
            elif f["classification"] == "MAJOR":
                major += 1
            elif f["classification"] == "MINOR":
                minor += 1
    audit["zt_count"] = zt
    audit["major_count"] = major
    audit["minor_count"] = minor
    audit["version"] += 1
    audit["updated_at"] = db.get_clock()


def compute_reimbursement_totals(review):
    """Compute total_reimbursement_cents from fee_items (per-item round half-up)."""
    from decimal import Decimal, ROUND_HALF_UP
    total = 0
    for item in review.get("fee_items", []):
        amount = item.get("amount_minor_units", 0)
        currency = item.get("currency", "USD")
        rate = FX_USD_CENTS_PER_MINOR.get(currency, 1.0)
        converted = Decimal(str(amount)) * Decimal(str(rate))
        cents = int(converted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += cents
    return total


def recompute_review_balance(review):
    """Recompute reimbursed_cents / outstanding_reimbursement_cents from RECORDED payments."""
    rec = sum(
        r["amount_cents"] for r in db.reimbursements.values()
        if r["review_id"] == review["id"] and r["status"] == "RECORDED"
    )
    review["reimbursed_cents"] = rec
    review["outstanding_reimbursement_cents"] = review["total_reimbursement_cents"] - rec
    review["version"] += 1
    review["updated_at"] = db.get_clock()


def find_supplier_for_finding(finding):
    audit = db.audits.get(finding["audit_id"])
    if not audit:
        return None, None, None
    facility = db.facilities.get(audit["facility_id"])
    if not facility:
        return None, audit, None
    supplier = db.suppliers.get(facility["supplier_id"])
    return supplier, audit, facility


def find_supplier_for_audit(audit):
    facility = db.facilities.get(audit["facility_id"])
    if not facility:
        return None, None
    supplier = db.suppliers.get(facility["supplier_id"])
    return supplier, facility


def find_supplier_for_facility(facility):
    return db.suppliers.get(facility["supplier_id"])


def find_supplier_for_review(review):
    audit = db.audits.get(review["audit_id"])
    if not audit:
        return None, None, None
    facility = db.facilities.get(audit["facility_id"])
    if not facility:
        return None, audit, None
    supplier = db.suppliers.get(facility["supplier_id"])
    return supplier, audit, facility
