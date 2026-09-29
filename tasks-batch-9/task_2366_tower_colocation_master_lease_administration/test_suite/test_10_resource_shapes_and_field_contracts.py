"""Resource shapes and field contracts of the Tower Colocation Master Lease API.

These tests cover the payload contracts the PRD pins on each resource: the
derived capacity block seeded onto a tower at registration (PRD §3.1, §2.7), the
success and error envelopes and their pagination members (PRD §2.2, §2.3), the
404 codes produced by path resolution (PRD §2.5, §2.6), the defaults and
per-field constraints of towers, landlords, tenants and colocation applications
(PRD §3.1, §3.3, §3.4), the server-derived equipment-line load figure (PRD
§3.4), the reduced immutable property set of a landlord payment (PRD §2.4, §3.2)
and the cost-share rows minted for a modification project's beneficiary set
(PRD §3.6).
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LANDLORD_W9_MISSING,
    ERR_TOWER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_resource_fields,
    assert_immutable_resource_fields,
    assert_list_meta,
    assert_load_units,
    assert_pct,
    assert_tower_capacity,
)
from test_helpers.constants import ELEV_MULT_TIER_2, WIND_COEFF_LBS_PER_SQFT
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    make_landlord_headers,
    make_tenant_headers,
)


# ─── Tower registration and the derived capacity block ───────────────────────


def test_tower_registration_seeds_derived_capacity_block(api):
    """PRD §3.1: "On registration the derived picture is seeded from those
    baselines: `reserved_load_units` and `reserved_ground_space_sqft` start at
    the baseline figures, `reserved_load_pct` and `available_ground_space_sqft`
    follow from them, `occupied_elevation_bands` starts as an empty array,
    `open_review_count` starts at 0, `capacity_posture` is computed by the
    posture ladder, and the tower's `version` is initialised to 1."

    Design: Corner/entities/tower_creation_returns_201_with_derived_capacity_fields
    """
    payload = factories.tower_payload(
        site_name="Corner Ridge",
        structure_type="MONOPOLE",
        rated_capacity_load_units=10000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=20000,
        baseline_reserved_load_units=2000,
        baseline_reserved_ground_sqft=0,
    )

    tower = validate_success(api.create_tower(payload, ADMIN_HEADERS), 201)

    assert tower["site_name"] == "Corner Ridge"
    assert_tower_capacity(
        tower,
        reserved_load_units=2000.0,
        reserved_load_pct=20.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=20000,
        open_review_count=0,
        capacity_posture="OPEN",
        occupied_band_count=0,
    )
    assert tower["occupied_elevation_bands"] == []
    assert_common_resource_fields(tower)
    assert tower["version"] == 1


def test_tower_read_returns_stored_capacity_and_elevation_range(api):
    """PRD §2.7: "`reserved_load_pct` is one hundred times `reserved_load_units`
    divided by `rated_capacity_load_units`, rounded half up to three decimal
    places."

    Design: Corner/entities/tower_retrieval_returns_stored_record
    """
    tower = fixtures.new_tower(
        api,
        site_name="Read Back Hill",
        structure_type="GUYED",
        rated_capacity_load_units=7200,
        min_colocation_elevation_ft=60,
        max_elevation_ft=250,
        ground_space_total_sqft=8000,
        baseline_reserved_load_units=3000,
    )

    response = api.get_tower(tower["id"], AUDITOR_HEADERS)

    read_back = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert read_back["id"] == tower["id"]
    assert read_back["structure_type"] == "GUYED"
    assert read_back["min_colocation_elevation_ft"] == 60
    assert read_back["max_elevation_ft"] == 250
    assert_tower_capacity(
        read_back,
        rated_capacity_load_units=7200,
        reserved_load_units=3000.0,
    )
    # 100 * 3000 / 7200 = 41.6666..., rounded half up to three decimals.
    assert_pct(read_back["reserved_load_pct"], 41.667, "reserved_load_pct")


def test_tower_listing_reports_total_count_and_has_more_across_pages(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`
    and `has_more` in the `meta` object of the envelope."

    PRD §2.3 also fixes the page size: "The `limit` parameter caps the number of
    items returned; it defaults to 10, has a minimum of 1 and a maximum of 100."

    Design: Corner/entities/tower_listing_paginates_with_total_count_and_has_more
    """
    first = fixtures.new_tower(
        api,
        site_name="Page One",
        structure_type="MONOPOLE",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )
    second = fixtures.new_tower(
        api,
        site_name="Page Two",
        structure_type="MONOPOLE",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )
    third = fixtures.new_tower(
        api,
        site_name="Page Three",
        structure_type="GUYED",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )

    page_one_response = api.list_towers({"limit": 2, "offset": 0}, ADMIN_HEADERS)
    page_two_response = api.list_towers({"limit": 2, "offset": 2}, ADMIN_HEADERS)

    page_one, page_one_meta = validate_paginated(page_one_response)
    assert page_one_response.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert_list_meta(page_one_meta, limit=2, offset=0, total_count=3, has_more=True)

    page_two, page_two_meta = validate_paginated(page_two_response)
    assert len(page_two) == 1
    assert_list_meta(page_two_meta, limit=2, offset=2, total_count=3, has_more=False)

    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == {
        first["id"],
        second["id"],
        third["id"],
    }


