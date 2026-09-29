"""Breadth over the role model: who may act, who may not, and who may not act twice.

The first two tests walk the quality organisation's exclusive surface and then bounce
the scheduler, the operator and the quality manager off each other's endpoints.  The
last four are the identity-sensitive cases: authentication before authorisation, the
one entity-backed role and its ownership check, and the two structural separations of
§2.10, where the bar is on the person rather than on the role.
"""

from test_helpers import (
    OPERATOR_BOB,
    QM_ALICE,
    QM_CAROL,
    ApiErrorId,
    adjudicate_deviation,
    adjudicate_deviation_payload,
    api_client,
    build_user_headers,
    create_vessel_payload,
    cycle_log_payload,
    dock_inspection_payload,
    list_cycle_logs,
    load_inspection_payload,
    make_customer_headers,
    make_quality_manager_headers,
    read_cycle,
    read_deviation,
    read_load,
    read_lot,
    read_vessel,
    receive_pallet,
    register_customer,
    release_decision_payload,
    set_clock,
    setup_completed_clean_cycle,
    setup_completed_deviated_cycle,
    setup_qualified_facility,
    setup_running_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CLOCK_AUG03,
    OPERATOR,
    QUALITY,
    QUALITY_SECOND,
    SCHEDULER,
)


def test_one_quality_manager_walks_the_whole_judgement_surface():
    """The same manager closes out the run, prices the leakers, and reads back both the
    money line and the customer it landed on.

    PRD 3.8: "Disposition is the moment the facility's commercial claim on a chamber
    run becomes real. A `QualityManager` closes out a completed cycle, and the request
    carries no body."
    PRD 3.8: "Once a cycle is dispositioned, each of its loads is inspected for package
    failures — the leaker check. A `QualityManager` records `units_inspected`, the
    number of units examined during post-cycle package inspection, and `leaker_units`,
    the number found leaking."
    PRD 4: "| GET | `/customers/{id}` | Read a customer with its trailing leaker rate
    and chargeback balance | FacilityAdmin, QualityManager, Customer |"
    PRD 4: "| GET | `/chargeback-lines` | List chargeback lines, filterable by
    customer, load, contract, deviation, basis and status | FacilityAdmin,
    QualityManager, Customer |"

    Design: Corner/rbac/corner_quality_manager_owns_the_ccp_judgement_surface
    """
    world = setup_completed_clean_cycle()

    validate_success(api_client.disposition_cycle(world["cycle"]["id"], QUALITY), 200)
    validate_success(
        api_client.record_load_inspection(
            world["load"]["id"], load_inspection_payload(1000, 3), QUALITY
        ),
        200,
    )
    lines, _ = validate_paginated(
        api_client.list_chargeback_lines(
            QUALITY, {"customer_id": world["customer"]["id"]}
        )
    )
    customer = validate_success(
        api_client.get_customer(world["customer"]["id"], QUALITY), 200
    )

    cycle = read_cycle(world["cycle"]["id"])
    load = read_load(world["load"]["id"])
    assert cycle["state"] == "DISPOSITIONED"
    assert cycle["actual_tolling_fee_cents"] == 12825
    assert load["inspection_state"] == "INSPECTED"
    assert load["leaker_ppm"] == 3000
    assert len(lines) == 1
    assert customer["chargeback_balance_cents"] == 6788


