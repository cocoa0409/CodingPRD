"""Role permissions: who may act, on which endpoint, and against which row.

Four suites cover the whole authorization surface: every role driving the
operations that belong to it alone, every role turned away from another role's
exclusive endpoint (including the header checks that fire before any role list
is consulted), the two paired duties that no single user id may perform on both
sides, and the two identity bindings that tie a technician to a ticket and a
customer administrator to a site.
"""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_2_USER_ID,
    ACCOUNT_MANAGER_USER_ID,
    FLEET_OPS_2_USER_ID,
    FLEET_OPS_USER_ID,
    TEST_USERS,
    ApiErrorId,
    activate_contract,
    advance_device_to,
    api_client,
    assert_device_dimensions,
    assert_fields,
    build_user_headers,
    configure_secure_release,
    create_quarterly_review,
    create_site,
    device_payload,
    dispatch_payload,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_part_stock,
    fetch_quarterly_review,
    fetch_service_ticket,
    fetch_site,
    fetch_technician,
    get_success_data,
    make_account_manager_headers,
    make_customer_admin_headers,
    make_field_technician_headers,
    make_fleet_ops_headers,
    meter_read_payload,
    removal_order_payload,
    resolve_exception_payload,
    resolve_ticket_payload,
    run_sweep,
    secure_release_config_payload,
    service_contract_payload,
    service_ticket_payload,
    set_clock,
    setup_print_environment,
    spare_part_stock_payload,
    submit_automated_read,
    technician_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
OPS = TEST_USERS["fleet_ops_headers"]

CONTRACT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 48_000,
    "labor_rate_cents_per_hour": 9_500,
}
MONO_TIERS = ((1, 1, None, 9_375),)
DEVICE = {
    "asset_tag": "MPS-0001",
    "model_code": "XR-M4200",
    "rated_monthly_duty_cycle": 20_000,
    "assessed_monthly_mono_pages": 9_000,
    "assessed_monthly_color_pages": 0,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
    "color_capable": False,
}
SITE = {"name": "Plant 1", "address_region": "NE-01", "toner_unit_cap": 4}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-15T00:00:00Z"
COVERAGE_END = "2026-08-15T00:00:00Z"

# 3,000 mono pages at 9,375 micro-dollars each is 2,812.5 cents, which rounds
# half up to 2,813 cents; the contract sets both page minimums to zero, so the
# usage subtotal is the whole statement total.
MONO_PAGES = 3_000
USAGE_CENTS = 2_813
PART_SKU = "FUSER-4200"


