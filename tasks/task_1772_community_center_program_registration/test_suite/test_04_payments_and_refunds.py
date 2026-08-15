"""Payment gates, the refund review threshold, voluntary-drop refund tiers,
and finance approval of large refunds."""
from test_helpers import (
    FD,
    FO,
    PC,
    MEETING_TIMES_4,
    ApiErrorId,
    assert_payment_transaction,
    create_payment_payload,
    drop_registration,
    find_refund_transaction,
    get_household_credit,
    get_registration,
    household_headers,
    list_payments_for,
    pay_registration,
    register_and_pay,
    register_participant,
    set_clock,
    setup_household_with_participants,
    setup_multi_session_catalog,
    setup_published_session,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api


def test_waitlisted_registration_cannot_pay(api):
    """PRD §3.7: "The checks run in a fixed order: the registration must be
    `ENROLLED` on the enrollment axis and `PENDING` on the payment axis, else
    `ERR_PAYMENT_NOT_ALLOWED` — a `WAITLISTED` registration cannot pay, and a
    second payment on a `PAID` registration fails here as well; then household
    membership for `HouseholdManager` callers, else
    `ERR_NOT_HOUSEHOLD_MEMBER`; then the amount must equal the pinned
    `fee_charged_cents` exactly, with no partial payments and no overpayment,
    else `ERR_INCORRECT_AMOUNT`; and finally, when `method` is
    `ACCOUNT_CREDIT`, the household's `account_credit_cents` must cover the
    amount, else `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/state_machines/waitlisted_registration_cannot_pay
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    register_participant(session_id, parts_a[0]["id"], household_a["id"])
    waitlisted = register_participant(session_id, parts_b[0]["id"], household_b["id"])
    assert waitlisted["enrollment_status"] == "WAITLISTED"

    resp = _api.pay_registration(
        waitlisted["id"], create_payment_payload(5000, "EXTERNAL"),
        household_headers(household_b))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_ALLOWED, 409)


def test_incorrect_amount_rejected(api):
    """PRD §3.7: "The checks run in a fixed order: the registration must be
    `ENROLLED` on the enrollment axis and `PENDING` on the payment axis, else
    `ERR_PAYMENT_NOT_ALLOWED` — a `WAITLISTED` registration cannot pay, and a
    second payment on a `PAID` registration fails here as well; then household
    membership for `HouseholdManager` callers, else
    `ERR_NOT_HOUSEHOLD_MEMBER`; then the amount must equal the pinned
    `fee_charged_cents` exactly, with no partial payments and no overpayment,
    else `ERR_INCORRECT_AMOUNT`; and finally, when `method` is
    `ACCOUNT_CREDIT`, the household's `account_credit_cents` must cover the
    amount, else `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/incorrect_amount_rejected
    """
    ctx = setup_published_session(fee_resident_cents=5000, fee_nonresident_cents=5000)
    household, parts = setup_household_with_participants(count=1, account_name="HI")
    registration = register_participant(ctx["session"]["id"], parts[0]["id"],
                                        household["id"])

    resp = _api.pay_registration(
        registration["id"], create_payment_payload(4999, "EXTERNAL"),
        household_headers(household))
    validate_error(resp, ApiErrorId.ERR_INCORRECT_AMOUNT, 422)
    assert get_registration(registration["id"])["payment_status"] == "PENDING"


def test_insufficient_credit_rejected(api):
    """PRD §3.7: "and finally, when `method` is `ACCOUNT_CREDIT`, the
    household's `account_credit_cents` must cover the amount, else
    `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/insufficient_credit_rejected
    """
    ctx = setup_published_session(fee_resident_cents=5000, fee_nonresident_cents=5000)
    household, parts = setup_household_with_participants(count=1, account_name="HJ")
    registration = register_participant(ctx["session"]["id"], parts[0]["id"],
                                        household["id"])
    assert get_household_credit(household["id"]) == 0

    resp = _api.pay_registration(
        registration["id"], create_payment_payload(5000, "ACCOUNT_CREDIT"),
        household_headers(household))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT, 422)


def test_refund_threshold_auto_vs_pending(api):
    """PRD §3.7: "A `REFUND` transaction always carries `method`
    `ACCOUNT_CREDIT`, and its life depends on size: amounts below one hundred
    dollars — 10000 cents — are auto-approved and born `COMPLETED`, while
    amounts of one hundred dollars or more are born `PENDING` and wait for a
    `FinanceOfficer` to approve the refund."
    PRD §3.8: "If no meeting has been held, the refund is the full
    `net_paid_cents`."

    Design: Corner/cross_cutting_complexity_layers/refund_threshold_auto_vs_pending
    """
    catalog = setup_multi_session_catalog([
        {"title": "S9", "fee_resident_cents": 9999, "fee_nonresident_cents": 9999},
        {"title": "S10", "fee_resident_cents": 10000, "fee_nonresident_cents": 10000},
    ])
    s9, s10 = catalog["sessions"]
    household_9, parts_9 = setup_household_with_participants(count=1, account_name="H9")
    household_10, parts_10 = setup_household_with_participants(count=1, account_name="H10")
    r9 = register_and_pay(s9["session"]["id"], parts_9[0]["id"], household_9["id"])
    r10 = register_and_pay(s10["session"]["id"], parts_10[0]["id"], household_10["id"])

    # Both drops happen before any meeting (full refund of the pinned fee).
    drop_registration(r9["id"], household_9["id"])
    drop_registration(r10["id"], household_10["id"])

    # 9999 < 10000: auto-approved, credited immediately.
    assert get_registration(r9["id"])["payment_status"] == "REFUNDED"
    assert get_household_credit(household_9["id"]) == 9999
    # 10000 >= 10000: born PENDING, nothing credited yet.
    assert get_registration(r10["id"])["payment_status"] == "REFUND_PENDING"
    assert get_household_credit(household_10["id"]) == 0


def test_refund_pending_approval_credits_household(api):
    """PRD §3.7: "Approval requires the transaction to be a `REFUND` still
    `PENDING`, else `ERR_REFUND_NOT_PENDING`; it moves the transaction to
    `COMPLETED`, adds the amount to the household's `account_credit_cents` and
    to the registration's `refund_total_cents`, and advances the
    registration's payment axis from `REFUND_PENDING` to `REFUNDED`."
    PRD §3.7: "All payment entries can be listed, optionally filtered by
    `registration_id`; the default chronological ordering by `created_at`
    ascending guarantees a `CHARGE` precedes its `REFUND`."
    PRD §2.1: "Access to each operation is further restricted by role; an
    attempt to perform an action outside the caller's designated role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/refund_pending_approval_credits_household
    """
    ctx = setup_published_session(fee_resident_cents=12000,
                                  fee_nonresident_cents=12000)
    household, parts = setup_household_with_participants(count=1, account_name="H1")
    registration = register_and_pay(ctx["session"]["id"], parts[0]["id"],
                                    household["id"])

    drop_registration(registration["id"], household["id"])
    ledger = list_payments_for(registration["id"])
    assert [entry["type"] for entry in ledger] == ["CHARGE", "REFUND"]
    refund = ledger[1]
    assert_payment_transaction(refund)
    assert refund["type"] == "REFUND"
    assert refund["status"] == "PENDING"          # 12000 >= 10000 threshold
    assert get_household_credit(household["id"]) == 0

    resp = _api.approve_refund(refund["id"], FD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    completed = validate_success(_api.approve_refund(refund["id"], FO))
    assert completed["status"] == "COMPLETED"
    assert get_household_credit(household["id"]) == 12000
    after = get_registration(registration["id"])
    assert after["payment_status"] == "REFUNDED"
    assert after["refund_total_cents"] == 12000


def _two_household_paid_session(fee: int = 10000, meeting_times=None,
                                min_enrollment: int = 2) -> dict:
    """Published session + two households each registered and paid in full."""
    ctx = setup_published_session(fee_resident_cents=fee, fee_nonresident_cents=fee,
                                  min_enrollment=min_enrollment,
                                  meeting_times=meeting_times)
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    ra = register_and_pay(ctx["session"]["id"], parts_a[0]["id"], household_a["id"])
    rb = register_and_pay(ctx["session"]["id"], parts_b[0]["id"], household_b["id"])
    return {"ctx": ctx, "ha": household_a, "hb": household_b, "ra": ra, "rb": rb}


def test_voluntary_drop_half_refund(api):
    """PRD §3.8: "A meeting counts as held when its `starts_at` is at or
    before now, and dropping at exactly a meeting's start time counts that
    meeting as held. If no meeting has been held, the refund is the full
    `net_paid_cents`. Otherwise, take the halfway point of the session — its
    total meeting count divided by two, rounded down to a whole number: when
    the number of meetings held is between one and that halfway point
    inclusive, the refund is one half of `net_paid_cents`, rounded half-up to
    a whole cent; when the number held exceeds the halfway point, the refund
    is zero."
    PRD §3.8: "Issuance then follows the ledger rules of §3.7: a refund
    greater than zero creates a `REFUND` transaction — `PENDING` at or above
    the one-hundred-dollar review threshold, moving the payment axis from
    `PAID` to `REFUND_PENDING`, otherwise `COMPLETED`, moving `PAID` to
    `REFUNDED` and crediting the household — while a zero refund creates
    nothing and leaves `PAID` untouched, and a never-paid `PENDING`
    registration simply voids to `VOID`."

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_admin_cancellation
    """
    scenario = _two_household_paid_session(fee=10000, meeting_times=MEETING_TIMES_4)
    ra, household_a = scenario["ra"], scenario["ha"]

    # Exactly one of the four meetings has started: 1 <= floor(4/2) -> 50%.
    set_clock("2026-09-20T18:30:00Z")
    drop_registration(ra["id"], household_a["id"])

    after = get_registration(ra["id"])
    assert after["enrollment_status"] == "DROPPED"
    assert after["drop_reason"] == "VOLUNTARY"
    assert after["refund_total_cents"] == 5000        # 50% of 10000
    assert after["payment_status"] == "REFUNDED"      # 5000 < 10000 threshold
    assert get_household_credit(household_a["id"]) == 5000


def test_admin_cancellation_full_refund_pending(api):
    """PRD §3.9: "Every `ENROLLED` registration moves to `CANCELLED` with
    `drop_reason` matching the session's reason, and each runs the
    cancellation variant of the refund rule: a full one hundred percent of
    `net_paid_cents`, regardless of timing, issued through the standard ledger
    path — `PENDING` and `REFUND_PENDING` at or above the review threshold,
    auto-`COMPLETED` and `REFUNDED` below it with the household credited, a
    never-paid `PENDING` axis voided, and `WAIVED` left alone."

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_admin_cancellation
    """
    scenario = _two_household_paid_session(fee=10000, meeting_times=MEETING_TIMES_4)
    ra, rb = scenario["ra"], scenario["rb"]
    household_a, household_b = scenario["ha"], scenario["hb"]

    # One meeting held: the voluntary drop refunds 50%; the later admin
    # cancellation refunds the survivor 100% (held for finance review).
    set_clock("2026-09-20T18:30:00Z")
    drop_registration(ra["id"], household_a["id"])
    validate_success(_api.cancel_class_session(scenario["ctx"]["session"]["id"],
                                               PC))

    survivor = get_registration(rb["id"])
    assert survivor["enrollment_status"] == "CANCELLED"
    assert survivor["drop_reason"] == "ADMIN"
    assert survivor["payment_status"] == "REFUND_PENDING"   # 10000 >= 10000
    assert get_household_credit(household_b["id"]) == 0     # not yet credited

    dropped = get_registration(ra["id"])
    assert dropped["refund_total_cents"] == 5000
    assert dropped["payment_status"] == "REFUNDED"
    assert get_household_credit(household_a["id"]) == 5000


def test_refund_before_first_meeting_is_full(api):
    """PRD §3.8: "A meeting counts as held when its `starts_at` is at or
    before now, and dropping at exactly a meeting's start time counts that
    meeting as held. If no meeting has been held, the refund is the full
    `net_paid_cents`."

    Design: Difficulty/boundary_precision_check/refund_first_meeting_start_boundary
    """
    scenario = _two_household_paid_session(
        fee=4000,
        meeting_times=[("2026-09-20T18:00:00Z", "2026-09-20T19:00:00Z"),
                       ("2026-09-27T18:00:00Z", "2026-09-27T19:00:00Z")],
        min_enrollment=1,
    )
    rb, household_b = scenario["rb"], scenario["hb"]

    # One second before the first meeting starts: no meeting held -> 100%.
    set_clock("2026-09-20T17:59:59Z")
    drop_registration(rb["id"], household_b["id"])

    after = get_registration(rb["id"])
    assert after["refund_total_cents"] == 4000
    assert after["payment_status"] == "REFUNDED"
    assert get_household_credit(household_b["id"]) == 4000


def test_refund_at_first_meeting_start_is_half(api):
    """PRD §3.8: "A meeting counts as held when its `starts_at` is at or
    before now, and dropping at exactly a meeting's start time counts that
    meeting as held. If no meeting has been held, the refund is the full
    `net_paid_cents`. Otherwise, take the halfway point of the session — its
    total meeting count divided by two, rounded down to a whole number: when
    the number of meetings held is between one and that halfway point
    inclusive, the refund is one half of `net_paid_cents`, rounded half-up to
    a whole cent; when the number held exceeds the halfway point, the refund
    is zero."

    Design: Difficulty/boundary_precision_check/refund_first_meeting_start_boundary
    """
    scenario = _two_household_paid_session(
        fee=4000,
        meeting_times=[("2026-09-20T18:00:00Z", "2026-09-20T19:00:00Z"),
                       ("2026-09-27T18:00:00Z", "2026-09-27T19:00:00Z")],
        min_enrollment=1,
    )
    ra, household_a = scenario["ra"], scenario["ha"]

    # Dropping at exactly the first meeting's starts_at counts it as held:
    # 1 <= floor(2/2) -> 50%.
    set_clock("2026-09-20T18:00:00Z")
    drop_registration(ra["id"], household_a["id"])

    after = get_registration(ra["id"])
    assert after["refund_total_cents"] == 2000
    assert after["payment_status"] == "REFUNDED"
    assert get_household_credit(household_a["id"]) == 2000
