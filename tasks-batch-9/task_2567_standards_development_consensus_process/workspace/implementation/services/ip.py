"""Patent clearance evaluation (PRD 3.7).

ip_status is derived, first match wins:
  1. any blocking disclosure                     -> IP_BLOCKED
  2. the call for patents is closed              -> IP_CLEARED
  3. no disclosures at all                       -> IP_PENDING
  4. otherwise                                   -> IP_DISCLOSED
"""

from core.store import touch

from . import graph

BLOCKING_ESSENTIALITY = ("ESSENTIAL", "POTENTIALLY_ESSENTIAL")
BLOCKING_STATUS = ("DISCLOSED_NO_COMMITMENT", "REFUSED")
CALL_CLOSED_STATES = (
    "CONSENSUS_APPROVED", "PUBLISHED", "UNDER_PERIODIC_REVIEW", "REAFFIRMED",
)


def blocks_publication(disclosure):
    return (disclosure["essentiality"] in BLOCKING_ESSENTIALITY
            and disclosure["status"] in BLOCKING_STATUS)


def refresh_flag(disclosure):
    disclosure["blocks_publication"] = blocks_publication(disclosure)
    return disclosure["blocks_publication"]


def call_for_patents_closed(work_item):
    return work_item["progress_status"] in CALL_CLOSED_STATES


def evaluate(work_item):
    disclosures = graph.disclosures_of(work_item)
    for disclosure in disclosures:
        if blocks_publication(disclosure):
            return "IP_BLOCKED"
    if call_for_patents_closed(work_item):
        return "IP_CLEARED"
    if not disclosures:
        return "IP_PENDING"
    return "IP_DISCLOSED"


def recompute(work_item):
    """Rewrite ip_status from scratch. Returns True when it changed."""
    for disclosure in graph.disclosures_of(work_item):
        refresh_flag(disclosure)
    status = evaluate(work_item)
    changed = work_item["ip_status"] != status
    work_item["ip_status"] = status
    if changed:
        touch(work_item)
    return changed
