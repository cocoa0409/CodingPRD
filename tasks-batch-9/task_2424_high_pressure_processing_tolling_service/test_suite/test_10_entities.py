"""Breadth over the entity layer: creation shapes, defaults, system fields, topology.

These probe the plainest promises the model makes — what a freshly created row
looks like, which inputs are optional, which are the server's to fill in, what a
list envelope carries, and how the many-to-many junction reads from both ends.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    commission_vessel,
    create_customer_payload,
    create_lot_payload,
    create_product_family_payload,
    cycle_log_payload,
    is_valid_uuid,
    list_cycle_logs,
    list_loads,
    list_lots,
    read_family,
    read_vessel,
    receive_pallet,
    setup_completed_clean_cycle,
    setup_loaded_cycle,
    setup_qualified_facility,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLOCK_AUG03, OPERATOR, QUALITY, SCHEDULER


def test_registering_a_customer_answers_201_with_both_counters_at_zero():
    """The brand owner arrives with no leaker history and no money owed, and the row
    is identified by a bare UUID.

    PRD 3.1: "A freshly registered customer starts with `trailing_leaker_ppm` at 0
    and `chargeback_balance_cents` at 0."
    PRD 2.4: "Every resource the API returns carries an `id`, which is a
    server-minted UUID with no type prefix and no client-supplied component, and a
    `created_at` timestamp in ISO 8601 UTC form with three fractional digits."

    Design: Corner/entities/corner_create_customer_returns_201_with_zeroed_counters
    """
    set_clock(CLOCK_AUG03)

    response = api_client.create_customer(
        create_customer_payload(
            code="VERDE", name="Verde Foods", billing_email="ap@verde.example"
        ),
        ADMIN,
    )
    customer = validate_success(response, 201)

    assert customer["name"] == "Verde Foods"
    assert customer["code"] == "VERDE"
    assert customer["billing_email"] == "ap@verde.example"
    assert customer["trailing_leaker_ppm"] == 0
    assert customer["chargeback_balance_cents"] == 0
    assert customer["version"] == 1
    assert is_valid_uuid(customer["id"])
    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"].startswith("req_")


def test_reading_an_unknown_cycle_id_answers_the_cycle_specific_not_found():
    """A well-formed UUID that resolves to nothing is a 404 naming the entity that
    failed to resolve, not a generic malformed-request 400.

    PRD 2.6: "**Path existence.** Each identifier taken from the URL resolves to a
    live row. The refusal names the entity that failed to resolve:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_FAMILY_NOT_FOUND`,
    `ERR_VESSEL_NOT_FOUND`, `ERR_COLD_ROOM_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_CYCLE_LOAD_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND` or
    `ERR_CHARGEBACK_LINE_NOT_FOUND`, each with HTTP 404."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/corner_get_vessel_cycle_unknown_id_returns_cycle_not_found
    """
    set_clock(CLOCK_AUG03)

    response = api_client.get_vessel_cycle(NON_EXISTENT_UUID, SCHEDULER)

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_receiving_a_pallet_without_a_ship_by_is_a_malformed_request():
    """`ship_by` closes the pallet's occupancy interval, so there is nothing to
    default it to and the request fails on schema before any room rule is consulted.

    PRD 3.4: "A `PlantOperator` receives one by recording the owning `customer_id`,
    the `qualification_id` naming the process recipe the pallet must be treated
    under, the `cold_room_id` of the room requested for storage, the carrier's
    `pallet_ref` from the receiving paperwork, the `unit_count` of saleable units on
    the pallet (greater than zero), the pallet's `gross_weight_kg`, the trailer
    reading `carrier_temp_c` taken at the door, and the customer-declared `ship_by`
    instant, which is the latest outbound date and therefore the end of the pallet's
    cold-room occupancy interval."
    PRD 2.6: "**Request schema.** Required fields present, types correct, enumerated
    values inside their declared domains, numeric bounds respected (`unit_count`
    greater than zero, `baskets_used` greater than zero, `units_inspected` greater
    than zero, `leaker_units` at least zero, `committed_slots` greater than zero,
    `peak_multiplier` at least 1.0), pattern-constrained strings matching their
    patterns (a customer's `code` and a deviation's `root_cause_code`), `window_end`
    strictly later than `window_start`, and pagination within its declared bounds —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_create_lot_without_ship_by_returns_invalid_request
    """
    world = setup_qualified_facility()
    payload = create_lot_payload(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref="PAL-900",
        unit_count=100,
        gross_weight_kg=70.0,
    )
    del payload["ship_by"]

    response = api_client.create_lot(payload, OPERATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert list_lots(customer_id=world["customer"]["id"]) == []


def test_a_family_defined_without_the_dedication_flag_defaults_it_to_false():
    """`requires_dedicated_cycle` is the family's only optional input, so a family
    that omits it lets several customers share one chamber run.

    PRD 3.1: "Defining one captures a `family_code`, which must be unique across all
    families — a collision yields `ERR_DUPLICATE_FAMILY_CODE` — together with the
    `cross_contamination_group` and the two cold-chain ceilings described in §2.8, a
    `cleanout_minutes` value of at least zero, and optionally
    `requires_dedicated_cycle`."

    Design: Corner/entities/corner_product_family_defaults_requires_dedicated_cycle_false
    """
    set_clock(CLOCK_AUG03)
    payload = create_product_family_payload(
        family_code="RTE_JUICE",
        cross_contamination_group="JUICE",
        cleanout_minutes=30,
        max_receipt_temp_c=4.0,
        max_outbound_temp_c=4.0,
    )
    assert "requires_dedicated_cycle" not in payload

    family = validate_success(api_client.create_product_family(payload, ADMIN), 201)

    assert family["requires_dedicated_cycle"] is False
    assert family["cleanout_minutes"] == 30
    assert family["cross_contamination_group"] == "JUICE"
    assert read_family(family["id"])["requires_dedicated_cycle"] is False


def test_a_received_pallet_ignores_client_supplied_states_and_ledgers():
    """Custody, release, the four unit buckets and the segregation zone are all the
    server's to set; the values the client sent for them are discarded.

    PRD 3.4: "Receipt snapshots the pallet's `segregation_group` from the
    `cross_contamination_group` of the product family reached through the
    qualification, freezing it on the pallet so later changes to configuration
    cannot silently re-zone stored product."
    PRD 3.4: "The pallet's `custody_state` begins at `AT_DOCK`, its `release_state`
    at `NOT_RELEASED`, its `pulp_temp_c`, `hold_reason` and `released_by_user_id` all
    null, and its unit ledger is opened with `units_untreated` equal to `unit_count`
    and `units_in_vessel`, `units_treated` and `units_disposed` all zero, so the
    conservation identity of §2.9 holds from the first instant."

    Design: Corner/entities/corner_lot_system_fields_ignore_client_supplied_states
    """
    world = setup_qualified_facility()

    lot = validate_success(
        api_client.create_lot(
            create_lot_payload(
                world["customer"]["id"],
                world["qualification"]["id"],
                world["room"]["id"],
                pallet_ref="PAL-001",
                custody_state="SHIPPED",
                release_state="RELEASED",
                units_untreated=0,
                units_treated=1000,
                segregation_group="RAW_PROTEIN",
            ),
            OPERATOR,
        ),
        201,
    )

    assert lot["custody_state"] == "AT_DOCK"
    assert lot["release_state"] == "NOT_RELEASED"
    assert lot["units_untreated"] == 1000
    assert lot["units_in_vessel"] == 0
    assert lot["units_treated"] == 0
    assert lot["units_disposed"] == 0
    assert lot["segregation_group"] == "RTE_PRODUCE"
    assert lot["version"] == 1


def test_patching_a_vessel_to_in_use_is_refused_and_leaves_the_status_alone():
    """`IN_USE` is a real vessel status but not one an administrator may supply, so
    the request is malformed rather than merely unauthorised.

    PRD 3.1: "A `FacilityAdmin` may take a machine out of service or return it to
    service by supplying a new `status`, but only `AVAILABLE`, `MAINTENANCE` or
    `DOWN` may be supplied that way — `IN_USE` is reserved for the system, which sets
    it when a chamber run begins and clears it when the run ends. Supplying `IN_USE`
    is a malformed request."

    Design: Corner/entities/corner_patch_vessel_to_in_use_is_invalid_request
    """
    set_clock(CLOCK_AUG03)
    vessel = commission_vessel()

    response = api_client.patch_vessel(vessel["id"], {"status": "IN_USE"}, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    after = read_vessel(vessel["id"])
    assert after["status"] == "AVAILABLE"
    assert after["version"] == 1


def test_listing_pallets_pages_the_filtered_set_and_rejects_a_zero_limit():
    """Two of three pallets come back with the true total alongside them, in
    created_at order, and a limit below the floor of 1 is refused outright.

    PRD 2.3: "The `meta` object of a list response carries `limit` and `offset` as
    they were applied, `total_count` as the number of rows matching the filters
    before the page window was taken, and `has_more` as a boolean that is true when
    rows remain beyond the current window."
    PRD 2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1, and
    may not be larger than 100."

    Design: Corner/entities/corner_list_lots_pagination_and_filter_envelope
    """
    world = setup_qualified_facility(room_capacity=3)
    first = receive_pallet(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref="PAL-001",
        unit_count=100,
        gross_weight_kg=70.0,
    )
    for ref in ("PAL-002", "PAL-003"):
        receive_pallet(
            world["customer"]["id"],
            world["qualification"]["id"],
            world["room"]["id"],
            pallet_ref=ref,
            unit_count=100,
            gross_weight_kg=70.0,
        )

    page, meta = validate_paginated(
        api_client.list_lots(
            OPERATOR,
            {"customer_id": world["customer"]["id"], "limit": 2, "offset": 0},
        )
    )
    refused = api_client.list_lots(
        OPERATOR, {"customer_id": world["customer"]["id"], "limit": 0}
    )

    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert page[0]["id"] == first["id"]
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_the_control_point_record_is_written_once_and_never_edited():
    """A second CCP capture on the same cycle is refused, the stored reading is the
    original one, and the row carries no version to bump.

    PRD 3.6: "Exactly one such record exists per cycle: a second attempt is refused
    with `ERR_DUPLICATE_CYCLE_LOG` (HTTP 409), and a capture attempted on a cycle
    that is not `RUNNING` is refused with `ERR_INVALID_CYCLE_STATE`."
    PRD 2.4: "Two resources are append-only event records and deliberately do not: a
    lab **validation run** and a chamber **cycle log** carry only `id` and
    `created_at`."

    Writing the record always moves the cycle out of `RUNNING`, so a second attempt
    necessarily also violates the state gate, and both checks live in the same
    tier 8 — PRD 2.6: "**State preconditions.** The target row's lifecycle state
    permits the requested transition, and single-occurrence records have not
    already been written. These yield HTTP 409." The PRD names both refusals but
    does not fix which of the two same-tier checks reports first, so either 409 is
    PRD-faithful; what the PRD does determine is that the second attempt is refused
    with a 409 and that the stored record is left exactly as first written.

    Design: Corner/entities/corner_cycle_log_is_write_once_immutable_record
    """
    world = setup_completed_clean_cycle()

    response = api_client.create_cycle_log(
        world["cycle"]["id"],
        cycle_log_payload(
            actual_pressure_mpa=600.0,
            actual_hold_seconds=300,
            come_up_seconds=104,
            water_temp_c=7.5,
        ),
        OPERATOR,
    )
    records = list_cycle_logs(world["cycle"]["id"])

    assert response.status_code == 409
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_DUPLICATE_CYCLE_LOG.value,
            ApiErrorId.ERR_INVALID_CYCLE_STATE.value,
        ],
    )
    assert len(records) == 1
    assert records[0]["actual_hold_seconds"] == 195
    assert "version" not in records[0]
    assert "updated_at" not in records[0]


def test_appending_a_validation_run_under_an_unknown_qualification_is_a_404():
    """The parent identifier is resolved first, so the body is never even looked at.

    PRD 2.6: "A request naming a validation-run collection under a qualification, or
    a load collection under a vessel cycle, must first resolve the parent
    identifier; if the parent does not exist the parent's own not-found error is
    returned and the remainder of the path is never considered."
    PRD 3.2: "The run's `qualification_id` is taken from the path rather than the
    body, and the appending manager's `X-User-ID` is stored as
    `recorded_by_user_id`."

    Design: Corner/entities/corner_validation_run_under_unknown_qualification_returns_404
    """
    set_clock(CLOCK_AUG03)

    response = api_client.append_validation_run(
        NON_EXISTENT_UUID,
        {
            "measured_pressure_mpa": 600.0,
            "measured_hold_time_seconds": 180,
            "achieved_log_reduction": 5.2,
            "package_integrity_result": "PASS",
            "units_tested": 50,
            "leaker_count": 0,
        },
        QUALITY,
    )

    validate_error(response, ApiErrorId.ERR_QUALIFICATION_NOT_FOUND.value, 404)


def test_the_load_junction_reads_back_identically_from_pallet_and_from_cycle():
    """Pallet and chamber run meet many-to-many through the load, and either filter
    finds the same single junction row.

    PRD 3.5: "Loads can be listed and filtered by `cycle_id`, `lot_id`,
    `contract_id`, `inspection_state` and `disposition_state`."
    PRD 3.5: "The booking carries the pallet as `lot_id`, the backing contract as
    `contract_id`, the number of carrier baskets the load occupies as `baskets_used`
    (greater than zero, and also the allocation weight for the cycle's fee), the
    `units_loaded` moved from the pallet into the chamber (greater than zero), and
    the `expected_cycle_version` of §2.5."

    Design: Corner/entities/corner_cycle_load_junction_is_readable_from_both_sides
    """
    world = setup_loaded_cycle()

    by_lot = list_loads(lot_id=world["lot"]["id"])
    by_cycle = list_loads(cycle_id=world["cycle"]["id"])

    assert len(by_lot) == 1
    assert len(by_cycle) == 1
    assert by_lot[0]["id"] == by_cycle[0]["id"] == world["load"]["id"]
    assert by_lot[0]["lot_id"] == world["lot"]["id"]
    assert by_lot[0]["cycle_id"] == world["cycle"]["id"]
    assert by_lot[0]["contract_id"] == world["contract"]["id"]
