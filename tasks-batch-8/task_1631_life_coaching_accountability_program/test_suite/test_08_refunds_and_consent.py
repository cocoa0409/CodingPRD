"""Refund variants and adjudication cascades, testimonial consent cycles,
and coach-ethics cascade depth."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    TIER_MEM12,
    activate_enrollment,
    add_member,
    book_session,
    complete_session,
    complete_sessions_for_enrollment,
    create_client,
    create_coach,
    create_fit_approved_enrollment,
    create_open_cohort,
    create_testimonial,
    create_tier,
    get_cohort,
    get_enrollment,
    get_membership,
    get_session,
    get_success_data,
    make_client_headers,
    make_coach_headers,
    set_clock,
    setup_active_enrollment,
    setup_coach_pair,
    setup_multi_client_active_enrollments,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["practice_manager_headers"]


def _file_refund(api, enrollment_id: str, client: dict) -> dict:
    resp = api.create_refund_request(
        {"enrollment_id": enrollment_id}, make_client_headers(client["id"]))
    return validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / refund_cooling_off_vs_pro_rata_same_data
# ---------------------------------------------------------------------------

def _setup_paid_enrollment_with_two_consumed_sessions(api):
    """ACTIVE-since-2026-08-03 PKG-8 enrollment paid in full (80000) with
    exactly 2 COMPLETED sessions (2026-08-04, 2026-08-05)."""
    ctx = setup_active_enrollment()
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    complete_sessions_for_enrollment(enrollment["id"], client, coach_a, count=2)
    return ctx


def test_refund_on_day_fourteen_uses_cooling_off_basis(api):
    """PRD §3.9: "Fourteen days or fewer — day fourteen itself included —
    selects the `COOLING_OFF` basis: the refund is everything actually paid
    so far, minus a flat $75.00 fee for each session already consumed,
    indifferent to the tier's list price."

    Design: Difficulty/dual_variant_calc/refund_cooling_off_vs_pro_rata_same_data
    """
    ctx = _setup_paid_enrollment_with_two_consumed_sessions(api)
    set_clock("2026-08-17T09:00:00Z")  # day 14 since the 2026-08-03 activation
    rr = _file_refund(api, ctx["enrollment"]["id"], ctx["client"])
    assert rr["basis"] == "COOLING_OFF"
    assert rr["amount_cents"] == 65000, \
        "80000 paid - 2 consumed sessions x 7500 = 65000"


def test_refund_on_day_fifteen_uses_pro_rata_basis(api):
    """PRD §3.9: "Fifteen days or more selects `PRO_RATA`, which works from
    the pinned list-price basis rather than from receipts."
    PRD §3.9: "For a `PACKAGE`, the value per remaining session is the
    pinned price divided by the tier's granted session count, rounded down to
    a whole cent."
    PRD §3.9: "The final `amount_cents` is the capped quote minus a flat
    $50.00 administrative fee, floored at zero: a negative result refunds
    nothing."

    Design: Difficulty/dual_variant_calc/refund_cooling_off_vs_pro_rata_same_data
    """
    ctx = _setup_paid_enrollment_with_two_consumed_sessions(api)
    set_clock("2026-08-18T09:00:00Z")  # day 15 -> PRO_RATA
    rr = _file_refund(api, ctx["enrollment"]["id"], ctx["client"])
    assert rr["basis"] == "PRO_RATA"
    # PACKAGE: 80000/8 = 10000 per remaining session; 6 remaining -> 60000;
    # min(60000, 80000) - 5000 = 55000.
    assert rr["amount_cents"] == 55000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / pro_rata_session_value_tiered_branch
# ---------------------------------------------------------------------------

def _setup_membership_enrollment(api):
    """MEM-12 membership enrollment ACTIVE since 2026-08-03, paid in full
    (120000), with 3 COMPLETED sessions (08-04/05/06)."""
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier(**TIER_MEM12)
    enrollment = create_fit_approved_enrollment(client, coach_a, coach_b, tier)
    enrollment = activate_enrollment(enrollment["id"], "2026-08-03T00:00:00Z")
    complete_sessions_for_enrollment(enrollment["id"], client, coach_a, count=3)
    return {"coach_a": coach_a, "client": client, "tier": tier,
            "enrollment": enrollment}


def test_pro_rata_refund_membership_branch_double_floor(api):
    """PRD §3.9: "For a `MEMBERSHIP`, time prorates first: the pinned price
    is multiplied by the whole days left in the program window — the window's
    closing instant minus the current time, never below zero — and divided by
    the window's total `duration_days`, rounding down to a whole cent; that
    time-prorated figure is then divided by the number of unconsumed sessions
    — a divisor treated as at least one even when every session has been
    consumed — again rounding down."
    PRD §3.9: "The gross quote is the per-remaining-session value multiplied
    by the count of unconsumed sessions, that count being the tier's granted
    sessions minus `sessions_consumed`, and the quote is capped at
    `paid_cents`."
    PRD §3.9: "The final `amount_cents` is the capped quote minus a flat
    $50.00 administrative fee, floored at zero: a negative result refunds
    nothing."

    Design: Difficulty/combinatorial_formula/pro_rata_session_value_tiered_branch
    """
    ctx = _setup_membership_enrollment(api)
    # Day 42 by date arithmetic (2026-08-03 -> 2026-09-14). PRD §3.9 defines
    # days_left as "the window's closing instant minus the current time":
    # close = activated_at + 84d = 2026-10-26T00:00:00Z; at 09:00 on 09-14
    # the remaining span is 41 days 15 hours -> 41 whole days.
    set_clock("2026-09-14T09:00:00Z")
    rr = _file_refund(api, ctx["enrollment"]["id"], ctx["client"])
    assert rr["basis"] == "PRO_RATA"
    # floor(120000*41/84) = 58571; floor(58571/9) = 6507; 6507*9 = 58563;
    # min(58563, 120000) - 5000 = 53563.
    assert rr["amount_cents"] == 53563


def test_pro_rata_refund_package_branch_flat_per_session(api):
    """PRD §3.9: "For a `PACKAGE`, the value per remaining session is the
    pinned price divided by the tier's granted session count, rounded down to
    a whole cent." The PACKAGE branch has no time proration, unlike the
    MEMBERSHIP branch.

    Design: Difficulty/combinatorial_formula/pro_rata_session_value_tiered_branch
    """
    ctx = _setup_paid_enrollment_with_two_consumed_sessions(api)
    set_clock("2026-09-01T09:00:00Z")  # day 29 -> PRO_RATA on a PACKAGE tier
    rr = _file_refund(api, ctx["enrollment"]["id"], ctx["client"])
    assert rr["basis"] == "PRO_RATA"
    # floor(80000/8) = 10000; 6 remaining -> 60000; -5000 -> 55000.
    assert rr["amount_cents"] == 55000


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / testimonial_consent_cycle_revoke_reconsent
# ---------------------------------------------------------------------------

def _setup_testimonial(api):
    ctx = setup_active_enrollment()
    testi = create_testimonial(ctx["enrollment"]["id"], ctx["client"])
    return ctx, testi


def test_revoke_consent_hides_publication_compensation(api):
    """PRD §3.8: "Consent is revocable. The client revokes a `CONSENTED`
    testimonial, moving consent to `REVOKED` while publication compensates by
    dropping back to `HIDDEN` in the same act."

    Design: Difficulty/non_linear_state_machine/testimonial_consent_cycle_revoke_reconsent
    """
    ctx, testi = _setup_testimonial(api)
    client_h = make_client_headers(ctx["client"]["id"])
    validate_success(api.consent_testimonial(testi["id"], client_h))
    resp = api.publish_testimonial(testi["id"], PM)
    published = validate_success(resp)
    assert published["publish_status"] == "PUBLISHED"
    resp = api.revoke_consent_testimonial(testi["id"], client_h)
    data = validate_success(resp)
    assert data["consent_status"] == "REVOKED"
    assert data["publish_status"] == "HIDDEN", \
        "revocation compensates by unpublishing in the same act"


def test_reconsent_after_revoke_does_not_restore_publication(api):
    """PRD §3.8: "Re-consent is allowed from `REVOKED` — consent returns to
    `CONSENTED` — but publication stays `HIDDEN` and must be re-published
    explicitly."

    Design: Difficulty/non_linear_state_machine/testimonial_consent_cycle_revoke_reconsent
    """
    ctx, testi = _setup_testimonial(api)
    client_h = make_client_headers(ctx["client"]["id"])
    validate_success(api.consent_testimonial(testi["id"], client_h))
    validate_success(api.publish_testimonial(testi["id"], PM))
    validate_success(api.revoke_consent_testimonial(testi["id"], client_h))
    resp = api.consent_testimonial(testi["id"], client_h)
    data = validate_success(resp)
    assert data["consent_status"] == "CONSENTED"
    assert data["publish_status"] == "HIDDEN", \
        "re-consent closes the consent cycle without restoring publication"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / coach_ethics_suspension_depth3_cascade
# ---------------------------------------------------------------------------

def _setup_ethics_cascade_scenario(api):
    """Coach A with: one ACTIVE enrollment (client X) holding one SCHEDULED
    session; one OPEN cohort with a second client's ACTIVE membership."""
    ctx = setup_multi_client_active_enrollments(2)
    coach_a = ctx["coach_a"]
    client_x, client_y = ctx["clients"]
    enr_x, enr_y = ctx["enrollments"]
    sess_x = book_session(
        enr_x["id"], client_x, scheduled_start="2026-08-06T10:00:00Z")
    cohort = create_open_cohort(coach_a, capacity=3, title="Momentum Group")
    memb_y = add_member(cohort["id"], enr_y["id"], coach_a)
    return {
        "coach_a": coach_a, "client_x": client_x, "client_y": client_y,
        "enr_x": enr_x, "enr_y": enr_y, "sess_x": sess_x,
        "cohort": cohort, "memb_y": memb_y,
    }


