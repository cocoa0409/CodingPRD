"""Complementary second tests for every Queue A (Difficulty) instance — each exercises a
distinct angle (the other side of a boundary, a contrasting input, or an additional observable)
of the same rule the primary test covers.

Every difficulty instance therefore carries >=2 tagged tests across the suite.
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]


# =========================================================================
# Rule 1 — dual_variant_calc (complementary)
# =========================================================================
def test_provisional_charge_updates_live_when_sibling_drops(api):
    """PRD §3.3: "This live, per-enrollment `monthly_charge_cents` reflects the family's current
    billing-active set at any instant and shifts as siblings and classes are added or dropped; it
    is the provisional figure."
    PRD §3.3: "the second class is discounted by ten percent."

    Complement to the snapshot test: where the invoiced snapshot stays frozen, the provisional
    Enrollment.monthly_charge_cents on the remaining class is unchanged at 10000 here because
    classA was always the un-discounted 1st class — confirming the live figure tracks the active
    set (classB's drop removes the 2nd-class line, not classA's).

    Design: Difficulty/dual_variant_calc/tuition_provisional_vs_invoiced_snapshot
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "JAZZ", "monthly_tuition_cents": 10000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 7000},
    )
    family = fx.create_family()
    student = fx.create_student(family["id"], full_name="Ada", level="ELITE")
    enr_a = fx.create_enrollment(student["id"], env["secA"]["id"])
    enr_b = fx.create_enrollment(student["id"], env["secB"]["id"])
    enr_b_before = validate_success(api.get_enrollment(enr_b["id"], ADMIN_H))
    assert enr_b_before["monthly_charge_cents"] == 6300  # 2nd class mc10%

    validate_success(api.drop_enrollment(enr_b["id"], ADMIN_H))
    enr_a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    enr_b_after = validate_success(api.get_enrollment(enr_b["id"], ADMIN_H))
    assert enr_a_after["monthly_charge_cents"] == 10000  # still the sole 1st class
    assert enr_b_after["placement_status"] == "DROPPED"
    assert enr_b_after["billing_status"] == "BILLING_ENDED"


