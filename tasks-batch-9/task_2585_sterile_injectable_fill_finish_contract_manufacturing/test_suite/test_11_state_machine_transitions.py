"""Initial states, undeclared transitions and terminal lockdowns.

The batch order runs two independent axes, the media fill, component lot,
excursion, deviation, review, audit engagement and project each run one, and the
logical clock drives three machines at once. Every test here proves either the
state a row is born in, the refusal of a transition the specification never
declared, or the exact ledger effect a legal transition carries.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QA_REVIEWER_SECOND,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: batch_order_starts_in_scheduled_and_pending_on_its_two_axes
# ---------------------------------------------------------------------------
def test_new_batch_is_scheduled_on_production_and_pending_on_quality(api):
    """The two axes start independently, and quality does not jump ahead.

    PRD 3.5: "A batch that survives all of the above is born with `production_status` of `SCHEDULED` and `quality_status` of `PENDING` on the two independent axes it will travel."

    Design: Corner/state_machines/batch_order_starts_in_scheduled_and_pending_on_its_two_axes
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)

    batch = validate_success(
        api.create_batch_order(
            factories.batch_order_payload(
                program["project_id"],
                program["suite_id"],
                program["qualification_ids"][0],
                fixtures.suite_version(api, program["suite_id"]),
            ),
            PROGRAM_MANAGER,
        ),
        201,
    )

    assert batch["production_status"] == "SCHEDULED"
    assert batch["quality_status"] == "PENDING"
    assert batch["version"] == 1
    assert batch["changeover_minutes_applied"] == constants.INITIAL_SETUP_MINUTES
    assert batch["component_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS
    assert batch["filled_unit_count"] is None
    assert batch["quarantined_unit_count"] == 0

    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"]
        == constants.WORKED_COMPONENT_DEMAND_UNITS
    )


# ---------------------------------------------------------------------------
# Design instance: batch_order_start_fill_from_scheduled_and_complete_fill_from_setup_rejected
# ---------------------------------------------------------------------------
def test_production_axis_refuses_to_skip_setup_or_skip_filling(api):
    """Start-fill from SCHEDULED and complete-fill from SETUP are both undeclared.

    PRD 3.6: "Starting the aseptic fill advances `SETUP → FILLING` and is the single most gated operation in the production axis, because it is the moment sterile product is exposed."

    PRD 3.6: "Closing the fill advances `FILLING → FILLED` and records `filled_unit_count`, the containers actually filled, which must be greater than 0 and at most `target_fill_units`."

    Design: Corner/state_machines/batch_order_start_fill_from_scheduled_and_complete_fill_from_setup_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_RESERVED)
    batch_id = program["batch_id"]

    validate_error(
        api.start_fill(batch_id, PRODUCTION_SUPERVISOR),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )
    validate_error(
        api.complete_fill(
            batch_id, factories.complete_fill_payload(9000), PRODUCTION_SUPERVISOR
        ),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )
    batch = fixtures.read_batch(api, batch_id)
    assert batch["production_status"] == "SCHEDULED"
    assert batch["version"] == 1

    assert fixtures.setup_batch(api, batch_id)["production_status"] == "SETUP"

    validate_error(
        api.complete_fill(
            batch_id, factories.complete_fill_payload(9000), PRODUCTION_SUPERVISOR
        ),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )
    batch = fixtures.read_batch(api, batch_id)
    assert batch["production_status"] == "SETUP"
    assert batch["quality_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Design instance: cancelled_batch_is_terminal_and_accepts_no_further_transition
# ---------------------------------------------------------------------------
def test_cancelled_batch_accepts_nothing_further_and_unwinds_only_once(api):
    """A second cancel, a setup and a start-fill all bounce off the terminal state.

    PRD 3.6: "`CANCELLED` is the production axis's only terminal state, and cancellation is available to a `ProgramManager` from `SCHEDULED`, `SETUP` or `SUSPENDED` with a `cancellation_reason`; a cancel attempted while the batch is `FILLING`, `FILLED` or already `CANCELLED` is refused with `ERR_BATCH_PRODUCTION_STATE_INVALID`."

    Design: Corner/state_machines/cancelled_batch_is_terminal_and_accepts_no_further_transition
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    batch_id = program["batch_id"]
    fixtures.cancel_batch(api, batch_id, PROGRAM_MANAGER)

    validate_error(
        api.cancel_batch(
            batch_id,
            factories.cancel_payload("Duplicate cancellation attempt."),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )
    validate_error(
        api.setup_batch(batch_id, PRODUCTION_SUPERVISOR),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )
    validate_error(
        api.start_fill(batch_id, PRODUCTION_SUPERVISOR),
        ApiErrorId.BATCH_PRODUCTION_STATE_INVALID,
        409,
    )

    batch = fixtures.read_batch(api, batch_id)
    assert batch["production_status"] == "CANCELLED"
    assert batch["quality_status"] == "REJECTED"
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 0
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"] == 0
    )


