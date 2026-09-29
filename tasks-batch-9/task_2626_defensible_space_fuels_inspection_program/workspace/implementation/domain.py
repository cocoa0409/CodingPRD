"""Shared domain helpers: conserved counters, cascades and derived metrics.

Every counter here is maintained as a conservation identity (PRD section 2.10):
it is recomputed from the record set it is defined over, so a compensating
operation restores it to exactly its pre-operation value.
"""

import datetime
from decimal import Decimal

import calc
from db import db, insert, sort_created
from errors import fail
from response import touch

UTC = datetime.timezone.utc

OPEN_NOTICE_STATUSES = ("ISSUED", "EXTENDED", "OVERDUE", "ABATEMENT_AUTHORIZED")
LIVE_INSPECTION_STATUSES = ("SCHEDULED", "NOTICED", "ACCESS_DENIED")
LIVE_ORDER_STATUSES = ("AWARDED", "WORK_COMPLETE")
LIVE_ORDER_ON_NOTICE = ("AUTHORIZED", "AWARDED", "WORK_COMPLETE", "INVOICED")
RESERVING_ENROLLMENT_STATUSES = ("APPROVED", "COMPLETED", "REIMBURSED")
LIVE_ENROLLMENT_STATUSES = (
    "REQUESTED", "APPROVED", "WAITLISTED", "COMPLETED", "REIMBURSED",
)


# --- rung 11: cycle activity -------------------------------------------------
def require_active_cycle(cycle):
    if cycle is None or cycle["status"] != "ACTIVE":
        fail("ERR_CYCLE_NOT_ACTIVE", "The governing inspection cycle is not ACTIVE.")


def governing_cycle(inspection):
    return db.cycles.get(inspection["cycle_id"])


# --- collection views --------------------------------------------------------
def parcel_notices(parcel_id):
    return sort_created([n for n in db.notices.values() if n["parcel_id"] == parcel_id])


def parcel_certificates(parcel_id):
    return sort_created(
        [c for c in db.certificates.values() if c["parcel_id"] == parcel_id]
    )


def inspection_zone_evaluations(inspection_id):
    return sort_created(
        [z for z in db.zone_evaluations.values() if z["inspection_id"] == inspection_id]
    )


def inspection_hardening_findings(inspection_id):
    return sort_created(
        [f for f in db.hardening_findings.values()
         if f["inspection_id"] == inspection_id]
    )


def order_payments(order_id):
    return sort_created(
        [p for p in db.payments.values() if p["abatement_order_id"] == order_id]
    )


def program_enrollments(program_id):
    return sort_created(
        [e for e in db.enrollments.values() if e["support_program_id"] == program_id]
    )


def community_parcels(community_id):
    return sort_created(
        [p for p in db.parcels.values() if p["community_id"] == community_id]
    )


def notice_order(notice_id):
    """The live abatement order raised under a notice, if any."""
    for order in sort_created(list(db.orders.values())):
        if order["violation_notice_id"] == notice_id:
            if order["status"] in LIVE_ORDER_ON_NOTICE:
                return order
    return None


def notice_orders(notice_id):
    return sort_created(
        [o for o in db.orders.values() if o["violation_notice_id"] == notice_id]
    )


# --- conserved counters ------------------------------------------------------
def recount_open_violations(parcel):
    parcel["open_violation_count"] = sum(
        1 for n in db.notices.values()
        if n["parcel_id"] == parcel["id"] and n["status"] in OPEN_NOTICE_STATUSES
    )
    return parcel["open_violation_count"]


def recount_inspector_load(inspector):
    if inspector is None:
        return
    inspector["assigned_open_count"] = sum(
        1 for i in db.inspections.values()
        if i["inspector_id"] == inspector["id"]
        and i["status"] in LIVE_INSPECTION_STATUSES
    )


def recount_contractor_commitment(contractor):
    if contractor is None:
        return
    total = Decimal("0")
    for order in db.orders.values():
        if order["contractor_id"] == contractor["id"] and order["status"] in LIVE_ORDER_STATUSES:
            total += Decimal(order["crew_hours"] or 0)
    contractor["committed_crew_hours"] = calc.rhu(total, 1)


