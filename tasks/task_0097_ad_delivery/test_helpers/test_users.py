"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

OPAQUE roles — X-User-ID is an opaque operator identifier not tied to
any persisted entity row. Shared constants are canonical for these:
  - PlatformAdmin
  - CreativeReviewer
  - ExchangeService
  - MeasurementPartner
  - AntiFraudService

ENTITY-BACKED roles — PRD §2.1: "When X-User-Role is AccountOwner,
CampaignManager, or FinanceOfficer, X-User-ID is interpreted as the
external_user_id of an AccountUser row belonging to the advertiser
scope of the request; ownership checks compare the resource's owning
advertiser_id to the advertiser referenced by that AccountUser."
Therefore every AccountOwner / CampaignManager / FinanceOfficer call
whose success depends on the AccountUser belonging to the right
advertiser scope MUST mint headers via the make_*_headers builders
with the AccountUser's external_user_id — never via the shared
fallback constants.

Additionally, PRD §2.1 segregation of duties: a CreativeReviewer's
X-User-ID MUST NOT equal any external_user_id of any AccountUser of the
creative's owning advertiser. Reviewers therefore need a stable opaque
id (distinct from any AccountUser external_user_id). And on appeal
decisions, the deciding reviewer's X-User-ID MUST NOT equal the
original rejection's reviewer_user_id, so a SECOND distinct reviewer id
is also required.

The shared CAMPAIGN_MANAGER_FALLBACK_ID / OWNER_FALLBACK_ID /
FINANCE_FALLBACK_ID constants below are ONLY safe for tests that DO NOT
exercise ownership (header-missing, role-mismatch, NotFound paths, or
calls where the role is provably non-permitted for that endpoint).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids — shared constants are PRD-correct because
# the server records but does not match these against any entity id.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "platform-admin-001"
PLATFORM_ADMIN_ID_ALT = "platform-admin-002"

CREATIVE_REVIEWER_ID = "reviewer-001"
CREATIVE_REVIEWER_ID_ALT = "reviewer-002"
CREATIVE_REVIEWER_ID_THIRD = "reviewer-003"

EXCHANGE_SERVICE_ID = "exchange-001"
EXCHANGE_SERVICE_ID_ALT = "exchange-002"

MEASUREMENT_PARTNER_ID = "mmp-001"
MEASUREMENT_PARTNER_ID_ALT = "mmp-002"

ANTI_FRAUD_SERVICE_ID = "antifraud-001"
ANTI_FRAUD_SERVICE_ID_ALT = "antifraud-002"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback ids — DO NOT USE for ownership-gated
# calls. Use the make_*_headers builders with the AccountUser's
# external_user_id instead.
# ---------------------------------------------------------------------------
OWNER_FALLBACK_ID = "owner-fallback-1"
CAMPAIGN_MANAGER_FALLBACK_ID = "campaign-manager-fallback-1"
FINANCE_FALLBACK_ID = "finance-fallback-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    "creative_reviewer_headers": build_user_headers(
        CREATIVE_REVIEWER_ID, "CreativeReviewer",
    ),
    "creative_reviewer_headers_alt": build_user_headers(
        CREATIVE_REVIEWER_ID_ALT, "CreativeReviewer",
    ),
    "creative_reviewer_headers_third": build_user_headers(
        CREATIVE_REVIEWER_ID_THIRD, "CreativeReviewer",
    ),
    "exchange_service_headers": build_user_headers(
        EXCHANGE_SERVICE_ID, "ExchangeService",
    ),
    "exchange_service_headers_alt": build_user_headers(
        EXCHANGE_SERVICE_ID_ALT, "ExchangeService",
    ),
    "measurement_partner_headers": build_user_headers(
        MEASUREMENT_PARTNER_ID, "MeasurementPartner",
    ),
    "measurement_partner_headers_alt": build_user_headers(
        MEASUREMENT_PARTNER_ID_ALT, "MeasurementPartner",
    ),
    "anti_fraud_service_headers": build_user_headers(
        ANTI_FRAUD_SERVICE_ID, "AntiFraudService",
    ),
    "anti_fraud_service_headers_alt": build_user_headers(
        ANTI_FRAUD_SERVICE_ID_ALT, "AntiFraudService",
    ),

    # Entity-backed fallbacks — ONLY for non-ownership-gated tests.
    "account_owner_headers": build_user_headers(
        OWNER_FALLBACK_ID, "AccountOwner",
    ),
    "campaign_manager_headers": build_user_headers(
        CAMPAIGN_MANAGER_FALLBACK_ID, "CampaignManager",
    ),
    "finance_officer_headers": build_user_headers(
        FINANCE_FALLBACK_ID, "FinanceOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles whenever the
# call is ownership-gated. The argument is the AccountUser's
# external_user_id (the same string that will be later looked up by the
# server when the role is AccountOwner / CampaignManager /
# FinanceOfficer per PRD §2.1).
# ---------------------------------------------------------------------------
def make_account_owner_headers(external_user_id: str) -> Dict[str, str]:
    """For AccountOwner (entity_backed:AccountUser). Pass the
    external_user_id of an AccountUser whose AccountUser.advertiser_id
    matches the advertiser scope of the request. Ownership-gated calls
    MUST use this builder; the OWNER_FALLBACK_ID constant is reserved
    for non-ownership tests.
    """
    return build_user_headers(external_user_id, "AccountOwner")


def make_campaign_manager_headers(external_user_id: str) -> Dict[str, str]:
    """For CampaignManager (entity_backed:AccountUser). Pass the
    external_user_id of an AccountUser belonging to the right advertiser.
    """
    return build_user_headers(external_user_id, "CampaignManager")


def make_finance_officer_headers(external_user_id: str) -> Dict[str, str]:
    """For FinanceOfficer (entity_backed:AccountUser). Pass the
    external_user_id of an AccountUser belonging to the right advertiser.
    """
    return build_user_headers(external_user_id, "FinanceOfficer")


def make_creative_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """For CreativeReviewer (opaque). The reviewer_id is an opaque
    string. Use a value that does NOT match any AccountUser
    external_user_id of the creative's owning advertiser (PRD §2.1
    segregation of duties). The base CREATIVE_REVIEWER_ID constants are
    safe because they never appear as advertiser-side AccountUser ids
    in fixture setups.
    """
    return build_user_headers(reviewer_id, "CreativeReviewer")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_exchange_service_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "ExchangeService")


def make_measurement_partner_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "MeasurementPartner")


def make_anti_fraud_service_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "AntiFraudService")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "CREATIVE_REVIEWER_ID",
    "CREATIVE_REVIEWER_ID_ALT",
    "CREATIVE_REVIEWER_ID_THIRD",
    "EXCHANGE_SERVICE_ID",
    "EXCHANGE_SERVICE_ID_ALT",
    "MEASUREMENT_PARTNER_ID",
    "MEASUREMENT_PARTNER_ID_ALT",
    "ANTI_FRAUD_SERVICE_ID",
    "ANTI_FRAUD_SERVICE_ID_ALT",
    "OWNER_FALLBACK_ID",
    "CAMPAIGN_MANAGER_FALLBACK_ID",
    "FINANCE_FALLBACK_ID",
    "TEST_USERS",
    "make_account_owner_headers",
    "make_campaign_manager_headers",
    "make_finance_officer_headers",
    "make_creative_reviewer_headers",
    "make_platform_admin_headers",
    "make_exchange_service_headers",
    "make_measurement_partner_headers",
    "make_anti_fraud_service_headers",
]