def test_chaperone_threshold_blocks_confirm_when_short(api):
    """PRD §3.7: "the number of chaperones required is the `participant_count` divided by the
    `chaperone_ratio` and rounded up to the next whole number, and this required count must be at
    most the `chaperone_count`."
    PRD §3.7: "one participant over a multiple bumps the requirement up by one. Failing this is
    rejected with `ERR_INSUFFICIENT_CHAPERONES`."

    Complement to the passing case: 5 participants, ratio 4, 1 chaperone -> ceil(5/4)=2 > 1 ->
    rejected. The chaperone ceil-threshold (TravelTrip domain) is exercised on its failing side.

    Design: Difficulty/dual_variant_calc/chaperone_threshold_vs_tuition_tier_distinct_domains
    """
    setup = fx.setup_proposed_trip(num_participants=5, chaperone_ratio=4, chaperone_count=1,
                                   per_member_cost_cents=50000, min_level="NOVICE")
    resp = api.confirm_trip(setup["trip"]["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CHAPERONES.value)
    trip_after = validate_success(api.get_trip(setup["trip"]["id"], ADMIN_H))
    assert trip_after["status"] == "PROPOSED"


# =========================================================================
# Rule 2 — combinatorial_formula (complementary)
# =========================================================================
def test_family_three_student_tier_stacks_on_multiclass(api):
    """PRD §3.3: "one such student yields no family discount, two students yield a five percent
    discount, and three or more students yield an eight percent discount."
    PRD §3.3: "apply the multi-class percentage and round that intermediate result half up to a
    whole cent; then apply the family percentage to that rounded figure and round half up again
    to a whole cent."

    Three single-class students (sibling_count 3 -> family 8%): each is a 1st class (no mc), so
    each charge is round(base*0.92). For base 10000 -> 9200; the family tier stacks atop the (zero)
    multi-class discount with the pinned per-line rounding.

    Design: Difficulty/combinatorial_formula/tuition_rounding_order_pinned_per_line
    """
    env = fx.setup_open_term_three_sections(tuitions=(10000, 10000, 10000))
    sections = env["sections"]
    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="A", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="B", level="ELITE")
    s3 = fx.create_student(family["id"], full_name="C", level="ELITE")
    e1 = fx.create_enrollment(s1["id"], sections[0]["id"])
    e2 = fx.create_enrollment(s2["id"], sections[1]["id"])
    e3 = fx.create_enrollment(s3["id"], sections[2]["id"])
    for e in (e1, e2, e3):
        after = validate_success(api.get_enrollment(e["id"], ADMIN_H))
        assert after["monthly_charge_cents"] == 9200, \
            f"each 1st-class charge with family 8% should be 9200, got {after['monthly_charge_cents']}"


def test_multiclass_third_class_twenty_percent(api):
    """PRD §3.3: "A student's first class gets no discount; the second class is discounted by ten
    percent; the third and any further class are discounted by twenty percent."
    PRD §3.3: "those active enrollments are sorted by their section's `monthly_tuition_cents`
    descending, breaking ties by `created_at` ascending (never by `id`)."

    Complement focusing on the 3rd-class 20% tier in isolation (single-student family, 0% family):
    classes 10000/8000/5000 -> 10000(1st), 7200(2nd mc10%), 4000(3rd mc20%).

    Design: Difficulty/combinatorial_formula/tuition_nonlinear_multiclass_family_interaction
    """
    env = fx.setup_open_term_three_sections(tuitions=(10000, 8000, 5000))
    sections = env["sections"]
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    e1 = fx.create_enrollment(student["id"], sections[0]["id"])
    e2 = fx.create_enrollment(student["id"], sections[1]["id"])
    e3 = fx.create_enrollment(student["id"], sections[2]["id"])
    a1 = validate_success(api.get_enrollment(e1["id"], ADMIN_H))
    a2 = validate_success(api.get_enrollment(e2["id"], ADMIN_H))
    a3 = validate_success(api.get_enrollment(e3["id"], ADMIN_H))
    assert a1["monthly_charge_cents"] == 10000
    assert a2["monthly_charge_cents"] == 7200
    assert a3["monthly_charge_cents"] == 4000


# =========================================================================
# Rule 3 — non_linear_state_machine (complementary)
# =========================================================================
def test_section_flips_to_full_on_capacity_reached(api):
    """PRD §3.2: "While `OPEN`, the section accepts confirmations until its `enrolled_count`
    reaches effective capacity, at which point the system flips it to `FULL` and routes further
    placements to the waitlist."
    PRD §3.3: "If that confirmation brings `enrolled_count` to effective capacity, the section
    flips from `OPEN` to `FULL`."

    Complement (the OPEN->FULL leg of the cycle): cap 1 section confirms one student and flips to
    FULL with enrolled_count 1; a further placement is routed to the waitlist.

    Design: Difficulty/non_linear_state_machine/section_cyclic_open_full_open
    """
    env = fx.setup_open_term_with_section(section_overrides={"capacity_cap": 1})
    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="First", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="Second", level="ELITE")
    fx.create_enrollment(s1["id"], env["section"]["id"])
    section_full = validate_success(api.get_section(env["section"]["id"], ADMIN_H))
    assert section_full["status"] == "FULL"
    assert section_full["enrolled_count"] == 1
    e2 = fx.create_enrollment(s2["id"], env["section"]["id"])
    assert e2["placement_status"] == "WAITLISTED"


