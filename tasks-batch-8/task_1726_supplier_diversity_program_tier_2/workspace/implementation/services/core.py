"""Domain services: record factory, serializers, recomputations, cascades,
and the tier-2 / scorecard / attainment pipelines (PRD 3.2-3.10)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, next_seq
from util import new_id, wall_now_ts, render_instant, clock_date, parse_period

CERT_TYPES = ("MBE", "WBE", "VET", "SDVET", "LGBTQBE", "DOBE", "SBA8A", "SELF_CERT")
GOAL_CATEGORIES = ("ALL",) + CERT_TYPES
SUPPLIER_KINDS = ("DIVERSE", "PRIME", "BOTH")
TRACKS = ("MENTORING", "CAPABILITY_BUILDING", "ACCESS_TO_CAPITAL")
BASES = ("ACCRUAL", "CASH")

# Risk score constants (scaffold 1.3 supplier_risk_score)
FAILED_AUDIT_POINTS = 40
EXPIRED_UNRENEWED_POINTS = 10
OPEN_AUDIT_POINTS = 15
INFO_REQUESTED_POINTS = 5
SCORE_CAP = 100

ATTAINMENT_CAP = Decimal("999.99")
EXCEEDS_BAND = Decimal("110.00")
MEETS_BAND = Decimal("100.00")
NEAR_BAND = Decimal("80.00")


# ---------------------------------------------------------------------------
# Record factory / mutation bookkeeping
# ---------------------------------------------------------------------------

def make_record(fields):
    ts = wall_now_ts()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """PRD 2.4: version increments by 1 on every mutation of the resource."""
    rec["updated_at"] = wall_now_ts()
    rec["version"] = int(rec["version"]) + 1


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def supplier_certs(supplier_id):
    return [c for c in db["certifications"].values() if c["supplier_id"] == supplier_id]


def supplier_engagements(supplier_id):
    return [e for e in db["engagements"].values() if e["supplier_id"] == supplier_id]


def supplier_audits(supplier_id):
    return [a for a in db["audit_cases"].values() if a["supplier_id"] == supplier_id]


# ---------------------------------------------------------------------------
# Supplier derived state (PRD 3.2, 3.10)
# ---------------------------------------------------------------------------

def compute_diverse_eligible(supplier):
    """True iff >=1 VERIFIED cert whose closed window covers the clock date."""
    today = clock_date()
    for c in supplier_certs(supplier["id"]):
        if c["status"] == "VERIFIED" and c["valid_from"] <= today <= c["valid_to"]:
            return True
    return False


def refresh_diverse_eligible(supplier):
    """Update supplier.diverse_eligible; return True when the value changed."""
    value = compute_diverse_eligible(supplier)
    if supplier["diverse_eligible"] != value:
        supplier["diverse_eligible"] = value
        return True
    return False


def compute_risk_scores(supplier):
    sid = supplier["id"]
    audits = supplier_audits(sid)
    failed = sum(1 for a in audits if a["status"] == "FAILED")
    open_count = sum(1 for a in audits if a["status"] == "OPEN")
    certs = supplier_certs(sid)
    expired_unrenewed = 0
    for c in certs:
        if c["status"] != "EXPIRED":
            continue
        renewed = any(
            o is not c and o["cert_type"] == c["cert_type"] and o["status"] == "VERIFIED"
            for o in certs
        )
        if not renewed:
            expired_unrenewed += 1
    info = sum(1 for c in certs if c["status"] == "INFO_REQUESTED")
    standard = min(SCORE_CAP, FAILED_AUDIT_POINTS * failed
                   + EXPIRED_UNRENEWED_POINTS * expired_unrenewed)
    conservative = min(SCORE_CAP, FAILED_AUDIT_POINTS * failed
                       + EXPIRED_UNRENEWED_POINTS * expired_unrenewed
                       + OPEN_AUDIT_POINTS * open_count
                       + INFO_REQUESTED_POINTS * info)
    return standard, conservative


def refresh_risk_scores(supplier):
    standard, conservative = compute_risk_scores(supplier)
    changed = False
    if supplier["risk_score_standard"] != standard:
        supplier["risk_score_standard"] = standard
        changed = True
    if supplier["risk_score_conservative"] != conservative:
        supplier["risk_score_conservative"] = conservative
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Sourcing-event diverse_bid_count (PRD 3.7)
# ---------------------------------------------------------------------------

def recompute_event_bid_count(event):
    count = 0
    for inv in db["invitations"].values():
        if inv["sourcing_event_id"] != event["id"] or inv["status"] != "BID_SUBMITTED":
            continue
        sup = db["suppliers"].get(inv["supplier_id"])
        if sup is not None and sup["diverse_eligible"]:
            count += 1
    if event["diverse_bid_count"] != count:
        event["diverse_bid_count"] = count
        touch(event)


def recompute_events_for_supplier(supplier_id):
    seen = set()
    for inv in db["invitations"].values():
        if inv["supplier_id"] != supplier_id:
            continue
        ev_id = inv["sourcing_event_id"]
        if ev_id in seen:
            continue
        seen.add(ev_id)
        event = db["sourcing_events"].get(ev_id)
        if event is not None:
            recompute_event_bid_count(event)


def withdraw_supplier_invitations(supplier_id):
    """Suspension cascade: INVITED/BID_SUBMITTED -> WITHDRAWN, each withdrawal
    recomputing its owning event's diverse_bid_count (PRD 3.1/3.9)."""
    for inv in list(db["invitations"].values()):
        if inv["supplier_id"] != supplier_id:
            continue
        if inv["status"] not in ("INVITED", "BID_SUBMITTED"):
            continue
        inv["status"] = "WITHDRAWN"
        touch(inv)
        event = db["sourcing_events"].get(inv["sourcing_event_id"])
        if event is not None:
            recompute_event_bid_count(event)


