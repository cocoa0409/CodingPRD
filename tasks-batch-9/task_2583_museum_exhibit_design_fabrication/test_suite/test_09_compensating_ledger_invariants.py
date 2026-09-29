"""Compensating actions and the identities they must not disturb.

Voiding a sheet is the compensating half of approving it, withdrawing an object is
the compensating half of reserving it, and both are exercised here in cycles: the
five-bucket ledger identity, the zone slot identity and the strictest-wins case
envelope must each come back to exactly the figures they carried before, never to
an approximation of them. Every test builds its own commission and asserts the
pinned cents, slot counts and derived bounds of PRD sections 2.7, 3.4, 3.5 and 3.7.
"""

from test_helpers import (
    CONSERVATOR,
    CURATOR,
    ERR_CASE_HAS_NO_ARTIFACTS,
    ERR_ENV_ENVELOPE_INFEASIBLE,
    ERR_INVALID_DRAWING_STATE,
    ERR_SECURITY_TIER_INSUFFICIENT,
    ERR_ZONE_CASE_SLOTS_EXHAUSTED,
    FABRICATION,
    OBJECTIVE_PRIMARY,
    PM,
    CaseDecision,
    CaseStatus,
    ComplexityTier,
    DrawingStatus,
    FinishGrade,
    MaterialClass,
    MountStatus,
    PackageStage,
    Phase,
    PlacementStatus,
    PrototypeDecision,
    SecurityTier,
    UsedIn,
    assert_empty_envelope,
    assert_envelope,
    assert_geometry,
    assert_ledger,
    assert_money_identity,
    assert_unchanged,
    assert_zone_slots,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONTRACT_CENTS = 9000000
#: The precision housing sheet's actual cost: 290,000 + 237,500 + 17,813 cents.
PRECISION_ACTUAL_CENTS = 545313
#: The standard housing sheet's actual cost: 76,000 + 95,000 + 12,825 cents.
STANDARD_ACTUAL_CENTS = 183825


def _schematic_commission(api, zone_overrides=None, project_overrides=None):
    """Open a commission, advance it to SCHEMATIC and register one gallery zone.

    Two interactives carry the project's two learning objectives between them so
    that the objective-coverage gate on the advance into FABRICATION is satisfied
    however many artifact cases the test chooses to design.
    """
    fx.set_clock(api)
    project = fx.create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone = fx.create_zone(api, project_id, **(zone_overrides or {}))
    fx.create_interactive(
        api, project_id, code="INT-RIVER", objective_code=OBJECTIVE_PRIMARY
    )
    interactive = fx.create_interactive(api, project_id)
    return {
        "project_id": project_id,
        "zone": zone,
        "zone_id": zone["id"],
        "interactive_id": interactive["id"],
    }


def _advance_to_design_dev(api, project_id):
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    return fx.advance(api, project_id, Phase.DESIGN_DEV)


def _advance_to_fabrication(api, project_id):
    _advance_to_design_dev(api, project_id)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    return fx.advance(api, project_id, Phase.FABRICATION)


def _approved_housing_material(api, project_id):
    """Screen and clear a powder-coated aluminium housing for interactive use."""
    material = fx.create_material(
        api,
        project_id,
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    fx.approve_material(api, material["id"])
    return material["id"]


def _approve_prototype(api, interactive_id):
    """Bench-test the station and have the project manager rule on the prototype."""
    get_success_data(
        api.submit_prototype(interactive_id, f.prototype_payload(), FABRICATION), 200
    )
    return get_success_data(
        api.prototype_decision(
            interactive_id,
            f.prototype_decision_payload(PrototypeDecision.APPROVE),
            PM,
        ),
        200,
    )


def _issue_precision_sheet(api, ctx, drawing_number):
    """A precision housing sheet: 20 shop hours over 5 square metres, satin finished."""
    return fx.create_drawing(
        api,
        ctx["project_id"],
        ctx["material_id"],
        drawing_number=drawing_number,
        subject_interactive_id=ctx["interactive_id"],
        complexity_tier=ComplexityTier.PRECISION,
        shop_hours=20.0,
        material_area_m2=5.0,
        finish_grade=FinishGrade.SATIN,
    )


def _issue_standard_sheet(api, ctx, drawing_number):
    """A standard housing sheet: 8 shop hours over 2 square metres, museum gloss."""
    return fx.create_drawing(
        api,
        ctx["project_id"],
        ctx["material_id"],
        drawing_number=drawing_number,
        subject_interactive_id=ctx["interactive_id"],
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=8.0,
        material_area_m2=2.0,
        finish_grade=FinishGrade.MUSEUM_GLOSS,
    )


def _approve_sheet(api, drawing_id, actual_shop_hours):
    """Rule APPROVE on a sheet with the shop's real hours and no waste allowance."""
    return fx.approve_drawing(
        api,
        drawing_id,
        actual_shop_hours=actual_shop_hours,
        actual_waste_factor=1.0,
    )


def _commission_with_two_approved_sheets(api):
    """A commission in FABRICATION carrying both housing sheets, each approved."""
    ctx = _schematic_commission(api)
    _advance_to_fabrication(api, ctx["project_id"])
    ctx["material_id"] = _approved_housing_material(api, ctx["project_id"])
    _approve_prototype(api, ctx["interactive_id"])
    precision = _issue_precision_sheet(api, ctx, "SD-901")
    _approve_sheet(api, precision["id"], 20.0)
    standard = _issue_standard_sheet(api, ctx, "SD-902")
    _approve_sheet(api, standard["id"], 8.0)
    ctx["precision_id"] = precision["id"]
    ctx["standard_id"] = standard["id"]
    return ctx


# ---------------------------------------------------------------------------
# voiding an approved sheet returns every cent
# ---------------------------------------------------------------------------
def test_two_approved_sheets_commit_each_already_rounded_line_item(api):
    """Both sheets price three separately rounded lines and commit their sum.

    "The cost model has three line items, and **each is rounded to whole cents before the three are summed**."
    "Finishing is a percentage of the **already-rounded** material line item — 0 percent for `MILL`, 7.5 percent for `SATIN` and 13.5 percent for `MUSEUM_GLOSS` — and it too is rounded to whole cents."
    Design: Difficulty/compensating_invariant/voiding_an_approved_drawing_returns_every_cent_and_the_five_bucket_identity_never_drifts
    """
    ctx = _schematic_commission(api)
    project_id = ctx["project_id"]
    _advance_to_fabrication(api, project_id)
    ctx["material_id"] = _approved_housing_material(api, project_id)
    _approve_prototype(api, ctx["interactive_id"])
    assert_ledger(fx.read_project(api, project_id), 0, CONTRACT_CENTS)

    precision = _issue_precision_sheet(api, ctx, "SD-901")
    assert precision["estimate_labor_cents"] == 333500
    assert precision["estimate_material_cents"] == 285000
    assert precision["estimate_finishing_cents"] == 21375
    assert precision["estimate_total_cents"] == 639875

    priced = _approve_sheet(api, precision["id"], 20.0)
    assert priced["status"] == DrawingStatus.APPROVED
    assert priced["actual_labor_cents"] == 290000
    assert priced["actual_material_cents"] == 237500
    assert priced["actual_finishing_cents"] == 17813
    assert priced["actual_cost_cents"] == PRECISION_ACTUAL_CENTS
    assert_ledger(fx.read_project(api, project_id), 545313, 8454687)

    standard = _issue_standard_sheet(api, ctx, "SD-902")
    assert standard["estimate_labor_cents"] == 87400
    assert standard["estimate_material_cents"] == 114000
    assert standard["estimate_finishing_cents"] == 15390
    assert standard["estimate_total_cents"] == 216790

    second = _approve_sheet(api, standard["id"], 8.0)
    assert second["actual_labor_cents"] == 76000
    assert second["actual_material_cents"] == 95000
    assert second["actual_finishing_cents"] == 12825
    assert second["actual_cost_cents"] == STANDARD_ACTUAL_CENTS
    assert_ledger(fx.read_project(api, project_id), 729138, 8270862)


def test_voiding_an_approved_sheet_releases_exactly_the_cents_it_committed(api):
    """The void hands back 545,313 cents and leaves the other sheet's money alone.

    "When the sheet's `actual_cost_cents` is non-null, exactly that amount is released from `committed_fabrication_cents` back into `uncommitted_cents` — a reversal, not a recomputation, so no cent drifts."
    Design: Difficulty/compensating_invariant/voiding_an_approved_drawing_returns_every_cent_and_the_five_bucket_identity_never_drifts
    """
    ctx = _commission_with_two_approved_sheets(api)
    project_id = ctx["project_id"]
    assert_ledger(fx.read_project(api, project_id), 729138, 8270862)

    voided = validate_success(
        api.void_drawing(
            ctx["precision_id"],
            f.void_payload(void_reason="Housing redesigned after the mock-up review"),
            PM,
        ),
        200,
    )
    assert voided["status"] == DrawingStatus.VOID
    assert voided["void_reason"] == "Housing redesigned after the mock-up review"

    project = fx.read_project(api, project_id)
    assert_ledger(project, 183825, 8816175)
    assert project["retainage_held_cents"] == 0
    assert project["warranty_reserve_cents"] == 0
    assert project["released_cents"] == 0

    survivor = get_success_data(api.get_shop_drawing(ctx["standard_id"], FABRICATION), 200)
    assert survivor["status"] == DrawingStatus.APPROVED
    assert survivor["actual_cost_cents"] == STANDARD_ACTUAL_CENTS


def test_a_sheet_already_void_cannot_be_credited_a_second_time(api):
    """The second void is refused and the ledger stands exactly where the first left it.

    "A sheet in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED` or `APPROVED_AS_NOTED` becomes `VOID`; a sheet that is already `VOID` cannot be voided again and answers `ERR_INVALID_DRAWING_STATE`, and neither can a `REJECTED` one."
    Design: Difficulty/compensating_invariant/voiding_an_approved_drawing_returns_every_cent_and_the_five_bucket_identity_never_drifts
    """
    ctx = _commission_with_two_approved_sheets(api)
    project_id = ctx["project_id"]
    validate_success(
        api.void_drawing(ctx["precision_id"], f.void_payload(), PM), 200
    )
    after_first_void = fx.read_project(api, project_id)
    assert_ledger(after_first_void, 183825, 8816175)
    voided_sheet = get_success_data(
        api.get_shop_drawing(ctx["precision_id"], FABRICATION), 200
    )

    refused = api.void_drawing(ctx["precision_id"], f.void_payload(), PM)
    validate_error(refused, ERR_INVALID_DRAWING_STATE, 409)

    unchanged_sheet = get_success_data(
        api.get_shop_drawing(ctx["precision_id"], FABRICATION), 200
    )
    assert_unchanged(voided_sheet, unchanged_sheet, ["status", "version", "void_reason"])
    after_refusal = fx.read_project(api, project_id)
    assert_ledger(after_refusal, 183825, 8816175)
    assert_unchanged(
        after_first_void,
        after_refusal,
        ["committed_fabrication_cents", "uncommitted_cents", "version"],
    )


def test_an_identical_replacement_sheet_restores_the_pre_void_ledger_exactly(api):
    """Re-issuing and re-approving the same specification lands the same cents again.

    "The three results land in `actual_labor_cents`, `actual_material_cents` and `actual_finishing_cents`, and their sum in `actual_cost_cents`."
    "When the sheet's `actual_cost_cents` is non-null, exactly that amount is released from `committed_fabrication_cents` back into `uncommitted_cents` — a reversal, not a recomputation, so no cent drifts."
    Design: Difficulty/compensating_invariant/voiding_an_approved_drawing_returns_every_cent_and_the_five_bucket_identity_never_drifts
    """
    ctx = _commission_with_two_approved_sheets(api)
    project_id = ctx["project_id"]
    validate_success(api.void_drawing(ctx["precision_id"], f.void_payload(), PM), 200)
    assert_ledger(fx.read_project(api, project_id), 183825, 8816175)

    replacement = _issue_precision_sheet(api, ctx, "SD-903")
    assert replacement["estimate_total_cents"] == 639875
    repriced = _approve_sheet(api, replacement["id"], 20.0)
    assert repriced["actual_cost_cents"] == PRECISION_ACTUAL_CENTS

    project = fx.read_project(api, project_id)
    assert_ledger(project, 729138, 8270862)


def test_voiding_every_sheet_returns_the_whole_contract_value_to_uncommitted(api):
    """With no sheet left committing money the pool is settled again to the cent.

    "`uncommitted_cents` is always the contract value less the sum of the other four buckets, and the five together always add up to `contract_value_cents` exactly."
    Design: Difficulty/compensating_invariant/voiding_an_approved_drawing_returns_every_cent_and_the_five_bucket_identity_never_drifts
    """
    ctx = _commission_with_two_approved_sheets(api)
    project_id = ctx["project_id"]
    validate_success(api.void_drawing(ctx["precision_id"], f.void_payload(), PM), 200)
    replacement = _issue_precision_sheet(api, ctx, "SD-903")
    _approve_sheet(api, replacement["id"], 20.0)
    assert_ledger(fx.read_project(api, project_id), 729138, 8270862)

    validate_success(api.void_drawing(ctx["standard_id"], f.void_payload(), PM), 200)
    assert_ledger(fx.read_project(api, project_id), 545313, 8454687)

    validate_success(api.void_drawing(replacement["id"], f.void_payload(), PM), 200)
    settled = fx.read_project(api, project_id)
    assert_ledger(settled, 0, CONTRACT_CENTS)
    assert settled["retainage_held_cents"] == 0
    assert settled["warranty_reserve_cents"] == 0
    assert settled["released_cents"] == 0
    assert_money_identity(settled)


# ---------------------------------------------------------------------------
# the zone slot identity survives approve, void and re-approve
# ---------------------------------------------------------------------------
def _read_case(api, case_id):
    return get_success_data(api.get_artifact_case(case_id, CONSERVATOR), 200)


def _read_zone(api, zone_id):
    return get_success_data(api.get_gallery_zone(zone_id, PM), 200)


def _read_artifact(api, artifact_id):
    return get_success_data(api.get_artifact(artifact_id, CURATOR), 200)


def _zone_filled_with_a_third_case_queued(api):
    """A two-slot zone with both slots reserved and a third case still under review.

    The first case is also the subject of an approved shop drawing worth 137,500
    cents, so voiding that sheet is what will hand its slot back.
    """
    ctx = _schematic_commission(api)
    project_id = ctx["project_id"]
    cases = []
    artifacts = []
    for case_code, accession in (
        ("C-01", "2019.14.3"),
        ("C-02", "2019.14.4"),
        ("C-03", "2019.14.5"),
    ):
        artifact = fx.create_artifact(api, project_id, accession_number=accession)
        case = fx.create_case(api, project_id, ctx["zone_id"], case_code=case_code)
        fx.place_artifact(api, case["id"], artifact["id"])
        artifacts.append(artifact)
        cases.append(case)
    fx.approve_case(api, cases[0]["id"])
    fx.approve_case(api, cases[1]["id"])
    queued = fx.submit_case(api, cases[2]["id"])
    assert queued["status"] == CaseStatus.CONSERVATOR_REVIEW

    _advance_to_fabrication(api, project_id)
    material = fx.create_material(api, project_id)
    fx.approve_material(api, material["id"])
    drawing = fx.create_drawing(
        api,
        project_id,
        material["id"],
        drawing_number="SD-950",
        subject_case_id=cases[0]["id"],
    )
    priced = _approve_sheet(api, drawing["id"], 10.0)
    assert priced["actual_cost_cents"] == 137500
    ctx.update(
        cases=cases,
        artifacts=artifacts,
        first_case_id=cases[0]["id"],
        queued_case_id=cases[2]["id"],
        first_artifact_id=artifacts[0]["id"],
        drawing_id=drawing["id"],
    )
    return ctx


def test_a_full_zone_refuses_the_third_case_without_consuming_a_slot(api):
    """Both slots are reserved, so the queued case is turned away and nothing moves.

    "Each gallery zone declares a `case_slot_capacity`, tracks `reserved_case_slots` and exposes `available_case_slots`; the identity that capacity equals reserved plus available holds before and after every operation that touches a slot."
    "An `APPROVE` demands three things of the case and its zone before it will land: `env_feasible` must be true, or the ruling is refused with `ERR_ENV_ENVELOPE_INFEASIBLE`; `security_ok` must be true, or it is refused with `ERR_SECURITY_TIER_INSUFFICIENT`; and the zone the case sits in must have at least one `available_case_slots`, or it is refused with `ERR_ZONE_CASE_SLOTS_EXHAUSTED` (HTTP 409)."
    Design: Difficulty/compensating_invariant/the_zone_slot_identity_survives_an_approve_void_reapprove_cycle_with_no_drift
    """
    ctx = _zone_filled_with_a_third_case_queued(api)
    before_zone = _read_zone(api, ctx["zone_id"])
    assert before_zone["case_slot_capacity"] == 2
    assert_zone_slots(before_zone, 2, 0)
    before_case = _read_case(api, ctx["queued_case_id"])

    refused = api.case_conservator_decision(
        ctx["queued_case_id"], f.case_decision_payload(CaseDecision.APPROVE), CONSERVATOR
    )
    validate_error(refused, ERR_ZONE_CASE_SLOTS_EXHAUSTED, 409)

    after_case = _read_case(api, ctx["queued_case_id"])
    assert after_case["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert_unchanged(before_case, after_case, ["status", "version", "decided_at"])
    after_zone = _read_zone(api, ctx["zone_id"])
    assert_zone_slots(after_zone, 2, 0)
    assert_unchanged(
        before_zone,
        after_zone,
        ["case_slot_capacity", "reserved_case_slots", "available_case_slots", "version"],
    )


def test_the_void_cascade_hands_back_the_slot_and_empties_the_case(api):
    """Voiding the sheet returns the slot, the case to DRAFT and the object to the pool.

    "When the sheet names a subject case that stands at `APPROVED` or `CONDITIONALLY_APPROVED`, that case reverts to `DRAFT`, gives back its zone case slot, clears its `conditions`, falls back from `MOUNT_FABRICATED` to `MOUNT_DESIGN` if its mount had got that far, and releases every `RESERVED` object in it to `UNPLACED` with `assigned_case_id` cleared and `placed_artifact_count` zeroed."
    "When the set is empty, the three derived limits are null and both feasibility flags are true."
    Design: Difficulty/compensating_invariant/the_zone_slot_identity_survives_an_approve_void_reapprove_cycle_with_no_drift
    """
    ctx = _zone_filled_with_a_third_case_queued(api)
    assert_ledger(fx.read_project(api, ctx["project_id"]), 137500, 8862500)

    validate_success(api.void_drawing(ctx["drawing_id"], f.void_payload(), PM), 200)

    zone = _read_zone(api, ctx["zone_id"])
    assert_zone_slots(zone, 1, 1)

    case = _read_case(api, ctx["first_case_id"])
    assert case["status"] == CaseStatus.DRAFT
    assert case["mount_status"] == MountStatus.NOT_STARTED
    assert case["conditions"] is None
    assert_empty_envelope(case)

    artifact = _read_artifact(api, ctx["first_artifact_id"])
    assert artifact["placement_status"] == PlacementStatus.UNPLACED
    assert artifact["assigned_case_id"] is None

    assert_ledger(fx.read_project(api, ctx["project_id"]), 0, CONTRACT_CENTS)


def test_the_freed_slot_goes_to_the_queued_case_and_the_reverted_one_waits(api):
    """The single freed slot is taken by the queued case, and the reverted case is refused it.

    "On success the case becomes `APPROVED`, its `conditions` is set to null, and the zone reserves the slot: `reserved_case_slots` rises by one and `available_case_slots` falls by one, preserving the capacity identity, with the zone's own `updated_at` and `version` advancing."
    "An `APPROVE` demands three things of the case and its zone before it will land: `env_feasible` must be true, or the ruling is refused with `ERR_ENV_ENVELOPE_INFEASIBLE`; `security_ok` must be true, or it is refused with `ERR_SECURITY_TIER_INSUFFICIENT`; and the zone the case sits in must have at least one `available_case_slots`, or it is refused with `ERR_ZONE_CASE_SLOTS_EXHAUSTED` (HTTP 409)."
    Design: Difficulty/compensating_invariant/the_zone_slot_identity_survives_an_approve_void_reapprove_cycle_with_no_drift
    """
    ctx = _zone_filled_with_a_third_case_queued(api)
    validate_success(api.void_drawing(ctx["drawing_id"], f.void_payload(), PM), 200)
    assert_zone_slots(_read_zone(api, ctx["zone_id"]), 1, 1)

    promoted = fx.decide_case(api, ctx["queued_case_id"], CaseDecision.APPROVE)
    assert promoted["status"] == CaseStatus.APPROVED
    assert_zone_slots(_read_zone(api, ctx["zone_id"]), 2, 0)

    fx.place_artifact(api, ctx["first_case_id"], ctx["first_artifact_id"])
    resubmitted = fx.submit_case(api, ctx["first_case_id"])
    assert resubmitted["status"] == CaseStatus.CONSERVATOR_REVIEW

    refused = api.case_conservator_decision(
        ctx["first_case_id"], f.case_decision_payload(CaseDecision.APPROVE), CONSERVATOR
    )
    validate_error(refused, ERR_ZONE_CASE_SLOTS_EXHAUSTED, 409)

    final_zone = _read_zone(api, ctx["zone_id"])
    assert_zone_slots(final_zone, 2, 0)
    assert final_zone["case_slot_capacity"] == 2


# ---------------------------------------------------------------------------
# withdrawing a placement relaxes the envelope back to the exact prior bounds
# ---------------------------------------------------------------------------
def _case_with_four_candidate_objects(api):
    """A tight case in DESIGN_DEV and four collection objects competing for it.

    The case holds 50 percent relative humidity to a two-point tolerance and lights
    to 50 lux. The wide object tolerates 45 to 55 percent at 50 lux, the narrow one
    48 to 52 percent at 60 lux, the dim one 48 to 52 percent at only 40 lux, and the
    guarded one is a high-value object the case's build tier cannot carry.
    """
    ctx = _schematic_commission(api)
    project_id = ctx["project_id"]
    case = fx.create_case(
        api,
        project_id,
        ctx["zone_id"],
        rh_tolerance_pct=2.0,
        uv_microwatt_per_lumen=20.0,
    )
    wide = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.3",
        material_class=MaterialClass.PAPER,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    narrow = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.4",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        max_lux=60.0,
        security_class=SecurityTier.ENHANCED,
    )
    dim = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.6",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        max_lux=40.0,
        security_class=SecurityTier.ENHANCED,
    )
    guarded = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.5",
        material_class=MaterialClass.METAL,
        required_rh_min_pct=40.0,
        required_rh_max_pct=60.0,
        max_lux=200.0,
        security_class=SecurityTier.HIGH_VALUE,
    )
    _advance_to_design_dev(api, project_id)
    ctx.update(
        case=case,
        case_id=case["id"],
        wide_id=wide["id"],
        narrow_id=narrow["id"],
        dim_id=dim["id"],
        guarded_id=guarded["id"],
    )
    return ctx


