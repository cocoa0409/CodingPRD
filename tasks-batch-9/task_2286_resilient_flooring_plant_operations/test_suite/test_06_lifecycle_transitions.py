"""Lifecycle transitions across the plant's state machines.

These tests walk the declared edges and refusals of the production run
(PRD 3.6), the two independent SKU dimensions (PRD 3.5), laboratory panel
resolution and its bubble-up to certification (PRD 3.4), the design grant's
suspend/reactivate cycle and its deliberately asymmetric cascade (PRD 2.9,
PRD 3.2), allocation cancellation under discontinuation (PRD 3.8) and the
fork/join of warranty branch reviews through to settlement (PRD 3.9).
"""

from test_helpers import (
    CLOCK_BOOT_UTC,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    TECHNICAL_DIRECTOR_B,
    USER_IDS,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    ApiErrorId,
    assert_license_ledger,
    assert_qc_gates,
    assert_traceability_snapshot,
    begin_testing,
    build_filled_allocation,
    build_provisional_sku,
    build_sku,
    build_stock_batch,
    commercial_status_payload,
    create_allocation,
    create_claim,
    create_distributor,
    create_panel,
    create_press_line,
    create_run,
    get_success_data,
    record_result,
    run_abort_payload,
    run_completion_payload,
    set_clock,
    set_license_status,
    setup_run,
    start_panel,
    start_run,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scheduled_run_starts_planned_pending_and_reserves_licensed_volume(api):
    """Scheduling mints a run at both of its declared initial states and reserves volume.

    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Corner/state_machines/production_run_created_in_planned_pending_with_reservation
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    line = create_press_line(api)

    resp = api.create_production_run(
        {
            "run_code": "RUN-A1",
            "sku_id": built["sku"]["id"],
            "press_line_id": line["id"],
            "planned_start_utc": "2026-08-01T01:00:00Z",
            "planned_end_utc": "2026-08-01T09:00:00Z",
            "planned_quantity_sqm": 1200.00,
        },
        PRODUCTION_PLANNER,
    )
    run = validate_success(resp, 201)

    assert run["run_status"] == "PLANNED"
    assert run["qc_disposition"] == "PENDING"
    assert run["changeover_minutes_applied"] is None
    assert run["actual_quantity_sqm"] == 0
    assert run["royalty_accrued_cents"] == 0
    assert run["pattern_waste_sqm"] is None
    assert run["auto_disposition_recommendation"] is None
    for gate in (
        "registration_within_tolerance",
        "emboss_within_tolerance",
        "curl_within_tolerance",
        "tongue_within_tolerance",
    ):
        assert run[gate] is None, f"{gate} must be null on a freshly scheduled run"

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["term_volume_cap_sqm"] == 2000.00
    assert utilization["reserved_volume_sqm"] == 1200.00
    assert utilization["consumed_volume_sqm"] == 0.00
    assert utilization["projected_volume_sqm"] == 1200.00
    assert utilization["remaining_volume_sqm"] == 800.00
    assert utilization["accrued_royalty_cents"] == 0
    assert utilization["contributing_run_count"] == 0

    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"
    assert sku["commercial_status"] == "DEVELOPMENT"


def test_planned_to_setup_persists_a_zero_changeover_allowance(api):
    """The PLANNED -> SETUP edge stores the required gap and leaves QC alone.

    "Setup takes the run `PLANNED → SETUP` and is where the changeover
    allowance is persisted."
    "If no such predecessor exists the required gap is zero minutes."
    "The gap computation above is re-evaluated against the current predecessor
    and stored in `changeover_minutes_applied`."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/production_run_planned_to_setup_persists_changeover_allowance
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], line["id"])
    assert run["run_status"] == "PLANNED"
    assert run["version"] == 1

    data = validate_success(api.setup_production_run(run["id"], PRODUCTION_PLANNER))

    assert data["run_status"] == "SETUP"
    assert data["changeover_minutes_applied"] == 0
    assert data["version"] == 2
    assert data["qc_disposition"] == "PENDING"


