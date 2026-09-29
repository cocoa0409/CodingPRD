"""Corner design — section `validations`.

The validation surface of the County Address and Emergency Response GIS API:
the ordered domain checks on address-point creation, the half-open window rules
that guard emergency service boundaries and their cell claims, the schema-level
scope pair on a QC scan, the two counterparty rules and the single-open-case
rule on discrepancy cases, the authentication gate that outranks everything,
and the two number-selection refusals raised at assignment time.

Every test builds its own world through documented endpoints, because the
harness restarts the server — and therefore empties the database — before each
test function.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ROLE_SYSTEM_ADMIN,
    SYSADMIN_HEADERS,
    ApiErrorId,
    headers_missing_user_id,
    headers_without_user_id,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Instance: house_number_outside_the_closed_range_rejected
# ===========================================================================
def test_house_number_one_step_outside_the_closed_range_is_refused(api):
    """200 (one above to_addr_left 198) and 98 (one below from_addr_left 100) both
    carry the correct EVEN parity yet are refused, and neither refusal consumes a
    slot on the side.

    **Third**, range membership: `house_number` must lie inside the closed interval formed by the chosen side's low and high bounds, both endpoints being perfectly valid addresses, or the creation fails with `ERR_ADDRESS_OUTSIDE_RANGE` (HTTP 422).

    Design: Corner/validations/house_number_outside_the_closed_range_rejected
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    above = api.create_address_point(
        {
            "house_number": 200,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": cell_id,
        },
        ANALYST_HEADERS,
    )
    validate_error(above, ApiErrorId.ADDRESS_OUTSIDE_RANGE)
    assert above.status_code == 422

    below = api.create_address_point(
        {
            "house_number": 98,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": cell_id,
        },
        ANALYST_HEADERS,
    )
    validate_error(below, ApiErrorId.ADDRESS_OUTSIDE_RANGE)
    assert below.status_code == 422

    road = fx.read_road(api, road_id)
    assert road["assignable_slot_count_left"] == 50, "the refusals consumed nothing"

    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": road_id, "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


# ===========================================================================
# Instance: house_number_inside_range_with_matching_parity_accepted
# ===========================================================================
def test_house_number_inside_range_with_matching_parity_is_created(api):
    """150 on the LEFT EVEN side of a VALIDATED road satisfies both the parity rule
    and the closed-range rule, so the point is created with a provisional
    confidence of 70 + 12 + 8 + 6 - 5 = 91.00 and one slot is consumed.

    Its raw value is assembled by starting from the base weight for the point's `source` — 70 for `PARCEL`, 60 for `PERMIT`, 45 for `POSTAL`, and 80 for `FIELD` — then adding 12 when `geometry_verified` is true, adding 8 when the point's `postal_city` equals the postal city of its jurisdiction, adding 6 when `unit_id` is null (that is, when the point is a base address rather than a unit), and finally subtracting the road-status penalty, which is 15 while the centerline is `DRAFT`, 5 while it is `VALIDATED` and 0 once it is `PUBLISHED`.

    Design: Corner/validations/house_number_inside_range_with_matching_parity_accepted
    """
    world = fx.setup_validated_road_world(api)
    road_id = world["road_id"]

    resp = api.create_address_point(
        {
            "house_number": 150,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": world["cell_id"],
            "geometry_verified": True,
        },
        ANALYST_HEADERS,
    )
    point = validate_success(resp, 201)

    assert point["house_number"] == 150
    assert point["side"] == "LEFT"
    assert point["status"] == "PENDING"
    assert float(point["confidence_score"]) == 91.00
    assert point["confidence_basis"] == "PROVISIONAL"
    assert point["certified_confidence_score"] is None
    assert point["jurisdiction_id"] == world["j_id"]

    road = fx.read_road(api, road_id)
    assert road["assignable_slot_count_left"] == 49


