"""Cross-entity eligibility gates, validation precedence, voc-rehab, award cycle.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency,
non_linear_state_machine (veteran award cycle). Corner queue: voc-rehab validation
and endpoint instances, award no-compensable-rating.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_veteran_headers,
    create_veteran,
    create_school,
    submit_enrollment,
    certify_enrollment,
    create_granted_claim,
    propose_voc_rehab_plan,
    update_veteran_payload,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]
SCO = TEST_USERS["school_official_headers"]


# ─── priority_pair_validation_conflict / state_before_giib_eligibility_on_certify ─

def test_certify_state_check_beats_gi_bill_eligibility(api):
    """PRD §3.15: "Only then is the target resource's state checked for the
    requested transition, yielding `ERR_INVALID_STATE` when it is wrong."
    PRD §3.15: "The remaining business guards — no-conditions, unrated-condition,
    appeal-exhausted, GI-Bill-eligibility, term-overlap, Yellow-Ribbon-availability,
    voc-rehab-ineligibility, entitlement-exhaustion, and no-compensable-rating —
    are then evaluated within the operations that own them."

    Design: Difficulty/priority_pair_validation_conflict/state_before_giib_eligibility_on_certify
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=180000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    # Certify once (now CERTIFIED).
    certify_enrollment(enr)
    # Drop the veteran's service days to 0 (tier 0) — now both state and GI-Bill fail.
    fresh_vet = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    get_success_data(
        api.update_veteran(
            vet["id"],
            update_veteran_payload(fresh_vet["version"], total_active_duty_days=0),
            ADMIN,
        )
    )
    fresh_enr = validate_success(api.get_enrollment(enr["id"], ADMIN), 200)
    res = api.certify_enrollment(
        enr["id"], {"expected_enrollment_version": fresh_enr["version"]}, SCO
    )
    # State (already CERTIFIED) is checked before GI-Bill-eligibility.
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_already_certified_enrollment_state_error(api):
    """PRD §3.12: "The enrollment must be in `SUBMITTED` status, or the request is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_giib_eligibility_on_certify
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=180000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    certified = certify_enrollment(enr)
    res = api.certify_enrollment(
        enr["id"], {"expected_enrollment_version": certified["version"]}, SCO
    )
    validate_error(res, "ERR_INVALID_STATE", 409)


# ─── priority_pair_validation_conflict / vocrehab_ineligible_before_entitlement_exhausted ─

def test_voc_rehab_ineligible_beats_entitlement_exhausted(api):
    """PRD §3.14: "First, the veteran must meet the minimum rating for vocational
    rehabilitation: the veteran's `combined_rating_pct` must be at least twenty, a
    cross-entity dependency on the veteran, failing otherwise with
    `ERR_VOC_REHAB_INELIGIBLE`. Second, the plan's `planned_months` must not
    exceed the veteran's remaining `voc_rehab_entitlement_months`, failing
    otherwise with `ERR_ENTITLEMENT_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/vocrehab_ineligible_before_entitlement_exhausted
    """
    # rating 10 (ineligible) AND planned_months 60 (> 48 entitlement).
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 10}])
    plan = propose_voc_rehab_plan(
        vet["id"], planned_months=60, track="EMPLOYMENT_THROUGH_LONG_TERM"
    )
    res = api.approve_voc_rehab_plan(plan["id"], ADMIN)
    validate_error(res, "ERR_VOC_REHAB_INELIGIBLE", 409)


def test_voc_rehab_ineligible_rating_below_minimum(api):
    """PRD §3.14: "the veteran's `combined_rating_pct` must be at least twenty, a
    cross-entity dependency on the veteran, failing otherwise with
    `ERR_VOC_REHAB_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/vocrehab_ineligible_before_entitlement_exhausted
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 10}])
    plan = propose_voc_rehab_plan(vet["id"], planned_months=60, track="REEMPLOYMENT")
    res = api.approve_voc_rehab_plan(plan["id"], ADMIN)
    validate_error(res, "ERR_VOC_REHAB_INELIGIBLE", 409)
    still = validate_success(api.get_voc_rehab_plan(plan["id"], ADMIN), 200)
    assert still["status"] == "PROPOSED"


# ─── cross_entity_state_dependency / enrollment_certify_requires_veteran_gi_bill ─

