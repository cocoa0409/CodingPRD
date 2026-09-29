"""Cascades, derived-figure recomputation and the clock-driven sweep.

PRD 2.10: every record a write affects gets exactly one updated_at refresh and
one version increment per request, and every derived figure on it is brought
back into agreement before the response is emitted.
"""
from datetime import timedelta

import calc
from store import db
from util import fmt_date, parse_date


def _touched():
    from flask import g
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def bump(rec):
    """One version increment per affected record per request."""
    if rec is None:
        return rec
    try:
        seen = _touched()
    except RuntimeError:
        seen = set()
    if rec["id"] in seen:
        return rec
    seen.add(rec["id"])
    return db.touch(rec)


# =============================================================================
# Merchant posture cascades (PRD 3.2, 3.10, 3.11)
# =============================================================================
def cascade_suspend(merchant):
    for enrollment in db.ordered(db.enrollments):
        if enrollment["merchant_id"] == merchant["id"] and enrollment["status"] == "ACTIVE":
            enrollment["status"] = "SUSPENDED"
            bump(enrollment)
    for draw in db.ordered(db.draws):
        if draw["merchant_id"] == merchant["id"] and draw["status"] == "REQUESTED":
            deny_draw(draw, "MERCHANT_SUSPENDED")


def cascade_reinstate(merchant):
    for enrollment in db.ordered(db.enrollments):
        if (enrollment["merchant_id"] == merchant["id"]
                and enrollment["status"] == "SUSPENDED"):
            enrollment["status"] = "ACTIVE"
            bump(enrollment)


def cascade_terminate(merchant):
    for enrollment in db.ordered(db.enrollments):
        if (enrollment["merchant_id"] == merchant["id"]
                and enrollment["status"] in ("ACTIVE", "SUSPENDED")):
            enrollment["status"] = "TERMINATED"
            bump(enrollment)
    for draw in db.ordered(db.draws):
        if draw["merchant_id"] == merchant["id"] and draw["status"] == "REQUESTED":
            deny_draw(draw, "MERCHANT_TERMINATED")
    for app in db.ordered(db.applications):
        if (app["merchant_id"] == merchant["id"]
                and app["decision"] in ("PENDING", "APPROVED", "COUNTER_OFFERED")):
            app["decision"] = "REVOKED"
            app["decision_reason_codes"] = list(app["decision_reason_codes"]) + [
                "MERCHANT_TERMINATED"]
            bump(app)


def suspend_merchant(merchant, reason_code):
    """APPROVED -> SUSPENDED plus the two-way cascade of PRD 3.2."""
    merchant["enrollment_status"] = "SUSPENDED"
    merchant["suspension_reason_code"] = reason_code
    bump(merchant)
    cascade_suspend(merchant)


def deny_draw(draw, reason_code):
    """REQUESTED -> DENIED: no money moves; headroom is released."""
    draw["status"] = "DENIED"
    draw["denial_reason_code"] = reason_code
    bump(draw)
    milestone = db.milestones.get(draw["project_milestone_id"])
    if milestone is not None:
        bump(milestone)
        project = calc.project_for_milestone(milestone)
        if project is not None:
            bump(project)


# =============================================================================
# Consumer-debt driven offer revocation (PRD 3.5)
# =============================================================================
def revoke_offers_on_dti(consumer_id):
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        return
    debt = calc.existing_program_debt_cents(consumer_id)
    for app in db.ordered(db.applications):
        if app["consumer_id"] != consumer_id:
            continue
        if app["decision"] not in ("APPROVED", "COUNTER_OFFERED"):
            continue
        ratio = calc.dti_bps(debt, app["project_amount_cents"],
                            consumer["annual_income_cents"])
        if ratio > calc.DTI_CEILING_BPS:
            app["decision"] = "REVOKED"
            app["decision_reason_codes"] = list(app["decision_reason_codes"]) + [
                "REVOKED_DTI_BREACH"]
            bump(app)


# =============================================================================
# The SYSTEM phantom-project detector (PRD 3.11)
# =============================================================================
def run_pre_completion_detector(project, rule):
    if project["completion_status"] == "CERTIFIED_COMPLETE":
        return None
    settled = calc.settled_funded_cents(project)
    if (settled * calc.BPS
            < rule["max_precompletion_release_bps"] * project["contract_amount_cents"]):
        return None
    for alert in db.ordered(db.alerts):
        if (alert["status"] == "OPEN" and alert["source"] == "SYSTEM"
                and alert["alert_type"] == "PRE_COMPLETION_FULL_DRAW"
                and alert.get("_project_id") == project["id"]):
            return None
    alert = db.new_record()
    alert.update({
        "merchant_id": project["merchant_id"],
        "alert_type": "PRE_COMPLETION_FULL_DRAW",
        "severity_weight": calc.SYSTEM_ALERT_SEVERITY_WEIGHT,
        "source": "SYSTEM",
        "status": "OPEN",
        "evidence_ref": None,
        "opened_on": fmt_date(db.today()),
        "investigated_by_user_id": None,
        "investigation_note": None,
        "_project_id": project["id"],
    })
    db.alerts[alert["id"]] = alert
    return alert


