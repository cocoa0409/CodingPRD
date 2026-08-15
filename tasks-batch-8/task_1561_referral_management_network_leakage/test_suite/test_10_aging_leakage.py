"""Aging sweep, SLA expiry boundary, leakage attribution, provider watch flag,
per-line exposure rounding."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_plan, create_provider, create_patient, create_referral,
    accept_referral, cancel_referral_payload,
    set_clock, get_referral, get_provider,
    list_referral_leakage_records, list_provider_leakage_records,
    assert_instant_equals, assert_leakage_record,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap(payer_mix_factor=1.0, plan_code="PPO-1"):
    plan = create_plan(plan_code=plan_code, payer_mix_factor=payer_mix_factor)
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, provider, patient


class TestSlaExpiryInclusiveBoundary:
    def test_one_second_before_due_does_not_expire(self, api):
        """PRD §3.3: "`sla_due_at` is computed as `triaged_at` plus the urgency's
        service-level window — 2 days for `STAT`, 7 days for `URGENT`, 30 days for
        `ROUTINE`, using exact second arithmetic".
        PRD §3.8: "expires any referral whose status is `ACCEPTED`, `SCHEDULED`,
        `VISIT_COMPLETED`, or `PENDING_VERIFICATION` and whose `sla_due_at` has been
        reached — the boundary is inclusive, so a referral exactly at its deadline
        expires."

        Design: Difficulty/boundary_precision_check/sla_expiry_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"], urgency="ROUTINE")
        accepted = accept_referral(referral["id"])
        assert_instant_equals(accepted["sla_due_at"], "2026-08-31T00:00:00Z",
                              label="sla_due_at (ROUTINE = +30 days)")

        set_clock("2026-08-30T23:59:59Z")  # one second before the deadline
        validate_success(api.run_aging_sweep(COORD))
        after = get_referral(referral["id"])
        assert after["status"] == "ACCEPTED", (
            "One second before sla_due_at the referral must survive the sweep"
        )

    def test_exactly_at_due_expires(self, api):
        """PRD §3.8: "the boundary is inclusive, so a referral exactly at its
        deadline expires. Expiry moves the referral to `EXPIRED`, creates a
        `LeakageRecord` of category `EXPIRED_UNRESOLVED`, sets `leaked` true,
        increments the attributed provider's `leakage_event_count` with `watch_flag`
        recomputed, cascade-cancels any appointment still in `SCHEDULED` or
        `CONFIRMED` (freeing the slot), and bumps the referral's `version`."

        Design: Difficulty/boundary_precision_check/sla_expiry_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"], urgency="ROUTINE")
        accept_referral(referral["id"])

        set_clock("2026-08-31T00:00:00Z")  # exactly the deadline
        validate_success(api.run_aging_sweep(COORD))
        after = get_referral(referral["id"])
        assert after["status"] == "EXPIRED"
        assert after["leaked"] is True
        records = list_referral_leakage_records(referral["id"])
        assert len(records) == 1
        assert_leakage_record(records[0])
        assert records[0]["category"] == "EXPIRED_UNRESOLVED"


class TestAgingSweepWatchCascade:
    def _setup_two_stat_referrals(self, api):
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap()
        r1 = create_referral(provider["id"], patient["id"], urgency="STAT",
                             diagnosis_code="I21")
        r2 = create_referral(provider["id"], patient["id"], urgency="STAT",
                             diagnosis_code="I22")
        accept_referral(r1["id"])
        accept_referral(r2["id"])
        # Both accepted at 2026-08-01T00:00:00Z -> sla_due_at 2026-08-03T00:00:00Z.
        set_clock("2026-08-03T00:00:00Z")
        return provider, r1, r2

    def test_sweep_expires_due_referrals(self, api):
        """PRD §3.8: "An ops-run aging sweep is the system's housekeeping pass,
        runnable by a `ReferralCoordinator`. It walks qualifying referrals in
        `created_at` ascending order and expires any referral whose status is
        `ACCEPTED`, `SCHEDULED`, `VISIT_COMPLETED`, or `PENDING_VERIFICATION` and
        whose `sla_due_at` has been reached".

        Design: Difficulty/transitive_cascade/aging_sweep_leakage_watch_cascade
        """
        provider, r1, r2 = self._setup_two_stat_referrals(api)
        validate_success(api.run_aging_sweep(COORD))
        assert get_referral(r1["id"])["status"] == "EXPIRED"
        assert get_referral(r2["id"])["status"] == "EXPIRED"
        records = list_provider_leakage_records(provider["id"])
        assert len(records) == 2
        assert {rec["category"] for rec in records} == {"EXPIRED_UNRESOLVED"}

    def test_watch_flag_set_at_two_events(self, api):
        """PRD §3.8: "On the provider side, each created record increments
        `leakage_event_count`; once that count reaches the watch threshold of 2 —
        inclusively — the provider's `watch_flag` becomes true, and it never
        auto-clears, since no decrement path exists."

        Design: Difficulty/transitive_cascade/aging_sweep_leakage_watch_cascade
        """
        provider, r1, r2 = self._setup_two_stat_referrals(api)
        before = get_provider(provider["id"])
        assert before["leakage_event_count"] == 0
        assert before["watch_flag"] is False

        validate_success(api.run_aging_sweep(COORD))
        after = get_provider(provider["id"])
        assert after["leakage_event_count"] == 2
        assert after["watch_flag"] is True, "Threshold of 2 is inclusive"


class TestLeakageExposurePerLineRounding:
    def _setup_two_leaked_ortho_referrals(self, api):
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap(payer_mix_factor=0.801, plan_code="MIX-1")
        r1 = create_referral(provider["id"], patient["id"], specialty="ORTHOPEDICS",
                             diagnosis_code="M17", urgency="ROUTINE")
        r2 = create_referral(provider["id"], patient["id"], specialty="ORTHOPEDICS",
                             diagnosis_code="M54", urgency="URGENT")
        validate_success(api.cancel_referral(
            r1["id"], cancel_referral_payload("PATIENT_WENT_OUT_OF_NETWORK"), COORD
        ))
        validate_success(api.cancel_referral(
            r2["id"], cancel_referral_payload("PATIENT_WENT_OUT_OF_NETWORK"), COORD
        ))
        return provider, r1, r2

    def test_per_line_value_rounded_half_up_at_creation(self, api):
        """PRD §3.8: "Its `estimated_value_cents` is frozen at creation as the
        specialty's base value multiplied by the referral plan's `payer_mix_factor`,
        rounded half-up to whole cents. The per-specialty base values, in cents,
        are: 42,000 for `CARDIOLOGY`; 33,500 for `ORTHOPEDICS`; 50,000 for
        `NEUROLOGY`; 18,000 for `DERMATOLOGY`; 26,000 for `ENDOCRINOLOGY`."
        PRD §3.6: "When the reason is `PATIENT_WENT_OUT_OF_NETWORK` and the referral
        has not already leaked, the cancellation additionally creates a
        `LeakageRecord` of category `PATIENT_CHOICE_OUT_OF_NETWORK`".

        Design: Difficulty/combinatorial_formula/leakage_exposure_per_line_rounding
        """
        provider, r1, r2 = self._setup_two_leaked_ortho_referrals(api)
        for r in (r1, r2):
            records = list_referral_leakage_records(r["id"])
            assert len(records) == 1
            # round_half_up(33500 x 0.801) == round_half_up(26833.5) == 26834.
            assert records[0]["estimated_value_cents"] == 26834, (
                f"Per-line rounding: expected 26834, got {records[0]['estimated_value_cents']}"
            )
            assert records[0]["category"] == "PATIENT_CHOICE_OUT_OF_NETWORK"

    def test_snapshot_exposure_sums_rounded_lines(self, api):
        """PRD §3.8: "The exposure field sums the per-line `estimated_value_cents`
        of the leakage records attached to the intake set's leaked referrals — and
        the rounding order is pinned: each line is rounded to whole cents at its own
        creation, then the integers are summed; summing raw products and rounding
        once at the end is a different number and is not the implemented order."
        PRD §3.8: "The leakage rate is the count of intake referrals with `leaked`
        true divided by the intake count, on the same 4-decimal rounding and
        zero-denominator convention."

        Design: Difficulty/combinatorial_formula/leakage_exposure_per_line_rounding
        """
        provider, r1, r2 = self._setup_two_leaked_ortho_referrals(api)
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.close_period(
            {"period_start": "2026-08-01", "period_end": "2026-09-01"},
            TEST_USERS["network_admin_headers"],
        ), 201)
        data, meta = validate_paginated(
            api.list_snapshots(TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 1
        row = data[0]
        assert row["referring_provider_id"] == provider["id"]
        assert row["leaked_count"] == 2
        assert row["estimated_leakage_exposure_cents"] == 53668, (
            "Per-line-then-sum: 26834 + 26834 == 53668 (NOT sum-then-round 53667)"
        )
        assert row["leakage_rate"] == pytest.approx(1.0, abs=1e-9)