def test_certify_requires_veteran_gi_bill_eligibility(api):
    """PRD §3.12: "The veteran must be GI Bill eligible: the veteran's
    `gi_bill_tier_pct` must be strictly greater than 0, a cross-entity dependency
    on the veteran's record, failing otherwise with
    `ERR_NO_GI_BILL_ELIGIBILITY`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_certify_requires_veteran_gi_bill
    """
    vet = create_veteran(total_active_duty_days=30)  # below 90 -> tier 0
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    res = api.certify_enrollment(
        enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
    )
    validate_error(res, "ERR_NO_GI_BILL_ELIGIBILITY", 409)


def test_certify_rejected_leaves_enrollment_submitted(api):
    """PRD §3.12: "A school certifying official certifies an enrollment, advancing
    it from `SUBMITTED` to `CERTIFIED`".
    PRD §3.12: "the veteran's `gi_bill_tier_pct` must be strictly greater than 0,
    a cross-entity dependency on the veteran's record, failing otherwise with
    `ERR_NO_GI_BILL_ELIGIBILITY`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_certify_requires_veteran_gi_bill
    """
    vet = create_veteran(total_active_duty_days=30)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    api.certify_enrollment(
        enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
    )
    still = validate_success(api.get_enrollment(enr["id"], ADMIN), 200)
    assert still["status"] == "SUBMITTED", (
        f"rejected certify leaves enrollment SUBMITTED, got {still['status']}"
    )


# ─── cross_entity_state_dependency / vocrehab_approve_requires_veteran_rating ─

def test_voc_rehab_approve_requires_veteran_rating(api):
    """PRD §3.14: "the veteran's `combined_rating_pct` must be at least twenty, a
    cross-entity dependency on the veteran, failing otherwise with
    `ERR_VOC_REHAB_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/vocrehab_approve_requires_veteran_rating
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 10}])
    plan = propose_voc_rehab_plan(vet["id"], planned_months=12, track="REEMPLOYMENT")
    res = api.approve_voc_rehab_plan(plan["id"], ADMIN)
    validate_error(res, "ERR_VOC_REHAB_INELIGIBLE", 409)


def test_voc_rehab_ineligible_leaves_plan_proposed(api):
    """PRD §3.14: "A claims officer approves a proposed plan, moving it from
    `PROPOSED` to `APPROVED`. Approval is permitted only from `PROPOSED`".

    Design: Difficulty/cross_entity_state_dependency/vocrehab_approve_requires_veteran_rating
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 10}])
    plan = propose_voc_rehab_plan(vet["id"], planned_months=12, track="REEMPLOYMENT")
    api.approve_voc_rehab_plan(plan["id"], ADMIN)
    still = validate_success(api.get_voc_rehab_plan(plan["id"], ADMIN), 200)
    assert still["status"] == "PROPOSED"


# ─── non_linear_state_machine / veteran_award_suspend_reactivate_cycle ────

def test_award_suspend_from_active(api):
    """PRD §3.9: "An active award may be suspended by a claims officer, moving
    `award_status` from `ACTIVE` to `SUSPENDED`; this is permitted only from
    `ACTIVE`, pauses disbursement while retaining the computed amount, and takes
    no version field."

    Design: Difficulty/non_linear_state_machine/veteran_award_suspend_reactivate_cycle
    """
    vet = _activated_award_veteran(api)
    suspended = validate_success(api.suspend_award(vet["id"], ADMIN), 200)
    assert suspended["award_status"] == "SUSPENDED", (
        f"suspend should yield SUSPENDED, got {suspended['award_status']}"
    )


def test_award_reactivate_from_suspended(api):
    """PRD §3.9: "A suspended award is reactivated through the same activation
    action: from `SUSPENDED` the award returns to `ACTIVE`, again requiring
    `combined_rating_pct` strictly greater than 0 (otherwise
    `ERR_NO_COMPENSABLE_RATING`) and `expected_veteran_version` to match the
    current `version` (otherwise `ERR_STALE_VERSION`), and again incrementing the
    veteran's `version` by one."

    Design: Difficulty/non_linear_state_machine/veteran_award_suspend_reactivate_cycle
    """
    vet = _activated_award_veteran(api)
    get_success_data(api.suspend_award(vet["id"], ADMIN))
    fresh = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    reactivated = validate_success(
        api.activate_award(
            vet["id"], {"expected_veteran_version": fresh["version"]}, ADMIN
        ),
        200,
    )
    assert reactivated["award_status"] == "ACTIVE", (
        f"reactivate from SUSPENDED should yield ACTIVE, got {reactivated['award_status']}"
    )


