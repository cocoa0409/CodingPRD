"""Edges of the gallery-calendar gates and of the ladder that guards a zone create.

Every test builds its own preconditions through the documented endpoints: the
harness restarts the server before each test, so each one opens on an empty
database with the logical clock at its documented default instant.
"""

from test_helpers import (
    CONSERVATOR,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_PROJECT_PHASE,
    ERR_INVALID_REQUEST,
    ERR_NOISE_LIMIT_EXCEEDED,
    ERR_NOTHING_TO_SETTLE,
    ERR_PROJECT_NOT_FOUND,
    ERR_ZONE_CLOSED_FOR_WORK,
    FABRICATION,
    LATE_CLOCK,
    NON_EXISTENT_UUID,
    OPERATIONS,
    PM,
    ComplexityTier,
    DrawingStatus,
    FinishGrade,
    MountStatus,
    OccupancyState,
    OddyResult,
    PackageStage,
    Phase,
    Posture,
    PrototypeDecision,
    UsedIn,
    WindowDecision,
    WindowStatus,
    WorkClass,
    assert_ledger,
    assert_money_identity,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)

#: The housing material every interactive sheet is drawn from. Its chamber
#: numbers sit inside every INTERACTIVE_HOUSING limit, so it clears outright.
HOUSING_MATERIAL = {
    "material_name": "Powder-coated aluminium housing",
    "used_in": UsedIn.INTERACTIVE_HOUSING,
    "oddy_test_result": OddyResult.PASS,
    "voc_mg_per_m2_day": 0.12,
    "formaldehyde_ppm": 0.02,
    "cure_days": 14,
}
#: The case lining every vitrine sheet is drawn from.
CASE_LINING_MATERIAL = {
    "material_name": "Buffered museum board",
    "used_in": UsedIn.CASE_INTERIOR,
    "oddy_test_result": OddyResult.PASS,
    "voc_mg_per_m2_day": 0.04,
    "formaldehyde_ppm": 0.015,
    "cure_days": 25,
}
#: Both galleries tolerate the same 85 dBA of work; they differ only in whether
#: the museum will let them be closed to visitors at all.
ZONE_CEILING_DBA = 85.0


