"""Breadth over the refusal surface: every code the ladder can produce, once each.

The not-found and duplicate families are probed entity by entity, because the
contract is that each failing reference and each uniqueness scope answers with its
own code rather than a shared one.  The rest are the one-shot rules — an inspection
that cannot run twice, a release that cannot precede the money, a waive that cannot
credit a customer twice — each checked with the surrounding state left untouched.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    QM_ALICE,
    ApiErrorId,
    adjudicate_deviation,
    adjudicate_deviation_payload,
    api_client,
    create_cold_room_payload,
    create_contract_payload,
    create_customer_payload,
    create_lot_payload,
    create_product_family_payload,
    create_qualification_payload,
    create_vessel_cycle_payload,
    create_vessel_payload,
    first_deviation_on_load,
    list_chargeback_lines,
    list_cycles,
    list_loads,
    list_lots,
    list_qualifications,
    load_inspection_payload,
    make_customer_headers,
    open_qualification,
    read_chargeback_line,
    read_cold_room,
    read_contract,
    read_customer,
    read_cycle,
    read_deviation,
    read_family,
    read_load,
    read_lot,
    read_vessel,
    release_decision_payload,
    record_release_decision,
    setup_completed_clean_cycle,
    setup_completed_deviated_cycle,
    setup_dispositioned_clean_cycle,
    setup_facility,
    setup_inspected_load,
    setup_loaded_cycle,
    setup_pending_chargeback_line,
    setup_scheduled_cycle,
    setup_stored_pallet,
    ship_payload,
    validate_error,
    waive_chargeback_line,
    waive_payload,
    write_contract,
)
from test_helpers.fixtures import ADMIN, OPERATOR, QUALITY, QUALITY_SECOND, SCHEDULER


def test_nine_single_resource_reads_on_an_empty_database_answer_nine_codes():
    """Each read names the entity that failed to resolve, so the nine refusals are
    nine distinct error_ids rather than one shared not-found code.

    PRD 2.6: "**Path existence.** Each identifier taken from the URL resolves to a
    live row. The refusal names the entity that failed to resolve:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_FAMILY_NOT_FOUND`,
    `ERR_VESSEL_NOT_FOUND`, `ERR_COLD_ROOM_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_CYCLE_LOAD_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND` or
    `ERR_CHARGEBACK_LINE_NOT_FOUND`, each with HTTP 404."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/errors/corner_every_path_id_404_names_its_own_entity
    """
    reads = [
        (api_client.get_customer(NON_EXISTENT_UUID, ADMIN), "ERR_CUSTOMER_NOT_FOUND"),
        (
            api_client.get_product_family(NON_EXISTENT_UUID, ADMIN),
            "ERR_PRODUCT_FAMILY_NOT_FOUND",
        ),
        (api_client.get_vessel(NON_EXISTENT_UUID, ADMIN), "ERR_VESSEL_NOT_FOUND"),
        (api_client.get_cold_room(NON_EXISTENT_UUID, ADMIN), "ERR_COLD_ROOM_NOT_FOUND"),
        (api_client.get_contract(NON_EXISTENT_UUID, ADMIN), "ERR_CONTRACT_NOT_FOUND"),
        (api_client.get_lot(NON_EXISTENT_UUID, QUALITY), "ERR_LOT_NOT_FOUND"),
        (
            api_client.get_cycle_load(NON_EXISTENT_UUID, ADMIN),
            "ERR_CYCLE_LOAD_NOT_FOUND",
        ),
        (api_client.get_deviation(NON_EXISTENT_UUID, ADMIN), "ERR_DEVIATION_NOT_FOUND"),
        (
            api_client.get_chargeback_line(NON_EXISTENT_UUID, ADMIN),
            "ERR_CHARGEBACK_LINE_NOT_FOUND",
        ),
    ]

    for response, expected in reads:
        validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"
    assert len({expected for _, expected in reads}) == 9


def test_each_unresolvable_body_reference_is_reported_by_its_own_entity():
    """Six writes each carry exactly one unknown foreign key against an otherwise
    complete world, and each answers with the code of the reference that failed.

    PRD 2.6: "**Body reference existence.** Each foreign identifier carried in the
    request body resolves to a live row, reusing the same eleven not-found codes: a
    body `customer_id` that does not resolve yields `ERR_CUSTOMER_NOT_FOUND`, a
    `product_family_id` yields `ERR_PRODUCT_FAMILY_NOT_FOUND`, a `qualification_id`
    or a `supersedes_qualification_id` yields `ERR_QUALIFICATION_NOT_FOUND`, a
    `cold_room_id` yields `ERR_COLD_ROOM_NOT_FOUND`, a `vessel_id` yields
    `ERR_VESSEL_NOT_FOUND`, a `lot_id` yields `ERR_LOT_NOT_FOUND`, and a
    `contract_id` yields `ERR_CONTRACT_NOT_FOUND`."
    PRD 2.6: "Nested paths are resolved strictly left to right. A request naming a
    validation-run collection under a qualification, or a load collection under a
    vessel cycle, must first resolve the parent identifier; if the parent does not
    exist the parent's own not-found error is returned and the remainder of the path
    is never considered."

    Design: Corner/errors/corner_body_foreign_keys_404_by_referenced_entity
    """
    world = setup_scheduled_cycle()
    cycle_version = world["cycle"]["version"]

    unknown_customer = api_client.create_lot(
        create_lot_payload(
            NON_EXISTENT_UUID,
            world["qualification"]["id"],
            world["room"]["id"],
            pallet_ref="PAL-FK1",
            unit_count=100,
            gross_weight_kg=70.0,
        ),
        OPERATOR,
    )
    unknown_room = api_client.create_lot(
        create_lot_payload(
            world["customer"]["id"],
            world["qualification"]["id"],
            NON_EXISTENT_UUID,
            pallet_ref="PAL-FK2",
            unit_count=100,
            gross_weight_kg=70.0,
        ),
        OPERATOR,
    )
    unknown_vessel = api_client.create_vessel_cycle(
        create_vessel_cycle_payload(NON_EXISTENT_UUID, world["family"]["id"]), SCHEDULER
    )
    unknown_family = api_client.create_vessel_cycle(
        create_vessel_cycle_payload(world["vessel"]["id"], NON_EXISTENT_UUID), SCHEDULER
    )
    unknown_lot = api_client.create_cycle_load(
        world["cycle"]["id"],
        {
            "lot_id": NON_EXISTENT_UUID,
            "contract_id": world["contract"]["id"],
            "baskets_used": 1,
            "units_loaded": 100,
            "expected_cycle_version": cycle_version,
        },
        SCHEDULER,
    )
    unknown_contract = api_client.create_cycle_load(
        world["cycle"]["id"],
        {
            "lot_id": world["lot"]["id"],
            "contract_id": NON_EXISTENT_UUID,
            "baskets_used": 1,
            "units_loaded": 100,
            "expected_cycle_version": cycle_version,
        },
        SCHEDULER,
    )

    validate_error(unknown_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)
    validate_error(unknown_room, ApiErrorId.ERR_COLD_ROOM_NOT_FOUND.value, 404)
    validate_error(unknown_vessel, ApiErrorId.ERR_VESSEL_NOT_FOUND.value, 404)
    validate_error(unknown_family, ApiErrorId.ERR_PRODUCT_FAMILY_NOT_FOUND.value, 404)
    validate_error(unknown_lot, ApiErrorId.ERR_LOT_NOT_FOUND.value, 404)
    validate_error(unknown_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)
    assert len(list_lots(customer_id=world["customer"]["id"])) == 1
    assert len(list_cycles(vessel_id=world["vessel"]["id"])) == 1
    assert list_loads(cycle_id=world["cycle"]["id"]) == []
    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["state"] == "SCHEDULED"
    assert cycle["version"] == cycle_version


def test_each_uniqueness_scope_answers_with_its_own_duplicate_code():
    """Six independent business keys collide in six different ways, and the composite
    qualification and contract scopes get their own codes too.

    PRD 2.6: "**Uniqueness.** Business keys that must not collide, yielding HTTP 409."
    PRD 3.1: "The `code` must consist only of uppercase letters, digits and
    underscores and be between 3 and 12 characters long, and it must be unique across
    all customers; a collision is refused with `ERR_DUPLICATE_CUSTOMER_CODE`."
    PRD 3.1: "Defining one captures a `family_code`, which must be unique across all
    families — a collision yields `ERR_DUPLICATE_FAMILY_CODE` — together with the
    `cross_contamination_group` and the two cold-chain ceilings described in §2.8, a
    `cleanout_minutes` value of at least zero, and optionally
    `requires_dedicated_cycle`."
    PRD 3.1: "Defining a **cold room** captures a `room_code`, unique across all
    rooms — otherwise `ERR_DUPLICATE_ROOM_CODE` — a `capacity_pallets` count greater
    than zero, the room's `setpoint_c`, and the non-empty `allowed_family_groups`
    list."
    PRD 3.2: "The combination of `customer_id`, `sku_code` and `version_label` must
    be unique across all qualifications, and a collision is refused with
    `ERR_DUPLICATE_QUALIFICATION_VERSION`."
    PRD 3.3: "The pair of `customer_id` and `season_code` must be unique across all
    contracts; a collision is refused with `ERR_DUPLICATE_CONTRACT_SEASON`."

    Design: Corner/errors/corner_each_uniqueness_constraint_has_its_own_code
    """
    world = setup_facility()
    open_qualification(world["customer"]["id"], world["family"]["id"])
    contract = write_contract(world["customer"]["id"])

    duplicate_customer = api_client.create_customer(
        create_customer_payload(name="Verde Foods Duplicate"), ADMIN
    )
    duplicate_family = api_client.create_product_family(
        create_product_family_payload(cleanout_minutes=45), ADMIN
    )
    duplicate_vessel = api_client.create_vessel(create_vessel_payload(), ADMIN)
    duplicate_room = api_client.create_cold_room(create_cold_room_payload(), ADMIN)
    duplicate_qualification = api_client.create_qualification(
        create_qualification_payload(world["customer"]["id"], world["family"]["id"]),
        make_customer_headers(world["customer"]["id"]),
    )
    duplicate_contract = api_client.create_contract(
        create_contract_payload(world["customer"]["id"], committed_slots=3), ADMIN
    )

    validate_error(
        duplicate_customer, ApiErrorId.ERR_DUPLICATE_CUSTOMER_CODE.value, 409
    )
    validate_error(duplicate_family, ApiErrorId.ERR_DUPLICATE_FAMILY_CODE.value, 409)
    validate_error(duplicate_vessel, ApiErrorId.ERR_DUPLICATE_VESSEL_CODE.value, 409)
    validate_error(duplicate_room, ApiErrorId.ERR_DUPLICATE_ROOM_CODE.value, 409)
    validate_error(
        duplicate_qualification,
        ApiErrorId.ERR_DUPLICATE_QUALIFICATION_VERSION.value,
        409,
    )
    validate_error(
        duplicate_contract, ApiErrorId.ERR_DUPLICATE_CONTRACT_SEASON.value, 409
    )
    assert read_customer(world["customer"]["id"])["code"] == "VERDE"
    assert read_family(world["family"]["id"])["family_code"] == "RTE_GUAC"
    assert read_vessel(world["vessel"]["id"])["vessel_code"] == "HPP-1"
    assert read_cold_room(world["room"]["id"])["room_code"] == "CR-1"
    assert len(list_qualifications(customer_id=world["customer"]["id"])) == 1
    assert read_contract(contract["id"])["committed_slots"] == 5


def test_the_same_pallet_cannot_be_booked_onto_one_chamber_run_twice():
    """The version supplied is current and two baskets are still free, so the only
    thing wrong with the second booking is that the pallet is already aboard.

    PRD 3.5: "The pallet must be sitting in cold storage — a pallet whose
    `custody_state` is not `IN_COLD_STORAGE` yields `ERR_INVALID_LOT_CUSTODY_STATE` —
    and no non-`VOIDED` load on this cycle may already reference the same pallet, a
    repeat yielding `ERR_DUPLICATE_CYCLE_LOAD` (HTTP 409)."
    PRD 2.5: "If `expected_cycle_version` does not equal the cycle's current
    `version`, the request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) and
    no load is created."
    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero
    the contract advances `ACTIVE → EXHAUSTED`."

    Design: Corner/errors/corner_second_load_of_the_same_pallet_on_one_cycle_is_refused
    """
    world = setup_loaded_cycle()

    response = api_client.create_cycle_load(
        world["cycle"]["id"],
        {
            "lot_id": world["lot"]["id"],
            "contract_id": world["contract"]["id"],
            "baskets_used": 1,
            "units_loaded": 500,
            "expected_cycle_version": world["cycle"]["version"],
        },
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CYCLE_LOAD.value, 409)
    assert len(list_loads(cycle_id=world["cycle"]["id"])) == 1
    assert read_cycle(world["cycle"]["id"])["baskets_used_total"] == 2
    assert read_contract(world["contract"]["id"])["reserved_slots"] == 1


def test_a_load_cannot_be_package_inspected_before_its_cycle_is_dispositioned():
    """The chamber run is closed but not yet priced, so there is no frozen fee for a
    leaker charge to be measured against and the inspection is refused.

    PRD 3.8: "Inspection is deliberately gated behind disposition so that the load's
    `allocated_fee_cents` is already frozen before any chargeback is priced against
    it: an inspection attempted before the parent cycle reached `DISPOSITIONED` is
    refused with `ERR_CYCLE_NOT_DISPOSITIONED` (HTTP 409)."
    PRD 3.5: "A successful booking creates the load with `disposition_state` of
    `PENDING`, `inspection_state` of `PENDING_INSPECTION`, `allocated_fee_cents` null,
    `units_inspected`, `leaker_units`, `leaker_ppm` and `chargeback_party` all null,
    and `chargeback_cents` at 0."

    Design: Corner/errors/corner_inspection_before_disposition_is_refused
    """
    world = setup_completed_clean_cycle()
    assert world["cycle"]["state"] == "COMPLETED_CLEAN"

    response = api_client.record_load_inspection(
        world["load"]["id"], load_inspection_payload(1000, 1), QUALITY
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_DISPOSITIONED.value, 409)
    load = read_load(world["load"]["id"])
    assert load["allocated_fee_cents"] is None
    assert load["inspection_state"] == "PENDING_INSPECTION"
    assert read_cycle(world["cycle"]["id"])["state"] == "COMPLETED_CLEAN"


def test_a_second_package_sample_cannot_re_open_an_inspected_load():
    """Inspection is one-shot, so the 3000 ppm result and the single 6788-cent line it
    minted both stand.

    PRD 3.8: "A load whose `inspection_state` is already `INSPECTED` is refused with
    `ERR_LOAD_ALREADY_INSPECTED` (HTTP 409), and `leaker_units` exceeding
    `units_inspected` is refused with `ERR_LEAKERS_EXCEED_INSPECTED` (HTTP 422)."
    PRD 3.8: "When the party is `CUSTOMER`, two components are added. Handling is
    `leaker_units` multiplied by 125 cents per leaking unit. Rework is half the load's
    `allocated_fee_cents` — the allocated fee multiplied by 0.50 and rounded half up
    to a whole cent — but only when the load's `leaker_ppm` is at least 3,000; below
    that threshold the rework component is 0."

    Design: Corner/errors/corner_second_inspection_of_the_same_load_is_refused
    """
    world = setup_inspected_load()

    response = api_client.record_load_inspection(
        world["load"]["id"], load_inspection_payload(1000, 0), QUALITY
    )

    validate_error(response, ApiErrorId.ERR_LOAD_ALREADY_INSPECTED.value, 409)
    load = read_load(world["load"]["id"])
    lines = list_chargeback_lines(customer_id=world["customer"]["id"])
    assert load["leaker_units"] == 3
    assert load["leaker_ppm"] == 3000
    assert len(lines) == 1
    assert lines[0]["amount_cents"] == 6788
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 6788


def test_a_treated_pallet_that_quality_has_not_signed_out_cannot_ship():
    """Physically the pallet is ready to leave, but the release dimension still reads
    NOT_RELEASED, so the truck is turned away and the room keeps its position filled.

    PRD 3.9: "The pallet's custody must be `TREATED`, or the refusal is
    `ERR_INVALID_LOT_CUSTODY_STATE`; its `release_state` must be exactly `RELEASED`
    before it may leave the site, and a pallet that is not released — including one
    still on microbiological hold — is refused with `ERR_LOT_NOT_RELEASED` (HTTP
    409)."
    PRD 3.1: "`occupied_pallets` is not a free-running counter: it is the number of
    pallets assigned to this room whose `custody_state` is `IN_COLD_STORAGE`,
    `IN_VESSEL` or `TREATED`."

    Design: Corner/errors/corner_shipping_an_unreleased_pallet_is_refused
    """
    world = setup_dispositioned_clean_cycle()

    response = api_client.ship_lot(
        world["lot"]["id"], ship_payload(outbound_temp_c=2.0), OPERATOR
    )

    validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASED.value, 409)
    lot = read_lot(world["lot"]["id"])
    assert lot["custody_state"] == "TREATED"
    assert lot["release_state"] == "NOT_RELEASED"
    assert read_cold_room(world["room"]["id"])["occupied_pallets"] == 1


def test_a_pallet_that_has_never_been_treated_cannot_be_released():
    """The release dimension is a legal NOT_RELEASED and the supplied version is
    current, so the refusal is about custody rather than concurrency.

    PRD 3.9: "The pallet's custody must be `TREATED` in every case — a pallet that
    has not been through a chamber, or has already shipped, is refused with
    `ERR_INVALID_LOT_CUSTODY_STATE`."
    PRD 2.5: "Recording a quality release decision on a pallet requires
    `expected_lot_version`, matching that `Lot`'s current `version`."

    Design: Corner/errors/corner_release_decision_on_an_untreated_pallet_is_refused
    """
    world = setup_stored_pallet()
    current_version = read_lot(world["lot"]["id"])["version"]

    response = api_client.record_release_decision(
        world["lot"]["id"],
        release_decision_payload("RELEASE", current_version),
        QUALITY,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_LOT_CUSTODY_STATE.value, 409)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_STALE_LOT_VERSION.value
    )
    lot = read_lot(world["lot"]["id"])
    assert lot["custody_state"] == "IN_COLD_STORAGE"
    assert lot["release_state"] == "NOT_RELEASED"
    assert lot["version"] == current_version


def test_a_released_pallet_accepts_no_further_release_decision():
    """RELEASED is terminal on the release dimension, so a second decision carrying a
    perfectly fresh version is still refused and the original signature stands.

    PRD 3.9: "The release dimension is then checked: `RELEASE` and `REJECT` are both
    accepted from `NOT_RELEASED` and from `ON_HOLD_FOR_TEST`, while `HOLD_FOR_TEST` is
    accepted only from `NOT_RELEASED`, and a pallet already at `RELEASED` or at
    `REJECTED` accepts nothing further. A decision the release dimension does not
    permit is refused with `ERR_INVALID_LOT_RELEASE_STATE` (HTTP 409)."
    PRD 3.9: "A `RELEASE` advances the pallet `NOT_RELEASED → RELEASED`, or
    `ON_HOLD_FOR_TEST → RELEASED` when it was on hold, in which case `hold_reason` is
    cleared to null. Either way `released_by_user_id` is stamped with the acting
    `X-User-ID`."

    Design: Corner/errors/corner_release_decision_after_release_is_refused
    """
    world = setup_dispositioned_clean_cycle()
    record_release_decision(world["lot"]["id"], "RELEASE", headers=QUALITY)
    fresh_version = read_lot(world["lot"]["id"])["version"]

    response = api_client.record_release_decision(
        world["lot"]["id"],
        release_decision_payload("REJECT", fresh_version),
        QUALITY_SECOND,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_LOT_RELEASE_STATE.value, 409)
    lot = read_lot(world["lot"]["id"])
    assert lot["release_state"] == "RELEASED"
    assert lot["custody_state"] == "TREATED"
    assert lot["released_by_user_id"] == QM_ALICE
    assert lot["units_treated"] == 1000
    assert lot["units_disposed"] == 0


def test_an_adjudicated_deviation_cannot_be_adjudicated_a_second_time():
    """The state gate at tier 8 fires before any disposition rule, so a REPROCESS
    attempt on an accepted deviation reports the state error and no cascade runs.

    PRD 3.7: "The deviation's `status` must be `OPEN`; a second adjudication is
    refused with `ERR_INVALID_DEVIATION_STATE` (HTTP 409)."
    PRD 3.7: "An `ACCEPT` advances the deviation `OPEN → ADJUDICATED_ACCEPT` and does
    nothing else. No pallet moves, no fee is computed, no chargeback line is minted;
    the cycle still has to be dispositioned separately by a `QualityManager` as
    described in §3.8."
    PRD 3.7: "That prefix carries commercial weight: a `root_cause_code` beginning
    with `PKG_` sets the deviation's `chargeback_party` to `CUSTOMER`, because the
    customer's package failed, and any other prefix sets it to `FACILITY`."

    Design: Corner/errors/corner_second_adjudication_of_a_deviation_is_refused
    """
    world = setup_completed_deviated_cycle(actual_hold_seconds=179)
    adjudicate_deviation(
        world["deviation"]["id"], "ACCEPT", root_cause_code="EQUIP_PUMP_FAULT"
    )

    response = api_client.adjudicate_deviation(
        world["deviation"]["id"],
        adjudicate_deviation_payload("REPROCESS", "PKG_FILM_SPEC"),
        QUALITY_SECOND,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_DEVIATION_STATE.value, 409)
    deviation = read_deviation(world["deviation"]["id"])
    assert deviation["status"] == "ADJUDICATED_ACCEPT"
    assert deviation["chargeback_party"] == "FACILITY"
    assert deviation["adjudicated_by_user_id"] == QM_ALICE
    assert read_cycle(world["cycle"]["id"])["state"] == "COMPLETED_DEVIATED"
    assert read_lot(world["lot"]["id"])["units_treated"] == 1000


def test_a_waived_chargeback_line_cannot_be_waived_again():
    """The credit is granted once: the second waive is refused, the amount stays on
    the row for audit, and the balance is not credited twice into a negative figure.

    PRD 3.9: "Waiving advances the line `PENDING → WAIVED`, stamps
    `waived_by_user_id` with the acting `X-User-ID`, and lowers the charged customer's
    `chargeback_balance_cents` by exactly the line's `amount_cents`, which itself
    stays intact on the row for audit. A line that is already `WAIVED` cannot be
    waived again; the refusal is `ERR_INVALID_CHARGEBACK_STATE` (HTTP 409). `WAIVED`
    is terminal."
    PRD 3.8: "When the party is `CUSTOMER`, two components are added. Handling is
    `leaker_units` multiplied by 125 cents per leaking unit. Rework is half the load's
    `allocated_fee_cents` — the allocated fee multiplied by 0.50 and rounded half up
    to a whole cent — but only when the load's `leaker_ppm` is at least 3,000; below
    that threshold the rework component is 0."

    Design: Corner/errors/corner_second_waive_on_a_waived_line_is_refused
    """
    world = setup_pending_chargeback_line()
    line_id = world["chargeback_line"]["id"]
    waive_chargeback_line(line_id, "goodwill credit for first offence")

    response = api_client.waive_chargeback_line(
        line_id, waive_payload("duplicate goodwill request"), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CHARGEBACK_STATE.value, 409)
    line = read_chargeback_line(line_id)
    assert line["status"] == "WAIVED"
    assert line["amount_cents"] == 6788
    assert line["waive_reason"] == "goodwill credit for first offence"
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 0


def test_quality_cannot_release_a_pallet_ahead_of_the_cycles_disposition():
    """No deviation exists to blame, so the refusal is specifically that the parent
    chamber run has not yet been priced and closed out.

    PRD 3.9: "Second, the pallet's most recent non-`VOIDED` load must belong to a
    cycle that has reached `DISPOSITIONED`, so that the fee and the load outcome are
    frozen before quality signs the pallet out; otherwise the refusal is
    `ERR_CYCLE_NOT_DISPOSITIONED`. Because the deviation check is evaluated first, an
    open deviation is what the client is told about."
    PRD 3.6: "On the clean branch the cycle advances `RUNNING → COMPLETED_CLEAN`, no
    deviation is created, and every pallet's `release_state` stays exactly where it
    was at `NOT_RELEASED`."

    Design: Corner/errors/corner_release_before_the_cycle_is_dispositioned_is_refused
    """
    world = setup_completed_clean_cycle()
    current_version = read_lot(world["lot"]["id"])["version"]

    response = api_client.record_release_decision(
        world["lot"]["id"],
        release_decision_payload("RELEASE", current_version),
        QUALITY,
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_DISPOSITIONED.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_DEVIATION_UNRESOLVED.value
    )
    assert read_lot(world["lot"]["id"])["release_state"] == "NOT_RELEASED"
    assert read_load(world["load"]["id"])["allocated_fee_cents"] is None


def test_a_package_failure_deviation_can_only_ever_be_accepted():
    """This deviation was raised after the fee was allocated, so it carries a
    cycle_load_id and a reprocess would have to unwind money that is already billed.

    PRD 3.7: "Finally, a `REPROCESS` or a `REJECT` is refused when the deviation's
    `cycle_load_id` is not null, because a package-failure deviation is raised after
    the cycle's fee has already been allocated and can therefore only be accepted;
    that refusal is `ERR_DEVIATION_DISPOSITION_NOT_PERMITTED` (HTTP 422)."
    PRD 3.8: "A load at or above 3,000 ppm additionally raises a fresh `Deviation` at
    `OPEN`, with `deviation_type` of `PACKAGE_FAILURE_RATE`, `severity` of `MAJOR`,
    `worst_shortfall_pct` of 0.00, `cycle_load_id` pointing at this load and
    `cycle_log_id` null."

    Design: Corner/errors/corner_package_failure_deviation_cannot_be_reprocessed
    """
    world = setup_inspected_load()
    deviation = first_deviation_on_load(world["load"]["id"])

    response = api_client.adjudicate_deviation(
        deviation["id"],
        adjudicate_deviation_payload("REPROCESS", "PKG_SEAL_INTEGRITY"),
        QUALITY,
    )

    validate_error(
        response, ApiErrorId.ERR_DEVIATION_DISPOSITION_NOT_PERMITTED.value, 422
    )
    after = read_deviation(deviation["id"])
    load = read_load(world["load"]["id"])
    assert after["deviation_type"] == "PACKAGE_FAILURE_RATE"
    assert after["severity"] == "MAJOR"
    assert after["cycle_load_id"] == world["load"]["id"]
    assert after["status"] == "OPEN"
    assert load["disposition_state"] == "ALLOCATED"
    assert load["allocated_fee_cents"] == 12825
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 6788