def test_no_role_may_reach_across_into_another_roles_exclusive_endpoint():
    """Role denial is decided before any state or payload rule, so four cross-role
    attempts all bounce with the same code and the world is left exactly as it was.

    PRD 2.1: "If the headers are well-formed but the named role is not authorised for
    the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.6: "**Authorisation.** The acting role appears in the called endpoint's
    permitted-role list — otherwise `ERR_UNAUTHORIZED`."
    PRD 4: "| POST | `/vessel-cycles/{id}/cycle-logs` | Capture the critical control
    point record for the cycle exactly once; the computed verdict decides which branch
    the cycle takes | PlantOperator |"
    PRD 4: "| POST | `/vessel-cycles/{id}/disposition` | Close out a completed cycle,
    freeze the actual tolling fee and allocate it across the loads | QualityManager |"
    PRD 4: "| POST | `/vessels` | Commission an HPP vessel | FacilityAdmin |"
    PRD 4: "| POST | `/lots/{id}/inspect` | Record the dock inspection; `outcome` is
    `ACCEPT` or `REJECT` | PlantOperator |"

    Design: Corner/rbac/corner_scheduler_and_operator_cannot_cross_into_quality_operations
    """
    world = setup_running_cycle()

    scheduler_logging = api_client.create_cycle_log(
        world["cycle"]["id"],
        cycle_log_payload(
            actual_pressure_mpa=600.0,
            actual_hold_seconds=195,
            come_up_seconds=104,
            water_temp_c=7.5,
        ),
        SCHEDULER,
    )
    operator_dispositioning = api_client.disposition_cycle(
        world["cycle"]["id"], OPERATOR
    )
    manager_commissioning = api_client.create_vessel(
        create_vessel_payload(vessel_code="HPP-9"), QUALITY
    )
    scheduler_inspecting = api_client.inspect_lot(
        world["lot"]["id"], dock_inspection_payload("ACCEPT", 3.2), SCHEDULER
    )

    for response in (
        scheduler_logging,
        operator_dispositioning,
        manager_commissioning,
        scheduler_inspecting,
    ):
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert list_cycle_logs(world["cycle"]["id"]) == []
    assert read_cycle(world["cycle"]["id"])["state"] == "RUNNING"
    assert read_vessel(world["vessel"]["id"])["vessel_code"] == "HPP-1"
    assert read_lot(world["lot"]["id"])["custody_state"] == "IN_VESSEL"


