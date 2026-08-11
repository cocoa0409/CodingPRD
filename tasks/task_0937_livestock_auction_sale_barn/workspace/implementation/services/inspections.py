"""Inspection documents and the two gates that consume them (PRD 3.6)."""
from clock import clock, parse_date
from errors import fail
from store import db


def lot_records(lot_id, inspection_type):
    return sorted([r for r in db["inspection_records"].values()
                   if r["lot_id"] == lot_id and r["inspection_type"] == inspection_type],
                  key=lambda r: r["_seq"])


def require_documents(lot, types):
    """Rung 30 then rung 31, in that order, across every required type.

    A missing document, one that is not CLEARED, or one that covers too few
    head answers ERR_INSPECTION_NOT_CLEARED; a document that is cleared and
    adequate but stale answers ERR_CVI_EXPIRED.
    """
    adequate = {}
    for inspection_type in types:
        found = [r for r in lot_records(lot["id"], inspection_type)
                 if r["status"] == "CLEARED" and r["inspected_head"] >= lot["head_count"]]
        if not found:
            fail("ERR_INSPECTION_NOT_CLEARED")
        adequate[inspection_type] = found
    today = clock.now_date()
    for inspection_type in types:
        fresh = [r for r in adequate[inspection_type]
                 if parse_date(r["valid_through"]) is not None
                 and parse_date(r["valid_through"]) >= today]
        if not fresh:
            fail("ERR_CVI_EXPIRED")


def mark_ready_documents(lot):
    """A cleared trichomoniasis test for a breeding bull, a cleared brucellosis
    test for a breeding female; the other four classes require nothing."""
    if lot["livestock_class"] == "BREEDING_BULL":
        return ["TRICH_TEST"]
    if lot["livestock_class"] == "BREEDING_FEMALE":
        return ["BRUCELLOSIS_TEST"]
    return []


def release_documents(lot, sale_day):
    """A brand record always; a CVI whenever the lot is leaving the state."""
    types = ["BRAND"]
    if lot.get("destination_state_code") \
            and lot["destination_state_code"] != sale_day["barn_state_code"]:
        types.append("CVI")
    return types
