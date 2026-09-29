"""Permit pricing evaluated twice: once at request, once at issuance.

The same `TransportPermit` row carries two fee figures produced by the same
formula run at two different evaluation sites — `provisional_fee_cents` from the
floor's declared dimensions and the permit's `planned_leg_count`, and
`final_fee_cents` from the floor's measured dimensions and the permit's actual
leg count.
"""

from test_helpers import (
    TEST_USERS,
    add_route_leg,
    api_client,
    assert_home_section,
    assert_transport_permit,
    measure_section,
    open_order,
    pay_permit_fee,
    read_permit,
    read_section,
    record_section,
    register_escort_crew,
    register_hauler,
    register_plant,
    release_section,
    request_permit,
    reserve_escort,
    set_logical_clock,
    validate_success,
)

PERMIT_DESK = TEST_USERS["permit_desk_headers"]

# The floor is declared 200 inches wide but comes off the line at 206 inches,
# and the permit is requested for two planned legs while three corridor legs are
# actually filed under it — so the two evaluations of PRD §3.4 read different
# inputs from the same rows.
DECLARED_WIDTH_IN = 200
MEASURED_WIDTH_IN = 206
TRAVEL_HEIGHT_IN = 150
PLANNED_LEG_COUNT = 2
ACTUAL_LEG_COUNT = 3
REMITTANCE_CENTS = 50000

EXPECTED_PROVISIONAL_FEE_CENTS = 44000
EXPECTED_FINAL_FEE_CENTS = 50000
EXPECTED_DIVERGENCE_CENTS = 6000


def _build_permit_awaiting_issuance():
    """A TX permit in `FEE_PAID` whose final evaluation must diverge upward.

    One plant in TX, one active carrier and two escort crews endorsed for
    oversize loads; a single-section TX order whose floor is declared 200 inches
    wide, measured at 206 inches by plant QC and released to the permit desk; a
    TX permit requested over two planned legs but carrying three filed corridor
    legs, covered by two reserved escorts and one reserved pilot car, with
    50,000 cents remitted against it.
    """
    set_logical_clock()
    plant = register_plant(name="Champion Athens", state_code="TX")
    hauler = register_hauler(name="Lone Star Toters", endorsed_states=["TX"])
    escort_a = register_escort_crew(
        vendor_name="Big Load Escort A",
        endorsed_states=["TX"],
        certified_roles=["ESCORT", "PILOT_CAR"],
        endorsement_class="OVERSIZE",
        buffer_minutes=45,
        max_reserved_minutes=1200,
    )
    escort_b = register_escort_crew(
        vendor_name="Big Load Escort B",
        endorsed_states=["TX"],
        certified_roles=["ESCORT", "PILOT_CAR"],
        endorsement_class="OVERSIZE",
        buffer_minutes=45,
        max_reserved_minutes=1200,
    )
    order = open_order(
        plant["id"],
        dealer_name="Hill Country Homes",
        home_model="Titan 3266",
        section_count=1,
        destination_state="TX",
        wind_zone="II",
    )
    section = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=DECLARED_WIDTH_IN,
        declared_height_in=TRAVEL_HEIGHT_IN,
        declared_length_in=768,
        declared_weight_lb=26500,
    )
    measure_section(section["id"], plant["id"], MEASURED_WIDTH_IN, TRAVEL_HEIGHT_IN)
    released = release_section(section["id"], plant["id"])

    permit = request_permit(
        section["id"],
        state_code="TX",
        planned_leg_count=PLANNED_LEG_COUNT,
        expected_section_version=released["version"],
        night_move=False,
    )
    leg_one = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=1,
        corridor_id="TX-US79",
        state_code="TX",
        window_start="2026-08-05T06:00:00.000Z",
        window_end="2026-08-05T14:00:00.000Z",
    )
    leg_two = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=2,
        corridor_id="TX-US290",
        state_code="TX",
        window_start="2026-08-06T06:00:00.000Z",
        window_end="2026-08-06T14:00:00.000Z",
    )
    leg_three = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=3,
        corridor_id="TX-FM1431",
        state_code="TX",
        window_start="2026-08-06T15:00:00.000Z",
        window_end="2026-08-06T19:00:00.000Z",
    )
    # Two reserved ESCORT-role assignments and one reserved PILOT_CAR assignment
    # across the permit's legs, which is what the sufficiency gate of PRD §3.4
    # demands for an escort_count_required of 2 with a pilot car required.
    reserve_escort(
        leg_one["id"],
        escort_a["id"],
        hauler["id"],
        role="ESCORT",
        window_start="2026-08-05T06:00:00.000Z",
        window_end="2026-08-05T14:00:00.000Z",
    )
    reserve_escort(
        leg_two["id"],
        escort_b["id"],
        hauler["id"],
        role="ESCORT",
        window_start="2026-08-06T06:00:00.000Z",
        window_end="2026-08-06T14:00:00.000Z",
    )
    reserve_escort(
        leg_three["id"],
        escort_a["id"],
        hauler["id"],
        role="PILOT_CAR",
        window_start="2026-08-06T15:00:00.000Z",
        window_end="2026-08-06T19:00:00.000Z",
    )
    pay_permit_fee(permit["id"], hauler["id"], REMITTANCE_CENTS)

    return {
        "plant": plant,
        "hauler": hauler,
        "order": order,
        "section": section,
        "permit": read_permit(permit["id"]),
        "legs": [leg_one, leg_two, leg_three],
    }