def test_setup_is_refused_before_the_lead_window_and_admitted_on_its_boundary(api):
    """Setup is refused two hours and one minute out, then admitted at exactly minus 120.

    "And the logical clock must have reached `planned_start_utc` minus 120
    minutes: setup may not begin more than two hours before the planned start,
    and an early attempt is `ERR_SETUP_TOO_EARLY` (HTTP 409)."
    "Because a single request often breaks several rules at once, the server
    evaluates validations in a strict ascending order of fifteen bands and
    **stops at the first violation**; no later band is evaluated, and the
    response carries only that first rule's error."

    Design: Corner/state_machines/run_setup_before_lead_window_rejected_then_admitted_at_exact_boundary
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    line = create_press_line(api)
    run = create_run(
        api,
        built["sku"]["id"],
        line["id"],
        run_code="RUN-A5",
        planned_start_utc="2026-08-01T05:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )

    early = api.setup_production_run(run["id"], PRODUCTION_PLANNER)
    validate_error(early, ApiErrorId.SETUP_TOO_EARLY.value)

    unchanged = validate_success(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert unchanged["run_status"] == "PLANNED"
    assert unchanged["changeover_minutes_applied"] is None
    assert unchanged["version"] == 1

    set_clock(api, "2026-08-01T03:00:00Z")
    admitted = validate_success(
        api.setup_production_run(run["id"], PRODUCTION_PLANNER)
    )
    assert admitted["run_status"] == "SETUP"


def test_completion_settles_the_ledger_and_mints_the_traceable_batch(api):
    """RUNNING -> COMPLETED computes the gates, swings the ledger and mints one batch.

    "`pattern_waste_sqm` is the run's `actual_quantity_sqm` multiplied by the
    larger of the film's two pattern repeats, divided by 60000, multiplied by
    0.35, rounded half up to two decimal places."
    "`auto_disposition_recommendation` is set to `RELEASED` when all four gates
    hold and `QUARANTINED` otherwise; it is advisory only."
    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`
    and the measured `actual_quantity_sqm` is added to its
    `consumed_volume_sqm`."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps`
    divided by 10000, and the product is rounded half up to a whole cent."
    "Fourth, provided `actual_quantity_sqm` is strictly greater than zero,
    exactly one batch is minted."
    "When a run completes with positive output, the batch is minted with a
    `batch_code` formed as the producing run's `run_code` followed by the suffix
    `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised
    from it for stock selection, a `quantity_sqm` equal to the run's
    `actual_quantity_sqm` that never changes thereafter, an
    `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from
    the run's measurement — the reading that will later serve as warranty defect
    evidence."
    "The batch also carries an immutable `traceability_snapshot` captured at
    that instant, recording the recipe's `formulation_code` and revision number,
    the pinned `blended_cost_per_kg_cents`, the print film's design code, the
    grant's `license_code`, the press line's code, the run's `planned_start_utc`
    and `planned_end_utc`, and the SKU's specified wear-layer thickness."

    Design: Corner/state_machines/run_completion_mints_batch_with_nine_field_traceability_snapshot
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], line["id"])
    setup_run(api, run["id"])
    start_run(api, run["id"])

    completed = validate_success(
        api.complete_production_run(
            run["id"], run_completion_payload(1200.00), PRODUCTION_PLANNER
        )
    )

    assert completed["run_status"] == "COMPLETED"
    assert completed["pattern_waste_sqm"] == 8.40
    assert completed["royalty_accrued_cents"] == 126000
    assert_qc_gates(completed, True)
    assert completed["auto_disposition_recommendation"] == "RELEASED"

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 0.00
    assert utilization["consumed_volume_sqm"] == 1200.00
    assert utilization["accrued_royalty_cents"] == 126000
    assert utilization["contributing_run_count"] == 1

    rows, meta = validate_paginated(
        api.list_batches(QA_TECHNICIAN, params={"production_run_id": run["id"]})
    )
    assert meta["total_count"] == 1
    batch = validate_success(api.get_batch(rows[0]["id"], QA_TECHNICIAN))
    assert batch["batch_code"] == "RUN-A1-B1"
    assert batch["status"] == "IN_PRODUCTION"
    assert batch["production_run_id"] == run["id"]
    assert batch["sku_id"] == built["sku"]["id"]
    assert batch["quantity_sqm"] == 1200.00
    assert batch["available_quantity_sqm"] == 0.00
    assert batch["wear_layer_measured_mil"] == 12.0
    assert batch["hold_reason"] is None
    assert batch["held_by_user_id"] is None

    snapshot = batch["traceability_snapshot"]
    assert_traceability_snapshot(
        snapshot,
        {
            "formulation_code": "F-MIN",
            "blended_cost_per_kg_cents": 201,
            "license_code": "LIC-OAK",
            "planned_start_utc": "2026-08-01T01:00:00Z",
            "planned_end_utc": "2026-08-01T09:00:00Z",
        },
    )
    snapshot_values = list(snapshot.values())
    assert "PF-OAK-1200" in snapshot_values, "the film's design code is not recorded"
    assert "PL-1" in snapshot_values, "the press line's code is not recorded"


