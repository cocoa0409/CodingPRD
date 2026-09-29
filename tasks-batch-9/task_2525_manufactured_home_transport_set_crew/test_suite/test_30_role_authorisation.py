"""Role authorisation, ownership scoping and the header ladder (PRD §2.1, §2.10, §4).

Each test drives the API through the seven roles the PRD names and pins the
error identifier the PRD attaches to a refusal, together with the positive
control proving the very same call succeeds for the role that owns it.
"""

from test_helpers import (
    ALL_ROLES,
    NON_EXISTENT_UUID,
    SITE_INSPECTOR_USER_ID,
    ApiErrorId,
    add_route_leg,
    adjudicate_damage_claim_payload,
    api_client,
    assert_allocation_sums_exactly,
    book_set_job,
    create_anchor_certification_payload,
    create_damage_claim_payload,
    create_marriage_joint_payload,
    create_permit_payload,
    create_plant_payload,
    create_route_leg_payload,
    create_section_payload,
    current_section_version,
    dispute_damage_claim_payload,
    headers_for_role,
    make_claims_adjuster_headers,
    make_inspector_headers,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
    measure_and_release_section,
    measure_section_payload,
    open_damage_claim,
    open_order,
    pay_and_issue_permit,
    pay_permit_fee_payload,
    read_damage_claim,
    read_plant,
    read_route_leg,
    read_section,
    read_set_crew,
    readiness_inspection_payload,
    record_section,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    request_permit,
    review_anchor_certification_payload,
    review_damage_claim,
    review_damage_claim_payload,
    reverse_damage_claim_payload,
    set_clock_payload,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PROBE_USER_ID = "probe-principal-1"


def _network_with_one_order():
    """A registered network plus one order, one released floor, a site and a crew."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    section = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(section["id"], plant["id"])
    site = register_site(order["id"], pad_type="RUNNER", pier_count=6)
    return {
        "plant": plant,
        "hauler": hauler,
        "set_crew": set_crew,
        "order": order,
        "section": section,
        "site": site,
    }


def _other_roles(owner_roles):
    """Every role in the PRD's seven that is not in ``owner_roles``."""
    return [role for role in ALL_ROLES if role not in owner_roles]


def test_network_admin_only_operations_are_closed_to_the_other_six_roles():
    """PRD §2.1: "If both headers are present but the named role is not authorised
    for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403); this gate runs before schema validation, so a wrong-role request
    carrying a malformed body still returns `ERR_UNAUTHORIZED` rather than a shape
    error." The administrator's exclusive surface is named in the same section:
    "It onboards plants, haulers, escort vendors and installer crews, books set
    jobs and authorises dispatch, and it is the only role that may drive the
    logical clock."

    Design: Corner/rbac/every_role_exclusive_operation_is_closed_to_the_other_six
    """
    set_logical_clock()

    for role in _other_roles(["NetworkAdmin"]):
        headers = headers_for_role(role, PROBE_USER_ID)
        validate_error(
            api_client.create_plant(create_plant_payload(), headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.set_clock(set_clock_payload("2026-08-02T00:00:00Z"), headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    plant = validate_success(
        api_client.create_plant(create_plant_payload(), make_network_admin_headers()),
        201,
    )
    assert plant["status"] == "ACTIVE", f"expected ACTIVE, got {plant['status']}"
    clock = validate_success(
        api_client.set_clock(
            set_clock_payload("2026-08-02T00:00:00Z"), make_network_admin_headers()
        ),
        200,
    )
    assert clock is not None, "the administrator's clock write must return a body"


def test_plant_floor_operations_are_closed_to_the_other_six_roles():
    """PRD §2.1 describes the dispatcher's exclusive surface — "It declares the
    home's floors, records plant-QC measurements, and releases floors to the permit
    desk." — and states that "If both headers are present but the named role is not
    authorised for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403); this gate runs before schema validation, so a
    wrong-role request carrying a malformed body still returns `ERR_UNAUTHORIZED`
    rather than a shape error."

    Design: Corner/rbac/every_role_exclusive_operation_is_closed_to_the_other_six
    """
    world = _network_with_one_order()
    section_id = world["section"]["id"]

    for role in _other_roles(["PlantDispatcher"]):
        headers = headers_for_role(role, PROBE_USER_ID)
        validate_error(
            api_client.create_section(
                create_section_payload(world["order"]["id"], section_index=2), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.measure_section(section_id, measure_section_payload(), headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.release_section(section_id, {}, headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    owner = make_plant_dispatcher_headers(world["plant"]["id"])
    second_order = open_order(world["plant"]["id"], section_count=1)
    fresh_floor = validate_success(
        api_client.create_section(create_section_payload(second_order["id"]), owner), 201
    )
    assert fresh_floor["transit_status"] == "AT_PLANT", (
        f"a newly declared floor starts AT_PLANT, got {fresh_floor['transit_status']}"
    )
    measured = validate_success(
        api_client.measure_section(
            fresh_floor["id"], measure_section_payload(), owner
        ),
        200,
    )
    assert measured["transit_status"] == "MEASURED", (
        f"expected MEASURED, got {measured['transit_status']}"
    )
    released = validate_success(
        api_client.release_section(fresh_floor["id"], {}, owner), 200
    )
    assert released["transit_status"] == "PERMIT_PENDING", (
        f"expected PERMIT_PENDING, got {released['transit_status']}"
    )


def test_the_permit_desk_and_the_carrier_cannot_take_each_others_permit_step():
    """PRD §2.1: "The role is deliberately separate from the carrier that pays the
    fee, so that no single principal can both pay for and issue the same permit."
    PRD §3.4: "A `PermitDesk` operator issues a permit that is in `FEE_PAID`,
    moving it `FEE_PAID → ISSUED`."

    Design: Corner/rbac/every_role_exclusive_operation_is_closed_to_the_other_six
    """
    world = _network_with_one_order()
    section_id = world["section"]["id"]
    carrier = make_transport_manager_headers(world["hauler"]["id"])
    desk = make_permit_desk_headers()

    validate_error(
        api_client.create_permit(
            create_permit_payload(section_id, current_section_version(section_id)),
            carrier,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    permit = validate_success(
        api_client.create_permit(
            create_permit_payload(section_id, current_section_version(section_id)), desk
        ),
        201,
    )
    assert permit["status"] == "REQUESTED", (
        f"a new permit opens at REQUESTED, got {permit['status']}"
    )
    validate_success(
        api_client.create_route_leg(
            create_route_leg_payload(permit["id"], world["hauler"]["id"]), desk
        ),
        201,
    )

    fee = permit["provisional_fee_cents"]
    validate_error(
        api_client.pay_permit_fee(permit["id"], pay_permit_fee_payload(fee), desk),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    paid = validate_success(
        api_client.pay_permit_fee(permit["id"], pay_permit_fee_payload(fee), carrier), 200
    )
    assert paid["paid_amount_cents"] == fee, (
        f"the remittance is added to paid_amount_cents, expected {fee}, "
        f"got {paid['paid_amount_cents']}"
    )
    assert paid["status"] == "FEE_PAID", (
        f"covering the provisional fee moves the permit to FEE_PAID, got {paid['status']}"
    )

    validate_error(
        api_client.issue_permit(permit["id"], {}, carrier),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.revoke_permit(permit["id"], {"reason_code": "BRIDGE_POSTING"}, carrier),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    issued = validate_success(api_client.issue_permit(permit["id"], {}, desk), 200)
    assert issued["status"] == "ISSUED", (
        f"the desk moves FEE_PAID -> ISSUED, got {issued['status']}"
    )


def test_crew_lead_and_inspector_operations_are_closed_to_the_other_six_roles():
    """PRD §2.1 splits the site work between two roles: the crew lead "records the
    marriage line, the skirting and steps scope split, the utility crossover, and
    the anchoring package", while the inspector "signs site readiness, certifies
    anchoring, and signs the final installation inspection that starts the
    warranty." A request from any other role "is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)".

    Design: Corner/rbac/every_role_exclusive_operation_is_closed_to_the_other_six
    """
    world = _network_with_one_order()
    job = book_set_job(world["order"]["id"], world["set_crew"]["id"])
    crew_lead = make_set_crew_lead_headers(world["set_crew"]["id"])
    site_id = world["site"]["id"]

    for role in _other_roles(["InstallationInspector"]):
        validate_error(
            api_client.inspect_site_readiness(
                site_id, readiness_inspection_payload(), headers_for_role(role, PROBE_USER_ID)
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
    verdict = validate_success(
        api_client.inspect_site_readiness(
            site_id,
            readiness_inspection_payload(),
            make_inspector_headers(SITE_INSPECTOR_USER_ID),
        ),
        200,
    )
    assert verdict["readiness_status"] == "READY", (
        f"a clean verdict on a fully piered site lands READY, got {verdict['readiness_status']}"
    )
    assert verdict["last_inspector_user_id"] == SITE_INSPECTOR_USER_ID, (
        "the readiness verdict records the signing inspector in last_inspector_user_id, "
        f"got {verdict['last_inspector_user_id']}"
    )

    for role in _other_roles(["SetCrewLead"]):
        headers = headers_for_role(role, PROBE_USER_ID)
        validate_error(
            api_client.create_marriage_joint(
                create_marriage_joint_payload(job["id"], 1), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.create_anchor_certification(
                create_anchor_certification_payload(job["id"]), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    certification = validate_success(
        api_client.create_anchor_certification(
            create_anchor_certification_payload(job["id"]), crew_lead
        ),
        201,
    )
    assert certification["status"] == "SUBMITTED", (
        f"a filed package opens at SUBMITTED, got {certification['status']}"
    )
    assert certification["revision_round"] == 1, (
        f"the first filing is revision_round 1, got {certification['revision_round']}"
    )

    validate_error(
        api_client.review_anchor_certification(
            certification["id"], review_anchor_certification_payload("CERTIFY"), crew_lead
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.dispatch_set_job(job["id"], {}, crew_lead),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )


def test_reads_are_open_to_all_seven_roles_while_shared_writes_accept_both_holders():
    """PRD §4: "In the table below, "Any" means all seven roles are authorised."
    PRD §3.5: "A corridor leg is the unit of actual movement, and either a
    `TransportManager` or a `PermitDesk` operator may add one to a permit."
    PRD §3.9: "A damage claim names four parties at once, and any of
    `PlantDispatcher`, `TransportManager`, `SetCrewLead` or `ClaimsAdjuster` may
    open one." and "A new claim opens at `status` `SUBMITTED` with `dispute_round`
    at 0, `allocation_basis` and `approved_amount_cents` null, and
    `plant_charge_cents`, `hauler_charge_cents` and `installer_charge_cents` all
    at 0."

    Design: Corner/rbac/every_role_exclusive_operation_is_closed_to_the_other_six
    """
    world = _network_with_one_order()
    section_id = world["section"]["id"]
    permit = request_permit(section_id, state_code="AZ", planned_leg_count=2)

    for role in ALL_ROLES:
        headers = headers_for_role(role, PROBE_USER_ID)
        read = validate_success(api_client.get_permit(permit["id"], headers), 200)
        assert read["id"] == permit["id"], (
            f"role {role} must be able to read the permit, got {read.get('id')}"
        )
        summary = validate_success(
            api_client.get_order_summary(world["order"]["id"], headers), 200
        )
        assert summary["order_id"] == world["order"]["id"], (
            f"role {role} must be able to read the order roll-up, got {summary}"
        )

    desk_leg = validate_success(
        api_client.create_route_leg(
            create_route_leg_payload(permit["id"], world["hauler"]["id"], sequence_no=1),
            make_permit_desk_headers(),
        ),
        201,
    )
    carrier_leg = validate_success(
        api_client.create_route_leg(
            create_route_leg_payload(permit["id"], world["hauler"]["id"], sequence_no=2),
            make_transport_manager_headers(world["hauler"]["id"]),
        ),
        201,
    )
    assert desk_leg["status"] == "SCHEDULED", (
        f"a corridor leg opens SCHEDULED, got {desk_leg['status']}"
    )
    assert carrier_leg["status"] == "SCHEDULED", (
        f"a corridor leg opens SCHEDULED, got {carrier_leg['status']}"
    )

    for opener in (
        make_plant_dispatcher_headers(world["plant"]["id"]),
        make_transport_manager_headers(world["hauler"]["id"]),
        make_set_crew_lead_headers(world["set_crew"]["id"]),
        make_claims_adjuster_headers(),
    ):
        claim = validate_success(
            api_client.create_damage_claim(
                create_damage_claim_payload(
                    world["order"]["id"],
                    section_id,
                    world["hauler"]["id"],
                    world["set_crew"]["id"],
                    discovered_stage="PLANT_QC",
                    claimed_amount_cents=100000,
                    blocks_set=False,
                ),
                opener,
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED", (
            f"a new claim opens at SUBMITTED, got {claim['status']}"
        )
        assert claim["dispute_round"] == 0, (
            f"a new claim opens with dispute_round at 0, got {claim['dispute_round']}"
        )


def _two_of_each_network():
    """Two plants, two carriers and two installer crews, with only the first of
    each attached to the live order, its permit, its leg and its set job."""
    set_logical_clock()
    plant_a = register_plant(state_code="AZ")
    plant_b = register_plant(state_code="AZ")
    hauler_a = register_hauler(endorsed_states=["AZ"])
    hauler_b = register_hauler(endorsed_states=["AZ"])
    crew_a = register_set_crew()
    crew_b = register_set_crew()

    order = open_order(plant_a["id"], section_count=2, destination_state="AZ", wind_zone="I")
    first = record_section(order["id"], plant_a["id"], section_index=1)
    second = record_section(
        order["id"], plant_a["id"], section_index=2, mates_to_section_id=first["id"]
    )
    measure_and_release_section(first["id"], plant_a["id"])
    permit = request_permit(first["id"], state_code="AZ", planned_leg_count=1)
    leg = add_route_leg(permit["id"], hauler_a["id"], sequence_no=1)
    pay_and_issue_permit(permit["id"], hauler_a["id"])
    job = book_set_job(order["id"], crew_a["id"])

    return {
        "plant_a": plant_a,
        "plant_b": plant_b,
        "hauler_a": hauler_a,
        "hauler_b": hauler_b,
        "crew_a": crew_a,
        "crew_b": crew_b,
        "order": order,
        "first": first,
        "second": second,
        "permit": permit,
        "leg": leg,
        "job": job,
    }


def test_a_dispatcher_from_another_plant_cannot_measure_this_homes_floor():
    """PRD §2.1: "An ownership violation by an entity-backed principal — a
    `PlantDispatcher` reaching for a floor built at a different plant, a
    `TransportManager` reaching for another carrier's leg, a `SetCrewLead` reaching
    for another company's set job — is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/entity_backed_principals_cannot_touch_a_foreign_plant_hauler_or_crew
    """
    world = _two_of_each_network()
    floor_id = world["second"]["id"]
    before = read_section(floor_id)

    validate_error(
        api_client.measure_section(
            floor_id,
            measure_section_payload(),
            make_plant_dispatcher_headers(world["plant_b"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.release_section(
            floor_id, {}, make_plant_dispatcher_headers(world["plant_b"]["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    untouched = read_section(floor_id)
    assert untouched["transit_status"] == "AT_PLANT", (
        f"the refused floor stays AT_PLANT, got {untouched['transit_status']}"
    )
    assert untouched["version"] == before["version"], (
        f"a refused request mutates nothing, expected version {before['version']}, "
        f"got {untouched['version']}"
    )

    owned = validate_success(
        api_client.measure_section(
            floor_id,
            measure_section_payload(),
            make_plant_dispatcher_headers(world["plant_a"]["id"]),
        ),
        200,
    )
    assert owned["transit_status"] == "MEASURED", (
        f"the owning plant's dispatcher may measure, got {owned['transit_status']}"
    )


def test_a_carrier_cannot_put_another_carriers_corridor_leg_on_the_road():
    """PRD §2.1: "An ownership violation by an entity-backed principal — a
    `PlantDispatcher` reaching for a floor built at a different plant, a
    `TransportManager` reaching for another carrier's leg, a `SetCrewLead` reaching
    for another company's set job — is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/entity_backed_principals_cannot_touch_a_foreign_plant_hauler_or_crew
    """
    world = _two_of_each_network()
    leg_id = world["leg"]["id"]
    stranger = make_transport_manager_headers(world["hauler_b"]["id"])

    validate_error(
        api_client.depart_route_leg(leg_id, {}, stranger),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.arrive_route_leg(leg_id, {}, stranger),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    held = read_route_leg(leg_id)
    assert held["status"] == "SCHEDULED", (
        f"the refused leg stays SCHEDULED, got {held['status']}"
    )

    rolling = validate_success(
        api_client.depart_route_leg(
            leg_id, {}, make_transport_manager_headers(world["hauler_a"]["id"])
        ),
        200,
    )
    assert rolling["status"] == "IN_TRANSIT", (
        f"the owning carrier moves the leg SCHEDULED -> IN_TRANSIT, got {rolling['status']}"
    )


def test_a_crew_lead_cannot_file_another_companys_anchoring_package():
    """PRD §2.1: "When `X-User-Role` is `SetCrewLead`, `X-User-ID` is the `id` of the
    acting `SetCrew`; ownership checks compare the addressed resource's
    `set_crew_id` to `X-User-ID`, resolving through the parent set job when the
    addressed row is a marriage joint or an anchoring certification."

    Design: Corner/rbac/entity_backed_principals_cannot_touch_a_foreign_plant_hauler_or_crew
    """
    world = _two_of_each_network()
    job_id = world["job"]["id"]
    stranger = make_set_crew_lead_headers(world["crew_b"]["id"])

    validate_error(
        api_client.create_anchor_certification(
            create_anchor_certification_payload(job_id), stranger
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.create_marriage_joint(
            create_marriage_joint_payload(job_id, 1), stranger
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    rows, _meta = validate_paginated(
        api_client.list_anchor_certifications(stranger, params={"set_job_id": job_id})
    )
    assert rows == [], f"a refused filing must persist nothing, got {rows}"
    joints, _joint_meta = validate_paginated(
        api_client.list_marriage_joints(stranger, params={"set_job_id": job_id})
    )
    assert joints == [], f"a refused joint must persist nothing, got {joints}"

    filed = validate_success(
        api_client.create_anchor_certification(
            create_anchor_certification_payload(job_id),
            make_set_crew_lead_headers(world["crew_a"]["id"]),
        ),
        201,
    )
    assert filed["status"] == "SUBMITTED", (
        f"the engaged crew's filing opens at SUBMITTED, got {filed['status']}"
    )
    assert filed["set_job_id"] == job_id, (
        f"the filing hangs off the engaged job, got {filed['set_job_id']}"
    )


def test_existence_outranks_ownership_for_a_foreign_entity_backed_principal():
    """PRD §2.1: "Ownership is evaluated only after the addressed row is known to
    exist, because it is an authorisation decision rather than an existence one."
    PRD §2.10 ranks priority 5 above priority 6, so a body reference that resolves
    to nothing is reported before any ownership decision: "**Priority 5** — every
    reference field in the request body resolves to an existing row of the
    referenced entity, on every creation endpoint."

    Design: Corner/rbac/entity_backed_principals_cannot_touch_a_foreign_plant_hauler_or_crew
    """
    world = _two_of_each_network()

    validate_error(
        api_client.measure_section(
            NON_EXISTENT_UUID,
            measure_section_payload(),
            make_plant_dispatcher_headers(world["plant_b"]["id"]),
        ),
        ApiErrorId.ERR_SECTION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.depart_route_leg(
            NON_EXISTENT_UUID, {}, make_transport_manager_headers(world["hauler_b"]["id"])
        ),
        ApiErrorId.ERR_ROUTE_LEG_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_anchor_certification(
            create_anchor_certification_payload(NON_EXISTENT_UUID),
            make_set_crew_lead_headers(world["crew_b"]["id"]),
        ),
        ApiErrorId.ERR_SET_JOB_NOT_FOUND,
        404,
    )


def _ladder_world():
    """One order with an `AT_PLANT` floor, plus a carrier and a crew to reference.

    The floor is deliberately left at `AT_PLANT`: PRD §3.2 pins plant QC to "a
    floor that is `AT_PLANT`", so the ladder probes below can use `measure` as
    their positive control on a resolvable path id.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    section = record_section(order["id"], plant["id"], section_index=1)
    return {
        "plant": plant,
        "hauler": hauler,
        "set_crew": set_crew,
        "order": order,
        "section": section,
    }


MEASURE_PATH = "/installations/sections/{section_id}/measure"


def test_absent_or_empty_identity_headers_are_rejected_before_anything_else():
    """PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before the body is parsed and before any path
    segment is resolved."

    Design: Corner/rbac/auth_ladder_401_then_403_then_400_then_404_then_body_fk
    """
    world = _ladder_world()
    unresolvable = MEASURE_PATH.format(section_id=NON_EXISTENT_UUID)
    nonsense_body = {"measured_width_in": "one hundred and sixty-eight"}

    header_probes = [
        {"Content-Type": "application/json"},
        {"X-User-Role": "PlantDispatcher", "Content-Type": "application/json"},
        {"X-User-ID": world["plant"]["id"], "Content-Type": "application/json"},
        {
            "X-User-ID": "",
            "X-User-Role": "PlantDispatcher",
            "Content-Type": "application/json",
        },
        {
            "X-User-ID": world["plant"]["id"],
            "X-User-Role": "",
            "Content-Type": "application/json",
        },
    ]
    for probe in header_probes:
        validate_error(
            api_client.request("POST", unresolvable, nonsense_body, headers=probe),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

    read_path = f"/installations/sections/{world['section']['id']}"
    validate_error(
        api_client.request("GET", read_path, headers={"Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    allowed = validate_success(
        api_client.request(
            "GET", read_path, headers=make_plant_dispatcher_headers(world["plant"]["id"])
        ),
        200,
    )
    assert allowed["id"] == world["section"]["id"], (
        f"the same read with both headers must succeed, got {allowed.get('id')}"
    )


def test_wrong_role_outranks_a_malformed_body_and_an_unresolvable_path_id():
    """PRD §2.10: "**Priority 2** — `X-User-Role` is one of the calling endpoint's
    authorised roles, on every endpoint. Violation: `ERR_UNAUTHORIZED` (403)."
    PRD §2.1 spells the consequence out: "this gate runs before schema validation,
    so a wrong-role request carrying a malformed body still returns
    `ERR_UNAUTHORIZED` rather than a shape error."

    Design: Corner/rbac/auth_ladder_401_then_403_then_400_then_404_then_body_fk
    """
    world = _ladder_world()
    unresolvable = MEASURE_PATH.format(section_id=NON_EXISTENT_UUID)

    validate_error(
        api_client.request(
            "POST",
            unresolvable,
            {"measured_width_in": "not a number"},
            headers=make_transport_manager_headers(world["hauler"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.request(
            "POST",
            unresolvable,
            {},
            headers=make_permit_desk_headers(),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )


def test_schema_failure_outranks_an_unresolvable_path_id_and_a_broken_body_reference():
    """PRD §2.10: "**Priority 3** — the request body parses and satisfies the endpoint's
    field schema: required fields present, types correct, enumerated values within
    range, numbers within their stated bounds, datetimes ISO 8601 UTC. Applies to
    every endpoint that has a request body. Violation: `ERR_INVALID_REQUEST` (400).
    This is a pure shape check performed with no database reads."

    Design: Corner/rbac/auth_ladder_401_then_403_then_400_then_404_then_body_fk
    """
    world = _ladder_world()
    dispatcher = make_plant_dispatcher_headers(world["plant"]["id"])

    validate_error(
        api_client.request(
            "POST",
            MEASURE_PATH.format(section_id=NON_EXISTENT_UUID),
            {"measured_width_in": 168},
            headers=dispatcher,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_section(
            create_section_payload(NON_EXISTENT_UUID, section_index=9), dispatcher
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


def test_an_unresolvable_path_id_reports_the_addressed_entitys_own_404_code():
    """PRD §2.10: "**Priority 4** — every `{id}` path parameter resolves to an existing
    row of the addressed entity, on every endpoint that has a path parameter."
    The same rung adds: "Path existence outranks body-reference existence, so a
    request with both a bad path id and a bad body reference returns the path error."

    Design: Corner/rbac/auth_ladder_401_then_403_then_400_then_404_then_body_fk
    """
    world = _ladder_world()
    dispatcher = make_plant_dispatcher_headers(world["plant"]["id"])

    validate_error(
        api_client.measure_section(NON_EXISTENT_UUID, measure_section_payload(), dispatcher),
        ApiErrorId.ERR_SECTION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_order(NON_EXISTENT_UUID, dispatcher),
        ApiErrorId.ERR_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_plant(NON_EXISTENT_UUID, dispatcher),
        ApiErrorId.ERR_PLANT_NOT_FOUND,
        404,
    )

    measured = validate_success(
        api_client.measure_section(
            world["section"]["id"], measure_section_payload(), dispatcher
        ),
        200,
    )
    assert measured["id"] == world["section"]["id"], (
        f"the resolvable path id must be served, got {measured.get('id')}"
    )


def test_body_references_are_resolved_left_to_right_and_report_the_leftmost_break():
    """PRD §2.10: "**Priority 5** — every reference field in the request body resolves
    to an existing row of the referenced entity, on every creation endpoint.
    Violation: the same family of 404 codes. Body references are resolved left to
    right in the order the fields are declared for that endpoint, so the leftmost
    broken reference is the one reported: a damage claim resolves `order_id`, then
    `section_id`, then `hauler_id`, then `set_crew_id`; a set-job booking resolves
    `order_id` then `set_crew_id`; a corridor leg resolves `permit_id` then
    `hauler_id`; an escort reservation resolves `route_leg_id` then
    `escort_crew_id`; a permit request resolves `section_id`; a floor resolves
    `order_id` then `mates_to_section_id`; a site resolves `order_id`; a marriage
    joint resolves `set_job_id`; an anchoring package resolves `set_job_id`; and an
    installation order resolves `plant_id`."

    Design: Corner/rbac/auth_ladder_401_then_403_then_400_then_404_then_body_fk
    """
    world = _ladder_world()
    order_id = world["order"]["id"]
    section_id = world["section"]["id"]
    desk = make_permit_desk_headers()
    adjuster = make_claims_adjuster_headers()

    validate_error(
        api_client.create_permit(
            create_permit_payload(NON_EXISTENT_UUID, 1), desk
        ),
        ApiErrorId.ERR_SECTION_NOT_FOUND,
        404,
    )

    permit = validate_success(
        api_client.create_permit(
            create_permit_payload(section_id, current_section_version(section_id)), desk
        ),
        201,
    )
    validate_error(
        api_client.create_route_leg(
            create_route_leg_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), desk
        ),
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_route_leg(
            create_route_leg_payload(permit["id"], NON_EXISTENT_UUID), desk
        ),
        ApiErrorId.ERR_HAULER_NOT_FOUND,
        404,
    )
    legs, _leg_meta = validate_paginated(
        api_client.list_route_legs(desk, params={"permit_id": permit["id"]})
    )
    assert legs == [], f"no leg may survive a broken reference, got {legs}"

    claim_probes = [
        (
            (NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            ApiErrorId.ERR_ORDER_NOT_FOUND,
        ),
        (
            (order_id, NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            ApiErrorId.ERR_SECTION_NOT_FOUND,
        ),
        (
            (order_id, section_id, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            ApiErrorId.ERR_HAULER_NOT_FOUND,
        ),
        (
            (order_id, section_id, world["hauler"]["id"], NON_EXISTENT_UUID),
            ApiErrorId.ERR_SET_CREW_NOT_FOUND,
        ),
    ]
    for refs, expected_error in claim_probes:
        validate_error(
            api_client.create_damage_claim(
                create_damage_claim_payload(
                    *refs, discovered_stage="PLANT_QC", claimed_amount_cents=100000
                ),
                adjuster,
            ),
            expected_error,
            404,
        )

    validate_error(
        api_client.create_set_job(
            {
                "order_id": NON_EXISTENT_UUID,
                "set_crew_id": NON_EXISTENT_UUID,
                "scheduled_start_date": "2026-08-10",
                "scheduled_end_date": "2026-08-11",
                "labor_base_cents": 480000,
                "expected_order_version": 1,
            },
            make_network_admin_headers(),
        ),
        ApiErrorId.ERR_ORDER_NOT_FOUND,
        404,
    )


def _claim_under_review():
    """One claim, opened at `PLANT_QC` for 100,000 cents and taken under review."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    section = record_section(order["id"], plant["id"], section_index=1)
    claim = open_damage_claim(
        order["id"],
        section["id"],
        hauler["id"],
        set_crew["id"],
        headers=make_claims_adjuster_headers(),
        discovered_stage="PLANT_QC",
        claimed_amount_cents=100000,
        blocks_set=False,
        plant_evidence_points=1,
        hauler_evidence_points=1,
        installer_evidence_points=0,
    )
    review_damage_claim(claim["id"])
    return {
        "plant": plant,
        "hauler": hauler,
        "set_crew": set_crew,
        "order": order,
        "section": section,
        "claim": claim,
    }


def test_a_named_party_may_dispute_and_rescore_the_evidence_split():
    """PRD §3.9: "The pushback carries a `reason_code` and may simultaneously
    re-score `plant_evidence_points`, `hauler_evidence_points` and
    `installer_evidence_points`, which changes the eventual evidence-based split;
    it moves the claim `UNDER_REVIEW → DISPUTED` and increments `dispute_round` by
    1." The same section adds: "The adjuster's review action is also the re-entry
    point, moving the claim `DISPUTED → UNDER_REVIEW` and closing the negotiation
    cycle `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` on the same row."

    Design: Corner/rbac/claims_triangle_role_asymmetry_adjuster_cannot_dispute
    """
    world = _claim_under_review()
    claim_id = world["claim"]["id"]

    disputed = validate_success(
        api_client.dispute_damage_claim(
            claim_id,
            dispute_damage_claim_payload(
                reason_code="WRONG_PARTY",
                plant_evidence_points=1,
                hauler_evidence_points=3,
                installer_evidence_points=0,
            ),
            make_plant_dispatcher_headers(world["plant"]["id"]),
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED", (
        f"the pushback moves UNDER_REVIEW -> DISPUTED, got {disputed['status']}"
    )
    assert disputed["dispute_round"] == 1, (
        f"dispute_round is incremented by 1, got {disputed['dispute_round']}"
    )

    reopened = validate_success(
        api_client.review_damage_claim(
            claim_id, review_damage_claim_payload(), make_claims_adjuster_headers()
        ),
        200,
    )
    assert reopened["status"] == "UNDER_REVIEW", (
        f"the adjuster's review reopens the claim, got {reopened['status']}"
    )

    settled = validate_success(
        api_client.adjudicate_damage_claim(
            claim_id,
            adjudicate_damage_claim_payload("EVIDENCE"),
            make_claims_adjuster_headers(),
        ),
        200,
    )
    assert settled["approved_amount_cents"] == 90000, (
        f"ninety percent of 100000 cents is 90000, got {settled['approved_amount_cents']}"
    )
    assert settled["plant_charge_cents"] == 22500, (
        f"one point of four earns 22500, got {settled['plant_charge_cents']}"
    )
    assert settled["hauler_charge_cents"] == 67500, (
        f"three points of four earn 67500, got {settled['hauler_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        f"zero points earn nothing, got {settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)

    plant = read_plant(world["plant"]["id"])
    crew = read_set_crew(world["set_crew"]["id"])
    assert plant["chargeback_balance_cents"] == 22500, (
        f"the plant's balance is its share, got {plant['chargeback_balance_cents']}"
    )
    assert plant["status"] == "ACTIVE", (
        f"22500 cents is far below the probation line, got {plant['status']}"
    )
    assert crew["chargeback_balance_cents"] == 0, (
        f"the installer was charged nothing, got {crew['chargeback_balance_cents']}"
    )


def test_the_adjuster_is_the_one_role_barred_from_disputing_a_claim():
    """PRD §2.1: "It reviews, adjudicates and reverses claims between plant, hauler
    and installer. It may not dispute a claim — only the named parties can."
    PRD §3.9 restates the asymmetry: "An adjuster may not dispute a claim, and a
    party may not review one."

    Design: Corner/rbac/claims_triangle_role_asymmetry_adjuster_cannot_dispute
    """
    world = _claim_under_review()
    claim_id = world["claim"]["id"]

    validate_error(
        api_client.dispute_damage_claim(
            claim_id, dispute_damage_claim_payload(), make_claims_adjuster_headers()
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    for role in ("NetworkAdmin", "PermitDesk", "InstallationInspector"):
        validate_error(
            api_client.dispute_damage_claim(
                claim_id,
                dispute_damage_claim_payload(),
                headers_for_role(role, PROBE_USER_ID),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    still_under_review = read_damage_claim(claim_id)
    assert still_under_review["status"] == "UNDER_REVIEW", (
        f"the refused pushbacks leave the claim UNDER_REVIEW, got {still_under_review['status']}"
    )
    assert still_under_review["dispute_round"] == 0, (
        f"no refused pushback may count, got {still_under_review['dispute_round']}"
    )


def test_a_named_party_may_not_review_adjudicate_or_reverse_the_claim():
    """PRD §3.9: "An adjuster may not dispute a claim, and a party may not review
    one." The same section reserves settlement for the adjuster: "From
    `UNDER_REVIEW` a `ClaimsAdjuster` settles the claim by supplying an
    `allocation_basis` of either `STAGE` or `EVIDENCE`, moving it `UNDER_REVIEW →
    ADJUDICATED`."

    Design: Corner/rbac/claims_triangle_role_asymmetry_adjuster_cannot_dispute
    """
    world = _claim_under_review()
    claim_id = world["claim"]["id"]
    party_headers = (
        make_plant_dispatcher_headers(world["plant"]["id"]),
        make_transport_manager_headers(world["hauler"]["id"]),
        make_set_crew_lead_headers(world["set_crew"]["id"]),
    )

    for headers in party_headers:
        validate_error(
            api_client.review_damage_claim(claim_id, review_damage_claim_payload(), headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.adjudicate_damage_claim(
                claim_id, adjudicate_damage_claim_payload("STAGE"), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.reverse_damage_claim(
                claim_id, reverse_damage_claim_payload(), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    untouched = read_damage_claim(claim_id)
    assert untouched["status"] == "UNDER_REVIEW", (
        f"none of the refused party actions may move the claim, got {untouched['status']}"
    )
    assert untouched["approved_amount_cents"] is None, (
        f"no approved amount may be posted, got {untouched['approved_amount_cents']}"
    )

    settled = validate_success(
        api_client.adjudicate_damage_claim(
            claim_id,
            adjudicate_damage_claim_payload("STAGE"),
            make_claims_adjuster_headers(),
        ),
        200,
    )
    assert settled["status"] == "ADJUDICATED", (
        f"the adjuster moves UNDER_REVIEW -> ADJUDICATED, got {settled['status']}"
    )
    assert settled["plant_charge_cents"] == 90000, (
        "damage found at PLANT_QC belongs to the plant, expected 90000, "
        f"got {settled['plant_charge_cents']}"
    )


def test_opening_a_claim_is_closed_to_the_inspector_the_desk_and_the_administrator():
    """PRD §3.9: "A damage claim names four parties at once, and any of
    `PlantDispatcher`, `TransportManager`, `SetCrewLead` or `ClaimsAdjuster` may
    open one." PRD §2.10: "**Priority 2** — `X-User-Role` is one of the calling
    endpoint's authorised roles, on every endpoint. Violation:
    `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/claims_triangle_role_asymmetry_adjuster_cannot_dispute
    """
    world = _claim_under_review()
    payload_refs = (
        world["order"]["id"],
        world["section"]["id"],
        world["hauler"]["id"],
        world["set_crew"]["id"],
    )

    for role in ("InstallationInspector", "PermitDesk", "NetworkAdmin"):
        validate_error(
            api_client.create_damage_claim(
                create_damage_claim_payload(
                    *payload_refs,
                    discovered_stage="PLANT_QC",
                    claimed_amount_cents=100000,
                ),
                headers_for_role(role, PROBE_USER_ID),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    rows, _meta = validate_paginated(
        api_client.list_damage_claims(
            make_claims_adjuster_headers(), params={"order_id": world["order"]["id"]}
        )
    )
    assert len(rows) == 1, (
        f"only the adjuster's own claim may exist, got {len(rows)} rows"
    )