def test_tower_listing_structure_type_filter_narrows_total_count(api):
    """PRD §3.1: "Towers can be listed with optional `capacity_posture` and
    `structure_type` filters alongside `limit` and `offset`, and every role may
    read them."

    Design: Corner/entities/tower_listing_paginates_with_total_count_and_has_more
    """
    for site_name, structure_type in (
        ("Page One", "MONOPOLE"),
        ("Page Two", "MONOPOLE"),
        ("Page Three", "GUYED"),
    ):
        fixtures.new_tower(
            api,
            site_name=site_name,
            structure_type=structure_type,
            rated_capacity_load_units=5000,
            min_colocation_elevation_ft=50,
            max_elevation_ft=200,
            ground_space_total_sqft=5000,
        )

    response = api.list_towers(
        {"structure_type": "GUYED", "limit": 10, "offset": 0}, ADMIN_HEADERS
    )

    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert_list_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert rows[0]["site_name"] == "Page Three"
    assert rows[0]["structure_type"] == "GUYED"


def test_tower_read_with_unknown_id_reports_tower_not_found(api):
    """PRD §2.5: "When a path contains more than one identifier, the system
    resolves them strictly left to right and rejects on the first one that does
    not exist, with the 404 code belonging to that resource type:
    `ERR_TOWER_NOT_FOUND`, `ERR_GROUND_LEASE_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`,
    `ERR_MLA_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_EQUIPMENT_LINE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
    `ERR_AMENDMENT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_COST_SHARE_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND` or
    `ERR_FINDING_NOT_FOUND`."

    Design: Corner/entities/tower_get_unknown_id_returns_tower_not_found
    """
    response = api.get_tower(NON_EXISTENT_UUID, ADMIN_HEADERS)

    validate_error(response, ERR_TOWER_NOT_FOUND, 404)


# ─── Required inputs, defaults and per-field constraints ─────────────────────


