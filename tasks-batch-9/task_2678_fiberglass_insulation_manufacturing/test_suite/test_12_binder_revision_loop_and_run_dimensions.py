"""Non-linear state machines: a formulation that revisits emissions testing, and a
run whose physical and quality dimensions advance on separate tracks.

Queue A / non_linear_state_machine.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import (
    QUALITY_ENGINEER_USER_ID_ALT,
    certification_officer_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

REVISION_NOTE = "VOC margin too thin at 4.8 g/kg"

WEAK_SPECIMENS = [12.40, 12.50, 12.60]
STRONG_SPECIMENS = [13.10, 13.20, 12.90]


def _binder_under_test(client: InsulationApiClient) -> Dict[str, Any]:
    """A formaldehyde-free formulation parked in EMISSIONS_TESTING on its first pass."""
    fx.reset_clock(client)
    binder = get_success_data(
        client.create_binder_formulation(
            f.formaldehyde_free_binder_payload(**FREE_BINDER), quality_engineer_headers()
        ),
        201,
    )
    get_success_data(client.submit_binder(binder["id"], quality_engineer_headers()))
    tested = get_success_data(
        client.record_binder_emissions_test(
            binder["id"],
            f.binder_emissions_test_payload(40, 4.8, "LAB-9001"),
            certification_officer_headers(),
        )
    )
    return tested


def _revised_binder(client: InsulationApiClient) -> Dict[str, Any]:
    """First pass rejected for rework, then reworked back to DRAFT."""
    tested = _binder_under_test(client)
    get_success_data(
        client.binder_certification_decision(
            tested["id"],
            f.binder_decision_payload("REQUEST_REVISION", revision_notes=REVISION_NOTE),
            certification_officer_headers(),
        )
    )
    return get_success_data(
        client.revise_binder(
            tested["id"],
            f.binder_revise_payload(
                "REVISE",
                formaldehyde_free=True,
                formaldehyde_ppm=0,
                voc_g_per_kg=3.2,
                min_cure_temp_f=420.0,
                min_dwell_s=150.0,
                loi_target_pct=4.5,
            ),
            quality_engineer_headers(),
        )
    )


def test_lab_measurement_overwrites_the_drafted_chemistry_on_the_first_pass(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "the two measured figures **overwrite** the drafted values on the row and
    the formulation advances `SUBMITTED -> EMISSIONS_TESTING` with the reference stored."

    Design: Difficulty/non_linear_state_machine/binder_revision_cycle_revisits_emissions_testing_twice
    """
    tested = _binder_under_test(client)

    assert_field_equals(tested, "status", "EMISSIONS_TESTING")
    assert_field_equals(tested, "formaldehyde_ppm", 40)
    assert_close(tested["voc_g_per_kg"], 4.8, 2, "voc_g_per_kg")
    assert_field_equals(tested, "lab_reference", "LAB-9001")
    assert_field_equals(tested, "revision_count", 0)
    assert tested["emissions_cert_id"] is None
    assert tested["certified_at"] is None


