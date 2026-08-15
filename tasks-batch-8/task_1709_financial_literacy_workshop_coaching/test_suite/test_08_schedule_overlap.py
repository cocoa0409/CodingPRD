"""Temporal overlap rules: the coach's half-open interval rule and the
participant's 30-minute buffered-window rule (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_module,
    create_participant,
    create_certified_coach,
    create_registration,
    create_registration_payload,
    create_workshop,
    create_workshop_payload,
    validate_error,
    validate_success,
)


def test_coach_back_to_back_sessions_allowed_half_open(api, admin_headers):
    """PRD §3.1: "Because the intervals are half-open, back-to-back sessions,
    where one session's `end_at` exactly equals the other's `start_at`, do not
    conflict."

    Design: Difficulty/resource_temporal_overlap/coach_half_open_adjacency_allowed
    """
    module = create_module(admin_headers, module_code="HS-701", title="Housing",
                           session_count=1, incentive_cents_per_hour=500,
                           completion_bonus_cents=0, completion_threshold=1)
    coach = create_certified_coach(admin_headers, full_name="K Fifteen",
                                   email="k15@test.org")
    validate_success(
        api.create_workshop(
            create_workshop_payload(
                module["id"], coach["id"],
                start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:30:00Z",
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    # end_at == start_at adjacency: no conflict under half-open semantics.
    adjacent = validate_success(
        api.create_workshop(
            create_workshop_payload(
                module["id"], coach["id"],
                start_at="2026-08-10T11:30:00Z", end_at="2026-08-10T13:00:00Z",
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_coach_true_overlap_rejected(api, admin_headers):
    """PRD §3.1: "A conflict exists whenever another workshop assigned to the
    same coach is still `SCHEDULED`, is a different workshop, and the two time
    ranges genuinely overlap — the new session's start falls before the other's
    end, and the other's start falls before the new session's end."

    Design: Difficulty/resource_temporal_overlap/coach_half_open_adjacency_allowed
    """
    module = create_module(admin_headers, module_code="HS-701B", title="Housing",
                           session_count=1, incentive_cents_per_hour=500,
                           completion_bonus_cents=0, completion_threshold=1)
    coach = create_certified_coach(admin_headers)
    create_workshop(module["id"], coach["id"], admin_headers,
                    start_at="2026-08-10T10:00:00Z",
                    end_at="2026-08-10T11:30:00Z")
    # 11:00-12:00 genuinely overlaps 10:00-11:30.
    resp = api.create_workshop(
        create_workshop_payload(
            module["id"], coach["id"], location="Rm H",
            start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T12:00:00Z",
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COACH_SCHEDULE_CONFLICT)


def test_participant_gap_under_30_minutes_conflicts(api, admin_headers):
    """PRD §3.2: "The new registration conflicts when its start falls before an
    existing session's buffered end and that session's start falls before the
    new session's buffered end. The comparison is strict: a gap of exactly 30
    minutes does not conflict, while any smaller positive gap does."

    Design: Difficulty/resource_temporal_overlap/participant_buffered_travel_gap
    """
    module = create_module(admin_headers, module_code="RT-801", title="Retirement",
                           session_count=1, incentive_cents_per_hour=500,
                           completion_bonus_cents=0, completion_threshold=1)
    coach1 = create_certified_coach(admin_headers, full_name="K Sixteen",
                                    email="k16@test.org")
    coach2 = create_certified_coach(admin_headers, full_name="K Sixteen B",
                                    email="k16b@test.org")
    participant = create_participant(admin_headers, full_name="P Buf",
                                     email="pbuf@test.org")
    wa = create_workshop(module["id"], coach1["id"], admin_headers,
                         start_at="2026-08-10T10:00:00Z",
                         end_at="2026-08-10T11:00:00Z")
    # 20-minute gap after Wa (11:00 -> 11:20) is smaller than the buffer.
    wb = create_workshop(module["id"], coach2["id"], admin_headers,
                         location="Rm I2",
                         start_at="2026-08-10T11:20:00Z",
                         end_at="2026-08-10T12:30:00Z")
    ra = create_registration(wa["id"], participant["id"], admin_headers)
    assert ra["status"] == "REGISTERED"

    resp = api.create_registration(
        create_registration_payload(wb["id"], participant["id"]), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_SCHEDULE_CONFLICT)


def test_participant_gap_exactly_30_minutes_allowed(api, admin_headers):
    """PRD §3.2: "The comparison is strict: a gap of exactly 30 minutes does
    not conflict, while any smaller positive gap does."

    Design: Difficulty/resource_temporal_overlap/participant_buffered_travel_gap
    """
    module = create_module(admin_headers, module_code="RT-801B", title="Retirement",
                           session_count=1, incentive_cents_per_hour=500,
                           completion_bonus_cents=0, completion_threshold=1)
    coach1 = create_certified_coach(admin_headers)
    coach2 = create_certified_coach(admin_headers)
    participant = create_participant(admin_headers)
    wa = create_workshop(module["id"], coach1["id"], admin_headers,
                         start_at="2026-08-10T10:00:00Z",
                         end_at="2026-08-10T11:00:00Z")
    # Exactly a 30-minute gap after Wa (11:00 -> 11:30), on a different coach
    # so only the participant buffered rule is exercised.
    wc = create_workshop(module["id"], coach2["id"], admin_headers,
                         start_at="2026-08-10T11:30:00Z",
                         end_at="2026-08-10T12:30:00Z")
    create_registration(wa["id"], participant["id"], admin_headers)
    rc = validate_success(
        api.create_registration(
            create_registration_payload(wc["id"], participant["id"]), admin_headers
        ),
        expected_status=201,
    )
    assert rc["status"] == "REGISTERED"
