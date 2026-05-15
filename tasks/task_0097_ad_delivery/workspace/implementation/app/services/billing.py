"""Billing-event ingest, finalization and reversal."""
from .. import store
from ..audit import emit as audit_emit
from ..clock import now_iso, start_of_utc_day
from ..errors import ApiError
from .lifecycle import pause_ad_group_cascade
from .wallet import recompute_balance, recompute_balance_state


STRATEGY_TO_EVENT = {
    "CPC": "CLICK",
    "CPM": "IMPRESSION",
    "CPA": "CONVERSION",
}


def _existing_dup(event_type: str, auction_event_id: str, dedup_key: str) -> dict | None:
    for be in store.list_all("BillingEvent"):
        if (
            be.get("event_type") == event_type
            and be.get("auction_event_id") == auction_event_id
            and be.get("dedup_key") == dedup_key
        ):
            return be
    return None


def _compute_today_spent(camp: dict) -> int:
    day_start_iso = start_of_utc_day().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    total = 0
    for be in store.list_all("BillingEvent"):
        if be.get("campaign_id") != camp["id"]:
            continue
        if be.get("status") != "FINALIZED":
            continue
        fa = be.get("finalized_at") or ""
        if fa >= day_start_iso:
            total += int(be.get("cost_cents", 0))
    return total


def _compute_lifetime_spent(camp: dict) -> int:
    total = 0
    for be in store.list_all("BillingEvent"):
        if be.get("campaign_id") != camp["id"]:
            continue
        if be.get("status") != "FINALIZED":
            continue
        total += int(be.get("cost_cents", 0))
    return total


def reaggregate_campaign(camp: dict):
    camp["lifetime_spent_cents"] = _compute_lifetime_spent(camp)
    camp["today_spent_cents"] = _compute_today_spent(camp)
    store.touch(camp)
    _evaluate_budget(camp)


def _evaluate_budget(camp: dict):
    """Trigger BUDGET_EXHAUSTED transitions or return from exhausted on under-budget."""
    daily = int(camp.get("daily_budget_cents", 0))
    lifetime = camp.get("lifetime_budget_cents")
    today = int(camp.get("today_spent_cents", 0))
    lt = int(camp.get("lifetime_spent_cents", 0))

    exhausted = (today >= daily) or (lifetime is not None and lt >= int(lifetime))

    status = camp.get("status")
    if exhausted and status in ("ACTIVE", "PAUSED"):
        camp["status"] = "BUDGET_EXHAUSTED"
        store.touch(camp)
        for ag in store.list_all("AdGroup"):
            if ag.get("campaign_id") == camp["id"] and ag.get("status") == "RUNNING":
                ag["status"] = "BUDGET_EXHAUSTED"
                store.touch(ag)
    elif not exhausted and status == "BUDGET_EXHAUSTED":
        camp["status"] = "ACTIVE"
        store.touch(camp)
        for ag in store.list_all("AdGroup"):
            if ag.get("campaign_id") == camp["id"] and ag.get("status") == "BUDGET_EXHAUSTED":
                ag["status"] = "RUNNING"
                store.touch(ag)


def _compute_charge(ag: dict, event_type: str, clearing_price: int) -> int:
    strategy = ag.get("bidding_strategy")
    if strategy == "OCPX":
        # Charge on CLICK or CONVERSION events; the event_type disambiguates.
        if event_type in ("CLICK", "CONVERSION"):
            return clearing_price
        return 0
    expected = STRATEGY_TO_EVENT.get(strategy)
    if expected == event_type:
        return clearing_price
    return 0