def recount_program_reservations(program):
    reserved_total = 0
    slots = 0
    for enrollment in db.enrollments.values():
        if enrollment["support_program_id"] != program["id"]:
            continue
        if enrollment["status"] in RESERVING_ENROLLMENT_STATUSES:
            reserved_total += enrollment["reserved_amount_cents"] or 0
            slots += 1
    program["budget_remaining_cents"] = program["budget_total_cents"] - reserved_total
    program["reserved_slots"] = slots


def renumber_waitlist(program):
    waitlisted = [
        e for e in program_enrollments(program["id"]) if e["status"] == "WAITLISTED"
    ]
    for index, enrollment in enumerate(waitlisted, start=1):
        enrollment["waitlist_position"] = index


# --- parcel posture ----------------------------------------------------------
def recompute_parcel_posture(parcel, verified_clear=False):
    """Re-derive compliance_status after notices closed or opened.

    ``verified_clear`` is the abatement-verification variant of PRD section 3.7
    link 4, where an empty open-notice set yields ``COMPLIANT`` outright.
    """
    if parcel["exemption_flag"]:
        parcel["compliance_status"] = "EXEMPT"
        return
    count = recount_open_violations(parcel)
    has_authorized = any(
        n["parcel_id"] == parcel["id"] and n["status"] == "ABATEMENT_AUTHORIZED"
        for n in db.notices.values()
    )
    if has_authorized:
        parcel["compliance_status"] = "ABATEMENT_PENDING"
    elif count > 0:
        parcel["compliance_status"] = "NON_COMPLIANT"
    elif verified_clear:
        parcel["compliance_status"] = "COMPLIANT"
    elif parcel["last_passed_inspection_at_utc"] is not None:
        parcel["compliance_status"] = "COMPLIANT"
    else:
        parcel["compliance_status"] = "PENDING_INSPECTION"


def rescore_parcel(parcel, veg_points=None, hardening_credit=None, basis=None):
    if basis is None:
        basis = parcel.get("risk_score_basis") or "INTAKE_PROVISIONAL"
    if basis == "POST_INSPECTION_VERIFIED" and veg_points is None:
        veg_points = parcel.get("_verified_veg_points")
        hardening_credit = parcel.get("_verified_hardening_credit")
    if hardening_credit is None:
        hardening_credit = Decimal("0.00")
    parcel["risk_score"] = calc.risk_score(parcel, veg_points, hardening_credit)
    parcel["risk_class"] = calc.risk_class(parcel["risk_score"])
    parcel["risk_score_basis"] = basis


# --- community rate and lapse ------------------------------------------------
def metrics_for(parcels):
    eligible = [p for p in parcels if p["compliance_status"] in calc.ELIGIBLE_STATUSES]
    compliant = [p for p in eligible if p["compliance_status"] == "COMPLIANT"]
    if not eligible:
        rate = None
    else:
        rate = calc.rhu(Decimal(100) * len(compliant) / Decimal(len(eligible)), 2)
    return len(eligible), len(compliant), rate


def community_rate(community_id):
    return metrics_for(community_parcels(community_id))[2]


def recompute_community(community, allow_lapse=True):
    """Recompute the community-scoped rate, then lapse if it broke the floor."""
    fresh = community_rate(community["id"])
    if community["compliance_rate_pct"] != fresh:
        community["compliance_rate_pct"] = fresh
        touch(community)
    if (
        allow_lapse
        and community["status"] == "CERTIFIED"
        and fresh is not None
        and fresh < calc.COMMUNITY_LAPSE_FLOOR_PCT
    ):
        community["status"] = "LAPSED"
        community["lapse_count"] += 1
        touch(community)
    return fresh


def cascade_parcel_posture(parcel, allow_lapse=True):
    """A parcel posture change is transitive: the community rate that reads it
    is recomputed in the same request (PRD section 2.10)."""
    if not parcel["community_id"]:
        return
    community = db.communities.get(parcel["community_id"])
    if community is not None:
        recompute_community(community, allow_lapse=allow_lapse)


