"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints and
uses the lenient validator, so a broken precondition surfaces as "Setup step failed".
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_business_payload,
    create_campaign_payload,
    create_listing_payload,
    create_location_payload,
    create_review_response_payload,
    email_contact_payload,
    ingest_review_payload,
    sms_contact_payload,
)
from .test_users import (
    TEST_USERS,
    anonymous_headers,
    make_compliance_officer_headers,
    make_response_agent_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT_1 = make_response_agent_headers("agent-1")
CO_1 = make_compliance_officer_headers("co-1")


# --------------------------------------------------------------------------
# Tier 0: thin single-call wrappers (all use the lenient setup validator)
# --------------------------------------------------------------------------
def set_clock(iso8601: str, headers=ADMIN) -> dict:
    """Move the server's logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, headers))


def create_business(headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_business(create_business_payload(**overrides), headers)
    )


def create_location(business_id: str, headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(business_id, create_location_payload(**overrides), headers)
    )


def create_listing(location_id: str, site: str = "GOOGLE", headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_listing(location_id, create_listing_payload(site, **overrides), headers)
    )


def sync_listing(listing_id: str, outcome: str = "SUCCESS", headers=ADMIN) -> dict:
    return get_success_data(api_client.sync_listing(listing_id, {"outcome": outcome}, headers))


def read_location(location_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_location(location_id, headers))


def read_campaign(campaign_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, headers))


def read_review(review_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_review(review_id, headers))


def read_review_response(response_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_review_response(response_id, headers))


def read_review_request(request_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_review_request(request_id, headers))


def read_listing(location_id: str, site: str, headers=ADMIN) -> dict:
    """Re-read one listing of a location by site (there is at most one per site)."""
    rows = get_success_data(api_client.list_listings(location_id, headers, {"limit": 100}))
    matches = [row for row in rows if row["site"] == site]
    assert matches, f"Setup step failed: no {site} listing on location {location_id}"
    return matches[0]


def read_widget(location_id: str, headers=ADMIN) -> dict:
    rows = get_success_data(api_client.get_widget(location_id, headers))
    assert rows, f"Setup step failed: location {location_id} has no widget"
    return rows[0]


def read_dashboard(location_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_dashboard(location_id, headers))


def read_escalations(review_id: str, headers=ADMIN) -> list:
    return get_success_data(api_client.list_review_escalations(review_id, headers))


def read_open_escalation(review_id: str, headers=ADMIN) -> dict:
    rows = read_escalations(review_id, headers)
    open_rows = [row for row in rows if row["state"] == "OPEN"]
    assert open_rows, f"Setup step failed: review {review_id} has no OPEN escalation"
    return open_rows[0]


def read_alerts(location_id: str, alert_type: str = None, headers=ADMIN) -> list:
    params = {"limit": 100}
    if alert_type:
        params["alert_type"] = alert_type
    return get_success_data(api_client.list_alerts(location_id, headers, params))


def count_alerts(location_id: str, alert_type: str, headers=ADMIN) -> int:
    return len([a for a in read_alerts(location_id, alert_type, headers)
                if a["alert_type"] == alert_type])


def ingest_review(location_id: str, headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.ingest_review(location_id, ingest_review_payload(**overrides), headers)
    )


def verify_review(review_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.verify_review(review_id, headers))


def flag_review(review_id: str, reason: str = "Suspected fake", headers=ADMIN) -> dict:
    return get_success_data(api_client.flag_review(review_id, {"reason": reason}, headers))


def create_email_contact(business_id: str, full_name: str, email: str, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_contact(business_id, email_contact_payload(full_name, email), headers)
    )


def create_sms_contact(business_id: str, full_name: str, phone: str, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_contact(business_id, sms_contact_payload(full_name, phone), headers)
    )


def create_template(business_id: str, payload: dict, headers=ADMIN) -> dict:
    return get_success_data(api_client.create_template(business_id, payload, headers))


def create_widget(location_id: str, headers=ADMIN, **overrides) -> dict:
    return get_success_data(api_client.create_widget(location_id, dict(overrides), headers))


def publish_widget(widget_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.publish_widget(widget_id, headers))


def create_survey(location_id: str, contact_id: str, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_survey(location_id, {"contact_id": contact_id}, headers)
    )


def submit_survey(survey_id: str, nps_score: int, comment: str = None) -> dict:
    payload = {"nps_score": nps_score}
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(api_client.submit_survey(survey_id, payload, anonymous_headers()))


def set_compliance_hold(location_id: str, on_hold: bool, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.set_compliance_hold(location_id, {"on_hold": on_hold}, headers)
    )


# --------------------------------------------------------------------------
# Tier 1: locations at a known listing_health_score
# --------------------------------------------------------------------------
def setup_location_with_connected_listings(sites=("GOOGLE", "YELP", "FACEBOOK"), **biz_overrides):
    """Business + Location + one NAP-matched CONNECTED listing per named site.

    With all three sites CONNECTED and freshly synced on the startup clock instant,
    listing_health_score is 100.00 and the location's posture is OPEN.

    Returns dict(business, location, listings={site: listing}).
    """
    business = create_business(**biz_overrides)
    location = create_location(business["id"])
    listings = {}
    for site in sites:
        listing = create_listing(location["id"], site)
        listings[site] = sync_listing(listing["id"], "SUCCESS")
    return {
        "business": business,
        "location": read_location(location["id"]),
        "listings": listings,
    }


def setup_location_with_google_only(**biz_overrides):
    """Business + Location + a single CONNECTED, NAP-matched GOOGLE listing.

    Google carries a weight of 0.5, so listing_health_score is 50.00 and posture is OPEN.
    """
    return setup_location_with_connected_listings(sites=("GOOGLE",), **biz_overrides)


def setup_bare_location(**biz_overrides):
    """Business + Location with no listings at all (listing_health_score 0.00)."""
    business = create_business(**biz_overrides)
    location = create_location(business["id"])
    return {"business": business, "location": location}


# --------------------------------------------------------------------------
# Tier 2: campaigns
# --------------------------------------------------------------------------
def create_campaign(location_id: str, headers=ADMIN, **overrides) -> dict:
    """Create a campaign, threading the location's current version into the OCC token."""
    location = read_location(location_id, headers)
    payload = create_campaign_payload(location["version"], **overrides)
    return get_success_data(api_client.create_campaign(location_id, payload, headers))


def schedule_campaign(campaign_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.schedule_campaign(campaign_id, headers))


def activate_campaign(campaign_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.activate_campaign(campaign_id, headers))


def create_running_campaign(location_id: str, headers=ADMIN, **overrides) -> dict:
    """DRAFT -> SCHEDULED -> RUNNING. Returns the RUNNING campaign."""
    campaign = create_campaign(location_id, headers, **overrides)
    schedule_campaign(campaign["id"], headers)
    return activate_campaign(campaign["id"], headers)


def enqueue_request(campaign_id: str, contact_id: str, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.create_review_request(campaign_id, {"contact_id": contact_id}, headers)
    )


def send_batch(campaign_id: str, batch_size: int, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.send_batch(campaign_id, {"batch_size": batch_size}, headers)
    )


def setup_running_email_campaign(num_contacts: int = 1, sites=("GOOGLE", "YELP", "FACEBOOK"),
                                 business_overrides=None, **campaign_overrides):
    """Full marketing preamble.

    Business + Location + CONNECTED listings + N email-consenting contacts +
    an EMAIL campaign walked DRAFT -> SCHEDULED -> RUNNING.

    Returns dict(business, location, listings, contacts, campaign).
    """
    env = setup_location_with_connected_listings(sites=sites, **(business_overrides or {}))
    contacts = [
        create_email_contact(env["business"]["id"], f"E {i}", f"e{i}@example.com")
        for i in range(1, num_contacts + 1)
    ]
    campaign = create_running_campaign(env["location"]["id"], **campaign_overrides)
    env["contacts"] = contacts
    env["campaign"] = campaign
    return env


def setup_running_sms_campaign(num_contacts: int = 3, **campaign_overrides):
    """Same shape as setup_running_email_campaign but on the SMS channel."""
    env = setup_location_with_connected_listings()
    contacts = [
        create_sms_contact(env["business"]["id"], f"S {i}", f"+1555111000{i}")
        for i in range(1, num_contacts + 1)
    ]
    overrides = {"name": "SMS Asks", "channel": "SMS"}
    overrides.update(campaign_overrides)
    campaign = create_running_campaign(env["location"]["id"], **overrides)
    env["contacts"] = contacts
    env["campaign"] = campaign
    return env


def setup_campaign_with_queued_requests(num_requests: int = 2, sites=("GOOGLE", "YELP", "FACEBOOK"),
                                        **campaign_overrides):
    """RUNNING EMAIL campaign holding `num_requests` QUEUED requests (one per contact)."""
    env = setup_running_email_campaign(
        num_contacts=num_requests, sites=sites, **campaign_overrides
    )
    env["requests"] = [
        enqueue_request(env["campaign"]["id"], contact["id"]) for contact in env["contacts"]
    ]
    return env


# --------------------------------------------------------------------------
# Tier 3: the reply workflow
# --------------------------------------------------------------------------
def draft_response(review_id: str, body: str = "Thank you!", template_id: str = None,
                   headers=AGENT_1) -> dict:
    """Draft a reply, threading the review's current version into the OCC token."""
    review = read_review(review_id)
    payload = create_review_response_payload(review["version"], body=body)
    if template_id is not None:
        payload["template_id"] = template_id
    return get_success_data(api_client.create_review_response(review_id, payload, headers))


def submit_response(response_id: str, headers=AGENT_1) -> dict:
    return get_success_data(api_client.submit_review_response(response_id, headers))


def approve_response(response_id: str, headers=CO_1) -> dict:
    return get_success_data(api_client.approve_review_response(response_id, headers))


def reject_response(response_id: str, reason: str = "Tone too casual", headers=CO_1) -> dict:
    return get_success_data(
        api_client.reject_review_response(response_id, {"rejection_reason": reason}, headers)
    )


def revise_response(response_id: str, body: str, headers=AGENT_1) -> dict:
    return get_success_data(
        api_client.revise_review_response(response_id, {"body": body}, headers)
    )


def publish_response(response_id: str, headers=CO_1) -> dict:
    return get_success_data(api_client.publish_review_response(response_id, headers))


def setup_pending_approval_response(review_id: str, drafter_headers=AGENT_1,
                                    body: str = "Thank you!") -> dict:
    """Draft + submit, leaving the response in PENDING_APPROVAL."""
    response = draft_response(review_id, body=body, headers=drafter_headers)
    submit_response(response["id"], drafter_headers)
    return read_review_response(response["id"])


def setup_approved_response(review_id: str, drafter_headers=AGENT_1,
                            approver_headers=CO_1, body: str = "Thank you!") -> dict:
    """Draft + submit + approve, leaving the response in APPROVED."""
    response = setup_pending_approval_response(review_id, drafter_headers, body=body)
    approve_response(response["id"], approver_headers)
    return read_review_response(response["id"])


def setup_review_with_approved_response(rating: int = 5, site: str = "GOOGLE",
                                        sites=("GOOGLE", "YELP", "FACEBOOK")):
    """CONNECTED listings + one ingested review + an APPROVED reply awaiting publication.

    Returns dict(business, location, listings, review, response).
    """
    env = setup_location_with_connected_listings(sites=sites)
    review = ingest_review(
        env["location"]["id"], site=site, external_review_id=f"{site[0].lower()}-r1", rating=rating
    )
    env["review"] = review
    env["response"] = setup_approved_response(review["id"])
    return env
