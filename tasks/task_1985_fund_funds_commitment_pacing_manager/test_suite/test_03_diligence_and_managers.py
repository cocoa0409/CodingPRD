"""Manager/vehicle diligence ladder: DD review cycle, composite score,
vehicle approval threshold, manager cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_manager,
    create_recommended_proposal,
    create_vehicle,
    get_latest_review,
    make_cio_headers,
    make_compliance_headers,
    make_staff_trio,
    run_vehicle_to_approved,
    score_and_submit_review,
    setup_open_program_with_plan,
    validate_error,
    validate_success,
)


class TestDdCompositeScore:
    def test_dd_composite_weighted_constants_applied(self):
        """PRD §3.3: "Submission computes `composite_score` as a weighted
        blend: thirty percent of `score_strategy_fit`, twenty-five percent of
        `score_track_record`, twenty-five percent of `score_operations`, and
        twenty percent of `score_compliance`, with the result rounded to 2
        decimal places round half up."

        Design: Corner/calculations/dd_composite_weighted_constants_applied
        """
        ana_h, _, _, _ = make_staff_trio("d3")
        manager = create_manager(ana_h, legal_name="AlphaBetaCap")
        vehicle = create_vehicle(manager["id"], ana_h, strategy="GROWTH", fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)
        resp = api_client.update_dd_review(
            vehicle["id"], review["id"],
            {
                "score_strategy_fit": 90,
                "score_track_record": 80,
                "score_operations": 70,
                "score_compliance": 60,
            },
            ana_h,
        )
        validate_success(resp)
        submitted = validate_success(api_client.submit_dd_review(vehicle["id"], review["id"], ana_h))
        # 0.30*90 + 0.25*80 + 0.25*70 + 0.20*60 = 27 + 20 + 17.5 + 12 = 76.50
        assert submitted["composite_score"] == pytest.approx(76.50, abs=0.005)

    def test_dd_composite_exactly_70_passes_vehicle_approval(self):
        """PRD §3.3: "Vehicle approval (from `IN_DILIGENCE` to `APPROVED`) is
        gated on the latest review — the one with the highest `round_index` —
        being in `COMPLETED` status with a `composite_score` of at least 70;
        failure is `ERR_DD_SCORE_TOO_LOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/dd_composite_exactly_70_passes_vehicle_approval
        """
        ana_h, ic_h, _, _ = make_staff_trio("twelve")
        manager = create_manager(ana_h, legal_name="LambdaCap")

        # Vehicle 1: scores 69/69/69/71 -> 0.30*69+0.25*69+0.25*69+0.20*71 = 69.40
        veh1 = create_vehicle(manager["id"], ana_h, fund_name="Lambda Low", strategy="CREDIT",
                              fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], veh1["id"], ana_h))
        rev1 = get_latest_review(veh1["id"], ana_h)
        api_client.update_dd_review(
            veh1["id"], rev1["id"],
            {"score_strategy_fit": 69, "score_track_record": 69,
             "score_operations": 69, "score_compliance": 71},
            ana_h,
        )
        validate_success(api_client.submit_dd_review(veh1["id"], rev1["id"], ana_h))
        validate_success(api_client.complete_dd_review(veh1["id"], rev1["id"], ic_h))

        # Vehicle 2: scores 70/70/70/70 -> exactly 70.00
        veh2 = create_vehicle(manager["id"], ana_h, fund_name="Lambda Edge", strategy="CREDIT",
                              fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], veh2["id"], ana_h))
        rev2 = get_latest_review(veh2["id"], ana_h)
        api_client.update_dd_review(
            veh2["id"], rev2["id"],
            {"score_strategy_fit": 70, "score_track_record": 70,
             "score_operations": 70, "score_compliance": 70},
            ana_h,
        )
        submitted2 = validate_success(api_client.submit_dd_review(veh2["id"], rev2["id"], ana_h))
        assert submitted2["composite_score"] == pytest.approx(70.00, abs=0.005)
        validate_success(api_client.complete_dd_review(veh2["id"], rev2["id"], ic_h))

        resp1 = api_client.approve_vehicle(manager["id"], veh1["id"], ic_h)
        validate_error(resp1, ApiErrorId.ERR_DD_SCORE_TOO_LOW)
        veh1_after = validate_success(api_client.get_vehicle_flat(veh1["id"], ana_h))
        assert veh1_after["status"] == "IN_DILIGENCE"

        ok = validate_success(api_client.approve_vehicle(manager["id"], veh2["id"], ic_h))
        assert ok["status"] == "APPROVED"
        manager_after = validate_success(api_client.get_manager(manager["id"], ana_h))
        assert manager_after["status"] == "APPROVED", (
            "first vehicle approval cascades manager PROSPECT -> APPROVED"
        )

    def test_dd_composite_just_below_70_rejected(self):
        """PRD §3.3: "Vehicle approval (from `IN_DILIGENCE` to `APPROVED`) is
        gated on the latest review — the one with the highest `round_index` —
        being in `COMPLETED` status with a `composite_score` of at least 70;
        failure is `ERR_DD_SCORE_TOO_LOW` (HTTP 422)."

        Second test for the same boundary: a composite of 69.80 (scores
        70/70/70/69) is below the inclusive gate and fails.

        Design: Difficulty/boundary_precision_check/dd_composite_exactly_70_passes_vehicle_approval
        """
        ana_h, ic_h, _, _ = make_staff_trio("twelveb")
        manager = create_manager(ana_h, legal_name="LambdaBelowCap")
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Lambda Below", strategy="CREDIT",
                                 fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)
        api_client.update_dd_review(
            vehicle["id"], review["id"],
            {"score_strategy_fit": 70, "score_track_record": 70,
             "score_operations": 70, "score_compliance": 69},
            ana_h,
        )
        submitted = validate_success(api_client.submit_dd_review(vehicle["id"], review["id"], ana_h))
        # 0.30*70 + 0.25*70 + 0.25*70 + 0.20*69 = 21+17.5+17.5+13.8 = 69.80
        assert submitted["composite_score"] == pytest.approx(69.80, abs=0.005)
        validate_success(api_client.complete_dd_review(vehicle["id"], review["id"], ic_h))
        resp = api_client.approve_vehicle(manager["id"], vehicle["id"], ic_h)
        validate_error(resp, ApiErrorId.ERR_DD_SCORE_TOO_LOW)


class TestDdReviewCycle:
    def test_dd_review_submit_info_request_resubmit_cycle(self):
        """PRD §3.3: "The `InvestmentCommittee` may kick a submitted review
        back to `INFO_REQUESTED`; resubmission from `INFO_REQUESTED` back to
        `SUBMITTED` recomputes the composite from the current scores, and this
        cycle may repeat."

        Design: Difficulty/non_linear_state_machine/dd_review_submit_info_request_resubmit_cycle
        """
        ana_h, ic_h, _, _ = make_staff_trio("five")
        manager = create_manager(ana_h, legal_name="EpsilonCap", domicile_country="GB",
                                 relationship_since_year=2019)
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Epsilon III",
                                 strategy="VENTURE", fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)

        first = score_and_submit_review(vehicle["id"], review["id"], ana_h, score=60)
        assert first["status"] == "SUBMITTED"
        assert first["composite_score"] == pytest.approx(60.00, abs=0.005)

        kicked = validate_success(
            api_client.request_info_dd_review(vehicle["id"], review["id"], ic_h)
        )
        assert kicked["status"] == "INFO_REQUESTED"

        # Scores are editable while INFO_REQUESTED (PRD §3.3: "While a review
        # is in `DRAFT` or has been kicked back to `INFO_REQUESTED`, the
        # analyst updates the four score fields").
        validate_success(
            api_client.update_dd_review(
                vehicle["id"], review["id"],
                {"score_strategy_fit": 90, "score_track_record": 90,
                 "score_operations": 90, "score_compliance": 90},
                ana_h,
            )
        )
        resubmitted = validate_success(
            api_client.resubmit_dd_review(vehicle["id"], review["id"], ana_h)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["composite_score"] == pytest.approx(90.00, abs=0.005)
        assert resubmitted["round_index"] == 1

    def test_dd_review_cycle_twice_recomputes_each_time(self):
        """PRD §3.3: "resubmission from `INFO_REQUESTED` back to `SUBMITTED`
        recomputes the composite from the current scores, and this cycle may
        repeat."

        Second test on the same instance: two full cycles on the same review
        round each recompute the composite.

        Design: Difficulty/non_linear_state_machine/dd_review_submit_info_request_resubmit_cycle
        """
        ana_h, ic_h, _, _ = make_staff_trio("fiveb")
        manager = create_manager(ana_h, legal_name="EpsilonTwoCap")
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Epsilon IV", strategy="VENTURE")
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)

        score_and_submit_review(vehicle["id"], review["id"], ana_h, score=50)
        for target in (70, 80):
            validate_success(api_client.request_info_dd_review(vehicle["id"], review["id"], ic_h))
            validate_success(
                api_client.update_dd_review(
                    vehicle["id"], review["id"],
                    {"score_strategy_fit": target, "score_track_record": target,
                     "score_operations": target, "score_compliance": target},
                    ana_h,
                )
            )
            resub = validate_success(api_client.resubmit_dd_review(vehicle["id"], review["id"], ana_h))
            assert resub["composite_score"] == pytest.approx(float(target), abs=0.005)
            assert resub["round_index"] == 1

    def test_dd_review_invalid_from_withdrawn(self):
        """PRD §3.3: "A submitted review is completed by the committee, and a
        draft review may be withdrawn by the analyst. `COMPLETED` and
        `WITHDRAWN` are the terminal states."
        PRD §2.4-adjacent state rule (§5): an impossible transition is
        `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/dd_review_invalid_from_withdrawn
        """
        ana_h, _, _, _ = make_staff_trio("c4")
        manager = create_manager(ana_h, legal_name="TauCap", relationship_since_year=2016)
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Tau I", strategy="GROWTH",
                                 fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)
        withdrawn = validate_success(api_client.withdraw_dd_review(vehicle["id"], review["id"], ana_h))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.submit_dd_review(vehicle["id"], review["id"], ana_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_dd_review(vehicle["id"], review["id"], ana_h))
        assert after["status"] == "WITHDRAWN"


class TestManagerLifecycle:
    def test_manager_legal_name_globally_unique(self):
        """PRD §3.3: "An `Analyst` registers a `Manager` by providing its
        `legal_name` (globally unique), a `domicile_country` ISO-3166 alpha-2
        code, and a `relationship_since_year` (at least 1980)."
        PRD §5: a duplicate violates the rule and surfaces
        `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/manager_legal_name_globally_unique
        """
        ana_h, _, _, _ = make_staff_trio("c1")
        validate_success(
            api_client.create_manager(
                {"legal_name": "DupCap", "domicile_country": "US", "relationship_since_year": 2010},
                ana_h,
            ),
            expected_status=201,
        )
        resp = api_client.create_manager(
            {"legal_name": "DupCap", "domicile_country": "GB", "relationship_since_year": 2012},
            ana_h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_error_no_approved_vehicle_on_manager_approve(self):
        """PRD §3.3: "the `CIO` approves a `PROSPECT` manager once at least
        one of its vehicles has reached `APPROVED` — otherwise
        `ERR_NO_APPROVED_VEHICLE` (HTTP 422)"

        Design: Corner/errors/error_no_approved_vehicle_on_manager_approve
        """
        ana_h, _, _, _ = make_staff_trio("f3")
        manager = create_manager(ana_h, legal_name="NoVehCap", relationship_since_year=2020)
        create_vehicle(manager["id"], ana_h, fund_name="NV I", strategy="VENTURE",
                       fund_size_target=100_000_000)
        resp = api_client.approve_manager(manager["id"], make_cio_headers())
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_VEHICLE)
        after = validate_success(api_client.get_manager(manager["id"], ana_h))
        assert after["status"] == "PROSPECT"

    def test_error_manager_not_eligible_on_begin_diligence(self):
        """PRD §3.3: "Beginning diligence moves a vehicle from `SCREENING` to
        `IN_DILIGENCE`, requires the manager to be in `PROSPECT` or `APPROVED`
        (otherwise `ERR_MANAGER_NOT_ELIGIBLE`), and spawns the first
        `DueDiligenceReview` round — `round_index` set to 1 — in `DRAFT`."

        Design: Corner/errors/error_manager_not_eligible_on_begin_diligence
        """
        ana_h, ic_h, _, _ = make_staff_trio("f4")
        manager = create_manager(ana_h, legal_name="SuspCap", relationship_since_year=2016)
        veh1 = create_vehicle(manager["id"], ana_h, fund_name="Susp I")
        run_vehicle_to_approved(manager["id"], veh1["id"], ana_h, ic_h)
        veh2 = create_vehicle(manager["id"], ana_h, fund_name="Susp II", strategy="GROWTH",
                              fund_size_target=200_000_000)
        validate_success(api_client.suspend_manager(manager["id"], make_compliance_headers()))
        resp = api_client.begin_diligence(manager["id"], veh2["id"], ana_h)
        validate_error(resp, ApiErrorId.ERR_MANAGER_NOT_ELIGIBLE)
        veh2_after = validate_success(api_client.get_vehicle_flat(veh2["id"], ana_h))
        assert veh2_after["status"] == "SCREENING"


class TestManagerSuspendCascade:
    def test_manager_suspend_cascade_depth3(self):
        """PRD §3.3: "A `ComplianceOfficer` may suspend an `APPROVED` manager,
        which cascades broadly: every vehicle of the manager in `IN_DILIGENCE`
        is moved to `DECLINED`, every due-diligence review on any of the
        manager's vehicles in `DRAFT`, `SUBMITTED`, or `INFO_REQUESTED` is
        moved to `WITHDRAWN`, and every proposal on any of the manager's
        vehicles in `DRAFT` or `RECOMMENDED` is moved to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/manager_suspend_cascade_depth3
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("seven")
        ctx = setup_open_program_with_plan(
            cash=20_000_000, staff_prefix="sevenp",
            program_name="P7", strategy_cap_pct=0.95, manager_cap_pct=0.95,
        )
        ana_h, ic_h = ctx.analyst_headers, ctx.ic_headers

        manager = create_manager(ana_h, legal_name="EtaCap", relationship_since_year=2011)
        # V1: APPROVED with a RECOMMENDED proposal.
        veh1 = create_vehicle(manager["id"], ana_h, fund_name="Eta I")
        veh1 = run_vehicle_to_approved(manager["id"], veh1["id"], ana_h, ic_h)
        prop1 = create_recommended_proposal(
            veh1["id"], ctx.program["id"], ctx.plan["id"], ana_h, 5_000_000
        )
        # V2: IN_DILIGENCE with a SUBMITTED review.
        veh2 = create_vehicle(manager["id"], ana_h, fund_name="Eta II", strategy="GROWTH",
                              fund_size_target=300_000_000)
        validate_success(api_client.begin_diligence(manager["id"], veh2["id"], ana_h))
        rev2 = get_latest_review(veh2["id"], ana_h)
        score_and_submit_review(veh2["id"], rev2["id"], ana_h, score=70)
        # V3: IN_DILIGENCE with a DRAFT review.
        veh3 = create_vehicle(manager["id"], ana_h, fund_name="Eta III", strategy="CREDIT",
                              fund_size_target=200_000_000)
        validate_success(api_client.begin_diligence(manager["id"], veh3["id"], ana_h))
        rev3 = get_latest_review(veh3["id"], ana_h)
        # The review on V1 is COMPLETED (terminal) — must survive the cascade.
        rev1 = get_latest_review(veh1["id"], ana_h)
        assert rev1["status"] == "COMPLETED"

        resp = api_client.suspend_manager(manager["id"], make_compliance_headers())
        suspended = validate_success(resp)
        assert suspended["status"] == "SUSPENDED"

        veh1_after = validate_success(api_client.get_vehicle_flat(veh1["id"], ana_h))
        veh2_after = validate_success(api_client.get_vehicle_flat(veh2["id"], ana_h))
        veh3_after = validate_success(api_client.get_vehicle_flat(veh3["id"], ana_h))
        assert veh1_after["status"] == "APPROVED", "only IN_DILIGENCE vehicles decline"
        assert veh2_after["status"] == "DECLINED"
        assert veh3_after["status"] == "DECLINED"

        rev1_after = validate_success(api_client.get_dd_review(veh1["id"], rev1["id"], ana_h))
        rev2_after = validate_success(api_client.get_dd_review(veh2["id"], rev2["id"], ana_h))
        rev3_after = validate_success(api_client.get_dd_review(veh3["id"], rev3["id"], ana_h))
        assert rev1_after["status"] == "COMPLETED", "terminal review untouched"
        assert rev2_after["status"] == "WITHDRAWN"
        assert rev3_after["status"] == "WITHDRAWN"

        prop1_after = validate_success(api_client.get_proposal(prop1["id"], ana_h))
        assert prop1_after["status"] == "WITHDRAWN"

    def test_manager_suspend_cascade_reinstate_restores_approved(self):
        """PRD §3.3: "The same officer may reinstate a suspended manager,
        restoring it to `APPROVED` with no cascade."

        Second test on the suspend instance: reinstate leaves the cascaded
        children untouched (DECLINED vehicles stay DECLINED) and only the
        manager row returns to APPROVED.

        Design: Difficulty/transitive_cascade/manager_suspend_cascade_depth3
        """
        ana_h, ic_h, _, _ = make_staff_trio("sevenb")
        manager = create_manager(ana_h, legal_name="EtaReinCap")
        veh = create_vehicle(manager["id"], ana_h, fund_name="EtaR I")
        run_vehicle_to_approved(manager["id"], veh["id"], ana_h, ic_h)
        veh2 = create_vehicle(manager["id"], ana_h, fund_name="EtaR II", strategy="GROWTH")
        validate_success(api_client.begin_diligence(manager["id"], veh2["id"], ana_h))

        validate_success(api_client.suspend_manager(manager["id"], make_compliance_headers()))
        veh2_mid = validate_success(api_client.get_vehicle_flat(veh2["id"], ana_h))
        assert veh2_mid["status"] == "DECLINED"

        reinstated = validate_success(api_client.reinstate_manager(manager["id"], make_compliance_headers()))
        assert reinstated["status"] == "APPROVED"
        veh2_after = validate_success(api_client.get_vehicle_flat(veh2["id"], ana_h))
        assert veh2_after["status"] == "DECLINED", "reinstate has no cascade"
