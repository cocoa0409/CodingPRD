"""Entity assertions and domain invariant checkers.

Each assert_* checks the common system fields plus the entity-specific fields
a PRD reader would expect on the wire. They are deliberately lenient about
server-extra fields (subset checking).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "status" in data or True  # status presence checked per entity below


def assert_community(data: dict):
    _assert_common(data)
    assert isinstance(data["community_name"], str) and data["community_name"]
    assert isinstance(data["total_planned_units"], int) and data["total_planned_units"] >= 1
    assert data["status"] in ["PLANNING", "ACTIVE", "TURNOVER_RECORDED"]
    assert isinstance(data["closed_unit_count"], int)
    assert data["transition_stage"] in [
        "DECLARANT_CONTROL", "OWNER_REPRESENTATION", "PARITY", "OWNER_MAJORITY", "TURNOVER_COMPLETE",
    ]


def assert_phase(data: dict):
    _assert_common(data)
    assert isinstance(data["phase_name"], str) and data["phase_name"]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["planned_lot_count"], int) and data["planned_lot_count"] >= 1
    assert data["status"] in ["PLANNED", "SALES_OPEN", "DELIVERING", "CLOSED_OUT", "CANCELLED"]


def assert_amenity(data: dict):
    _assert_common(data)
    assert data["amenity_type"] in [
        "CLUBHOUSE", "POOL", "PARK", "TRAIL_NETWORK", "FITNESS_CENTER", "EVENT_LAWN",
    ]
    assert data["status"] in ["COMMITTED", "IN_DESIGN", "UNDER_CONSTRUCTION", "OPEN", "DELINQUENT"]


def assert_builder(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["credit_tier"] in ["A", "B", "C"]
    assert data["standing"] in ["GOOD_STANDING", "PROBATION", "SUSPENDED"]
    assert isinstance(data["total_lots_purchased"], int)


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["base_price_per_lot_cents"], int) and data["base_price_per_lot_cents"] > 0
    assert isinstance(data["total_lots_committed"], int) and data["total_lots_committed"] >= 1
    assert data["status"] in ["DRAFT", "EXECUTED", "ACTIVE", "COMPLETED", "DEFAULTED", "TERMINATED"]
    assert isinstance(data["lots_closed_count"], int)


def assert_tranche(data: dict):
    _assert_common(data)
    assert isinstance(data["tranche_no"], int) and data["tranche_no"] >= 1
    assert isinstance(data["lot_count_due"], int) and data["lot_count_due"] >= 1
    assert isinstance(data["lots_credited"], int)
    assert isinstance(data["accrued_penalty_cents"], int)
    assert data["status"] in [
        "SCHEDULED", "OPEN", "SATISFIED", "MISSED", "CURED", "WAIVED", "DEFAULTED", "CANCELLED",
    ]


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert isinstance(data["lot_premium_cents"], int)
    assert data["status"] in ["PLATTED", "OFFERED", "UNDER_CONTRACT", "CLOSED", "WITHDRAWN"]


def assert_closing(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "CLOSED", "CANCELLED", "RESCINDED"]


def assert_budget(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int) and data["fiscal_year"] >= 2020
    assert isinstance(data["total_expense_cents"], int)
    assert isinstance(data["reserve_cents"], int)
    assert data["status"] in ["DRAFT", "PROPOSED", "PENDING_RATIFICATION", "ADOPTED", "REJECTED", "SUPERSEDED"]


def assert_line_item(data: dict):
    _assert_common(data)
    assert data["category"] in [
        "LANDSCAPE_MAINTENANCE", "AMENITY_OPERATIONS", "UTILITIES", "MANAGEMENT",
        "INSURANCE", "RESERVE_CONTRIBUTION", "EVENTS_PROGRAMMING", "CONTINGENCY",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_assessment_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["per_unit_annual_cents"], int)
    assert isinstance(data["quarterly_installments_cents"], list)
    assert data["status"] in ["CALCULATED", "ARMED", "EFFECTIVE", "SUPERSEDED"]


def assert_district(data: dict):
    _assert_common(data)
    assert isinstance(data["advance_principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["provisional_interest_cents"], int)
    assert isinstance(data["available_funds_cents"], int)


def assert_advance(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["reimbursed_principal_cents"], int)
    assert data["status"] in ["OUTSTANDING", "PARTIALLY_REIMBURSED", "REIMBURSED"]


def assert_levy(data: dict):
    _assert_common(data)
    assert isinstance(data["levy_year"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["PLANNED", "COLLECTED"]


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["REQUESTED", "CERTIFIED", "PAID", "REJECTED"]


def assert_application(data: dict):
    _assert_common(data)
    assert data["project_type"] in ["NEW_CONSTRUCTION", "EXTERIOR_MODIFICATION", "LANDSCAPE", "ADDITION"]
    assert isinstance(data["submission_round"], int)
    assert isinstance(data["review_fee_cents"], int)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "CONDITIONALLY_APPROVED",
        "DENIED", "RESUBMITTED", "EXPIRED", "WITHDRAWN",
    ]


def assert_violation(data: dict):
    _assert_common(data)
    assert data["violation_type"] in [
        "UNAPPROVED_MODIFICATION", "NONCONFORMING_MATERIALS", "SETBACK", "LANDSCAPE_DEADLINE",
    ]
    assert data["status"] in [
        "REPORTED", "NOTICE_SENT", "CURED", "ESCALATED", "HEARING_SCHEDULED",
        "FINED", "PAID", "APPEALED", "DISMISSED",
    ]


def assert_event(data: dict):
    _assert_common(data)
    assert data["venue"] in ["CLUBHOUSE", "POOL_DECK", "EVENT_LAWN", "SALES_CENTER"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int)
    assert data["status"] in ["PROPOSED", "SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_rsvp(data: dict):
    _assert_common(data)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in ["CONFIRMED", "WAITLISTED", "CANCELLED"]


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED"]


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ["PROSPECT", "PURCHASER", "OWNER", "FORMER"]


def assert_notice(data: dict):
    _assert_common(data)
    assert data["notice_type"] in [
        "ASSESSMENT_CHANGE", "TRANSITION_UPDATE", "AMENITY_DELINQUENCY",
        "GENERAL_MEETING", "BUDGET_ADOPTION",
    ]
    assert data["status"] in ["DRAFT", "SCHEDULED", "SENT", "CANCELLED", "SUPERSEDED"]


def assert_board_seat(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_no"], int) and 1 <= data["seat_no"] <= 5
    assert data["seat_class"] in ["DECLARANT_APPOINTED", "OWNER_ELECTED"]
    assert data["status"] in ["FILLED", "VACANT", "ELECTION_CALLED", "LAPSED"]


def assert_district_principal_invariant(district: dict, certified_principal_outstanding: int):
    """advance_principal_cents == outstanding_principal_cents + certified
    principal outstanding in CERTIFIED/PAID payments."""
    assert district["advance_principal_cents"] == (
        district["outstanding_principal_cents"] + certified_principal_outstanding
    ), (
        f"principal conservation broken: {district['advance_principal_cents']} != "
        f"{district['outstanding_principal_cents']} + {certified_principal_outstanding}"
    )
