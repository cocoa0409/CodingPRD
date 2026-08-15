"""Business logic: pricing, schedule estimates, sweeps, and cascades.

Derived ledgers (PRD sections 2.8, 3.5, 3.7) are computed from source records
at every read so the conservation invariants hold by construction:
  - Community.incentive_budget_remaining_cents = total - sum(APPROVED amounts)
  - PurchaseAgreement.options_total_cents     = sum(line_total over SELECTED/CONFIRMED/INSTALLED)
  - PurchaseAgreement.change_fees_total_cents = sum(change_fee_cents over selections)
  - PurchaseAgreement.incentives_total_cents  = sum(amount over APPROVED requests)
"""

from datetime import timedelta
from decimal import Decimal

import db
from constants import (
    BUILD_STAGES,
    STAGE_ORDINAL,
    STAGE_DURATIONS_DAYS,
    CLOSE_BUFFER_DAYS,
    LOT_TYPE_PREMIUM_CENTS,
    PREMIUM_CAP_CENTS,
    RE_RELEASE_UPLIFT_PCT,
    INCENTIVE_CAP_PCT,
    WARRANTY_TERM_MONTHS,
)
from util import rhu, ceil_days, decimal_of, parse_dt


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def selections_of(agreement_id):
    return [s for s in db.all_of("selections") if s["agreement_id"] == agreement_id]


def milestones_of(agreement_id):
    return sorted(
        (m for m in db.all_of("milestones") if m["agreement_id"] == agreement_id),
        key=lambda m: m["sequence_no"],
    )


def incentives_of(agreement_id):
    return [r for r in db.all_of("incentive_requests") if r["agreement_id"] == agreement_id]


def phases_of(community_id):
    return [p for p in db.all_of("price_phases") if p["community_id"] == community_id]


# ---------------------------------------------------------------------------
# Derived ledgers
# ---------------------------------------------------------------------------

def options_total_cents(agreement_id):
    return sum(
        s["line_total_cents"]
        for s in selections_of(agreement_id)
        if s["status"] in ("SELECTED", "CONFIRMED", "INSTALLED")
    )


def change_fees_total_cents(agreement_id):
    return sum(s["change_fee_cents"] for s in selections_of(agreement_id))


def incentives_total_cents(agreement_id):
    return sum(
        r["amount_cents"] for r in incentives_of(agreement_id) if r["status"] == "APPROVED"
    )


def community_budget_remaining_cents(community):
    approved = 0
    for req in db.all_of("incentive_requests"):
        if req["status"] != "APPROVED":
            continue
        agr = db.get("agreements", req["agreement_id"])
        if agr is not None and agr["community_id"] == community["id"]:
            approved += req["amount_cents"]
    return community["incentive_budget_total_cents"] - approved


def incentive_cap_cents(agreement):
    """round_half_up(INCENTIVE_CAP_PCT * provisional_total_cents); the cap base
    is the immutable provisional total, never final_total_cents."""
    return rhu(INCENTIVE_CAP_PCT * Decimal(agreement["provisional_total_cents"]))


# ---------------------------------------------------------------------------
# Price phases (status derived from the logical clock at every read)
# ---------------------------------------------------------------------------

def derive_phase_status(phase, now):
    if now < phase["_from_dt"]:
        return "SCHEDULED"
    if now < phase["_to_dt"]:
        return "ACTIVE"
    return "EXPIRED"


def active_phase_uplift(community_id, now):
    """uplift_pct (as Decimal) of the single ACTIVE phase, else 0."""
    for phase in phases_of(community_id):
        if phase["_from_dt"] <= now < phase["_to_dt"]:
            return decimal_of(phase["uplift_pct"])
    return Decimal("0")


# ---------------------------------------------------------------------------
# Pricing (calculation lot_release_pricing / agreement_pricing)
# ---------------------------------------------------------------------------

def lot_release_price(lot, now):
    """Initial DRAFT -> RELEASED pricing: each component rounded half up to
    whole cents FIRST, then summed (pinned rounding order)."""
    premium_raw = LOT_TYPE_PREMIUM_CENTS[lot["lot_type"]] + lot["view_adjustment_cents"]
    premium = min(PREMIUM_CAP_CENTS, premium_raw)
    factor = Decimal("1") + active_phase_uplift(lot["community_id"], now)
    base_component = rhu(Decimal(lot["base_price_cents"]) * factor)
    premium_component = rhu(Decimal(premium) * factor)
    return base_component + premium_component


