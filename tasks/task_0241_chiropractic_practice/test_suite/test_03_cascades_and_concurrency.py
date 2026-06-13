"""Transitive cascades (dismissal, plan discontinue), the cap-conservation
invariant, series generation, cap reservation, OCC on plan activation, and
immediate visibility.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_provider_headers,
    create_appointment_payload,
    setup_base_practice,
    create_cash_patient,
    create_insurance_patient,
    add_policy,
    accrue_strikes,
    book_appointment,
    create_series,
    setup_active_plan,
    setup_two_proposed_plans,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty: transitive_cascade / no_show_dismissal_cascade_releases_caps_depth3
# ===========================================================================
def test_fifth_no_show_dismisses_and_cancels_remaining_bookings(api):
    """PRD §3.7: "Dismissal cascades — every remaining `BOOKED` or `CHECKED_IN`
    appointment for the patient is cancel-released, freeing its cap slots, and any
    `ACTIVE` treatment plan is discontinued."
    PRD §3.7: "when that count reaches the dismissal threshold of five, the
    patient is dismissed: `is_dismissed` becomes true and `status` moves to the
    terminal `DISMISSED`."

    Design: Difficulty/transitive_cascade/no_show_dismissal_cascade_releases_caps_depth3
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Strike Sam")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]
    policy = add_policy(pid, annual_visit_cap=20)

    accrue_strikes(pid, prov_id, room_id, 4, start_hour=9, insurance_policy_id=policy["id"])  # 4 prior strikes, clock reset

    # Two future BOOKED insurance appointments reserve two cap slots.
    future1 = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-10T17:00:00Z", insurance_policy_id=policy["id"])
    future2 = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-11T17:00:00Z", insurance_policy_id=policy["id"])

    # The strike-5 appointment, now elapsed.
    ns5 = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-02T13:00:00Z", insurance_policy_id=policy["id"])
    validate_success(api.set_clock("2026-03-02T13:30:00Z", ADMIN), 200)
    validate_success(api.no_show_appointment(pid, ns5["id"], FRONTDESK), 200)

    refreshed = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert refreshed["no_show_strike_count"] == 5
    assert refreshed["status"] == "DISMISSED"

    a1 = validate_success(api.get_appointment(pid, future1["id"], FRONTDESK), 200)
    a2 = validate_success(api.get_appointment(pid, future2["id"], FRONTDESK), 200)
    assert a1["attendance_status"] == "CANCELLED"
    assert a2["attendance_status"] == "CANCELLED"

    policy_after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert policy_after["visits_reserved"] == 0


def test_dismissal_cap_slots_released_to_zero(api):
    """PRD §2.5: "When a patient accrues enough strikes to be dismissed, every
    `BOOKED` or `CHECKED_IN` appointment for that patient is cancel-released and
    any `ACTIVE` plan is discontinued."

    The two reserved cap slots are freed when dismissal cancel-releases them.

    Design: Difficulty/transitive_cascade/no_show_dismissal_cascade_releases_caps_depth3
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Strike Steph")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]
    policy = add_policy(pid, annual_visit_cap=20)

    accrue_strikes(pid, prov_id, room_id, 4, start_hour=9, insurance_policy_id=policy["id"])
    book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-10T17:00:00Z", insurance_policy_id=policy["id"])
    book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-11T17:00:00Z", insurance_policy_id=policy["id"])

    before = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert before["visits_reserved"] == 2

    ns5 = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-02T13:00:00Z", insurance_policy_id=policy["id"])
    validate_success(api.set_clock("2026-03-02T13:30:00Z", ADMIN), 200)
    validate_success(api.no_show_appointment(pid, ns5["id"], FRONTDESK), 200)

    after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert after["visits_reserved"] == 0


# ===========================================================================
# Difficulty: transitive_cascade / plan_discontinue_cascade_cancels_series_depth2
# ===========================================================================
def test_discontinue_cascades_to_series_and_appointments(api):
    """PRD §3.3: "this cascades to cancel every non-terminal phase and every
    `SCHEDULED` series under the plan, releasing the cap slots of the appointments
    those series generated as described in Section 2.5."
    PRD §2.5: "every `SCHEDULED` series is cancelled, which in turn cancel-releases
    each still-`BOOKED` appointment the series generated".

    Design: Difficulty/transitive_cascade/plan_discontinue_cascade_cancels_series_depth2
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 3}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    series = create_series(
        pid, ctx["plan"]["id"], ctx["phases"][0]["id"], prov_id, ctx["room"]["id"],
        start_date="2026-03-09", weekday_pattern=[0, 2, 4], start_time_minutes=540, duration_minutes=15,
    )
    res = validate_success(api.discontinue_plan(pid, ctx["plan"]["id"], make_provider_headers(prov_id)), 200)
    assert res["status"] == "DISCONTINUED"

    series_after = validate_success(api.get_series_by_id(series["id"], FRONTDESK), 200)
    assert series_after["status"] == "CANCELLED"

    appts, _ = validate_paginated(
        api.list_patient_appointments(pid, FRONTDESK, params={"appointment_series_id": series["id"]})
    )
    assert len(appts) == 3
    assert all(a["attendance_status"] == "CANCELLED" for a in appts)


