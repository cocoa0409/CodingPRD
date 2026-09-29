"""Who may call what, and in which order the two identity gates fire.

Authentication before everything else, endpoint authorization before request
shape and before existence, per-row builder ownership, the submit/review
separation, and the reads that every role shares.
"""

from test_helpers import (
    ADMIN,
    CLOCK_STARTUP_UTC,
    ENGINEER,
    ENGINEERING_MANAGER_USER_ID,
    ENGINEER_TWO_USER_ID,
    ENGINEER_USER_ID,
    LOGISTICS,
    MANAGER,
    NON_EXISTENT_UUID,
    PLANNER,
    SALES,
    SEALER,
    accept_quote,
    accept_quote_payload,
    append_components,
    assert_error_envelope,
    assert_pagination_meta,
    chain_authorized_builder,
    chain_locked_configuration,
    connection_component_payload,
    create_authorized_builder,
    create_configuration_payload,
    create_design,
    create_drawing_package_payload,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_production_line_payload,
    create_quote,
    create_quote_payload,
    get_builder,
    get_design,
    get_jurisdiction,
    get_quote,
    issue_quote,
    make_builder_headers,
    make_engineer_headers,
    make_engineering_manager_headers,
    member_component_payload,
    review_design,
    set_clock,
    set_clock_payload,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A platform administrator's identity that declares no capacity at all.
HEADERS_WITHOUT_ROLE = {
    "X-User-ID": "u_admin_1",
    "Content-Type": "application/json",
}

#: A declared capacity carried by nobody.
HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": "PlatformAdmin",
    "Content-Type": "application/json",
}

#: A plausible job title that is not one of the eight recognised roles.
HEADERS_WITH_UNKNOWN_ROLE = {
    "X-User-ID": "u_admin_1",
    "X-User-Role": "PlantForeman",
    "Content-Type": "application/json",
}


def _submitted_design():
    """A SUBMITTED design whose author is the detailing engineer ``u_eng_1``."""
    chain = chain_locked_configuration()
    design = create_design(
        chain["configuration"]["id"], chain["configuration"]["version"]
    )
    append_components(design["id"], [
        member_component_payload(),
        connection_component_payload(
            mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
        ),
        connection_component_payload(
            mark="B-1", connection_type="BASE", capacity_moment_kip_ft=900,
            erection_stage="ANCHORAGE",
        ),
    ])
    chain["design"] = submit_design(design["id"], user_id=ENGINEER_USER_ID)
    return chain


def test_01_both_identity_headers_are_mandatory_and_checked_first(api):
    """A missing or unrecognised role is refused before the id is even resolved.

    PRD §2.1: "Every request to every endpoint must carry two headers:
    ``X-User-ID``, identifying the acting user, and ``X-User-Role``, declaring the
    capacity in which that user is acting."

    PRD §2.1: "If either header is absent, or if ``X-User-Role`` is not one of the
    eight roles below, the request is rejected with ``ERR_UNAUTHENTICATED``."

    PRD §2.5: "Authentication comes first — headers present and role recognised,
    otherwise ``ERR_UNAUTHENTICATED``."

    PRD §2.5: "Fourth comes existence: path identifiers are resolved left to right,
    and only then body foreign keys, in the order the fields appear in the
    endpoint's input list; each missing resource has its own code, listed in §2.6."

    Design: Corner/rbac/requests_without_valid_role_headers_are_rejected_before_every_other_check
    """
    set_clock()
    jurisdiction = create_jurisdiction()

    roleless = api.get_jurisdiction(jurisdiction["id"], HEADERS_WITHOUT_ROLE)
    anonymous = api.get_jurisdiction(jurisdiction["id"], HEADERS_WITHOUT_USER_ID)
    unknown_role = api.get_jurisdiction(jurisdiction["id"], HEADERS_WITH_UNKNOWN_ROLE)
    roleless_on_a_ghost = api.get_jurisdiction(NON_EXISTENT_UUID, HEADERS_WITHOUT_ROLE)

    validate_error(roleless, "ERR_UNAUTHENTICATED", expected_status=401)
    # Both headers are mandatory, so the missing id fails the same way.
    validate_error(anonymous, "ERR_UNAUTHENTICATED", expected_status=401)
    assert_error_envelope(anonymous.json(), "ERR_UNAUTHENTICATED")
    # PlantForeman is outside the eight declared roles, so it fails authentication
    # rather than endpoint authorization.
    unrecognised = validate_error(
        unknown_role, "ERR_UNAUTHENTICATED", expected_status=401
    )
    assert unrecognised["error_id"] != "ERR_FORBIDDEN_ROLE"
    # Authentication precedes existence, so the unresolvable id is never reported.
    on_a_ghost = validate_error(
        roleless_on_a_ghost, "ERR_UNAUTHENTICATED", expected_status=401
    )
    assert on_a_ghost["error_id"] != "ERR_JURISDICTION_NOT_FOUND"

    reachable = validate_success(
        api.get_jurisdiction(jurisdiction["id"], ADMIN), expected_status=200
    )

    assert reachable["code"] == "TX-HARRIS"


