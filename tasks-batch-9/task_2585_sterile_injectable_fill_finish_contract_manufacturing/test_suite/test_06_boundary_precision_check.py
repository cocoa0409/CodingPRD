"""Verdict boundaries that sit exactly on a tolerance.

Fill-weight tolerances are compared after a four-place half-up rounding, and the
visual acceptable quality limit is compared as an exact ratio, so the values
chosen here land precisely on the edges the specification names.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from test_helpers import constants, fixtures, validate_paginated
from test_helpers.test_users import PRODUCTION_SUPERVISOR

Json = Dict[str, Any]


def _deviation_pct(check: Json) -> Decimal:
    return Decimal(str(check["max_absolute_deviation_pct"]))


# ---------------------------------------------------------------------------
# Design instance: fill_weight_deviation_half_up_tie_and_strict_reject_boundary
# ---------------------------------------------------------------------------
def _filling_batch_at_twenty_grams(api) -> Json:
    """A batch in FILLING whose project declares a 20000 mg target fill weight."""
    return fixtures.build_program(
        api, stage=fixtures.STAGE_FILLING, target_fill_weight_mg=20000
    )


def test_fill_weight_rounding_tie_is_resolved_upward_into_the_alert_band(api):
    """A raw 0.02995 deviation rounds to 0.03 and is therefore an ALERT.

    PRD 3.6: "That rounded figure is then compared against two tolerances, and the comparison happens *after* the rounding: a deviation strictly greater than 0.0500 gives a `result` of `FAIL`, a deviation of at least 0.0300 but not greater than 0.0500 gives `ALERT`, and anything below 0.0300 gives `PASS`."

    Design: Difficulty/boundary_precision_check/fill_weight_deviation_half_up_tie_and_strict_reject_boundary
    """
    program = _filling_batch_at_twenty_grams(api)

    below = fixtures.record_fill_weight_check(
        api,
        program["batch_id"],
        measured_fill_weights_mg=[20000, 20598, 19700],
        sample_size=5,
        destructive_sample_units=5,
    )
    assert _deviation_pct(below) == Decimal("0.0299")
    assert below["result"] == "PASS"

    tie = fixtures.record_fill_weight_check(
        api,
        program["batch_id"],
        measured_fill_weights_mg=[20599, 20000, 19900],
        sample_size=5,
        destructive_sample_units=5,
    )
    assert _deviation_pct(tie) == Decimal(str(constants.FILL_WEIGHT_ALERT_FLOOR))
    assert tie["result"] == "ALERT"
    assert tie["result"] != "PASS"


def test_fill_weight_reject_boundary_is_strict_at_five_percent(api):
    """Exactly 0.05 is still an ALERT and only 0.051 fails.

    PRD 3.6: "For a `FILL_WEIGHT` check the server reaches the owning project's `target_fill_weight_mg` through the batch, computes for each measurement in `measured_fill_weights_mg` the absolute difference between that measurement and the target divided by the target, takes the largest such relative deviation, and rounds it half up to four decimal places into `max_absolute_deviation_pct`."

    Design: Difficulty/boundary_precision_check/fill_weight_deviation_half_up_tie_and_strict_reject_boundary
    """
    program = _filling_batch_at_twenty_grams(api)

    on_boundary = fixtures.record_fill_weight_check(
        api,
        program["batch_id"],
        measured_fill_weights_mg=[21000, 19700],
        sample_size=5,
        destructive_sample_units=5,
    )
    assert _deviation_pct(on_boundary) == Decimal(
        str(constants.FILL_WEIGHT_FAIL_CEILING)
    )
    assert on_boundary["result"] == "ALERT"
    assert on_boundary["result"] != "FAIL"

    above_boundary = fixtures.record_fill_weight_check(
        api,
        program["batch_id"],
        measured_fill_weights_mg=[21020],
        sample_size=5,
        destructive_sample_units=5,
    )
    assert _deviation_pct(above_boundary) == Decimal("0.0510")
    assert above_boundary["result"] == "FAIL"

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["production_status"] == "FILLING"


# ---------------------------------------------------------------------------
# Design instance: visual_aql_exact_rational_equality_versus_cci_zero_defect
# ---------------------------------------------------------------------------
def test_visual_aql_is_an_inclusive_exact_ratio_boundary(api):
    """199 rejects in 8000 passes and 200 in 8000 fails on the nose.

    PRD 3.6: "For a `VISUAL_INSPECTION` check, `max_absolute_deviation_pct` is likewise 0 and the defect rate is `reject_unit_count` divided by `sample_size`, evaluated as an exact ratio and deliberately *not* pre-rounded: a defect rate at or above the acceptable quality limit of 0.0250 gives `FAIL`, and anything below it gives `PASS`."

    Design: Difficulty/boundary_precision_check/visual_aql_exact_rational_equality_versus_cci_zero_defect
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)

    below = fixtures.record_visual_check(
        api, program["batch_id"], sample_size=8000, reject_unit_count=199
    )
    assert below["result"] == "PASS"

    on_limit = fixtures.record_visual_check(
        api, program["batch_id"], sample_size=8000, reject_unit_count=200
    )
    assert on_limit["result"] == "FAIL"
    assert _deviation_pct(on_limit) == Decimal(0)
    assert Decimal(200) / Decimal(8000) == Decimal(str(constants.VISUAL_AQL))


def test_cci_is_zero_defect_with_no_alert_band(api):
    """A single container-closure reject fails outright.

    PRD 3.6: "For a `CCI` check, `max_absolute_deviation_pct` is 0 and the control is zero-defect: a `reject_unit_count` of at least 1 gives `FAIL`, and only a `reject_unit_count` of 0 gives `PASS` — there is no `ALERT` band for container closure integrity."

    Design: Difficulty/boundary_precision_check/visual_aql_exact_rational_equality_versus_cci_zero_defect
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)

    fixtures.record_visual_check(
        api, program["batch_id"], sample_size=8000, reject_unit_count=200
    )
    clean = fixtures.record_cci_check(
        api, program["batch_id"], sample_size=200, reject_unit_count=0,
        destructive_sample_units=200,
    )
    assert clean["result"] == "PASS"

    defective = fixtures.record_cci_check(
        api, program["batch_id"], sample_size=200, reject_unit_count=1,
        destructive_sample_units=200,
    )
    assert defective["result"] == "FAIL"
    assert _deviation_pct(defective) == Decimal(0)

    rows, _meta = validate_paginated(
        api.list_in_process_checks(
            PRODUCTION_SUPERVISOR,
            {"batch_order_id": program["batch_id"], "result": "FAIL"},
        )
    )
    assert len(rows) == 2

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["production_status"] == "FILLING"
