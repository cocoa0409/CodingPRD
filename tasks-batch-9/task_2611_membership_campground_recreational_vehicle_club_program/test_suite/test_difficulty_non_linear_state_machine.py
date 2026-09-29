"""State machines that branch, cycle and run two axes on one row."""

from test_helpers import (
    ADMIN,
    OFFICER,
    assert_entitlement_counters,
    assert_membership_axes,
    book_member_stay,
    check_in,
    create_classic_tier,
    create_open_park,
    create_president_tier,
    list_invoices,
    list_reservation_exceptions,
    make_exception_decision_payload,
    make_extension_payload,
    make_payment_payload,
    make_reinstatement_payload,
    make_suspension_payload,
    read_invoice,
    read_membership,
    read_reservation,
    reset_clock,
    sell_membership_to_new_member,
    set_clock,
    validate_success,
)


def _president_holder_15_days_past_due(api):
    """One ACTIVE, dues-CURRENT contract whose only invoice is 15 days late."""
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=1850000)
    invoice = list_invoices(api, holder["membership_id"])[0]
    set_clock(api, "2026-09-15")
    return holder, invoice


def test_billing_axis_reaches_grace_while_the_contract_axis_stays_active(api):
    """A late invoice moves only the billing axis; the contract axis does not follow.

    PRD §3.7: "A membership with an `OPEN` or `PAST_DUE` invoice whose
    `days_past_due` is at least 1 and below 30 moves from `CURRENT` to `GRACE`."

    Design: Difficulty/non_linear_state_machine/membership_contract_and_dues_axes_advance_independently
    """
    holder, invoice = _president_holder_15_days_past_due(api)

    validate_success(api.run_dues_delinquency(ADMIN), 200)

    aged = read_invoice(api, invoice["id"])
    assert aged["status"] == "PAST_DUE", "the grace threshold of 1 day has been crossed"
    assert aged["days_past_due"] == 15, "2026-09-15 less the 2026-08-31 due date"
    # 59508 * 1.5% * ceil(15/30) = 892.62, one half-up rounding at the end.
    assert aged["late_fee_cents"] == 893, "one multiplication and exactly one rounding"

    membership = read_membership(api, holder["membership_id"])
    assert_membership_axes(membership, "ACTIVE", "GRACE")
    assert membership["dues_balance_cents"] == 60401, (
        "the balance carries amount plus late fee less anything paid"
    )

    suspended = validate_success(
        api.suspend_membership(
            holder["membership_id"], make_suspension_payload(suspension_reason="ADMIN_ACTION"), ADMIN
        ),
        200,
    )
    assert_membership_axes(suspended, "SUSPENDED", "GRACE", suspension_reason="ADMIN_ACTION")


def test_payment_clears_the_billing_axis_without_lifting_the_suspension(api):
    """Settling the dues returns CURRENT but leaves SUSPENDED for a separate act.

    PRD §3.7: "Note carefully what a payment does **not** do: a membership that
    was suspended for delinquency stays `SUSPENDED` on the contract axis even
    after its dues return to `CURRENT`."

    Design: Difficulty/non_linear_state_machine/membership_contract_and_dues_axes_advance_independently
    """
    holder, invoice = _president_holder_15_days_past_due(api)
    validate_success(api.run_dues_delinquency(ADMIN), 200)
    validate_success(
        api.suspend_membership(
            holder["membership_id"], make_suspension_payload(suspension_reason="ADMIN_ACTION"), ADMIN
        ),
        200,
    )

    paid = validate_success(
        api.pay_dues_invoice(invoice["id"], make_payment_payload(60401), holder["headers"]), 200
    )
    assert paid["status"] == "PAID", "a settling payment moves the invoice to PAID"
    assert paid["paid_amount_cents"] == 60401, "the tendered figure is recorded"

    membership = read_membership(api, holder["membership_id"])
    assert_membership_axes(membership, "SUSPENDED", "CURRENT")
    assert membership["dues_balance_cents"] == 0, "nothing is left OPEN or PAST_DUE"

    reinstated = validate_success(
        api.reinstate_membership(
            holder["membership_id"],
            make_reinstatement_payload(reinstatement_fee_paid_cents=15000),
            ADMIN,
        ),
        200,
    )
    assert_membership_axes(reinstated, "ACTIVE", "CURRENT", suspension_reason=None)