def test_completed_run_refuses_abort_and_leaves_the_ledger_and_batch_intact(api):
    """COMPLETED is outside the abort from-set, so no compensation happens.

    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an
    `abort_reason`, and it is an exact compensation: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`,
    restoring that figure to its pre-scheduling value bit for bit."
    "A run's `run_status` outside the declared from-set of the requested step is
    `ERR_INVALID_RUN_STATE` (HTTP 409)."
    "No batch is minted and no royalty is accrued, so a schedule-then-abort pair
    leaves the ledger indistinguishable from never having scheduled."

    Design: Corner/state_machines/completed_run_cannot_be_aborted_and_ledger_is_untouched
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], line["id"])
    setup_run(api, run["id"])
    start_run(api, run["id"])
    get_success_data(
        api.complete_production_run(
            run["id"], run_completion_payload(1200.00), PRODUCTION_PLANNER
        )
    )

    refused = api.abort_production_run(
        run["id"], run_abort_payload(), PRODUCTION_PLANNER
    )
    validate_error(refused, ApiErrorId.INVALID_RUN_STATE.value)

    after = validate_success(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert after["run_status"] == "COMPLETED"
    assert after["abort_reason"] is None
    assert after["royalty_accrued_cents"] == 126000

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert_license_ledger(
        utilization, reserved=0.00, consumed=1200.00, accrued_cents=126000
    )

    _rows, meta = validate_paginated(
        api.list_batches(QA_TECHNICIAN, params={"production_run_id": run["id"]})
    )
    assert meta["total_count"] == 1


def test_discontinued_commercial_dimension_refuses_all_three_targets(api):
    """DISCONTINUED accepts neither of the other targets nor a self-loop.

    "`DEVELOPMENT → RELEASED` and `HOLD → RELEASED` are both declared, as is
    `RELEASED → HOLD`, giving a `RELEASED → HOLD → RELEASED` cycle;
    `DISCONTINUED` is reachable from `DEVELOPMENT`, `RELEASED` or `HOLD` and is
    terminal on this dimension."
    "A `to_status` that is not reachable from the SKU's current
    `commercial_status` is `ERR_INVALID_COMMERCIAL_STATE` (HTTP 409)."
    "It forces `certification_status` to `DECERTIFIED` on the same row — the one
    place where a commercial decision overwrites the certification dimension"

    Design: Corner/state_machines/discontinued_sku_commercial_dimension_accepts_nothing_further
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    sku_id = built["sku"]["id"]

    discontinued = validate_success(
        api.set_sku_commercial_status(
            sku_id, commercial_status_payload("DISCONTINUED"), PLANT_ADMIN
        )
    )
    assert discontinued["commercial_status"] == "DISCONTINUED"
    assert discontinued["certification_status"] == "DECERTIFIED"
    locked_version = discontinued["version"]

    for to_status in ("RELEASED", "HOLD", "DISCONTINUED"):
        refused = api.set_sku_commercial_status(
            sku_id, commercial_status_payload(to_status), PLANT_ADMIN
        )
        validate_error(refused, ApiErrorId.INVALID_COMMERCIAL_STATE.value)

    after = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert after["commercial_status"] == "DISCONTINUED"
    assert after["certification_status"] == "DECERTIFIED"
    assert after["version"] == locked_version