# ===========================================================================
# Instance: parity_check_precedes_the_range_check
# ===========================================================================
def test_parity_check_precedes_the_range_check(api):
    """house_number 201 on the LEFT side breaks the EVEN parity AND falls outside the
    closed range [100, 198], so the ordered walk must stop at the parity check and
    answer ERR_ADDRESS_PARITY_MISMATCH rather than ERR_ADDRESS_OUTSIDE_RANGE — 201
    would have been a perfectly good RIGHT-side address, so the refusal is
    genuinely side-scoped.

    Creation runs four domain checks in a fixed order, and the first to fail is the one reported.
    **Second**, parity: the parity of `house_number` must match the referenced road's declared parity for the chosen `side`, or the creation fails with `ERR_ADDRESS_PARITY_MISMATCH` (HTTP 422).

    Design: Corner/validations/parity_check_precedes_the_range_check
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]

    resp = api.create_address_point(
        {
            "house_number": 201,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": world["cell_id"],
        },
        ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.ADDRESS_PARITY_MISMATCH)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != ApiErrorId.ADDRESS_OUTSIDE_RANGE

    road = fx.read_road(api, road_id)
    assert road["assignable_slot_count_left"] == 50
    assert road["assignable_slot_count_right"] == 50


# ===========================================================================
# Instance: duplicate_address_check_skips_retired_points
# ===========================================================================
def test_duplicate_address_refused_while_pending_then_accepted_once_retired(api):
    """Re-creating 100 LEFT while the incumbent point is PENDING is refused, but the
    very same address is accepted once that point has been retired: the retired row
    is kept for records research while its key is released for re-issue.

    And an address point is unique on the combination of its `road_centerline_id`, `side`, `house_number`, `house_number_suffix` and `unit_id`, treating nulls as equal, but **only among points whose `status` is `PENDING` or `ACTIVE`** — violated with `ERR_DUPLICATE_ADDRESS`.
    Points in `RETIRED` or `VOIDED` status do not block reuse of their key, and that is precisely what makes permanent historical retention compatible with re-issuing an address to a rebuilt structure.

    Design: Corner/validations/duplicate_address_check_skips_retired_points
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]

    first = fx.setup_address_point(api, road_id, cell_id, house_number=100)

    duplicate_payload = {
        "house_number": 100,
        "road_centerline_id": road_id,
        "side": "LEFT",
        "source": "POSTAL",
        "postal_city": "FORT COLLINS",
        "cell_id": cell_id,
    }
    duplicate = api.create_address_point(duplicate_payload, ANALYST_HEADERS)
    validate_error(duplicate, ApiErrorId.DUPLICATE_ADDRESS)
    assert duplicate.status_code == 409

    retired = fx.retire_point(api, first["id"], retire_reason="Structure demolished")
    assert retired["status"] == "RETIRED"
    assert retired["retired_at"] == "2026-08-01T00:00:00.000Z"

    second = validate_success(
        api.create_address_point(duplicate_payload, ANALYST_HEADERS), 201
    )
    assert second["house_number"] == 100
    assert second["side"] == "LEFT"
    assert second["status"] == "PENDING"
    assert second["id"] != first["id"], "a new record; the old one is kept for research"

    road = fx.read_road(api, road_id)
    assert road["assignable_slot_count_left"] == 49, "50 -> 49 -> 50 -> 49"

    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": road_id, "include_retired": "true", "limit": 100},
            ANALYST_HEADERS,
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


