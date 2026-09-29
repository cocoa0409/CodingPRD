"""Role-based access control of PRD §2.1 against the endpoint role lists of PRD §4.

Covers what each of the five roles may and may not do: the operations reserved to
the `PortfolioAdmin`, the refusals the engineer, the auditor, the tenant and the
landlord receive when they reach for an endpoint their role is not listed for,
the tower read every role shares, the resolution of the two entity-backed
identities, and the segregation of duties PRD §3.6 imposes on certification.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_IDENTITY_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_cents,
    assert_common_resource_fields,
    assert_list_meta,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    ENGINEER_HEADERS,
    ENGINEER_USER_ID,
    OTHER_ENGINEER_HEADERS,
    OTHER_ENGINEER_USER_ID,
    UNRESOLVABLE_LANDLORD_HEADERS,
    UNRESOLVABLE_TENANT_HEADERS,
    make_landlord_headers,
    make_tenant_headers,
)

# ─────────────────────────────────────────────────────────────────────────────
# The operations reserved to the PortfolioAdmin
# ─────────────────────────────────────────────────────────────────────────────


def test_portfolio_admin_registers_the_site_asset_and_its_ground_lease(api):
    """PRD §3.2: "On creation the lease's `status` is `ACTIVE`, `renewals_exercised`
    is 0, `paid_through_date` is null because no payment exists yet,
    `buyout_paid_cents` is 0, and `current_monthly_rent_cents` is computed."

    The tower, the payee and the ground lease are all `PortfolioAdmin`-only
    registrations per the PRD §4 role lists, and PRD §3.2 adds that "Creating a
    lease also recomputes the tower's `capacity_posture` and increments the
    tower's `version` by one."

    Design: Corner/rbac/portfolio_admin_performs_its_exclusive_operations
    """
    tower = validate_success(
        api.create_tower(
            factories.tower_payload(
                site_name="Admin Authority Arch",
                structure_type="MONOPOLE",
                rated_capacity_load_units=9000,
                min_colocation_elevation_ft=50,
                max_elevation_ft=300,
                ground_space_total_sqft=9000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(tower)
    assert tower["version"] == 1, "a freshly registered tower starts at version 1"
    assert_tower_capacity(tower, capacity_posture="OPEN", open_review_count=0)

    landlord = validate_success(
        api.create_landlord(
            factories.landlord_payload(
                legal_name="Authority Land Trust",
                remit_contact_email="ap@authorityland.example",
                w9_on_file=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(landlord)
    assert landlord["w9_on_file"] is True

    lease = validate_success(
        api.create_ground_lease(
            factories.ground_lease_payload(
                tower["id"],
                landlord["id"],
                base_monthly_rent_cents=300000,
                escalator_pct=2.0,
                commencement_date="2020-06-01",
                term_end_date="2031-05-31",
                renewal_option_count=1,
                renewal_term_years=5,
                buyout_price_cents=9000000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(lease)
    assert lease["status"] == "ACTIVE"
    assert lease["renewals_exercised"] == 0
    assert lease["paid_through_date"] is None
    assert_cents(lease["buyout_paid_cents"], 0, "buyout_paid_cents")

    tower_after = fixtures.read_tower(api, tower["id"])
    assert_tower_capacity(tower_after, capacity_posture="OPEN")
    assert tower_after["version"] == 2, "creating the lease increments the tower version by one"


def test_portfolio_admin_registers_carrier_and_activates_its_master_lease(api):
    """PRD §3.3: "Activation recomputes `application_privilege`, which lands on
    `ENABLED` when the tenant's `credit_status` is `CURRENT`."

    Tenant registration, master-lease creation and activation are all
    `PortfolioAdmin` operations in the PRD §4 role lists, and before activation
    PRD §3.3 pins the starting posture: "A new master lease starts in `status`
    `DRAFT` with `application_privilege` at `ENABLED` and
    `executed_amendment_count` at 0."

    Design: Corner/rbac/portfolio_admin_performs_its_exclusive_operations
    """
    tenant = validate_success(
        api.create_tenant(
            factories.tenant_payload(legal_name="Authority Wireless", carrier_code="AAW"),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(tenant)
    assert_tenant_ledger(tenant, outstanding_balance_cents=0, credit_status="CURRENT")

    drafted = validate_success(
        api.create_master_lease_agreement(
            factories.master_lease_agreement_payload(
                tenant["id"],
                base_monthly_rent_cents=200000,
                escalator_pct=3.0,
                initial_term_years=10,
                renewal_terms_count=1,
                expires_on="2036-07-31",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(drafted)
    assert drafted["status"] == "DRAFT"
    assert drafted["application_privilege"] == "ENABLED"
    assert drafted["executed_amendment_count"] == 0

    activated = validate_success(
        api.activate_master_lease_agreement(drafted["id"], {}, ADMIN_HEADERS), 200
    )
    assert activated["id"] == drafted["id"]
    assert activated["status"] == "ACTIVE"
    assert activated["application_privilege"] == "ENABLED"

    stored = fixtures.read_master_lease(api, tenant["id"], drafted["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["application_privilege"] == "ENABLED"


# ─────────────────────────────────────────────────────────────────────────────
# Roles reaching for an endpoint they are not listed for
# ─────────────────────────────────────────────────────────────────────────────


def test_structural_engineer_cannot_execute_amendment(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not among
    the roles listed for the requested endpoint in §4, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (403)."

    Amendment execution is listed for `PortfolioAdmin` alone in PRD §4, so the
    engineer who analysed the application is refused even though every business
    gate of PRD §3.7 would pass, and the amendment claims nothing until the
    admin signs it.

    Design: Corner/rbac/structural_engineer_cannot_execute_amendment
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Engineer Limit Ledge",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Engineer Ledge Land",
            "remit_contact_email": "ap@engineerledge.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Engineer Limit Telecom", "carrier_code": "SEX"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "SE-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
    )
    tower_id = chain["tower"]["id"]
    amendment = chain["amendment"]

    refused = api.execute_site_amendment(
        amendment["id"], factories.execute_payload(True), ENGINEER_HEADERS
    )
    validate_error(refused, ERR_ROLE_NOT_PERMITTED, 403)

    parked = fixtures.read_amendment(api, amendment["id"])
    assert_amendment_axes(
        parked,
        execution_status="DRAFT",
        billing_status="NOT_BILLING",
        restoration_status="NOT_REQUIRED",
    )
    assert parked["version"] == amendment["version"], "the refusal mutated nothing"
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=0,
        reserved_ground_space_sqft=0,
        occupied_band_count=0,
    )

    executed = validate_success(
        api.execute_site_amendment(
            amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )
    assert_amendment_axes(executed, execution_status="EXECUTED", billing_status="BILLING")
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=500.0,
        reserved_ground_space_sqft=300,
        occupied_band_count=1,
    )


def test_compliance_auditor_cannot_open_colocation_application(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not among
    the roles listed for the requested endpoint in §4, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (403)."

    Application intake is listed for `Tenant` alone in PRD §4, so the auditor is
    refused at role authorization — before any identity or scope evaluation of
    PRD §2.6 — while the audit scheduling PRD §3.9 gives that same auditor
    still succeeds.

    Design: Corner/rbac/compliance_auditor_cannot_create_colocation_application
    """
    tower = fixtures.new_tower(
        api,
        site_name="Auditor Limit Arch",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Auditor Limit Radio", "carrier_code": "CAA"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )

    refused = api.create_colocation_application(
        factories.colocation_application_payload(
            tower["id"],
            carrier["mla"]["id"],
            requested_elevation_bottom_ft=100,
            requested_elevation_top_ft=140,
            requested_ground_space_sqft=300,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(refused, ERR_ROLE_NOT_PERMITTED, 403)

    rows, meta = validate_paginated(api.list_colocation_applications({"limit": 100}, ADMIN_HEADERS))
    assert rows == [], "the refused intake created no application"
    assert_list_meta(meta, total_count=0)

    audit = validate_success(
        api.create_equipment_audit(
            factories.equipment_audit_payload(tower["id"], basis="DISCOVERY_LIMITED"),
            AUDITOR_HEADERS,
        ),
        201,
    )
    assert audit["status"] == "SCHEDULED"
    assert audit["basis"] == "DISCOVERY_LIMITED"
    assert audit["auditor_user_id"] == AUDITOR_USER_ID
    assert audit["finding_count"] == 0
    assert_cents(audit["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents")


def test_tenant_cannot_approve_its_own_application(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not among
    the roles listed for the requested endpoint in §4, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (403)."

    Approval is listed for `PortfolioAdmin` alone in PRD §4, so the carrier that
    authored and submitted the application cannot approve it even though it owns
    the resource and would pass the ownership scope check of PRD §2.1.

    Design: Corner/rbac/tenant_cannot_approve_its_own_application
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Tenant Approve Arch",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Tenant Approve Radio", "carrier_code": "TAA"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "TA-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    application = chain["application"]
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert_analysis_outcome(chain["analysis"], result="PASS", status="ISSUED")

    refused = api.approve_colocation_application(
        application["id"], {}, chain["tenant_headers"]
    )
    validate_error(refused, ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = fixtures.read_application(api, application["id"])
    assert unchanged["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert unchanged["version"] == application["version"], "the refusal mutated nothing"
    assert_tower_capacity(fixtures.read_tower(api, chain["tower"]["id"]), open_review_count=1)


def test_landlord_cannot_list_colocation_applications(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not among
    the roles listed for the requested endpoint in §4, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (403)."

    The application list of PRD §4 names `PortfolioAdmin`, `StructuralEngineer`,
    `ComplianceAuditor` and `Tenant` but not `Landlord`, so the landlord is
    refused there while the tower read it does hold still answers.

    Design: Corner/rbac/landlord_cannot_list_colocation_applications
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Landlord Window Way",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Window Way Land",
            "remit_contact_email": "ap@windowway.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
    )
    landlord_headers = make_landlord_headers(site["landlord"]["id"])

    refused = api.list_colocation_applications({"limit": 100}, landlord_headers)
    validate_error(refused, ERR_ROLE_NOT_PERMITTED, 403)

    tower = validate_success(api.get_tower(site["tower"]["id"], landlord_headers), 200)
    assert tower["id"] == site["tower"]["id"]


# ─────────────────────────────────────────────────────────────────────────────
# The tower read every role shares
# ─────────────────────────────────────────────────────────────────────────────


def test_all_five_roles_read_the_same_tower_record(api):
    """PRD §3.1: "Towers can be listed with optional `capacity_posture` and
    `structure_type` filters alongside `limit` and `offset`, and every role may
    read them."

    The single-tower read of PRD §4 lists all five roles, so each of the five
    well-formed principals gets the same 200 payload for the same identifier.

    Design: Corner/rbac/all_five_roles_share_the_tower_read
    """
    tower = fixtures.new_tower(
        api,
        site_name="Five Roles Field",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Five Roles Radio", carrier_code="FIV")
    landlord = fixtures.new_landlord(
        api,
        legal_name="Five Roles Land",
        remit_contact_email="ap@fiveroles.example",
        w9_on_file=True,
    )

    readers = [
        ADMIN_HEADERS,
        ENGINEER_HEADERS,
        AUDITOR_HEADERS,
        make_tenant_headers(tenant["id"]),
        make_landlord_headers(landlord["id"]),
    ]
    payloads = []
    for headers in readers:
        data = validate_success(api.get_tower(tower["id"], headers), 200)
        assert data["id"] == tower["id"]
        assert_tower_capacity(
            data,
            rated_capacity_load_units=9000,
            capacity_posture="OPEN",
            reserved_load_units=0,
            available_ground_space_sqft=9000,
        )
        payloads.append(data)

    for data in payloads[1:]:
        assert data == payloads[0], "every role reads one and the same tower record"


def test_tower_read_rejects_an_unresolvable_entity_backed_identity(api):
    """PRD §2.1: "For both of these roles, if `X-User-ID` does not resolve to an
    existing row of the backing entity, the request fails with
    `ERR_IDENTITY_NOT_FOUND` (403)."

    The tower read is open to `Tenant` and `Landlord` per PRD §4, but those two
    identities are entity-backed, so a header naming no existing row is refused
    even though the tower itself exists.

    Design: Corner/rbac/all_five_roles_share_the_tower_read
    """
    tower = fixtures.new_tower(
        api,
        site_name="Five Roles Field Identity",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )

    validate_error(
        api.get_tower(tower["id"], UNRESOLVABLE_TENANT_HEADERS), ERR_IDENTITY_NOT_FOUND, 403
    )
    validate_error(
        api.get_tower(tower["id"], UNRESOLVABLE_LANDLORD_HEADERS), ERR_IDENTITY_NOT_FOUND, 403
    )

    still_readable = validate_success(api.get_tower(tower["id"], ADMIN_HEADERS), 200)
    assert still_readable["id"] == tower["id"]
    assert still_readable["version"] == tower["version"], "the refusals mutated nothing"


# ─────────────────────────────────────────────────────────────────────────────
# Segregation of duties on certification
# ─────────────────────────────────────────────────────────────────────────────


def test_originating_engineer_cannot_certify_its_own_reinforcement(api):
    """PRD §3.6: "Certification enforces segregation of duties: the acting
    `X-User-ID` must differ from the project's `proposing_engineer_user_id`
    **and** from the `engineer_user_id` of the originating structural analysis,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    One engineer authored the analysis and proposed the project, so that
    engineer cannot sign the work off despite holding the right role, while a
    second engineer certifies and lifts the freeze of PRD §2.8.

    Design: Corner/rbac/segregation_of_duties_blocks_originating_engineer_from_certifying
    """
    tower = fixtures.new_tower(
        api,
        site_name="Duty Split Summit",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=1000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
        baseline_reserved_load_units=900,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Duty Split Cellular", "carrier_code": "SOD"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant, mla = carrier["tenant"], carrier["mla"]

    application = fixtures.new_application(
        api,
        tower["id"],
        mla["id"],
        tenant["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        equipment_type="ANTENNA",
        model_code="SD-60",
        quantity=1,
        unit_weight_lbs=60,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, application["id"], tenant["id"])

    analysis = fixtures.run_analysis(
        api, application["id"], tower["id"], "PRELIMINARY", ENGINEER_HEADERS
    )
    assert_analysis_outcome(
        analysis,
        included_load_units=960.0,
        projected_loading_pct=96.0,
        result="MODIFICATION_REQUIRED",
    )
    assert analysis["engineer_user_id"] == ENGINEER_USER_ID
    fixtures.quote_analysis(api, analysis["id"], 1000000, ENGINEER_HEADERS)

    project = fixtures.propose_project(
        api,
        tower["id"],
        analysis["id"],
        ENGINEER_HEADERS,
        construction_window_start_date="2026-09-01",
        construction_window_end_date="2026-10-31",
        allocation_basis="PRO_RATA_LOAD",
    )
    assert project["proposing_engineer_user_id"] == ENGINEER_USER_ID
    fixtures.allocate_shares(api, project["id"], ENGINEER_HEADERS)
    share = fixtures.share_for_tenant(api, project["id"], tenant["id"])
    assert_cents(share["share_cents"], 1120000, "share_cents")
    fixtures.accept_share(api, share["id"], tenant["id"])
    assert fixtures.read_project(api, project["id"])["status"] == "FUNDED"

    fixtures.advance_clock(api, "2026-09-01T00:00:00Z")
    validate_success(api.start_construction(project["id"], {}, ENGINEER_HEADERS), 200)

    refused = api.certify_completion(
        project["id"], factories.certify_completion_payload(500), ENGINEER_HEADERS
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    still_building = fixtures.read_project(api, project["id"])
    assert still_building["status"] == "IN_CONSTRUCTION"
    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]),
        rated_capacity_load_units=1000,
        reserved_load_units=900.0,
        capacity_posture="FROZEN",
    )

    certified = validate_success(
        api.certify_completion(
            project["id"], factories.certify_completion_payload(500), OTHER_ENGINEER_HEADERS
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == OTHER_ENGINEER_USER_ID

    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]),
        rated_capacity_load_units=1500,
        reserved_load_units=900.0,
        reserved_load_pct=60.0,
        available_ground_space_sqft=9000,
        capacity_posture="OPEN",
    )
