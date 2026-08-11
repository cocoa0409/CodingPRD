"""CPM forward/backward pass and critical path identification (PRD §3.3,
scaffold calculations: cpm_forward_backward_pass, critical_path_identification).

All schedule quantities are integer calendar days (PRD §2.8). Dates are
datetimes; durations are added as whole days; total float is the whole-day
difference between late finish and early finish.
"""

from datetime import timedelta

from errors import ApiError, ERR_CYCLE_DETECTED
from middleware import touch
from util import fmt_dt, parse_dt
from routes.common import activities_of, relationships_of


def _topo_sort(ids, succ_edges):
    """Kahn's algorithm over the directed activity graph. Raises on cycle."""
    indeg = {i: 0 for i in ids}
    for r in succ_edges:
        indeg[r["successor_activity_id"]] += 1
    queue = [i for i in ids if indeg[i] == 0]
    topo = []
    while queue:
        n = queue.pop(0)
        topo.append(n)
        for r in succ_edges:
            if r["predecessor_activity_id"] == n:
                m = r["successor_activity_id"]
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
    if len(topo) != len(ids):
        raise ApiError(ERR_CYCLE_DETECTED, 422,
                       "Schedule network contains a cycle")
    return topo


def compute_cpm(activities, relationships, data_date):
    """Run the forward-and-backward pass.

    Returns (fields, projected_finish, critical_count) where fields maps
    activity id -> dict of computed values (datetimes for dates).
    """
    ids = [a["id"] for a in activities]
    if not ids:
        return {}, None, 0
    idset = set(ids)
    act_by_id = {a["id"]: a for a in activities}
    rels = [r for r in relationships
            if r["predecessor_activity_id"] in idset
            and r["successor_activity_id"] in idset]
    preds = {i: [] for i in ids}
    succs = {i: [] for i in ids}
    for r in rels:
        preds[r["successor_activity_id"]].append(r)
        succs[r["predecessor_activity_id"]].append(r)

    topo = _topo_sort(ids, rels)

    # ---- Forward pass ----
    es, ef = {}, {}
    for i in topo:
        dur = int(act_by_id[i]["remaining_duration_days"])
        cands = []
        for r in preds[i]:
            p = r["predecessor_activity_id"]
            lag = int(r["lag_days"])
            t = r["relationship_type"]
            if t == "FS":
                c = ef[p] + timedelta(days=lag)
            elif t == "SS":
                c = es[p] + timedelta(days=lag)
            elif t == "FF":
                c = ef[p] + timedelta(days=lag) - timedelta(days=dur)
            else:  # SF
                c = es[p] + timedelta(days=lag) - timedelta(days=dur)
            cands.append(c)
        es[i] = max(cands) if cands else data_date
        ef[i] = es[i] + timedelta(days=dur)

    terminals = [i for i in ids if not succs[i]]
    horizon = max(ef[i] for i in terminals)

    # ---- Backward pass ----
    ls, lf = {}, {}
    for i in reversed(topo):
        dur = int(act_by_id[i]["remaining_duration_days"])
        cands = []
        for r in succs[i]:
            s = r["successor_activity_id"]
            lag = int(r["lag_days"])
            t = r["relationship_type"]
            if t == "FS":
                c = ls[s] - timedelta(days=lag)
            elif t == "SS":
                c = ls[s] - timedelta(days=lag) + timedelta(days=dur)
            elif t == "FF":
                c = lf[s] - timedelta(days=lag)
            else:  # SF
                c = lf[s] - timedelta(days=lag) + timedelta(days=dur)
            cands.append(c)
        lf[i] = min(cands) if cands else horizon
        ls[i] = lf[i] - timedelta(days=dur)

    fields = {}
    for i in ids:
        tf = (lf[i] - ef[i]).days
        # LONGEST_PATH variant: critical iff total_float_days == 0 (default;
        # no externally imposed completion constraint exists in this system).
        fields[i] = {
            "early_start": es[i],
            "early_finish": ef[i],
            "late_start": ls[i],
            "late_finish": lf[i],
            "total_float_days": tf,
            "is_critical": tf == 0,
        }
    critical_count = sum(1 for i in ids if fields[i]["is_critical"])
    return fields, horizon, critical_count


def run_cpm_and_persist(version):
    """Run the CPM pass on a schedule version and persist all computed fields."""
    acts = activities_of(version["id"])
    rels = relationships_of(version["id"])
    data_date = parse_dt(version["data_date"], "data_date")
    fields, projected_finish, critical_count = compute_cpm(acts, rels, data_date)
    for a in acts:
        f = fields[a["id"]]
        a["early_start"] = fmt_dt(f["early_start"])
        a["early_finish"] = fmt_dt(f["early_finish"])
        a["late_start"] = fmt_dt(f["late_start"])
        a["late_finish"] = fmt_dt(f["late_finish"])
        a["total_float_days"] = f["total_float_days"]
        a["is_critical"] = f["is_critical"]
        touch(a)
    version["projected_finish_date"] = fmt_dt(projected_finish)
    version["critical_path_activity_count"] = critical_count
    version["total_activities"] = len(acts)
    touch(version)


def clear_computed_activity_fields(version):
    """Schedule-reject side effect: clear computed Activity date/float fields."""
    for a in activities_of(version["id"]):
        a["early_start"] = None
        a["early_finish"] = None
        a["late_start"] = None
        a["late_finish"] = None
        a["total_float_days"] = None
        a["is_critical"] = None
        touch(a)


def creates_cycle(version_id, predecessor_id, successor_id):
    """True iff adding predecessor -> successor closes a directed cycle."""
    adj = {}
    for r in relationships_of(version_id):
        adj.setdefault(r["predecessor_activity_id"], []).append(
            r["successor_activity_id"])
    stack = [successor_id]
    seen = set()
    while stack:
        n = stack.pop()
        if n == predecessor_id:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj.get(n, []))
    return False
