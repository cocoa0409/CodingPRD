"""Derived-state recomputation (PRD sections 2.4 and 2.9).

Derived fields are never patched incrementally: each helper re-derives the whole
figure from its source rows.  A re-derivation that moves at least one value is a
mutation of the owning row and therefore refreshes updated_at and increments
version; a re-derivation that changes nothing writes nothing.
"""

import db
from services import calc


# ---------------------------------------------------------------------------
# programme fund singleton
# ---------------------------------------------------------------------------

def ensure_fund():
    if db.store.fund is None:
        record = {}
        db.stamp_full(record)
        record.update({
            "cash_balance_cents": 0,
            "outstanding_points": 0,
            "breakage_rate_pct": calc.as_float(calc.DEFAULT_BREAKAGE_RATE_PCT),
            "point_liability_cents": 0,
            "solvency_ratio": calc.as_float(calc.SOLVENCY_SENTINEL),
            "status": "HEALTHY",
            "last_revalued_at": None,
        })
        # keep the common fields at the tail of the payload
        for key in ("created_at", "updated_at", "version"):
            record[key] = record.pop(key)
        db.store.fund = record
    return db.store.fund


def fund():
    return ensure_fund()


def _fund_values():
    settled_cash = sum(
        p["cash_due_cents"] for p in db.store.purchases.values() if p["status"] == "SETTLED"
    )
    paid_out = sum(
        b["net_payable_cents"] for b in db.store.batches.values() if b["status"] == "PAID"
    )
    cash = settled_cash - paid_out
    outstanding = sum(e["points"] for e in db.store.ledger_entries.values())
    record = ensure_fund()
    liability = calc.point_liability(outstanding, record["breakage_rate_pct"])
    ratio = calc.solvency(cash, liability)
    return {
        "cash_balance_cents": cash,
        "outstanding_points": outstanding,
        "point_liability_cents": liability,
        "solvency_ratio": calc.as_float(ratio),
        "status": calc.fund_status(ratio),
    }


def recompute_fund():
    """Implicit revaluation at the end of a request that moved points or cash."""
    record = ensure_fund()
    db.apply_derived(record, _fund_values())
    return record


def revalue_fund(stamp_last_revalued):
    """Explicit revaluation: always one version increment."""
    record = ensure_fund()
    record.update(_fund_values())
    if stamp_last_revalued:
        record["last_revalued_at"] = db.now_iso()
    db.touch(record)
    return record


def fund_is_impaired():
    """Read the current posture without writing: a refused request must not
    mutate the fund row."""
    return _fund_values()["status"] == "IMPAIRED"


def fund_cash():
    return _fund_values()["cash_balance_cents"]


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

def add_entry(member_id, entry_type, points, source_stay_id=None,
              source_redemption_id=None, source_purchase_id=None,
              reversal_of_entry_id=None, adjustment_reason=None):
    record = {}
    db.stamp_light(record)
    record.update({
        "member_id": member_id,
        "entry_type": entry_type,
        "points": points,
        "source_stay_id": source_stay_id,
        "source_redemption_id": source_redemption_id,
        "source_purchase_id": source_purchase_id,
        "reversal_of_entry_id": reversal_of_entry_id,
        "adjustment_reason": adjustment_reason,
        "liability_unit_cost_cents_per_1000": calc.LIABILITY_UNIT_COST_CENTS_PER_1000,
    })
    record["created_at"] = record.pop("created_at")
    db.store.ledger_entries[record["id"]] = record
    return record


def entries_for_stay(stay_id):
    return db.ordered([e for e in db.store.ledger_entries.values()
                       if e.get("source_stay_id") == stay_id])


def entries_for_purchase(purchase_id):
    return db.ordered([e for e in db.store.ledger_entries.values()
                       if e.get("source_purchase_id") == purchase_id])


def entries_for_redemption(redemption_id):
    return db.ordered([e for e in db.store.ledger_entries.values()
                       if e.get("source_redemption_id") == redemption_id])