def test_begin_testing_from_testing_is_rejected_rather_than_repeated(api):
    """A second begin-testing is a 409, not a silent re-entry that would re-clear the pins.

    "Beginning testing is a `QaTechnician` action that takes
    `certification_status` `UNCERTIFIED → TESTING` or `SUSPENDED → TESTING`;
    from any other certification state it is
    `ERR_INVALID_SKU_CERTIFICATION_STATE` (HTTP 409)."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/begin_testing_twice_is_rejected_not_silently_repeated
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    sku_id = built["sku"]["id"]
    first = begin_testing(api, sku_id)
    assert first["certification_status"] == "TESTING"

    refused = api.begin_sku_testing(sku_id, QA_TECHNICIAN)
    validate_error(refused, ApiErrorId.INVALID_SKU_CERTIFICATION_STATE.value)

    after = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert after["certification_status"] == "TESTING"
    assert after["version"] == 2


def test_certification_and_commercial_release_move_only_their_own_dimension(api):
    """Certifying leaves commerce at DEVELOPMENT; releasing leaves the pins and cost alone.

    "A SKU carries two independent status dimensions, and keeping them
    independent is deliberate: `certification_status` records what the
    laboratory and the technical function have established, while
    `commercial_status` records what the business has decided to sell."
    "Certification is a `TechnicalDirector` action reachable from `TESTING` or
    `PROVISIONAL` — `certification_status` `TESTING → CERTIFIED` and
    `PROVISIONAL → CERTIFIED` are treated identically."
    "`pinned_formulation_version` is set to the recipe's current `version` and
    `pinned_print_film_version` to the film's current `version`."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in
    §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the
    `target_margin_bps` gross-up."
    "`pin_stale` is set to false, `certified_at` to the logical clock and
    `certified_by_user_id` to the acting user."
    "Reaching `RELEASED` is additionally guarded across the dimension boundary:
    the SKU's `certification_status` must be exactly `CERTIFIED` and its
    `pin_stale` must be false"

    Design: Corner/state_machines/certification_and_commercial_dimensions_advance_independently
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    sku_id = built["sku"]["id"]

    certified = validate_success(api.certify_sku(sku_id, TECHNICAL_DIRECTOR_B))
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["commercial_status"] == "DEVELOPMENT"
    assert certified["standard_cost_cents_per_sqm"] == 1157
    assert certified["list_price_cents_per_sqm"] == 1562
    assert certified["pin_stale"] is False
    assert certified["certified_by_user_id"] == USER_IDS["technical_director_b"]
    assert certified["pinned_print_film_version"] == 1
    formulation = validate_success(
        api.get_formulation(built["formulation"]["id"], PLANT_ADMIN)
    )
    assert certified["pinned_formulation_version"] == formulation["version"]

    released = validate_success(
        api.set_sku_commercial_status(
            sku_id, commercial_status_payload("RELEASED"), PLANT_ADMIN
        )
    )
    assert released["commercial_status"] == "RELEASED"
    assert released["certification_status"] == "CERTIFIED"
    assert released["standard_cost_cents_per_sqm"] == 1157
    assert released["list_price_cents_per_sqm"] == 1562
    assert released["pinned_formulation_version"] == formulation["version"]
    assert released["pinned_print_film_version"] == 1
    assert released["pin_stale"] is False


