"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ASSOCIATION_NAME": "Cedar Hollow Road Association",
    "RESERVE_TARGET_CENTS": 1_000_000,
    "SEGMENT_NAME": "Cedar Hollow Main",
    "LENGTH_FEET": 1600,
    "WIDTH_FEET": 22,
    "MAX_GRADE_PCT": 8,
    "SURFACE_TYPE": "GRAVEL",
    "TURNOUT_COUNT": 1,
    "CULVERT_COUNT": 2,
    "DEED_BOOK_PAGE": "DB100-P01",
    "FRONTAGE_FEET": 290,
    "USAGE_CLASS": "RESIDENTIAL_YEAR_ROUND",
    "TRIPS_PER_DAY": 6,
    "OWNER_NAME": "A. Whitcomb",
    "DEED_RECORDED_DATE": "2019-04-11",
    "FISCAL_YEAR": 2026,
    "FY_START_DATE": "2026-01-01",
    "FY_END_DATE": "2026-12-31",
    "BUDGET_REQUIREMENT_CENTS": 4_000_000,
    "METHOD_VARIANT": "FRONTAGE_WEIGHTED",
    "PROPOSAL_TITLE": "Spring regrade",
    "PROJECT_TYPE": "GRADING",
    "ESTIMATED_COST_CENTS": 1_500_000,
    "COST_ALLOCATION_METHOD": "EQUAL_SHARE",
    "CATEGORY": "GRADING",
    "WINDOW_START_DATE": "2026-08-05",
    "WINDOW_END_DATE": "2026-08-08",
    "CONTRACTOR_NAME": "Basin Grading LLC",
    "BID_AMOUNT_CENTS": 400_000,
}


def create_association_payload(**overrides) -> dict:
    """PRD §3.1: `name` and `reserve_target_cents` are required; the four
    governance settings are optional and default server-side."""
    payload = {
        "name": DEFAULTS["ASSOCIATION_NAME"],
        "reserve_target_cents": DEFAULTS["RESERVE_TARGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_road_segment_payload(association_id: str, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "name": DEFAULTS["SEGMENT_NAME"],
        "length_feet": DEFAULTS["LENGTH_FEET"],
        "width_feet": DEFAULTS["WIDTH_FEET"],
        "max_grade_pct": DEFAULTS["MAX_GRADE_PCT"],
        "surface_type": DEFAULTS["SURFACE_TYPE"],
        "turnout_count": DEFAULTS["TURNOUT_COUNT"],
        "culvert_count": DEFAULTS["CULVERT_COUNT"],
        "turnaround_present": True,
        "bridge_present": False,
    }
    payload.update(overrides)
    return payload


def create_access_inspection_payload(inspected_at: str, **overrides) -> dict:
    payload = {
        "inspected_at": inspected_at,
        "measured_width_feet": DEFAULTS["WIDTH_FEET"],
        "measured_max_grade_pct": DEFAULTS["MAX_GRADE_PCT"],
        "measured_turnout_count": DEFAULTS["TURNOUT_COUNT"],
        "turnaround_present": True,
    }
    payload.update(overrides)
    return payload


def create_parcel_payload(road_segment_id: str, **overrides) -> dict:
    payload = {
        "road_segment_id": road_segment_id,
        "deed_book_page": DEFAULTS["DEED_BOOK_PAGE"],
        "frontage_feet": DEFAULTS["FRONTAGE_FEET"],
        "usage_class": DEFAULTS["USAGE_CLASS"],
        "trips_per_day": DEFAULTS["TRIPS_PER_DAY"],
        "covenant_recorded": True,
    }
    payload.update(overrides)
    return payload


def reclassify_parcel_payload(expected_parcel_version: int, **overrides) -> dict:
    """PRD §3.2: reclassification takes `expected_parcel_version` plus any
    subset of `frontage_feet`, `usage_class`, and `trips_per_day`."""
    payload = {"expected_parcel_version": expected_parcel_version}
    payload.update(overrides)
    return payload


def subdivide_payload(children: list) -> dict:
    """`children` is a list of {"deed_book_page": ..., "frontage_feet": ...}."""
    return {"children": children}


def create_member_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "owner_name": DEFAULTS["OWNER_NAME"],
        "deed_book_page": DEFAULTS["DEED_BOOK_PAGE"],
        "deed_recorded_date": DEFAULTS["DEED_RECORDED_DATE"],
    }
    payload.update(overrides)
    return payload


