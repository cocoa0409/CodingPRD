"""Synchronous cascades: suspension, restoration and escalation bookkeeping.

Every row a cascade touches gets its updated_at refreshed and its version
incremented once for the request (PRD 2.9).
"""

from db import db, clock_stamp, new_row, rows, touch

SEVERE = ("HIGH", "CRITICAL")
UNRESOLVED = ("OPEN", "ACKNOWLEDGED", "DELIVERY_HELD")
OPEN_DELIVERABLE_STATES = ("PLANNED", "IN_PROGRESS", "REWORK")


def opportunity_deliverables(opportunity_id):
    return [d for d in rows("deliverables") if d["opportunity_id"] == opportunity_id]


def engagement_for_opportunity(opportunity_id):
    for e in rows("engagements"):
        if e["opportunity_id"] == opportunity_id:
            return e
    return None


def engagement_escalations(engagement_id):
    return [e for e in rows("risk_escalations") if e["engagement_id"] == engagement_id]


def unresolved_severe_count(engagement_id):
    return sum(
        1
        for e in engagement_escalations(engagement_id)
        if e["severity"] in SEVERE and e["status"] in UNRESOLVED
    )


def recount_suspended(engagement):
    engagement["suspended_deliverable_count"] = sum(
        1
        for d in opportunity_deliverables(engagement["opportunity_id"])
        if d["status"] == "SUSPENDED"
    )


def hold_delivery(engagement):
    """ACTIVE -> ON_HOLD plus the deliverable suspension chain."""
    engagement["delivery_state"] = "ON_HOLD"
    for d in opportunity_deliverables(engagement["opportunity_id"]):
        if d["status"] in OPEN_DELIVERABLE_STATES:
            d["prior_status"] = d["status"]
            d["status"] = "SUSPENDED"
            touch(d)
    recount_suspended(engagement)
    touch(engagement)


def release_delivery(engagement):
    """ON_HOLD -> ACTIVE plus restoration of every suspended deliverable."""
    engagement["delivery_state"] = "ACTIVE"
    for d in opportunity_deliverables(engagement["opportunity_id"]):
        if d["status"] == "SUSPENDED":
            d["status"] = d.get("prior_status") or "PLANNED"
            d["prior_status"] = None
            touch(d)
    engagement["suspended_deliverable_count"] = 0
    touch(engagement)


def create_escalation(
    engagement,
    source,
    severity,
    opened_reason,
    source_quality_review_id=None,
    status="OPEN",
):
    row = new_row(
        {
            "engagement_id": engagement["id"],
            "source_quality_review_id": source_quality_review_id,
            "source": source,
            "severity": severity,
            "opened_reason": opened_reason,
            "status": status,
            "leadership_response": None,
            "resolved_at": None,
        }
    )
    db.risk_escalations[row["id"]] = row
    return row


def reconcile_on_raise(engagement, severity):
    """PRD 3.7 / 3.9 hop: flag leadership review and move the client counter."""
    if severity not in SEVERE:
        return
    engagement["leadership_review_required"] = True
    touch(engagement)
    if unresolved_severe_count(engagement["id"]) == 1:
        client = db.clients.get(engagement["client_id"])
        if client is not None:
            client["at_risk_engagement_count"] = client["at_risk_engagement_count"] + 1
            touch(client)


def reconcile_on_resolve(engagement, count_before):
    """Runs after a resolve; count_before is the pre-resolve unresolved-severe count."""
    if count_before == 0:
        # Nothing severe was outstanding, so nothing to reconcile.
        return
    if unresolved_severe_count(engagement["id"]) > 0:
        return
    engagement["leadership_review_required"] = False
    touch(engagement)
    client = db.clients.get(engagement["client_id"])
    if client is not None and client["at_risk_engagement_count"] > 0:
        client["at_risk_engagement_count"] = client["at_risk_engagement_count"] - 1
        touch(client)


def stamp_now():
    return clock_stamp()
