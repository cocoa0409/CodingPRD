"""Composite setup helpers.

Every test starts against an empty database (the runner reboots the server before
each test, resetting the logical clock to its 2026-07-01 default). Each helper
here builds the whole world it needs from PRD-declared endpoints only. Setup calls
use the lenient get_success_data() validator so a broken precondition surfaces as
"Setup failed" rather than a confusing assertion deep inside a test.

Identity threading: after a Member is created, every ownership-gated call in these
helpers uses make_member_headers(member["id"]) — never the shared TEST_USERS
constant.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC, DEFAULT_CHART
from .factories import (
    accept_transfer_payload,
    bank_payload,
    borrow_payload,
    create_guest_certificate_payload,
    create_listing_payload,
    create_member_payload,
    create_reservation_payload,
    create_resort_payload,
    create_transfer_payload,
    create_unit_type_payload,
    create_waitlist_payload,
    generate_statement_payload,
    pay_statement_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: single-call builders ─────────────────────────────────────────

def set_clock(to_iso8601: str) -> None:
    """Set the logical clock (PRD §2.4)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_billing_cycle() -> None:
    """Run the ops/billing cycle at the current clock (PRD §3.10)."""
    get_success_data(api_client.run_billing_cycle(ADMIN))


def new_member(owned_points: int = 5000, **overrides) -> dict:
    return get_success_data(
        api_client.create_member(create_member_payload(owned_points=owned_points, **overrides), ADMIN)
    )


def member_current_bucket(member_id: str) -> dict:
    """The member's initial (current-use-year) bucket (PRD §3.1)."""
    buckets = get_success_data(api_client.list_member_points_buckets(member_id, ADMIN))
    assert buckets, f"member {member_id} has no points buckets"
    return buckets[0]


def bucket_for_year(member_id: str, use_year: int) -> dict:
    """Find the member's bucket for a specific use year (PRD §3.1/§3.2)."""
    buckets = get_success_data(
        api_client.list_member_points_buckets(member_id, ADMIN, params={"use_year": use_year})
    )
    matches = [b for b in buckets if b["use_year"] == use_year]
    assert matches, f"member {member_id} has no bucket for use_year {use_year}"
    return matches[0]


def new_resort(**overrides) -> dict:
    return get_success_data(api_client.create_resort(create_resort_payload(**overrides), ADMIN))


def new_unit_type(resort_id: str, total_units: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit_type(
            resort_id, create_unit_type_payload(total_units=total_units, **overrides), ADMIN
        )
    )


# ─── Read helpers (GET allowed for admin per PRD §2.1) ────────────────────

def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def get_bucket(bucket_id: str) -> dict:
    return get_success_data(api_client.get_points_bucket(bucket_id, ADMIN))


def get_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


def get_waitlist(waitlist_id: str) -> dict:
    return get_success_data(api_client.get_waitlist_entry(waitlist_id, ADMIN))


def get_guest_certificate(reservation_id: str, cert_id: str) -> dict:
    certs = get_success_data(api_client.list_guest_certificates(reservation_id, ADMIN))
    for c in certs:
        if c["id"] == cert_id:
            return c
    raise AssertionError(f"guest certificate {cert_id} not found on reservation {reservation_id}")


# ─── Tier 1: inventory + member world ─────────────────────────────────────

def setup_member_and_unit_type(
    owned_points: int = 5000,
    total_units: int = 1,
    clock: str = CLOCK_DEFAULT_UTC,
    chart: dict = None,
) -> dict:
    """Clock + one member (with initial bucket) + one resort + one unit type.

    Returns {member, bucket, resort, unit_type, member_headers}.
    """
    set_clock(clock)
    member = new_member(owned_points=owned_points)
    bucket = member_current_bucket(member["id"])
    resort = new_resort()
    ut = new_unit_type(resort["id"], total_units=total_units, **(chart or DEFAULT_CHART))
    return {
        "member": member,
        "bucket": bucket,
        "resort": resort,
        "unit_type": ut,
        "member_headers": make_member_headers(member["id"]),
    }


def new_reservation(member_id: str, unit_type_id: str, bucket_id: str, check_in: str, check_out: str) -> dict:
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(member_id, unit_type_id, bucket_id, check_in, check_out),
            make_member_headers(member_id),
        )
    )


def new_waitlist(member_id: str, unit_type_id: str, bucket_id: str, check_in: str, check_out: str) -> dict:
    return get_success_data(
        api_client.create_waitlist_entry(
            create_waitlist_payload(member_id, unit_type_id, bucket_id, check_in, check_out),
            make_member_headers(member_id),
        )
    )


def setup_held_reservation(
    check_in: str,
    check_out: str,
    owned_points: int = 5000,
    total_units: int = 1,
    clock: str = CLOCK_DEFAULT_UTC,
    chart: dict = None,
) -> dict:
    """A world plus one HELD reservation for the member on the unit type.

    Returns {member, bucket, resort, unit_type, member_headers, reservation}.
    """
    world = setup_member_and_unit_type(owned_points, total_units, clock, chart)
    res = new_reservation(
        world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], check_in, check_out
    )
    world["reservation"] = res
    return world


def setup_confirmed_reservation(
    check_in: str,
    check_out: str,
    owned_points: int = 5000,
    total_units: int = 1,
    clock: str = CLOCK_DEFAULT_UTC,
    chart: dict = None,
) -> dict:
    """As setup_held_reservation but the reservation is advanced to CONFIRMED."""
    world = setup_held_reservation(check_in, check_out, owned_points, total_units, clock, chart)
    get_success_data(
        api_client.confirm_reservation(world["reservation"]["id"], world["member_headers"])
    )
    world["reservation"] = get_reservation(world["reservation"]["id"])
    return world


