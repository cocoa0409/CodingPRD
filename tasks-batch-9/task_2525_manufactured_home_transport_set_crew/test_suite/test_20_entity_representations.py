"""What a written or retrieved row actually contains.

These tests read the representation the API hands back: the fields an order
echoes on creation and the posture a descendant-free order lands on, the row a
hauler read returns, the scheduling defaults an escort crew and an installer
crew fall back to, the system fields the server mints and bumps, the fee figures
a permit request derives without any client help, and the deliberately
append-only shape of a marriage joint.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_append_only_row,
    assert_escort_crew,
    assert_hauler,
    assert_installation_order,
    assert_marriage_joint,
    assert_set_crew,
    assert_three_fractional_digits,
    assert_transport_permit,
    create_escort_crew_payload,
    create_hauler_payload,
    create_marriage_joint_payload,
    create_order_payload,
    create_permit_payload,
    create_set_crew_payload,
    current_section_version,
    is_valid_uuid,
    make_set_crew_lead_headers,
    measure_and_release_section,
    open_order,
    read_order,
    record_section,
    register_plant,
    set_logical_clock,
    setup_dispatched_set_job,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]
PERMIT_DESK = TEST_USERS["permit_desk_headers"]
INSPECTOR = TEST_USERS["installation_inspector_headers"]


# ---------------------------------------------------------------------------
# Opening an order: the six declared inputs and the derived opening posture
# ---------------------------------------------------------------------------


def test_order_creation_echoes_every_declared_field(api):
    """PRD §3.2: "Opening one takes the building plant's identifier as
    `plant_id`, the retail `dealer_name` that sold the home, the Champion
    `home_model` designation, the dealer-declared `section_count` (between 1 and
    4 inclusive), the two-uppercase-letter `destination_state` of the delivery
    site, and the HUD `wind_zone` of that destination, which is one of `I`, `II`
    or `III`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/order_creation_returns_declared_fields_and_open_posture
    """
    set_logical_clock()
    plant = register_plant()

    resp = api.create_order(
        create_order_payload(
            plant["id"],
            dealer_name="Valley Homes",
            home_model="Titan 2860",
            section_count=2,
            destination_state="AZ",
            wind_zone="I",
        ),
        ADMIN,
    )
    order = validate_success(resp, 201)
    assert_installation_order(order)

    assert order["plant_id"] == plant["id"], (
        f"plant_id must echo the building plant, expected {plant['id']}, "
        f"got {order['plant_id']}"
    )
    assert order["dealer_name"] == "Valley Homes", (
        f"expected dealer_name Valley Homes, got {order['dealer_name']}"
    )
    assert order["home_model"] == "Titan 2860", (
        f"expected home_model Titan 2860, got {order['home_model']}"
    )
    assert order["section_count"] == 2, (
        f"expected section_count 2, got {order['section_count']}"
    )
    assert order["destination_state"] == "AZ", (
        f"expected destination_state AZ, got {order['destination_state']}"
    )
    assert order["wind_zone"] == "I", (
        f"expected wind_zone I, got {order['wind_zone']}"
    )
    assert order["version"] == 1, (
        f"a freshly created order carries version 1, got {order['version']}"
    )


def test_descendant_free_order_opens_at_posture_open_with_null_invoice(api):
    """PRD §3.2: "A fresh order carries `posture` `OPEN`, a
    `warranty_start_date` of null and an `invoice_total_cents` of null; both of
    those latter fields stay null until a final inspection passes cleanly."
    PRD §2.8: "Otherwise the posture is `OPEN`. A freshly created order with no
    descendants at all therefore reads `OPEN`."

    Design: Corner/entities/order_creation_returns_declared_fields_and_open_posture
    """
    set_logical_clock()
    plant = register_plant()

    resp = api.create_order(
        create_order_payload(plant["id"], section_count=2, home_model="Titan 2860"),
        ADMIN,
    )
    order = validate_success(resp, 201)

    assert order["posture"] == "OPEN", (
        f"a descendant-free order reads posture OPEN, got {order['posture']}"
    )
    assert order["warranty_start_date"] is None, (
        f"warranty_start_date stays null until a final inspection passes, "
        f"got {order['warranty_start_date']}"
    )
    assert order["invoice_total_cents"] is None, (
        f"invoice_total_cents stays null until a final inspection passes, "
        f"got {order['invoice_total_cents']}"
    )

    # The stored row reads back with the same opening posture.
    stored = read_order(order["id"])
    assert stored["posture"] == "OPEN", (
        f"the stored order still reads posture OPEN, got {stored['posture']}"
    )


# ---------------------------------------------------------------------------
# Reading a carrier back: the declared fields plus the two computed ones
# ---------------------------------------------------------------------------


def test_hauler_read_returns_declared_and_computed_fields(api):
    """PRD §3.1: "A motor carrier is registered with its trade `name`, its USDOT
    `dot_number` (unique across all haulers), its cargo-insurance expiry as
    `insurance_expiry_date` in `YYYY-MM-DD` form, and `endorsed_states`, a
    non-empty array of two-letter state codes in which the carrier is permitted
    to haul oversize loads."
    PRD §3.1: "A hauler likewise begins with `chargeback_balance_cents` at 0 and
    `status` `ACTIVE`, but for carriers the threshold bites: once the carrier's
    chargeback balance reaches five thousand dollars — at or above 500,000 cents
    — the carrier's `status` becomes `SUSPENDED`, and a suspended carrier can
    neither be booked onto a new corridor leg nor put an existing one on the
    road, both refusals carrying `ERR_HAULER_SUSPENDED`."

    Design: Corner/entities/hauler_retrieval_returns_stored_row
    """
    set_logical_clock()
    created = validate_success(
        api.create_hauler(
            create_hauler_payload(
                name="Desert Toter",
                dot_number="DOT-771004",
                insurance_expiry_date="2027-01-31",
                endorsed_states=["AZ", "NM"],
            ),
            ADMIN,
        ),
        201,
    )

    fetched = validate_success(api.get_hauler(created["id"], PERMIT_DESK), 200)
    assert_hauler(fetched)

    assert fetched["id"] == created["id"], (
        f"the read must address the same row, expected {created['id']}, "
        f"got {fetched['id']}"
    )
    assert fetched["name"] == "Desert Toter", (
        f"expected name Desert Toter, got {fetched['name']}"
    )
    assert fetched["dot_number"] == "DOT-771004", (
        f"expected dot_number DOT-771004, got {fetched['dot_number']}"
    )
    assert fetched["insurance_expiry_date"] == "2027-01-31", (
        f"expected insurance_expiry_date 2027-01-31, "
        f"got {fetched['insurance_expiry_date']}"
    )
    assert fetched["endorsed_states"] == ["AZ", "NM"], (
        f"expected endorsed_states ['AZ', 'NM'], got {fetched['endorsed_states']}"
    )
    assert fetched["chargeback_balance_cents"] == 0, (
        "a hauler begins with chargeback_balance_cents at 0, got "
        f"{fetched['chargeback_balance_cents']}"
    )
    assert fetched["status"] == "ACTIVE", (
        f"a hauler begins with status ACTIVE, got {fetched['status']}"
    )
    assert fetched["version"] == 1, (
        f"an unmutated hauler carries version 1, got {fetched['version']}"
    )


# ---------------------------------------------------------------------------
# Scheduling defaults on the two crew flavours
# ---------------------------------------------------------------------------


def test_escort_crew_scheduling_defaults_and_explicit_zero_buffer(api):
    """PRD §3.1: "`buffer_minutes` is the turnaround buffer that inflates both
    ends of every reserved window when overlaps are tested; it defaults to three
    quarters of an hour — 45 minutes — and must lie between 0 and 240
    inclusive."
    PRD §3.1: "`max_reserved_minutes` is the reserved-minute ceiling above which
    the crew counts as overbooked; it defaults to ten hours, i.e. 600 minutes,
    and must be at least 1."
    PRD §3.1: "A new crew starts with `reserved_minutes` at 0 and `status`
    `AVAILABLE`, and its `status` becomes `OVERBOOKED` the moment its booked
    `reserved_minutes` exceeds `max_reserved_minutes` — a crew sitting exactly at
    the ceiling is still `AVAILABLE`."

    Design: Corner/entities/escort_crew_and_set_crew_defaults_applied
    """
    set_logical_clock()

    defaulted = validate_success(
        api.create_escort_crew(
            create_escort_crew_payload(
                vendor_name="Default Escort", endorsement_class="STANDARD"
            ),
            ADMIN,
        ),
        201,
    )
    assert_escort_crew(defaulted)
    assert defaulted["buffer_minutes"] == 45, (
        f"an omitted buffer_minutes defaults to 45, got {defaulted['buffer_minutes']}"
    )
    assert defaulted["max_reserved_minutes"] == 600, (
        "an omitted max_reserved_minutes defaults to 600, got "
        f"{defaulted['max_reserved_minutes']}"
    )
    assert defaulted["reserved_minutes"] == 0, (
        f"a new crew starts with reserved_minutes 0, got {defaulted['reserved_minutes']}"
    )
    assert defaulted["status"] == "AVAILABLE", (
        f"a new crew starts with status AVAILABLE, got {defaulted['status']}"
    )

    # 0 lies inside the declared 0-to-240 range, so an explicit zero is a value
    # the client chose and not an absent field to be defaulted away.
    explicit_zero = validate_success(
        api.create_escort_crew(
            create_escort_crew_payload(
                vendor_name="Explicit Zero Escort",
                endorsement_class="STANDARD",
                buffer_minutes=0,
                max_reserved_minutes=600,
            ),
            ADMIN,
        ),
        201,
    )
    assert explicit_zero["buffer_minutes"] == 0, (
        "an explicitly supplied buffer_minutes of 0 must be preserved, got "
        f"{explicit_zero['buffer_minutes']}"
    )
    assert explicit_zero["max_reserved_minutes"] == 600, (
        "an explicitly supplied max_reserved_minutes of 600 must be preserved, got "
        f"{explicit_zero['max_reserved_minutes']}"
    )


def test_set_crew_defaults_daily_capacity_and_opens_active_with_zero_balance(api):
    """PRD §3.1: "`daily_capacity` is optional, defaults to 1, and must lie
    between 1 and 4 inclusive; it caps how many set jobs the crew may hold on any
    single calendar day."
    PRD §3.1: "A set crew also carries a computed `chargeback_balance_cents`
    starting at 0 — its share of settled claims — and a computed `status` that
    reads `ACTIVE` while `license_expiry_date` falls on or after the logical
    clock's current UTC date and `LICENSE_EXPIRED` once that date has passed."

    Design: Corner/entities/escort_crew_and_set_crew_defaults_applied
    """
    set_logical_clock()

    crew = validate_success(
        api.create_set_crew(
            create_set_crew_payload(
                company_name="Sonoran Set",
                license_state="AZ",
                license_expiry_date="2027-06-30",
            ),
            ADMIN,
        ),
        201,
    )
    assert_set_crew(crew)

    assert crew["daily_capacity"] == 1, (
        f"an omitted daily_capacity defaults to 1, got {crew['daily_capacity']}"
    )
    assert crew["chargeback_balance_cents"] == 0, (
        "a set crew's chargeback_balance_cents starts at 0, got "
        f"{crew['chargeback_balance_cents']}"
    )
    assert crew["status"] == "ACTIVE", (
        "a licence expiring after the logical current date reads ACTIVE, got "
        f"{crew['status']}"
    )


# ---------------------------------------------------------------------------
# System fields: minted by the server, bumped by cascades
# ---------------------------------------------------------------------------


def test_order_system_fields_are_server_minted(api):
    """PRD §2.4: "Every persisted row carries a server-minted `id` formatted as
    a UUID with no type prefix; clients never supply it. Every row also carries
    `created_at`, an ISO 8601 UTC timestamp with exactly three fractional digits,
    fixed at insertion."
    PRD §2.4: "and `version`, an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row — including mutations
    that the row's owner never asked for, such as a recomputed balance or a
    cascaded status change."

    Design: Corner/entities/order_system_fields_minted_by_server
    """
    set_logical_clock()
    plant = register_plant()

    order = validate_success(
        api.create_order(create_order_payload(plant["id"], section_count=1), ADMIN),
        201,
    )

    assert is_valid_uuid(order["id"]), (
        f"the minted id must be a UUID, got {order['id']!r}"
    )
    assert "_" not in order["id"] and ":" not in order["id"], (
        f"the minted id is a bare UUID with no type prefix, got {order['id']!r}"
    )
    assert_three_fractional_digits(order["created_at"])
    assert order["version"] == 1, (
        f"version starts at 1 on creation, got {order['version']}"
    )


def test_recording_a_section_bumps_the_order_version_without_touching_created_at(api):
    """PRD §2.9: "Creating a child that changes a parent's derived state bumps
    the parent too: recording a home section or a site raises the order's
    `version`, requesting a permit raises the section's `version`, adding a route
    leg raises the permit's `version`, reserving an escort raises the escort
    crew's `version`, and booking a set job raises the order's `version`."
    PRD §2.4: "Every row also carries `created_at`, an ISO 8601 UTC timestamp
    with exactly three fractional digits, fixed at insertion."

    Design: Corner/entities/order_system_fields_minted_by_server
    """
    set_logical_clock()
    plant = register_plant()
    order = open_order(plant["id"], section_count=1)
    assert order["version"] == 1, (
        f"the order starts at version 1, got {order['version']}"
    )
    created_at_before = order["created_at"]

    record_section(order["id"], plant["id"], section_index=1)

    reread = read_order(order["id"])
    assert reread["version"] == 2, (
        "recording a home section raises the order's version to 2, got "
        f"{reread['version']}"
    )
    assert reread["created_at"] == created_at_before, (
        "created_at is fixed at insertion and must survive the child write, "
        f"expected {created_at_before}, got {reread['created_at']}"
    )


# ---------------------------------------------------------------------------
# A permit's fee figures are derived, never client-supplied
# ---------------------------------------------------------------------------


def _request_permit_for_a_released_az_floor(api, declared_width_in=168,
                                            declared_height_in=150):
    """Open an AZ order, record one floor, measure and release it, then request
    a single-leg AZ permit and return the created permit row."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1, destination_state="AZ")
    section = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=declared_width_in,
        declared_height_in=declared_height_in,
    )
    measure_and_release_section(section["id"], plant["id"])
    resp = api.create_permit(
        create_permit_payload(
            section["id"],
            current_section_version(section["id"]),
            state_code="AZ",
            planned_leg_count=1,
            night_move=False,
        ),
        PERMIT_DESK,
    )
    return validate_success(resp, 201)


