"""Fingerprint card construction and the site billable-print projection."""

from decimal import Decimal

import constants as C
from store import db

BILLABLE_STATUSES = ("SUBMITTED", "CLOSED", "REJECTED_CLOSED")


def open_card(appointment, device, site, captured_by_user_id,
              reprint_of_submission_id=None, free_reprint_granted=False):
    card = db.create(
        "cards",
        {
            "appointment_id": appointment["id"],
            "device_id": device["id"],
            "site_id": site["id"],
            "captured_by_user_id": captured_by_user_id,
            "status": "OPEN",
            "positions_passed_count": 0,
            "positions_exception_count": 0,
            "mean_quality_score": Decimal("0.00"),
            "worst_position_score": None,
            "submittable": False,
            "exception_override_by_user_id": None,
            "superseded_by_card_id": None,
            "reprint_of_submission_id": reprint_of_submission_id,
            "free_reprint_granted": free_reprint_granted,
            "taint_reason": None,
            "first_capture_at": None,
            "last_capture_at": None,
        },
    )
    for code in C.POSITION_CODES:
        db.create(
            "positions",
            {
                "card_id": card["id"],
                "position_code": code,
                "attempt_count": 0,
                "best_score": None,
                "status": "PENDING",
                "exception_code": None,
                "closed_at": None,
            },
        )
    return card


def cards_at_site(site_id):
    return [c for c in db.cards.values() if c["site_id"] == site_id]


def billable_count_for_site(site_id):
    return sum(1 for c in cards_at_site(site_id) if c["status"] in BILLABLE_STATUSES)


def recompute_site_billable(site):
    count = billable_count_for_site(site["id"])
    if site["billable_print_count"] != count:
        site["billable_print_count"] = count
        db.touch(site)
        return True
    return False


def billable_count_for_assignment(assignment):
    return sum(
        1
        for c in db.cards.values()
        if c["device_id"] == assignment["device_id"]
        and c["site_id"] == assignment["site_id"]
        and c["status"] in BILLABLE_STATUSES
    )
