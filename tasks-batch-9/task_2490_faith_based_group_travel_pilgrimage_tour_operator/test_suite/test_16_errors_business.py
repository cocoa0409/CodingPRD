"""Business refusals across the ladder's lower bands: the mobility and risk
gates on enrolment, the agreement gates, the modification freeze, the tier and
fiscal guards, double reversal, the clergy precondition, terminal purchase and
the two waiver gates."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    active_agreement,
    api_client,
    assign_room,
    confirm_traveler,
    create_advisory,
    create_departure,
    create_sacred_site,
    create_service_booking,
    enrol_traveler,
    expected_base_premium,
    hold_filler_service,
    make_group_leader_headers,
    open_departure,
    open_sales,
    pay,
    program_with_departure,
    publish_advisory,
    purchase_protection,
    quote_protection,
    read_agreement,
    read_departure,
    read_protection,
    read_receipt,
    read_service_booking,
    read_traveler,
    review_protection,
    set_clock,
    validate_error,
    validate_success,
    HOLY_LAND_T1_INVOICE_CENTS,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
FINANCE = TEST_USERS["finance_controller"]
PROTECTION = TEST_USERS["protection_administrator"]
PROTECTION_REVIEWER = TEST_USERS["protection_reviewer"]
PROTECTION_APPROVER = TEST_USERS["protection_approver"]


# ---------------------------------------------------------------------------
# Enrolment: the mobility gate and the suspended departure
# ---------------------------------------------------------------------------


def test_a_wheelchair_traveler_needs_a_coach_with_a_lift(api):
    """PRD §3.5: "When `mobility_code` is `WHEELCHAIR` or `WALKER`, the
    departure's `mobility_accessible_coach` must be true — a cane needs no lift,
    a walker does — failing which the answer is `ERR_MOBILITY_UNSUPPORTED` (HTTP
    422)."

    Design: Corner/errors/wheelchair_traveler_on_a_coach_without_lift_rejected
    """
    stage = open_departure(
        departure_overrides={"mobility_accessible_coach": False}
    )
    departure_id = stage["departure"]["id"]
    assert stage["departure"]["mobility_accessible_coach"] is False

    response = api_client.create_pilgrim(
        {
            "departure_id": departure_id,
            "full_name": "Wheelchair Traveler",
            "date_of_birth": "1952-05-04",
            "room_type_requested": "TWIN",
            "mobility_code": "WHEELCHAIR",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.MOBILITY_UNSUPPORTED.value)

    live = read_departure(departure_id)
    assert live["mobility_accessible_coach"] is False
    assert live["paying_pax_count"] == 0


def test_a_suspended_departure_takes_no_new_traveler_at_all(api):
    """PRD §3.5: "The departure's `risk_posture` must not be `SUSPENDED`; a
    suspended departure takes no new bookings at all and answers
    `ERR_DEPARTURE_SUSPENDED_NO_NEW_BOOKINGS` (HTTP 422), and no acknowledgement
    can unlock it." The posture itself comes from §3.9: "The governing advisory's
    identifier is written to `governing_advisory_id` and its level maps to the
    posture: `NORMAL` gives `OPEN`, `EXERCISE_CAUTION` gives `WATCH`,
    `RECONSIDER` gives `RESTRICTED` and `DO_NOT_TRAVEL` gives `SUSPENDED`."

    Design: Corner/errors/new_booking_on_a_suspended_departure_rejected
    """
    # The departure is left in PLANNING, which enrolment admits, so the posture
    # is the only gate in play: §3.9 moves only an OPEN_FOR_SALE departure on to
    # SALES_CLOSED when the posture turns SUSPENDED.
    _program, departure = program_with_departure()
    advisory = create_advisory(country="IL", level="DO_NOT_TRAVEL", source="MOFA")
    publish_advisory(advisory["id"])

    response = api_client.create_pilgrim(
        {
            "departure_id": departure["id"],
            "full_name": "Late Joiner",
            "date_of_birth": "1975-01-10",
            "room_type_requested": "DOUBLE",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.DEPARTURE_SUSPENDED_NO_NEW_BOOKINGS.value)

    live = read_departure(departure["id"])
    assert live["risk_posture"] == "SUSPENDED"
    assert live["status"] == "PLANNING"
    assert live["paying_pax_count"] == 0


# ---------------------------------------------------------------------------
# Leader agreements
# ---------------------------------------------------------------------------


def test_a_leader_cannot_countersign_the_same_agreement_twice(api):
    """PRD §3.4: "Countersigning moves `PENDING_COUNTERSIGN` to `ACTIVE` and is
    performed under the `GroupLeader` role, whose `X-User-ID` must equal the
    agreement's own `id`; countersigning from any other state is
    `ERR_AGREEMENT_INVALID_STATE`."

    Design: Corner/errors/countersigning_an_agreement_twice_returns_agreement_invalid_state
    """
    _program, departure = program_with_departure()
    agreement = active_agreement(
        departure["id"],
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=6,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6_000,
        accrual_basis="RECRUITED",
    )
    assert agreement["status"] == "ACTIVE"

    response = api_client.countersign_agreement(
        agreement["id"], make_group_leader_headers(agreement["id"])
    )
    validate_error(response, ApiErrorId.AGREEMENT_INVALID_STATE.value)

    assert read_agreement(agreement["id"])["status"] == "ACTIVE"


def test_a_november_agreement_cannot_recruit_onto_the_december_departure(api):
    """PRD §3.5: "When a `recruited_by_agreement_id` is supplied, that
    agreement's `departure_id` must equal the supplied `departure_id` and its
    `status` must be `PENDING_COUNTERSIGN` or `ACTIVE`, failing which the answer
    is `ERR_AGREEMENT_DEPARTURE_MISMATCH` (HTTP 422)."

    Design: Corner/errors/recruiting_agreement_from_another_departure_rejected
    """
    program, november = program_with_departure()
    december = create_departure(
        program["id"],
        departure_date="2026-12-06",
        return_date="2026-12-16",
        deposit_due_date="2026-09-20",
        final_payment_due_date="2026-11-20",
    )
    agreement = active_agreement(
        november["id"],
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=6,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6_000,
        accrual_basis="RECRUITED",
    )
    hold_filler_service(program, november)
    hold_filler_service(program, december)
    open_sales(november["id"])
    open_sales(december["id"])

    response = api_client.create_pilgrim(
        {
            "departure_id": december["id"],
            "recruited_by_agreement_id": agreement["id"],
            "full_name": "Misfiled Recruit",
            "date_of_birth": "1975-01-10",
            "room_type_requested": "DOUBLE",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.AGREEMENT_DEPARTURE_MISMATCH.value)

    assert read_departure(december["id"])["paying_pax_count"] == 0
    assert read_agreement(agreement["id"])["recruited_paying_count"] == 0


def test_a_free_seat_cannot_be_granted_before_one_is_earned(api):
    """PRD §3.5: "When `is_free_seat_grant` is true, a
    `recruited_by_agreement_id` must be present and that agreement's
    `earned_free_seats` must be strictly greater than its
    `free_seats_granted_count` — there must be an unconsumed earned seat —
    failing which the answer is `ERR_NO_EARNED_FREE_SEAT` (HTTP 422)." The
    accrual it reads is §3.4's: "From the recruited count the calculation derives
    the earned free seats as the recruited count divided by the agreement's
    `free_travel_threshold` using **integer floor division** — two recruits
    against a threshold of three earns zero seats, not a fraction of one."

    Design: Corner/errors/free_seat_grant_without_an_earned_seat_rejected
    """
    program, departure = program_with_departure()
    agreement = active_agreement(
        departure["id"],
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=6,
        commission_mode="FREE_SEAT_CREDIT",
        commission_rate_cents_per_pax=0,
        accrual_basis="RECRUITED",
    )
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    recruit = enrol_traveler(
        departure["id"],
        full_name="Recruit One",
        date_of_birth="1975-01-10",
        recruited_by_agreement_id=agreement["id"],
    )
    assign_room(recruit["id"])
    pay(recruit["id"], 50_000, method="PARISH_TRANSFER")

    response = api_client.create_pilgrim(
        {
            "departure_id": departure["id"],
            "recruited_by_agreement_id": agreement["id"],
            "full_name": "Premature Free Seat",
            "date_of_birth": "1968-09-09",
            "room_type_requested": "SINGLE",
            "is_free_seat_grant": True,
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.NO_EARNED_FREE_SEAT.value)

    accrual = read_agreement(agreement["id"])
    # One recruit against a threshold of six: floor(1 / 6) is zero.
    assert accrual["recruited_paying_count"] == 1
    assert accrual["earned_free_seats"] == 0
    assert accrual["free_seats_granted_count"] == 0
    assert read_departure(departure["id"])["paying_pax_count"] == 1


# ---------------------------------------------------------------------------
# The modification freeze and the closing tier guard
# ---------------------------------------------------------------------------


def test_an_unratified_modification_freezes_confirmations(api):
    """PRD §3.5: "And the departure must not be carrying an unratified
    modification, failing which the answer is
    `ERR_PENDING_MODIFICATION_UNRATIFIED` (HTTP 422)." The proposal that arms it
    is §3.9's: "Proposing sets `pending_modification_required` true, copies the
    reason into `pending_modification_reason`, stamps
    `pending_modification_proposed_by_user_id` with the acting `X-User-ID`,
    copies the delta into `pending_modification_cost_delta_cents`, and increments
    the departure's `version`."

    Design: Corner/errors/confirming_while_a_modification_is_unratified_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    traveler = enrol_traveler(
        departure_id, full_name="Traveler A", date_of_birth="1975-01-10"
    )
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    assert read_traveler(traveler["id"])["booking_status"] == "DEPOSITED"
    validate_success(
        api_client.propose_itinerary_modification(
            departure_id,
            {
                "modification_reason": "Basilica closed for restoration; substituting an alternate site",
                "cost_delta_cents": 250_000,
            },
            PLANNER,
        )
    )

    response = api_client.confirm_pilgrim(traveler["id"], PLANNER)
    validate_error(response, ApiErrorId.PENDING_MODIFICATION_UNRATIFIED.value)

    live = read_departure(departure_id)
    assert live["pending_modification_required"] is True
    assert live["pending_modification_cost_delta_cents"] == 250_000
    # The delta only joins the cumulative figure once it is ratified.
    assert live["itinerary_cost_delta_cents"] == 0
    assert read_traveler(traveler["id"])["booking_status"] == "DEPOSITED"


