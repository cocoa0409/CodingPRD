"""Quality measure scoring: rate, decile points, correction loop, lockdown gates."""
from test_helpers import (
    ADMIN, ApiErrorId, build_pipeline, create_quality_result_payload,
    report_quality, set_clock, setup_org, single_member_journey,
    validate_error, validate_success,
)
from test_helpers import CLOCK_RECONCILE, SINGLE_MEASURE_CATALOG


def test_quality_result_validate_correction_loop(api, quality_analyst_headers):
    """PRD §3.8: "Validation (`REPORTED → VALIDATED`) computes two derived fields. The `rate_bp` is the result's `numerator_count` multiplied by 10000 and divided by `denominator_count`, rounded half-up to a whole basis point. The `achievement_points` is the count of the measure's nine decile thresholds from the contract catalog that the `rate_bp` meets or exceeds — an integer from 0 to 9, with the comparison pinned as greater-than-or-equal."
    PRD §3.8: "From `VALIDATED` the analyst may return the result for correction (`VALIDATED → REPORTED`), which clears `rate_bp` and `achievement_points` back to null; this is permitted while the year is in `SETUP`, `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` once it has advanced past those). Also from `VALIDATED`, the analyst may lock the result (`VALIDATED → LOCKED`), permitted while the year is in `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` outside that window)."

    Design: Difficulty/non_linear_state_machine/quality_result_validate_correction_loop
    """
    org = setup_org(member_specs=[], practice_count=0)
    pipe = build_pipeline(
        org, stage="OPEN", attributions=[],
        contract_overrides={"quality_measures": SINGLE_MEASURE_CATALOG},
    )
    year_id = pipe["year"]["id"]

    created = api.create_quality_result(
        create_quality_result_payload(year_id, numerator_count=350, denominator_count=1000),
        quality_analyst_headers,
    )
    result = validate_success(created, 201)
    assert result["result_status"] == "REPORTED"
    assert result["rate_bp"] is None
    assert result["achievement_points"] is None

    first = validate_success(api.validate_quality_result(result["id"], quality_analyst_headers))
    assert first["result_status"] == "VALIDATED"
    assert first["rate_bp"] == 3500
    assert first["achievement_points"] == 3

    returned = validate_success(
        api.return_quality_result_for_correction(result["id"], quality_analyst_headers)
    )
    assert returned["result_status"] == "REPORTED"
    assert returned["rate_bp"] is None, "the loop edge clears computed scoring"
    assert returned["achievement_points"] is None

    second = validate_success(api.validate_quality_result(result["id"], quality_analyst_headers))
    assert second["result_status"] == "VALIDATED"
    assert second["rate_bp"] == 3500, "revalidation recomputes identically"
    assert second["achievement_points"] == 3

    locked = validate_success(api.lock_quality_result(result["id"], quality_analyst_headers))
    assert locked["result_status"] == "LOCKED"


def test_quality_result_double_correction_recomputes_identically(api, quality_analyst_headers):
    """PRD §3.8: "From `VALIDATED` the analyst may return the result for correction (`VALIDATED → REPORTED`), which clears `rate_bp` and `achievement_points` back to null; this is permitted while the year is in `SETUP`, `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` once it has advanced past those)."
    PRD §3.8: "Validation (`REPORTED → VALIDATED`) computes two derived fields. The `rate_bp` is the result's `numerator_count` multiplied by 10000 and divided by `denominator_count`, rounded half-up to a whole basis point."

    Design: Difficulty/non_linear_state_machine/quality_result_validate_correction_loop
    """
    org = setup_org(member_specs=[], practice_count=0)
    pipe = build_pipeline(
        org, stage="OPEN", attributions=[],
        contract_overrides={"quality_measures": SINGLE_MEASURE_CATALOG},
    )
    year_id = pipe["year"]["id"]
    result = validate_success(api.create_quality_result(
        create_quality_result_payload(year_id, numerator_count=350, denominator_count=1000),
        quality_analyst_headers,
    ), 201)

    for _ in range(2):
        validated = validate_success(api.validate_quality_result(result["id"], quality_analyst_headers))
        assert validated["rate_bp"] == 3500
        assert validated["achievement_points"] == 3
        returned = validate_success(
            api.return_quality_result_for_correction(result["id"], quality_analyst_headers)
        )
        assert returned["rate_bp"] is None
        assert returned["achievement_points"] is None

    final = validate_success(api.validate_quality_result(result["id"], quality_analyst_headers))
    assert final["rate_bp"] == 3500 and final["achievement_points"] == 3
    locked = validate_success(api.lock_quality_result(result["id"], quality_analyst_headers))
    assert locked["result_status"] == "LOCKED"


