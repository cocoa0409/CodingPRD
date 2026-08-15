from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP

import db
from response import now_ts


def _d(s):
    return date.fromisoformat(s)


def maybe_suspend(pharmacy):
    """Auto-suspension: balance at or below the negated threshold (inclusive)."""
    if (
        pharmacy["status"] == "ACTIVE"
        and pharmacy["balance_cents"] <= -pharmacy["auto_suspend_threshold_cents"]
    ):
        pharmacy["status"] = "SUSPENDED"


def find_active_entry(plan_id, drug_id):
    for e in db.formulary_entries.values():
        if (
            e["plan_id"] == plan_id
            and e["drug_id"] == drug_id
            and e["status"] == "ACTIVE"
        ):
            return e
    return None


def approved_pas(member_id, drug_id):
    """APPROVED PAs for (member, drug), ranked expires_at ASC then created_at ASC."""
    rows = [
        p
        for p in db.prior_authorizations.values()
        if p["member_id"] == member_id and p["drug_id"] == drug_id and p["status"] == "APPROVED"
    ]
    rows.sort(key=lambda p: (p["expires_at"], p["created_at"], p["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# DUR screening
# ---------------------------------------------------------------------------

def run_dur_screening(claim_id, member_id, drug, quantity, days_supply, fill_date):
    """Write one OPEN DurAlert row per (claim, alert_type) that fires.

    Fill windows are half-open: [fill_date, fill_date + days_supply). Only other
    PAID claims of the same member are compared. A live (OPEN or OVERRIDDEN)
    alert row of the same type suppresses a duplicate.
    """
    new_start = fill_date
    new_end = fill_date + timedelta(days=days_supply)
    fired = set()
    for c in db.claims.values():
        if c["id"] == claim_id or c["member_id"] != member_id or c["status"] != "PAID":
            continue
        c_start = _d(c["fill_date"])
        c_end = c_start + timedelta(days=c["days_supply"])
        if c_start < new_end and new_start < c_end:
            if c["drug_id"] == drug["id"]:
                fired.add(("EARLY_REFILL", "MEDIUM"))
            else:
                other = db.drugs.get(c["drug_id"])
                if other and other["therapeutic_class"] == drug["therapeutic_class"]:
                    fired.add(("THERAPEUTIC_DUPLICATION", "MEDIUM"))
    if quantity > drug["max_daily_dose_units"] * days_supply:
        fired.add(("HIGH_DAILY_DOSE", "HIGH"))
    for alert_type, severity in sorted(fired):
        live = any(
            a
            for a in db.dur_alerts.values()
            if a["claim_id"] == claim_id
            and a["alert_type"] == alert_type
            and a["status"] in ("OPEN", "OVERRIDDEN")
        )
        if live:
            continue
        alert_id = db.new_id()
        db.dur_alerts[alert_id] = {
            "id": alert_id,
            "created_at": now_ts(),
            "_seq": next(db._seq_counter),
            "claim_id": claim_id,
            "alert_type": alert_type,
            "severity": severity,
            "status": "OPEN",
            "override_code": None,
        }


# ---------------------------------------------------------------------------
# The eleven pinned adjudication edits (validations 12.1 - 12.11)
# ---------------------------------------------------------------------------

def adjudicate(claim_id, member, plan, drug, pharmacy, quantity, days_supply, fill_date):
    """Return (reject_reasons, formulary_entry, selected_pa).

    Edits run in pinned order; every failed edit's error_id is collected.
    DUR screening runs only after edits 1-10 all pass; edit 11 then checks
    for any remaining OPEN HIGH alert on this claim.
    """
    reasons = []

    # Edit 1: member eligibility (member ACTIVE, fill date inside inclusive window)
    if (
        member["status"] != "ACTIVE"
        or not (_d(member["eligibility_start_date"]) <= fill_date <= _d(member["eligibility_end_date"]))
    ):
        reasons.append("ERR_MEMBER_INELIGIBLE")

    # Edit 2: plan ACTIVE
    if plan["status"] != "ACTIVE":
        reasons.append("ERR_PLAN_NOT_ACTIVE")

    # Edit 3: ACTIVE formulary entry for (member's plan, drug)
    entry = find_active_entry(member["plan_id"], drug["id"])
    if entry is None:
        reasons.append("ERR_DRUG_NOT_ON_FORMULARY")

    # Edit 4: specialty channel
    if drug["is_specialty"] and pharmacy["channel"] != "SPECIALTY":
        reasons.append("ERR_SPECIALTY_CHANNEL_REQUIRED")

    # Edits 5-7: prior authorization presence, currency, quantity
    selected_pa = None
    if entry is not None and entry["pa_required"]:
        approved = approved_pas(member["id"], drug["id"])
        if not approved:
            reasons.append("ERR_PRIOR_AUTH_REQUIRED")
        else:
            selected_pa = approved[0]
            if _d(selected_pa["expires_at"]) < fill_date:
                reasons.append("ERR_PA_EXPIRED")
            if quantity > selected_pa["approved_quantity"] - selected_pa["quantity_consumed"]:
                reasons.append("ERR_PA_QUANTITY_EXCEEDED")

    # Edit 8: step therapy (inclusive lookback window, PAID step-drug claims only)
    if entry is not None and entry["step_therapy_required"]:
        window_start = fill_date - timedelta(days=entry["step_therapy_lookback_days"])
        satisfied = any(
            c["member_id"] == member["id"]
            and c["drug_id"] == entry["step_drug_id"]
            and c["status"] == "PAID"
            and window_start <= _d(c["fill_date"]) <= fill_date
            for c in db.claims.values()
        )
        if not satisfied:
            reasons.append("ERR_STEP_THERAPY_NOT_MET")

    # Edit 9: quantity ceiling (equality passes)
    if entry is not None and quantity > entry["quantity_limit_per_fill"]:
        reasons.append("ERR_QUANTITY_LIMIT_EXCEEDED")

    # Edit 10: days-supply ceiling (equality passes)
    if entry is not None and days_supply > entry["max_days_supply"]:
        reasons.append("ERR_DAYS_SUPPLY_EXCEEDED")

    # DUR screening + edit 11 (hard stop) only once edits 1-10 pass
    if not reasons:
        run_dur_screening(claim_id, member["id"], drug, quantity, days_supply, fill_date)
        hard_stop = any(
            a["claim_id"] == claim_id and a["status"] == "OPEN" and a["severity"] == "HIGH"
            for a in db.dur_alerts.values()
        )
        if hard_stop:
            reasons.append("ERR_DUR_HARD_STOP")

    return reasons, entry, selected_pa


# ---------------------------------------------------------------------------
# Pricing, copay assistance, and accumulator posting
# ---------------------------------------------------------------------------

def _round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_up_cents(value):
    """Percentage coinsurance rounds up to whole cents at its single rounding point."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_UP))


def price_claim(member, plan, drug, entry, quantity):
    """Pinned pricing order: allowed -> deductible -> copay base -> OOP cap -> card."""
    allowed = drug["unit_cost_cents"] * quantity + plan["dispensing_fee_cents"]
    remaining_ded = max(0, plan["deductible_cents"] - member["deductible_paid_cents"])
    ded_applied = min(allowed, remaining_ded)
    post_ded = allowed - ded_applied
    if entry["copay_type"] == "FLAT":
        copay_base = entry["copay_flat_cents"]
    else:
        copay_base = _round_up_cents(
            Decimal(allowed) * Decimal(str(entry["copay_percentage"])) / Decimal(100)
        )
    copay_owed = min(copay_base, post_ded)
    patient_resp_before_oop = ded_applied + copay_owed
    remaining_oop = max(0, plan["oop_max_cents"] - member["oop_paid_cents"])
    patient_resp = min(patient_resp_before_oop, remaining_oop)

    card_applied = 0
    if (
        member.get("card_drug_id")
        and member["card_drug_id"] == drug["id"]
        and member["card_balance_cents"] > 0
    ):
        if plan["assistance_model"] == "ACCUMULATOR":
            card_applied = min(
                member["card_balance_cents"],
                max(0, patient_resp - plan["member_min_pay_cents"]),
            )
        else:  # MAXIMIZER
            cap = plan["card_fill_cap_cents"] if plan["card_fill_cap_cents"] > 0 else patient_resp
            card_applied = min(member["card_balance_cents"], patient_resp, cap)

    member_pays = patient_resp - card_applied
    plan_paid = allowed - patient_resp
    return {
        "allowed_cents": allowed,
        "copay_base_cents": copay_base,
        "deductible_applied_cents": ded_applied,
        "card_applied_cents": card_applied,
        "member_pays_cents": member_pays,
        "plan_paid_cents": plan_paid,
    }


def zero_financials(claim):
    claim["allowed_cents"] = 0
    claim["copay_base_cents"] = 0
    claim["deductible_applied_cents"] = 0
    claim["card_applied_cents"] = 0
    claim["member_pays_cents"] = 0
    claim["plan_paid_cents"] = 0
    claim["pa_id"] = None
    claim["rebate_tag"] = "REBATE_INELIGIBLE"


def post_payment(claim, member, plan, pharmacy, pa):
    """Side effects of a claim entering PAID. Financial fields already set."""
    member["deductible_paid_cents"] += min(
        claim["member_pays_cents"], claim["deductible_applied_cents"]
    )
    member["oop_paid_cents"] += claim["member_pays_cents"]
    member["oop_max_reached"] = member["oop_paid_cents"] >= plan["oop_max_cents"]
    if claim["card_applied_cents"] > 0:
        member["card_balance_cents"] -= claim["card_applied_cents"]
    db.touch(member)
    if pa is not None:
        pa["quantity_consumed"] += claim["quantity"]
        db.touch(pa)
    pharmacy["balance_cents"] += claim["plan_paid_cents"]
    db.touch(pharmacy)
    maybe_suspend(pharmacy)


def compensate_payment(claim, member, plan, pharmacy):
    """Reversal: accumulators, card, PA consumption, and ledger return to pre-claim values."""
    member["deductible_paid_cents"] -= min(
        claim["member_pays_cents"], claim["deductible_applied_cents"]
    )
    member["oop_paid_cents"] -= claim["member_pays_cents"]
    member["oop_max_reached"] = member["oop_paid_cents"] >= plan["oop_max_cents"]
    if claim["card_applied_cents"] > 0:
        member["card_balance_cents"] += claim["card_applied_cents"]
    db.touch(member)
    if claim.get("pa_id"):
        pa = db.prior_authorizations.get(claim["pa_id"])
        if pa is not None:
            pa["quantity_consumed"] -= claim["quantity"]
            db.touch(pa)
    pharmacy["balance_cents"] -= claim["plan_paid_cents"]
    db.touch(pharmacy)
    maybe_suspend(pharmacy)
    if claim["rebate_tag"] == "REBATE_ELIGIBLE":
        claim["rebate_tag"] = "REBATE_VOID"


def pay_claim(claim, member, plan, drug, pharmacy, entry, pa):
    """Compute financials, set PAID fields, and run the posting cascade."""
    fin = price_claim(member, plan, drug, entry, claim["quantity"])
    claim.update(fin)
    claim["pa_id"] = pa["id"] if pa is not None else None
    claim["rebate_tag"] = "REBATE_ELIGIBLE" if entry["rebate_eligible"] else "REBATE_INELIGIBLE"
    claim["status"] = "PAID"
    claim["reject_reasons"] = []
    post_payment(claim, member, plan, pharmacy, pa)
