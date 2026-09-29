"""Genealogy navigation and cascading recomputation (PRD section 2.10)."""

from common import touch
from db import db


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def children_of(consultant_id):
    return by_created(
        [c for c in db.consultants.values() if c.get("sponsor_consultant_id") == consultant_id]
    )


def descendants_with_level(consultant_id):
    """Breadth-first list of (consultant_row, genealogical_level) at unlimited depth."""
    result = []
    frontier = [(child, 1) for child in children_of(consultant_id)]
    while frontier:
        node, level = frontier.pop(0)
        result.append((node, level))
        for child in children_of(node["id"]):
            frontier.append((child, level + 1))
    return result


def path_between(earner_id, descendant):
    """Identifiers strictly between the earner and the descendant, top down."""
    path = descendant.get("upline_path") or []
    if earner_id in path:
        return path[path.index(earner_id) + 1:]
    return list(path)


def recompute_direct_downline_count(consultant_id):
    if consultant_id is None:
        return
    consultant = db.consultants.get(consultant_id)
    if consultant is None:
        return
    count = len(
        [
            c
            for c in db.consultants.values()
            if c.get("sponsor_consultant_id") == consultant_id and c.get("status") != "TERMINATED"
        ]
    )
    if consultant.get("direct_downline_count") != count:
        consultant["direct_downline_count"] = count
        touch(consultant)


def recompute_subtree_paths(consultant_id, bump_self=True):
    """Recompute upline_path/genealogy_depth for a consultant and every descendant."""
    consultant = db.consultants.get(consultant_id)
    if consultant is None:
        return
    sponsor_id = consultant.get("sponsor_consultant_id")
    if sponsor_id is None:
        new_path = []
    else:
        sponsor = db.consultants.get(sponsor_id)
        new_path = list(sponsor.get("upline_path") or []) + [sponsor_id] if sponsor else []
    changed = consultant.get("upline_path") != new_path
    consultant["upline_path"] = new_path
    consultant["genealogy_depth"] = len(new_path)
    if changed and bump_self:
        touch(consultant)
    for child in children_of(consultant_id):
        recompute_subtree_paths(child["id"], bump_self=True)
