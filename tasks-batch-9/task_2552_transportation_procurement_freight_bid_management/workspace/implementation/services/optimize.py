"""The allocation waterfall, the objective score, routing-guide publication and the
backup-promotion re-derivation — PRD §3.6 and §3.7 link 4."""
from decimal import Decimal

import store
from numeric import D, floor_int, q2, q6
from services import bidding, lanes as lane_svc

POSITIONS = ("PRIMARY", "BACKUP_1", "BACKUP_2")
MAX_POSITIONS = 3
DEFAULT_MIN_CAPACITY_COVERAGE_PCT = Decimal("90.00")
ELIGIBLE_CARRIER_STATUSES = ("QUALIFIED", "CONDITIONALLY_QUALIFIED", "WATCHLIST")
# The waterfall reads lanes that are inside the frozen award scope.
RUN_LANE_STATUSES = ("LOCKED", "AWARDED", "UNDER_REBID")


def run_lanes(event_id):
    return [l for l in lane_svc.event_lanes(event_id)
            if l["status"] in RUN_LANE_STATUSES]


def latest_closed_round(event_id):
    closed = [r for r in store.rounds.values()
              if r["bid_event_id"] == event_id and r["status"] == "CLOSED"]
    if not closed:
        return None
    return max(closed, key=lambda r: (r["round_no"], r["_seq"]))


def _invitation_accepted(event_id, carrier_id):
    for invitation in store.invitations.values():
        if (invitation["bid_event_id"] == event_id
                and invitation["carrier_id"] == carrier_id
                and invitation["status"] == "ACCEPTED"):
            return True
    return False


def candidates(event, lane, round_row):
    """The lane's bids from the event's most recent CLOSED round only, that are
    SUBMITTED or SHORTLISTED and satisfy all five eligibility conditions."""
    if round_row is None:
        return []
    out = []
    for bid in bidding.lane_round_bids(round_row["id"], lane["id"]):
        if bid["status"] not in ("SUBMITTED", "SHORTLISTED"):
            continue
        carrier = store.carriers.get(bid["carrier_id"])
        if carrier is None:
            continue
        if not _invitation_accepted(event["id"], carrier["id"]):
            continue
        if carrier["status"] not in ELIGIBLE_CARRIER_STATUSES:
            continue
        expiry = store.dt_of(carrier["insurance_expiry_date"])
        if expiry is None or expiry <= store.now():
            continue
        if int(bid["transit_days_offered"]) > int(lane["service_days_required"]):
            continue
        if D(bid["rate_per_mile"]) < D(event["rate_floor_per_mile"]):
            continue
        out.append(bid)
    return sorted(out, key=bidding.rank_key)


def share_cap(event, lane):
    """Floor, never a rounded-up figure."""
    return floor_int(D(lane["annual_volume_loads"]) * D(event["max_award_share_pct"])
                     / Decimal("100.00"))


def pick_fields(lane, bid, grant, position):
    annual = D(lane["annual_volume_loads"])
    return {
        "lane_id": lane["id"],
        "carrier_id": bid["carrier_id"],
        "lane_bid_id": bid["id"],
        "routing_position": position,
        "allocated_volume_loads": grant,
        "allocated_pct": q2(D(grant) * Decimal("100.00") / annual),
        "allocated_cost_usd": q2(D(bid["cost_per_load_usd"]) * D(grant)),
    }


def waterfall(event, run, lane, round_row):
    """Fill routing positions from the best bid downward.  A grant of zero consumes no
    position: the candidate is skipped and the next one is considered for the same seat."""
    seats = min(int(run["max_carriers_per_lane"]), MAX_POSITIONS)
    remaining = int(lane["annual_volume_loads"])
    cap = share_cap(event, lane)
    picks = []
    for bid in candidates(event, lane, round_row):
        if len(picks) >= seats or remaining <= 0:
            break
        grant = min(remaining, int(bid["committed_volume_loads"]), cap)
        if grant <= 0:
            continue
        picks.append(pick_fields(lane, bid, grant, POSITIONS[len(picks)]))
        remaining -= grant
    return picks


