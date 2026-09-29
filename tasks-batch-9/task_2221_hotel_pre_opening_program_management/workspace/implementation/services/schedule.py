"""calculations.critical_path_schedule (PRD §3.3)."""
from datetime import timedelta

import clock
import repo
from errors import ApiError

OPTIMISTIC = "OPTIMISTIC"
COMMITTED = "COMMITTED"


def _index(milestones, deps):
    by_id = {m["id"]: m for m in milestones}
    incoming = {m["id"]: [] for m in milestones}
    outgoing = {m["id"]: [] for m in milestones}
    for dep in deps:
        incoming[dep["successor_milestone_id"]].append(dep)
        outgoing[dep["predecessor_milestone_id"]].append(dep)
    return by_id, incoming, outgoing


def topological_order(milestones, deps):
    """Kahn's algorithm. Ready frontier popped by planned_start_date ASC then
    created_at ASC. A stuck frontier means a cycle."""
    by_id, incoming, outgoing = _index(milestones, deps)
    indegree = {mid: len(incoming[mid]) for mid in by_id}
    frontier = [mid for mid in by_id if indegree[mid] == 0]
    order = []
    while frontier:
        frontier.sort(key=lambda mid: (by_id[mid]["planned_start_date"],
                                       by_id[mid]["created_at"],
                                       by_id[mid]["_seq"]))
        mid = frontier.pop(0)
        order.append(mid)
        for dep in outgoing[mid]:
            succ = dep["successor_milestone_id"]
            indegree[succ] -= 1
            if indegree[succ] == 0:
                frontier.append(succ)
    if len(order) != len(milestones):
        raise ApiError("ERR_DEPENDENCY_CYCLE")
    return order, by_id, incoming, outgoing


def has_cycle(milestones, deps):
    try:
        topological_order(milestones, deps)
    except ApiError:
        return True
    return False


def _effective_duration(milestone, program, variant):
    if variant == COMMITTED:
        return milestone["duration_days"] + milestone["blocked_days_accrued"]
    return milestone["duration_days"]


def _forward(order, by_id, incoming, program, variant):
    root = clock.parse_date_strict(program["construction_start_date"])
    es_map = {}
    ef_map = {}
    for mid in order:
        milestone = by_id[mid]
        edges = incoming[mid]
        if not edges:
            es = root
        else:
            candidates = []
            for dep in edges:
                pred = by_id[dep["predecessor_milestone_id"]]
                if dep["dependency_type"] == "FINISH_START":
                    base = ef_map[pred["id"]]
                else:
                    base = es_map[pred["id"]]
                candidate = base + timedelta(days=dep["lag_days"])
                if variant == COMMITTED and pred["rework_count"] > 0:
                    candidate = candidate + timedelta(days=program["rework_buffer_days"])
                candidates.append(candidate)
            es = max(candidates)
        # Actuals, once stamped, override the plan -- the test is on the date
        # fields, not on `state`.
        if milestone["actual_start_date"]:
            es = clock.parse_date_strict(milestone["actual_start_date"])
        if milestone["actual_finish_date"]:
            extra = milestone["blocked_days_accrued"] if variant == COMMITTED else 0
            ef = clock.parse_date_strict(milestone["actual_finish_date"]) + timedelta(days=extra)
        else:
            ef = es + timedelta(days=_effective_duration(milestone, program, variant))
        es_map[mid] = es
        ef_map[mid] = ef
    return es_map, ef_map


def _backward(order, by_id, outgoing, program, es_c, ef_c, project_finish):
    lf_map = {}
    for mid in reversed(order):
        milestone = by_id[mid]
        edges = outgoing[mid]
        rework_allowance = program["rework_buffer_days"] if milestone["rework_count"] > 0 else 0
        if not edges:
            lf = project_finish
        else:
            eff = _effective_duration(milestone, program, COMMITTED)
            candidates = []
            for dep in edges:
                succ = dep["successor_milestone_id"]
                candidate = (es_c[succ]
                             - timedelta(days=dep["lag_days"])
                             - timedelta(days=rework_allowance))
                if dep["dependency_type"] == "START_START":
                    candidate = candidate + timedelta(days=eff)
                candidates.append(candidate)
            lf = min(candidates)
        lf_map[mid] = lf
    return lf_map


def compute(program):
    """Run both variants and persist the results. Raises ERR_SCHEDULE_EMPTY /
    ERR_DEPENDENCY_CYCLE."""
    milestones = repo.milestones_of(program["id"])
    if not milestones:
        raise ApiError("ERR_SCHEDULE_EMPTY")
    deps = repo.dependencies_of_program(program["id"])
    order, by_id, incoming, outgoing = topological_order(milestones, deps)

    es_o, ef_o = _forward(order, by_id, incoming, program, OPTIMISTIC)
    es_c, ef_c = _forward(order, by_id, incoming, program, COMMITTED)

    finish_o = max(ef_o.values())
    finish_c = max(ef_c.values())
    lf_map = _backward(order, by_id, outgoing, program, es_c, ef_c, finish_c)

    critical = 0
    for mid in order:
        milestone = by_id[mid]
        total_float = (lf_map[mid] - ef_c[mid]).days
        milestone["earliest_start_date"] = clock.fmt_date(es_c[mid])
        milestone["earliest_finish_date"] = clock.fmt_date(ef_c[mid])
        milestone["latest_finish_date"] = clock.fmt_date(lf_map[mid])
        milestone["total_float_days"] = total_float
        milestone["is_critical"] = total_float == 0
        if total_float == 0:
            critical += 1

    projected_o = finish_o + timedelta(days=program["licensing_buffer_days"])
    projected_c = finish_c + timedelta(days=program["licensing_buffer_days"])
    target = clock.parse_date_strict(program["target_opening_date"])

    program["projected_opening_date_optimistic"] = clock.fmt_date(projected_o)
    program["projected_opening_date_committed"] = clock.fmt_date(projected_c)
    program["projected_opening_date"] = clock.fmt_date(projected_c)
    program["schedule_slip_days"] = max(0, (projected_c - target).days)
    program["critical_path_milestone_count"] = critical
    return program