# ===========================================================================
# Instance: subaddress_shape_inconsistencies_rejected  (arm 1 of 3)
# ===========================================================================
def test_unit_house_number_differing_from_its_parent_is_refused(api):
    """A unit whose house_number is 102 while its parent's is 100 is refused as a
    subaddress shape problem, and the correctly shaped unit already attached to that
    parent is untouched.

    `unit_id` may not be supplied without `parent_address_point_id`, nor `parent_address_point_id` without `unit_id`; `unit_type` may not be supplied without `unit_id`; the nominated parent may not itself have a non-null `parent_address_point_id`, because units may not nest; the parent's `status` may be neither `RETIRED` nor `VOIDED`; the parent's `road_centerline_id` and `side` must both equal the child's; and the child's `house_number` must equal the parent's, since a unit shares its parent's number.
    Any of these is `ERR_SUBADDRESS_PARENT_INVALID` (HTTP 422).

    Design: Corner/validations/subaddress_shape_inconsistencies_rejected
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]
    base = fx.setup_address_point(api, road_id, cell_id, house_number=100)
    unit_one = fx.setup_unit_point(api, road_id, cell_id, base["id"], unit_id="1")

    resp = api.create_address_point(
        {
            "house_number": 102,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": cell_id,
            "unit_type": "UNIT",
            "unit_id": "2",
            "parent_address_point_id": base["id"],
        },
        ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.SUBADDRESS_PARENT_INVALID)
    assert resp.status_code == 422

    assert fx.read_point(api, base["id"])["unit_child_count"] == 1
    assert fx.read_point(api, unit_one["id"])["unit_child_count"] == 0
    assert fx.read_road(api, road_id)["assignable_slot_count_left"] == 49


# ===========================================================================
# Instance: subaddress_shape_inconsistencies_rejected  (arm 2 of 3)
# ===========================================================================
def test_unit_side_differing_from_its_parent_is_refused(api):
    """A unit declared on the RIGHT while its parent sits on the LEFT is refused as a
    subaddress shape problem and NOT as a parity problem, even though 100 breaks the
    ODD parity the RIGHT side declares — subaddress shape is walked first.

    `unit_id` may not be supplied without `parent_address_point_id`, nor `parent_address_point_id` without `unit_id`; `unit_type` may not be supplied without `unit_id`; the nominated parent may not itself have a non-null `parent_address_point_id`, because units may not nest; the parent's `status` may be neither `RETIRED` nor `VOIDED`; the parent's `road_centerline_id` and `side` must both equal the child's; and the child's `house_number` must equal the parent's, since a unit shares its parent's number.
    Placing subaddress shape ahead of the geometry checks is deliberate: a malformed unit payload is reported as a subaddress problem rather than being masked by a parity or range complaint on a number that was only ever inherited from its parent.

    Design: Corner/validations/subaddress_shape_inconsistencies_rejected
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]
    base = fx.setup_address_point(api, road_id, cell_id, house_number=100)
    fx.setup_unit_point(api, road_id, cell_id, base["id"], unit_id="1")

    resp = api.create_address_point(
        {
            "house_number": 100,
            "road_centerline_id": road_id,
            "side": "RIGHT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": cell_id,
            "unit_type": "UNIT",
            "unit_id": "3",
            "parent_address_point_id": base["id"],
        },
        ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.SUBADDRESS_PARENT_INVALID)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != ApiErrorId.ADDRESS_PARITY_MISMATCH

    assert fx.read_point(api, base["id"])["unit_child_count"] == 1
    road = fx.read_road(api, road_id)
    assert road["assignable_slot_count_left"] == 49
    assert road["assignable_slot_count_right"] == 50


# ===========================================================================
# Instance: subaddress_shape_inconsistencies_rejected  (arm 3 of 3)
# ===========================================================================
def test_unit_nested_beneath_another_unit_is_refused(api):
    """A unit whose nominated parent is itself a unit is refused: units may not nest,
    so the only legal parent is a base address whose own parent reference is null.

    `unit_id` may not be supplied without `parent_address_point_id`, nor `parent_address_point_id` without `unit_id`; `unit_type` may not be supplied without `unit_id`; the nominated parent may not itself have a non-null `parent_address_point_id`, because units may not nest; the parent's `status` may be neither `RETIRED` nor `VOIDED`; the parent's `road_centerline_id` and `side` must both equal the child's; and the child's `house_number` must equal the parent's, since a unit shares its parent's number.
    The `unit_child_count` on any point is the number of points whose `parent_address_point_id` equals it and whose `status` is `PENDING` or `ACTIVE`.

    Design: Corner/validations/subaddress_shape_inconsistencies_rejected
    """
    world = fx.setup_draft_road_world(api)
    road_id = world["road_id"]
    cell_id = world["cell_id"]
    base = fx.setup_address_point(api, road_id, cell_id, house_number=100)
    unit_one = fx.setup_unit_point(api, road_id, cell_id, base["id"], unit_id="1")

    resp = api.create_address_point(
        {
            "house_number": 100,
            "road_centerline_id": road_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": "FORT COLLINS",
            "cell_id": cell_id,
            "unit_type": "UNIT",
            "unit_id": "4",
            "parent_address_point_id": unit_one["id"],
        },
        ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.SUBADDRESS_PARENT_INVALID)
    assert resp.status_code == 422

    assert fx.read_point(api, unit_one["id"])["unit_child_count"] == 0
    assert fx.read_point(api, base["id"])["unit_child_count"] == 1
    assert fx.read_road(api, road_id)["assignable_slot_count_left"] == 49


