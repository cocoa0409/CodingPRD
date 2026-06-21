"""Validation and error-catalogue corners: fiscal apply guard, draw range,
interval validity, conditional permit-final rule, completion guard against open
change orders, warranty expiry guard, and pagination bounds.

Queue B (validations section, errors section).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    setup_estimated_job, setup_in_production_job, setup_in_production_with_draw,
    setup_approved_change_order, setup_active_warranty,
    create_estimator_payload, create_job_payload, create_inspection_payload,
    complete_inspection_payload, create_draw_payload, create_change_order_payload,
    apply_change_order_payload, current_job_version, disburse_draw, set_clock,
)

FA = TEST_USERS["field_adjuster_headers"]
EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["production_manager_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


class TestFiscalAndRangeViolations:
    def test_change_order_apply_below_disbursed_rejected(self, api):
        """PRD §3.8: "the job's `contract_value_cents` plus this order's
        `delta_cents` must be at least the job's `disbursed_gross_cents`,
        otherwise the apply is rejected with `ERR_CONTRACT_BELOW_DISBURSED`."

        Design: Corner/validations/change_order_apply_below_disbursed_rejected
        """
        # Contract 110000, one 50% draw (disbursed_gross 55000). CO delta -60000
        # would drop contract to 50000 < 55000.
        job_id, info = setup_in_production_with_draw(cumulative_pct=0.5, line_items=SHINGLE_10)
        co = setup_approved_change_order(job_id, delta_cents=-60_000)
        jv = current_job_version(job_id)
        validate_error(api.apply_change_order(
            co["id"], apply_change_order_payload(expected_job_version=jv), PM),
            ApiErrorId.ERR_CONTRACT_BELOW_DISBURSED.value)

    def test_draw_pct_out_of_range_rejected(self, api):
        """PRD §3.7: "The `cumulative_pct` must be at most 1.0, else
        `ERR_PCT_OUT_OF_RANGE` (and a value at or below 0, or above 1, is also an
        invalid request at the range-validation stage)."

        Design: Corner/validations/draw_pct_out_of_range
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        validate_error(api.create_draw(create_draw_payload(
            job_id=job_id, cumulative_pct=1.5, expected_job_version=info["job_version"]), PM),
            ApiErrorId.ERR_PCT_OUT_OF_RANGE.value)

    def test_inspection_window_end_before_start_rejected(self, api):
        """PRD §3.1: "Each inspection names its `job_id`, a `kind`, and a closed
        scheduling window defined by `scheduled_start` and `scheduled_end`, where
        the end must be strictly later than the start."

        Design: Corner/validations/inspection_window_end_before_start
        """
        est_id = get_success_data(api.create_estimator(create_estimator_payload(), EST))["id"]
        job_id = get_success_data(api.create_job(
            create_job_payload(assigned_estimator_id=est_id), FA))["id"]
        validate_error(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="DAMAGE_ASSESSMENT",
            scheduled_start="2026-03-01T12:00:00Z", scheduled_end="2026-03-01T10:00:00Z"), FA),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_permit_final_without_permit_id_rejected(self, api):
        """PRD §3.1: "A `PERMIT_FINAL` inspection must name the `permit_id` it
        finalizes, and a `DAMAGE_ASSESSMENT` must not carry a `permit_id`;
        violating either rule is rejected with `ERR_PERMIT_FINAL_NEEDS_PERMIT`
        (HTTP 422)."

        Design: Corner/validations/permit_final_without_permit_id
        """
        est_id = get_success_data(api.create_estimator(create_estimator_payload(), EST))["id"]
        job_id = get_success_data(api.create_job(
            create_job_payload(assigned_estimator_id=est_id), FA))["id"]
        validate_error(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL",
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA),
            ApiErrorId.ERR_PERMIT_FINAL_NEEDS_PERMIT.value)


class TestCrossEntityAndTerminalGuards:
    def test_complete_job_with_open_change_order_rejected(self, api):
        """PRD §3.9: "And no change order for the job may be open in `PROPOSED`
        or `APPROVED` status, otherwise `ERR_OPEN_CHANGE_ORDER` — every change
        order must be resolved (applied or voided) before the job closes."

        Design: Corner/validations/complete_job_with_open_change_order_rejected
        """
        # Drive to IN_PRODUCTION, bill to 100%, pass PERMIT_FINAL, but leave a
        # PROPOSED change order open.
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        disburse_draw(job_id, 1.0, info["job_version"])
        pf = get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=info["permit"]["id"],
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        api.complete_inspection(pf["id"], complete_inspection_payload(outcome="PASS"), FA)
        # Propose (do not approve/apply/void) a change order.
        api.create_change_order(create_change_order_payload(
            job_id=job_id, reason="late add", delta_cents=1000), PM)
        validate_error(api.complete_job(job_id, PM), ApiErrorId.ERR_OPEN_CHANGE_ORDER.value)

    def test_warranty_expire_before_term_rejected(self, api):
        """PRD §3.10: "expiry is permitted only when the current logical clock is
        at or past `start_at` plus `term_months`, otherwise the request is
        rejected with `ERR_WARRANTY_NOT_EXPIRED`."

        Design: Corner/errors/warranty_expire_before_term_rejected
        """
        # start_at 2026-01-01, term 120 months; clock at 2026-02-01 is far short.
        job_id, war, _ = setup_active_warranty(
            premium_cents=50_000, term_months=120, start_clock="2026-01-01T00:00:00Z")
        set_clock("2026-02-01T00:00:00Z")
        validate_error(api.expire_warranty(war["id"], PM),
                       ApiErrorId.ERR_WARRANTY_NOT_EXPIRED.value)


class TestPagination:
    def test_list_jobs_limit_over_max_rejected(self, api):
        """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/errors/pagination_limit_out_of_bounds
        """
        validate_error(api.list_jobs(FA, params={"limit": 500}),
                       ApiErrorId.ERR_VALIDATION.value)
