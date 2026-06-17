"""Warranty callbacks, the within-warranty boundary, and the technician callback
rate (lifetime versus rolling divergence).

The callback-rate divergence drives six jobs to COMPLETED at strictly increasing
completed_at, files callbacks against the two oldest, and checks that the lifetime
rate (2/6) differs from the rolling-window rate (1/5).
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_flat_rate_item, create_customer, create_technician,
    create_service_job,
    setup_completed_job, run_one_completed_job, set_clock,
    file_callback,
    api_client, TEST_USERS, make_customer_headers,
)

OM = TEST_USERS["office_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]

NORMAL_START = "2026-06-16T10:00:00.000Z"
NORMAL_END = "2026-06-16T12:00:00.000Z"
NORMAL_ETA = "2026-06-16T10:15:00.000Z"


class TestCallbackRateVariants:
    def test_lifetime_and_rolling_callback_rates_diverge(self, api):
        """PRD §3.9: "The **lifetime** rate is the technician's
        `lifetime_callback_count` divided by its `lifetime_completed_count`, reported
        to four decimal places".
        PRD §3.9: "The rolling denominator is the smaller of 5 and the technician's
        `lifetime_completed_count`, and the rolling numerator is the count of those
        window jobs that have at least one callback."
        PRD §3.9: "it considers the technician's most recent completed jobs, ordered
        by `completed_at` descending with ties broken by `created_at` descending, and
        takes the most recent five."

        Design: Difficulty/dual_variant_calc/technician_lifetime_vs_rolling_callback_rate_diverge
        """
        set_clock("2026-01-01T09:00:00.000Z")
        customer = create_customer(credit_limit_cents=100000000)
        technician = create_technician(skill_level=5)
        fr = create_flat_rate_item(code="CB-GEN", category="DRAIN",
                                   base_price_cents=10000, skill_required=1)

        jobs = []
        # Six jobs completed on six consecutive days so completed_at strictly increases.
        for day in range(1, 7):
            set_clock(f"2026-01-0{day}T09:00:00.000Z")
            job = run_one_completed_job(
                customer["id"], technician["id"], fr["id"],
                f"2026-01-0{day}T10:00:00.000Z",
                f"2026-01-0{day}T12:00:00.000Z",
                f"2026-01-0{day}T10:15:00.000Z")
            jobs.append(job)

        # Callbacks against the two OLDEST jobs only (J1, J2).
        cust_h = make_customer_headers(customer["id"])
        validate_success(api.create_callback(
            {"original_job_id": jobs[0]["id"], "reason": "J1 recurred"}, cust_h),
            expected_status=201)
        validate_success(api.create_callback(
            {"original_job_id": jobs[1]["id"], "reason": "J2 recurred"}, cust_h),
            expected_status=201)

        rate = get_success_data(api.get_callback_rate(technician["id"], OM))
        assert rate["lifetime_completed_count"] == 6, \
            f"six distinct completions, got {rate['lifetime_completed_count']}"
        assert rate["lifetime_callback_count"] == 2, \
            f"two callbacks filed, got {rate['lifetime_callback_count']}"
        assert rate["lifetime_callback_rate"] == 0.3333, \
            f"lifetime 2/6 -> 0.3333, got {rate['lifetime_callback_rate']}"
        assert rate["rolling_callback_rate"] == 0.2000, \
            ("rolling window (J6..J2) holds only J2's callback -> 1/5 = 0.2000, "
             f"got {rate['rolling_callback_rate']}")
        assert rate["lifetime_callback_rate"] != rate["rolling_callback_rate"], \
            "the two rates must diverge on the same history"


class TestCallbackRateCorners:
    def test_callback_rate_zero_when_no_completions(self, api):
        """PRD §3.9: "The **lifetime** rate is the technician's
        `lifetime_callback_count` divided by its `lifetime_completed_count`, reported
        to four decimal places, and reported as 0.0 when the completed count is 0. ...
        The rolling rate is that numerator over that denominator, reported to four
        decimal places and as 0.0 when the denominator is 0."

        Design: Corner/calculations/callback_rate_zero_when_no_completions
        """
        technician = create_technician(skill_level=2)
        rate = get_success_data(api.get_callback_rate(technician["id"], OM))
        assert rate["lifetime_callback_rate"] == 0.0, \
            f"no completions -> lifetime rate 0.0, got {rate['lifetime_callback_rate']}"
        assert rate["rolling_callback_rate"] == 0.0, \
            f"no completions -> rolling rate 0.0, got {rate['rolling_callback_rate']}"


class TestWarrantyBoundary:
    def test_callback_at_exactly_90_days_is_within_warranty(self, api):
        """PRD §3.8: "The callback is within warranty when that whole-day count is
        less than or equal to the warranty period of 90 days; a callback filed exactly
        90 days after completion is still within warranty, because the boundary is
        inclusive."

        Design: Corner/calculations/callback_warranty_boundary_at_exactly_90_days
        """
        fr = create_flat_rate_item(code="WB-1", category="DRAIN",
                                   base_price_cents=15000, skill_required=1)
        scenario = setup_completed_job(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            consumed_parts=[],
            customer_overrides={"credit_limit_cents": 1000000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "DRAIN"},
            window_start="2026-03-01T11:00:00.000Z",
            window_end="2026-03-01T13:00:00.000Z",
            eta="2026-03-01T11:15:00.000Z")
        # The job was completed at 2026-03-01T10:00Z (the clock set inside the
        # lifecycle); advance exactly 90 days and file the callback.
        # Completion timestamp is the current clock; pin it then advance 90 days.
        # Drive completion at a known instant:
        # setup_completed_job did not set the clock, so completed_at == the prior clock.
        # Re-establish determinism by setting the clock to completion time then +90d.
        # (We read completed_at from the job to compute the exact boundary date.)
        completed_at = scenario["job"]["completed_at"]
        assert completed_at is not None
        boundary_iso = self._plus_days(completed_at, 90)
        set_clock(boundary_iso)
        cust_h = make_customer_headers(scenario["customer"]["id"])
        callback = get_success_data(api.create_callback(
            {"original_job_id": scenario["job"]["id"], "reason": "boundary check"}, cust_h))
        assert callback["within_warranty"] is True, \
            "a callback filed exactly 90 days after completion is within warranty"

    @staticmethod
    def _plus_days(iso_ts, days):
        from datetime import datetime, timedelta, timezone
        # Accept trailing Z; parse to aware datetime, add days, re-emit with millis + Z.
        ts = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts).astimezone(timezone.utc) + timedelta(days=days)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class TestWarrantyErrors:
    def test_callback_against_non_completed_job_rejected(self, api):
        """PRD §3.8: "A callback may only be filed against a job that is `COMPLETED`;
        a callback filed against a job in any other state is rejected with
        `ERR_WARRANTY_EXPIRED`."

        Design: Corner/errors/callback_against_non_completed_job_returns_warranty_expired
        """
        customer = create_customer(credit_limit_cents=100000)
        job = create_service_job(customer["id"], category="LEAK")  # RECEIVED
        cust_h = make_customer_headers(customer["id"])
        resp = api.create_callback(
            {"original_job_id": job["id"], "reason": "premature"}, cust_h)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)

    def test_accept_expired_warranty_callback_rejected(self, api):
        """PRD §3.8: "an attempt to accept a callback whose `within_warranty` is false
        is rejected with `ERR_WARRANTY_EXPIRED`."
        PRD §3.8: "The callback is within warranty when that whole-day count is less
        than or equal to the warranty period of 90 days".

        Design: Corner/errors/accept_expired_warranty_callback_returns_warranty_expired
        """
        fr = create_flat_rate_item(code="EX-1", category="DRAIN",
                                   base_price_cents=15000, skill_required=1)
        scenario = setup_completed_job(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            consumed_parts=[],
            customer_overrides={"credit_limit_cents": 1000000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "DRAIN"},
            window_start="2026-03-01T11:00:00.000Z",
            window_end="2026-03-01T13:00:00.000Z",
            eta="2026-03-01T11:15:00.000Z")
        completed_at = scenario["job"]["completed_at"]
        expired_iso = TestWarrantyBoundary._plus_days(completed_at, 91)
        set_clock(expired_iso)
        cust_h = make_customer_headers(scenario["customer"]["id"])
        callback = get_success_data(api.create_callback(
            {"original_job_id": scenario["job"]["id"], "reason": "too late"}, cust_h))
        assert callback["within_warranty"] is False, \
            "a callback 91 days out is out of warranty"

        resp = api.accept_callback(callback["id"], OM)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)
        reread = get_success_data(api.get_service_job(scenario["job"]["id"], DISP))
        assert reread["status"] == "COMPLETED", \
            "a rejected accept leaves the job COMPLETED"
