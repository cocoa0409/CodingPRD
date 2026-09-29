"""Derived-field reconciliation and the multi-hop cascades.

Everything in here is idempotent: `txn.commit` bumps a record's version only
when a field actually changed, so a recompute that finds nothing to do is free.
"""

from decimal import Decimal
from fractions import Fraction

import calc
import constants as K
import logical_clock
import store
import txn
from numeric import frac, pct, rhu_cents

ZERO = Decimal("0.00")
TOXICITY_RANK = {"I": 1, "II": 2, "III": 3, "IV": 4}


# --- collection accessors (every ordering ends on the insertion counter) ----

def _by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["seq"]))


def site_prps(site_id):
    return _by_created([p for p in store.prps.values() if p["site_id"] == site_id])


def site_waste(site_id):
    return _by_created(
        [w for w in store.waste_in_records.values() if w["site_id"] == site_id]
    )


def prp_waste(prp_id):
    return _by_created(
        [w for w in store.waste_in_records.values() if w["prp_id"] == prp_id]
    )


def prp_periods(prp_id):
    return _by_created(
        [o for o in store.ownership_periods.values() if o["prp_id"] == prp_id]
    )


def site_periods(site_id):
    return _by_created(
        [o for o in store.ownership_periods.values() if o["site_id"] == site_id]
    )


def site_rounds(site_id):
    rows = [r for r in store.allocation_rounds.values() if r["site_id"] == site_id]
    return sorted(rows, key=lambda r: (r["round_number"], r["seq"]))


def round_shares(round_id):
    """PRD 2.3/3.6: ordered by the owning party's created_at ascending, the same
    enumeration order the allocation arithmetic uses."""
    rows = [
        s
        for s in store.allocation_shares.values()
        if s["allocation_round_id"] == round_id
    ]
    return sorted(
        rows,
        key=lambda s: (
            store.prps[s["prp_id"]]["created_at"],
            store.prps[s["prp_id"]]["seq"],
        ),
    )


def prp_shares(prp_id):
    rows = [s for s in store.allocation_shares.values() if s["prp_id"] == prp_id]
    return _by_created(rows)


def site_rods(site_id):
    return _by_created(
        [r for r in store.records_of_decision.values() if r["site_id"] == site_id]
    )


def site_decrees(site_id):
    return _by_created(
        [d for d in store.consent_decrees.values() if d["site_id"] == site_id]
    )


def site_contracts(site_id):
    return _by_created(
        [c for c in store.remediation_contracts.values() if c["site_id"] == site_id]
    )


def contract_windows(contract_id):
    rows = [
        w
        for w in store.work_windows.values()
        if w["remediation_contract_id"] == contract_id
    ]
    return _by_created(rows)


def site_actions(site_id):
    return _by_created(
        [a for a in store.cost_recovery_actions.values() if a["site_id"] == site_id]
    )


def ri_samples(ri_id):
    rows = [
        s
        for s in store.contaminant_samples.values()
        if s["remedial_investigation_id"] == ri_id
    ]
    return _by_created(rows)


def ri_alternatives(ri_id):
    rows = [
        a
        for a in store.remedy_alternatives.values()
        if a["remedial_investigation_id"] == ri_id
    ]
    return _by_created(rows)


def site_investigations(site_id):
    return _by_created(
        [r for r in store.remedial_investigations.values() if r["site_id"] == site_id]
    )


def site_postings(site_id):
    rows = [p for p in store.oversight_postings.values() if p["site_id"] == site_id]
    return _by_created(rows)


def adopted_round(site):
    rid = site.get("adopted_round_id")
    return store.allocation_rounds.get(rid) if rid else None


def governing_decree(site):
    """PRD 3.7: the site's instrument whose legal_status is ENTERED becomes the
    governing oversight cap; a site has at most one at a time."""
    for decree in site_decrees(site["id"]):
        if decree["legal_status"] == "ENTERED":
            return decree
    return None


