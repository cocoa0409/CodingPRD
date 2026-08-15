"""Calculation rules (PRD 3.3-3.6, scaffold Table 3):

- dose_optimization
- claim_allowed_amount (per-component pinned rounding)
- member_cost_share
- redirection_incentive_estimate
- asp_retro_repricing (PAID/ADJUSTED -> ADJUSTED with ClaimAdjustment + ledger;
  APPROVED_FOR_PAYMENT/PENDED repriced in place)
- biosimilar activation in-flight repricing

All money is integer cents; all rounding is round-half-up at the pinned points.
"""
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import db, next_seq
from errors import raise_error, ERR_NO_ASP_RATE
from util import CLOCK, ceil_div_int, dec, new_id, pdate, round_cents

BASE_ADDON_PCT = Decimal("0.06")
REDIRECTED_SITE_ADDON_PCT = Decimal("0.02")
COINSURANCE_PCT = Decimal("0.20")


# ---------------------------------------------------------------------------
# Record mutation helpers (common fields: updated_at + version)
# ---------------------------------------------------------------------------

def touch(rec):
    rec["updated_at"] = CLOCK.ts()
    rec["version"] = rec.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_accepted_redirection(auth_id: str):
    for r in db["redirections"].values():
        if r["auth_id"] == auth_id and r["status"] == "ACCEPTED":
            return r
    return None


def active_biosimilar_policy_for(drug_id: str, service_date: date):
    """ACTIVE BiosimilarPolicy naming drug_id as its biosimilar whose half-open
    window covers service_date. Uniqueness is enforced at activation; if data
    ever disagrees, the latest-created policy wins."""
    best = None
    for p in db["biosimilar_policies"].values():
        if p["biosimilar_drug_id"] != drug_id or p["status"] != "ACTIVE":
            continue
        if pdate(p["effective_start"]) <= service_date < pdate(p["effective_end"]):
            if best is None or p["_seq"] > best["_seq"]:
                best = p
    return best


def asp_schedule_for(drug_id: str, service_date: date):
    """The schedule of the drug with the greatest effective_start <= service_date;
    ties broken by latest created (insertion sequence)."""
    best = None
    for s in db["asp_schedules"].values():
        if s["drug_id"] != drug_id:
            continue
        if pdate(s["effective_start"]) <= service_date:
            if best is None or (pdate(s["effective_start"]), s["_seq"]) > (
                pdate(best["effective_start"]), best["_seq"]
            ):
                best = s
    return best


# ---------------------------------------------------------------------------
# dose_optimization (auth approval)
# ---------------------------------------------------------------------------

def dose_optimization(drug: dict, auth: dict) -> int:
    if drug["weight_based_dosing"]:
        raw = dec(auth["weight_kg"]) * dec(drug["mg_per_kg"])
    else:
        raw = dec(auth["requested_dose_mg"])
    if drug["dose_rounding_mode"] == "VIAL":
        vial = dec(drug["vial_size_mg"])
        q = (raw / vial).to_integral_value(rounding=ROUND_CEILING)
        return int(q * vial)
    # INCREMENT: round half-up to nearest whole increment
    inc = dec(drug["rounding_increment_mg"])
    q = (raw / inc).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q * inc)


# ---------------------------------------------------------------------------
# claim_allowed_amount + member_cost_share
# ---------------------------------------------------------------------------

def compute_addon(claim_like: dict, service_date: date):
    """Total add-on fraction: base + redirection (site match) + biosimilar incentive.
    Returns (addon: Decimal, biosimilar_policy_or_None, accepted_redirection_or_None)."""
    addon = BASE_ADDON_PCT
    red = find_accepted_redirection(claim_like["auth_id"])
    if red is not None and claim_like["site_of_care"] == red["accepted_site"]:
        addon += REDIRECTED_SITE_ADDON_PCT
    bio = active_biosimilar_policy_for(claim_like["drug_id"], service_date)
    if bio is not None:
        addon += dec(bio["provider_incentive_addon_pct"])
    return addon, bio, red


def price_claim(drug: dict, claim_like: dict, rate_cents: int, service_date: date):
    """Pinned per-component rounding (PRD 3.6): round the drug component and the
    waste component independently, then sum. Also computes member cost share."""
    addon, bio, red = compute_addon(claim_like, service_date)
    payable_waste = (
        claim_like["waste_units"]
        if (drug["single_dose_vial"] and claim_like["jw_modifier"])
        else 0
    )
    mult = Decimal(1) + addon
    rate = dec(rate_cents)
    drug_amount = round_cents(dec(claim_like["billed_units"]) * rate * mult)
    waste_amount = round_cents(dec(payable_waste) * rate * mult)
    allowed = drug_amount + waste_amount
    # member_cost_share: waived to 0 exactly on an accepted redirection's site
    if red is not None and claim_like["site_of_care"] == red["accepted_site"]:
        mcs = 0
    else:
        waiver = dec(bio["member_copay_waiver_pct"]) if bio is not None else Decimal(0)
        mcs = round_cents(dec(allowed) * COINSURANCE_PCT * (Decimal(1) - waiver))
    return {
        "allowed": allowed,
        "mcs": mcs,
        "addon": addon,
        "payable_waste": payable_waste,
    }


# ---------------------------------------------------------------------------
# redirection_incentive_estimate (OFFERED -> ACCEPTED)
# ---------------------------------------------------------------------------