def test_discontinue_cancels_non_terminal_phase(api):
    """PRD §3.3: "this cascades to cancel every non-terminal phase and every
    `SCHEDULED` series under the plan".

    Design: Difficulty/transitive_cascade/plan_discontinue_cascade_cancels_series_depth2
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 3}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    create_series(
        pid, ctx["plan"]["id"], ctx["phases"][0]["id"], prov_id, ctx["room"]["id"],
        start_date="2026-03-09", weekday_pattern=[0, 2, 4], start_time_minutes=540, duration_minutes=15,
    )
    validate_success(api.discontinue_plan(pid, ctx["plan"]["id"], make_provider_headers(prov_id)), 200)
    phase = validate_success(api.get_phase_by_id(ctx["phases"][0]["id"], make_provider_headers(prov_id)), 200)
    assert phase["status"] == "CANCELLED"


# ===========================================================================
# Difficulty: compensating_invariant / cap_slot_conserved_book_then_cancel
# ===========================================================================
def test_clean_cancel_releases_reserved_cap_slot(api):
    """PRD §3.7: "A clean cancellation — moving a `BOOKED` appointment to
    `CANCELLED` — is permitted only when the current time is strictly earlier than
    the appointment's `scheduled_start` minus the late-cancel window of 24 hours;
    it releases any reserved cap slot (decrementing `visits_reserved` by one) and
    assesses no fee, leaving `no_show_fee_cents` at 0."

    Booking reserves one slot and the clean cancel releases it, so cap occupancy
    returns to 0.

    Design: Difficulty/compensating_invariant/cap_slot_conserved_book_then_cancel
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Conserve Cara")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=5)
    appt = book_appointment(
        pid, base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-20T17:00:00Z", insurance_policy_id=policy["id"],
    )
    reserved = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert reserved["visits_reserved"] == 1

    res = validate_success(api.cancel_appointment(pid, appt["id"], FRONTDESK), 200)
    assert res["attendance_status"] == "CANCELLED"
    after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert after["visits_reserved"] == 0
    assert after["visits_committed"] == 0


