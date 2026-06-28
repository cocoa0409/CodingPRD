"""Corner cases for calculations (ratio constants, aid floor, chronological proration,
waitlist selector), business validations, and action endpoints
(corner-design sections: calculations, validations, endpoints).
PRD §2.8, §3.3, §3.4, §3.6, §3.7, §3.8, §3.12.

Each test translates exactly one corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_classroom_payload, create_tier_payload, create_application_payload,
    create_conference_slot_payload, create_refund_request_payload, accept_offer_payload,
    create_payment_payload,
    set_clock, create_tier, create_classroom, create_room_with_staff, assign_staff,
    create_student, enroll_child, application_under_review, application_waitlisted,
    setup_room_at_placed_count, setup_enrolled_child, setup_withdrawn_with_payments,
    make_parent_headers, make_guide_headers, TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
GUIDE = TEST_USERS["guide_headers"]


# ─── calculations ──────────────────────────────────────

def test_ratio_toddler_boundary_seven_over_ratio(api):
    """PRD §2.8: "a TODDLER room may seat six children per assigned staff member".
    PRD §2.8: "a room whose placed_count exactly equals the level cap times its staff count
    is COMPLIANT while one more placed child than that tips it to OVER_RATIO."

    Design: Corner/calculations/ratio_toddler_boundary_six_compliant_seven_over_ratio
    """
    # 6 placed TODDLER children, 1 staff (cap 6) => COMPLIANT at the exact boundary.
    room, tier, enr_ids = setup_room_at_placed_count(
        level="TODDLER", capacity=10, placed=6, staff=1,
        min_age_months=18, max_age_months=36)
    assert room["placed_count"] == 6
    assert room["compliance_status"] == "COMPLIANT"

    # 7th placement => ceil(7/6)=2 > 1 staff => OVER_RATIO.
    stu = create_student(parent_user_id="tot-7", full_name="Seventh Tot",
                         date_of_birth="2024-09-01T00:00:00Z")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="tot-7")
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["placed_count"] == 7
    assert room_after["compliance_status"] == "OVER_RATIO", (
        f"got {room_after['compliance_status']}")


def test_financial_aid_floor_applied(api):
    """PRD §3.6: "the running figure is multiplied by the quantity one minus that fraction
    and rounded half up to whole cents, and then raised if necessary so that it is never
    less than a floor of 300,000 cents."

    Design: Corner/calculations/financial_aid_floor_applied
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="SMALL", level="PRIMARY", base_annual_cents=400_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1",
                       financial_aid_pct=0.50)
    # 400000 * 0.5 = 200000, clamped up to floor 300000.
    assert enr["net_annual_cents"] == 300000, f"got {enr['net_annual_cents']}"


def test_chronological_proration_rounding(api):
    """PRD §3.8: "The prorated portion is the monthly figure times attended days divided by
    days in the month, rounded half up to whole cents. The earned amount is the retained
    deposit, plus the count of fully earned months times the monthly figure, plus that
    prorated portion."

    Design: Corner/calculations/chronological_proration_rounding_precision
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000,
        program_start_date="2026-09-01T00:00:00Z", clock="2026-09-01T00:00:00Z")
    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "CHRONOLOGICAL"),
        REGISTRAR), 201)
    # deposit 100000 + Sep,Oct full (200000) + Nov prorated round_half_up(100000*20/30)=66667.
    assert rr["earned_cents"] == 366667, f"got {rr['earned_cents']}"
    assert rr["refund_cents"] == 333333, f"got {rr['refund_cents']}"
    assert rr["balance_due_cents"] == 0, f"got {rr['balance_due_cents']}"


def test_waitlist_staff_child_promoted_before_sibling(api):
    """PRD §3.3: "A sibling component adds 1,000 points when the student's
    sibling_of_student_id references a student that itself has an enrollment in placed
    status; otherwise it adds nothing. A staff-child component adds 1,500 points when the
    student's staff_child flag is true".
    PRD §3.3: "It ranks that candidate set by priority_score descending ... The single
    top-ranked candidate is the one promoted."

    Design: Corner/calculations/waitlist_priority_staff_child_beats_sibling
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1)

    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enr_a = enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")

    # B: staff child (1500).
    stu_b = create_student(parent_user_id="parent-b", full_name="Staff Child",
                           staff_child=True)
    app_b = application_waitlisted(stu_b["id"], room["id"], tier["id"],
                                   parent_user_id="parent-b")
    # C: sibling of PLACED child A (1000).
    stu_c = create_student(parent_user_id="parent-a", full_name="Sibling Child",
                           sibling_of_student_id=stu_a["id"])
    app_c = application_waitlisted(stu_c["id"], room["id"], tier["id"],
                                   parent_user_id="parent-a")

    # Free the seat; the higher-priority staff child (B) is promoted.
    validate_success(api.withdraw(enr_a["id"], REGISTRAR), 200)
    app_b_after = get_success_data(api.get_application(app_b["id"], REGISTRAR))
    app_c_after = get_success_data(api.get_application(app_c["id"], REGISTRAR))
    assert app_b_after["status"] == "OFFERED", f"B got {app_b_after['status']}"
    assert app_c_after["status"] == "WAITLISTED", f"C got {app_c_after['status']}"


