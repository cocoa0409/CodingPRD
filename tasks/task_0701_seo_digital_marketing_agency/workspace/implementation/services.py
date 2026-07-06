"""Cross-entity reconciliation: credit ledger, health score, dispute count,
rank momentum, report figures, and cascades (PRD §3)."""
import calc
from clock import parse_iso8601
from db import store, touch

DELIVERABLE_TERMINAL = {"APPROVED", "REJECTED", "CANCELLED"}
DELIVERABLE_RESERVED = {"ASSIGNED", "IN_PROGRESS", "IN_REVIEW"}


# ---------------------------------------------------------------------------
# Reseller lookup for a client
# ---------------------------------------------------------------------------


def reseller_for_client(client):
    rid = client.get("reseller_id")
    if not rid:
        return None
    return store.resellers.get(rid)


def ppc_base_rate(client):
    reseller = reseller_for_client(client)
    if reseller is not None:
        return reseller["ppc_management_pct"]
    return calc.AGENCY_PPC_PCT


# ---------------------------------------------------------------------------
# Retainer credit ledger (PRD §3.4 / calc retainer_credit_balance)
# ---------------------------------------------------------------------------


def recompute_retainer_balance(retainer):
    """Recompute committed/consumed/available from underlying deliverables of
    the current cycle. credits_granted is set by activate/rollover and not
    touched here."""
    rid = retainer["id"]
    cycle = retainer["cycle_index"]
    committed = 0
    consumed = 0
    for d in store.deliverables.values():
        if d["retainer_id"] != rid:
            continue
        if d["status"] in DELIVERABLE_RESERVED:
            committed += d["credit_cost"]
        elif d["status"] == "APPROVED" and d.get("_approved_cycle") == cycle:
            consumed += d["credit_cost"]
    retainer["credits_committed"] = committed
    retainer["credits_consumed"] = consumed
    retainer["credits_available"] = (
        retainer["credits_granted"] - committed - consumed
    )


# ---------------------------------------------------------------------------
# Sprint committed credits (PRD §3.6)
# ---------------------------------------------------------------------------


def recompute_sprint_committed(sprint):
    sid = sprint["id"]
    total = 0
    for d in store.deliverables.values():
        if d["sprint_id"] != sid:
            continue
        if d["status"] in ("CANCELLED", "REJECTED"):
            continue
        total += d["credit_cost"]
    sprint["committed_credits"] = total


# ---------------------------------------------------------------------------
# Open dispute count (PRD §3.8)
# ---------------------------------------------------------------------------


def recompute_open_dispute_count(client):
    cid = client["id"]
    count = 0
    for disp in store.ad_spend_disputes.values():
        if disp["client_id"] != cid:
            continue
        if disp["status"] in ("OPEN", "UNDER_REVIEW"):
            count += 1
    client["open_dispute_count"] = count


# ---------------------------------------------------------------------------
# Account health score (PRD §3.3 / calc account_health_score)
# ---------------------------------------------------------------------------


def latest_report_momentum(client):
    cid = client["id"]
    reports = [r for r in store.reports.values() if r["client_id"] == cid]
    if not reports:
        return 0.0
    latest = max(reports, key=lambda r: r["_seq"])
    return latest["rank_momentum"]


def recompute_health_score(client):
    base = 100
    momentum = latest_report_momentum(client)
    momentum_term = calc.MOMENTUM_WEIGHT * calc.Decimal(str(momentum))
    # clamp momentum term to [-30, 30]
    if momentum_term > 30:
        momentum_term = calc.Decimal(30)
    elif momentum_term < -30:
        momentum_term = calc.Decimal(-30)

    now = store.clock.now()
    cid = client["id"]
    overdue = 0
    for d in store.deliverables.values():
        if d["client_id"] != cid:
            continue
        if d["status"] not in DELIVERABLE_RESERVED:
            continue
        sprint = store.sprints.get(d["sprint_id"])
        if sprint is None:
            continue
        ends_at = parse_iso8601(sprint["ends_at"])
        if ends_at is not None and ends_at < now:
            overdue += 1
    overdue_penalty = calc.OVERDUE_PENALTY * overdue
    dispute_penalty = calc.DISPUTE_PENALTY * client["open_dispute_count"]

    raw = calc.Decimal(base) + momentum_term - calc.Decimal(overdue_penalty) - calc.Decimal(dispute_penalty)
    score = calc.round_half_up(raw, 0)
    score = max(0, min(100, score))
    client["health_score"] = score


