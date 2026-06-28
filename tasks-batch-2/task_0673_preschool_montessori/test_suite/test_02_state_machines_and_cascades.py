"""Application revision loop, parallel enrollment dimensions, withdrawal/refund cascades,
and compensating invariants (PRD §3.2, §3.5, §3.7, §3.9).

Each test translates exactly one design-index instance.
"""
from test_helpers import (
    validate_success, get_success_data,
    accept_offer_payload, create_refund_request_payload,
    set_clock, create_tier, create_classroom, create_room_with_staff, assign_staff,
    create_student, enroll_child, application_under_review, application_waitlisted,
    application_offered, capture_deposit, capture_installment,
    setup_enrolled_child, setup_withdrawn_with_payments,
    assert_refund_conservation,
    make_parent_headers, TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── non_linear_state_machine / application_revision_cycle ─────────────────────

def test_resubmit_returns_application_to_under_review(api):
    """PRD §3.2: "the family then revises and resubmits, which moves it
    CHANGES_REQUESTED → UNDER_REVIEW and closes one turn of the revision cycle."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_changes_requested
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room = create_classroom(name="Primary E", level="PRIMARY", capacity=5)
    student = create_student(parent_user_id="parent-1")
    app = application_under_review(student["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    validate_success(api.request_changes(app["id"], REGISTRAR), 200)

    resubmitted = validate_success(api.resubmit(app["id"], make_parent_headers("parent-1")), 200)
    assert resubmitted["status"] == "UNDER_REVIEW", f"got {resubmitted['status']}"


def test_revision_cycle_version_increments_each_hop(api):
    """PRD §3.2: "This loop — UNDER_REVIEW → CHANGES_REQUESTED → UNDER_REVIEW — may turn as
    many times as needed. Each of these transitions increments the application's version by
    one."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_changes_requested
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room = create_classroom(name="Primary E2", level="PRIMARY", capacity=5)
    student = create_student(parent_user_id="parent-1")
    app = application_under_review(student["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    # submit(v1) -> start-review(v2) -> request-changes(v3) -> resubmit(v4).
    validate_success(api.request_changes(app["id"], REGISTRAR), 200)
    resubmitted = validate_success(api.resubmit(app["id"], make_parent_headers("parent-1")), 200)
    assert resubmitted["version"] == 4, f"got version {resubmitted['version']}"


# ─── non_linear_state_machine / enrollment_parallel_placement_and_billing ──────

def test_leave_changes_placement_only_billing_unchanged(api):
    """PRD §3.5: "An enrollment carries two independent state dimensions that evolve
    separately on the same record: a placement dimension and a billing dimension."
    PRD §3.5: "A registrar may move a placed child onto leave, PLACED → ON_LEAVE, which
    frees the seat".

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_placement_and_billing_dimensions
    """
    room, tier, student, enr = setup_enrolled_child(
        base_annual_cents=1_000_000, deposit_pct=0.10, installments=10)
    # Deposit advances billing to ACTIVE.
    capture_deposit(enr["id"], 100_000)
    enr = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))
    assert enr["billing_status"] == "ACTIVE"

    left = validate_success(api.leave(enr["id"], REGISTRAR), 200)
    assert left["placement_status"] == "ON_LEAVE", f"got {left['placement_status']}"
    assert left["billing_status"] == "ACTIVE", (
        f"billing must be unchanged by placement transition, got {left['billing_status']}")


def test_deposit_advances_billing_placement_unchanged(api):
    """PRD §3.7: "When a deposit of exactly deposit_cents is captured while the enrollment is
    DEPOSIT_DUE, the billing dimension advances DEPOSIT_DUE → ACTIVE."
    PRD §3.5: "An enrollment carries two independent state dimensions that evolve separately
    on the same record: a placement dimension and a billing dimension."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_placement_and_billing_dimensions
    """
    room, tier, student, enr = setup_enrolled_child(
        base_annual_cents=1_000_000, deposit_pct=0.10, installments=10)
    assert enr["placement_status"] == "PLACED"
    assert enr["billing_status"] == "DEPOSIT_DUE"

    capture_deposit(enr["id"], 100_000)
    enr = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))
    assert enr["billing_status"] == "ACTIVE", f"got {enr['billing_status']}"
    assert enr["placement_status"] == "PLACED", (
        f"placement must be unchanged by deposit, got {enr['placement_status']}")


# ─── transitive_cascade / withdraw_frees_seat_promotes_waitlisted_depth3 ───────

