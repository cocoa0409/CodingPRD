"""Boundary precision: the exact value on the line, and the value one step past it.

Three different metrics on three different endpoints are probed at their exact
threshold — the provisioning eligibility minimum on the defect waive, the
inclusive house-number upper bound on the assignment mint, and the MAPPING
cadence interval to the millisecond on the package publish.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_assignment_request,
    assert_package,
    assert_qc_report,
    assert_road_centerline,
    assert_score_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Instance: eligibility_score_exactly_at_minimum_is_eligible
# ---------------------------------------------------------------------------
def _world_for_eligibility_boundary(api, low_confidence_numbers=(100, 102, 104, 106)):
    """A VALIDATED, un-normalized centerline carrying exactly one BLOCKING ADDRESS
    finding, one WARNING ROAD finding, two WARNING ADDRESS findings and one INFO
    ADDRESS finding per house number in ``low_confidence_numbers``."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"], primary_name="N Maple St")
    world["road_id"] = road["id"]
    world["road"] = fx.validate_road(api, world["road_id"])
    assert_road_centerline(
        world["road"],
        status="VALIDATED",
        primary_name="N Maple St",
        normalized_name="N MAPLE STREET",
    )

    # Low-confidence POSTAL points: 45 + 12 + 8 + 6 - 5 = 66.00 each.
    world["info_ids"] = []
    for house_number in low_confidence_numbers:
        point = fx.setup_address_point(
            api,
            world["road_id"],
            world["cell_id"],
            house_number=house_number,
            source="POSTAL",
            geometry_verified=True,
        )
        world["info_ids"].append(point["id"])

    # A postal-city mismatch: FIELD 80 + 12 + 0 + 6 - 5 = 93.00.
    mismatch = fx.setup_address_point(
        api,
        world["road_id"],
        world["cell_id"],
        house_number=108,
        source="FIELD",
        postal_city="LOVELAND",
        geometry_verified=True,
    )
    world["w1_id"] = mismatch["id"]

    # A unit with no unit_type: PARCEL 70 + 12 + 8 + 0 - 5 = 85.00.
    unit = fx.setup_unit_point(
        api,
        world["road_id"],
        world["cell_id"],
        world["w1_id"],
        unit_id="1",
        house_number=108,
        geometry_verified=True,
        omit=["unit_type"],
    )
    world["w2_id"] = unit["id"]

    # The single BLOCKING finding: PARCEL 70 + 0 + 8 + 6 - 5 = 79.00.
    blocking_point = fx.setup_address_point(
        api,
        world["road_id"],
        world["cell_id"],
        house_number=110,
        source="PARCEL",
        geometry_verified=False,
    )
    world["blk_pt_id"] = blocking_point["id"]

    report = fx.setup_road_scoped_report(api, world["road_id"])
    world["rep_id"] = report["id"]
    world["report"] = report
    blocking = fx.list_defects(api, world["rep_id"], {"severity": "BLOCKING", "limit": 100})
    assert len(blocking) == 1, blocking
    world["blk_defect_id"] = blocking[0]["id"]
    return world


