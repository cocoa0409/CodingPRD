"""Corner design — the `calculations` section.

Every derived number this API exposes is asserted against a value the PRD
itself computes: the normalized road-name key, the assignable slot counters,
the next-house-number selection, the low-confidence cutoff, the certified
confidence variant, the per-channel cadence interval, the channel-scoped
package release number, the closed-interval range-overlap test, and the
input set a ROAD-scoped QC scan is allowed to look at.

The server restarts before each test, so every test builds its own world
through the documented endpoints only.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_package,
    assert_package_record,
    assert_qc_report,
    assert_road_centerline,
    assert_score_equals,
    assert_slot_counters,
    expected_slot_capacity,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# normalized_name_expands_only_the_last_token
# ===========================================================================
def test_normalized_name_expands_only_the_last_token(api):
    """Only the final token of a road name is expanded, and punctuation and
    repeated spaces are stripped before the abbreviation lookup happens.

    Fourth, split the result on spaces and examine only the **last** token: if that last token is one of the recognised road-type abbreviations, replace it with its expansion — `ST` becomes `STREET`, `RD` becomes `ROAD`, `AVE` becomes `AVENUE`, `DR` becomes `DRIVE`, `LN` becomes `LANE`, `HWY` becomes `HIGHWAY`, `CT` becomes `COURT`, and `BLVD` becomes `BOULEVARD`.
    "St Andrews Ct" normalizes to `ST ANDREWS COURT`, because the leading `ST` is not the last token and is therefore untouched.

    Design: Corner/calculations/normalized_name_expands_only_the_last_token
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]

    # Four awkward spellings on deliberately non-overlapping ranges.
    r1 = fx.setup_road(api, j_id, primary_name="St Andrews Ct")
    r2 = fx.setup_road(api, j_id, primary_name="Oak Ln")
    r3 = fx.setup_road(
        api,
        j_id,
        primary_name="Oak Lane",
        from_addr_left=200,
        to_addr_left=298,
        from_addr_right=201,
        to_addr_right=299,
    )
    r4 = fx.setup_road(
        api,
        j_id,
        primary_name="  W.  Oak   Blvd ",
        from_addr_left=300,
        to_addr_left=398,
        from_addr_right=301,
        to_addr_right=399,
    )

    # The leading ST is NOT expanded; the county's spelling is preserved verbatim.
    assert_road_centerline(
        r1, primary_name="St Andrews Ct", normalized_name="ST ANDREWS COURT"
    )
    # "Oak Ln" and "Oak Lane" collapse onto one identical key.
    assert_road_centerline(r2, normalized_name="OAK LANE")
    assert_road_centerline(r3, normalized_name="OAK LANE")
    # Dot removed, space runs collapsed, ends trimmed, final BLVD expanded.
    assert_road_centerline(r4, normalized_name="W OAK BOULEVARD")