# ─── Corner / validations and endpoints (voc-rehab + award) ───────────────

def test_voc_rehab_entitlement_exhausted_alone(api):
    """PRD §3.14: "Second, the plan's `planned_months` must not exceed the
    veteran's remaining `voc_rehab_entitlement_months`, failing otherwise with
    `ERR_ENTITLEMENT_EXHAUSTED`."

    Design: Corner/validations/voc_rehab_entitlement_exhausted_alone
    """
    # rating 50 (eligible) but planned 60 > 48 entitlement.
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    plan = propose_voc_rehab_plan(vet["id"], planned_months=60, track="REEMPLOYMENT")
    res = api.approve_voc_rehab_plan(plan["id"], ADMIN)
    validate_error(res, "ERR_ENTITLEMENT_EXHAUSTED", 409)


def test_activate_award_no_compensable_rating(api):
    """PRD §3.9: "Activation is permitted only when the award is in `DRAFT`
    status, requires the veteran's `combined_rating_pct` to be strictly greater
    than 0 (otherwise `ERR_NO_COMPENSABLE_RATING`)".

    Design: Corner/validations/activate_award_no_compensable_rating
    """
    vet = create_veteran(total_active_duty_days=1095)  # combined_rating_pct = 0
    res = api.activate_award(
        vet["id"], {"expected_veteran_version": vet["version"]}, ADMIN
    )
    validate_error(res, "ERR_NO_COMPENSABLE_RATING", 409)
    still = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert still["award_status"] == "DRAFT"


def test_voc_rehab_approve_debits_entitlement(api):
    """PRD §3.14: "On approval, the requested `planned_months` is debited from the
    veteran's `voc_rehab_entitlement_months`."

    Design: Corner/endpoints/voc_rehab_approve_debits_entitlement
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    plan = propose_voc_rehab_plan(vet["id"], planned_months=12, track="REEMPLOYMENT")
    approved = validate_success(api.approve_voc_rehab_plan(plan["id"], ADMIN), 200)
    assert approved["status"] == "APPROVED"
    vet_after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert vet_after["voc_rehab_entitlement_months"] == 36, (
        f"48 - 12 = 36 entitlement months, got {vet_after['voc_rehab_entitlement_months']}"
    )


def test_voc_rehab_reject_from_proposed(api):
    """PRD §3.14: "a proposed plan may be rejected by a claims officer, moving it
    from `PROPOSED` to `REJECTED` (terminal); rejection is permitted only from
    `PROPOSED`."

    Design: Corner/state_machines/voc_rehab_reject_from_proposed
    """
    vet = create_veteran(total_active_duty_days=1095)
    plan = propose_voc_rehab_plan(vet["id"], planned_months=12, track="SELF_EMPLOYMENT")
    rejected = validate_success(api.reject_voc_rehab_plan(plan["id"], ADMIN), 200)
    assert rejected["status"] == "REJECTED"
    vet_after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert vet_after["voc_rehab_entitlement_months"] == 48, (
        "rejection does not debit entitlement"
    )


def test_compensation_summary_computed_read(api):
    """PRD §3.1: "a compensation summary that reports the veteran's
    `combined_rating_pct`, `provisional_combined_rating_pct`,
    `monthly_compensation_cents`, `gi_bill_tier_pct`,
    `voc_rehab_entitlement_months`, and the `active_dependent_count` — the number
    of the veteran's dependents currently in `ACTIVE` status."
    PRD §3.8: "50 pays 109,900 cents".

    Design: Corner/endpoints/compensation_summary_computed_read
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    summary = validate_success(api.get_compensation_summary(vet["id"], ADMIN), 200)
    assert summary["combined_rating_pct"] == 50
    assert summary["monthly_compensation_cents"] == 109900
    assert summary["gi_bill_tier_pct"] == 100
    assert summary["active_dependent_count"] == 0


# ─── helpers ──────────────────────────────────────────────────────────────

def _activated_award_veteran(api):
    """Create a veteran with combined_rating_pct=30 and an ACTIVE award."""
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 30}])
    fresh = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    get_success_data(
        api.activate_award(
            vet["id"], {"expected_veteran_version": fresh["version"]}, ADMIN
        )
    )
    return fresh