def ingest_billing_event(body: dict) -> dict:
    event_type = body.get("event_type")
    auction_event_id = body.get("auction_event_id")
    ad_group_id = body.get("ad_group_id")
    dedup_key = body.get("dedup_key")
    ivt_score = body.get("ivt_score")

    if event_type not in ("IMPRESSION", "CLICK", "CONVERSION"):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid event_type.")
    if not auction_event_id or not ad_group_id or not dedup_key:
        raise ApiError("ERR_INVALID_REQUEST", "auction_event_id, ad_group_id, dedup_key required.")
    if not isinstance(ivt_score, (int, float)) or isinstance(ivt_score, bool):
        raise ApiError("ERR_INVALID_REQUEST", "ivt_score must be numeric.")

    auction = store.get("AuctionEvent", auction_event_id)
    if not auction:
        raise ApiError("ERR_INVALID_REQUEST", "auction_event_id does not resolve.")
    ag = store.get("AdGroup", ad_group_id)
    if not ag:
        raise ApiError("ERR_INVALID_REQUEST", "ad_group_id does not resolve.")

    # Dedup check
    if _existing_dup(event_type, auction_event_id, dedup_key):
        raise ApiError("ERR_DUPLICATE_BILLING_EVENT")

    camp = store.get("Campaign", ag["campaign_id"])
    adv = store.get("Advertiser", ag["advertiser_id"])

    # Build the event.
    rec = {
        "id": store.gen_uuid(),
        "event_type": event_type,
        "auction_event_id": auction_event_id,
        "ad_group_id": ad_group_id,
        "campaign_id": camp["id"],
        "advertiser_id": adv["id"],
        "dedup_key": dedup_key,
        "gross_cost_cents": 0,
        "tax_cents": 0,
        "cost_cents": 0,
        "ivt_score": float(ivt_score),
        "status": "PENDING_IVT",
        "finalized_at": None,
        "reversal_reason": None,
    }
    store.stamp_common(rec, with_version=False)

    # IVT screen
    if float(ivt_score) > 0.7:
        rec["status"] = "INVALID_TRAFFIC"
        store.insert("BillingEvent", rec)
        return rec

    rec["status"] = "VALID"

    # Compute charge based on bidding_strategy and event_type alignment.
    clearing = int(auction.get("clearing_price_cents", 0))
    gross = _compute_charge(ag, event_type, clearing)
    tax_rate_bps = int(adv.get("tax_rate_bps", 0))
    tax = int((gross * tax_rate_bps) // 10000)  # floor
    cost = gross + tax
    rec["gross_cost_cents"] = gross
    rec["tax_cents"] = tax
    rec["cost_cents"] = cost
    rec["status"] = "FINALIZED"
    rec["finalized_at"] = now_iso()
    store.insert("BillingEvent", rec)

    # Wallet consumption.
    if cost > 0:
        wt = {
            "id": store.gen_uuid(),
            "advertiser_id": adv["id"],
            "tx_type": "CONSUMPTION",
            "amount_cents": -cost,
            "reference_event_id": rec["id"],
            "status": "SETTLED",
            "idempotency_key": f"consumption:{rec['id']}",
            "note": None,
        }
        store.stamp_common(wt, with_version=False)
        store.insert("WalletTransaction", wt)
        recompute_balance(adv)
        recompute_balance_state(adv)

    # Campaign aggregate update.
    reaggregate_campaign(camp)

    return rec


def reverse_billing_event(rec: dict, reason: str) -> dict:
    if rec.get("status") != "FINALIZED":
        raise ApiError("ERR_INVALID_BILLING_EVENT_STATE")
    if not reason or not str(reason).strip():
        raise ApiError("ERR_INVALID_REQUEST", "reversal_reason is required.")

    cost = int(rec.get("cost_cents", 0))
    rec["status"] = "REVERSED"
    rec["reversal_reason"] = reason

    adv = store.get("Advertiser", rec["advertiser_id"])
    if cost > 0 and adv is not None:
        wt = {
            "id": store.gen_uuid(),
            "advertiser_id": adv["id"],
            "tx_type": "REFUND",
            "amount_cents": cost,
            "reference_event_id": rec["id"],
            "status": "SETTLED",
            "idempotency_key": f"refund:{rec['id']}",
            "note": "billing_event_reversal",
        }
        store.stamp_common(wt, with_version=False)
        store.insert("WalletTransaction", wt)
        recompute_balance(adv)
        recompute_balance_state(adv)

    camp = store.get("Campaign", rec["campaign_id"])
    if camp:
        reaggregate_campaign(camp)

    audit_emit(
        "REFUND",
        "BillingEvent",
        rec["id"],
        before_value={"status": "FINALIZED", "cost_cents": cost},
        after_value={"status": "REVERSED", "reversal_reason": reason},
    )
    return rec
