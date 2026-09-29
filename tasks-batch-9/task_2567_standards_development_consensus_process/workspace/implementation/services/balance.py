"""Committee balance arithmetic (PRD 2.6) and the seat-drop cascade (PRD 3.1).

The inputs are always CommitteeMembership rows and the category read is always
the interest_category SNAPSHOTTED on the seat, never the participant's current
one. Percentages are rounded to one decimal before any threshold comparison and
every comparison is inclusive.
"""

from core.store import touch
from core.util import lte, pct1

from . import gate, graph

BALANCED_MIN_MEMBERS = 3
BALANCED_MIN_CATEGORIES = 3
BALANCED_MAX_DOMINANCE = "50.0"
PROVISIONAL_MIN_MEMBERS = 3
PROVISIONAL_MIN_CATEGORIES = 2
PROVISIONAL_MAX_DOMINANCE = "66.7"


def evaluate(seats):
    """Run the five ordered steps over a seat basis."""
    member_count = len(seats)
    category_counts = {}
    for seat in seats:
        key = seat["interest_category"]
        category_counts[key] = category_counts.get(key, 0) + 1
    distinct_category_count = len([k for k, v in category_counts.items() if v >= 1])
    largest_category_count = max(category_counts.values()) if category_counts else 0
    if member_count == 0:
        dominance_pct = 0.0
    else:
        dominance_pct = pct1(largest_category_count, member_count)

    if (member_count >= BALANCED_MIN_MEMBERS
            and distinct_category_count >= BALANCED_MIN_CATEGORIES
            and lte(dominance_pct, BALANCED_MAX_DOMINANCE)):
        verdict = "BALANCED"
    elif (member_count >= PROVISIONAL_MIN_MEMBERS
            and distinct_category_count >= PROVISIONAL_MIN_CATEGORIES
            and lte(dominance_pct, PROVISIONAL_MAX_DOMINANCE)):
        verdict = "PROVISIONAL"
    else:
        verdict = "UNBALANCED"

    return {
        "verdict": verdict,
        "member_count": member_count,
        "category_counts": category_counts,
        "distinct_category_count": distinct_category_count,
        "largest_category_count": largest_category_count,
        "dominance_pct": dominance_pct,
    }


def voting_basis(committee):
    return evaluate(graph.voting_seats(committee))


def roster_basis(committee):
    return evaluate(graph.roster_seats(committee))


def recompute(committee):
    """Persist both bases. Returns True when any stored value changed."""
    voting = voting_basis(committee)
    roster = roster_basis(committee)
    before = (
        committee.get("balance_status"), committee.get("active_member_count"),
        committee.get("dominance_pct"), committee.get("distinct_category_count"),
        committee.get("category_counts"), committee.get("roster_balance_status"),
        committee.get("roster_member_count"), committee.get("roster_dominance_pct"),
    )
    committee["balance_status"] = voting["verdict"]
    committee["active_member_count"] = voting["member_count"]
    committee["dominance_pct"] = voting["dominance_pct"]
    committee["distinct_category_count"] = voting["distinct_category_count"]
    committee["category_counts"] = voting["category_counts"]
    committee["roster_balance_status"] = roster["verdict"]
    committee["roster_member_count"] = roster["member_count"]
    committee["roster_dominance_pct"] = roster["dominance_pct"]
    after = (
        committee["balance_status"], committee["active_member_count"],
        committee["dominance_pct"], committee["distinct_category_count"],
        committee["category_counts"], committee["roster_balance_status"],
        committee["roster_member_count"], committee["roster_dominance_pct"],
    )
    return before != after


def refresh_open_ballot_count(committee):
    """open_ballot_count counts the committee's ballots in OPEN or CLOSED."""
    count = 0
    for ballot in graph.ballots_of_committee(committee):
        if ballot["status"] in ("OPEN", "CLOSED"):
            count += 1
    changed = committee.get("open_ballot_count") != count
    committee["open_ballot_count"] = count
    return changed


def seat_change_cascade(committee):
    """The four-hop cascade a seat status change triggers.

    hop 1 recompute the counters, hop 2 suspend the committee when the voting
    verdict has dropped below BALANCED, hop 3 re-derive the gate of every work
    item it sponsors, hop 4 stamp a procedural hold on every OPEN ballot.
    """
    if recompute(committee):
        touch(committee)
    dropped = (committee["status"] == "ACTIVE"
               and committee["balance_status"] != "BALANCED")
    if dropped:
        committee["status"] = "SUSPENDED"
        touch(committee)
    gate.recompute_for_committee(committee)
    if dropped:
        for ballot in graph.ballots_of_committee(committee):
            if ballot["status"] == "OPEN" and ballot["hold_reason"] != "COMMITTEE_UNBALANCED":
                ballot["hold_reason"] = "COMMITTEE_UNBALANCED"
                touch(ballot)
    return dropped
