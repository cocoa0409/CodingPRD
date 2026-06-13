"""Bind gate priority ordering, boundary precision, and cross-entity gates.
Queue A — rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_underwriter_headers,
    make_inspector_headers,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestBindValidationPriority:
    def test_state_check_precedes_authority_check(self, api):
        """PRD §2.6: "the target resource's state is checked for fitness for the
        operation ... yielding the operation-specific state conflict code. Only after
        these gates pass does the system evaluate business-referential, safety,
        temporal, fiscal, and constraint rules ... in that relative order."
        PRD §3.6: "The application must be `UNDER_REVIEW`, otherwise
        `ERR_APPLICATION_NOT_UNDER_REVIEW`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_bind
        """
        # SUBMITTED (not UNDER_REVIEW) application; underwriter authority below coverage.
        uw = fx.create_underwriter(authority_limit=100000)
        prop, ra = fx.setup_estimated_property()
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW.value)

    def test_authority_limit_fires_once_state_passes(self, api):
        """PRD §3.6: "The requested Coverage A must be at most the acting underwriter's
        `authority_limit`, otherwise `ERR_AUTHORITY_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_bind
        """
        # Same fiscal violation (coverage 300000 > authority 100000) but the
        # application is now genuinely UNDER_REVIEW with a passing inspection panel,
        # so the higher-priority state gate no longer pre-empts: the fiscal error
        # ERR_AUTHORITY_LIMIT_EXCEEDED surfaces.
        uw = fx.create_underwriter(authority_limit=100000)
        prop, ra = fx.setup_estimated_property()
        fx.setup_passed_inspection(prop["id"])
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AUTHORITY_LIMIT_EXCEEDED.value)

    def test_referential_inspection_check_precedes_safety_wildfire_check(self, api):
        """PRD §3.6: "There must be a `PASSED` inspection for the application's
        property, otherwise `ERR_INSPECTION_NOT_PASSED`. The property's risk assessment
        must have reached `FINAL` stage, otherwise `ERR_SCORE_NOT_FINAL`. The final
        wildfire score must be strictly less than 80 to be insurable; a score of 80 or
        higher declines the risk with `ERR_WILDFIRE_UNINSURABLE`, the boundary sitting
        exactly at 80."

        Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_bind
        """
        # High-wildfire RA, NO passed inspection: referential ERR_INSPECTION_NOT_PASSED
        # is checked before safety (and before score-not-final).
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property(
            ra_overrides={
                "wildfire_fuel_density": 100, "slope_grade_pct": 100,
                "defensible_space_ft": 80, "flood_zone": "X", "distance_to_coast_mi": 60,
            }
        )
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED.value)

    def test_safety_wildfire_check_fires_once_inspection_passed(self, api):
        """PRD §3.6: "The final wildfire score must be strictly less than 80 to be
        insurable; a score of 80 or higher declines the risk with
        `ERR_WILDFIRE_UNINSURABLE`, the boundary sitting exactly at 80."

        Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_bind
        """
        # Same high-wildfire property, but now WITH a PASSED inspection: the
        # referential gate (ERR_INSPECTION_NOT_PASSED) no longer pre-empts, so the
        # lower-priority safety gate ERR_WILDFIRE_UNINSURABLE surfaces.
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property(
            ra_overrides={
                "wildfire_fuel_density": 100, "slope_grade_pct": 100,
                "defensible_space_ft": 80, "flood_zone": "X", "distance_to_coast_mi": 60,
            }
        )
        fx.setup_passed_inspection(prop["id"])
        ra_after = fx.get_risk_assessment(ra["id"])
        assert ra_after["score_stage"] == "FINAL" and ra_after["wildfire_score"] == 84
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WILDFIRE_UNINSURABLE.value)


class TestBoundaryPrecision:
    def test_wildfire_final_score_at_or_above_80_declines_bind(self, api):
        """PRD §3.6: "The final wildfire score must be strictly less than 80 to be
        insurable; a score of 80 or higher declines the risk with
        `ERR_WILDFIRE_UNINSURABLE`, the boundary sitting exactly at 80."

        Design: Difficulty/boundary_precision_check/wildfire_score_80_boundary_declines_bind
        """
        uw = fx.create_underwriter()
        # fuel=100, slope=100, space=80 -> raw 96 -> FINAL 84 (>= 80)
        prop, ra = fx.setup_estimated_property(
            ra_overrides={
                "wildfire_fuel_density": 100, "slope_grade_pct": 100,
                "defensible_space_ft": 80, "flood_zone": "X", "distance_to_coast_mi": 60,
            }
        )
        fx.setup_passed_inspection(prop["id"])
        ra_after = fx.get_risk_assessment(ra["id"])
        assert ra_after["score_stage"] == "FINAL"
        assert ra_after["wildfire_score"] == 84
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WILDFIRE_UNINSURABLE.value)

    def test_wildfire_final_score_below_80_binds(self, api):
        """PRD §3.6: "The final wildfire score must be strictly less than 80 to be
        insurable; a score of 80 or higher declines the risk with
        `ERR_WILDFIRE_UNINSURABLE`, the boundary sitting exactly at 80."

        Design: Difficulty/boundary_precision_check/wildfire_score_80_boundary_declines_bind
        """
        uw = fx.create_underwriter()
        # fuel=100, slope=90, space=80 -> raw 0.7*100+0.5*90-0.3*80 = 91 -> FINAL 79 (< 80)
        prop, ra = fx.setup_estimated_property(
            ra_overrides={
                "wildfire_fuel_density": 100, "slope_grade_pct": 90,
                "defensible_space_ft": 80, "flood_zone": "X", "distance_to_coast_mi": 60,
            }
        )
        fx.setup_passed_inspection(prop["id"])
        ra_after = fx.get_risk_assessment(ra["id"])
        assert ra_after["score_stage"] == "FINAL"
        assert ra_after["wildfire_score"] == 79, f"raw 91 - 12 = 79, got {ra_after['wildfire_score']}"
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        bound = validate_success(
            api.bind_application(
                app["id"],
                f.bind_application_payload(1751000000, 1782536000, app["version"]),
                make_underwriter_headers(uw["id"]),
            )
        )
        assert bound["status"] == "BOUND", "score 79 < 80 is insurable and binds"

    def test_inspection_four_points_passes_boundary(self, api):
        """PRD §3.3: "when all four points are true — that is, when the passed count
        equals 4 — the inspection moves to `PASSED`; when fewer than four points are
        true the inspection moves to `FAILED`. The boundary is exact: three passing
        points fail, four pass."

        Design: Difficulty/boundary_precision_check/inspection_passed_count_4_vs_3_boundary
        """
        inspector = fx.create_inspector()
        prop = fx.create_property(street_address="12 Slope St")
        insp = fx.schedule_inspection(prop["id"], inspector["id"], 1750500000, 1750503600)
        completed = validate_success(
            api.complete_inspection(
                insp["id"], f.complete_inspection_payload(True, True, True, True),
                make_inspector_headers(inspector["id"]),
            )
        )
        assert completed["passed_count"] == 4
        assert completed["status"] == "PASSED"

    def test_inspection_three_points_fails_boundary(self, api):
        """PRD §3.3: "when all four points are true — that is, when the passed count
        equals 4 — the inspection moves to `PASSED`; when fewer than four points are
        true the inspection moves to `FAILED`. The boundary is exact: three passing
        points fail, four pass."

        Design: Difficulty/boundary_precision_check/inspection_passed_count_4_vs_3_boundary
        """
        inspector = fx.create_inspector()
        prop = fx.create_property(street_address="12 Slope St")
        insp = fx.schedule_inspection(prop["id"], inspector["id"], 1750500000, 1750503600)
        completed = validate_success(
            api.complete_inspection(
                insp["id"], f.complete_inspection_payload(True, True, True, False),
                make_inspector_headers(inspector["id"]),
            )
        )
        assert completed["passed_count"] == 3
        assert completed["status"] == "FAILED"


class TestCrossEntityGates:
    def test_bind_blocked_when_only_inspection_is_failed(self, api):
        """PRD §3.6: "There must be a `PASSED` inspection for the application's
        property, otherwise `ERR_INSPECTION_NOT_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/bind_requires_passed_inspection_application_inspection
        """
        uw = fx.create_underwriter()
        inspector = fx.create_inspector()
        prop, ra = fx.setup_estimated_property()
        insp = fx.schedule_inspection(prop["id"], inspector["id"], 1750600000, 1750603600)
        # 2/4 -> FAILED (not PASSED)
        failed = fx.complete_inspection(insp["id"], inspector["id"],
                                        roof_ok=True, electrical_ok=True,
                                        plumbing_ok=False, hvac_ok=False)
        assert failed["status"] == "FAILED"
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        resp = api.bind_application(
            app["id"],
            f.bind_application_payload(1751000000, 1782536000, app["version"]),
            make_underwriter_headers(uw["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED.value)

    def test_endorsement_remove_blocked_when_policy_cancelled(self, api):
        """PRD §3.7: "Removal is allowed only when the endorsement is `APPLIED`,
        otherwise `ERR_ENDORSEMENT_NOT_APPLIED`, and only while the application's
        policy is in `PENDING_PAYMENT`, `ACTIVE`, or `REINSTATED`, otherwise
        `ERR_POLICY_NOT_AMENDABLE`."

        Design: Difficulty/cross_entity_state_dependency/endorsement_remove_requires_amendable_policy_endorsement_policy
        """
        ctx = fx.setup_bound_policy(
            requested_coverage_a=300000, wind_hail_deductible_pct=2,
            endorsements=[("PERIL_ADD", "WATER_BACKUP", 20000)],
        )
        e1 = ctx["endorsements"][0]
        policy, uw = ctx["policy"], ctx["underwriter"]
        # Cancel the policy (from PENDING_PAYMENT path: cancel is allowed from
        # ACTIVE/REINSTATED/LAPSED only — here we pay to ACTIVE first then cancel).
        fx.pay_binding(policy["id"], policy["annual_premium"])
        fx.cancel_policy(policy["id"], uw["id"])
        resp = api.remove_endorsement(e1["id"], make_underwriter_headers(uw["id"]))
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_AMENDABLE.value)
        assert fx.get_endorsement(e1["id"])["status"] == "APPLIED", "no reversal posted"

    def test_bind_succeeds_when_inspection_passed(self, api):
        """PRD §3.6: "There must be a `PASSED` inspection for the application's
        property, otherwise `ERR_INSPECTION_NOT_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/bind_requires_passed_inspection_application_inspection
        """
        # The cross-entity gate is satisfied: a PASSED inspection exists for the
        # property, so the bind proceeds (the application reaches BOUND).
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property()
        inspector_id, insp = fx.setup_passed_inspection(prop["id"])
        assert insp["status"] == "PASSED"
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        bound = validate_success(
            api.bind_application(
                app["id"],
                f.bind_application_payload(1751000000, 1782536000, app["version"]),
                make_underwriter_headers(uw["id"]),
            )
        )
        assert bound["status"] == "BOUND"

    def test_endorsement_remove_succeeds_when_policy_amendable(self, api):
        """PRD §3.7: "Removal is allowed only when the endorsement is `APPLIED`,
        otherwise `ERR_ENDORSEMENT_NOT_APPLIED`, and only while the application's
        policy is in `PENDING_PAYMENT`, `ACTIVE`, or `REINSTATED`, otherwise
        `ERR_POLICY_NOT_AMENDABLE`."

        Design: Difficulty/cross_entity_state_dependency/endorsement_remove_requires_amendable_policy_endorsement_policy
        """
        # Policy left in PENDING_PAYMENT (an amendable state): removal is permitted
        # and the endorsement reaches REMOVED.
        ctx = fx.setup_bound_policy(
            requested_coverage_a=300000, wind_hail_deductible_pct=2,
            endorsements=[("PERIL_ADD", "WATER_BACKUP", 20000)],
        )
        e1 = ctx["endorsements"][0]
        policy, uw = ctx["policy"], ctx["underwriter"]
        assert policy["status"] == "PENDING_PAYMENT"
        removed = validate_success(
            api.remove_endorsement(e1["id"], make_underwriter_headers(uw["id"]))
        )
        assert removed["status"] == "REMOVED"
