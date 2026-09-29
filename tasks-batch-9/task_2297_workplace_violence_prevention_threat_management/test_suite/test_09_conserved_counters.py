"""Conserved ledgers: revocation and expiry release exactly what the booking committed."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    add_escort_action,
    add_restriction_action,
    assert_case_action,
    assert_case_state,
    assert_escort_ledger,
    assert_protection,
    assert_restriction_counters,
    assert_sweep_counters,
    assert_total_count,
    build_revocation,
    move_clock,
    read_case,
    read_case_action,
    read_employee,
    read_work_area,
    run_daily_sweep,
    setup_monitoring_case,
    setup_monitoring_case_with_escort,
)


class TestEscortRevocationRestoresTheLedger:
    """The escort ledger returns to zero while the revoked row keeps its committed duration."""

    def _booked_and_revoked(self, api: ApiClient):
        ctx = setup_monitoring_case_with_escort(api)
        ctx["escort_action"] = add_escort_action(
            api, ctx, "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"
        )
        ctx["revoked"] = get_success_data(
            api.revoke_case_action(
                ctx["escort_action"]["id"],
                build_revocation(
                    revocation_reason="Protected employee moved to remote work for the fortnight."
                ),
                ctx["headers"]["security_coordinator"],
            )
        )
        return ctx

    def test_revocation_zeroes_the_ledger_without_erasing_the_duration(
        self, api: ApiClient
    ) -> None:
        """A 240-minute escort takes the ledger to 240 and back to 0, and the row still reads 240.

        PRD: "Revoking a protective measure is a `SecurityCoordinator` action carrying a mandatory `revocation_reason`. It applies to `PROTECTIVE` actions in `SCHEDULED` or `ACTIVE` status — both arms behave identically — and writes `revoked_at` from the logical clock together with the `revocation_reason`, taking the row to `REVOKED`."
        Design: Difficulty/compensating_invariant/escort_revoke_restores_escort_committed_minutes_ledger_to_zero
        """
        ctx = setup_monitoring_case_with_escort(api)

        booked = add_escort_action(api, ctx, "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z")
        assert_case_action(booked, status="SCHEDULED", duration_minutes=240)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 240)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=332.00, protection_status="GAP"
        )

        revoked = get_success_data(
            api.revoke_case_action(
                booked["id"],
                build_revocation(
                    revocation_reason="Protected employee moved to remote work for the fortnight."
                ),
                ctx["headers"]["security_coordinator"],
            )
        )

        assert_case_action(revoked, status="REVOKED", duration_minutes=240)
        assert revoked["revoked_at"] == "2026-08-01T00:00:00Z"
        assert (
            revoked["revocation_reason"]
            == "Protected employee moved to remote work for the fortnight."
        )
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 0)

    def test_a_status_that_was_already_a_gap_appends_no_compensating_review(
        self, api: ApiClient
    ) -> None:
        """Losing partial coverage widens the gap to 336.00 but never flips COVERED to GAP, so nothing is appended.

        PRD: "Because the interval has left the conserved set, the coverage gap is recomputed and `protection_status` may flip from `COVERED` to `GAP`."
        Design: Difficulty/compensating_invariant/escort_revoke_restores_escort_committed_minutes_ledger_to_zero
        """
        ctx = self._booked_and_revoked(api)

        case = read_case(api, ctx)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, status="MONITORING", open_action_count=0)
        assert_total_count(
            api.list_case_actions(
                ctx["headers"]["security_coordinator"],
                {"case_id": ctx["case"]["id"], "auto_generated": True},
            ),
            0,
        )
        assert_case_action(
            read_case_action(api, ctx, ctx["escort_action"]["id"]),
            status="REVOKED",
            duration_minutes=240,
            auto_generated=False,
        )


class TestRestrictionExpiryRestoresBothCounters:
    """The sweep's expiry releases the area counter and the subject counter together."""

    def _restriction_lapsing_overnight(self, api: ApiClient):
        ctx = setup_monitoring_case(api)
        ctx["restriction"] = add_restriction_action(
            api, ctx, "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"
        )
        return ctx

    def test_the_sweep_expires_the_restriction_and_releases_both_counters(
        self, api: ApiClient
    ) -> None:
        """Both counters rise to one on booking and fall back to zero when the sweep expires the row.

        PRD: "Protective measures advance: a `SCHEDULED` protective action whose `starts_at` is at or before the clock while its `ends_at` is still in the future becomes `ACTIVE`; any protective action in `SCHEDULED` or `ACTIVE` whose `ends_at` is at or before the clock becomes `EXPIRED`, releasing its escort minutes and its area restriction as described in §2.11."
        Design: Difficulty/compensating_invariant/access_restriction_expiry_restores_both_restriction_counters
        """
        ctx = self._restriction_lapsing_overnight(api)
        assert_case_action(ctx["restriction"], status="SCHEDULED", duration_minutes=1440)
        assert_restriction_counters(
            read_work_area(api, ctx["work_area"]["id"]),
            read_employee(api, ctx["subj"]["id"]),
            1,
            1,
        )

        move_clock(api, "2026-08-06T00:00:00Z")
        sweep = run_daily_sweep(api)

        assert_sweep_counters(sweep, protective_expired_count=1)
        assert_restriction_counters(
            read_work_area(api, ctx["work_area"]["id"]),
            read_employee(api, ctx["subj"]["id"]),
            0,
            0,
        )

    def test_the_expired_row_keeps_its_duration_and_the_window_is_uncovered_again(
        self, api: ApiClient
    ) -> None:
        """Expiry releases the same credits a revocation would, restoring the full 336.00-hour gap.

        PRD: "A measure in `SCHEDULED` or `ACTIVE` whose `ends_at` has arrived becomes `EXPIRED`, releasing exactly the same credits as a revocation would — escort minutes decremented by `duration_minutes`, area and subject restriction counters decremented by one — and recomputing the owning case's `coverage_gap_hours` and `protection_status`."
        Design: Difficulty/compensating_invariant/access_restriction_expiry_restores_both_restriction_counters
        """
        ctx = self._restriction_lapsing_overnight(api)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=312.00, protection_status="GAP"
        )

        move_clock(api, "2026-08-06T00:00:00Z")
        run_daily_sweep(api)

        expired = read_case_action(api, ctx, ctx["restriction"]["id"])
        assert_case_action(expired, status="EXPIRED", duration_minutes=1440)
        assert expired["revoked_at"] is None
        case = read_case(api, ctx)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, status="MONITORING", open_action_count=0)
