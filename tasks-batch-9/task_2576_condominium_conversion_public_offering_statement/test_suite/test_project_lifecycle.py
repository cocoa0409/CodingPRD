"""Conversion project: creation defaults, server-generated system fields, partial
updates, derived summary reads, and the derived posture ladder.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_common_fields,
    assert_decimal_equals,
    assert_instant,
    assert_page,
)
from test_helpers.constants import CLOCK_DEFAULT_UTC, SPONSOR_USER_ID
from test_helpers.factories import (
    batch_payload,
    component_payload,
    household_payload,
    package_payload,
    project_payload,
)
from test_helpers.fixtures import (
    make_assessment,
    make_component,
    make_project,
    make_report,
    reject_report,
    set_clock,
    submit_report,
)
from test_helpers.test_users import (
    engineer_headers,
    escrow_headers,
    lender_headers,
    peer_headers,
    regulator_headers,
    sponsor_headers,
)

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_create_conversion_project_returns_declared_defaults(api):
    """PRD: A `ConverterSponsor` opens the file by registering a **conversion project**,
    supplying the `building_address` of the building being converted.

    Design: Corner/entities/create_conversion_project_returns_declared_defaults
    """
    data = validate_success(
        api.create_project(project_payload(*STD_PROJECT), sponsor_headers()),
        expected_status=201,
    )
    assert_common_fields(data)
    assert data["building_address"] == "44 Cove Lane, Bangor ME"
    assert data["year_built"] == 1968
    assert data["total_unit_count"] == 2
    assert data["sponsor_user_id"] == SPONSOR_USER_ID
    assert data["max_overlapping_remediations"] == 2
    assert data["status"] == "FEASIBILITY"
    assert data["posture"] == "RESTRICTED"
    assert data["suitability_gate"] == "UNEVALUATED"
    assert_decimal_equals(data["suitability_score"], "0.00", "suitability_score")
    assert data["included_unit_count"] == 0
    assert data["bp_conservation_total"] == 0
    assert data["escrow_deposits_received_cents"] == 0
    assert data["escrow_balance_cents"] == 0
    assert data["escrow_reconciliation_delta_cents"] == 0
    assert data["relocation_reconciliation_delta_cents"] == 0
    assert data["warranty_reserve_charge_cents"] == 0
    assert data["warrantability_verdict"] == "UNEVALUATED"
    assert data["warrantability_verdict_closed_basis"] == "UNEVALUATED"
    assert data["declaration_recorded_at"] is None
    assert data["warranty_start_at"] is None
    assert data["version"] == 1


def test_conversion_project_system_fields_generated_by_server(api):
    """PRD: Every entity in this system carries a server-generated `id`, `created_at`
    and `updated_at` timestamp, and an integer `version` that starts at 1.

    Design: Corner/entities/conversion_project_system_fields_generated_by_server
    """
    project = make_project(api, "9 Harbor Row, Bath ME", 1972, 3)
    assert_common_fields(project)
    baseline_version = project["version"]
    set_clock(api, "2026-08-15T00:00:00Z")

    data = validate_success(
        api.recalculate_posture(project["id"], regulator_headers())
    )
    assert data["id"] == project["id"]
    assert_instant(data["last_posture_recalculated_at"], "2026-08-15T00:00:00Z")
    assert data["posture"] == "RESTRICTED"
    assert data["version"] == baseline_version + 1


def test_omitted_optional_inputs_apply_declared_entity_defaults(api):
    """PRD: `planned_remediation_gain_years` defaults to 0, and both `is_life_safety`
    and `is_structural` default to false.

    Design: Corner/entities/omitted_optional_inputs_apply_declared_entity_defaults
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])

    component = validate_success(
        api.create_component(
            report["id"],
            component_payload("ROOF", 30, 10, 10000000, 0, "GOOD"),
            engineer_headers(),
        ),
        expected_status=201,
    )
    assert component["planned_remediation_gain_years"] == 0
    assert component["is_life_safety"] is False
    assert component["is_structural"] is False

    household = validate_success(
        api.create_household(
            project["id"],
            household_payload("HH-1", "2026-01-01T00:00:00Z", 300000),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert household["protected_class"] == "NONE"
    assert household["occupied_unit_id"] is None
    assert household["notice_status"] == "PRE_NOTICE"
    assert household["rofr_status"] == "NOT_OFFERED"
    assert household["relocation_status"] == "NOT_OWED"

    batch = validate_success(
        api.create_batch(
            project["id"],
            batch_payload(1, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", 51.0, 1),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert batch["status"] == "DRAFT"
    assert batch["assigned_agreement_count"] == 0
    assert_decimal_equals(batch["presale_pct"], "0.00", "presale_pct")


def test_patch_conversion_project_rewrites_only_the_supplied_fields(api):
    """PRD: The sponsor may later amend the `building_address`, the `total_unit_count`
    or the `max_overlapping_remediations` of a project.

    Design: Corner/endpoints/patch_conversion_project_rewrites_only_the_supplied_fields
    """
    project = validate_success(
        api.create_project(
            project_payload(
                "44 Cove Lane, Bangor ME", 1968, 12, max_overlapping_remediations=4
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert project["version"] == 1

    data = validate_success(
        api.patch_project(
            project["id"],
            {"building_address": "44 Cove Lane, Unit A, Bangor ME"},
            sponsor_headers(),
        )
    )
    assert data["building_address"] == "44 Cove Lane, Unit A, Bangor ME"
    assert data["total_unit_count"] == 12
    assert data["max_overlapping_remediations"] == 4
    assert data["year_built"] == 1968
    assert data["sponsor_user_id"] == SPONSOR_USER_ID
    assert data["status"] == "FEASIBILITY"
    assert data["posture"] == "RESTRICTED"
    assert data["suitability_gate"] == "UNEVALUATED"
    assert data["version"] == 2


def test_summary_reads_return_derived_projections_without_mutating_state(api):
    """PRD: Computed read of the project's escrow and relocation cash conservation
    snapshot.

    Design: Corner/endpoints/summary_reads_return_derived_projections_without_mutating_state
    """
    project = make_project(api, *STD_PROJECT)
    batch = validate_success(
        api.create_batch(
            project["id"],
            batch_payload(1, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", 50, 1),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert batch["version"] == 1

    validate_success(api.escrow_summary(project["id"], escrow_headers()))
    after_escrow = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert after_escrow["escrow_deposits_received_cents"] == 0
    assert after_escrow["escrow_balance_cents"] == 0
    assert after_escrow["escrow_refunded_cents"] == 0
    assert after_escrow["escrow_disbursed_cents"] == 0
    assert after_escrow["escrow_reconciliation_delta_cents"] == 0

    validate_success(api.relocation_summary(project["id"], regulator_headers()))
    after_relocation = validate_success(
        api.get_project(project["id"], sponsor_headers())
    )
    assert after_relocation["relocation_obligation_accrued_cents"] == 0
    assert after_relocation["relocation_outstanding_cents"] == 0
    assert after_relocation["relocation_reconciliation_delta_cents"] == 0

    validate_success(api.threshold_summary(batch["id"], lender_headers()))
    after_batch = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert after_batch["status"] == "DRAFT"
    assert after_batch["last_evaluated_at"] is None
    assert_decimal_equals(after_batch["presale_pct"], "0.00", "presale_pct")
    assert after_batch["assigned_agreement_count"] == 0
    assert after_batch["version"] == 1
    assert validate_success(api.get_project(project["id"], sponsor_headers()))["version"] == 1


def test_posture_first_match_reports_frozen_over_restricted(api):
    """PRD: A project is `FROZEN` when its `suitability_gate` is `FAILED`; otherwise it
    is `RESTRICTED`.

    Design: Corner/calculations/posture_first_match_reports_frozen_over_restricted
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api,
        report["id"],
        component_payload(
            "FOUNDATION", 1, 59, 4000000, 0, "POOR", is_structural=True
        ),
    )
    submit_report(api, report["id"])
    validate_success(api.verify_component(component["id"], True, peer_headers()))

    before = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert before["posture"] == "RESTRICTED"
    assert before["suitability_gate"] == "UNEVALUATED"

    assessment = make_assessment(api, report["id"])
    assert_decimal_equals(assessment["score"], "0.00", "score")
    assert assessment["basis"] == "VERIFIED_COMPONENTS"
    assert assessment["verdict"] == "FAILED"
    assert assessment["critical_cap_applied"] is False

    after = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert after["suitability_gate"] == "FAILED"
    assert after["posture"] == "FROZEN"
    assert after["status"] == "SUITABILITY_REVIEW"


def test_project_posture_rederived_from_children_after_gate_clears(api):
    """PRD: A project is `FROZEN` when its `suitability_gate` is `FAILED`; otherwise it
    is `RESTRICTED`.

    Design: Corner/state_machines/project_posture_rederived_from_children_after_gate_clears
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api, report["id"], component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")
    )
    submit_report(api, report["id"])
    reject_report(api, report["id"])

    before = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert before["posture"] == "FROZEN"
    assert before["suitability_gate"] == "FAILED"
    assert_decimal_equals(before["suitability_score"], "0.00", "suitability_score")

    # The project is FROZEN here, and PRD 3.1's pinned exemption list names
    # "adjusting a major component's engineering inputs" while saying nothing about
    # the explicit revision request.  The named route reopens the cycle by itself:
    # "If instead the parent report was in `status` `REVISION_REQUESTED`, the edit
    # reopens the drafting cycle and the report moves `REVISION_REQUESTED -> DRAFT`."
    validate_success(
        api.patch_component(component["id"], {"effective_age_years": 9}, engineer_headers())
    )
    reopened = validate_success(api.get_report(report["id"], engineer_headers()))
    assert reopened["status"] == "DRAFT"

    # Submission "sets `verification_status` to `VERIFIED` on every child major
    # component", which is what satisfies ACCEPT's extra precondition that the
    # report's `verified_component_count` be at least 1.
    resubmitted = submit_report(api, report["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["verified_component_count"] == 1
    validate_success(
        api.peer_review(
            report["id"],
            {"decision": "ACCEPT", "reviewed_by_user_id": "peer-1"},
            peer_headers(),
        )
    )

    assessment = make_assessment(api, report["id"])
    assert assessment["verdict"] == "PASSED"
    assert_decimal_equals(assessment["score"], "100.00", "score")
    cleared = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert cleared["suitability_gate"] == "PASSED"
    assert cleared["status"] == "DOCUMENTS_PREPARATION"

    swept = validate_success(api.recalculate_posture(project["id"], regulator_headers()))
    assert swept["posture"] == "RESTRICTED"
    assert_instant(swept["last_posture_recalculated_at"], CLOCK_DEFAULT_UTC)


def test_frozen_posture_blocks_non_exempt_writes_but_not_exempt_ones(api):
    """PRD: A `FROZEN` posture rejects every write request against the project's graph
    with `ERR_PROJECT_FROZEN` (HTTP 409), with a pinned exemption list.

    Design: Corner/validations/frozen_posture_blocks_non_exempt_writes_but_not_exempt_ones
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api, report["id"], component_payload("ROOF", 30, 4, 2500000, 0, "EXCELLENT")
    )
    submit_report(api, report["id"])
    reject_report(api, report["id"], review_note="component set incomplete")

    frozen_report = validate_success(api.get_report(report["id"], engineer_headers()))
    assert frozen_report["status"] == "REVISION_REQUESTED"
    frozen_project = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert frozen_project["suitability_gate"] == "FAILED"
    assert_decimal_equals(
        frozen_project["suitability_score"], "0.00", "suitability_score"
    )
    assert validate_success(api.get_component(component["id"], engineer_headers()))[
        "verification_status"
    ] == "UNVERIFIED"

    validate_error(
        api.create_package(project["id"], package_payload(), sponsor_headers()),
        "ERR_PROJECT_FROZEN",
        expected_status=409,
    )
    _, meta = validate_paginated(api.list_packages(project["id"], sponsor_headers()))
    assert_page(meta, total_count=0)

    swept = validate_success(api.recalculate_posture(project["id"], sponsor_headers()))
    assert swept["posture"] == "FROZEN"
    assert_instant(swept["last_posture_recalculated_at"], CLOCK_DEFAULT_UTC)

    edited = validate_success(
        api.patch_component(
            component["id"], {"remaining_useful_life_years": 25}, engineer_headers()
        )
    )
    assert edited["remaining_useful_life_years"] == 25
    assert validate_success(api.get_report(report["id"], engineer_headers()))[
        "status"
    ] == "DRAFT"


def test_posture_sweep_is_a_no_op_because_the_assessment_already_applied_its_projection(
    api,
):
    """PRD: A posture recalculation re-derives the same posture from the same children
    and stamps `last_posture_recalculated_at`.

    Design: Corner/consistency_model/posture_sweep_is_a_no_op_because_the_assessment_already_applied_its_projection
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(
        api, report["id"], component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")
    )
    submit_report(api, report["id"])
    validate_success(api.verify_component(component["id"], True, peer_headers()))

    before = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert before["posture"] == "RESTRICTED"
    assert before["suitability_gate"] == "UNEVALUATED"
    assert before["last_posture_recalculated_at"] is None

    make_assessment(api, report["id"])
    applied = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert applied["suitability_gate"] == "PASSED"
    assert_decimal_equals(applied["suitability_score"], "100.00", "suitability_score")
    assert applied["posture"] == "RESTRICTED"
    assert applied["status"] == "DOCUMENTS_PREPARATION"

    swept = validate_success(api.recalculate_posture(project["id"], sponsor_headers()))
    assert swept["posture"] == "RESTRICTED"
    assert swept["suitability_gate"] == "PASSED"
    assert_decimal_equals(swept["suitability_score"], "100.00", "suitability_score")
    assert swept["status"] == "DOCUMENTS_PREPARATION"
    assert_instant(swept["last_posture_recalculated_at"], CLOCK_DEFAULT_UTC)

    set_clock(api, "2026-08-02T00:00:00Z")
    resept = validate_success(api.recalculate_posture(project["id"], regulator_headers()))
    assert_instant(resept["last_posture_recalculated_at"], "2026-08-02T00:00:00Z")
