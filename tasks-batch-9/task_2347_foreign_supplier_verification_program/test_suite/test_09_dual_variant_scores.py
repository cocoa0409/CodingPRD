"""The two-variant scores: PROVISIONAL vs FINAL, and PLANNED vs REALIZED.

Both pairs of variants share one formula and differ only in which rows feed
them, so the gap between them is produced by input-set filtering alone.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_money,
    assert_pair_dimensions,
    assert_supplier_performance,
)
from test_helpers.test_users import make_qualified_individual_headers

# The canonical hazard picture of the mango pair: two hazards requiring control
# and one below the significance threshold.
CANONICAL_HAZARDS = [fx.HAZARD_LISTERIA, fx.HAZARD_PESTICIDE, fx.HAZARD_SALMONELLA]

FAIL_AUDIT_RECORD = dict(
    outcome="FAIL",
    performed_start="2026-09-12T00:00:00Z",
    performed_end="2026-09-14T00:00:00Z",
    findings_count=2,
    document_reference="AUD-2026-0912-RV",
)
PASS_AUDIT_RECORD = dict(
    outcome="PASS",
    performed_start="2026-09-12T00:00:00Z",
    performed_end="2026-09-14T00:00:00Z",
    findings_count=0,
    document_reference="AUD-2026-0912-RV",
)


def _verified_canonical(api: ApiClient):
    """Drive the mango pair all the way to a signed verification approval."""
    return fx.verified_program(api, hazards=CANONICAL_HAZARDS)


def test_unattested_fail_audit_scores_only_the_provisional_variant(api: ApiClient) -> None:
    """A merely received FAIL audit is scored, but not admitted anywhere.

    "Its `record_points` is the outcome points for its `outcome` -- 100 for
    `PASS`, 75 for `PASS_WITH_FINDINGS`, 20 for `FAIL` -- reduced by a findings
    penalty of 5 points per documented finding capped at 20 points in total",
    and the record's `weight` is the record type weight of the parent activity's
    type multiplied by a recency factor of 1.0 inside 365 days.

    Design: Difficulty/dual_variant_calc/supplier_performance_provisional_diverges_from_final_on_unattested_fail
    """
    world = _verified_canonical(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")

    response = api.create_verification_record(
        {"activity_id": world.activity_onsite["id"], **FAIL_AUDIT_RECORD},
        make_qualified_individual_headers(world.qi_a_id),
    )

    record = validate_success(response, 201)
    assert record["record_status"] == "RECEIVED"
    assert_money(record["record_points"], 10.00, "record_points")
    assert_money(record["weight"], 3.00, "weight")


def test_unattested_fail_audit_leaves_final_score_and_suspension_untouched(
    api: ApiClient,
) -> None:
    """Filing moves the advisory number and has no state effect at all.

    "Filing recomputes the supplier's `performance_score_provisional` and leaves
    `performance_score_final` untouched -- a merely received record moves the
    advisory number and has no state effect at all." The FINAL variant "takes
    only records whose `record_status` is `ATTESTED`", so its weight total is
    still 0.00 and the score is still exactly 100.00.

    Design: Difficulty/dual_variant_calc/supplier_performance_provisional_diverges_from_final_on_unattested_fail
    """
    world = _verified_canonical(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")

    fx.file_record(api, world.activity_onsite["id"], world.qi_a_id, **FAIL_AUDIT_RECORD)

    supplier = fx.get_supplier(api, world.supplier_id)
    assert_supplier_performance(
        supplier,
        provisional=10.00,
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )
    pair = fx.get_pair(api, world.pair_id)
    assert_pair_dimensions(
        pair,
        verification_status="VERIFICATION_APPROVED",
        entry_eligibility_status="ELIGIBLE",
    )


def test_attestation_admits_the_record_into_the_final_variant(api: ApiClient) -> None:
    """Attestation is the moment evidence becomes consequential.

    "**Hop 1**: the record moves `RECEIVED -> ATTESTED`, `attested_by_qi_id` is
    set to the attester's `X-User-ID`, and the supplier's
    `performance_score_final` and `performance_sample_weight_total` are
    recomputed over attested records only." One passing audit of weight 3.00
    keeps the score at 100.00 while publishing the weight total.

    Design: Difficulty/dual_variant_calc/pair_adequacy_planned_diverges_from_realized_after_one_attestation
    """
    world = _verified_canonical(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api, world.activity_onsite["id"], world.qi_a_id, **PASS_AUDIT_RECORD
    )

    response = api.post_record_attestation(
        record["id"],
        {"attestation_note": "Audit report reviewed against the approved activity scope"},
        make_qualified_individual_headers(world.qi_b_id),
    )

    attested = validate_success(response)
    assert attested["record_status"] == "ATTESTED"
    supplier = fx.get_supplier(api, world.supplier_id)
    assert_supplier_performance(supplier, final=100.00, weight_total=3.00)


def test_planned_adequacy_exceeds_realized_when_only_one_activity_has_evidence(
    api: ApiClient,
) -> None:
    """The realized input set is the attested subset of the planned one.

    The PLANNED variant "takes as its input set every activity on the
    combination whose `status` is `APPROVED`", while the REALIZED variant "takes
    as its input set the `APPROVED` activities that have at least one
    verification record with `record_status` `ATTESTED`". With three approved
    activities but attested evidence on the onsite audit alone, the two variants
    separate.

    Design: Difficulty/dual_variant_calc/pair_adequacy_planned_diverges_from_realized_after_one_attestation
    """
    world = _verified_canonical(api)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api, world.activity_onsite["id"], world.qi_a_id, **PASS_AUDIT_RECORD
    )
    fx.attest_record(
        api,
        record["id"],
        world.qi_b_id,
        attestation_note="Audit report reviewed against the approved activity scope",
    )

    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["required_coverage"], 40.58, "required_coverage")
    assert_money(pair["adequacy_score_planned"], 61.61, "adequacy_score_planned")
    assert_money(pair["adequacy_score_realized"], 24.64, "adequacy_score_realized")
    assert_pair_dimensions(pair, verification_status="VERIFICATION_APPROVED")
