"""work_rank_score and critical_path_float (SCAFFOLD 1.3; PRD 3.1).

Both run over the turnaround's PROPOSED work items and its dependency DAG
(acyclic — dependency creation rejects cycles).
"""
import db

RISK_WEIGHT = {"A": 5, "B": 3, "C": 1}
DOWNSTREAM_WEIGHT = 25
COST_TERM_CAP = 500
COST_TERM_DIVISOR = 10000


def _successor_map(tid):
    succ = {}
    for d in db.dependencies.values():
        if d["turnaround_id"] != tid:
            continue
        succ.setdefault(d["predecessor_work_item_id"], []).append(
            (d["successor_work_item_id"], d["lag_hours"]))
    return succ


def downstream_counts(tid):
    """Distinct work items reachable from each item via successor edges."""
    succ = _successor_map(tid)
    counts = {}

    def reach(start):
        seen = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt, _lag in succ.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        seen.discard(start)
        return len(seen)

    for w in db.work_items.values():
        if w["turnaround_id"] == tid:
            counts[w["id"]] = reach(w["id"])
    return counts


def cost_term(estimated_cost_cents):
    return max(0, COST_TERM_CAP - estimated_cost_cents // COST_TERM_DIVISOR)


def compute_rankings(tid, items):
    """Assign rank_score / rank_position to the given (PROPOSED) items.
    Order by rank_score DESC, tie-break created_at ASC; 1-based positions."""
    dc = downstream_counts(tid)
    scored = []
    for w in items:
        score = (RISK_WEIGHT[w["risk_class"]] * 1000
                 + DOWNSTREAM_WEIGHT * dc.get(w["id"], 0)
                 + cost_term(w["estimated_cost_cents"]))
        w["rank_score"] = score
        scored.append(w)
    scored.sort(key=lambda w: (-w["rank_score"], w["_seq"]))
    for idx, w in enumerate(scored, start=1):
        w["rank_position"] = idx
    return scored


def compute_critical_path(tid, items):
    """Set is_critical_path on the given items per critical_path_float.

    path_length(w) = estimated_hours(w) + max over successors s of
    (lag_hours(w->s) + path_length(s)); leaves contribute their own hours.
    total_float(w) = project_length - path_length(w); zero float => critical.
    """
    succ = _successor_map(tid)
    item_ids = {w["id"] for w in items}
    by_id = {w["id"]: w for w in items}
    memo = {}

    def path_length(wid):
        if wid in memo:
            return memo[wid]
        w = by_id[wid]
        best = None
        for nxt, lag in succ.get(wid, ()):
            if nxt not in item_ids:
                continue
            cand = lag + path_length(nxt)
            if best is None or cand > best:
                best = cand
        pl = w["estimated_hours"] + (best if best is not None else 0)
        memo[wid] = pl
        return pl

    if not items:
        return
    lengths = {w["id"]: path_length(w["id"]) for w in items}
    project_length = max(lengths.values())
    for w in items:
        w["is_critical_path"] = (project_length - lengths[w["id"]]) == 0


def would_create_cycle(tid, predecessor_id, successor_id):
    """True when adding predecessor -> successor closes a cycle (a self-loop
    counts). Equivalently: successor can already reach predecessor."""
    if predecessor_id == successor_id:
        return True
    succ = _successor_map(tid)
    seen = set()
    stack = [successor_id]
    while stack:
        cur = stack.pop()
        if cur == predecessor_id:
            return True
        for nxt, _lag in succ.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