# --- evidentiary recomputation (PRD 3.2 hop 2) -----------------------------

def effective_volume(record):
    """effective_volume_tons is the verified volume once verified, the claimed
    volume while still submitted, and zero once rejected."""
    if record["status"] == "VERIFIED":
        return record["verified_volume_tons"]
    if record["status"] == "SUBMITTED":
        return record["volume_tons"]
    return ZERO


def recompute_prp_volumes(prp):
    txn.watch(prp)
    records = prp_waste(prp["id"])
    submitted = ZERO
    verified = ZERO
    best = None
    for rec in records:
        if rec["status"] in ("SUBMITTED", "VERIFIED"):
            submitted += rec["effective_volume_tons"]
        if rec["status"] == "VERIFIED":
            verified += rec["verified_volume_tons"]
            rank = TOXICITY_RANK[rec["toxicity_class"]]
            if best is None or rank < best:
                best = rank
    prp["submitted_volume_tons"] = submitted
    prp["verified_volume_tons"] = verified
    prp["max_toxicity_class"] = None
    if best is not None:
        for name, rank in TOXICITY_RANK.items():
            if rank == best:
                prp["max_toxicity_class"] = name


def recompute_site_verified_volume(site):
    txn.watch(site)
    total = ZERO
    for rec in site_waste(site["id"]):
        if rec["status"] == "VERIFIED":
            total += rec["verified_volume_tons"]
    site["verified_waste_volume_tons"] = total


def recompute_prp_eligibility(site, prp):
    """The site total is the denominator of every party's share, so this runs for
    EVERY party of the site whenever the denominator moves."""
    txn.watch(prp)
    share = calc.volumetric_share_pct(
        prp["verified_volume_tons"], site["verified_waste_volume_tons"]
    )
    prp["volumetric_share_pct"] = share
    prp["de_minimis_eligible"] = calc.de_minimis_eligible(
        share, prp["max_toxicity_class"], prp["verified_volume_tons"]
    )


def recompute_all_eligibility(site):
    for prp in site_prps(site["id"]):
        recompute_prp_eligibility(site, prp)


def recompute_ownership_days_total(prp):
    txn.watch(prp)
    prp["ownership_days_total"] = sum(
        o["ownership_days"] for o in prp_periods(prp["id"])
    )


def after_waste_change(site, prp):
    """PRD 3.2: hop 2 then hop 3.  A rejection runs exactly the same hops as a
    verification, with the rejected record contributing zero."""
    recompute_prp_volumes(prp)
    recompute_site_verified_volume(site)
    recompute_all_eligibility(site)
    recompute_drafting_rounds(site)


# --- allocation arithmetic (PRD 3.6) --------------------------------------

def variant_rows(site, round_, variant):
    """One row per share, in party created_at order.  Provisional counts every
    SUBMITTED-or-VERIFIED record at effective_volume_tons; final counts only
    VERIFIED records at verified_volume_tons."""
    if variant == "provisional":
        wanted = ("SUBMITTED", "VERIFIED")
        field = "effective_volume_tons"
    else:
        wanted = ("VERIFIED",)
        field = "verified_volume_tons"

    records = [r for r in site_waste(site["id"]) if r["status"] in wanted]
    rows = []
    for share in round_shares(round_["id"]):
        prp = store.prps[share["prp_id"]]
        vol = Fraction(0)
        tox = Fraction(0)
        for rec in records:
            if rec["prp_id"] != prp["id"]:
                continue
            value = frac(rec[field])
            vol += value
            tox += value * K.TOXICITY_MULTIPLIER[rec["toxicity_class"]]
        rows.append(
            {
                "vol": vol,
                "tox": tox,
                "own": Fraction(prp["ownership_days_total"]),
                "key": share["id"],
            }
        )
    return rows


def round_weights(round_):
    return (
        round_["weight_volume_bp"],
        round_["weight_toxicity_bp"],
        round_["weight_ownership_bp"],
    )


