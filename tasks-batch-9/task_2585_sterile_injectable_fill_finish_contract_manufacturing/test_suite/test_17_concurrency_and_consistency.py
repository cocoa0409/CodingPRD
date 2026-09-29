"""The two optimistic-concurrency tokens, version counting, and immediacy.

Both guarded creates are legal twice over, so only a stale token may refuse
them, and the refusal must precede the business rules that would otherwise
answer. Versions count a row's own successful writes and nothing else. And
every derived figure — a sample's limits and risk index, a suite's posture — is
visible without a second write.
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
    PROGRAM_MANAGER,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: stale_expected_suite_version_on_a_second_batch_is_rejected
# ---------------------------------------------------------------------------
def test_a_second_batch_must_be_computed_from_a_fresh_view_of_the_suite(api):
    """The pre-B-001 token is refused at 412; the re-read makes it succeed.

    PRD 2.7: "A request to `POST /batch-orders` must carry `expected_suite_version` as a required, non-optional field holding the client's last observed `version` of the target `FillingSuite`. If it does not equal that suite's current `version`, the create is rejected with `ERR_STALE_SUITE_VERSION` (HTTP 412)."

    PRD 3.5: "Its project's `committed_demand_units` increases by the new `component_demand_units`, its suite's `committed_minutes` increases by the window length plus `changeover_minutes_applied`, and the suite's `version` is bumped — which is precisely why the next client to schedule into that suite must have read the suite again."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_suite_version_on_a_second_batch_is_rejected
    """
    # Two worked-example batches commit 2 x 21560 component units, so the project's
    # `reserved_unit_budget` must cover the pair or PRD 3.5's final ceiling
    # (`ERR_PROJECT_UNIT_BUDGET_EXCEEDED`) would legitimately refuse the second create.
    program = fixtures.build_program(
        api,
        stage=fixtures.STAGE_PROJECT,
        reserved_unit_budget=2 * constants.WORKED_COMPONENT_DEMAND_UNITS,
    )
    stale_version = fixtures.suite_version(api, program["suite_id"])
    fixtures.create_batch(
        api,
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
        stale_version,
    )
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540

    second_payload = factories.batch_order_payload(
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][1],
        stale_version,
        batch_number="B-002",
        planned_start="2026-09-11T08:00:00Z",
        planned_end="2026-09-11T14:00:00Z",
    )
    refusal = validate_error(
        api.create_batch_order(second_payload, PROGRAM_MANAGER),
        ApiErrorId.STALE_SUITE_VERSION,
        412,
    )
    assert refusal["error_id"] != ApiErrorId.SUITE_CHANGEOVER_CONFLICT
    assert refusal["error_id"] != ApiErrorId.SUITE_CAPACITY_EXCEEDED

    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    rows, meta = validate_paginated(
        api.list_batch_orders(
            PROGRAM_MANAGER, {"client_project_id": program["project_id"]}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1

    fresh_version = fixtures.suite_version(api, program["suite_id"])
    assert fresh_version == stale_version + 1

    second_payload["expected_suite_version"] = fresh_version
    second = validate_success(
        api.create_batch_order(second_payload, PROGRAM_MANAGER), 201
    )
    assert second["changeover_minutes_applied"] == 60

    suite_after = fixtures.read_suite(api, program["suite_id"])
    assert suite_after["committed_minutes"] == 960
    assert suite_after["version"] == fresh_version + 1
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"]
        == 2 * constants.WORKED_COMPONENT_DEMAND_UNITS
    )


# ---------------------------------------------------------------------------
# Design instance: stale_expected_component_lot_version_on_reservation_is_rejected
# ---------------------------------------------------------------------------
def test_the_sterilisation_release_itself_invalidates_the_clients_lot_token(api):
    """Version 1 was read before release, so reserving on it is a 412.

    PRD 2.7: "A request to `POST /component-reservations` must carry `expected_component_lot_version` as a required, non-optional field holding the client's last observed `version` of the target `ComponentLot`. If it does not equal that lot's current `version`, the create is rejected with `ERR_STALE_COMPONENT_LOT_VERSION` (HTTP 412), because the client's `quantity_reserved` was computed from a `quantity_available` that has since moved."

    PRD 2.10: "**Optimistic concurrency** — `ERR_STALE_SUITE_VERSION` on `POST /batch-orders`, then `ERR_STALE_COMPONENT_LOT_VERSION` on `POST /component-reservations`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_component_lot_version_on_reservation_is_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    batch = fixtures.create_batch(
        api,
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
    )
    lot = fixtures.create_lot(
        api, program["project_id"], component_type="VIAL", lot_code="VL-1"
    )
    quarantine_version = fixtures.lot_version(api, lot["id"])
    assert quarantine_version == 1
    assert lot["status"] == "QUARANTINE"
    assert lot["quantity_available"] == 0

    released = fixtures.validate_sterilization(api, lot["id"])
    assert released["version"] == 2
    assert released["quantity_available"] == 30000

    refusal = validate_error(
        api.create_component_reservation(
            factories.component_reservation_payload(
                batch["id"],
                lot["id"],
                constants.WORKED_VIAL_LINE_UNITS,
                quarantine_version,
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.STALE_COMPONENT_LOT_VERSION,
        412,
    )
    assert refusal["error_id"] != ApiErrorId.COMPONENT_STERILIZATION_INVALID
    assert refusal["error_id"] != ApiErrorId.COMPONENT_LOT_INSUFFICIENT

    held = fixtures.read_lot(api, lot["id"])
    assert held["quantity_available"] == 30000
    assert held["version"] == 2

    reservation = fixtures.reserve(
        api, batch["id"], lot["id"], constants.WORKED_VIAL_LINE_UNITS, 2
    )
    assert reservation["status"] == "RESERVED"
    assert reservation["quantity_reserved"] == constants.WORKED_VIAL_LINE_UNITS

    lot_after = fixtures.read_lot(api, lot["id"])
    assert lot_after["quantity_available"] == 19440
    assert lot_after["version"] == 3


# ---------------------------------------------------------------------------
# Design instance: entity_version_increments_once_per_successful_write
# ---------------------------------------------------------------------------
def test_each_row_counts_only_its_own_successful_writes(api):
    """A write issued through another entity's endpoint still versions the suite.

    PRD 2.4: "`version` begins at 1 when the row is created and increases by exactly 1 on every mutation of that row, and `updated_at` is refreshed to the same instant."

    PRD 3.2: "Either verdict recomputes the suite's `posture` and bumps the suite's `version`; a `FAILED` verdict necessarily drives that posture to `FROZEN`."

    Design: Corner/cross_cutting_complexity_layers/entity_version_increments_once_per_successful_write
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    assert suite["version"] == 1

    media_fill = fixtures.create_media_fill(api, suite["id"])
    fixtures.execute_media_fill(
        api,
        media_fill["id"],
        units_filled=6000,
        participating_operator_names=["OP-A", "OP-B"],
    )
    fixtures.read_media_fill_out(api, media_fill["id"], 0)
    assert fixtures.suite_version(api, suite["id"]) == 2

    fixtures.record_cleaning_validation(api, suite["id"], molecule_name="MOL-A")
    assert fixtures.suite_version(api, suite["id"]) == 3
    assert fixtures.suite_version(api, suite["id"]) == 3

    qualification = fixtures.create_qualification(
        api, "OP-A", suite["id"], media_fill_id=media_fill["id"]
    )
    assert qualification["version"] == 1
    granted = fixtures.qualify(api, qualification["id"])
    assert granted["version"] == 2

    project = fixtures.create_project(api, suite["id"])
    assert project["version"] == 1
    activated = fixtures.activate_project(api, project["id"])
    assert activated["version"] == 4

    before_scheduling = fixtures.suite_version(api, suite["id"])
    batch = fixtures.create_batch(
        api, project["id"], suite["id"], qualification["id"], before_scheduling
    )
    assert batch["version"] == 1
    assert fixtures.suite_version(api, suite["id"]) == before_scheduling + 1
    assert fixtures.suite_version(api, suite["id"]) == before_scheduling + 1


# ---------------------------------------------------------------------------
# Design instance: every_derived_field_is_visible_in_the_same_response
# ---------------------------------------------------------------------------
def test_the_creating_response_already_carries_every_derived_figure(api):
    """Twelve colonies score 48 in the same response that records them.

    PRD 3.7: "From these, the core term is the ratio multiplied by 20 and then by the grade weight, clamped so that it is never below 0 and never above 100, and then rounded half up to a whole number. The surcharges are added to that rounded core, and `risk_index` is the smaller of 150 and that sum."

    PRD 3.7: "A `WITHIN_LIMIT` sample is stamped with an `investigation_status` of `NOT_REQUIRED`, which is already terminal; an `ALERT` or `ACTION` sample is stamped `OPEN`."

    PRD 2.5: "`open_action_excursion_count` is the number of environmental monitoring samples in this suite whose `classification` is `ACTION` and whose `investigation_status` is either `OPEN` or `INVESTIGATING`; samples classified `ALERT` or `WITHIN_LIMIT` never restrict a suite, and neither does an `ACTION` sample whose investigation has reached `CLOSED`."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
    """
    world = fixtures.build_qualified_suite(api)
    assert fixtures.read_suite(api, world["suite_id"])["posture"] == constants.POSTURE_OPEN

    sample = validate_success(
        api.create_em_sample(
            factories.em_sample_payload(
                world["suite_id"], sample_type="VIABLE_AIR", cfu_count=12
            ),
            MICROBIOLOGY_ANALYST,
        ),
        201,
    )
    assert sample["alert_limit"] == 5
    assert sample["action_limit"] == 10
    assert sample["classification"] == "ACTION"
    assert sample["risk_index"] == 48
    assert sample["investigation_status"] == "OPEN"
    assertions.assert_em_sample_classification(sample, "B")

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["open_action_excursion_count"] == 1
    assert suite["posture"] == constants.POSTURE_RESTRICTED

    reread = fixtures.read_em_sample(api, sample["id"])
    assert reread["classification"] == sample["classification"]
    assert reread["risk_index"] == sample["risk_index"]
    assert reread["investigation_status"] == "OPEN"
