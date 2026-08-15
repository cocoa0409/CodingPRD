"""Multi-entity cascades: closing finalize (PRD 3.5), agreement lot-release
(PRD 3.7), and the clock sweep (PRD 2.5).

Version discipline: one mutation event increments each affected entity's
version by exactly one (PRD 2.4); an entity touched by several links of the
same cascade is touched once.
"""
from db import db
from services.core import (
    hoas_of_parcel,
    lots_of_parcel,
    lots_of_phase,
    recompute_parcel,
    touch,
)
from util import CLOCK, parse_dt


def finalize_cascade(closing):
    """POST /api/lot-closings/{id}/finalize — seven-link cascade."""
    lot = db["lots"][closing["lot_id"]]
    agreement = db["agreements"][closing["agreement_id"]]
    loan = db["loans"][closing["loan_id"]]
    phase = db["phases"][lot["phase_id"]]
    parcel = db["parcels"][phase["parcel_id"]]

    # Link 1: lot CLOSED + lien RELEASED
    lot["sales_status"] = "CLOSED"
    lot["lien_status"] = "RELEASED"
    touch(lot)

    # Closing itself: payment clamped at the loan's current outstanding balance
    payment = min(closing["release_price_cents"], loan["outstanding_balance_cents"])
    closing["payment_applied_cents"] = payment
    closing["finalized_at"] = CLOCK.now_iso()
    closing["status"] = "CLOSED"
    touch(closing)

    # Link 2: agreement count; auto-COMPLETED at the scheduled boundary (== triggers)
    agreement["closed_lot_count"] += 1
    if (agreement["status"] == "ACTIVE"
            and agreement["closed_lot_count"] >= agreement["scheduled_lot_count"]):
        agreement["status"] = "COMPLETED"
    touch(agreement)

    # Links 3-4: release payment lands on the loan; auto PAID_OFF at zero
    # balance with draws outstanding
    loan["outstanding_balance_cents"] -= payment
    loan["total_release_paid_cents"] += payment
    if (loan["outstanding_balance_cents"] == 0
            and loan["total_drawn_cents"] > 0
            and loan["status"] == "ACTIVE"):
        loan["status"] = "PAID_OFF"
    touch(loan)

    # Link 5: parcel derived fields recompute
    recompute_parcel(parcel, bump="always")

    # Link 6: phase SELLOUT / parcel SOLD_OUT (parcel status rides the same
    # mutation event as the recompute — one version increment per request)
    phase_lots = lots_of_phase(phase["id"])
    if (phase["status"] == "ACTIVE"
            and phase["recorded_lot_count"] > 0
            and all(lot_["sales_status"] == "CLOSED" for lot_ in phase_lots)):
        phase["status"] = "SELLOUT"
        touch(phase)
    all_lots = lots_of_parcel(parcel["id"])
    if (parcel["status"] == "ACQUIRED"
            and parcel["total_lots_planned"] > 0
            and all(lot_["sales_status"] == "CLOSED" for lot_ in all_lots)):
        parcel["status"] = "SOLD_OUT"

    # Link 7: HOA ratio auto-transition (integer cross-multiplication, inclusive)
    for hoa in hoas_of_parcel(parcel["id"]):
        if hoa["status"] != "DECLARANT_CONTROL":
            continue
        if (parcel["lots_closed_count"] * 10000
                >= parcel["total_lots_planned"] * hoa["control_transfer_pct_bp"]):
            hoa["status"] = "TRANSITIONING"
            touch(hoa)


def lot_release_cascade(agreement):
    """Declare-default / terminate lot-release cascade (PRD 3.7 links 1-4)."""
    # Links 1-2: cancel every PENDING closing whose lot is reserved under this
    # agreement; each cancelled lot hops lien RELEASE_PENDING -> ENCUMBERED and
    # sales UNDER_CONTRACT -> RESERVED.
    for closing in db["closings"].values():
        if closing["status"] != "PENDING":
            continue
        lot = db["lots"].get(closing["lot_id"])
        if lot is None or lot["reserved_agreement_id"] != agreement["id"]:
            continue
        closing["status"] = "CANCELLED"
        touch(closing)
        if lot["lien_status"] == "RELEASE_PENDING":
            lot["lien_status"] = "ENCUMBERED"
        if lot["sales_status"] == "UNDER_CONTRACT":
            lot["sales_status"] = "RESERVED"
        # lot version bumped in link 3 (single mutation per lot)

    # Link 3: release every RESERVED lot held by this agreement (both lots that
    # were merely reserved and lots that just hopped back from UNDER_CONTRACT).
    for lot in db["lots"].values():
        if lot["reserved_agreement_id"] == agreement["id"] and lot["sales_status"] == "RESERVED":
            lot["sales_status"] = "PLATTED"
            lot["reserved_agreement_id"] = None
            touch(lot)

    # Link 4: parcel derived fields recompute (lots_available_count rises).
    parcel = db["parcels"].get(agreement["parcel_id"])
    if parcel is not None:
        recompute_parcel(parcel, bump="always")


def clock_sweep(new_dt):
    """POST /api/_clock/set_current_utc side effects (PRD 2.5).

    1. Parcels in CONTINGENCY_ACTIVE whose contingency_end_date falls strictly
       before the new clock auto-transition to TERMINATED (deposit forfeited).
       The deadline is inclusive: clock == deadline does not expire.
    2. Every parcel's trailing absorption windows re-anchor to the new clock
       (version bumps only when a derived value actually moved).
    """
    for parcel in db["parcels"].values():
        if (parcel["status"] == "CONTINGENCY_ACTIVE"
                and parcel["contingency_end_date"] is not None
                and parse_dt(parcel["contingency_end_date"]) < new_dt):
            parcel["status"] = "TERMINATED"
            parcel["earnest_money_refunded"] = False
            touch(parcel)
    for parcel in db["parcels"].values():
        recompute_parcel(parcel, bump="change")
