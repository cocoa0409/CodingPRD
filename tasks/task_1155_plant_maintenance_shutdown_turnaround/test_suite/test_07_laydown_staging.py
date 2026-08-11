"""Lay-down areas and staging reservations: aggregate occupancy input set,
inclusive capacity boundary, reservation OCC, and the reserve/stage/release
space-ledger invariant."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    assert_laydown_occupancy_invariant,
    create_laydown_area,
    create_reservation,
    invite_contractor,
    setup_scope_frozen,
    make_supervisor_headers,
)


def test_occupancy_counts_only_reserved_and_staged(
    api, manager_headers, planner_headers
):
    """PRD §3.7: "Occupancy is an aggregate figure: an area's `occupied_sqm` is
    always the sum of `area_sqm` over its reservations standing in `RESERVED`
    or `STAGED`."
    PRD §3.7: "Releasing is the compensating action and takes two forms
    depending on where the reservation stands: releasing a `STAGED` reservation
    moves it to `RELEASED`, while releasing a still-`RESERVED` one moves it to
    `CANCELLED`; both subtract the reservation's `area_sqm` from the area's
    `occupied_sqm` and increment the area's `version`."

    Design: Corner/calculations/laydown_occupancy_excludes_released
    """
    ta, _items = setup_scope_frozen(name="TA-OC")
    contractor = invite_contractor(ta["id"], headcount_cap=3)
    area = create_laydown_area(ta["id"], capacity_sqm=500)
    assert area["version"] == 1

    r1 = create_reservation(area["id"], area["version"],
                            material_description="R1", area_sqm=120)
    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    r2 = create_reservation(area["id"], area["version"],
                            material_description="R2", area_sqm=80)
    validate_success(
        api.stage_reservation(r2["id"], make_supervisor_headers(contractor["id"]))
    )
    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    r3 = create_reservation(area["id"], area["version"],
                            material_description="R3", area_sqm=50)
    validate_success(
        api.release_reservation(r3["id"], make_supervisor_headers(contractor["id"]))
    )

    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    reservations = validate_success(
        api.list_reservations(area["id"], planner_headers)
    )
    assert_laydown_occupancy_invariant(area, reservations)
    # R1 120 RESERVED + R2 80 STAGED; R3 50 left the input set on release
    assert area["occupied_sqm"] == 200, (
        f"RELEASED/CANCELLED reservations must not count: {area['occupied_sqm']} != 200"
    )
    # area version: 1 at creation, +1 per occupancy-changing write
    # (3 reservations + 1 release); staging does not move the area
    assert area["version"] == 5, f"area version {area['version']} != 5"
    by_id = {r["id"]: r for r in reservations}
    assert by_id[r1["id"]]["status"] == "RESERVED"
    assert by_id[r2["id"]]["status"] == "STAGED"
    assert by_id[r3["id"]]["status"] == "CANCELLED"


def test_laydown_capacity_admits_equality_and_rejects_excess(api, planner_headers):
    """PRD §3.7: "Capacity is enforced with aggregate semantics — staging
    windows may overlap freely because the space is shared — and the sole check
    is that the area's current `occupied_sqm` plus the candidate `area_sqm`
    does not exceed `capacity_sqm`; exact equality is admitted, and any excess
    is rejected with `ERR_LAYDOWN_CAPACITY_EXCEEDED`."

    Design: Corner/errors/laydown_capacity_boundary
    """
    ta, _items = setup_scope_frozen(name="TA-LCB")
    area = create_laydown_area(ta["id"], capacity_sqm=500)
    create_reservation(area["id"], area["version"],
                       material_description="Big skid", area_sqm=450)
    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    assert area["occupied_sqm"] == 450

    # 450 + 60 > 500 -> rejected
    resp = api.create_reservation(
        area["id"],
        {
            "material_description": "Too big", "area_sqm": 60,
            "window_from": "2026-06-10T00:00:00Z",
            "window_until": "2026-06-20T00:00:00Z",
            "expected_laydown_area_version": area["version"],
        },
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LAYDOWN_CAPACITY_EXCEEDED)

    # the failed attempt consumed nothing: 450 + 50 == 500 is admitted at the
    # same observed version
    exact = validate_success(
        api.create_reservation(
            area["id"],
            {
                "material_description": "Exact fit", "area_sqm": 50,
                "window_from": "2026-06-10T00:00:00Z",
                "window_until": "2026-06-20T00:00:00Z",
                "expected_laydown_area_version": area["version"],
            },
            planner_headers,
        ),
        201,
    )
    assert exact["status"] == "RESERVED"

    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    assert area["occupied_sqm"] == 500
    assert area["version"] == 3


def test_reservation_with_stale_area_version_rejected(api, planner_headers):
    """PRD §2.7: "A request to create a staging reservation must carry
    `expected_laydown_area_version`, holding the `version` of the lay-down area
    as the client last observed it. Since creating a reservation commits shared
    capacity computed from the area's `occupied_sqm` at read time, a mismatch
    with the area's current `version` — because another reservation or release
    has already been applied — is likewise rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_laydown_reservation_stale_area
    """
    ta, _items = setup_scope_frozen(name="TA-OCC2")
    area = create_laydown_area(ta["id"], capacity_sqm=500)
    observed_version = area["version"]
    assert observed_version == 1

    r1 = create_reservation(area["id"], observed_version,
                            material_description="R1", area_sqm=120)
    assert r1["status"] == "RESERVED"

    # capacity would admit R2, but the expected version is now stale
    resp = api.create_reservation(
        area["id"],
        {
            "material_description": "R2", "area_sqm": 100,
            "window_from": "2026-06-10T00:00:00Z",
            "window_until": "2026-06-20T00:00:00Z",
            "expected_laydown_area_version": observed_version,
        },
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    assert area["version"] == 2, "the rejected reservation must leave no trace"
    assert area["occupied_sqm"] == 120


def _setup_area_with_reservation(api, planner_headers):
    """SCOPE_FROZEN turnaround with an invited contractor; area (capacity 500)
    carrying one 120-sqm reservation. Returns (contractor, area, reservation)."""
    ta, _items = setup_scope_frozen(name="TA-SPC")
    contractor = invite_contractor(ta["id"], headcount_cap=5)
    area = create_laydown_area(ta["id"], capacity_sqm=500)
    reservation = create_reservation(
        area["id"], area["version"],
        material_description="Fresh catalyst drums", area_sqm=120,
    )
    return contractor, area["id"], reservation


def test_reserve_and_stage_track_space_ledger(api, planner_headers):
    """PRD §3.7: "A successful reservation is created `RESERVED`, the area's
    `occupied_sqm` rises by `area_sqm`, and the area's `version` increments by
    one, recorded on each reservation as `laydown_area_id`."
    PRD §3.7: "When material physically arrives, a `ContractorSupervisor`
    stages the reservation, moving `RESERVED` to `STAGED` — occupancy does not
    change, since the space was already committed."

    Design: Difficulty/compensating_invariant/reservation_reserve_then_release_restores_space_ledger
    """
    contractor, area_id, reservation = _setup_area_with_reservation(api, planner_headers)

    area = validate_success(api.get_laydown_area(area_id, planner_headers))
    assert area["occupied_sqm"] == 120
    assert area["version"] == 2

    staged = validate_success(
        api.stage_reservation(reservation["id"], make_supervisor_headers(contractor["id"]))
    )
    assert staged["status"] == "STAGED"

    area = validate_success(api.get_laydown_area(area_id, planner_headers))
    reservations = validate_success(api.list_reservations(area_id, planner_headers))
    assert_laydown_occupancy_invariant(area, reservations)
    assert area["occupied_sqm"] == 120, "staging does not change occupancy"
    assert area["version"] == 2, "staging must not bump the area's version"


def test_release_restores_space_ledger_exactly(api, planner_headers):
    """PRD §3.7: "Releasing is the compensating action and takes two forms
    depending on where the reservation stands: releasing a `STAGED` reservation
    moves it to `RELEASED`, while releasing a still-`RESERVED` one moves it to
    `CANCELLED`; both subtract the reservation's `area_sqm` from the area's
    `occupied_sqm` and increment the area's `version`."
    PRD §3.7: "Occupancy is an aggregate figure: an area's `occupied_sqm` is
    always the sum of `area_sqm` over its reservations standing in `RESERVED`
    or `STAGED`."

    Design: Difficulty/compensating_invariant/reservation_reserve_then_release_restores_space_ledger
    """
    contractor, area_id, reservation = _setup_area_with_reservation(api, planner_headers)
    validate_success(
        api.stage_reservation(reservation["id"], make_supervisor_headers(contractor["id"]))
    )

    released = validate_success(
        api.release_reservation(reservation["id"], make_supervisor_headers(contractor["id"]))
    )
    assert released["status"] == "RELEASED"

    area = validate_success(api.get_laydown_area(area_id, planner_headers))
    reservations = validate_success(api.list_reservations(area_id, planner_headers))
    assert_laydown_occupancy_invariant(area, reservations)
    assert area["occupied_sqm"] == 0, "reserve 120 then release must restore 0"
    assert area["version"] == 3, f"reserve bumped to 2, release to 3: got {area['version']}"
