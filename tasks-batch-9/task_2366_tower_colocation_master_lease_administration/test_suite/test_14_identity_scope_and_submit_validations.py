"""Identity, ownership scope and the submit/execute rungs of the ladder.

Covers the header contract and entity-backed identity resolution of PRD §2.1,
the pagination bounds of PRD §2.3, and the places where the ordered ladder of
PRD §2.6 decides which of two simultaneous violations a caller is told about —
the master-lease and elevation rules on application submit (PRD §3.4) and the
post-execution structural-loading limit on amendment execution (PRD §3.7).
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ELEVATION_OUT_OF_RANGE,
    ERR_IDENTITY_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_LANDLORD_SCOPE_VIOLATION,
    ERR_MLA_NOT_ACTIVE,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STRUCTURAL_CAPACITY_EXCEEDED,
    ERR_TENANT_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_list_meta,
    assert_load_units,
    assert_tower_capacity,
)
from test_helpers.constants import (
    CLOCK_COLD_START_UTC,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
    STANDARD_REVIEW_DAYS,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    MISSING_ROLE_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    UNRESOLVABLE_TENANT_HEADERS,
    make_landlord_headers,
    make_tenant_headers,
)

# The logical clock is fixed at its cold-start instant for every test below, so
# every stamped instant is derived from it (PRD §2.4).
COLD_START_PREFIX = CLOCK_COLD_START_UTC[: len("2026-08-01T00:00:00")]


# ─────────────────────────────────────────────────────────────────────────────
# The two request headers (PRD §2.1)
# ─────────────────────────────────────────────────────────────────────────────


def test_read_without_a_role_header_is_rejected_before_the_tower_is_resolved(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (401)
    before anything else is examined."

    The path names a tower id that does not exist, so an authenticated caller
    would see a 404; the missing role header outranks that resolution entirely.

    Design: Corner/validations/missing_x_user_role_header_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Header Hill",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )

    resp = api.get_tower(NON_EXISTENT_UUID, MISSING_ROLE_HEADERS)

    validate_error(resp, ERR_UNAUTHENTICATED, 401)
    assert resp.json()["response_type"] == "error"

    # The registered tower is untouched and still readable by a declared role.
    readable = validate_success(api.get_tower(tower["id"], ADMIN_HEADERS), 200)
    assert readable["id"] == tower["id"]


def test_read_with_an_undeclared_role_string_is_rejected_as_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (401)
    before anything else is examined."

    A role string that is present but outside the declared five-role set fails
    authentication rather than the permission check that follows it.

    Design: Corner/validations/unknown_role_value_in_header_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Unknown Role Ridge",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )

    resp = api.get_tower(tower["id"], UNKNOWN_ROLE_HEADERS)

    validate_error(resp, ERR_UNAUTHENTICATED, 401)

    # The very same read succeeds for a declared role, isolating the header rule.
    validate_success(api.get_tower(tower["id"], ADMIN_HEADERS), 200)


def test_tenant_cannot_register_a_tower_even_with_a_malformed_body(api):
    """PRD §2.1: "If both headers are well formed but the acting role is not
    among the roles listed for the requested endpoint in §4, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (403)."

    The body is also malformed — `structure_type` and `ground_space_total_sqft`
    are absent — yet role authorization is evaluated first, so the caller learns
    nothing about body validity and no tower is registered.

    Design: Corner/validations/tenant_cannot_create_tower_returns_403
    """
    tenant = fixtures.new_tenant(
        api, legal_name="Role Fence Wireless", carrier_code="RFW"
    )

    payload = factories.tower_payload(
        site_name="Trespass Tower", rated_capacity_load_units=9000
    )
    payload.pop("structure_type")
    payload.pop("ground_space_total_sqft")

    resp = api.create_tower(payload, make_tenant_headers(tenant["id"]))

    validate_error(resp, ERR_ROLE_NOT_PERMITTED, 403)

    rows, meta = validate_paginated(api.list_towers({"limit": MAX_LIMIT}, ADMIN_HEADERS))
    assert_list_meta(meta, total_count=0)
    assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Pagination bounds (PRD §2.3)
# ─────────────────────────────────────────────────────────────────────────────


def test_limit_and_offset_outside_their_bounds_are_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (400)."

    A limit of 0, a limit of 101 and an offset of -1 are all rejected rather
    than clamped into range.

    Design: Corner/validations/pagination_limit_zero_rejected
    """
    fixtures.new_tower(
        api,
        site_name="Page Bound Peak",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )

    for params in ({"limit": 0}, {"limit": MAX_LIMIT + 1}, {"offset": -1}):
        validate_error(
            api.list_towers(params, ADMIN_HEADERS), ERR_INVALID_PAGINATION, 400
        )