def test_waiving_the_last_blocking_defect_lands_eligibility_exactly_at_the_minimum(api):
    """92.50 base minus one tier-B waiver is exactly 90.00, and the inclusive threshold accepts it.

    PRD: The `is_provisioning_eligible` flag is true when `provisioning_eligibility_score` is greater than or equal to 90.00 — the threshold is inclusive — **and** `open_blocking_defect_count` is zero.
    PRD: The base is 92.50, the tier is `B`, the penalty is one waiver at 2.5, and `provisioning_eligibility_score` is exactly 90.00 — precisely the minimum, so `is_provisioning_eligible` is true and a package on this report seals.
    Design: Difficulty/boundary_precision_check/eligibility_score_exactly_at_minimum_is_eligible
    """
    world = _world_for_eligibility_boundary(api)

    # The scoring inputs behind the eight findings.
    assert_score_equals(
        fx.read_point(api, world["info_ids"][0])["confidence_score"], 66.00,
        "confidence_score",
    )
    assert_score_equals(
        fx.read_point(api, world["w1_id"])["confidence_score"], 93.00, "confidence_score"
    )
    assert_score_equals(
        fx.read_point(api, world["w2_id"])["confidence_score"], 85.00, "confidence_score"
    )
    assert_score_equals(
        fx.read_point(api, world["blk_pt_id"])["confidence_score"], 79.00,
        "confidence_score",
    )

    before = fx.read_report(api, world["rep_id"])
    assert_qc_report(
        before,
        status="GENERATED",
        defect_count=8,
        warning_defect_count=3,
        info_defect_count=4,
        open_blocking_defect_count=1,
        waived_blocking_count=0,
        quality_score=86.88,
        quality_tier="B",
        provisioning_eligibility_score=86.88,
        is_provisioning_eligible=False,
    )

    validate_success(
        api.waive_qc_defect(
            world["blk_defect_id"],
            {"waiver_reason": "Survey geometry for 110 arrives next cycle; release approved"},
            QC_HEADERS,
        ),
        200,
    )

    after = fx.read_report(api, world["rep_id"])
    assert_qc_report(
        after,
        defect_count=8,
        warning_defect_count=3,
        info_defect_count=4,
        open_blocking_defect_count=0,
        waived_blocking_count=1,
        quality_score=92.50,
        quality_tier="B",
        provisioning_eligibility_score=90.00,
        is_provisioning_eligible=True,
    )
    assert_score_equals(after["quality_score"], 92.50, "quality_score")
    assert_score_equals(
        after["provisioning_eligibility_score"], 90.00, "provisioning_eligibility_score"
    )


def test_one_more_low_confidence_point_drops_eligibility_just_below_the_minimum(api):
    """A fifth INFO finding moves the same waive one step past the line: 89.33 is not eligible.

    PRD: Adding one more `INFO` `ADDRESS` finding, a fifth low-confidence point, drops the base to 91.83 and the eligibility to 89.33, and the report is no longer eligible.
    PRD: Note also the two-directional movement that waiving produces: a waiver always **raises** the strict base, because the waived defect leaves the open deduction base, and then **lowers** the eligibility score by the tier rate.
    Design: Difficulty/boundary_precision_check/eligibility_score_exactly_at_minimum_is_eligible
    """
    world = _world_for_eligibility_boundary(
        api, low_confidence_numbers=(100, 102, 104, 106, 112)
    )

    before = fx.read_report(api, world["rep_id"])
    assert_qc_report(
        before,
        status="GENERATED",
        defect_count=9,
        warning_defect_count=3,
        info_defect_count=5,
        open_blocking_defect_count=1,
        is_provisioning_eligible=False,
    )

    validate_success(
        api.waive_qc_defect(
            world["blk_defect_id"],
            {"waiver_reason": "Survey geometry for 110 arrives next cycle; release approved"},
            QC_HEADERS,
        ),
        200,
    )

    after = fx.read_report(api, world["rep_id"])
    assert_qc_report(
        after,
        defect_count=9,
        info_defect_count=5,
        open_blocking_defect_count=0,
        waived_blocking_count=1,
        quality_score=91.83,
        quality_tier="B",
        provisioning_eligibility_score=89.33,
        is_provisioning_eligible=False,
    )
    assert_score_equals(after["quality_score"], 91.83, "quality_score")
    assert_score_equals(
        after["provisioning_eligibility_score"], 89.33, "provisioning_eligibility_score"
    )


