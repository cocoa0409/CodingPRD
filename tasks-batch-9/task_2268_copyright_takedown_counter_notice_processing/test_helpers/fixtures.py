"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server, so no state survives
between tests). The lenient get_success_data is used internally so setup
failures surface as clear errors rather than opaque KeyErrors.

Entity-backed roles are always threaded through their own identity
(PRD §2.1): RightsHolderRep calls carry the acting rights holder's id and
Subscriber calls carry the acting account's id.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_account_payload,
    create_content_item_payload,
    create_counter_notice_payload,
    create_designated_agent_payload,
    create_ingestion_batch_payload,
    create_misrepresentation_case_payload,
    create_notice_payload,
    create_policy_payload,
    create_provider_payload,
    create_reference_file_payload,
    create_rights_holder_payload,
)
from .test_users import (
    TEST_USERS,
    make_abuse_investigator_headers,
    make_compliance_officer_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_2 = TEST_USERS["second_compliance_officer_headers"]
AGENT = TEST_USERS["takedown_agent_headers"]
INVESTIGATOR = TEST_USERS["abuse_investigator_headers"]
INVESTIGATOR_2 = TEST_USERS["second_abuse_investigator_headers"]


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(instant: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with a Z suffix."""
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_iso(base_iso: str, **delta) -> str:
    """Return base_iso shifted by the given timedelta keyword arguments."""
    return iso(parse_instant(base_iso) + timedelta(**delta))


def set_clock(current_utc: str, headers: Optional[Dict] = None) -> str:
    data = get_success_data(api_client.set_clock(current_utc, headers or OFFICER))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Provider documentation chain
# ---------------------------------------------------------------------------

def create_provider(headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides),
                                   headers or OFFICER)
    )


def get_provider(provider_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.get_provider(provider_id, headers or OFFICER))


def publish_contact(provider_id: str, headers: Optional[Dict] = None,
                    public_contact_url: Optional[str] = None) -> dict:
    url = public_contact_url or "https://northstar.example/legal/dmca-agent"
    return get_success_data(
        api_client.publish_provider_contact(provider_id, url, headers or OFFICER)
    )


def create_draft_agent(provider_id: str, headers: Optional[Dict] = None,
                       **overrides) -> dict:
    return get_success_data(
        api_client.create_designated_agent(
            create_designated_agent_payload(provider_id, **overrides),
            headers or OFFICER,
        )
    )


def create_submitted_agent(provider_id: str, headers: Optional[Dict] = None,
                           **overrides) -> dict:
    agent = create_draft_agent(provider_id, headers, **overrides)
    return get_success_data(
        api_client.submit_designated_agent(agent["id"], headers or OFFICER)
    )


def register_agent(agent_id: str, provider_id: str, headers: Optional[Dict] = None,
                   copyright_office_receipt: Optional[str] = None) -> dict:
    """Register a SUBMITTED agent, reading the provider's current version first."""
    hdrs = headers or OFFICER
    provider = get_provider(provider_id, hdrs)
    payload = {"expected_provider_version": provider["version"]}
    if copyright_office_receipt is not None:
        payload["copyright_office_receipt"] = copyright_office_receipt
    return get_success_data(
        api_client.register_designated_agent(agent_id, payload, hdrs)
    )


def create_registered_agent(provider_id: str, headers: Optional[Dict] = None,
                            copyright_office_receipt: Optional[str] = None,
                            **overrides) -> dict:
    agent = create_submitted_agent(provider_id, headers, **overrides)
    return register_agent(agent["id"], provider_id, headers, copyright_office_receipt)


def create_draft_policy(provider_id: str, headers: Optional[Dict] = None,
                        **overrides) -> dict:
    return get_success_data(
        api_client.create_policy(create_policy_payload(provider_id, **overrides),
                                 headers or OFFICER)
    )


def publish_policy(policy_id: str, provider_id: str,
                   headers: Optional[Dict] = None) -> dict:
    hdrs = headers or OFFICER
    provider = get_provider(provider_id, hdrs)
    return get_success_data(
        api_client.publish_policy(policy_id, provider["version"], hdrs)
    )


def create_published_policy(provider_id: str, headers: Optional[Dict] = None,
                            **overrides) -> dict:
    policy = create_draft_policy(provider_id, headers, **overrides)
    return publish_policy(policy["id"], provider_id, headers)


def setup_documented_provider(clock: Optional[str] = CLOCK_START_ISO,
                              **policy_overrides) -> dict:
    """Provider with published public contact, one REGISTERED designated agent
    and one PUBLISHED repeat-infringer policy.

    Returns {"provider": ..., "agent": ..., "policy": ...} where provider is
    re-read after the last mutation so its version is current.
    """
    if clock is not None:
        set_clock(clock)
    provider = create_provider()
    publish_contact(provider["id"])
    agent = create_registered_agent(provider["id"])
    policy = create_published_policy(provider["id"], **policy_overrides)
    return {
        "provider": get_provider(provider["id"]),
        "agent": agent,
        "policy": policy,
    }


def setup_provider_with_agent(clock: Optional[str] = CLOCK_START_ISO) -> dict:
    """Provider with published public contact and one REGISTERED designated
    agent, but no published repeat-infringer policy."""
    if clock is not None:
        set_clock(clock)
    provider = create_provider()
    publish_contact(provider["id"])
    agent = create_registered_agent(provider["id"])
    return {"provider": get_provider(provider["id"]), "agent": agent}


# ---------------------------------------------------------------------------
# Accounts and content
# ---------------------------------------------------------------------------

def create_account(provider_id: str, headers: Optional[Dict] = None,
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_account(create_account_payload(provider_id, **overrides),
                                  headers or OFFICER)
    )


def get_account(account_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or OFFICER))


def create_content_item(account_id: str, **overrides) -> dict:
    """Subscriber-owned upload: the acting identity is the account itself."""
    return get_success_data(
        api_client.create_content_item(
            create_content_item_payload(account_id, **overrides),
            make_subscriber_headers(account_id),
        )
    )


def get_content_item(item_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_content_item(item_id, headers or OFFICER)
    )


def list_account_content_items(account_id: str, headers: Optional[Dict] = None,
                               params: Optional[Dict] = None):
    data, meta = validate_paginated(
        api_client.list_account_content_items(account_id, headers or OFFICER, params)
    )
    return data, meta


def setup_account_with_items(provider_id: str, count: int = 1,
                             **account_overrides) -> dict:
    """One account plus `count` AVAILABLE content items owned by it."""
    account = create_account(provider_id, **account_overrides)
    items = [create_content_item(account["id"]) for _ in range(count)]
    return {"account": get_account(account["id"]), "items": items}


# ---------------------------------------------------------------------------
# Rights holders, reference files and ingestion
# ---------------------------------------------------------------------------

def create_rights_holder(headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_rights_holder(create_rights_holder_payload(**overrides),
                                        headers or OFFICER)
    )


def get_rights_holder(rights_holder_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_rights_holder(rights_holder_id, headers or OFFICER)
    )


def enroll_rights_holder(rights_holder_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.enroll_rights_holder(rights_holder_id, headers or OFFICER)
    )


def promote_tier(rights_holder_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.promote_rights_holder_tier(rights_holder_id, headers or OFFICER)
    )


def create_enrolled_rights_holder(tier: str = "STANDARD", **overrides) -> dict:
    """ENROLLED rights holder promoted up to the requested program tier."""
    holder = create_rights_holder(**overrides)
    holder = enroll_rights_holder(holder["id"])
    if tier == "VERIFIED":
        holder = promote_tier(holder["id"])
    elif tier == "TRUSTED":
        promote_tier(holder["id"])
        holder = promote_tier(holder["id"])
    return holder


def create_reference_file(rights_holder_id: str, headers: Optional[Dict] = None,
                         **overrides) -> dict:
    return get_success_data(
        api_client.create_reference_file(
            create_reference_file_payload(rights_holder_id, **overrides),
            headers or make_rights_holder_rep_headers(rights_holder_id),
        )
    )


def activate_reference_file(reference_file_id: str, rights_holder_id: str,
                            headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.activate_reference_file(
            reference_file_id,
            headers or make_rights_holder_rep_headers(rights_holder_id),
        )
    )


def create_active_reference_file(rights_holder_id: str, **overrides) -> dict:
    ref = create_reference_file(rights_holder_id, **overrides)
    return activate_reference_file(ref["id"], rights_holder_id)


def create_ingestion_batch(rights_holder_id: str, item_count: int,
                           headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.create_ingestion_batch(
            create_ingestion_batch_payload(rights_holder_id, item_count),
            headers or make_rights_holder_rep_headers(rights_holder_id),
        )
    )


# ---------------------------------------------------------------------------
# Notices and claims
# ---------------------------------------------------------------------------

def create_notice(rights_holder_id: str, claimed_urls: List[str],
                  headers: Optional[Dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_notice(
            create_notice_payload(rights_holder_id, claimed_urls, **overrides),
            headers or AGENT,
        )
    )


def get_notice(notice_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.get_notice(notice_id, headers or AGENT))


def validate_notice(notice_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.validate_notice(notice_id, headers or AGENT))


def process_notice(notice_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.process_notice(notice_id, headers or AGENT))


def create_validated_notice(rights_holder_id: str, claimed_urls: List[str],
                            **overrides) -> dict:
    notice = create_notice(rights_holder_id, claimed_urls, **overrides)
    return validate_notice(notice["id"])


def create_processed_notice(rights_holder_id: str, claimed_urls: List[str],
                            **overrides) -> dict:
    notice = create_validated_notice(rights_holder_id, claimed_urls, **overrides)
    return process_notice(notice["id"])


def list_claims(headers: Optional[Dict] = None, params: Optional[Dict] = None):
    data, meta = validate_paginated(
        api_client.list_claims(headers or AGENT, params)
    )
    return data, meta


def claims_of_notice(notice_id: str, headers: Optional[Dict] = None) -> List[dict]:
    data, _ = list_claims(headers, {"notice_id": notice_id})
    return data


def get_claim(claim_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or AGENT))


def uphold_claim(claim_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.uphold_claim(claim_id, headers or AGENT))


def restore_claim(claim_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.restore_claim(claim_id, headers or AGENT))


# ---------------------------------------------------------------------------
# Counter-notices
# ---------------------------------------------------------------------------

def create_counter_notice(claim_id: str, account_id: str,
                          expected_claim_version: Optional[int] = None,
                          headers: Optional[Dict] = None, **overrides) -> dict:
    """Subscriber-owned counter-notice; the claim version is read when omitted."""
    if expected_claim_version is None:
        expected_claim_version = get_claim(claim_id)["version"]
    return get_success_data(
        api_client.create_counter_notice(
            create_counter_notice_payload(claim_id, expected_claim_version, **overrides),
            headers or make_subscriber_headers(account_id),
        )
    )


def get_counter_notice(counter_notice_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_counter_notice(counter_notice_id, headers or AGENT)
    )


def validate_counter_notice(counter_notice_id: str,
                            headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.validate_counter_notice(counter_notice_id, headers or AGENT)
    )


def forward_counter_notice(counter_notice_id: str,
                           headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.forward_counter_notice(counter_notice_id, headers or AGENT)
    )


def create_forwarded_counter_notice(claim_id: str, account_id: str,
                                    **overrides) -> dict:
    counter = create_counter_notice(claim_id, account_id, **overrides)
    validate_counter_notice(counter["id"])
    return forward_counter_notice(counter["id"])


def record_suit_notice(counter_notice_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.record_suit_notice(counter_notice_id, headers or AGENT)
    )


# ---------------------------------------------------------------------------
# Strikes, terminations and misrepresentation cases
# ---------------------------------------------------------------------------

def list_account_strikes(account_id: str, headers: Optional[Dict] = None,
                         params: Optional[Dict] = None):
    data, meta = validate_paginated(
        api_client.list_account_strikes(account_id, headers or OFFICER, params)
    )
    return data, meta


def strike_summary(account_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_account_strike_summary(account_id, headers or OFFICER)
    )


def list_account_termination_cases(account_id: str, headers: Optional[Dict] = None,
                                   params: Optional[Dict] = None):
    data, meta = validate_paginated(
        api_client.list_account_termination_cases(account_id, headers or OFFICER, params)
    )
    return data, meta


def termination_cases_of_account(account_id: str,
                                 headers: Optional[Dict] = None) -> List[dict]:
    data, _ = list_account_termination_cases(account_id, headers)
    return data


def get_termination_case(case_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_termination_case(case_id, headers or OFFICER)
    )


def execute_termination_case(case_id: str, officer_user_id: str = "officer-01") -> dict:
    return get_success_data(
        api_client.execute_termination_case(
            case_id, make_compliance_officer_headers(officer_user_id)
        )
    )


def file_termination_appeal(case_id: str, account_id: str) -> dict:
    return get_success_data(
        api_client.file_termination_appeal(case_id, make_subscriber_headers(account_id))
    )


def decide_termination_appeal(case_id: str, decision: str,
                              officer_user_id: str = "officer-02") -> dict:
    return get_success_data(
        api_client.decide_termination_appeal(
            case_id, decision, make_compliance_officer_headers(officer_user_id)
        )
    )


def create_misrepresentation_case(rights_holder_id: str, claim_id: str,
                                  investigator_user_id: str = "investigator-01",
                                  **overrides) -> dict:
    return get_success_data(
        api_client.create_misrepresentation_case(
            create_misrepresentation_case_payload(rights_holder_id, claim_id,
                                                  **overrides),
            make_abuse_investigator_headers(investigator_user_id),
        )
    )


def substantiate_misrepresentation_case(case_id: str,
                                        investigator_user_id: str = "investigator-02"
                                        ) -> dict:
    return get_success_data(
        api_client.substantiate_misrepresentation_case(
            case_id, make_abuse_investigator_headers(investigator_user_id)
        )
    )


def dismiss_misrepresentation_case(case_id: str,
                                   investigator_user_id: str = "investigator-02") -> dict:
    return get_success_data(
        api_client.dismiss_misrepresentation_case(
            case_id, make_abuse_investigator_headers(investigator_user_id)
        )
    )


def get_misrepresentation_case(case_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.get_misrepresentation_case(case_id, headers or INVESTIGATOR)
    )


# ---------------------------------------------------------------------------
# Safe-harbour audits
# ---------------------------------------------------------------------------

def create_safe_harbor_audit(provider_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.create_safe_harbor_audit(provider_id, headers or OFFICER)
    )


def list_provider_audits(provider_id: str, headers: Optional[Dict] = None,
                         params: Optional[Dict] = None):
    data, meta = validate_paginated(
        api_client.list_provider_safe_harbor_audits(provider_id, headers or OFFICER,
                                                   params)
    )
    return data, meta


# ---------------------------------------------------------------------------
# End-to-end scene builders
# ---------------------------------------------------------------------------

def setup_disabled_claim(clock: str = CLOCK_START_ISO, tier: str = "STANDARD",
                         **policy_overrides) -> dict:
    """One PROCESSED notice against one AVAILABLE item, leaving a DISABLED
    claim, a DISABLED content item and one ACTIVE strike.

    Returns provider, policy, account, item, rights_holder, notice and claim.
    """
    setup = setup_documented_provider(clock, **policy_overrides)
    provider = setup["provider"]
    account = create_account(provider["id"])
    item = create_content_item(account["id"])
    holder = (create_enrolled_rights_holder(tier) if tier != "PROSPECT"
              else create_rights_holder())
    notice = create_processed_notice(holder["id"], [item["content_url"]])
    claims = claims_of_notice(notice["id"])
    return {
        "provider": get_provider(provider["id"]),
        "agent": setup["agent"],
        "policy": setup["policy"],
        "account": get_account(account["id"]),
        "item": get_content_item(item["id"]),
        "rights_holder": get_rights_holder(holder["id"]),
        "notice": get_notice(notice["id"]),
        "claim": claims[0] if claims else None,
        "claims": claims,
    }
