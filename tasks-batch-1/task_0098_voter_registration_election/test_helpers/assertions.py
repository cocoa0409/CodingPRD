"""Entity assertions and domain invariant checkers.

Audit-bearing entities are checked for id/created_at plus their domain fields.
The two lightweight entities (MachineFailure, EarlyVoteCheckIn) carry only id +
created_at, so their assertions never demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_ELECTION_STATES = {"SCHEDULED", "REGISTRATION_OPEN", "VOTING_OPEN", "POLLS_CLOSED", "CERTIFIED"}
_POSTURES = {"OPEN", "FULL"}
_TALLY_STATES = {"PENDING", "TALLIED"}
_REG_STATES = {"PENDING", "NEEDS_REVIEW", "ACTIVE", "REJECTED", "WITHDRAWN"}
_PARTIES = {"DEMOCRAT", "REPUBLICAN", "INDEPENDENT", "GREEN", "LIBERTARIAN", "UNAFFILIATED"}
_REQUEST_STATES = {"REQUESTED", "ISSUED", "RETURNED", "ACCEPTED", "REJECTED"}
_CURE_STATES = {"NONE", "FLAGGED", "CURE_PENDING", "CURED", "CURE_FAILED"}
_CURE_CASE_STATES = {"OPEN", "RESPONSE_SUBMITTED", "APPROVED", "DENIED", "EXPIRED"}
_MACHINE_ROLES = {"PRIMARY", "BACKUP"}
_MACHINE_STATES = {"OPERATIONAL", "FAILED", "REPLACED", "RETIRED"}
_RESOLUTIONS = {"BACKUP_ACTIVATED", "NO_BACKUP_AVAILABLE"}
_RECOUNT_STATES = {"REQUESTED", "MACHINE_DONE", "HAND_DONE", "BOTH_DONE", "CERTIFIED", "DISMISSED"}


def _assert_common_audit(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def _assert_lightweight(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lightweight entity must NOT carry updated_at"
    assert "version" not in data, "lightweight entity must NOT carry version"


def assert_election(data: dict):
    _assert_common_audit(data)
    assert data["status"] in _ELECTION_STATES, f"unexpected election status {data['status']!r}"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_registered"], int)
    assert isinstance(data["total_ballots_accepted"], int)


def assert_precinct(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["election_id"]), "election_id must be a UUID"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["max_registrations"], int) and data["max_registrations"] >= 1
    assert data["street_high"] >= data["street_low"], "street_high must be >= street_low"
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0
    assert data["capacity_posture"] in _POSTURES
    assert data["tally_status"] in _TALLY_STATES


def assert_voter_registration(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["election_id"]), "election_id must be a UUID"
    assert data["status"] in _REG_STATES, f"unexpected registration status {data['status']!r}"
    assert data["party"] in _PARTIES, f"unexpected party {data['party']!r}"
    assert isinstance(data["is_citizen"], bool)
    assert isinstance(data["street_number"], int)


def assert_absentee_ballot(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["registration_id"]), "registration_id must be a UUID"
    assert data["request_status"] in _REQUEST_STATES
    assert data["cure_status"] in _CURE_STATES


def assert_cure_case(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["ballot_id"]), "ballot_id must be a UUID"
    assert data["status"] in _CURE_CASE_STATES


def assert_voting_machine(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["precinct_id"]), "precinct_id must be a UUID"
    assert data["role"] in _MACHINE_ROLES
    assert data["status"] in _MACHINE_STATES
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_machine_failure(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data["machine_id"]), "machine_id must be a UUID"
    assert data["resolution"] in _RESOLUTIONS


def assert_early_vote_checkin(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data["registration_id"]), "registration_id must be a UUID"
    assert is_iso8601_timestamp(data.get("checked_in_at", "")), "checked_in_at must be ISO 8601"


def assert_recount_case(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data["election_id"]), "election_id must be a UUID"
    assert is_valid_uuid(data["precinct_id"]), "precinct_id must be a UUID"
    assert data["status"] in _RECOUNT_STATES