def test_request_revision_parks_the_note_without_minting_a_certificate(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "A `decision` of `REQUEST_REVISION` requires the formulation to be in
    `EMISSIONS_TESTING` and a non-empty `revision_notes`; it moves the formulation
    `EMISSIONS_TESTING -> REVISION_REQUIRED` and stores the note - no certificate is
    minted and `certified_at` stays null."

    Design: Difficulty/non_linear_state_machine/binder_revision_cycle_revisits_emissions_testing_twice
    """
    tested = _binder_under_test(client)

    parked = get_success_data(
        client.binder_certification_decision(
            tested["id"],
            f.binder_decision_payload("REQUEST_REVISION", revision_notes=REVISION_NOTE),
            certification_officer_headers(),
        )
    )

    assert_field_equals(parked, "status", "REVISION_REQUIRED")
    assert_field_equals(parked, "revision_notes", REVISION_NOTE)
    assert parked["emissions_cert_id"] is None
    assert parked["certified_at"] is None
    assert_field_equals(parked, "revision_count", 0)


def test_rework_returns_the_row_to_draft_and_clears_every_certification_trace(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "the formulation moves from `REVISION_REQUIRED` or `SUSPENDED` back to
    `DRAFT`: `revision_count` increases by one, and `emissions_cert_id`,
    `lab_reference`, `certified_at` and `revision_notes` are all cleared to null."

    Design: Difficulty/non_linear_state_machine/binder_revision_cycle_revisits_emissions_testing_twice
    """
    revised = _revised_binder(client)

    assert_field_equals(revised, "status", "DRAFT")
    assert_field_equals(revised, "revision_count", 1)
    assert revised["emissions_cert_id"] is None
    assert revised["lab_reference"] is None
    assert revised["certified_at"] is None
    assert revised["revision_notes"] is None
    # The rework re-declared the original chemistry, so the measured 40 ppm is gone.
    assert_field_equals(revised, "formaldehyde_free", True)
    assert_field_equals(revised, "formaldehyde_ppm", 0)
    assert_close(revised["voc_g_per_kg"], 3.2, 2, "voc_g_per_kg")


def test_second_pass_re_enters_emissions_testing_on_the_very_same_row(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "the revision cycle reads `DRAFT -> SUBMITTED -> EMISSIONS_TESTING ->
    REVISION_REQUIRED -> DRAFT`."

    Design: Difficulty/non_linear_state_machine/binder_revision_cycle_revisits_emissions_testing_twice
    """
    revised = _revised_binder(client)
    binder_id = revised["id"]

    resubmitted = get_success_data(
        client.submit_binder(binder_id, quality_engineer_headers())
    )
    assert_field_equals(resubmitted, "status", "SUBMITTED")
    assert_field_equals(resubmitted, "id", binder_id)

    retested = get_success_data(
        client.record_binder_emissions_test(
            binder_id,
            f.binder_emissions_test_payload(0, 3.2, "LAB-9002"),
            certification_officer_headers(),
        )
    )

    assert_field_equals(retested, "status", "EMISSIONS_TESTING")
    assert_field_equals(retested, "id", binder_id)
    assert_field_equals(retested, "lab_reference", "LAB-9002")
    # Re-entering the testing state is not itself a revision.
    assert_field_equals(retested, "revision_count", 1)


def test_certificate_earned_on_the_second_pass_differs_only_by_the_revision_counter(
    client: InsulationApiClient,
) -> None:
    """PRD 3.2: "it moves the formulation `EMISSIONS_TESTING -> CERTIFIED`, stores the
    supplied `emissions_cert_id` as the certificate identifier, and stamps
    `certified_at` with the logical clock's current reading."

    Design: Difficulty/non_linear_state_machine/binder_revision_cycle_revisits_emissions_testing_twice
    """
    revised = _revised_binder(client)
    binder_id = revised["id"]
    get_success_data(client.submit_binder(binder_id, quality_engineer_headers()))
    get_success_data(
        client.record_binder_emissions_test(
            binder_id,
            f.binder_emissions_test_payload(0, 3.2, "LAB-9002"),
            certification_officer_headers(),
        )
    )

    certified = get_success_data(
        client.binder_certification_decision(
            binder_id,
            f.binder_decision_payload("CERTIFY", emissions_cert_id="EC-4411"),
            certification_officer_headers(),
        )
    )

    assert_field_equals(certified, "status", "CERTIFIED")
    assert_field_equals(certified, "emissions_cert_id", "EC-4411")
    assert certified["certified_at"] is not None
    assert_field_equals(certified, "formaldehyde_ppm", 0)
    assert_close(certified["voc_g_per_kg"], 3.2, 2, "voc_g_per_kg")
    # A formulation certified on its first pass would carry revision_count 0; this row
    # is otherwise indistinguishable from that one.
    assert_field_equals(certified, "revision_count", 1)


def _packaged_run(client: InsulationApiClient) -> Dict[str, Any]:
    """PL-A on a formaldehyde-free binder, run through the oven and baled."""
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(FREE_BINDER),
        sku_overrides=dict(SKU_PL_A),
    )
    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    fx.start_melt(client, ctx["plant_id"], run["id"])
    fx.start_cure(
        client,
        ctx["plant_id"],
        run["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    run = fx.package_run(client, ctx["plant_id"], run["id"], bags_produced=120)
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    ctx["lot"] = fx.lot_for_run(client, run["id"])
    ctx["lot_id"] = ctx["lot"]["id"]
    fx.set_clock(client, "2026-08-04T08:00:00Z")
    return ctx


def _sampled_run(client: InsulationApiClient) -> Dict[str, Any]:
    """The packaged run with a thermal test open against it."""
    ctx = _packaged_run(client)
    ctx["test"] = fx.request_thermal_test(
        client,
        ctx["run_id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-04T08:00:00Z",
        window_end="2026-08-04T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    ctx["test_id"] = ctx["test"]["id"]
    return ctx


def _nonconforming_run(client: InsulationApiClient) -> Dict[str, Any]:
    """The sampled run condemned by a specimen under the floor."""
    ctx = _sampled_run(client)
    ctx["result"] = fx.record_thermal_result(
        client, ctx["test_id"], WEAK_SPECIMENS, user_id=QUALITY_ENGINEER_USER_ID_ALT
    )
    return ctx


def _retested_run(client: InsulationApiClient) -> Dict[str, Any]:
    """The condemned run sent back to the lab on a second attempt."""
    ctx = _nonconforming_run(client)
    ctx["retest"] = get_success_data(
        client.request_retest(
            ctx["test_id"],
            f.retest_window_payload("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z"),
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )
    return ctx


def test_requesting_a_test_moves_only_the_quality_dimension(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The same request advances the run's quality dimension
    `UNSAMPLED -> SAMPLED`."

    Design: Difficulty/non_linear_state_machine/run_status_and_qc_status_advance_as_independent_dimensions
    """
    ctx = _packaged_run(client)
    assert_field_equals(ctx["run"], "run_status", "PACKAGED")
    assert_field_equals(ctx["run"], "qc_status", "UNSAMPLED")
    assert_close(ctx["run"]["cure_index"], 110.00, 2, "cure_index")

    fx.request_thermal_test(
        client,
        ctx["run_id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-04T08:00:00Z",
        window_end="2026-08-04T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "SAMPLED")
    assert_field_equals(run, "run_status", "PACKAGED")
    assert run["closed_at"] is None


def test_a_condemning_verdict_leaves_the_physical_dimension_where_it_was(
    client: InsulationApiClient,
) -> None:
    """PRD 2.7: "A `ProductionRun` carries `run_status` (one of `SCHEDULED`, `HELD`,
    `MELTING`, `CURING`, `PACKAGED`, `CLOSED`, `ABORTED`) alongside `qc_status` (one of
    `UNSAMPLED`, `SAMPLED`, `CONFORMING`, `NONCONFORMING`, `RETEST_PENDING`)."

    Design: Difficulty/non_linear_state_machine/run_status_and_qc_status_advance_as_independent_dimensions
    """
    ctx = _nonconforming_run(client)

    assert_field_equals(ctx["result"], "conformance_verdict", "NONCONFORMING")
    assert_field_equals(ctx["result"], "status", "COMPLETED")
    assert_close(ctx["result"]["min_r_value"], 12.40, 2, "min_r_value")
    assert_close(ctx["result"]["mean_r_value"], 12.50, 2, "mean_r_value")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "NONCONFORMING")
    assert_field_equals(run, "run_status", "PACKAGED")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")
    assert_close(lot["available_sqft"], 0.00, 2, "available_sqft")


def test_a_retest_erases_the_result_and_parks_the_quality_dimension_pending(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "On success `attempt_number` increments by one, the status returns to
    `IN_LAB`, the new window replaces the old one, and the previous result is erased on
    the row - `specimen_r_values` back to empty, `specimen_count` to 0, `mean_r_value`,
    `min_r_value`, `conformance_verdict` and `recorded_by_user_id` all back to null -
    while the run's quality dimension moves `NONCONFORMING -> RETEST_PENDING`."

    Design: Difficulty/non_linear_state_machine/run_status_and_qc_status_advance_as_independent_dimensions
    """
    ctx = _retested_run(client)
    retest = ctx["retest"]

    assert_field_equals(retest, "id", ctx["test_id"])
    assert_field_equals(retest, "attempt_number", 2)
    assert_field_equals(retest, "status", "IN_LAB")
    assert_field_equals(retest, "specimen_r_values", [])
    assert_field_equals(retest, "specimen_count", 0)
    assert retest["mean_r_value"] is None
    assert retest["min_r_value"] is None
    assert retest["conformance_verdict"] is None
    assert retest["recorded_by_user_id"] is None

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "RETEST_PENDING")
    assert_field_equals(run, "run_status", "PACKAGED")


def test_a_clearing_retest_verdict_does_not_walk_the_quarantine_back(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "Because that cascade is not self-reversing, a subsequent `CONFORMING`
    retest result does **not** auto-release the quarantined lots - each one must be
    released explicitly, as 3.7 describes."

    Design: Difficulty/non_linear_state_machine/run_status_and_qc_status_advance_as_independent_dimensions
    """
    ctx = _retested_run(client)

    cleared = get_success_data(
        client.record_result(
            ctx["test_id"],
            STRONG_SPECIMENS,
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )

    assert_field_equals(cleared, "conformance_verdict", "CONFORMING")
    assert_field_equals(cleared, "status", "COMPLETED")
    assert_close(cleared["min_r_value"], 12.90, 2, "min_r_value")
    assert_close(cleared["mean_r_value"], 13.07, 2, "mean_r_value")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "CONFORMING")
    assert_field_equals(run, "run_status", "PACKAGED")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")


def test_closing_the_run_advances_the_physical_track_alone(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Closing advances the run `PACKAGED -> CLOSED` and stamps `closed_at`
    with the logical clock's current reading."

    Design: Difficulty/non_linear_state_machine/run_status_and_qc_status_advance_as_independent_dimensions
    """
    ctx = _retested_run(client)
    get_success_data(
        client.record_result(
            ctx["test_id"],
            STRONG_SPECIMENS,
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )

    closed = get_success_data(
        client.close_run(ctx["run_id"], plant_operator_headers(ctx["plant_id"]))
    )

    assert_field_equals(closed, "run_status", "CLOSED")
    assert_field_equals(closed, "qc_status", "CONFORMING")
    assert closed["closed_at"] is not None