def has_allocation_basis(site, round_):
    rows = variant_rows(site, round_, "provisional")
    return any(r["vol"] > 0 or r["tox"] > 0 or r["own"] > 0 for r in rows)


def recompute_provisional(site, round_):
    rows = variant_rows(site, round_, "provisional")
    pcts, has_basis = calc.allocation_pcts(round_weights(round_), rows)
    for share in round_shares(round_["id"]):
        txn.watch(share)
        share["provisional_pct"] = pcts.get(share["id"], ZERO) if has_basis else ZERO
    recompute_round_counters(round_)


def recompute_round_counters(round_):
    txn.watch(round_)
    shares = round_shares(round_["id"])
    round_["share_count"] = len(shares)
    round_["balloted_count"] = sum(1 for s in shares if s["ballot"] is not None)
    accept = Fraction(0)
    for share in shares:
        if share["ballot"] == "ACCEPT":
            accept += frac(share["provisional_pct"])
    round_["accept_share_pct"] = pct(accept)


def recompute_drafting_rounds(site):
    """Rounds that have left DRAFTING are frozen: provisional percentages become
    the weights parties vote on."""
    for round_ in site_rounds(site["id"]):
        if round_["status"] == "DRAFTING":
            recompute_provisional(site, round_)


def recompute_share_totals(round_):
    """PRD 3.6/2.10: allocated + orphan + settled == exactly 100.00 for an
    adopted round.  Before adoption allocated_share_total_pct reads 0.00."""
    txn.watch(round_)
    allocated = Fraction(0)
    orphaned = Fraction(0)
    settled = Fraction(0)
    for share in round_shares(round_["id"]):
        if share["disposition"] == "ALLOCATED":
            allocated += frac(share["final_pct"] or ZERO)
        elif share["disposition"] == "ORPHANED":
            orphaned += frac(share["pre_settlement_final_pct"] or ZERO)
        elif share["disposition"] == "SETTLED":
            settled += frac(share["pre_settlement_final_pct"] or ZERO)
    round_["allocated_share_total_pct"] = pct(allocated)
    round_["orphan_share_pct"] = pct(orphaned)
    round_["settled_share_pct"] = pct(settled)


def adopt_round(site, round_):
    """The final variant runs exactly once, here."""
    rows = variant_rows(site, round_, "final")
    pcts, _basis = calc.allocation_pcts(round_weights(round_), rows)
    for share in round_shares(round_["id"]):
        txn.watch(share)
        prp = store.prps[share["prp_id"]]
        value = pcts.get(share["id"], ZERO)
        if prp["status"] == "ORPHAN":
            share["pre_settlement_final_pct"] = value
            share["final_pct"] = ZERO
            share["disposition"] = "ORPHANED"
        elif prp["status"] == "DE_MINIMIS_SETTLED":
            share["pre_settlement_final_pct"] = value
            share["final_pct"] = ZERO
            share["disposition"] = "SETTLED"
        else:
            share["final_pct"] = value
            share["disposition"] = "ALLOCATED"
    recompute_share_totals(round_)
    txn.watch(round_)
    round_["status"] = "ADOPTED"
    round_["adopted_at"] = logical_clock.now()
    txn.watch(site)
    site["adopted_round_id"] = round_["id"]
    recompute_site_derived(site)


def share_for(round_id, prp_id):
    for share in store.allocation_shares.values():
        if share["allocation_round_id"] == round_id and share["prp_id"] == prp_id:
            return share
    return None


# --- oversight, ledger and posture (PRD 2.9, 2.10, 3.7) -------------------

def oversight_direct(site, extra_cents=0):
    return (
        sum(p["incurred_cents"] for p in site_postings(site["id"])) + extra_cents
    )


def prospective_oversight(site, extra_cents):
    """Used to test the cap BEFORE a posting lands, because a refused posting
    must leave every field exactly as it was."""
    return calc.oversight_figures(oversight_direct(site, extra_cents))


