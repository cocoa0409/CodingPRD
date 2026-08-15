"""Business logic: calculations, cascades, state-transition side effects.

Implements PRD §3: license-position derivation (§3.4), case exposure rollups
(§3.5), vendor-finding line pricing (§3.7), monitoring alert evaluation
(§3.9), and the logical-clock entitlement sweep (§2.4).

Version-bump discipline (PRD §2.8): only the enumerated operations advance a
parent AuditCase's version — confirming a scope item, excluding a confirmed
scope item, releasing a data submission, recording a vendor finding,
tendering an offer, accepting an offer, reopening evidence, withdrawing a
case, and completing a remediation. Plain recompute cascades (entitlement
create/void, deployment confirm, product PATCH, clock sweep, remediation
fail-verification, explicit recalculate) refresh the stored rollup values
without touching the case version.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

TERMINAL_CASE_STATES = ("CLOSED_SETTLED", "CLOSED_NO_ACTION", "WITHDRAWN")

# Severity ladder constants (calculation: gap_and_severity)
MATERIAL_QTY = 10
CRITICAL_QTY = 100
MISSION_CRITICAL_QTY = 25
# Ratios compared exactly via integer cross-multiplication:
#   deployed/entitled >= 1.25  <=>  deployed*100 >= entitled*125
#   deployed/entitled >  1.05  <=>  deployed*100 >  entitled*105
# (exact decimal arithmetic; a ratio of exactly 1.05 is NOT material,
#  exactly 1.25 IS critical.)

BACK_SUPPORT_YEARS = 2        # vendor_finding_line_pricing
EXPIRY_WARNING_DAYS = 30      # alert_evaluation


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------

def stamp_new(record):
    """Populate system fields on a freshly built record (PRD §2.5)."""
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version (every modification, §2.5)."""
    record["updated_at"] = db.now_iso()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Money helpers (PRD §2.7 — integer cents, ROUND_HALF_UP, no floats)
# ---------------------------------------------------------------------------

def _rate(value):
    """JSON number -> exact Decimal (via str to avoid binary float noise)."""
    return Decimal(str(value))


