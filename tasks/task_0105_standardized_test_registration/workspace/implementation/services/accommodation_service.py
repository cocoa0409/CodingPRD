"""AccommodationRequest service: 504/IEP review workflow with SOD enforcement."""

from datetime import timedelta
from typing import List, Optional

import db
from clock import now
from config import (
    ACCOMMODATION_FEE_CENTS,
    ACCOMMODATION_LEAD_DAYS,
    ACCOMMODATION_REVIEW_WINDOW_DAYS,
    ACCOMMODATION_TYPES,
)
from errors import (
    err_accommodation_deadline_passed,
    err_accommodation_not_eligible,
    err_accommodation_request_not_found,
    err_duplicate_accommodation,
    err_insufficient_permissions,
    err_invalid_accommodation_state,
    err_invalid_request,
    err_not_pinned_reviewer,
)
from response import iso_utc_ms, parse_iso_utc
from services.candidate_service import get_candidate_or_404
from services.capacity_service import (
    find_capacity_row,
    reconcile_capacity,
    standby_promotion_selector,
)
from services.test_event_service import get_test_event_or_404


def get_accommodation_or_404(accommodation_id: str) -> dict:
    a = db.accommodation_requests.get(accommodation_id)
    if a is None:
        raise err_accommodation_request_not_found()
    return a


def create_accommodation_request(body: dict, caller_role: str, caller_user_id: str) -> dict:
    candidate_id = body.get("candidate_id")
    test_event_id = body.get("test_event_id")
    requested = body.get("requested_accommodations")
    supporting = body.get("supporting_documents")

    if not isinstance(candidate_id, str) or not candidate_id:
        raise err_invalid_request("candidate_id is required")
    if not isinstance(test_event_id, str) or not test_event_id:
        raise err_invalid_request("test_event_id is required")
    if not isinstance(requested, list) or not requested:
        raise err_invalid_request("requested_accommodations must be a non-empty array")
    for v in requested:
        if v not in ACCOMMODATION_TYPES:
            raise err_invalid_request(f"requested_accommodations contains invalid value: {v}")
    if not isinstance(supporting, list) or not supporting:
        raise err_invalid_request("supporting_documents must be a non-empty array")

    candidate = get_candidate_or_404(candidate_id)
    event = get_test_event_or_404(test_event_id)

    if caller_role == "Candidate" and caller_user_id != candidate["id"]:
        raise err_insufficient_permissions()

    # Compute deadlines
    reg_deadline = parse_iso_utc(event["registration_deadline"])
    submission_deadline_at = reg_deadline - timedelta(days=ACCOMMODATION_LEAD_DAYS)
    review_deadline_at = submission_deadline_at + timedelta(days=ACCOMMODATION_REVIEW_WINDOW_DAYS)

    # Validation precedence after state: deadline → eligibility → duplicate
    if now() > submission_deadline_at:
        raise err_accommodation_deadline_passed()
    if not candidate.get("has_iep_or_504"):
        raise err_accommodation_not_eligible()
    for a in db.accommodation_requests.all():
        if (
            a["candidate_id"] == candidate_id
            and a["test_event_id"] == test_event_id
            and a["status"] != "EXPIRED"
        ):
            raise err_duplicate_accommodation()

    a = db.common_create()
    a.update(
        {
            "candidate_id": candidate_id,
            "test_event_id": test_event_id,
            "requested_accommodations": list(requested),
            "supporting_documents": list(supporting),
            "status": "SUBMITTED",
            "reviewer_user_id": None,
            "submission_deadline_at": iso_utc_ms(submission_deadline_at),
            "review_deadline_at": iso_utc_ms(review_deadline_at),
        }
    )
    db.accommodation_requests.insert(a)
    return a


def start_review(accommodation_id: str, caller_user_id: str) -> dict:
    a = get_accommodation_or_404(accommodation_id)
    if a["status"] != "SUBMITTED":
        raise err_invalid_accommodation_state()
    review_deadline = parse_iso_utc(a["review_deadline_at"])
    if now() > review_deadline:
        raise err_invalid_accommodation_state("Review deadline has passed")
    if not a["supporting_documents"]:
        raise err_invalid_accommodation_state("supporting_documents must be non-empty")
    a["status"] = "UNDER_REVIEW"
    a["reviewer_user_id"] = caller_user_id
    db.touch(a)
    return a


def request_info(accommodation_id: str, caller_user_id: str) -> dict:
    a = get_accommodation_or_404(accommodation_id)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_accommodation_state()
    if a.get("reviewer_user_id") != caller_user_id:
        raise err_not_pinned_reviewer()
    a["status"] = "NEEDS_MORE_INFO"
    db.touch(a)
    return a


def resubmit(accommodation_id: str, body: dict, caller_user_id: str) -> dict:
    a = get_accommodation_or_404(accommodation_id)
    if caller_user_id != a["candidate_id"]:
        raise err_insufficient_permissions()
    if a["status"] != "NEEDS_MORE_INFO":
        raise err_invalid_accommodation_state()
    review_deadline = parse_iso_utc(a["review_deadline_at"])
    if now() > review_deadline:
        raise err_invalid_accommodation_state("Review deadline has passed")

    new_docs = body.get("supporting_documents")
    if not isinstance(new_docs, list):
        raise err_invalid_request("supporting_documents must be an array")
    if len(new_docs) <= len(a["supporting_documents"]):
        raise err_invalid_request("supporting_documents length must strictly increase")

    a["supporting_documents"] = list(new_docs)
    a["status"] = "SUBMITTED"
    db.touch(a)
    return a


