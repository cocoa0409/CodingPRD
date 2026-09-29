"""The engineering revision state machine: rework loops, release, sunset, obsolescence."""
from test_helpers import (
    assert_instant,
    abort_run_payload,
    accumulate_cycle_evidence,
    firmware_release_payload,
    install_job_payload,
    make_compliance_officer_headers,
    model_revision_payload,
    new_equipment_model,
    new_facility,
    new_maintenance_visit,
    new_model_revision,
    new_service_partner,
    new_test_rig,
    order_payload,
    pm_program_payload,
    read_equipment_model,
    read_facility,
    read_firmware_certification,
    read_maintenance_visit,
    read_model_revision,
    read_order,
    read_pm_program,
    read_qualification_report,
    read_serialized_asset,
    read_service_partner,
    read_test_rig,
    read_test_run,
    receive_parts,
    refurb_intake,
    release_revision,
    resell_payload,
    rework_payload,
    scrap_payload,
    set_logical_clock,
    setup_active_pm_program,
    setup_configured_order,
    setup_installed_order,
    setup_qualified_revision,
    setup_released_revision,
    submit_for_testing,
    sunset_payload,
    sunset_revision,
    run_payload,
    trade_in_asset,
    load_firmware,
    confirm_ctx,
    quote_ctx,
    validate_error,
    validate_paginated,
    validate_success,
)

RIG_C = {"name": "RIG-C", "parallel_station_count": 2,
         "supported_duty_classes": ["FULL_COMMERCIAL"]}


def _test_failed_revision():
    """A FULL_COMMERCIAL revision pushed to TEST_FAILED by a late failure."""
    specs = [
        {"window_start": "2026-08-02T00:00:00Z", "window_end": "2026-08-06T12:00:00Z",
         "target_cycles": 300_000, "outcome": "PASSED", "achieved_cycles": 200_000},
        {"window_start": "2026-08-06T00:00:00Z", "window_end": "2026-08-10T12:00:00Z",
         "target_cycles": 300_000, "outcome": "FAILED", "failure_cycle_count": 150_000},
    ]
    model = new_equipment_model("T900")
    revision = new_model_revision(model, "T900", target_cycle_count=600_000)
    submit_for_testing(revision["id"])
    revision = read_model_revision(revision["id"])
    evidence = accumulate_cycle_evidence(revision, run_specs=specs)
    return {"model": model, "revision": read_model_revision(revision["id"]),
            "rig": evidence["rig"], "runs": evidence["runs"]}


def test_qualify_from_test_failed_is_an_undeclared_transition(api, product_engineer_headers):
    """TEST_FAILED carries no edge to QUALIFIED, so the shortcut is refused.

    The PRD declares that "Qualification itself moves a revision `IN_TESTING →
    QUALIFIED`", and the check ladder rejects anything else because "The target
    resource is in a state from which the requested transition is declared,
    otherwise `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Difficulty/non_linear_state_machine/revision_rework_loop_required_between_test_failed_and_qualify
    """
    ctx = _test_failed_revision()
    assert ctx["revision"]["status"] == "TEST_FAILED"
    assert ctx["revision"]["verified_cycle_count"] == 350_000

    response = api.qualify_revision(ctx["revision"]["id"], product_engineer_headers)

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
    still = read_model_revision(ctx["revision"]["id"], product_engineer_headers)
    assert still["status"] == "TEST_FAILED"
    assert still["qualified_at"] is None


def test_rework_zeroes_both_cycle_variants_immediately(api, product_engineer_headers):
    """The rework edge stamps the old runs and both variants fall back to zero.

    The PRD states that "every one of the revision's own `COMPLETED` durability
    runs has its `superseded_by_rework` flag set to true. Because a superseded
    run is excluded from both cycle-count variants forever,
    `verified_cycle_count` and `projected_cycle_count` both fall back to 0".

    Design: Difficulty/non_linear_state_machine/revision_rework_loop_required_between_test_failed_and_qualify
    """
    ctx = _test_failed_revision()

    response = api.rework_revision(
        ctx["revision"]["id"],
        rework_payload(rework_note="frame weld fixture revised"),
        product_engineer_headers,
    )

    reworked = validate_success(response)
    assert reworked["status"] == "DRAFT"
    assert reworked["rework_count"] == 1
    for run in ctx["runs"]:
        assert read_test_run(run["id"], product_engineer_headers)[
            "superseded_by_rework"
        ] is True
    report = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert report["verified_cycle_count"] == 0
    assert report["projected_cycle_count"] == 0
    assert report["completed_run_count"] == 0
    assert report["qualifies"] is False


