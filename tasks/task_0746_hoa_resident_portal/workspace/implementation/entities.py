"""Entity constructors + common-field helpers."""

import db
from utils import new_uuid


def _init_common(now_iso):
    return {
        "id": new_uuid(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }


def bump(row, now_iso):
    """Mark a row mutated: bump version, refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso


# ---------------- Homeowner ---------------- #

def new_homeowner(email, full_name, is_board_member, now_iso):
    row = _init_common(now_iso)
    row.update({
        "email": email,
        "full_name": full_name,
        "is_board_member": is_board_member,
        "standing": "GOOD_STANDING",
        "delinquency_score": 0,
        "booking_privilege": "ALLOWED",
    })
    return row


# ---------------- Property ---------------- #

def new_property(homeowner_id, address, monthly_dues_cents, now_iso):
    row = _init_common(now_iso)
    row.update({
        "homeowner_id": homeowner_id,
        "address": address,
        "monthly_dues_cents": monthly_dues_cents,
        "compliance_flag": "OPEN",
        "total_outstanding_cents": 0,
        "fine_balance_cents": 0,
    })
    return row


# ---------------- Assessment ---------------- #

def new_assessment(property_id, billing_period_start_iso, billing_period_end_iso,
                   due_date_iso, prorate_from_iso, amount_due_cents, now_iso):
    row = _init_common(now_iso)
    row.update({
        "property_id": property_id,
        "billing_period_start": billing_period_start_iso,
        "billing_period_end": billing_period_end_iso,
        "prorate_from": prorate_from_iso,
        "amount_due_cents": amount_due_cents,
        "amount_paid_cents": 0,
        "late_fee_cents": 0,
        "status": "OPEN",
        "due_date": due_date_iso,
    })
    return row


# ---------------- Payment ---------------- #

def new_payment(assessment_id, amount_cents, method, now_iso):
    row = _init_common(now_iso)
    row.update({
        "assessment_id": assessment_id,
        "amount_cents": amount_cents,
        "method": method,
        "posted_at": now_iso,
        "status": "POSTED",
        "reversal_reason": None,
    })
    return row


# ---------------- AutopayMandate ---------------- #

def new_autopay_mandate(homeowner_id, max_charge_cents, now_iso):
    row = _init_common(now_iso)
    row.update({
        "homeowner_id": homeowner_id,
        "max_charge_cents": max_charge_cents,
        "status": "ACTIVE",
    })
    return row


# ---------------- ARC ---------------- #

def new_arc_request(property_id, submitter_homeowner_id, category, description, now_iso):
    row = _init_common(now_iso)
    row.update({
        "property_id": property_id,
        "submitter_homeowner_id": submitter_homeowner_id,
        "category": category,
        "description": description,
        "revision_count": 0,
        "status": "DRAFT",
        "fee_cents": 0,
    })
    return row


def new_arc_review(arc_request_id, reviewer_homeowner_id, weight, verdict, comment, revision_count, now_iso):
    row = _init_common(now_iso)
    row.update({
        "arc_request_id": arc_request_id,
        "reviewer_homeowner_id": reviewer_homeowner_id,
        "weight": weight,
        "verdict": verdict,
        "comment": comment,
        # revision_count of the parent request at review time (used to segregate
        # current-revision reviews from archived prior-revision reviews)
        "revision_count": revision_count,
        # archived flag: true once the parent transitions REVISION_REQUESTED -> SUBMITTED again
        "archived": False,
    })
    return row


# ---------------- Violation ---------------- #

def new_violation(property_id, category, now_iso):
    row = _init_common(now_iso)
    row.update({
        "property_id": property_id,
        "category": category,
        "reported_at": now_iso,
        "fined_at": None,
        "fine_amount_cents": 0,
        "fine_balance_cents": 0,
        "status": "REPORTED",
    })
    return row


# ---------------- Amenity + Reservation ---------------- #

def new_amenity(name, capacity, start_hour, end_hour, blackout_dates, now_iso):
    row = _init_common(now_iso)
    row.update({
        "name": name,
        "capacity": capacity,
        "reservation_window_start_hour": start_hour,
        "reservation_window_end_hour": end_hour,
        "blackout_dates": list(blackout_dates),
    })
    return row


def new_amenity_reservation(amenity_id, homeowner_id, start_ts_iso, end_ts_iso, guest_count, now_iso):
    row = _init_common(now_iso)
    row.update({
        "amenity_id": amenity_id,
        "homeowner_id": homeowner_id,
        "start_ts": start_ts_iso,
        "end_ts": end_ts_iso,
        "guest_count": guest_count,
        "status": "BOOKED",
    })
    return row


# ---------------- Motion + Ballot ---------------- #

def new_motion(title, description, category, voting_window_start_iso, voting_window_end_iso,
               eligible_voter_count, quorum_pct, now_iso):
    row = _init_common(now_iso)
    row.update({
        "title": title,
        "description": description,
        "category": category,
        "voting_window_start": voting_window_start_iso,
        "voting_window_end": voting_window_end_iso,
        "eligible_voter_count": eligible_voter_count,
        "quorum_pct": quorum_pct,
        "status": "OPEN",
        "yes_count": 0,
        "no_count": 0,
    })
    return row


def new_ballot(motion_id, homeowner_id, choice, now_iso):
    row = _init_common(now_iso)
    row.update({
        "motion_id": motion_id,
        "homeowner_id": homeowner_id,
        "choice": choice,
    })
    return row


# ---------------- WorkOrder ---------------- #

def new_work_order(title, cost_estimate_cents, related_property_id, source, now_iso):
    row = _init_common(now_iso)
    row.update({
        "title": title,
        "cost_estimate_cents": cost_estimate_cents,
        "related_property_id": related_property_id,
        "assigned_vendor_id": None,
        "work_status": "NEW",
        "payment_status": "UNBILLED",
        "source": source,
    })
    return row


# ---------------- Document ---------------- #

def new_document(title, category, content_url, now_iso):
    # Documents carry only id + created_at (PRD §2.4).
    return {
        "id": new_uuid(),
        "created_at": now_iso,
        "title": title,
        "category": category,
        "content_url": content_url,
    }