def evaluate_run(event, run):
    """Run the waterfall over the in-scope lanes, then derive the headline figures."""
    round_row = latest_closed_round(event["id"])
    scope = run_lanes(event["id"])
    picks = []
    infeasible = []
    for lane in scope:
        lane_picks = waterfall(event, run, lane, round_row)
        if not any(p["routing_position"] == "PRIMARY" for p in lane_picks):
            infeasible.append(lane["id"])
        picks.extend(lane_picks)

    run["_picks"] = picks
    run["infeasible_lane_ids"] = infeasible
    run["proposed_primary_count"] = sum(1 for p in picks
                                        if p["routing_position"] == "PRIMARY")
    run["proposed_backup_count"] = sum(1 for p in picks
                                       if p["routing_position"] != "PRIMARY")

    allocated = sum(p["allocated_volume_loads"] for p in picks)
    scope_volume = sum(l["annual_volume_loads"] for l in scope)

    if len(infeasible) == len(scope):
        run["status"] = "FAILED"
        run["total_cost_usd"] = Decimal("0.00")
        run["coverage_pct"] = Decimal("0.00")
        run["objective_score"] = Decimal("0.00")
        run["diversity_pct"] = _diversity_pct(picks, allocated)
        return run

    run["status"] = "COMPLETED"
    run["total_cost_usd"] = q2(sum((D(p["allocated_cost_usd"]) for p in picks),
                                   Decimal("0")))
    if scope_volume:
        run["coverage_pct"] = q2(D(allocated) * Decimal("100.00") / D(scope_volume))
    else:
        run["coverage_pct"] = Decimal("0.00")
    run["diversity_pct"] = _diversity_pct(picks, allocated)

    cost_ratio = _cost_ratio(scope, picks)
    service_ratio = _service_ratio(picks, allocated)
    objective = ((Decimal("1.000000") - cost_ratio) * D(event["cost_weight"])
                 + service_ratio * D(event["service_weight"])
                 + q6(D(run["coverage_pct"]) / Decimal("100.00"))
                 * D(event["capacity_weight"])
                 + q6(D(run["diversity_pct"]) / Decimal("100.00"))
                 * D(event["diversity_weight"]))
    run["objective_score"] = q2(objective * Decimal("100.00"))
    return run


def _diversity_pct(picks, allocated):
    if allocated == 0:
        return Decimal("0.00")
    diverse = 0
    for pick in picks:
        carrier = store.carriers.get(pick["carrier_id"])
        if carrier and carrier["diversity_classification"] != "NONE":
            diverse += pick["allocated_volume_loads"]
    return q2(D(diverse) * Decimal("100.00") / D(allocated))


def _cost_ratio(scope, picks):
    """A ratio of sums over the in-scope lanes whose baseline is strictly positive —
    never a mean of per-lane ratios."""
    lane_ids = {l["id"] for l in scope if D(l["baseline_cost_usd"] or 0) > Decimal("0")}
    baseline = sum((D(l["baseline_cost_usd"] or 0) for l in scope
                    if l["id"] in lane_ids), Decimal("0"))
    if baseline == 0:
        return Decimal("1.000000")
    award = sum((D(p["allocated_cost_usd"]) for p in picks
                 if p["lane_id"] in lane_ids), Decimal("0"))
    return q6(award / baseline)


def _service_ratio(picks, allocated):
    if allocated == 0:
        return Decimal("0.000000")
    total = Decimal("0")
    for pick in picks:
        carrier = store.carriers.get(pick["carrier_id"])
        score = D(carrier["composite_score"]) if carrier else Decimal("0")
        total += D(pick["allocated_volume_loads"]) * (score / Decimal("100.00"))
    return q6(total / D(allocated))


