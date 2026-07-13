"""Attendance submission, approval, and payment (PRD §3.4, §3.6, §2.9).

Depth coverage for the estimated/actual payment split, the nested absence-cap gross,
the pinned copay-proration rounding order, the absence-cap boundary, cross-entity
approval gating, and state-vs-constraint precedence; breadth coverage for duplicate
attendance and invalid attendance days.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_authorization, submit_attendance, get_payment_for_attendance,
    make_provider_headers, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]


def _approve(api, attendance_id):
    return validate_success(api.approve_attendance(attendance_id, CW), 200)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / payment_estimated_vs_actual_across_authorization_and_payment
# ---------------------------------------------------------------------------
def test_authorization_estimate_assumes_full_attendance_and_full_copay(api):
    """PRD §3.4: "Its `estimated_monthly_payment_cents` assumes full attendance and the
    full monthly copay: it is the `authorized_daily_rate_cents` multiplied by the
    `authorized_days_per_month`, less the full `monthly_copay_cents` (deducted in whole,
    not prorated), with the result floored at 0 so it never goes negative."

    Design: Difficulty/dual_variant_calc/payment_estimated_vs_actual_across_authorization_and_payment
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    auth = ctx["authorization"]
    assert auth["authorized_daily_rate_cents"] == 5_000
    assert auth["estimated_monthly_payment_cents"] == 97_500


def test_actual_net_payment_diverges_from_estimate(api):
    """PRD §3.6: "The `net_provider_payment_cents` paid to the provider is the
    `gross_amount_cents` minus the `copay_deducted_cents`, floored at 0 so it is never
    negative."

    Design: Difficulty/dual_variant_calc/payment_estimated_vs_actual_across_authorization_and_payment
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    _approve(api, att["id"])
    payment = get_payment_for_attendance(att["id"])
    assert payment["net_provider_payment_cents"] == 93_072
    assert payment["net_provider_payment_cents"] != ctx["authorization"]["estimated_monthly_payment_cents"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / payment_gross_nested_min_absence_cap
# ---------------------------------------------------------------------------
def test_payable_days_applies_nested_absence_cap(api):
    """PRD §3.6: "`payable_days` is the `present_days` plus the smaller of the
    `absent_days` and the maximum paid-absence allowance of 5 days."

    Design: Difficulty/combinatorial_formula/payment_gross_nested_min_absence_cap
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=20, absent_days=8)
    approved = _approve(api, att["id"])
    assert approved["payable_days"] == 25


def test_gross_net_with_capped_absence(api):
    """PRD §3.6: "The `gross_amount_cents` is the voucher's `authorized_daily_rate_cents`
    multiplied by the `payable_days`."
    PRD §3.6: "The `net_provider_payment_cents` paid to the provider is the
    `gross_amount_cents` minus the `copay_deducted_cents`, floored at 0 so it is never
    negative."

    Design: Difficulty/combinatorial_formula/payment_gross_nested_min_absence_cap
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=20, absent_days=8)
    _approve(api, att["id"])
    payment = get_payment_for_attendance(att["id"])
    assert payment["gross_amount_cents"] == 125_000
    assert payment["copay_deducted_cents"] == 14_200
    assert payment["net_provider_payment_cents"] == 110_800


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / copay_proration_rounding_order_pinned
# ---------------------------------------------------------------------------
def test_copay_proration_rounds_per_day_before_multiplying(api):
    """PRD §3.6: "first the per-day copay is derived by dividing the voucher's
    `monthly_copay_cents` by its `authorized_days_per_month` and rounding half up to a
    whole cent, and only then is that rounded per-day copay multiplied by the
    `payable_days` to yield `copay_deducted_cents`."

    Design: Difficulty/combinatorial_formula/copay_proration_rounding_order_pinned
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    _approve(api, att["id"])
    payment = get_payment_for_attendance(att["id"])
    assert payment["copay_deducted_cents"] == 11_928


def test_net_reflects_pinned_proration_order(api):
    """PRD §3.6: "This order is deliberate — the copay is rounded per day before
    multiplying, not by rounding the monthly copay times payable days over authorized
    days."

    Design: Difficulty/combinatorial_formula/copay_proration_rounding_order_pinned
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    _approve(api, att["id"])
    payment = get_payment_for_attendance(att["id"])
    assert payment["net_provider_payment_cents"] == 93_072


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / absence_cap_boundary_on_attendance_approve
# ---------------------------------------------------------------------------
def test_sixth_absent_day_is_unpaid(api):
    """PRD §3.6: "`payable_days` is the `present_days` plus the smaller of the
    `absent_days` and the maximum paid-absence allowance of 5 days."

    Design: Difficulty/boundary_precision_check/absence_cap_boundary_on_attendance_approve
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=15, absent_days=6)
    approved = _approve(api, att["id"])
    assert approved["payable_days"] == 20