# --- priority ranking --------------------------------------------------------
def staleness_days(parcel):
    last = parcel["last_passed_inspection_at_utc"]
    if last is None:
        return calc.NEVER_INSPECTED_STALENESS_DAYS
    return int((db.clock - last).total_seconds() // 86400)


def recompute_priority_ranks():
    candidates = [p for p in db.parcels.values() if not p["exemption_flag"]]
    ordered = sorted(
        candidates,
        key=lambda p: (
            -calc.RISK_CLASS_ORDINAL[p["risk_class"]],
            -p["open_violation_count"],
            -staleness_days(p),
            p["created_at"],
            p["_seq"],
        ),
    )
    for index, parcel in enumerate(ordered, start=1):
        parcel["inspection_priority_rank"] = index


# --- district metrics --------------------------------------------------------
def survival_correlation(parcels):
    pool = [
        p for p in parcels
        if p["structure_survival_outcome"] in ("SURVIVED", "DESTROYED")
        and p["compliance_status"] in calc.ELIGIBLE_STATUSES
    ]
    compliant = [p for p in pool if p["compliance_status"] == "COMPLIANT"]
    noncompliant = [p for p in pool if p["compliance_status"] != "COMPLIANT"]

    def pct(group):
        if not group:
            return None
        survived = sum(1 for p in group if p["structure_survival_outcome"] == "SURVIVED")
        return calc.rhu(Decimal(100) * survived / Decimal(len(group)), 2)

    survived_compliant = pct(compliant)
    survived_noncompliant = pct(noncompliant)
    if survived_compliant is None or survived_noncompliant is None:
        delta = None
    else:
        delta = calc.rhu(survived_compliant - survived_noncompliant, 2)
    return survived_compliant, survived_noncompliant, delta


def district_metrics(cycle):
    parcels = list(db.parcels.values())
    eligible, compliant, rate = metrics_for(parcels)
    survived_compliant, survived_noncompliant, delta = survival_correlation(parcels)
    return {
        "eligible_parcel_count": eligible,
        "compliant_parcel_count": compliant,
        "compliance_rate_pct": rate,
        "survived_compliant_pct": survived_compliant,
        "survived_noncompliant_pct": survived_noncompliant,
        "survival_delta_pp": delta,
        "epoch": cycle["epoch"],
    }


# --- notice creation and supersession (PRD section 3.6) ----------------------
def issue_notice(parcel, inspection, severity, notice_method, supersede):
    superseded_id = None
    if supersede:
        open_notices = [
            n for n in parcel_notices(parcel["id"])
            if n["status"] in ("ISSUED", "EXTENDED", "OVERDUE")
        ]
        for existing in open_notices:
            existing["status"] = "VOIDED"
            existing["void_reason"] = "SUPERSEDED_BY_NEW_NOTICE"
            touch(existing)
            superseded_id = existing["id"]

    issued_at = db.clock
    delivered_at, compliance_days, deadline = calc.notice_dates(
        issued_at, notice_method, severity, parcel["hazard_zone"]
    )
    notice = insert(db.notices, {
        "parcel_id": parcel["id"],
        "inspection_id": inspection["id"] if inspection else None,
        "severity": severity,
        "notice_method": notice_method,
        "status": "ISSUED",
        "issued_at_utc": issued_at,
        "delivered_at_utc": delivered_at,
        "compliance_days": compliance_days,
        "deadline_utc": deadline,
        "extension_count": 0,
        "cleared_at_utc": None,
        "void_reason": None,
        "supersedes_notice_id": superseded_id,
    })
    recount_open_violations(parcel)
    return notice


def revoke_certificates(parcel):
    """PRD section 3.5 link 4: an unexpired ISSUED certificate is revoked."""
    for certificate in parcel_certificates(parcel["id"]):
        if certificate["status"] != "ISSUED":
            continue
        if certificate["expires_at_utc"] is not None and certificate["expires_at_utc"] < db.clock:
            continue
        certificate["status"] = "REVOKED"
        certificate["revoked_at_utc"] = db.clock
        touch(certificate)
