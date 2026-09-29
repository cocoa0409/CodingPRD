"""Tender acceptance metrics and the at-risk cascade — PRD §3.9."""
from decimal import Decimal

import store
from numeric import D, q2
from services import lanes as lane_svc

AT_RISK_MIN_SAMPLE = 5
AT_RISK_REJECTION_PCT = Decimal("20.00")
SYSTEM_MINI_BID_WINDOW_DAYS = 10
REJECTING_OUTCOMES = ("REJECTED", "TIMEOUT")


def record_tenders(record_id):
    rows = [t for t in store.tender_events.values() if t["rate_record_id"] == record_id]
    return sorted(rows, key=lambda t: (t["tendered_at"], t["created_at"], t["_seq"]))


def recompute_metrics(record):
    """tender_count counts every outcome; rejection_count counts REJECTED and TIMEOUT —
    a tender the carrier let time out counts against it exactly as a refusal does."""
    tenders = record_tenders(record["id"])
    record["tender_count"] = len(tenders)
    record["rejection_count"] = sum(1 for t in tenders
                                    if t["outcome"] in REJECTING_OUTCOMES)
    if record["tender_count"] == 0:
        record["rejection_pct"] = Decimal("0.00")
    else:
        record["rejection_pct"] = q2(D(record["rejection_count"]) * Decimal("100.00")
                                     / D(record["tender_count"]))
    record["acceptance_pct"] = q2(Decimal("100.00") - D(record["rejection_pct"]))


def is_at_risk(record):
    """Both gates matter, and the comparison reads the rounded percentage."""
    return (int(record["tender_count"]) >= AT_RISK_MIN_SAMPLE
            and D(record["rejection_pct"]) >= AT_RISK_REJECTION_PCT)


def apply_risk_determination(record):
    """Fires the three-link risk cascade when the determination turns positive, and
    unwinds it symmetrically when it turns negative."""
    if is_at_risk(record) and record["status"] == "LIVE":
        _enter_risk(record)
    elif (not is_at_risk(record) and record["status"] == "AT_RISK"
            and int(record["tender_count"]) >= AT_RISK_MIN_SAMPLE):
        _leave_risk(record)


def _enter_risk(record):
    record["status"] = "AT_RISK"

    allocation = store.allocations.get(record["award_allocation_id"])
    lane = store.lanes.get(record["lane_id"])
    if (allocation is not None and allocation["status"] == "ACTIVE"
            and allocation["routing_position"] == "PRIMARY"):
        allocation["status"] = "SUSPENDED_ROUTING"
        store.touch(allocation)
    if lane is not None and lane["status"] == "AWARDED":
        lane["status"] = "UNDER_REBID"
        store.touch(lane)

    if lane is not None:
        mini_bid = store.new_row(
            bid_event_id=lane["bid_event_id"],
            lane_id=lane["id"],
            rate_record_id=record["id"],
            applied_rate_record_id=None,
            proposed_by_carrier_id=None,
            trigger_reason="TENDER_REJECTION_RATE",
            origin="SYSTEM",
            status="REQUESTED",
            window_open_at=store.now_iso(),
            window_close_at=store.fmt(store.now()
                                      + store.days(SYSTEM_MINI_BID_WINDOW_DAYS)),
            proposed_rate_per_mile=None,
            adjustment_pct=None,
            contract_value_before_usd=None,
            contract_value_after_usd=None,
            denial_reason=None,
            revert_reason=None,
            applied_at=None,
            reverted_at=None,
        )
        store.mini_bids[mini_bid["id"]] = mini_bid


def _leave_risk(record):
    record["status"] = "LIVE"

    allocation = store.allocations.get(record["award_allocation_id"])
    if allocation is not None and allocation["status"] == "SUSPENDED_ROUTING":
        allocation["status"] = "ACTIVE"
        store.touch(allocation)

    lane = store.lanes.get(record["lane_id"])
    if lane is None or lane["status"] != "UNDER_REBID":
        return
    for other in store.rate_records.values():
        if other["id"] == record["id"]:
            continue
        if other["lane_id"] == lane["id"] and other["status"] == "AT_RISK":
            return
    lane["status"] = "AWARDED"
    lane_svc.recompute_awarded_coverage(lane)
    store.touch(lane)
