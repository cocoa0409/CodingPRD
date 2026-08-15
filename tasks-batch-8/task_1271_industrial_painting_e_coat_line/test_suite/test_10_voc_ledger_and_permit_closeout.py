"""VOC emission accounting: dual variants, reservation conservation, caps, closeout."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_color_change_payload, create_complete_slot_payload,
    create_customer, create_spec, create_paint_line, create_stage, create_permit,
    create_and_accept_lot, schedule_slot,
    setup_master_data, setup_lot_scheduled, setup_lot_running, setup_lot_curing,
    create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx,
    get_line, get_permit, get_lot, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestMeteredVsTheoreticalDivergence:
    def test_one_run_yields_different_kg_under_the_two_variants(self, api):
        """PRD §3.9: "Because it reasons from part area and film window rather than
        metered liters, identical production yields a different kilogram figure than
        the metered variant of §3.5 — the difference the closeout exists to reconcile."
        PRD §3.5: "The scheduler reports the `paint_used_liters` actually drawn, and
        the same request posts a `PAINT_USAGE_METERED` emission entry under the
        **metered** variant: the entry's `voc_kg` is the metered liters multiplied by
        the specification's `voc_g_per_l`, divided by 1000, rounded half-up to three
        decimal places."

        Design: Difficulty/dual_variant_calc/voc_metered_vs_theoretical_diverge
        """
        ctx = setup_lot_running()
        slot = ctx["slot"]
        # THEORETICAL reservation: 100 parts x 12 dm2 x 24 um x 1e-5 / (0.35 x 0.95)
        # = 86.766 L x 320 g/L / 1000 = 0.277 kg.
        assert slot["voc_projected_kg"] == pytest.approx(0.277, abs=1e-9)
        permit_mid = get_permit(ctx["permit"]["id"])
        assert permit_mid["reserved_kg"] == pytest.approx(0.277, abs=1e-9)

        validate_success(
            api.complete_run_slot(slot["id"], create_complete_slot_payload(paint_used_liters=0.95),
                                  SCHED),
            200,
        )
        # METERED posting: 0.95 L x 320 g/L / 1000 = 0.304 kg.
        entries = validate_success(api.list_emission_entries(ADMIN), 200)
        assert len(entries) == 1
        assert entries[0]["entry_variant"] == "METERED"
        assert entries[0]["source_type"] == "PAINT_USAGE_METERED"
        assert entries[0]["voc_kg"] == pytest.approx(0.304, abs=1e-9)
        assert entries[0]["voc_kg"] != slot["voc_projected_kg"]

        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["used_kg"] == pytest.approx(0.304, abs=1e-9)
        assert permit_after["reserved_kg"] == pytest.approx(0.0, abs=1e-9)

    def test_metered_entry_links_to_its_lot_and_variant(self, api):
        """PRD §3.9: "Lot-linked entries — paint usage and strip solvent — set
        `source_lot_id`; purge entries set `source_color_change_id`; the remaining
        references stay null. Entries can be listed per permit, or globally with
        optional `permit_id`, `source_lot_id`, and `source_color_change_id` filters."
        PRD §3.9: "Each entry carries the `permit_id` of the permit whose period
        contains the entry timestamp, a `source_type` of `PAINT_USAGE_METERED`,
        `PURGE_SOLVENT`, `STRIP_SOLVENT`, or `CLOSEOUT_ADJUSTMENT`, a signed `voc_kg`
        in three-decimal half-up arithmetic — the closeout adjustment may be negative —
        and an `entry_variant` of `METERED`, `THEORETICAL`, or `ADJUSTMENT` identifying
        which computation produced it: the run-completion posting is `METERED`, and the
        reconciliation posting is `ADJUSTMENT`."

        Design: Difficulty/dual_variant_calc/voc_metered_vs_theoretical_diverge
        """
        ctx = setup_lot_curing(paint_used_liters=0.95)
        entries = validate_success(
            api.list_emission_entries(ADMIN, params={"source_lot_id": ctx["lot"]["id"]}), 200
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry["source_type"] == "PAINT_USAGE_METERED"
        assert entry["entry_variant"] == "METERED"
        assert entry["permit_id"] == ctx["permit"]["id"]
        assert entry["voc_kg"] == pytest.approx(0.304, abs=1e-9)
        # The slot keeps its THEORETICAL projection snapshot even after settlement.
        slot_after = validate_success(api.get_run_slot(ctx["slot"]["id"], SCHED), 200)
        assert slot_after["voc_projected_kg"] == pytest.approx(0.277, abs=1e-9)

    def test_metered_rounding_to_three_decimals(self, api):
        """PRD §2.8: "**VOC quantities** are kilograms carried to exactly three
        decimal places, rounded half-up per ledger posting."
        PRD §3.5: "The scheduler reports the `paint_used_liters` actually drawn, and
        the same request posts a `PAINT_USAGE_METERED` emission entry under the
        **metered** variant: the entry's `voc_kg` is the metered liters multiplied by
        the specification's `voc_g_per_l`, divided by 1000, rounded half-up to three
        decimal places."

        Design: Corner/calculations/voc_metered_rounding_three_decimals
        """
        ctx = setup_lot_running()
        validate_success(
            api.complete_run_slot(ctx["slot"]["id"],
                                  create_complete_slot_payload(paint_used_liters=0.47), SCHED),
            200,
        )
        # 0.47 L x 320 / 1000 = 0.1504 -> 0.150 at three-decimal half-up.
        entries = validate_success(api.list_emission_entries(ADMIN), 200)
        assert len(entries) == 1
        assert entries[0]["voc_kg"] == pytest.approx(0.150, abs=1e-9)
        assert entries[0]["entry_variant"] == "METERED"
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["used_kg"] == pytest.approx(0.150, abs=1e-9)
        assert permit_after["reserved_kg"] == pytest.approx(0.0, abs=1e-9)


class TestUsedKgReconciliation:
    def test_used_kg_reconciles_after_each_posting(self, api):
        """PRD §2.10: "`used_kg` is the sum of `voc_kg` over all emission entries
        posted to the permit — actual, posted fact."
        PRD §3.8: "On success the purge VOC is posted to the permit as a
        `PURGE_SOLVENT` emission entry — with `source_color_change_id` set to this
        event — `used_kg` grows, the automatic `EXCEEDED` check runs, the line's
        `current_color_code` becomes `to_color_code`, and the line's `version`
        increments by one."

        Design: Corner/cross_cutting_layers/derived_used_kg_reconciles_after_each_posting
        """
        ctx = setup_lot_running()
        validate_success(
            api.complete_run_slot(ctx["slot"]["id"],
                                  create_complete_slot_payload(paint_used_liters=0.95), SCHED),
            200,
        )
        used_after_run = get_permit(ctx["permit"]["id"])["used_kg"]
        assert used_after_run == pytest.approx(0.304, abs=1e-9)

        validate_success(
            api.create_color_change(
                create_color_change_payload(
                    ctx["line"]["id"], to_color_code="RAL1018", purge_solvent_liters=1.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        # 1.0 L x 880 / 1000 = 0.880; 0.304 + 0.880 = 1.184.
        used_after_purge = get_permit(ctx["permit"]["id"])["used_kg"]
        assert used_after_purge == pytest.approx(1.184, abs=1e-9)


class TestReservationConservation:
    def test_schedule_then_cancel_conserves_reserved_kg(self, api):
        """PRD §3.5: "Cancelling a slot, available only from `SCHEDULED`, moves it to
        the terminal `CANCELLED`, returns the lot to `QUEUED` so it can be scheduled
        again, and releases the reservation by the same `voc_projected_kg` amount — the
        compensating action that keeps `reserved_kg` conserved."
        PRD §2.10: "`reserved_kg` is the sum of `voc_projected_kg` over run slots in
        `SCHEDULED` or `RUNNING` status whose reservation was taken against this permit
        — a forward-looking commitment that is released when the slot completes or is
        cancelled, so the reservation balance is conserved across the slot lifecycle."

        Design: Difficulty/compensating_invariant/voc_reservation_schedule_cancel_conserved
        """
        ctx = setup_lot_scheduled()
        permit_mid = get_permit(ctx["permit"]["id"])
        assert permit_mid["reserved_kg"] == pytest.approx(0.277, abs=1e-9)

        cancelled = validate_success(api.cancel_run_slot(ctx["slot"]["id"], SCHED), 200)
        assert cancelled["status"] == "CANCELLED"

        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["reserved_kg"] == pytest.approx(0.0, abs=1e-9)
        assert permit_after["used_kg"] == pytest.approx(0.0, abs=1e-9)

        entries = validate_success(
            api.list_emission_entries_of_permit(ctx["permit"]["id"], ADMIN), 200
        )
        assert len(entries) == 0

        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["status"] == "QUEUED"

    def test_reservation_settles_to_metered_used_on_completion(self, api):
        """PRD §3.5: "The reservation is settled in the same motion — the permit's
        `reserved_kg` is reduced by the slot's `voc_projected_kg` while `used_kg` grows
        by the posted amount — and if `used_kg` now exceeds `cap_kg` the permit flips
        automatically to `EXCEEDED`."

        Design: Difficulty/compensating_invariant/voc_reservation_schedule_cancel_conserved
        """
        ctx = setup_lot_running()
        validate_success(
            api.complete_run_slot(ctx["slot"]["id"],
                                  create_complete_slot_payload(paint_used_liters=0.95), SCHED),
            200,
        )
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["reserved_kg"] == pytest.approx(0.0, abs=1e-9)
        assert permit_after["used_kg"] == pytest.approx(0.304, abs=1e-9)


class TestVocCapBoundary:
    def test_exact_cap_equality_allowed_then_over_rejected(self, api):
        """PRD §2.10: "The capacity rule is uniform for every operation that would add
        emission: the permit covering the current logical clock must exist and not be
        `CLOSED` (its period is the half-open interval beginning at `period_start`,
        inclusive, and ending at `period_end`, exclusive), and the sum of `used_kg`
        plus `reserved_kg` plus the new emission must not exceed `cap_kg` — strictly
        greater rejects with `ERR_VOC_CAP_EXCEEDED`, while landing exactly on the cap
        is permitted."

        Design: Difficulty/boundary_precision_check/voc_cap_exact_equality_allowed_then_exceeded
        """
        ctx = setup_lot_curing(paint_used_liters=12.875,
                               permit_overrides={"cap_kg": 5.0})
        # Metered: 12.875 L x 320 / 1000 = 4.120 kg used.
        assert get_permit(ctx["permit"]["id"])["used_kg"] == pytest.approx(4.120, abs=1e-9)

        # First purge: 1.0 L -> 0.880 kg; 4.120 + 0.880 == 5.000 == cap -> allowed.
        cc1 = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    ctx["line"]["id"], to_color_code="RAL1018", purge_solvent_liters=1.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        assert cc1["purge_voc_kg"] == pytest.approx(0.880, abs=1e-9)
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["used_kg"] == pytest.approx(5.000, abs=1e-9)
        assert permit_after["status"] == "ACTIVE"

        # Second purge: 0.1 L -> 0.088 kg; 5.000 + 0.088 = 5.088 > 5.000 -> rejected.
        res = api.create_color_change(
            create_color_change_payload(
                ctx["line"]["id"], to_color_code="RAL6005", purge_solvent_liters=0.1,
                window_start_utc="2026-05-07T08:00:00Z",
                window_end_utc="2026-05-07T09:00:00Z",
            ),
            SCHED,
        )
        validate_error(res, "ERR_VOC_CAP_EXCEEDED", expected_status=409)

    def test_projection_over_cap_at_schedule_rejected_and_nothing_reserved(self, api):
        """PRD §2.10: "The capacity rule is uniform for every operation that would add
        emission: the permit covering the current logical clock must exist and not be
        `CLOSED` (its period is the half-open interval beginning at `period_start`,
        inclusive, and ending at `period_end`, exclusive), and the sum of `used_kg`
        plus `reserved_kg` plus the new emission must not exceed `cap_kg` — strictly
        greater rejects with `ERR_VOC_CAP_EXCEEDED`, while landing exactly on the cap
        is permitted."

        Design: Difficulty/boundary_precision_check/voc_cap_exact_equality_allowed_then_exceeded
        """
        ctx = setup_master_data(permit_overrides={"cap_kg": 0.2})
        lot = create_and_accept_lot_in_ctx(ctx)
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_VOC_CAP_EXCEEDED", expected_status=409)
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["reserved_kg"] == pytest.approx(0.0, abs=1e-9)
        assert permit_after["used_kg"] == pytest.approx(0.0, abs=1e-9)


class TestPermitCloseGuards:
    def test_close_before_period_end_rejected(self, api):
        """PRD §3.9: "Closing a period is a `PlantAdmin` act with two preconditions:
        the permit must still be `ACTIVE` or `EXCEEDED` — closing a `CLOSED` permit is
        rejected with `ERR_PERMIT_PERIOD_CLOSED` — and the current logical clock must
        have passed `period_end`, else `ERR_PERMIT_NOT_EXPIRED`."

        Design: Corner/state_machines/permit_close_before_period_end_returns_not_expired
        """
        permit = create_permit()  # 2026-05-01 -> 2026-06-01; clock still at default
        res = api.close_voc_permit(permit["id"], ADMIN)
        validate_error(res, "ERR_PERMIT_NOT_EXPIRED", expected_status=409)
        assert get_permit(permit["id"])["status"] == "ACTIVE"

    def test_close_twice_rejected_period_closed(self, api):
        """PRD §3.9: "Closing a period is a `PlantAdmin` act with two preconditions:
        the permit must still be `ACTIVE` or `EXCEEDED` — closing a `CLOSED` permit is
        rejected with `ERR_PERMIT_PERIOD_CLOSED` — and the current logical clock must
        have passed `period_end`, else `ERR_PERMIT_NOT_EXPIRED`."

        Design: Corner/state_machines/permit_close_twice_returns_period_closed
        """
        permit = create_permit()
        set_clock("2026-06-01T00:00:01Z")
        closed = validate_success(api.close_voc_permit(permit["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"
        assert closed["used_kg"] == pytest.approx(0.0, abs=1e-9)

        res = api.close_voc_permit(permit["id"], ADMIN)
        validate_error(res, "ERR_PERMIT_PERIOD_CLOSED", expected_status=409)


class TestCloseoutCascade:
    def test_closeout_adjustment_flips_permit_to_exceeded(self, api):
        """PRD §3.9: "The close posts the reconciliation: a single
        `CLOSEOUT_ADJUSTMENT` entry whose `voc_kg` is the theoretical total minus the
        metered total, rounded half-up to three decimal places."
        PRD §3.9: "The permit's `used_kg` is then recomputed as the sum of all its
        entries, and the outcome turns on the cap: if the recomputed `used_kg` exceeds
        `cap_kg`, the permit lands in `EXCEEDED` — the automatic transition applies
        even mid-close — and only a period at or under its cap settles into the
        terminal `CLOSED`."

        Design: Difficulty/transitive_cascade/permit_closeout_adjustment_exceeds_cap_cascade
        """
        ctx = setup_lot_curing(paint_used_liters=7.0, part_quantity=1000,
                               permit_overrides={"cap_kg": 3.0})
        # Metered posting: 7.0 L x 320 / 1000 = 2.240 kg.
        assert get_permit(ctx["permit"]["id"])["used_kg"] == pytest.approx(2.240, abs=1e-9)

        # Purge 0.5 L -> 0.440 kg; used 2.240 + 0.440 = 2.680 <= 3.000 cap.
        validate_success(
            api.create_color_change(
                create_color_change_payload(
                    ctx["line"]["id"], to_color_code="RAL1018", purge_solvent_liters=0.5,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        assert get_permit(ctx["permit"]["id"])["used_kg"] == pytest.approx(2.680, abs=1e-9)

        set_clock("2026-06-01T00:00:01Z")
        closed_res = validate_success(api.close_voc_permit(ctx["permit"]["id"], ADMIN), 200)

        # Theoretical total: 1000 x 12 x 24 x 1e-5 / (0.35 x 0.95) x 320 / 1000 = 2.772.
        # Adjustment = 2.772 - 2.240 = 0.532; used = 2.680 + 0.532 = 3.212 > 3.000.
        assert closed_res["status"] == "EXCEEDED"
        assert closed_res["used_kg"] == pytest.approx(3.212, abs=1e-9)

        entries = validate_success(
            api.list_emission_entries_of_permit(ctx["permit"]["id"], ADMIN), 200
        )
        adjustments = [e for e in entries if e["source_type"] == "CLOSEOUT_ADJUSTMENT"]
        assert len(adjustments) == 1
        assert adjustments[0]["entry_variant"] == "ADJUSTMENT"
        assert adjustments[0]["voc_kg"] == pytest.approx(0.532, abs=1e-9)

    def test_close_at_or_under_cap_settles_closed(self, api):
        """PRD §3.9: "The permit's `used_kg` is then recomputed as the sum of all its
        entries, and the outcome turns on the cap: if the recomputed `used_kg` exceeds
        `cap_kg`, the permit lands in `EXCEEDED` — the automatic transition applies
        even mid-close — and only a period at or under its cap settles into the
        terminal `CLOSED`."

        Design: Difficulty/transitive_cascade/permit_closeout_adjustment_exceeds_cap_cascade
        """
        ctx = setup_lot_curing(paint_used_liters=0.95)  # metered 0.304; cap 500
        set_clock("2026-06-01T00:00:01Z")
        closed_res = validate_success(api.close_voc_permit(ctx["permit"]["id"], ADMIN), 200)
        assert closed_res["status"] == "CLOSED"
        entries = validate_success(
            api.list_emission_entries_of_permit(ctx["permit"]["id"], ADMIN), 200
        )
        adjustments = [e for e in entries if e["source_type"] == "CLOSEOUT_ADJUSTMENT"]
        assert len(adjustments) == 1
        assert adjustments[0]["entry_variant"] == "ADJUSTMENT"
