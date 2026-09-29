"""Cross-cutting layers: the two optimistic guards and the listing envelope."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import placement_request_payload, study_payload
from test_helpers.fixtures import (
    assess_pad,
    build_campus,
    certify_study,
    create_policy,
    create_projection,
    create_site,
    create_study,
    create_unit,
    record_condition,
    school_version,
    set_clock,
    study_version,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
NORTHSIDE = {"name": "Northside Middle", "site_acreage": 10.0,
             "electrical_spare_capacity_kw": 40, "sewer_spare_connections": 1}
SUMMER_WINDOW = {"requested_window_start": "2027-06-15",
                 "requested_window_end": "2027-06-25"}


def test_certifying_one_study_makes_the_campus_version_a_planner_holds_stale(api):
    """PRD §2.6 rule 8: "`expected_school_version` is equal to the campus's `version` at
    the moment of the write — `ERR_STALE_SCHOOL_VERSION`, 412, on `POST
    /facilities/capacity-studies`." PRD §2.7: "`POST /facilities/capacity-studies` requires
    `expected_school_version` as a non-optional body field, carrying the `version` of the
    campus that the client last read. If it does not match the campus's current `version`,
    the create is rejected with `ERR_STALE_SCHOOL_VERSION` and HTTP 412." PRD §3.3: "the
    campus's `certified_study_id` is repointed to the newly certified study and its
    `reliance_flag` is recomputed. The newly certified study's `version` increases by 1 and
    the campus's `version` increases by 1." PRD §2.4: a `version` "starts at 1 on creation
    and increases by exactly 1 on every mutation of that row — including mutations the
    server performs on its own initiative as part of a cascade, and including mutations that
    only change a derived field."

    Design: Corner/complexity_layers/study_creation_rejects_a_stale_campus_version
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    next_policy = create_policy(api, effective_school_year="2028-29")
    for grade in (6, 7, 8):
        create_projection(api, ctx["school_id"], grade, 22, school_year="2028-29")

    stale_version = school_version(api, ctx["school_id"])
    assert stale_version == 1

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])

    current_version = school_version(api, ctx["school_id"])
    assert current_version == 2

    stale_create = api.create_capacity_study(
        study_payload(ctx["school_id"], next_policy["id"], stale_version,
                      school_year="2028-29"),
        PLANNER_HEADERS,
    )
    validate_error(stale_create, ApiErrorId.STALE_SCHOOL_VERSION, expected_status=412)

    _, meta = validate_paginated(
        api.list_capacity_studies(PLANNER_HEADERS, {"school_id": ctx["school_id"]})
    )
    assert meta["total_count"] == 1

    accepted = validate_success(
        api.create_capacity_study(
            study_payload(ctx["school_id"], next_policy["id"], current_version,
                          school_year="2028-29"),
            PLANNER_HEADERS,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["school_year"] == "2028-29"


def test_certification_makes_the_submit_time_study_version_stale_for_placement(api):
    """PRD §2.6 rule 9: "`expected_study_version` is equal to the study's `version` at the
    moment of the write — `ERR_STALE_STUDY_VERSION`, 412, on `POST
    /facilities/placement-requests`." PRD §3.3: submission "freezes `gross_room_seats` ...
    onto the study, and increments the study's `version` by 1", and on certification "The
    newly certified study's `version` increases by 1". PRD §3.5: "A new request opens in
    `DRAFT` with `required_permit_count` at 0". PRD §3.1: a new
    unit "sets `condition_status` to `SERVICEABLE` and `allocation_status` to
    `IN_STORAGE`", and PRD §3.4: "A newly registered pad has `feasibility_status`
    `UNASSESSED`, a null `occupied_by_unit_id`".

    Design: Corner/complexity_layers/request_creation_rejects_a_stale_study_version
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE)
    site = create_site(api, ctx["school_id"], pad_code="PAD-A")
    assess_pad(api, site["id"])
    unit = create_unit(api, asset_tag="PU-V101")

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    version_at_submit = study_version(api, study["id"])
    assert version_at_submit == 2

    certify_study(api, study["id"])
    version_certified = study_version(api, study["id"])
    assert version_certified == 3

    def payload(expected_version):
        return placement_request_payload(
            study["id"], site["id"], ctx["budget_id"], expected_version,
            portable_unit_id=unit["id"], **SUMMER_WINDOW
        )

    stale = api.create_placement_request(payload(version_at_submit), PLANNER_HEADERS)
    validate_error(stale, ApiErrorId.STALE_STUDY_VERSION, expected_status=412)

    assert validate_success(
        api.get_portable_unit(unit["id"], ASSET_HEADERS)
    )["allocation_status"] == "IN_STORAGE"
    assert validate_success(
        api.get_placement_site(site["id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    created = validate_success(
        api.create_placement_request(payload(version_certified), PLANNER_HEADERS),
        expected_status=201,
    )
    assert created["status"] == "DRAFT"
    assert created["estimated_relocation_cost_cents"] == 7_741_440


def test_the_inventory_listing_composes_filters_paging_and_counting(api):
    """PRD §2.3: "`limit` caps the number of rows returned ... `offset` is the number of
    rows to skip before the page begins ... The `meta` object of a list response carries
    `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every row
    matching the filters before the page window is applied." PRD §4 lists the inventory
    "optionally filtered by hosting campus, replacement lineage, either state dimension or
    size class". PRD §3.9: "`condition_status` records serviceability and moves only when an
    `AssetManager` records an inspection ... Recording `SERVICEABLE → NEEDS_REHAB` sets
    `condition_grade` to the supplied grade".

    Design: Corner/complexity_layers/inventory_listing_combines_filters_paging_and_stable_ordering
    """
    set_clock(api, CLOCK)
    one = create_unit(api, asset_tag="PU-P001", condition_grade="A",
                      ada_ramp_installed=True, in_service_year=2021)
    two = create_unit(api, asset_tag="PU-P002", condition_grade="B",
                      ada_ramp_installed=True, in_service_year=2019)
    three = create_unit(api, asset_tag="PU-P003", condition_grade="C",
                        in_service_year=2014)
    create_unit(api, asset_tag="PU-P004", size_class="DOUBLE_28x64",
                condition_grade="B", ada_ramp_installed=True,
                acquisition_cost_cents=15_000_000, in_service_year=2019)
    create_unit(api, asset_tag="PU-P005", size_class="DOUBLE_28x64",
                condition_grade="C", acquisition_cost_cents=15_000_000,
                in_service_year=2013)
    record_condition(api, three["id"], "NEEDS_REHAB", "C")

    singles = {one["id"], two["id"], three["id"]}

    first_rows, first_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS,
                                {"size_class": "SINGLE_24x40", "limit": 2,
                                 "offset": 0})
    )
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    first_ids = {row["id"] for row in first_rows}
    assert len(first_ids) == 2
    assert first_ids <= singles

    second_rows, second_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS,
                                {"size_class": "SINGLE_24x40", "limit": 2,
                                 "offset": 2})
    )
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    second_ids = {row["id"] for row in second_rows}
    assert second_ids == singles - first_ids

    narrowed, narrowed_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS,
                                {"size_class": "SINGLE_24x40",
                                 "condition_status": "NEEDS_REHAB"})
    )
    assert narrowed_meta["total_count"] == 1
    assert [row["id"] for row in narrowed] == [three["id"]]

    empty, empty_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS,
                                {"size_class": "DOUBLE_28x64",
                                 "condition_status": "UNSAFE"})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