def test_post_rework_evidence_alone_carries_the_revision_to_qualified(
    api, product_engineer_headers
):
    """After the loop only the fresh run counts, so the gate is met at 500,000.

    The PRD states that "a reworked revision re-accumulates its durability
    evidence from zero rather than inheriting the history of a design that
    failed", and qualification "requires `verified_cycle_count` to be greater
    than or equal to `min_required_cycles`".

    Design: Difficulty/non_linear_state_machine/revision_rework_loop_required_between_test_failed_and_qualify
    """
    ctx = _test_failed_revision()
    validate_success(
        api.rework_revision(ctx["revision"]["id"],
                            rework_payload(rework_note="frame weld fixture revised"),
                            product_engineer_headers)
    )
    submit_for_testing(ctx["revision"]["id"])
    third = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-10T00:00:00Z", "2026-08-14T12:00:00Z", 500_000),
            product_engineer_headers,
        ),
        201,
    )
    validate_success(api.start_test_run(third["id"], product_engineer_headers))
    validate_success(
        api.complete_test_run(third["id"],
                              {"outcome": "PASSED", "achieved_cycles": 500_000},
                              product_engineer_headers)
    )

    response = api.qualify_revision(ctx["revision"]["id"], product_engineer_headers)

    qualified = validate_success(response)
    assert qualified["status"] == "QUALIFIED"
    assert qualified["verified_cycle_count"] == 500_000
    assert qualified["projected_cycle_count"] == 500_000
    assert qualified["verified_cycle_count"] != 850_000
    assert qualified["rework_count"] == 1
    assert_instant(qualified["qualified_at"], "2026-08-01T00:00:00Z", "qualified_at")
    model = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    assert model["lifecycle_status"] == "PRE_RELEASE"
    assert model["released_revision_count"] == 0


def _sunset_cascade_fixture():
    """A connected asset in service, under an active PM program holding spares."""
    revision_ctx = setup_released_revision(
        "C700",
        revision_overrides={"target_cycle_count": 600_000, "revision_code": "C700-R1"},
        rig_overrides=RIG_C,
        certification_overrides={"test_report_ref": "RPT-C700-1"},
    )
    ctx = setup_installed_order(
        revision_ctx=revision_ctx,
        facility_overrides={"account_name": "Cadence Cycling Club", "freight_zone": "Z1"},
        partner_overrides={"name": "Cadence Service Co", "region": "R_WEST",
                           "certified_categories": ["CONNECTED"]},
    )
    load_firmware(ctx["asset"]["id"], ctx["firmware_release"]["id"])
    ctx["program"] = setup_active_pm_program(
        ctx["facility"]["id"], ctx["partner"]["id"], tier="PRO", visit_interval_days=90
    )
    receive_parts(ctx["partner"]["id"], 10)
    ctx["visit"] = new_maintenance_visit(
        ctx["program"]["id"], ctx["asset"]["id"], ctx["partner"]["id"],
        scheduled_date="2026-09-22T09:00:00Z", reserved_units=4,
    )
    return ctx


def test_sunset_cascades_through_model_asset_program_and_visit(api):
    """One sunset announcement propagates four levels outward in a single request.

    The PRD states that after the sunset "every serialized asset of this
    revision whose `status` is `IN_SERVICE` has its `firmware_support_expires_at`,
    `support_gap_days` and `connectivity_support_status` recomputed"; "every
    `ACTIVE` program covering any of those assets moves `ACTIVE →
    NEEDS_REVISION` with `needs_revision_reason` set to `CONSOLE_SUPPORT_LOST`;
    and every `SCHEDULED` visit of those programs moves `SCHEDULED → ON_HOLD`
    with `held_reason` `PROGRAM_NEEDS_REVISION`, releasing its held spare units."

    Design: Difficulty/transitive_cascade/revision_sunset_cascade_four_levels
    """
    ctx = _sunset_cascade_fixture()

    response = api.sunset_revision(
        ctx["revision"]["id"],
        sunset_payload(sunset_reason="next-generation console platform supersedes this build"),
        make_compliance_officer_headers("co-01"),
    )

    revision = validate_success(response)
    assert revision["status"] == "SUNSET_ANNOUNCED"
    assert_instant(revision["sunset_announced_at"], "2026-08-01T00:00:00Z", "sunset_announced_at")
    assert_instant(revision["firmware_support_until"], "2031-07-31T00:00:00Z", "firmware_support_until")
    assert read_equipment_model(ctx["model"]["id"])["lifecycle_status"] == "SUNSET"
    program = read_pm_program(ctx["program"]["id"])
    assert program["status"] == "NEEDS_REVISION"
    assert program["needs_revision_reason"] == "CONSOLE_SUPPORT_LOST"
    visit = read_maintenance_visit(ctx["visit"]["id"])
    assert visit["status"] == "ON_HOLD"
    assert visit["held_reason"] == "PROGRAM_NEEDS_REVISION"
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["spare_stock_reserved_units"] == 0
    assert partner["spare_stock_on_hand_units"] == 10


