"""Error and RBAC breadth: every parent-specific 404 code triggered on a real
unknown id, the referential check taken ahead of the version guard, the
role-exclusive refusals, the operations each role does own, and the row-level
scoping of a GroundTenant credential across an assignment."""

from test_helpers import (
    ERR_ALTERATION_NOT_FOUND,
    ERR_APPRAISAL_NOT_FOUND,
    ERR_ARBITRATION_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_LEASE_NOT_FOUND,
    ERR_LOSS_EVENT_NOT_FOUND,
    ERR_MORTGAGE_NOT_FOUND,
    ERR_NOTICE_NOT_FOUND,
    ERR_REVALUATION_NOT_FOUND,
    ERR_STATEMENT_NOT_FOUND,
    ERR_TRANSFER_NOT_FOUND,
    ERR_UNAUTHORIZED,
    NON_EXISTENT_UUID,
    assert_envelope_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_accountant_headers,
    make_arbitrator_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

MISSING = NON_EXISTENT_UUID


def test_every_unknown_id_answers_with_its_own_parent_specific_code(api):
    """PRD §2.8: "Each parent type has its own code — `ERR_LESSEE_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_MORTGAGE_NOT_FOUND`, `ERR_REVALUATION_NOT_FOUND`, `ERR_APPRAISAL_NOT_FOUND`, `ERR_ARBITRATION_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_ALTERATION_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_LOSS_EVENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND` and `ERR_CERTIFICATE_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/errors/unknown_ids_return_the_parent_specific_not_found_code
    """
    admin = make_lessor_admin_headers()
    manager = make_asset_manager_headers("am-1")
    accountant = make_accountant_headers("acct-1")
    agent = make_mortgagee_agent_headers("agent-keystone-1")

    reads = (
        (api.get_mortgage(MISSING, admin), ERR_MORTGAGE_NOT_FOUND),
        (api.get_revaluation(MISSING, admin), ERR_REVALUATION_NOT_FOUND),
        (api.get_appraisal(MISSING, admin), ERR_APPRAISAL_NOT_FOUND),
        (api.get_arbitration(MISSING, admin), ERR_ARBITRATION_NOT_FOUND),
        (api.get_statement(MISSING, accountant), ERR_STATEMENT_NOT_FOUND),
        (api.get_alteration(MISSING, manager), ERR_ALTERATION_NOT_FOUND),
        (api.get_transfer(MISSING, manager), ERR_TRANSFER_NOT_FOUND),
        (api.get_default_notice(MISSING, manager), ERR_NOTICE_NOT_FOUND),
        (api.get_loss_event(MISSING, accountant), ERR_LOSS_EVENT_NOT_FOUND),
        (api.get_reversion_assessment(MISSING, manager), ERR_ASSESSMENT_NOT_FOUND),
        (api.get_estoppel(MISSING, agent), ERR_CERTIFICATE_NOT_FOUND),
    )
    for response, expected in reads:
        validate_error(response, expected, expected_status=404)


def test_the_referential_check_is_taken_before_the_version_guard(api):
    """PRD §2.8: "Checks are evaluated in the following fixed priority order, and the **first** rule that fails determines the response; later rules are not consulted."

    Design: Corner/errors/unknown_ids_return_the_parent_specific_not_found_code
    """
    env = fx.standard_lease(api, "PIER-131", revaluation_interval_years=20)
    stale_version = env["lease"]["version"]
    fx.add_arrears(api, env["lease_id"], 3000000)
    assert fx.lease_version(api, env["lease_id"]) != stale_version

    validate_error(
        api.file_statement(
            f.statement_payload(
                MISSING, stale_version,
                "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", 120000000,
            ),
            env["tenant"],
        ),
        ERR_LEASE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.elect_new_lease(
            MISSING, f.new_lease_election_payload(env["lessee_id"]),
            make_mortgagee_agent_headers("agent-keystone-1"),
        ),
        ERR_MORTGAGE_NOT_FOUND,
        expected_status=404,
    )


def test_no_role_can_reach_another_roles_exclusive_operation(api):
    """PRD §4: "Every endpoint requires both the `X-User-ID` and `X-User-Role` headers; the Authorized Role(s) column is exhaustive, and any other role is refused with `ERR_UNAUTHORIZED` at HTTP 403 before any other check runs."

    Design: Corner/rbac/every_role_cannot_perform_another_roles_exclusive_operation
    """
    env = fx.standard_lease(api, "PIER-121")
    admin = make_lessor_admin_headers()
    manager = make_asset_manager_headers("am-1")
    accountant = make_accountant_headers("acct-1")
    mortgage = fx.record_senior_mortgage(
        api, env["lease_id"], original_principal_cents=30000000
    )

    refusals = (
        api.create_lease(
            f.lease_payload(env["lessee_id"], "PIER-122"), manager
        ),
        api.open_revaluation(
            env["lease_id"], f.revaluation_payload("2027-01-28T00:00:00Z"),
            env["tenant"],
        ),
        api.run_administration(manager),
        api.open_reversion_assessment(env["lease_id"], {}, accountant),
        api.create_alteration(
            env["lease_id"], f.alteration_payload(), manager
        ),
        api.elect_new_lease(
            mortgage["id"], f.new_lease_election_payload(env["lessee_id"]), admin
        ),
        api.list_statements(
            make_arbitrator_headers("appraiser-lessor-1"),
            {"lease_id": env["lease_id"]},
        ),
        api.list_lessees(make_mortgagee_agent_headers(mortgage["id"])),
        api.post_rent_charge(
            env["lease_id"], f.rent_charge_payload(-5000), env["tenant"]
        ),
    )
    for response in refusals:
        validate_error(response, ERR_UNAUTHORIZED, expected_status=403)

    _rows, meta = validate_paginated(api.list_leases(admin))
    assert meta["total_count"] == 1
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        version=1,
        arrears_balance_cents=0,
    )


