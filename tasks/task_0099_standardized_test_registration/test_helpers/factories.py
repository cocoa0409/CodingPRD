"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the request-body input fields for a create call.
System- and server-computed fields are never included (the server sets them).
"""

DEFAULTS = {
    "CENTER_NAME": "Bay Center",
    "CENTER_STATE": "CA",
    "ROOM_STANDARD": 50,
    "ROOM_ACCOMMODATED": 5,
    "BASE_FEE_CENTS": 6000,
    "EXAM_TYPE": "SAT",
    "EXAM_SUBJECT": "GENERAL",
    "TEST_DATE": "2026-09-01",
    "WINDOW_START": "2026-09-01T13:00:00.000Z",
    "WINDOW_END": "2026-09-01T17:00:00.000Z",
    "FIRST_NAME": "Ada",
    "LAST_NAME": "Lovelace",
    "DOB": "2008-12-10",
    "HOME_STATE": "CA",
    "ID_STATE": "CA",
    "RECIPIENT_CODE": "0001",
    "CLEP_SUBJECT": "COLLEGE_ALGEBRA",
}


def create_test_center_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CENTER_NAME"],
        "state_code": DEFAULTS["CENTER_STATE"],
        "room_capacity_standard": DEFAULTS["ROOM_STANDARD"],
        "room_capacity_accommodated": DEFAULTS["ROOM_ACCOMMODATED"],
    }
    payload.update(overrides)
    return payload


def create_test_session_payload(test_center_id, **overrides) -> dict:
    payload = {
        "test_center_id": test_center_id,
        "exam_type": DEFAULTS["EXAM_TYPE"],
        "exam_subject": DEFAULTS["EXAM_SUBJECT"],
        "test_date": DEFAULTS["TEST_DATE"],
        "window_start_utc": DEFAULTS["WINDOW_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(**overrides) -> dict:
    # has_active_504_iep is optional (defaults false server-side); omitted unless given.
    payload = {
        "legal_first_name": DEFAULTS["FIRST_NAME"],
        "legal_last_name": DEFAULTS["LAST_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "home_state_code": DEFAULTS["HOME_STATE"],
        "id_document_state_code": DEFAULTS["ID_STATE"],
    }
    payload.update(overrides)
    return payload


def create_registration_payload(test_session_id, candidate_id, expected_test_session_version, **overrides) -> dict:
    # fee_reduction_pct is optional (defaults 0.0 server-side); omitted unless given.
    payload = {
        "test_session_id": test_session_id,
        "candidate_id": candidate_id,
        "expected_test_session_version": expected_test_session_version,
    }
    payload.update(overrides)
    return payload


def create_accommodation_request_payload(candidate_id, target_registration_id,
                                         accommodation_type, basis, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "target_registration_id": target_registration_id,
        "accommodation_type": accommodation_type,
        "basis": basis,
    }
    payload.update(overrides)
    return payload


def create_standby_entry_payload(test_session_id, candidate_id, priority_tier, **overrides) -> dict:
    payload = {
        "test_session_id": test_session_id,
        "candidate_id": candidate_id,
        "priority_tier": priority_tier,
    }
    payload.update(overrides)
    return payload


def create_score_report_payload(exam_type, section_scores, **overrides) -> dict:
    payload = {
        "exam_type": exam_type,
        "section_scores": section_scores,
    }
    payload.update(overrides)
    return payload


def create_score_send_payload(registration_id, recipient_code, **overrides) -> dict:
    # use_super_score is optional (defaults false server-side); omitted unless given.
    payload = {
        "registration_id": registration_id,
        "recipient_code": recipient_code,
    }
    payload.update(overrides)
    return payload


def create_clep_claim_payload(candidate_id, clep_subject, clep_scaled_score, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "clep_subject": clep_subject,
        "clep_scaled_score": clep_scaled_score,
    }
    payload.update(overrides)
    return payload


def create_id_verification_payload(presented_first_name, presented_last_name,
                                   presented_id_state_code, **overrides) -> dict:
    payload = {
        "presented_first_name": presented_first_name,
        "presented_last_name": presented_last_name,
        "presented_id_state_code": presented_id_state_code,
    }
    payload.update(overrides)
    return payload


def request_info_payload(reviewer_note, **overrides) -> dict:
    payload = {"reviewer_note": reviewer_note}
    payload.update(overrides)
    return payload


def deny_payload(reviewer_note, **overrides) -> dict:
    payload = {"reviewer_note": reviewer_note}
    payload.update(overrides)
    return payload
