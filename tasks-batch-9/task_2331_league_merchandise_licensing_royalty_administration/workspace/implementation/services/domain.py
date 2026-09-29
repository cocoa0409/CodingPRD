"""Derived-field recomputation, the compliance risk index, posture recomputes
and every cascade described in PRD section 3.
"""

from fractions import Fraction

import db
from db import S, apply_changes, touch
from services import calc

# risk weights
WEIGHT_SAMPLE_FAIL = 8
WEIGHT_SUBMISSION_REJECTED = 5
WEIGHT_REPORT_RETURN = 6
WEIGHT_AUDIT_UNDERREPORT = 20
WEIGHT_ENFORCEMENT_SEIZURE = 15

WINDOW_QUARTERS = 8
INDEX_CEILING = 100

MARK_CLASS_ENVELOPE = {
    "LEAGUE_ONLY": {"LEAGUE"},
    "LEAGUE_AND_CLUB": {"LEAGUE", "CLUB"},
    "LEAGUE_CLUB_AND_PLAYER": {"LEAGUE", "CLUB", "PLAYER_GROUP", "PLAYER_INDIVIDUAL"},
}

HELD_SUBMISSION_STATES = ("SUBMITTED", "IN_REVIEW", "SAMPLE_REQUESTED")


# --------------------------------------------------------------------------- #
# lookups                                                                     #
# --------------------------------------------------------------------------- #

def category_of(agreement):
    return S.categories[agreement["category_id"]]


def licensee_of(agreement):
    return S.licensees[agreement["licensee_id"]]


def agreements_of(licensee_id):
    return [a for a in S.agreements.values() if a["licensee_id"] == licensee_id]


def submissions_of(agreement_id):
    return [s for s in S.submissions.values() if s["agreement_id"] == agreement_id]


def grants_of(agreement_id):
    return [g for g in S.grants.values() if g["agreement_id"] == agreement_id]


def reports_of(agreement_id):
    return [r for r in S.reports.values() if r["agreement_id"] == agreement_id]


def authorizations_of(licensee_id):
    return [a for a in S.authorizations.values() if a["licensee_id"] == licensee_id]


def engagements_of_licensee(licensee_id):
    ids = {a["id"] for a in agreements_of(licensee_id)}
    return [e for e in S.engagements.values() if e["agreement_id"] in ids]


def approved_sku_classes(licensee_id):
    classes = set()
    for agreement in agreements_of(licensee_id):
        for sub in submissions_of(agreement["id"]):
            if sub["status"] == "APPROVED":
                classes.add(sub["sku_class"])
    return classes


# --------------------------------------------------------------------------- #
# licensee aggregates                                                         #
# --------------------------------------------------------------------------- #

def refresh_agreement_count(licensee):
    count = len([a for a in agreements_of(licensee["id"])
                 if a["contract_status"] != "TERMINATED"])
    apply_changes(licensee, {"agreement_count": count})


def refresh_outstanding_recovery(licensee):
    total = 0
    for engagement in engagements_of_licensee(licensee["id"]):
        if engagement["status"] in ("FINDINGS_ISSUED", "DISPUTED", "SETTLED"):
            total += engagement["recovery_assessed_cents"]
    apply_changes(licensee, {"outstanding_recovery_cents": total})


# --------------------------------------------------------------------------- #
# agreement aggregates                                                        #
# --------------------------------------------------------------------------- #

def compute_approved_sku_count(agreement):
    return len([s for s in submissions_of(agreement["id"]) if s["status"] == "APPROVED"])


def compute_authorized_channel_count(agreement):
    own_classes = {s["sku_class"] for s in submissions_of(agreement["id"])
                   if s["status"] == "APPROVED"}
    channels = set()
    for auth in authorizations_of(agreement["licensee_id"]):
        if auth["status"] != "AUTHORIZED":
            continue
        if any(sku in own_classes for sku in auth["sku_classes"]):
            channels.add(auth["channel_class"])
    return len(channels)