def test_no_tier_covers_a_fully_paid_count_of_zero(api):
    """PRD §3.1: "Its guards are evaluated in a fixed order: first whether the
    final variant finds a tier covering the fully-paid confirmed paying count,
    including the case of a count of zero, failing which the answer is
    `ERR_NO_APPLICABLE_PRICE_TIER`; then whether that same count reaches the
    departure's `min_pax`, failing which the answer is `ERR_MIN_PAX_NOT_MET`;
    then whether `pending_modification_required` is false, failing which the
    answer is `ERR_PENDING_MODIFICATION_UNRATIFIED`." The final fields are still
    at their opening values because of §3.1: "Opening sales clears
    `final_tier_code` back to unset and `final_per_pax_price_cents` back to 0,
    re-derives the provisional snapshot, re-reads the risk posture, and increments
    the departure's `version`."

    Design: Corner/errors/close_sales_with_no_tier_covering_the_fully_paid_count_rejected
    """
    stage = open_departure(departure_overrides={"min_pax": 2, "max_pax": 9})
    departure_id = stage["departure"]["id"]
    # Two CONFIRMED travelers, neither of them PAID_IN_FULL, so the final
    # variant counts zero and the smallest tier still starts at one traveler.
    for full_name, born in (("Traveler A", "1975-01-10"), ("Traveler B", "1976-03-12")):
        traveler = enrol_traveler(
            departure_id, full_name=full_name, date_of_birth=born
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
        assert confirm_traveler(traveler["id"])["booking_status"] == "CONFIRMED"

    response = api_client.close_departure_sales(departure_id, PLANNER)
    validate_error(response, ApiErrorId.NO_APPLICABLE_PRICE_TIER.value)

    live = read_departure(departure_id)
    assert live["status"] == "OPEN_FOR_SALE"
    assert live["final_tier_code"] is None
    assert live["final_per_pax_price_cents"] == 0


# ---------------------------------------------------------------------------
# The ledger: the fiscal ceiling and double reversal
# ---------------------------------------------------------------------------


def test_a_receipt_one_cent_over_the_ceiling_is_refused(api):
    """PRD §3.7: "The receipt is also subject to a fiscal ceiling:
    `cash_applied_cents` plus the new `amount_cents` must not exceed
    `invoice_total_cents` plus `protection_premium_cents`. This is the one place
    in the system where the protection premium joins the land invoice, and
    exceeding the sum is `ERR_OVERPAYMENT_NOT_ALLOWED` (HTTP 422) — the
    lowest-ranked rule in the whole ladder, so a receipt against a cancelled
    traveler always reports `ERR_PILGRIM_NOT_ACTIVE` rather than the ceiling
    breach."

    Design: Corner/errors/payment_one_cent_above_the_fiscal_ceiling_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"], full_name="Traveler A", date_of_birth="1975-01-10"
    )
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    confirmed = confirm_traveler(traveler["id"])
    assert confirmed["invoice_total_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    assert confirmed["protection_premium_cents"] == 0

    # 50000 already applied plus 527169 is exactly one cent past 577168.
    response = api_client.record_payment(
        traveler["id"], {"amount_cents": 527_169, "method": "ACH"}, FINANCE
    )
    validate_error(response, ApiErrorId.OVERPAYMENT_NOT_ALLOWED.value)

    live = read_traveler(traveler["id"])
    assert live["invoice_total_cents"] == 577_168
    assert live["protection_premium_cents"] == 0
    assert live["cash_applied_cents"] == 50_000


def test_the_same_receipt_cannot_be_reversed_twice(api):
    """PRD §3.7: "The receipt's `status` must be `APPLIED`, and reversing twice
    is `ERR_PAYMENT_ALREADY_REVERSED` (HTTP 409); the traveler must not be
    `CANCELLED`, failing which the answer is `ERR_PILGRIM_NOT_ACTIVE`." And on
    the single unwind: "The receipt's `status` becomes `REVERSED` and
    `reversed_at` is stamped with the logical clock; the traveler's
    `cash_applied_cents` decreases by the receipt's `amount_cents`; a plan that
    had reached `COMPLETED` reverts to `ACTIVE`."

    Design: Corner/errors/reversing_the_same_payment_twice_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"], full_name="Traveler A", date_of_birth="1975-01-10"
    )
    assign_room(traveler["id"])
    receipt = pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    reversed_once = validate_success(
        api_client.reverse_payment(
            receipt["id"], {"reversal_reason": "BANK_RETURNED_THE_TRANSFER"}, FINANCE
        )
    )
    assert reversed_once["status"] == "REVERSED"

    response = api_client.reverse_payment(
        receipt["id"], {"reversal_reason": "BANK_RETURNED_THE_TRANSFER"}, FINANCE
    )
    validate_error(response, ApiErrorId.PAYMENT_ALREADY_REVERSED.value)

    assert read_receipt(receipt["id"])["status"] == "REVERSED"
    live = read_traveler(traveler["id"])
    # The 50000 came back exactly once.
    assert live["cash_applied_cents"] == 0
    assert live["credit_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Services and protection
# ---------------------------------------------------------------------------


def test_a_service_at_a_clergy_site_cannot_be_confirmed_unattended(api):
    """PRD §3.2: "Confirming the booking then moves it to `CONFIRMED`, and its
    own preconditions are asymmetric by design: when the site requires local
    clergy the booking must already be in `CLERGY_CONFIRMED`, and arriving at
    confirmation without that step is `ERR_CLERGY_NOT_CONFIRMED`; when the site
    does not require local clergy the booking must be in `SITE_HELD`, and any
    other state is `ERR_SERVICE_BOOKING_INVALID_STATE`."

    Design: Corner/errors/confirming_a_service_at_a_clergy_site_without_clergy_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    # OPEN_ACCESS, so no permit is owed: the celebrant is the only thing missing.
    site = create_sacred_site(
        name="Church of the Holy Sepulchre",
        country="IL",
        access_regime="OPEN_ACCESS",
        daily_capacity_pax=300,
        turnaround_buffer_minutes=30,
        requires_local_clergy=True,
    )
    booking = create_service_booking(
        departure_id,
        site["id"],
        service_type="MASS",
        scheduled_start_utc="2026-11-03T07:00:00Z",
        duration_minutes=60,
        pax_count=20,
    )
    assert booking["status"] == "SITE_HELD"

    response = api_client.confirm_service_booking(booking["id"], PLANNER)
    validate_error(response, ApiErrorId.CLERGY_NOT_CONFIRMED.value)

    live = read_service_booking(booking["id"])
    assert live["status"] == "SITE_HELD"
    assert live["clergy_contact_name"] is None
    assert read_departure(departure_id)["service_coverage_ok"] is False


def test_a_purchased_policy_cannot_be_purchased_again(api):
    """PRD §3.8: "Purchase requires the record to be in `QUOTED`,
    `WAIVER_APPROVED` or `WAIVER_DECLINED`, and requires a non-cancelled
    traveler." And: "Purchase moves the record to `PURCHASED`, mirrors
    `protection_status`, and copies `premium_cents` onto the traveler's
    `protection_premium_cents`, which raises that traveler's fiscal ceiling for
    receipts." And: "`PURCHASED` and `VOIDED` are terminal." The premium is
    §3.8's: "The `age_band` follows from the traveler's `age_at_departure`: band
    `D` at 75 or above priced at 1,280 basis points (12.8%), band `C` from 65
    through 74 at 910 basis points (9.1%), band `B` from 40 through 64 at 620
    basis points (6.2%), and band `A` at 39 or below at 400 basis points (4%).
    `base_premium_cents` is `insured_trip_cost_cents` multiplied by the band rate
    in basis points, divided by 10,000, rounded half up."

    Design: Corner/errors/purchasing_a_protection_twice_returns_protection_invalid_state
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"], full_name="Traveler A", date_of_birth="1975-01-10"
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="IL-220")
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    quoted = quote_protection(
        traveler["id"],
        plan_code="BASIC",
        medical_limit_cents=1_000_000,
        pre_existing_waiver_requested=False,
    )
    assert quoted["insured_trip_cost_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    bound = purchase_protection(quoted["id"])
    assert bound["status"] == "PURCHASED"

    response = api_client.purchase_protection(quoted["id"], PROTECTION)
    validate_error(response, ApiErrorId.PROTECTION_INVALID_STATE.value)

    live = read_protection(quoted["id"])
    assert live["status"] == "PURCHASED"
    # Age 51 at departure, so band B at 620 basis points of 577168.
    assert live["age_band"] == "B"
    assert live["premium_cents"] == expected_base_premium(
        HOLY_LAND_T1_INVOICE_CENTS, 51
    )
    assert live["premium_cents"] == 35_784
    insured = read_traveler(traveler["id"])
    assert insured["protection_premium_cents"] == 35_784
    assert insured["protection_status"] == "PURCHASED"


def test_forty_five_days_of_stability_falls_short_of_the_waiver_minimum(api):
    """PRD §3.8: "Otherwise it is true only when all three of the following
    hold: `questionnaire_complete` is true; `stable_period_days` is 60 or
    greater; and the whole-day difference between the logical clock's calendar
    date and `deposit_reference_date` is 21 days or fewer." And on the decision:
    "On the `APPROVE` branch two further gates apply, and their order matters:
    first the purchase window, where a whole-day difference between the logical
    clock's date and `deposit_reference_date` strictly greater than 21 days is
    rejected with `ERR_WAIVER_WINDOW_CLOSED` (HTTP 422); then general
    eligibility, where a `waiver_eligible` of false for any other reason — an
    incomplete questionnaire, or a `stable_period_days` below 60 — is rejected
    with `ERR_WAIVER_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/errors/waiver_approval_with_an_unstable_condition_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Senior Traveler",
        date_of_birth="1948-06-20",
    )
    assign_room(
        traveler["id"],
        room_type_assigned="DOUBLE",
        room_label="IL-221",
        ground_floor=True,
    )
    protection = quote_protection(
        traveler["id"],
        plan_code="PREMIER",
        medical_limit_cents=1_000_000,
        pre_existing_waiver_requested=True,
    )
    # The deposit stamps `deposit_reference_date` onto the quote it already owns.
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    reviewed = review_protection(
        protection["id"],
        PROTECTION_REVIEWER,
        questionnaire_complete=True,
        stable_period_days=45,
    )
    assert reviewed["status"] == "MEDICAL_REVIEWED"

    response = api_client.decide_waiver(
        protection["id"], {"decision": "APPROVE"}, PROTECTION_APPROVER
    )
    validate_error(response, ApiErrorId.WAIVER_NOT_ELIGIBLE.value)

    live = read_protection(protection["id"])
    assert live["status"] == "MEDICAL_REVIEWED"
    assert live["questionnaire_complete"] is True
    assert live["stable_period_days"] == 45
    assert live["waiver_eligible"] is False
    assert live["waiver_surcharge_cents"] == 0


def test_a_waiver_approved_twenty_four_days_after_the_deposit_is_too_late(api):
    """PRD §3.8: "On the `APPROVE` branch two further gates apply, and their
    order matters: first the purchase window, where a whole-day difference
    between the logical clock's date and `deposit_reference_date` strictly
    greater than 21 days is rejected with `ERR_WAIVER_WINDOW_CLOSED` (HTTP 422);
    then general eligibility, where a `waiver_eligible` of false for any other
    reason — an incomplete questionnaire, or a `stable_period_days` below 60 — is
    rejected with `ERR_WAIVER_NOT_ELIGIBLE` (HTTP 422)." The anchor is §3.7's:
    "That transition stamps `deposit_reference_date` with the logical clock's
    calendar date on any travel protection the traveler owns, anchoring the
    waiver window; recomputes the departure's `paying_pax_count` and provisional
    tier fields; recomputes the recruiting agreement's snapshot accrual; and
    recomputes `seats_assigned` on the departure's seat blocks, since the derived
    seat count is scoped to `DEPOSITED` and `CONFIRMED` travelers."

    Design: Corner/errors/waiver_approval_after_the_purchase_window_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Senior Traveler",
        date_of_birth="1948-06-20",
    )
    assign_room(
        traveler["id"],
        room_type_assigned="DOUBLE",
        room_label="IL-222",
        ground_floor=True,
    )
    protection = quote_protection(
        traveler["id"],
        plan_code="PREMIER",
        medical_limit_cents=1_000_000,
        pre_existing_waiver_requested=True,
    )
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    reviewed = review_protection(
        protection["id"],
        PROTECTION_REVIEWER,
        questionnaire_complete=True,
        stable_period_days=90,
    )
    assert reviewed["deposit_reference_date"] == "2026-08-01"
    # 24 whole days after the deposit: three days past the 21-day window.
    set_clock("2026-08-25T00:00:00Z")

    response = api_client.decide_waiver(
        protection["id"], {"decision": "APPROVE"}, PROTECTION_APPROVER
    )
    validate_error(response, ApiErrorId.WAIVER_WINDOW_CLOSED.value)

    live = read_protection(protection["id"])
    assert live["status"] == "MEDICAL_REVIEWED"
    assert live["deposit_reference_date"] == "2026-08-01"
    assert live["stable_period_days"] == 90