def lot_rerelease_price(lot):
    """Re-release variant (SOLD -> RELEASED after fallout): previous release
    price inflated by RE_RELEASE_UPLIFT_PCT, round half up; phase windows and
    lot-type premiums are NOT re-evaluated."""
    return rhu(Decimal(lot["release_price_cents"]) * (Decimal("1") + RE_RELEASE_UPLIFT_PCT))


# ---------------------------------------------------------------------------
# Closing estimates and slippage (calculations closing_date_estimate,
# slippage_flag)
# ---------------------------------------------------------------------------

def recompute_estimates(agreement, now):
    """Both variants consider only NOT_STARTED milestones in sequence order;
    partial progress inside the current stage is ignored."""
    remaining = [m for m in milestones_of(agreement["id"]) if m["status"] == "NOT_STARTED"]
    std_days = sum(m["planned_duration_days"] for m in remaining) + CLOSE_BUFFER_DAYS
    pad_days = sum(ceil_days(m["planned_duration_days"]) for m in remaining) + CLOSE_BUFFER_DAYS
    standard = now + timedelta(days=std_days)
    padded = now + timedelta(days=pad_days)
    agreement["estimated_close_standard"] = db.fmt_ts(standard)
    agreement["estimated_close_padded"] = db.fmt_ts(padded)
    # Slippage: strictly greater, timestamps compared to the second.
    agreement["slippage_flag"] = (
        padded.replace(microsecond=0) > agreement["_outside_dt"].replace(microsecond=0)
    )


# ---------------------------------------------------------------------------
# Construction milestone completion cascade (PRD section 3.6)
# ---------------------------------------------------------------------------

def complete_milestone(milestone, now):
    ts = db.fmt_ts(now)
    milestone["status"] = "COMPLETE"
    milestone["completed_at"] = ts
    milestone["buyer_notified_at"] = ts  # milestone communication to the buyer
    db.touch(milestone)

    agreement = db.get("agreements", milestone["agreement_id"])
    remaining = [m for m in milestones_of(agreement["id"]) if m["status"] == "NOT_STARTED"]
    agreement["current_stage"] = remaining[0]["stage"] if remaining else "COMPLETE"
    new_ordinal = STAGE_ORDINAL[agreement["current_stage"]]

    # Sweep 1: SELECTED selections whose cutoff now lies strictly behind the
    # new stage lapse for free (CUTOFF_EXPIRED, no change fee).
    # Sweep 2: CONFIRMED selections whose install stage now lies strictly
    # behind the new stage become INSTALLED.
    for sel in selections_of(agreement["id"]):
        item = db.get("option_items", sel["option_item_id"])
        if item is None:
            continue
        if sel["status"] == "SELECTED" and STAGE_ORDINAL[item["cutoff_stage"]] < new_ordinal:
            sel["status"] = "CANCELLED"
            sel["cancel_reason"] = "CUTOFF_EXPIRED"
            db.touch(sel)
        elif sel["status"] == "CONFIRMED" and STAGE_ORDINAL[item["install_stage"]] < new_ordinal:
            sel["status"] = "INSTALLED"
            db.touch(sel)

    recompute_estimates(agreement, now)
    db.touch(agreement)


# ---------------------------------------------------------------------------
# Agreement cancellation cascade (PRD section 3.8; also the section 3.4
# contingency-deadline sweep path with reason CONTINGENCY_EXPIRED)
# ---------------------------------------------------------------------------

