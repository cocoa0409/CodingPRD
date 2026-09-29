"""Breadth over the guard rails: every refusal the food-safety ladder can produce.

The qualification gates fire in their declared order, the booking ladder walks from
recipe validity through basket capacity to the contract window, and the receiving
dock refuses on temperature, on segregation, on paperwork and on posture.  Each
test also checks that the refused request left the ledgers exactly where it found
them.
"""

from test_helpers import (
    ApiErrorId,
    add_stored_pallet,
    api_client,
    append_acceptable_runs,
    append_validation_run,
    book_load,
    commission_vessel,
    create_cycle_load_payload,
    create_lot_payload,
    create_vessel_cycle_payload,
    cycle_version,
    decide_qualification,
    define_cold_room,
    define_family,
    list_chargeback_lines,
    list_cycles,
    list_loads,
    list_lots,
    load_inspection_payload,
    make_customer_headers,
    open_active_contract,
    open_qualification,
    qualify_recipe,
    read_cold_room,
    read_contract,
    read_customer,
    read_cycle,
    read_load,
    read_lot,
    read_qualification,
    read_vessel,
    receive_pallet,
    record_release_decision,
    register_customer,
    schedule_cycle,
    setup_dispositioned_clean_cycle,
    setup_loaded_cycle,
    setup_qualified_facility,
    setup_scheduled_cycle,
    setup_stored_pallet,
    set_clock,
    ship_payload,
    store_pallet,
    submit_qualification,
    supersede_qualification,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CLOCK_AUG03, OPERATOR, QUALITY, SCHEDULER


# --------------------------------------------------------------------------- #
# the four qualification gates, in their declared order
# --------------------------------------------------------------------------- #
def _submitted_under_validation(package: dict, sku_code: str) -> dict:
    """A qualification with the given package, submitted and twice validated."""
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    qualification = open_qualification(
        customer["id"],
        family["id"],
        sku_code=sku_code,
        max_water_temp_c=8.0,
        target_log_reduction=5.0,
        **package,
    )
    submit_qualification(qualification["id"], customer["id"])
    append_acceptable_runs(qualification["id"], how_many=2)
    return {"customer": customer, "family": family, "qualification": qualification}


def test_a_glass_package_is_banned_outright_even_scoring_above_the_line():
    """Glass loses only the format term, so it still scores 80.00 — well over the
    70.00 line — and only the categorical ban can refuse it.

    PRD 3.2: "Second, the `package_format` must not be `GLASS`; glass is never
    HPP-suitable, and the refusal is `ERR_PACKAGE_FORMAT_NOT_PERMITTED`."
    PRD 3.2: "The *format factor* is read from a fixed table: `POUCH` scores 1.0,
    `TRAY_SEALED` scores 0.85, `RIGID_BOTTLE` scores 0.60, and `GLASS` scores 0.0."

    Design: Corner/validations/corner_glass_package_blocks_qualification_even_above_the_score_line
    """
    world = _submitted_under_validation(
        {
            "package_format": "GLASS",
            "package_burst_pressure_mpa": 660.0,
            "film_thickness_micron": 90,
        },
        sku_code="JUICE-1L",
    )

    response = api_client.decide_qualification(
        world["qualification"]["id"], {"outcome": "QUALIFY"}, QUALITY
    )

    validate_error(
        response, ApiErrorId.ERR_PACKAGE_FORMAT_NOT_PERMITTED.value, 422
    )
    after = read_qualification(world["qualification"]["id"])
    assert after["package_suitability_score"] == 80.00
    assert after["validation_run_acceptable_count"] == 2
    assert after["status"] == "UNDER_VALIDATION"
    assert after["qualified_at"] is None


def test_a_zero_burst_margin_reports_the_burst_rule_and_not_the_score_rule():
    """A package bursting exactly at process pressure breaks two gates at once, and
    the more specific burst gate is the one the client is told about.

    PRD 3.2: "Third, `package_burst_pressure_mpa` must be strictly greater than
    `pressure_mpa` — a package that bursts exactly at process pressure is not
    acceptable — and the refusal is `ERR_BURST_PRESSURE_INSUFFICIENT`."
    PRD 3.2: "The score check is deliberately last: a glass package or a zero burst
    margin necessarily drags the composite score below 70, so reporting the composite
    first would hide the actual defect."

    Design: Corner/validations/corner_zero_burst_margin_reports_the_burst_rule_not_the_score_rule
    """
    world = _submitted_under_validation(
        {
            "package_format": "POUCH",
            "package_burst_pressure_mpa": 600.0,
            "film_thickness_micron": 90,
        },
        sku_code="DIP-250",
    )

    response = api_client.decide_qualification(
        world["qualification"]["id"], {"outcome": "QUALIFY"}, QUALITY
    )

    validate_error(
        response, ApiErrorId.ERR_BURST_PRESSURE_INSUFFICIENT.value, 422
    )
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_PACKAGE_NOT_SUITABLE.value
    )
    after = read_qualification(world["qualification"]["id"])
    assert after["package_suitability_score"] == 50.00
    assert after["status"] == "UNDER_VALIDATION"


