"""Fuel tax credit claims: provisional vs final variants, pinned rounding
order, the reject/reopen cycle, submission gates, period overlap, and terminal
lockdown (PRD §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dispenser,
    approve_inspection,
    authorize_and_complete,
    authorize_session_ok,
    calibrate,
    complete_inspection,
    complete_session_ok,
    create_account_with_card,
    create_active_station,
    create_claim,
    create_inspection,
    create_pricing_policy,
    create_station,
    make_fleet_driver_headers,
    set_clock,
    setup_fueling_ready,
    setup_settled_session_scenario,
    validate_error,
    validate_success,
    void_session_ok,
)

SM = TEST_USERS["station_manager_headers"]


class TestClaimDualVariant:
    """Difficulty instance: claim_provisional_vs_final_divergence (two tests).

    Station with a calibrated CNG dispenser (+0.50% -> factor 0.995) and an
    uncalibrated RNG dispenser (factor 1.0); two July sessions swept to
    SETTLED, one August session still COMPLETED.
    """

    def _setup(self, api):
        env = create_active_station(station_name="Beta", station_code="ST-BETA")
        station_id = env["station"]["id"]
        dsp_r = add_dispenser(station_id, dispenser_code="DSP-R", fuel_type="RNG")
        dsp_c = env["dispensers"][0]
        calibrate(dsp_c["id"], 0.50)  # PASS -> correction_factor 0.995
        create_pricing_policy(station_id, fuel_type="CNG", price_per_gge_cents=289)
        create_pricing_policy(station_id, fuel_type="RNG", price_per_gge_cents=289)
        party = create_account_with_card()
        env.update(party)  # expose account + card on env for test bodies
        card_id = party["card"]["id"]

        set_clock("2026-07-10T12:00:00Z")
        # C1: 26.0 kg CNG -> prov 10.129 / settled 10.078 (factor 0.995).
        s1 = authorize_and_complete(card_id, dsp_c["id"], "CR-C1", 26.0)
        # R1: 20.0 kg RNG -> 7.791 both (uncalibrated).
        s2 = authorize_and_complete(card_id, dsp_r["id"], "CR-R1", 20.0)
        # Advance across the month boundary so C1/R1 settle.
        set_clock("2026-08-01T00:00:00Z")
        set_clock("2026-08-05T12:00:00Z")
        # C2: 13.0 kg CNG -> prov 5.064 / settled 5.039; stays COMPLETED (same month).
        s3 = authorize_and_complete(card_id, dsp_c["id"], "CR-C2", 13.0)
        claim = create_claim(
            station_id,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        )
        return env, claim, s1, s2, s3

    def test_provisional_variant_includes_completed_and_uses_provisional_gge(self, api):
        """PRD §3.9: "The provisional variant, computed at creation and again
        at reopen, draws on the station's COMPLETED and SETTLED non-voided
        sessions whose `completed_at` falls inside the claim period, summing
        their `provisional_gge` into `eligible_gge_provisional` and pricing
        them into `claim_amount_provisional_cents`."
        PRD §3.9: "Credit rates are fixed at fifty cents per GGE for CNG volume
        and one hundred cents per GGE for RNG volume, each session's fuel type
        coming from its dispenser."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_divergence
        """
        _env, claim, s1, s2, s3 = self._setup(api)
        # (10.129 + 5.064) * 50 + 7.791 * 100 = 1538.75 -> half-up 1539.
        assert claim["claim_amount_provisional_cents"] == 1539
        assert claim["eligible_gge_provisional"] == pytest.approx(22.984, abs=1e-9)

    def test_final_variant_settled_only_with_correction(self, api):
        """PRD §3.9: "Finalization — which requires the claim to be DRAFT, else
        `ERR_CLAIM_NOT_FINALIZABLE` (HTTP 409) — computes the final variant:
        only SETTLED sessions in the period, using their calibration-corrected
        `settled_gge`, and excluding any session already captured by another
        claim at the same station in FINALIZED, SUBMITTED, or APPROVED status,
        which prevents double-claiming."
        PRD §2.5: "Any COMPLETED fueling session whose
        `completed_at` month is strictly earlier than the current calendar
        month moves to SETTLED and is stamped with `settled_at`."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_divergence
        """
        env, claim, s1, s2, s3 = self._setup(api)
        driver = make_fleet_driver_headers(env["card"]["id"])
        s1_after = validate_success(api.get_fueling_session(s1["id"], driver), 200)
        s2_after = validate_success(api.get_fueling_session(s2["id"], driver), 200)
        s3_after = validate_success(api.get_fueling_session(s3["id"], driver), 200)
        assert s1_after["status"] == "SETTLED"
        assert s2_after["status"] == "SETTLED"
        assert s3_after["status"] == "COMPLETED"

        finalized = validate_success(
            api.finalize_tax_credit_claim(claim["id"], SM), 200
        )
        # 10.078 * 50 + 7.791 * 100 = 503.9 + 779.1 = 1283.0; C2 excluded.
        assert finalized["claim_amount_final_cents"] == 1283
        assert finalized["eligible_gge_final"] == pytest.approx(17.869, abs=1e-9)


class TestClaimRoundingOrder:
    """Difficulty instance: claim_per_session_rounding_order (two tests)."""

    def _setup(self):
        env = setup_fueling_ready(station_name="Delta", station_code="ST-DELTA")
        card_id = env["card"]["id"]
        dispenser_id = env["dispenser"]["id"]
        # Three August sessions of exactly 1.0 kg: per-session 1.0/2.567 = 0.390.
        sessions = [
            authorize_and_complete(card_id, dispenser_id, f"CR-R{i}", 1.0, 5.0)
            for i in (1, 2, 3)
        ]
        claim = create_claim(
            env["station"]["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        )
        return env, sessions, claim

    def test_per_session_rounded_gge_summed(self, api):
        """PRD §3.9: "Rounding order is pinned: each session's GGE was already
        rounded to three decimal places at completion; the per-session rounded
        values are summed per fuel type with no re-rounding of the sums; and
        the claim amount is the CNG sum times fifty plus the RNG sum times one
        hundred, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/claim_per_session_rounding_order
        """
        _env, sessions, claim = self._setup()
        for s in sessions:
            assert s["provisional_gge"] == pytest.approx(0.390, abs=1e-9), (
                "per-session round of 1.0/2.567 = 0.3896"
            )
        assert claim["eligible_gge_provisional"] == pytest.approx(1.170, abs=1e-9), (
            "0.390 + 0.390 + 0.390"
        )

    def test_amount_uses_summed_rounded_gge_not_mass_aggregation(self, api):
        """PRD §3.9: "Rounding order is pinned: each session's GGE was already
        rounded to three decimal places at completion; the per-session rounded
        values are summed per fuel type with no re-rounding of the sums; and
        the claim amount is the CNG sum times fifty plus the RNG sum times one
        hundred, rounded half-up to a whole cent. Aggregating metered mass
        across sessions and converting once is forbidden — per-session rounded
        GGE values are the only admissible inputs."

        Design: Difficulty/combinatorial_formula/claim_per_session_rounding_order
        """
        _env, _sessions, claim = self._setup()
        # 1.170 * 50 = 58.5 -> round_half_up 59; sum-then-convert would yield 58.
        assert claim["claim_amount_provisional_cents"] == 59


class TestClaimReopenCycle:
    """Difficulty instance: claim_rejected_reopen_cycle (two tests)."""

    def _setup(self, api, station_manager_headers, compliance_officer_headers,
               network_operator_headers):
        env = setup_settled_session_scenario(
            station_name="Foxtrot", station_code="ST-FOX", metered_mass_kg=26.0
        )
        claim = create_claim(
            env["station"]["id"],
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        )
        return env, claim

    def test_reject_then_reopen_returns_draft_and_recomputes(
        self, api, station_manager_headers, compliance_officer_headers,
        network_operator_headers
    ):
        """PRD §3.9: "A rejected claim is not dead: a `StationManager` may
        reopen it, which requires REJECTED status else
        `ERR_CLAIM_NOT_REOPENABLE` (HTTP 409), returning it to DRAFT,
        recomputing the provisional fields from current session data, and
        clearing both final fields back to null."

        Design: Difficulty/non_linear_state_machine/claim_rejected_reopen_cycle
        """
        _env, claim = self._setup(
            api, station_manager_headers, compliance_officer_headers,
            network_operator_headers,
        )
        fin1 = validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        # SETTLED-only settled GGE 10.078 x 50 = 503.9 -> half-up 504.
        assert fin1["claim_amount_final_cents"] == 504
        validate_success(
            api.submit_tax_credit_claim(claim["id"], compliance_officer_headers), 200
        )
        validate_success(
            api.decide_tax_credit_claim(
                claim["id"],
                {"outcome": "REJECTED", "reason": "missing manifest attestation"},
                network_operator_headers,
            ),
            200,
        )
        reopened = validate_success(
            api.reopen_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        assert reopened["status"] == "DRAFT", "cycle REJECTED -> DRAFT traversed"
        fin2 = validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        assert fin2["claim_amount_final_cents"] == 504, (
            "re-finalize after reopen recomputes to the identical amount"
        )

    def test_full_cycle_reaches_approved(
        self, api, station_manager_headers, compliance_officer_headers,
        network_operator_headers
    ):
        """PRD §3.9: "A submitted claim awaits decision by a `NetworkOperator`,
        who supplies an `outcome` and an optional `reason`; deciding requires
        SUBMITTED status, else `ERR_CLAIM_NOT_DECIDABLE` (HTTP 409). The claim
        lands APPROVED — terminal — or REJECTED, with the supplied text
        recorded as `decision_reason` in either case."

        Design: Difficulty/non_linear_state_machine/claim_rejected_reopen_cycle
        """
        _env, claim = self._setup(
            api, station_manager_headers, compliance_officer_headers,
            network_operator_headers,
        )
        validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        validate_success(
            api.submit_tax_credit_claim(claim["id"], compliance_officer_headers), 200
        )
        validate_success(
            api.decide_tax_credit_claim(
                claim["id"], {"outcome": "REJECTED", "reason": "r"}, network_operator_headers
            ),
            200,
        )
        validate_success(api.reopen_tax_credit_claim(claim["id"], station_manager_headers), 200)
        validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        validate_success(
            api.submit_tax_credit_claim(claim["id"], compliance_officer_headers), 200
        )
        decided = validate_success(
            api.decide_tax_credit_claim(
                claim["id"], {"outcome": "APPROVED"}, network_operator_headers
            ),
            200,
        )
        assert decided["status"] == "APPROVED", "terminal reached after the loop"


class TestClaimApprovedLockdown:
    def test_claim_approved_terminal_lockdown(
        self, api, station_manager_headers, compliance_officer_headers,
        network_operator_headers
    ):
        """PRD §3.9: "A submitted claim awaits decision by a `NetworkOperator`,
        who supplies an `outcome` and an optional `reason`; deciding requires
        SUBMITTED status, else `ERR_CLAIM_NOT_DECIDABLE` (HTTP 409). The claim
        lands APPROVED — terminal — or REJECTED, with the supplied text
        recorded as `decision_reason` in either case. A rejected claim is not
        dead: a `StationManager` may reopen it, which requires REJECTED status
        else `ERR_CLAIM_NOT_REOPENABLE` (HTTP 409), returning it to DRAFT,
        recomputing the provisional fields from current session data, and
        clearing both final fields back to null."

        Design: Corner/state_machines/claim_approved_terminal_lockdown
        """
        env = setup_settled_session_scenario(
            station_name="CLock", station_code="ST-CLOCK", metered_mass_kg=26.0
        )
        claim = create_claim(env["station"]["id"])
        validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        validate_success(
            api.submit_tax_credit_claim(claim["id"], compliance_officer_headers), 200
        )
        validate_success(
            api.decide_tax_credit_claim(
                claim["id"], {"outcome": "APPROVED"}, network_operator_headers
            ),
            200,
        )
        resp_decision = api.decide_tax_credit_claim(
            claim["id"], {"outcome": "REJECTED"}, network_operator_headers
        )
        validate_error(resp_decision, ApiErrorId.ERR_CLAIM_NOT_DECIDABLE, 409)
        resp_reopen = api.reopen_tax_credit_claim(claim["id"], station_manager_headers)
        validate_error(resp_reopen, ApiErrorId.ERR_CLAIM_NOT_REOPENABLE, 409)
        after = validate_success(
            api.get_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        assert after["status"] == "APPROVED"


class TestClaimSubmitGates:
    def test_claim_submit_blocked_by_overdue_inspection(
        self, api, station_manager_headers, compliance_officer_headers
    ):
        """PRD §3.9: "Submission by a `ComplianceOfficer` requires the claim to
        be FINALIZED, else `ERR_CLAIM_NOT_SUBMITTABLE` (HTTP 409); the station
        must be ACTIVE, else `ERR_STATION_NOT_ACTIVE`; and no inspection at the
        station may be OVERDUE, else `ERR_OVERDUE_INSPECTION`."

        Design: Corner/validations/claim_submit_blocked_by_overdue_inspection
        """
        env = setup_settled_session_scenario(
            station_name="Gate", station_code="ST-GATE", metered_mass_kg=26.0,
            after_iso="2026-08-01T06:00:00Z",
        )
        claim = create_claim(env["station"]["id"])
        validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        inspection = create_inspection(
            env["station"]["id"], scheduled_for="2026-08-02T10:00:00Z"
        )
        set_clock("2026-08-03T00:00:00Z")

        resp = api.submit_tax_credit_claim(claim["id"], compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_OVERDUE_INSPECTION, 409)

        complete_inspection(inspection["id"], "PASS", "sm-500")
        approve_inspection(inspection["id"], "co-500")
        submitted = validate_success(
            api.submit_tax_credit_claim(claim["id"], compliance_officer_headers), 200
        )
        assert submitted["status"] == "SUBMITTED", (
            "gate clears once the inspection is COMPLETED and APPROVED"
        )

    def test_claim_submit_before_finalize_rejected(
        self, api, compliance_officer_headers
    ):
        """PRD §3.9: "Submission by a `ComplianceOfficer` requires the claim to
        be FINALIZED, else `ERR_CLAIM_NOT_SUBMITTABLE` (HTTP 409); the station
        must be ACTIVE, else `ERR_STATION_NOT_ACTIVE`; and no inspection at the
        station may be OVERDUE, else `ERR_OVERDUE_INSPECTION`."

        Design: Corner/validations/claim_submit_before_finalize_rejected
        """
        station = create_station(station_name="Skip", station_code="ST-SKIP")
        claim = create_claim(
            station["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        )
        resp = api.submit_tax_credit_claim(claim["id"], compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTABLE, 409)


class TestClaimPeriodOverlap:
    def test_claim_period_overlap_with_submitted_rejected(
        self, api, station_manager_headers, compliance_officer_headers
    ):
        """PRD §3.9: "The new period must not overlap the period of any
        SUBMITTED or APPROVED claim at the same station, else
        `ERR_CLAIM_PERIOD_OVERLAP` (HTTP 409). The claim starts DRAFT and its
        provisional figures are computed immediately."

        Design: Corner/validations/claim_period_overlap_with_submitted_rejected
        """
        env = setup_settled_session_scenario(
            station_name="OvC", station_code="ST-OVC", metered_mass_kg=26.0
        )
        claim_a = create_claim(env["station"]["id"])
        validate_success(
            api.finalize_tax_credit_claim(claim_a["id"], station_manager_headers), 200
        )
        validate_success(
            api.submit_tax_credit_claim(claim_a["id"], compliance_officer_headers), 200
        )
        resp = api.create_tax_credit_claim(
            {
                "station_id": env["station"]["id"],
                "period_start": "2026-07-15T00:00:00Z",
                "period_end": "2026-08-15T00:00:00Z",
            },
            station_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_PERIOD_OVERLAP, 409)
        after = validate_success(
            api.get_tax_credit_claim(claim_a["id"], station_manager_headers), 200
        )
        assert after["status"] == "SUBMITTED"


class TestClaimFinalizeGuards:
    def test_claim_finalize_twice_rejected(
        self, api, station_manager_headers
    ):
        """PRD §3.9: "Finalization — which requires the claim to be DRAFT, else
        `ERR_CLAIM_NOT_FINALIZABLE` (HTTP 409) — computes the final variant:
        only SETTLED sessions in the period, using their calibration-corrected
        `settled_gge`, and excluding any session already captured by another
        claim at the same station in FINALIZED, SUBMITTED, or APPROVED status,
        which prevents double-claiming."

        Design: Corner/validations/claim_finalize_twice_rejected
        """
        env = setup_settled_session_scenario(
            station_name="CF2", station_code="ST-CF2", metered_mass_kg=25.0,
            calibrate_error_pct=None,
        )
        claim = create_claim(env["station"]["id"])
        validate_success(
            api.finalize_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        resp = api.finalize_tax_credit_claim(claim["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FINALIZABLE, 409)

    def test_claim_finalize_empty_period_rejected(self, api, station_manager_headers):
        """PRD §3.9: "If that final eligible set is empty, finalization fails
        with `ERR_NO_ELIGIBLE_VOLUME` (HTTP 422)."

        Design: Corner/validations/claim_finalize_empty_period_rejected
        """
        station = create_station(station_name="NoVol", station_code="ST-NOVOL")
        claim = create_claim(station["id"])
        resp = api.finalize_tax_credit_claim(claim["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOLUME, 422)
        after = validate_success(
            api.get_tax_credit_claim(claim["id"], station_manager_headers), 200
        )
        assert after["status"] == "DRAFT"


class TestClaimProvisionalInputSet:
    def test_claim_provisional_excludes_voided_sessions(
        self, api, station_manager_headers
    ):
        """PRD §3.9: "The provisional variant, computed at creation and again
        at reopen, draws on the station's COMPLETED and SETTLED non-voided
        sessions whose `completed_at` falls inside the claim period, summing
        their `provisional_gge` into `eligible_gge_provisional` and pricing
        them into `claim_amount_provisional_cents`."

        Design: Corner/calculations/claim_provisional_excludes_voided_sessions
        """
        env = setup_fueling_ready(
            station_name="Xcl", station_code="ST-XCL", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-XC1", 20.0
        )
        complete_session_ok(session["id"], env["card"]["id"], 25.0)
        void_session_ok(session["id"], station_manager_headers, "MANAGER_VOID")
        claim = create_claim(
            env["station"]["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        )
        assert claim["eligible_gge_provisional"] == pytest.approx(0.000, abs=1e-9), (
            "VOIDED session excluded from the provisional input set"
        )
        assert claim["claim_amount_provisional_cents"] == 0
