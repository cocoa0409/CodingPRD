"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_event_payload, create_class_payload, create_zone_payload,
    create_registrant_payload, create_vehicle_payload, create_waiver_payload,
    create_registration_payload, create_judge_payload, create_criteria_scores,
    create_score_sheet_payload, create_ballot_payload,
    create_booth_application_payload, create_sound_slot_payload,
)
from .test_users import TEST_USERS, make_judge_headers, make_participant_headers

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: event state progression
# ---------------------------------------------------------------------------

def create_event(**overrides):
    """Create a bare event in DRAFT. Returns the event dict."""
    return get_success_data(api_client.create_event(create_event_payload(**overrides), ORG))


def create_event_with_class_and_zone(class_overrides=None, zone_overrides=None, **event_overrides):
    """Event in DRAFT with one class and one zone. Returns (event, cls, zone)."""
    ev = create_event(**event_overrides)
    cls = get_success_data(api_client.create_class(
        ev["id"], create_class_payload(**(class_overrides or {})), ORG))
    zone = get_success_data(api_client.create_zone(
        ev["id"], create_zone_payload(**(zone_overrides or {})), ORG))
    return ev, cls, zone


def create_published_event(class_overrides=None, zone_overrides=None, **event_overrides):
    """Event carried DRAFT -> PUBLISHED. Returns (event, cls, zone)."""
    ev, cls, zone = create_event_with_class_and_zone(class_overrides, zone_overrides, **event_overrides)
    ev = get_success_data(api_client.publish_event(ev["id"], ORG))
    return ev, cls, zone


def create_open_event(class_overrides=None, zone_overrides=None, **event_overrides):
    """Event carried through to REGISTRATION_OPEN. Returns (event, cls, zone)."""
    ev, cls, zone = create_published_event(class_overrides, zone_overrides, **event_overrides)
    ev = get_success_data(api_client.open_registration(ev["id"], ORG))
    return ev, cls, zone


# ---------------------------------------------------------------------------
# Tier 2: people, vehicles, waivers, registrations
# ---------------------------------------------------------------------------

def create_registrant_with_vehicle(club_member=False, is_minor=False,
                                   vehicle_overrides=None, name="Test Entrant",
                                   email="entrant@example.com"):
    """Registrant + one vehicle. Returns (registrant, vehicle)."""
    reg = get_success_data(api_client.create_registrant(
        create_registrant_payload(full_name=name, email=email,
                                  club_member=club_member, is_minor=is_minor), ORG))
    veh = get_success_data(api_client.create_vehicle(
        reg["id"], create_vehicle_payload(**(vehicle_overrides or {})), ORG))
    return reg, veh


def sign_waiver(event_id, registrant_id, signature_name="Test Entrant", guardian_name=None):
    payload = create_waiver_payload(event_id, registrant_id, signature_name=signature_name)
    if guardian_name is not None:
        payload["guardian_name"] = guardian_name
    return get_success_data(api_client.create_waiver(payload, DESK))


def create_registration(event_id, registrant_id, vehicle_id, class_id, headers=None, **overrides):
    return get_success_data(api_client.create_registration(
        create_registration_payload(event_id, registrant_id, vehicle_id, class_id, **overrides),
        headers or DESK))


def create_paid_registration(event_id, registrant_id, vehicle_id, class_id,
                             amount_cents=None, method="CASH", sign=True):
    """Registration created and settled for its frozen fee. Returns registration."""
    reg = create_registration(event_id, registrant_id, vehicle_id, class_id)
    if sign:
        # Waiver is not required for payment, but most flows need it later; the
        # caller controls this via the sign flag.
        pass
    pay_amount = amount_cents if amount_cents is not None else reg["fee_cents"]
    get_success_data(api_client.create_registration_payment(
        reg["id"], {"amount_cents": pay_amount, "method": method}, DESK))
    return get_success_data(api_client.get_registration(reg["id"], ORG))


def setup_open_event_with_registration(class_overrides=None, zone_overrides=None,
                                       club_member=False, vehicle_overrides=None,
                                       pay=True, waiver=False, **event_overrides):
    """REGISTRATION_OPEN event + one registration (optionally paid/waivered).

    Returns dict(event, cls, zone, registrant, vehicle, registration).
    """
    ev, cls, zone = create_open_event(class_overrides, zone_overrides, **event_overrides)
    reg, veh = create_registrant_with_vehicle(
        club_member=club_member, vehicle_overrides=vehicle_overrides)
    if waiver:
        sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
    if pay:
        registration = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
    else:
        registration = create_registration(ev["id"], reg["id"], veh["id"], cls["id"])
    return {
        "event": ev, "cls": cls, "zone": zone,
        "registrant": reg, "vehicle": veh, "registration": registration,
    }


def check_in(registration_id, zone_id):
    return get_success_data(api_client.check_in_registration(
        registration_id, {"zone_id": zone_id}, DESK))