def test_02_the_network_operations_are_the_platform_admins_alone(api):
    """Four operational roles are turned away before their bodies are inspected.

    PRD §2.1: "A ``PlatformAdmin`` runs network operations: registering
    jurisdictions and publishing their loading criteria, adding builders to the
    network and authorizing or suspending them, registering production lines, and
    driving the logical clock."

    PRD §2.5: "Endpoint authorization comes second — the acting role listed for the
    endpoint, otherwise ``ERR_FORBIDDEN_ROLE``."

    PRD §2.5: "Request-shape validation comes third: every required input present,
    every value of the right type, every enum member recognised, every numeric
    range honoured, ``component_marks`` a non-empty array of strings, and the
    component-class field consistency described in §3.6 — any failure here is
    ``ERR_INVALID_REQUEST``."

    PRD §2.4: "At server startup the logical clock reads exactly
    ``2026-08-01T00:00:00Z``, and it never falls back to real time."

    Design: Corner/rbac/operational_roles_cannot_reach_platform_admin_endpoints
    """
    line_body = create_production_line_payload(
        code="PL-9", name="Panel Line 9", line_type="PANEL_ROLL"
    )

    coordinator_line = api.create_production_line(line_body, LOGISTICS)
    coordinator_bad_line = api.create_production_line(
        create_production_line_payload(
            code="PL-9", name="Panel Line 9", line_type="LASER_TABLE"
        ),
        LOGISTICS,
    )
    planner_jurisdiction = api.create_jurisdiction(
        create_jurisdiction_payload(), PLANNER
    )
    engineer_clock = api.set_clock(set_clock_payload("2026-08-05T00:00:00Z"), ENGINEER)

    for refused in (
        coordinator_line,
        coordinator_bad_line,
        planner_jurisdiction,
        engineer_clock,
    ):
        validate_error(refused, "ERR_FORBIDDEN_ROLE", expected_status=403)
    # LASER_TABLE is not a line type, but the role gate fired before the shape
    # check could report it.
    assert coordinator_bad_line.json()["data"]["error_id"] != "ERR_INVALID_REQUEST"
    _, jurisdiction_meta = validate_paginated(api.list_jurisdictions(ADMIN))
    assert jurisdiction_meta["total_count"] == 0

    line = validate_success(
        api.create_production_line(line_body, ADMIN), expected_status=201
    )
    jurisdiction = validate_success(
        api.create_jurisdiction(create_jurisdiction_payload(), ADMIN),
        expected_status=201,
    )

    # PL-9 was never taken by the rejected attempt.
    assert line["code"] == "PL-9"
    assert line["line_type"] == "PANEL_ROLL"
    assert jurisdiction["code"] == "TX-HARRIS"
    # The engineer's clock request moved nothing, so both rows are stamped with
    # the startup default.
    assert line["created_at"] == CLOCK_STARTUP_UTC
    assert jurisdiction["created_at"] == CLOCK_STARTUP_UTC


