"""Settlement gain, base charge and the waterfall (PRD 3.9)."""
from decimal import Decimal

from common import dec, rhu, rhu_int, whole_days
from derive import (ADG_TIER_1_MULT, ADG_TIER_2_FLOOR, ADG_TIER_2_MULT,
                    ADG_TIER_3_FLOOR, ADG_TIER_3_MULT, DROUGHT_WAIVER_PCT,
                    GAIN_CAP_LBS_PER_HEAD, GRAZIER_EARLY_CREDIT_PCT,
                    OWNER_EARLY_PENALTY_PCT, REBATE_TIER_1_FLOOR,
                    REBATE_TIER_2_FLOOR, deaths_of_lot, tickets_of_contract,
                    treatments_of_lot)
from store import db


def provisional_gain(lot):
    shrunk_in = dec(lot["shrunk_weight_in_lbs"] or 0)
    shrunk_out = lot["shrunk_weight_out_lbs"] or 0
    head_recv = lot["head_count_received"] or 0
    head_out = lot["head_count_out"] or 0
    if head_recv == 0:
        adjusted_in = 0
    else:
        adjusted_in = rhu_int(shrunk_in / dec(head_recv) * dec(head_out))
    return adjusted_in, shrunk_out - adjusted_in


def compute_gain(settlement, lot):
    method = settlement["gain_method"]
    shrunk_in = dec(lot["shrunk_weight_in_lbs"] or 0)
    shrunk_out = lot["shrunk_weight_out_lbs"] or 0
    head_recv = lot["head_count_received"] or 0
    head_out = lot["head_count_out"] or 0

    prov_adjusted, prov_gain = provisional_gain(lot)

    if method == "PROVISIONAL_PRORATED":
        adjusted_in = prov_adjusted
        gain = prov_gain
    elif method == "FINAL_ADJUDICATED":
        if head_out == 0:
            adjusted_in = rhu_int(shrunk_in)
        else:
            avg_out = dec(shrunk_out) / dec(head_out)
            adjusted_in = rhu_int(shrunk_in - avg_out * dec(head_recv - head_out))
        gain = shrunk_out - adjusted_in
    else:  # SPLIT_MIDPOINT
        claimed = settlement.get("claimed_shrunk_gain_lbs")
        claimed = dec(claimed) if claimed is not None else Decimal(0)
        gain = rhu_int((dec(prov_gain) + claimed) / Decimal(2))
        adjusted_in = shrunk_out - gain
    return adjusted_in, gain


def compute_adg(gain_lbs, head_out, days_on_feed):
    if not head_out or not days_on_feed:
        return Decimal("0.0000")
    return rhu(dec(gain_lbs) / (dec(head_out) * dec(days_on_feed)), 4)


def _tier_multiplier(adg):
    if adg < ADG_TIER_2_FLOOR:
        return ADG_TIER_1_MULT
    if adg < ADG_TIER_3_FLOOR:
        return ADG_TIER_2_MULT
    return ADG_TIER_3_MULT


def compute_settlement(settlement, recompute_aggregates=True):
    lot = db.lots[settlement["lot_id"]]
    contract = db.contracts[settlement["contract_id"]]

    adjusted_in, gain = compute_gain(settlement, lot)
    days_on_feed = settlement["days_on_feed"] or 0
    head_out = lot["head_count_out"] or 0
    adg = compute_adg(gain, head_out, days_on_feed)

    settlement["adjusted_in_weight_lbs"] = adjusted_in
    settlement["shrunk_gain_lbs"] = gain
    settlement["average_daily_gain"] = float(adg)

    # ---- base charge -----------------------------------------------------
    if contract["billing_mode"] == "PER_HEAD_PER_DAY":
        raw_head_days = (lot["head_count_received"] or 0) * days_on_feed
        for report in deaths_of_lot(lot["id"]):
            if report["status"] != "CONFIRMED":
                continue
            raw_head_days -= report["head_lost"] * whole_days(lot["out_date"], report["death_date"])
        floor_head_days = contract["head_count_committed"] * contract["min_days"]
        billable = max(raw_head_days, floor_head_days)
        settlement["billable_head_days"] = billable
        settlement["base_charge_cents"] = rhu_int(dec(billable) * dec(contract["rate_cents"]))
    else:
        settlement["billable_head_days"] = 0
        multiplier = _tier_multiplier(adg)
        cap = dec(contract["head_count_committed"]) * GAIN_CAP_LBS_PER_HEAD
        capped_gain = min(dec(gain), cap)
        settlement["base_charge_cents"] = rhu_int(capped_gain * dec(contract["rate_cents"]) * multiplier)

    # ---- aggregated charge lines ----------------------------------------
    if recompute_aggregates:
        settlement["treatment_charge_cents"] = sum(
            t["owner_share_cents"] for t in treatments_of_lot(lot["id"]) if t["status"] == "APPROVED"
        )
        settlement["infrastructure_charge_cents"] = sum(
            k["owner_share_cents"] for k in tickets_of_contract(contract["id"])
            if k["status"] in ("REPAIRED", "BILLED")
        )
        settlement["death_loss_credit_cents"] = sum(
            d["credit_cents"] for d in deaths_of_lot(lot["id"]) if d["status"] == "CONFIRMED"
        )

    subtotal = (settlement["base_charge_cents"]
                + settlement["treatment_charge_cents"]
                + settlement["infrastructure_charge_cents"]
                - settlement["death_loss_credit_cents"])
    settlement["subtotal_cents"] = subtotal

    reason = contract.get("early_removal_reason")
    if reason == "DROUGHT":
        adjustment = -rhu_int(dec(subtotal) * DROUGHT_WAIVER_PCT / Decimal(100))
    elif reason == "OWNER_ELECTED":
        adjustment = rhu_int(dec(subtotal) * OWNER_EARLY_PENALTY_PCT / Decimal(100))
    elif reason == "GRAZIER_ELECTED":
        adjustment = -rhu_int(dec(subtotal) * GRAZIER_EARLY_CREDIT_PCT / Decimal(100))
    else:
        adjustment = 0
    settlement["early_removal_adjustment_cents"] = adjustment

    rebate_base = subtotal + adjustment
    if rebate_base < REBATE_TIER_1_FLOOR:
        rebate_pct = Decimal("0.0")
    elif rebate_base < REBATE_TIER_2_FLOOR:
        rebate_pct = Decimal("1.0")
    else:
        rebate_pct = Decimal("2.0")
    rebate = rhu_int(dec(rebate_base) * rebate_pct / Decimal(100))
    settlement["volume_rebate_cents"] = rebate
    settlement["total_due_cents"] = rebate_base - rebate
