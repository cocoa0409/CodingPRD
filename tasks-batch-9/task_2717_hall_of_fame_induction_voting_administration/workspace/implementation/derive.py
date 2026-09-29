"""Derived counters and readiness propagation (PRD 2.9, 3.9).

Every derived counter here is re-derived from its contributing rows -- never
patched from a stale value.  A cascade that changes a row refreshes that row's
updated_at and bumps its version by 1; a cascade that changes nothing changes
no version.
"""
from decimal import Decimal

import clock
import db

CYCLE_ROSTER_PHASES = ("NOMINATIONS_OPEN", "SCREENING", "BALLOTING")

AUSTERITY_REDUCED_AT = Decimal("0.50")
AUSTERITY_MINIMAL_AT = Decimal("0.80")


# --------------------------------------------------------------- cycle counters


def credentialed_roster_size():
    instant = clock.now()
    total = 0
    for row in db.electors.values():
        if row["status"] == "CREDENTIALED" and row["credential_expires_on"] >= instant:
            total += 1
    return total


def austerity_tier_for(committed, budget):
    if budget is None or budget <= 0:
        ratio = Decimal(0) if not committed else Decimal(10)
    else:
        ratio = Decimal(committed) / Decimal(budget)
    if ratio < AUSTERITY_REDUCED_AT:
        return "FULL"
    if ratio < AUSTERITY_MINIMAL_AT:
        return "REDUCED"
    return "MINIMAL"


def cycle_counters(cycle):
    """Return the freshly derived counter values for a cycle."""
    cid = cycle["id"]
    nomination_count = 0
    advanced = 0
    special_used = 0
    for row in db.candidacies.values():
        if row["cycle_id"] != cid:
            continue
        nomination_count += 1
        if row["status"] in ("ADVANCED", "ON_BALLOT"):
            advanced += 1
        if row["pathway"] == "SPECIAL" and row["status"] != "REJECTED":
            special_used += 1

    committed = 0
    for grant in db.travel_grants.values():
        if grant["cycle_id"] == cid and grant["status"] == "APPROVED":
            committed += grant["award_cents"]

    induction_count = 0
    ready_count = 0
    for row in db.inductions.values():
        if row["cycle_id"] != cid:
            continue
        induction_count += 1
        if row["ceremony_ready"]:
            ready_count += 1

    return {
        "nomination_count": nomination_count,
        "advanced_candidacy_count": advanced,
        "special_election_used": special_used,
        "travel_committed_cents": committed,
        "induction_count": induction_count,
        "ceremony_ready_count": ready_count,
        "austerity_tier": austerity_tier_for(committed, cycle["travel_budget_cents"]),
    }


def recompute_cycle(cycle, bump=True, include_roster=False):
    """Re-derive every counter of a cycle.  Returns True when anything changed."""
    fresh = cycle_counters(cycle)
    if include_roster:
        fresh["credentialed_roster_count"] = credentialed_roster_size()
    changed = False
    for key, value in fresh.items():
        if cycle.get(key) != value:
            cycle[key] = value
            changed = True
    if changed and bump:
        db.touch(cycle)
    return changed


def recompute_roster_counts_everywhere():
    """Credential / suspension / reinstatement recompute credentialed_roster_count
    for every cycle in NOMINATIONS_OPEN, SCREENING or BALLOTING."""
    size = credentialed_roster_size()
    for cycle in db.cycles.values():
        if cycle["status"] in CYCLE_ROSTER_PHASES and cycle["credentialed_roster_count"] != size:
            cycle["credentialed_roster_count"] = size
            db.touch(cycle)


def recompute_bloc(bloc):
    """seats_filled tracks every elector of the bloc whose status is
    CREDENTIALED or SUSPENDED.  VoterBloc carries no version to bump."""
    total = 0
    for row in db.electors.values():
        if row["bloc_id"] == bloc["id"] and row["status"] in ("CREDENTIALED", "SUSPENDED"):
            total += 1
    bloc["seats_filled"] = total
    return total


def recompute_all_blocs():
    for bloc in db.voter_blocs.values():
        recompute_bloc(bloc)


# -------------------------------------------------------------- ballot counters


