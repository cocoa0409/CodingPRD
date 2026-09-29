"""Gates that read a row the request never names.

Three admission tests in the exhibit contract are decided elsewhere: a shop
drawing's approval branch is chosen by the status of the material specification
it was issued from, a case's mount installation is unlocked only by an install
window running on that case's own gallery zone, and a sheet detailing an
interactive is held back until that station's prototype has been ruled on. Every
test builds its own commission from the endpoints of PRD sections 3.1 to 3.9 and
asserts the exact statuses, cost line items and ledger figures the PRD pins.
"""

from test_helpers import (
    CONSERVATOR,
    ERR_MATERIAL_NOT_CONSERVATION_APPROVED,
    ERR_INVALID_WINDOW_STATE,
    ERR_PROTOTYPE_NOT_APPROVED,
    ERR_SEGREGATION_OF_DUTIES,
    FABRICATION,
    PM,
    ROLE_PROJECT_MANAGER,
    USER_FABRICATION,
    ComplexityTier,
    DrawingDecision,
    DrawingStatus,
    FinishGrade,
    InteractiveStatus,
    MaintenanceTier,
    MaterialDecision,
    MaterialStatus,
    MountStatus,
    OccupancyState,
    PackageStage,
    Phase,
    PrototypeDecision,
    UsedIn,
    WindowStatus,
    assert_index,
    assert_ledger,
    assert_unchanged,
    get_success_data,
    headers_for,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONTRACT_CENTS = 9000000
#: The conditions text a conservator attaches when clearing a liner with conditions.
LINER_CONDITIONS = "vent the fabricated case for 14 days before any object goes in"


def _commission_in_fabrication(api, zone_specs=None, project_overrides=None):
    """Walk a fresh commission up to FABRICATION with its children in place.

    One gallery zone per entry in ``zone_specs`` is registered, the case is sited
    in the first of them and carries the project's primary learning objective
    while the interactive carries the second, so the objective-coverage gate on
    the advance into FABRICATION is satisfied. The case is left in DRAFT.
    """
    if zone_specs is None:
        zone_specs = [{}]
    fx.set_clock(api)
    project = fx.create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zones = [fx.create_zone(api, project_id, **spec) for spec in zone_specs]
    artifact = fx.create_artifact(api, project_id)
    interactive = fx.create_interactive(api, project_id)
    case = fx.create_case(api, project_id, zones[0]["id"])
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    return {
        "project_id": project_id,
        "zones": zones,
        "zone_id": zones[0]["id"],
        "artifact_id": artifact["id"],
        "interactive_id": interactive["id"],
        "case_id": case["id"],
    }


def _load_and_approve_case(api, ctx):
    """Reserve the collection object into the case and take the case to APPROVED."""
    fx.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    return fx.approve_case(api, ctx["case_id"])


def _conditionally_cleared_liner(api, project_id, material_name="Conditionally cleared liner"):
    """Screen a case-interior liner and clear it with conditions, landing it CONDITIONAL."""
    material = fx.create_material(
        api,
        project_id,
        material_name=material_name,
        voc_mg_per_m2_day=0.04,
        formaldehyde_ppm=0.015,
        cure_days=25,
    )
    cleared = fx.approve_material(
        api,
        material["id"],
        MaterialDecision.APPROVE_WITH_CONDITIONS,
        conditions=LINER_CONDITIONS,
    )
    assert cleared["status"] == MaterialStatus.CONDITIONAL
    return cleared


def _sheet_on_a_conditional_material(api):
    """A commission in FABRICATION whose only sheet is issued from a CONDITIONAL liner."""
    ctx = _commission_in_fabrication(api)
    _load_and_approve_case(api, ctx)
    material = _conditionally_cleared_liner(api, ctx["project_id"])
    drawing = fx.create_drawing(
        api,
        ctx["project_id"],
        material["id"],
        drawing_number="SD-602",
        subject_case_id=ctx["case_id"],
    )
    return ctx, material, drawing


# ---------------------------------------------------------------------------
# the material specification decides what the sheet may become
# ---------------------------------------------------------------------------
def test_a_material_conservation_has_not_cleared_cannot_carry_a_sheet(api):
    """A liner still awaiting a conservator blocks the sheet the cleared liner carries.

    "The named material must already be cleared: its status must be `APPROVED` or `CONDITIONAL`, and a material still `SUBMITTED` or in `CONSERVATOR_REVIEW`, or one that has been `REJECTED`, answers `ERR_MATERIAL_NOT_CONSERVATION_APPROVED` (HTTP 422) — you may not build from a material nobody has cleared."
    "Materials may be listed with `status`, `verdict` and `used_in` filters, and each material exposes the shop drawings built from it — the blast radius of a rejection, visible before the rejection happens."
    Design: Difficulty/cross_entity_state_dependency/the_drawing_decision_branch_is_selected_by_the_material_specs_status
    """
    ctx = _commission_in_fabrication(api)
    _load_and_approve_case(api, ctx)
    project_id = ctx["project_id"]
    pending = fx.create_material(
        api,
        project_id,
        material_name="Untested liner lot",
        voc_mg_per_m2_day=0.04,
        formaldehyde_ppm=0.015,
        cure_days=25,
    )
    assert pending["status"] == MaterialStatus.SUBMITTED
    conditional = _conditionally_cleared_liner(api, project_id)

    refused = api.create_shop_drawing(
        f.shop_drawing_payload(
            project_id,
            pending["id"],
            drawing_number="SD-601",
            subject_case_id=ctx["case_id"],
        ),
        FABRICATION,
    )
    validate_error(refused, ERR_MATERIAL_NOT_CONSERVATION_APPROVED, 422)

    issued = validate_success(
        api.create_shop_drawing(
            f.shop_drawing_payload(
                project_id,
                conditional["id"],
                drawing_number="SD-602",
                subject_case_id=ctx["case_id"],
            ),
            FABRICATION,
        ),
        201,
    )
    assert issued["status"] == DrawingStatus.SUBMITTED
    assert issued["material_spec_id"] == conditional["id"]

    cleared_sheets, cleared_meta = validate_paginated(
        api.list_material_shop_drawings(conditional["id"], FABRICATION)
    )
    assert [row["drawing_number"] for row in cleared_sheets] == ["SD-602"]
    assert cleared_meta["total_count"] == 1
    pending_sheets, pending_meta = validate_paginated(
        api.list_material_shop_drawings(pending["id"], FABRICATION)
    )
    assert pending_sheets == []
    assert pending_meta["total_count"] == 0


def test_the_sheet_issued_from_the_conditional_liner_prices_a_schematic_estimate(api):
    """Issue prices the advisory estimate with the schematic multipliers and moves no money.

    "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."
    "The three results land in `estimate_labor_cents`, `estimate_material_cents` and `estimate_finishing_cents`, with `estimate_total_cents` as their sum, and **no money moves** — the estimate is advisory."
    Design: Difficulty/cross_entity_state_dependency/the_drawing_decision_branch_is_selected_by_the_material_specs_status
    """
    ctx, material, drawing = _sheet_on_a_conditional_material(api)

    assert drawing["estimate_labor_cents"] == 109250
    assert drawing["estimate_material_cents"] == 51000
    assert drawing["estimate_finishing_cents"] == 0
    assert drawing["estimate_total_cents"] == 160250
    assert drawing["actual_labor_cents"] is None
    assert drawing["actual_material_cents"] is None
    assert drawing["actual_finishing_cents"] is None
    assert drawing["actual_cost_cents"] is None
    assert drawing["void_reason"] is None

    project = fx.read_project(api, ctx["project_id"])
    assert_ledger(project, 0, CONTRACT_CENTS)


def test_an_approve_against_a_conditionally_cleared_material_is_refused(api):
    """The outright approval branch reads the liner's status and refuses on CONDITIONAL.

    "A material cleared only with conditions can therefore never carry a sheet past `APPROVED_AS_NOTED`, and an `APPROVE` against such a material is refused with `ERR_MATERIAL_NOT_CONSERVATION_APPROVED`."
    Design: Difficulty/cross_entity_state_dependency/the_drawing_decision_branch_is_selected_by_the_material_specs_status
    """
    ctx, material, drawing = _sheet_on_a_conditional_material(api)
    in_review = get_success_data(api.start_drawing_review(drawing["id"], PM), 200)
    assert in_review["status"] == DrawingStatus.UNDER_REVIEW

    refused = api.drawing_decision(
        drawing["id"],
        f.drawing_decision_payload(
            DrawingDecision.APPROVE, actual_shop_hours=10.0, actual_waste_factor=1.0
        ),
        PM,
    )
    validate_error(refused, ERR_MATERIAL_NOT_CONSERVATION_APPROVED, 422)

    after = get_success_data(api.get_shop_drawing(drawing["id"], FABRICATION), 200)
    assert after["status"] == DrawingStatus.UNDER_REVIEW
    assert_unchanged(
        in_review,
        after,
        ["version", "actual_shop_hours", "actual_waste_factor", "actual_cost_cents"],
    )
    assert_ledger(fx.read_project(api, ctx["project_id"]), 0, CONTRACT_CENTS)


def test_approve_as_noted_carries_the_conditional_material_and_commits_the_actual_cost(api):
    """The as-noted branch accepts the same liner and commits the identical money.

    "`APPROVE_AS_NOTED` accepts a material that is either `APPROVED` or `CONDITIONAL` and lands the sheet in `APPROVED_AS_NOTED`."
    "The money effect of the two branches is identical; only the conservation status recorded on the sheet differs."
    Design: Difficulty/cross_entity_state_dependency/the_drawing_decision_branch_is_selected_by_the_material_specs_status
    """
    ctx, material, drawing = _sheet_on_a_conditional_material(api)
    get_success_data(api.start_drawing_review(drawing["id"], PM), 200)

    decided = validate_success(
        api.drawing_decision(
            drawing["id"],
            f.drawing_decision_payload(
                DrawingDecision.APPROVE_AS_NOTED,
                actual_shop_hours=10.0,
                actual_waste_factor=1.0,
            ),
            PM,
        ),
        200,
    )
    assert decided["status"] == DrawingStatus.APPROVED_AS_NOTED
    assert decided["actual_labor_cents"] == 95000
    assert decided["actual_material_cents"] == 42500
    assert decided["actual_finishing_cents"] == 0
    assert decided["actual_cost_cents"] == 137500
    assert decided["estimate_total_cents"] == 160250

    project = fx.read_project(api, ctx["project_id"])
    assert_ledger(project, 137500, 8862500)


# ---------------------------------------------------------------------------
# the mount reads a window on the case's own zone
# ---------------------------------------------------------------------------
#: The install shift both zones ask for, and the instant the clock is moved to.
SHIFT_START = "2026-09-10T08:00:00Z"
SHIFT_END = "2026-09-10T10:00:00Z"


def _installation_with_a_running_sibling_window(api):
    """A commission in INSTALLATION whose second zone is under install work.

    The case sits in the first zone with its mount at MOUNT_FABRICATED, and the
    only window running belongs to the sibling zone the case is not in.
    """
    ctx = _commission_in_fabrication(
        api,
        zone_specs=[
            {"zone_code": "Z-A", "visitor_route_order": 1},
            {"zone_code": "Z-B", "visitor_route_order": 2},
        ],
    )
    project_id = ctx["project_id"]
    _load_and_approve_case(api, ctx)
    material = fx.create_material(api, project_id)
    fx.approve_material(api, material["id"])
    drawing = fx.create_drawing(
        api,
        project_id,
        material["id"],
        drawing_number="SD-701",
        subject_case_id=ctx["case_id"],
    )
    fx.approve_drawing(api, drawing["id"], actual_waste_factor=1.0)
    fx.advance_mount(api, ctx["case_id"], MountStatus.MOUNT_DESIGN)
    fabricated = fx.advance_mount(api, ctx["case_id"], MountStatus.MOUNT_FABRICATED)
    assert fabricated["mount_status"] == MountStatus.MOUNT_FABRICATED

    sibling = fx.create_window(
        api,
        project_id,
        ctx["zones"][1]["id"],
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
    )
    fx.decide_window(api, sibling["id"])
    fx.advance(api, project_id, Phase.INSTALLATION)
    fx.set_clock(api, SHIFT_START)
    running = fx.start_window(api, sibling["id"])
    assert running["status"] == WindowStatus.IN_PROGRESS
    ctx["sibling_window_id"] = sibling["id"]
    ctx["sibling_zone_id"] = ctx["zones"][1]["id"]
    return ctx


def test_a_window_running_on_a_sibling_zone_does_not_unlock_the_mount(api):
    """Install work in the next gallery leaves this case's mount where it stood.

    "Entering `MOUNT_INSTALLED` requires the conservation status to be `APPROVED` or `CONDITIONALLY_APPROVED`, requires the project phase to be `INSTALLATION`, failing otherwise with `ERR_INVALID_PROJECT_PHASE`, and requires that at least one install window **on this case's own zone** is currently `IN_PROGRESS`, failing otherwise with `ERR_INVALID_WINDOW_STATE` — a window running on a sibling zone of the same project does not unlock the mount."
    Design: Difficulty/cross_entity_state_dependency/mount_installation_reads_an_install_window_on_the_cases_own_zone
    """
    ctx = _installation_with_a_running_sibling_window(api)
    before = get_success_data(api.get_artifact_case(ctx["case_id"], CONSERVATOR), 200)

    refused = api.mount_advance(
        ctx["case_id"],
        f.mount_advance_payload(MountStatus.MOUNT_INSTALLED),
        CONSERVATOR,
    )
    validate_error(refused, ERR_INVALID_WINDOW_STATE, 409)

    after = get_success_data(api.get_artifact_case(ctx["case_id"], CONSERVATOR), 200)
    assert after["mount_status"] == MountStatus.MOUNT_FABRICATED
    assert_unchanged(before, after, ["mount_status", "version"])

    own_zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    sibling_zone = get_success_data(api.get_gallery_zone(ctx["sibling_zone_id"], PM), 200)
    assert own_zone["occupancy_state"] == OccupancyState.OPERATING
    assert sibling_zone["occupancy_state"] == OccupancyState.PARTIAL_CLOSURE


def test_the_cases_own_zone_may_be_booked_for_the_very_same_shift(api):
    """The sibling zone's shift never occupies this zone, so the same hour is free here.

    "The occupying set is every other window on the same zone — excluding the window being judged — whose status is `REQUESTED`, `APPROVED` or `IN_PROGRESS`; a `DENIED`, `COMPLETED` or `CANCELLED` window never occupies its zone, so cancelling one immediately frees the slot for a rival that was blocked a moment earlier."
    Design: Difficulty/cross_entity_state_dependency/mount_installation_reads_an_install_window_on_the_cases_own_zone
    """
    ctx = _installation_with_a_running_sibling_window(api)

    own = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
    )
    decided = fx.decide_window(api, own["id"])
    assert decided["status"] == WindowStatus.APPROVED

    sibling = get_success_data(api.get_install_window(ctx["sibling_window_id"], PM), 200)
    assert sibling["status"] == WindowStatus.IN_PROGRESS