def reverse_entries(entries, **links):
    produced = []
    for entry in entries:
        produced.append(add_entry(
            entry["member_id"], "REVERSAL", -entry["points"],
            source_stay_id=entry.get("source_stay_id"),
            source_redemption_id=entry.get("source_redemption_id"),
            source_purchase_id=entry.get("source_purchase_id"),
            reversal_of_entry_id=entry["id"],
            **links
        ))
    return produced


# ---------------------------------------------------------------------------
# member
# ---------------------------------------------------------------------------

def member_entries(member_id):
    return [e for e in db.store.ledger_entries.values() if e["member_id"] == member_id]


def recompute_member(member):
    member_id = member["id"]
    balance = 0
    lifetime = 0
    for entry in db.store.ledger_entries.values():
        if entry["member_id"] != member_id:
            continue
        balance += entry["points"]
        if entry["points"] > 0:
            lifetime += entry["points"]

    year = db.clock_year()
    revenue = 0
    nights = 0
    for stay in db.store.stays.values():
        if stay["member_id"] != member_id:
            continue
        if stay["status"] != "POSTED_QUALIFYING":
            continue
        if db.year_of(stay["checkin_date"]) != year:
            continue
        revenue += stay["room_revenue_cents"]
        plan = db.store.rate_plans.get(stay["rate_plan_id"])
        if plan is not None and plan.get("counts_toward_elite"):
            nights += stay["nights"]

    # A purchase consumes the member's annual allowance from the moment it is
    # recorded: "The points_quantity is nevertheless added to the member's
    # points_purchased_current_year ... so both caps are consumed by the pending
    # purchase and cannot be defeated by leaving purchases unsettled" (PRD 3.8).
    # A refund takes the purchase back out of the counted set.
    purchased = 0
    for purchase in db.store.purchases.values():
        if purchase["member_id"] != member_id:
            continue
        if purchase["status"] not in ("PENDING", "SETTLED"):
            continue
        if db.year_of(purchase["created_at"]) != year:
            continue
        purchased += purchase["points_quantity"]

    db.apply_derived(member, {
        "elite_tier": calc.tier_for_nights(nights),
        "qualifying_nights_ytd": nights,
        "qualifying_revenue_cents_ytd": revenue,
        "point_balance": balance,
        "lifetime_points_earned": lifetime,
        "points_purchased_current_year": purchased,
    })
    return member


def member_purchase_consumption(member_id):
    """Points already consumed against the member's annual cap.  A purchase that
    is still PENDING consumes the cap so that it cannot be defeated by leaving
    purchases unsettled (PRD section 3.8)."""
    year = db.clock_year()
    total = 0
    for purchase in db.store.purchases.values():
        if purchase["member_id"] != member_id:
            continue
        if purchase["status"] not in ("PENDING", "SETTLED"):
            continue
        if db.year_of(purchase["created_at"]) != year:
            continue
        total += purchase["points_quantity"]
    return total


def partner_month_consumption(partner_id):
    month = db.clock_month_key()
    total = 0
    for purchase in db.store.purchases.values():
        if purchase.get("partner_id") != partner_id:
            continue
        if purchase["status"] not in ("PENDING", "SETTLED"):
            continue
        if db.month_key_of(purchase["created_at"]) != month:
            continue
        total += purchase["points_quantity"]
    return total


def recompute_partner(partner):
    # As with the member's annual allowance, a pending wholesale sale already
    # commits the partner's monthly volume (PRD 3.8), so PENDING and SETTLED both
    # count and only a refund releases the volume again.
    db.apply_derived(partner,
                     {"purchased_points_mtd": partner_month_consumption(partner["id"])})
    return partner


# ---------------------------------------------------------------------------
# hotel
# ---------------------------------------------------------------------------