def test_two_spellings_of_oak_lane_share_one_normalized_key(api):
    """The derived key, not the county's spelling, is what a normalized-name
    query matches, so the two spellings answer as one pair of centerlines.

    "Oak Ln" and "Oak Lane" both normalize to `OAK LANE`, which is exactly why they collide in the overlap and duplicate checks.

    Design: Corner/calculations/normalized_name_expands_only_the_last_token
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]

    abbreviated = fx.setup_road(api, j_id, primary_name="Oak Ln")
    spelled_out = fx.setup_road(
        api,
        j_id,
        primary_name="Oak Lane",
        from_addr_left=200,
        to_addr_left=298,
        from_addr_right=201,
        to_addr_right=299,
    )
    fx.setup_road(
        api,
        j_id,
        primary_name="St Andrews Ct",
        from_addr_left=300,
        to_addr_left=398,
        from_addr_right=301,
        to_addr_right=399,
    )

    rows, meta = validate_paginated(
        api.list_road_centerlines(
            {"normalized_name": "OAK LANE", "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 2, (
        f"both spellings share the key OAK LANE, got total_count {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {abbreviated["id"], spelled_out["id"]}

    rows, meta = validate_paginated(
        api.list_road_centerlines(
            {"normalized_name": "ST ANDREWS COURT", "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["primary_name"] == "St Andrews Ct"


# ===========================================================================
# assignable_slot_count_tracks_capacity_and_consumption
# ===========================================================================
def test_assignable_slot_count_tracks_capacity_and_consumption(api):
    """Capacity is fixed by the side's bounds; base points consume one slot
    each, units consume none, and a retirement gives one back.

    A left range of 100 through 198 `EVEN` therefore has a capacity of ninety-eight halved and floored, giving 49, plus one, giving 50; one `ACTIVE` base point at 100 and one `PENDING` base point at 102 consume two, leaving `assignable_slot_count_left` at 48.
    Subaddress units never consume a slot, because they share their parent's `house_number`; and points in `RETIRED` or `VOIDED` status release the slot they were holding.

    Design: Corner/calculations/assignable_slot_count_tracks_capacity_and_consumption
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    # capacity = floor((198 - 100) / 2) + 1 = 50 on the left, and the right
    # range 101-199 ODD carries the same capacity.
    assert expected_slot_capacity(100, 198) == 50
    assert_slot_counters(world["road"], 50, 50)

    base_100 = fx.setup_address_point(
        api, road_id, cell_id, house_number=100, geometry_verified=True
    )
    assert_slot_counters(fx.read_road(api, road_id), 49, 50)

    base_102 = fx.setup_address_point(
        api, road_id, cell_id, house_number=102, geometry_verified=True
    )
    assert_slot_counters(fx.read_road(api, road_id), 48, 50)

    # A unit beneath the point at 100 shares its parent's house number and so
    # consumes nothing.
    fx.setup_unit_point(
        api, road_id, cell_id, base_100["id"], unit_id="2", geometry_verified=True
    )
    assert_slot_counters(fx.read_road(api, road_id), 48, 50)
    assert_address_point(fx.read_point(api, base_100["id"]), unit_child_count=1)

    # Retiring the base point at 102 releases the slot it was holding.
    fx.retire_point(api, base_102["id"], retire_reason="Duplicate parcel record")
    assert_slot_counters(fx.read_road(api, road_id), 49, 50)


