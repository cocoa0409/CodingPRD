"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: each test runs against an empty database, so nothing is
carried over between tests.  Setup calls use the lenient success validator so
that a broken precondition surfaces as a clear setup failure.
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH_UTC,
    BASE_REGISTRATION_FEE_CENTS,
    SURCHARGE_LOW_THRESHOLD_CENTS,
    SURCHARGE_HIGH_THRESHOLD_CENTS,
    ADMIN_SURCHARGE_LOW_CENTS,
    ADMIN_SURCHARGE_HIGH_CENTS,
    MEDICAL_DIRECTOR_USER_ID,
    REGISTRATION_OFFICER_USER_ID,
    RECORDS_RATIFIER_USER_ID,
    SPONSOR_LIAISON_USER_ID,
    EDITION_REGISTRATION_DEADLINE_UTC,
    EDITION_START_DATE,
    EDITION_END_DATE,
)
from .factories import (
    games_edition_payload,
    sport_payload,
    sport_event_payload,
    venue_payload,
    session_slot_payload,
    athlete_payload,
    qualifying_result_payload,
    sport_entry_payload,
    medical_screening_payload,
    personnel_payload,
    personnel_assignment_payload,
    competition_result_payload,
    age_group_record_payload,
    accommodation_block_payload,
    village_stay_payload,
    sponsorship_commitment_payload,
    unique_sport_code,
)
from .test_users import (
    TEST_USERS,
    make_athlete_headers,
    make_sport_official_headers,
    make_registration_officer_headers,
    make_medical_director_headers,
    make_records_ratifier_headers,
    make_sponsor_liaison_headers,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
MEDICAL = TEST_USERS["medical_director_headers"]
RATIFIER = TEST_USERS["records_ratifier_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]


# ---------------------------------------------------------------------------
# Arithmetic mirrors used to drive setup (never to replace a test assertion).
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round to a whole number of cents, a fractional half rounding away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discount_pct_for(entry_count: int) -> float:
    if entry_count <= 1:
        return 0.0
    if entry_count <= 3:
        return 0.05
    if entry_count <= 5:
        return 0.12
    return 0.20


def expected_fee_total(event_fees_cents=()) -> int:
    """The settled `fee_total_cents` for an athlete holding live entries on
    events with the given entry fees."""
    fees = list(event_fees_cents)
    entry_count = len(fees)
    event_fees = sum(fees)
    subtotal = event_fees + BASE_REGISTRATION_FEE_CENTS
    pct = discount_pct_for(entry_count)
    discount = round_half_up(subtotal * pct)
    discounted = subtotal - discount
    if discounted < SURCHARGE_LOW_THRESHOLD_CENTS:
        surcharge = 0
    elif discounted < SURCHARGE_HIGH_THRESHOLD_CENTS:
        surcharge = ADMIN_SURCHARGE_LOW_CENTS
    else:
        surcharge = ADMIN_SURCHARGE_HIGH_CENTS
    return discounted + surcharge


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Reposition the server's logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock() -> dict:
    """Return the clock to the instant it reads on process startup."""
    return set_clock(CLOCK_EPOCH_UTC)


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation
# ---------------------------------------------------------------------------
def create_edition(**overrides) -> dict:
    """A games edition in DRAFT."""
    return get_success_data(
        api_client.create_games_edition(games_edition_payload(**overrides), ADMIN)
    )


def create_sport(**overrides) -> dict:
    return get_success_data(api_client.create_sport(sport_payload(**overrides), ADMIN))


def create_high_contact_sport(**overrides) -> dict:
    """A HIGH contact-class sport, which the medical-coverage gate keys on."""
    defaults = {
        "sport_code": unique_sport_code("BSK"),
        "name": "3x3 Basketball",
        "contact_class": "HIGH",
        "mark_direction": "HIGHER_IS_BETTER",
        "required_certification_level": 2,
        "min_age": 50,
    }
    defaults.update(overrides)
    return create_sport(**defaults)


def create_sport_event(sport_id: str, games_edition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sport_event(
            sport_event_payload(sport_id, games_edition_id, **overrides), ADMIN
        )
    )


def create_venue(games_edition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_venue(venue_payload(games_edition_id, **overrides), ADMIN)
    )


def create_cardiac_venue(games_edition_id: str, **overrides) -> dict:
    """A venue whose emergency tier is EP_CARDIAC and which has a medical bay."""
    defaults = {
        "name": "St Bede Cardiac Arena",
        "emergency_protocol_code": "EP_CARDIAC",
        "has_onsite_medical_bay": True,
    }
    defaults.update(overrides)
    return create_venue(games_edition_id, **defaults)


def create_accommodation_block(games_edition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_accommodation_block(
            accommodation_block_payload(games_edition_id, **overrides), ADMIN
        )
    )


def create_sponsorship_commitment(games_edition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsorship_commitment(
            sponsorship_commitment_payload(games_edition_id, **overrides), SPONSOR
        )
    )


def create_personnel(games_edition_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_personnel(personnel_payload(games_edition_id, **overrides), ADMIN)
    )


def create_qualifying_result(athlete_id: str, sport_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_qualifying_result(
            qualifying_result_payload(athlete_id, sport_id, **overrides), OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the edition preamble every workflow needs
# ---------------------------------------------------------------------------
def open_registration(games_edition_id: str) -> dict:
    """Move the edition DRAFT -> REGISTRATION_OPEN."""
    return get_success_data(api_client.open_registration(games_edition_id, ADMIN))


def ops_run(games_edition_id: str) -> dict:
    """Run the operations checkpoint."""
    return get_success_data(api_client.ops_run(games_edition_id, ADMIN))


def setup_open_edition(edition=None, sport=None, event=None) -> dict:
    """Edition in REGISTRATION_OPEN with one LOW-contact sport and one OPEN event.

    `edition`, `sport` and `event` are optional override dicts.  Returns
    {"edition", "sport", "event"} with the edition re-read after the
    open-registration transition.
    """
    ed = create_edition(**(edition or {}))
    sp = create_sport(**(sport or {}))
    ev = create_sport_event(sp["id"], ed["id"], **(event or {}))
    open_registration(ed["id"])
    ed = get_edition(ed["id"])
    return {"edition": ed, "sport": sp, "event": ev}


def setup_open_edition_high_contact(edition=None, sport=None, event=None) -> dict:
    """The same preamble, but the sport's contact_class is HIGH."""
    ed = create_edition(**(edition or {}))
    sp = create_high_contact_sport(**(sport or {}))
    defaults = {"event_code": "BB3X3", "entry_fee_cents": 4000}
    defaults.update(event or {})
    ev = create_sport_event(sp["id"], ed["id"], **defaults)
    open_registration(ed["id"])
    ed = get_edition(ed["id"])
    return {"edition": ed, "sport": sp, "event": ev}


# ---------------------------------------------------------------------------
# Re-read helpers (setup code that needs a row's current shape)
# ---------------------------------------------------------------------------
def get_edition(games_edition_id: str) -> dict:
    return get_success_data(api_client.get_games_edition(games_edition_id, ADMIN))


def get_event(sport_event_id: str) -> dict:
    return get_success_data(api_client.get_sport_event(sport_event_id, ADMIN))


def get_venue(venue_id: str) -> dict:
    return get_success_data(api_client.get_venue(venue_id, ADMIN))


def get_slot(session_slot_id: str) -> dict:
    return get_success_data(api_client.get_session_slot(session_slot_id, ADMIN))


def get_athlete(athlete_id: str) -> dict:
    return get_success_data(api_client.get_athlete(athlete_id, ADMIN))


def get_entry(sport_entry_id: str) -> dict:
    return get_success_data(api_client.get_sport_entry(sport_entry_id, ADMIN))


def get_person(personnel_id: str) -> dict:
    return get_success_data(api_client.get_personnel(personnel_id, ADMIN))


def get_assignment(personnel_assignment_id: str) -> dict:
    return get_success_data(
        api_client.get_personnel_assignment(personnel_assignment_id, ADMIN)
    )


def get_result(competition_result_id: str) -> dict:
    return get_success_data(api_client.get_competition_result(competition_result_id, ADMIN))


def get_record(age_group_record_id: str) -> dict:
    return get_success_data(api_client.get_age_group_record(age_group_record_id, ADMIN))


def get_block(accommodation_block_id: str) -> dict:
    return get_success_data(
        api_client.get_accommodation_block(accommodation_block_id, ADMIN)
    )


def get_stay(village_stay_id: str) -> dict:
    return get_success_data(api_client.get_village_stay(village_stay_id, ADMIN))


def get_commitment(sponsorship_commitment_id: str) -> dict:
    return get_success_data(
        api_client.get_sponsorship_commitment(sponsorship_commitment_id, ADMIN)
    )


def get_economic_impact(games_edition_id: str) -> dict:
    return get_success_data(api_client.get_economic_impact(games_edition_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3 — the athlete lifecycle
# ---------------------------------------------------------------------------
def create_athlete(games_edition_id: str, **overrides) -> dict:
    """An athlete in PENDING_PAYMENT / NOT_SCREENED."""
    return get_success_data(
        api_client.create_athlete(athlete_payload(games_edition_id, **overrides), OFFICER)
    )


def pay_fees(athlete_id: str, amount_cents: int) -> dict:
    """Settle the registration fee, moving PENDING_PAYMENT -> REGISTERED."""
    return get_success_data(
        api_client.pay_fees(athlete_id, {"amount_cents": amount_cents}, ADMIN)
    )


def pay_fees_for(athlete_id: str, event_fees_cents=()) -> dict:
    """Settle at the amount the PRD settlement produces for these entry fees."""
    return pay_fees(athlete_id, expected_fee_total(event_fees_cents))


def screen_athlete(athlete_id: str, **overrides) -> dict:
    """Record a screening.  Defaults (128 / 70 / no cardiac history) score below
    25.0 for a sixty-year-old with no HIGH-contact entries, so the athlete is
    CLEARED."""
    return get_success_data(
        api_client.create_medical_screening(
            medical_screening_payload(athlete_id, MEDICAL_DIRECTOR_USER_ID, **overrides),
            make_medical_director_headers(MEDICAL_DIRECTOR_USER_ID),
        )
    )


def create_registered_athlete(games_edition_id: str, event_fees_cents=(), **overrides) -> dict:
    """Athlete whose registration_status is REGISTERED and whose medical_status
    is SCREENED_CLEARED — the state entry acceptance demands."""
    athlete = create_athlete(games_edition_id, **overrides)
    pay_fees_for(athlete["id"], event_fees_cents)
    screen_athlete(athlete["id"])
    return get_athlete(athlete["id"])


def create_entry(athlete_id: str, sport_event_id: str, **overrides) -> dict:
    """File an entry, which opens in SUBMITTED."""
    return get_success_data(
        api_client.create_sport_entry(
            sport_entry_payload(athlete_id, sport_event_id, **overrides), OFFICER
        )
    )


def review_entry(sport_entry_id: str, decision: str, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.review_sport_entry(
            sport_entry_id, payload,
            make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID),
        )
    )


def take_up_and_accept(sport_entry_id: str) -> dict:
    """SUBMITTED -> UNDER_REVIEW -> ACCEPTED."""
    review_entry(sport_entry_id, "TAKE_UP")
    return review_entry(sport_entry_id, "ACCEPT")


def take_up_and_waitlist(sport_entry_id: str) -> dict:
    """SUBMITTED -> UNDER_REVIEW -> WAITLISTED, consuming no capacity."""
    review_entry(sport_entry_id, "TAKE_UP")
    return review_entry(sport_entry_id, "WAITLIST")


def setup_accepted_entry(games_edition_id: str, event: dict, **athlete_overrides) -> dict:
    """A registered, screened athlete holding one ACCEPTED entry on `event`.

    Returns {"athlete", "entry"}.
    """
    athlete = create_athlete(games_edition_id, **athlete_overrides)
    entry = create_entry(athlete["id"], event["id"])
    pay_fees_for(athlete["id"], [event["entry_fee_cents"]])
    screen_athlete(athlete["id"])
    take_up_and_accept(entry["id"])
    return {"athlete": get_athlete(athlete["id"]), "entry": get_entry(entry["id"])}


# ---------------------------------------------------------------------------
# Tier 4 — venues, blocks and staffing
# ---------------------------------------------------------------------------
def create_session_slot(venue_id: str, sport_event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_session_slot(
            session_slot_payload(venue_id, sport_event_id, **overrides), ADMIN
        )
    )


def create_assignment(personnel_id: str, session_slot_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_personnel_assignment(
            personnel_assignment_payload(personnel_id, session_slot_id, **overrides), ADMIN
        )
    )


def confirm_assignment(personnel_assignment_id: str, personnel_id: str) -> dict:
    """The person who holds the assignment confirms it themselves."""
    return get_success_data(
        api_client.confirm_personnel_assignment(
            personnel_assignment_id, make_sport_official_headers(personnel_id)
        )
    )


def advance_slot(session_slot_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.advance_session_slot(session_slot_id, {"to_status": to_status}, ADMIN)
    )


def close_venue(venue_id: str, reason: str = "Storm damage; facility out of service.") -> dict:
    return get_success_data(api_client.close_venue(venue_id, {"reason": reason}, ADMIN))


def seed_event(sport_event_id: str) -> dict:
    """OPEN -> SEEDED."""
    return get_success_data(
        api_client.seed_sport_event(
            sport_event_id, make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID)
        )
    )


def create_certified_official(games_edition_id: str, sport_code: str, **overrides) -> dict:
    """An OFFICIAL badged for `sport_code` at certification level 3."""
    defaults = {
        "full_name": "Owen Reyes",
        "personnel_type": "OFFICIAL",
        "certification_level": 3,
        "certified_sport_codes": [sport_code],
    }
    defaults.update(overrides)
    return create_personnel(games_edition_id, **defaults)


def reserve_stay(athlete_id: str, accommodation_block_id: str, **overrides) -> dict:
    """Reserve a village stay, reading the block's current version for the guard."""
    block = get_block(accommodation_block_id)
    payload = village_stay_payload(athlete_id, accommodation_block_id, block["version"])
    payload.update(overrides)
    return get_success_data(api_client.create_village_stay(payload, ADMIN))


def cancel_stay(village_stay_id: str, reason: str = "Travel plans changed.") -> dict:
    return get_success_data(
        api_client.cancel_village_stay(village_stay_id, ADMIN, {"reason": reason})
    )


def allocate_commitment(sponsorship_commitment_id: str, games_edition_id: str) -> dict:
    """Allocate the pledge, reading the edition's current version for the guard."""
    edition = get_edition(games_edition_id)
    return get_success_data(
        api_client.allocate_sponsorship_commitment(
            sponsorship_commitment_id,
            {"expected_games_edition_version": edition["version"]},
            make_sponsor_liaison_headers(SPONSOR_LIAISON_USER_ID),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 — full competition chains
# ---------------------------------------------------------------------------
def setup_seeded_event_with_staffed_slot(
    edition_overrides=None,
    sport_overrides=None,
    event_overrides=None,
    venue_overrides=None,
    slot_overrides=None,
) -> dict:
    """The whole competition spine: edition in REGISTRATION_OPEN, one venue, one
    registered and screened athlete with an ACCEPTED entry, the event SEEDED,
    one certified official, one SCHEDULED slot and one CONFIRMED assignment.

    Returns {"edition", "sport", "event", "venue", "athlete", "entry",
             "official", "slot", "assignment"}.
    """
    base = setup_open_edition(edition_overrides, sport_overrides, event_overrides)
    ed, sp, ev = base["edition"], base["sport"], base["event"]
    venue = create_venue(ed["id"], **(venue_overrides or {}))
    pair = setup_accepted_entry(ed["id"], ev)
    seed_event(ev["id"])
    official = create_certified_official(ed["id"], sp["sport_code"])
    slot = create_session_slot(venue["id"], ev["id"], **(slot_overrides or {}))
    assignment = create_assignment(official["id"], slot["id"])
    confirm_assignment(assignment["id"], official["id"])
    return {
        "edition": ed,
        "sport": sp,
        "event": get_event(ev["id"]),
        "venue": venue,
        "athlete": pair["athlete"],
        "entry": pair["entry"],
        "official": official,
        "slot": get_slot(slot["id"]),
        "assignment": get_assignment(assignment["id"]),
    }


def setup_slot_in_progress(**kwargs) -> dict:
    """`setup_seeded_event_with_staffed_slot`, then walk the clock to the slot's
    start instant and move the slot SCHEDULED -> IN_PROGRESS."""
    ctx = setup_seeded_event_with_staffed_slot(**kwargs)
    set_clock("2026-09-12T09:05:00Z")
    advance_slot(ctx["slot"]["id"], "IN_PROGRESS")
    ctx["slot"] = get_slot(ctx["slot"]["id"])
    ctx["event"] = get_event(ctx["event"]["id"])
    return ctx


def submit_result(entry_id: str, slot_id: str, personnel_id: str, **overrides) -> dict:
    """The officiating person files a mark under their own identity."""
    return get_success_data(
        api_client.create_competition_result(
            competition_result_payload(entry_id, slot_id, personnel_id, **overrides),
            make_sport_official_headers(personnel_id),
        )
    )


def setup_submitted_result(result_overrides=None, **kwargs) -> dict:
    """A SUBMITTED mark filed in a slot that has since been COMPLETED, so that
    verification's "slot must be COMPLETED" precondition already holds.

    Returns the `setup_slot_in_progress` context plus {"result"}.
    """
    ctx = setup_slot_in_progress(**kwargs)
    result = submit_result(
        ctx["entry"]["id"], ctx["slot"]["id"], ctx["official"]["id"],
        **(result_overrides or {}),
    )
    advance_slot(ctx["slot"]["id"], "COMPLETED")
    ctx["slot"] = get_slot(ctx["slot"]["id"])
    ctx["event"] = get_event(ctx["event"]["id"])
    ctx["assignment"] = get_assignment(ctx["assignment"]["id"])
    ctx["result"] = get_result(result["id"])
    return ctx


def verify_result(competition_result_id: str, verifier_user_id=None) -> dict:
    return get_success_data(
        api_client.verify_competition_result(
            competition_result_id,
            make_registration_officer_headers(
                verifier_user_id or REGISTRATION_OFFICER_USER_ID
            ),
        )
    )


def publish_result(competition_result_id: str) -> dict:
    return get_success_data(
        api_client.publish_competition_result(
            competition_result_id,
            make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID),
        )
    )


def setup_record_pending_result(verifier_user_id=None, **kwargs) -> dict:
    """A verified mark sitting in RECORD_PENDING because the event held no
    standing record.  Returns the `setup_submitted_result` context, refreshed."""
    ctx = setup_submitted_result(**kwargs)
    verify_result(ctx["result"]["id"], verifier_user_id)
    ctx["result"] = get_result(ctx["result"]["id"])
    ctx["event"] = get_event(ctx["event"]["id"])
    return ctx


def file_record_claim(
    sport_event_id: str, competition_result_id: str, claimed_by_user_id: str
) -> dict:
    """File a record claim, reading the event's current version for the guard."""
    event = get_event(sport_event_id)
    return get_success_data(
        api_client.create_age_group_record(
            age_group_record_payload(
                sport_event_id, competition_result_id, claimed_by_user_id, event["version"]
            ),
            make_records_ratifier_headers(claimed_by_user_id),
        )
    )


def setup_pending_record_claim(claimed_by_user_id=None, **kwargs) -> dict:
    """A RECORD_PENDING mark with one PENDING_RATIFICATION claim citing it.

    Returns the `setup_record_pending_result` context plus {"record"}.
    """
    claimer = claimed_by_user_id or RECORDS_RATIFIER_USER_ID
    ctx = setup_record_pending_result(**kwargs)
    record = file_record_claim(ctx["event"]["id"], ctx["result"]["id"], claimer)
    ctx["record"] = get_record(record["id"])
    ctx["event"] = get_event(ctx["event"]["id"])
    ctx["claimed_by_user_id"] = claimer
    return ctx


def ratify_record(age_group_record_id: str, ratifier_user_id: str, decision="RATIFY") -> dict:
    return get_success_data(
        api_client.ratify_age_group_record(
            age_group_record_id, {"decision": decision},
            make_records_ratifier_headers(ratifier_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 6 — walking an edition down its own lifecycle
# ---------------------------------------------------------------------------
def close_registration(games_edition_id: str) -> dict:
    """REGISTRATION_OPEN -> REGISTRATION_CLOSED: park the clock on the
    registration deadline and take one checkpoint step."""
    set_clock(EDITION_REGISTRATION_DEADLINE_UTC)
    ops_run(games_edition_id)
    return get_edition(games_edition_id)


def start_competition(games_edition_id: str, start_date=EDITION_START_DATE) -> dict:
    """REGISTRATION_CLOSED -> IN_PROGRESS: one further checkpoint step once the
    clock's date has reached the competition start date."""
    set_clock(f"{start_date}T00:00:00Z")
    ops_run(games_edition_id)
    return get_edition(games_edition_id)


def complete_competition(games_edition_id: str, end_date=EDITION_END_DATE) -> dict:
    """IN_PROGRESS -> COMPLETED: one further checkpoint step once the clock's
    date is past the competition end date."""
    set_clock(f"{end_date}T00:00:00Z")
    ops_run(games_edition_id)
    day_after = f"{end_date[:8]}{int(end_date[8:]) + 1:02d}T00:00:00Z"
    set_clock(day_after)
    ops_run(games_edition_id)
    return get_edition(games_edition_id)


def walk_edition_to_completed(games_edition_id: str) -> dict:
    """Take the three separate checkpoint steps that carry a REGISTRATION_OPEN
    edition to COMPLETED — one advance per checkpoint call, never a cascade."""
    close_registration(games_edition_id)
    start_competition(games_edition_id)
    return complete_competition(games_edition_id)


def finalize_impact(games_edition_id: str) -> dict:
    return get_success_data(
        api_client.finalize_impact(
            games_edition_id, make_sponsor_liaison_headers(SPONSOR_LIAISON_USER_ID)
        )
    )


def check_in(athlete_id: str) -> dict:
    return get_success_data(api_client.check_in_athlete(athlete_id, ADMIN))
