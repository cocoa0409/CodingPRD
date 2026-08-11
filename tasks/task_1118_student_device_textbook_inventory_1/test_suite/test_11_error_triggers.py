"""Temporal and fiscal error triggers (PRD §3.5, §3.7)."""

from test_helpers import (
    ApiErrorId,
    make_family_headers,
    set_clock,
    settle_fee_payload,
    setup_confirmed_damage_fee,
    setup_student_with_assignment,
    validate_error,
    validate_error_is_one_of,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_appeal_after_30_day_window_closed(api):
    """PRD §3.7: "The appeal window is 30 days from assessment; after that the attempt is refused with `ERR_APPEAL_WINDOW_CLOSED`."

    The fee is assessed at the boot clock (2026-05-01); 45 days later the
    appeal is refused.

    Design: Corner/errors/appeal_window_closed_after_30_days
    """
    ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                     observed_condition_grade="A")
    set_clock("2026-06-15T00:00:00Z")
    res = api.appeal_fee(
        ctx["program"]["id"], ctx["student"]["id"], ctx["fee"]["id"],
        make_family_headers(ctx["student"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


def test_declare_lost_before_30_days_overdue_rejected(api, registrar_headers):
    """PRD §3.5: "The assignment must have been `OVERDUE` for at least 30 days; a premature declaration is refused with `ERR_NOT_OVERDUE_LONG_ENOUGH`."

    Fifteen days past the expected return date is premature.

    Design: Corner/errors/declare_lost_before_30_days_rejected
    """
    ctx = setup_student_with_assignment(
        expected_return_date="2026-06-01T00:00:00Z"
    )
    set_clock("2026-06-16T00:00:00Z")
    res = api.declare_lost(
        ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOT_OVERDUE_LONG_ENOUGH)


def test_settle_below_amount_rejected_underpaid(api, admin_headers):
    """PRD §3.7: "a `DistrictAdmin` records a `payment_cents` amount, which is added to the fee's `paid_cents`, and the fee moves `ASSESSED → SETTLED` only once the collected `paid_cents` plus the `waived_cents` together reach the `amount_cents` — an attempt to settle short of that mark is rejected with `ERR_UNDERPAID` (HTTP 422)."

    A 5000-cent payment against a 10000-cent fee falls short of the mark.

    Design: Corner/errors/settle_underpaid_rejected
    """
    ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                     observed_condition_grade="A")
    assert ctx["fee"]["amount_cents"] == 10000
    res = api.settle_fee(ctx["program"]["id"], ctx["student"]["id"],
                         ctx["fee"]["id"], settle_fee_payload(5000),
                         admin_headers)
    validate_error(res, ApiErrorId.ERR_UNDERPAID)


def test_fee_write_off_guarded_by_student_status_and_age(api, admin_headers):
    """PRD §3.7: "Two conditions guard this: the student must already be `WITHDRAWN` or `GRADUATED` — an active student's fees cannot be written off, and the attempt meets `ERR_STUDENT_ACTIVE` — and the fee must have sat in `ASSESSED` for at least 180 days, else `ERR_WRITE_OFF_TOO_EARLY`."

    Here BOTH guards are unmet (student ENROLLED; fee 31 days old); the PRD
    does not commit to which of the two refusals fires first.

    Design: Corner/errors/write_off_too_early_rejected
    """
    ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                     observed_condition_grade="A")
    set_clock("2026-06-01T00:00:00Z")
    res = api.write_off_fee(ctx["program"]["id"], ctx["student"]["id"],
                            ctx["fee"]["id"], admin_headers)
    assert res.status_code == 409, f"Expected 409, got {res.status_code}"
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_WRITE_OFF_TOO_EARLY.value,
              ApiErrorId.ERR_STUDENT_ACTIVE.value]
    )
