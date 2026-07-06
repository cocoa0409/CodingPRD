"""Domain helpers: lookups, calculations, ledger, and vote tally."""
from decimal import Decimal

from store import store
from util import err, round_half_up, touch

# Calculation constants
MIN_CONTINGENCY_PCT = Decimal("0.10")
OVERHEAD_PCT = Decimal("0.05")
RANK_MAX_POINTS = 10

COMMITTED_STATUSES = {"SELECTED", "IN_IMPLEMENTATION", "COMPLETED"}


# ---------------------------------------------------------------------------
# Existence lookups (raise the resource-specific 404)
# ---------------------------------------------------------------------------
def get_cycle(cid):
    c = store.budget_cycles.get(cid)
    if c is None:
        err("ERR_BUDGET_CYCLE_NOT_FOUND", 404, "Budget cycle not found.")
    return c


def get_category(cat_id):
    c = store.categories.get(cat_id)
    if c is None:
        err("ERR_CATEGORY_NOT_FOUND", 404, "Category not found.")
    return c


def get_resident(rid):
    r = store.residents.get(rid)
    if r is None:
        err("ERR_RESIDENT_NOT_FOUND", 404, "Resident not found.")
    return r


def get_proposal(pid):
    p = store.proposals.get(pid)
    if p is None:
        err("ERR_PROPOSAL_NOT_FOUND", 404, "Proposal not found.")
    return p


def get_ballot(bid):
    b = store.ballots.get(bid)
    if b is None:
        err("ERR_BALLOT_NOT_FOUND", 404, "Ballot not found.")
    return b


def get_milestone(mid):
    m = store.milestones.get(mid)
    if m is None:
        err("ERR_MILESTONE_NOT_FOUND", 404, "Milestone not found.")
    return m


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def categories_of(cycle_id):
    return [c for c in store.categories.values() if c["budget_cycle_id"] == cycle_id]


def proposals_of_cycle(cycle_id):
    return [p for p in store.proposals.values() if p["budget_cycle_id"] == cycle_id]


def proposals_of_category(cat_id):
    return [p for p in store.proposals.values() if p["category_id"] == cat_id]


def line_items_of(proposal_id):
    return [li for li in store.cost_line_items.values()
            if li["proposal_id"] == proposal_id]


def entries_of_ballot(ballot_id):
    return [e for e in store.ballot_entries.values() if e["ballot_id"] == ballot_id]


def entries_for_proposal(proposal_id):
    return [e for e in store.ballot_entries.values()
            if e["proposal_id"] == proposal_id]


def milestones_of(proposal_id):
    return [m for m in store.milestones.values() if m["proposal_id"] == proposal_id]


# ---------------------------------------------------------------------------
# Cost estimation (calculations.proposal_cost_estimate)
# ---------------------------------------------------------------------------
def line_provisional(line):
    gross = line["unit_cost_cents"] * line["quantity"]
    c = Decimal(str(line.get("contingency_pct", 0) or 0))
    ceff = c if c > 0 else Decimal(0)
    return round_half_up(Decimal(gross) * (Decimal(1) + ceff))


def recompute_provisional(proposal):
    total = 0
    for line in line_items_of(proposal["id"]):
        line["line_provisional_cents"] = line_provisional(line)
        total += line["line_provisional_cents"]
    proposal["provisional_estimate_cents"] = total


def compute_final_estimate(proposal):
    subtotal = 0
    for line in line_items_of(proposal["id"]):
        gross = line["unit_cost_cents"] * line["quantity"]
        c = Decimal(str(line.get("contingency_pct", 0) or 0))
        ceff = c if c > MIN_CONTINGENCY_PCT else MIN_CONTINGENCY_PCT
        subtotal += round_half_up(Decimal(gross) * (Decimal(1) + ceff))
    final = round_half_up(Decimal(subtotal) * (Decimal(1) + OVERHEAD_PCT))
    return final


# ---------------------------------------------------------------------------
# Vote tally (calculations.vote_tally)
# ---------------------------------------------------------------------------
def entry_points(rank):
    if rank is None:
        return 0
    return max(0, RANK_MAX_POINTS - (rank - 1))


def recompute_vote_score(proposal):
    cycle = store.budget_cycles.get(proposal["budget_cycle_id"])
    method = cycle["voting_method"] if cycle else None
    score = 0
    for e in entries_for_proposal(proposal["id"]):
        if not e.get("active"):
            continue
        ballot = store.ballots.get(e["ballot_id"])
        if not ballot or ballot["status"] != "CAST":
            continue
        if method == "RANKED":
            score += e.get("points", 0)
        else:  # ALLOCATION
            score += e.get("allocated_cents") or 0
    if score != proposal.get("vote_score", 0):
        proposal["vote_score"] = score
        touch(proposal)


# ---------------------------------------------------------------------------
# Budget ledger (calculations.cycle_budget_ledger)
# ---------------------------------------------------------------------------
def recompute_ledger(cycle):
    total_committed = 0
    for cat in categories_of(cycle["id"]):
        committed = sum(
            p["awarded_cents"] for p in proposals_of_category(cat["id"])
            if p["status"] in COMMITTED_STATUSES
        )
        remaining = cat["category_budget_cap_cents"] - committed
        if committed != cat.get("committed_cents") or remaining != cat.get("remaining_cap_cents"):
            cat["committed_cents"] = committed
            cat["remaining_cap_cents"] = remaining
            touch(cat)
        total_committed += cat["committed_cents"]
    uncommitted = cycle["total_budget_cents"] - total_committed
    if total_committed != cycle.get("total_committed_cents") or uncommitted != cycle.get("uncommitted_cents"):
        cycle["total_committed_cents"] = total_committed
        cycle["uncommitted_cents"] = uncommitted
        touch(cycle)
