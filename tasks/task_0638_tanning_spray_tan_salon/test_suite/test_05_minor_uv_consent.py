"""Minor UV gates: guardian consent requirement and the regulatory weekly cap.

Covers queue-B validation corner instances that depend on the is_minor computed
classification and the ConsentRecord entity.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    create_session_payload,
)
from test_helpers import fixtures as fx

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_system_headers"]
SALON_MANAGER = TEST_USERS["salon_manager_headers"]


def test_minor_uv_without_consent_rejected(api):
    """PRD §3.5: "a minor member must have a valid, unexpired guardian consent on
    file to reserve a UV session: there must exist a `ConsentRecord` for the member
    whose `expires_at` is strictly after the current logical instant. ... If no such
    unexpired consent exists for a minor's UV booking, the booking is rejected with
    `ERR_MINOR_CONSENT_REQUIRED`."

    Design: Corner/validations/minor_uv_without_consent_rejected
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Minor bed", max_exposure_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    # DOB 2015-01-01 -> ~11 years old at clock 2026 -> is_minor true.
    member = fx.create_active_member(plan["id"], full_name="Minor NoConsent",
                                     date_of_birth="2015-01-01T00:00:00Z", skin_type="IV")
    mid = member["id"]
    after = validate_success(api.get_member(mid, FRONT_DESK))
    assert after["is_minor"] is True, "DOB 2015 must classify as minor at 2026 clock"
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MINOR_CONSENT_REQUIRED.value, expected_status=403)


def test_minor_weekly_frequency_exceeded(api):
    """PRD §3.5: "a minor may take at most one UV session per ISO week; this minor
    cap is regulatory and overrides whatever the plan's `weekly_uv_session_cap`
    would permit. If a minor already has at least one UV session counted for the
    target ISO week, a further UV booking is rejected with
    `ERR_MINOR_FREQUENCY_EXCEEDED`."

    Design: Corner/validations/minor_weekly_frequency_exceeded
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    eq1 = fx.create_equipment(name="MinorFreq A", max_exposure_seconds=600)
    eq2 = fx.create_equipment(name="MinorFreq B", max_exposure_seconds=600)
    fx.set_clock("2026-06-08T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Minor Freq",
                                     date_of_birth="2012-01-01T00:00:00Z", skin_type="IV")
    mid = member["id"]
    fx.add_consent(mid, guardian_name="Parent G", expires_at="2027-01-01T00:00:00Z")
    # First UV session this ISO week (started -> IN_PROGRESS counts).
    fx.start_uv_session(mid, eq1["id"], "2026-06-08T10:00:00Z", 120)
    fx.set_clock("2026-06-09T11:00:00Z")  # >24h later, cooldown satisfied
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="RESERVATION",
        equipment_id=eq2["id"], start_at="2026-06-09T11:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, make_member_headers(mid))
    validate_error(resp, ApiErrorId.ERR_MINOR_FREQUENCY_EXCEEDED.value, expected_status=403)