def test_clean_cancel_assesses_no_fee(api):
    """PRD §3.7: "it releases any reserved cap slot (decrementing `visits_reserved`
    by one) and assesses no fee, leaving `no_show_fee_cents` at 0."

    Design: Difficulty/compensating_invariant/cap_slot_conserved_book_then_cancel
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Conserve Colin")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=5)
    appt = book_appointment(
        pid, base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-20T17:00:00Z", insurance_policy_id=policy["id"],
    )
    res = validate_success(api.cancel_appointment(pid, appt["id"], FRONTDESK), 200)
    assert res["no_show_fee_cents"] == 0
    refreshed = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert refreshed["no_show_strike_count"] == 0


# ===========================================================================
# Corner: cross_cutting / occ_activate_plan_with_current_version_succeeds_then_stale_rejected
# ===========================================================================
def test_activate_with_fresh_version_then_stale_rejected(api):
    """PRD §2.7: "If another writer has activated a plan in the meantime — bumping
    the patient's `version` since the client read it — the supplied
    `expected_patient_version` will no longer match the current value, and the
    activation is rejected as stale with `ERR_STALE_PATIENT_VERSION` (HTTP 412)."
    PRD §3.3: "On success the plan transitions `PROPOSED → ACTIVE`; the phase with
    the lowest `sequence_index` transitions `PENDING → IN_PROGRESS` and the plan's
    `current_phase` is set to that phase's `phase_type`; and the patient's
    `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_activate_plan_with_current_version_succeeds_then_stale_rejected
    """
    ctx = setup_two_proposed_plans()
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    stale_version = ctx["version"]

    first = validate_success(
        api.activate_plan(pid, ctx["p1"]["id"], {"expected_patient_version": stale_version}, make_provider_headers(prov_id)),
        200,
    )
    assert first["status"] == "ACTIVE"
    bumped = validate_success(api.get_patient(pid, make_provider_headers(prov_id)), 200)
    assert bumped["version"] == stale_version + 1

    res = api.activate_plan(pid, ctx["p2"]["id"], {"expected_patient_version": stale_version}, make_provider_headers(prov_id))
    validate_error(res, "ERR_STALE_PATIENT_VERSION")


# ===========================================================================
# Corner: consistency_model / immediate_visibility_cap_reserved_in_same_response
# ===========================================================================
def test_cap_reservation_visible_immediately(api):
    """PRD §3.6: "On a successful cap-counting booking the policy's
    `visits_reserved` is incremented by one and the appointment's
    `counts_against_cap` is set true".

    The booking response carries counts_against_cap=true and an immediately
    following policy read shows visits_reserved=1.

    Design: Corner/consistency_model/immediate_visibility_cap_reserved_in_same_response
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Imm Ima")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=5)
    appt = book_appointment(
        pid, base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-10T17:00:00Z", insurance_policy_id=policy["id"],
    )
    assert appt["counts_against_cap"] is True
    policies, _ = validate_paginated(
        api.list_patient_policies(pid, BILLING, params={"status": "ACTIVE"})
    )
    target = next(p for p in policies if p["id"] == policy["id"])
    assert target["visits_reserved"] == 1


# ===========================================================================
# Corner: calculations / series_generates_exact_planned_count
# ===========================================================================
def test_series_generates_exact_planned_count(api):
    """PRD §3.5: "Generation produces exactly `planned_visit_count` appointments
    for the named phase."
    PRD §3.5: "on a successful materialization `generated_count` equals the
    phase's `planned_visit_count`".

    Design: Corner/calculations/series_generates_exact_planned_count
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 3}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    series = create_series(
        pid, ctx["plan"]["id"], ctx["phases"][0]["id"], prov_id, ctx["room"]["id"],
        start_date="2026-03-09", weekday_pattern=[0, 2, 4], start_time_minutes=540, duration_minutes=15,
    )
    assert series["generated_count"] == 3
    appts, _ = validate_paginated(
        api.list_patient_appointments(pid, FRONTDESK, params={"appointment_series_id": series["id"]})
    )
    assert len(appts) == 3
    assert all(a["attendance_status"] == "BOOKED" for a in appts)


# ===========================================================================
# Corner: calculations / cap_counting_excludes_exam_and_xray
# ===========================================================================
def test_exam_visit_does_not_reserve_cap(api):
    """PRD §3.6: "Only the visit types `ADJUSTMENT`, `THERAPY`, and `RE_EXAM`
    count against the cap; `EXAM` and `X_RAY` visits never consume a cap slot."
    PRD §3.6: "for non-cap-counting visits and for cash or wellness patients no
    slot is reserved and `counts_against_cap` stays false."

    Design: Corner/calculations/cap_counting_excludes_exam_and_xray
    """
    base = setup_base_practice(visit_type="EXAM", cash_rate_cents=12000)
    patient = create_insurance_patient("Exam Ed")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=1)
    appt = book_appointment(
        pid, base["provider"]["id"], base["room"]["id"],
        visit_type="EXAM", scheduled_start="2026-03-03T17:00:00Z", duration_minutes=30,
        insurance_policy_id=policy["id"],
    )
    assert appt["counts_against_cap"] is False
    policy_after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert policy_after["visits_reserved"] == 0
