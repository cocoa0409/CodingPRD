"""Packaging runs: completion cascade, gate ordering, boundaries, OCC, SoD."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, api_client,
    make_packaging_operator_headers,
    create_product_payload, create_label_approval_payload, create_license,
    create_packaging_run_payload, set_clock,
    setup_fermenting_batch, setup_ready_batch, setup_active_product,
    setup_packaging_ready, complete_run,
    assert_packaging_run,
)

CO = TEST_USERS["compliance_officer_headers"]
PO = TEST_USERS["packaging_operator_headers"]


# ─── Difficulty: transitive_cascade / packaging complete ────────────────────

def test_packaging_complete_full_draw_cascades(api):
    """PRD section 3.5: "A successful completion stamps `packaged_at`, draws the
    run's `volume_liters` out of the batch's `volume_liters`, adds the same
    volume to the license's `volume_used_liters`, and increments the batch's
    `version` by one. When the draw empties the batch — `volume_liters` reaching
    zero — the batch auto-advances from `READY` to `PACKAGED` and its tank
    returns to `EMPTY` with `current_batch_id` cleared."

    A single 50-L run drains a 50-L batch: batch PACKAGED, tank EMPTY, license
    credited 50 L.

    Design: Difficulty/transitive_cascade/packaging_complete_cascades_batch_to_tank_to_license
    """
    ctx = setup_packaging_ready(volume_liters=50, target_abv_pct=5.0)
    run = complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    assert run["status"] == "COMPLETED"

    batch_after = validate_success(api.get_fermentation_batch(ctx["batch"]["id"], PO), 200)
    assert batch_after["volume_liters"] == 0
    assert batch_after["status"] == "PACKAGED", "emptying the batch auto-advances it"

    tank_after = validate_success(api.get_tank(ctx["tank"]["id"], PO), 200)
    assert tank_after["status"] == "EMPTY"
    assert tank_after["current_batch_id"] is None

    license_after = validate_success(api.get_license(ctx["license"]["id"], PO), 200)
    assert license_after["volume_used_liters"] == 50


def test_packaging_complete_partial_draw_leaves_batch_ready(api):
    """PRD section 3.5: "A successful completion stamps `packaged_at`, draws the
    run's `volume_liters` out of the batch's `volume_liters`, adds the same
    volume to the license's `volume_used_liters`, and increments the batch's
    `version` by one. When the draw empties the batch — `volume_liters` reaching
    zero — the batch auto-advances from `READY` to `PACKAGED` and its tank
    returns to `EMPTY` with `current_batch_id` cleared."

    A 30-L draw from a 50-L batch leaves 20 L: the batch stays READY, its
    version advances by exactly one, the tank remains occupied, and the license
    is credited 30 L.

    Design: Difficulty/transitive_cascade/packaging_complete_cascades_batch_to_tank_to_license
    """
    ctx = setup_packaging_ready(volume_liters=50, target_abv_pct=5.0,
                                run_volume_liters=30)
    version_before = ctx["batch"]["version"]

    run = complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    assert run["status"] == "COMPLETED"

    batch_after = validate_success(api.get_fermentation_batch(ctx["batch"]["id"], PO), 200)
    assert batch_after["volume_liters"] == 20, "50 - 30 packaged"
    assert batch_after["status"] == "READY", "auto-advance only fires at zero volume"
    assert batch_after["version"] == version_before + 1, "completion increments the batch version by one"

    tank_after = validate_success(api.get_tank(ctx["tank"]["id"], PO), 200)
    assert tank_after["current_batch_id"] == ctx["batch"]["id"]

    license_after = validate_success(api.get_license(ctx["license"]["id"], PO), 200)
    assert license_after["volume_used_liters"] == 30


# ─── Difficulty: priority_pair_validation_conflict ──────────────────────────

def test_label_gate_precedes_batch_readiness_on_packaging_create(api):
    """PRD section 3.5: "Then the licensing and labeling gates of §3.4 run in
    sequence — license status (`ERR_LICENSE_NOT_ACTIVE`), label approval
    (`ERR_LABEL_NOT_APPROVED`), label expiry for non-federal markets
    (`ERR_LABEL_EXPIRED`), and permit expiry (`ERR_PERMIT_EXPIRED`). Only then
    do the batch checks run: the referenced fermentation batch must be `READY`
    (else `ERR_BATCH_NOT_READY`), and its `volume_liters` must cover the run's
    draw (else `ERR_INSUFFICIENT_VOLUME`)."

    With the label still SUBMITTED AND the batch still FERMENTING, the label
    gate fires first and masks the readiness failure.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_packaging_create
    """
    ctx = setup_fermenting_batch(actual_juice_liters=50, gravity_brix=8.0)
    product = validate_success(api.create_product(
        create_product_payload(sku="P8-SKU", target_abv_pct=5.0), CO), 201)
    label = validate_success(api.create_label_approval(
        product["id"], create_label_approval_payload(
            market="FEDERAL_TTB", application_number="TTB-P8"), CO), 201)
    assert label["status"] == "SUBMITTED", "Setup failed: label should be SUBMITTED"
    license_ = create_license()

    res = api.create_packaging_run(
        create_packaging_run_payload(product["id"], ctx["batch"]["id"],
                                     label["id"], license_["id"],
                                     volume_liters=50), PO)
    validate_error(res, "ERR_LABEL_NOT_APPROVED")


def test_batch_not_ready_when_label_gates_pass(api):
    """PRD section 3.5: "Only then do the batch checks run: the referenced
    fermentation batch must be `READY` (else `ERR_BATCH_NOT_READY`)".

    With license ACTIVE and label APPROVED, a FERMENTING batch surfaces the
    referential gate on its own.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_packaging_create
    """
    ctx = setup_fermenting_batch(actual_juice_liters=50, gravity_brix=8.0)
    prod = setup_active_product(target_abv_pct=5.0)
    license_ = create_license()

    res = api.create_packaging_run(
        create_packaging_run_payload(prod["product"]["id"], ctx["batch"]["id"],
                                     prod["labels"]["FEDERAL_TTB"]["id"],
                                     license_["id"], volume_liters=50), PO)
    validate_error(res, "ERR_BATCH_NOT_READY")


def test_suspended_license_masks_cap_exceeded_on_packaging_create(api):
    """PRD section 3.4: "Scheduling a packaging run and creating an interstate
    sales order both require the referenced license to be `ACTIVE` — a
    `SUSPENDED` or `EXPIRED` license is rejected with `ERR_LICENSE_NOT_ACTIVE`"
    PRD section 3.5: "Then the licensing and labeling gates of §3.4 run in
    sequence — license status (`ERR_LICENSE_NOT_ACTIVE`), label approval
    (`ERR_LABEL_NOT_APPROVED`), label expiry for non-federal markets
    (`ERR_LABEL_EXPIRED`), and permit expiry (`ERR_PERMIT_EXPIRED`)."
    PRD section 3.5: "Last comes the annual volume cap: a license with
    `annual_volume_cap_liters` of zero is uncapped and always passes; otherwise
    the projected total — the license's current `volume_used_liters` plus this
    run's `volume_liters` — is compared against the cap, and only a projection
    strictly greater than the cap is rejected with `ERR_LICENSE_CAP_EXCEEDED`,
    so landing exactly on the cap is allowed."

    License at cap (100 used of 100) and then SUSPENDED: the status gate runs
    before the fiscal cap check, so the rejection is ERR_LICENSE_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_cap_exceeded
    """
    ctx = setup_packaging_ready(volume_liters=200, target_abv_pct=5.0,
                                license_overrides={"annual_volume_cap_liters": 100},
                                run_volume_liters=100)
    complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    license_mid = validate_success(api.get_license(ctx["license"]["id"], PO), 200)
    assert license_mid["volume_used_liters"] == 100, "Setup failed: cap not reached"

    suspended = validate_success(api.suspend_license(ctx["license"]["id"], CO), 200)
    assert suspended["status"] == "SUSPENDED", "Setup failed: license not SUSPENDED"

    res = api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO)
    validate_error(res, "ERR_LICENSE_NOT_ACTIVE")


def test_cap_exceeded_when_license_active(api):
    """PRD section 3.5: "Last comes the annual volume cap: a license with
    `annual_volume_cap_liters` of zero is uncapped and always passes; otherwise
    the projected total — the license's current `volume_used_liters` plus this
    run's `volume_liters` — is compared against the cap, and only a projection
    strictly greater than the cap is rejected with `ERR_LICENSE_CAP_EXCEEDED`,
    so landing exactly on the cap is allowed."

    ACTIVE license, cap 100, nothing used: a 150-L run projects 150 > 100 and
    is rejected on the fiscal check alone.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_cap_exceeded
    """
    chain = setup_ready_batch(actual_juice_liters=200, measured_brix=13.0,
                              gravity_brix=4.0)
    prod = setup_active_product(target_abv_pct=5.0)
    license_ = create_license(annual_volume_cap_liters=100)

    res = api.create_packaging_run(
        create_packaging_run_payload(prod["product"]["id"], chain["batch"]["id"],
                                     prod["labels"]["FEDERAL_TTB"]["id"],
                                     license_["id"], volume_liters=150), PO)
    validate_error(res, "ERR_LICENSE_CAP_EXCEEDED")


# ─── Difficulty: boundary_precision_check ───────────────────────────────────

def test_abv_deviation_equal_to_tolerance_passes(api):
    """PRD section 3.5: "Next, ABV consistency is checked against the final
    gravity: the absolute difference between the batch's `abv_pct` — recomputed
    from the final gravity reading at packaging time — and the product's
    `target_abv_pct` must not exceed the product's `abv_tolerance_pct`; a
    strictly greater deviation is rejected with `ERR_ABV_OUT_OF_TOLERANCE`,
    while a deviation exactly equal to the tolerance passes."

    original 14.0, final gravity 4.3636 -> abv (14.0-4.3636)*0.55 = 5.30002 ->
    5.3 rounded half up; target 5.0, tolerance 0.3 -> deviation exactly 0.3
    passes.

    Design: Difficulty/boundary_precision_check/abv_tolerance_equality_passes
    """
    ctx = setup_packaging_ready(volume_liters=50, measured_brix=14.0,
                                gravity_brix=4.3636, target_abv_pct=5.0)
    run = complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    assert run["status"] == "COMPLETED", "deviation exactly at tolerance must pass"


def test_abv_deviation_beyond_tolerance_rejected(api):
    """PRD section 3.5: "a strictly greater deviation is rejected with
    `ERR_ABV_OUT_OF_TOLERANCE`, while a deviation exactly equal to the
    tolerance passes."

    original 14.0, final gravity 4.2 -> abv (14.0-4.2)*0.55 = 5.39 -> 5.4
    rounded half up; target 5.0, tolerance 0.3 -> deviation 0.4 > 0.3 rejects.

    Design: Difficulty/boundary_precision_check/abv_tolerance_equality_passes
    """
    ctx = setup_packaging_ready(volume_liters=50, measured_brix=14.0,
                                gravity_brix=4.2, target_abv_pct=5.0)
    batch = get_success_data(api.get_fermentation_batch(ctx["batch"]["id"], PO))
    # Completion order is state -> SoD -> ABV -> OCC (PRD 3.5): the completer
    # must differ from the scheduling operator or the SoD gate fires first and
    # masks the ABV rejection this test exercises.
    completer = make_packaging_operator_headers("op-abv-reject")
    res = api.complete_packaging_run(
        ctx["run"]["id"], {"expected_batch_version": batch["version"]}, completer)
    validate_error(res, "ERR_ABV_OUT_OF_TOLERANCE")

    run_after = validate_success(api.get_packaging_run(ctx["run"]["id"], PO), 200)
    assert run_after["status"] == "SCHEDULED", "rejected completion must not advance the run"


def test_license_cap_equality_passes(api):
    """PRD section 3.5: "only a projection strictly greater than the cap is
    rejected with `ERR_LICENSE_CAP_EXCEEDED`, so landing exactly on the cap is
    allowed."

    Cap 100, already used 50 (one completed 50-L run): a second 50-L run
    projects exactly 100 and is scheduled.

    Design: Difficulty/boundary_precision_check/license_cap_equality_passes
    """
    ctx = setup_packaging_ready(volume_liters=200, target_abv_pct=5.0,
                                license_overrides={"annual_volume_cap_liters": 100},
                                run_volume_liters=50)
    complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    license_mid = validate_success(api.get_license(ctx["license"]["id"], PO), 200)
    assert license_mid["volume_used_liters"] == 50, "Setup failed: expected 50 L used"

    run_b = validate_success(api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO), 201)
    assert run_b["status"] == "SCHEDULED", "projection equal to the cap must pass"


def test_license_cap_one_liter_over_rejected(api):
    """PRD section 3.5: "only a projection strictly greater than the cap is
    rejected with `ERR_LICENSE_CAP_EXCEEDED`, so landing exactly on the cap is
    allowed."

    Cap 100, already used 50: a 51-L run projects 101 > 100 and is rejected.

    Design: Difficulty/boundary_precision_check/license_cap_equality_passes
    """
    ctx = setup_packaging_ready(volume_liters=200, target_abv_pct=5.0,
                                license_overrides={"annual_volume_cap_liters": 100},
                                run_volume_liters=50)
    complete_run(ctx["run"]["id"], ctx["batch"]["id"])

    res = api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=51), PO)
    validate_error(res, "ERR_LICENSE_CAP_EXCEEDED")


# ─── Difficulty: cross_entity_state_dependency / batch readiness ────────────

def test_packaging_run_rejected_when_batch_aging(api):
    """PRD section 3.5: "Only then do the batch checks run: the referenced
    fermentation batch must be `READY` (else `ERR_BATCH_NOT_READY`)".

    The batch has reached AGING but not READY; scheduling a run against it is
    rejected.

    Design: Difficulty/cross_entity_state_dependency/packaging_run_requires_batch_ready
    """
    ctx = setup_fermenting_batch(actual_juice_liters=50, gravity_brix=4.0)
    aged = validate_success(api.age_batch(ctx["batch"]["id"], TEST_USERS["cellar_lead_headers"]), 200)
    assert aged["status"] == "AGING", "Setup failed: batch not AGING"
    prod = setup_active_product(target_abv_pct=5.0)
    license_ = create_license()

    res = api.create_packaging_run(
        create_packaging_run_payload(prod["product"]["id"], ctx["batch"]["id"],
                                     prod["labels"]["FEDERAL_TTB"]["id"],
                                     license_["id"], volume_liters=50), PO)
    validate_error(res, "ERR_BATCH_NOT_READY")


def test_packaging_run_rejected_when_batch_fermenting(api):
    """PRD section 3.5: "Only then do the batch checks run: the referenced
    fermentation batch must be `READY` (else `ERR_BATCH_NOT_READY`)".

    A batch still FERMENTING (never aged) is equally not READY.

    Design: Difficulty/cross_entity_state_dependency/packaging_run_requires_batch_ready
    """
    ctx = setup_fermenting_batch(actual_juice_liters=50, gravity_brix=4.0)
    assert ctx["batch"]["status"] == "FERMENTING", "Setup failed: batch not FERMENTING"
    prod = setup_active_product(target_abv_pct=5.0)
    license_ = create_license()

    res = api.create_packaging_run(
        create_packaging_run_payload(prod["product"]["id"], ctx["batch"]["id"],
                                     prod["labels"]["FEDERAL_TTB"]["id"],
                                     license_["id"], volume_liters=50), PO)
    validate_error(res, "ERR_BATCH_NOT_READY")


# ─── Difficulty: resource_temporal_overlap / license calendar-year window ───

def test_license_cap_window_resets_across_calendar_year(api):
    """PRD section 3.4: "The license starts `ACTIVE` with `volume_used_liters`
    at 0, and that tally accumulates the packaged volume attributed to the
    license during the calendar year."

    Cap 100 with 100 L packaged in 2026; once the logical clock crosses into
    2027 the new calendar year's tally starts empty, so a further 50-L run is
    scheduled.

    Design: Difficulty/resource_temporal_overlap/license_annual_window_spanning_calendar_year
    """
    ctx = setup_packaging_ready(
        volume_liters=300, target_abv_pct=5.0,
        license_overrides={"annual_volume_cap_liters": 100,
                           "expires_at": "2028-12-31T23:59:59Z"},
        run_volume_liters=50)
    complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    run_b = validate_success(api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO), 201)
    complete_run(run_b["id"], ctx["batch"]["id"])
    license_2026 = validate_success(api.get_license(ctx["license"]["id"], PO), 200)
    assert license_2026["volume_used_liters"] == 100, "Setup failed: expected cap reached"

    set_clock("2027-01-15T00:00:00Z")
    run_c = validate_success(api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO), 201)
    assert run_c["status"] == "SCHEDULED", "new calendar year resets the cap tally"


def test_license_cap_third_run_within_same_year_rejected(api):
    """PRD section 3.4: "The license starts `ACTIVE` with `volume_used_liters`
    at 0, and that tally accumulates the packaged volume attributed to the
    license during the calendar year."
    PRD section 3.5: "only a projection strictly greater than the cap is
    rejected with `ERR_LICENSE_CAP_EXCEEDED`".

    Cap 100 with 100 L already packaged in 2026: a third 50-L run in the same
    calendar year projects 150 > 100 and is rejected.

    Design: Difficulty/resource_temporal_overlap/license_annual_window_spanning_calendar_year
    """
    ctx = setup_packaging_ready(
        volume_liters=300, target_abv_pct=5.0,
        license_overrides={"annual_volume_cap_liters": 100},
        run_volume_liters=50)
    complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    run_b = validate_success(api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO), 201)
    complete_run(run_b["id"], ctx["batch"]["id"])

    res = api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=50), PO)
    validate_error(res, "ERR_LICENSE_CAP_EXCEEDED")


# ─── Corner: endpoints / errors / cross-cutting ─────────────────────────────

def test_get_packaging_run_by_id(api):
    """PRD section 3.5: "Container sizes are fixed: 0.355 liters for a 12-ounce
    can, 0.473 for a 16-ounce can, 0.500 and 0.750 liters for the two bottle
    formats, and 18.927 and 58.674 liters for the 5- and 15.5-gallon kegs. At
    scheduling, `units_produced` is computed as the run's `volume_liters`
    divided by the container size, floored to whole containers"

    25 L into 0.500-L bottles -> exactly 50 units on the persisted run.

    Design: Corner/endpoints/get_packaging_run_by_id
    """
    ctx = setup_packaging_ready(volume_liters=25, measured_brix=13.0,
                                gravity_brix=4.0, target_abv_pct=5.0,
                                run_volume_liters=25)
    run = validate_success(api.get_packaging_run(ctx["run"]["id"], PO), 200)
    assert_packaging_run(run)
    assert run["id"] == ctx["run"]["id"]
    assert run["status"] == "SCHEDULED"
    assert run["units_produced"] == 50


def test_segregation_of_duties_same_operator_cannot_complete(api):
    """PRD section 3.5: "Segregation of duties is then enforced: the operator
    completing the run must not be the same `X-User-ID` that scheduled it, and
    a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Operator op-42 schedules the run and then attempts to complete it.

    Design: Corner/errors/error_segregation_of_duties_triggerable
    """
    op42 = make_packaging_operator_headers("op-42")
    ctx = setup_packaging_ready(volume_liters=50, target_abv_pct=5.0,
                                creator_headers=op42)
    batch = get_success_data(api.get_fermentation_batch(ctx["batch"]["id"], op42))
    res = api.complete_packaging_run(
        ctx["run"]["id"], {"expected_batch_version": batch["version"]}, op42)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    run_after = validate_success(api.get_packaging_run(ctx["run"]["id"], PO), 200)
    assert run_after["status"] == "SCHEDULED", "rejected completion must not advance the run"


def test_packaging_complete_stale_batch_version_rejected(api):
    """PRD section 2.8: "Completing a packaging run likewise requires
    `expected_batch_version`, holding the client-observed `version` of the
    target `FermentationBatch`. A mismatch with the batch's current `version` —
    for example because another operator has already drawn volume from the same
    batch — is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 2.9: "The stale-version check of §2.8 runs last on the two
    endpoints that carry it, after all state and business rules have passed."

    Two runs (30 L each, scheduled by different operators) share a 100-L batch.
    After the first completes — bumping the batch version — the second's
    completion with the pre-completion version is stale.

    Design: Corner/cross_cutting_layers/occ_packaging_complete_stale_batch
    """
    op_a = make_packaging_operator_headers("op-A")
    op_b = make_packaging_operator_headers("op-B")
    op_a2 = make_packaging_operator_headers("op-A2")
    op_b2 = make_packaging_operator_headers("op-B2")

    ctx = setup_packaging_ready(volume_liters=100, target_abv_pct=5.0,
                                run_volume_liters=30, creator_headers=op_a)
    run_b = validate_success(api.create_packaging_run(
        create_packaging_run_payload(ctx["product"]["id"], ctx["batch"]["id"],
                                     ctx["labels"]["FEDERAL_TTB"]["id"],
                                     ctx["license"]["id"], volume_liters=30), op_b), 201)
    batch_pre = get_success_data(api.get_fermentation_batch(ctx["batch"]["id"], PO))
    stale_version = batch_pre["version"]

    done_a = validate_success(api.complete_packaging_run(
        ctx["run"]["id"], {"expected_batch_version": stale_version}, op_a2), 200)
    assert done_a["status"] == "COMPLETED", "Setup failed: first run did not complete"

    res = api.complete_packaging_run(
        run_b["id"], {"expected_batch_version": stale_version}, op_b2)
    validate_error(res, "ERR_STALE_VERSION")

    run_b_after = validate_success(api.get_packaging_run(run_b["id"], PO), 200)
    assert run_b_after["status"] == "SCHEDULED", "stale completion must not advance the run"
    batch_after = validate_success(api.get_fermentation_batch(ctx["batch"]["id"], PO), 200)
    assert batch_after["volume_liters"] == 70, "only the first 30-L draw was applied"
