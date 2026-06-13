"""Genealogy graph helpers (PRD §2.5, §3.6, §3.9).

The genealogy is a DAG: an edge (source_lot -> finished_lot) exists exactly when
a ConsumedLot line of a FINALIZED run links them. These helpers compute:
  - immediate one-up source lots of a lot,
  - immediate one-down finished lots of a lot,
  - the transitive one-down closure of finished lots downstream of a lot.

Traversal order over children is: ConsumedLot.created_at ASC then Lot.created_at
ASC; never by identifier.
"""
from __future__ import annotations

import db
from services.common import created_sort_key


def _finalized_edges():
    """Yield (source_lot_id, finished_lot_id, consumed_lot_rec) for every edge
    contributed by a FINALIZED run, ordered by ConsumedLot.created_at ASC then
    by finished Lot.created_at ASC."""
    edges = []
    for cl in db.consumed_lots.values():
        run = db.production_runs.get(cl["production_run_id"])
        if not run or run.get("status") != "FINALIZED":
            continue
        finished_lot_id = run.get("output_lot_id")
        if not finished_lot_id:
            continue
        edges.append((cl["source_lot_id"], finished_lot_id, cl))
    # Order children by ConsumedLot.created_at ASC then Lot.created_at ASC.
    def _key(e):
        cl = e[2]
        fl = db.lots.get(e[1], {})
        return (cl.get("created_at", ""), cl.get("_seq", 0),
                fl.get("created_at", ""), fl.get("_seq", 0))
    edges.sort(key=_key)
    return edges


def one_up_source_lot_ids(lot_id: str) -> list[str]:
    """Immediate source lots one hop up from the lot — the direct ConsumedLot
    parents of the recalled (finished) lot. Empty for a RAW_MATERIAL lot."""
    lot = db.lots.get(lot_id)
    if not lot or lot.get("lot_kind") != "FINISHED":
        return []
    run_id = None
    for run in db.production_runs.values():
        if run.get("output_lot_id") == lot_id and run.get("status") == "FINALIZED":
            run_id = run["id"]
            break
    if run_id is None:
        return []
    lines = [cl for cl in db.consumed_lots.values() if cl["production_run_id"] == run_id]
    lines.sort(key=lambda cl: (cl.get("created_at", ""), cl.get("_seq", 0)))
    seen = []
    for cl in lines:
        if cl["source_lot_id"] not in seen:
            seen.append(cl["source_lot_id"])
    return seen


def immediate_downstream(lot_id: str, edges) -> list[str]:
    """Finished lots directly downstream of lot_id, in traversal order."""
    out = []
    for src, fin, _cl in edges:
        if src == lot_id and fin not in out:
            out.append(fin)
    return out


def downstream_finished_closure(lot_id: str) -> list[str]:
    """Transitive closure of FINISHED lots reachable downstream from lot_id.

    Does NOT include lot_id itself. Order: first-discovered order under a BFS/DFS
    that visits children by ConsumedLot.created_at ASC then Lot.created_at ASC.
    """
    edges = _finalized_edges()
    result: list[str] = []
    visited: set[str] = set()

    def visit(node: str):
        for child in immediate_downstream(node, edges):
            if child not in visited:
                visited.add(child)
                result.append(child)
                visit(child)

    visit(lot_id)
    return result


def covered_set(target_lot_id: str) -> list[str]:
    """Hold covered set: the target lot together with every finished lot
    transitively downstream of it (PRD §3.6). Order: target first, then the
    downstream closure in traversal order."""
    out = [target_lot_id]
    for fid in downstream_finished_closure(target_lot_id):
        if fid not in out:
            out.append(fid)
    return out


def controlling_allergen_code(facility_id: str, codes) -> str | None:
    """The code in `codes` of highest AllergenProfile.severity_rank; tie-break
    by lexicographically smallest code; null if the set is empty (PRD §3.1, §3.4).

    A code without a registered AllergenProfile contributes severity rank 0 so it
    only wins when no profiled code is present, still tie-broken by code ASC.
    """
    codes = list(dict.fromkeys(codes))  # distinct, preserve order
    if not codes:
        return None
    rank_by_code = {}
    for ap in db.allergen_profiles.values():
        if ap.get("facility_id") == facility_id:
            rank_by_code[ap["code"]] = ap["severity_rank"]
    best = None
    best_rank = None
    for c in codes:
        r = rank_by_code.get(c, 0)
        if best is None or r > best_rank or (r == best_rank and c < best):
            best = c
            best_rank = r
    return best