def test_each_role_performs_the_operations_that_are_its_own(api):
    """PRD §2.1: "A `LeaseAccountant` owns the ledger: posting rent charges, assessing percentage-rent statements provisionally, auditing those statements, allocating loss proceeds and rescinding an allocation are exclusive to it; it shares default service, termination on an uncured default and holdback application, and it may read lease, statement, transfer, notice and loss-event resources."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_and_shared_operations
    """
    env = fx.standard_lease(api, "PIER-123")
    admin = make_lessor_admin_headers()

    amended = validate_success(
        api.amend_terms(env["lease_id"], {"percentage_rent_rate_bps": 700}, admin)
    )
    assert amended["percentage_rent_rate_bps"] == 700

    get_success_data(
        api.file_insurance_endorsement(
            env["lease_id"],
            f.insurance_payload(
                property_all_risk_limit_cents=80000000,
                builders_risk_limit_cents=3000000,
                expires_at="2027-08-01T00:00:00Z",
            ),
            admin,
        )
    )
    tenant_filing = get_success_data(
        api.file_insurance_endorsement(
            env["lease_id"],
            f.insurance_payload(
                property_all_risk_limit_cents=90000000,
                builders_risk_limit_cents=4000000,
                expires_at="2028-08-01T00:00:00Z",
            ),
            env["tenant"],
        )
    )
    assert tenant_filing["insurance_status"] == "ACTIVE"
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        insurance_status="ACTIVE",
        property_all_risk_limit_cents=90000000,
        builders_risk_limit_cents=4000000,
        lessor_additional_insured=True,
        insurance_expires_at="2028-08-01T00:00:00Z",
    )

    get_success_data(
        api.post_rent_charge(
            env["lease_id"], f.rent_charge_payload(2500000, "Q3 2026 base rent"),
            make_accountant_headers("acct-1"),
        )
    )
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 2500000

    request = validate_success(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(
                requested_gfa_sqft=10000,
                construction_window_start="2026-09-01T00:00:00Z",
                construction_window_end="2026-10-01T00:00:00Z",
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    assert request["status"] == "SUBMITTED"

    decided = validate_success(
        api.decide_alteration(
            request["id"], f.decision_payload("APPROVE"),
            make_asset_manager_headers("am-1"),
        )
    )
    assert_fields(decided, status="APPROVED", decided_by_user_id="am-1")
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, gfa_allocated_sqft=10000, gfa_unallocated_sqft=190000)
    assert_envelope_conserved(lease)


PEER = {
    "legal_name": "Cordova Yards Development LP",
    "notice_email": "notices@cordova.example",
}

ALT = {
    "requested_gfa_sqft": 10000,
    "construction_window_start": "2026-09-01T00:00:00Z",
    "construction_window_end": "2026-10-01T00:00:00Z",
}


def _two_tenants_one_lease_each(api):
    """Lessee A on PIER-124 and lessee B on PIER-125, each a valid GroundTenant."""
    lessee_a = fx.create_lessee(api)
    lessee_b = fx.create_lessee(api, **PEER)
    lease_a = fx.create_lease(api, lessee_a["id"], "PIER-124")
    lease_b = fx.create_lease(api, lessee_b["id"], "PIER-125")
    return {
        "a": lessee_a, "b": lessee_b,
        "lease_a": lease_a, "lease_b": lease_b,
        "tenant_a": make_ground_tenant_headers(lessee_a["id"]),
        "tenant_b": make_ground_tenant_headers(lessee_b["id"]),
    }


def test_a_ground_tenant_credential_does_not_reach_another_tenants_lease(api):
    """PRD §2.1: "When `X-User-Role` is `GroundTenant`, `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any resource that references a `Lessee` compare the resource's foreign-key field to `X-User-ID`, so a `GroundTenant` acting on a lease whose `lessee_id` is not its own `X-User-ID` is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/a_ground_tenant_cannot_touch_another_lessees_lease
    """
    world = _two_tenants_one_lease_each(api)
    lease_a, tenant_b = world["lease_a"], world["tenant_b"]

    refusals = (
        api.create_alteration(
            lease_a["id"], f.alteration_payload(**ALT), tenant_b
        ),
        api.file_statement(
            f.statement_payload(
                lease_a["id"], lease_a["version"],
                "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", 120000000,
            ),
            tenant_b,
        ),
        api.report_loss_event(
            lease_a["id"],
            f.loss_event_payload(damage_estimate_cents=4000000,
                                 damaged_area_sqft=20000),
            tenant_b,
        ),
        api.create_transfer(
            f.sublease_payload(
                lease_a["id"], "UNIT-A", 12000000, sublet_area_sqft=50000,
                transferee_legal_name="Northgate Grocers Inc",
                term_end="2029-09-01T00:00:00Z",
            ),
            tenant_b,
        ),
    )
    for response in refusals:
        validate_error(response, ERR_UNAUTHORIZED, expected_status=403)

    allowed = validate_success(
        api.create_alteration(
            world["lease_b"]["id"], f.alteration_payload(**ALT), tenant_b
        ),
        expected_status=201,
    )
    assert allowed["status"] == "SUBMITTED"
    assert_fields(fx.read_lease(api, lease_a["id"]),
                  lessee_id=world["a"]["id"], version=1)


def test_an_activated_assignment_moves_the_row_scope_to_the_assignee(api):
    """PRD §3.6: "For an `ASSIGNMENT`, the lease's `lessee_id` is rewritten to the request's `transferee_lessee_id` — the assignee becomes the tenant of record, and from that moment ownership checks on the lease compare against the new tenant's identifier."

    Design: Corner/rbac/a_ground_tenant_cannot_touch_another_lessees_lease
    """
    world = _two_tenants_one_lease_each(api)
    lease_a = world["lease_a"]

    assignment = validate_success(
        api.create_transfer(
            f.assignment_payload(
                lease_a["id"], world["b"]["id"], 40000000,
                transferee_legal_name=PEER["legal_name"],
                transferee_credit_rating_code="A",
            ),
            world["tenant_a"],
        ),
        expected_status=201,
    )
    granted = validate_success(
        api.decide_transfer(
            assignment["id"], f.decision_payload("APPROVE"),
            make_asset_manager_headers("am-1"),
        )
    )
    assert_fields(
        granted,
        status="CONSENT_GRANTED",
        transfer_fee_gross_cents=1200000,
        admin_charge_cents=30000,
        late_surcharge_cents=0,
        total_transfer_fee_cents=1230000,
        transfer_fee_paid_cents=0,
    )

    activated = validate_success(
        api.pay_transfer_fee(
            assignment["id"], f.fee_payment_payload(1230000), world["tenant_a"]
        )
    )
    assert_fields(activated, status="ACTIVE", transfer_fee_paid_cents=1230000)
    assert fx.read_lease(api, lease_a["id"])["lessee_id"] == world["b"]["id"]

    validate_error(
        api.create_alteration(
            lease_a["id"],
            f.alteration_payload(
                requested_gfa_sqft=5000,
                construction_window_start="2027-01-01T00:00:00Z",
                construction_window_end="2027-02-01T00:00:00Z",
            ),
            world["tenant_a"],
        ),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )
    filed = validate_success(
        api.create_alteration(
            lease_a["id"],
            f.alteration_payload(
                requested_gfa_sqft=5000,
                construction_window_start="2027-03-01T00:00:00Z",
                construction_window_end="2027-04-01T00:00:00Z",
            ),
            world["tenant_b"],
        ),
        expected_status=201,
    )
    assert filed["status"] == "SUBMITTED"
