"""Shift reporting: the per-line cost roll, the regrind ceiling and parts conservation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_production_report_payload,
    job_version,
    post_report,
    read_job,
    read_lot,
    setup_running_job,
    validate_error,
    validate_paginated,
    validate_success,
)

PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]

ROUNDING_PRESS = {"press_code": "P-725", "hourly_rate_cents": 7250}
ROUNDING_QUOTE = {"resin_price_cents_per_kg": 213}
HALF_CENT_LINE = {
    "shots": 10,
    "short_shot_shots": 0,
    "good_parts": 38,
    "scrap_parts": 2,
    "virgin_grams": 1200,
    "regrind_grams": 300,
    "run_minutes": 7,
}


def test_a_report_line_rounds_its_machine_and_material_cost_once_at_the_line(api):
    """PRD §3.7: "Each report line carries its own `report_direct_cost_cents`,
    computed as the machine burden — `run_minutes` multiplied by the press's
    `hourly_rate_cents`, divided by the 60 minutes in an hour, rounded half up —
    plus the material cost — the sum of `virgin_grams` and `regrind_grams`,
    multiplied by the quote's `resin_price_cents_per_kg`, divided by the 1,000 grams
    in a kilogram, rounded half up."

    Design: Difficulty/combinatorial_formula/job_cost_roll_rounds_per_report_line_then_sums
    """
    shop = setup_running_job(
        press_overrides=ROUNDING_PRESS,
        quote_overrides=ROUNDING_QUOTE,
        mold_overrides={"mold_code": "M-2"},
        job_overrides={"planned_qty": 40},
        lot_overrides={"supplier_lot_code": "L-88"},
    )

    report = validate_success(
        api.create_production_report(
            create_production_report_payload(
                shop["job"]["id"], job_version(shop["job"]["id"]), **HALF_CENT_LINE
            ),
            PE,
        ),
        201,
    )

    assert report["report_direct_cost_cents"] == 1166, (
        "846 cents of machine burden plus 320 cents of material, each rounded at the line"
    )


def test_the_job_direct_cost_sums_already_rounded_lines_not_raw_inputs(api):
    """PRD §3.7: "The job's `job_direct_cost_cents` is then the sum of those
    **already-rounded** line figures. Rounding per line and then summing is the
    rule; summing raw minutes and raw grams and rounding once at the end is
    explicitly not the rule, and the two produce different totals whenever two or
    more lines each carry a half-cent fraction."
    PRD §3.7: "The overhead tier is keyed on `job_direct_cost_cents` **before** any
    overhead is added: a direct cost below 500,000 cents takes 3,500 basis points, a
    direct cost from 500,000 up to but not including 2,000,000 cents takes 2,800
    basis points, and a direct cost of 2,000,000 cents or more takes 2,200 basis
    points. `job_overhead_cents` is `job_direct_cost_cents` multiplied by that
    basis-point rate, divided by 10,000, rounded half up, and `job_total_cost_cents`
    is simply `job_direct_cost_cents` plus `job_overhead_cents`."

    Design: Difficulty/combinatorial_formula/job_cost_roll_rounds_per_report_line_then_sums
    """
    shop = setup_running_job(
        press_overrides=ROUNDING_PRESS,
        quote_overrides=ROUNDING_QUOTE,
        mold_overrides={"mold_code": "M-2"},
        job_overrides={"planned_qty": 40},
        lot_overrides={"supplier_lot_code": "L-88"},
    )

    first = post_report(shop["job"]["id"], **HALF_CENT_LINE)
    second = post_report(shop["job"]["id"], **HALF_CENT_LINE)

    assert first["report_direct_cost_cents"] == 1166
    assert second["report_direct_cost_cents"] == 1166
    job = read_job(shop["job"]["id"])
    assert job["job_direct_cost_cents"] == 2332
    assert job["job_direct_cost_cents"] != 2331, (
        "summing the raw 14 minutes and 3000 grams and rounding once would give 2331"
    )
    assert job["job_overhead_cents"] == 816
    assert job["job_total_cost_cents"] == 3148
    assert job["cumulative_regrind_bp"] == 2000


def test_regrind_landing_exactly_on_the_approved_ceiling_is_accepted(api):
    """PRD §3.7: "The report's own **instantaneous** ratio, stored as
    `instantaneous_regrind_bp`, is `regrind_grams` multiplied by 10,000, divided by
    the sum of `virgin_grams` and `regrind_grams`, rounded half up; when that sum is
    zero the ratio is zero."
    PRD §3.7: "Both gates compare with a ceiling that is inclusive — a ratio landing
    exactly on the limit is accepted — and the instantaneous gate is evaluated
    **first**, with the cumulative gate consulted only if the instantaneous one
    passes. Either failure is reported as `ERR_REGRIND_RATIO_EXCEEDED`. On success
    the cumulative figure is written to the job's `cumulative_regrind_bp`."
    PRD §3.7: "When the tool's `approved_max_regrind_bp` is set, that is the limit;
    when it is still unset — the tool has never carried an approved or
    interim-approved package — the shop's default ceiling of 1,500 basis points,
    fifteen percent, applies instead."

    Design: Difficulty/boundary_precision_check/regrind_ratio_exactly_at_limit_passes_and_one_bp_over_fails
    """
    shop = setup_running_job()

    report = validate_success(
        api.create_production_report(
            create_production_report_payload(
                shop["job"]["id"],
                job_version(shop["job"]["id"]),
                shots=1000,
                short_shot_shots=10,
                good_parts=3900,
                scrap_parts=100,
                virgin_grams=32000,
                regrind_grams=8000,
                run_minutes=700,
            ),
            PE,
        ),
        201,
    )

    assert report["instantaneous_regrind_bp"] == 2000, (
        "8000 grams of regrind in 40000 grams of total mass is exactly 2000 basis points"
    )
    assert read_job(shop["job"]["id"])["cumulative_regrind_bp"] == 2000


def test_regrind_two_basis_points_over_the_ceiling_is_rejected(api):
    """PRD §3.7: "Both gates compare with a ceiling that is inclusive — a ratio
    landing exactly on the limit is accepted — and the instantaneous gate is
    evaluated **first**, with the cumulative gate consulted only if the
    instantaneous one passes. Either failure is reported as
    `ERR_REGRIND_RATIO_EXCEEDED`."
    PRD §3.5: "At every point in time, `qty_grams_remaining` equals the received
    kilograms multiplied by 1,000, minus the sum of `virgin_grams` over every
    non-reversed shift report whose `resin_lot_id` points at that lot."

    Design: Difficulty/boundary_precision_check/regrind_ratio_exactly_at_limit_passes_and_one_bp_over_fails
    """
    shop = setup_running_job()
    post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=10,
        good_parts=3900,
        scrap_parts=100,
        virgin_grams=32000,
        regrind_grams=8000,
        run_minutes=700,
    )

    response = api.create_production_report(
        create_production_report_payload(
            shop["job"]["id"],
            job_version(shop["job"]["id"]),
            shots=100,
            short_shot_shots=2,
            good_parts=390,
            scrap_parts=10,
            virgin_grams=3999,
            regrind_grams=1001,
            run_minutes=70,
        ),
        PE,
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_REGRIND_RATIO_EXCEEDED.value)
    job = read_job(shop["job"]["id"])
    assert job["total_shots"] == 1000
    assert job["parts_molded_total"] == 4000
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 468000


def test_a_report_whose_parts_do_not_conserve_is_rejected(api):
    """PRD §3.7: "`good_parts` plus `scrap_parts` must equal `shots` multiplied by
    the tool's `cavity_count`, and `scrap_parts` must be at least
    `short_shot_shots` multiplied by `cavity_count`, since a short shot cannot yield
    a good part in any cavity. A failure of either is rejected with
    `ERR_PARTS_BALANCE_MISMATCH`."

    Design: Corner/validations/parts_balance_mismatch_rejects_the_report
    """
    shop = setup_running_job()
    version = job_version(shop["job"]["id"])

    unbalanced = api.create_production_report(
        create_production_report_payload(
            shop["job"]["id"],
            version,
            shots=1000,
            short_shot_shots=5,
            good_parts=3900,
            scrap_parts=50,
            virgin_grams=36000,
            regrind_grams=4000,
            run_minutes=600,
        ),
        PE,
    )
    assert unbalanced.status_code == 422, f"Expected 422, got {unbalanced.status_code}"
    validate_error(unbalanced, ApiErrorId.ERR_PARTS_BALANCE_MISMATCH.value)

    too_little_scrap = api.create_production_report(
        create_production_report_payload(
            shop["job"]["id"],
            version,
            shots=1000,
            short_shot_shots=5,
            good_parts=3990,
            scrap_parts=10,
            virgin_grams=36000,
            regrind_grams=4000,
            run_minutes=600,
        ),
        PE,
    )
    assert too_little_scrap.status_code == 422, f"Expected 422, got {too_little_scrap.status_code}"
    validate_error(too_little_scrap, ApiErrorId.ERR_PARTS_BALANCE_MISMATCH.value)

    assert read_job(shop["job"]["id"])["total_shots"] == 0
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 500000


def test_posting_with_a_stale_job_version_is_rejected_and_retries_cleanly(api):
    """PRD §2.5: "Posting a shift report requires `expected_job_version` matching
    the target job's current `version`. A mismatch is rejected with
    `ERR_STALE_JOB_VERSION` (HTTP 412)."
    PRD §3.7: "On acceptance the report snapshots the job's `staged_resin_lot_id`
    into its own `resin_lot_id`, so the material traceability of the report survives
    any later de-staging, and the job's `version` is incremented by 1."

    Design: Corner/cross_cutting_layers/stale_job_version_on_production_report_returns_412
    """
    shop = setup_running_job()
    version_pre = job_version(shop["job"]["id"])
    line = dict(
        shots=100,
        short_shot_shots=0,
        good_parts=390,
        scrap_parts=10,
        virgin_grams=3600,
        regrind_grams=400,
        run_minutes=60,
    )
    validate_success(
        api.create_production_report(
            create_production_report_payload(shop["job"]["id"], version_pre, **line), PE
        ),
        201,
    )

    stale = api.create_production_report(
        create_production_report_payload(shop["job"]["id"], version_pre, **line), PE
    )
    assert stale.status_code == 412, f"Expected 412, got {stale.status_code}"
    validate_error(stale, ApiErrorId.ERR_STALE_JOB_VERSION.value)
    assert read_job(shop["job"]["id"])["total_shots"] == 100
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 496400

    version_post = job_version(shop["job"]["id"])
    assert version_post == version_pre + 1

    validate_success(
        api.create_production_report(
            create_production_report_payload(shop["job"]["id"], version_post, **line), PE
        ),
        201,
    )
    assert read_job(shop["job"]["id"])["total_shots"] == 200
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 492800


def test_shift_reports_are_reverse_navigable_by_job_and_by_lot(api):
    """PRD §2.3: "Shift reports may be filtered by `job_id`, `resin_lot_id` and
    `is_reversed`."
    PRD §3.7: "On acceptance the report snapshots the job's `staged_resin_lot_id`
    into its own `resin_lot_id`, so the material traceability of the report survives
    any later de-staging, and the job's `version` is incremented by 1."

    Design: Corner/endpoints/production_report_list_filters_by_job_and_resin_lot
    """
    shop = setup_running_job()
    line = dict(
        shots=100,
        short_shot_shots=0,
        good_parts=390,
        scrap_parts=10,
        virgin_grams=3600,
        regrind_grams=400,
        run_minutes=60,
    )
    post_report(shop["job"]["id"], **line)
    second = post_report(shop["job"]["id"], **line)

    _, by_job = validate_paginated(
        api.list_production_reports(QE, params={"job_id": shop["job"]["id"]})
    )
    assert by_job["total_count"] == 2
    assert by_job["has_more"] is False

    rows, by_lot = validate_paginated(
        api.list_production_reports(
            QE, params={"resin_lot_id": shop["lot"]["id"], "limit": 1, "offset": 0}
        )
    )
    assert by_lot["total_count"] == 2
    assert by_lot["has_more"] is True
    assert len(rows) == 1

    one = validate_success(api.get_production_report(second["id"], QE))
    assert one["job_id"] == shop["job"]["id"]
    assert one["resin_lot_id"] == shop["lot"]["id"]
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 492800