# ---------------------------------------------------------------------------
# Campaign management fee live recompute (PRD §3.7)
# ---------------------------------------------------------------------------


def recompute_campaign_fee(campaign):
    """Live estimate; only valid while UNBILLED. Caller decides when to call."""
    client = store.clients.get(campaign["client_id"])
    base_rate = ppc_base_rate(client) if client else calc.AGENCY_PPC_PCT
    campaign["management_fee_cents"] = calc.ppc_management_fee(
        campaign["spent_cents"], base_rate
    )


# ---------------------------------------------------------------------------
# Rank momentum & report figures (PRD §3.3)
# ---------------------------------------------------------------------------


def _snapshots_for_target_in_window(target_id, start, end):
    """Return in-window snapshots ordered by observed_at ASC then created_at ASC
    (tie-break by _seq for created_at stability)."""
    out = []
    for snap in store.rank_snapshots.values():
        if snap["keyword_target_id"] != target_id:
            continue
        observed = parse_iso8601(snap["observed_at"])
        if observed is None:
            continue
        if start <= observed < end:
            out.append(snap)
    out.sort(key=lambda s: (parse_iso8601(s["observed_at"]), s["_seq"]))
    return out


def compute_report_figures(client, period_start, period_end):
    """Return (avg_rank, total_traffic, rank_momentum)."""
    cid = client["id"]
    tracking = [
        k for k in store.keyword_targets.values()
        if k["client_id"] == cid and k["status"] == "TRACKING"
    ]

    # avg_rank: mean current_rank over TRACKING keywords with current_rank > 0
    ranked = [k["current_rank"] for k in tracking if k["current_rank"] > 0]
    if ranked:
        avg_rank = calc.round_half_up(sum(ranked) / len(ranked), 2)
    else:
        avg_rank = 0.0

    # total_traffic: sum organic_traffic for snapshots in [period_start, period_end)
    total_traffic = 0
    for snap in store.rank_snapshots.values():
        observed = parse_iso8601(snap["observed_at"])
        if observed is None:
            continue
        if period_start <= observed < period_end:
            # only snapshots whose keyword belongs to this client
            kt = store.keyword_targets.get(snap["keyword_target_id"])
            if kt is not None and kt["client_id"] == cid:
                total_traffic += snap["organic_traffic"]

    # rank_momentum: mean of per-keyword improvement over TRACKING keywords with
    # >=1 in-window snapshot
    improvements = []
    for k in tracking:
        snaps = _snapshots_for_target_in_window(k["id"], period_start, period_end)
        if not snaps:
            continue
        first_pos = snaps[0]["position"]
        last_pos = snaps[-1]["position"]
        first_eff = calc.UNRANKED_SENTINEL if first_pos == 0 else first_pos
        last_eff = calc.UNRANKED_SENTINEL if last_pos == 0 else last_pos
        improvements.append(first_eff - last_eff)

    if improvements:
        rank_momentum = calc.round_half_up(sum(improvements) / len(improvements), 2)
    else:
        rank_momentum = 0.0

    return avg_rank, total_traffic, rank_momentum


# ---------------------------------------------------------------------------
# Cascades (PRD §3.1, §3.4)
# ---------------------------------------------------------------------------


def cancel_non_terminal_deliverables_for_retainer(retainer):
    """Cascade: move every non-terminal deliverable of this retainer to
    CANCELLED, releasing reserved credits. Each child is an independent mutation."""
    rid = retainer["id"]
    for d in store.deliverables.values():
        if d["retainer_id"] != rid:
            continue
        if d["status"] in DELIVERABLE_TERMINAL:
            continue
        was_reserved = d["status"] in DELIVERABLE_RESERVED
        d["status"] = "CANCELLED"
        touch(d)
        if was_reserved:
            sprint = store.sprints.get(d["sprint_id"])
            if sprint is not None:
                recompute_sprint_committed(sprint)
                touch(sprint)
    recompute_retainer_balance(retainer)