def _fabrication_project_with_a_closeable_and_a_sealed_zone(api):
    """Walk a commission to FABRICATION carrying two comparable galleries.

    Both zones share a noise ceiling, a slot capacity and a settling buffer;
    Z-A permits closure to visitors and Z-B does not, which is the only
    difference the calendar rules can react to.
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    closeable = fixtures.create_zone(
        api,
        project_id,
        headers=OPERATIONS,
        zone_code="Z-A",
        visitor_route_order=1,
        max_noise_dba=ZONE_CEILING_DBA,
        case_slot_capacity=2,
        closure_allowed=True,
        dust_settling_buffer_minutes=120,
    )
    sealed = fixtures.create_zone(
        api,
        project_id,
        headers=OPERATIONS,
        zone_code="Z-B",
        visitor_route_order=2,
        max_noise_dba=ZONE_CEILING_DBA,
        case_slot_capacity=2,
        closure_allowed=False,
        dust_settling_buffer_minutes=120,
    )
    artifact = fixtures.create_artifact(api, project_id)
    case = fixtures.create_case(api, project_id, closeable["id"])
    fixtures.create_interactive(api, project_id)
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.advance(api, project_id, Phase.FABRICATION)
    return {
        "project_id": project_id,
        "closeable_zone_id": closeable["id"],
        "sealed_zone_id": sealed["id"],
        "artifact_id": artifact["id"],
        "case_id": case["id"],
    }


def _installation_project_with_a_closeable_and_a_sealed_zone(api):
    """Take the same two-gallery commission into INSTALLATION.

    The single case is loaded and approved and one sheet detailing it has been
    approved, which is what the step into installation demands.
    """
    ctx = _fabrication_project_with_a_closeable_and_a_sealed_zone(api)
    lining = fixtures.create_material(api, ctx["project_id"], **CASE_LINING_MATERIAL)
    fixtures.approve_material(api, lining["id"])
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])
    drawing = fixtures.create_drawing(
        api, ctx["project_id"], lining["id"], subject_case_id=ctx["case_id"]
    )
    fixtures.approve_drawing(api, drawing["id"], actual_shop_hours=10.0, actual_waste_factor=1.0)
    fixtures.advance(api, ctx["project_id"], Phase.INSTALLATION)
    return ctx


def _closeout_project_with_two_approved_sheets(api):
    """Walk one commission the whole way to CLOSEOUT with money committed.

    Two sheets are approved on the shop's real figures — one detailing the
    interactive station and one detailing the case — so the committed bucket is
    the exact sum of their two actual costs by the time the phase reaches
    closeout, and the station is commissioned so the closeout step is admitted.
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id, headers=OPERATIONS)
    artifact = fixtures.create_artifact(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])
    interactive = fixtures.create_interactive(api, project_id)
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.advance(api, project_id, Phase.FABRICATION)

    get_success_data(
        api.submit_prototype(interactive["id"], factories.prototype_payload(), FABRICATION),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive["id"],
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )

    housing = fixtures.create_material(api, project_id, **HOUSING_MATERIAL)
    fixtures.approve_material(api, housing["id"])
    lining = fixtures.create_material(api, project_id, **CASE_LINING_MATERIAL)
    fixtures.approve_material(api, lining["id"])
    fixtures.place_artifact(api, case["id"], artifact["id"])
    fixtures.approve_case(api, case["id"])

    station_sheet = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        drawing_number="SD-201",
        complexity_tier=ComplexityTier.CONSERVATION_GRADE,
        shop_hours=100.0,
        material_area_m2=60.0,
        finish_grade=FinishGrade.MILL,
        subject_interactive_id=interactive["id"],
    )
    fixtures.approve_drawing(
        api, station_sheet["id"], actual_shop_hours=100.0, actual_waste_factor=1.0
    )
    case_sheet = fixtures.create_drawing(
        api,
        project_id,
        lining["id"],
        drawing_number="SD-202",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
        subject_case_id=case["id"],
    )
    fixtures.approve_drawing(
        api, case_sheet["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )

    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_FABRICATED)
    get_success_data(api.mark_fabricated(interactive["id"], FABRICATION), 200)

    window = fixtures.create_window(
        api,
        project_id,
        zone["id"],
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    fixtures.decide_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.INSTALLATION)
    fixtures.set_clock(api, LATE_CLOCK)
    fixtures.start_window(api, window["id"])
    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_INSTALLED)
    fixtures.complete_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.COMMISSIONING)
    get_success_data(
        api.commission_interactive(interactive["id"], factories.commission_payload(), PM),
        200,
    )
    fixtures.advance(api, project_id, Phase.CLOSEOUT)
    return {
        "project_id": project_id,
        "station_sheet_id": station_sheet["id"],
        "case_sheet_id": case_sheet["id"],
    }


def test_the_noise_ceiling_is_not_consulted_when_the_gallery_is_closed(api):
    """95 dBA is fatal in an open gallery and legal in a closed one.

    The two requests name the same zone, the same work class and the same
    instants, so only the closure flag can explain the different rulings; the
    cancel in between is what frees the interval for the second request.

    "The request carries `project_id`, the `zone_id` of the gallery it occupies — which must belong to the same project, or the request answers `ERR_CROSS_PROJECT_REFERENCE` — a `work_class` of `QUIET`, `NOISY`, `DUST_GENERATING` or `CRANE_ACCESS`, the anticipated `noise_dba` between 0 and 130 inclusive, the nominal `starts_at` and `ends_at` instants, and an optional `requires_gallery_closure` flag that defaults to false."
    "The window is stored at status `REQUESTED` with `requested_by_user_id` from the caller and `denial_reason` null."
    "First noise: the window's `noise_dba` must be no greater than the zone's `max_noise_dba`, or the ruling answers `ERR_NOISE_LIMIT_EXCEEDED` (HTTP 422) — **unless** `requires_gallery_closure` is true, in which case the ceiling does not apply at all, because with the gallery closed there are no visitors to disturb."
    "A window may also be cancelled by `MuseumOperations` or the `FabricationLead` from `REQUESTED` or `APPROVED`, with an optional `denial_reason`; it becomes `CANCELLED` and stops occupying its zone."
    "The occupying set is every other window on the same zone — excluding the window being judged — whose status is `REQUESTED`, `APPROVED` or `IN_PROGRESS`; a `DENIED`, `COMPLETED` or `CANCELLED` window never occupies its zone, so cancelling one immediately frees the slot for a rival that was blocked a moment earlier."
    "Three flags are optional: `is_public_operating`, true by default, records whether the zone stays open to visitors during the install period; `closure_allowed`, false by default, records whether the museum will permit closing the zone to visitors for work at all; and `dust_settling_buffer_minutes`, 120 by default and constrained to between 0 and 480 inclusive, is the zone's own minimum settling period after dust-generating work."
    Design: Corner/validations/the_same_noise_figure_passes_or_fails_depending_only_on_the_closure_flag
    """
    ctx = _fabrication_project_with_a_closeable_and_a_sealed_zone(api)
    loud_work = dict(
        work_class=WorkClass.NOISY,
        noise_dba=95.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
    )

    open_gallery = fixtures.create_window(
        api, ctx["project_id"], ctx["closeable_zone_id"], **loud_work
    )
    assert open_gallery["status"] == WindowStatus.REQUESTED
    assert open_gallery["requires_gallery_closure"] is False
    assert open_gallery["denial_reason"] is None

    over_ceiling = api.window_decision(
        open_gallery["id"],
        factories.window_decision_payload(WindowDecision.APPROVE),
        OPERATIONS,
    )
    validate_error(over_ceiling, ERR_NOISE_LIMIT_EXCEEDED)

    released = fixtures.cancel_window(api, open_gallery["id"])
    assert released["status"] == WindowStatus.CANCELLED

    closed_gallery = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["closeable_zone_id"],
        requires_gallery_closure=True,
        **loud_work
    )
    assert closed_gallery["requires_gallery_closure"] is True

    ruled = fixtures.decide_window(api, closed_gallery["id"])
    assert ruled["status"] == WindowStatus.APPROVED
    assert ruled["noise_dba"] == 95.0