def issue_guest_cert(reservation_id: str, member_id: str, guest_name: str = "Guest G") -> dict:
    return get_success_data(
        api_client.issue_guest_certificate(
            reservation_id, create_guest_certificate_payload(guest_name=guest_name),
            make_member_headers(member_id),
        )
    )


def create_listing(reservation_id: str, member_id: str, listing_type: str = "RENTAL", **overrides) -> dict:
    return get_success_data(
        api_client.create_listing(
            reservation_id, create_listing_payload(listing_type=listing_type, **overrides),
            make_member_headers(member_id),
        )
    )


# ─── Tier 2: statements, aging, suspension ────────────────────────────────

def generate_statement(member_id: str, member_version: int, special_assessment_cents: int = None) -> dict:
    """Generate a member's current-period statement (PRD §3.9)."""
    kwargs = {}
    if special_assessment_cents is not None:
        kwargs["special_assessment_cents"] = special_assessment_cents
    return get_success_data(
        api_client.generate_statement(
            member_id, generate_statement_payload(member_version, **kwargs), ADMIN
        )
    )


def setup_member_with_statement(owned_points: int = 5000, special_assessment_cents: int = None) -> dict:
    """Clock 2026-07-01, a member, and one freshly generated CURRENT/UNPAID statement.

    Returns {member, bucket, statement, member_headers}. The member's version has
    advanced to 2 after generation.
    """
    set_clock(CLOCK_DEFAULT_UTC)
    member = new_member(owned_points=owned_points)
    bucket = member_current_bucket(member["id"])
    statement = generate_statement(member["id"], member["version"], special_assessment_cents)
    return {
        "member": member,
        "bucket": bucket,
        "statement": statement,
        "member_headers": make_member_headers(member["id"]),
    }


def setup_suspended_member(
    owned_points: int = 5000,
    special_assessment_cents: int = None,
    past_due_clock: str = "2026-08-16T00:00:00Z",
) -> dict:
    """Drive a member to SUSPENDED via delinquency (PRD §3.9/§3.10).

    Statement generated at 2026-07-01 (due 2026-07-31); clock advanced past
    due_date + 15-day grace; run_billing_cycle ages the statement PAST_DUE and
    suspends the member. Returns refreshed {member, bucket, statement, member_headers}.
    """
    world = setup_member_with_statement(owned_points, special_assessment_cents)
    set_clock(past_due_clock)
    run_billing_cycle()
    world["member"] = get_member(world["member"]["id"])
    world["statement"] = get_success_data(
        api_client.list_member_statements(world["member"]["id"], ADMIN)
    )[0]
    world["bucket"] = get_bucket(world["bucket"]["id"])
    return world


# ─── Tier 3: transfers ────────────────────────────────────────────────────

def setup_pending_transfer(points: int = 500, owned_points: int = 5000) -> dict:
    """Two ACTIVE members and a PENDING transfer A->B (escrow on A) (PRD §3.8).

    Returns {member_a, member_b, bucket_a, bucket_b, transfer}.
    """
    set_clock(CLOCK_DEFAULT_UTC)
    member_a = new_member(owned_points=owned_points)
    member_b = new_member(owned_points=owned_points)
    bucket_a = member_current_bucket(member_a["id"])
    bucket_b = member_current_bucket(member_b["id"])
    transfer = get_success_data(
        api_client.create_transfer(
            create_transfer_payload(member_a["id"], member_b["id"], points),
            make_member_headers(member_a["id"]),
        )
    )
    return {
        "member_a": member_a,
        "member_b": member_b,
        "bucket_a": bucket_a,
        "bucket_b": bucket_b,
        "transfer": transfer,
    }


# ─── Tier 4: banking / borrowing ──────────────────────────────────────────

def bank(bucket_id: str, member_id: str, points: int) -> dict:
    return get_success_data(
        api_client.bank_points(bucket_id, bank_payload(points), make_member_headers(member_id))
    )


def borrow(bucket_id: str, member_id: str, points: int) -> dict:
    return get_success_data(
        api_client.borrow_points(bucket_id, borrow_payload(points), make_member_headers(member_id))
    )


# ─── Tier 5: cascade scenarios (waitlist + cancel/suspension promotion) ────

def setup_reservation_with_waiting_member(
    held_check_in: str,
    held_check_out: str,
    wait_check_in: str,
    wait_check_out: str,
    clock: str = CLOCK_DEFAULT_UTC,
    owned_points: int = 5000,
    chart: dict = None,
) -> dict:
    """Member A holds a reservation on a total_units=1 unit type; member B has an
    ACTIVE waitlist entry on the same unit type for overlapping-but-fitting dates.

    Used to observe waitlist promotion when A's hold is released (cancel or
    suspension cascade). Returns {member_a, member_b, bucket_a, bucket_b,
    resort, unit_type, reservation_a, waitlist_b}.
    """
    set_clock(clock)
    member_a = new_member(owned_points=owned_points)
    member_b = new_member(owned_points=owned_points)
    bucket_a = member_current_bucket(member_a["id"])
    bucket_b = member_current_bucket(member_b["id"])
    resort = new_resort()
    ut = new_unit_type(resort["id"], total_units=1, **(chart or DEFAULT_CHART))
    reservation_a = new_reservation(member_a["id"], ut["id"], bucket_a["id"], held_check_in, held_check_out)
    waitlist_b = new_waitlist(member_b["id"], ut["id"], bucket_b["id"], wait_check_in, wait_check_out)
    return {
        "member_a": member_a,
        "member_b": member_b,
        "bucket_a": bucket_a,
        "bucket_b": bucket_b,
        "resort": resort,
        "unit_type": ut,
        "reservation_a": reservation_a,
        "waitlist_b": waitlist_b,
    }