def test_sunset_keeps_the_console_supported_and_the_certification_intact(api):
    """The five-year commitment outlives the three-year warranty, so no gap opens.

    The PRD states that `firmware_support_expires_at` "takes the revision's
    `firmware_support_until`, and the status is `SUNSET_TRACKED` when that
    horizon is at or after `warranty_expires_at`", with `support_gap_days`
    "floored at zero so it is never negative".

    Design: Difficulty/transitive_cascade/revision_sunset_cascade_four_levels
    """
    ctx = _sunset_cascade_fixture()
    asset_before = read_serialized_asset(ctx["asset"]["id"])
    assert asset_before["connectivity_support_status"] == "SUPPORTED"
    assert_instant(asset_before["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")

    validate_success(
        api.sunset_revision(
            ctx["revision"]["id"],
            sunset_payload(
                sunset_reason="next-generation console platform supersedes this build"
            ),
            make_compliance_officer_headers("co-01"),
        )
    )

    asset = read_serialized_asset(ctx["asset"]["id"])
    assert_instant(asset["firmware_support_expires_at"], "2031-07-31T00:00:00Z", "firmware_support_expires_at")
    assert asset["connectivity_support_status"] == "SUNSET_TRACKED"
    assert asset["support_gap_days"] == 0
    assert asset["status"] == "IN_SERVICE"
    certification = read_firmware_certification(ctx["certification"]["id"])
    assert certification["cert_status"] == "CERTIFIED"
    partner = read_service_partner(ctx["partner"]["id"])
    assert float(partner["committed_hours"]) == 8.75
    assert partner["coverage_status"] == "ACTIVE"


def test_model_lifecycle_rollup_walks_the_four_derived_states(
    api, product_engineer_headers, compliance_officer_headers, service_ops_admin_headers
):
    """The model's lifecycle is a pure rollup, re-derived on every revision move.

    The PRD states that a model's `lifecycle_status` "is never supplied by a
    client; it is derived from its own revisions", that "A freshly registered
    model is `PRE_RELEASE`", and that `released_revision_count` "counts the
    model's own revisions whose `status` is `RELEASED`, `SUNSET_ANNOUNCED` or
    `OBSOLETE`."

    Design: Corner/calculations/model_lifecycle_rollup_walks_pre_release_active_sunset_obsolete
    """
    ctx = setup_qualified_revision("T900")
    while_qualified = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    assert while_qualified["lifecycle_status"] == "PRE_RELEASE"
    assert while_qualified["released_revision_count"] == 0

    release_revision(ctx["revision"]["id"])
    after_release = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    assert after_release["lifecycle_status"] == "ACTIVE"
    assert after_release["released_revision_count"] == 1

    sunset = sunset_revision(
        ctx["revision"]["id"],
        sunset_reason="platform refresh announced to the dealer network",
    )
    assert_instant(sunset["firmware_support_until"], "2031-07-31T00:00:00Z", "firmware_support_until")
    after_sunset = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    assert after_sunset["lifecycle_status"] == "SUNSET"
    assert after_sunset["released_revision_count"] == 1

    set_logical_clock("2031-08-01T00:00:00Z", service_ops_admin_headers)
    obsolete = validate_success(
        api.mark_revision_obsolete(ctx["revision"]["id"], compliance_officer_headers)
    )
    assert obsolete["status"] == "OBSOLETE"
    assert obsolete["verified_cycle_count"] == 500_000
    final = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    assert final["lifecycle_status"] == "OBSOLETE"
    assert final["released_revision_count"] == 1


def test_initial_states_of_five_freshly_created_entities(
    api, product_engineer_headers, order_planner_headers, service_ops_admin_headers
):
    """Five creates land on their own declared initial states in one pass.

    The PRD declares that "A new revision begins at `status` `DRAFT`", that a
    booking "creates the run at `status` `RESERVED` with `outcome` `PENDING`,
    `achieved_cycles` 0", that "A release begins at `status` `ACTIVE` with
    `certified_revision_count` at 0 and `withdrawn_at` null", and that "A program
    is created in `status` `DRAFT` with `covered_asset_count` 0".

    Design: Corner/state_machines/initial_states_of_revision_run_firmware_order_and_program
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    first = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], model["version"],
                                   revision_code="T900-R1", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    submit_for_testing(first["id"])
    rig = new_test_rig(headers=product_engineer_headers, parallel_station_count=2,
                       supported_duty_classes=["FULL_COMMERCIAL", "INSTITUTIONAL"])
    facility = new_facility(headers=order_planner_headers)
    partner = new_service_partner(headers=service_ops_admin_headers)
    fresh_model = read_equipment_model(model["id"], product_engineer_headers)

    second = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], fresh_model["version"],
                                   revision_code="T900-R2", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    run = validate_success(
        api.create_test_run(
            run_payload(first["id"], rig["id"], "2026-08-02T00:00:00Z",
                             "2026-08-06T12:00:00Z", 300_000),
            product_engineer_headers,
        ),
        201,
    )
    build = validate_success(
        api.create_firmware_release(firmware_release_payload(), product_engineer_headers),
        201,
    )
    order = validate_success(
        api.create_order(order_payload(facility["id"]), order_planner_headers), 201
    )
    program = validate_success(
        api.create_pm_program(pm_program_payload(facility["id"], partner["id"], "PRO", 90),
                              service_ops_admin_headers),
        201,
    )

    assert second["status"] == "DRAFT"
    assert second["rework_count"] == 0
    assert second["qualified_at"] is None
    assert run["status"] == "RESERVED"
    assert run["outcome"] == "PENDING"
    assert run["achieved_cycles"] == 0
    assert build["status"] == "ACTIVE"
    assert build["withdrawn_at"] is None
    assert build["certified_revision_count"] == 0
    assert order["config_status"] == "CONFIGURING"
    assert order["fulfillment_status"] == "PENDING"
    assert order["billing_status"] == "UNQUOTED"
    assert order["price_variant_applied"] == "NONE"
    assert order["quoted_at"] is None
    assert program["status"] == "DRAFT"
    assert program["covered_asset_count"] == 0
    assert float(program["annual_labor_hours_committed"]) == 0.0
    assert read_model_revision(first["id"], product_engineer_headers)["status"] == "IN_TESTING"


def test_submit_for_testing_moves_draft_to_in_testing(api, product_engineer_headers):
    """The one declared trigger out of DRAFT moves exactly one revision.

    The PRD states that "Submitting a revision for testing moves it `DRAFT →
    IN_TESTING`" and that "The submission takes no body."

    Design: Corner/state_machines/submit_for_testing_moves_draft_to_in_testing
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    revision = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], model["version"],
                                   revision_code="T900-R1", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )

    response = api.submit_revision_for_testing(revision["id"], product_engineer_headers)

    data = validate_success(response)
    assert data["status"] == "IN_TESTING"
    assert data["version"] == 2
    assert data["verified_cycle_count"] == 0
    assert data["projected_cycle_count"] == 0
    assert data["rework_count"] == 0
    assert data["qualified_at"] is None
    owning = read_equipment_model(model["id"], product_engineer_headers)
    assert owning["lifecycle_status"] == "PRE_RELEASE"
    assert owning["released_revision_count"] == 0


def test_undeclared_triggers_from_draft_are_all_rejected(
    api, product_engineer_headers, compliance_officer_headers
):
    """From DRAFT every other trigger reports the transition code, not its own gate.

    The PRD's ordered checks put the declared-transition test at rung 11 and
    state that "The **first** check that fails aborts the request immediately:
    no later check runs, no side effect of any kind is persisted, and the
    response carries exactly that check's error identifier and status."

    Design: Corner/state_machines/undeclared_triggers_from_draft_are_all_rejected
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    revision = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], model["version"],
                                   revision_code="T900-R1", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )

    validate_error(api.qualify_revision(revision["id"], product_engineer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)
    validate_error(api.release_revision(revision["id"], compliance_officer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)
    validate_error(
        api.sunset_revision(revision["id"],
                            sunset_payload(sunset_reason="cancelled programme"),
                            compliance_officer_headers),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )
    validate_error(api.mark_revision_obsolete(revision["id"], compliance_officer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)

    unchanged = read_model_revision(revision["id"], product_engineer_headers)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1, "no rejected attempt bumped the version"
    assert read_equipment_model(model["id"], product_engineer_headers)[
        "lifecycle_status"
    ] == "PRE_RELEASE"


def test_terminal_states_reject_every_further_trigger(
    api, product_engineer_headers, order_planner_headers, service_ops_admin_headers
):
    """A scrapped asset and a completed run both refuse any later trigger.

    The PRD declares that an asset's status walks through its states with "the
    last two being terminal", and that a run's status moves "through `RESERVED`,
    `RUNNING`, `COMPLETED` and `ABORTED`, the last two being terminal."

    Design: Corner/state_machines/terminal_states_reject_every_further_trigger
    """
    ctx = setup_installed_order(preset="T900")
    buyer = new_facility(headers=order_planner_headers,
                         account_name="Riverside Athletic Club", freight_zone="Z2")
    trade_in_asset(ctx["asset"]["id"], "A", order_planner_headers)
    refurb_intake(ctx["asset"]["id"], service_ops_admin_headers)
    validate_success(
        api.scrap_asset(ctx["asset"]["id"],
                        scrap_payload(scrap_reason="frame corrosion beyond repair"),
                        service_ops_admin_headers)
    )
    completed_run = ctx["runs"][0]

    validate_error(
        api.resell_asset(ctx["asset"]["id"], resell_payload(buyer["id"]),
                         order_planner_headers),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )
    validate_error(
        api.scrap_asset(ctx["asset"]["id"], scrap_payload(scrap_reason="second attempt"),
                        service_ops_admin_headers),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )
    validate_error(api.start_test_run(completed_run["id"], product_engineer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)
    validate_error(
        api.abort_test_run(completed_run["id"],
                           abort_run_payload(abort_reason="second attempt"),
                           product_engineer_headers),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )

    asset = read_serialized_asset(ctx["asset"]["id"], order_planner_headers)
    assert asset["status"] == "SCRAPPED"
    assert asset["facility_id"] == ctx["facility"]["id"], "the resell did not rewrite it"
    run = read_test_run(completed_run["id"], product_engineer_headers)
    assert run["status"] == "COMPLETED"
    assert run["achieved_cycles"] == 300_000


def test_replaying_an_already_applied_trigger_is_rejected(
    api, product_engineer_headers, order_planner_headers
):
    """Replay is not idempotent: the second call of each trigger is refused.

    The PRD's exposure figure is "the sum of `quoted_total_cents` over its own
    orders whose `config_status` is `CONFIRMED` and whose `billing_status` is
    `QUOTED` or `INVOICED`", so a refused replay must leave it untouched.

    Design: Corner/state_machines/replaying_an_already_applied_trigger_is_rejected
    """
    ctx = setup_configured_order(preset="T900", quantity=1, finish_codes=["GRAPHITE"])
    quote_ctx(ctx)
    confirm_ctx(ctx)

    validate_error(
        api.submit_revision_for_testing(ctx["revision"]["id"], product_engineer_headers),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )
    validate_error(api.qualify_revision(ctx["revision"]["id"], product_engineer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)
    validate_error(api.confirm_order(ctx["order"]["id"], order_planner_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)

    revision = read_model_revision(ctx["revision"]["id"], product_engineer_headers)
    assert revision["status"] == "RELEASED"
    assert revision["rework_count"] == 0
    order = read_order(ctx["order"]["id"], order_planner_headers)
    assert order["config_status"] == "CONFIRMED"
    assert order["fulfillment_status"] == "IN_PRODUCTION"
    assert order["billing_status"] == "QUOTED"
    assert order["quoted_total_cents"] == 560_310
    facility = read_facility(ctx["facility"]["id"], order_planner_headers)
    assert facility["open_order_exposure_cents"] == 560_310, "exposure is not double-counted"


def test_creation_gates_enforce_referenced_entity_state(
    api, product_engineer_headers, order_planner_headers, service_ops_admin_headers
):
    """Two creation endpoints report the transition code for a wrongly-stated referent.

    The PRD states that "Three creation operations carry the same class of gate
    and report the same code: creating a durability run requires the referenced
    revision to be `IN_TESTING`; creating an install job requires the referenced
    order to have `config_status` of `CONFIRMED`".

    Design: Corner/state_machines/creation_gates_enforce_referenced_entity_state
    """
    ctx = setup_configured_order(preset="T900", quantity=1, finish_codes=["GRAPHITE"])
    fresh_model = read_equipment_model(ctx["model"]["id"], product_engineer_headers)
    draft = validate_success(
        api.create_model_revision(
            model_revision_payload(fresh_model["id"], fresh_model["version"],
                                   revision_code="T900-R2", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    partner = new_service_partner(headers=service_ops_admin_headers)
    booking = run_payload(draft["id"], ctx["rig"]["id"], "2026-08-10T00:00:00Z",
                               "2026-08-14T12:00:00Z", 300_000)

    validate_error(api.create_test_run(booking, product_engineer_headers),
                   "ERR_INVALID_STATE_TRANSITION", 409)
    validate_error(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], partner["id"],
                                "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", 3.0),
            order_planner_headers,
        ),
        "ERR_INVALID_STATE_TRANSITION", 409,
    )

    submit_for_testing(draft["id"])
    assert read_model_revision(draft["id"], product_engineer_headers)["status"] == "IN_TESTING"
    accepted = validate_success(
        api.create_test_run(booking, product_engineer_headers), 201
    )
    assert accepted["status"] == "RESERVED"
    assert read_test_rig(ctx["rig"]["id"], product_engineer_headers)[
        "occupied_station_count"
    ] == 1
    _, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 0


def test_mark_obsolete_at_exactly_the_support_horizon_is_allowed(
    api, compliance_officer_headers, service_ops_admin_headers
):
    """The obsolescence comparison includes the horizon instant itself.

    The PRD states that obsolescence "is permitted only once the revision's
    `firmware_support_until` is at or before the current logical clock — the
    five-year commitment must actually have run out. An early attempt is refused
    with `ERR_SUPPORT_WINDOW_ACTIVE`."

    Design: Corner/validations/mark_obsolete_at_exactly_the_support_horizon_is_allowed
    """
    ctx = setup_released_revision("T900")
    announced = sunset_revision(
        ctx["revision"]["id"],
        sunset_reason="platform refresh announced to the dealer network",
    )
    assert_instant(announced["firmware_support_until"], "2031-07-31T00:00:00Z", "firmware_support_until")

    set_logical_clock("2031-07-30T00:00:00Z", service_ops_admin_headers)
    validate_error(
        api.mark_revision_obsolete(ctx["revision"]["id"], compliance_officer_headers),
        "ERR_SUPPORT_WINDOW_ACTIVE", 409,
    )
    assert read_model_revision(ctx["revision"]["id"])["status"] == "SUNSET_ANNOUNCED"

    set_logical_clock("2031-07-31T00:00:00Z", service_ops_admin_headers)
    obsolete = validate_success(
        api.mark_revision_obsolete(ctx["revision"]["id"], compliance_officer_headers)
    )
    assert obsolete["status"] == "OBSOLETE"
    assert_instant(obsolete["sunset_announced_at"], "2026-08-01T00:00:00Z", "sunset_announced_at")
    model = read_equipment_model(ctx["model"]["id"])
    assert model["lifecycle_status"] == "OBSOLETE"
    assert model["released_revision_count"] == 1


def test_the_fourth_rework_loop_on_one_revision_is_refused(api, product_engineer_headers):
    """The rework counter is cumulative per revision and caps at three loops.

    The PRD states that "The preconditions are that `rework_count` is strictly
    less than three completed rework loops — a fourth request is
    `ERR_REWORK_LIMIT_EXCEEDED`".

    Design: Corner/errors/the_fourth_rework_loop_on_one_revision_is_refused
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    revision = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], model["version"],
                                   revision_code="T900-R1", target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    submit_for_testing(revision["id"])

    for loop in (1, 2, 3):
        reworked = validate_success(
            api.rework_revision(revision["id"],
                                rework_payload(rework_note="frame weld fixture revised"),
                                product_engineer_headers)
        )
        assert reworked["status"] == "DRAFT"
        assert reworked["rework_count"] == loop
        resubmitted = validate_success(
            api.submit_revision_for_testing(revision["id"], product_engineer_headers)
        )
        assert resubmitted["status"] == "IN_TESTING"

    before = read_model_revision(revision["id"], product_engineer_headers)
    assert before["rework_count"] == 3
    assert before["status"] == "IN_TESTING"

    response = api.rework_revision(
        revision["id"],
        rework_payload(rework_note="fourth attempt at the weld fixture"),
        product_engineer_headers,
    )

    validate_error(response, "ERR_REWORK_LIMIT_EXCEEDED", 409)
    after = read_model_revision(revision["id"], product_engineer_headers)
    assert after["status"] == "IN_TESTING"
    assert after["rework_count"] == 3
