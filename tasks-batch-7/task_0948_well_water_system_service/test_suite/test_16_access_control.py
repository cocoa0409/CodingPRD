"""Role-based access control and the two entity-backed ownership scopes."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ALPHA,
    TEST_USERS,
    assert_instant_equals,
    assert_money,
    fixtures,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def test_the_estimator_prices_and_only_the_customer_approves(api):
    """PRD 2.1: "An `Estimator` may price and send a quote but may never approve it —
    approval belongs exclusively to a `CustomerContact` acting on its own account, and an
    `Estimator` attempting it is refused at the role gate with `ERR_UNAUTHORIZED`."
    PRD 2.6: "A request against a row in the wrong state with an unknown role gets
    `ERR_UNAUTHORIZED` (G2), because the role gate precedes the state gate."

    Design: Corner/rbac/corner_rbac_sod_estimator_prices_and_only_the_customer_approves
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Segregation Co",
        email="sg@corner.example",
        address_line="3 Segregation",
        technician_name="Segregation Tech",
    )
    part = fixtures.new_part("CTL-5000-G", "CONTROL", 5000, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T09:00:00Z", "JOURNEYMAN",
    )

    validate_error(
        api.approve_quote(staged["quote_id"], ESTIMATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.price_quote(staged["quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    approved = validate_success(
        api.approve_quote(staged["quote_id"], world["customer_headers"])
    )
    assert approved["status"] == "APPROVED"
    assert_money(
        approved["approved_total_cents"], 18080, "Quote.approved_total_cents"
    )
    assert_instant_equals(
        approved["approved_at"], "2026-06-01T09:00:00Z", "Quote.approved_at"
    )


def test_the_platform_admins_exclusive_operations_are_closed_to_other_roles(api):
    """PRD 2.1: "A `PlatformAdmin` is the operator with configuration authority: accounts,
    properties, wells, technicians, the parts catalog, maintenance plans, the logical
    clock and coverage voids."
    PRD 2.1: "If the headers are well-formed but the named role is not permitted on the
    addressed endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_platform_admin_exclusive_operations_denied_to_other_roles
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    technician = fixtures.new_technician("Admin Only Tech", "MASTER", "JUR_ALPHA")
    part = fixtures.new_part("CTL-ADMIN-1", "CONTROL", 5000, on_hand_qty=10)

    validate_error(
        api.create_account(
            {
                "legal_name": "Dispatcher Made This",
                "billing_jurisdiction_code": "JUR_ALPHA",
                "contact_email": "dm@corner.example",
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.create_technician(
            {
                "full_name": "Estimator Made This",
                "tier": "MASTER",
                "home_jurisdiction_code": "JUR_ALPHA",
                "status": "AVAILABLE",
            },
            ESTIMATOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.set_clock(
            {"to_iso8601": "2026-07-01T09:00:00Z"},
            fixtures.make_technician_headers(technician["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.patch_part_catalog_item(part["id"], {"unit_cost_cents": 99999}, BILLING),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    assert_instant_equals(
        validate_success(api.get_clock(ADMIN))["current_utc"],
        "2026-06-01T09:00:00Z",
        "clock.current_utc",
    )
    accounts, _ = validate_paginated(api.list_accounts(ADMIN))
    assert accounts == []
    technicians, _ = validate_paginated(api.list_technicians(ADMIN))
    assert len(technicians) == 1
    stored = fixtures.get_part(part["id"])
    assert_money(stored["unit_cost_cents"], 5000, "PartCatalogItem.unit_cost_cents")
    assert stored["version"] == 1


def test_the_three_work_order_operations_belong_to_three_different_roles(api):
    """PRD 4.14: "Roles: `Dispatcher`. Success: 200, the updated `WorkOrder` at `SCHEDULED`
    with `hold_reason` cleared."
    PRD 4.14: "Roles: `Technician`. Success: 200, the updated `WorkOrder` at
    `IN_PROGRESS`."
    PRD 4.14: "Roles: `BillingClerk`. Success: 200, the updated `WorkOrder` at
    `WRITTEN_OFF`."
    PRD 2.6: "A request against a row in the wrong state with an unknown role gets
    `ERR_UNAUTHORIZED` (G2), because the role gate precedes the state gate."

    Design: Corner/rbac/corner_rbac_work_order_operations_are_partitioned_across_three_roles
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Role Partition Co",
        email="rp@corner.example",
        address_line="3 Roles",
        technician_tier="MASTER",
        technician_name="Partition Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        20000,
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )

    validate_error(
        api.schedule_work_order(
            work_order["id"],
            {
                "scheduled_start_at": "2026-06-03T12:00:00Z",
                "scheduled_end_at": "2026-06-03T14:00:00Z",
            },
            world["technician_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.start_work_order(work_order["id"], ESTIMATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.write_off_work_order(work_order["id"], DISPATCHER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    stored = fixtures.get_work_order(work_order["id"])
    assert stored["fulfillment_status"] == "DRAFT"
    assert stored["billing_status"] == "NOT_BILLABLE"
    assert stored["scheduled_start_at"] is None
    assert stored["actual_start_at"] is None


def test_the_compliance_officers_lifecycle_operations_are_closed_to_creators(api):
    """PRD 2.1: "A `ComplianceOfficer` is the water-quality and permitting authority: it
    records laboratory and confirmatory results and drives the permit lifecycle."
    PRD 4.9: "Roles: `ComplianceOfficer`. Success: 200, the updated `WaterTest`."
    PRD 4.18: "Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `FILED`
    with `jurisdiction_tier`, `fee_cents` and `filed_at` set."

    Design: Corner/rbac/corner_rbac_compliance_officer_exclusive_lab_and_permit_operations_denied
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Officer Only Co",
        email="oo@corner.example",
        address_line="1 Officer",
        technician_name="Officer Tech",
    )
    water_test = fixtures.collect_sample(
        world["well_id"],
        world["technician_id"],
        "BACTERIOLOGICAL",
        "2026-06-01T00:00:00Z",
    )
    permit = validate_success(
        api.create_permit(
            {
                "well_profile_id": world["well_id"],
                "jurisdiction_code": "JUR_ALPHA",
                "scope": "PUMP_REPLACEMENT",
                "expedited": False,
                "post_hoc": False,
            },
            ESTIMATOR,
        ),
        201,
    )

    validate_error(
        api.record_lab_result(
            water_test["id"],
            {"analyzed_at": "2026-06-02T00:00:00Z", "coliform_present": False},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.file_permit(permit["id"], ESTIMATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.approve_permit(permit["id"], {}, DISPATCHER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    stored_test = fixtures.get_water_test(water_test["id"])
    assert stored_test["result_status"] == "COLLECTED"
    assert stored_test["analyzed_at"] is None
    stored_permit = fixtures.get_permit(permit["id"])
    assert stored_permit["status"] == "DRAFT"
    assert_money(stored_permit["fee_cents"], 0, "Permit.fee_cents")
    assert stored_permit["filed_at"] is None
    assert fixtures.get_well(world["well_id"])["potability_status"] == "UNKNOWN"


def test_a_customer_contact_reaches_only_its_own_accounts_quote(api):
    """PRD 2.1: "When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the
    acting `Account`; ownership checks on any resource that references an account compare
    the resource's owning account to `X-User-ID`, resolved through the declared foreign-key
    chain: an invoice through its `account_id`; a quote through its `property_id` to that
    property's `account_id`; an emergency ticket through its `account_id`; a work order
    through its `property_id` to that property's `account_id`; and a treatment
    recommendation through its `well_profile_id` to that well's `property_id` and on to
    that property's `account_id`."
    PRD 2.1: "An ownership failure by either entity-backed role — a `CustomerContact` whose
    `X-User-ID` is not the owning account, or a `Technician` whose `X-User-ID` is not the
    assigned technician — is answered with `ERR_ACTOR_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_customer_contact_scope_is_confined_to_its_own_account
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Owner Account Co",
        email="own@corner.example",
        address_line="1 Owner",
        technician_name="Owner Tech",
    )
    stranger = fixtures.new_account(
        "Stranger Account Co", "JUR_ALPHA", "str@corner.example"
    )
    stranger_headers = fixtures.make_customer_headers(stranger["id"])
    part = fixtures.new_part("CTL-5000-O", "CONTROL", 5000, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T09:00:00Z", "JOURNEYMAN",
    )

    validate_error(
        api.get_quote(staged["quote_id"], stranger_headers),
        ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.approve_quote(staged["quote_id"], stranger_headers),
        ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value,
        403,
    )

    owner_view = validate_success(
        api.get_quote(staged["quote_id"], world["customer_headers"])
    )
    assert owner_view["status"] == "SENT"

    approved = validate_success(
        api.approve_quote(staged["quote_id"], world["customer_headers"])
    )
    assert approved["status"] == "APPROVED"
    assert_money(approved["approved_total_cents"], 18080, "Quote.approved_total_cents")


def test_a_technician_reaches_only_the_work_orders_it_is_assigned(api):
    """PRD 2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting
    `Technician` row; ownership checks on any resource that references a technician compare
    the resource's technician foreign key to `X-User-ID`. Concretely, the compared fields
    are `WorkOrder.assigned_technician_id`, `Inspection.technician_id` and
    `EmergencyTicket.assigned_technician_id`."
    PRD 3.9: "**Posting parts** is only possible against an `IN_PROGRESS` work order and
    only by its assigned technician."

    Design: Corner/rbac/corner_rbac_technician_scope_is_confined_to_assigned_work_orders
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Assigned Scope Co",
        email="as@corner.example",
        address_line="2 Assigned",
        technician_tier="MASTER",
        technician_name="Owner Field Tech",
    )
    other = fixtures.new_technician("Other Field Tech", "MASTER", "JUR_ALPHA")
    other_headers = fixtures.make_technician_headers(other["id"])
    part = fixtures.new_part("CTL-5000-A", "CONTROL", 5000, on_hand_qty=10)

    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"
    )
    fixtures.set_clock("2026-06-01T12:00:00Z")

    validate_error(
        api.start_work_order(work_order["id"], other_headers),
        ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value,
        403,
    )
    started = validate_success(
        api.start_work_order(work_order["id"], world["technician_headers"])
    )
    assert started["fulfillment_status"] == "IN_PROGRESS"
    assert_instant_equals(
        started["actual_start_at"], "2026-06-01T12:00:00Z", "WorkOrder.actual_start_at"
    )

    validate_error(
        api.post_parts_consumption(
            work_order["id"],
            {"part_catalog_item_id": part["id"], "quantity": 1},
            other_headers,
        ),
        ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value,
        403,
    )
    assert fixtures.get_part(part["id"])["on_hand_qty"] == 10
    rows, _ = validate_paginated(
        api.list_work_order_parts_consumption(work_order["id"], DISPATCHER)
    )
    assert rows == []


def test_shared_operations_accept_every_declared_role(api):
    """PRD 4.4: "Roles: `PlatformAdmin`, `Dispatcher`. Success: 201, the created
    `WellProfile` with `duty_cycle_ratio` and `duty_cycle_class` already derived and
    `potability_status` `UNKNOWN`."
    PRD 4.9: "Roles: `Technician`, `ComplianceOfficer`, `PlatformAdmin`. Success: 201, the
    created `WaterTest` in `COLLECTED` with `parent_test_id` null."

    Design: Corner/rbac/corner_rbac_shared_operations_accept_every_declared_holder
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    account = fixtures.new_account("Shared Ops Co", "JUR_ALPHA", "sh@corner.example")
    prop = fixtures.new_property(account["id"], "2 Shared", "JUR_ALPHA", 10.0, 3)
    technician = fixtures.new_technician("Shared Tech", "JOURNEYMAN", "JUR_ALPHA")

    well_admin = validate_success(
        api.create_well_profile(
            {
                "property_id": prop["id"],
                "jurisdiction_code": "JUR_ALPHA",
                "well_type": "DRILLED",
                "depth_feet": 200.0,
            },
            ADMIN,
        ),
        201,
    )
    well_dispatcher = validate_success(
        api.create_well_profile(
            {
                "property_id": prop["id"],
                "jurisdiction_code": "JUR_ALPHA",
                "well_type": "DRIVEN",
                "depth_feet": 120.0,
            },
            DISPATCHER,
        ),
        201,
    )
    assert well_admin["potability_status"] == "UNKNOWN"
    assert well_admin["version"] == 1
    assert well_dispatcher["well_type"] == "DRIVEN"
    assert well_dispatcher["potability_status"] == "UNKNOWN"

    wells, _ = validate_paginated(api.list_property_well_profiles(prop["id"], ADMIN))
    assert len(wells) == 2

    body = {
        "well_profile_id": well_admin["id"],
        "collected_by_technician_id": technician["id"],
        "panel_type": "BACTERIOLOGICAL",
        "sample_datetime": "2026-06-01T00:00:00Z",
    }
    by_technician = validate_success(
        api.create_water_test(
            body, fixtures.make_technician_headers(technician["id"])
        ),
        201,
    )
    by_officer = validate_success(
        api.create_water_test(dict(body, panel_type="CHEMICAL"), OFFICER), 201
    )
    by_admin = validate_success(
        api.create_water_test(
            dict(body, sample_datetime="2026-06-01T06:00:00Z"), ADMIN
        ),
        201,
    )
    assert by_technician["result_status"] == "COLLECTED"
    assert by_technician["parent_test_id"] is None
    assert by_officer["result_status"] == "COLLECTED"
    assert by_officer["panel_type"] == "CHEMICAL"
    assert by_admin["result_status"] == "COLLECTED"

    tests, _ = validate_paginated(
        api.list_water_tests(OFFICER, params={"well_profile_id": well_admin["id"]})
    )
    assert len(tests) == 3
