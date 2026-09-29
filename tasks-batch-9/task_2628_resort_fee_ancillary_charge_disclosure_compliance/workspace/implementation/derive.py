"""Denormalised parent recomputation, folio aggregation and the cascade chains
(PRD 2.9, 2.10, 3.3, 3.5)."""

import calc
import clock
import store

CHARGE_LINE_TYPES = ("ROOM", "MANDATORY_FEE", "OPTIONAL_FEE", "FEE_REBILL")
CREDIT_LINE_TYPES = ("FEE_CREDIT", "COMPLAINT_REFUND")

CANDIDATE_PROFILE_STATUSES = ("DEPLOYED", "FLAGGED", "REMEDIATED")
GAP_BEARING_BOOKING_STATUSES = ("DISPUTED", "UNDISCLOSED_CONFIRMED")
LIVE_COMPLAINT_STATUSES = ("SUBMITTED", "UNDER_INVESTIGATION", "SUBSTANTIATED")
CLOSED_INQUIRY_STATUSES = ("ACCEPTED", "WITHDRAWN")


# ------------------------------------------------------------- folio ledger

def next_sequence_no(folio):
    lines = store.lines_of_folio(folio["id"])
    return (lines[-1]["sequence_no"] + 1) if lines else 1


def append_line(folio, line_type, jurisdiction_id, description, amount_cents,
                taxability_determination, tax_rate_bps, tax_cents,
                fee_id=None, fee_code=None):
    row = {
        "folio_id": folio["id"],
        "fee_id": fee_id,
        "jurisdiction_id": jurisdiction_id,
        "line_type": line_type,
        "fee_code": fee_code,
        "description": description,
        "amount_cents": amount_cents,
        "taxability_determination": taxability_determination,
        "tax_rate_bps": tax_rate_bps,
        "tax_cents": tax_cents,
        "sequence_no": next_sequence_no(folio),
    }
    store.stamp_new(row, versioned=False)
    store.folio_lines[row["id"]] = row
    return row


def refresh_folio(folio):
    """Straight aggregation over every line then present (PRD 3.5)."""
    lines = store.lines_of_folio(folio["id"])
    charges = sum(l["amount_cents"] for l in lines if l["line_type"] in CHARGE_LINE_TYPES)
    credits = sum(l["amount_cents"] for l in lines if l["line_type"] in CREDIT_LINE_TYPES)
    tax_total = sum(l["tax_cents"] for l in lines)
    folio["line_count"] = len(lines)
    folio["charges_subtotal_cents"] = charges
    folio["credits_total_cents"] = credits
    folio["tax_total_cents"] = tax_total
    folio["folio_total_cents"] = charges - credits + tax_total
    return folio


def refresh_booking_money(booking, folio):
    booking["folio_total_cents"] = folio["folio_total_cents"]
    booking["guest_out_of_pocket_cents"] = folio["folio_total_cents"]
    return booking


# ------------------------------------------------------ profile scoring

def rescore_profile(profile, bump=True):
    profile["disclosure_score"] = calc.disclosure_score(profile)
    if bump:
        store.touch(profile)
    return profile["disclosure_score"]


def effective_score(profile):
    """A FLAGGED path contributes 0 regardless of its stored score (PRD 3.3)."""
    if profile["status"] == "FLAGGED":
        return 0
    return profile["disclosure_score"]


# --------------------------------------------- property recomputation

def min_channel_disclosure_score(prop):
    candidates = [
        p for p in store.profiles_of_property(prop["id"])
        if p["status"] in CANDIDATE_PROFILE_STATUSES
    ]
    if not candidates:
        return None
    return min(effective_score(p) for p in candidates)


def published_fee_program_count(prop):
    return sum(
        1 for p in store.programs_of_property(prop["id"]) if p["status"] == "PUBLISHED"
    )


def open_disclosure_obligation_count(prop):
    """PRD 2.10: flagged paths + disputed/confirmed bookings + live complaints on
    those bookings + dockets that are neither accepted nor withdrawn."""
    total = 0
    for profile in store.profiles_of_property(prop["id"]):
        if profile["status"] == "FLAGGED":
            total += 1
    bookings = store.bookings_of_property(prop["id"])
    for booking in bookings:
        if booking["disclosure_status"] in GAP_BEARING_BOOKING_STATUSES:
            total += 1
    for booking in bookings:
        # A submitted complaint is itself an open obligation (PRD 3.7), so every live
        # complaint on any of the property's bookings counts.
        for complaint in store.complaints_of_booking(booking["id"]):
            if complaint["status"] in LIVE_COMPLAINT_STATUSES:
                total += 1
    for inquiry in store.inquiries_of_property(prop["id"]):
        if inquiry["status"] not in CLOSED_INQUIRY_STATUSES:
            total += 1
    return total


def aggregate_disclosure_gap_cents(prop):
    total = 0
    for booking in store.bookings_of_property(prop["id"]):
        if booking["disclosure_status"] in GAP_BEARING_BOOKING_STATUSES:
            total += booking["quote_disclosure_gap_cents"]
    return total


def sweep_unaudited_quotes(prop):
    """A posture that lands on NON_COMPLIANT disputes the property's still-unaudited
    quotes: only QUOTED bookings in PENDING_AUDIT are swept (PRD 3.4)."""
    for booking in store.bookings_of_property(prop["id"]):
        if booking["stay_status"] == "QUOTED" and booking["disclosure_status"] == "PENDING_AUDIT":
            booking["disclosure_status"] = "DISPUTED"
            store.touch(booking)


def recompute_property(prop, force=False):
    """Recompute the five denormalised property fields. The version is bumped when a
    stored value actually changed (PRD 2.5) or when the caller's transition mandates it."""
    before = (
        prop["min_channel_disclosure_score"], prop["disclosure_posture"],
        prop["open_disclosure_obligation_count"], prop["published_fee_program_count"],
        prop["aggregate_disclosure_gap_cents"],
    )
    previous_posture = prop["disclosure_posture"]

    minimum = min_channel_disclosure_score(prop)
    posture = calc.posture_for(minimum)
    prop["min_channel_disclosure_score"] = minimum
    prop["disclosure_posture"] = posture

    if posture == "NON_COMPLIANT" and previous_posture != "NON_COMPLIANT":
        sweep_unaudited_quotes(prop)

    prop["published_fee_program_count"] = published_fee_program_count(prop)
    prop["open_disclosure_obligation_count"] = open_disclosure_obligation_count(prop)
    prop["aggregate_disclosure_gap_cents"] = aggregate_disclosure_gap_cents(prop)

    after = (
        prop["min_channel_disclosure_score"], prop["disclosure_posture"],
        prop["open_disclosure_obligation_count"], prop["published_fee_program_count"],
        prop["aggregate_disclosure_gap_cents"],
    )
    if force or before != after:
        store.touch(prop)
    return prop


def property_of(row):
    return store.properties.get(row["property_id"])


def confirmed_undisclosed_count(profile):
    """PRD 2.10: complaints in SUBSTANTIATED or REFUNDED whose booking used this path."""
    total = 0
    for booking in store.bookings.values():
        if booking["channel_disclosure_profile_id"] != profile["id"]:
            continue
        for complaint in store.complaints_of_booking(booking["id"]):
            if complaint["status"] in ("SUBSTANTIATED", "REFUNDED"):
                total += 1
    return total


def retire_profile(profile):
    """Systemic retirement. RETIRED is terminal (PRD 3.3)."""
    profile["status"] = "RETIRED"
    profile["_retired_at"] = clock.now()
    store.touch(profile)
