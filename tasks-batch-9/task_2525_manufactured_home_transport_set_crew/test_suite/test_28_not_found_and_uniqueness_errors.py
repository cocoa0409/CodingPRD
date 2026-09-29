"""Not-found reachability and the four scoped uniqueness conflicts.

The first group proves that every addressable collection reports its own 404
code, both for an unknown path id and for an unknown reference inside a creation
body.  The second group proves that each scoped uniqueness pairing refuses the
repeat and leaves the first row untouched.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    NOT_FOUND_BY_COLLECTION,
    api_client,
    create_anchor_certification_payload,
    create_escort_assignment_payload,
    create_marriage_joint_payload,
    create_order_payload,
    create_route_leg_payload,
    create_section_payload,
    create_set_job_payload,
    current_order_version,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
    measure_and_release_section,
    open_order,
    record_marriage_joint,
    record_section,
    register_plant,
    request_permit,
    set_logical_clock,
    setup_dispatched_set_job,
    setup_leg_awaiting_escorts,
    submit_anchor_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

READ_HEADERS = make_network_admin_headers()


@pytest.mark.parametrize(
    "collection, expected_error_id", sorted(NOT_FOUND_BY_COLLECTION.items())
)
def test_unknown_path_id_reports_the_addressed_entitys_own_not_found_code(
    collection, expected_error_id
):
    """PRD §2.10: "**Priority 4** — every `{id}` path parameter resolves to an
    existing row of the addressed entity, on every endpoint that has a path
    parameter. Violation: the 404 not-found code for that entity —
    `ERR_PLANT_NOT_FOUND`, `ERR_HAULER_NOT_FOUND`, `ERR_ESCORT_CREW_NOT_FOUND`,
    `ERR_SET_CREW_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ROUTE_LEG_NOT_FOUND`,
    `ERR_ESCORT_ASSIGNMENT_NOT_FOUND`, `ERR_SET_JOB_NOT_FOUND`,
    `ERR_MARRIAGE_JOINT_NOT_FOUND`, `ERR_ANCHOR_CERT_NOT_FOUND` or
    `ERR_CLAIM_NOT_FOUND`."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable_on_an_empty_db
    """
    set_logical_clock()
    response = api_client.request(
        "GET",
        f"/installations/{collection}/{NON_EXISTENT_UUID}",
        headers=READ_HEADERS,
    )
    validate_error(response, expected_error_id, 404)


def test_unknown_plant_reference_on_an_order_names_the_plant():
    """PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes."  PRD §2.10 pins the
    resolution order too: "an installation order resolves `plant_id`".

    Design: Corner/errors/unknown_body_foreign_keys_name_the_referenced_entity
    """
    set_logical_clock()
    response = api_client.create_order(
        create_order_payload(NON_EXISTENT_UUID), READ_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_PLANT_NOT_FOUND, 404)

    _, meta = validate_paginated(api_client.list_orders(READ_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused create left no order behind, got {meta['total_count']}"
    )


def test_unknown_hauler_reference_on_a_corridor_leg_names_the_hauler():
    """PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes. Body references are
    resolved left to right in the order the fields are declared for that
    endpoint, so the leftmost broken reference is the one reported: a damage claim
    resolves `order_id`, then `section_id`, then `hauler_id`, then `set_crew_id`;
    a set-job booking resolves `order_id` then `set_crew_id`; a corridor leg
    resolves `permit_id` then `hauler_id`; an escort reservation resolves
    `route_leg_id` then `escort_crew_id`; a permit request resolves `section_id`;
    a floor resolves `order_id` then `mates_to_section_id`; a site resolves
    `order_id`; a marriage joint resolves `set_job_id`; an anchoring package
    resolves `set_job_id`; and an installation order resolves `plant_id`."

    Design: Corner/errors/unknown_body_foreign_keys_name_the_referenced_entity
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1)
    section = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=1)

    response = api_client.create_route_leg(
        create_route_leg_payload(permit["id"], NON_EXISTENT_UUID),
        make_permit_desk_headers(),
    )
    validate_error(response, ApiErrorId.ERR_HAULER_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api_client.list_route_legs(READ_HEADERS, params={"permit_id": permit["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused create left no corridor leg behind, got {meta['total_count']}"
    )


def test_unknown_set_crew_reference_on_a_booking_names_the_set_crew():
    """PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes."  PRD §2.10 also ranks the
    concurrency guard below it: "**Priority 10** — the supplied expected parent
    version equals the parent row's current `version`."

    Design: Corner/errors/unknown_body_foreign_keys_name_the_referenced_entity
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1)

    response = api_client.create_set_job(
        create_set_job_payload(
            order["id"], NON_EXISTENT_UUID, current_order_version(order["id"])
        ),
        READ_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SET_CREW_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api_client.list_set_jobs(READ_HEADERS, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused booking left no set job behind, got {meta['total_count']}"
    )


def test_unknown_escort_crew_reference_on_a_reservation_names_the_escort_crew():
    """PRD §2.10: "**Priority 5** — every reference field in the request body
    resolves to an existing row of the referenced entity, on every creation
    endpoint. Violation: the same family of 404 codes."  PRD §2.10 pins the
    resolution order for this endpoint: "an escort reservation resolves
    `route_leg_id` then `escort_crew_id`".

    Design: Corner/errors/unknown_body_foreign_keys_name_the_referenced_entity
    """
    scenario = setup_leg_awaiting_escorts()

    response = api_client.create_escort_assignment(
        create_escort_assignment_payload(scenario["leg"]["id"], NON_EXISTENT_UUID),
        make_transport_manager_headers(scenario["hauler"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCORT_CREW_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api_client.list_escort_assignments(
            READ_HEADERS, params={"route_leg_id": scenario["leg"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused reservation left no assignment behind, got {meta['total_count']}"
    )


def test_repeated_section_index_is_refused_but_the_same_index_is_free_elsewhere():
    """PRD §2.10: "**Priority 24** — scoped uniqueness holds: the pairing of order
    and `section_index` is unique, the pairing of permit and leg `sequence_no` is
    unique, the pairing of set job and `joint_index` is unique, and at most one
    anchoring certification per set job exists in a status other than `FAILED`.
    Applies to `POST /installations/sections`, `POST /installations/route-legs`,
    `POST /installations/marriage-joints` and
    `POST /installations/anchor-certifications`. Violation:
    `ERR_DUPLICATE_SECTION_INDEX`, `ERR_DUPLICATE_LEG_SEQUENCE`,
    `ERR_DUPLICATE_JOINT_INDEX` or `ERR_DUPLICATE_ANCHOR_CERT` respectively (all
    409)."

    Design: Corner/errors/all_four_scoped_uniqueness_errors_are_reachable
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    first_order = open_order(plant["id"], section_count=1)
    second_order = open_order(plant["id"], section_count=1)
    dispatcher = make_plant_dispatcher_headers(plant["id"])
    record_section(first_order["id"], plant["id"], section_index=1)

    response = api_client.create_section(
        create_section_payload(
            first_order["id"], section_index=1, declared_width_in=180
        ),
        dispatcher,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SECTION_INDEX, 409)

    data, meta = validate_paginated(
        api_client.list_sections(READ_HEADERS, params={"order_id": first_order["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the order still has exactly one floor, got {meta['total_count']}"
    )
    assert data[0]["declared_width_in"] == 168, (
        "the refused create left the first floor untouched, expected 168, got "
        f"{data[0]['declared_width_in']}"
    )

    elsewhere = validate_success(
        api_client.create_section(
            create_section_payload(second_order["id"], section_index=1), dispatcher
        ),
        201,
    )
    assert elsewhere["section_index"] == 1, (
        "uniqueness is scoped to the order, so index 1 is free on another order, got "
        f"{elsewhere['section_index']}"
    )
    assert elsewhere["order_id"] == second_order["id"], (
        f"the second floor belongs to order {second_order['id']}, got "
        f"{elsewhere['order_id']}"
    )


def test_repeated_leg_sequence_number_on_the_same_permit_is_refused():
    """PRD §3.5: "A repeated sequence number on the same permit is refused with
    `ERR_DUPLICATE_LEG_SEQUENCE`."

    Design: Corner/errors/all_four_scoped_uniqueness_errors_are_reachable
    """
    scenario = setup_leg_awaiting_escorts()
    permit = scenario["permit"]

    response = api_client.create_route_leg(
        create_route_leg_payload(
            permit["id"],
            scenario["hauler"]["id"],
            sequence_no=1,
            corridor_id="AZ-I8",
            state_code="AZ",
        ),
        make_permit_desk_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_LEG_SEQUENCE, 409)

    data, meta = validate_paginated(
        api_client.list_route_legs(READ_HEADERS, params={"permit_id": permit["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the permit still carries exactly one leg, got {meta['total_count']}"
    )
    assert data[0]["corridor_id"] == "AZ-I10", (
        "the refused create left the first leg untouched, expected AZ-I10, got "
        f"{data[0]['corridor_id']}"
    )


def test_repeated_joint_index_on_the_same_set_job_is_refused():
    """PRD §3.7: "A repeated joint index on the same job is refused with
    `ERR_DUPLICATE_JOINT_INDEX`."

    Design: Corner/errors/all_four_scoped_uniqueness_errors_are_reachable
    """
    scenario = setup_dispatched_set_job(section_count=2)
    job = scenario["set_job"]
    crew_headers = make_set_crew_lead_headers(scenario["set_crew"]["id"])
    record_marriage_joint(
        job["id"],
        scenario["set_crew"]["id"],
        joint_index=1,
        gap_in=0.25,
        vertical_offset_in=0.0,
        ridge_beam_shim_in=0.0,
    )

    response = api_client.create_marriage_joint(
        create_marriage_joint_payload(job["id"], 1, gap_in=1.0),
        crew_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_JOINT_INDEX, 409)

    data, meta = validate_paginated(
        api_client.list_marriage_joints(READ_HEADERS, params={"set_job_id": job["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the job still carries exactly one joint reading, got {meta['total_count']}"
    )
    assert data[0]["gap_in"] == 0.25, (
        "the refused create left the recorded reading untouched, expected 0.25, got "
        f"{data[0]['gap_in']}"
    )


def test_second_anchoring_package_while_one_is_open_is_refused():
    """PRD §3.8: "A submission for a job that already has a certification in any
    status other than `FAILED` is refused with `ERR_DUPLICATE_ANCHOR_CERT`, and a
    submission under a crew whose licence has lapsed is refused with
    `ERR_INSTALLER_LICENSE_INVALID`. A new package opens at `status` `SUBMITTED`
    with `revision_round` at 1 and `certifier_user_id` null."

    Design: Corner/errors/all_four_scoped_uniqueness_errors_are_reachable
    """
    scenario = setup_dispatched_set_job(section_count=1)
    job = scenario["set_job"]
    crew = scenario["set_crew"]
    first = submit_anchor_certification(job["id"], crew["id"])
    assert first["status"] == "SUBMITTED", (
        f"a new package opens at SUBMITTED, got {first['status']}"
    )

    response = api_client.create_anchor_certification(
        create_anchor_certification_payload(job["id"], anchor_count=12),
        make_set_crew_lead_headers(crew["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ANCHOR_CERT, 409)

    data, meta = validate_paginated(
        api_client.list_anchor_certifications(READ_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the job still carries exactly one package, got {meta['total_count']}"
    )
    assert data[0]["anchor_count"] == 8, (
        "the refused submission left the open package untouched, expected 8 anchors, "
        f"got {data[0]['anchor_count']}"
    )
    assert data[0]["revision_round"] == 1, (
        f"the open package is still on revision round 1, got {data[0]['revision_round']}"
    )
