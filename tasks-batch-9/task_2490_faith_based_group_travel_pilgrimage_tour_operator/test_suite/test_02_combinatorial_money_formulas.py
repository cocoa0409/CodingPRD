"""Formulas whose answer depends on several independent inputs at once:
the four-input protection premium, the per-line land conversion, and the
grant tier that is keyed on the gross rather than on the post-fee total."""

from __future__ import annotations

from test_helpers import (
    assign_room,
    confirmed_traveler,
    countersign_land_assignment,
    create_departure,
    create_land_assignment,
    create_land_resource,
    create_program,
    decide_waiver,
    enrol_traveler,
    hold_filler_service,
    marian_shrines_program_payload,
    open_sales,
    pay,
    program_with_departure,
    quote_protection,
    read_departure,
    read_land_assignment,
    review_protection,
    rome_jubilee_program_payload,
    set_clock,
    TEST_USERS,
)

REVIEWER = TEST_USERS["protection_reviewer"]
APPROVER = TEST_USERS["protection_approver"]


# ---------------------------------------------------------------------------
# Four-input protection premium
# ---------------------------------------------------------------------------


def _senior_waiver_approved_protection():
    """A band-D traveler on a high-value programme, waiver approved in window."""
    program = create_program(payload=rome_jubilee_program_payload())
    departure = create_departure(
        program["id"],
        departure_date="2027-03-14",
        return_date="2027-03-22",
        min_pax=1,
        max_pax=12,
        deposit_due_date="2026-09-01",
        final_payment_due_date="2027-01-15",
    )
    traveler = enrol_traveler(
        departure["id"], full_name="Aldo Ferri", date_of_birth="1948-06-20"
    )
    assign_room(traveler["id"])
    # The quote must exist before the deposit lands: §3.7 says the crossing
    # receipt "stamps `deposit_reference_date` ... on any travel protection the
    # traveler owns", and §3.8 makes an unset reference date fatal to eligibility.
    protection = quote_protection(
        traveler["id"],
        plan_code="PREMIER",
        medical_limit_cents=5_000_000,
        pre_existing_waiver_requested=True,
    )
    pay(traveler["id"], 200_000)
    review_protection(protection["id"], REVIEWER, stable_period_days=90)
    set_clock("2026-08-10T00:00:00Z")
    decided = decide_waiver(protection["id"], "APPROVE", APPROVER)
    return traveler, decided


def test_protection_premium_combines_band_zero_uplift_and_capped_surcharge(api):
    """PRD §3.8: "The medical uplift then applies only when
    `medical_limit_cents` is **strictly greater** than $50,000.00 (5,000,000
    cents): a limit exactly at the threshold attracts no uplift, and above it
    `medical_uplift_cents` is `base_premium_cents` multiplied by 1,500 basis
    points (15%), divided by 10,000, rounded half up; otherwise it is 0."

    Design: Difficulty/combinatorial_formula/protection_premium_four_input_band_uplift_cap_combination
    """
    _traveler, decided = _senior_waiver_approved_protection()

    assert decided["age_band"] == "D"
    # 1966500 * 1280bp = 251712 exactly.
    assert decided["base_premium_cents"] == 251_712
    # A limit exactly at 5,000,000 cents attracts no uplift.
    assert decided["medical_uplift_cents"] == 0
    # 251712 * 2200bp = 55376.64 -> 55377, capped at 45000.
    assert decided["waiver_surcharge_cents"] == 45_000
    assert decided["premium_cents"] == 296_712


def test_protection_premium_captures_the_travelers_invoice_as_the_insured_trip_cost(api):
    """PRD §3.8: "The premium is re-derived at quote, at medical review, at
    waiver decision and at purchase, and each time it begins by capturing
    `insured_trip_cost_cents` from the traveler's current
    `invoice_total_cents`."

    Design: Difficulty/combinatorial_formula/protection_premium_four_input_band_uplift_cap_combination
    """
    traveler, decided = _senior_waiver_approved_protection()

    # A March 2027 departure against a June 1948 birthday: 78 complete years.
    assert traveler["age_at_departure"] == 78
    # gross 2000000 -> grant 100000 -> net 1900000 -> fee 66500 -> 1966500.
    assert decided["insured_trip_cost_cents"] == 1_966_500
    assert decided["status"] == "WAIVER_APPROVED"
    assert decided["waiver_eligible"] is True


# ---------------------------------------------------------------------------
# Land rollup: round per line, then sum
# ---------------------------------------------------------------------------


