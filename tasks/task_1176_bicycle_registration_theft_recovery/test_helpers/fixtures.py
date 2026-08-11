"""Composite setup helpers — multi-step scenario builders (PRD §3 workflows).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before each test, so nothing is
carried over between tests. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_partner_org_payload,
    create_bicycle_payload,
    create_transfer_payload,
    create_theft_report_payload,
    create_recovery_intake_payload,
    create_claim_payload,
    create_auction_payload,
    create_bid_payload,
    create_event_payload,
)
from .test_users import TEST_USERS, make_owner_headers, make_partner_headers

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + basic entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Drive the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_owner(email: str, full_name: str = "Test Owner") -> dict:
    resp = api_client.register_owner(
        create_owner_payload(email=email, full_name=full_name), ANONYMOUS
    )
    return get_success_data(resp)


def owner_headers(owner: dict) -> dict:
    return make_owner_headers(owner["id"])


def create_active_partner_org(
    name: str = "City PD",
    org_type: str = "LAW_ENFORCEMENT",
    jurisdiction_code: str = "CPD-1",
    contact_email: str = "pd@example.gov",
) -> dict:
    """Create a PartnerOrg and activate it (PENDING -> ACTIVE, PRD §3.1)."""
    org = get_success_data(
        api_client.create_partner_org(
            create_partner_org_payload(
                name=name,
                org_type=org_type,
                jurisdiction_code=jurisdiction_code,
                contact_email=contact_email,
            ),
            ADMIN,
        )
    )
    return get_success_data(api_client.activate_partner_org(org["id"], ADMIN))


def partner_headers(org: dict) -> dict:
    return make_partner_headers(org["id"])


def register_bicycle(owner: dict, **overrides) -> dict:
    """Register a bicycle for the given owner (identity-threaded, PRD §3.2)."""
    resp = api_client.create_bicycle(
        create_bicycle_payload(**overrides), owner_headers(owner)
    )
    return get_success_data(resp)


def file_theft_report(owner: dict, bicycle: dict, **overrides) -> dict:
    resp = api_client.create_theft_report(
        create_theft_report_payload(bicycle["id"], **overrides), owner_headers(owner)
    )
    return get_success_data(resp)


def flag_report(report_id: str) -> dict:
    return get_success_data(api_client.flag_theft_report(report_id, REGISTRAR))


def create_intake(org: dict, **overrides) -> dict:
    """Partner records a recovery intake (identity-threaded, PRD §3.5)."""
    resp = api_client.create_recovery_intake(
        create_recovery_intake_payload(**overrides), partner_headers(org)
    )
    return get_success_data(resp)


def scan_intake(intake_id: str, headers=None) -> dict:
    """Run the match scan (PRD §3.5). Defaults to the Registrar shared operation."""
    return get_success_data(
        api_client.scan_recovery_intake(intake_id, headers or REGISTRAR)
    )


def get_matches_for_intake(intake_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_matches(REGISTRAR, params={"recovery_intake_id": intake_id})
    )
    return data


def get_single_match_for_intake(intake_id: str) -> dict:
    matches = get_matches_for_intake(intake_id)
    assert len(matches) == 1, f"expected exactly one match for intake, got {len(matches)}"
    return matches[0]


def get_notifications_for_owner(owner_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_notifications(REGISTRAR, params={"owner_id": owner_id})
    )
    return data


def get_all_ledger_entries(params=None) -> list:
    merged = {"limit": 100}
    if params:
        merged.update(params)
    data, _meta = validate_paginated(api_client.list_ledger_entries(REGISTRAR, params=merged))
    return data


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_flagged_report_scenario(
    owner_email: str = "owner@x.com",
    bicycle_overrides: dict = None,
    report_overrides: dict = None,
) -> tuple:
    """Owner + bicycle + theft report moved UNDER_REVIEW -> FLAGGED (PRD §3.4).

    Returns (owner, bicycle, report); the bicycle is STOLEN after the cascade.
    """
    owner = register_owner(owner_email)
    bicycle = register_bicycle(owner, **(bicycle_overrides or {}))
    report = file_theft_report(owner, bicycle, **(report_overrides or {}))
    report = flag_report(report["id"])
    return owner, bicycle, report


def setup_duplicate_suspect_pair(owner_email: str = "dup@x.com") -> tuple:
    """Owner with bicycles DUP100/DUP101 (same make/model/color) — the second
    registration auto-flags the pair (confidence 9000 >= 8500, PRD §3.2).

    Returns (owner, bicycle_a, bicycle_b, flag); both bicycles DUPLICATE_SUSPECT.
    """
    owner = register_owner(owner_email)
    bicycle_a = register_bicycle(
        owner,
        serial_number="DUP100",
        manufacturer="Trek",
        model="X",
        primary_color="Black",
        declared_value_cents=100000,
        photo_url="https://x/a.jpg",
    )
    bicycle_b = register_bicycle(
        owner,
        serial_number="DUP101",
        manufacturer="Trek",
        model="X",
        primary_color="Black",
        declared_value_cents=90000,
        photo_url="https://x/b.jpg",
    )
    assert bicycle_b["integrity_status"] == "DUPLICATE_SUSPECT", (
        f"auto-flag did not fire: {bicycle_b['integrity_status']}"
    )
    flags, _meta = validate_paginated(
        api_client.list_duplicate_flags(REGISTRAR, params={"bicycle_a_id": bicycle_a["id"]})
    )
    assert len(flags) == 1, f"expected exactly one auto-created flag, got {len(flags)}"
    return owner, bicycle_a, bicycle_b, flags[0]


# ---------------------------------------------------------------------------
# Tier 2/3: match pipeline (report FLAGGED -> intake -> scan -> NOTIFIED match)
# ---------------------------------------------------------------------------

def setup_notified_match(
    owner_email: str = "owner@x.com",
    serial: str = "CSC200",
    manufacturer: str = "Giant",
    model: str = "Defy",
    color: str = "Red",
    declared_value_cents: int = 60000,
    photo_hash: str = None,
    occurred_at: str = "2026-05-10T00:00:00Z",
    appraised_value_cents: int = 40000,
    found_at: str = "2026-05-12T00:00:00Z",
    intake_overrides: dict = None,
    org: dict = None,
) -> dict:
    """Full match pipeline producing a NOTIFIED MatchCandidate (PRD §3.5).

    Owner registers a bicycle, files and flags a theft report; an ACTIVE partner
    org intakes a matching bicycle; the scan produces exactly one match with
    screening_score >= 7000 (NOTIFIED). Returns a dict with all entities.
    """
    set_clock(DEFAULT_CLOCK)
    owner = register_owner(owner_email)
    bicycle_overrides = dict(
        serial_number=serial,
        manufacturer=manufacturer,
        model=model,
        primary_color=color,
        declared_value_cents=declared_value_cents,
    )
    if photo_hash is not None:
        bicycle_overrides["photo_hash"] = photo_hash
    bicycle = register_bicycle(owner, **bicycle_overrides)
    report = file_theft_report(owner, bicycle, occurred_at=occurred_at)
    report = flag_report(report["id"])
    if org is None:
        org = create_active_partner_org()
    intake_payload = dict(
        serial_number_raw=serial,
        primary_color=color,
        found_at=found_at,
        appraised_value_cents=appraised_value_cents,
        manufacturer=manufacturer,
    )
    if photo_hash is not None:
        intake_payload["photo_hash"] = photo_hash
    if intake_overrides:
        intake_payload.update(intake_overrides)
    intake = create_intake(org, **intake_payload)
    scan_intake(intake["id"], partner_headers(org))
    match = get_single_match_for_intake(intake["id"])
    assert match["status"] == "NOTIFIED", (
        f"expected NOTIFIED match, got {match['status']} "
        f"(screening {match['screening_score']})"
    )
    return {
        "owner": owner,
        "bicycle": bicycle,
        "report": report,
        "org": org,
        "intake": intake,
        "match": match,
    }


def create_claim_for_match(scenario: dict, proof_text: str = "receipt and frame mark") -> dict:
    """Owner files an UNDER_REVIEW claim against the scenario's NOTIFIED match."""
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(
                scenario["intake"]["id"], scenario["match"]["id"], proof_text=proof_text
            ),
            owner_headers(scenario["owner"]),
        )
    )


