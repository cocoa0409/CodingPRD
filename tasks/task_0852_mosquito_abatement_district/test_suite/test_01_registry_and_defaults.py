"""District registries: service areas, protected sites, trap sites, and the
shape of the records they create."""

import test_helpers as fx
from test_helpers import (
    ADMIN,
    ECOLOGIST,
    LAB,
    MANAGER,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_service_area_opens_with_pessimistic_defaults(api):
    """PRD §3.1: "A freshly registered area starts in a deliberately
    pessimistic-about-evidence, permissive-about-nothing state: `risk_posture` is
    `NORMAL`, `posture_source` is `NO_ASSESSMENT`, `latest_confirmed_vector_index`
    is `0.00`, `seasonal_application_count` is 0, all four of
    `request_total_count`, `request_open_count`, `request_resolved_count` and
    `request_closed_count` are 0, and `version` is 1."

    Design: Corner/entities/corner_create_service_area_applies_all_declared_defaults
    """
    area = fx.create_area()

    data = validate_success(api.get_service_area(area["id"], ADMIN))
    fx.assert_service_area(data)
    assert data["risk_posture"] == "NORMAL"
    assert data["posture_source"] == "NO_ASSESSMENT"
    fx.assert_index(data["latest_confirmed_vector_index"], 0.00, "latest_confirmed_vector_index")
    assert data["seasonal_application_count"] == 0
    assert data["request_total_count"] == 0
    assert data["request_open_count"] == 0
    assert data["request_resolved_count"] == 0
    assert data["request_closed_count"] == 0
    assert data["version"] == 1


def test_service_area_without_code_is_rejected(api):
    """PRD §3.1: "Registration takes a human-readable `name` of 1 to 120
    characters, a short zone `code` of 2 to 8 characters composed only of
    uppercase letters and digits, the `season_start_date` on which the abatement
    season begins (a calendar date that becomes the baseline for degree-day
    accumulation), and the resident `population` served, which must be zero or
    greater and is carried purely for reporting."
    PRD §2.11: "**Request shape** — required fields present, types correct, enum
    values inside their declared sets, numeric ranges honoured, and pagination
    inside its bounds; otherwise `ERR_VALIDATION`."

    Design: Corner/entities/corner_create_service_area_missing_code_returns_validation
    """
    fx.set_clock(fx.CLOCK_BASE)

    response = api.create_service_area(
        {"name": "Nameless Zone", "season_start_date": "2026-05-01", "population": 100},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_unknown_trap_site_read_returns_trap_site_not_found(api):
    """PRD §2.5: "When a path names a service area that does not exist, the answer
    is `ERR_SERVICE_AREA_NOT_FOUND`; the analogous codes for the remaining path
    positions are `ERR_TRAP_SITE_NOT_FOUND`, `ERR_TRAP_COLLECTION_NOT_FOUND`,
    `ERR_LAB_POOL_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_APPLICATOR_NOT_FOUND`,
    `ERR_TREATMENT_PLAN_NOT_FOUND`, `ERR_TREATMENT_ROUTE_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, and `ERR_SERVICE_REQUEST_NOT_FOUND`. All ten are
    HTTP 404."

    Design: Corner/entities/corner_get_trap_site_with_unknown_id_returns_not_found
    """
    fx.set_clock(fx.CLOCK_BASE)

    response = api.get_trap_site("00000000-0000-4000-8000-0000000000ff", MANAGER)
    validate_error(response, ApiErrorId.ERR_TRAP_SITE_NOT_FOUND.value, 404)


def test_protected_site_buffer_defaults_follow_site_type(api):
    """PRD §3.1: "Each site type carries a default protection radius, and the
    district's negotiated practice is that bees and fish need the widest berth: an
    apiary and an aquaculture pond each default to 1600 metres, an organic farm to
    800 metres, and a school to 400 metres."
    PRD §3.1: "The registry stamps `registered_on` with the logical clock's
    calendar date."

    Design: Corner/entities/corner_sensitive_site_buffer_defaults_per_site_type
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    apiary = validate_success(
        api.create_sensitive_site(
            area["id"],
            fx.create_sensitive_site_payload(
                site_type="APIARY", operator_name="Bee Bright Apiary",
                contact_email="bees@example.com", x_m=100, y_m=100,
            ),
            ADMIN,
        ),
        201,
    )
    farm = validate_success(
        api.create_sensitive_site(
            area["id"],
            fx.create_sensitive_site_payload(
                site_type="ORGANIC_FARM", operator_name="Green Row Farm",
                contact_email="farm@example.com", x_m=200, y_m=200,
            ),
            ADMIN,
        ),
        201,
    )
    school = validate_success(
        api.create_sensitive_site(
            area["id"],
            fx.create_sensitive_site_payload(
                site_type="SCHOOL", operator_name="Elm Street Primary",
                contact_email="school@example.com", x_m=300, y_m=300,
            ),
            ADMIN,
        ),
        201,
    )

    fx.assert_sensitive_site(apiary)
    assert apiary["buffer_meters"] == 1600
    assert farm["buffer_meters"] == 800
    assert school["buffer_meters"] == 400
    assert apiary["registered_on"] == "2026-06-01"


def test_protected_site_buffer_override_replaces_type_default(api):
    """PRD §3.1: "An operator who has negotiated something different is recorded
    with `buffer_meters_override`, an optional whole number of metres that must be
    zero or greater when supplied; omitting it, or supplying null, leaves the type
    default in force. Whichever applies, the effective radius is written to
    `buffer_meters` at registration — the override when one was supplied,
    otherwise the default for the declared `site_type` — and every later
    encroachment test reads `buffer_meters` and never re-derives it."

    Design: Corner/entities/corner_sensitive_site_buffer_override_wins_over_type_default
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    site = validate_success(
        api.create_sensitive_site(
            area["id"],
            fx.create_sensitive_site_payload(
                site_type="APIARY", x_m=100, y_m=100, buffer_meters_override=2500
            ),
            ADMIN,
        ),
        201,
    )

    assert site["buffer_meters"] == 2500
    assert site["buffer_meters_override"] == 2500


def test_trap_site_rejects_unknown_trap_type(api):
    """PRD §3.1: "A trap site carries the `site_code` stencilled on the trap (1 to
    16 characters, unique among the trap sites of *its own* area, so two areas may
    reuse a code but one area may not), a `trap_type` of `CDC_LIGHT`, `GRAVID`, or
    `BG_SENTINEL`, the dominant `habitat` at the location — `URBAN`, `WETLAND`,
    `AGRICULTURAL`, or `STORMWATER` — and its own grid position as `x_m` and
    `y_m`."
    PRD §2.11: "**Request shape** — required fields present, types correct, enum
    values inside their declared sets, numeric ranges honoured, and pagination
    inside its bounds; otherwise `ERR_VALIDATION`."

    Design: Corner/entities/corner_trap_site_invalid_trap_type_enum_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    response = api.create_trap_site(
        area["id"],
        {"site_code": "T-001", "trap_type": "OVITRAP", "habitat": "URBAN", "x_m": 0, "y_m": 0},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_lab_pool_size_above_fifty_rejected_and_fifty_accepted(api):
    """PRD §3.4: "Creating a pool takes the `pool_size` — the number of mosquitoes
    going into the tube, at least 1 and at most 50, since a pool larger than 50
    mosquitoes cannot be reliably assayed — and an optional `assay`, which is
    `RT_PCR` or `VECTEST` and defaults to `RT_PCR`."
    PRD §3.3: "The first pool created from a `SUBMITTED` collection advances it
    `SUBMITTED → POOLED` as a system transition, and adds that pool's `pool_size`
    to `pooled_mosquito_count`."

    Design: Corner/entities/corner_lab_pool_above_pool_max_mosquitoes_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=80
    )

    too_big = api.create_lab_pool(collection["id"], {"pool_size": 51, "assay": "RT_PCR"}, LAB)
    validate_error(too_big, ApiErrorId.ERR_VALIDATION.value, 422)

    pool = validate_success(
        api.create_lab_pool(collection["id"], {"pool_size": 50, "assay": "RT_PCR"}, LAB), 201
    )
    fx.assert_lab_pool(pool)
    assert pool["pool_size"] == 50
    assert pool["status"] == "CREATED"

    refreshed = fx.read_collection(collection["id"])
    assert refreshed["pooled_mosquito_count"] == 50
    assert refreshed["status"] == "POOLED"


def test_larval_inspection_is_append_only(api):
    """PRD §2.4: "Two entities are deliberate exceptions because they are
    append-only evidence records and are never edited after the fact: a larval
    inspection and a weather observation carry only `id` and `created_at` — both
    `updated_at` and `version` are absent from their representations entirely."
    PRD §3.5: "Inspections of an area are listable, optionally narrowed by
    `habitat`."

    Design: Corner/entities/corner_larval_inspection_is_immutable_without_version_field
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    inspection = validate_success(
        api.create_larval_inspection(
            area["id"],
            {
                "inspection_date": "2026-05-30", "dips": 10, "larvae_count": 25,
                "habitat": "DITCH", "treated_on_site": True,
            },
            fx.make_field_tech_headers(tech["id"]),
        ),
        201,
    )
    fx.assert_larval_inspection(inspection)

    rows, meta = validate_paginated(
        api.list_larval_inspections(
            area["id"], fx.make_field_tech_headers(tech["id"]), params={"habitat": "DITCH"}
        )
    )
    assert meta["total_count"] == 1
    listed = next(row for row in rows if row["id"] == inspection["id"])
    assert "version" not in listed, "LarvalInspection must not expose version"
    assert "updated_at" not in listed, "LarvalInspection must not expose updated_at"
    assert listed["dips"] == 10
    assert listed["larvae_count"] == 25
    assert listed["treated_on_site"] is True


def test_collection_under_unknown_trap_site_returns_not_found(api):
    """PRD §2.5: "Paths in this API are flat: each collection is a top-level
    segment, and nesting is at most one level deep, expressing a parent-child
    creation or listing relationship. Path identifiers are resolved **left to
    right**, and the first segment that fails to resolve determines the error."
    PRD §2.5: "the analogous codes for the remaining path positions are
    `ERR_TRAP_SITE_NOT_FOUND`, `ERR_TRAP_COLLECTION_NOT_FOUND`,
    `ERR_LAB_POOL_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_APPLICATOR_NOT_FOUND`,
    `ERR_TREATMENT_PLAN_NOT_FOUND`, `ERR_TREATMENT_ROUTE_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, and `ERR_SERVICE_REQUEST_NOT_FOUND`."

    Design: Corner/entities/corner_collection_under_unknown_trap_site_returns_not_found
    """
    fx.set_clock(fx.CLOCK_BASE)
    tech = fx.create_applicator()

    response = api.create_trap_collection(
        "00000000-0000-4000-8000-0000000000aa",
        {"collection_date": "2026-05-30", "trap_nights": 1, "female_count": 5,
         "species": "OTHER"},
        fx.make_field_tech_headers(tech["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRAP_SITE_NOT_FOUND.value, 404)


def test_plan_with_unknown_service_area_body_reference_returns_not_found(api):
    """PRD §2.5: "Foreign keys that *do* travel in the body are resolved after
    every path identifier has resolved, and they are resolved in the order the
    endpoint's input list declares them — `service_area_id` first, then
    `trigger_assessment_id`, then `applicator_id`, then `pesticide_product_id`,
    then `sensitive_site_id`, then `assigned_applicator_id`. A body reference that
    does not resolve produces the 404 code for that reference's entity, so an
    unresolvable `sensitive_site_id` yields `ERR_SENSITIVE_SITE_NOT_FOUND` and an
    unresolvable `trigger_assessment_id` yields `ERR_RISK_ASSESSMENT_NOT_FOUND`."

    Design: Corner/entities/corner_flat_topology_body_fk_service_area_validated_on_plan_create
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    assessment = fx.open_assessment(area["id"])

    response = api.create_treatment_plan(
        {
            "service_area_id": "00000000-0000-4000-8000-0000000000bb",
            "trigger_assessment_id": assessment["id"],
            "treatment_type": "LARVICIDE",
        },
        ECOLOGIST,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND.value, 404)


def test_service_request_listing_pages_report_total_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset`
    as they were applied, `total_count` as the number of rows matching the filters
    *before* the limit and offset were applied, and `has_more`, which is true when
    rows matching the filters remain beyond the current page."
    PRD §3.10: "The area's `request_total_count` and `request_open_count` each
    increase by 1."

    Design: Corner/entities/corner_service_request_list_pagination_reports_total_and_has_more
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    for index, (contact, category) in enumerate(
        [("a@example.com", "STANDING_WATER"), ("b@example.com", "ADULT_ACTIVITY"),
         ("c@example.com", "DEAD_BIRD")]
    ):
        fx.file_request(
            area["id"], reporter_user_id=f"u-res-{index + 1}",
            reporter_contact=contact, category=category,
            description=["One", "Two", "Three"][index], x_m=index + 1, y_m=index + 1,
        )

    first, first_meta = validate_paginated(
        api.list_service_requests(
            MANAGER, params={"service_area_id": area["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second, second_meta = validate_paginated(
        api.list_service_requests(
            MANAGER, params={"service_area_id": area["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    refreshed = fx.read_area(area["id"])
    assert refreshed["request_total_count"] == 3
    assert refreshed["request_open_count"] == 3


def test_pagination_limit_above_hundred_rejected(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted
    value is 1 and the largest accepted value is 100. When `offset` is omitted it
    defaults to 0, and the smallest accepted value is 0. A `limit` below 1 or above
    100, or a negative `offset`, is a request-shape failure and is rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/corner_pagination_limit_above_maximum_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    response = api.list_service_requests(
        MANAGER, params={"service_area_id": area["id"], "limit": 101, "offset": 0}
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_lab_pool_listing_filters_by_parent_collection(api):
    """PRD §3.4: "Pools are listable across the district with optional narrowing by
    `trap_collection_id` and by `status`, and readable individually."
    PRD §3.3: "Later pools created against an already-`POOLED` collection only add
    to `pooled_mosquito_count`; the status stays `POOLED`."

    Design: Corner/entities/corner_lab_pools_filtered_list_returns_only_that_collections_children
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    first = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=40
    )
    second = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-29", trap_nights=1, female_count=20
    )
    pool_a = fx.create_pool(first["id"], 20)
    pool_b = fx.create_pool(first["id"], 20)
    pool_c = fx.create_pool(second["id"], 20)

    rows, meta = validate_paginated(
        api.list_lab_pools(
            LAB, params={"trap_collection_id": first["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    ids = {row["id"] for row in rows}
    assert ids == {pool_a["id"], pool_b["id"]}
    assert pool_c["id"] not in ids

    assert fx.read_collection(first["id"])["pooled_mosquito_count"] == 40
    assert fx.read_collection(second["id"])["pooled_mosquito_count"] == 20


def test_trap_collection_recorder_and_status_are_server_assigned(api):
    """PRD §3.3: "The server takes `trap_site_id` from the path and writes
    `recorded_by_applicator_id` from the caller's `X-User-ID`, so authorship is
    never client-assertable. The new record opens with `status` of `LOGGED`,
    `pooled_mosquito_count` of 0, `positive_pool_count` of 0, and `wnv_detected`
    false."
    PRD §2.4: "`updated_at` is refreshed on every mutation of the resource, and
    `version` is an integer that starts at 1 when the resource is created and
    increases by exactly 1 on each subsequent mutation."

    Design: Corner/entities/corner_trap_collection_system_fields_ignore_client_intent
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    fx.create_applicator(full_name="Tess Vega", license_no="L-1001")
    tech_b = fx.create_applicator(
        full_name="Ravi Shah", license_no="L-1002", license_category="ADULTICIDE"
    )
    site = fx.create_trap_site(area["id"])

    collection = validate_success(
        api.create_trap_collection(
            site["id"],
            {"collection_date": "2026-05-28", "trap_nights": 2, "female_count": 12,
             "species": "OTHER"},
            fx.make_field_tech_headers(tech_b["id"]),
        ),
        201,
    )

    fx.assert_trap_collection(collection)
    assert collection["recorded_by_applicator_id"] == tech_b["id"]
    assert collection["status"] == "LOGGED"
    assert collection["pooled_mosquito_count"] == 0
    assert collection["positive_pool_count"] == 0
    assert collection["wnv_detected"] is False
    assert collection["version"] == 1
