"""After-hours referral and on-call rota claims: coverage gating, the derived
after_hours flag, closed-interval overlap, the 12-hour rest buffer, overlap
evaluated before rest, and referral terminal lockdown (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_referral,
    book_appointment,
    check_in,
    create_on_call_shift_payload,
    create_referral_payload,
    make_on_call_shift,
    make_provider,
    make_student,
    set_clock,
    setup_open_encounter,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Depth probes: after-hours referral gated by a covering on-call shift
# ---------------------------------------------------------------------------

def test_after_hours_referral_without_coverage_rejected(api, clinician_headers):
    """PRD §3.9: "The health center's business hours are 08:00 through 17:00 UTC
    daily, treated as a half-open window: 08:00:00 is inside business hours,
    17:00:00 is outside them."
    PRD §3.9: "When the current logical time falls outside the business-hours
    window, a covering on-call shift must exist — any provider's shift whose
    `shift_start` is at or before the current moment and whose `shift_end` is
    strictly after it. If no such shift exists, the referral is rejected with
    `ERR_NO_ONCALL_COVERAGE`."
    PRD §3.9: "its derived `after_hours` flag records whether the referral was
    initiated outside business hours."

    Design: Difficulty/cross_entity_state_dependency/after_hours_referral_gated_by_oncall_shift
    """
    set_clock("2026-05-01T20:00:00Z")
    _, provider, _, enc = setup_open_encounter(
        external_ref="S801", visit_type="PRIMARY_URGENT",
        start="2026-05-01T21:00:00Z", end="2026-05-01T21:30:00Z",
        student_name="Night Owl",
    )

    # 20:00 is outside [08:00, 17:00) and no shift covers it.
    res = api.create_referral(
        enc["id"],
        create_referral_payload(hospital_name="General", reason="observation"),
        clinician_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_ONCALL_COVERAGE, expected_status=409)

    # A shift 18:00-24:00 covers 20:00 (start <= now < end); retry succeeds.
    make_on_call_shift(provider["id"], "2026-05-01T18:00:00Z", "2026-05-02T00:00:00Z")
    referral = validate_success(
        api.create_referral(
            enc["id"],
            create_referral_payload(hospital_name="General", reason="observation"),
            clinician_headers,
        ),
        201,
    )
    assert_referral(referral)
    assert referral["status"] == "INITIATED"
    assert referral["after_hours"] is True


def test_business_hours_referral_needs_no_shift(api, clinician_headers,
                                                front_desk_headers):
    """PRD §3.9: "Referrals initiated inside business hours carry no such
    requirement." and "its derived `after_hours` flag records whether the
    referral was initiated outside business hours."

    Design: Difficulty/cross_entity_state_dependency/after_hours_referral_gated_by_oncall_shift
    """
    set_clock("2026-05-01T20:00:00Z")
    student = make_student("S801", "Night Owl")
    make_provider("Dr P")
    provider2 = make_provider("Dr Q")
    # Book the follow-up visit for the next morning.
    appt2 = book_appointment(
        student["id"], provider2["id"], "PRIMARY_URGENT",
        "2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z",
    )
    # Move the clock into business hours; no covering shift exists.
    set_clock("2026-05-02T10:00:00Z")
    enc2 = check_in(appt2["id"])
    referral = validate_success(
        api.create_referral(
            enc2["id"],
            create_referral_payload(hospital_name="General", reason="follow-up"),
            clinician_headers,
        ),
        201,
    )
    assert referral["status"] == "INITIATED"
    assert referral["after_hours"] is False, "10:00 is inside [08:00, 17:00)"


# ---------------------------------------------------------------------------
# Depth probes: closed-interval overlap and the 12-hour rest buffer
# ---------------------------------------------------------------------------

def _setup_provider_with_shift():
    set_clock("2026-05-01T00:00:00Z")
    provider = make_provider("Dr S")
    shift = make_on_call_shift(
        provider["id"], "2026-06-05T18:00:00Z", "2026-06-06T00:00:00Z"
    )
    return provider, shift


def test_oncall_overlap_uses_closed_intervals(api, health_admin_headers):
    """PRD §3.9: "on-call overlap uses **closed-interval** semantics, so two
    shifts that merely touch — one ending exactly when the other begins — count
    as overlapping and are rejected with `ERR_ONCALL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/oncall_closed_interval_and_rest_buffer
    """
    provider, _ = _setup_provider_with_shift()

    # Interior overlap: 23:00 < existing end 24:00.
    res1 = api.create_on_call_shift(
        create_on_call_shift_payload(
            provider["id"], "2026-06-05T23:00:00Z", "2026-06-06T05:00:00Z"
        ),
        health_admin_headers,
    )
    validate_error(res1, ApiErrorId.ERR_ONCALL_OVERLAP, expected_status=409)

    # Touching endpoints: new shift starts exactly when the existing one ends;
    # closed intervals still conflict (unlike half-open appointment slots).
    res2 = api.create_on_call_shift(
        create_on_call_shift_payload(
            provider["id"], "2026-06-06T00:00:00Z", "2026-06-06T06:00:00Z"
        ),
        health_admin_headers,
    )
    validate_error(res2, ApiErrorId.ERR_ONCALL_OVERLAP, expected_status=409)


def test_oncall_rest_buffer_boundary(api, health_admin_headers):
    """PRD §3.9: "any two shifts of the same provider must be separated by at
    least twelve hours of rest; a gap shorter than twelve hours is rejected with
    `ERR_ONCALL_REST_VIOLATION`, while a gap of exactly twelve hours is
    permitted."

    Design: Difficulty/resource_temporal_overlap/oncall_closed_interval_and_rest_buffer
    """
    provider, _ = _setup_provider_with_shift()

    # Gap of 6 hours from the existing shift's 2026-06-06T00:00 end.
    res1 = api.create_on_call_shift(
        create_on_call_shift_payload(
            provider["id"], "2026-06-06T06:00:00Z", "2026-06-06T12:00:00Z"
        ),
        health_admin_headers,
    )
    validate_error(res1, ApiErrorId.ERR_ONCALL_REST_VIOLATION, expected_status=409)

    # Gap of exactly 12 hours is permitted (inclusive boundary).
    ok = validate_success(
        api.create_on_call_shift(
            create_on_call_shift_payload(
                provider["id"], "2026-06-06T12:00:00Z", "2026-06-06T18:00:00Z"
            ),
            health_admin_headers,
        ),
        201,
    )
    assert ok["provider_id"] == provider["id"]


# ---------------------------------------------------------------------------
# Corner: ACCEPTED is terminal
# ---------------------------------------------------------------------------

def test_referral_accept_twice_rejected(api, clinician_headers):
    """PRD §3.9: "Once initiated, a referral moves from `INITIATED` to
    `ACCEPTED` — its terminal state — when a `Clinician` marks the receiving
    hospital's acceptance; accepting anything not `INITIATED` is rejected with
    `ERR_REFERRAL_NOT_INITIATED`."

    Design: Corner/state_machines/referral_accept_twice_rejected
    """
    set_clock("2026-05-01T10:00:00Z")
    _, _, _, enc = setup_open_encounter(
        external_ref="S28", visit_type="PRIMARY_URGENT",
        start="2026-05-01T11:00:00Z", end="2026-05-01T11:30:00Z",
        student_name="Ref Test",
    )
    referral = validate_success(
        api.create_referral(
            enc["id"],
            create_referral_payload(hospital_name="General", reason="imaging"),
            clinician_headers,
        ),
        201,
    )
    assert referral["after_hours"] is False, "10:00 is inside business hours"

    accepted = validate_success(
        api.accept_referral(referral["id"], clinician_headers), 200
    )
    assert accepted["status"] == "ACCEPTED"

    res = api.accept_referral(referral["id"], clinician_headers)
    validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_INITIATED, expected_status=409)