def redirection_incentive_estimate(redirection: dict) -> int:
    auth = db["prior_authorizations"][redirection["auth_id"]]
    drug = db["drugs"][auth["drug_id"]]
    est_units = ceil_div_int(auth["approved_dose_mg"], drug["billing_unit_mg"])
    sched = asp_schedule_for(drug["id"], CLOCK.today())
    if sched is None:
        raise_error(ERR_NO_ASP_RATE, "no ASP rate effective on the current date")
    est_allowed = round_cents(dec(est_units) * dec(sched["asp_rate_cents"]) * (Decimal(1) + BASE_ADDON_PCT))
    return round_cents(dec(est_allowed) * COINSURANCE_PCT)


# ---------------------------------------------------------------------------
# asp_retro_repricing (schedule activation cascade hop 2->3->4)
# ---------------------------------------------------------------------------

def _apply_price_to_claim(claim: dict, drug: dict, rate_cents: int, schedule_id: str):
    res = price_claim(drug, claim, rate_cents, pdate(claim["service_date"]))
    old = claim["allowed_amount_cents"]
    claim["asp_rate_cents"] = rate_cents
    claim["addon_pct_applied"] = float(res["addon"])
    claim["payable_waste_units"] = res["payable_waste"]
    claim["allowed_amount_cents"] = res["allowed"]
    claim["asp_schedule_id_used"] = schedule_id
    return old, res


def reprice_for_schedule(schedule: dict):
    """Reprice candidate claims of the drug at the newly activated schedule's rate.

    Candidates: service_date >= schedule.effective_start and not already priced at
    this schedule; states PAID, ADJUSTED, APPROVED_FOR_PAYMENT, PENDED.
    Processed in service_date ASC, then creation order (never by identifier).
    """
    start = pdate(schedule["effective_start"])
    candidates = [
        c
        for c in db["claims"].values()
        if c["drug_id"] == schedule["drug_id"]
        and pdate(c["service_date"]) >= start
        and c["asp_schedule_id_used"] != schedule["id"]
        and c["status"] in ("PAID", "ADJUSTED", "APPROVED_FOR_PAYMENT", "PENDED")
    ]
    candidates.sort(key=lambda c: (pdate(c["service_date"]), c["_seq"]))
    touched_providers = set()
    for claim in candidates:
        drug = db["drugs"][claim["drug_id"]]
        old_allowed, res = _apply_price_to_claim(claim, drug, schedule["asp_rate_cents"], schedule["id"])
        if claim["status"] in ("PAID", "ADJUSTED"):
            new_allowed = res["allowed"]
            adj = {
                "id": new_id(),
                "claim_id": claim["id"],
                "asp_schedule_id": schedule["id"],
                "old_allowed_cents": old_allowed,
                "new_allowed_cents": new_allowed,
                "delta_cents": new_allowed - old_allowed,
                "reason": "ASP_RETRO",
                "created_at": CLOCK.ts(),
                "_seq": next_seq(),
            }
            db["claim_adjustments"][adj["id"]] = adj
            claim["status"] = "ADJUSTED"
            # member_cost_share_cents deliberately NOT retro-adjusted for paid claims
            prov = db["provider_accounts"].get(claim["provider_account_id"])
            if prov is not None:
                prov["cumulative_paid_cents"] += adj["delta_cents"]
                if adj["delta_cents"] < 0:
                    prov["recoupment_balance_cents"] += -adj["delta_cents"]
                touch(prov)
                touched_providers.add(prov["id"])
            touch(claim)
        else:
            # unpaid: reprice in place, recompute member cost share, no adjustment
            claim["member_cost_share_cents"] = res["mcs"]
            touch(claim)
    # after all claims: any provider left with a positive recoupment balance holds
    for pid in touched_providers:
        prov = db["provider_accounts"][pid]
        if prov["recoupment_balance_cents"] > 0 and prov["status"] == "ACTIVE":
            prov["status"] = "RECOUPMENT_HOLD"
            touch(prov)


def reprice_for_biosimilar(policy: dict):
    """In-flight repricing at biosimilar activation: unpaid claims on the
    biosimilar drug with service_date inside the half-open window are repriced
    in place (no ClaimAdjustment, no ledger movement); member cost share is
    recomputed under the new waiver."""
    start = pdate(policy["effective_start"])
    end = pdate(policy["effective_end"])
    candidates = [
        c
        for c in db["claims"].values()
        if c["drug_id"] == policy["biosimilar_drug_id"]
        and c["status"] in ("APPROVED_FOR_PAYMENT", "PENDED")
        and start <= pdate(c["service_date"]) < end
    ]
    candidates.sort(key=lambda c: (pdate(c["service_date"]), c["_seq"]))
    for claim in candidates:
        drug = db["drugs"][claim["drug_id"]]
        old_schedule = claim["asp_schedule_id_used"]
        res = price_claim(drug, claim, claim["asp_rate_cents"], pdate(claim["service_date"]))
        claim["addon_pct_applied"] = float(res["addon"])
        claim["payable_waste_units"] = res["payable_waste"]
        claim["allowed_amount_cents"] = res["allowed"]
        claim["member_cost_share_cents"] = res["mcs"]
        claim["asp_schedule_id_used"] = old_schedule
        touch(claim)
