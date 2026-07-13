"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch (the server database is empty
and the logical clock resets to 2026-05-01T00:00:00Z before every test). Setup
calls use get_success_data() so a broken precondition surfaces as a clear
"setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload, create_basic_plan_payload, create_court_payload,
    create_member_payload, create_pro_payload, create_subscription_payload,
    create_reservation_payload, create_lesson_payload, create_enrollment_payload,
    create_competition_payload, create_participant_payload,
    create_stringing_job_payload,
)
from .test_users import TEST_USERS

FD = TEST_USERS["frontdesk_headers"]


# ─── Primitive creators ───────────────────────────────────────────────
def set_clock(iso: str):
    """Reposition the server logical clock to an ISO 8601 instant (PRD §2.5)."""
    get_success_data(api_client.set_clock({"to_iso8601": iso}, FD))


def make_plan(**overrides):
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), FD))


def make_basic_plan(**overrides):
    return get_success_data(api_client.create_plan(create_basic_plan_payload(**overrides), FD))


def make_court(**overrides):
    return get_success_data(api_client.create_court(create_court_payload(**overrides), FD))


def make_member(**overrides):
    return get_success_data(api_client.create_member(create_member_payload(**overrides), FD))


def make_pro(**overrides):
    return get_success_data(api_client.create_pro(create_pro_payload(**overrides), FD))


def make_subscription(member_id, plan_id):
    return get_success_data(
        api_client.create_subscription(create_subscription_payload(member_id, plan_id), FD))


def make_reservation(court_id, member_id, start_time, end_time, headers=None, **overrides):
    h = headers or FD
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(court_id, member_id, start_time, end_time, **overrides), h))


def make_lesson(pro_id, court_id, kind, start_time, end_time, price_cents, **overrides):
    return get_success_data(api_client.create_lesson(
        create_lesson_payload(pro_id, court_id, kind, start_time, end_time, price_cents,
                              **overrides), FD))


def make_enrollment(lesson_id, member_id, headers=None):
    h = headers or FD
    return get_success_data(
        api_client.create_enrollment(create_enrollment_payload(lesson_id, member_id), h))


def make_stringing_job(member_id, **overrides):
    return get_success_data(
        api_client.create_stringing_job(create_stringing_job_payload(member_id, **overrides), FD))


# ─── Tier 2: Member + subscription + court scenarios ──────────────────
def setup_member_with_subscription(plan=None, **plan_overrides):
    """A member with one ACTIVE subscription on a PREMIER plan (unless a plan is
    supplied). Returns (plan, member, subscription)."""
    plan = plan if plan is not None else make_plan(**plan_overrides)
    member = make_member()
    sub = make_subscription(member["id"], plan["id"])
    return plan, member, sub


def setup_booking_scenario(plan=None, plan_overrides=None, court_overrides=None):
    """An AVAILABLE court plus a member with an ACTIVE subscription. Returns a dict
    with keys plan, court, member, sub."""
    plan = plan if plan is not None else make_plan(**(plan_overrides or {}))
    court = make_court(**(court_overrides or {}))
    member = make_member()
    sub = make_subscription(member["id"], plan["id"])
    return {"plan": plan, "court": court, "member": member, "sub": sub}


# ─── Tier 3: No-show accumulation ─────────────────────────────────────
def setup_member_with_strikes(strikes: int):
    """Drive `strikes` no-shows on a fresh PREMIER member using off-peak 1-hour
    credit reservations on 2026-05-02. Each reservation is booked (while the clock
    is before its start), the clock is advanced past the 15-minute grace, and the
    reservation is marked no-show. Leaves the clock at the last strike's grace
    instant. Returns (member, subscription, court)."""
    plan = make_plan()
    court = make_court()
    member = make_member()
    sub = make_subscription(member["id"], plan["id"])
    for i in range(strikes):
        hour = 8 + i
        start = f"2026-05-02T{hour:02d}:00:00Z"
        end = f"2026-05-02T{hour + 1:02d}:00:00Z"
        res = make_reservation(court["id"], member["id"], start, end)
        set_clock(f"2026-05-02T{hour:02d}:16:00Z")
        get_success_data(api_client.mark_no_show(res["id"], FD))
    return member, sub, court