def test_ethics_suspension_cancels_sessions_and_recomputes_enrollments(api):
    """PRD §3.1: "When a coach's ethics posture moves from `ACTIVE` to
    `SUSPENDED`, the coach's scheduled sessions cancel and the affected
    enrollments recompute as under revocation".
    PRD §3.4: "a `CANCELLED` session returns its credit to the pool."

    Design: Difficulty/transitive_cascade/coach_ethics_suspension_depth3_cascade
    """
    ctx = _setup_ethics_cascade_scenario(api)
    resp = api.suspend_ethics(ctx["coach_a"]["id"], PM)
    coach = validate_success(resp)
    assert coach["ethics_status"] == "SUSPENDED"
    assert get_session(ctx["sess_x"]["id"])["session_status"] == "CANCELLED"
    data = get_enrollment(ctx["enr_x"]["id"])
    assert data["sessions_remaining"] == 8, \
        "the cascade-cancelled session returns its credit to the enrollment"


def test_ethics_suspension_cancels_open_cohorts_and_memberships(api):
    """PRD §3.1: "additionally every cohort the coach facilitates that stands
    `OPEN` or `IN_PROGRESS` is `CANCELLED`, with each such cohort's `ACTIVE`
    and `WAITLISTED` memberships moved to `REMOVED`."

    Design: Difficulty/transitive_cascade/coach_ethics_suspension_depth3_cascade
    """
    ctx = _setup_ethics_cascade_scenario(api)
    validate_success(api.suspend_ethics(ctx["coach_a"]["id"], PM))
    assert get_cohort(ctx["cohort"]["id"])["cohort_status"] == "CANCELLED"
    assert get_membership(
        ctx["cohort"]["id"], ctx["memb_y"]["id"])["member_status"] == "REMOVED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade /
# refund_approval_depth2_cascade_with_waitlist_promotion
# ---------------------------------------------------------------------------

def _setup_refund_cascade_scenario(api):
    """Capacity-2 OPEN cohort (PRD §3.7: "a `capacity` of at least 2"):
    enrollment R ACTIVE member (with one SCHEDULED session), enrollment X the
    second ACTIVE member, enrollment W WAITLISTED; COOLING_OFF refund filed
    for R."""
    ctx = setup_multi_client_active_enrollments(3)
    coach_a = ctx["coach_a"]
    client_r, _client_x, client_w = ctx["clients"]
    enr_r, enr_x, enr_w = ctx["enrollments"]
    sess_r = book_session(
        enr_r["id"], client_r, scheduled_start="2026-08-06T10:00:00Z")
    cohort = create_open_cohort(coach_a, capacity=2, title="Tiny Cohort")
    memb_r = add_member(cohort["id"], enr_r["id"], coach_a)
    add_member(cohort["id"], enr_x["id"], coach_a)
    memb_w = add_member(cohort["id"], enr_w["id"], coach_a)
    assert memb_w["member_status"] == "WAITLISTED"
    set_clock("2026-08-13T09:00:00Z")  # day 10, 0 sessions consumed
    rr = _file_refund(api, enr_r["id"], client_r)
    return {
        "coach_a": coach_a, "client_r": client_r, "client_w": client_w,
        "enr_r": enr_r, "enr_w": enr_w, "sess_r": sess_r, "cohort": cohort,
        "memb_r": memb_r, "memb_w": memb_w, "rr": rr,
    }


