"""Quantities that must return to exactly where they started.

One counter on the importer is restored from a snapshot taken before the cascade
that moved it; one weight total on the supplier is restored by withdrawing the
evidence that moved it. In both cases "exactly" is the assertion.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
    assert_supplier_performance,
)
from test_helpers.factories import corrective_action_closure_payload
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS

RESOLVED_CLOSURE_NOTE = (
    "Post suspension sampling passed, so the corrective action is closed as resolved"
)


def test_resolved_closure_restores_the_blocked_pair_count_to_the_snapshot(
    api: ApiClient,
) -> None:
    """The counter went 0, then 1, and must come back to exactly 0.

    "The importer's `blocked_pair_count` is restored to exactly the action's
    `pre_action_blocked_pair_count`; when the closure followed a suspension
    decision, this also unblocks the combinations that branch B blocked, so the
    count returns exactly to the snapshot and not merely close to it."

    Design: Difficulty/compensating_invariant/blocked_pair_count_conservation
    """
    world = fx.reverified_after_decision(api, decision="IMPORT_SUSPENSION")
    assert_importer_rollup(fx.get_importer(api, world.importer_id), blocked_pair_count=1)

    response = api.post_corrective_action_closure(
        world.corrective_action_id,
        corrective_action_closure_payload("CLOSE_RESOLVED", closure_note=RESOLVED_CLOSURE_NOTE),
        COMPLIANCE_OFFICER_HEADERS,
    )

    action = validate_success(response)
    assert action["status"] == "CLOSED_RESOLVED"
    assert action["pre_action_blocked_pair_count"] == 0
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id),
        blocked_pair_count=0,
        open_corrective_action_count=0,
        program_status="COMPLIANT",
    )


def test_resolved_closure_reinstates_the_pair_the_entry_line_and_the_supplier(
    api: ApiClient,
) -> None:
    """Everything the suspension chain touched is walked back in one request.

    "The action's own combination moves `VERIFICATION_LAPSED ->
    VERIFICATION_APPROVED` or `REASSESSMENT_REQUIRED -> VERIFICATION_APPROVED`, with
    `last_reassessed_at` set to the logical clock. Its `entry_eligibility_status`
    moves `BLOCKED -> ELIGIBLE`, and every entry line on it whose `status` is `HELD`
    moves back to `ACCEPTED` with `held_reason` cleared to null." "The supplier moves
    `SUSPENDED_PENDING_REVIEW -> APPROVED` ... but only when the action being closed
    was the last non-closed action on that supplier". The score itself is not
    rewritten by the closure: the failed audit weighing 3.00 and the passing sample
    weighing 2.00 both remain in the attested set.

    Design: Difficulty/compensating_invariant/blocked_pair_count_conservation
    """
    world = fx.reverified_after_decision(api, decision="IMPORT_SUSPENSION")

    fx.close_corrective_action(
        api,
        world.corrective_action_id,
        "CLOSE_RESOLVED",
        closure_note=RESOLVED_CLOSURE_NOTE,
    )

    assert_pair_dimensions(
        fx.get_pair(api, world.pair_id),
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
    )
    entry = fx.get_entry(api, world.entry_id)
    assert entry["status"] == "ACCEPTED"
    assert entry["held_reason"] is None
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id),
        final=46.00,
        weight_total=5.00,
        status="APPROVED",
    )


# --- The weight total goes out and comes back -------------------------------
def _attested_sample_with_one_finding(api: ApiClient) -> SimpleNamespace:
    """One attested PASS_WITH_FINDINGS sample: score 70.00 on weight total 2.00."""
    world = fx.sampling_only_program(api, frequency_per_year=2)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="PASS_WITH_FINDINGS",
        performed_start="2026-10-02T00:00:00Z",
        performed_end="2026-10-03T00:00:00Z",
        findings_count=1,
        document_reference="LAB-2026-1002-A",
    )
    world.record_id = record["id"]
    world.record = fx.attest_record(
        api,
        world.record_id,
        world.qi_b_id,
        attestation_note="Laboratory certificate reviewed and admitted with one finding",
    )
    return world


def test_rescinding_the_only_attested_record_restores_the_weight_total_to_zero(
    api: ApiClient,
) -> None:
    """The conserved weight total goes 0.00, 2.00, and exactly 0.00 again.

    "Rescinding an `ATTESTED` record moves it `ATTESTED -> RESCINDED` and recomputes
    the supplier's `performance_sample_weight_total` and `performance_score_final`
    with that record removed, restoring both to exactly the values they held before
    the attestation, and recomputes `adequacy_score_realized` for the record's
    combination." With nothing attested, "If the weight total is 0.00 the score is
    exactly 100.00 -- no evidence is not bad evidence".

    Design: Difficulty/compensating_invariant/performance_weight_conservation
    """
    world = _attested_sample_with_one_finding(api)
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id), final=70.00, weight_total=2.00
    )

    fx.rescind_record(api, world.record_id, world.qi_a_id)

    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id),
        provisional=100.00,
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )
    assert_money(
        fx.get_pair(api, world.pair_id)["adequacy_score_realized"],
        0.00,
        "adequacy_score_realized",
    )


def test_the_rescinded_record_leaves_the_availability_bucket_but_not_the_archive(
    api: ApiClient,
) -> None:
    """Its points survive as history while its retention bucket changes.

    "its `available_for_inspection` flag is true exactly when the record's
    `record_status` is not `RESCINDED`". "A rescinded record is counted in
    `retained_record_count` but is neither available nor expired, so the latter three
    buckets are mutually disjoint and only the first is a superset of them."

    Design: Difficulty/compensating_invariant/performance_weight_conservation
    """
    world = _attested_sample_with_one_finding(api)

    rescinded = fx.rescind_record(api, world.record_id, world.qi_a_id)

    assert rescinded["record_status"] == "RESCINDED"
    assert_money(rescinded["record_points"], 70.00, "record_points")
    assert rescinded["available_for_inspection"] is False
    package = fx.get_records_package(api, world.importer_id)
    assert package["retained_record_count"] == 1
    assert package["rescinded_record_count"] == 1
    assert package["available_for_inspection_count"] == 0
    assert package["expired_record_count"] == 0
