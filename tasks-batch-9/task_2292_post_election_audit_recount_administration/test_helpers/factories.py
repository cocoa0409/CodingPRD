"""Payload factories: one per entity, carrying only client-supplied fields."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_election_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "jurisdiction_code": TEST_DEFAULTS["E1_JURISDICTION_CODE"],
        "election_name": TEST_DEFAULTS["E1_ELECTION_NAME"],
        "election_date": TEST_DEFAULTS["E1_ELECTION_DATE"],
        "certification_deadline_at": TEST_DEFAULTS["E1_CERTIFICATION_DEADLINE_AT"],
    }
    payload.update(overrides)
    return payload


def create_contest_payload(election_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "contest_label": TEST_DEFAULTS["C1_LABEL"],
        "office_name": TEST_DEFAULTS["C1_OFFICE_NAME"],
        "contest_type": "CANDIDATE",
        "candidate_names": list(TEST_DEFAULTS["C1_CANDIDATES"]),
        "ballots_cast": TEST_DEFAULTS["C1_BALLOTS_CAST"],
        "cvr_available": True,
    }
    payload.update(overrides)
    return payload


def create_ballot_batch_payload(
    election_id: str, contest_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "contest_id": contest_id,
        "batch_label": "B-001",
        "storage_location_code": TEST_DEFAULTS["C1_STORAGE_LOCATION_CODE"],
        "ballot_count": TEST_DEFAULTS["C1_BATCH_BALLOT_COUNT"],
        "machine_votes": dict(TEST_DEFAULTS["C1_BATCH_MACHINE_VOTES"]),
        "current_seal_number": "SEAL-001",
    }
    payload.update(overrides)
    return payload


def batch_line(
    batch_label: str,
    ballot_count: int,
    machine_votes: Dict[str, int],
    current_seal_number: str,
    storage_location_code: str = TEST_DEFAULTS["C1_STORAGE_LOCATION_CODE"],
) -> Dict[str, Any]:
    """One entry of the `batches` array accepted by the bulk batch endpoint."""
    return {
        "batch_label": batch_label,
        "storage_location_code": storage_location_code,
        "ballot_count": ballot_count,
        "machine_votes": dict(machine_votes),
        "current_seal_number": current_seal_number,
    }


def six_uniform_batch_lines() -> List[Dict[str, Any]]:
    """B-001..B-006, each 1000 ballots machine-tabulated ALVAREZ 525 / BRENNAN 475."""
    return [
        batch_line(
            f"B-00{index}",
            TEST_DEFAULTS["C1_BATCH_BALLOT_COUNT"],
            TEST_DEFAULTS["C1_BATCH_MACHINE_VOTES"],
            f"SEAL-00{index}",
        )
        for index in range(1, 7)
    ]


def bulk_ballot_batches_payload(
    election_id: str,
    contest_id: str,
    batches: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "contest_id": contest_id,
        "batches": batches if batches is not None else six_uniform_batch_lines(),
    }
    payload.update(overrides)
    return payload


def canvass_results_payload(**overrides) -> Dict[str, Any]:
    payload = {"reported_votes": dict(TEST_DEFAULTS["C1_REPORTED_VOTES"])}
    payload.update(overrides)
    return payload


def create_audit_payload(contest_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "contest_id": contest_id,
        "audit_type": "RISK_LIMITING",
        "risk_limit_alpha": TEST_DEFAULTS["RISK_LIMIT_ALPHA"],
    }
    payload.update(overrides)
    return payload


def seed_audit_payload(**overrides) -> Dict[str, Any]:
    payload = {"random_seed": TEST_DEFAULTS["AUDIT_SEED"]}
    payload.update(overrides)
    return payload


def create_audit_round_payload(expected_audit_version: int, **overrides) -> Dict[str, Any]:
    payload = {"expected_audit_version": expected_audit_version}
    payload.update(overrides)
    return payload


def retrieve_audit_batch_payload(
    expected_ballot_batch_version: int, observed_seal_number: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "expected_ballot_batch_version": expected_ballot_batch_version,
        "observed_seal_number": observed_seal_number,
    }
    payload.update(overrides)
    return payload


def return_audit_batch_payload(reseal_number: str, **overrides) -> Dict[str, Any]:
    payload = {"reseal_number": reseal_number}
    payload.update(overrides)
    return payload


def create_tally_team_payload(election_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "team_label": "T-1",
        "room_code": "ROOM-A",
    }
    payload.update(overrides)
    return payload


def bipartisan_members_payload(
    dem_user_id: str = TEST_DEFAULTS["TEAM_DEM_USER_ID"],
    rep_user_id: str = TEST_DEFAULTS["TEAM_REP_USER_ID"],
) -> Dict[str, Any]:
    return {
        "members": [
            {"user_id": dem_user_id, "party": "DEM", "seat_role": "LEAD"},
            {"user_id": rep_user_id, "party": "REP", "seat_role": "COUNTER"},
        ]
    }


def create_manual_tally_payload(
    audit_batch_id: str,
    tally_team_id: str,
    session_start_at: str,
    session_end_at: str,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "audit_batch_id": audit_batch_id,
        "tally_team_id": tally_team_id,
        "session_start_at": session_start_at,
        "session_end_at": session_end_at,
    }
    payload.update(overrides)
    return payload


def create_ballot_interpretation_payload(
    manual_tally_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "manual_tally_id": manual_tally_id,
        "ballot_ref": "B-003-0417",
        "ambiguity_type": "PARTIAL_MARK",
        "proposed_determination": "ALVAREZ",
    }
    payload.update(overrides)
    return payload


def board_vote_payload(party: str, vote: str) -> Dict[str, Any]:
    return {"party": party, "vote": vote}


def create_recount_payload(
    contest_id: str, expected_contest_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "contest_id": contest_id,
        "expected_contest_version": expected_contest_version,
        "trigger_type": "CANDIDATE_REQUESTED",
        "scope": "FULL_CONTEST",
    }
    payload.update(overrides)
    return payload


def create_corrective_action_payload(discrepancy_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "discrepancy_id": discrepancy_id,
        "category": "PROCESS",
        "description": "Retrain the counting board on blank-ballot handling.",
        "due_at": "2026-11-20T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_observer_credential_payload(election_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "organization_name": "League of Voters",
        "party_affiliation": "DEM",
        "room_code": "ROOM-A",
        "access_start_at": "2026-11-05T09:00:00Z",
        "access_end_at": "2026-11-05T17:00:00Z",
    }
    payload.update(overrides)
    return payload