def setup_approved_claim(**kwargs) -> dict:
    """Full claim-approval cascade: match CONFIRMED, intake CLAIM_PENDING,
    bicycle RECOVERED, report CLOSED_RECOVERED (PRD §3.6)."""
    scenario = setup_notified_match(**kwargs)
    scenario["claim"] = create_claim_for_match(scenario)
    scenario["claim"] = get_success_data(
        api_client.approve_claim(scenario["claim"]["id"], REGISTRAR)
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: disposition / auction pipeline
# ---------------------------------------------------------------------------

def setup_unclaimed_intake(
    serial: str = "ZZZ999",
    appraised_value_cents: int = 100000,
    org: dict = None,
    created_clock: str = DEFAULT_CLOCK,
    unclaimed_clock: str = "2026-06-01T00:00:00Z",
) -> tuple:
    """ACTIVE org + intake created at `created_clock`, marked UNCLAIMED after the
    thirty-day wait at `unclaimed_clock` (PRD §3.7). Returns (org, intake)."""
    set_clock(created_clock)
    if org is None:
        org = create_active_partner_org()
    intake = create_intake(
        org,
        serial_number_raw=serial,
        found_at="2026-04-30T00:00:00Z",
        appraised_value_cents=appraised_value_cents,
    )
    set_clock(unclaimed_clock)
    intake = get_success_data(api_client.mark_unclaimed(intake["id"], REGISTRAR))
    return org, intake


def create_auction_for_intake(
    intake: dict,
    starts_at: str = "2026-06-05T00:00:00Z",
    ends_at: str = "2026-06-10T00:00:00Z",
) -> dict:
    return get_success_data(
        api_client.create_auction(
            create_auction_payload(intake["id"], starts_at=starts_at, ends_at=ends_at),
            REGISTRAR,
        )
    )


def setup_open_auction(
    serial: str = "ZZZ999",
    appraised_value_cents: int = 100000,
    starts_at: str = "2026-06-05T00:00:00Z",
    ends_at: str = "2026-06-10T00:00:00Z",
    open_clock: str = "2026-06-05T00:00:00Z",
) -> dict:
    """UNCLAIMED intake + auction created, clock at `open_clock`, auction OPEN.

    Returns dict(org, intake, auction, auction_version) where auction_version is
    the live version after the open transition (for OCC-guarded bids).
    """
    org, intake = setup_unclaimed_intake(
        serial=serial, appraised_value_cents=appraised_value_cents
    )
    auction = create_auction_for_intake(intake, starts_at=starts_at, ends_at=ends_at)
    set_clock(open_clock)
    auction = get_success_data(api_client.open_auction(auction["id"], REGISTRAR))
    return {
        "org": org,
        "intake": intake,
        "auction": auction,
        "auction_version": auction["version"],
    }


def get_auction_version(auction_id: str) -> int:
    return get_success_data(api_client.get_auction(auction_id, REGISTRAR))["version"]


def place_bid(auction_id: str, owner: dict, amount_cents: int, expected_version: int) -> dict:
    return get_success_data(
        api_client.place_bid(
            auction_id,
            create_bid_payload(amount_cents, expected_version),
            owner_headers(owner),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: campus events
# ---------------------------------------------------------------------------

def setup_published_event(
    capacity: int = 5,
    starts_at: str = "2026-06-01T09:00:00Z",
    ends_at: str = "2026-06-01T12:00:00Z",
    clock: str = "2026-05-15T00:00:00Z",
    org_name: str = "State Univ",
    jurisdiction_code: str = "SU-1",
    contact_email: str = "su@example.edu",
) -> tuple:
    """ACTIVE CAMPUS org + event published (DRAFT -> PUBLISHED, PRD §3.9).

    Returns (org, event); logical clock left at `clock`.
    """
    set_clock(clock)
    org = create_active_partner_org(
        name=org_name,
        org_type="CAMPUS",
        jurisdiction_code=jurisdiction_code,
        contact_email=contact_email,
    )
    event = get_success_data(
        api_client.create_event(
            create_event_payload(
                org["id"], starts_at=starts_at, ends_at=ends_at, capacity=capacity
            ),
            ADMIN,
        )
    )
    event = get_success_data(api_client.publish_event(event["id"], ADMIN))
    return org, event


def book_seat(event: dict, owner: dict) -> dict:
    return get_success_data(
        api_client.book_event_seat(event["id"], owner_headers(owner))
    )