def _withdraw(api, case_id, artifact_id):
    """Withdraw a reserved object from the case it sits in."""
    return validate_success(api.delete_placement(case_id, artifact_id, CURATOR), 200)


def test_the_envelope_tightens_to_the_strictest_bound_as_objects_go_in(api):
    """Two objects fold to the largest floor, the smallest ceiling and the smallest lux.

    "When it is not empty, `required_rh_min_pct` becomes the **largest** of the objects' individual humidity floors, `required_rh_max_pct` becomes the **smallest** of their humidity ceilings, and `allowed_lux` becomes the **smallest** of their `max_lux` values."
    "Every one of those comparisons is inclusive, so a case whose `target_lux` exactly equals the strictest `allowed_lux` passes."
    Design: Difficulty/compensating_invariant/withdrawing_a_placement_relaxes_the_envelope_back_to_the_exact_prior_bounds
    """
    ctx = _case_with_four_candidate_objects(api)
    empty = _read_case(api, ctx["case_id"])
    assert empty["status"] == CaseStatus.DRAFT
    assert_empty_envelope(empty)

    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    with_one = _read_case(api, ctx["case_id"])
    assert_envelope(
        with_one,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )

    fx.place_artifact(api, ctx["case_id"], ctx["narrow_id"])
    with_two = _read_case(api, ctx["case_id"])
    assert_envelope(
        with_two,
        placed_artifact_count=2,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )


