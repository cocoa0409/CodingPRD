"""Sales pipeline mechanics (PRD 3.8 and 3.9): unit sale standing, the
rescission window, closing-batch counters and the half-open settlement window.

The closing-batch window is half-open [start, end) and adjacency is allowed;
the warranty remediation window of 3.9 is a *different* geometry and is
handled by services/warranty.py.  The two rules never share a helper.
"""

import store
from rounding import pct2, ratio_pct

SECONDS_PER_DAY = 86400
RESCISSION_DAYS = {"OWNER_OCCUPANT": 15, "INVESTOR": 7}
CONTRACT_BASIS_STATUSES = ("SIGNED", "HARD", "CLOSED")
QUALIFYING_ESCROW_STATUSES = ("FUNDED", "DISBURSED")

OWNER_OCCUPANCY_MIN_PCT = pct2("50.00")
INVESTOR_CONCENTRATION_MAX_PCT = pct2("25.00")
SINGLE_INVESTOR_MAX_PCT = pct2("10.00")
PRESALE_SOLD_MIN_PCT = pct2("51.00")


def rescission_window_seconds(purchaser_type):
    return RESCISSION_DAYS[purchaser_type] * SECONDS_PER_DAY


def derive_unit_sale_status(unit):
    """`sale_status` is always derived from the unit's agreements."""
    statuses = {a["contract_status"] for a in store.unit_agreements(unit["id"])}
    if "CLOSED" in statuses:
        derived = "SOLD"
    elif "HARD" in statuses:
        derived = "HARD_CONTRACT"
    elif "SIGNED" in statuses:
        derived = "UNDER_CONTRACT"
    else:
        derived = "UNSOLD"
    if unit["sale_status"] != derived:
        unit["sale_status"] = derived
        store.touch(unit)
    return derived


def presale_sold_pct(project):
    included = store.included_units(project["id"])
    if not included:
        return pct2(0)
    sold = [u for u in included
            if u["sale_status"] in ("HARD_CONTRACT", "SOLD")]
    return ratio_pct(len(sold), len(included))


def batch_counters(batch, project):
    """`assigned` counts every agreement in the batch at any contract status;
    `qualifying` narrows to a contract at SIGNED, HARD or CLOSED whose escrow
    is FUNDED or DISBURSED."""
    agreements = store.batch_agreements(batch["id"])
    assigned = len(agreements)
    qualifying = len([
        a for a in agreements
        if a["contract_status"] in CONTRACT_BASIS_STATUSES
        and a["escrow_status"] in QUALIFYING_ESCROW_STATUSES
    ])
    included_count = len(store.included_units(project["id"]))
    presale = ratio_pct(qualifying, included_count) if included_count else pct2(0)
    return assigned, qualifying, presale


def write_batch_counters(batch, project):
    assigned, qualifying, presale = batch_counters(batch, project)
    if (batch["assigned_agreement_count"] != assigned
            or batch["qualifying_agreement_count"] != qualifying
            or batch["presale_pct"] != presale):
        batch["assigned_agreement_count"] = assigned
        batch["qualifying_agreement_count"] = qualifying
        batch["presale_pct"] = presale
        store.touch(batch)
    return assigned, qualifying, presale


def thresholds_met(batch):
    """Both clauses are inclusive, and the percentage comparison is made on
    the rounded two-decimal value."""
    return (batch["presale_pct"] >= batch["min_presale_threshold_pct"]
            and batch["qualifying_agreement_count"]
            >= batch["min_absolute_unit_count"])


def windows_overlap(new_start, new_end, other_start, other_end):
    """Half-open windows overlap exactly when the new start falls strictly
    before the other's end and the other's start falls strictly before the new
    end.  Both comparisons being strict makes a window starting at the instant
    a sibling ends acceptable."""
    return new_start < other_end and other_start < new_end


OCCUPYING_BATCH_STATUSES = ("DRAFT", "OPEN_FOR_ASSIGNMENT", "THRESHOLD_SHORT",
                            "THRESHOLD_MET", "RELEASED")


def batch_window_conflict(project_id, start_at, end_at, exclude_batch_id=None):
    for sibling in store.project_batches(project_id):
        if sibling["id"] == exclude_batch_id:
            continue
        if sibling["status"] not in OCCUPYING_BATCH_STATUSES:
            continue
        if windows_overlap(start_at, end_at, sibling["window_start_at"],
                           sibling["window_end_at"]):
            return sibling
    return None


# --- lender warrantability (PRD 3.8) --------------------------------------

BASIS_FIELDS = {
    "contract": ("owner_occupancy_pct_contract_basis",
                 "investor_concentration_pct_contract_basis",
                 "warrantability_verdict"),
    "closed": ("owner_occupancy_pct_closed_basis",
               "investor_concentration_pct_closed_basis",
               "warrantability_verdict_closed_basis"),
}


def _population(project_id, basis):
    agreements = store.project_agreements(project_id)
    if basis == "contract":
        return [a for a in agreements
                if a["contract_status"] in CONTRACT_BASIS_STATUSES]
    return [a for a in agreements if a["contract_status"] == "CLOSED"]


def single_investor_max(project):
    """Always grouped over the *contract*-basis agreements, and always divided
    by the project's as-declared `total_unit_count`."""
    groups = {}
    for agreement in _population(project["id"], "contract"):
        key = agreement["purchaser_tax_id"]
        groups[key] = groups.get(key, 0) + 1
    if not groups:
        return pct2(0)
    return ratio_pct(max(groups.values()), project["total_unit_count"])


def recompute_warrantability(project, basis, bump=True):
    owner_field, investor_field, verdict_field = BASIS_FIELDS[basis]
    population = _population(project["id"], basis)
    values = {}
    if not population:
        values[owner_field] = pct2(0)
        values[investor_field] = pct2(0)
        values["single_investor_max_pct"] = pct2(0)
        values["presale_sold_pct"] = pct2(0)
        values[verdict_field] = "NON_WARRANTABLE"
    else:
        denominator = len(population)
        owner = ratio_pct(len([a for a in population
                               if a["purchaser_type"] == "OWNER_OCCUPANT"]),
                          denominator)
        investor = ratio_pct(len([a for a in population
                                  if a["purchaser_type"] == "INVESTOR"]),
                             denominator)
        single = single_investor_max(project)
        presale = presale_sold_pct(project)
        values[owner_field] = owner
        values[investor_field] = investor
        values["single_investor_max_pct"] = single
        values["presale_sold_pct"] = presale
        warrantable = (owner >= OWNER_OCCUPANCY_MIN_PCT
                       and investor <= INVESTOR_CONCENTRATION_MAX_PCT
                       and single <= SINGLE_INVESTOR_MAX_PCT
                       and presale >= PRESALE_SOLD_MIN_PCT)
        values[verdict_field] = ("WARRANTABLE" if warrantable
                                 else "NON_WARRANTABLE")

    changed = any(project[key] != value for key, value in values.items())
    project.update(values)
    if changed and bump:
        store.touch(project)
    return changed