def test_unit_id_without_a_parent_is_refused_and_holds_no_slot(api):
    """A unit payload naming no parent is rejected as a subaddress problem, and
    the refused call leaves the side's slot counter exactly where it was.

    Placing subaddress shape ahead of the geometry checks is deliberate: a malformed unit payload is reported as a subaddress problem rather than being masked by a parity or range complaint on a number that was only ever inherited from its parent.
    Any of these is `ERR_SUBADDRESS_PARENT_INVALID` (HTTP 422).

    Design: Corner/calculations/assignable_slot_count_tracks_capacity_and_consumption
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    fx.setup_address_point(
        api, road_id, cell_id, house_number=100, geometry_verified=True
    )
    fx.setup_address_point(
        api, road_id, cell_id, house_number=102, geometry_verified=True
    )
    assert_slot_counters(fx.read_road(api, road_id), 48, 50)

    orphan_unit = api.create_address_point(
        f.address_point_payload(
            road_id,
            cell_id,
            house_number=100,
            geometry_verified=True,
            unit_type="UNIT",
            unit_id="1",
        ),
        ANALYST_HEADERS,
    )
    validate_error(orphan_unit, ApiErrorId.SUBADDRESS_PARENT_INVALID)
    assert_slot_counters(fx.read_road(api, road_id), 48, 50)


# ===========================================================================
# next_house_number_reuses_the_lowest_gap
# ===========================================================================
def test_next_house_number_reuses_the_lowest_gap(api):
    """With 100 and 104 already taken the mint hands out the interior gap 102,
    not the next number above the highest existing address.

    To make that concrete: on a left range of 100 through 198 `EVEN` with `ACTIVE` base points at 100 and 104, the candidate set begins 102, 106, 108 and onward, and the smallest is 102.
    One **base** point is minted in `PENDING` status with `source` set to `PERMIT`, `unit_id` null, `geometry_verified` false, `postal_city` taken from the postal city of the centerline's jurisdiction, and `cell_id` set to the coverage cell of that jurisdiction with the lowest `cell_code` — or null when the jurisdiction holds no cells at all.

    Design: Corner/calculations/next_house_number_reuses_the_lowest_gap
    """
    world = fx.setup_validated_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    fx.setup_address_point(
        api, road_id, cell_id, house_number=100, geometry_verified=True
    )
    fx.setup_address_point(
        api, road_id, cell_id, house_number=104, geometry_verified=True
    )

    request = fx.setup_ready_to_assign_request(
        api, road_id, permit_number="BP-2026-0300", parcel_id="8712300300"
    )
    minted = validate_success(
        api.assign_assignment_request(request["id"], {}, ANALYST_HEADERS), 200
    )

    assert minted["assigned_house_number"] == 102, (
        f"the smallest candidate is 102, got {minted['assigned_house_number']}"
    )
    assert minted["fulfillment_status"] == "FULFILLED"
    assert minted["minted_point_count"] == 1, "requested_unit_count defaulted to 0"
    # create 1, gis-review +1, utility clearance +1, assign +1.
    assert minted["version"] == 4, f"version expected 4, got {minted['version']}"

    point = fx.read_point(api, minted["assigned_address_point_id"])
    assert_address_point(
        point,
        house_number=102,
        side="LEFT",
        source="PERMIT",
        status="PENDING",
        geometry_verified=False,
        unit_id=None,
        postal_city="FORT COLLINS",
        cell_id=cell_id,
    )
    # 60 PERMIT + 0 geometry + 8 postal match + 6 base - 5 VALIDATED road.
    assert_score_equals(point["confidence_score"], 69.00, "confidence_score")
    assert_slot_counters(fx.read_road(api, road_id), 47, 50)


# ===========================================================================
# low_confidence_cutoff_defect_fires_below_seventy_only
# ===========================================================================
def test_low_confidence_cutoff_defect_fires_below_seventy_only(api):
    """A point at 71.00 emits no low-confidence finding while a point at 69.00
    emits one, and the four resulting defects fix both score variants.

    Fires when the point's `confidence_score` is strictly below 70.
    It is `A` when `quality_score` is at least 95, otherwise `B` when it is at least 85, otherwise `C` when it is at least 70, and otherwise `D`.

    Design: Corner/calculations/low_confidence_cutoff_defect_fires_below_seventy_only
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    # 60 PERMIT + 12 geometry + 8 postal match + 6 base - 15 DRAFT = 71.00.
    point_a = fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=100,
        source="PERMIT",
        geometry_verified=True,
    )
    # 70 PARCEL + 0 geometry + 8 postal match + 6 base - 15 DRAFT = 69.00.
    point_b = fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=102,
        source="PARCEL",
        geometry_verified=False,
    )
    assert_score_equals(point_a["confidence_score"], 71.00, "confidence_score")
    assert_score_equals(point_b["confidence_score"], 69.00, "confidence_score")

    report = fx.setup_road_scoped_report(api, road_id)

    assert_qc_report(
        report,
        defect_count=4,
        blocking_defect_count=2,
        warning_defect_count=1,
        info_defect_count=1,
        quality_tier="B",
        is_provisioning_eligible=False,
    )
    # 0.45 * 86 = 38.70, 0.30 * 83.5 = 25.05, 0.25 * 100 = 25.00.
    assert_score_equals(report["quality_score"], 88.75, "quality_score")
    # BLOCKING only: 39.38 + 26.25 + 25.00.
    assert_score_equals(
        report["advisory_quality_score"], 90.63, "advisory_quality_score"
    )
    # No waivers, so no penalty is applied to the strict base.
    assert_score_equals(
        report["provisioning_eligibility_score"],
        88.75,
        "provisioning_eligibility_score",
    )

    low_confidence, meta = validate_paginated(
        api.list_qc_report_defects(
            report["id"],
            {"defect_code": "ADDRESS_LOW_CONFIDENCE", "limit": 100},
            ANALYST_HEADERS,
        )
    )
    assert meta["total_count"] == 1, "only the 69.00 point is below the cutoff"
    assert low_confidence[0]["entity_ref_id"] == point_b["id"]

    missing_geometry, meta = validate_paginated(
        api.list_qc_report_defects(
            report["id"],
            {"defect_code": "ADDRESS_MISSING_GEOMETRY", "limit": 100},
            ANALYST_HEADERS,
        )
    )
    assert meta["total_count"] == 1
    assert missing_geometry[0]["entity_ref_id"] == point_b["id"]


