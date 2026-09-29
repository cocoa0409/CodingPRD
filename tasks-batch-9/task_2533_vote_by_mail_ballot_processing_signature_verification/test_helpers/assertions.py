"""Entity assertions and domain invariant checkers for the vote-by-mail API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_POSTURES = ["PRE_MAIL", "MAILING", "RECEIVING", "CANVASS_LOCKED", "CERTIFIED"]
_PARTIES = ["DEM", "REP", "NPP", "OTHER"]
_SIGNATURE_STATES = ["UNVERIFIED", "PENDING_REVIEW", "ESCALATED", "CURE_REQUIRED",
                     "ACCEPTED", "REJECTED"]
_CUSTODY_STATES = ["SEALED", "SEPARATED", "COUNTED", "SEQUESTERED", "SUPERSEDED_BY_REMAKE"]
_CHALLENGE_STATES = ["NONE", "CHALLENGED", "SUSTAINED", "OVERRULED"]
_TIMELINESS = ["TIMELY", "TIMELY_BY_POSTMARK", "PROVISIONAL_TIMELY_POSTMARK", "UNTIMELY"]


def assert_common_fields(data: dict):
    """Every mutable resource carries an id, a created_at, an updated_at and a version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer: {data.get('version')!r}"


def assert_immutable_artifact_fields(data: dict):
    """Cure evidence and transparency log entries carry only an id and a created_at:
    they are never updated, so they expose no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an immutable artifact must not expose updated_at"
    assert "version" not in data, "an immutable artifact must not expose version"


def assert_election(data: dict):
    assert_common_fields(data)
    assert data["posture"] in _POSTURES
    assert isinstance(data["postage_budget_cents"], int)
    assert isinstance(data["postmark_grace_days"], int)
    assert isinstance(data["cure_window_days"], int)
    assert is_iso8601_timestamp(data["return_deadline_at"])
    assert is_iso8601_timestamp(data["canvass_lock_at"])
    assert data["reconciliation_status"] in ["IN_BALANCE", "OUT_OF_BALANCE"]
    for counter in ("packets_mailed_count", "envelopes_received_count",
                    "outstanding_packet_count", "undeliverable_packet_count",
                    "countable_envelope_count", "attributable_ballot_count",
                    "rejected_envelope_count", "provisional_referral_count",
                    "open_cure_count", "postage_committed_cents", "postage_actual_cents",
                    "separation_run_sequence", "canvass_sweep_index"):
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"{counter} must be a non-negative integer"
    assert data["canvass_days"] in [17, 21]


def assert_voter(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["party_affiliation"] in _PARTIES
    assert data["registration_status"] in ["ACTIVE", "INACTIVE", "CANCELLED"]
    assert data["uocava_status"] in ["NONE", "MILITARY", "OVERSEAS"]
    assert isinstance(data["signature_on_file_count"], int)
    assert isinstance(data["permanent_absentee_active"], bool)
    assert isinstance(data["provisional_ballot_eligible"], bool)


def assert_reviewer(data: dict):
    assert_common_fields(data)
    assert data["training_status"] in ["UNTRAINED", "TRAINED", "CERTIFIED_LEAD"]
    assert isinstance(data["active_review_count"], int)
    assert isinstance(data["completed_review_count"], int)
    assert data["party_affiliation"] in _PARTIES


def assert_ballot_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["RECEIVED", "ADDRESS_HOLD", "ADDRESS_CLEARED", "APPROVED",
                             "MAILED", "REJECTED", "SUPERSEDED"]
    assert data["request_channel"] in ["ONLINE", "PAPER", "PHONE"]
    assert data["delivery_method"] in ["MAIL", "EMAIL_UOCAVA"]
    assert data["forwarding_class"] in ["UNKNOWN", "SAME_ADDRESS", "FORWARDABLE",
                                       "NON_FORWARDABLE"]
    assert isinstance(data["permanent_flag"], bool)


def assert_address_verification(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "CLEARED", "FAILED"]
    if data.get("ncoa_result") is not None:
        assert data["ncoa_result"] in ["MATCH_SAME", "MATCH_FORWARDABLE",
                                      "MATCH_NON_FORWARDABLE", "NO_MATCH"]


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REMOVED"]
    assert isinstance(data["consecutive_undeliverable_count"], int)
    assert isinstance(data["reinstated_count"], int)


def assert_mailing_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SEALED", "DISPATCHED", "CANCELLED"]
    assert data["batch_type"] in ["UOCAVA", "DOMESTIC_INITIAL", "SUPPLEMENTAL"]
    assert isinstance(data["packet_count"], int)
    assert isinstance(data["estimated_postage_cents"], int)
    assert isinstance(data["required_send_by_date"], str) and data["required_send_by_date"]


def assert_ballot_packet(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["QUEUED", "MAILED", "RETURNED", "UNDELIVERABLE", "SPOILED"]
    assert isinstance(data["packet_weight_grams"], int)
    assert isinstance(data["packet_postage_cents"], int)
    assert isinstance(data["packet_serial"], str) and data["packet_serial"]
    assert isinstance(data["batch_sequence"], int)


def assert_return_envelope(data: dict):
    assert_common_fields(data)
    assert data["intake_channel"] in ["USPS", "DROPBOX", "IN_PERSON"]
    assert data["signature_status"] in _SIGNATURE_STATES
    assert data["custody_status"] in _CUSTODY_STATES
    assert data["challenge_status"] in _CHALLENGE_STATES
    assert data["preliminary_timeliness"] in _TIMELINESS
    if data.get("final_timeliness") is not None:
        assert data["final_timeliness"] in _TIMELINESS
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["review_round_count"], int)
    if data.get("resolved_signature_confidence") is not None:
        assert_confidence_precision(data["resolved_signature_confidence"])


def assert_signature_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ASSIGNED", "SUBMITTED", "VOIDED"]
    assert isinstance(data["review_round"], int) and 1 <= data["review_round"] <= 3
    assert is_valid_uuid(data["reviewer_id"])
    assert is_valid_uuid(data["return_envelope_id"])
    if data.get("decision") is not None:
        assert data["decision"] in ["MATCH", "NO_MATCH", "MISSING_SIGNATURE", "ABSTAIN"]
    if data.get("confidence_score") is not None:
        assert_confidence_precision(data["confidence_score"])


def assert_cure_notice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ISSUED", "UNDER_EVIDENCE_REVIEW", "CURED", "EXPIRED",
                             "WITHDRAWN"]
    assert data["reason_code"] in ["MISSING_SIGNATURE", "SIGNATURE_MISMATCH"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["cure_deadline_at"])
    assert data["canvass_days_at_issue"] in [17, 21]
    assert isinstance(data["open_cure_count_at_issue"], int)
    assert isinstance(data["evidence_submission_count"], int)
    assert isinstance(data["deficiency_count"], int)


def assert_cure_evidence(data: dict):
    assert_immutable_artifact_fields(data)
    assert data["evidence_type"] in ["SIGNED_AFFIDAVIT", "ID_COPY", "WITNESS_ATTESTATION"]
    assert data["submission_channel"] in ["MAIL", "EMAIL", "IN_PERSON", "PORTAL"]
    assert isinstance(data["affirmation_signed"], bool)
    assert is_iso8601_timestamp(data["received_at"])


def assert_remake_record(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "COMPLETED", "VOIDED"]
    assert data["reason_code"] in ["DAMAGED", "UNREADABLE_MARKS", "DUPLICATE_BALLOT",
                                  "TORN_ENVELOPE"]
    assert is_iso8601_timestamp(data["session_start_at"])
    assert is_iso8601_timestamp(data["session_end_at"])
    assert is_valid_uuid(data["team_member_a_reviewer_id"])
    assert is_valid_uuid(data["team_member_b_reviewer_id"])


def assert_observer_session(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "CHECKED_IN", "CLOSED", "REVOKED"]
    assert data["station_area"] in ["INTAKE", "SIGNATURE_REVIEW", "SEPARATION", "REMAKE"]
    assert data["party_affiliation"] in _PARTIES
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])


def assert_transparency_entry(data: dict):
    assert_immutable_artifact_fields(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert data["ballot_content_disclosed"] is False, \
        "a transparency log entry never discloses ballot content"
    assert is_iso8601_timestamp(data["recorded_at"])
    assert data["actor_role"] in ["ElectionsAdmin", "ElectionsClerk", "SignatureReviewer",
                                 "CanvassSupervisor", "Observer", "system"]
    if data["actor_role"] == "system":
        assert data.get("actor_user_id") is None, \
            "a system-actor entry carries a null actor_user_id"


# --- Domain invariant checkers ------------------------------------------------

def assert_confidence_precision(value):
    """A confidence score lies inside [0.0, 1.0] and is reported to four decimals."""
    assert isinstance(value, (int, float)), f"confidence must be numeric: {value!r}"
    assert 0.0 <= value <= 1.0, f"confidence must be clamped into [0.0, 1.0]: {value}"
    assert round(float(value), 4) == float(value), \
        f"confidence must be rounded to 4 decimal places: {value}"


def assert_whole_cents(value):
    """Every monetary amount is an integer count of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"amount must be whole cents as an integer: {value!r}"
    assert value >= 0, f"amount must not be negative: {value}"


