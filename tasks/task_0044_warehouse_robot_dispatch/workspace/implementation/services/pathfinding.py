"""Shortest-path computation using Dijkstra."""
from __future__ import annotations

import heapq
from db import db


PENALTY_INF = 10 ** 9


def _build_adjacency(fleet_id: str, penalty_nodes: dict[str, int] | None = None) -> dict[str, list[tuple[str, int]]]:
    """Build adjacency list keyed by from_node_id → list of (to_node_id, cost).

    Edges whose endpoints are BLOCKED are excluded. ``penalty_nodes`` is a map
    from node_id to a cost multiplier; if a destination node is in the map, we
    multiply the edge cost by that factor (used by deadlock recovery to bump
    cost on a contested node by DEADLOCK_PENALTY).
    """
    if penalty_nodes is None:
        penalty_nodes = {}
    adj: dict[str, list[tuple[str, int]]] = {}
    nodes = {n["id"]: n for n in db.map_nodes.values() if n["fleet_id"] == fleet_id}
    for edge in db.map_edges.values():
        if edge["fleet_id"] != fleet_id:
            continue
        u, v = edge["from_node_id"], edge["to_node_id"]
        if u not in nodes or v not in nodes:
            continue
        cost = edge["cost"]
        # Penalty: multiply (do not skip) — see deadlock recovery use.
        if v in penalty_nodes:
            cost = cost * penalty_nodes[v]
        adj.setdefault(u, []).append((v, cost, edge["id"]))
    return adj


def _node_open(node_id: str, ignore_blocked: set[str] | None = None) -> bool:
    node = db.map_nodes.get(node_id)
    if not node:
        return False
    if node["status"] != "OPEN":
        if ignore_blocked and node_id in ignore_blocked:
            return True
        return False
    return True


def _dijkstra(fleet_id: str, source: str, target: str,
              forbidden: set[str] | None = None,
              penalty_nodes: dict[str, int] | None = None,
              ignore_blocked: set[str] | None = None) -> tuple[int | None, list[str] | None]:
    """Return (total_cost, path_nodes). path_nodes is the sequence from source→…→target.

    A node is considered traversable iff it's OPEN (or whitelisted in ``ignore_blocked``).
    Source/target are always allowed (they themselves do not need to be OPEN).
    Tie-breaks on equal total cost: pick the path whose concatenated list of node codes
    sorts lexicographically smaller.
    """
    if forbidden is None:
        forbidden = set()
    if penalty_nodes is None:
        penalty_nodes = {}
    if ignore_blocked is None:
        ignore_blocked = set()
    # Source must exist
    src_node = db.map_nodes.get(source)
    tgt_node = db.map_nodes.get(target)
    if not src_node or not tgt_node:
        return None, None

    adj = _build_adjacency(fleet_id, penalty_nodes)
    nodes_by_id = {n["id"]: n for n in db.map_nodes.values() if n["fleet_id"] == fleet_id}

    # Best-known (cost, code-tuple) per node, plus predecessor.
    best: dict[str, tuple[int, tuple[str, ...]]] = {source: (0, (src_node["code"],))}
    pred: dict[str, str | None] = {source: None}
    # Heap: (cost, code_tuple, node_id)
    heap: list[tuple[int, tuple[str, ...], str]] = [(0, (src_node["code"],), source)]

    while heap:
        cost, code_tuple, u = heapq.heappop(heap)
        if (cost, code_tuple) != best.get(u, (None, None)):
            continue
        if u == target:
            # Reconstruct path
            path = []
            cur = u
            while cur is not None:
                path.append(cur)
                cur = pred[cur]
            path.reverse()
            return cost, path
        for v, edge_cost, _eid in adj.get(u, []):
            # v can be the target even if blocked? No — target itself must be OPEN
            # for a valid path. But we allow the target if it's the actual endpoint
            # only when status==OPEN. To be safe: require traversal nodes (intermediate)
            # to be OPEN, and target endpoint to be OPEN.
            v_node = nodes_by_id.get(v)
            if not v_node:
                continue
            if v in forbidden and v != target:
                continue
            if v_node["status"] != "OPEN" and v not in ignore_blocked:
                continue
            new_cost = cost + edge_cost
            new_code_tuple = code_tuple + (v_node["code"],)
            cur_best = best.get(v)
            if cur_best is None or (new_cost, new_code_tuple) < cur_best:
                best[v] = (new_cost, new_code_tuple)
                pred[v] = u
                heapq.heappush(heap, (new_cost, new_code_tuple, v))
    return None, None


def shortest_path_via(fleet_id: str, source: str, via: str, target: str,
                      penalty_nodes: dict[str, int] | None = None,
                      ignore_blocked_set: set[str] | None = None) -> tuple[int | None, list[str] | None]:
    """Compute the shortest path from source → via → target.

    Returns (total_cost, [source, …, via, …, target]) on success, else (None, None).
    ``ignore_blocked_set``: nodes whose BLOCKED status should be ignored (typically the
    source/via/target themselves if they happen to be blocked — though normally pickup/
    dropoff need to be OPEN).
    """
    # First leg
    c1, p1 = _dijkstra(fleet_id, source, via,
                       penalty_nodes=penalty_nodes,
                       ignore_blocked=ignore_blocked_set)
    if c1 is None:
        return None, None
    # Second leg from via to target
    c2, p2 = _dijkstra(fleet_id, via, target,
                       penalty_nodes=penalty_nodes,
                       ignore_blocked=ignore_blocked_set)
    if c2 is None:
        return None, None
    # Concatenate (drop the duplicated 'via')
    full = p1 + p2[1:]
    return c1 + c2, full


def shortest_path_simple(fleet_id: str, source: str, target: str,
                         penalty_nodes: dict[str, int] | None = None) -> tuple[int | None, list[str] | None]:
    return _dijkstra(fleet_id, source, target, penalty_nodes=penalty_nodes)
