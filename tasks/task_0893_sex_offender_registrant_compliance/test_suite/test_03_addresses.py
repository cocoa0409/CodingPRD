"""Address recording: exclusion-zone proximity, temporary-window overlap,
optimistic concurrency, and residence supersession."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_jurisdiction, create_exclusion_zone, create_registrant, add_offense,
    activate, add_address, get_registrant, setup_active_registrant, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]


def _active_reg_with_zone():
    jur = create_jurisdiction()
    create_exclusion_zone(jur["id"], name="Lincoln Elementary", zone_type="SCHOOL",
                          center_x=0, center_y=0, radius_meters=500, buffer_meters=100)
    reg = create_registrant(jur["id"], full_name="Near N")
    add_offense(reg["id"])
    reg = activate(reg["id"])
    return jur, reg


def test_residence_at_exact_radius_plus_buffer_prohibited(api):
    """PRD 3.3: "it computes the straight-line distance between the address point
    and the zone center — the square root of the sum of the squared differences of
    the x and y coordinates — and treats the address as prohibited when that
    distance is less than or equal to the zone's `radius_meters` plus its
    `buffer_meters`. If any zone prohibits the point, the address is rejected with
    `ERR_EXCLUSION_ZONE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/exclusion_zone_prohibits_at_exact_radius_plus_buffer
    """
    jur, reg = _active_reg_with_zone()
    # distance((600,0),(0,0)) = 600 == radius 500 + buffer 100 -> prohibited (<=).
    resp = api.create_address(
        reg["id"],
        {"address_type": "RESIDENCE", "line1": "600 Edge Ln", "city": "Metro",
         "state_code": "CA", "postal_code": "90001", "grid_x": 600, "grid_y": 0,
         "expected_registrant_version": reg["version"]},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_EXCLUSION_ZONE_VIOLATION)


def test_residence_one_meter_beyond_boundary_allowed(api):
    """PRD 3.3: "treats the address as prohibited when that distance is less than
    or equal to the zone's `radius_meters` plus its `buffer_meters`."

    Design: Difficulty/boundary_precision_check/exclusion_zone_prohibits_at_exact_radius_plus_buffer
    """
    jur, reg = _active_reg_with_zone()
    # distance((601,0),(0,0)) = 601 > 600 -> allowed.
    resp = api.create_address(
        reg["id"],
        {"address_type": "RESIDENCE", "line1": "601 Edge Ln", "city": "Metro",
         "state_code": "CA", "postal_code": "90001", "grid_x": 601, "grid_y": 0,
         "expected_registrant_version": reg["version"]},
        OFFICER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "VERIFIED"


def test_temporary_address_touching_prior_window_rejected(api):
    """PRD 3.3: "A new `TEMPORARY` address whose window overlaps an existing
    `TEMPORARY` window for the same registrant is rejected with
    `ERR_ADDRESS_PERIOD_CONFLICT`; these windows are treated as closed intervals,
    so windows that merely touch at an endpoint are considered to conflict."

    Design: Difficulty/resource_temporal_overlap/temporary_address_closed_touching_overlap_rejected
    """
    jur, reg = setup_active_registrant(full_name="Temp T")
    v = reg["version"]
    add_address(reg["id"], v, address_type="TEMPORARY", line1="1 Motel",
                grid_x=8000, grid_y=8000,
                effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-10T00:00:00Z")
    # New window starts exactly on the prior window's effective_to -> touching conflict.
    resp = api.create_address(
        reg["id"],
        {"address_type": "TEMPORARY", "line1": "2 Motel", "city": "Metro",
         "state_code": "CA", "postal_code": "90001", "grid_x": 8100, "grid_y": 8000,
         "effective_from": "2026-06-10T00:00:00Z", "effective_to": "2026-06-15T00:00:00Z",
         "expected_registrant_version": v},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_ADDRESS_PERIOD_CONFLICT)


def test_temporary_address_non_overlapping_window_allowed(api):
    """PRD 3.3: "A new `TEMPORARY` address whose window overlaps an existing
    `TEMPORARY` window for the same registrant is rejected with
    `ERR_ADDRESS_PERIOD_CONFLICT`; these windows are treated as closed intervals,
    so windows that merely touch at an endpoint are considered to conflict."

    Design: Difficulty/resource_temporal_overlap/temporary_address_closed_touching_overlap_rejected
    """
    jur, reg = setup_active_registrant(full_name="Temp T")
    v = reg["version"]
    add_address(reg["id"], v, address_type="TEMPORARY", line1="1 Motel",
                grid_x=8000, grid_y=8000,
                effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-10T00:00:00Z")
    # New window begins after the prior window closes (gap) -> no conflict.
    resp = api.create_address(
        reg["id"],
        {"address_type": "TEMPORARY", "line1": "2 Motel", "city": "Metro",
         "state_code": "CA", "postal_code": "90001", "grid_x": 8100, "grid_y": 8000,
         "effective_from": "2026-06-11T00:00:00Z", "effective_to": "2026-06-15T00:00:00Z",
         "expected_registrant_version": v},
        OFFICER,
    )
    validate_success(resp, expected_status=201)


def test_stale_registrant_version_on_address_create_rejected(api):
    """PRD 2.8: "If that value does not equal the registrant's current `version` —
    meaning another residence update has already advanced the registrant record
    since the client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from overwriting a residence state it never
    saw."

    Design: Corner/cross_cutting/address_create_stale_registrant_version_conflict
    """
    jur, reg = setup_active_registrant(full_name="Occ O")
    stale_v = reg["version"]
    add_address(reg["id"], stale_v, address_type="RESIDENCE", line1="1 First St",
                grid_x=4000, grid_y=4000)  # advances registrant.version
    resp = api.create_address(
        reg["id"],
        {"address_type": "RESIDENCE", "line1": "2 Second St", "city": "Metro",
         "state_code": "CA", "postal_code": "90002", "grid_x": 4200, "grid_y": 4200,
         "expected_registrant_version": stale_v},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_new_residence_supersedes_prior_marking_it_historical(api):
    """PRD 3.3: "When the residence clears the screen, it becomes the registrant's
    current residence: the prior `RESIDENCE` address, if any, transitions from
    `VERIFIED` to `HISTORICAL`, the new one is `VERIFIED`, and the registrant's
    `current_residence_address_id` is repointed to the new address."

    Design: Corner/cross_cutting/residence_supersede_marks_prior_historical
    """
    jur, reg = setup_active_registrant(full_name="Move M")
    addr1 = add_address(reg["id"], reg["version"], address_type="RESIDENCE",
                        line1="1 Old St", grid_x=4000, grid_y=4000)
    refreshed = get_registrant(reg["id"])
    addr2 = add_address(reg["id"], refreshed["version"], address_type="RESIDENCE",
                        line1="9 New St", postal_code="90003", grid_x=7000, grid_y=7000)
    addr1_after = get_success_data(api.list_addresses(reg["id"], OFFICER))
    # Find addr1 in the list and assert HISTORICAL.
    listed = {a["id"]: a for a in addr1_after}
    assert listed[addr1["id"]]["status"] == "HISTORICAL"
    assert addr2["status"] == "VERIFIED"
    final = get_registrant(reg["id"])
    assert final["current_residence_address_id"] == addr2["id"]
