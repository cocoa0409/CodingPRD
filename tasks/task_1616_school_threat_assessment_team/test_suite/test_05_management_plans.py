"""Management plan drafting, OCC-guarded activation, supersede, and cadence."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_plan_for_case,
    assert_management_plan,
    create_draft_plan,
    create_plan_payload,
    get_case,
    list_case_checkins,
    list_case_plans,
    make_team_lead_headers,
    make_threat_assessor_headers,
    send_referral,
    setup_case_plan_active,
    setup_case_with_finalized_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]

HIGH_50_FACTORS = [
    {"factor_code": "PLAN_SPECIFICITY", "severity": 2},
    {"factor_code": "GRIEVANCE_HISTORY", "severity": 2},
]


class TestPlanCadenceRules:
    def test_plan_cadence_defaults_to_level_default_when_omitted(self, api):
        """PRD: "When `cadence_days` is omitted it defaults by the case's
        current risk level: 3 days for `IMMINENT`, 7 for `HIGH`, 14 for
        `MODERATE`, and 30 for `LOW`."
        PRD: "Finally, the first monitoring check-in is auto-created with
        `auto_created` true, due the current calendar date plus the plan's
        cadence in days, unless a check-in in `SCHEDULED` or `MISSED` status
        already exists for that case on that calendar day."

        Design: Corner/calculations/plan_cadence_defaults_to_level_default_when_omitted
        """
        case, _assessment = setup_case_with_finalized_assessment()
        plan = validate_success(
            api.create_plan(
                create_plan_payload(case["id"], cadence_mode="FROM_COMPLETION"),
                TA1),
            201,
        )
        assert_management_plan(plan)
        assert plan["cadence_days"] == 14, (
            "a MODERATE case's plan defaults to a 14-day cadence"
        )

        activate_plan_for_case(plan["id"], case["id"])
        checkins, meta = list_case_checkins(case["id"])
        assert meta["total_count"] == 1
        assert checkins[0]["auto_created"] is True
        assert checkins[0]["due_date"] == "2026-08-15", (
            "activation on 2026-08-01 plus 14 days"
        )

    def test_plan_cadence_beyond_level_max_returns_422(self, api):
        """PRD: "A supplied `cadence_days` may not exceed the maximum for that
        level — 7 days for `IMMINENT`, 14 for `HIGH`, 30 for `MODERATE`, and
        60 for `LOW` — and an over-long cadence is rejected with
        `ERR_CADENCE_TOO_LONG` (HTTP 422)."

        Design: Corner/validations/plan_cadence_beyond_level_max_returns_422
        """
        case, _assessment = setup_case_with_finalized_assessment()
        resp = api.create_plan(
            create_plan_payload(case["id"], cadence_mode="FROM_COMPLETION",
                                cadence_days=31, conditions=["x"]),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_CADENCE_TOO_LONG)


class TestOptimisticConcurrencyOnActivation:
    def test_stale_case_version_rejected(self, api):
        """PRD: "Activation is a `TeamLead` decision and is the OCC-guarded
        operation of §2.6: the request must carry
        `expected_threat_case_version`, and a value that does not match the
        case's current `version` is rejected with `ERR_STALE_CASE_VERSION`
        before any state or business rule is consulted."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_and_version_increments
        """
        case, _assessment = setup_case_with_finalized_assessment()
        plan = create_draft_plan(case["id"])
        observed = get_case(case["id"])["version"]

        stale = api.activate_plan(plan["id"], observed - 1, TL1)
        validate_error(stale, ApiErrorId.ERR_STALE_CASE_VERSION)

        drafts, meta = list_case_plans(case["id"], status="DRAFT")
        assert meta["total_count"] == 1, (
            "a stale activation must leave the plan in DRAFT"
        )
        assert drafts[0]["id"] == plan["id"]

    def test_fresh_version_activates_and_increments_case_version(self, api):
        """PRD: "A successful activation stamps `activated_at`, increments the
        case's `version` by one, and writes `PLAN_ACTIVATED`."
        PRD: "The case itself moves to `PLAN_ACTIVE`, its
        `monitoring_cadence_days` is copied from the activated plan's
        `cadence_days` (the field is null until the first activation), and its
        `escalation_flag` is cleared to false — plan activation is, along with
        reopening, the only way that flag comes down."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_and_version_increments
        """
        case, _assessment = setup_case_with_finalized_assessment()
        plan = create_draft_plan(case["id"], cadence_days=10)
        observed = get_case(case["id"])["version"]

        activated = validate_success(
            api.activate_plan(plan["id"], observed, TL1), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["activated_at"] is not None

        case_after = get_case(case["id"])
        assert case_after["version"] == observed + 1, (
            "activation increments the case's version by exactly one"
        )
        assert case_after["status"] == "PLAN_ACTIVE"
        assert case_after["monitoring_cadence_days"] == 10


class TestPlanSupersede:
    def test_second_plan_activation_supersedes_first(self, api):
        """PRD: "A successful activation stamps `activated_at`, increments the
        case's `version` by one, and writes `PLAN_ACTIVATED`. The case's prior
        `ACTIVE` plan, if any, becomes `SUPERSEDED` with a `PLAN_SUPERSEDED`
        audit event; a plan that was flagged `needs_review` sheds that flag
        when a newer plan activates."
        PRD: "The case itself moves to `PLAN_ACTIVE`, its
        `monitoring_cadence_days` is copied from the activated plan's
        `cadence_days` (the field is null until the first activation), and its
        `escalation_flag` is cleared to false — plan activation is, along with
        reopening, the only way that flag comes down."

        Design: Corner/state_machines/second_plan_activation_supersedes_first
        """
        case, _assessment, plan_a, _chk = setup_case_plan_active()
        plan_b = create_draft_plan(case["id"], cadence_mode="FIXED_ANCHOR",
                                   cadence_days=7, conditions=["plan B"])

        activated_b = activate_plan_for_case(plan_b["id"], case["id"])
        assert activated_b["status"] == "ACTIVE"

        superseded, sup_meta = list_case_plans(case["id"], status="SUPERSEDED")
        assert sup_meta["total_count"] == 1
        assert superseded[0]["id"] == plan_a["id"]

        active, act_meta = list_case_plans(case["id"], status="ACTIVE")
        assert act_meta["total_count"] == 1, "exactly one ACTIVE plan per case"
        assert active[0]["id"] == plan_b["id"]

        case_after = get_case(case["id"])
        assert case_after["monitoring_cadence_days"] == 7, (
            "the case cadence is refreshed from the newly activated plan"
        )


class TestLeReferralGateOnActivation:
    def test_high_case_activation_blocked_without_acknowledged_le_referral(self, api):
        """PRD: "After the stale-version check, the gates evaluate in order:
        the plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); the case must be
        `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE`); when
        the case's `risk_level` is `HIGH` or `IMMINENT`, a law-enforcement
        referral in `ACKNOWLEDGED` status must exist for the case
        (`ERR_LE_REFERRAL_REQUIRED`); and a `FINALIZED` assessment must exist
        for the case (`ERR_NO_FINALIZED_ASSESSMENT`)."

        Design: Difficulty/cross_entity_state_dependency/plan_activation_gated_by_le_referral_ack
        """
        case, assessment = setup_case_with_finalized_assessment(
            factors=HIGH_50_FACTORS)
        assert assessment["risk_level"] == "HIGH"
        plan = create_draft_plan(case["id"], cadence_days=10,
                                 conditions=["daily check-in"])
        observed = get_case(case["id"])["version"]

        resp = api.activate_plan(plan["id"], observed, TL1)
        validate_error(resp, ApiErrorId.ERR_LE_REFERRAL_REQUIRED)

        plans, meta = list_case_plans(case["id"], status="DRAFT")
        assert meta["total_count"] == 1, "rejected activation leaves the plan DRAFT"

    def test_high_case_activation_succeeds_after_le_acknowledgement(self, api):
        """PRD: "After the stale-version check, the gates evaluate in order:
        the plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); the case must be
        `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE`); when
        the case's `risk_level` is `HIGH` or `IMMINENT`, a law-enforcement
        referral in `ACKNOWLEDGED` status must exist for the case
        (`ERR_LE_REFERRAL_REQUIRED`); and a `FINALIZED` assessment must exist
        for the case (`ERR_NO_FINALIZED_ASSESSMENT`)."
        PRD: "Acknowledgement moves the referral to `ACKNOWLEDGED` and writes
        `REFERRAL_ACKNOWLEDGED`."

        Design: Difficulty/cross_entity_state_dependency/plan_activation_gated_by_le_referral_ack
        """
        case, _assessment = setup_case_with_finalized_assessment(
            factors=HIGH_50_FACTORS)
        plan = create_draft_plan(case["id"], cadence_days=10,
                                 conditions=["daily check-in"])

        referral = send_referral(case["id"], referral_type="LAW_ENFORCEMENT",
                                 agency_name="City PD", urgency="URGENT",
                                 sender=TL1)
        acked = validate_success(
            api.acknowledge_referral(referral["id"], TA1), 200)
        assert acked["status"] == "ACKNOWLEDGED"

        activated = activate_plan_for_case(plan["id"], case["id"])
        assert activated["status"] == "ACTIVE"

        case_after = get_case(case["id"])
        assert case_after["status"] == "PLAN_ACTIVE"
        assert case_after["monitoring_cadence_days"] == 10