def test_refund_approval_refunds_enrollment_and_cancels_sessions(api):
    """PRD §3.9: "Approving a request that stands `PENDING` — against an
    enrollment in `ACTIVE` or `PAUSED` — moves `refund_status` to `APPROVED`
    and cascades: the enrollment's lifecycle becomes `REFUNDED`, its
    `refunded_cents`, the sum of approved refund amounts, recomputes, and its
    `version` advances; every `SCHEDULED` session cancels".

    Design: Difficulty/transitive_cascade/refund_approval_depth2_cascade_with_waitlist_promotion
    """
    ctx = _setup_refund_cascade_scenario(api)
    assert ctx["rr"]["amount_cents"] == 80000, \
        "COOLING_OFF with 0 consumed sessions refunds everything paid"
    resp = api.approve_refund_request(ctx["rr"]["id"], PM)
    rr = validate_success(resp)
    assert rr["refund_status"] == "APPROVED"
    assert get_enrollment(ctx["enr_r"]["id"])["lifecycle_status"] == "REFUNDED"
    assert get_session(ctx["sess_r"]["id"])["session_status"] == "CANCELLED"


def test_refund_approval_removes_membership_and_promotes_waitlist(api):
    """PRD §3.9: "its cohort memberships move to `REMOVED`, firing the
    waitlist promotion of §3.7 on each affected cohort."
    PRD §3.7: "exactly one `WAITLISTED` member promotes to `ACTIVE`: the
    earliest `joined_at` wins".

    Design: Difficulty/transitive_cascade/refund_approval_depth2_cascade_with_waitlist_promotion
    """
    ctx = _setup_refund_cascade_scenario(api)
    validate_success(api.approve_refund_request(ctx["rr"]["id"], PM))
    cohort_id = ctx["cohort"]["id"]
    assert get_membership(cohort_id, ctx["memb_r"]["id"])["member_status"] == "REMOVED"
    assert get_membership(cohort_id, ctx["memb_w"]["id"])["member_status"] == "ACTIVE", \
        "the waitlisted member promotes into the freed seat"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant /
# installment_schedule_total_conservation_across_payment_and_refund
# ---------------------------------------------------------------------------

def _setup_partially_paid_refunded_enrollment(api):
    """3-installment enrollment (schedule [26666, 26666, 26668]); only
    installment 1 paid at activation; PRO_RATA refund filed on day 17 with
    0 sessions consumed, then approved."""
    ctx = setup_active_enrollment(installment_count=3)
    set_clock("2026-08-20T09:00:00Z")  # day 17 -> PRO_RATA
    rr = _file_refund(api, ctx["enrollment"]["id"], ctx["client"])
    return ctx, rr