def _three_countersigned_land_lines():
    """Three lines over the same five inclusive days at one FX rate."""
    _program, departure = program_with_departure()
    departure_id = departure["id"]

    hotel = create_land_resource(
        operator_name="Terra Santa DMC Rooms",
        resource_type="HOTEL_ROOM_BLOCK",
        units_total=30,
        unit_rate_local_cents=45_000,
        fx_rate_bp=10_833,
        force_majeure_notice_days=45,
    )
    coach = create_land_resource(
        operator_name="Terra Santa DMC Coaches",
        resource_type="MOTORCOACH",
        units_total=3,
        unit_rate_local_cents=127_500,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )
    guide = create_land_resource(
        operator_name="Terra Santa DMC Guides",
        resource_type="GUIDE",
        units_total=4,
        unit_rate_local_cents=62_500,
        fx_rate_bp=10_833,
        force_majeure_notice_days=21,
    )

    lines = {}
    for key, resource, units in (
        ("hotel", hotel, 6),
        ("coach", coach, 1),
        ("guide", guide, 2),
    ):
        lines[key] = create_land_assignment(
            resource["id"],
            departure_id,
            date_from="2026-11-01",
            date_to="2026-11-05",
            units_requested=units,
        )

    countersign_land_assignment(lines["hotel"]["id"])
    countersign_land_assignment(lines["coach"]["id"])
    countersigned_guide = countersign_land_assignment(lines["guide"]["id"])
    return departure_id, lines, countersigned_guide


def test_each_land_line_converts_its_own_local_amount_to_whole_cents(api):
    """PRD §3.3: "From there the server computes `line_local_cents` as
    `units_requested` multiplied by `days_inclusive` multiplied by the
    resource's `unit_rate_local_cents`, and then `line_usd_cents` as
    `line_local_cents` multiplied by the resource's `fx_rate_bp`, divided by
    10,000, and rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/land_rollup_round_per_line_then_sum_order
    """
    _departure_id, lines, countersigned_guide = _three_countersigned_land_lines()

    hotel = read_land_assignment(lines["hotel"]["id"])
    assert hotel["days_inclusive"] == 5
    assert hotel["line_local_cents"] == 1_350_000
    assert hotel["line_usd_cents"] == 1_462_455

    coach = read_land_assignment(lines["coach"]["id"])
    assert coach["line_local_cents"] == 637_500
    # 637500 * 10833 / 10000 = 690603.75 -> 690604.
    assert coach["line_usd_cents"] == 690_604

    assert countersigned_guide["line_local_cents"] == 625_000
    # 625000 * 10833 / 10000 = 677062.5 -> 677063.
    assert countersigned_guide["line_usd_cents"] == 677_063


def test_land_rollup_sums_already_rounded_lines_rather_than_converting_once(api):
    """PRD §3.3: "The rounding order is pinned: each line is rounded to whole
    USD cents **first**, and the already-rounded lines are then added. Summing
    local amounts across lines and converting once at the end is forbidden and
    yields an off-by-cents total whenever two or more lines convert to
    fractional cents."

    Design: Difficulty/combinatorial_formula/land_rollup_round_per_line_then_sum_order
    """
    departure_id, _lines, _guide = _three_countersigned_land_lines()

    departure = read_departure(departure_id)
    # 1462455 + 690604 + 677063, each rounded before the addition.
    assert departure["land_cost_total_cents"] == 2_830_122
    # Converting the summed local amount once would have yielded 2830121.
    assert departure["land_cost_total_cents"] != 2_830_121


# ---------------------------------------------------------------------------
# Grant tier keyed on the gross
# ---------------------------------------------------------------------------


def _marian_confirmed_traveler():
    program = create_program(payload=marian_shrines_program_payload())
    departure = create_departure(
        program["id"],
        departure_date="2026-10-05",
        return_date="2026-10-12",
        min_pax=1,
        max_pax=30,
        deposit_due_date="2026-08-20",
        final_payment_due_date="2026-09-05",
        mobility_accessible_coach=False,
    )
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    traveler = confirmed_traveler(
        departure["id"],
        deposit_cents=30_000,
        full_name="Rosa Neves",
        date_of_birth="1991-09-09",
    )
    return departure, traveler


def test_invoice_grant_rate_is_selected_from_the_gross_not_the_post_fee_total(api):
    """PRD §3.5: "Select the parish-grant rate **from the gross, and only from
    the gross**: when the gross is greater than or equal to $5,000.00 (500,000
    cents) the grant rate is 5% (500 basis points); otherwise when the gross is
    greater than or equal to $3,000.00 (300,000 cents) the grant rate is 3%
    (300 basis points); otherwise there is no grant and the rate is 0."

    Design: Difficulty/combinatorial_formula/invoice_grant_tier_keyed_on_gross_not_total
    """
    _departure, traveler = _marian_confirmed_traveler()

    # gross 299000 is under 300000, so no grant: net 299000, fee 10465.
    assert traveler["invoice_total_cents"] == 309_465
    # Keying the 3% grant on the post-fee total 309465 would have given 300181.
    assert traveler["invoice_total_cents"] != 300_181


def test_invoice_gross_is_built_from_price_supplement_and_deviation_fee(api):
    """PRD §3.5: "Form the gross by adding the effective per-pax price, the
    traveler's `single_supplement_applied_cents` and the traveler's
    `deviation_fee_cents`."

    Design: Difficulty/combinatorial_formula/invoice_grant_tier_keyed_on_gross_not_total
    """
    departure, traveler = _marian_confirmed_traveler()

    assert traveler["price_locked_cents"] == 299_000
    assert traveler["single_supplement_applied_cents"] == 0
    assert traveler["deviation_fee_cents"] == 0

    live = read_departure(departure["id"])
    assert live["provisional_tier_code"] == "S1"
