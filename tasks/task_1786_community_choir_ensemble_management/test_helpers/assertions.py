"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AuditionDecision,
    AuditionStatus,
    BookingStatus,
    CheckoutStatus,
    CommitteeStatus,
    ConcertStatus,
    ContractStatus,
    GrantStatus,
    InvoiceStatus,
    MemberStatus,
    PaymentMethod,
    PaymentStatus,
    PieceStatus,
    PledgeStatus,
    RecognitionTier,
    RegistrationStatus,
    RehearsalStatus,
    ScoreStatus,
    SeasonPosture,
    SectionStatus,
    TourStatus,
    VenueStatus,
    VoicePart,
    AttendanceStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def assert_season(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_dues_cents"], int)
    assert isinstance(data["early_bird_pct"], (int, float))
    assert is_iso8601_timestamp(data.get("early_bird_cutoff", ""))
    assert is_iso8601_timestamp(data.get("dues_due_date", ""))
    assert isinstance(data["late_fee_weekly_cents"], int)
    assert isinstance(data["late_fee_cap_cents"], int)
    assert isinstance(data["scholarship_pool_cents"], int)
    assert isinstance(data["audition_slot_minutes"], int)
    assert isinstance(data["attendance_threshold"], (int, float))
    assert data["posture"] in _enum_values(SeasonPosture)
    assert isinstance(data["ops_week_index"], int)
    assert isinstance(data["pool_available_cents"], int)
    assert isinstance(data["pool_reserved_cents"], int)
    assert isinstance(data["pool_spent_cents"], int)
    assert isinstance(data["treasury_balance_cents"], int)


def assert_section(data: dict):
    _assert_common(data)
    assert data["voice_part"] in _enum_values(VoicePart)
    assert isinstance(data["target_min"], int)
    assert isinstance(data["target_max"], int)
    assert data["status"] in _enum_values(SectionStatus)
    assert isinstance(data["active_count"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data.get("section_id") is None or is_valid_uuid(data["section_id"])
    assert data["status"] in _enum_values(MemberStatus)
    if data.get("enrolled_at") is not None:
        assert is_iso8601_timestamp(data["enrolled_at"])
    assert isinstance(data["attendance_rate"], (int, float))
    assert isinstance(data["performance_eligible"], bool)
    assert isinstance(data["dues_balance_cents"], int)
    assert isinstance(data["ledger_balance_cents"], int)


def assert_audition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data["status"] in _enum_values(AuditionStatus)
    assert data["decision"] in _enum_values(AuditionDecision)
    for field in ("tone_score", "pitch_score", "sight_score"):
        if data.get(field) is not None:
            assert isinstance(data[field], int)
    if data.get("composite_score") is not None:
        assert isinstance(data["composite_score"], (int, float))


def assert_dues_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert isinstance(data["provisional_amount_cents"], int)
    if data.get("final_amount_cents") is not None:
        assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["scholarship_applied_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in _enum_values(InvoiceStatus)


def assert_dues_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in _enum_values(PaymentMethod)
    assert isinstance(data["allocations"], list)
    for alloc in data["allocations"]:
        assert is_valid_uuid(alloc.get("invoice_id", ""))
        assert isinstance(alloc["amount_cents"], int)
    assert data["status"] in _enum_values(PaymentStatus)
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_scholarship_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["requested_cents"], int)
    assert data["status"] in _enum_values(GrantStatus)
    if data.get("approved_cents") is not None:
        assert isinstance(data["approved_cents"], int)
    if data.get("invoice_id") is not None:
        assert is_valid_uuid(data["invoice_id"])


def assert_rehearsal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data["status"] in _enum_values(RehearsalStatus)


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rehearsal_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["status"] in _enum_values(AttendanceStatus)


def assert_music_score(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["copy_count"], int)
    assert isinstance(data["copies_available"], int)
    assert isinstance(data["copies_lost"], int)
    assert isinstance(data["replacement_cost_cents"], int)
    assert data["status"] in _enum_values(ScoreStatus)


def assert_score_checkout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("score_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("checked_out_at", ""))
    assert is_iso8601_timestamp(data.get("due_date", ""))
    if data.get("returned_at") is not None:
        assert is_iso8601_timestamp(data["returned_at"])
    assert data["status"] in _enum_values(CheckoutStatus)
    assert isinstance(data["fine_cents"], int)
    assert isinstance(data["charge_cents"], int)


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int)
    assert data["status"] in _enum_values(VenueStatus)


def assert_concert(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["expected_attendance"], int)
    assert data["status"] in _enum_values(ConcertStatus)
    assert isinstance(data["program_duration_seconds"], int)


def assert_venue_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("concert_id", ""))
    assert is_valid_uuid(data.get("venue_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["deposit_cents"], int)
    assert data["status"] in _enum_values(BookingStatus)


def assert_program_piece(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("concert_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["duration_seconds"], int)
    assert isinstance(data["sequence_no"], int)
    assert data["status"] in _enum_values(PieceStatus)


def assert_guest_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["musician_name"], str) and data["musician_name"]
    assert isinstance(data["service_lines"], list)
    assert isinstance(data["travel_stipend_cents"], int)
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["cancellation_fee_cents"], int)
    assert isinstance(data["counter_count"], int)
    assert data["status"] in _enum_values(ContractStatus)


def assert_tour_trip(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_count"], int)
    assert isinstance(data["min_seats"], int)
    assert isinstance(data["transport_lodging_cost_cents"], int)
    if data.get("provisional_share_cents") is not None:
        assert isinstance(data["provisional_share_cents"], int)
    if data.get("final_share_cents") is not None:
        assert isinstance(data["final_share_cents"], int)
    assert isinstance(data["confirmed_count"], int)
    assert data["status"] in _enum_values(TourStatus)


def assert_tour_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tour_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["status"] in _enum_values(RegistrationStatus)
    assert isinstance(data["deposit_paid_cents"], int)
    if data.get("share_charge_cents") is not None:
        assert isinstance(data["share_charge_cents"], int)
    assert isinstance(data["refund_cents"], int)


def assert_committee(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("chair_member_id", ""))
    assert isinstance(data["fundraising_goal_cents"], int)
    assert isinstance(data["raised_cents"], int)
    assert data["status"] in _enum_values(CommitteeStatus)


def assert_pledge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("committee_id", ""))
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _enum_values(PledgeStatus)
    if data.get("recognition_tier") is not None:
        assert data["recognition_tier"] in _enum_values(RecognitionTier)


def assert_scholarship_pool_invariant(season: dict):
    """PRD §3.4 conservation invariant: pool == available + reserved + spent."""
    total = season["scholarship_pool_cents"]
    available = season["pool_available_cents"]
    reserved = season["pool_reserved_cents"]
    spent = season["pool_spent_cents"]
    assert total == available + reserved + spent, (
        f"Scholarship pool conservation violated: {total} != "
        f"{available} + {reserved} + {spent}"
    )


def assert_copy_conservation(score: dict, open_checkouts: int):
    """PRD §3.5: copy_count == copies_available + open checkouts + copies_lost."""
    assert score["copy_count"] == (
        score["copies_available"] + open_checkouts + score["copies_lost"]
    ), (
        f"Copy conservation violated: {score['copy_count']} != "
        f"{score['copies_available']} + {open_checkouts} + {score['copies_lost']}"
    )
