"""The inclusive 192-inch oversize width boundary (PRD §3.4).

A floor measuring exactly 192 inches is `OVERSIZE`, collects the width escort
increment, drags a pilot car along with it and prices 7,750 cents higher than
the one-inch-narrower floor that stays `STANDARD`.  Every permit here is
requested against a two-section Texas order, so the issuing state contributes
one base escort to both evaluations and the difference between the two permits
is attributable to the width comparison alone.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_transport_permit,
    create_permit_payload,
    current_section_version,
    measure_and_release_section,
    open_order,
    record_section,
    register_plant,
    set_logical_clock,
    validate_success,
)

PERMIT_DESK = TEST_USERS["permit_desk_headers"]


def _tx_order_with_boundary_floors():
    """A two-section TX order: one floor exactly 192 in wide, one 191 in wide.

    Both floors are 150 inches tall, are measured at exactly their declared
    width and are then released to the permit desk, so the provisional
    evaluation of each permit reads the declared width the dealer supplied.
    """
    set_logical_clock()
    plant = register_plant(state_code="TX")
    order = open_order(
        plant["id"],
        section_count=2,
        destination_state="TX",
        wind_zone="II",
        dealer_name="Hill Country Homes",
        home_model="Titan 3266",
    )
    section_192 = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=192,
        declared_height_in=150,
        declared_length_in=768,
        declared_weight_lb=25500,
    )
    section_191 = record_section(
        order["id"],
        plant["id"],
        section_index=2,
        declared_width_in=191,
        declared_height_in=150,
        declared_length_in=768,
        declared_weight_lb=25400,
        mates_to_section_id=section_192["id"],
    )
    measure_and_release_section(section_192["id"], plant["id"])
    measure_and_release_section(section_191["id"], plant["id"])
    return {
        "plant": plant,
        "order": order,
        "section_192": section_192,
        "section_191": section_191,
    }


def _request_tx_permit(section_id):
    """Request a two-leg daylight TX permit for one released floor."""
    response = api_client.create_permit(
        create_permit_payload(
            section_id,
            current_section_version(section_id),
            state_code="TX",
            planned_leg_count=2,
            night_move=False,
        ),
        PERMIT_DESK,
    )
    return response


def test_width_exactly_192_inches_is_oversize_with_two_escorts_and_a_pilot_car():
    """PRD §3.4: "`permit_class` is `SUPERLOAD` when the width is at least
    eighteen feet (216 inches), otherwise `OVERSIZE` when the width is at least
    sixteen feet (192 inches), otherwise `STANDARD`; both comparisons are
    inclusive, so a box measuring exactly 192 inches is `OVERSIZE` and one
    measuring exactly 216 inches is `SUPERLOAD`."
    PRD §3.4: "`escort_count_required` starts from the issuing state's base
    requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1, and
    `KS` and `CO` each contribute 2 — and then adds one escort for a width of at
    least 192 inches, one more for a width of at least 216 inches (so a
    superload-width box collects both increments), one for a travel height of at
    least thirteen and a half feet (162 inches, again inclusive), and one for a
    night move."
    PRD §3.4: "`pilot_car_required` is true when any one of three conditions
    holds: the `permit_class` is anything other than `STANDARD`, or the leg count
    is at least 3, or the issuing `state_code` is `KS` and the travel height is
    at least 162 inches."
    PRD §3.4: "The subtotal begins at a base of one hundred and twenty dollars
    (12,000 cents). To it is added two dollars fifty (250 cents) for every inch
    by which the width in use exceeds the fourteen-foot free allowance of 168
    inches, where the excess is zero if the width is at or under the allowance.
    Then forty-five dollars (4,500 cents) is added for each leg in the leg count
    in use, and seventy-five dollars (7,500 cents) for each escort the
    requirement matrix demanded in the same evaluation."

    Design: Difficulty/boundary_precision_check/permit_class_width_boundary_exactly_192
    """
    scenario = _tx_order_with_boundary_floors()

    permit = validate_success(_request_tx_permit(scenario["section_192"]["id"]), 201)

    assert_transport_permit(permit)
    assert permit["permit_class"] == "OVERSIZE", (
        "a floor measuring exactly 192 inches is OVERSIZE, got "
        f"{permit['permit_class']}"
    )
    assert permit["escort_count_required"] == 2, (
        "the TX base of 1 plus the at-least-192-inch increment is 2 escorts, got "
        f"{permit['escort_count_required']}"
    )
    assert permit["pilot_car_required"] is True, (
        "a permit class other than STANDARD requires a pilot car, got "
        f"{permit['pilot_car_required']}"
    )
    assert permit["provisional_fee_cents"] == 42000, (
        "12000 base + 24 inches over the allowance at 250 + two legs at 4500 + "
        f"two escorts at 7500 is 42000 cents, got {permit['provisional_fee_cents']}"
    )


def test_width_one_inch_below_192_is_standard_with_one_escort_and_no_pilot_car():
    """PRD §3.4: "`permit_class` is `SUPERLOAD` when the width is at least
    eighteen feet (216 inches), otherwise `OVERSIZE` when the width is at least
    sixteen feet (192 inches), otherwise `STANDARD`; both comparisons are
    inclusive, so a box measuring exactly 192 inches is `OVERSIZE` and one
    measuring exactly 216 inches is `SUPERLOAD`."
    PRD §3.4: "`escort_count_required` starts from the issuing state's base
    requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1, and
    `KS` and `CO` each contribute 2 — and then adds one escort for a width of at
    least 192 inches, one more for a width of at least 216 inches (so a
    superload-width box collects both increments), one for a travel height of at
    least thirteen and a half feet (162 inches, again inclusive), and one for a
    night move."
    PRD §3.4: "`pilot_car_required` is true when any one of three conditions
    holds: the `permit_class` is anything other than `STANDARD`, or the leg count
    is at least 3, or the issuing `state_code` is `KS` and the travel height is
    at least 162 inches."
    PRD §3.4: "The subtotal begins at a base of one hundred and twenty dollars
    (12,000 cents). To it is added two dollars fifty (250 cents) for every inch
    by which the width in use exceeds the fourteen-foot free allowance of 168
    inches, where the excess is zero if the width is at or under the allowance.
    Then forty-five dollars (4,500 cents) is added for each leg in the leg count
    in use, and seventy-five dollars (7,500 cents) for each escort the
    requirement matrix demanded in the same evaluation."

    Design: Difficulty/boundary_precision_check/permit_class_width_boundary_exactly_192
    """
    scenario = _tx_order_with_boundary_floors()

    permit = validate_success(_request_tx_permit(scenario["section_191"]["id"]), 201)

    assert_transport_permit(permit)
    assert permit["permit_class"] == "STANDARD", (
        "a floor measuring 191 inches is below the 192-inch line and stays "
        f"STANDARD, got {permit['permit_class']}"
    )
    assert permit["escort_count_required"] == 1, (
        "only the TX base escort applies below 192 inches, got "
        f"{permit['escort_count_required']}"
    )
    assert permit["pilot_car_required"] is False, (
        "a STANDARD class on two legs out of TX needs no pilot car, got "
        f"{permit['pilot_car_required']}"
    )
    assert permit["provisional_fee_cents"] == 34250, (
        "12000 base + 23 inches over the allowance at 250 + two legs at 4500 + "
        f"one escort at 7500 is 34250 cents, got {permit['provisional_fee_cents']}"
    )


def test_one_inch_across_the_192_boundary_moves_the_provisional_fee_by_7750():
    """PRD §3.4: "`permit_class` is `SUPERLOAD` when the width is at least
    eighteen feet (216 inches), otherwise `OVERSIZE` when the width is at least
    sixteen feet (192 inches), otherwise `STANDARD`; both comparisons are
    inclusive, so a box measuring exactly 192 inches is `OVERSIZE` and one
    measuring exactly 216 inches is `SUPERLOAD`."
    PRD §3.4: "The subtotal begins at a base of one hundred and twenty dollars
    (12,000 cents). To it is added two dollars fifty (250 cents) for every inch
    by which the width in use exceeds the fourteen-foot free allowance of 168
    inches, where the excess is zero if the width is at or under the allowance.
    Then forty-five dollars (4,500 cents) is added for each leg in the leg count
    in use, and seventy-five dollars (7,500 cents) for each escort the
    requirement matrix demanded in the same evaluation."
    PRD §3.4: "The **provisional** variant runs when the permit is requested,
    before the plant has released measured dimensions and before any corridor leg
    exists; it uses the floor's `declared_width_in` and `declared_height_in` and
    the permit's `planned_leg_count`, and its result is stored as
    `provisional_fee_cents`."

    Design: Difficulty/boundary_precision_check/permit_class_width_boundary_exactly_192
    """
    scenario = _tx_order_with_boundary_floors()

    oversize = validate_success(_request_tx_permit(scenario["section_192"]["id"]), 201)
    standard = validate_success(_request_tx_permit(scenario["section_191"]["id"]), 201)

    assert oversize["provisional_fee_cents"] == 42000, (
        "the 192-inch floor prices at 42000 cents, got "
        f"{oversize['provisional_fee_cents']}"
    )
    assert standard["provisional_fee_cents"] == 34250, (
        "the 191-inch floor prices at 34250 cents, got "
        f"{standard['provisional_fee_cents']}"
    )
    difference = oversize["provisional_fee_cents"] - standard["provisional_fee_cents"]
    assert difference == 7750, (
        "one inch across the 192-inch line adds 250 cents of width charge and a "
        f"whole 7500-cent escort, i.e. 7750 cents, got {difference}"
    )
