"""Donation state transitions and cascades."""

import db
from common import clock_now_iso, bump


def apply_post(donation):
    """Apply the POSTED-side effects atomically.
    Assumes donation is in PENDING or (for CASH/CHECK) is being newly POSTED."""
    donation["status"] = "POSTED"
    donation["posted_at"] = clock_now_iso()
    # NOTE: caller is responsible for bumping the donation itself.

    pledge_id = donation.get("pledge_id")
    if pledge_id:
        pledge = db.pledges[pledge_id]
        pledge["received_amount_cents"] = pledge.get("received_amount_cents", 0) + donation["amount_cents"]
        pledge["remaining_amount_cents"] = max(0, pledge["pledged_amount_cents"] - pledge["received_amount_cents"])
        # Auto-transition ACTIVE -> FULFILLED when threshold reached.
        campaign = db.pledge_campaigns.get(pledge["campaign_id"])
        if pledge["status"] == "ACTIVE" and pledge["received_amount_cents"] >= pledge["pledged_amount_cents"]:
            pledge["status"] = "FULFILLED"
            if campaign is not None:
                campaign["fulfilled_pledge_count"] = campaign.get("fulfilled_pledge_count", 0) + 1
                bump(campaign)
        bump(pledge)

    campaign_id = donation.get("campaign_id")
    if campaign_id:
        campaign = db.pledge_campaigns[campaign_id]
        campaign["received_total_cents"] = campaign.get("received_total_cents", 0) + donation["amount_cents"]
        # Only bump campaign here if we haven't already bumped it in the pledge branch.
        # But both branches touch campaign; still per §2.4 every mutation bumps once — so bump again.
        # Actually: if pledge branch already bumped and there's no distinct campaign change here, we still
        # have a distinct state change (received_total_cents), so a version bump is warranted.
        bump(campaign)


def apply_refund(donation):
    """Apply the REFUNDED-side cascade (Links 1/2/3 per PRD §3.3)."""
    donation["status"] = "REFUNDED"
    donation["refunded_at"] = clock_now_iso()

    pledge_id = donation.get("pledge_id")
    if pledge_id:
        pledge = db.pledges[pledge_id]
        was_fulfilled = pledge["status"] == "FULFILLED"
        pledge["received_amount_cents"] = pledge.get("received_amount_cents", 0) - donation["amount_cents"]
        pledge["remaining_amount_cents"] = max(0, pledge["pledged_amount_cents"] - pledge["received_amount_cents"])
        # Link 2: FULFILLED -> ACTIVE if now under threshold.
        campaign = db.pledge_campaigns.get(pledge["campaign_id"])
        if was_fulfilled and pledge["received_amount_cents"] < pledge["pledged_amount_cents"]:
            pledge["status"] = "ACTIVE"
            # Link 3: decrement campaign fulfilled_pledge_count.
            if campaign is not None:
                campaign["fulfilled_pledge_count"] = campaign.get("fulfilled_pledge_count", 0) - 1
                bump(campaign)
        bump(pledge)

    campaign_id = donation.get("campaign_id")
    if campaign_id:
        campaign = db.pledge_campaigns[campaign_id]
        campaign["received_total_cents"] = campaign.get("received_total_cents", 0) - donation["amount_cents"]
        bump(campaign)


def apply_fail(donation):
    donation["status"] = "FAILED"
