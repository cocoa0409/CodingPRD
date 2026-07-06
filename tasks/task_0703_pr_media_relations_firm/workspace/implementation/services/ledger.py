"""Conserved-balance reconciliation (PRD 2.9).

These re-derive each conserved quantity from the current set of contributing
children rather than accumulating ad-hoc deltas, so balances never drift.

  - Campaign.earned_media_value_cents = sum VERIFIED coverage media_value_cents
  - Campaign.cost_basis_cents         = sum APPROVED time-entry cost_cents
  - Campaign.roi_ratio                = campaign_roi (pinned order)
  - Client.lifetime_earned_media_cents= sum earned across the client's campaigns
  - RetainerPeriod.hours_consumed     = sum non-void billable_hours
  - RetainerPeriod.provisional_total_cents = provisional billing
"""
import db
from services import calculations as calc


def recompute_campaign_ledger(campaign):
    """Re-derive earned / cost / roi for one campaign (pinned order, PRD 3.10)."""
    earned = calc.campaign_earned_cents(campaign)
    cost = calc.campaign_cost_basis_cents(campaign)
    campaign["earned_media_value_cents"] = earned
    campaign["cost_basis_cents"] = cost
    campaign["roi_ratio"] = calc.campaign_roi_ratio(earned, cost)


def recompute_client_lifetime(client):
    """Re-derive client lifetime earned media from all of its campaigns' earned."""
    total = 0
    for camp in db.campaigns.values():
        if camp["client_id"] == client["id"]:
            total += calc.campaign_earned_cents(camp)
    client["lifetime_earned_media_cents"] = total


def recompute_period(period):
    """Re-derive period hours_consumed and provisional_total_cents."""
    period["hours_consumed"] = calc.hours_consumed(period)
    period["provisional_total_cents"] = calc.provisional_total_cents(period)