def test_withdraw_frees_seat_promotes_top_waitlisted(api):
    """PRD §3.5: "the freed seat triggers an automatic waitlist promotion: the system
    selects the top-ranked WAITLISTED application for that classroom (using the ranking of
    §3.3) and transitions it WAITLISTED → OFFERED."

    Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlisted_depth3
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1, name="Primary G")

    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enr_a = enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")

    stu_b = create_student(parent_user_id="parent-b", full_name="Child B")
    app_b = application_waitlisted(stu_b["id"], room["id"], tier["id"],
                                   parent_user_id="parent-b")

    # hop1: withdraw frees the seat.
    validate_success(api.withdraw(enr_a["id"], REGISTRAR), 200)
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["placed_count"] == 0, f"placed_count got {room_after['placed_count']}"

    # hop2/hop3: top waitlisted application promoted to OFFERED.
    app_b_after = get_success_data(api.get_application(app_b["id"], REGISTRAR))
    assert app_b_after["status"] == "OFFERED", f"got {app_b_after['status']}"


def test_withdraw_sets_linked_application_withdrawn(api):
    """PRD §3.5: "the application linked through the withdrawing enrollment's application_id
    has its status set to WITHDRAWN, and the enrollment's own version is incremented."

    Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlisted_depth3
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1, name="Primary G2")

    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    # Build via offered application so we can read its id afterward.
    app_a = application_offered(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")
    enr_a = get_success_data(api.accept_offer(
        app_a["id"], accept_offer_payload("2026-09-01T00:00:00Z"),
        make_parent_headers("parent-a")))

    validate_success(api.withdraw(enr_a["id"], REGISTRAR), 200)
    app_a_after = get_success_data(api.get_application(app_a["id"], REGISTRAR))
    assert app_a_after["status"] == "WITHDRAWN", f"got {app_a_after['status']}"


# ─── transitive_cascade / refund_pay_marks_payments_refunded_depth2 ────────────

def test_refund_pay_recomputes_paid_to_date(api):
    """PRD §3.9: "It then recomputes the enrollment's paid_to_date_cents so that the
    relationship between paid_to_date_cents and refund_cents is preserved (the new
    paid-to-date equals the prior paid-to-date less the refunded amount)".

    Design: Difficulty/transitive_cascade/refund_pay_marks_payments_refunded_depth2
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000)
    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    assert rr["refund_cents"] == 300000
    validate_success(api.approve_refund(rr["id"], REGISTRAR), 200)

    validate_success(api.pay_refund(rr["id"], REGISTRAR), 200)
    enr_after = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))
    # 700000 paid - 300000 refunded = 400000.
    assert enr_after["paid_to_date_cents"] == 400000, (
        f"got {enr_after['paid_to_date_cents']}")


def test_refund_pay_settles_billing(api):
    """PRD §3.9: "transitions the enrollment's billing dimension to SETTLED".
    PRD §3.9: "an enrollment whose placement_status is WITHDRAWN and whose billing_status is
    either ACTIVE or PAST_DUE advances to SETTLED when its refund request reaches PAID."

    Design: Difficulty/transitive_cascade/refund_pay_marks_payments_refunded_depth2
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000)
    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    validate_success(api.approve_refund(rr["id"], REGISTRAR), 200)

    validate_success(api.pay_refund(rr["id"], REGISTRAR), 200)
    enr_after = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))
    assert enr_after["billing_status"] == "SETTLED", f"got {enr_after['billing_status']}"


# ─── compensating_invariant / refund_pay_conserves_money ───────────────────────

def test_refund_pay_conserves_money_no_drift(api):
    """PRD §3.9: "It then recomputes the enrollment's paid_to_date_cents so that the
    relationship between paid_to_date_cents and refund_cents is preserved (the new
    paid-to-date equals the prior paid-to-date less the refunded amount)".

    Design: Difficulty/compensating_invariant/refund_pay_conserves_money_paid_minus_refunded
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000)
    paid_before = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))["paid_to_date_cents"]
    assert paid_before == 700000

    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    validate_success(api.approve_refund(rr["id"], REGISTRAR), 200)
    validate_success(api.pay_refund(rr["id"], REGISTRAR), 200)

    paid_after = get_success_data(api.get_enrollment(enr["id"], REGISTRAR))["paid_to_date_cents"]
    assert_refund_conservation(paid_before, paid_after, rr["refund_cents"])
    assert paid_after == 400000


def test_refund_request_refund_cents_value(api):
    """PRD §3.8: "the refund owed to the family — the request's refund_cents — is the
    enrollment's paid_to_date_cents minus the earned amount, but never less than zero."

    Design: Difficulty/compensating_invariant/refund_pay_conserves_money_paid_minus_refunded
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000)
    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    # earned 400000, paid 700000 => refund 300000.
    assert rr["refund_cents"] == 300000, f"got {rr['refund_cents']}"


# ─── compensating_invariant / leave_then_return_conserves_placed_count ─────────

def test_leave_then_return_conserves_placed_count(api):
    """PRD §3.5: "A registrar may return a child from leave, ON_LEAVE → PLACED, but only if
    the room currently has a free seat (its placed_count is below capacity) and is
    COMPLIANT; a successful return increments the room's placed_count, recomputes its
    compliance_status, and increments the enrollment's version."

    Design: Difficulty/compensating_invariant/leave_then_return_conserves_classroom_placed_count
    """
    room, tier, student, enr = setup_enrolled_child(capacity=5)
    room_before = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_before["placed_count"] == 1

    validate_success(api.leave(enr["id"], REGISTRAR), 200)
    validate_success(api.return_from_leave(enr["id"], REGISTRAR), 200)
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["placed_count"] == 1, (
        f"seat count must be conserved, got {room_after['placed_count']}")


def test_leave_then_return_room_compliant(api):
    """PRD §2.8: "a room whose placed_count exactly equals the level cap times its staff
    count is COMPLIANT while one more placed child than that tips it to OVER_RATIO."
    PRD §3.5: "a successful return increments the room's placed_count, recomputes its
    compliance_status".

    Design: Difficulty/compensating_invariant/leave_then_return_conserves_classroom_placed_count
    """
    room, tier, student, enr = setup_enrolled_child(capacity=5)
    validate_success(api.leave(enr["id"], REGISTRAR), 200)
    validate_success(api.return_from_leave(enr["id"], REGISTRAR), 200)
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    # 1 placed, 1 PRIMARY staff (cap 10): required_staff = ceil(1/10) = 1 <= 1 => COMPLIANT.
    assert room_after["compliance_status"] == "COMPLIANT", (
        f"got {room_after['compliance_status']}")
