"""Cascading state transitions for Advertiser → Campaign → AdGroup → Creative.

This module owns the helper functions that pause / archive / end resources and
their dependents while taking care of timestamp + version bumps.
"""
from typing import Iterable

from .. import store
from ..audit import emit as audit_emit
from ..clock import now_iso


def _campaigns_for(advertiser_id: str) -> list[dict]:
    return [c for c in store.list_all("Campaign") if c.get("advertiser_id") == advertiser_id]


def _ad_groups_for(campaign_id: str) -> list[dict]:
    return [a for a in store.list_all("AdGroup") if a.get("campaign_id") == campaign_id]


def _creatives_for(ad_group_id: str) -> list[dict]:
    return [c for c in store.list_all("Creative") if c.get("ad_group_id") == ad_group_id]


def archive_creative_cascade(creative: dict):
    if creative.get("review_status") == "ARCHIVED":
        return
    was_approved = creative.get("review_status") == "APPROVED"
    creative["review_status"] = "ARCHIVED"
    creative["archived_at"] = now_iso()
    store.touch(creative)
    if was_approved:
        ag = store.get("AdGroup", creative["ad_group_id"])
        if ag:
            ag["approved_creative_count"] = max(0, int(ag.get("approved_creative_count", 0)) - 1)
            store.touch(ag)
            reevaluate_ad_group_status(ag)


def reevaluate_ad_group_status(ag: dict):
    """Bump DRAFT→READY when first approved arrives, and READY/RUNNING→DISAPPROVED if all approvals gone."""
    status = ag.get("status")
    approved = int(ag.get("approved_creative_count", 0))
    if status == "DRAFT" and approved >= 1:
        ag["status"] = "READY"
        store.touch(ag)
    elif status in ("READY", "RUNNING") and approved == 0:
        ag["status"] = "DISAPPROVED"
        store.touch(ag)
    elif status == "DISAPPROVED" and approved >= 1:
        ag["status"] = "READY"
        store.touch(ag)


def archive_ad_group_cascade(ag: dict):
    if ag.get("status") == "ARCHIVED":
        return
    ag["status"] = "ARCHIVED"
    store.touch(ag)
    for c in _creatives_for(ag["id"]):
        archive_creative_cascade(c)


def pause_ad_group_cascade(ag: dict):
    if ag.get("status") in ("PAUSED", "ARCHIVED"):
        return
    if ag.get("status") == "RUNNING":
        ag["status"] = "PAUSED"
        store.touch(ag)


def end_campaign_cascade(camp: dict):
    if camp.get("status") == "ENDED":
        return
    camp["status"] = "ENDED"
    store.touch(camp)
    for ag in _ad_groups_for(camp["id"]):
        archive_ad_group_cascade(ag)


def pause_campaign_cascade(camp: dict, *, cascade: bool = True):
    if camp.get("status") in ("PAUSED", "ENDED"):
        return
    if camp.get("status") in ("ACTIVE", "BUDGET_EXHAUSTED"):
        camp["status"] = "PAUSED"
        store.touch(camp)
    if cascade:
        for ag in _ad_groups_for(camp["id"]):
            if ag.get("status") == "RUNNING":
                pause_ad_group_cascade(ag)


def suspend_advertiser_cascade(adv: dict):
    """SUSPEND: depth-2 cascade — RUNNING campaigns → PAUSED; RUNNING ad-groups → PAUSED."""
    prev_status = adv.get("status")
    adv["status"] = "SUSPENDED"
    store.touch(adv)
    for camp in _campaigns_for(adv["id"]):
        if camp.get("status") in ("ACTIVE", "BUDGET_EXHAUSTED"):
            pause_campaign_cascade(camp, cascade=True)
    audit_emit(
        "ACCOUNT_STATUS_CHANGE",
        "Advertiser",
        adv["id"],
        before_value={"status": prev_status},
        after_value={"status": "SUSPENDED"},
    )


def close_advertiser_cascade(adv: dict):
    """CLOSE: depth-3 cascade — all Campaigns ENDED, AdGroups ARCHIVED, Creatives ARCHIVED."""
    prev_status = adv.get("status")
    adv["status"] = "CLOSED"
    store.touch(adv)
    for camp in _campaigns_for(adv["id"]):
        end_campaign_cascade(camp)
    audit_emit(
        "ACCOUNT_STATUS_CHANGE",
        "Advertiser",
        adv["id"],
        before_value={"status": prev_status},
        after_value={"status": "CLOSED"},
    )


def reinstate_advertiser(adv: dict):
    prev_status = adv.get("status")
    adv["status"] = "ACTIVE"
    store.touch(adv)
    audit_emit(
        "ACCOUNT_STATUS_CHANGE",
        "Advertiser",
        adv["id"],
        before_value={"status": prev_status},
        after_value={"status": "ACTIVE"},
    )