# ---------------------------------------------------------------------------
# Instance: house_number_equal_to_range_upper_bound_accepted
# ---------------------------------------------------------------------------
def _ready_request_with_proposed_number(api, proposed_house_number):
    """A VALIDATED centerline with an empty LEFT range and a READY_TO_ASSIGN request."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    world["road_id"] = road["id"]
    world["road"] = fx.validate_road(api, world["road_id"])
    assert world["road"]["assignable_slot_count_left"] == 50, world["road"]

    request = fx.setup_ready_to_assign_request(
        api,
        world["road_id"],
        permit_number="BP-2026-0198",
        parcel_id="8712300198",
        requested_unit_count=0,
        proposed_house_number=proposed_house_number,
    )
    world["req_id"] = request["id"]
    assert_assignment_request(
        request,
        review_status="GIS_APPROVED",
        utility_status="UTILITY_CLEARED",
        fulfillment_status="READY_TO_ASSIGN",
        proposed_house_number=proposed_house_number,
    )
    return world


def test_proposed_house_number_equal_to_the_inclusive_upper_bound_is_honoured(api):
    """198 is a member of the closed candidate set on [100,198] EVEN and is used verbatim.

    PRD: A `proposed_house_number` of 198 on an otherwise empty range is accepted, because the upper bound is inclusive; a `proposed_house_number` of 200 is not in the range at all and so is not a member, yielding `ERR_HOUSE_NUMBER_UNAVAILABLE`.
    PRD: The candidate set is every integer at or above the side's low bound and at or below its high bound — the interval is closed, so both endpoints are themselves candidates — whose parity matches the side's declared parity, and for which no address point already exists on that same centerline and `side` with that `house_number`, a null `unit_id`, and a `status` of `PENDING` or `ACTIVE`.
    Design: Difficulty/boundary_precision_check/house_number_equal_to_range_upper_bound_accepted
    """
    world = _ready_request_with_proposed_number(api, 198)

    assigned = validate_success(
        api.assign_assignment_request(world["req_id"], {}, ANALYST_HEADERS), 200
    )
    assert_assignment_request(
        assigned,
        fulfillment_status="FULFILLED",
        assigned_house_number=198,
        minted_point_count=1,
    )
    assert assigned["assigned_house_number"] != 100, assigned

    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(road, assignable_slot_count_left=49, assignable_slot_count_right=50)

    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": world["road_id"], "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 1, (rows, meta)
    assert_address_point(
        rows[0],
        house_number=198,
        source="PERMIT",
        postal_city="FORT COLLINS",
        status="PENDING",
        geometry_verified=False,
        cell_id=world["cell_id"],
    )
    assert rows[0]["unit_id"] is None, rows[0]
    assert rows[0]["id"] == assigned["assigned_address_point_id"], (rows[0], assigned)


def test_proposed_house_number_one_step_past_the_upper_bound_is_unavailable(api):
    """200 lies outside the closed interval, so the mint is refused rather than falling back.

    PRD: If `proposed_house_number` was supplied it must be a member of the candidate set — it may be taken already, of the wrong parity, or outside the range, and any of those refuses the request with `ERR_HOUSE_NUMBER_UNAVAILABLE` (HTTP 409) — and when it is a member it is used verbatim.
    Design: Difficulty/boundary_precision_check/house_number_equal_to_range_upper_bound_accepted
    """
    world = _ready_request_with_proposed_number(api, 200)

    resp = api.assign_assignment_request(world["req_id"], {}, ANALYST_HEADERS)
    validate_error(resp, ApiErrorId.HOUSE_NUMBER_UNAVAILABLE, 409)

    request = fx.read_request(api, world["req_id"])
    assert_assignment_request(
        request, fulfillment_status="READY_TO_ASSIGN", minted_point_count=0
    )

    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(road, assignable_slot_count_left=50)
    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": world["road_id"], "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 0, (rows, meta)


# ---------------------------------------------------------------------------
# Instance: cadence_window_opens_exactly_at_channel_interval
# ---------------------------------------------------------------------------
def _mapping_release_one_published_and_two_sealed(api):
    """MAPPING v1 PUBLISHED at 2026-08-01T00:00:00.000Z and MAPPING v2 SEALED
    behind it on the same jurisdiction, over a two-record snapshot."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    world["road_id"] = road["id"]
    point = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], geometry_verified=True
    )
    world["pt_id"] = point["id"]
    fx.validate_road(api, world["road_id"])
    fx.publish_road(api, world["road_id"])
    fx.activate_point(api, world["pt_id"])

    report = fx.setup_road_scoped_report(api, world["road_id"])
    world["rep_id"] = report["id"]
    certified = fx.certify_report(api, world["rep_id"])
    assert_qc_report(certified, status="CERTIFIED", open_blocking_defect_count=0,
                     is_provisioning_eligible=True)

    pkg1 = fx.setup_package(api, world["j_id"], world["rep_id"], "MAPPING")
    world["pkg1_id"] = pkg1["id"]
    fx.seal_package(api, world["pkg1_id"])
    world["pkg1"] = fx.publish_package(api, world["pkg1_id"])
    assert_package(
        world["pkg1"],
        status="PUBLISHED",
        package_version=1,
        published_at="2026-08-01T00:00:00.000Z",
    )

    pkg2 = fx.setup_package(api, world["j_id"], world["rep_id"], "MAPPING")
    world["pkg2_id"] = pkg2["id"]
    world["pkg2"] = fx.seal_package(api, world["pkg2_id"])
    assert_package(
        world["pkg2"],
        status="SEALED",
        package_version=2,
        pinned_record_count=2,
        fresh_pin_count=2,
        stale_pin_count=0,
        drift_detected=False,
    )
    assert world["pkg2"]["published_at"] is None, world["pkg2"]
    return world


