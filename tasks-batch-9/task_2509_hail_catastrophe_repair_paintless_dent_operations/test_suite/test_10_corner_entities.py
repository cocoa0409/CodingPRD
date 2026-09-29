"""Entity envelopes, defaults, body-shape refusals and cross-reference integrity."""

from test_helpers import (
    CLOCK_T0,
    CREW_COORDINATOR,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DIRECTOR,
    INTAKE_ADVISOR,
    MISSING_UUID,
    PERMIT_OFFICER,
    SHOP_ESTIMATOR,
    TECHNICIAN_SPECS,
    add_damage_line,
    add_second_facility,
    assert_damage_line_pricing,
    assert_no_version_or_updated_at,
    authorize_vehicle,
    damage_line_payload,
    estimate_vehicle,
    facility_payload,
    file_permit,
    ids_of,
    intake_vehicle,
    is_iso8601_timestamp,
    is_valid_uuid,
    line_by_panel,
    permit_decision_payload,
    read_damage_lines,
    read_deployment,
    read_vehicle,
    set_clock,
    setup_operational_facility,
    start_repair,
    storm_event_payload,
    tech_headers,
    tech_id,
    technician_payload,
    triage_vehicle,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
    work_ticket_payload,
)


def test_a_new_storm_event_answers_with_its_envelope_and_its_score(api):
    """PRD §3.1: "The new event lands in `EVALUATING` and its `demobilized_at` is
    null."

    PRD §3.1: "At the moment of registration — and only then — the server computes
    a `targeting_score` between 0 and 100 from those four swath and market inputs."

    PRD §2.5: "Every resource in the system carries a server-minted `id` formatted
    as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC
    with three fractional digits recording when the row was first written."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/storm_event_creation_returns_envelope_system_and_computed_fields
    """
    set_clock(api, CLOCK_T0)

    response = api.create_storm_event(storm_event_payload(), DIRECTOR)
    event = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert event["targeting_score"] == 72
    assert event["status"] == "EVALUATING"
    assert event["demobilized_at"] is None
    assert event["version"] == 1
    assert is_valid_uuid(event["id"])
    assert is_iso8601_timestamp(event["created_at"])
    assert is_iso8601_timestamp(event["updated_at"])
    assert event["name"] == "Wichita Supercell"
    assert event["max_hail_size_mm"] == 55
    assert event["swath_confidence"] == "GROUND_TRUTHED"


def test_a_freshly_taken_in_vehicle_reads_back_its_inputs_and_its_zeroes(api):
    """PRD §3.5: "Its `pinned_rate_agreement_id`, `matrix_variant_total_cents`,
    `conventional_variant_total_cents`, `triage_disposition`, `warranty_number`
    and `warranty_expires_at` are all null; `approved_repair_cents`,
    `approved_supplement_cents`, `admin_fee_cents`, `gross_billable_cents`,
    `discount_cents`, `net_billable_cents`, `rework_count`, `rental_days_billed`
    and `shop_absorbed_rental_cents` are all 0; and `released_at` and
    `rental_closed_at` are null."

    PRD §3.5: "When `rental_required` is true, intake stamps `rental_opened_at`
    from the logical clock, starting the rental exposure clock; when it is false,
    `rental_opened_at` stays null."

    Design: Corner/entities/vehicle_retrieval_returns_stored_inputs_and_zeroed_money_defaults
    """
    scenario = setup_operational_facility(api)
    created = intake_vehicle(api, scenario["facility_id"], scenario["insurer_id"])

    vehicle = read_vehicle(api, created["id"])
    assert vehicle["id"] == created["id"]
    assert vehicle["vin"] == "1HGCM82633A004352"
    assert vehicle["acv_cents"] == 2450000
    assert vehicle["owner_name"] == "D. Reyes"
    assert vehicle["facility_id"] == scenario["facility_id"]
    assert vehicle["insurer_id"] == scenario["insurer_id"]
    assert vehicle["repair_status"] == "INTAKE"
    assert vehicle["billing_status"] == "UNBILLED"
    for zeroed in (
        "approved_repair_cents",
        "approved_supplement_cents",
        "admin_fee_cents",
        "gross_billable_cents",
        "discount_cents",
        "net_billable_cents",
        "rework_count",
        "rental_days_billed",
        "shop_absorbed_rental_cents",
    ):
        assert vehicle[zeroed] == 0, zeroed
    for nulled in (
        "pinned_rate_agreement_id",
        "matrix_variant_total_cents",
        "conventional_variant_total_cents",
        "triage_disposition",
        "warranty_number",
        "warranty_expires_at",
        "released_at",
        "rental_closed_at",
    ):
        assert vehicle[nulled] is None, nulled
    assert vehicle["rental_opened_at"] == CLOCK_T0
    assert vehicle["version"] == 1