def supersede_history(event):
    """Creating a run supersedes the scenario history in three linked steps."""
    superseded_any = False
    for run in store.sorted_rows(store.runs.values()):
        if run["bid_event_id"] != event["id"]:
            continue
        if run["status"] not in ("COMPLETED", "PUBLISHED"):
            continue
        run["status"] = "SUPERSEDED"
        store.touch(run)
        for allocation in store.sorted_rows(store.allocations.values()):
            if allocation["optimization_run_id"] != run["id"]:
                continue
            if allocation["status"] not in ("PROPOSED", "APPROVED"):
                continue
            was_approved = allocation["status"] == "APPROVED"
            allocation["status"] = "SUPERSEDED"
            store.touch(allocation)
            superseded_any = True
            if was_approved:
                lane = store.lanes.get(allocation["lane_id"])
                if lane is not None:
                    lane["unallocated_volume_loads"] += allocation[
                        "allocated_volume_loads"]
                    lane_svc.recompute_awarded_coverage(lane)
                    store.touch(lane)

    # The event's coverage and diversity are rollups over the allocation status set
    # of §3.3; superseding allocations drops them out of that set, so the rollups
    # must follow rather than drift (§2.12).
    if superseded_any:
        lane_svc.recompute_coverage(event)
        store.touch(event)


def publish_guide(event, run):
    """Materialise the picks as PROPOSED allocations and settle the bid statuses."""
    created = []
    guided_lanes = set()
    selected_bid_ids = set()
    for pick in run["_picks"]:
        allocation = store.new_row(
            bid_event_id=event["id"],
            optimization_run_id=run["id"],
            lane_id=pick["lane_id"],
            carrier_id=pick["carrier_id"],
            lane_bid_id=pick["lane_bid_id"],
            routing_position=pick["routing_position"],
            allocated_volume_loads=pick["allocated_volume_loads"],
            allocated_pct=pick["allocated_pct"],
            allocated_cost_usd=pick["allocated_cost_usd"],
            status="PROPOSED",
            approved_by_user_id=None,
            approved_at=None,
            rejection_reason=None,
            promoted_from_position=None,
        )
        store.allocations[allocation["id"]] = allocation
        created.append(allocation)
        guided_lanes.add(pick["lane_id"])
        selected_bid_ids.add(pick["lane_bid_id"])

    round_row = latest_closed_round(event["id"])
    for bid_id in selected_bid_ids:
        bid = store.lane_bids.get(bid_id)
        if bid is not None and bid["status"] == "SUBMITTED":
            bid["status"] = "SHORTLISTED"
            store.touch(bid)
    if round_row is not None:
        for bid in store.sorted_rows(store.lane_bids.values()):
            if bid["bid_round_id"] != round_row["id"]:
                continue
            if bid["id"] in selected_bid_ids or bid["status"] != "SUBMITTED":
                continue
            if bid["lane_id"] not in guided_lanes:
                continue
            bid["status"] = "NOT_AWARDED"
            store.touch(bid)
    return created


def rederive_lane_volumes(event, lane, run_id=None):
    """PRD §3.7 link 4 — after a promotion the surviving positions are re-derived by the
    same waterfall arithmetic, and an allocation that already held a debit has only the
    difference applied to the lane."""
    surviving = [a for a in store.sorted_rows(store.allocations.values())
                 if a["lane_id"] == lane["id"] and a["status"] in ("PROPOSED", "APPROVED")
                 and (run_id is None or a["optimization_run_id"] == run_id)]
    surviving.sort(key=lambda a: (POSITIONS.index(a["routing_position"])
                                  if a["routing_position"] in POSITIONS else MAX_POSITIONS,
                                  a["_seq"]))
    remaining = int(lane["annual_volume_loads"])
    cap = share_cap(event, lane)
    for allocation in surviving:
        bid = store.lane_bids.get(allocation["lane_bid_id"])
        committed = int(bid["committed_volume_loads"]) if bid else 0
        grant = min(max(remaining, 0), committed, cap)
        old = int(allocation["allocated_volume_loads"])
        annual = D(lane["annual_volume_loads"])
        allocation["allocated_volume_loads"] = grant
        allocation["allocated_pct"] = q2(D(grant) * Decimal("100.00") / annual)
        cost_per_load = D(bid["cost_per_load_usd"]) if bid else Decimal("0")
        allocation["allocated_cost_usd"] = q2(cost_per_load * D(grant))
        store.touch(allocation)
        if allocation["status"] == "APPROVED":
            lane["unallocated_volume_loads"] -= (grant - old)
        remaining -= grant