# =============================================================================
# Loan-status helpers shared by payments and the sweep (PRD 3.9)
# =============================================================================
def capitalize_account(acct):
    """PROMO_ACTIVE -> PROMO_EXPIRED_CAPITALIZED, then the two caused hops."""
    plan = db.promotion_plans.get(acct["promotion_plan_id"])
    acct["capitalized_interest_cents"] = calc.capitalization_amount_cents(acct)
    acct["promo_status"] = "PROMO_EXPIRED_CAPITALIZED"
    if plan is not None:
        acct["apr_bps"] = plan["post_promo_apr_bps"]
    bump(acct)
    consumer = db.consumers.get(acct["consumer_id"])
    if consumer is not None:
        bump(consumer)
    revoke_offers_on_dti(acct["consumer_id"])


# =============================================================================
# The ops-run expiration sweep (PRD 3.9)
# =============================================================================
def run_expiration_sweep():
    counts = {
        "expired_licenses": 0,
        "expired_offers": 0,
        "expired_disclosures": 0,
        "capitalized_loans": 0,
        "delinquent_loans": 0,
        "charged_off_loans": 0,
        "escalated_disputes": 0,
    }
    now = db.now()
    today = db.today()

    for lic in db.ordered(db.licenses):
        if lic["verification_status"] == "VERIFIED" and today >= parse_date(lic["expires_on"]):
            lic["verification_status"] = "EXPIRED"
            bump(lic)
            counts["expired_licenses"] += 1

    for app in db.ordered(db.applications):
        if (app["decision"] in ("APPROVED", "COUNTER_OFFERED")
                and app["offer_expires_at"] is not None
                and now > app["offer_expires_at"]):
            app["decision"] = "EXPIRED"
            app["decision_reason_codes"] = list(app["decision_reason_codes"]) + [
                "OFFER_LAPSED"]
            bump(app)
            counts["expired_offers"] += 1

    for app in db.ordered(db.applications):
        delivered = app["disclosure_delivered_at"]
        if (app["disclosure_status"] == "DELIVERED" and delivered is not None
                and now > delivered + timedelta(days=calc.DISCLOSURE_ACK_DAYS)):
            app["disclosure_status"] = "EXPIRED_UNACKNOWLEDGED"
            bump(app)
            counts["expired_disclosures"] += 1

    for acct in db.ordered(db.loan_accounts):
        if acct["promo_status"] != "PROMO_ACTIVE":
            continue
        if not acct["promo_expires_on"]:
            continue
        if parse_date(acct["promo_expires_on"]) >= today:
            continue
        if calc.principal_balance_cents(acct) <= 0:
            continue
        capitalize_account(acct)
        counts["capitalized_loans"] += 1

    for acct in db.ordered(db.loan_accounts):
        if acct["balance_status"] != "CURRENT" or not acct["promo_expires_on"]:
            continue
        expires = parse_date(acct["promo_expires_on"])
        if (today - expires).days <= calc.DELINQUENCY_GRACE_DAYS:
            continue
        owed = calc.principal_balance_cents(acct) + acct["capitalized_interest_cents"]
        if owed <= 0:
            continue
        acct["balance_status"] = "DELINQUENT"
        bump(acct)
        merchant = db.merchants.get(acct["merchant_id"])
        if merchant is not None:
            bump(merchant)
        counts["delinquent_loans"] += 1

    for acct in db.ordered(db.loan_accounts):
        if acct["balance_status"] != "DELINQUENT" or not acct["promo_expires_on"]:
            continue
        expires = parse_date(acct["promo_expires_on"])
        if (today - expires).days <= calc.CHARGE_OFF_DAYS:
            continue
        acct["balance_status"] = "CHARGED_OFF"
        bump(acct)
        consumer = db.consumers.get(acct["consumer_id"])
        if consumer is not None:
            bump(consumer)
        merchant = db.merchants.get(acct["merchant_id"])
        if merchant is not None:
            bump(merchant)
        counts["charged_off_loans"] += 1

    for case in db.ordered(db.disputes):
        if (case["status"] == "MERCHANT_RESPONSE_PENDING"
                and case["merchant_responded_at"] is None
                and case["response_due_at"] is not None
                and now >= case["response_due_at"]):
            case["status"] = "ESCALATED_NO_RESPONSE"
            bump(case)
            counts["escalated_disputes"] += 1

    return counts
