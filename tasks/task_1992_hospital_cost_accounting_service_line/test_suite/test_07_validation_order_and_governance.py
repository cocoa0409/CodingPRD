"""Validation families, governance gates, and temporal windows (PRD §2.7, §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_budget_period,
    create_case,
    create_cost_center_payload,
    create_draft_cost_model,
    create_overhead_center,
    create_rvu_center,
    create_service_line,
    create_active_cost_model,
    post_case,
    propose_refresh,
    setup_case_with_lines,
    setup_ortho_tdabc,
    validate_error,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestValidationPriority:
    def test_state_beats_business_referential_on_case_post(self, api):
        """PRD §2.10: "Every mutating request is validated against a fixed,
        ordered sequence of rule families, and when several violations coexist
        the earliest family's error is the one returned."
        PRD §2.10: "4. **Target state** — the addressed resource must be in the
        state the transition requires (posting requires a `DRAFT` case, refresh
        approval requires a `PROPOSED` refresh, case locking requires a `POSTED`
        case, and so on), else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_case_post
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00)
        case = setup_case_with_lines(scenario, [100])
        posted = post_case(case["id"], scenario["model_version"])
        assert posted["status"] == "POSTED"

        # Re-posting an already-POSTED case: the target-state family (priority 4)
        # is the earliest family that can fire, so ERR_INVALID_STATE is returned.
        resp = api.post_case(
            case["id"], {"expected_model_version": scenario["model_version"]}, CA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_repost_of_posted_case_rejected_regardless_of_payload(self, api):
        """PRD §3.4: "Posting turns a `DRAFT` case into a priced, ledger-visible
        `POSTED` case."
        PRD §2.10: "the addressed resource must be in the state the transition
        requires (posting requires a `DRAFT` case, refresh approval requires a
        `PROPOSED` refresh, case locking requires a `POSTED` case, and so on),
        else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_case_post
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00)
        case = setup_case_with_lines(scenario, [100])
        post_case(case["id"], scenario["model_version"])

        # Even with a deliberately wrong version value, a POSTED case cannot be
        # re-posted: the state gate fires.
        resp = api.post_case(case["id"], {"expected_model_version": 999999}, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_existence_checked_before_state(self, api):
        """PRD §2.10: "3. **Existence** — path identifiers are validated first,
        strictly left to right, and only then are foreign keys in the request
        body checked, in their declared input order; the first identifier that
        does not resolve to an existing resource yields `ERR_NOT_FOUND`."
        PRD §2.10: "4. **Target state** — the addressed resource must be in the
        state the transition requires (posting requires a `DRAFT` case, refresh
        approval requires a `PROPOSED` refresh, case locking requires a `POSTED`
        case, and so on), else `ERR_INVALID_STATE`."

        Design: Corner/validations/existence_checked_before_state
        """
        scenario = setup_ortho_tdabc()
        resp = api.post_case(
            NON_EXISTENT_UUID,
            {"expected_model_version": scenario["model_version"]},
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRefreshGovernance:
    def test_business_safety_beats_business_constraint_on_refresh(self, api):
        """PRD §3.6: "every entry in the `variance_report` must have an absolute
        `delta_pct` of at most 3.00 percent (else `ERR_REFRESH_VARIANCE_EXCEEDED`)"
        PRD §2.10: "7. **Refresh governance gates** — variance and data-quality
        thresholds for refresh approval (`ERR_REFRESH_VARIANCE_EXCEEDED`,
        `ERR_DATA_QUALITY_TOO_LOW`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_refresh
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        model, model_v = create_active_cost_model(
            name="ORTHO-RVU", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        # 5200/2.0 = 2600 vs current 2500 -> delta +4.00% > 3.00 threshold.
        refresh = propose_refresh(
            model["id"], "2026-09",
            [{"cost_center_id": cc_lab["id"], "allocated_cost": 5200.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        resp = api.approve_cost_model_refresh(
            refresh["id"], {"expected_model_version": model_v}, FC
        )
        validate_error(resp, ApiErrorId.ERR_REFRESH_VARIANCE_EXCEEDED)

        still = validate_success(api.get_cost_model_refresh(refresh["id"], FC))
        assert still["status"] == "PROPOSED"

    def test_refresh_variance_report_records_delta_pct(self, api):
        """PRD §3.6: "Each report entry records the `cost_center_id`, the
        `current_rate`, the `proposed_rate`, and the `delta_pct`: the difference
        between proposed and current rate, divided by the current rate,
        expressed as a percentage and rounded half-up to two decimal places."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_refresh
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        model, _v = create_active_cost_model(
            name="ORTHO-RVU", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        refresh = propose_refresh(
            model["id"], "2026-09",
            [{"cost_center_id": cc_lab["id"], "allocated_cost": 5200.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        fetched = validate_success(api.get_cost_model_refresh(refresh["id"], FC))
        report = fetched["variance_report"]
        assert len(report) == 1
        entry = report[0]
        assert entry["cost_center_id"] == cc_lab["id"]
        assert entry["current_rate"] == pytest.approx(2500.00, abs=0.005)
        assert entry["proposed_rate"] == pytest.approx(2600.00, abs=0.005)
        assert entry["delta_pct"] == pytest.approx(4.00, abs=0.005)

    def test_refresh_low_data_quality_rejected(self, api):
        """PRD §3.6: "and the `data_quality_score` must be at least 80.00 (else
        `ERR_DATA_QUALITY_TOO_LOW`)."

        Design: Corner/validations/refresh_low_data_quality_rejected
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        model, model_v = create_active_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        # Variance +1.00% (within threshold) but data_quality 79.99 < 80.00.
        refresh = propose_refresh(
            model["id"], "2026-09",
            [{"cost_center_id": cc_lab["id"], "allocated_cost": 5050.00, "total_rvu": 2.0}],
            data_quality_score=79.99,
        )
        resp = api.approve_cost_model_refresh(
            refresh["id"], {"expected_model_version": model_v}, FC
        )
        validate_error(resp, ApiErrorId.ERR_DATA_QUALITY_TOO_LOW)

    def test_refresh_variance_exactly_at_threshold_passes(self, api):
        """PRD §3.6: "every entry in the `variance_report` must have an absolute
        `delta_pct` of at most 3.00 percent (else `ERR_REFRESH_VARIANCE_EXCEEDED`)"

        Design: Corner/calculations/refresh_variance_exactly_at_threshold_passes
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        model, model_v = create_active_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        # 5150/2.0 = 2575 vs current 2500 -> delta exactly +3.00 == threshold.
        refresh = propose_refresh(
            model["id"], "2026-09",
            [{"cost_center_id": cc_lab["id"], "allocated_cost": 5150.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        fetched = validate_success(api.get_cost_model_refresh(refresh["id"], FC))
        assert fetched["variance_report"][0]["delta_pct"] == pytest.approx(3.00, abs=0.005)

        approved = validate_success(
            api.approve_cost_model_refresh(
                refresh["id"], {"expected_model_version": model_v}, FC
            )
        )
        assert approved["status"] == "APPROVED"


class TestStructuralValidity:
    def test_overhead_center_must_be_overhead_type(self, api):
        """PRD §3.2: "The center named by `overhead_cost_center_id` must be an
        `ACTIVE` cost center whose `cost_type` is `OVERHEAD`; anything else is
        rejected with `ERR_OVERHEAD_CENTER_INVALID`."

        Design: Corner/validations/overhead_center_must_be_overhead_type
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        from test_helpers import create_minutes_center
        cc_mins = create_minutes_center(name="OR Minutes", code="ORMINS",
                                        allocated_cost=12000.00,
                                        practical_capacity_minutes=8000)
        resp = api.create_cost_model(
            {
                "name": "M",
                "service_line_id": sl["id"],
                "allocation_basis": "TDABC",
                "rate_factor": 1.00,
                "overhead_cost_center_id": cc_mins["id"],
                "effective_period": "2026-01",
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_OVERHEAD_CENTER_INVALID)


class TestFiscalSanity:
    def test_negative_unit_cost_rejected(self, api):
        """PRD §3.3: "An **implant** records an `item_code` from the implant
        catalog, a `vendor`, a `unit_cost` greater than zero, and an integer
        `quantity` of units implanted, also greater than zero."
        PRD §2.10: "10. **Numeric sanity and enum validity** — missing required
        fields, type mismatches, invalid enum values, and non-positive numbers
        where a positive value is required all surface as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/negative_unit_cost_rejected
        """
        scenario = setup_ortho_tdabc()
        case = create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        resp = api.add_implant(
            case["id"],
            {"item_code": "HIP-1", "vendor": "V1", "unit_cost": -5.00, "quantity": 1},
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTemporalWindows:
    def test_budget_period_duplicate_window_rejected(self, api):
        """PRD §3.5: "The pair of `cost_center_id` and `period` is unique across
        budget periods — a second period opened for the same pool and period is
        rejected with `ERR_DUPLICATE_BUDGET_PERIOD`"

        Design: Difficulty/resource_temporal_overlap/budget_period_duplicate_window_rejected
        """
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        create_budget_period(cost_center_id=cc_periop["id"], period="2026-08",
                             static_budget_amount=7000.00)

        dup = api.create_budget_period(
            {"cost_center_id": cc_periop["id"], "period": "2026-08",
             "static_budget_amount": 8000.00},
            FC,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_BUDGET_PERIOD)

    def test_budget_period_disjoint_window_admitted(self, api):
        """PRD §3.5: "The pair of `cost_center_id` and `period` is unique across
        budget periods — a second period opened for the same pool and period is
        rejected with `ERR_DUPLICATE_BUDGET_PERIOD`"

        Design: Difficulty/resource_temporal_overlap/budget_period_duplicate_window_rejected
        """
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        create_budget_period(cost_center_id=cc_periop["id"], period="2026-08",
                             static_budget_amount=7000.00)

        disjoint = validate_success(
            api.create_budget_period(
                {"cost_center_id": cc_periop["id"], "period": "2026-09",
                 "static_budget_amount": 8000.00},
                FC,
            ),
            expected_status=201,
        )
        assert disjoint["period"] == "2026-09"
        assert disjoint["cost_center_id"] == cc_periop["id"]

    def test_case_period_before_model_effective_window_rejected(self, api):
        """PRD §2.7: "A case's `period` must never precede the `effective_period`
        of the cost model that prices it — a violation is rejected with
        `ERR_CASE_PERIOD_BEFORE_MODEL` — and this window is verified both when
        the case is created and again when it is posted."

        Design: Difficulty/resource_temporal_overlap/case_period_before_model_effective_window_rejected
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, model_effective_period="2026-06")
        # Case creation itself enforces the window: period 2026-05 < 2026-06.
        resp = api.create_case(
            {
                "service_line_id": scenario["service_line"]["id"],
                "physician_id": scenario["physician"]["id"],
                "drg_id": scenario["drg"]["id"],
                "cost_model_id": scenario["model"]["id"],
                "period": "2026-05",
                "expected_reimbursement": 30000.00,
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_PERIOD_BEFORE_MODEL)

    def test_case_period_exactly_at_effective_window_admitted(self, api):
        """PRD §2.7: "A case's `period` must never precede the `effective_period`
        of the cost model that prices it — a violation is rejected with
        `ERR_CASE_PERIOD_BEFORE_MODEL` — and this window is verified both when
        the case is created and again when it is posted."

        Design: Difficulty/resource_temporal_overlap/case_period_before_model_effective_window_rejected
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, model_effective_period="2026-06")
        # 2026-06 == effective_period: admitted at creation and at post.
        case = setup_case_with_lines(scenario, [100], case_period="2026-06")
        posted = post_case(case["id"], scenario["model_version"])
        assert posted["status"] == "POSTED"
