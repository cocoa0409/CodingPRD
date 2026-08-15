"""Guarantee certificates: snapshots, settlement gates, dispute recompute loop."""
from test_helpers import (
    ApiErrorId,
    assert_guarantee_certificate,
    create_and_activate_contract,
    create_certificate,
    create_demand_profile,
    lock_demand_profile,
    log_run_hours,
    create_maintenance_schedule_payload,
    get_facility,
    make_contract_manager_headers,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    setup_certificate_pipeline,
    setup_savings_pipeline,
    validate_error,
    validate_success,
)

ENGINEER = make_energy_engineer_headers("eng-1")
CONTRACT_MGR = make_contract_manager_headers()

CANONICAL_LEAKS = [
    {"location_description": "header drop", "cfm_loss": 12.5, "repair_quote_cents": 400000},
    {"location_description": "hose reel", "cfm_loss": 8.0, "repair_quote_cents": 250000},
    {"location_description": "coupling", "cfm_loss": 1.5, "repair_quote_cents": 90000},
]


class TestSettleGate:
    def test_settle_rejected_while_case_modeled(self, api):
        """PRD §3.9: "Its gates run in order: the linked savings case must be
        `MEASURED` (`ERR_MEASUREMENT_INCOMPLETE`); the facility's posture must be
        `NORMAL` (`ERR_POSTURE_NOT_NORMAL`); and no dispute may be open."

        Design: Difficulty/cross_entity_state_dependency/certificate_settle_gated_by_measured_case
        """
        pipeline = setup_certificate_pipeline(name="F-XG2", case_stage="MODELED")
        certificate = pipeline["certificate"]

        resp = api.settle_certificate(certificate["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_INCOMPLETE, 409)
        certificate = validate_success(api.get_guarantee_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_status"] == "AWAITING_MEASUREMENT", (
            "a rejected settle must leave the certificate AWAITING_MEASUREMENT"
        )

    def test_settle_succeeds_after_measurement(self, api):
        """PRD §3.9: "Settling pulls `measured_kwh_at_settlement` from the case's
        `measured_annual_savings_kwh`, then computes `shortfall_kwh` as the
        `guaranteed_kwh` minus the measured value minus the `deadband_kwh` — the
        deadband is subtracted before clamping — floored at zero, and `payout_cents`
        as the shortfall multiplied by the facility's
        `utility_rate_cents_per_kwh`, rounded half-up to a whole cent, capped at
        twelve times the contract's `monthly_fee_cents`."
        PRD §3.9: "A zero shortfall settles to `SETTLED_NO_SHORTFALL` with
        `payout_cents` zero; a positive shortfall settles to `SETTLED_PAYOUT_DUE`."

        Design: Difficulty/cross_entity_state_dependency/certificate_settle_gated_by_measured_case
        """
        pipeline = setup_certificate_pipeline(name="F-XG2B", case_stage="MODELED")
        facility = pipeline["facility"]
        certificate = pipeline["certificate"]

        resp = api.settle_certificate(certificate["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_INCOMPLETE, 409)

        case = validate_success(api.open_measurement(pipeline["case"]["id"], ENGINEER))
        post = create_demand_profile(
            facility["id"],
            window_start_date="2026-06-01",
            window_end_date="2026-06-30",
            measured_kwh=200000,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post = lock_demand_profile(facility["id"], post["id"], user_id="eng-1")
        case = validate_success(
            api.close_measurement(
                case["id"],
                {"post_profile_id": post["id"]},
                make_energy_engineer_headers("eng-2"),
            )
        )
        assert case["savings_status"] == "MEASURED"

        certificate = validate_success(api.settle_certificate(certificate["id"], CONTRACT_MGR))
        # guaranteed round(496400 x 0.9) = 446760, deadband 8935, measured 486667
        # shortfall = max(0, 446760 - 486667 - 8935) = 0
        assert certificate["settlement_status"] == "SETTLED_NO_SHORTFALL"
        assert certificate["shortfall_kwh"] == 0


class TestDisputeRecomputeLoop:
    def test_certificate_snapshot_and_first_settle(self, api):
        """PRD §3.9: "`guaranteed_kwh` is the savings case's
        `deemed_annual_savings_kwh` at creation time multiplied by `guaranteed_pct`,
        rounded half-up to a whole kilowatt-hour; it is a snapshot that is never
        recomputed, even when the case's deemed figure later changes. `deadband_kwh`,
        the measurement-uncertainty allowance, is 2 percent of `guaranteed_kwh`,
        rounded half-up to a whole kilowatt-hour."

        Design: Difficulty/non_linear_state_machine/certificate_dispute_recompute_loop
        """
        pipeline = setup_certificate_pipeline(
            name="F-GC", case_stage="MEASURED", leaks=CANONICAL_LEAKS
        )
        certificate = pipeline["certificate"]
        assert_guarantee_certificate(certificate)
        # deemed 522800 -> guaranteed round(522800 x 0.9) = 470520; deadband round(470520 x 0.02) = 9410
        assert certificate["guaranteed_kwh"] == 470520, (
            f"guaranteed must be 470520, got {certificate['guaranteed_kwh']}"
        )
        assert certificate["deadband_kwh"] == 9410

        certificate = validate_success(api.settle_certificate(certificate["id"], CONTRACT_MGR))
        # measured 486667 -> shortfall max(0, 470520 - 486667 - 9410) = 0
        assert certificate["settlement_status"] == "SETTLED_NO_SHORTFALL"
        assert certificate["shortfall_kwh"] == 0
        assert certificate["payout_cents"] == 0

    def test_upheld_dispute_recomputes_settlement(self, api):
        """PRD §3.9: "An `UPHELD` outcome requires `corrected_measured_kwh` in the
        request body — its absence is a schema failure, `ERR_INVALID_REQUEST` — and
        it re-runs settlement with the corrected figure: `measured_kwh_at_settlement`
        becomes the corrected value, `shortfall_kwh` and `payout_cents` are
        recomputed by the same pinned formula, and `settlement_status` is
        re-derived, landing on `SETTLED_NO_SHORTFALL` when the recomputed shortfall
        is zero and `SETTLED_PAYOUT_DUE` otherwise; the re-derivation cannot collide
        with `PAID`, because payment is impossible while a dispute is open."
        PRD §3.9: "Payment moves a certificate from `SETTLED_PAYOUT_DUE` to the
        terminal `PAID`"

        Design: Difficulty/non_linear_state_machine/certificate_dispute_recompute_loop
        """
        pipeline = setup_certificate_pipeline(
            name="F-GC2", case_stage="MEASURED", leaks=CANONICAL_LEAKS
        )
        facility = pipeline["facility"]
        certificate = pipeline["certificate"]

        certificate = validate_success(api.settle_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_status"] == "SETTLED_NO_SHORTFALL"

        certificate = validate_success(
            api.dispute_certificate(
                certificate["id"],
                {"reason": "meter drift during measurement window"},
                make_facility_manager_headers(facility["id"]),
            )
        )
        assert certificate["dispute_status"] == "OPEN"

        certificate = validate_success(
            api.resolve_dispute(
                certificate["id"],
                {"outcome": "UPHELD", "corrected_measured_kwh": 420000},
                CONTRACT_MGR,
            )
        )
        assert certificate["dispute_status"] == "RESOLVED_UPHELD"
        # shortfall = 470520 - 420000 - 9410 = 41110; payout = 41110 x 12 = 493320
        assert certificate["shortfall_kwh"] == 41110, (
            f"recomputed shortfall must be 41110, got {certificate['shortfall_kwh']}"
        )
        assert certificate["payout_cents"] == 493320, (
            f"recomputed payout must be 493320 (under the 10800000 annual-fee cap), "
            f"got {certificate['payout_cents']}"
        )
        assert certificate["settlement_status"] == "SETTLED_PAYOUT_DUE", (
            "the recompute loop re-derives the settlement dimension"
        )

        certificate = validate_success(api.pay_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_status"] == "PAID"


class TestPostureCascadeToCertificateGate:
    def test_run_hours_cascade_flips_delinquency_and_posture(self, api):
        """PRD §3.2: "At creation the schedule is `ACTIVE` with `anchor_run_hours`
        set to the facility's current run-hour watermark — the largest
        `run_hours_total` among its compressors that are not `DECOMMISSIONED`, or
        zero when it has none — and `next_due_run_hours` computed as the anchor plus
        the interval."
        PRD §3.2: "Every logged reading ripples outward: schedule delinquency is
        recomputed, then facility posture, then certificate `settlement_blocked`,
        all within the same request."

        Design: Difficulty/transitive_cascade/run_hours_cascade_to_certificate_gate
        """
        pipeline = setup_certificate_pipeline(name="F-C1", case_stage="MEASURED")
        facility = pipeline["facility"]
        compressor = pipeline["compressors"][0]
        log_run_hours(compressor["id"], 4000)

        schedule = validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        assert schedule["anchor_run_hours"] == 4000, (
            f"anchor must be the current watermark 4000, got {schedule['anchor_run_hours']}"
        )
        assert schedule["is_delinquent"] is False

        log_run_hours(compressor["id"], 6000)
        schedule = validate_success(api.get_maintenance_schedule(schedule["id"], CONTRACT_MGR))
        assert schedule["is_delinquent"] is True, "6000 >= next_due 6000 (inclusive)"
        assert get_facility(facility["id"])["posture"] == "MAINTENANCE_DELINQUENT"

    def test_run_hours_cascade_blocks_certificate_settlement(self, api):
        """PRD §2.6: "Every posture recompute also refreshes `settlement_blocked` on
        each of the facility's guarantee certificates whose `settlement_status` is
        not `PAID`: the flag is set whenever the facility's posture is anything
        other than `NORMAL`, and cleared when posture returns to `NORMAL`."
        PRD §3.9: "the facility's posture must be `NORMAL`
        (`ERR_POSTURE_NOT_NORMAL`)"

        Design: Difficulty/transitive_cascade/run_hours_cascade_to_certificate_gate
        """
        pipeline = setup_certificate_pipeline(name="F-C1B", case_stage="MEASURED")
        facility = pipeline["facility"]
        certificate = pipeline["certificate"]
        compressor = pipeline["compressors"][0]
        log_run_hours(compressor["id"], 4000)
        validate_success(
            api.create_maintenance_schedule(
                create_maintenance_schedule_payload(
                    facility_id=facility["id"], component="DRYER", interval_hours=2000
                ),
                CONTRACT_MGR,
            ),
            201,
        )
        certificate = validate_success(api.get_guarantee_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_blocked"] is False, "posture NORMAL at creation"

        log_run_hours(compressor["id"], 6000)
        certificate = validate_success(api.get_guarantee_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_blocked"] is True, (
            "the delinquency cascade must flip settlement_blocked"
        )

        resp = api.settle_certificate(certificate["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_NORMAL, 409)


class TestCertificateCreationGates:
    def test_certificate_tier_gate_and_uniqueness(self, api):
        """PRD §3.9: "The contract must belong to the same facility, be `ACTIVE`,
        and carry tier `PREMIUM`; the savings case must belong to the same facility
        with `savings_status` `MODELED` or `MEASURED`; and at most one certificate
        may exist per savings case. The gates evaluate in order: contract presence
        (`ERR_NO_ACTIVE_CONTRACT`), cross-facility referential integrity
        (`ERR_FACILITY_MISMATCH`), the one-certificate-per-case uniqueness
        (`ERR_CERTIFICATE_EXISTS`), and the tier entitlement
        (`ERR_CONTRACT_TIER_INELIGIBLE`)."

        Design: Corner/validations/corner_certificate_tier_gate_and_uniqueness
        """
        pipe_a = setup_savings_pipeline(name="FA-CERT", advance_to="MODELED")
        contract_a = create_and_activate_contract(
            pipe_a["facility"]["id"], tier="PREMIUM", monthly_fee_cents=900000
        )
        cert_a = create_certificate(
            pipe_a["facility"]["id"], contract_a["id"], pipe_a["case"]["id"], 0.90
        )

        pipe_b = setup_savings_pipeline(name="FB-CERT", advance_to="MODELED")
        contract_b = create_and_activate_contract(
            pipe_b["facility"]["id"], tier="STANDARD", monthly_fee_cents=400000
        )

        resp = api.create_guarantee_certificate(
            {
                "facility_id": pipe_a["facility"]["id"],
                "contract_id": contract_a["id"],
                "savings_case_id": pipe_a["case"]["id"],
                "guaranteed_pct": 0.80,
            },
            CONTRACT_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXISTS, 409)

        resp = api.create_guarantee_certificate(
            {
                "facility_id": pipe_b["facility"]["id"],
                "contract_id": contract_b["id"],
                "savings_case_id": pipe_b["case"]["id"],
                "guaranteed_pct": 0.90,
            },
            CONTRACT_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_TIER_INELIGIBLE, 409)

        cert_a = validate_success(api.get_guarantee_certificate(cert_a["id"], CONTRACT_MGR))
        assert cert_a["settlement_status"] == "AWAITING_MEASUREMENT", (
            "the first certificate is unaffected by the rejected duplicates"
        )


class TestPayoutCapAndDisputeFreeze:
    def test_guarantee_payout_fee_cap_and_dispute_freeze(self, api):
        """PRD §3.9: "Settling pulls `measured_kwh_at_settlement` from the case's
        `measured_annual_savings_kwh`, then computes `shortfall_kwh` as the
        `guaranteed_kwh` minus the measured value minus the `deadband_kwh` — the
        deadband is subtracted before clamping — floored at zero, and `payout_cents`
        as the shortfall multiplied by the facility's `utility_rate_cents_per_kwh`,
        rounded half-up to a whole cent, capped at twelve times the contract's
        `monthly_fee_cents`."
        PRD §3.9: "Payment moves a certificate from `SETTLED_PAYOUT_DUE` to the
        terminal `PAID`, but a dispute freezes it: while `dispute_status` is `OPEN`,
        paying is rejected with `ERR_DISPUTE_OPEN_PAYOUT_FROZEN`; with
        `dispute_status` `NONE`, `RESOLVED_UPHELD`, or `RESOLVED_OVERRULED`, payment
        proceeds."
        PRD §3.9: "An `OVERRULED` outcome leaves every settlement figure unchanged
        and simply releases the payout for a subsequent pay call."

        Design: Corner/calculations/corner_guarantee_payout_fee_cap_and_dispute_freeze
        """
        pipeline = setup_certificate_pipeline(
            name="F-GCAP",
            case_stage="MEASURED",
            monthly_fee_cents=100000,
            post_kwh=240000,
        )
        facility = pipeline["facility"]
        case = pipeline["case"]
        certificate = pipeline["certificate"]

        assert case["measured_annual_savings_kwh"] == 0, (
            f"post annualization equals the baseline, so measured savings are 0 "
            f"(signed, unclamped), got {case['measured_annual_savings_kwh']}"
        )
        assert certificate["guaranteed_kwh"] == 446760
        assert certificate["deadband_kwh"] == 8935

        certificate = validate_success(api.settle_certificate(certificate["id"], CONTRACT_MGR))
        # shortfall = 446760 - 0 - 8935 = 437825; raw 437825 x 12 = 5253900;
        # capped at 12 x 100000 = 1200000
        assert certificate["shortfall_kwh"] == 437825
        assert certificate["payout_cents"] == 1200000, (
            f"the annual-fee cap must bind at 1200000, got {certificate['payout_cents']}"
        )
        assert certificate["settlement_status"] == "SETTLED_PAYOUT_DUE"

        certificate = validate_success(
            api.dispute_certificate(
                certificate["id"],
                {"reason": "baseline meters miscalibrated"},
                make_facility_manager_headers(facility["id"]),
            )
        )
        assert certificate["dispute_status"] == "OPEN"

        resp = api.pay_certificate(certificate["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_OPEN_PAYOUT_FROZEN, 409)

        certificate = validate_success(
            api.resolve_dispute(certificate["id"], {"outcome": "OVERRULED"}, CONTRACT_MGR)
        )
        assert certificate["dispute_status"] == "RESOLVED_OVERRULED"
        assert certificate["payout_cents"] == 1200000, "OVERRULED leaves settlement figures unchanged"

        certificate = validate_success(api.pay_certificate(certificate["id"], CONTRACT_MGR))
        assert certificate["settlement_status"] == "PAID"
