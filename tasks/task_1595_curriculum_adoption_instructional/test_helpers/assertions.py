"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_framework(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["subject_area"] in [
        "MATHEMATICS", "ENGLISH_LANGUAGE_ARTS", "SCIENCE", "SOCIAL_STUDIES",
        "WORLD_LANGUAGES",
    ]
    assert data["grade_band"] in ["K_5", "GRADES_6_8", "GRADES_9_12"]
    assert isinstance(data["standards_required_count"], int)
    assert data["standards_required_count"] >= 1
    assert isinstance(data["effective_year"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_cycle(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "ALIGNMENT_REVIEW", "PILOT_OPEN", "SCORING", "PUBLIC_REVIEW",
        "BOARD_PENDING", "ADOPTED", "PROCURING", "DISTRIBUTING", "ACTIVE",
        "SUNSET", "NOT_ADOPTED",
    ]
    assert data["award_method"] in ["LOWEST_RESPONSIVE", "BEST_VALUE"]
    assert isinstance(data["district_enrollment"], int)
    assert isinstance(data["school_year_start"], int)


def assert_material(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["publisher_name"], str) and data["publisher_name"]
    assert data["material_type"] in ["CORE", "SUPPLEMENTAL"]
    assert data["adoption_status"] in [
        "SUBMITTED", "VETTED", "PILOT_CANDIDATE", "ADOPTED", "REJECTED",
    ]
    assert data["availability_status"] in [
        "USABLE", "UNDER_CHALLENGE", "RESTRICTED", "REMOVED",
    ]


def assert_alignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["standard_code"], str) and data["standard_code"]
    assert data["coverage_rating"] in ["NONE", "PARTIAL", "FULL"]


def assert_pilot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert isinstance(data["teacher_count"], int) and data["teacher_count"] >= 1
    assert data["status"] in ["PLANNED", "ACTIVE", "CLOSED", "CANCELLED"]
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["ends_on"], str)


def assert_review(data: dict):
    _assert_common_fields(data)
    for dim in ("pedagogy_score", "alignment_score", "usability_score",
                "equity_score"):
        assert isinstance(data[dim], int) and 1 <= data[dim] <= 4, \
            f"{dim} must be an integer 1..4"
    assert data["status"] in ["SUBMITTED", "WITHDRAWN"]


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["publisher_name"], str) and data["publisher_name"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_EVALUATION", "CLARIFICATION_REQUESTED", "SELECTED",
        "REJECTED", "WITHDRAWN", "SUPERSEDED",
    ]
    assert data["print_unit_price"] >= 0
    assert data["print_quantity"] >= 0
    assert data["digital_seat_rate"] >= 0
    assert data["digital_seat_count"] >= 0


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert data["order_status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED",
        "CANCELLED", "SUPERSEDED",
    ]
    assert data["payment_status"] in [
        "UNENCUMBERED", "ENCUMBERED", "PARTIALLY_PAID", "PAID", "RELEASED",
    ]
    assert isinstance(data["print_quantity"], int) and data["print_quantity"] >= 1
    assert isinstance(data["digital_seat_count"], int)
    assert data["digital_seat_count"] >= 0


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    for field in ("on_hand_units", "in_transit_units", "delivered_units",
                  "total_received_units", "allocated_units", "available_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_distribution_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "REQUESTED", "APPROVED", "BACKORDERED", "SHIPPED", "RECEIVED",
        "CANCELLED",
    ]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["need_priority"], int)
    assert 1 <= data["need_priority"] <= 5


def assert_supplemental_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["estimated_cost"] > 0
    assert data["status"] in [
        "SUBMITTED", "VETTING", "APPROVED", "DENIED", "UNDER_CHALLENGE",
        "REAFFIRMED", "REVOKED",
    ]


def assert_challenge_case(data: dict):
    _assert_common_fields(data)
    assert data["target_type"] in ["MATERIAL", "SUPPLEMENTAL_REQUEST"]
    assert data["grounds"] in [
        "CONTENT_OBJECTION", "AGE_APPROPRIATENESS", "ALIGNMENT_DISPUTE",
        "PROCEDURAL_IRREGULARITY",
    ]
    assert data["status"] in [
        "FILED", "SCREENING", "COMMITTEE_REVIEW", "HEARING", "DECIDED",
        "APPEALED", "CLOSED",
    ]
    assert isinstance(data["vote_round"], int)
    assert isinstance(data["appeal_used"], bool)


def assert_committee_vote(data: dict):
    """An immutable vote record carries only id + created_at as system
    fields: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "a vote record carries no updated_at"
    assert "version" not in data, "a vote record carries no version"
    assert data["vote"] in ["UPHOLD", "RESTRICT", "REMOVE"]
    assert isinstance(data["vote_round"], int)


def assert_budget_ledger(data: dict):
    _assert_common_fields(data)
    for field in ("appropriation_total", "encumbered_total", "expended_total",
                  "available_balance"):
        assert isinstance(data[field], (int, float)), \
            f"{field} must be numeric"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_budget_money_conservation(ledger: dict):
    """PRD money conservation: appropriation total always equals available
    balance plus encumbered total plus expended total."""
    total = (ledger["available_balance"] + ledger["encumbered_total"]
             + ledger["expended_total"])
    assert abs(ledger["appropriation_total"] - total) < 0.005, (
        f"money conservation violated: appropriation "
        f"{ledger['appropriation_total']} != available "
        f"{ledger['available_balance']} + encumbered "
        f"{ledger['encumbered_total']} + expended {ledger['expended_total']}"
    )


def assert_inventory_unit_conservation(lot: dict):
    """PRD unit conservation: total_received_units always equals on-hand plus
    in-transit plus delivered."""
    total = (lot["on_hand_units"] + lot["in_transit_units"]
             + lot["delivered_units"])
    assert lot["total_received_units"] == total, (
        f"unit conservation violated: total_received "
        f"{lot['total_received_units']} != on_hand {lot['on_hand_units']} + "
        f"in_transit {lot['in_transit_units']} + delivered "
        f"{lot['delivered_units']}"
    )
    assert lot["available_units"] == lot["on_hand_units"] - lot["allocated_units"], (
        f"available_units {lot['available_units']} != on_hand "
        f"{lot['on_hand_units']} - allocated {lot['allocated_units']}"
    )