def test_billing_pause_recomputes_family_tuition(api):
    """PRD §3.3: "Either toggle re-runs the family tuition recompute, because a paused enrollment
    leaves the active set (lowering counts and possibly the discount tier) and a resumed one
    rejoins it."
    PRD §3.3: "the second class is discounted by ten percent."

    Complement focusing on the billing dimension's side effect: with one student in two classes
    (10000 1st, 7000 2nd mc10%=6300), pausing classB removes it from the active set so classA is
    recomputed as the now-sole class (still 10000), while placement stays CONFIRMED on both.

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_placement_vs_billing
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "JAZZ", "monthly_tuition_cents": 10000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 7000},
    )
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    enr_a = fx.create_enrollment(student["id"], env["secA"]["id"])
    enr_b = fx.create_enrollment(student["id"], env["secB"]["id"])
    validate_success(api.pause_billing(enr_b["id"], ADMIN_H))
    a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    b_after = validate_success(api.get_enrollment(enr_b["id"], ADMIN_H))
    assert a_after["monthly_charge_cents"] == 10000
    assert a_after["placement_status"] == "CONFIRMED"
    assert b_after["placement_status"] == "CONFIRMED"
    assert b_after["billing_status"] == "BILLING_PAUSED"


# =========================================================================
# Rule 4 — transitive_cascade (complementary)
# =========================================================================
def test_promotion_resequences_remaining_waitlist_ranks(api):
    """PRD §3.4: "every still-`WAITLISTED` enrollment behind it has its `waitlist_rank`
    decremented by one to close the gap."
    PRD §3.4: "the one with the lowest `waitlist_rank` (the earliest `created_at`) is promoted."

    Complement to the depth-3 chain: with two waitlisted enrollments behind a confirmed one,
    dropping the confirmed promotes rank-1 and decrements the remaining waitlisted one's rank
    from 2 to 1.

    Design: Difficulty/transitive_cascade/drop_promote_recompute_chain_depth3
    """
    env = fx.setup_open_term_with_section(section_overrides={"capacity_cap": 1})
    sec_id = env["section"]["id"]
    fam = fx.create_family()
    s_conf = fx.create_student(fam["id"], full_name="Conf", level="ELITE")
    s_w1 = fx.create_student(fam["id"], full_name="W1", level="ELITE")
    s_w2 = fx.create_student(fam["id"], full_name="W2", level="ELITE")
    conf = fx.create_enrollment(s_conf["id"], sec_id)
    w1 = fx.create_enrollment(s_w1["id"], sec_id)
    w2 = fx.create_enrollment(s_w2["id"], sec_id)
    assert w1["waitlist_rank"] == 1
    assert w2["waitlist_rank"] == 2

    validate_success(api.drop_enrollment(conf["id"], ADMIN_H))
    w1_after = validate_success(api.get_enrollment(w1["id"], ADMIN_H))
    w2_after = validate_success(api.get_enrollment(w2["id"], ADMIN_H))
    assert w1_after["placement_status"] == "WAITLIST_PROMOTED"
    assert w2_after["placement_status"] == "WAITLISTED"
    assert w2_after["waitlist_rank"] == 1


def test_section_cancel_drops_all_enrollments(api):
    """PRD §3.2: "When a populated section is cancelled, every enrollment in `CONFIRMED`,
    `WAITLISTED`, or `WAITLIST_PROMOTED` placement is moved to `DROPPED`; each one that was in
    `CONFIRMED` or `WAITLIST_PROMOTED` also has its `billing_status` moved to `BILLING_ENDED`."
    PRD §3.2: "Cancellation is permitted from `PLANNED`, `SCHEDULED`, or `OPEN`."

    Complement to the recompute chain: cancelling a populated, still-OPEN section (capacity_cap
    20, so two confirmations keep it under capacity and OPEN — cancellable) drops both CONFIRMED
    enrollments; each one's billing ends.

    Design: Difficulty/transitive_cascade/section_cancel_drop_recompute_chain_depth2
    """
    env = fx.setup_open_term_with_section(section_overrides={"capacity_cap": 20})
    sec_id = env["section"]["id"]
    fam = fx.create_family()
    s1 = fx.create_student(fam["id"], full_name="ConfA", level="ELITE")
    s2 = fx.create_student(fam["id"], full_name="ConfB", level="ELITE")
    conf_a = fx.create_enrollment(s1["id"], sec_id)
    conf_b = fx.create_enrollment(s2["id"], sec_id)
    assert conf_a["placement_status"] == "CONFIRMED"
    assert conf_b["placement_status"] == "CONFIRMED"

    validate_success(api.cancel_section(sec_id, ADMIN_H))
    a_after = validate_success(api.get_enrollment(conf_a["id"], ADMIN_H))
    b_after = validate_success(api.get_enrollment(conf_b["id"], ADMIN_H))
    assert a_after["placement_status"] == "DROPPED"
    assert a_after["billing_status"] == "BILLING_ENDED"
    assert b_after["placement_status"] == "DROPPED"
    assert b_after["billing_status"] == "BILLING_ENDED"


# =========================================================================
# Rule 5 — priority_pair_validation_conflict (complementary)
# =========================================================================
def test_delinquency_gate_alone_fires_when_state_legal(api):
    """PRD §3.3: "A confirmation additionally requires that the family not be `DELINQUENT`; a
    delinquent family's confirmation is refused with `ERR_FAMILY_DELINQUENT`."
    PRD §2.9: "while a family is `DELINQUENT`, it cannot confirm new enrollments and cannot sign
    students up for trips."

    Complement isolating the fiscal gate (no state violation): a fresh, legal enrollment into an
    open section by a DELINQUENT family hits only the delinquency gate -> ERR_FAMILY_DELINQUENT,
    confirming the fiscal check is what fires once the state path is clean.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_enrollment_confirm
    """
    del_env = fx.setup_delinquent_family(billing_month="2026-02", advance_to="2026-02-20T00:00:00Z")
    resp = api.create_enrollment(
        f.create_enrollment_payload(del_env["student"]["id"], del_env["secB"]["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_FAMILY_DELINQUENT.value)


def test_room_conflict_fires_when_section_exists(api):
    """PRD §3.2: "a new session **room-conflicts** if, on the same `day_of_week` and in the same
    room, its window from its start up to its end *plus the room's `turnover_buffer_minutes`*
    overlaps the equivalently-buffered window of any other section's session in that room — a
    violation is rejected with `ERR_ROOM_CONFLICT`."

    Complement: when the section id DOES resolve (no existence failure), the same temporal
    overlap that would have been pre-empted by ERR_NOT_FOUND instead surfaces the business-rule
    ERR_ROOM_CONFLICT — confirming existence (priority 4) and the conflict (a business check) are
    distinct gates.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_session_create
    """
    term = fx.create_term()
    room = fx.create_room(capacity=20, turnover_buffer_minutes=0)
    inst_a = fx.create_instructor(email="exA@x.com")
    inst_b = fx.create_instructor(email="exB@x.com")
    secA = fx.create_section(term["id"], room["id"], inst_a["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room["id"], inst_b["id"], discipline="TAP")
    resp = api.create_session(secB["id"], f.create_session_payload(
        day_of_week=0, start_minute=630, end_minute=690), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT.value)


# =========================================================================
# Rule 6 — boundary_precision_check (complementary)
# =========================================================================
def test_costume_rush_surcharge_applies_after_close_date(api):
    """PRD §3.6: "if the clock's date is strictly after the costume's `size_window_close_date`,
    the price is `unit_price_cents` plus `rush_surcharge_cents`."
    PRD §3.6: "only a clock date past it triggers the rush price."

    The X+1 side of the strict boundary: clock at 2026-03-16 (one day past close 2026-03-15)
    triggers the rush -> price 4500+1500=6000.

    Design: Difficulty/boundary_precision_check/costume_rush_boundary_on_close_date
    """
    env = fx.setup_costume_draft_order(unit_price_cents=4500, rush_surcharge_cents=1500,
                                       size_window_close_date="2026-03-15")
    get_success_data(api.set_clock("2026-03-16T00:00:00Z", ADMIN_H))
    validate_success(api.submit_costume_order(env["costume"]["id"], ADMIN_H))
    order_after = validate_success(api.get_costume_order(env["order"]["id"], ADMIN_H))
    assert order_after["price_cents"] == 6000, "rush surcharge applies the day after the close date"
    assert order_after["status"] == "SUBMITTED"


def test_second_seat_hold_on_sold_out_recital_rejected(api):
    """PRD §3.8: "a duplicate label, or a hold that would push `seats_sold` past `total_seats`,
    is rejected with `ERR_RECITAL_SOLD_OUT`."
    PRD §3.8: "when `seats_sold` reaches `total_seats` the system flips it to `SOLD_OUT`."

    Complement (the X+1 attempt over the boundary): after the only seat of a total_seats=1 recital
    is held, a second hold would push seats_sold past total_seats -> ERR_RECITAL_SOLD_OUT.

    Design: Difficulty/boundary_precision_check/recital_last_seat_sold_out_boundary
    """
    base = fx.setup_recital_with_held_seat(
        recital_overrides={"total_seats": 1, "ticket_price_cents": 2000, "free_tickets_per_family": 0},
        seat_label="A-1")
    family2 = fx.create_family(email="second@x.com", family_name="Second")
    resp = api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family2["id"], "A-2", base["recital_version"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_RECITAL_SOLD_OUT.value)


# =========================================================================
# Rule 7 — cross_entity_state_dependency (complementary)
# =========================================================================
def test_delinquent_family_cannot_sign_up_for_trip(api):
    """PRD §3.7: "Signing up is gated by family fiscal standing: a `DELINQUENT` family cannot add
    a participant, and the attempt is refused with `ERR_FAMILY_DELINQUENT`."
    PRD §2.9: "while a family is `DELINQUENT`, it cannot confirm new enrollments and cannot sign
    students up for trips."

    Complement entity pair (Family fiscal standing gating a DIFFERENT operation — trip signup):
    a DELINQUENT family's trip participant add is refused with ERR_FAMILY_DELINQUENT.

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_blocked_by_delinquent_family
    """
    del_env = fx.setup_delinquent_family(billing_month="2026-02", advance_to="2026-02-20T00:00:00Z")
    fam = del_env["family"]
    student = del_env["student"]
    # Build a LOCKED team rostering the delinquent family's student, plus a PROPOSED trip.
    team = fx.create_team(min_level="NOVICE", roster_cap=5)
    membership = get_success_data(api.create_membership(
        team["id"], f.create_membership_payload(student["id"], team["version"]), ADMIN_H))
    get_success_data(api.lock_team(team["id"], ADMIN_H))
    trip = get_success_data(api.create_trip(
        team["id"], f.create_trip_payload(chaperone_ratio=4, chaperone_count=1), ADMIN_H))
    resp = api.create_participant(
        trip["id"], f.create_participant_payload(membership["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_FAMILY_DELINQUENT.value)


def test_section_becomes_open_and_enrollable_when_term_opens(api):
    """PRD §3.2: "When its parent term opens, a `SCHEDULED` section transitions to `OPEN` and
    becomes enrollable — this is a system transition guarded on the term: a section opens only
    because its term opened, never independently."
    PRD §3.3: "If the section is `OPEN` with room under effective capacity and the student is
    eligible, the enrollment is confirmed directly."

    Complement (the positive leg of the ClassSection->Term dependency): once the term opens, the
    SCHEDULED section becomes OPEN and an eligible enrollment confirms directly.

    Design: Difficulty/cross_entity_state_dependency/section_open_depends_on_term_open
    """
    term = fx.create_term()
    room = fx.create_room(capacity=20)
    instructor = fx.create_instructor()
    sec = fx.create_section(term["id"], room["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(sec["id"], day_of_week=1, start_minute=600, end_minute=660)
    sec_before = validate_success(api.get_section(sec["id"], ADMIN_H))
    assert sec_before["status"] == "SCHEDULED"
    validate_success(api.open_term(term["id"], ADMIN_H))
    sec_after = validate_success(api.get_section(sec["id"], ADMIN_H))
    assert sec_after["status"] == "OPEN"
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")
    enr = fx.create_enrollment(student["id"], sec["id"])
    assert enr["placement_status"] == "CONFIRMED"


# =========================================================================
# Rule 8 — resource_temporal_overlap (complementary)
# =========================================================================
def test_room_no_conflict_outside_buffer_window(api):
    """PRD §3.2: "a new session **room-conflicts** if, on the same `day_of_week` and in the same
    room, its window from its start up to its end *plus the room's `turnover_buffer_minutes`*
    overlaps the equivalently-buffered window of any other section's session in that room."
    PRD §3.2: "Adding the first `ClassSession` moves it to `SCHEDULED`."

    Complement (the non-conflicting side of the buffered boundary): with a 30-min buffer a
    session 600-660 buffers to 690; a new 690-750 session starts exactly when the buffer ends, so
    [600,690) and [690,780) do not overlap and the add succeeds (section moves to SCHEDULED).

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnover_buffer
    """
    term = fx.create_term()
    room = fx.create_room(capacity=20, turnover_buffer_minutes=30)
    inst_a = fx.create_instructor(email="bufok_a@x.com")
    inst_b = fx.create_instructor(email="bufok_b@x.com")
    secA = fx.create_section(term["id"], room["id"], inst_a["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room["id"], inst_b["id"], discipline="TAP")
    session = validate_success(api.create_session(secB["id"], f.create_session_payload(
        day_of_week=0, start_minute=690, end_minute=750), ADMIN_H), expected_status=201)
    assert session["start_minute"] == 690
    secB_after = validate_success(api.get_section(secB["id"], ADMIN_H))
    assert secB_after["status"] == "SCHEDULED"


def test_instructor_no_conflict_on_adjacent_touching_sessions(api):
    """PRD §3.2: "a new session **instructor-conflicts** if, on the same `day_of_week`, its plain
    start-to-end window (no buffer) overlaps another session of the same instructor."
    PRD §3.2: "Adding the first `ClassSession` moves it to `SCHEDULED`."

    Complement (the non-overlapping side, no buffer): the same instructor's 600-660 and a touching
    660-720 session (half-open windows touch but do not overlap) in different rooms do not conflict,
    so the second session is accepted.

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_no_buffer
    """
    term = fx.create_term()
    room1 = fx.create_room(capacity=20, turnover_buffer_minutes=0)
    room2 = fx.create_room(capacity=20, turnover_buffer_minutes=0)
    instructor = fx.create_instructor(email="adj@x.com")
    secA = fx.create_section(term["id"], room1["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room2["id"], instructor["id"], discipline="TAP")
    session = validate_success(api.create_session(secB["id"], f.create_session_payload(
        day_of_week=0, start_minute=660, end_minute=720), ADMIN_H), expected_status=201)
    assert session["start_minute"] == 660


# =========================================================================
# Rule 9 — compensating_invariant (complementary)
# =========================================================================
def test_submitted_costume_order_folds_fee_into_open_invoice(api):
    """PRD §3.6: "Each submitted order moves from `DRAFT` to `SUBMITTED`, its pinned `price_cents`
    is folded as a fee line into its family's current open invoice (the invoice's `fees_cents`
    increases by that amount and its amount due is recomputed), and the costume moves to
    `ORDERED`."

    Complement to the cancel-conservation test, asserting the forward leg of the conserved
    quantity: submitting the order raises the OPEN invoice's fees_cents from 0 to 4500 and the
    costume becomes ORDERED.

    Design: Difficulty/compensating_invariant/costume_order_cancel_conserves_family_money
    """
    env = fx.setup_confirmed_enrollment(section_overrides={"discipline": "BALLET",
                                                           "monthly_tuition_cents": 9000})
    invoice = fx.generate_invoice(env["family"]["id"], env["term"]["id"], "2026-02")
    assert invoice["fees_cents"] == 0
    costume = get_success_data(api.create_costume(
        env["section"]["id"],
        f.create_costume_payload(unit_price_cents=4500, rush_surcharge_cents=1500,
                                 size_window_close_date="2026-05-01"), ADMIN_H))
    get_success_data(api.create_costume_order(
        f.create_costume_order_payload(costume["id"], env["enrollment"]["id"]), ADMIN_H))
    costume_after = validate_success(api.submit_costume_order(costume["id"], ADMIN_H))
    assert costume_after["status"] == "ORDERED"
    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    assert invoice_after["fees_cents"] == 4500


def test_held_seat_release_returns_recital_to_on_sale(api):
    """PRD §3.8: "A held seat may be released by the holding family back to inventory, moving it
    to the terminal `RELEASED`, decrementing the recital's `seats_sold`, returning a `SOLD_OUT`
    recital to `ON_SALE`, and recomputing the family's complimentary allotment for the freed slot."

    Complement (the HELD->RELEASED leg of inventory conservation, no purchase): holding the only
    seat of a total_seats=1 recital makes it SOLD_OUT; releasing the held seat returns seats_sold
    to 0 and the recital to ON_SALE (no money refund since it was only held).

    Design: Difficulty/compensating_invariant/seat_release_conserves_recital_inventory
    """
    base = fx.setup_recital_with_held_seat(
        recital_overrides={"total_seats": 1, "ticket_price_cents": 2000, "free_tickets_per_family": 0},
        seat_label="A-1")
    recital_sold = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_sold["status"] == "SOLD_OUT"
    seat_after = validate_success(api.release_seat(base["seat"]["id"], ADMIN_H))
    assert seat_after["status"] == "RELEASED"
    recital_after = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_after["seats_sold"] == 0
    assert recital_after["status"] == "ON_SALE"