# ---------------------------------------------------------------------------
# Tier 3: judging lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                        num_judges=1, clock_during_judging="2026-08-15T12:30:00Z",
                        checked_in=None, **kwargs):
    """Event walked to JUDGING with paid, waivered, checked-in registrations and
    rostered judges.

    Returns dict(event, cls, zone, registrations, judges).
    `checked_in` defaults to all registrations; pass a list of indices to
    check in only a subset (the rest stay CONFIRMED and flip to NO_SHOW at
    start-judging).
    """
    mode = "JUDGED" if judged else "PEOPLES_CHOICE"
    ev, cls, zone = create_open_event(
        class_overrides={
            "judging_mode": mode, "award_depth": award_depth,
            "min_year": 1900, "max_year": 2026,
        },
        zone_overrides={
            "arrival_window_start": "2026-08-15T08:00:00Z",
            "arrival_window_end": "2026-08-15T10:00:00Z",
        },
        **kwargs,
    )
    regs = []
    for i in range(num_registrations):
        reg, veh = create_registrant_with_vehicle(
            name=f"Entrant {i}", email=f"entrant{i}@example.com",
            vehicle_overrides={"year": 1970 + i},
        )
        sign_waiver(ev["id"], reg["id"], signature_name=reg["full_name"])
        regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"]))
    # Arrival window
    get_success_data(api_client.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
    to_check = checked_in if checked_in is not None else list(range(num_registrations))
    for i in to_check:
        regs[i] = check_in(regs[i]["id"], zone["id"])
    judges = []
    for j in range(num_judges):
        judges.append(get_success_data(api_client.create_judge(
            ev["id"],
            create_judge_payload(name=f"J{j}", email=f"judge{j}@example.com",
                                 assigned_class_ids=[cls["id"]]),
            ORG)))
    get_success_data(api_client.set_clock({"to_iso8601": clock_during_judging}, ORG))
    get_success_data(api_client.lock_registration(ev["id"], ORG))
    ev = get_success_data(api_client.start_judging(ev["id"], ORG))
    # Re-read registrations: start-judging may have flipped some to NO_SHOW.
    regs = [get_success_data(api_client.get_registration(r["id"], ORG)) for r in regs]
    return {"event": ev, "cls": cls, "zone": zone, "registrations": regs, "judges": judges}


def judge_create_and_submit_sheet(registration_id, judge_id, criteria_scores=None):
    """Judge creates a DRAFT sheet and submits it. Returns the sheet dict."""
    sheet = get_success_data(api_client.create_score_sheet(
        create_score_sheet_payload(
            registration_id,
            criteria_scores=criteria_scores or create_criteria_scores(),
        ),
        make_judge_headers(judge_id)))
    return get_success_data(api_client.submit_score_sheet(sheet["id"], make_judge_headers(judge_id)))


def finalize_event(event_id, caller_headers=None):
    """Finalize with the event's current version (fresh read). Returns the event."""
    headers = caller_headers or ORG
    ev = get_success_data(api_client.get_event(event_id, ORG))
    return get_success_data(api_client.finalize_tabulations(
        event_id, {"expected_event_version": ev["version"]}, headers))


def list_event_awards(event_id):
    return get_success_data(api_client.list_awards(ORG, params={"event_id": event_id, "limit": 100}))


def get_zone(event_id, zone_id):
    """Zones have no single-get endpoint; find it in the event's zone list."""
    zones = get_success_data(api_client.list_zones(event_id, ORG, params={"limit": 100}))
    for z in zones:
        if z["id"] == zone_id:
            return z
    raise AssertionError(f"zone {zone_id} not found in event {event_id}")


def get_class(event_id, class_id):
    classes = get_success_data(api_client.list_classes(event_id, ORG, params={"limit": 100}))
    for c in classes:
        if c["id"] == class_id:
            return c
    raise AssertionError(f"class {class_id} not found in event {event_id}")


def get_judge(event_id, judge_id):
    judges = get_success_data(api_client.list_judges(event_id, ORG, params={"limit": 100}))
    for j in judges:
        if j["id"] == judge_id:
            return j
    raise AssertionError(f"judge {judge_id} not found in event {event_id}")


def get_summary(event_id):
    return get_success_data(api_client.get_event_summary(event_id, ORG))


# ---------------------------------------------------------------------------
# Tier 4: people's-choice helpers
# ---------------------------------------------------------------------------

def cast_ballot(event_id, registration_id, voter_registrant_id):
    return get_success_data(api_client.create_ballot(
        create_ballot_payload(event_id, registration_id),
        make_participant_headers(voter_registrant_id)))


def create_voter(name, email, club_member=False):
    return get_success_data(api_client.create_registrant(
        create_registrant_payload(full_name=name, email=email, club_member=club_member), ORG))


# ---------------------------------------------------------------------------
# Tier 5: booth helpers
# ---------------------------------------------------------------------------

def create_booth_at_state(event_id, target_state="SUBMITTED", zone=None, spaces=None,
                          tier="SINGLE", power_requested=False, business_name="Vendor",
                          contact_email="vendor@example.com"):
    """Carry a booth application to the requested state (SUBMITTED, APPROVED,
    PAID, ASSIGNED). For ASSIGNED, pass the VENDOR_ROW zone and spaces."""
    app = get_success_data(api_client.create_booth_application(
        create_booth_application_payload(
            event_id, business_name=business_name, contact_email=contact_email,
            booth_tier=tier, power_requested=power_requested), ORG))
    if target_state == "SUBMITTED":
        return app
    app = get_success_data(api_client.approve_booth_application(app["id"], ORG))
    if target_state == "APPROVED":
        return app
    get_success_data(api_client.create_booth_payment(
        app["id"], {"amount_cents": app["fee_cents"], "method": "CARD"}, ORG))
    app = get_success_data(api_client.get_booth_application(app["id"], ORG))
    if target_state == "PAID":
        return app
    assert zone is not None and spaces is not None, "ASSIGNED requires zone and spaces"
    app = get_success_data(api_client.assign_booth(
        app["id"], {"zone_id": zone["id"], "spaces": spaces}, ORG))
    return app
