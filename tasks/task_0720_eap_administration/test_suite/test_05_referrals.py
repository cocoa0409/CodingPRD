"""Referrals: provider selection, lifecycle, work-life cap, ownership."""
import pytest
from test_helpers import (
    TEST_USERS, make_provider_headers,
    validate_success, validate_error, ApiErrorId,
    create_referral_payload,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


# ===========================================================================
# Combinatorial: provider selection least-loaded + created_at tie-break  (Difficulty)
# ===========================================================================
def test_provider_selection_least_loaded_with_created_at_tiebreak(api):
    """PRD §3.7: "the server picks the candidate with the lowest
    `active_referral_count`; ties are broken by the earliest provider
    `created_at`, and the provider `id` is never used as a tie-breaker."
    PRD §3.7: "The candidate pool is every provider whose `accepting` flag is
    true, whose `network_status` is `IN_NETWORK`, whose `specialties` include the
    referral's required specialty, and whose `id` is not the excluded provider."

    Design: Difficulty/combinatorial_formula/provider_selection_least_loaded_with_created_at_tiebreak
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    p1 = fx.create_provider(full_name="P1", network_status="IN_NETWORK",
                            specialties=["STRESS"], accepting=True)
    p2 = fx.create_provider(full_name="P2", network_status="IN_NETWORK",
                            specialties=["STRESS"], accepting=True)
    fx.create_provider(full_name="P3", network_status="OUT_OF_NETWORK",
                       specialties=["STRESS"], accepting=True)
    ref = validate_success(api.create_referral(
        create_referral_payload(employee["id"], "STRESS", referral_type="WORKLIFE"), COORD), 201)
    # both p1,p2 load 0; earliest created_at (p1) wins; p3 excluded (OON)
    assert ref["provider_id"] == p1["id"]
    assert validate_success(api.get_provider(p1["id"], ADMIN))["active_referral_count"] == 1


def test_provider_selection_excludes_non_matching_specialty(api):
    """PRD §3.7: "The candidate pool is every provider whose `accepting` flag is
    true, whose `network_status` is `IN_NETWORK`, whose `specialties` include the
    referral's required specialty, and whose `id` is not the excluded provider."

    Design: Difficulty/combinatorial_formula/provider_selection_least_loaded_with_created_at_tiebreak
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    # p_wrong matches neither specialty; p_right is the only eligible candidate.
    fx.create_provider(full_name="Wrong", network_status="IN_NETWORK",
                       specialties=["GRIEF"], accepting=True)
    p_right = fx.create_provider(full_name="Right", network_status="IN_NETWORK",
                                 specialties=["STRESS"], accepting=True)
    ref = validate_success(api.create_referral(
        create_referral_payload(employee["id"], "STRESS", referral_type="WORKLIFE"), COORD), 201)
    assert ref["provider_id"] == p_right["id"]


# ===========================================================================
# Compensating invariant: request then decline preserves count  (Difficulty)
# ===========================================================================
def test_request_then_decline_referral_preserves_provider_count(api):
    """PRD §3.7: "On creation the server auto-selects a provider, the referral's
    `status` becomes `REQUESTED`, the chosen provider is recorded in
    `provider_id`, and that provider's `active_referral_count` rises by one."
    PRD §3.7: "Declining clears the referral's `provider_id` to null, decrements
    that provider's `active_referral_count`, and makes the referral eligible for
    re-selection."

    Design: Difficulty/compensating_invariant/request_then_decline_referral_preserves_provider_count
    """
    contract, employee, providers, ref = fx.setup_referral(
        required_specialty="STRESS", provider_specs=[
            {"full_name": "Dr S", "network_status": "IN_NETWORK",
             "specialties": ["STRESS"], "accepting": True}])
    prov = providers[0]
    assert ref["provider_id"] == prov["id"]
    declined = validate_success(api.decline_referral(
        ref["id"], make_provider_headers(prov["id"])))
    assert declined["status"] == "DECLINED"
    assert declined["provider_id"] is None
    assert validate_success(api.get_provider(prov["id"], ADMIN))["active_referral_count"] == 0


def test_referral_creation_bumps_provider_count(api):
    """PRD §3.7: "On creation the server auto-selects a provider, the referral's
    `status` becomes `REQUESTED`, the chosen provider is recorded in
    `provider_id`, and that provider's `active_referral_count` rises by one."

    Design: Difficulty/compensating_invariant/request_then_decline_referral_preserves_provider_count
    """
    contract, employee, providers, ref = fx.setup_referral(
        required_specialty="STRESS", provider_specs=[
            {"full_name": "Dr S2", "network_status": "IN_NETWORK",
             "specialties": ["STRESS"], "accepting": True}])
    prov = providers[0]
    assert ref["status"] == "REQUESTED"
    assert ref["provider_id"] == prov["id"]
    assert validate_success(api.get_provider(prov["id"], ADMIN))["active_referral_count"] == 1


# ===========================================================================
# Referral lifecycle corners
# ===========================================================================
def test_referral_decline_then_reassign_excludes_decliner(api):
    """PRD §3.7: "A `CareCoordinator` then **reassigns** a declined referral,
    returning it from `DECLINED` to `REQUESTED` by selecting a new provider
    through the selection policy with the just-declined provider excluded ... and
    on success the newly selected provider's `active_referral_count` rises by one."

    Design: Corner/state_machines/referral_decline_then_reassign_excludes_decliner
    """
    contract, employee, providers, ref = fx.setup_referral(
        required_specialty="STRESS", provider_specs=[
            {"full_name": "P1", "network_status": "IN_NETWORK",
             "specialties": ["STRESS"], "accepting": True},
            {"full_name": "P2", "network_status": "IN_NETWORK",
             "specialties": ["STRESS"], "accepting": True}])
    p1, p2 = providers
    assert ref["provider_id"] == p1["id"]
    validate_success(api.decline_referral(ref["id"], make_provider_headers(p1["id"])))
    reassigned = validate_success(api.reassign_referral(ref["id"], COORD))
    assert reassigned["status"] == "REQUESTED"
    assert reassigned["provider_id"] == p2["id"]
    assert validate_success(api.get_provider(p2["id"], ADMIN))["active_referral_count"] == 1


def test_complete_referral_lifecycle_accept_then_complete(api):
    """PRD §3.7: "From `REQUESTED`, the assigned provider may **accept** (to
    `ACCEPTED`) ... From `ACCEPTED`, the assigned provider **completes** the
    referral (to `COMPLETED`), which lowers that provider's
    `active_referral_count` by one."

    Design: Corner/endpoints/complete_referral_lifecycle_accept_then_complete
    """
    contract, employee, providers, ref = fx.setup_referral(
        required_specialty="STRESS", provider_specs=[
            {"full_name": "Dr Lf", "network_status": "IN_NETWORK",
             "specialties": ["STRESS"], "accepting": True}])
    prov = providers[0]
    validate_success(api.accept_referral(ref["id"], make_provider_headers(prov["id"])))
    completed = validate_success(api.complete_referral(
        ref["id"], make_provider_headers(prov["id"])))
    assert completed["status"] == "COMPLETED"
    assert validate_success(api.get_provider(prov["id"], ADMIN))["active_referral_count"] == 0


def test_worklife_cap_exceeded_on_third_referral(api):
    """PRD §3.7: "For a `WORKLIFE`, `LEGAL`, or `FINANCIAL` referral, the work-life
    cap is enforced before the referral is created: the employee's
    `worklife_referrals_used` plus one must be less than or equal to the plan's
    `worklife_referrals_per_year`, or the create is rejected with
    `ERR_WORKLIFE_CAP_EXCEEDED`."

    Design: Corner/validations/worklife_cap_exceeded_on_fourth_referral
    """
    contract, plan, employee = fx.setup_contract_plan_employee(
        plan_overrides={"worklife_referrals_per_year": 2})
    fx.create_provider(full_name="WL1", network_status="IN_NETWORK",
                       specialties=["FINANCIAL_STRESS"], accepting=True)
    fx.create_provider(full_name="WL2", network_status="IN_NETWORK",
                       specialties=["FINANCIAL_STRESS"], accepting=True)
    validate_success(api.create_referral(create_referral_payload(
        employee["id"], "FINANCIAL_STRESS", referral_type="WORKLIFE"), COORD), 201)
    validate_success(api.create_referral(create_referral_payload(
        employee["id"], "FINANCIAL_STRESS", referral_type="LEGAL"), COORD), 201)
    # third (FINANCIAL) would make used+1 = 3 > cap 2
    validate_error(api.create_referral(create_referral_payload(
        employee["id"], "FINANCIAL_STRESS", referral_type="FINANCIAL"), COORD),
        ApiErrorId.ERR_WORKLIFE_CAP_EXCEEDED.value)


def test_no_provider_available_empty_pool(api):
    """PRD §3.7: "If the candidate pool is empty after these filters, the
    operation fails with `ERR_NO_PROVIDER_AVAILABLE`."

    To isolate ERR_NO_PROVIDER_AVAILABLE we must keep the required specialty
    RESOLVABLE against the network (PRD §2.2: "the requested specialty must be
    resolvable against the provider network", checked as ERR_REFERENTIAL_MISMATCH
    at the higher cross-foreign-key-consistency priority of §2.6) while still
    emptying the §3.7 candidate pool. So we register a provider that DOES carry
    the STRESS specialty but is filtered out of the candidate pool by the other
    selection filters (accepting=false, and out-of-network). Specialty is thus
    resolvable (no referential mismatch) but the candidate pool is empty.

    Design: Corner/calculations/no_provider_available_empty_pool
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    # Carries the required specialty (so specialty IS resolvable -> no
    # REFERENTIAL_MISMATCH) but is excluded from the candidate pool because it
    # is not accepting and is out-of-network.
    fx.create_provider(full_name="RightSpecButFiltered",
                       network_status="OUT_OF_NETWORK",
                       specialties=["STRESS"], accepting=False)
    validate_error(api.create_referral(create_referral_payload(
        employee["id"], "STRESS", referral_type="WORKLIFE"), COORD),
        ApiErrorId.ERR_NO_PROVIDER_AVAILABLE.value)


def test_non_assigned_provider_cannot_accept_referral(api):
    """PRD §3.7: "in both cases the acting provider must be the referral's
    assigned provider, or the action is rejected with `ERR_NOT_ASSIGNED_PROVIDER`."

    Design: Corner/rbac/non_assigned_provider_cannot_accept_referral
    """
    contract, plan, employee = fx.setup_contract_plan_employee(
        plan_overrides={"worklife_referrals_per_year": 5})
    p1 = fx.create_provider(full_name="P1", network_status="IN_NETWORK",
                            specialties=["STRESS"], accepting=True)
    p2 = fx.create_provider(full_name="P2", network_status="IN_NETWORK",
                            specialties=["GRIEF"], accepting=True)
    ref = validate_success(api.create_referral(create_referral_payload(
        employee["id"], "STRESS", referral_type="WORKLIFE"), COORD), 201)
    assert ref["provider_id"] == p1["id"]
    validate_error(api.accept_referral(ref["id"], make_provider_headers(p2["id"])),
                   ApiErrorId.ERR_NOT_ASSIGNED_PROVIDER.value)