def test_delamination_claim_joins_only_after_the_second_arm_and_settles_stepped(api):
    """A two-arm fork holds the claim in TRIAGE until the last arm is answered.

    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION`
    or `LOCK_FAILURE` claim requires both a materials review and a field review,
    while a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires
    the field review only."
    "The claim stays in `TRIAGE` while any required arm is unanswered; the
    instant every required arm carries a non-null outcome, the claim joins
    `TRIAGE → ADJUDICATION_READY`."
    "An approval takes it `ADJUDICATION_READY → APPROVED` and requires two
    further things: every required review outcome must be `DEFECT_CONFIRMED`,
    and any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval
    `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not
    be exhausted."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the
    SKU's `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the
    elapsed whole years as `elapsed_months` divided by twelve rounded down, then
    apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or
    3, 60 percent when it is 4 through 7, 40 percent when it is 8 through 12,
    and 20 percent beyond that, rounding the result half up to a whole cent."

    Design: Corner/state_machines/delamination_claim_forks_two_reviews_and_joins_to_adjudication_ready
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    set_clock(api, "2029-08-05T00:00:00Z")
    claim = create_claim(
        api,
        built["batch"]["id"],
        distributor["id"],
        claim_code="WC-DELAM-1",
        claim_type="DELAMINATION",
        claimed_area_sqm=25.50,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2029-08-05T00:00:00Z",
    )
    assert claim["status"] == "SUBMITTED"

    triaged = validate_success(
        api.triage_warranty_claim(claim["id"], WARRANTY_ADJUSTER)
    )
    assert triaged["status"] == "TRIAGE"
    assert triaged["assigned_adjuster_user_id"] == USER_IDS["warranty_adjuster"]
    arms = triaged["required_reviews"]
    assert len(arms) == 2, "DELAMINATION forks both a materials and a field review"

    after_first = validate_success(
        api.record_claim_review(
            claim["id"],
            {"review_kind": arms[0], "outcome": "DEFECT_CONFIRMED"},
            WARRANTY_ADJUSTER,
        )
    )
    assert after_first["status"] == "TRIAGE"
    answered = [
        after_first["materials_review_outcome"],
        after_first["field_review_outcome"],
    ]
    assert answered.count("DEFECT_CONFIRMED") == 1
    assert answered.count(None) == 1

    after_second = validate_success(
        api.record_claim_review(
            claim["id"],
            {"review_kind": arms[1], "outcome": "DEFECT_CONFIRMED"},
            WARRANTY_ADJUSTER,
        )
    )
    assert after_second["status"] == "ADJUDICATION_READY"
    assert after_second["materials_review_outcome"] == "DEFECT_CONFIRMED"
    assert after_second["field_review_outcome"] == "DEFECT_CONFIRMED"

    settled = validate_success(
        api.adjudicate_warranty_claim(
            claim["id"], {"decision": "APPROVE"}, WARRANTY_ADJUSTER_B
        )
    )
    assert settled["status"] == "APPROVED"
    assert settled["settlement_variant"] == "STEPPED_SCHEDULE"
    assert settled["elapsed_months"] == 36
    assert settled["replacement_value_cents"] == 53550
    assert settled["labor_allowance_cents"] == 0
    assert settled["settlement_amount_cents"] == 42840


def test_dimensional_movement_claim_forks_one_arm_and_joins_immediately(api):
    """The fork width follows claim_type: one arm joins on the first review.

    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION`
    or `LOCK_FAILURE` claim requires both a materials review and a field review,
    while a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires
    the field review only."
    "The claim stays in `TRIAGE` while any required arm is unanswered; the
    instant every required arm carries a non-null outcome, the claim joins
    `TRIAGE → ADJUDICATION_READY`."

    Design: Corner/state_machines/delamination_claim_forks_two_reviews_and_joins_to_adjudication_ready
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    set_clock(api, "2029-08-05T00:00:00Z")
    claim = create_claim(
        api,
        built["batch"]["id"],
        distributor["id"],
        claim_code="WC-DIM-1",
        claim_type="DIMENSIONAL_MOVEMENT",
    )

    triaged = triage_claim(api, claim["id"])
    arms = triaged["required_reviews"]
    assert len(arms) == 1, "DIMENSIONAL_MOVEMENT forks the field review only"

    joined = validate_success(
        api.record_claim_review(
            claim["id"],
            {"review_kind": arms[0], "outcome": "DEFECT_CONFIRMED"},
            WARRANTY_ADJUSTER,
        )
    )
    assert joined["status"] == "ADJUDICATION_READY"
    assert joined["field_review_outcome"] == "DEFECT_CONFIRMED"
    assert joined["materials_review_outcome"] is None


def test_discontinuation_cancels_the_open_allocation_and_spares_the_filled_one(api):
    """The cancellation cascade is conditional on allocation state.

    "It forces `certification_status` to `DECERTIFIED` on the same row — the one
    place where a commercial decision overwrites the certification dimension —
    and it cancels every allocation for the SKU whose `status` is `OPEN` or
    `PARTIALLY_FILLED`, deliberately leaving `FILLED` allocations alone."
    "Each cancelled allocation has every `ACTIVE` line voided with `void_reason`
    `ALLOCATION_CANCELLED`, and each voided line's `quantity_sqm` is added back
    to its batch's `available_quantity_sqm`."

    Design: Corner/state_machines/discontinue_cancels_open_allocation_but_spares_the_filled_one
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_filled_allocation(api)
    filled = built["allocation"]
    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 100.00
    assert built["batch"]["available_quantity_sqm"] == 1100.00

    open_allocation = create_allocation(
        api,
        built["distributor"]["id"],
        built["sku"]["id"],
        allocation_code="ALLOC-2",
        requested_quantity_sqm=50.00,
    )
    assert open_allocation["status"] == "OPEN"

    discontinued = validate_success(
        api.set_sku_commercial_status(
            built["sku"]["id"], commercial_status_payload("DISCONTINUED"), PLANT_ADMIN
        )
    )
    assert discontinued["commercial_status"] == "DISCONTINUED"
    assert discontinued["certification_status"] == "DECERTIFIED"

    spared = validate_success(api.get_allocation(filled["id"], PLANT_ADMIN))
    assert spared["status"] == "FILLED"
    assert spared["allocated_quantity_sqm"] == 100.00
    spared_lines, spared_meta = validate_paginated(
        api.list_allocation_lines(filled["id"], PLANT_ADMIN)
    )
    assert spared_meta["total_count"] == 1
    assert spared_lines[0]["status"] == "ACTIVE"
    assert spared_lines[0]["void_reason"] is None

    cancelled = validate_success(
        api.get_allocation(open_allocation["id"], PLANT_ADMIN)
    )
    assert cancelled["status"] == "CANCELLED"
    _cancelled_lines, cancelled_meta = validate_paginated(
        api.list_allocation_lines(open_allocation["id"], PLANT_ADMIN)
    )
    assert cancelled_meta["total_count"] == 0

    batch = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert batch["available_quantity_sqm"] == 1100.00


def test_license_reactivation_restores_the_film_but_not_the_sku_or_the_batch(api):
    """Suspension cascades three hops; reactivation deliberately restores only the film.

    "`ACTIVE → SUSPENDED` is a `PlantAdmin` action and cascades three hops:
    every `AVAILABLE` film on the grant moves to `RESTRICTED`; because those
    films were restricted, every SKU on one of them whose `commercial_status` is
    `RELEASED` moves to `HOLD`; and because those SKUs went on hold, each of
    their `IN_STOCK` batches moves to `HELD` with `hold_reason` `SKU_ON_HOLD`."
    "`SUSPENDED → ACTIVE` is the reverse edge, permitted only while the logical
    clock is strictly earlier than the grant's `valid_until`; it returns
    `RESTRICTED` films to `AVAILABLE` and stops there."
    "The SKUs put on hold stay on hold and the batches held stay held — the
    asymmetry of §2.9 in its most visible form."
    "Reactivating a suspended design grant restores the print films it
    restricted, but it does not restore the SKUs those films put on commercial
    hold, and it does not release the batches those SKUs held."
    "`IN_STOCK → HELD` records `held_by_user_id` as the acting user — or the
    string `system` when the transition arrived through a SKU-hold cascade
    rather than an operator action"

    Design: Corner/state_machines/license_suspend_then_reactivate_restores_films_only
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    assert built["batch"]["status"] == "IN_STOCK"

    suspended = set_license_status(api, built["license"]["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    film_held = validate_success(api.get_print_film(built["film"]["id"], PLANT_ADMIN))
    assert film_held["status"] == "RESTRICTED"
    sku_held = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku_held["commercial_status"] == "HOLD"
    assert sku_held["certification_status"] == "CERTIFIED"
    batch_held = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert batch_held["status"] == "HELD"
    assert batch_held["hold_reason"] == "SKU_ON_HOLD"
    assert batch_held["held_by_user_id"] == "system"
    assert batch_held["available_quantity_sqm"] == 1200.00

    reactivated = set_license_status(api, built["license"]["id"], "ACTIVE")
    assert reactivated["status"] == "ACTIVE"

    film_back = validate_success(api.get_print_film(built["film"]["id"], PLANT_ADMIN))
    assert film_back["status"] == "AVAILABLE"

    sku_after = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku_after["commercial_status"] == "HOLD"
    batch_after = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert batch_after["status"] == "HELD"
    assert batch_after["hold_reason"] == "SKU_ON_HOLD"


def test_panel_reaching_passed_advances_the_sku_to_provisional(api):
    """Completing coverage flips the panel to PASSED and bubbles up to the parent SKU.

    "Every panel requires `RESIDUAL_INDENTATION` and
    `DIMENSIONAL_STABILITY_HEAT`."
    "Each recorded measurement leaves the panel `IN_TEST` while coverage of
    `required_test_types` at the current `attempt_no` is still incomplete."
    "Otherwise, if coverage is complete and every outcome at that attempt is
    `PASS`, the panel moves `IN_TEST → PASSED`."
    "`DIMENSIONAL_STABILITY_HEAT` is measured in `PCT` and lower is better, with
    a limit of 0.15 for `CLICK_LOCK_SPC` and `CLICK_LOCK_WPC` constructions and
    0.25 for every other construction."
    "For a lower-is-better test the marginal edge is the limit multiplied by
    1.05, rounded half up to four decimal places; a `measured_value` no greater
    than the limit is `PASS`, a value above the limit but no greater than the
    marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "A panel that reaches `PASSED` whose coverage includes both
    `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's
    certification `TESTING → PROVISIONAL`."

    Design: Corner/state_machines/panel_pass_bubbles_up_to_sku_provisional_certification
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    sku_id = built["sku"]["id"]
    begin_testing(api, sku_id)
    panel = create_panel(api, sku_id)
    assert panel["required_test_types"] == [
        "RESIDUAL_INDENTATION",
        "DIMENSIONAL_STABILITY_HEAT",
    ]
    start_panel(api, panel["id"])
    first = record_result(api, panel["id"], "RESIDUAL_INDENTATION", 0.0800)
    assert first["outcome"] == "PASS"

    mid = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert mid["status"] == "IN_TEST"
    mid_sku = validate_success(api.get_product_sku(sku_id, QA_TECHNICIAN))
    assert mid_sku["certification_status"] == "TESTING"

    second = validate_success(
        api.record_test_result(
            panel["id"],
            {"test_type": "DIMENSIONAL_STABILITY_HEAT", "measured_value": 0.2000},
            QA_TECHNICIAN,
        ),
        201,
    )
    assert second["unit"] == "PCT"
    assert second["spec_limit"] == 0.25
    assert second["outcome"] == "PASS"

    resolved = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert resolved["status"] == "PASSED"
    assert resolved["attempt_no"] == 1
    assert resolved["retest_count"] == 0

    sku = validate_success(api.get_product_sku(sku_id, QA_TECHNICIAN))
    assert sku["certification_status"] == "PROVISIONAL"
