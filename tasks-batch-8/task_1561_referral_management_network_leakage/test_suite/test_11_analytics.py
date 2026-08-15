"""Analytics: conversion bases, snapshot intake set, period close guards, live report."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    period_close_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_referral, accept_referral,
    create_booked_referral, confirm_appointment, complete_appointment,
    create_closed_referral, set_clock, get_referral,
    assert_period_snapshot, assert_rate,
    TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestConversionDualBasis:
    def _setup_three_referral_period(self, api):
        """R1 fully closed; R2 STAT expired by sweep before scheduling; R3 scheduled
        but never completed. All created inside [2026-08-01, 2026-09-01)."""
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        specialist = create_specialist(accepts_urgent=True)
        create_participation(specialist["id"], plan["id"])
        provider = create_provider()
        patient = create_patient(plan["id"])

        # R1: book 2026-08-02T10:00, confirm, complete at 11:00, note, verify CLOSED.
        r1, _a1, _n1, _c1 = create_closed_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z",
            coordinator_user_id="coord-1", auditor_user_id="audit-1",
            diagnosis_code="I10",
        )
        # R2: STAT accepted at 2026-08-02T11:00 (sla 2026-08-04T11:00), never booked.
        r2 = create_referral(provider["id"], patient["id"], urgency="STAT",
                             diagnosis_code="I21")
        accept_referral(r2["id"])
        set_clock("2026-08-04T11:00:00Z")
        validate_success(api.run_aging_sweep(COORD))
        assert get_referral(r2["id"])["status"] == "EXPIRED"

        # R3: accepted + booked 2026-08-10, never completed.
        r3, _a3 = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z", diagnosis_code="I50",
        )
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.close_period(period_close_payload("2026-08-01", "2026-09-01"),
                                          ADMIN), 201)
        data, meta = validate_paginated(api.list_snapshots(ADMIN))
        assert meta["total_count"] == 1, "Exactly one provider has a non-empty intake set"
        row = data[0]
        assert_period_snapshot(row)
        assert row["referring_provider_id"] == provider["id"]
        return row

    def test_snapshot_counts_and_dual_basis_divergence(self, api):
        """PRD §3.8: "The intake basis divides the count of completed referrals by
        the full intake set — the provider's referrals created within the window
        whose status is not `REJECTED`, statuses being evaluated at computation time.
        The scheduled basis divides the same completed count by the subset of the
        intake set whose `ever_scheduled` flag is true; because its denominator only
        shrinks, the scheduled-basis rate is always at least the intake-basis rate
        for identical data, and strictly greater whenever any intake referral never
        reached scheduling. A referral counts as completed for these purposes when at
        least one of its appointments has reached `COMPLETED`. Both rates are
        reported to 4 decimal places, round-half-up, and a zero denominator yields
        0.0000."

        Design: Difficulty/dual_variant_calc/conversion_rate_dual_basis_divergence
        """
        row = self._setup_three_referral_period(api)
        assert row["intake_count"] == 3, "R1 CLOSED, R2 EXPIRED, R3 SCHEDULED; none REJECTED"
        assert row["completed_count"] == 1, "Only R1 has a COMPLETED appointment"
        assert row["scheduled_basis_count"] == 2, "R1 and R3 have ever_scheduled; R2 expired first"
        assert_rate(row["conversion_rate_intake"], 0.3333, "conversion_rate_intake (1/3)")
        assert_rate(row["conversion_rate_scheduled"], 0.5, "conversion_rate_scheduled (1/2)")
        assert row["conversion_rate_intake"] != row["conversion_rate_scheduled"], (
            "The denominator definition, not the data, drives the divergence"
        )

    def test_snapshot_leakage_fields(self, api):
        """PRD §3.8: "The leakage rate is the count of intake referrals with `leaked`
        true divided by the intake count, on the same 4-decimal rounding and
        zero-denominator convention."
        PRD §3.8: "The exposure field sums the per-line `estimated_value_cents` of
        the leakage records attached to the intake set's leaked referrals".
        PRD §3.8: "The per-specialty base values, in cents, are: 42,000 for
        `CARDIOLOGY`; ...".

        Design: Difficulty/dual_variant_calc/conversion_rate_dual_basis_divergence
        """
        row = self._setup_three_referral_period(api)
        assert row["leaked_count"] == 1, "Only R2 leaked (EXPIRED_UNRESOLVED)"
        assert_rate(row["leakage_rate"], 0.3333, "leakage_rate (1/3)")
        assert row["estimated_leakage_exposure_cents"] == 42000, (
            "CARDIOLOGY base 42000 x payer_mix_factor 1.0, rounded per line"
        )


class TestSnapshotInputSet:
    def test_excludes_out_of_window_and_rejected(self, api):
        """PRD §3.8: "the window covers referrals whose `created_at` is at or after
        `period_start` and strictly before `period_end`".
        PRD §3.8: "The intake basis divides the count of completed referrals by the
        full intake set — the provider's referrals created within the window whose
        status is not `REJECTED`".
        PRD §3.8: "a zero denominator yields 0.0000".
        PRD §2.4: "`ProviderPeriodSnapshot` likewise carries no `updated_at` and no
        `version`; it is a frozen row created at period close."

        Design: Corner/calculations/snapshot_input_set_excludes_out_of_window_and_rejected
        """
        set_clock("2026-07-31T00:00:00Z")
        plan = create_plan()
        provider = create_provider()
        patient = create_patient(plan["id"])
        # R0 created before the window.
        create_referral(provider["id"], patient["id"], diagnosis_code="I10")
        set_clock("2026-08-05T00:00:00Z")
        # R1 created inside the window but REJECTED.
        r1 = create_referral(provider["id"], patient["id"], diagnosis_code="I11")
        validate_success(api.reject_referral(r1["id"], {"reason": "Duplicate"}, COORD))
        # R2 created inside the window and accepted.
        r2 = create_referral(provider["id"], patient["id"], diagnosis_code="I20")
        accept_referral(r2["id"])

        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.close_period(period_close_payload("2026-08-01", "2026-09-01"),
                                          ADMIN), 201)
        data, meta = validate_paginated(api.list_snapshots(ADMIN))
        assert meta["total_count"] == 1
        row = data[0]
        assert_period_snapshot(row)  # asserts absence of version/updated_at
        assert row["intake_count"] == 1, "Only R2 is in-window and non-REJECTED"
        assert row["completed_count"] == 0
        assert row["scheduled_basis_count"] == 0
        assert_rate(row["conversion_rate_scheduled"], 0.0,
                    "conversion_rate_scheduled (zero-denominator guard)")
        assert_rate(row["leakage_rate"], 0.0, "leakage_rate (nothing leaked)")


class TestPeriodCloseGuards:
    def test_skips_providers_with_empty_intake(self, api):
        """PRD §3.8: "The close walks referring providers in `created_at` ascending
        order and, for each whose intake set in the window is non-empty, writes one
        `ProviderPeriodSnapshot` pinned at close time."

        Design: Corner/calculations/period_close_skips_providers_with_empty_intake
        """
        create_provider()
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.close_period(period_close_payload("2026-08-01", "2026-09-01"),
                                          ADMIN), 201)
        data, meta = validate_paginated(api.list_snapshots(ADMIN))
        assert meta["total_count"] == 0, (
            "A provider with zero non-REJECTED referrals in the window gets no snapshot"
        )
        assert data == []

    def test_period_close_validation_matrix(self, api):
        """PRD §3.8: "Three preconditions guard it: `period_end` must be strictly
        after `period_start`, else `ERR_INVALID_PERIOD`; the current date must have
        reached `period_end`, else `ERR_PERIOD_NOT_ENDED`; and no snapshot may
        already exist for the same period pair, else `ERR_PERIOD_ALREADY_CLOSED`."

        Design: Corner/validations/period_close_validation_matrix
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        provider = create_provider()
        patient = create_patient(plan["id"])
        set_clock("2026-08-05T00:00:00Z")
        referral = create_referral(provider["id"], patient["id"])
        accept_referral(referral["id"])
        set_clock("2026-08-15T00:00:00Z")

        e1 = api.close_period(period_close_payload("2026-09-01", "2026-08-01"), ADMIN)
        validate_error(e1, ApiErrorId.ERR_INVALID_PERIOD, expected_status=400)

        e2 = api.close_period(period_close_payload("2026-08-01", "2026-09-01"), ADMIN)
        validate_error(e2, ApiErrorId.ERR_PERIOD_NOT_ENDED, expected_status=409)

        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.close_period(period_close_payload("2026-08-01", "2026-09-01"),
                                          ADMIN), 201)
        data, meta = validate_paginated(api.list_snapshots(ADMIN))
        assert meta["total_count"] == 1

        e3 = api.close_period(period_close_payload("2026-08-01", "2026-09-01"), ADMIN)
        validate_error(e3, ApiErrorId.ERR_PERIOD_ALREADY_CLOSED, expected_status=409)