def test_decile_threshold_exact_rate_counts_point(api, quality_analyst_headers):
    """PRD §3.8: "The `achievement_points` is the count of the measure's nine decile thresholds from the contract catalog that the `rate_bp` meets or exceeds — an integer from 0 to 9, with the comparison pinned as greater-than-or-equal."
    PRD §3.8: "The `rate_bp` is the result's `numerator_count` multiplied by 10000 and divided by `denominator_count`, rounded half-up to a whole basis point."

    Design: Difficulty/boundary_precision_check/decile_threshold_exact_rate_counts_point
    """
    org = setup_org(member_specs=[], practice_count=0)
    pipe = build_pipeline(org, stage="OPEN", attributions=[])
    year_id = pipe["year"]["id"]
    exact = validate_success(api.create_quality_result(
        create_quality_result_payload(
            year_id, measure_code="HBA1C", numerator_count=300, denominator_count=1000
        ),
        quality_analyst_headers,
    ), 201)
    validated = validate_success(api.validate_quality_result(exact["id"], quality_analyst_headers))
    assert validated["rate_bp"] == 3000
    # rate 3000 meets thresholds 1000, 2000 and (via >=) the 3000 threshold
    assert validated["achievement_points"] == 3


def test_decile_threshold_one_bp_below_misses_point(api, quality_analyst_headers):
    """PRD §3.8: "The `achievement_points` is the count of the measure's nine decile thresholds from the contract catalog that the `rate_bp` meets or exceeds — an integer from 0 to 9, with the comparison pinned as greater-than-or-equal."

    Design: Difficulty/boundary_precision_check/decile_threshold_exact_rate_counts_point
    """
    org = setup_org(member_specs=[], practice_count=0)
    pipe = build_pipeline(org, stage="OPEN", attributions=[])
    year_id = pipe["year"]["id"]
    below = validate_success(api.create_quality_result(
        create_quality_result_payload(
            year_id, measure_code="HBA1C", numerator_count=299, denominator_count=1000
        ),
        quality_analyst_headers,
    ), 201)
    validated = validate_success(api.validate_quality_result(below["id"], quality_analyst_headers))
    assert validated["rate_bp"] == 2990
    assert validated["achievement_points"] == 2, "one bp below the third threshold loses the point"


def test_quality_lock_from_reported_rejected(api, quality_analyst_headers):
    """PRD §3.8: "Also from `VALIDATED`, the analyst may lock the result (`VALIDATED → LOCKED`), permitted while the year is in `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` outside that window)."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Corner/state_machines/quality_lock_from_reported_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    pipe = build_pipeline(org, stage="OPEN", attributions=[])
    result = report_quality(
        pipe["year"]["id"], "HBA1C", 350, 1000, validate=False, lock=False
    )
    assert result["result_status"] == "REPORTED"
    resp = api.lock_quality_result(result["id"], quality_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reread = validate_success(api.get_quality_result(result["id"], quality_analyst_headers))
    assert reread["result_status"] == "REPORTED"


def test_begin_reconciliation_with_unlocked_quality_rejected(api, payer_admin_headers, quality_analyst_headers):
    """PRD §3.4: "From `MEASURING` the admin begins reconciliation (`MEASURING → RECONCILING`); this is gated by three preconditions evaluated together — the logical clock date must be at or after `period_end` (`ERR_MEASUREMENT_PERIOD_NOT_ENDED`), the year's `total_member_months` must be strictly positive (`ERR_EMPTY_POPULATION`), and every `QualityMeasureResult` of the year must be in either `LOCKED` or `EXCLUDED` (`ERR_QUALITY_RESULTS_UNLOCKED`)."
    PRD §3.8: "Also from `VALIDATED`, the analyst may lock the result (`VALIDATED → LOCKED`), permitted while the year is in `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` outside that window)."

    Design: Corner/state_machines/begin_reconciliation_with_unlocked_quality_rejected
    """
    pipe = single_member_journey(stage="MEASURING", quality_lock=False)
    year_id = pipe["year"]["id"]
    result = pipe["quality"][0]
    assert result["result_status"] == "VALIDATED"

    set_clock(CLOCK_RECONCILE)
    blocked = api.begin_reconciliation(year_id, payer_admin_headers)
    validate_error(blocked, ApiErrorId.ERR_QUALITY_RESULTS_UNLOCKED)

    validate_success(api.lock_quality_result(result["id"], quality_analyst_headers))
    opened = api.begin_reconciliation(year_id, payer_admin_headers)
    assert validate_success(opened)["year_status"] == "RECONCILING"
