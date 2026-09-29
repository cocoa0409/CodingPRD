"""
Composite state builders and pytest fixtures.

The server is relaunched with an empty database before every test, so every
precondition has to be built from scratch through the API. The builders below
assemble the recurring compositions — a book of business, an issued
certificate, a claim whose evidence log is complete, a general average whose
security is fully lodged — so individual tests only describe what is unusual
about their own scenario.

Nothing here asserts a rule under test; failures inside a builder mean the
precondition could not be established.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    UNDERWRITER,
    make_assured_headers,
)
from .types import JsonDict


# ---------------------------------------------------------------------------
# Tier 1 — the book of business every scenario starts from
# ---------------------------------------------------------------------------
def build_canonical_environment(
    api: ApiClient,
    loading_port: Optional[JsonDict] = None,
    discharge_port: Optional[JsonDict] = None,
    vessel: Optional[JsonDict] = None,
    commodity_class_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    activate_policy: bool = True,
) -> JsonDict:
    """
    Build two green ports, an S3 commodity class, a screened 2015-built hull and
    an active open cover. Returns every created row plus the assured's headers.
    """
    port_load = F.create_port(api, loading_port or C.PORT_SGSIN)
    port_discharge = F.create_port(api, discharge_port or C.PORT_NLRTM)
    commodity_class = F.create_commodity_class(api, **(commodity_class_overrides or {}))
    hull = F.create_vessel(api, vessel or C.VESSEL_KITE)
    policy = F.create_open_policy(api, activate=activate_policy,
                                  **(policy_overrides or {}))
    return {
        "loading_port": port_load,
        "discharge_port": port_discharge,
        "commodity_class": commodity_class,
        "vessel": hull,
        "policy": policy,
        "loading_port_id": port_load["id"],
        "discharge_port_id": port_discharge["id"],
        "commodity_class_id": commodity_class["id"],
        "vessel_id": hull["id"],
        "policy_id": policy["id"],
        "assured": make_assured_headers(policy["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2 — a declared shipment, and an issued one
# ---------------------------------------------------------------------------
def build_draft_certificate(api: ApiClient, env: JsonDict,
                            base: Optional[JsonDict] = None,
                            **overrides: Any) -> JsonDict:
    """Declare one shipment against the environment's open cover."""
    return F.create_certificate(
        api,
        env["policy_id"],
        env["commodity_class_id"],
        overrides.pop("vessel_id", env["vessel_id"]),
        overrides.pop("loading_port_id", env["loading_port_id"]),
        overrides.pop("discharge_port_id", env["discharge_port_id"]),
        base=base,
        **overrides,
    )


def build_issued_certificate(api: ApiClient, env: JsonDict,
                             base: Optional[JsonDict] = None,
                             **overrides: Any) -> JsonDict:
    """Declare and issue one shipment; returns the issued certificate."""
    draft = build_draft_certificate(api, env, base=base, **overrides)
    return F.issue_certificate(api, draft["id"], env["policy_id"])