def recompute_oversight(site):
    txn.watch(site)
    postings = site_postings(site["id"])
    direct = sum(p["incurred_cents"] for p in postings)
    if not postings:
        # PRD 3.1: a newly proposed site begins with every derived cost figure
        # at zero, the indirect rate included.
        rate, indirect, billed = 0, 0, 0
    else:
        rate, indirect, billed = calc.oversight_figures(direct)
    site["oversight_direct_cents"] = direct
    site["oversight_indirect_rate_bp"] = rate
    site["oversight_indirect_cents"] = indirect
    site["oversight_billed_cents"] = billed
    decree = governing_decree(site)
    if decree is None:
        site["oversight_cap_utilization_pct"] = None
    else:
        site["oversight_cap_utilization_pct"] = calc.cap_utilization_pct(
            billed, decree["oversight_cost_cap_cents"]
        )


def recompute_ledger(site):
    txn.watch(site)
    total = site["oversight_billed_cents"]
    for contract in site_contracts(site["id"]):
        if contract["status"] in ("AWARDED", "CONSTRUCTION_COMPLETE", "CLOSED"):
            total += contract["awarded_amount_cents"] or 0
    recovered = 0
    for action in site_actions(site["id"]):
        # PRD 3.9: "Every receipt increases the site's recovered_cost_cents ...
        # so the ledger identity of 2.10 holds after every partial payment, not
        # merely at the end."  A partial receipt sits on an action that is still
        # ACCEPTED, and voiding zeroes the action's received_cents.
        if action["status"] in ("ACCEPTED", "COLLECTED"):
            recovered += action["received_cents"] or 0
    round_ = adopted_round(site)
    if round_ is None:
        orphan = 0
    else:
        orphan = rhu_cents(frac(total) * frac(round_["orphan_share_pct"]) / 100)
    site["total_response_cost_cents"] = total
    site["recovered_cost_cents"] = recovered
    site["orphan_write_off_cents"] = orphan
    # PRD 2.10: may be negative and is never floored at zero.
    site["unrecovered_cost_cents"] = total - recovered - orphan


def recompute_posture(site):
    txn.watch(site)
    decrees = site_decrees(site["id"])
    if any(d["compliance_status"] == "PENALTY_ACCRUING" for d in decrees):
        site["cost_posture"] = "FROZEN"
        return
    util = site.get("oversight_cap_utilization_pct")
    restricted = (
        (util is not None and frac(util) >= frac(Decimal(K.COST_RESTRICTION_UTILIZATION_PCT)))
        or any(d["compliance_status"] == "IN_VIOLATION" for d in decrees)
        or any(r["status"] == "AMENDMENT_REQUIRED" for r in site_rods(site["id"]))
        or site["listing_status"] == "REMEDY_REEVALUATION"
    )
    site["cost_posture"] = "RESTRICTED" if restricted else "OPEN"


def recompute_site_derived(site):
    """Idempotent full reconciliation of every derived figure on the site."""
    txn.watch(site)
    found = None
    for round_ in site_rounds(site["id"]):
        if round_["status"] == "ADOPTED":
            found = round_["id"]
    site["adopted_round_id"] = found
    recompute_oversight(site)
    recompute_ledger(site)
    recompute_posture(site)


def cost_ledger_view(site):
    round_ = adopted_round(site)
    allocated = round_["allocated_share_total_pct"] if round_ else ZERO
    orphan = round_["orphan_share_pct"] if round_ else ZERO
    settled = round_["settled_share_pct"] if round_ else ZERO
    balanced = (
        site["recovered_cost_cents"]
        + site["orphan_write_off_cents"]
        + site["unrecovered_cost_cents"]
        == site["total_response_cost_cents"]
    )
    return {
        "total_response_cost_cents": site["total_response_cost_cents"],
        "recovered_cost_cents": site["recovered_cost_cents"],
        "orphan_write_off_cents": site["orphan_write_off_cents"],
        "unrecovered_cost_cents": site["unrecovered_cost_cents"],
        "oversight_direct_cents": site["oversight_direct_cents"],
        "oversight_indirect_rate_bp": site["oversight_indirect_rate_bp"],
        "oversight_indirect_cents": site["oversight_indirect_cents"],
        "oversight_billed_cents": site["oversight_billed_cents"],
        "oversight_cap_utilization_pct": site["oversight_cap_utilization_pct"],
        "allocated_share_total_pct": allocated,
        "orphan_share_pct": orphan,
        "settled_share_pct": settled,
        "ledger_balanced": bool(balanced),
    }


