"""The guarded authorization-approve write: priority conflicts, overlap, capacity,
IPE dependency, and optimistic concurrency.

Difficulty queue (§1.8): priority_pair_validation_conflict (both instances);
cross_entity_state_dependency / authorization_approve_requires_ipe_approved;
resource_temporal_overlap (both instances).
Corner queue (§1.9): cross_cutting_complexity_layers / occ_stale_case_version_conflict.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_services_active_case, setup_plan_development_case, bootstrap_actors,
    new_services_active_case, request_authorization, request_and_approve_authorization,
    create_provider, get_case_version, create_authorization_payload,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


# ─── Difficulty: state (P8) beats fiscal (P17) ───────────────────────

def test_state_beats_fiscal_returns_invalid_state(api):
    """PRD §3.6: "the state check that the authorization is `REQUESTED` (else
    `ERR_INVALID_STATE`); the requirement that the case's most recent IPE is
    `APPROVED` (else `ERR_IPE_NOT_APPROVED`); the provider-eligibility check that the
    provider's `status` is `ACTIVE` and the authorization's `service_category` is
    among the provider's `service_categories` (else `ERR_PROVIDER_INELIGIBLE`); the
    period-overlap check; the provider-capacity check; and finally the budget check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorization_approve
    """
    ctx = setup_services_active_case(budget_allocated_cents=100000, monthly_income_cents=150000)
    auth = request_authorization(ctx, authorized_amount_cents=300000, comparable_benefit_cents=0)
    validate_success(api.cancel_authorization(auth["id"], ctx["counselor_headers"]), 200)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    validate_error(res, "ERR_INVALID_STATE")


def test_state_beats_fiscal_leaves_authorization_cancelled(api):
    """PRD §3.6: "the state check that the authorization is `REQUESTED` (else
    `ERR_INVALID_STATE`); ... and finally the budget check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorization_approve
    """
    ctx = setup_services_active_case(budget_allocated_cents=100000, monthly_income_cents=150000)
    auth = request_authorization(ctx, authorized_amount_cents=300000, comparable_benefit_cents=0)
    api.cancel_authorization(auth["id"], ctx["counselor_headers"])
    version = get_case_version(ctx["case_id"])
    api.approve_authorization(auth["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    after = validate_success(api.get_authorization(auth["id"], VRADMIN), 200)
    assert after["status"] == "CANCELLED"


# ─── Difficulty: referential (P11) beats temporal (P12) ──────────────

def _case_with_two_providers_overlap(api):
    ctx = setup_services_active_case(budget_allocated_cents=1000000, monthly_income_cents=150000)
    provider2 = create_provider(name="P2", service_categories=["TRAINING"],
                                max_concurrent_authorizations=5, status="SUSPENDED")
    # Auth A on the ACTIVE provider1, APPROVED.
    request_and_approve_authorization(ctx, service_category="TRAINING", authorized_amount_cents=100000,
                                      service_period_start="2026-05-01", service_period_end="2026-05-31")
    # Auth B on SUSPENDED provider2, overlapping period on same case + category.
    auth_b = get_success_data(api.create_authorization(
        create_authorization_payload(ctx["case_id"], ctx["ipe_id"], provider2["id"],
                                     service_category="TRAINING", authorized_amount_cents=100000,
                                     comparable_benefit_cents=0,
                                     service_period_start="2026-05-15", service_period_end="2026-06-15"),
        ctx["counselor_headers"]))
    return ctx, auth_b


def test_referential_beats_temporal_returns_provider_ineligible(api):
    """PRD §3.6: "the provider-eligibility check that the provider's `status` is
    `ACTIVE` and the authorization's `service_category` is among the provider's
    `service_categories` (else `ERR_PROVIDER_INELIGIBLE`); the period-overlap check".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_authorization_approve
    """
    ctx, auth_b = _case_with_two_providers_overlap(api)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth_b["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    validate_error(res, "ERR_PROVIDER_INELIGIBLE")


def test_referential_beats_temporal_leaves_authorization_requested(api):
    """PRD §3.6: "the provider-eligibility check that the provider's `status` is
    `ACTIVE` and the authorization's `service_category` is among the provider's
    `service_categories` (else `ERR_PROVIDER_INELIGIBLE`); the period-overlap check".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_authorization_approve
    """
    ctx, auth_b = _case_with_two_providers_overlap(api)
    version = get_case_version(ctx["case_id"])
    api.approve_authorization(auth_b["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    after = validate_success(api.get_authorization(auth_b["id"], VRADMIN), 200)
    assert after["status"] == "REQUESTED"


# ─── Difficulty: approve requires IPE APPROVED ───────────────────────

def test_authorization_approve_requires_ipe_approved(api):
    """PRD §3.6: "the requirement that the case's most recent IPE is `APPROVED` (else
    `ERR_IPE_NOT_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/authorization_approve_requires_ipe_approved
    """
    ctx = setup_plan_development_case(budget_allocated_cents=1000000, monthly_income_cents=150000)
    api.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"])  # IPE SUBMITTED, not APPROVED
    auth = request_authorization(ctx, authorized_amount_cents=100000)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    validate_error(res, "ERR_IPE_NOT_APPROVED")


def test_authorization_approve_ipe_not_approved_leaves_requested(api):
    """PRD §3.6: "the requirement that the case's most recent IPE is `APPROVED` (else
    `ERR_IPE_NOT_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/authorization_approve_requires_ipe_approved
    """
    ctx = setup_plan_development_case(budget_allocated_cents=1000000, monthly_income_cents=150000)
    api.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"])
    auth = request_authorization(ctx, authorized_amount_cents=100000)
    version = get_case_version(ctx["case_id"])
    api.approve_authorization(auth["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    after = validate_success(api.get_authorization(auth["id"], VRADMIN), 200)
    assert after["status"] == "REQUESTED"


# ─── Difficulty: same-case closed-interval overlap ───────────────────

def _case_with_overlapping_second_auth(api):
    ctx = setup_services_active_case(budget_allocated_cents=1000000, monthly_income_cents=150000)
    request_and_approve_authorization(ctx, service_category="TRAINING", authorized_amount_cents=100000,
                                      service_period_start="2026-05-01", service_period_end="2026-05-31")
    auth_b = request_authorization(ctx, service_category="TRAINING", authorized_amount_cents=100000,
                                   service_period_start="2026-05-31", service_period_end="2026-06-30")
    return ctx, auth_b


def test_same_case_closed_interval_adjacency_conflict(api):
    """PRD §3.6: "The period-overlap check rejects approval with
    `ERR_AUTHORIZATION_PERIOD_OVERLAP` when another `APPROVED` authorization on the
    **same case and same `service_category`** has a service period that overlaps the
    requested `[service_period_start, service_period_end]` treated as a closed
    interval, so that merely touching endpoints conflict."

    Design: Difficulty/resource_temporal_overlap/same_case_category_closed_interval_adjacency_conflict
    """
    ctx, auth_b = _case_with_overlapping_second_auth(api)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth_b["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    validate_error(res, "ERR_AUTHORIZATION_PERIOD_OVERLAP")


def test_same_case_closed_interval_adjacency_leaves_requested(api):
    """PRD §3.6: "The period-overlap check rejects approval with
    `ERR_AUTHORIZATION_PERIOD_OVERLAP` when another `APPROVED` authorization on the
    **same case and same `service_category`** has a service period that overlaps the
    requested `[service_period_start, service_period_end]` treated as a closed
    interval, so that merely touching endpoints conflict."

    Design: Difficulty/resource_temporal_overlap/same_case_category_closed_interval_adjacency_conflict
    """
    ctx, auth_b = _case_with_overlapping_second_auth(api)
    version = get_case_version(ctx["case_id"])
    api.approve_authorization(auth_b["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    after = validate_success(api.get_authorization(auth_b["id"], VRADMIN), 200)
    assert after["status"] == "REQUESTED"


# ─── Difficulty: provider capacity on half-open aggregate ────────────

def _two_cases_provider_capacity(api):
    ctx = bootstrap_actors(
        provider=True,
        provider_overrides={"service_categories": ["TRAINING", "ASSISTIVE_TECH"],
                            "max_concurrent_authorizations": 1},
        category_overrides={"slot_capacity": 5})
    ch, sh = ctx["counselor_headers"], ctx["supervisor_headers"]
    case1_id, ipe1_id = new_services_active_case(ch, sh, consumer_full_name="Pat Ray")
    case2_id, ipe2_id = new_services_active_case(ch, sh, consumer_full_name="Quo Ray")
    # Auth A on provider, case1, TRAINING [05-01,05-31], APPROVED.
    auth_a = get_success_data(api.create_authorization(
        create_authorization_payload(case1_id, ipe1_id, ctx["provider_id"], service_category="TRAINING",
                                     authorized_amount_cents=100000, comparable_benefit_cents=0,
                                     service_period_start="2026-05-01", service_period_end="2026-05-31"), ch))
    v1 = get_case_version(case1_id)
    get_success_data(api.approve_authorization(auth_a["id"], {"expected_case_version": v1}, sh))
    # Auth B on same provider, case2, ASSISTIVE_TECH [05-15,06-15] overlapping half-open window.
    auth_b = get_success_data(api.create_authorization(
        create_authorization_payload(case2_id, ipe2_id, ctx["provider_id"], service_category="ASSISTIVE_TECH",
                                     authorized_amount_cents=100000, comparable_benefit_cents=0,
                                     service_period_start="2026-05-15", service_period_end="2026-06-15"), ch))
    return sh, case2_id, auth_b


def test_provider_capacity_half_open_exceeded(api):
    """PRD §3.6: "The provider-capacity check rejects with
    `ERR_PROVIDER_CAPACITY_EXCEEDED` when approving would cause the number of the
    provider's overlapping `APPROVED` authorizations — measured on the half-open
    interval `[start, end)`, so touching endpoints do **not** conflict — to exceed
    the provider's `max_concurrent_authorizations`."

    Design: Difficulty/resource_temporal_overlap/provider_capacity_half_open_aggregate
    """
    sh, case2_id, auth_b = _two_cases_provider_capacity(api)
    version = get_success_data(api.get_case(case2_id, VRADMIN))["version"]
    res = api.approve_authorization(auth_b["id"], {"expected_case_version": version}, sh)
    validate_error(res, "ERR_PROVIDER_CAPACITY_EXCEEDED")


def test_provider_capacity_half_open_leaves_requested(api):
    """PRD §3.6: "The provider-capacity check rejects with
    `ERR_PROVIDER_CAPACITY_EXCEEDED` when approving would cause the number of the
    provider's overlapping `APPROVED` authorizations — measured on the half-open
    interval `[start, end)`, so touching endpoints do **not** conflict — to exceed
    the provider's `max_concurrent_authorizations`."

    Design: Difficulty/resource_temporal_overlap/provider_capacity_half_open_aggregate
    """
    sh, case2_id, auth_b = _two_cases_provider_capacity(api)
    version = get_success_data(api.get_case(case2_id, VRADMIN))["version"]
    api.approve_authorization(auth_b["id"], {"expected_case_version": version}, sh)
    after = validate_success(api.get_authorization(auth_b["id"], VRADMIN), 200)
    assert after["status"] == "REQUESTED"


# ─── Corner: optimistic concurrency stale version ────────────────────

def test_occ_stale_case_version_conflict(api):
    """PRD §2.7: "If `expected_case_version` does not equal the case's current
    `version` — for example because another approval has since committed funds and
    advanced the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    and no funds are committed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_conflict
    """
    ctx = setup_services_active_case(budget_allocated_cents=500000, monthly_income_cents=150000)
    auth = request_authorization(ctx, authorized_amount_cents=100000)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth["id"], {"expected_case_version": version - 1}, ctx["supervisor_headers"])
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_authorization(auth["id"], VRADMIN), 200)
    assert after["status"] == "REQUESTED"
