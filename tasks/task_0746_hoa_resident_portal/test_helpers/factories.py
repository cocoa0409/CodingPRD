"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MONTHLY_DUES_CENTS": 30000,
    "MAX_CHARGE_CENTS": 50000,
    "AMENITY_CAPACITY": 10,
    "AMENITY_START_HOUR": 6,
    "AMENITY_END_HOUR": 22,
    "GUEST_COUNT": 2,
    "ARC_CATEGORY": "SIMPLE",
    "REVIEW_WEIGHT": 1,
    "REVIEW_VERDICT": "APPROVE",
    "VIOLATION_CATEGORY": "NUISANCE",
    "FINE_AMOUNT_CENTS": 15000,
    "MOTION_QUORUM_PCT": 50,
    "MOTION_ELIGIBLE": 10,
    "WORK_ORDER_COST": 10000,
    "DOCUMENT_CATEGORY": "CCR",
}


def create_homeowner_payload(**overrides):
    defaults = {
        "email": overrides.pop("email", "owner@example.com"),
        "full_name": overrides.pop("full_name", "Test Owner"),
    }
    if "is_board_member" in overrides:
        defaults["is_board_member"] = overrides.pop("is_board_member")
    defaults.update(overrides)
    return defaults


def create_property_payload(homeowner_id, **overrides):
    defaults = {
        "homeowner_id": homeowner_id,
        "address": overrides.pop("address", "1 Test Ln"),
        "monthly_dues_cents": overrides.pop(
            "monthly_dues_cents", DEFAULTS["MONTHLY_DUES_CENTS"]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(property_id, **overrides):
    defaults = {
        "property_id": property_id,
        "billing_period_start": overrides.pop(
            "billing_period_start", "2026-03-01T00:00:00Z"
        ),
        "billing_period_end": overrides.pop(
            "billing_period_end", "2026-04-01T00:00:00Z"
        ),
        "due_date": overrides.pop("due_date", "2026-04-15T00:00:00Z"),
    }
    if "prorate_from" in overrides:
        defaults["prorate_from"] = overrides.pop("prorate_from")
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides):
    defaults = {
        "amount_cents": overrides.pop("amount_cents", 30000),
        "method": overrides.pop("method", "MANUAL"),
    }
    defaults.update(overrides)
    return defaults


def create_autopay_mandate_payload(expected_homeowner_version, **overrides):
    defaults = {
        "expected_homeowner_version": expected_homeowner_version,
        "max_charge_cents": overrides.pop(
            "max_charge_cents", DEFAULTS["MAX_CHARGE_CENTS"]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_arc_request_payload(property_id, submitter_homeowner_id, **overrides):
    defaults = {
        "property_id": property_id,
        "submitter_homeowner_id": submitter_homeowner_id,
        "category": overrides.pop("category", DEFAULTS["ARC_CATEGORY"]),
        "description": overrides.pop("description", "Test modification"),
    }
    defaults.update(overrides)
    return defaults


def create_arc_review_payload(reviewer_homeowner_id, **overrides):
    defaults = {
        "reviewer_homeowner_id": reviewer_homeowner_id,
        "weight": overrides.pop("weight", DEFAULTS["REVIEW_WEIGHT"]),
        "verdict": overrides.pop("verdict", DEFAULTS["REVIEW_VERDICT"]),
    }
    if "comment" in overrides:
        defaults["comment"] = overrides.pop("comment")
    defaults.update(overrides)
    return defaults


def create_violation_payload(property_id, **overrides):
    defaults = {
        "property_id": property_id,
        "category": overrides.pop("category", DEFAULTS["VIOLATION_CATEGORY"]),
    }
    defaults.update(overrides)
    return defaults


def create_amenity_payload(**overrides):
    defaults = {
        "name": overrides.pop("name", "Test Amenity"),
        "capacity": overrides.pop("capacity", DEFAULTS["AMENITY_CAPACITY"]),
        "reservation_window_start_hour": overrides.pop(
            "reservation_window_start_hour", DEFAULTS["AMENITY_START_HOUR"]
        ),
        "reservation_window_end_hour": overrides.pop(
            "reservation_window_end_hour", DEFAULTS["AMENITY_END_HOUR"]
        ),
    }
    if "blackout_dates" in overrides:
        defaults["blackout_dates"] = overrides.pop("blackout_dates")
    defaults.update(overrides)
    return defaults


def create_reservation_payload(amenity_id, homeowner_id, **overrides):
    defaults = {
        "amenity_id": amenity_id,
        "homeowner_id": homeowner_id,
        "start_ts": overrides.pop("start_ts", "2026-03-20T10:00:00Z"),
        "end_ts": overrides.pop("end_ts", "2026-03-20T12:00:00Z"),
        "guest_count": overrides.pop("guest_count", DEFAULTS["GUEST_COUNT"]),
    }
    defaults.update(overrides)
    return defaults


def create_motion_payload(**overrides):
    defaults = {
        "title": overrides.pop("title", "Test Motion"),
        "description": overrides.pop("description", "Test description"),
        "category": overrides.pop("category", "POLICY"),
        "voting_window_start": overrides.pop(
            "voting_window_start", "2026-04-01T00:00:00Z"
        ),
        "voting_window_end": overrides.pop(
            "voting_window_end", "2026-04-05T00:00:00Z"
        ),
        "eligible_voter_count": overrides.pop(
            "eligible_voter_count", DEFAULTS["MOTION_ELIGIBLE"]
        ),
        "quorum_pct": overrides.pop("quorum_pct", DEFAULTS["MOTION_QUORUM_PCT"]),
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(homeowner_id, **overrides):
    defaults = {
        "homeowner_id": homeowner_id,
        "choice": overrides.pop("choice", "YES"),
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides):
    defaults = {
        "title": overrides.pop("title", "Test Work"),
        "cost_estimate_cents": overrides.pop(
            "cost_estimate_cents", DEFAULTS["WORK_ORDER_COST"]
        ),
    }
    if "related_property_id" in overrides:
        defaults["related_property_id"] = overrides.pop("related_property_id")
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides):
    defaults = {
        "title": overrides.pop("title", "Test Doc"),
        "category": overrides.pop("category", DEFAULTS["DOCUMENT_CATEGORY"]),
        "content_url": overrides.pop("content_url", "https://example.com/doc.pdf"),
    }
    defaults.update(overrides)
    return defaults
