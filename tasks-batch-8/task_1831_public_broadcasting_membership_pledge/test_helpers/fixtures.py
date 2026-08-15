"""Composite setup helpers for the membership & pledge drive API tests.

The logical clock starts at 2026-08-01T00:00:00Z (PRD §2.8), so a drive whose
window opens at 2026-08-01 can go live immediately after scheduling. Every
helper builds its preconditions from scratch through PRD-declared endpoints;
setup calls use get_success_data so a failed precondition surfaces as a clear
setup error rather than a confusing assertion failure.
"""
from datetime import datetime

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LAPSED_CLOCK_ISO
from .factories import (
    DEFAULTS,
    create_break_payload,
    create_challenge_payload,
    create_donor_payload,
    create_drive_payload,
    create_level_payload,
    create_lot_payload,
    create_membership_payload,
    create_nffs_report_payload,
    create_payment_payload,
    create_pledge_payload,
    create_premium_payload,
    create_reason_payload,
    create_reservation_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["station_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
VOLUNTEER = TEST_USERS["phone_volunteer_headers"]


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp from the API into a datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Single-resource creators ─────────────────────────

def create_level(**overrides) -> dict:
    return get_success_data(api_client.create_membership_level(
        create_level_payload(**overrides), ADMIN))


def create_premium(**overrides) -> dict:
    return get_success_data(api_client.create_premium(
        create_premium_payload(**overrides), ADMIN))


def receive_lot(premium_id, **overrides) -> dict:
    return get_success_data(api_client.create_lot(
        premium_id, create_lot_payload(**overrides), COORD))


def create_donor(**overrides) -> dict:
    return get_success_data(api_client.create_donor(
        create_donor_payload(**overrides), COORD))


def open_membership(donor_id, level_code=DEFAULTS["LEVEL_CODE"], **overrides) -> dict:
    return get_success_data(api_client.create_membership(
        create_membership_payload(donor_id, level_code, **overrides), COORD))


def create_drive(**overrides) -> dict:
    return get_success_data(api_client.create_drive(
        create_drive_payload(**overrides), ADMIN))


def get_drive(drive_id) -> dict:
    return get_success_data(api_client.get_drive(drive_id, ADMIN))


def add_break(drive_id, expected_drive_version, **overrides) -> dict:
    return get_success_data(api_client.create_break(
        drive_id, create_break_payload(expected_drive_version, **overrides), ADMIN))


def create_challenge(drive_id, **overrides) -> dict:
    return get_success_data(api_client.create_matching_challenge(
        drive_id, create_challenge_payload(**overrides), ADMIN))


def advance_clock(to_iso8601) -> None:
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: state progression ────────────────────────

def schedule_drive(drive_id) -> dict:
    return get_success_data(api_client.schedule_drive(drive_id, ADMIN))


def go_live_drive(drive_id) -> dict:
    return get_success_data(api_client.go_live_drive(drive_id, ADMIN))


def close_drive(drive_id) -> dict:
    return get_success_data(api_client.close_drive(drive_id, ADMIN))


def setup_on_air_drive(break_overrides=None, **drive_overrides) -> dict:
    """Create a drive, add one break, schedule it, and move it ON_AIR.

    Returns the freshly-read drive (status ON_AIR, current version).
    """
    drive = create_drive(**drive_overrides)
    add_break(drive["id"], drive["version"], **(break_overrides or {}))
    schedule_drive(drive["id"])
    go_live_drive(drive["id"])
    return get_drive(drive["id"])


# ─── Tier 2: entity hierarchy ─────────────────────────

def setup_donor_membership(level_code=DEFAULTS["LEVEL_CODE"],
                           sustainer=False, **donor_overrides):
    """Register a donor and open a membership at the given level."""
    donor = create_donor(**donor_overrides)
    membership = open_membership(donor["id"], level_code, sustainer=sustainer)
    return donor, membership


def setup_station(level_overrides=None, drive_overrides=None,
                  break_overrides=None, with_premium=False,
                  premium_overrides=None, lot_overrides=None) -> dict:
    """Level + donor + membership + ON_AIR drive; optionally premium + lot.

    Returns a dict with keys: level, donor, membership, drive, premium, lot.
    """
    level = create_level(**(level_overrides or {}))
    donor, membership = setup_donor_membership(level["code"])
    drive = setup_on_air_drive(break_overrides=break_overrides,
                               **(drive_overrides or {}))
    premium = lot = None
    if with_premium:
        premium = create_premium(
            membership_level_code=level["code"], **(premium_overrides or {}))
        lot = receive_lot(premium["id"], **(lot_overrides or {}))
    return {
        "level": level,
        "donor": donor,
        "membership": membership,
        "drive": drive,
        "premium": premium,
        "lot": lot,
    }


# ─── Tier 2b: station with a matching challenge ───────

def setup_station_with_challenge(level_overrides=None, drive_overrides=None,
                                 sponsor_name="Acme Corp", goal_cents=10000,
                                 match_cents=50000) -> dict:
    """Level + donor + membership + ON_AIR drive carrying one OPEN challenge.

    The challenge is created while the drive is still DRAFT (before schedule
    and go-live). Returns the station dict plus a "challenge" key.
    """
    level = create_level(**(level_overrides or {}))
    donor, membership = setup_donor_membership(level["code"])
    drive = create_drive(**(drive_overrides or {}))
    add_break(drive["id"], drive["version"])
    challenge = create_challenge(drive["id"], sponsor_name=sponsor_name,
                                 goal_cents=goal_cents, match_cents=match_cents)
    schedule_drive(drive["id"])
    go_live_drive(drive["id"])
    return {
        "level": level,
        "donor": donor,
        "membership": membership,
        "drive": get_drive(drive["id"]),
        "premium": None,
        "lot": None,
        "challenge": challenge,
    }


# ─── Tier 3: pledge lifecycle shortcuts ───────────────

def capture_pledge(donor_id, membership_id, drive_id, **overrides) -> dict:
    """Capture a pledge as the phone volunteer. Returns the created pledge."""
    return get_success_data(api_client.create_pledge(
        create_pledge_payload(donor_id, membership_id, drive_id, **overrides),
        VOLUNTEER))


def get_pledge(pledge_id) -> dict:
    return get_success_data(api_client.get_pledge(pledge_id, COORD))


def post_payment_ok(pledge, amount_cents, expected_pledge_version=None) -> dict:
    """Post a payment expected to succeed. Returns the updated pledge."""
    version = pledge["version"] if expected_pledge_version is None else expected_pledge_version
    return get_success_data(api_client.post_payment(
        pledge["id"], create_payment_payload(amount_cents, version), VOLUNTEER))


def pay_in_full(pledge) -> dict:
    """Post a payment covering the pledge's full amount. Returns the pledge."""
    return post_payment_ok(pledge, pledge["amount_cents"])


def capture_and_pay(donor_id, membership_id, drive_id, **overrides) -> dict:
    """Capture a ONE_TIME pledge and pay it in full. Returns the paid pledge."""
    pledge = capture_pledge(donor_id, membership_id, drive_id, **overrides)
    return pay_in_full(pledge)


def get_lot_of_premium(premium_id) -> dict:
    """Read back the single lot of a premium (list endpoint, first row)."""
    lots = get_success_data(api_client.list_lots(premium_id, COORD))
    assert isinstance(lots, list) and len(lots) == 1, (
        f"expected exactly one lot for premium {premium_id}, got {lots!r}")
    return lots[0]


def get_pledge_reservation(pledge_id) -> dict:
    """Read back the single reservation of a pledge (list endpoint, first row)."""
    reservations = get_success_data(
        api_client.list_pledge_reservations(pledge_id, COORD))
    assert isinstance(reservations, list) and len(reservations) == 1, (
        f"expected exactly one reservation for pledge {pledge_id}, "
        f"got {reservations!r}")
    return reservations[0]


# ─── Tier 4: lapsed-member cycle ──────────────────────

def setup_lapsed_membership(payment_amount=6000) -> dict:
    """Donor + membership paid current through 2027-08-01, then the clock is
    advanced past period end + 30 days so the membership is LAPSED and the
    donor's lapse_count is 1. The drive remains ON_AIR.

    Returns a dict with keys: station fields plus pledge (the paid pledge),
    membership, donor (re-read after the clock advance).
    """
    station = setup_station()
    pledge = capture_and_pay(
        station["donor"]["id"], station["membership"]["id"],
        station["drive"]["id"], amount_cents=payment_amount)
    advance_clock(LAPSED_CLOCK_ISO)
    membership = get_success_data(
        api_client.get_membership(station["membership"]["id"], COORD))
    donor = get_success_data(
        api_client.get_donor(station["donor"]["id"], COORD))
    station.update({"pledge": pledge, "membership": membership, "donor": donor})
    return station


# ─── Tier 5: reporting scenarios ──────────────────────

def setup_nffs_mixed_pledges(drafter_headers) -> dict:
    """FY2026 drive with one PLEDGED premium pledge (12000, MUG FMV 2500,
    RESERVED) and one fully PAID plain pledge (20000), plus a drafted NFFS
    report for FY 2026.

    PROVISIONAL membership revenue is 12000 - 2500 + 20000 = 29500;
    FINAL membership revenue is 20000 (the still-PLEDGED pledge counts zero).
    """
    station = setup_station(with_premium=True,
                            lot_overrides={"total_qty": 25})
    donor2, membership2 = setup_donor_membership(station["level"]["code"])
    pledged_premium = capture_pledge(
        station["donor"]["id"], station["membership"]["id"],
        station["drive"]["id"], amount_cents=12000,
        premium_id=station["premium"]["id"])
    paid_plain = capture_and_pay(
        donor2["id"], membership2["id"], station["drive"]["id"],
        channel="WEB", amount_cents=20000)
    report = get_success_data(api_client.create_nffs_report(
        create_nffs_report_payload(2026), drafter_headers))
    station.update({
        "donor2": donor2,
        "membership2": membership2,
        "pledged_premium_pledge": pledged_premium,
        "paid_plain_pledge": paid_plain,
        "report": report,
    })
    return station


def write_off_pledge_ok(pledge_id, reason="no response after 3 follow-up contacts") -> dict:
    return get_success_data(api_client.write_off_pledge(
        pledge_id, create_reason_payload(reason), COORD))


def decline_pledge_ok(pledge_id, reason="donor disputed charge") -> dict:
    return get_success_data(api_client.decline_pledge(
        pledge_id, create_reason_payload(reason), VOLUNTEER))


def reserve_premium_ok(pledge_id, quantity=1) -> dict:
    return get_success_data(api_client.create_premium_reservation(
        pledge_id, create_reservation_payload(quantity), COORD))