def verify_deed_payload(verified_deed_book_page: str) -> dict:
    return {"verified_deed_book_page": verified_deed_book_page}


def create_assessment_roll_payload(association_id: str, **overrides) -> dict:
    payload = {
        "association_id": association_id,
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "fy_start_date": DEFAULTS["FY_START_DATE"],
        "fy_end_date": DEFAULTS["FY_END_DATE"],
        "budget_requirement_cents": DEFAULTS["BUDGET_REQUIREMENT_CENTS"],
        "method_variant": DEFAULTS["METHOD_VARIANT"],
    }
    payload.update(overrides)
    return payload


def recall_payload(recall_reason: str = "usage reclassification pending") -> dict:
    return {"recall_reason": recall_reason}


def payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_delinquency_action_payload(action_type: str, **overrides) -> dict:
    payload = {"action_type": action_type}
    payload.update(overrides)
    return payload


def release_payload(release_reason: str = "payment plan accepted by the board") -> dict:
    return {"release_reason": release_reason}


def create_proposal_payload(road_segment_id: str, **overrides) -> dict:
    payload = {
        "road_segment_id": road_segment_id,
        "project_type": DEFAULTS["PROJECT_TYPE"],
        "title": DEFAULTS["PROPOSAL_TITLE"],
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
        "cost_allocation_method": DEFAULTS["COST_ALLOCATION_METHOD"],
    }
    payload.update(overrides)
    return payload


def open_balloting_payload(balloting_closes_at: str) -> dict:
    return {"balloting_closes_at": balloting_closes_at}


def create_ballot_payload(
    proposal_id: str, member_id: str, choice: str, expected_proposal_version: int
) -> dict:
    return {
        "proposal_id": proposal_id,
        "member_id": member_id,
        "choice": choice,
        "expected_proposal_version": expected_proposal_version,
    }


def revoke_ballot_payload(expected_proposal_version: int) -> dict:
    return {"expected_proposal_version": expected_proposal_version}


def create_maintenance_project_payload(road_segment_id: str, **overrides) -> dict:
    payload = {
        "road_segment_id": road_segment_id,
        "category": DEFAULTS["CATEGORY"],
        "window_start_date": DEFAULTS["WINDOW_START_DATE"],
        "window_end_date": DEFAULTS["WINDOW_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_contractor_bid_payload(expected_project_version: int, **overrides) -> dict:
    payload = {
        "contractor_name": DEFAULTS["CONTRACTOR_NAME"],
        "amount_cents": DEFAULTS["BID_AMOUNT_CENTS"],
        "bond_on_file": True,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def award_payload(bid_id: str) -> dict:
    return {"bid_id": bid_id}


def complete_project_payload(completed_at: str, actual_cost_cents: int) -> dict:
    return {"completed_at": completed_at, "actual_cost_cents": actual_cost_cents}


def cancel_project_payload(cancellation_reason: str = "scope withdrawn by the board") -> dict:
    return {"cancellation_reason": cancellation_reason}


def withdraw_bid_payload(withdrawal_reason: str = "crew reassigned") -> dict:
    return {"withdrawal_reason": withdrawal_reason}


def create_connection_request_payload(parcel_id: str, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "requested_usage_class": "RESIDENTIAL_YEAR_ROUND",
        "requested_trips_per_day": 4,
        "easement_grant_recorded": True,
    }
    payload.update(overrides)
    return payload


def decide_connection_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(easement_grant_recorded: bool, resolution_note: str) -> dict:
    return {
        "easement_grant_recorded": easement_grant_recorded,
        "resolution_note": resolution_note,
    }