def test_application_without_requested_ground_space_is_rejected(api):
    """PRD §2.6: "Request shape — body and query parameters parse, required
    fields present, enum members valid, numeric ranges and the per-field
    constraints described in §3 satisfied → `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/colocation_application_missing_required_ground_space_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Required Field Ridge",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Corner Radio Networks"},
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
    )

    payload = factories.colocation_application_payload(
        tower["id"],
        carrier["mla"]["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
    )
    payload.pop("requested_ground_space_sqft")

    response = api.create_colocation_application(
        payload, make_tenant_headers(carrier["tenant"]["id"])
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api.list_colocation_applications({"tower_id": tower["id"]}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=0)


def test_tower_baseline_reservations_default_to_zero(api):
    """PRD §3.1: "Two optional inputs describe what the anchor or owner equipment
    already consumes before any colocation exists: `baseline_reserved_load_units`,
    which defaults to 0 and must be at least zero and strictly less than
    `rated_capacity_load_units`, and `baseline_reserved_ground_sqft`, which
    defaults to 0 and must be at least zero and strictly less than
    `ground_space_total_sqft`."

    Design: Corner/entities/tower_baseline_reservations_default_to_zero_when_omitted
    """
    payload = factories.tower_payload(
        site_name="Default Flats",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=4000,
        min_colocation_elevation_ft=40,
        max_elevation_ft=180,
        ground_space_total_sqft=4000,
    )
    payload.pop("baseline_reserved_load_units")
    payload.pop("baseline_reserved_ground_sqft")

    tower = validate_success(api.create_tower(payload, ADMIN_HEADERS), 201)

    assert tower["baseline_reserved_load_units"] == 0
    assert tower["baseline_reserved_ground_sqft"] == 0
    assert_tower_capacity(
        tower,
        reserved_load_units=0.0,
        reserved_load_pct=0.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=4000,
        capacity_posture="OPEN",
    )


def test_landlord_without_tax_documentation_blocks_remittance(api):
    """PRD §3.1: "A landlord is registered with a `legal_name` between 1 and 160
    characters and not blank, a `remit_contact_email` that must contain an `@`
    character, and an optional `w9_on_file` boolean that defaults to `false`."

    PRD §3.2 makes that default load-bearing: "Finally, the lease's landlord must
    have `w9_on_file` set to `true`, otherwise `ERR_LANDLORD_W9_MISSING`."

    Design: Corner/entities/landlord_w9_on_file_defaults_to_false_and_blocks_payment
    """
    tower = fixtures.new_tower(
        api,
        site_name="W9 Mesa",
        rated_capacity_load_units=6000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=250,
        ground_space_total_sqft=6000,
    )
    landlord_payload = factories.landlord_payload(
        legal_name="Mesa Land Trust", remit_contact_email="ap@mesa.example"
    )
    landlord_payload.pop("w9_on_file")
    landlord = validate_success(api.create_landlord(landlord_payload, ADMIN_HEADERS), 201)
    assert landlord["w9_on_file"] is False

    lease = fixtures.new_ground_lease(
        api,
        tower["id"],
        landlord["id"],
        base_monthly_rent_cents=400000,
        escalator_pct=2.5,
        commencement_date="2020-06-01",
        term_end_date="2031-05-31",
        renewal_option_count=1,
        renewal_term_years=5,
        buyout_price_cents=1000000,
    )

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(lease["id"], "2026-08-01", "2026-08-31"),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_LANDLORD_W9_MISSING, 422)
    assert fixtures.read_ground_lease(api, lease["id"])["paid_through_date"] is None
    _, meta = validate_paginated(api.list_landlord_payments(lease["id"], None, ADMIN_HEADERS))
    assert_list_meta(meta, total_count=0)


def test_tower_structure_type_outside_the_declared_enum_is_rejected(api):
    """PRD §3.1: "A `PortfolioAdmin` registers a tower by supplying a `site_name`
    between 1 and 120 characters and not blank, a `structure_type` that is one of
    `MONOPOLE`, `SELF_SUPPORT` or `GUYED`, a `rated_capacity_load_units` figure
    greater than zero, a `min_colocation_elevation_ft` of zero or more, a
    `max_elevation_ft` strictly greater than `min_colocation_elevation_ft`, and a
    `ground_space_total_sqft` greater than zero."

    Design: Corner/entities/tower_invalid_structure_type_enum_rejected
    """
    payload = factories.tower_payload(
        site_name="Bad Enum Butte",
        structure_type="LATTICE",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )

    response = api.create_tower(payload, ADMIN_HEADERS)

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(api.list_towers(None, ADMIN_HEADERS))
    assert_list_meta(meta, total_count=0)


def test_application_requested_band_with_top_equal_to_bottom_is_rejected(api):
    """PRD §3.4: "A carrier opens a colocation application against a specific
    site and a specific umbrella contract, supplying `tower_id`,
    `master_lease_agreement_id`, a `requested_elevation_bottom_ft` of zero or
    more, a `requested_elevation_top_ft` strictly greater than the bottom, a
    `requested_ground_space_sqft` greater than zero for cabinets and generators,
    and an optional `expedited_requested` boolean that defaults to `false` and
    invokes the master lease's expedited-review commitment."

    Design: Corner/entities/application_elevation_top_not_above_bottom_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Degenerate Band Butte",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Type Constraint Telecom"},
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
    )

    response = api.create_colocation_application(
        factories.colocation_application_payload(
            tower["id"],
            carrier["mla"]["id"],
            requested_elevation_bottom_ft=140,
            requested_elevation_top_ft=140,
            requested_ground_space_sqft=200,
        ),
        make_tenant_headers(carrier["tenant"]["id"]),
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api.list_colocation_applications({"tower_id": tower["id"]}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=0)


def test_second_tenant_claiming_an_existing_carrier_code_is_rejected(api):
    """PRD §3.3: "A carrier is registered as a tenant with a `legal_name` between
    1 and 160 characters and not blank and a `carrier_code` of 3 to 12 uppercase
    alphanumeric characters that must be unique across all tenants."

    Design: Corner/entities/tenant_duplicate_carrier_code_rejected
    """
    first = fixtures.new_tenant(api, legal_name="Duplicate Holder One", carrier_code="DUP")

    response = api.create_tenant(
        factories.tenant_payload(legal_name="Duplicate Holder Two", carrier_code="DUP"),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    survivor = fixtures.read_tenant(api, first["id"])
    assert survivor["legal_name"] == "Duplicate Holder One"
    assert survivor["carrier_code"] == "DUP"


# ─── Server-derived and system-minted fields ─────────────────────────────────


def test_equipment_line_load_units_are_derived_not_accepted_from_input(api):
    """PRD §3.4: "The raw figure is then the sum of `unit_weight_lbs` and thirty
    times `wind_area_sqft` — thirty being the wind coefficient in pounds per
    square foot — multiplied by `quantity`, multiplied by the elevation
    multiplier."

    PRD §3.4 also fixes the roll-up: "The application's `total_load_units` is the
    sum of the **already rounded** per-line figures, so each line is rounded to
    three decimals first and only then are the lines added together."

    Design: Corner/entities/equipment_line_load_units_computed_input_ignored
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="DRAFT",
        tower_overrides={
            "site_name": "Computed Crag",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Derived Cell Fields"},
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 160,
            "requested_ground_space_sqft": 200,
        },
        lines=[],
    )
    application_id = chain["application"]["id"]

    response = api.create_equipment_line(
        application_id,
        factories.equipment_line_payload(
            equipment_type="DISH",
            model_code="MW-140",
            quantity=2,
            unit_weight_lbs=140,
            wind_area_sqft=1.5,
            mount_elevation_ft=150,
            load_units=1,
        ),
        chain["tenant_headers"],
    )

    line = validate_success(response, 201)
    # A 150 ft mount sits in the 1.25 elevation tier of PRD §3.4.
    expected_load_units = (140 + WIND_COEFF_LBS_PER_SQFT * 1.5) * 2 * ELEV_MULT_TIER_2
    assert expected_load_units == 462.5
    assert_load_units(line["load_units"], 462.5, "load_units")

    application = fixtures.read_application(api, application_id)
    assert_load_units(application["total_load_units"], 462.5, "total_load_units")
    _, meta = validate_paginated(
        api.list_equipment_lines({"colocation_application_id": application_id}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=1)


def test_application_lifecycle_fields_are_minted_by_the_server(api):
    """PRD §3.4: "A fresh application starts in `DRAFT` with `total_load_units`
    at 0, `revision_count` at 0, `sla_breached` at `false`, and both
    `submitted_at` and `review_deadline_at` null."

    Design: Corner/entities/colocation_application_system_fields_input_ignored
    """
    tower = fixtures.new_tower(
        api,
        site_name="System Field Summit",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "System Fields Wireless"},
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
    )

    response = api.create_colocation_application(
        factories.colocation_application_payload(
            tower["id"],
            carrier["mla"]["id"],
            requested_elevation_bottom_ft=100,
            requested_elevation_top_ft=140,
            requested_ground_space_sqft=200,
            status="APPROVED",
            submitted_at="2020-01-01T00:00:00Z",
            revision_count=7,
        ),
        make_tenant_headers(carrier["tenant"]["id"]),
    )

    application = validate_success(response, 201)
    assert application["status"] == "DRAFT"
    assert application["submitted_at"] is None
    assert application["review_deadline_at"] is None
    assert application["revision_count"] == 0
    assert application["sla_breached"] is False
    assert_load_units(application["total_load_units"], 0.0, "total_load_units")


# ─── The immutable landlord payment record ───────────────────────────────────


def test_landlord_payment_carries_only_id_and_created_at(api):
    """PRD §2.4: "The single exception is the landlord payment record, which is
    immutable once written: a `LandlordPayment` carries only `id` and
    `created_at`, and both `updated_at` and `version` are absent from it
    entirely."

    PRD §3.2 pins the money on it: "A recorded payment computes `months_covered`
    as the count of whole calendar months contained in the inclusive-to-inclusive
    interval running from `period_start_date` through `period_end_date`, and
    computes `amount_cents` by evaluating the lease rent at the first day of each
    of those months, rounding each month's figure to whole cents, and summing the
    rounded monthly figures — never by summing first and rounding once."

    Design: Corner/entities/landlord_payment_is_immutable_with_no_version_or_update_surface
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Immutable Bench",
            "rated_capacity_load_units": 6000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 250,
            "ground_space_total_sqft": 6000,
        },
        landlord_overrides={
            "legal_name": "Bench Land Co",
            "remit_contact_email": "ap@bench.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 1000000,
        },
    )

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(
            site["ground_lease"]["id"], "2026-08-01", "2026-08-31"
        ),
        ADMIN_HEADERS,
    )

    payment = validate_success(response, 201)
    assert payment["months_covered"] == 1
    # Six anniversaries of 2020-06-01 have elapsed by 2026-08-01, so the simple
    # escalation of PRD §3.2 gives 400000 * (1 + 0.025 * 6) = 460000 cents.
    assert_cents(payment["amount_cents"], 460000, "amount_cents")
    assert_immutable_resource_fields(payment)