def _checked_in_ten_night_classic_stay(api):
    """A CLASSIC contract ten nights into a CLASS_C stay, already CHECKED_IN."""
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=795000)
    park = create_open_park(
        api,
        name="Pinyon Flats RV Park",
        park_class="CLASS_C",
        total_sites=20,
        member_allocation_pct=60,
    )
    reservation = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-05", "2026-08-15"
    )
    check_in(api, reservation["id"], holder["headers"], "2026-08-05")
    return holder, park, reservation


def test_extension_beyond_the_tier_limit_routes_into_review(api):
    """The overrun branch parks the stay in review and debits nothing yet.

    PRD §3.5: "On this branch `departure_date` is set to `new_departure_date`
    immediately, but **no entitlement is debited yet**: the added nights are
    charged only if the exception is granted, and `departure_date` is rolled back
    if it is denied."

    Design: Difficulty/non_linear_state_machine/reservation_checked_in_extension_review_cycle_returns_to_checked_in
    """
    holder, _park, reservation = _checked_in_ten_night_classic_stay(api)

    extended = validate_success(
        api.extend_reservation(
            reservation["id"],
            make_extension_payload("2026-08-22", reason="RIG_REPAIR"),
            holder["headers"],
        ),
        200,
    )
    assert extended["status"] == "EXTENSION_REVIEW", "the tier overrun routes into review"
    assert extended["departure_date"] == "2026-08-22", "the requested date is taken immediately"

    exceptions = list_reservation_exceptions(api, reservation["id"])
    assert len(exceptions) == 1, "one occupancy exception is opened"
    assert exceptions[0]["status"] == "REQUESTED"
    assert exceptions[0]["requested_run_nights"] == 17, "2026-08-05 through 2026-08-22"
    assert exceptions[0]["tier_limit_nights"] == 14, "the tier limit is captured at request time"
    assert exceptions[0]["granted_run_nights"] == 0

    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_c=10, annual=10)


def test_denied_exception_returns_the_stay_to_checked_in_for_another_try(api):
    """A denial rolls the stay back and the reservation may extend again in-tier.

    PRD §3.5: "The reservation also returns from `EXTENSION_REVIEW` to
    `CHECKED_IN`, but its `departure_date` is rolled back to the value it held
    before the extension was requested, no entitlement or partner quota is
    debited at all, and `extension_denied_count` increases by 1."

    Design: Difficulty/non_linear_state_machine/reservation_checked_in_extension_review_cycle_returns_to_checked_in
    """
    holder, _park, reservation = _checked_in_ten_night_classic_stay(api)
    validate_success(
        api.extend_reservation(
            reservation["id"],
            make_extension_payload("2026-08-22", reason="RIG_REPAIR"),
            holder["headers"],
        ),
        200,
    )
    exception = list_reservation_exceptions(api, reservation["id"])[0]

    decided = validate_success(
        api.decide_occupancy_exception(
            exception["id"],
            make_exception_decision_payload(
                "DENY", decision_note="No policy basis for a 17-night run"
            ),
            OFFICER,
        ),
        200,
    )
    assert decided["status"] == "DENIED"
    assert decided["granted_run_nights"] == 0

    rolled_back = read_reservation(api, reservation["id"])
    assert rolled_back["status"] == "CHECKED_IN", "the review cycle returns to CHECKED_IN"
    assert rolled_back["departure_date"] == "2026-08-15", "the pre-extension date is restored"
    assert rolled_back["extension_denied_count"] == 1

    again = validate_success(
        api.extend_reservation(
            reservation["id"],
            make_extension_payload("2026-08-18", reason="RIG_REPAIR"),
            holder["headers"],
        ),
        200,
    )
    assert again["status"] == "CHECKED_IN", "an in-tier extension is a self-loop"
    assert again["departure_date"] == "2026-08-18"
    assert again["extension_count"] == 1
    assert again["consecutive_run_nights"] == 13, "2026-08-05 through 2026-08-18"

    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_c=13, annual=13)
