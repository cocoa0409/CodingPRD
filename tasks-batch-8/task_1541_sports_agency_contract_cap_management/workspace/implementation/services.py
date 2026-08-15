"""Business logic: calculations (scaffold 1.3) and cascade side effects.

All money is integer cents; fractional results are rounded half-up to a whole
cent exactly where the governing rule specifies (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

import db
import helpers as h


def D(v):
    """Exact Decimal from a JSON number (avoids binary float noise)."""
    return Decimal(str(v))


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# contract_aav (scaffold 1.3): per-year rounding, then final AAV division.
# ---------------------------------------------------------------------------

def contract_valuation(base_salary_cents, years, signing_bonus_cents,
                       incentive_cents, escalator_pct):
    esc = D(escalator_pct)
    factor = Decimal(1) + esc
    per_year_base = []
    for y in range(1, years + 1):
        per_year_base.append(round_cents(D(base_salary_cents) * (factor ** (y - 1))))
    base_sum = sum(per_year_base)
    bonus_prorated = round_cents(D(signing_bonus_cents) / D(years))
    incentive_per = round_cents(D(incentive_cents) / D(years))
    per_year_cap_hit = [b + bonus_prorated + incentive_per for b in per_year_base]
    total_cap_value = sum(per_year_cap_hit)
    aav_cents = round_cents(D(total_cap_value) / D(years))
    total_value_cents = base_sum + signing_bonus_cents + incentive_cents
    return aav_cents, total_value_cents


def escalator_projection(base_salary_cents, years, escalator_pct):
    esc = D(escalator_pct)
    factor = Decimal(1) + esc
    return [round_cents(D(base_salary_cents) * (factor ** (y - 1)))
            for y in range(1, years + 1)]


# ---------------------------------------------------------------------------
# endorsement_agent_fee (scaffold 1.3): tiered base rate, then agency cap.
# ---------------------------------------------------------------------------

TIER1_MAX = 100000000    # $1M in cents
TIER2_MAX = 500000000    # $5M in cents
TIER1_RATE = Decimal("0.10")
TIER2_RATE = Decimal("0.15")
TIER3_RATE = Decimal("0.20")


def endorsement_agent_fee(deal_value_cents, fee_cap_pct):
    if deal_value_cents < TIER1_MAX:
        rate = TIER1_RATE
    elif deal_value_cents < TIER2_MAX:
        rate = TIER2_RATE
    else:
        rate = TIER3_RATE
    raw_fee = D(deal_value_cents) * rate
    capped_fee = D(deal_value_cents) * D(fee_cap_pct)
    return round_cents(min(raw_fee, capped_fee))


# ---------------------------------------------------------------------------
# contract_fee_accrual (scaffold 1.3)
# ---------------------------------------------------------------------------

def playing_contract_fee(aav_cents, fee_cap_pct):
    return round_cents(D(aav_cents) * D(fee_cap_pct))


# ---------------------------------------------------------------------------
# transition_split_fee (scaffold 1.3): 25/75 split, residue to the new agent.
# ---------------------------------------------------------------------------

def transition_split_amounts(contract, fee_cap_pct, current_season_year):
    remaining_years = contract["years"] - (current_season_year - contract["start_season_year"])
    remaining_aav = D(contract["aav_cents"]) * D(remaining_years)
    remaining_fee = round_cents(remaining_aav * D(fee_cap_pct))
    old_amount = round_cents(D(remaining_fee) * Decimal("0.25"))
    new_amount = remaining_fee - old_amount
    return remaining_fee, old_amount, new_amount


# ---------------------------------------------------------------------------
# Fee ledger
# ---------------------------------------------------------------------------

def emit_fee_entry(agency_id, contract_id, endorsement_deal_id, agent_id,
                   split_pct, amount_cents, kind):
    entry = h.new_entity()
    entry.update({
        "agency_id": agency_id,
        "contract_id": contract_id,
        "endorsement_deal_id": endorsement_deal_id,
        "agent_id": agent_id,
        "split_pct": split_pct,
        "amount_cents": amount_cents,
        "kind": kind,
        "status": "ACCRUED",
    })
    db.fee_ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Cap reservation cascades (PRD 2.8). Every affected entity gets its own
# updated_at refresh and version bump (PRD 2.4); one bump per entity per
# request regardless of how many cascade waves touch it.
# ---------------------------------------------------------------------------

def _release_reservation(proposal, contract):
    if proposal["status"] in ("SUBMITTED", "COUNTERED"):
        season = db.cap_seasons.get(contract["cap_season_id"])
        if season is not None:
            season["reserved_cents"] -= proposal["proposed_aav_cents"]
            h.bump_once(season)


def withdraw_proposal(proposal, contract):
    """Withdraw one proposal, releasing any reservation it holds."""
    _release_reservation(proposal, contract)
    proposal["status"] = "WITHDRAWN"
    h.bump_once(proposal)


def withdraw_open_proposals(contract):
    """Withdraw every DRAFT/SUBMITTED/COUNTERED proposal on a contract."""
    for p in db.proposals.values():
        if p["contract_id"] == contract["id"] and p["status"] in ("DRAFT", "SUBMITTED", "COUNTERED"):
            withdraw_proposal(p, contract)


def withdraw_agent_inflight_proposals(agent_id):
    """Agent suspension/revocation cascade: their live proposals die."""
    for p in db.proposals.values():
        if p["proposed_by_agent_id"] == agent_id and p["status"] in ("SUBMITTED", "COUNTERED"):
            contract = db.contracts.get(p["contract_id"])
            if contract is not None:
                withdraw_proposal(p, contract)


def lock_season_cascade(season):
    """CapSeason lock: force-withdraw live proposals against linked contracts."""
    linked_contract_ids = {
        c["id"] for c in db.contracts.values() if c["cap_season_id"] == season["id"]
    }
    for p in db.proposals.values():
        if p["contract_id"] in linked_contract_ids and p["status"] in ("SUBMITTED", "COUNTERED"):
            season["reserved_cents"] -= p["proposed_aav_cents"]
            p["status"] = "WITHDRAWN"
            h.bump_once(p)


def void_accrued_entries_for_contract(contract_id):
    for e in db.fee_ledger_entries.values():
        if e["contract_id"] == contract_id and e["status"] == "ACCRUED":
            e["status"] = "VOIDED"
            h.bump_once(e)


def void_accrued_entries_for_deal(deal_id):
    for e in db.fee_ledger_entries.values():
        if e["endorsement_deal_id"] == deal_id and e["status"] == "ACCRUED":
            e["status"] = "VOIDED"
            h.bump_once(e)


# ---------------------------------------------------------------------------
# Time-driven transitions (PRD 2.5): evaluated against the logical clock.
# ---------------------------------------------------------------------------

def sweep_time_transitions():
    now = db.get_clock()
    for deal in db.endorsements.values():
        if deal["status"] == "ACTIVE" and now >= deal["_end_dt"]:
            deal["status"] = "COMPLETED"
            h.bump(deal)
    for tender in db.tender_options.values():
        if tender["status"] == "PENDING" and now >= tender["_close_dt"]:
            tender["status"] = "EXPIRED"
            h.bump(tender)
