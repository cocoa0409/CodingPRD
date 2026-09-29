"""Multi-entity cascades (PRD 2.11, 3.9, 3.10, 3.11) and the shared
notice-round flow used by both the first service and every re-offer.
"""

import clockmod
import db
from services import calc, derive


# --------------------------------------------------------------------------
# Statutory notice rounds (PRD 3.5, 3.9)
# --------------------------------------------------------------------------

def declaration_notices(declaration_id):
    return [n for n in db.all_rows("notices") if n["declaration_id"] == declaration_id]


def highest_notice_round(declaration_id):
    rounds = [n["notice_round"] for n in declaration_notices(declaration_id)]
    return max(rounds) if rounds else 0


def current_round_notices(declaration_id):
    top = highest_notice_round(declaration_id)
    return [n for n in declaration_notices(declaration_id) if n["notice_round"] == top]


def issue_notice_round(declaration, agency_ids, window_days, notice_round):
    """Create one notice per recipient and stamp the declaration's window."""
    issued_at = clockmod.now()
    deadline = clockmod.plus_days(issued_at, window_days)
    for agency_id in agency_ids:
        db.insert("notices", {
            "declaration_id": declaration["id"],
            "recipient_agency_id": agency_id,
            "notice_round": notice_round,
            "issued_at": issued_at,
            "response_window_days": window_days,
            "response_deadline_at": deadline,
            "status": "ISSUED",
            "responded_at": None,
            "response_type": None,
            "claimed_preference_category": None,
            "intended_use": None,
        })
    declaration["notice_issued_at"] = issued_at
    declaration["notice_response_window_days"] = window_days
    declaration["notice_response_deadline_at"] = deadline


# --------------------------------------------------------------------------
# The unsuccessful cascade (PRD 3.9) — fired by close-bidding with no
# qualifying bid.
# --------------------------------------------------------------------------

def unsuccessful_cascade(offering):
    offering["status"] = "FAILED_NO_QUALIFYING_BID"
    db.touch(offering)

    declaration = db.get("declarations", offering["declaration_id"])
    if declaration is not None and declaration["status"] == "OFFERING_AUTHORIZED":
        declaration["status"] = "UNSUCCESSFUL"
        declaration["reoffer_eligible_at"] = clockmod.plus_days(
            clockmod.now(), calc.REOFFER_COOLING_OFF_DAYS)
        db.touch(declaration)

        parcel = db.get("parcels", declaration["parcel_id"])
        if parcel is not None:
            appraisal = derive.accepted_appraisal(parcel["id"])
            if appraisal is not None:
                appraisal["status"] = "SUPERSEDED"
                appraisal["revaluation_required"] = True
                db.touch(appraisal)


# --------------------------------------------------------------------------
# The withdrawal cascade (PRD 3.9) — every live offering and bid unwinds.
# --------------------------------------------------------------------------

CANCELLABLE_OFFERING_STATUSES = ("DRAFT", "OPEN", "EVALUATION")


def withdrawal_cascade(declaration):
    reason = declaration.get("withdrawn_reason")
    for offering in db.all_rows("offerings"):
        if offering["declaration_id"] != declaration["id"]:
            continue
        if offering["status"] not in CANCELLABLE_OFFERING_STATUSES:
            continue
        offering["status"] = "CANCELLED"
        offering["cancellation_reason"] = reason
        db.touch(offering)
        for bid in db.all_rows("bids"):
            if bid["offering_id"] != offering["id"]:
                continue
            if bid["qualification_status"] not in derive.LIVE_BID_STATUSES:
                continue
            bid["qualification_status"] = "WITHDRAWN"
            calc.release_bid_deposit(bid)
            db.touch(bid)


# --------------------------------------------------------------------------
# Award rescission (PRD 3.8) — the conveyance leg.
# --------------------------------------------------------------------------

RESCINDABLE_CONVEYANCE_STATUSES = ("PENDING_TITLE", "READY_TO_RECORD")


def offering_conveyances(offering_id):
    return [c for c in db.all_rows("conveyances") if c["offering_id"] == offering_id]


def rescind_conveyances(offering):
    for conveyance in offering_conveyances(offering["id"]):
        if conveyance["recording_status"] not in RESCINDABLE_CONVEYANCE_STATUSES:
            continue
        conveyance["recording_status"] = "RESCINDED"
        conveyance["net_proceeds_cents"] = 0
        conveyance["recoverable_curative_cost_cents"] = 0
        db.touch(conveyance)


def winning_bid(offering_id):
    for bid in db.all_rows("bids"):
        if bid["offering_id"] == offering_id and bid["qualification_status"] == "WINNING":
            return bid
    return None
