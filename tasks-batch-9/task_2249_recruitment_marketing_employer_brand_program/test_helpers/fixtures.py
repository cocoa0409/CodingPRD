"""Setup builders.

Each test starts against an empty database, so every precondition is built here by
calling the same public endpoints the tests exercise.  The builders return the raw
response payloads so tests can read ids, tokens and versions straight out of them.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .test_users import (
    anonymous_headers,
    brand_lead_headers,
    community_manager_headers,
    compliance_reviewer_headers,
    media_buyer_headers,
    persona_researcher_headers,
    recruiting_ops_headers,
)


def _data(response) -> Dict[str, Any]:
    return get_success_data(response)


# ------------------------------------------------------------------ logical clock

def move_clock(client: ApiClient, current_utc: str) -> None:
    """Recruiting operations owns the logical clock."""
    response = client.set_clock(current_utc, recruiting_ops_headers())
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------- programs

def create_program(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = client.create_program(f.program_payload(**overrides), brand_lead_headers())
    assert response.status_code == 201, response.text
    return _data(response)


def read_program(client: ApiClient, program_id: str) -> Dict[str, Any]:
    response = client.get_program(program_id, media_buyer_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def program_version(client: ApiClient, program_id: str) -> int:
    return read_program(client, program_id)["version"]


# ------------------------------------------------------------------- job families

def create_job_family(client: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_job_family(
        f.job_family_payload(program_id, **overrides), brand_lead_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def list_job_families(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_job_families(brand_lead_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


def list_channels(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_channels(brand_lead_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


def read_job_family(client: ApiClient, family_id: str) -> Dict[str, Any]:
    response = client.get_job_family(family_id, brand_lead_headers())
    assert response.status_code == 200, response.text
    return _data(response)


# ----------------------------------------------------------------------- channels

def create_channel(client: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_channel(
        f.channel_payload(program_id, **overrides), brand_lead_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def read_channel(client: ApiClient, channel_id: str) -> Dict[str, Any]:
    response = client.get_channel(channel_id, brand_lead_headers())
    assert response.status_code == 200, response.text
    return _data(response)


# -------------------------------------------------------------- candidate personas

def create_persona(client: ApiClient, job_family_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_candidate_persona(
        f.persona_payload(job_family_id, **overrides), persona_researcher_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def add_signal(
    client: ApiClient, persona_id: str, channel_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = client.create_channel_preference_signal(
        f.signal_payload(persona_id, channel_id, **overrides), persona_researcher_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def submit_persona(client: ApiClient, persona_id: str) -> Dict[str, Any]:
    response = client.submit_candidate_persona(persona_id, persona_researcher_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def approve_persona(
    client: ApiClient, persona_id: str, review_note: str = "research is current"
) -> Dict[str, Any]:
    response = client.review_candidate_persona(
        persona_id, f.persona_review_payload("APPROVE", review_note), brand_lead_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def approved_persona(
    client: ApiClient,
    job_family_id: str,
    channel_id: str,
    signal_overrides: Optional[Dict[str, Any]] = None,
    **persona_overrides: Any,
) -> Dict[str, Any]:
    """Draft a persona, give it one confident signal, submit it and approve it."""
    persona = create_persona(client, job_family_id, **persona_overrides)
    add_signal(client, persona["id"], channel_id, **(signal_overrides or {}))
    submit_persona(client, persona["id"])
    return approve_persona(client, persona["id"])


def read_persona(client: ApiClient, persona_id: str) -> Dict[str, Any]:
    response = client.get_candidate_persona(persona_id, persona_researcher_headers())
    assert response.status_code == 200, response.text
    return _data(response)


# --------------------------------------------------------------------- job postings

def create_posting(client: ApiClient, job_family_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_job_posting(
        f.posting_payload(job_family_id, **overrides), brand_lead_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def optimize_posting(
    client: ApiClient, posting_id: str, expected_posting_version: int, **overrides: Any
) -> Dict[str, Any]:
    response = client.optimize_job_posting(
        posting_id,
        f.optimize_payload(expected_posting_version, **overrides),
        brand_lead_headers(),
    )
    assert response.status_code == 200, response.text
    return _data(response)


def clear_posting(
    client: ApiClient, posting_id: str, note: str = "clean", user_id: Optional[str] = None
) -> Dict[str, Any]:
    response = client.compliance_review_job_posting(
        posting_id, f.compliance_review_payload("CLEAR", note), compliance_reviewer_headers(user_id)
    )
    assert response.status_code == 200, response.text
    return _data(response)


def flag_posting(
    client: ApiClient, posting_id: str, note: str = "pay range is stale", user_id: Optional[str] = None
) -> Dict[str, Any]:
    response = client.compliance_review_job_posting(
        posting_id, f.compliance_review_payload("FLAG", note), compliance_reviewer_headers(user_id)
    )
    assert response.status_code == 200, response.text
    return _data(response)


def publish_posting(client: ApiClient, posting_id: str) -> Dict[str, Any]:
    response = client.publish_job_posting(posting_id, brand_lead_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def list_postings(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_job_postings(brand_lead_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


def read_posting(client: ApiClient, posting_id: str) -> Dict[str, Any]:
    response = client.get_job_posting(posting_id, brand_lead_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def published_posting(
    client: ApiClient, job_family_id: str, channel_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A posting carried all the way to PUBLISHED: optimized, cleared, backed by a persona."""
    approved_persona(client, job_family_id, channel_id)
    posting = create_posting(client, job_family_id, **overrides)
    optimize_posting(client, posting["id"], posting["version"])
    clear_posting(client, posting["id"])
    return publish_posting(client, posting["id"])