def approve(accommodation_id: str, caller_user_id: str) -> dict:
    a = get_accommodation_or_404(accommodation_id)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_accommodation_state()
    if a.get("reviewer_user_id") != caller_user_id:
        raise err_not_pinned_reviewer()
    a["status"] = "APPROVED"
    db.touch(a)
    _apply_approval_cascade(a)
    return a


def deny(accommodation_id: str, caller_user_id: str) -> dict:
    a = get_accommodation_or_404(accommodation_id)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_accommodation_state()
    if a.get("reviewer_user_id") != caller_user_id:
        raise err_not_pinned_reviewer()
    a["status"] = "DENIED"
    db.touch(a)
    return a


def _apply_approval_cascade(a: dict):
    """For every Registration matching (candidate_id, test_event_id), flip
    accommodation_required=true, add the accommodation fee, and pin the
    accommodation request version. If the accommodation pool on the relevant
    TestCenterCapacity is exhausted, demote CONFIRMED → STANDBY.
    """
    affected_pairs = set()
    matching_regs = [
        r
        for r in db.registrations.all()
        if r["candidate_id"] == a["candidate_id"] and r["test_event_id"] == a["test_event_id"]
    ]
    for r in matching_regs:
        # Skip CANCELLED registrations.
        if r["status"] == "CANCELLED":
            continue
        if not r.get("accommodation_required"):
            r["accommodation_required"] = True
            r["accommodation_fee_cents_charged"] = r["accommodation_fee_cents_charged"] + ACCOMMODATION_FEE_CENTS
            r["amount_charged_cents"] = (
                r["base_fee_cents_charged"] + r["late_fee_cents_charged"] + r["accommodation_fee_cents_charged"]
            )
            r["amount_retained_cents"] = r["amount_charged_cents"] - r["amount_refunded_cents"]
        r["locked_accommodation_request_version"] = a["version"]
        db.touch(r)
        affected_pairs.add((r["test_event_id"], r["test_center_id"]))

    # First reconcile each pair so accommodation_seats_used reflects new flags.
    for ev_id, c_id in list(affected_pairs):
        reconcile_capacity(ev_id, c_id)

    # PRD §3.6: "On every TestCenter for which the affected candidate
    # holds a CONFIRMED registration, the system then checks whether the
    # accommodation pool has free capacity: if accommodation_capacity
    # minus accommodation_seats_used equals zero, the CONFIRMED
    # registration is demoted back to STANDBY".
    #
    # Only the *affected candidate's* (i.e., the candidate whose
    # accommodation request was just approved) CONFIRMED registrations
    # are eligible for demotion — pre-existing accommodation candidates
    # on the same pair keep their seats.
    for ev_id, c_id in list(affected_pairs):
        cap = find_capacity_row(ev_id, c_id)
        if cap is None:
            continue
        # Determine pool fullness BEFORE counting the affected candidate's
        # newly-flipped accommodation flag — i.e., is there a free
        # accommodation seat for them?
        affected_candidate_id = a["candidate_id"]
        other_accommodation_used = sum(
            1
            for rr in db.registrations.all()
            if rr["test_event_id"] == ev_id
            and rr["test_center_id"] == c_id
            and rr["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED")
            and rr.get("accommodation_required")
            and rr["candidate_id"] != affected_candidate_id
        )
        free_acc = cap["accommodation_capacity"] - other_accommodation_used
        demoted_general_count = 0
        if free_acc <= 0:
            # Demote the affected candidate's CONFIRMED registration(s) on
            # this pair to STANDBY.
            for rr in db.registrations.all():
                if (
                    rr["test_event_id"] == ev_id
                    and rr["test_center_id"] == c_id
                    and rr["candidate_id"] == affected_candidate_id
                    and rr["status"] == "CONFIRMED"
                ):
                    rr["status"] = "STANDBY"
                    db.touch(rr)
                    demoted_general_count += 1
            reconcile_capacity(ev_id, c_id)

        # After demotions, try standby promotions for general seats that may
        # have opened up. PRD §3.4 selector inputs: each demotion frees one
        # general seat; no acc seats are freed (the demoted candidate's seat
        # was the one that just became contested, and the other acc holders
        # still occupy theirs). So N = demoted_general_count, K = 0.
        if demoted_general_count > 0:
            standby_promotion_selector(
                ev_id, c_id,
                seats_freed=demoted_general_count,
                accommodation_seats_freed=0,
            )
        reconcile_capacity(ev_id, c_id)


def list_accommodation_requests(status: Optional[str], test_event_id: Optional[str]):
    items = db.accommodation_requests.all()
    if status:
        items = [a for a in items if a["status"] == status]
    if test_event_id:
        items = [a for a in items if a["test_event_id"] == test_event_id]
    items.sort(key=lambda a: a["created_at"])
    return items