# ===========================================================================
# certified_variant_withholds_full_coverage_bonus_on_a_gapped_cell
# ===========================================================================
def test_certified_variant_withholds_full_coverage_bonus_on_a_gapped_cell(api):
    """Certification flips the basis to CERTIFIED but the full-coverage bonus
    is withheld on a cell that still carries three gap service types.

    Its raw value uses all of the same terms as the provisional variant and then adds two more: a bonus of 10 when the point's coverage cell has zero gap pairs at the logical clock instant — that is, when all three service types are covered there — and a penalty of 20 when the point's centerline has an `open_discrepancy_case_count` greater than zero.
    It writes `certified_confidence_score`, sets `confidence_basis` to `CERTIFIED`, and deliberately leaves the provisional `confidence_score` untouched so that the delta between the two remains inspectable.

    Design: Corner/calculations/certified_variant_withholds_full_coverage_bonus_on_a_gapped_cell
    """
    # Jurisdiction + one cell + a centerline created (v1), validated (v2) and
    # published (v3). No emergency service boundary exists anywhere.
    world = fx.setup_published_road_world(api)
    point = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=100, geometry_verified=True
    )
    # 70 PARCEL + 12 geometry + 8 postal match + 6 base - 0 PUBLISHED = 96.00.
    assert_score_equals(point["confidence_score"], 96.00, "confidence_score")

    report = fx.setup_road_scoped_report(api, world["road_id"])
    assert_qc_report(report, defect_count=0, quality_tier="A", generated_by_user_id="analyst-1")
    assert_score_equals(report["quality_score"], 100.00, "quality_score")
    assert_score_equals(
        report["provisioning_eligibility_score"],
        100.00,
        "provisioning_eligibility_score",
    )
    assert report["is_provisioning_eligible"] is True

    certified = validate_success(
        api.certify_qc_report(report["id"], {}, QC_HEADERS), 200
    )
    assert_qc_report(
        certified,
        status="CERTIFIED",
        certified_by_user_id="qc-1",
        certified_at="2026-08-01T00:00:00.000Z",
        generated_by_user_id="analyst-1",
    )

    stamped = fx.read_point(api, point["id"])
    # The provisional number is left untouched and the certified number gains
    # nothing, because the point's cell has three gap pairs.
    assert_score_equals(stamped["confidence_score"], 96.00, "confidence_score")
    assert_score_equals(
        stamped["certified_confidence_score"], 96.00, "certified_confidence_score"
    )
    assert_address_point(stamped, confidence_basis="CERTIFIED", version=2)

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["gap_pair_count"] == 3, (
        "one cell against three service types with no active boundary is three gaps"
    )


