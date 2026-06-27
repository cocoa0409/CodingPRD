"""Photo capture, the auto-match scorer with its inclusive 80 threshold and
tie/selection rules, photo approval, student absence, and the cross-entity
session-posture dependency on matching (PRD §3.3, §3.4).

Queue A: boundary_precision_check, cross_entity_state_dependency,
priority_pair_validation_conflict.
Queue B: state_machines, calculations, endpoints, entities sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_photo_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package, capture_photo,
    create_session_capture_open, match_photo_for_student,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]


# --------------------------------------------------------------------------- #
# boundary_precision_check / match_score_at_80_threshold_inclusive  (queue A)
# --------------------------------------------------------------------------- #
def test_match_score_exactly_80_auto_matches(api):
    """PRD §3.3: "The winning candidate must clear an auto-match threshold of
    eighty points."
    PRD §3.3: "The boundary is inclusive: a score of exactly eighty auto-matches,
    while seventy-nine or below does not."

    Design: Difficulty/boundary_precision_check/match_score_at_80_threshold_inclusive
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Pat Kim", "grade": "6", "homeroom": "R-9",
                           "guardian_user_id": "g1"})
    # candidate matches name + homeroom but NOT grade -> 100*(0.5+0.3) = 80
    photo = capture_photo(session["id"], candidate_name="Pat Kim",
                          candidate_grade="99", candidate_homeroom="R-9")
    matched = validate_success(api.match_photo(photo["id"], PHOTOG), 200)
    assert matched["match_confidence_score"] == 80
    assert matched["status"] == "MATCHED"
    assert matched["matched_student_id"] == student["id"]


def test_match_score_below_80_no_candidate(api):
    """PRD §3.3: "If the candidate set is empty, or the best candidate's score is
    strictly below eighty, the match is refused with ERR_NO_MATCH_CANDIDATE. The
    boundary is inclusive: a score of exactly eighty auto-matches, while
    seventy-nine or below does not."

    Design: Difficulty/boundary_precision_check/match_score_at_80_threshold_inclusive
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Pat Kim", "grade": "6", "homeroom": "R-9",
                           "guardian_user_id": "g1"})
    # name only -> 100*0.5 = 50 (< 80)
    photo = capture_photo(session["id"], candidate_name="Pat Kim",
                          candidate_grade="X", candidate_homeroom="Y")
    res = api.match_photo(photo["id"], PHOTOG)
    validate_error(res, "ERR_NO_MATCH_CANDIDATE", expected_status=422)


# --------------------------------------------------------------------------- #
# Queue B / calculations / match_selector_picks_highest_score_candidate
# --------------------------------------------------------------------------- #
def test_match_selects_highest_scoring_candidate(api):
    """PRD §3.3: "Candidates are ranked by score descending, and ties are broken by
    created_at ascending — the earliest-created student wins a tie, never the id."
    PRD §3.3: "On a successful match, the photo's matched_student_id is set to the
    winning candidate, its match_confidence_score is recorded, the photo advances
    UNMATCHED → MATCHED, and the matched student advances ENROLLED → PHOTOGRAPHED."

    Design: Corner/calculations/match_selector_picks_highest_score_candidate
    """
    session = create_session()
    add_package(session["id"])
    full = add_student(session["id"], full_name="Exact Match", grade="7",
                       homeroom="HM7", guardian_user_id="g1")
    add_student(session["id"], full_name="Exact Match", grade="7",
                homeroom="OTHER", guardian_user_id="g2")
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    photo = capture_photo(session["id"], candidate_name="Exact Match",
                          candidate_grade="7", candidate_homeroom="HM7")
    matched = validate_success(api.match_photo(photo["id"], PHOTOG), 200)
    # FULL scores 100, PARTIAL (name+grade only) scores 70 -> FULL wins
    assert matched["match_confidence_score"] == 100
    assert matched["matched_student_id"] == full["id"]


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / photo_match_requires_session_capture_open (A)
# --------------------------------------------------------------------------- #
def test_match_requires_session_capture_open(api):
    """PRD §3.3: "Matching requires the session to be in CAPTURE_OPEN (otherwise
    ERR_SESSION_NOT_CAPTURING)."

    Design: Difficulty/cross_entity_state_dependency/photo_match_requires_session_capture_open
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Real Kid", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    photo = capture_photo(session["id"], candidate_name="Real Kid",
                          candidate_grade="1", candidate_homeroom="A")
    # move the session out of CAPTURE_OPEN before attempting the match
    api_client.mark_absent(student["id"], PHOTOG)
    api_client.open_gallery(session["id"], COORD)
    res = api.match_photo(photo["id"], PHOTOG)
    validate_error(res, "ERR_SESSION_NOT_CAPTURING", expected_status=409)
    photo_after = validate_success(api.get_photo(photo["id"], PHOTOG), 200)
    assert photo_after["status"] == "UNMATCHED"


