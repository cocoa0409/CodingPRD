"""Revision tokens, role gates and the promise that a response is already settled."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_scene,
    advance_to,
    create_design_package_payload,
    create_ride_system_payload,
    open_project,
    project_version,
    read_budget_position,
    read_capacity_summary,
    read_ledger,
    read_project,
    register_ride_system,
    select_ride,
    submit_package,
    validate_error,
    validate_paginated,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
REVIEWER = TEST_USERS["third_party_reviewer_headers"]

PACKAGE = {"package_label": "Ride And Controls Release 1",
           "discipline_scope": "RIDE_AND_CONTROLS",
           "base_construction_cost_cents": 400000000}


def test_the_ride_engineer_both_registers_and_revises_its_own_system(api):
    """A `RideEngineer` registers each vendor offer as a candidate ride system against a programme, supplying `project_id`, the manufacturer's `vendor_name` (1 to 120 characters), the `system_type` — one of `DARK_RIDE_TRACKLESS`, `OMNIMOVER`, `LAUNCH_COASTER`, `BOAT_FLUME` or `MOTION_BASE_THEATER` — and seven engineering parameters: `vehicle_count` (at least 1), `riders_per_vehicle` (at least 1), `block_zone_count` (at least 2), `cycle_time_seconds` (at least 1), `availability_pct` and `load_efficiency_pct` (each greater than 0 and at most 100, two decimal places), and `show_stops_per_hour` (at least 0, two decimal places).

    A `RideEngineer` may revise the engineering parameters — supplying the required
    `expected_ride_system_version` plus any subset of `vehicle_count`,
    `riders_per_vehicle`, `block_zone_count`, `cycle_time_seconds`,
    `availability_pct`, `load_efficiency_pct` and `show_stops_per_hour` — which
    recomputes `dispatch_interval_seconds` and both capacity variants and advances the
    row's `version`.

    The engineer owns this row from end to end: the same role that registered the
    offer revises it, and dropping availability from 96 to 90 leaves the theoretical
    1440 untouched while the derated figure moves 1179 to 1101, which only a genuine
    re-derivation produces.

    Design: Corner/rbac/ride_engineer_may_create_and_then_patch_its_own_ride_system
    """
    project = open_project(project_code="TAD-RB1")

    created = validate_success(
        api.create_ride_system(create_ride_system_payload(project["id"]), ENGINEER), 201)
    patched = validate_success(
        api.patch_ride_system(
            created["id"],
            {"expected_ride_system_version": created["version"], "availability_pct": 90},
            ENGINEER,
        ),
        200,
    )

    assert created["operational_hourly_capacity_guests"] == 1179
    assert patched["theoretical_hourly_capacity_guests"] == 1440
    assert patched["operational_hourly_capacity_guests"] == 1101
    assert patched["version"] == 2
    assert patched["status"] == "CANDIDATE"
    assert float(patched["availability_pct"]) == 90.0


def test_a_creative_director_is_refused_the_ledger_before_the_body_is_resolved(api):
    """A request whose role is well-formed but is not listed for the target endpoint in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    An `OwnerRep` posts a change order by supplying `project_id`, an `entry_kind` of
    `CHANGE_ORDER`, a signed `amount_cents` where a positive value increases committed
    cost and a negative value decreases it, a `memo` of 1 to 200 characters describing
    the entry, and the required `expected_project_version`.

    Body foreign keys resolve — the resource-specific 404 from §2.5.

    The payload also names a programme that does not exist, which would ordinarily be
    answered with the programme 404, yet the role gate sits above body resolution and
    answers first; no entry is written.

    Design: Corner/rbac/creative_director_cannot_post_a_budget_ledger_entry
    """
    project = open_project(project_code="TAD-RB2")

    response = api.create_ledger_entry(
        {
            "project_id": "99999999-8888-4777-8666-555544443333",
            "entry_kind": "CHANGE_ORDER",
            "amount_cents": 500000000,
            "memo": "Unauthorised change order",
            "expected_project_version": project["version"],
        },
        DESIGNER,
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    rows, meta = read_ledger(project["id"])
    assert rows == []
    assert meta["total_count"] == 0


def test_a_ceiling_patch_invalidates_a_held_token_for_a_package_create(api):
    """**Creating a design package** (`POST /design-packages`) must carry `expected_project_version` matching the programme's current `version`. A new package legitimately competes with any other package already in flight for the same programme — approving one supersedes the previously approved one — so a second create observing the same programme state would otherwise go through. If another writer has advanced the programme's `version` since the client last read it, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), which pins the create to the exact programme revision the pricing assumptions were derived from.

    A mismatch is rejected before any business rule is evaluated, with HTTP 412 and no
    change to any stored row.

    The token belongs to the parent programme rather than to the package, so a patch
    that only raises the ceiling is enough to invalidate it; replaying the byte-identical
    payload with the revision that patch returned succeeds, which proves the refusal
    was about staleness alone.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_project_version_on_package_create_returns_412
    """
    project = open_project(project_code="TAD-CC1")
    ride = register_ride_system(project["id"])
    patched = validate_success(
        api.patch_project(
            project["id"],
            {"expected_project_version": project["version"],
             "budget_ceiling_cents": 3800000000},
            OWNER,
        )
    )
    assert patched["version"] == 2

    stale = api.create_design_package(
        create_design_package_payload(project["id"], ride["id"], project["version"],
                                      package_label="Show Set Release 1",
                                      discipline_scope="SHOW_SET",
                                      base_construction_cost_cents=400000000),
        DESIGNER,
    )
    replayed = validate_success(
        api.create_design_package(
            create_design_package_payload(project["id"], ride["id"], patched["version"],
                                          package_label="Show Set Release 1",
                                          discipline_scope="SHOW_SET",
                                          base_construction_cost_cents=400000000),
            DESIGNER,
        ),
        201,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)
    assert replayed["total_cost_of_work_cents"] == 515200000
    assert replayed["status"] == "DRAFT"
    _, meta = validate_paginated(
        api.list_design_packages(DESIGNER, params={"project_id": project["id"]}))
    assert meta["total_count"] == 1


def test_an_approval_leaves_the_reviewer_holding_a_stale_package_token(api):
    """**Opening a safety review** (`POST /safety-reviews`) must carry `expected_package_version` matching the package's current `version`. A package may legitimately carry several reviews against different `standard_code` values, so a second sequential create sees identical package state and would otherwise succeed. If the package's `version` has advanced since the reviewer read it, the create is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412), guaranteeing that the review records the exact package revision that was assessed.

    Version pinning — `ERR_STALE_PROJECT_VERSION`, `ERR_STALE_PACKAGE_VERSION` or
    `ERR_STALE_RIDE_SYSTEM_VERSION` (412).

    The review is written with `reviewer_user_id` set to the opening caller's
    `X-User-ID`, `status` `IN_REVIEW`, `open_finding_count` 0 and `cleared_at` null,
    and — as noted in §2.6 — the act of opening it increments the *package's* `version`
    by one.

    The reviewer's token is the revision it saw at submit time and the owner's approval
    has moved the package on since; the token check sits above the package-state check,
    so the answer is staleness and not the approved status, and the replay with the
    approval's revision opens the review normally.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_package_version_on_review_create_returns_412
    """
    project = open_project(project_code="TAD-CC2")
    ride = register_ride_system(project["id"])
    package = validate_success(
        api.create_design_package(
            create_design_package_payload(project["id"], ride["id"],
                                          project["version"], **PACKAGE),
            DESIGNER,
        ),
        201,
    )
    submitted = submit_package(package["id"])
    approved = validate_success(
        api.approve_design_package(
            package["id"], {"expected_package_version": submitted["version"]}, OWNER)
    )
    assert submitted["version"] == 2
    assert approved["version"] == 3

    stale = api.create_safety_review(
        {"design_package_id": package["id"], "standard_code": "ASTM_F2291",
         "expected_package_version": submitted["version"]},
        REVIEWER,
    )
    replayed = validate_success(
        api.create_safety_review(
            {"design_package_id": package["id"], "standard_code": "ASTM_F2291",
             "expected_package_version": approved["version"]},
            REVIEWER,
        ),
        201,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PACKAGE_VERSION.value, 412)
    assert replayed["status"] == "IN_REVIEW"
    assert validate_success(
        api.get_design_package(package["id"], DESIGNER))["status"] == "APPROVED"


def test_a_stale_token_blocks_a_select_the_capacity_gate_would_have_allowed(api):
    """**Selecting a ride system** (`POST /ride-systems/{id}/select`) must carry `expected_project_version` matching the programme's current `version`. Selection legitimately supersedes the previously selected candidate, which cascades back to `CANDIDATE`, so a second sequential select sees state it may legally overwrite. If the programme's `version` has advanced since the owner read it, the select is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), forcing the owner to re-read the programme — including its `required_hourly_capacity_guests` — before overriding the earlier choice.

    On success the row becomes `SELECTED`; any *other* ride system of the same
    programme that was `SELECTED` cascades back to `CANDIDATE` with its own `version`
    incremented by one; the programme's `selected_ride_system_id` is set to this row's
    `id`; and the programme's `version` advances.

    The path names a ride system but the write lands on the programme, so the token is
    the programme's; this candidate comfortably clears the 800-guest target, which
    makes the 412 attributable to the token alone, and the mirror field stays null
    until the replay goes through.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_project_version_on_ride_system_select_returns_412
    """
    project = open_project(project_code="TAD-CC3")
    ride = register_ride_system(project["id"])
    patched = validate_success(
        api.patch_project(
            project["id"],
            {"expected_project_version": project["version"],
             "budget_ceiling_cents": 3800000000},
            OWNER,
        )
    )

    stale = api.select_ride_system(
        ride["id"], {"expected_project_version": project["version"]}, OWNER)
    validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)
    assert read_project(project["id"])["selected_ride_system_id"] is None

    selected = validate_success(
        api.select_ride_system(
            ride["id"], {"expected_project_version": patched["version"]}, OWNER),
        200,
    )

    programme = read_project(project["id"])
    assert selected["status"] == "SELECTED"
    assert programme["selected_ride_system_id"] == ride["id"]
    assert programme["version"] == 3


def test_the_ride_system_carries_its_own_token_distinct_from_the_programme_s(api):
    """`expected_ride_system_version` must equal the current `version` of the target `RideSystem`. A mismatch is rejected with `ERR_STALE_RIDE_SYSTEM_VERSION` (HTTP 412). It is required on `PATCH /ride-systems/{id}`.

    Both are recomputed on every write to the row regardless of `status`, so a
    candidate and a commissioned system are computed identically.

    One accepted revision takes the row to revision 2, and replaying the first
    revision's token is answered by the ride system's own staleness code rather than
    the programme's; the row keeps the load efficiency of 80 and the 1041 guests that
    the accepted patch derived instead of being quietly overwritten by 60.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_ride_system_version_on_patch_returns_412
    """
    project = open_project(project_code="TAD-CC4")
    ride = register_ride_system(project["id"])
    assert ride["version"] == 1
    first = validate_success(
        api.patch_ride_system(
            ride["id"],
            {"expected_ride_system_version": ride["version"], "load_efficiency_pct": 80},
            ENGINEER,
        )
    )
    assert first["version"] == 2
    assert first["operational_hourly_capacity_guests"] == 1041

    replay = api.patch_ride_system(
        ride["id"],
        {"expected_ride_system_version": ride["version"], "load_efficiency_pct": 60},
        ENGINEER,
    )

    validate_error(replay, ApiErrorId.ERR_STALE_RIDE_SYSTEM_VERSION.value, 412)
    stored = validate_success(api.get_ride_system(ride["id"], ENGINEER))
    assert float(stored["load_efficiency_pct"]) == 80.0
    assert stored["operational_hourly_capacity_guests"] == 1041
    assert stored["version"] == 2


def test_an_engineering_revision_after_submit_invalidates_the_approval(api):
    """Approval is the owner's decision and the single most consequential write in the system. Only an `OwnerRep` may approve, only from `SUBMITTED`, and only with the required `expected_package_version`. Five conditions must hold, and per §2.10 they are evaluated in this order after the posture and state checks: the posture must not be `FROZEN`; the approving caller's `X-User-ID` must differ from the recorded `submitted_by_user_id`, since a party may not approve its own submission even when that party legitimately holds `OwnerRep` — a self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`; the `pinned_ride_system_version` must still equal the current `version` of the ride system named by `ride_system_id`, so that any engineering revision made after submission invalidates the approval and yields `ERR_PINNED_REFERENCE_STALE`; and the programme's `committed_cost_cents` plus this package's `total_cost_of_work_cents` must not exceed `budget_ceiling_cents`, or the approval is refused with `ERR_BUDGET_CEILING_EXCEEDED`.

    That version bump is consequential: it invalidates any design package that pinned
    this system's revision at submit time, as §3.5 explains.

    The package's own token is perfectly current and a different party is approving
    than submitted, so neither staleness nor segregation can be doing the work: the
    pinned revision is what fails, the package stays submitted, and nothing is
    committed or written to the ledger.

    Design: Corner/cross_cutting_complexity_layers/package_approval_rejects_a_ride_system_that_moved_after_submit
    """
    project = open_project(project_code="TAD-CC5")
    ride = register_ride_system(project["id"])
    package = validate_success(
        api.create_design_package(
            create_design_package_payload(project["id"], ride["id"],
                                          project["version"], **PACKAGE),
            DESIGNER,
        ),
        201,
    )
    submitted = submit_package(package["id"])
    revised = validate_success(
        api.patch_ride_system(
            ride["id"],
            {"expected_ride_system_version": ride["version"], "load_efficiency_pct": 80},
            ENGINEER,
        )
    )
    assert submitted["pinned_ride_system_version"] == 1
    assert revised["version"] == 2

    response = api.approve_design_package(
        package["id"], {"expected_package_version": submitted["version"]}, OWNER)

    validate_error(response, ApiErrorId.ERR_PINNED_REFERENCE_STALE.value, 409)
    stored = validate_success(api.get_design_package(package["id"], DESIGNER))
    _, ledger_meta = read_ledger(project["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_user_id"] is None
    assert read_budget_position(project["id"])["committed_cost_cents"] == 0
    assert ledger_meta["total_count"] == 0


def test_the_patch_response_already_carries_the_recomputed_capacity_target(api):
    """When `design_day_attendance` or `peak_hour_share` changes, `required_hourly_capacity_guests` is recomputed by the same rounding-up rule.

    `required_hourly_capacity_guests` is the product of `design_day_attendance` and
    `peak_hour_share`, computed as an exact decimal and then rounded up to a whole
    number of guests.

    The capacity summary reports `required_hourly_capacity_guests`,
    `selected_ride_system_id`, both capacity variants of the selected system as
    `theoretical_hourly_capacity_guests` and `operational_hourly_capacity_guests`,
    `queue_capacity_total_guests`, `accessible_capacity_guests`,
    `accessible_share_pct`, `virtual_queue_allocation_guests`, `posted_wait_minutes`
    and `show_quality_score`, recomputing the queue and show-quality roll-ups for the
    response without persisting anything.

    No settling period is allowed between the write and the read: raising the design
    day from 8000 to 12000 must report 1200 in the patch's own body, and the summary
    that follows must agree to the guest, which is the moment the selected system's
    1179 becomes a visible deficit rather than a comfortable margin.

    Design: Corner/consistency_model/immediate_consistency_shows_the_recomputed_capacity_in_the_same_patch_response
    """
    project = open_project(project_code="TAD-CM1")
    assert project["required_hourly_capacity_guests"] == 800
    add_scene(project["id"])
    ride = register_ride_system(project["id"])
    advance_to(project["id"], "CONCEPT")
    select_ride(ride["id"], project["id"])

    patched = validate_success(
        api.patch_project(
            project["id"],
            {"expected_project_version": project_version(project["id"]),
             "design_day_attendance": 12000},
            OWNER,
        ),
        200,
    )

    summary = read_capacity_summary(project["id"])
    programme = read_project(project["id"])
    assert patched["required_hourly_capacity_guests"] == 1200
    assert summary["required_hourly_capacity_guests"] == 1200
    assert summary["operational_hourly_capacity_guests"] == 1179
    assert programme["design_day_attendance"] == 12000
    assert programme["selected_ride_system_id"] == ride["id"]
