"""Headers, identity scope, role authorisation and the sign-off separation."""
from test_helpers import (
    assert_instant,
    COMPLIANCE_OFFICER_ALT_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    NON_EXISTENT_UUID,
    ORDER_PLANNER_USER_ID,
    PRODUCT_ENGINEER_USER_ID,
    arrive_on_site,
    equipment_model_payload,
    facility_payload,
    firmware_certification_payload,
    firmware_release_payload,
    make_compliance_officer_headers,
    make_facility_manager_headers,
    make_headers,
    make_service_partner_tech_headers,
    new_facility,
    new_firmware_release,
    new_order,
    new_pm_program,
    new_service_partner,
    order_payload,
    parts_receipt_payload,
    pm_program_payload,
    read_facility,
    read_firmware_certification,
    read_firmware_release,
    read_install_job,
    read_order,
    read_serialized_asset,
    read_service_partner,
    reject_certification_payload,
    release_revision,
    scrap_payload,
    settle_payload,
    setup_installed_order,
    setup_qualified_revision,
    setup_released_revision,
    setup_scheduled_install,
    submit_firmware_certification,
    rig_payload,
    usage_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_release_payload,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def test_a_facility_manager_may_act_only_within_its_own_facility(
    api, order_planner_headers
):
    """The same create is refused for a stranger's facility and accepted for its own.

    The PRD states that when the role is `FacilityManager`, "`X-User-ID` is the `id`
    of the acting `Facility`. Ownership checks on any resource that references a
    `Facility` compare the resource's facility foreign-key field to `X-User-ID`" and
    that "A mismatch is refused with `ERR_FACILITY_SCOPE_VIOLATION` (403)."

    Design: Corner/validations/facility_manager_is_scoped_to_its_own_facility
    """
    home = new_facility(account_name="Grandstand Fitness", freight_zone="Z1")
    stranger = new_facility(account_name="Riverside Athletic Club", freight_zone="Z2")
    foreign_order = new_order(stranger["id"])
    manager = make_facility_manager_headers(home["id"])

    denied_create = api.create_order(order_payload(stranger["id"]), manager)
    denied_read = api.get_order(foreign_order["id"], manager)

    validate_error(denied_create, "ERR_FACILITY_SCOPE_VIOLATION", 403)
    validate_error(denied_read, "ERR_FACILITY_SCOPE_VIOLATION", 403)
    assert denied_read.status_code != 404, (
        "the order resolves, so the refusal is a scope refusal and not a miss"
    )

    own = validate_success(api.create_order(order_payload(home["id"]), manager), 201)

    assert own["facility_id"] == home["id"]
    assert own["config_status"] == "CONFIGURING"
    assert own["billing_status"] == "UNQUOTED"
    orders, meta = validate_paginated(
        api.list_orders(manager, params={"facility_id": home["id"]})
    )
    assert meta["total_count"] == 1
    assert orders[0]["id"] == own["id"]
    untouched = read_order(foreign_order["id"])
    assert untouched["facility_id"] == stranger["id"]
    assert untouched["config_status"] == "CONFIGURING"
    all_orders, all_meta = validate_paginated(api.list_orders(order_planner_headers))
    assert all_meta["total_count"] == 2
    assert sorted(order["facility_id"] for order in all_orders) == sorted(
        [home["id"], stranger["id"]]
    )


def test_a_service_partner_tech_may_act_only_for_its_own_partner(api):
    """A rival crew cannot report arrival on somebody else's install job.

    The PRD states that when the role is `ServicePartnerTech`, "`X-User-ID` is the
    `id` of the acting `ServicePartner`. Ownership checks on any resource that
    references a `ServicePartner` compare the resource's partner foreign-key field to
    `X-User-ID`: an install job's `service_partner_id`" and that "A mismatch is
    refused with `ERR_PARTNER_SCOPE_VIOLATION` (403)."

    Design: Corner/validations/service_partner_tech_is_scoped_to_its_own_partner
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1,
                                 partner_overrides={"name": "Meridian Service Co"})
    bystander = new_service_partner(name="Cascade Field Service",
                                    certified_categories=["CARDIO"])

    response = api.arrive_install_job(
        ctx["install_job"]["id"],
        make_service_partner_tech_headers(bystander["id"]),
    )

    validate_error(response, "ERR_PARTNER_SCOPE_VIOLATION", 403)
    held = read_install_job(ctx["install_job"]["id"])
    assert held["status"] == "SCHEDULED"
    assert held["service_partner_id"] == ctx["partner"]["id"]
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "STAGED"
    assert read_service_partner(bystander["id"])["committed_hours"] == 0.0

    job = arrive_on_site(ctx["install_job"]["id"], ctx["partner"]["id"])

    assert job["status"] == "ON_SITE"
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "INSTALLING"
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 3.0
    assert read_serialized_asset(ctx["asset"]["id"])["status"] == "BUILT"


def test_authentication_outranks_the_role_path_and_schema_checks(
    api, order_planner_headers
):
    """A bad header pair answers 401 even when the path and the body are bad too.

    The PRD states that "If either header is missing, empty, or if `X-User-Role`
    names something the system does not recognise, the request fails with
    `ERR_UNAUTHENTICATED` (401)", and it ranks that check first: "Both context
    headers present and non-empty, with `X-User-Role` naming a known role —
    otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/errors/authentication_is_checked_before_role_path_and_schema
    """
    facility = new_facility(account_name="Grandstand Fitness", freight_zone="Z1")
    order = new_order(facility["id"])
    role_missing = {"X-User-ID": ORDER_PLANNER_USER_ID}
    role_empty = {"X-User-ID": ORDER_PLANNER_USER_ID, "X-User-Role": ""}
    unknown_role = make_headers(ORDER_PLANNER_USER_ID, "Auditor")

    validate_error(api.get_order(NON_EXISTENT_UUID, role_missing),
                   "ERR_UNAUTHENTICATED", 401)
    validate_error(api.get_order(order["id"], role_empty),
                   "ERR_UNAUTHENTICATED", 401)
    validate_error(api.get_order(order["id"], unknown_role),
                   "ERR_UNAUTHENTICATED", 401)
    schema_and_path_also_bad = api.quote_order(NON_EXISTENT_UUID, {}, unknown_role)
    validate_error(schema_and_path_also_bad, "ERR_UNAUTHENTICATED", 401)
    assert schema_and_path_also_bad.status_code not in (400, 403, 404)

    missing = api.get_order(NON_EXISTENT_UUID, order_planner_headers)

    validate_error(missing, "ERR_ORDER_NOT_FOUND", 404)
    live = validate_success(api.get_order(order["id"], order_planner_headers))
    assert live["config_status"] == "CONFIGURING"
    assert live["version"] == order["version"], "no refused request touched the order"
    assert live["billing_status"] == "UNQUOTED"


def test_each_role_performs_the_operations_reserved_to_it(
    api, product_engineer_headers, compliance_officer_headers,
    service_ops_admin_headers, order_planner_headers
):
    """One estate, six actors, six operations that only that actor may perform.

    The PRD states that a `ProductEngineer` "owns product development: models,
    engineering revisions, durability testing, firmware builds and firmware
    loading", that a `ComplianceOfficer` "is the gatekeeper: it releases qualified
    revisions, certifies and rejects firmware/console pairings, announces sunsets,
    withdraws builds and declares obsolescence", that an `OrderPlanner` "owns
    commercial configuration and money", that a `ServiceOpsAdmin` "runs the service
    network", that a `FacilityManager` "may configure, line up and confirm its own
    orders", and that a `ServicePartnerTech` "owns on-site execution, usage
    reporting and preventive-maintenance delivery for its own partner only."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operations
    """
    ctx = setup_installed_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Grandstand Fitness", "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"})

    build = validate_success(
        api.create_firmware_release(firmware_release_payload(), product_engineer_headers),
        201,
    )
    assert build["status"] == "ACTIVE"
    assert build["certified_revision_count"] == 0

    withdrawn = validate_success(
        api.withdraw_firmware_release(build["id"], withdraw_release_payload(),
                                      compliance_officer_headers)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant(withdrawn["withdrawn_at"], CLOCK_START, "withdrawn_at")

    program = new_pm_program(ctx["facility"]["id"], ctx["partner"]["id"],
                             tier="PRO", visit_interval_days=90)
    activated = validate_success(
        api.activate_pm_program(program["id"], service_ops_admin_headers)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["covered_asset_count"] == 1
    assert activated["annual_labor_hours_committed"] == 6.25

    reported = validate_success(
        api.report_asset_usage(
            ctx["asset"]["id"], usage_report_payload(annual_usage_hours=1800.0),
            make_service_partner_tech_headers(ctx["partner"]["id"]))
    )
    assert reported["annual_usage_hours"] == 1800
    assert reported["status"] == "IN_SERVICE"

    settled = validate_success(
        api.settle_order(ctx["order"]["id"], settle_payload(), order_planner_headers)
    )
    assert settled["billing_status"] == "SETTLED"
    assert read_facility(ctx["facility"]["id"])["open_order_exposure_cents"] == 0

    follow_on = validate_success(
        api.create_order(order_payload(ctx["facility"]["id"]),
                         make_facility_manager_headers(ctx["facility"]["id"])),
        201,
    )
    assert follow_on["facility_id"] == ctx["facility"]["id"]
    assert follow_on["config_status"] == "CONFIGURING"


def test_no_role_may_perform_an_operation_reserved_to_another(
    api, product_engineer_headers, compliance_officer_headers,
    service_ops_admin_headers, order_planner_headers, facility_manager_headers,
    service_partner_tech_headers
):
    """Eight wrong-role calls are all refused before anything else is examined.

    The PRD states that "Each endpoint is authorised for a specific subset of these
    roles, listed in §4; a caller whose role is not on an endpoint's list is refused
    with `ERR_ROLE_NOT_PERMITTED` (403)", and it ranks that check second: "The
    caller's role appears on the endpoint's authorised list — otherwise
    `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation
    """
    validate_error(
        api.release_revision(NON_EXISTENT_UUID, product_engineer_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    validate_error(
        api.certify_firmware_certification(NON_EXISTENT_UUID, product_engineer_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    validate_error(
        api.create_equipment_model(equipment_model_payload("T900"),
                                   compliance_officer_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    empty_body = api.quote_order(NON_EXISTENT_UUID, {}, facility_manager_headers)
    validate_error(empty_body, "ERR_ROLE_NOT_PERMITTED", 403)
    assert empty_body.status_code != 400, (
        "the role check is reached before the body is validated"
    )
    validate_error(
        api.arrive_install_job(NON_EXISTENT_UUID, order_planner_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    validate_error(
        api.scrap_asset(NON_EXISTENT_UUID, scrap_payload(),
                        service_partner_tech_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    validate_error(
        api.post_parts_receipt(NON_EXISTENT_UUID, parts_receipt_payload(5),
                               product_engineer_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )
    validate_error(
        api.settle_order(NON_EXISTENT_UUID, settle_payload(),
                         service_ops_admin_headers),
        "ERR_ROLE_NOT_PERMITTED", 403,
    )

    _, meta = validate_paginated(api.list_equipment_models(product_engineer_headers))
    assert meta["total_count"] == 0, "not one refused call created anything"


def test_shared_operations_accept_either_of_their_authorised_roles(
    api, product_engineer_headers, compliance_officer_headers, service_ops_admin_headers
):
    """Rigs, facilities, programmes and certifications each admit two roles.

    The PRD states that a firmware certification's submitter identity "is stamped
    into `submitted_by_user_id` on a firmware certification when a
    `ProductEngineer` submits one" and that a `ComplianceOfficer` identity "is
    recorded as `certified_by_user_id` when the officer certifies a firmware
    pairing, and as `submitted_by_user_id` if the officer is the one who submitted
    the certification".

    Design: Corner/rbac/shared_operations_accept_either_of_their_declared_roles
    """
    connected = setup_released_revision("C700")
    assert connected["certification"]["cert_status"] == "CERTIFIED"
    assert connected["certification"]["submitted_by_user_id"] == PRODUCT_ENGINEER_USER_ID

    engineer_rig = validate_success(
        api.create_test_rig(rig_payload(name="RIG-B"), product_engineer_headers),
        201,
    )
    admin_rig = validate_success(
        api.create_test_rig(rig_payload(name="RIG-C"), service_ops_admin_headers),
        201,
    )
    assert engineer_rig["name"] == "RIG-B"
    assert admin_rig["name"] == "RIG-C"
    assert admin_rig["occupied_station_count"] == 0

    facility = validate_success(
        api.create_facility(facility_payload(account_name="Grandstand Fitness",
                                             freight_zone="Z1"),
                            service_ops_admin_headers),
        201,
    )
    assert facility["status"] == "ACTIVE"
    partner = new_service_partner(name="Meridian Service Co",
                                  certified_categories=["CONNECTED"])

    admin_program = validate_success(
        api.create_pm_program(pm_program_payload(facility["id"], partner["id"]),
                              service_ops_admin_headers),
        201,
    )
    manager_program = validate_success(
        api.create_pm_program(
            pm_program_payload(facility["id"], partner["id"], tier="BASIC",
                               visit_interval_days=120),
            make_facility_manager_headers(facility["id"])),
        201,
    )
    assert admin_program["status"] == "DRAFT"
    assert manager_program["status"] == "DRAFT"
    assert manager_program["tier"] == "BASIC"
    _, meta = validate_paginated(
        api.list_pm_programs(service_ops_admin_headers,
                             params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 2

    second_build = new_firmware_release(version_string="FW-2.2.0",
                                        console_platform="CONSOLE_T2")
    officer_submitted = validate_success(
        api.create_firmware_certification(
            firmware_certification_payload(second_build["id"],
                                           connected["revision"]["id"],
                                           test_report_ref="CONN-RPT-0002"),
            compliance_officer_headers),
        201,
    )
    assert officer_submitted["cert_status"] == "SUBMITTED"
    assert officer_submitted["submitted_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert officer_submitted["certified_by_user_id"] is None
    assert read_firmware_release(second_build["id"])["certified_revision_count"] == 0


def test_the_officer_who_submitted_a_certification_may_not_decide_it(
    api, compliance_officer_headers
):
    """Both decision paths close to the submitter and open to a second officer.

    The PRD states that "The `ComplianceOfficer` who certifies or rejects a
    certification must present an `X-User-ID` different from the
    `submitted_by_user_id` recorded when that certification was created; if they are
    the same string, the request is refused with `ERR_SEGREGATION_OF_DUTIES` (403)"
    and that success "writes `certified_by_user_id` from the acting `X-User-ID`,
    stamps `certified_at` from the logical clock, and raises the release's
    `certified_revision_count` by one."

    Design: Corner/rbac/the_submitter_of_a_certification_may_not_decide_it
    """
    qualified = setup_qualified_revision("C700")
    build = new_firmware_release(version_string="FW-2.1.0",
                                console_platform="CONSOLE_T2")
    certification = submit_firmware_certification(
        build["id"], qualified["revision"]["id"],
        submitter_user_id=COMPLIANCE_OFFICER_USER_ID,
        submitter_role="ComplianceOfficer")
    assert certification["submitted_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    validate_error(
        api.certify_firmware_certification(certification["id"],
                                           compliance_officer_headers),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )
    validate_error(
        api.reject_firmware_certification(certification["id"],
                                          reject_certification_payload(),
                                          compliance_officer_headers),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )

    held = read_firmware_certification(certification["id"])
    assert held["cert_status"] == "SUBMITTED"
    assert held["certified_by_user_id"] is None
    assert held["certified_at"] is None
    assert read_firmware_release(build["id"])["certified_revision_count"] == 0

    signed = validate_success(
        api.certify_firmware_certification(
            certification["id"],
            make_compliance_officer_headers(COMPLIANCE_OFFICER_ALT_USER_ID))
    )

    assert signed["cert_status"] == "CERTIFIED"
    assert signed["certified_by_user_id"] == COMPLIANCE_OFFICER_ALT_USER_ID
    assert_instant(signed["certified_at"], CLOCK_START, "certified_at")
    assert signed["submitted_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert read_firmware_release(build["id"])["certified_revision_count"] == 1
    assert release_revision(qualified["revision"]["id"])["status"] == "RELEASED"