def test_an_absent_or_unrecognised_role_header_never_reaches_the_role_check():
    """Authentication is decided first, so both an omitted role and an invented one are
    401s rather than the 403 a known-but-wrong role would earn.

    PRD 2.1: "Every request to this API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that principal
    is acting in. If either header is missing or empty, or if `X-User-Role` is not one
    of the five recognised role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.6: "**Authentication.** `X-User-ID` and `X-User-Role` both present and
    non-empty, and `X-User-Role` naming a recognised role — otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/corner_missing_or_unknown_role_header_cannot_reach_any_endpoint
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()

    without_role = api_client.get_customer(customer["id"], {"X-User-ID": "fa-root-01"})
    invented_role = api_client.get_customer(
        customer["id"], build_user_headers("fa-root-01", "Janitor")
    )

    for response in (without_role, invented_role):
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        body = response.json()["data"]
        assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
        assert "code" not in body
        assert "chargeback_balance_cents" not in body


def test_a_brand_owner_reads_its_own_pallet_and_only_its_own():
    """`Customer` is the one entity-backed role, so the same pallet id is a 403 for the
    neighbouring brand owner and a 200 for the owner named on the row.

    PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `Customer` record; ownership checks on any resource that references a `Customer`
    compare the resource's customer foreign key to `X-User-ID`, following the reference
    chain where necessary — a qualification and a contract carry `customer_id`
    directly, a pallet carries `customer_id`, a load reaches its customer through the
    pallet it draws from, and a chargeback line carries `customer_id`. A `Customer`
    that acts on, or reads, a resource belonging to a different customer is refused
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD 2.6: "**Ownership.** When the acting role is `Customer`, `X-User-ID` matches
    the owning customer of the target resource — otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/corner_customer_cannot_read_another_customers_pallet
    """
    world = setup_qualified_facility()
    neighbour = register_customer(
        code="NORTE", name="Norte Alimentos", billing_email="ap@norte.example"
    )
    pallet = receive_pallet(
        world["customer"]["id"], world["qualification"]["id"], world["room"]["id"]
    )

    refused = api_client.get_lot(pallet["id"], make_customer_headers(neighbour["id"]))
    allowed = api_client.get_lot(
        pallet["id"], make_customer_headers(world["customer"]["id"])
    )

    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    own = validate_success(allowed, 200)
    assert own["pallet_ref"] == "PAL-001"
    assert own["customer_id"] == world["customer"]["id"]


def test_the_operator_who_signed_the_control_point_record_cannot_judge_it():
    """The bar is on the identity rather than the role: op_bob wearing a quality hat is
    refused, and a manager who signed nothing clears the same deviation.

    PRD 2.10: "The `PlantOperator` whose `X-User-ID` was stamped into a cycle log's
    `logged_by_user_id` may never adjudicate a deviation that this same control-point
    record raised. An adjudication request whose `X-User-ID` equals the raising log's
    `logged_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.7: "The separation-of-duties rule of §2.10 then applies: when the deviation
    points at a control-point record, the adjudicating `X-User-ID` must differ from
    that record's `logged_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_the_operator_who_signed_the_log_cannot_adjudicate_it
    """
    world = setup_completed_deviated_cycle(actual_hold_seconds=179)

    refused = api_client.adjudicate_deviation(
        world["deviation"]["id"],
        adjudicate_deviation_payload("ACCEPT", "EQUIP_PUMP_FAULT"),
        make_quality_manager_headers(OPERATOR_BOB),
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    still_open = read_deviation(world["deviation"]["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["adjudicated_by_user_id"] is None

    adjudicate_deviation(
        world["deviation"]["id"], "ACCEPT", root_cause_code="EQUIP_PUMP_FAULT"
    )

    cleared = read_deviation(world["deviation"]["id"])
    assert cleared["status"] == "ADJUDICATED_ACCEPT"
    assert cleared["adjudicated_by_user_id"] == QM_ALICE
    assert list_cycle_logs(world["cycle"]["id"])[0]["logged_by_user_id"] == OPERATOR_BOB


def test_releasing_a_held_pallet_needs_eyes_other_than_the_adjudicators():
    """qm_alice accepted the deviation that put the pallet on hold, so she cannot sign
    it out; qm_carol sends the identical payload and it succeeds.

    PRD 2.10: "When a pallet sits at `ON_HOLD_FOR_TEST`, the `QualityManager` who
    releases it must not be a `QualityManager` who adjudicated any deviation on the
    chamber run that put it there. Concretely, the releasing `X-User-ID` must differ
    from every `adjudicated_by_user_id` recorded on any deviation belonging to that
    cycle; if it matches even one, the release is refused with
    `ERR_FOUR_EYES_REQUIRED` (HTTP 403)."
    PRD 3.9: "A `RELEASE` advances the pallet `NOT_RELEASED → RELEASED`, or
    `ON_HOLD_FOR_TEST → RELEASED` when it was on hold, in which case `hold_reason` is
    cleared to null. Either way `released_by_user_id` is stamped with the acting
    `X-User-ID`."

    Design: Corner/rbac/corner_four_eyes_required_between_adjudication_and_release
    """
    world = setup_completed_deviated_cycle(actual_hold_seconds=179)
    adjudicate_deviation(
        world["deviation"]["id"], "ACCEPT", root_cause_code="EQUIP_PUMP_FAULT"
    )
    validate_success(api_client.disposition_cycle(world["cycle"]["id"], QUALITY), 200)
    held_version = read_lot(world["lot"]["id"])["version"]
    assert read_lot(world["lot"]["id"])["release_state"] == "ON_HOLD_FOR_TEST"

    refused = api_client.record_release_decision(
        world["lot"]["id"], release_decision_payload("RELEASE", held_version), QUALITY
    )
    validate_error(refused, ApiErrorId.ERR_FOUR_EYES_REQUIRED.value, 403)
    assert read_lot(world["lot"]["id"])["version"] == held_version

    released = validate_success(
        api_client.record_release_decision(
            world["lot"]["id"],
            release_decision_payload("RELEASE", held_version),
            QUALITY_SECOND,
        ),
        200,
    )

    assert released["release_state"] == "RELEASED"
    assert released["released_by_user_id"] == QM_CAROL
    assert released["hold_reason"] is None
    assert released["custody_state"] == "TREATED"
    assert read_cycle(world["cycle"]["id"])["actual_tolling_fee_cents"] == 11400
