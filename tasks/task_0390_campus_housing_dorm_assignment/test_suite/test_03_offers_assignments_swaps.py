"""Offer accept/decline, assignment swaps, check-out cascades, and the
cross-room bed conservation invariant."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_assignment, assert_meal_plan,
    make_officer_headers, make_student_headers,
    create_student, create_building, create_room, create_cycle,
    create_submitted_application, run_lottery, open_assignment, close_cycle,
    accept_offer, create_damage_charge, bill_charge, waive_charge,
    get_meal_plan_for_assignment,
    setup_active_assignment, setup_two_active_assignments, setup_offered_application,
)

OFFICER = make_officer_headers()


# ─── Accept happy path & immediate consistency (corner) ───────────────────────

def test_accept_creates_assignment_immediately_queryable(api):
    """PRD §3.6: "On success the server mints an `Assignment` directly in
    `status` `ACTIVE` on the application's `offered_room_id` for this student,
    recording the assignment's `room_id`, `student_id`, and the producing
    `application_id`; it also creates a linked `MealPlan` in tier `STANDARD` and
    `status` `ACTIVE`; and the application's `version` increments by 1."

    Design: Corner/consistency_model/immediate_accept_reflects_assignment_and_balance_same_request
    """
    scn = setup_offered_application(term_label="IMM_T")
    app = scn["application"]
    res = api.accept_application(
        app["id"], {"expected_application_version": app["version"]},
        make_student_headers(scn["student"]["id"]))
    accepted = validate_success(res, 200)
    assert accepted["status"] == "ACCEPTED"
    listed, meta = _list(api.list_assignments(OFFICER, params={"application_id": app["id"]}))
    assert len(listed) == 1
    assert listed[0]["status"] == "ACTIVE"
    assert_assignment(listed[0])


def test_accept_mints_standard_meal_plan(api):
    """PRD §3.8: "Every accepted offer mints a `MealPlan` linked one-to-one to the
    new assignment by its `assignment_id`, beginning in tier `STANDARD` and
    `status` `ACTIVE`."

    Design: Corner/endpoints/meal_plans_filtered_by_assignment_returns_one
    """
    scn = setup_active_assignment(term_label="FM_T")
    listed, meta = _list(api.list_meal_plans(
        OFFICER, params={"assignment_id": scn["assignment"]["id"]}))
    assert meta["total_count"] == 1
    assert len(listed) == 1
    assert listed[0]["tier"] == "STANDARD"
    assert_meal_plan(listed[0])


def test_meal_plan_tier_change_recomputes_fee(api):
    """PRD §3.8: "The owning student may change the plan's `tier` while it is
    `ACTIVE`, supplying a new `tier`, which recomputes `weekly_fee_cents` from the
    table above" ... "an `UNLIMITED` tier costs 13500."

    Design: Corner/calculations/mealplan_weekly_fee_computed_from_tier
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Meal M",
                                                  "gender_identity": "FEMALE"},
                                  term_label="MEAL_T")
    mp = get_meal_plan_for_assignment(scn["assignment"]["id"])
    res = api.change_meal_plan_tier(
        mp["id"], {"tier": "UNLIMITED"}, make_student_headers(scn["student"]["id"]))
    updated = validate_success(res, 200)
    assert updated["tier"] == "UNLIMITED"
    assert updated["weekly_fee_cents"] == 13500


