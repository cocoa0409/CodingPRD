"""Corner-coverage tests for entity creation/constraints/computed fields and state-machine
transition guards.

Design queue B (Corner): sections entities, state_machines.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, make_lash_tech_headers,
    create_studio_payload, create_service_type_payload, create_member_payload,
    create_appointment_payload, create_patch_test_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, credit_ledger,
)


# ─── entities ─────────────────────────────────────────
def test_create_studio_returns_201_with_defaults():
    """PRD §3.1: "`deposit_rate_pct` is the fraction of a service's base price taken as a
    booking deposit and defaults to 0.20 (it must lie between 0 and 1 inclusive);
    `late_cancel_cutoff_hours` is the number of hours before an appointment's start under
    which a cancellation counts as late, defaulting to 24 (it must be at least 0);
    `noshow_strike_window_days` is the length in days of the rolling window over which no-show
    strikes accumulate, defaulting to 90; and `noshow_strike_threshold` is the strike count
    that triggers automatic suspension, defaulting to 3. A studio opens in `status` `OPEN`".

    Design: Corner/entities/create_studio_returns_201_with_defaults
    """
    studio = validate_success(api_client.create_studio(create_studio_payload(name="Glow"), SM),
                              expected_status=201)
    assert studio["deposit_rate_pct"] == 0.20
    assert studio["late_cancel_cutoff_hours"] == 24
    assert studio["noshow_strike_threshold"] == 3
    assert studio["status"] == "OPEN"


def test_get_studio_not_found():
    """PRD §2.8: "a path that names a non-existent resource is rejected with the matching
    not-found error — `ERR_STUDIO_NOT_FOUND` ... before any other check runs."

    Design: Corner/entities/get_studio_not_found
    """
    resp = api_client.get_studio(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_STUDIO_NOT_FOUND)


def test_service_type_missing_required_field_invalid_request():
    """PRD §3.5: "any missing or malformed required field — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/service_type_missing_required_field_invalid_request
    """
    studio = create_studio(name="Glow")
    payload = {"studio_id": studio["id"], "code": "FULL_SET", "name": "Full Set",
               "duration_minutes": 120, "credit_cost": 4, "category": "PREMIUM"}  # no base_price_cents
    resp = api_client.create_service_type(payload, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_service_type_invalid_enum_code_rejected():
    """PRD §3.1: "is described by a `code` — one of `FULL_SET`, `FILL`, `LIFT`, or `TINT`".
    PRD §3.5: "any missing or malformed required field — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/service_type_invalid_enum_code_rejected
    """
    studio = create_studio(name="Glow")
    payload = create_service_type_payload(studio["id"], code="OMBRE", name="Ombre",
                                          duration_minutes=90, base_price_cents=9000,
                                          credit_cost=3, category="PREMIUM")
    resp = api_client.create_service_type(payload, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_appointment_computed_end_utc_and_deposit():
    """PRD §3.5: "the appointment is created `BOOKED`, and `end_utc` is computed as
    `start_utc` plus the service's `duration_minutes`." ... "its `deposit_cents` is the
    service's `base_price_cents` multiplied by the studio's `deposit_rate_pct`, rounded half
    up to the nearest cent, and `credits_charged` is zero."

    Design: Corner/entities/appointment_computed_end_utc_and_deposit
    """
    studio = create_studio(name="Glow", deposit_rate_pct=0.20)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD),
        expected_status=201)
    assert appt["end_utc"][:19] == "2026-06-10T22:00:00", f"end = start+120min, got {appt['end_utc']}"
    assert appt["deposit_cents"] == 2400, f"12000*0.20=2400, got {appt['deposit_cents']}"
    assert appt["credits_charged"] == 0


def test_member_email_unique_within_studio():
    """PRD §3.3: "A `StudioManager` or `FrontDesk` registers a `Member` against a studio with
    a `full_name` and an `email` that must be unique within the studio."

    Design: Corner/entities/member_email_unique_within_studio
    """
    studio = create_studio(name="Glow")
    create_member(studio["id"], full_name="Ada", email="ada@x.com")
    resp = api_client.create_member(create_member_payload(studio["id"], full_name="Ada Two",
                                                          email="ada@x.com"), FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_credit_ledger_entry_immutable_no_version_field():
    """PRD §2.5: "Ledger entries are append-only and immutable once written; a
    `CreditLedgerEntry` therefore carries only `id` and `created_at`, and has neither an
    `updated_at` field nor a `version` field."

    Design: Corner/entities/credit_ledger_entry_immutable_no_version_field
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=4)
    data, meta = validate_paginated(api_client.list_credit_ledger(ms["id"], FD))
    grants = [e for e in data if e["reason"] == "GRANT"]
    assert len(grants) == 1 and grants[0]["delta"] == 4, f"one GRANT delta 4, got {grants}"
    for entry in data:
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry, "ledger entry has no version field"
        assert "updated_at" not in entry, "ledger entry has no updated_at field"


# ─── state_machines ───────────────────────────────────
def _booked_completed_full_set():
    """Cash FULL_SET appointment completed once; clock past its start. Returns (appt, tech)."""
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T12:00:00Z"), FD))
    set_clock("2026-06-10T12:30:00Z")
    get_success_data(api_client.complete_appointment(appt["id"],
                                                     make_lash_tech_headers(appt["lash_tech_id"])))
    return appt, appt["lash_tech_id"]


