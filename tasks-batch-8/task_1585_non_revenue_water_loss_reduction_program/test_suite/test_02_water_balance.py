"""Water balance lifecycle: provisional vs audited NRW, ILI, balance
consistency, overlap arithmetic, OCC, and terminal lockdown (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    PINNED_BALANCE,
    TEST_DEFAULTS,
    assert_dma,
    assert_water_balance_period,
    create_dma,
    create_submitted_balance,
    create_water_balance_period,
    finalize_water_balance_period,
    get_dma,
    make_field_supervisor_headers,
    make_utility_analyst_headers,
    setup_dma_with_finalized_balance,
    submit_water_balance_period,
    validate_error,
    validate_success,
)

UA = TEST_DEFAULTS["UTILITY_ANALYST"]
UA2 = TEST_DEFAULTS["UTILITY_ANALYST_ALT"]


class TestProvisionalVsAuditedNrw:
    def test_provisional_variant_reports_raw_percentage(self, api,
                                                        utility_analyst_headers):
        """PRD §3.2: "While the period is in `DRAFT` or `SUBMITTED`, the stored
        `nrw_pct` is exactly this base percentage, rounded half-up to 2 decimal
        places — the **provisional variant**." and "The non-revenue water volume
        `nrw_volume_m3` is the system input volume minus the billed authorized
        consumption. The apparent loss `apparent_loss_m3` is the sum of the
        unauthorized-consumption and metering-inaccuracy components."

        Design: Difficulty/dual_variant_calc/water_balance_provisional_vs_audited_nrw
        """
        dma = create_dma(code="DMA-DV1", name="Dual Variant One",
                         connection_count=5000, mains_length_km=120.0,
                         target_nrw_pct=20.0)
        period = create_water_balance_period(dma["id"], creator=UA)

        draft = validate_success(
            api.get_water_balance_period(period["id"], utility_analyst_headers), 200
        )
        assert_water_balance_period(draft)
        assert draft["status"] == "DRAFT"
        assert draft["nrw_volume_m3"] == pytest.approx(
            PINNED_BALANCE["NRW_VOLUME_M3"], abs=0.01
        )
        assert draft["apparent_loss_m3"] == pytest.approx(
            PINNED_BALANCE["APPARENT_LOSS_M3"], abs=0.01
        )
        assert draft["real_loss_m3"] == pytest.approx(
            PINNED_BALANCE["REAL_LOSS_M3"], abs=0.01
        )
        assert draft["nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_PROVISIONAL"], abs=0.01
        )
        assert draft["ili"] is None

        submitted = submit_water_balance_period(period["id"], user=UA)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_PROVISIONAL"], abs=0.01
        ), "submission recomputes the provisional figures"

    def test_audited_variant_subtracts_confidence_adjustment(self, api):
        """PRD §3.2: "At finalization the `nrw_pct` is recomputed under the
        **audited variant**: a confidence adjustment is subtracted from the base
        percentage, where the adjustment is the smaller of one-half of a
        percentage point (0.50) and one tenth of the base percentage itself, and
        the result is rounded half-up to 2 decimal places — so identical inputs
        report a slightly lower NRW once audited." and "Finalization also
        computes the period's `ili`, the **Infrastructure Leakage Index**, which
        is null on unfinalized periods."

        Design: Difficulty/dual_variant_calc/water_balance_provisional_vs_audited_nrw
        """
        dma = create_dma(code="DMA-DV1B", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_water_balance_period(dma["id"], creator=UA)
        submit_water_balance_period(period["id"], user=UA)

        finalized = finalize_water_balance_period(period["id"], user=UA2)
        assert finalized["status"] == "FINALIZED"
        assert finalized["nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_AUDITED"], abs=0.01
        )
        assert finalized["ili"] == pytest.approx(PINNED_BALANCE["ILI"], abs=0.01)


class TestIliComputation:
    def test_ili_uses_uarl_constants(self, api):
        """PRD §3.2: "the baseline UARL, in cubic metres per year, is the sum of
        18 per service connection, 0.8 per kilometre of mains, and 25 times the
        standard average zone pressure of 40 metres of head, with the sum
        divided by 1000 and then multiplied by 365; the current annual real loss
        is the period's `real_loss_m3` scaled by 365 divided by the period's
        length in whole days (the count of days between `period_start` and
        `period_end`); the ratio of the two is rounded half-up to 2 decimal
        places and, should the rounded value fall below 0.01, floored at 0.01."

        Design: Corner/calculations/ili_floor_and_constants
        """
        dma, finalized = setup_dma_with_finalized_balance(code="DMA-CALC1")
        assert finalized["status"] == "FINALIZED"
        assert finalized["ili"] == pytest.approx(PINNED_BALANCE["ILI"], abs=0.01)
        assert finalized["real_loss_m3"] == pytest.approx(
            PINNED_BALANCE["REAL_LOSS_M3"], abs=0.01
        )
        assert finalized["apparent_loss_m3"] == pytest.approx(
            PINNED_BALANCE["APPARENT_LOSS_M3"], abs=0.01
        )
        assert finalized["nrw_volume_m3"] == pytest.approx(
            PINNED_BALANCE["NRW_VOLUME_M3"], abs=0.01
        )


class TestImmediateConsistency:
    def test_finalize_response_and_dma_read_show_derived_fields(self, api,
                                                                utility_analyst_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "Finalization then updates the parent DMA: `latest_nrw_pct` is
        set from this period when its `period_end` is the latest among finalized
        siblings"

        Design: Corner/consistency_model/immediate_consistency_of_derived_fields
        """
        dma = create_dma(code="DMA-IMM", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_water_balance_period(dma["id"], creator=UA)
        submit_water_balance_period(period["id"], user=UA)

        finalized = finalize_water_balance_period(period["id"], user=UA2)
        # The finalize response itself already carries the audited figures.
        assert finalized["nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_AUDITED"], abs=0.01
        )
        assert finalized["ili"] == pytest.approx(PINNED_BALANCE["ILI"], abs=0.01)

        dma_after = validate_success(
            api.get_dma(dma["id"], utility_analyst_headers), 200
        )
        assert_dma(dma_after)
        assert dma_after["latest_nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_AUDITED"], abs=0.01
        )


