"""
Immediate visibility: a scoring run's own response is already the settled state.

The receipt scoring run is the widest single write in the system — it writes eight ledger rows,
two tallies, four grid metrics, a score, a reconciled value, a variance and a status transition —
so it is the natural place to prove that a caller learns everything from the response it already
has. Every figure is read twice, once out of the writing response and once out of a follow-up
read, and the two must agree.
"""

from test_helpers import (
    DESK_REVIEWER_HEADERS,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

CLEAN_GRID = [
    {
        "street_address": "1 Alder Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Alder Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _unscored_report(api):
    """A delivered report with a clean three-comparable grid, not yet scored."""
    env = fx.panel_and_loan(
        api,
        amc={"name": "Immediate Visibility AMC"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-C712",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-C712",
            "borrower_display_name": "Mia Borrower",
        },
    )
    env["appraisal"] = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"]
    )
    fx.add_comparables(api, env["appraisal"]["id"], env["amc"]["id"], CLEAN_GRID)
    env["appraisal"] = fx.read_appraisal(api, env["appraisal"]["id"])
    return env


def _score(api, env):
    """Run the receipt checks and hand back the writing response's own body."""
    return validate_success(
        api.run_rule_checks(
            env["appraisal"]["id"],
            f.version_payload(env["appraisal"]["version"]),
            DESK_REVIEWER_HEADERS,
        )
    )


def test_the_scoring_run_returns_its_own_settled_state(api):
    """The writing response is the post-write representation, not a stale echo.

    The run clears the report and spends its guard token, and both facts are legible in the
    response the caller already holds: the status has already moved and the version has already
    advanced. The follow-up read is then compared field by field and must add nothing.

    PRD: "The `data` field contains the resource object or an array of resource objects. For 2xx
    responses with no data, it contains an empty object. Unless otherwise noted, operations that
    create or modify a resource will return the created or updated resource object in the data
    field."

    PRD: "The run then lands the review dimension: the appraisal moves to `RULES_CLEARED` when the
    fail count is zero, and to `RULES_FLAGGED` otherwise."

    PRD: "Each accepted run increments the appraisal's `version` by 1, and the very first run on an
    appraisal also seeds `current_value_cents` from `reported_value_cents`, establishing the
    baseline that every later value revision moves off."

    Design: Corner/consistency_model/immediate_visibility_rule_check_run_returns_the_post_write_state
    """
    env = _unscored_report(api)
    before = env["appraisal"]["version"]

    written = _score(api, env)
    assert written["review_status"] == "RULES_CLEARED"
    assert written["completeness_score_bps"] == 10000
    assert written["rule_check_fail_count"] == 0
    assert written["version"] == before + 1

    read_back = fx.read_appraisal(api, env["appraisal"]["id"])
    assert read_back["review_status"] == written["review_status"]
    assert read_back["completeness_score_bps"] == written["completeness_score_bps"]
    assert read_back["rule_check_fail_count"] == written["rule_check_fail_count"]
    assert read_back["version"] == written["version"]
    assert read_back["current_value_cents"] == written["current_value_cents"] == 40000000


def test_every_derived_grid_figure_is_populated_in_the_same_response(api):
    """The reconciled value, the variance and both adjustment ceilings arrive with the run.

    None of these fields existed on the delivered report — the specification starts them all at
    null or zero — so seeing them filled in the run's own body is what proves the write and its
    visibility are one step. The reconciled value is the per-comparable rounding order applied to
    39390000, 40000000 and 40590000 over three eligible sales, which lands on 39993333 rather
    than the 39993334 a sum-then-divide order would give; the variance against the reported
    40000000 is 2 basis points; and each sale carries adjustments of exactly one percent of its
    own price, so both ceilings sit at 100 basis points.

    PRD: "In addition to the eight rows and the two tallies, the run writes
    `completeness_score_bps`, refreshes `eligible_comp_count` and `closed_comp_count`, and writes
    `max_gross_adjustment_bps`, `max_net_adjustment_bps`, `indicated_value_cents`, and
    `variance_vs_reported_bps`."

    PRD: "Otherwise the reconciled indicated value is built with a **pinned rounding order**: take
    the eligible comparables in ascending `created_at` order, divide each one's
    `adjusted_price_cents` by the number of eligible comparables, round *that per-comparable
    quotient* half-up to whole cents, and then add the rounded quotients together."

    Design: Corner/consistency_model/immediate_visibility_rule_check_run_returns_the_post_write_state
    """
    env = _unscored_report(api)
    assert env["appraisal"]["indicated_value_cents"] is None
    assert env["appraisal"]["max_gross_adjustment_bps"] == 0

    written = _score(api, env)
    assert written["eligible_comp_count"] == 3
    assert written["closed_comp_count"] == 3
    assert written["indicated_value_cents"] == 39993333
    assert written["variance_vs_reported_bps"] == 2
    assert written["max_gross_adjustment_bps"] == 100
    assert written["max_net_adjustment_bps"] == 100

    read_back = fx.read_appraisal(api, env["appraisal"]["id"])
    for field in (
        "eligible_comp_count",
        "closed_comp_count",
        "indicated_value_cents",
        "variance_vs_reported_bps",
        "max_gross_adjustment_bps",
        "max_net_adjustment_bps",
    ):
        assert read_back[field] == written[field]


def test_the_whole_check_ledger_is_readable_on_the_first_read_after_the_run(api):
    """All eight rows are already there, in emission order, on the very next request.

    There is no partially written ledger to observe: the first listing after the run returns the
    complete set of eight positions in ascending sequence, every one of them passing on this
    clean grid, and the tallies on the appraisal agree with what the rows say.

    PRD: "Each row records the parent `appraisal_id`, its `sequence_no` from 1 through 8, its
    `check_code`, its `outcome` of `PASS`, `WARN`, or `FAIL`, the `observed_value` as a string
    capturing the metric that produced the outcome, and a human-readable `detail` explaining it."

    PRD: "Two list endpoints layer an additional guarantee on top of creation order: the
    rule-check listing and the bias-flag listing return their rows in the fixed emission order the
    producing run wrote them in, which for rule checks is ascending `sequence_no` and for bias
    flags is the flag emission order described in §3.5."

    Design: Corner/consistency_model/immediate_visibility_rule_check_run_returns_the_post_write_state
    """
    env = _unscored_report(api)
    written = _score(api, env)

    rows, meta = validate_paginated(
        api.list_rule_checks(
            env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 8
    assert meta["has_more"] is False
    assert [row["sequence_no"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [row["outcome"] for row in rows] == ["PASS"] * 8
    assert all(row["appraisal_id"] == env["appraisal"]["id"] for row in rows)
    assert all(isinstance(row["observed_value"], str) for row in rows)

    assert written["rule_check_fail_count"] == 0
    assert written["rule_check_warn_count"] == 0
