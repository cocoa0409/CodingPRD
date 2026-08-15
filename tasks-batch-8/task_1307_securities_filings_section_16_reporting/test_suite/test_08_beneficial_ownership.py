"""Beneficial ownership monitoring: dual percentage variants, threshold
boundaries, schedule recording, and the immutable position log
(PRD §2.4, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_compliance_officer_headers,
    assert_position_change,
    create_issuer, create_beneficial_holder, post_position_change, get_holder,
)


class TestBasicVsFullyDiluted:
    def _setup_holder_with_derivatives(self, api):
        """Holder with +25,000 shares / +0 derivatives, then +25,000 shares /
        +25,000 derivatives (shares_outstanding 1,000,000)."""
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        post_position_change(holder["id"], shares_delta=25000,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        post_position_change(holder["id"], shares_delta=25000,
                             derivative_shares_delta=25000,
                             effective_date="2026-08-01")
        return holder

    def test_basic_variant_drives_threshold_and_shares_sum(self, api):
        """PRD §3.7: "Posting a change recomputes the holder's derived figures:
        `shares_beneficially_owned` is the sum of every `shares_delta` ever
        posted for the holder (the log is append-only and no status filter
        applies); `exercisable_derivative_shares` is the corresponding sum of
        `derivative_shares_delta`; `current_pct` is one hundred times
        `shares_beneficially_owned` divided by the issuer's current
        `shares_outstanding`, rounded half-up to two decimal places"
        PRD §3.7: "When a posting leaves `current_pct` at 5.00 or higher —
        equality triggers — the holder moves automatically from `MONITORING` to
        `FILING_REQUIRED`."

        Design: Difficulty/dual_variant_calc/beneficial_ownership_basic_vs_fully_diluted
        """
        holder = self._setup_holder_with_derivatives(api)
        data = get_holder(holder["id"])
        assert data["shares_beneficially_owned"] == 50000, (
            f"Expected summed shares 50000, "
            f"got {data['shares_beneficially_owned']}")
        assert data["current_pct"] == pytest.approx(5.00, abs=1e-9), (
            f"BASIC variant: 100 * 50,000 / 1,000,000 = 5.00, "
            f"got {data['current_pct']}")
        assert data["status"] == "FILING_REQUIRED", (
            f"Threshold monitoring uses the BASIC variant only, "
            f"got {data['status']}")

    def test_fully_diluted_variant_diverges(self, api):
        """PRD §3.7: "and `fully_diluted_pct` is one hundred times the sum of
        `shares_beneficially_owned` and `exercisable_derivative_shares` divided
        by the sum of `shares_outstanding` and `exercisable_derivative_shares`,
        rounded the same way. The fully diluted figure is informational only
        and never gates thresholds — it diverges from the basic figure whenever
        the holder has exercisable derivatives."

        Design: Difficulty/dual_variant_calc/beneficial_ownership_basic_vs_fully_diluted
        """
        holder = self._setup_holder_with_derivatives(api)
        data = get_holder(holder["id"])
        # 100 * 75,000 / 1,025,000 = 7.3170... -> 7.32 half-up at 2 decimals.
        assert data["fully_diluted_pct"] == pytest.approx(7.32, abs=1e-9), (
            f"FULLY_DILUTED variant must be 7.32, got {data['fully_diluted_pct']}")
        assert data["fully_diluted_pct"] != pytest.approx(
            data["current_pct"], abs=1e-9), (
            "The two variants must diverge for identical input data when the "
            "holder has exercisable derivatives")


class TestFivePercentBoundary:
    def test_below_threshold_stays_monitoring(self, api):
        """PRD §3.7: "Two thresholds drive the holder's `status`, and both
        evaluate `current_pct` alone. When a posting leaves `current_pct` at
        5.00 or higher — equality triggers — the holder moves automatically
        from `MONITORING` to `FILING_REQUIRED`."

        Design: Difficulty/boundary_precision_check/ownership_pct_exactly_five_triggers
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        post_position_change(holder["id"], shares_delta=49900,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        data = get_holder(holder["id"])
        assert data["current_pct"] == pytest.approx(4.99, abs=1e-9), (
            f"49,900 / 1,000,000 = 4.99, got {data['current_pct']}")
        assert data["status"] == "MONITORING", (
            f"4.99 < 5.00 must leave the holder MONITORING, "
            f"got {data['status']}")

    def test_exactly_five_percent_triggers_filing_required(self, api):
        """PRD §3.7: "When a posting leaves `current_pct` at 5.00 or higher —
        equality triggers — the holder moves automatically from `MONITORING` to
        `FILING_REQUIRED`."

        Design: Difficulty/boundary_precision_check/ownership_pct_exactly_five_triggers
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        post_position_change(holder["id"], shares_delta=49900,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        post_position_change(holder["id"], shares_delta=100,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        data = get_holder(holder["id"])
        assert data["current_pct"] == pytest.approx(5.00, abs=1e-9), (
            f"50,000 / 1,000,000 = 5.00, got {data['current_pct']}")
        assert data["status"] == "FILING_REQUIRED", (
            f"Equality at 5.00 triggers FILING_REQUIRED, got {data['status']}")


class TestAmendmentThreshold:
    def test_amendment_required_at_exactly_one_pct_move(self, api):
        """PRD §3.7: "Once a schedule is on file, drift matters instead: when
        the absolute difference between `current_pct` and the
        `last_reported_pct` snapshot reaches 1.00 or more — again with equality
        triggering — the holder moves automatically from `FILED` to
        `AMENDMENT_REQUIRED`"
        PRD §3.7: "On success the holder moves to `FILED`, `last_reported_pct`
        snapshots the then-current `current_pct`, and the supplied
        `schedule_type` is stored"

        Design: Corner/calculations/amendment_required_at_exactly_one_pct_move
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        post_position_change(holder["id"], shares_delta=50000,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        filed = get_success_data(api.file_schedule(
            holder["id"], {"schedule_type": "SCHEDULE_13G"},
            make_compliance_officer_headers()))
        assert filed["status"] == "FILED", (
            f"Schedule recording must yield FILED, got {filed['status']}")
        # Drift of 0.99 stays below the amendment trigger.
        post_position_change(holder["id"], shares_delta=9900,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        mid = get_holder(holder["id"])
        assert mid["current_pct"] == pytest.approx(5.99, abs=1e-9), (
            f"59,900 / 1,000,000 = 5.99, got {mid['current_pct']}")
        assert mid["status"] == "FILED", (
            f"Drift 0.99 < 1.00: no amendment due, got {mid['status']}")
        # Drift of exactly 1.00 triggers the amendment requirement.
        post_position_change(holder["id"], shares_delta=100,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        end = get_holder(holder["id"])
        assert end["current_pct"] == pytest.approx(6.00, abs=1e-9), (
            f"60,000 / 1,000,000 = 6.00, got {end['current_pct']}")
        assert end["status"] == "AMENDMENT_REQUIRED", (
            f"Drift exactly 1.00 triggers AMENDMENT_REQUIRED, "
            f"got {end['status']}")


class TestPositionChangeImmutability:
    def test_position_change_is_immutable_event(self, api):
        """PRD §2.4: "The `PositionChange` event is the sole exception. It is
        immutable once posted and carries only `id` and `created_at`; both
        `updated_at` and `version` are absent, and the resource is never
        modified after creation."

        Design: Corner/entities/position_change_is_immutable_event
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        change = post_position_change(holder["id"], shares_delta=10000,
                                      derivative_shares_delta=0,
                                      effective_date="2026-08-01")
        resp = api.get_position_change(change["id"],
                                       make_compliance_officer_headers())
        data = validate_success(resp, 200)
        assert_position_change(data)
        assert data["id"] == change["id"]
        assert data["shares_delta"] == 10000, (
            f"Expected shares_delta 10000 as posted, got {data['shares_delta']}")


class TestScheduleGuards:
    def test_schedule_not_required_below_threshold(self, api):
        """PRD §3.7: "Recording the Schedule 13D or 13G itself is a
        `ComplianceOfficer` action that supplies the `schedule_type`, either
        `SCHEDULE_13D` or `SCHEDULE_13G`. It is permitted only while the holder
        is `FILING_REQUIRED` or `AMENDMENT_REQUIRED`; from any other state it
        fails with `ERR_SCHEDULE_NOT_REQUIRED`."

        Design: Corner/validations/schedule_not_required_below_threshold
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        post_position_change(holder["id"], shares_delta=49900,
                             derivative_shares_delta=0,
                             effective_date="2026-08-01")
        # 4.99% leaves the holder MONITORING: no schedule is due.
        resp = api.file_schedule(holder["id"], {"schedule_type": "SCHEDULE_13G"},
                                 make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_REQUIRED)

    def test_future_effective_date_position_rejected(self, api):
        """PRD §3.7: "the `effective_date` of the change — which must not be
        later than the logical clock date, failing with
        `ERR_FUTURE_EFFECTIVE_DATE`"

        Design: Corner/validations/future_effective_date_position_rejected
        """
        issuer = create_issuer()
        holder = create_beneficial_holder(issuer["id"])
        # Logical clock is at the startup default 2026-08-01 (PRD §2.5).
        resp = api.post_position_change(
            holder["id"],
            {"shares_delta": 10000, "derivative_shares_delta": 0,
             "effective_date": "2026-08-05"},
            make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_FUTURE_EFFECTIVE_DATE)