def test_a_gallery_that_may_not_close_refuses_the_window_that_demands_closure(api):
    """Setting the flag is not free: the zone must permit closure at all.

    Both requests sit far below the same noise ceiling, and the only difference
    is the closure demand; their buffered intervals are 45 minutes apart at the
    nearest edge, so no calendar conflict can be confused with the refusal.

    "Second occupancy: the zone's `occupancy_state` must not be `CLOSED`, and if the window asks for a closure the zone's `closure_allowed` must be true, or the ruling answers `ERR_ZONE_CLOSED_FOR_WORK` (HTTP 422) — a zone on a required circulation route can never be closed no matter who asks."
    "The `pre_access_buffer_minutes` — the time the crew needs to protect objects and lay down floor covering before the nominal start — is 0 for `QUIET`, 15 for `NOISY`, 30 for `DUST_GENERATING` and 45 for `CRANE_ACCESS`."
    "The `settling_buffer_minutes` — the time airborne dust and noise need to clear before visitors return — is 0 for `QUIET`, 30 for `NOISY`, 120 for `DUST_GENERATING` and 60 for `CRANE_ACCESS`, except that for `DUST_GENERATING` work the buffer is the **larger** of that 120-minute floor and the zone's own `dust_settling_buffer_minutes`, so a zone with a slow air exchange lengthens the window it hosts."
    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."
    "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."
    Design: Corner/validations/the_same_noise_figure_passes_or_fails_depending_only_on_the_closure_flag
    """
    ctx = _fabrication_project_with_a_closeable_and_a_sealed_zone(api)

    demands_closure = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["sealed_zone_id"],
        work_class=WorkClass.NOISY,
        noise_dba=50.0,
        starts_at="2026-09-11T08:00:00Z",
        ends_at="2026-09-11T10:00:00Z",
        requires_gallery_closure=True,
    )
    assert demands_closure["pre_access_buffer_minutes"] == 15
    assert demands_closure["settling_buffer_minutes"] == 30
    assert demands_closure["effective_start_at"].startswith("2026-09-11T07:45:00")
    assert demands_closure["effective_end_at"].startswith("2026-09-11T10:30:00")

    refused = api.window_decision(
        demands_closure["id"],
        factories.window_decision_payload(WindowDecision.APPROVE),
        OPERATIONS,
    )
    validate_error(refused, ERR_ZONE_CLOSED_FOR_WORK)

    keeps_gallery_open = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["sealed_zone_id"],
        work_class=WorkClass.NOISY,
        noise_dba=50.0,
        starts_at="2026-09-11T11:00:00Z",
        ends_at="2026-09-11T12:00:00Z",
    )
    assert keeps_gallery_open["effective_start_at"].startswith("2026-09-11T10:45:00")
    assert keeps_gallery_open["effective_end_at"].startswith("2026-09-11T12:30:00")

    ruled = fixtures.decide_window(api, keeps_gallery_open["id"])
    assert ruled["status"] == WindowStatus.APPROVED