def test_complete_already_completed_returns_not_booked():
    """PRD §3.8: "Completion is performed by the assigned `LashTech` (or a `StudioManager`)
    and moves the appointment to `COMPLETED`; it is permitted only when the appointment is
    still `BOOKED` and the current clock has reached or passed `start_utc` (otherwise
    `ERR_APPOINTMENT_NOT_STARTED`, HTTP 409)."
    PRD §3.8: "Cancelling or no-showing an appointment that is not `BOOKED` is rejected with
    `ERR_APPOINTMENT_NOT_BOOKED` (HTTP 409)."

    Design: Corner/state_machines/complete_appointment_from_already_completed_returns_not_booked
    """
    appt, tech_id = _booked_completed_full_set()
    resp = api_client.complete_appointment(appt["id"], make_lash_tech_headers(tech_id))
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_BOOKED)


def test_complete_before_start_returns_not_started():
    """PRD §3.8: "it is permitted only when the appointment is still `BOOKED` and the current
    clock has reached or passed `start_utc` (otherwise `ERR_APPOINTMENT_NOT_STARTED`, HTTP
    409)."

    Design: Corner/state_machines/complete_before_start_returns_not_started
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD))
    # clock 10:00 is before start 20:00
    resp = api_client.complete_appointment(appt["id"], make_lash_tech_headers(appt["lash_tech_id"]))
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_STARTED)


def test_settle_dues_from_active_returns_invalid_membership_state():
    """PRD §3.4: "A transition requested from a state that does not permit it is rejected with
    `ERR_INVALID_MEMBERSHIP_STATE` (HTTP 409)."

    Design: Corner/state_machines/settle_dues_from_active_returns_invalid_membership_state
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"])
    resp = api_client.settle_dues(ms["id"], SM)  # membership is ACTIVE, not PAST_DUE
    validate_error(resp, ApiErrorId.ERR_INVALID_MEMBERSHIP_STATE)


def test_reactivate_while_strikes_active_returns_strikes_still_active():
    """PRD §3.4: "reactivating while the count is still at or above the threshold is rejected
    with `ERR_STRIKES_STILL_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/reactivate_while_strikes_active_returns_strikes_still_active
    """
    studio = create_studio(name="Glow", noshow_strike_threshold=3, noshow_strike_window_days=90)
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T00:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"])
    set_clock("2026-06-10T09:00:00Z")
    for s in ["2026-06-10T07:00:00Z", "2026-06-10T07:30:00Z", "2026-06-10T08:00:00Z"]:
        a = get_success_data(api_client.create_appointment(
            create_appointment_payload(member["id"], tint["id"], s), FD))
        get_success_data(api_client.mark_no_show(a["id"], FD))
    assert get_success_data(api_client.get_membership(ms["id"], SM))["status"] == "SUSPENDED"
    # clock NOT advanced — strikes still active
    resp = api_client.reactivate_membership(ms["id"], SM)
    validate_error(resp, ApiErrorId.ERR_STRIKES_STILL_ACTIVE)


def test_revoke_already_revoked_patch_test_returns_not_valid():
    """PRD §3.3: "revoking a record that is not `VALID` is rejected with
    `ERR_PATCH_TEST_NOT_VALID`."

    Design: Corner/state_machines/revoke_patch_test_from_revoked_returns_not_valid
    """
    studio = create_studio(name="Glow")
    member = create_member(studio["id"])
    pt = get_success_data(api_client.create_patch_test(
        create_patch_test_payload(member["id"], "2026-06-01T00:00:00Z", consent_signed=True), FD))
    get_success_data(api_client.revoke_patch_test(pt["id"], SM))
    resp = api_client.revoke_patch_test(pt["id"], SM)
    validate_error(resp, ApiErrorId.ERR_PATCH_TEST_NOT_VALID)


def test_spawn_next_from_paused_returns_invalid_schedule_state():
    """PRD §3.7: "A member or operator may also pause an `ACTIVE` schedule to `PAUSED`, resume
    a `PAUSED` schedule to `ACTIVE`, or end a schedule (from `ACTIVE` or `PAUSED`) to the
    terminal `ENDED` state; a transition from a state that does not permit it is rejected with
    `ERR_INVALID_SCHEDULE_STATE`."

    Design: Corner/state_machines/spawn_next_from_paused_returns_invalid_schedule_state
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    sched = get_success_data(api_client.create_recurring_schedule(
        {"member_id": member["id"], "service_type_id": fill["id"], "cadence_days": 14,
         "first_start_utc": "2026-06-15T10:00:00Z"}, FD))
    get_success_data(api_client.pause_schedule(sched["id"], FD))
    resp = api_client.spawn_next(sched["id"], ms["version"], FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_SCHEDULE_STATE)


def test_appointment_initial_state_is_booked():
    """PRD §3.5: "the appointment is created `BOOKED`".

    Design: Corner/state_machines/appointment_initial_state_is_booked
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD),
        expected_status=201)
    assert appt["status"] == "BOOKED"


def test_patch_test_auto_expires_blocks_booking():
    """PRD §3.3: "A patch test is treated as `EXPIRED` once the current clock is strictly past
    its `valid_through_utc` (evaluated whenever the record is read or used to gate a booking)".
    PRD §3.3: "When no such patch test exists, the booking is rejected with
    `ERR_NO_VALID_PATCH_TEST` (HTTP 422)."

    Design: Corner/state_machines/patch_test_auto_expires_blocks_booking
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=True)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    pt = get_success_data(api_client.create_patch_test(
        create_patch_test_payload(member["id"], "2025-01-01T00:00:00Z", consent_signed=True), FD))
    set_clock("2026-06-10T10:00:00Z")  # past valid_through 2026-01-01
    fetched = get_success_data(api_client.get_patch_test(pt["id"], FD))
    assert fetched["status"] == "EXPIRED", f"patch test EXPIRED at clock past validity, got {fetched['status']}"
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_VALID_PATCH_TEST)
