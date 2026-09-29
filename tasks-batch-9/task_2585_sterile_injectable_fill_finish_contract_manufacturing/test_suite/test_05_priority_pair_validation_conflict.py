"""Pairs of rules that a single request violates at once.

Each case is arranged so that two named refusals both apply, and only the one
the specification orders first may be reported.
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
)
from test_helpers.test_users import (
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QUALIFIED_PERSON,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance:
#   qp_release_terminal_quality_state_outranks_open_critical_deviation
# ---------------------------------------------------------------------------
def _released_batch_with_a_critical_deviation(api) -> Json:
    """A released batch that afterwards acquired an open CRITICAL deviation."""
    program = fixtures.build_program(api, stage=fixtures.STAGE_RELEASED)
    deviation = fixtures.raise_deviation(api, program["batch_id"], QA_REVIEWER)
    program["deviation"] = fixtures.classify_deviation(
        api, deviation["id"], QA_REVIEWER, classification="CRITICAL"
    )
    return program


def test_second_qp_release_reports_the_quality_state_not_the_open_critical_deviation(api):
    """The state gate is evaluated before the critical-deviation gate.

    PRD 3.8: "The batch's `quality_status` must be `QP_REVIEW`, or the request is refused with `ERR_BATCH_QUALITY_STATE_INVALID`; a batch that has been demoted back to `BR_REVIEW`, quarantined, or already dispositioned fails here even if its review is closed and clean."

    Design: Difficulty/priority_pair_validation_conflict/qp_release_terminal_quality_state_outranks_open_critical_deviation
    """
    program = _released_batch_with_a_critical_deviation(api)

    response = api.qp_release(
        program["batch_id"],
        factories.qp_release_payload(
            decision="REJECT", rationale="Reconsidering the disposition after the fact."
        ),
        QUALIFIED_PERSON,
    )
    error = validate_error(response, ApiErrorId.BATCH_QUALITY_STATE_INVALID, 409)
    assert error["error_id"] != ApiErrorId.OPEN_CRITICAL_DEVIATION
    assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES


def test_refused_second_release_leaves_the_first_disposition_and_its_fee_alone(api):
    """Exactly one immutable decision record survives, still carrying its fee.

    PRD 3.8: "A `RELEASE` sets the batch's `quality_status` to `RELEASED`, stamps `release_fee_cents` on the batch from the fee formula below, and appends a decision whose `released_unit_count` copies the batch's `final_releasable_units` and whose `fee_cents` copies `release_fee_cents`."

    Design: Difficulty/priority_pair_validation_conflict/qp_release_terminal_quality_state_outranks_open_critical_deviation
    """
    program = _released_batch_with_a_critical_deviation(api)
    api.qp_release(
        program["batch_id"],
        factories.qp_release_payload(decision="REJECT", rationale="Second thoughts."),
        QUALIFIED_PERSON,
    )

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "RELEASED"
    assert batch["release_fee_cents"] == constants.WORKED_FEE_SUBTOTAL_CENTS

    deviation = fixtures.read_deviation(api, program["deviation"]["id"])
    assert deviation["classification"] == "CRITICAL"
    assert deviation["status"] == "UNDER_INVESTIGATION"

    rows, _meta = validate_paginated(
        api.list_qp_release_decisions(program["batch_id"], QUALIFIED_PERSON)
    )
    assert len(rows) == 1
    assert rows[0]["decision"] == "RELEASE"
    assert rows[0]["released_unit_count"] == constants.WORKED_FINAL_RELEASABLE_UNITS
    assert rows[0]["fee_cents"] == constants.WORKED_FEE_SUBTOTAL_CENTS


# ---------------------------------------------------------------------------
# Design instance:
#   batch_scheduling_media_fill_lapse_outranks_project_unit_budget
# ---------------------------------------------------------------------------
def _project_with_one_batch_and_a_tight_budget(api) -> Json:
    """A single scheduled batch against a 25000-unit contractual ceiling."""
    return fixtures.build_program(
        api,
        stage=fixtures.STAGE_SCHEDULED,
        max_committed_minutes=20000,
        reserved_unit_budget=25000,
    )


def test_scheduling_reports_the_lapsed_simulation_before_the_unit_budget(api):
    """Suite fitness is judged before either contractual ceiling.

    PRD 3.5: "Both ceilings are checked last, after everything else has passed, and both answer with HTTP 402."

    Design: Difficulty/priority_pair_validation_conflict/batch_scheduling_media_fill_lapse_outranks_project_unit_budget
    """
    program = _project_with_one_batch_and_a_tight_budget(api)

    response = api.create_batch_order(
        factories.batch_order_payload(
            program["project_id"],
            program["suite_id"],
            program["lead_operator_qualification_id"],
            fixtures.suite_version(api, program["suite_id"]),
            batch_number="B-002",
            planned_start="2027-03-20T08:00:00Z",
            planned_end="2027-04-01T16:00:00Z",
            target_fill_units=10000,
        ),
        PROGRAM_MANAGER,
    )
    error = validate_error(response, ApiErrorId.MEDIA_FILL_QUALIFICATION_EXPIRED, 409)
    assert error["error_id"] != ApiErrorId.PROJECT_UNIT_BUDGET_EXCEEDED
    assert error["error_id"] != ApiErrorId.SUITE_CAPACITY_EXCEEDED


def test_refused_scheduling_leaves_both_ledgers_and_the_batch_list_untouched(api):
    """The rejected window commits nothing to the project or the suite.

    PRD 3.5: "The suite's aseptic qualification must cover the *whole* requested window, so `media_fill_valid_until` must be non-null and at or after the batch's `planned_end`; a suite with no valid simulation, or one whose validity lapses inside the window, is refused with `ERR_MEDIA_FILL_QUALIFICATION_EXPIRED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/batch_scheduling_media_fill_lapse_outranks_project_unit_budget
    """
    program = _project_with_one_batch_and_a_tight_budget(api)
    api.create_batch_order(
        factories.batch_order_payload(
            program["project_id"],
            program["suite_id"],
            program["lead_operator_qualification_id"],
            fixtures.suite_version(api, program["suite_id"]),
            batch_number="B-002",
            planned_start="2027-03-20T08:00:00Z",
            planned_end="2027-04-01T16:00:00Z",
        ),
        PROGRAM_MANAGER,
    )

    suite = fixtures.read_suite(api, program["suite_id"])
    assertions.assert_same_instant(
        suite["media_fill_valid_until"],
        constants.MEDIA_FILL_VALID_UNTIL,
        "media_fill_valid_until",
    )
    assert suite["committed_minutes"] == 540

    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS

    rows, _meta = validate_paginated(
        api.list_batch_orders(
            PROGRAM_MANAGER, {"client_project_id": program["project_id"]}
        )
    )
    assert len(rows) == 1
    assert rows[0]["batch_number"] == "B-001"
