"""Cascades, roll-up reconciliation and shared state-machine side effects."""

from decimal import Decimal

import calc
from common import public, rows_where
from store import by_created_at, db, new_record, touch


# ---- grower standing (PRD 3.3, four hops) --------------------------------
def grower_standing_cascade(grower, offending_contract_id=None):
    """Hop 2: flag counter and grower version.  Hop 3: standing re-derived
    from the counter alone.  Hop 4: the grower's other DRAFT/OFFERED
    contracts are flagged for field-officer review in created_at order."""
    grower["compliance_flag_count"] = grower["compliance_flag_count"] + 1
    grower["status"] = calc.grower_standing_for(grower["compliance_flag_count"])
    touch(grower)
    if grower["status"] in ("WATCH", "SUSPENDED"):
        siblings = [c for c in db.production_contracts.values()
                    if c["grower_id"] == grower["id"]
                    and c["id"] != offending_contract_id
                    and c["status"] in ("DRAFT", "OFFERED")]
        for contract in by_created_at(siblings):
            contract["requires_field_officer_review"] = True
            touch(contract)


# ---- derived roll-ups ---------------------------------------------------
def recompute_certified_units_total(contract):
    total = Decimal("0")
    for lot in db.seed_lots.values():
        if (lot["production_contract_id"] == contract["id"]
                and lot["certification_status"] == "TAGGED"
                and lot["final_clean_units"] is not None):
            total += calc.dec(lot["final_clean_units"])
    contract["certified_units_total"] = calc.round_half_up(total, 2)


def recompute_tagged_bag_count(lot):
    total = 0
    for tag in by_created_at(rows_where(db.certification_tags, seed_lot_id=lot["id"])):
        if tag["status"] == "ISSUED":
            total += tag["bag_count"]
    lot["tagged_bag_count"] = total


def recompute_lot_dockage(lot):
    lot["dockage_pct"] = calc.dockage_pct_for(lot["cumulative_shrink_kg"], lot["gross_kg"])


# ---- lot identity -------------------------------------------------------
def next_lot_code(contract, season_year):
    seq = contract.get("_lot_seq", 0) + 1
    contract["_lot_seq"] = seq
    return "L-%d-%04d" % (season_year, seq)


def new_seed_lot(contract, season_year, variety_id, gross_kg, bag_size_kg,
                 intake_moisture_pct, provisional_clean_units,
                 conditioning_status="RAW", certification_status="UNSAMPLED",
                 parent_seed_lot_id=None, carryover_generation=0,
                 bag_count=0, final_clean_units=None):
    lot = new_record(True)
    lot["lot_code"] = next_lot_code(contract, season_year)
    lot["variety_id"] = variety_id
    lot["production_contract_id"] = contract["id"]
    lot["parent_seed_lot_id"] = parent_seed_lot_id
    lot["season_year"] = season_year
    lot["carryover_generation"] = carryover_generation
    lot["gross_kg"] = calc.round_half_up(gross_kg, 2)
    lot["current_kg"] = calc.round_half_up(gross_kg, 2)
    lot["cumulative_shrink_kg"] = Decimal("0.00")
    lot["dockage_pct"] = calc.round_half_up(0, 2)
    lot["bag_size_kg"] = bag_size_kg
    lot["bag_count"] = bag_count
    lot["tagged_bag_count"] = 0
    lot["intake_moisture_pct"] = intake_moisture_pct
    lot["provisional_clean_units"] = provisional_clean_units
    lot["final_clean_units"] = final_clean_units
    lot["conditioning_status"] = conditioning_status
    lot["certification_status"] = certification_status
    lot["germination_pct"] = None
    lot["purity_pct"] = None
    lot["weed_seed_count_per_kg"] = None
    lot["germination_valid_until"] = None
    lot["adjusted_price_per_unit_cents"] = None
    lot["disposition"] = "NONE"
    db.seed_lots[lot["id"]] = lot
    return lot


# ---- failing laboratory result (PRD 3.7, five hops) ---------------------
def failed_result_cascade(sample, lot):
    """Hop 1 is the sample verdict itself (applied by the caller).  Hops 2-5
    propagate to the lot, its tags, its contract and that contract's
    COMPUTED settlements."""
    # hop 2 - the lot
    lot["certification_status"] = "FAILED"
    lot["disposition"] = "DOWNGRADE_TO_COMMERCIAL"
    lot["adjusted_price_per_unit_cents"] = None

    # hop 3 - every ISSUED tag of the lot, created_at ascending
    for tag in by_created_at(rows_where(db.certification_tags, seed_lot_id=lot["id"])):
        if tag["status"] == "ISSUED":
            tag["status"] = "VOIDED"
            tag["void_reason"] = "RETEST_FAILURE"
            touch(tag)
    lot["tagged_bag_count"] = 0
    touch(lot)

    # hop 4 - the contract's certified unit roll-up
    contract = db.production_contracts.get(lot["production_contract_id"])
    if contract is not None:
        recompute_certified_units_total(contract)
        touch(contract)

        # hop 5 - every COMPUTED settlement of the contract, created_at ascending
        settlements = [s for s in db.settlements.values()
                       if s["production_contract_id"] == contract["id"]
                       and s["status"] == "COMPUTED"]
        for settlement in by_created_at(settlements):
            settlement["quality_hold"] = True
            settlement["status"] = "SUPERSEDED"
            touch(settlement)


# ---- contract cancellation trailing paperwork ---------------------------
def close_open_inspections(contract):
    inspections = [i for i in db.field_inspections.values()
                   if i["production_contract_id"] == contract["id"]
                   and i["status"] in ("RECORDED", "ROGUEING_DECLARED")]
    for inspection in by_created_at(inspections):
        inspection["status"] = "CLOSED"
        touch(inspection)