def test_starting_the_window_on_the_cases_own_zone_installs_the_mount(api):
    """Once this zone's own shift is running the identical mount step goes through.

    "The window becomes `IN_PROGRESS` and the zone's `occupancy_state` changes: to `CLOSED` when `requires_gallery_closure` is true, and to `PARTIAL_CLOSURE` otherwise."
    "Entering `MOUNT_INSTALLED` requires the conservation status to be `APPROVED` or `CONDITIONALLY_APPROVED`, requires the project phase to be `INSTALLATION`, failing otherwise with `ERR_INVALID_PROJECT_PHASE`, and requires that at least one install window **on this case's own zone** is currently `IN_PROGRESS`, failing otherwise with `ERR_INVALID_WINDOW_STATE` — a window running on a sibling zone of the same project does not unlock the mount."
    Design: Difficulty/cross_entity_state_dependency/mount_installation_reads_an_install_window_on_the_cases_own_zone
    """
    ctx = _installation_with_a_running_sibling_window(api)
    own = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        starts_at=SHIFT_START,
        ends_at=SHIFT_END,
    )
    fx.decide_window(api, own["id"])
    running = fx.start_window(api, own["id"])
    assert running["status"] == WindowStatus.IN_PROGRESS

    own_zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    assert own_zone["occupancy_state"] == OccupancyState.PARTIAL_CLOSURE

    installed = validate_success(
        api.mount_advance(
            ctx["case_id"],
            f.mount_advance_payload(MountStatus.MOUNT_INSTALLED),
            CONSERVATOR,
        ),
        200,
    )
    assert installed["mount_status"] == MountStatus.MOUNT_INSTALLED