def test_gross_at_absence_cap_boundary(api):
    """PRD §3.6: "The `gross_amount_cents` is the voucher's `authorized_daily_rate_cents`
    multiplied by the `payable_days`."

    Design: Difficulty/boundary_precision_check/absence_cap_boundary_on_attendance_approve
    """
    ctx = setup_active_authorization(published=6_000, ceiling_max=5_000,
                                     authorized_days_per_month=22)
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=15, absent_days=6)
    _approve(api, att["id"])
    payment = get_payment_for_attendance(att["id"])
    assert payment["gross_amount_cents"] == 100_000


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / approve_requires_authorization_active
# ---------------------------------------------------------------------------
def test_approve_on_terminated_authorization_rejected(api):
    """PRD §3.6: "A `CaseWorker` approves submitted attendance, which requires that the
    underlying voucher be `ACTIVE` and that the reported days be coherent"
    PRD §2.9: "For any transition endpoint, the target resource must be in a state from
    which the transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_authorization_active
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    validate_success(api.terminate_authorization(ctx["authorization"]["id"], CW), 200)
    resp = api.approve_attendance(att["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_approve_leaves_attendance_submitted(api):
    """PRD §3.6: "A `CaseWorker` approves submitted attendance, which requires that the
    underlying voucher be `ACTIVE` and that the reported days be coherent"

    Design: Difficulty/cross_entity_state_dependency/approve_requires_authorization_active
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    validate_success(api.terminate_authorization(ctx["authorization"]["id"], CW), 200)
    api.approve_attendance(att["id"], CW)  # rejected
    current = validate_success(api.get_attendance_record(att["id"], CW), 200)
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state_beats_constraint_on_attendance_approve
# ---------------------------------------------------------------------------
def test_state_error_reported_when_both_state_and_days_fail(api):
    """PRD §2.9: "For any transition endpoint, the target resource must be in a state
    from which the transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE`. Only after these universal gates pass does the system evaluate
    the operation-specific business rules described in §3, in the relative order stated
    there."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_attendance_approve
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=30, absent_days=30)
    validate_success(api.terminate_authorization(ctx["authorization"]["id"], CW), 200)
    resp = api.approve_attendance(att["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_days_constraint_not_reported_before_state(api):
    """PRD §2.9: "Only after these universal gates pass does the system evaluate the
    operation-specific business rules described in §3, in the relative order stated
    there."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_attendance_approve
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=30, absent_days=30)
    validate_success(api.terminate_authorization(ctx["authorization"]["id"], CW), 200)
    resp = api.approve_attendance(att["id"], CW)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_INVALID_ATTENDANCE_DAYS"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / attendance_reject_resubmit_cycle
# ---------------------------------------------------------------------------
def test_reject_moves_submitted_attendance_to_rejected(api):
    """PRD §3.6: "Submitted attendance can instead be rejected by a `CaseWorker`,
    optionally with a `reason`, moving it from `SUBMITTED` to `REJECTED`; the same
    `REJECTED` state is reached automatically when a voucher is suspended."

    Design: Difficulty/non_linear_state_machine/attendance_reject_resubmit_cycle
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    data = validate_success(api.reject_attendance(att["id"], CW, {"reason": "documents missing"}), 200)
    assert data["status"] == "REJECTED"


def test_resubmit_returns_rejected_attendance_to_submitted_with_corrections(api):
    """PRD §3.6: "A `Provider` may resubmit a rejected record, optionally supplying
    corrected `present_days` and `absent_days` which overwrite the stored counts,
    moving it from `REJECTED` back to `SUBMITTED` — but only while the underlying
    voucher is `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/attendance_reject_resubmit_cycle
    """
    ctx = setup_active_authorization()
    prov_headers = make_provider_headers(ctx["provider"]["id"])
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            present_days=18, absent_days=3)
    api.reject_attendance(att["id"], CW, {"reason": "documents missing"})
    data = validate_success(
        api.resubmit_attendance(att["id"], prov_headers, {"present_days": 19, "absent_days": 2}), 200)
    assert data["status"] == "SUBMITTED"
    assert data["present_days"] == 19


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_attendance_same_month_returns_409
# ---------------------------------------------------------------------------
def test_second_attendance_for_same_month_returns_409(api):
    """PRD §3.6: "Only one attendance record may exist per voucher per month: a second
    submission for the same `authorization_id` and `service_month` is rejected with
    `ERR_DUPLICATE_ATTENDANCE`."

    Design: Corner/validations/duplicate_attendance_same_month_returns_409
    """
    ctx = setup_active_authorization()
    prov_headers = make_provider_headers(ctx["provider"]["id"])
    submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                      service_month="2026-03", present_days=18, absent_days=3)
    resp = api.create_attendance_record({
        "authorization_id": ctx["authorization"]["id"], "service_month": "2026-03",
        "present_days": 10, "absent_days": 1,
    }, prov_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTENDANCE)


# ---------------------------------------------------------------------------
# Corner: validations / invalid_attendance_days_on_approve_returns_422
# ---------------------------------------------------------------------------
def test_approve_with_days_exceeding_month_returns_422(api):
    """PRD §3.6: "`present_days` plus `absent_days` must not exceed the number of
    calendar days in the named `service_month`, or the approval is rejected with
    `ERR_INVALID_ATTENDANCE_DAYS`."

    Design: Corner/validations/invalid_attendance_days_on_approve_returns_422
    """
    ctx = setup_active_authorization()
    att = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                            service_month="2026-03", present_days=30, absent_days=30)
    resp = api.approve_attendance(att["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_ATTENDANCE_DAYS)