# ===========================================================================
# public_channel_cadence_uses_thirty_days
# ===========================================================================
def test_public_channel_cadence_uses_thirty_days(api):
    """The PUBLIC channel refuses a second release fourteen days out and accepts
    it at exactly thirty days, the inclusive boundary.

    Otherwise the elapsed interval is the time from that reference package's `published_at` to the current logical instant, expressed in whole and fractional days at millisecond arithmetic, and the window is open when that elapsed interval is greater than or equal to the channel's cadence interval — seven days for `DISPATCH_E911`, fourteen days for `MAPPING`, and thirty days for `PUBLIC`.

    Design: Corner/calculations/public_channel_cadence_uses_thirty_days
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_published_road_world(api)
    fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=100, geometry_verified=True
    )
    report = fx.setup_road_scoped_report(api, world["road_id"])
    fx.certify_report(api, report["id"])

    first = fx.setup_package(api, world["j_id"], report["id"], "PUBLIC")
    fx.seal_package(api, first["id"])
    fx.publish_package(api, first["id"])

    second = fx.setup_package(api, world["j_id"], report["id"], "PUBLIC")
    fx.seal_package(api, second["id"])

    # 2026-08-15 is 14.0 days after the incumbent publication: still closed for
    # a PUBLIC channel, though it would already be open for MAPPING.
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    refused = api.publish_package(second["id"], {}, PROV_HEADERS)
    validate_error(refused, ApiErrorId.CADENCE_WINDOW_NOT_OPEN)

    held = fx.read_package(api, second["id"])
    assert_package(held, status="SEALED")
    assert held["published_at"] is None, "the refused publish stamps nothing"

    # 2026-08-31 is precisely 30.0 days out and the comparison is inclusive.
    fx.set_clock(api, "2026-08-31T00:00:00Z")
    published = validate_success(
        api.publish_package(second["id"], {}, PROV_HEADERS), 200
    )
    assert_package(
        published,
        status="PUBLISHED",
        published_at="2026-08-31T00:00:00.000Z",
        published_by_user_id="prov-1",
        package_version=2,
        pinned_record_count=1,
        stale_pin_count=0,
    )

    incumbent = fx.read_package(api, first["id"])
    assert_package(
        incumbent,
        status="SUPERSEDED",
        package_version=1,
        published_at="2026-08-01T00:00:00.000Z",
    )


# ===========================================================================
# package_version_numbering_is_independent_per_channel
# ===========================================================================
def test_package_version_numbering_is_independent_per_channel(api):
    """MAPPING numbers 1 then 2 while PUBLIC starts again at 1 in the same
    jurisdiction, because the counter is scoped to the channel pairing.

    Sealing assigns the package a monotonic release number scoped to the pairing of `channel` and `jurisdiction_id`.
    So the first `DISPATCH_E911` seal for a county is numbered 1; if it is invalidated, the next seal for that channel and county is numbered 2; and a `MAPPING` seal for the same jurisdiction is numbered independently, starting again at 1.

    Design: Corner/calculations/package_version_numbering_is_independent_per_channel
    """
    world = fx.setup_published_road_world(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    fx.certify_report(api, report["id"])

    mapping_first = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    public_first = fx.setup_package(api, world["j_id"], report["id"], "PUBLIC")
    mapping_second = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")

    # A DRAFT package holds a null package_version and is never counted.
    for draft in (mapping_first, public_first, mapping_second):
        assert draft["package_version"] is None, "a DRAFT package has no release number"

    sealed_mapping_first = validate_success(
        api.seal_package(mapping_first["id"], {}, PROV_HEADERS), 200
    )
    sealed_public_first = validate_success(
        api.seal_package(public_first["id"], {}, PROV_HEADERS), 200
    )
    sealed_mapping_second = validate_success(
        api.seal_package(mapping_second["id"], {}, PROV_HEADERS), 200
    )

    assert_package(sealed_mapping_first, channel="MAPPING", package_version=1)
    assert_package(sealed_public_first, channel="PUBLIC", package_version=1)
    assert_package(sealed_mapping_second, channel="MAPPING", package_version=2)

    for sealed in (sealed_mapping_first, sealed_public_first, sealed_mapping_second):
        assert_package(
            sealed,
            status="SEALED",
            record_count=1,
            pinned_record_count=1,
            fresh_pin_count=1,
            stale_pin_count=0,
            drift_detected=False,
            sealed_by_user_id="prov-1",
            sealed_at="2026-08-01T00:00:00.000Z",
        )

    rows, meta = validate_paginated(
        api.list_package_records(mapping_second["id"], {"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, "only the PUBLISHED centerline is in scope"
    assert_package_record(
        rows[0],
        record_type="ROAD_CENTERLINE",
        record_id=world["road_id"],
        pinned_version=3,
        pin_state="FRESH",
    )


# ===========================================================================
# overlap_detection_compares_left_against_a_peer_right_range_rejected
# ===========================================================================
def test_overlap_detection_compares_left_against_a_peer_right_range_rejected(api):
    """A candidate's LEFT interval collides with a validated peer's RIGHT interval
    of the same parity, so the range test is cross-side, not side-for-side.

    Two intervals belonging to *different* centerlines conflict when all four of the following hold: they share the same `jurisdiction_id`; they share the same `normalized_name`; they carry the same parity value; and the closed intervals intersect, meaning the greater of the two low bounds is less than or equal to the lesser of the two high bounds.
    Peers still in `DRAFT` do **not** block validation — they surface later as a QC scan finding instead.

    Design: Corner/calculations/overlap_detection_compares_left_against_a_peer_right_range_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]

    # Incumbent: left 100-198 EVEN, right 101-199 ODD, promoted to VALIDATED.
    incumbent = fx.setup_road(api, j_id)
    fx.validate_road(api, incumbent["id"])

    # Candidate: its LEFT interval is 101-199 ODD, which is exactly the
    # incumbent's RIGHT interval; its own right side is the incumbent's left.
    candidate = fx.setup_road(
        api,
        j_id,
        primary_name="N. Maple St",
        from_addr_left=101,
        to_addr_left=199,
        parity_left="ODD",
        from_addr_right=100,
        to_addr_right=198,
        parity_right="EVEN",
    )
    assert_road_centerline(candidate, normalized_name="N MAPLE STREET")

    # A disjoint peer on the same normalized name, 200-298 / 201-299.
    disjoint = fx.setup_road(
        api,
        j_id,
        primary_name="N. Maple Street",
        from_addr_left=200,
        to_addr_left=298,
        parity_left="EVEN",
        from_addr_right=201,
        to_addr_right=299,
        parity_right="ODD",
    )

    refused = api.validate_road_centerline(candidate["id"], {}, ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.ROAD_RANGE_OVERLAP)

    held = fx.read_road(api, candidate["id"])
    assert_road_centerline(
        held,
        status="DRAFT",
        qc_dirty=True,
        version=1,
        normalized_name="N MAPLE STREET",
    )

    promoted = validate_success(
        api.validate_road_centerline(disjoint["id"], {}, ANALYST_HEADERS), 200
    )
    assert_road_centerline(promoted, status="VALIDATED", normalized_name="N MAPLE STREET")

    untouched = fx.read_road(api, incumbent["id"])
    assert_road_centerline(untouched, status="VALIDATED", version=2)