def test_limit_at_either_end_of_its_range_is_accepted(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, has a minimum of 1 and a maximum of 100."

    Both endpoints of the range are inclusive, so a limit of 1 and a limit of
    100 each return the page rather than a pagination error.

    Design: Corner/validations/pagination_limit_zero_rejected
    """
    fixtures.new_tower(
        api,
        site_name="Page Bound Peak",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )

    rows, meta = validate_paginated(
        api.list_towers({"limit": MIN_LIMIT, "offset": DEFAULT_OFFSET}, ADMIN_HEADERS)
    )
    assert_list_meta(
        meta, limit=MIN_LIMIT, offset=DEFAULT_OFFSET, total_count=1, has_more=False
    )
    assert len(rows) == 1

    rows, meta = validate_paginated(api.list_towers({"limit": MAX_LIMIT}, ADMIN_HEADERS))
    assert_list_meta(meta, limit=MAX_LIMIT, total_count=1, has_more=False)
    assert len(rows) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Entity-backed identity resolution and ownership scope (PRD §2.1)
# ─────────────────────────────────────────────────────────────────────────────


def test_application_creation_by_an_unresolvable_tenant_identity_is_rejected(api):
    """PRD §2.1: "For both of these roles, if `X-User-ID` does not resolve to an
    existing row of the backing entity, the request fails with
    `ERR_IDENTITY_NOT_FOUND` (403)."

    Both body foreign keys resolve, so the failure is identity resolution rather
    than a 404 or the ownership-scope violation a real other tenant would get.

    Design: Corner/validations/unknown_tenant_identity_header_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Identity Notch",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Identity Notch Networks", "carrier_code": "IDN"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )

    payload = factories.colocation_application_payload(
        tower["id"],
        carrier["mla"]["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )
    resp = api.create_colocation_application(payload, UNRESOLVABLE_TENANT_HEADERS)

    validate_error(resp, ERR_IDENTITY_NOT_FOUND, 403)

    rows, meta = validate_paginated(
        api.list_colocation_applications({"limit": MAX_LIMIT}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=0)
    assert rows == []


def test_tenant_cannot_submit_another_tenants_application(api):
    """PRD §2.1: "A `Tenant` may act only on resources whose owning tenant equals
    `X-User-ID` — for colocation applications, equipment lines and site
    amendments the owning tenant is the `tenant_id` of the governing master lease
    agreement; for cost shares it is the cost share's own `tenant_id`."

    The acting tenant is a real row, so identity resolves; ownership is resolved
    through the governing master lease and the submit is refused, leaving the
    application in `DRAFT` with no `submitted_at`.

    Design: Corner/validations/tenant_cannot_submit_another_tenants_application
    """
    tower = fixtures.new_tower(
        api,
        site_name="Scope Pass Peak",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )
    owner = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Scope Alpha", "carrier_code": "SCA"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    intruder = fixtures.new_tenant(api, legal_name="Scope Bravo", carrier_code="SCB")

    application = fixtures.new_application(
        api,
        tower["id"],
        owner["mla"]["id"],
        owner["tenant"]["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        owner["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="SC-100",
        quantity=5,
        unit_weight_lbs=100,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )

    resp = api.submit_colocation_application(
        application["id"], {}, make_tenant_headers(intruder["id"])
    )

    validate_error(resp, ERR_TENANT_SCOPE_VIOLATION, 403)

    unchanged = fixtures.read_application(api, application["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert unchanged["review_deadline_at"] is None
    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]), open_review_count=0
    )

    # The owning tenant's own submit is accepted, isolating the scope rule.
    submitted = validate_success(
        api.submit_colocation_application(
            application["id"], {}, make_tenant_headers(owner["tenant"]["id"])
        ),
        200,
    )
    assert submitted["status"] == "UNDER_STRUCTURAL_REVIEW"


def _tower_with_two_landlords_and_one_lease(api):
    """A tower whose only ACTIVE ground lease is held by landlord A, plus an
    unrelated landlord B that holds nothing (PRD §3.2)."""
    tower = fixtures.new_tower(
        api,
        site_name="Landlord Scope Crest",
        rated_capacity_load_units=9000,
        ground_space_total_sqft=9000,
    )
    landlord_a = fixtures.new_landlord(
        api, legal_name="Crest Land Alpha", remit_contact_email="ap@crestalpha.example"
    )
    landlord_b = fixtures.new_landlord(
        api, legal_name="Crest Land Bravo", remit_contact_email="ap@crestbravo.example"
    )
    lease = fixtures.new_ground_lease(
        api,
        tower["id"],
        landlord_a["id"],
        base_monthly_rent_cents=300000,
        escalator_pct=2.0,
        commencement_date="2020-06-01",
        term_end_date="2031-05-31",
        renewal_option_count=1,
        renewal_term_years=5,
        buyout_price_cents=9000000,
    )
    return tower, landlord_a, landlord_b, lease


def test_landlord_cannot_list_another_landlords_ground_leases(api):
    """PRD §2.1: "A `Landlord` may read only ground leases whose `landlord_id`
    equals `X-User-ID`; a violation yields `ERR_LANDLORD_SCOPE_VIOLATION` (403)."

    Asking for another landlord's leases is refused outright rather than served
    as an empty page.

    Design: Corner/validations/landlord_cannot_list_another_landlords_ground_leases_rejected
    """
    _tower, landlord_a, landlord_b, _lease = _tower_with_two_landlords_and_one_lease(api)

    resp = api.list_ground_leases(
        {"landlord_id": landlord_a["id"]}, make_landlord_headers(landlord_b["id"])
    )

    validate_error(resp, ERR_LANDLORD_SCOPE_VIOLATION, 403)


def test_landlord_lists_its_own_ground_lease(api):
    """PRD §3.2: "Leases are listed with optional `tower_id`, `landlord_id` and
    `status` filters, and a `Landlord` reading the list sees only leases whose
    `landlord_id` matches its own identifier."

    Design: Corner/validations/landlord_cannot_list_another_landlords_ground_leases_rejected
    """
    _tower, landlord_a, _landlord_b, lease = _tower_with_two_landlords_and_one_lease(api)

    rows, meta = validate_paginated(
        api.list_ground_leases(
            {"landlord_id": landlord_a["id"]}, make_landlord_headers(landlord_a["id"])
        )
    )

    assert_list_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [lease["id"]]
    assert rows[0]["landlord_id"] == landlord_a["id"]
    assert rows[0]["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Ordering of the submit-time checks (PRD §3.4)
# ─────────────────────────────────────────────────────────────────────────────


def _carrier_with_out_of_range_band_and_drafted_lease(api):
    """An application requesting 350..380 ft on a tower that tops out at 300 ft,
    filed under a master lease that has never been activated (PRD §3.3, §3.4)."""
    tower = fixtures.new_tower(
        api,
        site_name="Not Active Notch",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(
        api, legal_name="Not Active Networks", carrier_code="MNA"
    )
    mla = fixtures.new_master_lease(
        api,
        tenant["id"],
        activate=False,
        base_monthly_rent_cents=200000,
        escalator_pct=3.0,
        initial_term_years=10,
        renewal_terms_count=1,
        expires_on="2036-07-31",
    )
    application = fixtures.new_application(
        api,
        tower["id"],
        mla["id"],
        tenant["id"],
        requested_elevation_bottom_ft=350,
        requested_elevation_top_ft=380,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        equipment_type="ANTENNA",
        model_code="MN-100",
        quantity=5,
        unit_weight_lbs=100,
        wind_area_sqft=0,
        mount_elevation_ft=360,
    )
    return tower, tenant, mla, application


def test_submit_reports_the_inactive_master_lease_before_the_elevation_range(api):
    """PRD §3.4: "Per §2.6, the two lease-state checks are evaluated before the
    elevation check, which is evaluated before the equipment-line check, which is
    evaluated before the delinquency check."

    The submit violates both the lease-state rule and the elevation rule at once,
    and the lease-state rule is the one reported.

    Design: Corner/validations/mla_not_active_outranks_elevation_out_of_range_at_submit
    """
    tower, tenant, _mla, application = _carrier_with_out_of_range_band_and_drafted_lease(
        api
    )

    resp = api.submit_colocation_application(
        application["id"], {}, make_tenant_headers(tenant["id"])
    )

    validate_error(resp, ERR_MLA_NOT_ACTIVE, 409)

    unchanged = fixtures.read_application(api, application["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]),
        reserved_load_units=0,
        open_review_count=0,
    )


def test_submit_of_a_band_above_the_tower_limit_is_rejected_once_the_lease_is_active(
    api,
):
    """PRD §2.6: "The requested band lies inside the tower's usable elevation
    range → `ERR_ELEVATION_OUT_OF_RANGE` (422), on application submit."

    With the master lease activated the lease-state rung is satisfied, and the
    same submit now trips the elevation rung instead; the application still does
    not leave `DRAFT`.

    Design: Corner/validations/mla_not_active_outranks_elevation_out_of_range_at_submit
    """
    tower, tenant, mla, application = _carrier_with_out_of_range_band_and_drafted_lease(
        api
    )

    activated = validate_success(
        api.activate_master_lease_agreement(mla["id"], {}, ADMIN_HEADERS), 200
    )
    assert activated["status"] == "ACTIVE"
    assert activated["application_privilege"] == "ENABLED"

    resp = api.submit_colocation_application(
        application["id"], {}, make_tenant_headers(tenant["id"])
    )

    validate_error(resp, ERR_ELEVATION_OUT_OF_RANGE, 422)

    unchanged = fixtures.read_application(api, application["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]),
        reserved_load_units=0,
        open_review_count=0,
    )


def test_submit_accepts_a_band_sitting_exactly_on_the_tower_limits(api):
    """PRD §3.4: "Beyond the ownership check, submission requires that the
    application has at least one equipment line, otherwise
    `ERR_NO_EQUIPMENT_LINES`; that its master lease agreement is `ACTIVE`,
    otherwise `ERR_MLA_NOT_ACTIVE`; that the master lease's
    `application_privilege` is `ENABLED`, otherwise
    `ERR_MLA_PRIVILEGE_SUSPENDED`; that the requested band lies inside the
    tower's usable range, meaning `min_colocation_elevation_ft` is at or below
    `requested_elevation_bottom_ft` and `requested_elevation_top_ft` is at or
    below `max_elevation_ft`, otherwise `ERR_ELEVATION_OUT_OF_RANGE`; and that
    the tenant's `credit_status` is `CURRENT`, otherwise `ERR_TENANT_DELINQUENT`."

    Both comparisons are inclusive, so a band that exactly equals the tower's
    usable range is admitted and, the posture being `OPEN`, branches straight
    into structural review.

    Design: Corner/validations/satisfaction_submit_passes_when_band_sits_on_tower_limits
    """
    tower = fixtures.new_tower(
        api,
        site_name="Band Limit Bluff",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={
            "legal_name": "Band Limit Broadcasting",
            "carrier_code": "BND",
        },
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    application = fixtures.new_application(
        api,
        tower["id"],
        carrier["mla"]["id"],
        carrier["tenant"]["id"],
        requested_elevation_bottom_ft=50,
        requested_elevation_top_ft=300,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        carrier["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="BD-50",
        quantity=1,
        unit_weight_lbs=50,
        wind_area_sqft=0,
        mount_elevation_ft=50,
    )

    resp = api.submit_colocation_application(
        application["id"], {}, make_tenant_headers(carrier["tenant"]["id"])
    )

    submitted = validate_success(resp, 200)
    assert submitted["status"] == "UNDER_STRUCTURAL_REVIEW"
    # One 50 lb unit mounted below 100 ft carries the 1.00 multiplier.
    assert_load_units(submitted["total_load_units"], 50.0, "total_load_units")
    # The clock is at its cold-start instant, and the standard review period of
    # 45 days lands the deadline on 2026-09-15.
    assert submitted["submitted_at"].startswith(
        COLD_START_PREFIX
    ), f"submitted_at must be stamped from the logical clock: {submitted['submitted_at']!r}"
    assert submitted["review_deadline_at"].startswith(
        "2026-09-15T00:00:00"
    ), (
        f"review_deadline_at must be submitted_at plus {STANDARD_REVIEW_DAYS} days: "
        f"{submitted['review_deadline_at']!r}"
    )
    assert_tower_capacity(fixtures.read_tower(api, tower["id"]), open_review_count=1)


# ─────────────────────────────────────────────────────────────────────────────
# Post-execution structural loading (PRD §3.7)
# ─────────────────────────────────────────────────────────────────────────────


def test_amendment_execution_rejected_when_loading_would_reach_exactly_the_limit(api):
    """PRD §2.6: "Post-execution structural loading is strictly below the
    capacity limit → `ERR_STRUCTURAL_CAPACITY_EXCEEDED` (422), on amendment
    execution."

    Each carrier holds a genuine `PASS` analysis taken while the tower was empty,
    so structural clearance exists; the guard that fires is the loading limit,
    recomputed at execution time against live reserved load. 500 plus 500 of a
    rated 1,000 is exactly 100.000 percent, and the limit is strictly-below, so
    the second execution is refused and the tower keeps 500 units reserved.

    Design: Corner/validations/amendment_execute_rejected_when_capacity_would_reach_exactly_100_pct
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Capacity Exact Edge",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Exact Edge Land",
            "remit_contact_email": "ap@exactedge.example",
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
    tower_id = site["tower"]["id"]

    # Each carrier's single line weighs 100 lbs, five off, with no wind area and
    # a mount below 100 ft, so each application carries exactly 500 load units.
    line = {
        "equipment_type": "ANTENNA",
        "model_code": "CX-100",
        "quantity": 5,
        "unit_weight_lbs": 100,
        "wind_area_sqft": 0,
        "mount_elevation_ft": 80,
    }

    first = fixtures.add_carrier_to_site(
        api,
        site,
        stage="PAPERED",
        tenant_overrides={"legal_name": "Capacity Exact Alpha", "carrier_code": "CXA"},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[line],
    )
    second = fixtures.add_carrier_to_site(
        api,
        site,
        stage="PAPERED",
        tenant_overrides={"legal_name": "Capacity Exact Bravo", "carrier_code": "CXB"},
        application_overrides={
            "requested_elevation_bottom_ft": 200,
            "requested_elevation_top_ft": 240,
            "requested_ground_space_sqft": 300,
        },
        lines=[line],
    )

    assert_load_units(first["application"]["total_load_units"], 500.0, "total_load_units")
    assert_load_units(
        second["application"]["total_load_units"], 500.0, "total_load_units"
    )

    fixtures.execute_amendment(api, first["amendment"]["id"])
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=500.0,
        reserved_load_pct=50.0,
        capacity_posture="OPEN",
    )

    resp = api.execute_site_amendment(
        second["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )

    validate_error(resp, ERR_STRUCTURAL_CAPACITY_EXCEEDED, 422)

    refused = fixtures.read_amendment(api, second["amendment"]["id"])
    assert_amendment_axes(
        refused, execution_status="DRAFT", billing_status="NOT_BILLING"
    )
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=500.0,
        reserved_load_pct=50.0,
        capacity_posture="OPEN",
        occupied_band_count=1,
    )
    assert (
        fixtures.read_master_lease(api, second["tenant"]["id"], second["mla"]["id"])[
            "executed_amendment_count"
        ]
        == 0
    )