def test_permit_fee_diverges_between_provisional_and_final_evaluation():
    """PRD §3.4: "The **provisional** variant runs when the permit is requested,
    before the plant has released measured dimensions and before any corridor leg
    exists; it uses the floor's `declared_width_in` and `declared_height_in` and
    the permit's `planned_leg_count`, and its result is stored as
    `provisional_fee_cents`."
    PRD §3.4: "The **final** variant runs at issuance; it uses the floor's
    `measured_width_in` and `measured_height_in`, falling back to the declared
    figures only where a measured figure is still null, and it uses the permit's
    *actual* leg count — the number of that permit's route legs whose `status` is
    `SCHEDULED`, `IN_TRANSIT` or `ARRIVED`."
    PRD §3.4: "Both variants take their escort count and permit class from their
    own matrix evaluation, never from the stored `escort_count_required` and
    `permit_class` fields, which the final evaluation overwrites in the very same
    request."

    Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final_divergence
    """
    scenario = _build_permit_awaiting_issuance()
    permit_id = scenario["permit"]["id"]

    provisional = scenario["permit"]["provisional_fee_cents"]
    assert provisional == EXPECTED_PROVISIONAL_FEE_CENTS, (
        "the provisional variant prices a 200-inch declared width over two "
        f"planned legs at {EXPECTED_PROVISIONAL_FEE_CENTS} cents, got {provisional}"
    )

    issued = validate_success(
        api_client.issue_permit(permit_id, {}, PERMIT_DESK), 200
    )
    assert_transport_permit(issued)

    assert issued["final_fee_cents"] == EXPECTED_FINAL_FEE_CENTS, (
        "the final variant prices the 206-inch measured width over three actual "
        f"legs at {EXPECTED_FINAL_FEE_CENTS} cents, got {issued['final_fee_cents']}"
    )
    assert issued["provisional_fee_cents"] == EXPECTED_PROVISIONAL_FEE_CENTS, (
        "issuance must not rewrite provisional_fee_cents, expected "
        f"{EXPECTED_PROVISIONAL_FEE_CENTS}, got {issued['provisional_fee_cents']}"
    )
    divergence = issued["final_fee_cents"] - issued["provisional_fee_cents"]
    assert divergence == EXPECTED_DIVERGENCE_CENTS, (
        f"expected a {EXPECTED_DIVERGENCE_CENTS}-cent divergence produced by the "
        f"evaluation site alone, got {divergence}"
    )

    assert issued["permit_class"] == "OVERSIZE", (
        "a 206-inch measured width is at least 192 but under 216 inches, so the "
        f"final class is OVERSIZE, got {issued['permit_class']}"
    )
    assert issued["escort_count_required"] == 2, (
        "the TX base of one plus one increment for a width of at least 192 "
        f"inches is 2 escorts, got {issued['escort_count_required']}"
    )
    assert issued["pilot_car_required"] is True, (
        "an OVERSIZE class over three legs requires a pilot car, got "
        f"{issued['pilot_car_required']}"
    )


def test_permit_issuance_stamps_validity_and_frees_the_floor():
    """PRD §3.4: "A `PermitDesk` operator issues a permit that is in `FEE_PAID`,
    moving it `FEE_PAID → ISSUED`."
    PRD §3.4: "On success the permit's `valid_until_date` is set to the logical
    clock's current UTC date plus five days, the permit's floor moves
    `PERMIT_PENDING → DISPATCH_READY` — or `PERMIT_REVOKED_HOLD →
    DISPATCH_READY` when a held floor is being re-permitted, which is how a
    revocation hold is cleared — both rows' `version` values rise, and the
    order's posture is re-derived."
    PRD §3.4: "Second, and only afterwards, fee coverage: `paid_amount_cents`
    must be at least the freshly computed `final_fee_cents`, failing which the
    request is refused with `ERR_PERMIT_FEE_UNPAID` and HTTP 402."

    Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final_divergence
    """
    scenario = _build_permit_awaiting_issuance()
    permit_id = scenario["permit"]["id"]
    section_id = scenario["section"]["id"]

    assert scenario["permit"]["status"] == "FEE_PAID", (
        "a remittance of 50000 cents covers the 44000-cent provisional fee, so "
        f"the permit must sit in FEE_PAID, got {scenario['permit']['status']}"
    )

    issued = validate_success(
        api_client.issue_permit(permit_id, {}, PERMIT_DESK), 200
    )

    assert issued["status"] == "ISSUED", (
        f"issuance moves FEE_PAID -> ISSUED, got {issued['status']}"
    )
    assert issued["paid_amount_cents"] >= issued["final_fee_cents"], (
        "the remitted total must cover the freshly computed final fee, got "
        f"{issued['paid_amount_cents']} against {issued['final_fee_cents']}"
    )
    assert issued["valid_until_date"] == "2026-08-06", (
        "the logical clock reads 2026-08-01, so validity runs to 2026-08-06, got "
        f"{issued['valid_until_date']}"
    )

    section = read_section(section_id)
    assert_home_section(section)
    assert section["transit_status"] == "DISPATCH_READY", (
        "issuing the floor's permit moves it PERMIT_PENDING -> DISPATCH_READY, "
        f"got {section['transit_status']}"
    )
