"""Auction engine: filter → rank → price."""
import math

from .. import store
from ..clock import start_of_utc_day


SHADING_FACTOR = 0.92


def _frequency_impressions_today(ad_group_id: str, user_id: str) -> int:
    day_start = start_of_utc_day()
    count = 0
    for be in store.list_all("BillingEvent"):
        if be.get("ad_group_id") != ad_group_id:
            continue
        if be.get("event_type") != "IMPRESSION":
            continue
        if be.get("status") not in ("VALID", "FINALIZED"):
            continue
        # Join through auction to compare user_id
        auc = store.get("AuctionEvent", be.get("auction_event_id", ""))
        if not auc or auc.get("user_id") != user_id:
            continue
        # finalized_at must be on or after start of current UTC day
        fa = be.get("finalized_at") or be.get("created_at", "")
        # ISO timestamps compare lexicographically (Z suffix; common offset)
        if fa >= day_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"):
            count += 1
    return count


def _effective_bid_cents(ag: dict) -> float:
    bid = float(ag["bid_cents"])
    if ag["bidding_strategy"] == "CPM":
        return bid / 1000.0
    return bid


def _ranking_score(ag: dict) -> float:
    eb = _effective_bid_cents(ag)
    q = float(ag.get("quality_score", 5.0))
    ctr = float(ag.get("predicted_ctr", 0.02))
    return eb * q * ctr


def _filter_candidates(candidate_ids: list[str], user_id: str) -> tuple[list[dict], list[str]]:
    """Filter ad-groups by budget posture and frequency cap."""
    eligible = []
    filtered = []
    for ag_id in candidate_ids:
        ag = store.get("AdGroup", ag_id)
        if not ag:
            filtered.append(ag_id)
            continue
        # Budget posture: skip if parent campaign exhausted.
        camp = store.get("Campaign", ag.get("campaign_id", ""))
        if not camp:
            filtered.append(ag_id)
            continue
        if camp.get("status") == "BUDGET_EXHAUSTED":
            filtered.append(ag_id)
            continue
        # Frequency cap check.
        cap = ag.get("frequency_cap_per_user_per_day")
        if cap is not None:
            count = _frequency_impressions_today(ag_id, user_id)
            if count >= int(cap):
                filtered.append(ag_id)
                continue
        eligible.append(ag)
    return eligible, filtered


def _select_winning_creative(ag_id: str) -> str | None:
    approved = [
        c for c in store.list_all("Creative")
        if c.get("ad_group_id") == ag_id and c.get("review_status") == "APPROVED"
    ]
    if not approved:
        return None
    # Pick oldest approved creative deterministically.
    approved.sort(key=lambda c: (c.get("created_at", ""), c.get("id", "")))
    return approved[0]["id"]


def _gsp_price(winner: dict, runner: dict | None, floor_price: int, external_rtb: bool) -> tuple[int, bool]:
    """Compute clearing unit price under GSP, returning (price_cents, bid_shaded)."""
    eff_bid_w = _effective_bid_cents(winner)
    if runner is None:
        clearing = float(floor_price)
    else:
        # bid-just-to-beat: ceil( (R.ranking_score / (W.qs * W.pctr)) + 1 )
        q = float(winner.get("quality_score", 5.0))
        pctr = float(winner.get("predicted_ctr", 0.02))
        denom = q * pctr if (q * pctr) != 0 else 1e-9
        quotient = _ranking_score(runner) / denom
        clearing = float(math.ceil(quotient) + 1)

    # Clamp: floor enforcement first, then bid-shading.
    clearing = max(clearing, float(floor_price))
    clearing = min(clearing, float(eff_bid_w))

    shaded = False
    if external_rtb:
        clearing = math.floor(clearing * SHADING_FACTOR)
        shaded = True
    return int(clearing), shaded


def _vcg_price(winner: dict, runner: dict | None, floor_price: int) -> int:
    eff_bid_w = _effective_bid_cents(winner)
    if runner is None:
        return int(floor_price)
    q = float(winner.get("quality_score", 5.0))
    pctr = float(winner.get("predicted_ctr", 0.02))
    denom = q * pctr if (q * pctr) != 0 else 1e-9
    externality = _ranking_score(runner) / denom
    clearing = float(math.ceil(externality))
    clearing = max(clearing, float(floor_price))
    clearing = min(clearing, float(eff_bid_w))
    return int(clearing)


def run_auction(req: dict) -> dict:
    exchange = req["exchange"]
    pricing_rule = req["pricing_rule"]
    floor_price = int(req["floor_price_cents"])
    user_id = req["user_id"]
    candidate_ids = list(req.get("candidate_ad_group_ids", []))

    eligible, filtered = _filter_candidates(candidate_ids, user_id)

    outcome = "FILLED"
    winning_ag = None
    winning_creative_id = None
    clearing_price = 0
    bid_shaded = False

    if not eligible:
        if not candidate_ids:
            outcome = "NO_BID"
        else:
            outcome = "ALL_FILTERED"
    else:
        # Rank by ranking_score desc, tie-break by created_seq asc.
        eligible.sort(
            key=lambda a: (
                -_ranking_score(a),
                int(_campaign_seq(a)),
            )
        )
        winner = eligible[0]
        runner = eligible[1] if len(eligible) > 1 else None
        eff_bid_w = _effective_bid_cents(winner)

        if eff_bid_w < floor_price:
            outcome = "FLOOR_NOT_MET"
        else:
            if pricing_rule == "GSP":
                price, bid_shaded = _gsp_price(winner, runner, floor_price, exchange == "EXTERNAL_RTB")
            else:  # VCG
                price = _vcg_price(winner, runner, floor_price)
            clearing_price = price
            winning_ag = winner
            winning_creative_id = _select_winning_creative(winner["id"])

    rec = {
        "id": store.gen_uuid(),
        "exchange": exchange,
        "pricing_rule": pricing_rule,
        "floor_price_cents": floor_price,
        "user_id": user_id,
        "device": req.get("device"),
        "geo": req.get("geo"),
        "candidate_ad_group_ids": candidate_ids,
        "filtered_ad_group_ids": filtered,
        "winning_ad_group_id": winning_ag["id"] if winning_ag else None,
        "winning_creative_id": winning_creative_id,
        "clearing_price_cents": clearing_price,
        "bid_shaded": bid_shaded,
        "outcome": outcome,
    }
    store.stamp_common(rec, with_version=False)
    store.insert("AuctionEvent", rec)
    return rec


def _campaign_seq(ag: dict) -> int:
    camp = store.get("Campaign", ag.get("campaign_id", ""))
    return int(camp.get("created_seq", 0)) if camp else 0
