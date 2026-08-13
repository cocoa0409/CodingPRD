"""Calculation rules (SCAFFOLD 1.3): ranking score, estimated obligation,
scheduled amount, certified payment, advance cap, ranking waterfall."""
from decimal import Decimal

from db import STORE
from util import dec, money_mul, round_cents, round_score, is_num

TIER_HIGH = Decimal("60")
TIER_HIGH_BONUS = Decimal("10")
TIER_MID = Decimal("40")
TIER_MID_BONUS = Decimal("5")
SCORE_CAP = Decimal("100")


def ranking_score(program_id, answers):
    """Weighted scoring with tier bonus keyed on the base alone; evaluation order
    pinned: base -> tier lookup -> addition -> cap -> round_half_up(2dp)."""
    base = Decimal("0")
    answers = answers or {}
    for c in STORE.criteria.values():
        if c["program_id"] != program_id:
            continue
        pts = answers.get(c["criterion_code"], 0)
        if not is_num(pts):
            pts = 0
        pts = min(max(dec(pts), Decimal("0")), dec(c["max_points"]))
        base += pts * dec(c["weight"])
    if base >= TIER_HIGH:
        bonus = TIER_HIGH_BONUS
    elif base >= TIER_MID:
        bonus = TIER_MID_BONUS
    else:
        bonus = Decimal("0")
    score = base + bonus
    if score > SCORE_CAP:
        score = SCORE_CAP
    return round_score(score)


def applicable_rate_cents(rate_row, applicant_row):
    """HU applicants pay the hu rate; snapshot taken at item creation."""
    if applicant_row["historically_underserved"]:
        return rate_row["hu_rate_cents"]
    return rate_row["standard_rate_cents"]


def rate_for_code(program_id, practice_code):
    for r in STORE.rates.values():
        if r["program_id"] == program_id and r["practice_code"] == practice_code:
            return r
    return None


def estimated_obligation_cents(application, applicant_row):
    """Sum over planned practices of per-line round_half_up(qty * rate);
    lines rounded first, then summed — never the reverse."""
    total = 0
    for pp in application["planned_practices"]:
        rate_row = rate_for_code(application["program_id"], pp["practice_code"])
        rate = applicable_rate_cents(rate_row, applicant_row)
        total += money_mul(pp["quantity"], rate)
    return total


def scheduled_amount_cents(planned_quantity, applicable_rate):
    return money_mul(planned_quantity, applicable_rate)


def certified_payment_cents(item_row, documented_cost_cents):
    """min(round_half_up(certified_quantity * applicable_rate), documented_cost)."""
    by_rate = money_mul(item_row["certified_quantity"], item_row["applicable_rate_cents"])
    return min(by_rate, documented_cost_cents)


def advance_cap_cents(program, item_row):
    """round_half_up(advance_cap_pct * scheduled_amount_cents)."""
    return round_cents(dec(program["advance_cap_pct"]) * dec(item_row["scheduled_amount_cents"]))


def recompute_contract_obligated(contract):
    """Sum of scheduled_amount_cents over non-terminal items; sum of rounded
    lines, never a re-rounded total."""
    total = 0
    for i in STORE.items.values():
        if i["contract_id"] != contract["id"]:
            continue
        if i["certification_status"] in ("CANCELLED", "EXPIRED", "CERTIFICATION_REVOKED"):
            continue
        total += i["scheduled_amount_cents"]
    if contract["obligated_amount_cents"] != total:
        contract["obligated_amount_cents"] = total
        return True
    return False


HU_POOL_TYPE = {
    "BEGINNING_FARMER": "HU_BEGINNING_FARMER",
    "SOCIALLY_DISADVANTAGED": "HU_SOCIALLY_DISADVANTAGED",
    "LIMITED_RESOURCE": "HU_LIMITED_RESOURCE",
    "VETERAN": "HU_VETERAN",
}


def run_ranking_waterfall(program):
    """Selection waterfall. Selection mutates no pool balances — it carries a
    shadow availability per pool, decremented per selection, so earlier picks
    constrain later ones within the same run."""
    from helpers import touch  # local import to avoid a cycle

    candidates = [
        a for a in STORE.applications.values()
        if a["program_id"] == program["id"] and a["status"] == "SCREENED_IN"
    ]
    candidates.sort(key=lambda a: (
        -dec(a["ranking_score"]),
        a["estimated_obligation_cents"],
        a["created_at"],
        a["_seq"],
    ))
    pools = [p for p in STORE.pools.values() if p["program_id"] == program["id"]]
    pools.sort(key=lambda p: (p["created_at"], p["_seq"]))
    shadow = {
        p["id"]: p["allocated_cents"] - p["obligated_cents"] - p["paid_cents"]
        for p in pools
    }
    selected = 0
    not_selected = 0
    for app in candidates:
        applicant_row = STORE.applicants.get(app["applicant_id"])
        tried_types = []
        if applicant_row and applicant_row["historically_underserved"]:
            tried_types.append(HU_POOL_TYPE[applicant_row["hu_category"]])
            tried_types.append("GENERAL")
        else:
            tried_types.append("GENERAL")
        chosen = None
        for ptype in tried_types:
            for p in pools:
                if p["pool_type"] != ptype:
                    continue
                if app["estimated_obligation_cents"] <= shadow[p["id"]]:
                    chosen = p
                    break
            if chosen is not None:
                break
        if chosen is not None:
            shadow[chosen["id"]] -= app["estimated_obligation_cents"]
            app["status"] = "SELECTED"
            app["funded_pool_id"] = chosen["id"]
            touch(app)
            selected += 1
        else:
            app["status"] = "NOT_SELECTED"
            touch(app)
            not_selected += 1
    program["ranking_run_count"] = 1
    touch(program)
    return {
        "ranked_count": len(candidates),
        "selected_count": selected,
        "not_selected_count": not_selected,
    }