def round_cents(dec):
    """Round a Decimal to whole cents (integer), half up."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# LicensePosition (calculation: entitled_quantity / deployed_quantity /
# gap_and_severity / position_exposure)
# ---------------------------------------------------------------------------

def position_for_product(product_id):
    for p in db.positions.values():
        if p["product_id"] == product_id:
            return p
    return None


def severity_ladder(product, gap, deployed, entitled):
    """Evaluate the severity rungs in order, stopping at the first match."""
    if gap <= 0:
        return "COMPLIANT"
    if entitled == 0:
        return "CRITICAL"
    if product["mission_critical"] and gap >= MISSION_CRITICAL_QTY:
        return "CRITICAL"
    if deployed * 100 >= entitled * 125 or gap >= CRITICAL_QTY:
        return "CRITICAL"
    if deployed * 100 > entitled * 105 or gap >= MATERIAL_QTY:
        return "MATERIAL"
    return "MINOR"


def recompute_position(pos):
    """Refresh every computed field of a LicensePosition from source records.

    Server-initiated recomputation counts as a modification (PRD §2.5), so
    the position's version increments and updated_at refreshes.
    """
    product = db.products[pos["product_id"]]
    pid = product["id"]
    entitled = sum(e["quantity"] for e in db.entitlements.values()
                   if e["product_id"] == pid and e["status"] == "ACTIVE")
    deployed = 0
    for d in db.deployments.values():
        if d["product_id"] != pid or d["status"] != "CONFIRMED":
            continue
        if d["environment"] == "PRODUCTION" or product["counts_non_production"]:
            deployed += d["measured_quantity"]
    gap = deployed - entitled
    pos["entitled_quantity"] = entitled
    pos["deployed_quantity"] = deployed
    pos["gap_quantity"] = gap
    pos["gap_severity"] = severity_ladder(product, gap, deployed, entitled)
    price = product["unit_list_price_cents"]
    factor = round_cents(Decimal(price) * (Decimal(1) + _rate(product["support_rate_pct"])))
    pos["self_audit_exposure_cents"] = max(0, gap) * price
    pos["vendor_list_exposure_cents"] = max(0, gap) * factor
    touch(pos)


# ---------------------------------------------------------------------------
# AuditCase rollups (calculation: case_exposure_rollup)
# ---------------------------------------------------------------------------

def recompute_case_rollups(case):
    """Refresh provisional/worst-case totals over CONFIRMED scope items.

    Exact integer-cent sums of stored per-line values; no re-rounding and
    (per PRD §2.8) no version bump here — the enumerated operations bump the
    case version themselves.
    """
    prov = 0
    worst = 0
    for it in db.scope_items.values():
        if it["audit_case_id"] != case["id"] or it["scope_status"] != "CONFIRMED":
            continue
        pos = position_for_product(it["product_id"])
        prov += pos["self_audit_exposure_cents"]
        if it["vendor_finding_amount_cents"] is not None:
            worst += it["vendor_finding_amount_cents"]
        else:
            worst += pos["vendor_list_exposure_cents"]
    case["provisional_case_exposure_cents"] = prov
    case["worst_case_exposure_cents"] = worst


def non_terminal_cases_scoping(product_id):
    """Non-terminal audit cases holding a CONFIRMED scope item for product."""
    case_ids = {it["audit_case_id"] for it in db.scope_items.values()
                if it["product_id"] == product_id
                and it["scope_status"] == "CONFIRMED"}
    return [c for c in db.audit_cases.values()
            if c["id"] in case_ids and c["status"] not in TERMINAL_CASE_STATES]


def cascade_product(product_id, bump_cases=False):
    """Position recompute -> case rollups -> alert upsert (PRD §2.8)."""
    pos = position_for_product(product_id)
    if pos is not None:
        recompute_position(pos)
    for case in non_terminal_cases_scoping(product_id):
        recompute_case_rollups(case)
        if bump_cases:
            touch(case)
    upsert_alerts(product_id)


# ---------------------------------------------------------------------------
# Vendor finding line pricing (calculation: vendor_finding_line_pricing)
# ---------------------------------------------------------------------------

def vendor_finding_line_cents(pos):
    """round_half_up(gap * price * (1 + 2 * support_rate_pct)).

    Read from the LicensePosition at the moment of the finding; the rounded
    per-line cent value is stored on the scope item and never recomputed.
    """
    product = db.products[pos["product_id"]]
    raw = (Decimal(pos["gap_quantity"])
           * Decimal(product["unit_list_price_cents"])
           * (Decimal(1) + Decimal(BACK_SUPPORT_YEARS) * _rate(product["support_rate_pct"])))
    return round_cents(raw)


# ---------------------------------------------------------------------------
# Response deadline (calculation: response_deadline)
# ---------------------------------------------------------------------------

def compute_response_deadline(notice_iso, days):
    return db.format_iso(db.parse_iso(notice_iso) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Entitlement window overlap (closed intervals; AUTO_TRUE_UP exempt)
# ---------------------------------------------------------------------------

def entitlement_window_overlap(product_id, coverage_class, new_from, new_to):
    nf = db.parse_iso(new_from)
    nt = db.parse_iso(new_to) if new_to else None  # None = perpetual (+inf)
    for e in db.entitlements.values():
        if e["product_id"] != product_id or e["coverage_class"] != coverage_class:
            continue
        if e["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if e["source"] == "AUTO_TRUE_UP":
            continue
        ef = db.parse_iso(e["effective_from"])
        et = db.parse_iso(e["effective_to"]) if e["effective_to"] else None
        # Closed intervals overlap iff nf <= et and ef <= nt.
        if (et is None or nf <= et) and (nt is None or ef <= nt):
            return True
    return False


# ---------------------------------------------------------------------------
# Concurrent audit occupation (scope item confirm)
# ---------------------------------------------------------------------------

def product_under_concurrent_audit(product_id, exclude_case_id):
    """True when another non-terminal case holds a CONFIRMED item for product."""
    other_case_ids = {it["audit_case_id"] for it in db.scope_items.values()
                      if it["product_id"] == product_id
                      and it["scope_status"] == "CONFIRMED"
                      and it["audit_case_id"] != exclude_case_id}
    for cid in other_case_ids:
        c = db.audit_cases.get(cid)
        if c is not None and c["status"] not in TERMINAL_CASE_STATES:
            return True
    return False


# ---------------------------------------------------------------------------
# Monitoring alerts (calculation: alert_evaluation; workflow §3.9)
# ---------------------------------------------------------------------------

def _find_live_alert(product_id, alert_type):
    for a in db.alerts.values():
        if a["product_id"] == product_id and a["alert_type"] == alert_type \
                and a["status"] in ("OPEN", "SUPPRESSED"):
            return a
    return None


def _eval_alert(product_id, alert_type, condition, value, threshold,
                severity, worse):
    """Upsert one (product, alert_type) alert per the evaluation rules.

    - condition true, no live alert        -> create OPEN
    - condition true, alert OPEN           -> re-stamp when values changed
    - condition true, alert SUPPRESSED     -> re-open only when the value
      worsened strictly beyond suppressed_value
    - condition false, live alert          -> RESOLVED (terminal)
    """
    alert = _find_live_alert(product_id, alert_type)
    if condition:
        if alert is None:
            alert = stamp_new({
                "product_id": product_id,
                "alert_type": alert_type,
                "severity": severity,
                "status": "OPEN",
                "triggered_value": value,
                "threshold_value": threshold,
                "suppressed_value": None,
                "suppression_reason": None,
            })
            db.alerts[alert["id"]] = alert
        elif alert["status"] == "OPEN":
            if (alert["severity"] != severity
                    or alert["triggered_value"] != value
                    or alert["threshold_value"] != threshold):
                alert["severity"] = severity
                alert["triggered_value"] = value
                alert["threshold_value"] = threshold
                touch(alert)
        else:  # SUPPRESSED
            if worse(value, alert["suppressed_value"]):
                alert["status"] = "OPEN"
                alert["severity"] = severity
                alert["triggered_value"] = value
                alert["threshold_value"] = threshold
                alert["suppressed_value"] = None
                alert["suppression_reason"] = None
                touch(alert)
    else:
        if alert is not None:
            alert["status"] = "RESOLVED"
            alert["suppressed_value"] = None
            touch(alert)


def upsert_alerts(product_id):
    """Evaluate both alert conditions for a product."""
    pos = position_for_product(product_id)
    if pos is None:
        return
    # OVER_DEPLOYMENT: gap_quantity > 0 (strictly greater; 0 does not fire)
    gap = pos["gap_quantity"]
    if gap > 0:
        sev = {"MINOR": "INFO", "MATERIAL": "WARNING",
               "CRITICAL": "CRITICAL"}[pos["gap_severity"]]
        _eval_alert(product_id, "OVER_DEPLOYMENT", True, gap, 0, sev,
                    lambda new, old: new > old)
    else:
        _eval_alert(product_id, "OVER_DEPLOYMENT", False, None, 0, None,
                    lambda new, old: new > old)
    # ENTITLEMENT_EXPIRING: some ACTIVE entitlement reaches effective_to
    # within [0, 30] whole days (floor; exactly 30 triggers, 31 does not).
    now = db.clock.now()
    best = None
    for e in db.entitlements.values():
        if e["product_id"] != product_id or e["status"] != "ACTIVE":
            continue
        if not e["effective_to"]:
            continue
        delta = db.parse_iso(e["effective_to"]) - now
        days = math.floor(delta.total_seconds() / 86400)
        if 0 <= days <= EXPIRY_WARNING_DAYS:
            best = days if best is None else min(best, days)
    if best is not None:
        _eval_alert(product_id, "ENTITLEMENT_EXPIRING", True, best,
                    EXPIRY_WARNING_DAYS, "WARNING",
                    lambda new, old: new < old)
    else:
        _eval_alert(product_id, "ENTITLEMENT_EXPIRING", False, None,
                    EXPIRY_WARNING_DAYS, None, lambda new, old: new < old)


# ---------------------------------------------------------------------------
# Logical clock sweep (PRD §2.4)
# ---------------------------------------------------------------------------

def clock_sweep():
    """Entitlement status sweep + position/rollup/alert recomputation.

    SCHEDULED -> ACTIVE once effective_from is reached; ACTIVE -> EXPIRED
    once the clock reaches or passes effective_to (monotonic, never reverts).
    """
    now = db.clock.now()
    affected = set()
    for e in db.entitlements.values():
        if e["status"] == "SCHEDULED" and db.parse_iso(e["effective_from"]) <= now:
            e["status"] = "ACTIVE"
            touch(e)
            affected.add(e["product_id"])
        elif e["status"] == "ACTIVE" and e["effective_to"] is not None \
                and now >= db.parse_iso(e["effective_to"]):
            e["status"] = "EXPIRED"
            touch(e)
            affected.add(e["product_id"])
    for pid in affected:
        cascade_product(pid)
    # ENTITLEMENT_EXPIRING depends on the clock alone: sweep every product
    # not already covered by a cascade (the upsert is change-detecting, so
    # untouched conditions do not churn alert versions).
    for pid in list(db.products.keys()):
        if pid not in affected:
            upsert_alerts(pid)
