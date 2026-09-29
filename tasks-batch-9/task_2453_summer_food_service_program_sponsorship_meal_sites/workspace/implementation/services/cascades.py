"""Cascades and compensating reversals (PRD sec 2.7, sec 3.1, sec 3.5, sec 3.7).

Every hop mutates the row it touches on its own: each affected child refreshes
its ``updated_at`` and increments its ``version`` by one.
"""

import db
from services import calculations as calc
from services import lookup


# --------------------------------------------------------------------------
# Service-day voiding
# --------------------------------------------------------------------------
def void_day(day, reason):
    counted_total = (
        (day.get("counted_first_meals") or 0)
        + (day.get("counted_second_meals") or 0)
        + (day.get("counted_adult_meals") or 0)
    )
    day["status"] = "VOIDED"
    day["void_reason"] = reason
    day["reimbursable_meals"] = 0
    day["non_reimbursable_meals"] = counted_total
    db.touch(day)


def void_days(site, reason, planned_on_or_after=None, include_open=True):
    """Void the site's days, returning how many were voided.

    ``planned_on_or_after`` restricts the PLANNED sweep to service dates on or
    after that date; when None every PLANNED day is voided regardless of date.
    """
    voided = 0
    for day in lookup.site_days(site["id"]):
        if day["status"] == "PLANNED":
            if planned_on_or_after is not None:
                service_date = db.parse_date(day["service_date"])
                if service_date is None or service_date < planned_on_or_after:
                    continue
            void_day(day, reason)
            voided += 1
        elif day["status"] == "OPEN" and include_open:
            void_day(day, reason)
            voided += 1
    return voided


# --------------------------------------------------------------------------
# Claim-hold propagation
# --------------------------------------------------------------------------
def recompute_blocking_hold_count(claim):
    count = sum(
        1 for line in lookup.claim_line_items(claim["id"]) if line.get("hold_flag")
    )
    db.apply_changes(claim, {"blocking_hold_count": count})


def set_line_item_holds(site, flag):
    """Raise or lower hold_flag on the site's live claim line items."""
    touched_claims = {}
    for line in lookup.site_line_items(site["id"]):
        claim = db.store.claims.get(line["meal_claim_id"])
        if claim is None or claim["status"] not in ("DRAFT", "REVISION_OPENED"):
            continue
        if line.get("hold_flag") != flag:
            line["hold_flag"] = flag
            db.touch(line)
        touched_claims[claim["id"]] = claim
    for claim in touched_claims.values():
        recompute_blocking_hold_count(claim)


# --------------------------------------------------------------------------
# Site-level cascades
# --------------------------------------------------------------------------
def suspend_site(site, reason):
    """The three-part suspension cascade of PRD sec 3.5."""
    voided = void_days(
        site, "SITE_SUSPENDED", planned_on_or_after=db.clock.today(), include_open=True
    )
    site["approval_status"] = "SUSPENDED"
    site["suspension_reason"] = reason
    site["claim_hold"] = True
    site["voided_day_count"] = (site["voided_day_count"] or 0) + voided
    db.touch(site)
    set_line_item_holds(site, True)


def reinstate_site(site):
    """The compensating transition: releases holds, never un-voids days."""
    site["approval_status"] = "APPROVED"
    site["suspension_reason"] = None
    site["claim_hold"] = False
    db.touch(site)
    set_line_item_holds(site, False)


def deny_site_from_suspended(site, reason):
    voided = void_days(site, "SITE_DENIED", planned_on_or_after=None, include_open=True)
    site["approval_status"] = "DENIED"
    site["suspension_reason"] = reason
    site["voided_day_count"] = (site["voided_day_count"] or 0) + voided
    db.touch(site)


def close_season(site):
    voided = void_days(
        site, "SEASON_CLOSED", planned_on_or_after=db.clock.today(), include_open=False
    )
    site["operating_status"] = "CLOSED_FOR_SEASON"
    site["voided_day_count"] = (site["voided_day_count"] or 0) + voided
    db.touch(site)


def terminate_sponsor_cascade(sponsor):
    """PRD sec 3.1: sites denied, then their planned/open days voided."""
    for site in lookup.sponsor_sites(sponsor["id"]):
        if site["approval_status"] not in ("PENDING_REVIEW", "APPROVED", "SUSPENDED"):
            continue
        voided = void_days(
            site, "SITE_DENIED", planned_on_or_after=None, include_open=True
        )
        site["approval_status"] = "DENIED"
        site["suspension_reason"] = "SPONSOR_TERMINATED"
        site["claim_hold"] = True
        site["voided_day_count"] = (site["voided_day_count"] or 0) + voided
        db.touch(site)


def raise_claim_hold(site):
    """Raise claim_hold on its own, propagating to live line items."""
    if not site.get("claim_hold"):
        site["claim_hold"] = True
        db.touch(site)
        set_line_item_holds(site, True)


# --------------------------------------------------------------------------
# Monitoring deadline recomputation
# --------------------------------------------------------------------------
def recompute_visit_deadlines(site):
    for visit in lookup.site_visits(site["id"]):
        if visit["status"] == "CANCELLED":
            continue
        db.apply_changes(visit, {"due_date": calc.visit_due_date(visit, site)})


# --------------------------------------------------------------------------
# Corrective actions
# --------------------------------------------------------------------------
def live_critical_actions(site_id, ignore_id=None):
    return [
        action
        for action in lookup.site_actions(site_id)
        if action["severity"] == "CRITICAL"
        and action["status"] in ("OPEN", "RESPONSE_SUBMITTED", "REJECTED", "ESCALATED")
        and action["id"] != ignore_id
    ]


def create_corrective_action(
    site,
    severity,
    finding_code,
    origin,
    opened_by_user_id,
    monitoring_visit_id=None,
    follow_up_of_corrective_action_id=None,
):
    action = db.new_row(
        {
            "site_id": site["id"],
            "monitoring_visit_id": monitoring_visit_id,
            "follow_up_of_corrective_action_id": follow_up_of_corrective_action_id,
            "origin": origin,
            "finding_code": finding_code,
            "severity": severity,
            "status": "OPEN",
            "due_date": calc.action_due_date(severity),
            "rejection_count": 0,
            "response_note": None,
            "evidence_ref": None,
            "opened_by_user_id": opened_by_user_id,
            "closed_by_user_id": None,
        }
    )
    db.store.actions[action["id"]] = action
    # A CRITICAL action fires the full site suspension cascade on creation.
    if severity == "CRITICAL" and site["approval_status"] == "APPROVED":
        suspend_site(site, "CRITICAL_FINDING:" + str(finding_code))
    return action


def maybe_reinstate_after_closure(site, closed_action):
    """Automatic reinstatement when the last live CRITICAL action closes."""
    if closed_action["severity"] != "CRITICAL":
        return
    if site["approval_status"] != "SUSPENDED":
        return
    if live_critical_actions(site["id"]):
        return
    reinstate_site(site)


def maybe_close_visit(action):
    """A REPORT_FILED visit bubbles to CLOSED once all its actions are closed."""
    visit_id = action.get("monitoring_visit_id")
    if not visit_id:
        return
    visit = db.store.visits.get(visit_id)
    if visit is None or visit["status"] != "REPORT_FILED":
        return
    siblings = lookup.visit_actions(visit_id)
    if not siblings:
        return
    for sibling in siblings:
        if sibling["status"] != "CLOSED":
            return
    visit["status"] = "CLOSED"
    db.touch(visit)
