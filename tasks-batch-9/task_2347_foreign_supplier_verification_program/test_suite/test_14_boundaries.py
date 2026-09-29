"""Three thresholds probed at the exact value that decides them.

One inclusive score threshold, one strict score threshold, and one inclusive
date threshold, each with the neighbouring value on the other side.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_hazard_scores,
    assert_importer_rollup,
    assert_money,
    assert_supplier_performance,
)
from test_helpers.factories import attestation_payload, hazard_payload
from test_helpers.test_users import make_qualified_individual_headers

# On a GENERAL, non-raw, not-ready-to-eat food every optional multiplier is 1.00.
AT_THRESHOLD_HAZARD = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Salmonella in dry commodity",
    severity=4,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)
BELOW_THRESHOLD_HAZARD = dict(
    hazard_type="PHYSICAL",
    hazard_name="Metal fragments from milling",
    severity=2,
    probability=5,
    control_owner="SUPPLIER_OF_SUPPLIER",
)


def _plain_food_draft_analysis(api: ApiClient) -> SimpleNamespace:
    """A draft analysis on a food that neutralises every optional multiplier."""
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"], approve_by_qi_id=qi_a["id"])
    food = fx.create_plain_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    analysis = fx.create_hazard_analysis(
        api,
        pair["id"],
        qi_a["id"],
        methodology_note="Dry commodity hazard identification for a non ready to eat food",
    )
    return SimpleNamespace(
        importer_id=importer["id"],
        qi_a_id=qi_a["id"],
        pair_id=pair["id"],
        analysis_id=analysis["id"],
    )


def test_hazard_scoring_exactly_twelve_requires_control_and_eleven_does_not(
    api: ApiClient,
) -> None:
    """The significance boundary is inclusive on one side and excludes the other.

    "A hazard's `requires_control` flag is true exactly when its `risk_score` is
    at or above 12.00 -- the boundary is inclusive, so a hazard scoring exactly
    12.00 *is* a significant hazard requiring a control." The control factor is
    1.00 for a foreign supplier and 1.10 for a supplier of the supplier, which is
    what separates 12.00 from 11.00 here.

    Design: Difficulty/boundary_precision_check/hazard_score_exactly_twelve_is_significant
    """
    world = _plain_food_draft_analysis(api)
    headers = make_qualified_individual_headers(world.qi_a_id)

    at_boundary = validate_success(
        api.create_hazard(world.analysis_id, hazard_payload(**AT_THRESHOLD_HAZARD), headers),
        201,
    )
    below_boundary = validate_success(
        api.create_hazard(
            world.analysis_id, hazard_payload(**BELOW_THRESHOLD_HAZARD), headers
        ),
        201,
    )

    assert_hazard_scores(at_boundary, 12.00, requires_control=True)
    assert_hazard_scores(below_boundary, 11.00, requires_control=False)


def test_only_the_significant_hazard_is_counted_but_both_are_totalled(
    api: ApiClient,
) -> None:
    """The sub-threshold hazard still contributes to the analysis total.

    "Because only controlled-significant hazards enter the hazard load, a hazard
    scoring below 12.00 contributes to the analysis's `risk_total` but not to the
    combination's composite risk."

    Design: Difficulty/boundary_precision_check/hazard_score_exactly_twelve_is_significant
    """
    world = _plain_food_draft_analysis(api)
    fx.add_hazard(api, world.analysis_id, world.qi_a_id, **AT_THRESHOLD_HAZARD)
    fx.add_hazard(api, world.analysis_id, world.qi_a_id, **BELOW_THRESHOLD_HAZARD)

    analysis = fx.get_analysis(api, world.analysis_id)
    assert analysis["hazard_count"] == 2
    assert analysis["significant_hazard_count"] == 1
    assert_money(analysis["risk_total"], 23.00, "risk_total")


# --- Exactly 60.00 is not below 60.00 --------------------------------------
def _one_attested_pass_and_one_pending_fail(api: ApiClient) -> SimpleNamespace:
    """An attested passing sample, plus a failing sample awaiting attestation."""
    world = fx.sampling_only_program(api, frequency_per_year=2)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    passing = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-10-02T00:00:00Z",
        performed_end="2026-10-03T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1002-A",
    )
    fx.attest_record(
        api,
        passing["id"],
        world.qi_b_id,
        attestation_note="Laboratory certificate reviewed and admitted",
    )
    world.failing = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2026-10-05T00:00:00Z",
        performed_end="2026-10-06T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1005-B",
    )
    world.failing_id = world.failing["id"]
    return world


def test_final_score_of_exactly_sixty_is_reached_by_the_weighted_average(
    api: ApiClient,
) -> None:
    """A clean pass and a clean failure average to the threshold value itself.

    "Its `record_points` is the outcome points for its `outcome` -- 100 for
    `PASS`, 75 for `PASS_WITH_FINDINGS`, 20 for `FAIL`". "the weighted sum is the
    sum of each record's `record_points` multiplied by its `weight`, rounded half
    up to two decimal places", divided by the weight total.

    Design: Difficulty/boundary_precision_check/performance_score_exactly_sixty_does_not_suspend
    """
    world = _one_attested_pass_and_one_pending_fail(api)

    response = api.post_record_attestation(
        world.failing_id,
        attestation_payload(
            attestation_note="Second laboratory certificate reviewed and admitted"
        ),
        make_qualified_individual_headers(world.qi_b_id),
    )

    record = validate_success(response)
    assert_money(record["record_points"], 20.00, "record_points")
    assert_money(record["weight"], 2.00, "weight")
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id), final=60.00, weight_total=4.00
    )


def test_final_score_of_exactly_sixty_does_not_suspend_the_supplier(
    api: ApiClient,
) -> None:
    """Nothing cascades, because the comparison is strict.

    "The threshold is strict: a final score of exactly 60.00 leaves the supplier
    approved." With no suspension there is no lapse, so no corrective action is
    synthesised and the programme stays clean.

    Design: Difficulty/boundary_precision_check/performance_score_exactly_sixty_does_not_suspend
    """
    world = _one_attested_pass_and_one_pending_fail(api)

    fx.attest_record(
        api,
        world.failing_id,
        world.qi_b_id,
        attestation_note="Second laboratory certificate reviewed and admitted",
    )

    assert fx.get_supplier(api, world.supplier_id)["status"] == "APPROVED"
    assert fx.list_corrective_actions(api, supplier_id=world.supplier_id) == []
    assert fx.get_pair(api, world.pair_id)["verification_status"] == "HAZARD_ANALYZED"
    assert_importer_rollup(
        fx.get_importer(api, world.importer_id), program_status="COMPLIANT"
    )


# --- The retention date counts on the day it falls due ----------------------
def _attested_record_retained_until_october_2028(api: ApiClient) -> SimpleNamespace:
    """One attested sampling record performed on 2026-10-10 under 24-month retention."""
    world = fx.sampling_only_program(api, frequency_per_year=2)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    record = fx.file_record(
        api,
        world.activity_id,
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-10-08T00:00:00Z",
        performed_end="2026-10-10T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1008-C",
    )
    world.record = fx.attest_record(
        api,
        record["id"],
        world.qi_b_id,
        attestation_note="Laboratory certificate reviewed and admitted",
    )
    world.record_id = record["id"]
    return world


def test_records_package_at_the_retention_instant_still_counts_the_record(
    api: ApiClient,
) -> None:
    """An inspection dated exactly on the retention date still sees the record.

    "Every verification record's `retained_until` is its `performed_end` advanced
    by the importer's `record_retention_months` in calendar months". "The
    retention boundary is
    inclusive: an evaluation instant exactly equal to `retained_until` still
    counts as available."

    Design: Difficulty/boundary_precision_check/retention_as_of_equal_to_retained_until_is_still_available
    """
    world = _attested_record_retained_until_october_2028(api)

    package = fx.get_records_package(
        api, world.importer_id, as_of_iso8601="2028-10-10T00:00:00Z"
    )

    assert fx.get_record(api, world.record_id)["retained_until"].startswith(
        "2028-10-10T00:00:00"
    )
    assert package["available_for_inspection_count"] == 1
    assert package["expired_record_count"] == 0
    assert package["retained_record_count"] == 1
    assert package["rescinded_record_count"] == 0


def test_records_package_one_second_later_counts_the_record_as_expired(
    api: ApiClient,
) -> None:
    """One second past the boundary moves the record into the expired bucket.

    "`expired_record_count`, the number of non-rescinded records whose
    `retained_until` is strictly before the evaluation instant". A record always
    remains inside "`retained_record_count`, the number of records regardless of
    status".

    Design: Difficulty/boundary_precision_check/retention_as_of_equal_to_retained_until_is_still_available
    """
    world = _attested_record_retained_until_october_2028(api)

    package = fx.get_records_package(
        api, world.importer_id, as_of_iso8601="2028-10-10T00:00:01Z"
    )

    assert package["available_for_inspection_count"] == 0
    assert package["expired_record_count"] == 1
    assert package["retained_record_count"] == 1
