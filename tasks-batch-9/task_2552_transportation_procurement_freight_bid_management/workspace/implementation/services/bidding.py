"""Bid evaluation, the service credit, rank ordering and the round counters —
PRD §3.5, plus the withdrawal cascade shared by §3.1 and §3.4."""
from decimal import Decimal

import store
from numeric import D, q2, q4, rnd_int

FORECAST_GROWTH_FACTOR = Decimal("1.20")
SERVICE_CREDIT_BASE = Decimal("80.00")
SERVICE_CREDIT_DIVISOR = Decimal("200")
SERVICE_CREDIT_FLOOR = Decimal("0.0000")
SERVICE_CREDIT_MAX = Decimal("0.0500")

# PRD §2.12 status sets.
COUNTED_BID_STATUSES = ("SUBMITTED", "SHORTLISTED", "AWARDED_PRIMARY",
                        "AWARDED_BACKUP", "NOT_AWARDED")
RANKED_BID_STATUSES = ("SUBMITTED", "SHORTLISTED")


def effective_rate(rate_per_mile, fuel_included, event):
    """Step 1 — the quoted rate unchanged when fuel is included, otherwise the quoted
    rate plus the event's fuel index rounded to 4 decimal places."""
    if fuel_included:
        return D(rate_per_mile)
    return q4(D(rate_per_mile) + D(event["fuel_index_per_mile"]))


def evaluate_bid(bid, lane, event, carrier):
    """Steps 1-6 of the cost evaluation, then the service credit and the rank score.
    The rounding points are part of the answer: step 4 adds two already-rounded
    figures."""
    basis = event["cost_basis"]
    bid["evaluated_basis"] = basis

    rate = effective_rate(bid["rate_per_mile"], bid["fuel_surcharge_included"], event)
    bid["effective_rate_per_mile"] = rate
    bid["linehaul_per_load_usd"] = q2(D(lane["mileage"]) * rate)

    accessorial = D(lane["accessorial_history_usd_per_load"])
    if basis == "FORECAST":
        bid["accessorial_per_load_usd"] = q2(accessorial
                                             * D(event["accessorial_inflation_factor"]))
    else:
        bid["accessorial_per_load_usd"] = q2(accessorial)

    bid["cost_per_load_usd"] = q2(D(bid["linehaul_per_load_usd"])
                                  + D(bid["accessorial_per_load_usd"]))

    if basis == "FORECAST":
        volume_basis = rnd_int(D(lane["annual_volume_loads"]) * FORECAST_GROWTH_FACTOR)
    else:
        trailing = lane["trailing_12m_actual_loads"]
        volume_basis = 0 if trailing is None else int(trailing)
    bid["awardable_volume_loads"] = min(int(bid["committed_volume_loads"]), volume_basis)

    bid["evaluated_total_cost_usd"] = q2(D(bid["cost_per_load_usd"])
                                         * D(bid["awardable_volume_loads"]))

    credit = q4((D(carrier["composite_score"]) - SERVICE_CREDIT_BASE)
                / SERVICE_CREDIT_DIVISOR)
    if credit < SERVICE_CREDIT_FLOOR:
        credit = SERVICE_CREDIT_FLOOR
    if credit > SERVICE_CREDIT_MAX:
        credit = SERVICE_CREDIT_MAX
    bid["service_credit_pct"] = credit
    bid["cost_rank_score"] = q2(D(bid["evaluated_total_cost_usd"])
                                * (Decimal("1") - credit))
    return bid


def rank_key(bid):
    """cost_rank_score ascending, transit_days_offered ascending, is_incumbent
    descending, created_at ascending.  The bid's own id is never an input."""
    return (D(bid["cost_rank_score"]), int(bid["transit_days_offered"]),
            0 if bid["is_incumbent"] else 1, bid["created_at"], bid["_seq"])


def lane_round_bids(round_id, lane_id):
    return [b for b in store.lane_bids.values()
            if b["bid_round_id"] == round_id and b["lane_id"] == lane_id]


def rerank_lane(round_id, lane_id, touch_others=True):
    """Renumber rank_in_lane contiguously from 1 over the lane's rankable bids in one
    round."""
    ranked = sorted([b for b in lane_round_bids(round_id, lane_id)
                     if b["status"] in RANKED_BID_STATUSES], key=rank_key)
    for index, bid in enumerate(ranked, start=1):
        if bid["rank_in_lane"] != index:
            bid["rank_in_lane"] = index
            if touch_others:
                store.touch(bid)
        else:
            bid["rank_in_lane"] = index


def recompute_round_counters(round_row):
    """submitted_bid_count reads the counted status set; lowest_rate_per_mile reads only
    the bids that are still SUBMITTED and is null when the round holds none."""
    bids = [b for b in store.lane_bids.values() if b["bid_round_id"] == round_row["id"]]
    round_row["submitted_bid_count"] = sum(1 for b in bids
                                           if b["status"] in COUNTED_BID_STATUSES)
    rates = [D(b["rate_per_mile"]) for b in bids if b["status"] == "SUBMITTED"]
    round_row["lowest_rate_per_mile"] = min(rates) if rates else None


def withdrawal_cascade(carrier_id):
    """Every lane bid of the carrier that is SUBMITTED on a round that is still OPEN
    moves to WITHDRAWN, and each affected round's counters are recomputed.  Shared by
    carrier disqualification (§3.1) and invitation revocation (§3.4), which is why the
    two leave the rounds in an identical state."""
    affected_rounds = {}
    affected_lanes = set()
    for bid in store.sorted_rows(store.lane_bids.values()):
        if bid["carrier_id"] != carrier_id or bid["status"] != "SUBMITTED":
            continue
        round_row = store.rounds.get(bid["bid_round_id"])
        if round_row is None or round_row["status"] != "OPEN":
            continue
        bid["status"] = "WITHDRAWN"
        bid["withdrawn_at"] = store.now_iso()
        store.touch(bid)
        affected_rounds[round_row["id"]] = round_row
        affected_lanes.add((round_row["id"], bid["lane_id"]))
    for round_id, lane_id in sorted(affected_lanes):
        rerank_lane(round_id, lane_id)
    for round_row in affected_rounds.values():
        recompute_round_counters(round_row)
        store.touch(round_row)