# ===========================================================================
# road_scoped_scan_excludes_terminal_points_and_all_cells
# ===========================================================================
def test_road_scoped_scan_excludes_terminal_points_and_all_cells(api):
    """A RETIRED point that would otherwise be a low-confidence finding is
    invisible to the scan, and a ROAD scope inspects no cells at all.

    A `ROAD`-scoped scan covers the single named centerline and its address points with `status` `PENDING` or `ACTIVE`, and **no cells at all**.
    Terminal address points — those in `RETIRED` or `VOIDED` — lie outside every scope and never produce a finding.

    Design: Corner/calculations/road_scoped_scan_excludes_terminal_points_and_all_cells
    """
    world = fx.setup_published_road_world(api)

    keeper = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], house_number=100, geometry_verified=True
    )
    keeper = fx.activate_point(api, keeper["id"])
    assert_address_point(keeper, status="ACTIVE")
    assert_score_equals(keeper["confidence_score"], 96.00)

    # A weak POSTAL point with a mismatched city and no geometry: 45 + 0 + 0
    # with a PUBLISHED road penalty of 0 lands at 45.00 before retirement.
    doomed = fx.setup_address_point(
        api,
        world["road_id"],
        world["cell_id"],
        house_number=102,
        source="POSTAL",
        postal_city="LOVELAND",
        geometry_verified=False,
    )
    doomed = fx.retire_point(api, doomed["id"], retire_reason="Never built")
    assert_address_point(doomed, status="RETIRED")

    report = fx.setup_road_scoped_report(api, world["road_id"])
    assert_qc_report(
        report,
        scope="ROAD",
        defect_count=0,
        open_blocking_defect_count=0,
        blocking_defect_count=0,
        warning_defect_count=0,
        info_defect_count=0,
        quality_tier="A",
        is_provisioning_eligible=True,
    )
    assert_score_equals(report["quality_score"], 100.00)
    assert_score_equals(report["provisioning_eligibility_score"], 100.00)

    rows, meta = validate_paginated(
        api.list_qc_report_defects(report["id"], {"limit": 100}, QC_HEADERS)
    )
    assert meta["total_count"] == 0, "the retired point produced no finding"
    assert rows == [], "a ROAD scope inspects no cells, so no gap findings either"

    # The cell gaps are real but out of scope: the jurisdiction counter proves it.
    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["gap_pair_count"] == 3, (
        "the cell really is uncovered on all three service types"
    )