# -------------------------------------------------------------------- media flights

def reserve_flight(
    client: ApiClient,
    channel_id: str,
    job_family_id: str,
    job_posting_id: str,
    expected_program_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    response = client.create_media_flight(
        f.flight_payload(
            channel_id, job_family_id, job_posting_id, expected_program_version, **overrides
        ),
        media_buyer_headers(),
    )
    assert response.status_code == 201, response.text
    return _data(response)


def activate_flight(client: ApiClient, flight_id: str) -> Dict[str, Any]:
    response = client.activate_media_flight(flight_id, media_buyer_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def record_spend(
    client: ApiClient, flight_id: str, amount_cents: int, spent_on: str = "2026-08-01"
) -> Dict[str, Any]:
    response = client.spend_media_flight(
        flight_id, f.spend_payload(amount_cents, spent_on), media_buyer_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def cancel_flight(client: ApiClient, flight_id: str, reason: str = "cancelled") -> Dict[str, Any]:
    response = client.cancel_media_flight(
        flight_id, f.cancel_reason_payload(reason), media_buyer_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def read_flight(client: ApiClient, flight_id: str) -> Dict[str, Any]:
    response = client.get_media_flight(flight_id, media_buyer_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def list_flights(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_media_flights(media_buyer_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


# ----------------------------------------------------------- applications and touches

def start_application(
    client: ApiClient, job_posting_id: str, candidate_email: str = "a1@example.com"
) -> Dict[str, Any]:
    response = client.create_application(
        f.application_payload(job_posting_id, candidate_email), anonymous_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def add_touchpoint(
    client: ApiClient, application_id: str, channel_id: str, occurred_at: str, **overrides: Any
) -> Dict[str, Any]:
    response = client.create_touchpoint(
        f.touchpoint_payload(application_id, channel_id, occurred_at, **overrides),
        media_buyer_headers(),
    )
    assert response.status_code == 201, response.text
    return _data(response)


def submit_application(client: ApiClient, application_id: str) -> Dict[str, Any]:
    response = client.submit_application(application_id, anonymous_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def screen_application(client: ApiClient, application_id: str) -> Dict[str, Any]:
    response = client.screen_application(application_id, recruiting_ops_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def decide_application(
    client: ApiClient, application_id: str, outcome: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    response = client.decide_application(
        application_id, f.decide_payload(outcome, reason), recruiting_ops_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def read_application(client: ApiClient, application_id: str) -> Dict[str, Any]:
    response = client.get_application(application_id, recruiting_ops_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def read_touchpoint(client: ApiClient, touchpoint_id: str) -> Dict[str, Any]:
    response = client.get_touchpoint(touchpoint_id, recruiting_ops_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def list_touchpoints(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_touchpoints(recruiting_ops_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------- talent community members

def join_community(
    client: ApiClient, program_id: str, email: str = "m1@example.com", **overrides: Any
) -> Dict[str, Any]:
    response = client.create_talent_community_member(
        f.member_payload(program_id, email, **overrides), anonymous_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def confirm_member(client: ApiClient, member_id: str, consent_token: str) -> Dict[str, Any]:
    response = client.confirm_consent(
        member_id, f.confirm_consent_payload(consent_token), anonymous_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def change_consent(client: ApiClient, member_id: str, action: str) -> Dict[str, Any]:
    response = client.change_consent(
        member_id, f.consent_change_payload(action), community_manager_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def subscribed_member(
    client: ApiClient, program_id: str, email: str = "m1@example.com", **overrides: Any
) -> Dict[str, Any]:
    """A member who joined and then confirmed the double opt-in."""
    member = join_community(client, program_id, email, **overrides)
    confirmed = confirm_member(client, member["id"], member["consent_token"])
    confirmed["consent_token"] = member["consent_token"]
    return confirmed


def read_member(client: ApiClient, member_id: str) -> Dict[str, Any]:
    response = client.get_talent_community_member(member_id, community_manager_headers())
    assert response.status_code == 200, response.text
    return _data(response)


# ------------------------------------------------------------------ nurture campaigns

def create_campaign(client: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_nurture_campaign(
        f.campaign_payload(program_id, **overrides), community_manager_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def schedule_campaign(client: ApiClient, campaign_id: str, scheduled_for: str) -> Dict[str, Any]:
    response = client.schedule_nurture_campaign(
        campaign_id, f.schedule_payload(scheduled_for), community_manager_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def scheduled_campaign(
    client: ApiClient, program_id: str, scheduled_for: str = "2026-08-01T00:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    campaign = create_campaign(client, program_id, **overrides)
    return schedule_campaign(client, campaign["id"], scheduled_for)


def dispatch_campaign(client: ApiClient, campaign_id: str) -> Dict[str, Any]:
    response = client.dispatch_nurture_campaign(campaign_id, community_manager_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def read_campaign(client: ApiClient, campaign_id: str) -> Dict[str, Any]:
    response = client.get_nurture_campaign(campaign_id, community_manager_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def list_nurture_sends(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = client.list_nurture_sends(community_manager_headers(), params or None)
    assert response.status_code == 200, response.text
    return _data(response)


# -------------------------------------------------------------------- employer reviews

def ingest_review(client: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    response = client.create_employer_review(
        f.review_payload(program_id, **overrides), community_manager_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def triage_review(client: ApiClient, review_id: str, note: str = "first pass") -> Dict[str, Any]:
    response = client.triage_employer_review(
        review_id, community_manager_headers(), f.triage_payload(note)
    )
    assert response.status_code == 200, response.text
    return _data(response)


def draft_review_response(
    client: ApiClient, review_id: str, response_body: str = "Thank you for the feedback."
) -> Dict[str, Any]:
    response = client.draft_response(
        review_id, f.draft_response_payload(response_body), community_manager_headers()
    )
    assert response.status_code == 200, response.text
    return _data(response)


def submit_review_to_legal(client: ApiClient, review_id: str) -> Dict[str, Any]:
    response = client.submit_legal(review_id, community_manager_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def decide_legal_review(
    client: ApiClient, review_id: str, decision: str, note: str = "reviewed",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    response = client.legal_review(
        review_id, f.legal_review_payload(decision, note), compliance_reviewer_headers(user_id)
    )
    assert response.status_code == 200, response.text
    return _data(response)


def read_review(client: ApiClient, review_id: str) -> Dict[str, Any]:
    response = client.get_employer_review(review_id, community_manager_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def drive_brand_health_down(
    client: ApiClient, program_id: str, review_count: int, posted_at: str = "2026-07-31T00:00:00Z"
) -> None:
    """Ingest ``review_count`` one-star reviews, each costing five points of brand health."""
    for index in range(1, review_count + 1):
        ingest_review(
            client,
            program_id,
            external_ref="gd-%02d" % index,
            rating=1,
            posted_at=posted_at,
        )


# --------------------------------------------------------------------- event presences

def plan_presence(
    client: ApiClient, program_id: str, job_family_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = client.create_event_presence(
        f.presence_payload(program_id, job_family_id, **overrides), media_buyer_headers()
    )
    assert response.status_code == 201, response.text
    return _data(response)


def confirm_presence(client: ApiClient, presence_id: str) -> Dict[str, Any]:
    response = client.confirm_event_presence(presence_id, None, media_buyer_headers())
    assert response.status_code == 200, response.text
    return _data(response)


def confirmed_presence(
    client: ApiClient, program_id: str, job_family_id: str, **overrides: Any
) -> Dict[str, Any]:
    presence = plan_presence(client, program_id, job_family_id, **overrides)
    return confirm_presence(client, presence["id"])


def read_presence(client: ApiClient, presence_id: str) -> Dict[str, Any]:
    response = client.get_event_presence(presence_id, media_buyer_headers())
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------------------- budget ledger

def list_ledger_entries(client: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    """Ledger rows, ordered by sequence number as the API returns them."""
    merged = dict(params)
    merged.setdefault("limit", 100)
    response = client.list_budget_ledger_entries(media_buyer_headers(), merged)
    assert response.status_code == 200, response.text
    return _data(response)


def ledger_entries_for_source(client: ApiClient, source_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_ledger_entries(client, source_id=source_id, **params)
