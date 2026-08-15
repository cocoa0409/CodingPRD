"""Business logic: calculations, posture, cascades (scaffold §1.2/§1.3)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import next_seq, now_iso, store, touch

LIVE_PO_STATUSES = {"ACTIVE", "PARTIALLY_SHIPPED", "SHIPPED"}
YTD_PO_STATUSES = {"ACTIVE", "PARTIALLY_SHIPPED", "SHIPPED", "CLOSED"}

TIER1_MAX_CENTS = 10000000
TIER2_MAX_CENTS = 50000000
SUSPENSION_THRESHOLD_CENTS = 1000000
NEGOTIATION_ROUND_CAP = 6
REVISION_CAP = 3
CIF_CAP_RATE = Decimal("0.12")
CRITICAL_FINDING_DEDUCTION = 5

REQUIRED_DOCS_BY_CATEGORY = {
    "APPAREL": {"SOCIAL_AUDIT", "PRODUCT_TEST"},
    "ELECTRONICS": {"PRODUCT_TEST", "LAB_TEST"},
    "TOYS": {"PRODUCT_TEST", "LAB_TEST", "SOCIAL_AUDIT"},
    "FURNITURE": {"FIRE_SAFETY", "PRODUCT_TEST"},
}

AQL_SAMPLE_SIZES = ((500, 50), (1200, 80), (3200, 125))
AQL_AC_RE = {50: (3, 4), 80: (5, 6), 125: (7, 8), 200: (10, 11)}


def _q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q0(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Views with dynamically computed roll-ups
# ---------------------------------------------------------------------------

def buyer_ytd_gmv_cents(buyer_id):
    year = store.clock.year
    total = 0
    for po in store.purchase_orders.values():
        if (
            po["buyer_id"] == buyer_id
            and po["status"] in YTD_PO_STATUSES
            and po["_created_dt"].year == year
        ):
            total += po["total_cents"]
    return total


def agent_commission_ytd_cents(agent_id):
    year = store.clock.year
    total = 0
    for po in store.purchase_orders.values():
        if (
            po["assigned_agent_id"] == agent_id
            and po["status"] == "CLOSED"
            and po["_created_dt"].year == year
            and po["final_commission_cents"] is not None
        ):
            total += po["final_commission_cents"]
    return total


# ---------------------------------------------------------------------------
# §1.3 audit_score
# ---------------------------------------------------------------------------

def compute_audit_score(audit_type, qs, sc, pc, fs, critical_findings):
    if audit_type == "SCREENING":
        weights = (Decimal("0.35"), Decimal("0.25"), Decimal("0.25"), Decimal("0.15"))
    else:
        weights = (Decimal("0.40"), Decimal("0.30"), Decimal("0.20"), Decimal("0.10"))
    scores = (qs, sc, pc, fs)
    raw = Decimal(0)
    for score_i, weight_i in zip(scores, weights):
        raw += _q2(Decimal(score_i) * weight_i)
    if audit_type == "ONSITE":
        raw -= Decimal(CRITICAL_FINDING_DEDUCTION * critical_findings)
        if raw < 0:
            raw = Decimal(0)
    score = int(_q0(raw))
    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 50:
        grade = "C"
    else:
        grade = "D"
    return score, grade


def refresh_factory_grade(factory):
    """Re-derive latest_audit_grade/audit_score from APPROVED ONSITE audits.

    Selection: most recent approved_at, tie-break created_at ascending, then
    approval sequence descending. Bumps Factory.version when fields rewritten.
    """
    approved = [
        a
        for a in store.audits.values()
        if a["factory_id"] == factory["id"]
        and a["status"] == "APPROVED"
        and a["audit_type"] == "ONSITE"
    ]
    if not approved:
        grade, score, source = "NONE", 0, None
    else:
        approved.sort(
            key=lambda a: (
                -a["_approved_dt"].timestamp(),
                a["_created_dt"].timestamp(),
                a["_seq"],
                -(a["_approved_seq"] or 0),
            )
        )
        winner = approved[0]
        grade, score, source = winner["grade"], winner["score"], winner["id"]
    if (
        factory.get("_grade_source") != source
        or factory["latest_audit_grade"] != grade
        or factory["audit_score"] != score
    ):
        factory["latest_audit_grade"] = grade
        factory["audit_score"] = score
        factory["_grade_source"] = source
        touch(factory)


# ---------------------------------------------------------------------------
# §1.3 commission (provisional + final variants)
# ---------------------------------------------------------------------------

def compute_commission(po, sr):
    basis = buyer_ytd_gmv_cents(po["buyer_id"])
    if basis < TIER1_MAX_CENTS:
        rate_bp = 500
    elif basis < TIER2_MAX_CENTS:
        rate_bp = 400
    else:
        rate_bp = 300
    base = po["total_cents"]
    if sr["commission_mode"] == "CIF":
        base += po["freight_cents"] + po["insurance_cents"]
    commission = int(_q0(Decimal(base) * Decimal(rate_bp) / Decimal(10000)))
    if sr["commission_mode"] == "CIF":
        cap = int(_q0(Decimal(po["total_cents"]) * CIF_CAP_RATE))
        commission = min(commission, cap)
    return commission, rate_bp


# ---------------------------------------------------------------------------
# §1.3 aql_result
# ---------------------------------------------------------------------------

def aql_sample_size(lot_size):
    for upper, n in AQL_SAMPLE_SIZES:
        if lot_size <= upper:
            return n
    return 200


def aql_result(sample_size, defects_critical, defects_major, defects_minor):
    ac, re = AQL_AC_RE[sample_size]
    if defects_critical > 0:
        return "FAILED"
    if defects_major >= re:
        return "FAILED"
    if defects_minor > 2 * ac:
        return "FAILED"
    return "PASSED"


# ---------------------------------------------------------------------------
# §1.3 chargeback
# ---------------------------------------------------------------------------

def compute_chargeback(claim, po):
    base_lines = [
        item["qty_defective"] * item["unit_price_cents"] for item in claim["items"]
    ]
    base_amount = sum(base_lines)
    defective_qty = sum(item["qty_defective"] for item in claim["items"])
    defect_rate = (Decimal(defective_qty) / Decimal(po["ordered_qty"])).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    if defect_rate <= Decimal("0.05"):
        penalty_rate = Decimal("0")
    elif defect_rate <= Decimal("0.10"):
        penalty_rate = Decimal("0.02")
    else:
        penalty_rate = Decimal("0.05")
    penalty = sum(int(_q0(Decimal(line) * penalty_rate)) for line in base_lines)
    total = base_amount + penalty
    return base_amount, defective_qty, defect_rate, penalty, total


# ---------------------------------------------------------------------------
# §1.3 committed_units / capacity
# ---------------------------------------------------------------------------

def committed_units(factory_id, delivery_month, exclude_po_id=None):
    total = 0
    for po in store.purchase_orders.values():
        if (
            po["factory_id"] == factory_id
            and po["delivery_month"] == delivery_month
            and po["status"] in LIVE_PO_STATUSES
            and po["id"] != exclude_po_id
        ):
            total += po["open_qty"] + po["shipped_qty"]
    return total


# ---------------------------------------------------------------------------
# §1.3 compliance_posture + ship gate
# ---------------------------------------------------------------------------

def compute_posture(factory_id):
    categories = set()
    for po in store.purchase_orders.values():
        if po["factory_id"] == factory_id and po["status"] in LIVE_PO_STATUSES:
            sr = store.sourcing_requests.get(po["sourcing_request_id"])
            if sr is not None:
                categories.add(sr["product_category"])
    if not categories:
        return "COMPLIANT"
    required = set()
    for category in categories:
        required |= REQUIRED_DOCS_BY_CATEGORY[category]
    for doc_type in required:
        satisfied = any(
            doc["factory_id"] == factory_id
            and doc["doc_type"] == doc_type
            and doc["status"] == "VERIFIED"
            and doc["_expires_dt"] > store.clock
            for doc in store.documents.values()
        )
        if not satisfied:
            return "NON_COMPLIANT"
    return "COMPLIANT"


def apply_posture(factory, new_posture):
    """Rewrite factory posture; on flip, rewrite ship_blocked on live POs."""
    if factory["compliance_posture"] == new_posture:
        return
    factory["compliance_posture"] = new_posture
    touch(factory)
    blocked = new_posture == "NON_COMPLIANT"
    for po in store.purchase_orders.values():
        if po["factory_id"] == factory["id"] and po["status"] in LIVE_PO_STATUSES:
            if po["ship_blocked"] != blocked:
                po["ship_blocked"] = blocked
                touch(po)


# ---------------------------------------------------------------------------
# Clock sweeps (PRD §2.5)
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    affected_factories = []
    for doc in store.documents.values():
        if doc["status"] == "VERIFIED" and doc["_expires_dt"] < store.clock:
            doc["status"] = "EXPIRED"
            touch(doc)
            if doc["factory_id"] not in affected_factories:
                affected_factories.append(doc["factory_id"])
    for factory_id in affected_factories:
        factory = store.factories.get(factory_id)
        if factory is not None:
            apply_posture(factory, compute_posture(factory_id))
    for quotation in store.quotations.values():
        if (
            quotation["status"] in ("OPEN", "COUNTERED")
            and quotation["_valid_until_dt"] < store.clock
        ):
            quotation["status"] = "EXPIRED"
            touch(quotation)


# ---------------------------------------------------------------------------
# Shared PO helpers
# ---------------------------------------------------------------------------

def live_shipments(po_id):
    return [
        s
        for s in store.shipments.values()
        if s["po_id"] == po_id and s["status"] != "CANCELLED"
    ]


def latest_delivered_at(po_id):
    delivered = [
        s["_delivered_dt"]
        for s in store.shipments.values()
        if s["po_id"] == po_id and s["status"] == "DELIVERED" and s["_delivered_dt"]
    ]
    return max(delivered) if delivered else None


def claim_window_open(po_id):
    latest = latest_delivered_at(po_id)
    if latest is None:
        return False
    return store.clock <= latest + timedelta(days=30)


def close_po_if_complete(po):
    """After a confirm-receipt: close PO when fully shipped and delivered."""
    if po["open_qty"] != 0:
        return False
    shipments = live_shipments(po["id"])
    if not shipments or any(s["status"] != "DELIVERED" for s in shipments):
        return False
    po["status"] = "CLOSED"
    sr = store.sourcing_requests.get(po["sourcing_request_id"])
    commission, rate_bp = compute_commission(po, sr)
    po["final_commission_cents"] = commission
    po["commission_rate_bp"] = rate_bp
    touch(po)
    if sr is not None and sr["status"] == "PO_PLACED":
        sr["status"] = "COMPLETED"
        touch(sr)
    return True


def suspend_factory_cascade(factory):
    """Claim-approval cascade: SUSPEND factory, expire quotes, cancel POs."""
    factory["status"] = "SUSPENDED"
    for quotation in store.quotations.values():
        if quotation["factory_id"] == factory["id"] and quotation["status"] in (
            "OPEN",
            "COUNTERED",
        ):
            quotation["status"] = "EXPIRED"
            touch(quotation)
    for po in store.purchase_orders.values():
        if (
            po["factory_id"] == factory["id"]
            and po["status"] == "ACTIVE"
            and po["shipped_qty"] == 0
        ):
            po["status"] = "CANCELLED"
            po["cancelled_qty"] += po["open_qty"]
            po["open_qty"] = 0
            touch(po)


def recompute_remaining_payable(po):
    approved_total = sum(
        c["total_chargeback_cents"]
        for c in store.claims.values()
        if c["po_id"] == po["id"] and c["status"] == "APPROVED"
    )
    po["remaining_payable_cents"] = po["total_cents"] - approved_total
