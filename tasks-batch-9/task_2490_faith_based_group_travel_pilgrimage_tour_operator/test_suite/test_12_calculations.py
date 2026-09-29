"""Single-formula arithmetic at pinned inputs: the deviation fee and the invoice
it moves, the installment remainder, the paying-set filter, the lowest premium
band, and the closed tier boundary."""

from __future__ import annotations

from test_helpers import (
    api_client,
    active_agreement,
    assign_room,
    confirmed_air_block,
    confirmed_traveler,
    create_departure,
    create_program,
    enrol_traveler,
    expected_base_premium,
    expected_installment_amounts,
    expected_invoice_total,
    hold_filler_service,
    marian_shrines_program_payload,
    open_departure,
    open_sales,
    pay,
    program_with_departure,
    read_agreement,
    read_departure,
    read_traveler,
    two_tier_program_payload,
    validate_success,
    HOLY_LAND_T1_INVOICE_CENTS,
    MARIAN_SHRINES_S1_INVOICE_CENTS,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
FINANCE = TEST_USERS["finance_controller"]
PROTECTION = TEST_USERS["protection_administrator"]


def test_an_origin_change_ninety_two_days_out_takes_the_parity_multiplier(api):
    """PRD §3.6: "The base depends on the type: an `ORIGIN_CHANGE` costs a flat
    $125.00 (12,500 cents); a `DATE_DEVIATION` costs a flat $90.00 (9,000
    cents); a `CLASS_UPGRADE` is priced off the contracted block fare, as the
    block's `contracted_fare_cents` multiplied by 4,500 basis points (45%),
    divided by 10,000, rounded half up to whole cents. A lateness multiplier
    then applies: the whole-day difference between the departure's
    `departure_date` and the logical clock's date is compared against 30 days,
    and when it is 30 days or fewer the multiplier is 15,000 basis points (1.5
    times), and otherwise it is 10,000 basis points (parity, leaving the base
    unchanged)."

    Design: Corner/calculations/air_deviation_origin_change_fee_reprices_invoice
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    confirmed_air_block(departure_id, offered_fare_cents=810_000)
    traveler = confirmed_traveler(departure_id)

    updated = validate_success(
        api_client.record_air_deviation(
            traveler["id"], {"deviation_type": "ORIGIN_CHANGE"}, AIR_DESK
        )
    )

    assert updated["deviation_type"] == "ORIGIN_CHANGE"
    # 2026-08-01 to 2026-11-01 is 92 days, so the flat base stands unmultiplied.
    assert updated["deviation_fee_cents"] == 12_500
    assert updated["price_locked_cents"] == 587_000
    assert updated["invoice_total_cents"] == expected_invoice_total(587_000, 0, 12_500)
    assert updated["invoice_total_cents"] == 589_458


def test_a_six_month_plan_loads_its_remainder_cents_onto_the_earliest_dues(api):
    """PRD §3.7: "The remainder cents load onto the **earliest** installments,
    one cent each: the installment at `sequence_no` 1 through the installment at
    `sequence_no` equal to the remainder each carry the base amount plus one
    cent, and the rest carry the base amount exactly. The due date of installment
    1 is `first_due_date`, and each later installment falls one further calendar
    month on, keeping the same day of month but clamping to the last day of a
    shorter month — a plan whose `first_due_date` is the 31st bills the 28th or
    29th in February."

    Design: Corner/calculations/payment_plan_monthly_6_remainder_loads_earliest_installments
    """
    stage = open_departure()
    traveler = confirmed_traveler(stage["departure"]["id"])

    created = validate_success(
        api_client.create_payment_plan(
            traveler["id"],
            {
                "plan_type": "MONTHLY_6",
                "first_due_date": "2026-08-15",
                "expected_pilgrim_version": traveler["version"],
            },
            FINANCE,
        ),
        201,
    )

    assert created["installment_count"] == 6
    assert created["total_scheduled_cents"] == HOLY_LAND_T1_INVOICE_CENTS
    # 577168 = 6 * 96194 + 4, so the first four installments carry the odd cents.
    amounts = expected_installment_amounts(HOLY_LAND_T1_INVOICE_CENTS, 6)
    assert amounts == [96_195, 96_195, 96_195, 96_195, 96_194, 96_194]
    assert [item["amount_due_cents"] for item in created["installments"]] == amounts
    assert created["installments"][0]["due_date"] == "2026-08-15"
    assert created["installments"][5]["due_date"] == "2027-01-15"
    assert created["status"] == "ACTIVE"


def test_a_free_seat_grant_enters_neither_the_tier_count_nor_the_accrual(api):
    """PRD §3.5: "A successful enrolment writes `booking_status` `INQUIRY`,
    `payment_status` `UNPAID` and `protection_status` `NONE`; sets `is_paying` to
    the logical negation of `is_free_seat_grant`; computes `age_at_departure` as
    the number of complete years between `date_of_birth` and the departure's
    `departure_date`, floored, so a traveler whose birthday falls the day after
    departure is one year younger for every purpose in this system; increments
    the recruiting agreement's `free_seats_granted_count` when the booking is a
    free seat; and recomputes both the departure's provisional tier snapshot and
    the recruiting agreement's snapshot accrual." The counted population is
    §3.1: "`paying_pax_count` is the number of travelers on the departure whose
    `is_paying` is true and whose `booking_status` is `DEPOSITED` or `CONFIRMED`
    — the same population the provisional variant prices from — and it opens at 0
    and is refreshed on every roster movement."

    Design: Corner/calculations/free_seat_grant_excluded_from_paying_counts
    """
    program, departure = program_with_departure()
    agreement = active_agreement(
        departure["id"],
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=1,
        commission_mode="FREE_SEAT_CREDIT",
        commission_rate_cents_per_pax=0,
        accrual_basis="RECRUITED",
    )
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    recruit = enrol_traveler(
        departure["id"],
        full_name="Recruit One",
        recruited_by_agreement_id=agreement["id"],
    )
    assign_room(recruit["id"])
    pay(recruit["id"], 50_000, method="PARISH_TRANSFER")

    created = validate_success(
        api_client.create_pilgrim(
            {
                "departure_id": departure["id"],
                "recruited_by_agreement_id": agreement["id"],
                "full_name": "Leader Free Seat",
                "date_of_birth": "1968-09-09",
                "room_type_requested": "SINGLE",
                "is_free_seat_grant": True,
            },
            PLANNER,
        ),
        201,
    )

    assert created["is_free_seat_grant"] is True
    assert created["is_paying"] is False

    live = read_departure(departure["id"])
    assert live["paying_pax_count"] == 1
    assert live["provisional_tier_code"] == "T1"

    accrual = read_agreement(agreement["id"])
    assert accrual["recruited_paying_count"] == 1
    assert accrual["earned_free_seats"] == 1
    assert accrual["free_seats_granted_count"] == 1
    assert accrual["commission_payable_cents"] == 0


def test_the_youngest_age_band_prices_at_four_hundred_basis_points(api):
    """PRD §3.8: "The `age_band` follows from the traveler's `age_at_departure`:
    band `D` at 75 or above priced at 1,280 basis points (12.8%), band `C` from
    65 through 74 at 910 basis points (9.1%), band `B` from 40 through 64 at 620
    basis points (6.2%), and band `A` at 39 or below at 400 basis points (4%).
    `base_premium_cents` is `insured_trip_cost_cents` multiplied by the band rate
    in basis points, divided by 10,000, rounded half up."

    Design: Corner/calculations/protection_premium_band_a_uses_lowest_age_constant
    """
    program = create_program(marian_shrines_program_payload(duration_days=9))
    departure = create_departure(program["id"], max_pax=30)
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    traveler = enrol_traveler(
        departure["id"],
        full_name="Young Traveler",
        date_of_birth="1991-01-10",
        room_type_requested="DOUBLE",
    )
    assign_room(traveler["id"], room_type_assigned="DOUBLE", room_label="PT-301")
    pay(traveler["id"], 30_000, method="CARD")

    created = validate_success(
        api_client.create_protection(
            {
                "pilgrim_id": traveler["id"],
                "plan_code": "BASIC",
                "medical_limit_cents": 1_000_000,
                "pre_existing_waiver_requested": False,
            },
            PROTECTION,
        ),
        201,
    )

    priced = read_traveler(traveler["id"])
    # 299000 gross sits below the 300000 grant floor, so no grant is deducted.
    assert priced["invoice_total_cents"] == MARIAN_SHRINES_S1_INVOICE_CENTS
    assert priced["age_at_departure"] == 35
    assert created["age_band"] == "A"
    assert created["insured_trip_cost_cents"] == MARIAN_SHRINES_S1_INVOICE_CENTS
    assert created["base_premium_cents"] == expected_base_premium(
        MARIAN_SHRINES_S1_INVOICE_CENTS, 35
    )
    assert created["base_premium_cents"] == 12_379
    assert created["medical_uplift_cents"] == 0
    assert created["waiver_surcharge_cents"] == 0
    assert created["premium_cents"] == 12_379
    assert created["status"] == "QUOTED"


def test_the_second_deposit_crosses_the_closed_tier_boundary_at_two(api):
    """PRD §3.1: "Tier selection itself is the same in both variants: the single
    item of `price_tiers` whose range contains the effective count, where the
    range is a **closed interval** inclusive at both ends."

    Design: Corner/calculations/provisional_tier_crosses_p1_to_p2_on_second_deposit
    """
    program = create_program(two_tier_program_payload())
    departure = create_departure(program["id"], max_pax=3)
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    first = enrol_traveler(
        departure["id"], full_name="Traveler A", date_of_birth="1975-01-10"
    )
    second = enrol_traveler(
        departure["id"], full_name="Traveler B", date_of_birth="1976-03-12"
    )
    assign_room(first["id"])
    assign_room(second["id"])
    pay(first["id"], 60_000, method="ACH")
    assert read_departure(departure["id"])["provisional_tier_code"] == "P1"

    created = validate_success(
        api_client.record_payment(
            second["id"], {"amount_cents": 60_000, "method": "ACH"}, FINANCE
        ),
        201,
    )
    assert created["amount_cents"] == 60_000

    assert read_traveler(second["id"])["booking_status"] == "DEPOSITED"
    live = read_departure(departure["id"])
    assert live["paying_pax_count"] == 2
    assert live["provisional_tier_code"] == "P2"
    assert live["provisional_per_pax_price_cents"] == 587_000
    assert live["provisional_single_supplement_cents"] == 98_000
    assert live["provisional_deposit_cents"] == 50_000