def test_the_deployment_filter_and_the_page_window_compose(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` — the total number of rows matching the filters before
    pagination — and `has_more`, a boolean that is true when rows remain beyond
    the current page."

    PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted
    value is 1, and its maximum accepted value is 100."

    PRD §2.10: "Crew deployments may be filtered by `technician_id`,
    `facility_id`, `housing_unit_id` and `status`."

    Design: Corner/entities/crew_deployment_listing_filters_by_facility_and_paginates
    """
    scenario = setup_operational_facility(
        api, technicians=("TA", "TB", "TD"), on_site=()
    )
    elsewhere = add_second_facility(api, scenario)
    stranger_id = elsewhere["deployments"]["TO"]["id"]
    home = scenario["facility_id"]

    first, first_meta = validate_paginated(
        api.list_crew_deployments(
            CREW_COORDINATOR, {"facility_id": home, "limit": 2, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert len(first) == 2

    second, second_meta = validate_paginated(
        api.list_crew_deployments(
            CREW_COORDINATOR, {"facility_id": home, "limit": 2, "offset": 2}
        )
    )
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False
    assert len(second) == 1
    assert stranger_id not in ids_of(first) + ids_of(second)

    unwindowed, unwindowed_meta = validate_paginated(
        api.list_crew_deployments(CREW_COORDINATOR, {"facility_id": home})
    )
    assert unwindowed_meta["total_count"] == 3
    assert unwindowed_meta["limit"] == DEFAULT_LIMIT
    assert unwindowed_meta["offset"] == DEFAULT_OFFSET
    for row in unwindowed:
        assert row["facility_id"] == home
        assert row["status"] == "CONFIRMED"
    assert read_deployment(api, stranger_id)["facility_id"] == elsewhere["facility_id"]


def test_each_unresolvable_identifier_names_its_own_entity(api):
    """PRD §2.10: "Unresolvable identifiers report the type-specific code where
    one exists — `ERR_STORM_EVENT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`,
    `ERR_RATE_AGREEMENT_NOT_FOUND` — and fall back to `ERR_RESOURCE_NOT_FOUND`
    for permits, housing units, crew deployments, damage lines, work tickets,
    supplements and quality inspections."

    PRD §2.11: "**Path existence** — every identifier in the path resolves,
    checked left to right: the 404 family above, on every endpoint carrying a path
    identifier."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/unknown_path_and_body_ids_return_their_own_not_found_error_ids
    """
    set_clock(api, CLOCK_T0)

    validate_error(
        api.get_storm_event(MISSING_UUID, DIRECTOR), "ERR_STORM_EVENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_facility(MISSING_UUID, DIRECTOR), "ERR_FACILITY_NOT_FOUND", 404
    )
    validate_error(
        api.get_vehicle(MISSING_UUID, INTAKE_ADVISOR), "ERR_VEHICLE_NOT_FOUND", 404
    )
    validate_error(
        api.get_technician(MISSING_UUID, CREW_COORDINATOR),
        "ERR_TECHNICIAN_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_insurer(MISSING_UUID, DIRECTOR), "ERR_INSURER_NOT_FOUND", 404
    )
    validate_error(
        api.get_rate_agreement(MISSING_UUID, DIRECTOR),
        "ERR_RATE_AGREEMENT_NOT_FOUND",
        404,
    )

    # The collapsed family: no code of their own to report.
    for response in (
        api.get_work_ticket(MISSING_UUID, SHOP_ESTIMATOR),
        api.get_supplement(MISSING_UUID, SHOP_ESTIMATOR),
        api.get_quality_inspection(MISSING_UUID, SHOP_ESTIMATOR),
    ):
        payload = validate_error(response, "ERR_RESOURCE_NOT_FOUND", 404)
        assert payload["message"]

    # A nested listing resolves its parent identifier first, so it names the site.
    validate_error(
        api.list_facility_permits(MISSING_UUID, DIRECTOR),
        "ERR_FACILITY_NOT_FOUND",
        404,
    )


def test_four_shapes_of_malformed_body_all_answer_the_same_way(api):
    """PRD §2.11: "**Request shape** — required fields present, enum values inside
    their declared sets, and numeric ranges honoured: `dent_count` at least 1,
    `acv_cents` at least 1, `staging_slot_count` at least 1, `bed_count` at least
    1, `flat_split_pct` greater than 0 and at most 1, `labor_units` at least 0,
    `requested_amount_cents` at least 1, `start_date` no later than `end_date`,
    `valid_from` no later than `valid_to`, `defect_panel_codes` empty when
    `result` is `PASS`, and `vin` exactly 17 characters. Violations yield
    `ERR_INVALID_REQUEST` (400), on every endpoint."

    PRD §3.5: "It carries the `dent_count` on that panel (at least 1), the
    `dent_size_class` of `DIME`, `NICKEL`, `QUARTER` or `HALF_DOLLAR`, and the
    `aluminum` flag marking a panel whose metal is harder to push."

    Design: Corner/entities/damage_line_missing_required_fields_and_bad_enums_rejected
    """
    scenario = setup_operational_facility(api)
    car = intake_vehicle(api, scenario["facility_id"], scenario["insurer_id"])

    missing = damage_line_payload(car["id"], r_and_i_hours=None)
    del missing["dent_size_class"]
    validate_error(
        api.create_damage_line(missing, INTAKE_ADVISOR), "ERR_INVALID_REQUEST", 400
    )

    validate_error(
        api.create_damage_line(
            damage_line_payload(car["id"], panel_code="SUNROOF"), INTAKE_ADVISOR
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_damage_line(
            damage_line_payload(car["id"], dent_count=0), INTAKE_ADVISOR
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_vehicle(
            vehicle_payload(
                scenario["facility_id"],
                scenario["insurer_id"],
                vin="1HGCM82633A00435",
                owner_name="T. Short",
                rental_required=False,
            ),
            INTAKE_ADVISOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _, lines_meta = validate_paginated(
        api.list_vehicle_damage_lines(car["id"], SHOP_ESTIMATOR)
    )
    assert lines_meta["total_count"] == 0
    _, cars_meta = validate_paginated(
        api.list_vehicles(INTAKE_ADVISOR, {"facility_id": scenario["facility_id"]})
    )
    assert cars_meta["total_count"] == 1

    settled = read_vehicle(api, car["id"])
    assert settled["repair_status"] == "INTAKE"
    assert settled["version"] == 1


def test_the_two_optional_panel_inputs_default_to_zero_rather_than_null(api):
    """PRD §3.5: "It optionally carries `r_and_i_hours`, the remove-and-install
    labour hours needed to reach the panel, defaulting to 0, and
    `oversize_dent_count`, the number of dents simply too large for paintless
    work, also defaulting to 0 and never negative."

    PRD §3.5: "A panel is routed to `CONVENTIONAL` in `routed_to` when it was
    capped or when its `oversize_dent_count` is greater than zero, and to `PDR`
    otherwise."

    PRD §3.5: "Feasibility follows from the panel-level findings: `pdr_feasible`
    is true only when no damage line of the vehicle was capped and the total of
    every line's `oversize_dent_count` across the vehicle is zero."

    Design: Corner/entities/damage_line_optional_hours_and_oversize_count_default_to_zero
    """
    scenario = setup_operational_facility(api)
    car = intake_vehicle(
        api, scenario["facility_id"], scenario["insurer_id"], rental_required=False
    )

    response = api.create_damage_line(
        damage_line_payload(car["id"], r_and_i_hours=None), INTAKE_ADVISOR
    )
    line = validate_success(response, 201)
    assert line["r_and_i_hours"] == 0
    assert line["oversize_dent_count"] == 0

    estimated = estimate_vehicle(api, car["id"])
    # Forty-two nickel dents at the volume tier and no remove-and-install labour.
    assert_damage_line_pricing(
        line_by_panel(read_damage_lines(api, car["id"]), "HOOD"),
        pdr_line_cents=107528,
        conventional_line_cents=77000,
        capped=False,
        routed_to="PDR",
    )
    assert estimated["matrix_variant_total_cents"] == 107528
    assert estimated["conventional_variant_total_cents"] == 77000
    assert estimated["pdr_feasible"] is True
    assert estimated["repair_status"] == "ESTIMATED"
    assert estimated["pinned_rate_agreement_id"] == scenario["rate_agreement_id"]


def test_a_posted_identifier_and_a_posted_balance_are_both_discarded(api):
    """PRD §2.5: "Most resources additionally carry an `updated_at` timestamp,
    refreshed on every mutation, and a `version` integer that starts at 1 on
    creation and increments by exactly one on every mutation of that resource —
    including mutations that only rewrite derived money or counter fields."

    PRD §3.3: "A fresh technician has `deployment_state` of `AVAILABLE`,
    `accrued_pay_cents` of 0 and `approved_ticket_count` of 0."

    PRD §2.5: "Every resource in the system carries a server-minted `id`
    formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO
    8601 UTC with three fractional digits recording when the row was first
    written."

    Design: Corner/entities/technician_system_and_computed_field_input_ignored
    """
    set_clock(api, CLOCK_T0)

    response = api.create_technician(
        technician_payload(
            **TECHNICIAN_SPECS["TA"],
            id=MISSING_UUID,
            version=99,
            accrued_pay_cents=500000,
            deployment_state="DEPLOYED",
        ),
        CREW_COORDINATOR,
    )
    technician = validate_success(response, 201)

    assert technician["id"] != MISSING_UUID
    assert is_valid_uuid(technician["id"])
    assert technician["version"] == 1
    assert technician["accrued_pay_cents"] == 0
    assert technician["approved_ticket_count"] == 0
    assert technician["deployment_state"] == "AVAILABLE"
    assert technician["full_name"] == "Tara Alvarez"
    assert technician["skill_tier"] == "MASTER"
    assert technician["flat_split_pct"] == 0.45


def test_ranges_intervals_and_enums_are_policed_independently(api):
    """PRD §3.2: "The creation payload names the parent event through
    `storm_event_id`, the facility `name`, the two-uppercase-letter `state_code`
    the lot physically sits in, the street `address`, the `staging_slot_count` of
    vehicle slots on that lot (at least 1), and the crew `pay_model`, which is
    either `FLAT` or `POOLED` and permanently selects which pay split the site's
    crews are paid under."

    PRD §3.3: "A `CrewCoordinator` adds a traveling technician to the roster with
    a `full_name`, the `home_state_code` of their home base, the
    two-uppercase-letter `license_state_code` of the state whose repair licence
    they actually hold, the `license_expires_at` date on which that licence lapses
    inclusively, a `skill_tier` of `APPRENTICE`, `JOURNEYMAN` or `MASTER`, and a
    `flat_split_pct` strictly greater than 0 and at most 1 representing their
    contracted share of ticket work value."

    PRD §3.2: "A filed permit sits in `PENDING` with a null `valid_from`, a null
    `valid_to` and a null `decided_at`; the shop does not get to choose its own
    validity window."

    Design: Corner/entities/storm_event_and_permit_range_constraints_rejected
    """
    scenario = setup_operational_facility(
        api, commission=False, activate_event=False, technicians=()
    )
    pending = file_permit(api, scenario["facility_id"], "FIRE_OCCUPANCY")

    validate_error(
        api.create_facility(
            facility_payload(
                scenario["event_id"],
                name="Zero Slot Lot",
                address="2 Nowhere Ave",
                staging_slot_count=0,
            ),
            DIRECTOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_technician(
            technician_payload(
                full_name="Over Split", home_state_code="KS", flat_split_pct=1.5
            ),
            CREW_COORDINATOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.decide_permit(
            pending["id"],
            permit_decision_payload("APPROVE", "2026-09-30", "2026-08-01"),
            PERMIT_OFFICER,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_storm_event(
            storm_event_payload(name="Bad Confidence", swath_confidence="GUESSED"),
            DIRECTOR,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    permits, _ = validate_paginated(
        api.list_facility_permits(
            scenario["facility_id"], DIRECTOR, {"permit_type": "FIRE_OCCUPANCY"}
        )
    )
    assert len(permits) == 1
    assert permits[0]["status"] == "PENDING"
    assert permits[0]["valid_from"] is None
    assert permits[0]["valid_to"] is None

    _, lots = validate_paginated(
        api.list_facilities(DIRECTOR, {"storm_event_id": scenario["event_id"]})
    )
    assert lots["total_count"] == 1


def test_a_damage_line_carries_no_version_and_is_corrected_by_addition(api):
    """PRD §2.5: "Three resource types are exceptions and carry only `id` and
    `created_at`: **Permit**, **DamageLine** and **QualityInspection** have no
    `updated_at` field and no `version` field at all."

    PRD §3.5: "The computed fields `pdr_line_cents`, `conventional_line_cents`,
    `capped` and `routed_to` stay null (with `capped` defaulting to false) until
    the next estimate runs, and damage lines are immutable once written."

    PRD §3.5: "Estimating is a `ShopEstimator` action that advances the vehicle to
    `ESTIMATED`, and it is re-runnable: the estimator may run it from `INTAKE` or
    from `ESTIMATED`, so adding a missed panel and re-pricing is a normal move."

    Design: Corner/entities/damage_line_is_immutable_with_no_version_and_no_update_path
    """
    scenario = setup_operational_facility(api)
    car = intake_vehicle(
        api, scenario["facility_id"], scenario["insurer_id"], rental_required=False
    )
    add_damage_line(api, car["id"], r_and_i_hours=0)
    estimate_vehicle(api, car["id"])

    lines, meta = validate_paginated(
        api.list_vehicle_damage_lines(car["id"], SHOP_ESTIMATOR)
    )
    assert meta["total_count"] == 1
    assert lines[0]["panel_code"] == "HOOD"
    for row in lines:
        assert_no_version_or_updated_at(row)
    assert lines[0]["pdr_line_cents"] == 107528

    # The only correction available is another row.
    add_damage_line(
        api,
        car["id"],
        panel_code="ROOF",
        dent_count=15,
        dent_size_class="DIME",
        conventional_labor_hours=12.0,
        conventional_paint_materials_cents=26000,
        r_and_i_hours=0,
    )
    reestimated = estimate_vehicle(api, car["id"])

    assert (
        line_by_panel(read_damage_lines(api, car["id"]), "HOOD")["pdr_line_cents"]
        == 107528
    )
    assert reestimated["matrix_variant_total_cents"] == 140723
    assert reestimated["conventional_variant_total_cents"] == 181000
    assert reestimated["repair_status"] == "ESTIMATED"
    _, after = validate_paginated(
        api.list_vehicle_damage_lines(car["id"], SHOP_ESTIMATOR)
    )
    assert after["total_count"] == 2


def test_a_licensed_technician_at_the_wrong_lot_cannot_claim_the_labour(api):
    """PRD §3.7: "Tickets may only be opened against a vehicle whose
    `repair_status` is `IN_REPAIR`, at a site whose `status` is `COMMISSIONED` and
    whose `posture` is not `FROZEN`, by a technician whose licence is valid —
    `license_expires_at` no earlier than the current clock date and
    `license_state_code` matching the site's `state_code`, else
    `ERR_TECHNICIAN_LICENSE_INVALID` — and who actually has a deployment with
    `status` of `ON_SITE` at that vehicle's facility, else
    `ERR_INSPECTOR_NOT_DEPLOYED`."

    PRD §2.11: "**Ticketing technician deployment** — the same
    `ERR_INSPECTOR_NOT_DEPLOYED` (409), on `POST /hail-ops/work-tickets`."

    PRD §3.7: "A new ticket lands in `OPEN` with `payable_flat_cents`,
    `payable_pooled_cents` and `payable_cents` all 0 and `pay_model_applied`
    null."

    Design: Corner/entities/work_ticket_requires_its_technician_deployed_at_the_vehicles_own_facility
    """
    scenario = setup_operational_facility(api)
    annex = add_second_facility(
        api,
        scenario,
        name="Salina Annex Lot",
        state_code="KS",
        address="700 E Crawford St",
        staging_slot_count=4,
        pay_model="FLAT",
        technicians=("TB",),
        commission=False,
    )
    car = intake_vehicle(
        api, scenario["facility_id"], scenario["insurer_id"], rental_required=False
    )
    add_damage_line(api, car["id"], r_and_i_hours=0)
    estimate_vehicle(api, car["id"])
    triage_vehicle(api, car["id"])
    authorize_vehicle(api, car["id"], scenario["insurer_id"])
    start_repair(api, car["id"])

    stranger_id = tech_id(annex, "TB")
    refused = api.create_work_ticket(
        work_ticket_payload(car["id"], stranger_id, labor_units=3.0, dents_repaired=20),
        tech_headers(annex, "TB"),
    )
    validate_error(refused, "ERR_INSPECTOR_NOT_DEPLOYED", 409)

    resident_id = tech_id(scenario, "TA")
    accepted = api.create_work_ticket(
        work_ticket_payload(car["id"], resident_id, labor_units=3.0, dents_repaired=20),
        tech_headers(scenario, "TA"),
    )
    ticket = validate_success(accepted, 201)
    assert ticket["status"] == "OPEN"
    assert ticket["payable_cents"] == 0
    assert ticket["technician_id"] == resident_id
    assert ticket["vehicle_id"] == car["id"]

    _, tickets = validate_paginated(
        api.list_work_tickets(SHOP_ESTIMATOR, {"vehicle_id": car["id"]})
    )
    assert tickets["total_count"] == 1
    assert read_vehicle(api, car["id"])["repair_status"] == "IN_REPAIR"
    stranger_deployment = read_deployment(api, annex["deployments"]["TB"]["id"])
    assert stranger_deployment["facility_id"] == annex["facility_id"]
    assert stranger_deployment["status"] == "ON_SITE"