def test_gender_incompatible_accept_rejected(api):
    """PRD §3.4: "A violation at accept or at swap-proposal time is rejected with
    `ERR_GENDER_INCOMPATIBLE` (HTTP 409); during the lottery sweep an incompatible
    room simply does not match, so the candidate is offered another matching room
    or waitlisted."

    Design: Corner/validations/gender_incompatible_accept_rejected
    """
    male = create_student(full_name="Male First", class_year="SENIOR",
                          gender_identity="MALE", lottery_number=370)
    female = create_student(full_name="Female Next", class_year="SENIOR",
                            gender_identity="FEMALE", lottery_number=371)
    building = create_building(name="Gender Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="G1", room_type="DOUBLE",
                       gender_inclusivity="SINGLE_GENDER")
    cycle = create_cycle(term_label="GEN_T")
    m_app = create_submitted_application(cycle["id"], male["id"],
                                         preferred_room_type="DOUBLE")
    f_app = create_submitted_application(cycle["id"], female["id"],
                                         preferred_room_type="DOUBLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    # Male accepts first, occupying the SINGLE_GENDER DOUBLE.
    accept_offer(m_app["id"], male["id"])
    # Female holds an offer for the same room; accept must now fail the gender check.
    f_current = validate_success(api.get_application(f_app["id"], OFFICER), 200)
    res = api.accept_application(
        f_app["id"], {"expected_application_version": f_current["version"]},
        make_student_headers(female["id"]))
    validate_error(res, "ERR_GENDER_INCOMPATIBLE")
    after = validate_success(api.get_application(f_app["id"], OFFICER), 200)
    assert after["status"] == "OFFERED"


# ─── Cycle close expires offers (corner) ──────────────────────────────────────

def test_cycle_close_expires_outstanding_offer_releases_bed(api):
    """PRD §3.3: "Closing cascades over every application still in `OFFERED`: each
    moves to the terminal `EXPIRED`, its reserved bed is released (the room's
    `occupied_bed_count` decrements and the room's `status` may flip from
    `RESTRICTED` back to `OPEN`), and any still-`QUEUED` waitlist entry is simply
    left for the next cycle."

    Design: Corner/state_machines/cycle_close_expires_outstanding_offer
    """
    scn = setup_offered_application(term_label="EXP_T")
    app, room, cycle = scn["application"], scn["room"], scn["cycle"]
    close_cycle(cycle["id"])
    app_after = validate_success(api.get_application(app["id"], OFFICER), 200)
    room_after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert app_after["status"] == "EXPIRED"
    assert room_after["occupied_bed_count"] == 0


# ─── Difficulty: decline releases bed, depth-3 promotion ──────────────────────

def test_decline_releases_bed_then_promotes_waitlist(api):
    """PRD §3.6: "Declining releases the offered bed — the room's
    `occupied_bed_count` decrements and its `status` may flip from `RESTRICTED`
    to `OPEN` — and then promotes the waitlist. Promotion selects, among the
    cycle's `QUEUED` waitlist entries, the entry with the best precedence —
    smallest `priority_rank_snapshot`, then smallest `lottery_number_snapshot`,
    then earliest `created_at` — whose application can match the freed room; that
    application moves from `WAITLISTED` to `OFFERED` on that room and the waitlist
    entry moves to `PROMOTED`."

    Design: Difficulty/transitive_cascade/decline_releases_bed_then_promotes_waitlist_depth3
    """
    senior = create_student(full_name="Senior S", class_year="SENIOR",
                            gender_identity="MALE", lottery_number=50)
    frosh = create_student(full_name="Frosh F", class_year="FRESHMAN",
                           gender_identity="MALE", lottery_number=51)
    building = create_building(name="Cascade Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="C1", room_type="SINGLE",
                       gender_inclusivity="ALL_GENDER")
    cycle = create_cycle(term_label="FALL_2026G")
    sr_app = create_submitted_application(cycle["id"], senior["id"],
                                          preferred_room_type="SINGLE")
    fr_app = create_submitted_application(cycle["id"], frosh["id"],
                                          preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    # Senior holds the offer; freshman is waitlisted.
    api.decline_application(sr_app["id"], make_student_headers(senior["id"]))
    sr_after = validate_success(api.get_application(sr_app["id"], OFFICER), 200)
    fr_after = validate_success(api.get_application(fr_app["id"], OFFICER), 200)
    assert sr_after["status"] == "DECLINED"
    assert fr_after["status"] == "OFFERED"
    assert fr_after["offered_room_id"] == room["id"]
    # The freshman's waitlist entry must now be PROMOTED.
    wl, _ = _list(api.list_waitlist_entries(OFFICER, params={"application_id": fr_app["id"]}))
    assert wl and wl[0]["status"] == "PROMOTED"


def test_decline_sets_application_terminal_declined(api):
    """PRD §3.6: "A student may instead decline an offer during the assignment
    window, moving the application from `OFFERED` to the terminal `DECLINED` (a
    non-`ASSIGNMENT_OPEN` phase fails with `ERR_INVALID_STATE`)."

    Design: Difficulty/transitive_cascade/decline_releases_bed_then_promotes_waitlist_depth3
    """
    senior = create_student(full_name="Solo Senior", class_year="SENIOR",
                            gender_identity="MALE", lottery_number=52)
    frosh = create_student(full_name="WL Frosh", class_year="FRESHMAN",
                           gender_identity="MALE", lottery_number=53)
    building = create_building(name="Cascade2 Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="C2", room_type="SINGLE",
                       gender_inclusivity="ALL_GENDER")
    cycle = create_cycle(term_label="FALL_CAS2")
    sr_app = create_submitted_application(cycle["id"], senior["id"],
                                          preferred_room_type="SINGLE")
    create_submitted_application(cycle["id"], frosh["id"], preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    declined = validate_success(
        api.decline_application(sr_app["id"], make_student_headers(senior["id"])), 200)
    assert declined["status"] == "DECLINED"
    room_after = validate_success(api.get_room(room["id"], OFFICER), 200)
    # bed is re-reserved by the promoted application, so it stays at 1 occupied.
    assert room_after["occupied_bed_count"] == 1


# ─── Difficulty: check-out cancels meal plan (depth-2) ────────────────────────

def test_checkout_active_cancels_meal_plan(api):
    """PRD §3.6: "If the assignment was still `ACTIVE` at check-out, the bed is
    also released, the room's `status` re-derived, and the linked meal plan moved
    from `ACTIVE` to `CANCELLED`."

    Design: Difficulty/transitive_cascade/checkout_active_cancels_mealplan_depth2
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Checkout C",
                                                  "gender_identity": "FEMALE",
                                                  "lottery_number": 60},
                                  term_label="FALL_2026H")
    asg = scn["assignment"]
    mp_before = get_meal_plan_for_assignment(asg["id"])
    assert mp_before["status"] == "ACTIVE"
    res = api.check_out_assignment(asg["id"], OFFICER)
    checked = validate_success(res, 200)
    assert checked["status"] == "CHECKED_OUT"
    mp_after = validate_success(api.get_meal_plan(mp_before["id"], OFFICER), 200)
    assert mp_after["status"] == "CANCELLED"


def test_checkout_total_zero_when_no_charges(api):
    """PRD §3.6: "On a permitted check-out the server computes
    `checkout_total_cents` as the sum of `amount_cents` over the assignment's
    damage charges whose status is `BILLED` or `PAID` (charges that are `WAIVED`
    or `PENDING` are excluded; since check-out is blocked while any are `PENDING`,
    the sum is taken over a settled set)."

    Design: Difficulty/transitive_cascade/checkout_active_cancels_mealplan_depth2
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "NoCharge C",
                                                  "lottery_number": 61},
                                  term_label="FALL_NC")
    res = api.check_out_assignment(scn["assignment"]["id"], OFFICER)
    checked = validate_success(res, 200)
    assert checked["checkout_total_cents"] == 0


# ─── Check-out billing filtering (corner) ─────────────────────────────────────

def test_checkout_total_excludes_waived_charges(api):
    """PRD §3.6: "On a permitted check-out the server computes
    `checkout_total_cents` as the sum of `amount_cents` over the assignment's
    damage charges whose status is `BILLED` or `PAID` (charges that are `WAIVED`
    or `PENDING` are excluded; since check-out is blocked while any are `PENDING`,
    the sum is taken over a settled set)."

    Design: Corner/calculations/checkout_total_excludes_waived_charges
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Checkout Mix",
                                                  "gender_identity": "MALE",
                                                  "lottery_number": 320},
                                  term_label="MIX_T")
    asg = scn["assignment"]
    ch1 = create_damage_charge(asg["id"], category="CLEANING",
                               assessed_cents=3000, split_basis="SOLE")
    ch2 = create_damage_charge(asg["id"], category="LOST_KEY",
                               assessed_cents=5000, split_basis="SOLE")
    bill_charge(ch1["id"])
    waive_charge(ch2["id"])
    res = api.check_out_assignment(asg["id"], OFFICER)
    checked = validate_success(res, 200)
    assert checked["checkout_total_cents"] == 3000
    assert checked["status"] == "CHECKED_OUT"


def test_checkout_with_pending_charge_rejected(api):
    """PRD §3.6: "Check-out is blocked while any damage charge on the assignment
    is still `PENDING`; such a request is rejected with `ERR_UNSETTLED_CHARGES`
    (HTTP 409)."

    Design: Corner/validations/checkout_with_pending_charge_rejected
    """
    scn = setup_active_assignment(student_kwargs={"full_name": "Unsettled U",
                                                  "gender_identity": "MALE",
                                                  "lottery_number": 390},
                                  term_label="UNS_T")
    asg = scn["assignment"]
    create_damage_charge(asg["id"], category="REPAIR",
                         assessed_cents=2000, split_basis="SOLE")
    res = api.check_out_assignment(asg["id"], OFFICER)
    validate_error(res, "ERR_UNSETTLED_CHARGES")
    after = validate_success(api.get_assignment(asg["id"], OFFICER), 200)
    assert after["status"] == "ACTIVE"


# ─── Swaps (corner precondition + difficulty cycle/invariant) ─────────────────

def test_propose_swap_counterparty_not_active_precondition(api):
    """PRD §3.6: "A swap proposal is permitted only by the proposing assignment's
    own student, only while the cycle is in `ASSIGNMENT_OPEN`, only when the
    counterparty assignment exists and is `ACTIVE`, and only when both rooms are
    gender-compatible with both students (per §3.4); a failed cross-entity
    precondition such as a non-`ACTIVE` counterparty is `ERR_PRECONDITION_NOT_MET`
    (HTTP 409)."

    Design: Corner/errors/propose_swap_counterparty_not_active_precondition
    """
    scn = setup_two_active_assignments(term_label="SW2_T")
    proposer = scn["assignment_a"]
    counterparty = scn["assignment_b"]
    # Check out the counterparty so it is CHECKED_OUT (not ACTIVE).
    validate_success(api.check_out_assignment(counterparty["id"], OFFICER), 200)
    res = api.propose_swap(
        proposer["id"], {"counterparty_assignment_id": counterparty["id"]},
        make_student_headers(scn["student_a"]["id"]))
    validate_error(res, "ERR_PRECONDITION_NOT_MET")
    after = validate_success(api.get_assignment(proposer["id"], OFFICER), 200)
    assert after["status"] == "ACTIVE"


def test_swap_propose_then_confirm_exchanges_rooms(api):
    """PRD §3.6: "Confirming exchanges the `room_id` between the two assignments,
    moves both back from `SWAP_PENDING` to `ACTIVE`, clears
    `swap_counterparty_assignment_id` on both, re-derives each room's `status`,
    and increments the confirming assignment's `version` by 1; the total occupied
    bed count is unchanged but each room's count is recomputed."

    Design: Difficulty/non_linear_state_machine/assignment_swap_cyclic_pending_back_to_active
    """
    scn = setup_two_active_assignments(term_label="FALL_2026F")
    a, b = scn["assignment_a"], scn["assignment_b"]
    a_room_before = validate_success(api.get_assignment(a["id"], OFFICER), 200)["room_id"]
    # propose (a -> SWAP_PENDING, b -> SWAP_PENDING)
    validate_success(api.propose_swap(
        a["id"], {"counterparty_assignment_id": b["id"]},
        make_student_headers(scn["student_a"]["id"])), 200)
    b_pending = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    assert b_pending["status"] == "SWAP_PENDING"
    # confirm from the non-proposing leg (b) with its current version
    validate_success(api.confirm_swap(
        b["id"], {"expected_assignment_version": b_pending["version"]},
        make_student_headers(scn["student_b"]["id"])), 200)
    a_after = validate_success(api.get_assignment(a["id"], OFFICER), 200)
    b_after = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    assert a_after["status"] == "ACTIVE"
    assert b_after["status"] == "ACTIVE"
    assert a_after["room_id"] != a_room_before, "rooms were exchanged"


def test_swap_cycle_clears_counterparty_back_to_active(api):
    """PRD §3.6: "Proposing moves both assignments from `ACTIVE` to
    `SWAP_PENDING` and sets each assignment's `swap_counterparty_assignment_id` to
    the other." ... "moves both back from `SWAP_PENDING` to `ACTIVE`, clears
    `swap_counterparty_assignment_id` on both".

    Design: Difficulty/non_linear_state_machine/assignment_swap_cyclic_pending_back_to_active
    """
    scn = setup_two_active_assignments(term_label="FALL_SWCYC")
    a, b = scn["assignment_a"], scn["assignment_b"]
    validate_success(api.propose_swap(
        a["id"], {"counterparty_assignment_id": b["id"]},
        make_student_headers(scn["student_a"]["id"])), 200)
    a_pending = validate_success(api.get_assignment(a["id"], OFFICER), 200)
    assert a_pending["swap_counterparty_assignment_id"] == b["id"]
    b_pending = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    validate_success(api.confirm_swap(
        b["id"], {"expected_assignment_version": b_pending["version"]},
        make_student_headers(scn["student_b"]["id"])), 200)
    a_after = validate_success(api.get_assignment(a["id"], OFFICER), 200)
    b_after = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    assert a_after["status"] == "ACTIVE" and b_after["status"] == "ACTIVE"
    assert a_after["swap_counterparty_assignment_id"] is None
    assert b_after["swap_counterparty_assignment_id"] is None


def test_swap_confirm_conserves_total_beds_over_two_rooms(api):
    """PRD §3.6: "the total occupied bed count is unchanged but each room's count
    is recomputed."
    PRD §2.5: "A building's `occupied_bed_count` is the sum of
    `occupied_bed_count` across its rooms".

    Design: Difficulty/compensating_invariant/swap_confirm_conserves_total_beds_over_two_rooms
    """
    scn = setup_two_active_assignments(term_label="FALL_2026Q")
    a, b = scn["assignment_a"], scn["assignment_b"]
    room_a, room_b = scn["room_a"], scn["room_b"]
    validate_success(api.propose_swap(
        a["id"], {"counterparty_assignment_id": b["id"]},
        make_student_headers(scn["student_a"]["id"])), 200)
    b_pending = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    validate_success(api.confirm_swap(
        b["id"], {"expected_assignment_version": b_pending["version"]},
        make_student_headers(scn["student_b"]["id"])), 200)
    ra = validate_success(api.get_room(room_a["id"], OFFICER), 200)
    rb = validate_success(api.get_room(room_b["id"], OFFICER), 200)
    assert ra["occupied_bed_count"] == 1
    assert rb["occupied_bed_count"] == 1
    assert ra["occupied_bed_count"] + rb["occupied_bed_count"] == 2


def test_swap_confirm_conserves_building_occupied_bed_count(api):
    """PRD §2.5: "A building's `occupied_bed_count` is the sum of
    `occupied_bed_count` across its rooms, and its `total_bed_count` is the sum of
    `bed_capacity` across only those rooms whose status is not `OFFLINE`."
    PRD §3.6: "the total occupied bed count is unchanged but each room's count is
    recomputed."

    Design: Difficulty/compensating_invariant/swap_confirm_conserves_total_beds_over_two_rooms
    """
    scn = setup_two_active_assignments(term_label="FALL_SWBLD")
    a, b = scn["assignment_a"], scn["assignment_b"]
    building = scn["building"]
    before = validate_success(api.get_building(building["id"], OFFICER), 200)
    assert before["occupied_bed_count"] == 2
    validate_success(api.propose_swap(
        a["id"], {"counterparty_assignment_id": b["id"]},
        make_student_headers(scn["student_a"]["id"])), 200)
    b_pending = validate_success(api.get_assignment(b["id"], OFFICER), 200)
    validate_success(api.confirm_swap(
        b["id"], {"expected_assignment_version": b_pending["version"]},
        make_student_headers(scn["student_b"]["id"])), 200)
    after = validate_success(api.get_building(building["id"], OFFICER), 200)
    assert after["occupied_bed_count"] == 2, "total occupied beds conserved across the swap"


# ─── local list helper ────────────────────────────────────────────────────────

def _list(response):
    assert 200 <= response.status_code < 300, f"list failed: {response.status_code} {response.text}"
    body = response.json()
    return body["data"], body.get("meta", {})
