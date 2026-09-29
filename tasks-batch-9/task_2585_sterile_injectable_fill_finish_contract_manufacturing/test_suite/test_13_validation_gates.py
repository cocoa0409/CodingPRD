"""The validation ladder of PRD 2.10 exercised one rung at a time.

Each test drives a single request into a single rule and proves both the typed
refusal and that the refusal left nothing behind: aggregate ceilings that only
a running total can breach, payload coherence that depends on another field,
uniqueness scoped to a component type, a project or the whole estate, the
gates in front of a batch record review and a Qualified-Person signature,
cross-entity sterility, cleaning and operator rules, and windows whose
endpoints must be strictly ordered.
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
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QA_REVIEWER_SECOND,
    QA_USER_ID,
    QUALIFIED_PERSON,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: suite_capacity_exceeded_only_in_aggregate_across_two_batches
# ---------------------------------------------------------------------------
def test_two_individually_small_windows_breach_the_cap_only_in_aggregate(api):
    """540 minutes is accepted, a second 540 drives the running total past 1000.

    PRD 3.5: "Then the suite's occupancy ceiling is tested by adding the requested window length in minutes and the newly derived `changeover_minutes_applied` to the suite's current `committed_minutes`: if that sum exceeds the suite's `max_committed_minutes`, the request is refused with `ERR_SUITE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/suite_capacity_exceeded_only_in_aggregate_across_two_batches
    """
    program = fixtures.build_program(
        api,
        stage=fixtures.STAGE_SCHEDULED,
        max_committed_minutes=1000,
        reserved_unit_budget=50000,
    )
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540

    validate_error(
        api.create_batch_order(
            factories.batch_order_payload(
                program["project_id"],
                program["suite_id"],
                program["qualification_ids"][1],
                fixtures.suite_version(api, program["suite_id"]),
                batch_number="B-002",
                planned_start="2026-09-10T18:00:00Z",
                planned_end="2026-09-11T02:00:00Z",
                target_fill_units=10000,
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.SUITE_CAPACITY_EXCEEDED,
        402,
    )

    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"]
        == constants.WORKED_COMPONENT_DEMAND_UNITS
    )
    rows, meta = validate_paginated(
        api.list_batch_orders(PROGRAM_MANAGER, {"suite_id": program["suite_id"]})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["batch_number"] == "B-001"


# ---------------------------------------------------------------------------
# Design instance: in_process_check_payload_consistency_depends_on_the_check_type
# ---------------------------------------------------------------------------
def test_measurement_array_coherence_is_decided_by_the_check_type(api):
    """Weights on a CCI row, none on a fill-weight row and an over-count all fail.

    PRD 3.6: "Payload coherence is strict: `measured_fill_weights_mg` must be present and non-empty when `check_type` is `FILL_WEIGHT` and must be empty for `CCI` and `VISUAL_INSPECTION`, and `reject_unit_count` must be at most `sample_size`; any violation is refused with `ERR_IPC_PAYLOAD_INCONSISTENT` (HTTP 422)."

    Design: Corner/validations/in_process_check_payload_consistency_depends_on_the_check_type
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    batch_id = program["batch_id"]

    validate_error(
        api.create_in_process_check(
            factories.cci_check_payload(
                batch_id, measured_fill_weights_mg=[1000, 1010]
            ),
            PRODUCTION_SUPERVISOR,
        ),
        ApiErrorId.IPC_PAYLOAD_INCONSISTENT,
        422,
    )
    validate_error(
        api.create_in_process_check(
            factories.fill_weight_check_payload(batch_id, measured_fill_weights_mg=[]),
            PRODUCTION_SUPERVISOR,
        ),
        ApiErrorId.IPC_PAYLOAD_INCONSISTENT,
        422,
    )
    validate_error(
        api.create_in_process_check(
            factories.visual_check_payload(
                batch_id, sample_size=100, reject_unit_count=101
            ),
            PRODUCTION_SUPERVISOR,
        ),
        ApiErrorId.IPC_PAYLOAD_INCONSISTENT,
        422,
    )

    accepted = validate_success(
        api.create_in_process_check(
            factories.cci_check_payload(batch_id), PRODUCTION_SUPERVISOR
        ),
        201,
    )
    assert accepted["result"] == "PASS"
    assert float(accepted["max_absolute_deviation_pct"]) == 0

    rows, meta = validate_paginated(
        api.list_in_process_checks(PRODUCTION_SUPERVISOR, {"batch_order_id": batch_id})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Design instance: component_sterility_hold_time_must_cover_the_whole_planned_fill_window
# ---------------------------------------------------------------------------
def test_a_lot_expiring_inside_the_window_is_a_sterility_refusal_not_a_state_one(api):
    """The lot is RELEASED and unexpired, yet cannot cover the planned fill.

    PRD 3.4: "Beyond that status arm, the lot's sterility must cover the whole planned fill: `sterilization_validation_status` must be `RELEASED`, `sterilization_expiry` must be strictly later than the logical clock, *and* `sterilization_expiry` must be at or after the owning batch's `planned_end`, since a sterilised component has to remain inside its hold time through the entire window it will be used in. A failure of any of those three yields `ERR_COMPONENT_STERILIZATION_INVALID` (HTTP 409)."

    Design: Corner/validations/component_sterility_hold_time_must_cover_the_whole_planned_fill_window
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    short_dated = fixtures.release_lot(
        api,
        program["project_id"],
        component_type="VIAL",
        lot_code="VL-S",
        quantity_received=30000,
        sterilization_expiry="2026-09-09T00:00:00Z",
    )
    assert short_dated["status"] == "RELEASED"

    error = validate_error(
        api.create_component_reservation(
            factories.component_reservation_payload(
                program["batch_id"],
                short_dated["id"],
                constants.WORKED_VIAL_LINE_UNITS,
                short_dated["version"],
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.COMPONENT_STERILIZATION_INVALID,
        409,
    )
    assert error["error_id"] != ApiErrorId.COMPONENT_LOT_STATE_INVALID

    lot = fixtures.read_lot(api, short_dated["id"])
    assert lot["status"] == "RELEASED"
    assert lot["quantity_available"] == 30000
    rows, meta = validate_paginated(
        api.list_component_reservations(
            PROGRAM_MANAGER, {"batch_order_id": program["batch_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: duplicate_lot_code_is_scoped_to_the_component_type
# ---------------------------------------------------------------------------
def test_a_lot_code_is_unique_per_component_type_and_not_per_project(api):
    """VL-1 cannot repeat as a vial for anyone, but is free as a stopper.

    PRD 3.4: "A `ProgramManager` receives a lot naming its owning `client_project_id`, its `component_type` — one of `VIAL`, `STOPPER`, `SYRINGE` or `PLUNGER` — and the vendor's `lot_code`, a string of 1 to 30 characters that must be unique within that `component_type`; a collision is refused with `ERR_DUPLICATE_LOT_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_lot_code_is_scoped_to_the_component_type
    """
    world = fixtures.build_qualified_suite(api)
    sponsor_a = fixtures.create_project(api, world["suite_id"])
    sponsor_b = fixtures.create_project(
        api,
        world["suite_id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        target_fill_weight_mg=800,
        historical_reject_rate_ppm=1500,
    )
    fixtures.create_lot(
        api, sponsor_a["id"], component_type="VIAL", lot_code="VL-1", quantity_received=30000
    )

    for project_id in (sponsor_a["id"], sponsor_b["id"]):
        validate_error(
            api.create_component_lot(
                factories.component_lot_payload(
                    project_id,
                    component_type="VIAL",
                    lot_code="VL-1",
                    quantity_received=5000,
                    sterilization_expiry="2027-02-01T00:00:00Z",
                ),
                PROGRAM_MANAGER,
            ),
            ApiErrorId.DUPLICATE_LOT_CODE,
            409,
        )

    stopper = validate_success(
        api.create_component_lot(
            factories.component_lot_payload(
                sponsor_a["id"],
                component_type="STOPPER",
                lot_code="VL-1",
                quantity_received=12000,
                sterilization_expiry="2027-02-01T00:00:00Z",
            ),
            PROGRAM_MANAGER,
        ),
        201,
    )
    assert stopper["component_type"] == "STOPPER"
    assert stopper["lot_code"] == "VL-1"

    rows, meta = validate_paginated(
        api.list_component_lots(PROGRAM_MANAGER, {"component_type": "VIAL"})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Design instance: duplicate_suite_code_rejected_across_all_suites
# ---------------------------------------------------------------------------
def test_a_suite_code_is_unique_across_the_whole_estate(api):
    """Re-registering FS-1 with different parameters changes nothing.

    PRD 3.2: "A shared filling suite is registered by a `ProgramManager` with a `suite_code` of 1 to 20 characters that must be unique across every suite — a collision is refused with `ERR_DUPLICATE_SUITE_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_suite_code_rejected_across_all_suites
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    first = fixtures.create_suite(api)

    validate_error(
        api.create_filling_suite(
            factories.filling_suite_payload(
                suite_code="FS-1",
                grade="C",
                changeover_minutes_same_product=30,
                changeover_minutes_product_change=90,
                max_committed_minutes=5000,
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.DUPLICATE_SUITE_CODE,
        409,
    )
    untouched = fixtures.read_suite(api, first["id"])
    assert untouched["grade"] == "B"
    assert untouched["max_committed_minutes"] == 20000

    second = validate_success(
        api.create_filling_suite(
            factories.filling_suite_payload(
                suite_code="FS-2",
                grade="C",
                changeover_minutes_same_product=30,
                changeover_minutes_product_change=90,
                max_committed_minutes=5000,
            ),
            PROGRAM_MANAGER,
        ),
        201,
    )
    assert second["suite_code"] == "FS-2"

    rows, meta = validate_paginated(api.list_filling_suites(PROGRAM_MANAGER))
    assert len(rows) == 2
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Design instance: duplicate_batch_number_is_scoped_to_the_client_project
# ---------------------------------------------------------------------------
def test_a_batch_number_is_unique_within_its_project_only(api):
    """A second B-001 for the same sponsor is refused; Sponsor B may reuse it.

    PRD 3.5: "The `batch_number` must be unused by any non-`CANCELLED` batch of the same project, or the request is refused with `ERR_DUPLICATE_BATCH_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_batch_number_is_scoped_to_the_client_project
    """
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SCHEDULED, reserved_unit_budget=50000
    )

    error = validate_error(
        api.create_batch_order(
            factories.batch_order_payload(
                program["project_id"],
                program["suite_id"],
                program["qualification_ids"][0],
                fixtures.suite_version(api, program["suite_id"]),
                batch_number="B-001",
                planned_start="2026-09-20T08:00:00Z",
                planned_end="2026-09-20T16:00:00Z",
                target_fill_units=10000,
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.DUPLICATE_BATCH_NUMBER,
        409,
    )
    assert error["error_id"] != ApiErrorId.SUITE_CHANGEOVER_CONFLICT
    assert error["error_id"] != ApiErrorId.PROJECT_UNIT_BUDGET_EXCEEDED

    sponsor_b = fixtures.create_project(
        api,
        program["suite_id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        target_fill_weight_mg=800,
        historical_reject_rate_ppm=1500,
        reserved_unit_budget=50000,
    )
    fixtures.activate_project(api, sponsor_b["id"])
    accepted = fixtures.create_batch(
        api,
        sponsor_b["id"],
        program["suite_id"],
        program["qualification_ids"][1],
        batch_number="B-001",
        planned_start="2026-09-25T08:00:00Z",
        planned_end="2026-09-25T16:00:00Z",
        target_fill_units=10000,
    )
    assert accepted["batch_number"] == "B-001"
    assert accepted["client_project_id"] == sponsor_b["id"]

    rows, meta = validate_paginated(
        api.list_batch_orders(
            PROGRAM_MANAGER, {"client_project_id": program["project_id"]}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Design instance: required_in_process_checks_gate_the_batch_record_review
# ---------------------------------------------------------------------------
def test_completeness_is_checked_before_uniqueness_when_opening_a_review(api):
    """Two of three kinds is a 422; a second review of a complete batch is a 409.

    PRD 3.7: "The batch must carry at least one in-process control of *each* of the three required kinds — `FILL_WEIGHT`, `CCI` and `VISUAL_INSPECTION` — and a batch missing any one of them is refused with `ERR_REQUIRED_IPC_MISSING` (HTTP 422)."

    PRD 3.7: "And at most one review row may ever exist per batch, so a second attempt is refused with `ERR_BR_REVIEW_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/validations/required_in_process_checks_gate_the_batch_record_review
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)
    batch_id = program["batch_id"]
    fixtures.record_fill_weight_check(api, batch_id)
    fixtures.record_cci_check(api, batch_id)
    fixtures.complete_fill(api, batch_id, constants.WORKED_FILLED_UNIT_COUNT)

    validate_error(
        api.create_batch_record_review(
            factories.batch_record_review_payload(batch_id), QA_REVIEWER
        ),
        ApiErrorId.REQUIRED_IPC_MISSING,
        422,
    )
    assert fixtures.read_batch(api, batch_id)["quality_status"] == "IN_PROCESS_REVIEW"

    fixtures.record_visual_check(
        api,
        batch_id,
        QA_REVIEWER,
        sample_size=constants.WORKED_FILLED_UNIT_COUNT,
        reject_unit_count=constants.WORKED_ACTUAL_VISUAL_REJECT_UNITS,
    )
    review = validate_success(
        api.create_batch_record_review(
            factories.batch_record_review_payload(batch_id), QA_REVIEWER
        ),
        201,
    )
    assert review["status"] == "IN_PROGRESS"
    assert review["reviewer_user_id"] == QA_USER_ID
    assert fixtures.read_batch(api, batch_id)["quality_status"] == "BR_REVIEW"

    # PRD 3.7 names `ERR_BR_REVIEW_ALREADY_EXISTS` for the second attempt, but the
    # same section also advances the batch `IN_PROCESS_REVIEW -> BR_REVIEW` when the
    # first review opens, and PRD 2.10 orders the state-machine guards (rung 12)
    # ahead of the uniqueness rung (16). Both readings are PRD-faithful.
    second = api.create_batch_record_review(
        factories.batch_record_review_payload(batch_id), QA_REVIEWER_SECOND
    )
    assert second.status_code == 409
    validate_error_is_one_of(
        second,
        [ApiErrorId.BR_REVIEW_ALREADY_EXISTS, ApiErrorId.BATCH_QUALITY_STATE_INVALID],
    )
    rows, meta = validate_paginated(
        api.list_batch_record_reviews(QA_REVIEWER, {"batch_order_id": batch_id})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Design instance: failed_in_process_check_blocks_the_batch_record_review
# ---------------------------------------------------------------------------
def test_a_failed_fill_weight_control_blocks_the_review_on_its_own_code(api):
    """A 6 percent deviation fails the control and the review never opens.

    PRD 3.7: "No in-process control of the batch may carry a `result` of `FAIL`; one that does is refused with `ERR_IPC_FAILED` (HTTP 409), and note that an `ALERT` result does not block the review."

    Design: Corner/validations/failed_in_process_check_blocks_the_batch_record_review
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)
    batch_id = program["batch_id"]

    failed = fixtures.record_fill_weight_check(
        api, batch_id, measured_fill_weights_mg=[1000, 1060]
    )
    assert failed["result"] == "FAIL"
    assert float(failed["max_absolute_deviation_pct"]) == 0.06

    fixtures.record_cci_check(api, batch_id)
    fixtures.record_visual_check(
        api,
        batch_id,
        sample_size=constants.WORKED_FILLED_UNIT_COUNT,
        reject_unit_count=constants.WORKED_ACTUAL_VISUAL_REJECT_UNITS,
    )
    fixtures.complete_fill(api, batch_id, constants.WORKED_FILLED_UNIT_COUNT)

    error = validate_error(
        api.create_batch_record_review(
            factories.batch_record_review_payload(batch_id), QA_REVIEWER
        ),
        ApiErrorId.IPC_FAILED,
        409,
    )
    assert error["error_id"] != ApiErrorId.REQUIRED_IPC_MISSING

    assert fixtures.read_batch(api, batch_id)["quality_status"] == "IN_PROCESS_REVIEW"
    rows, meta = validate_paginated(
        api.list_batch_record_reviews(QA_REVIEWER, {"batch_order_id": batch_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: start_fill_requires_full_component_coverage_and_sufficient_lots
# ---------------------------------------------------------------------------
def test_the_fill_waits_for_every_component_unit_the_batch_demands(api):
    """One line reserved is not coverage, and no lot lends more than it holds.

    PRD 3.4: "And the lot must actually have the units: `quantity_reserved` must be at most the lot's current `quantity_available`, or the create is refused with `ERR_COMPONENT_LOT_INSUFFICIENT` (HTTP 409)."

    PRD 3.6: "And the components must actually be in the room: the sum of `quantity_reserved` over the batch's reservations whose `status` is `RESERVED` must be at least the batch's `component_demand_units`, or the attempt is refused with `ERR_COMPONENTS_NOT_RESERVED` (HTTP 409)."

    Design: Corner/validations/start_fill_requires_full_component_coverage_and_sufficient_lots
    """
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SCHEDULED, lot_quantities={"STOPPER": 12000}
    )
    batch_id = program["batch_id"]
    stopper_id = program["lot_ids"]["STOPPER"]
    fixtures.reserve(
        api, batch_id, program["lot_ids"]["VIAL"], constants.WORKED_VIAL_LINE_UNITS
    )
    fixtures.setup_batch(api, batch_id)

    validate_error(
        api.create_component_reservation(
            factories.component_reservation_payload(
                batch_id, stopper_id, 12001, fixtures.lot_version(api, stopper_id)
            ),
            PRODUCTION_SUPERVISOR,
        ),
        ApiErrorId.COMPONENT_LOT_INSUFFICIENT,
        409,
    )
    assert fixtures.read_lot(api, stopper_id)["quantity_available"] == 12000

    validate_error(
        api.start_fill(batch_id, PRODUCTION_SUPERVISOR),
        ApiErrorId.COMPONENTS_NOT_RESERVED,
        409,
    )
    assert fixtures.read_batch(api, batch_id)["production_status"] == "SETUP"

    fixtures.reserve(
        api,
        batch_id,
        stopper_id,
        constants.WORKED_STOPPER_LINE_UNITS,
        headers=PRODUCTION_SUPERVISOR,
    )
    assert fixtures.read_lot(api, stopper_id)["quantity_available"] == 1000

    filling = fixtures.start_fill(api, batch_id)
    assert filling["production_status"] == "FILLING"
    assert filling["quality_status"] == "IN_PROCESS_REVIEW"


# ---------------------------------------------------------------------------
# Design instance: cleaning_validation_molecule_mismatch_blocks_start_fill
# ---------------------------------------------------------------------------
def test_a_suite_cleaned_for_another_molecule_may_not_start_this_fill(api):
    """The suite is validated and OPEN, but it was cleaned down for MOL-X.

    PRD 3.6: "The suite's cross-contamination state must match the product: `cleaning_validation_status` must be `VALIDATED` *and* `last_cleaned_molecule` must equal the owning project's `molecule_name`, or the attempt is refused with `ERR_CLEANING_VALIDATION_REQUIRED` (HTTP 409) — cleaning down for a different molecule than the one about to be filled is exactly the failure this rule exists to prevent."

    Design: Corner/validations/cleaning_validation_molecule_mismatch_blocks_start_fill
    """
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SETUP, cleaning_molecule="MOL-X"
    )

    validate_error(
        api.start_fill(program["batch_id"], PRODUCTION_SUPERVISOR),
        ApiErrorId.CLEANING_VALIDATION_REQUIRED,
        409,
    )

    suite = fixtures.read_suite(api, program["suite_id"])
    assert suite["cleaning_validation_status"] == "VALIDATED"
    assert suite["last_cleaned_molecule"] == "MOL-X"
    assert suite["posture"] == constants.POSTURE_OPEN

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["production_status"] == "SETUP"
    assert batch["quality_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Design instance: lead_operator_must_be_qualified_at_scheduling
# ---------------------------------------------------------------------------
def test_a_pending_lead_operator_record_cannot_carry_a_batch(api):
    """The row exists and expires far away, but it was never granted.

    PRD 3.5: "And the nominated lead operator must be genuinely effective: the qualification named by `lead_operator_qualification_id` must be an `ASEPTIC_INTERVENTION` qualification for this very suite — its `suite_id` equal to the batch's `suite_id` — with `status` of `QUALIFIED` and `expires_on` at or after the logical clock. Otherwise the request is refused with `ERR_OPERATOR_NOT_QUALIFIED` (HTTP 409)."

    Design: Corner/validations/lead_operator_must_be_qualified_at_scheduling
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    ungranted = fixtures.create_qualification(
        api, "OP-C", program["suite_id"], media_fill_id=program["media_fill_id"]
    )
    assert ungranted["status"] == "PENDING"

    validate_error(
        api.create_batch_order(
            factories.batch_order_payload(
                program["project_id"],
                program["suite_id"],
                ungranted["id"],
                fixtures.suite_version(api, program["suite_id"]),
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.OPERATOR_NOT_QUALIFIED,
        409,
    )
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 0
    rows, meta = validate_paginated(api.list_batch_orders(PROGRAM_MANAGER))
    assert rows == []
    assert meta["total_count"] == 0

    accepted = fixtures.create_batch(
        api,
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
    )
    assert accepted["lead_operator_qualification_id"] == program["qualification_ids"][0]
    assert fixtures.read_qualification(api, ungranted["id"])["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Design instance: window_endpoints_must_be_strictly_ordered_and_in_the_future
# ---------------------------------------------------------------------------
def test_equality_is_never_a_valid_window_anywhere_the_rule_applies(api):
    """A zero-length fill window, a same-instant expiry and a same-instant audit.

    PRD 3.5: "The window is half-open: `planned_start` is inclusive, `planned_end` is exclusive, and `planned_end` must be strictly after `planned_start` or the request is refused with `ERR_INVALID_WINDOW` (HTTP 422)."

    PRD 3.3: "The record declares `expires_on`, the instant at or after which the competence is no longer effective, and that instant must be strictly later than the logical clock at the moment of creation — an `expires_on` at or before the clock is refused with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/window_endpoints_must_be_strictly_ordered_and_in_the_future
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)

    validate_error(
        api.create_batch_order(
            factories.batch_order_payload(
                program["project_id"],
                program["suite_id"],
                program["qualification_ids"][0],
                fixtures.suite_version(api, program["suite_id"]),
                planned_start="2026-09-10T08:00:00Z",
                planned_end="2026-09-10T08:00:00Z",
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.INVALID_WINDOW,
        422,
    )
    validate_error(
        api.create_qualification(
            factories.qualification_payload(
                "OP-D",
                program["suite_id"],
                qualification_type="GOWNING",
                expires_on=constants.SCENARIO_CLOCK,
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.INVALID_WINDOW,
        422,
    )
    validate_error(
        api.create_audit_engagement(
            factories.audit_engagement_payload(
                program["project_id"],
                audit_kind="INSPECTION_READINESS",
                requested_window_start=constants.SCENARIO_CLOCK,
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.INVALID_WINDOW,
        422,
    )

    batches, _meta = validate_paginated(
        api.list_batch_orders(
            PROGRAM_MANAGER, {"client_project_id": program["project_id"]}
        )
    )
    assert batches == []
    operators, _meta = validate_paginated(
        api.list_qualifications(MICROBIOLOGY_ANALYST, {"operator_name": "OP-D"})
    )
    assert operators == []
    engagements, _meta = validate_paginated(
        api.list_project_audit_engagements(program["project_id"], PROGRAM_MANAGER)
    )
    assert engagements == []


# ---------------------------------------------------------------------------
# Design instance: qp_release_requires_a_closed_and_clean_batch_record_review
# ---------------------------------------------------------------------------
def test_the_review_closure_check_is_ordered_ahead_of_the_quality_axis_check(api):
    """Two open findings answer with the review code, not the state code.

    PRD 3.8: "The batch must have a batch record review, that review's `status` must be `CLOSED` and its `open_findings_count` must be 0, or the request is refused with `ERR_BR_REVIEW_NOT_CLOSED` (HTTP 409) — and this check is evaluated *before* the state check, so a Qualified Person signing against an unreviewed batch learns that fact rather than merely being told the state machine disagrees."

    Design: Corner/validations/qp_release_requires_a_closed_and_clean_batch_record_review
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_BR_REVIEW)
    review = fixtures.record_findings(
        api,
        program["review_id"],
        2,
        QA_REVIEWER,
        findings_note="Two unsigned line-clearance entries.",
    )
    assert review["status"] == "COMPLETE_WITH_FINDINGS"
    assert fixtures.read_batch(api, program["batch_id"])["quality_status"] == "BR_REVIEW"

    error = validate_error(
        api.qp_release(
            program["batch_id"],
            factories.qp_release_payload(
                decision="RELEASE",
                rationale="Attempting release before the batch record is closed.",
            ),
            QUALIFIED_PERSON,
        ),
        ApiErrorId.BR_REVIEW_NOT_CLOSED,
        409,
    )
    assert error["error_id"] != ApiErrorId.BATCH_QUALITY_STATE_INVALID

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "BR_REVIEW"
    assert batch["final_releasable_units"] is None
    rows, meta = validate_paginated(
        api.list_qp_release_decisions(program["batch_id"], QUALIFIED_PERSON)
    )
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: em_sample_batch_reference_must_belong_to_the_sampled_suite
# ---------------------------------------------------------------------------
def test_a_sample_may_only_cite_a_batch_running_in_the_sampled_suite(api):
    """FS-2 cannot claim FS-1's batch; FS-1 records the same reading at 42.

    PRD 3.7: "A sample taken while a batch was in progress may name that batch through `batch_order_id`, and when it does, that batch's `suite_id` must equal the sample's own `suite_id`, or the record is refused with `ERR_EM_SAMPLE_SUITE_MISMATCH` (HTTP 409)."

    Design: Corner/validations/em_sample_batch_reference_must_belong_to_the_sampled_suite
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    other_suite = fixtures.create_suite(api, suite_code="FS-2")

    validate_error(
        api.create_em_sample(
            factories.em_sample_payload(
                other_suite["id"],
                sample_type="SURFACE",
                cfu_count=4,
                batch_order_id=program["batch_id"],
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.EM_SAMPLE_SUITE_MISMATCH,
        409,
    )

    accepted = fixtures.record_em_sample(
        api,
        program["suite_id"],
        sample_type="SURFACE",
        cfu_count=4,
        batch_order_id=program["batch_id"],
    )
    assert accepted["alert_limit"] == 3
    assert accepted["action_limit"] == 5
    assert accepted["classification"] == "ALERT"
    assert accepted["risk_index"] == 42
    assertions.assert_em_sample_classification(accepted, "B", batch_was_filling=False)

    rows, meta = validate_paginated(
        api.list_em_samples(MICROBIOLOGY_ANALYST, {"suite_id": other_suite["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