def test_recorded_remittance_advances_paid_through_date_and_is_visible_to_its_landlord(api):
    """PRD §3.2: "Recording the payment sets the lease's `paid_through_date` to
    `period_end_date`."

    PRD §3.2 also fixes who may read it back: "Payments for one lease can be
    listed with `limit` and `offset`, in `period_start_date` order, by a
    `PortfolioAdmin` or by the lease's own landlord."

    Design: Corner/entities/landlord_payment_is_immutable_with_no_version_or_update_surface
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Immutable Bench",
            "rated_capacity_load_units": 6000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 250,
            "ground_space_total_sqft": 6000,
        },
        landlord_overrides={
            "legal_name": "Bench Land Co",
            "remit_contact_email": "ap@bench.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 1000000,
        },
    )
    lease_id = site["ground_lease"]["id"]
    fixtures.record_landlord_payment(api, lease_id, "2026-08-01", "2026-08-31")

    response = api.list_landlord_payments(
        lease_id, {"limit": 10, "offset": 0}, make_landlord_headers(site["landlord"]["id"])
    )

    rows, meta = validate_paginated(response)
    assert_list_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert len(rows) == 1
    assert rows[0]["period_start_date"] == "2026-08-01"
    assert rows[0]["period_end_date"] == "2026-08-31"
    assert_cents(rows[0]["amount_cents"], 460000, "amount_cents")
    assert fixtures.read_ground_lease(api, lease_id)["paid_through_date"] == "2026-08-31"


# ─── Child resources and their parents ───────────────────────────────────────


def test_equipment_line_under_unknown_application_reports_application_not_found(api):
    """PRD §2.6: "Path resources exist, left to right → the matching 404 code
    from §2.5. All endpoints with path parameters."

    Design: Corner/entities/equipment_line_creation_under_unknown_application_not_found
    """
    tenant = fixtures.new_tenant(api, legal_name="Parent Relations Radio", carrier_code="PAR")

    response = api.create_equipment_line(
        NON_EXISTENT_UUID,
        factories.equipment_line_payload(
            equipment_type="ANTENNA",
            model_code="OR-90",
            quantity=1,
            unit_weight_lbs=90,
            wind_area_sqft=0,
            mount_elevation_ft=80,
        ),
        make_tenant_headers(tenant["id"]),
    )

    validate_error(response, ERR_APPLICATION_NOT_FOUND, 404)
    _, meta = validate_paginated(api.list_equipment_lines(None, ADMIN_HEADERS))
    assert_list_meta(meta, total_count=0)


# ─── Cost shares as the project × tenant junction ────────────────────────────


def _project_with_allocated_cost_shares(api):
    """One tower carrying an EXECUTED amendment plus a quoted, allocated project.

    PRD §3.6 resolves two beneficiaries here: the executed amendment of the first
    carrier (1600 load units) and the originating analysis's own application from
    the second carrier (2187.5 load units).
    """
    first_carrier = fixtures.build_colocation_chain(
        api,
        stage="EXECUTED",
        tower_overrides={
            "site_name": "Junction Basin",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 3900,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 400,
            "ground_space_total_sqft": 10000,
        },
        landlord_overrides={
            "legal_name": "Junction Land",
            "remit_contact_email": "ap@junction.example",
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
        tenant_overrides={"legal_name": "Junction Alpha", "carrier_code": "JXA"},
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "BX-160",
                "quantity": 10,
                "unit_weight_lbs": 160,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2025-08-01",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )
    second_carrier = fixtures.add_carrier_to_site(
        api,
        first_carrier,
        stage="REVIEWED",
        tenant_overrides={"legal_name": "Junction Bravo", "carrier_code": "JXB"},
        mla_overrides={"base_monthly_rent_cents": 250000, "escalator_pct": 3.5},
        application_overrides={
            "requested_elevation_bottom_ft": 150,
            "requested_elevation_top_ft": 190,
            "requested_ground_space_sqft": 500,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "AX-175",
                "quantity": 10,
                "unit_weight_lbs": 175,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 125,
            }
        ],
    )
    tower_id = first_carrier["tower"]["id"]
    analysis_id = second_carrier["analysis"]["id"]
    fixtures.quote_analysis(api, analysis_id, 20000000)
    project = fixtures.propose_project(api, tower_id, analysis_id)
    project = fixtures.allocate_shares(api, project["id"])
    return {
        "first_carrier": first_carrier,
        "second_carrier": second_carrier,
        "project": project,
    }


def test_cost_share_for_an_executed_amendment_carries_that_amendment_key(api):
    """PRD §3.6: "Every site amendment on the project's tower whose
    `execution_status` is `EXECUTED` produces one beneficiary entry, whose
    `basis_load_units` is that amendment's `reserved_load_units`, whose
    `basis_created_at` is that amendment's `created_at`, whose `tenant_id` is the
    `tenant_id` of the amendment's master lease agreement, and whose
    `site_amendment_id` is that amendment's identifier."

    Design: Corner/entities/cost_share_junction_carries_project_tenant_and_amendment_keys
    """
    world = _project_with_allocated_cost_shares(api)
    amendment = world["first_carrier"]["amendment"]

    response = api.list_cost_shares({"site_amendment_id": amendment["id"]}, ADMIN_HEADERS)

    rows, meta = validate_paginated(response)
    assert_list_meta(meta, total_count=1)
    assert len(rows) == 1
    share = rows[0]
    assert share["site_amendment_id"] == amendment["id"]
    assert share["tenant_id"] == world["first_carrier"]["tenant"]["id"]
    assert share["modification_project_id"] == world["project"]["id"]
    assert share["status"] == "PENDING"
    # Pro-rata over bases 1600 and 2187.5 of a 22,064,000-cent total cost:
    # floored to 9,320,765 cents plus the whole 1-cent remainder, which PRD §3.6
    # gives to the beneficiary with the earliest basis_created_at.
    assert_cents(share["share_cents"], 9320766, "share_cents")


def test_cost_share_for_the_originating_application_carries_a_null_amendment_key(api):
    """PRD §3.6: "In addition, the originating analysis's own application
    produces one beneficiary entry when its `status` is `SUBMITTED`,
    `UNDER_STRUCTURAL_REVIEW`, `CAPACITY_HOLD`, `MODIFICATION_REQUIRED` or
    `APPROVED`; its `basis_load_units` is the application's `total_load_units`,
    its `basis_created_at` is the application's `created_at`, its `tenant_id`
    comes from that application's master lease agreement, and its
    `site_amendment_id` is null because the applicant has no amendment yet."

    Design: Corner/entities/cost_share_junction_carries_project_tenant_and_amendment_keys
    """
    world = _project_with_allocated_cost_shares(api)
    project_id = world["project"]["id"]
    applicant_tenant_id = world["second_carrier"]["tenant"]["id"]

    response = api.list_cost_shares(
        {"modification_project_id": project_id, "tenant_id": applicant_tenant_id},
        ADMIN_HEADERS,
    )

    rows, meta = validate_paginated(response)
    assert_list_meta(meta, total_count=1)
    assert len(rows) == 1
    share = rows[0]
    assert share["site_amendment_id"] is None
    assert share["tenant_id"] == applicant_tenant_id
    assert share["status"] == "PENDING"
    assert_cents(share["share_cents"], 12743234, "share_cents")

    # The pinned seven-step pipeline of PRD §3.6 on a 20,000,000-cent quotation:
    # a 1.5 percent volume discount leaves 19,700,000 plus a 2,364,000 fee.
    project = fixtures.read_project(api, project_id)
    assert_cents(project["total_cost_cents"], 22064000, "total_cost_cents")
    assert_cents(project["allocated_cents"], 22064000, "allocated_cents")
    all_shares = fixtures.list_project_shares(api, project_id)
    assert sum(int(row["share_cents"]) for row in all_shares) == 22064000
