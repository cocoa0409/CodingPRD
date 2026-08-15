"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup step failed"
errors.

Identity threading (PRD §2.1): ProviderRep calls always carry
make_provider_rep_headers(provider["id"]) — the representative's X-User-ID is
the provider account's id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULTS
from .factories import (
    create_asp_schedule_payload,
    create_auth_payload,
    create_biosimilar_policy_payload,
    create_claim_payload,
    create_clinical_policy_payload,
    create_drug_payload,
    create_pipeline_drug_payload,
    create_provider_account_payload,
    create_spend_forecast_payload,
)
from .test_users import TEST_USERS, make_provider_rep_headers

ADMIN = TEST_USERS["plan_admin_headers"]
MPO = TEST_USERS["mpo_headers"]
CM = TEST_USERS["case_manager_headers"]
ANALYST = TEST_USERS["pharmacy_analyst_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: single-entity creates and the drug+policy backbone
# ---------------------------------------------------------------------------


def create_drug(**overrides):
    """Register a drug and return the created DrugCatalogEntry (PRD §3.1)."""
    resp = api_client.create_drug(create_drug_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_drug_version(drug_id):
    """Read the drug's current OCC version (canonical source, PRD §3.1)."""
    return get_success_data(api_client.get_drug(drug_id, ADMIN))["version"]


def create_policy(drug_id, expected_drug_version=None, **overrides):
    """Create a clinical policy version, OCC-guarded (PRD §2.7, §3.2).

    When expected_drug_version is omitted the drug is re-read so the OCC field
    is always fresh.
    """
    if expected_drug_version is None:
        expected_drug_version = get_drug_version(drug_id)
    resp = api_client.create_clinical_policy(
        create_clinical_policy_payload(
            drug_id, expected_drug_version, **overrides
        ),
        MPO,
    )
    return get_success_data(resp)


def activate_policy(policy_id, drug_id):
    """Activate a DRAFT policy with a freshly-read OCC version (PRD §3.2)."""
    resp = api_client.activate_clinical_policy(
        policy_id, {"expected_drug_version": get_drug_version(drug_id)}, MPO
    )
    return get_success_data(resp)


def publish_rate(drug_id, asp_rate_cents=None, effective_start=None):
    """Publish an ASP rate schedule (PRD §3.3)."""
    overrides = {}
    if asp_rate_cents is not None:
        overrides["asp_rate_cents"] = asp_rate_cents
    if effective_start is not None:
        overrides["effective_start"] = effective_start
    resp = api_client.create_asp_schedule(
        create_asp_schedule_payload(drug_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_provider(**overrides):
    """Register a provider organization (PRD §3.3)."""
    resp = api_client.create_provider_account(
        create_provider_account_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def setup_drug_with_policy(
    drug_overrides=None,
    policy_overrides=None,
    with_rate=True,
    rate_cents=None,
    rate_effective_start=None,
):
    """Drug (+ optional ASP rate) + ACTIVE clinical policy.

    Returns dict(drug, policy, schedule). Drug version after the ACTIVE policy
    create is available via get_drug_version(drug["id"]).
    """
    drug = create_drug(**(drug_overrides or {}))
    schedule = None
    if with_rate:
        schedule = publish_rate(
            drug["id"],
            asp_rate_cents=rate_cents,
            effective_start=rate_effective_start,
        )
    policy = create_policy(drug["id"], drug["version"], **(policy_overrides or {}))
    return {"drug": drug, "policy": policy, "schedule": schedule}


# ---------------------------------------------------------------------------
# Tier 2/3: authorization lifecycle
# ---------------------------------------------------------------------------


def submit_auth(drug_id, provider_id, member_id=None, **overrides):
    """Submit a prior authorization as the owning ProviderRep (PRD §3.4).

    Override values of None remove the key entirely (conditional-presence rules
    require e.g. requested_dose_mg to be absent for weight-based drugs).
    """
    payload = create_auth_payload(drug_id, member_id, **overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = api_client.create_prior_authorization(
        payload, make_provider_rep_headers(provider_id)
    )
    return get_success_data(resp)


def approve_auth(auth_id, max_administrations=None):
    """Approve a SUBMITTED authorization (PRD §3.4)."""
    resp = api_client.approve_auth(
        auth_id,
        {"max_administrations": max_administrations or DEFAULTS["MAX_ADMINISTRATIONS"]},
        MPO,
    )
    return get_success_data(resp)


def setup_approved_scenario(
    drug_overrides=None,
    policy_overrides=None,
    member_id=None,
    auth_overrides=None,
    max_administrations=None,
    rate_cents=None,
    with_rate=True,
):
    """Full claimable chain: drug (+ASP rate) + ACTIVE policy + provider +
    APPROVED authorization (PRD §3.4).

    Returns dict(drug, policy, schedule, provider, auth, rep_headers).
    """
    backbone = setup_drug_with_policy(
        drug_overrides=drug_overrides,
        policy_overrides=policy_overrides,
        with_rate=with_rate,
        rate_cents=rate_cents,
    )
    provider = create_provider()
    auth = submit_auth(
        backbone["drug"]["id"], provider["id"], member_id, **(auth_overrides or {})
    )
    auth = approve_auth(auth["id"], max_administrations)
    return {
        **backbone,
        "provider": provider,
        "auth": auth,
        "rep_headers": make_provider_rep_headers(provider["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: claims
# ---------------------------------------------------------------------------


def submit_claim(scenario, **overrides):
    """Create a claim as the owning ProviderRep; expects adjudication success
    (APPROVED_FOR_PAYMENT or PENDED). Returns the InfusionClaim (PRD §3.6)."""
    drug = scenario["drug"]
    auth = scenario["auth"]
    payload = create_claim_payload(auth["id"], drug["id"], drug["j_code"], **overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = api_client.create_claim(payload, scenario["rep_headers"])
    return get_success_data(resp)


def pay_claim(claim_id):
    """Pay an APPROVED_FOR_PAYMENT claim (PRD §3.6)."""
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def get_auth(auth_id):
    return get_success_data(api_client.get_prior_authorization(auth_id, ADMIN))


def get_provider(provider_id):
    return get_success_data(api_client.get_provider_account(provider_id, ADMIN))


def list_claims_for_auth(auth_id, status=None):
    params = {"auth_id": auth_id}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_claims(ADMIN, params=params))


def list_adjustments_for_claim(claim_id):
    return get_success_data(
        api_client.list_claim_adjustments(ADMIN, params={"claim_id": claim_id})
    )


# ---------------------------------------------------------------------------
# Tier 3/5: redirections
# ---------------------------------------------------------------------------


def setup_offered_redirection(max_administrations=None, member_id=None):
    """Eligible drug + policy requiring redirection + APPROVED auth, so exactly
    one OFFERED redirection exists (PRD §3.4, §3.5).

    Returns the scenario dict plus "redirection".
    """
    scenario = setup_approved_scenario(
        drug_overrides={"site_of_care_eligible": True},
        policy_overrides={"requires_site_of_care_redirection": True},
        member_id=member_id,
        max_administrations=max_administrations,
    )
    redirection = get_redirection_for_auth(scenario["auth"]["id"])
    return {**scenario, "redirection": redirection}


def get_redirection_for_auth(auth_id):
    data = get_success_data(api_client.list_redirections(CM, params={"auth_id": auth_id}))
    assert len(data) == 1, f"Expected exactly one redirection for auth {auth_id}"
    return data[0]


def get_redirection(redirection_id):
    return get_success_data(api_client.get_redirection(redirection_id, CM))


# ---------------------------------------------------------------------------
# Tier 3: biosimilar policies
# ---------------------------------------------------------------------------


def create_biosimilar_policy(reference_drug_id, biosimilar_drug_id, **overrides):
    """Create a DRAFT biosimilar policy (PRD §3.7)."""
    resp = api_client.create_biosimilar_policy(
        create_biosimilar_policy_payload(
            reference_drug_id, biosimilar_drug_id, **overrides
        ),
        ADMIN,
    )
    return get_success_data(resp)


def activate_biosimilar_policy(policy_id):
    return get_success_data(api_client.activate_biosimilar_policy(policy_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: paid-claim scenarios feeding the repricing / ledger tests (PRD §3.3)
# ---------------------------------------------------------------------------


def setup_paid_claim_scenario(
    billed_units=2,
    rate_cents=500,
    member_id=None,
    service_date=None,
    auth_overrides=None,
    max_administrations=None,
):
    """Drug (rate `rate_cents` effective 2026-01-01) + policy + provider +
    APPROVED auth (100 mg) + one claim of `billed_units` units, PAID.

    Returns dict(scenario fields + claim).
    """
    scenario = setup_approved_scenario(
        rate_cents=rate_cents,
        member_id=member_id,
        auth_overrides=auth_overrides,
        max_administrations=max_administrations,
    )
    claim_overrides = {"billed_units": billed_units}
    if service_date is not None:
        claim_overrides["service_date"] = service_date
    claim = submit_claim(scenario, **claim_overrides)
    claim = pay_claim(claim["id"])
    return {**scenario, "claim": claim}


# ---------------------------------------------------------------------------
# Tier 4: pipeline registry + forecasts
# ---------------------------------------------------------------------------


def register_pipeline_drug(**overrides):
    resp = api_client.create_pipeline_drug(
        create_pipeline_drug_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def run_forecast(variant="BASELINE", horizon_years=1, enrollment_projection=500000):
    resp = api_client.create_spend_forecast(
        create_spend_forecast_payload(
            variant=variant,
            horizon_years=horizon_years,
            enrollment_projection=enrollment_projection,
        ),
        ANALYST,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.4); applies due transitions eagerly."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