def test_a_refused_placement_leaves_the_envelope_exactly_as_it_was(api):
    """Neither the dim object nor the guarded one is admitted, and nothing drifts.

    "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."
    Design: Difficulty/compensating_invariant/withdrawing_a_placement_relaxes_the_envelope_back_to_the_exact_prior_bounds
    """
    ctx = _case_with_four_candidate_objects(api)
    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["narrow_id"])
    before = _read_case(api, ctx["case_id"])

    too_dim = api.create_placement(
        ctx["case_id"], f.placement_payload(ctx["dim_id"], before["version"]), CURATOR
    )
    validate_error(too_dim, ERR_ENV_ENVELOPE_INFEASIBLE, 422)
    after_dim = _read_case(api, ctx["case_id"])
    assert_unchanged(
        before,
        after_dim,
        [
            "version",
            "placed_artifact_count",
            "required_rh_min_pct",
            "required_rh_max_pct",
            "allowed_lux",
            "env_feasible",
        ],
    )
    assert _read_artifact(api, ctx["dim_id"])["placement_status"] == PlacementStatus.UNPLACED

    too_valuable = api.create_placement(
        ctx["case_id"],
        f.placement_payload(ctx["guarded_id"], after_dim["version"]),
        CURATOR,
    )
    validate_error(too_valuable, ERR_SECURITY_TIER_INSUFFICIENT, 422)
    after_guarded = _read_case(api, ctx["case_id"])
    assert_envelope(
        after_guarded,
        placed_artifact_count=2,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )
    assert_unchanged(before, after_guarded, ["version"])


