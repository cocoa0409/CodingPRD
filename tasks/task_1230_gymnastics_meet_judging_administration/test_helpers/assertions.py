"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MEET_POSTURES = ["DRAFT", "SCHEDULED", "WARMUP_OPEN", "IN_COMPETITION",
                 "SCORING_CLOSED", "FINALIZED", "ARCHIVED"]
SESSION_STATES = ["SCHEDULED", "WARMUP_OPEN", "MARCH_IN", "IN_ROTATION", "SCORING", "CLOSED"]
ENTRY_STATUSES = ["REGISTERED", "CHECKED_IN", "SCRATCHED", "COMPETING", "COMPLETED"]
CREDENTIAL_STATES = ["PENDING_VERIFICATION", "CREDENTIALED", "SUSPENDED", "REVOKED"]
PASS_STATES = ["ISSUED", "FLOOR_ACCESS_GRANTED", "FLOOR_ACCESS_SUSPENDED", "REVOKED"]
PANEL_STATES = ["FORMING", "FULL", "ACTIVE", "RELEASED"]
ASSIGNMENT_STATES = ["PROPOSED", "CONFIRMED", "RECUSED", "RELEASED"]
ROTATION_STATES = ["PENDING", "WARMUP", "TIMED_WARMUP_HELD", "OPEN_FOR_SCORING",
                   "SCORING_CLOSED", "FINALIZED"]
WARMUP_BLOCK_STATES = ["SCHEDULED", "IN_PROGRESS", "COMPLETE", "SKIPPED"]
SCORE_STATES = ["DRAFT", "PUBLISHED", "UNDER_INQUIRY", "INQUIRY_RESOLVED", "FINAL", "VOID"]
INQUIRY_STATES = ["FILED", "UNDER_REVIEW", "UPHELD", "DENIED", "WITHDRAWN", "EXPIRED"]
TICKET_STATES = ["ISSUED", "SCANNED", "REDEEMED", "REFUNDED", "VOID"]
QUALIFICATION_STATES = ["PROVISIONAL", "CONFIRMED", "DECLINED", "REVOKED"]
APPARATUS = ["VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_score_precision(value, field="score"):
    """Score quantities are carried at exactly three decimal places."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    scaled = round(float(value) * 1000)
    assert abs(float(value) * 1000 - scaled) < 1e-4, \
        f"{field} must have at most 3 decimal places, got {value!r}"


def assert_meet(data: dict):
    _assert_common(data)
    assert isinstance(data["meet_name"], str) and data["meet_name"]
    assert isinstance(data["sanction_year"], int)
    assert isinstance(data["sanction_number"], str)
    assert data["posture"] in MEET_POSTURES
    assert data["tiebreak_policy"] in ["USAG_CLASSIC", "NCAA_MODIFIED"]
    assert data["qualifying_score_rule"] in ["ALL_AROUND_ONLY", "PER_EVENT", "BOTH"]


def assert_session(data: dict):
    _assert_common(data)
    assert data["state"] in SESSION_STATES
    assert data["level_band"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data.get("apparatus_set"), list)


def assert_squad(data: dict):
    _assert_common(data)
    assert data["starting_apparatus"] in APPARATUS
    assert isinstance(data["athlete_count"], int) and data["athlete_count"] >= 0
    assert isinstance(data["rotation_index"], int)


def assert_gymnast(data: dict):
    _assert_common(data)
    assert isinstance(data["usag_member_number"], str)
    assert data["competitive_level"]


def assert_athlete_entry(data: dict):
    _assert_common(data)
    assert data["entry_status"] in ENTRY_STATUSES


def assert_coach(data: dict):
    _assert_common(data)
    assert data["credential_state"] in CREDENTIAL_STATES


def assert_coach_meet_pass(data: dict):
    _assert_common(data)
    assert data["pass_state"] in PASS_STATES


def assert_judge(data: dict):
    _assert_common(data)
    assert data["rating"] in ["BREVET", "NATIONAL", "USA", "LEVEL_10", "LEVEL_9",
                              "LEVEL_8", "LEVEL_7", "LEVEL_4_5", "XCEL"]


def assert_judge_panel(data: dict):
    _assert_common(data)
    assert data["apparatus"] in APPARATUS
    assert data["panel_state"] in PANEL_STATES
    assert isinstance(data["required_judge_count"], int)


def assert_panel_assignment(data: dict):
    _assert_common(data)
    assert data["role"] in ["PANEL_CHIEF", "D_JUDGE", "E_JUDGE", "LINE_JUDGE", "TIMER"]
    assert data["assignment_state"] in ASSIGNMENT_STATES
    assert isinstance(data["conflict_flag"], bool)


def assert_rotation(data: dict):
    _assert_common(data)
    assert data["apparatus"] in APPARATUS
    assert data["state"] in ROTATION_STATES
    assert isinstance(data["rotation_number"], int)


def assert_warmup_block(data: dict):
    _assert_common(data)
    assert data["state"] in WARMUP_BLOCK_STATES
    assert is_iso8601_timestamp(data.get("block_start", ""))
    assert is_iso8601_timestamp(data.get("block_end", ""))


def assert_score(data: dict):
    _assert_common(data)
    assert data["apparatus"] in APPARATUS
    assert data["score_state"] in SCORE_STATES
    for field in ("difficulty_score", "execution_score", "neutral_deduction"):
        assert_score_precision(data[field], field)


def assert_inquiry(data: dict):
    _assert_common(data)
    assert data["inquiry_state"] in INQUIRY_STATES


def assert_award(data: dict):
    _assert_common(data)
    assert data["category"] in APPARATUS + ["ALL_AROUND"]
    assert isinstance(data["place"], int) and data["place"] >= 1


def assert_spectator_ticket(data: dict):
    _assert_common(data)
    assert data["ticket_state"] in TICKET_STATES
    assert data["ticket_class"] in ["GENERAL_ADMISSION", "RESERVED", "VIP", "COMP"]
    assert isinstance(data["price_cents"], int)


def assert_qualification_record(data: dict):
    _assert_common(data)
    assert data["qualification_state"] in QUALIFICATION_STATES
    assert data["target_meet_level"] in ["STATE", "REGIONAL", "NATIONAL"]