def test_pro_rata_refund_capped_at_partial_paid_amount(api):
    """PRD §3.9: "The gross quote is the per-remaining-session value
    multiplied by the count of unconsumed sessions, that count being the
    tier's granted sessions minus `sessions_consumed`, and the quote is
    capped at `paid_cents`."
    PRD §3.9: "The final `amount_cents` is the capped quote minus a flat
    $50.00 administrative fee, floored at zero: a negative result refunds
    nothing."

    Design: Difficulty/compensating_invariant/installment_schedule_total_conservation_across_payment_and_refund
    """
    ctx, rr = _setup_partially_paid_refunded_enrollment(api)
    # PACKAGE gross quote: floor(80000/8) * 8 = 80000, capped at paid 26666;
    # minus 5000 -> 21666.
    assert rr["basis"] == "PRO_RATA"
    assert rr["amount_cents"] == 21666
    validate_success(api.approve_refund_request(rr["id"], PM))
    data = get_enrollment(ctx["enrollment"]["id"])
    assert data["paid_cents"] == 26666
    assert data["refunded_cents"] == 21666
    assert data["paid_cents"] - data["refunded_cents"] == 5000, \
        "the retained administrative fee is exactly the 5000-cent gap"


def test_installment_schedule_total_survives_payment_and_refund(api):
    """PRD §2.6: "derived totals are exact integer sums of stored rows."
    PRD §3.3: "the remainder — the price minus the base multiplied by the
    installment count — lands entirely on the final installment, so every
    installment but the last carries exactly the base."

    Design: Difficulty/compensating_invariant/installment_schedule_total_conservation_across_payment_and_refund
    """
    ctx, rr = _setup_partially_paid_refunded_enrollment(api)
    validate_success(api.approve_refund_request(rr["id"], PM))
    resp = api.list_enrollment_installments(ctx["enrollment"]["id"], PM)
    from test_helpers import validate_paginated
    rows, _meta = validate_paginated(resp)
    assert sum(r["amount_cents"] for r in rows) == 80000, \
        "the schedule total equals the pinned price basis across payment and refund"
    assert sorted(r["amount_cents"] for r in rows) == [26666, 26666, 26668]


# ---------------------------------------------------------------------------
# Corner instances.
# ---------------------------------------------------------------------------

def test_refund_on_never_activated_enrollment_rejected(api):
    """PRD §3.9: "Filing is refused with `ERR_REFUND_NOT_ALLOWED` unless the
    enrollment's lifecycle stands `ACTIVE` or `PAUSED`, `activated_at` is
    set, `paid_cents` is greater than zero, and no earlier request for the
    same enrollment was ever `APPROVED`."

    Design: Corner/validations/refund_on_never_activated_enrollment_rejected
    """
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    enrollment = create_fit_approved_enrollment(client, coach_a, coach_b, tier)
    assert enrollment["lifecycle_status"] == "PENDING_PAYMENT"
    resp = api.create_refund_request(
        {"enrollment_id": enrollment["id"]}, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_REFUND_NOT_ALLOWED)


def test_publish_without_consent_returns_invalid_state(api):
    """PRD §3.8: "a `PracticeManager` publishes, moving `publish_status` to
    `PUBLISHED`, only while consent stands `CONSENTED`, publication still
    stands `HIDDEN`, and the linked enrollment's lifecycle is `COMPLETED` or
    `ACTIVE`". PRD §2.11: "Fourth, the target's state must permit the
    operation — booking a session additionally requires the parent enrollment
    to be `ACTIVE`, and a habit check-in requires its goal to be `OPEN` —
    else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/validations/publish_without_consent_returns_invalid_state
    """
    ctx, testi = _setup_testimonial(api)
    assert testi["consent_status"] == "PENDING"
    resp = api.publish_testimonial(testi["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = get_success_data(api.get_testimonial(testi["id"], PM))
    assert data["publish_status"] == "HIDDEN"