def suspend_supplier_cascade(supplier):
    """Shared ACTIVE -> SUSPENDED cascade (manual suspend and audit failure)."""
    changed = False
    if supplier["status"] == "ACTIVE":
        supplier["status"] = "SUSPENDED"
        changed = True
    if refresh_diverse_eligible(supplier):
        changed = True
    if changed:
        touch(supplier)
    withdraw_supplier_invitations(supplier["id"])
    recompute_events_for_supplier(supplier["id"])


# ---------------------------------------------------------------------------
# Tier-2 aggregation (PRD 3.4): per-line round-half-up first, then sum.
# ---------------------------------------------------------------------------

def compute_tier2_totals(lines):
    total_subcontracted = 0
    total_diverse = 0
    for line in lines:
        gross = int(line["gross_subcontract_cents"])
        pct = Decimal(str(line["diverse_share_pct"]))
        allocated = int(
            (Decimal(gross) * pct / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        total_subcontracted += gross
        total_diverse += allocated
    return total_subcontracted, total_diverse


# ---------------------------------------------------------------------------
# Scorecard pipeline (PRD 3.6): attribution, tier-2 roll-up, attainment.
# ---------------------------------------------------------------------------

def compute_scorecard_fields(business_unit_id, reporting_period, attribution_basis):
    year, _quarter, period_start, period_end = parse_period(reporting_period)

    def basis_date(rec):
        if attribution_basis == "ACCRUAL":
            return rec["transaction_date"]
        return rec["payment_date"]

    input_records = [
        r for r in db["spend_records"].values()
        if r["business_unit_id"] == business_unit_id
        and r["status"] == "POSTED"
        and period_start <= basis_date(r) <= period_end
    ]
    total_spend = sum(r["amount_cents"] for r in input_records)

    direct = 0
    by_category = {}
    for r in input_records:
        bdate = basis_date(r)
        covering = [
            c for c in supplier_certs(r["supplier_id"])
            if c["status"] in ("VERIFIED", "EXPIRED")
            and c["valid_from"] <= bdate <= c["valid_to"]
        ]
        if not covering:
            continue
        direct += r["amount_cents"]
        # Latest valid_from wins; identical valid_from -> created_at ascending.
        covering.sort(key=lambda c: (c["created_at"], c["_seq"]))
        covering.sort(key=lambda c: c["valid_from"], reverse=True)
        chosen = covering[0]
        by_category[chosen["cert_type"]] = (
            by_category.get(chosen["cert_type"], 0) + r["amount_cents"]
        )

    tier2 = sum(
        rep["total_diverse_tier2_cents"]
        for rep in db["tier2_reports"].values()
        if rep["business_unit_id"] == business_unit_id
        and rep["reporting_period"] == reporting_period
        and rep["status"] == "APPROVED"
    )

    goal = None
    for g in db["goals"].values():
        if (g["business_unit_id"] == business_unit_id
                and g["cert_category"] == "ALL"
                and g["fiscal_year"] == year
                and g["status"] == "PUBLISHED"):
            goal = g
            break

    if goal is None:
        attainment = None
        rating = "NO_GOAL"
        goal_id = None
    else:
        goal_id = goal["id"]
        effective = direct + (tier2 if goal["include_tier2"] else 0)
        if goal["goal_type"] == "PERCENT_OF_SPEND":
            if total_spend == 0:
                actual_pct = Decimal("0.00")
            else:
                actual_pct = (
                    Decimal(100) * Decimal(effective) / Decimal(total_spend)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            attainment_d = (
                Decimal(100) * actual_pct / Decimal(str(goal["target_value"]))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:  # ABSOLUTE_AMOUNT
            attainment_d = (
                Decimal(100) * Decimal(effective)
                / Decimal(int(goal["target_value"]))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if attainment_d > ATTAINMENT_CAP:
            attainment_d = ATTAINMENT_CAP
        attainment = float(attainment_d)
        if attainment_d >= EXCEEDS_BAND:
            rating = "EXCEEDS"
        elif attainment_d >= MEETS_BAND:
            rating = "MEETS"
        elif attainment_d >= NEAR_BAND:
            rating = "NEAR"
        else:
            rating = "BELOW"

    return {
        "total_spend_cents": total_spend,
        "direct_diverse_spend_cents": direct,
        "tier2_diverse_spend_cents": tier2,
        "spend_by_category": by_category,
        "attainment_pct": attainment,
        "rating": rating,
        "goal_id": goal_id,
    }


# ---------------------------------------------------------------------------
# Serializers (public views; exact field sets, dates rendered as ISO strings)
# ---------------------------------------------------------------------------

def _base(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def pub_business_unit(r):
    out = _base(r)
    out.update({
        "name": r["name"],
        "code": r["code"],
        "lead_user_id": r["lead_user_id"],
        "inclusion_min_diverse_bidders": r["inclusion_min_diverse_bidders"],
        "lifetime_imported_spend_cents": r["lifetime_imported_spend_cents"],
        "lifetime_voided_spend_cents": r["lifetime_voided_spend_cents"],
    })
    return out


def pub_supplier(r):
    out = _base(r)
    out.update({
        "legal_name": r["legal_name"],
        "tax_id": r["tax_id"],
        "kind": r["kind"],
        "contact_email": r["contact_email"],
        "status": r["status"],
        "diverse_eligible": r["diverse_eligible"],
        "risk_score_standard": r["risk_score_standard"],
        "risk_score_conservative": r["risk_score_conservative"],
    })
    return out


def pub_certification(r):
    out = _base(r)
    out.update({
        "supplier_id": r["supplier_id"],
        "cert_type": r["cert_type"],
        "certifying_body": r["certifying_body"],
        "certificate_number": r["certificate_number"],
        "valid_from": r["valid_from"].isoformat(),
        "valid_to": r["valid_to"].isoformat(),
        "status": r["status"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "verified_by_user_id": r["verified_by_user_id"],
        "review_note": r["review_note"],
    })
    return out


def pub_spend_record(r):
    out = _base(r)
    out.update({
        "supplier_id": r["supplier_id"],
        "business_unit_id": r["business_unit_id"],
        "amount_cents": r["amount_cents"],
        "transaction_date": r["transaction_date"].isoformat(),
        "payment_date": r["payment_date"].isoformat(),
        "po_number": r["po_number"],
        "status": r["status"],
    })
    return out


def pub_tier2_report(r):
    out = _base(r)
    out.update({
        "prime_supplier_id": r["prime_supplier_id"],
        "business_unit_id": r["business_unit_id"],
        "reporting_period": r["reporting_period"],
        "lines": [dict(line) for line in r["lines"]],
        "total_subcontracted_cents": r["total_subcontracted_cents"],
        "total_diverse_tier2_cents": r["total_diverse_tier2_cents"],
        "status": r["status"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
    })
    return out


def pub_goal(r):
    out = _base(r)
    out.update({
        "business_unit_id": r["business_unit_id"],
        "fiscal_year": r["fiscal_year"],
        "cert_category": r["cert_category"],
        "goal_type": r["goal_type"],
        "target_value": r["target_value"],
        "include_tier2": r["include_tier2"],
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
    })
    return out


def pub_scorecard(r):
    out = _base(r)
    out.update({
        "business_unit_id": r["business_unit_id"],
        "reporting_period": r["reporting_period"],
        "attribution_basis": r["attribution_basis"],
        "total_spend_cents": r["total_spend_cents"],
        "direct_diverse_spend_cents": r["direct_diverse_spend_cents"],
        "tier2_diverse_spend_cents": r["tier2_diverse_spend_cents"],
        "spend_by_category": dict(r["spend_by_category"]),
        "attainment_pct": r["attainment_pct"],
        "rating": r["rating"],
        "goal_id": r["goal_id"],
        "status": r["status"],
    })
    return out


def pub_sourcing_event(r):
    out = _base(r)
    out.update({
        "business_unit_id": r["business_unit_id"],
        "title": r["title"],
        "estimated_value_cents": r["estimated_value_cents"],
        "required_diverse_bidders": r["required_diverse_bidders"],
        "award_supplier_id": r["award_supplier_id"],
        "award_amount_cents": r["award_amount_cents"],
        "inclusion_waiver_reason": r["inclusion_waiver_reason"],
        "diverse_bid_count": r["diverse_bid_count"],
        "status": r["status"],
    })
    return out


def pub_invitation(r):
    out = _base(r)
    out.update({
        "sourcing_event_id": r["sourcing_event_id"],
        "supplier_id": r["supplier_id"],
        "status": r["status"],
    })
    return out


def pub_engagement(r):
    out = _base(r)
    out.update({
        "supplier_id": r["supplier_id"],
        "track": r["track"],
        "start_date": r["start_date"].isoformat(),
        "end_date": r["end_date"].isoformat(),
        "mentor_name": r["mentor_name"],
        "capacity_score_before": r["capacity_score_before"],
        "capacity_score_after": r["capacity_score_after"],
        "improvement": r["improvement"],
        "status": r["status"],
    })
    return out


def pub_audit_case(r):
    out = _base(r)
    out.update({
        "supplier_id": r["supplier_id"],
        "certification_id": r["certification_id"],
        "reason": r["reason"],
        "auditor_user_id": r["auditor_user_id"],
        "outcome": r["outcome"],
        "outcome_recorded_at": render_instant(r["outcome_recorded_at"]),
        "status": r["status"],
    })
    return out
