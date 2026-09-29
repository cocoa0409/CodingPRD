"""The escort requirement matrix as a five-input formula under a hard cap.

Two permits filed in the same state against the same order sit on opposite sides
of the four-escort ceiling: one accumulates six raw increments and is clamped,
the other accumulates three and is returned untouched. Both permits' provisional
fees are priced from the escort figure the matrix actually returned.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_transport_permit,
    create_permit_payload,
    measure_section,
    open_order,
    record_section,
    register_plant,
    release_section,
    set_logical_clock,
    validate_success,
)

PERMIT_DESK = TEST_USERS["permit_desk_headers"]

# Floor A is a superload-width box travelling over-height at night; floor B is an
# oversize-width box travelling by day at ordinary height. Both move through KS,
# whose base requirement is two escorts, over three planned legs.
SUPERLOAD_SECTION_WIDTH_IN = 224
SUPERLOAD_SECTION_HEIGHT_IN = 168
OVERSIZE_SECTION_WIDTH_IN = 200
OVERSIZE_SECTION_HEIGHT_IN = 150
PLANNED_LEG_COUNT = 3

EXPECTED_CAPPED_ESCORT_COUNT = 4
EXPECTED_UNCAPPED_ESCORT_COUNT = 3
EXPECTED_SUPERLOAD_FEE_CENTS = 98125
EXPECTED_OVERSIZE_FEE_CENTS = 56000


def _build_released_kansas_floors():
    """A two-section KS order whose floors are both released to the permit desk.

    Floor one is declared and measured 224 inches wide by 168 inches tall; floor
    two is declared and measured 200 inches wide by 150 inches tall, mated to the
    first. Both are walked `AT_PLANT` -> `MEASURED` -> `PERMIT_PENDING`.
    """
    set_logical_clock()
    plant = register_plant(name="Champion Topeka", state_code="KS")
    order = open_order(
        plant["id"],
        dealer_name="Prairie Home Center",
        home_model="Titan 4076",
        section_count=2,
        destination_state="KS",
        wind_zone="III",
    )
    section_a = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=SUPERLOAD_SECTION_WIDTH_IN,
        declared_height_in=SUPERLOAD_SECTION_HEIGHT_IN,
        declared_length_in=900,
        declared_weight_lb=31000,
    )
    section_b = record_section(
        order["id"],
        plant["id"],
        section_index=2,
        declared_width_in=OVERSIZE_SECTION_WIDTH_IN,
        declared_height_in=OVERSIZE_SECTION_HEIGHT_IN,
        declared_length_in=900,
        declared_weight_lb=29000,
        mates_to_section_id=section_a["id"],
    )
    measure_section(
        section_a["id"],
        plant["id"],
        SUPERLOAD_SECTION_WIDTH_IN,
        SUPERLOAD_SECTION_HEIGHT_IN,
    )
    released_a = release_section(section_a["id"], plant["id"])
    measure_section(
        section_b["id"],
        plant["id"],
        OVERSIZE_SECTION_WIDTH_IN,
        OVERSIZE_SECTION_HEIGHT_IN,
    )
    released_b = release_section(section_b["id"], plant["id"])

    return {
        "plant": plant,
        "order": order,
        "section_a": released_a,
        "section_b": released_b,
    }


def _request_kansas_permit(section, night_move):
    payload = create_permit_payload(
        section["id"],
        section["version"],
        state_code="KS",
        planned_leg_count=PLANNED_LEG_COUNT,
        night_move=night_move,
    )
    return validate_success(api_client.create_permit(payload, PERMIT_DESK), 201)


def test_superload_night_move_over_three_legs_is_clamped_to_four_escorts():
    """PRD §3.4: "`escort_count_required` starts from the issuing state's base
    requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1, and
    `KS` and `CO` each contribute 2 — and then adds one escort for a width of at
    least 192 inches, one more for a width of at least 216 inches (so a
    superload-width box collects both increments), one for a travel height of at
    least thirteen and a half feet (162 inches, again inclusive), and one for a
    night move. The sum is finally capped at four escorts, which is the network's
    hard ceiling regardless of how the increments accumulate."
    PRD §3.4: "Finally, if the height in use is at least 162 inches, a flat
    over-height surcharge of ninety dollars (9,000 cents) is added; otherwise
    nothing is added on that account. The assembled subtotal is then multiplied by
    1.25 when the `permit_class` from the same evaluation is `SUPERLOAD`, and left
    unchanged otherwise."
    PRD §3.4: "A new permit opens at `status` `REQUESTED` with
    `paid_amount_cents` at 0, `final_fee_cents` null and `valid_until_date` null,
    raises the floor's `version`, and re-derives the order's posture."

    Design: Difficulty/combinatorial_formula/escort_matrix_min_cap_over_five_inputs
    """
    scenario = _build_released_kansas_floors()

    permit = _request_kansas_permit(scenario["section_a"], night_move=True)
    assert_transport_permit(permit)

    assert permit["permit_class"] == "SUPERLOAD", (
        "a 224-inch width is at least 216 inches, so the class is SUPERLOAD, got "
        f"{permit['permit_class']}"
    )
    assert permit["escort_count_required"] == EXPECTED_CAPPED_ESCORT_COUNT, (
        "the KS base of 2 plus the 192-inch, 216-inch, over-height and night-move "
        f"increments sums to 6 and must clamp to {EXPECTED_CAPPED_ESCORT_COUNT}, "
        f"got {permit['escort_count_required']}"
    )
    assert permit["pilot_car_required"] is True, (
        "a non-STANDARD class alone requires a pilot car, got "
        f"{permit['pilot_car_required']}"
    )
    assert permit["provisional_fee_cents"] == EXPECTED_SUPERLOAD_FEE_CENTS, (
        "the subtotal of 78500 cents priced on the clamped four escorts, "
        f"multiplied once by 1.25, is {EXPECTED_SUPERLOAD_FEE_CENTS} cents, got "
        f"{permit['provisional_fee_cents']}"
    )
    assert permit["status"] == "REQUESTED", (
        f"a new permit opens at REQUESTED, got {permit['status']}"
    )
    assert permit["paid_amount_cents"] == 0, (
        f"a new permit opens with paid_amount_cents at 0, got {permit['paid_amount_cents']}"
    )


def test_oversize_day_move_returns_the_uncapped_escort_sum():
    """PRD §3.4: "`permit_class` is `SUPERLOAD` when the width is at least
    eighteen feet (216 inches), otherwise `OVERSIZE` when the width is at least
    sixteen feet (192 inches), otherwise `STANDARD`; both comparisons are
    inclusive, so a box measuring exactly 192 inches is `OVERSIZE` and one
    measuring exactly 216 inches is `SUPERLOAD`."
    PRD §3.4: "`pilot_car_required` is true when any one of three conditions
    holds: the `permit_class` is anything other than `STANDARD`, or the leg count
    is at least 3, or the issuing `state_code` is `KS` and the travel height is at
    least 162 inches."
    PRD §3.4: "To it is added two dollars fifty (250 cents) for every inch by
    which the width in use exceeds the fourteen-foot free allowance of 168 inches,
    where the excess is zero if the width is at or under the allowance. Then
    forty-five dollars (4,500 cents) is added for each leg in the leg count in
    use, and seventy-five dollars (7,500 cents) for each escort the requirement
    matrix demanded in the same evaluation."

    Design: Difficulty/combinatorial_formula/escort_matrix_min_cap_over_five_inputs
    """
    scenario = _build_released_kansas_floors()

    superload_permit = _request_kansas_permit(scenario["section_a"], night_move=True)
    oversize_permit = _request_kansas_permit(scenario["section_b"], night_move=False)
    assert_transport_permit(oversize_permit)

    assert oversize_permit["permit_class"] == "OVERSIZE", (
        "a 200-inch width is at least 192 but under 216 inches, so the class is "
        f"OVERSIZE, got {oversize_permit['permit_class']}"
    )
    assert oversize_permit["escort_count_required"] == EXPECTED_UNCAPPED_ESCORT_COUNT, (
        "the KS base of 2 plus the single 192-inch increment sums to "
        f"{EXPECTED_UNCAPPED_ESCORT_COUNT} and is under the cap, got "
        f"{oversize_permit['escort_count_required']}"
    )
    assert oversize_permit["pilot_car_required"] is True, (
        "a leg count of at least 3 is on its own enough to require a pilot car, "
        f"got {oversize_permit['pilot_car_required']}"
    )
    assert oversize_permit["provisional_fee_cents"] == EXPECTED_OVERSIZE_FEE_CENTS, (
        "12000 base plus 8000 for 32 inches over the allowance plus 13500 for "
        "three legs plus 22500 for three escorts and no over-height surcharge is "
        f"{EXPECTED_OVERSIZE_FEE_CENTS} cents, got "
        f"{oversize_permit['provisional_fee_cents']}"
    )

    escort_gap = (
        superload_permit["escort_count_required"]
        - oversize_permit["escort_count_required"]
    )
    assert escort_gap == 1, (
        "the clamped superload permit exceeds the uncapped oversize permit by "
        f"exactly one escort, got a gap of {escort_gap}"
    )
