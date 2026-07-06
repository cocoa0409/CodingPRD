"""Complaint intake, severity/priority scoring, and request-integrity basics."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_complaint, make_officer,
    create_complaint_payload, create_officer_payload,
    assert_complaint, assert_officer,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ==========================================================================
# Difficulty: combinatorial_formula / complaint_priority_multi_input_nonlinear
# ==========================================================================
def test_priority_score_nonlinear_multi_input_equals_100(api):
    """PRD 3.1: "a bite scores 50" and "wildlife multiplies by 1.5". PRD 3.1:
    "the system counts the complaints already persisted in the same zone whose
    status is either NEW or DISPATCHED ... multiplies that count by 5, and caps
    the result at 20." PRD 3.1: "a vulnerable-victim bonus of 15 points, added
    when involves_vulnerable_victim is true and 0 otherwise." PRD 3.1: "The
    severity_score is the animal-weighted base plus the repeat bonus plus the
    vulnerable bonus, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/complaint_priority_multi_input_nonlinear
    """
    make_complaint(api, reporter_name="P1", zone="NORTH", animal_type="DOG", complaint_type="NOISE")
    make_complaint(api, reporter_name="P2", zone="NORTH", animal_type="CAT", complaint_type="STRAY")
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="T", zone="NORTH", animal_type="WILDLIFE",
        complaint_type="BITE", involves_vulnerable_victim=True), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    # 50 * 1.5 + min(2*5, 20) + 15 = 75 + 10 + 15 = 100.00
    assert data["severity_score"] == pytest.approx(100.00, abs=0.01)


def test_priority_score_100_maps_to_p1(api):
    """PRD 3.1: "a score of at least 60 is P1, a score of at least 30 but below
    60 is P2, and anything below 30 is P3."

    Design: Difficulty/combinatorial_formula/complaint_priority_multi_input_nonlinear
    """
    make_complaint(api, reporter_name="P1", zone="NORTH", animal_type="DOG", complaint_type="NOISE")
    make_complaint(api, reporter_name="P2", zone="NORTH", animal_type="CAT", complaint_type="STRAY")
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="T", zone="NORTH", animal_type="WILDLIFE",
        complaint_type="BITE", involves_vulnerable_victim=True), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    assert data["severity_score"] == pytest.approx(100.00, abs=0.01)
    assert data["priority"] == "P1"


# ==========================================================================
# Difficulty: boundary_precision_check / priority_threshold_60_inclusive
# ==========================================================================
def test_severity_exactly_60_on_bite_dog(api):
    """PRD 3.1: "a bite scores 50" and "dogs by 1.2". PRD 3.1: "The
    severity_score is the animal-weighted base plus the repeat bonus plus the
    vulnerable bonus, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/priority_threshold_60_inclusive
    """
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="T60", zone="SOUTH", animal_type="DOG", complaint_type="BITE"), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    # 50 * 1.2 = 60.00, no repeat bonus (empty DB), no vulnerable bonus.
    assert data["severity_score"] == pytest.approx(60.00, abs=0.01)


def test_score_of_exactly_60_is_p1_inclusive(api):
    """PRD 3.1: "a score of at least 60 is P1, a score of at least 30 but below
    60 is P2, and anything below 30 is P3."

    Design: Difficulty/boundary_precision_check/priority_threshold_60_inclusive
    """
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="T60", zone="SOUTH", animal_type="DOG", complaint_type="BITE"), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    assert data["severity_score"] == pytest.approx(60.00, abs=0.01)
    assert data["priority"] == "P1"


# ==========================================================================
# Corner: entities
# ==========================================================================
def test_cat_stray_scores_15_priority_p3(api):
    """PRD 3.1: "a stray 15" and "both cats and the catch-all "other" by 1.0."
    PRD 3.1: "anything below 30 is P3."

    Design: Corner/entities/complaint_create_computed_priority_p3
    """
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="Q1", zone="EAST", animal_type="CAT", complaint_type="STRAY"), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    assert_complaint(data)
    assert data["severity_score"] == pytest.approx(15.00, abs=0.01)
    assert data["priority"] == "P3"


def test_vulnerable_flag_defaults_false_no_bonus(api):
    """PRD 3.1: "the optional involves_vulnerable_victim flag records whether a
    minor or elderly person is involved; when omitted it is treated as false."
    PRD 3.1: "a stray 15" and "dogs by 1.2".

    Design: Corner/entities/complaint_default_vulnerable_false
    """
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="Q2", zone="EAST", animal_type="DOG", complaint_type="STRAY"), DISPATCHER)
    data = validate_success(resp, expected_status=201)
    assert data["involves_vulnerable_victim"] is False
    # 15 * 1.2 = 18.00, no vulnerable bonus applied.
    assert data["severity_score"] == pytest.approx(18.00, abs=0.01)


def test_officer_registration_mints_id_and_zero_dispatch_count(api):
    """PRD 3.2: "A freshly registered officer has active_dispatch_count of 0."
    PRD 2.4: "id — a unique, server-minted UUID with no type prefix."

    Design: Corner/entities/officer_system_fields_generated
    """
    resp = api.create_officer(create_officer_payload(
        name="Sys Ofc", badge_number="SB1", territory_zone="WEST"), SUPERVISOR)
    data = validate_success(resp, expected_status=201)
    assert_officer(data)
    assert data["active_dispatch_count"] == 0


def test_complaint_missing_complaint_type_rejected(api):
    """PRD 2.6: "Required body fields present, enum values valid, datetimes
    parseable, numeric fields well-formed, and window ordering satisfied
    (scheduled_end_at strictly after scheduled_start_at; hold_until strictly
    after impounded_at) — otherwise ERR_INVALID_REQUEST (422)."

    Design: Corner/entities/complaint_missing_required_complaint_type_rejected
    """
    resp = api.create_complaint(
        {"reporter_name": "Bad", "reporter_phone": "555-3004", "zone": "EAST", "animal_type": "DOG"},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_complaint_invalid_zone_enum_rejected(api):
    """PRD 2.6: "Required body fields present, enum values valid, datetimes
    parseable, numeric fields well-formed, and window ordering satisfied
    (scheduled_end_at strictly after scheduled_start_at; hold_until strictly
    after impounded_at) — otherwise ERR_INVALID_REQUEST (422)."

    Design: Corner/entities/complaint_invalid_enum_zone_rejected
    """
    resp = api.create_complaint(create_complaint_payload(
        reporter_name="Bad2", zone="MARS", animal_type="DOG", complaint_type="STRAY"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_missing_complaint_returns_404(api):
    """PRD 2.6: "the first unresolved id yields the matching not-found error
    (ERR_COMPLAINT_NOT_FOUND, ERR_OFFICER_NOT_FOUND, ERR_KENNEL_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND, ERR_CASE_NOT_FOUND, ERR_QUARANTINE_HOLD_NOT_FOUND,
    ERR_IMPOUND_NOT_FOUND, ERR_CITATION_NOT_FOUND, or
    ERR_RABIES_REPORT_NOT_FOUND), all 404."

    Design: Corner/entities/complaint_not_found_returns_404
    """
    resp = api.get_complaint(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)
