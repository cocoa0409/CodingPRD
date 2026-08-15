"""Adherence (PDC) variants and the refill gate boundary, spoiled-fill
exclusion, and outcome-report metrics over the half-open reporting window
with OCC and period-closed rejection."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_outcome_report,
    create_active_with_delivered_fill,
    create_approved_with_card,
    create_outcome_report_payload,
    deliver,
    enrollment_version,
    get_enrollment,
    report_adverse_event,
    request_shipment,
    set_clock,
    ship,
    spoil,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]


class TestPdcVariantDivergence:

    def _setup_delivered_plus_shipped(self):
        """Fill 1 (30 days) DELIVERED 2026-08-01; fill 2 (30 days) SHIPPED
        2026-08-21 and never delivered; clock advanced to 2026-09-10, so the
        evaluation window is exactly 40 days."""
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-C", days_supply=30,
            requested_delivery_date="2026-08-01", delivered_date="2026-08-01")
        enr_id = ctx["enrollment"]["id"]
        set_clock("2026-08-21T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-22")
        ship(fill_2["id"])
        set_clock("2026-09-10T00:00:00Z")
        return enr_id

    def test_pdc_confirmed_counts_only_delivered_shipments(self):
        """PRD section 3.7: "The confirmed variant counts only `DELIVERED`
        shipments; it feeds the enrollment's `pdc_confirmed_pct`, the refill
        gate below, and the adherence figure on outcome reports, and it is
        evaluated at the current logical clock date for the first two of
        those uses."
        PRD section 3.7: "Covered days are the sum of `days_supply` across
        the variant's shipment set, capped at the window length. The
        percentage itself is one hundred times the covered days divided by
        the window days, rounded half-up to exactly one decimal place."

        Design: Difficulty/dual_variant_calc/pdc_provisional_vs_confirmed_divergence
        """
        enr_id = self._setup_delivered_plus_shipped()
        enr = get_enrollment(enr_id)
        # 40-day window, only fill 1 delivered: min(40, 30)/40 = 75.0
        assert enr["pdc_confirmed_pct"] == pytest.approx(75.0, abs=0.001), \
            f"confirmed counts DELIVERED only, got {enr['pdc_confirmed_pct']}"

    def test_pdc_provisional_counts_shipped_and_delivered(self):
        """PRD section 3.7: "The provisional variant counts shipments in
        `SHIPPED` or `DELIVERED`, feeding the enrollment's
        `pdc_provisional_pct` — the forward-looking outreach view."
        PRD section 3.7: "For identical data the provisional figure is never
        below the confirmed figure, and it is strictly greater whenever a
        shipped-but-not-yet-delivered fill exists."

        Design: Difficulty/dual_variant_calc/pdc_provisional_vs_confirmed_divergence
        """
        enr_id = self._setup_delivered_plus_shipped()
        enr = get_enrollment(enr_id)
        # provisional input set: fill 1 + fill 2 -> min(40, 60)/40 = 100.0
        assert enr["pdc_provisional_pct"] == pytest.approx(100.0, abs=0.001), \
            f"provisional counts SHIPPED+DELIVERED, got {enr['pdc_provisional_pct']}"
        assert enr["pdc_provisional_pct"] > enr["pdc_confirmed_pct"], \
            "the variants disagree whenever a shipped-not-delivered fill exists"


class TestPdcExcludesSpoiled:

    def test_pdc_excludes_spoiled_shipments_from_both_variants(self):
        """PRD section 3.7: "Both variants exclude `SPOILED` and `CANCELLED`
        shipments."
        PRD section 3.7: "Covered days are the sum of `days_supply` across
        the variant's shipment set, capped at the window length. The
        percentage itself is one hundred times the covered days divided by
        the window days, rounded half-up to exactly one decimal place."

        Design: Corner/calculations/pdc_excludes_spoiled_shipments_from_both_variants
        """
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-C1", days_supply=30,
            requested_delivery_date="2026-08-01", delivered_date="2026-08-01")
        enr_id = ctx["enrollment"]["id"]
        set_clock("2026-08-21T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-22")
        ship(fill_2["id"])
        spoil(fill_2["id"], reason="excursion")
        set_clock("2026-09-10T00:00:00Z")

        enr = get_enrollment(enr_id)
        assert enr["pdc_confirmed_pct"] == pytest.approx(75.0, abs=0.001)
        assert enr["pdc_provisional_pct"] == pytest.approx(75.0, abs=0.001), \
            "a SPOILED fill feeds neither variant; counting it would read 100.0"


class TestRefillGateBoundary:

    def _setup_at_gate(self, clock_iso):
        """Fill 1 (days_supply 20) delivered 2026-08-01; clock at the given
        date."""
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-L", days_supply=20,
            requested_delivery_date="2026-08-01", delivered_date="2026-08-01",
            program_overrides={"default_days_supply": 20})
        set_clock(clock_iso)
        return ctx["enrollment"]["id"]

    def test_refill_gate_at_exactly_80_passes(self):
        """PRD section 3.7: "The refill gate stands at 80.0: creating a
        `REFILL` shipment requires the confirmed-variant percentage,
        evaluated at the current logical clock date, to be at least 80.0 —
        and exactly 80.0 passes the gate."

        Design: Difficulty/boundary_precision_check/refill_gate_adherence_exactly_80_passes
        """
        # window 2026-08-01 -> 2026-08-26 is 25 days; 20 covered -> 80.0
        enr_id = self._setup_at_gate("2026-08-26T00:00:00Z")
        resp = api_client.create_shipment(
            enr_id,
            {"requested_delivery_date": "2026-08-26",
             "transit_hours": 24, "days_supply": 20},
            CM)
        fill = validate_success(resp, expected_status=201)
        assert fill["fill_number"] == 2
        assert fill["fill_type"] == "REFILL"
        assert fill["status"] == "SCHEDULED"

    def test_confirmed_pdc_is_exactly_80_at_gate_evaluation(self):
        """PRD section 3.7: "The refill gate stands at 80.0: creating a
        `REFILL` shipment requires the confirmed-variant percentage,
        evaluated at the current logical clock date, to be at least 80.0 —
        and exactly 80.0 passes the gate."
        PRD section 3.7: "The percentage itself is one hundred times the
        covered days divided by the window days, rounded half-up to exactly
        one decimal place."

        Design: Difficulty/boundary_precision_check/refill_gate_adherence_exactly_80_passes
        """
        enr_id = self._setup_at_gate("2026-08-26T00:00:00Z")
        enr = get_enrollment(enr_id)
        assert enr["pdc_confirmed_pct"] == pytest.approx(80.0, abs=0.001), \
            f"20 covered days over a 25-day window is exactly 80.0, got {enr['pdc_confirmed_pct']}"
        resp = api_client.create_shipment(
            enr_id,
            {"requested_delivery_date": "2026-08-26",
             "transit_hours": 24, "days_supply": 20},
            CM)
        validate_success(resp, expected_status=201)

    def test_refill_below_gate_rejected_with_adherence_too_low(self):
        """PRD section 3.7: "A refill requested below the threshold is
        rejected with `ERR_ADHERENCE_TOO_LOW`."
        PRD section 3.7: "The percentage itself is one hundred times the
        covered days divided by the window days, rounded half-up to exactly
        one decimal place."

        Design: Corner/errors/err_adherence_too_low_trigger_coverage
        """
        # window 2026-08-01 -> 2026-08-27 is 26 days; 20 covered -> 76.9
        enr_id = self._setup_at_gate("2026-08-27T00:00:00Z")
        enr = get_enrollment(enr_id)
        assert enr["pdc_confirmed_pct"] == pytest.approx(76.9, abs=0.001)
        resp = api_client.create_shipment(
            enr_id,
            {"requested_delivery_date": "2026-08-28",
             "transit_hours": 24, "days_supply": 20},
            CM)
        validate_error(resp, ApiErrorId.ERR_ADHERENCE_TOO_LOW)


class TestOutcomeReportLifecycle:

    def test_outcome_report_submit_valid_transition(self):
        """PRD section 3.8: "A new report begins in `DRAFT`."
        PRD section 3.8: "A `DRAFT` report may be submitted to the payer by
        a `CaseManager`, moving it `DRAFT` → `SUBMITTED`, which is terminal;
        since both `SUBMITTED` and `SUPERSEDED` are terminal states, any
        further transition on them is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/outcome_report_submit_valid_transition
        """
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-S3", requested_delivery_date="2026-08-01",
            delivered_date="2026-08-01")
        enr_id = ctx["enrollment"]["id"]
        version = enrollment_version(enr_id)
        created = validate_success(api_client.create_outcome_report(
            enr_id, create_outcome_report_payload(version), CM),
            expected_status=201)
        assert_outcome_report(created)
        assert created["status"] == "DRAFT"

        submitted = validate_success(
            api_client.submit_outcome_report(created["id"], CM),
            expected_status=200)
        assert submitted["status"] == "SUBMITTED"

        data, _ = validate_paginated(
            api_client.list_outcome_reports(enr_id, CM))
        assert data[0]["id"] == created["id"]
        assert data[0]["status"] == "SUBMITTED", \
            "the response and the re-read agree on SUBMITTED"

    def test_outcome_report_metrics_half_open_window(self):
        """PRD section 3.8: "The `fills_delivered_count` counts the
        enrollment's `DELIVERED` shipments whose `delivered_date` falls
        within the period. The `adverse_event_count` counts the enrollment's
        events standing in `REPORTED` or `ACKNOWLEDGED` whose
        `awareness_at` date falls within the period. The
        `total_assistance_cents` sums `assistance_pay_cents` over that same
        delivered-shipment set."
        PRD section 3.8: "Because the window is half-open, a delivery
        exactly on `period_end` is excluded from every metric."
        PRD section 3.8: "The `pdc_pct` is the confirmed-variant adherence
        evaluated with the period's end as the evaluation date, null when
        `therapy_start_date` is null or when the period end does not fall
        after `therapy_start_date`."

        Design: Corner/calculations/outcome_report_metrics_half_open_window
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-C2",
            bi_overrides={"plan_has_accumulator": False,
                          "patient_cost_share_cents": 20_000})
        enr_id = ctx["enrollment"]["id"]

        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-03")
        ship(fill_1["id"])
        deliver(fill_1["id"], "2026-08-03")

        set_clock("2026-08-24T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-24")
        ship(fill_2["id"])
        # Delivered exactly ON period_end 2026-08-31: excluded (half-open).
        deliver(fill_2["id"], "2026-08-31")

        report_adverse_event(
            enr_id, awareness_at="2026-08-23T12:00:00Z",
            seriousness="SERIOUS",
            description="injection site reaction")

        version = enrollment_version(enr_id)
        report = validate_success(api_client.create_outcome_report(
            enr_id,
            create_outcome_report_payload(
                version, period_start="2026-08-01", period_end="2026-08-31"),
            CM), expected_status=201)
        assert_outcome_report(report)
        assert report["fills_delivered_count"] == 1, \
            "the 2026-08-31 delivery falls on the exclusive period_end"
        assert report["adverse_event_count"] == 1
        assert report["total_assistance_cents"] == 15_000, \
            "only the in-window DELIVERED fill contributes"
        # therapy_start 2026-08-03 -> 28-day window; delivered fills supply
        # 60 days, capped at the window: 28/28 = 100.0
        assert report["pdc_pct"] == pytest.approx(100.0, abs=0.001)

    def test_occ_outcome_report_with_stale_version_rejected(self):
        """PRD section 2.9: "Creating an outcome report is guarded
        identically: the request must carry `expected_enrollment_version`, a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a
        successful create supersedes overlapping draft reports and
        increments the enrollment's `version` by one."
        PRD section 3.8: "If its period overlaps the period of an existing
        `DRAFT` report for the same enrollment, that existing draft is
        superseded — moved `DRAFT` → `SUPERSEDED` — as part of the
        creation."

        Design: Corner/cross_cutting_layers/occ_outcome_report_with_stale_version_rejected
        """
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-O2", requested_delivery_date="2026-08-01",
            delivered_date="2026-08-01")
        enr_id = ctx["enrollment"]["id"]
        observed = enrollment_version(enr_id)

        rep_1 = validate_success(api_client.create_outcome_report(
            enr_id, create_outcome_report_payload(observed), CM), 201)

        stale = api_client.create_outcome_report(
            enr_id, create_outcome_report_payload(observed), CM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = enrollment_version(enr_id)
        rep_2 = validate_success(api_client.create_outcome_report(
            enr_id, create_outcome_report_payload(fresh), CM), 201)

        data, _ = validate_paginated(
            api_client.list_outcome_reports(enr_id, CM))
        by_id = {r["id"]: r for r in data}
        assert by_id[rep_1["id"]]["status"] == "SUPERSEDED", \
            "the overlapping earlier DRAFT is superseded by the fresh create"
        assert by_id[rep_2["id"]]["status"] == "DRAFT"

    def test_report_overlapping_submitted_period_rejected(self):
        """PRD section 3.8: "If the period instead overlaps a `SUBMITTED`
        report for the enrollment, creation is rejected outright with
        `ERR_REPORT_PERIOD_CLOSED`."

        Design: Corner/errors/err_report_period_closed_trigger_coverage
        """
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-RC", requested_delivery_date="2026-08-01",
            delivered_date="2026-08-01")
        enr_id = ctx["enrollment"]["id"]
        rep = validate_success(api_client.create_outcome_report(
            enr_id,
            create_outcome_report_payload(enrollment_version(enr_id)),
            CM), 201)
        validate_success(api_client.submit_outcome_report(rep["id"], CM), 200)

        resp = api_client.create_outcome_report(
            enr_id,
            create_outcome_report_payload(
                enrollment_version(enr_id),
                period_start="2026-08-15", period_end="2026-09-15"),
            CM)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_CLOSED)