# ---------------------------------------------------------------------------
# Design instance: personnel_qualification_qualify_twice_rejected
# ---------------------------------------------------------------------------
def test_granting_an_already_qualified_record_twice_is_an_error_not_a_no_op(api):
    """The replay is refused and the roster is not double-counted.

    PRD 3.3: "A grant attempted from any status other than `PENDING` is refused with `ERR_QUALIFICATION_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/personnel_qualification_qualify_twice_rejected
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    _media_fill, records = fixtures.qualify_suite(
        api, suite["id"], operators=("OP-A", "OP-B"), qualify_operators=False
    )
    granted = fixtures.qualify(api, records[0]["id"])
    assert granted["status"] == "QUALIFIED"
    version_after_grant = granted["version"]

    validate_error(
        api.qualify(records[0]["id"], MICROBIOLOGY_ANALYST),
        ApiErrorId.QUALIFICATION_STATE_INVALID,
        409,
    )

    record = fixtures.read_qualification(api, records[0]["id"])
    assert record["status"] == "QUALIFIED"
    assert record["version"] == version_after_grant

    read_suite = fixtures.read_suite(api, suite["id"])
    assert read_suite["qualified_operator_count"] == 1
    assert read_suite["posture"] == constants.POSTURE_RESTRICTED


# ---------------------------------------------------------------------------
# Design instance: media_fill_adjudicate_from_incubating_and_execute_after_passed_rejected
# ---------------------------------------------------------------------------
def test_a_clean_simulation_readout_cannot_be_re_litigated_or_re_run(api):
    """Adjudication before the readout and execution after it are both refused.

    PRD 3.2: "Attempting to execute a simulation whose `status` is anything other than `SCHEDULED` yields `ERR_MEDIA_FILL_STATE_INVALID` (HTTP 409)."

    PRD 3.2: "Adjudication from any other `status` yields `ERR_MEDIA_FILL_STATE_INVALID`."

    Design: Corner/state_machines/media_fill_adjudicate_from_incubating_and_execute_after_passed_rejected
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    media_fill = fixtures.create_media_fill(api, suite["id"])
    fixtures.execute_media_fill(
        api,
        media_fill["id"],
        units_filled=6000,
        participating_operator_names=["OP-A", "OP-B"],
    )

    validate_error(
        api.adjudicate_media_fill(
            media_fill["id"],
            factories.media_fill_adjudicate_payload(
                outcome="PASSED",
                adjudication_rationale="Attempting to adjudicate before the readout.",
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.MEDIA_FILL_STATE_INVALID,
        409,
    )
    assert fixtures.read_media_fill(api, media_fill["id"])["status"] == "INCUBATING"

    passed = fixtures.read_media_fill_out(api, media_fill["id"], 0)
    assert passed["status"] == "PASSED"
    assert (
        fixtures.read_suite(api, suite["id"])["aseptic_qualification_status"]
        == "QUALIFIED"
    )

    validate_error(
        api.execute_media_fill(
            media_fill["id"],
            factories.media_fill_execute_payload(
                units_filled=6000, participating_operator_names=["OP-A"]
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.MEDIA_FILL_STATE_INVALID,
        409,
    )
    validate_error(
        api.adjudicate_media_fill(
            media_fill["id"],
            factories.media_fill_adjudicate_payload(
                outcome="FAILED",
                adjudication_rationale="Attempting to overturn a PASSED readout.",
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.MEDIA_FILL_STATE_INVALID,
        409,
    )

    assert fixtures.read_media_fill(api, media_fill["id"])["status"] == "PASSED"
    assertions.assert_same_instant(
        fixtures.read_suite(api, suite["id"])["media_fill_valid_until"],
        constants.MEDIA_FILL_VALID_UNTIL,
        "media_fill_valid_until",
    )


# ---------------------------------------------------------------------------
# Design instance: component_lot_second_sterilization_validation_rejected
# ---------------------------------------------------------------------------
def test_a_lot_takes_exactly_one_sterilisation_verdict(api):
    """Neither a released lot nor a rejected one accepts a second verdict.

    PRD 3.4: "The verdict is only accepted while the lot's `sterilization_validation_status` is still `PENDING`; a second verdict on the same lot is refused with `ERR_COMPONENT_LOT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/component_lot_second_sterilization_validation_rejected
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])
    vial = fixtures.release_lot(
        api, project["id"], component_type="VIAL", lot_code="VL-1"
    )
    stopper_lot = fixtures.create_lot(
        api,
        project["id"],
        component_type="STOPPER",
        lot_code="ST-1",
        quantity_received=12000,
    )
    rejected = fixtures.validate_sterilization(
        api, stopper_lot["id"], outcome="REJECTED", f0_minutes=4
    )
    assert rejected["status"] == "REJECTED"

    validate_error(
        api.record_sterilization_validation(
            vial["id"],
            factories.sterilization_validation_payload(outcome="RELEASED", f0_minutes=15),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.COMPONENT_LOT_STATE_INVALID,
        409,
    )
    validate_error(
        api.record_sterilization_validation(
            stopper_lot["id"],
            factories.sterilization_validation_payload(outcome="RELEASED", f0_minutes=20),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.COMPONENT_LOT_STATE_INVALID,
        409,
    )

    vial_after = fixtures.read_lot(api, vial["id"])
    assert vial_after["status"] == "RELEASED"
    assert vial_after["quantity_available"] == 30000
    stopper_after = fixtures.read_lot(api, stopper_lot["id"])
    assert stopper_after["status"] == "REJECTED"
    assert stopper_after["quantity_available"] == 0


# ---------------------------------------------------------------------------
# Design instance: em_sample_close_investigation_before_investigate_rejected
# ---------------------------------------------------------------------------
def test_the_excursion_machine_has_no_shortcut_from_open_to_closed(api):
    """Closing before investigating, re-investigating and touching a clean sample all fail.

    PRD 3.7: "An investigate or close attempted from a status that does not permit it is refused with `ERR_EXCURSION_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/em_sample_close_investigation_before_investigate_rejected
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(
        api,
        suite_code="FS-C",
        grade="C",
        changeover_minutes_same_product=30,
        changeover_minutes_product_change=120,
    )
    excursion = fixtures.record_em_sample(
        api, suite["id"], sample_type="VIABLE_AIR", cfu_count=60
    )
    clean = fixtures.record_em_sample(
        api, suite["id"], sample_type="VIABLE_AIR", cfu_count=10
    )

    validate_error(
        api.close_em_investigation(
            excursion["id"],
            factories.close_investigation_payload(
                "Attempting to close before opening the investigation."
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.EXCURSION_STATE_INVALID,
        409,
    )
    assert fixtures.read_em_sample(api, excursion["id"])["investigation_status"] == "OPEN"

    validate_error(
        api.investigate_em_sample(
            clean["id"],
            factories.investigate_payload(
                "Attempting to investigate a within-limit sample."
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.EXCURSION_STATE_INVALID,
        409,
    )
    clean_after = fixtures.read_em_sample(api, clean["id"])
    assert clean_after["investigation_status"] == "NOT_REQUIRED"
    assert clean_after["classification"] == "WITHIN_LIMIT"
    assert clean_after["risk_index"] == 0

    opened = fixtures.investigate_em(api, excursion["id"])
    assert opened["investigation_status"] == "INVESTIGATING"

    validate_error(
        api.investigate_em_sample(
            excursion["id"],
            factories.investigate_payload("Duplicate investigation attempt."),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.EXCURSION_STATE_INVALID,
        409,
    )

    closed = fixtures.close_em_investigation(
        api,
        excursion["id"],
        root_cause="Transient HVAC pressure loss during gowning.",
    )
    assert closed["investigation_status"] == "CLOSED"
    assert closed["root_cause"] == "Transient HVAC pressure loss during gowning."


# ---------------------------------------------------------------------------
# Design instance: deviation_submit_capa_before_classification_rejected
# ---------------------------------------------------------------------------
def test_a_deviation_must_be_classified_before_any_capa_exists(api):
    """From OPEN only classify is declared, and a decision needs a submission.

    PRD 3.7: "Corrective action follows. A `QaReviewer` submits the remedy by supplying a non-empty `capa_summary`, moving the deviation `UNDER_INVESTIGATION → CAPA_PENDING`."

    PRD 3.7: "The decision supplies an `outcome` of `APPROVED` or `REJECTED` and a `decision_note`, and it is only accepted from `CAPA_PENDING`."

    Design: Corner/state_machines/deviation_submit_capa_before_classification_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    deviation = fixtures.raise_deviation(
        api,
        program["batch_id"],
        QA_REVIEWER,
        summary="Fill weight drift observed during line clearance.",
    )

    validate_error(
        api.submit_capa(
            deviation["id"],
            factories.submit_capa_payload(
                "Attempting to submit a CAPA before classification."
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.DEVIATION_STATE_INVALID,
        409,
    )
    validate_error(
        api.decide_capa(
            deviation["id"],
            factories.decide_capa_payload(
                outcome="APPROVED",
                decision_note="Attempting to decide a CAPA that does not exist.",
            ),
            QA_REVIEWER_SECOND,
        ),
        ApiErrorId.DEVIATION_STATE_INVALID,
        409,
    )
    still_open = fixtures.read_deviation(api, deviation["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["classification"] is None
    assert still_open["risk_score"] == 0
    assert still_open["capa_summary"] is None

    classified = fixtures.classify_deviation(
        api,
        deviation["id"],
        QA_REVIEWER,
        classification="MINOR",
        classification_rationale="No product impact; documentation only.",
    )
    assert classified["status"] == "UNDER_INVESTIGATION"
    assert classified["classification"] == "MINOR"
    assert classified["risk_score"] == constants.DEVIATION_BASE_POINTS["MINOR"]

    validate_error(
        api.decide_capa(
            deviation["id"],
            factories.decide_capa_payload(
                outcome="APPROVED", decision_note="Still no CAPA submitted."
            ),
            QA_REVIEWER_SECOND,
        ),
        ApiErrorId.DEVIATION_STATE_INVALID,
        409,
    )
    assert (
        fixtures.read_deviation(api, deviation["id"])["status"] == "UNDER_INVESTIGATION"
    )
    assert (
        fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"]
        == 5
    )


# ---------------------------------------------------------------------------
# Design instance: batch_record_review_close_with_open_findings_rejected
# ---------------------------------------------------------------------------
def test_a_review_closes_only_once_its_findings_are_driven_to_zero(api):
    """Two outstanding findings block the close; the self-loop clears them.

    PRD 3.8: "Closing the review is permitted from either `IN_PROGRESS` or `COMPLETE_WITH_FINDINGS`, requires `open_findings_count` to be exactly 0, and requires the owning batch to still be in `BR_REVIEW`; a close attempted with findings outstanding, or from a status that does not permit it, is refused with `ERR_BR_REVIEW_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/batch_record_review_close_with_open_findings_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_BR_REVIEW)
    review_id = program["review_id"]
    with_findings = fixtures.record_findings(
        api,
        review_id,
        2,
        findings_note="Two unsigned line-clearance entries.",
    )
    assert with_findings["status"] == "COMPLETE_WITH_FINDINGS"

    validate_error(
        api.close_batch_record_review(review_id, QA_REVIEWER),
        ApiErrorId.BR_REVIEW_STATE_INVALID,
        409,
    )
    blocked = fixtures.read_review(api, review_id, QA_REVIEWER)
    assert blocked["status"] == "COMPLETE_WITH_FINDINGS"
    assert blocked["open_findings_count"] == 2
    assert blocked["closed_at"] is None
    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "BR_REVIEW"
    assert batch["final_releasable_units"] is None

    cleared = fixtures.record_findings(
        api,
        review_id,
        0,
        findings_note="Both entries retrospectively signed and verified.",
    )
    assert cleared["status"] == "COMPLETE_WITH_FINDINGS"
    assert cleared["open_findings_count"] == 0

    closed = fixtures.close_review(api, review_id)
    assert closed["status"] == "CLOSED"
    assertions.assert_same_instant(
        closed["closed_at"], constants.SCENARIO_CLOCK, "closed_at"
    )
    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "QP_REVIEW"
    assert batch["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS


# ---------------------------------------------------------------------------
# Design instance: audit_engagement_hosted_is_terminal_and_second_host_rejected
# ---------------------------------------------------------------------------
def test_a_hosted_audit_cannot_be_hosted_or_deferred_again(api):
    """The inspection record written by the first hosting is not rewritable.

    PRD 3.9: "Hosting is permitted from `REQUESTED` and also from `DEFERRED` — a deferred engagement is re-hostable later, which is what makes the deferral loop worth having — but hosting an engagement whose `status` is already `HOSTED` is refused with `ERR_AUDIT_ENGAGEMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/audit_engagement_hosted_is_terminal_and_second_host_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    engagement = fixtures.request_audit(
        api,
        program["project_id"],
        audit_kind="CLIENT_AUDIT",
        requested_window_start="2026-10-05T09:00:00Z",
    )
    hosted = fixtures.host_audit(
        api, engagement["id"], outcome="HOSTED", finding_count=3
    )
    assert hosted["status"] == "HOSTED"

    for payload in (
        factories.host_audit_payload(outcome="HOSTED", finding_count=0),
        factories.host_audit_payload(outcome="DEFERRED", finding_count=0),
    ):
        validate_error(
            api.host_audit_engagement(engagement["id"], payload, PROGRAM_MANAGER),
            ApiErrorId.AUDIT_ENGAGEMENT_STATE_INVALID,
            409,
        )

    rows, meta = validate_paginated(
        api.list_project_audit_engagements(program["project_id"], PROGRAM_MANAGER)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "HOSTED"
    assert rows[0]["finding_count"] == 3
    assertions.assert_same_instant(
        rows[0]["hosted_at"], constants.SCENARIO_CLOCK, "hosted_at"
    )
    assert (
        fixtures.read_project(api, program["project_id"])[
            "last_client_audit_finding_count"
        ]
        == 3
    )


# ---------------------------------------------------------------------------
# Design instance: advance_tech_transfer_after_project_is_active_rejected
# ---------------------------------------------------------------------------
def test_an_active_project_neither_re_walks_transfer_nor_releases_a_hold(api):
    """Both calls need a status the project no longer has.

    PRD 3.1: "`to_stage` must be the immediate successor of the project's current `tech_transfer_stage` in the ordered progression `NOT_STARTED`, `GAP_ASSESSMENT`, `ENGINEERING_RUN`, `COMPLETE` — skipping a stage or naming the current stage again is refused with `ERR_PROJECT_STATE_INVALID` (HTTP 409), as is any advance attempted on a project whose `status` is no longer `INTAKE`."

    PRD 3.1: "That release requires the project to actually be in `ON_HOLD` — otherwise `ERR_PROJECT_STATE_INVALID` — and requires that no deviation written against any of the project's batches still carries a `classification` of `CRITICAL` with a `status` other than `CLOSED`; if one does, the release is refused with `ERR_OPEN_CRITICAL_DEVIATION` (HTTP 409)."

    Design: Corner/state_machines/advance_tech_transfer_after_project_is_active_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    project_id = program["project_id"]

    validate_error(
        api.advance_tech_transfer(
            project_id,
            factories.advance_tech_transfer_payload(
                to_stage="COMPLETE", analytical_method_transfer_status="VALIDATED"
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.PROJECT_STATE_INVALID,
        409,
    )
    validate_error(
        api.release_hold(
            project_id,
            factories.release_hold_payload(
                "Attempting to release a hold that was never placed."
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.PROJECT_STATE_INVALID,
        409,
    )

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "ACTIVE"
    assert project["tech_transfer_stage"] == "COMPLETE"
    assert project["analytical_method_transfer_status"] == "VALIDATED"


# ---------------------------------------------------------------------------
# Design instance:
#   clock_advance_lapses_qualifications_and_expires_lots_and_recomputes_posture
# ---------------------------------------------------------------------------
def test_one_clock_advance_lapses_expires_and_recomputes_in_a_single_act(api):
    """The move retires two qualifications and one lot and reports both counts.

    PRD 2.4: "An operator moves the clock by supplying a `to_iso8601` instant to the clock endpoint, which answers with the resulting `current_utc` together with `lapsed_qualification_count` and `expired_component_lot_count` — the number of operator qualifications and component lots the move retired."

    PRD 2.4: "Every component lot whose `status` is `RELEASED` or `EXHAUSTED` and whose `sterilization_expiry` is at or before the new clock value becomes `EXPIRED` with its `quantity_available` set to 0, processed in ascending `sterilization_expiry` order with ties broken by ascending `created_at`; reservations already held against such a lot are deliberately left untouched so that the component-unit ledger still balances against `quantity_received`."

    Design: Corner/state_machines/clock_advance_lapses_qualifications_and_expires_lots_and_recomputes_posture
    """
    world = fixtures.build_qualified_suite(api)
    project = fixtures.create_project(api, world["suite_id"])
    lot = fixtures.release_lot(
        api,
        project["id"],
        component_type="VIAL",
        lot_code="VL-1",
        sterilization_expiry="2027-01-01T00:00:00Z",
    )
    assert fixtures.read_suite(api, world["suite_id"])["posture"] == constants.POSTURE_OPEN

    moved = fixtures.set_clock(api, "2027-07-01T00:00:00Z")
    assertions.assert_same_instant(
        moved["current_utc"], "2027-07-01T00:00:00Z", "current_utc"
    )
    assert moved["lapsed_qualification_count"] == 2
    assert moved["expired_component_lot_count"] == 1

    for qualification_id in world["qualification_ids"]:
        assert fixtures.read_qualification(api, qualification_id)["status"] == "LAPSED"

    expired = fixtures.read_lot(api, lot["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["quantity_available"] == 0

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["posture"] == constants.POSTURE_RESTRICTED
    assert suite["aseptic_qualification_status"] == "QUALIFIED"
    assert suite["cleaning_validation_status"] == "VALIDATED"


# ---------------------------------------------------------------------------
# Design instance:
#   project_hold_release_restores_the_suspended_batch_and_the_two_ledgers
# ---------------------------------------------------------------------------
def test_releasing_the_hold_restores_the_batch_and_both_ledgers_but_not_quality(api):
    """Production returns to SCHEDULED while the quality axis stays quarantined.

    PRD 3.6: "The reverse edge, `SUSPENDED → SCHEDULED`, fires when the suite requalifies from `INVALIDATED` back to `QUALIFIED` or when a `QaReviewer` releases the project hold; it requires the suite's `posture` to be something other than `FROZEN` and the project's `status` to be `ACTIVE`, and it recomputes both ledgers again."

    PRD 3.6: "Restoration is deliberately asymmetric: `production_status` returns to `SCHEDULED`, but `quality_status` is *not* restored automatically and remains `QUARANTINED` until the deviation-closure path in section 3.7 moves it."

    Design: Corner/state_machines/project_hold_release_restores_the_suspended_batch_and_the_two_ledgers
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    deviation = fixtures.raise_deviation(
        api,
        program["batch_id"],
        QA_REVIEWER,
        summary="Grade B viable air excursion during setup.",
    )
    fixtures.classify_deviation(
        api,
        deviation["id"],
        QA_REVIEWER,
        classification="CRITICAL",
        classification_rationale="Potential sterility impact.",
    )
    fixtures.submit_capa(
        api,
        deviation["id"],
        QA_REVIEWER,
        capa_summary="HVAC balancing repeated and requalified.",
    )
    fixtures.decide_capa(
        api,
        deviation["id"],
        QA_REVIEWER_SECOND,
        outcome="APPROVED",
        decision_note="Effectiveness check accepted.",
    )

    assert fixtures.read_project(api, program["project_id"])["status"] == "ON_HOLD"
    held = fixtures.read_batch(api, program["batch_id"])
    assert held["production_status"] == "SUSPENDED"
    assert held["quality_status"] == "QUARANTINED"
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 0
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"] == 0
    )

    released = fixtures.release_hold(
        api,
        program["project_id"],
        QA_REVIEWER_SECOND,
        release_rationale="CRITICAL deviation closed with an approved CAPA.",
    )
    assert released["status"] == "ACTIVE"

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["production_status"] == "SCHEDULED"
    assert batch["quality_status"] == "QUARANTINED"

    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS
    assert project["open_deviation_risk_total"] == 0
    assert fixtures.read_deviation(api, deviation["id"])["status"] == "CLOSED"