# ===========================================================================
# Instance: zero_length_and_inverted_boundary_windows_rejected  (arm 1 of 2)
# ===========================================================================
def test_zero_length_boundary_window_is_refused_while_one_second_window_is_accepted(api):
    """The window test is effective_end at or before effective_start, so the
    zero-length window is refused exactly like an inverted one, while a window ending
    one second after it starts is accepted — which is what makes the half-open
    [start, end) convention coherent.

    A boundary whose `effective_end` is non-null and is at or before its `effective_start` is refused with `ERR_BOUNDARY_WINDOW_INVALID` (HTTP 422) — zero-length and inverted windows are both rejected.

    Design: Corner/validations/zero_length_and_inverted_boundary_windows_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    agency = fx.setup_agency(api, jurisdiction["id"], "LAW")
    liaison = make_agency_liaison_headers(agency["id"])

    zero_length = api.create_boundary(
        {
            "agency_id": agency["id"],
            "effective_start": "2026-09-01T00:00:00Z",
            "effective_end": "2026-09-01T00:00:00Z",
        },
        liaison,
    )
    validate_error(zero_length, ApiErrorId.BOUNDARY_WINDOW_INVALID)
    assert zero_length.status_code == 422

    accepted = validate_success(
        api.create_boundary(
            {
                "agency_id": agency["id"],
                "effective_start": "2026-09-01T00:00:00Z",
                "effective_end": "2026-09-01T00:00:01Z",
            },
            liaison,
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["service_type"] == "LAW", "copied from the agency's agency_type"
    assert accepted["version"] == 1
    assert accepted["assigned_cell_count"] == 0
    assert accepted["effective_start"] == "2026-09-01T00:00:00.000Z"
    assert accepted["effective_end"] == "2026-09-01T00:00:01.000Z"

    _rows, meta = validate_paginated(
        api.list_boundaries({"agency_id": agency["id"], "limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, "only the one-second window was ever stored"


# ===========================================================================
# Instance: zero_length_and_inverted_boundary_windows_rejected  (arm 2 of 2)
# ===========================================================================
def test_inverted_boundary_window_is_refused(api):
    """A window whose effective_end precedes its effective_start is refused with the
    same code as the zero-length window, and no boundary row is left behind.

    A boundary whose `effective_end` is non-null and is at or before its `effective_start` is refused with `ERR_BOUNDARY_WINDOW_INVALID` (HTTP 422) — zero-length and inverted windows are both rejected.

    Design: Corner/validations/zero_length_and_inverted_boundary_windows_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    agency = fx.setup_agency(api, jurisdiction["id"], "LAW")

    inverted = api.create_boundary(
        {
            "agency_id": agency["id"],
            "effective_start": "2026-09-01T00:00:00Z",
            "effective_end": "2026-08-01T00:00:00Z",
        },
        make_agency_liaison_headers(agency["id"]),
    )
    validate_error(inverted, ApiErrorId.BOUNDARY_WINDOW_INVALID)
    assert inverted.status_code == 422

    _rows, meta = validate_paginated(
        api.list_boundaries({"agency_id": agency["id"], "limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0


# ===========================================================================
# Instance: cell_assignment_window_must_be_contained_in_the_boundary_window
# ===========================================================================
def test_cell_assignment_window_must_be_contained_in_the_boundary_window(api):
    """A claim running to 2026-09-15 under a boundary that ends 2026-09-01 is refused,
    while the identical claim truncated to the boundary's own end is accepted —
    sharing the boundary's exclusive end is containment, not a violation. The refusal
    leaves the boundary's version at 1, so the same expected_boundary_version can be
    replayed on the corrected claim.

    And a window problem is `ERR_BOUNDARY_WINDOW_INVALID` (HTTP 422), which covers three distinct situations: the claim's `effective_end` being non-null and at or before its `effective_start`; the claim's window not being wholly contained inside the parent boundary's own half-open window; and the claimed cell's `jurisdiction_id` differing from the jurisdiction of the boundary's agency.

    Design: Corner/validations/cell_assignment_window_must_be_contained_in_the_boundary_window
    """
    world = fx.setup_base_geography(api)
    agency = fx.setup_agency(api, world["j_id"], "LAW")
    liaison = make_agency_liaison_headers(agency["id"])
    boundary = fx.setup_boundary(
        api,
        agency["id"],
        effective_start="2026-08-01T00:00:00Z",
        effective_end="2026-09-01T00:00:00Z",
    )
    observed_version = boundary["version"]
    assert observed_version == 1

    overrunning = api.create_cell_assignment(
        boundary["id"],
        {
            "cell_id": world["cell_id"],
            "effective_start": "2026-08-15T00:00:00Z",
            "effective_end": "2026-09-15T00:00:00Z",
            "expected_boundary_version": observed_version,
        },
        liaison,
    )
    validate_error(overrunning, ApiErrorId.BOUNDARY_WINDOW_INVALID)
    assert overrunning.status_code == 422

    after_refusal = fx.read_boundary(api, boundary["id"])
    assert after_refusal["version"] == 1, "a refused write mutates nothing"
    assert after_refusal["assigned_cell_count"] == 0

    assignment = validate_success(
        api.create_cell_assignment(
            boundary["id"],
            {
                "cell_id": world["cell_id"],
                "effective_start": "2026-08-15T00:00:00Z",
                "effective_end": "2026-09-01T00:00:00Z",
                "expected_boundary_version": observed_version,
            },
            liaison,
        ),
        201,
    )
    assert assignment["status"] == "PENDING"
    assert assignment["service_type"] == "LAW"
    assert assignment["effective_end"] == "2026-09-01T00:00:00.000Z"

    after_accept = fx.read_boundary(api, boundary["id"])
    assert after_accept["version"] == 2
    assert after_accept["assigned_cell_count"] == 1


# ===========================================================================
# Instance: cell_assignment_cell_must_share_the_agency_jurisdiction
# ===========================================================================
def test_cell_assignment_cell_must_share_the_agency_jurisdiction(api):
    """A cell that exists but belongs to another jurisdiction is a window-rule refusal,
    not a not-found: the reference resolves perfectly well and it is the
    cross-jurisdiction relation that fails. The same claim on the agency's own cell is
    accepted and inherits the boundary's open-ended window.

    And a window problem is `ERR_BOUNDARY_WINDOW_INVALID` (HTTP 422), which covers three distinct situations: the claim's `effective_end` being non-null and at or before its `effective_start`; the claim's window not being wholly contained inside the parent boundary's own half-open window; and the claimed cell's `jurisdiction_id` differing from the jurisdiction of the boundary's agency.

    Design: Corner/validations/cell_assignment_cell_must_share_the_agency_jurisdiction
    """
    home = fx.setup_jurisdiction(api)
    foreign = fx.setup_jurisdiction(
        api, name="Weld County", code="WELDCO", postal_city="GREELEY"
    )
    home_cell = fx.setup_coverage_cell(api, home["id"], "C001")
    foreign_cell = fx.setup_coverage_cell(api, foreign["id"], "C900")

    agency = fx.setup_agency(api, home["id"], "LAW")
    liaison = make_agency_liaison_headers(agency["id"])
    boundary = fx.setup_boundary(
        api, agency["id"], effective_start="2026-08-01T00:00:00Z"
    )
    observed_version = boundary["version"]

    cross = api.create_cell_assignment(
        boundary["id"],
        {
            "cell_id": foreign_cell["id"],
            "effective_start": "2026-08-01T00:00:00Z",
            "expected_boundary_version": observed_version,
        },
        liaison,
    )
    validate_error(cross, ApiErrorId.BOUNDARY_WINDOW_INVALID)
    assert cross.status_code == 422, "422, not 404 — the foreign cell exists"
    assert (
        cross.json()["data"]["error_id"] != ApiErrorId.COVERAGE_CELL_NOT_FOUND
    ), "the reference resolves; the relation is what fails"
    assert fx.read_cell(api, foreign_cell["id"])["id"] == foreign_cell["id"]

    assignment = validate_success(
        api.create_cell_assignment(
            boundary["id"],
            {
                "cell_id": home_cell["id"],
                "effective_start": "2026-08-01T00:00:00Z",
                "expected_boundary_version": observed_version,
            },
            liaison,
        ),
        201,
    )
    assert assignment["cell_id"] == home_cell["id"]
    assert assignment["effective_end"] is None, "open-ended, like the boundary"
    assert assignment["status"] == "PENDING"

    assert fx.read_boundary(api, boundary["id"])["version"] == 2
    assert fx.read_jurisdiction(api, home["id"])["cell_count"] == 1
    assert fx.read_jurisdiction(api, foreign["id"])["cell_count"] == 1


# ===========================================================================
# Instance: report_scope_field_pair_must_match_the_declared_scope_rejected
# ===========================================================================
def test_report_scope_field_pair_must_match_the_declared_scope(api):
    """Scope ROAD carrying jurisdiction_id, scope JURISDICTION carrying
    road_centerline_id, and scope ROAD carrying neither identifier are all schema-level
    refusals raised before any scan runs, so no report row is created and the
    centerline's qc_dirty flag is left exactly as it was.

    The scope fields are mutually exclusive and strictly enforced: a `JURISDICTION`-scoped report requires `jurisdiction_id` and forbids `road_centerline_id`, a `ROAD`-scoped report requires `road_centerline_id` and forbids `jurisdiction_id`, and getting that pairing wrong is `ERR_INVALID_REQUEST`.

    Design: Corner/validations/report_scope_field_pair_must_match_the_declared_scope_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    road = fx.setup_road(api, jurisdiction["id"])

    road_scope_with_jurisdiction = api.create_qc_report(
        {"scope": "ROAD", "jurisdiction_id": jurisdiction["id"]}, ANALYST_HEADERS
    )
    validate_error(road_scope_with_jurisdiction, ApiErrorId.INVALID_REQUEST)
    assert road_scope_with_jurisdiction.status_code == 400

    jurisdiction_scope_with_road = api.create_qc_report(
        {"scope": "JURISDICTION", "road_centerline_id": road["id"]}, ANALYST_HEADERS
    )
    validate_error(jurisdiction_scope_with_road, ApiErrorId.INVALID_REQUEST)
    assert jurisdiction_scope_with_road.status_code == 400

    road_scope_with_neither = api.create_qc_report({"scope": "ROAD"}, ANALYST_HEADERS)
    validate_error(road_scope_with_neither, ApiErrorId.INVALID_REQUEST)
    assert road_scope_with_neither.status_code == 400

    _rows, meta = validate_paginated(
        api.list_qc_reports({"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0, "no report row was created"
    assert fx.read_road(api, road["id"])["qc_dirty"] is True, "no scan ran"


# ===========================================================================
# Instance: counterparty_in_another_jurisdiction_rejected
# ===========================================================================
def test_counterparty_in_another_jurisdiction_or_naming_itself_is_refused(api):
    """A Weld County fire agency named as counterparty on a Larimer County road is
    refused, and so is the sheriff naming itself; only the in-jurisdiction fire agency
    is a legitimate counterparty, and only that accepted case is counted on the road.

    The `counterparty_agency_id` may not equal the acting agency, and the counterparty's `jurisdiction_id` may not differ from the subject record's `jurisdiction_id`; either is `ERR_COUNTERPARTY_INVALID` (HTTP 422).
    The case's `opened_by_agency_id` is set from the calling `X-User-ID`, and its `jurisdiction_id` is copied from the subject record's jurisdiction.

    Design: Corner/validations/counterparty_in_another_jurisdiction_rejected
    """
    home = fx.setup_jurisdiction(api)
    foreign = fx.setup_jurisdiction(
        api, name="Weld County", code="WELDCO", postal_city="GREELEY"
    )
    sheriff = fx.setup_agency(api, home["id"], "LAW")
    poudre_fire = fx.setup_agency(api, home["id"], "FIRE")
    greeley_fire = fx.setup_agency(
        api, foreign["id"], "FIRE", name="Greeley Fire Department"
    )
    road = fx.setup_road(api, home["id"])
    liaison = make_agency_liaison_headers(sheriff["id"])

    cross_jurisdiction = api.create_discrepancy_case(
        {
            "subject_type": "ROAD_NAME",
            "subject_ref_id": road["id"],
            "counterparty_agency_id": greeley_fire["id"],
            "description": "Greeley disputes the Maple Street name",
        },
        liaison,
    )
    validate_error(cross_jurisdiction, ApiErrorId.COUNTERPARTY_INVALID)
    assert cross_jurisdiction.status_code == 422

    self_named = api.create_discrepancy_case(
        {
            "subject_type": "ROAD_NAME",
            "subject_ref_id": road["id"],
            "counterparty_agency_id": sheriff["id"],
            "description": "The sheriff disputes itself",
        },
        liaison,
    )
    validate_error(self_named, ApiErrorId.COUNTERPARTY_INVALID)
    assert self_named.status_code == 422

    case = validate_success(
        api.create_discrepancy_case(
            {
                "subject_type": "ROAD_NAME",
                "subject_ref_id": road["id"],
                "counterparty_agency_id": poudre_fire["id"],
                "description": "Poudre Fire disputes the Maple Street name",
            },
            liaison,
        ),
        201,
    )
    assert case["status"] == "OPEN"
    assert case["round_count"] == 0
    assert case["jurisdiction_id"] == home["id"]
    assert case["opened_by_agency_id"] == sheriff["id"]
    assert case["counterparty_agency_id"] == poudre_fire["id"]

    assert fx.read_road(api, road["id"])["open_discrepancy_case_count"] == 1


# ===========================================================================
# Instance: second_open_case_on_the_same_subject_rejected
# ===========================================================================
def test_second_open_case_on_the_same_subject_is_refused(api):
    """A third agency filing on the same (subject_type, subject_ref_id) pairing is
    refused while the incumbent case is still unresolved, yet a case on a different
    subject_type over the same road identifier is accepted — a different subject_type
    is a different subject. The road stays DRAFT because the freeze is enforced at
    transition time rather than at case creation.

    And no case may already exist on the same pairing of `subject_type` and `subject_ref_id` whose `status` is anything other than `ADOPTED` or `ARBITRATED`, or the creation is refused with `ERR_SUBJECT_CASE_ALREADY_OPEN` (HTTP 409).
    A centerline's `open_discrepancy_case_count` is the number of cases on it whose `status` is `OPEN`, `PROPOSAL_PENDING`, `COUNTERED` or `ESCALATED`.

    Design: Corner/validations/second_open_case_on_the_same_subject_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    sheriff = fx.setup_agency(api, jurisdiction["id"], "LAW")
    poudre_fire = fx.setup_agency(api, jurisdiction["id"], "FIRE")
    valley_ems = fx.setup_agency(api, jurisdiction["id"], "EMS")
    road = fx.setup_road(api, jurisdiction["id"])

    first_case = fx.setup_discrepancy_case(
        api,
        road["id"],
        sheriff["id"],
        poudre_fire["id"],
        subject_type="ROAD_NAME",
        description="Name should be MAPLE STREET",
    )
    assert first_case["status"] == "OPEN"

    ems_liaison = make_agency_liaison_headers(valley_ems["id"])
    same_subject = api.create_discrepancy_case(
        {
            "subject_type": "ROAD_NAME",
            "subject_ref_id": road["id"],
            "counterparty_agency_id": sheriff["id"],
            "description": "EMS also disputes the name",
        },
        ems_liaison,
    )
    validate_error(same_subject, ApiErrorId.SUBJECT_CASE_ALREADY_OPEN)
    assert same_subject.status_code == 409

    other_subject = validate_success(
        api.create_discrepancy_case(
            {
                "subject_type": "ADDRESS_RANGE",
                "subject_ref_id": road["id"],
                "counterparty_agency_id": sheriff["id"],
                "description": "EMS disputes the LEFT range instead",
            },
            ems_liaison,
        ),
        201,
    )
    assert other_subject["status"] == "OPEN"
    assert fx.read_case(api, first_case["id"])["status"] == "OPEN"

    road_after = fx.read_road(api, road["id"])
    assert road_after["open_discrepancy_case_count"] == 2
    assert road_after["status"] == "DRAFT"


# ===========================================================================
# Instance: unauthenticated_request_without_a_user_header_rejected
# ===========================================================================
def test_unauthenticated_request_without_a_user_header_is_refused(api):
    """The authentication gate outranks the schema check: a POST whose X-User-ID header
    is absent answers 401 even though its body is also missing the required `code`
    field, and an empty X-User-ID is treated identically. Nothing is stored.

    If `X-User-ID` is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other evaluation takes place.

    Design: Corner/validations/unauthenticated_request_without_a_user_header_rejected
    """
    body_missing_code = {
        "name": "Larimer County",
        "jurisdiction_type": "COUNTY",
        "postal_city": "FORT COLLINS",
    }

    absent = api.create_jurisdiction(
        body_missing_code, headers_missing_user_id(ROLE_SYSTEM_ADMIN)
    )
    validate_error(absent, ApiErrorId.UNAUTHENTICATED)
    assert absent.status_code == 401
    assert absent.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST
    assert absent.json()["data"]["message"].strip() != ""

    empty = api.create_jurisdiction(
        body_missing_code, headers_without_user_id(ROLE_SYSTEM_ADMIN)
    )
    validate_error(empty, ApiErrorId.UNAUTHENTICATED)
    assert empty.status_code == 401

    _rows, meta = validate_paginated(
        api.list_jurisdictions({"limit": 100}, SYSADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


# ===========================================================================
# Instance: exhausted_range_leaves_no_assignable_address_rejected
# ===========================================================================
def test_exhausted_range_leaves_no_assignable_address(api):
    """A single-slot side — LEFT [100, 100] EVEN, capacity ((100-100)//2)+1 = 1 — that
    already holds one PENDING base point yields an empty candidate set, so the mint is
    refused even though every individual step along the way was legal. The refused
    assign leaves the request READY_TO_ASSIGN at version 3 with nothing minted.

    If the candidate set is empty the range is exhausted and the request is refused with `ERR_NO_ASSIGNABLE_ADDRESS` (HTTP 409).
    For each side, capacity is computed as the difference between the side's high bound and its low bound, divided by two with any fraction discarded, plus one.

    Design: Corner/validations/exhausted_range_leaves_no_assignable_address_rejected
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(
        api,
        world["j_id"],
        primary_name="CUL DE SAC COURT",
        from_addr_left=100,
        to_addr_left=100,
        parity_left="EVEN",
        from_addr_right=101,
        to_addr_right=101,
        parity_right="ODD",
    )
    road_id = road["id"]
    fx.validate_road(api, road_id)
    point = fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=100, geometry_verified=True
    )

    request = fx.setup_assignment_request(
        api,
        road_id,
        permit_number="BP-2026-0400",
        parcel_id="8712300400",
        side="LEFT",
    )
    fx.gis_review(api, request["id"], "APPROVE")
    fx.utility_clearance(api, request["id"], "CLEAR")

    resp = api.assign_assignment_request(request["id"], {}, ANALYST_HEADERS)
    validate_error(resp, ApiErrorId.NO_ASSIGNABLE_ADDRESS)
    assert resp.status_code == 409

    road_after = fx.read_road(api, road_id)
    assert road_after["assignable_slot_count_left"] == 0
    assert road_after["assignable_slot_count_right"] == 1

    request_after = fx.read_request(api, request["id"])
    assert request_after["fulfillment_status"] == "READY_TO_ASSIGN"
    assert request_after["assigned_house_number"] is None
    assert request_after["minted_point_count"] == 0
    assert request_after["version"] == 3, "the failed assign did not bump it"

    rows, meta = validate_paginated(
        api.list_address_points(
            {"road_centerline_id": road_id, "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == point["id"]


# ===========================================================================
# Instance: proposed_house_number_outside_the_candidate_set_rejected
# ===========================================================================
def test_proposed_house_number_outside_the_candidate_set_is_refused(api):
    """proposed_house_number is accepted verbatim at intake and only tested at mint
    time: 200 lies outside the closed range [100, 198], so the assign is refused rather
    than silently falling back to the computed minimum of 100. The candidate set is
    non-empty, so the refusal is not the range-exhausted code.

    If `proposed_house_number` was supplied it must be a member of the candidate set — it may be taken already, of the wrong parity, or outside the range, and any of those refuses the request with `ERR_HOUSE_NUMBER_UNAVAILABLE` (HTTP 409) — and when it is a member it is used verbatim.

    Design: Corner/validations/proposed_house_number_outside_the_candidate_set_rejected
    """
    world = fx.setup_validated_road_world(api)
    road_id = world["road_id"]

    request = fx.setup_assignment_request(
        api,
        road_id,
        permit_number="BP-2026-0500",
        parcel_id="8712300500",
        side="LEFT",
        proposed_house_number=200,
    )
    assert request["proposed_house_number"] == 200, "not range-checked at intake"
    fx.gis_review(api, request["id"], "APPROVE")
    fx.utility_clearance(api, request["id"], "CLEAR")

    resp = api.assign_assignment_request(request["id"], {}, ANALYST_HEADERS)
    validate_error(resp, ApiErrorId.HOUSE_NUMBER_UNAVAILABLE)
    assert resp.status_code == 409
    assert (
        resp.json()["data"]["error_id"] != ApiErrorId.NO_ASSIGNABLE_ADDRESS
    ), "the candidate set is non-empty — 100 is free"

    request_after = fx.read_request(api, request["id"])
    assert request_after["fulfillment_status"] == "READY_TO_ASSIGN"
    assert request_after["assigned_address_point_id"] is None
    assert request_after["assigned_house_number"] is None

    assert fx.read_road(api, road_id)["assignable_slot_count_left"] == 50