def test_03_the_selling_role_and_the_sealing_role_cannot_swap_places(api):
    """Each exclusive write is refused for its peer before any id is resolved.

    PRD §2.1: "A ``SalesEngineer`` drafts and locks building configurations,
    attaches accessory kits, and prices and issues quotes."

    PRD §2.1: "A ``SealingEngineer`` opens and seals permit drawing sets."

    PRD §2.5: "Endpoint authorization comes second — the acting role listed for the
    endpoint, otherwise ``ERR_FORBIDDEN_ROLE``."

    PRD §2.1: "Every read endpoint is available to all eight roles."

    Design: Corner/rbac/sales_engineer_cannot_seal_and_sealing_engineer_cannot_quote
    """
    set_clock()
    jurisdiction = create_jurisdiction()

    sales_package = api.create_drawing_package(
        create_drawing_package_payload(NON_EXISTENT_UUID, jurisdiction["id"]), SALES
    )
    sealer_quote = api.create_quote(
        create_quote_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), SEALER
    )
    sealer_configuration = api.create_configuration(
        create_configuration_payload(NON_EXISTENT_UUID, jurisdiction["id"]), SEALER
    )

    # The design id in the body is unresolvable, but the role gate reports first.
    refused_package = validate_error(
        sales_package, "ERR_FORBIDDEN_ROLE", expected_status=403
    )
    assert refused_package["error_id"] != "ERR_DESIGN_NOT_FOUND"
    refused_quote = validate_error(
        sealer_quote, "ERR_FORBIDDEN_ROLE", expected_status=403
    )
    assert refused_quote["error_id"] != "ERR_BUILDER_NOT_FOUND"
    # Configuring buildings is the sales engineer's exclusive write.
    validate_error(sealer_configuration, "ERR_FORBIDDEN_ROLE", expected_status=403)

    # The shared read answers both roles with the same row.
    assert get_jurisdiction(jurisdiction["id"], headers=SALES) == get_jurisdiction(
        jurisdiction["id"], headers=SEALER
    )
    packages, package_meta = validate_paginated(
        api.list_drawing_packages(SALES, params={"limit": 5})
    )
    assert packages == []
    assert package_meta["total_count"] == 0
    _, quote_meta = validate_paginated(api.list_quotes(SEALER))
    assert quote_meta["total_count"] == 0
    _, configuration_meta = validate_paginated(api.list_configurations(SEALER))
    assert configuration_meta["total_count"] == 0