def test_approving_a_closure_window_leaves_the_gallery_open_until_work_starts(api):
    """Occupancy moves when the crew starts, not when the ruling is made.

    "A new zone starts with `reserved_case_slots` at 0 and `available_case_slots` equal to its capacity, so the slot identity of §2.7 holds from creation, and with `occupancy_state` at `OPERATING`."
    "Requesting a window does not change the zone's `occupancy_state` — the gallery stays open until work actually starts — but a merely `REQUESTED` window already occupies the zone for conflict purposes, so the first request in a slot blocks the second even before anyone approves it."
    "`MuseumOperations` starts an `APPROVED` window, which requires the project to be in `INSTALLATION` and requires the logical clock to have reached or passed the window's `starts_at` — starting early answers `ERR_INVALID_WINDOW_STATE`."
    "The window becomes `IN_PROGRESS` and the zone's `occupancy_state` changes: to `CLOSED` when `requires_gallery_closure` is true, and to `PARTIAL_CLOSURE` otherwise."
    Design: Corner/validations/the_zone_availability_gate_reads_the_current_occupancy_not_the_requested_interval
    """
    ctx = _installation_project_with_a_closeable_and_a_sealed_zone(api)

    window = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["closeable_zone_id"],
        work_class=WorkClass.QUIET,
        noise_dba=40.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
        requires_gallery_closure=True,
    )
    ruled = fixtures.decide_window(api, window["id"])
    assert ruled["status"] == WindowStatus.APPROVED

    still_open = get_success_data(
        api.get_gallery_zone(ctx["closeable_zone_id"], OPERATIONS), 200
    )
    assert still_open["occupancy_state"] == OccupancyState.OPERATING

    fixtures.set_clock(api, "2026-09-10T08:00:00Z")
    started = fixtures.start_window(api, window["id"])
    assert started["status"] == WindowStatus.IN_PROGRESS

    now_closed = get_success_data(
        api.get_gallery_zone(ctx["closeable_zone_id"], OPERATIONS), 200
    )
    assert now_closed["occupancy_state"] == OccupancyState.CLOSED


def test_a_closed_gallery_refuses_a_window_two_days_later_while_its_neighbour_is_approved(api):
    """The availability gate reads the zone now, not the interval requested.

    The second window asks for a slot two days after the in-progress one ends,
    so no interval arithmetic can object to it, and the identical request on the
    neighbouring gallery is approved in the same breath.

    "Second occupancy: the zone's `occupancy_state` must not be `CLOSED`, and if the window asks for a closure the zone's `closure_allowed` must be true, or the ruling answers `ERR_ZONE_CLOSED_FOR_WORK` (HTTP 422) — a zone on a required circulation route can never be closed no matter who asks."
    "The window becomes `IN_PROGRESS` and the zone's `occupancy_state` changes: to `CLOSED` when `requires_gallery_closure` is true, and to `PARTIAL_CLOSURE` otherwise."
    "Requesting a window does not change the zone's `occupancy_state` — the gallery stays open until work actually starts — but a merely `REQUESTED` window already occupies the zone for conflict purposes, so the first request in a slot blocks the second even before anyone approves it."
    "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."
    Design: Corner/validations/the_zone_availability_gate_reads_the_current_occupancy_not_the_requested_interval
    """
    ctx = _installation_project_with_a_closeable_and_a_sealed_zone(api)
    later_work = dict(
        work_class=WorkClass.QUIET,
        noise_dba=40.0,
        starts_at="2026-09-12T08:00:00Z",
        ends_at="2026-09-12T10:00:00Z",
    )

    closure = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["closeable_zone_id"],
        work_class=WorkClass.QUIET,
        noise_dba=40.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
        requires_gallery_closure=True,
    )
    fixtures.decide_window(api, closure["id"])
    fixtures.set_clock(api, "2026-09-10T08:00:00Z")
    fixtures.start_window(api, closure["id"])

    on_the_closed_zone = fixtures.create_window(
        api, ctx["project_id"], ctx["closeable_zone_id"], **later_work
    )
    refused = api.window_decision(
        on_the_closed_zone["id"],
        factories.window_decision_payload(WindowDecision.APPROVE),
        OPERATIONS,
    )
    validate_error(refused, ERR_ZONE_CLOSED_FOR_WORK)

    on_the_neighbour = fixtures.create_window(
        api, ctx["project_id"], ctx["sealed_zone_id"], **later_work
    )
    ruled = fixtures.decide_window(api, on_the_neighbour["id"])
    assert ruled["status"] == WindowStatus.APPROVED

    neighbour = get_success_data(
        api.get_gallery_zone(ctx["sealed_zone_id"], OPERATIONS), 200
    )
    assert neighbour["occupancy_state"] == OccupancyState.OPERATING