# ─── Tier 4: Clinics ──────────────────────────────────────────────────
def setup_clinic(capacity=2, price_cents=2000, enroll=0, extra_members=0):
    """A CLINIC lesson (2026-05-08T10:00..11:00) plus `enroll + extra_members`
    members each holding an ACTIVE subscription; the first `enroll` are enrolled in
    creation order. Returns a dict with keys plan, pro, court, lesson, members,
    enrollments."""
    plan = make_plan()
    pro = make_pro()
    court = make_court()
    lesson = make_lesson(pro["id"], court["id"], "CLINIC",
                         "2026-05-08T10:00:00Z", "2026-05-08T11:00:00Z", price_cents,
                         capacity=capacity)
    members = []
    for _ in range(enroll + extra_members):
        m = make_member()
        make_subscription(m["id"], plan["id"])
        members.append(m)
    enrollments = []
    for i in range(enroll):
        enrollments.append(make_enrollment(lesson["id"], members[i]["id"]))
    return {"plan": plan, "pro": pro, "court": court, "lesson": lesson,
            "members": members, "enrollments": enrollments}


# ─── Tier 4: Competitions ─────────────────────────────────────────────
def setup_tournament(draw_size=2, seeds=(1, 2), entry_fee_cents=0):
    """A TOURNAMENT with `len(seeds)` ACTIVE participants seeded as given. Returns a
    dict with keys competition, members, participants (participants aligned to
    seeds order)."""
    comp = get_success_data(api_client.create_competition(
        create_competition_payload("Spring Open", "TOURNAMENT",
                                   draw_size=draw_size, entry_fee_cents=entry_fee_cents), FD))
    members, participants = [], []
    for s in seeds:
        m = make_member()
        members.append(m)
        p = get_success_data(api_client.create_participant(
            create_participant_payload(comp["id"], m["id"], seed=s), FD))
        participants.append(p)
    return {"competition": comp, "members": members, "participants": participants}


def setup_round_robin_with_participant(entry_fee_cents=0):
    """A ROUND_ROBIN competition (REGISTRATION) with one registered member. Returns
    (competition, member, participant)."""
    comp = get_success_data(api_client.create_competition(
        create_competition_payload("Ladder A", "ROUND_ROBIN",
                                   entry_fee_cents=entry_fee_cents), FD))
    member = make_member()
    participant = get_success_data(api_client.create_participant(
        create_participant_payload(comp["id"], member["id"]), FD))
    return comp, member, participant


# ─── Tier 5: OCC scenarios ────────────────────────────────────────────
def setup_change_plan_occ():
    """A member with an ACTIVE subscription on plan_a and a second plan_b to move
    to. Returns a dict with keys plan_a, plan_b, member, sub, v0 (the subscription
    version captured at creation)."""
    plan_a = make_plan()
    plan_b = make_plan(name="Elite", tier="ELITE", monthly_fee_cents=9000,
                       monthly_court_credits=20, peak_access=True,
                       guest_fee_cents=1000, freeze_limit=3)
    member = make_member()
    sub = make_subscription(member["id"], plan_a["id"])
    return {"plan_a": plan_a, "plan_b": plan_b, "member": member,
            "sub": sub, "v0": sub["version"]}


def setup_reschedule_occ():
    """A member with an ACTIVE subscription and one BOOKED reservation on
    2026-05-14T10:00. Returns a dict with keys plan, court, member, sub,
    reservation, rv0 (the reservation version captured at booking)."""
    scenario = setup_booking_scenario()
    res = make_reservation(scenario["court"]["id"], scenario["member"]["id"],
                           "2026-05-14T10:00:00Z", "2026-05-14T11:00:00Z")
    scenario["reservation"] = res
    scenario["rv0"] = res["version"]
    return scenario