def test_04_a_quote_may_only_be_accepted_by_the_builder_it_names(api):
    """Ownership is per row, so a peer in the same territory is still refused.

    PRD §2.1: "Concretely, a ``Builder`` may only accept a quote whose
    ``builder_id`` equals its own ``X-User-ID``; an attempt to accept another
    builder's quote is rejected with ``ERR_NOT_RESOURCE_OWNER``."

    PRD §2.1: "A ``Builder`` accepts issued quotes."

    PRD §2.5: "Fifth comes builder ownership, ``ERR_NOT_RESOURCE_OWNER``."

    Design: Corner/rbac/builder_cannot_accept_a_quote_issued_to_another_builder
    """
    chain = chain_locked_configuration()
    first_builder = chain["builder"]
    second_builder = create_authorized_builder(
        chain["jurisdiction"]["id"], name="Bayou Erectors"
    )
    quote = create_quote(first_builder["id"], chain["configuration"]["id"])
    issue_quote(quote["id"])

    stranger = api.accept_quote(
        quote["id"],
        accept_quote_payload(job_site_code="SITE-B2", site_delivery_capacity=None),
        make_builder_headers(second_builder["id"]),
    )
    seller = api.accept_quote(
        quote["id"],
        accept_quote_payload(job_site_code="SITE-SE", site_delivery_capacity=None),
        SALES,
    )

    # The stranger is AUTHORIZED in the same territory and still not the owner.
    validate_error(stranger, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    assert_error_envelope(stranger.json(), "ERR_NOT_RESOURCE_OWNER")
    # Accepting is the builder's own operation, so the sales engineer never
    # reaches the ownership comparison at all.
    validate_error(seller, "ERR_FORBIDDEN_ROLE", expected_status=403)
    assert get_quote(quote["id"])["status"] == "ISSUED"
    assert get_builder(second_builder["id"])["credit_used_cents"] == 0

    order = accept_quote(quote["id"], first_builder["id"], site_delivery_capacity=None)

    assert order["builder_id"] == first_builder["id"]
    assert order["job_site_code"] == "SITE-A"
    assert get_quote(quote["id"])["status"] == "ACCEPTED"


def test_05_the_engineer_who_submitted_a_design_may_never_review_it(api):
    """The prohibition follows the user, not the decision, and role is separate.

    PRD §2.1: "One further identity rule cuts across the engineering roles: the
    user who submits a design may never be the user who reviews it."

    PRD §2.1: "Because both are recorded as raw ``X-User-ID`` values, this is
    enforced by comparing the reviewing ``X-User-ID`` against the design's stored
    ``submitted_by_user_id``, and a match is rejected with
    ``ERR_SEGREGATION_OF_DUTIES``."

    PRD §2.1: "An ``EngineeringManager`` reviews submitted designs and does nothing
    else."

    PRD §3.6: "Both branches set ``reviewed_by_user_id`` to the reviewing
    ``X-User-ID`` and increment the design's ``version``, but their downstream
    effects diverge and each branch is spelled out in full."

    Design: Corner/rbac/the_submitting_engineer_must_not_review_their_own_design
    """
    chain = _submitted_design()
    design_id = chain["design"]["id"]
    assert chain["design"]["submitted_by_user_id"] == ENGINEER_USER_ID

    self_approval = api.review_design(
        design_id,
        {"decision": "APPROVE"},
        make_engineering_manager_headers(ENGINEER_USER_ID),
    )
    self_rejection = api.review_design(
        design_id,
        {"decision": "REQUEST_REVISION"},
        make_engineering_manager_headers(ENGINEER_USER_ID),
    )
    peer_engineer = api.review_design(
        design_id,
        {"decision": "APPROVE"},
        make_engineer_headers(ENGINEER_TWO_USER_ID),
    )

    validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    # The prohibition is on the user, so the other decision is refused alike.
    validate_error(self_rejection, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    # Role and same-user are two independent gates.
    validate_error(peer_engineer, "ERR_FORBIDDEN_ROLE", expected_status=403)
    still_submitted = get_design(design_id)
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["reviewed_by_user_id"] is None
    assert still_submitted["version"] == chain["design"]["version"]

    reviewed = review_design(design_id, "APPROVE", ENGINEERING_MANAGER_USER_ID)

    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by_user_id"] == ENGINEERING_MANAGER_USER_ID
    assert reviewed["version"] == chain["design"]["version"] + 1


def test_06_the_platform_admin_cannot_stand_in_for_the_other_seven_roles(api):
    """Eight writes belonging to seven peers are all refused for the admin.

    PRD §2.1: "The eight recognised roles are ``PlatformAdmin``,
    ``SalesEngineer``, ``Engineer``, ``EngineeringManager``, ``SealingEngineer``,
    ``ProductionPlanner``, ``LogisticsCoordinator``, and ``Builder``."

    PRD §2.1: "If both headers are well formed but the declared role is not among
    the roles authorized for the endpoint being called, the request is rejected
    with ``ERR_FORBIDDEN_ROLE``."

    PRD §2.5: "Endpoint authorization comes second — the acting role listed for the
    endpoint, otherwise ``ERR_FORBIDDEN_ROLE``."

    Design: Corner/rbac/platform_admin_cannot_stand_in_for_the_other_seven_roles
    """
    borrowed = [
        api.lock_configuration(NON_EXISTENT_UUID, ADMIN),
        api.issue_quote(NON_EXISTENT_UUID, ADMIN),
        api.accept_quote(
            NON_EXISTENT_UUID,
            accept_quote_payload(job_site_code="SITE-X", site_delivery_capacity=None),
            ADMIN,
        ),
        api.submit_design(NON_EXISTENT_UUID, ADMIN),
        api.review_design(NON_EXISTENT_UUID, {"decision": "APPROVE"}, ADMIN),
        api.seal_drawing_package(NON_EXISTENT_UUID, ADMIN),
        api.complete_production_lot(NON_EXISTENT_UUID, ADMIN),
        api.dispatch_shipment_load(NON_EXISTENT_UUID, ADMIN),
    ]

    reported = []
    for refused in borrowed:
        error = validate_error(refused, "ERR_FORBIDDEN_ROLE", expected_status=403)
        assert_error_envelope(refused.json(), "ERR_FORBIDDEN_ROLE")
        reported.append(error["error_id"])

    assert len(reported) == 8
    # Every id above is unresolvable, and not one of the ten not-found codes is
    # reported, because the role gate short-circuits ahead of existence.
    assert set(reported) == {"ERR_FORBIDDEN_ROLE"}
    # Accepting is the builder's write, so the admin is refused on the role and
    # never on the ownership comparison that follows it.
    assert "ERR_NOT_RESOURCE_OWNER" not in reported


def test_07_every_read_endpoint_answers_all_eight_roles_alike(api):
    """The same row comes back for each role, and no read moves anything.

    PRD §2.1: "Every read endpoint is available to all eight roles."

    PRD §2.1: "Read endpoints impose no such ownership restriction — a ``Builder``
    may read any resource."

    PRD §4: "In the Authorized Role(s) column, "Any" means all eight roles listed
    in §2.1 may call the endpoint."

    PRD §2.3: "The ``meta`` object of a collection response carries ``limit``,
    ``offset``, ``total_count`` (the number of rows matching the filters before
    pagination is applied) and ``has_more`` (true when rows remain beyond the
    current window)."

    Design: Corner/rbac/all_eight_roles_share_every_read_endpoint
    """
    chain = chain_authorized_builder()
    jurisdiction_id = chain["jurisdiction"]["id"]
    builder = chain["builder"]
    builder_headers = make_builder_headers(builder["id"])

    readings = [
        get_jurisdiction(jurisdiction_id, headers=headers)
        for headers in (
            ADMIN, SALES, ENGINEER, MANAGER, SEALER, PLANNER, LOGISTICS,
            builder_headers,
        )
    ]

    assert len(readings) == 8
    for reading in readings:
        # Reads are not scoped by role, so every payload is the same row.
        assert reading == readings[0]
        assert reading["code"] == "TX-HARRIS"

    builders, builder_meta = validate_paginated(
        api.list_builders(
            LOGISTICS, params={"jurisdiction_id": jurisdiction_id, "limit": 5}
        )
    )
    orders, order_meta = validate_paginated(
        api.list_orders(builder_headers, params={"limit": 5})
    )

    assert_pagination_meta(
        builder_meta, limit=5, offset=0, total_count=1, has_more=False
    )
    assert builders[0]["id"] == builder["id"]
    assert orders == []
    assert_pagination_meta(order_meta, limit=5, offset=0, total_count=0, has_more=False)
    # Ten reads later, the builder row is exactly as authorization left it.
    assert get_builder(builder["id"])["version"] == builder["version"]
