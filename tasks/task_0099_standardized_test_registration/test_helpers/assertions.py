"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_test_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["room_capacity_standard"], int)
    assert isinstance(data["room_capacity_accommodated"], int)
    assert isinstance(data["net_revenue_cents"], int)


def assert_test_session(data: dict):
    _assert_common(data)
    assert isinstance(data["test_center_id"], str)
    assert data["exam_type"] in ("SAT", "ACT", "AP")
    assert isinstance(data["exam_subject"], str)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["standard_seats_reserved"], int) and data["standard_seats_reserved"] >= 0
    assert isinstance(data["accommodated_seats_reserved"], int) and data["accommodated_seats_reserved"] >= 0
    assert data["registration_status"] in ("OPEN", "CLOSED")


def assert_candidate(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_first_name"], str)
    assert isinstance(data["legal_last_name"], str)
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["id_document_state_code"], str)
    assert isinstance(data["has_active_504_iep"], bool)


def assert_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["test_session_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert data["seat_kind"] in ("STANDARD", "ACCOMMODATED")
    assert isinstance(data["allotted_minutes"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_refunded_cents"], int)
    assert data["lifecycle_status"] in ("RESERVED", "CONFIRMED", "CHECKED_IN", "CANCELLED", "NO_SHOW")
    assert data["score_status"] in ("PENDING", "SCORED", "RELEASED", "CANCELLED_SCORE")
    assert isinstance(data["is_standby_origin"], bool)


def assert_accommodation_request(data: dict):
    _assert_common(data)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["target_registration_id"], str)
    assert data["accommodation_type"] in (
        "EXTENDED_TIME_50", "EXTENDED_TIME_100", "SEPARATE_ROOM", "BREAKS_ONLY"
    )
    assert data["basis"] in ("PLAN_504", "IEP")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "MORE_INFO_NEEDED", "APPROVED", "DENIED"
    )


def assert_standby_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["test_session_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert data["priority_tier"] in ("FEE_WAIVER", "SCHOOL_DAY", "GENERAL")
    assert isinstance(data["promotion_score"], (int, float))
    assert data["status"] in ("WAITING", "OFFERED", "CLAIMED", "DECLINED", "EXPIRED")


def assert_score_report(data: dict):
    _assert_common(data)
    assert isinstance(data["registration_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert data["exam_type"] in ("SAT", "ACT")
    assert isinstance(data["section_scores"], dict)
    assert isinstance(data["sitting_composite"], int)
    assert isinstance(data["super_composite"], int)


def assert_score_send(data: dict):
    _assert_common(data)
    assert isinstance(data["registration_id"], str)
    assert isinstance(data["recipient_code"], str)
    assert isinstance(data["sent_composite"], int)
    assert data["status"] in ("QUEUED", "SENT")


def assert_clep_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["clep_subject"], str)
    assert isinstance(data["clep_scaled_score"], int)
    assert isinstance(data["recommended_credit_hours"], int)
    assert data["status"] in ("PENDING", "RECOGNIZED", "REJECTED")


def assert_id_verification(data: dict):
    _assert_common(data)
    assert isinstance(data["registration_id"], str)
    assert isinstance(data["cross_state"], bool)
    assert data["outcome"] in ("MATCH", "MISMATCH")


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_seat_counters_nonnegative(session: dict):
    """Seat pools never go negative (PRD §2.7 conservation)."""
    assert session["standard_seats_reserved"] >= 0, "standard pool went negative"
    assert session["accommodated_seats_reserved"] >= 0, "accommodated pool went negative"


def assert_net_revenue_consistent(center: dict, expected_net_cents: int):
    """net_revenue_cents == sum(fees captured) - sum(refunds) (PRD §2.8)."""
    assert center["net_revenue_cents"] == expected_net_cents, (
        f"net_revenue_cents expected {expected_net_cents}, got {center['net_revenue_cents']}"
    )
