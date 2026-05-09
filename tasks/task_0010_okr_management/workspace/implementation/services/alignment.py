"""Alignment graph: cycle detection and impact scores."""

import db
from util import round4

ATTENUATION = 0.7
UPSTREAM_INFLUENCE = 0.5


def accepted_links():
    return [l for l in db.alignment_links.values() if l.get("status") == "ACCEPTED"]


def would_introduce_cycle(upstream_id: str, downstream_id: str) -> bool:
    """Test if adding edge upstream->downstream to the ACCEPTED graph creates a cycle.
    Equivalent: does a directed path already exist from downstream back to upstream
    via ACCEPTED links? Includes 2-cycles when reverse link is already ACCEPTED.
    """
    if upstream_id == downstream_id:
        return True
    # adjacency: u -> [d, ...]
    adj = {}
    for l in accepted_links():
        u = l["upstream_objective_id"]
        d = l["downstream_objective_id"]
        adj.setdefault(u, []).append(d)
    # DFS from downstream_id; if we reach upstream_id, accepting creates a cycle.
    stack = [downstream_id]
    seen = set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if node == upstream_id:
            return True
        for nxt in adj.get(node, []):
            if nxt not in seen:
                stack.append(nxt)
    return False


def count_accepted_upstreams(downstream_id: str) -> int:
    return sum(1 for l in accepted_links() if l.get("downstream_objective_id") == downstream_id)


def compute_forward_impact(link: dict) -> float:
    up = db.objectives.get(link["upstream_objective_id"])
    if not up:
        return 0.0
    return round4((up.get("progress") or 0.0) * ATTENUATION)


def compute_backward_impact(link: dict) -> float:
    down = db.objectives.get(link["downstream_objective_id"])
    if not down:
        return 0.0
    n = count_accepted_upstreams(link["downstream_objective_id"])
    if n == 0:
        return 0.0
    return round4((down.get("progress") or 0.0) * UPSTREAM_INFLUENCE / n)


def recompute_link_impact(link: dict):
    if link.get("status") != "ACCEPTED":
        link["forward_impact_score"] = None
        link["backward_impact_score"] = None
        return
    link["forward_impact_score"] = compute_forward_impact(link)
    link["backward_impact_score"] = compute_backward_impact(link)