def test_mapping_publish_is_refused_one_millisecond_before_the_cadence_interval(api):
    """At 2026-08-14T23:59:59.999Z the elapsed interval is 13.99999... days and the window is shut.

    PRD: Fourth, the cadence window for the package's channel-and-jurisdiction pairing must be open, or the request is refused with `ERR_CADENCE_WINDOW_NOT_OPEN` (HTTP 409).
    PRD: The comparison is inclusive: a `DISPATCH_E911` package published at `2026-08-01T00:00:00.000Z` reopens its window at exactly `2026-08-08T00:00:00.000Z`, where the elapsed interval is precisely seven days; at `2026-08-07T23:59:59.999Z` the window is still closed.
    Design: Difficulty/boundary_precision_check/cadence_window_opens_exactly_at_channel_interval
    """
    world = _mapping_release_one_published_and_two_sealed(api)

    assert fx.set_clock(api, "2026-08-14T23:59:59.999Z") == "2026-08-14T23:59:59.999Z"

    resp = api.publish_package(world["pkg2_id"], {}, PROV_HEADERS)
    validate_error(resp, ApiErrorId.CADENCE_WINDOW_NOT_OPEN, 409)

    pkg2 = fx.read_package(api, world["pkg2_id"])
    assert_package(pkg2, status="SEALED", package_version=2)
    assert pkg2["published_at"] is None, pkg2
    assert_package(
        fx.read_package(api, world["pkg1_id"]),
        status="PUBLISHED",
        package_version=1,
        published_at="2026-08-01T00:00:00.000Z",
    )


def test_mapping_publish_succeeds_at_exactly_the_fourteen_day_cadence_interval(api):
    """One millisecond later the elapsed interval is precisely 14 days, so the inclusive window opens.

    PRD: Otherwise the elapsed interval is the time from that reference package's `published_at` to the current logical instant, expressed in whole and fractional days at millisecond arithmetic, and the window is open when that elapsed interval is greater than or equal to the channel's cadence interval — seven days for `DISPATCH_E911`, fourteen days for `MAPPING`, and thirty days for `PUBLIC`.
    PRD: A successful publication stamps `published_at` at the logical clock instant and `published_by_user_id` from the calling `X-User-ID`, increments the package's `version` by 1, and then supersedes the incumbent: any other package on the same channel-and-jurisdiction pairing whose `status` is `PUBLISHED` transitions `PUBLISHED → SUPERSEDED`, incrementing its own `version` by 1.
    Design: Difficulty/boundary_precision_check/cadence_window_opens_exactly_at_channel_interval
    """
    world = _mapping_release_one_published_and_two_sealed(api)

    fx.set_clock(api, "2026-08-14T23:59:59.999Z")
    closed = api.publish_package(world["pkg2_id"], {}, PROV_HEADERS)
    validate_error(closed, ApiErrorId.CADENCE_WINDOW_NOT_OPEN, 409)

    assert fx.set_clock(api, "2026-08-15T00:00:00Z") == "2026-08-15T00:00:00.000Z"
    published = validate_success(
        api.publish_package(world["pkg2_id"], {}, PROV_HEADERS), 200
    )
    assert_package(
        published,
        status="PUBLISHED",
        package_version=2,
        published_at="2026-08-15T00:00:00.000Z",
    )

    incumbent = fx.read_package(api, world["pkg1_id"])
    assert_package(
        incumbent,
        status="SUPERSEDED",
        package_version=1,
        published_at="2026-08-01T00:00:00.000Z",
    )
