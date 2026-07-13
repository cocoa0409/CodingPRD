"""Clinics/enrollment, competitions, stringing, and the no-show strike boundary."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_member_with_strikes, setup_clinic, setup_tournament,
    setup_round_robin_with_participant, make_member, make_subscription,
    make_stringing_job, make_enrollment, create_enrollment_payload,
    create_participant_payload, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── boundary_precision / boundary_noshow_strikes_two_does_not_suspend ─
def test_two_noshows_do_not_suspend_member():
    """PRD §3.4: "When no_show_strikes reaches at least 3, the member is automatically
    transitioned ACTIVE → SUSPENDED (two strikes do not suspend; the third does)."

    Design: Difficulty/boundary_precision_check/boundary_noshow_strikes_two_does_not_suspend
    """
    member, _, _ = setup_member_with_strikes(2)
    m = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m["no_show_strikes"] == 2
    assert m["status"] == "ACTIVE"


def test_two_noshows_leave_subscription_active():
    """PRD §3.4: "entering SUSPENDED triggers a further cascade: if the member owns a
    non-CANCELLED subscription that is currently ACTIVE, that subscription is
    transitioned ACTIVE → FROZEN and its frozen_at is stamped to the current clock
    instant."

    Design: Difficulty/boundary_precision_check/boundary_noshow_strikes_two_does_not_suspend
    """
    _, sub, _ = setup_member_with_strikes(2)
    s = validate_success(api_client.get_subscription(sub["id"], FD), 200)
    assert s["status"] == "ACTIVE"


# ─── cross_entity_state_dependency / enrollment requires ACTIVE sub ───
def test_enroll_with_frozen_subscription_rejected():
    """PRD §3.5: "the enrolling member must be ACTIVE (else ERR_MEMBER_SUSPENDED) and
    must hold an ACTIVE subscription — a member with no subscription at all is rejected
    with ERR_SUBSCRIPTION_REQUIRED, and one whose subscription exists but is not ACTIVE
    with ERR_SUBSCRIPTION_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/xdep_enrollment_requires_subscription_active
    """
    c = setup_clinic(capacity=4)
    member = make_member()
    sub = make_subscription(member["id"], c["plan"]["id"])
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    res = api_client.create_enrollment(
        create_enrollment_payload(c["lesson"]["id"], member["id"]), FD)
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_enroll_allowed_once_subscription_unfrozen():
    """PRD §3.2: "Unfreezing moves a FROZEN subscription back to ACTIVE and clears
    frozen_at to null."
    PRD §3.5: "must hold an ACTIVE subscription — a member with no subscription at all
    is rejected with ERR_SUBSCRIPTION_REQUIRED, and one whose subscription exists but
    is not ACTIVE with ERR_SUBSCRIPTION_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/xdep_enrollment_requires_subscription_active
    """
    c = setup_clinic(capacity=4)
    member = make_member()
    sub = make_subscription(member["id"], c["plan"]["id"])
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    get_success_data(api_client.unfreeze_subscription(sub["id"], FD))
    enrollment = make_enrollment(c["lesson"]["id"], member["id"])
    assert enrollment["status"] == "ENROLLED"


# ─── boundary_precision / boundary_clinic_capacity_full_waitlists ─────
def test_enroll_at_full_capacity_is_waitlisted():
    """PRD §3.5: "once `enrolled_count` equals `capacity`, further enrollments are
    placed as `WAITLISTED`."

    Design: Difficulty/boundary_precision_check/boundary_clinic_capacity_full_waitlists
    """
    c = setup_clinic(capacity=2, enroll=2, extra_members=1)
    third = c["members"][2]
    enrollment = make_enrollment(c["lesson"]["id"], third["id"])
    assert enrollment["status"] == "WAITLISTED"


def test_enrolled_count_stays_at_capacity_when_full():
    """PRD §3.5: "Only `ENROLLED` seats count against capacity; `WAITLISTED` seats do
    not."

    Design: Difficulty/boundary_precision_check/boundary_clinic_capacity_full_waitlists
    """
    c = setup_clinic(capacity=2, enroll=2, extra_members=1)
    third = c["members"][2]
    make_enrollment(c["lesson"]["id"], third["id"])
    lesson = validate_success(api_client.get_lesson(c["lesson"]["id"], FD), 200)
    assert lesson["enrolled_count"] == 2


# ─── Corner: tournament_seeding_bracket_slots_deterministic ───────────
def test_tournament_seeding_assigns_bracket_slots_by_seed():
    """PRD §3.6: "Seeding orders the active participants by seed ascending, treating a
    null seed as ranking after all explicit seeds, and breaks ties by created_at
    ascending (never by id); it then assigns bracket_slot values 1 through draw_size in
    that order."

    Design: Corner/calculations/tournament_seeding_bracket_slots_deterministic
    """
    t = setup_tournament(draw_size=2, seeds=(1, 2))
    comp = get_success_data(api_client.start_competition(t["competition"]["id"], FD))
    p1 = validate_success(api_client.get_participant(t["participants"][0]["id"], FD), 200)
    p2 = validate_success(api_client.get_participant(t["participants"][1]["id"], FD), 200)
    assert p1["bracket_slot"] == 1
    assert p2["bracket_slot"] == 2
    assert comp["status"] == "IN_PROGRESS"


# ─── Corner: duplicate_participant_registration_rejected ──────────────
def test_duplicate_participant_registration_rejected():
    """PRD §3.6: "a member may not register twice in the same competition, else
    ERR_DUPLICATE_PARTICIPANT."

    Design: Corner/validations/duplicate_participant_registration_rejected
    """
    comp, member, _ = setup_round_robin_with_participant()
    res = api_client.create_participant(
        create_participant_payload(comp["id"], member["id"]), FD)
    validate_error(res, "ERR_DUPLICATE_PARTICIPANT")


# ─── Corner: stringing_intake_charges_then_cancel_refunds ─────────────
def test_stringing_intake_charges_then_cancel_refunds():
    """PRD §3.7: "its `price_cents` is posted to the member's `account_balance_cents` at
    intake."
    PRD §3.7: "cancellation reverses the job's `price_cents` from the member's
    `account_balance_cents`."

    Design: Corner/cross_cutting/stringing_intake_charges_then_cancel_refunds
    """
    member = make_member()
    job = make_stringing_job(member["id"], racquet_label="Blade",
                             string_type="Gut", tension=52, price_cents=4500)
    m_after_intake = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m_after_intake["account_balance_cents"] == 4500

    cancelled = get_success_data(api_client.cancel_stringing_job(job["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    m_after_cancel = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m_after_cancel["account_balance_cents"] == 0
