"""Graph walks, freshness cascades and the two recomputed ledgers."""

import calc
import lookup
import store
from core import bps_share, clock
from errors import fail

LIVE_DECISIONS = ("ENDORSED", "CONDITIONED", "VETOED")
COMMITTED_STATUSES = ("PROGRAMMED", "GRANT_SUBMITTED", "AWARDED")


# ---------------------------------------------------------------------------
# acyclicity of the two dependency graphs
# ---------------------------------------------------------------------------

def walk_asset_chain(asset_id, upstream_id):
    """Walk upward from upstream_id; must reach null without revisiting asset_id.

    Returns the dependency depth (hops from asset_id to the root).
    """
    seen = {asset_id}
    depth = 0
    cursor = upstream_id
    while cursor is not None:
        if cursor in seen:
            fail("ERR_ASSET_DEPENDENCY_CYCLE", "The upstream dependency chain contains a cycle.")
        seen.add(cursor)
        depth += 1
        parent = store.assets.get(cursor)
        if parent is None:
            break
        cursor = parent.get("upstream_asset_id")
    return depth


def walk_project_chain(project_id, prerequisite_id):
    seen = {project_id}
    cursor = prerequisite_id
    while cursor is not None:
        if cursor in seen:
            fail(
                "ERR_PROJECT_PREREQUISITE_CYCLE",
                "The prerequisite chain contains a cycle.",
            )
        seen.add(cursor)
        parent = store.projects.get(cursor)
        if parent is None:
            break
        cursor = parent.get("prerequisite_project_id")


# ---------------------------------------------------------------------------
# PRD 3.2 -- the five-hop hazard republication cascade
# ---------------------------------------------------------------------------

def republication_cascade(profile):
    """Hops 2 through 5. Hop 1 is written by the caller before this runs."""
    # Hop 2: assessments computed against an older publication counter go STALE,
    # retaining their score and band as the stale reading.
    stale_asset_ids = []
    for row in store.ordered(store.assessments):
        if row["hazard_profile_id"] != profile["id"]:
            continue
        if row["status"] != "ASSESSED":
            continue
        if row["assessed_profile_version"] is None:
            continue
        if row["assessed_profile_version"] >= profile["published_version"]:
            continue
        row["status"] = "STALE"
        store.touch(row)
        stale_asset_ids.append(row["asset_id"])

    # Hop 3: the assets those assessments ranked lose their ranking outputs.
    recompute_asset_ids = []
    for asset_id in stale_asset_ids:
        asset = store.assets.get(asset_id)
        if asset is None or asset["criticality_status"] != "RANKED":
            continue
        asset["criticality_status"] = "RECOMPUTE_REQUIRED"
        asset["consequence_score"] = None
        asset["criticality_tier"] = None
        asset["dependency_depth"] = None
        store.touch(asset)
        recompute_asset_ids.append(asset_id)

    if not recompute_asset_ids:
        return

    affected = set(recompute_asset_ids)

    # Hop 4: certified analyses whose project links one of those assets go STALE.
    stale_project_ids = []
    for analysis in store.ordered(store.analyses):
        if analysis["status"] != "CERTIFIED":
            continue
        linked = {row["asset_id"] for row in lookup.links_of(analysis["project_id"])}
        if not (linked & affected):
            continue
        analysis["status"] = "STALE"
        analysis["stale_reason"] = "ASSET_RECOMPUTE"
        store.touch(analysis)
        project = store.projects.get(analysis["project_id"])
        if project is not None and project["analysis_status"] == "BCA_CERTIFIED":
            project["analysis_status"] = "BCA_STALE"
            store.touch(project)
            stale_project_ids.append(project["id"])

    # Hop 5: an open endorsement round on a cycle owning one of those projects is
    # pushed back into REVISION, or fails outright when the budget is spent.
    cycle_ids = []
    for project_id in stale_project_ids:
        project = store.projects.get(project_id)
        if project is None:
            continue
        if project["plan_cycle_id"] not in cycle_ids:
            cycle_ids.append(project["plan_cycle_id"])
    for cycle_id in cycle_ids:
        cycle = store.plan_cycles.get(cycle_id)
        if cycle is None or cycle["status"] != "ENDORSEMENT_ROUND":
            continue
        supersede_live_endorsements(cycle)
        if cycle["revision_count"] + 1 <= cycle["max_revision_rounds"]:
            cycle["status"] = "REVISION"
            cycle["revision_count"] += 1
        else:
            cycle["status"] = "FAILED"
            fail_cycle_side_effects(cycle)
        store.touch(cycle)


