"""Payload factories — one per resource, client-supplied input fields only."""

DEFAULTS = {
    "VOLUNTEER_NAME": "Ada Reyes",
    "VOLUNTEER_EMAIL": "ada@krcr.example",
    "ROLE_TRACK": "PROGRAMMER",
    "SENIORITY_START_DATE": "2024-08-01",
    "CERT_TYPE": "BOARD_OPERATION",
    "PASSING_SCORE": 88,
    "FAILING_SCORE": 70,
    "PROPOSAL_TITLE": "Delta Blues Hour",
    "FORMAT_CODE": "MUSIC",
    "LANGUAGE_CODE": "EN",
    "DAYPART": "MIDDAY",
    "DURATION_MINUTES": 60,
    "SEASON_CODE": "FALL-2026",
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2026-12-31T23:59:00Z",
    "DAY_OF_WEEK": 1,
    "START_MINUTE": 540,
    "SLOT_DURATION": 60,
    "SCHEDULED_START_UTC": "2026-08-03T09:00:00Z",
    "UNDERWRITER_NAME": "Bluebird Bakery",
    "SPOT_CLASS": "UNDERWRITING",
    "FLIGHT_START": "2026-08-01T00:00:00Z",
    "FLIGHT_END": "2026-08-31T23:59:00Z",
    "DRIVE_NAME": "Fall Drive 2026",
    "GOAL_CENTS": 500_000,
    "DRIVE_START": "2026-08-01T00:00:00Z",
    "DRIVE_END": "2026-08-10T00:00:00Z",
    "PHONE_LINE_COUNT": 2,
    "SKU": "MUG-01",
    "PREMIUM_NAME": "Station mug",
    "TIER_THRESHOLD_CENTS": 5000,
    "FAIR_MARKET_VALUE_CENTS": 1500,
    "UNITS_RECEIVED_QTY": 2,
    "DONOR_NAME": "Iris Vance",
    "AMOUNT_CENTS": 6000,
}


