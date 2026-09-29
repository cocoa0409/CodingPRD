"""Branch-scoped endpoint edges: denials, zero-payload actions, listings, chains.

Each test drives the endpoint under test against preconditions it builds itself
and pins the exact figures, statuses and orderings the contract derives.
"""

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    ERR_NOISE_LIMIT_EXCEEDED,
    FABRICATION,
    LATE_CLOCK,
    OPERATIONS,
    PM,
    CaseStatus,
    ComplexityTier,
    DrawingStatus,
    FinishGrade,
    InteractiveStatus,
    MaintenanceTier,
    MaterialStatus,
    MountStatus,
    PackageStatus,
    Phase,
    Posture,
    PrototypeDecision,
    PunchStatus,
    Severity,
    UsedIn,
    Verdict,
    WindowDecision,
    WindowStatus,
    WorkClass,
    assert_counters,
    assert_ids_in_order,
    assert_index,
    assert_ledger,
    assert_unchanged,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)


def _rows(response):
    """Validate a list envelope and return its rows."""
    validate_paginated(response)
    return response.json()["data"]


def _assert_page(response, total_count, has_more=False, limit=10, offset=0):
    """Pin the four pagination fields the contract returns on every list."""
    meta = response.json()["meta"]
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more
    assert meta["limit"] == limit
    assert meta["offset"] == offset


def _codes(rows, field):
    return [row[field] for row in rows]


def test_denying_an_install_window_runs_none_of_the_approval_checks(api):
    """A window over its zone's noise ceiling and overlapping a neighbour is still deniable.

    "The `decision` is `APPROVE` or `DENY`, with an optional `denial_reason`
    recorded on a denial. On an approval four checks run in a fixed order. First
    noise: the window's `noise_dba` must be no greater than the zone's
    `max_noise_dba`, or the ruling answers `ERR_NOISE_LIMIT_EXCEEDED` (HTTP 422)
    — **unless** `requires_gallery_closure` is true, in which case the ceiling
    does not apply at all, because with the gallery closed there are no visitors
    to disturb."

    "The occupying set is every other window on the same zone — excluding the
    window being judged — whose status is `REQUESTED`, `APPROVED` or
    `IN_PROGRESS`; a `DENIED`, `COMPLETED` or `CANCELLED` window never occupies
    its zone, so cancelling one immediately frees the slot for a rival that was
    blocked a moment earlier."

    "Four collections deviate, and the deviation is part of the contract: the
    top-level project list is ordered by `created_at` descending, newest
    commission first; a project's gallery zones are ordered by
    `visitor_route_order` ascending, which is the order a visitor walks them; a
    package's review rounds are ordered by `round_number` ascending; and install
    windows, whether listed for a project or for a single zone, are ordered by
    `starts_at` ascending with `created_at` ascending as the tie-break."

    Design: Corner/endpoints/a_denial_skips_every_precondition_that_only_the_approval_branch_runs
    """
    ctx = fixtures.project_in_phase(
        api, Phase.FABRICATION, zone_overrides={"closure_allowed": True}
    )
    project_id = ctx["project_id"]
    zone_id = ctx["zone_id"]

    reason = "Half-term week; no power tools in the west gallery."
    loud = fixtures.create_window(
        api,
        project_id,
        zone_id,
        work_class=WorkClass.NOISY,
        noise_dba=95.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
    )
    assert loud["status"] == WindowStatus.REQUESTED
    assert loud["denial_reason"] is None
    assert loud["version"] == 1

    denied_loud = fixtures.decide_window(
        api, loud["id"], WindowDecision.DENY, denial_reason=reason
    )
    assert denied_loud["status"] == WindowStatus.DENIED
    assert denied_loud["denial_reason"] == reason
    assert denied_loud["version"] == 2

    closure = fixtures.create_window(
        api,
        project_id,
        zone_id,
        work_class=WorkClass.NOISY,
        noise_dba=95.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
        requires_gallery_closure=True,
    )
    approved_closure = fixtures.decide_window(
        api, closure["id"], WindowDecision.APPROVE
    )
    assert approved_closure["status"] == WindowStatus.APPROVED
    assert approved_closure["denial_reason"] is None

    overlapping = fixtures.create_window(
        api,
        project_id,
        zone_id,
        work_class=WorkClass.NOISY,
        noise_dba=95.0,
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T11:00:00Z",
    )
    refused = api.window_decision(
        overlapping["id"],
        factories.window_decision_payload(WindowDecision.APPROVE),
        OPERATIONS,
    )
    validate_error(refused, ERR_NOISE_LIMIT_EXCEEDED, 422)

    untouched = get_success_data(
        api.get_install_window(overlapping["id"], OPERATIONS), 200
    )
    assert untouched["status"] == WindowStatus.REQUESTED
    assert_unchanged(
        overlapping,
        untouched,
        ["status", "denial_reason", "version", "updated_at"],
    )

    denied_overlapping = fixtures.decide_window(
        api, overlapping["id"], WindowDecision.DENY
    )
    assert denied_overlapping["status"] == WindowStatus.DENIED
    assert denied_overlapping["denial_reason"] is None
    assert denied_overlapping["version"] == 2

    denials = api.list_zone_install_windows(
        zone_id, OPERATIONS, {"status": WindowStatus.DENIED}
    )
    assert_ids_in_order(_rows(denials), [loud["id"], overlapping["id"]])
    _assert_page(denials, total_count=2)

    approvals = api.list_zone_install_windows(
        zone_id, OPERATIONS, {"status": WindowStatus.APPROVED}
    )
    assert_ids_in_order(_rows(approvals), [closure["id"]])
    _assert_page(approvals, total_count=1)


