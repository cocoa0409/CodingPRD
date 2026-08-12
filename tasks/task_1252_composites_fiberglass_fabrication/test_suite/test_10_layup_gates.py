"""Layup gating: mold availability, permit coverage, and validation precedence."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_batch,
    create_layup_session_payload,
    create_work_order_payload,
    demold,
    release_work_order,
    run_cure,
    schedule_cure,
    set_clock,
    setup_shop,
    setup_work_order_awaiting_cure,
    setup_work_order_cured,
    setup_work_order_in_layup,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

LAM = TEST_USERS["laminator_headers"]
SM = TEST_USERS["shop_manager_headers"]
TE = TEST_USERS["tooling_engineer_headers"]
CT = TEST_USERS["cure_technician_headers"]


class TestStartLayupMoldGate:
    def _setup_worn_mold(self, api, put_in_maintenance: bool):
        """Interval-1 mold worn to MAINTENANCE_DUE by WO-G1's completed cure,
        demolded; WO-G2 released against the same mold (release is still allowed).
        Optionally walks the mold into IN_MAINTENANCE."""
        ctx = setup_work_order_cured(
            mold_overrides={
                "mold_code": "MOLD-G1",
                "maintenance_interval_cycles": 1,
                "tooling_phase": "PRODUCTION",
            },
            work_order_overrides={"work_order_no": "WO-G1"},
            batch_overrides={"batch_code": "BATCH-G1"},
        )
        demold(ctx, 2000.0)
        mold = validate_success(api.get_mold(ctx["mold"]["id"], TE), 200)
        assert mold["status"] == "MAINTENANCE_DUE"
        if put_in_maintenance:
            validate_success(api.start_mold_maintenance(ctx["mold"]["id"], TE), 200)
        set_clock("2026-06-01T10:00:01Z")  # strictly after WO-G1's demold
        wo2 = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    ctx["mold"]["id"],
                    ctx["ply_book"]["id"],
                    work_order_no="WO-G2",
                ),
                SM,
            ),
            201,
        )
        return ctx, wo2

    def test_start_layup_rejected_on_maintenance_due_mold(self, api):
        """PRD §2.9: "starting layup and scheduling a first, mold-bearing cure both
        require the mold to be `ACTIVE`, failing with the same
        `ERR_MOLD_NOT_AVAILABLE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/start_layup_gated_on_mold_active
        """
        _, wo2 = self._setup_worn_mold(api, put_in_maintenance=False)
        res = api.start_layup(wo2["id"], LAM)
        validate_error(res, ApiErrorId.ERR_MOLD_NOT_AVAILABLE, expected_status=409)

    def test_failed_start_layup_leaves_order_released(self, api):
        """PRD §2.9: "starting layup and scheduling a first, mold-bearing cure both
        require the mold to be `ACTIVE`". The refused transition leaves the order
        untouched in `RELEASED`; with the mold walked further into `IN_MAINTENANCE`
        the same gate still answers `ERR_MOLD_NOT_AVAILABLE` (only `ACTIVE` admits).

        Design: Difficulty/cross_entity_state_dependency/start_layup_gated_on_mold_active
        """
        _, wo2 = self._setup_worn_mold(api, put_in_maintenance=True)
        res = api.start_layup(wo2["id"], LAM)
        validate_error(res, ApiErrorId.ERR_MOLD_NOT_AVAILABLE, expected_status=409)
        order = validate_success(api.get_work_order(wo2["id"], LAM), 200)
        assert order["status"] == "RELEASED"


class TestPermitCoverageGate:
    def test_start_layup_without_clock_rejected_no_active_permit(self, api):
        """PRD §2.5: "Before any client interaction, the clock starts at exactly
        2026-05-01T00:00:00Z." PRD §3.4: "an `ACTIVE` emission permit must cover the
        current logical time, and the occupancy rule must hold, with the three
        failures surfacing as `ERR_MOLD_NOT_AVAILABLE`, `ERR_NO_ACTIVE_PERMIT`, and
        `ERR_MOLD_OCCUPANCY_CONFLICT` respectively." The default clock precedes the
        June permit's window.

        Design: Corner/validations/start_layup_without_clock_rejected_no_active_permit
        """
        # No clock call: logical time stays at the 2026-05-01 default.
        shop = setup_shop(
            set_clock_to=None,
            mold_overrides={"mold_code": "MOLD-DF1", "tooling_phase": "PRODUCTION"},
        )
        order = release_work_order(shop, work_order_no="WO-DF1")
        res = api.start_layup(order["id"], LAM)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_PERMIT, expected_status=409)


class TestValidationPrecedence:
    def test_state_beats_safety_on_layup_session(self, api):
        """PRD §2.11: "On the two guarded patch endpoints the optimistic-concurrency
        check (`ERR_STALE_VERSION`) then runs, followed by state-machine legality
        (`ERR_INVALID_STATE`, including the draft-only guards `ERR_PLY_BOOK_NOT_DRAFT`
        and the batch-usability guard `ERR_RESIN_BATCH_NOT_USABLE`). Layup compliance
        gates come after that (`ERR_NO_ACTIVE_PERMIT`, `ERR_PERMIT_QUOTA_EXCEEDED`,
        `ERR_RESIN_POT_LIFE_EXPIRED`)". The order is `RELEASED` (state violation)
        and the batch is two hours past its pot life (safety violation); the state
        tier fires first. PRD §3.4: "The work order must be in `LAYUP_IN_PROGRESS`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_layup_session
        """
        shop = setup_shop(
            mold_overrides={"mold_code": "MOLD-P1", "tooling_phase": "PRODUCTION"}
        )
        order = release_work_order(shop, work_order_no="WO-P1")
        batch = create_batch(batch_code="BATCH-P1", nominal_pot_life_minutes=60)
        set_clock("2026-06-01T12:00:00Z")  # batch expired two hours after mixing
        res = api.create_layup_session(
            create_layup_session_payload(order["id"], batch["id"], resin_used_g=100),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_state_violation_alone_yields_same_error(self, api):
        """PRD §3.4: "The work order must be in `LAYUP_IN_PROGRESS`" and
        PRD §2.11 ranks state-machine legality (`ERR_INVALID_STATE`) ahead of the
        layup compliance gates. With a fresh, fully usable batch the same state
        violation still surfaces `ERR_INVALID_STATE`, isolating the tier.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_layup_session
        """
        shop = setup_shop(
            mold_overrides={"mold_code": "MOLD-P1B", "tooling_phase": "PRODUCTION"}
        )
        order = release_work_order(shop, work_order_no="WO-P1B")
        batch = create_batch(batch_code="BATCH-P1B")  # 600-minute pot life, fresh
        res = api.create_layup_session(
            create_layup_session_payload(order["id"], batch["id"], resin_used_g=100),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def _setup_quota_vs_mismatch(self, api):
        """WO-P2 in LAYUP_IN_PROGRESS against an EPOXY book; POLYESTER batch;
        permit quota 0.005 kg so a 250 g session (0.0088 kg) breaches it."""
        return setup_work_order_in_layup(
            permit_overrides={"permit_code": "PER-TINY2", "styrene_quota_kg": 0.005},
            mold_overrides={"mold_code": "MOLD-P2", "tooling_phase": "PRODUCTION"},
            ply_book_overrides={
                "part_number": "PN-200",
                "part_area_m2": 1.0,
                "plies": [
                    {
                        "seq": 1,
                        "material_code": "GF-450",
                        "orientation_deg": 0,
                        "areal_weight_g_m2": 450,
                    }
                ],
                "resin_system": "EPOXY",
            },
            work_order_overrides={"work_order_no": "WO-P2", "part_number": "PN-200"},
            batch_overrides={"batch_code": "BATCH-P2"},  # POLYESTER batch
        )

    def test_safety_beats_constraint_on_layup_session(self, api):
        """PRD §2.11: "Layup compliance gates come after that (`ERR_NO_ACTIVE_PERMIT`,
        `ERR_PERMIT_QUOTA_EXCEEDED`, `ERR_RESIN_POT_LIFE_EXPIRED`), then the
        cross-entity configuration gates". PRD §3.4: "the batch's `resin_system`
        must match the chemistry of the work order's pinned ply book, else
        `ERR_RESIN_SYSTEM_MISMATCH`". The session would breach the 0.005 kg quota
        (post-add 0.0088 > quota) and also mix POLYESTER into an EPOXY book; the
        quota gate fires first.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_layup_session
        """
        ctx = self._setup_quota_vs_mismatch(api)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=250
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_QUOTA_EXCEEDED, expected_status=409)

    def test_quota_rejection_posts_nothing_to_permit(self, api, ehs_officer_headers):
        """PRD §2.11: "Layup compliance gates come after that (`ERR_NO_ACTIVE_PERMIT`,
        `ERR_PERMIT_QUOTA_EXCEEDED`, `ERR_RESIN_POT_LIFE_EXPIRED`), then the
        cross-entity configuration gates". PRD §2.8: "Consumption accumulates into
        the computed `styrene_used_kg`, which is always the sum of the stored
        per-session `styrene_emitted_kg` values of the sessions in `ACTIVE` status
        posted to that permit". The refused session posts nothing, so the permit
        still reads 0.0 and stays `ACTIVE`.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_layup_session
        """
        ctx = self._setup_quota_vs_mismatch(api)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=250
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_QUOTA_EXCEEDED, expected_status=409)
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == 0.0
        assert permit["status"] == "ACTIVE"

    def test_resin_system_mismatch_rejected(self, api):
        """PRD §3.4: "the batch's `resin_system` must match the chemistry of the
        work order's pinned ply book, else `ERR_RESIN_SYSTEM_MISMATCH`". With a
        generous quota the safety gate passes and the mismatch surfaces.

        Design: Corner/validations/resin_system_mismatch_rejected
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-RM1", "tooling_phase": "PRODUCTION"},
            ply_book_overrides={
                "part_number": "PN-300",
                "part_area_m2": 1.0,
                "plies": [
                    {
                        "seq": 1,
                        "material_code": "GF-450",
                        "orientation_deg": 0,
                        "areal_weight_g_m2": 450,
                    }
                ],
                "resin_system": "EPOXY",
            },
            work_order_overrides={"work_order_no": "WO-RM1", "part_number": "PN-300"},
            batch_overrides={"batch_code": "BATCH-RM1"},  # POLYESTER batch
        )
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=100
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_SYSTEM_MISMATCH, expected_status=409)