def test_permit_request_derives_class_escort_count_and_pilot_car_flag(api):
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
    is at least 3, or the issuing `state_code` is `KS` and the travel height is at
    least 162 inches."

    Design: Corner/entities/permit_computed_fee_fields_ignore_client_supplied_values
    """
    permit = _request_permit_for_a_released_az_floor(api)
    assert_transport_permit(permit)

    assert permit["permit_class"] == "STANDARD", (
        "a 168-inch-wide floor is under the 192-inch oversize threshold, so the "
        f"class is STANDARD, got {permit['permit_class']}"
    )
    assert permit["escort_count_required"] == 0, (
        "AZ contributes 0 and neither the width nor the height nor a night move "
        f"adds an escort, so the requirement is 0, got {permit['escort_count_required']}"
    )
    assert permit["pilot_car_required"] is False, (
        "a STANDARD class on one leg out of AZ triggers none of the three pilot-car "
        f"conditions, got {permit['pilot_car_required']}"
    )


def test_permit_request_derives_provisional_fee_and_opens_unpaid(api):
    """PRD §3.4: "The subtotal begins at a base of one hundred and twenty dollars
    (12,000 cents). To it is added two dollars fifty (250 cents) for every inch by
    which the width in use exceeds the fourteen-foot free allowance of 168 inches,
    where the excess is zero if the width is at or under the allowance. Then
    forty-five dollars (4,500 cents) is added for each leg in the leg count in
    use, and seventy-five dollars (7,500 cents) for each escort the requirement
    matrix demanded in the same evaluation."
    PRD §3.4: "it uses the floor's `declared_width_in` and `declared_height_in`
    and the permit's `planned_leg_count`, and its result is stored as
    `provisional_fee_cents`"
    PRD §3.4: "A new permit opens at `status` `REQUESTED` with `paid_amount_cents`
    at 0, `final_fee_cents` null and `valid_until_date` null, raises the floor's
    `version`, and re-derives the order's posture."

    Design: Corner/entities/permit_computed_fee_fields_ignore_client_supplied_values
    """
    permit = _request_permit_for_a_released_az_floor(api)

    assert permit["provisional_fee_cents"] == 16500, (
        "12,000 base + 0 width excess + 4,500 for one leg + 0 escort surcharge + 0 "
        f"over-height surcharge is 16,500 cents, got {permit['provisional_fee_cents']}"
    )
    assert permit["status"] == "REQUESTED", (
        f"a new permit opens at status REQUESTED, got {permit['status']}"
    )
    assert permit["paid_amount_cents"] == 0, (
        f"a new permit opens with paid_amount_cents 0, got {permit['paid_amount_cents']}"
    )
    assert permit["final_fee_cents"] is None, (
        "final_fee_cents is null until issuance re-runs the calculation, got "
        f"{permit['final_fee_cents']}"
    )
    assert permit["valid_until_date"] is None, (
        f"valid_until_date is null until issuance, got {permit['valid_until_date']}"
    )


# ---------------------------------------------------------------------------
# The marriage joint: an append-only measurement event
# ---------------------------------------------------------------------------


def test_marriage_joint_row_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "One entity is deliberately different. A marriage joint is an
    append-only measurement event: it carries `id` and `created_at` only. It has
    no `updated_at` and no `version` field at all, because a recorded measurement
    is never edited and never revised — a corrected reading is a new joint row,
    and the pairing of set job and joint index is what prevents duplicates."

    Design: Corner/entities/marriage_joint_immutable_row_has_no_version_and_no_update
    """
    scenario = setup_dispatched_set_job(section_count=2)
    job = scenario["set_job"]
    crew = scenario["set_crew"]

    created = validate_success(
        api.create_marriage_joint(
            create_marriage_joint_payload(
                job["id"],
                joint_index=1,
                gap_in=0.5,
                vertical_offset_in=1.0,
                ridge_beam_shim_in=0.25,
            ),
            make_set_crew_lead_headers(crew["id"]),
        ),
        201,
    )
    assert_append_only_row(created)

    fetched = validate_success(api.get_marriage_joint(created["id"], INSPECTOR), 200)
    assert_marriage_joint(fetched)
    assert fetched["id"] == created["id"], (
        f"the read must address the same joint, expected {created['id']}, "
        f"got {fetched['id']}"
    )
    assert "version" not in fetched, (
        f"a marriage joint has no version field at all, got {fetched.get('version')}"
    )
    assert "updated_at" not in fetched, (
        f"a marriage joint has no updated_at field at all, "
        f"got {fetched.get('updated_at')}"
    )
    assert fetched["set_job_id"] == job["id"], (
        f"the joint names its set job, expected {job['id']}, got {fetched['set_job_id']}"
    )
    assert fetched["joint_index"] == 1, (
        f"expected joint_index 1, got {fetched['joint_index']}"
    )