def compute_distribution_ready(agreement, approved_sku_count, authorized_channel_count):
    return bool(agreement["central_licensing_flag"]
                and agreement["contract_status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
                and approved_sku_count > 0
                and authorized_channel_count > 0)


def refresh_agreement_aggregates(agreement):
    approved = compute_approved_sku_count(agreement)
    channels = compute_authorized_channel_count(agreement)
    ready = compute_distribution_ready(agreement, approved, channels)
    return apply_changes(agreement, {
        "approved_sku_count": approved,
        "authorized_channel_count": channels,
        "distribution_ready": ready,
    })


def refresh_distribution_ready(agreement):
    approved = compute_approved_sku_count(agreement)
    channels = compute_authorized_channel_count(agreement)
    ready = compute_distribution_ready(agreement, approved, channels)
    return apply_changes(agreement, {
        "approved_sku_count": approved,
        "authorized_channel_count": channels,
        "distribution_ready": ready,
    })


def refresh_portfolio_aggregates(licensee_id):
    for agreement in agreements_of(licensee_id):
        refresh_agreement_aggregates(agreement)


# --------------------------------------------------------------------------- #
# compliance risk index                                                       #
# --------------------------------------------------------------------------- #

def risk_factors(licensee_id):
    """Return a list of (weight, quarter) contributing rows, undated filtering."""
    rows = []
    agreement_ids = {a["id"] for a in agreements_of(licensee_id)}
    submission_ids = set()
    for sub in S.submissions.values():
        if sub["agreement_id"] in agreement_ids:
            submission_ids.add(sub["id"])
            if sub["status"] == "REJECTED" and sub.get("rejection_reason") != "AGREEMENT_EXPIRED":
                rows.append((WEIGHT_SUBMISSION_REJECTED, db.quarter_of_iso(sub["updated_at"])))

    for review in S.sample_reviews.values():
        if review["submission_id"] in submission_ids and review["verdict"] == "FAIL":
            rows.append((WEIGHT_SAMPLE_FAIL, review["occurrence_quarter"]))

    for report in S.reports.values():
        if report["agreement_id"] in agreement_ids and report["return_count"] > 0:
            for _ in range(report["return_count"]):
                rows.append((WEIGHT_REPORT_RETURN, report["period_quarter"]))

    for engagement in S.engagements.values():
        if engagement["agreement_id"] not in agreement_ids:
            continue
        if engagement["status"] not in ("FINDINGS_ISSUED", "DISPUTED", "SETTLED", "CLOSED"):
            continue
        if engagement["underreported_royalty_cents"] > 0 and engagement["findings_quarter"]:
            rows.append((WEIGHT_AUDIT_UNDERREPORT, engagement["findings_quarter"]))

    for action in S.enforcements.values():
        if action["suspected_licensee_id"] != licensee_id:
            continue
        if action["status"] in ("SEIZURE_ORDERED", "RESOLVED") and action["occurrence_quarter"]:
            rows.append((WEIGHT_ENFORCEMENT_SEIZURE, action["occurrence_quarter"]))

    return rows


def decay_factor(variant, elapsed):
    if variant == "STRICT_ASSESSMENT":
        return Fraction(1)
    steps = elapsed if elapsed < 4 else 4
    return Fraction(1, 2 ** steps)


def compute_risk_index(licensee_id, as_of_quarter, variant):
    raw = Fraction(0)
    factor_count = 0
    for weight, quarter in risk_factors(licensee_id):
        elapsed = db.elapsed_quarters(quarter, as_of_quarter)
        if elapsed < 0 or elapsed > WINDOW_QUARTERS - 1:
            continue
        factor_count += 1
        raw += weight * decay_factor(variant, elapsed)
    index = calc.round_half_up_frac(raw)
    if index > INDEX_CEILING:
        index = INDEX_CEILING
    raw_milli = calc.floor_frac(raw * 1000)
    return {
        "index": index,
        "factor_count": factor_count,
        "raw_weighted_total_milli": raw_milli,
        "posture_band": posture_band(index),
    }


def posture_band(index):
    if index >= 60:
        return "FROZEN"
    if index >= 35:
        return "PROBATION"
    if index >= 15:
        return "WATCH"
    return "CLEAR"


def refresh_risk_index(licensee, as_of_quarter=None):
    quarter = as_of_quarter or db.current_quarter()
    result = compute_risk_index(licensee["id"], quarter, "ROLLING_MONITOR")
    apply_changes(licensee, {
        "compliance_risk_index": result["index"],
        "risk_index_as_of_quarter": quarter,
    })
    return result


# --------------------------------------------------------------------------- #
# posture recompute                                                           #
# --------------------------------------------------------------------------- #

def posture_recompute(agreement, as_of_quarter):
    """Move compliance_posture to the band implied by the licensee's index.

    Returns (changed, submissions_held, submissions_released).
    """
    if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
        return False, 0, 0
    licensee = licensee_of(agreement)
    band = posture_band(licensee["compliance_risk_index"])
    current = agreement["compliance_posture"]
    if band == current:
        return False, 0, 0

    agreement["compliance_posture"] = band
    agreement["posture_as_of_quarter"] = as_of_quarter
    touch(agreement)

    held = 0
    released = 0
    if band in ("PROBATION", "FROZEN"):
        for sub in submissions_of(agreement["id"]):
            if sub["status"] in HELD_SUBMISSION_STATES and not sub["review_hold"]:
                sub["review_hold"] = True
                touch(sub)
                held += 1
    elif current in ("PROBATION", "FROZEN"):
        for sub in submissions_of(agreement["id"]):
            if sub["review_hold"]:
                sub["review_hold"] = False
                touch(sub)
                released += 1
    return True, held, released


def posture_cascade(licensee_id, as_of_quarter):
    changed = held = released = 0
    for agreement in agreements_of(licensee_id):
        moved, h, r = posture_recompute(agreement, as_of_quarter)
        if moved:
            changed += 1
        held += h
        released += r
    return changed, held, released


# --------------------------------------------------------------------------- #
# submission revocation cascade                                               #
# --------------------------------------------------------------------------- #

def revoke_submission(submission, reason):
    submission["status"] = "REVOKED"
    submission["revocation_reason"] = reason
    touch(submission)
    agreement = S.agreements[submission["agreement_id"]]
    refresh_agreement_aggregates(agreement)
    suspend_authorizations_without_skus(agreement["licensee_id"])


def suspend_authorizations_without_skus(licensee_id):
    live_classes = approved_sku_classes(licensee_id)
    suspended_any = False
    for auth in authorizations_of(licensee_id):
        if auth["status"] != "AUTHORIZED":
            continue
        if any(sku in live_classes for sku in auth["sku_classes"]):
            continue
        auth["status"] = "SUSPENDED"
        auth["suspension_reason"] = "NO_APPROVED_SKUS"
        auth["suspended_at"] = db.now_iso()
        touch(auth)
        suspended_any = True
    if suspended_any:
        refresh_portfolio_aggregates(licensee_id)


# --------------------------------------------------------------------------- #
# mark withdrawal cascade                                                     #
# --------------------------------------------------------------------------- #

def snapshot_contains_mark(submission, mark_id):
    return any(entry.get("mark_id") == mark_id
               for entry in submission.get("approved_mark_snapshot") or [])


def withdraw_mark(mark, reason):
    mark["status"] = "WITHDRAWN"
    mark["status_reason"] = reason
    mark["withdrawn_at"] = db.now_iso()
    touch(mark)
    for sub in list(S.submissions.values()):
        if sub["status"] == "APPROVED" and snapshot_contains_mark(sub, mark["id"]):
            revoke_submission(sub, "MARK_WITHDRAWN")


def restrict_mark(mark, reason):
    mark["status"] = "RESTRICTED"
    mark["status_reason"] = reason
    touch(mark)
    for sub in list(S.submissions.values()):
        if sub["status"] == "APPROVED" and snapshot_contains_mark(sub, mark["id"]):
            if not sub["mark_snapshot_stale"]:
                sub["mark_snapshot_stale"] = True
                touch(sub)


# --------------------------------------------------------------------------- #
# minimum guarantee shortfalls                                                #
# --------------------------------------------------------------------------- #

def assess_interim_shortfall(agreement, as_of_quarter):
    start_q = db.quarter_of_iso(agreement["term_start_date"])
    end_q = db.quarter_of_iso(agreement["term_end_date"])
    total, elapsed = calc.term_quarter_counts(
        start_q, end_q, as_of_quarter, db.elapsed_quarters)
    value = calc.interim_shortfall(agreement["minimum_guarantee_cents"],
                                   agreement["cumulative_royalty_cents"],
                                   total, elapsed)
    return apply_changes(agreement, {"mg_accrued_shortfall_cents": value})


def assess_final_shortfall(agreement):
    return calc.final_shortfall(agreement["minimum_guarantee_cents"],
                                agreement["cumulative_royalty_cents"])