# ---------------------------------------------------------------------------
# the sheet for a station waits on that station's prototype
# ---------------------------------------------------------------------------
def _commission_with_a_housing_material(api):
    """A commission in FABRICATION with a cleared interactive-housing material.

    The station itself is untouched, so it still stands at SPECIFIED with only
    its catalogue index computed.
    """
    ctx = _commission_in_fabrication(api)
    material = fx.create_material(
        api,
        ctx["project_id"],
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    fx.approve_material(api, material["id"])
    ctx["material_id"] = material["id"]
    return ctx


def _housing_sheet_payload(ctx, drawing_number):
    """The precision housing sheet: 20 shop hours over 5 square metres, satin finished."""
    return f.shop_drawing_payload(
        ctx["project_id"],
        ctx["material_id"],
        drawing_number=drawing_number,
        subject_interactive_id=ctx["interactive_id"],
        complexity_tier=ComplexityTier.PRECISION,
        shop_hours=20.0,
        material_area_m2=5.0,
        finish_grade=FinishGrade.SATIN,
    )


def test_a_station_still_specified_cannot_carry_a_shop_drawing(api):
    """The housing sheet is refused while the station has only a catalogue index.

    "A named subject interactive must have got past its prototype: its status must be `PROTOTYPE_APPROVED`, `FABRICATED` or `COMMISSIONED`, and anything earlier answers `ERR_PROTOTYPE_NOT_APPROVED` (HTTP 409)."
    "The **specification** variant uses `expected_daily_uses` and the catalogue `mtbf_cycles` with a prototype credit of zero, and writes `durability_index_spec`."
    Design: Difficulty/cross_entity_state_dependency/an_interactives_shop_drawing_is_gated_by_the_prototype_status_of_a_third_entity
    """
    ctx = _commission_with_a_housing_material(api)
    station = get_success_data(api.get_interactive(ctx["interactive_id"], FABRICATION), 200)
    assert station["status"] == InteractiveStatus.SPECIFIED
    assert_index(station["durability_index_spec"], 70.60)
    assert station["durability_index_verified"] is None
    assert station["maintenance_tier"] == MaintenanceTier.MEDIUM

    refused = api.create_shop_drawing(_housing_sheet_payload(ctx, "SD-801"), FABRICATION)
    validate_error(refused, ERR_PROTOTYPE_NOT_APPROVED, 409)

    sheets, meta = validate_paginated(api.list_shop_drawings(FABRICATION))
    assert sheets == []
    assert meta["total_count"] == 0


def test_a_submitted_but_unruled_prototype_is_still_refused_the_sheet(api):
    """Bench figures on the record are not a ruling, so the sheet is refused again.

    "A `FabricationLead` submits a prototype from `SPECIFIED` or from `PROTOTYPE_REJECTED` — the rejected branch is the rework loop and may be walked any number of times — while the project is in `DESIGN_DEV` or `FABRICATION` and not frozen."
    "A named subject interactive must have got past its prototype: its status must be `PROTOTYPE_APPROVED`, `FABRICATED` or `COMMISSIONED`, and anything earlier answers `ERR_PROTOTYPE_NOT_APPROVED` (HTTP 409)."
    Design: Difficulty/cross_entity_state_dependency/an_interactives_shop_drawing_is_gated_by_the_prototype_status_of_a_third_entity
    """
    ctx = _commission_with_a_housing_material(api)
    submitted = validate_success(
        api.submit_prototype(
            ctx["interactive_id"],
            f.prototype_payload(measured_daily_uses=60, measured_mtbf_cycles=1500000),
            FABRICATION,
        ),
        200,
    )
    assert submitted["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert submitted["prototype_iteration"] == 1
    assert submitted["durability_index_verified"] is None
    assert submitted["maintenance_tier"] == MaintenanceTier.MEDIUM

    refused = api.create_shop_drawing(_housing_sheet_payload(ctx, "SD-802"), FABRICATION)
    validate_error(refused, ERR_PROTOTYPE_NOT_APPROVED, 409)


def test_the_bench_submitter_may_not_rule_on_their_own_prototype(api):
    """A project-manager header carrying the submitting user's id is refused.

    "Five pairings are enforced, each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): the caller deciding a shop drawing may not be the caller stored in that drawing's `submitted_by_user_id`; the caller ruling on a prototype may not be the caller stored in that interactive's `submitted_by_user_id`; the caller verifying or waiving a punch item may not be the caller stored in that item's `raised_by_user_id`; the caller deciding an install window may not be the caller stored in that window's `requested_by_user_id`; and the caller casting a panel vote may not be the caller stored in the package's `submitted_by_user_id`."
    Design: Difficulty/cross_entity_state_dependency/an_interactives_shop_drawing_is_gated_by_the_prototype_status_of_a_third_entity
    """
    ctx = _commission_with_a_housing_material(api)
    submitted = validate_success(
        api.submit_prototype(
            ctx["interactive_id"],
            f.prototype_payload(measured_daily_uses=60, measured_mtbf_cycles=1500000),
            FABRICATION,
        ),
        200,
    )

    refused = api.prototype_decision(
        ctx["interactive_id"],
        f.prototype_decision_payload(PrototypeDecision.APPROVE),
        headers_for(ROLE_PROJECT_MANAGER, USER_FABRICATION),
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    after = get_success_data(api.get_interactive(ctx["interactive_id"], FABRICATION), 200)
    assert after["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert after["durability_index_verified"] is None
    assert_unchanged(submitted, after, ["status", "version", "durability_index_verified"])


def test_the_prototype_approval_rewrites_the_verified_index_and_unlocks_the_sheet(api):
    """The ruling on the station is what lets the housing sheet be issued and priced.

    "The **verified** variant uses the bench-measured `measured_daily_uses` and `measured_mtbf_cycles` with a prototype credit of 8 points — the reward for having actually built and tested the thing — and writes `durability_index_verified`; because the credit can push a strong station past a perfect score, this variant is where the cap at 100.0 bites."
    "The `maintenance_tier` is then derived from `durability_index_verified` when that field is non-null and from `durability_index_spec` otherwise, with inclusive lower boundaries: at least 80 is `LOW`, at least 60 is `MEDIUM`, at least 40 is `HIGH`, and anything below 40 is `CRITICAL`."
    Design: Difficulty/cross_entity_state_dependency/an_interactives_shop_drawing_is_gated_by_the_prototype_status_of_a_third_entity
    """
    ctx = _commission_with_a_housing_material(api)
    validate_success(
        api.submit_prototype(
            ctx["interactive_id"],
            f.prototype_payload(measured_daily_uses=60, measured_mtbf_cycles=1500000),
            FABRICATION,
        ),
        200,
    )

    ruled = validate_success(
        api.prototype_decision(
            ctx["interactive_id"],
            f.prototype_decision_payload(PrototypeDecision.APPROVE),
            PM,
        ),
        200,
    )
    assert ruled["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert_index(ruled["durability_index_spec"], 70.60)
    assert_index(ruled["durability_index_verified"], 87.58)
    assert ruled["maintenance_tier"] == MaintenanceTier.LOW

    issued = validate_success(
        api.create_shop_drawing(_housing_sheet_payload(ctx, "SD-803"), FABRICATION), 201
    )
    assert issued["subject_interactive_id"] == ctx["interactive_id"]
    assert issued["estimate_labor_cents"] == 333500
    assert issued["estimate_material_cents"] == 285000
    assert issued["estimate_finishing_cents"] == 21375
    assert issued["estimate_total_cents"] == 639875