def test_match_in_capture_open_succeeds(api):
    """PRD §3.3: "On a successful match, the photo's matched_student_id is set to
    the winning candidate, its match_confidence_score is recorded, the photo
    advances UNMATCHED → MATCHED, and the matched student advances ENROLLED →
    PHOTOGRAPHED."

    Design: Difficulty/cross_entity_state_dependency/photo_match_requires_session_capture_open
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Real Kid", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    photo = capture_photo(session["id"], candidate_name="Real Kid",
                          candidate_grade="1", candidate_homeroom="A")
    matched = validate_success(api.match_photo(photo["id"], PHOTOG), 200)
    assert matched["status"] == "MATCHED"
    assert matched["matched_student_id"] == student["id"]
    student_after = validate_success(api.get_student(student["id"], PHOTOG), 200)
    assert student_after["status"] == "PHOTOGRAPHED"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / state_beats_safety_on_match...  (queue A)
# --------------------------------------------------------------------------- #
def test_match_session_state_error_beats_no_candidate(api):
    """PRD §2.6: "After body validation, the server enforces session posture (is
    the parent session in the right state for this operation), then the target
    resource's own state"
    PRD §2.6: "Domain-specific business gates — scheduling overlap, gallery access,
    the match threshold, shipping prerequisites, retouch credit sufficiency, and the
    settle-time version check — are evaluated last, after the structural checks have
    all passed."
    PRD §3.3: "Matching requires the session to be in CAPTURE_OPEN (otherwise
    ERR_SESSION_NOT_CAPTURING)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_match_after_terminal_session
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Real Kid", "grade": "9", "homeroom": "Z9",
                           "guardian_user_id": "g1"})
    # capture a photo whose slate matches NO enrolled student
    photo = capture_photo(session["id"], candidate_name="Nobody Here",
                          candidate_grade="0", candidate_homeroom="X0")
    api_client.mark_absent(student["id"], PHOTOG)
    api_client.open_gallery(session["id"], COORD)  # session no longer CAPTURE_OPEN
    res = api.match_photo(photo["id"], PHOTOG)
    # session-posture (structural) error wins over the no-candidate (business) gate
    validate_error(res, "ERR_SESSION_NOT_CAPTURING", expected_status=409)


def test_match_no_candidate_in_capture_open(api):
    """PRD §3.3: "If the candidate set is empty, or the best candidate's score is
    strictly below eighty, the match is refused with ERR_NO_MATCH_CANDIDATE."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_match_after_terminal_session
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Real Kid", "grade": "9", "homeroom": "Z9",
                           "guardian_user_id": "g1"})
    photo = capture_photo(session["id"], candidate_name="Nobody Here",
                          candidate_grade="0", candidate_homeroom="X0")
    api_client.mark_absent(student["id"], PHOTOG)  # candidate set now empty
    # session is still CAPTURE_OPEN, so the business gate (not the posture) fires
    res = api.match_photo(photo["id"], PHOTOG)
    validate_error(res, "ERR_NO_MATCH_CANDIDATE", expected_status=422)


# --------------------------------------------------------------------------- #
# Queue B / state_machines + entities + endpoints
# --------------------------------------------------------------------------- #
def test_mark_absent_after_photographed_rejected(api):
    """PRD §3.3: "marking a student who has already been photographed is rejected
    with ERR_STUDENT_ALREADY_PHOTOGRAPHED."

    Design: Corner/state_machines/mark_absent_after_photographed_rejected
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Got Shot", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    match_photo_for_student(session["id"], student)  # student -> PHOTOGRAPHED
    res = api.mark_absent(student["id"], PHOTOG)
    validate_error(res, "ERR_STUDENT_ALREADY_PHOTOGRAPHED", expected_status=409)


def test_reapprove_approved_photo_rejected(api):
    """PRD §3.4: "Approval requires the session to be in GALLERY_OPEN (otherwise
    ERR_SESSION_NOT_GALLERY) and the photo to be in either MATCHED or RETAKEN
    (otherwise ERR_PHOTO_NOT_APPROVABLE)."

    Design: Corner/state_machines/approve_photo_terminal_then_reapprove_invalid
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Pic Kid", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    photo = match_photo_for_student(session["id"], student)
    api_client.open_gallery(session["id"], COORD)
    approved = validate_success(api.approve_photo(photo["id"], COORD), 200)
    assert approved["status"] == "APPROVED"
    res = api.approve_photo(photo["id"], COORD)
    validate_error(res, "ERR_PHOTO_NOT_APPROVABLE", expected_status=409)


def test_yearbook_export_marks_photos_exported(api):
    """PRD §3.4: "The export returns the APPROVED photos and, as a side effect,
    sets yearbook_exported to true on each photo it returns, marking that the frame
    has been included in a yearbook export batch."

    Design: Corner/endpoints/yearbook_export_marks_photos_exported
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Yb Kid", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    photo = match_photo_for_student(session["id"], student)
    api_client.open_gallery(session["id"], COORD)
    api_client.approve_photo(photo["id"], COORD)
    export_res = api.yearbook_export(session["id"], COORD)
    exported, _meta = validate_paginated(export_res)
    assert any(p["id"] == photo["id"] for p in exported)
    photo_after = validate_success(api.get_photo(photo["id"], COORD), 200)
    assert photo_after["yearbook_exported"] is True


def test_list_photos_by_matched_student(api):
    """PRD §4: "List photos (filter by session, matched student, retake lineage,
    status)"
    PRD §3.3: "On a successful match, the photo's matched_student_id is set to the
    winning candidate"

    Design: Corner/endpoints/fk_reverse_list_photos_by_matched_student
    """
    session, student, package = create_session_capture_open(
        student_overrides={"full_name": "Find Me", "grade": "1", "homeroom": "A",
                           "guardian_user_id": "g1"})
    photo = match_photo_for_student(session["id"], student)
    res = api.list_photos(PHOTOG, params={"matched_student_id": student["id"]})
    data, _meta = validate_paginated(res)
    assert any(p["id"] == photo["id"] for p in data)
    assert all(p["matched_student_id"] == student["id"] for p in data)
