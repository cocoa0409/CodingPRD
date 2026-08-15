"""Entity assertions and computed-read shape checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_MEETING_STATUSES = [
    "DRAFT", "RECORD_DATE_LOCKED", "MATERIALS_DISTRIBUTED", "VOTING_OPEN",
    "MEETING_IN_PROGRESS", "ADJOURNED", "MEETING_HELD", "RESULTS_CERTIFIED",
    "FILED_8K", "CANCELLED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_meeting(data: dict):
    """Validate a Meeting object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert data["meeting_type"] in ["ANNUAL", "SPECIAL", "CONTESTED"]
    assert isinstance(data["record_date"], str) and data["record_date"]
    assert isinstance(data["meeting_datetime"], str) and data["meeting_datetime"]
    assert data["meeting_mode"] in ["IN_PERSON", "VIRTUAL", "HYBRID"]
    assert isinstance(data["quorum_threshold_pct"], (int, float))
    assert 0 < data["quorum_threshold_pct"] <= 1
    assert isinstance(data["outstanding_shares"], int) and data["outstanding_shares"] > 0
    assert data["status"] in _MEETING_STATUSES
    assert isinstance(data["walk_in_shares"], int) and data["walk_in_shares"] >= 0
    assert "filed_at" in data, "filed_at must be present (null until filing)"
    assert "filing_reference" in data, "filing_reference must be present (null until filing)"


def assert_shareholder_account(data: dict):
    """Validate a ShareholderAccount object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["share_class"] in ["COMMON", "PREFERRED"]
    assert isinstance(data["shares_held"], int) and data["shares_held"] > 0
    assert data["delivery_preference"] in ["NOTICE_AND_ACCESS", "FULL_MAIL", "E_DELIVERY"]
    assert isinstance(data["householding_opt_out"], bool)
    assert data.get("control_number") is not None, "control_number must be minted at creation"
    assert data["status"] in ["PENDING", "ELIGIBLE"]


def assert_broker_search_record(data: dict):
    """Validate a BrokerSearchRecord object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["broker_code"], str) and data["broker_code"]
    assert isinstance(data["broker_name"], str) and data["broker_name"]
    assert data["status"] in ["REQUESTED", "RESPONDED"]
    assert "shares_reported" in data, "shares_reported must be present (null until RESPONDED)"
    if data["shares_reported"] is not None:
        assert isinstance(data["shares_reported"], int) and data["shares_reported"] >= 0


def assert_material_distribution(data: dict):
    """Validate a MaterialDistribution package against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert data["channel"] in ["NOTICE_AND_ACCESS", "FULL_MAIL", "E_DELIVERY"]
    assert isinstance(data["representative_account_id"], str) and data["representative_account_id"]
    assert isinstance(data["covered_account_ids"], list) and len(data["covered_account_ids"]) >= 1
    assert data["representative_account_id"] in data["covered_account_ids"]
    assert isinstance(data["covered_shares"], int) and data["covered_shares"] > 0
    assert data["status"] in ["ACTIVE", "DELIVERED", "BOUNCED", "SUPERSEDED"]


def assert_proposal(data: dict):
    """Validate a Proposal object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["proposal_number"], int)
    assert isinstance(data["title"], str) and data["title"]
    assert data["proposal_type"] in [
        "DIRECTOR_ELECTION", "SAY_ON_PAY", "RATIFICATION", "SHAREHOLDER_PROPOSAL",
    ]
    assert data["vote_standard"] in [
        "MAJORITY_OF_VOTES_CAST", "MAJORITY_OF_OUTSTANDING", "PLURALITY",
    ]
    assert data["board_recommendation"] in ["FOR", "AGAINST", "NO_RECOMMENDATION"]
    assert data["status"] in ["DRAFT", "ACTIVE", "PASSED", "FAILED", "WITHDRAWN"]


def assert_vote_instruction(data: dict):
    """Validate a VoteInstruction object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["proposal_id"], str) and data["proposal_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert data["channel"] in ["INTERNET", "PHONE", "MAIL", "BROKER", "IN_PERSON"]
    assert data["choice"] in ["FOR", "AGAINST", "ABSTAIN", "WITHHOLD"]
    assert isinstance(data["shares_voted"], int) and data["shares_voted"] > 0
    assert data["status"] in ["VALIDATED", "SUPERSEDED", "REVOKED", "INVALIDATED"]


def assert_platform_session(data: dict):
    """Validate a MeetingPlatformSession object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert data["session_type"] in ["REHEARSAL", "LIVE"]
    assert isinstance(data["start_at"], str) and data["start_at"]
    assert isinstance(data["end_at"], str) and data["end_at"]
    assert data["status"] == "SCHEDULED"


def assert_question_submission(data: dict):
    """Validate a QuestionSubmission object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["question_text"], str) and len(data["question_text"]) > 0
    assert "moderation_note" in data, "moderation_note must be present (null until moderated)"
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "RETURNED"]


def assert_vote_challenge(data: dict):
    """Validate a VoteChallenge object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["vote_instruction_id"], str) and data["vote_instruction_id"]
    assert isinstance(data["reason"], str) and data["reason"]
    assert "ruling" in data, "ruling must be present (null until adjudicated)"
    assert "resolution_note" in data, "resolution_note must be present (null until adjudicated)"
    assert data["status"] in ["OPEN", "UPHELD", "OVERRULED"]


def assert_solicitation_campaign(data: dict):
    """Validate a SolicitationCampaign object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["soliciting_party"], str) and data["soliciting_party"]
    assert isinstance(data["start_at"], str) and data["start_at"]
    assert isinstance(data["end_at"], str) and data["end_at"]


def assert_inspector_certification(data: dict):
    """Validate an InspectorCertification object against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["final_quorum_met"], bool)
    assert isinstance(data["final_quorum_pct_bp"], int)
    assert isinstance(data["outcomes"], dict)
    for proposal_id, outcome in data["outcomes"].items():
        assert outcome in ["PASSED", "FAILED"], f"outcome for {proposal_id} must be PASSED or FAILED"
    assert data["status"] in ["DRAFT", "SIGNED", "SUPERSEDED"]


def assert_quorum_read(data: dict):
    """Validate the computed quorum read shape (PRD §3.7)."""
    assert isinstance(data["meeting_id"], str) and data["meeting_id"]
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["shares_present"], int) and data["shares_present"] >= 0
    assert isinstance(data["outstanding_shares"], int) and data["outstanding_shares"] > 0
    assert isinstance(data["quorum_pct_bp"], int) and data["quorum_pct_bp"] >= 0
    assert isinstance(data["threshold_bp"], int) and data["threshold_bp"] >= 0
    assert isinstance(data["quorum_met"], bool)


def assert_tabulation_read(data: dict):
    """Validate the computed tabulation read shape (PRD §3.4)."""
    assert isinstance(data["proposal_id"], str) and data["proposal_id"]
    assert data["variant"] in ["UNOFFICIAL", "CERTIFIED"]
    for field in ("for_votes", "against_votes", "abstain_votes", "withhold_votes", "votes_cast"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"
    assert data["projected_outcome"] in ["PASS", "FAIL"]
