"""Validation-precedence conflicts: two rules violated at once, one code returned.

Each instance pairs two different error categories on one request and pins the
winner, then proves the loser is genuinely violated by removing the winner from
the picture and watching the second code appear.
"""

from test_helpers import (
    ANALYST_HEADERS,
    SYSADMIN_HEADERS,
    ApiErrorId,
    assert_road_centerline,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _world_with_two_agencies_and_a_road(api, **road_overrides):
    """Jurisdiction LARCO, an ACTIVE LAW agency, an ACTIVE FIRE agency, one road."""
    jurisdiction = fx.setup_jurisdiction(api)
    world = {"j_id": jurisdiction["id"]}
    world.update(fx.setup_two_agencies(api, world["j_id"]))
    road = fx.setup_road(api, world["j_id"], **road_overrides)
    world["road"] = road
    world["road_id"] = road["id"]
    return world


# ---------------------------------------------------------------------------
# Instance: road_retire_state_beats_discrepancy_freeze
# ---------------------------------------------------------------------------
def test_second_retire_of_a_contested_retired_centerline_reports_the_invalid_state(api):
    """State legality (priority 7) is evaluated before the discrepancy freeze (priority 10).

    PRD: Attempting a transition that the target record's current state does not define — including repeating a transition already performed, since idempotency is *not* granted anywhere in this system, and including any action on a terminal state — yields that entity's invalid-state code with HTTP 409: `ERR_ROAD_INVALID_STATE`, `ERR_ADDRESS_POINT_INVALID_STATE`, `ERR_BOUNDARY_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_DEFECT_INVALID_STATE`, `ERR_PACKAGE_INVALID_STATE` or `ERR_CASE_INVALID_STATE`.
    PRD: The order is: authentication (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_UNAUTHORIZED`), then agency identity ownership (`ERR_AGENCY_IDENTITY_MISMATCH`), then path-entity existence, then referenced-entity existence, then request-schema validity (`ERR_INVALID_REQUEST`), then target-state legality, then expected-version staleness, and only then the domain-specific business rules of §2.8 onwards in the order in which they are introduced there.
    Design: Difficulty/priority_pair_validation_conflict/road_retire_state_beats_discrepancy_freeze
    """
    world = _world_with_two_agencies_and_a_road(api)

    validate_success(
        api.retire_road_centerline(
            world["road_id"],
            {"retire_reason": "Duplicate centerline created in error"},
            ANALYST_HEADERS,
        ),
        200,
    )
    case = fx.setup_discrepancy_case(
        api,
        world["road_id"],
        world["opener_id"],
        world["counterparty_id"],
        description="Fire disputes the retirement of the N MAPLE STREET name record",
    )
    frozen = fx.read_road(api, world["road_id"])
    assert frozen["open_discrepancy_case_count"] == 1, frozen

    resp = api.retire_road_centerline(
        world["road_id"], {"retire_reason": "Second retirement attempt"}, ANALYST_HEADERS
    )
    error = validate_error(resp, ApiErrorId.ROAD_INVALID_STATE, 409)
    assert error["error_id"] != "ERR_ROAD_FROZEN_BY_DISCREPANCY", error

    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(
        road,
        status="RETIRED",
        retire_reason="Duplicate centerline created in error",
        open_discrepancy_case_count=1,
    )
    assert fx.read_case(api, case["id"])["status"] == "OPEN", case


def test_retiring_a_draft_centerline_under_an_open_case_reports_the_freeze(api):
    """With the state check satisfied the safety error is what surfaces, so it was really violated.

    PRD: Whenever `open_discrepancy_case_count` is greater than zero, five operations are refused with `ERR_ROAD_FROZEN_BY_DISCREPANCY` (HTTP 409): editing the centerline, validating it, publishing it, retiring it, and activating any address point that sits on it.
    Design: Difficulty/priority_pair_validation_conflict/road_retire_state_beats_discrepancy_freeze
    """
    world = _world_with_two_agencies_and_a_road(api)
    fx.setup_discrepancy_case(
        api, world["road_id"], world["opener_id"], world["counterparty_id"]
    )

    resp = api.retire_road_centerline(
        world["road_id"], {"retire_reason": "Second retirement attempt"}, ANALYST_HEADERS
    )
    error = validate_error(resp, ApiErrorId.ROAD_FROZEN_BY_DISCREPANCY, 409)
    assert error["error_id"] != "ERR_ROAD_INVALID_STATE", error

    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(road, status="DRAFT", open_discrepancy_case_count=1)
    assert road["retired_at"] is None, road


# ---------------------------------------------------------------------------
# Instance: road_frozen_safety_beats_range_overlap
# ---------------------------------------------------------------------------
def _two_same_named_overlapping_roads(api):
    """R1 'N MAPLE STREET' [100,198] EVEN VALIDATED, R2 'N Maple St' [150,248] EVEN DRAFT."""
    world = _world_with_two_agencies_and_a_road(api)
    world["r1_id"] = world["road_id"]
    fx.validate_road(api, world["r1_id"])
    r2 = fx.setup_road(
        api,
        world["j_id"],
        primary_name="N Maple St",
        from_addr_left=150,
        to_addr_left=248,
        parity_left="EVEN",
        from_addr_right=151,
        to_addr_right=249,
        parity_right="ODD",
    )
    world["r2_id"] = r2["id"]
    return world


def test_validating_a_contested_overlapping_centerline_reports_the_freeze(api):
    """business_safety (priority 10) is evaluated before the range-overlap constraint (priority 21).

    PRD: Three preconditions apply: the centerline's `open_discrepancy_case_count` is zero, its range geometry is valid, and its ranges do not overlap any *other* centerline's ranges under the conflict test below when that peer's `status` is `VALIDATED` or `PUBLISHED`.
    PRD: Whenever `open_discrepancy_case_count` is greater than zero, five operations are refused with `ERR_ROAD_FROZEN_BY_DISCREPANCY` (HTTP 409): editing the centerline, validating it, publishing it, retiring it, and activating any address point that sits on it.
    Design: Difficulty/priority_pair_validation_conflict/road_frozen_safety_beats_range_overlap
    """
    world = _two_same_named_overlapping_roads(api)
    fx.setup_discrepancy_case(
        api,
        world["r2_id"],
        world["opener_id"],
        world["counterparty_id"],
        subject_type="ADDRESS_RANGE",
        description="Sheriff and fire disagree on the 150-248 block assignment",
    )

    resp = api.validate_road_centerline(world["r2_id"], {}, ANALYST_HEADERS)
    error = validate_error(resp, ApiErrorId.ROAD_FROZEN_BY_DISCREPANCY, 409)
    assert error["error_id"] != "ERR_ROAD_RANGE_OVERLAP", error

    r2 = fx.read_road(api, world["r2_id"])
    assert_road_centerline(
        r2,
        status="DRAFT",
        normalized_name="N MAPLE STREET",
        open_discrepancy_case_count=1,
    )
    assert fx.read_road(api, world["r1_id"])["status"] == "VALIDATED"


def test_validating_an_overlapping_centerline_with_no_open_case_reports_the_overlap(api):
    """Lift the freeze and the range conflict is what refuses the same call.

    PRD: A blocking overlap is `ERR_ROAD_RANGE_OVERLAP` (HTTP 409).
    PRD: For a worked case: a centerline named "N Maple St" with left interval 100 through 198 `EVEN` conflicts with a candidate named "N. Maple Street" whose left interval is 150 through 248 `EVEN`, because the normalized names both reduce to `N MAPLE STREET`, the parities match, and the greater low bound 150 does not exceed the lesser high bound 198; the same candidate shifted to 200 through 298 is allowed, because 200 exceeds 198.
    Design: Difficulty/priority_pair_validation_conflict/road_frozen_safety_beats_range_overlap
    """
    world = _two_same_named_overlapping_roads(api)
    assert fx.read_road(api, world["r2_id"])["open_discrepancy_case_count"] == 0

    resp = api.validate_road_centerline(world["r2_id"], {}, ANALYST_HEADERS)
    error = validate_error(resp, ApiErrorId.ROAD_RANGE_OVERLAP, 409)
    assert error["error_id"] != "ERR_ROAD_FROZEN_BY_DISCREPANCY", error

    r2 = fx.read_road(api, world["r2_id"])
    assert_road_centerline(r2, status="DRAFT", normalized_name="N MAPLE STREET")

    # Shifted clear of the shared endpoint the very same name validates.
    clear = fx.setup_road(
        api,
        world["j_id"],
        primary_name="N Maple St",
        from_addr_left=200,
        to_addr_left=298,
        parity_left="EVEN",
        from_addr_right=201,
        to_addr_right=299,
        parity_right="ODD",
    )
    assert fx.validate_road(api, clear["id"])["status"] == "VALIDATED"


# ---------------------------------------------------------------------------
# Instance: occ_stale_beats_boundary_window_invalid
# ---------------------------------------------------------------------------
def _boundary_with_one_claim_and_a_stale_version(api):
    """A DRAFT boundary over C001 whose creation-time version is now one behind."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api, cell_codes=["C001", "C002"])
    world["cell1_id"] = world["cells"][0]["id"]
    world["cell2_id"] = world["cells"][1]["id"]
    agency = fx.setup_agency(api, world["j_id"], "LAW")
    world["law_id"] = agency["id"]
    world["headers"] = make_agency_liaison_headers(world["law_id"])
    boundary = fx.setup_boundary(api, world["law_id"])
    world["b_id"] = boundary["id"]
    world["b_v_stale"] = boundary["version"]
    assert boundary["status"] == "DRAFT", boundary

    first = validate_success(
        api.create_cell_assignment(
            world["b_id"],
            {
                "cell_id": world["cell1_id"],
                "effective_start": "2026-08-01T00:00:00Z",
                "expected_boundary_version": world["b_v_stale"],
            },
            world["headers"],
        ),
        201,
    )
    world["asn1_id"] = first["id"]
    live = fx.read_boundary(api, world["b_id"])
    assert live["version"] > world["b_v_stale"], (live, world["b_v_stale"])
    assert live["assigned_cell_count"] == 1, live
    world["b_v_live"] = live["version"]
    return world


def test_stale_boundary_version_outranks_the_inverted_claim_window(api):
    """Priority 8 returns 412 even though the same payload also breaks the 422 window rule.

    PRD: A stale `expected_boundary_version` is `ERR_STALE_BOUNDARY_VERSION` (HTTP 412).
    PRD: A mismatch with the boundary's current `version` is rejected with `ERR_STALE_BOUNDARY_VERSION` (HTTP 412).
    PRD: Validation is strictly ordered, and the **first** failing check determines the response; later checks are never reported for the same request.
    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_boundary_window_invalid
    """
    world = _boundary_with_one_claim_and_a_stale_version(api)

    resp = api.create_cell_assignment(
        world["b_id"],
        {
            "cell_id": world["cell2_id"],
            "effective_start": "2026-08-01T00:00:00Z",
            "effective_end": "2026-07-01T00:00:00Z",
            "expected_boundary_version": world["b_v_stale"],
        },
        world["headers"],
    )
    error = validate_error(resp, ApiErrorId.STALE_BOUNDARY_VERSION, 412)
    assert error["error_id"] != "ERR_BOUNDARY_WINDOW_INVALID", error
    assert resp.status_code != 422, resp.text

    boundary = fx.read_boundary(api, world["b_id"])
    assert boundary["status"] == "DRAFT", boundary
    assert boundary["assigned_cell_count"] == 1, boundary
    assert fx.read_cell_assignment(api, world["asn1_id"])["status"] == "PENDING"

    rows, meta = validate_paginated(
        api.list_boundary_cell_assignments_of(
            world["b_id"], {"limit": 100}, world["headers"]
        )
    )
    assert meta["total_count"] == 1, (rows, meta)


def test_inverted_claim_window_is_reported_once_the_boundary_version_is_current(api):
    """With the OCC check satisfied the temporal rule surfaces as a 422, proving both were broken.

    PRD: And a window problem is `ERR_BOUNDARY_WINDOW_INVALID` (HTTP 422), which covers three distinct situations: the claim's `effective_end` being non-null and at or before its `effective_start`; the claim's window not being wholly contained inside the parent boundary's own half-open window; and the claimed cell's `jurisdiction_id` differing from the jurisdiction of the boundary's agency.
    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_boundary_window_invalid
    """
    world = _boundary_with_one_claim_and_a_stale_version(api)

    resp = api.create_cell_assignment(
        world["b_id"],
        {
            "cell_id": world["cell2_id"],
            "effective_start": "2026-08-01T00:00:00Z",
            "effective_end": "2026-07-01T00:00:00Z",
            "expected_boundary_version": world["b_v_live"],
        },
        world["headers"],
    )
    error = validate_error(resp, ApiErrorId.BOUNDARY_WINDOW_INVALID, 422)
    assert error["error_id"] != "ERR_STALE_BOUNDARY_VERSION", error

    boundary = fx.read_boundary(api, world["b_id"])
    assert boundary["assigned_cell_count"] == 1, boundary
    assert boundary["version"] == world["b_v_live"], boundary
    rows, meta = validate_paginated(
        api.list_boundary_cell_assignments_of(
            world["b_id"], {"limit": 100}, world["headers"]
        )
    )
    assert meta["total_count"] == 1, (rows, meta)


# ---------------------------------------------------------------------------
# Instance: adopt_unauthorized_role_beats_case_not_found
# ---------------------------------------------------------------------------
def test_analyst_adopting_an_unknown_case_is_refused_on_role_not_on_existence(api):
    """The role gate (priority 2) runs before the path id is resolved (priority 4), so 403 not 404.

    PRD: If the role named in `X-User-Role` is not among the roles authorised for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
    PRD: **Adoption** is a `SystemAdmin` act, available only from `CONCURRED`, and it is the most far-reaching cascade in the system.
    Design: Difficulty/priority_pair_validation_conflict/adopt_unauthorized_role_beats_case_not_found
    """
    fx.setup_jurisdiction(api)

    resp = api.adopt_discrepancy_case(ZERO_UUID, {}, ANALYST_HEADERS)
    error = validate_error(resp, ApiErrorId.UNAUTHORIZED, 403)
    assert error["error_id"] != "ERR_CASE_NOT_FOUND", error
    assert resp.status_code != 404, resp.text
    assert isinstance(error["message"], str) and error["message"].strip(), error


def test_sysadmin_adopting_an_unknown_case_receives_the_case_not_found_code(api):
    """Once the role is authorised the very same unknown id is reported as 404.

    PRD: Each entity has its own 404 code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_COVERAGE_CELL_NOT_FOUND`, `ERR_ROAD_NOT_FOUND`, `ERR_ADDRESS_POINT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_BOUNDARY_NOT_FOUND`, `ERR_CELL_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and `ERR_PROPOSAL_NOT_FOUND`.
    Design: Difficulty/priority_pair_validation_conflict/adopt_unauthorized_role_beats_case_not_found
    """
    fx.setup_jurisdiction(api)

    resp = api.adopt_discrepancy_case(ZERO_UUID, {}, SYSADMIN_HEADERS)
    error = validate_error(resp, ApiErrorId.CASE_NOT_FOUND, 404)
    assert error["error_id"] != "ERR_UNAUTHORIZED", error
    assert resp.status_code != 403, resp.text
