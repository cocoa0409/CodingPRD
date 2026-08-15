"""Expiry sweep, posture cascade depth, pinned evaluation order, termination
cascades, hiring prerequisites, and expiry-monitoring buckets
(PRD §2.5, §3.1, §3.5, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_unit_counters,
    book_shift,
    create_certification,
    create_nurse,
    create_requirement,
    create_unit,
    get_license,
    get_nurse,
    get_packet,
    get_shift,
    get_unit,
    record_completion,
    run_sweep,
    set_clock,
    setup_approved_packet,
    setup_credentialed_nurse,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
CO1 = TEST_USERS["compliance_1"]


class TestSweepLicenseExpiryCascadeDepth4:
    """Difficulty instance: sweep_license_expiry_cascade_depth4 — license EXPIRED
    (hop 1) -> posture SCHEDULING_SUSPENDED (hop 2) -> future shift AUTO_CANCELLED
    (hop 3) -> unit counters decremented (hop 4)."""

    def _setup_sara_and_sweep(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Sara Sweep", email="sara.sweep@x.com")
        unit = create_unit(name="MED", required_cert_types=[])
        nurse = ctx["nurse"]
        # Move the clock past the license (2027-06-30) and BLS (2027-03-31) expiry but
        # before the competency lapse (2027-07-15). The future shift is booked after
        # the clock move — the nurse's stored posture is still CLEAR and her stored
        # credential statuses are untouched by the clock (PRD §2.5) — so its start lies
        # after the sweep instant and the cascade can reach it.
        set_clock("2027-07-01T00:00:00Z")
        shift = book_shift(nurse["id"], unit["id"],
                           "2027-08-10T07:00:00Z", "2027-08-10T19:00:00Z")
        summary = run_sweep()
        return ctx, unit, shift, summary

    def test_sweep_summary_and_hops_1_2(self):
        """PRD §3.9: "First, licenses standing `ACTIVE` or `ENCUMBERED` whose
        `expires_on` has passed move to `EXPIRED`. Second, `ACTIVE` certifications past
        expiry move to `EXPIRED`, firing the packet-item invalidation cascade of §3.7.
        Third, `CURRENT` completions past expiry move to `LAPSED` with the same
        cascade. Fourth, the posture of every affected nurse recomputes, firing the
        posture cascade of §3.5 wherever the posture flips."
        PRD §3.9: "Its response summarizes the run as counts — `licenses_expired`,
        `certifications_expired`, `completions_lapsed`, `postures_changed`,
        `shifts_auto_cancelled`, `packets_voided`, and
        `privilege_evaluations_appended`."

        Design: Difficulty/transitive_cascade/sweep_license_expiry_cascade_depth4
        """
        ctx, _unit, _shift, summary = self._setup_sara_and_sweep()
        assert summary["licenses_expired"] == 1
        assert summary["certifications_expired"] == 1
        assert summary["completions_lapsed"] == 0, (
            "the completion is valid through 2027-07-15 inclusive"
        )
        assert summary["postures_changed"] == 1
        assert summary["shifts_auto_cancelled"] == 1
        assert summary["packets_voided"] == 0

        assert get_license(ctx["license"]["id"])["status"] == "EXPIRED", "hop 1"
        assert get_nurse(ctx["nurse"]["id"])["credential_posture"] == "SCHEDULING_SUSPENDED", (
            "hop 2, caused by the license/cert mutations"
        )

    def test_sweep_cascade_hops_3_4_unit_counters(self):
        """PRD §3.5: "When the flip is away from `CLEAR`, the posture cascade fires
        exactly once: every shift assignment still `SCHEDULED` with a start after the
        current instant is auto-cancelled with `cancel_reason`
        `POSTURE_SCHEDULING_SUSPENDED` or `POSTURE_PRACTICE_RESTRICTED` matching the
        new posture; each such cancellation decrements its unit's
        `scheduled_hours_total` and `active_assignment_count`; and every packet
        standing `APPROVED` moves to `VOIDED`."

        Design: Difficulty/transitive_cascade/sweep_license_expiry_cascade_depth4
        """
        ctx, unit, shift, summary = self._setup_sara_and_sweep()
        after = get_shift(shift["id"])
        assert after["status"] == "AUTO_CANCELLED", "hop 3, caused by the posture flip"
        assert after["cancel_reason"] == "POSTURE_SCHEDULING_SUSPENDED"
        unit_after = get_unit(unit["id"])
        assert_unit_counters(unit_after, 0.0, 0)  # hop 4


class TestPostureFixpointSnapshotOrder:
    """Difficulty instance: posture_evaluation_fixpoint_snapshot_order — the
    unit-derived requirement set is snapshotted BEFORE the cascade cancels future
    shifts, so the ACLS deficit that triggered the suspension still counts."""

    def _setup_pia_and_sweep(self):
        set_clock()
        req = create_requirement(code="ANNUAL_SKILLS", name="Annual Skills",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        unit = create_unit(name="ICU", required_cert_types=["ACLS"])
        ctx = setup_credentialed_nurse(full_name="Pia Fix", email="pia.fix@x.com",
                                       requirement=req)
        nurse = ctx["nurse"]
        acls = create_certification(nurse["id"], "ACLS", obtained_on="2025-09-01",
                                    expires_on="2026-08-31")
        # Re-activate is unnecessary: cert creation recomputes posture; Pia is CLEAR.
        shift = book_shift(nurse["id"], unit["id"],
                           "2026-09-10T07:00:00Z", "2026-09-10T19:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        summary = run_sweep()
        return ctx, unit, acls, shift, summary

    def test_snapshot_taken_before_cascade_cancellation(self):
        """PRD §3.5: "Before anything else is examined, the unit-derived requirement
        set is snapshotted: the union of `required_cert_types` over every unit holding
        at least one of this nurse's shift assignments in `SCHEDULED` or `IN_PROGRESS`
        at that instant. Cancellations fired later within the same evaluation do not
        shrink this snapshot, so a single trigger cannot oscillate; a later recompute
        may clear the nurse after remediation."

        Design: Difficulty/combinatorial_formula/posture_evaluation_fixpoint_snapshot_order
        """
        ctx, unit, _acls, shift, summary = self._setup_pia_and_sweep()
        assert summary["certifications_expired"] == 1
        assert summary["licenses_expired"] == 0
        assert summary["completions_lapsed"] == 0
        assert summary["postures_changed"] == 1
        assert summary["shifts_auto_cancelled"] == 1

        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["credential_posture"] == "SCHEDULING_SUSPENDED", (
            "the ACLS deficit still counts within this evaluation even though the "
            "cascade cancelled the ICU shift that contributed it"
        )
        after = get_shift(shift["id"])
        assert after["status"] == "AUTO_CANCELLED"
        assert after["cancel_reason"] == "POSTURE_SCHEDULING_SUSPENDED"
        assert get_unit(unit["id"])["scheduled_hours_total"] == 0.0

    def test_remediation_recompute_clears_nurse(self):
        """PRD §3.4: "Renewal moves a certification from `EXPIRED` back to `ACTIVE` —
        renewal from any other state is `ERR_INVALID_CERTIFICATION_STATE` — with a
        `new_expires_on` strictly after the current date, else
        `ERR_INVALID_DATE_RANGE`. Renewal recomputes posture but does not resurrect
        invalidated packet items; those need fresh evidence."
        PRD §3.5: "Otherwise she is `CLEAR`."

        Design: Difficulty/combinatorial_formula/posture_evaluation_fixpoint_snapshot_order
        """
        ctx, _unit, acls, _shift, _summary = self._setup_pia_and_sweep()
        assert get_nurse(ctx["nurse"]["id"])["credential_posture"] == "SCHEDULING_SUSPENDED"

        renewed = validate_success(
            api_client.renew_certification(
                acls["id"], {"new_expires_on": "2027-08-31"}, SPEC1
            ),
            200,
        )
        assert renewed["status"] == "ACTIVE"
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["credential_posture"] == "CLEAR", (
            "a fresh recompute sees the remediated cert; the unit requirement set is "
            "now empty (the cancelled assignment left the snapshot set)"
        )


class TestSweepIdempotency:
    def test_sweep_second_run_idempotent(self):
        """PRD §3.9: "The sweep is idempotent: a second run at the same clock changes
        nothing."
        PRD §2.5: "Setting the clock mutates no entity: licenses, certifications, and
        completions do not expire merely because the clock advanced past their dates."

        Design: Corner/endpoints/sweep_second_run_idempotent
        """
        set_clock()
        ctx = setup_credentialed_nurse(
            full_name="Idem Potent", email="idem.potent@x.com",
            license_expires_on="2026-08-10", activate=False,
        )
        lic = ctx["license"]
        set_clock("2026-08-11T00:00:00Z")

        first = run_sweep()
        assert first["licenses_expired"] == 1
        assert get_license(lic["id"])["status"] == "EXPIRED"

        second = run_sweep()
        for key in ("licenses_expired", "certifications_expired", "completions_lapsed",
                    "postures_changed", "shifts_auto_cancelled", "packets_voided",
                    "privilege_evaluations_appended"):
            assert second[key] == 0, f"second sweep must change nothing: {key}"


class TestTerminationCascades:
    def test_nurse_terminate_cascades_shifts_and_packets(self):
        """PRD §3.1: "Termination cascades within the same request. Every shift
        assignment still `SCHEDULED` whose start lies in the future is auto-cancelled —
        its status becomes `AUTO_CANCELLED` with `cancel_reason` `NURSE_TERMINATED` —
        and each such cancellation decrements its unit's `scheduled_hours_total` by the
        assignment's `hours` and its `active_assignment_count` by 1. Every credential
        packet in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` moves to
        `VOIDED`. The nurse's `credential_posture` is forced to `SCHEDULING_SUSPENDED`
        as the terminal snapshot."

        Design: Corner/state_machines/nurse_terminate_cascades_shifts_and_packets
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Ter Minate", email="ter.minate@x.com",
                                       employment_type="TRAVEL")
        nurse = ctx["nurse"]
        unit = create_unit(name="MED", required_cert_types=[])
        packet_ctx = setup_approved_packet(nurse["id"], unit["id"])
        shift = book_shift(nurse["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        assert_unit_counters(get_unit(unit["id"]), 12.0, 1)

        terminated = validate_success(api_client.terminate_nurse(nurse["id"], SPEC1), 200)
        assert terminated["status"] == "TERMINATED"
        assert terminated["credential_posture"] == "SCHEDULING_SUSPENDED"

        after_shift = get_shift(shift["id"])
        assert after_shift["status"] == "AUTO_CANCELLED"
        assert after_shift["cancel_reason"] == "NURSE_TERMINATED"
        assert_unit_counters(get_unit(unit["id"]), 0.0, 0)
        assert get_packet(packet_ctx["packet"]["id"])["status"] == "VOIDED"

    def test_nurse_terminate_twice_rejected(self):
        """PRD §3.1: "Termination moves a nurse from either `ONBOARDING` or `ACTIVE` to
        `TERMINATED`; terminating an already `TERMINATED` nurse is rejected with
        `ERR_INVALID_NURSE_STATE`."

        Design: Corner/validations/nurse_terminate_twice_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Term Twice", email="term.twice@x.com")
        first = validate_success(api_client.terminate_nurse(nurse["id"], SPEC1), 200)
        assert first["status"] == "TERMINATED"

        resp = api_client.terminate_nurse(nurse["id"], SPEC1)
        validate_error(resp, ApiErrorId.ERR_INVALID_NURSE_STATE)
        assert get_nurse(nurse["id"])["status"] == "TERMINATED"

    def test_hire_activate_without_license_rejected(self):
        """PRD §3.1: "Two hiring prerequisites must hold, both reported as
        `ERR_HIRE_REQUIREMENTS_UNMET`: at least one of the nurse's state licenses
        stands `ACTIVE`, and the derived `practice_scope` contains the facility state
        (§3.5)."

        Design: Corner/validations/hire_activate_without_license_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="No License", email="no.license@x.com")
        resp = api_client.activate_nurse(nurse["id"], SPEC1)
        validate_error(resp, ApiErrorId.ERR_HIRE_REQUIREMENTS_UNMET)
        assert get_nurse(nurse["id"])["status"] == "ONBOARDING"


class TestExpiryMonitoringBuckets:
    def test_monitoring_bucket_boundaries(self):
        """PRD §3.9: "For each credential row it computes `days_to_expiry`, the
        whole-day difference from the current date to the row's `expires_on`, negative
        once the date has passed, and buckets it: `EXPIRED` when the difference is
        negative, `CRITICAL` from zero up to and including 30 days, `WARNING` beyond 30
        up to and including 60 days, and `OK` beyond 60."
        PRD §3.9: "The report includes licenses in `VERIFIED`, `ACTIVE`, `ENCUMBERED`,
        or `EXPIRED` — never `DRAFT` or `PENDING_VERIFICATION` — certifications in
        `ACTIVE` or `EXPIRED` (never `REVOKED`), and completions in `CURRENT` or
        `LAPSED` (never `SUPERSEDED`)."
        PRD §3.9: "An optional `nurse_id` narrows the report to one nurse, and rows
        sort by `days_to_expiry` ascending, ties broken by `created_at` ascending."

        Design: Corner/calculations/monitoring_bucket_boundaries
        """
        set_clock()
        nurse = create_nurse(full_name="Mona Buckets", email="mona.buckets@x.com")
        create_certification(nurse["id"], "BLS", obtained_on="2025-08-31",
                             expires_on="2026-08-31")   # 30 days
        create_certification(nurse["id"], "ACLS", obtained_on="2025-09-01",
                             expires_on="2026-09-01")   # 31 days
        create_certification(nurse["id"], "PALS", obtained_on="2025-09-30",
                             expires_on="2026-09-30")   # 60 days
        create_certification(nurse["id"], "CCRN", issuing_body="AACN",
                             obtained_on="2025-10-01",
                             expires_on="2026-10-01")   # 61 days
        cnor = create_certification(nurse["id"], "CNOR", issuing_body="CCI",
                                    obtained_on="2025-09-15", expires_on="2026-09-15")
        validate_success(api_client.revoke_certification(cnor["id"], CO1), 200)

        resp = api_client.get_expiry_report(CO1, params={"nurse_id": nurse["id"]})
        data = validate_success(resp, 200)
        rows = data.get("rows", data) if isinstance(data, dict) else data
        assert len(rows) == 4, "the REVOKED CNOR cert is excluded from the input set"
        days = [row["days_to_expiry"] for row in rows]
        buckets = [row["bucket"] for row in rows]
        assert days == [30, 31, 60, 61], "rows sort by days_to_expiry ascending"
        assert buckets == ["CRITICAL", "WARNING", "WARNING", "OK"], (
            "day 30 is CRITICAL, days 31 and 60 are WARNING, day 61 is OK"
        )