class TestTerminalLockdown:
    def test_finalized_period_rejects_further_finalize(self, api):
        """PRD §2.7: "State-machine validity — the target entity is in a
        from-state that permits the invoked transition, and terminal states
        reject every transition; failure yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/water_balance_terminal_finalize_rejects_further_transitions
        """
        dma, finalized = setup_dma_with_finalized_balance(code="DMA-SM1")
        assert finalized["status"] == "FINALIZED"

        res = api.finalize_water_balance_period(
            finalized["id"], make_utility_analyst_headers(UA2)
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        reread = validate_success(
            api.get_water_balance_period(
                finalized["id"], make_utility_analyst_headers(UA)
            ),
            200,
        )
        assert reread["status"] == "FINALIZED"


class TestBalanceConsistency:
    def test_inconsistent_balance_rejected_at_submit(self, api):
        """PRD §3.2: "Submission moves a period from `DRAFT` to `SUBMITTED` and
        is allowed only while the parent DMA is not `FROZEN` and the computed
        `real_loss_m3` remainder reconciles — that is, the billed authorized,
        unbilled authorized, and apparent-loss components together must not
        exceed the system input volume; a period whose raw remainder would be
        negative is rejected at submission with `ERR_BALANCE_INCONSISTENT`
        (HTTP 422)."

        Design: Corner/validations/balance_inconsistent_submit_rejected
        """
        dma = create_dma(code="DMA-VAL1", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_water_balance_period(
            dma["id"],
            creator=UA,
            billed_authorized_m3=900000,
            unbilled_authorized_m3=50000,
            unauthorized_consumption_m3=40000,
            metering_inaccuracy_m3=30000,
        )
        res = api.submit_water_balance_period(
            period["id"], make_utility_analyst_headers(UA)
        )
        validate_error(res, ApiErrorId.ERR_BALANCE_INCONSISTENT, expected_status=422)

        reread = validate_success(
            api.get_water_balance_period(
                period["id"], make_utility_analyst_headers(UA)
            ),
            200,
        )
        assert reread["status"] == "DRAFT"


class TestHalfOpenOverlap:
    def test_touching_boundary_accepted(self, api):
        """PRD §3.2: "two balance periods for the same DMA whose statuses lie in
        `DRAFT`, `SUBMITTED`, or `FINALIZED` must never overlap — though
        adjacent periods sharing exactly one boundary instant are permitted,
        since the end of one period may coincide with the start of the next."

        Design: Difficulty/resource_temporal_overlap/water_balance_half_open_touching_allowed_overlap_rejected
        """
        dma = create_dma(code="DMA-TO1", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        first = create_water_balance_period(dma["id"], creator=UA)
        assert first["status"] == "DRAFT"

        second = create_water_balance_period(
            dma["id"],
            creator=UA,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            system_input_volume_m3=900000,
            billed_authorized_m3=700000,
            unbilled_authorized_m3=30000,
            unauthorized_consumption_m3=12000,
            metering_inaccuracy_m3=20000,
        )
        assert_water_balance_period(second)
        assert second["dma_id"] == dma["id"]

    def test_overlapping_period_rejected(self, api):
        """PRD §3.2: "two balance periods for the same DMA whose statuses lie in
        `DRAFT`, `SUBMITTED`, or `FINALIZED` must never overlap — though
        adjacent periods sharing exactly one boundary instant are permitted,
        since the end of one period may coincide with the start of the next.
        Violations surface as `ERR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/water_balance_half_open_touching_allowed_overlap_rejected
        """
        dma = create_dma(code="DMA-TO1B", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        create_water_balance_period(dma["id"], creator=UA)
        create_water_balance_period(
            dma["id"],
            creator=UA,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            system_input_volume_m3=900000,
            billed_authorized_m3=700000,
            unbilled_authorized_m3=30000,
            unauthorized_consumption_m3=12000,
            metering_inaccuracy_m3=20000,
        )

        dma_fresh = get_dma(dma["id"])
        res = api.create_water_balance_period(
            {
                "dma_id": dma["id"],
                "period_start": "2026-06-30T23:00:00Z",
                "period_end": "2026-10-01T00:00:00Z",
                "system_input_volume_m3": 800000,
                "billed_authorized_m3": 600000,
                "unbilled_authorized_m3": 25000,
                "unauthorized_consumption_m3": 10000,
                "metering_inaccuracy_m3": 18000,
                "expected_dma_version": dma_fresh["version"],
            },
            make_utility_analyst_headers(UA),
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_CONFLICT, expected_status=409)


class TestOptimisticConcurrencyOnCreate:
    def test_stale_dma_version_rejected_then_fresh_retry_succeeds(
        self, api, utility_analyst_headers
    ):
        """PRD §2.10: "If the DMA's current `version` has advanced since that
        observation — for instance because another writer submitted a balance
        for an overlapping window, which legitimately recomputed the DMA's
        posture — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.2: "creation populates the computed fields described below under
        the provisional variant, appends an audit event, and — because the DMA
        gains a child — increments the parent DMA's `version` by one."

        Design: Corner/cross_cutting_layers/occ_stale_dma_version_rejected
        """
        dma = create_dma(code="DMA-OCC1", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        observed_v0 = dma["version"]

        # First create succeeds and advances the parent DMA version by one.
        first = create_water_balance_period(
            dma["id"], expected_dma_version=observed_v0, creator=UA
        )
        assert first["status"] == "DRAFT"
        dma_after_first = get_dma(dma["id"])
        assert dma_after_first["version"] == observed_v0 + 1

        # Replaying the stale observation is rejected.
        stale_res = api.create_water_balance_period(
            {
                "dma_id": dma["id"],
                "period_start": "2026-04-01T00:00:00Z",
                "period_end": "2026-07-01T00:00:00Z",
                "system_input_volume_m3": 900000,
                "billed_authorized_m3": 700000,
                "unbilled_authorized_m3": 30000,
                "unauthorized_consumption_m3": 12000,
                "metering_inaccuracy_m3": 20000,
                "expected_dma_version": observed_v0,
            },
            utility_analyst_headers,
        )
        validate_error(stale_res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Re-reading the parent and retrying with the fresh version succeeds.
        retry = create_water_balance_period(
            dma["id"],
            creator=UA,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            system_input_volume_m3=900000,
            billed_authorized_m3=700000,
            unbilled_authorized_m3=30000,
            unauthorized_consumption_m3=12000,
            metering_inaccuracy_m3=20000,
        )
        assert retry["status"] == "DRAFT"


class TestRbacOnFinalize:
    def test_field_supervisor_cannot_finalize_balance(self, api):
        """PRD §2.1: "A request whose role is recognized but not on the
        endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/field_supervisor_cannot_finalize_balance
        """
        dma = create_dma(code="DMA-RB1", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_submitted_balance(dma["id"], creator=UA)
        assert period["status"] == "SUBMITTED"

        res = api.finalize_water_balance_period(
            period["id"], make_field_supervisor_headers("fs-9")
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        reread = validate_success(
            api.get_water_balance_period(
                period["id"], make_utility_analyst_headers(UA)
            ),
            200,
        )
        assert reread["status"] == "SUBMITTED"
