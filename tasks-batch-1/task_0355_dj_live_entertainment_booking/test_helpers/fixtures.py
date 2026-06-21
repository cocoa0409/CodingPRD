"""Composite setup helpers.

These encapsulate the multi-step preambles that the booking lifecycle requires so
tests can focus on assertions. Every setup call uses get_success_data() (the
lenient validator) so a setup failure surfaces as a clear "Setup failed" error.

Identity threading: Performer and Client are entity-backed. After creating one,
ownership-gated calls use make_performer_headers(performer_id) /
make_client_headers(client_id) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_studio_admin_headers,
    make_booking_agent_headers,
    make_performer_headers,
    make_client_headers,
)
from . import factories as F

ADMIN = TEST_USERS["studio_admin_headers"]
AGENT = TEST_USERS["booking_agent_headers"]

DEFAULT_CLOCK = "2026-06-14T00:00:00Z"
DEFAULT_EVENT_START = "2026-08-01T20:00:00Z"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(now_utc=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(now_utc, ADMIN))


# --------------------------------------------------------------------------
# Catalogue primitives
# --------------------------------------------------------------------------
def create_travel_zone(**overrides):
    payload = F.create_travel_zone_payload(**overrides)
    return get_success_data(api_client.create_travel_zone(payload, ADMIN))


def create_home_zone():
    return create_travel_zone(name="Home", base_travel_fee_cents=0,
                              per_mile_fee_cents=0, surge_multiplier_bps=10000)


def create_event_zone():
    """Charged zone: base 10000, per_mile 500, surge 12000 bps."""
    return create_travel_zone(name="Event", base_travel_fee_cents=10000,
                              per_mile_fee_cents=500, surge_multiplier_bps=12000)


def create_package(**overrides):
    payload = F.create_package_payload(**overrides)
    return get_success_data(api_client.create_package(payload, ADMIN))


def add_equipment(package_id, **overrides):
    payload = F.create_equipment_payload(**overrides)
    return get_success_data(api_client.add_equipment(package_id, payload, ADMIN))


def create_performer(home_zone_id, **overrides):
    payload = F.create_performer_payload(home_zone_id=home_zone_id, **overrides)
    return get_success_data(api_client.create_performer(payload, ADMIN))


def create_client(**overrides):
    payload = F.create_client_payload(**overrides)
    return get_success_data(api_client.create_client(payload, AGENT))


def create_blackout(performer_id, **overrides):
    payload = F.create_blackout_payload(**overrides)
    return get_success_data(api_client.create_blackout(performer_id, payload, ADMIN))


# --------------------------------------------------------------------------
# Catalogue bundles
# --------------------------------------------------------------------------
def setup_home_catalogue(with_equipment=False):
    """Clock + home zone + STANDARD package (optionally two equipment lines) +
    performer + client. Returns dict of ids/objects."""
    set_clock()
    zhome = create_home_zone()
    pkg = create_package()
    if with_equipment:
        add_equipment(pkg["id"], category="SOUND", label="PA", unit_fee_cents=30000)
        add_equipment(pkg["id"], category="LIGHTING", label="Rig", unit_fee_cents=20000)
    perf = create_performer(zhome["id"])
    cli = create_client()
    return {
        "zhome": zhome, "pkg": pkg, "perf": perf, "cli": cli,
        "zhome_id": zhome["id"], "pkg_id": pkg["id"],
        "perf_id": perf["id"], "cli_id": cli["id"],
    }


def setup_charged_catalogue():
    """Clock + home zone + event (charged) zone + STANDARD package with two
    equipment lines + performer (home zone) + client. The canonical 324000-quote
    scenario when booked into the event zone with 20 miles."""
    set_clock()
    zhome = create_home_zone()
    zevent = create_event_zone()
    pkg = create_package()
    add_equipment(pkg["id"], category="SOUND", label="PA", unit_fee_cents=30000)
    add_equipment(pkg["id"], category="LIGHTING", label="Rig", unit_fee_cents=20000)
    perf = create_performer(zhome["id"])
    cli = create_client()
    return {
        "zhome": zhome, "zevent": zevent, "pkg": pkg, "perf": perf, "cli": cli,
        "zhome_id": zhome["id"], "zevent_id": zevent["id"], "pkg_id": pkg["id"],
        "perf_id": perf["id"], "cli_id": cli["id"],
    }


# --------------------------------------------------------------------------
# Booking creation + lifecycle progression
# --------------------------------------------------------------------------
def create_booking(cat, *, event_zone_id=None, miles=0, **overrides):
    zone = event_zone_id or cat["zhome_id"]
    payload = F.create_booking_payload(
        client_id=cat["cli_id"], performer_id=cat["perf_id"],
        package_id=cat["pkg_id"], event_zone_id=zone,
        event_miles_from_home=miles, **overrides,
    )
    return get_success_data(api_client.create_booking(payload, AGENT))


def hold_booking(booking_id):
    return get_success_data(api_client.hold_booking(booking_id, AGENT))


def create_held_booking(cat=None, *, event_zone_id=None, miles=0, **booking_overrides):
    """Catalogue (home) + booking + hold. Returns (cat, held_booking)."""
    if cat is None:
        cat = setup_home_catalogue()
    bk = create_booking(cat, event_zone_id=event_zone_id, miles=miles, **booking_overrides)
    held = hold_booking(bk["id"])
    return cat, held


def issue_contract(booking_id, expected_version):
    return get_success_data(
        api_client.issue_contract(booking_id, expected_version, AGENT)
    )


def get_first_contract_id(booking_id):
    data = get_success_data(api_client.list_contracts(booking_id, AGENT))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]["id"]


def sign_contract(contract_id, client_id):
    return get_success_data(
        api_client.sign_contract(contract_id, make_client_headers(client_id))
    )


def create_contract_sent_booking(cat=None, *, event_zone_id=None, miles=0, **booking_overrides):
    """Booking driven to CONTRACT_SENT with one ISSUED contract (revision 1).
    Returns (cat, booking, contract_id, version_at_contract_sent)."""
    cat, held = create_held_booking(cat, event_zone_id=event_zone_id, miles=miles, **booking_overrides)
    bk_id = held["id"]
    issued = issue_contract(bk_id, held["version"])
    ct_id = get_first_contract_id(bk_id)
    return cat, issued, ct_id


def create_signed_contract_booking(cat=None, *, event_zone_id=None, miles=0, **booking_overrides):
    """CONTRACT_SENT booking whose contract is SIGNED (not yet confirmed).
    Returns (cat, booking, contract_id)."""
    cat, bk, ct_id = create_contract_sent_booking(cat, event_zone_id=event_zone_id, miles=miles, **booking_overrides)
    sign_contract(ct_id, cat["cli_id"])
    return cat, bk, ct_id


def create_payment(booking_id, *, kind="DEPOSIT", amount_cents, refund_destination=None):
    payload = F.create_payment_payload(
        booking_id=booking_id, kind=kind, amount_cents=amount_cents,
    )
    if refund_destination is not None:
        payload["refund_destination"] = refund_destination
    return get_success_data(api_client.create_payment(payload, AGENT))


def capture_payment(payment_id):
    return get_success_data(api_client.capture_payment(payment_id, AGENT))


def create_confirmed_booking(cat=None, *, deposit_cents=62500, refund_destination=None,
                             event_zone_id=None, miles=0, **booking_overrides):
    """CONTRACT_SENT (signed) booking + captured deposit that meets the threshold,
    auto-advancing the booking to CONFIRMED.

    deposit_cents defaults to 62500 (the deposit on a 250000 home-zone quote);
    for the 324000 charged scenario pass deposit_cents=81000.
    Returns (cat, confirmed_booking, contract_id, deposit_payment).
    """
    cat, bk, ct_id = create_signed_contract_booking(
        cat, event_zone_id=event_zone_id, miles=miles, **booking_overrides
    )
    dep = create_payment(bk["id"], kind="DEPOSIT", amount_cents=deposit_cents,
                         refund_destination=refund_destination)
    capture_payment(dep["id"])
    confirmed = get_success_data(api_client.get_booking(bk["id"], AGENT))
    return cat, confirmed, ct_id, dep


def advance_to_performed(booking_id, *, actual_set_minutes=120,
                         event_start_clock="2026-08-01T20:00:00Z"):
    """From CONFIRMED: move clock to event start, start the set, complete it.
    Returns the PERFORMED booking."""
    set_clock(event_start_clock)
    get_success_data(api_client.start_set(booking_id, AGENT))
    return get_success_data(api_client.complete_set(booking_id, actual_set_minutes, AGENT))


def create_performed_booking(cat=None, *, deposit_cents=62500, actual_set_minutes=120,
                             event_start_clock="2026-08-01T20:00:00Z", **booking_overrides):
    """Full lifecycle through PERFORMED. Returns (cat, performed_booking)."""
    cat, confirmed, ct_id, dep = create_confirmed_booking(cat, deposit_cents=deposit_cents, **booking_overrides)
    performed = advance_to_performed(
        confirmed["id"], actual_set_minutes=actual_set_minutes,
        event_start_clock=event_start_clock,
    )
    return cat, performed


def create_settled_booking(cat=None, *, quote_cents=250000, deposit_cents=62500,
                           actual_set_minutes=120, **booking_overrides):
    """Full lifecycle through SETTLED: pay deposit + balance, perform, settle.
    Returns (cat, settled_booking, [deposit_payment, balance_payment])."""
    cat, bk, ct_id = create_signed_contract_booking(cat, **booking_overrides)
    dep = create_payment(bk["id"], kind="DEPOSIT", amount_cents=deposit_cents)
    capture_payment(dep["id"])
    balance = quote_cents - deposit_cents
    bal = create_payment(bk["id"], kind="BALANCE", amount_cents=balance)
    capture_payment(bal["id"])
    performed = advance_to_performed(bk["id"], actual_set_minutes=actual_set_minutes)
    settled = get_success_data(api_client.settle_booking(performed["id"], AGENT))
    return cat, settled, [dep, bal]


# --------------------------------------------------------------------------
# Backup assignment helpers
# --------------------------------------------------------------------------
def offer_backup(booking_id, candidate_performer_id, rank=1):
    payload = F.create_backup_assignment_payload(
        candidate_performer_id=candidate_performer_id, rank=rank,
    )
    return get_success_data(api_client.create_backup_assignment(booking_id, payload, AGENT))


def accept_backup(backup_assignment_id, candidate_performer_id):
    return get_success_data(
        api_client.accept_backup(backup_assignment_id, make_performer_headers(candidate_performer_id))
    )


def setup_confirmed_with_accepted_backup(cat=None, *, deposit_cents=62500):
    """CONFIRMED booking with a primary performer plus one ACCEPTED backup
    (rank 1, distinct backup performer). Returns dict with keys:
    cat, booking, primary_id, backup_id, backup_assignment, version_pre_promote.
    """
    if cat is None:
        cat = setup_home_catalogue()
        # add a second (backup) performer to the catalogue
        backup = create_performer(cat["zhome_id"], stage_name="Backup",
                                  base_set_rate_cents=180000)
        cat["backup"] = backup
        cat["backup_id"] = backup["id"]
    cat, confirmed, ct_id, dep = create_confirmed_booking(cat, deposit_cents=deposit_cents)
    ba = offer_backup(confirmed["id"], cat["backup_id"], rank=1)
    accept_backup(ba["id"], cat["backup_id"])
    pre = get_success_data(api_client.get_booking(confirmed["id"], AGENT))
    return {
        "cat": cat, "booking": confirmed, "primary_id": cat["perf_id"],
        "backup_id": cat["backup_id"], "backup_assignment": ba,
        "version_pre_promote": pre["version"],
    }


def setup_confirmed_with_two_accepted_backups(cat=None, *, deposit_cents=62500):
    """CONFIRMED booking with two ACCEPTED backups (rank 1 = b1, rank 2 = b2).
    Returns dict with cat, booking, primary_id, b1_id, b2_id, ba1, ba2,
    version_pre_promote.
    """
    if cat is None:
        cat = setup_home_catalogue()
    b1 = create_performer(cat["zhome_id"], stage_name="B1", base_set_rate_cents=180000)
    b2 = create_performer(cat["zhome_id"], stage_name="B2", base_set_rate_cents=170000)
    cat, confirmed, ct_id, dep = create_confirmed_booking(cat, deposit_cents=deposit_cents)
    ba1 = offer_backup(confirmed["id"], b1["id"], rank=1)
    accept_backup(ba1["id"], b1["id"])
    ba2 = offer_backup(confirmed["id"], b2["id"], rank=2)
    accept_backup(ba2["id"], b2["id"])
    pre = get_success_data(api_client.get_booking(confirmed["id"], AGENT))
    return {
        "cat": cat, "booking": confirmed, "primary_id": cat["perf_id"],
        "b1_id": b1["id"], "b2_id": b2["id"], "ba1": ba1, "ba2": ba2,
        "version_pre_promote": pre["version"],
    }


# --------------------------------------------------------------------------
# Song request helpers
# --------------------------------------------------------------------------
def add_song_request(booking_id, client_id, *, title, artist=None,
                     list_type="REQUEST", priority=None):
    payload = F.create_song_request_payload(title=title, list_type=list_type)
    if artist is not None:
        payload["artist"] = artist
    if priority is not None:
        payload["priority"] = priority
    return get_success_data(
        api_client.create_song_request(booking_id, payload, make_client_headers(client_id))
    )
