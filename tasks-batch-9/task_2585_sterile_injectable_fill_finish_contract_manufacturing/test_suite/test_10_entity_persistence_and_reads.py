"""Persistence, defaults and read contracts for the fifteen resource types.

Every test here proves what a freshly written row looks like, what a read of it
returns, or what the server refuses to write at all: the system defaults and zero
ledgers of PRD 3.1, 3.2 and 3.4, the envelope and pagination shapes of PRD 2.2
and 2.3, the append-only Qualified-Person record of PRD 2.4, and the shape,
enum, foreign-key and coherence refusals of PRD 2.10, 2.11 and 3.4.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QP_USER_ID,
    QUALIFIED_PERSON,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: client_project_creation_stamps_system_defaults_and_zero_ledgers
# ---------------------------------------------------------------------------
def test_client_project_intake_stamps_system_defaults_and_zero_ledgers(api):
    """A freshly intaken sponsor carries the pinned defaults and three zero ledgers.

    PRD 3.1: "A freshly intaken project starts with `status` set to `INTAKE`, `tech_transfer_stage` set to `NOT_STARTED`, `analytical_method_transfer_status` set to `NOT_STARTED`, and all three derived ledgers — `committed_demand_units`, `open_deviation_risk_total` and `last_client_audit_finding_count` — at 0."

    Design: Corner/entities/client_project_creation_stamps_system_defaults_and_zero_ledgers
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)

    project = validate_success(
        api.create_client_project(
            factories.client_project_payload(suite["id"]), PROGRAM_MANAGER
        ),
        201,
    )

    assert project["status"] == "INTAKE"
    assert project["tech_transfer_stage"] == "NOT_STARTED"
    assert project["analytical_method_transfer_status"] == "NOT_STARTED"
    assert project["committed_demand_units"] == 0
    assert project["open_deviation_risk_total"] == 0
    assert project["last_client_audit_finding_count"] == 0
    assert project["version"] == 1
    assert project["client_name"] == "Sponsor A"
    assert project["molecule_name"] == "MOL-A"
    assert project["dosage_form"] == "VIAL"
    assert project["primary_suite_id"] == suite["id"]
    assert project["target_fill_weight_mg"] == 1000
    assert project["historical_reject_rate_ppm"] == 2500
    assert project["reserved_unit_budget"] == 30000
    assertions.assert_client_project(project, expected_version=1)


# ---------------------------------------------------------------------------
# Design instance: client_project_get_returns_success_envelope_with_meta_and_object_data
# ---------------------------------------------------------------------------
def test_client_project_read_returns_the_object_success_envelope(api):
    """The read answers with meta, an object response type and the project itself.

    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/client_project_get_returns_success_envelope_with_meta_and_object_data
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    created = fixtures.create_project(api, suite["id"])

    response = api.get_client_project(created["id"], QA_REVIEWER)
    assert response.status_code == 200
    body = response.json()

    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str)
    assert request_id != ""
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"

    data = body["data"]
    assert data["id"] == created["id"]
    assert is_valid_uuid(data["id"])
    assert data["client_name"] == "Sponsor A"
    assert data["molecule_name"] == "MOL-A"


# ---------------------------------------------------------------------------
# Design instance: component_lot_creation_defaults_to_quarantine_with_zero_available
# ---------------------------------------------------------------------------
def test_received_lot_starts_in_quarantine_and_opens_only_on_release(api):
    """Nothing is drawable until the dossier clears, and then the whole receipt is.

    PRD 3.4: "A received lot begins with `status` of `QUARANTINE`, `sterilization_validation_status` of `PENDING`, and `quantity_available` of 0 — nothing may be drawn from a lot that has not yet cleared its dossier."

    Design: Corner/entities/component_lot_creation_defaults_to_quarantine_with_zero_available
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])

    lot = validate_success(
        api.create_component_lot(
            factories.component_lot_payload(project["id"]), PROGRAM_MANAGER
        ),
        201,
    )
    assert lot["status"] == "QUARANTINE"
    assert lot["sterilization_validation_status"] == "PENDING"
    assert lot["quantity_available"] == 0
    assert lot["quantity_received"] == 30000
    assert lot["version"] == 1
    assertions.assert_component_lot(lot, expected_version=1)

    released = validate_success(
        api.record_sterilization_validation(
            lot["id"],
            factories.sterilization_validation_payload(outcome="RELEASED", f0_minutes=15),
            MICROBIOLOGY_ANALYST,
        ),
        200,
    )
    assert released["status"] == "RELEASED"
    assert released["sterilization_validation_status"] == "RELEASED"
    assert released["quantity_available"] == 30000
    assert released["quantity_received"] == 30000
    assert released["version"] == 2