def build_environment_with_issued_certificate(api: ApiClient,
                                             **env_kwargs: Any) -> JsonDict:
    """
    The canonical environment plus one issued CIF certificate carrying war and
    strikes cover — insured value 1155000.00, total premium 6444.91.
    """
    env = build_canonical_environment(api, **env_kwargs)
    env["certificate"] = build_issued_certificate(api, env)
    env["certificate_id"] = env["certificate"]["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 3 — a conveyance carrying two issued certificates
# ---------------------------------------------------------------------------
def build_two_contributor_conveyance(api: ApiClient,
                                     **env_kwargs: Any) -> JsonDict:
    """
    Two certificates issued on one hull for the same sailing date: a CIF
    shipment insured for 1155000.00 and a declared-value shipment insured for
    800000.00 — the pair a general average is stated over.
    """
    env = build_canonical_environment(api, **env_kwargs)
    env["certificate_a"] = build_issued_certificate(api, env)
    env["certificate_d"] = build_issued_certificate(
        api, env, base=C.CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-D", declared_value=800000,
        package_count=80, gross_weight_kg=12000)
    env["certificate_a_id"] = env["certificate_a"]["id"]
    env["certificate_d_id"] = env["certificate_d"]["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 4 — general average, declared / called / fully secured
# ---------------------------------------------------------------------------
def build_ga_event_with_security_calls(api: ApiClient,
                                       **env_kwargs: Any) -> JsonDict:
    """
    A general average declared over the two-contributor conveyance with its
    security calls issued: postings of 93049.60 and 64450.40 are outstanding.
    """
    env = build_two_contributor_conveyance(api, **env_kwargs)
    ga_event = F.declare_ga_event(api, env["vessel_id"])
    env["ga_event"] = F.issue_ga_security_calls(api, ga_event["id"])
    env["ga_event_id"] = ga_event["id"]
    env["posting_a"] = F.ga_posting_for_certificate(
        api, ga_event["id"], env["certificate_a_id"])
    env["posting_d"] = F.ga_posting_for_certificate(
        api, ga_event["id"], env["certificate_d_id"])
    env["posting_a_id"] = env["posting_a"]["id"]
    env["posting_d_id"] = env["posting_d"]["id"]
    return env


def build_ga_security_complete(api: ApiClient, **env_kwargs: Any) -> JsonDict:
    """
    The same general average with both securities lodged exactly as called, so
    the event has collected its security and the hull is held for adjustment.
    """
    env = build_ga_event_with_security_calls(api, **env_kwargs)
    env["posting_a"] = F.post_ga_security(
        api, env["posting_a_id"], env["policy_id"],
        C.EXPECTED_GA_CONTRIBUTION_LARGEST, C.EXPECTED_GA_DEPOSIT_LARGEST,
        ga_event_id=env["ga_event_id"])
    env["posting_d"] = F.post_ga_security(
        api, env["posting_d_id"], env["policy_id"],
        C.EXPECTED_GA_CONTRIBUTION_SMALLER, C.EXPECTED_GA_DEPOSIT_SMALLER,
        ga_event_id=env["ga_event_id"])
    env["ga_event"] = get_success_data(
        api.get_ga_event(env["ga_event_id"], CLAIMS_ADJUSTER))
    return env


# ---------------------------------------------------------------------------
# Tier 4 — claims, surveys and declarations
# ---------------------------------------------------------------------------
def build_claim_with_complete_evidence(api: ApiClient,
                                       claim_overrides: Optional[Dict[str, Any]] = None,
                                       **env_kwargs: Any) -> JsonDict:
    """
    An issued CIF certificate with a claim whose evidence log already carries
    the survey report, the bill of lading and the carrier claim letter, so the
    claim is ready to be adjusted.
    """
    env = build_environment_with_issued_certificate(api, **env_kwargs)
    overrides = dict(claim_overrides or {})
    overrides.setdefault("damage_percentage", 12.5)
    env["claim"] = F.open_claim_file(api, env["certificate_id"], **overrides)
    env["claim_id"] = env["claim"]["id"]
    env["documents"] = F.complete_claim_documents(api, env["claim_id"])
    return env


def build_adjusted_claim(api: ApiClient, **kwargs: Any) -> JsonDict:
    """The same claim, taken through adjustment to 141875.00."""
    env = build_claim_with_complete_evidence(api, **kwargs)
    env["claim"] = F.adjust_claim_file(api, env["claim_id"])
    return env


def build_surveyor_environment(api: ApiClient, **env_kwargs: Any) -> JsonDict:
    """
    An issued certificate, an open claim on it, and an active panel surveyor
    based at the discharge port certified for the shipment's susceptibility.
    """
    env = build_environment_with_issued_certificate(api, **env_kwargs)
    env["surveyor"] = F.create_surveyor(api, env["discharge_port_id"])
    env["surveyor_id"] = env["surveyor"]["id"]
    env["claim"] = F.open_claim_file(api, env["certificate_id"],
                                     damage_percentage=12.5)
    env["claim_id"] = env["claim"]["id"]
    return env


def build_open_declaration(api: ApiClient,
                           period_start: str = "2026-08-01T00:00:00Z",
                           period_end: str = "2026-09-01T00:00:00Z",
                           **env_kwargs: Any) -> JsonDict:
    """
    An issued certificate of 6444.91 premium and an open premium declaration
    covering the month it was issued in.
    """
    env = build_environment_with_issued_certificate(api, **env_kwargs)
    env["declaration"] = F.create_declaration(api, env["policy_id"],
                                              period_start, period_end)
    env["declaration_id"] = env["declaration"]["id"]
    return env


def build_submitted_declaration(api: ApiClient,
                                declared_premium_total: float =
                                C.EXPECTED_TOTAL_PREMIUM,
                                **kwargs: Any) -> JsonDict:
    """The same declaration, reported at `declared_premium_total`."""
    env = build_open_declaration(api, **kwargs)
    env["declaration"] = F.submit_declaration(
        api, env["declaration_id"], env["policy_id"], declared_premium_total)
    return env


# ---------------------------------------------------------------------------
# Tier 5 — terminal and finalised states
# ---------------------------------------------------------------------------
def build_cancelled_certificate(api: ApiClient, **env_kwargs: Any) -> JsonDict:
    """An issued certificate cancelled before its cover attached."""
    env = build_environment_with_issued_certificate(api, **env_kwargs)
    env["certificate"] = get_success_data(api.cancel_certificate(
        env["certificate_id"], UNDERWRITER,
        {"cancellation_reason": "SHIPMENT_NOT_SHIPPED"}))
    return env


def build_suspended_policy(api: ApiClient, **env_kwargs: Any) -> JsonDict:
    """
    An open cover suspended by an audit that found a material under-declaration:
    5000.00 was reported against a computed 6444.91.
    """
    env = build_submitted_declaration(api, declared_premium_total=5000.00,
                                      **env_kwargs)
    env["declaration"] = F.audit_declaration(
        api, env["declaration_id"], "material under-declaration")
    env["policy"] = get_success_data(
        api.get_open_policy(env["policy_id"], UNDERWRITER))
    return env


def build_war_terminated_environment(api: ApiClient,
                                     **env_kwargs: Any) -> JsonDict:
    """
    An issued certificate whose discharge port has been listed, so war cover has
    fallen away on both the cover and the certificate.
    """
    env = build_environment_with_issued_certificate(api, **env_kwargs)
    env["port_listing"] = get_success_data(api.set_port_war_risk_tier(
        env["discharge_port_id"], {"war_risk_tier": "LISTED_AREA"},
        COMPLIANCE_OFFICER))
    env["certificate"] = get_success_data(
        api.get_certificate(env["certificate_id"], UNDERWRITER))
    return env


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def canonical_env(api: ApiClient) -> JsonDict:
    """Two green ports, a commodity class, a screened hull and an active cover."""
    return build_canonical_environment(api)


@pytest.fixture
def issued_certificate_env(api: ApiClient) -> JsonDict:
    """The canonical environment plus one issued CIF certificate."""
    return build_environment_with_issued_certificate(api)


@pytest.fixture
def two_contributor_env(api: ApiClient) -> JsonDict:
    """Two certificates issued on one hull for one sailing date."""
    return build_two_contributor_conveyance(api)


@pytest.fixture
def ga_called_env(api: ApiClient) -> JsonDict:
    """A general average with its security calls issued and unposted."""
    return build_ga_event_with_security_calls(api)


@pytest.fixture
def ga_secured_env(api: ApiClient) -> JsonDict:
    """A general average whose security is fully lodged."""
    return build_ga_security_complete(api)


@pytest.fixture
def claim_ready_env(api: ApiClient) -> JsonDict:
    """A claim whose evidence log is complete."""
    return build_claim_with_complete_evidence(api)


@pytest.fixture
def surveyor_env(api: ApiClient) -> JsonDict:
    """An open claim and an active panel surveyor at the discharge port."""
    return build_surveyor_environment(api)


@pytest.fixture
def open_declaration_env(api: ApiClient) -> JsonDict:
    """An issued certificate and an open premium declaration."""
    return build_open_declaration(api)
