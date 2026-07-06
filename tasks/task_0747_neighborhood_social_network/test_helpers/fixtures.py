"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server's database is reset before every individual test.
Fixtures use get_success_data() (lenient validator) internally so setup failures
surface clearly as "Setup failed" rather than as confusing assertion errors.

Identity threading: Resident, Moderator, and BusinessOwner roles are
entity_backed (PRD §2.1) — their X-User-ID MUST equal the id of a live entity
of the corresponding type. Every fixture that acts on behalf of a resident,
moderator, or business owner uses `make_resident_headers(...)`,
`make_moderator_headers(...)`, or `make_business_owner_headers(...)` with the
concrete entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_resident_headers,
    make_moderator_headers,
    make_business_owner_headers,
    make_agency_officer_headers,
    make_admin_headers,
)
from .constants import (
    TEST_BASE_CLOCK,
    DEFAULT_NEIGHBORHOOD_CENTER_LAT,
    DEFAULT_NEIGHBORHOOD_CENTER_LNG,
    DEFAULT_NEIGHBORHOOD_RADIUS_M,
    AGENCY_OFFICER_USER_ID,
)
from .factories import (
    create_neighborhood_payload,
    create_resident_payload,
    create_verification_request_payload,
    create_post_payload,
    create_marketplace_listing_payload,
    create_incident_payload,
    create_civic_notice_payload,
    create_flag_report_payload,
    create_moderation_decision_payload,
    create_business_payload,
    create_local_ad_payload,
    create_group_payload,
    create_event_payload,
    create_event_rsvp_payload,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


# --------------------------------------------------------------------------- clock helpers
def set_clock(iso8601: str = TEST_BASE_CLOCK) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


# --------------------------------------------------------------------------- Tier 1: base entities
def create_neighborhood(**overrides) -> dict:
    """Create a Neighborhood. Returns the neighborhood resource."""
    return get_success_data(
        api_client.create_neighborhood(create_neighborhood_payload(**overrides), ADMIN)
    )


def create_resident(neighborhood_id: str, **overrides) -> dict:
    """Register a Resident under a neighborhood. The initial POSTCARD_CODE
    VerificationRequest is auto-issued as a server side effect (PRD §3.1)."""
    return get_success_data(
        api_client.create_resident(create_resident_payload(neighborhood_id, **overrides), ADMIN)
    )


def fetch_pending_verification(resident_id: str) -> dict:
    """Locate the auto-issued VerificationRequest for a Resident. The initial
    request is auto-issued at POST /residents time (PRD §3.1); the listing
    endpoint filters by resident_id."""
    resp = api_client.list_verification_requests(ADMIN, params={"resident_id": resident_id})
    data = get_success_data(resp)
    # The response envelope may deliver rows as data.data or data itself.
    rows = data if isinstance(data, list) else data.get("data", data)
    # Some frameworks unwrap the array. Fall back to the raw data.
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    assert rows, f"Setup failed: no VerificationRequest found for resident {resident_id}"
    return rows[0]


# --------------------------------------------------------------------------- Tier 2: verified residents
def promote_to_moderator(resident_id: str) -> dict:
    """PlatformAdmin flips Resident.is_moderator=true (PRD §3.1)."""
    return get_success_data(api_client.promote_moderator(resident_id, ADMIN))


def approve_verification(vr_id: str, moderator_resident_id: str) -> dict:
    """Moderator claims + approves a SUBMITTED VerificationRequest so the
    Resident's verification_status flips to VERIFIED (PRD §3.1)."""
    mod_headers = make_moderator_headers(moderator_resident_id)
    get_success_data(api_client.claim_verification_request(vr_id, mod_headers))
    return get_success_data(api_client.approve_verification(vr_id, mod_headers))


def create_verified_resident(neighborhood_id: str, moderator_resident_id: str,
                             **overrides) -> dict:
    """Create a Resident and drive their auto-issued VerificationRequest to
    APPROVED via the supplied moderator. Returns the refreshed Resident."""
    resident = create_resident(neighborhood_id, **overrides)
    vr = fetch_pending_verification(resident["id"])
    approve_verification(vr["id"], moderator_resident_id)
    return get_success_data(api_client.get_resident(resident["id"], ADMIN))


def setup_neighborhood_with_moderator(neighborhood_overrides=None):
    """Create a Neighborhood + one Moderator (Resident with is_moderator=true
    and VERIFIED membership). Returns (neighborhood, moderator_resident)."""
    set_clock()
    n = create_neighborhood(**(neighborhood_overrides or {}))
    # The first resident becomes moderator; approve their auto-VR via themselves
    # first requires them to be a moderator, which requires them to be a live
    # Resident with is_moderator=true — so the moderator's own verification
    # request is left in SUBMITTED (the moderator role only needs is_moderator
    # to be true; verification_status is separate).
    mod = create_resident(n["id"], email="mod@x.com", display_name="Mod",
                          home_address_line="1 A St")
    promote_to_moderator(mod["id"])
    # Approve the moderator's own initial VerificationRequest so their
    # verification_status is VERIFIED and they have a VERIFIED membership.
    mod_vr = fetch_pending_verification(mod["id"])
    approve_verification(mod_vr["id"], mod["id"])
    mod = get_success_data(api_client.get_resident(mod["id"], ADMIN))
    return n, mod


def setup_neighborhood_with_verified_resident(neighborhood_overrides=None,
                                              resident_overrides=None):
    """Neighborhood + Moderator + one additional VERIFIED Resident.
    Returns (neighborhood, moderator, resident)."""
    n, mod = setup_neighborhood_with_moderator(neighborhood_overrides)
    r_overrides = {"email": "r1@x.com", "display_name": "R1",
                   "home_address_line": "2 A St"}
    r_overrides.update(resident_overrides or {})
    r = create_verified_resident(n["id"], mod["id"], **r_overrides)
    return n, mod, r


def setup_neighborhood_with_verified_residents(count: int,
                                               neighborhood_overrides=None):
    """Neighborhood + Moderator + `count` additional VERIFIED Residents.
    Returns (neighborhood, moderator, list_of_verified_residents)."""
    n, mod = setup_neighborhood_with_moderator(neighborhood_overrides)
    residents = []
    for i in range(count):
        r = create_verified_resident(
            n["id"], mod["id"],
            email=f"r{i+1}@x.com",
            display_name=f"R{i+1}",
            home_address_line=f"{i+2} A St",
        )
        residents.append(r)
    return n, mod, residents


# --------------------------------------------------------------------------- Post + moderation preambles
def create_post(author_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    """Create a Post authored by a verified resident."""
    return get_success_data(
        api_client.create_post(
            create_post_payload(author_resident_id, neighborhood_id, **overrides),
            make_resident_headers(author_resident_id),
        )
    )


def flag_post(reporter_resident_id: str, post_id: str, reason: str = "SPAM") -> dict:
    """File a FlagReport on a Post."""
    return get_success_data(
        api_client.create_flag_report(
            create_flag_report_payload(reporter_resident_id, "POST", post_id, reason=reason),
            make_resident_headers(reporter_resident_id),
        )
    )


def drive_post_to_flagged(post_id: str, reporter_ids: list):
    """File FLAG_HIDE_THRESHOLD=3 FlagReports from distinct reporters so the
    Post auto-transitions PUBLISHED->FLAGGED (PRD §3.2 / §3.7). Returns the
    first flag_report id and the refreshed Post."""
    assert len(reporter_ids) >= 3, "Need at least 3 reporters to reach FLAG_HIDE_THRESHOLD"
    first_fr_id = None
    for i, rid in enumerate(reporter_ids[:3]):
        fr = flag_post(rid, post_id)
        if i == 0:
            first_fr_id = fr["id"]
    post = get_success_data(api_client.get_post(post_id, ADMIN))
    return first_fr_id, post


def setup_flagged_post(reporter_count: int = 3):
    """Neighborhood + Moderator + author + N reporters + a Post driven to
    state=FLAGGED via 3 open flag reports.

    Returns dict: {n, mod, author, reporters, post, first_fr_id, post_version}.
    """
    n, mod, residents = setup_neighborhood_with_verified_residents(1 + reporter_count)
    author = residents[0]
    reporters = residents[1:1 + reporter_count]
    post = create_post(author["id"], n["id"], category="GENERAL",
                       title="P1", body="p1")
    first_fr_id, post = drive_post_to_flagged(post["id"],
                                              [r["id"] for r in reporters])
    return {
        "n": n,
        "mod": mod,
        "author": author,
        "reporters": reporters,
        "post": post,
        "first_fr_id": first_fr_id,
        "post_version": post["version"],
    }


def moderate_decision(moderator_resident_id: str, flag_report_id: str,
                      decision: str, expected_target_version: int,
                      rationale: str = "test rationale") -> dict:
    """Submit a ModerationDecision as the given moderator."""
    return get_success_data(
        api_client.create_moderation_decision(
            create_moderation_decision_payload(
                moderator_resident_id, flag_report_id, decision,
                expected_target_version, rationale=rationale,
            ),
            make_moderator_headers(moderator_resident_id),
        )
    )


def find_upheld_flag_report(post_id: str, moderator_resident_id: str) -> dict:
    """Locate the UPHELD flag report against a Post — used to file the REVERSE
    decision (PRD §3.7 says REVERSE addresses the previously-UPHELD flag)."""
    resp = api_client.list_flag_reports(
        make_moderator_headers(moderator_resident_id),
        params={"target_id": post_id, "status": "UPHELD"},
    )
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("data", data)
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    assert rows, f"Setup failed: no UPHELD flag report found for post {post_id}"
    return rows[0]


# --------------------------------------------------------------------------- Incidents (safety posture)
def report_critical_incident(reporter_resident_id: str, neighborhood_id: str,
                             occurred_at: str = "2026-06-01T00:00:00Z",
                             category: str = "PROPERTY_CRIME") -> dict:
    return get_success_data(
        api_client.create_incident(
            create_incident_payload(
                reporter_resident_id, neighborhood_id,
                severity="CRITICAL", category=category,
                occurred_at=occurred_at,
            ),
            make_resident_headers(reporter_resident_id),
        )
    )


def drive_neighborhood_to_emergency(neighborhood_id: str, reporter_resident_id: str,
                                    occurred_at: str = "2026-06-01T00:00:00Z"):
    """Create 3 CRITICAL Incidents under one reporter so the Neighborhood's
    safety_posture recomputes to EMERGENCY (PRD §3.4, threshold >= 3).
    Returns the three incident ids (as list)."""
    categories = ["PROPERTY_CRIME", "TRAFFIC_HAZARD", "ENVIRONMENTAL"]
    incidents = []
    for cat in categories:
        inc = report_critical_incident(reporter_resident_id, neighborhood_id,
                                       occurred_at=occurred_at, category=cat)
        incidents.append(inc)
    return incidents


def setup_neighborhood_in_emergency(reporter_count: int = 1):
    """Neighborhood + Moderator + reporter(s) + 3 CRITICAL open Incidents
    driving safety_posture=EMERGENCY. Returns dict with (n, mod, reporters,
    incidents, refreshed_n)."""
    n, mod, residents = setup_neighborhood_with_verified_residents(reporter_count)
    reporter = residents[0]
    incidents = drive_neighborhood_to_emergency(n["id"], reporter["id"])
    refreshed_n = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
    return {
        "n": refreshed_n,
        "mod": mod,
        "reporter": reporter,
        "reporters": residents,
        "incidents": incidents,
    }


# --------------------------------------------------------------------------- Businesses + LocalAds
def create_verified_business(owner_resident_id: str, neighborhood_id: str,
                             **overrides) -> dict:
    """Claim a Business and flip it to VERIFIED_BUSINESS (PRD §3.8)."""
    biz = get_success_data(
        api_client.create_business(
            create_business_payload(owner_resident_id, neighborhood_id, **overrides),
            make_resident_headers(owner_resident_id),
        )
    )
    return get_success_data(api_client.verify_business(biz["id"], ADMIN))


def setup_business_owner_scaffold(business_overrides=None):
    """Neighborhood + Moderator + Verified Resident + VERIFIED_BUSINESS owned
    by that resident. Returns (n, mod, resident, business)."""
    n, mod, r = setup_neighborhood_with_verified_resident()
    biz = create_verified_business(r["id"], n["id"], **(business_overrides or {}))
    return n, mod, r, biz


def create_running_local_ad(business_id: str, neighborhood_ids: list,
                            budget_cents: int = 5000,
                            bid_cents_per_impression: int = 100,
                            start_at: str = "2026-06-01T00:00:00Z",
                            end_at: str = "2026-06-30T00:00:00Z") -> dict:
    """Create a LocalAd and start it -> state=RUNNING."""
    ad = get_success_data(
        api_client.create_local_ad(
            create_local_ad_payload(
                business_id, neighborhood_ids,
                budget_cents=budget_cents,
                bid_cents_per_impression=bid_cents_per_impression,
                start_at=start_at, end_at=end_at,
            ),
            make_business_owner_headers(business_id),
        )
    )
    return get_success_data(
        api_client.start_local_ad(ad["id"], make_business_owner_headers(business_id))
    )


# --------------------------------------------------------------------------- Groups + Events
def create_group(creator_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_group(
            create_group_payload(creator_resident_id, neighborhood_id, **overrides),
            make_resident_headers(creator_resident_id),
        )
    )


def create_event(group_id: str, neighborhood_id: str, creator_resident_id: str,
                 **overrides) -> dict:
    """Create an Event authored by the group creator."""
    return get_success_data(
        api_client.create_event(
            create_event_payload(group_id, neighborhood_id, **overrides),
            make_resident_headers(creator_resident_id),
        )
    )


def rsvp_yes(event_id: str, resident_id: str) -> dict:
    return get_success_data(
        api_client.create_event_rsvp(
            create_event_rsvp_payload(event_id, resident_id, rsvp_status="YES"),
            make_resident_headers(resident_id),
        )
    )


# --------------------------------------------------------------------------- CivicNotice
def create_active_civic_notice(neighborhood_id: str,
                               effective_from: str = "2026-06-05T00:00:00Z",
                               effective_until: str = "2026-06-10T00:00:00Z",
                               notice_kind: str = "POLICE",
                               officer_id: str = AGENCY_OFFICER_USER_ID) -> dict:
    """Publish a CivicNotice as an AgencyOfficer."""
    return get_success_data(
        api_client.create_civic_notice(
            create_civic_notice_payload(
                neighborhood_id,
                effective_from=effective_from,
                effective_until=effective_until,
                notice_kind=notice_kind,
            ),
            make_agency_officer_headers(officer_id),
        )
    )