def test_voiding_every_approved_sheet_returns_the_committed_money_to_the_cent(api):
    """Two voids reverse two commitments exactly, emptying the committed bucket.

    The commission sits in closeout with 4,837,500 cents committed against its
    two approved sheets — 4,700,000 for the station housing and 137,500 for the
    case lining — and voiding both hands the whole contract value back.

    "`uncommitted_cents` is always the contract value less the sum of the other four buckets, and the five together always add up to `contract_value_cents` exactly."
    "With them the cost model runs again as the **shop-drawing actual**: the hours are the supplied `actual_shop_hours`, the labour multiplier is exactly 1.00 because the schematic contingency is *dropped* rather than re-based, and the waste factor is the supplied `actual_waste_factor`."
    "Labour is the hours multiplied by the shop rate for the sheet's complexity tier multiplied by a labour multiplier: the shop charges 95 dollars per hour at `STANDARD`, 145 dollars per hour at `PRECISION` and 185 dollars per hour at `CONSERVATION_GRADE`, recorded as 9,500, 14,500 and 18,500 cents per hour respectively."
    "Material is the `material_area_m2` multiplied by the rate for the **material's** `used_in` assembly multiplied by a waste factor, where the rates per square metre are 42,500 cents for `CASE_INTERIOR`, 31,000 for `CASE_EXTERIOR`, 58,000 for `MOUNT`, 12,500 for `GRAPHIC` and 47,500 for `INTERACTIVE_HOUSING`."
    "The three results land in `actual_labor_cents`, `actual_material_cents` and `actual_finishing_cents`, and their sum in `actual_cost_cents`."
    "On success the amount moves out of `uncommitted_cents` and into `committed_fabrication_cents`, the project's `updated_at` and `version` advance, and the sheet's `version` advances."
    "A sheet in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED` or `APPROVED_AS_NOTED` becomes `VOID`; a sheet that is already `VOID` cannot be voided again and answers `ERR_INVALID_DRAWING_STATE`, and neither can a `REJECTED` one."
    "Each voided sheet that had actually committed money — one that stood at `APPROVED` or `APPROVED_AS_NOTED` and therefore carries a non-null `actual_cost_cents` — releases exactly that amount from the project's `committed_fabrication_cents` back into `uncommitted_cents`."
    "The five-bucket identity of §2.7 is preserved exactly; nothing is recomputed, the original commitment is simply reversed."
    "Otherwise posture is `OPEN`."
    Design: Corner/validations/closeout_refuses_to_settle_an_empty_committed_bucket_after_every_sheet_is_voided
    """
    ctx = _closeout_project_with_two_approved_sheets(api)

    before = fixtures.read_project(api, ctx["project_id"])
    assert before["phase"] == Phase.CLOSEOUT
    assert_ledger(before, committed=4837500, uncommitted=4162500)
    assert_money_identity(before)

    station_sheet = get_success_data(
        api.void_drawing(
            ctx["station_sheet_id"],
            factories.void_payload(
                void_reason="Interactive housing re-detailed after the commissioning review; sheet retired."
            ),
            PM,
        ),
        200,
    )
    assert station_sheet["status"] == DrawingStatus.VOID
    assert station_sheet["actual_cost_cents"] == 4700000

    case_sheet = get_success_data(
        api.void_drawing(
            ctx["case_sheet_id"],
            factories.void_payload(
                void_reason="Case C-01 vitrine sheet retired; the as-built record supersedes it."
            ),
            PM,
        ),
        200,
    )
    assert case_sheet["status"] == DrawingStatus.VOID
    assert case_sheet["actual_cost_cents"] == 137500

    after = fixtures.read_project(api, ctx["project_id"])
    assert_ledger(after, committed=0, uncommitted=9000000)
    assert_money_identity(after)
    assert after["posture"] == Posture.OPEN
    assert after["phase"] == Phase.CLOSEOUT


def test_closeout_refuses_to_settle_a_commission_with_nothing_committed(api):
    """An empty committed bucket is refused rather than settled over zeros.

    The refusal writes nothing at all: the handover fields stay unset, the three
    settlement figures stay zero and the commission stays in closeout.

    "The project must be in `CLOSEOUT`; its `posture` must be exactly `OPEN`, so a `RESTRICTED` or `FROZEN_CONSERVATION` commission cannot be settled and answers `ERR_PROJECT_POSTURE_RESTRICTED`; and `committed_fabrication_cents` must be greater than zero, or there is nothing to settle and the request answers `ERR_NOTHING_TO_SETTLE` (HTTP 409)."
    "Each voided sheet that had actually committed money — one that stood at `APPROVED` or `APPROVED_AS_NOTED` and therefore carries a non-null `actual_cost_cents` — releases exactly that amount from the project's `committed_fabrication_cents` back into `uncommitted_cents`."
    "The results are written to `retainage_held_cents`, `warranty_reserve_cents` and `released_cents`."
    "Finally the phase advances from `CLOSEOUT` to `WARRANTY_CLOSED` and the project's `version` is incremented by one."
    "The closeout-only fields are empty until closeout writes them: `parts_commitment_years` is 0, and `docent_kit_url`, `maintenance_manual_url` and `warranty_registered_at` are all null."
    Design: Corner/validations/closeout_refuses_to_settle_an_empty_committed_bucket_after_every_sheet_is_voided
    """
    ctx = _closeout_project_with_two_approved_sheets(api)
    for drawing_id in (ctx["station_sheet_id"], ctx["case_sheet_id"]):
        get_success_data(
            api.void_drawing(
                drawing_id,
                factories.void_payload(void_reason="Sheet retired at closeout by the project manager."),
                PM,
            ),
            200,
        )

    refused = api.closeout(
        ctx["project_id"],
        factories.closeout_payload(
            docent_kit_url="https://docs.example.org/deep-time/docent-kit.pdf",
            maintenance_manual_url="https://docs.example.org/deep-time/maintenance.pdf",
            parts_commitment_years=10,
        ),
        PM,
    )
    validate_error(refused, ERR_NOTHING_TO_SETTLE)

    unsettled = fixtures.read_project(api, ctx["project_id"])
    assert unsettled["phase"] == Phase.CLOSEOUT
    assert unsettled["retainage_held_cents"] == 0
    assert unsettled["warranty_reserve_cents"] == 0
    assert unsettled["released_cents"] == 0
    assert unsettled["uncommitted_cents"] == 9000000
    assert unsettled["docent_kit_url"] is None
    assert unsettled["maintenance_manual_url"] is None
    assert unsettled["warranty_registered_at"] is None
    assert unsettled["parts_commitment_years"] == 0
    assert_money_identity(unsettled)


def test_a_malformed_zone_body_outranks_the_unknown_commission_it_is_sent_to(api):
    """Body shape is judged before any identifier is resolved.

    The first request breaks the declared slot range while also repeating an
    existing code in a phase that forbids the create at all, and still reports
    the malformed body; the second is well formed and names nothing, so the
    404 speaks before uniqueness or phase.

    "Request-body shape: parseable JSON object, every required field present and non-null, every enum-typed field carrying a declared value, every number within its declared domain, every datetime a valid ISO 8601 UTC instant (`ERR_INVALID_REQUEST`)."
    "Existence of every referenced row, path-supplied and body-supplied alike, in the order the eleven 404s are listed in §2.5."
    "`case_slot_capacity` declares how many artifact cases the floor plan can carry and must be between 1 and 20 inclusive; it is the conserved slot pool."
    "An unknown project identifier yields `ERR_PROJECT_NOT_FOUND`; an unknown design package yields `ERR_PACKAGE_NOT_FOUND`; an unknown review round yields `ERR_ROUND_NOT_FOUND`; an unknown gallery zone yields `ERR_ZONE_NOT_FOUND`; an unknown artifact case yields `ERR_CASE_NOT_FOUND`; an unknown collection object yields `ERR_ARTIFACT_NOT_FOUND`; an unknown interactive yields `ERR_INTERACTIVE_NOT_FOUND`; an unknown material specification yields `ERR_MATERIAL_NOT_FOUND`; an unknown shop drawing yields `ERR_DRAWING_NOT_FOUND`; an unknown install window yields `ERR_WINDOW_NOT_FOUND`; and an unknown punch item yields `ERR_PUNCH_ITEM_NOT_FOUND`."
    Design: Corner/validations/the_zone_create_ladder_reports_invalid_request_then_not_found_then_duplicate_then_phase
    """
    ctx = _fabrication_project_with_a_closeable_and_a_sealed_zone(api)

    over_capacity = api.create_gallery_zone(
        ctx["project_id"],
        factories.gallery_zone_payload(
            zone_code="Z-A",
            visitor_route_order=1,
            max_noise_dba=ZONE_CEILING_DBA,
            case_slot_capacity=25,
        ),
        OPERATIONS,
    )
    validate_error(over_capacity, ERR_INVALID_REQUEST)

    unknown_commission = api.create_gallery_zone(
        NON_EXISTENT_UUID,
        factories.gallery_zone_payload(
            zone_code="Z-A",
            visitor_route_order=1,
            max_noise_dba=ZONE_CEILING_DBA,
            case_slot_capacity=3,
        ),
        OPERATIONS,
    )
    validate_error(unknown_commission, ERR_PROJECT_NOT_FOUND)


def test_a_duplicate_zone_code_outranks_the_phase_that_forbids_the_create(api):
    """Scoped uniqueness speaks before the phase gate, then the phase gate speaks.

    Both requests are refused for creating a gallery during fabrication, yet the
    one that also repeats an existing code reports the duplicate instead, and
    neither request adds a gallery to the walk.

    "Scoped uniqueness of human-authored codes (`ERR_DUPLICATE_CODE`), then single-instance constraints on votes and open rounds (`ERR_DUPLICATE_VOTE`, `ERR_ROUND_ALREADY_OPEN`), then panel seating (`ERR_VOTER_NOT_ON_PANEL`)."
    "Project phase (`ERR_INVALID_PROJECT_PHASE`)."
    "Each zone carries a `zone_code` of 1 to 40 characters that must be unique among the project's zones, and a `visitor_route_order` of at least 1 that places it on the interpretive walk and must likewise be unique among the project's zones — a collision on either is reported as `ERR_DUPLICATE_CODE` (HTTP 409), with codes compared case-sensitively and exactly."
    "Phase also decides which children may be created at all, and a mismatch is `ERR_INVALID_PROJECT_PHASE`."
    "Gallery zones, collection objects and interactives may be registered only while the phase is `INTERPRETIVE`, `SCHEMATIC` or `DESIGN_DEV`."
    "Four collections deviate, and the deviation is part of the contract: the top-level project list is ordered by `created_at` descending, newest commission first; a project's gallery zones are ordered by `visitor_route_order` ascending, which is the order a visitor walks them; a package's review rounds are ordered by `round_number` ascending; and install windows, whether listed for a project or for a single zone, are ordered by `starts_at` ascending with `created_at` ascending as the tie-break."
    Design: Corner/validations/the_zone_create_ladder_reports_invalid_request_then_not_found_then_duplicate_then_phase
    """
    ctx = _fabrication_project_with_a_closeable_and_a_sealed_zone(api)

    repeated_code = api.create_gallery_zone(
        ctx["project_id"],
        factories.gallery_zone_payload(
            zone_code="Z-A",
            visitor_route_order=4,
            max_noise_dba=ZONE_CEILING_DBA,
            case_slot_capacity=3,
        ),
        OPERATIONS,
    )
    validate_error(repeated_code, ERR_DUPLICATE_CODE)

    fresh_code = api.create_gallery_zone(
        ctx["project_id"],
        factories.gallery_zone_payload(
            zone_code="Z-C",
            visitor_route_order=4,
            max_noise_dba=ZONE_CEILING_DBA,
            case_slot_capacity=3,
        ),
        OPERATIONS,
    )
    validate_error(fresh_code, ERR_INVALID_PROJECT_PHASE)

    rows, meta = validate_paginated(api.list_gallery_zones(ctx["project_id"], OPERATIONS))
    assert meta["total_count"] == 2
    assert [row["zone_code"] for row in rows] == ["Z-A", "Z-B"]
    assert [row["id"] for row in rows] == [ctx["closeable_zone_id"], ctx["sealed_zone_id"]]