def test_withdrawing_an_object_refolds_the_remaining_set(api):
    """The bounds come back to their exact prior values, then relax past them.

    "A `RESERVED` object returns to `UNPLACED` and its `assigned_case_id` is cleared, so `placed_artifact_count` returns to exactly its pre-placement value with no drift."
    "When it is not empty, `required_rh_min_pct` becomes the **largest** of the objects' individual humidity floors, `required_rh_max_pct` becomes the **smallest** of their humidity ceilings, and `allowed_lux` becomes the **smallest** of their `max_lux` values."
    Design: Difficulty/compensating_invariant/withdrawing_a_placement_relaxes_the_envelope_back_to_the_exact_prior_bounds
    """
    ctx = _case_with_four_candidate_objects(api)
    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    with_one = _read_case(api, ctx["case_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["narrow_id"])

    _withdraw(api, ctx["case_id"], ctx["narrow_id"])
    back_to_one = _read_case(api, ctx["case_id"])
    assert_envelope(
        back_to_one,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )
    assert_unchanged(
        with_one,
        back_to_one,
        [
            "placed_artifact_count",
            "required_rh_min_pct",
            "required_rh_max_pct",
            "allowed_lux",
        ],
    )

    fx.place_artifact(api, ctx["case_id"], ctx["narrow_id"])
    tight_again = _read_case(api, ctx["case_id"])
    assert_envelope(
        tight_again,
        placed_artifact_count=2,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=50.0,
        env_feasible=True,
    )

    _withdraw(api, ctx["case_id"], ctx["wide_id"])
    refolded = _read_case(api, ctx["case_id"])
    assert_envelope(
        refolded,
        placed_artifact_count=1,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=60.0,
        env_feasible=True,
        security_ok=True,
    )
    assert _read_artifact(api, ctx["wide_id"])["placement_status"] == PlacementStatus.UNPLACED


def test_emptying_the_case_restores_the_null_bounds_and_the_unplaced_pool(api):
    """An emptied case reports null bounds, keeps its geometry and cannot be reviewed.

    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    "When the set is empty, the three derived limits are null and both feasibility flags are true."
    "An empty case has no envelope to review, so submission requires `placed_artifact_count` of at least 1 and otherwise fails with `ERR_CASE_HAS_NO_ARTIFACTS` (HTTP 422); the project must not be in `FROZEN_CONSERVATION`; and the envelope is recomputed immediately before the transition so the conservator rules on current numbers."
    Design: Difficulty/compensating_invariant/withdrawing_a_placement_relaxes_the_envelope_back_to_the_exact_prior_bounds
    """
    ctx = _case_with_four_candidate_objects(api)
    empty = _read_case(api, ctx["case_id"])
    assert_geometry(empty, 0.648, 0.91)

    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["narrow_id"])
    _withdraw(api, ctx["case_id"], ctx["wide_id"])
    _withdraw(api, ctx["case_id"], ctx["narrow_id"])

    emptied = _read_case(api, ctx["case_id"])
    assert emptied["status"] == CaseStatus.DRAFT
    assert_empty_envelope(emptied)
    assert_geometry(emptied, 0.648, 0.91)

    refused = api.submit_case_for_conservation(ctx["case_id"], PM)
    validate_error(refused, ERR_CASE_HAS_NO_ARTIFACTS, 422)
    assert _read_case(api, ctx["case_id"])["status"] == CaseStatus.DRAFT

    released = _read_artifact(api, ctx["narrow_id"])
    assert released["placement_status"] == PlacementStatus.UNPLACED
    assert released["assigned_case_id"] is None
