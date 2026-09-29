"""Payload factories — one per write endpoint, client-supplied fields only."""

from .constants import TEST_ELECTION


def election_payload(**overrides) -> dict:
    payload = dict(TEST_ELECTION)
    payload.update(overrides)
    return payload


def voter_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Boyle",
        "party_affiliation": "DEM",
        "residence_address": "17 Quince St",
        "last_signature_update_at": "2026-01-05T00:00:00Z",
        "uocava_status": "NONE",
        "signature_on_file_count": 1,
    }
    payload.update(overrides)
    return payload


def reviewer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Tess Ward",
        "party_affiliation": "NPP",
        "training_status": "TRAINED",
        "training_completed_at": "2026-08-01T00:00:00Z",
        "curriculum_version": "2026.1",
    }
    payload.update(overrides)
    return payload


def training_completion_payload(**overrides) -> dict:
    payload = {
        "completed_at": "2026-08-01T00:00:00Z",
        "curriculum_version": "2026.1",
    }
    payload.update(overrides)
    return payload


def ballot_request_payload(voter_id, election_id, expected_voter_version, **overrides) -> dict:
    payload = {
        "voter_id": voter_id,
        "election_id": election_id,
        "request_channel": "ONLINE",
        "delivery_method": "MAIL",
        "expected_voter_version": expected_voter_version,
    }
    payload.update(overrides)
    return payload


def address_result_payload(ncoa_result="MATCH_SAME", **overrides) -> dict:
    payload = {"ncoa_result": ncoa_result}
    payload.update(overrides)
    return payload


def mailing_batch_payload(election_id, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "batch_type": "DOMESTIC_INITIAL",
        "scheduled_send_date": "2026-09-15",
    }
    payload.update(overrides)
    return payload


def packet_payload(ballot_request_id, packet_weight_grams=28, **overrides) -> dict:
    payload = {
        "ballot_request_id": ballot_request_id,
        "packet_weight_grams": packet_weight_grams,
    }
    payload.update(overrides)
    return payload


def return_envelope_payload(ballot_packet_id, intake_channel="DROPBOX", **overrides) -> dict:
    payload = {
        "ballot_packet_id": ballot_packet_id,
        "intake_channel": intake_channel,
    }
    payload.update(overrides)
    return payload


# A similarity score is required for MATCH and NO_MATCH and forbidden for the two
# decisions that carry no visual judgment, so it is omitted for those.
SCORELESS_DECISIONS = ("MISSING_SIGNATURE", "ABSTAIN")


def signature_decision_payload(decision="MATCH", similarity_score=90, **overrides) -> dict:
    payload = {"decision": decision}
    if decision not in SCORELESS_DECISIONS:
        payload["similarity_score"] = similarity_score
    payload.update(overrides)
    return payload


def cure_evidence_payload(**overrides) -> dict:
    payload = {
        "evidence_type": "SIGNED_AFFIDAVIT",
        "submission_channel": "MAIL",
        "affirmation_signed": True,
    }
    payload.update(overrides)
    return payload


def cure_adjudication_payload(outcome="CURE", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def remake_payload(team_member_a_reviewer_id, team_member_b_reviewer_id,
                   expected_envelope_version, **overrides) -> dict:
    payload = {
        "team_member_a_reviewer_id": team_member_a_reviewer_id,
        "team_member_b_reviewer_id": team_member_b_reviewer_id,
        "reason_code": "DAMAGED",
        "session_start_at": "2026-11-05T09:00:00Z",
        "session_end_at": "2026-11-05T10:00:00Z",
        "expected_envelope_version": expected_envelope_version,
    }
    payload.update(overrides)
    return payload


def challenge_payload(challenge_reason_code="SIGNATURE_DISPUTE", **overrides) -> dict:
    payload = {"challenge_reason_code": challenge_reason_code}
    payload.update(overrides)
    return payload


def challenge_adjudication_payload(outcome="OVERRULE",
                                   challenge_findings="Reviewed and resolved.",
                                   **overrides) -> dict:
    payload = {"outcome": outcome, "challenge_findings": challenge_findings}
    payload.update(overrides)
    return payload


def observer_session_payload(observer_user_id, **overrides) -> dict:
    payload = {
        "observer_user_id": observer_user_id,
        "observer_name": "Olive Reed",
        "organization": "League of Voters",
        "party_affiliation": "DEM",
        "station_area": "SIGNATURE_REVIEW",
        "window_start_at": "2026-11-04T09:00:00Z",
        "window_end_at": "2026-11-04T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def separation_run_payload(return_envelope_ids, **overrides) -> dict:
    payload = {"return_envelope_ids": list(return_envelope_ids)}
    payload.update(overrides)
    return payload