def create_volunteer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["VOLUNTEER_NAME"],
        "email": DEFAULTS["VOLUNTEER_EMAIL"],
        "role_track": DEFAULTS["ROLE_TRACK"],
        "seniority_start_date": DEFAULTS["SENIORITY_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> dict:
    payload = {"cert_type": DEFAULTS["CERT_TYPE"]}
    payload.update(overrides)
    return payload


def grade_certification_payload(exam_score=DEFAULTS["PASSING_SCORE"], **overrides) -> dict:
    payload = {"exam_score": exam_score}
    payload.update(overrides)
    return payload


def revoke_certification_payload(incident_id, revocation_reason="Substantiated incident.", **overrides) -> dict:
    payload = {"incident_id": incident_id, "revocation_reason": revocation_reason}
    payload.update(overrides)
    return payload


def create_proposal_payload(proposer_volunteer_id, **overrides) -> dict:
    payload = {
        "proposer_volunteer_id": proposer_volunteer_id,
        "title": DEFAULTS["PROPOSAL_TITLE"],
        "format_code": DEFAULTS["FORMAT_CODE"],
        "language_code": DEFAULTS["LANGUAGE_CODE"],
        "requested_daypart": DEFAULTS["DAYPART"],
        "requested_duration_minutes": DEFAULTS["DURATION_MINUTES"],
    }
    payload.update(overrides)
    return payload


def cast_vote_payload(member_volunteer_id, format_fit_score=4, diversity_score=4,
                      quality_score=4, recommendation="APPROVE", **overrides) -> dict:
    payload = {
        "member_volunteer_id": member_volunteer_id,
        "format_fit_score": format_fit_score,
        "diversity_score": diversity_score,
        "quality_score": quality_score,
        "recommendation": recommendation,
    }
    payload.update(overrides)
    return payload


def decide_proposal_payload(expected_proposal_version, **overrides) -> dict:
    payload = {"expected_proposal_version": expected_proposal_version}
    payload.update(overrides)
    return payload


def create_schedule_grid_payload(**overrides) -> dict:
    payload = {
        "season_code": DEFAULTS["SEASON_CODE"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_slot_assignment_payload(program_id, expected_grid_version, **overrides) -> dict:
    payload = {
        "expected_grid_version": expected_grid_version,
        "program_id": program_id,
        "day_of_week": DEFAULTS["DAY_OF_WEEK"],
        "start_minute": DEFAULTS["START_MINUTE"],
        "duration_minutes": DEFAULTS["SLOT_DURATION"],
    }
    payload.update(overrides)
    return payload


def publish_grid_payload(expected_grid_version, **overrides) -> dict:
    payload = {"expected_grid_version": expected_grid_version}
    payload.update(overrides)
    return payload


def release_slot_payload(release_reason="Released for testing.", **overrides) -> dict:
    payload = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


def create_episode_payload(program_id, slot_assignment_id, board_operator_volunteer_id,
                           scheduled_start_utc=DEFAULTS["SCHEDULED_START_UTC"], **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "slot_assignment_id": slot_assignment_id,
        "board_operator_volunteer_id": board_operator_volunteer_id,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


def air_result_payload(air_status="AIRED", **overrides) -> dict:
    payload = {"air_status": air_status}
    payload.update(overrides)
    return payload


def create_playlist_entry_payload(sequence_number, artist="The Delta Kings", title="Backwater Blues",
                                  duration_seconds=185, play_source="LIBRARY_CD",
                                  is_local_artist=False, **overrides) -> dict:
    payload = {
        "sequence_number": sequence_number,
        "artist": artist,
        "title": title,
        "duration_seconds": duration_seconds,
        "play_source": play_source,
        "is_local_artist": is_local_artist,
    }
    payload.update(overrides)
    return payload


def log_decision_payload(decision="CERTIFY", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def performance_review_payload(review_window="TRAILING_SIX", **overrides) -> dict:
    payload = {"review_window": review_window}
    payload.update(overrides)
    return payload


def cancel_program_payload(expected_program_version, cancellation_reason="Host withdrew", **overrides) -> dict:
    payload = {
        "expected_program_version": expected_program_version,
        "cancellation_reason": cancellation_reason,
    }
    payload.update(overrides)
    return payload


def create_underwriting_spot_payload(**overrides) -> dict:
    payload = {
        "underwriter_name": DEFAULTS["UNDERWRITER_NAME"],
        "spot_class": DEFAULTS["SPOT_CLASS"],
        "copy_text": "Fresh sourdough is baked daily on Fifth Street.",
        "flight_start": DEFAULTS["FLIGHT_START"],
        "flight_end": DEFAULTS["FLIGHT_END"],
    }
    payload.update(overrides)
    return payload


def review_spot_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def public_file_posting_payload(public_file_reference="PF-2026-0001", **overrides) -> dict:
    payload = {"public_file_reference": public_file_reference}
    payload.update(overrides)
    return payload


def create_incident_payload(category, severity, occurred_at,
                            complainant_note="Complaint on file.", **overrides) -> dict:
    payload = {
        "category": category,
        "severity": severity,
        "occurred_at": occurred_at,
        "complainant_note": complainant_note,
    }
    payload.update(overrides)
    return payload


def adjudicate_incident_payload(finding="SUBSTANTIATED", **overrides) -> dict:
    payload = {"finding": finding}
    payload.update(overrides)
    return payload


def remediate_incident_payload(remediation_note="Corrective action taken.", **overrides) -> dict:
    payload = {"remediation_note": remediation_note}
    payload.update(overrides)
    return payload


def create_membership_drive_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DRIVE_NAME"],
        "goal_cents": DEFAULTS["GOAL_CENTS"],
        "start_at": DEFAULTS["DRIVE_START"],
        "end_at": DEFAULTS["DRIVE_END"],
        "phone_line_count": DEFAULTS["PHONE_LINE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_phone_bank_shift_payload(drive_id, volunteer_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "drive_id": drive_id,
        "volunteer_id": volunteer_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def close_shift_payload(outcome="COMPLETED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_premium_item_payload(**overrides) -> dict:
    payload = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PREMIUM_NAME"],
        "tier_threshold_cents": DEFAULTS["TIER_THRESHOLD_CENTS"],
        "fair_market_value_cents": DEFAULTS["FAIR_MARKET_VALUE_CENTS"],
        "units_received_qty": DEFAULTS["UNITS_RECEIVED_QTY"],
    }
    payload.update(overrides)
    return payload


def premium_receipt_payload(received_qty=1, **overrides) -> dict:
    payload = {"received_qty": received_qty}
    payload.update(overrides)
    return payload


def create_pledge_payload(drive_id, **overrides) -> dict:
    payload = {
        "drive_id": drive_id,
        "donor_name": DEFAULTS["DONOR_NAME"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def pledge_payment_payload(outcome="PAID", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def premium_fulfillment_payload(action="SHIP", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload
