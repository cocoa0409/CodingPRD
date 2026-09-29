"""Lookups, aggregate recomputation and the two named cascade chains
(PRD §2.9, §3.4, §3.8, §3.9)."""

from datetime import timedelta

import calc
import store
from errors import ApiError
from util import floor_utc_day, whole_minutes
from validation import set_field, touch

# --------------------------------------------------------------------------- #
# lookups (PRD §2.5)
# --------------------------------------------------------------------------- #

_NOT_FOUND = {
    "vendors": "ERR_VENDOR_NOT_FOUND",
    "solicitations": "ERR_SOLICITATION_NOT_FOUND",
    "bids": "ERR_BID_NOT_FOUND",
    "questions": "ERR_QUESTION_NOT_FOUND",
    "protests": "ERR_PROTEST_NOT_FOUND",
    "hearings": "ERR_HEARING_NOT_FOUND",
    "awards": "ERR_AWARD_NOT_FOUND",
    "proceedings": "ERR_PROCEEDING_NOT_FOUND",
    "petitions": "ERR_PETITION_NOT_FOUND",
    "screenings": "ERR_SCREENING_NOT_FOUND",
}


def must(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


# --------------------------------------------------------------------------- #
# child collections
# --------------------------------------------------------------------------- #

def bids_of(solicitation):
    return store.ordered(
        [b for b in store.values("bids") if b["solicitation_id"] == solicitation["id"]]
    )


def addenda_of(solicitation):
    return sorted(
        [a for a in store.values("addenda") if a["solicitation_id"] == solicitation["id"]],
        key=lambda a: a["sequence_number"],
    )


def requirements_of(solicitation):
    return store.ordered(
        [r for r in store.values("requirements") if r["solicitation_id"] == solicitation["id"]]
    )


def questions_of(solicitation):
    return store.ordered(
        [q for q in store.values("questions") if q["solicitation_id"] == solicitation["id"]]
    )


def awards_of(solicitation):
    return store.ordered(
        [a for a in store.values("awards") if a["solicitation_id"] == solicitation["id"]]
    )


def protests_of(solicitation):
    return store.ordered(
        [p for p in store.values("protests") if p["solicitation_id"] == solicitation["id"]]
    )


def reviews_of(bid):
    return store.ordered(
        [r for r in store.values("reviews") if r["bid_id"] == bid["id"]]
    )


def hearings_of(protest):
    return store.ordered(
        [h for h in store.values("hearings") if h["protest_id"] == protest["id"]]
    )


def record_items_of(protest):
    return sorted(
        [i for i in store.values("record_items") if i["protest_id"] == protest["id"]],
        key=lambda i: i["sequence_number"],
    )


def bids_of_vendor(vendor):
    return store.ordered(
        [b for b in store.values("bids") if b["vendor_id"] == vendor["id"]]
    )


def proceedings_of_vendor(vendor):
    return store.ordered(
        [p for p in store.values("proceedings") if p["vendor_id"] == vendor["id"]]
    )


def petitions_of(proceeding):
    return store.ordered(
        [p for p in store.values("petitions") if p["proceeding_id"] == proceeding["id"]]
    )


def screenings_of_sub(vendor):
    return store.ordered(
        [s for s in store.values("screenings") if s["sub_vendor_id"] == vendor["id"]]
    )


# --------------------------------------------------------------------------- #
# aggregates (PRD §2.9 rule 2 - always re-derived, never adjusted)
# --------------------------------------------------------------------------- #

def recompute_apparent_low_bid(solicitation):
    """Pinned ranking procedure of PRD §3.4. Returns (previous, current)."""
    candidates = [
        b for b in bids_of(solicitation)
        if b["responsiveness_status"] in ("UNREVIEWED", "RESPONSIVE")
        and b["responsibility_status"] != "NONRESPONSIBLE"
        and b["evaluated_price_cents"] is not None
    ]
    candidates.sort(key=lambda b: (b["evaluated_price_cents"], b["created_at"], b["_seq"]))
    current = candidates[0]["id"] if candidates else None
    previous = solicitation["apparent_low_bid_id"]
    set_field(solicitation, "apparent_low_bid_id", current)
    return previous, current


def recompute_addendum_aggregates(solicitation):
    addenda = addenda_of(solicitation)
    total_days = sum(a["extends_bid_due_by_days"] for a in addenda)
    set_field(solicitation, "cumulative_extension_days", total_days)
    set_field(solicitation, "addendum_count", len(addenda))
    return total_days


def recompute_record_item_count(protest):
    set_field(protest, "record_item_count", len(record_items_of(protest)))


def recompute_strike_count(vendor):
    total = 0
    for proceeding in proceedings_of_vendor(vendor):
        if proceeding["status"] == "DEBARRED" or proceeding["interim_status"] == "INTERIM_SUSPENDED":
            total += proceeding["strikes_applied"]
    set_field(vendor, "debarment_strike_count", total)
    return total


def has_active_stay(solicitation):
    return any(p["stay_status"] == "ACTIVE" for p in protests_of(solicitation))


# --------------------------------------------------------------------------- #
# hearing capacity (PRD §3.8)
# --------------------------------------------------------------------------- #

LIVE_HEARING_STATUSES = ("SCHEDULED", "CONVENED")


def check_hearing_capacity(candidate_id, officer_user_id, start, end, room_code):
    """Room-occupancy check with the changeover buffer, then the officer's
    daily docket ceiling. The row being re-scheduled excludes itself."""
    buffer = timedelta(minutes=calc.CHANGEOVER_BUFFER_MINUTES)
    others = [
        h for h in store.values("hearings")
        if h["id"] != candidate_id and h["status"] in LIVE_HEARING_STATUSES
    ]

    for other in others:
        if other["room_code"] != room_code:
            continue
        if start < other["scheduled_end_utc"] + buffer and other["scheduled_start_utc"] < end + buffer:
            raise ApiError("ERR_HEARING_ROOM_CONFLICT")

    day_start = floor_utc_day(start)
    day_end = day_start + timedelta(days=1)
    booked = 0
    for other in others:
        if other["hearing_officer_user_id"] != officer_user_id:
            continue
        if not (day_start <= other["scheduled_start_utc"] < day_end):
            continue
        booked += whole_minutes(other["scheduled_start_utc"], other["scheduled_end_utc"]) or 0
    if booked + (whole_minutes(start, end) or 0) > calc.OFFICER_DAILY_MINUTE_CAP:
        raise ApiError("ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED")


# --------------------------------------------------------------------------- #
# solicitation cascades
# --------------------------------------------------------------------------- #

def revert_solicitation_to_evaluation(solicitation):
    """Cascade A hops 3-5 (also reached from Cascade B hop 3)."""
    set_field(solicitation, "status", "EVALUATION")
    recompute_apparent_low_bid(solicitation)
    for bid in bids_of(solicitation):
        if bid["responsibility_status"] in ("RESPONSIBLE", "NONRESPONSIBLE"):
            set_field(bid, "responsibility_status", "NOT_REVIEWED")
            for review in reviews_of(bid):
                if review["superseded_at_utc"] is None:
                    set_field(review, "superseded_at_utc", store.now())
    recompute_apparent_low_bid(solicitation)


def cancel_solicitation(solicitation):
    """PRD §3.8: cancellation clears the field in three moves."""
    set_field(solicitation, "status", "CANCELLED")
    for bid in bids_of(solicitation):
        if bid["responsiveness_status"] in ("UNREVIEWED", "RESPONSIVE"):
            set_field(bid, "responsiveness_status", "NONRESPONSIVE")
            bid["nonresponsive_reason_codes"] = bid["nonresponsive_reason_codes"] + [
                "OFFICER_DETERMINATION"
            ]
            touch(bid)
    for award in awards_of(solicitation):
        if award["status"] == "PENDING_STAY":
            set_field(award, "status", "VOID")
            set_field(award, "void_reason_code", "SOLICITATION_CANCELLED")
    set_field(solicitation, "apparent_low_bid_id", None)


def sustained_protest_cascade(solicitation, remedy_code):
    """Cascade A hops 2-5 (PRD §3.8)."""
    award_left = False
    for award in awards_of(solicitation):
        if award["status"] == "PENDING_STAY":
            set_field(award, "status", "VOID")
            set_field(award, "void_reason_code", "PROTEST_SUSTAINED")
            award_left = True
        elif award["status"] == "EXECUTED":
            set_field(award, "status", "RESCINDED")
            set_field(award, "void_reason_code", "PROTEST_SUSTAINED")
            award_left = True
    if remedy_code == "CORRECTIVE_ACTION":
        if award_left and solicitation["status"] in ("AWARD_PENDING", "AWARDED"):
            revert_solicitation_to_evaluation(solicitation)
    else:
        # CANCELLATION and RESOLICITATION both drive the solicitation to CANCELLED
        cancel_solicitation(solicitation)


# --------------------------------------------------------------------------- #
# vendor cascades (Cascade B, PRD §3.9)
# --------------------------------------------------------------------------- #

def vendor_ineligibility_cascade(vendor, reason_code):
    """Bids of an ineligible vendor go NONRESPONSIVE; affected solicitations
    re-rank, and a solicitation pushed out of AWARD_PENDING voids its award."""
    affected = []
    for bid in bids_of_vendor(vendor):
        solicitation = store.get("solicitations", bid["solicitation_id"])
        if solicitation is None:
            continue
        if solicitation["status"] not in ("BIDS_OPENED", "EVALUATION", "AWARD_PENDING"):
            continue
        if bid["responsiveness_status"] not in ("UNREVIEWED", "RESPONSIVE"):
            continue
        set_field(bid, "responsiveness_status", "NONRESPONSIVE")
        bid["nonresponsive_reason_codes"] = bid["nonresponsive_reason_codes"] + [reason_code]
        touch(bid)
        if solicitation["id"] not in [s["id"] for s in affected]:
            affected.append(solicitation)
    for solicitation in affected:
        previous, current = recompute_apparent_low_bid(solicitation)
        if solicitation["status"] == "AWARD_PENDING" and previous != current:
            revert_solicitation_to_evaluation(solicitation)
            for award in awards_of(solicitation):
                if award["status"] == "PENDING_STAY":
                    set_field(award, "status", "VOID")
                    set_field(award, "void_reason_code", "APPARENT_LOW_BIDDER_CHANGED")


def screening_fanout(vendor, from_results, to_result):
    """Re-evaluate the subcontractor screenings that name this vendor as the sub."""
    for screening in screenings_of_sub(vendor):
        if screening["result"] not in from_results:
            continue
        set_field(screening, "result", to_result)
        if to_result == "CLEARED":
            set_field(screening, "blocked_reason_code", None)
        else:
            set_field(screening, "blocked_reason_code", vendor["suspension_reason_code"])
        screening["rescreened_count"] = screening["rescreened_count"] + 1
        screening["screened_at_utc"] = store.now()
        touch(screening)


def suspend_vendor(vendor, proceeding):
    """Vendor ELIGIBLE -> SUSPENDED with its bid and screening fan-outs."""
    set_field(vendor, "eligibility_status", "SUSPENDED")
    set_field(vendor, "suspension_reason_code", proceeding["cause_code"])
    set_field(vendor, "active_debarment_id", proceeding["id"])
    recompute_strike_count(vendor)
    vendor_ineligibility_cascade(vendor, "VENDOR_SUSPENDED")
    screening_fanout(vendor, ("CLEARED",), "BLOCKED_SUSPENDED")


def debar_vendor(vendor, proceeding):
    """Cascade B hops 1-4 plus the screening fan-out."""
    set_field(vendor, "eligibility_status", "DEBARRED")
    set_field(vendor, "suspension_reason_code", proceeding["cause_code"])
    set_field(vendor, "active_debarment_id", proceeding["id"])
    set_field(
        vendor,
        "reinstatement_earliest_petition_utc",
        calc.earliest_petition_instant(
            proceeding["debarment_start_utc"], proceeding["debarment_period_months"]
        ),
    )
    recompute_strike_count(vendor)
    vendor_ineligibility_cascade(vendor, "VENDOR_DEBARRED")
    screening_fanout(vendor, ("CLEARED",), "BLOCKED_DEBARRED")


def restore_vendor(vendor, from_results):
    """Compensating restoration: SUSPENDED/DEBARRED -> ELIGIBLE.

    PRD §2.9: fiscal and eligibility state is restored, but bids already marked
    NONRESPONSIVE stay NONRESPONSIVE.
    """
    set_field(vendor, "eligibility_status", "ELIGIBLE")
    set_field(vendor, "active_debarment_id", None)
    set_field(vendor, "suspension_reason_code", None)
    set_field(vendor, "reinstatement_earliest_petition_utc", None)
    recompute_strike_count(vendor)
    screening_fanout(vendor, from_results, "CLEARED")
