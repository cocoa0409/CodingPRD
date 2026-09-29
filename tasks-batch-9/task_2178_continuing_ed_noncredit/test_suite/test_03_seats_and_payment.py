"""Payment, seat resolution, waitlist capacity and voucher usability at the till."""

from test_helpers import (
    ADMIN,
    REGISTRAR,
    ApiErrorId,
    add_paid_registration,
    make_learner_headers,
    new_learner,
    pay_payload,
    read_offering,
    read_voucher,
    register_learner,
    reset_clock,
    setup_assigned_voucher,
    setup_locked_offering_with_underfunded_voucher,
    setup_open_offering,
    setup_single_seat_offering_with_waitlist,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParallelStateAxes:
    """The seat axis and the money axis advance independently on the same row."""

    def test_payment_lands_waitlisted_on_the_seat_axis_and_paid_on_the_money_axis(self, api):
        """PRD 3.5: "If instead `confirmed_enrollment_count` already equals
        `max_enrollment` when payment lands, the registration moves `PENDING →
        WAITLISTED` and the section's `waitlist_count` increases by 1."
        PRD 3.5: "A self-paid registration moves `UNPAID → PAID` with
        `amount_paid_cents` set to `total_due_cents`, and increments the registration's
        `version` and the section's `version` by 1 each."
        PRD 3.5: "A registration may legitimately sit in combinations such as
        waitlisted-and-paid, enrolled-and-voucher-committed, or
        enrolled-and-partially-refunded, and implementers must not collapse the two
        axes into a single status field."

        Design: Difficulty/non_linear_state_machine/registration_axes_move_independently_waitlisted_and_paid
        """
        reset_clock()
        scene = setup_open_offering(
            offering_overrides={"min_enrollment": 1, "max_enrollment": 1, "tuition_cents": 60000}
        )
        add_paid_registration(scene["offering_id"], learner_index=0)
        after_first = read_offering(scene["offering_id"])
        assert after_first["status"] == "WAITLIST_ONLY", (
            "the last seat closes the door behind itself"
        )

        ben = new_learner(email="ben@x.com", full_name="Ben Osei")
        reg = register_learner(scene["offering_id"], ben["id"], after_first["version"])
        data = validate_success(
            api.pay_registration(
                reg["id"], pay_payload("SELF_PAY"), make_learner_headers(ben["id"])
            )
        )
        assert data["enrollment_status"] == "WAITLISTED"
        assert data["payment_status"] == "PAID"
        assert data["amount_paid_cents"] == 62400

    def test_section_counters_separate_the_seated_learner_from_the_waitlisted_one(self, api):
        """PRD 3.2: "Of the counters, `confirmed_enrollment_count` is the number of
        registrations on the section whose `enrollment_status` is `ENROLLED`;
        `paid_enrollment_count` is the number whose `enrollment_status` is `ENROLLED`
        **and** whose `payment_status` is either `PAID` or `VOUCHER_COMMITTED`; and
        `waitlist_count` is the number whose `enrollment_status` is `WAITLISTED`."
        PRD 3.5: "If `confirmed_enrollment_count` is strictly below `max_enrollment`,
        the registration moves `PENDING → ENROLLED`, its `enrolled_at` is stamped with
        the current logical-clock instant, and the section's
        `confirmed_enrollment_count` and `paid_enrollment_count` each increase by 1."

        Design: Difficulty/non_linear_state_machine/registration_axes_move_independently_waitlisted_and_paid
        """
        reset_clock()
        scene = setup_single_seat_offering_with_waitlist(waitlisted=1)
        seated = validate_success(
            api.get_registration(scene["seated"]["registration_id"], REGISTRAR)
        )
        assert seated["enrollment_status"] == "ENROLLED"

        offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
        assert offering["confirmed_enrollment_count"] == 1
        assert offering["waitlist_count"] == 1
        assert offering["paid_enrollment_count"] == 1


class TestOpennessOutranksVoucherBalance:
    """A payment that breaks both rules reports the earlier-evaluated one."""

    def test_locked_section_reports_offering_not_open_over_voucher_balance(self, api):
        """PRD 2.8: "When a request would fail more than one rule, exactly one error is
        returned, and which one is fully determined: rules are evaluated in ascending
        priority order and the **first** rule that fails determines the response."
        PRD 2.8: "Offering openness — the offering backing a registration create or a
        payment is `OPEN` or `WAITLIST_ONLY`; otherwise `ERR_OFFERING_NOT_OPEN`."
        PRD 3.5: "Separately, the voucher's `remaining_cents` must be at least the
        registration's `total_due_cents`, or the payment is refused with
        `ERR_VOUCHER_INSUFFICIENT_BALANCE` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_offering_not_open_wins_over_fiscal_voucher_insufficient
        """
        reset_clock()
        scene = setup_locked_offering_with_underfunded_voucher()
        assert scene["offering"]["status"] == "CENSUS_LOCKED"

        resp = api.pay_registration(
            scene["registration_id"],
            pay_payload("VOUCHER", scene["voucher_id"]),
            make_learner_headers(scene["learner_id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_OPEN, 409)
        assert error["error_id"] != "ERR_VOUCHER_INSUFFICIENT_BALANCE"

    def test_rejected_payment_leaves_registration_and_voucher_untouched(self, api):
        """PRD 3.5: "Payment requires the registration's `payment_status` to be
        `UNPAID` and its `enrollment_status` to be `PENDING`, and it requires the
        section to still be `OPEN` or `WAITLIST_ONLY`, failing which the answer is
        `ERR_OFFERING_NOT_OPEN`."
        PRD 3.5: "On success the registration's `voucher_id` is set from the payload,
        its `payment_status` moves `UNPAID → VOUCHER_COMMITTED`, and `amount_paid_cents`
        is set to `total_due_cents`."

        Design: Difficulty/priority_pair_validation_conflict/state_offering_not_open_wins_over_fiscal_voucher_insufficient
        """
        reset_clock()
        scene = setup_locked_offering_with_underfunded_voucher()
        api.pay_registration(
            scene["registration_id"],
            pay_payload("VOUCHER", scene["voucher_id"]),
            make_learner_headers(scene["learner_id"]),
        )
        registration = validate_success(
            api.get_registration(scene["registration_id"], REGISTRAR)
        )
        assert registration["payment_status"] == "UNPAID"
        assert registration["voucher_id"] is None

        voucher = read_voucher(scene["voucher_id"], scene["account_id"])
        assert voucher["remaining_cents"] == 1000
        assert voucher["committed_cents"] == 0


def test_duplicate_registration_on_same_section_returns_conflict(api):
    """PRD 3.5: "Fourth, the learner must not already hold another registration on
    this same section whose `enrollment_status` is `PENDING`, `ENROLLED`, `WAITLISTED`
    or `COMPLETED`; a repeat attempt is `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_registration_for_same_learner_and_offering_returns_conflict
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")
    first = register_learner(scene["offering_id"], learner["id"], scene["version"])

    fresh_version = read_offering(scene["offering_id"])["version"]
    validate_error(
        api.create_registration(
            scene["offering_id"],
            {"learner_id": learner["id"], "expected_offering_version": fresh_version},
            make_learner_headers(learner["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_REGISTRATION,
        409,
    )
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"learner_id": learner["id"]})
    )
    assert meta["total_count"] == 1
    kept = validate_success(api.get_registration(first["id"], REGISTRAR))
    assert kept["enrollment_status"] == "PENDING"


def test_expired_voucher_is_not_usable_at_payment(api):
    """PRD 3.5: "Four usability conditions must all hold: the voucher's `status` must
    be `ASSIGNED` or `PARTIALLY_REDEEMED`, its `assigned_learner_id` must equal the
    registration's `learner_id`, the logical clock must be strictly earlier than its
    `expires_at`, and its sponsor account's `status` must be `ACTIVE`. Any failure
    yields `ERR_VOUCHER_NOT_USABLE` (HTTP 422)."

    Design: Corner/validations/expired_voucher_returns_voucher_not_usable
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")
    money = setup_assigned_voucher(
        learner["id"], 200000, 200000, expires_at="2026-08-15T00:00:00Z"
    )
    registration = register_learner(scene["offering_id"], learner["id"], scene["version"])
    validate_success(api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, ADMIN))

    validate_error(
        api.pay_registration(
            registration["id"],
            pay_payload("VOUCHER", money["voucher_id"]),
            make_learner_headers(learner["id"]),
        ),
        ApiErrorId.ERR_VOUCHER_NOT_USABLE,
        422,
    )
    after = validate_success(api.get_registration(registration["id"], REGISTRAR))
    assert after["payment_status"] == "UNPAID"
    voucher = read_voucher(money["voucher_id"], money["account_id"])
    assert voucher["remaining_cents"] == 200000
    assert voucher["status"] == "ASSIGNED"
    account = validate_success(api.get_corporate_account(money["account_id"], ADMIN))
    assert account["committed_cents"] == 0


def test_voucher_below_total_due_returns_insufficient_balance(api):
    """PRD 3.5: "Separately, the voucher's `remaining_cents` must be at least the
    registration's `total_due_cents`, or the payment is refused with
    `ERR_VOUCHER_INSUFFICIENT_BALANCE` (HTTP 402)."

    Design: Corner/errors/voucher_remaining_below_total_due_returns_voucher_insufficient_balance
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")
    money = setup_assigned_voucher(learner["id"], 1000, 1000)
    registration = register_learner(scene["offering_id"], learner["id"], scene["version"])

    validate_error(
        api.pay_registration(
            registration["id"],
            pay_payload("VOUCHER", money["voucher_id"]),
            make_learner_headers(learner["id"]),
        ),
        ApiErrorId.ERR_VOUCHER_INSUFFICIENT_BALANCE,
        402,
    )
    after = validate_success(api.get_registration(registration["id"], REGISTRAR))
    assert after["payment_status"] == "UNPAID"
    voucher = read_voucher(money["voucher_id"], money["account_id"])
    assert voucher["remaining_cents"] == 1000
    assert voucher["committed_cents"] == 0
    account = validate_success(api.get_corporate_account(money["account_id"], ADMIN))
    assert account["committed_cents"] == 0


def test_waitlist_cap_of_five_returns_offering_full(api):
    """PRD 3.5: "Fifth, when the section is currently `WAITLIST_ONLY`, its
    `waitlist_count` must be strictly below the waitlist cap of 5, or the create is
    refused with `ERR_OFFERING_FULL`."

    Design: Corner/errors/waitlist_cap_reached_returns_offering_full
    """
    reset_clock()
    scene = setup_single_seat_offering_with_waitlist(waitlisted=5)
    before = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert before["waitlist_count"] == 5

    seventh = new_learner(email="hal@x.com", full_name="Hal Quinn")
    validate_error(
        api.create_registration(
            scene["offering_id"],
            {"learner_id": seventh["id"], "expected_offering_version": before["version"]},
            REGISTRAR,
        ),
        ApiErrorId.ERR_OFFERING_FULL,
        409,
    )
    after = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert after["waitlist_count"] == 5
    assert after["confirmed_enrollment_count"] == 1
    assert after["status"] == "WAITLIST_ONLY"
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"learner_id": seventh["id"]})
    )
    assert meta["total_count"] == 0


def test_offering_read_exposes_live_seat_and_revenue_counters(api):
    """PRD 3.2: "Of the counters, `confirmed_enrollment_count` is the number of
    registrations on the section whose `enrollment_status` is `ENROLLED`;
    `paid_enrollment_count` is the number whose `enrollment_status` is `ENROLLED`
    **and** whose `payment_status` is either `PAID` or `VOUCHER_COMMITTED`; and
    `waitlist_count` is the number whose `enrollment_status` is `WAITLISTED`."
    PRD 3.6: "For each line, take its gross as `amount_paid_cents` less
    `amount_refunded_cents`; compute institutional overhead as that gross multiplied by
    an overhead rate of 18.5 percent, **rounded half up to whole cents at this point,
    per line**; then subtract that overhead and a flat platform fee of 250 cents per
    registration from the gross to obtain the line's net."

    Design: Corner/endpoints/offering_read_exposes_live_seat_and_revenue_counters
    """
    reset_clock()
    scene = setup_open_offering()
    add_paid_registration(scene["offering_id"], learner_index=0)
    ben = new_learner(email="ben@x.com", full_name="Ben Osei")
    register_learner(scene["offering_id"], ben["id"], as_registrar=True)

    data = validate_success(api.get_offering(scene["offering_id"], REGISTRAR))
    assert data["confirmed_enrollment_count"] == 1
    assert data["paid_enrollment_count"] == 1
    assert data["waitlist_count"] == 0
    assert data["net_program_revenue_cents"] == 50606, (
        f"62400 gross less 11544 overhead less 250 platform fee is 50606, got "
        f"{data['net_program_revenue_cents']}"
    )
    assert data["status"] == "OPEN"


def test_payment_response_already_reports_the_settled_seat_and_counters(api):
    """PRD 2.9: "There is no deferred recomputation and no eventual consistency
    anywhere in this system; a read issued immediately after a write observes every
    consequence of that write."
    PRD 3.5: "If `confirmed_enrollment_count` is strictly below `max_enrollment`, the
    registration moves `PENDING → ENROLLED`, its `enrolled_at` is stamped with the
    current logical-clock instant, and the section's `confirmed_enrollment_count` and
    `paid_enrollment_count` each increase by 1."
    PRD 2.5: "The server starts with its logical clock positioned at exactly
    `2026-08-01T00:00:00Z` and must not fall back to real wall-clock time either before
    or after the clock has been repositioned."

    Design: Corner/consistency_model/immediate_consistency_pay_response_carries_settled_seat_and_price
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")
    registration = register_learner(scene["offering_id"], learner["id"], scene["version"])

    data = validate_success(
        api.pay_registration(
            registration["id"], pay_payload("SELF_PAY"), make_learner_headers(learner["id"])
        )
    )
    assert data["enrollment_status"] == "ENROLLED"
    assert data["amount_paid_cents"] == 62400
    assert data["enrolled_at"] == "2026-08-01T00:00:00.000Z", (
        f"enrolled_at is stamped from the logical clock, got {data['enrolled_at']}"
    )

    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["confirmed_enrollment_count"] == 1
    assert offering["net_program_revenue_cents"] == 50606