def cancel_agreement(agreement, reason, now):
    from constants import EARNEST_FORFEIT_PCT

    status = agreement["status"]
    earnest = agreement["earnest_money_deposited_cents"]
    # earnest_money_refund: full refund everywhere except CONTINGENCIES_CLEARED
    # + BUYER_DEFAULT, which forfeits round_half_up(earnest * 0.25).
    if (
        reason == "CONTINGENCY_EXPIRED"
        or status in ("DRAFT", "PENDING_CONTINGENCIES")
        or (status == "CONTINGENCIES_CLEARED" and reason == "BUILDER_DEFAULT")
    ):
        refund, forfeited = earnest, 0
    else:
        forfeited = rhu(Decimal(earnest) * EARNEST_FORFEIT_PCT)
        refund = earnest - forfeited

    agreement["status"] = "CANCELLED"
    agreement["cancel_reason"] = reason
    agreement["refund_amount_cents"] = refund
    agreement["forfeited_amount_cents"] = forfeited

    # Selections in SELECTED/CONFIRMED -> CANCELLED (AGREEMENT_CANCELLED, no fee).
    for sel in selections_of(agreement["id"]):
        if sel["status"] in ("SELECTED", "CONFIRMED"):
            sel["status"] = "CANCELLED"
            sel["cancel_reason"] = "AGREEMENT_CANCELLED"
            db.touch(sel)

    # APPROVED incentives -> REVOKED; the derived budget ledger restores itself.
    for req in incentives_of(agreement["id"]):
        if req["status"] == "APPROVED":
            req["status"] = "REVOKED"
            db.touch(req)

    # Post-signing fallout returns the lot to RELEASED with re-release
    # repricing and release_count += 1. A DRAFT agreement never marked the lot
    # SOLD, so the lot is left entirely unchanged.
    if status in ("PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED"):
        lot = db.get("lots", agreement["lot_id"])
        if lot is not None and lot["status"] == "SOLD":
            lot["status"] = "RELEASED"
            lot["reserved_buyer_id"] = None
            lot["hold_expires_at"] = None
            lot["release_count"] += 1
            lot["release_price_cents"] = lot_rerelease_price(lot)
            db.touch(lot)

    db.touch(agreement)


# ---------------------------------------------------------------------------
# Closing (PRD section 3.9)
# ---------------------------------------------------------------------------

def close_agreement(agreement, now):
    agreement["status"] = "CLOSED"
    # agreement_pricing final variant: provisional + options + fees - incentives.
    agreement["final_total_cents"] = (
        agreement["provisional_total_cents"]
        + options_total_cents(agreement["id"])
        + change_fees_total_cents(agreement["id"])
        - incentives_total_cents(agreement["id"])
    )
    agreement["warranty_status"] = "ENROLLED"
    agreement["warranty_term_months"] = WARRANTY_TERM_MONTHS
    agreement["warranty_enrolled_at"] = db.fmt_ts(now)

    lot = db.get("lots", agreement["lot_id"])
    if lot is not None and lot["status"] == "SOLD":
        lot["status"] = "CLOSED"
        db.touch(lot)

    db.touch(agreement)


# ---------------------------------------------------------------------------
# Clock sweep (PRD section 2.6): phase status re-derivation is lazy (status is
# computed from the clock at every read), so the sweep materializes as the
# reservation-hold release and the contingency-deadline auto-cancellation.
# ---------------------------------------------------------------------------

def run_clock_sweep(now):
    # Expired reservation holds: released without repricing (hold churn never
    # reprices; release_count untouched).
    for lot in db.all_of("lots"):
        if lot["status"] == "RESERVED" and lot["hold_expires_at"] is not None:
            if parse_dt(lot["hold_expires_at"], "hold_expires_at") <= now:
                lot["status"] = "RELEASED"
                lot["reserved_buyer_id"] = None
                lot["hold_expires_at"] = None
                db.touch(lot)

    # Contingency-deadline auto-cancellation: clock strictly past the deadline
    # with any contingency still PENDING -> full-refund cancellation.
    for agreement in db.all_of("agreements"):
        if agreement["status"] != "PENDING_CONTINGENCIES":
            continue
        if now > agreement["_deadline_dt"] and any(
            agreement[field] == "PENDING"
            for field in (
                "financing_contingency_status",
                "appraisal_contingency_status",
                "sale_of_home_contingency_status",
            )
        ):
            cancel_agreement(agreement, "CONTINGENCY_EXPIRED", now)


# ---------------------------------------------------------------------------
# Serializers (derived fields injected at read time)
# ---------------------------------------------------------------------------

def ser_community(community):
    d = db.public(community)
    d["incentive_budget_remaining_cents"] = community_budget_remaining_cents(community)
    return d


def ser_phase(phase):
    d = db.public(phase)
    d["status"] = derive_phase_status(phase, db.now())
    return d


def ser_lot(lot):
    return db.public(lot)


def ser_plan(plan):
    return db.public(plan)


def ser_option_item(item):
    return db.public(item)


def ser_buyer(buyer):
    return db.public(buyer)


def ser_agreement(agreement):
    d = db.public(agreement)
    d["options_total_cents"] = options_total_cents(agreement["id"])
    d["change_fees_total_cents"] = change_fees_total_cents(agreement["id"])
    d["incentives_total_cents"] = incentives_total_cents(agreement["id"])
    return d


def ser_selection(selection):
    return db.public(selection)


def ser_milestone(milestone):
    return db.public(milestone)


def ser_incentive(request_ent):
    return db.public(request_ent)
