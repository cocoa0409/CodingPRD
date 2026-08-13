"""Corner: validations — auth, RBAC denials, ownership, SoD, domain range
errors, temporal rules, existence ordering (§1.9 validations)."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_risk, create_identified_risk,
    create_assessed_risk, create_proposed_plan,
    create_active_control, create_active_mapping, create_proposed_mapping,
    approve_mapping, approve_appetite, create_appetite,
    create_approved_appetite,
    create_emerging_risk, validate_emerging_risk,
    create_active_kri, observe_kri,
    get_risk, advance_clock,
    create_category_payload, create_risk_payload, create_kri_payload,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers, make_internal_auditor_headers,
    USER_RISK_OWNER, USER_RISK_OWNER_2, USER_RISK_MANAGER, USER_RISK_MANAGER_2,
    USER_CONTROL_OWNER, USER_INTERNAL_AUDITOR, USER_DUAL,
    NON_EXISTENT_UUID,
)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or carrying a role
        value outside this set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        res = api_client.list_categories(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRbacDenials:
    def test_riskowner_cannot_create_category(self):
        """PRD §4: `POST /categories` is authorized for `RiskManager` only.
        PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/validations/riskowner_cannot_create_category_forbidden
        """
        res = api_client.create_category(
            {"name": "Nope"}, make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


class TestOwnership:
    def test_assessment_by_non_owner_rejected(self):
        """PRD §3.2: "Submission moves a risk `DRAFT` → `IDENTIFIED` and is
        restricted to the risk's owner — the caller's `X-User-ID` must equal
        the recorded `owner_user_id`, or the request fails with
        `ERR_OWNER_MISMATCH`. Every subsequent risk transition and every
        assessment is likewise owner-only."

        Design: Corner/validations/assessment_by_non_owner_returns_owner_mismatch
        """
        cat = create_category(name="OM")
        risk = create_identified_risk(category_id=cat["id"])
        v = risk["version"]
        res = api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 2, "impact": 2,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER_2),
        )
        validate_error(res, ApiErrorId.ERR_OWNER_MISMATCH.value)


class TestSegregationOfDuties:
    def test_plan_self_approve_rejected(self):
        """PRD §2.10: "A treatment plan may be approved or rejected only by a
        `RiskManager` whose `X-User-ID` differs from the plan's recorded
        `proposer_user_id` — the operator who created the plan can never
        decide its fate... Either violation is rejected with
        `ERR_SOD_VIOLATION` (HTTP 422)."

        Design: Corner/validations/sod_plan_self_approve_rejected
        """
        # Build a scenario where one person (USER_DUAL) creates the plan as
        # RiskOwner and then tries to approve it as RiskManager — same X-User-ID.
        cat = create_category(name="SOD")
        risk = create_risk(cat["id"], owner_user_id=USER_DUAL,
                             treatment_budget_cents=500_000)
        api_client.submit_risk(risk["id"], make_risk_owner_headers(USER_DUAL))
        v = validate_success(
            api_client.get_risk(risk["id"], make_risk_owner_headers(USER_DUAL)),
            200,
        )["version"]
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 3, "impact": 3,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_DUAL),
        )
        v2 = validate_success(
            api_client.get_risk(risk["id"], make_risk_owner_headers(USER_DUAL)),
            200,
        )["version"]
        plan_res = api_client.create_treatment_plan(
            risk["id"],
            {"title": "Self plan", "budget_cents": 100_000,
             "due_date": "2026-12-31T00:00:00Z",
             "owner_user_id": USER_DUAL,
             "expected_risk_version": v2},
            make_risk_owner_headers(USER_DUAL),
        )
        plan = validate_success(plan_res, 201)
        # Same person (X-User-ID == USER_DUAL) approves as RiskManager
        res = api_client.approve_treatment_plan(
            plan["id"], make_risk_manager_headers(USER_DUAL),
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_appetite_creator_cannot_approve(self):
        """PRD §2.10: "An appetite statement may be approved only by a
        `RiskManager` whose `X-User-ID` differs from the statement's
        `created_by`. Either violation is rejected with `ERR_SOD_VIOLATION`
        (HTTP 422)."

        Design: Corner/validations/sod_appetite_creator_cannot_approve
        """
        cat = create_category(name="SODA")
        stmt = create_appetite(cat["id"], creator_user_id=USER_RISK_MANAGER)
        # Same RiskManager user cannot approve their own creation
        res = api_client.approve_appetite_statement(
            stmt["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)
        # A different RiskManager can
        res2 = api_client.approve_appetite_statement(
            stmt["id"], make_risk_manager_headers(USER_RISK_MANAGER_2),
        )
        assert validate_success(res2, 200)["status"] == "APPROVED"


class TestDuplicateMapping:
    def test_second_proposed_mapping_rejected(self):
        """PRD §3.3: "If a `PROPOSED` or `ACTIVE` mapping already exists for
        the same risk-and-control pair, the proposal is rejected with
        `ERR_MAPPING_EXISTS`."

        Design: Corner/validations/duplicate_mapping_rejected
        """
        risk = create_assessed_risk(likelihood=2, impact=2)
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        create_active_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        res = api_client.create_control_mapping(
            risk["id"],
            {"control_id": ctl["id"], "coverage_weight": 0.3},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_MAPPING_EXISTS.value)


class TestControlCapacityExceeded:
    def test_second_approve_rejected_at_capacity(self):
        """PRD §3.3: "the control's `mapped_active_count` must be strictly
        below its `max_mapped_risks`, or the approval fails with
        `ERR_CONTROL_CAPACITY_EXCEEDED`."

        Design: Corner/validations/control_capacity_exceeded_on_approve
        """
        cat = create_category(name="CAP")
        r1 = create_assessed_risk(category_id=cat["id"], likelihood=2, impact=2,
                                    title="R1")
        r2 = create_assessed_risk(category_id=cat["id"], likelihood=2, impact=3,
                                    title="R2")
        ctl = create_active_control(name="C1", effectiveness_pct=0.5,
                                     max_mapped_risks=1)
        create_active_mapping(r1["id"], ctl["id"], coverage_weight=0.5)
        m2 = create_proposed_mapping(r2["id"], ctl["id"], coverage_weight=0.4)
        res = api_client.approve_mapping(
            m2["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_CONTROL_CAPACITY_EXCEEDED.value)
        # Mapping m2 stays PROPOSED
        list_res = api_client.list_risk_control_mappings(
            r2["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        mappings = validate_success(list_res, 200)
        statuses = {m["id"]: m["status"] for m in mappings}
        assert statuses[m2["id"]] == "PROPOSED"


class TestAppetiteRetireRequiresCoverage:
    def test_retire_only_approved_rejected(self):
        """PRD §3.1: "retiring a statement is rejected with
        `ERR_NO_APPETITE_COVERAGE` when it would leave the category with no
        other `APPROVED` statement effective at the current logical clock."

        Design: Corner/validations/appetite_retire_without_coverage_rejected
        """
        cat = create_category(name="NAC")
        stmt = create_approved_appetite(cat["id"], tolerance_score=10,
                                           acceptance_cap_score=20)
        res = api_client.retire_appetite_statement(
            stmt["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_NO_APPETITE_COVERAGE.value)

    def test_create_overlapping_approved_window_rejected(self):
        """PRD §3.1: "Among `APPROVED` statements of the same category these
        half-open windows must never overlap, a rule enforced both when a
        statement is created and again when it is approved... An overlap is
        rejected with `ERR_WINDOW_OVERLAP`."

        Design: Corner/validations/appetite_retire_without_coverage_rejected
        """
        cat = create_category(name="NAC")
        create_approved_appetite(cat["id"], tolerance_score=10,
                                    acceptance_cap_score=20)
        # Second window overlapping the APPROVED one
        res = api_client.create_appetite_statement(
            {
                "category_id": cat["id"],
                "tolerance_score": 12, "acceptance_cap_score": 22,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2028-01-01T00:00:00Z",
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP.value)


class TestEmergingBelowThreshold:
    def test_promote_below_threshold_rejected(self):
        """PRD §3.7: "the `scenario_score` must be at least 10, or the
        promoter must set `force` to true together with a non-empty
        `rationale`; a promotion that satisfies neither branch is rejected
        with `ERR_EMERGING_SCORE_BELOW_THRESHOLD`."

        Design: Corner/validations/emerging_promote_below_threshold_rejected
        """
        cat = create_category(name="EBT")
        er = create_emerging_risk(
            cat["id"], title="Minor trend",
            scenario_severity=2, scenario_probability=3,
        )
        assert er["scenario_score"] == 6
        validate_emerging_risk(er["id"])
        res = api_client.promote_emerging_risk(
            er["id"], {"owner_user_id": USER_RISK_OWNER},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_EMERGING_SCORE_BELOW_THRESHOLD.value)

    def test_force_with_rationale_promotes(self):
        """PRD §3.7: "or the promoter must set `force` to true together with
        a non-empty `rationale`".

        Design: Corner/validations/emerging_promote_below_threshold_rejected
        """
        cat = create_category(name="EBT")
        er = create_emerging_risk(
            cat["id"], title="Minor trend",
            scenario_severity=2, scenario_probability=3,
        )
        validate_emerging_risk(er["id"])
        res = api_client.promote_emerging_risk(
            er["id"],
            {"owner_user_id": USER_RISK_OWNER, "force": True,
             "rationale": "board directive"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        new_risk = validate_success(res, 201)
        assert new_risk["status"] == "DRAFT"


class TestKriObservationGap:
    def _weekly_kri(self):
        cat = create_category(name="GAP")
        kri = create_active_kri(
            cat["id"], name="Weekly KRI", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=7,
        )
        observe_kri(kri["id"], 10, "2026-08-01T00:00:00Z")
        return kri

    def test_six_day_gap_rejected(self):
        """PRD §3.6: "`observed_at` must be strictly after
        `last_observation_at` with a gap of at least
        `min_observation_interval_days` days since that last observation
        (`ERR_OBSERVATION_TOO_SOON`)".

        Design: Corner/validations/kri_observation_gap_boundary
        """
        kri = self._weekly_kri()
        advance_clock("2026-08-10T00:00:00Z")
        res = api_client.create_kri_observation(
            kri["id"],
            {"observed_value": 11, "observed_at": "2026-08-07T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_OBSERVATION_TOO_SOON.value)

    def test_exactly_min_gap_passes(self):
        """PRD §3.6: "`observed_at` must be strictly after
        `last_observation_at` with a gap of at least
        `min_observation_interval_days` days since that last observation".

        Design: Corner/validations/kri_observation_gap_boundary
        """
        kri = self._weekly_kri()
        advance_clock("2026-08-10T00:00:00Z")
        res = api_client.create_kri_observation(
            kri["id"],
            {"observed_value": 11, "observed_at": "2026-08-08T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        obs = validate_success(res, 201)
        assert obs["kri_id"] == kri["id"]


class TestObservationInFuture:
    def test_observed_at_after_clock_rejected(self):
        """PRD §3.6: "the observation must not lie in the future relative to
        the logical clock (`ERR_OBSERVATION_IN_FUTURE`)".

        Design: Corner/validations/observation_in_future_rejected
        """
        cat = create_category(name="FUT")
        kri = create_active_kri(
            cat["id"], name="F", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # Default clock is 2026-08-01T00:00:00Z (PRD §2.4)
        res = api_client.create_kri_observation(
            kri["id"],
            {"observed_value": 10, "observed_at": "2026-08-02T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_OBSERVATION_IN_FUTURE.value)


class TestExistenceBeatsState:
    def test_submit_on_nonexistent_risk_returns_404(self):
        """PRD §2.8: "From highest to lowest priority: ... 4. Existence — path
        identifiers validated left to right... (`ERR_NOT_FOUND`). ... 7. State
        guards — the requested transition exists from the entity's current
        status... (`ERR_INVALID_STATE`...)".
        PRD §2.9: "path identifiers are validated from left to right, and the
        first identifier that does not correspond to an existing resource
        yields `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/validations/existence_priority_beats_state
        """
        res = api_client.submit_risk(
            NON_EXISTENT_UUID, make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestKriThresholdOrderInvalid:
    def test_above_direction_amber_must_be_below_red(self):
        """PRD §3.6: "an `ABOVE` indicator requires the amber threshold to be
        strictly below the red threshold, while a `BELOW` indicator requires
        amber strictly above red; either violation is rejected with
        `ERR_THRESHOLD_ORDER_INVALID`."

        Design: Corner/validations/kri_threshold_order_invalid_for_direction
        """
        cat = create_category(name="THO")
        res = api_client.create_kri(
            {
                "category_id": cat["id"], "name": "BadKRI",
                "direction": "ABOVE",
                "amber_threshold": 80, "red_threshold": 75,
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID.value)
