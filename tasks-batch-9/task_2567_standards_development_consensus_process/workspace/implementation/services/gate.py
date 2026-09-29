"""Consensus gate evaluation (PRD 2.9).

The gate is never incrementally patched: it is recomputed from scratch by walking
the work item's appeals, its drafts and its sponsoring committee. The same walk
refreshes the work item's unresolved_negative_count.
"""

from core.store import touch

from . import graph

LIVE_APPEAL_STATES = ("FILED", "ACCEPTED_FOR_REVIEW")


def unresolved_negatives(work_item):
    """Votes reachable through the work item's drafts and their ballots that are
    still CAST, NEGATIVE and awaiting adjudication."""
    total = 0
    for vote in graph.votes_of_work_item(work_item):
        if (vote["status"] == "CAST" and vote["position"] == "NEGATIVE"
                and vote["adjudication_status"] == "PENDING"):
            total += 1
    return total


def evaluate(work_item):
    """Returns (gate, unresolved_negative_count) without writing anything."""
    blocked = False
    for appeal in graph.appeals_of(work_item):
        if appeal["status"] in LIVE_APPEAL_STATES:
            blocked = True
            break
    if not blocked:
        for draft in graph.drafts_of(work_item):
            if draft["status"] == "COMMENT_RESOLUTION":
                blocked = True
                break
    if not blocked:
        committee = graph.sponsoring_committee(work_item)
        if committee is not None and (
                committee["status"] != "ACTIVE"
                or committee["balance_status"] != "BALANCED"):
            blocked = True
    return ("BLOCKED" if blocked else "OPEN"), unresolved_negatives(work_item)


def recompute(work_item, bump=False):
    """Write the freshly derived gate and negative count. Returns True when a
    stored value actually changed."""
    gate, negatives = evaluate(work_item)
    changed = (work_item["consensus_gate"] != gate
               or work_item["unresolved_negative_count"] != negatives)
    work_item["consensus_gate"] = gate
    work_item["unresolved_negative_count"] = negatives
    if changed or bump:
        touch(work_item)
    return changed


def recompute_for_committee(committee):
    """Re-derive the gate on every work item this committee sponsors."""
    for work_item in graph.work_items_of_committee(committee):
        recompute(work_item)