def test_marriage_joint_deviation_score_frozen_at_insert(api):
    """PRD §3.7: "the gap contributes, at weight 1.0, however much the gap exceeds
    a quarter of an inch (0.25 inches), and nothing at all if the gap is 0.25
    inches or less; the vertical offset contributes, at weight 0.6, however much
    the *absolute value* of the offset exceeds half an inch (0.5 inches), and
    nothing at all if that absolute value is 0.5 inches or less; and the shim
    contributes its full thickness at weight 0.4, with no tolerance allowance."
    PRD §3.7: "Those three contributions are added and the sum is rounded half up
    to two decimal places, and that rounded figure is stored as the joint's
    `deviation_score`."

    Design: Corner/entities/marriage_joint_immutable_row_has_no_version_and_no_update
    """
    scenario = setup_dispatched_set_job(section_count=2)
    job = scenario["set_job"]
    crew = scenario["set_crew"]

    created = validate_success(
        api.create_marriage_joint(
            create_marriage_joint_payload(
                job["id"],
                joint_index=1,
                gap_in=0.5,
                vertical_offset_in=1.0,
                ridge_beam_shim_in=0.25,
            ),
            make_set_crew_lead_headers(crew["id"]),
        ),
        201,
    )

    # 1.0 * (0.5 - 0.25) + 0.6 * (|1.0| - 0.5) + 0.4 * 0.25 = 0.25 + 0.30 + 0.10.
    assert created["deviation_score"] == pytest.approx(0.65, abs=0.01), (
        f"expected a deviation_score of 0.65, got {created['deviation_score']}"
    )

    # The reading is frozen at insert, so the stored row reports the same figure.
    fetched = validate_success(api.get_marriage_joint(created["id"], INSPECTOR), 200)
    assert fetched["deviation_score"] == pytest.approx(0.65, abs=0.01), (
        "the stored deviation_score must still read 0.65, got "
        f"{fetched['deviation_score']}"
    )