def assert_accountability_identity(data: dict):
    """accountability_delta is packets_mailed_count minus the sum of the returned,
    outstanding and undeliverable counts, and the status follows its sign."""
    delta = (data["packets_mailed_count"]
             - (data["returned_packet_count"] + data["outstanding_packet_count"]
                + data["undeliverable_packet_count"]))
    assert data["accountability_delta"] == delta, \
        f"accountability_delta must equal {delta}, got {data['accountability_delta']}"
    expected = "IN_BALANCE" if delta == 0 else "OUT_OF_BALANCE"
    assert data["reconciliation_status"] == expected, \
        f"reconciliation_status must be {expected} when the delta is {delta}"


def assert_election_counter_bounds(data: dict):
    """No derived envelope population may exceed the ballots the election accounts for."""
    assert data["countable_envelope_count"] <= data["attributable_ballot_count"], \
        "the countable envelopes are a subset of the attributable ballots"
    assert data["outstanding_packet_count"] <= data["packets_mailed_count"]
    assert data["undeliverable_packet_count"] <= data["packets_mailed_count"]


def assert_request_id_format(response_json: dict):
    """Every response reports a request identifier prefixed with req_."""
    meta = response_json.get("meta") or {}
    assert str(meta.get("api_request_id", "")).startswith("req_"), \
        f"api_request_id must start with req_: {meta.get('api_request_id')!r}"
