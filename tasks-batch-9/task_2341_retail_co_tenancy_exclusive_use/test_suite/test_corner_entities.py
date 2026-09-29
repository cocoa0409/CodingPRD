"""Entity-level tests for the retail co-tenancy API.

Covers record creation and echoed inputs, declared defaults, computed and
server-minted fields, schema rejections, per-entity path and foreign-key
resolution, the self-referential lease link, single-record reads and the
filtered collection reads with their pagination defaults.
"""
from test_helpers import (
    DEFAULT_LIMIT,
    DEFAULT_OCCUPANCY_GRACE_DAYS,
    DEFAULT_OFFSET,
    ERR_CENTER_NOT_FOUND,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_CLAUSE_NOT_FOUND,
    ERR_CONDITION_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_ELECTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LEASE_NOT_FOUND,
    ERR_MEASUREMENT_NOT_FOUND,
    ERR_NOTICE_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_REQUIREMENT_NOT_FOUND,
    ERR_RESTRICTION_NOT_FOUND,
    ERR_TENANT_NOT_FOUND,
    add_anchor_requirement,
    add_clause,
    add_condition,
    add_radius_restriction,
    assert_anchor_requirement_shape,
    assert_center_quantities,
    assert_center_shape,
    assert_condition_shape,
    assert_lease_dimensions,
    assert_lease_shape,
    assert_null,
    assert_pagination_meta,
    assert_pct,
    assert_tenant_shape,
    create_center,
    create_lease_for_new_tenant,
    create_tenant,
    draft_lease,
    execute_lease,
    factories,
    fetch_center,
    get_success_data,
    ids_of,
    is_valid_uuid,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    open_lease,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"
CLIENT_SUPPLIED_ID = "11111111-1111-4111-8111-111111111111"

# The five suites of the Northgate Crossing fixture: two anchor boxes and three
# inline suites, 255,000 sqft of 300,000 counted once every store is open.
NORTHGATE_SUITES = (
    {
        "suite_code": "A1",
        "gla_sqft": 120000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "DISCOUNT_DEPT",
        "base_rent_monthly_cents": 6000000,
        "tenant_legal_name": "Boxmart Retail Inc",
        "is_national_chain": True,
    },
    {
        "suite_code": "A2",
        "gla_sqft": 100000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "GROCERY",
        "base_rent_monthly_cents": 4000000,
        "tenant_legal_name": "Grocerway Foods LLC",
        "is_national_chain": True,
    },
    {
        "suite_code": "I1",
        "gla_sqft": 2000,
        "parcel_kind": "INLINE",
        "primary_use_code": "COFFEE",
        "base_rent_monthly_cents": 1000000,
        "tenant_legal_name": "Bean Theory Coffee LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I2",
        "gla_sqft": 3000,
        "parcel_kind": "INLINE",
        "primary_use_code": "BOOKS",
        "base_rent_monthly_cents": 1200000,
        "tenant_legal_name": "Margin Books LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I3",
        "gla_sqft": 30000,
        "parcel_kind": "INLINE",
        "primary_use_code": "FITNESS",
        "base_rent_monthly_cents": 1500000,
        "tenant_legal_name": "Pulse Fitness Group",
        "is_national_chain": True,
    },
)


def _northgate(api):
    """Stand up Northgate Crossing with all five suites drafted, executed, opened."""
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    leases = {}
    tenants = {}
    for spec in NORTHGATE_SUITES:
        spec = dict(spec)
        suite_code = spec.pop("suite_code")
        lease, tenant = create_lease_for_new_tenant(
            api,
            center["id"],
            suite_code,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
            state="DRAFT",
            **spec,
        )
        leases[suite_code] = lease
        tenants[suite_code] = tenant
    suite_codes = list(leases)
    for suite_code in suite_codes:
        execute_lease(api, leases[suite_code]["id"])
    for suite_code in suite_codes:
        leases[suite_code] = open_lease(api, leases[suite_code]["id"])
    return center, leases, tenants


def _northgate_condition(api, lease_id):
    """The ONGOING GLA_PCT condition benefiting suite I1 at 81.67 pct."""
    return add_condition(
        api,
        lease_id,
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )


def _optical_center_and_tenant(api):
    """A center plus one tenant, the minimum a lease draft needs."""
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    tenant = create_tenant(
        api,
        legal_name="Halcyon Optical LLC",
        notice_email="legal@halcyonoptical.example",
        primary_use_code="OPTICAL",
        is_national_chain=False,
    )
    return center, tenant


# --------------------------------------------------------------------------
# Centers
# --------------------------------------------------------------------------
def test_center_creation_returns_all_declared_fields(api):
    """A freshly registered center exposes every declared field at its initial value.

    PRD: "A newly registered center starts with `occupied_gla_sqft` at 0, `open_occupancy_pct` at 0.00, `operating_store_count`, `open_anchor_count`, `protected_exclusive_count`, and `open_violation_count` all at 0, `aggregate_effective_rent_cents` at 0, `compliance_posture` at `COMPLIANT`, `redevelopment_status` at `NONE`, `last_sweep_at` at null, and `version` at 1."

    Design: Corner/entities/center_creation_returns_all_declared_fields
    """
    set_clock(api, CLOCK)

    res = api.create_center(
        factories.center_payload(
            name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
        ),
        make_asset_manager_headers(),
    )
    center = validate_success(res, 201)

    assert res.json()["response_type"] == "object"
    assert_center_shape(center)
    assert center["name"] == "Northgate Crossing"
    assert center["total_gla_sqft"] == 300000
    assert center["occupancy_grace_days"] == 30
    assert_center_quantities(
        center,
        occupied_gla_sqft=0,
        open_occupancy_pct=0.00,
        operating_store_count=0,
        open_anchor_count=0,
        protected_exclusive_count=0,
        aggregate_effective_rent_cents=0,
        open_violation_count=0,
        compliance_posture="COMPLIANT",
        redevelopment_status="NONE",
    )
    assert_null(center["last_sweep_at"], "last_sweep_at")
    assert center["version"] == 1


def test_center_omitted_occupancy_grace_days_defaults_to_ninety(api):
    """Omitting occupancy_grace_days stores the declared default of 90 days.

    PRD: "An `AssetManager` registers a shopping center by supplying its legal `name` and its `total_gla_sqft`, optionally overriding `occupancy_grace_days`, which defaults to 90 days when omitted."

    Design: Corner/entities/center_omitted_occupancy_grace_days_defaults_to_ninety
    """
    set_clock(api, CLOCK)

    res = api.create_center(
        factories.center_payload(name="Riverbend Commons", total_gla_sqft=250000),
        make_asset_manager_headers(),
    )
    center = validate_success(res, 201)

    assert center["occupancy_grace_days"] == DEFAULT_OCCUPANCY_GRACE_DAYS
    assert center["total_gla_sqft"] == 250000
    assert center["compliance_posture"] == "COMPLIANT"


# --------------------------------------------------------------------------
# Tenants
# --------------------------------------------------------------------------
def test_tenant_omitted_is_national_chain_defaults_to_false(api):
    """A tenant registered without is_national_chain lands on false.

    PRD: "The abstracting flag `is_national_chain` defaults to false and marks the tenants who most often hold radius restrictions."

    Design: Corner/entities/tenant_omitted_optionals_default_to_active_and_not_national
    """
    set_clock(api, CLOCK)

    res = api.create_tenant(
        factories.tenant_payload(
            legal_name="Halcyon Optical LLC",
            notice_email="legal@halcyonoptical.example",
            primary_use_code="OPTICAL",
        ),
        make_lease_administrator_headers(),
    )
    tenant = validate_success(res, 201)

    assert_tenant_shape(tenant)
    assert tenant["is_national_chain"] is False
    assert tenant["primary_use_code"] == "OPTICAL"
    assert tenant["version"] == 1


def test_tenant_credit_status_starts_active(api):
    """A tenant's credit status starts at ACTIVE without the client naming it.

    PRD: "A tenant's credit `status` starts at `ACTIVE` and may later be moved to `DEFAULTED` or `BANKRUPT`; the counting consequences of each are in §2.5, and the consequences of moving it are in §3.3."

    Design: Corner/entities/tenant_omitted_optionals_default_to_active_and_not_national
    """
    set_clock(api, CLOCK)

    res = api.create_tenant(
        factories.tenant_payload(
            legal_name="Halcyon Optical LLC",
            notice_email="legal@halcyonoptical.example",
            primary_use_code="OPTICAL",
        ),
        make_lease_administrator_headers(),
    )
    tenant = validate_success(res, 201)

    assert tenant["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Lease drafting: required fields, enums, computed and server-minted fields
# --------------------------------------------------------------------------
def test_lease_missing_required_gla_sqft_returns_invalid_request(api):
    """Drafting a lease without gla_sqft is a schema rejection that stores nothing.

    PRD: "Schema — every required body field present with its declared type, every enum field carrying a declared member, every percentage between 0 and 100 inclusive, every `_cents` field a non-negative integer, and every date a well-formed ISO 8601 calendar date. `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/lease_missing_required_gla_sqft_returns_invalid_request
    """
    center, tenant = _optical_center_and_tenant(api)

    res = api.create_lease(
        center["id"],
        factories.lease_payload(
            tenant_id=tenant["id"],
            suite_code="I9",
            gla_sqft=None,
            parcel_kind="INLINE",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
        ),
        make_lease_administrator_headers(),
    )
    validate_error(res, ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_leases(make_lease_administrator_headers(), {"center_id": center["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fetch_center(api, center["id"])["occupied_gla_sqft"] == 0


def test_lease_invalid_parcel_kind_enum_rejected(api):
    """An undeclared parcel_kind member is refused rather than coerced.

    PRD: "Schema — every required body field present with its declared type, every enum field carrying a declared member, every percentage between 0 and 100 inclusive, every `_cents` field a non-negative integer, and every date a well-formed ISO 8601 calendar date. `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/lease_invalid_parcel_kind_enum_rejected
    """
    center, tenant = _optical_center_and_tenant(api)

    res = api.create_lease(
        center["id"],
        factories.lease_payload(
            tenant_id=tenant["id"],
            suite_code="I9",
            gla_sqft=2200,
            parcel_kind="OUTPARCEL",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
        ),
        make_lease_administrator_headers(),
    )
    validate_error(res, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_leases(make_lease_administrator_headers(), {"center_id": center["id"]})
    )
    assert meta["total_count"] == 0


def test_lease_is_anchor_computed_from_parcel_kind(api):
    """is_anchor is true exactly for an ANCHOR_BOX parcel and false for a PAD.

    PRD: "It is derived as true exactly when `parcel_kind` is `ANCHOR_BOX`, and any value a client supplies for it is discarded."

    Design: Corner/entities/lease_is_anchor_computed_from_parcel_kind
    """
    set_clock(api, CLOCK)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    box_tenant = create_tenant(
        api,
        legal_name="Boxmart Retail Inc",
        notice_email="legal@boxmart.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    pad_tenant = create_tenant(
        api,
        legal_name="Fuelstop Pads LLC",
        notice_email="legal@fuelstop.example",
        primary_use_code="FUEL",
        is_national_chain=True,
    )

    box_lease = draft_lease(
        api,
        center["id"],
        box_tenant["id"],
        suite_code="A1",
        gla_sqft=120000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=6000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    pad_lease = draft_lease(
        api,
        center["id"],
        pad_tenant["id"],
        suite_code="P1",
        gla_sqft=4000,
        parcel_kind="PAD",
        primary_use_code="FUEL",
        base_rent_monthly_cents=900000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )

    assert box_lease["is_anchor"] is True
    assert pad_lease["is_anchor"] is False


def test_drafted_lease_starts_with_declared_initial_state(api):
    """A drafted lease starts DRAFT/NONE/CLEAR with effective rent equal to base rent.

    PRD: "A drafted lease starts with `premises_status` at `DRAFT`, `remedy_status` at `NONE`, `use_compliance_status` at `CLEAR`, `effective_rent_monthly_cents` equal to `base_rent_monthly_cents`, `total_abated_cents` at 0, and `opened_at`, `dark_since`, and `remedy_eligible_at` all null."

    Design: Corner/entities/lease_is_anchor_computed_from_parcel_kind
    """
    set_clock(api, CLOCK)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    box_tenant = create_tenant(
        api,
        legal_name="Boxmart Retail Inc",
        notice_email="legal@boxmart.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    pad_tenant = create_tenant(
        api,
        legal_name="Fuelstop Pads LLC",
        notice_email="legal@fuelstop.example",
        primary_use_code="FUEL",
        is_national_chain=True,
    )

    box_lease = draft_lease(
        api,
        center["id"],
        box_tenant["id"],
        suite_code="A1",
        gla_sqft=120000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=6000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    pad_lease = draft_lease(
        api,
        center["id"],
        pad_tenant["id"],
        suite_code="P1",
        gla_sqft=4000,
        parcel_kind="PAD",
        primary_use_code="FUEL",
        base_rent_monthly_cents=900000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )

    assert_lease_shape(box_lease)
    assert_lease_dimensions(
        box_lease,
        premises_status="DRAFT",
        remedy_status="NONE",
        use_compliance_status="CLEAR",
        effective_rent_monthly_cents=6000000,
        total_abated_cents=0,
    )
    assert_null(box_lease["opened_at"], "opened_at")
    assert_null(box_lease["dark_since"], "dark_since")
    assert_null(box_lease["remedy_eligible_at"], "remedy_eligible_at")
    assert pad_lease["effective_rent_monthly_cents"] == 900000


def test_lease_id_and_version_are_server_minted(api):
    """A client-supplied id and version do not become the stored identity.

    PRD: "Every persisted record exposes an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits."

    Design: Corner/entities/lease_system_fields_generated_and_client_input_ignored
    """
    center, tenant = _optical_center_and_tenant(api)

    res = api.create_lease(
        center["id"],
        factories.lease_payload(
            tenant_id=tenant["id"],
            suite_code="I9",
            gla_sqft=2200,
            parcel_kind="INLINE",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
            id=CLIENT_SUPPLIED_ID,
            version=77,
            premises_status="OPEN",
            total_abated_cents=999999,
        ),
        make_lease_administrator_headers(),
    )
    lease = validate_success(res, 201)

    assert lease["id"] != CLIENT_SUPPLIED_ID
    assert is_valid_uuid(lease["id"])
    assert lease["version"] == 1


def test_lease_client_supplied_premises_status_is_ignored(api):
    """A client-supplied premises_status and total_abated_cents are discarded.

    PRD: "A drafted lease starts with `premises_status` at `DRAFT`, `remedy_status` at `NONE`, `use_compliance_status` at `CLEAR`, `effective_rent_monthly_cents` equal to `base_rent_monthly_cents`, `total_abated_cents` at 0, and `opened_at`, `dark_since`, and `remedy_eligible_at` all null."

    Design: Corner/entities/lease_system_fields_generated_and_client_input_ignored
    """
    center, tenant = _optical_center_and_tenant(api)

    res = api.create_lease(
        center["id"],
        factories.lease_payload(
            tenant_id=tenant["id"],
            suite_code="I9",
            gla_sqft=2200,
            parcel_kind="INLINE",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
            id=CLIENT_SUPPLIED_ID,
            version=77,
            premises_status="OPEN",
            total_abated_cents=999999,
        ),
        make_lease_administrator_headers(),
    )
    lease = validate_success(res, 201)

    assert_lease_dimensions(lease, premises_status="DRAFT", total_abated_cents=0)


def test_lease_creation_with_unknown_tenant_returns_tenant_not_found(api):
    """An unresolvable tenant_id in the body answers the tenant's own 404 code.

    PRD: "Body foreign-key existence — every foreign key supplied in a body resolves, covering `tenant_id`, `condition_id`, `source_notice_id`, `clause_id`, `radius_restriction_id`, `measurement_id`, `anchor_lease_id`, `replacement_for_lease_id`, and `pad_parcel_lease_id`. The per-entity 404 above."

    Design: Corner/entities/lease_creation_with_unknown_tenant_returns_tenant_not_found
    """
    set_clock(api, CLOCK)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )

    res = api.create_lease(
        center["id"],
        factories.lease_payload(
            tenant_id=UNKNOWN_ID,
            suite_code="I9",
            gla_sqft=2200,
            parcel_kind="INLINE",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
        ),
        make_lease_administrator_headers(),
    )
    validate_error(res, ERR_TENANT_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_leases(make_lease_administrator_headers(), {"center_id": center["id"]})
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Exclusive-use clause schema bound
# --------------------------------------------------------------------------
def test_clause_incidental_cap_above_one_hundred_returns_invalid_request(api):
    """A clause whose incidental_sales_pct_cap exceeds 100 is a schema rejection.

    PRD: "Schema — every required body field present with its declared type, every enum field carrying a declared member, every percentage between 0 and 100 inclusive, every `_cents` field a non-negative integer, and every date a well-formed ISO 8601 calendar date. `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/clause_incidental_cap_above_one_hundred_returns_invalid_request
    """
    center, leases, _ = _northgate(api)

    res = api.create_clause(
        leases["I2"]["id"],
        factories.clause_payload(
            protected_use_codes=["BOOKS"],
            exclusivity_scope="CENTER_WIDE",
            gla_carve_out_sqft=0,
            incidental_sales_pct_cap=120.0,
            effective_from_date="2026-01-01",
            effective_through_date="2036-12-31",
        ),
        make_lease_administrator_headers(),
    )
    validate_error(res, ERR_INVALID_REQUEST, 400)

    assert fetch_center(api, center["id"])["protected_exclusive_count"] == 0


# --------------------------------------------------------------------------
# Anchor requirements: the one immutable record
# --------------------------------------------------------------------------
def test_anchor_requirement_creation_echoes_declared_fields(api):
    """Naming an anchor stores the requirement's declared inputs verbatim.

    PRD: "A `LeaseAdministrator` adds such a requirement by supplying `anchor_lease_id` — which must belong to a lease whose `parcel_kind` is `ANCHOR_BOX` in the same center as the condition's benefited lease — together with `substitution_allowed` and `min_substitute_gla_sqft` (at least 0)."

    Design: Corner/entities/anchor_requirement_is_immutable_and_carries_no_version
    """
    _, leases, _ = _northgate(api)
    condition = _northgate_condition(api, leases["I1"]["id"])

    res = api.create_anchor_requirement(
        condition["id"],
        factories.anchor_requirement_payload(
            anchor_lease_id=leases["A1"]["id"],
            substitution_allowed=True,
            min_substitute_gla_sqft=100000,
        ),
        make_lease_administrator_headers(),
    )
    requirement = validate_success(res, 201)

    assert requirement["condition_id"] == condition["id"]
    assert requirement["anchor_lease_id"] == leases["A1"]["id"]
    assert requirement["substitution_allowed"] is True
    assert requirement["min_substitute_gla_sqft"] == 100000


def test_anchor_requirement_read_carries_no_version_or_updated_at(api):
    """A stored anchor requirement exposes id and created_at but no version or updated_at.

    PRD: "The one exception is the `AnchorRequirement` record, which is immutable after creation: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it."

    Design: Corner/entities/anchor_requirement_is_immutable_and_carries_no_version
    """
    _, leases, _ = _northgate(api)
    condition = _northgate_condition(api, leases["I1"]["id"])
    requirement = add_anchor_requirement(
        api,
        condition["id"],
        leases["A1"]["id"],
        substitution_allowed=True,
        min_substitute_gla_sqft=100000,
    )

    stored = get_success_data(
        api.get_anchor_requirement(requirement["id"], make_lender_rep_headers()), 200
    )

    assert_anchor_requirement_shape(stored)
    assert "version" not in stored
    assert "updated_at" not in stored


# --------------------------------------------------------------------------
# The self-referential lease link
# --------------------------------------------------------------------------
def test_lease_self_referential_replacement_link_is_stored(api):
    """A replacement lease stores the id of the lease it displaces.

    PRD: "During a redevelopment a new lease may point back at the lease it displaces through `replacement_for_lease_id`, which is null for original leases and makes the lease graph self-referential."

    Design: Corner/entities/lease_self_referential_replacement_link_is_stored_and_filterable
    """
    _, leases, _ = _northgate(api)
    center_id = leases["I3"]["center_id"]
    replacement_tenant = create_tenant(
        api,
        legal_name="Northline Athletics LLC",
        notice_email="legal@northline.example",
        primary_use_code="FITNESS",
        is_national_chain=False,
    )

    replacement = draft_lease(
        api,
        center_id,
        replacement_tenant["id"],
        suite_code="I7",
        gla_sqft=28000,
        parcel_kind="INLINE",
        primary_use_code="FITNESS",
        base_rent_monthly_cents=1400000,
        commencement_date="2026-10-01",
        expiration_date="2036-09-30",
        replacement_for_lease_id=leases["I3"]["id"],
    )

    assert replacement["replacement_for_lease_id"] == leases["I3"]["id"]
    assert replacement["premises_status"] == "DRAFT"
    assert leases["I3"]["replacement_for_lease_id"] is None


def test_leases_filter_by_replacement_for_lease_id(api):
    """Listing leases filtered on replacement_for_lease_id returns only the successor.

    PRD: "List endpoints accept the query parameters named in §3 alongside `limit` and `offset`: centers filter on `compliance_posture`; leases on `center_id`, `tenant_id`, `replacement_for_lease_id`, `premises_status`, `remedy_status`, and `parcel_kind`; co-tenancy conditions on `lease_id`, `last_evaluated_measurement_id`, `condition_kind`, and `status`; anchor requirements on `condition_id` and `anchor_lease_id`; exclusive-use clauses on `lease_id`, `suspended_by_plan_id`, `status`, and `exclusivity_scope`; radius restrictions on `lease_id`, `status`, and `recapture_basis`; notices on `violating_lease_id`, `clause_id`, `radius_restriction_id`, `notice_kind`, and `status`; disputes on `notice_id`, `filed_by_tenant_id`, `status`, and `grounds_code`; elections on `lease_id`, `condition_id`, `source_notice_id`, `election_kind`, and `status`; measurements on `center_id`, `variant`, and `status`; estoppel certificates on `lease_id`, `measurement_id`, and `status`; and redevelopment plans on `center_id`, `pad_parcel_lease_id`, `plan_kind`, and `status`."

    Design: Corner/entities/lease_self_referential_replacement_link_is_stored_and_filterable
    """
    _, leases, _ = _northgate(api)
    center_id = leases["I3"]["center_id"]
    replacement_tenant = create_tenant(
        api,
        legal_name="Northline Athletics LLC",
        notice_email="legal@northline.example",
        primary_use_code="FITNESS",
        is_national_chain=False,
    )
    replacement = draft_lease(
        api,
        center_id,
        replacement_tenant["id"],
        suite_code="I7",
        gla_sqft=28000,
        parcel_kind="INLINE",
        primary_use_code="FITNESS",
        base_rent_monthly_cents=1400000,
        commencement_date="2026-10-01",
        expiration_date="2036-09-30",
        replacement_for_lease_id=leases["I3"]["id"],
    )

    rows, meta = validate_paginated(
        api.list_leases(
            make_lease_administrator_headers(),
            {"replacement_for_lease_id": leases["I3"]["id"]},
        )
    )

    assert meta["total_count"] == 1
    assert ids_of(rows) == [replacement["id"]]


# --------------------------------------------------------------------------
# Path resolution across every single-record read
# --------------------------------------------------------------------------
def test_every_entity_read_with_unknown_id_returns_its_not_found_error(api):
    """Each single-entity read answers its own per-entity 404 for an unknown id.

    PRD: "Resolution failures are 404s and are named per entity: `ERR_CENTER_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_CONDITION_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`, `ERR_CLAUSE_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_PLAN_NOT_FOUND`."

    Design: Corner/entities/every_entity_read_with_unknown_id_returns_its_not_found_error
    """
    set_clock(api, CLOCK)
    lease_admin = make_lease_administrator_headers()
    asset_manager = make_asset_manager_headers()
    enforcer = make_compliance_officer_headers("co-enforce-1")
    analyst = make_compliance_officer_headers("co-analyst-1")
    lender = make_lender_rep_headers()

    probes = (
        (api.get_center(UNKNOWN_ID, asset_manager), ERR_CENTER_NOT_FOUND),
        (api.get_tenant(UNKNOWN_ID, lease_admin), ERR_TENANT_NOT_FOUND),
        (api.get_lease(UNKNOWN_ID, lease_admin), ERR_LEASE_NOT_FOUND),
        (api.get_condition(UNKNOWN_ID, lease_admin), ERR_CONDITION_NOT_FOUND),
        (api.get_anchor_requirement(UNKNOWN_ID, lease_admin), ERR_REQUIREMENT_NOT_FOUND),
        (api.get_clause(UNKNOWN_ID, lease_admin), ERR_CLAUSE_NOT_FOUND),
        (api.get_radius_restriction(UNKNOWN_ID, lease_admin), ERR_RESTRICTION_NOT_FOUND),
        (api.get_notice(UNKNOWN_ID, enforcer), ERR_NOTICE_NOT_FOUND),
        (api.get_dispute(UNKNOWN_ID, enforcer), ERR_DISPUTE_NOT_FOUND),
        (api.get_election(UNKNOWN_ID, asset_manager), ERR_ELECTION_NOT_FOUND),
        (api.get_measurement(UNKNOWN_ID, analyst), ERR_MEASUREMENT_NOT_FOUND),
        (api.get_certificate(UNKNOWN_ID, lender), ERR_CERTIFICATE_NOT_FOUND),
        (api.get_plan(UNKNOWN_ID, asset_manager), ERR_PLAN_NOT_FOUND),
    )

    for response, expected_error in probes:
        validate_error(response, expected_error, 404)
        assert response.json()["response_type"] == "error"


# --------------------------------------------------------------------------
# Co-tenancy condition reads
# --------------------------------------------------------------------------
def test_condition_retrieval_returns_stored_thresholds(api):
    """A GLA_PCT condition stores its occupancy threshold and no store-count threshold.

    PRD: "Exactly one threshold field is mandatory and the other must be omitted: a `GLA_PCT` condition requires `required_occupancy_pct` (greater than 0 and at most 100) and must not carry `required_open_store_count`; a `STORE_COUNT` condition requires `required_open_store_count` of at least 1 and must not carry `required_occupancy_pct`."

    Design: Corner/entities/condition_retrieval_returns_stored_and_computed_fields
    """
    _, leases, _ = _northgate(api)
    condition = _northgate_condition(api, leases["I1"]["id"])

    stored = get_success_data(
        api.get_condition(condition["id"], make_lender_rep_headers()), 200
    )

    assert_condition_shape(stored)
    assert stored["lease_id"] == leases["I1"]["id"]
    assert stored["condition_kind"] == "ONGOING"
    assert stored["measurement_basis"] == "GLA_PCT"
    assert_pct(stored["required_occupancy_pct"], 81.67, "required_occupancy_pct")
    assert_null(stored["required_open_store_count"], "required_open_store_count")
    assert stored["required_anchor_count"] == 2
    assert stored["grace_period_days"] == 0
    assert stored["cure_period_days"] == 30
    assert_pct(stored["max_reduction_pct"], 25.0, "max_reduction_pct")


def test_condition_is_evaluated_immediately_at_creation(api):
    """A condition met by the live strict figures reads SATISFIED the instant it exists.

    PRD: "A condition is **evaluated immediately at creation** under the live strict engine, so its `status` is either `SATISFIED` or `BREACHED` the instant it exists — there is no pending or unevaluated state."

    Design: Corner/entities/condition_retrieval_returns_stored_and_computed_fields
    """
    center, leases, _ = _northgate(api)
    assert_pct(
        fetch_center(api, center["id"])["open_occupancy_pct"], 85.00, "open_occupancy_pct"
    )
    condition = _northgate_condition(api, leases["I1"]["id"])

    stored = get_success_data(
        api.get_condition(condition["id"], make_lender_rep_headers()), 200
    )

    assert stored["status"] == "SATISFIED"
    assert_null(stored["breach_detected_at"], "breach_detected_at")
    assert stored["consecutive_breach_days"] == 0
    assert_null(
        stored["last_evaluated_measurement_id"], "last_evaluated_measurement_id"
    )


# --------------------------------------------------------------------------
# Collection reads
# --------------------------------------------------------------------------
def _northgate_with_protections(api):
    """Northgate plus a condition, an anchor requirement, a clause and a restriction."""
    center, leases, tenants = _northgate(api)
    condition = _northgate_condition(api, leases["I1"]["id"])
    requirement = add_anchor_requirement(
        api,
        condition["id"],
        leases["A1"]["id"],
        substitution_allowed=False,
        min_substitute_gla_sqft=0,
    )
    clause = add_clause(
        api,
        leases["I1"]["id"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    restriction = add_radius_restriction(
        api,
        leases["I3"]["id"],
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="GROSS_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    return center, leases, condition, requirement, clause, restriction


def test_collection_reads_apply_their_declared_filters(api):
    """Each collection route narrows its result set by the filters §4 declares for it.

    PRD: "List endpoints accept the query parameters named in §3 alongside `limit` and `offset`: centers filter on `compliance_posture`; leases on `center_id`, `tenant_id`, `replacement_for_lease_id`, `premises_status`, `remedy_status`, and `parcel_kind`; co-tenancy conditions on `lease_id`, `last_evaluated_measurement_id`, `condition_kind`, and `status`; anchor requirements on `condition_id` and `anchor_lease_id`; exclusive-use clauses on `lease_id`, `suspended_by_plan_id`, `status`, and `exclusivity_scope`; radius restrictions on `lease_id`, `status`, and `recapture_basis`; notices on `violating_lease_id`, `clause_id`, `radius_restriction_id`, `notice_kind`, and `status`; disputes on `notice_id`, `filed_by_tenant_id`, `status`, and `grounds_code`; elections on `lease_id`, `condition_id`, `source_notice_id`, `election_kind`, and `status`; measurements on `center_id`, `variant`, and `status`; estoppel certificates on `lease_id`, `measurement_id`, and `status`; and redevelopment plans on `center_id`, `pad_parcel_lease_id`, `plan_kind`, and `status`."

    Design: Corner/entities/collection_reads_honour_declared_filters_and_pagination_defaults
    """
    center, leases, condition, requirement, clause, restriction = (
        _northgate_with_protections(api)
    )
    headers = make_asset_manager_headers()

    centers, centers_meta = validate_paginated(
        api.list_centers(headers, {"compliance_posture": "COMPLIANT"})
    )
    conditions, conditions_meta = validate_paginated(
        api.list_conditions(
            headers, {"lease_id": leases["I1"]["id"], "status": "SATISFIED"}
        )
    )
    requirements, requirements_meta = validate_paginated(
        api.list_anchor_requirements(headers, {"condition_id": condition["id"]})
    )
    clauses, clauses_meta = validate_paginated(
        api.list_clauses(headers, {"lease_id": leases["I1"]["id"], "status": "ACTIVE"})
    )
    restrictions, restrictions_meta = validate_paginated(
        api.list_radius_restrictions(
            headers, {"lease_id": leases["I3"]["id"], "recapture_basis": "GROSS_SALES"}
        )
    )

    assert centers_meta["total_count"] == 1
    assert ids_of(centers) == [center["id"]]
    assert conditions_meta["total_count"] == 1
    assert ids_of(conditions) == [condition["id"]]
    assert requirements_meta["total_count"] == 1
    assert ids_of(requirements) == [requirement["id"]]
    assert clauses_meta["total_count"] == 1
    assert ids_of(clauses) == [clause["id"]]
    assert restrictions_meta["total_count"] == 1
    assert ids_of(restrictions) == [restriction["id"]]


def test_collection_reads_default_to_limit_ten_and_offset_zero(api):
    """A listing with no pagination parameters falls back to limit 10 and offset 0.

    PRD: "`limit` caps the number of records returned; it defaults to 10, accepts a minimum of 1 and a maximum of 100."

    Design: Corner/entities/collection_reads_honour_declared_filters_and_pagination_defaults
    """
    _, leases, condition, _, _, _ = _northgate_with_protections(api)
    headers = make_asset_manager_headers()

    responses = (
        api.list_centers(headers, {"compliance_posture": "COMPLIANT"}),
        api.list_conditions(
            headers, {"lease_id": leases["I1"]["id"], "status": "SATISFIED"}
        ),
        api.list_anchor_requirements(headers, {"condition_id": condition["id"]}),
        api.list_clauses(headers, {"lease_id": leases["I1"]["id"], "status": "ACTIVE"}),
        api.list_radius_restrictions(
            headers, {"lease_id": leases["I3"]["id"], "recapture_basis": "GROSS_SALES"}
        ),
    )

    for response in responses:
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert_pagination_meta(
            meta,
            expected_total=1,
            expected_limit=DEFAULT_LIMIT,
            expected_offset=DEFAULT_OFFSET,
            expected_has_more=False,
        )
        assert len(rows) == 1