def test_the_empty_body_actions_advance_one_field_and_bump_one_version(api):
    """Screening, opening a review and recording a build each move one field only.

    "Moving a material into review is done by a `FabricationLead` or a
    `ProjectManager`, and the status may be `SUBMITTED`, `REJECTED`, `APPROVED`
    or `CONDITIONAL`; anything else answers `ERR_INVALID_MATERIAL_STATE`."

    "That alone raises the project's `pending_material_count` and is enough to
    make an otherwise clean project `RESTRICTED`, and it increments the project's
    `version`."

    "Both set `decided_at` to the logical-clock instant, drop the material out of
    `pending_material_count`, and recompute posture — so clearing the last
    pending material is what returns a project to `OPEN`."

    "A `ProjectManager` takes a submitted sheet into review, moving `SUBMITTED →
    UNDER_REVIEW`; any other starting status answers
    `ERR_INVALID_DRAWING_STATE`. The ruling that follows is also the
    `ProjectManager`'s, and it is where the money moves."

    "Marking a station built is the `FabricationLead`'s, requires status exactly
    `PROTOTYPE_APPROVED` — anything else, including a station still `SPECIFIED`,
    answers `ERR_PROTOTYPE_NOT_APPROVED` — requires the project to be in
    `FABRICATION` or `INSTALLATION` and not frozen, and lands it at
    `FABRICATED`."

    "The cost model has three line items, and **each is rounded to whole cents
    before the three are summed**. Labour is the hours multiplied by the shop rate
    for the sheet's complexity tier multiplied by a labour multiplier: the shop
    charges 95 dollars per hour at `STANDARD`, 145 dollars per hour at `PRECISION`
    and 185 dollars per hour at `CONSERVATION_GRADE`, recorded as 9,500, 14,500
    and 18,500 cents per hour respectively. Material is the `material_area_m2`
    multiplied by the rate for the **material's** `used_in` assembly multiplied by
    a waste factor, where the rates per square metre are 42,500 cents for
    `CASE_INTERIOR`, 31,000 for `CASE_EXTERIOR`, 58,000 for `MOUNT`, 12,500 for
    `GRAPHIC` and 47,500 for `INTERACTIVE_HOUSING`. Finishing is a percentage of
    the **already-rounded** material line item — 0 percent for `MILL`, 7.5 percent
    for `SATIN` and 13.5 percent for `MUSEUM_GLOSS` — and it too is rounded to
    whole cents. The total is the plain sum of the three rounded line items."

    "At issue it runs as a **schematic estimate**: the hours are the submitted
    `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and
    the waste factor is the schematic allowance of 1.20."

    "The index is 100 less the three penalties plus a prototype credit, capped
    above at 100.0, and rounded half up to two decimal places."

    "The `maintenance_tier` is then derived from `durability_index_verified` when
    that field is non-null and from `durability_index_spec` otherwise, with
    inclusive lower boundaries: at least 80 is `LOW`, at least 60 is `MEDIUM`, at
    least 40 is `HIGH`, and anything below 40 is `CRITICAL`."

    Design: Corner/endpoints/the_zero_payload_action_endpoints_advance_one_field_and_bump_one_version
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    interactive_id = ctx["interactive_id"]

    get_success_data(
        api.submit_prototype(interactive_id, factories.prototype_payload(), FABRICATION),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            PM,
        ),
        200,
    )

    housing = fixtures.create_material(
        api,
        project_id,
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    assert housing["status"] == MaterialStatus.SUBMITTED
    assert housing["verdict"] == Verdict.CONSERVATION_SAFE
    assert housing["version"] == 1
    assert housing["conditions"] is None
    assert housing["decided_at"] is None

    pending = fixtures.read_project(api, project_id)
    assert_counters(pending, pending_material_count=1, posture=Posture.RESTRICTED)
    assert_ledger(pending, 0, 9000000)

    screened = get_success_data(
        api.submit_material_for_conservation(housing["id"], PM), 200
    )
    assert screened["status"] == MaterialStatus.CONSERVATOR_REVIEW
    assert screened["version"] == 2
    assert screened["verdict"] == Verdict.CONSERVATION_SAFE
    assert screened["conditions"] is None
    assert screened["decided_at"] is None

    still_pending = fixtures.read_project(api, project_id)
    assert_counters(still_pending, pending_material_count=1, posture=Posture.RESTRICTED)

    cleared = get_success_data(
        api.material_conservator_decision(
            housing["id"], factories.material_decision_payload(), CONSERVATOR
        ),
        200,
    )
    assert cleared["status"] == MaterialStatus.APPROVED

    sheet = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        drawing_number="SD-801",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=8.0,
        material_area_m2=0.5,
        finish_grade=FinishGrade.MILL,
        subject_interactive_id=interactive_id,
    )
    assert sheet["status"] == DrawingStatus.SUBMITTED
    assert sheet["version"] == 1
    assert sheet["actual_cost_cents"] is None
    assert sheet["estimate_labor_cents"] == 87400
    assert sheet["estimate_material_cents"] == 28500
    assert sheet["estimate_finishing_cents"] == 0
    assert sheet["estimate_total_cents"] == 115900

    opened = get_success_data(api.start_drawing_review(sheet["id"], PM), 200)
    assert opened["status"] == DrawingStatus.UNDER_REVIEW
    assert opened["version"] == 2
    assert opened["actual_shop_hours"] is None
    assert opened["actual_waste_factor"] is None
    assert opened["actual_labor_cents"] is None
    assert opened["actual_material_cents"] is None
    assert opened["actual_finishing_cents"] is None
    assert opened["actual_cost_cents"] is None
    assert opened["estimate_total_cents"] == 115900

    unmoved = fixtures.read_project(api, project_id)
    assert_ledger(unmoved, 0, 9000000)
    assert_counters(unmoved, pending_material_count=0, posture=Posture.OPEN)

    prototyped = get_success_data(api.get_interactive(interactive_id, FABRICATION), 200)
    assert prototyped["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert_index(prototyped["durability_index_verified"], 87.58)
    assert prototyped["maintenance_tier"] == MaintenanceTier.LOW
    assert prototyped["prototype_iteration"] == 1

    built = get_success_data(api.mark_fabricated(interactive_id, FABRICATION), 200)
    assert built["status"] == InteractiveStatus.FABRICATED
    assert_index(built["durability_index_verified"], 87.58)
    assert built["maintenance_tier"] == MaintenanceTier.LOW
    assert built["prototype_iteration"] == 1
    assert built["version"] == prototyped["version"] + 1
    assert_unchanged(
        prototyped,
        built,
        [
            "durability_index_spec",
            "durability_index_verified",
            "maintenance_tier",
            "prototype_iteration",
            "measured_daily_uses",
            "measured_mtbf_cycles",
        ],
    )


def test_the_child_listings_and_the_each_filter_strictly_by_their_own_columns(api):
    """Case, interactive and defect filters AND together and never widen the result.

    "A project's cases may be listed with `status`, `mount_status` and `zone_id`
    filters, and a single case read returns both state dimensions together with
    the full derived envelope."

    "The project-scoped interactive list accepts `status` and `maintenance_tier`
    filters, and an interactive may be read individually with both index figures
    and its derived tier."

    "The `maintenance_tier` is then derived from `durability_index_verified` when
    that field is non-null and from `durability_index_spec` otherwise, with
    inclusive lower boundaries: at least 80 is `LOW`, at least 60 is `MEDIUM`, at
    least 40 is `HIGH`, and anything below 40 is `CRITICAL`."

    "The item may point at one subject — either an `interactive_id` or a
    `case_id`, both of which must belong to the same project — but naming both at
    once is `ERR_INVALID_REQUEST`, and naming neither is a general project-level
    defect."

    "The project-scoped punch list accepts `status` and `severity`; the global
    list accepts `project_id`, `interactive_id`, `case_id`, `status` and
    `severity`."

    "Unless a list is explicitly documented otherwise, results are ordered by
    `created_at` ascending — oldest first."

    "The four pagination fields `limit`, `offset`, `total_count` and `has_more`
    are returned inside `meta` on every list response, where `total_count` is the
    number of rows matching the filters before the window is applied and
    `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/the_three_remaining_child_listings_filter_strictly_by_their_own_columns
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    zone_id = ctx["zone_id"]
    case_id = ctx["case_id"]
    interactive_id = ctx["interactive_id"]

    fixtures.place_artifact(api, case_id, ctx["artifact_id"])
    fixtures.approve_case(api, case_id)
    sheet = fixtures.create_drawing(
        api, project_id, ctx["material_id"], subject_case_id=case_id
    )
    fixtures.approve_drawing(api, sheet["id"])

    get_success_data(
        api.submit_prototype(interactive_id, factories.prototype_payload(), FABRICATION),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    get_success_data(api.mark_fabricated(interactive_id, FABRICATION), 200)

    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_DESIGN)
    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_FABRICATED)
    fixtures.advance(api, project_id, Phase.INSTALLATION)

    window = fixtures.create_window(
        api,
        project_id,
        zone_id,
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    fixtures.decide_window(api, window["id"])
    fixtures.set_clock(api, LATE_CLOCK)
    fixtures.start_window(api, window["id"])
    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_INSTALLED)
    fixtures.complete_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.COMMISSIONING)

    every_case = api.list_artifact_cases(project_id, CURATOR)
    rows = _rows(every_case)
    assert _codes(rows, "case_code") == ["C-01"]
    assert rows[0]["status"] == CaseStatus.APPROVED
    assert rows[0]["mount_status"] == MountStatus.MOUNT_INSTALLED
    _assert_page(every_case, total_count=1)

    draft_cases = api.list_artifact_cases(
        project_id, CURATOR, {"status": CaseStatus.DRAFT}
    )
    assert _rows(draft_cases) == []
    _assert_page(draft_cases, total_count=0)

    installed_in_zone = api.list_artifact_cases(
        project_id,
        CURATOR,
        {"mount_status": MountStatus.MOUNT_INSTALLED, "zone_id": zone_id},
    )
    assert_ids_in_order(_rows(installed_in_zone), [case_id])
    _assert_page(installed_in_zone, total_count=1)

    designing_in_zone = api.list_artifact_cases(
        project_id,
        CURATOR,
        {"mount_status": MountStatus.MOUNT_DESIGN, "zone_id": zone_id},
    )
    assert _rows(designing_in_zone) == []
    _assert_page(designing_in_zone, total_count=0)

    fabricated = api.list_interactives(
        project_id, FABRICATION, {"status": InteractiveStatus.FABRICATED}
    )
    stations = _rows(fabricated)
    assert _codes(stations, "code") == ["INT-STRATA"]
    assert stations[0]["maintenance_tier"] == MaintenanceTier.LOW
    assert_index(stations[0]["durability_index_verified"], 87.58)
    _assert_page(fabricated, total_count=1)

    critical = api.list_interactives(
        project_id, FABRICATION, {"maintenance_tier": MaintenanceTier.CRITICAL}
    )
    assert _rows(critical) == []
    _assert_page(critical, total_count=0)

    low_tier = api.list_interactives(
        project_id, FABRICATION, {"maintenance_tier": MaintenanceTier.LOW}
    )
    assert_ids_in_order(_rows(low_tier), [interactive_id])
    _assert_page(low_tier, total_count=1)

    on_station = fixtures.raise_punch_item(
        api,
        project_id,
        headers=PM,
        severity=Severity.MAJOR,
        description="Touchscreen registers a ghost touch in the lower third.",
        interactive_id=interactive_id,
    )
    on_case = fixtures.raise_punch_item(
        api,
        project_id,
        headers=OPERATIONS,
        severity=Severity.MINOR,
        description="Case gasket proud of the frame on the hinge side.",
        case_id=case_id,
    )
    on_gallery = fixtures.raise_punch_item(
        api,
        project_id,
        headers=CURATOR,
        severity=Severity.MINOR,
        description="Gallery entry vinyl misaligned with the threshold.",
    )
    assert on_gallery["interactive_id"] is None
    assert on_gallery["case_id"] is None

    every_defect = api.list_punch_items(PM, {"project_id": project_id})
    assert_ids_in_order(
        _rows(every_defect), [on_station["id"], on_case["id"], on_gallery["id"]]
    )
    _assert_page(every_defect, total_count=3)

    station_defects = api.list_punch_items(PM, {"interactive_id": interactive_id})
    assert_ids_in_order(_rows(station_defects), [on_station["id"]])
    _assert_page(station_defects, total_count=1)

    case_defects = api.list_punch_items(PM, {"case_id": case_id})
    assert_ids_in_order(_rows(case_defects), [on_case["id"]])
    _assert_page(case_defects, total_count=1)

    minor_defects = api.list_punch_items(
        PM, {"project_id": project_id, "severity": Severity.MINOR}
    )
    assert_ids_in_order(_rows(minor_defects), [on_case["id"], on_gallery["id"]])
    _assert_page(minor_defects, total_count=2)

    verified_defects = api.list_punch_items(
        PM, {"project_id": project_id, "status": PunchStatus.VERIFIED}
    )
    assert _rows(verified_defects) == []
    _assert_page(verified_defects, total_count=0)


def test_the_supersede_pointer_names_the_immediate_successor(api):
    """Three packages of one stage form a one-hop chain, not a star on the newest.

    "Every existing package of this project whose `stage` matches the new one and
    whose status is not already `SUPERSEDED` — that is, any package in `DRAFT`,
    `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to
    `SUPERSEDED`, processed in ascending `created_at` order, and has its
    `superseded_by_package_id` set to the new package's identifier."

    "Because the self-referential pointer runs from the old package to the new
    one, the set of packages a given package displaced is readable in reverse,
    oldest first."

    "A package that passes is stored in status `DRAFT` with `review_round_count`
    and `revision_count` both 0, `submitted_by_user_id` taken from the caller's
    header, `approved_at` null and `superseded_by_package_id` null."

    "Each superseded package and each closed round has its own `updated_at`
    refreshed and `version` incremented."

    Design: Corner/endpoints/the_supersede_pointer_names_the_immediate_successor_not_the_newest_package
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    first = fixtures.create_package(api, project_id)
    assert first["status"] == PackageStatus.DRAFT
    assert first["superseded_by_package_id"] is None
    assert first["version"] == 1

    version_before_second = fixtures.project_version(api, project_id)
    second = fixtures.create_package(
        api, project_id, expected_project_version=version_before_second
    )
    version_before_third = fixtures.project_version(api, project_id)
    assert version_before_third == version_before_second + 1

    third = fixtures.create_package(
        api, project_id, expected_project_version=version_before_third
    )
    assert third["status"] == PackageStatus.DRAFT
    assert third["superseded_by_package_id"] is None
    assert fixtures.project_version(api, project_id) == version_before_third + 1

    oldest = get_success_data(api.get_design_package(first["id"], ACCESSIBILITY), 200)
    assert oldest["status"] == PackageStatus.SUPERSEDED
    assert oldest["superseded_by_package_id"] == second["id"]
    assert oldest["version"] == 2

    middle = get_success_data(api.get_design_package(second["id"], ACCESSIBILITY), 200)
    assert middle["status"] == PackageStatus.SUPERSEDED
    assert middle["superseded_by_package_id"] == third["id"]
    assert middle["version"] == 2

    newest = get_success_data(api.get_design_package(third["id"], ACCESSIBILITY), 200)
    assert newest["status"] == PackageStatus.DRAFT
    assert newest["superseded_by_package_id"] is None
    assert newest["version"] == 1

    displaced_by_third = api.list_superseded_packages(third["id"], ACCESSIBILITY)
    assert_ids_in_order(_rows(displaced_by_third), [second["id"]])
    _assert_page(displaced_by_third, total_count=1)

    displaced_by_second = api.list_superseded_packages(second["id"], ACCESSIBILITY)
    rows = _rows(displaced_by_second)
    assert_ids_in_order(rows, [first["id"]])
    assert rows[0]["status"] == PackageStatus.SUPERSEDED
    _assert_page(displaced_by_second, total_count=1)

    displaced_by_first = api.list_superseded_packages(first["id"], ACCESSIBILITY)
    assert _rows(displaced_by_first) == []
    _assert_page(displaced_by_first, total_count=0)
