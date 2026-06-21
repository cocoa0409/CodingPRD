"""Composite setup helpers.

Each test starts against an empty database (the harness restarts the server
before every test), so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Helpers use get_success_data() so setup failures
surface as clear "Setup failed" errors.

Identity threading: the acting Participant is entity-backed, so every
participant-owned mutation passes make_participant_headers(participant_id) — never
the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_participant_headers
from .factories import (
    participant_payload, event_payload, distance_payload, wave_payload,
    pricing_tier_payload, registration_payload, pledge_payload, result_payload,
)
from .constants import (
    OPENS_UTC, CLOSES_UTC, RACE_DATE_UTC,
    TIER_EARLY_FROM, TIER_REGULAR_FROM, TIER_LATE_FROM, CLOCK_REGULAR,
)

RD = TEST_USERS["race_director_headers"]
TO = TEST_USERS["timing_official_headers"]


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_participant(**overrides) -> dict:
    return get_success_data(api_client.create_participant(participant_payload(**overrides), RD))


def create_event(**overrides) -> dict:
    return get_success_data(api_client.create_event(event_payload(**overrides), RD))


def create_distance(event_id, **overrides) -> dict:
    return get_success_data(api_client.create_distance(event_id, distance_payload(**overrides), RD))


def create_wave(distance_id, **overrides) -> dict:
    return get_success_data(api_client.create_wave(distance_id, wave_payload(**overrides), RD))


def create_pricing_tier(distance_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pricing_tier(distance_id, pricing_tier_payload(**overrides), RD))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, RD))


def distance_version(distance_id, headers=None) -> int:
    headers = headers or RD
    return get_success_data(api_client.get_distance(distance_id, headers))["version"]


# --------------------------------------------------------------------------
# Read-back accessors (RaceDirector reads any resource per PRD §2.1)
# --------------------------------------------------------------------------
def get_distance_data(distance_id) -> dict:
    return get_success_data(api_client.get_distance(distance_id, RD))


def get_registration_data(registration_id) -> dict:
    return get_success_data(api_client.get_registration(registration_id, RD))


def get_waitlist_entry_data(waitlist_entry_id) -> dict:
    return get_success_data(api_client.get_waitlist_entry(waitlist_entry_id, RD))


def get_wave_data(wave_id) -> dict:
    return get_success_data(api_client.get_wave(wave_id, RD))


def get_event_data(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, RD))


def api_cancel(registration, participant) -> dict:
    """Cancel a registration as its owning participant."""
    return get_success_data(
        api_client.cancel_registration(registration["id"],
                                       make_participant_headers(participant["id"])))


def get_event_close(event_id) -> dict:
    """Transition an OPEN event to CLOSED (RaceDirector)."""
    return get_success_data(api_client.close_event(event_id, RD))


# --------------------------------------------------------------------------
# Tier 1/2: a fully OPEN event with one distance, one wave, and pricing tiers.
# --------------------------------------------------------------------------
def setup_open_event(
    capacity_total=50,
    wave_capacity=50,
    corral_capacity=10,
    distance_label="FIVE_K",
    distance_km=5.0,
    charity_capacity=None,
    charity_fundraising_minimum_cents=None,
    tiers=None,
    open_clock=CLOCK_REGULAR,
    **event_overrides,
):
    """Build participant-free preconditions: Event(OPEN) + Distance + Wave + tiers.

    tiers: list of dicts (tier_name, effective_from_utc, base_price_cents). Default
    is a single REGULAR tier active from 2026-05-01. The clock is set to open_clock
    before opening so the open precondition (now >= registration_opens_utc) holds.

    Returns (event, distance, wave).
    """
    if tiers is None:
        tiers = [dict(tier_name="REGULAR", effective_from_utc=TIER_REGULAR_FROM,
                      base_price_cents=5500)]
    dist_kwargs = dict(label=distance_label, distance_km=distance_km,
                       capacity_total=capacity_total)
    if charity_capacity is not None:
        dist_kwargs["charity_capacity"] = charity_capacity
    if charity_fundraising_minimum_cents is not None:
        dist_kwargs["charity_fundraising_minimum_cents"] = charity_fundraising_minimum_cents

    event = create_event(**event_overrides)
    distance = create_distance(event["id"], **dist_kwargs)
    wave = create_wave(distance["id"], wave_capacity=wave_capacity,
                       corral_capacity=corral_capacity)
    for t in tiers:
        create_pricing_tier(distance["id"], **t)
    set_clock(open_clock)
    get_success_data(api_client.open_event(event["id"], RD))
    return event, distance, wave


def standard_tiers():
    """The canonical three-tier ladder: EARLY 4000, REGULAR 5500, LATE 7000."""
    return [
        dict(tier_name="EARLY_BIRD", effective_from_utc=TIER_EARLY_FROM, base_price_cents=4000),
        dict(tier_name="REGULAR", effective_from_utc=TIER_REGULAR_FROM, base_price_cents=5500),
        dict(tier_name="LATE", effective_from_utc=TIER_LATE_FROM, base_price_cents=7000),
    ]


# --------------------------------------------------------------------------
# Tier 1: registration creation / confirmation
# --------------------------------------------------------------------------
def create_registration(event, distance, wave, participant, **overrides):
    """Create a PENDING_PAYMENT registration owned by `participant`."""
    headers = make_participant_headers(participant["id"])
    payload = registration_payload(event["id"], distance["id"], wave["id"],
                                   participant["id"], **overrides)
    return get_success_data(api_client.create_registration(payload, headers))


def confirm_registration(registration, distance, participant):
    """Confirm a PENDING_PAYMENT registration using the live distance version.

    Returns the registration object after confirmation (CONFIRMED or WAITLISTED).
    """
    headers = make_participant_headers(participant["id"])
    dv = distance_version(distance["id"], headers)
    return get_success_data(
        api_client.confirm_payment(registration["id"], {"expected_distance_version": dv}, headers))


def setup_confirmed_registration(capacity_total=5, participant=None, **open_overrides):
    """OPEN event + distance + wave + one CONFIRMED registration.

    Returns (event, distance, wave, participant, registration).
    """
    event, distance, wave = setup_open_event(capacity_total=capacity_total, **open_overrides)
    participant = participant or create_participant()
    reg = create_registration(event, distance, wave, participant)
    reg = confirm_registration(reg, distance, participant)
    return event, distance, wave, participant, reg


# --------------------------------------------------------------------------
# Tier 3: full lifecycle through BIB_ASSIGNED / RESULTS_POSTED
# --------------------------------------------------------------------------
def setup_bib_assigned_registration(capacity_total=50, **open_overrides):
    """OPEN event + CONFIRMED registration advanced to BIB_ASSIGNED.

    Returns (event, distance, wave, participant, registration, bib_assignment).
    """
    event, distance, wave, participant, reg = setup_confirmed_registration(
        capacity_total=capacity_total, **open_overrides)
    bib = get_success_data(api_client.assign_bib(reg["id"], RD))
    return event, distance, wave, participant, reg, bib


def advance_event_to_results_posted(event_id, race_clock="2026-07-05T01:00:00Z"):
    """CLOSE the event, advance the clock past race_date_utc, and post results."""
    get_success_data(api_client.close_event(event_id, RD))
    set_clock(race_clock)
    get_success_data(api_client.post_results_event(event_id, TO))


def setup_results_posted_with_bib(capacity_total=50, **open_overrides):
    """Full setup: BIB_ASSIGNED registration on an event that is RESULTS_POSTED.

    Returns (event, distance, wave, participant, registration, bib_assignment).
    """
    event, distance, wave, participant, reg, bib = setup_bib_assigned_registration(
        capacity_total=capacity_total, **open_overrides)
    advance_event_to_results_posted(event["id"])
    return event, distance, wave, participant, reg, bib


def post_result(registration, distance, gun_start=0, mat_cross=130, finish=12130):
    """Post a PROVISIONAL ResultRecord for a registration (TimingOfficial)."""
    payload = result_payload(registration["id"], distance["id"], gun_start, mat_cross, finish)
    return get_success_data(api_client.create_result(payload, TO))


# --------------------------------------------------------------------------
# Tier 4: waitlist scenarios (full distance routes to WAITLISTED)
# --------------------------------------------------------------------------
def setup_capacity_one_with_waitlist(num_waitlisted=1, **open_overrides):
    """Capacity-1 distance: P1 CONFIRMED; `num_waitlisted` additional participants
    each routed to WAITLISTED (QUEUED) in FIFO order.

    Returns (event, distance, wave, p1, reg1, waitlisted) where `waitlisted` is a
    list of (participant, registration, waitlist_entry) tuples in queue order.
    """
    event, distance, wave = setup_open_event(capacity_total=1, **open_overrides)
    p1 = create_participant()
    reg1 = create_registration(event, distance, wave, p1)
    reg1 = confirm_registration(reg1, distance, p1)

    waitlisted = []
    for _ in range(num_waitlisted):
        p = create_participant()
        reg = create_registration(event, distance, wave, p)
        reg = confirm_registration(reg, distance, p)  # routes to WAITLISTED
        waitlisted.append((p, reg))

    # Resolve queued waitlist entries in FIFO (created_at ASC) order.
    queued = get_success_data(
        api_client.list_distance_waitlist_entries(distance["id"], RD, {"status": "QUEUED"}))
    entries_by_reg = {e["registration_id"]: e for e in queued}
    resolved = [(p, reg, entries_by_reg.get(reg["id"])) for (p, reg) in waitlisted]
    return event, distance, wave, p1, reg1, resolved


def setup_offered_waitlist_entry(**open_overrides):
    """Capacity-1: P1 CONFIRMED, P2 WAITLISTED, then P1 cancels so P2's entry is
    promoted to OFFERED.

    Returns (event, distance, wave, p1, reg1, p2, reg2, wl2).
    """
    event, distance, wave, p1, reg1, resolved = setup_capacity_one_with_waitlist(
        num_waitlisted=1, **open_overrides)
    p2, reg2, _ = resolved[0]
    get_success_data(api_client.cancel_registration(reg1["id"], make_participant_headers(p1["id"])))
    # P2's entry should now be OFFERED.
    wl2 = get_success_data(
        api_client.list_distance_waitlist_entries(distance["id"], RD,
                                                  {"status": "OFFERED"}))[0]
    return event, distance, wave, p1, reg1, p2, reg2, wl2


# --------------------------------------------------------------------------
# Tier: charity entries and fundraising
# --------------------------------------------------------------------------
def setup_confirmed_charity_registration(
    charity_capacity=10, charity_fundraising_minimum_cents=25000,
    capacity_total=50, wave_capacity=50, **open_overrides
):
    """OPEN event with a charity-enabled distance and a CONFIRMED CHARITY
    registration (no pledges yet).

    Returns (event, distance, wave, participant, registration).
    """
    event, distance, wave = setup_open_event(
        capacity_total=capacity_total, wave_capacity=wave_capacity,
        charity_capacity=charity_capacity,
        charity_fundraising_minimum_cents=charity_fundraising_minimum_cents,
        **open_overrides)
    participant = create_participant()
    reg = create_registration(event, distance, wave, participant, entry_type="CHARITY")
    reg = confirm_registration(reg, distance, participant)
    return event, distance, wave, participant, reg


def add_pledge(registration, participant, amount_cents, donor_name="Donor", settle=False):
    """Create a pledge on a CHARITY registration; optionally settle it."""
    headers = make_participant_headers(participant["id"])
    pledge = get_success_data(
        api_client.create_pledge(pledge_payload(registration["id"], amount_cents=amount_cents,
                                                donor_name=donor_name), headers))
    if settle:
        pledge = get_success_data(api_client.settle_pledge(pledge["id"], headers))
    return pledge