def test_a_composite_score_below_seventy_is_the_last_gate_to_fire():
    """The tray has a legal burst margin and a permitted format, so 44.25 against the
    70.00 line is the only thing left to refuse it.

    PRD 3.2: "Fourth and last, `package_suitability_score` must be at least 70.00,
    refused otherwise with `ERR_PACKAGE_NOT_SUITABLE`."
    PRD 3.2: "The components are held at full precision throughout; there is exactly
    one rounding step, applied half up to two decimal places on the summed total, and
    that total is stored as `package_suitability_score`."

    Design: Corner/validations/corner_score_below_seventy_blocks_qualification
    """
    world = _submitted_under_validation(
        {
            "package_format": "TRAY_SEALED",
            "package_burst_pressure_mpa": 611.125,
            "film_thickness_micron": 43,
        },
        sku_code="SOUP-200",
    )

    response = api_client.decide_qualification(
        world["qualification"]["id"], {"outcome": "QUALIFY"}, QUALITY
    )

    validate_error(response, ApiErrorId.ERR_PACKAGE_NOT_SUITABLE.value, 422)
    after = read_qualification(world["qualification"]["id"])
    assert after["package_suitability_score"] == 44.25
    assert after["status"] == "UNDER_VALIDATION"


def test_a_single_acceptable_run_outranks_a_flawless_package():
    """The run-count gate is first, so a package scoring a perfect 100.00 is still
    refused for having only one acceptable run behind it.

    PRD 3.2: "First, `validation_run_acceptable_count` must be at least two — the
    facility will not qualify a recipe on a single acceptable run — and a shortfall is
    refused with `ERR_INSUFFICIENT_VALIDATION_RUNS`."
    PRD 3.2: "A `QUALIFY` outcome passes four food-safety gates, evaluated in exactly
    this order so that the most specific defect is the one reported."

    Design: Corner/validations/corner_one_acceptable_run_is_not_enough_to_qualify
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    qualification = open_qualification(customer["id"], family["id"])
    submit_qualification(qualification["id"], customer["id"])
    append_validation_run(qualification["id"])

    response = api_client.decide_qualification(
        qualification["id"], {"outcome": "QUALIFY"}, QUALITY
    )

    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_VALIDATION_RUNS.value, 422
    )
    after = read_qualification(qualification["id"])
    assert after["validation_run_acceptable_count"] == 1
    assert after["package_suitability_score"] == 100.00
    assert after["status"] == "UNDER_VALIDATION"


def test_the_fourth_resubmission_after_four_change_requests_is_refused():
    """Three completed rounds may still be resubmitted, which is what makes the
    fourth attempt — at `revision_round` 4 — the first one refused.

    PRD 3.2: "The same operation also closes the revision loop: a qualification
    sitting at `CHANGES_REQUESTED` advances `CHANGES_REQUESTED → SUBMITTED`, but only
    while `revision_round` has not exceeded three completed rounds — a fourth attempt
    is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 422)."
    PRD 3.2: "A `REQUEST_CHANGES` outcome instead advances `UNDER_VALIDATION →
    CHANGES_REQUESTED` and increments `revision_round` by one; it has no gates of its
    own beyond the state check."

    Design: Corner/validations/corner_fifth_submission_after_four_change_requests_is_refused
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    qualification = open_qualification(customer["id"], family["id"])
    rounds_seen = []
    for _ in range(4):
        submit_qualification(qualification["id"], customer["id"])
        append_validation_run(qualification["id"])
        decide_qualification(qualification["id"], "REQUEST_CHANGES")
        rounds_seen.append(read_qualification(qualification["id"])["revision_round"])

    response = api_client.submit_qualification(
        qualification["id"], make_customer_headers(customer["id"])
    )

    assert rounds_seen == [1, 2, 3, 4]
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 422)
    after = read_qualification(qualification["id"])
    assert after["revision_round"] == 4
    assert after["status"] == "CHANGES_REQUESTED"


# --------------------------------------------------------------------------- #
# the booking ladder
# --------------------------------------------------------------------------- #
def test_superseding_the_recipe_retroactively_closes_the_loading_door():
    """The pallet was received under a `QUALIFIED` recipe, but the booking reads the
    recipe's status now, and REV-A is `SUPERSEDED` by then.

    PRD 3.5: "The pallet's qualification must be `QUALIFIED`, or the refusal is
    `ERR_QUALIFICATION_NOT_QUALIFIED` (HTTP 422), and its `expires_at` must be
    strictly later than the logical clock, or the refusal is
    `ERR_QUALIFICATION_EXPIRED` (HTTP 422)."
    PRD 3.3: "Activation advances it `DRAFT → ACTIVE` and re-establishes that same
    opening ledger — `reserved_slots` and `consumed_slots` at zero and
    `available_slots` equal to `committed_slots` — making the slots bookable."

    Design: Corner/validations/corner_loading_a_superseded_qualification_is_refused
    """
    world = setup_scheduled_cycle()
    source = read_qualification(world["qualification"]["id"])
    supersede_qualification(
        source["id"], world["customer"]["id"], source["version"], version_label="REV-B"
    )
    assert read_qualification(source["id"])["status"] == "SUPERSEDED"

    response = api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=1000,
            expected_cycle_version=world["cycle"]["version"],
        ),
        SCHEDULER,
    )

    validate_error(
        response, ApiErrorId.ERR_QUALIFICATION_NOT_QUALIFIED.value, 422
    )
    assert list_loads(cycle_id=world["cycle"]["id"]) == []
    assert read_cycle(world["cycle"]["id"])["state"] == "SCHEDULED"
    contract = read_contract(world["contract"]["id"])
    assert contract["reserved_slots"] == 0
    assert contract["available_slots"] == 5


def test_a_pallet_cannot_be_booked_onto_another_familys_chamber_run():
    """One chamber runs one family, so an RTE_PRODUCE pallet offered to a juice cycle
    is refused rather than quietly re-scheduled.

    PRD 3.5: "The qualification's `product_family_id` must equal the cycle's
    `product_family_id`, since a chamber runs one family only — a mismatch is
    `ERR_FAMILY_MISMATCH` (HTTP 422)."
    PRD 3.5: "`baskets_used_total` is the sum of `baskets_used` across the cycle's
    loads whose `disposition_state` is anything other than `VOIDED`, which is why a
    voided load lowers utilisation on the next recompute."

    Design: Corner/validations/corner_loading_a_foreign_family_lot_is_refused
    """
    world = setup_stored_pallet()
    juice = define_family(
        family_code="RTE_JUICE",
        cross_contamination_group="JUICE",
        cleanout_minutes=30,
        requires_dedicated_cycle=False,
    )
    juice_cycle = schedule_cycle(
        world["vessel"]["id"], juice["id"], scheduled_start="2026-08-07T09:00:00Z"
    )

    response = api_client.create_cycle_load(
        juice_cycle["id"],
        create_cycle_load_payload(
            world["lot"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=1000,
            expected_cycle_version=juice_cycle["version"],
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_FAMILY_MISMATCH.value, 422)
    after = read_cycle(juice_cycle["id"])
    assert after["state"] == "SCHEDULED"
    assert after["baskets_used_total"] == 0
    assert read_lot(world["lot"]["id"])["units_untreated"] == 1000


def test_a_dedicated_family_refuses_a_second_customers_pallet():
    """The first pallet books normally; the second is refused for nothing but its
    ownership, and its own contract is left untouched.

    PRD 3.5: "When the family's `requires_dedicated_cycle` is true, every
    non-`VOIDED` load already on the cycle must belong to the same customer as this
    pallet, and co-mingling is refused with `ERR_DEDICATED_CYCLE_REQUIRED` (HTTP
    422)."
    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero
    the contract advances `ACTIVE → EXHAUSTED`."

    Design: Corner/validations/corner_dedicated_cycle_refuses_a_second_customer
    """
    set_clock(CLOCK_AUG03)
    verde = register_customer()
    norte = register_customer(
        code="NORTE", name="Norte Fresh", billing_email="ap@norte.example"
    )
    family = define_family(family_code="RTE_DED", requires_dedicated_cycle=True)
    vessel = commission_vessel()
    room = define_cold_room()
    verde_recipe = qualify_recipe(verde["id"], family["id"], sku_code="DED-A")
    norte_recipe = qualify_recipe(norte["id"], family["id"], sku_code="DED-B")
    verde_contract = open_active_contract(verde["id"])
    norte_contract = open_active_contract(norte["id"], priority_rank=2)
    verde_pallet = store_pallet(
        verde["id"],
        verde_recipe["id"],
        room["id"],
        pallet_ref="PAL-A",
        unit_count=500,
        gross_weight_kg=320.0,
    )
    norte_pallet = store_pallet(
        norte["id"],
        norte_recipe["id"],
        room["id"],
        pallet_ref="PAL-B",
        unit_count=500,
        gross_weight_kg=320.0,
    )
    cycle = schedule_cycle(vessel["id"], family["id"])
    book_load(
        cycle["id"],
        verde_pallet["id"],
        verde_contract["id"],
        baskets_used=1,
        units_loaded=500,
    )

    response = api_client.create_cycle_load(
        cycle["id"],
        create_cycle_load_payload(
            norte_pallet["id"],
            norte_contract["id"],
            baskets_used=1,
            units_loaded=500,
            expected_cycle_version=cycle_version(cycle["id"]),
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_DEDICATED_CYCLE_REQUIRED.value, 422)
    assert read_cycle(cycle["id"])["baskets_used_total"] == 1
    assert len(list_loads(cycle_id=cycle["id"])) == 1
    refused = read_contract(norte_contract["id"])
    assert refused["reserved_slots"] == 0
    assert refused["available_slots"] == 5
    assert read_contract(verde_contract["id"])["reserved_slots"] == 1


def test_starting_a_chamber_set_below_the_qualified_recipe_is_refused():
    """A 500 MPa target schedules and loads happily; only the start compares it
    against the pallet's qualified 600 MPa.

    PRD 3.6: "The chamber's own recipe must be at least as severe as every recipe in
    it: the cycle's `target_pressure_mpa` must be greater than or equal to the largest
    `pressure_mpa` among the qualifications of the loaded pallets, and the cycle's
    `target_hold_seconds` must be greater than or equal to the largest
    `hold_time_seconds` among those same qualifications."
    PRD 3.6: "A successful start stamps `started_at` with the logical clock, moves the
    vessel `AVAILABLE → IN_USE`, and for each loaded pallet advances `IN_COLD_STORAGE
    → IN_VESSEL` while moving that load's `units_loaded` out of `units_untreated` and
    into `units_in_vessel`."

    Design: Corner/validations/corner_start_below_the_qualified_process_targets_is_refused
    """
    world = setup_stored_pallet()
    cycle = schedule_cycle(
        world["vessel"]["id"], world["family"]["id"], target_pressure_mpa=500.0
    )
    book_load(
        cycle["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
    )

    response = api_client.start_cycle(cycle["id"], OPERATOR)

    validate_error(
        response, ApiErrorId.ERR_CYCLE_TARGET_BELOW_QUALIFIED.value, 422
    )
    assert read_cycle(cycle["id"])["state"] == "LOADED"
    assert read_vessel(world["vessel"]["id"])["status"] == "AVAILABLE"
    lot = read_lot(world["lot"]["id"])
    assert lot["custody_state"] == "IN_COLD_STORAGE"
    assert lot["units_in_vessel"] == 0


def test_a_target_above_the_vessels_rating_is_refused_at_scheduling_time():
    """700 MPa on a 600 MPa machine never gets as far as the occupancy calendar.

    PRD 3.5: "The target pressure may not exceed the vessel's `max_pressure_mpa`; an
    over-specification is refused with `ERR_PRESSURE_ABOVE_VESSEL_MAX` (HTTP 422)."

    Design: Corner/validations/corner_target_pressure_above_the_vessel_rating_is_refused
    """
    set_clock(CLOCK_AUG03)
    family = define_family()
    vessel = commission_vessel()

    response = api_client.create_vessel_cycle(
        create_vessel_cycle_payload(
            vessel["id"], family["id"], target_pressure_mpa=700.0
        ),
        SCHEDULER,
    )

    validate_error(
        response, ApiErrorId.ERR_PRESSURE_ABOVE_VESSEL_MAX.value, 422
    )
    assert list_cycles(vessel_id=vessel["id"]) == []


def test_basket_capacity_is_measured_against_the_accumulated_total():
    """Two baskets are already spoken for, so a three-basket request overflows the
    four-basket carrier and the incumbent load survives untouched.

    PRD 3.5: "The chamber must physically hold the load: the cycle's existing
    `baskets_used_total` plus the requested `baskets_used` must not exceed the
    vessel's `basket_count`, or the refusal is `ERR_BASKET_CAPACITY_EXCEEDED` (HTTP
    422)."
    PRD 3.5: "Chamber utilisation, `utilization_pct`, is 100 multiplied by the cycle's
    `baskets_used_total` and divided by the vessel's `basket_count`, rounded half up
    to two decimal places."

    Design: Corner/validations/corner_basket_capacity_is_checked_against_the_running_total
    """
    world = setup_loaded_cycle()
    second = add_stored_pallet(world, "PAL-002", 500, gross_weight_kg=320.0)

    response = api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            second["id"],
            world["contract"]["id"],
            baskets_used=3,
            units_loaded=500,
            expected_cycle_version=cycle_version(world["cycle"]["id"]),
        ),
        SCHEDULER,
    )

    validate_error(
        response, ApiErrorId.ERR_BASKET_CAPACITY_EXCEEDED.value, 422
    )
    after = read_cycle(world["cycle"]["id"])
    assert after["baskets_used_total"] == 2
    assert after["utilization_pct"] == 50.00
    assert read_contract(world["contract"]["id"])["reserved_slots"] == 1


def test_a_cycle_outside_the_contract_window_cannot_draw_on_its_slots():
    """The FY26 contract closes on the last instant of 2026, so a January run is
    refused on the window rule rather than on the recipe or the slot count.

    PRD 3.5: "The cycle's `scheduled_start` must fall inside the contract's inclusive
    window from `window_start` through `window_end`, or the refusal is
    `ERR_CONTRACT_WINDOW_MISMATCH` (HTTP 422)."
    PRD 2.6: "Because tier 9 precedes tier 14, a load booked against an expired
    qualification reports `ERR_QUALIFICATION_EXPIRED` even when the contract also has
    no slots left."

    Design: Corner/validations/corner_load_against_a_cycle_outside_the_contract_window_is_refused
    """
    world = setup_stored_pallet()
    late_cycle = schedule_cycle(
        world["vessel"]["id"],
        world["family"]["id"],
        scheduled_start="2027-01-05T09:00:00Z",
    )

    response = api_client.create_cycle_load(
        late_cycle["id"],
        create_cycle_load_payload(
            world["lot"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=1000,
            expected_cycle_version=late_cycle["version"],
        ),
        SCHEDULER,
    )

    validate_error(
        response, ApiErrorId.ERR_CONTRACT_WINDOW_MISMATCH.value, 422
    )
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_QUALIFICATION_EXPIRED.value
    )
    contract = read_contract(world["contract"]["id"])
    assert contract["reserved_slots"] == 0
    assert contract["available_slots"] == 5


def test_an_empty_scheduled_cycle_reports_emptiness_and_not_a_state_error():
    """`SCHEDULED` is an accepted start state, so the unloaded chamber falls all the
    way through to the emptiness rule.

    PRD 3.6: "A start attempted on a cycle that has already run, been terminated or
    been dispositioned is refused with `ERR_INVALID_CYCLE_STATE`; a start attempted on
    a cycle still sitting at `SCHEDULED` passes that state gate and is instead caught
    by the emptiness rule below, because a `SCHEDULED` cycle by definition has no
    loads."
    PRD 3.6: "The cycle must hold at least one load whose `disposition_state` is
    `PENDING`, since an empty chamber is never pressurised; an empty cycle is refused
    with `ERR_EMPTY_CYCLE` (HTTP 422)."

    Design: Corner/validations/corner_starting_an_empty_scheduled_cycle_is_refused
    """
    set_clock(CLOCK_AUG03)
    family = define_family()
    vessel = commission_vessel()
    cycle = schedule_cycle(vessel["id"], family["id"])

    response = api_client.start_cycle(cycle["id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_EMPTY_CYCLE.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_CYCLE_STATE.value
    )
    assert read_cycle(cycle["id"])["state"] == "SCHEDULED"
    assert read_vessel(vessel["id"])["status"] == "AVAILABLE"


# --------------------------------------------------------------------------- #
# the receiving dock
# --------------------------------------------------------------------------- #
def test_a_trailer_above_the_families_receipt_ceiling_is_turned_away():
    """The inbound gate reads the ceiling from the family behind the qualification,
    and 5.2 C against 4.0 C never reaches the room at all.

    PRD 3.4: "The trailer temperature must not exceed the family's
    `max_receipt_temp_c`, or the pallet is refused with `ERR_COLD_CHAIN_BREACH`."
    PRD 3.4: "Receipt snapshots the pallet's `segregation_group` from the
    `cross_contamination_group` of the product family reached through the
    qualification, freezing it on the pallet so later changes to configuration cannot
    silently re-zone stored product."

    Design: Corner/validations/corner_receipt_above_the_family_receipt_temp_is_refused
    """
    world = setup_qualified_facility()

    response = api_client.create_lot(
        create_lot_payload(
            world["customer"]["id"],
            world["qualification"]["id"],
            world["room"]["id"],
            pallet_ref="PAL-WARM",
            unit_count=100,
            gross_weight_kg=70.0,
            carrier_temp_c=5.2,
        ),
        OPERATOR,
    )

    validate_error(response, ApiErrorId.ERR_COLD_CHAIN_BREACH.value, 422)
    assert list_lots(customer_id=world["customer"]["id"]) == []
    assert read_cold_room(world["room"]["id"])["occupied_pallets"] == 0


def test_a_trailer_exactly_on_the_receipt_ceiling_is_accepted():
    """The comparison is an at-most, so a reading equal to the 4.0 C ceiling passes
    and the pallet is created in the ordinary way.

    PRD 3.4: "The trailer temperature must not exceed the family's
    `max_receipt_temp_c`, or the pallet is refused with `ERR_COLD_CHAIN_BREACH`."
    PRD 3.4: "On acceptance the pallet advances `AT_DOCK → IN_COLD_STORAGE`, no units
    move at all (the unit ledger was already opened at receipt), the room's
    `occupied_pallets` rises by one, and the room's `capacity_state` is recomputed —
    flipping `NORMAL → AT_CAPACITY` when `occupied_pallets` has reached
    `capacity_pallets`."

    Design: Corner/validations/corner_receipt_exactly_at_the_receipt_temp_limit_is_accepted
    """
    world = setup_qualified_facility()

    lot = validate_success(
        api_client.create_lot(
            create_lot_payload(
                world["customer"]["id"],
                world["qualification"]["id"],
                world["room"]["id"],
                pallet_ref="PAL-EDGE",
                unit_count=100,
                gross_weight_kg=70.0,
                carrier_temp_c=4.0,
            ),
            OPERATOR,
        ),
        201,
    )

    assert lot["custody_state"] == "AT_DOCK"
    assert lot["carrier_temp_c"] == 4.0
    assert lot["units_untreated"] == 100
    assert read_cold_room(world["room"]["id"])["occupied_pallets"] == 0


def test_a_room_that_does_not_admit_the_group_refuses_an_in_spec_pallet():
    """CR-2 admits juice only, so an RTE_PRODUCE pallet is refused on segregation
    grounds despite an in-spec trailer and an empty room.

    PRD 3.4: "The pallet's `segregation_group` must appear in the room's
    `allowed_family_groups`, or the refusal is `ERR_SEGREGATION_ZONE_VIOLATION`."
    PRD 2.8: "A cold room declares `allowed_family_groups`, a non-empty list of those
    same five values, and a pallet whose `segregation_group` is not among them cannot
    be received into that room — the refusal is `ERR_SEGREGATION_ZONE_VIOLATION` (HTTP
    422)."

    Design: Corner/validations/corner_receipt_into_a_zone_that_disallows_the_group_is_refused
    """
    world = setup_qualified_facility()
    juice_room = define_cold_room(
        room_code="CR-2",
        capacity_pallets=4,
        setpoint_c=2.0,
        allowed_family_groups=["JUICE"],
    )

    response = api_client.create_lot(
        create_lot_payload(
            world["customer"]["id"],
            world["qualification"]["id"],
            juice_room["id"],
            pallet_ref="PAL-ZONE",
            unit_count=100,
            gross_weight_kg=70.0,
        ),
        OPERATOR,
    )

    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_ZONE_VIOLATION.value, 422
    )
    assert list_lots(cold_room_id=juice_room["id"]) == []
    assert read_cold_room(juice_room["id"])["occupied_pallets"] == 0


def test_a_repeated_pallet_ref_for_the_same_customer_is_a_duplicate():
    """Uniqueness is scoped to the customer's own paperwork, and it is checked ahead
    of every room-capacity rule.

    PRD 3.4: "The `pallet_ref` must be unique among that customer's pallets; a repeat
    is refused with `ERR_DUPLICATE_PALLET_REF`."
    PRD 2.6: "10. **Uniqueness.** Business keys that must not collide, yielding HTTP
    409."

    Design: Corner/validations/corner_duplicate_pallet_ref_for_the_same_customer_is_refused
    """
    world = setup_qualified_facility()
    receive_pallet(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref="PAL-001",
    )

    response = api_client.create_lot(
        create_lot_payload(
            world["customer"]["id"],
            world["qualification"]["id"],
            world["room"]["id"],
            pallet_ref="PAL-001",
            unit_count=250,
            gross_weight_kg=160.0,
        ),
        OPERATOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PALLET_REF.value, 409)
    pallets = list_lots(customer_id=world["customer"]["id"])
    assert len(pallets) == 1
    assert pallets[0]["unit_count"] == 1000


def test_a_full_room_reports_the_posture_gate_before_the_interval_rule():
    """Two accepted pallets fill CR-1, so the third receipt breaks the instantaneous
    posture gate and the interval calculation at once — and the posture gate wins.

    PRD 3.4: "The room's derived posture must be `NORMAL` at this instant; a room
    already at `AT_CAPACITY` refuses further receipts with `ERR_COLD_ROOM_AT_CAPACITY`
    (HTTP 409)."
    PRD 3.1: "The room's `capacity_state` is a derived posture with exactly two values
    — it is `AT_CAPACITY` whenever `occupied_pallets` is greater than or equal to
    `capacity_pallets`, and `NORMAL` otherwise — and it is recomputed after every
    request that changes the room's occupancy."

    Design: Corner/validations/corner_full_cold_room_reports_the_posture_gate_not_the_interval_rule
    """
    world = setup_stored_pallet()
    add_stored_pallet(world, "PAL-002", 500, gross_weight_kg=320.0)
    room = read_cold_room(world["room"]["id"])
    assert room["occupied_pallets"] == 2
    assert room["capacity_state"] == "AT_CAPACITY"

    response = api_client.create_lot(
        create_lot_payload(
            world["customer"]["id"],
            world["qualification"]["id"],
            world["room"]["id"],
            pallet_ref="PAL-003",
            unit_count=100,
            gross_weight_kg=70.0,
        ),
        OPERATOR,
    )

    validate_error(response, ApiErrorId.ERR_COLD_ROOM_AT_CAPACITY.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_COLD_ROOM_CAPACITY_EXCEEDED.value
    )
    assert len(list_lots(cold_room_id=world["room"]["id"])) == 2


# --------------------------------------------------------------------------- #
# inspection arithmetic and the outbound cold chain
# --------------------------------------------------------------------------- #
def test_more_leakers_than_units_inspected_is_refused_before_any_pricing():
    """An impossible sample never becomes a rate, so no line is minted and the load
    stays uninspected.

    PRD 3.8: "A load whose `inspection_state` is already `INSPECTED` is refused with
    `ERR_LOAD_ALREADY_INSPECTED` (HTTP 409), and `leaker_units` exceeding
    `units_inspected` is refused with `ERR_LEAKERS_EXCEED_INSPECTED` (HTTP 422)."
    PRD 3.8: "The load's failure rate, `leaker_ppm`, is one million multiplied by
    `leaker_units` and divided by `units_inspected`, rounded half up to a whole part
    per million."

    Design: Corner/validations/corner_leaker_count_above_the_inspected_count_is_refused
    """
    world = setup_dispositioned_clean_cycle()

    response = api_client.record_load_inspection(
        world["load"]["id"],
        load_inspection_payload(units_inspected=100, leaker_units=101),
        QUALITY,
    )

    validate_error(
        response, ApiErrorId.ERR_LEAKERS_EXCEED_INSPECTED.value, 422
    )
    load = read_load(world["load"]["id"])
    assert load["inspection_state"] == "PENDING_INSPECTION"
    assert load["leaker_ppm"] is None
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 0
    assert list_chargeback_lines(customer_id=world["customer"]["id"]) == []


def test_quality_release_is_not_a_licence_to_ship_a_warm_trailer():
    """A fully released pallet on a 4.5 C truck is still refused, and none of the
    shipping cascade runs.

    PRD 3.9: "The outbound temperature must not exceed the family's
    `max_outbound_temp_c`, or the refusal is `ERR_OUTBOUND_TEMP_BREACH`."
    PRD 3.9: "A successful shipment advances the pallet `TREATED → SHIPPED`, lowers
    the cold room's `occupied_pallets` by one and recomputes the room's
    `capacity_state`, freeing a position for the next inbound pallet, and increments
    the pallet's `version`."

    Design: Corner/validations/corner_outbound_temp_breach_blocks_a_released_pallet
    """
    world = setup_dispositioned_clean_cycle()
    record_release_decision(world["lot"]["id"], "RELEASE", headers=QUALITY)

    response = api_client.ship_lot(
        world["lot"]["id"],
        ship_payload(outbound_temp_c=4.5, carrier_name="Frostline TRK-77"),
        OPERATOR,
    )

    validate_error(response, ApiErrorId.ERR_OUTBOUND_TEMP_BREACH.value, 422)
    lot = read_lot(world["lot"]["id"])
    assert lot["custody_state"] == "TREATED"
    assert lot["release_state"] == "RELEASED"
    assert read_cold_room(world["room"]["id"])["occupied_pallets"] == 1
