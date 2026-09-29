"""Endpoint contracts that only a full round trip can pin down.

The unit-accounting read must publish both stamped variants and their delta
rather than recomputing one figure twice; the readiness assessment applies the
enum rung to a query parameter; and the audit engagement is a cyclic machine
whose deferral discards the supplied finding count while a later hosting stamps
it, subject to the frozen-suite guard.
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
    PROGRAM_MANAGER,
    QUALIFIED_PERSON,
    make_client_representative_headers,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: unit_accounting_read_exposes_both_variants_and_their_delta
# ---------------------------------------------------------------------------
def test_the_accounting_read_publishes_both_variants_and_a_delta_of_144(api):
    """8418 provisional against 8274 final, with every component term beside them.

    PRD 3.9: "Addressed at a batch, it returns `batch_order_id`, the `filled_unit_count` both variants start from, the forward-looking `expected_reject_units` derived from the sponsor's historical rate, the `actual_visual_reject_units` actually recorded by visual inspection controls, the `destructive_total_units` both variants subtract, the `quarantined_unit_count` only the final variant subtracts, the stored `provisional_releasable_units` and `final_releasable_units`, and `variant_delta_units`, which is `provisional_releasable_units` minus `final_releasable_units` — positive whenever the sponsor's declared history flattered the batch."

    PRD 3.8: "It projects rejects from the sponsor's own contractual figure: the expected reject count is `filled_unit_count` multiplied by the project's `historical_reject_rate_ppm` divided by one million, rounded *up* to a whole number — a ceiling, never a half-up rounding."

    Design: Corner/endpoints/unit_accounting_read_exposes_both_variants_and_their_delta
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)

    accounting = validate_success(
        api.get_unit_accounting(program["batch_id"], QUALIFIED_PERSON), 200
    )
    assert accounting["batch_order_id"] == program["batch_id"]
    assert accounting["filled_unit_count"] == constants.WORKED_FILLED_UNIT_COUNT
    assert accounting["expected_reject_units"] == constants.WORKED_EXPECTED_REJECT_UNITS
    assert accounting["expected_reject_units"] != 21
    assert (
        accounting["actual_visual_reject_units"]
        == constants.WORKED_ACTUAL_VISUAL_REJECT_UNITS
    )
    assert (
        accounting["destructive_total_units"] == constants.WORKED_DESTRUCTIVE_TOTAL_UNITS
    )
    assert accounting["quarantined_unit_count"] == 0
    assert (
        accounting["provisional_releasable_units"]
        == constants.WORKED_PROVISIONAL_RELEASABLE_UNITS
    )
    assert accounting["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS
    assert accounting["variant_delta_units"] == constants.WORKED_VARIANT_DELTA_UNITS
    assert (
        accounting["provisional_releasable_units"] != accounting["final_releasable_units"]
    )


# ---------------------------------------------------------------------------
# Design instance: readiness_assessment_invalid_enum_variant_rejected
# ---------------------------------------------------------------------------
def test_the_enum_rung_reaches_the_readiness_query_parameter(api):
    """PROVISIONAL is no variant at all; GMP_AUDIT scores this project at 100.

    PRD 3.9: "The caller must supply a `variant` of either `INTAKE_FORECAST` or `GMP_AUDIT`; the parameter is required and a value outside that set is refused with `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

    PRD 2.10: "**Enum membership** — `ERR_INVALID_ENUM_VALUE`, on every POST carrying an enum-typed input and additionally on the two computed reads `GET /client-projects/{id}/readiness-assessment` and `GET /batch-orders/{id}/unit-accounting`."

    Design: Corner/endpoints/readiness_assessment_invalid_enum_variant_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)

    validate_error(
        api.get_readiness_assessment(
            program["project_id"], PROGRAM_MANAGER, {"variant": "PROVISIONAL"}
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
        422,
    )

    audit_view = validate_success(
        api.get_readiness_assessment(
            program["project_id"], PROGRAM_MANAGER, {"variant": "GMP_AUDIT"}
        ),
        200,
    )
    assert audit_view["variant"] == "GMP_AUDIT"
    assert audit_view["tech_points"] == constants.READINESS_TECH_MAX
    assert audit_view["analytical_points"] == constants.READINESS_ANALYTICAL_MAX
    assert audit_view["aseptic_points"] == constants.READINESS_ASEPTIC_MAX
    assert audit_view["operator_points"] == constants.READINESS_OPERATOR_MAX
    assert audit_view["counted_operator_count"] == 2
    assert audit_view["readiness_score"] == 100

    forecast_view = validate_success(
        api.get_readiness_assessment(
            program["project_id"], PROGRAM_MANAGER, {"variant": "INTAKE_FORECAST"}
        ),
        200,
    )
    assert forecast_view["variant"] == "INTAKE_FORECAST"
    assert forecast_view["counted_operator_count"] == 2
    assert forecast_view["readiness_score"] == 100


# ---------------------------------------------------------------------------
# Design instance:
#   audit_engagement_deferral_then_hosting_recomputes_the_project_finding_count
# ---------------------------------------------------------------------------
def test_a_deferral_discards_its_findings_and_a_later_hosting_stamps_them(api):
    """Nine findings evaporate on the deferral; four survive the re-hosting.

    PRD 3.9: "A new engagement is born with `status` of `REQUESTED`, `finding_count` of 0 and `hosted_at` null."

    PRD 3.9: "A deferral instead sets `status` to `DEFERRED`, leaves `hosted_at` null and leaves `finding_count` at 0 regardless of what was supplied, and bumps the engagement's `version`."

    PRD 3.9: "A successful hosting writes the supplied `finding_count`, stamps `hosted_at` from the logical clock, sets `status` to `HOSTED`, recomputes the project's `last_client_audit_finding_count`, and bumps the engagement's `version`."

    Design: Corner/endpoints/audit_engagement_deferral_then_hosting_recomputes_the_project_finding_count
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    sponsor = make_client_representative_headers(program["project_id"])

    engagement = validate_success(
        api.create_audit_engagement(
            factories.audit_engagement_payload(
                program["project_id"], audit_kind="CLIENT_AUDIT"
            ),
            sponsor,
        ),
        201,
    )
    assert engagement["status"] == "REQUESTED"
    assert engagement["finding_count"] == 0
    assert engagement["hosted_at"] is None

    deferred = fixtures.host_audit(
        api, engagement["id"], outcome="DEFERRED", finding_count=9
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["finding_count"] == 0
    assert deferred["hosted_at"] is None
    assert (
        fixtures.read_project(api, program["project_id"])[
            "last_client_audit_finding_count"
        ]
        == 0
    )

    fixtures.set_clock(api, "2026-09-25T00:00:00Z")
    hosted = fixtures.host_audit(
        api, engagement["id"], outcome="HOSTED", finding_count=4
    )
    assert hosted["status"] == "HOSTED"
    assert hosted["finding_count"] == 4
    assertions.assert_same_instant(
        hosted["hosted_at"], "2026-09-25T00:00:00Z", "hosted_at"
    )
    assert (
        fixtures.read_project(api, program["project_id"])[
            "last_client_audit_finding_count"
        ]
        == 4
    )

    rows, meta = validate_paginated(
        api.list_project_audit_engagements(program["project_id"], sponsor)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "HOSTED"
    assert rows[0]["finding_count"] == 4


# ---------------------------------------------------------------------------
# Design instance: audit_engagement_hosting_on_a_frozen_suite_rejected
# ---------------------------------------------------------------------------
def test_no_sponsor_is_walked_through_a_frozen_suite(api):
    """A three-unit contamination freezes FS-1 and the rehearsal is refused.

    PRD 3.9: "Hosting additionally requires that the project's `status` is `ACTIVE`, or else `ERR_PROJECT_STATE_INVALID` (HTTP 409), and that the project's nominated `primary_suite_id` has a `posture` other than `FROZEN`, or else `ERR_SUITE_NOT_OPEN` (HTTP 409) — you do not walk a sponsor through a frozen suite."

    Design: Corner/endpoints/audit_engagement_hosting_on_a_frozen_suite_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    engagement = fixtures.request_audit(
        api, program["project_id"], audit_kind="INSPECTION_READINESS"
    )
    assert engagement["status"] == "REQUESTED"

    second_run = fixtures.create_media_fill(
        api, program["suite_id"], scheduled_run_date="2026-09-05T08:00:00Z"
    )
    fixtures.execute_media_fill(
        api,
        second_run["id"],
        units_filled=6000,
        participating_operator_names=["OP-A", "OP-B"],
    )
    failed = fixtures.read_media_fill_out(api, second_run["id"], 3)
    assert failed["status"] == "FAILED"

    error = validate_error(
        api.host_audit_engagement(
            engagement["id"],
            factories.host_audit_payload(outcome="HOSTED", finding_count=2),
            PROGRAM_MANAGER,
        ),
        ApiErrorId.SUITE_NOT_OPEN,
        409,
    )
    assert error["error_id"] != ApiErrorId.AUDIT_ENGAGEMENT_STATE_INVALID
    assert error["error_id"] != ApiErrorId.PROJECT_STATE_INVALID

    suite = fixtures.read_suite(api, program["suite_id"])
    assert suite["aseptic_qualification_status"] == "INVALIDATED"
    assert suite["posture"] == constants.POSTURE_FROZEN

    project = fixtures.read_project(api, program["project_id"])
    assert project["status"] == "ACTIVE"
    assert project["last_client_audit_finding_count"] == 0

    rows, _meta = validate_paginated(
        api.list_project_audit_engagements(program["project_id"], PROGRAM_MANAGER)
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "REQUESTED"
    assert rows[0]["hosted_at"] is None
    assert rows[0]["finding_count"] == 0
