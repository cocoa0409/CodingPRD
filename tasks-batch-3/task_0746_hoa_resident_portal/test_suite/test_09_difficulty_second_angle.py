"""Second-angle tests for each SCAFFOLD_DIFFICULTY_DESIGN instance.

Each instance in the difficulty index deserves at least two tests. This file
carries the second angle — a boundary variant, a different value, or an
orthogonal observable that isolates a distinct aspect of the same rule.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    api_client,
    setup_homeowner_and_property,
    setup_homeowner_property_assessment,
    setup_paid_assessment,
    setup_amenity_and_homeowner,
    setup_property_suspended_via_fined_violation,
    setup_arc_request_submitted,
    setup_arc_request_under_review,
    setup_open_motion,
    setup_board_member,
    setup_fined_violation,
    create_reservation,
    create_amenity,
    create_homeowner,
    create_work_order,
    create_arc_request_payload,
    create_arc_review_payload,
    create_motion_payload,
    create_ballot_payload,
    create_assessment_payload,
    set_clock,
    set_grace_policy,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]
_COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
def test_daily_prorate_full_range_of_included_days(api):
    """PRD §3.2: "the number of included days is the whole-day count from
    `prorate_from` (inclusive) to `billing_period_end` (exclusive), and the
    number of days in the period is the whole-day count from
    `billing_period_start` to `billing_period_end`. The raw prorated amount
    is `monthly_dues_cents` multiplied by included days, then divided by
    days in period; the value written to `amount_due_cents` is that raw
    amount rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/assessment_prorate_full_vs_daily
    """
    # prorate_from = day 25 of a 31-day March period → included_days = 7
    # 30000 * 7 / 31 = 6774.1935... → round half-up → 6774
    _, prop = setup_homeowner_and_property(
        email="hdaily2@example.com", address="2A Daily Ln",
        monthly_dues_cents=30000,
    )
    resp = api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
            prorate_from="2026-03-25T00:00:00Z",
        ),
        _MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["amount_due_cents"] == 6774


def test_delinquency_lenient_excludes_young_assessment_entirely(api):
    """PRD §3.2: "Under the **lenient** variant (in effect whenever
    `grace_policy` is `LENIENT`), the calculation is identical except that
    any assessment whose age is strictly less than 30 days is excluded
    entirely from the summation — its contribution is zero rather than
    weight 1.0."

    Design: Difficulty/dual_variant_calc/delinquency_score_strict_vs_lenient
    """
    set_grace_policy("LENIENT")
    homeowner, prop = setup_homeowner_and_property(
        email="hlen@example.com", address="3B Lenient Ln",
        monthly_dues_cents=30000,
    )
    api.create_assessment(
        create_assessment_payload(
            prop["id"],
            billing_period_start="2026-05-01T00:00:00Z",
            billing_period_end="2026-06-01T00:00:00Z",
            due_date="2026-05-25T00:00:00Z",  # 7-day-old at 2026-06-01
        ),
        _MANAGER,
    )
    set_clock("2026-06-01T00:00:00Z")
    resp = api.get_homeowner(homeowner["id"], _MANAGER)
    data = validate_success(resp)
    # Only one 7-day-old assessment → excluded under LENIENT → score 0
    assert data["delinquency_score"] == 0
    assert data["standing"] == "GOOD_STANDING"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
def test_late_fee_tier4_at_60_days_good_standing(api):
    """PRD §3.2: "and 60 or greater selects tier 4."
    PRD §3.2: "the tier caps are 2500, 5000, 10000, and 25000 cents."
    PRD §3.2: "The tier's base fee is computed by multiplying the outstanding
    amount by that tier's rate (0.02 for tier 1, 0.05 for tier 2, 0.10 for
    tier 3, 0.15 for tier 4)"

    Design: Difficulty/combinatorial_formula/late_fee_tiered_nonlinear_mode_a
    """
    _, _, assessment = setup_homeowner_property_assessment(
        email="ht4@example.com",
        address="4B Tier4 Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    set_clock("2026-06-14T00:00:00Z")  # 60 days past due
    resp = api.get_assessment(assessment["id"], _MANAGER)
    data = validate_success(resp)
    # base = round(30000 * 0.15) = 4500; mult 1.0 = 4500; floor=5000, cap=25000 → 5000
    assert data["late_fee_cents"] == 5000
    # PRD §3.2: "When current_utc advances 60 days or more past due_date and the
    # assessment is still OVERDUE, it further auto-transitions to DELINQUENT." At
    # exactly 60 days overdue the tier-4 fee is stamped at the OVERDUE transition and
    # the same clock advance then carries the assessment on to DELINQUENT.
    assert data["status"] == "DELINQUENT"


def test_arc_fee_sum_then_round_complex_two_reviews(api):
    """PRD §3.4: "A base fee in cents is selected from the request's
    `category`: 2500 for `SIMPLE`, 10000 for `MEDIUM`, and 25000 for
    `COMPLEX`."
    PRD §3.4: "The final fee is the sum of the base fee and all unrounded
    per-review contributions, rounded half-up to a whole cent at the end of
    the summation. This evaluation order — **sum first, then round** — is
    pinned"

    Design: Difficulty/combinatorial_formula/arc_fee_sum_then_round_mode_b
    """
    bm1 = setup_board_member("bmc1@ex.com", "BMC1")
    bm2 = setup_board_member("bmc2@ex.com", "BMC2")
    homeowner, prop = setup_homeowner_and_property(
        email="hcxplx@ex.com", address="5B Cx Ln", monthly_dues_cents=30000,
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="COMPLEX", description="Full rebuild",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_success(resp)
    for bm, w in [(bm1, 1), (bm2, 3)]:
        resp = api.create_arc_review(
            arc["id"],
            create_arc_review_payload(bm["id"], weight=w, verdict="APPROVE"),
            make_board_member_headers(bm["id"]),
        )
        validate_success(resp, expected_status=201)
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(bm1["id"])
    )
    data = validate_success(resp)
    # base=25000; per-review raw = [1*25000*0.10725, 3*25000*0.10725]
    #                              = [2681.25, 8043.75]; sum=10725.0
    # total_raw = 25000 + 10725.0 = 35725.0 → round → 35725
    assert data["fee_cents"] == 35725
    assert data["status"] == "APPROVED"


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
def test_arc_cyclic_revision_second_loop_reaches_count_2(api):
    """PRD §3.4: "otherwise, if at least one current-revision verdict is
    `REVISE` and none is `REJECT`, the request transitions to
    `REVISION_REQUESTED` and `revision_count` is incremented by one"

    Design: Difficulty/non_linear_state_machine/arc_request_cyclic_revision_loop
    """
    board_member, homeowner, prop, arc = setup_arc_request_submitted(
        homeowner_email="hcyc2@ex.com",
        board_email="bmcyc2@ex.com",
        address="6B Cyc Ln",
    )
    for expected_count in (1, 2):
        resp = api.create_arc_review(
            arc["id"],
            create_arc_review_payload(board_member["id"], weight=1, verdict="REVISE"),
            make_board_member_headers(board_member["id"]),
        )
        validate_success(resp, expected_status=201)
        resp = api.finalize_arc_request(
            arc["id"], make_board_member_headers(board_member["id"])
        )
        finalized = validate_success(resp)
        assert finalized["revision_count"] == expected_count
        assert finalized["status"] == "REVISION_REQUESTED"
        # Resubmit for the next iteration (allowed while count < 3).
        resp = api.submit_arc_request(
            arc["id"], make_homeowner_headers(homeowner["id"])
        )
        submitted = validate_success(resp)
        assert submitted["status"] == "SUBMITTED"


def test_work_order_completed_and_paid_terminate_independently(api):
    """PRD §3.8: "The two dimensions may therefore terminate at different
    times: a work order may reach `COMPLETED` on the work axis while still
    `INVOICED` on the payment axis, or reach `PAID` on the payment axis
    while still `IN_PROGRESS` on the work axis."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions
    """
    wo = create_work_order(title="Roof repair", cost_estimate_cents=80000)
    validate_success(api.assign_work_order(
        wo["id"], {"assigned_vendor_id": "v-42"}, _MANAGER
    ))
    validate_success(api.start_work_order(wo["id"], _MANAGER))
    validate_success(api.invoice_work_order(wo["id"], _MANAGER))
    resp = api.mark_paid_work_order(wo["id"], _MANAGER)
    after_paid = validate_success(resp)
    assert after_paid["payment_status"] == "PAID"
    assert after_paid["work_status"] == "IN_PROGRESS"
    resp = api.complete_work_order(wo["id"], _MANAGER)
    after_complete = validate_success(resp)
    assert after_complete["work_status"] == "COMPLETED"
    assert after_complete["payment_status"] == "PAID"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
def test_payment_reversal_before_due_reverts_to_partially_paid(api):
    """PRD §3.2: "If the assessment had been `PAID` and the reversal drops it
    below full, the assessment reverts: to `OVERDUE` when the logical clock
    has already reached or passed `due_date` (at which point `late_fee_cents`
    is re-stamped from the late-fee calculation above), or to
    `PARTIALLY_PAID` when the logical clock is still strictly before
    `due_date`."

    Design: Difficulty/transitive_cascade/payment_reversal_depth_3_cascade
    """
    homeowner, prop, assessment = setup_homeowner_property_assessment(
        email="hpr2@ex.com",
        address="7B Casc Ln",
        monthly_dues_cents=100000,
        due_date="2026-08-15T00:00:00Z",  # far in the future
    )
    # First payment: partial 40000
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 40000, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    partial_payment = validate_success(resp, expected_status=201)
    # Second payment: 60000 → PAID
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 60000, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    full_payment = validate_success(resp, expected_status=201)

    # Reverse the second payment while clock still before due_date (2026-03-01).
    resp = api.reverse_payment(
        full_payment["id"], {"reversal_reason": "Client stop-pay"}, _MANAGER
    )
    validate_success(resp)
    resp = api.get_assessment(assessment["id"], _MANAGER)
    a_state = validate_success(resp)
    assert a_state["status"] == "PARTIALLY_PAID"
    assert a_state["amount_paid_cents"] == 40000


def test_arc_rejected_finalize_does_not_cascade_to_flag_or_workorder(api):
    """PRD §3.4: "On both `APPROVED` and `REJECTED` — but not on
    `REVISION_REQUESTED` — the server stamps `fee_cents` from the
    arc-finalisation calculation described below."
    PRD §3.4: "A `REJECTED` finalise does not trigger these cascades; only
    the fee stamp fires."

    Design: Difficulty/transitive_cascade/arc_approval_depth_2_cascade
    """
    board_member, homeowner, prop, arc = setup_arc_request_under_review(
        homeowner_email="hrej@ex.com",
        board_email="bmrej@ex.com",
        address="8B Rej Ln",
        arc_category="SIMPLE",
        review_verdict="REJECT",
        review_weight=1,
    )
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    data = validate_success(resp)
    assert data["status"] == "REJECTED"

    # compliance_flag stays OPEN (no APPROVED_MOD cascade on REJECTED).
    resp = api.get_property(prop["id"], _MANAGER)
    p = validate_success(resp)
    assert p["compliance_flag"] == "OPEN"

    # No AUTO_ARC work order is created.
    resp = api.list_property_work_orders(prop["id"], _MANAGER)
    wos = validate_success(resp)
    assert len(wos) == 0


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
def test_paid_terminal_state_beats_overpayment_paid_lower_amount(api):
    """PRD §2.8: "The ordering is significant"
    PRD §2.8 (priority 5): "State precondition — the target resource must be
    in a state that permits the requested transition (see §3 for per-entity
    state machines); otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_pay_terminal_wins_state
    """
    homeowner, prop, assessment, _ = setup_paid_assessment(
        email="hprio2@ex.com",
        address="9B Prio Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    # Even a benign 1-cent extra on a PAID assessment gets rejected as state.
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 1, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] != "ERR_OVERPAYMENT"


def test_appeal_safety_within_window_still_rejected_as_non_appealable(api):
    """PRD §3.5: "In addition, a violation with `category` equal to `SAFETY`
    is non-appealable at any point — safety fines never enter the appeal
    branch, and any attempt to appeal one is rejected with
    `ERR_APPEAL_NON_APPEALABLE`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_temporal_appeal_safety_wins_constraint
    """
    homeowner, _, violation = setup_fined_violation(
        homeowner_email="hs2@ex.com",
        address="10B Safety Ln",
        category="SAFETY",
        fine_amount_cents=25000,
        fine_at_iso="2026-03-05T00:00:00Z",
    )
    # Well within the 14-day window: SAFETY still rejects.
    set_clock("2026-03-10T00:00:00Z")
    resp = api.appeal_violation(
        violation["id"], make_homeowner_headers(homeowner["id"])
    )
    err = validate_error(resp, ApiErrorId.ERR_APPEAL_NON_APPEALABLE)
    assert err["error_id"] != "ERR_APPEAL_WINDOW_EXPIRED"


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
def test_late_fee_tier_boundary_at_days_13_vs_14(api):
    """PRD §3.2: "A tier is chosen from days overdue against the boundaries
    14, 30, and 60 days: days overdue at least 1 and strictly less than 14
    selects tier 1, at least 14 and strictly less than 30 selects tier 2"
    PRD §3.2: "The tier's base fee is computed by multiplying the outstanding
    amount by that tier's rate (0.02 for tier 1, 0.05 for tier 2"
    PRD §3.2: "The tier floors are 1000, 1000, 2500, and 5000 cents for tiers
    1 through 4 respectively"

    Design: Difficulty/boundary_precision_check/late_fee_tier_boundary_days_30_vs_29
    """
    _, _, a13 = setup_homeowner_property_assessment(
        email="h13@ex.com",
        address="13 Boundary Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    _, prop14 = setup_homeowner_and_property(
        email="h14@ex.com", address="14 Boundary Ln", monthly_dues_cents=30000
    )
    set_clock("2026-04-28T00:00:00Z")  # 13 days past due
    resp = api.get_assessment(a13["id"], _MANAGER)
    d13 = validate_success(resp)
    # Now create the 14-day assessment.
    resp = api.create_assessment(
        create_assessment_payload(
            prop14["id"],
            billing_period_start="2026-03-01T00:00:00Z",
            billing_period_end="2026-04-01T00:00:00Z",
            due_date="2026-04-15T00:00:00Z",
        ),
        _MANAGER,
    )
    a14 = validate_success(resp, expected_status=201)
    set_clock("2026-04-29T00:00:00Z")  # 14 days past due
    resp = api.get_assessment(a14["id"], _MANAGER)
    d14 = validate_success(resp)
    # 13 days = tier 1: base=round(30000*0.02)=600, floor=1000, cap=2500 → 1000
    # 14 days = tier 2: base=round(30000*0.05)=1500, floor=1000, cap=5000 → 1500
    assert d13["late_fee_cents"] == 1000
    assert d14["late_fee_cents"] == 1500


def test_amenity_capacity_full_utilization_still_accepted(api):
    """PRD §3.6: "The candidate is accepted when concurrent guests at peak is
    at most the amenity's `capacity`; equality is accepted"

    Design: Difficulty/boundary_precision_check/amenity_capacity_boundary_equal_vs_over
    """
    homeowner = create_homeowner("hcap2@ex.com", "H Cap2")
    amenity = create_amenity("Yoga", capacity=8)
    # First 8-guest reservation fills capacity exactly.
    r1 = create_reservation(
        amenity["id"], homeowner["id"],
        "2026-03-11T09:00:00Z", "2026-03-11T11:00:00Z", 8,
    )
    assert r1["status"] == "BOOKED"
    # Any additional overlapping guest → peak 9 > 8 → rejected.
    resp = api.create_amenity_reservation(
        {"amenity_id": amenity["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-11T10:00:00Z", "end_ts": "2026-03-11T12:00:00Z",
         "guest_count": 1},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
def test_arc_submit_succeeds_when_property_compliance_flag_open(api):
    """PRD §3.4: "Moving a request from `DRAFT` to `SUBMITTED` succeeds only
    when the target property's `compliance_flag` is not `SUSPENDED` and the
    submitter's `standing` is not `DELINQUENT`."

    Design: Difficulty/cross_entity_state_dependency/arc_submit_blocked_on_property_suspended
    """
    # Positive case: compliance_flag=OPEN and homeowner=GOOD_STANDING → submit ok
    homeowner, prop = setup_homeowner_and_property(
        email="hops@ex.com", address="11B Ops Ln"
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="SIMPLE", description="Paint",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    submitted = validate_success(resp)
    assert submitted["status"] == "SUBMITTED"


def test_amenity_reservation_succeeds_when_homeowner_booking_allowed(api):
    """PRD §3.6: "A reservation may not be created while the acting
    homeowner's `booking_privilege` is `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/amenity_reservation_blocked_on_homeowner_frozen
    """
    # Positive complement: fresh homeowner (ALLOWED) can create reservation.
    homeowner = create_homeowner("hallow@ex.com", "H Allow")
    amenity = create_amenity("Lounge", capacity=8)
    resp = api.create_amenity_reservation(
        {"amenity_id": amenity["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T10:00:00Z", "end_ts": "2026-03-20T12:00:00Z",
         "guest_count": 3},
        make_homeowner_headers(homeowner["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
def test_amenity_reservations_within_capacity_and_overlap_stack(api):
    """PRD §3.6: "It then computes the peak concurrent guest count: for each
    candidate boundary `t` — a value drawn from the set consisting of the
    candidate's own `start_ts` together with every overlapping reservation's
    `start_ts` — the server sums `guest_count` across every overlapping
    reservation whose `start_ts` is at or before `t` and whose `end_ts` is
    strictly after `t`, and adds the candidate's own `guest_count`."

    Design: Difficulty/resource_temporal_overlap/amenity_half_open_capacity_aggregation
    """
    homeowner = create_homeowner("hstck@ex.com", "H Stack")
    amenity = create_amenity("Court", capacity=10)
    # Three stacking reservations with combined peak within capacity.
    create_reservation(
        amenity["id"], homeowner["id"],
        "2026-03-20T10:00:00Z", "2026-03-20T12:00:00Z", 3,
    )
    create_reservation(
        amenity["id"], homeowner["id"],
        "2026-03-20T11:00:00Z", "2026-03-20T13:00:00Z", 3,
    )
    resp = api.create_amenity_reservation(
        {"amenity_id": amenity["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T11:30:00Z", "end_ts": "2026-03-20T12:30:00Z",
         "guest_count": 4},
        make_homeowner_headers(homeowner["id"]),
    )
    # Peak at 11:30: 3 + 3 + 4 = 10 == capacity → accepted.
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED"


def test_motion_window_conflict_from_before_first_motion_start(api):
    """PRD §3.7: "within any single category, no two `OPEN` motions may have
    voting windows within 24 hours of one another (that is, a new motion is
    rejected with `ERR_MOTION_WINDOW_CONFLICT` if any existing `OPEN` motion
    of the same category has its own voting window overlapping the interval
    that extends the new motion's voting window by 24 hours on each side)."

    Design: Difficulty/resource_temporal_overlap/motion_window_24h_buffer_conflict
    """
    board_member, _ = setup_open_motion(
        board_email="bmm3@ex.com",
        title="Budget C", category="BUDGET",
        voting_window_start="2026-04-10T00:00:00Z",
        voting_window_end="2026-04-15T00:00:00Z",
        eligible_voter_count=10, quorum_pct=50,
    )
    # Second motion ending 12h before first starts (within 24h buffer).
    resp = api.create_motion(
        create_motion_payload(
            title="Budget D", description="Budget D",
            category="BUDGET",
            voting_window_start="2026-04-05T00:00:00Z",
            voting_window_end="2026-04-09T12:00:00Z",
            eligible_voter_count=10, quorum_pct=50,
        ),
        make_board_member_headers(board_member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MOTION_WINDOW_CONFLICT)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
def test_payment_reverse_status_flips_and_reversal_reason_stamped(api):
    """PRD §3.2: "The manager may reverse a `POSTED` payment by supplying a
    `reversal_reason`. Reversal flips the payment's `status` to `REVERSED`,
    stamps `reversal_reason`, and reduces the target assessment's
    `amount_paid_cents` by the payment's `amount_cents`."

    Design: Difficulty/compensating_invariant/payment_reverse_restores_outstanding_money_conservation
    """
    homeowner, prop, assessment, payment = setup_paid_assessment(
        email="hinvB@ex.com",
        address="13B Inv Ln",
        monthly_dues_cents=30000,
        due_date="2026-05-15T00:00:00Z",
    )
    resp = api.reverse_payment(
        payment["id"], {"reversal_reason": "Compensating test"}, _MANAGER
    )
    reversed_payment = validate_success(resp)
    assert reversed_payment["status"] == "REVERSED"
    assert reversed_payment["reversal_reason"] == "Compensating test"

    resp = api.get_assessment(assessment["id"], _MANAGER)
    a_state = validate_success(resp)
    assert a_state["amount_paid_cents"] == 0


def test_amenity_cancel_moves_to_terminal_cancelled_status(api):
    """PRD §3.6: "the reservation moves to the terminal `CANCELLED` state
    and the previously-consumed capacity is restored for future overlap
    checks — this is the compensating invariant that keeps two sequential
    cancel-and-rebook cycles idempotent."

    Design: Difficulty/compensating_invariant/amenity_cancel_restores_capacity_conservation
    """
    homeowner = create_homeowner("hcx@ex.com", "H CX")
    amenity = create_amenity("Deck", capacity=5)
    reservation = create_reservation(
        amenity["id"], homeowner["id"],
        "2026-03-15T10:00:00Z", "2026-03-15T12:00:00Z", 3,
    )
    resp = api.cancel_reservation(
        reservation["id"], make_homeowner_headers(homeowner["id"])
    )
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"

    # A brand-new reservation of the same guest_count at the same window
    # succeeds — capacity has been restored.
    resp = api.create_amenity_reservation(
        {"amenity_id": amenity["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-15T10:00:00Z", "end_ts": "2026-03-15T12:00:00Z",
         "guest_count": 3},
        make_homeowner_headers(homeowner["id"]),
    )
    new_res = validate_success(resp, expected_status=201)
    assert new_res["status"] == "BOOKED"
