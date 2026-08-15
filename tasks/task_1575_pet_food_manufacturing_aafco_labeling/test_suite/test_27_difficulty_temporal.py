"""Difficulty: resource/temporal overlap — the half-open line-schedule window
and the registration slot lifecycle (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_production_batch,
    get_registration,
    make_regulatory_affairs_headers,
    setup_locked_formula,
    state_registration_payload,
    validate_error,
    validate_success,
)


class TestLineScheduleHalfOpenWindowConflict:
    def _setup_three_batches(self, api):
        """Batches X (08:00), Y (15:59), Z (16:00) on LINE-G, same LOCKED
        formula; X is released first (window [08:00, 16:00))."""
        ctx = setup_locked_formula()
        x = create_production_batch(
            ctx["formula"]["id"], planned_kg=400.0, line_id="LINE-G",
            scheduled_start="2026-08-15T08:00:00Z",
        )
        y = create_production_batch(
            ctx["formula"]["id"], planned_kg=400.0, line_id="LINE-G",
            scheduled_start="2026-08-15T15:59:00Z",
        )
        z = create_production_batch(
            ctx["formula"]["id"], planned_kg=400.0, line_id="LINE-G",
            scheduled_start="2026-08-15T16:00:00Z",
        )
        return ctx, x, y, z

    def test_overlapping_window_rejected(self, api, production_planner_headers):
        """PRD §3.5: "Fourth, the line-schedule gate: the batch's production
        window is the half-open interval beginning at its `scheduled_start` and
        extending eight hours, and that window must not intersect the
        corresponding window of any other batch on the same `line_id` currently
        in `RELEASED_FOR_PRODUCTION` or `IN_PROCESS`; a conflict is rejected with
        `ERR_LINE_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/line_schedule_half_open_window_conflict
        """
        _ctx, x, y, _z = self._setup_three_batches(api)
        validate_success(api.release_batch(x["id"], production_planner_headers))
        # Y starts at 15:59, one minute inside X's [08:00, 16:00) window.
        resp = api.release_batch(y["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT.value)

    def test_touching_window_boundary_admitted(self, api, production_planner_headers):
        """PRD §3.5: "Because the interval is half-open, back-to-back batches
        that merely touch at the boundary — one ending exactly when the other
        begins — are allowed."

        Design: Difficulty/resource_temporal_overlap/line_schedule_half_open_window_conflict
        """
        _ctx, x, _y, z = self._setup_three_batches(api)
        validate_success(api.release_batch(x["id"], production_planner_headers))
        # Z starts at 16:00, exactly when X's half-open window ends.
        released = validate_success(api.release_batch(z["id"], production_planner_headers))
        assert released["status"] == "RELEASED_FOR_PRODUCTION"


class TestRegistrationResubmitAfterRejectionWindow:
    def _setup_rejected_tx_registration(self, api, state_regulator_headers):
        """LOCKED formula (CAT profile); TX registration R1 walked to REJECTED."""
        ctx = setup_locked_formula(
            species="CAT",
            profile_overrides={
                "crude_protein_min_pct": 30.0,
                "crude_fat_min_pct": 12.0,
                "crude_fiber_max_pct": 3.0,
                "moisture_max_pct": 10.0,
                "calcium_min_pct": 1.0,
                "phosphorus_min_pct": 0.8,
            },
        )
        ra = make_regulatory_affairs_headers(ctx["brand"]["id"])
        r1 = validate_success(
            api.create_state_registration(
                ctx["formula"]["id"],
                state_registration_payload(state_code="TX", tonnage_tier=3.0),
                ra,
            ),
            expected_status=201,
        )
        validate_success(api.accept_registration_for_review(r1["id"], state_regulator_headers))
        rejected = validate_success(api.reject_registration(r1["id"], state_regulator_headers))
        assert rejected["status"] == "REJECTED"
        return ctx, r1, ra

    def test_resubmit_recomputes_fee_from_fresh_tier(
        self, api, state_regulator_headers
    ):
        """PRD §3.7: "A `RegulatoryAffairs` specialist may resubmit a `REJECTED`
        registration, moving it back to `SUBMITTED`; resubmission requires the
        formula to be `SUBSTANTIATED` or `LOCKED`, carries a fresh
        `tonnage_tier`, and recomputes `fee_cents` from the fee schedule."
        PRD §3.7: "The annual registration fee is assessed in integer cents from a
        per-state base — 7500 cents for CA, 6000 cents for TX, 8000 cents for NY,
        and a default of 5000 cents for any other state — scaled by the declared
        tonnage tier."
        PRD §3.7: "50 tons or more pays double."

        Design: Difficulty/resource_temporal_overlap/registration_resubmit_after_rejection_window
        """
        _ctx, r1, ra = self._setup_rejected_tx_registration(api, state_regulator_headers)
        # Fresh tonnage of 60 tons (>= 50) pays double (PRD §3.7).
        resubmitted = validate_success(
            api.resubmit_registration(r1["id"], {"tonnage_tier": 60.0}, ra)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["fee_cents"] == 12000  # TX base 6000 x 2.0

    def test_fresh_duplicate_state_submission_rejected(
        self, api, state_regulator_headers
    ):
        """PRD §3.1: "Uniqueness is enforced platform-wide with
        `ERR_DUPLICATE_KEY` (HTTP 409): the `fein` across brand owners, the
        `fsma_facility_id` across suppliers, the `aafco_name` across ingredients,
        the `protocol_code` across feeding-trial protocols, the `formula_code`
        within each brand owner, and the `state_code` within each formula's
        registrations."
        PRD §3.7: "The request names the `state_code` (exactly two uppercase
        letters, unique within the formula's registrations)"

        Design: Difficulty/resource_temporal_overlap/registration_resubmit_after_rejection_window
        """
        ctx, r1, ra = self._setup_rejected_tx_registration(api, state_regulator_headers)
        validate_success(api.resubmit_registration(r1["id"], {"tonnage_tier": 60.0}, ra))
        assert get_registration(r1["id"])["status"] == "SUBMITTED"

        dup = api.create_state_registration(
            ctx["formula"]["id"],
            state_registration_payload(state_code="TX", tonnage_tier=3.0),
            ra,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_KEY.value)
