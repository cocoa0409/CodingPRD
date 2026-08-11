"""Cascading mutations per PRD §2.9 and the state-machine side-effect tables.

Every resource touched by a cascade gets its own updated_at refresh and
version increment, exactly as if the client had written to it directly.
"""

import db
from services.calculations import (
    recompute_engagement,
    recompute_propensity,
    recompute_all_preferences_for,
    rederive_posture,
)
from services.common import touch, logical_ts


def end_membership(membership, reason):
    """ACTIVE/INVITED -> ENDED with reason; adjusts committee_count and posture
    only when the membership was ACTIVE (counted)."""
    committee = db.committees.get(membership["committee_id"])
    was_active = membership["status"] == "ACTIVE"
    membership["status"] = "ENDED"
    membership["ended_reason"] = reason
    touch(membership)
    if committee is not None:
        if membership["role"] == "CHAIR" and committee.get("chair_membership_id") == membership["id"]:
            committee["chair_membership_id"] = None
            touch(committee)
        if was_active:
            event = db.events.get(committee["event_id"])
            if event is not None:
                event["committee_count"] = max(0, event["committee_count"] - 1)
                rederive_posture(event)


def cancel_registration(reg, reason):
    """PENDING_PAYMENT/CONFIRMED -> CANCELLED; decrements sold_count and
    total_revenue_cents when the registration had been CONFIRMED."""
    was_confirmed = reg["payment_status"] == "CONFIRMED"
    reg["payment_status"] = "CANCELLED"
    reg["cancelled_reason"] = reason
    touch(reg)
    if was_confirmed:
        tier = db.ticket_tiers.get(reg["tier_id"])
        if tier is not None:
            tier["sold_count"] = max(0, tier["sold_count"] - 1)
            touch(tier)
        event = db.events.get(reg["event_id"])
        if event is not None:
            event["total_revenue_cents"] -= reg.get("final_price_cents") or 0
            rederive_posture(event)


def lapse_pledge(pledge):
    """PLEDGED -> LAPSED; decrements campaign pledged total and recomputes the
    pledgor's giving_propensity."""
    pledge["status"] = "LAPSED"
    touch(pledge)
    campaign = db.campaigns.get(pledge["campaign_id"])
    if campaign is not None:
        campaign["pledged_total_cents"] -= pledge["amount_cents"]
        touch(campaign)
    recompute_propensity(pledge["alumni_id"])


def mark_alumnus_deceased(record):
    """Full cascade for AlumniRecord -> DECEASED."""
    record["status"] = "DECEASED"
    touch(record)
    alumni_id = record["id"]

    # Committee memberships ACTIVE/INVITED -> ENDED (ALUMNUS_DECEASED)
    for m in list(db.memberships.values()):
        if m["alumni_id"] == alumni_id and m["status"] in ("ACTIVE", "INVITED"):
            end_membership(m, "ALUMNUS_DECEASED")

    # Registrations PENDING_PAYMENT/CONFIRMED -> CANCELLED (ALUMNUS_DECEASED)
    for reg in list(db.registrations.values()):
        if reg["alumni_id"] == alumni_id and reg["payment_status"] in ("PENDING_PAYMENT", "CONFIRMED"):
            cancel_registration(reg, "ALUMNUS_DECEASED")

    # Pledges PLEDGED -> LAPSED
    for p in list(db.pledges.values()):
        if p["alumni_id"] == alumni_id and p["status"] == "PLEDGED":
            lapse_pledge(p)

    # Preferences suppressed with DO_NOT_CONTACT_RECORD
    recompute_all_preferences_for(alumni_id)


def cancel_event(event):
    """ReunionEvent -> CANCELLED with scope-dependent cascade."""
    previous_status = event["status"]
    event["status"] = "CANCELLED"
    touch(event)

    if previous_status == "OPEN_FOR_REGISTRATION":
        # Cancel outstanding registrations
        for reg in list(db.registrations.values()):
            if reg["event_id"] == event["id"] and reg["payment_status"] in ("PENDING_PAYMENT", "CONFIRMED"):
                cancel_registration(reg, "EVENT_CANCELLED")

        # Abandon linked ACTIVE campaign and lapse its pledges
        for campaign in list(db.campaigns.values()):
            if campaign["event_id"] == event["id"] and campaign["status"] == "ACTIVE":
                campaign["status"] = "ABANDONED"
                touch(campaign)
                for p in list(db.pledges.values()):
                    if p["campaign_id"] == campaign["id"] and p["status"] == "PLEDGED":
                        lapse_pledge(p)

        # Publications in DRAFT/IN_REVIEW/APPROVED are deliberately untouched.

    # End memberships (all three cancellable from-states do this)
    for m in list(db.memberships.values()):
        committee = db.committees.get(m["committee_id"])
        if committee is not None and committee["event_id"] == event["id"] \
                and m["status"] in ("ACTIVE", "INVITED"):
            end_membership(m, "EVENT_CANCELLED")

    rederive_posture(event)


def reunite_alumnus(record):
    """LOST -> ACTIVE on research-case reunite."""
    record["status"] = "ACTIVE"
    record["lost_since"] = None
    touch(record)
    recompute_engagement(record["id"])
    recompute_all_preferences_for(record["id"])