def _fleet_driven_by_its_owning_roles():
    """One contract lifecycle where each write is issued by the role that owns it.

    The AccountManager writes the contract, its rate card, the technician and the
    site; the FleetOpsController registers the device and pushes the automated
    reading; the CustomerAdmin for that site runs the secure-release probe; the
    FieldTechnician places and network-integrates the hardware; the
    BillingAnalyst opens the period.
    """
    env = setup_print_environment(
        contract=CONTRACT,
        mono_tiers=MONO_TIERS,
        site=dict(SITE),
        devices=[dict(DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    env["read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=MONO_PAGES,
        toner_level_pct=70,
        coverage_start=PERIOD_START,
        coverage_end=COVERAGE_END,
        user_id=FLEET_OPS_USER_ID,
    )
    return env


class TestEveryRoleDrivesItsOwnOperations:
    """Each role's exclusive writes succeed, and the shared reads answer everyone."""

    def test_each_role_completes_its_exclusive_operations_from_contract_to_close(self):
        """Every write in one contract lifecycle is accepted from the role that owns it.

        PRD: "Writes the contract shell and its cost-per-page rate card, activates, suspends and resumes it, registers customer sites and field technicians, authors quarterly business reviews, approves reviews authored by someone else, links refresh successors onto superseded assets, and opens and schedules end-of-contract removal orders."
        PRD: "Registers devices, activates them once the hosting site's secure print release is configured, stocks the site parts locker, ingests automated meter readings, resolves read exceptions raised by someone else's submission, voids the newest accepted read, sweeps a period for silent devices, raises and cancels consumable orders, and dispatches technicians."
        PRD: "Places and network-integrates hardware, submits manual meter readings, delivers cartridges, declares parts holds, records arrival onsite, resolves tickets with reported labour hours, and collects and sanitizes hardware at end of contract."
        PRD: "Configures secure print release for the site it represents, raises and cancels service tickets for devices at that site, and reads its own statements and reviews."
        PRD: "Opens billing periods, issues the forward-looking provisional statement, closes a period into its chronological final statement, and posts the end-of-contract settlement."

        Design: Corner/rbac/every_role_performs_its_exclusive_and_shared_operations_end_to_end
        """
        env = _fleet_driven_by_its_owning_roles()

        # The AccountManager's shell and the CustomerAdmin's probe both landed.
        assert_fields(fetch_contract(env["contract_id"]), status="ACTIVE")
        assert_fields(
            fetch_site(env["site_id"]),
            secure_release_state="CONFIGURED",
            release_method="PIN",
        )
        # The technician's two moves and the controller's activation both landed.
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")
        assert_fields(
            fetch_meter_read(env["read"]["id"]),
            status="ACCEPTED",
            source="AUTOMATED",
            mono_delta=MONO_PAGES,
            submitted_by_user_id=FLEET_OPS_USER_ID,
        )

        # The FleetOpsController stocks the site's parts locker.
        get_success_data(
            api_client.adjust_spare_part_stock(
                env["site_id"], spare_part_stock_payload(PART_SKU, 2), OPS
            )
        )
        assert_fields(fetch_part_stock(env["site_id"], PART_SKU), on_hand_qty=2)

        # The AccountManager registers a second technician and authors the review.
        second_technician = validate_success(
            api_client.create_technician(
                technician_payload(
                    full_name="Ivan Petrov", home_region="NE-02", skill_level="L1"
                ),
                AM,
            ),
            expected_status=201,
        )
        assert_fields(second_technician, skill_level="L1", travel_buffer_minutes=30)
        review = create_quarterly_review(
            env["contract_id"], quarter_label="2026-Q3", user_id=ACCOUNT_MANAGER_USER_ID
        )
        assert_fields(
            review, status="DRAFT", authored_by_user_id=ACCOUNT_MANAGER_USER_ID
        )

        # The FleetOpsController sweeps; the BillingAnalyst closes.
        run_sweep(env["period_id"], user_id=FLEET_OPS_USER_ID)
        assert_fields(
            fetch_billing_period(env["period_id"]), status="SWEPT", exception_open_count=0
        )
        set_clock(PERIOD_END, headers=BA)
        statement = validate_success(
            api_client.close_billing_period(env["period_id"], BA), expected_status=201
        )
        assert_fields(
            statement,
            variant="FINAL",
            usage_subtotal_cents=USAGE_CENTS,
            total_cents=USAGE_CENTS,
        )

    def test_shared_reads_answer_roles_that_own_none_of_those_writes(self):
        """Read endpoints listing several roles answer 200 to each of them.

        PRD: "If both headers are well formed but the named role is not authorized for the endpoint being called (see the authorization column in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "Creating a new resource returns HTTP 201; every other successful operation, including all state transitions, all reads and all list queries, returns HTTP 200."
        PRD: "Configures secure print release for the site it represents, raises and cancels service tickets for devices at that site, and reads its own statements and reviews."

        Design: Corner/rbac/every_role_performs_its_exclusive_and_shared_operations_end_to_end
        """
        env = _fleet_driven_by_its_owning_roles()
        get_success_data(
            api_client.adjust_spare_part_stock(
                env["site_id"], spare_part_stock_payload(PART_SKU, 2), OPS
            )
        )
        review = create_quarterly_review(
            env["contract_id"], quarter_label="2026-Q3", user_id=ACCOUNT_MANAGER_USER_ID
        )
        run_sweep(env["period_id"], user_id=FLEET_OPS_USER_ID)
        set_clock(PERIOD_END, headers=BA)
        statement = get_success_data(
            api_client.close_billing_period(env["period_id"], BA)
        )

        tech_headers = env["tech_headers"]
        site_headers = env["site_headers"]

        # A technician reads the commercial shell it never writes.
        assert_fields(
            validate_success(
                api_client.get_service_contract(env["contract_id"], tech_headers)
            ),
            status="ACTIVE",
        )
        # The customer reads one device by id.
        assert_fields(
            validate_success(api_client.get_device(env["device_id"], site_headers)),
            lifecycle_state="ACTIVE",
        )
        # The analyst lists the fleet it never registers.
        devices, devices_meta = validate_paginated(
            api_client.list_devices(BA, params={"contract_id": env["contract_id"]})
        )
        assert len(devices) == 1
        assert devices_meta["total_count"] == 1
        # A second account manager lists the readings it never submits.
        reads, reads_meta = validate_paginated(
            api_client.list_meter_reads(
                make_account_manager_headers(ACCOUNT_MANAGER_2_USER_ID),
                params={"billing_period_id": env["period_id"]},
            )
        )
        assert reads_meta["total_count"] == 1
        assert_fields(reads[0], id=env["read"]["id"], status="ACCEPTED")
        # The technician lists the locker the controller stocked.
        stocks, _ = validate_paginated(
            api_client.list_spare_part_stocks(
                env["site_id"], tech_headers, params={"part_sku": PART_SKU, "limit": 100}
            )
        )
        assert len(stocks) == 1
        # The customer reads its own review and its own statement lines.
        assert_fields(
            validate_success(api_client.get_quarterly_review(review["id"], site_headers)),
            quarter_label="2026-Q3",
        )
        lines, _ = validate_paginated(
            api_client.list_statement_lines(
                statement["id"], site_headers, params={"limit": 100}
            )
        )
        assert len(lines) == 1
        assert_fields(lines[0], pages=MONO_PAGES, amount_cents=USAGE_CENTS)


def _role_matrix_environment():
    """An ACTIVE contract, one ACTIVE device, an OPEN period and a DRAFT review."""
    env = setup_print_environment(
        contract=CONTRACT,
        mono_tiers=MONO_TIERS,
        site=dict(SITE),
        devices=[dict(DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    env["review"] = create_quarterly_review(
        env["contract_id"], quarter_label="2026-Q3", user_id=ACCOUNT_MANAGER_USER_ID
    )
    return env


def _intake_body(env):
    return meter_read_payload(
        env["device_id"],
        env["period_id"],
        mono_meter=1_000,
        color_meter=0,
        toner_level_pct=80,
        coverage_start=PERIOD_START,
        coverage_end="2026-08-10T00:00:00Z",
    )


# Each entry is one endpoint called by a role the endpoint does not list.
DENIED_CALLS = {
    "contract_create_as_analyst": lambda env: api_client.create_service_contract(
        service_contract_payload(
            customer_name="Rogue Co", term_months=12, monthly_service_fee_cents=1_000
        ),
        BA,
    ),
    "device_create_as_customer": lambda env: api_client.create_device(
        device_payload(
            env["contract_id"], env["site_id"], **dict(DEVICE, asset_tag="MPS-0002")
        ),
        make_customer_admin_headers(env["site_id"]),
    ),
    "period_close_as_controller": lambda env: api_client.close_billing_period(
        env["period_id"], OPS
    ),
    "agent_intake_as_technician": lambda env: api_client.submit_automated_meter_read(
        _intake_body(env), make_field_technician_headers(env["technician_id"])
    ),
    "manual_intake_as_controller": lambda env: api_client.submit_manual_meter_read(
        _intake_body(env), OPS
    ),
    "device_list_as_customer": lambda env: api_client.list_devices(
        make_customer_admin_headers(env["site_id"]),
        params={"contract_id": env["contract_id"]},
    ),
    "review_approve_as_analyst": lambda env: api_client.approve_quarterly_review(
        env["review"]["id"], BA
    ),
    "removal_order_as_analyst": lambda env: api_client.create_removal_order(
        removal_order_payload(env["contract_id"], "2026-12-01T00:00:00Z"), BA
    ),
    "ticket_create_as_technician": lambda env: api_client.create_service_ticket(
        service_ticket_payload(env["device_id"]),
        make_field_technician_headers(env["technician_id"]),
    ),
}


class TestNoRoleReachesAnotherRolesExclusiveEndpoint:
    """The role gate is per endpoint, and the header gate fires before it."""

    @pytest.mark.parametrize("case", sorted(DENIED_CALLS))
    def test_a_role_outside_the_endpoints_list_is_refused(self, case):
        """Each endpoint refuses a well-formed caller whose role it does not list.

        PRD: "If both headers are well formed but the named role is not authorized for the endpoint being called (see the authorization column in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "**Role authorization.** The acting role appears in the endpoint's authorized-role list in §4 — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_headerless_calls_are_rejected
        """
        env = _role_matrix_environment()
        validate_error(DENIED_CALLS[case](env), ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    def test_every_refused_call_leaves_the_platform_exactly_as_it_was(self):
        """None of the refused writes leaves a trace behind it.

        PRD: "If both headers are well formed but the named role is not authorized for the endpoint being called (see the authorization column in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "**Role authorization.** The acting role appears in the endpoint's authorized-role list in §4 — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_headerless_calls_are_rejected
        """
        env = _role_matrix_environment()
        for case in sorted(DENIED_CALLS):
            validate_error(DENIED_CALLS[case](env), ApiErrorId.ERR_ROLE_NOT_PERMITTED)

        # The fleet gained no second device, and both intake attempts stored nothing.
        devices, devices_meta = validate_paginated(
            api_client.list_devices(BA, params={"contract_id": env["contract_id"]})
        )
        assert len(devices) == 1
        assert devices_meta["total_count"] == 1
        _, reads_meta = validate_paginated(
            api_client.list_meter_reads(OPS, params={"billing_period_id": env["period_id"]})
        )
        assert reads_meta["total_count"] == 0
        # No transition ran: the period is still open, the review still a draft, the
        # contract still active rather than winding down, and no ticket exists.
        assert_fields(fetch_billing_period(env["period_id"]), status="OPEN")
        review = fetch_quarterly_review(env["review"]["id"])
        assert_fields(review, status="DRAFT", approved_by_user_id=None)
        assert_fields(fetch_contract(env["contract_id"]), status="ACTIVE")
        _, tickets_meta = validate_paginated(
            api_client.list_service_tickets(OPS, params={"device_id": env["device_id"]})
        )
        assert tickets_meta["total_count"] == 0

    def test_absent_and_undeclared_role_headers_are_rejected_before_any_role_list(self):
        """A missing header and an unknown role name both report the authentication failure.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the five role names below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD: "**Authentication.** Both `X-User-Role` and `X-User-ID` are present and `X-User-Role` is one of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_headerless_calls_are_rejected
        """
        env = _role_matrix_environment()

        # Neither header present at all.
        validate_error(
            api_client.get_service_contract(env["contract_id"], {}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        # Both headers present, but the named role is not one of the five.
        validate_error(
            api_client.activate_device(
                env["device_id"], build_user_headers("root-1", "SuperAdmin")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        # The refused transition did not run.
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")


def _exception_read_and_draft_review():
    """A reading parked in EXCEPTION by ops-1, plus a review authored by am-1.

    The device's rated monthly duty cycle is 20,000 pages, so a first reading of
    60,001 mono pages exceeds three times that cycle by exactly one page and
    lands in EXCEPTION instead of being accepted.
    """
    env = setup_print_environment(
        contract=CONTRACT,
        mono_tiers=MONO_TIERS,
        site=dict(SITE),
        devices=[dict(DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    env["read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=60_001,
        toner_level_pct=40,
        coverage_start=PERIOD_START,
        coverage_end=COVERAGE_END,
        user_id=FLEET_OPS_USER_ID,
    )
    env["review"] = create_quarterly_review(
        env["contract_id"], quarter_label="2026-Q3", user_id=ACCOUNT_MANAGER_USER_ID
    )
    return env


CORRECTION = {
    "corrected_mono_meter": 5_000,
    "corrected_color_meter": 0,
    "corrected_toner_level_pct": 60,
}


class TestPairedDutiesRequireTwoDistinctUsers:
    """The submitter may not resolve, the author may not approve — by user id."""

    def test_the_submitting_controller_cannot_resolve_its_own_exception(self):
        """Resolution is refused to the submitter and accepted from a second controller.

        PRD: "A meter reading records the operator who submitted it in `submitted_by_user_id`; when an exception on that reading is later resolved, the resolving operator is recorded in `resolved_by_user_id`, and the two must differ."
        PRD: "The reading must currently be in `EXCEPTION` (otherwise `ERR_READ_INVALID_STATE`), its period must not be `CLOSED` (otherwise `ERR_PERIOD_ALREADY_CLOSED`), and the resolving `X-User-ID` must differ from the reading's `submitted_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."
        PRD: "Resolution overwrites the reading's `mono_meter`, `color_meter` and `toner_level_pct` with the three corrected values, records the `resolution_note`, stamps `resolved_by_user_id` with the acting `X-User-ID`, increments the reading's `version`, and moves it `EXCEPTION → PENDING_VALIDATION` — after which **exactly the same validation runs again** and lands the reading either in `ACCEPTED`, with the full four-hop cascade above, or right back in `EXCEPTION`."

        Design: Corner/rbac/segregation_of_duties_submitter_and_author_are_barred_from_their_own_second_step
        """
        env = _exception_read_and_draft_review()
        read_id = env["read"]["id"]
        assert_fields(
            fetch_meter_read(read_id),
            status="EXCEPTION",
            exception_reason="IMPLAUSIBLE_SPIKE",
            submitted_by_user_id=FLEET_OPS_USER_ID,
        )

        validate_error(
            api_client.resolve_meter_read_exception(
                read_id,
                resolve_exception_payload(
                    resolution_note="panel re-read by submitter", **CORRECTION
                ),
                make_fleet_ops_headers(FLEET_OPS_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        # Nothing was corrected and nobody was recorded as the resolver.
        assert_fields(
            fetch_meter_read(read_id),
            status="EXCEPTION",
            mono_meter=60_001,
            resolved_by_user_id=None,
        )

        resolved = validate_success(
            api_client.resolve_meter_read_exception(
                read_id,
                resolve_exception_payload(
                    resolution_note="panel re-read by reviewer", **CORRECTION
                ),
                make_fleet_ops_headers(FLEET_OPS_2_USER_ID),
            )
        )
        assert_fields(
            resolved,
            status="ACCEPTED",
            mono_meter=5_000,
            mono_delta=5_000,
            resolved_by_user_id=FLEET_OPS_2_USER_ID,
        )
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=5_000,
            lifetime_mono_pages=5_000,
            toner_level_pct=60,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_the_authoring_manager_cannot_approve_its_own_review(self):
        """Approval is refused to the author and accepted from a second manager.

        PRD: "A quarterly business review records its author in `authored_by_user_id`; when it is approved, the approver is recorded in `approved_by_user_id`, and again the two must differ."
        PRD: "In both cases an attempt by the same `X-User-ID` to perform both halves is rejected with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."
        PRD: "A second `AccountManager` — necessarily a different `X-User-ID` from the review's `authored_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` — approves the review, driving `DRAFT → APPROVED`, stamping `approved_by_user_id` with the acting `X-User-ID`, and incrementing the review's `version`."

        Design: Corner/rbac/segregation_of_duties_submitter_and_author_are_barred_from_their_own_second_step
        """
        env = _exception_read_and_draft_review()
        review = env["review"]
        assert_fields(
            review, status="DRAFT", authored_by_user_id=ACCOUNT_MANAGER_USER_ID
        )

        validate_error(
            api_client.approve_quarterly_review(
                review["id"], make_account_manager_headers(ACCOUNT_MANAGER_USER_ID)
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        assert_fields(
            fetch_quarterly_review(review["id"]),
            status="DRAFT",
            approved_by_user_id=None,
            version=review["version"],
        )

        approved = validate_success(
            api_client.approve_quarterly_review(
                review["id"], make_account_manager_headers(ACCOUNT_MANAGER_2_USER_ID)
            )
        )
        assert_fields(
            approved,
            status="APPROVED",
            approved_by_user_id=ACCOUNT_MANAGER_2_USER_ID,
            version=review["version"] + 1,
        )


SECOND_TECHNICIAN = {
    "full_name": "Dana Volk",
    "home_region": "NE-01",
    "skill_level": "L3",
    "travel_buffer_minutes": 30,
}
TICKET_CLOCK = "2026-08-15T08:00:00Z"
WINDOW_START = "2026-08-15T09:00:00Z"
WINDOW_END = "2026-08-15T11:00:00Z"
LABOR_HOURS = 2
LABOR_CENTS = 19_000


def _two_sites_and_two_technicians():
    """Two sites in one region and two equally qualified L3 technicians.

    The device lives at the first site and is still ASSESSED; only the second
    site has run its secure-release probe.
    """
    env = setup_print_environment(
        contract=CONTRACT,
        mono_tiers=MONO_TIERS,
        site=dict(SITE),
        devices=[dict(DEVICE)],
        extra_technicians=(dict(SECOND_TECHNICIAN),),
        activate=False,
        probe_result=None,
        device_stage="ASSESSED",
        period=None,
    )
    second_site = create_site(
        env["contract_id"],
        name="Plant 2",
        address_region="NE-01",
        toner_unit_cap=4,
        network_vlan_tag=2002,
    )
    activate_contract(env["contract_id"])
    configure_secure_release(
        second_site["id"],
        release_method="BADGE",
        probe_result="PASS",
        network_vlan_tag=2002,
    )
    set_clock(TICKET_CLOCK)
    env["second_site"] = second_site
    env["second_site_id"] = second_site["id"]
    env["second_site_headers"] = make_customer_admin_headers(second_site["id"])
    env["second_technician_id"] = env["technicians"][1]["id"]
    return env


def _active_device_at_its_own_site():
    """The first site configured by its own administrator, its device ACTIVE."""
    env = _two_sites_and_two_technicians()
    configure_secure_release(
        env["site_id"], release_method="PIN", probe_result="PASS", network_vlan_tag=2001
    )
    advance_device_to(env["device_id"], env["technician_id"], stage="ACTIVE")
    return env


class TestIdentityBindingScopesActionsToOwnedResources:
    """A customer administrator owns one site; a technician owns one ticket."""

    def test_secure_release_configuration_is_bound_to_the_acting_site(self):
        """Another site's administrator cannot configure this site, its own can.

        PRD: "A `CustomerAdmin` acting on a site other than the one its `X-User-ID` names is rejected with `ERR_SITE_OWNERSHIP_REQUIRED`."
        PRD: "It writes both `release_method` and `network_vlan_tag` onto the site, sets `secure_release_state` to `CONFIGURED`, and increments the site's `version` by 1."

        Design: Corner/rbac/segregation_of_duties_identity_binding_scopes_technician_and_customer_actions_to_their_own_resources
        """
        env = _two_sites_and_two_technicians()
        before = fetch_site(env["site_id"])
        assert_fields(before, secure_release_state="UNCONFIGURED", release_method="NONE")

        config = secure_release_config_payload(
            release_method="PIN", probe_result="PASS", network_vlan_tag=2001
        )
        validate_error(
            api_client.configure_secure_release(
                env["site_id"], config, env["second_site_headers"]
            ),
            ApiErrorId.ERR_SITE_OWNERSHIP_REQUIRED,
        )
        assert_fields(
            fetch_site(env["site_id"]),
            secure_release_state="UNCONFIGURED",
            release_method="NONE",
            version=before["version"],
        )

        configured = validate_success(
            api_client.configure_secure_release(
                env["site_id"], config, env["site_headers"]
            )
        )
        assert_fields(
            configured,
            secure_release_state="CONFIGURED",
            release_method="PIN",
            network_vlan_tag=2001,
            version=before["version"] + 1,
        )

    def test_ticket_creation_is_bound_to_the_site_hosting_the_device(self):
        """A ticket for a device at another site is refused; the owning site's is accepted.

        PRD: "A ticket raised for a device at another site is rejected with `ERR_SITE_OWNERSHIP_REQUIRED`, and a ticket raised against a contract that is not `ACTIVE` is rejected with `ERR_CONTRACT_NOT_ACTIVE`."
        PRD: "A `CustomerAdmin` acting on a site other than the one its `X-User-ID` names is rejected with `ERR_SITE_OWNERSHIP_REQUIRED`."

        Design: Corner/rbac/segregation_of_duties_identity_binding_scopes_technician_and_customer_actions_to_their_own_resources
        """
        env = _active_device_at_its_own_site()
        body = service_ticket_payload(
            env["device_id"], severity="STANDARD", symptom_code="PAPER_JAM"
        )

        validate_error(
            api_client.create_service_ticket(body, env["second_site_headers"]),
            ApiErrorId.ERR_SITE_OWNERSHIP_REQUIRED,
        )
        _, tickets_meta = validate_paginated(
            api_client.list_service_tickets(OPS, params={"device_id": env["device_id"]})
        )
        assert tickets_meta["total_count"] == 0

        ticket = validate_success(
            api_client.create_service_ticket(body, env["site_headers"]),
            expected_status=201,
        )
        assert_fields(ticket, status="OPEN", device_id=env["device_id"], severity="STANDARD")

    def test_only_the_assigned_technician_may_advance_and_resolve_the_ticket(self):
        """A second equally qualified technician is refused arrival and resolution.

        PRD: "From this point on every ticket action is restricted to the assigned technician — a `FieldTechnician` whose `X-User-ID` differs from the ticket's `assigned_technician_id` is rejected with `ERR_TECHNICIAN_NOT_ASSIGNED`."
        PRD: "**Ownership.** The acting `FieldTechnician`'s `X-User-ID` equals the ticket's `assigned_technician_id`, and the acting `CustomerAdmin`'s `X-User-ID` equals the owning `Site` identifier — otherwise `ERR_TECHNICIAN_NOT_ASSIGNED` or `ERR_SITE_OWNERSHIP_REQUIRED` (403)."
        PRD: "Resolution performs `ONSITE → RESOLVED`, stamps `responded_at` from the logical clock, recomputes the technician's `open_dispatch_count` downward, increments the ticket's `version`, and cascades onto the hardware: when the device's `lifecycle_state` is `SERVICE_HOLD` it returns `SERVICE_HOLD → ACTIVE` with its own `version` increment, making `ACTIVE → SERVICE_HOLD → ACTIVE` a cycle that repeats once per dispatched ticket."
        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's `included_service_scope` is `FULL`, and otherwise the reported `labor_hours` **rounded up to a whole number of hours first** and then multiplied by the contract's `labor_rate_cents_per_hour` — the rounding happens before the multiplication, never after."
        PRD: "First, `hours_late`: the number of hours between `respond_by` and `responded_at`, rounded up to a whole hour, floored at zero so that a ticket resolved on or before its deadline records exactly 0."

        Design: Corner/rbac/segregation_of_duties_identity_binding_scopes_technician_and_customer_actions_to_their_own_resources
        """
        env = _active_device_at_its_own_site()
        assigned = make_field_technician_headers(env["technician_id"])
        stranger = make_field_technician_headers(env["second_technician_id"])

        ticket = get_success_data(
            api_client.create_service_ticket(
                service_ticket_payload(env["device_id"]), env["site_headers"]
            )
        )
        dispatched = validate_success(
            api_client.dispatch_service_ticket(
                ticket["id"],
                dispatch_payload(env["technician_id"], WINDOW_START, WINDOW_END),
                OPS,
            )
        )
        assert_fields(
            dispatched, status="DISPATCHED", assigned_technician_id=env["technician_id"]
        )
        assert_device_dimensions(
            fetch_device(env["device_id"]), "SERVICE_HOLD", "SUPPLY_OK"
        )

        # Arrival by the technician the ticket was not dispatched to.
        validate_error(
            api_client.arrive_onsite(ticket["id"], stranger),
            ApiErrorId.ERR_TECHNICIAN_NOT_ASSIGNED,
        )
        assert_fields(fetch_service_ticket(ticket["id"]), status="DISPATCHED")

        assert_fields(
            validate_success(api_client.arrive_onsite(ticket["id"], assigned)),
            status="ONSITE",
        )

        # Resolution by the same stranger, with a perfectly valid labour report.
        validate_error(
            api_client.resolve_service_ticket(
                ticket["id"], resolve_ticket_payload(labor_hours=LABOR_HOURS), stranger
            ),
            ApiErrorId.ERR_TECHNICIAN_NOT_ASSIGNED,
        )
        assert_fields(fetch_service_ticket(ticket["id"]), status="ONSITE", labor_cents=0)

        resolved = validate_success(
            api_client.resolve_service_ticket(
                ticket["id"], resolve_ticket_payload(labor_hours=LABOR_HOURS), assigned
            )
        )
        assert_fields(
            resolved,
            status="RESOLVED",
            labor_cents=LABOR_CENTS,
            hours_late=0,
            sla_credit_cents=0,
        )
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=0)