# ---------------------------------------------------------------------------
# Design instance: batch_order_missing_required_target_fill_units_rejected
# ---------------------------------------------------------------------------
def test_batch_order_without_target_fill_units_is_refused_as_ill_shaped(api):
    """An absent required field is a shape failure, and nothing is committed.

    PRD 2.10: "**Request shape** — `ERR_INVALID_REQUEST`, on every POST: a required field absent or null, a field of the wrong JSON type, an array field that is not an array, or a numeric field outside its declared range."

    Design: Corner/entities/batch_order_missing_required_target_fill_units_rejected
    """
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_PROJECT, reserved_unit_budget=50000
    )
    payload = factories.batch_order_payload(
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
        fixtures.suite_version(api, program["suite_id"]),
    )
    del payload["target_fill_units"]

    validate_error(
        api.create_batch_order(payload, PROGRAM_MANAGER),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(api.list_batch_orders(PROGRAM_MANAGER))
    assert rows == []
    assert meta["total_count"] == 0
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 0
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"] == 0
    )


# ---------------------------------------------------------------------------
# Design instance: component_lot_invalid_component_type_enum_rejected
# ---------------------------------------------------------------------------
def test_component_lot_with_an_undeclared_component_type_is_refused(api):
    """`AMPOULE` is not one of the four lines, so enum membership rejects it.

    PRD 2.10: "**Enum membership** — `ERR_INVALID_ENUM_VALUE`, on every POST carrying an enum-typed input and additionally on the two computed reads `GET /client-projects/{id}/readiness-assessment` and `GET /batch-orders/{id}/unit-accounting`."

    Design: Corner/entities/component_lot_invalid_component_type_enum_rejected
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])

    validate_error(
        api.create_component_lot(
            factories.component_lot_payload(project["id"], component_type="AMPOULE"),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
        422,
    )

    rows, meta = validate_paginated(api.list_component_lots(PROGRAM_MANAGER))
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: em_sample_grade_c_computed_limits_and_alert_classification_stamped
# ---------------------------------------------------------------------------
def test_grade_c_air_sample_stamps_the_grade_c_limits_and_an_alert(api):
    """Sixty colonies in a grade C room are an alert, not an action.

    PRD 3.7: "In grade `C`, viable air carries 50 and 100, surfaces carry 15 and 25, and personnel gloves carry 5 and 10."

    Design: Corner/entities/em_sample_grade_c_computed_limits_and_alert_classification_stamped
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(
        api,
        suite_code="FS-C",
        grade="C",
        changeover_minutes_same_product=30,
        changeover_minutes_product_change=120,
        max_committed_minutes=20000,
    )

    sample = validate_success(
        api.create_em_sample(
            factories.em_sample_payload(
                suite["id"], sample_type="VIABLE_AIR", cfu_count=60
            ),
            MICROBIOLOGY_ANALYST,
        ),
        201,
    )
    assert sample["alert_limit"] == 50
    assert sample["action_limit"] == 100
    assert sample["classification"] == "ALERT"
    assert sample["risk_index"] == 12
    assert sample["investigation_status"] == "OPEN"
    assert sample["root_cause"] is None
    assert sample["batch_order_id"] is None
    assertions.assert_em_sample_classification(sample, "C")

    assert fixtures.read_suite(api, suite["id"])["open_action_excursion_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: batch_order_get_with_unknown_id_returns_not_found
# ---------------------------------------------------------------------------
def test_reading_an_unknown_batch_order_is_a_typed_not_found(api):
    """A path id that resolves to nothing yields the batch-order 404, not a generic one.

    PRD 2.11: "Each resource type has its own not-found code: `ERR_CLIENT_PROJECT_NOT_FOUND`, `ERR_FILLING_SUITE_NOT_FOUND`, `ERR_MEDIA_FILL_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_BATCH_ORDER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_IN_PROCESS_CHECK_NOT_FOUND`, `ERR_EM_SAMPLE_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_BR_REVIEW_NOT_FOUND` and `ERR_AUDIT_ENGAGEMENT_NOT_FOUND`, all at HTTP 404."

    Design: Corner/entities/batch_order_get_with_unknown_id_returns_not_found
    """
    response = api.get_batch_order(NON_EXISTENT_UUID, PROGRAM_MANAGER)

    validate_error(response, ApiErrorId.BATCH_ORDER_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


# ---------------------------------------------------------------------------
# Design instance: component_lot_list_pagination_reports_total_count_and_has_more
# ---------------------------------------------------------------------------
def _three_lots(api) -> Json:
    """Two vial lots and one stopper lot, booked in that order."""
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])
    fixtures.create_lot(api, project["id"], component_type="VIAL", lot_code="VL-1")
    fixtures.create_lot(api, project["id"], component_type="STOPPER", lot_code="ST-1")
    fixtures.create_lot(
        api,
        project["id"],
        component_type="VIAL",
        lot_code="VL-2",
        quantity_received=15000,
    )
    return {"project_id": project["id"], "suite_id": suite["id"]}