# --- remedy scoring -------------------------------------------------------

def score_alternative(alternative, exceeded):
    txn.watch(alternative)
    alternative["cost_score"] = calc.cost_score(alternative["npv_cents"])
    alternative["remedy_score"] = calc.remedy_score(
        alternative["effectiveness_score"],
        alternative["implementability_score"],
        alternative["cost_score"],
        exceeded,
    )


def rescore_alternatives(ri):
    """Submission re-scores every alternative already recorded, because
    action_level_exceeded may have just flipped the weighting branch."""
    for alternative in ri_alternatives(ri["id"]):
        score_alternative(alternative, ri["action_level_exceeded"])


def recompute_valid_sample_count(ri):
    txn.watch(ri)
    ri["valid_sample_count"] = sum(
        1
        for s in ri_samples(ri["id"])
        if s["medium"] == ri["exposure_medium"] and s["qa_status"] == "VALID"
    )


# --- cascades -------------------------------------------------------------

def defunct_cascade(site, prp):
    """PRD 3.1: a three-part cascade, and every part must land."""
    round_ = adopted_round(site)
    if round_ is not None:
        share = share_for(round_["id"], prp["id"])
        if share is not None and share["disposition"] == "ALLOCATED":
            txn.watch(share)
            share["pre_settlement_final_pct"] = share["final_pct"] or ZERO
            share["final_pct"] = ZERO
            share["disposition"] = "ORPHANED"
            recompute_share_totals(round_)
    for other in site_rounds(site["id"]):
        if other["status"] not in ("DRAFTING", "BALLOTING"):
            continue
        share = share_for(other["id"], prp["id"])
        if share is None:
            continue
        txn.watch(share)
        share["ballot"] = "ABSTAIN"
        recompute_round_counters(other)
    recompute_site_derived(site)


def not_protective_cascade(site):
    """PRD 3.8: hop 1 the phase, hop 2 the signed decision, hop 3 the posture."""
    txn.watch(site)
    site["listing_status"] = "REMEDY_REEVALUATION"
    for rod in site_rods(site["id"]):
        if rod["status"] == "SIGNED":
            txn.watch(rod)
            rod["status"] = "AMENDMENT_REQUIRED"
    recompute_site_derived(site)


def withdraw_amendment_required(site):
    """PRD 3.5: an amended signature withdraws every document awaiting
    amendment, and never touches one that is merely SIGNED."""
    for rod in site_rods(site["id"]):
        if rod["status"] == "AMENDMENT_REQUIRED":
            txn.watch(rod)
            rod["status"] = "WITHDRAWN"


def terminate_eligible_decrees(site):
    """PRD 3.7: termination is never requested directly.  An instrument with an
    outstanding penalty balance stays entered."""
    for decree in site_decrees(site["id"]):
        if (
            decree["legal_status"] == "ENTERED"
            and decree["compliance_status"] == "COMPLIANT"
            and decree["accrued_penalty_cents"] == decree["paid_penalty_cents"]
        ):
            txn.watch(decree)
            decree["legal_status"] = "TERMINATED"
            decree["terminated_at"] = logical_clock.now()


def advance_review_due(site):
    """Chained off the PREVIOUS due date, never off the review date."""
    txn.watch(site)
    if site["five_year_review_due_at"] is not None:
        site["five_year_review_due_at"] = logical_clock.plus_days(
            site["five_year_review_due_at"], K.FIVE_YEAR_REVIEW_DAYS
        )
