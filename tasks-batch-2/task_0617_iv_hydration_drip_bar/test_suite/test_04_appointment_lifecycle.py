"""Appointment branching lifecycle (clearance fork, MD review/approve/decline),
the cyclic Membership machine, and the OCC success path.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success,
    set_clock, create_menu_item, create_lounge, create_patient, create_membership,
    create_supply_lot, create_requested_appointment, submit_intake, sign_consent,
    current_version, schedule_appointment, setup_screen_pending_appointment,
    setup_cleared_lounge_ready_to_schedule,
    TEST_USERS, make_medical_director_headers,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]
FAR_EXPIRY = "2026-12-31T00:00:00Z"


# ─── Difficulty: non_linear_state_machine / nl_appointment_fork_review_then_approve ───
def test_schedule_forks_review_appointment_to_requires_md_review(api):
    """PRD §3.7: "If the latest screening's `outcome` is `REQUIRES_MD_REVIEW`, scheduling
    does not complete the booking; instead it forks the appointment from `SCREEN_PENDING`
    to `REQUIRES_MD_REVIEW` and increments its `version` by one, deferring the booking to
    a medical director."

    A patient born 1950 with pregnancy scores 40+10(age)=50 -> REQUIRES_MD_REVIEW.

    Design: Difficulty/non_linear_state_machine/nl_appointment_fork_review_then_approve
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=3)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient(date_of_birth="1950-01-01T00:00:00Z")
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"], author_user_id="intake-1", pregnancy=True)
    sign_consent(appt["id"], witness_user_id="wit-1")
    forked = schedule_appointment(appt["id"])
    assert forked["status"] == "REQUIRES_MD_REVIEW", \
        f"expected fork to REQUIRES_MD_REVIEW, got {forked['status']}"


def test_md_approve_drives_review_appointment_to_scheduled(api):
    """PRD §3.9: "Approval drives the appointment from `REQUIRES_MD_REVIEW` to
    `SCHEDULED` ... On success it pins the standing order, reserves supply via FEFO,
    computes `amount_charged_cents`, decrements membership credits, sets `status` to
    `SCHEDULED`, and increments `version` by one."

    A reviewer (md-2) distinct from the screening author (intake-1) approves; the cash
    MYERS visit charges 17500.

    Design: Difficulty/non_linear_state_machine/nl_appointment_fork_review_then_approve
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=3)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient(date_of_birth="1950-01-01T00:00:00Z")
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"], author_user_id="intake-1", pregnancy=True)
    sign_consent(appt["id"], witness_user_id="wit-1")
    schedule_appointment(appt["id"])  # -> REQUIRES_MD_REVIEW
    v = current_version(appt["id"])
    approved = get_success_data(api_client.md_approve_appointment(
        appt["id"], {"expected_appointment_version": v},
        make_medical_director_headers("md-2")))
    assert approved["status"] == "SCHEDULED"
    assert approved["amount_charged_cents"] == 17500, \
        f"expected 17500, got {approved['amount_charged_cents']}"


# ─── Difficulty: non_linear_state_machine / nl_membership_suspend_reinstate_cycle ───
def test_membership_suspend_transition(api):
    """PRD §3.2: "A `ClinicAdmin` may move a membership from `ACTIVE` to `SUSPENDED`; this
    sets `status` to `SUSPENDED` and increments the membership's `version` by one."

    Design: Difficulty/non_linear_state_machine/nl_membership_suspend_reinstate_cycle
    """
    set_clock("2026-06-22T00:00:00Z")
    mem = create_membership(tier="GOLD", covered_drip_tier="MYERS",
                            drip_credits_total=2, addon_credits_total=2)
    assert mem["version"] == 1
    suspended = get_success_data(api_client.suspend_membership(mem["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2


def test_membership_reinstate_completes_cycle_back_to_active(api):
    """PRD §3.2: "The reverse transition takes a `SUSPENDED` membership back to `ACTIVE`,
    setting `status` to `ACTIVE` and incrementing `version` by one."

    Create (v1) -> suspend (v2) -> reinstate (v3) returns to ACTIVE with version 3.

    Design: Difficulty/non_linear_state_machine/nl_membership_suspend_reinstate_cycle
    """
    set_clock("2026-06-22T00:00:00Z")
    mem = create_membership(tier="GOLD", covered_drip_tier="MYERS",
                            drip_credits_total=2, addon_credits_total=2)
    get_success_data(api_client.suspend_membership(mem["id"], ADMIN))
    reinstated = get_success_data(api_client.reinstate_membership(mem["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == 3, f"expected version 3, got {reinstated['version']}"


# ─── Corner: state_machines / md_decline_moves_to_declined ───
def test_md_decline_moves_review_appointment_to_declined(api):
    """PRD §3.9: "Alternatively the director may decline — again the caller's `X-User-ID`
    must differ from the screening `author_user_id` — moving the appointment from
    `REQUIRES_MD_REVIEW` to the terminal `DECLINED` state and incrementing `version` by
    one."

    Design: Corner/state_machines/md_decline_moves_to_declined
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    patient = create_patient(date_of_birth="1950-01-01T00:00:00Z")
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"], author_user_id="intake-1", pregnancy=True)
    sign_consent(appt["id"], witness_user_id="wit-1")
    schedule_appointment(appt["id"])  # -> REQUIRES_MD_REVIEW
    declined = get_success_data(api_client.md_decline_appointment(
        appt["id"], make_medical_director_headers("md-2")))
    assert declined["status"] == "DECLINED"


# ─── Corner: cross_cutting / occ_schedule_correct_version_succeeds ───
def test_schedule_with_current_version_succeeds_and_increments(api):
    """PRD §2.5: "Scheduling an appointment requires an `expected_appointment_version`
    field whose value must equal that appointment's current `version`."
    PRD §3.7: "sets `status` to `SCHEDULED`, and increments `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_correct_version_succeeds
    """
    ctx = setup_cleared_lounge_ready_to_schedule(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False})
    v = ctx["version"]
    scheduled = schedule_appointment(ctx["appointment"]["id"], v)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["version"] == v + 1, \
        f"expected version {v + 1}, got {scheduled['version']}"