def test_component_lot_list_windows_the_rows_and_counts_the_whole_match(api):
    """`total_count` counts every match while the window returns only its slice.

    PRD 2.3: "List responses set `response_type` to `"array"` and populate four pagination fields in `meta`: `limit` and `offset` echo the effective values, `total_count` reports the number of rows matching the filters before the window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/component_lot_list_pagination_reports_total_count_and_has_more
    """
    _three_lots(api)

    rows, meta = validate_paginated(
        api.list_component_lots(PROGRAM_MANAGER, {"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assertions.assert_created_at_ascending(rows)

    rows, meta = validate_paginated(
        api.list_component_lots(PROGRAM_MANAGER, {"limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["offset"] == 2

    rows, meta = validate_paginated(
        api.list_component_lots(PROGRAM_MANAGER, {"component_type": "VIAL"})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == constants.DEFAULT_LIMIT
    assert {row["lot_code"] for row in rows} == {"VL-1", "VL-2"}


# ---------------------------------------------------------------------------
# Design instance: component_lot_list_rejects_out_of_range_limit
# ---------------------------------------------------------------------------
def test_component_lot_list_rejects_limits_outside_one_to_one_hundred(api):
    """Zero, 101 and a negative offset are refused; exactly 100 is accepted.

    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/component_lot_list_rejects_out_of_range_limit
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])
    fixtures.create_lot(api, project["id"])

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_component_lots(PROGRAM_MANAGER, params),
            ApiErrorId.INVALID_PAGINATION,
            400,
        )

    rows, meta = validate_paginated(
        api.list_component_lots(PROGRAM_MANAGER, {"limit": constants.MAX_LIMIT})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["limit"] == constants.MAX_LIMIT
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Design instance: qp_release_decision_is_immutable_and_carries_no_version_field
# ---------------------------------------------------------------------------
def test_qualified_person_decision_is_append_only_and_unrepeatable(api):
    """The signed record carries no `version` and no `updated_at`, and never gains one.

    PRD 2.4: "The single exception is the Qualified-Person release decision: it is an append-only evidential record that is never modified after it is written, so it carries only `id` and `created_at` — it has no `updated_at` field and no `version` field at all."

    Design: Corner/entities/qp_release_decision_is_immutable_and_carries_no_version_field
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)

    decision = validate_success(
        api.qp_release(
            program["batch_id"],
            factories.qp_release_payload(decision="QUARANTINE"),
            QUALIFIED_PERSON,
        ),
        201,
    )
    assert decision["decision"] == "QUARANTINE"
    assert decision["qp_user_id"] == QP_USER_ID
    assert decision["batch_order_id"] == program["batch_id"]
    assert decision["released_unit_count"] == 0
    assert decision["fee_cents"] == 0
    assert "version" not in decision
    assert "updated_at" not in decision
    assertions.assert_qp_release_decision(decision)

    rows, meta = validate_paginated(
        api.list_qp_release_decisions(program["batch_id"], QUALIFIED_PERSON)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert fixtures.read_batch(api, program["batch_id"])["quality_status"] == "QUARANTINED"

    validate_error(
        api.qp_release(
            program["batch_id"],
            factories.qp_release_payload(decision="RELEASE"),
            QUALIFIED_PERSON,
        ),
        ApiErrorId.BATCH_QUALITY_STATE_INVALID,
        409,
    )

    rows, meta = validate_paginated(
        api.list_qp_release_decisions(program["batch_id"], QUALIFIED_PERSON)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["decision"] == "QUARANTINE"
    assert rows[0]["released_unit_count"] == 0
    assert "version" not in rows[0]


# ---------------------------------------------------------------------------
# Design instance: client_project_unknown_primary_suite_reference_rejected
# ---------------------------------------------------------------------------
def test_intake_naming_a_suite_that_does_not_exist_is_refused(api):
    """A body foreign key that resolves to nothing yields the suite's own 404.

    PRD 2.11: "A `primary_suite_id` or `suite_id` that names no suite yields `ERR_FILLING_SUITE_NOT_FOUND`; a `client_project_id` that names no project yields `ERR_CLIENT_PROJECT_NOT_FOUND`; a `media_fill_id` yields `ERR_MEDIA_FILL_NOT_FOUND`; a `lead_operator_qualification_id` yields `ERR_QUALIFICATION_NOT_FOUND`; a `batch_order_id` yields `ERR_BATCH_ORDER_NOT_FOUND`; a `component_lot_id` yields `ERR_COMPONENT_LOT_NOT_FOUND`; and an `em_sample_id` yields `ERR_EM_SAMPLE_NOT_FOUND`."

    Design: Corner/entities/client_project_unknown_primary_suite_reference_rejected
    """
    validate_error(
        api.create_client_project(
            factories.client_project_payload(NON_EXISTENT_UUID), PROGRAM_MANAGER
        ),
        ApiErrorId.FILLING_SUITE_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(api.list_client_projects(PROGRAM_MANAGER))
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: filling_suite_system_fields_generated_and_client_supplied_values_ignored
# ---------------------------------------------------------------------------
def test_new_suite_generates_its_own_system_fields_and_ignores_supplied_ones(api):
    """The client's id, version, posture and ledgers are all discarded.

    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID with no type prefix; clients never supply it."

    PRD 3.2: "A new suite is born with `aseptic_qualification_status` of `NOT_QUALIFIED`, `cleaning_validation_status` of `NOT_VALIDATED`, `media_fill_valid_until` and `last_cleaned_molecule` both null, and `committed_minutes`, `open_action_excursion_count` and `qualified_operator_count` all 0 — which, per section 2.5, computes an initial `posture` of `RESTRICTED`."

    Design: Corner/entities/filling_suite_system_fields_generated_and_client_supplied_values_ignored
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)

    suite = validate_success(
        api.create_filling_suite(
            factories.filling_suite_payload(
                suite_code="FS-9",
                grade="A",
                changeover_minutes_same_product=45,
                changeover_minutes_product_change=180,
                max_committed_minutes=9000,
                id=NON_EXISTENT_UUID,
                version=77,
                posture=constants.POSTURE_OPEN,
                committed_minutes=5000,
                aseptic_qualification_status="QUALIFIED",
                cleaning_validation_status="VALIDATED",
                media_fill_valid_until="2030-01-01T00:00:00Z",
                qualified_operator_count=9,
                open_action_excursion_count=4,
                created_at="2020-01-01T00:00:00.000Z",
                updated_at="2020-01-01T00:00:00.000Z",
            ),
            PROGRAM_MANAGER,
        ),
        201,
    )

    assert is_valid_uuid(suite["id"])
    assert suite["id"] != NON_EXISTENT_UUID
    assert suite["version"] == 1
    assert is_iso8601_timestamp(suite["created_at"])
    assert is_iso8601_timestamp(suite["updated_at"])
    assert not suite["created_at"].startswith("2020")
    assert suite["suite_code"] == "FS-9"
    assert suite["grade"] == "A"
    assert suite["changeover_minutes_same_product"] == 45
    assert suite["changeover_minutes_product_change"] == 180
    assert suite["max_committed_minutes"] == 9000
    assert suite["committed_minutes"] == 0
    assert suite["posture"] == constants.POSTURE_RESTRICTED
    assert suite["aseptic_qualification_status"] == "NOT_QUALIFIED"
    assert suite["cleaning_validation_status"] == "NOT_VALIDATED"
    assert suite["media_fill_valid_until"] is None
    assert suite["last_cleaned_molecule"] is None
    assert suite["open_action_excursion_count"] == 0
    assert suite["qualified_operator_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: component_reservation_rejects_lot_belonging_to_another_project
# ---------------------------------------------------------------------------
def test_reserving_another_sponsors_lot_is_refused_as_a_project_mismatch(api):
    """Packaging is project-dedicated, so a foreign lot cannot back this batch.

    PRD 3.4: "The lot must belong to the same programme and the right presentation: its `client_project_id` must equal the batch's `client_project_id`, and its `component_type` must be one of the lines the project's `dosage_form` actually calls for — a `VIAL` project consumes `VIAL` and `STOPPER` lots, a `PRESYRINGE` project consumes `SYRINGE` and `PLUNGER` lots — with any mismatch refused as `ERR_COMPONENT_LOT_PROJECT_MISMATCH` (HTTP 409)."

    Design: Corner/entities/component_reservation_rejects_lot_belonging_to_another_project
    """
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SCHEDULED, reserved_unit_budget=50000
    )
    other = fixtures.create_project(
        api,
        program["suite_id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        reserved_unit_budget=50000,
    )
    fixtures.activate_project(api, other["id"])
    foreign_lot = fixtures.release_lot(
        api, other["id"], component_type="VIAL", lot_code="VL-B"
    )
    assert foreign_lot["quantity_available"] == 30000

    validate_error(
        api.create_component_reservation(
            factories.component_reservation_payload(
                program["batch_id"],
                foreign_lot["id"],
                constants.WORKED_VIAL_LINE_UNITS,
                foreign_lot["version"],
            ),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.COMPONENT_LOT_PROJECT_MISMATCH,
        409,
    )

    rows, meta = validate_paginated(
        api.list_component_reservations(
            PROGRAM_MANAGER, {"batch_order_id": program["batch_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    lot = fixtures.read_lot(api, foreign_lot["id"])
    assert lot["quantity_available"] == 30000
    assert lot["status"] == "RELEASED"