# ---------------------------------------------------------------------------
# PRD 3.8 -- endorsement supersession and the FAILED cascade
# ---------------------------------------------------------------------------

def supersede_live_endorsements(cycle):
    for row in lookup.endorsements_of_cycle(cycle["id"], cycle["round_number"]):
        if row["decision"] in LIVE_DECISIONS:
            row["decision"] = "SUPERSEDED"
            store.touch(row)


def fail_cycle_side_effects(cycle):
    """Cancel scheduled sessions and screen out unprogrammed screened-in projects."""
    for row in lookup.sessions_of_cycle(cycle["id"]):
        if row["status"] == "SCHEDULED":
            row["status"] = "CANCELLED"
            store.touch(row)
    for row in lookup.projects_of_cycle(cycle["id"]):
        if row["screening_status"] == "SCREENED_IN" and row["program_status"] == "UNPROGRAMMED":
            row["screening_status"] = "SCREENED_OUT"
            store.touch(row)


# ---------------------------------------------------------------------------
# PRD 3.7 -- the capital program ledger, recomputed from scratch
# ---------------------------------------------------------------------------

def recompute_program_ledger(program, skip_touch=()):
    rows = [
        row for row in lookup.projects_of_program(program["id"])
        if row["program_status"] in COMMITTED_STATUSES
    ]
    committed = sum(int(row["allocated_cents"] or 0) for row in rows)
    available = int(program["authorized_cents"]) - committed
    equity_committed = 0
    for row in rows:
        share = row.get("equity_benefit_share_bps")
        if share is not None and int(share) >= int(program["equity_target_bps"]):
            equity_committed += int(row["allocated_cents"] or 0)
    program["committed_cents"] = committed
    program["available_cents"] = available
    program["equity_committed_cents"] = equity_committed
    program["equity_achieved_bps"] = 0 if committed == 0 else bps_share(equity_committed, committed)
    program["funding_posture"] = calc.funding_posture(available, program["authorized_cents"])

    # A CLOSED posture puts every PROGRAMMED project of the program on grant hold;
    # leaving CLOSED clears the flag again on every PROGRAMMED sibling.
    hold = program["funding_posture"] == "CLOSED"
    for row in lookup.projects_of_program(program["id"]):
        if row["program_status"] != "PROGRAMMED":
            continue
        if bool(row["grant_hold_flag"]) == hold:
            continue
        row["grant_hold_flag"] = hold
        if row["id"] not in skip_touch:
            store.touch(row)


# ---------------------------------------------------------------------------
# PRD 3.9 -- the mutual aid pact ledger
# ---------------------------------------------------------------------------

def active_commitment_windows(pact_id, extra=None):
    windows = [
        (row["window_start"], row["window_end"], row["committed_units"])
        for row in lookup.commitments_of_pact(pact_id, ("COMMITTED", "FULFILLED"))
    ]
    if extra is not None:
        windows.append(extra)
    return windows


def recompute_pact_ledger(pact):
    reserved = calc.peak_unit_load(active_commitment_windows(pact["id"]))
    pact["reserved_units"] = reserved
    pact["free_units"] = int(pact["pledged_units"]) - reserved
    pact["status"] = derive_pact_status(pact)


def derive_pact_status(pact):
    """EXPIRED first -- the temporal check runs before any capacity consideration."""
    if clock.now() >= pact["window_end"]:
        return "EXPIRED"
    if int(pact["free_units"]) == 0:
        return "EXHAUSTED"
    return "OPEN"