# ─── validations ───────────────────────────────────────

def test_age_below_min_age_out_of_range(api):
    """PRD §3.3: "the student's age in months, derived from date_of_birth against the
    logical clock, must fall within the room's min_age_months and max_age_months inclusive
    ... A child whose age falls outside the inclusive band is rejected with
    ERR_AGE_OUT_OF_RANGE".

    Design: Corner/validations/age_below_min_returns_age_out_of_range
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1,
                                     min_age_months=36, max_age_months=72)
    # DOB 2025-09-01 against clock 2026-09-01 => 12 months, below min 36.
    student = create_student(parent_user_id="parent-1", full_name="Baby",
                             date_of_birth="2025-09-01T00:00:00Z")
    app = application_under_review(student["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    res = api.offer(app["id"], REGISTRAR)
    validate_error(res, "ERR_AGE_OUT_OF_RANGE", expected_status=422)


def test_tier_level_mismatch_on_application(api):
    """PRD §3.4: "When a registrar waitlists an application ... the classroom's level must
    equal the level of the tier named by the application's tier_id ... a tier whose level
    does not match the classroom's level — or a tier that is no longer active — is rejected
    with ERR_TIER_LEVEL_MISMATCH".

    The mismatch check guards the waitlist (and offer) transition out of UNDER_REVIEW, not
    plain submission, so we drive an UNDER_REVIEW application referencing a TODDLER tier into
    a PRIMARY room through waitlist.

    Design: Corner/validations/tier_level_mismatch_on_application
    """
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1,
                                     min_age_months=36, max_age_months=72)
    tier = create_tier(code="TOD", level="TODDLER", base_annual_cents=800_000,
                       deposit_pct=0.10)
    student = create_student(parent_user_id="parent-1")
    app = application_under_review(student["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    res = api.waitlist(app["id"], REGISTRAR)
    validate_error(res, "ERR_TIER_LEVEL_MISMATCH", expected_status=422)


def test_invalid_interval_end_before_start(api):
    """PRD §3.12: "end_at, an exclusive end instant that must be strictly after start_at. A
    slot whose end_at is not strictly after its start_at is rejected with
    ERR_INVALID_INTERVAL."

    Design: Corner/validations/invalid_interval_end_before_start
    """
    room = get_success_data(api.create_classroom(
        create_classroom_payload(name="Room", level="PRIMARY", capacity=5), COMPLIANCE))
    res = api.create_conference_slot(
        create_conference_slot_payload("guide-1", room["id"],
                                       "2026-10-01T15:30:00Z", "2026-10-01T15:00:00Z"),
        make_guide_headers("guide-1"))
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_refund_not_eligible_when_not_withdrawn(api):
    """PRD §3.8: "A refund request may be created only for an enrollment whose
    placement_status is WITHDRAWN, and only one non-void refund request may exist per
    enrollment; a request that violates either condition is rejected with
    ERR_REFUND_NOT_ELIGIBLE."

    Design: Corner/validations/refund_not_eligible_enrollment_not_withdrawn
    """
    room, tier, student, enr = setup_enrolled_child()
    assert enr["placement_status"] == "PLACED"
    res = api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR)
    validate_error(res, "ERR_REFUND_NOT_ELIGIBLE", expected_status=409)


# ─── endpoints ─────────────────────────────────────────

def test_deposit_payment_advances_billing_active(api):
    """PRD §3.7: "When a deposit of exactly deposit_cents is captured while the enrollment is
    DEPOSIT_DUE, the billing dimension advances DEPOSIT_DUE → ACTIVE."
    PRD §3.7: "The paid_to_date_cents figure is simply the exact sum of the amount_cents of
    all payments on the enrollment that are currently in CAPTURED status".

    Design: Corner/endpoints/deposit_payment_advances_billing_to_active
    """
    room, tier, student, enr = setup_enrolled_child()
    res = api.create_payment(
        create_payment_payload(enr["id"], "DEPOSIT", 100_000), REGISTRAR)
    validate_success(res, 201)
    enr_after = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))
    assert enr_after["billing_status"] == "ACTIVE"
    assert enr_after["paid_to_date_cents"] == 100000


def test_promote_waitlist_manual_endpoint(api):
    """PRD §3.4: "The second route is promotion from the waitlist, WAITLISTED → OFFERED,
    which a registrar may trigger manually for a classroom ...; promotion requires the
    application to be WAITLISTED, the room to be COMPLIANT, the room to have a free seat, and
    the application to be the top-ranked waitlisted candidate for the room."

    Design: Corner/endpoints/promote_waitlist_manual_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    app = application_waitlisted(student["id"], room["id"], tier["id"],
                                 parent_user_id="parent-1")
    res = api.promote_waitlist(room["id"], REGISTRAR)
    promoted = validate_success(res, 200)
    assert promoted["status"] == "OFFERED", f"got {promoted['status']}"
    assert promoted["id"] == app["id"]