class TestLiveLeakageReport:
    def _setup_one_completed_one_accepted(self, api):
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        specialist = create_specialist()
        create_participation(specialist["id"], plan["id"])
        provider = create_provider()
        patient = create_patient(plan["id"])
        r1, a1 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                        "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                                        diagnosis_code="I10")
        confirm_appointment(a1["id"])
        set_clock("2026-08-02T11:00:00Z")
        complete_appointment(a1["id"], specialist["id"])
        r2 = create_referral(provider["id"], patient["id"], diagnosis_code="I11")
        accept_referral(r2["id"])
        return provider["id"]

    def test_basis_selection_intake_vs_scheduled(self, api):
        """PRD §3.8: "A live analytics read is available per referring provider. It
        computes over an all-time window rather than a bound period, accepts an
        optional `basis` selector choosing the intake or scheduled conversion basis,
        and returns the chosen `basis` label, `intake_count`, `completed_count`,
        `leaked_count`, the selected `conversion_rate`, the `leakage_rate`, and
        `estimated_leakage_exposure_cents`."
        PRD §3.8: "The scheduled basis divides the same completed count by the subset
        of the intake set whose `ever_scheduled` flag is true".

        Design: Corner/calculations/live_report_basis_selection_and_default
        """
        provider_id = self._setup_one_completed_one_accepted(api)
        intake = validate_success(api.get_provider_leakage_report(
            provider_id, COORD, params={"basis": "INTAKE"}
        ))
        assert_rate(intake["conversion_rate"], 0.5, "INTAKE conversion_rate (1/2)")
        assert intake["intake_count"] == 2
        assert intake["completed_count"] == 1
        assert intake["leaked_count"] == 0

        scheduled = validate_success(api.get_provider_leakage_report(
            provider_id, COORD, params={"basis": "SCHEDULED"}
        ))
        assert_rate(scheduled["conversion_rate"], 1.0, "SCHEDULED conversion_rate (1/1)")
        assert scheduled["intake_count"] == 2
        assert scheduled["completed_count"] == 1
        assert scheduled["leaked_count"] == 0