def recompute_hotel(hotel):
    hotel_id = hotel["id"]

    fee_charges = 0
    for stay in db.store.stays.values():
        if stay["hotel_id"] != hotel_id:
            continue
        if stay["status"] not in calc.FEE_LEDGER_STATUSES:
            continue
        fee_charges += stay["program_fee_assessed_cents"]
    fee_credits = 0
    for batch in db.store.batches.values():
        if batch["hotel_id"] != hotel_id:
            continue
        if batch["status"] != "PAID":
            continue
        fee_credits += batch["fee_offset_base_cents"]

    owed = 0
    for redemption in db.store.redemptions.values():
        if redemption["hotel_id"] != hotel_id:
            continue
        if redemption["reimbursement_status"] not in ("ACCRUED", "BATCHED"):
            continue
        owed += redemption["settled_reimbursement_cents"]

    recovery = 0
    denials = 0
    for delivery in db.store.deliveries.values():
        stay = db.store.stays.get(delivery["stay_id"])
        if stay is None or stay["hotel_id"] != hotel_id:
            continue
        if delivery["status"] == "DELIVERED":
            recovery += delivery["cost_recovery_cents"]
        if delivery["status"] in ("DENIED", "ESCALATED", "DENIED_FINAL"):
            denials += 1

    year = db.clock_year()
    blackout_days = 0
    for window in db.store.blackout_windows.values():
        if window["hotel_id"] != hotel_id:
            continue
        if window["status"] != "ACTIVE":
            continue
        if db.year_of(window["start_date"]) != year:
            continue
        blackout_days += window["day_count"]

    db.apply_derived(hotel, {
        "fee_ledger_balance_cents": fee_charges - fee_credits,
        "reimbursement_owed_cents": owed,
        "benefit_recovery_owed_cents": recovery,
        "benefit_denial_count": denials,
        "blackout_days_used_current_year": blackout_days,
    })
    return hotel


def evaluate_delinquency(hotel):
    """ACTIVE -> FEE_DELINQUENT once the fee ledger passes the threshold."""
    if (hotel["status"] == "ACTIVE"
            and hotel["fee_ledger_balance_cents"] > calc.FEE_DELINQUENCY_THRESHOLD_CENTS):
        hotel["status"] = "FEE_DELINQUENT"
        db.touch(hotel)
        return True
    return False


def evaluate_delinquency_cure(hotel):
    """FEE_DELINQUENT -> ACTIVE once the fee ledger is fully settled."""
    if hotel["status"] == "FEE_DELINQUENT" and hotel["fee_ledger_balance_cents"] <= 0:
        hotel["status"] = "ACTIVE"
        db.touch(hotel)
        return True
    return False


# ---------------------------------------------------------------------------
# elite benefit obligations
# ---------------------------------------------------------------------------

def deliveries_for_stay(stay_id):
    return db.ordered([d for d in db.store.deliveries.values() if d["stay_id"] == stay_id])


def waive_obligations_no_longer_entitled(member):
    """After a tier fall, every still-OBLIGATED benefit of that member whose type
    the new tier no longer entitles is waived."""
    entitled = calc.entitled_benefits(member["elite_tier"])
    touched_hotels = set()
    for delivery in db.ordered(list(db.store.deliveries.values())):
        if delivery["status"] != "OBLIGATED":
            continue
        stay = db.store.stays.get(delivery["stay_id"])
        if stay is None or stay["member_id"] != member["id"]:
            continue
        if delivery["benefit_type"] in entitled:
            continue
        delivery["status"] = "WAIVED"
        db.touch(delivery)
        touched_hotels.add(stay["hotel_id"])
    return touched_hotels


def synthesize_obligations(stay, hotel):
    """Create one obligation per benefit the tier recorded at check-in earns."""
    created = []
    for benefit_type in calc.entitled_benefits(stay["tier_at_checkin"]):
        record = {}
        db.stamp_full(record)
        record.update({
            "stay_id": stay["id"],
            "benefit_type": benefit_type,
            "status": "OBLIGATED",
            "cost_recovery_cents": 0,
            "denial_reason": None,
        })
        for key in ("created_at", "updated_at", "version"):
            record[key] = record.pop(key)
        db.store.deliveries[record["id"]] = record
        created.append(record)
    return created