def slots_of(ballot_id):
    return db.creation_order([s for s in db.ballot_slots.values() if s["ballot_id"] == ballot_id])


def counted_submissions_of(ballot_id):
    rows = [
        s
        for s in db.vote_submissions.values()
        if s["ballot_id"] == ballot_id and s["status"] == "COUNTED"
    ]
    return sorted(rows, key=lambda r: (r["cast_at"], r["created_at"], r["_seq"]))


def recompute_ballot_counters(ballot, bump=False):
    """slot_count, ballots_cast and total_selections_counted are definitional
    counts over their contributing rows."""
    slots = slots_of(ballot["id"])
    slot_count = len([s for s in slots if s["status"] != "STRUCK"])
    counted = counted_submissions_of(ballot["id"])
    struck_ids = set(s["id"] for s in slots if s["status"] == "STRUCK")
    total_selections = 0
    for sub in counted:
        total_selections += len([sid for sid in sub["selected_slot_ids"] if sid not in struck_ids])
    changed = False
    for key, value in (
        ("slot_count", slot_count),
        ("ballots_cast", len(counted)),
        ("total_selections_counted", total_selections),
    ):
        if ballot[key] != value:
            ballot[key] = value
            changed = True
    if changed and bump:
        db.touch(ballot)
    return changed


def recompute_slot_votes(ballot):
    """Slot vote figures over the surviving COUNTED submissions."""
    counted = counted_submissions_of(ballot["id"])
    cast = len(counted)
    for slot in slots_of(ballot["id"]):
        if slot["status"] == "STRUCK":
            if slot["votes_received"] != 0 or slot["vote_pct"] != 0:
                slot["votes_received"] = 0
                slot["vote_pct"] = 0.0
                db.touch(slot)
            continue
        votes = len([s for s in counted if slot["id"] in s["selected_slot_ids"]])
        pct = 0.0 if cast == 0 else round_half_up_pct(votes, cast)
        if slot["votes_received"] != votes or slot["vote_pct"] != pct:
            slot["votes_received"] = votes
            slot["vote_pct"] = pct
            db.touch(slot)


def round_half_up_pct(numerator, denominator):
    from decimal import ROUND_HALF_UP

    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(value)


# ----------------------------------------------------------- induction readiness


def compute_ceremony_ready(induction):
    travel_ok = induction["travel_status"] in ("APPROVED", "WAIVED")
    display_ok = (
        induction["artifact_status"] == "RECEIVED" and induction["exhibit_status"] == "INSTALLED"
    ) or induction["artifact_status"] == "EXEMPT"
    return bool(travel_ok and display_ok)


def refresh_induction_readiness(induction):
    """Re-derived from scratch on every mutation of any of the three dimensions."""
    ready = compute_ceremony_ready(induction)
    if induction["ceremony_ready"] != ready:
        induction["ceremony_ready"] = ready
        return True
    return False


def refresh_cycle_ready_count(cycle):
    if cycle is None:
        return False
    total = 0
    count = 0
    for row in db.inductions.values():
        if row["cycle_id"] != cycle["id"]:
            continue
        total += 1
        if row["ceremony_ready"]:
            count += 1
    changed = False
    if cycle["induction_count"] != total:
        cycle["induction_count"] = total
        changed = True
    if cycle["ceremony_ready_count"] != count:
        cycle["ceremony_ready_count"] = count
        changed = True
    return changed


def ballots_of(cycle_id):
    return db.creation_order([b for b in db.ballots.values() if b["cycle_id"] == cycle_id])


def newest_ballot_of(cycle_id):
    rows = ballots_of(cycle_id)
    return rows[-1] if rows else None


def candidacies_of(cycle_id):
    return db.creation_order([c for c in db.candidacies.values() if c["cycle_id"] == cycle_id])


def inductions_of(cycle_id):
    return db.creation_order([i for i in db.inductions.values() if i["cycle_id"] == cycle_id])


def roster_at(instant):
    """Elector rows CREDENTIALED with credential_expires_on at or after instant."""
    total = 0
    for row in db.electors.values():
        if row["status"] == "CREDENTIALED" and row["credential_expires_on"] >= instant:
            total += 1
    return total
